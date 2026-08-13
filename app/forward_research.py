from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation import (
    EvidenceEvaluator,
    EvaluationInput,
    EvaluationPolicy,
    ExecutionComparison,
    ForecastOutcome,
    NavObservation,
    TradeOutcome,
)
from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardForecastRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.models import Experiment, Strategy, StrategyVersion

ZERO = Decimal("0")
PNL_TOLERANCE = Decimal("0.000001")
DECIMAL_POLICY_FIELDS = {
    "max_drawdown_pct",
    "min_profit_factor",
    "max_top3_profit_concentration",
    "cost_stress_multiplier",
    "min_shadow_fill_ratio",
    "max_shadow_p90_price_divergence_bps",
    "max_prediction_calibration_error",
}


class ForwardResearchError(ValueError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _policy_json(policy: EvaluationPolicy) -> str:
    policy.validate()
    return _json(asdict(policy))


def policy_from_json(payload: str) -> EvaluationPolicy:
    try:
        values = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ForwardResearchError("stored evaluation policy is invalid JSON") from exc
    if not isinstance(values, dict):
        raise ForwardResearchError("stored evaluation policy must be an object")
    for field in DECIMAL_POLICY_FIELDS:
        if field in values:
            values[field] = Decimal(str(values[field]))
    try:
        policy = EvaluationPolicy(**values)
        policy.validate()
        return policy
    except (TypeError, ValueError) as exc:
        raise ForwardResearchError(f"stored evaluation policy is invalid: {exc}") from exc


def _registered_version(db: Session, strategy_slug: str, version_name: str) -> tuple[Strategy, StrategyVersion]:
    strategy = db.scalar(select(Strategy).where(Strategy.slug == strategy_slug))
    if strategy is None:
        raise ForwardResearchError("strategy must be registered before a forward study starts")
    version = db.scalar(
        select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy.id,
            StrategyVersion.version == version_name,
        )
    )
    if version is None:
        raise ForwardResearchError("strategy version must be registered before a forward study starts")
    if not version.immutable:
        raise ForwardResearchError("forward studies require an immutable strategy version")
    return strategy, version


def _registered_experiment(db: Session, experiment_id: str, strategy_version_id: str) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise ForwardResearchError("experiment must be registered before a forward study starts")
    if experiment.strategy_version_id != strategy_version_id:
        raise ForwardResearchError("experiment does not belong to the requested strategy version")
    if experiment.status not in {"registered", "running"}:
        raise ForwardResearchError("experiment is not eligible for forward research")
    return experiment


def _active(study: ForwardStudy) -> None:
    if study.status != "active":
        raise ForwardResearchError(f"forward study is not active: {study.status}")


def _same_decimal(left: Decimal, right: Decimal) -> bool:
    return Decimal(left) == Decimal(right)


class ForwardResearchService:
    @staticmethod
    def create_study(
        db: Session,
        *,
        external_id: str,
        strategy_slug: str,
        strategy_version: str,
        experiment_id: str,
        family: str,
        venue: str,
        instrument: str,
        initial_capital_usd: Decimal,
        evaluation_policy: EvaluationPolicy,
        study_config: dict[str, Any],
        started_at: datetime,
    ) -> ForwardStudy:
        if not external_id.strip() or not family.strip() or not venue.strip() or not instrument.strip():
            raise ForwardResearchError("study identity/family/venue/instrument are required")
        if initial_capital_usd <= ZERO:
            raise ForwardResearchError("initial study capital must be positive")
        existing = db.scalar(select(ForwardStudy).where(ForwardStudy.external_id == external_id))
        if existing is not None:
            if existing.strategy_version_id != _registered_version(db, strategy_slug, strategy_version)[1].id:
                raise ForwardResearchError("external study id already belongs to a different strategy version")
            return existing
        _, version = _registered_version(db, strategy_slug, strategy_version)
        _registered_experiment(db, experiment_id, version.id)
        study = ForwardStudy(
            external_id=external_id,
            strategy_version_id=version.id,
            experiment_id=experiment_id,
            family=family,
            venue=venue,
            instrument=instrument,
            initial_capital_usd=initial_capital_usd,
            evaluation_policy_json=_policy_json(evaluation_policy),
            study_config_json=_json(study_config),
            started_at=_aware(started_at),
            status="active",
        )
        db.add(study)
        db.commit()
        db.refresh(study)
        return study

    @staticmethod
    def get_study(db: Session, study_id: str) -> ForwardStudy:
        study = db.get(ForwardStudy, study_id)
        if study is None:
            raise ForwardResearchError("forward study not found")
        return study

    @staticmethod
    def record_nav(
        db: Session,
        *,
        study_id: str,
        observed_at: datetime,
        nav_usd: Decimal,
        source: str = "forward-runner",
    ) -> ForwardNavObservation:
        study = ForwardResearchService.get_study(db, study_id)
        _active(study)
        observed_at = _aware(observed_at)
        if observed_at < _aware(study.started_at):
            raise ForwardResearchError("NAV observation predates study start")
        if nav_usd <= ZERO:
            raise ForwardResearchError("NAV must be positive")
        existing = db.scalar(
            select(ForwardNavObservation).where(
                ForwardNavObservation.study_id == study_id,
                ForwardNavObservation.observed_at == observed_at,
            )
        )
        if existing is not None:
            if not _same_decimal(existing.nav_usd, nav_usd):
                raise ForwardResearchError("conflicting NAV observation for the same timestamp")
            return existing
        row = ForwardNavObservation(study_id=study_id, observed_at=observed_at, nav_usd=nav_usd, source=source)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def record_trade(
        db: Session,
        *,
        study_id: str,
        external_key: str,
        opened_at: datetime,
        closed_at: datetime,
        gross_pnl_usd: Decimal,
        net_pnl_usd: Decimal,
        fees_usd: Decimal,
        slippage_usd: Decimal,
        allocated_capital_usd: Decimal,
        planned_loss_usd: Decimal,
        metadata: dict[str, Any] | None = None,
    ) -> ForwardTradeRecord:
        study = ForwardResearchService.get_study(db, study_id)
        _active(study)
        if not external_key.strip():
            raise ForwardResearchError("trade external key is required")
        opened_at, closed_at = _aware(opened_at), _aware(closed_at)
        if opened_at < _aware(study.started_at) or closed_at < opened_at:
            raise ForwardResearchError("trade timestamps are outside valid forward chronology")
        if fees_usd < ZERO or slippage_usd < ZERO:
            raise ForwardResearchError("trade costs cannot be negative")
        if allocated_capital_usd <= ZERO or planned_loss_usd <= ZERO or planned_loss_usd > allocated_capital_usd:
            raise ForwardResearchError("trade capital/planned loss is invalid")
        if abs(net_pnl_usd - (gross_pnl_usd - fees_usd - slippage_usd)) > PNL_TOLERANCE:
            raise ForwardResearchError("trade net PnL does not reconcile")
        existing = db.scalar(
            select(ForwardTradeRecord).where(
                ForwardTradeRecord.study_id == study_id,
                ForwardTradeRecord.external_key == external_key,
            )
        )
        if existing is not None:
            if not _same_decimal(existing.net_pnl_usd, net_pnl_usd) or _aware(existing.closed_at) != closed_at:
                raise ForwardResearchError("conflicting retry for existing trade key")
            return existing
        row = ForwardTradeRecord(
            study_id=study_id,
            external_key=external_key,
            opened_at=opened_at,
            closed_at=closed_at,
            gross_pnl_usd=gross_pnl_usd,
            net_pnl_usd=net_pnl_usd,
            fees_usd=fees_usd,
            slippage_usd=slippage_usd,
            allocated_capital_usd=allocated_capital_usd,
            planned_loss_usd=planned_loss_usd,
            metadata_json=_json(metadata or {}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def record_execution(
        db: Session,
        *,
        study_id: str,
        external_key: str,
        observed_at: datetime,
        side: str,
        intended_quantity: Decimal,
        paper_filled_quantity: Decimal,
        shadow_filled_quantity: Decimal,
        paper_average_price: Decimal | None,
        shadow_average_price: Decimal | None,
        paper_cost_usd: Decimal = ZERO,
        shadow_cost_usd: Decimal = ZERO,
        trade_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ForwardExecutionRecord:
        study = ForwardResearchService.get_study(db, study_id)
        _active(study)
        observed_at = _aware(observed_at)
        if observed_at < _aware(study.started_at):
            raise ForwardResearchError("execution observation predates study start")
        if side not in {"buy", "sell"} or not external_key.strip():
            raise ForwardResearchError("execution side/key is invalid")
        if intended_quantity <= ZERO or paper_filled_quantity < ZERO or shadow_filled_quantity < ZERO:
            raise ForwardResearchError("execution quantities are invalid")
        if paper_filled_quantity > intended_quantity or shadow_filled_quantity > intended_quantity:
            raise ForwardResearchError("execution fill cannot exceed intended quantity")
        if paper_average_price is not None and paper_average_price <= ZERO:
            raise ForwardResearchError("paper execution price must be positive")
        if shadow_average_price is not None and shadow_average_price <= ZERO:
            raise ForwardResearchError("shadow execution price must be positive")
        if paper_cost_usd < ZERO or shadow_cost_usd < ZERO:
            raise ForwardResearchError("execution costs cannot be negative")
        if trade_id is not None:
            trade = db.get(ForwardTradeRecord, trade_id)
            if trade is None or trade.study_id != study_id:
                raise ForwardResearchError("execution trade link is invalid")
        existing = db.scalar(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key == external_key,
            )
        )
        if existing is not None:
            return existing
        row = ForwardExecutionRecord(
            study_id=study_id,
            trade_id=trade_id,
            external_key=external_key,
            observed_at=observed_at,
            side=side,
            intended_quantity=intended_quantity,
            paper_filled_quantity=paper_filled_quantity,
            shadow_filled_quantity=shadow_filled_quantity,
            paper_average_price=paper_average_price,
            shadow_average_price=shadow_average_price,
            paper_cost_usd=paper_cost_usd,
            shadow_cost_usd=shadow_cost_usd,
            metadata_json=_json(metadata or {}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def record_forecast(
        db: Session,
        *,
        study_id: str,
        external_key: str,
        resolved_at: datetime,
        probability: Decimal,
        outcome: int,
        market_probability: Decimal | None,
        metadata: dict[str, Any] | None = None,
    ) -> ForwardForecastRecord:
        study = ForwardResearchService.get_study(db, study_id)
        _active(study)
        resolved_at = _aware(resolved_at)
        if resolved_at < _aware(study.started_at):
            raise ForwardResearchError("forecast resolution predates study start")
        if not external_key.strip() or probability < ZERO or probability > Decimal("1") or outcome not in {0, 1}:
            raise ForwardResearchError("forecast key/probability/outcome is invalid")
        if market_probability is not None and (market_probability < ZERO or market_probability > Decimal("1")):
            raise ForwardResearchError("market probability is invalid")
        existing = db.scalar(
            select(ForwardForecastRecord).where(
                ForwardForecastRecord.study_id == study_id,
                ForwardForecastRecord.external_key == external_key,
            )
        )
        if existing is not None:
            return existing
        row = ForwardForecastRecord(
            study_id=study_id,
            external_key=external_key,
            resolved_at=resolved_at,
            probability=probability,
            outcome=outcome,
            market_probability=market_probability,
            metadata_json=_json(metadata or {}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def record_incident(
        db: Session,
        *,
        study_id: str,
        external_key: str,
        severity: str,
        code: str,
        message: str,
        opened_at: datetime,
        data_integrity: bool = False,
    ) -> ForwardStudyIncident:
        study = ForwardResearchService.get_study(db, study_id)
        _active(study)
        if severity not in {"info", "warning", "error", "critical"}:
            raise ForwardResearchError("invalid incident severity")
        if not external_key.strip() or not code.strip() or not message.strip():
            raise ForwardResearchError("incident key/code/message are required")
        opened_at = _aware(opened_at)
        if opened_at < _aware(study.started_at):
            raise ForwardResearchError("incident predates study start")
        existing = db.scalar(
            select(ForwardStudyIncident).where(
                ForwardStudyIncident.study_id == study_id,
                ForwardStudyIncident.external_key == external_key,
            )
        )
        if existing is not None:
            return existing
        row = ForwardStudyIncident(
            study_id=study_id,
            external_key=external_key,
            severity=severity,
            code=code,
            message=message,
            data_integrity=data_integrity,
            opened_at=opened_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def resolve_incident(db: Session, *, study_id: str, external_key: str, resolved_at: datetime) -> ForwardStudyIncident:
        row = db.scalar(
            select(ForwardStudyIncident).where(
                ForwardStudyIncident.study_id == study_id,
                ForwardStudyIncident.external_key == external_key,
            )
        )
        if row is None:
            raise ForwardResearchError("incident not found")
        resolved_at = _aware(resolved_at)
        if resolved_at < _aware(row.opened_at):
            raise ForwardResearchError("incident resolution predates incident")
        row.resolved = True
        row.resolved_at = resolved_at
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def build_evaluation_input(db: Session, *, study_id: str, evaluated_at: datetime) -> tuple[EvaluationInput, StrategyVersion]:
        study = ForwardResearchService.get_study(db, study_id)
        evaluated_at = _aware(evaluated_at)
        if evaluated_at < _aware(study.started_at):
            raise ForwardResearchError("evaluation cutoff predates study start")
        version = db.get(StrategyVersion, study.strategy_version_id)
        if version is None or not version.immutable:
            raise ForwardResearchError("study strategy version is missing or mutable")
        strategy = db.get(Strategy, version.strategy_id)
        if strategy is None:
            raise ForwardResearchError("study strategy is missing")

        nav_rows = db.scalars(
            select(ForwardNavObservation)
            .where(ForwardNavObservation.study_id == study_id, ForwardNavObservation.observed_at <= evaluated_at)
            .order_by(ForwardNavObservation.observed_at.asc())
        ).all()
        trades = db.scalars(
            select(ForwardTradeRecord)
            .where(ForwardTradeRecord.study_id == study_id, ForwardTradeRecord.closed_at <= evaluated_at)
            .order_by(ForwardTradeRecord.closed_at.asc())
        ).all()
        executions = db.scalars(
            select(ForwardExecutionRecord)
            .where(ForwardExecutionRecord.study_id == study_id, ForwardExecutionRecord.observed_at <= evaluated_at)
            .order_by(ForwardExecutionRecord.observed_at.asc())
        ).all()
        forecasts = db.scalars(
            select(ForwardForecastRecord)
            .where(ForwardForecastRecord.study_id == study_id, ForwardForecastRecord.resolved_at <= evaluated_at)
            .order_by(ForwardForecastRecord.resolved_at.asc())
        ).all()
        incidents = db.scalars(
            select(ForwardStudyIncident).where(
                ForwardStudyIncident.study_id == study_id,
                ForwardStudyIncident.opened_at <= evaluated_at,
            )
        ).all()

        evaluation = EvaluationInput(
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            family=study.family,
            forward_started_at=_aware(study.started_at),
            evaluated_at=evaluated_at,
            nav_series=tuple(NavObservation(_aware(row.observed_at), Decimal(row.nav_usd)) for row in nav_rows),
            trades=tuple(
                TradeOutcome(
                    _aware(row.closed_at),
                    Decimal(row.gross_pnl_usd),
                    Decimal(row.net_pnl_usd),
                    Decimal(row.fees_usd),
                    Decimal(row.slippage_usd),
                    Decimal(row.allocated_capital_usd),
                    Decimal(row.planned_loss_usd),
                )
                for row in trades
            ),
            executions=tuple(
                ExecutionComparison(
                    _aware(row.observed_at),
                    row.side,
                    Decimal(row.intended_quantity),
                    Decimal(row.paper_filled_quantity),
                    Decimal(row.shadow_filled_quantity),
                    Decimal(row.paper_average_price) if row.paper_average_price is not None else None,
                    Decimal(row.shadow_average_price) if row.shadow_average_price is not None else None,
                    Decimal(row.paper_cost_usd),
                    Decimal(row.shadow_cost_usd),
                )
                for row in executions
            ),
            forecasts=tuple(
                ForecastOutcome(
                    _aware(row.resolved_at),
                    Decimal(row.probability),
                    int(row.outcome),
                    Decimal(row.market_probability) if row.market_probability is not None else None,
                )
                for row in forecasts
            ),
            unresolved_critical_incidents=sum(1 for row in incidents if row.severity == "critical" and not row.resolved),
            data_integrity_failures=sum(1 for row in incidents if row.data_integrity),
        )
        return evaluation, version

    @staticmethod
    def evaluate_study(db: Session, *, study_id: str, evaluated_at: datetime) -> tuple[str, Any]:
        study = ForwardResearchService.get_study(db, study_id)
        policy = policy_from_json(study.evaluation_policy_json)
        evaluation, version = ForwardResearchService.build_evaluation_input(db, study_id=study_id, evaluated_at=evaluated_at)
        result = EvidenceEvaluator(policy).evaluate(evaluation)
        run_id = str(uuid.uuid4())
        metrics = {
            "performance": asdict(result.performance),
            "execution": asdict(result.execution),
            "prediction": asdict(result.prediction),
        }
        db.add(
            StrategyEvaluationRun(
                external_run_id=run_id,
                strategy_version_id=version.id,
                strategy_slug=evaluation.strategy_slug,
                strategy_version=evaluation.strategy_version,
                family=evaluation.family,
                recommendation=result.recommendation,
                forward_started_at=evaluation.forward_started_at,
                evaluated_at=evaluation.evaluated_at,
                forward_days=result.performance.forward_days,
                trade_count=result.performance.trade_count,
                forecast_count=result.prediction.forecast_count,
                execution_observation_count=result.execution.observation_count,
                net_pnl_usd=result.performance.net_pnl_usd,
                stressed_net_pnl_usd=result.performance.stressed_net_pnl_usd,
                max_drawdown_pct=result.performance.max_drawdown_pct,
                profit_factor=result.performance.profit_factor,
                brier_score=result.prediction.brier_score,
                calibration_error=result.prediction.calibration_error,
                policy_json=study.evaluation_policy_json,
                metrics_json=_json(metrics),
                reasons_json=_json(list(result.reasons)),
                input_json=_json(asdict(evaluation)),
                created_at=result.created_at,
            )
        )
        db.commit()
        return run_id, result

    @staticmethod
    def complete_study(db: Session, *, study_id: str, completed_at: datetime) -> ForwardStudy:
        study = ForwardResearchService.get_study(db, study_id)
        _active(study)
        completed_at = _aware(completed_at)
        if completed_at < _aware(study.started_at):
            raise ForwardResearchError("study completion predates start")
        study.status = "completed"
        study.completed_at = completed_at
        db.commit()
        db.refresh(study)
        return study
