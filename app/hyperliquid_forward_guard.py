from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forward_research import ForwardResearchError, ForwardResearchService
from app.hyperliquid_forward import CarryStudyConfig, HyperliquidCarryForwardRunner, _aware
from app.hyperliquid_forward_models import HyperliquidCarryPosition

SHADOW_RECOVERY_GRACE_SECONDS = 5


def _incident(db: Session, position: HyperliquidCarryPosition, *, code: str, message: str, now: datetime) -> None:
    try:
        ForwardResearchService.record_incident(
            db,
            study_id=position.study_id,
            external_key=f"{position.external_key}:{code}",
            severity="error",
            code=code,
            message=message,
            opened_at=now,
            data_integrity=True,
        )
    except ForwardResearchError as exc:
        if "conflicting retry" not in str(exc):
            raise


def shadow_deadline(base_time: datetime, config: CarryStudyConfig) -> datetime:
    return _aware(base_time) + timedelta(
        seconds=config.shadow_delay_seconds + SHADOW_RECOVERY_GRACE_SECONDS
    )


def can_recover_shadow(base_time: datetime, config: CarryStudyConfig, now: datetime) -> bool:
    """Recovery is allowed only if a full configured delay can still finish inside the grace budget."""
    now = _aware(now)
    finish = now + timedelta(seconds=config.shadow_delay_seconds)
    return finish <= shadow_deadline(base_time, config)


async def recover_pending_shadow_state(
    db: Session,
    *,
    runner: HyperliquidCarryForwardRunner,
    study_id: str,
    config: CarryStudyConfig,
    now: datetime | None = None,
) -> int:
    """Recover shadow capture only while the original latency window remains credible."""
    now = _aware(now or datetime.now(timezone.utc))
    recovered = 0
    rows = list(
        db.scalars(
            select(HyperliquidCarryPosition)
            .where(HyperliquidCarryPosition.study_id == study_id)
            .order_by(HyperliquidCarryPosition.opened_at.asc())
        ).all()
    )
    for position in rows:
        if position.status == "open" and position.entry_shadow_observed_at is None:
            if can_recover_shadow(position.opened_at, config, now):
                await runner._entry_shadow(db, position, config)
                recovered += 1
        elif position.status == "closed" and position.exit_shadow_observed_at is None:
            reference = position.closed_at or position.target_close_at
            if can_recover_shadow(reference, config, now):
                await runner._exit_shadow(db, position, config)
                runner._ensure_closed_evidence(db, position)
                recovered += 1
    return recovered


def invalidate_stale_shadow_state(
    db: Session,
    *,
    study_id: str,
    config: CarryStudyConfig,
    now: datetime | None = None,
) -> int:
    """Invalidate positions whose intended shadow window can no longer be reproduced honestly."""
    now = _aware(now or datetime.now(timezone.utc))
    invalidated = 0
    rows = list(
        db.scalars(
            select(HyperliquidCarryPosition)
            .where(HyperliquidCarryPosition.study_id == study_id)
            .order_by(HyperliquidCarryPosition.opened_at.asc())
        ).all()
    )
    for position in rows:
        if position.status == "open" and position.entry_shadow_observed_at is None:
            if not can_recover_shadow(position.opened_at, config, now):
                _incident(
                    db,
                    position,
                    code="ENTRY_SHADOW_WINDOW_MISSED",
                    message="runner restart could no longer reproduce the frozen entry shadow window; later book was not backfilled",
                    now=now,
                )
                position.status = "invalid"
                position.close_reason = "entry-shadow-window-missed"
                invalidated += 1
        elif position.status == "closed" and position.exit_shadow_observed_at is None:
            reference = position.closed_at or position.target_close_at
            if not can_recover_shadow(reference, config, now):
                _incident(
                    db,
                    position,
                    code="EXIT_SHADOW_WINDOW_MISSED",
                    message="runner restart could no longer reproduce the frozen exit shadow window; later book was not backfilled",
                    now=now,
                )
                position.status = "invalid"
                position.close_reason = "exit-shadow-window-missed"
                invalidated += 1
    if invalidated:
        db.commit()
    return invalidated


def repair_closed_evidence(
    db: Session,
    *,
    runner: HyperliquidCarryForwardRunner,
    study_id: str,
) -> int:
    """Repair journal writes only when all persisted close/shadow facts already exist."""
    rows = list(
        db.scalars(
            select(HyperliquidCarryPosition).where(
                HyperliquidCarryPosition.study_id == study_id,
                HyperliquidCarryPosition.status == "closed",
                HyperliquidCarryPosition.exit_shadow_observed_at.is_not(None),
            )
        ).all()
    )
    repaired = 0
    for position in rows:
        before = position.trade_record_id
        runner._ensure_closed_evidence(db, position)
        if before is None and position.trade_record_id is not None:
            repaired += 1
    return repaired
