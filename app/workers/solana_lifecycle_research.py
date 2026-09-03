from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy import select

from app.config import get_settings
from app.control_service import OwnerControlService
from app.database import get_session_factory
from app.forward_models import ForwardStudy
from app.solana_lifecycle import SolanaLifecycleResearchRunner
from app.venues.solana import JupiterShadowClient

log = logging.getLogger("edge_lab.solana_lifecycle_research")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


async def run_cycle() -> None:
    settings = get_settings()
    if settings.signer_enabled:
        raise RuntimeError("refusing M6H lifecycle research with SIGNER_ENABLED=true")
    if not settings.jupiter_api_key:
        raise RuntimeError("JUPITER_API_KEY is required for quote-only M6H research")

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        active_studies = list(
            db.scalars(
                select(ForwardStudy).where(
                    ForwardStudy.status == "active",
                    ForwardStudy.venue == "solana",
                    ForwardStudy.family == "meme",
                )
            ).all()
        )
        enabled = [
            study for study in active_studies
            if OwnerControlService.lifecycle_enabled(db, study.id)
        ]
        if not enabled:
            log.info("M6H lifecycle disabled by owner control; no observations recorded")
            return
        if len(enabled) != len(active_studies):
            raise RuntimeError(
                "mixed per-study M6H lifecycle state is not supported; refusing cycle fail-closed"
            )

        async with JupiterShadowClient(
            api_key=settings.jupiter_api_key,
            timeout_seconds=settings.jupiter_timeout_seconds,
        ) as jupiter:
            runner = SolanaLifecycleResearchRunner(
                jupiter=jupiter,
                max_observation_age_minutes=_env_int(
                    "LIFECYCLE_MAX_OBSERVATION_AGE_MINUTES", 1440
                ),
                max_feature_age_minutes=_env_int(
                    "LIFECYCLE_MAX_FEATURE_AGE_MINUTES", 15
                ),
            )
            result = await runner.run_active_studies(db)
            log.info(
                "M6H lifecycle cycle studies=%s targets=%s observations=%s decisions=%s",
                result["studies"],
                result["targets"],
                result["observations"],
                result["decisions"],
            )
    finally:
        db.close()


async def run() -> None:
    poll_seconds = _env_int("LIFECYCLE_POLL_SECONDS", 60)
    if poll_seconds < 15 or poll_seconds > 3600:
        raise RuntimeError("LIFECYCLE_POLL_SECONDS must be between 15 and 3600")
    while True:
        try:
            await run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("M6H lifecycle research cycle failed")
        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
