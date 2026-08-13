import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.evaluation import EvidenceEvaluator, EvaluationInput, EvaluationPolicy, ExecutionComparison, NavObservation, TradeOutcome
from app.forward_research import ForwardResearchError, ForwardResearchService
from app.models import Base, Experiment, Strategy, StrategyVersion
import app.evaluation_models
import app.forward_models

D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def policy(**overrides):
    values = dict(
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
        max_nav_gap_days=D("2"),
    )
    values.update(overrides)
    return EvaluationPolicy(**values)


def registered_study(db: Session):
    strategy = Strategy(slug="integrity-funding", name="Integrity Funding", status="red")
    db.add(strategy); db.commit()
    version = StrategyVersion(strategy_id=strategy.id, version="v1", config_json="{}", immutable=True)
    db.add(version); db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="forward integrity test",
        data_version="v1",
        train_window="historical",
        validation_window="forward",
        holdout_window="future",
        search_space_json="{}",
        status="registered",
    )
    db.add(experiment); db.commit()
    study = ForwardResearchService.create_study(
        db,
        external_id="integrity-study",
        strategy_slug=strategy.slug,
        strategy_version=version.version,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        initial_capital_usd=D("1000"),
        evaluation_policy=policy(),
        study_config={"horizon_hours": 24},
        started_at=START,
    )
    return strategy, version, experiment, study


def trade_kwargs(study_id: str):
    return dict(
        study_id=study_id,
        external_key="trade-1",
        opened_at=START + timedelta(hours=1),
        closed_at=START + timedelta(days=1),
        gross_pnl_usd=D("2.1"),
        net_pnl_usd=D("2"),
        fees_usd=D("0.05"),
        slippage_usd=D("0.05"),
        allocated_capital_usd=D("100"),
        planned_loss_usd=D("2"),
        metadata={"source": "runner-v1"},
    )


def test_study_retry_must_match_frozen_definition_exactly():
    db = session(); strategy, version, experiment, study = registered_study(db)
    retry = ForwardResearchService.create_study(
        db,
        external_id=study.external_id,
        strategy_slug=strategy.slug,
        strategy_version=version.version,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        initial_capital_usd=D("1000"),
        evaluation_policy=policy(),
        study_config={"horizon_hours": 24},
        started_at=START,
    )
    assert retry.id == study.id
    with pytest.raises(ForwardResearchError, match="conflicting retry"):
        ForwardResearchService.create_study(
            db,
            external_id=study.external_id,
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            experiment_id=experiment.id,
            family="funding",
            venue="hyperliquid",
            instrument="BTC",
            initial_capital_usd=D("1000"),
            evaluation_policy=policy(max_nav_gap_days=D("1")),
            study_config={"horizon_hours": 24},
            started_at=START,
        )
    db.close()


def test_trade_execution_forecast_and_incident_retries_reject_changed_payloads():
    db = session(); _, _, _, study = registered_study(db)
    trade = ForwardResearchService.record_trade(db, **trade_kwargs(study.id))
    assert ForwardResearchService.record_trade(db, **trade_kwargs(study.id)).id == trade.id
    changed_trade = trade_kwargs(study.id); changed_trade["metadata"] = {"source": "tampered"}
    with pytest.raises(ForwardResearchError, match="conflicting retry"):
        ForwardResearchService.record_trade(db, **changed_trade)

    execution = ForwardResearchService.record_execution(
        db,
        study_id=study.id,
        external_key="exec-1",
        observed_at=START + timedelta(hours=2),
        side="buy",
        intended_quantity=D("1"),
        paper_filled_quantity=D("1"),
        shadow_filled_quantity=D("1"),
        paper_average_price=D("100"),
        shadow_average_price=D("100.1"),
        paper_cost_usd=D("0.1"),
        shadow_cost_usd=D("0.12"),
        trade_id=trade.id,
        metadata={"leg": "spot"},
    )
    assert execution.external_key == "exec-1"
    with pytest.raises(ForwardResearchError, match="conflicting retry"):
        ForwardResearchService.record_execution(
            db,
            study_id=study.id,
            external_key="exec-1",
            observed_at=START + timedelta(hours=2),
            side="buy",
            intended_quantity=D("1"),
            paper_filled_quantity=D("1"),
            shadow_filled_quantity=D("0.5"),
            paper_average_price=D("100"),
            shadow_average_price=D("100.1"),
            paper_cost_usd=D("0.1"),
            shadow_cost_usd=D("0.12"),
            trade_id=trade.id,
            metadata={"leg": "spot"},
        )

    forecast = ForwardResearchService.record_forecast(
        db,
        study_id=study.id,
        external_key="forecast-1",
        resolved_at=START + timedelta(days=1),
        probability=D("0.7"),
        outcome=1,
        market_probability=D("0.6"),
        metadata={"market": "x"},
    )
    assert forecast.external_key == "forecast-1"
    with pytest.raises(ForwardResearchError, match="conflicting retry"):
        ForwardResearchService.record_forecast(
            db,
            study_id=study.id,
            external_key="forecast-1",
            resolved_at=START + timedelta(days=1),
            probability=D("0.8"),
            outcome=1,
            market_probability=D("0.6"),
            metadata={"market": "x"},
        )

    incident = ForwardResearchService.record_incident(
        db,
        study_id=study.id,
        external_key="incident-1",
        severity="warning",
        code="FEED_DELAY",
        message="delayed feed",
        opened_at=START + timedelta(hours=3),
    )
    assert incident.external_key == "incident-1"
    with pytest.raises(ForwardResearchError, match="conflicting retry"):
        ForwardResearchService.record_incident(
            db,
            study_id=study.id,
            external_key="incident-1",
            severity="critical",
            code="FEED_DELAY",
            message="delayed feed",
            opened_at=START + timedelta(hours=3),
        )
    db.close()


def test_completion_retry_is_idempotent_and_cannot_extend_evaluation_period():
    db = session(); _, _, _, study = registered_study(db)
    completed_at = START + timedelta(days=2)
    completed = ForwardResearchService.complete_study(db, study_id=study.id, completed_at=completed_at)
    assert ForwardResearchService.complete_study(db, study_id=study.id, completed_at=completed_at).id == completed.id
    with pytest.raises(ForwardResearchError, match="conflicting retry"):
        ForwardResearchService.complete_study(db, study_id=study.id, completed_at=START + timedelta(days=3))
    with pytest.raises(ForwardResearchError, match="cannot exceed completed study period"):
        ForwardResearchService.build_evaluation_input(db, study_id=study.id, evaluated_at=START + timedelta(days=90))
    db.close()


def test_future_dated_study_or_evaluation_cutoff_is_rejected():
    db = session(); strategy, version, experiment, study = registered_study(db)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(ForwardResearchError, match="future"):
        ForwardResearchService.create_study(
            db,
            external_id="future-study",
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            experiment_id=experiment.id,
            family="funding",
            venue="hyperliquid",
            instrument="BTC",
            initial_capital_usd=D("1000"),
            evaluation_policy=policy(),
            study_config={},
            started_at=future,
        )
    with pytest.raises(ForwardResearchError, match="future"):
        ForwardResearchService.build_evaluation_input(db, study_id=study.id, evaluated_at=future)
    db.close()


def test_nav_blackout_keeps_otherwise_sufficient_study_amber():
    nav = tuple(
        [NavObservation(START + timedelta(days=i), D("1000") + D(i)) for i in range(60)]
        + [NavObservation(START + timedelta(days=100), D("1100"))]
    )
    trades = tuple(
        TradeOutcome(
            closed_at=START + timedelta(days=1 + i),
            gross_pnl_usd=D("1.1"),
            net_pnl_usd=D("1"),
            fees_usd=D("0.05"),
            slippage_usd=D("0.05"),
            allocated_capital_usd=D("100"),
            planned_loss_usd=D("2"),
        )
        for i in range(60)
    )
    executions = tuple(
        ExecutionComparison(
            observed_at=START + timedelta(days=1 + i),
            side="buy",
            intended_quantity=D("1"),
            paper_filled_quantity=D("1"),
            shadow_filled_quantity=D("1"),
            paper_average_price=D("100"),
            shadow_average_price=D("100.1"),
            paper_cost_usd=D("0.1"),
            shadow_cost_usd=D("0.1"),
        )
        for i in range(30)
    )
    evaluation = EvaluationInput(
        strategy_slug="x",
        strategy_version="v1",
        family="funding",
        forward_started_at=START,
        evaluated_at=START + timedelta(days=100),
        nav_series=nav,
        trades=trades,
        executions=executions,
    )
    result = EvidenceEvaluator(
        EvaluationPolicy(
            min_forward_days=90,
            min_nav_observations=60,
            min_shadow_observations=30,
            min_trades_funding=60,
            max_nav_gap_days=D("3"),
            max_top3_profit_concentration=D("1"),
        )
    ).evaluate(evaluation)
    assert result.performance.nav_observation_count >= 60
    assert result.performance.max_nav_gap_days > D("3")
    assert result.recommendation == "AMBER"
    assert "NAV_COVERAGE_GAP" in result.reasons
