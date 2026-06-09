/**
 * tests/backtest.test.js
 *
 * Placeholder test file for future backtesting functionality.
 *
 * A backtest replays historical predictions through a set of features,
 * checks model performance, and validates that no data leakage occurred.
 *
 * Run with Node.js:
 *   node tests/backtest.test.js
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { runBacktest } from '../js/backtest/engine.js';

// ─── Chronological split validation ──────────────────────────

describe('Chronological time-series split (isolated)', () => {
  // Ensure that train/val/test splits never use random shuffling on time-series data.
  function chronologicalSplit(data, trainFrac = 0.7, valFrac = 0.15) {
    const n = data.length;
    const trainEnd = Math.floor(n * trainFrac);
    const valEnd   = Math.floor(n * (trainFrac + valFrac));
    return {
      train: data.slice(0, trainEnd),
      val:   data.slice(trainEnd, valEnd),
      test:  data.slice(valEnd),
    };
  }

  it('returns non-overlapping consecutive slices', () => {
    const data = Array.from({ length: 100 }, (_, i) => i);
    const { train, val, test } = chronologicalSplit(data);
    assert.equal(train.length + val.length + test.length, 100);
    // No overlap: last train index < first val index
    assert.ok(train[train.length - 1] < val[0]);
    assert.ok(val[val.length - 1] < test[0]);
  });

  it('preserves chronological order within each split', () => {
    const dates = Array.from({ length: 100 }, (_, i) => new Date(2020, 0, i + 1));
    const { train, val, test } = chronologicalSplit(dates);
    const allSorted = [...train, ...val, ...test];
    for (let i = 1; i < allSorted.length; i++) {
      assert.ok(allSorted[i] >= allSorted[i - 1]);
    }
  });

  it('test data is always after train data (no leakage)', () => {
    const data = Array.from({ length: 200 }, (_, i) => i);
    const { train, test } = chronologicalSplit(data);
    const maxTrain = Math.max(...train);
    const minTest  = Math.min(...test);
    assert.ok(minTest > maxTrain, 'Test data must be strictly after training data');
  });
});

// ─── Direction accuracy helper (isolated) ────────────────────

describe('Direction accuracy calculation (isolated)', () => {
  function computeHitRate(predictions) {
    const resolved = predictions.filter(p => p.isCorrect !== null);
    if (resolved.length === 0) return null;
    return resolved.filter(p => p.isCorrect).length / resolved.length;
  }

  it('returns null for empty list', () => {
    assert.equal(computeHitRate([]), null);
  });

  it('returns null when no predictions are resolved', () => {
    assert.equal(computeHitRate([
      { isCorrect: null },
      { isCorrect: null },
    ]), null);
  });

  it('returns 1.0 for all-correct predictions', () => {
    const preds = Array.from({ length: 10 }, () => ({ isCorrect: true }));
    assert.equal(computeHitRate(preds), 1.0);
  });

  it('returns 0.0 for all-wrong predictions', () => {
    const preds = Array.from({ length: 10 }, () => ({ isCorrect: false }));
    assert.equal(computeHitRate(preds), 0.0);
  });

  it('returns 0.5 for 50% correct', () => {
    const preds = [
      { isCorrect: true }, { isCorrect: false },
      { isCorrect: true }, { isCorrect: false },
    ];
    assert.equal(computeHitRate(preds), 0.5);
  });
});

// ─── Backtest engine regression tests ─────────────────────────

describe('Backtest engine regressions', () => {
  function makeCandles(symbol, closes, startDay = 1) {
    return closes.map((close, idx) => ({
      symbol,
      date: `2026-01-${String(startDay + idx).padStart(2, '0')}`,
      open: close,
      high: close * 1.01,
      low: close * 0.99,
      close,
      volume: 1_000_000 + idx,
    }));
  }

  it('replays generated signals without lookahead leakage', () => {
    const candles = makeCandles('AAA', [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111]);
    const result = runBacktest(candles, [], {
      confidenceThreshold: 0.5,
      maxPositions: 1,
    });

    const buyTrades = result.trades.filter(t => t.action === 'BUY');
    assert.ok(buyTrades.length > 0, 'Expected at least one generated BUY trade');
    // Momentum fallback starts at index 6, so first possible signal date is day 7.
    assert.ok(buyTrades.every(t => t.date >= '2026-01-07'));
  });

  it('computes finite Sharpe ratio for a deterministic strategy run', () => {
    const closes = [100, 102, 101, 103, 104, 105, 106, 107, 108, 110, 109, 111, 113, 112, 115];
    const candles = makeCandles('AAA', closes);
    const predictions = candles.slice(1).map(c => ({
      symbol: 'AAA',
      date: c.date,
      direction: 'UP',
      confidence: 0.9,
    }));

    const result = runBacktest(candles, predictions, {
      confidenceThreshold: 0.6,
      maxPositions: 1,
    });

    assert.equal(Number.isFinite(result.metrics.sharpeRatio), true);
    assert.equal(Number.isNaN(result.metrics.sharpeRatio), false);
  });

  it('keeps signal outcomes consistent when prices are uniformly scaled', () => {
    const base = makeCandles('AAA', [10, 11, 12, 11, 12, 13, 14, 13, 14, 15, 16, 15, 16, 17]);
    const scaled = base.map(c => ({
      ...c,
      open: c.open * 10,
      high: c.high * 10,
      low: c.low * 10,
      close: c.close * 10,
    }));

    const predictions = base.slice(1).map(c => ({
      symbol: 'AAA',
      date: c.date,
      direction: 'UP',
      confidence: 0.85,
    }));

    const r1 = runBacktest(base, predictions, { confidenceThreshold: 0.6, maxPositions: 1 });
    const r2 = runBacktest(scaled, predictions, { confidenceThreshold: 0.6, maxPositions: 1 });

    assert.equal(r1.metrics.winRate, r2.metrics.winRate);
    assert.equal(r1.metrics.totalTrades, r2.metrics.totalTrades);
    assert.equal(Math.sign(r1.metrics.totalReturn), Math.sign(r2.metrics.totalReturn));
  });

  it('detects concept drift via rolling hit-rate degradation', () => {
    const timeline = [
      ...Array.from({ length: 20 }, (_, i) => ({ day: i + 1, isCorrect: i < 15 })),
      ...Array.from({ length: 20 }, (_, i) => ({ day: i + 21, isCorrect: i < 6 })),
    ];

    function segmentHitRate(rows, startDay, endDay) {
      const seg = rows.filter(r => r.day >= startDay && r.day <= endDay);
      return seg.filter(r => r.isCorrect).length / seg.length;
    }

    const early = segmentHitRate(timeline, 1, 20);
    const late = segmentHitRate(timeline, 21, 40);
    assert.ok(early > late, `Expected degradation, got early=${early} late=${late}`);
    assert.ok((early - late) >= 0.3, 'Expected meaningful concept-drift degradation gap');
  });
});
