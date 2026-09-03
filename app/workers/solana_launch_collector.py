from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.solana_research import SolanaResearchRepository
from app.venues.solana import HeliusPumpStream, PUMP_PROGRAM_ID, parse_pump_launch_notification
from app.venues.solana_rpc_sampled import SolanaRpcSampledPumpStream

log = logging.getLogger("edge_lab.solana_launch_collector")


async def run() -> None:
    settings = get_settings()
    rpc_http = settings.solana_rpc_http_url.strip()

    if rpc_http:
        # Cost guard: never use the configured standard-RPC WebSocket for Pump
        # discovery. A program-wide logsSubscribe stream is bandwidth-priced and
        # can consume millions of CUs before client-side filtering. Poll only the
        # Pump creation program over bounded HTTP instead. PumpSwap migrations do
        # not create the mint, so the PumpSwap program is intentionally excluded.
        stream = SolanaRpcSampledPumpStream(
            http_url=rpc_http,
            program_ids=[PUMP_PROGRAM_ID],
            commitment=settings.solana_rpc_commitment,
            timeout_seconds=settings.solana_rpc_timeout_seconds,
            poll_seconds=60,
            signatures_per_program=1000,
            max_transactions_per_poll=3,
            hourly_cu_budget=10_000,
        )
        log.info(
            "Solana launch collector using bounded HTTP sampling; broad RPC WebSocket disabled; "
            "estimated ceiling=%s CU/hour",
            stream.estimated_hourly_cu,
        )
        if settings.solana_rpc_ws_url.strip():
            log.info("SOLANA_RPC_WS_URL is configured but intentionally unused by launch discovery")
    elif settings.helius_api_key:
        programs = [x.strip() for x in settings.helius_pump_program_ids.split(",") if x.strip()]
        stream = HeliusPumpStream(
            api_key=settings.helius_api_key,
            program_ids=programs,
            commitment=settings.helius_commitment,
        )
        log.info("Solana launch collector using legacy Helius transactionSubscribe fallback")
    else:
        raise RuntimeError(
            "Solana launch collector requires SOLANA_RPC_HTTP_URL or legacy HELIUS_API_KEY"
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
