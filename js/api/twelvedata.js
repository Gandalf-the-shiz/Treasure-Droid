/**
 * js/api/twelvedata.js
 * Twelve Data API integration module — secondary fallback.
 *
 * Docs: https://twelvedata.com/docs
 * Free tier: 800 calls/day, 8 calls/minute, CORS ✅
 */

const BASE_URL = 'https://api.twelvedata.com';

/**
 * Get the Twelve Data API key from localStorage.
 * Uses the cache module's namespace prefix (nostradamus_twelvedata_key).
 * @returns {string|null}
 */
function getApiKey() {
  try {
    const raw = localStorage.getItem('nostradamus_twelvedata_key');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Perform a fetch request to the Twelve Data API.
 * @param {string} path  - API path (e.g. "/quote")
 * @param {Object} params  - Query parameters (excluding apikey)
 * @returns {Promise<Object>}
 */
async function apiFetch(path, params = {}) {
  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error('Twelve Data API key not configured. Add your key in Settings.');
  }
  const url = new URL(`${BASE_URL}${path}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  url.searchParams.set('apikey', apiKey);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Twelve Data API error: HTTP ${response.status} for ${path}`);
  }
  const data = await response.json();
  if (data.status === 'error' || data.code === 400) {
    throw new Error(`Twelve Data API error: ${data.message || 'Unknown error'}`);
  }
  return data;
}

/**
 * Fetch a real-time price quote.
 * @param {string} symbol
 * @returns {Promise<{symbol: string, name: string, exchange: string, currency: string, datetime: string, open: string, high: string, low: string, close: string, volume: string, previous_close: string, change: string, percent_change: string}>}
 */
export async function getQuote(symbol) {
  return apiFetch('/quote', { symbol });
}

/**
 * Fetch time series (OHLCV) data.
 * @param {string} symbol
 * @param {'1min'|'5min'|'15min'|'30min'|'1h'|'1day'|'1week'|'1month'} interval
 * @param {number} [outputsize=30]  - Number of data points to return
 * @returns {Promise<{values: Array<{datetime: string, open: string, high: string, low: string, close: string, volume: string}>}>}
 */
export async function getTimeSeries(symbol, interval = '1day', outputsize = 30) {
  return apiFetch('/time_series', { symbol, interval, outputsize });
}

/**
 * Search for symbols.
 * @param {string} query
 * @returns {Promise<Array<{symbol: string, instrument_name: string, exchange: string, mic_code: string, exchange_timezone: string, instrument_type: string, country: string, currency: string}>>}
 */
export async function searchSymbols(query) {
  const apiKey = getApiKey();
  const url = new URL(`${BASE_URL}/symbol_search`);
  url.searchParams.set('symbol', query);
  if (apiKey) url.searchParams.set('apikey', apiKey);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Twelve Data API error: HTTP ${response.status} for /symbol_search`);
  }
  const data = await response.json();
  if (data.status === 'error') {
    throw new Error(`Twelve Data API error: ${data.message || 'Unknown error'}`);
  }
  return data.data || [];
}

