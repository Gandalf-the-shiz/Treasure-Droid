/**
 * js/ui/news.js
 * News sentiment display component.
 *
 * Fetches recent company news from the local Nostradamus server (Yahoo RSS)
 * with an optional Finnhub fallback, and renders it with a simple
 * keyword-based sentiment score (positive / neutral / negative).
 * If no news is available, displays an empty state — never falls back to
 * fabricated/demo articles.
 *
 * Dependencies: js/api/manager.js, js/utils/helpers.js
 */

import { getNews } from '../api/manager.js';
import { daysAgoISO, todayISO, escapeHtml } from '../utils/helpers.js';

// ─── Sentiment keywords ───────────────────────────────────────

/** Words that shift sentiment score positively. */
const POSITIVE_WORDS = [
  'surge', 'surges', 'soar', 'soars', 'beat', 'beats', 'record', 'growth',
  'gain', 'gains', 'profit', 'profits', 'upgrade', 'buy', 'outperform',
  'strong', 'rally', 'boost', 'win', 'wins', 'up', 'rise', 'rises',
  'bullish', 'positive', 'exceeds', 'exceed', 'innovative', 'breakthrough',
  'partnership', 'deal', 'acquire', 'launch', 'expand', 'expansion',
];

/** Words that shift sentiment score negatively. */
const NEGATIVE_WORDS = [
  'fall', 'falls', 'drop', 'drops', 'miss', 'misses', 'loss', 'losses',
  'decline', 'declines', 'cut', 'downgrade', 'sell', 'underperform',
  'weak', 'down', 'crash', 'concern', 'risk', 'risks', 'warning',
  'bearish', 'negative', 'lawsuit', 'fine', 'probe', 'investigation',
  'layoff', 'layoffs', 'recall', 'fraud', 'scandal', 'default',
];

// ─── Public API ───────────────────────────────────────────────

/**
 * Fetch and render news for a symbol into the given container.
 * Falls back to demo news when the API key is absent.
 *
 * @param {HTMLElement} container
 * @param {string}      symbol
 * @param {{ mode: 'demo'|'live' }} appState
 * @returns {Promise<void>}
 */
export async function renderNewsPanel(container, symbol, appState) {
  container.innerHTML = '<div class="news-loading">Loading news…</div>';

  let articles = [];
  let fromLocal = false;

  // Prefer the local Nostradamus server (Yahoo RSS + FinBERT cache).
  try {
    articles = await _fetchLocalNews(symbol);
    fromLocal = articles.length > 0;
  } catch { /* fall through */ }

  if (!fromLocal) {
    try {
      const from = daysAgoISO(7);
      const to   = todayISO();
      articles = await getNews(symbol, from, to);
    } catch (err) {
      console.warn('[News] API fetch failed:', err.message);
      articles = [];
    }
  }

  container.innerHTML = '';
  _renderArticles(container, articles || [], symbol);
}

/**
 * Score a text snippet and return a sentiment label.
 *
 * @param {string} text
 * @returns {'positive'|'negative'|'neutral'}
 */
export function scoreSentiment(text) {
  if (!text) return 'neutral';
  const lower = text.toLowerCase();
  const words = lower.split(/\W+/);
  let score = 0;
  for (const word of words) {
    if (POSITIVE_WORDS.includes(word)) score++;
    if (NEGATIVE_WORDS.includes(word)) score--;
  }
  if (score > 0) return 'positive';
  if (score < 0) return 'negative';
  return 'neutral';
}

/**
 * Fetch news headlines for a symbol as plain strings (for sentiment scoring).
 * Returns up to 5 headlines. Gracefully falls back to demo data.
 *
 * @param {string} symbol
 * @param {{ mode: 'demo'|'live' }} appState
 * @returns {Promise<string[]>}
 */
export async function fetchNewsHeadlines(symbol, appState) {
  let articles = [];
  try {
    articles = await _fetchLocalNews(symbol);
  } catch { /* fall through */ }
  if (!articles.length) {
    try {
      const from = daysAgoISO(7);
      const to   = todayISO();
      articles = await getNews(symbol, from, to);
    } catch {
      articles = [];
    }
  }
  return (articles || []).map(a => a.headline || a.summary || '').filter(Boolean);
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * Fetch news from the local Nostradamus server's /api/news endpoint.
 * Returns articles in the canonical Finnhub shape or [] if unavailable.
 * @param {string} symbol
 * @returns {Promise<Array>}
 */
async function _fetchLocalNews(symbol) {
  const r = await fetch(`/api/news?symbol=${encodeURIComponent(symbol)}&max_headlines=8`, { cache: 'no-cache' });
  if (!r.ok) return [];
  const payload = await r.json();
  const headlines = payload?.headlines || [];
  return headlines
    .filter(h => h && h.url && /^https?:\/\//i.test(h.url))
    .map(h => {
      const published = h.published ? Date.parse(h.published) : NaN;
      return {
        headline: h.title || '',
        summary:  '',
        url:      h.url,
        datetime: Number.isFinite(published) ? published / 1000 : (Date.now() / 1000),
        source:   'Yahoo Finance',
      };
    });
}

/**
 * Render a list of articles into the container.
 * @param {HTMLElement} container
 * @param {Array}       articles
 * @param {string}      symbol
 */
function _renderArticles(container, articles, symbol) {
  // Filter out anything without a real http(s) link.
  const usable = (articles || []).filter(a => a && typeof a.url === 'string' && /^https?:\/\//i.test(a.url));

  if (usable.length === 0) {
    container.innerHTML = '<p class="news-empty">No recent news available for ' + escapeHtml(symbol) + '.</p>';
    return;
  }

  const list = document.createElement('div');
  list.className = 'news-list';

  for (const article of usable) {
    const sentiment = scoreSentiment(`${article.headline} ${article.summary}`);
    const sentimentLabel = { positive: '😊 Positive', negative: '😟 Negative', neutral: '😐 Neutral' }[sentiment];
    const date = article.datetime
      ? new Date(article.datetime * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '';

    const item = document.createElement('div');
    item.className = `news-item news-item--${sentiment}`;
    item.innerHTML = `
      <div class="news-item__meta">
        <span class="news-item__sentiment news-item__sentiment--${sentiment}">${sentimentLabel}</span>
        <span class="news-item__date">${escapeHtml(date)}</span>
        <span class="news-item__source">${escapeHtml(article.source || '')}</span>
      </div>
      <a class="news-item__headline" href="${escapeHtml(article.url)}" target="_blank" rel="noopener noreferrer">
        ${escapeHtml(article.headline || 'No headline')}
      </a>
      ${article.summary ? `<p class="news-item__summary">${escapeHtml(article.summary)}</p>` : ''}
    `;
    list.appendChild(item);
  }

  container.appendChild(list);
}

