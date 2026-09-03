import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.models import Base
from app.notification_models import NotificationDelivery
from app.notifications import (
    AlertEventCollector,
    NotificationDispatcher,
    NotificationRepository,
    TelegramSender,
)


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def study(
    db: Session,
    *,
    external_id: str = "study-1",
    venue: str = "test",
    instrument: str = "TEST",
) -> ForwardStudy:
    now = datetime.now(timezone.utc) - timedelta(days=1)
    row = ForwardStudy(
        external_id=external_id,
        strategy_version_id="strategy-version-1",
        experiment_id="experiment-1",
        family="funding",
        venue=venue,
        instrument=instrument,
        status="active",
        initial_capital_usd=Decimal("1000"),
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def evaluation(
    db: Session,
    *,
    external_id: str,
    recommendation: str,
    evaluated_at: datetime,
) -> StrategyEvaluationRun:
    row = StrategyEvaluationRun(
        external_run_id=external_id,
        strategy_version_id="strategy-version-1",
        strategy_slug="test-strategy",
        strategy_version="v1",
        family="funding",
        recommendation=recommendation,
        forward_started_at=evaluated_at - timedelta(days=30),
        evaluated_at=evaluated_at,
        forward_days=30,
        trade_count=12,
        forecast_count=0,
        execution_observation_count=12,
        net_pnl_usd=Decimal("12.5"),
        stressed_net_pnl_usd=Decimal("8.0"),
        max_drawdown_pct=Decimal("0.02"),
        profit_factor=Decimal("1.5"),
        brier_score=None,
        calibration_error=None,
        policy_json="{}",
        metrics_json="{}",
        reasons_json=json.dumps(["INSUFFICIENT_FORWARD_DAYS"]),
        input_json="{}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_critical_incident_is_queued_once_and_never_changes_study():
    db = db_session()
    s = study(db)
    opened = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.add(
        ForwardStudyIncident(
            study_id=s.id,
            external_key="incident-1",
            severity="critical",
            code="DATA_STALE",
            message="market data stale",
            data_integrity=False,
            resolved=False,
            opened_at=opened,
        )
    )
    db.commit()

    assert NotificationDispatcher.queue_current_events(db, heartbeat_hour_utc=23) == 1
    assert NotificationDispatcher.queue_current_events(db, heartbeat_hour_utc=23) == 0
    deliveries = list(db.scalars(select(NotificationDelivery)).all())
    assert len(deliveries) == 1
    assert deliveries[0].status == "pending"
    assert db.get(ForwardStudy, s.id).status == "active"


def test_only_latest_evaluation_state_transition_is_alerted():
    db = db_session()
    now = datetime.now(timezone.utc)
    evaluation(db, external_id="run-1", recommendation="AMBER", evaluated_at=now - timedelta(days=1))
    latest = evaluation(db, external_id="run-2", recommendation="GREEN-1_CANDIDATE", evaluated_at=now)

    events = AlertEventCollector.evaluation_events(db)
    assert len(events) == 1
    assert events[0].metadata["evaluation_id"] == latest.id
    assert "AMBER → GREEN-1_CANDIDATE" in events[0].text
    assert "cannot enable live trading" in events[0].text

    evaluation(db, external_id="run-3", recommendation="GREEN-1_CANDIDATE", evaluated_at=now + timedelta(seconds=1))
    assert AlertEventCollector.evaluation_events(db) == []


def test_solana_open_and_trade_close_events_are_idempotent_and_paper_labeled():
    db = db_session()
    s = study(db, external_id="solana-study", venue="solana", instrument="PUMP_LAUNCH_BASELINE")
    opened = datetime.now(timezone.utc) - timedelta(minutes=40)
    execution = ForwardExecutionRecord(
        study_id=s.id,
        trade_id=None,
        external_key="solana-entry:signature-1",
        observed_at=opened,
        side="buy",
        intended_quantity=Decimal("25000000"),
        paper_filled_quantity=Decimal("25000000"),
        shadow_filled_quantity=Decimal("25000000"),
        paper_average_price=Decimal("0.000012"),
        shadow_average_price=Decimal("0.000013"),
        paper_cost_usd=Decimal("0.10"),
        shadow_cost_usd=Decimal("0.12"),
        metadata_json=json.dumps(
            {
                "phase": "entry",
                "status": "open",
                "mint": "Mint111",
                "opened_at": opened.isoformat(),
                "hold_until": (opened + timedelta(minutes=30)).isoformat(),
                "allocated_capital_usd": "25",
            }
        ),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    trade = ForwardTradeRecord(
        study_id=s.id,
        external_key="solana-trade:signature-1",
        opened_at=opened,
        closed_at=opened + timedelta(minutes=30),
        gross_pnl_usd=Decimal("3.00"),
        net_pnl_usd=Decimal("2.50"),
        fees_usd=Decimal("0.20"),
        slippage_usd=Decimal("0.30"),
        allocated_capital_usd=Decimal("25"),
        planned_loss_usd=Decimal("25"),
        metadata_json=json.dumps({"mint": "Mint111", "exit_reason": "HOLD_COMPLETE"}),
    )
    db.add(trade)
    db.commit()

    events = AlertEventCollector.trade_events(db)
    assert len(events) == 2
    opened_event = next(event for event in events if event.event_type == "paper_trade_open")
    closed_event = next(event for event in events if event.event_type == "paper_trade_close")
    assert opened_event.event_key == f"trade-open:solana:{execution.id}"
    assert "PAPER/SHADOW TRADE OPENED" in opened_event.text
    assert "no real money" in opened_event.text
    assert closed_event.event_key == f"trade-close:{trade.id}"
    assert "Net P&L: $2.50 (10.00%)" in closed_event.text
    assert "HOLD_COMPLETE" in closed_event.text

    now = datetime.now(timezone.utc).replace(hour=10)
    assert NotificationDispatcher.queue_current_events(db, now=now, heartbeat_hour_utc=18) == 2
    assert NotificationDispatcher.queue_current_events(db, now=now, heartbeat_hour_utc=18) == 0


def test_rejected_solana_entry_does_not_create_trade_open_alert():
    db = db_session()
    s = study(db, external_id="solana-rejected", venue="solana", instrument="PUMP_LAUNCH_BASELINE")
    db.add(
        ForwardExecutionRecord(
            study_id=s.id,
            trade_id=None,
            external_key="solana-entry:rejected-signature",
            observed_at=datetime.now(timezone.utc),
            side="buy",
            intended_quantity=Decimal("25000000"),
            paper_filled_quantity=Decimal("25000000"),
            shadow_filled_quantity=Decimal("0"),
            paper_average_price=Decimal("0.000012"),
            shadow_average_price=None,
            paper_cost_usd=Decimal("0.10"),
            shadow_cost_usd=Decimal("0"),
            metadata_json=json.dumps(
                {
                    "phase": "entry",
                    "status": "rejected",
                    "reason": "SHADOW_ENTRY_QUOTE_INVALID",
                }
            ),
        )
    )
    db.commit()
    assert AlertEventCollector.trade_events(db) == []


def test_daily_heartbeat_is_once_per_utc_day_and_waits_until_configured_hour():
    db = db_session()
    s = study(db, external_id="heartbeat-study", venue="solana", instrument="PUMP_LAUNCH_BASELINE")
    now = datetime(2026, 9, 3, 18, 5, tzinfo=timezone.utc)
    db.add(
        ForwardNavObservation(
            study_id=s.id,
            observed_at=now - timedelta(minutes=2),
            nav_usd=Decimal("1005.25"),
            source="test",
        )
    )
    db.commit()

    assert AlertEventCollector.heartbeat_events(
        db,
        now=now.replace(hour=17),
        heartbeat_hour_utc=18,
    ) == []

    events = AlertEventCollector.heartbeat_events(db, now=now, heartbeat_hour_utc=18)
    assert len(events) == 1
    assert events[0].event_key == "daily-heartbeat:2026-09-03"
    assert "Combined simulated NAV: $1,005.25" in events[0].text
    assert "No paper/shadow trades closed today" in events[0].text
    assert "Use /research" in events[0].text

    NotificationRepository.queue(db, events[0], now=now)
    assert AlertEventCollector.heartbeat_events(db, now=now + timedelta(minutes=5), heartbeat_hour_utc=18) == []


def test_telegram_send_success_marks_delivery_sent():
    db = db_session()
    event = AlertEventCollector.evaluation_events(db)
    assert event == []
    from app.notifications import NotificationEvent

    NotificationRepository.queue(
        db,
        NotificationEvent(
            event_key="test:1",
            event_type="test",
            severity="info",
            text="test message",
            metadata={},
        ),
    )

    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["chat_id"] == "123"
            assert body["text"] == "test message"
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        async with TelegramSender(
            bot_token="123:test-token",
            chat_id="123",
            transport=httpx.MockTransport(handler),
        ) as sender:
            return await NotificationDispatcher.dispatch_due(db, sender=sender)

    assert asyncio.run(run()) == (1, 0)
    row = db.scalar(select(NotificationDelivery))
    assert row is not None
    assert row.status == "sent"
    assert row.attempt_count == 1
    assert row.sent_at is not None


def test_telegram_failure_retries_without_touching_research_state():
    db = db_session()
    s = study(db)
    from app.notifications import NotificationEvent

    NotificationRepository.queue(
        db,
        NotificationEvent(
            event_key="test:retry",
            event_type="test",
            severity="warning",
            text="retry me",
            metadata={},
        ),
    )
    now = datetime.now(timezone.utc)

    async def run():
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"ok": False})

        async with TelegramSender(
            bot_token="123:test-token",
            chat_id="123",
            transport=httpx.MockTransport(handler),
        ) as sender:
            return await NotificationDispatcher.dispatch_due(
                db,
                sender=sender,
                now=now,
                max_attempts=3,
                retry_base_seconds=60,
                retry_max_seconds=600,
            )

    assert asyncio.run(run()) == (0, 1)
    row = db.scalar(select(NotificationDelivery))
    assert row is not None
    assert row.status == "retry"
    assert row.attempt_count == 1
    assert aware(row.next_attempt_at) >= now + timedelta(seconds=60)
    assert db.get(ForwardStudy, s.id).status == "active"
