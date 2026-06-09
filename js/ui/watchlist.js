/**
 * js/ui/watchlist.js
 * Watchlist management — localStorage persistence + view rendering.
 *
 * localStorage key: `nostradamus_watchlist` (raw array, no cache TTL wrapper).
 *
 * Exports:
 *   getWatchlist()          → string[]
 *   isInWatchlist(symbol)   → boolean
 *   addToWatchlist(symbol)
 *   removeFromWatchlist(symbol)
 *   initWatchlist(appState)
 */

import { getQuote, getCandles, loadDemoData, loadTickerRegistry, hasAnyQuoteProviderConfigured } from '../api/manager.js';
import { demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';
import { showToast } from '../utils/helpers.js';

const WL_KEY = 'nostradamus_watchlist';   // raw localStorage key
const CUSTOM_EVENT = 'watchlist-changed';

// ─── Persistence helpers ──────────────────────────────────────

/**
 * Return the current watchlist array from localStorage.
 * @returns {string[]}
 */
export function getWatchlist() {
  try {
    const raw = localStorage.getItem(WL_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Check if a symbol is in the watchlist.
 * @param {string} symbol
 * @returns {boolean}
 */
export function isInWatchlist(symbol) {
  return getWatchlist().includes(symbol.toUpperCase());
}

/**
 * Add a symbol to the watchlist.
 * Dispatches 'watchlist-changed' custom event on document.
 * @param {string} symbol
 */
export function addToWatchlist(symbol) {
  const sym = symbol.toUpperCase();
  const list = getWatchlist();
  if (!list.includes(sym)) {
    list.push(sym);
    _save(list);
    _dispatch(sym, 'added');
  }
}

/**
 * Remove a symbol from the watchlist.
 * Dispatches 'watchlist-changed' custom event on document.
 * @param {string} symbol
 */
export function removeFromWatchlist(symbol) {
  const sym = symbol.toUpperCase();
  const list = getWatchlist().filter(s => s !== sym);
  _save(list);
  _dispatch(sym, 'removed');
}

// ─── View rendering ───────────────────────────────────────────

/**
 * Initialise / refresh the Watchlist view section.
 * Called from app.js whenever the user navigates to the Watchlist tab.
 * @param {{ mode: 'demo'|'live', chartReady: boolean }} appState
 */
export async function initWatchlist(appState) {
  const container = document.getElementById('watchlist-grid');
  if (!container) return;

  const list = getWatchlist();

  if (list.length === 0) {
    _renderEmpty(container);
    return;
  }

  _showSkeletons(container, list.length);

  let stocks = [];

  if (appState.v2Predictions && appState.v2Predictions.items.length > 0) {
    // V2 pipeline predictions are available — use them for watchlisted symbols.
    const listSet = new Set(list.map(s => s.toUpperCase()));
    const predMap = new Map(
      appState.v2Predictions.items
        .filter(p => listSet.has(p.symbol))
        .map(p => [p.symbol, p])
    );

    let tickerMap = new Map();
    try { tickerMap = await loadTickerRegistry(); } catch (err) {
      console.warn('[Watchlist] Could not load ticker registry:', err.message);
    }

    // Build a stock stub for every watchlisted symbol
    for (const symbol of list) {
      const sym  = symbol.toUpperCase();
      const pred = predMap.get(sym) ?? null;
      const info = tickerMap.get(sym) ?? {};
      stocks.push({
        symbol:    sym,
        name:      info.name || sym,
        exchange:  info.exchange || null,
        industry:  info.sector  || null,
        marketCap: null,
        quote: {
          current:       pred?.currentPrice || 0,
          open:          0,
          high:          0,
          low:           0,
          previousClose: 0,
          change:        pred?.delta || 0,
          changePercent: 0,
          volume:        0,
          history:       [],
        },
        candles: [],
        _v2Prediction: pred,
      });
    }

    // Enrich with live quotes when any API key is configured
    if (hasAnyQuoteProviderConfigured()) {
      await _enrichWatchlistWithQuotes(stocks, appState.v2Predictions.items);
    }
  } else if (appState.mode === 'live') {
    await Promise.allSettled(
      list.map(async symbol => {
        try {
          const [quote, candles] = await Promise.all([
            getQuote(symbol),
            getCandles(symbol),
          ]);
          if (!quote) return;
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
          console.warn(`[Watchlist] Failed to load ${symbol}:`, err.message);
        }
      })
    );

    if (stocks.length === 0) {
      _renderEmpty(container, 'Could not load watchlist data. Check your API keys.');
      return;
    }
  } else {
    // Demo fallback
    try {
      const demoData = await loadDemoData();
      const demoStocks = demoData.stocks || [];
      stocks = demoStocks.filter(s => list.includes(s.symbol));
      for (const sym of list) {
        if (!stocks.find(s => s.symbol === sym)) {
          stocks.push(_fakeDemoStock(sym));
        }
      }
    } catch {
      stocks = list.map(_fakeDemoStock);
    }
  }

  container.innerHTML = '';

  stocks.forEach((stock, i) => {
    // Use the attached V2 prediction when available; fall back to demo prediction.
    const prediction = stock._v2Prediction
      ? stock._v2Prediction
      : demoPrediction(stock.symbol, stock.quote.current);

    const card = renderStockCard(stock, prediction, appState.chartReady);
    card.style.animationDelay = `${i * 50}ms`;
    card.classList.add('stock-card--animate-in');
    container.appendChild(card);
  });

  _appendClearButton(container);
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * Enrich watchlist stock stubs (built from V2 predictions) with live quote data.
 * Mirrors the same logic used by dashboard._enrichV2StocksWithQuotes.
 * @param {Array} stocks  - stock objects with _v2Prediction attached
 * @param {Array} v2Items - original V2 prediction items
 * @returns {Promise<void>}
 */
async function _enrichWatchlistWithQuotes(stocks, v2Items) {
  const v2Map = new Map(v2Items.map(item => [item.symbol, item]));

  await Promise.allSettled(stocks.map(async stock => {
    try {
      const quote = await getQuote(stock.symbol);
      if (!quote || !quote.current) return;

      const currentPrice = quote.current;
      stock.quote.current       = currentPrice;
      stock.quote.open          = quote.open          || 0;
      stock.quote.high          = quote.high          || 0;
      stock.quote.low           = quote.low           || 0;
      stock.quote.previousClose = quote.previousClose || 0;
      stock.quote.change        = quote.change        || 0;
      stock.quote.changePercent = quote.changePercent || 0;
      stock.quote.volume        = quote.volume        || 0;

      // Enrich the attached V2 prediction with live-price-based fields
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
      console.warn(`[Watchlist] Could not enrich ${stock.symbol} with live price:`, err.message);
    }
  }));
}

function _save(list) {
  try {
    localStorage.setItem(WL_KEY, JSON.stringify(list));
  } catch {
    // ignore
  }
}

function _dispatch(symbol, action) {
  document.dispatchEvent(new CustomEvent(CUSTOM_EVENT, {
    detail: { symbol, action },
    bubbles: true,
  }));
}

function _renderEmpty(container, message) {
  container.innerHTML = `
    <div class="watchlist-empty" style="grid-column: 1/-1;">
      <span class="watchlist-empty__icon">📋</span>
      <p class="watchlist-empty__text">${message || 'Your watchlist is empty. Search for stocks and tap ☆ to add them.'}</p>
    </div>
  `;
}

function _showSkeletons(container, count) {
  container.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const sk = document.createElement('div');
    sk.className = 'stock-card stock-card--skeleton';
    sk.setAttribute('aria-hidden', 'true');
    sk.innerHTML = `
      <div class="skeleton-line skeleton-line--short"></div>
      <div class="skeleton-line skeleton-line--long"></div>
      <div class="skeleton-line skeleton-line--medium"></div>
    `;
    container.appendChild(sk);
  }
}

function _appendClearButton(container) {
  const wrap = document.createElement('div');
  wrap.className = 'watchlist-header';
  wrap.style.gridColumn = '1/-1';
  const btn = document.createElement('button');
  btn.className = 'btn btn--danger';
  btn.textContent = 'Clear Watchlist';
  btn.addEventListener('click', () => {
    _save([]);
    _dispatch('*', 'cleared');
    showToast('Watchlist cleared.', 'info');
    _renderEmpty(container);
  });
  wrap.appendChild(btn);
  container.appendChild(wrap);
}

function _fakeDemoStock(sym) {
  const price = 100 + (sym.charCodeAt(0) % 400);
  return {
    symbol: sym,
    name: sym,
    exchange: null,
    industry: null,
    marketCap: null,
    quote: {
      current: price, open: price - 1, high: price + 2,
      low: price - 2, previousClose: price - 0.5,
      change: 0.5, changePercent: 0.5,
      volume: 1000000, history: [],
    },
    candles: [],
  };
}
