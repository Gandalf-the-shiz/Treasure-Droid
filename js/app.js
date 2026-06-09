/**
 * js/app.js
 * Main application entry point for Nostradamus.
 *
 * Responsibilities:
 *  - Wait for the DOM and CDN libraries (TensorFlow.js, Chart.js) to be ready
 *  - Detect whether API keys are configured in localStorage
 *  - Show/hide the Demo Mode banner accordingly
 *  - Initialize all UI modules (dashboard, search, navigation)
 *  - Bootstrap the ML prediction engine if model weights are available
 *  - Wire up the Settings panel save/clear actions
 *
 * Phase 1: Scaffold — shows welcome screen and loads demo data.
 * Phase 2+: Will load live data via the API manager.
 */

import { getItem, setItem, removeItem, clearAll } from './storage/cache.js';
import { showToast } from './utils/helpers.js';
import { initDashboard } from './ui/dashboard.js';
import { initSearch } from './ui/search.js';
import { initTheme, toggleTheme } from './ui/theme.js';
import { initWatchlist } from './ui/watchlist.js';
import { initAccuracyDashboard } from './ui/accuracy-dashboard.js';
import { trainModel } from './ml/training.js';
import { loadDemoData, loadLatestPredictions } from './api/manager.js';
import { clearPredictions } from './ml/tracker.js';
import { openHelp } from './ui/help.js';
import { openStockDetail } from './ui/detail.js';

// ─── Constants ────────────────────────────────────────────────
const STORAGE_KEYS = {
  FINNHUB_KEY:    'finnhub_key',
  TWELVEDATA_KEY: 'twelvedata_key',
  POLYGON_KEY:    'polygon_key',
};

// ─── App State ────────────────────────────────────────────────
const appState = {
  /** @type {'demo'|'live'} */
  mode: 'demo',
  /** Whether TensorFlow.js loaded successfully */
  tfReady: false,
  /** Whether Chart.js loaded successfully */
  chartReady: false,
  /** @type {'dashboard'|'watchlist'|'accuracy'|'sectors'|'heatmap'|'screener'|'backtest'|'earnings'|'ipos'|'settings'} */
  activeView: 'dashboard',
  /**
   * V2 pipeline predictions loaded from data/predictions/YYYY-MM-DD.json.
   * null = not yet loaded (or not available).
   * @type {{ date: string, generatedAt: string, items: Array } | null}
   */
  v2Predictions: null,
};

// ─── Initialisation ───────────────────────────────────────────

/**
 * Bootstrap the entire application.
 * Called once the DOM is ready.
 */
async function init() {
  console.log('[Nostradamus] Initializing app…');

  initTheme();
  checkLibraries();
  detectMode();
  initNavigation();
  initHamburgerMenu();

  // Load V2 predictions before rendering UI so they're available for all views
  try {
    appState.v2Predictions = await loadLatestPredictions();
  } catch (err) {
    console.warn('[Nostradamus] Could not load V2 predictions:', err.message);
  }

  initSettingsPanel();
  initThemeToggle();
  registerServiceWorker();
  initOfflineDetection();

  // Initialize UI modules
  await initDashboard(appState);
  initSearch(appState);

  // Wire global "open detail" events from lazy-loaded views (heatmap, screener)
  _initDetailEventBridge(appState);

  console.log(`[Nostradamus] App ready in ${appState.mode} mode.`);
}

/**
 * Check that CDN libraries loaded successfully.
 * Logs warnings but does not crash the app.
 */
function checkLibraries() {
  // TensorFlow.js
  if (typeof tf !== 'undefined') {
    appState.tfReady = true;
    console.log('[Nostradamus] TensorFlow.js ready:', tf.version.tfjs);
  } else {
    console.warn('[Nostradamus] TensorFlow.js not loaded. ML predictions unavailable.');
  }

  // Chart.js
  if (typeof Chart !== 'undefined') {
    appState.chartReady = true;
    console.log('[Nostradamus] Chart.js ready.');
  } else {
    console.warn('[Nostradamus] Chart.js not loaded. Charts unavailable.');
  }
}

/**
 * Determine whether we're running in demo mode (no API keys)
 * or live mode (at least a Finnhub key is configured).
 */
function detectMode() {
  const hasAnyKey = getItem(STORAGE_KEYS.FINNHUB_KEY)
    || getItem(STORAGE_KEYS.TWELVEDATA_KEY)
    || getItem(STORAGE_KEYS.POLYGON_KEY);
  appState.mode = hasAnyKey ? 'live' : 'demo';
  console.log(`[Nostradamus] Mode: ${appState.mode}`);
}

// ─── Navigation ───────────────────────────────────────────────

function initNavigation() {
  const navDashboard = document.getElementById('nav-dashboard');
  const navWatchlist = document.getElementById('nav-watchlist');
  const navHeatmap   = document.getElementById('nav-heatmap');
  const navScreener  = document.getElementById('nav-screener');
  const navBacktest  = document.getElementById('nav-backtest');
  const navInvestor  = document.getElementById('nav-investor');
  const navEarnings  = document.getElementById('nav-earnings');
  const navIpos      = document.getElementById('nav-ipos');
  const navAccuracy  = document.getElementById('nav-accuracy');
  const navSectors   = document.getElementById('nav-sectors');
  const navHelp      = document.getElementById('nav-help');
  const navSettings  = document.getElementById('nav-settings');

  navDashboard?.addEventListener('click', () => navigateTo('dashboard'));
  navWatchlist?.addEventListener('click', () => navigateTo('watchlist'));
  navHeatmap?.addEventListener('click',   () => navigateTo('heatmap'));
  navScreener?.addEventListener('click',  () => navigateTo('screener'));
  navBacktest?.addEventListener('click',  () => navigateTo('backtest'));
  navInvestor?.addEventListener('click',  () => navigateTo('investor'));
  navEarnings?.addEventListener('click',  () => navigateTo('earnings'));
  navIpos?.addEventListener('click',      () => navigateTo('ipos'));
  navAccuracy?.addEventListener('click',  () => navigateTo('accuracy'));
  navSectors?.addEventListener('click',   () => navigateTo('sectors'));
  navHelp?.addEventListener('click',      () => openHelp());
  navSettings?.addEventListener('click',  () => navigateTo('settings'));
}

/**
 * Switch the visible view and update the active nav button.
 * @param {'dashboard'|'watchlist'|'accuracy'|'sectors'|'heatmap'|'screener'|'backtest'|'earnings'|'ipos'|'settings'} viewName
 */
function navigateTo(viewName) {
  const views = ['dashboard', 'watchlist', 'accuracy', 'sectors', 'heatmap', 'screener', 'backtest', 'investor', 'earnings', 'ipos', 'settings'];
  const navBtns = {
    dashboard: document.getElementById('nav-dashboard'),
    watchlist: document.getElementById('nav-watchlist'),
    accuracy:  document.getElementById('nav-accuracy'),
    sectors:   document.getElementById('nav-sectors'),
    heatmap:   document.getElementById('nav-heatmap'),
    screener:  document.getElementById('nav-screener'),
    backtest:  document.getElementById('nav-backtest'),
    investor:  document.getElementById('nav-investor'),
    earnings:  document.getElementById('nav-earnings'),
    ipos:      document.getElementById('nav-ipos'),
    settings:  document.getElementById('nav-settings'),
  };

  views.forEach(name => {
    const viewEl = document.getElementById(`view-${name}`);
    if (viewEl) viewEl.hidden = name !== viewName;

    const navBtn = navBtns[name];
    if (navBtn) {
      navBtn.classList.toggle('nav-btn--active', name === viewName);
      navBtn.setAttribute('aria-current', name === viewName ? 'page' : 'false');
    }
  });

  appState.activeView = viewName;

  // Notify mobile nav to sync active state
  document.dispatchEvent(new CustomEvent('navigated', { detail: { view: viewName } }));

  // Refresh view-specific content on navigation (lazy-loaded modules)
  if (viewName === 'watchlist') {
    initWatchlist(appState);
  } else if (viewName === 'accuracy') {
    initAccuracyDashboard(appState);
  } else if (viewName === 'sectors') {
    // Lazy-load sectors module on first visit
    import('./ui/sectors.js').then(({ renderSectorsPanel }) => {
      const container = document.getElementById('view-sectors');
      if (container) renderSectorsPanel(container, appState);
    }).catch(err => {
      console.error('[App] Failed to load sectors module:', err);
      showToast('Sectors view failed to load. Please refresh.', 'error');
    });
  } else if (viewName === 'heatmap') {
    import('./ui/heatmap.js').then(({ renderHeatmap }) => {
      const container = document.getElementById('view-heatmap');
      if (container) renderHeatmap(container, appState.v2Predictions?.items ?? null, appState);
    }).catch(err => {
      console.error('[App] Failed to load heatmap module:', err);
      showToast('Heatmap view failed to load. Please refresh.', 'error');
    });
  } else if (viewName === 'screener') {
    import('./ui/screener.js').then(({ renderScreener }) => {
      const container = document.getElementById('view-screener');
      if (container) renderScreener(container, appState.v2Predictions?.items ?? null, appState);
    }).catch(err => {
      console.error('[App] Failed to load screener module:', err);
      showToast('Screener view failed to load. Please refresh.', 'error');
    });
  } else if (viewName === 'backtest') {
    import('./ui/backtest-ui.js').then(({ renderBacktestUI }) => {
      const container = document.getElementById('view-backtest');
      if (container) renderBacktestUI(container, appState);
    }).catch(err => {
      console.error('[App] Failed to load backtest module:', err);
      showToast('Backtest view failed to load. Please refresh.', 'error');
    });
  } else if (viewName === 'investor') {
    import('./ui/investor.js').then(({ renderInvestorUI }) => {
      const container = document.getElementById('view-investor');
      if (container) renderInvestorUI(container, appState);
    }).catch(err => {
      console.error('[App] Failed to load investor module:', err);
      showToast('Investor view failed to load. Please refresh.', 'error');
    });
  } else if (viewName === 'earnings') {
    import('./ui/earnings.js').then(({ renderEarningsView }) => {
      const container = document.getElementById('view-earnings');
      if (container) renderEarningsView(container, appState);
    }).catch(err => {
      console.error('[App] Failed to load earnings module:', err);
      showToast('Earnings view failed to load. Please refresh.', 'error');
    });
  } else if (viewName === 'ipos') {
    import('./ui/ipos.js').then(({ renderIpoView }) => {
      const container = document.getElementById('view-ipos');
      if (container) renderIpoView(container, appState);
    }).catch(err => {
      console.error('[App] Failed to load IPO module:', err);
      showToast('IPO view failed to load. Please refresh.', 'error');
    });
  }
}

// ─── Theme Toggle ─────────────────────────────────────────────

function initThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  btn?.addEventListener('click', toggleTheme);
}

// ─── Hamburger Mobile Menu ────────────────────────────────────

function initHamburgerMenu() {
  const hamburger     = document.getElementById('nav-hamburger');
  const mobileNav     = document.getElementById('mobile-nav');
  const mobileOverlay = document.getElementById('mobile-nav-overlay');
  const closeBtn      = document.getElementById('mobile-nav-close');
  const themeBtn      = document.getElementById('mobile-theme-toggle');
  const helpBtn       = document.getElementById('mobile-nav-help');

  if (!hamburger || !mobileNav) return;

  function openMenu() {
    mobileNav.classList.add('mobile-nav--open');
    if (mobileOverlay) mobileOverlay.classList.add('mobile-nav-overlay--visible');
    hamburger.setAttribute('aria-expanded', 'true');
    document.body.classList.add('mobile-nav-active');
  }

  function closeMenu() {
    mobileNav.classList.remove('mobile-nav--open');
    if (mobileOverlay) mobileOverlay.classList.remove('mobile-nav-overlay--visible');
    hamburger.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('mobile-nav-active');
  }

  hamburger.addEventListener('click', () => {
    const isOpen = mobileNav.classList.contains('mobile-nav--open');
    isOpen ? closeMenu() : openMenu();
  });

  closeBtn?.addEventListener('click', closeMenu);
  mobileOverlay?.addEventListener('click', closeMenu);

  // Wire mobile nav buttons to navigateTo and close the panel
  mobileNav.querySelectorAll('[data-nav]').forEach(btn => {
    btn.addEventListener('click', () => {
      navigateTo(btn.dataset.nav);
      closeMenu();
    });
  });

  themeBtn?.addEventListener('click', () => {
    toggleTheme();
    closeMenu();
  });

  helpBtn?.addEventListener('click', () => {
    openHelp();
    closeMenu();
  });

  // Keep mobile nav active state in sync with the desktop nav
  document.addEventListener('navigated', e => {
    mobileNav.querySelectorAll('[data-nav]').forEach(btn => {
      btn.classList.toggle('nav-btn--active', btn.dataset.nav === e.detail?.view);
    });
  });

  // Close on Escape
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeMenu();
  });
}

// ─── Settings Panel ───────────────────────────────────────────

function initSettingsPanel() {
  const saveBtn       = document.getElementById('setting-save-btn');
  const clearBtn      = document.getElementById('setting-clear-btn');
  const clearCacheBtn = document.getElementById('setting-clear-cache-btn');
  const trainBtn      = document.getElementById('setting-train-btn');
  const clearModelBtn = document.getElementById('setting-clear-model-btn');
  const clearPredsBtn = document.getElementById('setting-clear-predictions-btn');

  // Populate existing keys (masked)
  populateSettingsInputs();

  saveBtn?.addEventListener('click', saveApiKeys);
  clearBtn?.addEventListener('click', clearApiKeys);
  clearCacheBtn?.addEventListener('click', clearCache);

  trainBtn?.addEventListener('click', async () => {
    trainBtn.disabled = true;
    trainBtn.textContent = 'Training…';
    const progressEl = document.getElementById('training-progress');
    if (progressEl) progressEl.hidden = false;

    try {
      const demoData = await loadDemoData();
      const allCandles = [];
      for (const stock of (demoData.stocks || [])) {
        if (stock.candles && stock.candles.length > 0) {
          allCandles.push(...stock.candles);
        }
      }
      // Note: candles from different stocks are combined into one dataset.
      // All close prices and volumes are min-max normalized within buildFeatureMatrix,
      // so relative scale differences between stocks are removed during preprocessing.

      await trainModel(allCandles, (progress) => {
        const epochEl = document.getElementById('training-epoch');
        const lossEl  = document.getElementById('training-loss');
        const barEl   = document.getElementById('training-progress-bar');
        if (epochEl) epochEl.textContent = `Epoch ${progress.epoch}/${progress.totalEpochs}`;
        if (lossEl)  lossEl.textContent  = `Loss: ${progress.loss.toFixed(6)}`;
        if (barEl)   barEl.style.width   = `${(progress.epoch / progress.totalEpochs) * 100}%`;
      });

      showToast('Model training complete! 🧠', 'success');
    } catch (err) {
      console.error('[App] Training failed:', err);
      showToast(`Training failed: ${err.message}`, 'error');
    } finally {
      trainBtn.disabled = false;
      trainBtn.textContent = '🧠 Train Model';
    }
  });

  clearModelBtn?.addEventListener('click', () => {
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.includes('nostradamus-model') || key === 'nostradamus_scaling_params')) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach(k => localStorage.removeItem(k));
    showToast('Saved model deleted.', 'info');
  });

  clearPredsBtn?.addEventListener('click', () => {
    clearPredictions();
    showToast('Prediction history cleared.', 'info');
  });

  document.getElementById('settings-goto-accuracy')?.addEventListener('click', () => {
    navigateTo('accuracy');
  });
}

function populateSettingsInputs() {
  const fields = [
    { id: 'setting-finnhub-key',    key: STORAGE_KEYS.FINNHUB_KEY },
    { id: 'setting-twelvedata-key', key: STORAGE_KEYS.TWELVEDATA_KEY },
    { id: 'setting-polygon-key',    key: STORAGE_KEYS.POLYGON_KEY },
  ];

  fields.forEach(({ id, key }) => {
    const input = document.getElementById(id);
    const value = getItem(key);
    if (input && value) {
      // Show masked value so user knows a key exists
      input.placeholder = '••••••••••••••••••••';
    }
  });
}

function saveApiKeys() {
  const fields = [
    { id: 'setting-finnhub-key',    key: STORAGE_KEYS.FINNHUB_KEY },
    { id: 'setting-twelvedata-key', key: STORAGE_KEYS.TWELVEDATA_KEY },
    { id: 'setting-polygon-key',    key: STORAGE_KEYS.POLYGON_KEY },
  ];

  let saved = 0;
  fields.forEach(({ id, key }) => {
    const input = document.getElementById(id);
    if (input?.value.trim()) {
      setItem(key, input.value.trim());
      input.value = '';
      input.placeholder = '••••••••••••••••••••';
      saved++;
    }
  });

  if (saved > 0) {
    showToast(`${saved} API key(s) saved.`, 'success');
    detectMode();
  } else {
    showToast('No keys entered.', 'info');
  }
}

function clearApiKeys() {
  Object.values(STORAGE_KEYS).forEach(key => removeItem(key));
  showToast('API keys cleared. Demo mode active.', 'info');
  detectMode();
  populateSettingsInputs();
}

function clearCache() {
  const count = clearAll(false);
  showToast(`Cache cleared (${count} entr${count === 1 ? 'y' : 'ies'} removed).`, 'success');
}

// ─── Service Worker ───────────────────────────────────────────

/**
 * Register the service worker for PWA / offline support.
 * Fails silently if service workers are not supported or if the
 * registration fails (e.g., cross-origin, local file:// protocol).
 */
function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').then(reg => {
      console.log('[SW] Registered:', reg.scope);
    }).catch(err => {
      console.warn('[SW] Registration failed (non-fatal):', err.message);
    });
  });
}

// ─── Offline detection ────────────────────────────────────────

/**
 * Show/hide the offline indicator banner when network status changes.
 */
function initOfflineDetection() {
  const banner = document.getElementById('offline-banner');
  if (!banner) return;

  function update() {
    banner.hidden = navigator.onLine;
    if (!navigator.onLine) {
      showToast('You are offline. Showing cached data.', 'info');
    }
  }

  window.addEventListener('online',  update);
  window.addEventListener('offline', update);
  update(); // Set initial state
}

// ─── Global detail overlay event bridge ───────────────────────

/**
 * Listen for "open detail" events bubbled up from lazy-loaded views
 * (heatmap canvas clicks, screener row clicks) and open the stock detail
 * overlay with whatever data is available at that point.
 *
 * Both events must be wired once, at app startup, not inside navigateTo()
 * to avoid registering duplicate listeners on repeated navigation.
 *
 * @param {{ mode: string, v2Predictions: object|null, _tickerMap: Map|undefined }} appState
 */
function _initDetailEventBridge(appState) {
  /**
   * Build a minimal stock object suitable for openStockDetail from a
   * prediction-only payload (no live quote data yet).
   */
  function _buildMinimalStock(symbol, pred) {
    const tickerMap = appState._tickerMap || new Map();
    const info = tickerMap.get(symbol) || {};
    return {
      symbol,
      name:     info.name || symbol,
      exchange: info.exchange || null,
      industry: info.sector || null,
      marketCap: null,
      quote: {
        current:       pred?.currentPrice   || 0,
        open:          0,
        high:          0,
        low:           0,
        previousClose: 0,
        change:        pred?.delta          || 0,
        changePercent: 0,
        volume:        0,
        history:       [],
      },
      candles: [],
      _v2Prediction: pred || null,
    };
  }

  // Heatmap cell click — detail: { symbol, pred }
  document.addEventListener('heatmap-cell-click', e => {
    const { symbol, pred } = e.detail || {};
    if (!symbol) return;
    const stock = _buildMinimalStock(symbol, pred);
    openStockDetail(symbol, stock, [], pred || null, appState);
  });

  // Screener row click — detail: { symbol, direction, confidence, … }
  document.addEventListener('screener-row-click', e => {
    const d = e.detail || {};
    const symbol = d.symbol;
    if (!symbol) return;
    // Reconstruct a prediction object from the row data passed in the event.
    // generatedAt is intentionally omitted — the screener row only carries
    // the latest model output, not the original timestamp.
    const pred = {
      symbol,
      direction:       d.direction       || 'UP',
      confidence:      d.confidence      ?? 0,
      probability:     d.probability     ?? 0.5,
      predictedReturn: d.predictedReturn ?? null,
      delta:           d.delta           || 0,
      currentPrice:    d.currentPrice    || 0,
      predictedPrice:  d.predictedPrice  || 0,
      isDemo:          false,
    };
    const stock = _buildMinimalStock(symbol, pred);
    openStockDetail(symbol, stock, [], pred, appState);
  });
}

// ─── DOM Ready ────────────────────────────────────────────────
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
