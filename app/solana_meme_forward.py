from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forward_models import ForwardExecutionRecord, ForwardScanObservation, ForwardStudy
from app.scan_telemetry import record_scan_observation
from app.forward_research import ForwardResearchService
from app.solana_forward import (
    ZERO,
    SolanaForwardConfig,
    SolanaForwardTick,
    _aware,
)
from app.solana_forward_operational import OperationalSolanaLaunchBaselineForwardRunner
from app.venues.solana import USDC_MINT
from app.venues.solana_models import (
    SolanaForensicFeatureSnapshot,
    SolanaLaunchEvent,
    SolanaSecuritySnapshot,
)

M6L_RUNNER = "solana_meme_momentum_m6l_v1"
M6L_INSTRUMENT = "PUMP_MOMENTUM_M6L"
M6L_STRATEGY_SLUG = "solana-pump-momentum-paper"
M6L_STRATEGY_NAME = "Solana Pump Momentum Paper"
M6L_STRATEGY_VERSION = "m6l-v2"
M6L_STRICT_EXTERNAL_ID = "solana-meme-momentum-strict-m6l-v2"
M6L_EXPLORATORY_EXTERNAL_ID = "solana-meme-momentum-exploratory-m6l-v2"


class M6LMemeConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class M6LMemeConfig:
    cohort: str
    min_alpha_score: int
    min_momentum_score: Decimal
    min_volume_acceleration: Decimal
    max_sell_ratio_5m: Decimal
    max_5m_loss_pct: Decimal
    max_5m_spike_pct: Decimal
    hard_stop_recovery_ratio: Decimal
    trail_arm_ratio: Decimal
    trail_drawdown_ratio: Decimal
    high_trail_arm_ratio: Decimal
    high_trail_drawdown_ratio: Decimal
    feature_refresh_seconds: int

    @classmethod
    def from_study(cls, study: ForwardStudy) -> "M6LMemeConfig":
        try:
            raw = json.loads(study.study_config_json)
        except json.JSONDecodeError as exc:
            raise M6LMemeConfigError("M6L study config is invalid JSON") from exc
        if not isinstance(raw, dict) or raw.get("strategy_runner") != M6L_RUNNER:
            raise M6LMemeConfigError(f"M6L study must declare strategy_runner={M6L_RUNNER}")
        try:
            config = cls(
                cohort=str(raw["cohort"]).strip().lower(),
                min_alpha_score=int(raw["min_alpha_score"]),
                min_momentum_score=Decimal(str(raw["min_momentum_score"])),
                min_volume_acceleration=Decimal(str(raw["min_volume_acceleration"])),
                max_sell_ratio_5m=Decimal(str(raw["max_sell_ratio_5m"])),
                max_5m_loss_pct=Decimal(str(raw["max_5m_loss_pct"])),
                max_5m_spike_pct=Decimal(str(raw["max_5m_spike_pct"])),
                hard_stop_recovery_ratio=Decimal(str(raw["hard_stop_recovery_ratio"])),
                trail_arm_ratio=Decimal(str(raw["trail_arm_ratio"])),
                trail_drawdown_ratio=Decimal(str(raw["trail_drawdown_ratio"])),
                high_trail_arm_ratio=Decimal(str(raw["high_trail_arm_ratio"])),
                high_trail_drawdown_ratio=Decimal(str(raw["high_trail_drawdown_ratio"])),
                feature_refresh_seconds=int(raw["feature_refresh_seconds"]),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise M6LMemeConfigError(f"invalid M6L meme configuration: {exc}") from exc
        config.validate()
        return config

    def validate(self) -> None:
        if self.cohort not in {"strict", "exploratory"}:
            raise M6LMemeConfigError("cohort must be strict or exploratory")
        if self.min_alpha_score < 1 or self.min_alpha_score > 10:
            raise M6LMemeConfigError("min_alpha_score must be between 1 and 10")
        if self.min_momentum_score < Decimal("-1") or self.min_momentum_score > Decimal("1"):
            raise M6LMemeConfigError("min_momentum_score outside [-1, 1]")
        if self.min_volume_acceleration < ZERO:
            raise M6LMemeConfigError("min_volume_acceleration cannot be negative")
        if self.max_sell_ratio_5m <= ZERO or self.max_sell_ratio_5m > Decimal("1"):
            raise M6LMemeConfigError("max_sell_ratio_5m must be in (0, 1]")
        if self.max_5m_loss_pct <= ZERO or self.max_5m_spike_pct <= ZERO:
            raise M6LMemeConfigError("5m guard thresholds must be positive")
        if not (ZERO < self.hard_stop_recovery_ratio < Decimal("1")):
            raise M6LMemeConfigError("hard stop ratio must be between 0 and 1")
        if not (Decimal("1") < self.trail_arm_ratio < self.high_trail_arm_ratio):
            raise M6LMemeConfigError("trailing arm ratios are invalid")
        if not (ZERO < self.trail_drawdown_ratio < Decimal("1")):
            raise M6LMemeConfigError("trail drawdown ratio must be in (0, 1)")
        if not (ZERO < self.high_trail_drawdown_ratio < Decimal("1")):
            raise M6LMemeConfigError("high trail drawdown ratio must be in (0, 1)")
        if self.feature_refresh_seconds < 30 or self.feature_refresh_seconds > 600:
            raise M6LMemeConfigError("feature_refresh_seconds must be 30..600")


def _missing_fields(feature: SolanaForensicFeatureSnapshot) -> tuple[str, ...]:
    try:
        value = json.loads(feature.missing_fields_json)
    except (json.JSONDecodeError, TypeError):
        return ("INVALID_MISSING_FIELDS_JSON",)
    if not isinstance(value, list):
        return ("INVALID_MISSING_FIELDS_JSON",)
    return tuple(str(item).strip().upper() for item in value if str(item).strip())


def security_gate(
    feature: SolanaForensicFeatureSnapshot,
    security: SolanaSecuritySnapshot | None,
    *,
    cohort: str,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Separate known unsafe conditions from uncertainty.

    Exploratory paper trading may study UNKNOWN states, but known mechanical hazards remain
    hard blocks. Strict paper trading requires the same fields to be conclusively clean.
    """

    blocked: list[str] = []
    unknown: list[str] = []

    if feature.mintable is True:
        blocked.append("MINT_AUTHORITY_ACTIVE")
    elif feature.mintable is None:
        unknown.append("MINT_AUTHORITY_UNKNOWN")
    if feature.freezable is True:
        blocked.append("FREEZE_AUTHORITY_ACTIVE")
    elif feature.freezable is None:
        unknown.append("FREEZE_AUTHORITY_UNKNOWN")
    if feature.malicious_creator is True:
        blocked.append("MALICIOUS_CREATOR_KNOWN")
    elif feature.malicious_creator is None:
        unknown.append("CREATOR_SECURITY_UNKNOWN")
    if feature.transfer_fee_rate is not None:
        if Decimal(feature.transfer_fee_rate) != ZERO:
            blocked.append("NONZERO_TRANSFER_FEE_KNOWN")
    else:
        unknown.append("TRANSFER_FEE_UNKNOWN")

    if security is None:
        unknown.append("SECURITY_SNAPSHOT_MISSING")
    else:
        if security.non_transferable is True:
            blocked.append("NON_TRANSFERABLE_KNOWN")
        elif security.non_transferable is None:
            unknown.append("NON_TRANSFERABLE_UNKNOWN")
        if security.mintable is True:
            blocked.append("SECURITY_MINT_AUTHORITY_ACTIVE")
        elif security.mintable is None:
            unknown.append("SECURITY_MINT_AUTHORITY_UNKNOWN")
        if security.freezable is True:
            blocked.append("SECURITY_FREEZE_AUTHORITY_ACTIVE")
        elif security.freezable is None:
            unknown.append("SECURITY_FREEZE_AUTHORITY_UNKNOWN")
        if security.malicious_creator is True:
            blocked.append("SECURITY_MALICIOUS_CREATOR_KNOWN")
        elif security.malicious_creator is None:
            unknown.append("SECURITY_CREATOR_UNKNOWN")

    missing = _missing_fields(feature)
    for field in missing:
        if field in {"SECURITY_SNAPSHOT", "ASSET_METADATA"}:
            unknown.append(f"{field}_MISSING")

    blocked = list(dict.fromkeys(blocked))
    unknown = list(dict.fromkeys(unknown))
    if blocked:
        return False, tuple(blocked), tuple(unknown)
    if cohort == "strict" and unknown:
        return False, tuple(), tuple(unknown)
    return True, tuple(), tuple(unknown)


def alpha_score(
    feature: SolanaForensicFeatureSnapshot,
    config: M6LMemeConfig,
) -> tuple[int, bool, tuple[str, ...], dict[str, Any]]:
    """Preregistered M6L-v1 flow score using only decision-time features."""

    score = 0
    reasons: list[str] = []
    components: dict[str, Any] = {
        "age_minutes": str(feature.age_minutes),
        "momentum_score": str(feature.momentum_score) if feature.momentum_score is not None else None,
        "sell_ratio_5m": str(feature.sell_ratio_5m) if feature.sell_ratio_5m is not None else None,
        "volume_acceleration": (
            str(feature.volume_acceleration) if feature.volume_acceleration is not None else None
        ),
        "price_change_5m": (
            str(feature.price_change_5m) if feature.price_change_5m is not None else None
        ),
        "market_cap": str(feature.market_cap) if feature.market_cap is not None else None,
        "liquidity_usd": str(feature.liquidity_usd) if feature.liquidity_usd is not None else None,
    }

    momentum = Decimal(feature.momentum_score) if feature.momentum_score is not None else None
    if momentum is not None and momentum >= config.min_momentum_score:
        score += 2
    else:
        reasons.append("MOMENTUM_BELOW_ENTRY")

    acceleration = (
        Decimal(feature.volume_acceleration) if feature.volume_acceleration is not None else None
    )
    if acceleration is not None and acceleration >= config.min_volume_acceleration:
        score += 1
    elif acceleration is not None:
        reasons.append("VOLUME_ACCELERATION_BELOW_ENTRY")

    sell_ratio = Decimal(feature.sell_ratio_5m) if feature.sell_ratio_5m is not None else None
    if sell_ratio is not None and sell_ratio <= config.max_sell_ratio_5m:
        score += 1
    elif sell_ratio is not None:
        reasons.append("SELL_PRESSURE_TOO_HIGH")

    age = Decimal(feature.age_minutes)
    if age <= Decimal("12"):
        score += 1

    if feature.market_cap is not None and Decimal(feature.market_cap) >= Decimal("1000"):
        score += 1

    change_5m = Decimal(feature.price_change_5m) if feature.price_change_5m is not None else None
    if change_5m is not None:
        if change_5m <= -config.max_5m_loss_pct:
            reasons.append("EARLY_PRICE_COLLAPSE")
        elif change_5m >= config.max_5m_spike_pct:
            reasons.append("EXTREME_SHORT_WINDOW_SPIKE")
        elif change_5m > ZERO:
            score += 1

    hard_reject = any(
        reason in {"MOMENTUM_BELOW_ENTRY", "VOLUME_ACCELERATION_BELOW_ENTRY", "SELL_PRESSURE_TOO_HIGH", "EARLY_PRICE_COLLAPSE", "EXTREME_SHORT_WINDOW_SPIKE"}
        for reason in reasons
    )
    if score < config.min_alpha_score:
        reasons.append("ALPHA_SCORE_BELOW_ENTRY")
    accepted = not hard_reject and score >= config.min_alpha_score
    components["score"] = score
    return score, accepted, tuple(dict.fromkeys(reasons)), components


class OperationalSolanaMemeMomentumForwardRunner(OperationalSolanaLaunchBaselineForwardRunner):
    """Active quote-only paper/shadow meme challenger; never submits a transaction."""

    @staticmethod
    def _m6l_candidate_key(cohort: str, launch: SolanaLaunchEvent, feature: SolanaForensicFeatureSnapshot) -> str:
        return f"m6l-sol:{cohort}:candidate:{launch.signature}:{feature.id}"

    @staticmethod
    def _mark_prefix(signature: str) -> str:
        return f"m6l-sol-mark:{signature}:"

    @classmethod
    def _peak_recovery_ratio(cls, db: Session, study_id: str, signature: str) -> Decimal:
        rows = db.scalars(
            select(ForwardScanObservation).where(
                ForwardScanObservation.study_id == study_id,
                ForwardScanObservation.external_key.like(f"{cls._mark_prefix(signature)}%"),
            )
        ).all()
        peak = ZERO
        for row in rows:
            try:
                meta = json.loads(row.metadata_json)
                value = Decimal(str(meta.get("recovery_ratio")))
            except (json.JSONDecodeError, TypeError, ValueError, ArithmeticError):
                continue
            peak = max(peak, value)
        return peak

    async def _executable_equity(self, db, study, config, *, now):
        if json.loads(study.study_config_json).get("implementation_revision") == "m6l-v2":
            config = replace(config, max_quote_price_impact_pct=Decimal("1"))
        return await super()._executable_equity(db, study, config, now=now)

    async def _latest_feature(
        self,
        db: Session,
        launch: SolanaLaunchEvent,
        base: SolanaForwardConfig,
        m6l: M6LMemeConfig,
        *,
        now: datetime,
    ) -> SolanaForensicFeatureSnapshot | None:
        launch_at = _aware(launch.observed_at)
        lower = launch_at + timedelta(minutes=base.decision_delay_minutes)
        upper = launch_at + timedelta(minutes=base.max_candidate_age_minutes)
        now = _aware(now)
        if now < lower or now > upper:
            return None
        latest = db.scalar(
            select(SolanaForensicFeatureSnapshot)
            .where(
                SolanaForensicFeatureSnapshot.mint == launch.mint,
                SolanaForensicFeatureSnapshot.captured_at >= lower,
                SolanaForensicFeatureSnapshot.captured_at <= now,
            )
            .order_by(SolanaForensicFeatureSnapshot.captured_at.desc())
            .limit(1)
        )
        if latest is not None:
            age_seconds = (now - _aware(latest.captured_at)).total_seconds()
            if age_seconds <= m6l.feature_refresh_seconds:
                return latest
        feature = await self.forensics.analyze_mint(
            db,
            mint=launch.mint,
            exit_test_notional_usd=base.entry_notional_usd,
        )
        captured = _aware(feature.captured_at)
        if captured < lower or captured > upper:
            return latest
        return feature

    async def _attempt_new_entries(
        self,
        db: Session,
        study: ForwardStudy,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> tuple[int, int]:
        # Historical v1 studies drain existing positions but cannot open new ones.
        if json.loads(study.study_config_json).get("implementation_revision") != "m6l-v2":
            return 0, 0
        m6l = M6LMemeConfig.from_study(study)
        attempted = self._attempted_signatures(db, study.id)
        open_positions = self._open_positions(db, study.id)
        capacity = max(0, config.max_open_positions - len(open_positions))
        cycle_bucket = int(_aware(now).timestamp() // 60)
        cycle_key = f"m6l-sol:{m6l.cohort}:cycle:{cycle_bucket}"
        if capacity <= 0:
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=cycle_key,
                observation_kind="cycle",
                observed_at=now,
                deferred_count=1,
                metadata={"research_lane": "m6l-sol-paper", "cohort": m6l.cohort, "open_positions": len(open_positions)},
            )
            return 0, 0

        equity = self._equity(db, study)
        allocated_open = sum((position.allocated_capital_usd for position in open_positions), ZERO)
        if allocated_open + config.entry_notional_usd > equity:
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=cycle_key,
                observation_kind="cycle",
                observed_at=now,
                deferred_count=1,
                metadata={"research_lane": "m6l-sol-paper", "cohort": m6l.cohort, "capital_capacity_blocked": 1},
            )
            return 0, 0

        cutoff = _aware(now) - timedelta(minutes=config.max_candidate_age_minutes)
        launches = db.scalars(
            select(SolanaLaunchEvent)
            .where(
                SolanaLaunchEvent.observed_at >= study.started_at,
                SolanaLaunchEvent.observed_at >= cutoff,
            )
            .order_by(SolanaLaunchEvent.observed_at.asc())
            .limit(1000)
        ).all()

        opened = quote_attempts = features_ready = alpha_passed = security_passed = 0
        scan_started = time.monotonic()
        for launch in launches:
            if time.monotonic() - scan_started > 10:
                break
            if launch.signature in attempted:
                continue
            if opened >= min(capacity, config.max_entries_per_cycle):
                break
            feature = await self._latest_feature(db, launch, config, m6l, now=now)
            if feature is None:
                continue
            features_ready += 1
            security = self._security_for_feature(db, feature)
            security_ok, blocked_reasons, unknown_reasons = security_gate(
                feature, security, cohort=m6l.cohort
            )
            score, alpha_ok, alpha_reasons, components = alpha_score(feature, m6l)
            security_passed += int(security_ok)
            alpha_passed += int(alpha_ok)
            accepted = security_ok and alpha_ok
            reasons = list(blocked_reasons)
            if m6l.cohort == "strict" and unknown_reasons:
                reasons.extend(f"STRICT_{reason}" for reason in unknown_reasons)
            reasons.extend(alpha_reasons)
            key = self._m6l_candidate_key(m6l.cohort, launch, feature)
            metadata = {
                "research_lane": "m6l-sol-paper",
                "strategy_version": M6L_STRATEGY_VERSION,
                "implementation_revision": "m6l-v2",
                "cohort": m6l.cohort,
                "mint": launch.mint,
                "launch_signature": launch.signature,
                "feature_id": feature.id,
                "feature_captured_at": _aware(feature.captured_at).isoformat(),
                "alpha_score": score,
                "alpha_components": components,
                "known_unsafe_reasons": list(blocked_reasons),
                "unknown_security_reasons": list(unknown_reasons),
                "paper_eligible": accepted,
            }
            if not accepted:
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=key,
                    observation_kind="candidate",
                    observed_at=_aware(feature.captured_at),
                    examined_count=1,
                    rejected_count=1,
                    rejection_reasons={reason: 1 for reason in reasons or ["M6L_FILTER_REJECT"]},
                    metadata=metadata,
                )
                continue

            if allocated_open + (opened + 1) * config.entry_notional_usd > equity:
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=key,
                    observation_kind="candidate",
                    observed_at=_aware(feature.captured_at),
                    examined_count=1,
                    rejected_count=1,
                    rejection_reasons={"SIMULATED_EQUITY_INSUFFICIENT": 1},
                    metadata=metadata,
                )
                break

            quote_attempts += 1
            did_open = await self._attempt_entry(db, study, launch, feature, config)
            if did_open:
                opened += 1
                metadata["status"] = "opened"
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=key,
                    observation_kind="candidate",
                    observed_at=datetime.now(timezone.utc),
                    examined_count=1,
                    accepted_count=1,
                    metadata=metadata,
                )
            else:
                execution = db.scalar(
                    select(ForwardExecutionRecord).where(
                        ForwardExecutionRecord.study_id == study.id,
                        ForwardExecutionRecord.external_key == self._entry_key(launch.signature),
                    )
                )
                reason = "QUOTE_STAGE_REJECTED"
                if execution is not None:
                    try:
                        reason = str(json.loads(execution.metadata_json).get("reason") or reason)
                    except (json.JSONDecodeError, TypeError):
                        pass
                metadata["status"] = "execution_rejected"
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=key,
                    observation_kind="candidate",
                    observed_at=datetime.now(timezone.utc),
                    examined_count=1,
                    rejected_count=1,
                    rejection_reasons={reason: 1},
                    metadata=metadata,
                )

        record_scan_observation(
            db,
            study_id=study.id,
            external_key=cycle_key,
            observation_kind="cycle",
            observed_at=now,
            metadata={
                "research_lane": "m6l-sol-paper",
                "cohort": m6l.cohort,
                "launches_in_window": len(launches),
                "features_ready": features_ready,
                "security_passed": security_passed,
                "alpha_passed": alpha_passed,
                "quote_attempts": quote_attempts,
                "opened": opened,
            },
        )
        return opened, quote_attempts

    async def _exit_due_positions(
        self,
        db: Session,
        study: ForwardStudy,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> tuple[int, int]:
        m6l = M6LMemeConfig.from_study(study)
        if json.loads(study.study_config_json).get("implementation_revision") == "m6l-v2":
            # A real full-size adverse exit is a loss to record, not an absent route.
            config = replace(config, max_quote_price_impact_pct=Decimal("1"))
        closed_count = failed_attempts = 0
        for position in self._open_positions(db, study.id):
            now = _aware(now)
            deadline = _aware(position.hold_until) + timedelta(minutes=config.max_exit_delay_minutes)
            if now > deadline:
                row = self._record_exit_execution(
                    db,
                    study,
                    position,
                    config,
                    paper=None,
                    shadow=None,
                    status="forced_loss",
                    reason="NO_EXECUTABLE_EXIT_BEFORE_DEADLINE",
                    now=now,
                )
                self._trade_from_exit_metadata(db, study, row)
                closed_count += 1
                continue

            paper = await self._quote(
                input_mint=position.mint,
                output_mint=USDC_MINT,
                amount=position.token_amount_atomic,
            )
            paper_valid = self._quote_valid(
                paper,
                input_mint=position.mint,
                output_mint=USDC_MINT,
                input_amount=position.token_amount_atomic,
                max_price_impact=config.max_quote_price_impact_pct,
            )
            if paper_valid:
                await self._sleep_delay(config)
            shadow = (
                await self._quote(
                    input_mint=position.mint,
                    output_mint=USDC_MINT,
                    amount=position.token_amount_atomic,
                )
                if paper_valid
                else None
            )
            shadow_valid = self._quote_valid(
                shadow,
                input_mint=position.mint,
                output_mint=USDC_MINT,
                input_amount=position.token_amount_atomic,
                max_price_impact=config.max_quote_price_impact_pct,
            )
            if not paper_valid or not shadow_valid or shadow is None:
                self._record_exit_execution(
                    db,
                    study,
                    position,
                    config,
                    paper=paper,
                    shadow=shadow,
                    status="retry",
                    reason="EXIT_QUOTE_NOT_FULLY_EXECUTABLE",
                    now=now,
                )
                failed_attempts += 1
                continue

            recovery = Decimal(shadow.out_usd_value) / position.entry_in_usd
            bucket = _aware(shadow.captured_at).isoformat()
            mark_key = f"{self._mark_prefix(position.launch_signature)}{bucket}"
            record_scan_observation(
                db,
                study_id=study.id,
                external_key=mark_key,
                observation_kind="candidate",
                observed_at=_aware(shadow.captured_at),
                examined_count=1,
                accepted_count=1,
                metadata={
                    "research_lane": "m6l-sol-paper-mark",
                    "cohort": m6l.cohort,
                    "launch_signature": position.launch_signature,
                    "mint": position.mint,
                    "recovery_ratio": str(recovery),
                    "executable_exit_usd": str(shadow.out_usd_value),
                    "entry_usd": str(position.entry_in_usd),
                },
            )
            peak = self._peak_recovery_ratio(db, study.id, position.launch_signature)
            exit_reason: str | None = None
            if recovery <= m6l.hard_stop_recovery_ratio:
                exit_reason = "M6L_HARD_STOP"
            elif peak >= m6l.high_trail_arm_ratio and recovery <= peak * (
                Decimal("1") - m6l.high_trail_drawdown_ratio
            ):
                exit_reason = "M6L_HIGH_TRAILING_REVERSAL"
            elif peak >= m6l.trail_arm_ratio and recovery <= peak * (
                Decimal("1") - m6l.trail_drawdown_ratio
            ):
                exit_reason = "M6L_TRAILING_REVERSAL"
            elif now >= _aware(position.hold_until):
                exit_reason = "M6L_TIME_STOP"

            if exit_reason is None:
                continue
            row = self._record_exit_execution(
                db,
                study,
                position,
                config,
                paper=paper,
                shadow=shadow,
                status="closed",
                reason=exit_reason,
                now=now,
            )
            self._trade_from_exit_metadata(db, study, row)
            closed_count += 1
        return closed_count, failed_attempts

    async def run_active_studies(
        self,
        db: Session,
        *,
        now: datetime | None = None,
    ) -> list[SolanaForwardTick]:
        now = _aware(now or datetime.now(timezone.utc))
        studies = db.scalars(
            select(ForwardStudy).where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "solana",
                ForwardStudy.family == "meme",
                ForwardStudy.instrument == M6L_INSTRUMENT,
            )
        ).all()
        results: list[SolanaForwardTick] = []
        entry_studies = []
        for study in studies:
            blocked = self._block_reason(study.id, db)
            if blocked is not None:
                results.append(SolanaForwardTick(study.id, "blocked", blocked))
                continue
            try:
                M6LMemeConfig.from_study(study)
                tick = await self.run_study_once(db, study, now=now, allow_entries=False)
                results.append(tick)
                if tick.action == "cycle":
                    if json.loads(study.study_config_json).get("implementation_revision") == "m6l-v2":
                        entry_studies.append(study)
                    elif not self._open_positions(db, study.id):
                        # Preserve and close historical evidence; no reset or relabelling.
                        finished_at = datetime.now(timezone.utc)
                        ForwardResearchService.evaluate_study(db, study_id=study.id, evaluated_at=finished_at)
                        ForwardResearchService.complete_study(db, study_id=study.id, completed_at=finished_at)
            except Exception as exc:
                db.rollback()
                self._record_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="M6L_SOLANA_FORWARD_ERROR",
                    message=f"{type(exc).__name__}: {exc}",
                    data_integrity=False,
                )
                results.append(SolanaForwardTick(study.id, "error", f"{type(exc).__name__}: {exc}"))
        for study in entry_studies:
            try:
                await self._attempt_new_entries(db, study, SolanaForwardConfig.from_study(study), now=now)
            except Exception as exc:
                db.rollback()
                self._record_incident(db, study, now, severity="error", code="M6L_SOLANA_ENTRY_ERROR",
                                      message=f"{type(exc).__name__}: {exc}", data_integrity=False)
                results.append(SolanaForwardTick(study.id, "error", "entry scan failed"))
        return results

