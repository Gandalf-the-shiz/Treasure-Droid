/**
 * js/ui/stockcard.js
 * Stock card component — renders a single stock card DOM element.
 *
 * Each card displays:
 *  - Symbol + company name
 *  - Current price + change ($ and %)
 *  - Mini sparkline chart (if Chart.js available)
 *  - OHLCV compact row (Open, High, Low, Volume)
 *  - Daily range bar with current price marker
 *  - ML prediction (UP/DOWN + dollar amount)
 *  - Watchlist toggle button (persisted in localStorage)
 *
 * Phase 1: Renders from demo data with demo predictions.
 * Phase 3: Adds watchlist persistence, OHLCV row, range bar, glow effects, stagger animation.
 * Phase 4+: Real ML predictions replace demo predictions.
 */

import { formatCurrency, formatPercent, formatDollarChange, formatLargeNumber, escapeHtml } from '../utils/helpers.js';
import { renderSparkline } from './charts.js';
import { isInWatchlist, addToWatchlist, removeFromWatchlist } from './watchlist.js';

/**
 * @typedef {Object} StockData
 * @property {string} symbol
 * @property {string} name
 * @property {Object} quote
 * @property {number} quote.current
 * @property {number} quote.open
 * @property {number} quote.high
 * @property {number} quote.low
 * @property {number} quote.previousClose
 * @property {number} quote.change
 * @property {number} quote.changePercent
 * @property {number} quote.volume
 * @property {number[]} quote.history  - Array of recent close prices for sparkline
 */

/**
 * @typedef {import('../ml/prediction.js').Prediction} Prediction
 */

/**
 * Create and return a stock card DOM element.
 * @param {StockData} stock
 * @param {Prediction} prediction
 * @param {boolean} chartAvailable  - Whether Chart.js is loaded
 * @returns {HTMLElement}
 */
export function renderStockCard(stock, prediction, chartAvailable) {
  const isUp   = stock.quote.change >= 0;
  const predUp = prediction.direction === 'UP';
  const inWL   = isInWatchlist(stock.symbol);

  // V2 mode: stock was built from pipeline predictions (no live prices available)
  const isV2 = !!stock._v2Prediction;

  // Determine the card's gain/loss class
  const gainLossClass = isV2 ? (predUp ? 'gainer' : 'loser') : (isUp ? 'gainer' : 'loser');
  const card = document.createElement('div');
  card.className = `stock-card stock-card--${gainLossClass}${isV2 ? ' stock-card--v2' : ''}`;
  card.setAttribute('role', 'article');
  card.setAttribute('aria-label', `${stock.symbol} stock card`);
  card.dataset.symbol = stock.symbol;

  // Range bar calculation (only meaningful with live prices)
  const low     = stock.quote.low  || 0;
  const high    = stock.quote.high || 0;
  const current = stock.quote.current || 0;
  const rangeWidth = high > low ? Math.round(((current - low) / (high - low)) * 100) : 50;

  // Confidence gauge tier
  const confTier = prediction.confidence >= 0.75 ? 'high' : prediction.confidence >= 0.6 ? 'medium' : 'low';
  const confPct  = Math.round(prediction.confidence * 100);

  // V2 visual block: replaces the chart container to fill the visual gap
  const v2VisualHTML = `
    <div class="stock-card__v2-visual">
      <div class="stock-card__v2-visual__return stock-card__v2-visual__return--${predUp ? 'up' : 'down'}">
        ${prediction.predictedReturn != null
          ? `<span class="stock-card__v2-visual__pct">${predUp ? '+' : ''}${(prediction.predictedReturn * 100).toFixed(2)}%</span>`
          : `<span class="stock-card__v2-visual__pct">${predUp ? '▲' : '▼'}</span>`
        }
        <span class="stock-card__v2-visual__label">Predicted Return</span>
      </div>
      <div class="stock-card__v2-visual__bar" role="meter" aria-valuenow="${confPct}" aria-valuemin="0" aria-valuemax="100" aria-label="Prediction confidence level: ${confPct} percent">
        <div class="stock-card__v2-visual__fill stock-card__v2-visual__fill--${confTier}" style="width:${confPct}%;"></div>
      </div>
    </div>`;

  // Prediction section HTML differs for V2 vs live mode
  const predictionHTML = isV2
    ? `<div class="stock-card__prediction">
        <div style="display:flex;align-items:center;gap:var(--space-2);">
          <span class="stock-card__pred-dir stock-card__pred-dir--${predUp ? 'up' : 'down'}">
            ${predUp ? '▲' : '▼'} ${predUp ? 'UP' : 'DOWN'}
          </span>
          <span class="stock-card__prediction-badge stock-card__prediction-badge--${confTier}" style="margin-left:auto;">${confPct}% confidence</span>
        </div>
      </div>`
    : `<div class="stock-card__prediction">
        <span class="stock-card__prediction-label">${prediction.isDemo ? '📊' : '🧠'} Prediction:</span>
        <span class="stock-card__prediction-value stock-card__prediction-value--${predUp ? 'up' : 'down'}">
          ${predUp ? '▲' : '▼'} ${prediction.delta === 0 && prediction.predictedReturn != null
            ? `${predUp ? '+' : ''}${(prediction.predictedReturn * 100).toFixed(2)}%`
            : formatDollarChange(predUp ? prediction.delta : -prediction.delta)
          }
        </span>
        ${prediction.isDemo
          ? '<span class="stock-card__prediction-badge">Demo</span>'
          : `<span class="stock-card__prediction-badge stock-card__prediction-badge--${confTier}">${confPct}%</span>`
        }
        <div class="conf-gauge">
          <div class="conf-gauge__fill conf-gauge__fill--${confTier}" style="width:${confPct}%"></div>
        </div>
      </div>`;

  card.innerHTML = `
    <div class="stock-card__header">
      <div>
        <div class="stock-card__symbol">${escapeHtml(stock.symbol)}</div>
        <div class="stock-card__name" title="${escapeHtml(stock.name)}">${escapeHtml(stock.name)}</div>
      </div>
      <button
        class="stock-card__watchlist-btn${inWL ? ' stock-card__watchlist-btn--active' : ''}"
        aria-label="${inWL ? 'Remove' : 'Add'} ${escapeHtml(stock.symbol)} ${inWL ? 'from' : 'to'} watchlist"
        data-symbol="${escapeHtml(stock.symbol)}"
      >${inWL ? '★' : '☆'}</button>
    </div>

    <div class="stock-card__price-row">
      <span class="stock-card__price">${isV2 ? '—' : formatCurrency(stock.quote.current)}</span>
      ${isV2
        ? '<span class="stock-card__change stock-card__change--up" style="opacity:0.4;">--</span>'
        : `<span class="stock-card__change stock-card__change--${isUp ? 'up' : 'down'}">
            ${formatDollarChange(stock.quote.change)} (${formatPercent(stock.quote.changePercent)})
           </span>`
      }
    </div>

    ${isV2 ? v2VisualHTML : `<div class="stock-card__chart-container" id="chart-${escapeHtml(stock.symbol)}">
      ${chartAvailable ? '' : '<p style="font-size:11px;color:var(--color-text-faint);text-align:center;padding:8px 0;">Chart unavailable</p>'}
    </div>`}

    ${isV2 ? '' : `
    <div class="stock-card__ohlcv-row">
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">O</span><span class="stock-card__ohlcv-value">${formatCurrency(stock.quote.open || 0)}</span></div>
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">H</span><span class="stock-card__ohlcv-value stock-card__ohlcv-value--up">${formatCurrency(stock.quote.high || 0)}</span></div>
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">L</span><span class="stock-card__ohlcv-value stock-card__ohlcv-value--down">${formatCurrency(stock.quote.low || 0)}</span></div>
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">Vol</span><span class="stock-card__ohlcv-value">${stock.quote.volume ? formatLargeNumber(stock.quote.volume) : '—'}</span></div>
    </div>

    <div class="stock-card__range-bar" aria-label="Daily range: low ${formatCurrency(low)} to high ${formatCurrency(high)}">
      <span class="stock-card__range-label">${formatCurrency(low)}</span>
      <div class="stock-card__range-track">
        <div class="stock-card__range-fill" style="width:${rangeWidth}%"></div>
        <div class="stock-card__range-marker" style="left:${rangeWidth}%"></div>
      </div>
      <span class="stock-card__range-label">${formatCurrency(high)}</span>
    </div>
    `}

    ${predictionHTML}
  `;

  // Render sparkline chart lazily (only when the card enters the viewport)
  if (!isV2 && chartAvailable && stock.quote.history && stock.quote.history.length > 0) {
    const chartContainer = card.querySelector(`#chart-${stock.symbol}`);
    if (chartContainer) {
      _observeSparkline(chartContainer, stock.quote.history, isUp);
    }
  }

  // Watchlist toggle
  const watchBtn = card.querySelector('.stock-card__watchlist-btn');
  watchBtn?.addEventListener('click', e => {
    e.stopPropagation();
    _toggleWatchlist(stock.symbol, watchBtn);
  });

  // Card click → open detail view (wired by dashboard.js via data-symbol)
  card.addEventListener('click', () => {
    card.dispatchEvent(new CustomEvent('stock-card-click', {
      bubbles: true,
      detail: { stock, prediction },
    }));
  });

  return card;
}

/**
 * Toggle a stock in/out of the watchlist (with localStorage persistence).
 * @param {string} symbol
 * @param {HTMLButtonElement} btn
 */
function _toggleWatchlist(symbol, btn) {
  const willAdd = !isInWatchlist(symbol);
  if (willAdd) {
    addToWatchlist(symbol);
  } else {
    removeFromWatchlist(symbol);
  }
  btn.classList.toggle('stock-card__watchlist-btn--active', willAdd);
  btn.textContent = willAdd ? '★' : '☆';
  btn.setAttribute('aria-label', `${willAdd ? 'Remove' : 'Add'} ${symbol} ${willAdd ? 'from' : 'to'} watchlist`);
}

/**
 * Lazily render a sparkline when the container scrolls into the viewport.
 * Uses IntersectionObserver if available; falls back to immediate render.
 *
 * @param {HTMLElement} container
 * @param {number[]}    history  - Array of close prices
 * @param {boolean}     isUp     - Whether today's change is positive
 */
function _observeSparkline(container, history, isUp) {
  if (!('IntersectionObserver' in window)) {
    // Fallback: render immediately
    renderSparkline(container, history, isUp);
    return;
  }

  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        renderSparkline(entry.target, history, isUp);
        observer.unobserve(entry.target);
      }
    }
  }, { threshold: 0.1 });

  observer.observe(container);
}


