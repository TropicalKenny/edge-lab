import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import ForwardStudy, ForwardStudyIncident
from app.forward_operations import (
    ForwardOperationsError,
    ForwardOperationsService,
    STRATEGY_CODE_SHA,
    STRATEGY_SLUG,
)
from app.forward_research import ForwardResearchService
from app.hyperliquid_forward_operational import OperationalHyperliquidCarryForwardRunner
from app.models import Base, Experiment, Strategy, StrategyVersion
from app.services import HealthRegistry
from app.venues.hyperliquid_models import HyperliquidPerpSnapshot
import app.evaluation_models
import app.forward_models
import app.hyperliquid_forward_models
import app.venues.hyperliquid_models

D = Decimal


def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def settings(**updates):
    base = Settings(
        database_url="sqlite:///:memory:",
        hyperliquid_forward_study_external_id="ops-hl-btc-v1",
        hyperliquid_forward_instrument="BTC",
        hyperliquid_forward_initial_capital_usd=1000,
        hyperliquid_forward_paired_notional_usd=100,
        hyperliquid_forward_horizon_hours=24,
        hyperliquid_forward_min_edge_bps=10,
        hyperliquid_forward_planned_loss_pct=0.02,
        hyperliquid_forward_spot_fee_bps=7,
        hyperliquid_forward_perp_fee_bps=4.5,
        hyperliquid_forward_slippage_reserve_bps_per_leg=2,
        hyperliquid_forward_shadow_delay_ms=1000,
        hyperliquid_forward_max_exit_delay_hours=6,
        hyperliquid_forward_max_funding_oracle_age_minutes=5,
        forward_status_max_market_age_seconds=900,
    )
    return base.model_copy(update=updates)


def test_bootstrap_is_idempotent_and_freezes_lineage_policy_config_and_initial_nav():
    db = db_session()
    now = datetime.now(timezone.utc) - timedelta(seconds=5)
    cfg = settings()

    first = ForwardOperationsService.bootstrap_hyperliquid_study(
        db, settings=cfg, now=now
    )
    second = ForwardOperationsService.bootstrap_hyperliquid_study(
        db, settings=cfg, now=now + timedelta(seconds=2)
    )

    assert first.created is True
    assert second.created is False
    assert first.study_id == second.study_id
    assert first.started_at == second.started_at == now
    assert first.strategy_slug == STRATEGY_SLUG
    assert first.strategy_code_sha == STRATEGY_CODE_SHA
    assert D(first.initial_nav_usd) == D("1000")
    assert db.scalar(select(func.count()).select_from(Strategy)) == 1
    assert db.scalar(select(func.count()).select_from(StrategyVersion)) == 1
    assert db.scalar(select(func.count()).select_from(Experiment)) == 1
    assert db.scalar(select(func.count()).select_from(ForwardStudy)) == 1
    study = db.get(ForwardStudy, first.study_id)
    nav_count = db.scalar(
        select(func.count())
        .select_from(__import__("app.forward_models", fromlist=["ForwardNavObservation"]).ForwardNavObservation)
        .where(
            __import__("app.forward_models", fromlist=["ForwardNavObservation"]).ForwardNavObservation.study_id
            == study.id
        )
    )
    assert nav_count == 1
    strategy = db.scalar(select(Strategy).where(Strategy.slug == STRATEGY_SLUG))
    version = db.get(StrategyVersion, study.strategy_version_id)
    assert strategy.status == "red"
    assert version.immutable is True and version.code_sha == STRATEGY_CODE_SHA
    db.close()


def test_bootstrap_refuses_environment_drift_for_existing_external_id():
    db = db_session()
    now = datetime.now(timezone.utc) - timedelta(seconds=5)
    ForwardOperationsService.bootstrap_hyperliquid_study(
        db, settings=settings(), now=now
    )

    changed = settings(hyperliquid_forward_paired_notional_usd=125)
    with pytest.raises(ForwardOperationsError, match="study_config"):
        ForwardOperationsService.bootstrap_hyperliquid_study(
            db, settings=changed, now=now + timedelta(seconds=1)
        )
    assert db.scalar(select(func.count()).select_from(ForwardStudy)) == 1
    db.close()


def test_daily_evaluator_writes_once_and_never_promotes_strategy_status():
    db = db_session()
    # Both evaluations must be in the past and on the same UTC calendar day.
    now = datetime(2025, 1, 15, 12, tzinfo=timezone.utc)
    boot = ForwardOperationsService.bootstrap_hyperliquid_study(
        db, settings=settings(), now=now - timedelta(days=1)
    )

    first = ForwardOperationsService.evaluate_due_studies(db, now=now)
    second = ForwardOperationsService.evaluate_due_studies(
        db, now=now + timedelta(minutes=10)
    )

    assert len(first) == 1 and first[0].action == "evaluated"
    assert first[0].recommendation in {"RED", "AMBER", "GREEN-1_CANDIDATE"}
    assert len(second) == 1 and second[0].action == "already_evaluated_today"
    assert db.scalar(select(func.count()).select_from(StrategyEvaluationRun)) == 1
    study = db.get(ForwardStudy, boot.study_id)
    version = db.get(StrategyVersion, study.strategy_version_id)
    strategy = db.get(Strategy, version.strategy_id)
    assert strategy.status == "red"
    db.close()


def test_status_reports_ready_after_fresh_market_snapshot_and_blocks_integrity_failure():
    db = db_session()
    now = datetime.now(timezone.utc) - timedelta(seconds=5)
    boot = ForwardOperationsService.bootstrap_hyperliquid_study(
        db, settings=settings(), now=now - timedelta(minutes=5)
    )
    db.add(
        HyperliquidPerpSnapshot(
            coin="BTC",
            mark_px=D("100"),
            mid_px=D("100"),
            oracle_px=D("100"),
            funding_rate_hourly=D("0.001"),
            premium=D("0"),
            open_interest=D("1000"),
            day_ntl_volume=D("1000000"),
            captured_at=now,
        )
    )
    db.commit()

    report = ForwardOperationsService.study_statuses(
        db, settings=settings(), external_id=boot.external_id, now=now
    )[0]
    assert report["operational_state"] == "ready"
    assert report["hard_reasons"] == []
    assert report["warnings"] == []
    assert report["strategy_status"] == "red"

    ForwardResearchService.record_incident(
        db,
        study_id=boot.study_id,
        external_key="test-integrity",
        severity="error",
        code="TEST_INTEGRITY",
        message="synthetic integrity failure",
        opened_at=now,
        data_integrity=True,
    )
    blocked = ForwardOperationsService.study_statuses(
        db, settings=settings(), external_id=boot.external_id, now=now
    )[0]
    assert blocked["operational_state"] == "blocked"
    assert "DATA_INTEGRITY_CONTAMINATED" in blocked["hard_reasons"]
    assert blocked["data_integrity_failure_count"] == 1
    db.close()


class NeverCalledClient:
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        async def fail(*args, **kwargs):
            self.calls += 1
            raise AssertionError(f"client method {name} must not be called")

        return fail


def test_operational_runner_makes_zero_market_calls_after_integrity_contamination():
    db = db_session()
    now = datetime.now(timezone.utc) - timedelta(seconds=5)
    boot = ForwardOperationsService.bootstrap_hyperliquid_study(
        db, settings=settings(), now=now - timedelta(minutes=5)
    )
    ForwardResearchService.record_incident(
        db,
        study_id=boot.study_id,
        external_key="permanent-integrity",
        severity="critical",
        code="DATA_LOSS",
        message="forward evidence is contaminated",
        opened_at=now,
        data_integrity=True,
    )
    client = NeverCalledClient()
    runner = OperationalHyperliquidCarryForwardRunner(
        client=client, health=HealthRegistry()
    )

    results = asyncio.run(runner.run_active_studies(db, now=now))

    assert len(results) == 1
    assert results[0].action == "blocked"
    assert "data-integrity" in results[0].detail
    assert client.calls == 0
    db.close()

