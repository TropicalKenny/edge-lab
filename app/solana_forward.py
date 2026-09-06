from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudy,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.forward_research import ForwardResearchError, ForwardResearchService
from app.solana_research import SolanaForensicService
from app.services import HealthRegistry
from app.scan_telemetry import record_scan_observation
from app.venues.solana import JupiterShadowClient, JupiterShadowQuote, USDC_MINT
from app.venues.solana_models import (
    SolanaForensicFeatureSnapshot,
    SolanaLaunchEvent,
    SolanaSecuritySnapshot,
)

ZERO = Decimal("0")
ONE = Decimal("1")
USDC_ATOMIC = Decimal("1000000")
RUNNER_NAME = "solana_pump_baseline_v1"
INSTRUMENT = "PUMP_LAUNCH_BASELINE"
STRATEGY_SLUG = "solana-pump-safety-baseline"
STRATEGY_NAME = "Solana Pump Safety Baseline"
STRATEGY_VERSION = "m6g-v1"


class SolanaForwardError(RuntimeError):
    pass


class SolanaForwardConfigError(SolanaForwardError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _quote_dict(quote: JupiterShadowQuote | None) -> dict[str, Any] | None:
    if quote is None:
        return None
    values = asdict(quote)
    values["captured_at"] = _aware(quote.captured_at).isoformat()
    values["in_usd_value"] = str(quote.in_usd_value) if quote.in_usd_value is not None else None
    values["out_usd_value"] = str(quote.out_usd_value) if quote.out_usd_value is not None else None
    values["price_impact_pct"] = (
        str(quote.price_impact_pct) if quote.price_impact_pct is not None else None
    )
    return values


@dataclass(frozen=True)
class SolanaForwardConfig:
    entry_notional_usd: Decimal
    decision_delay_minutes: int
    max_candidate_age_minutes: int
    hold_minutes: int
    max_exit_delay_minutes: int
    shadow_delay_ms: int
    max_quote_price_impact_pct: Decimal
    min_preflight_exit_ratio: Decimal
    max_open_positions: int
    max_entries_per_cycle: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "SolanaForwardConfig":
        config = cls(
            entry_notional_usd=_d(settings.solana_forward_entry_notional_usd),
            decision_delay_minutes=settings.solana_forward_decision_delay_minutes,
            max_candidate_age_minutes=settings.solana_forward_max_candidate_age_minutes,
            hold_minutes=settings.solana_forward_hold_minutes,
            max_exit_delay_minutes=settings.solana_forward_max_exit_delay_minutes,
            shadow_delay_ms=settings.solana_forward_shadow_delay_ms,
            max_quote_price_impact_pct=_d(
                settings.solana_forward_max_quote_price_impact_pct
            ),
            min_preflight_exit_ratio=_d(
                settings.solana_forward_min_preflight_exit_ratio
            ),
            max_open_positions=settings.solana_forward_max_open_positions,
            max_entries_per_cycle=settings.solana_forward_max_entries_per_cycle,
        )
        config.validate()
        return config

    @classmethod
    def from_study(cls, study: ForwardStudy) -> "SolanaForwardConfig":
        try:
            raw = json.loads(study.study_config_json)
        except json.JSONDecodeError as exc:
            raise SolanaForwardConfigError("study_config_json is invalid JSON") from exc
        if not isinstance(raw, dict) or raw.get("runner") != RUNNER_NAME:
            raise SolanaForwardConfigError(
                f"forward study must declare runner={RUNNER_NAME}"
            )
        try:
            config = cls(
                entry_notional_usd=_d(raw["entry_notional_usd"]),
                decision_delay_minutes=int(raw["decision_delay_minutes"]),
                max_candidate_age_minutes=int(raw["max_candidate_age_minutes"]),
                hold_minutes=int(raw["hold_minutes"]),
                max_exit_delay_minutes=int(raw["max_exit_delay_minutes"]),
                shadow_delay_ms=int(raw["shadow_delay_ms"]),
                max_quote_price_impact_pct=_d(raw["max_quote_price_impact_pct"]),
                min_preflight_exit_ratio=_d(raw["min_preflight_exit_ratio"]),
                max_open_positions=int(raw["max_open_positions"]),
                max_entries_per_cycle=int(raw["max_entries_per_cycle"]),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise SolanaForwardConfigError(
                f"invalid stored Solana forward configuration: {exc}"
            ) from exc
        config.validate()
        return config

    def validate(self) -> None:
        if self.entry_notional_usd <= ZERO or self.entry_notional_usd > Decimal("100"):
            raise SolanaForwardConfigError(
                "entry notional must be >0 and <=100 simulated USD"
            )
        if self.decision_delay_minutes < 1 or self.decision_delay_minutes > 60:
            raise SolanaForwardConfigError("decision delay must be between 1 and 60 minutes")
        if (
            self.max_candidate_age_minutes < self.decision_delay_minutes
            or self.max_candidate_age_minutes > 360
        ):
            raise SolanaForwardConfigError(
                "candidate age must be >= decision delay and <=360 minutes"
            )
        if self.hold_minutes < 5 or self.hold_minutes > 1440:
            raise SolanaForwardConfigError("hold horizon must be between 5m and 24h")
        if self.max_exit_delay_minutes < 5 or self.max_exit_delay_minutes > 1440:
            raise SolanaForwardConfigError(
                "maximum exit delay must be between 5m and 24h"
            )
        if self.shadow_delay_ms < 0 or self.shadow_delay_ms > 5000:
            raise SolanaForwardConfigError("shadow delay must be between 0 and 5000ms")
        if (
            self.max_quote_price_impact_pct < ZERO
            or self.max_quote_price_impact_pct > Decimal("0.25")
        ):
            raise SolanaForwardConfigError(
                "maximum quote price impact must be between 0 and 0.25"
            )
        if (
            self.min_preflight_exit_ratio <= ZERO
            or self.min_preflight_exit_ratio > ONE
        ):
            raise SolanaForwardConfigError(
                "minimum preflight exit ratio must be >0 and <=1"
            )
        if self.max_open_positions < 1 or self.max_open_positions > 50:
            raise SolanaForwardConfigError("max open positions must be between 1 and 50")
        if self.max_entries_per_cycle < 1 or self.max_entries_per_cycle > 20:
            raise SolanaForwardConfigError("max entries per cycle must be between 1 and 20")

    def study_config(self) -> dict[str, Any]:
        return {
            "runner": RUNNER_NAME,
            "entry_notional_usd": str(self.entry_notional_usd),
            "decision_delay_minutes": self.decision_delay_minutes,
            "max_candidate_age_minutes": self.max_candidate_age_minutes,
            "hold_minutes": self.hold_minutes,
            "max_exit_delay_minutes": self.max_exit_delay_minutes,
            "shadow_delay_ms": self.shadow_delay_ms,
            "max_quote_price_impact_pct": str(self.max_quote_price_impact_pct),
            "min_preflight_exit_ratio": str(self.min_preflight_exit_ratio),
            "max_open_positions": self.max_open_positions,
            "max_entries_per_cycle": self.max_entries_per_cycle,
            "quote_mint": USDC_MINT,
            "entry_policy": "chronological_safety_exitability_baseline_no_alpha_score",
            "planned_loss": "full_allocated_capital",
        }

    @property
    def entry_usdc_atomic(self) -> int:
        return int(
            (self.entry_notional_usd * USDC_ATOMIC).to_integral_value(
                rounding=ROUND_DOWN
            )
        )


@dataclass(frozen=True)
class SolanaForwardTick:
    study_id: str
    action: str
    detail: str


@dataclass(frozen=True)
class OpenPosition:
    launch_signature: str
    mint: str
    creator: str
    opened_at: datetime
    hold_until: datetime
    token_amount_atomic: int
    allocated_capital_usd: Decimal
    entry_in_usd: Decimal
    entry_out_usd: Decimal
    entry_execution_key: str


class SolanaLaunchBaselineForwardRunner:
    """Quote-only forward challenger for chain-native Pump launches."""

    def __init__(
        self,
        *,
        forensics: SolanaForensicService,
        jupiter: JupiterShadowClient,
        health: HealthRegistry,
    ) -> None:
        self.forensics = forensics
        self.jupiter = jupiter
        self.health = health

    @staticmethod
    def _block_reason(study_id: str, db: Session) -> str | None:
        integrity = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(
                    ForwardStudyIncident.study_id == study_id,
                    ForwardStudyIncident.data_integrity.is_(True),
                )
            )
            or 0
        )
        if integrity:
            return "study has a recorded data-integrity failure; further evidence is disabled"
        critical = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(
                    ForwardStudyIncident.study_id == study_id,
                    ForwardStudyIncident.severity == "critical",
                    ForwardStudyIncident.resolved.is_(False),
                )
            )
            or 0
        )
        if critical:
            return "study has an unresolved critical incident; forward runner is paused"
        return None

    @staticmethod
    def _record_incident(
        db: Session,
        study: ForwardStudy,
        now: datetime,
        *,
        severity: str,
        code: str,
        message: str,
        data_integrity: bool,
    ) -> None:
        fingerprint = hashlib.sha256(f"{severity}:{data_integrity}:{message}".encode()).hexdigest()[:16]
        bucket = int(_aware(now).timestamp() // 3600)
        key = f"solana-forward:{code}:{bucket}:{fingerprint}"
        existing = db.scalar(select(ForwardStudyIncident).where(
            ForwardStudyIncident.study_id == study.id, ForwardStudyIncident.external_key == key
        ))
        opened_at = _aware(existing.opened_at) if existing is not None else _aware(now)
        ForwardResearchService.record_incident(
            db,
            study_id=study.id,
            external_key=key,
            severity=severity,
            code=code,
            message=message,
            opened_at=opened_at,
            data_integrity=data_integrity,
        )

    @staticmethod
    def _quote_valid(
        quote: JupiterShadowQuote | None,
        *,
        input_mint: str,
        output_mint: str,
        input_amount: int,
        max_price_impact: Decimal,
    ) -> bool:
        if quote is None or quote.transaction_present:
            return False
        if quote.input_mint != input_mint or quote.output_mint != output_mint:
            return False
        if quote.in_amount != input_amount or quote.out_amount <= 0:
            return False
        if quote.in_usd_value is None or quote.out_usd_value is None:
            return False
        if quote.in_usd_value <= ZERO or quote.out_usd_value <= ZERO:
            return False
        if quote.price_impact_pct is None:
            return False
        if abs(Decimal(quote.price_impact_pct)) > max_price_impact:
            return False
        return True

    @staticmethod
    def _quote_cost(quote: JupiterShadowQuote) -> Decimal:
        if quote.in_usd_value is None or quote.out_usd_value is None:
            return ZERO
        return max(ZERO, Decimal(quote.in_usd_value) - Decimal(quote.out_usd_value))

    @staticmethod
    def _buy_average_price(quote: JupiterShadowQuote) -> Decimal:
        return Decimal(quote.in_usd_value) / Decimal(quote.out_amount)

    @staticmethod
    def _sell_average_price(quote: JupiterShadowQuote) -> Decimal:
        return Decimal(quote.out_usd_value) / Decimal(quote.in_amount)

    @staticmethod
    def _entry_key(signature: str) -> str:
        return f"solana-entry:{signature}"

    @staticmethod
    def _exit_prefix(signature: str) -> str:
        return f"solana-exit:{signature}:"

    @staticmethod
    def _trade_key(signature: str) -> str:
        return f"solana-trade:{signature}"

    @staticmethod
    def _metadata(row: ForwardExecutionRecord) -> dict[str, Any]:
        try:
            value = json.loads(row.metadata_json)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _attempted_signatures(cls, db: Session, study_id: str) -> set[str]:
        rows = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.like("solana-entry:%"),
            )
        ).all()
        return {
            row.external_key.split("solana-entry:", 1)[1]
            for row in rows
            if row.external_key.startswith("solana-entry:")
        }

    @classmethod
    def _successful_exit_signatures(cls, db: Session, study_id: str) -> set[str]:
        rows = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.like("solana-exit:%"),
            )
        ).all()
        closed: set[str] = set()
        for row in rows:
            metadata = cls._metadata(row)
            if metadata.get("status") in {"closed", "forced_loss"}:
                signature = str(metadata.get("launch_signature") or "")
                if signature:
                    closed.add(signature)
        return closed

    @classmethod
    def _open_positions(cls, db: Session, study_id: str) -> list[OpenPosition]:
        closed = cls._successful_exit_signatures(db, study_id)
        rows = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.like("solana-entry:%"),
            )
        ).all()
        positions: list[OpenPosition] = []
        for row in rows:
            metadata = cls._metadata(row)
            if metadata.get("status") != "open":
                continue
            signature = str(metadata.get("launch_signature") or "")
            if not signature or signature in closed:
                continue
            try:
                positions.append(
                    OpenPosition(
                        launch_signature=signature,
                        mint=str(metadata["mint"]),
                        creator=str(metadata["creator"]),
                        opened_at=datetime.fromisoformat(
                            str(metadata["opened_at"]).replace("Z", "+00:00")
                        ),
                        hold_until=datetime.fromisoformat(
                            str(metadata["hold_until"]).replace("Z", "+00:00")
                        ),
                        token_amount_atomic=int(metadata["token_amount_atomic"]),
                        allocated_capital_usd=_d(metadata["allocated_capital_usd"]),
                        entry_in_usd=_d(metadata["entry_in_usd"]),
                        entry_out_usd=_d(metadata["entry_out_usd"]),
                        entry_execution_key=row.external_key,
                    )
                )
            except (KeyError, TypeError, ValueError, ArithmeticError):
                continue
        return positions

    @staticmethod
    def _closed_pnl(db: Session, study_id: str) -> Decimal:
        value = db.scalar(
            select(func.coalesce(func.sum(ForwardTradeRecord.net_pnl_usd), 0)).where(
                ForwardTradeRecord.study_id == study_id
            )
        )
        return Decimal(value or 0)

    @classmethod
    def _equity(cls, db: Session, study: ForwardStudy) -> Decimal:
        return Decimal(study.initial_capital_usd) + cls._closed_pnl(db, study.id)

    @classmethod
    def _latest_nav_hour(cls, db: Session, study_id: str) -> datetime | None:
        row = db.scalar(
            select(ForwardNavObservation)
            .where(ForwardNavObservation.study_id == study_id)
            .order_by(ForwardNavObservation.observed_at.desc())
            .limit(1)
        )
        return _aware(row.observed_at) if row is not None else None

    @classmethod
    def _record_hourly_nav(
        cls,
        db: Session,
        study: ForwardStudy,
        *,
        now: datetime,
    ) -> None:
        now = _aware(now)
        latest = cls._latest_nav_hour(db, study.id)
        if latest is not None and latest.replace(minute=0, second=0, microsecond=0) == now.replace(
            minute=0, second=0, microsecond=0
        ):
            return
        equity = cls._equity(db, study)
        for position in cls._open_positions(db, study.id):
            equity += position.entry_out_usd - position.entry_in_usd
        if equity <= ZERO:
            cls._record_incident(
                db,
                study,
                now,
                severity="critical",
                code="SOLANA_SIMULATED_CAPITAL_DEPLETED",
                message="simulated Solana forward NAV is non-positive",
                data_integrity=False,
            )
            return
        observed_at = now.replace(minute=0, second=0, microsecond=0)
        if observed_at < _aware(study.started_at):
            observed_at = now
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=observed_at,
            nav_usd=equity,
            source="solana-forward-hourly-realized-plus-entry-mark",
        )

    @staticmethod
    def _decision_feature(
        db: Session,
        launch: SolanaLaunchEvent,
        config: SolanaForwardConfig,
    ) -> SolanaForensicFeatureSnapshot | None:
        lower = _aware(launch.observed_at) + timedelta(
            minutes=config.decision_delay_minutes
        )
        upper = _aware(launch.observed_at) + timedelta(
            minutes=config.max_candidate_age_minutes
        )
        return db.scalar(
            select(SolanaForensicFeatureSnapshot)
            .where(
                SolanaForensicFeatureSnapshot.mint == launch.mint,
                SolanaForensicFeatureSnapshot.captured_at >= lower,
                SolanaForensicFeatureSnapshot.captured_at <= upper,
            )
            .order_by(SolanaForensicFeatureSnapshot.captured_at.asc())
            .limit(1)
        )

    @staticmethod
    def _security_for_feature(
        db: Session,
        feature: SolanaForensicFeatureSnapshot,
    ) -> SolanaSecuritySnapshot | None:
        return db.scalar(
            select(SolanaSecuritySnapshot)
            .where(
                SolanaSecuritySnapshot.mint == feature.mint,
                SolanaSecuritySnapshot.captured_at <= feature.captured_at,
            )
            .order_by(SolanaSecuritySnapshot.captured_at.desc())
            .limit(1)
        )

    @staticmethod
    def _eligibility(
        feature: SolanaForensicFeatureSnapshot,
        security: SolanaSecuritySnapshot | None,
        config: SolanaForwardConfig,
    ) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        try:
            missing = json.loads(feature.missing_fields_json)
        except json.JSONDecodeError:
            missing = ["invalid_missing_fields_json"]
        required_missing = {
            "dex_snapshot",
            "security_snapshot",
            "asset_metadata",
            "exit_shadow_quote",
        }
        if not isinstance(missing, list) or required_missing.intersection(
            str(item) for item in missing
        ):
            reasons.append("REQUIRED_FORENSIC_DATA_MISSING")
        if feature.mintable is not False:
            reasons.append("MINT_AUTHORITY_NOT_REVOKED")
        if feature.freezable is not False:
            reasons.append("FREEZE_AUTHORITY_NOT_REVOKED")
        if feature.malicious_creator is not False:
            reasons.append("CREATOR_SECURITY_NOT_CLEAN")
        if feature.transfer_fee_rate is None or Decimal(feature.transfer_fee_rate) != ZERO:
            reasons.append("TRANSFER_FEE_NOT_ZERO_OR_UNKNOWN")
        if security is None:
            reasons.append("SECURITY_SNAPSHOT_MISSING")
        else:
            if security.non_transferable is not False:
                reasons.append("NON_TRANSFERABLE_NOT_FALSE")
            if security.mintable is True or security.freezable is True:
                reasons.append("SECURITY_AUTHORITY_FLAGGED")
            if security.malicious_creator is not False:
                reasons.append("SECURITY_CREATOR_NOT_CLEAN")
        if feature.exit_quote_usd is None:
            reasons.append("PREFLIGHT_EXIT_VALUE_MISSING")
        elif Decimal(feature.exit_quote_usd) < (
            config.entry_notional_usd * config.min_preflight_exit_ratio
        ):
            reasons.append("PREFLIGHT_EXIT_VALUE_TOO_LOW")
        if feature.exit_price_impact_pct is None:
            reasons.append("PREFLIGHT_EXIT_IMPACT_MISSING")
        elif abs(Decimal(feature.exit_price_impact_pct)) > config.max_quote_price_impact_pct:
            reasons.append("PREFLIGHT_EXIT_IMPACT_TOO_HIGH")
        return (not reasons, tuple(reasons))

    async def _ensure_feature(
        self,
        db: Session,
        launch: SolanaLaunchEvent,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> SolanaForensicFeatureSnapshot | None:
        existing = self._decision_feature(db, launch, config)
        if existing is not None:
            return existing
        launch_at = _aware(launch.observed_at)
        lower = launch_at + timedelta(minutes=config.decision_delay_minutes)
        upper = launch_at + timedelta(minutes=config.max_candidate_age_minutes)
        now = _aware(now)
        if now < lower or now > upper:
            return None
        feature = await self.forensics.analyze_mint(
            db,
            mint=launch.mint,
            exit_test_notional_usd=config.entry_notional_usd,
        )
        captured = _aware(feature.captured_at)
        if captured < lower or captured > upper:
            return None
        return feature

    @staticmethod
    async def _sleep_delay(config: SolanaForwardConfig) -> None:
        if config.shadow_delay_ms > 0:
            await asyncio.sleep(config.shadow_delay_ms / 1000)

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

    def _record_entry_execution(
        self,
        db: Session,
        study: ForwardStudy,
        launch: SolanaLaunchEvent,
        config: SolanaForwardConfig,
        *,
        paper: JupiterShadowQuote | None,
        shadow: JupiterShadowQuote | None,
        preflight: JupiterShadowQuote | None,
        status: str,
        reason: str | None,
        feature: SolanaForensicFeatureSnapshot,
    ) -> ForwardExecutionRecord:
        paper_valid = self._quote_valid(
            paper,
            input_mint=USDC_MINT,
            output_mint=launch.mint,
            input_amount=config.entry_usdc_atomic,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        shadow_valid = self._quote_valid(
            shadow,
            input_mint=USDC_MINT,
            output_mint=launch.mint,
            input_amount=config.entry_usdc_atomic,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        observed_at = _aware(
            shadow.captured_at
            if shadow is not None
            else paper.captured_at
            if paper is not None
            else datetime.now(timezone.utc)
        )
        metadata: dict[str, Any] = {
            "phase": "entry",
            "status": status,
            "reason": reason,
            "launch_signature": launch.signature,
            "mint": launch.mint,
            "creator": launch.creator,
            "launch_at": _aware(launch.observed_at).isoformat(),
            "feature_id": feature.id,
            "feature_captured_at": _aware(feature.captured_at).isoformat(),
            "paper_quote": _quote_dict(paper),
            "shadow_quote": _quote_dict(shadow),
            "preflight_exit_quote": _quote_dict(preflight),
        }
        if status == "open" and shadow is not None:
            opened_at = _aware(shadow.captured_at)
            metadata.update(
                {
                    "opened_at": opened_at.isoformat(),
                    "hold_until": (
                        opened_at + timedelta(minutes=config.hold_minutes)
                    ).isoformat(),
                    "token_amount_atomic": shadow.out_amount,
                    "allocated_capital_usd": str(shadow.in_usd_value),
                    "entry_in_usd": str(shadow.in_usd_value),
                    "entry_out_usd": str(shadow.out_usd_value),
                }
            )
        return ForwardResearchService.record_execution(
            db,
            study_id=study.id,
            external_key=self._entry_key(launch.signature),
            observed_at=observed_at,
            side="buy",
            intended_quantity=Decimal(config.entry_usdc_atomic),
            paper_filled_quantity=(
                Decimal(config.entry_usdc_atomic) if paper_valid else ZERO
            ),
            shadow_filled_quantity=(
                Decimal(config.entry_usdc_atomic) if shadow_valid else ZERO
            ),
            paper_average_price=(
                self._buy_average_price(paper) if paper_valid and paper is not None else None
            ),
            shadow_average_price=(
                self._buy_average_price(shadow)
                if shadow_valid and shadow is not None
                else None
            ),
            paper_cost_usd=(self._quote_cost(paper) if paper_valid and paper else ZERO),
            shadow_cost_usd=(
                self._quote_cost(shadow) if shadow_valid and shadow else ZERO
            ),
            metadata=metadata,
        )

    async def _attempt_entry(
        self,
        db: Session,
        study: ForwardStudy,
        launch: SolanaLaunchEvent,
        feature: SolanaForensicFeatureSnapshot,
        config: SolanaForwardConfig,
    ) -> bool:
        paper = await self._quote(
            input_mint=USDC_MINT,
            output_mint=launch.mint,
            amount=config.entry_usdc_atomic,
        )
        paper_valid = self._quote_valid(
            paper,
            input_mint=USDC_MINT,
            output_mint=launch.mint,
            input_amount=config.entry_usdc_atomic,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        if not paper_valid:
            self._record_entry_execution(
                db,
                study,
                launch,
                config,
                paper=paper,
                shadow=None,
                preflight=None,
                status="rejected",
                reason="PAPER_ENTRY_QUOTE_INVALID",
                feature=feature,
            )
            return False

        await self._sleep_delay(config)
        shadow = await self._quote(
            input_mint=USDC_MINT,
            output_mint=launch.mint,
            amount=config.entry_usdc_atomic,
        )
        shadow_valid = self._quote_valid(
            shadow,
            input_mint=USDC_MINT,
            output_mint=launch.mint,
            input_amount=config.entry_usdc_atomic,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        if not shadow_valid or shadow is None:
            self._record_entry_execution(
                db,
                study,
                launch,
                config,
                paper=paper,
                shadow=shadow,
                preflight=None,
                status="rejected",
                reason="SHADOW_ENTRY_QUOTE_INVALID",
                feature=feature,
            )
            return False

        preflight = await self._quote(
            input_mint=launch.mint,
            output_mint=USDC_MINT,
            amount=shadow.out_amount,
        )
        preflight_valid = self._quote_valid(
            preflight,
            input_mint=launch.mint,
            output_mint=USDC_MINT,
            input_amount=shadow.out_amount,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        if (
            not preflight_valid
            or preflight is None
            or Decimal(preflight.out_usd_value)
            < config.entry_notional_usd * config.min_preflight_exit_ratio
        ):
            self._record_entry_execution(
                db,
                study,
                launch,
                config,
                paper=paper,
                shadow=shadow,
                preflight=preflight,
                status="rejected",
                reason="LIVE_PREFLIGHT_EXIT_INVALID",
                feature=feature,
            )
            return False

        self._record_entry_execution(
            db,
            study,
            launch,
            config,
            paper=paper,
            shadow=shadow,
            preflight=preflight,
            status="open",
            reason=None,
            feature=feature,
        )
        return True

    def _exit_attempt_number(self, db: Session, study_id: str, signature: str) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(ForwardExecutionRecord)
                .where(
                    ForwardExecutionRecord.study_id == study_id,
                    ForwardExecutionRecord.external_key.like(
                        f"{self._exit_prefix(signature)}%"
                    ),
                )
            )
            or 0
        ) + 1

    def _record_exit_execution(
        self,
        db: Session,
        study: ForwardStudy,
        position: OpenPosition,
        config: SolanaForwardConfig,
        *,
        paper: JupiterShadowQuote | None,
        shadow: JupiterShadowQuote | None,
        status: str,
        reason: str | None,
        now: datetime,
    ) -> ForwardExecutionRecord:
        paper_valid = self._quote_valid(
            paper,
            input_mint=position.mint,
            output_mint=USDC_MINT,
            input_amount=position.token_amount_atomic,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        shadow_valid = self._quote_valid(
            shadow,
            input_mint=position.mint,
            output_mint=USDC_MINT,
            input_amount=position.token_amount_atomic,
            max_price_impact=config.max_quote_price_impact_pct,
        )
        observed_at = _aware(
            shadow.captured_at
            if shadow is not None
            else paper.captured_at
            if paper is not None
            else now
        )
        attempt = self._exit_attempt_number(
            db, study.id, position.launch_signature
        )
        metadata = {
            "phase": "exit",
            "status": status,
            "reason": reason,
            "launch_signature": position.launch_signature,
            "mint": position.mint,
            "creator": position.creator,
            "opened_at": _aware(position.opened_at).isoformat(),
            "hold_until": _aware(position.hold_until).isoformat(),
            "entry_execution_key": position.entry_execution_key,
            "token_amount_atomic": position.token_amount_atomic,
            "allocated_capital_usd": str(position.allocated_capital_usd),
            "entry_in_usd": str(position.entry_in_usd),
            "entry_out_usd": str(position.entry_out_usd),
            "paper_quote": _quote_dict(paper),
            "shadow_quote": _quote_dict(shadow),
        }
        if status == "forced_loss":
            metadata.update(
                {
                    "exit_in_usd": "0",
                    "exit_out_usd": "0",
                    "closed_at": observed_at.isoformat(),
                }
            )
        elif status == "closed" and shadow is not None:
            metadata.update(
                {
                    "exit_in_usd": str(shadow.in_usd_value),
                    "exit_out_usd": str(shadow.out_usd_value),
                    "closed_at": _aware(shadow.captured_at).isoformat(),
                }
            )
        return ForwardResearchService.record_execution(
            db,
            study_id=study.id,
            external_key=f"{self._exit_prefix(position.launch_signature)}{attempt}",
            observed_at=observed_at,
            side="sell",
            intended_quantity=Decimal(position.token_amount_atomic),
            paper_filled_quantity=(
                Decimal(position.token_amount_atomic) if paper_valid else ZERO
            ),
            shadow_filled_quantity=(
                Decimal(position.token_amount_atomic) if shadow_valid else ZERO
            ),
            paper_average_price=(
                self._sell_average_price(paper) if paper_valid and paper is not None else None
            ),
            shadow_average_price=(
                self._sell_average_price(shadow)
                if shadow_valid and shadow is not None
                else None
            ),
            paper_cost_usd=(self._quote_cost(paper) if paper_valid and paper else ZERO),
            shadow_cost_usd=(
                self._quote_cost(shadow) if shadow_valid and shadow else ZERO
            ),
            metadata=metadata,
        )

    @staticmethod
    def _trade_from_exit_metadata(
        db: Session,
        study: ForwardStudy,
        row: ForwardExecutionRecord,
    ) -> ForwardTradeRecord | None:
        try:
            metadata = json.loads(row.metadata_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(metadata, dict) or metadata.get("status") not in {
            "closed",
            "forced_loss",
        }:
            return None
        signature = str(metadata.get("launch_signature") or "")
        if not signature:
            return None
        try:
            opened_at = datetime.fromisoformat(
                str(metadata["opened_at"]).replace("Z", "+00:00")
            )
            closed_at = datetime.fromisoformat(
                str(metadata["closed_at"]).replace("Z", "+00:00")
            )
            entry_in = _d(metadata["entry_in_usd"])
            entry_out = _d(metadata["entry_out_usd"])
            exit_in = _d(metadata["exit_in_usd"])
            exit_out = _d(metadata["exit_out_usd"])
            allocated = _d(metadata["allocated_capital_usd"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None
        entry_cost = max(ZERO, entry_in - entry_out)
        exit_cost = max(ZERO, exit_in - exit_out)
        gross_pnl = exit_in - entry_out
        slippage = entry_cost + exit_cost
        net_pnl = gross_pnl - slippage
        return ForwardResearchService.record_trade(
            db,
            study_id=study.id,
            external_key=f"solana-trade:{signature}",
            opened_at=_aware(opened_at),
            closed_at=_aware(closed_at),
            gross_pnl_usd=gross_pnl,
            net_pnl_usd=net_pnl,
            fees_usd=ZERO,
            slippage_usd=slippage,
            allocated_capital_usd=allocated,
            planned_loss_usd=allocated,
            metadata={
                "runner": RUNNER_NAME,
                "launch_signature": signature,
                "mint": metadata.get("mint"),
                "creator": metadata.get("creator"),
                "exit_execution_key": row.external_key,
                "exit_status": metadata.get("status"),
                "accounting": "quote_value_change_minus_entry_and_exit_quote_deterioration",
            },
        )

    @classmethod
    def _reconcile_closed_executions(
        cls,
        db: Session,
        study: ForwardStudy,
    ) -> int:
        rows = db.scalars(
            select(ForwardExecutionRecord).where(
                ForwardExecutionRecord.study_id == study.id,
                ForwardExecutionRecord.external_key.like("solana-exit:%"),
            )
        ).all()
        created = 0
        for row in rows:
            metadata = cls._metadata(row)
            if metadata.get("status") not in {"closed", "forced_loss"}:
                continue
            signature = str(metadata.get("launch_signature") or "")
            if not signature:
                continue
            existing = db.scalar(
                select(ForwardTradeRecord.id).where(
                    ForwardTradeRecord.study_id == study.id,
                    ForwardTradeRecord.external_key == cls._trade_key(signature),
                )
            )
            if existing:
                continue
            if cls._trade_from_exit_metadata(db, study, row) is not None:
                created += 1
        return created

    async def _exit_due_positions(
        self,
        db: Session,
        study: ForwardStudy,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> tuple[int, int]:
        closed_count = 0
        failed_attempts = 0
        for position in self._open_positions(db, study.id):
            now = _aware(now)
            if now < _aware(position.hold_until):
                continue
            deadline = _aware(position.hold_until) + timedelta(
                minutes=config.max_exit_delay_minutes
            )
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

            row = self._record_exit_execution(
                db,
                study,
                position,
                config,
                paper=paper,
                shadow=shadow,
                status="closed",
                reason=None,
                now=now,
            )
            self._trade_from_exit_metadata(db, study, row)
            closed_count += 1
        return closed_count, failed_attempts

    async def _attempt_new_entries(
        self,
        db: Session,
        study: ForwardStudy,
        config: SolanaForwardConfig,
        *,
        now: datetime,
    ) -> tuple[int, int]:
        attempted = self._attempted_signatures(db, study.id)
        open_positions = self._open_positions(db, study.id)
        capacity = max(0, config.max_open_positions - len(open_positions))
        cycle_key = f"solana-cycle:{int(_aware(now).timestamp() // 60)}"
        if capacity <= 0:
            record_scan_observation(
                db, study_id=study.id, external_key=cycle_key, observation_kind="cycle",
                observed_at=now, deferred_count=1, metadata={"open_positions": len(open_positions)},
            )
            return 0, 0
        equity = self._equity(db, study)
        allocated_open = sum(
            (position.allocated_capital_usd for position in open_positions), ZERO
        )
        if allocated_open + config.entry_notional_usd > equity:
            record_scan_observation(
                db, study_id=study.id, external_key=cycle_key, observation_kind="cycle",
                observed_at=now, deferred_count=1, metadata={"capital_capacity_blocked": 1},
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
        opened = 0
        quote_attempts = 0
        features_ready = 0
        for launch in launches:
            if launch.signature in attempted:
                continue
            if opened >= min(capacity, config.max_entries_per_cycle):
                break
            feature = await self._ensure_feature(db, launch, config, now=now)
            if feature is None:
                continue
            features_ready += 1
            candidate_key = f"solana-candidate:{launch.signature}"
            security = self._security_for_feature(db, feature)
            eligible, eligibility_reasons = self._eligibility(feature, security, config)
            if not eligible:
                record_scan_observation(
                    db,
                    study_id=study.id,
                    external_key=candidate_key,
                    observation_kind="candidate",
                    observed_at=_aware(feature.captured_at),
                    examined_count=1,
                    rejected_count=1,
                    rejection_reasons={reason: 1 for reason in eligibility_reasons},
                    metadata={"mint": launch.mint, "stage": "safety_exitability"},
                )
                continue
            if allocated_open + (opened + 1) * config.entry_notional_usd > equity:
                record_scan_observation(
                    db, study_id=study.id, external_key=candidate_key, observation_kind="candidate",
                    observed_at=_aware(feature.captured_at), examined_count=1, rejected_count=1,
                    rejection_reasons={"SIMULATED_EQUITY_INSUFFICIENT": 1},
                    metadata={"mint": launch.mint, "stage": "capital"},
                )
                break
            quote_attempts += 1
            did_open = await self._attempt_entry(db, study, launch, feature, config)
            if did_open:
                opened += 1
                record_scan_observation(
                    db, study_id=study.id, external_key=candidate_key, observation_kind="candidate",
                    observed_at=datetime.now(timezone.utc), examined_count=1, accepted_count=1,
                    metadata={"mint": launch.mint, "stage": "delayed_execution", "status": "opened"},
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
                    reason = str(self._metadata(execution).get("reason") or reason)
                record_scan_observation(
                    db, study_id=study.id, external_key=candidate_key, observation_kind="candidate",
                    observed_at=datetime.now(timezone.utc), examined_count=1, rejected_count=1,
                    rejection_reasons={reason: 1},
                    metadata={"mint": launch.mint, "stage": "delayed_execution"},
                )
        record_scan_observation(
            db,
            study_id=study.id,
            external_key=cycle_key,
            observation_kind="cycle",
            observed_at=now,
            metadata={
                "launches_in_window": len(launches),
                "features_ready": features_ready,
                "quote_attempts": quote_attempts,
                "opened": opened,
            },
        )
        return opened, quote_attempts

    async def run_study_once(
        self,
        db: Session,
        study: ForwardStudy,
        *,
        now: datetime | None = None,
    ) -> SolanaForwardTick:
        now = _aware(now or datetime.now(timezone.utc))
        config = SolanaForwardConfig.from_study(study)
        reconciled = self._reconcile_closed_executions(db, study)
        closed, failed_exits = await self._exit_due_positions(
            db,
            study,
            config,
            now=now,
        )
        opened, attempts = await self._attempt_new_entries(
            db,
            study,
            config,
            now=now,
        )
        self._record_hourly_nav(db, study, now=now)
        detail = (
            f"reconciled={reconciled} closed={closed} failed_exits={failed_exits} "
            f"entry_attempts={attempts} opened={opened} open={len(self._open_positions(db, study.id))}"
        )
        self.health.set("solana_forward", True, detail)
        return SolanaForwardTick(study.id, "cycle", detail)

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
                ForwardStudy.instrument == INSTRUMENT,
            )
        ).all()
        results: list[SolanaForwardTick] = []
        for study in studies:
            blocked = self._block_reason(study.id, db)
            if blocked is not None:
                results.append(SolanaForwardTick(study.id, "blocked", blocked))
                continue
            try:
                results.append(await self.run_study_once(db, study, now=now))
            except (ForwardResearchError, SolanaForwardConfigError, SolanaForwardError) as exc:
                db.rollback()
                self._record_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="SOLANA_FORWARD_RUNNER_ERROR",
                    message=str(exc),
                    data_integrity=False,
                )
                results.append(SolanaForwardTick(study.id, "error", str(exc)))
            except Exception as exc:
                db.rollback()
                self._record_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="SOLANA_FORWARD_UNEXPECTED_ERROR",
                    message=f"{type(exc).__name__}: {exc}",
                    data_integrity=False,
                )
                results.append(
                    SolanaForwardTick(
                        study.id,
                        "error",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
        return results

