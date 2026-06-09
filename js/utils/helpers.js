/**
 * js/utils/helpers.js
 * Shared utility functions used across all modules.
 *
 * Covers: number formatting, date helpers, DOM utilities, toast notifications.
 */

// ─── Number Formatting ────────────────────────────────────────

/**
 * Format a number as a USD currency string.
 * @param {number} value
 * @param {number} [decimals=2]
 * @returns {string}  e.g. "$182.63"
 */
export function formatCurrency(value, decimals = 2) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * Format a percentage change.
 * @param {number} value  - e.g. 1.23 for +1.23%
 * @returns {string}  e.g. "+1.23%" or "-0.45%"
 */
export function formatPercent(value) {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

/**
 * Format a signed dollar change.
 * @param {number} value
 * @returns {string}  e.g. "+$2.15" or "-$1.03"
 */
export function formatDollarChange(value) {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${formatCurrency(value)}`;
}

/**
 * Format a large number with K/M/B abbreviation.
 * @param {number} value
 * @returns {string}  e.g. "2.3M" or "14.5B"
 */
export function formatLargeNumber(value) {
  if (Math.abs(value) >= 1e9)  return `${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6)  return `${(value / 1e6).toFixed(1)}M`;
  if (Math.abs(value) >= 1e3)  return `${(value / 1e3).toFixed(1)}K`;
  return String(value);
}

// ─── Date Helpers ─────────────────────────────────────────────

/**
 * Format a Unix timestamp (seconds) to a short date string.
 * @param {number} ts  - Unix timestamp in seconds
 * @returns {string}  e.g. "Apr 5"
 */
export function formatDateShort(ts) {
  return new Date(ts * 1000).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Return the current date in YYYY-MM-DD format (for API calls).
 * @returns {string}
 */
export function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Return the date N days ago in YYYY-MM-DD format.
 * @param {number} days
 * @returns {string}
 */
export function daysAgoISO(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

// ─── Math / Array Utilities ───────────────────────────────────

/**
 * Calculate the simple moving average over the last N values of an array.
 * @param {number[]} arr
 * @param {number} window
 * @returns {number[]}  Same length as input; initial values are NaN.
 */
export function sma(arr, window) {
  return arr.map((_, i) => {
    if (i < window - 1) return NaN;
    const slice = arr.slice(i - window + 1, i + 1);
    return slice.reduce((sum, v) => sum + v, 0) / window;
  });
}

/**
 * Clamp a number between min and max.
 * @param {number} value
 * @param {number} min
 * @param {number} max
 * @returns {number}
 */
export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

/**
 * Linear interpolation.
 * @param {number} a
 * @param {number} b
 * @param {number} t  - 0..1
 * @returns {number}
 */
export function lerp(a, b, t) {
  return a + (b - a) * t;
}

// ─── DOM Utilities ────────────────────────────────────────────

/**
 * Shorthand for querySelector with optional parent context.
 * @param {string} selector
 * @param {Element|Document} [parent=document]
 * @returns {Element|null}
 */
export function qs(selector, parent = document) {
  return parent.querySelector(selector);
}

/**
 * Shorthand for querySelectorAll → Array.
 * @param {string} selector
 * @param {Element|Document} [parent=document]
 * @returns {Element[]}
 */
export function qsa(selector, parent = document) {
  return Array.from(parent.querySelectorAll(selector));
}

/**
 * Create a DOM element with optional attributes and children.
 * @param {string} tag
 * @param {Object} [attrs={}]
 * @param {...(string|Element)} children
 * @returns {Element}
 */
export function createElement(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'className') el.className = v;
    else if (k === 'textContent') el.textContent = v;
    else el.setAttribute(k, v);
  });
  children.forEach(child => {
    if (typeof child === 'string') el.appendChild(document.createTextNode(child));
    else if (child instanceof Element) el.appendChild(child);
  });
  return el;
}

// ─── Toast Notifications ──────────────────────────────────────

/** @type {HTMLElement|null} */
let _toastContainer = null;

function getToastContainer() {
  if (!_toastContainer) {
    _toastContainer = createElement('div', { className: 'toast-container', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(_toastContainer);
  }
  return _toastContainer;
}

/**
 * Show a brief toast notification.
 * @param {string} message
 * @param {'success'|'error'|'info'} [type='info']
 * @param {number} [durationMs=3000]
 */
export function showToast(message, type = 'info', durationMs = 3000) {
  const container = getToastContainer();
  const toast = createElement('div', { className: `toast toast--${type}`, role: 'alert' }, message);
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 300ms';
    setTimeout(() => toast.remove(), 300);
  }, durationMs);
}

// ─── HTML Sanitisation ────────────────────────────────────────

/**
 * Escape HTML special characters to prevent XSS when injecting
 * untrusted strings into innerHTML.
 * @param {string} str
 * @returns {string}
 */
export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── Async Utilities ──────────────────────────────────────────

/**
 * Wait for a given number of milliseconds.
 * @param {number} ms
 * @returns {Promise<void>}
 */
export function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Retry an async function with exponential backoff.
 * @param {() => Promise<*>} fn
 * @param {number} [maxRetries=3]
 * @param {number} [baseDelayMs=500]
 * @returns {Promise<*>}
 */
export async function withRetry(fn, maxRetries = 3, baseDelayMs = 500) {
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt < maxRetries) {
        const delay = baseDelayMs * Math.pow(2, attempt);
        console.warn(`[Retry] Attempt ${attempt + 1} failed. Retrying in ${delay}ms…`, err.message);
        await sleep(delay);
      }
    }
  }
  throw lastError;
}
