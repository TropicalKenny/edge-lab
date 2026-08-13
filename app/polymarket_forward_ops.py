from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.forward_research import ForwardResearchError, policy_from_json
from app.models import Strategy, StrategyVersion
from app.polymarket_forward import (
    ANALYZER_CODE_SHA,
    INSTRUMENT,
    STRATEGY_SLUG,
    STRATEGY_VERSION,
    PolymarketForwardConfig,
    PolymarketForwardConfigError,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot JSON encode {type(value).__name__}")


def _print(value: Any, *, quiet: bool = False) -> None:
    if not quiet:
        print(json.dumps(value, default=_json_default, sort_keys=True, indent=2))


def study_statuses(
    db: Session,
    *,
    settings: Settings,
    external_id: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = _aware(now or datetime.now(timezone.utc))
    query = select(ForwardStudy).where(
        ForwardStudy.venue == "polymarket",
        ForwardStudy.family == "other",
        ForwardStudy.instrument == INSTRUMENT,
    )
    if external_id:
        query = query.where(ForwardStudy.external_id == external_id)
    studies = db.scalars(query.order_by(ForwardStudy.started_at.asc())).all()
    reports: list[dict[str, Any]] = []

    for study in studies:
        version = db.get(StrategyVersion, study.strategy_version_id)
        strategy = db.get(Strategy, version.strategy_id) if version is not None else None
        latest_nav = db.scalar(
            select(ForwardNavObservation)
            .where(ForwardNavObservation.study_id == study.id)
            .order_by(ForwardNavObservation.observed_at.desc())
            .limit(1)
        )
        initial_nav = db.scalar(
            select(ForwardNavObservation).where(
                ForwardNavObservation.study_id == study.id,
                ForwardNavObservation.observed_at == study.started_at,
            )
        )
        unresolved_critical = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(
                    ForwardStudyIncident.study_id == study.id,
                    ForwardStudyIncident.severity == "critical",
                    ForwardStudyIncident.resolved.is_(False),
                )
            )
            or 0
        )
        integrity_failures = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(
                    ForwardStudyIncident.study_id == study.id,
                    ForwardStudyIncident.data_integrity.is_(True),
                )
            )
            or 0
        )
        incident_count = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(ForwardStudyIncident.study_id == study.id)
            )
            or 0
        )
        trade_count = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardTradeRecord)
                .where(ForwardTradeRecord.study_id == study.id)
            )
            or 0
        )
        execution_count = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardExecutionRecord)
                .where(ForwardExecutionRecord.study_id == study.id)
            )
            or 0
        )

        hard_reasons: list[str] = []
        warnings: list[str] = []
        if study.status != "active":
            hard_reasons.append("STUDY_NOT_ACTIVE")
        try:
            policy_from_json(study.evaluation_policy_json)
            PolymarketForwardConfig.from_study(study)
        except (ForwardResearchError, PolymarketForwardConfigError, ValueError) as exc:
            hard_reasons.append(f"FROZEN_CONFIG_INVALID:{exc}")
        if version is None or not version.immutable:
            hard_reasons.append("STRATEGY_VERSION_MISSING_OR_MUTABLE")
        else:
            if version.version != STRATEGY_VERSION or version.code_sha != ANALYZER_CODE_SHA:
                hard_reasons.append("STRATEGY_LINEAGE_MISMATCH")
        if strategy is None:
            hard_reasons.append("STRATEGY_MISSING")
        elif strategy.slug != STRATEGY_SLUG:
            hard_reasons.append("STRATEGY_SLUG_MISMATCH")
        if integrity_failures:
            hard_reasons.append("DATA_INTEGRITY_CONTAMINATED")
        if unresolved_critical:
            hard_reasons.append("UNRESOLVED_CRITICAL_INCIDENT")
        if initial_nav is None:
            hard_reasons.append("INITIAL_NAV_MISSING")
        elif (
            Decimal(initial_nav.nav_usd) != Decimal(study.initial_capital_usd)
            or initial_nav.source != "study-initial-capital"
        ):
            hard_reasons.append("INITIAL_NAV_MISMATCH")
        if latest_nav is None:
            hard_reasons.append("NO_NAV")

        nav_age_seconds: float | None = None
        if latest_nav is not None:
            nav_age_seconds = max(
                0.0,
                (now - _aware(latest_nav.observed_at)).total_seconds(),
            )
            if nav_age_seconds > settings.polymarket_forward_health_max_nav_age_seconds:
                warnings.append("FORWARD_RUNNER_NAV_STALE")

        if hard_reasons:
            operational_state = "blocked"
        elif warnings:
            operational_state = "waiting"
        else:
            operational_state = "ready"

        reports.append(
            {
                "study_id": study.id,
                "external_id": study.external_id,
                "status": study.status,
                "operational_state": operational_state,
                "hard_reasons": hard_reasons,
                "warnings": warnings,
                "instrument": study.instrument,
                "started_at": _aware(study.started_at),
                "forward_age_days": max(0, (now - _aware(study.started_at)).days),
                "strategy_slug": strategy.slug if strategy is not None else None,
                "strategy_status": strategy.status if strategy is not None else None,
                "strategy_version": version.version if version is not None else None,
                "strategy_code_sha": version.code_sha if version is not None else None,
                "initial_capital_usd": Decimal(study.initial_capital_usd),
                "last_nav_usd": Decimal(latest_nav.nav_usd) if latest_nav is not None else None,
                "last_nav_at": _aware(latest_nav.observed_at) if latest_nav is not None else None,
                "nav_age_seconds": nav_age_seconds,
                "trade_count": trade_count,
                "execution_observation_count": execution_count,
                "incident_count": incident_count,
                "data_integrity_failure_count": integrity_failures,
                "unresolved_critical_incident_count": unresolved_critical,
            }
        )
    return reports


def status(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = get_session_factory()()
    try:
        reports = study_statuses(
            db,
            settings=settings,
            external_id=args.external_id,
        )
        _print({"studies": reports}, quiet=args.quiet)
        if not reports:
            return 2 if args.require_ready else 0
        if args.require_ready and any(
            report["operational_state"] != "ready" for report in reports
        ):
            return 3
        return 0
    finally:
        db.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m app.polymarket_forward_ops",
        description="Read-only operations for the frozen Polymarket forward study.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser(
        "status",
        help="Print Polymarket forward-study operational status.",
    )
    status_parser.add_argument("--external-id")
    status_parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return non-zero unless every selected study is operationally ready.",
    )
    status_parser.add_argument("--quiet", action="store_true")
    status_parser.set_defaults(handler=status)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.handler(args))
    except (ForwardResearchError, PolymarketForwardConfigError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
