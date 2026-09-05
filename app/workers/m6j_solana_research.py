from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.forward_models import ForwardScanObservation, ForwardStudy
from app.m6k_research import solana_unknown_group
from app.research_acceleration import (
    classify_solana_candidate,
    compact_jupiter_quote,
    parse_csv_ints,
)
from app.scan_telemetry import record_scan_observation
from app.solana_forward import SolanaForwardConfig, SolanaLaunchBaselineForwardRunner
from app.venues.solana import JupiterShadowClient, USDC_MINT
from app.venues.solana_models import (
    SolanaForensicFeatureSnapshot,
    SolanaLaunchEvent,
    SolanaSecuritySnapshot,
)

log = logging.getLogger("edge_lab.m6j_solana")
ZERO = Decimal("0")
USDC_ATOMIC = Decimal("1000000")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _metadata(row: ForwardScanObservation) -> dict:
    try:
        value = json.loads(row.metadata_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _valid_public_quote(quote) -> bool:
    return bool(
        quote is not None
        and not quote.transaction_present
        and quote.out_amount > 0
        and quote.in_usd_value is not None
        and quote.out_usd_value is not None
        and Decimal(quote.in_usd_value) > ZERO
        and Decimal(quote.out_usd_value) > ZERO
    )


async def _quote(client: JupiterShadowClient, *, input_mint: str, output_mint: str, amount: int):
    try:
        return await client.order_quote(input_mint=input_mint, output_mint=output_mint, amount=amount)
    except Exception:
        return None


def _record_m6k_unknown_entry(
    db,
    *,
    study: ForwardStudy,
    launch: SolanaLaunchEvent,
    feature: SolanaForensicFeatureSnapshot,
    classification,
    quote_notional: Decimal,
    entry,
    exit_quote,
    observed_at: datetime,
) -> None:
    if classification.state != "UNKNOWN":
        return
    entry_valid = _valid_public_quote(entry)
    exit_valid = _valid_public_quote(exit_quote)
    entry_in = Decimal(entry.in_usd_value) if entry_valid else None
    immediate_exit = Decimal(exit_quote.out_usd_value) if exit_valid else None
    recovery_ratio = (
        immediate_exit / entry_in
        if immediate_exit is not None and entry_in is not None and entry_in > ZERO
        else None
    )
    record_scan_observation(
        db,
        study_id=study.id,
        external_key=f"m6k:sol:unknown-entry:{launch.signature}",
        observation_kind="candidate",
        observed_at=observed_at,
        rejection_reasons={reason: 1 for reason in classification.reasons},
        metadata={
            "research_lane": "m6k-sol",
            "research_mode": "unknown_decomposition_counterfactual_quote_only",
            "screen_version": "m6k-sol-v1",
            "launch_signature": launch.signature,
            "mint": launch.mint,
            "creator": launch.creator,
            "launch_at": _aware(launch.observed_at).isoformat(),
            "original_feature_id": feature.id,
            "original_feature_captured_at": _aware(feature.captured_at).isoformat(),
            "original_classification": classification.state,
            "original_unknown_reasons": list(classification.reasons),
            "unknown_group": solana_unknown_group(classification.reasons),
            "quote_notional_usd": str(quote_notional),
            "entry_quote_attempted": True,
            "entry_quote_available": entry_valid,
            "entry_quote": compact_jupiter_quote(entry),
            "immediate_exit_quote_available": exit_valid,
            "immediate_exit_quote": compact_jupiter_quote(exit_quote),
            "immediate_roundtrip_recovery_ratio": (
                str(recovery_ratio) if recovery_ratio is not None else None
            ),
            "immediate_roundtrip_pnl_usd": (
                str(immediate_exit - entry_in)
                if immediate_exit is not None and entry_in is not None
                else None
            ),
            "baseline_gate_unchanged": True,
            "unknown_treated_as_safe": False,
        },
    )


async def _sample_entries(client: JupiterShadowClient, db, study: ForwardStudy, *, now: datetime) -> dict[str, int]:
    settings = get_settings()
    config = SolanaForwardConfig.from_study(study)
    cutoff = now - timedelta(minutes=settings.m6j_solana_candidate_age_minutes)
    launches = db.scalars(
        select(SolanaLaunchEvent)
        .where(
            SolanaLaunchEvent.observed_at >= study.started_at,
            SolanaLaunchEvent.observed_at >= cutoff,
        )
        .order_by(SolanaLaunchEvent.observed_at.asc())
        .limit(2000)
    ).all()

    stats = {
        "examined": 0,
        "safe": 0,
        "unknown": 0,
        "unsafe": 0,
        "quote_attempts": 0,
        "entry_quotes": 0,
        "roundtrip_quotes": 0,
        "m6k_unknown_entries": 0,
    }
    quote_notional = Decimal(str(settings.m6j_solana_quote_notional_usd))
    if quote_notional <= ZERO or quote_notional > Decimal("100"):
        raise RuntimeError("M6J Solana quote notional must be >0 and <=100 simulated USD")
    entry_amount = int((quote_notional * USDC_ATOMIC).to_integral_value())

    for launch in launches:
        if stats["examined"] >= settings.m6j_solana_max_samples_per_cycle:
            break
        external_key = f"m6j:solana:entry:{launch.signature}"
        exists = db.scalar(
            select(ForwardScanObservation.id).where(
                ForwardScanObservation.study_id == study.id,
                ForwardScanObservation.external_key == external_key,
            )
        )
        if exists is not None:
            continue
        feature = SolanaLaunchBaselineForwardRunner._decision_feature(db, launch, config)
        if feature is None:
            continue
        security = SolanaLaunchBaselineForwardRunner._security_for_feature(db, feature)
        classification = classify_solana_candidate(feature, security)
        stats["examined"] += 1
        stats[classification.state.lower()] += 1

        metadata = {
            "research_lane": "m6j",
            "research_mode": "counterfactual_quote_only_no_execution",
            "classification": classification.state,
            "classification_reasons": list(classification.reasons),
            "launch_signature": launch.signature,
            "mint": launch.mint,
            "creator": launch.creator,
            "launch_at": _aware(launch.observed_at).isoformat(),
            "feature_id": feature.id,
            "feature_captured_at": _aware(feature.captured_at).isoformat(),
            "quote_notional_usd": str(quote_notional),
            "baseline_would_require_explicit_clean": True,
        }

        if classification.state == "UNSAFE":
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=external_key,
                observation_kind="candidate",
                observed_at=now,
                examined_count=1,
                rejected_count=1,
                rejection_reasons={reason: 1 for reason in classification.reasons},
                metadata={**metadata, "quote_attempted": False},
            )
            continue

        stats["quote_attempts"] += 1
        entry = await _quote(client, input_mint=USDC_MINT, output_mint=launch.mint, amount=entry_amount)
        if not _valid_public_quote(entry):
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=external_key,
                observation_kind="candidate",
                observed_at=now,
                examined_count=1,
                rejected_count=1,
                rejection_reasons={"COUNTERFACTUAL_ENTRY_QUOTE_UNAVAILABLE": 1},
                metadata={**metadata, "quote_attempted": True, "entry_quote": compact_jupiter_quote(entry)},
            )
            if settings.m6k_enabled and classification.state == "UNKNOWN":
                _record_m6k_unknown_entry(
                    db,
                    study=study,
                    launch=launch,
                    feature=feature,
                    classification=classification,
                    quote_notional=quote_notional,
                    entry=entry,
                    exit_quote=None,
                    observed_at=now,
                )
                stats["m6k_unknown_entries"] += 1
            continue

        stats["entry_quotes"] += 1
        exit_quote = await _quote(
            client,
            input_mint=launch.mint,
            output_mint=USDC_MINT,
            amount=entry.out_amount,
        )
        if _valid_public_quote(exit_quote):
            stats["roundtrip_quotes"] += 1
        entry_in = Decimal(entry.in_usd_value)
        immediate_exit = Decimal(exit_quote.out_usd_value) if _valid_public_quote(exit_quote) else None
        record_scan_observation(
            db,
            study_id=study.id,
            external_key=external_key,
            observation_kind="candidate",
            observed_at=_aware(entry.captured_at),
            examined_count=1,
            accepted_count=1,
            metadata={
                **metadata,
                "quote_attempted": True,
                "entry_quote": compact_jupiter_quote(entry),
                "immediate_exit_quote": compact_jupiter_quote(exit_quote),
                "entry_token_amount_atomic": entry.out_amount,
                "entry_in_usd": str(entry_in),
                "entry_out_usd": str(entry.out_usd_value),
                "entry_captured_at": _aware(entry.captured_at).isoformat(),
                "immediate_exit_usd": str(immediate_exit) if immediate_exit is not None else None,
                "immediate_roundtrip_pnl_usd": (
                    str(immediate_exit - entry_in) if immediate_exit is not None else None
                ),
            },
        )
        if settings.m6k_enabled and classification.state == "UNKNOWN":
            _record_m6k_unknown_entry(
                db,
                study=study,
                launch=launch,
                feature=feature,
                classification=classification,
                quote_notional=quote_notional,
                entry=entry,
                exit_quote=exit_quote,
                observed_at=_aware(entry.captured_at),
            )
            stats["m6k_unknown_entries"] += 1
    return stats


async def _sample_outcomes(
    client: JupiterShadowClient,
    db,
    study: ForwardStudy,
    *,
    now: datetime,
) -> tuple[int, int]:
    settings = get_settings()
    horizons = parse_csv_ints(
        settings.m6j_solana_outcome_horizons_minutes,
        minimum=1,
        maximum=24 * 60,
    )
    entries = db.scalars(
        select(ForwardScanObservation)
        .where(
            ForwardScanObservation.study_id == study.id,
            ForwardScanObservation.external_key.like("m6j:solana:entry:%"),
            ForwardScanObservation.accepted_count == 1,
        )
        .order_by(ForwardScanObservation.observed_at.asc())
    ).all()
    sampled = m6k_unknown_outcomes = 0
    for entry_row in entries:
        meta = _metadata(entry_row)
        try:
            mint = str(meta["mint"])
            launch_signature = str(meta["launch_signature"])
            amount = int(meta["entry_token_amount_atomic"])
            entry_in_usd = Decimal(str(meta["entry_in_usd"]))
            entry_at = datetime.fromisoformat(str(meta["entry_captured_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        for horizon in horizons:
            if sampled >= settings.m6j_solana_max_outcomes_per_cycle:
                return sampled, m6k_unknown_outcomes
            if now < _aware(entry_at) + timedelta(minutes=horizon):
                continue
            external_key = f"m6j:solana:outcome:{launch_signature}:{horizon}m"
            exists = db.scalar(
                select(ForwardScanObservation.id).where(
                    ForwardScanObservation.study_id == study.id,
                    ForwardScanObservation.external_key == external_key,
                )
            )
            if exists is not None:
                continue
            exit_quote = await _quote(client, input_mint=mint, output_mint=USDC_MINT, amount=amount)
            valid = _valid_public_quote(exit_quote)
            out_usd = Decimal(exit_quote.out_usd_value) if valid else None
            pnl = out_usd - entry_in_usd if out_usd is not None else None
            return_pct = (pnl / entry_in_usd * Decimal("100")) if pnl is not None and entry_in_usd > ZERO else None
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=external_key,
                observation_kind="candidate",
                observed_at=now,
                rejection_reasons={} if valid else {"COUNTERFACTUAL_EXIT_QUOTE_UNAVAILABLE": 1},
                metadata={
                    "research_lane": "m6j",
                    "research_mode": "counterfactual_outcome_quote_only_no_execution",
                    "launch_signature": launch_signature,
                    "mint": mint,
                    "classification": meta.get("classification"),
                    "horizon_minutes": horizon,
                    "entry_in_usd": str(entry_in_usd),
                    "exit_quote": compact_jupiter_quote(exit_quote),
                    "counterfactual_exit_usd": str(out_usd) if out_usd is not None else None,
                    "counterfactual_pnl_usd": str(pnl) if pnl is not None else None,
                    "counterfactual_return_pct": str(return_pct) if return_pct is not None else None,
                },
            )
            if settings.m6k_enabled and meta.get("classification") == "UNKNOWN":
                reasons = meta.get("classification_reasons") or []
                recovery_ratio = out_usd / entry_in_usd if out_usd is not None and entry_in_usd > ZERO else None
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=f"m6k:sol:outcome:{launch_signature}:{horizon}m",
                    observation_kind="candidate",
                    observed_at=now,
                    rejection_reasons={} if valid else {"COUNTERFACTUAL_EXIT_QUOTE_UNAVAILABLE": 1},
                    metadata={
                        "research_lane": "m6k-sol",
                        "research_mode": "unknown_group_counterfactual_outcome_quote_only",
                        "screen_version": "m6k-sol-v1",
                        "launch_signature": launch_signature,
                        "mint": mint,
                        "original_classification": "UNKNOWN",
                        "original_unknown_reasons": list(reasons),
                        "unknown_group": solana_unknown_group(reasons),
                        "horizon_minutes": horizon,
                        "exit_route_available": valid,
                        "entry_in_usd": str(entry_in_usd),
                        "counterfactual_exit_usd": str(out_usd) if out_usd is not None else None,
                        "counterfactual_pnl_usd": str(pnl) if pnl is not None else None,
                        "counterfactual_return_pct": str(return_pct) if return_pct is not None else None,
                        "recovery_ratio": str(recovery_ratio) if recovery_ratio is not None else None,
                        "exit_quote": compact_jupiter_quote(exit_quote),
                        "baseline_gate_unchanged": True,
                    },
                )
                m6k_unknown_outcomes += 1
            sampled += 1
    return sampled, m6k_unknown_outcomes


def _latest_feature_and_security(db, *, mint: str, after: datetime, now: datetime):
    feature = db.scalar(
        select(SolanaForensicFeatureSnapshot)
        .where(
            SolanaForensicFeatureSnapshot.mint == mint,
            SolanaForensicFeatureSnapshot.captured_at >= after,
            SolanaForensicFeatureSnapshot.captured_at <= now,
        )
        .order_by(SolanaForensicFeatureSnapshot.captured_at.desc())
        .limit(1)
    )
    security = db.scalar(
        select(SolanaSecuritySnapshot)
        .where(
            SolanaSecuritySnapshot.mint == mint,
            SolanaSecuritySnapshot.captured_at >= after,
            SolanaSecuritySnapshot.captured_at <= now,
        )
        .order_by(SolanaSecuritySnapshot.captured_at.desc())
        .limit(1)
    )
    return feature, security


def _sample_unknown_resolutions(db, study: ForwardStudy, *, now: datetime) -> tuple[int, int]:
    settings = get_settings()
    if not settings.m6k_enabled:
        return 0, 0
    cutoff = now - timedelta(hours=max(1, settings.m6k_solana_resolution_lookback_hours))
    rows = db.scalars(
        select(ForwardScanObservation)
        .where(
            ForwardScanObservation.study_id == study.id,
            ForwardScanObservation.external_key.like("m6k:sol:unknown-entry:%"),
            ForwardScanObservation.observed_at >= cutoff,
            ForwardScanObservation.observed_at <= now,
        )
        .order_by(ForwardScanObservation.observed_at.asc())
        .limit(2000)
    ).all()
    resolved_safe = resolved_unsafe = checked = 0
    check_limit = max(1, settings.m6k_solana_resolution_max_per_cycle)
    for row in rows:
        meta = _metadata(row)
        try:
            launch_signature = str(meta["launch_signature"])
            mint = str(meta["mint"])
            original_feature_at = datetime.fromisoformat(
                str(meta["original_feature_captured_at"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            continue
        resolution_key = f"m6k:sol:resolution:{launch_signature}"
        exists = db.scalar(
            select(ForwardScanObservation.id).where(
                ForwardScanObservation.study_id == study.id,
                ForwardScanObservation.external_key == resolution_key,
            )
        )
        if exists is not None:
            continue
        if checked >= check_limit:
            break
        checked += 1
        feature, security = _latest_feature_and_security(
            db,
            mint=mint,
            after=_aware(original_feature_at),
            now=now,
        )
        if feature is None:
            continue
        classification = classify_solana_candidate(feature, security)
        if classification.state == "UNKNOWN":
            continue
        resolved_safe += int(classification.state == "SAFE")
        resolved_unsafe += int(classification.state == "UNSAFE")
        resolution_at = _aware(feature.captured_at)
        if security is not None:
            resolution_at = max(resolution_at, _aware(security.captured_at))
        lag_minutes = (
            resolution_at - _aware(original_feature_at)
        ).total_seconds() / 60
        record_scan_observation(
            db,
            study_id=study.id,
            external_key=resolution_key,
            observation_kind="candidate",
            observed_at=resolution_at,
            metadata={
                "research_lane": "m6k-sol",
                "research_mode": "later_evidence_resolution_observation_only",
                "screen_version": "m6k-sol-v1",
                "launch_signature": launch_signature,
                "mint": mint,
                "unknown_group": meta.get("unknown_group"),
                "original_unknown_reasons": meta.get("original_unknown_reasons") or [],
                "original_feature_captured_at": _aware(original_feature_at).isoformat(),
                "resolved_state": classification.state,
                "resolved_reasons": list(classification.reasons),
                "resolved_feature_id": feature.id,
                "resolved_feature_captured_at": _aware(feature.captured_at).isoformat(),
                "resolved_security_id": security.id if security is not None else None,
                "resolved_security_captured_at": (
                    _aware(security.captured_at).isoformat() if security is not None else None
                ),
                "resolved_at": resolution_at.isoformat(),
                "resolution_lag_minutes": str(lag_minutes),
                "original_decision_record_mutated": False,
                "baseline_gate_unchanged": True,
            },
        )
    return resolved_safe, resolved_unsafe


async def _cycle(client: JupiterShadowClient) -> None:
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        study = db.scalar(
            select(ForwardStudy)
            .where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "solana",
                ForwardStudy.family == "meme",
            )
            .order_by(ForwardStudy.started_at.asc())
            .limit(1)
        )
        if study is None:
            return
        now = datetime.now(timezone.utc)
        stats = await _sample_entries(client, db, study, now=now)
        outcomes, m6k_unknown_outcomes = await _sample_outcomes(client, db, study, now=now)
        resolved_safe, resolved_unsafe = _sample_unknown_resolutions(db, study, now=now)
        bucket = int(now.timestamp() // settings.m6j_solana_poll_seconds)
        record_scan_observation(
            db,
            study_id=study.id,
            external_key=f"m6j:solana:cycle:{bucket}",
            observation_kind="cycle",
            observed_at=now,
            metadata={
                "research_lane": "m6j",
                "research_mode": "counterfactual_quote_only_no_execution",
                "m6j_candidates_examined": stats["examined"],
                "m6j_safe_candidates": stats["safe"],
                "m6j_unknown_candidates": stats["unknown"],
                "m6j_unsafe_candidates": stats["unsafe"],
                "m6j_counterfactual_quote_attempts": stats["quote_attempts"],
                "m6j_counterfactual_entry_quotes": stats["entry_quotes"],
                "m6j_counterfactual_roundtrip_quotes": stats["roundtrip_quotes"],
                "m6j_counterfactual_outcomes": outcomes,
            },
        )
        if settings.m6k_enabled:
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=f"m6k:sol:cycle:{bucket}",
                observation_kind="cycle",
                observed_at=now,
                metadata={
                    "research_lane": "m6k-sol",
                    "research_mode": "unknown_decomposition_observation_only",
                    "screen_version": "m6k-sol-v1",
                    "m6k_sol_unknown_entries": stats["m6k_unknown_entries"],
                    "m6k_sol_unknown_outcomes": m6k_unknown_outcomes,
                    "m6k_sol_resolutions_safe": resolved_safe,
                    "m6k_sol_resolutions_unsafe": resolved_unsafe,
                },
            )
        log.info(
            "M6J/M6K Solana cycle: examined=%s unknown=%s unsafe=%s entry_quotes=%s outcomes=%s m6k_unknown=%s resolved_safe=%s resolved_unsafe=%s",
            stats["examined"],
            stats["unknown"],
            stats["unsafe"],
            stats["entry_quotes"],
            outcomes,
            stats["m6k_unknown_entries"],
            resolved_safe,
            resolved_unsafe,
        )
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    if not settings.m6j_enabled:
        log.info("M6J is disabled")
        return
    if not settings.jupiter_api_key:
        raise RuntimeError("M6J/M6K Solana research requires JUPITER_API_KEY for quote-only observation")
    async with JupiterShadowClient(
        api_key=settings.jupiter_api_key,
        timeout_seconds=settings.jupiter_timeout_seconds,
    ) as client:
        while True:
            try:
                await _cycle(client)
            except Exception:
                log.exception("M6J/M6K Solana cycle failed")
            await asyncio.sleep(settings.m6j_solana_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
