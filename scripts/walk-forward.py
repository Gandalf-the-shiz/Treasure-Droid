"""
walk-forward.py — Monthly walk-forward diagnostics for Nostradamus V2.

Trains a compact dual-head BiLSTM on rolling 12-month windows and evaluates on
the following month across the last 18 months of feature data. Writes:
  data/accuracy/walk-forward-YYYY-MM.json
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(SCRIPT_DIR, "..")
FEATURES_DIR = os.path.join(REPO_ROOT, "data", "features")
OUT_DIR = os.path.join(REPO_ROOT, "data", "accuracy")

LOOKBACK = 30
DEFAULT_FEATURE_COUNT = 33  # fallback when no feature files are present


@dataclass
class TickerSeries:
    symbol: str
    dates: list[str]
    features: list[list[float]]
    labels: list[int]
    pct_returns: list[float]


def load_tickers(max_tickers: int | None) -> tuple[list[TickerSeries], int]:
    """
    Load ticker feature data from data/features/.
    Returns (tickers, feature_count) where feature_count is resolved from
    the first valid ticker found (typically 33 or 40 depending on the pipeline).
    """
    out = []
    resolved_features: int | None = None
    for fname in sorted(os.listdir(FEATURES_DIR)):
        if not fname.endswith(".json") or fname == "scaling_params.json":
            continue
        with open(os.path.join(FEATURES_DIR, fname), "r") as f:
            data = json.load(f)
        for symbol, td in data.get("tickers", {}).items():
            dates = td.get("dates", [])
            feats = td.get("features", [])
            labels = td.get("labels", [])
            pct = td.get("pct_returns", [])
            if len(dates) < LOOKBACK + 5 or not feats or not labels:
                continue
            n_features = len(feats[0])
            if resolved_features is None:
                resolved_features = n_features
            elif n_features != resolved_features:
                # Skip tickers whose feature count doesn't match the resolved count
                continue
            if not pct or len(pct) != len(labels):
                pct = [0.0] * len(labels)
            out.append(TickerSeries(symbol, dates, feats, labels, pct))
            if max_tickers and len(out) >= max_tickers:
                return out, (resolved_features or DEFAULT_FEATURE_COUNT)
    return out, (resolved_features or DEFAULT_FEATURE_COUNT)


def month_key(date_str: str) -> str:
    return date_str[:7]


def build_samples(tickers: list[TickerSeries]):
    samples = []
    for t in tickers:
        n = len(t.features)
        for i in range(LOOKBACK - 1, n):
            window = t.features[i - LOOKBACK + 1 : i + 1]
            label = t.labels[i]
            reg = t.pct_returns[i]
            d = t.dates[i]
            samples.append((month_key(d), np.array(window, dtype=np.float32), float(label), float(reg)))
    return samples


def build_model(feature_count: int):
    import tensorflow as tf
    from tensorflow.keras import layers

    inp = layers.Input(shape=(LOOKBACK, feature_count))
    x = layers.Bidirectional(layers.LSTM(32, return_sequences=True))(inp)
    x = layers.Dropout(0.2)(x)
    x = layers.LSTM(16)(x)
    x = layers.Dropout(0.2)(x)
    x = layers.Dense(16, activation="relu")(x)
    cls = layers.Dense(1, activation="sigmoid", name="cls_output")(x)
    reg = layers.Dense(1, activation="linear", name="reg_output")(x)
    model = tf.keras.Model(inp, [cls, reg])
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss={"cls_output": "binary_crossentropy", "reg_output": "mse"},
        loss_weights={"cls_output": 1.0, "reg_output": 0.5},
    )
    return model


def run_fold(train_set, test_set, epochs: int, batch_size: int, feature_count: int):
    import tensorflow as tf

    X_train = np.stack([x for _, x, _, _ in train_set])
    y_train_cls = np.array([y for _, _, y, _ in train_set], dtype=np.float32)
    y_train_reg = np.array([r for _, _, _, r in train_set], dtype=np.float32)

    X_test = np.stack([x for _, x, _, _ in test_set])
    y_test_cls = np.array([y for _, _, y, _ in test_set], dtype=np.float32)
    y_test_reg = np.array([r for _, _, _, r in test_set], dtype=np.float32)

    model = build_model(feature_count)
    model.fit(
        X_train,
        [y_train_cls, y_train_reg],
        epochs=epochs,
        batch_size=batch_size,
        verbose=0,
        validation_split=0.1,
        callbacks=[
            tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=2, restore_best_weights=True),
        ],
    )
    cls_pred, reg_pred = model.predict(X_test, verbose=0)
    cls_pred = cls_pred.reshape(-1)
    reg_pred = reg_pred.reshape(-1)
    y_hat = (cls_pred >= 0.5).astype(np.float32)
    acc = float((y_hat == y_test_cls).mean())
    mae = float(np.mean(np.abs(reg_pred - y_test_reg)))
    auc_metric = tf.keras.metrics.AUC()
    auc_metric.update_state(y_test_cls, cls_pred)
    auc = float(auc_metric.result().numpy())
    return acc, auc, mae, int(len(y_test_cls))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tickers", type=int, default=None, help="Limit ticker count for faster diagnostics")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=256)
    args = ap.parse_args()

    tickers, feature_count = load_tickers(args.max_tickers)
    if not tickers:
        print("[walk-forward] No ticker feature data found. Skipping — no output written.")
        sys.exit(0)

    print(f"[walk-forward] Resolved feature count: {feature_count}")

    samples = build_samples(tickers)
    months = sorted({m for m, *_ in samples})
    if len(months) < 13:
        print(
            f"[walk-forward] Only {len(months)} month(s) of data available; "
            "need at least 13 for a single fold. Skipping — no output written."
        )
        sys.exit(0)

    months = months[-18:]
    folds = []
    for start in range(0, max(0, len(months) - 12)):
        train_months = set(months[start : start + 12])
        test_month = months[start + 12]
        train_set = [s for s in samples if s[0] in train_months]
        test_set = [s for s in samples if s[0] == test_month]
        if len(train_set) < 2000 or len(test_set) < 200:
            continue
        acc, auc, mae, n = run_fold(train_set, test_set, args.epochs, args.batch_size, feature_count)
        folds.append({
            "trainMonths": sorted(train_months),
            "testMonth": test_month,
            "accuracy": round(acc, 4),
            "auc": round(auc, 4),
            "regressionMAE": round(mae, 6),
            "sampleSize": n,
        })

    if not folds:
        print("[walk-forward] No eligible folds produced (insufficient sample sizes). Skipping — no output written.")
        sys.exit(0)

    weighted_n = sum(f["sampleSize"] for f in folds)
    agg = {
        "accuracy": round(sum(f["accuracy"] * f["sampleSize"] for f in folds) / weighted_n, 4),
        "auc": round(sum(f["auc"] * f["sampleSize"] for f in folds) / weighted_n, 4),
        "regressionMAE": round(sum(f["regressionMAE"] * f["sampleSize"] for f in folds) / weighted_n, 6),
        "sampleSize": weighted_n,
        "folds": len(folds),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m")
    out_path = os.path.join(OUT_DIR, f"walk-forward-{stamp}.json")
    report = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "maxTickers": args.max_tickers,
        "folds": folds,
        "aggregated": agg,
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[walk-forward] wrote {out_path}")


if __name__ == "__main__":
    main()
