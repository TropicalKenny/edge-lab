from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.models import StrategyVersion

ZERO = Decimal("0")
STATIC_DIR = Path(__file__).resolve().parent / "dashboard_static"

app = FastAPI(
    title="Edge Lab Dashboard",
    version="1.0.0",
    description="Read-only owner dashboard for paper/shadow forward research.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="dashboard-assets")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _decode_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _latest_nav(db: Session, study_id: str) -> ForwardNavObservation | None:
    return db.scalar(
        select(ForwardNavObservation)
        .where(ForwardNavObservation.study_id == study_id)
        .order_by(ForwardNavObservation.observed_at.desc())
        .limit(1)
    )


def _latest_evaluation(db: Session, strategy_version_id: str) -> StrategyEvaluationRun | None:
    return db.scalar(
        select(StrategyEvaluationRun)
        .where(StrategyEvaluationRun.strategy_version_id == strategy_version_id)
        .order_by(StrategyEvaluationRun.evaluated_at.desc())
        .limit(1)
    )


def _count(db: Session, model, *criteria) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(*criteria)) or 0
    )


def _solana_open_positions(db: Session, study_id: str) -> int:
    rows = db.scalars(
        select(ForwardExecutionRecord).where(
            ForwardExecutionRecord.study_id == study_id,
            ForwardExecutionRecord.external_key.like("solana-entry:%"),
        )
    ).all()
    count = 0
    for row in rows:
        metadata = _decode_json(row.metadata_json, {})
        if isinstance(metadata, dict) and metadata.get("status") == "open":
            count += 1
    return count


def _open_positions(db: Session, study: ForwardStudy) -> int:
    if study.venue == "hyperliquid":
        return _count(
            db,
            HyperliquidCarryPosition,
            HyperliquidCarryPosition.study_id == study.id,
            HyperliquidCarryPosition.status == "open",
        )
    if study.venue == "solana":
        return _solana_open_positions(db, study.id)
    return 0


def _study_card(db: Session, study: ForwardStudy, now: datetime) -> dict[str, Any]:
    nav = _latest_nav(db, study.id)
    evaluation = _latest_evaluation(db, study.strategy_version_id)
    version = db.get(StrategyVersion, study.strategy_version_id)
    initial = Decimal(study.initial_capital_usd)
    current = Decimal(nav.nav_usd) if nav is not None else initial
    pnl = current - initial
    return_pct = (pnl / initial * Decimal("100")) if initial > ZERO else ZERO
    started = _aware(study.started_at)
    nav_at = _aware(nav.observed_at) if nav is not None else None
    incidents = _count(
        db,
        ForwardStudyIncident,
        ForwardStudyIncident.study_id == study.id,
        ForwardStudyIncident.resolved.is_(False),
    )
    integrity = _count(
        db,
        ForwardStudyIncident,
        ForwardStudyIncident.study_id == study.id,
        ForwardStudyIncident.data_integrity.is_(True),
    )
    critical = _count(
        db,
        ForwardStudyIncident,
        ForwardStudyIncident.study_id == study.id,
        ForwardStudyIncident.severity == "critical",
        ForwardStudyIncident.resolved.is_(False),
    )
    trade_count = _count(
        db, ForwardTradeRecord, ForwardTradeRecord.study_id == study.id
    )
    execution_count = _count(
        db, ForwardExecutionRecord, ForwardExecutionRecord.study_id == study.id
    )
    if integrity or critical:
        operational_state = "blocked"
    elif study.status != "active":
        operational_state = study.status
    else:
        operational_state = "active"
    recommendation = evaluation.recommendation if evaluation is not None else "RESEARCH"
    reasons = _decode_json(evaluation.reasons_json, []) if evaluation is not None else []
    metrics = _decode_json(evaluation.metrics_json, {}) if evaluation is not None else {}
    return {
        "id": study.id,
        "external_id": study.external_id,
        "family": study.family,
        "venue": study.venue,
        "instrument": study.instrument,
        "status": study.status,
        "operational_state": operational_state,
        "strategy_version": version.version if version is not None else None,
        "started_at": started,
        "forward_days": max(0, (now - started).days) if started else 0,
        "initial_nav_usd": initial,
        "nav_usd": current,
        "nav_at": nav_at,
        "nav_age_seconds": max(0.0, (now - nav_at).total_seconds()) if nav_at else None,
        "pnl_usd": pnl,
        "return_pct": return_pct,
        "open_positions": _open_positions(db, study),
        "closed_trades": trade_count,
        "execution_observations": execution_count,
        "unresolved_incidents": incidents,
        "data_integrity_failures": integrity,
        "recommendation": recommendation,
        "evaluation_reasons": reasons,
        "evaluation_metrics": metrics,
        "last_evaluated_at": _aware(evaluation.evaluated_at) if evaluation is not None else None,
    }


@app.get("/")
def dashboard_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    studies = db.scalars(
        select(ForwardStudy).order_by(ForwardStudy.started_at.asc())
    ).all()
    cards = [_study_card(db, study, now) for study in studies]
    active = [card for card in cards if card["status"] == "active"]
    total_initial = sum((card["initial_nav_usd"] for card in active), ZERO)
    total_nav = sum((card["nav_usd"] for card in active), ZERO)
    total_pnl = total_nav - total_initial
    total_return = (
        total_pnl / total_initial * Decimal("100") if total_initial > ZERO else ZERO
    )
    unresolved_incidents = _count(
        db,
        ForwardStudyIncident,
        ForwardStudyIncident.resolved.is_(False),
    )
    integrity_failures = _count(
        db,
        ForwardStudyIncident,
        ForwardStudyIncident.data_integrity.is_(True),
    )
    critical = _count(
        db,
        ForwardStudyIncident,
        ForwardStudyIncident.severity == "critical",
        ForwardStudyIncident.resolved.is_(False),
    )
    if integrity_failures or critical:
        system_state = "attention"
    elif not active:
        system_state = "idle"
    else:
        system_state = "healthy"
    return {
        "generated_at": now,
        "mode": "paper-shadow-research-only",
        "live_capital_enabled": False,
        "signer_enabled": False,
        "fund_movement_enabled": False,
        "system_state": system_state,
        "combined_research_initial_usd": total_initial,
        "combined_research_nav_usd": total_nav,
        "combined_research_pnl_usd": total_pnl,
        "combined_research_return_pct": total_return,
        "active_study_count": len(active),
        "unresolved_incident_count": unresolved_incidents,
        "data_integrity_failure_count": integrity_failures,
        "studies": cards,
    }


@app.get("/api/nav/{study_id}")
def dashboard_nav(
    study_id: str,
    limit: int = Query(default=500, ge=2, le=5000),
    db: Session = Depends(get_db),
):
    study = db.get(ForwardStudy, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="study not found")
    rows = db.scalars(
        select(ForwardNavObservation)
        .where(ForwardNavObservation.study_id == study_id)
        .order_by(ForwardNavObservation.observed_at.desc())
        .limit(limit)
    ).all()
    rows.reverse()
    return {
        "study_id": study_id,
        "external_id": study.external_id,
        "venue": study.venue,
        "instrument": study.instrument,
        "points": [
            {"time": _aware(row.observed_at), "nav_usd": Decimal(row.nav_usd)}
            for row in rows
        ],
    }


@app.get("/api/trades")
def dashboard_trades(
    limit: int = Query(default=50, ge=1, le=250),
    study_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = select(ForwardTradeRecord).order_by(ForwardTradeRecord.closed_at.desc())
    if study_id:
        query = query.where(ForwardTradeRecord.study_id == study_id)
    rows = db.scalars(query.limit(limit)).all()
    study_ids = {row.study_id for row in rows}
    studies = {
        study.id: study
        for study in db.scalars(select(ForwardStudy).where(ForwardStudy.id.in_(study_ids))).all()
    } if study_ids else {}
    return [
        {
            "id": row.id,
            "study_id": row.study_id,
            "venue": studies[row.study_id].venue if row.study_id in studies else None,
            "instrument": studies[row.study_id].instrument if row.study_id in studies else None,
            "opened_at": _aware(row.opened_at),
            "closed_at": _aware(row.closed_at),
            "gross_pnl_usd": Decimal(row.gross_pnl_usd),
            "net_pnl_usd": Decimal(row.net_pnl_usd),
            "fees_usd": Decimal(row.fees_usd),
            "slippage_usd": Decimal(row.slippage_usd),
            "allocated_capital_usd": Decimal(row.allocated_capital_usd),
            "planned_loss_usd": Decimal(row.planned_loss_usd),
            "metadata": _decode_json(row.metadata_json, {}),
        }
        for row in rows
    ]


@app.get("/api/incidents")
def dashboard_incidents(
    limit: int = Query(default=50, ge=1, le=250),
    unresolved_only: bool = True,
    db: Session = Depends(get_db),
):
    query = select(ForwardStudyIncident).order_by(ForwardStudyIncident.opened_at.desc())
    if unresolved_only:
        query = query.where(ForwardStudyIncident.resolved.is_(False))
    rows = db.scalars(query.limit(limit)).all()
    return [
        {
            "id": row.id,
            "study_id": row.study_id,
            "severity": row.severity,
            "code": row.code,
            "message": row.message,
            "data_integrity": row.data_integrity,
            "resolved": row.resolved,
            "opened_at": _aware(row.opened_at),
            "resolved_at": _aware(row.resolved_at),
        }
        for row in rows
    ]


@app.get("/api/safety")
def dashboard_safety():
    return {
        "dashboard_mode": "read-only",
        "live_trading": False,
        "signing": False,
        "wallet_keys_on_dashboard": False,
        "fund_transfers": False,
        "recommended_exposure": "loopback-only or authenticated private tunnel",
    }
