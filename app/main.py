from contextlib import AsyncExitStack
from dataclasses import asdict
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.hyperliquid_research import HyperliquidResearchService, public_opportunity_dict
from app.polymarket_research import PolymarketResearchService, public_scan_dict
from app.schemas import PaperExecutionResult, PaperOrderRequest, RiskEvaluationRequest, RiskEvaluationResult
from app.services import DisabledSigner, HealthRegistry, PaperBroker, RiskService
from app.solana_research import ForwardLabelService, SolanaForensicService
from app.venues.hyperliquid import HyperliquidInfoClient
from app.venues.polymarket import PolymarketPublicClient, StructuralArbitrageAnalyzer
from app.venues.solana import DexScreenerClient, GoPlusSolanaClient, JupiterShadowClient
from app.venues.solana_asset import HeliusAssetClient
from app.venues.solana_models import SolanaLaunchEvent
from app.version import APP_VERSION

app = FastAPI(
    title="Edge Lab",
    version=APP_VERSION,
    description="Quant research core. Live signing and venue order submission are disabled.",
)
settings = get_settings()
risk = RiskService(settings)
health = HealthRegistry()
signer = DisabledSigner()


@app.get("/health")
def get_health(): return health.snapshot()


@app.post("/risk/evaluate", response_model=RiskEvaluationResult)
def evaluate(req: RiskEvaluationRequest): return risk.evaluate(req.proposal, req.portfolio, health.dependency_health())


@app.post("/paper/simulate", response_model=PaperExecutionResult)
def paper(req: PaperOrderRequest): return PaperBroker.simulate(req)


@app.get("/signer/status")
def signer_status(): return signer.status()


@app.get("/venues/hyperliquid/status")
def hyperliquid_status():
    return {"network": settings.hyperliquid_network, "mode": "public-data-research-only", "can_submit_orders": False, "can_sign": False, "health": health.snapshot()["components"].get("hyperliquid")}


@app.post("/venues/hyperliquid/refresh")
async def hyperliquid_refresh(db: Session = Depends(get_db)):
    try:
        async with HyperliquidInfoClient(network=settings.hyperliquid_network, timeout_seconds=settings.hyperliquid_timeout_seconds) as client:
            perps, spots = await HyperliquidResearchService(client=client, health=health).market_state(db, persist=True)
        return {"perps": len(perps), "spots": len(spots), "persisted": True}
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/hyperliquid/opportunities")
async def hyperliquid_opportunities(horizon_hours: int = Query(24, ge=1, le=24*30), min_edge_bps: Decimal = Query(Decimal("0"), ge=0), db: Session = Depends(get_db)):
    try:
        async with HyperliquidInfoClient(network=settings.hyperliquid_network, timeout_seconds=settings.hyperliquid_timeout_seconds) as client:
            opportunities = await HyperliquidResearchService(client=client, health=health).opportunities(db, horizon_hours=horizon_hours, min_expected_edge_bps=min_edge_bps, persist_snapshot=True)
        return [public_opportunity_dict(o) for o in opportunities]
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/hyperliquid/funding/{coin}")
async def hyperliquid_funding(coin: str, hours: int = Query(168, ge=1, le=24*90), db: Session = Depends(get_db)):
    try:
        async with HyperliquidInfoClient(network=settings.hyperliquid_network, timeout_seconds=settings.hyperliquid_timeout_seconds) as client:
            points = await HyperliquidResearchService(client=client, health=health).funding_history(db, coin=coin, hours=hours, persist=True)
        return [{"coin": p.coin, "funding_rate": p.funding_rate, "premium": p.premium, "time": p.time} for p in points]
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/hyperliquid/paper-book/{coin}", response_model=PaperExecutionResult)
async def hyperliquid_paper_book(coin: str, side: str = Query(..., pattern="^(buy|sell)$"), quantity: Decimal = Query(..., gt=0), fee_bps: Decimal = Query(Decimal("4.5"), ge=0), allow_partial: bool = True):
    try:
        async with HyperliquidInfoClient(network=settings.hyperliquid_network, timeout_seconds=settings.hyperliquid_timeout_seconds) as client:
            return await HyperliquidResearchService(client=client, health=health).paper_book(coin=coin.upper(), side=side, quantity=quantity, fee_bps=fee_bps, allow_partial=allow_partial)
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/polymarket/status")
def polymarket_status():
    return {"protocol": "CLOB-V2-public-data", "mode": "structural-research-only", "can_submit_orders": False, "can_sign": False, "health": health.snapshot()["components"].get("polymarket")}


def _polymarket_analyzer(*, min_edge_bps: Decimal | None=None, max_shares: Decimal | None=None) -> StructuralArbitrageAnalyzer:
    return StructuralArbitrageAnalyzer(min_edge_bps=min_edge_bps if min_edge_bps is not None else Decimal(str(settings.polymarket_min_edge_bps)), max_shares=max_shares if max_shares is not None else Decimal(str(settings.polymarket_max_shares_per_opportunity)), max_book_age_seconds=settings.polymarket_max_book_age_seconds)


@app.post("/venues/polymarket/scan")
async def polymarket_scan(max_markets: int | None=Query(default=None, ge=1, le=500), max_negrisk_events: int | None=Query(default=None, ge=0, le=50), max_shares: Decimal | None=Query(default=None, gt=0), min_edge_bps: Decimal | None=Query(default=None, ge=0), db: Session=Depends(get_db)):
    try:
        async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
            service = PolymarketResearchService(client=client, health=health, analyzer=_polymarket_analyzer(min_edge_bps=min_edge_bps, max_shares=max_shares))
            result = await service.scan(db, max_markets=max_markets or settings.polymarket_max_markets, max_negrisk_events=settings.polymarket_max_negrisk_events if max_negrisk_events is None else max_negrisk_events, persist=True)
        return public_scan_dict(result)
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/polymarket/geoblock")
async def polymarket_geoblock():
    try:
        async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client: result = await client.geoblock()
        return {**result, "scope": "server-ip-observation-only", "trading_enabled": False}
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/polymarket/clob-market/{condition_id}")
async def polymarket_clob_market(condition_id: str):
    try:
        async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client: return await client.get_clob_market_info(condition_id)
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/solana/status")
def solana_status():
    return {
        "mode": "onchain-forensic-and-shadow-research-only",
        "home_treasury_asset": "Solana USDC",
        "launch_stream": "Helius transactionSubscribe",
        "launch_stream_configured": bool(settings.helius_api_key),
        "jupiter_shadow_configured": bool(settings.jupiter_api_key),
        "goplus_enrichment_configured": bool(settings.goplus_access_token),
        "can_submit_swaps": False,
        "can_sign": False,
        "health": health.snapshot()["components"].get("solana_forensics"),
    }


@app.get("/venues/solana/recent-launches")
def solana_recent_launches(limit: int=Query(20, ge=1, le=100), db: Session=Depends(get_db)):
    rows = db.scalars(select(SolanaLaunchEvent).order_by(SolanaLaunchEvent.observed_at.desc()).limit(limit)).all()
    return [{"signature": r.signature, "slot": r.slot, "creator": r.creator, "mint": r.mint, "program_id": r.program_id, "observed_at": r.observed_at} for r in rows]


@app.post("/venues/solana/analyze/{mint}")
async def solana_analyze(mint: str, exit_test_notional_usd: Decimal=Query(Decimal("25"), gt=0, le=1000), db: Session=Depends(get_db)):
    try:
        async with AsyncExitStack() as stack:
            dex = await stack.enter_async_context(DexScreenerClient(timeout_seconds=settings.dexscreener_timeout_seconds))
            goplus = await stack.enter_async_context(GoPlusSolanaClient(access_token=settings.goplus_access_token, timeout_seconds=settings.goplus_timeout_seconds))
            helius = await stack.enter_async_context(HeliusAssetClient(api_key=settings.helius_api_key, timeout_seconds=10)) if settings.helius_api_key else None
            jupiter = await stack.enter_async_context(JupiterShadowClient(api_key=settings.jupiter_api_key, timeout_seconds=settings.jupiter_timeout_seconds)) if settings.jupiter_api_key else None
            feature = await SolanaForensicService(dexscreener=dex, goplus=goplus, helius_assets=helius, jupiter=jupiter, health=health, quote_mint=settings.solana_quote_mint).analyze_mint(db, mint=mint, exit_test_notional_usd=exit_test_notional_usd)
        return {column.name: getattr(feature, column.name) for column in feature.__table__.columns}
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/solana/jupiter-shadow")
async def solana_jupiter_shadow(input_mint: str, output_mint: str, amount: int=Query(..., gt=0)):
    if not settings.jupiter_api_key: raise HTTPException(status_code=503, detail="JUPITER_API_KEY is not configured")
    try:
        async with JupiterShadowClient(api_key=settings.jupiter_api_key, timeout_seconds=settings.jupiter_timeout_seconds) as client:
            quote = await client.order_quote(input_mint=input_mint, output_mint=output_mint, amount=amount)
        return {**asdict(quote), "can_execute": False, "taker_supplied": False}
    except Exception as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/venues/solana/labels/{mint}/resolve")
def solana_resolve_labels(mint: str, db: Session=Depends(get_db)):
    return {"mint": mint, "labels_created": ForwardLabelService.resolve(db, mint=mint)}


# Compose milestone routers last so the core app remains importable in isolation.
from app.dashboard_api import router as dashboard_router
from app.evaluation_api import router as evaluation_router
from app.forward_api import router as forward_router
from app.forward_ops_api import router as forward_ops_router
from app.portfolio_api import router as portfolio_router

app.include_router(dashboard_router)
app.include_router(evaluation_router)
app.include_router(forward_router)
app.include_router(forward_ops_router)
app.include_router(portfolio_router)
