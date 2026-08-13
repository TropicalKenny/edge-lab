from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation import EvaluationPolicy
from app.forward_models import ForwardStudyIncident, ForwardTradeRecord
from app.forward_research import ForwardResearchService
from app.hyperliquid_forward import CarryStudyConfig
from app.hyperliquid_forward_guard import invalidate_stale_shadow_state, repair_closed_evidence
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.models import Base, Experiment, Strategy, StrategyVersion
import app.evaluation_models
import app.forward_models
import app.hyperliquid_forward_models
import app.venues.hyperliquid_models

D = Decimal
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


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


def study(db: Session):
    strategy = Strategy(slug="guard", name="Guard", status="red")
    db.add(strategy); db.commit()
    version = StrategyVersion(strategy_id=strategy.id, version="v1", config_json="{}", immutable=True)
    db.add(version); db.commit()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="guard",
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
        external_id="guard-study",
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


def position(db: Session, study_id: str, *, status="open", closed_at=None, with_exit_shadow=False):
    row = HyperliquidCarryPosition(
        study_id=study_id,
        external_key=f"p-{status}-{with_exit_shadow}",
        coin="BTC",
        spot_book_coin="@142",
        status=status,
        quantity=D("1"),
        allocated_capital_usd=D("200"),
        planned_loss_usd=D("4"),
        opened_at=START + timedelta(hours=1),
        target_close_at=START + timedelta(days=1, hours=1),
        closed_at=closed_at,
        entry_spot_mid=D("100"),
        entry_perp_mid=D("100"),
        entry_spot_price=D("100.1"),
        entry_perp_price=D("99.9"),
        entry_spot_fee_usd=D("0.1"),
        entry_perp_fee_usd=D("0.1"),
        entry_spot_slippage_usd=D("0.1"),
        entry_perp_slippage_usd=D("0.1"),
        exit_spot_mid=D("101") if status == "closed" else None,
        exit_perp_mid=D("101") if status == "closed" else None,
        exit_spot_price=D("100.9") if status == "closed" else None,
        exit_perp_price=D("101.1") if status == "closed" else None,
        exit_spot_fee_usd=D("0.1") if status == "closed" else None,
        exit_perp_fee_usd=D("0.1") if status == "closed" else None,
        exit_spot_slippage_usd=D("0.1") if status == "closed" else None,
        exit_perp_slippage_usd=D("0.1") if status == "closed" else None,
        exit_shadow_observed_at=(closed_at + timedelta(seconds=2)) if with_exit_shadow and closed_at else None,
        exit_shadow_spot_filled_quantity=D("1") if with_exit_shadow else None,
        exit_shadow_perp_filled_quantity=D("1") if with_exit_shadow else None,
        exit_shadow_spot_price=D("100.8") if with_exit_shadow else None,
        exit_shadow_perp_price=D("101.2") if with_exit_shadow else None,
        exit_shadow_spot_cost_usd=D("0.1") if with_exit_shadow else None,
        exit_shadow_perp_cost_usd=D("0.1") if with_exit_shadow else None,
        funding_pnl_usd=D("1") if status == "closed" else None,
        gross_pnl_usd=D("1") if status == "closed" else None,
        fees_usd=D("0.4") if status == "closed" else None,
        slippage_usd=D("0.4") if status == "closed" else None,
        net_pnl_usd=D("0.2") if status == "closed" else None,
        close_reason="horizon" if status == "closed" else None,
        metadata_json="{}",
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_missed_entry_shadow_is_invalidated_not_backfilled():
    db = db_session(); s = study(db); p = position(db, s.id)
    count = invalidate_stale_shadow_state(
        db,
        study_id=s.id,
        config=config(),
        now=p.opened_at + timedelta(minutes=5),
    )
    db.refresh(p)
    incident = db.scalar(select(ForwardStudyIncident).where(ForwardStudyIncident.study_id == s.id))
    assert count == 1
    assert p.status == "invalid"
    assert p.close_reason == "entry-shadow-window-missed"
    assert incident is not None and incident.data_integrity is True
    db.close()


def test_missed_exit_shadow_is_invalidated_not_backfilled():
    db = db_session(); s = study(db)
    closed = START + timedelta(days=1)
    p = position(db, s.id, status="closed", closed_at=closed)
    count = invalidate_stale_shadow_state(
        db,
        study_id=s.id,
        config=config(),
        now=closed + timedelta(minutes=5),
    )
    db.refresh(p)
    assert count == 1
    assert p.status == "invalid"
    assert p.close_reason == "exit-shadow-window-missed"
    db.close()


def test_closed_evidence_repair_uses_only_already_persisted_shadow_facts():
    db = db_session(); s = study(db)
    p = position(db, s.id, status="closed", closed_at=START + timedelta(days=1), with_exit_shadow=True)

    class FakeRunner:
        def _ensure_closed_evidence(self, db, position):
            trade = ForwardResearchService.record_trade(
                db,
                study_id=position.study_id,
                external_key=position.external_key,
                opened_at=position.opened_at,
                closed_at=position.closed_at,
                gross_pnl_usd=position.gross_pnl_usd,
                net_pnl_usd=position.net_pnl_usd,
                fees_usd=position.fees_usd,
                slippage_usd=position.slippage_usd,
                allocated_capital_usd=position.allocated_capital_usd,
                planned_loss_usd=position.planned_loss_usd,
                metadata={"repaired": True},
            )
            position.trade_record_id = trade.id
            db.commit()

    repaired = repair_closed_evidence(db, runner=FakeRunner(), study_id=s.id)
    db.refresh(p)
    trade = db.scalar(select(ForwardTradeRecord).where(ForwardTradeRecord.study_id == s.id))
    assert repaired == 1
    assert p.trade_record_id == trade.id
    assert trade is not None
    db.close()
