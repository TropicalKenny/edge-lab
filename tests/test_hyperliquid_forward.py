import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.evaluation import EvaluationPolicy
from app.forward_models import ForwardExecutionRecord, ForwardNavObservation, ForwardTradeRecord
from app.forward_research import ForwardResearchService
from app.hyperliquid_forward import (
    CarryRunnerConfigError,
    CarryStudyConfig,
    HyperliquidCarryForwardRunner,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.models import Base, Experiment, Strategy, StrategyVersion
from app.services import HealthRegistry
from app.venues.hyperliquid_models import HyperliquidPerpSnapshot
import app.evaluation_models
import app.forward_models
import app.hyperliquid_forward_models
import app.venues.hyperliquid_models

D = Decimal


class FakeHyperliquidClient:
    def __init__(
        self,
        *,
        funding_rate: str = "0.005",
        spot_mid: str = "100",
        perp_mid: str = "100",
        book_quantity: str = "10",
        funding_points=None,
    ):
        self.funding_rate = funding_rate
        self.spot_mid = spot_mid
        self.perp_mid = perp_mid
        self.book_quantity = book_quantity
        self.funding_points = funding_points or []
        self.book_calls = 0
        self.book_times: list[datetime] = []

    async def meta_and_asset_contexts(self, dex: str = ""):
        return [
            {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
            [{
                "markPx": self.perp_mid,
                "midPx": self.perp_mid,
                "oraclePx": self.perp_mid,
                "funding": self.funding_rate,
                "premium": "0",
                "openInterest": "1000",
                "dayNtlVlm": "1000000",
            }],
        ]

    async def spot_meta_and_asset_contexts(self):
        return [
            {
                "tokens": [{"index": 0, "name": "USDC"}, {"index": 1, "name": "UBTC"}],
                "universe": [{"name": "@0", "tokens": [1, 0]}],
            },
            [{"midPx": self.spot_mid, "dayNtlVlm": "1000000"}],
        ]

    async def l2_book(self, coin: str):
        self.book_calls += 1
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        observed_at = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        self.book_times.append(observed_at)
        qty = self.book_quantity
        if coin == "@0":
            bids = [{"px": str(D(self.spot_mid) - D("0.1")), "sz": qty}]
            asks = [{"px": str(D(self.spot_mid) + D("0.1")), "sz": qty}]
        else:
            bids = [{"px": str(D(self.perp_mid) - D("0.1")), "sz": qty}]
            asks = [{"px": str(D(self.perp_mid) + D("0.1")), "sz": qty}]
        return {"coin": coin, "time": now_ms, "levels": [bids, asks]}

    async def funding_history(self, coin: str, start_time_ms: int, end_time_ms: int | None = None):
        return list(self.funding_points)


def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def policy():
    return EvaluationPolicy(
        min_forward_days=2,
        min_nav_observations=3,
        min_shadow_observations=2,
        min_trades_default=2,
        min_trades_funding=2,
        min_trades_directional=2,
        min_trades_meme=2,
        min_forecasts_prediction=2,
        max_top3_profit_concentration=D("1"),
        max_nav_gap_days=D("3"),
    )


def make_study(db: Session, *, now: datetime, config_overrides=None, started_hours_ago=0):
    strategy = Strategy(slug="hl-carry", name="HL Carry", status="red")
    db.add(strategy)
    db.commit()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="v1",
        config_json="{}",
        immutable=True,
    )
    db.add(version)
    db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="Positive Hyperliquid funding can support delta-neutral carry after executable costs.",
        data_version="forward-live-books-v1",
        train_window="historical",
        validation_window="paper-shadow",
        holdout_window="future-forward",
        search_space_json="{}",
        status="registered",
    )
    db.add(experiment)
    db.commit()
    cfg = {
        "runner": "hyperliquid_carry_v1",
        "paired_notional_usd": "100",
        "horizon_hours": 1,
        "min_edge_bps": "0",
        "planned_loss_pct": "0.02",
        "spot_fee_bps": "7",
        "perp_fee_bps": "4.5",
        "slippage_reserve_bps_per_leg": "2",
        "shadow_delay_ms": 0,
        "max_exit_delay_hours": 3,
        "max_funding_oracle_age_minutes": 5,
    }
    cfg.update(config_overrides or {})
    return ForwardResearchService.create_study(
        db,
        external_id="hl-carry-forward",
        strategy_slug=strategy.slug,
        strategy_version=version.version,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        initial_capital_usd=D("1000"),
        evaluation_policy=policy(),
        study_config=cfg,
        started_at=now - timedelta(hours=started_hours_ago, minutes=5),
    )


def test_eligible_carry_opens_only_after_both_paper_and_shadow_legs_fill():
    now = datetime.now(timezone.utc)
    db = db_session()
    study = make_study(db, now=now, started_hours_ago=2)
    client = FakeHyperliquidClient()
    runner = HyperliquidCarryForwardRunner(client=client, health=HealthRegistry())

    result = asyncio.run(runner.run_study_once(db, study=study, now=now))

    position = db.scalar(
        select(HyperliquidCarryPosition).where(HyperliquidCarryPosition.study_id == study.id)
    )
    executions = db.scalars(
        select(ForwardExecutionRecord).where(ForwardExecutionRecord.study_id == study.id)
    ).all()
    navs = db.scalars(
        select(ForwardNavObservation)
        .where(ForwardNavObservation.study_id == study.id)
        .order_by(ForwardNavObservation.observed_at.asc())
    ).all()
    assert result.action == "opened"
    assert position is not None and position.status == "open"
    assert position.coin == "BTC" and position.spot_book_coin == "@0"
    assert position.quantity == D("1.0000000000")
    assert position.allocated_capital_usd == D("200.0000000000")
    assert len(executions) == 2
    assert all(D(row.paper_filled_quantity) == D("1") for row in executions)
    assert all(D(row.shadow_filled_quantity) == D("1") for row in executions)
    assert client.book_calls >= 6
    assert len(navs) == 2
    assert navs[-1].observed_at in client.book_times
    assert navs[-1].observed_at != navs[-1].observed_at.replace(
        minute=0, second=0, microsecond=0
    )
    db.close()


def test_insufficient_depth_records_execution_quality_but_never_opens_position():
    now = datetime.now(timezone.utc)
    db = db_session()
    study = make_study(db, now=now)
    client = FakeHyperliquidClient(book_quantity="0.25")
    runner = HyperliquidCarryForwardRunner(client=client, health=HealthRegistry())

    first = asyncio.run(runner.run_study_once(db, study=study, now=now))
    second = asyncio.run(runner.run_study_once(db, study=study, now=now + timedelta(seconds=5)))

    assert first.action == "entry_rejected"
    assert second.action == "entry_already_attempted"
    assert db.scalar(
        select(HyperliquidCarryPosition).where(HyperliquidCarryPosition.study_id == study.id)
    ) is None
    count = db.scalar(
        select(func.count()).select_from(ForwardExecutionRecord).where(
            ForwardExecutionRecord.study_id == study.id
        )
    )
    assert count == 2
    db.close()


def test_study_config_forbids_using_more_than_initial_capital_without_leverage():
    now = datetime.now(timezone.utc)
    db = db_session()
    study = make_study(db, now=now, config_overrides={"paired_notional_usd": "600"})
    with pytest.raises(CarryRunnerConfigError, match="exceeds study initial capital"):
        CarryStudyConfig.from_study(study)
    db.close()


def test_due_position_closes_atomically_using_oracle_based_settled_funding():
    now = datetime.now(timezone.utc)
    funding_time = now - timedelta(minutes=30)
    db = db_session()
    study = make_study(db, now=now, started_hours_ago=3)
    ForwardResearchService.record_nav(
        db,
        study_id=study.id,
        observed_at=study.started_at,
        nav_usd=D("1000"),
        source="study-initial-capital",
    )
    position = HyperliquidCarryPosition(
        study_id=study.id,
        external_key="seeded-entry",
        coin="BTC",
        spot_book_coin="@0",
        status="open",
        quantity=D("1"),
        allocated_capital_usd=D("200"),
        planned_loss_usd=D("4"),
        opened_at=now - timedelta(hours=2),
        target_close_at=now - timedelta(hours=1),
        entry_spot_mid=D("100"),
        entry_perp_mid=D("80"),
        entry_spot_price=D("100.1"),
        entry_perp_price=D("79.9"),
        entry_spot_fee_usd=D("0.07"),
        entry_perp_fee_usd=D("0.045"),
        entry_spot_slippage_usd=D("0.1"),
        entry_perp_slippage_usd=D("0.1"),
        metadata_json="{}",
    )
    db.add(position)
    db.add(
        HyperliquidPerpSnapshot(
            coin="BTC",
            mark_px=D("999"),
            mid_px=D("999"),
            oracle_px=D("100"),
            funding_rate_hourly=D("0.001"),
            premium=D("0"),
            open_interest=D("1000"),
            day_ntl_volume=D("1000000"),
            captured_at=funding_time - timedelta(minutes=1),
        )
    )
    db.commit()
    db.refresh(position)
    client = FakeHyperliquidClient(
        spot_mid="101",
        perp_mid="101",
        funding_points=[{
            "coin": "BTC",
            "fundingRate": "0.001",
            "premium": "0",
            "time": int(funding_time.timestamp() * 1000),
        }],
    )
    runner = HyperliquidCarryForwardRunner(client=client, health=HealthRegistry())

    result = asyncio.run(runner.run_study_once(db, study=study, now=now))

    db.refresh(position)
    trade = db.scalar(select(ForwardTradeRecord).where(ForwardTradeRecord.study_id == study.id))
    assert result.action == "closed"
    assert position.status == "closed" and position.trade_record_id is not None
    assert trade is not None and trade.id == position.trade_record_id
    # Funding must use the persisted oracle (100), not the mark (999) or entry mid (80).
    assert D(position.funding_pnl_usd) == D("0.1000000000")
    assert D(trade.net_pnl_usd) == D(trade.gross_pnl_usd) - D(trade.fees_usd) - D(
        trade.slippage_usd
    )
    assert D(position.net_pnl_usd) == D(trade.net_pnl_usd)
    db.close()


def test_position_model_contains_no_signing_or_wallet_material():
    names = {column.name for column in HyperliquidCarryPosition.__table__.columns}
    forbidden = {"private_key", "seed_phrase", "api_secret", "wallet_key", "signing_key"}
    assert names.isdisjoint(forbidden)
