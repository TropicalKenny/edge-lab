from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.forward_models import ForwardStudy
from app.lifecycle_models import (
    LifecycleDecisionOutcome,
    LifecyclePolicyDecision,
    LifecyclePolicyState,
)
from app.lifecycle_research import (
    CANDIDATE_POLICIES,
    POLICY_VERSION,
    LifecycleDecisionEngine,
    LifecycleResearchService,
    LifecycleSnapshot,
)
from app.models import Base

D = Decimal


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def snapshot(**overrides) -> LifecycleSnapshot:
    values = {
        "state": "invested",
        "observed_at": datetime.now(timezone.utc),
        "current_value_usd": D("30"),
        "virtual_entry_value_usd": D("25"),
        "virtual_exit_value_usd": None,
        "virtual_exit_at": None,
        "peak_return_pct": D("0.20"),
        "mark_quote_available": True,
        "mark_price_impact_pct": D("0.01"),
        "reentry_quote_available": True,
        "reentry_price_impact_pct": D("0.01"),
        "liquidity_usd": D("100000"),
        "baseline_entry_liquidity_usd": D("100000"),
        "momentum_score": D("0.2"),
        "volume_acceleration": D("1.1"),
        "sell_ratio_5m": D("0.4"),
        "security_clean": True,
    }
    values.update(overrides)
    return LifecycleSnapshot(**values)


def add_study(db: Session, now: datetime) -> ForwardStudy:
    study = ForwardStudy(
        external_id="m6h-test-study",
        strategy_version_id="strategy-version-test",
        experiment_id="experiment-test",
        family="meme",
        venue="solana",
        instrument="PUMP_LAUNCH_BASELINE",
        status="active",
        initial_capital_usd=D("1000"),
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=now - timedelta(hours=2),
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


def record(
    db: Session,
    study: ForwardStudy,
    *,
    at: datetime,
    value: str,
    baseline_state: str = "invested",
    momentum: str = "0.2",
    sell_ratio: str = "0.4",
):
    return LifecycleResearchService.record_observation(
        db,
        study_id=study.id,
        position_key="launch-signature-1",
        asset_id="mint-1",
        venue="solana",
        baseline_state=baseline_state,
        observed_at=at,
        baseline_entry_at=study.started_at,
        baseline_exit_at=None,
        baseline_entry_value_usd=D("25"),
        baseline_exit_value_usd=None,
        current_value_usd=D(value),
        mark_quote_available=True,
        mark_price_impact_pct=D("0.01"),
        reentry_quote_available=True,
        reentry_price_impact_pct=D("0.01"),
        liquidity_usd=D("90000"),
        baseline_entry_liquidity_usd=D("100000"),
        momentum_score=D(momentum),
        sell_ratio_5m=D(sell_ratio),
        volume_acceleration=D("1.1"),
        security_clean=True,
        metadata={"lookahead_used": False},
    )


def test_invested_decisions_hold_take_profit_and_abandon():
    policy = CANDIDATE_POLICIES[0]
    assert LifecycleDecisionEngine.evaluate(snapshot(), policy).action == "HOLD"
    assert (
        LifecycleDecisionEngine.evaluate(
            snapshot(current_value_usd=D("33")), policy
        ).action
        == "TAKE_PROFIT"
    )
    assert (
        LifecycleDecisionEngine.evaluate(
            snapshot(current_value_usd=D("15")), policy
        ).action
        == "ABANDON"
    )


def test_reentry_requires_pullback_and_structure_confirmation():
    policy = CANDIDATE_POLICIES[0]
    sold_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    good = snapshot(
        state="cash",
        current_value_usd=D("28"),
        virtual_entry_value_usd=D("25"),
        virtual_exit_value_usd=D("35"),
        virtual_exit_at=sold_at,
    )
    assert LifecycleDecisionEngine.evaluate(good, policy).action == "REENTER"
    assert (
        LifecycleDecisionEngine.evaluate(
            snapshot(
                state="cash",
                current_value_usd=D("33"),
                virtual_exit_value_usd=D("35"),
                virtual_exit_at=sold_at,
            ),
            policy,
        ).action
        == "WAIT"
    )
    assert (
        LifecycleDecisionEngine.evaluate(
            snapshot(
                state="cash",
                current_value_usd=D("28"),
                virtual_exit_value_usd=D("35"),
                virtual_exit_at=sold_at,
                sell_ratio_5m=D("0.80"),
            ),
            policy,
        ).action
        == "WAIT"
    )
    assert (
        LifecycleDecisionEngine.evaluate(
            snapshot(
                state="cash",
                current_value_usd=D("28"),
                virtual_exit_value_usd=D("35"),
                virtual_exit_at=sold_at,
                security_clean=None,
            ),
            policy,
        ).action
        == "WAIT"
    )
    assert (
        LifecycleDecisionEngine.evaluate(
            snapshot(
                state="cash",
                current_value_usd=D("28"),
                virtual_exit_value_usd=D("35"),
                virtual_exit_at=sold_at,
                volume_acceleration=D("0.8"),
            ),
            policy,
        ).action
        == "WAIT"
    )


def test_missing_quotes_never_invent_an_executable_action():
    policy = CANDIDATE_POLICIES[0]
    invested = LifecycleDecisionEngine.evaluate(
        snapshot(mark_quote_available=False), policy
    )
    cash = LifecycleDecisionEngine.evaluate(
        snapshot(
            state="cash",
            virtual_exit_value_usd=D("35"),
            virtual_exit_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            reentry_quote_available=False,
        ),
        policy,
    )
    assert invested.action == "HOLD"
    assert cash.action == "WAIT"


def test_candidate_policy_state_can_sell_wait_and_reenter_without_mutating_baseline():
    db = db_session()
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    study = add_study(db, now)

    first = record(db, study, at=now, value="25")
    LifecycleResearchService.evaluate_observation(db, first)

    high = record(db, study, at=now + timedelta(minutes=5), value="38")
    high_decisions = LifecycleResearchService.evaluate_observation(db, high)
    actions = {row.policy_name: row.action for row in high_decisions}
    assert actions["tp30-rebuy15"] == "TAKE_PROFIT"
    assert actions["tp50-rebuy20"] == "TAKE_PROFIT"
    assert actions["tp80-rebuy25"] == "HOLD"

    pullback = record(db, study, at=now + timedelta(minutes=10), value="30")
    pullback_decisions = LifecycleResearchService.evaluate_observation(db, pullback)
    actions = {row.policy_name: row.action for row in pullback_decisions}
    assert actions["tp30-rebuy15"] == "REENTER"
    assert actions["tp50-rebuy20"] == "REENTER"
    assert actions["tp80-rebuy25"] == "HOLD"

    states = db.scalars(select(LifecyclePolicyState)).all()
    by_name = {row.policy_name: row for row in states}
    assert by_name["tp30-rebuy15"].state == "invested"
    assert by_name["tp30-rebuy15"].cycle_count == 1
    assert by_name["tp50-rebuy20"].state == "invested"
    assert by_name["tp80-rebuy25"].state == "invested"

    decisions = db.scalars(select(LifecyclePolicyDecision)).all()
    assert decisions
    assert all(row.can_execute is False for row in decisions)
    assert high.baseline_state == "invested"
    assert pullback.baseline_state == "invested"


def test_counterfactual_outcomes_are_resolved_only_after_future_observations_exist():
    db = db_session()
    now = datetime.now(timezone.utc) - timedelta(hours=2)
    study = add_study(db, now)
    origin = record(db, study, at=now, value="35")
    decisions = LifecycleResearchService.evaluate_observation(db, origin)
    assert decisions
    assert (
        LifecycleResearchService.resolve_outcomes(
            db, now=now + timedelta(minutes=31)
        )
        == 0
    )

    record(db, study, at=now + timedelta(minutes=30), value="28")
    created = LifecycleResearchService.resolve_outcomes(
        db, now=now + timedelta(minutes=31)
    )
    assert created > 0
    outcomes = db.scalars(select(LifecycleDecisionOutcome)).all()
    assert outcomes
    assert all(row.future_value_usd == D("28") for row in outcomes)
    assert all(row.horizon_minutes in {5, 15, 30} for row in outcomes)
    assert all(row.decision_id in {decision.id for decision in decisions} for row in outcomes)


def test_policy_version_is_frozen_for_journal_rows():
    assert POLICY_VERSION == "m6h-v1"
    assert {policy.name for policy in CANDIDATE_POLICIES} == {
        "tp30-rebuy15",
        "tp50-rebuy20",
        "tp80-rebuy25",
    }
