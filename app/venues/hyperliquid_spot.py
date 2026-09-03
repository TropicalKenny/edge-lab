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
    """Parse the current Hyperliquid spot universe without positional corruption.

    Current mainnet responses may contain more asset-context rows than current spot
    markets. The current `spotMeta.universe` is therefore the source of truth: when
    contexts expose a `coin` identity, each listed market is matched only to a context
    whose identity exactly equals that market's metadata `name`. Extra context rows
    that are not current markets are ignored. Missing or duplicate contexts for a
    current market fail closed.

    Older response shapes without `coin` retain positional parsing, but only when the
    metadata and context arrays have identical lengths.
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

    context_identities = [
        str(ctx.get("coin", "")).strip() if isinstance(ctx, dict) else ""
        for ctx in contexts
    ]
    identified_count = sum(bool(identity) for identity in context_identities)

    aligned: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if identified_count:
        if identified_count != len(contexts):
            raise HyperliquidInfoError("mixed identified/unidentified spot contexts")

        contexts_by_identity: dict[str, dict[str, Any]] = {}
        duplicate_identities: set[str] = set()
        for ctx, identity in zip(contexts, context_identities, strict=True):
            if not isinstance(ctx, dict):
                raise HyperliquidInfoError("invalid identified spot context")
            if identity in contexts_by_identity:
                duplicate_identities.add(identity)
            else:
                contexts_by_identity[identity] = ctx

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
            if market_name in duplicate_identities:
                raise HyperliquidInfoError(f"duplicate spot context for current market: {market_name}")
            ctx = contexts_by_identity.get(market_name)
            if ctx is None:
                raise HyperliquidInfoError(f"missing spot context for current market: {market_name}")
            aligned.append((market, ctx))
    else:
        if len(universe) != len(contexts):
            raise HyperliquidInfoError("spot metadata/context length mismatch without context identities")
        for market, ctx in zip(universe, contexts, strict=True):
            if not isinstance(market, dict) or not isinstance(ctx, dict):
                raise HyperliquidInfoError("invalid positional spot metadata/context entry")
            aligned.append((market, ctx))

    out: list[SpotContext] = []
    for market, ctx in aligned:
        parsed = _spot_context(market, ctx, token_names, captured_at)
        if parsed is None:
            market_name = str(market.get("name", "<unknown>"))
            raise HyperliquidInfoError(f"failed to parse current spot market: {market_name}")
        out.append(parsed)
    return out
