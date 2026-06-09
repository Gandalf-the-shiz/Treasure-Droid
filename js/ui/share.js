/**
 * js/ui/share.js
 * Social sharing functionality — Phase 6.
 *
 * Provides share buttons for individual stock predictions:
 *   - Twitter/X: pre-filled tweet with symbol, direction, confidence and app URL
 *   - Copy to clipboard: copies a shareable text snippet
 *
 * Accessible via a "Share" button rendered in the stock detail overlay.
 *
 * Dependencies: js/utils/helpers.js (showToast)
 */

import { showToast } from '../utils/helpers.js';

/** Canonical app URL used in share text. Falls back to current page origin. */
const APP_URL = (typeof window !== 'undefined' && window.location?.origin)
  ? window.location.origin + window.location.pathname.replace(/\/[^/]*$/, '/')
  : 'https://gandalf-the-shiz.github.io/Nostradamus/';

// ─── Public API ───────────────────────────────────────────────

/**
 * Build and return a share button row element for a prediction.
 * The row contains a Twitter/X share button and a clipboard copy button.
 *
 * @param {string} symbol
 * @param {{ direction: 'UP'|'DOWN', delta: number, confidence: number, predictedPrice?: number }} prediction
 * @returns {HTMLElement}
 */
export function buildShareButtons(symbol, prediction) {
  const shareText = _buildShareText(symbol, prediction);
  const twitterUrl = _buildTwitterUrl(shareText);

  const wrapper = document.createElement('div');
  wrapper.className = 'share-buttons';

  // Twitter/X button
  const twitterBtn = document.createElement('a');
  twitterBtn.className = 'share-btn share-btn--twitter';
  twitterBtn.href = twitterUrl;
  twitterBtn.target = '_blank';
  twitterBtn.rel = 'noopener noreferrer';
  twitterBtn.setAttribute('aria-label', 'Share prediction on Twitter/X');
  twitterBtn.innerHTML = '𝕏 Share on X';

  // Copy to clipboard button
  const copyBtn = document.createElement('button');
  copyBtn.className = 'share-btn share-btn--copy';
  copyBtn.setAttribute('aria-label', 'Copy prediction to clipboard');
  copyBtn.innerHTML = '📋 Copy';
  copyBtn.addEventListener('click', async () => {
    const copied = await _copyToClipboard(shareText);
    if (copied) {
      showToast('Prediction copied to clipboard! 📋', 'success');
      copyBtn.textContent = '✓ Copied';
      setTimeout(() => { copyBtn.innerHTML = '📋 Copy'; }, 2000);
    } else {
      showToast('Could not copy to clipboard.', 'error');
    }
  });

  wrapper.appendChild(twitterBtn);
  wrapper.appendChild(copyBtn);

  return wrapper;
}

/**
 * Programmatically share a prediction. Tries the Web Share API first
 * (mobile-native), then falls back to buildShareButtons.
 *
 * @param {string} symbol
 * @param {Object} prediction
 * @returns {Promise<boolean>}  true if native share was invoked
 */
export async function shareNative(symbol, prediction) {
  if (navigator.share) {
    try {
      await navigator.share({
        title: `${symbol} Prediction — Nostradamus`,
        text:  _buildShareText(symbol, prediction),
        url:   APP_URL,
      });
      return true;
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.warn('[Share] navigator.share failed:', err.message);
      }
    }
  }
  return false;
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * Build the plain-text share string for a prediction.
 *
 * @param {string} symbol
 * @param {{ direction: string, delta: number, confidence: number, predictedPrice?: number }} prediction
 * @returns {string}
 */
function _buildShareText(symbol, prediction) {
  const arrow     = prediction.direction === 'UP' ? '▲' : '▼';
  const deltaStr  = prediction.delta != null ? `$${Math.abs(prediction.delta).toFixed(2)}` : '';
  const confStr   = prediction.confidence != null ? ` (${Math.round(prediction.confidence * 100)}% confidence)` : '';
  return `🔮 Nostradamus AI predicts $${symbol} will go ${arrow} ${prediction.direction} by ${deltaStr}${confStr}. Check it out: ${APP_URL}`;
}

/**
 * Build a Twitter/X intent URL for a given text.
 *
 * @param {string} text
 * @returns {string}
 */
function _buildTwitterUrl(text) {
  const params = new URLSearchParams({ text });
  return `https://twitter.com/intent/tweet?${params.toString()}`;
}

/**
 * Copy text to the clipboard. Returns true on success.
 *
 * @param {string} text
 * @returns {Promise<boolean>}
 */
async function _copyToClipboard(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    // Fallback for older browsers
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.top = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
