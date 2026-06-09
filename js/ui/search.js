/**
 * js/ui/search.js
 * Stock search bar with autocomplete suggestions.
 *
 * Phase 1: Wires up the search input with a no-op handler.
 * Phase 2: Calls api/manager.js searchSymbols for live autocomplete.
 * Phase 3: Clicking a suggestion opens the stock detail view + watchlist star.
 */

import { searchSymbols, getQuote, getCandles } from '../api/manager.js';
import { demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';
import { openStockDetail } from './detail.js';
import { isInWatchlist, addToWatchlist, removeFromWatchlist } from './watchlist.js';
import { escapeHtml } from '../utils/helpers.js';

/** Minimum characters before triggering a search. */
const MIN_QUERY_LENGTH = 2;
/** Debounce delay in ms to avoid firing on every keystroke. */
const DEBOUNCE_MS = 300;
/** Max suggestions to display. */
const MAX_SUGGESTIONS = 8;

/** In-memory cache of the ticker registry (loaded once). */
let _tickerRegistry = null;
/** Promise guard to avoid duplicate fetches. */
let _tickerRegistryPromise = null;

/**
 * Load the committed ticker registry from data/tickers/us_tickers.json.
 * Caches the result in memory so subsequent calls are free.
 * @returns {Promise<Array<{symbol: string, name: string, exchange: string, sector: string}>>}
 */
async function loadTickerRegistry() {
  if (_tickerRegistry !== null) return _tickerRegistry;
  if (_tickerRegistryPromise) return _tickerRegistryPromise;

  _tickerRegistryPromise = (async () => {
    try {
      const resp = await fetch('./data/tickers/us_tickers.json');
      if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
      const data = await resp.json();
      _tickerRegistry = Array.isArray(data.tickers) ? data.tickers : [];
      console.log(`[Search] Ticker registry loaded: ${_tickerRegistry.length.toLocaleString()} tickers`);
    } catch (err) {
      // Registry may not exist yet (first deploy before workflow runs) — this is expected
      console.warn('[Search] Could not load ticker registry, falling back to hardcoded list:', err.message);
      _tickerRegistry = [];
    }
    return _tickerRegistry;
  })();

  return _tickerRegistryPromise;
}

/**
 * Initialize the search bar.
 * @param {{ mode: 'demo'|'live' }} appState
 */
export function initSearch(appState) {
  // Kick off registry load in the background so it's ready before the user types
  loadTickerRegistry();
  const input       = document.getElementById('stock-search');
  const suggestions = document.getElementById('search-suggestions');

  if (!input || !suggestions) return;

  let debounceTimer = null;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const query = input.value.trim();

    if (query.length < MIN_QUERY_LENGTH) {
      hideSuggestions(suggestions);
      return;
    }

    debounceTimer = setTimeout(() => {
      handleSearch(query, suggestions, appState);
    }, DEBOUNCE_MS);
  });

  // Close suggestions when clicking outside
  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !suggestions.contains(e.target)) {
      hideSuggestions(suggestions);
    }
  });

  // Keyboard navigation within suggestions
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') hideSuggestions(suggestions);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const first = suggestions.querySelector('[role="option"]');
      first?.focus();
    }
  });

  console.log('[Search] Initialized.');
}

/**
 * Handle a search query.
 * @param {string} query
 * @param {HTMLElement} suggestions
 * @param {{ mode: string }} appState
 */
async function handleSearch(query, suggestions, appState) {
  suggestions.hidden = false;
  suggestions.innerHTML = '<div class="search-suggestion-item" style="color:var(--color-text-muted)">Searching…</div>';

  try {
    let results;
    // Always try API search first — manager handles fallback gracefully
    try {
      results = await searchSymbols(query);
    } catch (err) {
      console.warn('[Search] API search failed, using local registry:', err.message);
    }
    // Fall back to local ticker registry if API returned nothing
    if (!results || results.length === 0) {
      results = await getDemoSearchResults(query);
    }

    if (results.length === 0) {
      suggestions.innerHTML = `<div class="search-suggestion-item" style="color:var(--color-text-muted)">No results for "${escapeHtml(query)}"</div>`;
      return;
    }

    renderSuggestions(suggestions, results, appState);
  } catch (err) {
    console.error('[Search] Error:', err);
    // Try demo fallback on error
    try {
      const results = await getDemoSearchResults(query);
      if (results.length > 0) {
        renderSuggestions(suggestions, results, appState);
        return;
      }
    } catch {
      // ignore
    }
    suggestions.innerHTML = '<div class="search-suggestion-item" style="color:var(--color-down)">Search failed. Try again.</div>';
  }
}

/**
 * Search over the committed ticker registry (7,000+ tickers).
 * Matches on symbol prefix OR company name substring (case-insensitive).
 * Falls back to a small hardcoded list if the registry hasn't loaded yet.
 * @param {string} query
 * @returns {Promise<Array<{symbol: string, name: string, exchange: string, sector: string}>>}
 */
async function getDemoSearchResults(query) {
  const FALLBACK = [
    { symbol: 'AAPL',  name: 'Apple Inc.',              exchange: 'NASDAQ', sector: 'Technology' },
    { symbol: 'GOOGL', name: 'Alphabet Inc.',            exchange: 'NASDAQ', sector: 'Technology' },
    { symbol: 'MSFT',  name: 'Microsoft Corporation',    exchange: 'NASDAQ', sector: 'Technology' },
    { symbol: 'AMZN',  name: 'Amazon.com Inc.',          exchange: 'NASDAQ', sector: 'Consumer Discretionary' },
    { symbol: 'TSLA',  name: 'Tesla, Inc.',              exchange: 'NASDAQ', sector: 'Consumer Discretionary' },
    { symbol: 'META',  name: 'Meta Platforms Inc.',      exchange: 'NASDAQ', sector: 'Communication Services' },
    { symbol: 'NVDA',  name: 'NVIDIA Corporation',       exchange: 'NASDAQ', sector: 'Technology' },
    { symbol: 'NFLX',  name: 'Netflix, Inc.',            exchange: 'NASDAQ', sector: 'Communication Services' },
    { symbol: 'BRKB',  name: 'Berkshire Hathaway Inc.',  exchange: 'NYSE',   sector: 'Financials' },
    { symbol: 'JPM',   name: 'JPMorgan Chase & Co.',     exchange: 'NYSE',   sector: 'Financials' },
  ];

  const registry = await loadTickerRegistry();
  const pool = registry.length > 0 ? registry : FALLBACK;

  const q = query.toUpperCase();
  const qLower = query.toLowerCase();

  const results = [];
  for (const entry of pool) {
    if (
      entry.symbol.startsWith(q) ||
      entry.name.toLowerCase().includes(qLower)
    ) {
      results.push(entry);
      if (results.length >= MAX_SUGGESTIONS) break;
    }
  }
  return results;
}

/**
 * Render autocomplete suggestions into the dropdown.
 * Each suggestion has a ☆/★ watchlist button on the right.
 * @param {HTMLElement} container
 * @param {Array<{symbol: string, name: string}>} results
 * @param {{ mode: string }} appState
 */
function renderSuggestions(container, results, appState) {
  container.innerHTML = '';
  results.slice(0, MAX_SUGGESTIONS).forEach((item, index) => {
    const inWL = isInWatchlist(item.symbol);
    const el = document.createElement('div');
    el.className = 'search-suggestion-item';
    el.setAttribute('role', 'option');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-selected', 'false');
    el.innerHTML = `
      <span class="search-suggestion-item__symbol">${escapeHtml(item.symbol)}</span>
      <span class="search-suggestion-item__name">${escapeHtml(item.name)}</span>
      <button
        class="search-suggestion-item__wl-btn${inWL ? ' search-suggestion-item__wl-btn--active' : ''}"
        aria-label="${inWL ? 'Remove from' : 'Add to'} watchlist"
        title="${inWL ? 'Remove from watchlist' : 'Add to watchlist'}"
        data-symbol="${escapeHtml(item.symbol)}"
      >${inWL ? '★' : '☆'}</button>
    `;

    // Watchlist star click — toggle without opening the detail view
    el.querySelector('.search-suggestion-item__wl-btn')?.addEventListener('click', e => {
      e.stopPropagation();
      const sym = item.symbol;
      const btn = e.currentTarget;
      if (isInWatchlist(sym)) {
        removeFromWatchlist(sym);
        btn.textContent = '☆';
        btn.classList.remove('search-suggestion-item__wl-btn--active');
        btn.setAttribute('aria-label', 'Add to watchlist');
        btn.title = 'Add to watchlist';
      } else {
        addToWatchlist(sym);
        btn.textContent = '★';
        btn.classList.add('search-suggestion-item__wl-btn--active');
        btn.setAttribute('aria-label', 'Remove from watchlist');
        btn.title = 'Remove from watchlist';
      }
    });

    el.addEventListener('click', () => {
      onSelectSymbol(item.symbol, container, appState);
    });

    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelectSymbol(item.symbol, container, appState);
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        el.nextElementSibling?.focus();
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = el.previousElementSibling;
        if (prev) prev.focus();
        else document.getElementById('stock-search')?.focus();
      }
    });

    container.appendChild(el);
  });
}

/**
 * Handle selecting a symbol from the suggestions.
 * Fetches stock data, adds card to dashboard, and opens detail view.
 * @param {string} symbol
 * @param {HTMLElement} suggestionsEl
 * @param {{ mode: string }} appState
 */
async function onSelectSymbol(symbol, suggestionsEl, appState) {
  const input = document.getElementById('stock-search');
  if (input) input.value = symbol;
  hideSuggestions(suggestionsEl);

  await addSymbolToDashboard(symbol, appState);
}

/**
 * Fetch data for a symbol and add a new card to the dashboard stock grid,
 * then open the stock detail view.
 * @param {string} symbol
 * @param {{ chartReady: boolean, mode: string }} appState
 */
async function addSymbolToDashboard(symbol, appState) {
  const stockGrid = document.getElementById('stock-grid');
  if (!stockGrid) return;

  let stock = null;
  let candles = [];

  try {
    let quote = null;

    // Always try live APIs — the manager handles fallback gracefully
    try {
      [quote, candles] = await Promise.all([
        getQuote(symbol),
        getCandles(symbol),
      ]);
    } catch (err) {
      console.warn(`[Search] API calls failed for ${symbol}, using demo fallback:`, err.message);
    }

    if (!quote) {
      // Demo fallback: build a minimal object so the detail view still opens
      const price = 100 + (symbol.charCodeAt(0) % 400);
      quote = {
        symbol, current: price, open: price - 1, high: price + 2,
        low: price - 2, previousClose: price - 0.5,
        change: 0.5, changePercent: 0.5, volume: 1000000,
      };
    }

    stock = {
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
    };

    // Use V2 pipeline prediction if available for this symbol; fall back to demo
    const v2Item = appState?.v2Predictions?.items?.find(p => p.symbol === symbol);
    const prediction = v2Item || demoPrediction(stock.symbol, stock.quote.current);

    // Attach V2 prediction to stock object so the card renders correctly
    if (v2Item) {
      stock._v2Prediction = v2Item;
    }

    // Add card to dashboard grid if it's not already there
    if (!stockGrid.querySelector(`[data-symbol="${symbol}"]`)) {
      const card = renderStockCard(stock, prediction, appState.chartReady);
      card.classList.add('stock-card--animate-in');
      stockGrid.appendChild(card);
    }

    // Open detail view
    openStockDetail(symbol, stock, candles, prediction, appState);
    console.log(`[Search] Added ${symbol} to dashboard and opened detail.`);
  } catch (err) {
    console.error(`[Search] Failed to add ${symbol}:`, err.message);
  }
}

/**
 * Hide the suggestions dropdown.
 * @param {HTMLElement} el
 */
function hideSuggestions(el) {
  el.hidden = true;
  el.innerHTML = '';
}



