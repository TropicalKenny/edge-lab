from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.solana_research import ForwardLabelService, SolanaForensicService
from app.services import HealthRegistry
from app.venues.solana import DexScreenerClient, GoPlusSolanaClient, JupiterShadowClient
from app.venues.solana_asset import HeliusAssetClient
from app.venues.solana_models import SolanaForensicFeatureSnapshot, SolanaLaunchEvent

log = logging.getLogger("edge_lab.solana_forensic_sampler")


def selected(mint: str, modulo: int) -> bool:
    if modulo <= 1:
        return True
    digest = hashlib.sha256(mint.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulo == 0


async def run_cycle() -> int:
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    health = HealthRegistry()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.solana_max_candidate_age_hours)
    try:
        launches = list(
            db.scalars(
                select(SolanaLaunchEvent)
                .where(SolanaLaunchEvent.observed_at >= cutoff)
                .order_by(SolanaLaunchEvent.observed_at.desc())
                .limit(5000)
            ).all()
        )
        candidates = [launch for launch in launches if selected(launch.mint, settings.solana_enrichment_sample_modulo)]
        chosen: list[SolanaLaunchEvent] = []
        min_interval = timedelta(minutes=settings.solana_min_enrichment_interval_minutes)
        now = datetime.now(timezone.utc)
        for launch in candidates:
            latest = db.scalar(
                select(SolanaForensicFeatureSnapshot)
                .where(SolanaForensicFeatureSnapshot.mint == launch.mint)
                .order_by(SolanaForensicFeatureSnapshot.captured_at.desc())
                .limit(1)
            )
            if latest is not None and now - latest.captured_at < min_interval:
                continue
            chosen.append(launch)
            if len(chosen) >= settings.solana_max_enrichments_per_cycle:
                break

        async with AsyncExitStack() as stack:
            dex = await stack.enter_async_context(DexScreenerClient(timeout_seconds=settings.dexscreener_timeout_seconds))
            goplus = await stack.enter_async_context(
                GoPlusSolanaClient(
                    access_token=settings.goplus_access_token,
                    timeout_seconds=settings.goplus_timeout_seconds,
                )
            )
            helius = None
            if settings.helius_api_key:
                helius = await stack.enter_async_context(
                    HeliusAssetClient(api_key=settings.helius_api_key, timeout_seconds=10)
                )
            jupiter = None
            if settings.jupiter_api_key:
                jupiter = await stack.enter_async_context(
                    JupiterShadowClient(
                        api_key=settings.jupiter_api_key,
                        timeout_seconds=settings.jupiter_timeout_seconds,
                    )
                )
            service = SolanaForensicService(
                dexscreener=dex,
                goplus=goplus,
                helius_assets=helius,
                jupiter=jupiter,
                health=health,
                quote_mint=settings.solana_quote_mint,
            )
            completed = 0
            for launch in chosen:
                try:
                    await service.analyze_mint(
                        db,
                        mint=launch.mint,
                        exit_test_notional_usd=Decimal(str(settings.solana_shadow_exit_notional_usd)),
                    )
                    ForwardLabelService.resolve(db, mint=launch.mint)
                    completed += 1
                except Exception:
                    db.rollback()
                    log.exception("forensic enrichment failed for %s", launch.mint)
            return completed
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    while True:
        completed = await run_cycle()
        log.info("Solana forensic sample cycle completed: %s mints", completed)
        await asyncio.sleep(settings.solana_forensic_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
