from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.solana_research import SolanaResearchRepository
from app.venues.solana import HeliusPumpStream, parse_pump_launch_notification

log = logging.getLogger("edge_lab.solana_launch_collector")


async def run() -> None:
    settings = get_settings()
    if not settings.helius_api_key:
        raise RuntimeError("HELIUS_API_KEY is required to run the Solana launch collector")
    programs = [x.strip() for x in settings.helius_pump_program_ids.split(",") if x.strip()]
    stream = HeliusPumpStream(
        api_key=settings.helius_api_key,
        program_ids=programs,
        commitment=settings.helius_commitment,
    )
    SessionLocal = get_session_factory()
    async for notification in stream.stream():
        event = parse_pump_launch_notification(notification)
        if event is None:
            continue
        db = SessionLocal()
        try:
            if SolanaResearchRepository.save_launch(db, event):
                log.info("new Pump launch: mint=%s creator=%s signature=%s", event.mint, event.creator, event.signature)
        except Exception:
            db.rollback()
            log.exception("failed to persist Pump launch %s", event.signature)
        finally:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
