import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import ForwardNavObservation
from app.models import Base
from app.polymarket_forward import (
    PolymarketForwardConfig,
    PolymarketForwardConfigError,
    StructuralCandidate,
)
from app.polymarket_forward_operational import (
    OperationalPolymarketForwardBootstrap,
    OperationalPolymarketStructuralForwardRunner,
)
from app.services import HealthRegistry
from app.venues.polymarket import FeeSchedule, LegExecution, MarketContext, StructuralOpportunity

D = Decimal


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def settings(**updates) -> Settings:
    base = Settings(
        _env_file=None,
        polymarket_forward_study_external_id="pm-hardening-v1",
        polymarket_forward_initial_capital_usd=1000,
        polymarket_forward_fee_buffer_pct=2,
        polymarket_forward_shadow_delay_ms=0,
        polymarket_forward_operation_cost_usd=0.25,
        polymarket_forward_planned_loss_pct=0.02,
        polymarket_forward_attempt_interval_seconds=300,
        polymarket_forward_max_attempts_per_cycle=3,
        polymarket_max_markets=50,
        polymarket_max_negrisk_events=8,
        polymarket_max_shares_per_opportunity=100,
        polymarket_min_edge_bps=10,
        polymarket_max_book_age_seconds=10,
    )
    return base.model_copy(update=updates)


def neg_market(now: datetime, index: int) -> MarketContext:
    return MarketContext(
        market_id=f"m{index}",
        condition_id=f"c{index}",
        question=f"Will outcome {index} win?",
        slug=f"outcome-{index}",
        event_id="neg-event",
        event_slug="neg-event",
        event_title="Who wins?",
        yes_token_id=f"y{index}",
        no_token_id=f"n{index}",
        outcome_labels=("Yes", "No"),
        active=True,
        closed=False,
        accepting_orders=True,
        enable_order_book=True,
        neg_risk=True,
        neg_risk_other=False,
        fees_enabled=False,
        fee_schedule=FeeSchedule(rate=D("0"), exponent=1, taker_only=True),
        resolution_source="official",
        description="Exactly one outcome wins.",
        group_item_title=f"Outcome {index}",
        end_date=now + timedelta(days=1),
        captured_at=now,
    )


def neg_candidate(now: datetime) -> StructuralCandidate:
    markets = {f"m{i}": neg_market(now, i) for i in range(3)}
    legs = tuple(
        LegExecution(
            market_id=f"m{i}",
            condition_id=f"c{i}",
            token_id=f"n{i}",
            outcome="No",
            shares=D("10"),
            average_price=D("0.60"),
            notional=D("6.00"),
            fee=D("0"),
            total_cost=D("6.00"),
        )
        for i in range(3)
    )
    opportunity = StructuralOpportunity(
        kind="negrisk_no_complete_set",
        event_id="neg-event",
        condition_id=None,
        quantity=D("10"),
        gross_cost=D("18.00"),
        total_fees=D("0"),
        total_cost=D("18.00"),
        payout=D("20.00"),
        net_profit=D("2.00"),
        roi_bps=D("1111.111111"),
        eligible=True,
        reasons=(),
        legs=legs,
        captured_at=now,
    )
    return StructuralCandidate(opportunity=opportunity, markets=markets)


def event_payload(*, changed=False, augmented=False, other=False):
    rows = []
    for i in range(3):
        market_id = "m-changed" if changed and i == 2 else f"m{i}"
        condition_id = "c-changed" if changed and i == 2 else f"c{i}"
        yes = "y-changed" if changed and i == 2 else f"y{i}"
        no = "n-changed" if changed and i == 2 else f"n{i}"
        rows.append(
            {
                "id": market_id,
                "conditionId": condition_id,
                "question": f"Will outcome {i} win?",
                "slug": market_id,
                "outcomes": ["Yes", "No"],
                "clobTokenIds": [yes, no],
                "active": True,
                "closed": False,
                "acceptingOrders": True,
                "enableOrderBook": True,
                "negRisk": True,
                "negRiskOther": other and i == 2,
                "groupItemTitle": "Other" if other and i == 2 else f"Outcome {i}",
                "feesEnabled": False,
            }
        )
    return {
        "id": "neg-event",
        "title": "Who wins?",
        "slug": "neg-event",
        "description": "Exactly one outcome wins.",
        "resolutionSource": "official",
        "negRisk": True,
        "negRiskAugmented": augmented,
        "markets": rows,
    }


class EventOnlyClient:
    def __init__(self, payload):
        self.payload = payload
        self.event_calls = 0

    async def get_event(self, event_id: str):
        self.event_calls += 1
        assert event_id == "neg-event"
        return self.payload

    def __getattr__(self, name):
        async def fail(*args, **kwargs):
            raise AssertionError(f"unexpected client method after failed event revalidation: {name}")

        return fail


def test_negrisk_operation_reserve_scales_with_conversion_and_merge_count():
    candidate = neg_candidate(datetime.now(timezone.utc) - timedelta(seconds=1))
    config = PolymarketForwardConfig.from_settings(settings())

    effective = OperationalPolymarketStructuralForwardRunner._effective_config(
        candidate.opportunity,
        config,
    )

    # Three-outcome No basket = one conversion + two merges = three structural actions.
    assert effective.operation_cost_usd == D("0.75")
    assert OperationalPolymarketStructuralForwardRunner._required_capital(
        candidate.opportunity,
        config,
    ) == D("18.75")


def test_negrisk_shadow_reprice_fails_closed_if_event_membership_changes():
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    candidate = neg_candidate(now)
    client = EventOnlyClient(event_payload(changed=True))
    runner = OperationalPolymarketStructuralForwardRunner(
        client=client,
        health=HealthRegistry(),
    )

    rows = asyncio.run(
        runner._shadow_reprice(candidate, PolymarketForwardConfig.from_settings(settings()))
    )

    assert client.event_calls == 1
    assert len(rows) == 3
    assert all(row.filled_quantity == 0 for row in rows)
    assert all(row.reason == "NEGRISK_EVENT_MEMBERSHIP_CHANGED" for row in rows)


@pytest.mark.parametrize(
    "payload,reason",
    [
        (event_payload(augmented=True), "NEGRISK_EVENT_BECAME_UNSAFE"),
        (event_payload(other=True), "NEGRISK_EVENT_BECAME_UNSAFE"),
    ],
)
def test_negrisk_shadow_reprice_fails_closed_if_event_becomes_unsafe(payload, reason):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    candidate = neg_candidate(now)
    runner = OperationalPolymarketStructuralForwardRunner(
        client=EventOnlyClient(payload),
        health=HealthRegistry(),
    )

    rows = asyncio.run(
        runner._shadow_reprice(candidate, PolymarketForwardConfig.from_settings(settings()))
    )

    assert all(row.filled_quantity == 0 for row in rows)
    assert all(row.reason == reason for row in rows)


def test_bootstrap_rejects_conflicting_initial_nav_instead_of_repairing_it():
    db = db_session()
    started = datetime.now(timezone.utc) - timedelta(minutes=2)
    cfg = settings()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=cfg,
        now=started,
    )
    nav = db.scalar(
        select(ForwardNavObservation).where(ForwardNavObservation.study_id == study.id)
    )
    assert nav is not None
    nav.nav_usd = D("999")
    db.commit()

    with pytest.raises(PolymarketForwardConfigError, match="initial NAV conflicts"):
        OperationalPolymarketForwardBootstrap.bootstrap(db, settings=cfg)

    db.close()
