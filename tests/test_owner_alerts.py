import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import ForwardStudy, ForwardStudyIncident
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


def study(db: Session, *, external_id: str = "study-1") -> ForwardStudy:
    now = datetime.now(timezone.utc) - timedelta(days=1)
    row = ForwardStudy(
        external_id=external_id,
        strategy_version_id="strategy-version-1",
        experiment_id="experiment-1",
        family="funding",
        venue="test",
        instrument="TEST",
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

    assert NotificationDispatcher.queue_current_events(db) == 1
    assert NotificationDispatcher.queue_current_events(db) == 0
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

    # Repeating the same recommendation creates no new transition event.
    evaluation(db, external_id="run-3", recommendation="GREEN-1_CANDIDATE", evaluated_at=now + timedelta(seconds=1))
    assert AlertEventCollector.evaluation_events(db) == []


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
