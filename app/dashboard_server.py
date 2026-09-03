from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dashboard_api import router as dashboard_router
from app.dashboard_auth import DashboardAuth
from app.database import get_db
from app.version import APP_VERSION

app = FastAPI(
    title="Edge Lab Dashboard",
    version=APP_VERSION,
    description="Read-only hosted research dashboard. Internal trading/research APIs are not mounted.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
settings = get_settings()
auth = DashboardAuth(settings)
app.include_router(dashboard_router)

STATIC_DIR = Path(__file__).resolve().parent / "static" / "dashboard"
PUBLIC_PATHS = {"/healthz", "/login", "/auth/request-otp", "/auth/verify-otp"}
AUTH_ASSETS = {
    "login.css": ("text/css", STATIC_DIR / "login.css"),
    "login.js": ("application/javascript", STATIC_DIR / "login.js"),
}


class VerifyOtpRequest(BaseModel):
    challenge_id: str = Field(min_length=16, max_length=160)
    code: str = Field(pattern=r"^\d{6}$")


@app.middleware("http")
async def dashboard_security_and_auth(request: Request, call_next):
    path = request.url.path
    public = path in PUBLIC_PATHS or path.startswith("/auth/assets/")
    if not public and not auth.session_valid(request.cookies.get(auth.cookie_name)):
        if path in {"/", "/dashboard"}:
            response = RedirectResponse("/login", status_code=303)
        else:
            response = JSONResponse({"detail": "authentication required"}, status_code=401)
    else:
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
def root():
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    if auth.session_valid(request.cookies.get(auth.cookie_name)):
        return RedirectResponse("/dashboard", status_code=303)
    return FileResponse(STATIC_DIR / "login.html", media_type="text/html")


@app.get("/auth/assets/{asset}", include_in_schema=False)
def auth_asset(asset: str):
    found = AUTH_ASSETS.get(asset)
    if found is None:
        raise HTTPException(status_code=404, detail="auth asset not found")
    media_type, path = found
    return FileResponse(path, media_type=media_type)


@app.post("/auth/request-otp", include_in_schema=False)
def request_otp():
    challenge_id = auth.issue_otp()
    return {
        "challenge_id": challenge_id,
        "expires_in_seconds": settings.dashboard_otp_ttl_seconds,
    }


@app.post("/auth/verify-otp", include_in_schema=False)
def verify_otp(payload: VerifyOtpRequest):
    token = auth.verify_otp(payload.challenge_id, payload.code)
    response = JSONResponse({"authenticated": True})
    auth.set_session_cookie(response, token)
    return response


@app.post("/auth/logout", include_in_schema=False)
def logout():
    response = JSONResponse({"authenticated": False})
    auth.clear_session_cookie(response)
    return response


@app.get("/healthz", include_in_schema=False)
def healthz(db: Session = Depends(get_db)):
    if settings.signer_enabled:
        raise HTTPException(status_code=503, detail="unsafe signer configuration")
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dashboard database unavailable") from exc
    return {
        "status": "ok",
        "surface": "dashboard-only",
        "mode": "dashboard-read-only",
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
        "vault_accessible": False,
        "signer_enabled": False,
        "live_capital_usd": 0,
    }
