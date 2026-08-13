from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
from app.forward_operations import evaluation_policy_from_settings
from app.forward_research import ForwardResearchError, ForwardResearchService
from app.models import Experiment, Strategy, StrategyStatus, StrategyVersion
from app.polymarket_research import PolymarketResearchService
from app.services import HealthRegistry
from app.venues.polymarket import (
    LegExecution,
    MarketContext,
    OrderBook,
    PolymarketPublicClient,
    StructuralArbitrageAnalyzer,
    StructuralOpportunity,
    taker_fee,
)
from app.venues.polymarket_validation import apply_clob_market_info

ZERO = Decimal("0")
BPS = Decimal("10000")
STRATEGY_SLUG = "polymarket-immediate-structural"
STRATEGY_NAME = "Polymarket Immediate Structural"
STRATEGY_VERSION = "m6f-v1"
ANALYZER_CODE_SHA = "293321ef0d07cb79e317d33c4fe31aea4c724c8c"
RUNNER_NAME = "polymarket_structural_v1"
INSTRUMENT = "STRUCTURAL_IMMEDIATE"
IMMEDIATE_KINDS = {"binary_complete_set", "negrisk_no_complete_set"}


class PolymarketForwardError(RuntimeError):
    pass


class PolymarketForwardConfigError(PolymarketForwardError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class PolymarketForwardConfig:
    max_markets: int
    max_negrisk_events: int
    max_shares: Decimal
    min_edge_bps: Decimal
    max_book_age_seconds: int
    fee_buffer_pct: Decimal
    shadow_delay_ms: int
    operation_cost_usd: Decimal
    planned_loss_pct: Decimal
    attempt_interval_seconds: int
    max_attempts_per_cycle: int

    @classmethod
    def from_study(cls, study: ForwardStudy) -> "PolymarketForwardConfig":
        try:
            raw = json.loads(study.study_config_json)
        except json.JSONDecodeError as exc:
            raise PolymarketForwardConfigError("study_config_json is invalid JSON") from exc
        if not isinstance(raw, dict) or raw.get("runner") != RUNNER_NAME:
            raise PolymarketForwardConfigError(f"forward study must declare runner={RUNNER_NAME}")
        try:
            config = cls(
                max_markets=int(raw["max_markets"]),
                max_negrisk_events=int(raw["max_negrisk_events"]),
                max_shares=_d(raw["max_shares"]),
                min_edge_bps=_d(raw["min_edge_bps"]),
                max_book_age_seconds=int(raw["max_book_age_seconds"]),
                fee_buffer_pct=_d(raw["fee_buffer_pct"]),
                shadow_delay_ms=int(raw["shadow_delay_ms"]),
                operation_cost_usd=_d(raw["operation_cost_usd"]),
                planned_loss_pct=_d(raw["planned_loss_pct"]),
                attempt_interval_seconds=int(raw["attempt_interval_seconds"]),
                max_attempts_per_cycle=int(raw["max_attempts_per_cycle"]),
            )
        except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
            raise PolymarketForwardConfigError(f"invalid Polymarket forward config: {exc}") from exc
        config.validate()
        return config

    @classmethod
    def from_settings(cls, settings: Settings) -> "PolymarketForwardConfig":
        config = cls(
            max_markets=settings.polymarket_max_markets,
            max_negrisk_events=settings.polymarket_max_negrisk_events,
            max_shares=_d(settings.polymarket_max_shares_per_opportunity),
            min_edge_bps=_d(settings.polymarket_min_edge_bps),
            max_book_age_seconds=settings.polymarket_max_book_age_seconds,
            fee_buffer_pct=_d(settings.polymarket_forward_fee_buffer_pct),
            shadow_delay_ms=settings.polymarket_forward_shadow_delay_ms,
            operation_cost_usd=_d(settings.polymarket_forward_operation_cost_usd),
            planned_loss_pct=_d(settings.polymarket_forward_planned_loss_pct),
            attempt_interval_seconds=settings.polymarket_forward_attempt_interval_seconds,
            max_attempts_per_cycle=settings.polymarket_forward_max_attempts_per_cycle,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.max_markets < 1 or self.max_markets > 500:
            raise PolymarketForwardConfigError("max_markets must be between 1 and 500")
        if self.max_negrisk_events < 0 or self.max_negrisk_events > 50:
            raise PolymarketForwardConfigError("max_negrisk_events must be between 0 and 50")
        if self.max_shares <= ZERO:
            raise PolymarketForwardConfigError("max_shares must be positive")
        if self.min_edge_bps < ZERO:
            raise PolymarketForwardConfigError("min_edge_bps cannot be negative")
        if self.max_book_age_seconds < 1 or self.max_book_age_seconds > 60:
            raise PolymarketForwardConfigError("max_book_age_seconds must be between 1 and 60")
        if self.fee_buffer_pct < ZERO or self.fee_buffer_pct > Decimal("100"):
            raise PolymarketForwardConfigError("fee_buffer_pct must be between 0 and 100")
        if self.shadow_delay_ms < 0 or self.shadow_delay_ms > 5000:
            raise PolymarketForwardConfigError("shadow_delay_ms must be between 0 and 5000")
        if self.operation_cost_usd < ZERO:
            raise PolymarketForwardConfigError("operation_cost_usd cannot be negative")
        if self.planned_loss_pct <= ZERO or self.planned_loss_pct > Decimal("1"):
            raise PolymarketForwardConfigError("planned_loss_pct must be >0 and <=1")
        if self.attempt_interval_seconds < 60 or self.attempt_interval_seconds > 86400:
            raise PolymarketForwardConfigError("attempt_interval_seconds must be between 60 and 86400")
        if self.max_attempts_per_cycle < 1 or self.max_attempts_per_cycle > 20:
            raise PolymarketForwardConfigError("max_attempts_per_cycle must be between 1 and 20")

    def study_config(self) -> dict[str, Any]:
        return {
            "runner": RUNNER_NAME,
            "max_markets": self.max_markets,
            "max_negrisk_events": self.max_negrisk_events,
            "max_shares": str(self.max_shares),
            "min_edge_bps": str(self.min_edge_bps),
            "max_book_age_seconds": self.max_book_age_seconds,
            "fee_buffer_pct": str(self.fee_buffer_pct),
            "shadow_delay_ms": self.shadow_delay_ms,
            "operation_cost_usd": str(self.operation_cost_usd),
            "planned_loss_pct": str(self.planned_loss_pct),
            "attempt_interval_seconds": self.attempt_interval_seconds,
            "max_attempts_per_cycle": self.max_attempts_per_cycle,
            "immediate_kinds": sorted(IMMEDIATE_KINDS),
            "negrisk_yes_complete_set": "deferred_resolution_dependent",
        }

    def analyzer(self) -> StructuralArbitrageAnalyzer:
        return StructuralArbitrageAnalyzer(
            min_edge_bps=self.min_edge_bps,
            max_shares=self.max_shares,
            max_book_age_seconds=self.max_book_age_seconds,
            fee_buffer_pct=self.fee_buffer_pct,
        )


@dataclass(frozen=True)
class StructuralCandidate:
    opportunity: StructuralOpportunity
    markets: dict[str, MarketContext]

    @property
    def identity(self) -> str:
        leg_ids = ",".join(sorted(leg.token_id for leg in self.opportunity.legs))
        base = (
            f"{self.opportunity.kind}|{self.opportunity.event_id or ''}|"
            f"{self.opportunity.condition_id or ''}|{leg_ids}"
        )
        return hashlib.sha256(base.encode()).hexdigest()[:24]


@dataclass(frozen=True)
class ShadowLeg:
    market_id: str
    condition_id: str
    token_id: str
    outcome: str
    intended_quantity: Decimal
    filled_quantity: Decimal
    average_price: Decimal | None
    notional: Decimal
    fee: Decimal
    observed_at: datetime
    reason: str | None = None

    @property
    def full(self) -> bool:
        return self.filled_quantity == self.intended_quantity and self.average_price is not None


@dataclass(frozen=True)
class ForwardTick:
    study_id: str
    action: str
    detail: str


class PolymarketForwardBootstrap:
    @staticmethod
    def _version_config() -> str:
        return _json(
            {
                "family": "other",
                "venue": "polymarket",
                "runner": RUNNER_NAME,
                "immediate_kinds": sorted(IMMEDIATE_KINDS),
                "analyzer_code_sha": ANALYZER_CODE_SHA,
                "live_execution": False,
            }
        )

    @staticmethod
    def bootstrap(
        db: Session,
        *,
        settings: Settings,
        now: datetime | None = None,
    ) -> ForwardStudy:
        now = _aware(now or datetime.now(timezone.utc))
        config = PolymarketForwardConfig.from_settings(settings)
        policy = evaluation_policy_from_settings(settings)
        external_id = settings.polymarket_forward_study_external_id.strip()
        initial_capital = _d(settings.polymarket_forward_initial_capital_usd)
        if not external_id or initial_capital <= ZERO:
            raise PolymarketForwardConfigError("Polymarket forward external id/capital is invalid")

        strategy = db.scalar(select(Strategy).where(Strategy.slug == STRATEGY_SLUG))
        if strategy is None:
            strategy = Strategy(slug=STRATEGY_SLUG, name=STRATEGY_NAME, status=StrategyStatus.RED.value)
            db.add(strategy)
            db.commit()
            db.refresh(strategy)

        version = db.scalar(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version == STRATEGY_VERSION,
            )
        )
        version_config = PolymarketForwardBootstrap._version_config()
        if version is None:
            version = StrategyVersion(
                strategy_id=strategy.id,
                version=STRATEGY_VERSION,
                code_sha=ANALYZER_CODE_SHA,
                config_json=version_config,
                immutable=True,
            )
            db.add(version)
            db.commit()
            db.refresh(version)
        elif (
            not version.immutable
            or version.code_sha != ANALYZER_CODE_SHA
            or version.config_json != version_config
        ):
            raise PolymarketForwardConfigError("registered Polymarket strategy version conflicts with frozen v1")

        experiment_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"edge-lab:polymarket-forward:{external_id}")
        )
        experiment = db.get(Experiment, experiment_id)
        if experiment is None:
            experiment = Experiment(
                id=experiment_id,
                strategy_version_id=version.id,
                hypothesis=(
                    "Public CLOB structural complete-set discounts remain executable after a delayed "
                    "re-quote and conservative fee/operation costs."
                ),
                data_version="polymarket-public-clob-v2-forward-v1",
                train_window="pre-registered-structural-research",
                validation_window="signal-book-plus-delayed-shadow-book",
                holdout_window="future-forward-observations",
                search_space_json="{}",
                status="registered",
            )
            db.add(experiment)
            db.commit()
            db.refresh(experiment)
        elif experiment.strategy_version_id != version.id or experiment.status not in {"registered", "running"}:
            raise PolymarketForwardConfigError("existing Polymarket experiment conflicts with frozen lineage")

        existing = db.scalar(select(ForwardStudy).where(ForwardStudy.external_id == external_id))
        expected_config = _json(config.study_config())
        expected_policy = _json(asdict(policy))
        if existing is not None:
            mismatches: list[str] = []
            if existing.strategy_version_id != version.id:
                mismatches.append("strategy_version")
            if existing.experiment_id != experiment.id:
                mismatches.append("experiment")
            if existing.family != "other" or existing.venue != "polymarket":
                mismatches.append("family_or_venue")
            if existing.instrument != INSTRUMENT:
                mismatches.append("instrument")
            if Decimal(existing.initial_capital_usd) != initial_capital:
                mismatches.append("initial_capital")
            if existing.study_config_json != expected_config:
                mismatches.append("study_config")
            if existing.evaluation_policy_json != expected_policy:
                mismatches.append("evaluation_policy")
            if mismatches:
                raise PolymarketForwardConfigError(
                    "existing Polymarket forward study conflicts with bootstrap spec: " + ",".join(mismatches)
                )
            return existing

        study = ForwardResearchService.create_study(
            db,
            external_id=external_id,
            strategy_slug=strategy.slug,
            strategy_version=version.version,
            experiment_id=experiment.id,
            family="other",
            venue="polymarket",
            instrument=INSTRUMENT,
            initial_capital_usd=initial_capital,
            evaluation_policy=policy,
            study_config=config.study_config(),
            started_at=now,
        )
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=now,
            nav_usd=initial_capital,
            source="study-initial-capital",
        )
        return study


class PolymarketStructuralForwardRunner:
    """Public-data-only immediate structural forward runner; no order or CTF action surface."""

    def __init__(
        self,
        *,
        client: PolymarketPublicClient,
        health: HealthRegistry | None = None,
        sleep=asyncio.sleep,
    ) -> None:
        self.client = client
        self.health = health or HealthRegistry()
        self.sleep = sleep

    async def run_active_studies(
        self,
        db: Session,
        *,
        now: datetime | None = None,
    ) -> list[ForwardTick]:
        now = _aware(now or datetime.now(timezone.utc))
        studies = db.scalars(
            select(ForwardStudy).where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "polymarket",
                ForwardStudy.family == "other",
                ForwardStudy.instrument == INSTRUMENT,
            )
        ).all()
        results: list[ForwardTick] = []
        for study in studies:
            if self._has_integrity_failure(db, study.id):
                results.append(ForwardTick(study.id, "blocked", "study has permanent data-integrity failure"))
                continue
            if self._has_unresolved_critical(db, study.id):
                results.append(ForwardTick(study.id, "paused", "study has unresolved critical incident"))
                continue
            try:
                results.append(await self.run_study_once(db, study=study, now=now))
            except PolymarketForwardConfigError as exc:
                self._record_incident(db, study, now, "critical", "PM_FORWARD_CONFIG", str(exc), True)
                results.append(ForwardTick(study.id, "blocked", str(exc)))
            except (ForwardResearchError, PolymarketForwardError) as exc:
                self._record_incident(db, study, now, "error", "PM_FORWARD_RUNNER", str(exc), False)
                results.append(ForwardTick(study.id, "error", str(exc)))
            except Exception as exc:
                db.rollback()
                self._record_incident(
                    db,
                    study,
                    now,
                    "error",
                    "PM_FORWARD_UNEXPECTED",
                    f"{type(exc).__name__}: {exc}",
                    False,
                )
                results.append(ForwardTick(study.id, "error", f"{type(exc).__name__}: {exc}"))
        return results

    async def run_study_once(
        self,
        db: Session,
        *,
        study: ForwardStudy,
        now: datetime,
    ) -> ForwardTick:
        if study.status != "active" or study.venue != "polymarket" or study.instrument != INSTRUMENT:
            raise PolymarketForwardError("study is not an active Polymarket structural study")
        config = PolymarketForwardConfig.from_study(study)
        candidates = await self._discover_candidates(config)
        attempts = 0
        trades = 0
        for candidate in candidates:
            if attempts >= config.max_attempts_per_cycle:
                break
            if not self._signal_passes_cost_reserve(candidate.opportunity, config):
                continue
            attempt_key = self._attempt_key(candidate, config)
            if self._attempt_exists(db, study.id, attempt_key):
                continue
            if self._required_capital(candidate.opportunity, config) > self._flat_equity(db, study):
                continue
            attempts += 1
            if config.shadow_delay_ms:
                await self.sleep(config.shadow_delay_ms / 1000)
            shadow = await self._shadow_reprice(candidate, config)
            traded = self._persist_attempt(db, study, candidate, shadow, config, attempt_key)
            if traded:
                trades += 1

        self._record_hourly_flat_nav(db, study)
        self.health.set(
            "polymarket_forward",
            True,
            f"study={study.external_id} candidates={len(candidates)} attempts={attempts} trades={trades}",
        )
        action = "traded" if trades else ("observed" if attempts else "no_entry")
        return ForwardTick(study.id, action, f"candidates={len(candidates)} attempts={attempts} trades={trades}")

    async def _discover_candidates(self, config: PolymarketForwardConfig) -> list[StructuralCandidate]:
        analyzer = config.analyzer()
        research = PolymarketResearchService(client=self.client, health=self.health, analyzer=analyzer)
        discovered = await research.discover_markets(max_markets=config.max_markets)
        markets, _ = await research._validate_markets(discovered)
        if not markets:
            raise PolymarketForwardError("no Polymarket markets passed current CLOB metadata validation")

        token_ids = [
            token
            for market in markets
            for token in (market.yes_token_id, market.no_token_id)
            if token
        ]
        books, _ = await research.fetch_books(token_ids)
        rejected: dict[str, int] = {}
        research._remove_book_metadata_mismatches(markets, books, rejected)

        candidates: list[StructuralCandidate] = []
        scan_now = datetime.now(timezone.utc)
        for market in markets:
            if market.neg_risk:
                continue
            opportunity, _ = analyzer.binary_complete_set(market, books, now=scan_now)
            if opportunity is not None and opportunity.eligible:
                candidates.append(StructuralCandidate(opportunity, {market.market_id: market}))

        events, _ = await research._load_negrisk_events(
            markets,
            max_events=config.max_negrisk_events,
        )
        event_markets = [market for event in events for market in event.markets]
        extra_tokens = [
            token
            for market in event_markets
            for token in (market.yes_token_id, market.no_token_id)
            if token and token not in books
        ]
        if extra_tokens:
            extra_books, _ = await research.fetch_books(extra_tokens)
            books.update(extra_books)
        research._remove_book_metadata_mismatches(event_markets, books, rejected)

        for event in events:
            opportunities, _ = analyzer.neg_risk_event(event, books, now=scan_now)
            market_map = {market.market_id: market for market in event.markets}
            for opportunity in opportunities:
                if opportunity.kind == "negrisk_no_complete_set" and opportunity.eligible:
                    candidates.append(StructuralCandidate(opportunity, market_map))

        return sorted(candidates, key=lambda row: row.opportunity.net_profit, reverse=True)

    async def _shadow_reprice(
        self,
        candidate: StructuralCandidate,
        config: PolymarketForwardConfig,
    ) -> list[ShadowLeg]:
        unique_markets = {
            leg.market_id: candidate.markets[leg.market_id]
            for leg in candidate.opportunity.legs
            if leg.market_id in candidate.markets
        }
        validated: dict[str, MarketContext] = {}
        semaphore = asyncio.Semaphore(10)

        async def load(market: MarketContext):
            async with semaphore:
                info = await self.client.get_clob_market_info(market.condition_id)
                return apply_clob_market_info(market, info)

        results = await asyncio.gather(*(load(market) for market in unique_markets.values()), return_exceptions=True)
        for market, result in zip(unique_markets.values(), results, strict=True):
            if isinstance(result, MarketContext):
                validated[market.market_id] = result

        token_ids = [leg.token_id for leg in candidate.opportunity.legs]
        research = PolymarketResearchService(
            client=self.client,
            health=self.health,
            analyzer=config.analyzer(),
        )
        try:
            books, _ = await research.fetch_books(token_ids)
        except Exception:
            books = {}
        rejected: dict[str, int] = {}
        research._remove_book_metadata_mismatches(list(validated.values()), books, rejected)

        observed_now = datetime.now(timezone.utc)
        shadow: list[ShadowLeg] = []
        for leg in candidate.opportunity.legs:
            market = validated.get(leg.market_id)
            book = books.get(leg.token_id)
            if market is None:
                shadow.append(self._empty_shadow(leg, observed_now, "MARKET_METADATA_REVALIDATION_FAILED"))
                continue
            if book is None:
                shadow.append(self._empty_shadow(leg, observed_now, "MISSING_SHADOW_BOOK"))
                continue
            if book.condition_id != market.condition_id or book.neg_risk != market.neg_risk:
                shadow.append(self._empty_shadow(leg, _aware(book.timestamp), "SHADOW_BOOK_METADATA_MISMATCH"))
                continue
            age = (observed_now - _aware(book.timestamp)).total_seconds()
            if age < -1 or age > config.max_book_age_seconds:
                shadow.append(self._empty_shadow(leg, _aware(book.timestamp), "STALE_SHADOW_BOOK"))
                continue
            shadow.append(self._walk_shadow_leg(leg, market, book, config))
        return shadow

    @staticmethod
    def _empty_shadow(leg: LegExecution, observed_at: datetime, reason: str) -> ShadowLeg:
        return ShadowLeg(
            market_id=leg.market_id,
            condition_id=leg.condition_id,
            token_id=leg.token_id,
            outcome=leg.outcome,
            intended_quantity=leg.shares,
            filled_quantity=ZERO,
            average_price=None,
            notional=ZERO,
            fee=ZERO,
            observed_at=_aware(observed_at),
            reason=reason,
        )

    @staticmethod
    def _walk_shadow_leg(
        leg: LegExecution,
        market: MarketContext,
        book: OrderBook,
        config: PolymarketForwardConfig,
    ) -> ShadowLeg:
        if market.fee_schedule is None or not book.asks:
            return PolymarketStructuralForwardRunner._empty_shadow(
                leg,
                book.timestamp,
                "NO_FEE_SCHEDULE_OR_ASK_LIQUIDITY",
            )
        remaining = leg.shares
        filled = ZERO
        notional = ZERO
        fees = ZERO
        for level in book.asks:
            if remaining <= ZERO:
                break
            take = min(remaining, level.size)
            notional += take * level.price
            fees += taker_fee(
                take,
                level.price,
                market.fee_schedule,
                buffer_pct=config.fee_buffer_pct,
            )
            filled += take
            remaining -= take
        average = notional / filled if filled > ZERO else None
        return ShadowLeg(
            market_id=leg.market_id,
            condition_id=leg.condition_id,
            token_id=leg.token_id,
            outcome=leg.outcome,
            intended_quantity=leg.shares,
            filled_quantity=filled,
            average_price=average,
            notional=notional,
            fee=fees,
            observed_at=_aware(book.timestamp),
            reason=None if filled == leg.shares else "INSUFFICIENT_SHADOW_DEPTH",
        )

    def _persist_attempt(
        self,
        db: Session,
        study: ForwardStudy,
        candidate: StructuralCandidate,
        shadow: list[ShadowLeg],
        config: PolymarketForwardConfig,
        attempt_key: str,
    ) -> bool:
        opportunity = candidate.opportunity
        shadow_by_token = {leg.token_id: leg for leg in shadow}
        all_full = len(shadow_by_token) == len(opportunity.legs) and all(
            shadow_by_token.get(leg.token_id) is not None
            and shadow_by_token[leg.token_id].full
            for leg in opportunity.legs
        )
        shadow_gross = sum((row.notional for row in shadow), ZERO)
        shadow_fees = sum((row.fee for row in shadow), ZERO)
        allocated = shadow_gross + shadow_fees + config.operation_cost_usd
        gross_pnl = opportunity.payout - shadow_gross
        fees = shadow_fees + config.operation_cost_usd
        net_pnl = gross_pnl - fees
        shadow_roi = (net_pnl / allocated) * BPS if allocated > ZERO else ZERO
        qualifies = all_full and net_pnl > ZERO and shadow_roi >= config.min_edge_bps
        close_at = max((row.observed_at for row in shadow), default=datetime.now(timezone.utc))
        close_at = max(_aware(close_at), _aware(opportunity.captured_at), _aware(study.started_at))

        trade: ForwardTradeRecord | None = None
        if qualifies:
            planned_loss = allocated * config.planned_loss_pct
            trade = ForwardTradeRecord(
                study_id=study.id,
                external_key=f"{attempt_key}:trade",
                opened_at=max(_aware(opportunity.captured_at), _aware(study.started_at)),
                closed_at=close_at,
                gross_pnl_usd=gross_pnl,
                net_pnl_usd=net_pnl,
                fees_usd=fees,
                slippage_usd=ZERO,
                allocated_capital_usd=allocated,
                planned_loss_usd=planned_loss,
                metadata_json=_json(
                    {
                        "kind": opportunity.kind,
                        "event_id": opportunity.event_id,
                        "condition_id": opportunity.condition_id,
                        "quantity": opportunity.quantity,
                        "payout_usd": opportunity.payout,
                        "signal_total_cost_usd": opportunity.total_cost,
                        "signal_net_profit_usd": opportunity.net_profit,
                        "signal_roi_bps": opportunity.roi_bps,
                        "shadow_gross_cost_usd": shadow_gross,
                        "shadow_fees_usd": shadow_fees,
                        "operation_cost_reserve_usd": config.operation_cost_usd,
                        "shadow_roi_bps": shadow_roi,
                        "close_mechanic": (
                            "binary_ctf_merge"
                            if opportunity.kind == "binary_complete_set"
                            else "negrisk_no_convert"
                        ),
                        "live_execution": False,
                    }
                ),
            )
            db.add(trade)
            db.flush()

        for index, paper in enumerate(opportunity.legs):
            delayed = shadow_by_token.get(paper.token_id)
            if delayed is None:
                delayed = self._empty_shadow(paper, close_at, "MISSING_SHADOW_LEG")
            db.add(
                ForwardExecutionRecord(
                    study_id=study.id,
                    trade_id=trade.id if trade is not None else None,
                    external_key=f"{attempt_key}:leg:{index}",
                    observed_at=delayed.observed_at,
                    side="buy",
                    intended_quantity=paper.shares,
                    paper_filled_quantity=paper.shares,
                    shadow_filled_quantity=delayed.filled_quantity,
                    paper_average_price=paper.average_price,
                    shadow_average_price=delayed.average_price,
                    paper_cost_usd=paper.fee,
                    shadow_cost_usd=delayed.fee,
                    metadata_json=_json(
                        {
                            "kind": opportunity.kind,
                            "event_id": opportunity.event_id,
                            "condition_id": paper.condition_id,
                            "market_id": paper.market_id,
                            "token_id": paper.token_id,
                            "outcome": paper.outcome,
                            "signal_notional_usd": paper.notional,
                            "shadow_notional_usd": delayed.notional,
                            "shadow_reason": delayed.reason,
                            "operation_cost_reserve_usd": config.operation_cost_usd,
                        }
                    ),
                )
            )
        db.commit()
        return trade is not None

    @staticmethod
    def _signal_passes_cost_reserve(
        opportunity: StructuralOpportunity,
        config: PolymarketForwardConfig,
    ) -> bool:
        net = opportunity.net_profit - config.operation_cost_usd
        capital = opportunity.total_cost + config.operation_cost_usd
        roi = (net / capital) * BPS if capital > ZERO else ZERO
        return opportunity.eligible and opportunity.kind in IMMEDIATE_KINDS and net > ZERO and roi >= config.min_edge_bps

    @staticmethod
    def _required_capital(
        opportunity: StructuralOpportunity,
        config: PolymarketForwardConfig,
    ) -> Decimal:
        return opportunity.total_cost + config.operation_cost_usd

    @staticmethod
    def _attempt_key(candidate: StructuralCandidate, config: PolymarketForwardConfig) -> str:
        bucket = int(_aware(candidate.opportunity.captured_at).timestamp()) // config.attempt_interval_seconds
        return f"pmf:{candidate.identity}:{bucket}"

    @staticmethod
    def _attempt_exists(db: Session, study_id: str, attempt_key: str) -> bool:
        return db.scalar(
            select(ForwardExecutionRecord.id).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.like(f"{attempt_key}:%"),
            ).limit(1)
        ) is not None

    @staticmethod
    def _flat_equity(db: Session, study: ForwardStudy) -> Decimal:
        realised = db.scalar(
            select(func.coalesce(func.sum(ForwardTradeRecord.net_pnl_usd), ZERO)).where(
                ForwardTradeRecord.study_id == study.id
            )
        )
        return Decimal(study.initial_capital_usd) + Decimal(str(realised or ZERO))

    def _record_hourly_flat_nav(self, db: Session, study: ForwardStudy) -> None:
        observed_at = datetime.now(timezone.utc)
        bucket = observed_at.replace(minute=0, second=0, microsecond=0)
        exists = db.scalar(
            select(ForwardNavObservation.id).where(
                ForwardNavObservation.study_id == study.id,
                ForwardNavObservation.observed_at >= bucket,
                ForwardNavObservation.observed_at < bucket + timedelta(hours=1),
            ).limit(1)
        )
        if exists is not None:
            return
        nav = self._flat_equity(db, study)
        if nav <= ZERO:
            self._record_incident(
                db,
                study,
                observed_at,
                "critical",
                "PM_FORWARD_NAV_NON_POSITIVE",
                "computed Polymarket structural forward NAV is non-positive",
                True,
            )
            return
        db.add(
            ForwardNavObservation(
                study_id=study.id,
                observed_at=observed_at,
                nav_usd=nav,
                source="polymarket-structural-realised-nav",
            )
        )
        db.commit()

    @staticmethod
    def _has_integrity_failure(db: Session, study_id: str) -> bool:
        return bool(
            db.scalar(
                select(func.count()).select_from(ForwardStudyIncident).where(
                    ForwardStudyIncident.study_id == study_id,
                    ForwardStudyIncident.data_integrity.is_(True),
                )
            )
        )

    @staticmethod
    def _has_unresolved_critical(db: Session, study_id: str) -> bool:
        return bool(
            db.scalar(
                select(func.count()).select_from(ForwardStudyIncident).where(
                    ForwardStudyIncident.study_id == study_id,
                    ForwardStudyIncident.severity == "critical",
                    ForwardStudyIncident.resolved.is_(False),
                )
            )
        )

    @staticmethod
    def _record_incident(
        db: Session,
        study: ForwardStudy,
        now: datetime,
        severity: str,
        code: str,
        message: str,
        data_integrity: bool,
    ) -> None:
        bucket = _aware(now).replace(minute=0, second=0, microsecond=0)
        key = f"pmf:{code}:{bucket.isoformat()}"
        try:
            ForwardResearchService.record_incident(
                db,
                study_id=study.id,
                external_key=key,
                severity=severity,
                code=code,
                message=message[:2000],
                opened_at=_aware(now),
                data_integrity=data_integrity,
            )
        except ForwardResearchError as exc:
            if "conflicting retry" not in str(exc):
                raise
