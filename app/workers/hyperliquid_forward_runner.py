from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.database import get_session_factory
from app.hyperliquid_forward_operational import OperationalHyperliquidCarryForwardRunner
from app.services import HealthRegistry
from app.scan_telemetry import normalize_reason, record_scan_observation
from app.venues.hyperliquid import HyperliquidInfoClient

log = logging.getLogger("edge_lab.hyperliquid_forward_runner")


async def run() -> None:
    settings = get_settings()
    health = HealthRegistry()
    SessionLocal = get_session_factory()

    async with HyperliquidInfoClient(
        network=settings.hyperliquid_network,
        timeout_seconds=settings.hyperliquid_timeout_seconds,
    ) as client:
        runner = OperationalHyperliquidCarryForwardRunner(client=client, health=health)
        while True:
            db = SessionLocal()
            try:
                results = await runner.run_active_studies(db)
                for result in results:
                    observed_at = datetime.now(timezone.utc)
                    record_scan_observation(
                        db,
                        study_id=result.study_id,
                        external_key=f"hyperliquid-cycle:{int(observed_at.timestamp() // settings.hyperliquid_forward_poll_seconds)}",
                        observation_kind="cycle",
                        observed_at=observed_at,
                        metadata={"action": result.action, "detail": result.detail},
                    )
                    if result.action in {"opened", "no_entry", "entry_rejected", "entry_rejected_capital"}:
                        if result.action == "opened":
                            accepted_count, rejected_count, reasons = 1, 0, {}
                        else:
                            accepted_count, rejected_count = 0, 1
                            raw_reasons = str(result.detail).split(",") if result.action == "no_entry" else [result.detail]
                            reasons = {normalize_reason(reason): 1 for reason in raw_reasons if str(reason).strip()}
                        record_scan_observation(
                            db,
                            study_id=result.study_id,
                            external_key=f"hyperliquid-candidate:{int(observed_at.timestamp() // settings.hyperliquid_forward_poll_seconds)}",
                            observation_kind="candidate",
                            observed_at=observed_at,
                            examined_count=1,
                            accepted_count=accepted_count,
                            rejected_count=rejected_count,
                            rejection_reasons=reasons,
                            metadata={"action": result.action},
                        )
                    log.info(
                        "Hyperliquid forward study %s: %s - %s",
                        result.study_id,
                        result.action,
                        result.detail,
                    )
            except Exception:
                db.rollback()
                log.exception("Hyperliquid forward runner cycle failed")
            finally:
                db.close()
            await asyncio.sleep(settings.hyperliquid_forward_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
