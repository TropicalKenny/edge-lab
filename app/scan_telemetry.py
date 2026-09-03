from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forward_models import ForwardScanObservation

_NUMERIC_METADATA_KEYS = {
    "launches_in_window",
    "features_ready",
    "quote_attempts",
    "opened",
    "markets_discovered",
    "markets_validated",
    "structural_candidates",
    "attempts",
    "trades",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), default=str, sort_keys=True, separators=(",", ":"))


def normalize_reason(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_").upper()
    return text[:120] or "UNSPECIFIED_REJECTION"


def record_scan_observation(
    db: Session,
    *,
    study_id: str,
    external_key: str,
    observation_kind: str,
    observed_at: datetime,
    examined_count: int = 0,
    accepted_count: int = 0,
    rejected_count: int = 0,
    deferred_count: int = 0,
    rejection_reasons: Mapping[str, int] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ForwardScanObservation:
    counts = (examined_count, accepted_count, rejected_count, deferred_count)
    if any(int(value) < 0 for value in counts):
        raise ValueError("scan telemetry counts cannot be negative")
    if accepted_count + rejected_count > examined_count:
        raise ValueError("accepted + rejected cannot exceed examined")
    if observation_kind not in {"cycle", "candidate"}:
        raise ValueError("observation_kind must be cycle or candidate")
    reasons = {normalize_reason(k): int(v) for k, v in (rejection_reasons or {}).items() if int(v) > 0}
    reasons_json = _json(reasons)
    metadata_json = _json(metadata)
    existing = db.scalar(
        select(ForwardScanObservation).where(
            ForwardScanObservation.study_id == study_id,
            ForwardScanObservation.external_key == external_key,
        )
    )
    if existing is not None:
        # Cycle keys are bucketed heartbeats. A restart in the same bucket reuses the
        # first durable observation instead of turning telemetry into a runtime blocker.
        if existing.observation_kind == "cycle" and observation_kind == "cycle":
            return existing
        # Candidate keys are deliberately stable. Re-observing the same frozen decision
        # returns the original row rather than double-counting it.
        if (
            existing.observation_kind != observation_kind
            or existing.examined_count != examined_count
            or existing.accepted_count != accepted_count
            or existing.rejected_count != rejected_count
            or existing.deferred_count != deferred_count
            or existing.rejection_reasons_json != reasons_json
            or existing.metadata_json != metadata_json
        ):
            raise ValueError(f"conflicting scan observation for {study_id}/{external_key}")
        return existing
    row = ForwardScanObservation(
        study_id=study_id,
        external_key=external_key,
        observation_kind=observation_kind,
        observed_at=_aware(observed_at),
        examined_count=int(examined_count),
        accepted_count=int(accepted_count),
        rejected_count=int(rejected_count),
        deferred_count=int(deferred_count),
        rejection_reasons_json=reasons_json,
        metadata_json=metadata_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def scan_activity_summary(
    db: Session,
    *,
    study_id: str,
    now: datetime,
    window_hours: int = 24,
) -> dict[str, Any]:
    now = _aware(now)
    since = now - timedelta(hours=window_hours)
    rows = db.scalars(
        select(ForwardScanObservation)
        .where(
            ForwardScanObservation.study_id == study_id,
            ForwardScanObservation.observed_at >= since,
            ForwardScanObservation.observed_at <= now,
        )
        .order_by(ForwardScanObservation.observed_at.asc())
    ).all()
    earliest = db.scalar(
        select(ForwardScanObservation)
        .where(ForwardScanObservation.study_id == study_id)
        .order_by(ForwardScanObservation.observed_at.asc())
        .limit(1)
    )
    reasons: Counter[str] = Counter()
    metadata_totals: Counter[str] = Counter()
    examined = accepted = rejected = deferred = cycles = 0
    last_scan_at = None
    for row in rows:
        examined += int(row.examined_count)
        accepted += int(row.accepted_count)
        rejected += int(row.rejected_count)
        deferred += int(row.deferred_count)
        if row.observation_kind == "cycle":
            cycles += 1
        last_scan_at = _aware(row.observed_at)
        try:
            reason_map = json.loads(row.rejection_reasons_json)
        except json.JSONDecodeError:
            reason_map = {}
        if isinstance(reason_map, dict):
            for reason, count in reason_map.items():
                try:
                    reasons[normalize_reason(reason)] += max(0, int(count))
                except (TypeError, ValueError):
                    continue
        try:
            meta = json.loads(row.metadata_json)
        except json.JSONDecodeError:
            meta = {}
        if isinstance(meta, dict):
            for key in _NUMERIC_METADATA_KEYS:
                value = meta.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metadata_totals[key] += int(value)
    return {
        "tracking": earliest is not None,
        "tracking_since": _aware(earliest.observed_at) if earliest is not None else None,
        "window_hours": window_hours,
        "last_scan_at": last_scan_at,
        "cycles": cycles,
        "examined": examined,
        "accepted": accepted,
        "rejected": rejected,
        "deferred": deferred,
        "top_rejection_reasons": [
            {"reason": reason, "count": count} for reason, count in reasons.most_common(5)
        ],
        "metadata_totals": dict(sorted(metadata_totals.items())),
    }
