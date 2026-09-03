from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from app.venues.polymarket import OrderBook, PriceLevel
from app.venues.solana import JupiterShadowQuote
from app.venues.solana_models import SolanaForensicFeatureSnapshot, SolanaSecuritySnapshot

ZERO = Decimal("0")
ONE = Decimal("1")

SolanaResearchState = Literal["SAFE", "UNKNOWN", "UNSAFE"]


@dataclass(frozen=True)
class SolanaResearchClassification:
    state: SolanaResearchState
    reasons: tuple[str, ...]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def parse_csv_ints(value: str, *, minimum: int = 1, maximum: int | None = None) -> tuple[int, ...]:
    parsed: list[int] = []
    for raw in str(value).split(","):
        raw = raw.strip()
        if not raw:
            continue
        number = int(raw)
        if number < minimum or (maximum is not None and number > maximum):
            raise ValueError(f"integer {number} is outside the allowed research range")
        if number not in parsed:
            parsed.append(number)
    if not parsed:
        raise ValueError("at least one integer value is required")
    return tuple(parsed)


def parse_csv_symbols(value: str) -> tuple[str, ...]:
    symbols: list[str] = []
    for raw in str(value).split(","):
        symbol = raw.strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if not symbols:
        raise ValueError("at least one symbol is required")
    return tuple(symbols)


def classify_solana_candidate(
    feature: SolanaForensicFeatureSnapshot,
    security: SolanaSecuritySnapshot | None,
) -> SolanaResearchClassification:
    """Tri-state security classification for observation-only M6J research.

    UNKNOWN is deliberately distinct from UNSAFE. The baseline remains unchanged and
    still requires explicit clean values. M6J uses UNKNOWN only to decide whether a
    counterfactual quote should be observed; it never enables execution.
    """

    unsafe: list[str] = []
    unknown: list[str] = []

    if feature.mintable is True:
        unsafe.append("MINT_AUTHORITY_ACTIVE")
    elif feature.mintable is None:
        unknown.append("MINT_AUTHORITY_UNKNOWN")

    if feature.freezable is True:
        unsafe.append("FREEZE_AUTHORITY_ACTIVE")
    elif feature.freezable is None:
        unknown.append("FREEZE_AUTHORITY_UNKNOWN")

    if feature.malicious_creator is True:
        unsafe.append("CREATOR_FLAGGED_MALICIOUS")
    elif feature.malicious_creator is None:
        unknown.append("CREATOR_SECURITY_UNKNOWN")

    if feature.transfer_fee_rate is None:
        unknown.append("TRANSFER_FEE_UNKNOWN")
    elif Decimal(feature.transfer_fee_rate) != ZERO:
        unsafe.append("TRANSFER_FEE_NONZERO")

    try:
        missing = json.loads(feature.missing_fields_json)
    except (json.JSONDecodeError, TypeError):
        missing = ["invalid_missing_fields_json"]
    if not isinstance(missing, list):
        missing = ["invalid_missing_fields_json"]
    security_relevant_missing = {"security_snapshot", "asset_metadata"}
    for item in sorted(security_relevant_missing.intersection(str(value) for value in missing)):
        unknown.append(f"{item.upper()}_MISSING")

    if security is None:
        unknown.append("SECURITY_SNAPSHOT_MISSING")
    else:
        if security.non_transferable is True:
            unsafe.append("NON_TRANSFERABLE_TOKEN")
        elif security.non_transferable is None:
            unknown.append("NON_TRANSFERABLE_UNKNOWN")

        if security.mintable is True:
            unsafe.append("SECURITY_MINT_AUTHORITY_ACTIVE")
        elif security.mintable is None:
            unknown.append("SECURITY_MINT_AUTHORITY_UNKNOWN")

        if security.freezable is True:
            unsafe.append("SECURITY_FREEZE_AUTHORITY_ACTIVE")
        elif security.freezable is None:
            unknown.append("SECURITY_FREEZE_AUTHORITY_UNKNOWN")

        if security.malicious_creator is True:
            unsafe.append("SECURITY_CREATOR_FLAGGED_MALICIOUS")
        elif security.malicious_creator is None:
            unknown.append("SECURITY_CREATOR_UNKNOWN")

    if unsafe:
        return SolanaResearchClassification("UNSAFE", tuple(dict.fromkeys(unsafe + unknown)))
    if unknown:
        return SolanaResearchClassification("UNKNOWN", tuple(dict.fromkeys(unknown)))
    return SolanaResearchClassification("SAFE", ("EXPLICIT_SECURITY_CHECKS_CLEAN",))


def compact_jupiter_quote(quote: JupiterShadowQuote | None) -> dict[str, Any] | None:
    """Return bounded quote telemetry only; never expose or preserve transaction material."""

    if quote is None:
        return None
    return {
        "input_mint": quote.input_mint,
        "output_mint": quote.output_mint,
        "in_amount": quote.in_amount,
        "out_amount": quote.out_amount,
        "in_usd_value": str(quote.in_usd_value) if quote.in_usd_value is not None else None,
        "out_usd_value": str(quote.out_usd_value) if quote.out_usd_value is not None else None,
        "price_impact_pct": str(quote.price_impact_pct) if quote.price_impact_pct is not None else None,
        "captured_at": _aware(quote.captured_at).isoformat(),
        "transaction_present": bool(quote.transaction_present),
    }


def _price_levels(rows: Any, *, reverse: bool) -> tuple[PriceLevel, ...]:
    parsed: list[PriceLevel] = []
    if not isinstance(rows, list):
        return ()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            price = Decimal(str(row.get("price")))
            size = Decimal(str(row.get("size")))
        except (ValueError, TypeError, ArithmeticError):
            continue
        if price <= ZERO or price >= ONE or size <= ZERO:
            continue
        parsed.append(PriceLevel(price=price, size=size))
    return tuple(sorted(parsed, key=lambda level: level.price, reverse=reverse))


def polymarket_book_from_ws(
    seed: OrderBook,
    payload: dict[str, Any],
    *,
    captured_at: datetime | None = None,
) -> OrderBook:
    """Convert a public Polymarket market-channel book event into an OrderBook.

    The websocket event omits static min-order/tick metadata, so those values are
    inherited from the REST seed book validated before the subscription starts.
    """

    if payload.get("event_type") != "book":
        raise ValueError("Polymarket websocket payload is not a book event")
    asset_id = str(payload.get("asset_id") or "")
    if asset_id != seed.token_id:
        raise ValueError("Polymarket websocket asset does not match seed book")
    market = str(payload.get("market") or "")
    if market and market != seed.condition_id:
        raise ValueError("Polymarket websocket condition does not match seed book")
    try:
        raw_timestamp = int(str(payload.get("timestamp") or "0"))
    except ValueError as exc:
        raise ValueError("Polymarket websocket book timestamp is invalid") from exc
    if raw_timestamp <= 0:
        raise ValueError("Polymarket websocket book timestamp is missing")
    timestamp_seconds = raw_timestamp / 1000 if raw_timestamp > 10_000_000_000 else raw_timestamp
    timestamp = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
    return OrderBook(
        condition_id=seed.condition_id,
        token_id=seed.token_id,
        bids=_price_levels(payload.get("bids"), reverse=True),
        asks=_price_levels(payload.get("asks"), reverse=False),
        min_order_size=seed.min_order_size,
        tick_size=seed.tick_size,
        neg_risk=seed.neg_risk,
        last_trade_price=seed.last_trade_price,
        book_hash=str(payload.get("hash")) if payload.get("hash") else seed.book_hash,
        timestamp=timestamp,
        captured_at=_aware(captured_at or datetime.now(timezone.utc)),
    )
