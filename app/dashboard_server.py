from fastapi import FastAPI

from app.dashboard_api import router as dashboard_router


app = FastAPI(
    title="Edge Lab Dashboard",
    version="0.7.1",
    description=(
        "Read-only hosted research dashboard. Trading and internal research APIs "
        "are intentionally not mounted."
    ),
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(dashboard_router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {
        "status": "ok",
        "surface": "dashboard-only",
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
    }
