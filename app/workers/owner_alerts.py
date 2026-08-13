from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.notifications import NotificationDispatcher, TelegramSender

log = logging.getLogger("edge_lab.owner_alerts")


async def run_cycle() -> tuple[int, int, int]:
    settings = get_settings()
    if not settings.telegram_bot_token.strip() or not settings.telegram_chat_id.strip():
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required for owner alerts")

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        queued = NotificationDispatcher.queue_current_events(db)
        async with TelegramSender(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            timeout_seconds=settings.telegram_timeout_seconds,
        ) as sender:
            sent, failed = await NotificationDispatcher.dispatch_due(
                db,
                sender=sender,
                max_attempts=settings.telegram_alert_max_attempts,
                retry_base_seconds=settings.telegram_alert_retry_base_seconds,
                retry_max_seconds=settings.telegram_alert_retry_max_seconds,
                batch_size=settings.telegram_alert_batch_size,
            )
        return queued, sent, failed
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    while True:
        try:
            queued, sent, failed = await run_cycle()
            if queued or sent or failed:
                log.info("owner alerts: queued=%s sent=%s failed=%s", queued, sent, failed)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("owner alert cycle failed; research workers are unaffected")
        await asyncio.sleep(settings.telegram_alert_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
