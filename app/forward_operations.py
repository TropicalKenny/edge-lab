from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.evaluation import EvaluationPolicy
from app.evaluation_lookup import latest_study_evaluation
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.forward_research import ForwardResearchError, ForwardResearchService, policy_from_json
from app.hyperliquid_forward import CarryRunnerConfigError, CarryStudyConfig
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.models import Experiment, Strategy, StrategyStatus, StrategyVersion
from app.venues.hyperliquid_models import HyperliquidFundingSnapshot, HyperliquidPerpSnapshot

ZERO = Decimal("0")
STRATEGY_SLUG = "hyperliquid-funding-carry"
STRATEGY_NAME = "Hyperliquid Funding Carry"
STRATEGY_VERSION = "m6c-v1"
STRATEGY_CODE_SHA = "649496cd08bbcb7ad6d5c4cfd61ae44412fabdc4"
EXPERIMENT_HYPOTHESIS = (
    "Positive Hyperliquid perpetual funding can support long-spot/short-perp carry "
    "after executable fees, slippage, funding settlement and liquidity constraints."
)


class ForwardOperationsError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def evaluation_policy_from_settings(settings: Settings) -> EvaluationPolicy:
    policy = EvaluationPolicy(
        min_forward_days=settings.evaluation_min_forward_days,
        min_nav_observations=settings.evaluation_min_nav_observations,
        min_shadow_observations=settings.evaluation_min_shadow_observations,
        min_trades_default=settings.evaluation_min_trades_default,
        min_trades_funding=settings.evaluation_min_trades_funding,
        min_trades_directional=settings.evaluation_min_trades_directional,
        min_trades_meme=settings.evaluation_min_trades_meme,
        min_forecasts_prediction=settings.evaluation_min_forecasts_prediction,
        max_drawdown_pct=_d(settings.evaluation_max_drawdown_pct),
        min_profit_factor=_d(settings.evaluation_min_profit_factor),
        max_top3_profit_concentration=_d(
            settings.evaluation_max_top3_profit_concentration
        ),
        cost_stress_multiplier=_d(settings.evaluation_cost_stress_multiplier),
        min_shadow_fill_ratio=_d(settings.evaluation_min_shadow_fill_ratio),
        max_shadow_p90_price_divergence_bps=_d(
            settings.evaluation_max_shadow_p90_price_divergence_bps
        ),
        max_prediction_calibration_error=_d(
            settings.evaluation_max_prediction_calibration_error
        ),
        max_nav_gap_days=_d(settings.evaluation_max_nav_gap_days),
    )
    policy.validate()
    return policy


@dataclass(frozen=True)
class HyperliquidBootstrapSpec:
    external_id: str
    instrument: str
    initial_capital_usd: Decimal
    paired_notional_usd: Decimal
    horizon_hours: int
    min_edge_bps: Decimal
    planned_loss_pct: Decimal
    spot_fee_bps: Decimal
    perp_fee_bps: Decimal
    slippage_reserve_bps_per_leg: Decimal
    shadow_delay_ms: int
    max_exit_delay_hours: int
    max_funding_oracle_age_minutes: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "HyperliquidBootstrapSpec":
        return cls(
            external_id=settings.hyperliquid_forward_study_external_id.strip(),
            instrument=settings.hyperliquid_forward_instrument.strip().upper(),
            initial_capital_usd=_d(settings.hyperliquid_forward_initial_capital_usd),
            paired_notional_usd=_d(settings.hyperliquid_forward_paired_notional_usd),
            horizon_hours=settings.hyperliquid_forward_horizon_hours,
            min_edge_bps=_d(settings.hyperliquid_forward_min_edge_bps),
            planned_loss_pct=_d(settings.hyperliquid_forward_planned_loss_pct),
            spot_fee_bps=_d(settings.hyperliquid_forward_spot_fee_bps),
            perp_fee_bps=_d(settings.hyperliquid_forward_perp_fee_bps),
            slippage_reserve_bps_per_leg=_d(
                settings.hyperliquid_forward_slippage_reserve_bps_per_leg
            ),
            shadow_delay_ms=settings.hyperliquid_forward_shadow_delay_ms,
            max_exit_delay_hours=settings.hyperliquid_forward_max_exit_delay_hours,
            max_funding_oracle_age_minutes=(
                settings.hyperliquid_forward_max_funding_oracle_age_minutes
            ),
        )

    def validate(self) -> None:
        if not self.external_id or not self.instrument:
            raise ForwardOperationsError("forward study external id and instrument are required")
        if self.initial_capital_usd <= ZERO or self.paired_notional_usd <= ZERO:
            raise ForwardOperationsError("simulated capital and paired notional must be positive")
        if self.paired_notional_usd * Decimal("2") > self.initial_capital_usd:
            raise ForwardOperationsError(
                "paired notional requires more simulated capital than the no-leverage study provides"
            )
        if self.horizon_hours < 1 or self.horizon_hours > 72:
            raise ForwardOperationsError("horizon hours must be between 1 and 72")
        if self.min_edge_bps < ZERO:
            raise ForwardOperationsError("minimum edge cannot be negative")
        if self.planned_loss_pct <= ZERO or self.planned_loss_pct > Decimal("0.25"):
            raise ForwardOperationsError("planned loss pct must be >0 and <=0.25")
        if min(
            self.spot_fee_bps,
            self.perp_fee_bps,
            self.slippage_reserve_bps_per_leg,
        ) < ZERO:
            raise ForwardOperationsError("fee/slippage assumptions cannot be negative")
        if self.shadow_delay_ms < 0 or self.shadow_delay_ms > 5000:
            raise ForwardOperationsError("shadow delay must be between 0 and 5000ms")
        if self.max_exit_delay_hours < 1 or self.max_exit_delay_hours > 24:
            raise ForwardOperationsError("max exit delay must be between 1 and 24 hours")
        if not 1 <= self.max_funding_oracle_age_minutes <= 60:
            raise ForwardOperationsError("funding oracle age must be between 1 and 60 minutes")

    def study_config(self) -> dict[str, Any]:
        return {
            "runner": "hyperliquid_carry_v1",
            "paired_notional_usd": str(self.paired_notional_usd),
            "horizon_hours": self.horizon_hours,
            "min_edge_bps": str(self.min_edge_bps),
            "planned_loss_pct": str(self.planned_loss_pct),
            "spot_fee_bps": str(self.spot_fee_bps),
            "perp_fee_bps": str(self.perp_fee_bps),
            "slippage_reserve_bps_per_leg": str(
                self.slippage_reserve_bps_per_leg
            ),
            "shadow_delay_ms": self.shadow_delay_ms,
            "max_exit_delay_hours": self.max_exit_delay_hours,
            "max_funding_oracle_age_minutes": self.max_funding_oracle_age_minutes,
        }


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    study_id: str
    external_id: str
    strategy_slug: str
    strategy_version: str
    strategy_code_sha: str
    experiment_id: str
    instrument: str
    started_at: datetime
    initial_nav_usd: Decimal


@dataclass(frozen=True)
class EvaluationTick:
    study_id: str
    external_id: str
    action: str
    run_id: str | None
    recommendation: str | None


class ForwardOperationsService:
    @staticmethod
    def _strategy_config() -> str:
        return _json(
            {
                "family": "funding",
                "venue": "hyperliquid",
                "runner": "hyperliquid_carry_v1",
                "direction": "long_spot_short_perp",
                "live_execution": False,
            }
        )

    @staticmethod
    def _ensure_strategy(db: Session) -> Strategy:
        strategy = db.scalar(select(Strategy).where(Strategy.slug == STRATEGY_SLUG))
        if strategy is None:
            strategy = Strategy(
                slug=STRATEGY_SLUG,
                name=STRATEGY_NAME,
                status=StrategyStatus.RED.value,
            )
            db.add(strategy)
            db.commit()
            db.refresh(strategy)
        return strategy

    @staticmethod
    def _ensure_version(db: Session, strategy: Strategy) -> StrategyVersion:
        config_json = ForwardOperationsService._strategy_config()
        version = db.scalar(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version == STRATEGY_VERSION,
            )
        )
        if version is None:
            version = StrategyVersion(
                strategy_id=strategy.id,
                version=STRATEGY_VERSION,
                code_sha=STRATEGY_CODE_SHA,
                config_json=config_json,
                immutable=True,
            )
            db.add(version)
            db.commit()
            db.refresh(version)
            return version
        if not version.immutable:
            raise ForwardOperationsError("registered forward strategy version is mutable")
        if version.code_sha != STRATEGY_CODE_SHA or version.config_json != config_json:
            raise ForwardOperationsError(
                "registered strategy version conflicts with the frozen M6C implementation"
            )
        return version

    @staticmethod
    def _ensure_experiment(
        db: Session, *, version: StrategyVersion, external_id: str
    ) -> Experiment:
        experiment_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"edge-lab:hyperliquid-forward-experiment:{external_id}",
            )
        )
        experiment = db.get(Experiment, experiment_id)
        expected = {
            "strategy_version_id": version.id,
            "hypothesis": EXPERIMENT_HYPOTHESIS,
            "data_version": "hyperliquid-public-forward-v1",
            "train_window": "pre-registered-research-only",
            "validation_window": "paper-plus-delayed-shadow",
            "holdout_window": "future-forward-observations",
            "search_space_json": "{}",
        }
        if experiment is None:
            experiment = Experiment(
                id=experiment_id,
                **expected,
                status="registered",
            )
            db.add(experiment)
            db.commit()
            db.refresh(experiment)
            return experiment
        for field, value in expected.items():
            if getattr(experiment, field) != value:
                raise ForwardOperationsError(
                    f"existing bootstrap experiment conflicts on {field}"
                )
        if experiment.status not in {"registered", "running"}:
            raise ForwardOperationsError(
                f"existing bootstrap experiment is not reusable: {experiment.status}"
            )
        return experiment

    @staticmethod
    def _validate_existing_study(
        db: Session,
        *,
        study: ForwardStudy,
        spec: HyperliquidBootstrapSpec,
        policy: EvaluationPolicy,
    ) -> tuple[StrategyVersion, Experiment]:
        version = db.get(StrategyVersion, study.strategy_version_id)
        if version is None:
            raise ForwardOperationsError("existing forward study lost its strategy version")
        strategy = db.get(Strategy, version.strategy_id)
        experiment = db.get(Experiment, study.experiment_id)
        if strategy is None or experiment is None:
            raise ForwardOperationsError("existing forward study lost registered lineage")
        expected_policy = _json(asdict(policy))
        expected_config = _json(spec.study_config())
        mismatches: list[str] = []
        if strategy.slug != STRATEGY_SLUG:
            mismatches.append("strategy")
        if version.version != STRATEGY_VERSION or version.code_sha != STRATEGY_CODE_SHA:
            mismatches.append("strategy_version")
        if not version.immutable:
            mismatches.append("mutable_strategy_version")
        if study.family != "funding" or study.venue != "hyperliquid":
            mismatches.append("family_or_venue")
        if study.instrument.upper() != spec.instrument:
            mismatches.append("instrument")
        if Decimal(study.initial_capital_usd) != spec.initial_capital_usd:
            mismatches.append("initial_capital")
        if study.study_config_json != expected_config:
            mismatches.append("study_config")
        if study.evaluation_policy_json != expected_policy:
            mismatches.append("evaluation_policy")
        if experiment.strategy_version_id != version.id:
            mismatches.append("experiment_lineage")
        if mismatches:
            raise ForwardOperationsError(
                "existing forward study conflicts with bootstrap spec: "
                + ",".join(mismatches)
            )
        return version, experiment

    @staticmethod
    def bootstrap_hyperliquid_study(
        db: Session,
        *,
        settings: Settings,
        now: datetime | None = None,
    ) -> BootstrapResult:
        now = _aware(now or datetime.now(timezone.utc))
        spec = HyperliquidBootstrapSpec.from_settings(settings)
        spec.validate()
        policy = evaluation_policy_from_settings(settings)
        existing = db.scalar(
            select(ForwardStudy).where(ForwardStudy.external_id == spec.external_id)
        )
        if existing is not None:
            version, experiment = ForwardOperationsService._validate_existing_study(
                db, study=existing, spec=spec, policy=policy
            )
            initial_nav = db.scalar(
                select(ForwardNavObservation).where(
                    ForwardNavObservation.study_id == existing.id,
                    ForwardNavObservation.observed_at == existing.started_at,
                )
            )
            if initial_nav is None:
                if existing.status != "active":
                    raise ForwardOperationsError(
                        "completed/non-active study is missing its frozen initial NAV"
                    )
                initial_nav = ForwardResearchService.record_nav(
                    db,
                    study_id=existing.id,
                    observed_at=_aware(existing.started_at),
                    nav_usd=Decimal(existing.initial_capital_usd),
                    source="study-initial-capital",
                )
            return BootstrapResult(
                created=False,
                study_id=existing.id,
                external_id=existing.external_id,
                strategy_slug=STRATEGY_SLUG,
                strategy_version=version.version,
                strategy_code_sha=version.code_sha or "",
                experiment_id=experiment.id,
                instrument=existing.instrument,
                started_at=_aware(existing.started_at),
                initial_nav_usd=Decimal(initial_nav.nav_usd),
            )

        strategy = ForwardOperationsService._ensure_strategy(db)
        version = ForwardOperationsService._ensure_version(db, strategy)
        experiment = ForwardOperationsService._ensure_experiment(
            db, version=version, external_id=spec.external_id
        )
        study = ForwardResearchService.create_study(
            db,
            external_id=spec.external_id,
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            experiment_id=experiment.id,
            family="funding",
            venue="hyperliquid",
            instrument=spec.instrument,
            initial_capital_usd=spec.initial_capital_usd,
            evaluation_policy=policy,
            study_config=spec.study_config(),
            started_at=now,
        )
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=now,
            nav_usd=spec.initial_capital_usd,
            source="study-initial-capital",
        )
        return BootstrapResult(
            created=True,
            study_id=study.id,
            external_id=study.external_id,
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            strategy_code_sha=version.code_sha or "",
            experiment_id=experiment.id,
            instrument=study.instrument,
            started_at=now,
            initial_nav_usd=spec.initial_capital_usd,
        )

    @staticmethod
    def evaluate_due_studies(
        db: Session, *, now: datetime | None = None
    ) -> list[EvaluationTick]:
        now = _aware(now or datetime.now(timezone.utc))
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        studies = db.scalars(
            select(ForwardStudy)
            .where(ForwardStudy.status == "active")
            .order_by(ForwardStudy.started_at.asc())
        ).all()
        ticks: list[EvaluationTick] = []
        for study in studies:
            existing = latest_study_evaluation(db, study)
            if existing is not None and day_start <= _aware(existing.evaluated_at) < day_end:
                ticks.append(
                    EvaluationTick(
                        study.id,
                        study.external_id,
                        "already_evaluated_today",
                        None,
                        None,
                    )
                )
                continue
            run_id, result = ForwardResearchService.evaluate_study(
                db, study_id=study.id, evaluated_at=now
            )
            ticks.append(
                EvaluationTick(
                    study.id,
                    study.external_id,
                    "evaluated",
                    run_id,
                    result.recommendation,
                )
            )
        return ticks

    @staticmethod
    def study_statuses(
        db: Session,
        *,
        settings: Settings,
        external_id: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        now = _aware(now or datetime.now(timezone.utc))
        query = select(ForwardStudy).where(
            ForwardStudy.venue == "hyperliquid",
            ForwardStudy.family == "funding",
        )
        if external_id:
            query = query.where(ForwardStudy.external_id == external_id)
        studies = db.scalars(query.order_by(ForwardStudy.started_at.asc())).all()
        reports: list[dict[str, Any]] = []
        for study in studies:
            version = db.get(StrategyVersion, study.strategy_version_id)
            strategy = db.get(Strategy, version.strategy_id) if version is not None else None
            nav = db.scalar(
                select(ForwardNavObservation)
                .where(ForwardNavObservation.study_id == study.id)
                .order_by(ForwardNavObservation.observed_at.desc())
                .limit(1)
            )
            open_positions = db.scalars(
                select(HyperliquidCarryPosition).where(
                    HyperliquidCarryPosition.study_id == study.id,
                    HyperliquidCarryPosition.status == "open",
                )
            ).all()
            unresolved_critical = int(
                db.scalar(
                    select(func.count())
                    .select_from(ForwardStudyIncident)
                    .where(
                        ForwardStudyIncident.study_id == study.id,
                        ForwardStudyIncident.severity == "critical",
                        ForwardStudyIncident.resolved.is_(False),
                    )
                )
                or 0
            )
            integrity_failures = int(
                db.scalar(
                    select(func.count())
                    .select_from(ForwardStudyIncident)
                    .where(
                        ForwardStudyIncident.study_id == study.id,
                        ForwardStudyIncident.data_integrity.is_(True),
                    )
                )
                or 0
            )
            incident_count = int(
                db.scalar(
                    select(func.count())
                    .select_from(ForwardStudyIncident)
                    .where(ForwardStudyIncident.study_id == study.id)
                )
                or 0
            )
            trade_count = int(
                db.scalar(
                    select(func.count())
                    .select_from(ForwardTradeRecord)
                    .where(ForwardTradeRecord.study_id == study.id)
                )
                or 0
            )
            execution_count = int(
                db.scalar(
                    select(func.count())
                    .select_from(ForwardExecutionRecord)
                    .where(ForwardExecutionRecord.study_id == study.id)
                )
                or 0
            )
            latest_market = db.scalar(
                select(HyperliquidPerpSnapshot)
                .where(HyperliquidPerpSnapshot.coin == study.instrument.upper())
                .order_by(HyperliquidPerpSnapshot.captured_at.desc())
                .limit(1)
            )
            latest_funding = db.scalar(
                select(HyperliquidFundingSnapshot)
                .where(HyperliquidFundingSnapshot.coin == study.instrument.upper())
                .order_by(HyperliquidFundingSnapshot.funding_time.desc())
                .limit(1)
            )
            latest_evaluation = latest_study_evaluation(db, study)

            hard_reasons: list[str] = []
            warnings: list[str] = []
            if study.status != "active":
                hard_reasons.append("STUDY_NOT_ACTIVE")
            try:
                policy_from_json(study.evaluation_policy_json)
                CarryStudyConfig.from_study(study)
            except (ForwardResearchError, CarryRunnerConfigError, ValueError) as exc:
                hard_reasons.append(f"FROZEN_CONFIG_INVALID:{exc}")
            if version is None or not version.immutable:
                hard_reasons.append("STRATEGY_VERSION_MISSING_OR_MUTABLE")
            if strategy is None:
                hard_reasons.append("STRATEGY_MISSING")
            if integrity_failures:
                hard_reasons.append("DATA_INTEGRITY_CONTAMINATED")
            if unresolved_critical:
                hard_reasons.append("UNRESOLVED_CRITICAL_INCIDENT")
            if len(open_positions) > 1:
                hard_reasons.append("MULTIPLE_OPEN_POSITIONS")
            if nav is None:
                hard_reasons.append("NO_NAV")

            market_age_seconds: float | None = None
            if latest_market is None:
                warnings.append("NO_MARKET_SNAPSHOT_YET")
            else:
                market_age_seconds = max(
                    0.0,
                    (now - _aware(latest_market.captured_at)).total_seconds(),
                )
                if market_age_seconds > settings.forward_status_max_market_age_seconds:
                    warnings.append("MARKET_SNAPSHOT_STALE")

            funding_age_seconds: float | None = None
            if latest_funding is not None:
                funding_age_seconds = max(
                    0.0,
                    (now - _aware(latest_funding.funding_time)).total_seconds(),
                )
            if open_positions:
                opened_at = min(_aware(row.opened_at) for row in open_positions)
                if now - opened_at >= timedelta(hours=2):
                    if latest_funding is None or _aware(latest_funding.funding_time) <= opened_at:
                        hard_reasons.append("OPEN_POSITION_FUNDING_MISSING")

            if hard_reasons:
                operational_state = "blocked"
            elif warnings:
                operational_state = "waiting"
            else:
                operational_state = "ready"

            reports.append(
                {
                    "study_id": study.id,
                    "external_id": study.external_id,
                    "status": study.status,
                    "operational_state": operational_state,
                    "hard_reasons": hard_reasons,
                    "warnings": warnings,
                    "instrument": study.instrument,
                    "started_at": _aware(study.started_at),
                    "forward_age_days": max(
                        0,
                        (now - _aware(study.started_at)).days,
                    ),
                    "strategy_slug": strategy.slug if strategy is not None else None,
                    "strategy_status": strategy.status if strategy is not None else None,
                    "strategy_version": version.version if version is not None else None,
                    "strategy_code_sha": version.code_sha if version is not None else None,
                    "initial_capital_usd": Decimal(study.initial_capital_usd),
                    "last_nav_usd": Decimal(nav.nav_usd) if nav is not None else None,
                    "last_nav_at": _aware(nav.observed_at) if nav is not None else None,
                    "open_position_count": len(open_positions),
                    "open_position_ids": [row.id for row in open_positions],
                    "trade_count": trade_count,
                    "execution_observation_count": execution_count,
                    "incident_count": incident_count,
                    "data_integrity_failure_count": integrity_failures,
                    "unresolved_critical_incident_count": unresolved_critical,
                    "latest_market_at": (
                        _aware(latest_market.captured_at)
                        if latest_market is not None
                        else None
                    ),
                    "market_age_seconds": market_age_seconds,
                    "latest_funding_at": (
                        _aware(latest_funding.funding_time)
                        if latest_funding is not None
                        else None
                    ),
                    "funding_age_seconds": funding_age_seconds,
                    "latest_evaluation_at": (
                        _aware(latest_evaluation.evaluated_at)
                        if latest_evaluation is not None
                        else None
                    ),
                    "latest_recommendation": (
                        latest_evaluation.recommendation
                        if latest_evaluation is not None
                        else None
                    ),
                }
            )
        return reports

