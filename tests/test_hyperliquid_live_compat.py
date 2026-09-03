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
        {"name": "UBTC", "index": 150},
        {"name": "ETH", "index": 151},
        {"name": "HYPE", "index": 152},
    ],
    "universe": [
        {"name": "@107", "tokens": [150, 0], "index": 107},
        {"name": "@108", "tokens": [151, 0], "index": 108},
        {"name": "HYPE/USDC", "tokens": [152, 0], "index": 109},
    ],
}


def test_current_spot_context_identity_allows_sparse_and_reordered_contexts():
    payload = [
        META,
        [
            {"coin": "@108", "midPx": "4500", "markPx": "4501", "dayNtlVlm": "4000000"},
            {"coin": "@107", "midPx": "120000", "markPx": "120010", "dayNtlVlm": "8000000"},
        ],
    ]
    spots = parse_spot_contexts(payload, captured_at=NOW)
    assert [(spot.book_coin, spot.pair) for spot in spots] == [
        ("@108", "ETH/USDC"),
        ("@107", "UBTC/USDC"),
    ]


def test_current_spot_context_identity_accepts_unique_human_pair_alias():
    payload = [
        META,
        [{"coin": "UBTC/USDC", "midPx": "120000", "markPx": "120010", "dayNtlVlm": "8000000"}],
    ]
    spots = parse_spot_contexts(payload, captured_at=NOW)
    assert len(spots) == 1
    assert spots[0].book_coin == "@107"
    assert spots[0].pair == "UBTC/USDC"


def test_legacy_unidentified_contexts_require_exact_positional_alignment():
    payload = [
        {"tokens": META["tokens"], "universe": META["universe"][:2]},
        [
            {"midPx": "120000", "markPx": "120010", "dayNtlVlm": "8000000"},
            {"midPx": "4500", "markPx": "4501", "dayNtlVlm": "4000000"},
        ],
    ]
    spots = parse_spot_contexts(payload, captured_at=NOW)
    assert [spot.book_coin for spot in spots] == ["@107", "@108"]

    with pytest.raises(HyperliquidInfoError, match="length mismatch without context identities"):
        parse_spot_contexts([META, payload[1]], captured_at=NOW)


def test_identity_alignment_fails_closed_on_mixed_unknown_or_duplicate_contexts():
    with pytest.raises(HyperliquidInfoError, match="mixed identified/unidentified"):
        parse_spot_contexts(
            [META, [{"coin": "@107", "midPx": "1"}, {"midPx": "2"}]],
            captured_at=NOW,
        )
    with pytest.raises(HyperliquidInfoError, match="unknown spot context identity"):
        parse_spot_contexts([META, [{"coin": "@999", "midPx": "1"}]], captured_at=NOW)
    with pytest.raises(HyperliquidInfoError, match="duplicate spot context identity"):
        parse_spot_contexts(
            [META, [{"coin": "@107", "midPx": "1"}, {"coin": "UBTC/USDC", "midPx": "1"}]],
            captured_at=NOW,
        )


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
