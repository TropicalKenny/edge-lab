import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import (
    ForwardExecutionRecord,
    ForwardNavObservation,
    ForwardStudyIncident,
    ForwardTradeRecord,
)
from app.models import Base, Strategy
from app.services import HealthRegistry
from app.solana_forward import SolanaForwardConfigError
from app.solana_forward_operational import (
    OperationalSolanaForwardBootstrap,
    OperationalSolanaLaunchBaselineForwardRunner,
    SolanaForwardOperationalError,
)
from app.venues.solana import JupiterShadowQuote, USDC_MINT
from app.venues.solana_models import (
    SolanaForensicFeatureSnapshot,
    SolanaLaunchEvent,
    SolanaSecuritySnapshot,
)

D = Decimal
TOKEN_MINT = "Meme111111111111111111111111111111111111111"
CREATOR = "Creator1111111111111111111111111111111111111"


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def scenario_now() -> datetime:
    # ForwardResearchService deliberately rejects future evidence. Starting the
    # synthetic clock two hours in the past lets tests advance 10–61 minutes
    # without weakening that production integrity rule.
    return datetime.now(timezone.utc) - timedelta(hours=2)


def settings(**overrides) -> Settings:
    values = {
        "solana_forward_study_external_id": "solana-test-m6g-v1",
        "solana_forward_initial_capital_usd": 1000.0,
        "solana_forward_entry_notional_usd": 25.0,
        "solana_forward_decision_delay_minutes": 5,
        "solana_forward_max_candidate_age_minutes": 30,
        "solana_forward_hold_minutes": 30,
        "solana_forward_max_exit_delay_minutes": 30,
        "solana_forward_shadow_delay_ms": 0,
        "solana_forward_max_quote_price_impact_pct": 0.05,
        "solana_forward_min_preflight_exit_ratio": 0.90,
        "solana_forward_max_open_positions": 5,
        "solana_forward_max_entries_per_cycle": 3,
        "solana_forward_nav_interval_seconds": 300,
        "solana_forward_health_max_nav_age_seconds": 900,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def quote(
    *,
    input_mint: str,
    output_mint: str,
    in_amount: int,
    out_amount: int,
    in_usd: str,
    out_usd: str,
    captured_at: datetime,
    impact: str = "0.01",
) -> JupiterShadowQuote:
    return JupiterShadowQuote(
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=in_amount,
        out_amount=out_amount,
        in_usd_value=D(in_usd),
        out_usd_value=D(out_usd),
        price_impact_pct=D(impact),
        fee_bps=None,
        fee_mint=None,
        platform_fee_amount=None,
        signature_fee_lamports=None,
        prioritization_fee_lamports=None,
        router="jupiter",
        mode="quote",
        request_id="test",
        quote_time_ms=5,
        transaction_present=False,
        captured_at=captured_at,
    )


class FakeJupiter:
    def __init__(self, quotes):
        self.quotes = list(quotes)
        self.calls = []

    async def order_quote(self, *, input_mint: str, output_mint: str, amount: int):
        self.calls.append((input_mint, output_mint, amount))
        if not self.quotes:
            raise RuntimeError("no fake quote available")
        value = self.quotes.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class NeverForensics:
    async def analyze_mint(self, *args, **kwargs):
        raise AssertionError("persisted decision feature should have been used")


def runner(fake_jupiter: FakeJupiter):
    return OperationalSolanaLaunchBaselineForwardRunner(
        forensics=NeverForensics(),
        jupiter=fake_jupiter,
        health=HealthRegistry(),
    )


def add_candidate(
    db: Session,
    *,
    launch_at: datetime,
    feature_at: datetime,
    safe: bool = True,
):
    db.add_all(
        [
            SolanaLaunchEvent(
                signature="sig-1",
                slot=1,
                creator=CREATOR,
                mint=TOKEN_MINT,
                program_id="pump",
                logs_json="[]",
                observed_at=launch_at,
            ),
            SolanaSecuritySnapshot(
                mint=TOKEN_MINT,
                mintable=False,
                freezable=False,
                non_transferable=False,
                metadata_mutable=False,
                malicious_creator=False if safe else True,
                top10_holder_pct=D("0.40"),
                transfer_fee_rate=D("0"),
                trusted_token=None,
                raw_json="{}",
                captured_at=feature_at,
            ),
            SolanaForensicFeatureSnapshot(
                mint=TOKEN_MINT,
                creator=CREATOR,
                source="pump_onchain",
                age_minutes=D("5"),
                liquidity_usd=D("10000"),
                market_cap=D("50000"),
                momentum_score=D("0"),
                sell_ratio_5m=D("0.5"),
                volume_acceleration=D("1"),
                liquidity_to_mcap=D("0.2"),
                price_change_5m=D("0"),
                price_change_1h=D("0"),
                mintable=False,
                freezable=False,
                malicious_creator=False if safe else True,
                top10_holder_pct=D("0.40"),
                transfer_fee_rate=D("0"),
                exit_quote_usd=D("24"),
                exit_price_impact_pct=D("0.01"),
                missing_fields_json="[]",
                captured_at=feature_at,
            ),
        ]
    )
    db.commit()


def entry_quotes(now: datetime):
    return [
        quote(
            input_mint=USDC_MINT,
            output_mint=TOKEN_MINT,
            in_amount=25_000_000,
            out_amount=1_000_000,
            in_usd="25",
            out_usd="24.9",
            captured_at=now,
        ),
        quote(
            input_mint=USDC_MINT,
            output_mint=TOKEN_MINT,
            in_amount=25_000_000,
            out_amount=980_000,
            in_usd="25",
            out_usd="24.8",
            captured_at=now + timedelta(milliseconds=1),
        ),
        quote(
            input_mint=TOKEN_MINT,
            output_mint=USDC_MINT,
            in_amount=980_000,
            out_amount=24_500_000,
            in_usd="24.8",
            out_usd="24.5",
            captured_at=now + timedelta(milliseconds=2),
        ),
    ]


def prepared_study(db: Session, now: datetime, *, safe: bool = True):
    study = OperationalSolanaForwardBootstrap.bootstrap(
        db,
        settings=settings(),
        now=now - timedelta(minutes=10),
    )
    add_candidate(
        db,
        launch_at=now - timedelta(minutes=6),
        feature_at=now - timedelta(minutes=1),
        safe=safe,
    )
    return study


def test_bootstrap_is_idempotent_freezes_baseline_and_keeps_strategy_red():
    now = scenario_now()
    db = db_session()
    cfg = settings()
    first = OperationalSolanaForwardBootstrap.bootstrap(db, settings=cfg, now=now)
    second = OperationalSolanaForwardBootstrap.bootstrap(
        db, settings=cfg, now=now + timedelta(seconds=10)
    )
    assert first.id == second.id
    stored = json.loads(first.study_config_json)
    assert stored["entry_policy"] == "chronological_safety_exitability_baseline_no_alpha_score"
    assert stored["entry_notional_usd"] == "25.0"
    assert stored["nav_interval_seconds"] == 300
    strategy = db.scalar(select(Strategy).where(Strategy.slug == "solana-pump-safety-baseline"))
    assert strategy is not None and strategy.status == "red"
    nav = db.scalar(select(ForwardNavObservation).where(ForwardNavObservation.study_id == first.id))
    assert nav is not None and D(nav.nav_usd) == D("1000")
    db.close()


def test_bootstrap_rejects_config_drift_and_implicit_leverage():
    now = scenario_now()
    db = db_session()
    OperationalSolanaForwardBootstrap.bootstrap(db, settings=settings(), now=now)
    with pytest.raises(SolanaForwardOperationalError, match="study_config"):
        OperationalSolanaForwardBootstrap.bootstrap(
            db,
            settings=settings(solana_forward_entry_notional_usd=20.0),
        )
    db.close()

    db = db_session()
    with pytest.raises(SolanaForwardOperationalError, match="no-leverage"):
        OperationalSolanaForwardBootstrap.bootstrap(
            db,
            settings=settings(
                solana_forward_initial_capital_usd=100.0,
                solana_forward_entry_notional_usd=25.0,
                solana_forward_max_open_positions=5,
                solana_forward_study_external_id="too-much-notional",
            ),
            now=now,
        )
    db.close()


def test_unsafe_security_feature_is_never_quoted():
    now = scenario_now()
    db = db_session()
    study = prepared_study(db, now, safe=False)
    fake = FakeJupiter([])
    result = asyncio.run(runner(fake).run_study_once(db, study, now=now))
    assert result.action == "cycle"
    assert fake.calls == []
    assert db.scalar(select(ForwardExecutionRecord)) is None
    db.close()


def test_valid_entry_uses_shadow_amount_and_exit_pnl_reconciles():
    now = scenario_now()
    db = db_session()
    study = prepared_study(db, now)
    fake = FakeJupiter(entry_quotes(now))
    first = asyncio.run(runner(fake).run_study_once(db, study, now=now))
    assert "opened=1" in first.detail
    entry = db.scalar(
        select(ForwardExecutionRecord).where(
            ForwardExecutionRecord.external_key == "solana-entry:sig-1"
        )
    )
    metadata = json.loads(entry.metadata_json)
    assert metadata["token_amount_atomic"] == 980_000
    assert D(metadata["entry_in_usd"]) == D("25")

    exit_at = now + timedelta(minutes=31)
    fake.quotes.extend(
        [
            quote(
                input_mint=TOKEN_MINT,
                output_mint=USDC_MINT,
                in_amount=980_000,
                out_amount=29_500_000,
                in_usd="30",
                out_usd="29.5",
                captured_at=exit_at,
            ),
            quote(
                input_mint=TOKEN_MINT,
                output_mint=USDC_MINT,
                in_amount=980_000,
                out_amount=29_000_000,
                in_usd="30",
                out_usd="29",
                captured_at=exit_at + timedelta(milliseconds=1),
            ),
        ]
    )
    second = asyncio.run(runner(fake).run_study_once(db, study, now=exit_at))
    assert "closed=1" in second.detail
    trade = db.scalar(select(ForwardTradeRecord).where(ForwardTradeRecord.study_id == study.id))
    assert trade is not None
    assert D(trade.gross_pnl_usd) == D("5.2")
    assert D(trade.slippage_usd) == D("1.2")
    assert D(trade.net_pnl_usd) == D("4.0")
    assert D(trade.planned_loss_usd) == D("25")
    db.close()


def test_open_position_nav_uses_current_executable_exit_mark():
    now = scenario_now()
    db = db_session()
    study = prepared_study(db, now)
    fake = FakeJupiter(entry_quotes(now))
    asyncio.run(runner(fake).run_study_once(db, study, now=now))

    mark_at = now + timedelta(minutes=10)
    fake.quotes.append(
        quote(
            input_mint=TOKEN_MINT,
            output_mint=USDC_MINT,
            in_amount=980_000,
            out_amount=20_000_000,
            in_usd="21",
            out_usd="20",
            captured_at=mark_at,
        )
    )
    asyncio.run(runner(fake).run_study_once(db, study, now=mark_at))
    nav = db.scalar(
        select(ForwardNavObservation)
        .where(ForwardNavObservation.study_id == study.id)
        .order_by(ForwardNavObservation.observed_at.desc())
        .limit(1)
    )
    assert nav.source == "solana-forward-executable-liquidation-nav"
    assert D(nav.nav_usd) == D("995")
    db.close()


def test_missing_executable_nav_mark_prevents_new_risk():
    now = scenario_now()
    db = db_session()
    study = prepared_study(db, now)
    fake = FakeJupiter(entry_quotes(now))
    asyncio.run(runner(fake).run_study_once(db, study, now=now))
    before = len(fake.calls)
    result = asyncio.run(
        runner(fake).run_study_once(db, study, now=now + timedelta(minutes=10))
    )
    assert result.action == "waiting"
    assert len(fake.calls) == before + 1
    db.close()


def test_exit_route_missing_through_deadline_becomes_full_loss():
    now = scenario_now()
    db = db_session()
    study = prepared_study(db, now)
    fake = FakeJupiter(entry_quotes(now))
    asyncio.run(runner(fake).run_study_once(db, study, now=now))
    asyncio.run(
        runner(fake).run_study_once(db, study, now=now + timedelta(minutes=61))
    )
    trade = db.scalar(select(ForwardTradeRecord).where(ForwardTradeRecord.study_id == study.id))
    assert trade is not None
    assert D(trade.net_pnl_usd) == D("-25")
    assert json.loads(trade.metadata_json)["exit_status"] == "forced_loss"
    db.close()


def test_corrupt_open_journal_is_permanent_integrity_failure_without_quotes():
    now = scenario_now()
    db = db_session()
    study = OperationalSolanaForwardBootstrap.bootstrap(
        db,
        settings=settings(),
        now=now - timedelta(minutes=10),
    )
    db.add(
        ForwardExecutionRecord(
            study_id=study.id,
            trade_id=None,
            external_key="solana-entry:broken",
            observed_at=now - timedelta(minutes=1),
            side="buy",
            intended_quantity=D("25000000"),
            paper_filled_quantity=D("25000000"),
            shadow_filled_quantity=D("25000000"),
            paper_average_price=D("0.000025"),
            shadow_average_price=D("0.000025"),
            paper_cost_usd=D("0"),
            shadow_cost_usd=D("0"),
            metadata_json='{"status":"open"}',
        )
    )
    db.commit()
    fake = FakeJupiter([])
    result = asyncio.run(runner(fake).run_study_once(db, study, now=now))
    assert result.action == "blocked"
    incident = db.scalar(
        select(ForwardStudyIncident).where(
            ForwardStudyIncident.study_id == study.id,
            ForwardStudyIncident.code == "SOLANA_FORWARD_JOURNAL_CORRUPT",
        )
    )
    assert incident is not None and incident.data_integrity is True
    assert fake.calls == []
    db.close()


def test_core_config_rejects_excessive_price_impact_boundary():
    db = db_session()
    with pytest.raises(SolanaForwardConfigError, match="maximum quote price impact"):
        OperationalSolanaForwardBootstrap.bootstrap(
            db,
            settings=settings(
                solana_forward_study_external_id="bad-impact",
                solana_forward_max_quote_price_impact_pct=0.30,
            ),
            now=scenario_now(),
        )
    db.close()
