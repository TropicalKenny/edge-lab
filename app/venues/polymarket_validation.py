from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.venues.polymarket import FeeSchedule, MarketContext, PolymarketPublicError


def apply_clob_market_info(market: MarketContext, info: dict[str, Any]) -> MarketContext:
    tokens = info.get("t")
    if not isinstance(tokens, list) or len(tokens) != 2:
        raise PolymarketPublicError("CLOB market info does not contain exactly two outcome tokens")
    mapped: dict[str, str] = {}
    for token in tokens:
        if not isinstance(token, dict) or token.get("t") is None or token.get("o") is None:
            raise PolymarketPublicError("CLOB token metadata is incomplete")
        mapped[str(token["o"]).strip().lower()] = str(token["t"])
    if "yes" not in mapped or "no" not in mapped:
        raise PolymarketPublicError("CLOB market does not expose Yes/No tokens")

    fee = info.get("fd")
    if not isinstance(fee, dict):
        raise PolymarketPublicError("CLOB market fee details are missing")
    try:
        rate = Decimal(str(fee.get("r")))
        exponent_decimal = Decimal(str(fee.get("e")))
    except Exception as exc:
        raise PolymarketPublicError("CLOB fee details are invalid") from exc
    if rate < 0 or rate > 1:
        raise PolymarketPublicError("CLOB fee rate is outside expected range")
    if exponent_decimal != exponent_decimal.to_integral_value() or exponent_decimal < 0 or exponent_decimal > 8:
        raise PolymarketPublicError("CLOB fee exponent is invalid")
    schedule = FeeSchedule(
        rate=rate,
        exponent=int(exponent_decimal),
        taker_only=bool(fee.get("to", True)),
        rebate_rate=market.fee_schedule.rebate_rate if market.fee_schedule else Decimal("0"),
    )

    gamma_tokens = {market.yes_token_id, market.no_token_id}
    clob_tokens = {mapped["yes"], mapped["no"]}
    if None not in gamma_tokens and gamma_tokens != clob_tokens:
        raise PolymarketPublicError("Gamma/CLOB token IDs disagree")
    if market.fee_schedule is not None:
        if market.fee_schedule.rate != schedule.rate or market.fee_schedule.exponent != schedule.exponent:
            raise PolymarketPublicError("Gamma/CLOB fee schedules disagree")
    if "nr" in info and bool(info["nr"]) != market.neg_risk:
        raise PolymarketPublicError("Gamma/CLOB NegRisk flags disagree")

    return replace(
        market,
        yes_token_id=mapped["yes"],
        no_token_id=mapped["no"],
        fees_enabled=rate > 0,
        fee_schedule=schedule,
    )
