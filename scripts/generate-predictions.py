"""
generate-predictions.py — Daily Prediction Generation

Loads the trained V3 ensemble model from models/v2/ and the latest historical data
from data/historical/, computes features using the same pipeline as
build-features.py (including Phase A/B/C signals), and generates UP/DOWN
predictions for all tickers.

Phase D enhancements:
  - Ensemble of 5 models: ensembleStd field (uncertainty)
  - Platt-calibrated probability
  - Expected Value (EV) = calibrated_prob × predictedReturn − (1−calibrated_prob) × |predictedReturn|

Output: data/predictions/YYYY-MM-DD.json

Run daily after market close (see .github/workflows/generate-predictions.yml).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import numpy as np
from public_data_history import load_macro_snapshots, load_ticker_snapshots, resolve_macro_features, resolve_ticker_record

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT       = os.path.join(SCRIPT_DIR, "..")
HISTORICAL_DIR  = os.path.join(REPO_ROOT, "data", "historical")
FEATURES_DIR    = os.path.join(REPO_ROOT, "data", "features")
MODELS_V2_DIR   = os.path.join(REPO_ROOT, "models", "v2")
PREDICTIONS_DIR = os.path.join(REPO_ROOT, "data", "predictions")
SENTIMENT_DIR   = os.path.join(REPO_ROOT, "data", "sentiment")
FUNDAMENTALS_DIR = os.path.join(REPO_ROOT, "data", "fundamentals")
MACRO_DIR       = os.path.join(REPO_ROOT, "data", "macro")

# ---------------------------------------------------------------------------
# Constants (resolved dynamically from scaling_params.json)
# ---------------------------------------------------------------------------

TIMESTEPS     = 30
FEATURE_COUNT = 44   # updated value; overridden at runtime from scaling_params
MIN_CANDLES   = 60   # minimum candles needed after indicator warmup
MAX_PREDICTION_TICKERS = int(os.getenv("MAX_PREDICTION_TICKERS", "0") or "0")

# Feature names must match build-features.py FEATURE_NAMES
FEATURE_NAMES = [
    "close_norm", "open_norm", "high_norm", "low_norm", "volume_norm",
    "rsi_14", "macd_line", "macd_signal", "macd_hist",
    "sma5_rel", "sma20_rel", "sma50_rel",
    "ema12_rel", "ema26_rel",
    "bb_upper_rel", "bb_lower_rel", "bb_width",
    "atr14_norm", "obv_norm",
    "stoch_k", "stoch_d",
    "roc10", "momentum5", "volatility30", "volume_ratio",
    "dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri",
    "month_sin", "month_cos",
    # Phase A
    "news_sentiment", "reddit_sentiment", "sec_filings_norm",
    # Phase B
    "insider_buy_ratio", "earnings_days_norm", "earnings_surprise", "put_call_ratio_norm",
    # Phase C
    "macro_vix_norm",
    "macro_spread_norm",
    "macro_fed_norm",
    "macro_sentiment_norm",
    "macro_claims_norm",
]
assert len(FEATURE_NAMES) == FEATURE_COUNT

# Cache of the feature names the current model was trained on.
# Loaded lazily from models/v2/metadata.json on first call to _get_model_feature_names().
_MODEL_FEATURE_NAMES: list[str] | None = None


def _get_model_feature_names() -> list[str]:
    """
    Return the feature names (in order) that the current saved model expects.
    Reads models/v2/metadata.json once and caches the result.

    Falls back to the 40-feature FEATURE_NAMES list when no metadata is found,
    so the function is safe to call even before a model has been trained.

    Old models (pre Phase A/B/C) used a single "sentiment" feature (a technical
    proxy).  New 40-feature models use "news_sentiment", "reddit_sentiment", etc.
    Both naming schemes are handled in _build_features_for_candles via an alias.
    """
    global _MODEL_FEATURE_NAMES
    if _MODEL_FEATURE_NAMES is not None:
        return _MODEL_FEATURE_NAMES
    metadata_path = os.path.join(MODELS_V2_DIR, "metadata.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path) as f:
                meta = json.load(f)
            fn = meta.get("featureNames", [])
            if fn:
                _MODEL_FEATURE_NAMES = fn
                print(
                    f"[generate-predictions] Model expects {len(fn)} features "
                    f"(e.g. {fn[:2]}…{fn[-2:]})"
                )
                return _MODEL_FEATURE_NAMES
        except Exception as e:
            print(f"[generate-predictions] WARN: could not read model metadata: {e}")
    _MODEL_FEATURE_NAMES = FEATURE_NAMES
    return _MODEL_FEATURE_NAMES

# ---------------------------------------------------------------------------
# Re-use feature computation from build-features.py
# ---------------------------------------------------------------------------

def _load_supplementary_data() -> tuple[list[tuple[date, dict[str, dict]]], list[tuple[date, dict[str, dict]]], list[tuple[date, dict]]]:
    """
    Load Phase A/B/C supplementary data: sentiment, fundamentals, macro.
    Returns (sentiment_by_ticker, fundamentals_by_ticker, macro_norm_features).
    """
    sentiment_history = load_ticker_snapshots(SENTIMENT_DIR)
    fundamentals_history = load_ticker_snapshots(FUNDAMENTALS_DIR)
    macro_history = load_macro_snapshots(MACRO_DIR)

    print(f"[generate-predictions] Loaded {len(sentiment_history)} dated sentiment snapshot(s)")
    print(f"[generate-predictions] Loaded {len(fundamentals_history)} dated fundamentals snapshot(s)")
    print(f"[generate-predictions] Loaded {len(macro_history)} dated macro snapshot(s)")

    return sentiment_history, fundamentals_history, macro_history


def _build_features_for_candles(
    candles: list,
    ticker: str = "",
    sentiment_history: list[tuple[date, dict[str, dict]]] | None = None,
    fundamentals_history: list[tuple[date, dict[str, dict]]] | None = None,
    macro_history: list[tuple[date, dict]] | None = None,
) -> list[list[float]] | None:
    """
    Compute the 40-feature matrix for a list of OHLCV candle dicts.
    Returns a list of feature rows (each a list of FEATURE_COUNT floats), or None if
    there isn't enough data.

    This function mirrors the logic in build-features.py so that
    inference features exactly match training features.
    """
    try:
        import ta
        import pandas as pd
    except ImportError:
        print("ERROR: 'ta' and 'pandas' packages required. Run: pip install ta pandas")
        sys.exit(1)

    if len(candles) < MIN_CANDLES:
        return None

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    close   = df["close"].astype(float)
    open_   = df["open"].astype(float)
    high    = df["high"].astype(float)
    low     = df["low"].astype(float)
    volume  = df["volume"].astype(float)

    def minmax(s):
        mn, mx = s.min(), s.max()
        rng = mx - mn
        return ((s - mn) / rng) if rng != 0 else pd.Series(0.5, index=s.index)

    def safe_div(a, b):
        return a.div(b.replace(0, float("nan"))).fillna(0)

    close_norm  = minmax(close)
    open_norm   = minmax(open_)
    high_norm   = minmax(high)
    low_norm    = minmax(low)
    volume_norm = minmax(volume)

    rsi_14   = ta.momentum.RSIIndicator(close=close, window=14).rsi() / 100.0
    macd_obj = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line   = safe_div(macd_obj.macd(), close)
    macd_signal = safe_div(macd_obj.macd_signal(), close)
    macd_hist   = safe_div(macd_obj.macd_diff(), close)

    sma5  = ta.trend.SMAIndicator(close=close, window=5).sma_indicator()
    sma20 = ta.trend.SMAIndicator(close=close, window=20).sma_indicator()
    sma50 = ta.trend.SMAIndicator(close=close, window=50).sma_indicator()
    sma5_rel  = safe_div(sma5  - close, close)
    sma20_rel = safe_div(sma20 - close, close)
    sma50_rel = safe_div(sma50 - close, close)

    ema12 = ta.trend.EMAIndicator(close=close, window=12).ema_indicator()
    ema26 = ta.trend.EMAIndicator(close=close, window=26).ema_indicator()
    ema12_rel = safe_div(ema12 - close, close)
    ema26_rel = safe_div(ema26 - close, close)

    bb         = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_upper_rel = safe_div(bb.bollinger_hband() - close, close)
    bb_lower_rel = safe_div(close - bb.bollinger_lband(), close)
    bb_width     = safe_div(bb.bollinger_hband() - bb.bollinger_lband(), close)

    atr14_norm = safe_div(
        ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range(),
        close
    )

    obv_raw = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    obv_min, obv_max = obv_raw.min(), obv_raw.max()
    obv_norm = ((obv_raw - obv_min) / (obv_max - obv_min)) if obv_max != obv_min else pd.Series(0.5, index=obv_raw.index)

    stoch = ta.momentum.StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    stoch_k = stoch.stoch() / 100.0
    stoch_d = stoch.stoch_signal() / 100.0

    roc10     = ta.momentum.ROCIndicator(close=close, window=10).roc() / 100.0
    momentum5 = safe_div(close - close.shift(5), close.shift(5))

    daily_returns = close.pct_change()
    volatility30  = daily_returns.rolling(30).std() * math.sqrt(252)

    vol_sma20     = volume.rolling(20).mean()
    volume_ratio  = safe_div(volume, vol_sma20)

    dow       = df["date"].dt.dayofweek
    dow_mon   = (dow == 0).astype(float)
    dow_tue   = (dow == 1).astype(float)
    dow_wed   = (dow == 2).astype(float)
    dow_thu   = (dow == 3).astype(float)
    dow_fri   = (dow == 4).astype(float)

    month     = df["date"].dt.month
    month_sin = np.sin(2 * math.pi * month / 12)
    month_cos = np.cos(2 * math.pi * month / 12)

    # --- Phase A: sentiment (real snapshot, no technical proxy fallback) ---
    n_rows = len(df)
    target_dt = df["date"].iloc[-1].date()
    news_sentiment_col   = pd.Series(0.0, index=df.index)
    reddit_sentiment_col = pd.Series(0.0, index=df.index)
    sec_filings_col      = pd.Series(0.0, index=df.index)

    if sentiment_history:
        sd = resolve_ticker_record(sentiment_history, ticker, target_dt, max_age_days=14)
    else:
        sd = None
    if sd is not None:
        last_idx = n_rows - 1
        news_sentiment_col.iloc[last_idx] = float(sd.get("news_sentiment", 0.0) or 0.0)
        reddit_sentiment_col.iloc[last_idx] = float(sd.get("reddit_sentiment", 0.0) or 0.0)
        raw_filings = float(sd.get("sec_filings_7d", 0) or 0)
        sec_filings_col.iloc[last_idx] = min(1.0, raw_filings / 10.0)

    # --- Phase B: fundamentals (static snapshot) ---
    insider_col   = pd.Series(0.5, index=df.index)
    earn_days_col = pd.Series(1.0, index=df.index)
    earn_surp_col = pd.Series(0.0, index=df.index)
    pcr_col       = pd.Series(0.5, index=df.index)

    if fundamentals_history:
        fd = resolve_ticker_record(fundamentals_history, ticker, target_dt, max_age_days=14)
    else:
        fd = None
    if fd is not None:
        ibr = float(fd.get("insider_buy_ratio_30d", 0.5) or 0.5)
        insider_col.iloc[:] = max(0.0, min(1.0, ibr))
        edd = float(fd.get("earnings_days_to", 60) or 60)
        earn_days_col.iloc[:] = max(0.0, min(1.0, 1.0 - edd / 60.0))
        esp = float(fd.get("earnings_surprise_prev", 0.0) or 0.0)
        earn_surp_col.iloc[:] = max(-0.5, min(0.5, esp))
        pcr = float(fd.get("put_call_ratio", 1.0) or 1.0)
        pcr_col.iloc[:] = max(0.0, min(1.0, pcr / 5.0))

    # --- Phase C: macro (scalar set) ---
    macro_defaults = {
        "macro_vix_norm": 0.3,
        "macro_spread_norm": 0.5,
        "macro_fed_norm": 0.5,
        "macro_sentiment_norm": 0.5,
        "macro_claims_norm": 0.5,
    }
    macro_vix = macro_defaults["macro_vix_norm"]
    macro_spread = macro_defaults["macro_spread_norm"]
    macro_fed = macro_defaults["macro_fed_norm"]
    macro_sent = macro_defaults["macro_sentiment_norm"]
    macro_claims = macro_defaults["macro_claims_norm"]
    if macro_history:
        md = resolve_macro_features(macro_history, target_dt, max_age_days=14)
        if md is not None:
            macro_vix = float(md.get("macro_vix_norm", macro_defaults["macro_vix_norm"]) or macro_defaults["macro_vix_norm"])
            macro_spread = float(md.get("macro_spread_norm", macro_defaults["macro_spread_norm"]) or macro_defaults["macro_spread_norm"])
            macro_fed = float(md.get("macro_fed_norm", macro_defaults["macro_fed_norm"]) or macro_defaults["macro_fed_norm"])
            macro_sent = float(md.get("macro_sentiment_norm", macro_defaults["macro_sentiment_norm"]) or macro_defaults["macro_sentiment_norm"])
            macro_claims = float(md.get("macro_claims_norm", macro_defaults["macro_claims_norm"]) or macro_defaults["macro_claims_norm"])
    macro_vix_col = pd.Series(macro_vix, index=df.index)
    macro_spread_col = pd.Series(macro_spread, index=df.index)
    macro_fed_col = pd.Series(macro_fed, index=df.index)
    macro_sent_col = pd.Series(macro_sent, index=df.index)
    macro_claims_col = pd.Series(macro_claims, index=df.index)

    feature_df = pd.DataFrame({
        "close_norm":          close_norm,    "open_norm":       open_norm,
        "high_norm":           high_norm,     "low_norm":        low_norm,
        "volume_norm":         volume_norm,   "rsi_14":          rsi_14,
        "macd_line":           macd_line,     "macd_signal":     macd_signal,
        "macd_hist":           macd_hist,     "sma5_rel":        sma5_rel,
        "sma20_rel":           sma20_rel,     "sma50_rel":       sma50_rel,
        "ema12_rel":           ema12_rel,     "ema26_rel":       ema26_rel,
        "bb_upper_rel":        bb_upper_rel,  "bb_lower_rel":    bb_lower_rel,
        "bb_width":            bb_width,      "atr14_norm":      atr14_norm,
        "obv_norm":            obv_norm,      "stoch_k":         stoch_k,
        "stoch_d":             stoch_d,       "roc10":           roc10,
        "momentum5":           momentum5,     "volatility30":    volatility30,
        "volume_ratio":        volume_ratio,
        "dow_mon":             dow_mon,       "dow_tue":         dow_tue,
        "dow_wed":             dow_wed,       "dow_thu":         dow_thu,
        "dow_fri":             dow_fri,       "month_sin":       month_sin,
        "month_cos":           month_cos,
        # Phase A
        "news_sentiment":      news_sentiment_col,
        "reddit_sentiment":    reddit_sentiment_col,
        "sec_filings_norm":    sec_filings_col,
        # Phase B
        "insider_buy_ratio":   insider_col,
        "earnings_days_norm":  earn_days_col,
        "earnings_surprise":   earn_surp_col,
        "put_call_ratio_norm": pcr_col,
        # Phase C
        "macro_vix_norm":      macro_vix_col,
        "macro_spread_norm":   macro_spread_col,
        "macro_fed_norm":      macro_fed_col,
        "macro_sentiment_norm": macro_sent_col,
        "macro_claims_norm":   macro_claims_col,
        # Legacy alias: old models (pre Phase A/B/C) used a single "sentiment" feature
        # which was derived from a technical proxy. We now avoid synthetic proxy
        # and keep this neutral unless present in model feature names.
        "sentiment":           pd.Series(0.0, index=df.index),
    })

    import numpy as _np
    feature_df.replace([_np.inf, -_np.inf], _np.nan, inplace=True)
    feature_df.dropna(inplace=True)

    if len(feature_df) < TIMESTEPS:
        return None

    # Select and order columns to exactly match what the trained model expects.
    # For any feature the model needs that isn't in our DataFrame, use 0.0.
    model_features = _get_model_feature_names()
    result_cols = []
    missing_features = []
    for name in model_features:
        if name in feature_df.columns:
            result_cols.append(feature_df[name])
        else:
            missing_features.append(name)
            result_cols.append(pd.Series(0.0, index=feature_df.index, name=name))
    if missing_features:
        print(
            f"[generate-predictions] WARN: {len(missing_features)} feature(s) expected by the model "
            f"are not in the computed feature set and will be filled with 0.0: {missing_features}"
        )
    result_df = pd.concat(result_cols, axis=1)
    result_df.columns = model_features

    return result_df.values.tolist()


# ---------------------------------------------------------------------------
# Model loading and inference
# ---------------------------------------------------------------------------

def load_platt_params() -> tuple[float, float]:
    """Load Platt calibration parameters from models/v2/platt_params.json."""
    platt_path = os.path.join(MODELS_V2_DIR, "platt_params.json")
    if os.path.exists(platt_path):
        try:
            with open(platt_path) as f:
                p = json.load(f)
            return float(p.get("a", 1.0)), float(p.get("b", 0.0))
        except Exception:
            pass
    return 1.0, 0.0


def apply_platt(raw_prob: float, platt_a: float, platt_b: float) -> float:
    """Apply Platt scaling to convert raw sigmoid output to calibrated probability."""
    z = platt_a * raw_prob + platt_b
    return 1.0 / (1.0 + math.exp(-z))


def load_model():
    """
    Load the V3 TensorFlow model for server-side inference.
    Attempts to load all ENSEMBLE_SIZE members from models/v2/ensemble/.
    Falls back to single model at models/v2/ if ensemble not found.
    """
    # Sklearn fallback model (TensorFlow-free path)
    sklearn_path = os.path.join(MODELS_V2_DIR, "sklearn_model.joblib")
    if os.path.exists(sklearn_path):
        try:
            import joblib

            bundle = joblib.load(sklearn_path)
            if isinstance(bundle, dict) and bundle.get("classifier") is not None:
                print(f"[generate-predictions] Loaded sklearn fallback model from {sklearn_path}")
                return {
                    "backend": "sklearn",
                    "classifier": bundle.get("classifier"),
                    "regressor": bundle.get("regressor"),
                    "timesteps": int(bundle.get("timesteps", TIMESTEPS)),
                }
        except Exception as e:
            print(f"[generate-predictions] WARN: could not load sklearn fallback model: {e}")

    ENSEMBLE_SIZE = 5
    ensemble_dir = os.path.join(MODELS_V2_DIR, "ensemble")
    ensemble_models = []

    # Try loading ensemble members
    if os.path.isdir(ensemble_dir):
        for i in range(ENSEMBLE_SIZE):
            member_dir  = os.path.join(ensemble_dir, f"model_{i}")
            keras_path  = os.path.join(member_dir, "keras_model.keras")
            if os.path.exists(keras_path):
                try:
                    import tensorflow as tf
                    m = tf.keras.models.load_model(keras_path)
                    ensemble_models.append(m)
                    print(f"[generate-predictions] Loaded ensemble member {i} from {keras_path}")
                except Exception as e:
                    print(f"[generate-predictions] WARN: could not load ensemble member {i}: {e}")

    if ensemble_models:
        print(f"[generate-predictions] Ensemble loaded: {len(ensemble_models)} models")
        return {"backend": "tensorflow", "models": ensemble_models}

    # Fall back to single model
    model_path = os.path.join(MODELS_V2_DIR, "saved_model")
    keras_path = os.path.join(MODELS_V2_DIR, "keras_model.keras")
    h5_path    = os.path.join(MODELS_V2_DIR, "model.h5")

    for path in [keras_path, h5_path, model_path]:
        if os.path.exists(path):
            try:
                import tensorflow as tf
                model = tf.keras.models.load_model(path)
                print(f"[generate-predictions] Loaded single model from {path}")
                return {"backend": "tensorflow", "models": [model]}
            except Exception as e:
                print(f"[generate-predictions] Could not load {path}: {e}")

    print("[generate-predictions] ERROR: No trained model found in models/v2/")
    print("  Run scripts/train-model.py first.")
    sys.exit(1)


def load_decision_threshold(default: float = 0.5) -> float:
    """Load adaptive classification threshold from model metadata."""
    metadata_path = os.path.join(MODELS_V2_DIR, "metadata.json")
    if not os.path.exists(metadata_path):
        return default
    try:
        with open(metadata_path) as f:
            meta = json.load(f)
        t = ((meta.get("trainingStats") or {}).get("decisionThreshold"))
        if t is None:
            return default
        t = float(t)
        if 0.01 <= t <= 0.99:
            return t
    except Exception:
        pass
    return default


def predict_ticker(model_bundle: dict, features: list[list[float]],
                   platt_a: float = 1.0, platt_b: float = 0.0,
                   decision_threshold: float = 0.5) -> dict:
    """
    Run ensemble inference on the last TIMESTEPS rows of a feature matrix.

    Returns probability (Platt-calibrated), direction, confidence,
    ensembleStd (uncertainty), predictedReturn (when available), and EV.

    EV = calibrated_prob × |predictedReturn| − (1 − calibrated_prob) × |predictedReturn|
       = (2 × calibrated_prob − 1) × |predictedReturn|
    (A positive EV means the expected gain outweighs the expected loss.)
    """
    backend = (model_bundle or {}).get("backend", "tensorflow")

    raw_probs = []
    predicted_returns = []

    if backend == "sklearn":
        clf = model_bundle.get("classifier")
        reg = model_bundle.get("regressor")
        if clf is None:
            raise RuntimeError("sklearn classifier is missing from loaded model bundle")
        window_flat = np.array(features[-TIMESTEPS:], dtype=np.float32).reshape(1, -1)
        raw_probs.append(float(clf.predict_proba(window_flat)[0][1]))
        if reg is not None:
            predicted_returns.append(float(reg.predict(window_flat)[0]))
    else:
        models = model_bundle.get("models", [])
        if not models:
            raise RuntimeError("tensorflow model list is empty")
        window = np.array([features[-TIMESTEPS:]], dtype=np.float32)   # (1, 30, F)
        for model in models:
            outputs = model.predict(window, verbose=0)
            if isinstance(outputs, list) and len(outputs) == 2:
                raw_probs.append(float(outputs[0][0][0]))
                predicted_returns.append(float(outputs[1][0][0]))
            else:
                raw_probs.append(float(outputs[0][0]))

    # Ensemble average
    raw_prob_mean = float(np.mean(raw_probs))
    raw_prob_std  = float(np.std(raw_probs)) if len(raw_probs) > 1 else 0.0

    # Platt calibration
    calibrated_prob = apply_platt(raw_prob_mean, platt_a, platt_b)
    calibrated_prob = max(0.001, min(0.999, calibrated_prob))

    direction  = "UP" if calibrated_prob >= decision_threshold else "DOWN"
    confidence = round(abs(calibrated_prob - decision_threshold) * 2, 4)
    confidence = max(0.0, min(1.0, confidence))

    result = {
        "probability":   round(calibrated_prob, 4),
        "direction":     direction,
        "confidence":    confidence,
        "ensembleStd":   round(raw_prob_std, 4),
        "decisionThreshold": round(decision_threshold, 4),
    }

    if predicted_returns:
        pred_return = float(np.mean(predicted_returns))
        result["predictedReturn"] = round(pred_return, 4)
        # EV: positive when calibrated_prob > 0.5 AND predicted_return > 0
        ev = (2 * calibrated_prob - 1) * abs(pred_return)
        result["ev"] = round(ev, 6)

    return result


# ---------------------------------------------------------------------------
# Historical data loading
# ---------------------------------------------------------------------------

def load_historical_candles(sector_file: str) -> dict[str, list]:
    """Load candles for every ticker in a sector JSON file."""
    with open(sector_file) as f:
        data = json.load(f)
    result = {}
    for ticker, info in data.get("stocks", {}).items():
        candles = info.get("candles", [])
        if candles:
            result[ticker] = candles
    return result


# ---------------------------------------------------------------------------
# Next trading day helper
# ---------------------------------------------------------------------------

def next_trading_day(from_date: date) -> str:
    """Return the next weekday after from_date as YYYY-MM-DD."""
    d = from_date + timedelta(days=1)
    while d.weekday() >= 5:   # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d.isoformat()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)

    today_str = date.today().isoformat()
    prediction_date = next_trading_day(date.today())

    out_path = os.path.join(PREDICTIONS_DIR, f"{today_str}.json")

    # Load ensemble models
    model_bundle = load_model()

    # Load Platt calibration parameters
    platt_a, platt_b = load_platt_params()
    print(f"[generate-predictions] Platt params: a={platt_a}, b={platt_b}")

    # Load adaptive decision threshold
    decision_threshold = load_decision_threshold(default=0.5)
    print(f"[generate-predictions] Decision threshold: {decision_threshold}")

    # Load supplementary data (Phase A/B/C)
    sentiment_history, fundamentals_history, macro_history = _load_supplementary_data()

    # Load manifest to find sector files
    manifest_path = os.path.join(HISTORICAL_DIR, "manifest.json")
    if not os.path.exists(manifest_path):
        print("[generate-predictions] ERROR: data/historical/manifest.json not found.")
        sys.exit(1)

    sector_files = [
        os.path.join(HISTORICAL_DIR, f)
        for f in os.listdir(HISTORICAL_DIR)
        if f.endswith(".json") and f != "manifest.json"
    ]

    if not sector_files:
        print("[generate-predictions] ERROR: No sector files found in data/historical/")
        sys.exit(1)

    predictions = {}
    total, skipped = 0, 0
    attempted = 0

    if MAX_PREDICTION_TICKERS > 0:
        print(f"[generate-predictions] MAX_PREDICTION_TICKERS={MAX_PREDICTION_TICKERS:,}")
    else:
        print("[generate-predictions] MAX_PREDICTION_TICKERS=0 (processing all tickers)")

    for sector_file in sorted(sector_files):
        sector_name = os.path.basename(sector_file).replace(".json", "")
        print(f"[generate-predictions] Processing {sector_name}…")

        candles_by_ticker = load_historical_candles(sector_file)

        for ticker, candles in candles_by_ticker.items():
            if MAX_PREDICTION_TICKERS > 0 and attempted >= MAX_PREDICTION_TICKERS:
                break
            attempted += 1

            features = _build_features_for_candles(
                candles, ticker=ticker,
                sentiment_history=sentiment_history,
                fundamentals_history=fundamentals_history,
                macro_history=macro_history,
            )
            if features is None or len(features) < TIMESTEPS:
                skipped += 1
                continue

            try:
                result = predict_ticker(
                    model_bundle,
                    features,
                    platt_a=platt_a,
                    platt_b=platt_b,
                    decision_threshold=decision_threshold,
                )
                predictions[ticker] = result
                total += 1
            except Exception as e:
                print(f"  [WARN] {ticker}: prediction failed — {e}")
                skipped += 1

            if attempted % 200 == 0:
                print(
                    f"[generate-predictions] Progress: attempted={attempted:,}, "
                    f"predictions={total:,}, skipped={skipped:,}"
                )

        if MAX_PREDICTION_TICKERS > 0 and attempted >= MAX_PREDICTION_TICKERS:
            break

    # Read model version from metadata.json if available
    model_version = "3.0.0"
    metadata_path = os.path.join(MODELS_V2_DIR, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path) as f:
            meta = json.load(f)
        model_version = meta.get("version", meta.get("modelVersion", model_version))

    # Determine current macro regime
    current_regime = "UNKNOWN"
    regime_path = os.path.join(MACRO_DIR, "current-regime.json")
    if os.path.exists(regime_path):
        try:
            with open(regime_path) as f:
                regime_data = json.load(f)
            current_regime = regime_data.get("regime", "UNKNOWN")
        except Exception:
            pass

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "date":          today_str,
        "predictionFor": prediction_date,
        "generatedAt":   now_utc,
        "modelVersion":  model_version,
        "macroRegime":   current_regime,
        "ensembleSize":  len((model_bundle.get("models") or [])),
        "inferenceBackend": model_bundle.get("backend", "tensorflow"),
        "predictions":   predictions,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print()
    print("=" * 60)
    print("[generate-predictions] DONE")
    print(f"  Date:        {today_str}")
    print(f"  For:         {prediction_date}")
    print(f"  Regime:      {current_regime}")
    print(f"  Backend:     {model_bundle.get('backend', 'tensorflow')}")
    print(f"  Ensemble:    {len((model_bundle.get('models') or []))} models")
    print(f"  Predictions: {total}")
    print(f"  Skipped:     {skipped}")
    print(f"  Attempted:   {attempted}")
    print(f"  Output:      {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
