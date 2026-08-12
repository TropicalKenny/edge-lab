from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.hyperliquid_research import HyperliquidResearchService, public_opportunity_dict
from app.polymarket_research import PolymarketResearchService, public_scan_dict
from app.schemas import PaperExecutionResult, PaperOrderRequest, RiskEvaluationRequest, RiskEvaluationResult
from app.services import DisabledSigner, HealthRegistry, PaperBroker, RiskService
from app.venues.hyperliquid import HyperliquidInfoClient
from app.venues.polymarket import PolymarketPublicClient, StructuralArbitrageAnalyzer

app = FastAPI(
    title="Edge Lab",
    version="0.3.0",
    description="Quant research core. Live signing and venue order submission are disabled.",
)
settings = get_settings()
risk = RiskService(settings)
health = HealthRegistry()
signer = DisabledSigner()


@app.get("/health")
def get_health():
    return health.snapshot()


@app.post("/risk/evaluate", response_model=RiskEvaluationResult)
def evaluate(req: RiskEvaluationRequest):
    return risk.evaluate(req.proposal, req.portfolio, health.dependency_health())


@app.post("/paper/simulate", response_model=PaperExecutionResult)
def paper(req: PaperOrderRequest):
    return PaperBroker.simulate(req)


@app.get("/signer/status")
def signer_status():
    return signer.status()


@app.get("/venues/hyperliquid/status")
def hyperliquid_status():
    component = health.snapshot()["components"].get("hyperliquid")
    return {
        "network": settings.hyperliquid_network,
        "mode": "public-data-research-only",
        "can_submit_orders": False,
        "can_sign": False,
        "health": component,
    }


@app.post("/venues/hyperliquid/refresh")
async def hyperliquid_refresh(db: Session = Depends(get_db)):
    try:
        async with HyperliquidInfoClient(
            network=settings.hyperliquid_network,
            timeout_seconds=settings.hyperliquid_timeout_seconds,
        ) as client:
            service = HyperliquidResearchService(client=client, health=health)
            perps, spots = await service.market_state(db, persist=True)
        return {"perps": len(perps), "spots": len(spots), "persisted": True}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/hyperliquid/opportunities")
async def hyperliquid_opportunities(
    horizon_hours: int = Query(24, ge=1, le=24 * 30),
    min_edge_bps: Decimal = Query(Decimal("0"), ge=0),
    db: Session = Depends(get_db),
):
    try:
        async with HyperliquidInfoClient(
            network=settings.hyperliquid_network,
            timeout_seconds=settings.hyperliquid_timeout_seconds,
        ) as client:
            service = HyperliquidResearchService(client=client, health=health)
            opportunities = await service.opportunities(
                db,
                horizon_hours=horizon_hours,
                min_expected_edge_bps=min_edge_bps,
                persist_snapshot=True,
            )
        return [public_opportunity_dict(o) for o in opportunities]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/hyperliquid/funding/{coin}")
async def hyperliquid_funding(
    coin: str,
    hours: int = Query(168, ge=1, le=24 * 90),
    db: Session = Depends(get_db),
):
    try:
        async with HyperliquidInfoClient(
            network=settings.hyperliquid_network,
            timeout_seconds=settings.hyperliquid_timeout_seconds,
        ) as client:
            service = HyperliquidResearchService(client=client, health=health)
            points = await service.funding_history(db, coin=coin, hours=hours, persist=True)
        return [
            {
                "coin": p.coin,
                "funding_rate": p.funding_rate,
                "premium": p.premium,
                "time": p.time,
            }
            for p in points
        ]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/hyperliquid/paper-book/{coin}", response_model=PaperExecutionResult)
async def hyperliquid_paper_book(
    coin: str,
    side: str = Query(..., pattern="^(buy|sell)$"),
    quantity: Decimal = Query(..., gt=0),
    fee_bps: Decimal = Query(Decimal("4.5"), ge=0),
    allow_partial: bool = True,
):
    try:
        async with HyperliquidInfoClient(
            network=settings.hyperliquid_network,
            timeout_seconds=settings.hyperliquid_timeout_seconds,
        ) as client:
            service = HyperliquidResearchService(client=client, health=health)
            return await service.paper_book(
                coin=coin.upper(),
                side=side,
                quantity=quantity,
                fee_bps=fee_bps,
                allow_partial=allow_partial,
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/polymarket/status")
def polymarket_status():
    component = health.snapshot()["components"].get("polymarket")
    return {
        "protocol": "CLOB-V2-public-data",
        "mode": "structural-research-only",
        "can_submit_orders": False,
        "can_sign": False,
        "health": component,
    }


def _polymarket_analyzer(
    *,
    min_edge_bps: Decimal | None = None,
    max_shares: Decimal | None = None,
) -> StructuralArbitrageAnalyzer:
    return StructuralArbitrageAnalyzer(
        min_edge_bps=min_edge_bps if min_edge_bps is not None else Decimal(str(settings.polymarket_min_edge_bps)),
        max_shares=max_shares if max_shares is not None else Decimal(str(settings.polymarket_max_shares_per_opportunity)),
        max_book_age_seconds=settings.polymarket_max_book_age_seconds,
    )


@app.post("/venues/polymarket/scan")
async def polymarket_scan(
    max_markets: int = Query(default=None, ge=1, le=500),
    max_negrisk_events: int = Query(default=None, ge=0, le=50),
    max_shares: Decimal | None = Query(default=None, gt=0),
    min_edge_bps: Decimal | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
):
    try:
        async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
            service = PolymarketResearchService(
                client=client,
                health=health,
                analyzer=_polymarket_analyzer(min_edge_bps=min_edge_bps, max_shares=max_shares),
            )
            result = await service.scan(
                db,
                max_markets=max_markets or settings.polymarket_max_markets,
                max_negrisk_events=(
                    settings.polymarket_max_negrisk_events
                    if max_negrisk_events is None
                    else max_negrisk_events
                ),
                persist=True,
            )
        return public_scan_dict(result)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/polymarket/geoblock")
async def polymarket_geoblock():
    try:
        async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
            result = await client.geoblock()
        return {
            **result,
            "scope": "server-ip-observation-only",
            "trading_enabled": False,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/venues/polymarket/clob-market/{condition_id}")
async def polymarket_clob_market(condition_id: str):
    try:
        async with PolymarketPublicClient(timeout_seconds=settings.polymarket_timeout_seconds) as client:
            return await client.get_clob_market_info(condition_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
