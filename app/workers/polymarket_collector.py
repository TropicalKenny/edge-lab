from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from app.config import get_settings
from app.database import get_session_factory
from app.polymarket_research import PolymarketResearchService
from app.services import HealthRegistry
from app.venues.polymarket import PolymarketPublicClient, StructuralArbitrageAnalyzer

log = logging.getLogger("edge_lab.polymarket_collector")


async def run() -> None:
    settings = get_settings()
    health = HealthRegistry()
    SessionLocal = get_session_factory()
    analyzer = StructuralArbitrageAnalyzer(
        min_edge_bps=Decimal(str(settings.polymarket_min_edge_bps)),
        max_shares=Decimal(str(settings.polymarket_max_shares_per_opportunity)),
        max_book_age_seconds=settings.polymarket_max_book_age_seconds,
    )
    async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
        service = PolymarketResearchService(client=client, health=health, analyzer=analyzer)
        while True:
            db = SessionLocal()
            try:
                result = await service.scan(
                    db,
                    max_markets=settings.polymarket_max_markets,
                    max_negrisk_events=settings.polymarket_max_negrisk_events,
                    persist=True,
                )
                eligible = sum(1 for opportunity in result.opportunities if opportunity.eligible)
                log.info(
                    "Polymarket structural scan: %s opportunities (%s eligible), rejections=%s",
                    len(result.opportunities),
                    eligible,
                    result.rejection_counts,
                )
            except Exception:
                log.exception("Polymarket structural scan failed")
            finally:
                db.close()
            await asyncio.sleep(settings.polymarket_scan_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
