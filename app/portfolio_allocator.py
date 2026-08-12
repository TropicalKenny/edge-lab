from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Literal

ZERO = Decimal("0")
ONE = Decimal("1")


class AllocationError(ValueError):
    pass


@dataclass(frozen=True)
class AllocationCandidate:
    candidate_id: str
    strategy: str
    strategy_version: str
    venue: str
    instrument: str
    correlation_bucket: str
    expected_edge_pct: Decimal
    confidence: Decimal
    proposed_notional_usd: Decimal
    planned_max_loss_usd: Decimal
    liquidity_capacity_usd: Decimal
    current_notional_usd: Decimal = ZERO
    evidence_status: Literal["RED", "AMBER", "GREEN-1", "GREEN-2", "GREEN-3"] = "RED"


@dataclass(frozen=True)
class VenueBalance:
    venue: str
    available_usd: Decimal


@dataclass(frozen=True)
class TransferCost:
    source: str
    destination: str
    fixed_cost_usd: Decimal
    variable_cost_bps: Decimal = ZERO
    min_transfer_usd: Decimal = ZERO

    def estimate(self, amount_usd: Decimal) -> Decimal:
        if amount_usd <= ZERO:
            return ZERO
        return self.fixed_cost_usd + amount_usd * self.variable_cost_bps / Decimal("10000")


@dataclass(frozen=True)
class AllocationInput:
    nav_usd: Decimal
    authorized_working_capital_usd: Decimal
    vault_usd: Decimal
    venue_balances: tuple[VenueBalance, ...]
    existing_bucket_risk_usd: dict[str, Decimal] = field(default_factory=dict)
    existing_global_risk_usd: Decimal = ZERO
    mode: Literal["paper", "shadow", "live"] = "paper"


@dataclass(frozen=True)
class AllocationDecision:
    candidate_id: str
    strategy: str
    venue: str
    correlation_bucket: str
    requested_notional_usd: Decimal
    approved_notional_usd: Decimal
    planned_loss_usd: Decimal
    score: Decimal
    approved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TreasuryProposal:
    source: str
    destination: str
    amount_usd: Decimal
    estimated_cost_usd: Decimal
    reason: str
    proposal_only: bool = True
    requires_owner_approval: bool = True
    executable: bool = False


@dataclass(frozen=True)
class AllocationResult:
    run_id: str
    mode: str
    nav_usd: Decimal
    authorized_working_capital_usd: Decimal
    vault_usd_untouched: Decimal
    reserve_floor_usd: Decimal
    allocated_notional_usd: Decimal
    planned_risk_usd: Decimal
    decisions: tuple[AllocationDecision, ...]
    venue_targets_usd: dict[str, Decimal]
    treasury_proposals: tuple[TreasuryProposal, ...]
    created_at: datetime


@dataclass(frozen=True)
class AllocationPolicy:
    min_unallocated_pct: Decimal = Decimal("0.40")
    global_planned_risk_pct: Decimal = Decimal("0.02")
    bucket_planned_risk_pct: Decimal = Decimal("0.01")
    max_strategy_notional_pct: Decimal = Decimal("0.20")
    max_venue_notional_pct: Decimal = Decimal("0.35")
    venue_float_buffer_pct: Decimal = Decimal("0.10")
    min_rebalance_usd: Decimal = Decimal("25")
    max_transfer_cost_pct: Decimal = Decimal("0.005")

    def validate(self) -> None:
        for name, value in (
            ("min_unallocated_pct", self.min_unallocated_pct),
            ("global_planned_risk_pct", self.global_planned_risk_pct),
            ("bucket_planned_risk_pct", self.bucket_planned_risk_pct),
            ("max_strategy_notional_pct", self.max_strategy_notional_pct),
            ("max_venue_notional_pct", self.max_venue_notional_pct),
            ("venue_float_buffer_pct", self.venue_float_buffer_pct),
            ("max_transfer_cost_pct", self.max_transfer_cost_pct),
        ):
            if value < ZERO or value > ONE:
                raise AllocationError(f"{name} must be between 0 and 1")
        if self.min_rebalance_usd < ZERO:
            raise AllocationError("min_rebalance_usd cannot be negative")


class PortfolioAllocator:
    """Deterministic research allocator. It cannot move funds or authorize live capital."""

    def __init__(self, policy: AllocationPolicy) -> None:
        policy.validate()
        self.policy = policy

    @staticmethod
    def _candidate_score(candidate: AllocationCandidate) -> Decimal:
        if candidate.planned_max_loss_usd <= ZERO:
            return ZERO
        return candidate.expected_edge_pct * candidate.confidence / candidate.planned_max_loss_usd

    @staticmethod
    def _validate_candidate(candidate: AllocationCandidate) -> tuple[str, ...]:
        reasons: list[str] = []
        if candidate.expected_edge_pct <= ZERO:
            reasons.append("NON_POSITIVE_EDGE")
        if candidate.confidence <= ZERO or candidate.confidence > ONE:
            reasons.append("INVALID_CONFIDENCE")
        if candidate.proposed_notional_usd <= ZERO:
            reasons.append("INVALID_NOTIONAL")
        if candidate.planned_max_loss_usd <= ZERO:
            reasons.append("INVALID_PLANNED_LOSS")
        if candidate.liquidity_capacity_usd <= ZERO:
            reasons.append("NO_LIQUIDITY_CAPACITY")
        if not candidate.correlation_bucket:
            reasons.append("MISSING_CORRELATION_BUCKET")
        return tuple(reasons)

    def allocate(
        self,
        allocation_input: AllocationInput,
        candidates: Iterable[AllocationCandidate],
        *,
        transfer_costs: Iterable[TransferCost] = (),
        run_id: str,
    ) -> AllocationResult:
        if allocation_input.mode == "live":
            raise AllocationError("Milestone 5 allocator does not support live mode")
        if allocation_input.nav_usd <= ZERO:
            raise AllocationError("nav_usd must be positive")
        if allocation_input.authorized_working_capital_usd < ZERO:
            raise AllocationError("authorized working capital cannot be negative")
        if allocation_input.authorized_working_capital_usd > allocation_input.nav_usd:
            raise AllocationError("authorized working capital cannot exceed NAV")
        if allocation_input.vault_usd < ZERO:
            raise AllocationError("vault_usd cannot be negative")

        nav = allocation_input.nav_usd
        authorized = allocation_input.authorized_working_capital_usd
        reserve_floor = authorized * self.policy.min_unallocated_pct
        deployable_capital = max(ZERO, authorized - reserve_floor)
        global_risk_cap = nav * self.policy.global_planned_risk_pct
        bucket_risk_cap = nav * self.policy.bucket_planned_risk_pct
        strategy_notional_cap = nav * self.policy.max_strategy_notional_pct
        venue_notional_cap = nav * self.policy.max_venue_notional_pct

        global_risk_used = max(ZERO, allocation_input.existing_global_risk_usd)
        bucket_risk_used = {k: max(ZERO, v) for k, v in allocation_input.existing_bucket_risk_usd.items()}
        venue_notional_used: dict[str, Decimal] = {}
        strategy_notional_used: dict[str, Decimal] = {}
        total_notional = ZERO
        decisions: list[AllocationDecision] = []

        ordered = sorted(
            list(candidates),
            key=lambda c: (self._candidate_score(c), c.expected_edge_pct, c.confidence, c.candidate_id),
            reverse=True,
        )

        for candidate in ordered:
            reasons = list(self._validate_candidate(candidate))
            score = self._candidate_score(candidate)
            if reasons:
                decisions.append(
                    AllocationDecision(
                        candidate_id=candidate.candidate_id,
                        strategy=candidate.strategy,
                        venue=candidate.venue,
                        correlation_bucket=candidate.correlation_bucket,
                        requested_notional_usd=candidate.proposed_notional_usd,
                        approved_notional_usd=ZERO,
                        planned_loss_usd=ZERO,
                        score=score,
                        approved=False,
                        reasons=tuple(reasons),
                    )
                )
                continue

            remaining_capital = max(ZERO, deployable_capital - total_notional)
            venue_remaining = max(ZERO, venue_notional_cap - venue_notional_used.get(candidate.venue, ZERO))
            strategy_remaining = max(ZERO, strategy_notional_cap - strategy_notional_used.get(candidate.strategy, ZERO))
            liquidity_remaining = max(ZERO, candidate.liquidity_capacity_usd - candidate.current_notional_usd)
            risk_fraction = candidate.planned_max_loss_usd / candidate.proposed_notional_usd
            global_risk_remaining = max(ZERO, global_risk_cap - global_risk_used)
            bucket_risk_remaining = max(
                ZERO,
                bucket_risk_cap - bucket_risk_used.get(candidate.correlation_bucket, ZERO),
            )
            risk_limited_notional = (
                min(global_risk_remaining, bucket_risk_remaining) / risk_fraction
                if risk_fraction > ZERO
                else ZERO
            )

            approved_notional = min(
                candidate.proposed_notional_usd,
                remaining_capital,
                venue_remaining,
                strategy_remaining,
                liquidity_remaining,
                risk_limited_notional,
            )
            if approved_notional <= ZERO:
                if remaining_capital <= ZERO:
                    reasons.append("AUTHORIZED_CAPITAL_EXHAUSTED")
                if venue_remaining <= ZERO:
                    reasons.append("VENUE_NOTIONAL_CAP")
                if strategy_remaining <= ZERO:
                    reasons.append("STRATEGY_NOTIONAL_CAP")
                if liquidity_remaining <= ZERO:
                    reasons.append("LIQUIDITY_CAPACITY")
                if global_risk_remaining <= ZERO:
                    reasons.append("GLOBAL_RISK_CAP")
                if bucket_risk_remaining <= ZERO:
                    reasons.append("CORRELATION_BUCKET_RISK_CAP")
                decisions.append(
                    AllocationDecision(
                        candidate_id=candidate.candidate_id,
                        strategy=candidate.strategy,
                        venue=candidate.venue,
                        correlation_bucket=candidate.correlation_bucket,
                        requested_notional_usd=candidate.proposed_notional_usd,
                        approved_notional_usd=ZERO,
                        planned_loss_usd=ZERO,
                        score=score,
                        approved=False,
                        reasons=tuple(reasons or ["NO_CAPACITY"]),
                    )
                )
                continue

            approved_loss = approved_notional * risk_fraction
            if approved_notional < candidate.proposed_notional_usd:
                reasons.append("SIZED_DOWN_BY_PORTFOLIO_LIMITS")
            total_notional += approved_notional
            global_risk_used += approved_loss
            bucket_risk_used[candidate.correlation_bucket] = (
                bucket_risk_used.get(candidate.correlation_bucket, ZERO) + approved_loss
            )
            venue_notional_used[candidate.venue] = venue_notional_used.get(candidate.venue, ZERO) + approved_notional
            strategy_notional_used[candidate.strategy] = strategy_notional_used.get(candidate.strategy, ZERO) + approved_notional
            decisions.append(
                AllocationDecision(
                    candidate_id=candidate.candidate_id,
                    strategy=candidate.strategy,
                    venue=candidate.venue,
                    correlation_bucket=candidate.correlation_bucket,
                    requested_notional_usd=candidate.proposed_notional_usd,
                    approved_notional_usd=approved_notional,
                    planned_loss_usd=approved_loss,
                    score=score,
                    approved=True,
                    reasons=tuple(reasons),
                )
            )

        venue_targets = {
            venue: min(
                venue_notional_cap,
                amount * (ONE + self.policy.venue_float_buffer_pct),
            )
            for venue, amount in venue_notional_used.items()
            if amount > ZERO
        }
        proposals = self._treasury_proposals(
            venue_targets=venue_targets,
            venue_balances=allocation_input.venue_balances,
            transfer_costs=tuple(transfer_costs),
        )
        return AllocationResult(
            run_id=run_id,
            mode=allocation_input.mode,
            nav_usd=nav,
            authorized_working_capital_usd=authorized,
            vault_usd_untouched=allocation_input.vault_usd,
            reserve_floor_usd=reserve_floor,
            allocated_notional_usd=total_notional,
            planned_risk_usd=max(ZERO, global_risk_used - allocation_input.existing_global_risk_usd),
            decisions=tuple(decisions),
            venue_targets_usd=venue_targets,
            treasury_proposals=tuple(proposals),
            created_at=datetime.now(timezone.utc),
        )

    def _treasury_proposals(
        self,
        *,
        venue_targets: dict[str, Decimal],
        venue_balances: tuple[VenueBalance, ...],
        transfer_costs: tuple[TransferCost, ...],
    ) -> list[TreasuryProposal]:
        balances = {b.venue: max(ZERO, b.available_usd) for b in venue_balances}
        working_treasury = balances.get("solana_working_treasury", ZERO)
        routes = {(r.source, r.destination): r for r in transfer_costs}
        proposals: list[TreasuryProposal] = []
        remaining_treasury = working_treasury
        for venue, target in sorted(venue_targets.items()):
            current = balances.get(venue, ZERO)
            gap = target - current
            if gap < self.policy.min_rebalance_usd:
                continue
            route = routes.get(("solana_working_treasury", venue))
            if route is None:
                continue
            amount = min(gap, remaining_treasury)
            if amount < max(self.policy.min_rebalance_usd, route.min_transfer_usd):
                continue
            cost = route.estimate(amount)
            if amount <= ZERO or cost / amount > self.policy.max_transfer_cost_pct:
                continue
            proposals.append(
                TreasuryProposal(
                    source="solana_working_treasury",
                    destination=venue,
                    amount_usd=amount,
                    estimated_cost_usd=cost,
                    reason="working-float target gap within known transfer-cost policy",
                )
            )
            remaining_treasury -= amount
        return proposals
