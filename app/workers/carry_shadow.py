"""Public-info-only M6O worker; no wallet, account or exchange endpoint."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.carry_shadow import HOUR, advance, database, finite, save_funding
from app.venues.hyperliquid import HyperliquidInfoClient, parse_perp_contexts
from app.workers.trend_research import write_summary


def resolve(perp_payload, spot_payload, captured_ms):
    perps = parse_perp_contexts(perp_payload)
    perp = next(p for p in perps if p.coin == "BTC")
    meta = spot_payload[0]
    tokens = {int(t["index"]): t for t in meta["tokens"]}
    matches = [
        m
        for m in meta["universe"]
        if tokens[m["tokens"][0]]["name"] == "UBTC" and tokens[m["tokens"][1]]["name"] == "USDC"
    ]
    if len(matches) != 1:
        raise ValueError("expected exactly one UBTC/USDC spot market")
    market = matches[0]
    base, quote = (tokens[i] for i in market["tokens"])
    return {
        "spot_coin": market["name"],
        "oracle": finite(perp.oracle_px, True),
        "captured_ms": captured_ms,
        "quantity_decimals": min(perp.sz_decimals, int(base["szDecimals"])),
        "identity": {
            "perp": "BTC",
            "spot_book": market["name"],
            "market_index": market["index"],
            "base": {k: base[k] for k in ("name", "index", "tokenId")},
            "quote": {k: quote[k] for k in ("name", "index", "tokenId")},
        },
    }


async def refresh_funding(db, client, now):
    latest = db.execute("SELECT max(time) FROM funding").fetchone()[0]
    cursor = max(now - 722 * HOUR, latest - HOUR if latest else 0)
    for _ in range(5):
        rows = await client.funding_history("BTC", cursor, now)
        if not isinstance(rows, list):
            raise TypeError("invalid funding payload")
        if any(int(r["time"]) > now or int(r["time"]) < cursor for r in rows):
            raise ValueError("funding outside requested interval")
        save_funding(db, rows)
        if len(rows) < 500:
            return
        next_cursor = max(int(r["time"]) for r in rows) + 1
        if next_cursor <= cursor:
            raise ValueError("funding pagination failed to advance")
        cursor = next_cursor
    raise ValueError("funding pagination limit")


async def cycle(db, client):
    # Funding acquisition can be slower than the quote capture. Do it first.
    now = int(datetime.now(UTC).timestamp() * 1000)
    await refresh_funding(db, client, now)
    perp, spot = await asyncio.gather(
        client.meta_and_asset_contexts(), client.spot_meta_and_asset_contexts()
    )
    market = resolve(perp, spot, int(datetime.now(UTC).timestamp() * 1000))
    spot_book, perp_book = await asyncio.gather(
        client.l2_book(market["spot_coin"]), client.l2_book("BTC")
    )
    captured = datetime.now(UTC)
    result = advance(db, int(captured.timestamp() * 1000), market, spot_book, perp_book)
    result.update(checked_at=captured.isoformat(), status="running", identity=market["identity"])
    return result


async def run():
    if os.environ.get("SIGNER_ENABLED", "false").lower() != "false":
        raise RuntimeError("signing must remain disabled")
    root = Path(os.environ.get("CARRY_RESEARCH_DIR", "/data/carry"))
    root.mkdir(parents=True, exist_ok=True)
    db = database(root / "research.sqlite3")
    async with HyperliquidInfoClient(network="mainnet", timeout_seconds=10) as client:
        while True:
            try:
                result = await cycle(db, client)
            except Exception as exc:  # noqa: BLE001 - daemon records failure without fabricating NAV
                result = {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "status": "blocked",
                    "error": str(exc)[:250],
                    "can_trade_live": False,
                }
            write_summary(root / "summary.json", result)
            print(json.dumps(result, sort_keys=True), flush=True)
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(run())
