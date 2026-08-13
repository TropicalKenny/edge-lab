from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from app.config import Settings, get_settings
from app.database import get_session_factory
from app.forward_operations import ForwardOperationsError, ForwardOperationsService
from app.forward_research import ForwardResearchError


def _json_default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot JSON encode {type(value).__name__}")


def _print(value: Any, *, quiet: bool = False) -> None:
    if not quiet:
        print(json.dumps(value, default=_json_default, sort_keys=True, indent=2))


def _bootstrap_settings(settings: Settings, args: argparse.Namespace) -> Settings:
    updates: dict[str, Any] = {}
    if args.external_id:
        updates["hyperliquid_forward_study_external_id"] = args.external_id
    if args.instrument:
        updates["hyperliquid_forward_instrument"] = args.instrument
    if args.initial_capital is not None:
        updates["hyperliquid_forward_initial_capital_usd"] = args.initial_capital
    if args.paired_notional is not None:
        updates["hyperliquid_forward_paired_notional_usd"] = args.paired_notional
    return settings.model_copy(update=updates)


def bootstrap(args: argparse.Namespace) -> int:
    settings = _bootstrap_settings(get_settings(), args)
    db = get_session_factory()()
    try:
        result = ForwardOperationsService.bootstrap_hyperliquid_study(
            db, settings=settings
        )
        _print(asdict(result))
        return 0
    finally:
        db.close()


def status(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = get_session_factory()()
    try:
        reports = ForwardOperationsService.study_statuses(
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


def evaluate(args: argparse.Namespace) -> int:
    db = get_session_factory()()
    try:
        ticks = ForwardOperationsService.evaluate_due_studies(db)
        _print({"evaluations": [asdict(tick) for tick in ticks]})
        return 0
    finally:
        db.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m app.forward_ops",
        description="Safe operations for frozen forward-research studies.",
    )
    commands = root.add_subparsers(dest="command", required=True)

    bootstrap_parser = commands.add_parser(
        "bootstrap",
        help="Idempotently register and start the frozen Hyperliquid carry study.",
    )
    bootstrap_parser.add_argument("--external-id")
    bootstrap_parser.add_argument("--instrument")
    bootstrap_parser.add_argument("--initial-capital", type=float)
    bootstrap_parser.add_argument("--paired-notional", type=float)
    bootstrap_parser.set_defaults(handler=bootstrap)

    status_parser = commands.add_parser(
        "status",
        help="Print read-only forward-study operational status.",
    )
    status_parser.add_argument("--external-id")
    status_parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return non-zero unless every selected study is operationally ready.",
    )
    status_parser.add_argument("--quiet", action="store_true")
    status_parser.set_defaults(handler=status)

    evaluate_parser = commands.add_parser(
        "evaluate",
        help="Write at most one recommendation-only evaluation per active study per UTC day.",
    )
    evaluate_parser.set_defaults(handler=evaluate)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.handler(args))
    except (ForwardOperationsError, ForwardResearchError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
