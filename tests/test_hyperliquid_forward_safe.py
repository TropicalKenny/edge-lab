from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.hyperliquid_forward import CarryStudyConfig, HyperliquidForwardError
from app.hyperliquid_forward_safe import SafeHyperliquidCarryForwardRunner

D = Decimal


def config(notional="100"):
    return CarryStudyConfig(
        spot_symbol="UBTC",
        horizon_hours=24,
        notional_usd=D(notional),
        planned_loss_pct=D("0.02"),
        min_expected_edge_bps=D("5"),
        shadow_delay_seconds=2,
        spot_fee_bps=D("7"),
        perp_fee_bps=D("4.5"),
        round_trip_slippage_reserve_bps=D("10"),
        funding_mark_tolerance_minutes=15,
        nav_interval_hours=24,
        max_close_delay_minutes=30,
    )


def test_fully_collateralized_allocation_must_fit_frozen_study_capital():
    study = SimpleNamespace(initial_capital_usd=D("200"))
    SafeHyperliquidCarryForwardRunner.validate_study_capital(study, config("100"))

    with pytest.raises(HyperliquidForwardError, match="implicit leverage"):
        SafeHyperliquidCarryForwardRunner.validate_study_capital(
            SimpleNamespace(initial_capital_usd=D("199.99")),
            config("100"),
        )
