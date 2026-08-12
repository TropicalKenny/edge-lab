import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base
from app.venues.hyperliquid_models import HyperliquidFundingSnapshot, HyperliquidPerpSnapshot, HyperliquidSpotSnapshot
from app.services import HealthRegistry, PaperBroker
from app.hyperliquid_research import HyperliquidResearchService, HyperliquidSnapshotRepository
from app.venues.hyperliquid import (
    FundingCarryAnalyzer,
    HyperliquidInfoClient,
    HyperliquidInfoError,
    l2_book_to_paper_order,
    parse_funding_history,
    parse_perp_contexts,
    parse_spot_contexts,
    subscription_message,
)

NOW = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)

PERP_PAYLOAD = [
    {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 25}]},
    [
        {"markPx": "120000", "midPx": "119999", "oraclePx": "119980", "funding": "0.0002", "premium": "0.0001", "openInterest": "100", "dayNtlVlm": "50000000"},
        {"markPx": "4500", "midPx": "4499", "oraclePx": "4498", "funding": "-0.00002", "premium": "-0.00001", "openInterest": "500", "dayNtlVlm": "20000000"},
    ],
]

SPOT_PAYLOAD = [
    {
        "tokens": [
            {"name": "USDC", "index": 0},
            {"name": "UBTC", "index": 150},
            {"name": "ETH", "index": 151},
        ],
        "universe": [
            {"name": "@107", "tokens": [150, 0], "index": 107},
            {"name": "@108", "tokens": [151, 0], "index": 108},
        ],
    },
    [
        {"midPx": "119900", "markPx": "119905", "dayNtlVlm": "8000000"},
        {"midPx": "4495", "markPx": "4496", "dayNtlVlm": "4000000"},
    ],
]

FUNDING_PAYLOAD = [
    {"coin": "BTC", "fundingRate": "0.0001", "premium": "0.00005", "time": NOW_MS - 3600000},
    {"coin": "BTC", "fundingRate": "0.0002", "premium": "0.00010", "time": NOW_MS},
]

BOOK_PAYLOAD = {
    "coin": "BTC",
    "time": NOW_MS,
    "levels": [
        [{"px": "119990", "sz": "0.5", "n": 2}, {"px": "119980", "sz": "1.0", "n": 3}],
        [{"px": "120000", "sz": "0.25", "n": 2}, {"px": "120010", "sz": "1.0", "n": 4}],
    ],
}


def test_parses_perp_and_noncanonical_spot_metadata():
    perps = parse_perp_contexts(PERP_PAYLOAD, captured_at=NOW)
    spots = parse_spot_contexts(SPOT_PAYLOAD, captured_at=NOW)
    assert perps[0].coin == "BTC" and perps[0].funding_rate_hourly == Decimal("0.0002")
    assert spots[0].book_coin == "@107"
    assert spots[0].pair == "UBTC/USDC"
    assert spots[0].base == "UBTC"


def test_metadata_context_mismatch_fails_closed():
    with pytest.raises(HyperliquidInfoError):
        parse_perp_contexts([{"universe": [{"name": "BTC"}]}, []])
    with pytest.raises(HyperliquidInfoError):
        parse_spot_contexts([{"tokens": [], "universe": [{"name": "@1"}]}, []])


def test_funding_carry_is_cost_aware_and_aliases_btc():
    perps = parse_perp_contexts(PERP_PAYLOAD, captured_at=NOW)
    spots = parse_spot_contexts(SPOT_PAYLOAD, captured_at=NOW)
    results = FundingCarryAnalyzer().analyze(perps, spots, horizon_hours=24)
    btc = next(x for x in results if x.coin == "BTC")
    eth = next(x for x in results if x.coin == "ETH")
    assert btc.spot_pair == "UBTC/USDC"
    assert btc.gross_funding_pct == Decimal("0.0048")
    assert btc.estimated_cost_pct == Decimal("0.0031")
    assert btc.expected_edge_pct == Decimal("0.0017")
    assert btc.eligible
    assert not eth.eligible and "NON_POSITIVE_FUNDING" in eth.reasons


def test_l2_book_maps_into_shared_paper_engine():
    order = l2_book_to_paper_order(BOOK_PAYLOAD, side="buy", quantity=Decimal("0.5"), fee_bps=Decimal("4.5"))
    result = PaperBroker.simulate(order, now=NOW)
    assert result.status == "filled"
    assert result.filled_quantity == Decimal("0.5")
    assert result.average_price == Decimal("120005")
    assert result.total_fees > 0


def test_public_info_client_posts_only_to_info_endpoint():
    seen = []
    async def handler(request: httpx.Request):
        seen.append((str(request.url), request.content.decode()))
        return httpx.Response(200, json=PERP_PAYLOAD)
    async def run():
        transport = httpx.MockTransport(handler)
        async with HyperliquidInfoClient(transport=transport) as client:
            payload = await client.meta_and_asset_contexts()
            assert payload == PERP_PAYLOAD
            assert not hasattr(client, "place_order")
    asyncio.run(run())
    assert seen and seen[0][0].endswith("/info")
    assert '"type":"metaAndAssetCtxs"' in seen[0][1]


def test_research_service_persists_snapshots_and_updates_health():
    async def handler(request: httpx.Request):
        body = request.content.decode()
        if "spotMetaAndAssetCtxs" in body:
            return httpx.Response(200, json=SPOT_PAYLOAD)
        if "metaAndAssetCtxs" in body:
            return httpx.Response(200, json=PERP_PAYLOAD)
        return httpx.Response(400)
    async def run():
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        health = HealthRegistry()
        async with HyperliquidInfoClient(transport=httpx.MockTransport(handler)) as client:
            service = HyperliquidResearchService(client=client, health=health)
            perps, spots = await service.market_state(db, persist=True)
        assert len(perps) == 2 and len(spots) == 2
        assert len(db.scalars(select(HyperliquidPerpSnapshot)).all()) == 2
        assert len(db.scalars(select(HyperliquidSpotSnapshot)).all()) == 2
        assert health.c["market_data"].healthy
        db.close()
    asyncio.run(run())


def test_funding_persistence_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    points = parse_funding_history(FUNDING_PAYLOAD)
    assert HyperliquidSnapshotRepository.save_funding(db, points) == 2
    assert HyperliquidSnapshotRepository.save_funding(db, points) == 0
    assert len(db.scalars(select(HyperliquidFundingSnapshot)).all()) == 2
    db.close()


def test_failed_refresh_marks_market_data_unhealthy():
    async def handler(_: httpx.Request):
        return httpx.Response(503, text="down")
    async def run():
        health = HealthRegistry()
        async with HyperliquidInfoClient(transport=httpx.MockTransport(handler)) as client:
            service = HyperliquidResearchService(client=client, health=health)
            with pytest.raises(HyperliquidInfoError):
                await service.market_state(persist=False)
        assert not health.c["market_data"].healthy
        assert not health.dependency_health().healthy
    asyncio.run(run())


def test_subscription_message_is_read_only_subscribe_shape():
    msg = subscription_message({"type": "l2Book", "coin": "BTC"})
    assert msg == '{"method":"subscribe","subscription":{"type":"l2Book","coin":"BTC"}}'
