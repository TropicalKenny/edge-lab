from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from app.hyperliquid_forward import HyperliquidForwardError, ResolvedMarketState

ZERO = Decimal("0")


def _items(obj: Any):
    if isinstance(obj, dict):
        return obj.items()
    try:
        return vars(obj).items()
    except TypeError:
        return ()


def _string_values(obj: Any) -> list[str]:
    return [str(value).strip() for _, value in _items(obj) if isinstance(value, str) and value.strip()]


def _named(obj: Any, *names: str):
    for name in names:
        if isinstance(obj, dict):
            value = obj.get(name)
        else:
            value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _decimal(obj: Any, *names: str) -> Decimal | None:
    for name in names:
        value = _named(obj, name)
        if value in (None, ""):
            continue
        try:
            return Decimal(str(value))
        except (ArithmeticError, TypeError, ValueError):
            continue
    return None


def _norm(value: str) -> str:
    normalized = value.upper().strip()
    for suffix in ("/USDC", "-USDC", "_USDC"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _matches_symbol(obj: Any, symbol: str) -> bool:
    target = _norm(symbol)
    explicit = [
        _named(obj, "base_symbol"),
        _named(obj, "base"),
        _named(obj, "symbol"),
        _named(obj, "display_name"),
        _named(obj, "name"),
        _named(obj, "market"),
        _named(obj, "coin"),
        _named(obj, "pair"),
    ]
    values = [str(value) for value in explicit if value is not None] + _string_values(obj)
    return any(_norm(value) == target for value in values if not value.startswith("@"))


def _raw_book(obj: Any) -> str | None:
    for name in ("raw_name", "raw_market", "raw_coin", "market_id", "book_coin", "coin", "name"):
        value = _named(obj, name)
        if isinstance(value, str) and value.startswith("@"):
            return value
    return next((value for value in _string_values(obj) if value.startswith("@")), None)


def resolve_market_state_robust(
    perps: Iterable[Any],
    spots: Iterable[Any],
    *,
    coin: str,
    spot_symbol: str,
) -> ResolvedMarketState:
    coin = coin.upper()
    perp = next(
        (
            row
            for row in perps
            if str(_named(row, "coin", "symbol", "name") or "").upper() == coin
        ),
        None,
    )
    if perp is None:
        raise HyperliquidForwardError(f"missing Hyperliquid perp state for {coin}")
    perp_mark = _decimal(perp, "mark_price", "markPx", "mark")
    funding = _decimal(perp, "funding_rate", "funding")
    if perp_mark is None or perp_mark <= ZERO or funding is None:
        raise HyperliquidForwardError(f"incomplete Hyperliquid perp state for {coin}")

    candidates = [row for row in spots if _matches_symbol(row, spot_symbol)]
    if not candidates:
        raise HyperliquidForwardError(f"missing Hyperliquid spot state for {spot_symbol}")
    spot = candidates[0]
    spot_mark = _decimal(spot, "mid_price", "midPx", "mark_price", "markPx", "price")
    raw_book = _raw_book(spot)
    if spot_mark is None or spot_mark <= ZERO or raw_book is None:
        raise HyperliquidForwardError(f"incomplete/raw spot state for {spot_symbol}")
    return ResolvedMarketState(
        coin=coin,
        spot_book_coin=raw_book,
        spot_mark=spot_mark,
        perp_mark=perp_mark,
        funding_rate=funding,
    )
