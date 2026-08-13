from __future__ import annotations

import json

from app.config import get_settings
from app.database import get_session_factory
from app.polymarket_forward_operational import OperationalPolymarketForwardBootstrap


def run() -> None:
    settings = get_settings()
    db = get_session_factory()()
    try:
        study = OperationalPolymarketForwardBootstrap.bootstrap(db, settings=settings)
        print(
            json.dumps(
                {
                    "study_id": study.id,
                    "external_id": study.external_id,
                    "venue": study.venue,
                    "instrument": study.instrument,
                    "status": study.status,
                    "started_at": study.started_at.isoformat(),
                    "signer_enabled": False,
                },
                sort_keys=True,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
