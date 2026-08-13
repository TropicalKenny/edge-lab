from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.forward_models import ForwardStudy
from app.polymarket_forward import (
    PolymarketForwardConfig,
    PolymarketStructuralForwardRunner,
    ShadowLeg,
    StructuralCandidate,
    _aware,
)


class OperationalPolymarketStructuralForwardRunner(PolymarketStructuralForwardRunner):
    """Reject evidence whose source books fall outside the frozen forward window."""

    def _persist_attempt(
        self,
        db: Session,
        study: ForwardStudy,
        candidate: StructuralCandidate,
        shadow: list[ShadowLeg],
        config: PolymarketForwardConfig,
        attempt_key: str,
    ) -> bool:
        started_at = _aware(study.started_at)
        signal_at = _aware(candidate.opportunity.captured_at)
        if signal_at < started_at:
            return False
        if any(_aware(row.observed_at) < started_at for row in shadow):
            return False
        future_limit = datetime.now(timezone.utc) + timedelta(minutes=1)
        if signal_at > future_limit or any(_aware(row.observed_at) > future_limit for row in shadow):
            self._record_incident(
                db,
                study,
                datetime.now(timezone.utc),
                "critical",
                "PM_FORWARD_FUTURE_BOOK_TIMESTAMP",
                "Polymarket forward book timestamp exceeded the allowed future tolerance",
                True,
            )
            return False
        return super()._persist_attempt(db, study, candidate, shadow, config, attempt_key)
