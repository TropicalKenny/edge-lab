from fastapi import FastAPI
from app.config import get_settings
from app.schemas import PaperExecutionResult, PaperOrderRequest, RiskEvaluationRequest, RiskEvaluationResult
from app.services import DisabledSigner, HealthRegistry, PaperBroker, RiskService
app=FastAPI(title='Edge Lab',version='0.1.0',description='Quant research core. Live signing and venue submission are disabled in Milestone 1.')
settings=get_settings(); risk=RiskService(settings); health=HealthRegistry(); signer=DisabledSigner()
@app.get('/health')
def get_health(): return health.snapshot()
@app.post('/risk/evaluate',response_model=RiskEvaluationResult)
def evaluate(req:RiskEvaluationRequest): return risk.evaluate(req.proposal,req.portfolio,health.dependency_health())
@app.post('/paper/simulate',response_model=PaperExecutionResult)
def paper(req:PaperOrderRequest): return PaperBroker.simulate(req)
@app.get('/signer/status')
def signer_status(): return signer.status()
