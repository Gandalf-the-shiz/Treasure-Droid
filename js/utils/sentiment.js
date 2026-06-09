/**
 * js/utils/sentiment.js
 * Reusable sentiment scoring utility.
 *
 * Provides a keyword-based sentiment scorer that returns a numeric score
 * in the range [-1, +1] for a given headline or text string.
 * Extracted and enhanced from js/ui/news.js for reuse across the codebase.
 *
 * In the future this score can be integrated as an additional ML feature
 * alongside price/volume technicals.
 */

// ─── Sentiment Lexicon ────────────────────────────────────────

/**
 * @typedef {Object} LexiconEntry
 * @property {number} weight  - Positive or negative weight for this word
 */

/** Words and their positive sentiment weights (+0.1 to +1.0). */
const POSITIVE_LEXICON = {
  // Strong positives
  'surge': 0.8, 'surges': 0.8, 'soar': 0.8, 'soars': 0.8,
  'record': 0.7, 'breakthrough': 0.8, 'outperform': 0.7,
  'beat': 0.6, 'beats': 0.6, 'exceeds': 0.6, 'exceed': 0.6,
  // Moderate positives
  'growth': 0.5, 'profit': 0.5, 'profits': 0.5, 'gain': 0.5, 'gains': 0.5,
  'upgrade': 0.5, 'buy': 0.4, 'strong': 0.5, 'rally': 0.6,
  'bullish': 0.6, 'positive': 0.4, 'innovative': 0.5,
  'partnership': 0.4, 'deal': 0.3, 'acquire': 0.3,
  'launch': 0.3, 'expand': 0.4, 'expansion': 0.4,
  // Mild positives
  'rise': 0.3, 'rises': 0.3, 'up': 0.2, 'win': 0.4, 'wins': 0.4,
  'boost': 0.4, 'accelerate': 0.4, 'accelerates': 0.4,
  'approve': 0.4, 'approved': 0.4, 'recovery': 0.4,
};

/** Words and their negative sentiment weights (-0.1 to -1.0). */
const NEGATIVE_LEXICON = {
  // Strong negatives
  'crash': -0.8, 'fraud': -0.9, 'scandal': -0.9, 'default': -0.8,
  'bankruptcy': -0.9, 'bankrupt': -0.9, 'collapse': -0.8,
  // Moderate negatives
  'fall': -0.5, 'falls': -0.5, 'drop': -0.5, 'drops': -0.5,
  'miss': -0.5, 'misses': -0.5, 'loss': -0.5, 'losses': -0.5,
  'decline': -0.5, 'declines': -0.5, 'cut': -0.4,
  'downgrade': -0.6, 'sell': -0.4, 'underperform': -0.6,
  'weak': -0.4, 'bearish': -0.6, 'negative': -0.4,
  'lawsuit': -0.5, 'fine': -0.4, 'probe': -0.4,
  'investigation': -0.5, 'recall': -0.5,
  // Mild negatives
  'down': -0.3, 'concern': -0.3, 'risk': -0.3, 'risks': -0.3,
  'warning': -0.4, 'layoff': -0.5, 'layoffs': -0.5,
  'miss': -0.5, 'disappoint': -0.5, 'disappoints': -0.5,
  'disappointing': -0.5, 'disappointed': -0.5,
};

/**
 * Negation words that flip the sentiment of the following phrase.
 * Simple one-word look-behind; handles "not great" → negative, etc.
 */
const NEGATIONS = new Set(['not', 'no', "n't", 'never', 'barely', 'hardly', 'without']);

// ─── Scorer ───────────────────────────────────────────────────

/**
 * Score a text string for financial sentiment.
 *
 * Algorithm:
 *  1. Tokenise into lower-case words.
 *  2. For each token, look up weight in positive/negative lexicons.
 *  3. If the preceding token was a negation, flip the weight sign.
 *  4. Sum all weights, then tanh-compress to keep the result in [-1, +1].
 *
 * @param {string} text  - Headline or body text to score
 * @returns {number}  Sentiment score in [-1, +1]
 *   Positive values indicate bullish sentiment; negative values bearish.
 *   Zero means neutral or insufficient signal.
 */
export function scoreSentiment(text) {
  if (!text || typeof text !== 'string') return 0;

  const tokens = text.toLowerCase().replace(/[^\w\s']/g, ' ').split(/\s+/).filter(Boolean);
  let total = 0;

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    let weight = (POSITIVE_LEXICON[token] ?? 0) + (NEGATIVE_LEXICON[token] ?? 0);
    if (weight !== 0 && i > 0 && NEGATIONS.has(tokens[i - 1])) {
      weight = -weight;
    }
    total += weight;
  }

  // tanh compresses unbounded sum to (-1, +1) — similar to how many NLP
  // libraries normalise polarity scores.
  return parseFloat(Math.tanh(total).toFixed(4));
}

/**
 * Classify a numeric score into a human-readable sentiment label.
 * @param {number} score  - Value from scoreSentiment(), in [-1, +1]
 * @returns {'positive'|'neutral'|'negative'}
 */
export function classifySentiment(score) {
  if (score > 0.15)  return 'positive';
  if (score < -0.15) return 'negative';
  return 'neutral';
}

/**
 * Aggregate sentiment scores from multiple headlines.
 * Returns the weighted mean (more extreme scores get higher weight).
 *
 * @param {string[]} headlines
 * @returns {{ score: number, label: 'positive'|'neutral'|'negative', count: number }}
 */
export function aggregateSentiment(headlines) {
  if (!Array.isArray(headlines) || headlines.length === 0) {
    return { score: 0, label: 'neutral', count: 0 };
  }

  const scores = headlines.map(h => scoreSentiment(h));
  const sum = scores.reduce((s, v) => s + v, 0);
  const score = parseFloat((sum / scores.length).toFixed(4));

  return {
    score,
    label: classifySentiment(score),
    count: headlines.length,
  };
}
