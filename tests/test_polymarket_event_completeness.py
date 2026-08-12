import asyncio
from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from app.polymarket_research import PolymarketResearchService
from app.services import HealthRegistry
from app.venues.polymarket import PolymarketPublicClient, StructuralArbitrageAnalyzer


def _market(i: int, *, accepting: bool = True) -> dict:
    return {
        "id": f"m{i}",
        "conditionId": f"c{i}",
        "question": f"Outcome {i}?",
        "slug": f"m{i}",
        "outcomes": ["Yes", "No"],
        "clobTokenIds": [f"y{i}", f"n{i}"],
        "active": True,
        "closed": False,
        "acceptingOrders": accepting,
        "enableOrderBook": True,
        "negRisk": True,
        "feesEnabled": False,
        "resolutionSource": "https://example.com/official",
        "description": "Exactly one outcome resolves Yes.",
        "groupItemTitle": f"Outcome {i}",
        "events": [{"id": "e-neg", "slug": "e-neg", "title": "NegRisk Event", "negRisk": True}],
    }


def _clob_info(i: int) -> dict:
    return {
        "t": [{"t": f"y{i}", "o": "Yes"}, {"t": f"n{i}", "o": "No"}],
        "mts": "0.01",
        "mos": "1",
        "fd": {"r": "0", "e": "1", "to": True},
        "nr": True,
    }


def _book(token: str, condition: str) -> dict:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "market": condition,
        "asset_id": token,
        "timestamp": str(now_ms),
        "hash": f"hash-{token}",
        "bids": [{"price": "0.40", "size": "10"}],
        "asks": [{"price": "0.45", "size": "10"}],
        "min_order_size": "1",
        "tick_size": "0.01",
        "neg_risk": True,
        "last_trade_price": "0.44",
    }


def test_negrisk_event_rejects_when_any_declared_outcome_is_unavailable():
    initial = _market(0)
    incomplete_event = {
        "id": "e-neg",
        "title": "NegRisk Event",
        "slug": "e-neg",
        "description": "Exactly one outcome resolves Yes.",
        "resolutionSource": "https://example.com/official",
        "negRisk": True,
        "enableNegRisk": True,
        "negRiskAugmented": False,
        "markets": [_market(0), _market(1), _market(2, accepting=False)],
    }

    async def gamma_handler(request: httpx.Request):
        if request.url.path == "/markets/keyset":
            return httpx.Response(200, json={"markets": [initial]})
        if request.url.path == "/events/e-neg":
            return httpx.Response(200, json=incomplete_event)
        return httpx.Response(404)

    async def clob_handler(request: httpx.Request):
        if request.url.path == "/clob-markets/c0":
            return httpx.Response(200, json=_clob_info(0))
        if request.url.path == "/books":
            return httpx.Response(200, json=[_book("y0", "c0"), _book("n0", "c0")])
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
            result = await service.scan(db, max_markets=1, max_negrisk_events=1, persist=False)
        assert result.rejection_counts.get("INCOMPLETE_NEG_RISK_EVENT", 0) >= 1
        assert not any(op.kind.startswith("negrisk_") for op in result.opportunities)
        db.close()

    asyncio.run(run())
