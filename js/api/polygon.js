/**
 * js/api/polygon.js
 * Polygon.io API integration module — tertiary fallback.
 *
 * Docs: https://polygon.io/docs
 * Free tier: unlimited calls (prev-day data only on free tier), CORS ✅
 */

const BASE_URL = 'https://api.polygon.io';

/**
 * Get the Polygon.io API key from localStorage.
 * Uses the cache module's namespace prefix (nostradamus_polygon_key).
 * @returns {string|null}
 */
function getApiKey() {
  try {
    const raw = localStorage.getItem('nostradamus_polygon_key');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Perform a fetch request to the Polygon API.
 * @param {string} path  - API path
 * @param {Object} params  - Query parameters (excluding apiKey)
 * @returns {Promise<Object>}
 */
async function apiFetch(path, params = {}) {
  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error('Polygon API key not configured. Add your key in Settings.');
  }
  const url = new URL(`${BASE_URL}${path}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  url.searchParams.set('apiKey', apiKey);

  const response = await fetch(url.toString());
  if (!response.ok) {
    throw new Error(`Polygon API error: HTTP ${response.status} for ${path}`);
  }
  return response.json();
}

/**
 * Fetch the previous day's OHLCV data for a ticker.
 * @param {string} ticker  - e.g. "AAPL"
 * @returns {Promise<{ticker: string, queryCount: number, resultsCount: number, adjusted: boolean, results: Array<{T: string, v: number, o: number, c: number, h: number, l: number, t: number, n: number}>}>}
 */
export async function getPreviousClose(ticker) {
  return apiFetch(`/v2/aggs/ticker/${encodeURIComponent(ticker)}/prev`, { adjusted: 'true' });
}

/**
 * Fetch aggregate OHLCV bars for a range.
 * @param {string} ticker
 * @param {number} multiplier  - Size of the timespan multiplier (e.g. 1)
 * @param {'minute'|'hour'|'day'|'week'|'month'|'quarter'|'year'} timespan
 * @param {string} from  - YYYY-MM-DD
 * @param {string} to    - YYYY-MM-DD
 * @returns {Promise<Object>}
 */
export async function getAggregates(ticker, multiplier, timespan, from, to) {
  return apiFetch(
    `/v2/aggs/ticker/${encodeURIComponent(ticker)}/range/${multiplier}/${timespan}/${from}/${to}`,
    { adjusted: 'true', sort: 'asc' }
  );
}

/**
 * Search for tickers matching a query.
 * @param {string} query
 * @returns {Promise<Array<{ticker: string, name: string, market: string, locale: string, type: string, currency_name: string}>>}
 */
export async function searchTickers(query) {
  const data = await apiFetch('/v3/reference/tickers', {
    search: query,
    active: 'true',
    limit: '10',
  });
  return data.results || [];
}

/**
 * Fetch ticker details (company info, description, etc.).
 * @param {string} ticker
 * @returns {Promise<Object>}
 */
export async function getTickerDetails(ticker) {
  const data = await apiFetch(`/v3/reference/tickers/${encodeURIComponent(ticker)}`);
  return data.results || data;
}
