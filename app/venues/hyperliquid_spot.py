from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.venues.hyperliquid import HyperliquidInfoError, SpotContext, ZERO, _d


def _spot_context(
    market: dict[str, Any],
    ctx: dict[str, Any],
    token_names: dict[int, str],
    captured_at: datetime,
) -> SpotContext | None:
    book_coin = str(market.get("name", ""))
    token_ids = market.get("tokens", [])
    if not book_coin or not isinstance(token_ids, list) or len(token_ids) != 2:
        return None
    try:
        base = token_names.get(int(token_ids[0]))
        quote = token_names.get(int(token_ids[1]))
    except (TypeError, ValueError):
        return None
    if not base or not quote:
        return None
    mid = _d(ctx.get("midPx"), None) or _d(ctx.get("markPx"), None)
    if mid is None:
        return None
    return SpotContext(
        pair=f"{base}/{quote}",
        book_coin=book_coin,
        base=base,
        quote=quote,
        mid_px=mid,
        day_ntl_volume=_d(ctx.get("dayNtlVlm")) or ZERO,
        captured_at=captured_at,
    )


def parse_spot_contexts(payload: Any, *, captured_at: datetime | None = None) -> list[SpotContext]:
    """Parse Hyperliquid spot contexts using the market index contract.

    `spotMetaAndAssetCtxs` may return substantially more context rows than currently
    listed spot markets. Current market metadata is the source of truth. Each market's
    explicit `index` selects its corresponding row in the context array. Context rows
    not referenced by the current universe are ignored.

    For every current market we still fail closed when the market index is missing,
    duplicated, negative or out of range; the referenced row is not a mapping; a
    non-empty `coin` identity disagrees with the market metadata name; token metadata
    is incomplete; or the referenced context has no usable price.
    """

    captured_at = captured_at or datetime.now(timezone.utc)
    if not isinstance(payload, list) or len(payload) != 2:
        raise HyperliquidInfoError("unexpected spotMetaAndAssetCtxs response shape")
    meta, contexts = payload
    if not isinstance(meta, dict) or not isinstance(contexts, list):
        raise HyperliquidInfoError("unexpected spotMetaAndAssetCtxs response shape")

    universe = meta.get("universe", [])
    tokens = meta.get("tokens", [])
    if not isinstance(universe, list) or not isinstance(tokens, list):
        raise HyperliquidInfoError("unexpected spot metadata shape")

    token_names: dict[int, str] = {}
    for token in tokens:
        if not isinstance(token, dict) or "index" not in token or "name" not in token:
            continue
        try:
            token_names[int(token["index"])] = str(token["name"])
        except (TypeError, ValueError):
            continue

    aligned: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_market_names: set[str] = set()
    seen_market_indexes: set[int] = set()

    for market in universe:
        if not isinstance(market, dict):
            raise HyperliquidInfoError("invalid current spot metadata entry")

        market_name = str(market.get("name", "")).strip()
        if not market_name:
            raise HyperliquidInfoError("current spot market is missing a name")
        if market_name in seen_market_names:
            raise HyperliquidInfoError(f"duplicate current spot market name: {market_name}")
        seen_market_names.add(market_name)

        try:
            market_index = int(market["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HyperliquidInfoError(f"invalid spot market index for current market: {market_name}") from exc
        if market_index < 0:
            raise HyperliquidInfoError(f"invalid spot market index for current market: {market_name}")
        if market_index in seen_market_indexes:
            raise HyperliquidInfoError(f"duplicate current spot market index: {market_index}")
        seen_market_indexes.add(market_index)
        if market_index >= len(contexts):
            raise HyperliquidInfoError(
                f"spot context index out of range for current market: {market_name} ({market_index})"
            )

        ctx = contexts[market_index]
        if not isinstance(ctx, dict):
            raise HyperliquidInfoError(f"invalid spot context for current market: {market_name}")

        context_identity = str(ctx.get("coin", "")).strip()
        if context_identity and context_identity != market_name:
            raise HyperliquidInfoError(
                f"spot context identity mismatch for current market: {market_name} != {context_identity}"
            )

        aligned.append((market, ctx))

    out: list[SpotContext] = []
    for market, ctx in aligned:
        parsed = _spot_context(market, ctx, token_names, captured_at)
        if parsed is None:
            market_name = str(market.get("name", "<unknown>"))
            raise HyperliquidInfoError(f"failed to parse current spot market: {market_name}")
        out.append(parsed)
    return out
