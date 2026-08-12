import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base
from app.polymarket_research import PolymarketResearchService
from app.services import HealthRegistry
from app.venues.polymarket import (
    FeeSchedule,
    PolymarketPublicClient,
    StructuralArbitrageAnalyzer,
    parse_book,
    parse_event,
    parse_market,
    taker_fee,
)
from app.venues.polymarket_models import (
    PolymarketBookSnapshot,
    PolymarketMarketSnapshot,
    PolymarketStructuralOpportunitySnapshot,
)

NOW = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)


def market_row(
    *,
    market_id="m1",
    condition="c1",
    yes="yes1",
    no="no1",
    yes_question="Will X happen?",
    event_id="e1",
    neg_risk=False,
    fees_enabled=False,
    fee_schedule=None,
    neg_risk_other=False,
    group_item_title=None,
):
    row = {
        "id": market_id,
        "conditionId": condition,
        "question": yes_question,
        "slug": market_id,
        "outcomes": ["Yes", "No"],
        "clobTokenIds": [yes, no],
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
        "negRisk": neg_risk,
        "negRiskOther": neg_risk_other,
        "feesEnabled": fees_enabled,
        "resolutionSource": "https://example.com/source",
        "description": "Resolves from the named official source.",
        "events": [{"id": event_id, "slug": event_id, "title": "Event", "negRisk": neg_risk}],
    }
    if fee_schedule is not None:
        row["feeSchedule"] = fee_schedule
    if group_item_title is not None:
        row["groupItemTitle"] = group_item_title
    return row


def book_row(token, condition, asks, *, when=NOW, neg_risk=False):
    return {
        "market": condition,
        "asset_id": token,
        "timestamp": str(int(when.timestamp() * 1000)),
        "hash": f"hash-{token}",
        "bids": [{"price": "0.40", "size": "100"}],
        "asks": [{"price": str(price), "size": str(size)} for price, size in asks],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": neg_risk,
        "last_trade_price": "0.45",
    }


def test_fee_curve_matches_v2_formula():
    schedule = FeeSchedule(rate=Decimal("0.04"), exponent=1, taker_only=True)
    assert taker_fee(Decimal("100"), Decimal("0.5"), schedule) == Decimal("1.00000")
    curved = FeeSchedule(rate=Decimal("0.02"), exponent=2, taker_only=True)
    assert taker_fee(Decimal("100"), Decimal("0.5"), curved) == Decimal("0.12500")


def test_binary_complete_set_walks_common_depth():
    market = parse_market(market_row(), captured_at=NOW)
    books = {
        "yes1": parse_book(book_row("yes1", "c1", [("0.47", "4"), ("0.48", "6")]), captured_at=NOW),
        "no1": parse_book(book_row("no1", "c1", [("0.48", "10")]), captured_at=NOW),
    }
    analyzer = StructuralArbitrageAnalyzer(min_edge_bps=Decimal("1"), max_shares=Decimal("100"))
    opportunity, reasons = analyzer.binary_complete_set(market, books, now=NOW)
    assert reasons == ()
    assert opportunity is not None and opportunity.eligible
    assert opportunity.quantity == Decimal("10")
    assert opportunity.payout == Decimal("10")
    assert opportunity.total_cost == Decimal("9.56")
    assert opportunity.net_profit == Decimal("0.44")


def test_fees_can_remove_apparent_binary_edge():
    row = market_row(
        fees_enabled=True,
        fee_schedule={"rate": "0.07", "exponent": "1", "takerOnly": True, "rebateRate": "0.2"},
    )
    market = parse_market(row, captured_at=NOW)
    books = {
        "yes1": parse_book(book_row("yes1", "c1", [("0.495", "10")]), captured_at=NOW),
        "no1": parse_book(book_row("no1", "c1", [("0.495", "10")]), captured_at=NOW),
    }
    opportunity, reasons = StructuralArbitrageAnalyzer(min_edge_bps=0).binary_complete_set(market, books, now=NOW)
    assert opportunity is None
    assert "NO_EXECUTABLE_EDGE" in reasons


def test_missing_fee_schedule_fails_closed():
    market = parse_market(market_row(fees_enabled=True), captured_at=NOW)
    books = {
        "yes1": parse_book(book_row("yes1", "c1", [("0.40", "10")]), captured_at=NOW),
        "no1": parse_book(book_row("no1", "c1", [("0.40", "10")]), captured_at=NOW),
    }
    opportunity, reasons = StructuralArbitrageAnalyzer().binary_complete_set(market, books, now=NOW)
    assert opportunity is None and reasons == ("UNKNOWN_FEE_SCHEDULE",)


def test_stale_book_fails_closed():
    market = parse_market(market_row(), captured_at=NOW)
    stale = NOW - timedelta(seconds=30)
    books = {
        "yes1": parse_book(book_row("yes1", "c1", [("0.40", "10")], when=stale), captured_at=NOW),
        "no1": parse_book(book_row("no1", "c1", [("0.40", "10")], when=stale), captured_at=NOW),
    }
    opportunity, reasons = StructuralArbitrageAnalyzer(max_book_age_seconds=5).binary_complete_set(market, books, now=NOW)
    assert opportunity is None and "STALE_BOOK" in reasons


def make_negrisk_event(*, augmented=False, other=False):
    markets = []
    for i in range(3):
        markets.append(
            market_row(
                market_id=f"m{i}",
                condition=f"c{i}",
                yes=f"y{i}",
                no=f"n{i}",
                event_id="e-neg",
                neg_risk=True,
                neg_risk_other=other and i == 2,
                group_item_title="Other" if other and i == 2 else f"Outcome {i}",
            )
        )
    return {
        "id": "e-neg",
        "title": "Who wins?",
        "slug": "who-wins",
        "description": "Exactly one named outcome resolves Yes.",
        "resolutionSource": "https://example.com/official",
        "negRisk": True,
        "enableNegRisk": True,
        "negRiskAugmented": augmented,
        "markets": markets,
    }


def negrisk_books():
    books = {}
    for i in range(3):
        books[f"y{i}"] = parse_book(book_row(f"y{i}", f"c{i}", [("0.30", "10")], neg_risk=True), captured_at=NOW)
        books[f"n{i}"] = parse_book(book_row(f"n{i}", f"c{i}", [("0.60", "10")], neg_risk=True), captured_at=NOW)
    return books


def test_standard_negrisk_detects_yes_and_no_complete_sets():
    event = parse_event(make_negrisk_event(), captured_at=NOW)
    opportunities, rejected = StructuralArbitrageAnalyzer(min_edge_bps=1).neg_risk_event(event, negrisk_books(), now=NOW)
    assert rejected == {}
    kinds = {o.kind for o in opportunities}
    assert kinds == {"negrisk_yes_complete_set", "negrisk_no_complete_set"}
    assert all(o.eligible for o in opportunities)
    assert next(o for o in opportunities if o.kind == "negrisk_yes_complete_set").net_profit == Decimal("1.00")
    assert next(o for o in opportunities if o.kind == "negrisk_no_complete_set").net_profit == Decimal("2.00")


def test_augmented_negrisk_is_deferred():
    event = parse_event(make_negrisk_event(augmented=True), captured_at=NOW)
    opportunities, rejected = StructuralArbitrageAnalyzer().neg_risk_event(event, negrisk_books(), now=NOW)
    assert opportunities == [] and rejected == {"AUGMENTED_NEG_RISK_DEFERRED": 1}


def test_other_outcome_is_reported_but_not_eligible():
    event = parse_event(make_negrisk_event(other=True), captured_at=NOW)
    opportunities, _ = StructuralArbitrageAnalyzer(min_edge_bps=1).neg_risk_event(event, negrisk_books(), now=NOW)
    assert opportunities
    assert all(not o.eligible and "DYNAMIC_OTHER_OUTCOME" in o.reasons for o in opportunities)


def test_public_client_has_no_order_surface_and_uses_public_endpoints():
    seen = []

    async def gamma_handler(request: httpx.Request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"markets": [], "next_cursor": None})

    async def clob_handler(request: httpx.Request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"t": [{"t": "yes", "o": "Yes"}], "mts": 0.01, "mos": 1, "fd": {"r": 0, "e": 1, "to": True}})

    async def run():
        async with PolymarketPublicClient(
            gamma_transport=httpx.MockTransport(gamma_handler),
            clob_transport=httpx.MockTransport(clob_handler),
        ) as client:
            await client.list_markets_page()
            await client.get_clob_market_info("c1")
            assert not hasattr(client, "place_order")
            assert not hasattr(client, "cancel_order")

    asyncio.run(run())
    assert any("gamma-api.polymarket.com/markets/keyset" in url for url in seen)
    assert any("clob.polymarket.com/clob-markets/c1" in url for url in seen)


def test_full_structural_scan_persists_reproducible_snapshot():
    now = datetime.now(timezone.utc)
    market = market_row(event_id="e-simple")
    market["events"] = [{"id": "e-simple", "slug": "simple", "title": "Simple", "negRisk": False}]
    yes_book = book_row("yes1", "c1", [("0.45", "10")], when=now)
    no_book = book_row("no1", "c1", [("0.45", "10")], when=now)

    async def gamma_handler(request: httpx.Request):
        if request.url.path == "/markets/keyset":
            return httpx.Response(200, json={"markets": [market]})
        return httpx.Response(404)

    async def clob_handler(request: httpx.Request):
        if request.url.path == "/books":
            return httpx.Response(200, json=[yes_book, no_book])
        return httpx.Response(404)

    async def run():
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = Session(engine)
        health = HealthRegistry()
        async with PolymarketPublicClient(
            gamma_transport=httpx.MockTransport(gamma_handler),
            clob_transport=httpx.MockTransport(clob_handler),
        ) as client:
            service = PolymarketResearchService(
                client=client,
                health=health,
                analyzer=StructuralArbitrageAnalyzer(min_edge_bps=1, max_book_age_seconds=30),
            )
            result = await service.scan(db, max_markets=1, max_negrisk_events=0, persist=True)
        assert len(result.opportunities) == 1 and result.opportunities[0].eligible
        assert len(db.scalars(select(PolymarketMarketSnapshot)).all()) == 1
        assert len(db.scalars(select(PolymarketBookSnapshot)).all()) == 2
        stored = db.scalars(select(PolymarketStructuralOpportunitySnapshot)).one()
        assert stored.net_profit > 0 and json.loads(stored.legs_json)
        assert health.c["polymarket"].healthy
        db.close()

    asyncio.run(run())
