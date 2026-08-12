from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import app
from app.models import Account,Base
from app.schemas import BookLevel,DependencyHealth,Exposure,PaperOrderRequest,PortfolioState,TradeProposal
from app.services import DisabledSigner,DisabledSignerError,EntryInput,ExperimentInvariantError,ExperimentService,LedgerInvariantError,LedgerService,PaperBroker,RiskService
NOW=datetime(2026,8,12,20,0,tzinfo=timezone.utc)
def db():
    e=create_engine('sqlite:///:memory:'); Base.metadata.create_all(e); return Session(e)
def prop(**kw):
    d=dict(strategy='funding-v1',instrument='BTC-PERP',side='short',correlation_bucket='funding/carry',requested_notional=Decimal('250'),planned_loss=Decimal('3'),expected_edge_pct=Decimal('0.02'),market_data_at=NOW,exceptional=False); d.update(kw); return TradeProposal(**d)
def port(**kw): d=dict(nav=Decimal('1500')); d.update(kw); return PortfolioState(**d)
def risk(): return RiskService(Settings(_env_file=None))
def test_ledger_balances_and_rejects_unbalanced():
    s=db(); a=Account(name='treasury',kind='asset',currency='USDC'); q=Account(name='owner',kind='equity',currency='USDC'); s.add_all([a,q]); s.commit(); LedgerService.post(s,reference='d1',description='deposit',entries=[EntryInput(a.id,Decimal('1500')),EntryInput(q.id,Decimal('-1500'))]); assert LedgerService.asset_nav(s)==Decimal('1500')
    with pytest.raises(LedgerInvariantError): LedgerService.post(s,reference='bad',description='bad',entries=[EntryInput(a.id,Decimal('10')),EntryInput(q.id,Decimal('-9'))])
def test_risk_good_and_fail_closed():
    assert risk().evaluate(prop(),port(),DependencyHealth(),now=NOW).approved
    assert not risk().evaluate(prop(),port(),DependencyHealth(accounting=False),now=NOW).approved
    assert 'STALE_MARKET_DATA' in risk().evaluate(prop(market_data_at=NOW-timedelta(seconds=30)),port(),DependencyHealth(),now=NOW).reasons
def test_risk_limits_drawdown_correlation_and_edge():
    assert 'TRADE_RISK_LIMIT' in risk().evaluate(prop(planned_loss=Decimal('8')),port(),DependencyHealth(),now=NOW).reasons
    r=risk().evaluate(prop(),port(peak_to_current_drawdown_pct=Decimal('0.10')),DependencyHealth(),now=NOW); assert r.approved and r.approved_notional==Decimal('125.0')
    assert 'PORTFOLIO_FREEZE_DRAWDOWN' in risk().evaluate(prop(),port(peak_to_current_drawdown_pct=Decimal('0.15')),DependencyHealth(),now=NOW).reasons
    assert 'CORRELATION_BUCKET_LIMIT' in risk().evaluate(prop(),port(existing_exposures=[Exposure(bucket='funding/carry',planned_loss=Decimal('13'))]),DependencyHealth(),now=NOW).reasons
    assert 'NON_POSITIVE_EXPECTED_EDGE' in risk().evaluate(prop(expected_edge_pct=0),port(),DependencyHealth(),now=NOW).reasons
def test_paper_depth_fees_partial_and_stale():
    r=PaperBroker.simulate(PaperOrderRequest(venue='x',instrument='BTC',side='buy',quantity=Decimal('3'),asks=[BookLevel(price=101,quantity=2),BookLevel(price=100,quantity=2)],bids=[],fee_bps=10,fixed_network_fee=Decimal('0.1'),market_data_at=NOW),now=NOW); assert r.status=='filled' and r.gross_notional==Decimal('301') and r.total_fees==Decimal('0.3010000000')
    p=PaperBroker.simulate(PaperOrderRequest(venue='x',instrument='X',side='buy',quantity=5,asks=[BookLevel(price=10,quantity=2)],bids=[],market_data_at=NOW),now=NOW); assert p.status=='partially_filled'
    f=PaperBroker.simulate(PaperOrderRequest(venue='x',instrument='X',side='buy',quantity=5,asks=[BookLevel(price=10,quantity=2)],bids=[],allow_partial=False,market_data_at=NOW),now=NOW); assert f.status=='rejected'
    st=PaperBroker.simulate(PaperOrderRequest(venue='x',instrument='X',side='sell',quantity=1,bids=[BookLevel(price=10,quantity=2)],asks=[],market_data_at=NOW-timedelta(seconds=20)),now=NOW); assert 'STALE_OR_INVALID_MARKET_DATA' in st.reasons
def test_experiments_are_versioned():
    s=db(); st=ExperimentService.create_strategy(s,'funding','Funding'); ExperimentService.create_version(s,strategy_id=st.id,version='1.0.0',config={})
    with pytest.raises(ExperimentInvariantError): ExperimentService.create_version(s,strategy_id=st.id,version='1.0.0',config={})
def test_signer_disabled():
    s=DisabledSigner(); assert s.status()['can_sign'] is False
    with pytest.raises(DisabledSignerError): s.sign(b'x')
def test_api_health_signer_and_risk():
    c=TestClient(app); assert c.get('/health').json()['healthy']; assert c.get('/signer/status').json()['can_sign'] is False
    now=datetime.now(timezone.utc).isoformat(); payload={'proposal':{'strategy':'funding','instrument':'BTC','side':'short','correlation_bucket':'funding/carry','requested_notional':'100','planned_loss':'2','expected_edge_pct':'0.02','market_data_at':now},'portfolio':{'nav':'1500'},'health':{}}; assert c.post('/risk/evaluate',json=payload).json()['approved']
