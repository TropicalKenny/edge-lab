from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.control_models import OwnerCommand
from app.control_service import OwnerControlError, OwnerControlService
from app.dashboard_api import dashboard_summary
from app.database import get_db
from app.version import APP_VERSION


class OwnerCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=160)
    reason: str = Field(default="owner API command", max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=180)


app = FastAPI(
    title="Edge Lab Owner Control",
    version=APP_VERSION,
    description="Private typed research-control service. No signer, shell or live-capital capability.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
settings = get_settings()


def _require_owner_token(request: Request) -> None:
    expected = settings.owner_control_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="owner control token is not configured")
    auth = request.headers.get("authorization", "")
    scheme, _, supplied = auth.partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/healthz", include_in_schema=False)
def healthz():
    if settings.signer_enabled:
        raise HTTPException(status_code=503, detail="unsafe signer configuration")
    return {
        "status": "ok",
        "surface": "owner-control-private",
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
        "shell_access": False,
    }


@app.get("/v1/summary", dependencies=[Depends(_require_owner_token)])
def summary(db: Session = Depends(get_db)):
    return dashboard_summary(db)


@app.get("/v1/commands", dependencies=[Depends(_require_owner_token)])
def recent_commands(limit: int = 20, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    rows = list(
        db.scalars(select(OwnerCommand).order_by(OwnerCommand.requested_at.desc()).limit(limit)).all()
    )
    return [
        {
            "id": row.id,
            "command": row.command,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "reason": row.reason,
            "status": row.status,
            "requested_at": row.requested_at,
            "completed_at": row.completed_at,
        }
        for row in rows
    ]


@app.post("/v1/commands", dependencies=[Depends(_require_owner_token)])
def command(req: OwnerCommandRequest, db: Session = Depends(get_db)):
    try:
        result = OwnerControlService.execute(
            db,
            command=req.command,
            actor_type="owner_api",
            actor_id="private-loopback-api",
            idempotency_key=req.idempotency_key,
            target=req.target,
            reason=req.reason,
        )
    except OwnerControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.public_dict()
