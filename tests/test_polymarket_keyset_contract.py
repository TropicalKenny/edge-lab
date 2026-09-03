import asyncio

import httpx

from app.venues.polymarket import PolymarketPublicClient


def test_gamma_keyset_uses_current_camelcase_liquidity_sort_field():
    seen = {}

    async def handler(request: httpx.Request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"markets": [], "next_cursor": None})

    async def run():
        async with PolymarketPublicClient(gamma_transport=httpx.MockTransport(handler)) as client:
            await client.list_markets_page(limit=2)

    asyncio.run(run())
    assert seen["params"]["order"] == "liquidityNum"
    assert seen["params"]["ascending"] == "false"
    assert seen["params"]["closed"] == "false"
