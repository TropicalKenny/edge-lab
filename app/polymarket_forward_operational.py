from __future__ import annotations

from dataclasses import replace
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
from app.venues.polymarket import StructuralOpportunity, parse_event


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
        elif (
            Decimal(initial_nav.nav_usd) != Decimal(study.initial_capital_usd)
            or initial_nav.source != "study-initial-capital"
        ):
            raise PolymarketForwardConfigError(
                "Polymarket forward study initial NAV conflicts with frozen bootstrap capital"
            )
        return study


class OperationalPolymarketStructuralForwardRunner(PolymarketStructuralForwardRunner):
    """Fail-closed operational hardening for the public-data Polymarket runner."""

    @staticmethod
    def _operation_count(opportunity: StructuralOpportunity) -> int:
        if opportunity.kind == "binary_complete_set":
            return 1
        if opportunity.kind == "negrisk_no_complete_set":
            # One No->all-other-Yes conversion, then one merge for each of the
            # remaining N-1 markets. Total structural actions = N.
            return max(1, len(opportunity.legs))
        return 1

    @classmethod
    def _effective_config(
        cls,
        opportunity: StructuralOpportunity,
        config: PolymarketForwardConfig,
    ) -> PolymarketForwardConfig:
        return replace(
            config,
            operation_cost_usd=(
                config.operation_cost_usd * Decimal(cls._operation_count(opportunity))
            ),
        )

    @classmethod
    def _signal_passes_cost_reserve(
        cls,
        opportunity: StructuralOpportunity,
        config: PolymarketForwardConfig,
    ) -> bool:
        return super()._signal_passes_cost_reserve(
            opportunity,
            cls._effective_config(opportunity, config),
        )

    @classmethod
    def _required_capital(
        cls,
        opportunity: StructuralOpportunity,
        config: PolymarketForwardConfig,
    ) -> Decimal:
        return super()._required_capital(
            opportunity,
            cls._effective_config(opportunity, config),
        )

    @staticmethod
    def _empty_candidate_shadow(
        candidate: StructuralCandidate,
        reason: str,
    ) -> list[ShadowLeg]:
        observed_at = datetime.now(timezone.utc)
        return [
            PolymarketStructuralForwardRunner._empty_shadow(
                leg,
                observed_at,
                reason,
            )
            for leg in candidate.opportunity.legs
        ]

    async def _shadow_reprice(
        self,
        candidate: StructuralCandidate,
        config: PolymarketForwardConfig,
    ) -> list[ShadowLeg]:
        opportunity = candidate.opportunity
        if opportunity.kind == "negrisk_no_complete_set":
            if not opportunity.event_id:
                return self._empty_candidate_shadow(
                    candidate,
                    "NEGRISK_EVENT_ID_MISSING",
                )
            try:
                payload = await self.client.get_event(str(opportunity.event_id))
                if not isinstance(payload, dict):
                    raise ValueError("event response is not an object")
                event = parse_event(payload)
            except Exception:
                return self._empty_candidate_shadow(
                    candidate,
                    "NEGRISK_EVENT_REVALIDATION_FAILED",
                )

            current_markets = [market for market in event.markets if market.is_tradeable_binary]
            unsafe = (
                not event.neg_risk
                or event.neg_risk_augmented
                or len(current_markets) < 3
                or len(current_markets) != len(event.markets)
                or any(
                    market.neg_risk_other
                    or (
                        market.group_item_title
                        and market.group_item_title.strip().lower() == "other"
                    )
                    for market in current_markets
                )
            )
            if unsafe:
                return self._empty_candidate_shadow(
                    candidate,
                    "NEGRISK_EVENT_BECAME_UNSAFE",
                )

            expected = {
                (
                    market.market_id,
                    market.condition_id,
                    market.yes_token_id,
                    market.no_token_id,
                )
                for market in candidate.markets.values()
            }
            current = {
                (
                    market.market_id,
                    market.condition_id,
                    market.yes_token_id,
                    market.no_token_id,
                )
                for market in current_markets
            }
            if current != expected:
                return self._empty_candidate_shadow(
                    candidate,
                    "NEGRISK_EVENT_MEMBERSHIP_CHANGED",
                )

        return await super()._shadow_reprice(candidate, config)

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
        if signal_at > future_limit or any(
            _aware(row.observed_at) > future_limit for row in shadow
        ):
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
        return super()._persist_attempt(
            db,
            study,
            candidate,
            shadow,
            self._effective_config(candidate.opportunity, config),
            attempt_key,
        )