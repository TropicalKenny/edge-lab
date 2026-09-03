from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.venues.hyperliquid import HyperliquidInfoError, SpotContext, ZERO, _d


def _spot_context(market: dict[str, Any], ctx: dict[str, Any], token_names: dict[int, str], captured_at: datetime) -> SpotContext | None:
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
    """Parse spot contexts without assuming metadata and live contexts have equal length.

    Hyperliquid's current typed SDK exposes a `coin` identity on each spot context.
    When present, that identity is authoritative and lets inactive metadata entries be
    omitted from the context array without corrupting market alignment. Older response
    shapes without `coin` retain the positional path, but only when lengths match.
    Ambiguous, mixed, duplicate, or unknown identity mappings fail closed.
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

    markets_by_identity: dict[str, dict[str, Any]] = {}
    ambiguous_identities: set[str] = set()
    for market in universe:
        if not isinstance(market, dict):
            continue
        book_coin = str(market.get("name", ""))
        if not book_coin:
            continue
        identities = {book_coin}
        token_ids = market.get("tokens", [])
        if isinstance(token_ids, list) and len(token_ids) == 2:
            try:
                base = token_names.get(int(token_ids[0]))
                quote = token_names.get(int(token_ids[1]))
            except (TypeError, ValueError):
                base = quote = None
            if base and quote:
                identities.add(f"{base}/{quote}")
        for identity in identities:
            existing = markets_by_identity.get(identity)
            if existing is not None and existing is not market:
                ambiguous_identities.add(identity)
            else:
                markets_by_identity[identity] = market

    context_identities = [
        str(ctx.get("coin", "")).strip() if isinstance(ctx, dict) else ""
        for ctx in contexts
    ]
    identified_count = sum(bool(identity) for identity in context_identities)

    aligned: list[tuple[dict[str, Any], dict[str, Any]]]
    if identified_count:
        if identified_count != len(contexts):
            raise HyperliquidInfoError("mixed identified/unidentified spot contexts")
        aligned = []
        seen_markets: set[str] = set()
        for ctx, identity in zip(contexts, context_identities, strict=True):
            if not isinstance(ctx, dict):
                raise HyperliquidInfoError("invalid identified spot context")
            if identity in ambiguous_identities:
                raise HyperliquidInfoError(f"ambiguous spot context identity: {identity}")
            market = markets_by_identity.get(identity)
            if market is None:
                raise HyperliquidInfoError(f"unknown spot context identity: {identity}")
            book_coin = str(market.get("name", ""))
            if book_coin in seen_markets:
                raise HyperliquidInfoError(f"duplicate spot context identity: {identity}")
            seen_markets.add(book_coin)
            aligned.append((market, ctx))
    else:
        if len(universe) != len(contexts):
            raise HyperliquidInfoError("spot metadata/context length mismatch without context identities")
        aligned = []
        for market, ctx in zip(universe, contexts, strict=True):
            if not isinstance(market, dict) or not isinstance(ctx, dict):
                raise HyperliquidInfoError("invalid positional spot metadata/context entry")
            aligned.append((market, ctx))

    out: list[SpotContext] = []
    for market, ctx in aligned:
        parsed = _spot_context(market, ctx, token_names, captured_at)
        if parsed is not None:
            out.append(parsed)
    return out
