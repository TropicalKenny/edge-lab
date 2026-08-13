const state = { summary: null, selectedStudy: null, refreshTimer: null };

const $ = (id) => document.getElementById(id);
const money = (value, digits = 2) => {
  const number = Number(value || 0);
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(number);
};
const pct = (value, digits = 2) => `${Number(value || 0) >= 0 ? '+' : ''}${Number(value || 0).toFixed(digits)}%`;
const compact = (value) => new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));
const dateTime = (value) => value ? new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
const shortDate = (value) => value ? new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '—';
const escapeHtml = (text) => String(text ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

async function api(path) {
  const response = await fetch(path, { headers: { 'Accept': 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function deltaClass(value) {
  const number = Number(value || 0);
  return number > 0 ? 'positive' : number < 0 ? 'negative' : 'neutral';
}

function recommendationClass(value) {
  const upper = String(value || '').toUpperCase();
  if (upper.includes('GREEN')) return 'green';
  if (upper.includes('RED') || upper.includes('BLOCK')) return 'red';
  return 'amber';
}

function venueLabel(venue) {
  if (venue === 'hyperliquid') return 'Hyperliquid';
  if (venue === 'polymarket') return 'Polymarket';
  if (venue === 'solana') return 'Solana';
  return String(venue || 'Unknown');
}

function instrumentLabel(study) {
  if (study.venue === 'hyperliquid') return `${study.instrument} funding / carry`;
  if (study.venue === 'polymarket') return 'Structural markets';
  if (study.venue === 'solana') return 'Pump launch baseline';
  return study.instrument || study.external_id;
}

function renderSummary(summary) {
  state.summary = summary;
  $('combinedNav').textContent = money(summary.combined_research_nav_usd);
  const pnl = Number(summary.combined_research_pnl_usd || 0);
  const pnlEl = $('combinedPnl');
  pnlEl.textContent = `${pnl >= 0 ? '+' : ''}${money(pnl)} · ${pct(summary.combined_research_return_pct)}`;
  pnlEl.className = `delta ${deltaClass(pnl)}`;
  $('activeStudies').textContent = summary.active_study_count;

  const active = (summary.studies || []).filter((study) => study.status === 'active');
  const venues = new Set(active.map((study) => study.venue));
  $('venueCount').textContent = venues.size;
  $('openPositions').textContent = active.reduce((total, study) => total + Number(study.open_positions || 0), 0);
  $('tradeCount').textContent = compact(active.reduce((total, study) => total + Number(study.closed_trades || 0), 0));
  $('incidentCount').textContent = summary.unresolved_incident_count;
  $('systemState').textContent = summary.system_state;
  $('systemDot').className = `state-orb ${summary.system_state === 'healthy' ? 'healthy' : summary.system_state === 'attention' ? 'attention' : ''}`;

  const banner = $('attentionBanner');
  if (summary.data_integrity_failure_count > 0) {
    banner.textContent = `${summary.data_integrity_failure_count} data-integrity issue${summary.data_integrity_failure_count === 1 ? '' : 's'} recorded. Affected studies cannot qualify for live promotion.`;
    banner.classList.remove('hidden');
  } else if (summary.unresolved_incident_count > 0) {
    banner.textContent = `${summary.unresolved_incident_count} operational incident${summary.unresolved_incident_count === 1 ? '' : 's'} need attention. Research continues only where the study remains valid.`;
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }

  renderStrategies(summary.studies || []);
  renderStudySelect(summary.studies || []);
  $('lastUpdated').textContent = `Updated ${dateTime(summary.generated_at)}`;
}

function renderStrategies(studies) {
  const grid = $('strategyGrid');
  if (!studies.length) {
    grid.innerHTML = '<div class="panel empty-panel">No forward studies have been bootstrapped yet.</div>';
    return;
  }
  grid.innerHTML = studies.map((study) => {
    const ret = Number(study.return_pct || 0);
    const progress = Math.max(0, Math.min(100, Number(study.forward_days || 0) / 90 * 100));
    const recommendation = study.recommendation || 'RESEARCH';
    const problem = study.data_integrity_failures > 0
      ? `${study.data_integrity_failures} permanent data-integrity issue${study.data_integrity_failures === 1 ? '' : 's'}`
      : study.unresolved_incidents > 0
        ? `${study.unresolved_incidents} unresolved incident${study.unresolved_incidents === 1 ? '' : 's'}`
        : '';
    return `
      <article class="strategy-card" data-study-id="${escapeHtml(study.id)}">
        <div class="strategy-top">
          <div><div class="venue-chip">${escapeHtml(venueLabel(study.venue))}</div><div class="strategy-name">${escapeHtml(instrumentLabel(study))}</div></div>
          <span class="status-chip ${recommendationClass(recommendation)}">${escapeHtml(recommendation.replaceAll('_', ' '))}</span>
        </div>
        <div class="strategy-return"><strong class="${deltaClass(ret) === 'positive' ? 'pnl-positive' : deltaClass(ret) === 'negative' ? 'pnl-negative' : ''}">${pct(ret)}</strong><span>${money(study.pnl_usd)} P&amp;L</span></div>
        <div class="progress-track" title="${study.forward_days} of minimum 90 forward days"><div class="progress-bar" style="width:${progress}%"></div></div>
        <div class="strategy-stats">
          <div class="strategy-stat"><span>NAV</span><strong>${money(study.nav_usd)}</strong></div>
          <div class="strategy-stat"><span>Trades</span><strong>${compact(study.closed_trades)}</strong></div>
          <div class="strategy-stat"><span>Forward</span><strong>${study.forward_days}d</strong></div>
        </div>
        ${problem ? `<div class="strategy-alert">${escapeHtml(problem)}</div>` : ''}
      </article>`;
  }).join('');
}

function renderStudySelect(studies) {
  const select = $('studySelect');
  const current = state.selectedStudy;
  select.innerHTML = studies.map((study) => `<option value="${escapeHtml(study.id)}">${escapeHtml(venueLabel(study.venue))} · ${escapeHtml(instrumentLabel(study))}</option>`).join('');
  if (!studies.length) {
    state.selectedStudy = null;
    drawNavChart([]);
    return;
  }
  state.selectedStudy = studies.some((study) => study.id === current) ? current : studies[0].id;
  select.value = state.selectedStudy;
  updateSelectedStudyHeader();
  loadNav(state.selectedStudy);
}

function updateSelectedStudyHeader() {
  const study = state.summary?.studies?.find((item) => item.id === state.selectedStudy);
  if (!study) return;
  $('selectedNav').textContent = money(study.nav_usd);
  $('selectedReturn').textContent = pct(study.return_pct);
  $('selectedReturn').className = deltaClass(study.return_pct) === 'positive' ? 'pnl-positive' : deltaClass(study.return_pct) === 'negative' ? 'pnl-negative' : '';
  $('selectedDays').textContent = `${study.forward_days} days`;
}

async function loadNav(studyId) {
  if (!studyId) return;
  try {
    const data = await api(`/api/nav/${encodeURIComponent(studyId)}?limit=1000`);
    drawNavChart(data.points || []);
  } catch (error) {
    drawNavChart([]);
    showToast(`NAV unavailable: ${error.message}`);
  }
}

function drawNavChart(points) {
  const canvas = $('navChart');
  const empty = $('chartEmpty');
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);

  if (!points || points.length < 2) {
    empty.classList.remove('hidden');
    $('chartStart').textContent = points?.length ? shortDate(points[0].time) : '—';
    $('chartEnd').textContent = points?.length ? shortDate(points[points.length - 1].time) : '—';
    return;
  }
  empty.classList.add('hidden');
  $('chartStart').textContent = shortDate(points[0].time);
  $('chartEnd').textContent = shortDate(points[points.length - 1].time);

  const values = points.map((point) => Number(point.nav_usd));
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const spread = max - min;
  min -= spread * 0.12;
  max += spread * 0.12;
  const pad = { left: 5, right: 5, top: 10, bottom: 10 };
  const x = (index) => pad.left + index / (points.length - 1) * (width - pad.left - pad.right);
  const y = (value) => pad.top + (max - value) / (max - min) * (height - pad.top - pad.bottom);

  ctx.lineWidth = 1;
  ctx.strokeStyle = '#edf0ed';
  for (let i = 1; i < 4; i += 1) {
    const gy = height * i / 4;
    ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke();
  }

  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, 'rgba(38, 135, 83, .17)');
  gradient.addColorStop(1, 'rgba(38, 135, 83, 0)');
  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(index); const py = y(Number(point.nav_usd));
    if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.lineTo(x(points.length - 1), height); ctx.lineTo(x(0), height); ctx.closePath();
  ctx.fillStyle = gradient; ctx.fill();

  ctx.beginPath();
  points.forEach((point, index) => {
    const px = x(index); const py = y(Number(point.nav_usd));
    if (index === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.strokeStyle = '#247a4d'; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.stroke();

  const lastX = x(points.length - 1); const lastY = y(values[values.length - 1]);
  ctx.beginPath(); ctx.arc(lastX, lastY, 3.2, 0, Math.PI * 2); ctx.fillStyle = '#247a4d'; ctx.fill();
}

function renderTrades(trades) {
  const body = $('tradesBody');
  $('tradeCaption').textContent = `${trades.length} most recent paper / shadow outcomes`;
  if (!trades.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty-cell">No closed forward trades yet.</td></tr>';
    return;
  }
  body.innerHTML = trades.map((trade) => {
    const costs = Number(trade.fees_usd || 0) + Number(trade.slippage_usd || 0);
    const pnl = Number(trade.net_pnl_usd || 0);
    return `<tr>
      <td class="trade-venue">${escapeHtml(venueLabel(trade.venue))}</td>
      <td>${escapeHtml(trade.instrument || '—')}</td>
      <td>${escapeHtml(dateTime(trade.closed_at))}</td>
      <td>${money(trade.allocated_capital_usd)}</td>
      <td>${money(costs)}</td>
      <td class="${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">${pnl >= 0 ? '+' : ''}${money(pnl)}</td>
    </tr>`;
  }).join('');
}

function renderIncidents(incidents) {
  const list = $('incidentList');
  if (!incidents.length) {
    list.innerHTML = '<div class="panel empty-panel">No unresolved incidents. Research services are operationally clean.</div>';
    return;
  }
  list.innerHTML = incidents.map((incident) => `<article class="incident-card ${escapeHtml(incident.severity)}">
    <span class="incident-mark"></span>
    <div><div class="incident-code">${escapeHtml(incident.code)}${incident.data_integrity ? ' · DATA INTEGRITY' : ''}</div><div class="incident-message">${escapeHtml(incident.message)}</div></div>
    <time class="incident-time">${escapeHtml(dateTime(incident.opened_at))}</time>
  </article>`).join('');
}

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 2600);
}

async function refresh({ silent = false } = {}) {
  const button = $('refreshButton');
  button.classList.add('spinning');
  try {
    const [summary, trades, incidents] = await Promise.all([
      api('/api/summary'), api('/api/trades?limit=40'), api('/api/incidents?limit=40&unresolved_only=true')
    ]);
    renderSummary(summary); renderTrades(trades); renderIncidents(incidents);
    if (!silent) showToast('Dashboard refreshed');
  } catch (error) {
    showToast(`Dashboard unavailable: ${error.message}`);
    $('systemState').textContent = 'offline';
    $('systemDot').className = 'state-orb attention';
  } finally {
    button.classList.remove('spinning');
  }
}

$('refreshButton').addEventListener('click', () => refresh());
$('studySelect').addEventListener('change', (event) => {
  state.selectedStudy = event.target.value;
  updateSelectedStudyHeader();
  loadNav(state.selectedStudy);
});
window.addEventListener('resize', () => {
  if (state.selectedStudy) loadNav(state.selectedStudy);
});

document.querySelectorAll('.nav-item').forEach((link) => link.addEventListener('click', () => {
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.remove('active'));
  link.classList.add('active');
}));

refresh({ silent: true });
state.refreshTimer = window.setInterval(() => refresh({ silent: true }), 15000);
