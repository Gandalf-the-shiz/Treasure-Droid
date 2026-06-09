/**
 * js/ui/heatmap.js
 * Market Treemap Heatmap — Phase 7.
 *
 * Renders a Finviz-style squarified treemap on a <canvas> element.
 * Stocks are grouped by sector, sized by |predictedReturn| (min floor),
 * and coloured by predictedReturn sign + confidence.
 *
 * Export: renderHeatmap(container, predictionsData, appState)
 *   - container: HTMLElement — will receive a <canvas> and tooltip DOM
 *   - predictionsData: Array of prediction objects from tracker.js or demo
 *   - appState: { mode, chartReady }
 *
 * Lazy-loaded by app.js when the user navigates to the "heatmap" view.
 */

import { getPredictions } from '../ml/tracker.js';
import { demoPrediction }  from '../ml/prediction.js';
import { escapeHtml as _escHtml } from '../utils/helpers.js';

// ─── Sector palette ───────────────────────────────────────────

const SECTOR_COLORS = {
  'Technology':             '#7c6fef',
  'Consumer Discretionary': '#f0b429',
  'Financials':             '#26d97f',
  'Healthcare':             '#4dc3ff',
  'Communication Services': '#ff7b54',
  'Energy':                 '#f05c6e',
  'Consumer Staples':       '#a8e6a3',
  'Industrials':            '#c8a2c8',
  'Materials':              '#d4a373',
  'Real Estate':            '#90e0ef',
  'Utilities':              '#b5838d',
  'Other':                  '#8b91a7',
};

/**
 * Broad sector map covering common S&P 500 / Nasdaq-100 tickers.
 * Used as a fallback when the ticker registry has no sector data.
 */
const TICKER_SECTORS = {
  // Technology
  AAPL: 'Technology', MSFT: 'Technology', NVDA: 'Technology', META: 'Technology',
  GOOGL: 'Technology', GOOG: 'Technology', AVGO: 'Technology', ORCL: 'Technology',
  CRM: 'Technology', CSCO: 'Technology', AMD: 'Technology', INTC: 'Technology',
  QCOM: 'Technology', TXN: 'Technology', IBM: 'Technology', NOW: 'Technology',
  ADBE: 'Technology', INTU: 'Technology', AMAT: 'Technology', MU: 'Technology',
  KLAC: 'Technology', LRCX: 'Technology', SNPS: 'Technology', CDNS: 'Technology',
  PANW: 'Technology', FTNT: 'Technology', CRWD: 'Technology', ZS: 'Technology',
  PLTR: 'Technology', DELL: 'Technology', HPQ: 'Technology', HPE: 'Technology',
  STX: 'Technology', WDC: 'Technology', NTAP: 'Technology', KEYS: 'Technology',
  IT: 'Technology', EPAM: 'Technology', GDDY: 'Technology', AKAM: 'Technology',
  NET: 'Technology', DDOG: 'Technology', SNOW: 'Technology', MDB: 'Technology',
  TEAM: 'Technology', WDAY: 'Technology', HUBS: 'Technology', ZM: 'Technology',
  DOCU: 'Technology', TTD: 'Technology', FICO: 'Technology',

  // Communication Services
  NFLX: 'Communication Services', DIS: 'Communication Services',
  CMCSA: 'Communication Services', T: 'Communication Services',
  VZ: 'Communication Services', TMUS: 'Communication Services',
  CHTR: 'Communication Services', FOXA: 'Communication Services',
  FOX: 'Communication Services', PARA: 'Communication Services',
  WBD: 'Communication Services', MTCH: 'Communication Services',
  SNAP: 'Communication Services', PINS: 'Communication Services',
  SPOT: 'Communication Services', EA: 'Communication Services',
  TTWO: 'Communication Services', ATVI: 'Communication Services',
  RBLX: 'Communication Services', LYFT: 'Communication Services',
  UBER: 'Communication Services',

  // Consumer Discretionary
  AMZN: 'Consumer Discretionary', TSLA: 'Consumer Discretionary',
  HD: 'Consumer Discretionary', MCD: 'Consumer Discretionary',
  NKE: 'Consumer Discretionary', LOW: 'Consumer Discretionary',
  SBUX: 'Consumer Discretionary', TJX: 'Consumer Discretionary',
  BKNG: 'Consumer Discretionary', MAR: 'Consumer Discretionary',
  GM: 'Consumer Discretionary', F: 'Consumer Discretionary',
  RIVN: 'Consumer Discretionary', LCID: 'Consumer Discretionary',
  EXPE: 'Consumer Discretionary', ABNB: 'Consumer Discretionary',
  EBAY: 'Consumer Discretionary', ETSY: 'Consumer Discretionary',
  RCL: 'Consumer Discretionary', CCL: 'Consumer Discretionary',
  HLT: 'Consumer Discretionary', YUM: 'Consumer Discretionary',
  ORLY: 'Consumer Discretionary', AZO: 'Consumer Discretionary',
  ROST: 'Consumer Discretionary', DLTR: 'Consumer Discretionary',
  DG: 'Consumer Discretionary', LULU: 'Consumer Discretionary',
  PHM: 'Consumer Discretionary', DHI: 'Consumer Discretionary',
  LEN: 'Consumer Discretionary', TOL: 'Consumer Discretionary',

  // Consumer Staples
  WMT: 'Consumer Staples', PG: 'Consumer Staples', KO: 'Consumer Staples',
  PEP: 'Consumer Staples', COST: 'Consumer Staples', MDLZ: 'Consumer Staples',
  MO: 'Consumer Staples', PM: 'Consumer Staples', CL: 'Consumer Staples',
  KMB: 'Consumer Staples', STZ: 'Consumer Staples', GIS: 'Consumer Staples',
  KHC: 'Consumer Staples', HSY: 'Consumer Staples', CAG: 'Consumer Staples',
  SJM: 'Consumer Staples', CPB: 'Consumer Staples', KR: 'Consumer Staples',
  ADM: 'Consumer Staples', BG: 'Consumer Staples',

  // Healthcare
  JNJ: 'Healthcare', UNH: 'Healthcare', LLY: 'Healthcare', PFE: 'Healthcare',
  MRK: 'Healthcare', ABBV: 'Healthcare', ABT: 'Healthcare', TMO: 'Healthcare',
  DHR: 'Healthcare', BMY: 'Healthcare', AMGN: 'Healthcare', GILD: 'Healthcare',
  MDT: 'Healthcare', SYK: 'Healthcare', BSX: 'Healthcare', ISRG: 'Healthcare',
  HCA: 'Healthcare', CI: 'Healthcare', CVS: 'Healthcare', MCK: 'Healthcare',
  ABC: 'Healthcare', CAH: 'Healthcare', BIIB: 'Healthcare', REGN: 'Healthcare',
  VRTX: 'Healthcare', MRNA: 'Healthcare', ILMN: 'Healthcare', IDXX: 'Healthcare',
  IQV: 'Healthcare', A: 'Healthcare', ZBH: 'Healthcare', BAX: 'Healthcare',
  BDX: 'Healthcare', EW: 'Healthcare', HOLX: 'Healthcare', VTRS: 'Healthcare',

  // Financials
  JPM: 'Financials', BAC: 'Financials', WFC: 'Financials', GS: 'Financials',
  MS: 'Financials', C: 'Financials', AXP: 'Financials', V: 'Financials',
  MA: 'Financials', BK: 'Financials', USB: 'Financials', TFC: 'Financials',
  PNC: 'Financials', COF: 'Financials', DFS: 'Financials', SYF: 'Financials',
  SCHW: 'Financials', BLK: 'Financials', SPGI: 'Financials', MCO: 'Financials',
  ICE: 'Financials', CME: 'Financials', CB: 'Financials', PGR: 'Financials',
  TRV: 'Financials', MET: 'Financials', PRU: 'Financials', AFL: 'Financials',
  AIG: 'Financials', ALL: 'Financials', HIG: 'Financials', L: 'Financials',
  FITB: 'Financials', HBAN: 'Financials', RF: 'Financials', CFG: 'Financials',
  KEY: 'Financials', MTB: 'Financials', WBS: 'Financials', ZION: 'Financials',
  FDS: 'Financials', MSCI: 'Financials', NDAQ: 'Financials',

  // Energy
  XOM: 'Energy', CVX: 'Energy', COP: 'Energy', EOG: 'Energy',
  SLB: 'Energy', MPC: 'Energy', PSX: 'Energy', VLO: 'Energy',
  PXD: 'Energy', OXY: 'Energy', HAL: 'Energy', BKR: 'Energy',
  DVN: 'Energy', FANG: 'Energy', HES: 'Energy', APA: 'Energy',
  MRO: 'Energy', RRC: 'Energy', EQT: 'Energy', AR: 'Energy',
  KMI: 'Energy', WMB: 'Energy', OKE: 'Energy', ET: 'Energy',
  EPD: 'Energy', MPLX: 'Energy',

  // Industrials
  BA: 'Industrials', HON: 'Industrials', UPS: 'Industrials', CAT: 'Industrials',
  DE: 'Industrials', GE: 'Industrials', LMT: 'Industrials', RTX: 'Industrials',
  NOC: 'Industrials', GD: 'Industrials', MMM: 'Industrials', EMR: 'Industrials',
  ETN: 'Industrials', ITW: 'Industrials', PH: 'Industrials', ROK: 'Industrials',
  FDX: 'Industrials', CSX: 'Industrials', UNP: 'Industrials', NSC: 'Industrials',
  DAL: 'Industrials', UAL: 'Industrials', AAL: 'Industrials', LUV: 'Industrials',
  WM: 'Industrials', RSG: 'Industrials', CTAS: 'Industrials', FAST: 'Industrials',
  GWW: 'Industrials', VRSK: 'Industrials', CPRT: 'Industrials',

  // Materials
  LIN: 'Materials', APD: 'Materials', NEM: 'Materials', FCX: 'Materials',
  DD: 'Materials', DOW: 'Materials', PPG: 'Materials', SHW: 'Materials',
  ECL: 'Materials', ALB: 'Materials', CF: 'Materials', MOS: 'Materials',
  NUE: 'Materials', STLD: 'Materials', RS: 'Materials', AA: 'Materials',

  // Real Estate
  PLD: 'Real Estate', AMT: 'Real Estate', EQIX: 'Real Estate', CCI: 'Real Estate',
  SPG: 'Real Estate', O: 'Real Estate', WELL: 'Real Estate', DLR: 'Real Estate',
  PSA: 'Real Estate', EQR: 'Real Estate', AVB: 'Real Estate', VTR: 'Real Estate',
  ARE: 'Real Estate', BXP: 'Real Estate', SLG: 'Real Estate',

  // Utilities
  NEE: 'Utilities', DUK: 'Utilities', SO: 'Utilities', D: 'Utilities',
  AEP: 'Utilities', EXC: 'Utilities', XEL: 'Utilities', PCG: 'Utilities',
  ED: 'Utilities', ES: 'Utilities', ETR: 'Utilities', PPL: 'Utilities',
  WEC: 'Utilities', CMS: 'Utilities', AES: 'Utilities', NI: 'Utilities',
};

// ─── Squarified treemap algorithm ────────────────────────────

/**
 * Squarify layout algorithm.
 * @param {number[]} values   - Non-negative weights (same length as items)
 * @param {number} x
 * @param {number} y
 * @param {number} w
 * @param {number} h
 * @returns {{ x, y, w, h }[]}
 */
function squarify(values, x, y, w, h) {
  if (values.length === 0) return [];
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) {
    const n = values.length;
    return values.map((_, i) => ({ x: x + (i * w) / n, y, w: w / n, h }));
  }

  const rects = [];
  _squarifyRow(values, x, y, w, h, total, rects);
  return rects;
}

function _squarifyRow(values, x, y, w, h, total, rects) {
  if (values.length === 0) return;
  if (values.length === 1) {
    rects.push({ x, y, w, h });
    return;
  }

  const horizontal = w >= h;
  const side = horizontal ? h : w;

  let row = [];
  let rowArea = 0;
  let i = 0;

  while (i < values.length) {
    const v = (values[i] / total) * (w * h);
    const candidate = [...row, v];
    const candidateArea = rowArea + v;

    if (row.length === 0 || _worstRatio(candidate, candidateArea, side) <= _worstRatio(row, rowArea, side)) {
      row.push(v);
      rowArea += v;
      i++;
    } else {
      break;
    }
  }

  // Lay out the current row
  const rowFrac = rowArea / (w * h);
  let cursor = horizontal ? x : y;
  for (const rv of row) {
    const frac = rv / rowArea;
    if (horizontal) {
      const rh = rowFrac * h;
      const rw = frac * w;
      rects.push({ x: cursor, y, w: rw, h: rh });
      cursor += rw;
    } else {
      const rw = rowFrac * w;
      const rh = frac * h;
      rects.push({ x, y: cursor, w: rw, h: rh });
      cursor += rh;
    }
  }

  // Recurse on remaining values
  if (i < values.length) {
    if (horizontal) {
      const usedH = rowFrac * h;
      _squarifyRow(values.slice(i), x, y + usedH, w, h - usedH, total - rowArea / (w * h) * total, rects);
    } else {
      const usedW = rowFrac * w;
      _squarifyRow(values.slice(i), x + usedW, y, w - usedW, h, total - rowArea / (w * h) * total, rects);
    }
  }
}

function _worstRatio(row, area, side) {
  if (row.length === 0 || area === 0) return Infinity;
  const maxA = Math.max(...row);
  const minA = Math.min(...row);
  const s2 = side * side;
  const a2 = area * area;
  return Math.max((s2 * maxA) / a2, a2 / (s2 * minA));
}

// ─── Colour helpers ───────────────────────────────────────────

/**
 * Map a prediction to a canvas fill colour.
 * Direction is derived from predictedReturn sign when available,
 * falling back to the direction field.
 * UP → green gradient by confidence; DOWN → red gradient; neutral → gray.
 */
function _predictionColor(pred) {
  if (!pred) return 'rgba(139,145,167,0.5)';
  const c = pred.confidence ?? 0.5;
  const alpha = 0.4 + c * 0.55; // 0.4 – 0.95

  // Prefer predictedReturn sign as source of truth (direction can disagree with it in v2)
  const isUp = pred.predictedReturn != null
    ? pred.predictedReturn >= 0
    : pred.direction === 'UP';

  if (isUp) {
    // green family
    const g = Math.round(180 + c * 75);
    return `rgba(38,${g},127,${alpha.toFixed(2)})`;
  }
  // DOWN → red family
  const r = Math.round(200 + c * 55);
  return `rgba(${r},60,90,${alpha.toFixed(2)})`;
}

// ─── Public API ───────────────────────────────────────────────

// Maximum number of tickers to render in the treemap.
// With thousands of tickers from the v2 pipeline the canvas becomes unreadable.
const HEATMAP_MAX_TICKERS = 100;

/**
 * Render (or refresh) the heatmap into the given container.
 *
 * @param {HTMLElement} container
 * @param {Object[]|null} predictionsData  - Optional override; uses tracker if null
 * @param {{ mode: 'demo'|'live' }} appState
 */
export function renderHeatmap(container, predictionsData, appState) {
  // Disconnect any existing ResizeObserver before wiping the DOM.
  const oldCanvas = container.querySelector('canvas.heatmap-canvas');
  if (oldCanvas?._resizeObserver) {
    oldCanvas._resizeObserver.disconnect();
    oldCanvas._resizeObserver = null;
  }

  container.innerHTML = '';

  // ── Build prediction lookup
  let predictions = predictionsData;
  if (!predictions || predictions.length === 0) {
    predictions = getPredictions();
  }

  // Fall back to demo predictions for the default watchlist
  if (predictions.length === 0) {
    const DEMO_SYMBOLS = ['AAPL','GOOGL','MSFT','AMZN','TSLA','META','NVDA','NFLX',
                          'JPM','V','JNJ','PFE','XOM','CVX','GS','BAC','WMT','KO','DIS','BA'];
    const BASE_PRICES  = { AAPL:185,GOOGL:140,MSFT:380,AMZN:178,TSLA:245,META:490,NVDA:800,
                           NFLX:600,JPM:195,V:270,JNJ:160,PFE:28,XOM:110,CVX:155,GS:400,
                           BAC:38,WMT:175,KO:61,DIS:95,BA:215 };
    predictions = DEMO_SYMBOLS.map(s => demoPrediction(s, BASE_PRICES[s] ?? 100));
  }

  // Latest per symbol
  const latestMap = new Map();
  for (const p of predictions) {
    const ex = latestMap.get(p.symbol);
    if (!ex || p.generatedAt > ex.generatedAt) latestMap.set(p.symbol, p);
  }

  // When there are many tickers (live v2 pipeline), keep only the top N
  // ranked by |predictedReturn| × confidence so the treemap stays readable.
  let entries = Array.from(latestMap.entries());
  if (entries.length > HEATMAP_MAX_TICKERS) {
    entries.sort(([, a], [, b]) => {
      const scoreA = Math.abs(a.predictedReturn ?? 0) * (a.confidence ?? 0.5);
      const scoreB = Math.abs(b.predictedReturn ?? 0) * (b.confidence ?? 0.5);
      return scoreB - scoreA;
    });
    entries = entries.slice(0, HEATMAP_MAX_TICKERS);
    // Rebuild latestMap with only the top tickers
    latestMap.clear();
    for (const [sym, pred] of entries) latestMap.set(sym, pred);
  }

  // Group by sector using the broad TICKER_SECTORS map
  const sectorGroups = new Map();
  for (const [symbol, pred] of latestMap) {
    const sector = TICKER_SECTORS[symbol] ?? 'Other';
    if (!sectorGroups.has(sector)) sectorGroups.set(sector, []);
    sectorGroups.get(sector).push({ symbol, pred });
  }

  // ── Title
  const titleEl = document.createElement('h2');
  titleEl.className = 'heatmap-title';
  titleEl.textContent = '🌡️ Market Heatmap';
  container.appendChild(titleEl);

  const subtitleEl = document.createElement('p');
  subtitleEl.className = 'heatmap-subtitle';
  subtitleEl.textContent =
    'Colour = predicted direction (green ▲ / red ▼); stronger colour indicates higher confidence. Size = signal strength. Click a cell to view details.';
  container.appendChild(subtitleEl);

  // ── Legend
  const legend = document.createElement('div');
  legend.className = 'heatmap-legend';
  legend.innerHTML = `
    <span class="heatmap-legend__item heatmap-legend__item--up">▲ Bullish</span>
    <span class="heatmap-legend__item heatmap-legend__item--neutral">◼ No data</span>
    <span class="heatmap-legend__item heatmap-legend__item--down">▼ Bearish</span>
  `;
  container.appendChild(legend);

  if (appState.mode === 'demo' && (!predictionsData || predictionsData.length === 0)) {
    const note = document.createElement('p');
    note.className = 'heatmap-demo-note';
    note.textContent = 'Demo mode — showing sample predictions for illustration.';
    container.appendChild(note);
  } else if (entries.length === HEATMAP_MAX_TICKERS) {
    const note = document.createElement('p');
    note.className = 'heatmap-demo-note';
    note.textContent = `Showing top ${HEATMAP_MAX_TICKERS} tickers by signal strength.`;
    container.appendChild(note);
  }

  // ── Canvas
  const canvasWrap = document.createElement('div');
  canvasWrap.className = 'heatmap-canvas-wrap';
  const canvas = document.createElement('canvas');
  canvas.className = 'heatmap-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'Market heatmap treemap');
  canvasWrap.appendChild(canvas);
  container.appendChild(canvasWrap);

  // ── Tooltip
  const tooltip = document.createElement('div');
  tooltip.className = 'heatmap-tooltip';
  tooltip.hidden = true;
  container.appendChild(tooltip);

  // Draw after layout (so offsetWidth is known)
  requestAnimationFrame(() => {
    _drawHeatmap(canvas, tooltip, sectorGroups, latestMap);
    // Redraw on container resize
    const observer = new ResizeObserver(() => {
      _drawHeatmap(canvas, tooltip, sectorGroups, latestMap);
    });
    observer.observe(canvasWrap);
    canvas._resizeObserver = observer;
  });
}

// ─── Drawing ──────────────────────────────────────────────────

function _drawHeatmap(canvas, tooltip, sectorGroups, latestMap) {
  const wrap = canvas.parentElement;
  const W = wrap.clientWidth  || 600;
  const H = Math.max(400, Math.round(W * 0.55));

  canvas.width  = W;
  canvas.height = H;

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  // Gather all stocks in sector order
  const stocks = [];
  const sortedSectors = Array.from(sectorGroups.keys()).sort();
  for (const sector of sortedSectors) {
    for (const item of sectorGroups.get(sector)) {
      stocks.push({ ...item, sector });
    }
  }

  if (stocks.length === 0) return;

  // Size cells by |predictedReturn| × confidence, with a minimum floor so
  // every cell is visible. Falls back to equal weight when no return data.
  const MIN_WEIGHT = 0.2;
  const values = stocks.map(s => {
    const ret = s.pred?.predictedReturn;
    const conf = s.pred?.confidence ?? 0.5;
    return ret != null
      ? Math.max(MIN_WEIGHT, Math.abs(ret) * (1 + conf))
      : 1;
  });
  const rects  = squarify(values, 0, 0, W, H);

  // Store rect data for hit-testing
  canvas._cells = [];

  for (let i = 0; i < stocks.length; i++) {
    const { symbol, pred, sector } = stocks[i];
    const { x, y, w, h } = rects[i];
    if (w < 1 || h < 1) continue;

    const color = _predictionColor(pred);
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);

    // Border
    ctx.strokeStyle = 'rgba(15,17,23,0.8)';
    ctx.lineWidth   = 1.5;
    ctx.strokeRect(x + 0.75, y + 0.75, w - 1.5, h - 1.5);

    // Label (only if cell is large enough)
    if (w > 36 && h > 20) {
      ctx.save();
      ctx.fillStyle = 'rgba(255,255,255,0.92)';
      const fontSize = Math.min(13, Math.max(9, Math.floor(Math.min(w, h) / 5)));
      ctx.font       = `700 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      ctx.textAlign  = 'center';
      ctx.textBaseline = 'middle';
      // Clip to cell
      ctx.beginPath();
      ctx.rect(x + 2, y + 2, w - 4, h - 4);
      ctx.clip();

      const retPct = pred?.predictedReturn != null
        ? `${pred.predictedReturn >= 0 ? '+' : ''}${(pred.predictedReturn * 100).toFixed(1)}%`
        : null;

      if (h > 36 && retPct) {
        // Two-line label: symbol + return %
        ctx.fillText(symbol, x + w / 2, y + h / 2 - fontSize * 0.6);
        ctx.font = `400 ${Math.max(8, fontSize - 2)}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
        ctx.fillStyle = 'rgba(255,255,255,0.75)';
        ctx.fillText(retPct, x + w / 2, y + h / 2 + fontSize * 0.7);
      } else {
        ctx.fillText(symbol, x + w / 2, y + h / 2);
      }
      ctx.restore();
    }

    canvas._cells.push({ x, y, w, h, symbol, pred, sector });
  }

  // Wire up pointer events (attach only once per canvas instance)
  if (!canvas._eventsWired) {
    canvas._eventsWired = true;
    _wireCanvasEvents(canvas, tooltip, latestMap);
  }
}

function _wireCanvasEvents(canvas, tooltip, latestMap) {
  canvas.style.cursor = 'pointer';

  canvas.addEventListener('pointermove', e => {
    const cell = _hitTest(canvas, e);
    if (!cell) {
      tooltip.hidden = true;
      return;
    }

    const pred = cell.pred;
    // Derive direction from predictedReturn when available (matches color logic)
    const isUp = pred?.predictedReturn != null
      ? pred.predictedReturn >= 0
      : pred?.direction === 'UP';
    const dir  = pred ? (isUp ? '▲ UP' : '▼ DOWN') : '—';
    const conf = pred ? `${Math.round((pred.confidence ?? 0) * 100)}%` : '—';
    const prob = pred ? `${Math.round((pred.probability ?? 0.5) * 100)}%` : '—';
    const retPct = pred?.predictedReturn != null
      ? `${pred.predictedReturn >= 0 ? '+' : ''}${(pred.predictedReturn * 100).toFixed(2)}%`
      : null;

    tooltip.innerHTML = `
      <strong>${_escHtml(cell.symbol)}</strong>
      <span class="heatmap-tooltip__sector">${_escHtml(cell.sector)}</span>
      <span class="heatmap-tooltip__dir heatmap-tooltip__dir--${isUp ? 'up' : 'down'}">${dir}</span>
      ${retPct ? `<span>Predicted: ${_escHtml(retPct)}</span>` : ''}
      <span>Confidence: ${conf}</span>
      <span>Probability: ${prob}</span>
    `;
    tooltip.hidden = false;

    // Position tooltip in CSS pixels relative to the canvas wrapper.
    // Use wrap.clientWidth (CSS px) — canvas.width may be in physical px on HiDPI.
    const wrap = canvas.parentElement;
    const rect = canvas.getBoundingClientRect();
    const tx = e.clientX - rect.left;
    const ty = e.clientY - rect.top;
    const wrapW = wrap.clientWidth;
    const tipW  = tooltip.offsetWidth  || 160;
    const tipH  = tooltip.offsetHeight || 80;
    tooltip.style.left = `${Math.max(8, Math.min(tx + 12, wrapW - tipW - 8))}px`;
    tooltip.style.top  = `${Math.max(ty - tipH - 8, 8)}px`;
  });

  canvas.addEventListener('pointerleave', () => {
    tooltip.hidden = true;
  });

  canvas.addEventListener('click', e => {
    const cell = _hitTest(canvas, e);
    if (!cell) return;
    // Dispatch event so app.js / dashboard can open detail modal
    canvas.dispatchEvent(new CustomEvent('heatmap-cell-click', {
      bubbles:   true,
      composed:  true,
      detail:    { symbol: cell.symbol, pred: cell.pred },
    }));
  });
}

function _hitTest(canvas, e) {
  if (!canvas._cells) return null;
  const rect = canvas.getBoundingClientRect();
  const mx   = e.clientX - rect.left;
  const my   = e.clientY - rect.top;
  for (const cell of canvas._cells) {
    if (mx >= cell.x && mx <= cell.x + cell.w && my >= cell.y && my <= cell.y + cell.h) {
      return cell;
    }
  }
  return null;
}
