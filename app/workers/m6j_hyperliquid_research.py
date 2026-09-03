from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.forward_models import ForwardStudy
from app.hyperliquid_research import HyperliquidResearchService
from app.research_acceleration import parse_csv_ints, parse_csv_symbols
from app.scan_telemetry import record_scan_observation
from app.services import HealthRegistry
from app.venues.hyperliquid import FundingCarryAnalyzer, HyperliquidInfoClient

log = logging.getLogger("edge_lab.m6j_hyperliquid")
BPS = Decimal("10000")
ZERO = Decimal("0")


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / Decimal(len(values)) if values else None


def _mean_since(points, since: datetime) -> Decimal | None:
    values = [Decimal(point.funding_rate) for point in points if point.time >= since]
    return _mean(values)


async def _cycle(client: HyperliquidInfoClient) -> None:
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        study = db.scalar(
            select(ForwardStudy)
            .where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "hyperliquid",
                ForwardStudy.family == "funding",
            )
            .order_by(ForwardStudy.started_at.asc())
            .limit(1)
        )
        if study is None:
            return

        health = HealthRegistry()
        service = HyperliquidResearchService(client=client, health=health)
        perps, spots = await service.market_state(db, persist=False)
        analyzer = FundingCarryAnalyzer(
            perp_taker_fee_bps=Decimal(str(settings.hyperliquid_forward_perp_fee_bps)),
            spot_taker_fee_bps=Decimal(str(settings.hyperliquid_forward_spot_fee_bps)),
            slippage_reserve_bps_per_leg=Decimal(
                str(settings.hyperliquid_forward_slippage_reserve_bps_per_leg)
            ),
        )
        coins = parse_csv_symbols(settings.m6j_hyperliquid_coins)
        horizons = parse_csv_ints(
            settings.m6j_hyperliquid_horizons_hours,
            minimum=1,
            maximum=24 * 30,
        )
        now = datetime.now(timezone.utc)
        history_hours = max(168, min(settings.m6j_hyperliquid_history_hours, 24 * 90))
        history_by_coin = {}
        for coin in coins:
            try:
                history_by_coin[coin] = await service.funding_history(
                    None,
                    coin=coin,
                    hours=history_hours,
                    persist=False,
                    now=now,
                )
            except Exception:
                log.exception("M6J funding-history refresh failed for %s", coin)
                history_by_coin[coin] = []

        examined = accepted = rejected = 0
        for horizon in horizons:
            opportunities = analyzer.analyze(
                perps,
                spots,
                horizon_hours=horizon,
                min_expected_edge_pct=ZERO,
            )
            by_coin = {opportunity.coin.upper(): opportunity for opportunity in opportunities}
            for coin in coins:
                opportunity = by_coin.get(coin)
                if opportunity is None:
                    continue
                examined += 1
                positive = opportunity.expected_edge_pct > ZERO and opportunity.funding_rate_hourly > ZERO
                accepted += int(positive)
                rejected += int(not positive)
                points = history_by_coin.get(coin) or []
                mean_7d = _mean_since(points, now - timedelta(days=7))
                mean_30d = _mean_since(points, now - timedelta(days=30))
                estimated_cost_bps = opportunity.estimated_cost_pct * BPS
                metadata = {
                    "research_lane": "m6j",
                    "research_mode": "observation_only_no_execution",
                    "coin": coin,
                    "horizon_hours": horizon,
                    "spot_pair": opportunity.spot_pair,
                    "current_funding_hourly": str(opportunity.funding_rate_hourly),
                    "current_projected_edge_bps": str(opportunity.expected_edge_pct * BPS),
                    "estimated_round_trip_cost_bps": str(estimated_cost_bps),
                    "basis_bps": str(opportunity.basis_bps),
                    "baseline_min_edge_bps": str(settings.hyperliquid_forward_min_edge_bps),
                    "trailing_7d_mean_funding_hourly": str(mean_7d) if mean_7d is not None else None,
                    "trailing_7d_projected_edge_bps": (
                        str(mean_7d * Decimal(horizon) * BPS - estimated_cost_bps)
                        if mean_7d is not None
                        else None
                    ),
                    "trailing_30d_mean_funding_hourly": str(mean_30d) if mean_30d is not None else None,
                    "trailing_30d_projected_edge_bps": (
                        str(mean_30d * Decimal(horizon) * BPS - estimated_cost_bps)
                        if mean_30d is not None
                        else None
                    ),
                    "history_points": len(points),
                }
                bucket = int(now.timestamp() // settings.m6j_hyperliquid_poll_seconds)
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=f"m6j:hyperliquid:{coin}:{horizon}:{bucket}",
                    observation_kind="candidate",
                    observed_at=now,
                    examined_count=1,
                    accepted_count=int(positive),
                    rejected_count=int(not positive),
                    rejection_reasons={} if positive else {"NO_POSITIVE_EDGE_AFTER_COSTS": 1},
                    metadata=metadata,
                )

        bucket = int(now.timestamp() // settings.m6j_hyperliquid_poll_seconds)
        record_scan_observation(
            db,
            study_id=study.id,
            external_key=f"m6j:hyperliquid:cycle:{bucket}",
            observation_kind="cycle",
            observed_at=now,
            metadata={
                "research_lane": "m6j",
                "research_mode": "observation_only_no_execution",
                "m6j_horizons_tested": len(horizons),
                "m6j_assets_tested": len(coins),
                "m6j_candidates_examined": examined,
                "m6j_positive_edge_candidates": accepted,
                "m6j_nonpositive_edge_candidates": rejected,
            },
        )
        log.info("M6J Hyperliquid cycle: examined=%s positive=%s", examined, accepted)
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    if not settings.m6j_enabled:
        log.info("M6J is disabled")
        return
    async with HyperliquidInfoClient(
        network=settings.hyperliquid_network,
        timeout_seconds=settings.hyperliquid_timeout_seconds,
    ) as client:
        while True:
            try:
                await _cycle(client)
            except Exception:
                log.exception("M6J Hyperliquid cycle failed")
            await asyncio.sleep(settings.m6j_hyperliquid_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
