/**
 * sw.js — Nostradamus Service Worker
 *
 * Implements a cache-first strategy for the app shell and a
 * network-first strategy for API calls. Enables offline support
 * and makes the app installable as a PWA.
 *
 * Cache strategy:
 *   - App shell (HTML, CSS, JS modules, icons) → cache-first
 *   - CDN assets (TensorFlow.js, Chart.js) → stale-while-revalidate
 *   - Finnhub / Twelve Data / Polygon API calls → network-only (no cache)
 *   - data/sample.json, models/ → cache-first
 */

const CACHE_VERSION = 'nostradamus-v7';
const SHELL_CACHE   = `${CACHE_VERSION}-shell`;
const CDN_CACHE     = `${CACHE_VERSION}-cdn`;

/** Files that form the app shell — cached on install. */
const SHELL_ASSETS = [
  './',
  './index.html',
  './css/styles.css',
  './js/app.js',
  './js/api/finnhub.js',
  './js/api/twelvedata.js',
  './js/api/polygon.js',
  './js/api/manager.js',
  './js/ml/model.js',
  './js/ml/training.js',
  './js/ml/prediction.js',
  './js/ml/preprocessing.js',
  './js/ml/tracker.js',
  './js/ml/accuracy.js',
  './js/ml/versioning.js',
  './js/ml/retraining.js',
  './js/ui/dashboard.js',
  './js/ui/charts.js',
  './js/ui/stockcard.js',
  './js/ui/search.js',
  './js/ui/detail.js',
  './js/ui/watchlist.js',
  './js/ui/theme.js',
  './js/ui/accuracy-dashboard.js',
  './js/ui/sectors.js',
  './js/ui/news.js',
  './js/ui/help.js',
  './js/ui/earnings.js',
  './js/ui/share.js',
  './js/ui/export.js',
  './js/storage/cache.js',
  './js/utils/helpers.js',
  './data/sample.json',
  './data/sample-earnings.json',
  './manifest.json',
  './icons/icon-192.svg',
  './icons/icon-512.svg',
];

/** CDN URLs to cache with stale-while-revalidate. */
const CDN_ASSETS = [
  'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js',
];

// ─── Install ─────────────────────────────────────────────────

self.addEventListener('install', event => {
  event.waitUntil(
    (async () => {
      // Cache app shell
      const shellCache = await caches.open(SHELL_CACHE);
      await shellCache.addAll(SHELL_ASSETS).catch(err => {
        // Non-fatal: log but don't block install
        console.warn('[SW] Some shell assets failed to pre-cache:', err.message);
      });

      // Cache CDN assets
      const cdnCache = await caches.open(CDN_CACHE);
      await cdnCache.addAll(CDN_ASSETS).catch(err => {
        console.warn('[SW] CDN assets failed to pre-cache:', err.message);
      });

      // Activate immediately without waiting for old SW to idle
      await self.skipWaiting();
      console.log('[SW] Installed and shell cached.');
    })()
  );
});

// ─── Activate ────────────────────────────────────────────────

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      // Delete caches from previous versions
      const allKeys = await caches.keys();
      await Promise.all(
        allKeys
          .filter(key => key.startsWith('nostradamus-') && key !== SHELL_CACHE && key !== CDN_CACHE)
          .map(key => caches.delete(key))
      );
      // Take control of all open clients immediately
      await self.clients.claim();
      console.log('[SW] Activated. Old caches removed.');
    })()
  );
});

// ─── Fetch ───────────────────────────────────────────────────

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Pass through all non-GET requests and cross-origin API calls
  if (event.request.method !== 'GET') return;

  // Never cache: local server APIs + live data files (so the UI always sees fresh data).
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/data/historical/') ||
    url.pathname.startsWith('/data/investor_v3/') ||
    url.pathname.startsWith('/data/sentiment/')
  ) {
    return; // network-only, no SW interception
  }

  // Never cache API calls to external data providers
  if (
    url.hostname === 'finnhub.io' ||
    url.hostname === 'api.twelvedata.com' ||
    url.hostname === 'api.polygon.io'
  ) {
    // Network-only: let the request pass through unchanged
    return;
  }

  // CDN assets: stale-while-revalidate
  if (url.hostname === 'cdn.jsdelivr.net') {
    event.respondWith(staleWhileRevalidate(event.request, CDN_CACHE));
    return;
  }

  // Prediction JSON files: network-first so fresh data is always preferred
  if (url.pathname.includes('/data/predictions/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // App shell: cache-first with network fallback
  event.respondWith(cacheFirst(event.request));
});

// ─── Cache Strategies ────────────────────────────────────────

/**
 * Network-first strategy.
 * Fetches from the network first; caches the response on success.
 * Falls back to the cache if the network request fails.
 * Returns a 503 if both fail.
 *
 * @param {Request} request
 * @returns {Promise<Response>}
 */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response('Prediction data unavailable offline.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/**
 * Cache-first strategy.
 * Returns the cached response if available, otherwise fetches from
 * the network, caches the response, and returns it.
 * If both fail (offline + not cached) returns a minimal offline page.
 *
 * @param {Request} request
 * @returns {Promise<Response>}
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Offline and not cached — return the cached index.html as fallback
    const fallback = await caches.match('./index.html');
    if (fallback) return fallback;
    return new Response('Offline — Nostradamus is not cached yet. Please connect to the internet first.', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/**
 * Stale-while-revalidate strategy.
 * Returns the cached version immediately (if available) while
 * simultaneously updating the cache from the network.
 *
 * @param {Request} request
 * @param {string}  cacheName
 * @returns {Promise<Response>}
 */
async function staleWhileRevalidate(request, cacheName) {
  const cache  = await caches.open(cacheName);
  const cached = await cache.match(request);

  const networkFetch = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  return cached || await networkFetch || new Response('CDN resource unavailable offline.', {
    status: 503,
    headers: { 'Content-Type': 'text/plain' },
  });
}

// ─── Offline status broadcast ─────────────────────────────────

/**
 * Listen for messages from the main thread (e.g. to skip waiting).
 */
self.addEventListener('message', event => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
