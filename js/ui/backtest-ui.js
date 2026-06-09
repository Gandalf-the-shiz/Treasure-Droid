/**
 * js/ui/backtest-ui.js
 * Backtesting Interface — Phase 9.
 *
 * Full-featured backtest UI view:
 *   - Configuration panel (date range, capital, threshold, max positions)
 *   - "Run Backtest" button with progress indicator
 *   - Metrics cards (Total Return, Sharpe, Max Drawdown, Win Rate, Total Trades)
 *   - Equity curve chart (Chart.js) vs. benchmark
 *   - Drawdown chart
 *   - Trade log table (paginated)
 *   - Export-to-CSV button
 *
 * Export: renderBacktestUI(container, appState)
 * Lazy-loaded by app.js.
 */

import { runBacktest }     from '../backtest/engine.js';
import { getPredictions }  from '../ml/tracker.js';
import { loadDemoData }    from '../api/manager.js';
import { formatCurrency, escapeHtml as _escHtml } from '../utils/helpers.js';
import { demoPrediction }  from '../ml/prediction.js';

// ─── Chart registry ───────────────────────────────────────────

let _equityChart   = null;
let _drawdownChart = null;

// ─── Trade-log pagination ─────────────────────────────────────

const TRADE_PAGE_SIZE = 20;
let _trades    = [];
let _tradePage = 1;

// ─── Public API ───────────────────────────────────────────────

/**
 * Render (or refresh) the backtest view.
 *
 * @param {HTMLElement} container
 * @param {{ mode: 'demo'|'live', chartReady: boolean }} appState
 */
export async function renderBacktestUI(container, appState) {
  container.innerHTML = '';

  // ── Title
  const title = document.createElement('h2');
  title.className = 'backtest-title';
  title.textContent = '📈 Backtesting Engine';
  container.appendChild(title);

  const subtitle = document.createElement('p');
  subtitle.className = 'backtest-subtitle';
  subtitle.textContent =
    'Simulate a trading strategy driven by AI predictions on historical data. Runs entirely in your browser.';
  container.appendChild(subtitle);

  if (appState.mode === 'demo') {
    const note = document.createElement('p');
    note.className = 'backtest-demo-note';
    note.textContent = 'Demo mode — using sample historical data.';
    container.appendChild(note);
  }

  // ── Config panel
  const configPanel = _buildConfigPanel();
  container.appendChild(configPanel);

  // ── Results placeholder
  const resultsEl = document.createElement('div');
  resultsEl.id        = 'backtest-results';
  resultsEl.className = 'backtest-results';
  resultsEl.hidden    = true;
  container.appendChild(resultsEl);

  // ── Wire "Run Backtest" button
  const runBtn = configPanel.querySelector('#backtest-run-btn');
  const progressEl = configPanel.querySelector('#backtest-progress');

  runBtn?.addEventListener('click', async () => {
    runBtn.disabled    = true;
    runBtn.textContent = '⏳ Running…';
    if (progressEl) progressEl.hidden = false;

    // Small yield so the browser can paint the loading state
    await new Promise(r => setTimeout(r, 20));

    try {
      const cfg    = _readConfig(configPanel);
      const candles = await _getCandles(appState);
      const preds   = _getPreds();
      const result  = runBacktest(candles, preds, cfg);
      _renderResults(resultsEl, result, appState);
    } catch (err) {
      console.error('[Backtest] Error:', err);
      resultsEl.hidden    = false;
      resultsEl.innerHTML = `<p class="backtest-error">Backtest failed: ${_escHtml(err.message)}</p>`;
    } finally {
      runBtn.disabled    = false;
      runBtn.textContent = '▶ Run Backtest';
      if (progressEl) progressEl.hidden = true;
    }
  });
}

// ─── Config panel ─────────────────────────────────────────────

function _buildConfigPanel() {
  const panel = document.createElement('div');
  panel.className = 'backtest-config-panel';

  panel.innerHTML = `
    <div class="backtest-config-grid">
      <div class="backtest-field">
        <label class="backtest-label" for="bt-start-date">Start Date</label>
        <input type="date" id="bt-start-date" class="backtest-input" value="2023-01-01" />
      </div>
      <div class="backtest-field">
        <label class="backtest-label" for="bt-end-date">End Date</label>
        <input type="date" id="bt-end-date" class="backtest-input" value="${_todayStr()}" />
      </div>
      <div class="backtest-field">
        <label class="backtest-label" for="bt-capital">Initial Capital ($)</label>
        <input type="number" id="bt-capital" class="backtest-input" value="10000" min="100" step="1000" />
      </div>
      <div class="backtest-field">
        <label class="backtest-label" for="bt-threshold">Min Confidence (%)</label>
        <input type="number" id="bt-threshold" class="backtest-input" value="60" min="50" max="95" step="5" />
      </div>
      <div class="backtest-field">
        <label class="backtest-label" for="bt-max-pos">Max Positions</label>
        <input type="number" id="bt-max-pos" class="backtest-input" value="5" min="1" max="20" />
      </div>
    </div>
    <div class="backtest-actions">
      <button id="backtest-run-btn" class="btn btn--primary">▶ Run Backtest</button>
      <span id="backtest-progress" class="backtest-progress" hidden>Simulating…</span>
    </div>
  `;

  return panel;
}

function _readConfig(panel) {
  const startDate = panel.querySelector('#bt-start-date')?.value ?? '';
  const endDate   = panel.querySelector('#bt-end-date')?.value   ?? '';
  const capital   = parseFloat(panel.querySelector('#bt-capital')?.value ?? '10000');
  const threshold = parseFloat(panel.querySelector('#bt-threshold')?.value ?? '60') / 100;
  const maxPos    = parseInt(panel.querySelector('#bt-max-pos')?.value ?? '5', 10);

  return {
    startDate,
    endDate,
    initialCapital:      isNaN(capital)   ? 10_000 : capital,
    confidenceThreshold: isNaN(threshold) ? 0.60   : threshold,
    maxPositions:        isNaN(maxPos)    ? 5      : maxPos,
    sectorFilter:        null,
  };
}

// ─── Data sourcing ────────────────────────────────────────────

async function _getCandles(appState) {
  // Try loading demo data (always works, even without API keys)
  try {
    const demo = await loadDemoData();
    const candles = [];
    for (const stock of (demo.stocks ?? [])) {
      const sym = stock.symbol ?? 'UNKNOWN';
      if (!Array.isArray(stock.candles)) continue;
      for (const c of stock.candles) {
        candles.push({ ...c, symbol: sym });
      }
    }
    if (candles.length > 0) return candles;
  } catch (_) { /* fall through to generated */ }

  // Fallback: generate synthetic candles for demo symbols
  return _generateDemoCandles();
}

function _getPreds() {
  const stored = getPredictions();
  if (stored.length > 0) return stored;
  return []; // engine will use momentum fallback
}

/**
 * Generate synthetic OHLCV candles for demo symbols over ~1 year.
 */
function _generateDemoCandles() {
  const DEMO = {
    AAPL: 150, GOOGL: 130, MSFT: 350, AMZN: 160, TSLA: 200,
    META: 300, NVDA: 500, JPM: 170, V: 250, JNJ: 155,
  };
  const candles = [];
  const today = new Date();

  for (const [symbol, seedPrice] of Object.entries(DEMO)) {
    let price = seedPrice;
    for (let d = 365; d >= 0; d--) {
      const date = new Date(today);
      date.setDate(date.getDate() - d);
      const dayOfWeek = date.getDay();
      if (dayOfWeek === 0 || dayOfWeek === 6) continue; // skip weekends

      const change = (Math.random() - 0.49) * price * 0.02;
      price = Math.max(1, price + change);
      const open   = parseFloat((price * (0.995 + Math.random() * 0.01)).toFixed(2));
      const high   = parseFloat((price * (1.005 + Math.random() * 0.015)).toFixed(2));
      const low    = parseFloat((price * (0.985 - Math.random() * 0.01)).toFixed(2));
      const close  = parseFloat(price.toFixed(2));
      const volume = Math.floor(1_000_000 + Math.random() * 9_000_000);

      candles.push({
        symbol,
        date:   date.toISOString().slice(0, 10),
        open, high, low, close, volume,
      });
    }
  }
  return candles;
}

// ─── Results rendering ────────────────────────────────────────

function _renderResults(container, result, appState) {
  container.hidden    = false;
  container.innerHTML = '';

  // Metrics cards
  container.appendChild(_buildMetricCards(result.metrics, result.benchmark));

  // Equity curve chart
  if (appState.chartReady && result.equityCurve.length > 1) {
    container.appendChild(_buildEquityChart(result.equityCurve, result));
    container.appendChild(_buildDrawdownChart(result.equityCurve));
  } else {
    const note = document.createElement('p');
    note.className = 'backtest-chart-note';
    note.textContent = 'Chart.js not available — install chart library to see equity curve.';
    container.appendChild(note);
  }

  // Trade log
  _trades    = result.trades.slice().reverse(); // newest first
  _tradePage = 1;
  container.appendChild(_buildTradeLog());

  // Export button
  const exportBtn = document.createElement('button');
  exportBtn.className = 'btn btn--secondary backtest-export-btn';
  exportBtn.textContent = '⬇️ Export Trades CSV';
  exportBtn.addEventListener('click', () => _exportCSV(result));
  container.appendChild(exportBtn);
}

// ── Metric cards

function _buildMetricCards(metrics, benchmark) {
  const grid = document.createElement('div');
  grid.className = 'backtest-metrics-grid';

  const stratReturn  = metrics.totalReturn * 100;
  const benchReturn  = benchmark.totalReturn * 100;
  const drawdownPct  = metrics.maxDrawdown * 100;
  const winRatePct   = metrics.winRate * 100;

  const cards = [
    {
      icon:  '📈',
      label: 'Total Return',
      value: `${stratReturn >= 0 ? '+' : ''}${stratReturn.toFixed(2)}%`,
      sub:   `Benchmark: ${benchReturn >= 0 ? '+' : ''}${benchReturn.toFixed(2)}%`,
      good:  stratReturn > 0,
    },
    {
      icon:  '⚡',
      label: 'Sharpe Ratio',
      value: isNaN(metrics.sharpeRatio) ? '—' : metrics.sharpeRatio.toFixed(2),
      sub:   '>1.0 = good risk-adjusted return',
      good:  metrics.sharpeRatio > 1,
    },
    {
      icon:  '📉',
      label: 'Max Drawdown',
      value: `-${drawdownPct.toFixed(2)}%`,
      sub:   metrics.maxDrawdownDate ? `on ${metrics.maxDrawdownDate}` : '',
      good:  drawdownPct < 20,
    },
    {
      icon:  '🎯',
      label: 'Win Rate',
      value: `${winRatePct.toFixed(1)}%`,
      sub:   `${metrics.totalTrades} closed trades`,
      good:  metrics.winRate > 0.5,
    },
    {
      icon:  '💰',
      label: 'Profit Factor',
      value: isFinite(metrics.profitFactor) ? metrics.profitFactor.toFixed(2) : '∞',
      sub:   'Gross profit / gross loss',
      good:  metrics.profitFactor > 1,
    },
  ];

  cards.forEach(c => {
    const card = document.createElement('div');
    card.className = 'backtest-metric-card';
    if (c.good === true)  card.classList.add('backtest-metric-card--good');
    if (c.good === false) card.classList.add('backtest-metric-card--bad');
    card.innerHTML = `
      <span class="backtest-metric-card__icon">${c.icon}</span>
      <span class="backtest-metric-card__label">${c.label}</span>
      <span class="backtest-metric-card__value">${_escHtml(c.value)}</span>
      <span class="backtest-metric-card__sub">${_escHtml(c.sub)}</span>
    `;
    grid.appendChild(card);
  });

  return grid;
}

// ── Equity chart

function _buildEquityChart(equityCurve, result) {
  const wrap = document.createElement('div');
  wrap.className = 'backtest-chart-section';

  const h = document.createElement('h3');
  h.className = 'backtest-chart-title';
  h.textContent = 'Equity Curve';
  wrap.appendChild(h);

  const container = document.createElement('div');
  container.className = 'backtest-chart-container';
  wrap.appendChild(container);

  requestAnimationFrame(() => {
    if (!document.contains(container) || typeof Chart === 'undefined') return;

    if (_equityChart) { _equityChart.destroy(); _equityChart = null; }

    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-label', 'Equity curve chart');
    canvas.setAttribute('role', 'img');
    container.appendChild(canvas);

    const step    = Math.max(1, Math.floor(equityCurve.length / 100));
    const sampled = equityCurve.filter((_, i) => i % step === 0);

    const labels = sampled.map(p => p.date);
    const values = sampled.map(p => p.portfolioValue);

    // Build benchmark equity curve (buy-and-hold same capital growth rate)
    const benchStart = result.benchmark.finalValue
      ? result.metrics.totalReturn !== 0
        ? equityCurve[0].portfolioValue
        : equityCurve[0].portfolioValue
      : equityCurve[0].portfolioValue;

    // Simple linear interpolation of benchmark
    const benchFinal = result.benchmark.finalValue;
    const benchValues = sampled.map((_, i) => {
      const frac = equityCurve.length > 1 ? (sampled[i] ? equityCurve.indexOf(sampled[i]) / (equityCurve.length - 1) : 0) : 0;
      return benchStart + (benchFinal - benchStart) * frac;
    });

    const C_UP     = 'rgba(38, 217, 127, 1)';
    const C_UP_DIM = 'rgba(38, 217, 127, 0.15)';
    const C_BENCH  = 'rgba(139, 145, 167, 0.7)';
    const C_GRID   = 'rgba(255,255,255,0.06)';
    const C_TICK   = 'rgba(255,255,255,0.35)';

    _equityChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Strategy',
            data: values,
            borderColor: C_UP,
            backgroundColor: C_UP_DIM,
            borderWidth: 2,
            fill: true,
            tension: 0.2,
            pointRadius: 0,
          },
          {
            label: 'Benchmark (B&H)',
            data: benchValues,
            borderColor: C_BENCH,
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            borderDash: [5, 4],
            fill: false,
            tension: 0.1,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
          legend: { display: true, labels: { color: C_TICK, font: { size: 11 }, boxWidth: 16 } },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(26,29,39,0.95)',
            bodyColor: '#e8eaf0',
            callbacks: {
              label: ctx => ` ${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y)}`,
            },
          },
        },
        scales: {
          x: { ticks: { color: C_TICK, font: { size: 10 }, maxTicksLimit: 8, maxRotation: 0 }, grid: { color: C_GRID }, border: { color: C_GRID } },
          y: { ticks: { color: C_TICK, font: { size: 10 }, callback: v => `$${(v/1000).toFixed(1)}k` }, grid: { color: C_GRID }, border: { color: C_GRID } },
        },
      },
    });
  });

  return wrap;
}

// ── Drawdown chart

function _buildDrawdownChart(equityCurve) {
  const wrap = document.createElement('div');
  wrap.className = 'backtest-chart-section';

  const h = document.createElement('h3');
  h.className = 'backtest-chart-title';
  h.textContent = 'Drawdown';
  wrap.appendChild(h);

  const container = document.createElement('div');
  container.className = 'backtest-chart-container';
  wrap.appendChild(container);

  requestAnimationFrame(() => {
    if (!document.contains(container) || typeof Chart === 'undefined') return;

    if (_drawdownChart) { _drawdownChart.destroy(); _drawdownChart = null; }

    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-label', 'Drawdown chart');
    canvas.setAttribute('role', 'img');
    container.appendChild(canvas);

    // Compute drawdown series
    const step    = Math.max(1, Math.floor(equityCurve.length / 100));
    const sampled = equityCurve.filter((_, i) => i % step === 0);

    let peak = sampled[0]?.portfolioValue ?? 1;
    const ddSeries = sampled.map(p => {
      if (p.portfolioValue > peak) peak = p.portfolioValue;
      const dd = peak > 0 ? ((p.portfolioValue - peak) / peak) * 100 : 0;
      return { date: p.date, dd };
    });

    const C_DOWN    = 'rgba(240, 92, 110, 1)';
    const C_DOWN_DIM = 'rgba(240, 92, 110, 0.2)';
    const C_GRID    = 'rgba(255,255,255,0.06)';
    const C_TICK    = 'rgba(255,255,255,0.35)';

    _drawdownChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: ddSeries.map(p => p.date),
        datasets: [{
          label: 'Drawdown %',
          data: ddSeries.map(p => p.dd),
          borderColor: C_DOWN,
          backgroundColor: C_DOWN_DIM,
          borderWidth: 1.5,
          fill: true,
          tension: 0.2,
          pointRadius: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(26,29,39,0.95)',
            bodyColor: '#e8eaf0',
            callbacks: {
              label: ctx => ` Drawdown: ${ctx.parsed.y.toFixed(2)}%`,
            },
          },
        },
        scales: {
          x: { ticks: { color: C_TICK, font: { size: 10 }, maxTicksLimit: 8, maxRotation: 0 }, grid: { color: C_GRID }, border: { color: C_GRID } },
          y: { ticks: { color: C_TICK, font: { size: 10 }, callback: v => `${v.toFixed(1)}%` }, grid: { color: C_GRID }, border: { color: C_GRID } },
        },
      },
    });
  });

  return wrap;
}

// ── Trade log

function _buildTradeLog() {
  const section = document.createElement('div');
  section.className = 'backtest-trade-log';

  const h = document.createElement('h3');
  h.className = 'backtest-chart-title';
  h.textContent = `📋 Trade Log (${_trades.length} trades)`;
  section.appendChild(h);

  if (_trades.length === 0) {
    const note = document.createElement('p');
    note.className = 'backtest-empty';
    note.textContent = 'No trades were executed with the current configuration. Try lowering the confidence threshold.';
    section.appendChild(note);
    return section;
  }

  const tableWrap = document.createElement('div');
  tableWrap.className = 'backtest-table-wrap';

  const table = document.createElement('table');
  table.className = 'backtest-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Date</th>
        <th>Symbol</th>
        <th>Action</th>
        <th>Price</th>
        <th>Shares</th>
        <th>P&amp;L</th>
      </tr>
    </thead>
    <tbody id="bt-trade-tbody"></tbody>
  `;
  tableWrap.appendChild(table);
  section.appendChild(tableWrap);

  const pagination = document.createElement('div');
  pagination.className = 'screener-pagination'; // reuse screener pagination styles
  section.appendChild(pagination);

  // Use closure to allow refreshing
  const refresh = () => {
    const tbody = table.querySelector('#bt-trade-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    const start = (_tradePage - 1) * TRADE_PAGE_SIZE;
    const page  = _trades.slice(start, start + TRADE_PAGE_SIZE);
    for (const t of page) {
      const tr = document.createElement('tr');
      const pnlClass = t.action === 'BUY'
        ? ''
        : t.pnl >= 0 ? 'screener-delta--up' : 'screener-delta--down';
      const pnlStr = t.action === 'BUY'
        ? '—'
        : (t.pnl >= 0 ? '+' : '') + formatCurrency(t.pnl);

      tr.innerHTML = `
        <td>${_escHtml(t.date)}</td>
        <td><strong>${_escHtml(t.symbol)}</strong></td>
        <td><span class="${t.action === 'BUY' ? 'screener-badge screener-badge--up' : 'screener-badge screener-badge--down'}">${t.action}</span></td>
        <td>${formatCurrency(t.price)}</td>
        <td>${t.shares}</td>
        <td class="${pnlClass}">${pnlStr}</td>
      `;
      tbody.appendChild(tr);
    }

    // Pagination
    pagination.innerHTML = '';
    const totalPages = Math.max(1, Math.ceil(_trades.length / TRADE_PAGE_SIZE));
    if (totalPages > 1) {
      const prev = document.createElement('button');
      prev.className = 'screener-page-btn';
      prev.textContent = '← Prev';
      prev.disabled = _tradePage <= 1;
      prev.addEventListener('click', () => { _tradePage--; refresh(); });

      const info = document.createElement('span');
      info.className = 'screener-page-info';
      info.textContent = `Page ${_tradePage} of ${totalPages}`;

      const next = document.createElement('button');
      next.className = 'screener-page-btn';
      next.textContent = 'Next →';
      next.disabled = _tradePage >= totalPages;
      next.addEventListener('click', () => { _tradePage++; refresh(); });

      pagination.append(prev, info, next);
    }
  };

  refresh();
  return section;
}

// ─── CSV export ───────────────────────────────────────────────

function _exportCSV(result) {
  const rows = [
    ['Date', 'Symbol', 'Action', 'Price', 'Shares', 'PnL'].join(','),
    ...result.trades.map(t =>
      [t.date, t.symbol, t.action, t.price, t.shares, t.pnl].join(',')
    ),
  ];
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `backtest-trades-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── Helpers ──────────────────────────────────────────────────

function _todayStr() {
  return new Date().toISOString().slice(0, 10);
}
