from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.forward_models import ForwardStudy
from app.hyperliquid_forward import HyperliquidCarryForwardRunner
from app.services import HealthRegistry
from app.venues.hyperliquid import HyperliquidInfoClient

log = logging.getLogger("edge_lab.hyperliquid_carry_forward")


async def run_cycle() -> int:
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    health = HealthRegistry()
    try:
        studies = list(
            db.scalars(
                select(ForwardStudy)
                .where(
                    ForwardStudy.status == "active",
                    ForwardStudy.family == "funding",
                    ForwardStudy.venue == "hyperliquid",
                )
                .order_by(ForwardStudy.started_at.asc())
            ).all()
        )
        if not studies:
            return 0
        async with HyperliquidInfoClient(
            network=settings.hyperliquid_network,
            timeout_seconds=settings.hyperliquid_timeout_seconds,
        ) as client:
            runner = HyperliquidCarryForwardRunner(client=client, health=health)
            completed = 0
            for study in studies:
                now = datetime.now(timezone.utc)
                try:
                    result = await runner.run_study_cycle(db, study, now=now)
                    log.info(
                        "carry study cycle study=%s instrument=%s opened=%s closed=%s nav=%s",
                        study.external_id,
                        study.instrument,
                        result["opened"],
                        result["closed"],
                        result["nav_recorded"],
                    )
                    completed += 1
                except Exception:
                    db.rollback()
                    log.exception("Hyperliquid carry forward cycle failed for study=%s", study.external_id)
            return completed
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    while True:
        try:
            completed = await run_cycle()
            log.info("Hyperliquid carry forward worker completed %s studies", completed)
        except Exception:
            log.exception("Hyperliquid carry forward worker cycle failed")
        await asyncio.sleep(settings.hyperliquid_market_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
