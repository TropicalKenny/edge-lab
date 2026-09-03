from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.telegram_control import TelegramControlClient, TelegramControlRouter

log = logging.getLogger("edge_lab.telegram_controls")


async def run() -> None:
    settings = get_settings()
    if settings.signer_enabled:
        raise RuntimeError("refusing Telegram controls with SIGNER_ENABLED=true")
    if not settings.telegram_bot_token.strip():
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for Telegram controls")
    router = TelegramControlRouter(settings)
    SessionLocal = get_session_factory()

    async with TelegramControlClient(
        bot_token=settings.telegram_bot_token,
        poll_timeout_seconds=settings.telegram_control_poll_timeout_seconds,
        request_timeout_seconds=settings.telegram_timeout_seconds,
    ) as client:
        try:
            # Menu registration changes only Telegram's command hints. Failure must not
            # take down the private owner-control worker.
            await client.set_commands()
        except Exception:
            log.exception("Telegram command-menu registration failed")

        while True:
            try:
                # Never hold a database transaction open while Telegram long-polls.
                db = SessionLocal()
                try:
                    offset = router.load_offset(db)
                finally:
                    db.close()

                updates = await client.get_updates(offset=offset)
                for update in updates:
                    update_id_raw = update.get("update_id")
                    if not isinstance(update_id_raw, int):
                        continue
                    update_id = int(update_id_raw)
                    authorized = router.authorized_message(update)
                    if authorized is None:
                        # Consume untrusted/irrelevant updates so they cannot be replayed forever.
                        db = SessionLocal()
                        try:
                            router.store_offset(db, update_id + 1)
                        except Exception:
                            db.rollback()
                            raise
                        finally:
                            db.close()
                        continue

                    chat_id, user_id, text = authorized
                    # Build/apply the response while the DB session is open, then close it
                    # before awaiting Telegram. Mutations are idempotent, so a failed send
                    # may safely retry the same update without duplicating the command.
                    db = SessionLocal()
                    try:
                        response = router.apply(
                            db,
                            update_id=update_id,
                            user_id=user_id,
                            text=text,
                        )
                        if response is None:
                            response = router.render(db, text)
                    except Exception:
                        db.rollback()
                        raise
                    finally:
                        db.close()

                    await client.send(chat_id=chat_id, text=response)

                    # Advance the durable cursor only after the response was sent.
                    db = SessionLocal()
                    try:
                        router.store_offset(db, update_id + 1)
                    except Exception:
                        db.rollback()
                        raise
                    finally:
                        db.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Telegram owner-control cycle failed")
                await asyncio.sleep(settings.telegram_control_retry_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
