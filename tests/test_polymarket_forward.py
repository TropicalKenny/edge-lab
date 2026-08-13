import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.models import Base, Strategy
from app.polymarket_forward import (
    PolymarketForwardConfigError,
    PolymarketForwardBootstrap,
    PolymarketStructuralForwardRunner,
    StructuralCandidate,
)
from app.polymarket_forward_operational import (
    OperationalPolymarketForwardBootstrap,
    OperationalPolymarketStructuralForwardRunner,
)
from app.services import HealthRegistry
from app.venues.polymarket import (
    FeeSchedule,
    LegExecution,
    MarketContext,
    StructuralOpportunity,
)

D = Decimal


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def settings(**overrides) -> Settings:
    values = {
        "polymarket_forward_shadow_delay_ms": 0,
        "polymarket_forward_operation_cost_usd": 0.10,
        "polymarket_forward_attempt_interval_seconds": 300,
        "polymarket_forward_max_attempts_per_cycle": 3,
        "polymarket_min_edge_bps": 10.0,
        "polymarket_max_shares_per_opportunity": 100.0,
        "polymarket_max_book_age_seconds": 10,
        "polymarket_forward_initial_capital_usd": 1000.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def market(now: datetime) -> MarketContext:
    return MarketContext(
        market_id="m1",
        condition_id="c1",
        question="Will X happen?",
        slug="will-x-happen",
        event_id="e1",
        event_slug="event",
        event_title="Event",
        yes_token_id="yes1",
        no_token_id="no1",
        outcome_labels=("Yes", "No"),
        active=True,
        closed=False,
        accepting_orders=True,
        enable_order_book=True,
        neg_risk=False,
        neg_risk_other=False,
        fees_enabled=False,
        fee_schedule=FeeSchedule(rate=D("0"), exponent=1, taker_only=True),
        resolution_source="official",
        description="test",
        group_item_title=None,
        end_date=now + timedelta(days=1),
        captured_at=now,
    )


def binary_candidate(now: datetime, *, kind="binary_complete_set") -> StructuralCandidate:
    m = market(now)
    legs = (
        LegExecution(
            market_id="m1",
            condition_id="c1",
            token_id="yes1",
            outcome="Yes",
            shares=D("10"),
            average_price=D("0.47"),
            notional=D("4.7"),
            fee=D("0"),
            total_cost=D("4.7"),
        ),
        LegExecution(
            market_id="m1",
            condition_id="c1",
            token_id="no1",
            outcome="No",
            shares=D("10"),
            average_price=D("0.48"),
            notional=D("4.8"),
            fee=D("0"),
            total_cost=D("4.8"),
        ),
    )
    opportunity = StructuralOpportunity(
        kind=kind,
        event_id="e1",
        condition_id="c1",
        quantity=D("10"),
        gross_cost=D("9.5"),
        total_fees=D("0"),
        total_cost=D("9.5"),
        payout=D("10"),
        net_profit=D("0.5"),
        roi_bps=D("526.315789"),
        eligible=True,
        reasons=(),
        legs=legs,
        captured_at=now,
    )
    return StructuralCandidate(opportunity=opportunity, markets={"m1": m})


class FakeClient:
    def __init__(self, *, now: datetime, yes_price="0.48", no_price="0.49", yes_size="20", no_size="20"):
        self.now = now
        self.yes_price = yes_price
        self.no_price = no_price
        self.yes_size = yes_size
        self.no_size = no_size
        self.info_calls = 0
        self.book_calls = 0

    async def get_clob_market_info(self, condition_id: str):
        self.info_calls += 1
        assert condition_id == "c1"
        return {
            "t": [{"t": "yes1", "o": "Yes"}, {"t": "no1", "o": "No"}],
            "fd": {"r": "0", "e": "1", "to": True},
            "nr": False,
        }

    async def get_books(self, token_ids: list[str]):
        self.book_calls += 1
        rows = []
        for token_id in token_ids:
            price = self.yes_price if token_id == "yes1" else self.no_price
            size = self.yes_size if token_id == "yes1" else self.no_size
            rows.append(
                {
                    "market": "c1",
                    "asset_id": token_id,
                    "timestamp": str(int(self.now.timestamp() * 1000)),
                    "hash": f"shadow-{token_id}",
                    "bids": [{"price": "0.40", "size": "100"}],
                    "asks": [{"price": price, "size": size}],
                    "min_order_size": "1",
                    "tick_size": "0.01",
                    "neg_risk": False,
                    "last_trade_price": "0.45",
                }
            )
        return rows


def attach_candidate(runner, candidate):
    calls = {"count": 0}

    async def discover(_config):
        calls["count"] += 1
        return [candidate]

    runner._discover_candidates = discover
    return calls


def test_bootstrap_is_idempotent_and_restores_missing_initial_nav():
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    db = db_session()
    cfg = settings()
    first = OperationalPolymarketForwardBootstrap.bootstrap(db, settings=cfg, now=now)
    second = OperationalPolymarketForwardBootstrap.bootstrap(db, settings=cfg, now=now + timedelta(minutes=1))
    assert first.id == second.id
    nav = db.scalar(select(ForwardNavObservation).where(ForwardNavObservation.study_id == first.id))
    assert nav is not None and D(nav.nav_usd) == D("1000")

    db.delete(nav)
    db.commit()
    repaired = OperationalPolymarketForwardBootstrap.bootstrap(db, settings=cfg)
    assert repaired.id == first.id
    nav = db.scalar(select(ForwardNavObservation).where(ForwardNavObservation.study_id == first.id))
    assert nav is not None and D(nav.nav_usd) == D("1000")
    db.close()


def test_bootstrap_rejects_config_drift_for_existing_external_id():
    now = datetime.now(timezone.utc) - timedelta(minutes=2)
    db = db_session()
    PolymarketForwardBootstrap.bootstrap(db, settings=settings(), now=now)
    with pytest.raises(PolymarketForwardConfigError, match="study_config"):
        PolymarketForwardBootstrap.bootstrap(
            db,
            settings=settings(polymarket_forward_operation_cost_usd=0.55),
        )
    db.close()


def test_delayed_full_basket_records_conservative_immediate_trade():
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    db = db_session()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=settings(),
        now=now - timedelta(minutes=2),
    )
    client = FakeClient(now=now)
    runner = OperationalPolymarketStructuralForwardRunner(
        client=client,
        health=HealthRegistry(),
    )
    attach_candidate(runner, binary_candidate(now))

    result = asyncio.run(runner.run_study_once(db, study=study, now=now))

    trade = db.scalar(select(ForwardTradeRecord).where(ForwardTradeRecord.study_id == study.id))
    executions = db.scalars(
        select(ForwardExecutionRecord).where(ForwardExecutionRecord.study_id == study.id)
    ).all()
    strategy = db.scalar(select(Strategy).where(Strategy.slug == "polymarket-immediate-structural"))
    assert result.action == "traded"
    assert trade is not None
    # Delayed executable basket: 10*0.48 + 10*0.49 = 9.70; fixed operation reserve = 0.10.
    assert D(trade.gross_pnl_usd) == D("0.30")
    assert D(trade.fees_usd) == D("0.10")
    assert D(trade.net_pnl_usd) == D("0.20")
    assert D(trade.allocated_capital_usd) == D("9.80")
    assert len(executions) == 2
    assert all(row.trade_id == trade.id for row in executions)
    assert all(D(row.shadow_filled_quantity) == D("10") for row in executions)
    assert json.loads(trade.metadata_json)["close_mechanic"] == "binary_ctf_merge"
    assert strategy is not None and strategy.status == "red"
    db.close()


def test_partial_delayed_depth_records_execution_evidence_but_no_trade():
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    db = db_session()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=settings(),
        now=now - timedelta(minutes=2),
    )
    client = FakeClient(now=now, yes_size="5")
    runner = OperationalPolymarketStructuralForwardRunner(client=client, health=HealthRegistry())
    attach_candidate(runner, binary_candidate(now))

    result = asyncio.run(runner.run_study_once(db, study=study, now=now))

    assert result.action == "observed"
    assert db.scalar(select(func.count()).select_from(ForwardTradeRecord)) == 0
    rows = db.scalars(select(ForwardExecutionRecord).order_by(ForwardExecutionRecord.external_key)).all()
    assert len(rows) == 2
    assert sorted(D(row.shadow_filled_quantity) for row in rows) == [D("5"), D("10")]
    db.close()


def test_operation_cost_reserve_can_remove_signal_before_shadow_calls():
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    db = db_session()
    cfg = settings(polymarket_forward_operation_cost_usd=0.60)
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=cfg,
        now=now - timedelta(minutes=2),
    )
    client = FakeClient(now=now)
    runner = OperationalPolymarketStructuralForwardRunner(client=client, health=HealthRegistry())
    attach_candidate(runner, binary_candidate(now))

    result = asyncio.run(runner.run_study_once(db, study=study, now=now))

    assert result.action == "no_entry"
    assert client.info_calls == 0 and client.book_calls == 0
    assert db.scalar(select(func.count()).select_from(ForwardExecutionRecord)) == 0
    db.close()


def test_resolution_dependent_negrisk_yes_is_not_an_immediate_forward_trade():
    cfg = PolymarketForwardBootstrap.bootstrap
    del cfg  # keep this test independent of database bootstrap
    config = settings()
    study_config = None
    candidate = binary_candidate(datetime.now(timezone.utc), kind="negrisk_yes_complete_set")
    from app.polymarket_forward import PolymarketForwardConfig

    frozen = PolymarketForwardConfig.from_settings(config)
    assert not PolymarketStructuralForwardRunner._signal_passes_cost_reserve(candidate.opportunity, frozen)
    assert study_config is None


def test_pre_study_book_times_cannot_enter_forward_evidence():
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    db = db_session()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=settings(),
        now=now - timedelta(seconds=10),
    )
    old = now - timedelta(minutes=5)
    client = FakeClient(now=now)
    runner = OperationalPolymarketStructuralForwardRunner(client=client, health=HealthRegistry())
    attach_candidate(runner, binary_candidate(old))

    result = asyncio.run(runner.run_study_once(db, study=study, now=now))

    assert result.action == "observed"
    assert db.scalar(select(func.count()).select_from(ForwardExecutionRecord)) == 0
    assert db.scalar(select(func.count()).select_from(ForwardTradeRecord)) == 0
    db.close()


def test_integrity_contamination_blocks_future_market_calls_permanently():
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    db = db_session()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=settings(),
        now=now - timedelta(minutes=2),
    )
    db.add(
        ForwardStudyIncident(
            study_id=study.id,
            external_key="seed-integrity",
            severity="error",
            code="TEST_INTEGRITY",
            message="seed contamination",
            data_integrity=True,
            resolved=True,
            opened_at=now - timedelta(minutes=1),
            resolved_at=now,
        )
    )
    db.commit()
    client = FakeClient(now=now)
    runner = OperationalPolymarketStructuralForwardRunner(client=client, health=HealthRegistry())
    calls = attach_candidate(runner, binary_candidate(now))

    results = asyncio.run(runner.run_active_studies(db, now=now))

    assert len(results) == 1 and results[0].action == "blocked"
    assert calls["count"] == 0
    assert client.info_calls == 0 and client.book_calls == 0
    db.close()
