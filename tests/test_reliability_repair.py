import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.dashboard_api import _study_payload
from app.evaluation_lookup import latest_study_evaluation
from app.forward_models import ForwardNavObservation, ForwardStudyIncident
from app.forward_operations import ForwardOperationsService
from app.forward_research import ForwardResearchService
from app.models import Base
from app.services import HealthRegistry
from app.solana_forward import SolanaForwardConfig, SolanaLaunchBaselineForwardRunner
from app.solana_forward_ops import study_statuses
from app.solana_meme_forward import M6LMemeConfig, OperationalSolanaMemeMomentumForwardRunner, alpha_score
from app.solana_meme_forward_operational import M6LMemeBootstrap


def fixture():
    db = Session(create_engine('sqlite:///:memory:'))
    Base.metadata.create_all(db.bind)
    now = datetime.now(timezone.utc) - timedelta(hours=2)
    cfg = Settings(_env_file=None)
    studies = M6LMemeBootstrap.bootstrap_all(db, settings=cfg, now=now)
    return db, now, cfg, studies


def test_momentum_and_available_acceleration_are_mandatory():
    db, _, _, studies = fixture()
    config = M6LMemeConfig.from_study(studies[1])
    f = SimpleNamespace(age_minutes=D('5'), momentum_score=D('-0.2'),
                        sell_ratio_5m=D('.2'), volume_acceleration=D('3'),
                        price_change_5m=D('10'), market_cap=D('3000'), liquidity_usd=0)
    score, accepted, reasons, _ = alpha_score(f, config)
    assert score >= 3 and not accepted and 'MOMENTUM_BELOW_ENTRY' in reasons
    f.momentum_score=D('.2'); f.volume_acceleration=D('.5')
    assert not alpha_score(f, config)[1]
    f.volume_acceleration=None
    assert alpha_score(f, config)[1]


def test_repeated_incidents_preserve_first_timestamp_and_separate_messages():
    db, now, _, studies = fixture()
    for offset, message in [(0,'missing exit A'),(60,'missing exit A'),(120,'missing exit B')]:
        SolanaLaunchBaselineForwardRunner._record_incident(db, studies[1], now+timedelta(seconds=offset),
            severity='error', code='QUOTE_UNAVAILABLE', message=message, data_integrity=False)
    rows=db.scalars(select(ForwardStudyIncident).order_by(ForwardStudyIncident.opened_at)).all()
    assert len(rows)==2
    assert rows[0].opened_at.replace(tzinfo=timezone.utc)==now


def test_lifetime_drawdown_survives_chart_window_and_total_incident_count():
    db, now, _, studies=fixture();study=studies[1]
    for i in range(1,81):
        db.add(ForwardNavObservation(study_id=study.id, observed_at=now+timedelta(minutes=i),
            nav_usd=D('700') if i==1 else D('950'), source='test'))
    db.commit()
    payload=_study_payload(db,study,datetime.now(timezone.utc))
    assert payload['observed_max_drawdown_pct']==D('.3')
    assert len(payload['nav_history'])==60
    assert payload['total_pnl_usd']==D('-50')
    assert payload['drawdown_scope']=='lifetime'


def test_both_cohorts_evaluate_and_report_their_own_evidence():
    db, now, _, studies=fixture()
    ticks=ForwardOperationsService.evaluate_due_studies(db,now=now+timedelta(minutes=10))
    assert [t.action for t in ticks]==['evaluated','evaluated']
    runs=[latest_study_evaluation(db,s) for s in studies]
    assert runs[0].id!=runs[1].id
    assert [json.loads(r.metrics_json)['study_id'] for r in runs]==[s.id for s in studies]
    # An unscoped historical evaluation shared by two studies must not be guessed.
    for run in runs:
        data=json.loads(run.metrics_json);data.pop('study_id');run.metrics_json=json.dumps(data)
    db.commit()
    assert all(latest_study_evaluation(db,s) is None for s in studies)


def test_m6l_operational_reports_include_integrity_failures():
    db,now,cfg,studies=fixture()
    reports=study_statuses(db,settings=cfg,now=now,include_meme=True)
    assert len(reports)==2 and all(r['operational_state']=='ready' for r in reports)
    ForwardResearchService.record_incident(db,study_id=studies[1].id,external_key='integrity',
        severity='critical',code='TEST',message='test',opened_at=now,data_integrity=True)
    reports=study_statuses(db,settings=cfg,now=now,include_meme=True)
    assert 'DATA_INTEGRITY_CONTAMINATED' in reports[1]['hard_reasons']


def test_all_exits_are_checked_before_any_entry_scan():
    db,now,_,studies=fixture()
    runner=OperationalSolanaMemeMomentumForwardRunner(forensics=None,jupiter=None,health=HealthRegistry())
    events=[]
    async def cycle(db,study,**kw):
        assert kw['allow_entries'] is False
        events.append(('exit',study.id))
        return SimpleNamespace(action='cycle')
    async def enter(db,study,config,**kw):
        events.append(('entry',study.id));return (0,0)
    runner.run_study_once=cycle;runner._attempt_new_entries=enter
    asyncio.run(runner.run_active_studies(db,now=now))
    assert events==[('exit',s.id) for s in studies]+[('entry',s.id) for s in studies]


def test_historical_v1_cannot_open_new_positions():
    db,now,_,studies=fixture();study=studies[1]
    raw=json.loads(study.study_config_json);raw.pop('implementation_revision')
    study.study_config_json=json.dumps(raw)
    runner=OperationalSolanaMemeMomentumForwardRunner(forensics=None,jupiter=None,health=HealthRegistry())
    assert asyncio.run(runner._attempt_new_entries(db,study,SolanaForwardConfig.from_study(study),now=now))==(0,0)


def test_adverse_executable_exit_is_recorded_instead_of_rejected():
    db,now,_,studies=fixture();study=studies[1]
    runner=OperationalSolanaMemeMomentumForwardRunner(forensics=None,jupiter=None,health=HealthRegistry())
    position=SimpleNamespace(mint='mint',token_amount_atomic=100,launch_signature='sig',
        hold_until=now+timedelta(minutes=30),entry_in_usd=D('25'))
    runner._open_positions=lambda db,sid:[position]
    from app.venues.solana import USDC_MINT
    q=SimpleNamespace(transaction_present=False,input_mint='mint',output_mint=USDC_MINT,
        in_amount=100,out_amount=6000000,in_usd_value=D('10'),out_usd_value=D('6'),
        price_impact_pct=D('.4'),captured_at=now)
    runner._quote=AsyncMock(return_value=q);runner._sleep_delay=AsyncMock()
    recorded=[]
    def record(db,study,position,config,**kw):
        recorded.append((config,kw));return None
    runner._record_exit_execution=record
    runner._trade_from_exit_metadata=lambda *a:None
    result=asyncio.run(runner._exit_due_positions(db,study,SolanaForwardConfig.from_study(study),now=now))
    assert result==(1,0)
    assert recorded[0][1]['reason']=='M6L_HARD_STOP'
    assert recorded[0][1]['shadow'].out_usd_value==D('6')
    # Never fabricate recovery at the nominal 25% stop.
    assert recorded[0][0].max_quote_price_impact_pct==D('1')


def test_missing_exit_route_is_zero_recovery_only_after_deadline():
    db,now,_,studies=fixture();study=studies[1]
    runner=OperationalSolanaMemeMomentumForwardRunner(forensics=None,jupiter=None,health=HealthRegistry())
    position=SimpleNamespace(mint='mint',token_amount_atomic=100,launch_signature='sig',
        hold_until=now-timedelta(minutes=11),entry_in_usd=D('25'))
    runner._open_positions=lambda db,sid:[position]
    runner._quote=AsyncMock(side_effect=AssertionError('deadline must not obtain new quotes'))
    calls=[]
    runner._record_exit_execution=lambda *a,**kw:calls.append(kw)
    runner._trade_from_exit_metadata=lambda *a:None
    assert asyncio.run(runner._exit_due_positions(db,study,SolanaForwardConfig.from_study(study),now=now))==(1,0)
    assert calls[0]['status']=='forced_loss' and calls[0]['shadow'] is None


def test_atomic_token_prices_persist_and_legacy_quotes_remain_evaluable():
    from app.forward_research import _evaluation_price
    db,now,_,studies=fixture()
    row=ForwardResearchService.record_execution(db,study_id=studies[1].id,external_key='tiny',
        observed_at=now,side='buy',intended_quantity=D('25'),paper_filled_quantity=D('25'),
        shadow_filled_quantity=D('25'),paper_average_price=D('2.5e-15'),shadow_average_price=D('2.4e-15'),
        metadata={'phase':'entry','paper_quote':{'in_usd_value':'25','out_amount':10**16},
                  'shadow_quote':{'in_usd_value':'24','out_amount':10**16}})
    assert row.paper_average_price > 0
    # Simulate an already persisted pre-migration row; evaluation must not rewrite it.
    row.paper_average_price=D('0');row.shadow_average_price=D('0');db.commit()
    assert _evaluation_price(row,'paper')==D('2.5e-15')
    assert _evaluation_price(row,'shadow')==D('2.4e-15')
    ForwardResearchService.evaluate_study(db,study_id=studies[1].id,evaluated_at=now+timedelta(minutes=1))
    db.refresh(row);assert row.paper_average_price==0


def test_unexplained_zero_execution_price_still_fails_closed():
    import pytest
    from app.forward_research import _evaluation_price, ForwardResearchError
    row=SimpleNamespace(paper_average_price=D('0'),paper_filled_quantity=1,side='buy',metadata_json='{}')
    with pytest.raises(ForwardResearchError,match='immutable quote'):
        _evaluation_price(row,'paper')
