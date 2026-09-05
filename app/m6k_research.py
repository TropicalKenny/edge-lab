from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Sequence

from app.venues.polymarket import EventContext, MarketContext, OrderBook, walk_buy

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")


@dataclass(frozen=True)
class HyperliquidPersistenceMetrics:
    observation_count: int
    positive_edge_count: int
    baseline_edge_count: int
    stress_positive_count: int
    positive_edge_fraction: Decimal
    baseline_edge_fraction: Decimal
    stress_positive_fraction: Decimal
    current_baseline_streak: int
    max_baseline_streak: int
    funding_sign_flips: int
    mean_funding_hourly: Decimal | None
    funding_stddev_hourly: Decimal | None
    mean_projected_edge_bps: Decimal | None
    min_projected_edge_bps: Decimal | None
    max_projected_edge_bps: Decimal | None


@dataclass(frozen=True)
class HyperliquidPersistenceScreen:
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PolymarketEventConsistencyObservation:
    event_id: str
    market_count: int
    quantity: Decimal
    gross_cost: Decimal
    total_fees: Decimal
    total_cost: Decimal
    payout: Decimal
    gap_usd: Decimal
    gap_bps: Decimal
    positive_violation: bool
    baseline_edge_qualified: bool


def _fraction(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return ZERO
    return Decimal(numerator) / Decimal(denominator)


def hyperliquid_persistence_metrics(
    funding_rates: Sequence[Decimal] | Iterable[Decimal],
    *,
    horizon_hours: int,
    estimated_cost_bps: Decimal,
    baseline_edge_bps: Decimal = Decimal("10"),
    stress_cost_multiplier: Decimal = Decimal("2"),
) -> HyperliquidPersistenceMetrics:
    """Summarize historical funding persistence without creating trading evidence.

    Each funding observation is projected across the proposed holding horizon only as a
    counterfactual screen. The result is research telemetry, not a claim that the future
    funding rate will persist for that horizon.
    """

    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    if estimated_cost_bps < ZERO:
        raise ValueError("estimated_cost_bps cannot be negative")
    if baseline_edge_bps < ZERO:
        raise ValueError("baseline_edge_bps cannot be negative")
    if stress_cost_multiplier < ONE:
        raise ValueError("stress_cost_multiplier must be >= 1")

    rates = [Decimal(value) for value in funding_rates]
    edges = [rate * Decimal(horizon_hours) * BPS - estimated_cost_bps for rate in rates]
    stressed = [
        rate * Decimal(horizon_hours) * BPS - estimated_cost_bps * stress_cost_multiplier
        for rate in rates
    ]

    positive_count = sum(edge > ZERO for edge in edges)
    baseline_count = sum(edge >= baseline_edge_bps for edge in edges)
    stress_positive_count = sum(edge > ZERO for edge in stressed)

    current_streak = 0
    for edge in reversed(edges):
        if edge < baseline_edge_bps:
            break
        current_streak += 1

    max_streak = streak = 0
    for edge in edges:
        if edge >= baseline_edge_bps:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    signs = [1 if rate > ZERO else -1 if rate < ZERO else 0 for rate in rates]
    nonzero_signs = [value for value in signs if value]
    sign_flips = sum(a != b for a, b in zip(nonzero_signs, nonzero_signs[1:]))

    mean_rate = None
    stddev = None
    mean_edge = min_edge = max_edge = None
    if rates:
        mean_rate = sum(rates, ZERO) / Decimal(len(rates))
        variance = sum((rate - mean_rate) ** 2 for rate in rates) / Decimal(len(rates))
        stddev = variance.sqrt()
        mean_edge = sum(edges, ZERO) / Decimal(len(edges))
        min_edge = min(edges)
        max_edge = max(edges)

    count = len(rates)
    return HyperliquidPersistenceMetrics(
        observation_count=count,
        positive_edge_count=positive_count,
        baseline_edge_count=baseline_count,
        stress_positive_count=stress_positive_count,
        positive_edge_fraction=_fraction(positive_count, count),
        baseline_edge_fraction=_fraction(baseline_count, count),
        stress_positive_fraction=_fraction(stress_positive_count, count),
        current_baseline_streak=current_streak,
        max_baseline_streak=max_streak,
        funding_sign_flips=sign_flips,
        mean_funding_hourly=mean_rate,
        funding_stddev_hourly=stddev,
        mean_projected_edge_bps=mean_edge,
        min_projected_edge_bps=min_edge,
        max_projected_edge_bps=max_edge,
    )


def evaluate_hyperliquid_persistence_screen(
    metrics: HyperliquidPersistenceMetrics,
    *,
    min_observations: int = 168,
    min_positive_fraction: Decimal = Decimal("0.70"),
    min_baseline_fraction: Decimal = Decimal("0.50"),
    min_stress_positive_fraction: Decimal = Decimal("0.50"),
    min_current_baseline_streak: int = 24,
) -> HyperliquidPersistenceScreen:
    """Apply preregistered M6K-HL research-screen thresholds.

    Passing this screen means only that a coin/horizon pair is worth a *new, separately
    registered* forward hypothesis. It never promotes the frozen M6C study.
    """

    reasons: list[str] = []
    if metrics.observation_count < min_observations:
        reasons.append("INSUFFICIENT_PERSISTENCE_OBSERVATIONS")
    if metrics.positive_edge_fraction < min_positive_fraction:
        reasons.append("POSITIVE_EDGE_FRACTION_BELOW_SCREEN")
    if metrics.baseline_edge_fraction < min_baseline_fraction:
        reasons.append("BASELINE_EDGE_FRACTION_BELOW_SCREEN")
    if metrics.stress_positive_fraction < min_stress_positive_fraction:
        reasons.append("COST_STRESS_FRACTION_BELOW_SCREEN")
    if metrics.current_baseline_streak < min_current_baseline_streak:
        reasons.append("CURRENT_BASELINE_STREAK_BELOW_SCREEN")
    return HyperliquidPersistenceScreen(passed=not reasons, reasons=tuple(reasons))


def _candidate_quantities(books: Iterable[OrderBook], max_shares: Decimal) -> list[Decimal]:
    books = list(books)
    if not books or max_shares <= ZERO or any(not book.asks for book in books):
        return []
    max_common = min(sum((level.size for level in book.asks), ZERO) for book in books)
    max_common = min(max_common, max_shares)
    minimum = max(book.min_order_size for book in books)
    if max_common < minimum:
        return []
    candidates = {minimum, max_common}
    for book in books:
        cumulative = ZERO
        for level in book.asks:
            cumulative += level.size
            clipped = min(cumulative, max_common)
            if clipped >= minimum:
                candidates.add(clipped)
            if cumulative >= max_common:
                break
    return sorted(value for value in candidates if minimum <= value <= max_common)


def polymarket_negrisk_yes_consistency(
    event: EventContext,
    books: dict[str, OrderBook],
    *,
    now: datetime,
    max_shares: Decimal,
    max_book_age_seconds: int,
    fee_buffer_pct: Decimal,
    baseline_edge_bps: Decimal = Decimal("10"),
) -> tuple[PolymarketEventConsistencyObservation | None, tuple[str, ...]]:
    """Measure the executable YES-complete-set gap for a standard NegRisk event.

    A standard, complete NegRisk event represents mutually exclusive/exhaustive outcomes,
    so one YES share across every outcome has a deterministic total payout of one unit at
    resolution. This helper measures the current executable ask-side cost of that invariant
    even when the gap is negative. It never uses resolved outcomes or submits an order.
    """

    if not event.neg_risk:
        return None, ("NOT_NEG_RISK",)
    if event.neg_risk_augmented:
        return None, ("AUGMENTED_NEG_RISK_DEFERRED",)
    if len(event.markets) < 3 or any(not market.is_tradeable_binary for market in event.markets):
        return None, ("INCOMPLETE_NEG_RISK_EVENT",)
    markets = list(event.markets)
    if any(
        market.neg_risk_other
        or (market.group_item_title and market.group_item_title.strip().lower() == "other")
        for market in markets
    ):
        return None, ("DYNAMIC_OTHER_OUTCOME",)
    if any(market.fee_schedule is None for market in markets):
        return None, ("UNKNOWN_FEE_SCHEDULE",)

    legs: list[tuple[MarketContext, OrderBook]] = []
    for market in markets:
        book = books.get(market.yes_token_id or "")
        if book is None:
            return None, ("MISSING_BOOK",)
        age = (now - book.timestamp).total_seconds()
        if age < -1 or age > max_book_age_seconds:
            return None, ("STALE_BOOK",)
        if not book.asks:
            return None, ("NO_ASK_LIQUIDITY",)
        legs.append((market, book))

    best: PolymarketEventConsistencyObservation | None = None
    for quantity in _candidate_quantities((book for _, book in legs), max_shares):
        executions = []
        for market, book in legs:
            execution = walk_buy(
                market=market,
                book=book,
                outcome="Yes",
                quantity=quantity,
                fee_buffer_pct=fee_buffer_pct,
            )
            if execution is None:
                executions = []
                break
            executions.append(execution)
        if not executions:
            continue
        gross = sum((row.notional for row in executions), ZERO)
        fees = sum((row.fee for row in executions), ZERO)
        total = gross + fees
        payout = quantity
        gap = payout - total
        gap_bps = (gap / total) * BPS if total > ZERO else ZERO
        candidate = PolymarketEventConsistencyObservation(
            event_id=event.event_id,
            market_count=len(markets),
            quantity=quantity,
            gross_cost=gross,
            total_fees=fees,
            total_cost=total,
            payout=payout,
            gap_usd=gap,
            gap_bps=gap_bps,
            positive_violation=gap > ZERO,
            baseline_edge_qualified=gap_bps >= baseline_edge_bps,
        )
        if best is None or candidate.gap_bps > best.gap_bps:
            best = candidate
    return (best, ()) if best is not None else (None, ("NO_COMMON_EXECUTABLE_DEPTH",))


def solana_unknown_group(reasons: Iterable[str]) -> str:
    """Collapse UNKNOWN reason detail into one preregistered analysis bucket."""

    reason_set = {str(reason).strip().upper() for reason in reasons if str(reason).strip()}
    groups: list[str] = []

    if any("CREATOR" in reason and "UNKNOWN" in reason for reason in reason_set):
        groups.append("creator_security_unknown")
    if "TRANSFER_FEE_UNKNOWN" in reason_set:
        groups.append("transfer_fee_unknown")
    if "SECURITY_SNAPSHOT_MISSING" in reason_set:
        groups.append("security_snapshot_missing")
    if "ASSET_METADATA_MISSING" in reason_set:
        groups.append("asset_metadata_missing")
    if any(
        reason in reason_set
        for reason in {
            "MINT_AUTHORITY_UNKNOWN",
            "FREEZE_AUTHORITY_UNKNOWN",
            "SECURITY_MINT_AUTHORITY_UNKNOWN",
            "SECURITY_FREEZE_AUTHORITY_UNKNOWN",
        }
    ):
        groups.append("mint_freeze_authority_unknown")
    if "NON_TRANSFERABLE_UNKNOWN" in reason_set:
        groups.append("non_transferable_unknown")

    groups = list(dict.fromkeys(groups))
    if not groups:
        return "other_unknown"
    if len(groups) == 1:
        return groups[0]
    return "multiple_unknown_reasons"
