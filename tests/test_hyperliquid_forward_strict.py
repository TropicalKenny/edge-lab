import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation import EvaluationPolicy
from app.forward_models import ForwardNavObservation, ForwardStudyIncident, ForwardTradeRecord
from app.forward_research import ForwardResearchService
from app.hyperliquid_forward import CarryStudyConfig
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.hyperliquid_forward_strict import StrictHyperliquidCarryForwardRunner
from app.models import Base, Experiment, Strategy, StrategyVersion
from app.services import HealthRegistry
import app.evaluation_models
import app.forward_models
import app.hyperliquid_forward_models
import app.venues.hyperliquid_models

D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def config():
    return {
        "spot_symbol": "UBTC",
        "horizon_hours": 24,
        "notional_usd": "100",
        "planned_loss_pct": "0.02",
        "min_expected_edge_bps": "5",
        "shadow_delay_seconds": 0,
        "spot_fee_bps": "7",
        "perp_fee_bps": "4.5",
        "round_trip_slippage_reserve_bps": "10",
        "funding_mark_tolerance_minutes": 15,
        "nav_interval_hours": 1,
        "max_close_delay_minutes": 30,
    }


def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def create_study(db: Session):
    strategy = Strategy(slug="strict-carry", name="Strict Carry", status="red")
    db.add(strategy); db.commit()
    version = StrategyVersion(strategy_id=strategy.id, version="v1", config_json="{}", immutable=True)
    db.add(version); db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="strict carry",
        data_version="v1",
        train_window="x",
        validation_window="y",
        holdout_window="z",
        search_space_json="{}",
        status="registered",
    )
    db.add(experiment); db.commit()
    study = ForwardResearchService.create_study(
        db,
        external_id="strict-carry-study",
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
        study_config=config(),
        started_at=START,
    )
    return study


def add_position(db: Session, study_id: str):
    position = HyperliquidCarryPosition(
        study_id=study_id,
        external_key="strict-position",
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
        entry_shadow_observed_at=START + timedelta(hours=1, seconds=2),
        entry_shadow_spot_filled_quantity=D("1"),
        entry_shadow_perp_filled_quantity=D("1"),
        entry_shadow_spot_price=D("100.1"),
        entry_shadow_perp_price=D("99.9"),
        entry_shadow_spot_cost_usd=D("0.1"),
        entry_shadow_perp_cost_usd=D("0.1"),
        metadata_json="{}",
    )
    db.add(position); db.commit(); db.refresh(position)
    return position


class StrictFakeService:
    def __init__(self, *, adverse=False):
        self.adverse = adverse
        self.funding_calls = 0
        self.paper_calls = 0

    async def market_state(self, db, persist=True):
        perp_mark = D("110") if self.adverse else D("100")
        return (
            [SimpleNamespace(coin="BTC", mark_price=perp_mark, funding_rate=D("0.001"))],
            [SimpleNamespace(base_symbol="UBTC", display_name="UBTC/USDC", mid_price=D("100"), raw_name="@142")],
        )

    async def funding_history(self, db, *, coin, hours, persist=True):
        self.funding_calls += 1
        return []

    async def paper_book(self, *, coin, side, quantity, fee_bps, allow_partial):
        self.paper_calls += 1
        if coin.startswith("@"):
            price = D("99.9") if side == "sell" else D("100.1")
        else:
            price = D("110.1") if self.adverse and side == "buy" else (D("100.1") if side == "buy" else D("99.9"))
        return SimpleNamespace(
            status="filled",
            filled_quantity=quantity,
            average_price=price,
            total_fees=D("0.1"),
            network_fee=D("0"),
        )


async def noop(_seconds=0):
    return None


def test_nav_refreshes_funding_and_refuses_zero_settlements_after_two_hours():
    async def run():
        db = db_session(); study = create_study(db); position = add_position(db, study.id)
        runner = StrictHyperliquidCarryForwardRunner(client=None, health=HealthRegistry(), sleep=noop)
        fake = StrictFakeService(adverse=False)
        runner.service = fake
        now = position.opened_at + timedelta(hours=3)
        recorded = await runner.maybe_nav(db, study, CarryStudyConfig.from_json(study.study_config_json), now)
        incident = db.scalar(select(ForwardStudyIncident).where(ForwardStudyIncident.study_id == study.id))
        nav = db.scalar(select(ForwardNavObservation).where(ForwardNavObservation.study_id == study.id))
        assert recorded is False
        assert fake.funding_calls >= 1
        assert incident is not None and incident.code == "FUNDING_HISTORY_MISSING"
        assert incident.data_integrity is True
        assert nav is None
        db.close()
    asyncio.run(run())


def test_planned_loss_breach_closes_before_horizon_and_persists_trade_evidence():
    async def run():
        db = db_session(); study = create_study(db); position = add_position(db, study.id)
        runner = StrictHyperliquidCarryForwardRunner(client=None, health=HealthRegistry(), sleep=noop)
        runner.service = StrictFakeService(adverse=True)
        now = position.opened_at + timedelta(minutes=30)
        closed = await runner.maybe_planned_loss_close(
            db,
            study,
            position,
            CarryStudyConfig.from_json(study.study_config_json),
            now,
        )
        db.refresh(position)
        trade = db.scalar(select(ForwardTradeRecord).where(ForwardTradeRecord.study_id == study.id))
        assert closed is True
        assert position.status == "closed"
        assert position.close_reason == "planned-loss"
        assert position.closed_at < position.target_close_at
        assert Decimal(position.net_pnl_usd) <= -Decimal(position.planned_loss_usd)
        assert trade is not None
        assert Decimal(trade.net_pnl_usd) == Decimal(position.net_pnl_usd)
        db.close()
    asyncio.run(run())
