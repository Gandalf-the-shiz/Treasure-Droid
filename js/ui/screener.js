/**
 * js/ui/screener.js
 * Stock Screener with Filters — Phase 7.
 *
 * Renders a filterable, sortable, paginated table of all stocks with
 * their latest AI prediction data.
 *
 * Filter controls:
 *   - Direction: UP / DOWN / All
 *   - Confidence threshold: ≥50% … ≥90%
 *   - Sector: dropdown
 *   - Sort by: Confidence (desc), Symbol (asc), Sector, Delta
 *
 * Table columns: Symbol, Sector, Direction, Confidence, Predicted Price,
 *                Current Price, Delta
 *
 * Export: renderScreener(container, predictionsData, appState)
 * Lazy-loaded by app.js.
 */

import { getPredictions }  from '../ml/tracker.js';
import { demoPrediction }  from '../ml/prediction.js';
import { formatCurrency, escapeHtml as _escHtml } from '../utils/helpers.js';

// ─── Constants ───────────────────────────────────────────────

const PAGE_SIZE = 50;

const DEMO_SECTORS = {
  AAPL:  'Technology', GOOGL: 'Technology', MSFT:  'Technology',
  AMZN:  'Consumer Discretionary', TSLA: 'Consumer Discretionary',
  META:  'Technology', NVDA:  'Technology', NFLX: 'Communication Services',
  JPM:   'Financials', V:    'Financials',  JNJ:  'Healthcare',
  PFE:   'Healthcare', XOM:  'Energy',      CVX:  'Energy',
  GS:    'Financials', BAC:  'Financials',  WMT:  'Consumer Staples',
  KO:    'Consumer Staples', DIS: 'Communication Services', BA: 'Industrials',
};

const ALL_SECTORS = [
  'All', 'Communication Services', 'Consumer Discretionary', 'Consumer Staples',
  'Energy', 'Financials', 'Healthcare', 'Industrials', 'Materials',
  'Real Estate', 'Technology', 'Utilities', 'Other',
];

const SORT_OPTIONS = [
  { value: 'confidence_desc', label: 'Confidence (High → Low)' },
  { value: 'confidence_asc',  label: 'Confidence (Low → High)' },
  { value: 'symbol_asc',      label: 'Symbol (A → Z)' },
  { value: 'symbol_desc',     label: 'Symbol (Z → A)' },
  { value: 'delta_desc',      label: 'Delta (Largest)' },
  { value: 'sector_asc',      label: 'Sector (A → Z)' },
];

// ─── Module state ─────────────────────────────────────────────

/** @type {{ direction: string, minConf: number, sector: string, sortBy: string, page: number }} */
let _filters = {
  direction: 'all',
  minConf:   0.5,
  sector:    'All',
  sortBy:    'confidence_desc',
  page:      1,
};

/** @type {Array} */
let _allRows = [];

/** @type {HTMLElement|null} */
let _tableBody = null;
let _paginationEl = null;
let _countEl = null;

/** @type {boolean} */
let _isV2Mode = false;

// ─── Public API ───────────────────────────────────────────────

/**
 * Render (or refresh) the screener view.
 *
 * @param {HTMLElement} container
 * @param {Object[]|null} predictionsData  - Optional override; uses tracker if null
 * @param {{ mode: 'demo'|'live' }} appState
 */
export function renderScreener(container, predictionsData, appState) {
  container.innerHTML = '';
  _filters = { direction: 'all', minConf: 0.5, sector: 'All', sortBy: 'confidence_desc', page: 1 };

  // ── Collect latest predictions
  let predictions = predictionsData;
  if (!predictions || predictions.length === 0) {
    predictions = getPredictions();
  }

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

  _allRows = Array.from(latestMap.values()).map(pred => ({
    symbol:         pred.symbol,
    sector:         DEMO_SECTORS[pred.symbol] ?? 'Other',
    direction:      pred.direction,
    confidence:     pred.confidence ?? 0,
    probability:    pred.probability ?? 0.5,
    predictedPrice: pred.predictedPrice ?? 0,
    currentPrice:   pred.currentPrice ?? 0,
    delta:          pred.delta ?? 0,
    predictedReturn: pred.predictedReturn ?? null,
  }));

  // Detect V2 mode: predictions have no live prices (predictedPrice === 0 but predictedReturn available)
  _isV2Mode = _allRows.length > 0 &&
    _allRows[0].predictedPrice === 0 &&
    _allRows[0].predictedReturn !== null;

  // ── Panel title
  const title = document.createElement('h2');
  title.className = 'screener-title';
  title.textContent = '🔍 Stock Screener';
  container.appendChild(title);

  if (appState.mode === 'demo' && (!predictionsData || predictionsData.length === 0)) {
    const note = document.createElement('p');
    note.className = 'screener-demo-note';
    note.textContent = 'Demo mode — showing sample predictions.';
    container.appendChild(note);
  }

  // ── Filter bar
  container.appendChild(_buildFilterBar());

  // ── Count
  _countEl = document.createElement('p');
  _countEl.className = 'screener-count';
  container.appendChild(_countEl);

  // ── Table
  const tableWrap = document.createElement('div');
  tableWrap.className = 'screener-table-wrap';

  const table = document.createElement('table');
  table.className = 'screener-table';
  table.setAttribute('role', 'table');
  table.innerHTML = `
    <thead>
      <tr>
        <th scope="col">Symbol</th>
        <th scope="col">Sector</th>
        <th scope="col">Direction</th>
        <th scope="col">Confidence</th>
        <th scope="col">${_isV2Mode ? 'Return' : 'Predicted'}</th>
        <th scope="col">${_isV2Mode ? 'Probability' : 'Current'}</th>
        <th scope="col">${_isV2Mode ? 'Confidence' : 'Delta'}</th>
      </tr>
    </thead>
    <tbody id="screener-tbody"></tbody>
  `;
  tableWrap.appendChild(table);
  container.appendChild(tableWrap);

  _tableBody = table.querySelector('#screener-tbody');

  // ── Pagination
  _paginationEl = document.createElement('div');
  _paginationEl.className = 'screener-pagination';
  container.appendChild(_paginationEl);

  _applyFilters();
}

// ─── Filter bar ───────────────────────────────────────────────

function _buildFilterBar() {
  const bar = document.createElement('div');
  bar.className = 'screener-filter-bar';

  // Direction toggles
  const dirGroup = document.createElement('div');
  dirGroup.className = 'screener-filter-group';
  const dirLabel = document.createElement('label');
  dirLabel.className = 'screener-filter-label';
  dirLabel.textContent = 'Direction';
  dirGroup.appendChild(dirLabel);

  const dirBtns = document.createElement('div');
  dirBtns.className = 'screener-dir-btns';
  [['all', 'All'], ['UP', '▲ UP'], ['DOWN', '▼ DOWN']].forEach(([val, label]) => {
    const btn = document.createElement('button');
    btn.className = `screener-dir-btn${val === 'all' ? ' screener-dir-btn--active' : ''}`;
    btn.dataset.dir = val;
    btn.textContent = label;
    btn.addEventListener('click', () => {
      _filters.direction = val;
      _filters.page = 1;
      bar.querySelectorAll('.screener-dir-btn').forEach(b => {
        b.classList.toggle('screener-dir-btn--active', b.dataset.dir === val);
      });
      _applyFilters();
    });
    dirBtns.appendChild(btn);
  });
  dirGroup.appendChild(dirBtns);
  bar.appendChild(dirGroup);

  // Confidence threshold
  const confGroup = document.createElement('div');
  confGroup.className = 'screener-filter-group';
  const confLabel = document.createElement('label');
  confLabel.className = 'screener-filter-label';
  confLabel.setAttribute('for', 'screener-conf-select');
  confLabel.textContent = 'Min Confidence';
  confGroup.appendChild(confLabel);

  const confSelect = document.createElement('select');
  confSelect.id = 'screener-conf-select';
  confSelect.className = 'screener-select';
  [50, 60, 70, 80, 90].forEach(pct => {
    const opt = document.createElement('option');
    opt.value  = String(pct / 100);
    opt.textContent = `≥ ${pct}%`;
    confSelect.appendChild(opt);
  });
  confSelect.addEventListener('change', () => {
    _filters.minConf = parseFloat(confSelect.value);
    _filters.page = 1;
    _applyFilters();
  });
  confGroup.appendChild(confSelect);
  bar.appendChild(confGroup);

  // Sector dropdown
  const sectorGroup = document.createElement('div');
  sectorGroup.className = 'screener-filter-group';
  const sectorLabel = document.createElement('label');
  sectorLabel.className = 'screener-filter-label';
  sectorLabel.setAttribute('for', 'screener-sector-select');
  sectorLabel.textContent = 'Sector';
  sectorGroup.appendChild(sectorLabel);

  const sectorSelect = document.createElement('select');
  sectorSelect.id = 'screener-sector-select';
  sectorSelect.className = 'screener-select';
  ALL_SECTORS.forEach(s => {
    const opt = document.createElement('option');
    opt.value       = s;
    opt.textContent = s;
    sectorSelect.appendChild(opt);
  });
  sectorSelect.addEventListener('change', () => {
    _filters.sector = sectorSelect.value;
    _filters.page = 1;
    _applyFilters();
  });
  sectorGroup.appendChild(sectorSelect);
  bar.appendChild(sectorGroup);

  // Sort
  const sortGroup = document.createElement('div');
  sortGroup.className = 'screener-filter-group';
  const sortLabel = document.createElement('label');
  sortLabel.className = 'screener-filter-label';
  sortLabel.setAttribute('for', 'screener-sort-select');
  sortLabel.textContent = 'Sort By';
  sortGroup.appendChild(sortLabel);

  const sortSelect = document.createElement('select');
  sortSelect.id = 'screener-sort-select';
  sortSelect.className = 'screener-select';
  SORT_OPTIONS.forEach(({ value, label }) => {
    const opt = document.createElement('option');
    opt.value       = value;
    opt.textContent = label;
    sortSelect.appendChild(opt);
  });
  sortSelect.addEventListener('change', () => {
    _filters.sortBy = sortSelect.value;
    _filters.page = 1;
    _applyFilters();
  });
  sortGroup.appendChild(sortSelect);
  bar.appendChild(sortGroup);

  return bar;
}

// ─── Filter + render logic ────────────────────────────────────

function _applyFilters() {
  if (!_tableBody) return;

  let rows = _allRows.slice();

  // Direction filter
  if (_filters.direction !== 'all') {
    rows = rows.filter(r => r.direction === _filters.direction);
  }

  // Confidence filter
  rows = rows.filter(r => r.confidence >= _filters.minConf);

  // Sector filter
  if (_filters.sector !== 'All') {
    rows = rows.filter(r => r.sector === _filters.sector);
  }

  // Sort
  rows = _sortRows(rows, _filters.sortBy);

  // Count
  if (_countEl) {
    _countEl.textContent = `${rows.length} result${rows.length !== 1 ? 's' : ''}`;
  }

  // Pagination
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  _filters.page = Math.min(_filters.page, totalPages);
  const start = (_filters.page - 1) * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  // Render rows
  _tableBody.innerHTML = '';
  if (pageRows.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="7" class="screener-empty">No stocks match the current filters.</td>`;
    _tableBody.appendChild(tr);
  } else {
    for (const row of pageRows) {
      _tableBody.appendChild(_buildRow(row));
    }
  }

  // Render pagination
  if (_paginationEl) {
    _renderPagination(totalPages, rows);
  }
}

function _sortRows(rows, sortBy) {
  return rows.slice().sort((a, b) => {
    switch (sortBy) {
      case 'confidence_desc': return b.confidence - a.confidence;
      case 'confidence_asc':  return a.confidence - b.confidence;
      case 'symbol_asc':      return a.symbol.localeCompare(b.symbol);
      case 'symbol_desc':     return b.symbol.localeCompare(a.symbol);
      case 'delta_desc':      return _isV2Mode
        ? Math.abs(b.predictedReturn ?? 0) - Math.abs(a.predictedReturn ?? 0)
        : Math.abs(b.delta) - Math.abs(a.delta);
      case 'sector_asc':      return a.sector.localeCompare(b.sector);
      default:                return 0;
    }
  });
}

function _buildRow(row) {
  const tr = document.createElement('tr');
  tr.className = 'screener-row';
  tr.setAttribute('role', 'row');

  const isUp     = row.direction === 'UP';
  const dirClass = isUp ? 'screener-badge screener-badge--up' : 'screener-badge screener-badge--down';
  const dirText  = isUp ? '▲ UP' : '▼ DOWN';

  // Columns 5–7 differ between V2 (prediction-only) and live mode
  let col5, col6, col7;
  if (_isV2Mode) {
    // Return: predicted return %
    const retPct = row.predictedReturn != null
      ? `${isUp ? '+' : ''}${(row.predictedReturn * 100).toFixed(2)}%`
      : '—';
    const retClass = isUp ? 'screener-delta--up' : 'screener-delta--down';
    col5 = `<span class="${retClass}">${_escHtml(retPct)}</span>`;

    // Probability
    const probPct = Math.round((row.probability ?? 0.5) * 100);
    col6 = `${probPct}%`;

    // Confidence bar
    const confPct = Math.round(row.confidence * 100);
    const confTier = row.confidence >= 0.75 ? 'high' : row.confidence >= 0.6 ? 'medium' : 'low';
    col7 = `<div class="conf-gauge" style="min-width:60px;"><div class="conf-gauge__fill conf-gauge__fill--${confTier}" style="width:${confPct}%"></div></div>`;
  } else {
    const deltaStr = row.delta >= 0
      ? `+${formatCurrency(row.delta)}`
      : formatCurrency(row.delta);
    const deltaClass = row.delta >= 0 ? 'screener-delta--up' : 'screener-delta--down';
    col5 = formatCurrency(row.predictedPrice);
    col6 = formatCurrency(row.currentPrice);
    col7 = `<span class="${deltaClass}">${deltaStr}</span>`;
  }

  tr.innerHTML = `
    <td class="screener-cell screener-cell--symbol"><strong>${_escHtml(row.symbol)}</strong></td>
    <td class="screener-cell screener-cell--sector">${_escHtml(row.sector)}</td>
    <td class="screener-cell"><span class="${dirClass}">${dirText}</span></td>
    <td class="screener-cell">${Math.round(row.confidence * 100)}%</td>
    <td class="screener-cell">${col5}</td>
    <td class="screener-cell">${col6}</td>
    <td class="screener-cell">${col7}</td>
  `;

  // Click to open detail (dispatch event)
  tr.addEventListener('click', () => {
    tr.dispatchEvent(new CustomEvent('screener-row-click', {
      bubbles:  true,
      composed: true,
      detail:   {
        symbol:    row.symbol,
        direction: row.direction,
        confidence: row.confidence,
        probability: row.probability,
        predictedReturn: row.predictedReturn,
        delta:     row.delta,
        currentPrice: row.currentPrice,
        predictedPrice: row.predictedPrice,
      },
    }));
  });
  tr.style.cursor = 'pointer';

  return tr;
}

// ─── Pagination ───────────────────────────────────────────────

function _renderPagination(totalPages, allFilteredRows) {
  _paginationEl.innerHTML = '';
  if (totalPages <= 1) return;

  const prevBtn = document.createElement('button');
  prevBtn.className = 'screener-page-btn';
  prevBtn.textContent = '← Prev';
  prevBtn.disabled = _filters.page <= 1;
  prevBtn.addEventListener('click', () => {
    if (_filters.page > 1) { _filters.page--; _applyFilters(); }
  });
  _paginationEl.appendChild(prevBtn);

  const pageInfo = document.createElement('span');
  pageInfo.className = 'screener-page-info';
  pageInfo.textContent = `Page ${_filters.page} of ${totalPages}`;
  _paginationEl.appendChild(pageInfo);

  const nextBtn = document.createElement('button');
  nextBtn.className = 'screener-page-btn';
  nextBtn.textContent = 'Next →';
  nextBtn.disabled = _filters.page >= totalPages;
  nextBtn.addEventListener('click', () => {
    if (_filters.page < totalPages) { _filters.page++; _applyFilters(); }
  });
  _paginationEl.appendChild(nextBtn);
}


