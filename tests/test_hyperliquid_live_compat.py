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
        {"name": "UBTC", "index": 197},
        {"name": "ETH", "index": 151},
        {"name": "HYPE", "index": 150},
    ],
    "universe": [
        {"name": "@142", "tokens": [197, 0], "index": 142},
        {"name": "@108", "tokens": [151, 0], "index": 108},
        {"name": "@107", "tokens": [150, 0], "index": 107},
    ],
}


def test_identified_contexts_follow_current_universe_and_ignore_extra_rows():
    payload = [
        META,
        [
            {"coin": "@197", "midPx": None, "markPx": "1", "dayNtlVlm": "0"},
            {"coin": "@108", "midPx": "4500", "markPx": "4501", "dayNtlVlm": "4000000"},
            {"coin": "@71", "midPx": None, "markPx": "1", "dayNtlVlm": "0"},
            {"coin": "@142", "midPx": "77558.5", "markPx": "77558", "dayNtlVlm": "30556047"},
            {"coin": "@107", "midPx": "81.7165", "markPx": "81.724", "dayNtlVlm": "78043463"},
        ],
    ]
    spots = parse_spot_contexts(payload, captured_at=NOW)
    assert [(spot.book_coin, spot.pair) for spot in spots] == [
        ("@142", "UBTC/USDC"),
        ("@108", "ETH/USDC"),
        ("@107", "HYPE/USDC"),
    ]


def test_ubtc_uses_current_market_context_not_extra_token_index_context():
    meta = {
        "tokens": [{"name": "USDC", "index": 0}, {"name": "UBTC", "index": 197}],
        "universe": [{"name": "@142", "tokens": [197, 0], "index": 142}],
    }
    payload = [
        meta,
        [
            {"coin": "@197", "midPx": None, "markPx": "1", "dayNtlVlm": "0"},
            {"coin": "@142", "midPx": "77558.5", "markPx": "77558", "dayNtlVlm": "30556047"},
        ],
    ]
    spots = parse_spot_contexts(payload, captured_at=NOW)
    assert len(spots) == 1
    assert spots[0].book_coin == "@142"
    assert spots[0].pair == "UBTC/USDC"
    assert str(spots[0].mid_px) == "77558.5"
    assert str(spots[0].day_ntl_volume) == "30556047"


def test_identified_contexts_fail_closed_when_current_market_is_missing_or_duplicated():
    with pytest.raises(HyperliquidInfoError, match="missing spot context for current market: @108"):
        parse_spot_contexts(
            [
                META,
                [
                    {"coin": "@142", "midPx": "77558.5"},
                    {"coin": "@107", "midPx": "81.7"},
                    {"coin": "@71", "midPx": "1"},
                ],
            ],
            captured_at=NOW,
        )

    one_market = {
        "tokens": META["tokens"],
        "universe": [META["universe"][0]],
    }
    with pytest.raises(HyperliquidInfoError, match="duplicate spot context for current market: @142"):
        parse_spot_contexts(
            [
                one_market,
                [
                    {"coin": "@142", "midPx": "77558.5"},
                    {"coin": "@142", "midPx": "77559"},
                ],
            ],
            captured_at=NOW,
        )


def test_identified_contexts_fail_closed_on_mixed_identity_shape():
    one_market = {
        "tokens": META["tokens"],
        "universe": [META["universe"][0]],
    }
    with pytest.raises(HyperliquidInfoError, match="mixed identified/unidentified"):
        parse_spot_contexts(
            [one_market, [{"coin": "@142", "midPx": "77558.5"}, {"midPx": "1"}]],
            captured_at=NOW,
        )


def test_legacy_unidentified_contexts_require_exact_positional_alignment():
    payload = [
        {"tokens": META["tokens"], "universe": META["universe"][:2]},
        [
            {"midPx": "77558.5", "markPx": "77558", "dayNtlVlm": "30556047"},
            {"midPx": "4500", "markPx": "4501", "dayNtlVlm": "4000000"},
        ],
    ]
    spots = parse_spot_contexts(payload, captured_at=NOW)
    assert [spot.book_coin for spot in spots] == ["@142", "@108"]

    with pytest.raises(HyperliquidInfoError, match="length mismatch without context identities"):
        parse_spot_contexts([META, payload[1]], captured_at=NOW)


def test_current_market_without_parseable_price_fails_closed():
    one_market = {
        "tokens": META["tokens"],
        "universe": [META["universe"][0]],
    }
    with pytest.raises(HyperliquidInfoError, match="failed to parse current spot market: @142"):
        parse_spot_contexts(
            [one_market, [{"coin": "@142", "midPx": None, "markPx": None}]],
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
