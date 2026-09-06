from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.dashboard_api import dashboard_summary
from app.database import get_session_factory
from app.forward_operations import ForwardOperationsService
from app.polymarket_forward_ops import study_statuses as polymarket_study_statuses
from app.solana_forward_ops import study_statuses as solana_study_statuses
from app.scan_telemetry import scan_activity_summary

SNAPSHOT_SCHEMA = "edge-lab-research-snapshot-v1"
CHALLENGER_RESEARCH_LANES = ("m6j", "m6k-hl", "m6k-pm", "m6k-sol", "m6l-sol-paper-mark")
M6K_LANE_BY_VENUE = {
    "hyperliquid": "m6k-hl",
    "polymarket": "m6k-pm",
    "solana": "m6k-sol",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    raise TypeError(f"cannot JSON encode {type(value).__name__}")


def _operational_reports(
    db: Session,
    *,
    settings: Settings,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    reports.extend(
        ForwardOperationsService.study_statuses(db, settings=settings, now=now)
    )
    reports.extend(solana_study_statuses(db, settings=settings, now=now, include_meme=True))
    reports.extend(polymarket_study_statuses(db, settings=settings, now=now))
    return {str(report["study_id"]): report for report in reports}


def _compact_operational(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "state": "unknown",
            "hard_reasons": ["OPERATIONAL_REPORT_MISSING"],
            "warnings": [],
        }
    keep = (
        "operational_state",
        "hard_reasons",
        "warnings",
        "last_nav_at",
        "nav_age_seconds",
        "latest_market_at",
        "market_age_seconds",
        "latest_funding_at",
        "funding_age_seconds",
        "open_position_count",
        "trade_count",
        "execution_observation_count",
        "incident_count",
        "data_integrity_failure_count",
        "unresolved_critical_incident_count",
    )
    compact = {key: report.get(key) for key in keep if key in report}
    compact["state"] = compact.pop("operational_state", "unknown")
    return compact


def _compact_evaluation(evaluation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not evaluation:
        return None
    keep = (
        "recommendation",
        "evaluated_at",
        "forward_days",
        "trade_count",
        "net_pnl_usd",
        "stressed_net_pnl_usd",
        "max_drawdown_pct",
        "has_newer_trades",
        "profit_factor",
        "reasons",
    )
    return {key: evaluation.get(key) for key in keep}


def build_research_snapshot(
    db: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a bounded, deterministic, read-only research snapshot.

    The snapshot intentionally contains no credentials, wallet material, bearer tokens,
    arbitrary SQL, shell surface, or execution controls. It is designed to be safe for
    Telegram owner reporting and the typed Aurent VPS read bridge.
    """

    settings = settings or get_settings()
    if settings.signer_enabled:
        raise RuntimeError("refusing research snapshot with SIGNER_ENABLED=true")

    captured_at = _aware(now or datetime.now(timezone.utc))
    assert captured_at is not None
    dashboard = dashboard_summary(db)
    operational = _operational_reports(db, settings=settings, now=captured_at)

    studies: list[dict[str, Any]] = []
    for row in dashboard.get("studies") or []:
        study_id = str(row.get("study_id"))
        venue = str(row.get("venue") or "").lower()
        baseline_activity = scan_activity_summary(
            db,
            study_id=study_id,
            now=captured_at,
            exclude_research_lanes=CHALLENGER_RESEARCH_LANES,
        )
        m6j_activity = scan_activity_summary(
            db,
            study_id=study_id,
            now=captured_at,
            research_lane="m6j",
        )
        m6k_lane = M6K_LANE_BY_VENUE.get(venue)
        m6k_activity = (
            scan_activity_summary(
                db,
                study_id=study_id,
                now=captured_at,
                research_lane=m6k_lane,
            )
            if m6k_lane
            else None
        )
        studies.append(
            {
                "study_id": study_id,
                "external_id": row.get("external_id"),
                "venue": row.get("venue"),
                "family": row.get("family"),
                "instrument": row.get("instrument"),
                "strategy_name": row.get("strategy_name"),
                "strategy_version": row.get("strategy_version"),
                "strategy_status": row.get("strategy_status"),
                "study_status": row.get("study_status"),
                "started_at": row.get("started_at"),
                "elapsed_days": row.get("elapsed_days"),
                "initial_capital_usd": row.get("initial_capital_usd"),
                "latest_nav_usd": row.get("latest_nav_usd"),
                "net_pnl_usd": row.get("net_pnl_usd"),
                "return_pct": row.get("return_pct"),
                "observed_max_drawdown_pct": row.get("observed_max_drawdown_pct"),
                "drawdown_scope": row.get("drawdown_scope"),
                "drawdown_unit": "fraction",
                "cohort": row.get("cohort"),
                "total_pnl_usd": row.get("total_pnl_usd"),
                "realized_pnl_usd": row.get("realized_pnl_usd"),
                "unrealized_pnl_usd": row.get("unrealized_pnl_usd"),
                "nav_as_of": row.get("nav_as_of"),
                "closed_trades": row.get("closed_trades"),
                "execution_observations": row.get("execution_observations"),
                "unresolved_incidents": row.get("unresolved_incidents"),
                "data_integrity_incidents": row.get("data_integrity_incidents"),
                "contaminated": bool(row.get("contaminated")),
                "latest_evaluation": _compact_evaluation(row.get("latest_evaluation")),
                "operational": _compact_operational(operational.get(study_id)),
                "activity": baseline_activity,
                "research_acceleration": m6j_activity,
                "strategy_research": m6k_activity,
            }
        )

    recent_trades = []
    for trade in (dashboard.get("recent_trades") or [])[:10]:
        recent_trades.append(
            {
                "id": trade.get("id"),
                "study_id": trade.get("study_id"),
                "strategy_name": trade.get("strategy_name"),
                "opened_at": trade.get("opened_at"),
                "closed_at": trade.get("closed_at"),
                "net_pnl_usd": trade.get("net_pnl_usd"),
                "fees_usd": trade.get("fees_usd"),
                "slippage_usd": trade.get("slippage_usd"),
                "allocated_capital_usd": trade.get("allocated_capital_usd"),
                "planned_loss_usd": trade.get("planned_loss_usd"),
            }
        )

    incidents = []
    for incident in (dashboard.get("incidents") or [])[:10]:
        incidents.append(
            {
                "id": incident.get("id"),
                "study_id": incident.get("study_id"),
                "strategy_name": incident.get("strategy_name"),
                "severity": incident.get("severity"),
                "code": incident.get("code"),
                "message": incident.get("message"),
                "data_integrity": bool(incident.get("data_integrity")),
                "opened_at": incident.get("opened_at"),
            }
        )

    portfolio = dashboard.get("portfolio") or {}
    return {
        "schema": SNAPSHOT_SCHEMA,
        "captured_at": captured_at,
        "mode": "paper-shadow-research-only",
        "safety": {
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "shell_access": False,
            "wallet_access": False,
            "signer_enabled": False,
            "live_capital_usd": Decimal("0"),
        },
        "portfolio": {
            "study_count": portfolio.get("study_count", 0),
            "active_study_count": portfolio.get("active_study_count", 0),
            "simulated_initial_capital_usd": portfolio.get("simulated_initial_capital_usd"),
            "simulated_latest_nav_usd": portfolio.get("simulated_latest_nav_usd"),
            "net_pnl_usd": portfolio.get("net_pnl_usd"),
            "return_pct": portfolio.get("return_pct"),
            "worst_observed_study_drawdown_pct": portfolio.get("worst_observed_study_drawdown_pct"),
            "closed_trades": portfolio.get("closed_trades", 0),
            "execution_observations": portfolio.get("execution_observations", 0),
            "unresolved_incidents": portfolio.get("unresolved_incidents", 0),
            "permanent_data_integrity_incidents": portfolio.get("permanent_data_integrity_incidents", 0),
            "contaminated_study_count": portfolio.get("contaminated_study_count", 0),
        },
        "studies": studies,
        "incidents": incidents,
        "recent_trades": recent_trades,
    }


def _money(value: Any) -> str:
    return f"${Decimal(str(value or 0)):,.2f}"


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{Decimal(str(value)):+.2f}%"


def render_research_snapshot_text(snapshot: dict[str, Any]) -> str:
    portfolio = snapshot.get("portfolio") or {}
    lines = [
        "EDGE LAB — RESEARCH SNAPSHOT",
        f"Captured: {snapshot.get('captured_at')}",
        "Mode: PAPER/SHADOW | Signer: DISABLED | Live capital: $0.00",
        (
            "Portfolio: "
            f"NAV {_money(portfolio.get('simulated_latest_nav_usd'))} | "
            f"P&L {_money(portfolio.get('net_pnl_usd'))} ({_pct(portfolio.get('return_pct'))})"
        ),
    ]

    for row in snapshot.get("studies") or []:
        op = row.get("operational") or {}
        evaluation = row.get("latest_evaluation") or {}
        lines.extend(
            [
                "",
                f"{str(row.get('venue') or 'unknown').upper()} — {row.get('strategy_name')}",
                (
                    f"State: {str(op.get('state') or 'unknown').upper()} | "
                    f"Study: {str(row.get('study_status') or 'unknown').upper()}"
                ),
                (
                    f"NAV {_money(row.get('latest_nav_usd'))} | "
                    f"P&L {_money(row.get('net_pnl_usd'))} ({_pct(row.get('return_pct'))}) | "
                    f"Trades {row.get('closed_trades', 0)}"
                ),
                (
                    "Evidence: "
                    f"{evaluation.get('recommendation', 'not evaluated')} | "
                    f"days {evaluation.get('forward_days', 0)} | "
                    f"eval trades {evaluation.get('trade_count', 0)}"
                ),
            ]
        )
        activity = row.get("activity") or {}
        if activity.get("tracking"):
            lines.append(
                "Activity 24h: "
                f"scans {activity.get('cycles', 0)} | "
                f"examined {activity.get('examined', 0)} | "
                f"passed {activity.get('accepted', 0)} | "
                f"rejected {activity.get('rejected', 0)}"
            )
            meta = activity.get("metadata_totals") or {}
            venue = str(row.get("venue") or "").lower()
            if venue == "solana" and meta:
                lines.append(
                    "Scan detail: "
                    f"launch-window observations {meta.get('launches_in_window', 0)} | "
                    f"decision features {meta.get('features_ready', 0)} | "
                    f"quote attempts {meta.get('quote_attempts', 0)}"
                )
            elif venue == "polymarket" and meta:
                lines.append(
                    "Scan detail: "
                    f"markets discovered {meta.get('markets_discovered', 0)} | "
                    f"validated {meta.get('markets_validated', 0)} | "
                    f"structural candidates {meta.get('structural_candidates', 0)}"
                )
            top = activity.get("top_rejection_reasons") or []
            if top:
                lines.append(
                    "Top rejects: " + "; ".join(
                        f"{item.get('reason')} {item.get('count')}" for item in top[:5]
                    )
                )
        else:
            lines.append("Activity: tracking enabled; waiting for first completed scan")

        m6j = row.get("research_acceleration") or {}
        if m6j.get("tracking"):
            lines.append(
                "M6J research 24h: "
                f"cycles {m6j.get('cycles', 0)} | "
                f"examined {m6j.get('examined', 0)} | "
                f"positive/quoted {m6j.get('accepted', 0)} | "
                f"rejected/unsafe {m6j.get('rejected', 0)}"
            )
            m6j_meta = m6j.get("metadata_totals") or {}
            venue = str(row.get("venue") or "").lower()
            if venue == "hyperliquid":
                lines.append(
                    "M6J detail: "
                    f"horizon tests {m6j_meta.get('m6j_candidates_examined', 0)} | "
                    f"positive edge {m6j_meta.get('m6j_positive_edge_candidates', 0)}"
                )
            elif venue == "polymarket":
                lines.append(
                    "M6J detail: "
                    f"WS messages {m6j_meta.get('m6j_ws_messages', 0)} | "
                    f"book events {m6j_meta.get('m6j_book_events', 0)} | "
                    f"positive edge events {m6j_meta.get('m6j_positive_edge_events', 0)}"
                )
            elif venue == "solana":
                lines.append(
                    "M6J detail: "
                    f"unknown {m6j_meta.get('m6j_unknown_candidates', 0)} | "
                    f"unsafe {m6j_meta.get('m6j_unsafe_candidates', 0)} | "
                    f"quote attempts {m6j_meta.get('m6j_counterfactual_quote_attempts', 0)} | "
                    f"outcomes {m6j_meta.get('m6j_counterfactual_outcomes', 0)}"
                )

        m6k = row.get("strategy_research") or {}
        if m6k.get("tracking"):
            meta = m6k.get("metadata_totals") or {}
            venue = str(row.get("venue") or "").lower()
            if venue == "hyperliquid":
                lines.append(
                    "M6K strategy research: PERSISTENCE SCREEN ONLY | "
                    f"tested {meta.get('m6k_hl_candidates_examined', 0)} | "
                    f"screen-pass {meta.get('m6k_hl_screen_passed', 0)} | "
                    f"screen-reject {meta.get('m6k_hl_screen_rejected', 0)}"
                )
            elif venue == "polymarket":
                lines.append(
                    "M6K strategy research: EVENT CONSISTENCY | "
                    f"checks {meta.get('m6k_pm_event_checks', 0)} | "
                    f"valid {meta.get('m6k_pm_valid_observations', 0)} | "
                    f"positive gaps {meta.get('m6k_pm_positive_violations', 0)} | "
                    f">=baseline {meta.get('m6k_pm_baseline_qualified', 0)}"
                )
            elif venue == "solana":
                lines.append(
                    "M6K strategy research: UNKNOWN DECOMPOSITION | "
                    f"new unknown {meta.get('m6k_sol_unknown_entries', 0)} | "
                    f"outcomes {meta.get('m6k_sol_unknown_outcomes', 0)} | "
                    f"later SAFE {meta.get('m6k_sol_resolutions_safe', 0)} | "
                    f"later UNSAFE {meta.get('m6k_sol_resolutions_unsafe', 0)}"
                )

        hard = op.get("hard_reasons") or []
        warnings = op.get("warnings") or []
        if hard:
            lines.append("Blocked: " + ", ".join(str(item) for item in hard[:3]))
        if warnings:
            lines.append("Warnings: " + ", ".join(str(item) for item in warnings[:3]))

    lines.extend(
        [
            "",
            f"Open incidents: {portfolio.get('unresolved_incidents', 0)}",
            "Research only. M6J/M6K challenger observations do not promote a strategy and cannot trade, sign, move funds, access a wallet, or execute shell commands.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    settings = get_settings()
    db = get_session_factory()()
    try:
        snapshot = build_research_snapshot(db, settings=settings)
        print(json.dumps(snapshot, default=_json_default, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
