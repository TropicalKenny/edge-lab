from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
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
from app.evaluation_models import StrategyEvaluationRun

router = APIRouter(prefix="/evaluation", tags=["forward-evidence"])
settings = get_settings()


class NavObservationRequest(BaseModel):
    observed_at: datetime
    nav_usd: Decimal = Field(gt=0)


class TradeOutcomeRequest(BaseModel):
    closed_at: datetime
    gross_pnl_usd: Decimal
    net_pnl_usd: Decimal
    fees_usd: Decimal = Field(ge=0)
    slippage_usd: Decimal = Field(ge=0)
    allocated_capital_usd: Decimal = Field(gt=0)
    planned_loss_usd: Decimal = Field(gt=0)


class ExecutionComparisonRequest(BaseModel):
    observed_at: datetime
    side: Literal["buy", "sell"]
    intended_quantity: Decimal = Field(gt=0)
    paper_filled_quantity: Decimal = Field(ge=0)
    shadow_filled_quantity: Decimal = Field(ge=0)
    paper_average_price: Decimal | None = Field(default=None, gt=0)
    shadow_average_price: Decimal | None = Field(default=None, gt=0)
    paper_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    shadow_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)


class ForecastOutcomeRequest(BaseModel):
    resolved_at: datetime
    probability: Decimal = Field(ge=0, le=1)
    outcome: Literal[0, 1]
    market_probability: Decimal | None = Field(default=None, ge=0, le=1)


class StrategyEvaluationRequest(BaseModel):
    strategy_slug: str = Field(min_length=1, max_length=100)
    strategy_version: str = Field(min_length=1, max_length=64)
    family: Literal["funding", "prediction", "directional", "meme", "other"]
    forward_started_at: datetime
    evaluated_at: datetime
    nav_series: list[NavObservationRequest] = Field(default_factory=list)
    trades: list[TradeOutcomeRequest] = Field(default_factory=list)
    executions: list[ExecutionComparisonRequest] = Field(default_factory=list)
    forecasts: list[ForecastOutcomeRequest] = Field(default_factory=list)
    unresolved_critical_incidents: int = Field(default=0, ge=0)
    data_integrity_failures: int = Field(default=0, ge=0)


def evaluation_policy() -> EvaluationPolicy:
    return EvaluationPolicy(
        min_forward_days=settings.evaluation_min_forward_days,
        min_trades_default=settings.evaluation_min_trades_default,
        min_trades_funding=settings.evaluation_min_trades_funding,
        min_trades_directional=settings.evaluation_min_trades_directional,
        min_trades_meme=settings.evaluation_min_trades_meme,
        min_forecasts_prediction=settings.evaluation_min_forecasts_prediction,
        max_drawdown_pct=Decimal(str(settings.evaluation_max_drawdown_pct)),
        min_profit_factor=Decimal(str(settings.evaluation_min_profit_factor)),
        max_top3_profit_concentration=Decimal(str(settings.evaluation_max_top3_profit_concentration)),
        cost_stress_multiplier=Decimal(str(settings.evaluation_cost_stress_multiplier)),
        min_shadow_fill_ratio=Decimal(str(settings.evaluation_min_shadow_fill_ratio)),
        max_shadow_p90_price_divergence_bps=Decimal(str(settings.evaluation_max_shadow_p90_price_divergence_bps)),
        max_prediction_calibration_error=Decimal(str(settings.evaluation_max_prediction_calibration_error)),
    )


def _domain(request: StrategyEvaluationRequest) -> EvaluationInput:
    return EvaluationInput(
        strategy_slug=request.strategy_slug,
        strategy_version=request.strategy_version,
        family=request.family,
        forward_started_at=request.forward_started_at,
        evaluated_at=request.evaluated_at,
        nav_series=tuple(NavObservation(**item.model_dump()) for item in request.nav_series),
        trades=tuple(TradeOutcome(**item.model_dump()) for item in request.trades),
        executions=tuple(ExecutionComparison(**item.model_dump()) for item in request.executions),
        forecasts=tuple(ForecastOutcome(**item.model_dump()) for item in request.forecasts),
        unresolved_critical_incidents=request.unresolved_critical_incidents,
        data_integrity_failures=request.data_integrity_failures,
    )


def _json(value) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _persist(db: Session, run_id: str, request: StrategyEvaluationRequest, result, policy: EvaluationPolicy) -> None:
    metrics = {
        "performance": asdict(result.performance),
        "execution": asdict(result.execution),
        "prediction": asdict(result.prediction),
    }
    db.add(
        StrategyEvaluationRun(
            external_run_id=run_id,
            strategy_slug=request.strategy_slug,
            strategy_version=request.strategy_version,
            family=request.family,
            recommendation=result.recommendation,
            forward_started_at=request.forward_started_at,
            evaluated_at=request.evaluated_at,
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
            policy_json=_json(asdict(policy)),
            metrics_json=_json(metrics),
            reasons_json=_json(list(result.reasons)),
            input_json=request.model_dump_json(),
            created_at=result.created_at,
        )
    )
    db.commit()


@router.post("/strategy")
def evaluate_strategy(request: StrategyEvaluationRequest, db: Session = Depends(get_db)):
    policy = evaluation_policy()
    evaluator = EvidenceEvaluator(policy)
    run_id = str(uuid.uuid4())
    try:
        result = evaluator.evaluate(_domain(request))
        _persist(db, run_id, request, result, policy)
    except EvaluationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return {
        "run_id": run_id,
        **asdict(result),
        "safety": {
            "recommendation_only": True,
            "can_promote_strategy": False,
            "can_enable_signer": False,
            "can_authorize_capital": False,
            "live_trading": False,
        },
    }


@router.get("/runs/{run_id}")
def get_evaluation_run(run_id: str, db: Session = Depends(get_db)):
    row = db.scalar(select(StrategyEvaluationRun).where(StrategyEvaluationRun.external_run_id == run_id))
    if row is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


@router.get("/status")
def evaluation_status():
    return {
        "mode": "forward-research-only",
        "recommendation_values": ["RED", "AMBER", "GREEN-1_CANDIDATE"],
        "can_promote_strategy": False,
        "can_enable_signer": False,
        "can_authorize_capital": False,
        "minimum_forward_days": settings.evaluation_min_forward_days,
    }
