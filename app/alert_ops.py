from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.config import get_settings
from app.database import get_session_factory
from app.notification_models import NotificationDelivery
from app.notifications import TelegramSender


async def send_test() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token.strip() or not settings.telegram_chat_id.strip():
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    async with TelegramSender(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        timeout_seconds=settings.telegram_timeout_seconds,
    ) as sender:
        await sender.send(
            "EDGE LAB — ALERT CHANNEL TEST\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}\n"
            "Status: notification channel reachable.\n"
            "Safety: research only; no signer or live capital is enabled."
        )
    print("Telegram alert test sent successfully.")


def status() -> None:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        counts = dict(
            db.execute(
                select(NotificationDelivery.status, func.count(NotificationDelivery.id))
                .group_by(NotificationDelivery.status)
            ).all()
        )
        print(
            "notification deliveries: "
            + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
            if counts
            else "notification deliveries: none"
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge Lab owner-alert operations")
    parser.add_argument("command", choices=["test", "status"])
    args = parser.parse_args()
    if args.command == "test":
        asyncio.run(send_test())
    else:
        status()


if __name__ == "__main__":
    main()
