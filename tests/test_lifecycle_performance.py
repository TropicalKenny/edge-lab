from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.forward_models import ForwardStudy
from app.lifecycle_models import LifecyclePerformanceSnapshot, LifecyclePolicyCycle
from app.lifecycle_performance import (
    ACCOUNTING_VERSION,
    LifecyclePerformanceService,
)
from app.lifecycle_research import POLICY_VERSION, LifecycleResearchService
from app.models import Base

D = Decimal


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def add_study(db: Session, now: datetime) -> ForwardStudy:
    study = ForwardStudy(
        external_id="m6h-performance-test-study",
        strategy_version_id="strategy-version-test",
        experiment_id="experiment-test",
        family="meme",
        venue="solana",
        instrument="PUMP_LAUNCH_BASELINE",
        status="active",
        initial_capital_usd=D("1000"),
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=now,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


def record_detailed(
    db: Session,
    study: ForwardStudy,
    *,
    at: datetime,
    value: str | None,
    momentum: str = "0.2",
    reentry_output_amount: int = 800_000,
):
    mark_available = value is not None
    current = D(value) if value is not None else None
    observation = LifecycleResearchService.record_observation(
        db,
        study_id=study.id,
        position_key="launch-signature-performance-1",
        asset_id="mint-performance-1",
        venue="solana",
        baseline_state="invested",
        observed_at=at,
        baseline_entry_at=study.started_at,
        baseline_exit_at=None,
        baseline_entry_value_usd=D("25"),
        baseline_exit_value_usd=None,
        current_value_usd=current,
        mark_quote_available=mark_available,
        mark_price_impact_pct=D("0.01") if mark_available else None,
        reentry_quote_available=mark_available,
        reentry_price_impact_pct=D("0.01") if mark_available else None,
        liquidity_usd=D("90000"),
        baseline_entry_liquidity_usd=D("100000"),
        momentum_score=D(momentum),
        sell_ratio_5m=D("0.4"),
        volume_acceleration=D("1.1"),
        security_clean=True,
        mark_input_amount_atomic=1_000_000 if mark_available else None,
        mark_output_amount_atomic=(int(current * D("1000000")) if current is not None else None),
        mark_input_value_usd=(current + D("1") if current is not None else None),
        mark_output_value_usd=current,
        reentry_input_amount_atomic=25_000_000 if mark_available else None,
        reentry_output_amount_atomic=(reentry_output_amount if mark_available else None),
        reentry_input_value_usd=D("25") if mark_available else None,
        reentry_output_value_usd=D("24.5") if mark_available else None,
        metadata={"quote_only": True, "can_execute": False},
    )
    LifecycleResearchService.evaluate_observation(db, observation)
    LifecyclePerformanceService.account_observation(db, observation)
    return observation


def snapshot_for(
    db: Session,
    observation_id: str,
    policy_name: str,
) -> LifecyclePerformanceSnapshot:
    row = db.scalar(
        select(LifecyclePerformanceSnapshot).where(
            LifecyclePerformanceSnapshot.observation_id == observation_id,
            LifecyclePerformanceSnapshot.policy_name == policy_name,
            LifecyclePerformanceSnapshot.accounting_version == ACCOUNTING_VERSION,
        )
    )
    assert row is not None
    return row


def test_performance_accounts_complete_sell_wait_reentry_cycle_after_costs():
    db = db_session()
    now = datetime.now(UTC) - timedelta(hours=2)
    study = add_study(db, now)

    record_detailed(db, study, at=now, value="25")
    high = record_detailed(db, study, at=now + timedelta(minutes=5), value="38")
    sold = snapshot_for(db, high.id, "tp30-rebuy15")
    assert sold.state_after == "cash"
    assert D(sold.net_value_usd) == D("37.914")
    assert D(sold.hold_value_usd) == D("37.914")
    assert D(sold.transaction_cost_usd) == D("1.086")
    assert sold.complete is True

    pullback = record_detailed(db, study, at=now + timedelta(minutes=10), value="30")
    reentered = snapshot_for(db, pullback.id, "tp30-rebuy15")
    assert reentered.state_after == "invested"
    assert reentered.round_trip_count == 1
    assert D(reentered.token_units) > D("1")
    assert D(reentered.transaction_cost_usd) > D("0.8")
    assert reentered.complete is True

    loss = record_detailed(db, study, at=now + timedelta(minutes=15), value="15")
    abandoned = snapshot_for(db, loss.id, "tp30-rebuy15")
    assert abandoned.state_after == "abandoned"
    assert abandoned.failed_reentry_count == 1
    assert D(abandoned.net_return_pct) < D("0")
    assert D(abandoned.excess_return_pct) > D("0")
    assert D(abandoned.downside_avoided_pct) > D("0")

    cycles = db.scalars(
        select(LifecyclePolicyCycle)
        .where(
            LifecyclePolicyCycle.study_id == study.id,
            LifecyclePolicyCycle.policy_name == "tp30-rebuy15",
        )
        .order_by(LifecyclePolicyCycle.cycle_index.asc())
    ).all()
    assert [row.cycle_index for row in cycles] == [0, 1]
    assert cycles[0].entered_via == "BASELINE"
    assert cycles[1].entered_via == "REENTER"
    assert cycles[1].failed_reentry is True
    assert all(row.exit_decision_id for row in cycles)

    assert LifecyclePerformanceService.account_observation(db, loss) == 0
    assert (
        db.scalar(
            select(LifecyclePerformanceSnapshot).where(
                LifecyclePerformanceSnapshot.observation_id == loss.id,
                LifecyclePerformanceSnapshot.policy_name == "tp30-rebuy15",
            )
        )
        is not None
    )


def test_missing_executable_mark_never_carries_forward_an_invented_value():
    db = db_session()
    now = datetime.now(UTC) - timedelta(hours=1)
    study = add_study(db, now)

    missing = record_detailed(db, study, at=now, value=None)
    row = snapshot_for(db, missing.id, "tp30-rebuy15")
    assert row.state_after == "invested"
    assert row.net_value_usd is None
    assert row.hold_value_usd is None
    assert row.complete is False
    assert D(row.token_units) == D("1")
    assert D(row.cumulative_cost_usd) == D("0")


def test_cash_recovery_is_counted_once_without_changing_the_policy_decision():
    db = db_session()
    now = datetime.now(UTC) - timedelta(hours=2)
    study = add_study(db, now)

    record_detailed(db, study, at=now, value="25")
    record_detailed(db, study, at=now + timedelta(minutes=5), value="38")
    waiting = record_detailed(
        db,
        study,
        at=now + timedelta(minutes=10),
        value="30",
        momentum="-0.2",
    )
    assert snapshot_for(db, waiting.id, "tp30-rebuy15").state_after == "cash"

    recovered = record_detailed(db, study, at=now + timedelta(minutes=15), value="40")
    recovered_row = snapshot_for(db, recovered.id, "tp30-rebuy15")
    assert recovered_row.state_after == "cash"
    assert recovered_row.missed_recovery_count == 1
    assert recovered_row.cash_interval_missed_recovery is True

    later = record_detailed(db, study, at=now + timedelta(minutes=20), value="42")
    later_row = snapshot_for(db, later.id, "tp30-rebuy15")
    assert later_row.missed_recovery_count == 1


def test_small_sample_summary_refuses_policy_promotion_or_ranking():
    db = db_session()
    now = datetime.now(UTC) - timedelta(hours=1)
    study = add_study(db, now)
    record_detailed(db, study, at=now, value="25")
    record_detailed(db, study, at=now + timedelta(minutes=5), value="38")

    summary = LifecyclePerformanceService.summarize_policy(
        db,
        study_id=study.id,
        policy_name="tp30-rebuy15",
        policy_version=POLICY_VERSION,
    )
    assert summary.position_count == 1
    assert summary.complete_position_count == 1
    assert summary.completed_cycle_count == 1
    assert summary.mean_excess_return_pct is not None
    assert summary.sample_sufficient is False
    assert summary.selection_status == "INSUFFICIENT_SAMPLE"
    assert summary.can_promote is False
