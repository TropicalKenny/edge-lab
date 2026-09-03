from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.venues.hyperliquid_models import (
    HyperliquidFundingSnapshot,
    HyperliquidPerpSnapshot,
    HyperliquidSpotSnapshot,
)
from app.services import HealthRegistry, PaperBroker
from app.venues.hyperliquid import (
    FundingCarryAnalyzer,
    FundingCarryOpportunity,
    FundingRatePoint,
    HyperliquidInfoClient,
    PerpContext,
    SpotContext,
    l2_book_to_paper_order,
    parse_funding_history,
    parse_perp_contexts,
)
from app.venues.hyperliquid_spot import parse_spot_contexts


class HyperliquidSnapshotRepository:
    @staticmethod
    def save_markets(db: Session, perps: list[PerpContext], spots: list[SpotContext]) -> None:
        db.add_all(
            [
                HyperliquidPerpSnapshot(
                    coin=p.coin,
                    mark_px=p.mark_px,
                    mid_px=p.mid_px,
                    oracle_px=p.oracle_px,
                    funding_rate_hourly=p.funding_rate_hourly,
                    premium=p.premium,
                    open_interest=p.open_interest,
                    day_ntl_volume=p.day_ntl_volume,
                    captured_at=p.captured_at,
                )
                for p in perps
            ]
        )
        db.add_all(
            [
                HyperliquidSpotSnapshot(
                    pair=s.pair,
                    book_coin=s.book_coin,
                    base=s.base,
                    quote=s.quote,
                    mid_px=s.mid_px,
                    day_ntl_volume=s.day_ntl_volume,
                    captured_at=s.captured_at,
                )
                for s in spots
            ]
        )
        db.commit()

    @staticmethod
    def save_funding(db: Session, points: list[FundingRatePoint]) -> int:
        inserted = 0
        for p in points:
            exists = db.scalar(
                select(HyperliquidFundingSnapshot.id).where(
                    HyperliquidFundingSnapshot.coin == p.coin,
                    HyperliquidFundingSnapshot.funding_time == p.time,
                )
            )
            if exists:
                continue
            db.add(
                HyperliquidFundingSnapshot(
                    coin=p.coin,
                    funding_rate=p.funding_rate,
                    premium=p.premium,
                    funding_time=p.time,
                )
            )
            inserted += 1
        db.commit()
        return inserted


class HyperliquidResearchService:
    """Public-data-only Hyperliquid research facade. No exchange actions are exposed."""

    def __init__(
        self,
        *,
        client: HyperliquidInfoClient,
        health: HealthRegistry,
        analyzer: FundingCarryAnalyzer | None = None,
    ) -> None:
        self.client = client
        self.health = health
        self.analyzer = analyzer or FundingCarryAnalyzer()

    async def market_state(
        self,
        db: Session | None = None,
        *,
        persist: bool = True,
    ) -> tuple[list[PerpContext], list[SpotContext]]:
        captured_at = datetime.now(timezone.utc)
        try:
            perp_payload, spot_payload = await asyncio.gather(
                self.client.meta_and_asset_contexts(),
                self.client.spot_meta_and_asset_contexts(),
            )
            perps = parse_perp_contexts(perp_payload, captured_at=captured_at)
            spots = parse_spot_contexts(spot_payload, captured_at=captured_at)
            if not perps or not spots:
                raise RuntimeError("Hyperliquid returned an empty perp or spot universe")
            if persist:
                if db is None:
                    raise RuntimeError("database session required when persist=True")
                HyperliquidSnapshotRepository.save_markets(db, perps, spots)
            self.health.set("hyperliquid", True, f"public market snapshot: {len(perps)} perps/{len(spots)} spots")
            self.health.set("market_data", True, "Hyperliquid public market data available")
            return perps, spots
        except Exception as exc:
            if db is not None:
                db.rollback()
            self.health.set("hyperliquid", False, str(exc))
            self.health.set("market_data", False, "Hyperliquid public market-data refresh failed")
            raise

    async def funding_history(
        self,
        db: Session | None,
        *,
        coin: str,
        hours: int = 168,
        persist: bool = True,
        now: datetime | None = None,
    ) -> list[FundingRatePoint]:
        if hours <= 0 or hours > 24 * 90:
            raise ValueError("hours must be between 1 and 2160")
        now = now or datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)
        end_ms = int(now.timestamp() * 1000)
        cursor_ms = int(start.timestamp() * 1000)
        by_time: dict[tuple[str, datetime], FundingRatePoint] = {}
        pages = 0
        while cursor_ms <= end_ms:
            payload = await self.client.funding_history(coin.upper(), cursor_ms, end_ms)
            if not isinstance(payload, list):
                raise RuntimeError("unexpected Hyperliquid funding-history response")
            points = parse_funding_history(payload)
            for point in points:
                by_time[(point.coin, point.time)] = point
            if not payload or len(payload) < 500:
                break
            if not points:
                raise RuntimeError("funding-history page contained no parseable timestamps")
            last_ms = max(int(point.time.timestamp() * 1000) for point in points)
            if last_ms < cursor_ms:
                raise RuntimeError("funding-history pagination did not advance")
            cursor_ms = last_ms + 1
            pages += 1
            if pages >= 10:
                raise RuntimeError("funding-history pagination exceeded safety page limit")
        result = sorted(by_time.values(), key=lambda point: point.time)
        if persist:
            if db is None:
                raise RuntimeError("database session required when persist=True")
            HyperliquidSnapshotRepository.save_funding(db, result)
        return result

    async def opportunities(
        self,
        db: Session | None = None,
        *,
        horizon_hours: int = 24,
        min_expected_edge_bps: Decimal = Decimal("0"),
        persist_snapshot: bool = True,
    ) -> list[FundingCarryOpportunity]:
        perps, spots = await self.market_state(db, persist=persist_snapshot)
        return self.analyzer.analyze(
            perps,
            spots,
            horizon_hours=horizon_hours,
            min_expected_edge_pct=min_expected_edge_bps / Decimal("10000"),
        )

    async def paper_book(
        self,
        *,
        coin: str,
        side: str,
        quantity: Decimal,
        fee_bps: Decimal,
        allow_partial: bool = True,
    ):
        payload = await self.client.l2_book(coin)
        order = l2_book_to_paper_order(
            payload,
            side=side,
            quantity=quantity,
            fee_bps=fee_bps,
            allow_partial=allow_partial,
        )
        return PaperBroker.simulate(order)


def public_opportunity_dict(o: FundingCarryOpportunity) -> dict:
    data = asdict(o)
    data["reasons"] = list(o.reasons)
    return data
