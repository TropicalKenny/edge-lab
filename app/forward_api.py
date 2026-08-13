from __future__ import annotations

import hmac
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.evaluation_api import evaluation_policy
from app.forward_research import ForwardResearchError, ForwardResearchService

router = APIRouter(prefix="/forward", tags=["forward-research"])
settings = get_settings()


def require_forward_secret(x_edge_research_secret: str | None = Header(default=None)) -> None:
    configured = settings.forward_ingest_secret
    if not configured:
        raise HTTPException(status_code=503, detail="forward research writes are disabled")
    if x_edge_research_secret is None or not hmac.compare_digest(x_edge_research_secret, configured):
        raise HTTPException(status_code=401, detail="invalid forward research credential")


class StudyCreateRequest(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    strategy_slug: str = Field(min_length=1, max_length=100)
    strategy_version: str = Field(min_length=1, max_length=64)
    experiment_id: str = Field(min_length=1, max_length=36)
    family: Literal["funding", "prediction", "directional", "meme", "other"]
    venue: str = Field(min_length=1, max_length=64)
    instrument: str = Field(min_length=1, max_length=120)
    initial_capital_usd: Decimal = Field(gt=0)
    study_config: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NavRequest(BaseModel):
    observed_at: datetime
    nav_usd: Decimal = Field(gt=0)
    source: str = Field(default="forward-runner", min_length=1, max_length=64)


class TradeRequest(BaseModel):
    external_key: str = Field(min_length=1, max_length=140)
    opened_at: datetime
    closed_at: datetime
    gross_pnl_usd: Decimal
    net_pnl_usd: Decimal
    fees_usd: Decimal = Field(ge=0)
    slippage_usd: Decimal = Field(ge=0)
    allocated_capital_usd: Decimal = Field(gt=0)
    planned_loss_usd: Decimal = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionRequest(BaseModel):
    external_key: str = Field(min_length=1, max_length=160)
    observed_at: datetime
    side: Literal["buy", "sell"]
    intended_quantity: Decimal = Field(gt=0)
    paper_filled_quantity: Decimal = Field(ge=0)
    shadow_filled_quantity: Decimal = Field(ge=0)
    paper_average_price: Decimal | None = Field(default=None, gt=0)
    shadow_average_price: Decimal | None = Field(default=None, gt=0)
    paper_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    shadow_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    trade_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ForecastRequest(BaseModel):
    external_key: str = Field(min_length=1, max_length=160)
    resolved_at: datetime
    probability: Decimal = Field(ge=0, le=1)
    outcome: Literal[0, 1]
    market_probability: Decimal | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentRequest(BaseModel):
    external_key: str = Field(min_length=1, max_length=160)
    severity: Literal["info", "warning", "error", "critical"]
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1)
    opened_at: datetime
    data_integrity: bool = False


class ResolveIncidentRequest(BaseModel):
    resolved_at: datetime


class EvaluateStudyRequest(BaseModel):
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CompleteStudyRequest(BaseModel):
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _row(row) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _service_error(exc: ForwardResearchError) -> HTTPException:
    status = 404 if "not found" in str(exc).lower() else 422
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/status")
def forward_status():
    return {
        "mode": "frozen-forward-research-only",
        "write_ingest_enabled": bool(settings.forward_ingest_secret),
        "policy_frozen_at_study_start": True,
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
    }


@router.post("/studies", dependencies=[Depends(require_forward_secret)])
def create_study(request: StudyCreateRequest, db: Session = Depends(get_db)):
    try:
        study = ForwardResearchService.create_study(
            db,
            external_id=request.external_id,
            strategy_slug=request.strategy_slug,
            strategy_version=request.strategy_version,
            experiment_id=request.experiment_id,
            family=request.family,
            venue=request.venue,
            instrument=request.instrument,
            initial_capital_usd=request.initial_capital_usd,
            evaluation_policy=evaluation_policy(),
            study_config=request.study_config,
            started_at=request.started_at,
        )
        return _row(study)
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.get("/studies/{study_id}", dependencies=[Depends(require_forward_secret)])
def get_study(study_id: str, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.get_study(db, study_id))
    except ForwardResearchError as exc:
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/nav", dependencies=[Depends(require_forward_secret)])
def record_nav(study_id: str, request: NavRequest, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.record_nav(db, study_id=study_id, **request.model_dump()))
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/trades", dependencies=[Depends(require_forward_secret)])
def record_trade(study_id: str, request: TradeRequest, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.record_trade(db, study_id=study_id, **request.model_dump()))
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/executions", dependencies=[Depends(require_forward_secret)])
def record_execution(study_id: str, request: ExecutionRequest, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.record_execution(db, study_id=study_id, **request.model_dump()))
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/forecasts", dependencies=[Depends(require_forward_secret)])
def record_forecast(study_id: str, request: ForecastRequest, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.record_forecast(db, study_id=study_id, **request.model_dump()))
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/incidents", dependencies=[Depends(require_forward_secret)])
def record_incident(study_id: str, request: IncidentRequest, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.record_incident(db, study_id=study_id, **request.model_dump()))
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/incidents/{external_key}/resolve", dependencies=[Depends(require_forward_secret)])
def resolve_incident(study_id: str, external_key: str, request: ResolveIncidentRequest, db: Session = Depends(get_db)):
    try:
        return _row(
            ForwardResearchService.resolve_incident(
                db,
                study_id=study_id,
                external_key=external_key,
                resolved_at=request.resolved_at,
            )
        )
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/evaluate", dependencies=[Depends(require_forward_secret)])
def evaluate_study(study_id: str, request: EvaluateStudyRequest, db: Session = Depends(get_db)):
    try:
        run_id, result = ForwardResearchService.evaluate_study(db, study_id=study_id, evaluated_at=request.evaluated_at)
        return {
            "run_id": run_id,
            **asdict(result),
            "safety": {
                "recommendation_only": True,
                "can_promote_strategy": False,
                "can_enable_signer": False,
                "can_authorize_capital": False,
            },
        }
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc


@router.post("/studies/{study_id}/complete", dependencies=[Depends(require_forward_secret)])
def complete_study(study_id: str, request: CompleteStudyRequest, db: Session = Depends(get_db)):
    try:
        return _row(ForwardResearchService.complete_study(db, study_id=study_id, completed_at=request.completed_at))
    except ForwardResearchError as exc:
        db.rollback()
        raise _service_error(exc) from exc
