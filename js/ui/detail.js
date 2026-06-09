/**
 * js/ui/detail.js
 * Stock detail overlay / modal component.
 *
 * openStockDetail(symbol, stock, candles, prediction)
 *   - Opens a full-screen overlay with price, OHLCV stats, chart, prediction.
 *   - Accessible: traps focus, responds to Escape key, has ARIA role="dialog".
 *
 * closeStockDetail()
 *   - Removes the overlay from DOM and destroys its Chart.js instance.
 */

import { formatCurrency, formatPercent, formatDollarChange, formatLargeNumber, escapeHtml as _esc } from '../utils/helpers.js';
import { renderDetailChart, renderFullChart, destroyContainerChart } from './charts.js';
import { isInWatchlist, addToWatchlist, removeFromWatchlist } from './watchlist.js';
import { renderNewsPanel } from './news.js';
import { fetchNewsHeadlines } from './news.js';
import { buildShareButtons } from './share.js';
import { aggregateSentiment, classifySentiment } from '../utils/sentiment.js';
import { getPredictionsBySymbol } from '../ml/tracker.js';

const OVERLAY_ID = 'stock-detail-overlay';

/** The element that triggered the modal; focus is returned here on close. */
let _triggerEl = null;

// ─── Public API ───────────────────────────────────────────────

/**
 * Open the stock detail modal.
 *
 * @param {string}  symbol
 * @param {Object}  stock        - StockData object (quote + candles)
 * @param {Array}   candles      - OHLCV candle array (may be empty)
 * @param {Object|null} prediction - Prediction object or null
 * @param {{ mode: 'demo'|'live' }} [appState]  - App state for feature flags
 */
export function openStockDetail(symbol, stock, candles, prediction, appState = { mode: 'demo' }) {
  // Close any existing overlay first
  closeStockDetail();

  _triggerEl = document.activeElement;

  const overlay = _buildOverlay(symbol, stock, candles, prediction, appState);
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';

  // Reveal overlay + render chart on the next tick. setTimeout (not RAF)
  // because RAF is throttled in backgrounded / non-visible tabs and that
  // leaves the canvas at 0x0 forever.
  setTimeout(() => {
    overlay.removeAttribute('hidden');
    const first = overlay.querySelector('button, [tabindex="0"]');
    first?.focus();
    // One more tick so layout/animation has applied before Chart.js measures.
    setTimeout(() => {
      _renderOverlayChart(overlay, symbol, stock, candles, prediction);
      // Safety net: kick Chart.js to remeasure once layout has fully settled.
      setTimeout(() => window.dispatchEvent(new Event('resize')), 120);
    }, 0);
  }, 0);

  // Escape key closes
  overlay._keyHandler = e => {
    if (e.key === 'Escape') closeStockDetail();
    if (e.key === 'Tab')    _trapFocus(e, overlay);
  };
  document.addEventListener('keydown', overlay._keyHandler);

  // (chart rendering happens in _renderOverlayChart, invoked from RAF above)

  // Async: populate news panel after overlay is shown
  const newsContainer = overlay.querySelector('.detail-overlay__news-body');
  if (newsContainer) {
    renderNewsPanel(newsContainer, symbol, appState);
  }

  // Async: hydrate V2-mode price strip from local /api/quote (works for any US ticker).
  const v2PriceEl = overlay.querySelector('.detail-overlay__price--v2');
  if (v2PriceEl) {
    fetch(`/api/quote?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-cache' })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(q2 => {
        const close   = Number(q2.close) || 0;
        const change  = Number(q2.change) || 0;
        const pct     = Number(q2.changePercent) || 0;
        const isUp2   = change >= 0;
        v2PriceEl.querySelector('.detail-overlay__price-value').textContent = formatCurrency(close);
        const chg = v2PriceEl.querySelector('.detail-overlay__price-change');
        chg.textContent = `${formatDollarChange(change)} (${formatPercent(pct / 100)})`;
        chg.classList.add(`detail-overlay__price-change--${isUp2 ? 'up' : 'down'}`);
        const asof = v2PriceEl.querySelector('.detail-overlay__price-asof');
        if (asof && q2.date) asof.textContent = `as of ${q2.date}${q2.source === 'live' ? ' • live' : ''}`;
        v2PriceEl.removeAttribute('hidden');
      })
      .catch(() => { /* leave hidden if no quote available */ });
  }

  // Async: compute and display sentiment badge from recent headlines
  const sentimentEl = overlay.querySelector('.detail-overlay__sentiment');
  if (sentimentEl) {
    fetchNewsHeadlines(symbol, appState).then(headlines => {
      if (!headlines.length) return;
      const result = aggregateSentiment(headlines);
      const label  = classifySentiment(result.average);
      const emoji  = label === 'bullish' ? '😊' : label === 'bearish' ? '😟' : '😐';
      const pct    = Math.round((result.average + 1) * 50); // map [-1,1] → [0,100]
      sentimentEl.querySelector('.sentiment-badge__text').textContent =
        `${emoji} ${label.charAt(0).toUpperCase() + label.slice(1)}`;
      sentimentEl.querySelector('.sentiment-badge__score').textContent =
        `${result.average >= 0 ? '+' : ''}${result.average.toFixed(2)}`;
      const bar = sentimentEl.querySelector('.sentiment-gauge__fill');
      if (bar) {
        bar.style.width = `${pct}%`;
        bar.className = `sentiment-gauge__fill sentiment-gauge__fill--${label}`;
      }
      sentimentEl.removeAttribute('hidden');
    }).catch(() => { /* sentiment is optional — fail silently */ });
  }
}

/**
 * Close the stock detail modal.
 */
export function closeStockDetail() {
  const overlay = document.getElementById(OVERLAY_ID);
  if (!overlay) return;

  // Destroy chart
  const chartContainer = overlay.querySelector('.detail-overlay__chart-inner');
  if (chartContainer) destroyContainerChart(chartContainer);

  // Remove key listener
  if (overlay._keyHandler) {
    document.removeEventListener('keydown', overlay._keyHandler);
  }

  // Animate out
  overlay.classList.add('detail-overlay--closing');
  setTimeout(() => {
    overlay.remove();
    document.body.style.overflow = '';
    _triggerEl?.focus();
    _triggerEl = null;
  }, 280);
}

// ─── DOM builders ─────────────────────────────────────────────

function _buildOverlay(symbol, stock, candles, prediction, appState) {
  const q       = stock.quote || {};
  const isUp    = (q.change || 0) >= 0;
  const predUp  = prediction?.direction === 'UP';

  // V2 mode: no live prices — only pipeline prediction data available
  const isV2 = stock._v2Prediction != null;

  const overlay = document.createElement('div');
  overlay.id        = OVERLAY_ID;
  overlay.className = 'detail-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', `${symbol} stock detail`);
  overlay.hidden    = true;

  // Build prediction details section (for both V2 and live modes)
  const confPct  = Math.round((prediction?.confidence ?? 0) * 100);
  const confTier = (prediction?.confidence ?? 0) >= 0.75 ? 'high' : (prediction?.confidence ?? 0) >= 0.6 ? 'medium' : 'low';
  const predReturnPct = prediction?.predictedReturn != null
    ? `${predUp ? '+' : ''}${(prediction.predictedReturn * 100).toFixed(2)}%`
    : null;

  const predictionBlock = prediction ? `
    <div class="detail-overlay__prediction">
      <div class="detail-overlay__prediction-header">
        <span class="detail-overlay__prediction-title">🔮 AI Prediction</span>
        <span class="detail-overlay__prediction-badge${prediction.isDemo ? '' : ' detail-overlay__prediction-badge--live'}">${prediction.isDemo ? 'Demo' : confPct + '%'}</span>
      </div>
      <div class="detail-overlay__prediction-body">
        <span class="detail-overlay__prediction-direction detail-overlay__prediction-direction--${predUp ? 'up' : 'down'}">
          ${predUp ? '▲ UP' : '▼ DOWN'}
        </span>
        ${isV2 && predReturnPct
          ? `<span class="detail-overlay__prediction-price">${_esc(predReturnPct)}</span>`
          : !isV2
            ? `<span class="detail-overlay__prediction-price">${formatCurrency(prediction.predictedPrice || 0)}</span>
               <span class="detail-overlay__prediction-delta detail-overlay__prediction-delta--${predUp ? 'up' : 'down'}">
                 ${formatDollarChange(predUp ? prediction.delta : -(prediction.delta || 0))}
               </span>`
            : ''
        }
      </div>
      ${isV2 ? `
      <div style="margin-top:var(--space-2);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-1);font-size:var(--font-size-sm);color:var(--color-text-muted);">
          <span>Confidence</span><span>${confPct}%</span>
        </div>
        <div class="conf-gauge">
          <div class="conf-gauge__fill conf-gauge__fill--${confTier}" style="width:${confPct}%"></div>
        </div>
        ${prediction.probability != null ? `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:var(--space-2);font-size:var(--font-size-sm);color:var(--color-text-muted);">
          <span>Probability</span><span>${Math.round((prediction.probability ?? 0.5) * 100)}%</span>
        </div>` : ''}
      </div>` : ''}
    </div>
  ` : '';

  overlay.innerHTML = `
    <div class="detail-overlay__backdrop" aria-hidden="true"></div>
    <div class="detail-overlay__panel">

      <!-- Header -->
      <div class="detail-overlay__header">
        <div class="detail-overlay__header-info">
          <span class="detail-overlay__symbol">${_esc(symbol)}</span>
          <span class="detail-overlay__name">${_esc(stock.name || symbol)}</span>
          ${stock.exchange ? `<span class="detail-overlay__exchange">${_esc(stock.exchange)}</span>` : ''}
        </div>
        <button class="detail-overlay__close" aria-label="Close detail view" id="detail-close-btn">✕</button>
      </div>

      ${isV2 ? `
      <!-- Live price (V2 mode: hydrated async from /api/quote) -->
      <div class="detail-overlay__price detail-overlay__price--v2" data-quote="${_esc(symbol)}" hidden>
        <span class="detail-overlay__price-value">—</span>
        <span class="detail-overlay__price-change">—</span>
        <span class="detail-overlay__price-asof" style="font-size:11px;opacity:0.6;margin-left:8px;"></span>
      </div>
      ` : `
      <!-- Price (live mode only) -->
      <div class="detail-overlay__price">
        <span class="detail-overlay__price-value">${formatCurrency(q.current || 0)}</span>
        <span class="detail-overlay__price-change detail-overlay__price-change--${isUp ? 'up' : 'down'}">
          ${formatDollarChange(q.change || 0)} (${formatPercent(q.changePercent || 0)})
        </span>
      </div>

      <!-- OHLCV Stats (live mode only) -->
      <div class="detail-overlay__stats">
        ${_statItem('Open',       formatCurrency(q.open || 0))}
        ${_statItem('High',       formatCurrency(q.high || 0))}
        ${_statItem('Low',        formatCurrency(q.low  || 0))}
        ${_statItem('Prev Close', formatCurrency(q.previousClose || 0))}
        ${_statItem('Volume',     formatLargeNumber(q.volume || 0))}
        ${_statItem('Market Cap', stock.marketCap ? formatLargeNumber(stock.marketCap) : '—')}
      </div>`}

      <!-- AI Prediction -->
      ${predictionBlock}

      <!-- Chart -->
      <div class="detail-overlay__chart" style="min-height:296px;flex-shrink:0;">
        <div class="detail-overlay__chart-inner" style="height:280px;min-height:240px;position:relative;width:100%;"></div>
      </div>

      <!-- Sentiment Badge (populated asynchronously) -->
      <div class="detail-overlay__sentiment sentiment-badge" hidden aria-live="polite">
        <span class="sentiment-badge__label">📰 News Sentiment:</span>
        <span class="sentiment-badge__text">—</span>
        <span class="sentiment-badge__score"></span>
        <div class="sentiment-gauge" aria-hidden="true">
          <div class="sentiment-gauge__fill"></div>
        </div>
      </div>

      <!-- Actions -->
      <div class="detail-overlay__actions">
        <button class="btn btn--secondary detail-overlay__watchlist-btn" data-symbol="${_esc(symbol)}" id="detail-watchlist-btn">
          ${isInWatchlist(symbol) ? '★ Remove from Watchlist' : '☆ Add to Watchlist'}
        </button>
      </div>

      <!-- News -->
      <div class="detail-overlay__news">
        <h3 class="detail-overlay__section-title">📰 Recent News &amp; Sentiment</h3>
        <div class="detail-overlay__news-body">
          <!-- populated async by renderNewsPanel -->
        </div>
      </div>

    </div>
  `;

  // Close on backdrop click
  overlay.querySelector('.detail-overlay__backdrop')?.addEventListener('click', closeStockDetail);
  overlay.querySelector('#detail-close-btn')?.addEventListener('click', closeStockDetail);

  // Watchlist toggle
  overlay.querySelector('#detail-watchlist-btn')?.addEventListener('click', e => {
    e.stopPropagation();
    _toggleWatchlistBtn(symbol, overlay.querySelector('#detail-watchlist-btn'));
  });

  // Share buttons (append to actions row)
  if (prediction) {
    const actionsEl = overlay.querySelector('.detail-overlay__actions');
    if (actionsEl) {
      actionsEl.appendChild(buildShareButtons(symbol, prediction));
    }
  }

  return overlay;
}

function _statItem(label, value) {
  return `
    <div class="detail-overlay__stat">
      <span class="detail-overlay__stat-label">${label}</span>
      <span class="detail-overlay__stat-value">${value}</span>
    </div>
  `;
}

/**
 * Render the chart into the overlay. Called AFTER the overlay is visible so
 * Chart.js can measure a non-zero parent. Tries (a) caller-supplied candles,
 * (b) stock.quote.history sparkline, then (c) on-demand /api/bars fetch.
 */
function _renderOverlayChart(overlay, symbol, stock, candles, prediction) {
  const chartContainer = overlay.querySelector('.detail-overlay__chart-inner');
  if (!chartContainer) return;

  const trackedPreds = getPredictionsBySymbol(symbol);
  const pastPredictions = trackedPreds
    .filter(p => p.predictedPrice != null)
    .map(p => ({
      date: p.predictionDate || new Date(p.generatedAt).toISOString().slice(0, 10),
      predictedPrice: p.predictedPrice,
    }));

  const renderLocalFetch = () => {
    chartContainer.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;color:var(--color-text-muted);font-size:13px;">
        <span style="font-size:13px;opacity:0.7;">Loading local price history…</span>
      </div>`;
    fetch(`/api/bars?symbol=${encodeURIComponent(symbol)}&limit=252`, { cache: 'no-cache' })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(payload => {
        const c = payload?.candles || [];
        if (c.length === 0) throw new Error('no candles');
        chartContainer.innerHTML = '';
        renderFullChart(chartContainer, c, prediction, pastPredictions);
      })
      .catch(() => {
        chartContainer.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;color:var(--color-text-muted);font-size:13px;text-align:center;padding:16px;">
            <span style="font-size:2rem;">📊</span>
            <span>No local bars on disk for <strong>${symbol}</strong>.</span>
            <span style="font-size:11px;opacity:0.6;">Run the nightly fetch (or wait for it) to populate <code>data/historical/</code>.</span>
          </div>`;
      });
  };

  if (candles && candles.length > 0) {
    renderFullChart(chartContainer, candles, prediction, pastPredictions);
  } else if (stock.quote?.history && stock.quote.history.length > 0) {
    const history = stock.quote.history.map((close, i) => ({ date: String(i), close }));
    renderDetailChart(chartContainer, history, prediction, pastPredictions);
  } else {
    renderLocalFetch();
  }
}

function _toggleWatchlistBtn(symbol, btn) {
  if (isInWatchlist(symbol)) {
    removeFromWatchlist(symbol);
    btn.textContent = '☆ Add to Watchlist';
  } else {
    addToWatchlist(symbol);
    btn.textContent = '★ Remove from Watchlist';
  }
}

// ─── Focus trap ───────────────────────────────────────────────

function _trapFocus(e, modal) {
  const focusable = Array.from(
    modal.querySelectorAll('a[href], button:not([disabled]), input, [tabindex="0"]')
  ).filter(el => !el.closest('[hidden]'));
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last  = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
