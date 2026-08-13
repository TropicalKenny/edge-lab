import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation import EvaluationPolicy
from app.forward_models import ForwardStudyIncident, ForwardTradeRecord
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


def study_config():
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
        "nav_interval_hours": 24,
        "max_close_delay_minutes": 30,
    }


def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def create_study(db: Session, capital: Decimal):
    strategy = Strategy(slug="capital-carry", name="Capital Carry", status="red")
    db.add(strategy); db.commit()
    version = StrategyVersion(strategy_id=strategy.id, version="v1", config_json="{}", immutable=True)
    db.add(version); db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="capital integrity",
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
        external_id=f"capital-study-{capital}",
        strategy_slug=strategy.slug,
        strategy_version=version.version,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        initial_capital_usd=capital,
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
        study_config=study_config(),
        started_at=START,
    )


class EntryService:
    def __init__(self):
        self.paper_calls = 0

    async def market_state(self, db, persist=True):
        return (
            [SimpleNamespace(coin="BTC", mark_price=D("100"), funding_rate=D("0.001"))],
            [SimpleNamespace(base_symbol="UBTC", display_name="UBTC/USDC", mid_price=D("100"), raw_name="@142")],
        )

    async def paper_book(self, *, coin, side, quantity, fee_bps, allow_partial):
        self.paper_calls += 1
        if coin.startswith("@"):
            price = D("100.1")
        else:
            price = D("99.9") if side == "sell" else D("100.1")
        return SimpleNamespace(
            status="filled",
            filled_quantity=quantity,
            average_price=price,
            total_fees=D("0.1"),
            network_fee=D("0"),
        )


async def noop(_seconds=0):
    return None


def test_actual_entry_notionals_plus_fees_cannot_exceed_study_equity():
    async def run():
        db = database(); study = create_study(db, D("200"))
        runner = StrictHyperliquidCarryForwardRunner(client=None, health=HealthRegistry(), sleep=noop)
        runner.service = EntryService()
        position = await runner.maybe_open(
            db,
            study,
            CarryStudyConfig.from_json(study.study_config_json),
            START + timedelta(hours=1),
        )
        db.refresh(position)
        incident = db.scalar(select(ForwardStudyIncident).where(ForwardStudyIncident.study_id == study.id))
        assert position.status == "invalid"
        assert position.close_reason == "entry-capital-exceeded"
        assert incident is not None and incident.code == "ENTRY_CAPITAL_EXCEEDED"
        db.close()
    asyncio.run(run())


def test_prior_realized_loss_reduces_flat_equity_available_for_next_trade():
    async def run():
        db = database(); study = create_study(db, D("200"))
        db.add(
            ForwardTradeRecord(
                study_id=study.id,
                external_key="old-loss",
                opened_at=START + timedelta(hours=1),
                closed_at=START + timedelta(hours=2),
                gross_pnl_usd=D("-9.8"),
                net_pnl_usd=D("-10"),
                fees_usd=D("0.1"),
                slippage_usd=D("0.1"),
                allocated_capital_usd=D("200"),
                planned_loss_usd=D("4"),
                metadata_json=json.dumps({}),
            )
        )
        db.commit()
        runner = StrictHyperliquidCarryForwardRunner(client=None, health=HealthRegistry(), sleep=noop)
        service = EntryService(); runner.service = service
        position = await runner.maybe_open(
            db,
            study,
            CarryStudyConfig.from_json(study.study_config_json),
            START + timedelta(hours=3),
        )
        assert position is None
        assert runner.flat_equity_usd(db, study) == D("190")
        assert service.paper_calls == 0
        assert db.scalar(select(HyperliquidCarryPosition).where(HyperliquidCarryPosition.study_id == study.id)) is None
        db.close()
    asyncio.run(run())
