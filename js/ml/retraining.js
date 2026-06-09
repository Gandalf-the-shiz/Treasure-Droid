/**
 * js/ml/retraining.js
 * Automatic model retraining trigger — Phase 5.
 *
 * When fresh price data is loaded (new daily candles for any symbol),
 * this module decides whether a retraining cycle should be kicked off.
 *
 * Trigger conditions:
 *   1. At least MIN_CANDLES_FOR_TRAINING new candles since last training.
 *   2. At least MIN_RETRAIN_INTERVAL_MS has elapsed since the last training.
 *
 * Retraining runs in the background via scheduledTrain() so it never
 * blocks the UI.  After training completes a new model version is
 * recorded and compared against the current champion (A/B promotion).
 *
 * localStorage key (via cache.js): 'last_training' → 'nostradamus_last_training'
 */

import { getItem, setItem } from '../storage/cache.js';
import { scheduledTrain }   from './training.js';
import { getAccuracySummary } from './accuracy.js';
import { createModelVersion, compareAndPromote } from './versioning.js';

const LAST_TRAINING_KEY       = 'last_training';
const MIN_RETRAIN_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24 hours
const MIN_CANDLES_FOR_TRAINING = 40; // need enough data for meaningful training

/**
 * @typedef {Object} TrainingInfo
 * @property {number|null} lastTrainedAt  - Unix ms, or null if never trained
 * @property {number}      candleCount    - Number of candles used in last training
 * @property {string|null} versionId      - Most recent model version id
 */

/**
 * Retrieve information about the most recent training run.
 * @returns {TrainingInfo}
 */
export function getLastTrainingInfo() {
  const stored = getItem(LAST_TRAINING_KEY);
  return {
    lastTrainedAt: stored?.lastTrainedAt ?? null,
    candleCount:   stored?.candleCount   ?? 0,
    versionId:     stored?.versionId     ?? null,
  };
}

/**
 * Persist information about a completed training run.
 * @param {{ lastTrainedAt: number, candleCount: number, versionId: string }} info
 */
function _setLastTrainingInfo(info) {
  setItem(LAST_TRAINING_KEY, info);
}

/**
 * Determine whether a new retraining run is warranted given the current
 * candle data.
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles
 * @returns {boolean}
 */
export function shouldRetrain(candles) {
  if (!Array.isArray(candles) || candles.length < MIN_CANDLES_FOR_TRAINING) {
    return false;
  }

  const { lastTrainedAt, candleCount } = getLastTrainingInfo();

  // Never trained before → train now
  if (!lastTrainedAt) return true;

  const elapsed = Date.now() - lastTrainedAt;
  if (elapsed < MIN_RETRAIN_INTERVAL_MS) return false;

  // Retrain if we have meaningfully more data than last time
  const newCandleCount = candles.length;
  if (newCandleCount <= candleCount) return false;

  return true;
}

/**
 * Trigger a background retraining cycle if shouldRetrain() returns true.
 *
 * After training finishes:
 *  1. A new model version is recorded with current training metrics.
 *  2. The new version is compared against the champion (A/B promotion).
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles  - Full candle history
 * @param {(progress: import('./training.js').TrainingProgress) => void} [onProgress]
 * @returns {Promise<void>}  Resolves when training and version recording complete
 */
export async function autoRetrain(candles, onProgress) {
  if (!shouldRetrain(candles)) {
    console.log('[Retraining] No retraining needed at this time.');
    return;
  }

  console.log('[Retraining] Triggering background retraining…');

  let finalLoss    = 0;
  let finalValLoss = 0;

  const wrappedProgress = (progress) => {
    finalLoss    = progress.loss;
    finalValLoss = progress.valLoss;
    if (onProgress) onProgress(progress);
  };

  const candleCount = candles.length;

  // Await training completion before recording the version
  const model = await scheduledTrain(candles, wrappedProgress);

  const accuracySnapshot = getAccuracySummary();
  const version = createModelVersion({
    trainLoss:  finalLoss,
    valLoss:    finalValLoss,
    accuracy: {
      hitRate:       accuracySnapshot.hitRate,
      mae:           accuracySnapshot.mae,
      resolvedCount: accuracySnapshot.resolvedCount,
    },
  });

  _setLastTrainingInfo({
    lastTrainedAt: Date.now(),
    candleCount,
    versionId: version.id,
  });

  compareAndPromote(version.id);
  console.log(`[Retraining] Recorded model version ${version.versionNumber}`);
  return model;
}
