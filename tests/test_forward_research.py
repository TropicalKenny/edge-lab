import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation import EvaluationPolicy
from app.evaluation_models import StrategyEvaluationRun
from app.forward_api import require_forward_secret
from app.forward_models import ForwardNavObservation, ForwardStudy
from app.forward_research import ForwardResearchError, ForwardResearchService, policy_from_json
from app.models import Base, Experiment, Strategy, StrategyVersion
import app.evaluation_models
import app.forward_models

D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def registered(db: Session):
    strategy = Strategy(slug="funding-forward", name="Funding Forward", status="red")
    db.add(strategy)
    db.commit()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="v1",
        config_json=json.dumps({"horizon_hours": 24}),
        immutable=True,
    )
    db.add(version)
    db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="Positive funding carry remains profitable after realistic costs.",
        data_version="forward-v1",
        train_window="historical-only",
        validation_window="paper-forward",
        holdout_window="future-forward",
        search_space_json="{}",
        status="registered",
    )
    db.add(experiment)
    db.commit()
    return strategy, version, experiment


def small_policy():
    return EvaluationPolicy(
        min_forward_days=2,
        min_nav_observations=3,
        min_shadow_observations=1,
        min_trades_default=2,
        min_trades_funding=2,
        min_trades_directional=2,
        min_trades_meme=2,
        min_forecasts_prediction=2,
        max_drawdown_pct=D("0.15"),
        min_profit_factor=D("1.30"),
        max_top3_profit_concentration=D("1"),
        cost_stress_multiplier=D("2"),
        min_shadow_fill_ratio=D("0.90"),
        max_shadow_p90_price_divergence_bps=D("50"),
        max_prediction_calibration_error=D("0.10"),
    )


def create_study(db: Session):
    strategy, version, experiment = registered(db)
    study = ForwardResearchService.create_study(
        db,
        external_id="funding-forward-v1-2026",
        strategy_slug=strategy.slug,
        strategy_version=version.version,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        initial_capital_usd=D("1000"),
        evaluation_policy=small_policy(),
        study_config={"horizon_hours": 24, "notional_usd": "100"},
        started_at=START,
    )
    return strategy, version, experiment, study


def add_green_evidence(db: Session, study_id: str):
    for day, nav in ((0, "1000"), (1, "1001"), (2, "1001")):
        ForwardResearchService.record_nav(
            db,
            study_id=study_id,
            observed_at=START + timedelta(days=day),
            nav_usd=D(nav),
        )
    ForwardResearchService.record_trade(
        db,
        study_id=study_id,
        external_key="trade-win",
        opened_at=START + timedelta(hours=1),
        closed_at=START + timedelta(days=1),
        gross_pnl_usd=D("2.1"),
        net_pnl_usd=D("2"),
        fees_usd=D("0.05"),
        slippage_usd=D("0.05"),
        allocated_capital_usd=D("100"),
        planned_loss_usd=D("2"),
    )
    ForwardResearchService.record_trade(
        db,
        study_id=study_id,
        external_key="trade-loss",
        opened_at=START + timedelta(days=1, hours=1),
        closed_at=START + timedelta(days=2),
        gross_pnl_usd=D("-0.9"),
        net_pnl_usd=D("-1"),
        fees_usd=D("0.05"),
        slippage_usd=D("0.05"),
        allocated_capital_usd=D("100"),
        planned_loss_usd=D("2"),
    )
    ForwardResearchService.record_execution(
        db,
        study_id=study_id,
        external_key="entry-shadow-1",
        observed_at=START + timedelta(hours=1),
        side="buy",
        intended_quantity=D("1"),
        paper_filled_quantity=D("1"),
        shadow_filled_quantity=D("1"),
        paper_average_price=D("100"),
        shadow_average_price=D("100.1"),
        paper_cost_usd=D("0.10"),
        shadow_cost_usd=D("0.12"),
    )


def test_study_freezes_policy_and_links_registered_experiment_version():
    db = db_session()
    strategy, version, experiment, study = create_study(db)
    frozen = policy_from_json(study.evaluation_policy_json)
    assert study.strategy_version_id == version.id
    assert study.experiment_id == experiment.id
    assert frozen.min_forward_days == 2
    assert frozen.min_nav_observations == 3
    assert json.loads(study.study_config_json)["horizon_hours"] == 24
    assert strategy.status == "red"
    db.close()


def test_forward_study_rejects_unregistered_or_wrong_experiment():
    db = db_session()
    with pytest.raises(ForwardResearchError, match="strategy must be registered"):
        ForwardResearchService.create_study(
            db,
            external_id="missing",
            strategy_slug="missing",
            strategy_version="v1",
            experiment_id="missing",
            family="funding",
            venue="hyperliquid",
            instrument="BTC",
            initial_capital_usd=D("1000"),
            evaluation_policy=small_policy(),
            study_config={},
            started_at=START,
        )
    strategy, version, experiment = registered(db)
    other = Strategy(slug="other", name="Other")
    db.add(other); db.commit()
    other_version = StrategyVersion(strategy_id=other.id, version="v1", config_json="{}", immutable=True)
    db.add(other_version); db.commit()
    with pytest.raises(ForwardResearchError, match="does not belong"):
        ForwardResearchService.create_study(
            db,
            external_id="wrong-exp",
            strategy_slug=other.slug,
            strategy_version=other_version.version,
            experiment_id=experiment.id,
            family="funding",
            venue="hyperliquid",
            instrument="BTC",
            initial_capital_usd=D("1000"),
            evaluation_policy=small_policy(),
            study_config={},
            started_at=START,
        )
    db.close()


def test_nav_retry_is_idempotent_but_conflicting_retry_fails():
    db = db_session(); _, _, _, study = create_study(db)
    first = ForwardResearchService.record_nav(db, study_id=study.id, observed_at=START, nav_usd=D("1000"))
    retry = ForwardResearchService.record_nav(db, study_id=study.id, observed_at=START, nav_usd=D("1000"))
    assert retry.id == first.id
    assert db.scalar(select(ForwardNavObservation).where(ForwardNavObservation.study_id == study.id)) is not None
    with pytest.raises(ForwardResearchError, match="conflicting NAV"):
        ForwardResearchService.record_nav(db, study_id=study.id, observed_at=START, nav_usd=D("999"))
    db.close()


def test_bad_trade_pnl_is_rejected_before_entering_forward_dataset():
    db = db_session(); _, _, _, study = create_study(db)
    with pytest.raises(ForwardResearchError, match="does not reconcile"):
        ForwardResearchService.record_trade(
            db,
            study_id=study.id,
            external_key="bad",
            opened_at=START,
            closed_at=START + timedelta(hours=1),
            gross_pnl_usd=D("2"),
            net_pnl_usd=D("999"),
            fees_usd=D("0.1"),
            slippage_usd=D("0.1"),
            allocated_capital_usd=D("100"),
            planned_loss_usd=D("2"),
        )
    db.close()


def test_database_backed_study_evaluates_with_frozen_policy_without_promoting_strategy():
    db = db_session(); strategy, version, _, study = create_study(db)
    add_green_evidence(db, study.id)
    run_id, result = ForwardResearchService.evaluate_study(
        db,
        study_id=study.id,
        evaluated_at=START + timedelta(days=2),
    )
    stored = db.scalar(select(StrategyEvaluationRun).where(StrategyEvaluationRun.external_run_id == run_id))
    db.refresh(strategy)
    assert result.recommendation == "GREEN-1_CANDIDATE"
    assert stored is not None and stored.strategy_version_id == version.id
    assert json.loads(stored.policy_json)["min_forward_days"] == 2
    assert strategy.status == "red"
    db.close()


def test_data_integrity_incident_forces_red_even_after_resolution():
    db = db_session(); _, _, _, study = create_study(db)
    add_green_evidence(db, study.id)
    ForwardResearchService.record_incident(
        db,
        study_id=study.id,
        external_key="bad-feed",
        severity="error",
        code="BAD_FEED",
        message="source emitted inconsistent prices",
        opened_at=START + timedelta(hours=2),
        data_integrity=True,
    )
    ForwardResearchService.resolve_incident(
        db,
        study_id=study.id,
        external_key="bad-feed",
        resolved_at=START + timedelta(hours=3),
    )
    _, result = ForwardResearchService.evaluate_study(db, study_id=study.id, evaluated_at=START + timedelta(days=2))
    assert result.recommendation == "RED"
    assert "DATA_INTEGRITY_FAILURE" in result.reasons
    db.close()


def test_completed_study_is_read_only():
    db = db_session(); _, _, _, study = create_study(db)
    ForwardResearchService.complete_study(db, study_id=study.id, completed_at=START + timedelta(days=2))
    with pytest.raises(ForwardResearchError, match="not active"):
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=START + timedelta(days=2),
            nav_usd=D("1000"),
        )
    db.close()


def test_forward_write_api_is_disabled_without_internal_secret():
    with pytest.raises(HTTPException) as exc:
        require_forward_secret(None)
    assert exc.value.status_code == 503


def test_forward_study_row_defaults_to_active():
    db = db_session(); _, _, _, study = create_study(db)
    row = db.scalar(select(ForwardStudy).where(ForwardStudy.id == study.id))
    assert row is not None and row.status == "active"
    db.close()
