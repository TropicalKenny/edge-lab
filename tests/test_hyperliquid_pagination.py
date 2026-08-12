import asyncio
import json
from datetime import datetime, timezone

import httpx

from app.hyperliquid_research import HyperliquidResearchService
from app.services import HealthRegistry
from app.venues.hyperliquid import HyperliquidInfoClient

NOW = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def test_funding_history_paginates_past_500_rows():
    first = [
        {"coin": "BTC", "fundingRate": "0.0001", "premium": "0", "time": NOW_MS - (600 - i) * 3600000}
        for i in range(500)
    ]
    second = [
        {"coin": "BTC", "fundingRate": "0.0002", "premium": "0", "time": first[-1]["time"] + (i + 1) * 3600000}
        for i in range(100)
    ]
    calls = []

    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body["startTime"])
        return httpx.Response(200, json=first if len(calls) == 1 else second)

    async def run():
        health = HealthRegistry()
        async with HyperliquidInfoClient(transport=httpx.MockTransport(handler)) as client:
            service = HyperliquidResearchService(client=client, health=health)
            points = await service.funding_history(None, coin="BTC", hours=700, persist=False, now=NOW)
        assert len(points) == 600
        assert len(calls) == 2 and calls[1] > calls[0]

    asyncio.run(run())
