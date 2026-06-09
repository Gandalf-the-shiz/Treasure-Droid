/**
 * js/ml/preprocessing.js
 * Data preprocessing utilities for the ML pipeline.
 *
 * Converts raw OHLCV data into normalised feature tensors suitable for LSTM training.
 * Computes exactly 33 features per time step in the same order as FEATURE_NAMES in
 * build-features.py — feature parity is CRITICAL for server-trained model inference.
 *
 * Feature set (indices match build-features.py FEATURE_NAMES):
 *  0  close_norm       — min-max normalised close price
 *  1  open_norm        — min-max normalised open price
 *  2  high_norm        — min-max normalised high price
 *  3  low_norm         — min-max normalised low price
 *  4  volume_norm      — min-max normalised volume
 *  5  rsi_14           — RSI(14) ÷ 100
 *  6  macd_line        — MACD line ÷ close (normalised by price)
 *  7  macd_signal      — MACD signal ÷ close
 *  8  macd_hist        — MACD histogram ÷ close
 *  9  sma5_rel         — (SMA5 − close) ÷ close
 *  10 sma20_rel        — (SMA20 − close) ÷ close
 *  11 sma50_rel        — (SMA50 − close) ÷ close
 *  12 ema12_rel        — (EMA12 − close) ÷ close
 *  13 ema26_rel        — (EMA26 − close) ÷ close
 *  14 bb_upper_rel     — (BB upper − close) ÷ close
 *  15 bb_lower_rel     — (close − BB lower) ÷ close
 *  16 bb_width         — (BB upper − BB lower) ÷ close
 *  17 atr14_norm       — ATR(14) ÷ close
 *  18 obv_norm         — OBV min-max normalised
 *  19 stoch_k          — Stochastic %K ÷ 100
 *  20 stoch_d          — Stochastic %D ÷ 100
 *  21 roc10            — ROC(10) ÷ 100
 *  22 momentum5        — (close − close[−5]) ÷ close[−5]
 *  23 volatility30     — 30-day realised vol (annualised std of daily returns)
 *  24 volume_ratio     — volume ÷ SMA20(volume)
 *  25 dow_mon          — 1 if Monday else 0
 *  26 dow_tue          — 1 if Tuesday else 0
 *  27 dow_wed          — 1 if Wednesday else 0
 *  28 dow_thu          — 1 if Thursday else 0
 *  29 dow_fri          — 1 if Friday else 0
 *  30 month_sin        — sin(2π × month ÷ 12)
 *  31 month_cos        — cos(2π × month ÷ 12)
 *  32 sentiment        — sentiment score [-1, +1] (from news or technical proxy)
 */

/**
 * @typedef {Object} OHLCV
 * @property {string} date
 * @property {number} open
 * @property {number} high
 * @property {number} low
 * @property {number} close
 * @property {number} volume
 */

/**
 * Normalise an array of values to the [0, 1] range using min-max scaling.
 * Uses iterative reduce() to avoid stack overflow on large arrays.
 *
 * @param {number[]} values
 * @returns {{ normalised: number[], min: number, max: number }}
 */
export function minMaxScale(values) {
  if (values.length === 0) return { normalised: [], min: 0, max: 0 };

  const min = values.reduce((a, b) => (b < a ? b : a), values[0]);
  const max = values.reduce((a, b) => (b > a ? b : a), values[0]);
  const range = max - min || 1; // avoid division by zero
  const normalised = values.map(v => (v - min) / range);
  return { normalised, min, max };
}

/**
 * Denormalise a value from [0, 1] back to the original scale.
 * @param {number} value
 * @param {number} min
 * @param {number} max
 * @returns {number}
 */
export function minMaxDescale(value, min, max) {
  return value * (max - min) + min;
}

/**
 * Safe division: a / b, returns 0 when b is 0.
 * @param {number} a
 * @param {number} b
 * @returns {number}
 */
function safeDiv(a, b) {
  return b === 0 ? 0 : a / b;
}

/**
 * Compute EMA for an array of values.
 * @param {number[]} values
 * @param {number} period
 * @returns {number[]}  Same length; initial values are NaN until period is reached.
 */
function calculateEMA(values, period) {
  const result = new Array(values.length).fill(NaN);
  const multiplier = 2 / (period + 1);

  // Seed with SMA of first `period` values
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  result[period - 1] = sum / period;

  for (let i = period; i < values.length; i++) {
    result[i] = values[i] * multiplier + result[i - 1] * (1 - multiplier);
  }
  return result;
}

/**
 * Calculate RSI (Relative Strength Index) for an array of close prices.
 * @param {number[]} closes
 * @param {number} [period=14]
 * @returns {number[]}  Same length as closes; initial values are NaN. Values in [0, 1].
 */
export function calculateRSI(closes, period = 14) {
  const rsi = new Array(closes.length).fill(NaN);

  if (closes.length <= period) return rsi;

  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = closes[i] - closes[i - 1];
    if (change > 0) gains += change;
    else losses += -change;
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  rsi[period] = avgLoss === 0 ? 1.0 : (100 - 100 / (1 + avgGain / avgLoss)) / 100;

  for (let i = period + 1; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(change, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-change, 0)) / period;
    rsi[i] = avgLoss === 0 ? 1.0 : (100 - 100 / (1 + avgGain / avgLoss)) / 100;
  }

  return rsi;
}

/**
 * Calculate MACD (Moving Average Convergence Divergence).
 * @param {number[]} closes
 * @param {number} [fast=12]
 * @param {number} [slow=26]
 * @param {number} [signal=9]
 * @returns {{ macd: number[], signal: number[], histogram: number[] }}
 */
export function calculateMACD(closes, fast = 12, slow = 26, signal = 9) {
  const len = closes.length;
  const macdLine   = new Array(len).fill(NaN);
  const signalLine = new Array(len).fill(NaN);
  const histogram  = new Array(len).fill(NaN);

  if (len < slow) return { macd: macdLine, signal: signalLine, histogram };

  const emaFast = calculateEMA(closes, fast);
  const emaSlow = calculateEMA(closes, slow);

  for (let i = slow - 1; i < len; i++) {
    if (!isNaN(emaFast[i]) && !isNaN(emaSlow[i])) {
      macdLine[i] = safeDiv(emaFast[i] - emaSlow[i], closes[i]);
    }
  }

  const signalMultiplier = 2 / (signal + 1);
  let firstMacdIdx = -1;
  for (let i = 0; i < len; i++) {
    if (!isNaN(macdLine[i])) { firstMacdIdx = i; break; }
  }

  if (firstMacdIdx >= 0 && firstMacdIdx + signal - 1 < len) {
    let seedSum = 0;
    let count = 0;
    for (let i = firstMacdIdx; count < signal && i < len; i++) {
      if (!isNaN(macdLine[i])) {
        seedSum += macdLine[i];
        count++;
        if (count === signal) {
          signalLine[i] = seedSum / signal;
          histogram[i]  = macdLine[i] - signalLine[i];
          for (let j = i + 1; j < len; j++) {
            signalLine[j] = isNaN(macdLine[j])
              ? signalLine[j - 1]
              : macdLine[j] * signalMultiplier + signalLine[j - 1] * (1 - signalMultiplier);
            histogram[j] = isNaN(macdLine[j]) ? NaN : macdLine[j] - signalLine[j];
          }
        }
      }
    }
  }

  return { macd: macdLine, signal: signalLine, histogram };
}

/**
 * Calculate Bollinger Bands (20-period, 2 std dev).
 * @param {number[]} closes
 * @param {number} [period=20]
 * @param {number} [stdDevMultiplier=2]
 * @returns {{ upper: number[], lower: number[], middle: number[] }}
 */
function calculateBollingerBands(closes, period = 20, stdDevMultiplier = 2) {
  const upper  = new Array(closes.length).fill(NaN);
  const lower  = new Array(closes.length).fill(NaN);
  const middle = new Array(closes.length).fill(NaN);

  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1);
    const mean  = slice.reduce((s, v) => s + v, 0) / period;
    const variance = slice.reduce((s, v) => s + (v - mean) ** 2, 0) / period;
    const stdDev = Math.sqrt(variance);
    middle[i] = mean;
    upper[i]  = mean + stdDevMultiplier * stdDev;
    lower[i]  = mean - stdDevMultiplier * stdDev;
  }
  return { upper, lower, middle };
}

/**
 * Calculate ATR (Average True Range).
 * @param {number[]} highs
 * @param {number[]} lows
 * @param {number[]} closes
 * @param {number} [period=14]
 * @returns {number[]}
 */
function calculateATR(highs, lows, closes, period = 14) {
  const atr = new Array(closes.length).fill(NaN);
  if (closes.length <= period) return atr;

  // True Range
  const tr = new Array(closes.length).fill(NaN);
  tr[0] = highs[0] - lows[0];
  for (let i = 1; i < closes.length; i++) {
    tr[i] = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
  }

  // Seed with simple average
  let sum = 0;
  for (let i = 0; i < period; i++) sum += tr[i];
  atr[period - 1] = sum / period;

  for (let i = period; i < closes.length; i++) {
    atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period;
  }
  return atr;
}

/**
 * Calculate OBV (On-Balance Volume).
 * @param {number[]} closes
 * @param {number[]} volumes
 * @returns {number[]}
 */
function calculateOBV(closes, volumes) {
  const obv = new Array(closes.length).fill(0);
  for (let i = 1; i < closes.length; i++) {
    if (closes[i] > closes[i - 1])      obv[i] = obv[i - 1] + volumes[i];
    else if (closes[i] < closes[i - 1]) obv[i] = obv[i - 1] - volumes[i];
    else                                 obv[i] = obv[i - 1];
  }
  return obv;
}

/**
 * Calculate Stochastic Oscillator %K and %D.
 * @param {number[]} highs
 * @param {number[]} lows
 * @param {number[]} closes
 * @param {number} [period=14]
 * @param {number} [smoothPeriod=3]
 * @returns {{ k: number[], d: number[] }}
 */
function calculateStochastic(highs, lows, closes, period = 14, smoothPeriod = 3) {
  const k = new Array(closes.length).fill(NaN);
  const d = new Array(closes.length).fill(NaN);

  for (let i = period - 1; i < closes.length; i++) {
    const windowHighs  = highs.slice(i - period + 1, i + 1);
    const windowLows   = lows.slice(i - period + 1, i + 1);
    const highestHigh  = windowHighs.reduce((a, b) => (b > a ? b : a), windowHighs[0]);
    const lowestLow    = windowLows.reduce((a, b) => (b < a ? b : a), windowLows[0]);
    const range = highestHigh - lowestLow;
    k[i] = range === 0 ? 0.5 : (closes[i] - lowestLow) / range;
  }

  // %D = SMA(smoothPeriod) of %K
  for (let i = period + smoothPeriod - 2; i < closes.length; i++) {
    const slice = k.slice(i - smoothPeriod + 1, i + 1);
    if (slice.every(v => !isNaN(v))) {
      d[i] = slice.reduce((s, v) => s + v, 0) / smoothPeriod;
    }
  }

  return { k, d };
}

/**
 * Calculate simple moving averages for an array of values.
 * @param {number[]} values
 * @param {number} period
 * @returns {number[]}  Same length; initial values are NaN.
 */
function smaArr(values, period) {
  return values.map((_, i) => {
    if (i < period - 1) return NaN;
    const slice = values.slice(i - period + 1, i + 1);
    return slice.reduce((s, v) => s + v, 0) / period;
  });
}

/**
 * Convert an array of OHLCV objects into a 2D feature matrix with 33 features per row.
 * Feature order is IDENTICAL to FEATURE_NAMES in build-features.py.
 *
 * Optionally applies per-ticker scaling parameters from models/v2/metadata.json
 * when passed as the second argument.
 *
 * An optional `sentimentScores` map (date string → score in [-1, +1]) can be provided
 * to supply real news-derived sentiment for each day. When a date has no entry in the map,
 * a technical sentiment proxy is computed instead (matching build-features.py).
 *
 * @param {OHLCV[]} candles  - Sorted oldest → newest; must include open/high/low/close/volume/date
 * @param {Object|null} [scalingParams=null]  - Optional per-ticker scaling from metadata.json
 * @param {Map<string, number>|null} [sentimentScores=null]  - Optional map of date→sentiment score
 * @returns {{ features: number[][], priceMin: number, priceMax: number, volumeMin: number, volumeMax: number }}
 */
export function buildFeatureMatrix(candles, scalingParams = null, sentimentScores = null) {
  const n = candles.length;
  if (n === 0) return { features: [], priceMin: 0, priceMax: 0, volumeMin: 0, volumeMax: 0 };

  const closes  = candles.map(c => c.close);
  const opens   = candles.map(c => c.open);
  const highs   = candles.map(c => c.high);
  const lows    = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume);

  // ── Min-max normalise price/volume (iterative, no stack overflow) ──
  const { normalised: closeNorm,  min: priceMin,  max: priceMax  } = minMaxScale(closes);
  const { normalised: openNorm                                    } = minMaxScale(opens);
  const { normalised: highNorm                                    } = minMaxScale(highs);
  const { normalised: lowNorm                                     } = minMaxScale(lows);
  const { normalised: volumeNorm, min: volumeMin, max: volumeMax } = minMaxScale(volumes);

  // ── RSI-14 ──
  const rsi14 = calculateRSI(closes, 14);

  // ── MACD ──
  const { macd: macdLine, signal: macdSignal, histogram: macdHist } = calculateMACD(closes);

  // ── SMAs relative to close: (SMA - close) / close ──
  const sma5  = smaArr(closes, 5);
  const sma20 = smaArr(closes, 20);
  const sma50 = smaArr(closes, 50);
  const sma5Rel  = sma5.map((v, i)  => isNaN(v) ? NaN : safeDiv(v - closes[i], closes[i]));
  const sma20Rel = sma20.map((v, i) => isNaN(v) ? NaN : safeDiv(v - closes[i], closes[i]));
  const sma50Rel = sma50.map((v, i) => isNaN(v) ? NaN : safeDiv(v - closes[i], closes[i]));

  // ── EMAs relative to close ──
  const ema12 = calculateEMA(closes, 12);
  const ema26 = calculateEMA(closes, 26);
  const ema12Rel = ema12.map((v, i) => isNaN(v) ? NaN : safeDiv(v - closes[i], closes[i]));
  const ema26Rel = ema26.map((v, i) => isNaN(v) ? NaN : safeDiv(v - closes[i], closes[i]));

  // ── Bollinger Bands ──
  const bb = calculateBollingerBands(closes, 20, 2);
  const bbUpperRel = bb.upper.map((v, i) => isNaN(v) ? NaN : safeDiv(v - closes[i], closes[i]));
  const bbLowerRel = bb.lower.map((v, i) => isNaN(v) ? NaN : safeDiv(closes[i] - v, closes[i]));
  const bbWidth    = bb.upper.map((v, i) => isNaN(v) ? NaN : safeDiv(v - bb.lower[i], closes[i]));

  // ── ATR-14 normalised by close ──
  const atr14 = calculateATR(highs, lows, closes, 14);
  const atr14Norm = atr14.map((v, i) => isNaN(v) ? NaN : safeDiv(v, closes[i]));

  // ── OBV normalised ──
  const obvRaw  = calculateOBV(closes, volumes);
  const { normalised: obvNorm } = minMaxScale(obvRaw);

  // ── Stochastic %K, %D ──
  const { k: stochK, d: stochD } = calculateStochastic(highs, lows, closes, 14, 3);

  // ── ROC-10: (close - close[i-10]) / close[i-10] ÷ 100 ──
  const roc10 = closes.map((v, i) => {
    if (i < 10) return NaN;
    const prev = closes[i - 10];
    return safeDiv(v - prev, prev);
  });

  // ── 5-day momentum: (close - close[i-5]) / close[i-5] ──
  const momentum5 = closes.map((v, i) => {
    if (i < 5) return NaN;
    const prev = closes[i - 5];
    return safeDiv(v - prev, prev);
  });

  // ── 30-day realised volatility (annualised std of daily returns) ──
  const dailyReturns = closes.map((v, i) => i === 0 ? NaN : safeDiv(v - closes[i - 1], closes[i - 1]));
  const volatility30 = dailyReturns.map((_, i) => {
    if (i < 30) return NaN;
    const window = dailyReturns.slice(i - 29, i + 1).filter(v => !isNaN(v));
    if (window.length < 2) return NaN;
    const mean = window.reduce((s, v) => s + v, 0) / window.length;
    const variance = window.reduce((s, v) => s + (v - mean) ** 2, 0) / (window.length - 1);
    return Math.sqrt(variance) * Math.sqrt(252);
  });

  // ── Volume ratio: volume / SMA20(volume) ──
  const volSma20 = smaArr(volumes, 20);
  const volumeRatio = volumes.map((v, i) => isNaN(volSma20[i]) ? NaN : safeDiv(v, volSma20[i]));

  // ── Calendar features ──
  const features = [];

  for (let i = 0; i < n; i++) {
    // Skip rows where any key indicator is NaN (warmup period)
    if (
      isNaN(rsi14[i])     ||
      isNaN(macdLine[i])  ||
      isNaN(macdSignal[i])||
      isNaN(macdHist[i])  ||
      isNaN(sma5Rel[i])   ||
      isNaN(sma20Rel[i])  ||
      isNaN(sma50Rel[i])  ||
      isNaN(ema12Rel[i])  ||
      isNaN(ema26Rel[i])  ||
      isNaN(bbUpperRel[i])||
      isNaN(bbLowerRel[i])||
      isNaN(bbWidth[i])   ||
      isNaN(atr14Norm[i]) ||
      isNaN(stochK[i])    ||
      isNaN(stochD[i])    ||
      isNaN(roc10[i])     ||
      isNaN(momentum5[i]) ||
      isNaN(volatility30[i]) ||
      isNaN(volumeRatio[i])
    ) continue;

    // Parse day-of-week and month from date string.
    // JavaScript Date.getDay(): 0=Sunday, 1=Monday, …, 5=Friday, 6=Saturday.
    // build-features.py uses dt.dayofweek: 0=Monday, …, 4=Friday.
    // Both produce equivalent one-hot encodings: Mon-Fri each get their own bit;
    // weekends (Sat/Sun) have all five bits = 0 (no market data on weekends anyway).
    const dateObj = new Date(candles[i].date);
    const dow = dateObj.getDay(); // 0=Sun, 1=Mon, …, 6=Sat
    const month = dateObj.getMonth() + 1; // 1–12

    // Sentiment: use real score from map when available, otherwise compute technical proxy
    // matching build-features.py: tanh(rsiDev * 0.5 + momentum5 * 2 + macdHist * 10)
    const dateStr = candles[i].date.slice(0, 10); // normalise to YYYY-MM-DD
    let sentimentValue;
    if (sentimentScores !== null && sentimentScores.has(dateStr)) {
      sentimentValue = sentimentScores.get(dateStr);
    } else {
      // Technical sentiment proxy matching build-features.py
      const rsiDev = (rsi14[i] - 0.5) * 2;
      sentimentValue = Math.tanh(rsiDev * 0.5 + momentum5[i] * 2 + macdHist[i] * 10);
    }

    features.push([
      closeNorm[i],           //  0 close_norm
      openNorm[i],            //  1 open_norm
      highNorm[i],            //  2 high_norm
      lowNorm[i],             //  3 low_norm
      volumeNorm[i],          //  4 volume_norm
      rsi14[i],               //  5 rsi_14
      macdLine[i],            //  6 macd_line
      macdSignal[i],          //  7 macd_signal
      macdHist[i],            //  8 macd_hist
      sma5Rel[i],             //  9 sma5_rel
      sma20Rel[i],            // 10 sma20_rel
      sma50Rel[i],            // 11 sma50_rel
      ema12Rel[i],            // 12 ema12_rel
      ema26Rel[i],            // 13 ema26_rel
      bbUpperRel[i],          // 14 bb_upper_rel
      bbLowerRel[i],          // 15 bb_lower_rel
      bbWidth[i],             // 16 bb_width
      atr14Norm[i],           // 17 atr14_norm
      obvNorm[i],             // 18 obv_norm
      stochK[i],              // 19 stoch_k
      stochD[i],              // 20 stoch_d
      roc10[i],               // 21 roc10
      momentum5[i],           // 22 momentum5
      volatility30[i],        // 23 volatility30
      volumeRatio[i],         // 24 volume_ratio
      dow === 1 ? 1 : 0,      // 25 dow_mon
      dow === 2 ? 1 : 0,      // 26 dow_tue
      dow === 3 ? 1 : 0,      // 27 dow_wed
      dow === 4 ? 1 : 0,      // 28 dow_thu
      dow === 5 ? 1 : 0,      // 29 dow_fri
      Math.sin(2 * Math.PI * month / 12),  // 30 month_sin
      Math.cos(2 * Math.PI * month / 12),  // 31 month_cos
      sentimentValue,                       // 32 sentiment
    ]);
  }

  return { features, priceMin, priceMax, volumeMin, volumeMax };
}

/**
 * Slice the feature matrix into overlapping windows for sequence modeling.
 *
 * @param {number[][]} features
 * @param {number} windowSize
 * @param {number} [priceMin=0]   - Returned by buildFeatureMatrix; used to descale close for regression labels.
 * @param {number} [priceMax=1]   - Returned by buildFeatureMatrix; used to descale close for regression labels.
 * @returns {{ X: number[][][], y: number[], yReg: number[] }}
 *   X[i]    = window of windowSize rows (input tensor)
 *   y[i]    = 1 if next close > current close, else 0  (binary classification label)
 *   yReg[i] = approximate next-day % return, clipped to ±0.20 (regression label)
 */
export function createWindows(features, windowSize, priceMin = 0, priceMax = 1) {
  const X    = [];
  const y    = [];
  const yReg = [];

  const priceRange = priceMax - priceMin;

  for (let i = 0; i + windowSize < features.length; i++) {
    X.push(features.slice(i, i + windowSize));

    // close_norm is feature index 0
    const closeNormCurr = features[i + windowSize - 1][0];
    const closeNormNext = features[i + windowSize][0];

    // Binary classification label: did price go UP?
    y.push(closeNormNext > closeNormCurr ? 1 : 0);

    // Regression label: approximate % return from descaled close prices, clipped to ±20%
    // Matches server-side build-features.py: pct_return = ((next - curr) / curr).clip(-0.20, 0.20)
    if (priceRange > 0) {
      const closeCurr = closeNormCurr * priceRange + priceMin;
      const closeNext = closeNormNext * priceRange + priceMin;
      const pct = closeCurr > 0 ? (closeNext - closeCurr) / closeCurr : 0;
      yReg.push(Math.max(-0.20, Math.min(0.20, pct)));
    } else {
      yReg.push(0);
    }
  }

  return { X, y, yReg };
}
