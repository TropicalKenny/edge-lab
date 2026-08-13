from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.hyperliquid_forward_operational import OperationalHyperliquidCarryForwardRunner
from app.services import HealthRegistry
from app.venues.hyperliquid import HyperliquidInfoClient

log = logging.getLogger("edge_lab.hyperliquid_forward_runner")


async def run() -> None:
    settings = get_settings()
    health = HealthRegistry()
    SessionLocal = get_session_factory()

    async with HyperliquidInfoClient(
        network=settings.hyperliquid_network,
        timeout_seconds=settings.hyperliquid_timeout_seconds,
    ) as client:
        runner = OperationalHyperliquidCarryForwardRunner(client=client, health=health)
        while True:
            db = SessionLocal()
            try:
                results = await runner.run_active_studies(db)
                for result in results:
                    log.info(
                        "Hyperliquid forward study %s: %s - %s",
                        result.study_id,
                        result.action,
                        result.detail,
                    )
            except Exception:
                db.rollback()
                log.exception("Hyperliquid forward runner cycle failed")
            finally:
                db.close()
            await asyncio.sleep(settings.hyperliquid_forward_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
