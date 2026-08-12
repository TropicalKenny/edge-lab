from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.hyperliquid_research import HyperliquidResearchService
from app.services import HealthRegistry
from app.venues.hyperliquid import HyperliquidInfoClient

log = logging.getLogger("edge_lab.hyperliquid_collector")


async def run() -> None:
    settings = get_settings()
    health = HealthRegistry()
    SessionLocal = get_session_factory()
    funding_coins = [c.strip().upper() for c in settings.hyperliquid_funding_coins.split(",") if c.strip()]
    last_funding_poll = 0.0
    loop = asyncio.get_running_loop()

    async with HyperliquidInfoClient(
        network=settings.hyperliquid_network,
        timeout_seconds=settings.hyperliquid_timeout_seconds,
    ) as client:
        service = HyperliquidResearchService(client=client, health=health)
        while True:
            db = SessionLocal()
            try:
                perps, spots = await service.market_state(db, persist=True)
                log.info("stored Hyperliquid snapshot: %s perps, %s spots", len(perps), len(spots))

                if loop.time() - last_funding_poll >= settings.hyperliquid_funding_poll_seconds:
                    for coin in funding_coins:
                        try:
                            points = await service.funding_history(db, coin=coin, hours=6, persist=True)
                            log.info("refreshed %s funding history: %s rows", coin, len(points))
                        except Exception:
                            log.exception("Hyperliquid funding refresh failed for %s", coin)
                    last_funding_poll = loop.time()
            except Exception:
                log.exception("Hyperliquid market snapshot failed")
            finally:
                db.close()
            await asyncio.sleep(settings.hyperliquid_market_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
