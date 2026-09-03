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
    """Parse Hyperliquid spot contexts using the current market-index contract.

    Current `spotMetaAndAssetCtxs` responses may contain substantially more context
    rows than listed spot markets. `meta.universe` is the source of current markets,
    and each current market's explicit `index` selects its context row. Unreferenced
    context rows are ignored.

    A narrow compatibility path remains for older/test response shapes: if every
    context row is a mapping, none exposes a non-empty `coin` identity, and the two
    arrays have exactly equal length, positional parsing is allowed when explicit
    market indexes are absent or unusable. Current identified mainnet responses never
    use this fallback.

    The indexed path fails closed on missing/invalid/duplicate indexes, out-of-range
    context references, identity mismatches, incomplete token metadata, and unusable
    prices.
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

    markets: list[dict[str, Any]] = []
    market_names: list[str] = []
    parsed_indexes: list[int | None] = []
    seen_market_names: set[str] = set()

    for market in universe:
        if not isinstance(market, dict):
            raise HyperliquidInfoError("invalid current spot metadata entry")
        market_name = str(market.get("name", "")).strip()
        if not market_name:
            raise HyperliquidInfoError("current spot market is missing a name")
        if market_name in seen_market_names:
            raise HyperliquidInfoError(f"duplicate current spot market name: {market_name}")
        seen_market_names.add(market_name)
        markets.append(market)
        market_names.append(market_name)

        try:
            market_index = int(market["index"])
        except (KeyError, TypeError, ValueError):
            market_index = None
        parsed_indexes.append(market_index)

    all_contexts_plain = all(isinstance(ctx, dict) for ctx in contexts)
    any_context_identity = any(
        bool(str(ctx.get("coin", "")).strip())
        for ctx in contexts
        if isinstance(ctx, dict)
    )
    legacy_positional_shape = (
        len(markets) == len(contexts)
        and all_contexts_plain
        and not any_context_identity
    )

    indexed_usable = all(
        index is not None and index >= 0 and index < len(contexts)
        for index in parsed_indexes
    )

    aligned: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if legacy_positional_shape and not indexed_usable:
        aligned = list(zip(markets, contexts, strict=True))
    else:
        seen_market_indexes: set[int] = set()
        for market_name, market_index in zip(market_names, parsed_indexes, strict=True):
            if market_index is None or market_index < 0:
                raise HyperliquidInfoError(
                    f"invalid spot market index for current market: {market_name}"
                )
            if market_index in seen_market_indexes:
                raise HyperliquidInfoError(f"duplicate current spot market index: {market_index}")
            seen_market_indexes.add(market_index)
            if market_index >= len(contexts):
                raise HyperliquidInfoError(
                    f"spot context index out of range for current market: {market_name} ({market_index})"
                )

        for market, market_name, market_index in zip(
            markets, market_names, parsed_indexes, strict=True
        ):
            assert market_index is not None
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
