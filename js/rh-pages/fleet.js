import { api } from '../rh-api.js';
import { fmt, chartCard, accordionSection } from '../rh-components.js';
import { renderLineChart, renderSparkline, destroyChart, PROFIT, LOSS } from '../rh-charts.js';

const SLEEVE_LABEL = {
  ml_edge: 'model edge', ml_proba: 'model probability',
  reversal_1d: '1-day reversal', reversal_5d: '5-day reversal',
  momentum_120_20: '6-month momentum', pead: 'post-earnings drift', revisions: 'analyst revisions',
};

let _fleetChart = null;

function fmtUsd(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
function fmtPct(v, signed = true) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${signed && n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}
function tone(v) { return (Number(v) || 0) > 0 ? 'edge-pos' : (Number(v) || 0) < 0 ? 'edge-neg' : ''; }

function statusPill(s) {
  const map = { live_capital: 'rh-pill--green', live_paper: 'rh-pill--green', shadow: '', candidate: 'rh-pill--muted', retired: 'rh-pill--muted' };
  return `<span class="rh-pill ${map[s] || ''}">${(s || 'shadow').replace('_', ' ')}</span>`;
}

function agentCard(a, leaderId) {
  const crown = a.id === leaderId ? '<span class="td-agent-card__crown" title="Forward leader">👑</span>' : '';
  return `<button type="button" class="td-agent-card td-agent-card--v2" data-agent="${a.id}">
    <div class="td-agent-card__top">
      <span class="td-agent-card__name">${a.name || a.id}${crown}</span>
      ${statusPill(a.status)}
    </div>
    <div class="td-agent-card__big ${tone(a.returnPct)}">${fmtPct(a.returnPct)}</div>
    <div class="td-agent-card__spark"><canvas class="td-agent-spark" data-agent="${a.id}" height="36"></canvas></div>
    <div class="td-agent-card__row">
      <span>${fmtUsd(a.equity)}</span>
      <span class="${tone(a.dayPnl)}">${a.dayPnl >= 0 ? '+' : ''}${fmtUsd(a.dayPnl)}</span>
    </div>
    <span class="td-agent-card__cta">Open book →</span>
  </button>`;
}

export async function renderFleet(main, route = {}, stale = () => false) {
  if (route.agentId) return renderAgent(main, route.agentId, stale);

  main.innerHTML = '<div class="rh-loading">Mustering spawns…</div>';
  let data;
  try { data = await api.fleet(); } catch (e) {
    main.innerHTML = `<section class="rh-card"><h2>🏴‍☠️ The Fleet</h2><p class="rh-muted">${e.message}</p></section>`;
    return;
  }
  if (stale()) return;
  if (!data.ok) {
    main.innerHTML = `<section class="rh-card"><h2>🏴‍☠️ The Fleet</h2><p class="rh-muted">${data.message || 'No fleet data yet.'}</p></section>`;
    return;
  }

  const agents = data.agents || [];
  const leaderId = data.leader?.id;
  const leader = agents.find((a) => a.id === leaderId);

  main.innerHTML = `
    <header class="td-fleet-hero">
      <h2 class="td-fleet-hero__title">🏴‍☠️ The Fleet</h2>
      <p class="td-fleet-hero__sub">Every spawn walks forward on paper. I promote the greediest survivor — not the best backtest.</p>
      <div class="td-fleet-hero__stats">
        <span class="rh-chip rh-chip--ok">${agents.length} spawns</span>
        <span class="rh-chip">${data.date || '—'}</span>
        ${leader ? `<span class="rh-chip">Leader <b>${leader.name || leader.id}</b> ${fmtPct(leader.returnPct)}</span>` : ''}
      </div>
    </header>
    <div class="td-fleet-grid">${agents.map((a) => agentCard(a, leaderId)).join('')}</div>`;

  main.querySelectorAll('.td-agent-card').forEach((b) =>
    b.addEventListener('click', () => { location.hash = `#/fleet/${b.dataset.agent}`; }));

  agents.forEach((a) => loadAgentSpark(main, a.id, stale));
}

async function loadAgentSpark(main, agentId, stale) {
  const canvas = main.querySelector(`canvas[data-agent="${agentId}"]`);
  if (!canvas) return;
  try {
    const d = await api.fleetAgent(agentId);
    if (stale()) return;
    const vals = (d.equityCurve || []).map((p) => p.equity);
    renderSparkline(canvas, vals);
  } catch (_) { /* card still works without spark */ }
}

function pickRow(p, i) {
  const s = p.signals || {};
  const sleeves = Object.entries(s.sleeves || {})
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 6)
    .map(([k, v]) => `<span class="td-sleeve ${v >= 0 ? 'edge-pos' : 'edge-neg'}">${SLEEVE_LABEL[k] || k} ${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}σ</span>`)
    .join('');
  const sideCls = p.side === 'long' ? 'edge-pos' : 'edge-neg';
  return `<details class="td-pick-acc">
    <summary class="td-pick-acc__sum">
      <span class="td-pick__sym">${p.symbol} <span class="td-pick__side ${sideCls}">${(p.side || '').toUpperCase()}</span></span>
      <span class="td-pick-acc__nums">${p.shares ?? 0} sh · ${fmtUsd(p.notional)}</span>
    </summary>
    <div class="td-pick-acc__body">
      <div class="td-pick__sleeves">${sleeves || '<span class="rh-muted">blended</span>'}</div>
      <p class="rh-muted" style="font-size:13px">${p.why || ''}</p>
    </div>
  </details>`;
}

async function renderAgent(main, agentId, stale) {
  _fleetChart = destroyChart(_fleetChart);
  main.innerHTML = '<div class="rh-loading">Opening the ledger…</div>';
  let d;
  try { d = await api.fleetAgent(agentId); } catch (e) {
    main.innerHTML = `<section class="rh-card"><p class="rh-muted">${e.message}</p><a href="#/fleet">← Fleet</a></section>`;
    return;
  }
  if (stale()) return;
  const a = d.agent || {}, t = d.today || {};
  const picks = t.picks || [];
  const trades = d.trades || [];
  const curve = d.equityCurve || [];

  main.innerHTML = `
    <div class="td-breadcrumb"><a href="#/fleet">Fleet</a> <span>/</span> <strong>${a.name || agentId}</strong></div>

    <section class="td-agent-hero">
      <div class="td-agent-hero__top">
        <h2>${a.name || agentId} ${statusPill(a.status)}</h2>
        <span class="rh-pill">${a.kind || ''}</span>
      </div>
      <p class="td-agent-hero__blurb">${(a.blurb || 'Forward paper spawn.').slice(0, 160)}</p>
      <div class="td-agent-kpis">
        <div class="td-agent-kpi"><span class="td-agent-kpi__l">Equity</span><span class="td-agent-kpi__v">${fmtUsd(t.equity)}</span></div>
        <div class="td-agent-kpi"><span class="td-agent-kpi__l">Return</span><span class="td-agent-kpi__v ${tone(t.returnPct)}">${fmtPct(t.returnPct)}</span></div>
        <div class="td-agent-kpi"><span class="td-agent-kpi__l">Today</span><span class="td-agent-kpi__v ${tone(t.dayPnl)}">${t.dayPnl >= 0 ? '+' : ''}${fmtUsd(t.dayPnl)}</span></div>
        <div class="td-agent-kpi"><span class="td-agent-kpi__l">Book</span><span class="td-agent-kpi__v">${t.nLong ?? 0}L / ${t.nShort ?? 0}S</span></div>
      </div>
    </section>

    ${chartCard('Forward equity curve', `${curve.length} sessions · real prices, fake money`, 'chart-fleet-eq', 220)}

    ${accordionSection({
      id: 'acc-picks',
      title: `Portfolio · ${picks.length} positions`,
      summary: picks.length ? `Top: ${picks.slice(0, 3).map((p) => p.symbol).join(', ')}` : 'Flat',
      open: picks.length > 0 && picks.length <= 8,
      bodyHtml: picks.length ? picks.map(pickRow).join('') : '<p class="rh-muted">No positions this session.</p>',
    })}

    ${accordionSection({
      id: 'acc-trades',
      title: 'Trade history',
      summary: `${trades.length} fills`,
      bodyHtml: trades.length ? `<div class="td-trades">${trades.slice(0, 40).map((tr) => `<div class="td-trade">
        <a class="td-trade__sym" href="#/stock/${tr.symbol}">${tr.symbol}</a>
        <span class="td-trade__act ${tr.side === 'buy' ? 'edge-pos' : 'edge-neg'}">${(tr.side || '').toUpperCase()} ${tr.qty}</span>
        <span class="rh-muted">${fmtUsd(tr.price)} · ${tr.date}</span>
      </div>`).join('')}</div>` : '<p class="rh-muted">No trades yet.</p>',
    })}`;

  if (!window.Chart) {
    await new Promise((r) => setTimeout(r, 500));
  }
  if (curve.length) {
    _fleetChart = renderLineChart(main.querySelector('#chart-fleet-eq'), {
      labels: curve.map((p) => p.date),
      values: curve.map((p) => p.equity),
      label: 'Equity',
      color: (curve[curve.length - 1]?.equity || 0) >= (curve[0]?.equity || 0) ? PROFIT : LOSS,
    });
  }
}
