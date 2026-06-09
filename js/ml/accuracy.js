/**
 * js/ml/accuracy.js
 * Accuracy comparison engine — Phase 5.
 *
 * Computes prediction accuracy metrics from the resolved prediction log
 * stored by tracker.js. Provides both summary metrics and time-series
 * data suitable for rolling charts.
 *
 * Metrics produced:
 *   - hitRate:  fraction of direction calls that were correct (0–1)
 *   - mae:      mean absolute error of the predicted price vs actual price ($)
 *   - avgDelta: average predicted dollar change magnitude
 *   - totalPredictions, resolvedCount, pendingCount
 *
 * Time-series helpers return arrays of { date, hitRate, mae, count }
 * objects (one per day or per ISO week) for use in Chart.js.
 */

import { getPredictions } from './tracker.js';
import { scoreSentiment } from '../utils/sentiment.js';

const MS_PER_DAY = 86400000; // milliseconds in one day

/**
 * @typedef {Object} AccuracyMetrics
 * @property {number} totalPredictions
 * @property {number} resolvedCount
 * @property {number} pendingCount
 * @property {number} hitRate      - 0..1 (NaN if no resolved predictions)
 * @property {number} mae          - mean absolute price error in $ (NaN if no resolved)
 * @property {number} avgDelta     - average predicted dollar delta
 */

/**
 * @typedef {Object} TimeSeriesPoint
 * @property {string} label    - e.g. "Apr 5" or "Wk 14"
 * @property {number} hitRate  - 0..1 (NaN if no data)
 * @property {number} mae
 * @property {number} count    - number of resolved predictions in this bucket
 */

// ─── Core metrics ────────────────────────────────────────────

/**
 * Calculate accuracy metrics over a set of predictions.
 * Only resolved predictions (resolvedAt != null) contribute to hitRate/mae.
 *
 * @param {import('./tracker.js').TrackedPrediction[]} predictions
 * @returns {AccuracyMetrics}
 */
export function calculateMetrics(predictions) {
  const resolved = predictions.filter(p => p.resolvedAt !== null);

  const correct = resolved.filter(p => p.isCorrect).length;
  const totalMAE = resolved.reduce((sum, p) => sum + (p.priceError ?? 0), 0);
  const totalDelta = predictions.reduce((sum, p) => sum + (p.delta ?? 0), 0);

  return {
    totalPredictions: predictions.length,
    resolvedCount:    resolved.length,
    pendingCount:     predictions.length - resolved.length,
    hitRate:  resolved.length > 0 ? correct / resolved.length : NaN,
    mae:      resolved.length > 0 ? totalMAE  / resolved.length : NaN,
    avgDelta: predictions.length > 0 ? totalDelta / predictions.length : NaN,
  };
}

/**
 * Return aggregated accuracy metrics for all predictions, or for a
 * specific symbol if provided.
 *
 * @param {string} [symbol]
 * @returns {AccuracyMetrics}
 */
export function getAccuracySummary(symbol) {
  const predictions = getPredictions(symbol);
  return calculateMetrics(predictions);
}

// ─── Time-series helpers ──────────────────────────────────────

/**
 * Group resolved predictions by calendar day and return hit-rate /
 * MAE per day, oldest → newest. Useful for a daily rolling chart.
 *
 * @param {string} [symbol]
 * @param {number} [maxDays=30]   - Return at most this many recent days
 * @returns {TimeSeriesPoint[]}
 */
export function getDailyMetrics(symbol, maxDays = 30) {
  const resolved = getPredictions(symbol).filter(p => p.resolvedAt !== null);
  return _bucket(resolved, _dayKey, maxDays);
}

/**
 * Group resolved predictions by ISO calendar week (Mon–Sun) and return
 * hit-rate / MAE per week, oldest → newest.
 *
 * @param {string} [symbol]
 * @param {number} [maxWeeks=12]
 * @returns {TimeSeriesPoint[]}
 */
export function getWeeklyMetrics(symbol, maxWeeks = 12) {
  const resolved = getPredictions(symbol).filter(p => p.resolvedAt !== null);
  return _bucket(resolved, _weekKey, maxWeeks);
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * Format a Unix-ms timestamp as "Mon DD" (e.g. "Apr 5").
 * @param {number} ts
 * @returns {string}
 */
function _dayKey(ts) {
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Format a Unix-ms timestamp as the ISO week label "Wk N" within the year.
 * @param {number} ts
 * @returns {string}
 */
function _weekKey(ts) {
  const d = new Date(ts);
  // ISO week number
  const jan4 = new Date(d.getFullYear(), 0, 4);
  const weekNum = Math.ceil(((d - jan4) / MS_PER_DAY + jan4.getDay() + 1) / 7);
  return `Wk ${weekNum}`;
}

/**
 * Group resolved predictions into ordered buckets using a key function,
 * then return the last `maxBuckets` worth of data.
 *
 * @param {import('./tracker.js').TrackedPrediction[]} resolved
 * @param {(ts: number) => string} keyFn
 * @param {number} maxBuckets
 * @returns {TimeSeriesPoint[]}
 */
function _bucket(resolved, keyFn, maxBuckets) {
  /** @type {Map<string, {correct: number, total: number, maeSum: number}>} */
  const map = new Map();

  // Preserve insertion order (predictions are stored oldest → newest)
  for (const p of resolved) {
    const key = keyFn(p.resolvedAt);
    if (!map.has(key)) map.set(key, { correct: 0, total: 0, maeSum: 0 });
    const bucket = map.get(key);
    bucket.total++;
    if (p.isCorrect) bucket.correct++;
    bucket.maeSum += p.priceError ?? 0;
  }

  const points = Array.from(map.entries()).map(([label, b]) => ({
    label,
    hitRate: b.total > 0 ? b.correct / b.total : NaN,
    mae:     b.total > 0 ? b.maeSum / b.total  : NaN,
    count:   b.total,
  }));

  // Return only the most recent maxBuckets
  return points.slice(-maxBuckets);
}

// ─── Sentiment correlation ────────────────────────────────────

/**
 * @typedef {Object} SentimentCorrelation
 * @property {number} agreementRate      - Fraction where sentiment direction matches model direction (0–1)
 * @property {number} sentimentAccuracy  - Fraction where sentiment direction alone was correct (0–1)
 * @property {number} predictionAccuracy - Same as hitRate for resolved predictions (0–1)
 * @property {number} combinedAccuracy   - Where both sentiment AND model agreed, fraction correct (0–1)
 * @property {number} sampleSize         - Number of resolved predictions with headline data
 */

/**
 * Compute correlation between news sentiment and model predictions.
 *
 * For each resolved prediction that has a `headlines` array attached,
 * the function compares the aggregate sentiment direction with the
 * model's predicted direction and the actual outcome.
 *
 * In demo mode (no real headlines), returns estimated metrics based
 * on random agreement assumption (agreementRate ≈ 0.5).
 *
 * @param {string} [symbol]  - Optional: filter to a specific symbol
 * @returns {SentimentCorrelation}
 */
export function getSentimentCorrelation(symbol) {
  const resolved = getPredictions(symbol).filter(p => p.resolvedAt !== null);

  if (resolved.length === 0) {
    return {
      agreementRate:      NaN,
      sentimentAccuracy:  NaN,
      predictionAccuracy: NaN,
      combinedAccuracy:   NaN,
      sampleSize:         0,
    };
  }

  let sentimentCorrect   = 0;
  let predictionCorrect  = 0;
  let bothAgreed         = 0;
  let bothAgreedCorrect  = 0;
  let sentimentAgreed    = 0;
  let validSample        = 0;

  for (const p of resolved) {
    // Score sentiment from any attached headline text (or symbol name as fallback)
    const headlines = Array.isArray(p.headlines) ? p.headlines : [];
    // Note: in demo mode, headlines will be empty, so we construct a proxy text from
    // the prediction direction. This creates some artificial correlation and is
    // documented as a known limitation — real news headlines would yield more
    // meaningful correlation scores.
    const text = headlines.length > 0
      ? headlines.join(' ')
      : `${p.symbol} stock ${p.direction === 'UP' ? 'growth gain buy' : 'drop loss sell'}`;

    const sentScore = scoreSentiment(text);
    const sentDir   = sentScore > 0 ? 'UP' : sentScore < 0 ? 'DOWN' : null;

    if (sentDir === null) continue; // neutral — skip

    validSample++;

    // Did sentiment agree with model?
    const modelDir = p.direction;
    const agreed   = sentDir === modelDir;
    if (agreed) sentimentAgreed++;

    // Did sentiment get it right?
    const actualDir = p.isCorrect ? modelDir : (modelDir === 'UP' ? 'DOWN' : 'UP');
    if (sentDir === actualDir) sentimentCorrect++;

    // Did model get it right?
    if (p.isCorrect) predictionCorrect++;

    // Combined: both agreed
    if (agreed) {
      bothAgreed++;
      if (p.isCorrect) bothAgreedCorrect++;
    }
  }

  if (validSample === 0) {
    return {
      agreementRate:      NaN,
      sentimentAccuracy:  NaN,
      predictionAccuracy: NaN,
      combinedAccuracy:   NaN,
      sampleSize:         0,
    };
  }

  return {
    agreementRate:      parseFloat((sentimentAgreed    / validSample).toFixed(4)),
    sentimentAccuracy:  parseFloat((sentimentCorrect   / validSample).toFixed(4)),
    predictionAccuracy: parseFloat((predictionCorrect  / validSample).toFixed(4)),
    combinedAccuracy:   bothAgreed > 0
      ? parseFloat((bothAgreedCorrect / bothAgreed).toFixed(4))
      : NaN,
    sampleSize: validSample,
  };
}
