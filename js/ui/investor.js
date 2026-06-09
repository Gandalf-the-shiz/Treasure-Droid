/**
 * js/ui/investor.js
 * Investor Agent (v3) — "What is the bot doing, and why?" pane.
 *
 * Renders the rich decisions.json artefact produced by
 *   scripts/train-investor-v3.py
 * as a single-pane day-by-day cockpit:
 *
 *   - KPI strip (equity, return, Sharpe, max DD, win rate, trades)
 *   - Equity curve sparkline with marker on the active day
 *   - Day strip / playback controls (◀ ▶, slider, ▶ Play)
 *   - Today's picks as cards (allocation, conviction, expected vs realised,
 *     30-day price spark, reasoning bullets, outcome tag)
 *   - Sector exposure summary
 *   - Settlement panel ("what closed today and for how much")
 *
 * Lazy-loaded by app.js when the user opens the "🤖 Investor" tab.
 *
 * Export: renderInvestorUI(container)
 */

import { formatCurrency, formatPercent, escapeHtml, showToast } from '../utils/helpers.js';

// ─── Module state ─────────────────────────────────────────────

let _data = null;          // parsed decisions.json
let _dayIndex = 0;         // currently visible day
let _equityChart = null;
let _playTimer = null;
let _backend = null;       // /api/health response when local server is up
let _retrainPoller = null;
let _bookOptions = {};
const SPARK_DAYS = 30;     // days of price history rendered in each pick card

// ─── Public API ───────────────────────────────────────────────

/**
 * Shared book UI (KPIs, equity curve, day playback, pick cards).
 * @param {object} options - { title, subtitle, showRetrain, showCommandCenter, breadcrumbHtml }
 */
export async function renderInvestorBook(container, data, options = {}) {
  _bookOptions = options;
  _data = data;
  container.innerHTML = '';

  if (options.breadcrumbHtml) {
    const nav = document.createElement('div');
    nav.className = 'inv-breadcrumb';
    nav.innerHTML = options.breadcrumbHtml;
    container.appendChild(nav);
  }

  const title = document.createElement('h2');
  title.className = 'inv-title';
  title.textContent = options.title || '🤖 Investor Agent';
  container.appendChild(title);

  const subtitle = document.createElement('p');
  subtitle.className = 'inv-subtitle';
  subtitle.textContent = options.subtitle ||
    'Day-by-day fake-dollar decisions. Each card shows sizing, conviction, reasoning, and outcomes where known.';
  container.appendChild(subtitle);

  const days = _data.days || [];
  if (!days.length) {
    container.appendChild(_errorBlock('No trading days in this book.'));
    return;
  }
  _dayIndex = days.length - 1;
  for (let i = days.length - 1; i >= 0; i--) {
    if ((days[i].picks || []).length > 0) { _dayIndex = i; break; }
  }

  const grid = document.createElement('div');
  grid.className = 'inv-grid';
  grid.innerHTML = `
    <section class="inv-refresh-bar" id="inv-refresh-bar"></section>
    ${options.showCommandCenter !== false ? '<section class="inv-cc" id="inv-cc"></section>' : ''}
    <section class="inv-kpis" id="inv-kpis"></section>
    <section class="inv-equity-card">
      <div class="inv-card-header">
        <h3>Equity Curve</h3>
        <span class="inv-card-sub" id="inv-equity-sub"></span>
      </div>
      <div class="inv-equity-wrap"><canvas id="inv-equity-chart" height="160"></canvas></div>
    </section>
    <section class="inv-day-controls">
      <button class="inv-btn" id="inv-prev"  aria-label="Previous day">◀</button>
      <button class="inv-btn" id="inv-play"  aria-label="Play through days">▶ Play</button>
      <button class="inv-btn" id="inv-next"  aria-label="Next day">▶</button>
      <button class="inv-btn" id="inv-jump-trade" title="Jump to next day with picks">↷ Next pick day</button>
      <input  class="inv-slider" id="inv-slider" type="range" min="0" max="${days.length - 1}" value="${_dayIndex}" />
      <span class="inv-date-label" id="inv-date-label"></span>
    </section>
    <section class="inv-day-summary" id="inv-day-summary"></section>
    <section class="inv-picks" id="inv-picks"></section>
    <section class="inv-meta">
      <details class="inv-config">
        <summary>Configuration & methodology</summary>
        <div id="inv-config-body"></div>
      </details>
    </section>
  `;
  container.appendChild(grid);

  _renderKpis();
  _renderEquityChart();
  _renderConfigPanel();
  _wireControls(days);
  _renderDay();
  _renderRefreshBar();
  if (options.showCommandCenter !== false) _renderCommandCenter();
}

export async function renderInvestorUI(container) {
  container.innerHTML = '';
  const status = document.createElement('div');
  status.className = 'inv-status';
  status.textContent = 'Loading decisions…';
  container.appendChild(status);

  _backend = null;
  try {
    const h = await fetch('/api/health', { cache: 'no-cache' });
    if (h.ok) _backend = await h.json();
  } catch (_) { /* no local server */ }

  const url = _backend ? '/api/decisions' : 'data/investor_v3/decisions.json';
  try {
    const resp = await fetch(url, { cache: 'no-cache' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    status.remove();
    await renderInvestorBook(container, data, {
      title: '🔮 Investor Agent (v3)',
      subtitle:
        'Watch the v3 investor make day-by-day fake-dollar decisions. Each card shows what was bought, ' +
        'how much, the model\'s reasoning, and (where available) the realised outcome.',
      showRetrain: true,
      showCommandCenter: true,
    });
  } catch (err) {
    status.innerHTML =
      `<div class="inv-error">Could not load decisions from <code>${escapeHtml(url)}</code>: ${escapeHtml(String(err.message || err))}.<br>` +
      `Re-run <code>scripts/train-investor-v3.py</code> (or start the local server: <code>python scripts/serve.py</code>).</div>`;
  }
}

// ─── Command Center ───────────────────────────────────────────
//
// Single-pane synthesis: what is the bot holding RIGHT NOW, what is the
// strategy, what is the recent tape, and what is the prevailing reasoning.

function _computePortfolioState() {
  const days = _data.days || [];
  const ph = _data.price_history || {};
  const open = new Map();
  const events = [];
  const recentSettled = [];
  for (const day of days) {
    for (const s of (day.settled || [])) {
      events.push({ date: day.date, type: 'SETTLE', symbol: s.symbol, pnl: s.pnl, ret: s.ret });
      open.delete(s.symbol);
      recentSettled.push(s.ret);
    }
    for (const p of (day.picks || [])) {
      events.push({ date: day.date, type: 'OPEN', symbol: p.symbol, pick: p });
      open.set(p.symbol, { open_date: day.date, pick: p });
    }
  }
  const openPositions = [];
  for (const [, info] of open) {
    const hist = ph[info.pick.symbol] || [];
    const last = hist.length ? hist[hist.length - 1] : null;
    const lastClose = last ? last.close : info.pick.entry_price;
    const unrealizedRet = (lastClose - info.pick.entry_price) / info.pick.entry_price;
    openPositions.push({
      ...info.pick,
      open_date: info.open_date,
      last_close: lastClose,
      last_date: last ? last.date : info.open_date,
      unrealized_ret: unrealizedRet,
      unrealized_pnl: info.pick.notional * unrealizedRet,
    });
  }
  openPositions.sort((a, b) => b.weight - a.weight);
  return { openPositions, events, recentSettled: recentSettled.slice(-10) };
}

function _renderCommandCenter() {
  const el = document.getElementById('inv-cc');
  if (!el) return;
  const days = _data.days || [];
  const latest = days[days.length - 1] || {};
  const cfg = _data.config || {};
  const { openPositions, events, recentSettled } = _computePortfolioState();
  const grossExposure = openPositions.reduce((a, p) => a + p.notional, 0);
  const equity = latest.equity || _data.summary?.ending_cash || 0;
  const cash = latest.cash != null ? latest.cash : (equity - grossExposure);
  const exposurePct = equity > 0 ? (grossExposure / equity) * 100 : 0;

  const sentScores = openPositions.map(p => p.sentiment).filter(s => s && s.n_headlines);
  let portSent = null;
  if (sentScores.length) {
    const wsum = openPositions.reduce((a, p) => a + (p.sentiment && p.sentiment.n_headlines ? p.weight : 0), 0);
    const ssum = openPositions.reduce((a, p) => a + (p.sentiment && p.sentiment.n_headlines ? p.weight * p.sentiment.score : 0), 0);
    portSent = wsum > 0 ? ssum / wsum : null;
  }

  const wins = recentSettled.filter(r => r > 0).length;
  const losses = recentSettled.filter(r => r <= 0).length;
  const streakLabel = recentSettled.length ? `${wins}W / ${losses}L (last 10)` : 'no recent trades';

  const ph = _data.price_history || {};
  let lastBarDate = null;
  for (const sym of Object.keys(ph)) {
    const arr = ph[sym];
    if (arr && arr.length) {
      const d = arr[arr.length - 1].date;
      if (!lastBarDate || d > lastBarDate) lastBarDate = d;
    }
  }
  const today = new Date().toISOString().slice(0, 10);
  const stale = lastBarDate && lastBarDate < today;
  const stalenessDays = lastBarDate ? Math.max(0, Math.round((Date.parse(today) - Date.parse(lastBarDate)) / 86400000)) : null;

  const sentChip = portSent == null
    ? `<span class="inv-cc__chip neu">no sentiment</span>`
    : (() => {
        const cls = portSent > 0.15 ? 'pos' : portSent < -0.15 ? 'neg' : 'neu';
        const sign = portSent > 0 ? '+' : '';
        return `<span class="inv-cc__chip ${cls}">${sign}${portSent.toFixed(2)}</span>`;
      })();
  const totalRet = _data.summary?.total_return_pct || 0;
  const equityCls = totalRet >= 0 ? 'pos' : 'neg';

  const nowStrip = `
    <div class="inv-cc__now">
      <div class="inv-cc__stat">
        <span class="lbl">Portfolio equity</span>
        <span class="val ${equityCls}">${formatCurrency(equity)}</span>
        <span class="sub">${formatPercent(totalRet)} since inception</span>
      </div>
      <div class="inv-cc__stat">
        <span class="lbl">Cash on hand</span>
        <span class="val">${formatCurrency(cash)}</span>
        <span class="sub">${(100 - exposurePct).toFixed(0)}% of equity</span>
      </div>
      <div class="inv-cc__stat">
        <span class="lbl">Open positions</span>
        <span class="val">${openPositions.length}</span>
        <span class="sub">gross ${exposurePct.toFixed(0)}% / cap ${((cfg.max_gross_exposure || 0) * 100).toFixed(0)}%</span>
      </div>
      <div class="inv-cc__stat">
        <span class="lbl">Portfolio sentiment</span>
        <span class="val">${sentChip}</span>
        <span class="sub">FinBERT, weighted by size</span>
      </div>
      <div class="inv-cc__stat">
        <span class="lbl">Recent streak</span>
        <span class="val">${streakLabel}</span>
        <span class="sub">${(_data.summary?.win_rate_pct || 0).toFixed(0)}% overall</span>
      </div>
      <div class="inv-cc__stat inv-cc__stat--freshness ${stale ? 'warn' : 'ok'}">
        <span class="lbl">Data freshness</span>
        <span class="val">${lastBarDate || 'n/a'}</span>
        <span class="sub">${stale ? `${stalenessDays}d behind today` : 'current'}</span>
      </div>      ${_renderPipelineStat()}    </div>
  `;

  let portfolioBlock = '';
  if (openPositions.length) {
    portfolioBlock = `
      <div class="inv-cc__portfolio">
        <h3>Live portfolio <span class="inv-muted">— what the agent holds right now</span></h3>
        <table class="inv-cc__table">
          <thead><tr>
            <th>Sym</th><th>Sector</th><th class="num">Weight</th>
            <th class="num">Entry → last</th><th class="num">Unrealized</th>
            <th class="num">Conv</th><th>News</th><th>Top reason</th>
          </tr></thead>
          <tbody>
            ${openPositions.map(p => {
              const ucls = p.unrealized_ret > 0 ? 'pos' : p.unrealized_ret < 0 ? 'neg' : '';
              const s = p.sentiment;
              const sChip = (s && s.n_headlines)
                ? (() => {
                    const cls = s.label === 'positive' ? 'pos' : s.label === 'negative' ? 'neg' : 'neu';
                    const sign = s.score > 0 ? '+' : '';
                    return `<span class="inv-cc__chip ${cls}" title="${escapeHtml(s.n_headlines + ' headlines')}">${s.label} ${sign}${s.score.toFixed(2)}</span>`;
                  })()
                : `<span class="inv-cc__chip neu">—</span>`;
              const topReason = (p.why && p.why[0]) ? p.why[0] : '—';
              return `
                <tr>
                  <td class="sym">${escapeHtml(p.symbol)}<div class="sub">opened ${p.open_date}</div></td>
                  <td>${escapeHtml(p.sector || '')}</td>
                  <td class="num">${(p.weight * 100).toFixed(1)}%<div class="sub">${formatCurrency(p.notional)}</div></td>
                  <td class="num">$${p.entry_price.toFixed(2)} → $${p.last_close.toFixed(2)}</td>
                  <td class="num ${ucls}">${formatPercent(p.unrealized_ret * 100)}<div class="sub">${formatCurrency(p.unrealized_pnl)}</div></td>
                  <td class="num">${(p.pred_proba_up * 100).toFixed(0)}%</td>
                  <td>${sChip}</td>
                  <td class="reason">${escapeHtml(topReason)}</td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;
  } else {
    const recentPickDays = days.slice().reverse().filter(d => (d.picks || []).length).slice(0, 1);
    const recentPicks = recentPickDays.length ? recentPickDays[0].picks : [];
    portfolioBlock = `
      <div class="inv-cc__portfolio inv-cc__portfolio--empty">
        <h3>Live portfolio</h3>
        <div class="inv-cc__cash-state">
          <div class="inv-cc__cash-icon">💵</div>
          <div>
            <div class="inv-cc__cash-headline">Fully in cash</div>
            <div class="inv-cc__cash-sub">
              No open positions. The agent is waiting for a signal that clears
              <strong>${((cfg.min_proba || 0) * 100).toFixed(0)}%</strong> probability and
              <strong>${((cfg.min_pred_ret || 0) * 100).toFixed(1)}%</strong> predicted return.
              ${recentPickDays.length ? `Last activity <strong>${recentPickDays[0].date}</strong>: ${recentPicks.map(p => escapeHtml(p.symbol)).join(', ')}.` : ''}
            </div>
          </div>
        </div>
      </div>`;
  }

  const exclude = (cfg.exclude_pattern || '').slice(0, 60);
  const strategyBlock = `
    <div class="inv-cc__strategy">
      <h3>Strategy in play</h3>
      <ul class="inv-cc__strat-list">
        <li><span>Top-K per day</span><strong>${cfg.top_k ?? '—'}</strong></li>
        <li><span>Max position</span><strong>${((cfg.max_position_frac || 0) * 100).toFixed(0)}%</strong></li>
        <li><span>Max gross exposure</span><strong>${((cfg.max_gross_exposure || 0) * 100).toFixed(0)}%</strong></li>
        <li><span>Kelly scale</span><strong>${(cfg.kelly_scale ?? 0).toFixed(2)}×</strong></li>
        <li><span>Min P(up)</span><strong>${((cfg.min_proba || 0) * 100).toFixed(0)}%</strong></li>
        <li><span>Min pred. return</span><strong>${((cfg.min_pred_ret || 0) * 100).toFixed(1)}%</strong></li>
        <li><span>Min 20d vol</span><strong>${((cfg.min_vol_20 || 0) * 100).toFixed(1)}%</strong></li>
        <li><span>Cost / slip</span><strong>${cfg.cost_bps ?? 0} / ${cfg.slippage_bps ?? 0} bps</strong></li>
        <li><span>Policy mode</span><strong>${escapeHtml(cfg.policy_mode || 'edge')}</strong></li>
      </ul>
      <div class="inv-cc__strat-foot">excludes <code>${escapeHtml(exclude)}${(cfg.exclude_pattern || '').length > 60 ? '…' : ''}</code></div>
    </div>
  `;

  const tape = events.slice(-12).reverse().map(e => {
    if (e.type === 'OPEN') {
      return `<li class="inv-cc__ev open">
        <span class="dot"></span>
        <span class="date">${e.date}</span>
        <span class="kind">OPEN</span>
        <span class="sym">${escapeHtml(e.symbol)}</span>
        <span class="meta">conv ${(e.pick.pred_proba_up * 100).toFixed(0)}% · ${(e.pick.weight * 100).toFixed(1)}%</span>
      </li>`;
    }
    const cls = e.ret > 0 ? 'win' : 'loss';
    return `<li class="inv-cc__ev settle ${cls}">
      <span class="dot"></span>
      <span class="date">${e.date}</span>
      <span class="kind">${e.ret > 0 ? 'WIN' : 'LOSS'}</span>
      <span class="sym">${escapeHtml(e.symbol)}</span>
      <span class="meta">${formatPercent(e.ret * 100)} · ${formatCurrency(e.pnl)}</span>
    </li>`;
  }).join('');
  const tapeBlock = `
    <div class="inv-cc__tape">
      <h3>Recent trade tape</h3>
      ${events.length ? `<ul class="inv-cc__tape-list">${tape}</ul>` : `<div class="inv-cc__empty">No trades yet.</div>`}
    </div>`;

  const recentDaysSlice = days.slice(-90);
  const reasonCounts = new Map();
  let totalReasonsSeen = 0;
  let pickCount = 0;
  for (const d of recentDaysSlice) {
    for (const p of (d.picks || [])) {
      pickCount += 1;
      for (const w of (p.why || [])) {
        const key = w.replace(/[-+]?\d+(?:\.\d+)?%?/g, '#').replace(/\$[\d.,]+/g, '$#');
        reasonCounts.set(key, (reasonCounts.get(key) || 0) + 1);
        totalReasonsSeen += 1;
      }
    }
  }
  const topReasons = [...reasonCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  const maxReason = topReasons.length ? topReasons[0][1] : 1;
  const reasoningBlock = `
    <div class="inv-cc__reasoning">
      <h3>Reasoning patterns <span class="inv-muted">— last ${recentDaysSlice.length} days</span></h3>
      ${topReasons.length ? `
        <ul class="inv-cc__reason-list">
          ${topReasons.map(([txt, n]) => `
            <li>
              <div class="inv-cc__reason-bar"><div class="fill" style="width:${(n / maxReason * 100).toFixed(0)}%"></div></div>
              <div class="inv-cc__reason-row">
                <span class="txt">${escapeHtml(txt)}</span>
                <span class="cnt">${n}×</span>
              </div>
            </li>`).join('')}
        </ul>
        <div class="inv-cc__reason-foot">${totalReasonsSeen} reasons across ${pickCount} picks</div>
      ` : `<div class="inv-cc__empty">No picks in the last ${recentDaysSlice.length} days.</div>`}
    </div>`;

  el.innerHTML = `
    <header class="inv-cc__header">
      <div>
        <h2 class="inv-cc__title">Command Center</h2>
        <p class="inv-cc__subtitle">Single pane of glass — current portfolio, active strategy, recent trades, and why the agent is making its calls.</p>
      </div>
    </header>
    ${nowStrip}
    <div class="inv-cc__main">
      ${portfolioBlock}
      ${strategyBlock}
    </div>
    <div class="inv-cc__insights">
      ${tapeBlock}
      ${reasoningBlock}
    </div>
  `;
}

// ─── Pipeline status (server-side) ────────────────────────────

function _renderPipelineStat() {
  const p = _backend?.pipeline;
  if (!p) {
    return `
      <div class="inv-cc__stat inv-cc__stat--pipeline warn">
        <span class="lbl">Pipeline</span>
        <span class="val">offline</span>
        <span class="sub">start the local server</span>
      </div>
    `;
  }
  const ln = p.last_nightly || {};
  const ranOk = ln.exists && ln.train_rc === 0;
  const fetchOk = ln.fetch_rc === 0;
  const enrichOk = ln.enrich_rc === 0;
  let cls = 'ok';
  let val = 'healthy';
  let sub = '';
  if (!ln.exists) {
    cls = 'warn';
    val = 'never run';
    sub = 'M-F at 17:30 local';
  } else {
    const when = ln.modified_at ? new Date(ln.modified_at).toLocaleString() : '';
    if (!ranOk) {
      cls = 'warn';
      val = 'train failed';
      sub = when;
    } else {
      const parts = [
        `fetch ${fetchOk ? 'OK' : 'fail'}`,
        `train OK`,
        `enrich ${enrichOk ? 'OK' : 'skipped'}`,
      ];
      val = 'last run OK';
      sub = `${when} — ${parts.join(' / ')}`;
      if (!fetchOk) cls = 'warn';
    }
  }
  const modelAge = p.model?.modified_at
    ? `model ${_formatRelative(p.model.modified_at)}`
    : 'no model on disk';
  return `
    <div class="inv-cc__stat inv-cc__stat--pipeline ${cls}">
      <span class="lbl">Pipeline</span>
      <span class="val">${val}</span>
      <span class="sub">${sub || modelAge}</span>
    </div>
  `;
}

// ─── KPI strip ────────────────────────────────────────────────

function _renderKpis() {
  const s = _data.summary || {};
  const cfg = _data.config || {};
  const totalRet = s.total_return_pct || 0;
  const meta = _data._arenaMeta;
  const items = [
    { label: 'Equity',        value: formatCurrency(s.ending_cash || 0),       sub: `start ${formatCurrency(s.starting_cash || 0)}` },
    { label: 'Total return',  value: formatPercent(totalRet),                  sub: `${s.trading_days || 0} pulse days`, cls: totalRet >= 0 ? 'pos' : 'neg' },
    { label: 'Sharpe',        value: s.annualized_sharpe != null ? Number(s.annualized_sharpe).toFixed(2) : '—',    sub: meta ? 'sim only' : 'annualised' },
    { label: 'Max drawdown',  value: formatPercent(s.max_drawdown_pct || 0),   sub: 'peak-to-trough', cls: 'neg' },
    { label: 'Win rate',      value: s.win_rate_pct != null ? `${Number(s.win_rate_pct).toFixed(1)}%` : '—',   sub: s.wins != null ? `${s.wins}W / ${s.losses}L` : (meta ? 'arena sim' : '') },
    { label: meta ? 'Pulse trades' : 'Trades', value: String(s.trades || 0),  sub: meta ? `${meta.version} genome` : `top-${cfg.top_k} / day` },
  ];
  const el = document.getElementById('inv-kpis');
  el.innerHTML = items.map(i => `
    <div class="inv-kpi">
      <div class="inv-kpi__label">${escapeHtml(i.label)}</div>
      <div class="inv-kpi__value ${i.cls || ''}">${escapeHtml(i.value)}</div>
      <div class="inv-kpi__sub">${escapeHtml(i.sub)}</div>
    </div>
  `).join('');
}

// ─── Equity curve ─────────────────────────────────────────────

function _renderEquityChart() {
  const canvas = document.getElementById('inv-equity-chart');
  if (!canvas || typeof window.Chart === 'undefined') return;
  const labels  = _data.equity_curve.map(p => p.date);
  const equity  = _data.equity_curve.map(p => p.equity);
  const start   = _data.summary.starting_cash || equity[0];
  const baseline = labels.map(() => start);

  _equityChart?.destroy();
  _equityChart = new window.Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Equity',
          data: equity,
          borderColor: '#22c55e',
          backgroundColor: 'rgba(34,197,94,0.12)',
          fill: true,
          pointRadius: 0,
          tension: 0.15,
          borderWidth: 2,
        },
        {
          label: 'Starting cash',
          data: baseline,
          borderColor: 'rgba(148,163,184,0.6)',
          borderDash: [4, 4],
          pointRadius: 0,
          borderWidth: 1,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { ticks: { maxTicksLimit: 6, autoSkip: true, color: '#94a3b8' }, grid: { display: false } },
        y: { ticks: { color: '#94a3b8', callback: (v) => `$${(v/1000).toFixed(1)}k` }, grid: { color: 'rgba(148,163,184,0.12)' } },
      },
    },
  });
}

function _markActiveDayOnChart() {
  if (!_equityChart) return;
  const day = _data.days[_dayIndex];
  const idx = _data.equity_curve.findIndex(e => e.date === day.date);
  const n = _data.equity_curve.length;
  const ds = _equityChart.data.datasets[0];
  ds.pointRadius   = _data.equity_curve.map((_, i) => i === idx ? 5 : 0);
  ds.pointBackgroundColor = _data.equity_curve.map((_, i) => i === idx ? '#fbbf24' : '#22c55e');
  _equityChart.update('none');
  const sub = document.getElementById('inv-equity-sub');
  if (sub) sub.textContent = `Day ${idx + 1} of ${n}`;
}

// ─── Day controls ─────────────────────────────────────────────

function _wireControls(days) {
  const prev = document.getElementById('inv-prev');
  const next = document.getElementById('inv-next');
  const play = document.getElementById('inv-play');
  const jump = document.getElementById('inv-jump-trade');
  const slider = document.getElementById('inv-slider');

  prev.addEventListener('click', () => { _setDay(_dayIndex - 1); });
  next.addEventListener('click', () => { _setDay(_dayIndex + 1); });
  jump.addEventListener('click', () => {
    for (let i = _dayIndex + 1; i < days.length; i++) {
      if ((days[i].picks || []).length > 0) { _setDay(i); return; }
    }
    showToast('No more days with picks.', 'info');
  });
  slider.addEventListener('input', (e) => { _setDay(parseInt(e.target.value, 10)); });
  play.addEventListener('click', () => _togglePlay(play));
}

function _togglePlay(btn) {
  if (_playTimer) {
    clearInterval(_playTimer);
    _playTimer = null;
    btn.textContent = '▶ Play';
    return;
  }
  btn.textContent = '⏸ Pause';
  _playTimer = setInterval(() => {
    if (_dayIndex >= _data.days.length - 1) {
      clearInterval(_playTimer); _playTimer = null; btn.textContent = '▶ Play';
      return;
    }
    _setDay(_dayIndex + 1);
  }, 350);
}

function _setDay(i) {
  i = Math.max(0, Math.min(_data.days.length - 1, i));
  _dayIndex = i;
  const slider = document.getElementById('inv-slider');
  if (slider) slider.value = String(i);
  _renderDay();
}

// ─── Day content ──────────────────────────────────────────────

function _renderDay() {
  const day = _data.days[_dayIndex];
  if (!day) return;

  // Date label
  const label = document.getElementById('inv-date-label');
  if (label) {
    const d = new Date(day.date + 'T00:00:00');
    const fmt = d.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
    label.innerHTML = `<strong>${escapeHtml(fmt)}</strong>` +
      `<span class="inv-date-sub"> · day ${_dayIndex + 1} of ${_data.days.length}</span>`;
  }

  // Day summary card
  const summaryEl = document.getElementById('inv-day-summary');
  const pnl = day.pnl_today || 0;
  const pnlCls = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '';
  const settled = day.settled || [];
  const settledHtml = settled.length
    ? `<div class="inv-settled">
         <h4>Settled today</h4>
         <ul>
           ${settled.map(s => `
             <li class="${s.pnl >= 0 ? 'pos' : 'neg'}">
               <span class="sym">${escapeHtml(s.symbol)}</span>
               <span class="ret">${formatPercent(s.ret * 100)}</span>
               <span class="pnl">${formatCurrency(s.pnl)}</span>
             </li>`).join('')}
         </ul>
       </div>`
    : `<div class="inv-settled inv-settled--empty">No positions to settle today.</div>`;

  const pulseExtra = _data._arenaMeta ? `
    <div class="inv-day-stat"><span class="lbl">Day return</span><span class="val ${pctClass(day.returnPct)}">${day.returnPct != null ? `${Number(day.returnPct).toFixed(2)}%` : '—'}</span></div>
    <div class="inv-day-stat"><span class="lbl">Long / short</span><span class="val">${day.nLong ?? 0} / ${day.nShort ?? 0}</span></div>
  ` : '';

  summaryEl.innerHTML = `
    <div class="inv-day-stat"><span class="lbl">Equity</span><span class="val">${formatCurrency(day.equity)}</span></div>
    <div class="inv-day-stat"><span class="lbl">Cash</span><span class="val">${formatCurrency(day.cash)}</span></div>
    <div class="inv-day-stat"><span class="lbl">P&amp;L today</span><span class="val ${pnlCls}">${formatCurrency(pnl)}</span></div>
    <div class="inv-day-stat"><span class="lbl">Eligible signals</span><span class="val">${day.eligible_count || 0}</span></div>
    <div class="inv-day-stat"><span class="lbl">New picks</span><span class="val">${(day.picks || []).length}</span></div>
    ${pulseExtra}
    ${settledHtml}
  `;

  if (day.reasoning) {
    summaryEl.insertAdjacentHTML('beforeend', `
      <div class="inv-pulse-reasoning">
        <h4>Pulse reasoning</h4>
        <div class="inv-pulse-reasoning__body">${escapeHtml(day.reasoning)}</div>
      </div>`);
  }

  // Picks
  const picksEl = document.getElementById('inv-picks');
  const picks = day.picks || [];
  if (!picks.length) {
    picksEl.innerHTML = `<div class="inv-empty">
      <h3>No new positions today.</h3>
      <p>${day.eligible_count > 0
        ? `${day.eligible_count} signal(s) passed the proba threshold but were filtered by score, min-pred-ret or sizing.`
        : `No signal cleared the 60% probability / 2% predicted-return floor today. The agent stays in cash.`}</p>
    </div>`;
    _markActiveDayOnChart();
    return;
  }

  // Sector exposure pill row
  const sectorAgg = {};
  for (const p of picks) sectorAgg[p.sector] = (sectorAgg[p.sector] || 0) + p.notional;
  const totalNotional = Object.values(sectorAgg).reduce((a, b) => a + b, 0);
  const sectorPills = Object.entries(sectorAgg)
    .sort((a, b) => b[1] - a[1])
    .map(([s, v]) => `<span class="inv-sector-pill">${escapeHtml(s)} <em>${((v / totalNotional) * 100).toFixed(0)}%</em></span>`)
    .join('');

  picksEl.innerHTML = `
    <div class="inv-picks-header">
      <h3>Today's picks <span class="inv-muted">— ranked by edge score</span></h3>
      <div class="inv-sector-row">${sectorPills}</div>
    </div>
    <div class="inv-pick-grid">
      ${picks.map((p, i) => _renderPickCard(p, i, day)).join('')}
    </div>
  `;

  // Draw sparklines after DOM insertion
  requestAnimationFrame(() => {
    for (const p of picks) _drawSparkline(p, day.date);
  });

  _markActiveDayOnChart();
}

function _renderPickCard(p, i, day) {
  const proba = p.pred_proba_up;
  const predRet = p.pred_ret;
  const realised = p.realised_ret;
  const realisedKnown = Number.isFinite(realised);
  const realisedCls = realisedKnown ? (realised > 0 ? 'pos' : 'neg') : '';
  const outcomeTag = realisedKnown
    ? `<span class="inv-outcome ${realised > 0 ? 'win' : 'loss'}">${realised > 0 ? 'WIN' : 'LOSS'} ${formatPercent(realised * 100)}</span>`
    : '';
  const why = (p.why || []).map(line => `<li>${escapeHtml(line)}</li>`).join('');
  const sentChip = _renderSentimentChip(p.sentiment);
  const sentBlock = _renderSentimentDetails(p.sentiment);
  const sparkId = `inv-spark-${day.date.replace(/-/g, '')}-${p.symbol.replace(/[^A-Z0-9]/gi, '')}-${i}`;
  return `
    <article class="inv-pick" data-symbol="${escapeHtml(p.symbol)}">
      <header class="inv-pick__head">
        <div class="inv-pick__id">
          <span class="inv-rank">#${p.rank}</span>
          <span class="inv-sym">${escapeHtml(p.symbol)}</span>
          ${p.side ? `<span class="inv-side-tag">${escapeHtml(p.side)}</span>` : ''}
          <span class="inv-sector">${escapeHtml(p.sector)}</span>
        </div>
        ${sentChip}${outcomeTag}
      </header>
      <div class="inv-pick__alloc">
        <div class="inv-alloc-bar"><div class="inv-alloc-fill" style="width:${Math.min(100, p.weight * 100).toFixed(1)}%"></div></div>
        <div class="inv-alloc-text">${formatCurrency(p.notional)} <span class="inv-muted">(${(p.weight * 100).toFixed(1)}% of equity)</span></div>
      </div>
      <div class="inv-pick__metrics">
        <div class="inv-metric">
          <span class="lbl">Conviction</span>
          <div class="inv-gauge"><div class="inv-gauge-fill" style="width:${(proba * 100).toFixed(1)}%"></div></div>
          <span class="val">${(proba * 100).toFixed(1)}%</span>
        </div>
        <div class="inv-metric">
          <span class="lbl">Predicted ${realisedKnown ? '/ realised' : ''}</span>
          <span class="val">
            <span class="pred">${formatPercent(predRet * 100)}</span>
            ${realisedKnown ? `<span class="sep">→</span><span class="real ${realisedCls}">${formatPercent(realised * 100)}</span>` : ''}
          </span>
        </div>
        <div class="inv-metric">
          <span class="lbl">Edge score</span>
          <span class="val">${(p.edge * 100).toFixed(3)}%</span>
        </div>
        <div class="inv-metric">
          <span class="lbl">20d vol · ADV</span>
          <span class="val small">${(p.vol_20 * 100).toFixed(2)}% · $${(p.adv_20 / 1e6).toFixed(1)}M</span>
        </div>
      </div>
      <div class="inv-pick__spark">
        <canvas id="${sparkId}" height="60"></canvas>
        <div class="inv-spark-cap">Last ${SPARK_DAYS} trading days · entry $${p.entry_price.toFixed(2)}</div>
      </div>
      <details class="inv-pick__why">
        <summary>Why this pick</summary>
        <ul>${why}</ul>
      </details>
      ${sentBlock}
    </article>
  `;
}

function _renderSentimentChip(s) {
  if (!s || !s.n_headlines) return '';
  const cls = s.label === 'positive' ? 'pos' : s.label === 'negative' ? 'neg' : 'neu';
  const sign = s.score > 0 ? '+' : '';
  const tip = `News sentiment ${s.label} (${s.n_headlines} headlines, mean ${sign}${s.score.toFixed(2)})`;
  return `<span class="inv-sent inv-sent--${cls}" title="${escapeHtml(tip)}">
      <span class="inv-sent__dot"></span>
      <span class="inv-sent__label">${s.label}</span>
      <span class="inv-sent__score">${sign}${s.score.toFixed(2)}</span>
    </span>`;
}

function _renderSentimentDetails(s) {
  if (!s || !s.n_headlines) return '';
  const items = (s.headlines || []).slice(0, 5).map(h => {
    const cls = h.label === 'positive' ? 'pos' : h.label === 'negative' ? 'neg' : 'neu';
    const sign = h.score > 0 ? '+' : '';
    return `<li class="inv-headline inv-headline--${cls}">
        <span class="inv-headline__score">${sign}${h.score.toFixed(2)}</span>
        <span class="inv-headline__title">${escapeHtml(h.title)}</span>
      </li>`;
  }).join('');
  return `<details class="inv-pick__news">
      <summary>News &amp; sentiment <span class="inv-muted">(${s.n_headlines} headlines)</span></summary>
      <ul class="inv-headlines">${items}</ul>
    </details>`;
}

function _drawSparkline(pick, entryDate) {
  const sparkId = `inv-spark-${entryDate.replace(/-/g, '')}-${pick.symbol.replace(/[^A-Z0-9]/gi, '')}-`;
  // we suffix with rank index; find by prefix
  const canvas = document.querySelector(`canvas[id^="${CSS.escape(sparkId)}"]`);
  if (!canvas || typeof window.Chart === 'undefined') return;
  const history = (_data.price_history || {})[pick.symbol] || [];
  if (!history.length) return;
  // Take bars up to & including entry date, then last SPARK_DAYS
  const upto = history.filter(b => b.date <= entryDate);
  const slice = upto.slice(-SPARK_DAYS);
  if (!slice.length) return;
  const labels = slice.map(b => b.date);
  const closes = slice.map(b => b.close);
  const entryIdx = slice.length - 1;
  // tear down any prior chart on this canvas
  if (canvas._chart) { canvas._chart.destroy(); canvas._chart = null; }
  const ctx = canvas.getContext('2d');
  const trend = closes[closes.length - 1] >= closes[0];
  const color = trend ? '#22c55e' : '#ef4444';
  canvas._chart = new window.Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: closes,
        borderColor: color,
        backgroundColor: color + '22',
        fill: true,
        tension: 0.2,
        borderWidth: 1.5,
        pointRadius: closes.map((_, i) => i === entryIdx ? 4 : 0),
        pointBackgroundColor: closes.map((_, i) => i === entryIdx ? '#fbbf24' : color),
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        callbacks: { label: (ctx) => `${ctx.label}: $${ctx.parsed.y.toFixed(2)}` },
      } },
      scales: { x: { display: false }, y: { display: false } },
      elements: { point: { hoverRadius: 5 } },
    },
  });
}

// ─── Config / methodology panel ───────────────────────────────

function pctClass(v) {
  const n = Number(v);
  if (Number.isNaN(n) || v == null) return '';
  return n > 0 ? 'pos' : n < 0 ? 'neg' : '';
}

function _renderConfigPanel() {
  const body = document.getElementById('inv-config-body');
  if (!body) return;
  const c = _data.config || {};
  const meta = _data._arenaMeta;
  const genomeExtra = meta ? `
    <h4>Arena genome (${escapeHtml(meta.version)} · trader ${escapeHtml(meta.traderId)})</h4>
    <table class="inv-config-tbl"><tbody>
      ${Object.entries(meta.genome || {}).filter(([, v]) => v != null).map(([k, v]) =>
        `<tr><td>${escapeHtml(k)}</td><td><code>${escapeHtml(String(v))}</code></td></tr>`).join('')}
    </tbody></table>
    <p class="inv-muted">Simulated returns from pred_ret — not live fills.</p>
  ` : '';
  body.innerHTML = `
    <p>The agent runs a calibrated up-day classifier + expected-return regressor, ranks the eligible
       universe each day by an "edge score" <code>(2·p − 1) · |E[r]|</code>, and opens the top-K with
       fractional-Kelly sizing capped at <code>${(c.max_position_frac * 100).toFixed(0)}%</code> per name.</p>
    <table class="inv-config-tbl">
      <tbody>
        <tr><td>Policy mode</td><td><code>${escapeHtml(String(c.policy_mode || 'edge'))}</code></td></tr>
        <tr><td>Top-K per day</td><td>${c.top_k}</td></tr>
        <tr><td>Min probability</td><td>${(c.min_proba * 100).toFixed(1)}%</td></tr>
        <tr><td>Min predicted return</td><td>${(c.min_pred_ret * 100).toFixed(2)}%</td></tr>
        <tr><td>Min 20d realised vol</td><td>${(c.min_vol_20 * 100).toFixed(2)}%</td></tr>
        <tr><td>Kelly scale</td><td>${c.kelly_scale}</td></tr>
        <tr><td>Max gross exposure</td><td>${(c.max_gross_exposure * 100).toFixed(0)}%</td></tr>
        <tr><td>Cost / slippage</td><td>${c.cost_bps} bps + ${c.slippage_bps} bps/side</td></tr>
        <tr><td>Per-trade return cap</td><td>±${(c.max_daily_ret * 100).toFixed(0)}%</td></tr>
        <tr><td>Excluded symbols</td><td><code>${escapeHtml(String(c.exclude_pattern || ''))}</code></td></tr>
      </tbody>
    </table>
    ${genomeExtra}
    <p class="inv-muted">Generated ${escapeHtml(String(_data.generated_at || ''))} from ${escapeHtml(String(_data.version || ''))}.</p>
  `;
}

function _errorBlock(msg) {
  const el = document.createElement('div');
  el.className = 'inv-error';
  el.textContent = msg;
  return el;
}

// ─── Refresh bar (local server only) ──────────────────────────

function _formatRelative(iso) {
  if (!iso) return 'unknown';
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return iso;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

function _renderRefreshBar() {
  const bar = document.getElementById('inv-refresh-bar');
  if (!bar) return;
  if (_bookOptions.showRetrain === false) {
    bar.innerHTML = `
      <div class="inv-refresh">
        <span class="inv-refresh__mode inv-refresh__mode--static">ARENA SIM</span>
        <span class="inv-refresh__msg">Playback of arena pulse history — use Investor tab to retrain v3.</span>
      </div>`;
    return;
  }
  if (!_backend) {
    bar.innerHTML = `
      <div class="inv-refresh">
        <span class="inv-refresh__mode inv-refresh__mode--static">STATIC</span>
        <span class="inv-refresh__msg">Served as a static file. Start the local server
          (<code>python scripts/serve.py</code>) to enable on-demand retraining.</span>
      </div>`;
    return;
  }
  const modified = _backend.decisions?.modified_at;
  const generated = _data?.generated_at;
  const jobState = _backend.job?.state || 'idle';
  bar.innerHTML = `
    <div class="inv-refresh">
      <span class="inv-refresh__mode inv-refresh__mode--live">LIVE</span>
      <span class="inv-refresh__msg">
        Data refreshed <strong>${escapeHtml(_formatRelative(modified || generated))}</strong>
        ${modified ? `<span class="inv-muted"> (${escapeHtml(new Date(modified).toLocaleString())})</span>` : ''}
      </span>
      <button class="inv-btn" id="inv-retrain-btn" ${jobState === 'running' ? 'disabled' : ''}>
        ${jobState === 'running' ? '⏳ Retraining…' : '↻ Retrain now'}
      </button>
      <span class="inv-refresh__job" id="inv-retrain-status"></span>
    </div>`;
  const btn = document.getElementById('inv-retrain-btn');
  btn?.addEventListener('click', _triggerRetrain);
  if (jobState === 'running') _pollRetrainStatus();
}

async function _triggerRetrain() {
  const btn = document.getElementById('inv-retrain-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Retraining…'; }
  try {
    const resp = await fetch('/api/retrain', { method: 'POST' });
    if (!resp.ok) {
      const txt = await resp.text();
      showToast(`Retrain failed to start: ${txt}`, 'error');
      if (btn) { btn.disabled = false; btn.textContent = '↻ Retrain now'; }
      return;
    }
    showToast('Retrain started — this can take a couple of minutes.', 'info');
    _pollRetrainStatus();
  } catch (err) {
    showToast(`Retrain error: ${err.message || err}`, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '↻ Retrain now'; }
  }
}

function _pollRetrainStatus() {
  if (_retrainPoller) return;
  const statusEl = document.getElementById('inv-retrain-status');
  _retrainPoller = setInterval(async () => {
    try {
      const r = await fetch('/api/retrain/status', { cache: 'no-cache' });
      if (!r.ok) return;
      const s = await r.json();
      if (statusEl) {
        const tail = (s.log_tail || []).slice(-1)[0] || '';
        statusEl.textContent = tail ? `· ${tail.slice(0, 80)}` : '';
      }
      if (s.state === 'done' || s.state === 'failed') {
        clearInterval(_retrainPoller);
        _retrainPoller = null;
        if (s.state === 'done') {
          showToast('Retrain complete — reloading decisions…', 'success');
          // refresh health + data, then re-render
          try {
            const h = await fetch('/api/health', { cache: 'no-cache' });
            if (h.ok) _backend = await h.json();
            const d = await fetch('/api/decisions', { cache: 'no-cache' });
            if (d.ok) _data = await d.json();
            _renderKpis();
            _renderEquityChart();
            _renderConfigPanel();
            _renderDay();
            _renderRefreshBar();
          } catch (e) {
            showToast('Reload failed: ' + (e.message || e), 'error');
          }
        } else {
          showToast(`Retrain failed (exit ${s.returncode}). Check logs/.`, 'error');
          _renderRefreshBar();
        }
      }
    } catch (_) { /* keep polling */ }
  }, 2000);
}
