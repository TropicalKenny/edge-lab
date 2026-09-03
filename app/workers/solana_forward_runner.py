from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack

from app.config import get_settings
from app.database import get_session_factory
from app.services import HealthRegistry
from app.solana_forward_operational import OperationalSolanaLaunchBaselineForwardRunner
from app.solana_research import SolanaForensicService
from app.venues.solana import DexScreenerClient, GoPlusSolanaClient, JupiterShadowClient
from app.venues.solana_asset import HeliusAssetClient
from app.venues.solana_rpc import SolanaRpcAssetClient

log = logging.getLogger("edge_lab.solana_forward_runner")


async def run_cycle() -> None:
    settings = get_settings()
    if settings.signer_enabled:
        raise RuntimeError("refusing Solana forward runner with SIGNER_ENABLED=true")
    if not settings.jupiter_api_key:
        raise RuntimeError("JUPITER_API_KEY is required for quote-only Solana forward research")

    rpc_http = settings.solana_rpc_http_url.strip()
    if not rpc_http and not settings.helius_api_key:
        raise RuntimeError("Solana forward research requires SOLANA_RPC_HTTP_URL or HELIUS_API_KEY")

    SessionLocal = get_session_factory()
    db = SessionLocal()
    health = HealthRegistry()
    try:
        async with AsyncExitStack() as stack:
            dex = await stack.enter_async_context(
                DexScreenerClient(timeout_seconds=settings.dexscreener_timeout_seconds)
            )
            goplus = await stack.enter_async_context(
                GoPlusSolanaClient(
                    access_token=settings.goplus_access_token,
                    timeout_seconds=settings.goplus_timeout_seconds,
                )
            )
            if rpc_http:
                asset_client = await stack.enter_async_context(
                    SolanaRpcAssetClient(
                        http_url=rpc_http,
                        commitment=settings.solana_rpc_commitment,
                        timeout_seconds=settings.solana_rpc_timeout_seconds,
                    )
                )
            else:
                asset_client = await stack.enter_async_context(
                    HeliusAssetClient(api_key=settings.helius_api_key, timeout_seconds=10)
                )
            jupiter = await stack.enter_async_context(
                JupiterShadowClient(
                    api_key=settings.jupiter_api_key,
                    timeout_seconds=settings.jupiter_timeout_seconds,
                )
            )
            forensics = SolanaForensicService(
                dexscreener=dex,
                goplus=goplus,
                helius_assets=asset_client,
                jupiter=jupiter,
                health=health,
                quote_mint=settings.solana_quote_mint,
            )
            runner = OperationalSolanaLaunchBaselineForwardRunner(
                forensics=forensics,
                jupiter=jupiter,
                health=health,
            )
            ticks = await runner.run_active_studies(db)
            for tick in ticks:
                log.info(
                    "Solana forward tick study=%s action=%s detail=%s",
                    tick.study_id,
                    tick.action,
                    tick.detail,
                )
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    while True:
        try:
            await run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Solana forward cycle failed")
        await asyncio.sleep(settings.solana_forward_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
