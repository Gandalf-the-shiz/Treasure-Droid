"""
train-model-sklearn.py

TensorFlow-free fallback training pipeline.
Trains a lightweight sklearn classifier/regressor on the same rolling-window
feature data and writes model artifacts compatible with daily prediction scripts.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(SCRIPT_DIR, "..")
FEATURES_DIR = os.path.join(REPO_ROOT, "data", "features")
MODELS_V2_DIR = os.path.join(REPO_ROOT, "models", "v2")
TRAINING_LOGS_DIR = os.path.join(REPO_ROOT, "data", "training-logs")
TIMESTEPS = 30
MAX_TRAIN_SAMPLES = int(os.getenv("MAX_TRAIN_SAMPLES", "0") or "0")
SKLEARN_LEARNING_RATE = float(os.getenv("SKLEARN_LEARNING_RATE", "0.06") or "0.06")
SKLEARN_MAX_DEPTH = int(os.getenv("SKLEARN_MAX_DEPTH", "6") or "6")
SKLEARN_MAX_ITER = int(os.getenv("SKLEARN_MAX_ITER", "120") or "120")
SKLEARN_MIN_SAMPLES_LEAF = int(os.getenv("SKLEARN_MIN_SAMPLES_LEAF", "60") or "60")
PROFIT_WEIGHT_ALPHA = float(os.getenv("PROFIT_WEIGHT_ALPHA", "1.6") or "1.6")
POS_RETURN_BONUS = float(os.getenv("POS_RETURN_BONUS", "0.75") or "0.75")
THRESHOLD_OBJECTIVE = os.getenv("THRESHOLD_OBJECTIVE", "profit").strip().lower()


def load_feature_files(features_dir: str) -> list[dict]:
    sector_files = [
        f for f in os.listdir(features_dir)
        if f.endswith(".json") and f != "scaling_params.json"
    ]
    if not sector_files:
        print("ERROR: no feature files found")
        sys.exit(1)
    out = []
    for fname in sorted(sector_files):
        with open(os.path.join(features_dir, fname), "r") as fh:
            out.append(json.load(fh))
    return out


def build_windows(features: list[list[float]], labels: list[int], timesteps: int,
                  pct_returns: list[float] | None = None):
    n = len(features)
    if n < timesteps:
        return None, None, None

    X = np.array(features, dtype=np.float32)
    y_cls = np.array(labels, dtype=np.float32)

    num_windows = n - timesteps + 1
    X_windows = np.lib.stride_tricks.as_strided(
        X,
        shape=(num_windows, timesteps, X.shape[1]),
        strides=(X.strides[0], X.strides[0], X.strides[1]),
    ).copy()
    y_cls_windows = y_cls[timesteps - 1 :]

    y_reg_windows = None
    if pct_returns is not None:
        y_reg = np.array(pct_returns, dtype=np.float32)
        y_reg_windows = y_reg[timesteps - 1 :]

    return X_windows, y_cls_windows, y_reg_windows


def collect_data(sectors: list[dict], max_samples: int):
    X_all, y_cls_all, y_reg_all = [], [], []
    feature_names = []
    total_windows = 0
    ticker_count = 0
    capped = max_samples > 0

    for sector_data in sectors:
        if not feature_names:
            feature_names = sector_data.get("featureNames", [])
        for _, td in (sector_data.get("tickers", {}) or {}).items():
            ticker_count += 1
            features = td.get("features", [])
            labels = td.get("labels", [])
            pct_returns = td.get("pct_returns", None)
            if not features or not labels:
                continue
            Xw, yw, yr = build_windows(features, labels, TIMESTEPS, pct_returns)
            if Xw is None:
                continue

            if capped:
                remaining = max_samples - total_windows
                if remaining <= 0:
                    break
                if len(Xw) > remaining:
                    Xw = Xw[:remaining]
                    yw = yw[:remaining]
                    yr = yr[:remaining] if yr is not None else None

            X_all.append(Xw)
            y_cls_all.append(yw)
            if yr is not None:
                y_reg_all.append(yr)
            total_windows += len(Xw)

            if ticker_count % 200 == 0:
                print(
                    f"[train-sklearn] Processed {ticker_count:,} tickers, "
                    f"collected {total_windows:,} windows"
                )

        if capped and total_windows >= max_samples:
            break

    if not X_all:
        print("ERROR: no trainable windows built from feature data")
        sys.exit(1)

    X = np.concatenate(X_all, axis=0)
    y_cls = np.concatenate(y_cls_all, axis=0)
    y_reg = np.concatenate(y_reg_all, axis=0) if y_reg_all else None
    print(
        f"[train-sklearn] Final window count: {len(X):,}"
        + (f" (capped at {max_samples:,})" if capped else "")
    )
    return X, y_cls, y_reg, feature_names


def split_timeseries(X: np.ndarray, y_cls: np.ndarray, y_reg: np.ndarray | None):
    n = len(X)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    X_train, y_train = X[:train_end], y_cls[:train_end]
    X_val, y_val = X[train_end:val_end], y_cls[train_end:val_end]
    X_test, y_test = X[val_end:], y_cls[val_end:]

    if y_reg is None:
        return X_train, y_train, None, X_val, y_val, None, X_test, y_test, None

    y_reg_train = y_reg[:train_end]
    y_reg_val = y_reg[train_end:val_end]
    y_reg_test = y_reg[val_end:]
    return X_train, y_train, y_reg_train, X_val, y_val, y_reg_val, X_test, y_test, y_reg_test


def optimize_threshold(probs: np.ndarray, y_true: np.ndarray) -> tuple[float, dict]:
    best_t = 0.5
    best_f1 = -1.0
    best_acc = -1.0
    for t in np.arange(0.35, 0.66, 0.01):
        y_pred = (probs >= t).astype(int)
        acc = float((y_pred == y_true).mean())
        f1 = float(f1_score(y_true, y_pred, zero_division=0))
        if f1 > best_f1 or (abs(f1 - best_f1) < 1e-12 and acc > best_acc):
            best_t = float(t)
            best_f1 = f1
            best_acc = acc
    return round(best_t, 4), {"accuracy": round(best_acc, 4), "f1": round(best_f1, 4)}


def optimize_threshold_profit(
    probs: np.ndarray,
    y_true: np.ndarray,
    y_reg_true: np.ndarray,
) -> tuple[float, dict]:
    best_t = 0.5
    best_objective = -1e18
    best = {
        "objective": "profit",
        "trades": 0,
        "tradeRate": 0.0,
        "avgTradeReturn": 0.0,
        "totalReturn": 0.0,
        "hitRate": 0.0,
        "f1": 0.0,
    }

    for t in np.arange(0.35, 0.86, 0.01):
        take = probs >= t
        n_trades = int(take.sum())
        if n_trades < 25:
            continue

        realized = y_reg_true[take]
        avg_trade_ret = float(realized.mean()) if n_trades > 0 else 0.0
        total_ret = float(realized.sum()) if n_trades > 0 else 0.0
        hit_rate = float((realized > 0).mean()) if n_trades > 0 else 0.0
        trade_rate = float(n_trades / len(probs)) if len(probs) else 0.0
        y_pred = take.astype(int)
        f1 = float(f1_score(y_true, y_pred, zero_division=0))

        # Favors profitable return-per-trade while penalizing sparse overfitting.
        objective = (avg_trade_ret * 10000.0) + (0.35 * hit_rate) + (0.10 * f1) - (0.08 * max(0.0, 0.12 - trade_rate))

        if objective > best_objective:
            best_objective = objective
            best_t = float(t)
            best = {
                "objective": "profit",
                "trades": n_trades,
                "tradeRate": round(trade_rate, 4),
                "avgTradeReturn": round(avg_trade_ret, 6),
                "totalReturn": round(total_ret, 6),
                "hitRate": round(hit_rate, 4),
                "f1": round(f1, 4),
            }

    if best["trades"] == 0:
        return optimize_threshold(probs, y_true)

    return round(best_t, 4), best


def main() -> None:
    start_time = time.time()

    print("=" * 60)
    print("Phase 5 (Fallback): Sklearn Training Pipeline")
    print("=" * 60)
    if MAX_TRAIN_SAMPLES > 0:
        print(f"[train-sklearn] MAX_TRAIN_SAMPLES={MAX_TRAIN_SAMPLES:,}")
    else:
        print("[train-sklearn] MAX_TRAIN_SAMPLES=0 (using all samples)")
    print(
        "[train-sklearn] Boosting params: "
        f"lr={SKLEARN_LEARNING_RATE}, depth={SKLEARN_MAX_DEPTH}, "
        f"iters={SKLEARN_MAX_ITER}, min_leaf={SKLEARN_MIN_SAMPLES_LEAF}"
    )
    print(
        "[train-sklearn] Profit controls: "
        f"thresholdObjective={THRESHOLD_OBJECTIVE}, profitWeightAlpha={PROFIT_WEIGHT_ALPHA}, "
        f"posReturnBonus={POS_RETURN_BONUS}"
    )

    sectors = load_feature_files(FEATURES_DIR)
    X, y_cls, y_reg, feature_names = collect_data(sectors, MAX_TRAIN_SAMPLES)

    feature_count = X.shape[2]
    X_train, y_train, y_reg_train, X_val, y_val, y_reg_val, X_test, y_test, y_reg_test = split_timeseries(X, y_cls, y_reg)

    X_train_2d = X_train.reshape((len(X_train), -1))
    X_val_2d = X_val.reshape((len(X_val), -1))
    X_test_2d = X_test.reshape((len(X_test), -1))

    n_down = int((y_train == 0).sum())
    n_up = int((y_train == 1).sum())
    w_down = len(y_train) / (2.0 * n_down) if n_down > 0 else 1.0
    w_up = len(y_train) / (2.0 * n_up) if n_up > 0 else 1.0
    class_weight = np.where(y_train == 1, w_up, w_down).astype(np.float32)

    if y_reg_train is not None:
        abs_ret = np.abs(y_reg_train)
        ret_scale = np.clip(abs_ret / 0.03, 0.0, 3.0)
        profit_weight = 1.0 + (PROFIT_WEIGHT_ALPHA * ret_scale)
        positive_bonus = np.where(y_reg_train > 0, 1.0 + POS_RETURN_BONUS, 1.0)
        sample_weight = (class_weight * profit_weight * positive_bonus).astype(np.float32)
    else:
        sample_weight = class_weight

    clf = HistGradientBoostingClassifier(
        learning_rate=SKLEARN_LEARNING_RATE,
        max_depth=SKLEARN_MAX_DEPTH,
        max_iter=SKLEARN_MAX_ITER,
        min_samples_leaf=SKLEARN_MIN_SAMPLES_LEAF,
        random_state=42,
    )
    print("[train-sklearn] Fitting classifier...")
    clf.fit(X_train_2d, y_train.astype(int), sample_weight=sample_weight)
    print("[train-sklearn] Classifier fit complete")

    reg = None
    if y_reg_train is not None:
        reg = HistGradientBoostingRegressor(
            learning_rate=SKLEARN_LEARNING_RATE,
            max_depth=SKLEARN_MAX_DEPTH,
            max_iter=SKLEARN_MAX_ITER,
            min_samples_leaf=SKLEARN_MIN_SAMPLES_LEAF,
            random_state=42,
        )
        print("[train-sklearn] Fitting regressor...")
        reg.fit(X_train_2d, y_reg_train)
        print("[train-sklearn] Regressor fit complete")

    val_probs = clf.predict_proba(X_val_2d)[:, 1]
    if THRESHOLD_OBJECTIVE == "profit" and y_reg_val is not None:
        decision_threshold, threshold_metrics = optimize_threshold_profit(
            val_probs,
            y_val.astype(int),
            y_reg_val.astype(np.float32),
        )
    else:
        decision_threshold, threshold_metrics = optimize_threshold(val_probs, y_val.astype(int))

    platt_lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    platt_lr.fit(val_probs.reshape(-1, 1), y_val.astype(int))
    platt_a = float(platt_lr.coef_[0][0])
    platt_b = float(platt_lr.intercept_[0])

    test_probs_raw = clf.predict_proba(X_test_2d)[:, 1]
    z = platt_a * test_probs_raw + platt_b
    test_probs = 1.0 / (1.0 + np.exp(-z))
    y_pred = (test_probs >= decision_threshold).astype(int)
    y_true = y_test.astype(int)

    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())

    accuracy = float((y_pred == y_true).mean())
    auc = float(roc_auc_score(y_true, test_probs)) if len(np.unique(y_true)) > 1 else 0.5
    f1 = float(f1_score(y_true, y_pred, zero_division=0))

    reg_mae = None
    if reg is not None and y_reg_test is not None:
        reg_pred = reg.predict(X_test_2d)
        reg_mae = float(np.abs(reg_pred - y_reg_test).mean())

    os.makedirs(MODELS_V2_DIR, exist_ok=True)
    joblib.dump(
        {
            "classifier": clf,
            "regressor": reg,
            "timesteps": TIMESTEPS,
            "feature_count": feature_count,
            "backend": "sklearn",
        },
        os.path.join(MODELS_V2_DIR, "sklearn_model.joblib"),
    )

    with open(os.path.join(MODELS_V2_DIR, "platt_params.json"), "w") as f:
        json.dump({"a": round(platt_a, 6), "b": round(platt_b, 6)}, f, indent=2)

    metadata = {
        "version": "3.0.0",
        "trainedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "architecture": "HistGradientBoosting-DualHead-Fallback",
        "backend": "sklearn",
        "inputShape": [TIMESTEPS, feature_count],
        "featureCount": feature_count,
        "featureNames": feature_names,
        "lookbackDays": TIMESTEPS,
        "trainingStats": {
            "totalSamples": int(len(X)),
            "trainSamples": int(len(X_train)),
            "valSamples": int(len(X_val)),
            "testSamples": int(len(X_test)),
            "epochs": 1,
            "bestEpoch": 1,
            "decisionThreshold": round(float(decision_threshold), 4),
        },
        "testMetrics": {
            "accuracy": round(accuracy, 4),
            "auc": round(auc, 4),
            "f1": round(f1, 4),
            "confusion_matrix": [[tn, fp], [fn, tp]],
        },
        "thresholdMetrics": threshold_metrics,
    }
    if reg_mae is not None:
        metadata["testMetrics"]["reg_mae"] = round(reg_mae, 6)

    with open(os.path.join(MODELS_V2_DIR, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    os.makedirs(TRAINING_LOGS_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    duration_seconds = round(time.time() - start_time, 3)
    with open(os.path.join(TRAINING_LOGS_DIR, f"{today}.json"), "w") as f:
        json.dump(
            {
                "date": today,
                "duration_seconds": duration_seconds,
                "epochs_run": 1,
                "best_epoch": 1,
                "history": {"val_auc": [round(auc, 4)]},
                "test_results": metadata["testMetrics"],
                "backend": "sklearn",
            },
            f,
            indent=2,
        )

    print("\n=== Fallback Training Complete ===")
    print(f"  Samples    : {len(X):,}")
    print(f"  Accuracy   : {accuracy:.4f}")
    print(f"  AUC        : {auc:.4f}")
    print(f"  F1         : {f1:.4f}")
    if reg_mae is not None:
        print(f"  Reg MAE    : {reg_mae:.6f}")
    print(f"  Duration   : {duration_seconds:.1f}s")
    print(f"  Threshold  : {decision_threshold:.2f}")
    print(f"  Model path : {os.path.join(MODELS_V2_DIR, 'sklearn_model.joblib')}")


if __name__ == "__main__":
    main()
