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
from app.forward_models import ForwardExecutionRecord, ForwardNavObservation, ForwardStudy
from app.forward_operations import evaluation_policy_from_settings
from app.forward_research import ForwardResearchService
from app.models import Experiment, Strategy, StrategyStatus, StrategyVersion
from app.solana_forward import (
    INSTRUMENT,
    RUNNER_NAME,
    STRATEGY_NAME,
    STRATEGY_SLUG,
    STRATEGY_VERSION,
    OpenPosition,
    SolanaForwardConfig,
    SolanaForwardConfigError,
    SolanaForwardTick,
    SolanaLaunchBaselineForwardRunner,
    _aware,
)

ZERO = Decimal("0")
CORE_RUNNER_CODE_SHA = "314e9c158355613f7fccf0a5a5c0e302669c38a6"
M4_FORENSIC_SOURCE_SHA = "f26dd56e597c700c9c0783e8cf70d40d224eec80"
EXPERIMENT_HYPOTHESIS = (
    "A pre-registered safety-and-exitability baseline applied to chain-native Pump launches can "
    "produce measurable forward paper returns without momentum tuning, survivorship selection, "
    "wallet signing, or live execution."
)


class SolanaForwardOperationalError(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class SolanaBootstrapSpec:
    external_id: str
    initial_capital_usd: Decimal
    nav_interval_seconds: int
    config: SolanaForwardConfig

    @classmethod
    def from_settings(cls, settings: Settings) -> "SolanaBootstrapSpec":
        spec = cls(
            external_id=settings.solana_forward_study_external_id.strip(),
            initial_capital_usd=_d(settings.solana_forward_initial_capital_usd),
            nav_interval_seconds=settings.solana_forward_nav_interval_seconds,
            config=SolanaForwardConfig.from_settings(settings),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if not self.external_id:
            raise SolanaForwardOperationalError("Solana forward external id is required")
        if self.initial_capital_usd <= ZERO:
            raise SolanaForwardOperationalError("Solana simulated capital must be positive")
        max_allocated = self.config.entry_notional_usd * Decimal(self.config.max_open_positions)
        if max_allocated > self.initial_capital_usd:
            raise SolanaForwardOperationalError(
                "configured maximum open positions can exceed the no-leverage simulated capital"
            )
        if self.nav_interval_seconds < 60 or self.nav_interval_seconds > 3600:
            raise SolanaForwardOperationalError("NAV interval must be between 60 and 3600 seconds")

    def study_config(self) -> dict[str, Any]:
        values = self.config.study_config()
        values["nav_interval_seconds"] = self.nav_interval_seconds
        values["core_runner_code_sha"] = CORE_RUNNER_CODE_SHA
        values["forensic_source_sha"] = M4_FORENSIC_SOURCE_SHA
        return values


class OperationalSolanaForwardBootstrap:
    @staticmethod
    def _strategy_config() -> str:
        return _json(
            {
                "family": "meme",
                "venue": "solana",
                "runner": RUNNER_NAME,
                "entry_policy": "chronological_safety_exitability_baseline_no_alpha_score",
                "live_execution": False,
                "core_runner_code_sha": CORE_RUNNER_CODE_SHA,
                "forensic_source_sha": M4_FORENSIC_SOURCE_SHA,
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

    @classmethod
    def _ensure_version(cls, db: Session, strategy: Strategy) -> StrategyVersion:
        expected_config = cls._strategy_config()
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
                code_sha=CORE_RUNNER_CODE_SHA,
                config_json=expected_config,
                immutable=True,
            )
            db.add(version)
            db.commit()
            db.refresh(version)
            return version
        if (
            not version.immutable
            or version.code_sha != CORE_RUNNER_CODE_SHA
            or version.config_json != expected_config
        ):
            raise SolanaForwardOperationalError(
                "registered Solana forward strategy version conflicts with the frozen M6G baseline"
            )
        return version

    @staticmethod
    def _ensure_experiment(
        db: Session,
        *,
        version: StrategyVersion,
        external_id: str,
    ) -> Experiment:
        experiment_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"edge-lab:solana-forward-experiment:{external_id}")
        )
        expected = {
            "strategy_version_id": version.id,
            "hypothesis": EXPERIMENT_HYPOTHESIS,
            "data_version": "solana-pump-public-forward-v1",
            "train_window": "none-pre-registered-baseline",
            "validation_window": "quote-only-paper-plus-delayed-shadow",
            "holdout_window": "future-forward-observations",
            "search_space_json": "{}",
        }
        experiment = db.get(Experiment, experiment_id)
        if experiment is None:
            experiment = Experiment(id=experiment_id, **expected, status="registered")
            db.add(experiment)
            db.commit()
            db.refresh(experiment)
            return experiment
        for field, value in expected.items():
            if getattr(experiment, field) != value:
                raise SolanaForwardOperationalError(
                    f"existing Solana bootstrap experiment conflicts on {field}"
                )
        if experiment.status not in {"registered", "running"}:
            raise SolanaForwardOperationalError(
                f"existing Solana bootstrap experiment is not reusable: {experiment.status}"
            )
        return experiment

    @staticmethod
    def _validate_existing(
        db: Session,
        *,
        study: ForwardStudy,
        spec: SolanaBootstrapSpec,
        policy: EvaluationPolicy,
    ) -> tuple[StrategyVersion, Experiment]:
        version = db.get(StrategyVersion, study.strategy_version_id)
        if version is None:
            raise SolanaForwardOperationalError("existing Solana study lost its strategy version")
        strategy = db.get(Strategy, version.strategy_id)
        experiment = db.get(Experiment, study.experiment_id)
        if strategy is None or experiment is None:
            raise SolanaForwardOperationalError("existing Solana study lost registered lineage")
        mismatches: list[str] = []
        if strategy.slug != STRATEGY_SLUG:
            mismatches.append("strategy")
        if (
            version.version != STRATEGY_VERSION
            or version.code_sha != CORE_RUNNER_CODE_SHA
            or not version.immutable
        ):
            mismatches.append("strategy_version")
        if study.family != "meme" or study.venue != "solana" or study.instrument != INSTRUMENT:
            mismatches.append("family_venue_instrument")
        if Decimal(study.initial_capital_usd) != spec.initial_capital_usd:
            mismatches.append("initial_capital")
        if study.study_config_json != _json(spec.study_config()):
            mismatches.append("study_config")
        if study.evaluation_policy_json != _json(asdict(policy)):
            mismatches.append("evaluation_policy")
        if experiment.strategy_version_id != version.id:
            mismatches.append("experiment_lineage")
        if mismatches:
            raise SolanaForwardOperationalError(
                "existing Solana forward study conflicts with bootstrap spec: " + ",".join(mismatches)
            )
        return version, experiment

    @classmethod
    def bootstrap(
        cls,
        db: Session,
        *,
        settings: Settings,
        now: datetime | None = None,
    ) -> ForwardStudy:
        now = _aware(now or datetime.now(timezone.utc))
        spec = SolanaBootstrapSpec.from_settings(settings)
        policy = evaluation_policy_from_settings(settings)
        existing = db.scalar(
            select(ForwardStudy).where(ForwardStudy.external_id == spec.external_id)
        )
        if existing is not None:
            cls._validate_existing(db, study=existing, spec=spec, policy=policy)
            initial_nav = db.scalar(
                select(ForwardNavObservation).where(
                    ForwardNavObservation.study_id == existing.id,
                    ForwardNavObservation.observed_at == existing.started_at,
                )
            )
            if initial_nav is None:
                if existing.status != "active":
                    raise SolanaForwardOperationalError(
                        "non-active Solana forward study is missing its frozen initial NAV"
                    )
                initial_nav = ForwardResearchService.record_nav(
                    db,
                    study_id=existing.id,
                    observed_at=_aware(existing.started_at),
                    nav_usd=Decimal(existing.initial_capital_usd),
                    source="study-initial-capital",
                )
            elif (
                Decimal(initial_nav.nav_usd) != Decimal(existing.initial_capital_usd)
                or initial_nav.source != "study-initial-capital"
            ):
                raise SolanaForwardOperationalError(
                    "Solana forward initial NAV conflicts with frozen bootstrap capital"
                )
            return existing

        strategy = cls._ensure_strategy(db)
        version = cls._ensure_version(db, strategy)
        experiment = cls._ensure_experiment(db, version=version, external_id=spec.external_id)
        study = ForwardResearchService.create_study(
            db,
            external_id=spec.external_id,
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            experiment_id=experiment.id,
            family="meme",
            venue="solana",
            instrument=INSTRUMENT,
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
        return study


class OperationalSolanaLaunchBaselineForwardRunner(SolanaLaunchBaselineForwardRunner):
    """Fail-closed evidence hardening around the quote-only M6G baseline runner."""

    @staticmethod
    def _nav_interval_seconds(study: ForwardStudy) -> int:
        try:
            raw = json.loads(study.study_config_json)
            value = int(raw["nav_interval_seconds"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SolanaForwardConfigError("stored Solana NAV interval is invalid") from exc
        if value < 60 or value > 3600:
            raise SolanaForwardConfigError("stored Solana NAV interval is outside allowed bounds")
        return value

    @classmethod
    def journal_errors(cls, db: Session, study_id: str) -> list[tuple[str, str]]:
        rows = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.like("solana-entry:%"),
            )
        ).all()
        errors: list[tuple[str, str]] = []
        required = {
            "launch_signature",
            "mint",
            "creator",
            "opened_at",
            "hold_until",
            "token_amount_atomic",
            "allocated_capital_usd",
            "entry_in_usd",
            "entry_out_usd",
        }
        for row in rows:
            try:
                metadata = json.loads(row.metadata_json)
            except json.JSONDecodeError:
                errors.append((row.id, "ENTRY_METADATA_INVALID_JSON"))
                continue
            if not isinstance(metadata, dict):
                errors.append((row.id, "ENTRY_METADATA_NOT_OBJECT"))
                continue
            if metadata.get("status") != "open":
                continue
            missing = sorted(required.difference(metadata))
            if missing:
                errors.append((row.id, "ENTRY_METADATA_MISSING:" + ",".join(missing)))
                continue
            try:
                if int(metadata["token_amount_atomic"]) <= 0:
                    raise ValueError("non-positive token amount")
                if _d(metadata["allocated_capital_usd"]) <= ZERO:
                    raise ValueError("non-positive capital")
                datetime.fromisoformat(str(metadata["opened_at"]).replace("Z", "+00:00"))
                datetime.fromisoformat(str(metadata["hold_until"]).replace("Z", "+00:00"))
            except (TypeError, ValueError, ArithmeticError):
                errors.append((row.id, "ENTRY_METADATA_INVALID_VALUES"))
        return errors

    @classmethod
    def _persist_journal_errors(
        cls,
        db: Session,
        study: ForwardStudy,
        *,
        now: datetime,
    ) -> list[tuple[str, str]]:
        errors = cls.journal_errors(db, study.id)
        for row_id, reason in errors:
            ForwardResearchService.record_incident(
                db,
                study_id=study.id,
                external_key=f"solana-forward-journal:{row_id}",
                severity="critical",
                code="SOLANA_FORWARD_JOURNAL_CORRUPT",
                message=reason,
                opened_at=_aware(now),
                data_integrity=True,
            )
        return errors

    async def _executable_equity(
        self,
        db: Session,
        study: ForwardStudy,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> Decimal | None:
        equity = self._equity(db, study)
        for position in self._open_positions(db, study.id):
            quote = await self._quote(
                input_mint=position.mint,
                output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                amount=position.token_amount_atomic,
            )
            if not self._quote_valid(
                quote,
                input_mint=position.mint,
                output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                input_amount=position.token_amount_atomic,
                max_price_impact=config.max_quote_price_impact_pct,
            ) or quote is None:
                bucket = int(_aware(now).timestamp() // 300)
                ForwardResearchService.record_incident(
                    db,
                    study_id=study.id,
                    external_key=f"solana-nav-mark:{position.launch_signature}:{bucket}",
                    severity="error",
                    code="SOLANA_EXECUTABLE_NAV_MARK_UNAVAILABLE",
                    message=f"no valid executable exit mark for {position.mint}",
                    opened_at=_aware(now),
                    data_integrity=False,
                )
                return None
            equity += Decimal(quote.out_usd_value) - position.entry_in_usd
        return equity

    @classmethod
    def _latest_nav(cls, db: Session, study_id: str) -> ForwardNavObservation | None:
        return db.scalar(
            select(ForwardNavObservation)
            .where(ForwardNavObservation.study_id == study_id)
            .order_by(ForwardNavObservation.observed_at.desc())
            .limit(1)
        )

    async def _mark_nav_if_due(
        self,
        db: Session,
        study: ForwardStudy,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> tuple[bool, str]:
        latest = self._latest_nav(db, study.id)
        interval = self._nav_interval_seconds(study)
        if latest is not None and (_aware(now) - _aware(latest.observed_at)).total_seconds() < interval:
            # Still obtain an executable mark when positions are open before adding more risk.
            if self._open_positions(db, study.id):
                equity = await self._executable_equity(db, study, config, now=now)
                return (equity is not None, "checked-not-due" if equity is not None else "unavailable")
            return True, "not-due"
        equity = await self._executable_equity(db, study, config, now=now)
        if equity is None:
            return False, "unavailable"
        if equity <= ZERO:
            self._record_incident(
                db,
                study,
                now,
                severity="critical",
                code="SOLANA_SIMULATED_CAPITAL_DEPLETED",
                message="simulated Solana forward NAV is non-positive",
                data_integrity=False,
            )
            return False, "depleted"
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=_aware(now),
            nav_usd=equity,
            source="solana-forward-executable-liquidation-nav",
        )
        return True, "recorded"

    async def run_study_once(
        self,
        db: Session,
        study: ForwardStudy,
        *,
        now: datetime | None = None,
    ) -> SolanaForwardTick:
        now = _aware(now or datetime.now(timezone.utc))
        config = SolanaForwardConfig.from_study(study)
        errors = self._persist_journal_errors(db, study, now=now)
        if errors:
            detail = f"journal_integrity_failures={len(errors)}"
            self.health.set("solana_forward", False, detail)
            return SolanaForwardTick(study.id, "blocked", detail)

        reconciled = self._reconcile_closed_executions(db, study)
        closed, failed_exits = await self._exit_due_positions(db, study, config, now=now)
        nav_ok, nav_action = await self._mark_nav_if_due(db, study, config, now=now)
        opened = attempts = 0
        if nav_ok:
            opened, attempts = await self._attempt_new_entries(db, study, config, now=now)
        detail = (
            f"reconciled={reconciled} closed={closed} failed_exits={failed_exits} "
            f"nav={nav_action} entry_attempts={attempts} opened={opened} "
            f"open={len(self._open_positions(db, study.id))}"
        )
        self.health.set("solana_forward", nav_ok, detail)
        return SolanaForwardTick(study.id, "cycle" if nav_ok else "waiting", detail)
