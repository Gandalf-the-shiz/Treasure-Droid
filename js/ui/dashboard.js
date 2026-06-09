/**
 * js/ui/dashboard.js
 * Main dashboard rendering and layout controller.
 *
 * Responsibilities:
 *  - Load stock data (demo or live)
 *  - Render the market overview strip
 *  - Render stock cards grid with staggered animation
 *  - Coordinate with charts.js and prediction.js
 *  - Wire card clicks to the stock detail overlay
 *
 * Phase 1: Renders demo data from data/sample.json.
 * Phase 2: Pulls live data via api/manager.js.
 * Phase 3: Stagger animation, detail view wiring.
 * Phase 4+: Adds prediction overlays on each card.
 */

import {
  loadDemoData,
  getQuote,
  getCandles,
  loadTickerRegistry,
  startQuoteRotation,
  hasAnyQuoteProviderConfigured,
  getProviderHealthStatus,
} from '../api/manager.js';
import { getItem } from '../storage/cache.js';
import { escapeHtml as _escapeHtml } from '../utils/helpers.js';
import { runPrediction, demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';
import { openStockDetail } from './detail.js';
import { storePrediction } from '../ml/tracker.js';
import { resolveAll, getPredictions } from '../ml/tracker.js';
import { autoRetrain } from '../ml/retraining.js';
import { aggregateSentiment } from '../utils/sentiment.js';

const DEFAULT_WATCHLIST = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA'];

/** Number of top bullish + top bearish cards to show from V2 predictions */
const V2_TOP_N = 20;
let _quoteRotation = null;
let _healthTimer = null;
let _dashboardNavHooked = false;

/**
 * Initialize the dashboard with the given app state.
 * @param {{ mode: 'demo'|'live', tfReady: boolean, chartReady: boolean, v2Predictions: object|null }} appState
 */
export async function initDashboard(appState) {
  console.log('[Dashboard] Initializing…');

  const stockGrid = document.getElementById('stock-grid');
  if (!stockGrid) return;

  _stopDashboardQuoteRotation();

  // Show loading skeletons
  showLoadingSkeletons(stockGrid);

  let stocks = [];

  if (appState.v2Predictions && appState.v2Predictions.items.length > 0) {
    // V2 pipeline predictions are the primary data source — always use them when available.
    let tickerMap = new Map();
    try { tickerMap = await loadTickerRegistry(); } catch (err) { console.warn('[Dashboard] Failed to load ticker registry:', err); }
    stocks = _buildStocksFromV2Predictions(appState.v2Predictions, tickerMap);
    appState._tickerMap = tickerMap;
    // Enrich V2 stocks with live prices when any API key is available
    await _enrichV2StocksWithQuotes(stocks, appState.v2Predictions.items);
  } else if (appState.mode === 'live') {
    stocks = await loadLiveStocks(appState, stockGrid);
  } else {
    // True demo fallback: sample.json
    const demoData = await loadDemoData();
    stocks = demoData.stocks || [];
  }

  // Clear skeletons
  stockGrid.innerHTML = '';

  if (stocks.length === 0) {
    renderEmptyState(stockGrid);
    return;
  }

  renderMarketOverview(stocks);

  if (appState.v2Predictions) {
    _renderPredDateBar(appState.v2Predictions);
  }

  // Build a price map for resolving any pending predictions from earlier runs
  const priceMap = {};
  for (const stock of stocks) {
    if (stock.symbol && stock.quote?.current) {
      priceMap[stock.symbol] = stock.quote.current;
    }
  }
  try { resolveAll(priceMap); } catch (e) { console.warn('[Dashboard] resolveAll failed:', e); }

  // Collect candles for auto-retraining
  const allCandles = [];
  for (const stock of stocks) {
    if (Array.isArray(stock.candles) && stock.candles.length > 0) {
      allCandles.push(...stock.candles);
    }
  }

  // Render each stock card with staggered animation
  for (let i = 0; i < stocks.length; i++) {
    const stock = stocks[i];
    let prediction;

    // Use the pre-attached V2 prediction if available (avoids redundant ML inference)
    if (stock._v2Prediction) {
      prediction = stock._v2Prediction;
    } else if (appState.tfReady && stock.candles && stock.candles.length >= 30) {
      try {
        prediction = await runPrediction(stock.symbol, stock.candles);
      } catch (err) {
        console.warn(`[Dashboard] ML prediction failed for ${stock.symbol}, using demo:`, err.message);
        prediction = demoPrediction(stock.symbol, stock.quote.current);
      }
    } else {
      prediction = demoPrediction(stock.symbol, stock.quote.current);
    }

    // Track the prediction (graceful — never break the render loop)
    try { storePrediction(prediction); } catch (e) { console.warn('[Dashboard] storePrediction failed:', e); }

    const card = renderStockCard(stock, prediction, appState.chartReady);
    card.style.animationDelay = `${i * 50}ms`;
    card.classList.add('stock-card--animate-in');
    stockGrid.appendChild(card);
  }

  if (appState.v2Predictions && hasAnyQuoteProviderConfigured()) {
    _startDashboardQuoteRotation(stocks, stockGrid);
  }
  _renderProviderHealthBadge();
  _bindDashboardNavigationLifecycle();

  // Trigger background retraining if needed (after rendering, non-blocking)
  if (appState.tfReady && allCandles.length >= 40) {
    try { autoRetrain(allCandles); } catch (e) { console.warn('[Dashboard] autoRetrain failed:', e); }
  }

  // Wire card clicks to detail overlay
  stockGrid.addEventListener('stock-card-click', e => {
    const { stock, prediction } = e.detail;
    const candles = stock.candles || [];
    openStockDetail(stock.symbol, stock, candles, prediction, appState);
  });

  // Render supplemental panels below the grid
  _renderDashboardPanels(stocks, appState);

  // Market Mood indicator in header
  _renderMarketMood(stocks, appState);

  console.log(`[Dashboard] Rendered ${stocks.length} stock cards.`);
}

function _startDashboardQuoteRotation(stocks, stockGrid) {
  const symbols = stocks.map(s => s.symbol).filter(Boolean);
  if (!symbols.length) return;
  _quoteRotation = startQuoteRotation(symbols, (symbol, quote) => {
    const stock = stocks.find(s => s.symbol === symbol);
    if (!stock || !quote?.current) return;
    stock.quote.current = quote.current;
    stock.quote.change = quote.change ?? 0;
    stock.quote.changePercent = quote.changePercent ?? 0;
    stock.quote.previousClose = quote.previousClose ?? stock.quote.previousClose ?? 0;
    stock.quote.open = quote.open ?? stock.quote.open ?? 0;
    stock.quote.high = quote.high ?? stock.quote.high ?? 0;
    stock.quote.low = quote.low ?? stock.quote.low ?? 0;
    stock.quote.volume = quote.volume ?? stock.quote.volume ?? 0;

    const card = stockGrid.querySelector(`.stock-card[data-symbol="${symbol}"]`);
    if (!card) return;
    const priceEl = card.querySelector('.stock-card__price');
    if (priceEl) priceEl.textContent = `$${Number(quote.current).toFixed(2)}`;
    const changeEl = card.querySelector('.stock-card__change');
    if (changeEl) {
      const delta = quote.change ?? 0;
      const pct = quote.changePercent ?? 0;
      changeEl.textContent = `${delta >= 0 ? '+' : ''}$${Math.abs(delta).toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)`;
      changeEl.classList.toggle('stock-card__change--up', delta >= 0);
      changeEl.classList.toggle('stock-card__change--down', delta < 0);
    }
  });
}

function _stopDashboardQuoteRotation() {
  if (_quoteRotation) {
    _quoteRotation.stop();
    _quoteRotation = null;
  }
  if (_healthTimer) {
    clearInterval(_healthTimer);
    _healthTimer = null;
  }
}

function _bindDashboardNavigationLifecycle() {
  if (_dashboardNavHooked) return;
  _dashboardNavHooked = true;
  document.addEventListener('navigated', e => {
    const view = e.detail?.view;
    if (view && view !== 'dashboard') {
      _stopDashboardQuoteRotation();
    }
  });
}

function _renderProviderHealthBadge() {
  const dashView = document.getElementById('view-dashboard');
  if (!dashView) return;

  const debugEnabled = (() => {
    try { return localStorage.getItem('nostradamus_debug') === '1'; } catch { return false; }
  })();

  dashView.querySelectorAll('.provider-health-badge').forEach(el => el.remove());
  if (!debugEnabled) return;

  const badge = document.createElement('div');
  badge.className = 'provider-health-badge';
  dashView.prepend(badge);

  const render = () => {
    const h = getProviderHealthStatus();
    badge.textContent = `API health • Finnhub: ${h.finnhub} • TwelveData: ${h.twelvedata} • Polygon: ${h.polygon}`;
  };
  render();
  _healthTimer = setInterval(render, 1000);
}

/**
 * Build a minimal stocks array from V2 pipeline predictions.
 * Selects the top N bullish + top N bearish tickers by confidence
 * to display on the dashboard.
 *
 * @param {{ date: string, generatedAt: string, items: Array }} v2Preds
 * @param {Map<string, { name: string, sector: string, exchange: string }>} tickerMap
 * @returns {Array}
 */
function _buildStocksFromV2Predictions(v2Preds, tickerMap = new Map()) {
  const items = v2Preds.items;

  const bullish = items
    .filter(p => p.direction === 'UP')
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, V2_TOP_N);

  const bearish = items
    .filter(p => p.direction === 'DOWN')
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, V2_TOP_N);

  const selected = [...bullish, ...bearish];

  return selected.map(pred => {
    const info = tickerMap.get(pred.symbol) || {};
    return {
      symbol:    pred.symbol,
      name:      info.name || pred.symbol,
      exchange:  info.exchange || null,
      industry:  info.sector  || null,
      marketCap: null,
      quote: {
        current:       pred.currentPrice || 0,
        open:          0,
        high:          0,
        low:           0,
        previousClose: 0,
        change:        pred.delta || 0,
        changePercent: 0,
        volume:  0,
        history: [],
      },
      candles: [],
      // Attach the pre-computed V2 prediction so the render loop can use it directly
      _v2Prediction: pred,
    };
  });
}

/**
 * Enrich a stocks array (built from V2 predictions) with live quote data.
 * Fetches quotes for all symbols in parallel via the API manager fallback chain.
 * Silently skips symbols for which no quote is available.
 *
 * @param {Array} stocks   - Stock objects produced by _buildStocksFromV2Predictions
 * @param {Array} v2Items  - Original V2 prediction items (for predictedReturn access)
 * @returns {Promise<void>}
 */
async function _enrichV2StocksWithQuotes(stocks, v2Items) {
  const v2Map = new Map(v2Items.map(item => [item.symbol, item]));

  await Promise.allSettled(stocks.map(async stock => {
    try {
      const quote = await getQuote(stock.symbol);
      if (!quote || !quote.current) return;

      const currentPrice = quote.current;

      // Update the stock's quote object with live data
      stock.quote.current       = currentPrice;
      stock.quote.open          = quote.open          || 0;
      stock.quote.high          = quote.high          || 0;
      stock.quote.low           = quote.low           || 0;
      stock.quote.previousClose = quote.previousClose || 0;
      stock.quote.change        = quote.change        || 0;
      stock.quote.changePercent = quote.changePercent || 0;
      stock.quote.volume        = quote.volume        || 0;

      // Enrich the attached V2 prediction with computed price fields
      const v2Pred = v2Map.get(stock.symbol);
      if (v2Pred && stock._v2Prediction) {
        const predictedReturn = v2Pred.predictedReturn
          ?? (v2Pred.direction === 'UP' ? 0.01 : -0.01);
        const predictedPrice = parseFloat((currentPrice * (1 + predictedReturn)).toFixed(2));
        const delta          = parseFloat((predictedPrice - currentPrice).toFixed(2));

        stock._v2Prediction.currentPrice   = currentPrice;
        stock._v2Prediction.predictedPrice = predictedPrice;
        stock._v2Prediction.delta          = delta;
      }
    } catch (err) {
      console.warn(`[Dashboard] Could not enrich V2 stock ${stock.symbol} with live price:`, err.message);
    }
  }));
}

/**
 * Load live stock data for the watchlist, with per-symbol error handling.
 * Falls back to demo data on total failure.
 * @param {{ mode: string, chartReady: boolean }} appState
 * @param {HTMLElement} stockGrid
 * @returns {Promise<Array>}
 */
async function loadLiveStocks(appState, stockGrid) {
  const savedWatchlist = getItem('watchlist');
  const watchlist = Array.isArray(savedWatchlist) && savedWatchlist.length > 0
    ? savedWatchlist
    : DEFAULT_WATCHLIST;

  const stocks = [];

  await Promise.allSettled(
    watchlist.map(async symbol => {
      try {
        const [quote, candles] = await Promise.all([
          getQuote(symbol),
          getCandles(symbol),
        ]);

        if (!quote) {
          console.warn(`[Dashboard] No quote data for ${symbol}, skipping.`);
          return;
        }

        stocks.push({
          symbol,
          name:      quote.symbol || symbol,
          exchange:  quote.exchange || null,
          industry:  null,
          marketCap: null,
          quote: {
            current:       quote.current       || 0,
            open:          quote.open          || 0,
            high:          quote.high          || 0,
            low:           quote.low           || 0,
            previousClose: quote.previousClose || 0,
            change:        quote.change        || 0,
            changePercent: quote.changePercent || 0,
            volume:        quote.volume        || 0,
            history:       Array.isArray(candles) ? candles.map(c => c.close) : [],
          },
          candles: candles || [],
        });
      } catch (err) {
        console.error(`[Dashboard] Failed to load ${symbol}:`, err.message);
        renderErrorCard(stockGrid, symbol, err.message);
      }
    })
  );

  // If live loading produced nothing, fall back to demo
  if (stocks.length === 0) {
    console.warn('[Dashboard] All live loads failed. Falling back to demo data.');
    const demoData = await loadDemoData();
    return demoData.stocks || [];
  }

  return stocks;
}

/**
 * Show loading skeleton cards while data is being fetched.
 * @param {HTMLElement} container
 */
function showLoadingSkeletons(container) {
  container.innerHTML = '';
  for (let i = 0; i < 5; i++) {
    const skeleton = document.createElement('div');
    skeleton.className = 'stock-card stock-card--skeleton';
    skeleton.setAttribute('aria-hidden', 'true');
    skeleton.innerHTML = `
      <div class="skeleton-line skeleton-line--short"></div>
      <div class="skeleton-line skeleton-line--long"></div>
      <div class="skeleton-line skeleton-line--medium"></div>
    `;
    container.appendChild(skeleton);
  }
}

/**
 * Render an error card for a symbol that failed to load.
 * @param {HTMLElement} container
 * @param {string} symbol
 * @param {string} message
 */
function renderErrorCard(container, symbol, message) {
  const card = document.createElement('div');
  card.className = 'stock-card stock-card--error';
  card.innerHTML = `
    <div class="stock-card__header">
      <span class="stock-card__symbol">${_escapeHtml(symbol)}</span>
    </div>
    <p class="stock-card__error-text">Failed to load data.</p>
    <p class="stock-card__error-detail" style="font-size:0.75rem;color:var(--color-text-muted)">${_escapeHtml(message || '')}</p>
  `;
  container.appendChild(card);
}


/**
 * Render the horizontal market overview strip (index values, etc.).
 * @param {Array} stocks
 */
function renderMarketOverview(stocks) {
  const container = document.getElementById('market-overview');
  if (!container) return;

  container.innerHTML = '';

  // Detect V2 mode: stocks built from pipeline predictions have _v2Prediction set
  const isV2 = stocks.length > 0 && stocks.some(s => s._v2Prediction != null);

  let items;
  if (isV2) {
    // In V2 mode use prediction direction instead of quote.change
    const bullish = stocks.filter(s => s._v2Prediction?.direction === 'UP').length;
    const bearish  = stocks.length - bullish;
    const avgConf  = stocks.reduce((sum, s) => sum + (s._v2Prediction?.confidence ?? 0), 0) / stocks.length;
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    items = [
      { label: 'Bullish',     value: String(bullish), positive: true  },
      { label: 'Bearish',     value: String(bearish),  positive: false },
      { label: 'Avg Confidence', value: `${(avgConf * 100).toFixed(1)}%`, positive: avgConf >= 0.6 },
      { label: 'Tracked',    value: String(stocks.length), positive: null },
      { label: 'Updated',    value: timeStr, positive: null },
    ];
  } else {
    // Calculate simple market stats from the live stocks
    const gainers = stocks.filter(s => s.quote.change >= 0).length;
    const losers  = stocks.length - gainers;
    const avgChange = stocks.reduce((sum, s) => sum + s.quote.changePercent, 0) / stocks.length;
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    items = [
      { label: 'Gainers',    value: String(gainers), positive: true },
      { label: 'Losers',     value: String(losers),  positive: false },
      { label: 'Avg Change', value: `${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%`, positive: avgChange >= 0 },
      { label: 'Tracked',    value: String(stocks.length), positive: null },
      { label: 'Updated',    value: timeStr, positive: null },
    ];
  }

  items.forEach(item => {
    const el = document.createElement('div');
    el.className = 'market-overview__item';
    el.innerHTML = `
      <span class="market-overview__item-label">${item.label}</span>
      <span class="market-overview__item-value" style="color: ${
        item.positive === null
          ? 'var(--color-text)'
          : item.positive
            ? 'var(--color-up)'
            : 'var(--color-down)'
      }">${item.value}</span>
    `;
    container.appendChild(el);
  });
}

/**
 * Render an empty state when no stocks are available.
 * @param {HTMLElement} container
 */
function renderEmptyState(container) {
  container.innerHTML = `
    <div class="empty-state" style="grid-column: 1/-1;">
      <span class="empty-state__icon">📭</span>
      <h2 class="empty-state__title">No stocks to display</h2>
      <p class="empty-state__text">Search for a stock to add it to your watchlist, or configure an API key to load live data.</p>
    </div>
  `;
}

// ─── Supplemental dashboard panels ──────────────────────────

/**
 * Render Top Predictions, Sector Rotation, and Momentum Scanner panels.
 * @param {Array} stocks
 * @param {{ mode: string, v2Predictions: object|null, _tickerMap?: Map }} appState
 */
function _renderDashboardPanels(stocks, appState) {
  const dashView = document.getElementById('view-dashboard');
  if (!dashView) return;

  // Remove stale panels from a previous render
  dashView.querySelectorAll('.dashboard-panels').forEach(el => el.remove());

  // Prefer V2 pipeline predictions (thousands of tickers) over tracker data (few symbols)
  let predsArr;
  if (appState.v2Predictions && appState.v2Predictions.items.length > 0) {
    predsArr = appState.v2Predictions.items;
  } else {
    const allPreds = getPredictions();
    const latestMap = new Map();
    for (const p of allPreds) {
      const ex = latestMap.get(p.symbol);
      if (!ex || p.generatedAt > ex.generatedAt) latestMap.set(p.symbol, p);
    }
    if (latestMap.size === 0) return;
    predsArr = Array.from(latestMap.values());
  }

  if (!predsArr || predsArr.length === 0) return;

  const tickerMap = appState._tickerMap || new Map();
  const panels = document.createElement('div');
  panels.className = 'dashboard-panels';

  // Top Predictions
  panels.appendChild(_buildTopPredictionsPanel(predsArr));

  // Sector Rotation
  panels.appendChild(_buildSectorRotationPanel(predsArr, tickerMap));

  // Momentum Scanner (confidence > 80%)
  panels.appendChild(_buildMomentumPanel(predsArr));

  dashView.appendChild(panels);
}

/**
 * Build "Top Predictions" panel: top 10 bullish + top 10 bearish.
 */
function _buildTopPredictionsPanel(preds) {
  const section = document.createElement('div');
  section.className = 'dash-panel';

  const title = document.createElement('h2');
  title.className = 'dash-panel__title';
  title.textContent = '🏆 Top Predictions';
  section.appendChild(title);

  const grid = document.createElement('div');
  grid.className = 'top-preds-grid';

  const bullish = preds
    .filter(p => p.direction === 'UP')
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 10);

  const bearish = preds
    .filter(p => p.direction === 'DOWN')
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 10);

  grid.appendChild(_buildTopList('🐂 Top Bullish', bullish, 'up'));
  grid.appendChild(_buildTopList('🐻 Top Bearish', bearish, 'down'));

  section.appendChild(grid);
  return section;
}

function _buildTopList(heading, items, dir) {
  const col = document.createElement('div');
  col.className = 'top-preds-col';

  const h = document.createElement('h3');
  h.className = 'top-preds-col__title';
  h.textContent = heading;
  col.appendChild(h);

  if (items.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'top-preds-empty';
    empty.textContent = 'No predictions yet.';
    col.appendChild(empty);
    return col;
  }

  const list = document.createElement('ul');
  list.className = 'top-preds-list';

  items.forEach(p => {
    const li = document.createElement('li');
    li.className = 'top-preds-item';
    li.innerHTML = `
      <span class="top-preds-item__symbol">${_escapeHtml(p.symbol)}</span>
      <span class="top-preds-item__badge top-preds-item__badge--${dir}">${dir === 'up' ? '▲' : '▼'} ${dir.toUpperCase()}</span>
      <span class="top-preds-item__conf">${Math.round((p.confidence ?? 0) * 100)}%</span>
    `;
    list.appendChild(li);
  });

  col.appendChild(list);
  return col;
}

/**
 * Build "Sector Rotation" mini-panel.
 * @param {Array} preds
 * @param {Map<string, { name: string, sector: string, exchange: string }>} tickerMap
 */
function _buildSectorRotationPanel(preds, tickerMap = new Map()) {
  const section = document.createElement('div');
  section.className = 'dash-panel';

  const title = document.createElement('h2');
  title.className = 'dash-panel__title';
  title.textContent = '🔄 Sector Rotation';
  section.appendChild(title);

  // Aggregate avg probability per sector
  const sectorMap = new Map();
  for (const p of preds) {
    const sector = tickerMap.get(p.symbol)?.sector ?? 'Other';
    if (!sectorMap.has(sector)) sectorMap.set(sector, { sum: 0, count: 0 });
    const s = sectorMap.get(sector);
    s.sum   += p.probability ?? 0.5;
    s.count += 1;
  }

  const sectors = Array.from(sectorMap.entries())
    .map(([name, { sum, count }]) => ({ name, avg: sum / count }))
    .sort((a, b) => b.avg - a.avg);

  if (sectors.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'top-preds-empty';
    empty.textContent = 'No sector data yet.';
    section.appendChild(empty);
    return section;
  }

  const list = document.createElement('ul');
  list.className = 'sector-rotation-list';

  sectors.forEach(({ name, avg }) => {
    const sentiment = avg > 0.55 ? 'bullish' : avg < 0.45 ? 'bearish' : 'neutral';
    const pct = Math.round(avg * 100);

    const li = document.createElement('li');
    li.className = `sector-rotation-item sector-rotation-item--${sentiment}`;
    li.innerHTML = `
      <span class="sector-rotation-item__name">${_escapeHtml(name)}</span>
      <div class="sector-rotation-item__bar-wrap">
        <div class="sector-rotation-item__bar" style="width:${pct}%"></div>
      </div>
      <span class="sector-rotation-item__pct">${pct}%</span>
    `;
    list.appendChild(li);
  });

  section.appendChild(list);
  return section;
}

/**
 * Build "Momentum Scanner" panel — stocks with confidence > 80%.
 */
function _buildMomentumPanel(preds) {
  const section = document.createElement('div');
  section.className = 'dash-panel';

  const title = document.createElement('h2');
  title.className = 'dash-panel__title';
  title.textContent = '⚡ Momentum Scanner';
  section.appendChild(title);

  const subtitle = document.createElement('p');
  subtitle.className = 'dash-panel__subtitle';
  subtitle.textContent = 'Stocks with model confidence > 80%';
  section.appendChild(subtitle);

  const highConf = preds
    .filter(p => (p.confidence ?? 0) >= 0.80)
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));

  if (highConf.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'top-preds-empty';
    empty.textContent = 'No high-confidence signals at the moment.';
    section.appendChild(empty);
    return section;
  }

  const list = document.createElement('ul');
  list.className = 'momentum-list';

  highConf.slice(0, 12).forEach(p => {
    const dir = p.direction === 'UP' ? 'up' : 'down';
    const li  = document.createElement('li');
    li.className = `momentum-item momentum-item--${dir}`;
    li.innerHTML = `
      <span class="momentum-item__symbol">${_escapeHtml(p.symbol)}</span>
      <span class="momentum-item__dir">${p.direction === 'UP' ? '▲' : '▼'}</span>
      <span class="momentum-item__conf">${Math.round((p.confidence ?? 0) * 100)}%</span>
    `;
    list.appendChild(li);
  });

  section.appendChild(list);
  return section;
}

/**
 * Render Market Mood indicator in the dashboard header area.
 * @param {Array} stocks
 * @param {{ v2Predictions: object|null }} appState
 */
function _renderMarketMood(stocks, appState) {
  const moodEl = document.getElementById('market-mood');
  if (!moodEl) return;

  // Prefer V2 predictions for a more representative mood calculation
  let source = [];
  if (appState && appState.v2Predictions && appState.v2Predictions.items.length > 0) {
    source = appState.v2Predictions.items;
  } else {
    source = getPredictions();
  }

  if (source.length === 0 && stocks.length === 0) {
    moodEl.hidden = true;
    return;
  }

  let avgProb = 0.5;

  if (source.length > 0) {
    avgProb = source.reduce((s, p) => s + (p.probability ?? 0.5), 0) / source.length;
  } else if (stocks.length > 0) {
    // fallback: use avg price change
    const avgChange = stocks.reduce((s, st) => s + (st.quote?.changePercent ?? 0), 0) / stocks.length;
    avgProb = 0.5 + Math.tanh(avgChange / 5) * 0.3;
  }

  const sentiment = avgProb > 0.55 ? 'bullish' : avgProb < 0.45 ? 'bearish' : 'neutral';
  const emoji     = { bullish: '😊', neutral: '😐', bearish: '😟' }[sentiment];
  const label     = { bullish: 'Bullish', neutral: 'Neutral', bearish: 'Bearish' }[sentiment];
  const score     = Math.round(avgProb * 100);

  moodEl.hidden    = false;
  moodEl.className = `market-mood market-mood--${sentiment}`;
  moodEl.innerHTML = `
    <span class="market-mood__emoji">${emoji}</span>
    <span class="market-mood__label">${label}</span>
    <span class="market-mood__score">${score}%</span>
  `;
  moodEl.setAttribute('title', `Market Mood: ${label} (${score}% avg bullish probability)`);
}


/**
 * Render a date info bar above the stock grid showing prediction metadata.
 * @param {{ date: string, generatedAt?: string, items: Array }} v2Preds
 */
function _renderPredDateBar(v2Preds) {
  const dashView = document.getElementById('view-dashboard');
  if (!dashView) return;

  // Remove any existing bar
  dashView.querySelectorAll('.pred-date-bar').forEach(el => el.remove());

  const bar = document.createElement('div');
  bar.className = 'pred-date-bar';

  const dot = document.createElement('span');
  dot.className = 'pred-date-bar__dot';
  dot.setAttribute('aria-hidden', 'true');

  const text = document.createElement('span');
  let genDate = v2Preds.date;
  if (v2Preds.generatedAt) {
    const d = new Date(v2Preds.generatedAt);
    if (!isNaN(d.getTime())) {
      genDate = d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
    }
  }
  text.textContent = `🔮 AI Predictions · ${v2Preds.items.length.toLocaleString()} stocks · Generated ${genDate}`;

  bar.appendChild(dot);
  bar.appendChild(text);

  // Insert before the stock grid
  const grid = document.getElementById('stock-grid');
  if (grid) {
    dashView.insertBefore(bar, grid);
  } else {
    dashView.prepend(bar);
  }
}
