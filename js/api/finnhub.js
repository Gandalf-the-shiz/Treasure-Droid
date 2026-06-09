/**
 * js/api/finnhub.js
 * Finnhub API integration module — primary data source.
 *
 * Docs: https://finnhub.io/docs/api
 * Free tier: 60 API calls/minute, WebSocket support, CORS ✅
 */

const BASE_URL = 'https://finnhub.io/api/v1';

/**
 * Get the Finnhub API key from localStorage.
 * Uses the cache module's namespace prefix (nostradamus_finnhub_key).
 * @returns {string|null}
 */
function getApiKey() {
  try {
    const raw = localStorage.getItem('nostradamus_finnhub_key');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Perform a fetch request to the Finnhub API.
 * @param {string} path  - API path (e.g. "/quote")
 * @param {Object} params  - Query parameters (excluding token)
 * @returns {Promise<Object>}
 */
async function apiFetch(path, params = {}) {
  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error('Finnhub API key not configured. Add your key in Settings.');
  }
  const url = new URL(`${BASE_URL}${path}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  url.searchParams.set('token', apiKey);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Finnhub API error: HTTP ${response.status} for ${path}`);
  }
  return response.json();
}

/**
 * Fetch the real-time quote for a stock symbol.
 * @param {string} symbol  - e.g. "AAPL"
 * @returns {Promise<{c: number, d: number, dp: number, h: number, l: number, o: number, pc: number, t: number}>}
 *   c=current, d=change, dp=change%, h=high, l=low, o=open, pc=prev close, t=timestamp
 */
export async function getQuote(symbol) {
  return apiFetch('/quote', { symbol });
}

/**
 * Fetch company profile (name, industry, market cap, logo, etc.).
 * @param {string} symbol
 * @returns {Promise<Object>}
 */
export async function getCompanyProfile(symbol) {
  return apiFetch('/stock/profile2', { symbol });
}

/**
 * Fetch historical OHLCV candlestick data.
 * @param {string} symbol
 * @param {'1'|'5'|'15'|'30'|'60'|'D'|'W'|'M'} resolution  - Candle resolution
 * @param {number} from  - Unix timestamp (seconds), start of range
 * @param {number} to    - Unix timestamp (seconds), end of range
 * @returns {Promise<{c: number[], h: number[], l: number[], o: number[], v: number[], t: number[], s: string}>}
 */
export async function getCandles(symbol, resolution, from, to) {
  return apiFetch('/stock/candle', { symbol, resolution, from, to });
}

/**
 * Search for symbols matching a query string.
 * @param {string} query  - e.g. "Apple" or "AAPL"
 * @returns {Promise<{result: Array<{description: string, displaySymbol: string, symbol: string, type: string}>}>}
 */
export async function searchSymbols(query) {
  return apiFetch('/search', { q: query });
}

/**
 * Fetch latest company news.
 * @param {string} symbol
 * @param {string} from  - YYYY-MM-DD
 * @param {string} to    - YYYY-MM-DD
 * @returns {Promise<Array<{category: string, datetime: number, headline: string, id: number, image: string, related: string, source: string, summary: string, url: string}>>}
 */
export async function getCompanyNews(symbol, from, to) {
  return apiFetch('/company-news', { symbol, from, to });
}

/**
 * Fetch earnings calendar from Finnhub.
 * @param {string} from - YYYY-MM-DD
 * @param {string} to - YYYY-MM-DD
 * @param {string} [symbol] - Optional ticker filter
 * @returns {Promise<{earningsCalendar?: Array}>}
 */
export async function getEarningsCalendar(from, to, symbol) {
  const params = { from, to };
  if (symbol) params.symbol = symbol;
  return apiFetch('/calendar/earnings', params);
}

/**
 * Open a WebSocket connection for real-time trade data.
 * @param {string[]} symbols  - Array of symbols to subscribe to
 * @param {(trade: Object) => void} onTrade  - Callback for each trade event
 * @returns {{ close: () => void }}  - Object with a close() method to unsubscribe
 */
export function openTradesWebSocket(symbols, onTrade) {
  const apiKey = getApiKey();
  if (!apiKey) {
    console.warn('[Finnhub] WebSocket: API key not configured.');
    return { close: () => {} };
  }

  const ws = new WebSocket(`wss://ws.finnhub.io?token=${apiKey}`);

  ws.addEventListener('open', () => {
    symbols.forEach(symbol => {
      ws.send(JSON.stringify({ type: 'subscribe', symbol }));
    });
  });

  ws.addEventListener('message', event => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'trade' && Array.isArray(data.data)) {
        data.data.forEach(trade => onTrade(trade));
      }
    } catch (err) {
      console.warn('[Finnhub] WebSocket message parse error:', err.message);
    }
  });

  ws.addEventListener('error', err => {
    console.error('[Finnhub] WebSocket error:', err);
  });

  return {
    close: () => {
      symbols.forEach(symbol => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'unsubscribe', symbol }));
        }
      });
      ws.close();
    },
  };
}
