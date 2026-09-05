from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

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
    # M6J research-acceleration telemetry. These are observation counters only;
    # they never alter baseline trade/evaluation evidence.
    "m6j_horizons_tested",
    "m6j_assets_tested",
    "m6j_candidates_examined",
    "m6j_positive_edge_candidates",
    "m6j_nonpositive_edge_candidates",
    "m6j_ws_messages",
    "m6j_book_events",
    "m6j_pair_checks",
    "m6j_binary_checks",
    "m6j_negrisk_checks",
    "m6j_positive_edge_events",
    "m6j_baseline_10bps_edge_events",
    "m6j_markets_subscribed",
    "m6j_assets_subscribed",
    "m6j_safe_candidates",
    "m6j_unknown_candidates",
    "m6j_unsafe_candidates",
    "m6j_counterfactual_quote_attempts",
    "m6j_counterfactual_entry_quotes",
    "m6j_counterfactual_roundtrip_quotes",
    "m6j_counterfactual_outcomes",
    # M6K strategy-design telemetry. These lanes remain observation-only and are
    # intentionally excluded from frozen baseline/evaluation evidence.
    "m6k_hl_candidates_examined",
    "m6k_hl_screen_passed",
    "m6k_hl_screen_rejected",
    "m6k_pm_event_checks",
    "m6k_pm_valid_observations",
    "m6k_pm_positive_violations",
    "m6k_pm_baseline_qualified",
    "m6k_sol_unknown_entries",
    "m6k_sol_unknown_outcomes",
    "m6k_sol_resolutions_safe",
    "m6k_sol_resolutions_unsafe",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), default=str, sort_keys=True, separators=(",", ":"))


def _metadata(row: ForwardScanObservation) -> dict[str, Any]:
    try:
        value = json.loads(row.metadata_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _lane_token(lane: str) -> str:
    return f'"research_lane":"{lane.strip()}"'


def _apply_lane_filters(stmt, *, research_lane: str | None, exclude_research_lanes: Sequence[str]):
    if research_lane:
        stmt = stmt.where(ForwardScanObservation.metadata_json.contains(_lane_token(research_lane)))
    for lane in exclude_research_lanes:
        if lane.strip():
            stmt = stmt.where(~ForwardScanObservation.metadata_json.contains(_lane_token(lane)))
    return stmt


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
    research_lane: str | None = None,
    exclude_research_lanes: Sequence[str] = (),
) -> dict[str, Any]:
    """Summarize durable scan telemetry with optional lane isolation.

    M6J/M6K intentionally write observation-only telemetry under the same study foreign
    key as the frozen baseline they compare against. Lane filters keep those observations
    analytically separate so baseline activity counts are never inflated by challenger
    research.
    """

    if research_lane and research_lane in exclude_research_lanes:
        raise ValueError("research_lane cannot also be excluded")
    now = _aware(now)
    since = now - timedelta(hours=window_hours)
    rows_stmt = select(ForwardScanObservation).where(
        ForwardScanObservation.study_id == study_id,
        ForwardScanObservation.observed_at >= since,
        ForwardScanObservation.observed_at <= now,
    )
    rows_stmt = _apply_lane_filters(
        rows_stmt,
        research_lane=research_lane,
        exclude_research_lanes=exclude_research_lanes,
    )
    rows = db.scalars(rows_stmt.order_by(ForwardScanObservation.observed_at.asc())).all()

    earliest_stmt = select(ForwardScanObservation).where(ForwardScanObservation.study_id == study_id)
    earliest_stmt = _apply_lane_filters(
        earliest_stmt,
        research_lane=research_lane,
        exclude_research_lanes=exclude_research_lanes,
    )
    earliest = db.scalar(earliest_stmt.order_by(ForwardScanObservation.observed_at.asc()).limit(1))

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
        meta = _metadata(row)
        for key in _NUMERIC_METADATA_KEYS:
            value = meta.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metadata_totals[key] += int(value)
    return {
        "tracking": earliest is not None,
        "tracking_since": _aware(earliest.observed_at) if earliest is not None else None,
        "research_lane": research_lane,
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
