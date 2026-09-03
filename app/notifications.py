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
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition
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


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return default


def _metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _duration_text(opened_at: datetime, closed_at: datetime) -> str:
    seconds = max(0, int((_aware(closed_at) - _aware(opened_at)).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _study_label(study: ForwardStudy | None, fallback: str) -> str:
    return study.external_id if study is not None else fallback


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
            study_name = _study_label(study, incident.study_id)
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

    @staticmethod
    def trade_events(db: Session) -> list[NotificationEvent]:
        """Return immutable paper/shadow trade lifecycle events.

        Hyperliquid has a durable position row, Solana has a durable accepted-entry
        execution row, and all venues create a ForwardTradeRecord when a simulated
        trade is complete. Event keys are tied to those persisted row ids so worker
        restarts cannot duplicate an alert.
        """

        events: list[NotificationEvent] = []

        positions = list(
            db.scalars(
                select(HyperliquidCarryPosition).order_by(HyperliquidCarryPosition.opened_at.asc())
            ).all()
        )
        for position in positions:
            study = db.get(ForwardStudy, position.study_id)
            study_name = _study_label(study, position.study_id)
            entry_cost = Decimal(position.entry_spot_fee_usd) + Decimal(position.entry_perp_fee_usd)
            text = (
                "EDGE LAB — PAPER/SHADOW TRADE OPENED\n"
                "Venue: Hyperliquid\n"
                f"Study: {study_name}\n"
                f"Instrument: {position.coin} funding/carry\n"
                f"Simulated allocation: {_money(position.allocated_capital_usd)}\n"
                f"Spot entry: {Decimal(position.entry_spot_price):f}\n"
                f"Perp entry: {Decimal(position.entry_perp_price):f}\n"
                f"Entry fees: {_money(entry_cost)}\n"
                f"Opened: {_aware(position.opened_at).isoformat()}\n"
                f"Planned close: {_aware(position.target_close_at).isoformat()}\n"
                "PAPER/SHADOW ONLY — no real money, wallet, signing or live order was used."
            )
            events.append(
                NotificationEvent(
                    event_key=f"trade-open:hyperliquid:{position.id}",
                    event_type="paper_trade_open",
                    severity="info",
                    text=text,
                    metadata={
                        "venue": "hyperliquid",
                        "study_id": position.study_id,
                        "position_id": position.id,
                        "instrument": position.coin,
                        "opened_at": _aware(position.opened_at).isoformat(),
                    },
                )
            )

        solana_entries = list(
            db.scalars(
                select(ForwardExecutionRecord)
                .where(ForwardExecutionRecord.external_key.like("solana-entry:%"))
                .order_by(ForwardExecutionRecord.observed_at.asc())
            ).all()
        )
        for execution in solana_entries:
            meta = _metadata(execution.metadata_json)
            if meta.get("phase") != "entry" or meta.get("status") != "open":
                continue
            study = db.get(ForwardStudy, execution.study_id)
            study_name = _study_label(study, execution.study_id)
            mint = str(meta.get("mint") or (study.instrument if study is not None else "unknown"))
            allocated = _decimal(meta.get("allocated_capital_usd"), Decimal(execution.shadow_cost_usd))
            entry_price = execution.shadow_average_price or execution.paper_average_price
            price_text = f"{Decimal(entry_price):f}" if entry_price is not None else "n/a"
            text = (
                "EDGE LAB — PAPER/SHADOW TRADE OPENED\n"
                "Venue: Solana\n"
                f"Study: {study_name}\n"
                f"Asset: {mint}\n"
                f"Simulated allocation: {_money(allocated)}\n"
                f"Shadow entry price: {price_text}\n"
                f"Opened: {meta.get('opened_at') or _aware(execution.observed_at).isoformat()}\n"
                f"Planned hold until: {meta.get('hold_until') or 'n/a'}\n"
                "Entry reason: frozen M6G safety/exitability rules passed.\n"
                "PAPER/SHADOW ONLY — no real money, wallet, signing or live order was used."
            )
            events.append(
                NotificationEvent(
                    event_key=f"trade-open:solana:{execution.id}",
                    event_type="paper_trade_open",
                    severity="info",
                    text=text,
                    metadata={
                        "venue": "solana",
                        "study_id": execution.study_id,
                        "execution_id": execution.id,
                        "mint": mint,
                        "opened_at": meta.get("opened_at") or _aware(execution.observed_at).isoformat(),
                    },
                )
            )

        trades = list(
            db.scalars(select(ForwardTradeRecord).order_by(ForwardTradeRecord.closed_at.asc())).all()
        )
        for trade in trades:
            study = db.get(ForwardStudy, trade.study_id)
            study_name = _study_label(study, trade.study_id)
            venue = study.venue if study is not None else "unknown"
            instrument = study.instrument if study is not None else "unknown"
            meta = _metadata(trade.metadata_json)
            close_reason = str(
                meta.get("close_reason")
                or meta.get("exit_reason")
                or meta.get("reason")
                or "strategy exit/completion"
            )
            if venue == "hyperliquid":
                position = db.scalar(
                    select(HyperliquidCarryPosition).where(
                        HyperliquidCarryPosition.trade_record_id == trade.id
                    )
                )
                if position is not None:
                    instrument = f"{position.coin} funding/carry"
                    close_reason = position.close_reason or close_reason
            elif venue == "solana":
                instrument = str(meta.get("mint") or instrument)
            elif venue == "polymarket":
                instrument = str(meta.get("kind") or meta.get("opportunity_kind") or instrument)

            allocated = Decimal(trade.allocated_capital_usd)
            net = Decimal(trade.net_pnl_usd)
            return_pct = (net / allocated * Decimal("100")) if allocated > ZERO else ZERO
            title = "TRADE COMPLETED" if venue == "polymarket" else "TRADE CLOSED"
            text = (
                f"EDGE LAB — PAPER/SHADOW {title}\n"
                f"Venue: {venue.title()}\n"
                f"Study: {study_name}\n"
                f"Instrument: {instrument}\n"
                f"Simulated allocation: {_money(allocated)}\n"
                f"Net P&L: {_money(net)} ({return_pct:.2f}%)\n"
                f"Fees: {_money(trade.fees_usd)}\n"
                f"Slippage/cost divergence: {_money(trade.slippage_usd)}\n"
                f"Held: {_duration_text(trade.opened_at, trade.closed_at)}\n"
                f"Exit reason: {close_reason}\n"
                f"Opened: {_aware(trade.opened_at).isoformat()}\n"
                f"Closed: {_aware(trade.closed_at).isoformat()}\n"
                "PAPER/SHADOW ONLY — no real money, wallet, signing or live order was used."
            )
            events.append(
                NotificationEvent(
                    event_key=f"trade-close:{trade.id}",
                    event_type="paper_trade_close",
                    severity="info" if net >= ZERO else "warning",
                    text=text,
                    metadata={
                        "venue": venue,
                        "study_id": trade.study_id,
                        "trade_id": trade.id,
                        "net_pnl_usd": str(net),
                        "closed_at": _aware(trade.closed_at).isoformat(),
                    },
                )
            )

        return events

    @staticmethod
    def _solana_open_count(db: Session) -> int:
        count = 0
        rows = list(
            db.scalars(
                select(ForwardExecutionRecord).where(
                    ForwardExecutionRecord.external_key.like("solana-entry:%")
                )
            ).all()
        )
        for row in rows:
            meta = _metadata(row.metadata_json)
            if meta.get("status") != "open":
                continue
            signature = row.external_key.removeprefix("solana-entry:")
            closed = db.scalar(
                select(ForwardTradeRecord.id).where(
                    ForwardTradeRecord.study_id == row.study_id,
                    ForwardTradeRecord.external_key == f"solana-trade:{signature}",
                )
            )
            if closed is None:
                count += 1
        return count

    @classmethod
    def heartbeat_events(
        cls,
        db: Session,
        *,
        now: datetime,
        heartbeat_hour_utc: int = 18,
    ) -> list[NotificationEvent]:
        now = _aware(now)
        if heartbeat_hour_utc < 0 or heartbeat_hour_utc > 23:
            raise ValueError("heartbeat_hour_utc must be between 0 and 23")
        if now.hour < heartbeat_hour_utc:
            return []

        event_key = f"daily-heartbeat:{now.date().isoformat()}"
        if db.scalar(
            select(NotificationDelivery.id).where(
                NotificationDelivery.channel == CHANNEL_TELEGRAM,
                NotificationDelivery.event_key == event_key,
            )
        ) is not None:
            return []

        studies = list(
            db.scalars(
                select(ForwardStudy)
                .where(ForwardStudy.status == "active")
                .order_by(ForwardStudy.venue.asc(), ForwardStudy.external_id.asc())
            ).all()
        )
        latest_nav_total = ZERO
        lines: list[str] = []
        for study in studies:
            nav = db.scalar(
                select(ForwardNavObservation)
                .where(ForwardNavObservation.study_id == study.id)
                .order_by(ForwardNavObservation.observed_at.desc())
                .limit(1)
            )
            nav_value = Decimal(nav.nav_usd) if nav is not None else Decimal(study.initial_capital_usd)
            latest_nav_total += nav_value
            trade_count = len(
                list(
                    db.scalars(
                        select(ForwardTradeRecord.id).where(ForwardTradeRecord.study_id == study.id)
                    ).all()
                )
            )
            lines.append(f"- {study.venue.title()}: active | NAV {_money(nav_value)} | closed trades {trade_count}")

        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        trades_today = len(
            list(
                db.scalars(
                    select(ForwardTradeRecord.id).where(ForwardTradeRecord.closed_at >= start)
                ).all()
            )
        )
        hl_open = len(
            list(
                db.scalars(
                    select(HyperliquidCarryPosition.id).where(
                        HyperliquidCarryPosition.status == "open"
                    )
                ).all()
            )
        )
        solana_open = cls._solana_open_count(db)
        open_positions = hl_open + solana_open
        no_trade_note = (
            "No paper/shadow trades closed today — studies remain active and watching for qualifying setups."
            if trades_today == 0
            else f"Paper/shadow trades closed today: {trades_today}."
        )
        text = (
            "EDGE LAB — DAILY RESEARCH HEARTBEAT\n"
            f"Date (UTC): {now.date().isoformat()}\n"
            f"Active studies: {len(studies)}\n"
            + "\n".join(lines)
            + ("\n" if lines else "")
            + f"Open paper/shadow positions: {open_positions}\n"
            + f"Combined simulated NAV: {_money(latest_nav_total)}\n"
            + no_trade_note
            + "\nUse /research for the full live readiness/evidence snapshot.\n"
            + "PAPER/SHADOW ONLY — live capital remains disabled."
        )
        return [
            NotificationEvent(
                event_key=event_key,
                event_type="daily_research_heartbeat",
                severity="info",
                text=text,
                metadata={
                    "date": now.date().isoformat(),
                    "active_studies": len(studies),
                    "open_positions": open_positions,
                    "trades_today": trades_today,
                    "simulated_nav_usd": str(latest_nav_total),
                },
            )
        ]

    @classmethod
    def collect(
        cls,
        db: Session,
        *,
        now: datetime | None = None,
        heartbeat_hour_utc: int = 18,
    ) -> list[NotificationEvent]:
        now = _aware(now or datetime.now(timezone.utc))
        return (
            cls.incident_events(db)
            + cls.evaluation_events(db)
            + cls.trade_events(db)
            + cls.heartbeat_events(db, now=now, heartbeat_hour_utc=heartbeat_hour_utc)
        )


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
    def queue_current_events(
        db: Session,
        *,
        now: datetime | None = None,
        heartbeat_hour_utc: int = 18,
    ) -> int:
        now = _aware(now or datetime.now(timezone.utc))
        queued = 0
        for event in AlertEventCollector.collect(
            db,
            now=now,
            heartbeat_hour_utc=heartbeat_hour_utc,
        ):
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
