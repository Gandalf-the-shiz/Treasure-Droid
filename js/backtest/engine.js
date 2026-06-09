/**
 * js/backtest/engine.js
 * Backtesting Engine — Phase 9.
 *
 * Simulates a simple long-only strategy driven by the AI prediction engine.
 * Iterates day-by-day through historical candle data, entering/exiting
 * positions based on prediction direction and confidence threshold.
 *
 * Usage:
 *   const result = runBacktest(candles, predictions, config);
 *
 * candles      — Array of { date, open, high, low, close, volume }
 * predictions  — Array of { symbol, date (YYYY-MM-DD), direction, confidence, probability }
 *                OR the engine generates demo predictions from candle price movement.
 * config       — BacktestConfig object (see typedef below)
 *
 * Returns a BacktestResult object with equityCurve, trades, metrics, benchmark.
 *
 * Runs entirely client-side — no server required.
 */

// ─── Typedefs ────────────────────────────────────────────────

/**
 * @typedef {Object} BacktestConfig
 * @property {number}      initialCapital       - Starting cash (default 10000)
 * @property {number}      confidenceThreshold  - Minimum confidence to trade (0–1, default 0.6)
 * @property {number}      maxPositions         - Max concurrent positions (default 5)
 * @property {string|null} sectorFilter         - Only trade this sector (null = all)
 * @property {string}      startDate            - YYYY-MM-DD ('' = use all data)
 * @property {string}      endDate              - YYYY-MM-DD ('' = use all data)
 */

/**
 * @typedef {Object} BacktestResult
 * @property {{ date: string, portfolioValue: number, cash: number, invested: number }[]} equityCurve
 * @property {{ date: string, symbol: string, action: string, price: number, shares: number, pnl: number }[]} trades
 * @property {BacktestMetrics} metrics
 * @property {{ totalReturn: number, finalValue: number }} benchmark
 */

/**
 * @typedef {Object} BacktestMetrics
 * @property {number} totalReturn       - Decimal (e.g. 0.25 = +25%)
 * @property {number} annualizedReturn  - CAGR (decimal)
 * @property {number} sharpeRatio       - Annualised Sharpe (risk-free ≈ 5% p.a.)
 * @property {number} maxDrawdown       - Fraction of portfolio peak (e.g. 0.12 = −12%)
 * @property {string} maxDrawdownDate
 * @property {number} winRate           - Fraction of closed trades that were profitable
 * @property {number} avgWin            - Average P&L on winning trades ($)
 * @property {number} avgLoss           - Average P&L on losing trades ($, always ≤ 0)
 * @property {number} profitFactor      - Gross profits / gross losses (Infinity if no losses)
 * @property {number} totalTrades
 */

// ─── Constants ───────────────────────────────────────────────

const RISK_FREE_DAILY = 0.05 / 252; // ~5% annual T-bill rate expressed per day
const SQRT_252 = Math.sqrt(252);

/** Default configuration */
const DEFAULT_CONFIG = {
  initialCapital:      10_000,
  confidenceThreshold: 0.60,
  maxPositions:        5,
  sectorFilter:        null,
  startDate:           '',
  endDate:             '',
};

// ─── Public API ───────────────────────────────────────────────

/**
 * Run a full backtest simulation.
 *
 * @param {Object[]} candles     - OHLCV candles sorted by date ascending
 *   Each candle must have: { date: 'YYYY-MM-DD', open, high, low, close, volume, symbol? }
 * @param {Object[]} predictions - Pre-computed predictions (optional; generated from candles if empty)
 *   Each must have: { symbol, date: 'YYYY-MM-DD', direction: 'UP'|'DOWN', confidence: 0–1 }
 * @param {Partial<BacktestConfig>} [config]
 * @returns {BacktestResult}
 */
export function runBacktest(candles, predictions, config = {}) {
  const cfg = { ...DEFAULT_CONFIG, ...config };

  if (!Array.isArray(candles) || candles.length === 0) {
    return _emptyResult(cfg.initialCapital);
  }

  // ── 1. Deduplicate & normalise candles
  const normCandles = _normaliseCandles(candles);

  // ── 2. Date range filter
  const filtered = _filterByDateRange(normCandles, cfg.startDate, cfg.endDate);
  if (filtered.length === 0) return _emptyResult(cfg.initialCapital);

  // ── 3. Group candles by symbol → sorted date arrays
  const bySymbol = _groupBySymbol(filtered);
  const symbols  = Array.from(bySymbol.keys());

  // ── 4. Build a fast lookup: symbol → date → close price
  const priceLookup = _buildPriceLookup(bySymbol);

  // ── 5. Generate / index predictions
  const predBySymbolDate = _indexPredictions(predictions, bySymbol);

  // ── 6. Collect all unique trading dates (union across symbols)
  const allDates = _getAllDates(filtered);

  // ── 7. Simulation
  let cash      = cfg.initialCapital;
  /** @type {Map<string, { shares: number, entryPrice: number, entryDate: string }>} */
  const positions = new Map();

  const equityCurve = [];
  const trades      = [];

  for (const date of allDates) {
    // ─ Close positions where prediction flipped (or signal gone)
    for (const [sym, pos] of Array.from(positions.entries())) {
      const closePrice = priceLookup.get(sym)?.get(date);
      if (closePrice === undefined) continue; // no price today — hold

      const signal = predBySymbolDate.get(sym)?.get(date);
      const shouldExit =
        (signal && signal.direction !== 'UP') ||
        (signal && signal.confidence < cfg.confidenceThreshold);

      if (shouldExit) {
        const pnl = (closePrice - pos.entryPrice) * pos.shares;
        cash += closePrice * pos.shares;
        trades.push({
          date,
          symbol: sym,
          action: 'SELL',
          price:  parseFloat(closePrice.toFixed(4)),
          shares: pos.shares,
          pnl:    parseFloat(pnl.toFixed(4)),
        });
        positions.delete(sym);
      }
    }

    // ─ Open new positions
    if (positions.size < cfg.maxPositions) {
      const candidates = _getCandidates(date, symbols, predBySymbolDate, positions, cfg);

      for (const cand of candidates) {
        if (positions.size >= cfg.maxPositions) break;

        const price = priceLookup.get(cand.symbol)?.get(date);
        if (!price || price <= 0) continue;

        // Equal-weight: divide available cash among (maxPositions - current positions)
        const slots     = cfg.maxPositions - positions.size;
        const alloc     = cash / Math.max(slots, 1);
        const shares    = Math.floor(alloc / price);
        if (shares < 1) continue;

        const cost = shares * price;
        if (cost > cash) continue;

        cash -= cost;
        positions.set(cand.symbol, { shares, entryPrice: price, entryDate: date });
        trades.push({
          date,
          symbol: cand.symbol,
          action: 'BUY',
          price:  parseFloat(price.toFixed(4)),
          shares,
          pnl:    0,
        });
      }
    }

    // ─ Record equity curve point
    let invested = 0;
    for (const [sym, pos] of positions) {
      const p = priceLookup.get(sym)?.get(date) ?? pos.entryPrice;
      invested += p * pos.shares;
    }
    equityCurve.push({
      date,
      portfolioValue: parseFloat((cash + invested).toFixed(4)),
      cash:           parseFloat(cash.toFixed(4)),
      invested:       parseFloat(invested.toFixed(4)),
    });
  }

  // ─ Close all remaining positions at last known price
  const lastDate = allDates[allDates.length - 1];
  for (const [sym, pos] of Array.from(positions.entries())) {
    const price = _lastKnownPrice(priceLookup, sym, lastDate, allDates);
    if (!price) continue;
    const pnl = (price - pos.entryPrice) * pos.shares;
    cash += price * pos.shares;
    trades.push({
      date:   lastDate,
      symbol: sym,
      action: 'SELL',
      price:  parseFloat(price.toFixed(4)),
      shares: pos.shares,
      pnl:    parseFloat(pnl.toFixed(4)),
    });
  }

  const finalValue = parseFloat(cash.toFixed(4));

  // ── 8. Benchmark: equal-weight buy-and-hold across all symbols
  const benchmark = _calcBenchmark(bySymbol, allDates, cfg.initialCapital, symbols);

  // ── 9. Metrics
  const metrics = _calcMetrics(equityCurve, trades, cfg.initialCapital, allDates);

  return { equityCurve, trades, metrics, benchmark };
}

// ─── Helpers ─────────────────────────────────────────────────

function _normaliseCandles(candles) {
  return candles
    .filter(c => c && c.date && typeof c.close === 'number' && !isNaN(c.close))
    .map(c => ({
      ...c,
      symbol: c.symbol ?? 'UNKNOWN',
      date:   String(c.date).slice(0, 10), // YYYY-MM-DD
    }));
}

function _filterByDateRange(candles, start, end) {
  if (!start && !end) return candles;
  return candles.filter(c => {
    if (start && c.date < start) return false;
    if (end   && c.date > end)   return false;
    return true;
  });
}

function _groupBySymbol(candles) {
  /** @type {Map<string, Object[]>} */
  const map = new Map();
  for (const c of candles) {
    if (!map.has(c.symbol)) map.set(c.symbol, []);
    map.get(c.symbol).push(c);
  }
  // Sort each symbol's candles by date
  for (const [, arr] of map) arr.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return map;
}

function _buildPriceLookup(bySymbol) {
  /** @type {Map<string, Map<string, number>>} */
  const outer = new Map();
  for (const [sym, candles] of bySymbol) {
    const inner = new Map();
    for (const c of candles) inner.set(c.date, c.close);
    outer.set(sym, inner);
  }
  return outer;
}

function _getAllDates(candles) {
  const set = new Set(candles.map(c => c.date));
  return Array.from(set).sort();
}

/**
 * Build a two-level map: symbol → date → { direction, confidence }.
 * If predictions array is empty, generate naive "momentum" signals from candles.
 */
function _indexPredictions(predictions, bySymbol) {
  /** @type {Map<string, Map<string, { direction: string, confidence: number }>>} */
  const map = new Map();

  if (!Array.isArray(predictions) || predictions.length === 0) {
    // Generate simple momentum signal using ONLY past data (no lookahead bias).
    // Signal for day[i] uses previous day's close vs 5-day SMA of days [i-6..i-2].
    // At the start of day[i], we know yesterday's close (candles[i-1].close) and all
    // prior closes, but NOT today's close (candles[i].close).
    for (const [sym, candles] of bySymbol) {
      const inner = new Map();
      for (let i = 6; i < candles.length; i++) {
        // SMA of the 5 days ending at i-2 (all known before day i opens)
        let sma5 = 0;
        for (let k = 2; k <= 6; k++) sma5 += candles[i - k].close;
        sma5 /= 5;
        // Compare previous day's close (known) against the historical SMA
        const prevClose  = candles[i - 1].close;
        const direction  = prevClose > sma5 ? 'UP' : 'DOWN';
        const confidence = Math.min(0.9, 0.5 + Math.abs(prevClose - sma5) / sma5 * 5);
        inner.set(candles[i].date, { direction, confidence });
      }
      map.set(sym, inner);
    }
    return map;
  }

  for (const p of predictions) {
    if (!p.symbol || !p.date) continue;
    if (!map.has(p.symbol)) map.set(p.symbol, new Map());
    map.get(p.symbol).set(String(p.date).slice(0, 10), {
      direction:  p.direction  ?? 'UP',
      confidence: p.confidence ?? 0.5,
    });
  }
  return map;
}

function _getCandidates(date, symbols, predBySymbolDate, positions, cfg) {
  const candidates = [];
  for (const sym of symbols) {
    if (positions.has(sym)) continue;
    const signal = predBySymbolDate.get(sym)?.get(date);
    if (!signal) continue;
    if (signal.direction !== 'UP') continue;
    if (signal.confidence < cfg.confidenceThreshold) continue;
    candidates.push({ symbol: sym, confidence: signal.confidence });
  }
  // Sort highest confidence first
  return candidates.sort((a, b) => b.confidence - a.confidence);
}

function _lastKnownPrice(priceLookup, sym, targetDate, allDates) {
  const prices = priceLookup.get(sym);
  if (!prices) return null;
  // Walk backwards from targetDate
  for (let i = allDates.length - 1; i >= 0; i--) {
    const d = allDates[i];
    if (d <= targetDate && prices.has(d)) return prices.get(d);
  }
  return null;
}

// ─── Benchmark ────────────────────────────────────────────────

function _calcBenchmark(bySymbol, allDates, initialCapital, symbols) {
  if (symbols.length === 0 || allDates.length === 0) {
    return { totalReturn: 0, finalValue: initialCapital };
  }

  const firstDate = allDates[0];
  const lastDate  = allDates[allDates.length - 1];

  const perSymbolCapital = initialCapital / symbols.length;

  let totalFinal = 0;
  for (const sym of symbols) {
    const candles = bySymbol.get(sym);
    if (!candles || candles.length === 0) { totalFinal += perSymbolCapital; continue; }

    const first = candles[0].close;
    const last  = candles[candles.length - 1].close;
    if (!first || first === 0) { totalFinal += perSymbolCapital; continue; }

    const shares = perSymbolCapital / first;
    totalFinal  += shares * last;
  }

  const totalReturn = (totalFinal - initialCapital) / initialCapital;
  return {
    totalReturn: parseFloat(totalReturn.toFixed(6)),
    finalValue:  parseFloat(totalFinal.toFixed(4)),
  };
}

// ─── Metrics ─────────────────────────────────────────────────

function _calcMetrics(equityCurve, trades, initialCapital, allDates) {
  if (equityCurve.length === 0) {
    return _zeroMetrics();
  }

  const finalValue = equityCurve[equityCurve.length - 1].portfolioValue;
  const totalReturn = (finalValue - initialCapital) / initialCapital;

  // Annualised return (CAGR)
  const years = allDates.length / 252;
  const annualizedReturn = years > 0
    ? Math.pow(1 + totalReturn, 1 / years) - 1
    : totalReturn;

  // Daily returns for Sharpe
  const dailyReturns = [];
  for (let i = 1; i < equityCurve.length; i++) {
    const prev = equityCurve[i - 1].portfolioValue;
    const cur  = equityCurve[i].portfolioValue;
    if (prev > 0) dailyReturns.push((cur - prev) / prev);
  }

  const sharpeRatio = _calcSharpe(dailyReturns);

  // Max drawdown
  const { maxDrawdown, maxDrawdownDate } = _calcMaxDrawdown(equityCurve);

  // Trade metrics (only SELL trades have a real P&L)
  const closedTrades = trades.filter(t => t.action === 'SELL');
  const wins  = closedTrades.filter(t => t.pnl > 0);
  const losses = closedTrades.filter(t => t.pnl <= 0);

  const grossProfit = wins.reduce((s, t) => s + t.pnl, 0);
  const grossLoss   = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));

  const winRate     = closedTrades.length > 0 ? wins.length / closedTrades.length : 0;
  const avgWin      = wins.length  > 0 ? grossProfit / wins.length  : 0;
  const avgLoss     = losses.length > 0 ? -(grossLoss / losses.length) : 0;
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : (grossProfit > 0 ? Infinity : 1);

  return {
    totalReturn:      parseFloat(totalReturn.toFixed(6)),
    annualizedReturn: parseFloat(annualizedReturn.toFixed(6)),
    sharpeRatio:      parseFloat(sharpeRatio.toFixed(4)),
    maxDrawdown:      parseFloat(maxDrawdown.toFixed(6)),
    maxDrawdownDate,
    winRate:          parseFloat(winRate.toFixed(4)),
    avgWin:           parseFloat(avgWin.toFixed(4)),
    avgLoss:          parseFloat(avgLoss.toFixed(4)),
    profitFactor:     isFinite(profitFactor) ? parseFloat(profitFactor.toFixed(4)) : Infinity,
    totalTrades:      closedTrades.length,
  };
}

function _calcSharpe(dailyReturns) {
  if (dailyReturns.length < 2) return 0;
  const mean   = dailyReturns.reduce((s, r) => s + r, 0) / dailyReturns.length;
  const excess = mean - RISK_FREE_DAILY;
  const variance = dailyReturns.reduce((s, r) => s + Math.pow(r - mean, 2), 0) / (dailyReturns.length - 1);
  const std = Math.sqrt(variance);
  return std === 0 ? 0 : (excess / std) * SQRT_252;
}

function _calcMaxDrawdown(equityCurve) {
  let peak     = equityCurve[0].portfolioValue;
  let maxDD    = 0;
  let maxDDDate = equityCurve[0].date;

  for (const point of equityCurve) {
    if (point.portfolioValue > peak) {
      peak = point.portfolioValue;
    }
    const dd = peak > 0 ? (peak - point.portfolioValue) / peak : 0;
    if (dd > maxDD) {
      maxDD    = dd;
      maxDDDate = point.date;
    }
  }
  return { maxDrawdown: maxDD, maxDrawdownDate: maxDDDate };
}

function _zeroMetrics() {
  return {
    totalReturn: 0, annualizedReturn: 0, sharpeRatio: 0,
    maxDrawdown: 0, maxDrawdownDate: '', winRate: 0,
    avgWin: 0, avgLoss: 0, profitFactor: 1, totalTrades: 0,
  };
}

function _emptyResult(initialCapital) {
  return {
    equityCurve: [{ date: '', portfolioValue: initialCapital, cash: initialCapital, invested: 0 }],
    trades:      [],
    metrics:     _zeroMetrics(),
    benchmark:   { totalReturn: 0, finalValue: initialCapital },
  };
}
