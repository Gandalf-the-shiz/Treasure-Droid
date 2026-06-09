/**
 * js/ui/sectors.js
 * Sector / industry analysis view — Phase 6.
 *
 * Groups watchlist (and demo) stocks by sector, shows aggregate
 * prediction direction and average confidence per sector.
 * Works fully in demo mode using hardcoded sector assignments
 * for the demo stocks (AAPL, GOOGL, MSFT, AMZN, TSLA).
 *
 * Dependencies: js/ml/tracker.js, js/utils/helpers.js
 */

import { getPredictions } from '../ml/tracker.js';
import { formatPercent, escapeHtml as _escapeHtml } from '../utils/helpers.js';

// ─── Sector definitions ───────────────────────────────────────

/**
 * Hardcoded sector assignments used in demo mode and as a fallback
 * when a company profile has not been loaded yet.
 *
 * @type {Object.<string, string>}
 */
const DEMO_SECTORS = {
  AAPL:  'Technology',
  GOOGL: 'Technology',
  MSFT:  'Technology',
  AMZN:  'Consumer Discretionary',
  TSLA:  'Consumer Discretionary',
  META:  'Technology',
  NVDA:  'Technology',
  NFLX:  'Communication Services',
  JPM:   'Financials',
  V:     'Financials',
  JNJ:   'Healthcare',
  PFE:   'Healthcare',
  XOM:   'Energy',
  CVX:   'Energy',
  GS:    'Financials',
  BAC:   'Financials',
  WMT:   'Consumer Staples',
  KO:    'Consumer Staples',
  DIS:   'Communication Services',
  BA:    'Industrials',
};

/** Sector display order and emoji badges. */
const SECTOR_META = {
  'Technology':             { emoji: '💻', order: 1 },
  'Consumer Discretionary': { emoji: '🛍️', order: 2 },
  'Financials':             { emoji: '🏦', order: 3 },
  'Healthcare':             { emoji: '🏥', order: 4 },
  'Communication Services': { emoji: '📡', order: 5 },
  'Energy':                 { emoji: '⚡', order: 6 },
  'Consumer Staples':       { emoji: '🛒', order: 7 },
  'Industrials':            { emoji: '⚙️', order: 8 },
  'Other':                  { emoji: '📊', order: 99 },
};

// ─── Public API ───────────────────────────────────────────────

/**
 * Render the sectors analysis panel into the given container element.
 * Reads the most recent prediction per tracked symbol and groups them.
 *
 * @param {HTMLElement} container
 * @param {{ mode: 'demo'|'live' }} appState
 * @param {Object.<string, string>} [symbolSectorMap={}]  - Live sector data keyed by symbol
 */
export function renderSectorsPanel(container, appState, symbolSectorMap = {}) {
  container.innerHTML = '';

  const panel = document.createElement('div');
  panel.className = 'sectors-panel';

  const title = document.createElement('h2');
  title.className = 'sectors-panel__title';
  title.textContent = '🏭 Sector Analysis';
  panel.appendChild(title);

  const subtitle = document.createElement('p');
  subtitle.className = 'sectors-panel__subtitle';
  subtitle.textContent = 'Aggregate AI predictions grouped by sector/industry. Based on the most recent prediction per symbol.';
  panel.appendChild(subtitle);

  // Gather the most recent prediction per symbol from tracker
  const allPredictions = getPredictions();
  const latestBySymbol = _getLatestPerSymbol(allPredictions);

  if (latestBySymbol.size === 0) {
    const empty = document.createElement('p');
    empty.className = 'sectors-empty';
    empty.textContent = 'No predictions yet. Load stocks on the Dashboard to generate predictions.';
    panel.appendChild(empty);
    container.appendChild(panel);
    return;
  }

  // Build sector → predictions map
  const sectorMap = _groupBySector(latestBySymbol, { ...DEMO_SECTORS, ...symbolSectorMap });

  // Render each sector card, sorted by meta order
  const sorted = Array.from(sectorMap.entries())
    .sort(([a], [b]) => {
      const orderA = (SECTOR_META[a] || SECTOR_META['Other']).order;
      const orderB = (SECTOR_META[b] || SECTOR_META['Other']).order;
      return orderA - orderB;
    });

  const grid = document.createElement('div');
  grid.className = 'sectors-grid';

  for (const [sector, preds] of sorted) {
    grid.appendChild(_buildSectorCard(sector, preds));
  }

  panel.appendChild(grid);
  container.appendChild(panel);
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * Return a Map of symbol → most recent prediction.
 *
 * @param {import('../ml/tracker.js').TrackedPrediction[]} predictions
 * @returns {Map<string, import('../ml/tracker.js').TrackedPrediction>}
 */
function _getLatestPerSymbol(predictions) {
  const map = new Map();
  for (const p of predictions) {
    const existing = map.get(p.symbol);
    if (!existing || p.generatedAt > existing.generatedAt) {
      map.set(p.symbol, p);
    }
  }
  return map;
}

/**
 * Group a symbol→prediction map by sector.
 *
 * @param {Map<string, Object>} latestBySymbol
 * @param {Object.<string, string>} sectorLookup
 * @returns {Map<string, Object[]>}
 */
function _groupBySector(latestBySymbol, sectorLookup) {
  const map = new Map();
  for (const [symbol, pred] of latestBySymbol) {
    const sector = sectorLookup[symbol] || 'Other';
    if (!map.has(sector)) map.set(sector, []);
    map.get(sector).push({ symbol, pred });
  }
  return map;
}

/**
 * Build a sector summary card DOM element.
 *
 * @param {string} sector
 * @param {{ symbol: string, pred: Object }[]} items
 * @returns {HTMLElement}
 */
function _buildSectorCard(sector, items) {
  const meta = SECTOR_META[sector] || SECTOR_META['Other'];

  const upCount   = items.filter(i => i.pred.direction === 'UP').length;
  const downCount = items.filter(i => i.pred.direction === 'DOWN').length;
  const total     = items.length;
  const bullishPct = total > 0 ? Math.round((upCount / total) * 100) : 0;

  const avgConfidence = items.reduce((sum, i) => sum + (i.pred.confidence || 0), 0) / total;
  const sentiment = bullishPct >= 60 ? 'bullish' : bullishPct <= 40 ? 'bearish' : 'neutral';

  const card = document.createElement('div');
  card.className = `sector-card sector-card--${sentiment}`;

  card.innerHTML = `
    <div class="sector-card__header">
      <span class="sector-card__emoji">${meta.emoji}</span>
      <div>
        <div class="sector-card__name">${_escapeHtml(sector)}</div>
        <div class="sector-card__count">${total} stock${total !== 1 ? 's' : ''}</div>
      </div>
      <span class="sector-card__badge sector-card__badge--${sentiment}">
        ${sentiment.charAt(0).toUpperCase() + sentiment.slice(1)}
      </span>
    </div>
    <div class="sector-card__bar-wrap">
      <div class="sector-card__bar">
        <div class="sector-card__bar-fill sector-card__bar-fill--up" style="width:${bullishPct}%"></div>
      </div>
      <div class="sector-card__bar-labels">
        <span class="sector-card__bar-up">▲ ${upCount} UP (${bullishPct}%)</span>
        <span class="sector-card__bar-down">▼ ${downCount} DOWN</span>
      </div>
    </div>
    <div class="sector-card__meta">
      <span>Avg confidence: <strong>${Math.round(avgConfidence * 100)}%</strong></span>
    </div>
    <div class="sector-card__symbols">
      ${items.map(({ symbol, pred }) => `
        <span class="sector-symbol sector-symbol--${pred.direction === 'UP' ? 'up' : 'down'}">
          ${_escapeHtml(symbol)} ${pred.direction === 'UP' ? '▲' : '▼'}
        </span>
      `).join('')}
    </div>
  `;

  return card;
}

