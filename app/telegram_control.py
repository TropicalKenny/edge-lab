from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.control_models import IntegrationCursor
from app.control_service import OwnerControlError, OwnerControlService
from app.dashboard_api import dashboard_summary
from app.forward_models import ForwardStudy
from app.lifecycle_performance import LifecyclePerformanceService
from app.lifecycle_research import CANDIDATE_POLICIES, POLICY_VERSION


class TelegramControlError(RuntimeError):
    pass


def _money(value: Any) -> str:
    return f"${Decimal(str(value or 0)):,.2f}"


def _dashboard_pct(value: Any) -> str:
    return f"{Decimal(str(value or 0)):+.2f}%"


def _ratio_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{Decimal(str(value)) * Decimal('100'):+.2f}%"


def _short(value: str, size: int = 12) -> str:
    return value if len(value) <= size else value[:size]


HELP_TEXT = """EDGE LAB — OWNER CONTROLS

Read:
/status
/balance
/pnl
/performance
/strategies
/evidence
/incidents

Research controls:
/pause <solana|polymarket|hyperliquid|all> [reason]
/resume <target> [reason]
/freeze <target> [reason]
/lifecycle on|off [reason]
/incident ack|resolve <incident-id> [reason]

All balances are simulated paper/shadow research values. Live capital is $0 and signing is disabled."""


class TelegramControlClient:
    def __init__(
        self,
        *,
        bot_token: str,
        poll_timeout_seconds: int = 25,
        request_timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not bot_token.strip():
            raise ValueError("Telegram bot token is required")
        if poll_timeout_seconds < 1 or poll_timeout_seconds > 50:
            raise ValueError("Telegram poll timeout must be between 1 and 50 seconds")
        self.poll_timeout_seconds = poll_timeout_seconds
        timeout = httpx.Timeout(
            connect=request_timeout_seconds,
            read=max(request_timeout_seconds, poll_timeout_seconds + 10),
            write=request_timeout_seconds,
            pool=request_timeout_seconds,
        )
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._base = f"https://api.telegram.org/bot{bot_token}"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http.post(f"{self._base}/{method}", json=payload)
        except httpx.RequestError as exc:
            raise TelegramControlError(f"Telegram request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise TelegramControlError(f"Telegram HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramControlError("Telegram returned invalid JSON") from exc
        if body.get("ok") is not True:
            description = str(body.get("description") or "request rejected")
            raise TelegramControlError(f"Telegram rejected request: {description[:200]}")
        return body

    async def get_updates(self, *, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": self.poll_timeout_seconds,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        body = await self._call("getUpdates", payload)
        result = body.get("result") or []
        return [item for item in result if isinstance(item, dict)]

    async def send(self, *, chat_id: str, text: str) -> None:
        if not text.strip():
            return
        await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4096],
                "protect_content": True,
            },
        )


class TelegramControlRouter:
    CURSOR_KEY = "telegram-owner-controls"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.chat_id = settings.telegram_chat_id.strip()
        self.owner_user_id = settings.telegram_owner_user_id.strip()
        if not self.chat_id or not self.owner_user_id:
            raise ValueError("TELEGRAM_CHAT_ID and TELEGRAM_OWNER_USER_ID are required")

    @classmethod
    def load_offset(cls, db: Session) -> int | None:
        row = db.get(IntegrationCursor, cls.CURSOR_KEY)
        if row is None:
            return None
        try:
            return int(row.cursor_value)
        except ValueError:
            return None

    @classmethod
    def store_offset(cls, db: Session, offset: int) -> None:
        row = db.get(IntegrationCursor, cls.CURSOR_KEY)
        if row is None:
            row = IntegrationCursor(
                integration=cls.CURSOR_KEY,
                cursor_value=str(offset),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(row)
        else:
            row.cursor_value = str(offset)
            row.updated_at = datetime.now(timezone.utc)
        db.commit()

    def authorized_message(self, update: dict[str, Any]) -> tuple[str, str, str] | None:
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "")
        user_id = str(sender.get("id") or "")
        text = str(message.get("text") or "").strip()
        if chat_id != self.chat_id or user_id != self.owner_user_id:
            return None
        if not text:
            return None
        return chat_id, user_id, text

    def render(self, db: Session, text: str) -> str:
        token = text.split()[0]
        command = token.split("@", 1)[0].lower()
        args = text.split()[1:]

        if command in {"/start", "/help"}:
            return HELP_TEXT
        if command == "/status":
            return self._status(db)
        if command == "/balance":
            return self._balance(db)
        if command == "/pnl":
            return self._pnl(db)
        if command == "/performance":
            return self._performance(db)
        if command == "/strategies":
            return self._strategies(db)
        if command == "/evidence":
            return self._evidence(db)
        if command == "/incidents":
            return self._incidents(db)
        return "Unknown command. Use /help."

    def apply(self, db: Session, *, update_id: int, user_id: str, text: str) -> str | None:
        parts = text.split()
        if not parts:
            return None
        command = parts[0].split("@", 1)[0].lower()
        if command not in {"/pause", "/resume", "/freeze", "/lifecycle", "/incident"}:
            return None

        if command in {"/pause", "/resume", "/freeze"}:
            if len(parts) < 2:
                return f"Usage: {command} <solana|polymarket|hyperliquid|all> [reason]"
            action = command[1:]
            target = parts[1].lower()
            reason = " ".join(parts[2:]).strip() or "owner command via Telegram"
            if target == "all":
                results: list[str] = []
                studies = OwnerControlService.list_studies(db)
                if not studies:
                    return "No forward studies are registered yet."
                for study in studies:
                    try:
                        result = OwnerControlService.execute(
                            db,
                            command=action,
                            actor_type="telegram",
                            actor_id=user_id,
                            idempotency_key=f"telegram:{update_id}:{action}:{study.id}",
                            target=study.id,
                            reason=reason,
                        )
                    except OwnerControlError as exc:
                        results.append(f"{study.venue}: rejected — {exc}")
                    else:
                        results.append(
                            f"{study.venue}: {result.outcome.get('before')} → {result.outcome.get('after')}"
                        )
                return "EDGE LAB — CONTROL\n" + "\n".join(results)
            try:
                result = OwnerControlService.execute(
                    db,
                    command=action,
                    actor_type="telegram",
                    actor_id=user_id,
                    idempotency_key=f"telegram:{update_id}:{action}:{target}",
                    target=target,
                    reason=reason,
                )
            except OwnerControlError as exc:
                return f"Command rejected: {exc}"
            outcome = result.outcome
            return (
                "EDGE LAB — CONTROL\n"
                f"Study: {outcome.get('study', target)}\n"
                f"State: {outcome.get('before')} → {outcome.get('after')}\n"
                f"Audit: {_short(result.command_id)}"
            )

        if command == "/lifecycle":
            if len(parts) < 2 or parts[1].lower() not in {"on", "off"}:
                return "Usage: /lifecycle on|off [reason]"
            enabled = parts[1].lower() == "on"
            reason = " ".join(parts[2:]).strip() or "owner lifecycle command via Telegram"
            action = "lifecycle_on" if enabled else "lifecycle_off"
            try:
                result = OwnerControlService.execute(
                    db,
                    command=action,
                    actor_type="telegram",
                    actor_id=user_id,
                    idempotency_key=f"telegram:{update_id}:{action}:solana",
                    target="solana",
                    reason=reason,
                )
            except OwnerControlError as exc:
                return f"Command rejected: {exc}"
            return (
                "EDGE LAB — M6H LIFECYCLE\n"
                f"Enabled: {str(result.outcome.get('lifecycle_after')).upper()}\n"
                "Execution: DISABLED\n"
                f"Audit: {_short(result.command_id)}"
            )

        if command == "/incident":
            if len(parts) < 3 or parts[1].lower() not in {"ack", "resolve"}:
                return "Usage: /incident ack|resolve <incident-id> [reason]"
            verb = parts[1].lower()
            incident_id = parts[2]
            reason = " ".join(parts[3:]).strip() or "owner incident command via Telegram"
            action = "incident_ack" if verb == "ack" else "incident_resolve"
            try:
                result = OwnerControlService.execute(
                    db,
                    command=action,
                    actor_type="telegram",
                    actor_id=user_id,
                    idempotency_key=f"telegram:{update_id}:{action}:{incident_id}",
                    target=incident_id,
                    reason=reason,
                )
            except OwnerControlError as exc:
                return f"Command rejected: {exc}"
            return (
                "EDGE LAB — INCIDENT\n"
                f"ID: {incident_id}\n"
                f"Acknowledged: {result.outcome.get('acknowledged')}\n"
                f"Resolved: {result.outcome.get('resolved')}\n"
                f"Audit: {_short(result.command_id)}"
            )
        return None

    @staticmethod
    def _summary(db: Session) -> dict[str, Any]:
        return dashboard_summary(db)

    def _status(self, db: Session) -> str:
        data = self._summary(db)
        studies = data.get("studies") or []
        lines = [
            "EDGE LAB — STATUS",
            "Mode: PAPER/SHADOW",
            "Signer: DISABLED",
            "Live capital: $0.00",
            f"Studies: {len(studies)}",
        ]
        for row in studies:
            lifecycle = ""
            if row.get("venue") == "solana":
                lifecycle = f" | M6H {'ON' if OwnerControlService.lifecycle_enabled(db, row['study_id']) else 'OFF'}"
            lines.append(f"{row.get('venue')}: {str(row.get('study_status')).upper()}{lifecycle}")
        lines.append(f"Open incidents: {data.get('portfolio', {}).get('unresolved_incidents', 0)}")
        return "\n".join(lines)

    def _balance(self, db: Session) -> str:
        data = self._summary(db)
        portfolio = data.get("portfolio") or {}
        return "\n".join(
            [
                "EDGE LAB — PAPER/SHADOW BALANCE",
                f"Combined simulated NAV: {_money(portfolio.get('simulated_latest_nav_usd'))}",
                f"Starting simulated capital: {_money(portfolio.get('simulated_initial_capital_usd'))}",
                f"Net P&L: {_money(portfolio.get('net_pnl_usd'))} ({_dashboard_pct(portfolio.get('return_pct'))})",
                "Live capital: $0.00",
                "Signer: DISABLED",
            ]
        )

    def _pnl(self, db: Session) -> str:
        data = self._summary(db)
        portfolio = data.get("portfolio") or {}
        lines = [
            "EDGE LAB — P&L",
            f"Combined: {_money(portfolio.get('net_pnl_usd'))} ({_dashboard_pct(portfolio.get('return_pct'))})",
        ]
        studies = data.get("studies") or []
        if not studies:
            lines.append("No forward studies registered yet.")
        for row in studies:
            lines.append(
                f"{row.get('venue')}: {_money(row.get('net_pnl_usd'))} ({_dashboard_pct(row.get('return_pct'))}) | NAV {_money(row.get('latest_nav_usd'))}"
            )
        return "\n".join(lines)

    def _strategies(self, db: Session) -> str:
        data = self._summary(db)
        studies = data.get("studies") or []
        lines = ["EDGE LAB — STRATEGIES"]
        if not studies:
            return "EDGE LAB — STRATEGIES\nNo forward studies registered yet."
        for row in studies:
            lines.extend(
                [
                    f"\n{row.get('strategy_name')}",
                    f"Venue: {row.get('venue')} | Study: {row.get('study_status')}",
                    f"NAV: {_money(row.get('latest_nav_usd'))} | P&L: {_money(row.get('net_pnl_usd'))}",
                    f"Evidence: {(row.get('latest_evaluation') or {}).get('recommendation', 'not evaluated')}",
                ]
            )
        return "\n".join(lines)

    def _evidence(self, db: Session) -> str:
        data = self._summary(db)
        lines = ["EDGE LAB — EVIDENCE"]
        studies = data.get("studies") or []
        if not studies:
            lines.append("No studies registered yet.")
        for row in studies:
            evaluation = row.get("latest_evaluation") or {}
            lines.append(
                f"{row.get('venue')}: {evaluation.get('recommendation', 'not evaluated')} | days {evaluation.get('forward_days', 0)} | trades {evaluation.get('trade_count', 0)}"
            )
        lines.append("GREEN-1_CANDIDATE is evidence only; it never enables trading.")
        return "\n".join(lines)

    def _incidents(self, db: Session) -> str:
        data = self._summary(db)
        incidents = data.get("incidents") or []
        if not incidents:
            return "EDGE LAB — INCIDENTS\nNo unresolved incidents."
        lines = ["EDGE LAB — INCIDENTS"]
        for item in incidents[:10]:
            ack = OwnerControlService.incident_acknowledged(db, item["id"])
            lines.append(
                f"{_short(item['id'])} | {item.get('severity')} | {item.get('strategy_name')} | ack={'yes' if ack else 'no'} | {item.get('code')}"
            )
        return "\n".join(lines)

    def _performance(self, db: Session) -> str:
        data = self._summary(db)
        lines = ["EDGE LAB — PERFORMANCE"]
        studies = data.get("studies") or []
        if not studies:
            return "EDGE LAB — PERFORMANCE\nNo forward studies registered yet."
        for row in studies:
            lines.append(
                f"{row.get('venue')}: return {_dashboard_pct(row.get('return_pct'))} | P&L {_money(row.get('net_pnl_usd'))} | drawdown {_ratio_pct(row.get('observed_max_drawdown_pct'))}"
            )
        solana: ForwardStudy | None = db.scalar(
            select(ForwardStudy)
            .where(ForwardStudy.venue == "solana", ForwardStudy.family == "meme")
            .order_by(ForwardStudy.started_at.desc())
            .limit(1)
        )
        if solana is not None:
            lines.append("\nM6H lifecycle vs uninterrupted hold:")
            for policy in CANDIDATE_POLICIES:
                summary = LifecyclePerformanceService.summarize_policy(
                    db,
                    study_id=solana.id,
                    policy_name=policy.name,
                    policy_version=POLICY_VERSION,
                )
                lines.append(
                    f"{policy.name}: policy {_ratio_pct(summary.mean_net_return_pct)} | hold {_ratio_pct(summary.mean_hold_return_pct)} | excess {_ratio_pct(summary.mean_excess_return_pct)} | samples {summary.complete_position_count}/300 | cycles {summary.completed_cycle_count}/300"
                )
        return "\n".join(lines)
