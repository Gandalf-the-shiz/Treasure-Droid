/**
 * Stack & Edge — mega pipeline map, ML doctrine, Mad Scientist, walk-forward (live).
 */
import { api } from '../rh-api.js';
import {
  PIPELINE_NODES, RECURSIVE_LOOPS, COMPARE_MODELS, COMPARE_LABELS, CADENCE_ROWS,
  LAYER_COLORS, ALPHA_SLEEVES, EXPERIMENT_PROFILES, STORY_FLOW, nodeById,
} from '../rh-arch-data.js';
import { renderMegaChart, tooltipHtml } from '../rh-arch-mega.js';
import { brainLogsHtml, bindBrainLogsTabs, fetchBrainInsights } from './brain-logs.js';

let _chartInstances = [];

function destroyCharts() {
  _chartInstances.forEach((c) => { try { c.destroy(); } catch (_) { /* */ } });
  _chartInstances = [];
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function scoreDots(n, max = 5) {
  const filled = Math.round(Math.max(0, Math.min(max, n)));
  return `${'●'.repeat(filled)}${'○'.repeat(max - filled)}`;
}

async function fetchStackData() {
  const out = { stack: null, operating: null, agents: null, compare: null, experiment: null,
    harvest: null, megamind: null, livePanel: null, commandCenter: null, walkforward: null,
    apiStale: false, errors: [] };
  try {
    const [stack, cc, wf] = await Promise.all([
      api.stackOverview(),
      api.commandCenter().catch(() => null),
      api.walkforward().catch(() => null),
    ]);
    out.stack = stack;
    out.operating = stack.operating;
    out.agents = stack.realAgents;
    out.compare = stack.compare;
    out.experiment = stack.experiment;
    out.harvest = stack.harvest;
    out.megamind = stack.megamind;
    out.livePanel = stack.livePanel;
    out.commandCenter = cc;
    out.walkforward = wf;
    return out;
  } catch (_) { /* fallback below */ }

  const [op, ag, cmp, exp, cc, wf] = await Promise.all([
    api.arenaOperating().catch(() => null),
    api.realAgents().catch(() => null),
    api.arenaCompare().catch(() => null),
    api.arenaExperiment().catch(() => null),
    api.commandCenter().catch(() => null),
    api.walkforward().catch(() => null),
  ]);
  out.operating = op;
  out.agents = ag;
  out.compare = cmp;
  out.experiment = exp;
  out.commandCenter = cc;
  out.walkforward = wf;
  return out;
}

function colorLegendHtml() {
  return `<div class="td-arch-legend">
    ${Object.entries(LAYER_COLORS).filter(([k]) => k !== 'loop').map(([k, v]) =>
      `<span class="td-arch-legend__item"><i style="background:${v.stroke}"></i>${v.label}</span>`).join('')}
    <span class="td-arch-legend__flow">${STORY_FLOW.split(' → ').map((part, i) => {
      const colors = ['#9ca3af', '#22c55e', '#a855f7', '#ff9500'];
      return `<b style="color:${colors[i] || '#fff'}">${part}</b>${i < 3 ? ' → ' : ''}`;
    }).join('')}</span>
  </div>`;
}

function mlModelsHtml() {
  const models = PIPELINE_NODES.filter((n) => n.layer === 'ml');
  return `<div class="td-ml-grid">${models.map((m) => {
    const lc = LAYER_COLORS.ml;
    return `<article class="td-ml-card" data-ml-card="${m.id}">
      <header class="td-ml-card__head" style="border-color:${lc.stroke}">
        <h3>${m.label}</h3>
        <code>${m.script || ''}</code>
      </header>
      <p class="td-ml-card__edge">${m.edge}</p>
      ${m.theory ? `<p class="td-ml-card__theory"><strong>Theory:</strong> ${m.theory}</p>` : ''}
      ${m.equation ? `<pre class="td-ml-card__eq">${m.equation}</pre>` : ''}
      <details class="td-ml-card__more">
        <summary>Sources, cadence, downstream</summary>
        <p><b>Cadence:</b> ${m.cadence}</p>
        <p><b>Sources:</b> ${m.sources.join(' · ')}</p>
        <p><b>Downstream:</b> ${m.downstream.join(' · ')}</p>
      </details>
    </article>`;
  }).join('')}</div>
    <p class="rh-section-title">Alpha factory sleeves (each neutralized → combined)</p>
    <div class="td-sleeve-grid">${ALPHA_SLEEVES.map((s) => `
      <article class="td-sleeve-card">
        <h4>${s.label}</h4>
        <pre class="td-sleeve-eq">${s.equation}</pre>
        ${s.theory ? `<p class="td-sleeve-theory">${s.theory}</p>` : ''}
        <p class="td-sleeve-edge">${s.edge}</p>
      </article>`).join('')}</div>
    <div class="td-arch-callout">
      <strong>Fundamental Law (Grinold):</strong> IR = IC × √Breadth × TransferCoefficient.
      Treasure Droid attacks all three: multi-sleeve IC, 2,500+ symbol breadth, market-neutral transfer.
    </div>`;
}

function sleeveIcHtml(cc) {
  const ic = cc?.sleeveIc;
  if (!ic?.ok || !ic.sleeves?.length) {
    return '<p class="rh-muted" style="font-size:12px">Sleeve IC tracker will populate after daily close harness runs.</p>';
  }
  const rows = ic.sleeves.map((s) => `<tr class="${s.decayed ? 'td-sleeve-decayed' : ''}">
    <td><code>${esc(s.id)}</code></td>
    <td>${s.forwardIc != null ? Number(s.forwardIc).toFixed(4) : '—'}</td>
    <td>${s.forwardIcir != null ? Number(s.forwardIcir).toFixed(2) : '—'}</td>
    <td>${s.effectiveWeight != null ? Number(s.effectiveWeight).toFixed(2) : '—'}</td>
    <td>${s.decayed ? '⚠ decay' : '✓'}</td>
  </tr>`).join('');
  return `<p class="rh-section-title">Live sleeve IC (forward truth → alpha weights)</p>
    <p class="rh-muted" style="font-size:12px">Mode: <strong>${esc(ic.weightMode || '—')}</strong> · ${ic.forwardDays || 0} forward days</p>
    <table class="rh-table rh-table--compact"><thead><tr><th>Sleeve</th><th>Fwd IC</th><th>ICIR</th><th>Weight</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function madScientistHtml(cc) {
  const lab = cc?.madScientistLab || {};
  const loop = lab.loop || {};
  const lb = lab.leaderboard || [];
  const rows = lb.slice(0, 8).map((r) => `<tr>
    <td><code>${esc(r.id || r.genomeId || '—')}</code></td>
    <td>${esc(r.family || '—')}</td>
    <td>${r.selSharpe != null ? Number(r.selSharpe).toFixed(2) : '—'}</td>
    <td><strong>${r.holdSharpe != null ? Number(r.holdSharpe).toFixed(2) : '—'}</strong></td>
    <td>${r.holdReturnPct != null ? `${Number(r.holdReturnPct).toFixed(1)}%` : '—'}</td>
  </tr>`).join('');

  return `
    <div class="td-mad-hero">
      <h2>🧪 Mad Scientist Doctrine</h2>
      <p>Experiment relentlessly on history. Prove forward on paper. Unleash capital only when the data screams yes.</p>
    </div>
    <div class="td-mad-flow">
      <div class="td-mad-step td-mad-step--data"><span>8yr OHLCV train</span><small>predictor v3 ≤ 2023</small></div>
      <div class="td-mad-arrow">→</div>
      <div class="td-mad-step td-mad-step--pipe"><span>Historical panel</span><small>2024–2025 · live columns</small></div>
      <div class="td-mad-arrow">→</div>
      <div class="td-mad-step td-mad-step--ml"><span>Genome walk</span><small>500+ spawns / cycle</small></div>
      <div class="td-mad-arrow">→</div>
      <div class="td-mad-step td-mad-step--ml"><span>Select 60%</span><small>judge 40% holdout</small></div>
      <div class="td-mad-arrow">→</div>
      <div class="td-mad-step td-mad-step--droid"><span>Shadow fleet</span><small>MS-* forward paper</small></div>
    </div>
    <div class="rh-arch-live">
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Loop cycle</div>
        <div class="rh-arch-stat__value">${loop.cycle ?? '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Profile</div>
        <div class="rh-arch-stat__value">${esc(loop.profile || '—')}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Genomes</div>
        <div class="rh-arch-stat__value">${lab.nGenomes ?? '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Scored</div>
        <div class="rh-arch-stat__value">${lab.nScored ?? '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Best holdout Sharpe</div>
        <div class="rh-arch-stat__value rh-arch-stat__value--accent">${lab.bestHoldoutSharpe != null ? Number(lab.bestHoldoutSharpe).toFixed(2) : '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Survivors promoted</div>
        <div class="rh-arch-stat__value">${lab.nSurvivors ?? 0}</div></div>
    </div>
    ${lab.verdict ? `<div class="td-arch-callout td-arch-callout--warn"><strong>Latest verdict:</strong> ${esc(lab.verdict)}</div>` : ''}
    ${lab.caveat ? `<p class="rh-muted" style="font-size:12px">${esc(lab.caveat)}</p>` : ''}
    ${lab.method ? `<p class="rh-muted" style="font-size:12px"><strong>Method:</strong> ${esc(lab.method)}</p>` : ''}
    <p class="rh-section-title">Experiment profiles (rotate every 3h)</p>
    <table class="rh-table rh-table--compact"><thead><tr><th>Profile</th><th>Genomes</th><th>Signal bias</th><th>Promote</th><th>Edge</th></tr></thead>
    <tbody>${EXPERIMENT_PROFILES.map((p) => `<tr><td><code>${p.name}</code></td><td>${p.genomes}</td><td>${p.signal}</td><td>${p.promote}</td><td>${p.edge}</td></tr>`).join('')}</tbody></table>
    <p class="rh-section-title">Genome families explored</p>
    <p class="rh-muted" style="font-size:12px">alpha_neutral · ml_edge · momentum_long · contrarian · short_bias · long_short_neutral · high_conviction · mean_reverter · breakout</p>
    <p class="rh-section-title">Live leaderboard (updates each lab run)</p>
    ${rows ? `<table class="rh-table"><thead><tr><th>Genome</th><th>Family</th><th>Sel Sharpe</th><th>Hold Sharpe</th><th>Hold ret</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="rh-muted">No lab results yet — mad scientist loop will populate.</p>'}
    <pre class="td-mad-eq">genome day return:
  R = w_long·Σ ret_top − w_short·Σ ret_bottom − cost_bps·turnover
signal ∈ {edge, α}; genome = {min_proba, min_pred_ret, top_k, kelly, short_frac}
promote if holdout Sharpe ≥ 0.5 and held on unseen tail</pre>`;
}

function walkforwardHtml(cc, wf) {
  const lab = cc?.madScientistLab || {};
  const w = lab.window || {};
  const panel = lab.panel || {};
  const held = lab.topHeldUp;
  return `
    <h2>8-year train · 2-year walk-forward</h2>
    <p class="rh-muted">Train end <strong>2023-12-31</strong>. Walk-forward <strong>2024-01-01 → 2025-12-31</strong> on a panel that mirrors live Treasure Droid outputs.</p>
    ${lab.generatedAt ? `<p class="rh-muted" style="font-size:11px">Last lab run: ${esc(lab.generatedAt)}</p>` : ''}
    <div class="rh-arch-live">
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Panel rows</div><div class="rh-arch-stat__value">${panel.rows != null ? Number(panel.rows).toLocaleString() : '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Trading days</div><div class="rh-arch-stat__value">${w.nDays ?? panel.nDays ?? '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Symbols</div><div class="rh-arch-stat__value">${panel.nSymbols ?? '—'}</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Selection frac</div><div class="rh-arch-stat__value">60%</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Cost assumption</div><div class="rh-arch-stat__value">7 bps</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Return clip</div><div class="rh-arch-stat__value">±15%/day</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Min promote Sharpe</div><div class="rh-arch-stat__value">0.50</div></div>
      <div class="rh-arch-stat"><div class="rh-arch-stat__label">Selection held up</div>
        <div class="rh-arch-stat__value">${held != null ? `${Math.round(held * 100)}%` : '—'}</div></div>
    </div>
    <div class="rh-chart-wrap rh-chart-wrap--md"><canvas id="rh-wf-holdout"></canvas></div>
    <ol class="rh-arch-steps">
      <li><strong>panel_builder.py</strong> merges predictor val+test, point-in-time price sleeves, alpha frame (pred_proba_up, pred_ret, edge, n_*, alpha, y_ret).</li>
      <li><strong>walkforward_lab.py</strong> spawns N genomes; walks day-by-day; scores selection window then holdout tail.</li>
      <li><strong>Promote</strong> top holdout survivors → shadow fleet agents (MS-*). Forward paper is the only real proof.</li>
      <li><strong>mad_scientist_loop.py</strong> rotates experiment profiles every 3h (alpha_neutral_wide, edge_hunter, deep_search, tight_holdout).</li>
    </ol>
    ${wf?.ok ? `<p class="rh-muted">Fleet walkforward JSON: ${wf.nSurvivors ?? wf.survivors?.length ?? 0} survivors in fleet walkforward artifact.</p>` : ''}
    ${sleeveIcHtml(cc)}
    <div class="td-arch-callout"><strong>Honest caveat:</strong> Holdout Sharpe on historical panel is an upper bound — correlated genomes share the same predictor test set. Label as research until forward IC agrees.</div>`;
}

function recursiveLoopsHtml() {
  return `<div class="td-loop-grid">${RECURSIVE_LOOPS.map((loop) => {
    const lc = LAYER_COLORS.loop;
    return `<article class="td-loop-card" style="border-color:${lc.stroke}">
      <header><h3>${loop.label}</h3><span class="td-loop-cadence">${loop.cadence}</span></header>
      <p>${loop.edge}</p>
      <ul>${loop.children.map((c) => `<li>${c}</li>`).join('')}</ul>
      ${loop.script ? `<code>${loop.script}</code>` : ''}
    </article>`;
  }).join('')}</div>
  <div class="td-recursive-diagram">
    <p class="rh-muted" style="font-size:12px;margin-bottom:8px">Recursive learning — dashed feedback into the mega map:</p>
    <svg class="td-recursive-svg" viewBox="0 0 720 200" xmlns="http://www.w3.org/2000/svg">
      <defs><marker id="arr-loop" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#818cf8"/></marker></defs>
      <rect x="10" y="70" width="100" height="36" rx="6" fill="#374151" stroke="#9ca3af"/><text x="60" y="93" text-anchor="middle" fill="#f3f4f6" font-size="10">Data feeds</text>
      <rect x="140" y="70" width="100" height="36" rx="6" fill="#14532d" stroke="#22c55e"/><text x="190" y="93" text-anchor="middle" fill="#bbf7d0" font-size="10">Pipelines</text>
      <rect x="270" y="70" width="100" height="36" rx="6" fill="#4c1d95" stroke="#a855f7"/><text x="320" y="93" text-anchor="middle" fill="#e9d5ff" font-size="10">ML + Arena</text>
      <rect x="400" y="70" width="110" height="36" rx="6" fill="#7c2d12" stroke="#ff9500"/><text x="455" y="93" text-anchor="middle" fill="#fff4e0" font-size="10">Treasure Droid</text>
      <rect x="540" y="70" width="90" height="36" rx="6" fill="#0c4a6e" stroke="#38bdf8"/><text x="585" y="93" text-anchor="middle" fill="#bae6fd" font-size="10">Forward IC</text>
      <path d="M110 88 H140 M240 88 H270 M370 88 H400 M510 88 H540" stroke="rgba(148,163,184,0.5)" stroke-width="2" fill="none"/>
      <path d="M585 106 C585 160 320 170 320 106" stroke="#38bdf8" stroke-width="1.5" fill="none" stroke-dasharray="6 4" marker-end="url(#arr-loop)"/>
      <path d="M455 70 C455 30 190 20 190 70" stroke="#a855f7" stroke-width="1.5" fill="none" stroke-dasharray="5 3" opacity="0.7"/>
      <text x="360" y="18" text-anchor="middle" fill="#94a3b8" font-size="9">sleeve_ic + lab results reweight ML</text>
      <text x="400" y="188" text-anchor="middle" fill="#38bdf8" font-size="9">forward truth gates capital</text>
    </svg>
  </div>`;
}

function opsTabHtml(data) {
  const op = data.operating || {};
  return `
    <p class="rh-section-title">Autonomous schedule</p>
    <table class="rh-table"><thead><tr><th>Cadence</th><th>Job</th><th>What it does</th></tr></thead>
    <tbody>${CADENCE_ROWS.map(([c, j, d]) => `<tr><td>${c}</td><td><code>${esc(j)}</code></td><td>${esc(d)}</td></tr>`).join('')}</tbody></table>
    <p class="rh-section-title">Live arena (sim)</p>
    <p class="rh-muted" style="font-size:12px">Champion: <strong>${esc(op.champion || 'v3')}</strong> · Pulse: ${esc((op.pulseVersions || []).join(', '))}</p>
    <div class="rh-chart-wrap rh-chart-wrap--md"><canvas id="rh-arena-bar"></canvas></div>
    <div class="rh-chart-wrap"><canvas id="rh-arena-equity"></canvas></div>`;
}

function compareTabHtml(data) {
  const rows = COMPARE_MODELS.map((m) => {
    const cells = COMPARE_LABELS.map(({ key }) => `<td>${scoreDots(m[key])} <span class="rh-muted">${m[key]}/5</span></td>`).join('');
    const total = COMPARE_LABELS.reduce((s, { key }) => s + (m[key] || 0), 0);
    return `<tr class="${m.us ? 'rh-us' : ''}"><td>${esc(m.name)}</td>${cells}<td><strong>${total}/30</strong></td></tr>`;
  }).join('');
  const head = COMPARE_LABELS.map((c) => `<th>${c.label}</th>`).join('');
  return `
    <div class="rh-arch-hero"><h2>Stack vs industry</h2><p>Architecture scorecard — not verified live returns.</p></div>
    <table class="rh-compare-table"><thead><tr><th>System</th>${head}<th>Total</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="rh-chart-wrap"><canvas id="rh-compare-chart"></canvas></div>`;
}

function renderArenaBarChart(compare, operating) {
  const canvas = document.getElementById('rh-arena-bar');
  if (!canvas || typeof Chart === 'undefined' || !compare?.versionSummaries) return;
  const summaries = compare.versionSummaries;
  const labels = compare.versions || Object.keys(summaries);
  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Mean cum %',
        data: labels.map((v) => Number(summaries[v]?.meanCumulativePct ?? 0)),
        backgroundColor: labels.map((v) => {
          if (v === 'v1' || v === 'v2') return 'rgba(156,163,175,0.7)';
          if (v === operating?.champion) return 'rgba(255,149,0,0.9)';
          return 'rgba(168,85,247,0.7)';
        }),
      }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { y: { ticks: { color: '#9aa3c0' }, grid: { color: 'rgba(90,110,170,0.12)' } },
        x: { ticks: { color: '#9aa3c0' }, grid: { display: false } } } },
  });
  _chartInstances.push(chart);
}

function renderArenaEquityChart(compare, operating) {
  const canvas = document.getElementById('rh-arena-equity');
  if (!canvas || typeof Chart === 'undefined' || !compare?.dates?.length) return;
  const active = new Set(operating?.pulseVersions || ['v1', 'v2', 'v3']);
  const palette = ['#9ca3af', '#22c55e', '#a855f7', '#ff9500'];
  const datasets = (compare.versions || []).filter((v) => active.has(v) && compare[`${v}EquityIndex`]).map((v, i) => ({
    label: v, data: compare[`${v}EquityIndex`], borderColor: palette[i % palette.length],
    borderWidth: 2, tension: 0.25, pointRadius: 0,
  }));
  if (!datasets.length) return;
  const chart = new Chart(canvas, {
    type: 'line',
    data: { labels: compare.dates, datasets },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#9aa3c0' } } },
      scales: { y: { ticks: { color: '#9aa3c0' }, grid: { color: 'rgba(90,110,170,0.12)' } },
        x: { ticks: { color: '#9aa3c0', maxTicksLimit: 8 }, grid: { display: false } } } },
  });
  _chartInstances.push(chart);
}

function renderWalkforwardChart(cc) {
  const canvas = document.getElementById('rh-wf-holdout');
  const lab = cc?.madScientistLab;
  if (!canvas || typeof Chart === 'undefined' || !lab?.leaderboard?.length) return;
  const lb = lab.leaderboard.slice(0, 10);
  const labels = lb.map((r) => r.id || r.genomeId || '?');
  const data = lb.map((r) => Number(r.holdSharpe ?? 0));
  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Holdout Sharpe',
        data,
        backgroundColor: data.map((_, i) => {
          const t = i / Math.max(1, data.length - 1);
          const r = Math.round(156 - t * 60 + t * t * 99);
          const g = Math.round(163 - t * 80 + t * t * 20);
          const b = Math.round(175 - t * 120);
          return `rgba(${r},${g},${b},0.88)`;
        }),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: 'Top genomes — holdout Sharpe (grey → legendary orange = rank)', color: '#9aa3c0', font: { size: 11 } },
      },
      scales: {
        y: { ticks: { color: '#9aa3c0' }, grid: { color: 'rgba(90,110,170,0.12)' } },
        x: { ticks: { color: '#9aa3c0', maxRotation: 45, font: { size: 9 } }, grid: { display: false } },
      },
    },
  });
  _chartInstances.push(chart);
}

function renderCompareRadar() {
  const canvas = document.getElementById('rh-compare-chart');
  if (!canvas || typeof Chart === 'undefined') return;
  const labels = COMPARE_LABELS.map((c) => c.label);
  const nostra = COMPARE_MODELS.find((m) => m.us);
  const ds = (row) => COMPARE_LABELS.map(({ key }) => row[key]);
  const chart = new Chart(canvas, {
    type: 'radar',
    data: {
      labels,
      datasets: [
        { label: 'Treasure Droid', data: ds(nostra), borderColor: '#ff9500', backgroundColor: 'rgba(255,149,0,0.14)', borderWidth: 2 },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false,
      scales: { r: { min: 0, max: 5, ticks: { color: '#6b7280' }, grid: { color: 'rgba(90,110,170,0.15)' }, pointLabels: { color: '#9aa3c0', font: { size: 10 } } } },
      plugins: { legend: { labels: { color: '#9aa3c0' } } } },
  });
  _chartInstances.push(chart);
}

function bindDetailTabs(container) {
  const root = container.querySelector('#td-arch-detail-tabs');
  if (!root) return;
  root.querySelectorAll('[data-detail-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.detailTab;
      root.querySelectorAll('[data-detail-tab]').forEach((b) => b.classList.toggle('td-arch-detail-tab--active', b.dataset.detailTab === id));
      root.querySelectorAll('[data-detail-panel]').forEach((p) => { p.hidden = p.dataset.detailPanel !== id; });
    });
  });
}

function schematicsHtml(data) {
  return `
    <section class="td-mega-showcase" aria-label="Pipeline mega map">
      <div class="td-mega-showcase__glow" aria-hidden="true"></div>
      <header class="td-mega-showcase__head">
        <div>
          <p class="td-mega-showcase__eyebrow">Stack & Edge</p>
          <h2 class="td-mega-showcase__title">The transformation pipeline</h2>
        </div>
        ${colorLegendHtml()}
      </header>
      <div id="td-mega-wrap" class="td-mega-wrap td-mega-wrap--hero" aria-label="Mega pipeline map"></div>
      <p class="td-mega-showcase__hint">Hover any node — edges light up along the grey → green → purple → orange story</p>
    </section>

    <aside id="td-mega-tip" class="td-mega-tip td-mega-tip--dock">${tooltipHtml(nodeById('live_panel'))}</aside>`;
}

function schematicsDetailHtml(data) {
  return `
    <nav id="td-arch-detail-tabs" class="td-arch-detail-tabs" aria-label="Deep dive sections">
      <button type="button" class="td-arch-detail-tab td-arch-detail-tab--active" data-detail-tab="ml">ML models & equations</button>
      <button type="button" class="td-arch-detail-tab" data-detail-tab="mad">Mad Scientist</button>
      <button type="button" class="td-arch-detail-tab" data-detail-tab="walk">8yr / 2yr walk-forward</button>
      <button type="button" class="td-arch-detail-tab" data-detail-tab="loops">Recursive learning</button>
      <button type="button" class="td-arch-detail-tab" data-detail-tab="ops">Live ops</button>
    </nav>
    <div data-detail-panel="ml" class="td-arch-detail-panel">${mlModelsHtml()}</div>
    <div data-detail-panel="mad" class="td-arch-detail-panel" hidden>${madScientistHtml(data.commandCenter)}</div>
    <div data-detail-panel="walk" class="td-arch-detail-panel" hidden>${walkforwardHtml(data.commandCenter, data.walkforward)}</div>
    <div data-detail-panel="loops" class="td-arch-detail-panel" hidden>${recursiveLoopsHtml()}</div>
    <div data-detail-panel="ops" class="td-arch-detail-panel" hidden>${opsTabHtml(data)}</div>`;
}

export async function renderArchitecture(container, route = {}) {
  const sub = route.sub || (location.hash.includes('/brain') ? 'brain'
    : location.hash.includes('/compare') ? 'compare' : 'system');
  container.innerHTML = '<div class="rh-loading">Loading schematics…</div>';
  destroyCharts();

  const [data, brain] = await Promise.all([
    fetchStackData(),
    sub === 'brain' ? fetchBrainInsights().catch(() => ({ backtests: [], devChangelog: [], harness: {} })) : null,
  ]);

  container.innerHTML = `
    <div class="rh-arch-page ${sub === 'system' ? 'rh-arch-page--showcase' : ''}">
      ${sub === 'system' ? schematicsHtml(data) : ''}
      <nav class="rh-arch-subnav" aria-label="Architecture sections">
        <button type="button" data-arch-sub="system" class="${sub === 'system' ? 'rh-arch-subnav--active' : ''}">Schematics</button>
        <button type="button" data-arch-sub="brain" class="${sub === 'brain' ? 'rh-arch-subnav--active' : ''}">Brain logs</button>
        <button type="button" data-arch-sub="compare" class="${sub === 'compare' ? 'rh-arch-subnav--active' : ''}">Industry compare</button>
      </nav>
      <div id="rh-arch-panel">${sub === 'compare' ? compareTabHtml(data)
    : sub === 'brain' ? brainLogsHtml(brain || {})
      : schematicsDetailHtml(data)}</div>
    </div>`;

  container.querySelectorAll('[data-arch-sub]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const s = btn.dataset.archSub;
      location.hash = s === 'compare' ? '#/architecture/compare'
        : s === 'brain' ? '#/architecture/brain' : '#/architecture';
    });
  });

  if (sub === 'compare') {
    renderCompareRadar();
  } else if (sub === 'brain') {
    bindBrainLogsTabs(container);
  } else {
    const tip = container.querySelector('#td-mega-tip');
    const wrap = container.querySelector('#td-mega-wrap');
    if (wrap) {
      renderMegaChart(wrap, {
        onSelect: (node) => { if (tip) tip.innerHTML = tooltipHtml(node); },
      });
    }
    bindDetailTabs(container);
    renderArenaBarChart(data.compare, data.operating);
    renderArenaEquityChart(data.compare, data.operating);
    renderWalkforwardChart(data.commandCenter);
  }
}
