from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone


from app.config import get_settings
from app.database import get_session_factory
from app.solana_meme_forward import (
    M6L_EXPLORATORY_EXTERNAL_ID,
    M6L_STRICT_EXTERNAL_ID,
)


def _aware(value):
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def status(*, require_ready: bool = False) -> dict:
    settings = get_settings()
    if settings.signer_enabled:
        raise RuntimeError("M6L status refuses SIGNER_ENABLED=true")
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        from app.solana_forward_ops import study_statuses
        reports = study_statuses(db, settings=settings, now=datetime.now(timezone.utc), include_meme=True)
        by_id = {row["external_id"]: row for row in reports}
        results = []
        for external_id in (M6L_STRICT_EXTERNAL_ID, M6L_EXPLORATORY_EXTERNAL_ID):
            report = by_id.get(external_id)
            results.append(report or {"external_id": external_id, "operational_state": "missing"})
        ready = all(row["operational_state"] == "ready" for row in results)
        payload = {"mode": "paper-shadow-only", "signer_enabled": False, "ready": ready, "studies": results}
        if require_ready and not ready:
            raise RuntimeError("M6L Solana paper studies are not ready")
        return payload
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("status")
    p.add_argument("--require-ready", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    payload = status(require_ready=args.require_ready)
    if not args.quiet:
        print(json.dumps(payload, default=str, sort_keys=True))


if __name__ == "__main__":
    main()

