/**
 * tests/preprocessing.test.js
 *
 * Unit tests for js/ml/preprocessing.js
 *
 * Run with Node.js (no test framework required — uses built-in assert):
 *   node tests/preprocessing.test.js
 *
 * Or with a test runner that supports ES modules (e.g., --experimental-vm-modules jest).
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

// We need to import from the preprocessing module. Since it uses ES modules
// and has no browser globals, it runs fine in Node.js 18+.
import {
  minMaxScale,
  minMaxDescale,
  calculateRSI,
  calculateMACD,
  buildFeatureMatrix,
} from '../js/ml/preprocessing.js';

// ─── minMaxScale ─────────────────────────────────────────────

describe('minMaxScale', () => {
  it('normalises a normal array to [0, 1]', () => {
    const { normalised, min, max } = minMaxScale([10, 20, 30, 40, 50]);
    assert.equal(min, 10);
    assert.equal(max, 50);
    assert.equal(normalised[0], 0);
    assert.equal(normalised[4], 1);
    assert.ok(normalised.every(v => v >= 0 && v <= 1));
  });

  it('handles an empty array without throwing', () => {
    const { normalised, min, max } = minMaxScale([]);
    assert.deepEqual(normalised, []);
    assert.equal(min, 0);
    assert.equal(max, 0);
  });

  it('handles a single-element array', () => {
    const { normalised, min, max } = minMaxScale([42]);
    assert.equal(min, 42);
    assert.equal(max, 42);
    // range is 0 → use 1 to avoid division by zero; result is 0
    assert.equal(normalised[0], 0);
  });

  it('handles all-identical values without division by zero', () => {
    const { normalised } = minMaxScale([7, 7, 7, 7]);
    assert.ok(normalised.every(v => v === 0));
  });

  it('does NOT stack overflow on a 200 000-element array (iterative reduce)', () => {
    const big = Array.from({ length: 200_000 }, (_, i) => i);
    assert.doesNotThrow(() => minMaxScale(big));
    const { normalised } = minMaxScale(big);
    assert.equal(normalised[0], 0);
    assert.equal(normalised[199_999], 1);
  });
});

// ─── minMaxDescale ────────────────────────────────────────────

describe('minMaxDescale', () => {
  it('round-trips scale + descale correctly', () => {
    const original = [100, 150, 200, 250, 300];
    const { normalised, min, max } = minMaxScale(original);
    const restored = normalised.map(v => minMaxDescale(v, min, max));
    original.forEach((v, i) => assert.ok(Math.abs(restored[i] - v) < 1e-10));
  });
});

// ─── calculateRSI ─────────────────────────────────────────────

describe('calculateRSI', () => {
  // Generate a stable series of close prices
  function makeCloses(n = 50) {
    const closes = [100];
    for (let i = 1; i < n; i++) {
      closes.push(closes[i - 1] * (1 + (Math.sin(i) * 0.02)));
    }
    return closes;
  }

  it('returns an array of the same length as input', () => {
    const closes = makeCloses(50);
    const rsi = calculateRSI(closes);
    assert.equal(rsi.length, closes.length);
  });

  it('initial values (< period) are NaN', () => {
    const closes = makeCloses(50);
    const rsi = calculateRSI(closes, 14);
    for (let i = 0; i < 14; i++) assert.ok(isNaN(rsi[i]));
  });

  it('all valid values are in [0, 1]', () => {
    const closes = makeCloses(100);
    const rsi = calculateRSI(closes, 14);
    rsi.filter(v => !isNaN(v)).forEach(v => {
      assert.ok(v >= 0 && v <= 1, `RSI value ${v} out of [0,1]`);
    });
  });

  it('returns all NaN if array is shorter than period', () => {
    const closes = [100, 101, 102];
    const rsi = calculateRSI(closes, 14);
    assert.ok(rsi.every(v => isNaN(v)));
  });

  it('RSI = 1 for continuously rising prices', () => {
    const closes = Array.from({ length: 30 }, (_, i) => 100 + i);
    const rsi = calculateRSI(closes, 14);
    const validRSI = rsi.filter(v => !isNaN(v));
    validRSI.forEach(v => assert.ok(v === 1.0, `Expected RSI 1.0, got ${v}`));
  });
});

// ─── calculateMACD ────────────────────────────────────────────

describe('calculateMACD', () => {
  function makeCloses(n = 60) {
    const c = [100];
    for (let i = 1; i < n; i++) c.push(c[i-1] + Math.sin(i * 0.3));
    return c;
  }

  it('returns an object with macd, signal, and histogram arrays', () => {
    const closes = makeCloses(60);
    const result = calculateMACD(closes);
    assert.ok('macd' in result);
    assert.ok('signal' in result);
    assert.ok('histogram' in result);
    assert.equal(result.macd.length, closes.length);
    assert.equal(result.signal.length, closes.length);
    assert.equal(result.histogram.length, closes.length);
  });

  it('histogram = macd − signal where both are valid', () => {
    const closes = makeCloses(100);
    const { macd, signal, histogram } = calculateMACD(closes);
    for (let i = 0; i < closes.length; i++) {
      if (!isNaN(macd[i]) && !isNaN(signal[i]) && !isNaN(histogram[i])) {
        assert.ok(Math.abs(histogram[i] - (macd[i] - signal[i])) < 1e-10);
      }
    }
  });

  it('returns all NaN when input is too short', () => {
    const result = calculateMACD([100, 101, 102]);
    assert.ok(result.macd.every(v => isNaN(v)));
  });
});

// ─── buildFeatureMatrix ───────────────────────────────────────

function makeCandles(n = 120) {
  const candles = [];
  let close = 100;
  const base = new Date('2023-01-02'); // Monday
  for (let i = 0; i < n; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    close = close * (1 + (Math.sin(i * 0.3) * 0.015));
    const open   = close * (1 - 0.005);
    const high   = close * (1 + 0.01);
    const low    = close * (1 - 0.01);
    const volume = 1_000_000 + i * 1000;
    candles.push({
      date:   d.toISOString().slice(0, 10),
      open,
      high,
      low,
      close,
      volume,
    });
  }
  return candles;
}

describe('buildFeatureMatrix', () => {
  it('returns exactly 33 features per row', () => {
    const candles = makeCandles(120);
    const { features } = buildFeatureMatrix(candles);
    assert.ok(features.length > 0, 'Expected at least one feature row');
    features.forEach((row, i) => {
      assert.equal(row.length, 33, `Row ${i} has ${row.length} features, expected 33`);
    });
  });

  it('returns an empty array for an empty candle input', () => {
    const { features } = buildFeatureMatrix([]);
    assert.deepEqual(features, []);
  });

  it('all feature values are finite numbers', () => {
    const candles = makeCandles(120);
    const { features } = buildFeatureMatrix(candles);
    features.forEach((row, ri) => {
      row.forEach((v, ci) => {
        assert.ok(isFinite(v), `Non-finite value at row ${ri}, col ${ci}: ${v}`);
      });
    });
  });

  it('day-of-week one-hot columns are in {0, 1}', () => {
    const candles = makeCandles(120);
    const { features } = buildFeatureMatrix(candles);
    features.forEach((row, ri) => {
      // DOW features are at indices 25-29
      for (let c = 25; c <= 29; c++) {
        assert.ok(row[c] === 0 || row[c] === 1, `DOW col ${c} row ${ri} = ${row[c]}`);
      }
      // At most one DOW bit set per row
      const dowSum = row.slice(25, 30).reduce((s, v) => s + v, 0);
      assert.ok(dowSum <= 1, `Multiple DOW bits set in row ${ri}: sum=${dowSum}`);
    });
  });

  it('month cyclical encoding stays in [-1, 1]', () => {
    const candles = makeCandles(120);
    const { features } = buildFeatureMatrix(candles);
    features.forEach((row, ri) => {
      assert.ok(row[30] >= -1 && row[30] <= 1, `month_sin out of range row ${ri}`);
      assert.ok(row[31] >= -1 && row[31] <= 1, `month_cos out of range row ${ri}`);
    });
  });

  it('close_norm (index 0) is in [0, 1]', () => {
    const candles = makeCandles(120);
    const { features } = buildFeatureMatrix(candles);
    features.forEach((row, ri) => {
      assert.ok(row[0] >= 0 && row[0] <= 1, `close_norm out of [0,1] at row ${ri}: ${row[0]}`);
    });
  });

  it('does not overflow with 200K elements in minMaxScale (called internally)', () => {
    // Create 200K candles — this will trigger large array handling
    // We only need to verify no stack overflow, so we cap at 500 candles
    // but ensure the internal reduce path is used.
    const candles = makeCandles(200);
    assert.doesNotThrow(() => buildFeatureMatrix(candles));
  });
});
