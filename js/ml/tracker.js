/**
 * js/ml/tracker.js
 * Prediction tracking system — Phase 5.
 *
 * Stores every prediction the model makes with timestamps, symbol,
 * direction (UP/DOWN), probability, predicted price, and actual price
 * at prediction time. Predictions are persisted in localStorage.
 *
 * Predictions are resolved at T+1: only when actual close price for the
 * PREDICTED DATE (next trading day) is available. This prevents premature
 * resolution from intraday price updates.
 *
 * localStorage key (via cache.js): 'predictions' → 'nostradamus_predictions'
 */

import { getItem, setItem } from '../storage/cache.js';

const PREDICTIONS_KEY = 'predictions';
const MAX_STORED = 500; // keep last N predictions to avoid unbounded growth

/**
 * @typedef {Object} TrackedPrediction
 * @property {string}  id             - Unique identifier
 * @property {string}  symbol
 * @property {'UP'|'DOWN'} direction
 * @property {number}  probability    - Raw P(UP) from model
 * @property {number}  delta          - Estimated dollar change magnitude
 * @property {number}  predictedPrice
 * @property {number}  currentPrice   - Price at the time of prediction
 * @property {number}  confidence     - 0..1
 * @property {number}  generatedAt    - Unix ms timestamp
 * @property {string}  predictionDate - YYYY-MM-DD: the trading day this prediction is FOR
 * @property {boolean} isDemo         - Was this a demo (no real model)?
 * @property {number|null}  actualPrice    - Filled when resolved
 * @property {'UP'|'DOWN'|null} actualDirection - UP/DOWN relative to currentPrice
 * @property {boolean|null} isCorrect  - Was the direction call correct?
 * @property {number|null}  priceError - |predictedPrice - actualPrice|
 * @property {number|null}  resolvedAt - Unix ms timestamp when resolved
 */

/**
 * Return the next trading day (skipping Saturday and Sunday) after a given date.
 * @param {Date} [date=new Date()]
 * @returns {string}  YYYY-MM-DD
 */
export function getNextTradingDay(date = new Date()) {
  const next = new Date(date);
  next.setDate(next.getDate() + 1);
  // Skip weekends: 6 = Saturday, 0 = Sunday
  while (next.getDay() === 6 || next.getDay() === 0) {
    next.setDate(next.getDate() + 1);
  }
  return next.toISOString().slice(0, 10);
}

/**
 * Load all tracked predictions from localStorage.
 * @returns {TrackedPrediction[]}
 */
function _load() {
  const stored = getItem(PREDICTIONS_KEY);
  return Array.isArray(stored) ? stored : [];
}

/**
 * Persist predictions array to localStorage.
 * Trims to MAX_STORED (most recent first) to avoid quota exhaustion.
 * @param {TrackedPrediction[]} predictions
 */
function _save(predictions) {
  const trimmed = predictions.slice(-MAX_STORED);
  setItem(PREDICTIONS_KEY, trimmed);
}

/**
 * Store a new prediction.
 * Automatically sets predictionDate = next trading day from today.
 * Returns the assigned unique ID.
 *
 * @param {import('./prediction.js').Prediction} prediction
 * @returns {string}  The ID of the stored prediction
 */
export function storePrediction(prediction) {
  const predictions = _load();

  const id = `pred_${prediction.generatedAt}_${Math.random().toString(36).slice(2, 7)}`;
  const predictionDate = getNextTradingDay(new Date(prediction.generatedAt));

  const entry = {
    id,
    symbol:         prediction.symbol,
    direction:      prediction.direction,
    probability:    prediction.probability ?? null,
    delta:          prediction.delta,
    predictedPrice: prediction.predictedPrice,
    currentPrice:   prediction.currentPrice,
    confidence:     prediction.confidence ?? null,
    generatedAt:    prediction.generatedAt,
    predictionDate,
    isDemo:         prediction.isDemo ?? false,
    // resolved fields — null until actual prices arrive for predictionDate
    actualPrice:    null,
    actualDirection: null,
    isCorrect:      null,
    priceError:     null,
    resolvedAt:     null,
  };

  predictions.push(entry);
  _save(predictions);
  return id;
}

/**
 * Return all tracked predictions, optionally filtered by symbol.
 * @param {string} [symbol]
 * @returns {TrackedPrediction[]}
 */
export function getPredictions(symbol) {
  const all = _load();
  if (!symbol) return all;
  return all.filter(p => p.symbol === symbol.toUpperCase());
}

/**
 * Return all tracked predictions for a given symbol, sorted by generatedAt ascending.
 * Useful for rendering historical prediction overlays on charts.
 *
 * @param {string} symbol
 * @returns {TrackedPrediction[]}
 */
export function getPredictionsBySymbol(symbol) {
  return getPredictions(symbol).sort((a, b) => a.generatedAt - b.generatedAt);
}

/**
 * Return only predictions that have not yet been resolved
 * (i.e., actualPrice is still null).
 * @param {string} [symbol]
 * @returns {TrackedPrediction[]}
 */
export function getPendingPredictions(symbol) {
  return getPredictions(symbol).filter(p => p.resolvedAt === null);
}

/**
 * Resolve a single prediction by its ID.
 * Fills in actualPrice, actualDirection, isCorrect, priceError, resolvedAt.
 *
 * @param {string} id
 * @param {number} actualPrice  - Actual close price for the predictionDate
 * @returns {boolean}  true if found and updated, false otherwise
 */
export function resolvePrediction(id, actualPrice) {
  const predictions = _load();
  const idx = predictions.findIndex(p => p.id === id);
  if (idx === -1) return false;

  const p = predictions[idx];
  const actualDirection = actualPrice >= p.currentPrice ? 'UP' : 'DOWN';

  predictions[idx] = {
    ...p,
    actualPrice:      parseFloat(actualPrice.toFixed(2)),
    actualDirection,
    isCorrect:        p.direction === actualDirection,
    priceError:       parseFloat(Math.abs(p.predictedPrice - actualPrice).toFixed(2)),
    resolvedAt:       Date.now(),
  };

  _save(predictions);
  return true;
}

/**
 * Resolve pending predictions whose predictionDate matches a date in the price map.
 * Predictions are only resolved when actual close price for the SPECIFIC predicted
 * date is available — not for any arbitrary price update.
 *
 * Backward compatibility: predictions created before this version (without a
 * predictionDate field) are resolved using the old behaviour (any matching price).
 *
 * @param {Object.<string, number>} symbolPriceMap  - e.g. { AAPL: 182.50, TSLA: 245.10 }
 * @param {string} [priceDate]  - YYYY-MM-DD date that the prices in symbolPriceMap correspond to.
 *                                Defaults to today's date in local time.
 * @returns {number}  Count of predictions resolved
 */
export function resolveAll(symbolPriceMap, priceDate) {
  const today = priceDate ?? new Date().toISOString().slice(0, 10);
  const predictions = _load();
  let resolvedCount = 0;

  const updated = predictions.map(p => {
    if (p.resolvedAt !== null) return p;              // already resolved
    // T+1 date check: skip if this prediction has a predictionDate that doesn't match today.
    // Legacy predictions (created before this version) have no predictionDate and are
    // resolved with the old behaviour (any matching price).
    if (p.predictionDate && p.predictionDate !== today) return p; // wrong date
    const actualPrice = symbolPriceMap[p.symbol];
    if (actualPrice == null) return p;                // no price for this symbol

    const actualDirection = actualPrice >= p.currentPrice ? 'UP' : 'DOWN';
    resolvedCount++;
    return {
      ...p,
      actualPrice:      parseFloat(actualPrice.toFixed(2)),
      actualDirection,
      isCorrect:        p.direction === actualDirection,
      priceError:       parseFloat(Math.abs(p.predictedPrice - actualPrice).toFixed(2)),
      resolvedAt:       Date.now(),
    };
  });

  if (resolvedCount > 0) _save(updated);
  return resolvedCount;
}

/**
 * Remove all stored predictions (e.g., from the Settings clear action).
 */
export function clearPredictions() {
  setItem(PREDICTIONS_KEY, []);
}
