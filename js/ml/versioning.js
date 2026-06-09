/**
 * js/ml/versioning.js
 * Model versioning & A/B comparison — Phase 5.
 *
 * Every time the model is retrained a new version record is created in
 * localStorage.  Each record captures the training metrics (loss, val_loss)
 * and the prediction-accuracy snapshot at that point in time.
 *
 * A/B comparison:
 *   - One version is designated the "champion" (best hitRate so far).
 *   - When a candidate is evaluated, compareAndPromote() checks whether it
 *     beats the current champion on hitRate (tie-break: lower MAE).
 *   - If it does, the candidate is promoted and the old champion demoted.
 *
 * localStorage key (via cache.js): 'model_versions' → 'nostradamus_model_versions'
 */

import { getItem, setItem } from '../storage/cache.js';

const VERSIONS_KEY = 'model_versions';
const MAX_VERSIONS = 20; // keep rolling window of recent versions
/** Minimum number of resolved predictions required to make a meaningful A/B comparison. */
const MIN_RESOLVED_FOR_PROMOTION = 5;

/**
 * @typedef {Object} ModelVersion
 * @property {string}  id
 * @property {number}  versionNumber
 * @property {number}  trainedAt      - Unix ms timestamp
 * @property {number}  trainLoss      - Final training loss
 * @property {number}  valLoss        - Final validation loss
 * @property {Object}  accuracy       - Snapshot of AccuracyMetrics at promotion time
 * @property {number}  accuracy.hitRate
 * @property {number}  accuracy.mae
 * @property {number}  accuracy.resolvedCount
 * @property {boolean} isChampion     - Is this the current best model?
 */

// ─── Persistence ──────────────────────────────────────────────

/** @returns {ModelVersion[]} */
function _load() {
  const stored = getItem(VERSIONS_KEY);
  return Array.isArray(stored) ? stored : [];
}

/** @param {ModelVersion[]} versions */
function _save(versions) {
  setItem(VERSIONS_KEY, versions.slice(-MAX_VERSIONS));
}

// ─── Public API ───────────────────────────────────────────────

/**
 * Return all stored model versions, newest first.
 * @returns {ModelVersion[]}
 */
export function getVersions() {
  return _load().slice().reverse();
}

/**
 * Return the current champion version, or null if none exists.
 * @returns {ModelVersion|null}
 */
export function getChampionVersion() {
  return _load().find(v => v.isChampion) ?? null;
}

/**
 * Return the next sequential version number.
 * @returns {number}
 */
export function getNextVersionNumber() {
  const versions = _load();
  if (versions.length === 0) return 1;
  return Math.max(...versions.map(v => v.versionNumber)) + 1;
}

/**
 * Create and persist a new model version record.
 * The new version is NOT automatically promoted; call compareAndPromote()
 * to decide whether it should become the champion.
 *
 * @param {Object} params
 * @param {number} params.trainLoss
 * @param {number} params.valLoss
 * @param {{ hitRate: number, mae: number, resolvedCount: number }} params.accuracy
 * @returns {ModelVersion}
 */
export function createModelVersion({ trainLoss, valLoss, accuracy }) {
  const versions = _load();
  const versionNumber = versions.length === 0
    ? 1
    : Math.max(...versions.map(v => v.versionNumber)) + 1;

  const version = {
    id:            `v${versionNumber}_${Date.now()}`,
    versionNumber,
    trainedAt:     Date.now(),
    trainLoss:     parseFloat((trainLoss ?? 0).toFixed(6)),
    valLoss:       parseFloat((valLoss  ?? 0).toFixed(6)),
    accuracy: {
      hitRate:       accuracy?.hitRate       ?? NaN,
      mae:           accuracy?.mae           ?? NaN,
      resolvedCount: accuracy?.resolvedCount ?? 0,
    },
    isChampion: false,
  };

  versions.push(version);
  _save(versions);
  return version;
}

/**
 * Compare a candidate version against the current champion and promote it
 * if it has a better hitRate (or equal hitRate + lower MAE).
 *
 * If there is no existing champion the candidate is automatically promoted.
 *
 * @param {string} candidateId  - id of the candidate version
 * @returns {{ promoted: boolean, champion: ModelVersion }}
 */
export function compareAndPromote(candidateId) {
  const versions = _load();
  const candidate = versions.find(v => v.id === candidateId);
  if (!candidate) {
    console.warn('[Versioning] Candidate version not found:', candidateId);
    const champion = versions.find(v => v.isChampion) ?? null;
    return { promoted: false, champion };
  }

  const currentChampion = versions.find(v => v.isChampion);

  const candidateHitRate = isNaN(candidate.accuracy.hitRate) ? 0 : candidate.accuracy.hitRate;
  const championHitRate  = currentChampion
    ? (isNaN(currentChampion.accuracy.hitRate) ? 0 : currentChampion.accuracy.hitRate)
    : -Infinity;

  const candidateMAE = isNaN(candidate.accuracy.mae) ? Infinity : candidate.accuracy.mae;
  const championMAE  = currentChampion
    ? (isNaN(currentChampion.accuracy.mae) ? Infinity : currentChampion.accuracy.mae)
    : Infinity;

  // Promote if: better hitRate OR (same hitRate AND lower MAE)
  const shouldPromote =
    candidateHitRate > championHitRate ||
    (candidateHitRate === championHitRate && candidateMAE < championMAE) ||
    !currentChampion;

  // Need at least some resolved data to make a meaningful comparison,
  // unless there's no champion at all (first version always wins).
  const hasEnoughData = candidate.accuracy.resolvedCount >= MIN_RESOLVED_FOR_PROMOTION || !currentChampion;

  if (shouldPromote && hasEnoughData) {
    const updated = versions.map(v => ({
      ...v,
      isChampion: v.id === candidateId,
    }));
    _save(updated);
    const promoted = updated.find(v => v.id === candidateId);
    console.log(`[Versioning] Promoted v${promoted.versionNumber} as champion. hitRate: ${promoted.accuracy.hitRate?.toFixed(2)}`);
    return { promoted: true, champion: promoted };
  }

  console.log(`[Versioning] Candidate v${candidate.versionNumber} did not beat champion. No promotion.`);
  return { promoted: false, champion: currentChampion ?? candidate };
}

/**
 * Attach updated accuracy metrics to an existing version (e.g. after
 * evaluating the latest predictions).
 *
 * @param {string} versionId
 * @param {{ hitRate: number, mae: number, resolvedCount: number }} accuracy
 * @returns {boolean}
 */
export function updateVersionAccuracy(versionId, accuracy) {
  const versions = _load();
  const idx = versions.findIndex(v => v.id === versionId);
  if (idx === -1) return false;
  versions[idx] = {
    ...versions[idx],
    accuracy: {
      hitRate:       accuracy.hitRate       ?? NaN,
      mae:           accuracy.mae           ?? NaN,
      resolvedCount: accuracy.resolvedCount ?? 0,
    },
  };
  _save(versions);
  return true;
}
