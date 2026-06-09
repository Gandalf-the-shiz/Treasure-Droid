/**
 * js/storage/cache.js
 * localStorage manager with TTL support.
 *
 * All keys are namespaced under "nostradamus_" to avoid collisions.
 *
 * Phase 1: Provides basic get/set/remove.
 * Phase 2: Adds TTL-aware cache for API responses.
 */

const CACHE_PREFIX = 'nostradamus_';
const DEFAULT_TTL_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Store a value in localStorage (no expiry — for persistent settings).
 * @param {string} key
 * @param {*} value  - Will be JSON-serialised.
 */
export function setItem(key, value) {
  try {
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(value));
  } catch (e) {
    console.warn('[Cache] setItem failed:', e.message);
  }
}

/**
 * Retrieve a value from localStorage.
 * @param {string} key
 * @returns {*} Parsed value, or null if not found.
 */
export function getItem(key) {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    return raw !== null ? JSON.parse(raw) : null;
  } catch (e) {
    console.warn('[Cache] getItem failed:', e.message);
    return null;
  }
}

/**
 * Remove a value from localStorage.
 * @param {string} key
 */
export function removeItem(key) {
  try {
    localStorage.removeItem(CACHE_PREFIX + key);
  } catch (e) {
    console.warn('[Cache] removeItem failed:', e.message);
  }
}

/**
 * Store a value with a TTL (Time-To-Live) expiry.
 * Used for API response caching to avoid re-fetching within the window.
 *
 * @param {string} key
 * @param {*} value
 * @param {number} [ttlMs=DEFAULT_TTL_MS]  - Expiry in milliseconds.
 */
export function setWithTTL(key, value, ttlMs = DEFAULT_TTL_MS) {
  const record = {
    value,
    expiresAt: Date.now() + ttlMs,
  };
  setItem(key, record);
}

/**
 * Retrieve a value only if it has not expired.
 *
 * @param {string} key
 * @returns {*} The cached value, or null if missing or expired.
 */
export function getWithTTL(key) {
  const record = getItem(key);
  if (!record || typeof record.expiresAt !== 'number') return null;
  if (Date.now() > record.expiresAt) {
    removeItem(key);
    return null;
  }
  return record.value;
}

/**
 * Clear all Nostradamus-namespaced cache entries.
 *
 * @param {boolean} [allKeys=false]  - If true, clears everything including
 *   persistent settings (API keys, preferences). If false (default), only
 *   clears TTL-cached API responses (keys matching quote_, candles_, profile_, search_).
 * @returns {number} The number of keys removed.
 */
export function clearAll(allKeys = false) {
  const keysToRemove = [];
  const API_CACHE_PATTERNS = ['quote_', 'candles_', 'profile_', 'search_'];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k || !k.startsWith(CACHE_PREFIX)) continue;
    if (allKeys) {
      keysToRemove.push(k);
    } else {
      // Strip the namespace prefix to check the bare key pattern
      const bare = k.slice(CACHE_PREFIX.length);
      if (API_CACHE_PATTERNS.some(p => bare.startsWith(p))) {
        keysToRemove.push(k);
      }
    }
  }
  keysToRemove.forEach(k => localStorage.removeItem(k));
  return keysToRemove.length;
}

/**
 * Return cache statistics for the Settings panel display.
 * @returns {{ totalKeys: number, expiredKeys: number, sizeEstimateKB: number }}
 */
export function getStats() {
  let totalKeys = 0;
  let expiredKeys = 0;
  let sizeBytes = 0;
  const now = Date.now();

  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k || !k.startsWith(CACHE_PREFIX)) continue;
    totalKeys++;
    const raw = localStorage.getItem(k) || '';
    sizeBytes += k.length + raw.length;
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.expiresAt === 'number' && now > parsed.expiresAt) {
        expiredKeys++;
      }
    } catch {
      // not a TTL entry, ignore
    }
  }

  return {
    totalKeys,
    expiredKeys,
    sizeEstimateKB: Math.round(sizeBytes / 1024),
  };
}
