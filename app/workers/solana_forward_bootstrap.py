from __future__ import annotations

import json
import logging

from app.config import get_settings
from app.database import get_session_factory
from app.solana_forward_operational import OperationalSolanaForwardBootstrap

log = logging.getLogger("edge_lab.solana_forward_bootstrap")


def run() -> None:
    settings = get_settings()
    if settings.signer_enabled:
        raise RuntimeError("refusing Solana forward bootstrap with SIGNER_ENABLED=true")
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        study = OperationalSolanaForwardBootstrap.bootstrap(db, settings=settings)
        log.info(
            "Solana forward study ready: %s",
            json.dumps(
                {
                    "study_id": study.id,
                    "external_id": study.external_id,
                    "status": study.status,
                    "initial_capital_usd": str(study.initial_capital_usd),
                },
                sort_keys=True,
            ),
        )
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
