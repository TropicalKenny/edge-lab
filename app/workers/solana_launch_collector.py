from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.solana_research import SolanaResearchRepository
from app.venues.solana import HeliusPumpStream, parse_pump_launch_notification
from app.venues.solana_rpc import SolanaRpcPumpStream

log = logging.getLogger("edge_lab.solana_launch_collector")


async def run() -> None:
    settings = get_settings()
    programs = [x.strip() for x in settings.solana_pump_program_ids.split(",") if x.strip()]
    rpc_http = settings.solana_rpc_http_url.strip()
    rpc_ws = settings.solana_rpc_ws_url.strip()

    if bool(rpc_http) != bool(rpc_ws):
        raise RuntimeError("SOLANA_RPC_HTTP_URL and SOLANA_RPC_WS_URL must be configured together")

    if rpc_http and rpc_ws:
        stream = SolanaRpcPumpStream(
            http_url=rpc_http,
            ws_url=rpc_ws,
            program_ids=programs,
            commitment=settings.solana_rpc_commitment,
            timeout_seconds=settings.solana_rpc_timeout_seconds,
        )
        log.info("Solana launch collector using standard RPC provider")
    elif settings.helius_api_key:
        stream = HeliusPumpStream(
            api_key=settings.helius_api_key,
            program_ids=programs,
            commitment=settings.helius_commitment,
        )
        log.info("Solana launch collector using legacy Helius transactionSubscribe fallback")
    else:
        raise RuntimeError(
            "Solana launch collector requires SOLANA_RPC_HTTP_URL + SOLANA_RPC_WS_URL or HELIUS_API_KEY"
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
