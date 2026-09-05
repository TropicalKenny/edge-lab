from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from app.m6k_research import (
    evaluate_hyperliquid_persistence_screen,
    hyperliquid_persistence_metrics,
    polymarket_negrisk_yes_consistency,
    solana_unknown_group,
)
from app.venues.polymarket import EventContext, FeeSchedule, MarketContext, OrderBook, PriceLevel

NOW = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)
D = Decimal


def test_hyperliquid_persistence_screen_uses_realized_rolling_funding_windows():
    rates = [D("0.0001")] * 200
    metrics = hyperliquid_persistence_metrics(
        rates,
        horizon_hours=24,
        estimated_cost_bps=D("10"),
        baseline_edge_bps=D("10"),
        stress_cost_multiplier=D("2"),
    )
    screen = evaluate_hyperliquid_persistence_screen(metrics)

    assert metrics.funding_point_count == 200
    assert metrics.observation_count == 177
    assert metrics.mean_window_edge_bps == D("14.0000")
    assert metrics.positive_edge_fraction == D("1")
    assert metrics.baseline_edge_fraction == D("1")
    assert metrics.stress_positive_fraction == D("1")
    assert metrics.current_baseline_streak == 177
    assert metrics.funding_sign_flips == 0
    assert screen.passed is True
    assert screen.reasons == ()


def test_hyperliquid_persistence_screen_rejects_current_spike_without_history():
    rates = [D("-0.00005")] * 20 + [D("0.0002")] * 10
    metrics = hyperliquid_persistence_metrics(
        rates,
        horizon_hours=24,
        estimated_cost_bps=D("10"),
    )
    screen = evaluate_hyperliquid_persistence_screen(metrics)

    assert metrics.funding_point_count == 30
    assert metrics.observation_count == 7
    assert metrics.funding_sign_flips == 1
    assert screen.passed is False
    assert "INSUFFICIENT_PERSISTENCE_OBSERVATIONS" in screen.reasons
    assert "CURRENT_BASELINE_STREAK_BELOW_SCREEN" in screen.reasons


def _market(index: int, *, other: bool = False) -> MarketContext:
    return MarketContext(
        market_id=f"market-{index}",
        condition_id=f"condition-{index}",
        question=f"Outcome {index}?",
        slug=f"outcome-{index}",
        event_id="event-1",
        event_slug="event-1",
        event_title="Complete event",
        yes_token_id=f"yes-{index}",
        no_token_id=f"no-{index}",
        outcome_labels=("Yes", "No"),
        active=True,
        closed=False,
        accepting_orders=True,
        enable_order_book=True,
        neg_risk=True,
        neg_risk_other=other,
        fees_enabled=False,
        fee_schedule=FeeSchedule(rate=D("0"), exponent=1, taker_only=True),
        resolution_source="official",
        description="Exactly one outcome wins.",
        group_item_title="Other" if other else f"Outcome {index}",
        end_date=None,
        captured_at=NOW,
    )


def _event(*markets: MarketContext) -> EventContext:
    return EventContext(
        event_id="event-1",
        title="Complete event",
        slug="event-1",
        description="Exactly one outcome wins.",
        resolution_source="official",
        neg_risk=True,
        neg_risk_augmented=False,
        markets=tuple(markets),
        captured_at=NOW,
    )


def _book(index: int, ask: str) -> OrderBook:
    return OrderBook(
        condition_id=f"condition-{index}",
        token_id=f"yes-{index}",
        bids=(PriceLevel(D("0.20"), D("100")),),
        asks=(PriceLevel(D(ask), D("100")),),
        min_order_size=D("5"),
        tick_size=D("0.01"),
        neg_risk=True,
        last_trade_price=None,
        book_hash=f"hash-{index}-{ask}",
        timestamp=NOW,
        captured_at=NOW,
    )


def test_polymarket_event_consistency_records_positive_and_negative_gaps():
    event = _event(*(_market(index) for index in range(3)))
    positive, reasons = polymarket_negrisk_yes_consistency(
        event,
        {f"yes-{index}": _book(index, "0.30") for index in range(3)},
        now=NOW,
        max_shares=D("100"),
        max_book_age_seconds=5,
        fee_buffer_pct=D("2"),
    )
    negative, negative_reasons = polymarket_negrisk_yes_consistency(
        event,
        {f"yes-{index}": _book(index, "0.34") for index in range(3)},
        now=NOW,
        max_shares=D("100"),
        max_book_age_seconds=5,
        fee_buffer_pct=D("2"),
    )

    assert reasons == ()
    assert positive is not None
    assert positive.positive_violation is True
    assert positive.baseline_edge_qualified is True
    assert positive.gap_usd > 0

    assert negative_reasons == ()
    assert negative is not None
    assert negative.positive_violation is False
    assert negative.gap_usd < 0


def test_polymarket_event_consistency_fails_closed_on_dynamic_or_incomplete_event():
    dynamic = _event(_market(0, other=True), _market(1), _market(2))
    observation, reasons = polymarket_negrisk_yes_consistency(
        dynamic,
        {f"yes-{index}": _book(index, "0.30") for index in range(3)},
        now=NOW,
        max_shares=D("100"),
        max_book_age_seconds=5,
        fee_buffer_pct=D("2"),
    )
    assert observation is None
    assert reasons == ("DYNAMIC_OTHER_OUTCOME",)

    inactive = replace(_market(2), accepting_orders=False)
    incomplete = _event(_market(0), _market(1), inactive)
    observation, reasons = polymarket_negrisk_yes_consistency(
        incomplete,
        {f"yes-{index}": _book(index, "0.30") for index in range(3)},
        now=NOW,
        max_shares=D("100"),
        max_book_age_seconds=5,
        fee_buffer_pct=D("2"),
    )
    assert observation is None
    assert reasons == ("INCOMPLETE_NEG_RISK_EVENT",)


def test_solana_unknown_group_is_preregistered_and_non_promotional():
    assert solana_unknown_group(["CREATOR_SECURITY_UNKNOWN"]) == "creator_security_unknown"
    assert solana_unknown_group(["TRANSFER_FEE_UNKNOWN"]) == "transfer_fee_unknown"
    assert solana_unknown_group(["SECURITY_SNAPSHOT_MISSING"]) == "security_snapshot_missing"
    assert solana_unknown_group(["ASSET_METADATA_MISSING"]) == "asset_metadata_missing"
    assert (
        solana_unknown_group(["MINT_AUTHORITY_UNKNOWN", "SECURITY_FREEZE_AUTHORITY_UNKNOWN"])
        == "mint_freeze_authority_unknown"
    )
    assert solana_unknown_group(["NON_TRANSFERABLE_UNKNOWN"]) == "non_transferable_unknown"
    assert (
        solana_unknown_group(["CREATOR_SECURITY_UNKNOWN", "TRANSFER_FEE_UNKNOWN"])
        == "multiple_unknown_reasons"
    )
