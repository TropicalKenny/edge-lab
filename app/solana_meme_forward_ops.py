from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.forward_models import ForwardNavObservation, ForwardStudy
from app.solana_forward_operational import OperationalSolanaLaunchBaselineForwardRunner
from app.solana_meme_forward import (
    M6L_EXPLORATORY_EXTERNAL_ID,
    M6L_INSTRUMENT,
    M6L_STRICT_EXTERNAL_ID,
    M6LMemeConfig,
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
        now = datetime.now(timezone.utc)
        results = []
        ready = True
        for external_id in (M6L_STRICT_EXTERNAL_ID, M6L_EXPLORATORY_EXTERNAL_ID):
            study = db.scalar(select(ForwardStudy).where(ForwardStudy.external_id == external_id))
            if study is None:
                results.append({"external_id": external_id, "state": "missing"})
                ready = False
                continue
            reasons = []
            try:
                config = M6LMemeConfig.from_study(study)
            except Exception as exc:
                config = None
                reasons.append(f"config:{type(exc).__name__}")
            if study.status != "active":
                reasons.append(f"study_status:{study.status}")
            if study.instrument != M6L_INSTRUMENT:
                reasons.append("instrument_mismatch")
            journal_errors = OperationalSolanaLaunchBaselineForwardRunner.journal_errors(db, study.id)
            if journal_errors:
                reasons.append(f"journal_errors:{len(journal_errors)}")
            latest_nav = db.scalar(
                select(ForwardNavObservation)
                .where(ForwardNavObservation.study_id == study.id)
                .order_by(ForwardNavObservation.observed_at.desc())
                .limit(1)
            )
            nav_age = None
            if latest_nav is None:
                reasons.append("missing_nav")
            else:
                nav_age = (now - _aware(latest_nav.observed_at)).total_seconds()
                if nav_age > settings.solana_forward_health_max_nav_age_seconds:
                    reasons.append("stale_nav")
            state = "ready" if not reasons else "not_ready"
            ready = ready and state == "ready"
            results.append(
                {
                    "external_id": external_id,
                    "study_id": study.id,
                    "cohort": config.cohort if config else None,
                    "state": state,
                    "reasons": reasons,
                    "latest_nav_usd": str(latest_nav.nav_usd) if latest_nav else None,
                    "nav_age_seconds": nav_age,
                }
            )
        payload = {
            "mode": "paper-shadow-only",
            "signer_enabled": False,
            "ready": ready,
            "studies": results,
        }
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
