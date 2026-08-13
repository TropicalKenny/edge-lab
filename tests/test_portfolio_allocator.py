from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base
import app.portfolio_models  # register audit tables for in-memory tests
from app.portfolio_allocator import (
    AllocationCandidate,
    AllocationError,
    AllocationInput,
    AllocationPolicy,
    PortfolioAllocator,
    TransferCost,
    VenueBalance,
)
from app.portfolio_api import AllocationRequest, allocate
from app.portfolio_models import PortfolioAllocationDecision, PortfolioAllocationRun, TreasuryRebalanceProposal

D = Decimal


def candidate(
    cid: str,
    *,
    strategy: str = "funding",
    venue: str = "hyperliquid",
    bucket: str = "funding/carry",
    edge: str = "0.02",
    confidence: str = "0.8",
    notional: str = "100",
    loss: str = "2",
    liquidity: str = "1000",
):
    return AllocationCandidate(
        candidate_id=cid,
        strategy=strategy,
        strategy_version="v1",
        venue=venue,
        instrument="TEST",
        correlation_bucket=bucket,
        expected_edge_pct=D(edge),
        confidence=D(confidence),
        proposed_notional_usd=D(notional),
        planned_max_loss_usd=D(loss),
        liquidity_capacity_usd=D(liquidity),
    )


def state(**overrides):
    values = dict(
        nav_usd=D("1000"),
        authorized_working_capital_usd=D("500"),
        vault_usd=D("500"),
        venue_balances=(VenueBalance("solana_working_treasury", D("300")),),
        mode="paper",
    )
    values.update(overrides)
    return AllocationInput(**values)


def policy(**overrides):
    values = dict(
        min_unallocated_pct=D("0.40"),
        global_planned_risk_pct=D("0.02"),
        bucket_planned_risk_pct=D("0.01"),
        max_strategy_notional_pct=D("0.20"),
        max_venue_notional_pct=D("0.35"),
        venue_float_buffer_pct=D("0.10"),
        min_rebalance_usd=D("25"),
        max_transfer_cost_pct=D("0.005"),
    )
    values.update(overrides)
    return AllocationPolicy(**values)


def test_live_mode_is_hard_rejected():
    allocator = PortfolioAllocator(policy())
    with pytest.raises(AllocationError, match="does not support live mode"):
        allocator.allocate(state(mode="live"), [candidate("a")], run_id="run-live")


def test_vault_is_untouched_and_authorized_capital_keeps_reserve():
    result = PortfolioAllocator(policy()).allocate(state(), [candidate("a", notional="500", loss="5")], run_id="run")
    assert result.vault_usd_untouched == D("500")
    assert result.reserve_floor_usd == D("200")
    assert result.newly_allocated_notional_usd <= D("300")
    assert result.authorized_working_capital_usd == D("500")


def test_existing_allocations_reduce_remaining_authorized_capital():
    s = state(
        existing_allocated_notional_usd=D("250"),
        existing_venue_notional_usd={"hyperliquid": D("250")},
        existing_strategy_notional_usd={"funding": D("150")},
    )
    result = PortfolioAllocator(policy(max_strategy_notional_pct=D("0.50"), max_venue_notional_pct=D("0.50"))).allocate(
        s, [candidate("a", notional="100", loss="1")], run_id="run"
    )
    assert result.newly_allocated_notional_usd == D("50")
    assert result.total_allocated_notional_usd == D("300")
    assert "SIZED_DOWN_BY_PORTFOLIO_LIMITS" in result.decisions[0].reasons


def test_correlation_bucket_risk_aggregates_across_strategies():
    allocator = PortfolioAllocator(policy(bucket_planned_risk_pct=D("0.01"), global_planned_risk_pct=D("0.05"), max_strategy_notional_pct=D("0.50")))
    candidates = [
        candidate("btc", strategy="trend", bucket="crypto-beta", notional="200", loss="8"),
        candidate("sol", strategy="meme", bucket="crypto-beta", notional="200", loss="8"),
    ]
    result = allocator.allocate(state(), candidates, run_id="run")
    assert sum(d.planned_loss_usd for d in result.decisions) <= D("10")
    assert result.planned_new_risk_usd <= D("10")


def test_score_uses_expected_profit_per_dollar_at_risk_not_position_size():
    small = candidate("small", edge="0.02", confidence="0.8", notional="100", loss="2")
    large = candidate("large", edge="0.02", confidence="0.8", notional="200", loss="4")
    assert PortfolioAllocator._candidate_score(small) == PortfolioAllocator._candidate_score(large)


def test_unknown_transfer_route_creates_no_treasury_proposal():
    allocator = PortfolioAllocator(policy(max_strategy_notional_pct=D("0.50")))
    result = allocator.allocate(state(), [candidate("a", notional="100", loss="1")], run_id="run")
    assert result.treasury_proposals == ()


def test_known_low_cost_route_creates_proposal_only_and_never_executes():
    allocator = PortfolioAllocator(policy(max_strategy_notional_pct=D("0.50")))
    route = TransferCost(
        source="solana_working_treasury",
        destination="hyperliquid",
        fixed_cost_usd=D("0.20"),
        variable_cost_bps=D("1"),
    )
    result = allocator.allocate(state(), [candidate("a", notional="100", loss="1")], transfer_costs=[route], run_id="run")
    assert len(result.treasury_proposals) == 1
    proposal = result.treasury_proposals[0]
    assert proposal.proposal_only is True
    assert proposal.requires_owner_approval is True
    assert proposal.executable is False
    assert proposal.source == "solana_working_treasury"


def test_treasury_proposal_cannot_spend_protected_reserve():
    allocator = PortfolioAllocator(policy(max_strategy_notional_pct=D("0.50")))
    route = TransferCost("solana_working_treasury", "hyperliquid", fixed_cost_usd=D("0.10"))
    result = allocator.allocate(state(), [candidate("a", notional="100", loss="1")], transfer_costs=[route], run_id="reserve")
    assert result.reserve_floor_usd == D("200")
    assert len(result.treasury_proposals) == 1
    proposal = result.treasury_proposals[0]
    assert proposal.amount_usd == D("100")
    assert D("300") - proposal.amount_usd >= result.reserve_floor_usd


def test_expensive_transfer_route_is_rejected():
    allocator = PortfolioAllocator(policy(max_strategy_notional_pct=D("0.50"), max_transfer_cost_pct=D("0.001")))
    route = TransferCost("solana_working_treasury", "hyperliquid", fixed_cost_usd=D("10"))
    result = allocator.allocate(state(), [candidate("a", notional="100", loss="1")], transfer_costs=[route], run_id="run")
    assert result.treasury_proposals == ()


def test_negative_existing_exposure_fails_closed():
    allocator = PortfolioAllocator(policy())
    with pytest.raises(AllocationError, match="negative values"):
        allocator.allocate(
            state(
                existing_allocated_notional_usd=D("10"),
                existing_venue_notional_usd={"hyperliquid": D("-1")},
            ),
            [candidate("a")],
            run_id="bad-negative",
        )


def test_inconsistent_existing_exposure_maps_fail_closed():
    allocator = PortfolioAllocator(policy())
    with pytest.raises(AllocationError, match="venue notionals"):
        allocator.allocate(
            state(
                existing_allocated_notional_usd=D("50"),
                existing_venue_notional_usd={"hyperliquid": D("60")},
            ),
            [candidate("a")],
            run_id="bad-map",
        )
    with pytest.raises(AllocationError, match="bucket risk"):
        allocator.allocate(
            state(
                existing_global_risk_usd=D("5"),
                existing_bucket_risk_usd={"crypto-beta": D("6")},
            ),
            [candidate("a")],
            run_id="bad-risk-map",
        )


def test_vault_and_authorized_working_capital_cannot_overlap_past_nav():
    allocator = PortfolioAllocator(policy())
    with pytest.raises(AllocationError, match="cannot exceed NAV"):
        allocator.allocate(
            state(vault_usd=D("600"), authorized_working_capital_usd=D("500")),
            [candidate("a")],
            run_id="overlap",
        )


def test_allocation_api_persists_auditable_run_and_proposal():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    request = AllocationRequest.model_validate(
        {
            "mode": "paper",
            "nav_usd": "1000",
            "authorized_working_capital_usd": "500",
            "vault_usd": "500",
            "venue_balances": [{"venue": "solana_working_treasury", "available_usd": "300"}],
            "candidates": [
                {
                    "candidate_id": "funding-1",
                    "strategy": "funding",
                    "strategy_version": "v1",
                    "venue": "hyperliquid",
                    "instrument": "BTC",
                    "correlation_bucket": "funding/carry",
                    "expected_edge_pct": "0.02",
                    "confidence": "0.8",
                    "proposed_notional_usd": "100",
                    "planned_max_loss_usd": "1",
                    "liquidity_capacity_usd": "1000",
                    "evidence_status": "AMBER",
                }
            ],
            "transfer_costs": [
                {
                    "source": "solana_working_treasury",
                    "destination": "hyperliquid",
                    "fixed_cost_usd": "0.1",
                    "variable_cost_bps": "1",
                }
            ],
        }
    )
    response = allocate(request, db)
    run_id = response["run_id"]
    stored_run = db.scalar(select(PortfolioAllocationRun).where(PortfolioAllocationRun.external_run_id == run_id))
    stored_decisions = list(db.scalars(select(PortfolioAllocationDecision).where(PortfolioAllocationDecision.run_id == run_id)).all())
    proposals = list(db.scalars(select(TreasuryRebalanceProposal).where(TreasuryRebalanceProposal.run_id == run_id)).all())
    assert stored_run is not None and stored_run.vault_usd_untouched == D("500")
    assert len(stored_decisions) == 1 and stored_decisions[0].evidence_status == "AMBER"
    assert proposals and proposals[0].executable is False and proposals[0].requires_owner_approval is True
    db.close()
