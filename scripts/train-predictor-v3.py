"""Predictor v3 — 10-year retraining on day-to-day OHLCV diffs.

Reads data/historical/<sector>.json (rebuilt from Stooq, 10y of candles per ticker),
builds day-to-day diff features, trains a stacked ensemble of
HistGradientBoostingClassifier (5 seeds) + HistGradientBoostingRegressor for
next-day return, with isotonic probability calibration.

Walk-forward split:
  train  : candles up to 2023-12-31
  val    : 2024 (used for early-stop / calibration / meta-learner fit)
  test   : 2025-01-01 onward (held out)

Outputs:
  models/v3/predictor/clf_seed_<s>.joblib           # base classifiers
  models/v3/predictor/reg.joblib                    # return regressor
  models/v3/predictor/calibrator.joblib             # isotonic on val
  models/v3/predictor/meta.joblib                   # logistic stack on val
  models/v3/predictor/feature_columns.json
  models/v3/predictor/metadata.json
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    roc_auc_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    brier_score_loss,
)

REPO = Path(__file__).resolve().parents[1]
HIST = REPO / "data" / "historical"
OUT = REPO / "models" / "v3" / "predictor"

sys.path.insert(0, str(REPO / "scripts"))
from overlay_features import attach_all_overlays, OVERLAY_FEATURE_COLS  # noqa: E402

TRAIN_END = "2023-12-31"
VAL_END = "2024-12-31"

FEATURE_COLS: list[str] = []  # populated after build


def build_features_for_ticker(symbol: str, sector: str, candles: list[dict]) -> pd.DataFrame | None:
    if len(candles) < 60:
        return None
    df = pd.DataFrame(candles)
    if not {"date", "open", "high", "low", "close", "volume"}.issubset(df.columns):
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < 60:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"].fillna(0.0)

    ret1 = close.pct_change()
    # Day-to-day diffs (the requested core)
    df["ret_1"] = ret1
    df["ret_2"] = close.pct_change(2)
    df["ret_5"] = close.pct_change(5)
    df["ret_10"] = close.pct_change(10)
    df["ret_20"] = close.pct_change(20)
    df["log_ret_1"] = np.log(close).diff()

    # Rolling stats on daily returns
    df["vol_5"] = ret1.rolling(5).std()
    df["vol_20"] = ret1.rolling(20).std()
    df["mean_5"] = ret1.rolling(5).mean()
    df["mean_20"] = ret1.rolling(20).mean()
    df["skew_20"] = ret1.rolling(20).skew()
    df["kurt_20"] = ret1.rolling(20).kurt()

    # Momentum / trend
    sma_10 = close.rolling(10).mean()
    sma_50 = close.rolling(50).mean()
    df["sma_ratio_10_50"] = sma_10 / sma_50 - 1.0
    df["price_over_sma20"] = close / close.rolling(20).mean() - 1.0
    df["price_over_sma50"] = close / sma_50 - 1.0

    # RSI(14)
    delta = close.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    rs = up / dn.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    df["macd"] = macd / close
    df["macd_hist"] = (macd - macd_sig) / close

    # ATR(14) ratio
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr_14_ratio"] = tr.rolling(14).mean() / close

    # High/low range ratio
    df["hl_range"] = (high - low) / close
    df["close_pos_in_range"] = (close - low) / (high - low).replace(0, np.nan)

    # Volume diffs
    vlog = np.log1p(vol)
    df["vol_chg_1"] = vlog.diff()
    df["vol_chg_5"] = vlog.diff(5)
    df["vol_z_20"] = (vlog - vlog.rolling(20).mean()) / vlog.rolling(20).std()

    # Drawdown vs 50-day high
    df["dd_50"] = close / close.rolling(50).max() - 1.0

    # Labels: next-day direction + next-day return
    fwd_ret = close.shift(-1) / close - 1.0
    df["y_ret"] = fwd_ret
    df["y_up"] = (fwd_ret > 0).astype("int8")

    df["symbol"] = symbol
    df["sector"] = sector
    df = df.dropna().reset_index(drop=True)
    if df.empty:
        return None
    return df


def load_all(min_candles: int = 200, sample_tickers: int | None = None) -> pd.DataFrame:
    files = sorted(HIST.glob("*.json"))
    frames: list[pd.DataFrame] = []
    total_tickers = 0
    accepted_tickers = 0
    t0 = time.time()
    for fp in files:
        if fp.name in {"manifest.json", "multiyear-coverage.json", "stooq-bulk-coverage.json"}:
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[skip] {fp.name}: {e}", flush=True)
            continue
        sector = data.get("sector") or fp.stem
        stocks = data.get("stocks") or {}
        if not isinstance(stocks, dict):
            continue
        items = list(stocks.items())
        if sample_tickers:
            items = items[:sample_tickers]
        for sym, payload in items:
            total_tickers += 1
            candles = (payload or {}).get("candles") or []
            if len(candles) < min_candles:
                continue
            d = build_features_for_ticker(sym, sector, candles)
            if d is None or len(d) < 30:
                continue
            frames.append(d)
            accepted_tickers += 1
        print(f"[load] {fp.name}: tickers_seen={total_tickers} accepted={accepted_tickers} elapsed={time.time()-t0:.1f}s", flush=True)
    if not frames:
        raise SystemExit("no data loaded")
    out = pd.concat(frames, ignore_index=True)
    print(f"[load] attaching overlays ({len(OVERLAY_FEATURE_COLS)} cols)…", flush=True)
    out = attach_all_overlays(out, date_col="date")
    print(f"[load] total_rows={len(out):,} tickers={accepted_tickers}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-candles", type=int, default=300)
    ap.add_argument("--sample-tickers", type=int, default=0, help="limit per sector for smoke testing")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--max-iter", type=int, default=400)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--early-stopping-rounds", type=int, default=30)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    df = load_all(min_candles=args.min_candles, sample_tickers=args.sample_tickers or None)

    drop_cols = {"date", "symbol", "sector", "y_ret", "y_up", "open", "high", "low", "close", "volume"}
    feature_cols = [c for c in df.columns if c not in drop_cols]
    global FEATURE_COLS
    FEATURE_COLS = feature_cols
    print(f"[features] {len(feature_cols)} cols: {feature_cols}", flush=True)

    train_mask = df["date"] <= TRAIN_END
    val_mask = (df["date"] > TRAIN_END) & (df["date"] <= VAL_END)
    test_mask = df["date"] > VAL_END

    Xtr, ytr_cls, ytr_reg = df.loc[train_mask, feature_cols].to_numpy(dtype=np.float32), df.loc[train_mask, "y_up"].to_numpy(), df.loc[train_mask, "y_ret"].to_numpy(dtype=np.float32)
    Xva, yva_cls, yva_reg = df.loc[val_mask, feature_cols].to_numpy(dtype=np.float32), df.loc[val_mask, "y_up"].to_numpy(), df.loc[val_mask, "y_ret"].to_numpy(dtype=np.float32)
    Xte, yte_cls, yte_reg = df.loc[test_mask, feature_cols].to_numpy(dtype=np.float32), df.loc[test_mask, "y_up"].to_numpy(), df.loc[test_mask, "y_ret"].to_numpy(dtype=np.float32)
    print(f"[split] train={len(Xtr):,} val={len(Xva):,} test={len(Xte):,}", flush=True)
    if len(Xtr) == 0 or len(Xva) == 0 or len(Xte) == 0:
        raise SystemExit("empty split; check date ranges vs data")

    # Base classifiers (5 seeds)
    base_val_probas = []
    base_test_probas = []
    classifiers = []
    for seed in range(args.seeds):
        t = time.time()
        clf = HistGradientBoostingClassifier(
            loss="log_loss",
            learning_rate=args.learning_rate,
            max_iter=args.max_iter,
            max_depth=args.max_depth,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=args.early_stopping_rounds,
            random_state=seed,
        )
        clf.fit(Xtr, ytr_cls)
        pv = clf.predict_proba(Xva)[:, 1]
        pt = clf.predict_proba(Xte)[:, 1]
        base_val_probas.append(pv)
        base_test_probas.append(pt)
        classifiers.append(clf)
        joblib.dump(clf, OUT / f"clf_seed_{seed}.joblib")
        print(f"[clf seed={seed}] iters={clf.n_iter_} val_auc={roc_auc_score(yva_cls, pv):.4f} val_acc={accuracy_score(yva_cls, pv>0.5):.4f} {time.time()-t:.1f}s", flush=True)

    val_stack = np.column_stack(base_val_probas)
    test_stack = np.column_stack(base_test_probas)

    # Meta-learner on val
    meta = LogisticRegression(C=1.0, max_iter=200)
    meta.fit(val_stack, yva_cls)
    val_proba_meta = meta.predict_proba(val_stack)[:, 1]
    test_proba_meta = meta.predict_proba(test_stack)[:, 1]
    joblib.dump(meta, OUT / "meta.joblib")

    # Isotonic calibration on val meta-probs
    cal = IsotonicRegression(out_of_bounds="clip")
    cal.fit(val_proba_meta, yva_cls)
    val_proba_cal = cal.transform(val_proba_meta)
    test_proba_cal = cal.transform(test_proba_meta)
    joblib.dump(cal, OUT / "calibrator.joblib")

    # Return regressor
    t = time.time()
    reg = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=args.learning_rate,
        max_iter=args.max_iter,
        max_depth=args.max_depth,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=args.early_stopping_rounds,
        random_state=0,
    )
    reg.fit(Xtr, ytr_reg)
    test_pred_ret = reg.predict(Xte)
    val_pred_ret = reg.predict(Xva)
    joblib.dump(reg, OUT / "reg.joblib")
    print(f"[reg] iters={reg.n_iter_} val_mae={mean_absolute_error(yva_reg, val_pred_ret):.5f} test_mae={mean_absolute_error(yte_reg, test_pred_ret):.5f} {time.time()-t:.1f}s", flush=True)

    # Final metrics on TEST
    metrics = {
        "test": {
            "n": int(len(yte_cls)),
            "accuracy": float(accuracy_score(yte_cls, test_proba_cal > 0.5)),
            "auc": float(roc_auc_score(yte_cls, test_proba_cal)),
            "f1": float(f1_score(yte_cls, test_proba_cal > 0.5)),
            "log_loss": float(log_loss(yte_cls, np.clip(test_proba_cal, 1e-6, 1 - 1e-6))),
            "brier": float(brier_score_loss(yte_cls, test_proba_cal)),
            "reg_mae": float(mean_absolute_error(yte_reg, test_pred_ret)),
        },
        "val": {
            "n": int(len(yva_cls)),
            "accuracy": float(accuracy_score(yva_cls, val_proba_cal > 0.5)),
            "auc": float(roc_auc_score(yva_cls, val_proba_cal)),
            "f1": float(f1_score(yva_cls, val_proba_cal > 0.5)),
            "reg_mae": float(mean_absolute_error(yva_reg, val_pred_ret)),
        },
    }

    meta_doc = {
        "version": "3.0.0-v3",
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "architecture": "HistGradientBoosting x5 (stacked, isotonic-calibrated) + HGBR return head",
        "library": "scikit-learn",
        "feature_count": len(feature_cols),
        "feature_kind": "day-to-day OHLCV diffs + regime/congress/insider overlays",
        "overlay_features": OVERLAY_FEATURE_COLS,
        "train_window": {"end": TRAIN_END, "rows": int(len(Xtr))},
        "val_window": {"start": TRAIN_END, "end": VAL_END, "rows": int(len(Xva))},
        "test_window": {"start": VAL_END, "rows": int(len(Xte))},
        "metrics": metrics,
        "hyperparameters": {
            "seeds": args.seeds,
            "max_iter": args.max_iter,
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
            "early_stopping_rounds": args.early_stopping_rounds,
        },
    }
    with open(OUT / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_doc, f, indent=2)
    with open(OUT / "feature_columns.json", "w", encoding="utf-8") as f:
        json.dump(feature_cols, f, indent=2)

    # Export test predictions so the investor can train without re-inference
    test_out = df.loc[test_mask, ["date", "symbol", "sector", "y_up", "y_ret"]].copy()
    test_out["pred_proba_up"] = test_proba_cal
    test_out["pred_ret"] = test_pred_ret
    val_out = df.loc[val_mask, ["date", "symbol", "sector", "y_up", "y_ret"]].copy()
    val_out["pred_proba_up"] = val_proba_cal
    val_out["pred_ret"] = val_pred_ret
    Path(REPO / "data" / "predictions_v3").mkdir(parents=True, exist_ok=True)
    test_out.to_csv(REPO / "data" / "predictions_v3" / "test.csv", index=False)
    val_out.to_csv(REPO / "data" / "predictions_v3" / "val.csv", index=False)

    print("\n=== TEST METRICS ===")
    print(json.dumps(metrics["test"], indent=2))
    print(f"\n[done] artifacts in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
