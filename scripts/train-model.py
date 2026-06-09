"""
train-model.py — Phase 5: Server-Side Model Training Pipeline

Reads feature data from data/features/*.json (Phase 4 output), builds a
Bidirectional LSTM model, trains it with time-series-aware splits, evaluates
on a held-out test set, then exports to TensorFlow.js format.

Architecture: BiLSTM (128) → LSTM (64) → Dense (32, relu) → Dense (1, sigmoid)
Input shape:  (30, 33) — 30 timesteps × 33 features from Phase 4
Output:       P(price UP tomorrow) ∈ [0, 1]

All layers are TF.js-compatible (no MultiHeadAttention, no Lambda).
"""

import json
import os
import sys
import math
import random
import time
import shutil
from datetime import datetime, timezone

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(SCRIPT_DIR, "..")
FEATURES_DIR = os.path.join(REPO_ROOT, "data", "features")
SCALING_PARAMS_PATH = os.path.join(FEATURES_DIR, "scaling_params.json")
MODELS_V2_DIR = os.path.join(REPO_ROOT, "models", "v2")
MODELS_ARCHIVE_DIR = os.path.join(REPO_ROOT, "models", "archive")
TRAINING_LOGS_DIR = os.path.join(REPO_ROOT, "data", "training-logs")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMESTEPS = 30       # lookback window (must match Phase 4 LOOKBACK_DAYS)
FEATURES = None      # resolved dynamically from scaling_params.json; default 40
TRAIN_FRAC = 0.70
VAL_FRAC = 0.15
# TEST_FRAC = 0.15   (implicit: remainder)

MAX_TRAIN_SAMPLES = int(os.getenv("MAX_TRAIN_SAMPLES", "2000000"))
MIN_SAMPLES = 10_000             # warn if dataset is very small
ARCHIVE_MAX_MB = 500
ARCHIVE_MIN_KEEP = 4

# Phase D: Ensemble training parameters
ENSEMBLE_SIZE = 5    # number of models in the ensemble (different random seeds)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_feature_files(features_dir: str) -> list[dict]:
    """
    Load all sector feature files from data/features/*.json.
    Returns list of sector dicts, each with 'sector' and 'tickers' keys.
    """
    sector_files = [
        f for f in os.listdir(features_dir)
        if f.endswith(".json") and f != "scaling_params.json"
    ]
    if not sector_files:
        print("ERROR: No feature files found in", features_dir)
        print("  Run Phase 4 (build-features.py) first.")
        sys.exit(1)

    sectors = []
    for fname in sorted(sector_files):
        path = os.path.join(features_dir, fname)
        with open(path, "r") as fh:
            data = json.load(fh)
        sectors.append(data)
        tickers_in_file = len(data.get("tickers", {}))
        print(f"  Loaded {fname}: {tickers_in_file} tickers")
    return sectors


def build_windows(features: list[list[float]], labels: list[int], timesteps: int,
                   pct_returns: list[float] | None = None):
    """
    Build sliding windows from a single ticker's per-day feature vectors.
    Window [i] covers days [i .. i+timesteps-1].
    The label for window [i] is labels[i + timesteps - 1].

    Returns X (num_windows, timesteps, num_features), y_cls (num_windows,),
    and optionally y_reg (num_windows,) when pct_returns is provided.
    """
    n = len(features)
    if n < timesteps:
        return None, None, None
    num_windows = n - timesteps + 1
    X = np.array(features, dtype=np.float32)   # (n, FEATURES)
    y_all = np.array(labels, dtype=np.float32)

    X_windows = np.lib.stride_tricks.as_strided(
        X,
        shape=(num_windows, timesteps, X.shape[1]),
        strides=(X.strides[0], X.strides[0], X.strides[1]),
    ).copy()
    y_windows = y_all[timesteps - 1 :]
    assert len(X_windows) == len(y_windows), "Window/label count mismatch"

    y_reg_windows = None
    if pct_returns is not None:
        y_reg_all = np.array(pct_returns, dtype=np.float32)
        y_reg_windows = y_reg_all[timesteps - 1 :]
        assert len(X_windows) == len(y_reg_windows), "Window/pct_return count mismatch"

    return X_windows, y_windows, y_reg_windows


def collect_ticker_data(sectors: list[dict], timesteps: int):
    """
    Iterate all tickers across all sectors and build windowed arrays.
    Returns (X, y_cls, y_reg, sector_labels) where sector_labels[i] is the sector name
    for sample i (for per-sector accuracy computation).
    Also returns feature_names from the first sector file encountered.
    y_reg may be None if no pct_returns data is available in the feature files.
    """
    X_all, y_cls_all, y_reg_all, sector_all = [], [], [], []
    feature_names = None
    tickers_used = 0
    has_reg = False

    for sector_data in sectors:
        sector_name = sector_data.get("sector", "Unknown")
        if feature_names is None:
            feature_names = sector_data.get("featureNames", [])
        tickers = sector_data.get("tickers", {})

        for ticker, td in tickers.items():
            features = td.get("features", [])
            labels_raw = td.get("labels", [])
            pct_returns_raw = td.get("pct_returns", None)
            if not features or not labels_raw:
                continue
            X_t, y_cls_t, y_reg_t = build_windows(features, labels_raw, timesteps, pct_returns_raw)
            if X_t is None or len(X_t) == 0:
                continue
            X_all.append(X_t)
            y_cls_all.append(y_cls_t)
            if y_reg_t is not None:
                y_reg_all.append(y_reg_t)
                has_reg = True
            sector_all.extend([sector_name] * len(X_t))
            tickers_used += 1

    if not X_all:
        print("ERROR: No valid windowed samples could be built from the feature data.")
        sys.exit(1)

    X_out = np.concatenate(X_all, axis=0)
    y_cls_out = np.concatenate(y_cls_all, axis=0)
    y_reg_out = np.concatenate(y_reg_all, axis=0) if has_reg else None
    sector_out = np.array(sector_all)

    return X_out, y_cls_out, y_reg_out, sector_out, feature_names, tickers_used


# ---------------------------------------------------------------------------
# Time-series-aware train / val / test split
# ---------------------------------------------------------------------------

def timeseries_split(X: np.ndarray, y_cls: np.ndarray, y_reg: np.ndarray | None,
                     sector_labels: np.ndarray,
                     train_frac: float = TRAIN_FRAC, val_frac: float = VAL_FRAC):
    """
    Per-ticker chronological split: first 70% train, next 15% val, last 15% test.
    Because we already concatenated all tickers in order (windows are consecutive
    per ticker), we need to split the combined array respecting that the samples
    are already in temporal order within each ticker.

    For a combined dataset, a safe approximation is a global chronological split:
    the first train_frac fraction goes to train, the next val_frac to val, the
    remainder to test. This preserves time ordering and prevents future leakage.
    """
    n = len(X)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))

    X_train, y_cls_train = X[:train_end], y_cls[:train_end]
    X_val, y_cls_val = X[train_end:val_end], y_cls[train_end:val_end]
    X_test, y_cls_test = X[val_end:], y_cls[val_end:]
    sectors_test = sector_labels[val_end:]

    if y_reg is not None:
        y_reg_train = y_reg[:train_end]
        y_reg_val = y_reg[train_end:val_end]
        y_reg_test = y_reg[val_end:]
    else:
        y_reg_train = y_reg_val = y_reg_test = None

    return (X_train, y_cls_train, y_reg_train,
            X_val, y_cls_val, y_reg_val,
            X_test, y_cls_test, y_reg_test,
            sectors_test)


def shuffle_training_set(X_train: np.ndarray, y_cls_train: np.ndarray,
                          y_reg_train: np.ndarray | None, seed: int = 42):
    """Shuffle training set (NOT val or test)."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X_train))
    y_reg_out = y_reg_train[idx] if y_reg_train is not None else None
    return X_train[idx], y_cls_train[idx], y_reg_out


def subsample_training_set(X_train: np.ndarray, y_cls_train: np.ndarray,
                            y_reg_train: np.ndarray | None,
                            max_samples: int, seed: int = 42):
    """Randomly subsample training set when it exceeds max_samples."""
    if max_samples <= 0:
        print("  MAX_TRAIN_SAMPLES<=0: using full training set without subsampling.")
        return X_train, y_cls_train, y_reg_train
    if len(X_train) <= max_samples:
        return X_train, y_cls_train, y_reg_train
    print(f"  Training set ({len(X_train):,}) exceeds {max_samples:,}. Subsampling…")
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X_train), size=max_samples, replace=False)
    y_reg_out = y_reg_train[idx] if y_reg_train is not None else None
    return X_train[idx], y_cls_train[idx], y_reg_out


def compute_class_weights(y: np.ndarray) -> dict:
    """Compute balanced class weights for binary labels."""
    n = len(y)
    n_down = int((y == 0).sum())
    n_up = int((y == 1).sum())
    if n_down == 0 or n_up == 0:
        return {0: 1.0, 1: 1.0}
    # sklearn formula: n_samples / (n_classes * n_class_i)
    w_down = n / (2.0 * n_down)
    w_up = n / (2.0 * n_up)
    return {0: round(w_down, 4), 1: round(w_up, 4)}


# ---------------------------------------------------------------------------
# Model definition
# ---------------------------------------------------------------------------

def build_model(timesteps: int = TIMESTEPS, features: int = 40):
    """
    TF.js-compatible dual-head BiLSTM model.

    Architecture:
      Input(30, 33)
      → Bidirectional(LSTM(128, return_sequences=True))
      → Dropout(0.3)
      → LSTM(64, return_sequences=False)
      → Dropout(0.2)
      → Dense(32, relu)
      → Dropout(0.2)
      → cls_output: Dense(1, sigmoid)  — P(price UP tomorrow)
      → reg_output: Dense(1, linear)   — predicted % return

    All layers are supported by tensorflowjs_converter.
    """
    import tensorflow as tf
    from tensorflow.keras import layers, Model

    inputs = layers.Input(shape=(timesteps, features), name="input")

    # Bidirectional LSTM — captures temporal context in both directions
    x = layers.Bidirectional(
        layers.LSTM(128, return_sequences=True, name="lstm_1"),
        name="bidirectional_1",
    )(inputs)
    x = layers.Dropout(0.3, name="dropout_1")(x)

    # Second LSTM — collapses the sequence into a fixed-size representation
    x = layers.LSTM(64, return_sequences=False, name="lstm_2")(x)
    x = layers.Dropout(0.2, name="dropout_2")(x)

    # Dense hidden layer
    x = layers.Dense(32, activation="relu", name="dense_1")(x)
    x = layers.Dropout(0.2, name="dropout_3")(x)

    # Classification head — P(UP) [0, 1]
    cls_output = layers.Dense(1, activation="sigmoid", name="cls_output")(x)

    # Regression head — predicted % return (linear activation)
    reg_output = layers.Dense(1, activation="linear", name="reg_output")(x)

    model = Model(inputs=inputs, outputs=[cls_output, reg_output], name="nostradamus_v2")
    return model


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(model, X_train, y_cls_train, y_reg_train, X_val, y_cls_val, y_reg_val, class_weights: dict):
    import tensorflow as tf

    # Build target lists for dual-head model (must match model output order)
    # Both y and sample_weight must use the same format (list) for Keras 3 / TF >=2.16
    y_train_list = [y_cls_train]
    y_val_list   = [y_cls_val]
    if y_reg_train is not None:
        y_train_list.append(y_reg_train)
        y_val_list.append(y_reg_val)

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss={
            "cls_output": "binary_crossentropy",
            "reg_output": "mse",
        },
        loss_weights={
            "cls_output": 1.0,
            "reg_output": 0.5,
        },
        metrics={
            "cls_output": ["accuracy", tf.keras.metrics.AUC(name="auc")],
            "reg_output": ["mae"],
        },
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_cls_output_auc",
            patience=10,
            mode="max",
            restore_best_weights=True,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
        ),
    ]

    # Convert class_weight dict → per-sample weight array for cls_output only
    # (Keras doesn't support class_weight with multi-output models)
    sample_weights_cls = np.where(y_cls_train == 1, class_weights[1], class_weights[0]).astype(np.float32)

    # Pass as a list matching model output order: [cls_output, reg_output]
    # Keras resolves sample_weight by integer index, not string key, for list-output models.
    # reg_output gets uniform weights (no class balancing needed for regression)
    sample_weights_list = [sample_weights_cls]
    if y_reg_train is not None:
        sample_weights_list.append(np.ones(len(y_cls_train), dtype=np.float32))

    history = model.fit(
        X_train,
        y_train_list,
        validation_data=(X_val, y_val_list),
        epochs=100,
        batch_size=256,
        sample_weight=sample_weights_list,
        callbacks=callbacks,
        verbose=1,
    )
    return history


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_model(model, X_test, y_cls_test, y_reg_test, sectors_test):
    """Evaluate on held-out test set; return metrics dict."""
    import tensorflow as tf

    # Dual-head model returns [cls_output, reg_output]
    raw_preds = model.predict(X_test, verbose=0)
    if isinstance(raw_preds, list) and len(raw_preds) == 2:
        y_pred_prob = raw_preds[0].flatten()
        y_reg_pred  = raw_preds[1].flatten()
    else:
        y_pred_prob = raw_preds.flatten()
        y_reg_pred  = None

    y_pred = (y_pred_prob >= 0.5).astype(int)
    y_true = y_cls_test.astype(int)

    # Confusion matrix
    tp = ((y_pred == 1) & (y_true == 1)).sum()
    tn = ((y_pred == 0) & (y_true == 0)).sum()
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()
    confusion = [[int(tn), int(fp)], [int(fn), int(tp)]]

    # Accuracy computed directly from predictions (robust across Keras versions)
    accuracy = float((y_pred == y_true).mean())

    # AUC via TF metrics API (numerically stable, no sklearn dependency)
    auc_metric = tf.keras.metrics.AUC(name="auc")
    auc_metric.update_state(y_true, y_pred_prob)
    auc_val = float(auc_metric.result())

    # Precision / Recall / F1
    prec_val = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    rec_val  = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = (2 * prec_val * rec_val / (prec_val + rec_val)) if (prec_val + rec_val) > 0 else 0.0

    # Regression MAE
    reg_mae = None
    if y_reg_test is not None and y_reg_pred is not None:
        reg_mae = float(np.abs(y_reg_pred - y_reg_test).mean())

    print("\n=== Test Set Evaluation ===")
    print(f"  Accuracy : {accuracy:.4f}")
    print(f"  AUC      : {auc_val:.4f}")
    print(f"  F1       : {f1:.4f}")
    if reg_mae is not None:
        print(f"  Reg MAE  : {reg_mae:.6f}  (predicted % return)")
    print(f"  Confusion Matrix (TN, FP, FN, TP): {tn}, {fp}, {fn}, {tp}")

    # Per-sector accuracy
    unique_sectors = sorted(set(sectors_test))
    if len(unique_sectors) > 1:
        print("\n  Per-sector accuracy:")
        for s in unique_sectors:
            mask = sectors_test == s
            if mask.sum() == 0:
                continue
            s_acc = (y_pred[mask] == y_true[mask]).mean()
            print(f"    {s:<30} {s_acc:.4f}  (n={mask.sum():,})")

    if accuracy < 0.50:
        print("\nWARN: Test accuracy < 50% (worse than random). Model will still be exported.")

    out = {
        "accuracy":         round(float(accuracy), 4),
        "auc":              round(float(auc_val), 4),
        "f1":               round(float(f1), 4),
        "confusion_matrix": confusion,
    }
    if reg_mae is not None:
        out["reg_mae"] = round(reg_mae, 6)
    return out


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_model(model, models_v2_dir: str):
    """Save in Keras SavedModel format, then convert to TF.js."""
    import tensorflow as tf
    import tensorflowjs as tfjs

    os.makedirs(models_v2_dir, exist_ok=True)
    keras_path = os.path.join(models_v2_dir, "keras_model.keras")
    print(f"\nSaving Keras model to {keras_path} …")
    model.save(keras_path)

    print(f"Converting to TF.js format in {models_v2_dir} …")
    tfjs.converters.save_keras_model(model, models_v2_dir)
    print("  TF.js export complete.")


def write_metadata(
    models_v2_dir: str,
    feature_names: list[str],
    feature_count: int,
    train_samples: int,
    val_samples: int,
    test_samples: int,
    epochs_run: int,
    history,
    test_metrics: dict,
    class_weights: dict,
    training_data_range: dict,
    parent_model_sha: str | None,
    decision_threshold: float,
    threshold_metrics: dict,
):
    """Write models/v2/metadata.json with training stats."""
    import tensorflow as tf

    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Best epoch = epoch with highest val_cls_output_auc (dual-head) or val_auc (legacy)
    val_auc_list = (history.history.get("val_cls_output_auc")
                    or history.history.get("val_auc", []))
    best_epoch = int(np.argmax(val_auc_list)) + 1 if val_auc_list else epochs_run

    lr_history = history.history.get("lr", [])
    final_lr = float(lr_history[-1]) if lr_history else 0.001

    metadata = {
        "version": "3.0.0",
        "trainedAt": trained_at,
        "architecture": "BiLSTM-Dense-DualHead-Ensemble",
        "inputShape": [TIMESTEPS, feature_count],
        "featureCount": feature_count,
        "featureNames": feature_names,
        "lookbackDays": TIMESTEPS,
        "gitSha": os.getenv("GITHUB_SHA"),
        "parentModelSha": parent_model_sha,
        "trainingDataRange": training_data_range,
        "outputType": "dual_head_classification_regression",
        "outputInterpretation": "cls_output: P(price_UP_tomorrow) sigmoid [0,1]; reg_output: predicted % return linear",
        "ensembleSize": ENSEMBLE_SIZE,
        "trainingStats": {
            "totalSamples": train_samples + val_samples + test_samples,
            "trainSamples": train_samples,
            "valSamples": val_samples,
            "testSamples": test_samples,
            "epochs": epochs_run,
            "bestEpoch": best_epoch,
            "finalLR": round(final_lr, 8),
            "decisionThreshold": round(float(decision_threshold), 4),
        },
        "testMetrics": {
            "accuracy": test_metrics["accuracy"],
            "auc": test_metrics["auc"],
            "f1": test_metrics["f1"],
        },
        "classWeights": {str(k): v for k, v in class_weights.items()},
        "thresholdMetrics": threshold_metrics,
        "scalingParams": "See data/features/scaling_params.json",
    }

    if "reg_mae" in test_metrics:
        metadata["testMetrics"]["reg_mae"] = test_metrics["reg_mae"]

    path = os.path.join(models_v2_dir, "metadata.json")
    with open(path, "w") as fh:
        json.dump(metadata, fh, indent=2)
    print(f"Wrote {path}")
    return metadata


def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total


def archive_current_model(models_v2_dir: str):
    os.makedirs(MODELS_ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target = os.path.join(MODELS_ARCHIVE_DIR, f"v2-{stamp}")
    if os.path.exists(target):
        # Keep snapshots immutable by adding time suffix when same-day rerun happens
        suffix = datetime.now(timezone.utc).strftime("%H%M%S")
        target = f"{target}-{suffix}"
    shutil.copytree(models_v2_dir, target, dirs_exist_ok=False)
    print(f"Archived model snapshot to {target}")
    prune_model_archive(MODELS_ARCHIVE_DIR)


def prune_model_archive(archive_dir: str):
    snapshots = []
    for name in os.listdir(archive_dir):
        p = os.path.join(archive_dir, name)
        if os.path.isdir(p) and name.startswith("v2-"):
            snapshots.append((os.path.getmtime(p), p))
    snapshots.sort()
    total_mb = _dir_size_bytes(archive_dir) / (1024 * 1024)
    print(f"Archive size: {total_mb:.1f} MB")
    while total_mb > ARCHIVE_MAX_MB and len(snapshots) > ARCHIVE_MIN_KEEP:
        _, oldest = snapshots.pop(0)
        shutil.rmtree(oldest, ignore_errors=True)
        print(f"Pruned old snapshot: {oldest}")
        total_mb = _dir_size_bytes(archive_dir) / (1024 * 1024)


def write_training_log(
    training_logs_dir: str,
    duration_seconds: float,
    epochs_run: int,
    history,
    test_metrics: dict,
):
    """Write data/training-logs/YYYY-MM-DD.json with training history."""
    os.makedirs(training_logs_dir, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    val_auc_list = (history.history.get("val_cls_output_auc")
                    or history.history.get("val_auc", []))
    best_epoch = int(np.argmax(val_auc_list)) + 1 if val_auc_list else epochs_run

    def to_python(v):
        if isinstance(v, (np.floating, np.integer)):
            return float(v)
        return v

    log = {
        "date": today,
        "duration_seconds": round(duration_seconds, 1),
        "epochs_run": epochs_run,
        "best_epoch": best_epoch,
        "history": {
            k: [to_python(x) for x in v]
            for k, v in history.history.items()
        },
        "test_results": test_metrics,
    }

    path = os.path.join(training_logs_dir, f"{today}.json")
    with open(path, "w") as fh:
        json.dump(log, fh, indent=2)
    print(f"Wrote training log to {path}")


# ---------------------------------------------------------------------------
# Phase D: Platt calibration helper
# ---------------------------------------------------------------------------

def fit_platt_scaling(model, X_val: np.ndarray, y_cls_val: np.ndarray) -> tuple[float, float]:
    """
    Fit Platt scaling (logistic regression on raw sigmoid outputs) to calibrate
    the classifier so P(UP=x) is genuinely x% likely to be correct.

    Returns (platt_a, platt_b) — the slope and intercept of the calibration.
    Saves to models/v2/platt_params.json.
    """
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("  WARN: scikit-learn not available — skipping Platt calibration.")
        return 1.0, 0.0

    raw_preds = model.predict(X_val, verbose=0)
    if isinstance(raw_preds, list) and len(raw_preds) == 2:
        probs = raw_preds[0].flatten()
    else:
        probs = raw_preds.flatten()

    # Platt scaling: fit logistic regression on raw scores (not re-applying sigmoid)
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    lr.fit(probs.reshape(-1, 1), y_cls_val.astype(int))

    platt_a = float(lr.coef_[0][0])
    platt_b = float(lr.intercept_[0])

    platt_params = {"a": round(platt_a, 6), "b": round(platt_b, 6)}
    platt_path = os.path.join(MODELS_V2_DIR, "platt_params.json")
    with open(platt_path, "w") as f:
        json.dump(platt_params, f, indent=2)
    print(f"  Platt calibration: a={platt_a:.4f}, b={platt_b:.4f} → saved to {platt_path}")
    return platt_a, platt_b


def platt_calibrate(raw_prob: float, platt_a: float, platt_b: float) -> float:
    """Apply Platt scaling to convert raw probability to calibrated probability."""
    import math
    z = platt_a * raw_prob + platt_b
    return 1.0 / (1.0 + math.exp(-z))


# ---------------------------------------------------------------------------
# Phase D: Ensemble training and export
# ---------------------------------------------------------------------------

def train_ensemble(
    X_train, y_cls_train, y_reg_train,
    X_val, y_cls_val, y_reg_val,
    X_test, y_cls_test, y_reg_test,
    sectors_test,
    feature_count: int,
) -> tuple[list, dict]:
    """
    Train ENSEMBLE_SIZE models with different random seeds.
    Each model is saved to models/v2/ensemble/model_{i}/.
    Returns (list_of_models, averaged_test_metrics).
    """
    ensemble_dir = os.path.join(MODELS_V2_DIR, "ensemble")
    os.makedirs(ensemble_dir, exist_ok=True)

    models     = []
    histories  = []
    all_probs  = []   # (ensemble_size, test_size) — for ensemble averaging

    class_weights = compute_class_weights(y_cls_train)

    for i in range(ENSEMBLE_SIZE):
        seed = 42 + i * 17   # 17 is a prime offset to ensure seed diversity across ensemble members
        print(f"\n  ── Ensemble member {i+1}/{ENSEMBLE_SIZE} (seed={seed}) ──")

        # Set random seeds
        import tensorflow as tf
        tf.random.set_seed(seed)
        np.random.seed(seed)

        # Shuffle training set with this seed
        X_tr_i, y_cls_tr_i, y_reg_tr_i = shuffle_training_set(
            X_train, y_cls_train, y_reg_train, seed=seed
        )

        model_i = build_model(TIMESTEPS, feature_count)
        hist_i  = train(model_i, X_tr_i, y_cls_tr_i, y_reg_tr_i,
                        X_val, y_cls_val, y_reg_val, class_weights)

        # Save each ensemble member
        member_dir  = os.path.join(ensemble_dir, f"model_{i}")
        keras_path  = os.path.join(member_dir, "keras_model.keras")
        os.makedirs(member_dir, exist_ok=True)
        model_i.save(keras_path)

        # Collect test probabilities
        raw = model_i.predict(X_test, verbose=0)
        probs = raw[0].flatten() if isinstance(raw, list) else raw.flatten()
        all_probs.append(probs)

        models.append(model_i)
        histories.append(hist_i)

    # Ensemble: average probabilities
    all_probs_arr  = np.stack(all_probs, axis=0)           # (ensemble, n_test)
    ensemble_probs = all_probs_arr.mean(axis=0)            # (n_test,)
    ensemble_std   = all_probs_arr.std(axis=0)             # (n_test,) — uncertainty

    # Save std for inspection
    std_path = os.path.join(MODELS_V2_DIR, "ensemble_std_sample.json")
    with open(std_path, "w") as f:
        json.dump({"mean_std": round(float(ensemble_std.mean()), 4),
                   "max_std": round(float(ensemble_std.max()), 4)}, f)

    # Evaluate ensemble
    import tensorflow as tf
    ensemble_preds = (ensemble_probs >= 0.5).astype(int)
    y_true = y_cls_test.astype(int)

    tp = int(((ensemble_preds == 1) & (y_true == 1)).sum())
    tn = int(((ensemble_preds == 0) & (y_true == 0)).sum())
    fp = int(((ensemble_preds == 1) & (y_true == 0)).sum())
    fn = int(((ensemble_preds == 0) & (y_true == 1)).sum())

    accuracy = float((ensemble_preds == y_true).mean())
    auc_metric = tf.keras.metrics.AUC()
    auc_metric.update_state(y_true, ensemble_probs)
    auc_val = float(auc_metric.result())
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    avg_metrics = {
        "accuracy":         round(accuracy, 4),
        "auc":              round(auc_val, 4),
        "f1":               round(float(f1), 4),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "ensemble_mean_std": round(float(ensemble_std.mean()), 4),
    }

    print(f"\n  ── Ensemble combined accuracy: {accuracy:.4f}, AUC: {auc_val:.4f} ──")
    return models, avg_metrics, histories


def optimize_decision_threshold(models: list, X_val: np.ndarray, y_cls_val: np.ndarray) -> tuple[float, dict]:
    """
    Optimize classification threshold on validation predictions.
    Objective: maximize F1 with accuracy as tiebreaker.
    """
    val_probs = []
    for model in models:
        raw = model.predict(X_val, verbose=0)
        probs = raw[0].flatten() if isinstance(raw, list) else raw.flatten()
        val_probs.append(probs)

    if not val_probs:
        return 0.5, {"accuracy": None, "f1": None}

    ensemble_probs = np.stack(val_probs, axis=0).mean(axis=0)
    y_true = y_cls_val.astype(int)

    best_t = 0.5
    best_f1 = -1.0
    best_acc = -1.0

    for t in np.arange(0.35, 0.66, 0.01):
        y_pred = (ensemble_probs >= t).astype(int)
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        acc = float((y_pred == y_true).mean())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        if f1 > best_f1 or (abs(f1 - best_f1) < 1e-9 and acc > best_acc):
            best_t = float(t)
            best_f1 = float(f1)
            best_acc = float(acc)

    return round(best_t, 4), {
        "accuracy": round(best_acc, 4),
        "f1": round(best_f1, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    print("=" * 60)
    print("Phase 5+D: Nostradamus Model Training Pipeline (Ensemble)")
    print("=" * 60)

    # --- 1. Load feature files ---
    print("\n[1/7] Loading feature files …")
    sectors = load_feature_files(FEATURES_DIR)

    # --- Resolve feature count dynamically from scaling_params ---
    feature_count = None
    if os.path.exists(SCALING_PARAMS_PATH):
        try:
            with open(SCALING_PARAMS_PATH) as f:
                sp = json.load(f)
            feature_count = int(sp.get("featureCount", 0)) or None
        except Exception:
            pass

    # --- 2. Build windowed dataset ---
    print("\n[2/7] Building sliding-window dataset …")
    X, y_cls, y_reg, sector_labels, feature_names, tickers_used = collect_ticker_data(
        sectors, TIMESTEPS
    )

    if feature_count is None:
        feature_count = X.shape[2] if len(X.shape) == 3 else (
            len(feature_names) if feature_names else 40
        )
    print(f"  Feature count  : {feature_count}")

    total_samples = len(X)
    n_up = int((y_cls == 1).sum())
    n_down = int((y_cls == 0).sum())
    print(f"  Total samples  : {total_samples:,}")
    print(f"  UP  (label=1)  : {n_up:,}  ({n_up/total_samples*100:.1f}%)")
    print(f"  DOWN(label=0)  : {n_down:,}  ({n_down/total_samples*100:.1f}%)")
    print(f"  Tickers used   : {tickers_used:,}")
    print(f"  Regression targets available: {y_reg is not None}")

    # Training data range metadata
    all_dates = []
    for sec in sectors:
        for td in sec.get("tickers", {}).values():
            all_dates.extend(td.get("dates", []))
    all_dates.sort()
    training_data_range = {
        "start": all_dates[0] if all_dates else None,
        "end": all_dates[-1] if all_dates else None,
        "tickerCount": tickers_used,
        "sampleCount": int(total_samples),
    }

    parent_model_sha = None
    prev_meta_path = os.path.join(MODELS_V2_DIR, "metadata.json")
    if os.path.exists(prev_meta_path):
        try:
            with open(prev_meta_path, "r") as f:
                prev_meta = json.load(f)
            parent_model_sha = prev_meta.get("gitSha")
        except Exception:
            parent_model_sha = None

    if total_samples < MIN_SAMPLES:
        print(f"\nWARN: Only {total_samples:,} samples (< {MIN_SAMPLES:,}). "
              "Training on a small dataset — accuracy may be low.")

    # --- 3. Split ---
    print("\n[3/7] Time-series-aware train/val/test split …")
    (X_train, y_cls_train, y_reg_train,
     X_val,   y_cls_val,   y_reg_val,
     X_test,  y_cls_test,  y_reg_test,
     sectors_test) = timeseries_split(X, y_cls, y_reg, sector_labels)
    print(f"  Train : {len(X_train):,}")
    print(f"  Val   : {len(X_val):,}")
    print(f"  Test  : {len(X_test):,}")

    # Subsample training set if needed (before per-seed shuffling)
    X_train, y_cls_train, y_reg_train = subsample_training_set(
        X_train, y_cls_train, y_reg_train, MAX_TRAIN_SAMPLES
    )

    class_weights = compute_class_weights(y_cls_train)
    print(f"\n  Class weights: DOWN={class_weights[0]}, UP={class_weights[1]}")

    # --- 4. Train ensemble ---
    print(f"\n[4/7] Training ensemble of {ENSEMBLE_SIZE} models …")
    ensemble_models, test_metrics, histories = train_ensemble(
        X_train, y_cls_train, y_reg_train,
        X_val,   y_cls_val,   y_reg_val,
        X_test,  y_cls_test,  y_reg_test,
        sectors_test,
        feature_count=feature_count,
    )

    # --- 5. Platt calibration (fitted on ensemble mean predictions over the validation set) ---
    print("\n[5/7] Fitting Platt calibration on ensemble-averaged validation outputs …")
    # Compute ensemble-averaged validation probabilities first
    val_probs_all = []
    for m_i in ensemble_models:
        raw_v = m_i.predict(X_val, verbose=0)
        vp = raw_v[0].flatten() if isinstance(raw_v, list) else raw_v.flatten()
        val_probs_all.append(vp)
    ensemble_val_probs = np.stack(val_probs_all, axis=0).mean(axis=0)

    # Fit Platt scaling using a temporary wrapper so we can pass pre-computed probs
    try:
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
        lr.fit(ensemble_val_probs.reshape(-1, 1), y_cls_val.astype(int))
        platt_a = float(lr.coef_[0][0])
        platt_b = float(lr.intercept_[0])
        platt_params = {"a": round(platt_a, 6), "b": round(platt_b, 6)}
        platt_path = os.path.join(MODELS_V2_DIR, "platt_params.json")
        with open(platt_path, "w") as f:
            json.dump(platt_params, f, indent=2)
        print(f"  Platt calibration: a={platt_a:.4f}, b={platt_b:.4f} → {platt_path}")
    except ImportError:
        print("  WARN: scikit-learn not available — skipping Platt calibration.")
        platt_a, platt_b = 1.0, 0.0

    # --- 5b. Optimize decision threshold on validation set ---
    decision_threshold, threshold_metrics = optimize_decision_threshold(
        ensemble_models, X_val, y_cls_val
    )
    print(
        f"[threshold] optimized decision threshold={decision_threshold:.2f} "
        f"(val_f1={threshold_metrics.get('f1')}, val_acc={threshold_metrics.get('accuracy')})"
    )

    # --- 6. Export primary model (first member; ensemble used at inference) ---
    print("\n[6/7] Exporting primary model …")
    os.makedirs(MODELS_V2_DIR, exist_ok=True)
    export_model(ensemble_models[0], MODELS_V2_DIR)

    duration = time.time() - start_time

    epochs_run = len(histories[0].history.get("loss", []))

    write_metadata(
        MODELS_V2_DIR,
        feature_names or [],
        feature_count=feature_count,
        train_samples=len(X_train),
        val_samples=len(X_val),
        test_samples=len(X_test),
        epochs_run=epochs_run,
        history=histories[0],
        test_metrics=test_metrics,
        class_weights=class_weights,
        training_data_range=training_data_range,
        parent_model_sha=parent_model_sha,
        decision_threshold=decision_threshold,
        threshold_metrics=threshold_metrics,
    )

    archive_current_model(MODELS_V2_DIR)

    write_training_log(
        TRAINING_LOGS_DIR,
        duration_seconds=duration,
        epochs_run=epochs_run,
        history=histories[0],
        test_metrics=test_metrics,
    )

    print(f"\nDone in {duration/60:.1f} min. Ensemble exported to {MODELS_V2_DIR}")
    print(f"Test accuracy: {test_metrics['accuracy']:.4f} | AUC: {test_metrics['auc']:.4f}")


if __name__ == "__main__":
    main()
