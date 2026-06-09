/**
 * tests/prediction.test.js
 *
 * Unit tests for js/ml/prediction.js
 *
 * Run with Node.js (no test framework required — uses built-in assert):
 *   node tests/prediction.test.js
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

// The prediction module imports from model.js and preprocessing.js.
// For these unit tests we only test the exported pure functions
// that do not require TF.js (demoPrediction) plus structural checks.
import { demoPrediction } from '../js/ml/prediction.js';

// ─── demoPrediction ───────────────────────────────────────────

describe('demoPrediction', () => {
  it('returns a valid Prediction object structure', () => {
    const pred = demoPrediction('AAPL', 185.0);
    assert.ok(typeof pred.symbol        === 'string');
    assert.ok(pred.direction === 'UP' || pred.direction === 'DOWN');
    assert.ok(typeof pred.probability   === 'number');
    assert.ok(typeof pred.delta         === 'number');
    assert.ok(typeof pred.confidence    === 'number');
    assert.ok(typeof pred.predictedPrice === 'number');
    assert.ok(typeof pred.currentPrice  === 'number');
    assert.ok(typeof pred.generatedAt   === 'number');
    assert.ok(pred.isDemo === true);
  });

  it('symbol field matches input', () => {
    const pred = demoPrediction('TSLA', 200.0);
    assert.equal(pred.symbol, 'TSLA');
  });

  it('currentPrice matches input', () => {
    const pred = demoPrediction('MSFT', 350.0);
    assert.equal(pred.currentPrice, 350.0);
  });

  it('confidence is within [0, 1]', () => {
    const symbols = ['AAPL', 'GOOG', 'AMZN', 'TSLA', 'NVDA', 'A', 'ZZ'];
    for (const s of symbols) {
      const pred = demoPrediction(s, 100.0);
      assert.ok(
        pred.confidence >= 0 && pred.confidence <= 1,
        `confidence out of [0,1] for ${s}: ${pred.confidence}`
      );
    }
  });

  it('predictedPrice reflects direction correctly', () => {
    const pred = demoPrediction('AAPL', 100.0);
    if (pred.direction === 'UP') {
      assert.ok(pred.predictedPrice > pred.currentPrice);
    } else {
      assert.ok(pred.predictedPrice < pred.currentPrice);
    }
  });

  it('is deterministic for the same symbol', () => {
    const p1 = demoPrediction('AAPL', 185.0);
    const p2 = demoPrediction('AAPL', 185.0);
    assert.equal(p1.direction,  p2.direction);
    assert.equal(p1.delta,      p2.delta);
    assert.equal(p1.confidence, p2.confidence);
  });

  it('generatedAt is a recent timestamp', () => {
    const before = Date.now();
    const pred   = demoPrediction('AAPL', 100.0);
    const after  = Date.now();
    assert.ok(pred.generatedAt >= before && pred.generatedAt <= after);
  });
});

// ─── Confidence clamping logic (isolated) ─────────────────────

describe('MC Dropout confidence formula (isolated)', () => {
  // Extract the formula inline for testing without TF.js
  function computeConfidence(stddev) {
    const raw = 1 - 2 * stddev;
    return parseFloat(Math.min(0.99, Math.max(0.3, raw)).toFixed(2));
  }

  it('returns max confidence (0.99) for zero stddev', () => {
    assert.equal(computeConfidence(0), 0.99);
  });

  it('returns min confidence (0.30) for high stddev', () => {
    // stddev = 0.5 → raw = 0 → clamp to 0.3
    assert.equal(computeConfidence(0.5), 0.3);
    assert.equal(computeConfidence(1.0), 0.3);
  });

  it('returns midpoint correctly', () => {
    // stddev = 0.25 → raw = 0.5
    assert.equal(computeConfidence(0.25), 0.5);
  });

  it('is always in [0.3, 0.99]', () => {
    const stddevs = [0, 0.01, 0.1, 0.25, 0.35, 0.5, 0.7, 1.0, 2.0];
    for (const s of stddevs) {
      const c = computeConfidence(s);
      assert.ok(c >= 0.3 && c <= 0.99, `confidence ${c} out of [0.3, 0.99] for stddev=${s}`);
    }
  });
});
