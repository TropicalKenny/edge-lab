from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, model_validator
class Exposure(BaseModel): bucket:str; planned_loss:Decimal=Field(ge=0)
class PortfolioState(BaseModel):
    nav:Decimal=Field(gt=0); daily_realised_loss:Decimal=Field(ge=0,default=0); weekly_drawdown_pct:Decimal=Field(ge=0,default=0); monthly_drawdown_pct:Decimal=Field(ge=0,default=0); peak_to_current_drawdown_pct:Decimal=Field(ge=0,default=0); existing_exposures:list[Exposure]=Field(default_factory=list)
class TradeProposal(BaseModel):
    strategy:str; instrument:str; side:Literal['buy','sell','long','short']; correlation_bucket:str; requested_notional:Decimal=Field(gt=0); planned_loss:Decimal=Field(gt=0); exceptional:bool=False; market_data_at:datetime; expected_edge_pct:Decimal=0
class DependencyHealth(BaseModel):
    risk_db:bool=True; market_data:bool=True; accounting:bool=True; reconciliation:bool=True
    @property
    def healthy(self): return self.risk_db and self.market_data and self.accounting and self.reconciliation
class RiskEvaluationRequest(BaseModel): proposal:TradeProposal; portfolio:PortfolioState; health:DependencyHealth=Field(default_factory=DependencyHealth)
class RiskEvaluationResult(BaseModel): approved:bool; requested_notional:Decimal; approved_notional:Decimal; portfolio_risk_pct:Decimal; risk_multiplier:Decimal; reasons:list[str]
class BookLevel(BaseModel): price:Decimal=Field(gt=0); quantity:Decimal=Field(gt=0)
class PaperOrderRequest(BaseModel):
    venue:str; instrument:str; side:Literal['buy','sell']; quantity:Decimal=Field(gt=0); bids:list[BookLevel]=Field(default_factory=list); asks:list[BookLevel]=Field(default_factory=list); fee_bps:Decimal=Field(ge=0,default=0); fixed_network_fee:Decimal=Field(ge=0,default=0); latency_ms:int=Field(ge=0,default=0); allow_partial:bool=True; market_data_at:datetime; max_data_age_seconds:int=Field(gt=0,default=5)
    @model_validator(mode='after')
    def book(self):
        if not (self.asks if self.side=='buy' else self.bids): raise ValueError('relevant order-book side cannot be empty')
        return self
class PaperFill(BaseModel): price:Decimal; quantity:Decimal; fee:Decimal
class PaperExecutionResult(BaseModel): status:Literal['filled','partially_filled','rejected']; requested_quantity:Decimal; filled_quantity:Decimal; average_price:Decimal|None; gross_notional:Decimal; total_fees:Decimal; network_fee:Decimal; fills:list[PaperFill]; latency_ms:int; reasons:list[str]
