from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation import (
    EvidenceEvaluator,
    EvaluationError,
    EvaluationInput,
    EvaluationPolicy,
    ExecutionComparison,
    ForecastOutcome,
    NavObservation,
    TradeOutcome,
)
from app.evaluation_api import StrategyEvaluationRequest, evaluate_strategy
from app.evaluation_models import StrategyEvaluationRun
from app.models import Base, Strategy, StrategyVersion
import app.evaluation_models  # register evaluation table for in-memory metadata

D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(days=100)


def nav_series(drawdown: bool = False):
    rows = []
    for day in range(101):
        if drawdown:
            if day <= 30:
                value = D("1000") + D(day) * D("100") / D("30")
            elif day <= 60:
                value = D("1100") - D(day - 30) * D("200") / D("30")
            else:
                value = D("900") + D(day - 60) * D("150") / D("40")
        else:
            value = D("1000") + D(day) * D("0.4")
        rows.append(NavObservation(START + timedelta(days=day), value))
    return tuple(rows)


def profitable_trades(count: int = 60):
    trades = []
    for i in range(count):
        closed_at = START + timedelta(days=1 + (i % 90), minutes=i)
        if i % 2 == 0:
            gross = D("2.1")
            net = D("2")
        else:
            gross = D("-0.9")
            net = D("-1")
        trades.append(
            TradeOutcome(
                closed_at=closed_at,
                gross_pnl_usd=gross,
                net_pnl_usd=net,
                fees_usd=D("0.05"),
                slippage_usd=D("0.05"),
                allocated_capital_usd=D("100"),
                planned_loss_usd=D("2"),
            )
        )
    return tuple(trades)


def good_executions(count: int = 30):
    return tuple(
        ExecutionComparison(
            observed_at=START + timedelta(days=2 + (i % 90), minutes=i),
            side="buy" if i % 2 == 0 else "sell",
            intended_quantity=D("10"),
            paper_filled_quantity=D("10"),
            shadow_filled_quantity=D("10"),
            paper_average_price=D("100"),
            shadow_average_price=D("100.1"),
            paper_cost_usd=D("0.10"),
            shadow_cost_usd=D("0.12"),
        )
        for i in range(count)
    )


def calibrated_forecasts():
    rows = []
    day = 1
    for probability, yes_count, no_count in ((D("0.8"), 20, 5), (D("0.2"), 5, 20)):
        for outcome in [1] * yes_count + [0] * no_count:
            rows.append(
                ForecastOutcome(
                    resolved_at=START + timedelta(days=day),
                    probability=probability,
                    outcome=outcome,
                    market_probability=D("0.5"),
                )
            )
            day += 1
    return tuple(rows)


def base_input(*, family="funding", trades=None, nav=None, executions=None, forecasts=()):
    return EvaluationInput(
        strategy_slug="strategy-a",
        strategy_version="v1",
        family=family,
        forward_started_at=START,
        evaluated_at=END,
        nav_series=nav if nav is not None else nav_series(),
        trades=trades if trades is not None else profitable_trades(),
        executions=executions if executions is not None else good_executions(),
        forecasts=forecasts,
    )


def relaxed_policy(**overrides):
    values = dict(
        min_forward_days=90,
        min_nav_observations=60,
        min_shadow_observations=30,
        min_trades_default=60,
        min_trades_funding=60,
        min_trades_directional=60,
        min_trades_meme=60,
        min_forecasts_prediction=50,
        max_drawdown_pct=D("0.15"),
        min_profit_factor=D("1.30"),
        max_top3_profit_concentration=D("0.50"),
        cost_stress_multiplier=D("2"),
        min_shadow_fill_ratio=D("0.90"),
        max_shadow_p90_price_divergence_bps=D("50"),
        max_prediction_calibration_error=D("0.10"),
    )
    values.update(overrides)
    return EvaluationPolicy(**values)


def test_funding_strategy_can_only_become_green1_candidate_after_all_gates():
    result = EvidenceEvaluator(relaxed_policy()).evaluate(base_input())
    assert result.recommendation == "GREEN-1_CANDIDATE"
    assert result.reasons == ("ALL_PRE_REGISTERED_FORWARD_GATES_PASSED",)
    assert result.performance.nav_observation_count == 101
    assert result.performance.trade_count == 60
    assert result.performance.net_pnl_usd == D("30")
    assert result.performance.stressed_net_pnl_usd == D("24.0")
    assert result.performance.profit_factor == D("2")
    assert result.performance.top3_profit_concentration == D("0.1")
    assert result.performance.max_drawdown_pct == D("0")
    assert result.execution.observation_count == 30
    assert result.execution.mean_shadow_fill_ratio == D("1")
    assert result.execution.p90_absolute_price_divergence_bps == D("10.0")


def test_insufficient_forward_days_is_amber():
    end = START + timedelta(days=40)
    evaluation = EvaluationInput(
        strategy_slug="strategy-a",
        strategy_version="v1",
        family="funding",
        forward_started_at=START,
        evaluated_at=end,
        nav_series=tuple(x for x in nav_series() if x.observed_at <= end),
        trades=tuple(x for x in profitable_trades(20) if x.closed_at <= end),
        executions=tuple(x for x in good_executions(10) if x.observed_at <= end),
    )
    result = EvidenceEvaluator(
        relaxed_policy(min_nav_observations=20, min_shadow_observations=10, min_trades_funding=10)
    ).evaluate(evaluation)
    assert result.recommendation == "AMBER"
    assert "INSUFFICIENT_FORWARD_DAYS" in result.reasons


def test_cost_stress_failure_is_red_even_when_observed_net_is_positive():
    trades = []
    for i in range(60):
        gross = D("1.5") if i % 2 == 0 else D("-0.5")
        fees = D("0.20")
        slippage = D("0.20")
        trades.append(
            TradeOutcome(
                closed_at=START + timedelta(days=1 + i),
                gross_pnl_usd=gross,
                net_pnl_usd=gross - fees - slippage,
                fees_usd=fees,
                slippage_usd=slippage,
                allocated_capital_usd=D("100"),
                planned_loss_usd=D("2"),
            )
        )
    result = EvidenceEvaluator(relaxed_policy()).evaluate(base_input(trades=tuple(trades)))
    assert result.performance.net_pnl_usd == D("6.0")
    assert result.performance.stressed_net_pnl_usd == D("-18.0")
    assert result.recommendation == "RED"
    assert "FAILS_COST_STRESS" in result.reasons


def test_drawdown_above_gate_is_red():
    result = EvidenceEvaluator(relaxed_policy()).evaluate(base_input(nav=nav_series(drawdown=True)))
    assert result.performance.max_drawdown_pct > D("0.15")
    assert result.recommendation == "RED"
    assert "MAX_DRAWDOWN_EXCEEDED" in result.reasons


def test_tiny_nav_or_shadow_samples_cannot_be_green():
    result = EvidenceEvaluator(relaxed_policy()).evaluate(
        base_input(nav=nav_series()[:10], executions=good_executions(3))
    )
    assert result.recommendation == "AMBER"
    assert "INSUFFICIENT_NAV_OBSERVATIONS" in result.reasons
    assert "INSUFFICIENT_SHADOW_SAMPLE" in result.reasons


def test_no_trades_and_no_nav_history_cannot_be_green():
    result = EvidenceEvaluator(relaxed_policy()).evaluate(base_input(trades=(), nav=()))
    assert result.recommendation == "AMBER"
    assert "NO_CLOSED_TRADES" in result.reasons
    assert "INSUFFICIENT_NAV_SERIES" in result.reasons


def test_critical_incident_and_data_integrity_failure_are_red():
    evaluation = base_input()
    evaluation = EvaluationInput(**{**evaluation.__dict__, "unresolved_critical_incidents": 1, "data_integrity_failures": 1})
    result = EvidenceEvaluator(relaxed_policy()).evaluate(evaluation)
    assert result.recommendation == "RED"
    assert "UNRESOLVED_CRITICAL_INCIDENT" in result.reasons
    assert "DATA_INTEGRITY_FAILURE" in result.reasons


def test_bad_shadow_execution_keeps_strategy_amber():
    bad = tuple(
        ExecutionComparison(
            observed_at=START + timedelta(days=2 + i),
            side="buy",
            intended_quantity=D("10"),
            paper_filled_quantity=D("10"),
            shadow_filled_quantity=D("5"),
            paper_average_price=D("100"),
            shadow_average_price=D("102"),
            paper_cost_usd=D("0.1"),
            shadow_cost_usd=D("0.5"),
        )
        for i in range(30)
    )
    result = EvidenceEvaluator(relaxed_policy()).evaluate(base_input(executions=bad))
    assert result.recommendation == "AMBER"
    assert "SHADOW_FILL_RATIO_BELOW_GATE" in result.reasons
    assert "PAPER_SHADOW_PRICE_DIVERGENCE" in result.reasons


def test_evidence_outside_declared_forward_window_is_rejected():
    leaked_nav = nav_series() + (NavObservation(START - timedelta(days=1), D("999")),)
    with pytest.raises(EvaluationError, match="inside the declared forward window"):
        EvidenceEvaluator(relaxed_policy()).evaluate(base_input(nav=leaked_nav))


def test_trade_pnl_must_reconcile_to_gross_minus_costs():
    trade = profitable_trades(1)[0]
    broken = TradeOutcome(
        closed_at=trade.closed_at,
        gross_pnl_usd=trade.gross_pnl_usd,
        net_pnl_usd=D("999"),
        fees_usd=trade.fees_usd,
        slippage_usd=trade.slippage_usd,
        allocated_capital_usd=trade.allocated_capital_usd,
        planned_loss_usd=trade.planned_loss_usd,
    )
    with pytest.raises(EvaluationError, match="reconcile"):
        EvidenceEvaluator(relaxed_policy(min_trades_funding=1)).evaluate(base_input(trades=(broken,)))


def test_prediction_strategy_needs_calibration_and_complete_market_baseline():
    forecasts = calibrated_forecasts()
    good = EvidenceEvaluator(relaxed_policy()).evaluate(base_input(family="prediction", forecasts=forecasts))
    assert good.prediction.forecast_count == 50
    assert good.prediction.calibration_error == D("0.0")
    assert good.prediction.brier_score == D("0.16")
    assert good.prediction.market_brier_score == D("0.25")
    assert good.prediction.brier_improvement_vs_market == D("0.09")
    assert good.recommendation == "GREEN-1_CANDIDATE"

    partial_baseline = list(forecasts)
    first = partial_baseline[0]
    partial_baseline[0] = ForecastOutcome(first.resolved_at, first.probability, first.outcome, None)
    amber = EvidenceEvaluator(relaxed_policy()).evaluate(
        base_input(family="prediction", forecasts=tuple(partial_baseline))
    )
    assert amber.recommendation == "AMBER"
    assert "MISSING_MARKET_BRIER_BASELINE" in amber.reasons
    assert amber.prediction.market_brier_score is None


def registered_request():
    return StrategyEvaluationRequest.model_validate(
        {
            "strategy_slug": "strategy-a",
            "strategy_version": "v1",
            "family": "funding",
            "forward_started_at": START,
            "evaluated_at": END,
            "nav_series": [{"observed_at": x.observed_at, "nav_usd": x.nav_usd} for x in nav_series()],
            "trades": [
                {
                    "closed_at": x.closed_at,
                    "gross_pnl_usd": x.gross_pnl_usd,
                    "net_pnl_usd": x.net_pnl_usd,
                    "fees_usd": x.fees_usd,
                    "slippage_usd": x.slippage_usd,
                    "allocated_capital_usd": x.allocated_capital_usd,
                    "planned_loss_usd": x.planned_loss_usd,
                }
                for x in profitable_trades()
            ],
            "executions": [
                {
                    "observed_at": x.observed_at,
                    "side": x.side,
                    "intended_quantity": x.intended_quantity,
                    "paper_filled_quantity": x.paper_filled_quantity,
                    "shadow_filled_quantity": x.shadow_filled_quantity,
                    "paper_average_price": x.paper_average_price,
                    "shadow_average_price": x.shadow_average_price,
                    "paper_cost_usd": x.paper_cost_usd,
                    "shadow_cost_usd": x.shadow_cost_usd,
                }
                for x in good_executions()
            ],
        }
    )


def test_evaluation_api_requires_registered_version_and_never_mutates_strategy_status():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    request = registered_request()

    with pytest.raises(HTTPException) as missing_strategy:
        evaluate_strategy(request, db)
    assert missing_strategy.value.status_code == 422

    strategy = Strategy(slug="strategy-a", name="Strategy A", status="red")
    db.add(strategy)
    db.commit()
    with pytest.raises(HTTPException) as missing_version:
        evaluate_strategy(request, db)
    assert missing_version.value.status_code == 422

    version = StrategyVersion(strategy_id=strategy.id, version="v1", config_json="{}", immutable=True)
    db.add(version)
    db.commit()
    response = evaluate_strategy(request, db)
    stored = db.scalar(select(StrategyEvaluationRun).where(StrategyEvaluationRun.external_run_id == response["run_id"]))
    db.refresh(strategy)
    assert stored is not None
    assert stored.strategy_version_id == version.id
    assert stored.recommendation == "GREEN-1_CANDIDATE"
    assert strategy.status == "red"
    assert response["safety"]["recommendation_only"] is True
    assert response["safety"]["can_promote_strategy"] is False
    assert response["safety"]["can_enable_signer"] is False
    assert response["safety"]["can_authorize_capital"] is False
    db.close()
