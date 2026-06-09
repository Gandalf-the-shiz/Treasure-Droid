"""Fast intraday inference — latest-bar predictions without full retrain.

Writes data/predictions_v3/live.csv (one row per symbol, latest date).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
HIST = REPO / "data" / "historical"
MODEL_DIR = REPO / "models" / "v3" / "predictor"
OUT = REPO / "data" / "predictions_v3"

sys.path.insert(0, str(REPO / "scripts"))
from overlay_features import attach_all_overlays  # noqa: E402


def _load_tpv3():
    spec = importlib.util.spec_from_file_location(
        "train_predictor_v3", REPO / "scripts" / "train-predictor-v3.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _load_models(feature_cols: list[str]):
    seeds = []
    for p in MODEL_DIR.glob("clf_seed_*.joblib"):
        seeds.append(int(p.stem.split("_")[-1]))
    seeds = sorted(seeds) or [0]
    clfs = [joblib.load(MODEL_DIR / f"clf_seed_{s}.joblib") for s in seeds]
    meta = joblib.load(MODEL_DIR / "meta.joblib")
    cal = joblib.load(MODEL_DIR / "calibrator.joblib")
    reg = joblib.load(MODEL_DIR / "reg.joblib")
    return clfs, meta, cal, reg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.getenv("LIVE_PREDICT_LIMIT", "2500")), help="max tickers to score")
    args = ap.parse_args()

    feat_path = MODEL_DIR / "feature_columns.json"
    if not feat_path.exists():
        raise SystemExit("missing models — run train-predictor-v3.py first")
    feature_cols: list[str] = json.loads(feat_path.read_text(encoding="utf-8"))
    clfs, meta, cal, reg = _load_models(feature_cols)
    tpv3 = _load_tpv3()

    frames: list[pd.DataFrame] = []
    n = 0
    t0 = time.time()
    for fp in sorted(HIST.glob("*.json")):
        if fp.name in {"manifest.json", "multiyear-coverage.json", "stooq-bulk-coverage.json"}:
            continue
        sector = fp.stem
        data = json.loads(fp.read_text(encoding="utf-8"))
        for sym, payload in (data.get("stocks") or {}).items():
            if args.limit and n >= args.limit:
                break
            candles = (payload or {}).get("candles") or []
            df = tpv3.build_features_for_ticker(sym, sector, candles)
            if df is None or df.empty:
                continue
            frames.append(df.tail(1))
            n += 1
        if args.limit and n >= args.limit:
            break

    if not frames:
        raise SystemExit("no live rows built")
    live = pd.concat(frames, ignore_index=True)
    live = attach_all_overlays(live, date_col="date")
    for c in feature_cols:
        if c not in live.columns:
            live[c] = 0.0
    X = live[feature_cols].to_numpy(dtype=np.float32)
    base = np.column_stack([c.predict_proba(X)[:, 1] for c in clfs])
    proba = cal.transform(meta.predict_proba(base)[:, 1])
    pred_ret = reg.predict(X)
    out = live[["date", "symbol", "sector"]].copy()
    out["pred_proba_up"] = proba
    out["pred_ret"] = pred_ret
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT / "live.csv", index=False)
    print(f"[live] {len(out):,} symbols @ {out['date'].iloc[0]} in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
