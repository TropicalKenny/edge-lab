from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import ForwardStudy, ForwardStudyIncident
from app.notification_models import NotificationDelivery

CHANNEL_TELEGRAM = "telegram"
ZERO = Decimal("0")


class NotificationError(RuntimeError):
    pass


class NotificationIntegrityError(NotificationError):
    pass


class NotificationSendError(NotificationError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _money(value: Decimal) -> str:
    return f"${Decimal(value):,.2f}"


@dataclass(frozen=True)
class NotificationEvent:
    event_key: str
    event_type: str
    severity: str
    text: str
    metadata: dict[str, Any]

    def payload_json(self) -> str:
        return _json({"text": self.text, "metadata": self.metadata})


class NotificationRepository:
    @staticmethod
    def queue(db: Session, event: NotificationEvent, *, now: datetime | None = None) -> NotificationDelivery:
        now = _aware(now or datetime.now(timezone.utc))
        existing = db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.channel == CHANNEL_TELEGRAM,
                NotificationDelivery.event_key == event.event_key,
            )
        )
        payload = event.payload_json()
        if existing is not None:
            if (
                existing.event_type != event.event_type
                or existing.severity != event.severity
                or existing.payload_json != payload
            ):
                raise NotificationIntegrityError(f"conflicting notification event: {event.event_key}")
            return existing
        row = NotificationDelivery(
            channel=CHANNEL_TELEGRAM,
            event_key=event.event_key,
            event_type=event.event_type,
            severity=event.severity,
            payload_json=payload,
            status="pending",
            attempt_count=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def due(db: Session, *, now: datetime, max_attempts: int, limit: int) -> list[NotificationDelivery]:
        return list(
            db.scalars(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.channel == CHANNEL_TELEGRAM,
                    NotificationDelivery.status.in_(["pending", "retry"]),
                    NotificationDelivery.attempt_count < max_attempts,
                    NotificationDelivery.next_attempt_at <= now,
                )
                .order_by(NotificationDelivery.created_at.asc())
                .limit(limit)
            ).all()
        )

    @staticmethod
    def mark_sent(db: Session, row: NotificationDelivery, *, now: datetime) -> None:
        row.status = "sent"
        row.attempt_count += 1
        row.sent_at = now
        row.last_error = None
        row.updated_at = now
        db.commit()

    @staticmethod
    def mark_failed(
        db: Session,
        row: NotificationDelivery,
        *,
        now: datetime,
        error: str,
        max_attempts: int,
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> None:
        row.attempt_count += 1
        row.last_error = error[:1000]
        row.updated_at = now
        if row.attempt_count >= max_attempts:
            row.status = "dead"
            row.next_attempt_at = now
        else:
            row.status = "retry"
            delay = min(retry_max_seconds, retry_base_seconds * (2 ** max(0, row.attempt_count - 1)))
            row.next_attempt_at = now + timedelta(seconds=delay)
        db.commit()


class AlertEventCollector:
    @staticmethod
    def incident_events(db: Session) -> list[NotificationEvent]:
        incidents = list(
            db.scalars(
                select(ForwardStudyIncident)
                .where(
                    (ForwardStudyIncident.data_integrity.is_(True))
                    | (ForwardStudyIncident.severity == "critical")
                )
                .order_by(ForwardStudyIncident.opened_at.asc())
            ).all()
        )
        events: list[NotificationEvent] = []
        for incident in incidents:
            study = db.get(ForwardStudy, incident.study_id)
            study_name = study.external_id if study is not None else incident.study_id
            integrity = "DATA INTEGRITY" if incident.data_integrity else "CRITICAL"
            text = (
                f"EDGE LAB — {integrity}\n"
                f"Study: {study_name}\n"
                f"Code: {incident.code}\n"
                f"Message: {incident.message}\n"
                f"Opened: {_aware(incident.opened_at).isoformat()}\n"
                "Action: review the dashboard; no live capital is enabled."
            )
            events.append(
                NotificationEvent(
                    event_key=f"incident-open:{incident.id}",
                    event_type="study_incident",
                    severity="critical" if incident.severity == "critical" else "integrity",
                    text=text,
                    metadata={
                        "incident_id": incident.id,
                        "study_id": incident.study_id,
                        "study_external_id": study_name,
                        "code": incident.code,
                        "data_integrity": bool(incident.data_integrity),
                    },
                )
            )
        return events

    @staticmethod
    def evaluation_events(db: Session) -> list[NotificationEvent]:
        version_ids = list(db.scalars(select(StrategyEvaluationRun.strategy_version_id).distinct()).all())
        events: list[NotificationEvent] = []
        for version_id in version_ids:
            runs = list(
                db.scalars(
                    select(StrategyEvaluationRun)
                    .where(StrategyEvaluationRun.strategy_version_id == version_id)
                    .order_by(StrategyEvaluationRun.evaluated_at.desc(), StrategyEvaluationRun.created_at.desc())
                    .limit(2)
                ).all()
            )
            if not runs:
                continue
            latest = runs[0]
            previous = runs[1] if len(runs) > 1 else None
            if previous is not None and previous.recommendation == latest.recommendation:
                continue
            try:
                reasons = json.loads(latest.reasons_json)
            except (json.JSONDecodeError, TypeError):
                reasons = []
            reason_text = ", ".join(str(item) for item in reasons[:5]) if isinstance(reasons, list) else ""
            transition = f"{previous.recommendation} → {latest.recommendation}" if previous else f"initial → {latest.recommendation}"
            text = (
                "EDGE LAB — EVIDENCE STATE CHANGE\n"
                f"Strategy: {latest.strategy_slug} {latest.strategy_version}\n"
                f"State: {transition}\n"
                f"Forward days: {latest.forward_days}\n"
                f"Trades: {latest.trade_count}; shadow observations: {latest.execution_observation_count}\n"
                f"Net research P&L: {_money(latest.net_pnl_usd)}\n"
                f"Reasons: {reason_text or 'none'}\n"
                "Note: GREEN-1_CANDIDATE is evidence only and cannot enable live trading."
            )
            events.append(
                NotificationEvent(
                    event_key=f"evaluation-state:{latest.id}",
                    event_type="evaluation_state_change",
                    severity="info" if latest.recommendation != "RED" else "warning",
                    text=text,
                    metadata={
                        "evaluation_id": latest.id,
                        "strategy_version_id": version_id,
                        "recommendation": latest.recommendation,
                        "previous_recommendation": previous.recommendation if previous else None,
                    },
                )
            )
        return events

    @classmethod
    def collect(cls, db: Session) -> list[NotificationEvent]:
        return cls.incident_events(db) + cls.evaluation_events(db)


class TelegramSender:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not bot_token.strip() or not chat_id.strip():
            raise ValueError("Telegram bot token and chat id are required")
        self.chat_id = chat_id
        self._http = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def send(self, text: str) -> None:
        if not text.strip():
            raise NotificationSendError("notification text is empty")
        try:
            response = await self._http.post(
                self._url,
                json={
                    "chat_id": self.chat_id,
                    "text": text[:4096],
                    "protect_content": True,
                },
            )
        except httpx.RequestError as exc:
            raise NotificationSendError(f"Telegram request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise NotificationSendError(f"Telegram HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NotificationSendError("Telegram returned invalid JSON") from exc
        if payload.get("ok") is not True:
            raise NotificationSendError("Telegram rejected sendMessage")


class NotificationDispatcher:
    @staticmethod
    def queue_current_events(db: Session, *, now: datetime | None = None) -> int:
        queued = 0
        for event in AlertEventCollector.collect(db):
            before = db.scalar(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.channel == CHANNEL_TELEGRAM,
                    NotificationDelivery.event_key == event.event_key,
                )
            )
            NotificationRepository.queue(db, event, now=now)
            if before is None:
                queued += 1
        return queued

    @staticmethod
    async def dispatch_due(
        db: Session,
        *,
        sender: TelegramSender,
        now: datetime | None = None,
        max_attempts: int = 6,
        retry_base_seconds: int = 60,
        retry_max_seconds: int = 3600,
        batch_size: int = 20,
    ) -> tuple[int, int]:
        now = _aware(now or datetime.now(timezone.utc))
        sent = failed = 0
        rows = NotificationRepository.due(db, now=now, max_attempts=max_attempts, limit=batch_size)
        for row in rows:
            try:
                payload = json.loads(row.payload_json)
                text = str(payload["text"])
                await sender.send(text)
            except Exception as exc:
                db.rollback()
                fresh = db.get(NotificationDelivery, row.id)
                if fresh is not None:
                    NotificationRepository.mark_failed(
                        db,
                        fresh,
                        now=now,
                        error=f"{type(exc).__name__}: {str(exc)[:500]}",
                        max_attempts=max_attempts,
                        retry_base_seconds=retry_base_seconds,
                        retry_max_seconds=retry_max_seconds,
                    )
                failed += 1
            else:
                NotificationRepository.mark_sent(db, row, now=now)
                sent += 1
        return sent, failed
