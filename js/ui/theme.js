/**
 * js/ui/theme.js
 * Dark / Light theme toggle for Nostradamus.
 *
 * Reads / writes `nostradamus_theme` via localStorage (raw, no cache TTL).
 * Applies theme by setting data-theme="light" on <html> (dark is the default).
 * Updates <meta name="theme-color"> to match.
 * Adds `.theme-transitioning` briefly so CSS can animate the change.
 */

const THEME_KEY  = 'nostradamus_theme';   // raw localStorage key
const DARK_META  = '#0f1117';
const LIGHT_META = '#f5f7fa';

/**
 * Initialise the theme on page load.
 * Reads saved preference; falls back to prefers-color-scheme; defaults to dark.
 */
export function initTheme() {
  const saved = _readRaw();
  let theme;

  if (saved === 'light' || saved === 'dark') {
    theme = saved;
  } else {
    // Use system preference as a hint
    theme = window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  _applyTheme(theme, false);
  _updateToggleButton(theme);
}

/**
 * Toggle between dark and light themes.
 * Saves the preference to localStorage and smoothly transitions.
 */
export function toggleTheme() {
  const current = _current();
  const next    = current === 'dark' ? 'light' : 'dark';

  _saveRaw(next);
  _applyTheme(next, true);
  _updateToggleButton(next);
}

/**
 * Return the current theme name.
 * @returns {'dark'|'light'}
 */
export function currentTheme() {
  return _current();
}

// ─── Private helpers ──────────────────────────────────────────

function _current() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

function _applyTheme(theme, animate) {
  const html = document.documentElement;

  if (animate) {
    html.classList.add('theme-transitioning');
    setTimeout(() => html.classList.remove('theme-transitioning'), 400);
  }

  if (theme === 'light') {
    html.dataset.theme = 'light';
  } else {
    delete html.dataset.theme;
  }

  // Update theme-color meta tag
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute('content', theme === 'light' ? LIGHT_META : DARK_META);
  }
}

function _updateToggleButton(theme) {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.textContent = theme === 'dark' ? '🌙' : '☀️';
  btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  btn.setAttribute('title', btn.getAttribute('aria-label'));
}

function _readRaw() {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch {
    return null;
  }
}

function _saveRaw(value) {
  try {
    localStorage.setItem(THEME_KEY, value);
  } catch {
    // ignore quota errors
  }
}
