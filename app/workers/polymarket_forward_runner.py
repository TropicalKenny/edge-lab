from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.polymarket_forward_operational import OperationalPolymarketStructuralForwardRunner
from app.services import HealthRegistry
from app.venues.polymarket import PolymarketPublicClient

log = logging.getLogger("edge_lab.polymarket_forward_runner")


async def run() -> None:
    settings = get_settings()
    health = HealthRegistry()
    SessionLocal = get_session_factory()
    async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
        runner = OperationalPolymarketStructuralForwardRunner(client=client, health=health)
        while True:
            db = SessionLocal()
            try:
                results = await runner.run_active_studies(db)
                for result in results:
                    log.info(
                        "Polymarket forward study %s: %s - %s",
                        result.study_id,
                        result.action,
                        result.detail,
                    )
            except Exception:
                db.rollback()
                log.exception("Polymarket forward runner cycle failed")
            finally:
                db.close()
            await asyncio.sleep(settings.polymarket_forward_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
