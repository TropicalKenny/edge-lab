from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
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
from app.models import Strategy, StrategyVersion

router = APIRouter(tags=["dashboard"])
STATIC_DIR = Path(__file__).resolve().parent / "static" / "dashboard"
ZERO = Decimal("0")
ASSETS = {
    "dashboard.css": ("text/css", STATIC_DIR / "dashboard.css"),
    "dashboard.js": ("application/javascript", STATIC_DIR / "dashboard.js"),
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _max_drawdown_pct(nav_rows: list[ForwardNavObservation]) -> Decimal | None:
    if not nav_rows:
        return None
    peak = Decimal(nav_rows[0].nav_usd)
    worst = ZERO
    for row in nav_rows:
        nav = Decimal(row.nav_usd)
        if nav > peak:
            peak = nav
        if peak > ZERO:
            drawdown = (peak - nav) / peak
            if drawdown > worst:
                worst = drawdown
    return worst


def _latest_evaluation(db: Session, study: ForwardStudy) -> StrategyEvaluationRun | None:
    return db.scalar(
        select(StrategyEvaluationRun)
        .where(StrategyEvaluationRun.strategy_version_id == study.strategy_version_id)
        .order_by(StrategyEvaluationRun.evaluated_at.desc())
        .limit(1)
    )


def _strategy_identity(db: Session, study: ForwardStudy) -> tuple[str, str, str]:
    version = db.get(StrategyVersion, study.strategy_version_id)
    if version is None:
        return study.external_id, "unknown", "red"
    strategy = db.get(Strategy, version.strategy_id)
    if strategy is None:
        return study.external_id, version.version, "red"
    return strategy.name, version.version, strategy.status


def _study_payload(db: Session, study: ForwardStudy, now: datetime) -> dict[str, Any]:
    nav_rows = list(
        db.scalars(
            select(ForwardNavObservation)
            .where(ForwardNavObservation.study_id == study.id)
            .order_by(ForwardNavObservation.observed_at.desc())
            .limit(60)
        ).all()
    )
    nav_rows.reverse()
    latest_nav = nav_rows[-1] if nav_rows else None
    trade_count = db.scalar(
        select(func.count(ForwardTradeRecord.id)).where(ForwardTradeRecord.study_id == study.id)
    ) or 0
    execution_count = db.scalar(
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
            ForwardStudyIncident.data_integrity.is_(True),
        )
    ) or 0
    net_pnl = db.scalar(
        select(func.coalesce(func.sum(ForwardTradeRecord.net_pnl_usd), 0)).where(
            ForwardTradeRecord.study_id == study.id
        )
    ) or ZERO
    evaluation = _latest_evaluation(db, study)
    name, version, strategy_status = _strategy_identity(db, study)
    started = _aware(study.started_at)
    elapsed_days = max(0, int((now - started).total_seconds() // 86400)) if started else 0
    initial = Decimal(study.initial_capital_usd)
    current = Decimal(latest_nav.nav_usd) if latest_nav else initial
    observed_drawdown = _max_drawdown_pct(nav_rows)
    return {
        "study_id": study.id,
        "external_id": study.external_id,
        "strategy_name": name,
        "strategy_version": version,
        "strategy_status": strategy_status,
        "family": study.family,
        "venue": study.venue,
        "instrument": study.instrument,
        "study_status": study.status,
        "started_at": study.started_at,
        "completed_at": study.completed_at,
        "elapsed_days": elapsed_days,
        "initial_capital_usd": initial,
        "latest_nav_usd": current,
        "net_pnl_usd": Decimal(net_pnl),
        "return_pct": ((current - initial) / initial * Decimal("100")) if initial > ZERO else ZERO,
        "observed_max_drawdown_pct": observed_drawdown,
        "closed_trades": int(trade_count),
        "execution_observations": int(execution_count),
        "unresolved_incidents": int(unresolved),
        "data_integrity_incidents": int(integrity),
        "contaminated": bool(integrity),
        "latest_evaluation": (
            {
                "recommendation": evaluation.recommendation,
                "evaluated_at": evaluation.evaluated_at,
                "forward_days": evaluation.forward_days,
                "trade_count": evaluation.trade_count,
                "net_pnl_usd": Decimal(evaluation.net_pnl_usd),
                "stressed_net_pnl_usd": Decimal(evaluation.stressed_net_pnl_usd),
                "max_drawdown_pct": Decimal(evaluation.max_drawdown_pct)
                if evaluation.max_drawdown_pct is not None
                else None,
                "profit_factor": Decimal(evaluation.profit_factor)
                if evaluation.profit_factor is not None
                else None,
                "reasons": _json(evaluation.reasons_json) or [],
            }
            if evaluation
            else None
        ),
        "nav_history": [
            {"observed_at": row.observed_at, "nav_usd": Decimal(row.nav_usd)} for row in nav_rows
        ],
    }


@router.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@router.get("/dashboard/assets/{asset}", include_in_schema=False)
def dashboard_asset(asset: str):
    found = ASSETS.get(asset)
    if found is None:
        raise HTTPException(status_code=404, detail="dashboard asset not found")
    media_type, path = found
    return FileResponse(path, media_type=media_type)


@router.get("/dashboard/api/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    studies = list(db.scalars(select(ForwardStudy).order_by(ForwardStudy.started_at.asc())).all())
    study_rows = [_study_payload(db, study, now) for study in studies]
    total_initial = sum((Decimal(row["initial_capital_usd"]) for row in study_rows), ZERO)
    total_nav = sum((Decimal(row["latest_nav_usd"]) for row in study_rows), ZERO)
    total_net_pnl = sum((Decimal(row["net_pnl_usd"]) for row in study_rows), ZERO)
    unresolved = list(
        db.scalars(
            select(ForwardStudyIncident)
            .where(ForwardStudyIncident.resolved.is_(False))
            .order_by(ForwardStudyIncident.opened_at.desc())
            .limit(20)
        ).all()
    )
    permanent_integrity_count = int(
        db.scalar(
            select(func.count(ForwardStudyIncident.id)).where(
                ForwardStudyIncident.data_integrity.is_(True)
            )
        )
        or 0
    )
    recent_trades = list(
        db.scalars(select(ForwardTradeRecord).order_by(ForwardTradeRecord.closed_at.desc()).limit(20)).all()
    )
    study_names = {row["study_id"]: row["strategy_name"] for row in study_rows}
    drawdowns = [
        Decimal(row["observed_max_drawdown_pct"])
        for row in study_rows
        if row["observed_max_drawdown_pct"] is not None
    ]
    return {
        "mode": "read-only-dashboard",
        "generated_at": now,
        "capital_scope": "independent-simulated-forward-study-bankrolls",
        "safety": {
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "vault_accessible": False,
            "signer_enabled": False,
            "live_capital_usd": ZERO,
        },
        "portfolio": {
            "label": "aggregate simulated research capital",
            "study_count": len(study_rows),
            "active_study_count": sum(1 for row in study_rows if row["study_status"] == "active"),
            "simulated_initial_capital_usd": total_initial,
            "simulated_latest_nav_usd": total_nav,
            # Compatibility aliases for early Dashboard V1 clients.
            "initial_capital_usd": total_initial,
            "latest_nav_usd": total_nav,
            "net_pnl_usd": total_net_pnl,
            "return_pct": ((total_nav - total_initial) / total_initial * Decimal("100"))
            if total_initial > ZERO
            else ZERO,
            "worst_observed_study_drawdown_pct": max(drawdowns) if drawdowns else None,
            "closed_trades": sum(int(row["closed_trades"]) for row in study_rows),
            "execution_observations": sum(int(row["execution_observations"]) for row in study_rows),
            "unresolved_incidents": len(unresolved),
            "permanent_data_integrity_incidents": permanent_integrity_count,
            "contaminated_study_count": sum(1 for row in study_rows if row["contaminated"]),
            # Compatibility alias; integrity failures are permanent even if operationally resolved.
            "data_integrity_incidents": permanent_integrity_count,
        },
        "studies": study_rows,
        "incidents": [
            {
                "id": item.id,
                "study_id": item.study_id,
                "strategy_name": study_names.get(item.study_id, "Unknown study"),
                "severity": item.severity,
                "code": item.code,
                "message": item.message,
                "data_integrity": item.data_integrity,
                "opened_at": item.opened_at,
            }
            for item in unresolved
        ],
        "recent_trades": [
            {
                "id": item.id,
                "study_id": item.study_id,
                "strategy_name": study_names.get(item.study_id, "Unknown study"),
                "opened_at": item.opened_at,
                "closed_at": item.closed_at,
                "gross_pnl_usd": Decimal(item.gross_pnl_usd),
                "net_pnl_usd": Decimal(item.net_pnl_usd),
                "fees_usd": Decimal(item.fees_usd),
                "slippage_usd": Decimal(item.slippage_usd),
                "allocated_capital_usd": Decimal(item.allocated_capital_usd),
                "planned_loss_usd": Decimal(item.planned_loss_usd),
            }
            for item in recent_trades
        ],
    }
