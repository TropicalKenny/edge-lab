import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.evaluation import EvaluationPolicy
from app.forward_research import ForwardResearchService
from app.hyperliquid_forward import CarryStudyConfig
from app.hyperliquid_forward_guard import (
    SHADOW_RECOVERY_GRACE_SECONDS,
    can_recover_shadow,
    recover_pending_shadow_state,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.models import Base, Experiment, Strategy, StrategyVersion
import app.evaluation_models
import app.forward_models
import app.hyperliquid_forward_models
import app.venues.hyperliquid_models

D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def config():
    return CarryStudyConfig(
        spot_symbol="UBTC",
        horizon_hours=24,
        notional_usd=D("100"),
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


def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def study(db: Session):
    strategy = Strategy(slug="shadow-recovery", name="Shadow Recovery", status="red")
    db.add(strategy); db.commit()
    version = StrategyVersion(strategy_id=strategy.id, version="v1", config_json="{}", immutable=True)
    db.add(version); db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="recovery",
        data_version="v1",
        train_window="x",
        validation_window="y",
        holdout_window="z",
        search_space_json="{}",
        status="registered",
    )
    db.add(experiment); db.commit()
    return ForwardResearchService.create_study(
        db,
        external_id="shadow-recovery-study",
        strategy_slug=strategy.slug,
        strategy_version=version.version,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        initial_capital_usd=D("1000"),
        evaluation_policy=EvaluationPolicy(
            min_forward_days=2,
            min_nav_observations=2,
            min_shadow_observations=1,
            min_trades_default=1,
            min_trades_funding=1,
            min_trades_directional=1,
            min_trades_meme=1,
            min_forecasts_prediction=1,
            max_top3_profit_concentration=D("1"),
            max_nav_gap_days=D("2"),
        ),
        study_config={
            "spot_symbol": "UBTC",
            "horizon_hours": 24,
            "notional_usd": "100",
            "planned_loss_pct": "0.02",
            "min_expected_edge_bps": "5",
            "shadow_delay_seconds": 2,
            "spot_fee_bps": "7",
            "perp_fee_bps": "4.5",
            "round_trip_slippage_reserve_bps": "10",
            "funding_mark_tolerance_minutes": 15,
            "nav_interval_hours": 24,
            "max_close_delay_minutes": 30,
        },
        started_at=START,
    )


def open_position(db: Session, study_id: str):
    row = HyperliquidCarryPosition(
        study_id=study_id,
        external_key="recovery-position",
        coin="BTC",
        spot_book_coin="@142",
        status="open",
        quantity=D("1"),
        allocated_capital_usd=D("200"),
        planned_loss_usd=D("4"),
        opened_at=START + timedelta(hours=1),
        target_close_at=START + timedelta(days=1, hours=1),
        entry_spot_mid=D("100"),
        entry_perp_mid=D("100"),
        entry_spot_price=D("100.1"),
        entry_perp_price=D("99.9"),
        entry_spot_fee_usd=D("0.1"),
        entry_perp_fee_usd=D("0.1"),
        entry_spot_slippage_usd=D("0.1"),
        entry_perp_slippage_usd=D("0.1"),
        metadata_json="{}",
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_shadow_recovery_budget_is_only_five_seconds_beyond_frozen_delay():
    cfg = config()
    base = START
    assert SHADOW_RECOVERY_GRACE_SECONDS == 5
    assert can_recover_shadow(base, cfg, base + timedelta(seconds=4)) is True
    assert can_recover_shadow(base, cfg, base + timedelta(seconds=6)) is False


def test_pending_entry_shadow_can_recover_inside_budget_without_creating_a_new_trade():
    async def run():
        db = database(); s = study(db); p = open_position(db, s.id)

        class FakeRunner:
            def __init__(self):
                self.calls = 0

            async def _entry_shadow(self, db, position, cfg):
                self.calls += 1
                position.entry_shadow_observed_at = position.opened_at + timedelta(seconds=cfg.shadow_delay_seconds)
                position.entry_shadow_spot_filled_quantity = position.quantity
                position.entry_shadow_perp_filled_quantity = position.quantity
                position.entry_shadow_spot_price = D("100.2")
                position.entry_shadow_perp_price = D("99.8")
                position.entry_shadow_spot_cost_usd = D("0.1")
                position.entry_shadow_perp_cost_usd = D("0.1")
                db.commit()

        runner = FakeRunner()
        recovered = await recover_pending_shadow_state(
            db,
            runner=runner,
            study_id=s.id,
            config=config(),
            now=p.opened_at + timedelta(seconds=1),
        )
        db.refresh(p)
        assert recovered == 1
        assert runner.calls == 1
        assert p.entry_shadow_observed_at is not None
        assert p.status == "open"
        db.close()
    asyncio.run(run())
