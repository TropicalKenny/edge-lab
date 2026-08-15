from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forward_models import ForwardExecutionRecord, ForwardStudy
from app.lifecycle_research import LifecycleResearchService
from app.venues.solana import JupiterShadowClient, JupiterShadowQuote, USDC_MINT
from app.venues.solana_models import SolanaForensicFeatureSnapshot

ZERO = Decimal("0")
USDC_ATOMIC = Decimal("1000000")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _d(value) -> Decimal:
    return Decimal(str(value))


def _metadata(row: ForwardExecutionRecord) -> dict:
    try:
        value = json.loads(row.metadata_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class LifecycleTarget:
    position_key: str
    mint: str
    baseline_state: str
    opened_at: datetime
    baseline_exit_at: datetime | None
    token_amount_atomic: int
    baseline_entry_value_usd: Decimal
    baseline_exit_value_usd: Decimal | None
    entry_feature_id: str | None


class SolanaLifecycleResearchRunner:
    """Quote-only M6H observer. It never mutates the frozen M6G baseline."""

    def __init__(
        self,
        *,
        jupiter: JupiterShadowClient,
        max_observation_age_minutes: int = 1440,
        max_feature_age_minutes: int = 15,
    ) -> None:
        if max_observation_age_minutes < 60 or max_observation_age_minutes > 10080:
            raise ValueError("lifecycle observation age must be between 60m and 7d")
        if max_feature_age_minutes < 1 or max_feature_age_minutes > 120:
            raise ValueError("lifecycle feature age must be between 1m and 120m")
        self.jupiter = jupiter
        self.max_observation_age_minutes = max_observation_age_minutes
        self.max_feature_age_minutes = max_feature_age_minutes

    @staticmethod
    def _quote_usable(
        quote: JupiterShadowQuote | None,
        *,
        input_mint: str,
        output_mint: str,
        input_amount: int,
    ) -> bool:
        return bool(
            quote is not None
            and not quote.transaction_present
            and quote.input_mint == input_mint
            and quote.output_mint == output_mint
            and quote.in_amount == input_amount
            and quote.out_amount > 0
            and quote.in_usd_value is not None
            and quote.out_usd_value is not None
            and quote.in_usd_value > ZERO
            and quote.out_usd_value > ZERO
        )

    async def _quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount: int,
    ) -> JupiterShadowQuote | None:
        try:
            return await self.jupiter.order_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=amount,
            )
        except Exception:
            return None

    @staticmethod
    def _targets(
        db: Session,
        study: ForwardStudy,
        *,
        now: datetime,
        max_observation_age_minutes: int,
    ) -> list[LifecycleTarget]:
        entries = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study.id,
                ForwardExecutionRecord.external_key.like("solana-entry:%"),
            )
        ).all()
        exits = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study.id,
                ForwardExecutionRecord.external_key.like("solana-exit:%"),
            )
        ).all()
        closed_by_signature: dict[str, ForwardExecutionRecord] = {}
        for row in exits:
            metadata = _metadata(row)
            if metadata.get("status") not in {"closed", "forced_loss"}:
                continue
            signature = str(metadata.get("launch_signature") or "")
            if signature:
                previous = closed_by_signature.get(signature)
                if previous is None or row.observed_at > previous.observed_at:
                    closed_by_signature[signature] = row

        targets: list[LifecycleTarget] = []
        cutoff = _aware(now) - timedelta(minutes=max_observation_age_minutes)
        for row in entries:
            metadata = _metadata(row)
            if metadata.get("status") != "open":
                continue
            signature = str(metadata.get("launch_signature") or "")
            mint = str(metadata.get("mint") or "")
            if not signature or not mint:
                continue
            try:
                opened_at = datetime.fromisoformat(
                    str(metadata["opened_at"]).replace("Z", "+00:00")
                )
                if _aware(opened_at) < cutoff:
                    continue
                token_amount = int(metadata["token_amount_atomic"])
                entry_value = _d(metadata["entry_out_usd"])
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
            if token_amount <= 0 or entry_value <= ZERO:
                continue

            exit_row = closed_by_signature.get(signature)
            baseline_state = "invested"
            baseline_exit_at = None
            baseline_exit_value = None
            if exit_row is not None:
                exit_metadata = _metadata(exit_row)
                if exit_metadata.get("status") == "forced_loss":
                    continue
                try:
                    baseline_exit_at = datetime.fromisoformat(
                        str(exit_metadata["closed_at"]).replace("Z", "+00:00")
                    )
                    baseline_exit_value = _d(exit_metadata["exit_out_usd"])
                    baseline_state = "cash"
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    continue

            targets.append(
                LifecycleTarget(
                    position_key=signature,
                    mint=mint,
                    baseline_state=baseline_state,
                    opened_at=_aware(opened_at),
                    baseline_exit_at=(
                        _aware(baseline_exit_at) if baseline_exit_at is not None else None
                    ),
                    token_amount_atomic=token_amount,
                    baseline_entry_value_usd=entry_value,
                    baseline_exit_value_usd=baseline_exit_value,
                    entry_feature_id=(
                        str(metadata.get("feature_id"))
                        if metadata.get("feature_id")
                        else None
                    ),
                )
            )
        return targets

    @staticmethod
    def _entry_feature(
        db: Session,
        target: LifecycleTarget,
    ) -> SolanaForensicFeatureSnapshot | None:
        if not target.entry_feature_id:
            return None
        return db.get(SolanaForensicFeatureSnapshot, target.entry_feature_id)

    @staticmethod
    def _latest_feature(
        db: Session,
        target: LifecycleTarget,
        *,
        observed_at: datetime,
        max_feature_age_minutes: int,
    ) -> SolanaForensicFeatureSnapshot | None:
        lower = _aware(observed_at) - timedelta(minutes=max_feature_age_minutes)
        return db.scalar(
            select(SolanaForensicFeatureSnapshot)
            .where(
                SolanaForensicFeatureSnapshot.mint == target.mint,
                SolanaForensicFeatureSnapshot.captured_at <= observed_at,
                SolanaForensicFeatureSnapshot.captured_at >= lower,
            )
            .order_by(SolanaForensicFeatureSnapshot.captured_at.desc())
            .limit(1)
        )

    @staticmethod
    def _security_clean(
        feature: SolanaForensicFeatureSnapshot | None,
    ) -> bool | None:
        if feature is None:
            return None
        if (
            feature.mintable is None
            or feature.freezable is None
            or feature.malicious_creator is None
            or feature.transfer_fee_rate is None
        ):
            return None
        return bool(
            feature.mintable is False
            and feature.freezable is False
            and feature.malicious_creator is False
            and Decimal(feature.transfer_fee_rate) == ZERO
        )

    async def observe_target(
        self,
        db: Session,
        study: ForwardStudy,
        target: LifecycleTarget,
        *,
        now: datetime,
    ) -> int:
        mark = await self._quote(
            input_mint=target.mint,
            output_mint=USDC_MINT,
            amount=target.token_amount_atomic,
        )
        mark_ok = self._quote_usable(
            mark,
            input_mint=target.mint,
            output_mint=USDC_MINT,
            input_amount=target.token_amount_atomic,
        )

        reentry_input = int(
            (target.baseline_entry_value_usd * USDC_ATOMIC).to_integral_value(
                rounding=ROUND_DOWN
            )
        )
        reentry = await self._quote(
            input_mint=USDC_MINT,
            output_mint=target.mint,
            amount=reentry_input,
        )
        reentry_ok = self._quote_usable(
            reentry,
            input_mint=USDC_MINT,
            output_mint=target.mint,
            input_amount=reentry_input,
        )

        observed_at = _aware(mark.captured_at if mark is not None else now)
        latest = self._latest_feature(
            db,
            target,
            observed_at=observed_at,
            max_feature_age_minutes=self.max_feature_age_minutes,
        )
        entry = self._entry_feature(db, target)

        observation = LifecycleResearchService.record_observation(
            db,
            study_id=study.id,
            position_key=target.position_key,
            asset_id=target.mint,
            venue="solana",
            baseline_state=target.baseline_state,
            observed_at=observed_at,
            baseline_entry_at=target.opened_at,
            baseline_exit_at=target.baseline_exit_at,
            baseline_entry_value_usd=target.baseline_entry_value_usd,
            baseline_exit_value_usd=target.baseline_exit_value_usd,
            current_value_usd=(
                Decimal(mark.out_usd_value) if mark_ok and mark is not None else None
            ),
            mark_quote_available=mark_ok,
            mark_price_impact_pct=(
                Decimal(mark.price_impact_pct)
                if mark_ok and mark is not None and mark.price_impact_pct is not None
                else None
            ),
            reentry_quote_available=reentry_ok,
            reentry_price_impact_pct=(
                Decimal(reentry.price_impact_pct)
                if reentry_ok
                and reentry is not None
                and reentry.price_impact_pct is not None
                else None
            ),
            liquidity_usd=(
                Decimal(latest.liquidity_usd)
                if latest is not None and latest.liquidity_usd is not None
                else None
            ),
            baseline_entry_liquidity_usd=(
                Decimal(entry.liquidity_usd)
                if entry is not None and entry.liquidity_usd is not None
                else None
            ),
            momentum_score=(
                Decimal(latest.momentum_score)
                if latest is not None and latest.momentum_score is not None
                else None
            ),
            sell_ratio_5m=(
                Decimal(latest.sell_ratio_5m)
                if latest is not None and latest.sell_ratio_5m is not None
                else None
            ),
            volume_acceleration=(
                Decimal(latest.volume_acceleration)
                if latest is not None and latest.volume_acceleration is not None
                else None
            ),
            security_clean=self._security_clean(latest),
            metadata={
                "milestone": "M6H",
                "scope": "adaptive-hold-exit-reentry-research",
                "quote_only": True,
                "can_execute": False,
                "baseline_mutated": False,
                "lookahead_used": False,
                "latest_feature_id": latest.id if latest is not None else None,
                "latest_feature_max_age_minutes": self.max_feature_age_minutes,
            },
        )
        decisions = LifecycleResearchService.evaluate_observation(db, observation)
        LifecycleResearchService.resolve_outcomes(db, now=observed_at)
        return len(decisions)

    async def run_active_studies(
        self,
        db: Session,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        now = _aware(now or datetime.now(timezone.utc))
        studies = db.scalars(
            select(ForwardStudy).where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "solana",
                ForwardStudy.family == "meme",
            )
        ).all()
        target_count = 0
        observation_count = 0
        decision_count = 0
        for study in studies:
            targets = self._targets(
                db,
                study,
                now=now,
                max_observation_age_minutes=self.max_observation_age_minutes,
            )
            target_count += len(targets)
            for target in targets:
                decision_count += await self.observe_target(
                    db,
                    study,
                    target,
                    now=now,
                )
                observation_count += 1
        return {
            "studies": len(studies),
            "targets": target_count,
            "observations": observation_count,
            "decisions": decision_count,
        }
