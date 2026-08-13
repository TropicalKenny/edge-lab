from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.forward_operations import ForwardOperationsService

log = logging.getLogger("edge_lab.forward_evaluator")


async def run() -> None:
    settings = get_settings()
    SessionLocal = get_session_factory()
    while True:
        db = SessionLocal()
        try:
            ticks = ForwardOperationsService.evaluate_due_studies(db)
            for tick in ticks:
                log.info(
                    "forward evaluation study=%s action=%s run=%s recommendation=%s",
                    tick.external_id,
                    tick.action,
                    tick.run_id,
                    tick.recommendation,
                )
        except Exception:
            db.rollback()
            log.exception("forward evaluation cycle failed")
        finally:
            db.close()
        await asyncio.sleep(settings.forward_evaluation_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
