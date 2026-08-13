from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dashboard_api import router as dashboard_router
from app.database import get_db

app = FastAPI(
    title="Edge Lab Dashboard",
    version="0.7.1",
    description="Read-only hosted research dashboard. Internal research APIs are not mounted here.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
settings = get_settings()
app.include_router(dashboard_router)


@app.middleware("http")
async def dashboard_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
def dashboard_root():
    return RedirectResponse(url="/dashboard", status_code=307)


@app.get("/healthz", include_in_schema=False)
def dashboard_health(db: Session = Depends(get_db)):
    if settings.signer_enabled:
        raise HTTPException(status_code=503, detail="unsafe signer configuration")
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dashboard database unavailable") from exc
    return {
        "status": "ok",
        "mode": "dashboard-read-only",
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
        "vault_accessible": False,
        "signer_enabled": False,
        "live_capital_usd": 0,
    }
