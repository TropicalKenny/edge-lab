from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.config import Settings
from app.models import Account, Experiment, LedgerEntry, LedgerTransaction, Strategy, StrategyVersion
from app.schemas import DependencyHealth, PaperExecutionResult, PaperFill, PaperOrderRequest, PortfolioState, RiskEvaluationResult, TradeProposal
ZERO=Decimal('0'); ONE=Decimal('1'); BPS=Decimal('10000')
class LedgerInvariantError(ValueError): pass
@dataclass(frozen=True)
class EntryInput: account_id:str; amount:Decimal; memo:str|None=None
class LedgerService:
    @staticmethod
    def post(db:Session,*,reference:str,description:str,entries:list[EntryInput]):
        if len(entries)<2: raise LedgerInvariantError('a ledger transaction requires at least two entries')
        total=sum((e.amount for e in entries),ZERO)
        if total!=0: raise LedgerInvariantError(f'ledger entries must balance to zero; got {total}')
        if any(e.amount==0 for e in entries): raise LedgerInvariantError('zero-value ledger entries are forbidden')
        ids={e.account_id for e in entries}; found=set(db.scalars(select(Account.id).where(Account.id.in_(ids))).all())
        if ids-found: raise LedgerInvariantError(f'unknown account(s): {sorted(ids-found)}')
        tx=LedgerTransaction(reference=reference,description=description); tx.entries=[LedgerEntry(account_id=e.account_id,amount=e.amount,memo=e.memo) for e in entries]; db.add(tx); db.commit(); db.refresh(tx); return tx
    @staticmethod
    def balance(db:Session,account_id:str):
        v=db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount),0)).where(LedgerEntry.account_id==account_id)); return Decimal(str(v or 0))
    @staticmethod
    def asset_nav(db:Session,currency='USDC'):
        v=db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount),0)).join(Account,Account.id==LedgerEntry.account_id).where(Account.kind=='asset',Account.currency==currency)); return Decimal(str(v or 0))
class RiskService:
    def __init__(self,settings:Settings): self.s=settings
    def evaluate(self,p:TradeProposal,portfolio:PortfolioState,h:DependencyHealth,*,now=None):
        reasons=[]; now=now or datetime.now(timezone.utc); ts=p.market_data_at if p.market_data_at.tzinfo else p.market_data_at.replace(tzinfo=timezone.utc)
        if not h.healthy: reasons.append('DEPENDENCY_DEGRADED')
        age=(now-ts).total_seconds()
        if age < -1: reasons.append('MARKET_DATA_FROM_FUTURE')
        if age>self.s.risk_max_market_data_age_seconds: reasons.append('STALE_MARKET_DATA')
        risk=p.planned_loss/portfolio.nav; limit=Decimal(str(self.s.risk_max_exceptional_loss_pct if p.exceptional else self.s.risk_max_normal_loss_pct))
        if risk>limit: reasons.append('TRADE_RISK_LIMIT')
        if portfolio.daily_realised_loss>=portfolio.nav*Decimal(str(self.s.risk_daily_stop_pct)): reasons.append('DAILY_LOSS_STOP')
        if portfolio.weekly_drawdown_pct>=Decimal(str(self.s.risk_weekly_stop_pct)): reasons.append('WEEKLY_DRAWDOWN_STOP')
        if portfolio.monthly_drawdown_pct>=Decimal(str(self.s.risk_monthly_stop_pct)): reasons.append('MONTHLY_DRAWDOWN_STOP')
        if portfolio.peak_to_current_drawdown_pct>=Decimal(str(self.s.risk_freeze_at_drawdown_pct)): reasons.append('PORTFOLIO_FREEZE_DRAWDOWN')
        correlated=sum((e.planned_loss for e in portfolio.existing_exposures if e.bucket==p.correlation_bucket),ZERO)
        if (correlated+p.planned_loss)/portfolio.nav>Decimal('0.01'): reasons.append('CORRELATION_BUCKET_LIMIT')
        mult=Decimal('0.5') if portfolio.peak_to_current_drawdown_pct>=Decimal(str(self.s.risk_halve_at_drawdown_pct)) else ONE
        if p.expected_edge_pct<=0: reasons.append('NON_POSITIVE_EXPECTED_EDGE')
        ok=not reasons
        return RiskEvaluationResult(approved=ok,requested_notional=p.requested_notional,approved_notional=p.requested_notional*mult if ok else ZERO,portfolio_risk_pct=risk,risk_multiplier=mult,reasons=reasons)
class PaperBroker:
    @staticmethod
    def simulate(r:PaperOrderRequest,*,now=None):
        now=now or datetime.now(timezone.utc); ts=r.market_data_at if r.market_data_at.tzinfo else r.market_data_at.replace(tzinfo=timezone.utc); age=(now-ts).total_seconds()
        if age < -1 or age>r.max_data_age_seconds: return PaperBroker.reject(r,'STALE_OR_INVALID_MARKET_DATA')
        levels=sorted(r.asks,key=lambda x:x.price) if r.side=='buy' else sorted(r.bids,key=lambda x:x.price,reverse=True); rem=r.quantity; fills=[]; gross=fees=ZERO
        for l in levels:
            if rem<=0: break
            take=min(rem,l.quantity); notion=take*l.price; fee=(notion*r.fee_bps/BPS).quantize(Decimal('0.0000000001'),rounding=ROUND_HALF_UP); fills.append(PaperFill(price=l.price,quantity=take,fee=fee)); gross+=notion; fees+=fee; rem-=take
        filled=r.quantity-rem
        if filled==0: return PaperBroker.reject(r,'NO_EXECUTABLE_LIQUIDITY')
        if rem>0 and not r.allow_partial: return PaperBroker.reject(r,'INSUFFICIENT_DEPTH_FOR_FULL_FILL')
        return PaperExecutionResult(status='filled' if rem==0 else 'partially_filled',requested_quantity=r.quantity,filled_quantity=filled,average_price=gross/filled,gross_notional=gross,total_fees=fees,network_fee=r.fixed_network_fee,fills=fills,latency_ms=r.latency_ms,reasons=[] if rem==0 else ['PARTIAL_FILL_DEPTH_LIMIT'])
    @staticmethod
    def reject(r,reason): return PaperExecutionResult(status='rejected',requested_quantity=r.quantity,filled_quantity=ZERO,average_price=None,gross_notional=ZERO,total_fees=ZERO,network_fee=ZERO,fills=[],latency_ms=r.latency_ms,reasons=[reason])
class DisabledSignerError(RuntimeError): pass
class DisabledSigner:
    enabled=False
    def sign(self,*a,**k): raise DisabledSignerError('signing is disabled in Milestone 1')
    def status(self): return {'enabled':False,'mode':'disabled','can_sign':False}
class ExperimentInvariantError(ValueError): pass
class ExperimentService:
    @staticmethod
    def create_strategy(db,slug,name): s=Strategy(slug=slug,name=name); db.add(s); db.commit(); db.refresh(s); return s
    @staticmethod
    def create_version(db,*,strategy_id,version,config,code_sha=None):
        if db.scalar(select(StrategyVersion).where(StrategyVersion.strategy_id==strategy_id,StrategyVersion.version==version)): raise ExperimentInvariantError('strategy version already exists and is immutable')
        v=StrategyVersion(strategy_id=strategy_id,version=version,config_json=json.dumps(config,sort_keys=True),code_sha=code_sha,immutable=True); db.add(v); db.commit(); db.refresh(v); return v
    @staticmethod
    def register(db,*,strategy_version_id,hypothesis,data_version,train_window,validation_window,holdout_window,search_space):
        if not hypothesis.strip(): raise ExperimentInvariantError('hypothesis is required before evaluation')
        if not holdout_window.strip(): raise ExperimentInvariantError('untouched holdout window is required')
        e=Experiment(strategy_version_id=strategy_version_id,hypothesis=hypothesis.strip(),data_version=data_version,train_window=train_window,validation_window=validation_window,holdout_window=holdout_window,search_space_json=json.dumps(search_space,sort_keys=True)); db.add(e); db.commit(); db.refresh(e); return e
@dataclass
class ComponentHealth: healthy:bool; detail:str='ok'; checked_at:datetime=field(default_factory=lambda:datetime.now(timezone.utc))
class HealthRegistry:
    def __init__(self): self.c={'api':ComponentHealth(True),'risk':ComponentHealth(True),'accounting':ComponentHealth(True),'market_data':ComponentHealth(False,'no-live-collector'),'reconciliation':ComponentHealth(False,'not-wired'),'signer':ComponentHealth(True,'disabled-by-design')}
    def set(self, component:str, healthy:bool, detail:str='ok'):
        self.c[component]=ComponentHealth(healthy,detail)
    def dependency_health(self):
        return DependencyHealth(
            risk_db=self.c.get('risk',ComponentHealth(False,'missing')).healthy,
            market_data=self.c.get('market_data',ComponentHealth(False,'missing')).healthy,
            accounting=self.c.get('accounting',ComponentHealth(False,'missing')).healthy,
            reconciliation=self.c.get('reconciliation',ComponentHealth(False,'missing')).healthy,
        )
    def snapshot(self):
        cs={k:{'healthy':v.healthy,'detail':v.detail,'checked_at':v.checked_at.isoformat()} for k,v in self.c.items()}; return {'healthy':all(v.healthy for v in self.c.values()),'components':cs}
@dataclass(frozen=True)
class ExecutableQuote: venue:str; instrument:str; side:str; requested_quantity:Decimal; executable_quantity:Decimal; average_price:Decimal; estimated_fees:Decimal; captured_at:datetime; raw_reference:str|None=None
class ShadowBroker:
    def __init__(self,provider): self.provider=provider
    def capture(self,*,instrument,side,quantity): return self.provider.quote(instrument=instrument,side=side,quantity=quantity)
