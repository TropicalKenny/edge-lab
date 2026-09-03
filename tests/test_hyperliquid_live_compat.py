from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.venues.hyperliquid import HyperliquidInfoError
from app.venues.hyperliquid_spot import parse_spot_contexts

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]

META = {
    "tokens": [
        {"name": "USDC", "index": 0},
        {"name": "PEAR", "index": 71},
        {"name": "ETH", "index": 151},
        {"name": "HYPE", "index": 150},
    ],
    "universe": [
        {"name": "@114", "tokens": [71, 0], "index": 114},
        {"name": "@108", "tokens": [151, 0], "index": 108},
        {"name": "@107", "tokens": [150, 0], "index": 107},
    ],
}


def _contexts(size: int = 160):
    return [None] * size


def test_current_spot_markets_select_contexts_by_explicit_market_index():
    contexts = _contexts()
    # This is a real-world-shaped extra row: token index 71 can have a context row,
    # but it is not the current context for market index 114.
    contexts[71] = {
        "coin": "@71",
        "midPx": None,
        "markPx": "1",
        "dayNtlVlm": "0",
    }
    contexts[107] = {
        "coin": "@107",
        "midPx": "81.7165",
        "markPx": "81.724",
        "dayNtlVlm": "78043463",
    }
    contexts[108] = {
        "coin": "@108",
        "midPx": "4500",
        "markPx": "4501",
        "dayNtlVlm": "4000000",
    }
    contexts[114] = {
        "coin": "@114",
        "midPx": "0.0001033",
        "markPx": "0.0000812",
        "dayNtlVlm": "0",
    }

    spots = parse_spot_contexts([META, contexts], captured_at=NOW)
    assert [(spot.book_coin, spot.pair) for spot in spots] == [
        ("@114", "PEAR/USDC"),
        ("@108", "ETH/USDC"),
        ("@107", "HYPE/USDC"),
    ]
    assert str(spots[0].mid_px) == "0.0001033"


def test_context_rows_not_referenced_by_current_universe_are_ignored():
    meta = {
        "tokens": [{"name": "USDC", "index": 0}, {"name": "PEAR", "index": 71}],
        "universe": [{"name": "@114", "tokens": [71, 0], "index": 114}],
    }
    contexts = _contexts(120)
    contexts[71] = {"coin": "@71", "markPx": "1", "dayNtlVlm": "0"}
    contexts[98] = {"coin": "@98", "markPx": "2", "dayNtlVlm": "0"}
    contexts[114] = {
        "coin": "@114",
        "midPx": "0.0001033",
        "markPx": "0.0000812",
        "dayNtlVlm": "0",
    }

    spots = parse_spot_contexts([meta, contexts], captured_at=NOW)
    assert len(spots) == 1
    assert spots[0].book_coin == "@114"
    assert spots[0].pair == "PEAR/USDC"


def test_context_identity_must_match_the_current_market_at_that_index():
    meta = {
        "tokens": [{"name": "USDC", "index": 0}, {"name": "PEAR", "index": 71}],
        "universe": [{"name": "@114", "tokens": [71, 0], "index": 114}],
    }
    contexts = _contexts(120)
    contexts[114] = {"coin": "@71", "midPx": "1"}

    with pytest.raises(HyperliquidInfoError, match="spot context identity mismatch"):
        parse_spot_contexts([meta, contexts], captured_at=NOW)


def test_missing_invalid_duplicate_or_out_of_range_market_index_fails_closed():
    tokens = [{"name": "USDC", "index": 0}, {"name": "PEAR", "index": 71}]

    with pytest.raises(HyperliquidInfoError, match="invalid spot market index"):
        parse_spot_contexts(
            [{"tokens": tokens, "universe": [{"name": "@114", "tokens": [71, 0]}]}, _contexts()],
            captured_at=NOW,
        )

    with pytest.raises(HyperliquidInfoError, match="invalid spot market index"):
        parse_spot_contexts(
            [
                {"tokens": tokens, "universe": [{"name": "@114", "tokens": [71, 0], "index": -1}]},
                _contexts(),
            ],
            captured_at=NOW,
        )

    with pytest.raises(HyperliquidInfoError, match="duplicate current spot market index: 114"):
        parse_spot_contexts(
            [
                {
                    "tokens": tokens,
                    "universe": [
                        {"name": "@114", "tokens": [71, 0], "index": 114},
                        {"name": "PEAR/USDC", "tokens": [71, 0], "index": 114},
                    ],
                },
                _contexts(),
            ],
            captured_at=NOW,
        )

    with pytest.raises(HyperliquidInfoError, match="spot context index out of range"):
        parse_spot_contexts(
            [
                {"tokens": tokens, "universe": [{"name": "@114", "tokens": [71, 0], "index": 114}]},
                _contexts(100),
            ],
            captured_at=NOW,
        )


def test_unidentified_context_is_accepted_when_explicit_market_index_is_unambiguous():
    meta = {
        "tokens": [{"name": "USDC", "index": 0}, {"name": "PURR", "index": 1}],
        "universe": [{"name": "PURR/USDC", "tokens": [1, 0], "index": 0}],
    }
    contexts = [{"midPx": "0.107035", "markPx": "0.10702", "dayNtlVlm": "10"}]
    spots = parse_spot_contexts([meta, contexts], captured_at=NOW)
    assert len(spots) == 1
    assert spots[0].book_coin == "PURR/USDC"
    assert spots[0].pair == "PURR/USDC"


def test_current_market_without_parseable_price_fails_closed():
    meta = {
        "tokens": [{"name": "USDC", "index": 0}, {"name": "PEAR", "index": 71}],
        "universe": [{"name": "@114", "tokens": [71, 0], "index": 114}],
    }
    contexts = _contexts(120)
    contexts[114] = {"coin": "@114", "midPx": None, "markPx": None}
    with pytest.raises(HyperliquidInfoError, match="failed to parse current spot market: @114"):
        parse_spot_contexts([meta, contexts], captured_at=NOW)


def test_hyperliquid_shadow_fill_migration_covers_every_model_only_column():
    path = ROOT / "alembic" / "versions" / "m3e6ab97d288_add_hyperliquid_shadow_fill_columns.py"
    text = path.read_text()
    assert 'down_revision: str | Sequence[str] | None = "l2d59a86c177"' in text
    expected = {
        "entry_shadow_observed_at",
        "entry_shadow_spot_filled_quantity",
        "entry_shadow_perp_filled_quantity",
        "entry_shadow_spot_price",
        "entry_shadow_perp_price",
        "entry_shadow_spot_cost_usd",
        "entry_shadow_perp_cost_usd",
        "exit_spot_fee_usd",
        "exit_perp_fee_usd",
        "exit_spot_slippage_usd",
        "exit_perp_slippage_usd",
        "exit_shadow_observed_at",
        "exit_shadow_spot_filled_quantity",
        "exit_shadow_perp_filled_quantity",
        "exit_shadow_spot_price",
        "exit_shadow_perp_price",
        "exit_shadow_spot_cost_usd",
        "exit_shadow_perp_cost_usd",
    }
    for column in expected:
        assert f'"{column}"' in text
