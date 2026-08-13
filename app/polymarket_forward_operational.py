from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import ForwardNavObservation, ForwardStudy
from app.forward_research import ForwardResearchService
from app.polymarket_forward import (
    PolymarketForwardBootstrap,
    PolymarketForwardConfig,
    PolymarketForwardConfigError,
    PolymarketStructuralForwardRunner,
    ShadowLeg,
    StructuralCandidate,
    _aware,
)


class OperationalPolymarketForwardBootstrap:
    """Idempotent bootstrap that also verifies the frozen initial NAV exists."""

    @staticmethod
    def bootstrap(
        db: Session,
        *,
        settings: Settings,
        now: datetime | None = None,
    ) -> ForwardStudy:
        study = PolymarketForwardBootstrap.bootstrap(db, settings=settings, now=now)
        initial_nav = db.scalar(
            select(ForwardNavObservation).where(
                ForwardNavObservation.study_id == study.id,
                ForwardNavObservation.observed_at == study.started_at,
            )
        )
        if initial_nav is None:
            if study.status != "active":
                raise PolymarketForwardConfigError(
                    "non-active Polymarket forward study is missing its frozen initial NAV"
                )
            ForwardResearchService.record_nav(
                db,
                study_id=study.id,
                observed_at=_aware(study.started_at),
                nav_usd=Decimal(study.initial_capital_usd),
                source="study-initial-capital",
            )
        return study


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
