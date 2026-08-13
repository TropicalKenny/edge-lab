from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import ForwardNavObservation, ForwardStudy, ForwardStudyIncident
from app.forward_operations import ForwardOperationsService
from app.polymarket_forward_ops import study_statuses as polymarket_study_statuses
from app.solana_forward_ops import study_statuses as solana_study_statuses

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
_security = HTTPBasic(auto_error=False)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _dashboard_auth(
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    settings = get_settings()
    if not settings.dashboard_username or not settings.dashboard_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dashboard credentials are not configured",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Edge Lab"'},
        )
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), settings.dashboard_username.encode("utf-8")
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), settings.dashboard_password.encode("utf-8")
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid dashboard credentials",
            headers={"WWW-Authenticate": 'Basic realm="Edge Lab"'},
        )


def _security_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )


class DashboardService:
    @staticmethod
    def _latest_evaluation(db: Session, study: ForwardStudy) -> StrategyEvaluationRun | None:
        return db.scalar(
            select(StrategyEvaluationRun)
            .where(
                StrategyEvaluationRun.strategy_version_id == study.strategy_version_id,
                StrategyEvaluationRun.forward_started_at == study.started_at,
            )
            .order_by(StrategyEvaluationRun.evaluated_at.desc())
            .limit(1)
        )

    @staticmethod
    def snapshot(
        db: Session,
        *,
        settings: Settings,
        now: datetime | None = None,
        nav_points_per_study: int = 144,
    ) -> dict[str, Any]:
        now = _aware(now or datetime.now(timezone.utc))
        sources: list[tuple[str, list[dict[str, Any]]]] = [
            (
                "hyperliquid",
                ForwardOperationsService.study_statuses(db, settings=settings, now=now),
            ),
            (
                "polymarket",
                polymarket_study_statuses(db, settings=settings, now=now),
            ),
            (
                "solana",
                solana_study_statuses(db, settings=settings, now=now),
            ),
        ]

        engines: list[dict[str, Any]] = []
        nav_series: list[dict[str, Any]] = []
        study_map: dict[str, ForwardStudy] = {}

        for venue, reports in sources:
            for report in reports:
                study = db.get(ForwardStudy, report["study_id"])
                if study is None:
                    continue
                study_map[study.id] = study
                evaluation = DashboardService._latest_evaluation(db, study)
                initial = Decimal(str(report.get("initial_capital_usd") or 0))
                latest_raw = report.get("last_nav_usd")
                latest = Decimal(str(latest_raw)) if latest_raw is not None else None
                pnl = latest - initial if latest is not None else None
                pnl_pct = (
                    (pnl / initial * Decimal("100"))
                    if pnl is not None and initial > 0
                    else None
                )
                hard_reasons = list(report.get("hard_reasons") or [])
                warnings = list(report.get("warnings") or [])
                engines.append(
                    {
                        "study_id": study.id,
                        "external_id": study.external_id,
                        "venue": venue,
                        "family": study.family,
                        "instrument": report.get("instrument") or study.instrument,
                        "study_status": report.get("status") or study.status,
                        "operational_state": report.get("operational_state", "waiting"),
                        "strategy_slug": report.get("strategy_slug"),
                        "strategy_status": report.get("strategy_status"),
                        "strategy_version": report.get("strategy_version"),
                        "started_at": _aware(study.started_at),
                        "forward_age_days": report.get("forward_age_days", 0),
                        "initial_capital_usd": initial,
                        "latest_nav_usd": latest,
                        "pnl_usd": pnl,
                        "pnl_pct": pnl_pct,
                        "open_position_count": int(report.get("open_position_count", 0) or 0),
                        "trade_count": int(report.get("trade_count", 0) or 0),
                        "execution_observation_count": int(
                            report.get("execution_observation_count", 0) or 0
                        ),
                        "incident_count": int(report.get("incident_count", 0) or 0),
                        "data_integrity_failure_count": int(
                            report.get("data_integrity_failure_count", 0) or 0
                        ),
                        "unresolved_critical_incident_count": int(
                            report.get("unresolved_critical_incident_count", 0) or 0
                        ),
                        "hard_reasons": hard_reasons,
                        "warnings": warnings,
                        "headline_reason": (hard_reasons or warnings or [None])[0],
                        "latest_evaluation_at": (
                            _aware(evaluation.evaluated_at) if evaluation is not None else None
                        ),
                        "latest_recommendation": (
                            evaluation.recommendation if evaluation is not None else None
                        ),
                    }
                )

                nav_rows = db.scalars(
                    select(ForwardNavObservation)
                    .where(ForwardNavObservation.study_id == study.id)
                    .order_by(ForwardNavObservation.observed_at.desc())
                    .limit(nav_points_per_study)
                ).all()
                nav_series.append(
                    {
                        "study_id": study.id,
                        "external_id": study.external_id,
                        "venue": venue,
                        "points": [
                            {
                                "observed_at": _aware(row.observed_at),
                                "nav_usd": Decimal(row.nav_usd),
                            }
                            for row in reversed(nav_rows)
                        ],
                    }
                )

        incident_rows = db.scalars(
            select(ForwardStudyIncident)
            .order_by(ForwardStudyIncident.opened_at.desc())
            .limit(50)
        ).all()
        incidents: list[dict[str, Any]] = []
        for row in incident_rows:
            study = study_map.get(row.study_id) or db.get(ForwardStudy, row.study_id)
            incidents.append(
                {
                    "id": row.id,
                    "study_id": row.study_id,
                    "external_id": study.external_id if study is not None else None,
                    "venue": study.venue if study is not None else None,
                    "severity": row.severity,
                    "code": row.code,
                    "message": row.message,
                    "data_integrity": bool(row.data_integrity),
                    "resolved": bool(row.resolved),
                    "opened_at": _aware(row.opened_at),
                    "resolved_at": _aware(row.resolved_at) if row.resolved_at else None,
                }
            )

        active = [row for row in engines if row["study_status"] == "active"]
        blocked = sum(row["operational_state"] == "blocked" for row in active)
        waiting = sum(row["operational_state"] == "waiting" for row in active)
        ready = sum(row["operational_state"] == "ready" for row in active)
        overall_state = "blocked" if blocked else ("waiting" if waiting or not active else "ready")
        initial_total = sum(
            (row["initial_capital_usd"] for row in active), Decimal("0")
        )
        current_values = [row["latest_nav_usd"] for row in active if row["latest_nav_usd"] is not None]
        current_total = sum(current_values, Decimal("0")) if current_values else None
        pnl_total = current_total - initial_total if current_total is not None else None
        pnl_pct_total = (
            pnl_total / initial_total * Decimal("100")
            if pnl_total is not None and initial_total > 0
            else None
        )

        return {
            "generated_at": now,
            "mode": "read-only-forward-research-observatory",
            "overall_state": overall_state,
            "safety": {
                "can_trade_live": False,
                "can_sign": False,
                "can_move_funds": False,
                "can_promote_strategy": False,
            },
            "totals": {
                "active_studies": len(active),
                "ready_studies": ready,
                "waiting_studies": waiting,
                "blocked_studies": blocked,
                "initial_nav_usd": initial_total,
                "current_nav_usd": current_total,
                "pnl_usd": pnl_total,
                "pnl_pct": pnl_pct_total,
                "closed_trades": sum(row["trade_count"] for row in active),
                "execution_observations": sum(
                    row["execution_observation_count"] for row in active
                ),
                "unresolved_critical_incidents": sum(
                    row["unresolved_critical_incident_count"] for row in active
                ),
                "data_integrity_failures": sum(
                    row["data_integrity_failure_count"] for row in active
                ),
            },
            "engines": engines,
            "nav_series": nav_series,
            "incidents": incidents,
        }


DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>Edge Lab · Forward Observatory</title>
<style>
:root{--bg:#090d12;--panel:#10161e;--panel2:#131b25;--line:#202c3a;--text:#eef4fb;--muted:#8190a3;--blue:#6ea8ff;--cyan:#55d6c2;--amber:#f5c76b;--red:#ff7a86;--green:#5ed39b;--shadow:0 18px 50px rgba(0,0,0,.28)}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}body{min-height:100vh;background:radial-gradient(circle at 80% -10%,rgba(82,130,255,.13),transparent 34rem),var(--bg)}
.shell{max-width:1500px;margin:0 auto;padding:30px 28px 60px}.top{display:flex;align-items:center;justify-content:space-between;gap:22px;margin-bottom:26px}.brand{display:flex;align-items:center;gap:13px}.mark{width:38px;height:38px;border:1px solid #31445c;border-radius:11px;display:grid;place-items:center;background:linear-gradient(145deg,#182433,#0e151e);box-shadow:var(--shadow)}.mark:before{content:"";width:16px;height:16px;border:2px solid var(--blue);border-top-color:var(--cyan);border-radius:50%;box-shadow:0 0 18px rgba(110,168,255,.35)}h1{font-size:17px;letter-spacing:.01em;margin:0}.eyebrow,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-top:3px}.top-right{display:flex;align-items:center;gap:12px}.fresh{font-size:12px;color:var(--muted)}button{appearance:none;border:1px solid var(--line);background:#111925;color:#dbe8f7;padding:9px 12px;border-radius:9px;font-weight:650;cursor:pointer}button:hover{border-color:#34475e}.safety{display:flex;align-items:center;gap:10px;border:1px solid #1d3a37;background:#0d1a1a;border-radius:12px;padding:11px 14px;color:#aadbd0;font-size:12px;margin-bottom:18px}.lock{width:7px;height:7px;background:var(--cyan);border-radius:50%;box-shadow:0 0 0 4px rgba(85,214,194,.1)}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}.card{background:linear-gradient(180deg,rgba(18,25,35,.94),rgba(13,19,27,.94));border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}.metric{grid-column:span 3;padding:18px}.metric .label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.09em}.metric .value{font-size:26px;font-weight:720;letter-spacing:-.03em;margin-top:11px}.metric .sub{font-size:12px;color:var(--muted);margin-top:6px}.section{margin-top:30px}.section-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:12px}.section h2{font-size:14px;margin:0}.section p{font-size:12px;color:var(--muted);margin:4px 0 0}.engines{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.engine{padding:18px;min-height:220px}.engine-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.venue{font-size:13px;font-weight:700;text-transform:capitalize}.pill{font-size:10px;text-transform:uppercase;letter-spacing:.08em;border:1px solid var(--line);padding:5px 7px;border-radius:999px}.pill.ready{color:var(--green);border-color:#27513f;background:#10231b}.pill.waiting{color:var(--amber);border-color:#584a29;background:#211c10}.pill.blocked{color:var(--red);border-color:#5f2e36;background:#241217}.instrument{font-size:12px;color:var(--muted);margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.engine-nav{display:flex;align-items:baseline;justify-content:space-between;margin-top:24px}.engine-nav .nav{font-size:24px;font-weight:720}.delta{font-size:12px}.pos{color:var(--green)}.neg{color:var(--red)}.neutral{color:var(--muted)}.engine-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:18px}.mini{border-top:1px solid var(--line);padding-top:11px}.mini b{display:block;font-size:14px}.mini span{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}.reason{font-size:11px;color:var(--amber);margin-top:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.chart-card{grid-column:span 8;padding:18px}.incident-card{grid-column:span 4;padding:18px}.canvas-wrap{height:260px;margin-top:14px}canvas{width:100%;height:100%}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted)}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px}.incident-list{margin-top:10px;display:grid;gap:9px;max-height:286px;overflow:auto}.incident{border:1px solid var(--line);background:#0d131b;border-radius:10px;padding:10px}.incident-top{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:var(--muted);text-transform:uppercase}.incident-code{font-size:11px;margin-top:6px;color:#dce7f5}.incident-msg{font-size:11px;color:var(--muted);margin-top:4px;line-height:1.45}.empty{font-size:12px;color:var(--muted);padding:20px 0}.footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:15px;color:#647487;font-size:10px}.error{padding:14px;border:1px solid #5f2e36;border-radius:12px;color:#ffb0b8;background:#241217;display:none;margin-bottom:14px}
@media(max-width:980px){.metric{grid-column:span 6}.engines{grid-template-columns:1fr}.chart-card,.incident-card{grid-column:span 12}}@media(max-width:620px){.shell{padding:20px 14px 40px}.top{align-items:flex-start}.fresh{display:none}.metric{grid-column:span 12}.metric .value{font-size:24px}.top-right{gap:7px}.engine-stats{grid-template-columns:repeat(3,1fr)}.footer{flex-direction:column}.safety{align-items:flex-start}}
</style>
</head>
<body>
<main class="shell">
  <header class="top"><div class="brand"><div class="mark"></div><div><h1>Edge Lab</h1><div class="eyebrow">Forward Research Observatory</div></div></div><div class="top-right"><span id="fresh" class="fresh mono">loading…</span><button id="refresh">Refresh</button></div></header>
  <div id="error" class="error"></div>
  <div class="safety"><span class="lock"></span><span>Research-only surface · signer disabled · no live orders · no fund movement · no automatic strategy promotion</span></div>
  <section class="grid" id="metrics"></section>
  <section class="section"><div class="section-head"><div><h2>Research engines</h2><p>Frozen forward studies across all three venues.</p></div><span id="overall" class="pill waiting">loading</span></div><div class="engines" id="engines"></div></section>
  <section class="section grid"><div class="card chart-card"><div class="section-head"><div><h2>Forward NAV</h2><p>Persisted simulated NAV observations. No reconstructed browser-side P&amp;L.</p></div><div class="legend" id="legend"></div></div><div class="canvas-wrap"><canvas id="navchart"></canvas></div></div><div class="card incident-card"><div class="section-head"><div><h2>Incident stream</h2><p>Newest evidence and integrity incidents.</p></div></div><div class="incident-list" id="incidents"></div></div></section>
  <footer class="footer"><span>Edge Lab M6H · private operational observability</span><span class="mono">GET-only dashboard surface</span></footer>
</main>
<script>
const $=s=>document.querySelector(s);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(Number(v));
const num=v=>new Intl.NumberFormat('en-US').format(Number(v||0));const pct=v=>v==null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(2)}%`;
const age=s=>{if(!s)return '—';const n=Number(s);if(n<60)return `${Math.round(n)}s`;if(n<3600)return `${Math.round(n/60)}m`;return `${(n/3600).toFixed(1)}h`};
const colors={hyperliquid:'#6ea8ff',polymarket:'#f5c76b',solana:'#55d6c2'};
function metric(label,value,sub=''){return `<article class="card metric"><div class="label">${esc(label)}</div><div class="value">${value}</div><div class="sub">${esc(sub)}</div></article>`}
function renderMetrics(d){const t=d.totals;const cls=Number(t.pnl_usd||0)>0?'pos':Number(t.pnl_usd||0)<0?'neg':'neutral';$('#metrics').innerHTML=metric('Active studies',num(t.active_studies),`${t.ready_studies} ready · ${t.waiting_studies} waiting · ${t.blocked_studies} blocked`)+metric('Combined NAV',money(t.current_nav_usd),`Initial ${money(t.initial_nav_usd)}`)+metric('Net forward P&L',`<span class="${cls}">${money(t.pnl_usd)}</span>`,pct(t.pnl_pct))+metric('Evidence',num(t.execution_observations),`${num(t.closed_trades)} closed trades · ${num(t.data_integrity_failures)} integrity failures`)}
function renderEngines(d){$('#overall').className=`pill ${d.overall_state}`;$('#overall').textContent=d.overall_state;$('#engines').innerHTML=d.engines.length?d.engines.map(e=>{const dc=Number(e.pnl_usd||0)>0?'pos':Number(e.pnl_usd||0)<0?'neg':'neutral';return `<article class="card engine"><div class="engine-top"><div><div class="venue">${esc(e.venue)}</div><div class="instrument mono">${esc(e.instrument)}</div></div><span class="pill ${esc(e.operational_state)}">${esc(e.operational_state)}</span></div><div class="engine-nav"><div><div class="eyebrow">Latest NAV</div><div class="nav">${money(e.latest_nav_usd)}</div></div><div class="delta ${dc}">${pct(e.pnl_pct)}</div></div><div class="engine-stats"><div class="mini"><b>${num(e.trade_count)}</b><span>Trades</span></div><div class="mini"><b>${num(e.execution_observation_count)}</b><span>Exec obs</span></div><div class="mini"><b>${num(e.forward_age_days)}d</b><span>Forward age</span></div></div><div class="reason mono">${esc(e.headline_reason||e.latest_recommendation||'No active warnings')}</div></article>`}).join(''):'<div class="empty">No forward studies have been bootstrapped yet.</div>'}
function renderIncidents(d){const rows=d.incidents.slice(0,18);$('#incidents').innerHTML=rows.length?rows.map(i=>`<div class="incident"><div class="incident-top"><span>${esc(i.venue||'unknown')} · ${esc(i.severity)}</span><span>${i.resolved?'resolved':'open'}</span></div><div class="incident-code mono">${esc(i.code)}</div><div class="incident-msg">${esc(i.message)}</div></div>`).join(''):'<div class="empty">No incidents recorded.</div>'}
function drawChart(d){const canvas=$('#navchart'),box=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio||1;canvas.width=Math.max(1,Math.floor(box.width*ratio));canvas.height=Math.max(1,Math.floor(box.height*ratio));const c=canvas.getContext('2d');c.scale(ratio,ratio);const W=box.width,H=box.height,p={l:44,r:12,t:14,b:26};c.clearRect(0,0,W,H);const series=d.nav_series.filter(s=>s.points.length);$('#legend').innerHTML=series.map(s=>`<span><i class="dot" style="background:${colors[s.venue]||'#8190a3'}"></i>${esc(s.venue)}</span>`).join('');if(!series.length){c.fillStyle='#8190a3';c.font='12px sans-serif';c.fillText('NAV observations will appear here after bootstrap.',p.l,40);return}const pts=series.flatMap(s=>s.points.map(x=>({t:+new Date(x.observed_at),v:Number(x.nav_usd)})));let minT=Math.min(...pts.map(x=>x.t)),maxT=Math.max(...pts.map(x=>x.t)),minV=Math.min(...pts.map(x=>x.v)),maxV=Math.max(...pts.map(x=>x.v));if(maxT===minT)maxT=minT+1;if(maxV===minV){minV-=1;maxV+=1}const pad=(maxV-minV)*.08;minV-=pad;maxV+=pad;const x=t=>p.l+(t-minT)/(maxT-minT)*(W-p.l-p.r),y=v=>p.t+(maxV-v)/(maxV-minV)*(H-p.t-p.b);c.strokeStyle='#202c3a';c.lineWidth=1;c.font='10px ui-monospace';c.fillStyle='#718196';for(let i=0;i<4;i++){const yy=p.t+i*(H-p.t-p.b)/3;c.beginPath();c.moveTo(p.l,yy);c.lineTo(W-p.r,yy);c.stroke();const val=maxV-i*(maxV-minV)/3;c.fillText('$'+val.toFixed(0),4,yy+3)}series.forEach(s=>{c.beginPath();c.strokeStyle=colors[s.venue]||'#8190a3';c.lineWidth=2;let first=true;s.points.forEach(q=>{const xx=x(+new Date(q.observed_at)),yy=y(Number(q.nav_usd));first?(c.moveTo(xx,yy),first=false):c.lineTo(xx,yy)});c.stroke()})}
async function load(){try{$('#error').style.display='none';const r=await fetch('/dashboard/api/snapshot',{cache:'no-store'});if(!r.ok)throw new Error(`Dashboard data request failed (${r.status})`);const d=await r.json();renderMetrics(d);renderEngines(d);renderIncidents(d);drawChart(d);$('#fresh').textContent='updated '+new Date(d.generated_at).toLocaleTimeString()}catch(e){$('#error').textContent=e.message;$('#error').style.display='block'}}
$('#refresh').addEventListener('click',load);window.addEventListener('resize',()=>load());load();setInterval(load,30000);
</script>
</body>
</html>'''


@router.get("", response_class=HTMLResponse, dependencies=[Depends(_dashboard_auth)])
def dashboard_page(response: Response) -> HTMLResponse:
    rendered = HTMLResponse(DASHBOARD_HTML)
    _security_headers(rendered)
    return rendered


@router.get("/api/snapshot", dependencies=[Depends(_dashboard_auth)])
def dashboard_snapshot(
    response: Response,
    db: Session = Depends(get_db),
):
    _security_headers(response)
    return DashboardService.snapshot(db, settings=get_settings())
