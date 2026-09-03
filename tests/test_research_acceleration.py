from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.forward_models import ForwardScanObservation
from app.models import Base
from app.research_acceleration import (
    classify_solana_candidate,
    compact_jupiter_quote,
    parse_csv_ints,
    parse_csv_symbols,
    polymarket_book_from_ws,
)
from app.scan_telemetry import record_scan_observation, scan_activity_summary
from app.venues.polymarket import OrderBook, PriceLevel

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _feature(**overrides):
    values = {
        "mintable": False,
        "freezable": False,
        "malicious_creator": False,
        "transfer_fee_rate": Decimal("0"),
        "missing_fields_json": "[]",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _security(**overrides):
    values = {
        "non_transferable": False,
        "mintable": False,
        "freezable": False,
        "malicious_creator": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_solana_tri_state_keeps_unknown_distinct_from_unsafe():
    safe = classify_solana_candidate(_feature(), _security())
    unknown = classify_solana_candidate(
        _feature(malicious_creator=None, transfer_fee_rate=None),
        _security(malicious_creator=None),
    )
    unsafe = classify_solana_candidate(_feature(freezable=True), _security())

    assert safe.state == "SAFE"
    assert unknown.state == "UNKNOWN"
    assert "CREATOR_SECURITY_UNKNOWN" in unknown.reasons
    assert "TRANSFER_FEE_UNKNOWN" in unknown.reasons
    assert unsafe.state == "UNSAFE"
    assert "FREEZE_AUTHORITY_ACTIVE" in unsafe.reasons


def test_confirmed_unsafe_wins_even_when_other_fields_are_unknown():
    result = classify_solana_candidate(
        _feature(mintable=True, malicious_creator=None, transfer_fee_rate=None),
        None,
    )
    assert result.state == "UNSAFE"
    assert "MINT_AUTHORITY_ACTIVE" in result.reasons
    assert "SECURITY_SNAPSHOT_MISSING" in result.reasons


def test_compact_jupiter_quote_never_preserves_transaction_material():
    quote = SimpleNamespace(
        input_mint="USDC",
        output_mint="TOKEN",
        in_amount=25_000_000,
        out_amount=123456,
        in_usd_value=Decimal("25"),
        out_usd_value=Decimal("24.8"),
        price_impact_pct=Decimal("0.01"),
        captured_at=NOW,
        transaction_present=False,
        transaction="must-not-be-copied",
        swap_transaction="must-not-be-copied",
    )
    compact = compact_jupiter_quote(quote)
    assert compact is not None
    assert compact["transaction_present"] is False
    assert "transaction" not in compact
    assert "swap_transaction" not in compact


def test_csv_research_configuration_is_deduplicated_and_bounded():
    assert parse_csv_ints("5,15,15,60", minimum=1, maximum=60) == (5, 15, 60)
    assert parse_csv_symbols("btc, ETH,btc, sol") == ("BTC", "ETH", "SOL")


def test_polymarket_ws_book_uses_rest_seed_metadata_and_validates_identity():
    seed = OrderBook(
        condition_id="condition-1",
        token_id="token-yes",
        bids=(PriceLevel(Decimal("0.49"), Decimal("10")),),
        asks=(PriceLevel(Decimal("0.51"), Decimal("10")),),
        min_order_size=Decimal("5"),
        tick_size=Decimal("0.01"),
        neg_risk=False,
        last_trade_price=Decimal("0.50"),
        book_hash="seed",
        timestamp=NOW,
        captured_at=NOW,
    )
    payload = {
        "event_type": "book",
        "asset_id": "token-yes",
        "market": "condition-1",
        "timestamp": str(int(NOW.timestamp() * 1000)),
        "hash": "ws-hash",
        "bids": [{"price": "0.48", "size": "12"}],
        "asks": [{"price": "0.50", "size": "8"}],
    }
    book = polymarket_book_from_ws(seed, payload, captured_at=NOW + timedelta(seconds=1))
    assert book.min_order_size == seed.min_order_size
    assert book.tick_size == seed.tick_size
    assert book.bids[0].price == Decimal("0.48")
    assert book.asks[0].price == Decimal("0.50")
    assert book.book_hash == "ws-hash"


def test_scan_summary_can_isolate_m6j_from_frozen_baseline_activity():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        record_scan_observation(
            db,
            study_id="study-1",
            external_key="baseline-1",
            observation_kind="candidate",
            observed_at=NOW,
            examined_count=1,
            rejected_count=1,
            rejection_reasons={"BASELINE_REJECT": 1},
            metadata={"stage": "baseline"},
        )
        record_scan_observation(
            db,
            study_id="study-1",
            external_key="m6j-1",
            observation_kind="candidate",
            observed_at=NOW + timedelta(seconds=1),
            examined_count=1,
            accepted_count=1,
            metadata={"research_lane": "m6j", "m6j_candidates_examined": 1},
        )

        baseline = scan_activity_summary(
            db,
            study_id="study-1",
            now=NOW + timedelta(minutes=1),
            exclude_research_lanes=("m6j",),
        )
        m6j = scan_activity_summary(
            db,
            study_id="study-1",
            now=NOW + timedelta(minutes=1),
            research_lane="m6j",
        )

    assert baseline["examined"] == 1
    assert baseline["rejected"] == 1
    assert baseline["accepted"] == 0
    assert m6j["examined"] == 1
    assert m6j["accepted"] == 1
    assert m6j["rejected"] == 0
    assert m6j["metadata_totals"]["m6j_candidates_examined"] == 1
