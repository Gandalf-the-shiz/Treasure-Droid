"""Score a single symbol from recent candles (NPU ONNX or joblib fallback)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CHAMPION, CHAMPION_JOBLIB
from .features import features_from_candles
from .infer import predict_matrix


def champion_meta() -> dict | None:
    if not CHAMPION.exists():
        return None
    try:
        return json.loads(CHAMPION.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def score_candles(candles: list) -> dict | None:
    """Return {score, trialId, horizon, backend} or None if no champion / bad data."""
    meta = champion_meta()
    if not meta:
        return None
    if len(candles) < 80:
        return None
    cfg = meta.get("config") or {}
    feat_cols = cfg.get("features") or []
    if not feat_cols:
        return None

    raw = pd.DataFrame(candles)
    if "date" not in raw.columns or "close" not in raw.columns:
        return None
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"]).sort_values("date")
    for c in ("open", "high", "low", "close", "volume"):
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = raw.dropna(subset=["close"])
    if len(raw) < 80:
        return None

    feats = features_from_candles(raw.set_index("date"))
    row = feats.iloc[-1]
    if row[feat_cols].isna().any():
        return None
    X = row[feat_cols].to_numpy(dtype=np.float32).reshape(1, -1)

    score = float("nan")
    backend = "none"
    try:
        pred = predict_matrix(X)
        if np.isfinite(pred[0]):
            score = float(pred[0])
            backend = "onnx"
    except Exception:
        pass

    if not np.isfinite(score) and CHAMPION_JOBLIB.exists():
        try:
            import joblib
            blob = joblib.load(CHAMPION_JOBLIB)
            model = blob.get("model")
            if model is not None:
                score = float(model.predict(X.astype(np.float64))[0])
                backend = "joblib"
        except Exception:
            return None

    if not np.isfinite(score):
        return None

    return {
        "score": score,
        "trialId": meta.get("trialId"),
        "horizon": cfg.get("horizon"),
        "backend": backend,
        "objective": meta.get("objective"),
        "meanIc": (meta.get("metrics") or {}).get("mean_ic"),
    }
