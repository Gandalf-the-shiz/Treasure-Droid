/**
 * js/ui/charts.js
 * Chart.js integration — price history sparklines and prediction overlays.
 *
 * Phase 1: Renders mini sparkline charts on stock cards.
 * Phase 3: Full-size price charts in stock detail view + prediction overlay.
 * Phase 4+: Real ML predictions replace demo predictions.
 *
 * Requires Chart.js loaded via CDN (window.Chart).
 */

// Registry of active Chart instances to allow destruction on re-render.
/** @type {Map<string, Chart>} */
const chartRegistry = new Map();

// ─── Colour palette (dark-theme compatible) ──────────────────
const C_GRID    = 'rgba(255,255,255,0.06)';
const C_TICK    = 'rgba(255,255,255,0.35)';
const C_UP      = 'rgba(38, 217, 127, 1)';
const C_UP_DIM  = 'rgba(38, 217, 127, 0.12)';
const C_DOWN    = 'rgba(240, 92, 110, 1)';
const C_DOWN_DIM= 'rgba(240, 92, 110, 0.12)';
const C_VOL     = 'rgba(124, 111, 239, 0.35)';
const C_RANGE   = 'rgba(124, 111, 239, 0.10)';

// ─── Helpers ─────────────────────────────────────────────────

/** Create (or replace) a canvas inside a container. */
function _makeCanvas(container, ariaLabel) {
  const key = container.dataset.chartKey;
  if (key && chartRegistry.has(key)) {
    chartRegistry.get(key).destroy();
    chartRegistry.delete(key);
  }
  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-label', ariaLabel);
  canvas.setAttribute('role', 'img');
  container.innerHTML = '';
  container.appendChild(canvas);
  return canvas;
}

/** Register a chart instance; attach key to the container. */
function _register(container, chart) {
  const key = `chart_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  container.dataset.chartKey = key;
  chartRegistry.set(key, chart);
  return key;
}

/** Destroy the chart attached to a container (if any). */
export function destroyContainerChart(container) {
  const key = container?.dataset?.chartKey;
  if (key && chartRegistry.has(key)) {
    chartRegistry.get(key).destroy();
    chartRegistry.delete(key);
    delete container.dataset.chartKey;
  }
}

// Gold/orange colour for the AI Prediction overlay line
const C_AI_PRED = 'rgba(255, 193, 7, 1)';

/**
 * Build prediction overlay datasets appended after the last historical point.
 * @param {number[]} prices           - historical close prices
 * @param {string[]} labels           - corresponding x-axis labels (YYYY-MM-DD or index strings)
 * @param {import('../ml/prediction.js').Prediction|null} prediction
 * @param {Array<{date: string, predictedPrice: number}>} [pastPredictions]
 * @returns {{ predLabels: string[], predDatasets: object[] }}
 */
function _predictionDatasets(prices, labels, prediction, pastPredictions = []) {
  const datasets = [];
  const extraLabels = [];

  // ── Past AI predictions overlay ──────────────────────────────
  if (pastPredictions.length > 0) {
    // Align each prediction to its matching label index; null for unmatched dates
    const aiData = labels.map(lbl => {
      const match = pastPredictions.find(pp => pp.date === lbl);
      return match ? match.predictedPrice : null;
    });

    datasets.push({
      label: 'AI Prediction',
      data: aiData,
      borderColor: C_AI_PRED,
      backgroundColor: 'transparent',
      borderWidth: 2,
      borderDash: [6, 4],
      pointRadius: aiData.map(v => (v !== null ? 4 : 0)),
      pointHoverRadius: aiData.map(v => (v !== null ? 5 : 0)),
      pointBackgroundColor: C_AI_PRED,
      pointBorderColor: '#0f1117',
      pointBorderWidth: 1,
      tension: 0,
      fill: false,
      spanGaps: true,
      order: 0,
    });
  }

  // ── Future prediction (single dashed extension) ──────────────
  if (prediction) {
    const lastPrice = prices[prices.length - 1];
    const predColor = prediction.direction === 'UP' ? C_UP : C_DOWN;
    const nHistory  = prices.length;

    // Two-point segment: last historical → predicted price
    const predPoint = [
      { x: nHistory - 1, y: lastPrice },
      { x: nHistory,     y: prediction.predictedPrice },
    ];

    extraLabels.push('Future Prediction');
    datasets.push({
      label: 'Future Prediction',
      data: predPoint,
      borderColor: predColor,
      backgroundColor: 'transparent',
      borderWidth: 2,
      borderDash: [6, 4],
      pointRadius: [0, 6],
      pointBackgroundColor: predColor,
      pointBorderColor: '#0f1117',
      pointBorderWidth: 2,
      tension: 0,
      fill: false,
      order: 0,
    });
  }

  return { predLabels: extraLabels, predDatasets: datasets };
}

// ─── Public API ───────────────────────────────────────────────

/**
 * Render a compact sparkline chart for a stock card.
 * Now includes a hover tooltip and a dot at the last price point.
 *
 * @param {HTMLElement} container  - The chart container element
 * @param {number[]} prices        - Array of close prices (oldest → newest)
 * @param {boolean} [isUp=true]    - Determines chart color (green/red)
 */
export function renderSparkline(container, prices, isUp = true) {
  if (typeof Chart === 'undefined') {
    console.warn('[Charts] Chart.js not loaded. Skipping sparkline.');
    return;
  }
  if (!prices || prices.length === 0) return;

  const canvas = _makeCanvas(container, 'Price sparkline chart');

  const color     = isUp ? C_UP   : C_DOWN;
  const fillColor = isUp ? C_UP_DIM : C_DOWN_DIM;

  // Point radii: 0 for all except the last point
  const pointRadii = prices.map((_, i) => i === prices.length - 1 ? 4 : 0);
  const hoverRadii = prices.map((_, i) => i === prices.length - 1 ? 5 : 3);

  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: prices.map((_, i) => i),
      datasets: [{
        data: prices,
        borderColor: color,
        backgroundColor: fillColor,
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: pointRadii,
        pointHoverRadius: hoverRadii,
        pointBackgroundColor: color,
        pointBorderColor: '#0f1117',
        pointBorderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          mode: 'index',
          intersect: false,
          backgroundColor: 'rgba(26,29,39,0.92)',
          titleColor: 'rgba(255,255,255,0.5)',
          bodyColor: '#e8eaf0',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          padding: 6,
          displayColors: false,
          callbacks: {
            title: () => '',
            label: ctx => `$${Number(ctx.parsed.y).toFixed(2)}`,
          },
        },
      },
      scales: {
        x: { display: false },
        y: { display: false },
      },
      interaction: { mode: 'index', intersect: false },
    },
  });

  _register(container, chart);
}

/**
 * Render a full-size interactive price history chart with optional prediction overlay.
 * Used in the stock detail view.
 *
 * @param {HTMLElement} container
 * @param {Array<{date: string, close: number}>} history    - date strings + close prices
 * @param {import('../ml/prediction.js').Prediction|null} [prediction]
 * @param {Array<{date: string, predictedPrice: number}>} [pastPredictions]
 */
export function renderDetailChart(container, history, prediction = null, pastPredictions = []) {
  if (typeof Chart === 'undefined') {
    container.innerHTML = '<p style="color:var(--color-text-muted);padding:16px;text-align:center;">Chart.js not loaded.</p>';
    return;
  }
  if (!history || history.length === 0) {
    container.innerHTML = '<p style="color:var(--color-text-muted);padding:16px;text-align:center;">No chart data available.</p>';
    return;
  }

  const canvas = _makeCanvas(container, 'Price history chart');

  const prices = history.map(h => h.close);
  const labels = history.map(h => h.date);
  const isUp   = prices[prices.length - 1] >= prices[0];

  const color     = isUp ? C_UP   : C_DOWN;
  const fillColor = isUp ? C_UP_DIM : C_DOWN_DIM;

  const { predLabels, predDatasets } = _predictionDatasets(prices, labels, prediction, pastPredictions);
  const allLabels = [...labels, ...predLabels];

  const datasets = [
    {
      label: 'Actual Price',
      data: prices,
      borderColor: color,
      backgroundColor: (ctx) => {
        const chart = ctx.chart;
        const { ctx: c2d, chartArea } = chart;
        if (!chartArea) return fillColor;
        const grad = c2d.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
        grad.addColorStop(0, isUp ? 'rgba(38,217,127,0.22)' : 'rgba(240,92,110,0.22)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        return grad;
      },
      borderWidth: 2,
      fill: true,
      tension: 0.3,
      pointRadius: 0,
      pointHoverRadius: 5,
      pointHoverBackgroundColor: color,
      order: 1,
    },
    ...predDatasets,
  ];

  const chart = new Chart(canvas, {
    type: 'line',
    data: { labels: allLabels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 500, easing: 'easeInOutQuart' },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: predDatasets.length > 0,
          labels: { color: C_TICK, font: { size: 11 }, boxWidth: 16 },
        },
        tooltip: {
          backgroundColor: 'rgba(26,29,39,0.95)',
          titleColor: 'rgba(255,255,255,0.6)',
          bodyColor: '#e8eaf0',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: ctx => {
              const val = ctx.parsed.y;
              if (val == null) return '';
              return `${ctx.dataset.label}: $${Number(val).toFixed(2)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: C_TICK, maxTicksLimit: 6, maxRotation: 0, font: { size: 11 } },
          grid:  { color: C_GRID },
          border: { color: C_GRID },
        },
        y: {
          position: 'right',
          ticks: { color: C_TICK, font: { size: 11 }, callback: v => `$${Number(v).toFixed(0)}` },
          grid:  { color: C_GRID },
          border: { color: C_GRID },
        },
      },
    },
  });

  _register(container, chart);
}

/**
 * Render a full OHLCV chart: close-price line with high/low shaded range
 * and volume bars on a secondary Y-axis.
 *
 * @param {HTMLElement} container
 * @param {Array<{date:string, open:number, high:number, low:number, close:number, volume:number}>} candles
 * @param {import('../ml/prediction.js').Prediction|null} [prediction]
 * @param {Array<{date: string, predictedPrice: number}>} [pastPredictions]
 */
export function renderFullChart(container, candles, prediction = null, pastPredictions = []) {
  if (typeof Chart === 'undefined') {
    container.innerHTML = '<p style="color:var(--color-text-muted);padding:16px;text-align:center;">Chart.js not loaded.</p>';
    return;
  }
  if (!candles || candles.length === 0) {
    container.innerHTML = '<p style="color:var(--color-text-muted);padding:16px;text-align:center;">No chart data available.</p>';
    return;
  }

  const canvas = _makeCanvas(container, 'Full OHLCV chart');

  const labels  = candles.map(c => c.date);
  const closes  = candles.map(c => c.close);
  const highs   = candles.map(c => c.high);
  const lows    = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume);

  const isUp = closes[closes.length - 1] >= closes[0];
  const lineColor = isUp ? C_UP : C_DOWN;

  // High-low range as fill between two lines
  const highDataset = {
    label: 'High',
    data: highs,
    borderColor: 'transparent',
    backgroundColor: C_RANGE,
    borderWidth: 0,
    fill: '+1',   // fill between high and low (next dataset)
    tension: 0.3,
    pointRadius: 0,
    yAxisID: 'y',
    order: 3,
  };
  const lowDataset = {
    label: 'Low',
    data: lows,
    borderColor: 'transparent',
    backgroundColor: 'transparent',
    borderWidth: 0,
    fill: false,
    tension: 0.3,
    pointRadius: 0,
    yAxisID: 'y',
    order: 4,
  };
  const closeDataset = {
    label: 'Actual Price',
    data: closes,
    borderColor: lineColor,
    backgroundColor: 'transparent',
    borderWidth: 2,
    fill: false,
    tension: 0.3,
    pointRadius: 0,
    pointHoverRadius: 5,
    pointHoverBackgroundColor: lineColor,
    yAxisID: 'y',
    order: 2,
  };
  const volDataset = {
    label: 'Volume',
    data: volumes,
    type: 'bar',
    backgroundColor: C_VOL,
    borderColor: 'transparent',
    borderWidth: 0,
    yAxisID: 'yVol',
    order: 5,
  };

  const { predLabels, predDatasets } = _predictionDatasets(closes, labels, prediction, pastPredictions);
  const allLabels = [...labels, ...predLabels];

  // Offset prediction datasets to use primary y-axis
  predDatasets.forEach(ds => { ds.yAxisID = 'y'; });

  const chart = new Chart(canvas, {
    type: 'line',
    data: { labels: allLabels, datasets: [highDataset, lowDataset, closeDataset, volDataset, ...predDatasets] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 500 },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: {
            color: C_TICK,
            font: { size: 11 },
            boxWidth: 14,
            filter: item => !['High', 'Low'].includes(item.text),
          },
        },
        tooltip: {
          backgroundColor: 'rgba(26,29,39,0.95)',
          titleColor: 'rgba(255,255,255,0.6)',
          bodyColor: '#e8eaf0',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: ctx => {
              const label = ctx.dataset.label;
              const val   = ctx.parsed.y;
              if (val == null) return '';
              if (label === 'Volume') return `Vol: ${_fmt(val)}`;
              return `${label}: $${Number(val).toFixed(2)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: C_TICK, maxTicksLimit: 6, maxRotation: 0, font: { size: 11 } },
          grid:  { color: C_GRID },
          border: { color: C_GRID },
        },
        y: {
          position: 'right',
          ticks: { color: C_TICK, font: { size: 11 }, callback: v => `$${Number(v).toFixed(0)}` },
          grid:  { color: C_GRID },
          border: { color: C_GRID },
        },
        yVol: {
          position: 'left',
          grid: { display: false },
          border: { color: C_GRID },
          ticks: { color: C_TICK, font: { size: 10 }, callback: v => _fmt(v) },
          max: Math.max(...volumes, 1) * 4,  // keep volume bars in lower 25% of chart
        },
      },
    },
  });

  _register(container, chart);
}

/**
 * Destroy all active chart instances (e.g., on route change).
 */
export function destroyAllCharts() {
  chartRegistry.forEach(chart => chart.destroy());
  chartRegistry.clear();
}

// ─── Internal ─────────────────────────────────────────────────

function _fmt(v) {
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}
