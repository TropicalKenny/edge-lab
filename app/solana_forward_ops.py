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
from app.solana_forward import (
    INSTRUMENT,
    STRATEGY_SLUG,
    STRATEGY_VERSION,
    SolanaForwardConfig,
    SolanaForwardConfigError,
)
from app.solana_forward_operational import (
    CORE_RUNNER_CODE_SHA,
    OperationalSolanaForwardBootstrap,
    OperationalSolanaLaunchBaselineForwardRunner,
    SolanaForwardOperationalError,
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
    include_meme: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = _aware(now or datetime.now(timezone.utc))
    query = select(ForwardStudy).where(
        ForwardStudy.venue == "solana",
        ForwardStudy.family == "meme",
        ForwardStudy.instrument.in_([INSTRUMENT, "PUMP_MOMENTUM_M6L"] if include_meme else [INSTRUMENT]),
    )
    if external_id:
        query = query.where(ForwardStudy.external_id == external_id)
    studies = db.scalars(query.order_by(ForwardStudy.started_at.asc())).all()
    reports: list[dict[str, Any]] = []

    for study in studies:
        is_meme = study.instrument == "PUMP_MOMENTUM_M6L"
        version = db.get(StrategyVersion, study.strategy_version_id)
        strategy = db.get(Strategy, version.strategy_id) if version is not None else None
        initial_nav = db.scalar(
            select(ForwardNavObservation).where(
                ForwardNavObservation.study_id == study.id,
                ForwardNavObservation.observed_at == study.started_at,
            )
        )
        latest_nav = db.scalar(
            select(ForwardNavObservation)
            .where(ForwardNavObservation.study_id == study.id)
            .order_by(ForwardNavObservation.observed_at.desc())
            .limit(1)
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
            SolanaForwardConfig.from_study(study)
            OperationalSolanaLaunchBaselineForwardRunner._nav_interval_seconds(study)
        except (ForwardResearchError, SolanaForwardConfigError, ValueError) as exc:
            hard_reasons.append(f"FROZEN_CONFIG_INVALID:{exc}")
        if version is None or not version.immutable:
            hard_reasons.append("STRATEGY_VERSION_MISSING_OR_MUTABLE")
        else:
            if is_meme:
                from app.solana_meme_forward import M6LMemeConfig
                try:
                    M6LMemeConfig.from_study(study)
                except (ValueError, RuntimeError) as exc:
                    hard_reasons.append(f"FROZEN_CONFIG_INVALID:{exc}")
                expected_code = {"m6l-v1": "m6l-solana-meme-momentum-v1", "m6l-v2": "m6l-solana-meme-momentum-v2"}
                if version.code_sha != expected_code.get(version.version, "invalid"):
                    hard_reasons.append("STRATEGY_LINEAGE_MISMATCH")
            elif version.version != STRATEGY_VERSION or version.code_sha != CORE_RUNNER_CODE_SHA:
                hard_reasons.append("STRATEGY_LINEAGE_MISMATCH")
        if strategy is None:
            hard_reasons.append("STRATEGY_MISSING")
        elif strategy.slug != ("solana-pump-momentum-paper" if is_meme else STRATEGY_SLUG):
            hard_reasons.append("STRATEGY_SLUG_MISMATCH")
        if integrity_failures:
            hard_reasons.append("DATA_INTEGRITY_CONTAMINATED")
        if unresolved_critical:
            hard_reasons.append("UNRESOLVED_CRITICAL_INCIDENT")

        journal_errors = OperationalSolanaLaunchBaselineForwardRunner.journal_errors(db, study.id)
        if journal_errors:
            hard_reasons.append("OPEN_POSITION_JOURNAL_CORRUPT")

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
            nav_age_seconds = max(0.0, (now - _aware(latest_nav.observed_at)).total_seconds())
            if nav_age_seconds > settings.solana_forward_health_max_nav_age_seconds:
                warnings.append("FORWARD_RUNNER_NAV_STALE")

        open_positions = []
        if not journal_errors:
            open_positions = OperationalSolanaLaunchBaselineForwardRunner._open_positions(db, study.id)

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
                "open_position_count": len(open_positions),
                "trade_count": trade_count,
                "execution_observation_count": execution_count,
                "incident_count": incident_count,
                "data_integrity_failure_count": integrity_failures,
                "unresolved_critical_incident_count": unresolved_critical,
                "journal_error_count": len(journal_errors),
            }
        )
    return reports


def bootstrap(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.signer_enabled:
        raise SolanaForwardOperationalError("refusing Solana forward bootstrap with signer enabled")
    db = get_session_factory()()
    try:
        study = OperationalSolanaForwardBootstrap.bootstrap(db, settings=settings)
        _print(
            {
                "study_id": study.id,
                "external_id": study.external_id,
                "status": study.status,
                "started_at": _aware(study.started_at),
                "initial_capital_usd": Decimal(study.initial_capital_usd),
            },
            quiet=args.quiet,
        )
        return 0
    finally:
        db.close()


def status(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = get_session_factory()()
    try:
        reports = study_statuses(db, settings=settings, external_id=args.external_id)
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
        prog="python -m app.solana_forward_ops",
        description="Bootstrap and read-only status for the frozen Solana forward baseline.",
    )
    commands = root.add_subparsers(dest="command", required=True)

    bootstrap_parser = commands.add_parser("bootstrap", help="Idempotently create the frozen study.")
    bootstrap_parser.add_argument("--quiet", action="store_true")
    bootstrap_parser.set_defaults(handler=bootstrap)

    status_parser = commands.add_parser("status", help="Print Solana forward-study operational status.")
    status_parser.add_argument("--external-id")
    status_parser.add_argument("--require-ready", action="store_true")
    status_parser.add_argument("--quiet", action="store_true")
    status_parser.set_defaults(handler=status)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.handler(args))
    except (
        ForwardResearchError,
        SolanaForwardConfigError,
        SolanaForwardOperationalError,
        ValueError,
    ) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

