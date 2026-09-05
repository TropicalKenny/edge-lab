from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import ForwardNavObservation, ForwardStudy
from app.forward_operations import evaluation_policy_from_settings
from app.forward_research import ForwardResearchService
from app.models import Experiment, Strategy, StrategyStatus, StrategyVersion
from app.solana_forward import RUNNER_NAME, _aware
from app.solana_meme_forward import (
    M6L_EXPLORATORY_EXTERNAL_ID,
    M6L_INSTRUMENT,
    M6L_RUNNER,
    M6L_STRATEGY_NAME,
    M6L_STRATEGY_SLUG,
    M6L_STRATEGY_VERSION,
    M6L_STRICT_EXTERNAL_ID,
)

M6L_CODE_ID = "m6l-solana-meme-momentum-v1"
INITIAL_CAPITAL = Decimal("1000")


class M6LMemeBootstrapError(RuntimeError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _strategy_config() -> dict[str, Any]:
    return {
        "family": "meme",
        "venue": "solana",
        "instrument": M6L_INSTRUMENT,
        "strategy_runner": M6L_RUNNER,
        "paper_only": True,
        "alpha_version": "m6l-sol-alpha-v1",
        "execution_engine": RUNNER_NAME,
        "decision_window_minutes": [3, 20],
        "min_alpha_score": 3,
        "min_momentum_score": "0.10",
        "min_volume_acceleration": "1.20",
        "max_sell_ratio_5m": "0.55",
        "max_5m_loss_pct": "20",
        "max_5m_spike_pct": "150",
        "hard_stop_recovery_ratio": "0.75",
        "trail_arm_ratio": "1.30",
        "trail_drawdown_ratio": "0.15",
        "high_trail_arm_ratio": "1.75",
        "high_trail_drawdown_ratio": "0.10",
    }


def study_config(cohort: str) -> dict[str, Any]:
    if cohort not in {"strict", "exploratory"}:
        raise M6LMemeBootstrapError("invalid M6L cohort")
    return {
        "runner": RUNNER_NAME,
        "strategy_runner": M6L_RUNNER,
        "cohort": cohort,
        "entry_notional_usd": "25",
        "decision_delay_minutes": 3,
        "max_candidate_age_minutes": 20,
        "hold_minutes": 30,
        "max_exit_delay_minutes": 10,
        "shadow_delay_ms": 1000,
        "max_quote_price_impact_pct": "0.08",
        "min_preflight_exit_ratio": "0.88",
        "max_open_positions": 10,
        "max_entries_per_cycle": 5,
        "nav_interval_seconds": 300,
        "min_alpha_score": 3,
        "min_momentum_score": "0.10",
        "min_volume_acceleration": "1.20",
        "max_sell_ratio_5m": "0.55",
        "max_5m_loss_pct": "20",
        "max_5m_spike_pct": "150",
        "hard_stop_recovery_ratio": "0.75",
        "trail_arm_ratio": "1.30",
        "trail_drawdown_ratio": "0.15",
        "high_trail_arm_ratio": "1.75",
        "high_trail_drawdown_ratio": "0.10",
        "feature_refresh_seconds": 120,
        "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "planned_loss": "full_allocated_capital_if_no_route",
        "entry_policy": "m6l_flow_alpha_then_quote_only_execution",
        "unknown_policy": (
            "reject_unknown" if cohort == "strict" else "allow_unknown_block_known_unsafe"
        ),
    }


class M6LMemeBootstrap:
    @staticmethod
    def _ensure_strategy(db: Session) -> Strategy:
        strategy = db.scalar(select(Strategy).where(Strategy.slug == M6L_STRATEGY_SLUG))
        if strategy is None:
            strategy = Strategy(
                slug=M6L_STRATEGY_SLUG,
                name=M6L_STRATEGY_NAME,
                status=StrategyStatus.RED.value,
            )
            db.add(strategy)
            db.commit()
            db.refresh(strategy)
        return strategy

    @classmethod
    def _ensure_version(cls, db: Session, strategy: Strategy) -> StrategyVersion:
        expected = _json(_strategy_config())
        version = db.scalar(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version == M6L_STRATEGY_VERSION,
            )
        )
        if version is None:
            version = StrategyVersion(
                strategy_id=strategy.id,
                version=M6L_STRATEGY_VERSION,
                code_sha=M6L_CODE_ID,
                config_json=expected,
                immutable=True,
            )
            db.add(version)
            db.commit()
            db.refresh(version)
            return version
        if (
            not version.immutable
            or version.code_sha != M6L_CODE_ID
            or version.config_json != expected
        ):
            raise M6LMemeBootstrapError("existing M6L strategy version conflicts with frozen v1")
        return version

    @staticmethod
    def _ensure_experiment(
        db: Session,
        *,
        version: StrategyVersion,
        cohort: str,
        external_id: str,
    ) -> Experiment:
        experiment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"edge-lab:m6l-sol:{external_id}"))
        hypothesis = (
            "Decision-time early buy pressure and volume acceleration can produce positive "
            "quote-realistic short-horizon Pump/PumpSwap paper expectancy; compare strict "
            "security certainty against an exploratory UNKNOWN-allowed cohort without "
            "allowing known unsafe mechanics."
        )
        expected = {
            "strategy_version_id": version.id,
            "hypothesis": hypothesis,
            "data_version": "solana-pump-forward-m6l-v1",
            "train_window": "none-preregistered-challenger",
            "validation_window": f"forward-paper-shadow-{cohort}",
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
                raise M6LMemeBootstrapError(f"existing M6L experiment conflicts on {field}")
        if experiment.status not in {"registered", "running"}:
            raise M6LMemeBootstrapError("existing M6L experiment is not reusable")
        return experiment

    @classmethod
    def _ensure_study(
        cls,
        db: Session,
        *,
        settings: Settings,
        strategy: Strategy,
        version: StrategyVersion,
        cohort: str,
        external_id: str,
        now: datetime,
    ) -> ForwardStudy:
        expected_config = study_config(cohort)
        policy = evaluation_policy_from_settings(settings)
        existing = db.scalar(select(ForwardStudy).where(ForwardStudy.external_id == external_id))
        if existing is not None:
            if (
                existing.strategy_version_id != version.id
                or existing.family != "meme"
                or existing.venue != "solana"
                or existing.instrument != M6L_INSTRUMENT
                or Decimal(existing.initial_capital_usd) != INITIAL_CAPITAL
                or existing.study_config_json != _json(expected_config)
            ):
                raise M6LMemeBootstrapError(f"existing M6L study conflicts: {external_id}")
            initial = db.scalar(
                select(ForwardNavObservation).where(
                    ForwardNavObservation.study_id == existing.id,
                    ForwardNavObservation.observed_at == existing.started_at,
                )
            )
            if initial is None:
                ForwardResearchService.record_nav(
                    db,
                    study_id=existing.id,
                    observed_at=_aware(existing.started_at),
                    nav_usd=INITIAL_CAPITAL,
                    source="study-initial-capital",
                )
            return existing

        experiment = cls._ensure_experiment(
            db, version=version, cohort=cohort, external_id=external_id
        )
        study = ForwardResearchService.create_study(
            db,
            external_id=external_id,
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            experiment_id=experiment.id,
            family="meme",
            venue="solana",
            instrument=M6L_INSTRUMENT,
            initial_capital_usd=INITIAL_CAPITAL,
            evaluation_policy=policy,
            study_config=expected_config,
            started_at=now,
        )
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=now,
            nav_usd=INITIAL_CAPITAL,
            source="study-initial-capital",
        )
        return study

    @classmethod
    def bootstrap_all(
        cls,
        db: Session,
        *,
        settings: Settings,
        now: datetime | None = None,
    ) -> list[ForwardStudy]:
        if settings.signer_enabled:
            raise M6LMemeBootstrapError("refusing M6L bootstrap with SIGNER_ENABLED=true")
        now = _aware(now or datetime.now(timezone.utc))
        strategy = cls._ensure_strategy(db)
        version = cls._ensure_version(db, strategy)
        studies = []
        for cohort, external_id in (
            ("strict", M6L_STRICT_EXTERNAL_ID),
            ("exploratory", M6L_EXPLORATORY_EXTERNAL_ID),
        ):
            studies.append(
                cls._ensure_study(
                    db,
                    settings=settings,
                    strategy=strategy,
                    version=version,
                    cohort=cohort,
                    external_id=external_id,
                    now=now,
                )
            )
        return studies
