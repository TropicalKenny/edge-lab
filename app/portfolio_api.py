from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.portfolio_allocator import (
    AllocationCandidate,
    AllocationError,
    AllocationInput,
    AllocationPolicy,
    PortfolioAllocator,
    TransferCost,
    VenueBalance,
)
from app.portfolio_models import PortfolioAllocationDecision, PortfolioAllocationRun, TreasuryRebalanceProposal

router = APIRouter(prefix="/portfolio", tags=["portfolio-research"])
settings = get_settings()


class VenueBalanceRequest(BaseModel):
    venue: str = Field(min_length=1, max_length=100)
    available_usd: Decimal = Field(ge=0)


class TransferCostRequest(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    fixed_cost_usd: Decimal = Field(ge=0)
    variable_cost_bps: Decimal = Field(default=Decimal("0"), ge=0)
    min_transfer_usd: Decimal = Field(default=Decimal("0"), ge=0)


class AllocationCandidateRequest(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=100)
    strategy: str = Field(min_length=1, max_length=100)
    strategy_version: str = Field(min_length=1, max_length=100)
    venue: str = Field(min_length=1, max_length=64)
    instrument: str = Field(min_length=1, max_length=120)
    correlation_bucket: str = Field(min_length=1, max_length=100)
    expected_edge_pct: Decimal
    confidence: Decimal
    proposed_notional_usd: Decimal
    planned_max_loss_usd: Decimal
    liquidity_capacity_usd: Decimal
    current_notional_usd: Decimal = Decimal("0")
    evidence_status: Literal["RED", "AMBER", "GREEN-1", "GREEN-2", "GREEN-3"] = "RED"


class AllocationRequest(BaseModel):
    mode: Literal["paper", "shadow", "live"] = "paper"
    nav_usd: Decimal = Field(gt=0)
    authorized_working_capital_usd: Decimal = Field(ge=0)
    vault_usd: Decimal = Field(ge=0)
    existing_allocated_notional_usd: Decimal = Field(default=Decimal("0"), ge=0)
    existing_global_risk_usd: Decimal = Field(default=Decimal("0"), ge=0)
    existing_venue_notional_usd: dict[str, Decimal] = Field(default_factory=dict)
    existing_strategy_notional_usd: dict[str, Decimal] = Field(default_factory=dict)
    existing_bucket_risk_usd: dict[str, Decimal] = Field(default_factory=dict)
    venue_balances: list[VenueBalanceRequest]
    candidates: list[AllocationCandidateRequest]
    transfer_costs: list[TransferCostRequest] = Field(default_factory=list)


def _policy() -> AllocationPolicy:
    return AllocationPolicy(
        min_unallocated_pct=Decimal(str(settings.portfolio_min_unallocated_pct)),
        global_planned_risk_pct=Decimal(str(settings.portfolio_global_planned_risk_pct)),
        bucket_planned_risk_pct=Decimal(str(settings.portfolio_bucket_planned_risk_pct)),
        max_strategy_notional_pct=Decimal(str(settings.portfolio_max_strategy_notional_pct)),
        max_venue_notional_pct=Decimal(str(settings.portfolio_max_venue_notional_pct)),
        venue_float_buffer_pct=Decimal(str(settings.portfolio_venue_float_buffer_pct)),
        min_rebalance_usd=Decimal(str(settings.treasury_min_rebalance_usd)),
        max_transfer_cost_pct=Decimal(str(settings.treasury_max_transfer_cost_pct)),
    )


def _json(value) -> str:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


def _persist(db: Session, request: AllocationRequest, result, policy: AllocationPolicy) -> None:
    db.add(
        PortfolioAllocationRun(
            external_run_id=result.run_id,
            mode=result.mode,
            nav_usd=result.nav_usd,
            authorized_working_capital_usd=result.authorized_working_capital_usd,
            vault_usd_untouched=result.vault_usd_untouched,
            reserve_floor_usd=result.reserve_floor_usd,
            allocated_notional_usd=result.newly_allocated_notional_usd,
            planned_risk_usd=result.planned_new_risk_usd,
            input_json=request.model_dump_json(),
            policy_json=_json(asdict(policy)),
            created_at=result.created_at,
        )
    )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in request.candidates}
    for decision in result.decisions:
        original = candidate_by_id[decision.candidate_id]
        db.add(
            PortfolioAllocationDecision(
                run_id=result.run_id,
                candidate_id=decision.candidate_id,
                strategy=decision.strategy,
                strategy_version=original.strategy_version,
                venue=decision.venue,
                instrument=original.instrument,
                correlation_bucket=decision.correlation_bucket,
                evidence_status=original.evidence_status,
                requested_notional_usd=decision.requested_notional_usd,
                approved_notional_usd=decision.approved_notional_usd,
                planned_loss_usd=decision.planned_loss_usd,
                score=decision.score,
                approved=decision.approved,
                reasons_json=_json(list(decision.reasons)),
                created_at=result.created_at,
            )
        )
    for proposal in result.treasury_proposals:
        db.add(
            TreasuryRebalanceProposal(
                run_id=result.run_id,
                source=proposal.source,
                destination=proposal.destination,
                amount_usd=proposal.amount_usd,
                estimated_cost_usd=proposal.estimated_cost_usd,
                reason=proposal.reason,
                proposal_only=True,
                requires_owner_approval=True,
                executable=False,
                created_at=result.created_at,
            )
        )
    db.commit()


@router.post("/allocate")
def allocate(request: AllocationRequest, db: Session = Depends(get_db)):
    policy = _policy()
    allocator = PortfolioAllocator(policy)
    domain_input = AllocationInput(
        nav_usd=request.nav_usd,
        authorized_working_capital_usd=request.authorized_working_capital_usd,
        vault_usd=request.vault_usd,
        venue_balances=tuple(VenueBalance(**item.model_dump()) for item in request.venue_balances),
        existing_allocated_notional_usd=request.existing_allocated_notional_usd,
        existing_venue_notional_usd=request.existing_venue_notional_usd,
        existing_strategy_notional_usd=request.existing_strategy_notional_usd,
        existing_bucket_risk_usd=request.existing_bucket_risk_usd,
        existing_global_risk_usd=request.existing_global_risk_usd,
        mode=request.mode,
    )
    candidates = tuple(AllocationCandidate(**item.model_dump()) for item in request.candidates)
    transfer_costs = tuple(TransferCost(**item.model_dump()) for item in request.transfer_costs)
    run_id = str(uuid.uuid4())
    try:
        result = allocator.allocate(domain_input, candidates, transfer_costs=transfer_costs, run_id=run_id)
        _persist(db, request, result, policy)
        return {
            **asdict(result),
            "safety": {
                "research_only": True,
                "live_mode_supported": False,
                "vault_access": False,
                "transfer_execution": False,
                "treasury_proposals_require_owner_approval": True,
            },
        }
    except AllocationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.scalar(select(PortfolioAllocationRun).where(PortfolioAllocationRun.external_run_id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="allocation run not found")
    decisions = list(
        db.scalars(
            select(PortfolioAllocationDecision)
            .where(PortfolioAllocationDecision.run_id == run_id)
            .order_by(PortfolioAllocationDecision.created_at, PortfolioAllocationDecision.candidate_id)
        ).all()
    )
    proposals = list(
        db.scalars(
            select(TreasuryRebalanceProposal)
            .where(TreasuryRebalanceProposal.run_id == run_id)
            .order_by(TreasuryRebalanceProposal.created_at, TreasuryRebalanceProposal.destination)
        ).all()
    )
    return {
        "run": {column.name: getattr(run, column.name) for column in run.__table__.columns},
        "decisions": [
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
            for row in decisions
        ],
        "treasury_proposals": [
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
            for row in proposals
        ],
    }


@router.get("/treasury/status")
def treasury_status():
    return {
        "mode": "proposal-only",
        "home_network": "solana",
        "home_asset": "native USDC",
        "vault_access": False,
        "can_transfer": False,
        "can_bridge": False,
        "owner_approval_required": True,
    }
