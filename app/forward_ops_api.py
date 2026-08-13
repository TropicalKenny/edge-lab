from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition

router = APIRouter(prefix="/forward/ops", tags=["forward-ops"])


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {"value": decoded}
    except json.JSONDecodeError:
        return {"raw": value}


def _study_summary(db: Session, study: ForwardStudy, now: datetime) -> dict[str, Any]:
    nav = db.scalar(
        select(ForwardNavObservation)
        .where(ForwardNavObservation.study_id == study.id)
        .order_by(ForwardNavObservation.observed_at.desc())
        .limit(1)
    )
    open_positions = db.scalar(
        select(func.count(HyperliquidCarryPosition.id)).where(
            HyperliquidCarryPosition.study_id == study.id,
            HyperliquidCarryPosition.status == "open",
        )
    ) or 0
    closed_trades = db.scalar(
        select(func.count(ForwardTradeRecord.id)).where(ForwardTradeRecord.study_id == study.id)
    ) or 0
    executions = db.scalar(
        select(func.count(ForwardExecutionRecord.id)).where(ForwardExecutionRecord.study_id == study.id)
    ) or 0
    unresolved = db.scalar(
        select(func.count(ForwardStudyIncident.id)).where(
            ForwardStudyIncident.study_id == study.id,
            ForwardStudyIncident.resolved.is_(False),
        )
    ) or 0
    integrity = db.scalar(
        select(func.count(ForwardStudyIncident.id)).where(
            ForwardStudyIncident.study_id == study.id,
            ForwardStudyIncident.resolved.is_(False),
            ForwardStudyIncident.data_integrity.is_(True),
        )
    ) or 0
    latest_nav_at = _aware(nav.observed_at) if nav else None
    nav_age_seconds = (now - latest_nav_at).total_seconds() if latest_nav_at else None
    return {
        "study_id": study.id,
        "external_id": study.external_id,
        "family": study.family,
        "venue": study.venue,
        "instrument": study.instrument,
        "status": study.status,
        "started_at": study.started_at,
        "completed_at": study.completed_at,
        "initial_capital_usd": Decimal(study.initial_capital_usd),
        "latest_nav_usd": Decimal(nav.nav_usd) if nav else None,
        "latest_nav_at": latest_nav_at,
        "nav_age_seconds": nav_age_seconds,
        "open_positions": int(open_positions),
        "closed_trades": int(closed_trades),
        "execution_observations": int(executions),
        "unresolved_incidents": int(unresolved),
        "unresolved_data_integrity_incidents": int(integrity),
        "contaminated": bool(integrity),
        "study_config": _json(study.study_config_json),
    }


@router.get("/summary")
def forward_ops_summary(
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    query = select(ForwardStudy).order_by(ForwardStudy.started_at.desc()).limit(limit)
    if active_only:
        query = query.where(ForwardStudy.status == "active")
    studies = db.scalars(query).all()
    rows = [_study_summary(db, study, now) for study in studies]
    return {
        "mode": "read-only-forward-observability",
        "generated_at": now,
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
        "studies": rows,
    }


@router.get("/incidents")
def forward_ops_incidents(
    unresolved_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(ForwardStudyIncident).order_by(ForwardStudyIncident.opened_at.desc()).limit(limit)
    if unresolved_only:
        query = query.where(ForwardStudyIncident.resolved.is_(False))
    rows = db.scalars(query).all()
    return [
        {
            "id": row.id,
            "study_id": row.study_id,
            "external_key": row.external_key,
            "severity": row.severity,
            "code": row.code,
            "message": row.message,
            "data_integrity": row.data_integrity,
            "resolved": row.resolved,
            "opened_at": row.opened_at,
            "resolved_at": row.resolved_at,
        }
        for row in rows
    ]


@router.get("/positions")
def forward_ops_positions(
    status: str | None = Query(default=None, pattern="^(open|closed|invalid)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(HyperliquidCarryPosition).order_by(HyperliquidCarryPosition.opened_at.desc()).limit(limit)
    if status:
        query = query.where(HyperliquidCarryPosition.status == status)
    rows = db.scalars(query).all()
    return [
        {
            "id": row.id,
            "study_id": row.study_id,
            "coin": row.coin,
            "status": row.status,
            "quantity": Decimal(row.quantity),
            "allocated_capital_usd": Decimal(row.allocated_capital_usd),
            "planned_loss_usd": Decimal(row.planned_loss_usd),
            "opened_at": row.opened_at,
            "target_close_at": row.target_close_at,
            "closed_at": row.closed_at,
            "funding_pnl_usd": Decimal(row.funding_pnl_usd) if row.funding_pnl_usd is not None else None,
            "net_pnl_usd": Decimal(row.net_pnl_usd) if row.net_pnl_usd is not None else None,
            "close_reason": row.close_reason,
        }
        for row in rows
    ]
