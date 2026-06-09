/**
 * tests/api-manager.test.js
 *
 * Unit tests for js/api/manager.js — fallback chain logic and cache TTL.
 *
 * Run with Node.js:
 *   node tests/api-manager.test.js
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

// ─── Cache TTL behaviour (isolated, no DOM) ───────────────────

describe('Cache TTL behaviour (isolated logic)', () => {
  // Replicate cache expiry logic without browser globals
  function isCacheExpired(storedAt, ttlMs) {
    if (storedAt == null) return true;
    return Date.now() - storedAt > ttlMs;
  }

  it('returns false when cache is fresh', () => {
    const ttl    = 5 * 60 * 1000; // 5 minutes
    const stored = Date.now() - 60_000; // 1 minute ago
    assert.equal(isCacheExpired(stored, ttl), false);
  });

  it('returns true when cache is stale', () => {
    const ttl    = 5 * 60 * 1000;
    const stored = Date.now() - 10 * 60 * 1000; // 10 minutes ago
    assert.equal(isCacheExpired(stored, ttl), true);
  });

  it('returns true when storedAt is null (no cache entry)', () => {
    assert.equal(isCacheExpired(null, 60_000), true);
  });

  it('returns true when storedAt is undefined', () => {
    assert.equal(isCacheExpired(undefined, 60_000), true);
  });

  it('expires at exactly the TTL boundary', () => {
    const ttl     = 5000;
    const storeAt = Date.now() - ttl - 1;
    assert.equal(isCacheExpired(storeAt, ttl), true);
  });
});

// ─── Fallback chain logic (isolated) ─────────────────────────

describe('API fallback chain logic (isolated)', () => {
  // Simulate a fallback chain: try each provider in order, return first success
  async function fetchWithFallback(providers) {
    const errors = [];
    for (const provider of providers) {
      try {
        return await provider();
      } catch (err) {
        errors.push(err.message);
      }
    }
    throw new Error(`All providers failed: ${errors.join(', ')}`);
  }

  it('returns the first provider result when it succeeds', async () => {
    const result = await fetchWithFallback([
      () => Promise.resolve('provider-A'),
      () => Promise.resolve('provider-B'),
    ]);
    assert.equal(result, 'provider-A');
  });

  it('falls through to second provider when first fails', async () => {
    const result = await fetchWithFallback([
      () => Promise.reject(new Error('Provider A down')),
      () => Promise.resolve('provider-B'),
    ]);
    assert.equal(result, 'provider-B');
  });

  it('falls through to third provider when first two fail', async () => {
    const result = await fetchWithFallback([
      () => Promise.reject(new Error('A')),
      () => Promise.reject(new Error('B')),
      () => Promise.resolve('provider-C'),
    ]);
    assert.equal(result, 'provider-C');
  });

  it('throws when all providers fail', async () => {
    await assert.rejects(
      () => fetchWithFallback([
        () => Promise.reject(new Error('A')),
        () => Promise.reject(new Error('B')),
      ]),
      /All providers failed/
    );
  });

  it('does not call later providers after a success', async () => {
    let called = false;
    await fetchWithFallback([
      () => Promise.resolve('ok'),
      () => { called = true; return Promise.resolve('late'); },
    ]);
    assert.equal(called, false);
  });
});

describe('Prediction payload normalisation (isolated)', () => {
  function normalisePredictions(data) {
    const entries = Array.isArray(data.predictions)
      ? data.predictions.filter(p => p?.symbol).map(p => [p.symbol, p])
      : Object.entries(data.predictions || {});
    return entries.map(([symbol, pred]) => ({
      symbol,
      probability: pred.probability ?? 0.5,
      direction: pred.direction ?? ((pred.probability ?? 0.5) > 0.5 ? 'UP' : 'DOWN'),
      confidence: pred.confidence ?? Math.abs((pred.probability ?? 0.5) - 0.5) * 2,
    }));
  }

  it('accepts dict-shaped predictions payload', () => {
    const out = normalisePredictions({
      predictions: {
        AAPL: { probability: 0.7, direction: 'UP', confidence: 0.8 },
      },
    });
    assert.equal(out.length, 1);
    assert.equal(out[0].symbol, 'AAPL');
  });

  it('accepts array-shaped predictions payload', () => {
    const out = normalisePredictions({
      predictions: [
        { symbol: 'MSFT', probability: 0.4, direction: 'DOWN', confidence: 0.7 },
      ],
    });
    assert.equal(out.length, 1);
    assert.equal(out[0].symbol, 'MSFT');
    assert.equal(out[0].direction, 'DOWN');
  });
});
