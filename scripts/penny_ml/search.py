"""Endless Penny Wolf ML search — all historical sub-$5 data, honest walk-forward IC.

Training runs on CPU (HistGradientBoosting). Champion exports to ONNX for
Snapdragon NPU inference via QNN/DirectML at scoring time.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor

from .config import CHAMPION, CHAMPION_JOBLIB, LEDGER, ML_DIR, STATUS, MODEL_DIR
from .features import FEATURE_NAMES
from .infer import export_champion_onnx
from .metrics import evaluate_oos, objective
from .panel import add_labels, build_panel
from .splits import walk_forward_folds

HORIZONS = [1, 3, 5, 10, 20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(doc: dict) -> None:
    ML_DIR.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _sample_config(rng: random.Random) -> dict:
    n_feat = rng.randint(8, min(18, len(FEATURE_NAMES)))
    feats = rng.sample(FEATURE_NAMES, n_feat)
    return {
        "horizon": rng.choice(HORIZONS),
        "features": feats,
        "max_depth": rng.choice([4, 6, 8, 10]),
        "learning_rate": rng.choice([0.03, 0.05, 0.08, 0.12]),
        "max_iter": rng.choice([200, 350, 500]),
        "min_samples_leaf": rng.choice([20, 40, 80, 120]),
        "l2_regularization": rng.choice([0.0, 0.1, 0.5, 1.0]),
    }


def _run_trial(panel: pd.DataFrame, cfg: dict, rng: random.Random) -> tuple[pd.DataFrame, dict]:
    h = cfg["horizon"]
    feats = cfg["features"]
    labeled = add_labels(panel, h)
    if labeled.empty or len(labeled["date"].unique()) < 30:
        return pd.DataFrame(), {"valid": False}

    folds = walk_forward_folds(labeled["date"], n_splits=5, label_horizon=h)
    if not folds:
        return pd.DataFrame(), {"valid": False}

    oos_parts = []
    for fold in folds:
        tr = labeled[labeled["date"].isin(fold.train_dates)]
        te = labeled[labeled["date"].isin(fold.test_dates)]
        if len(tr) < 500 or len(te) < 100:
            continue
        X_tr = tr[feats].to_numpy(dtype=np.float64)
        y_tr = tr["y_ret"].to_numpy(dtype=np.float64)
        X_te = te[feats].to_numpy(dtype=np.float64)
        model = HistGradientBoostingRegressor(
            max_depth=cfg["max_depth"],
            learning_rate=cfg["learning_rate"],
            max_iter=cfg["max_iter"],
            min_samples_leaf=cfg["min_samples_leaf"],
            l2_regularization=cfg["l2_regularization"],
            random_state=rng.randint(0, 2**31 - 1),
        )
        model.fit(X_tr, y_tr)
        te = te.copy()
        te["score"] = model.predict(X_te)
        oos_parts.append(te)

    if not oos_parts:
        return pd.DataFrame(), {"valid": False}
    oos = pd.concat(oos_parts, ignore_index=True)
    metrics = evaluate_oos(oos)
    return oos, metrics


def _load_champion() -> dict | None:
    if not CHAMPION.exists():
        return None
    try:
        return json.loads(CHAMPION.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _promote(trial: dict, panel: pd.DataFrame) -> None:
    cfg = trial["config"]
    labeled = add_labels(panel, cfg["horizon"])
    feats = cfg["features"]
    tr = labeled[labeled["date"] < labeled["date"].quantile(0.8)]
    model = HistGradientBoostingRegressor(
        max_depth=cfg["max_depth"],
        learning_rate=cfg["learning_rate"],
        max_iter=cfg["max_iter"],
        min_samples_leaf=cfg["min_samples_leaf"],
        l2_regularization=cfg["l2_regularization"],
        random_state=42,
    )
    X = tr[feats].to_numpy(dtype=np.float64)
    y = tr["y_ret"].to_numpy(dtype=np.float64)
    model.fit(X, y)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "config": cfg, "features": feats}, CHAMPION_JOBLIB)
    # HistGradientBoosting does not convert to ONNX; mirror with ExtraTrees for NPU path.
    n = len(X)
    cap = 120_000
    if n > cap:
        idx = np.random.default_rng(42).choice(n, cap, replace=False)
        X_et, y_et = X[idx], y[idx]
    else:
        X_et, y_et = X, y
    et = ExtraTreesRegressor(
        n_estimators=80, max_depth=cfg["max_depth"], min_samples_leaf=cfg["min_samples_leaf"],
        n_jobs=-1, random_state=42,
    )
    et.fit(X_et.astype(np.float32), y_et)
    onnx = export_champion_onnx(et, feats)
    trial["onnx"] = onnx
    trial["onnxNote"] = "ExtraTrees shadow of HGB champion for ONNX/NPU inference"
    CHAMPION.write_text(json.dumps(trial, indent=2), encoding="utf-8")


def run_search(*, max_trials: int | None = None, seed: int | None = None,
               refresh_panel: bool = False) -> dict:
    from npu_runtime import write_status as npu_status

    npu_status({"pennyMlSearch": True})
    rng = random.Random(seed if seed is not None else int(time.time()))
    _write_status({"phase": "building_panel", "startedAt": _now()})
    print("[penny-ml] building penny panel from all historical data ...", flush=True)
    panel = build_panel(refresh=refresh_panel)
    print(f"[penny-ml] panel rows={len(panel):,} symbols={panel['symbol'].nunique()}", flush=True)

    champ = _load_champion()
    best_obj = champ.get("objective", -9.0) if champ else -np.inf
    done = 0
    if LEDGER.exists():
        with open(LEDGER, encoding="utf-8") as fh:
            done = sum(1 for _ in fh)

    trial_n = 0
    _write_status({
        "phase": "searching",
        "panelRows": len(panel),
        "symbols": int(panel["symbol"].nunique()) if len(panel) else 0,
        "trialsDone": done,
        "bestObjective": best_obj,
        "championId": champ.get("trialId") if champ else None,
    })

    with open(LEDGER, "a", encoding="utf-8") as ledger:
        while max_trials is None or trial_n < max_trials:
            trial_n += 1
            cfg = _sample_config(rng)
            t0 = time.time()
            try:
                _, metrics = _run_trial(panel, cfg, rng)
                obj = objective(metrics, cfg["horizon"])
            except Exception as exc:
                print(f"[penny-ml] trial error: {exc}", flush=True)
                metrics = {"valid": False, "error": str(exc)[:200]}
                obj = -9.0
            trial = {
                "trialId": uuid.uuid4().hex[:12],
                "ts": _now(),
                "config": cfg,
                "metrics": metrics,
                "objective": round(obj, 6),
                "elapsedSec": round(time.time() - t0, 1),
            }
            ledger.write(json.dumps(trial) + "\n")
            ledger.flush()

            if metrics.get("valid") and obj > best_obj and (metrics.get("quintile_spread") or 0) > 0:
                best_obj = obj
                trial["promoted"] = True
                try:
                    _promote(trial, panel)
                    champ = trial
                    print(f"[penny-ml] CHAMPION trial={trial['trialId']} obj={obj:.4f} "
                          f"IC={metrics.get('mean_ic')} spread={metrics.get('quintile_spread')}", flush=True)
                except Exception as exc:
                    print(f"[penny-ml] promote failed: {exc}", flush=True)
                    trial["promoteError"] = str(exc)[:200]

            if trial_n % 10 == 0:
                ic = metrics.get("mean_ic")
                sp = metrics.get("quintile_spread")
                print(f"[penny-ml] trial {done + trial_n} h={cfg['horizon']} "
                      f"IC={ic} spread={sp} obj={obj:.4f} best={best_obj:.4f}", flush=True)
                _write_status({
                    "phase": "searching",
                    "trialsDone": done + trial_n,
                    "bestObjective": best_obj,
                    "lastTrial": trial,
                    "championId": champ.get("trialId") if champ else None,
                })

    _write_status({"phase": "complete", "trialsDone": done + trial_n, "bestObjective": best_obj,
                   "finishedAt": _now()})
    return {"trials": trial_n, "bestObjective": best_obj, "champion": champ}


def main() -> int:
    ap = argparse.ArgumentParser(description="Penny Wolf ML champion search")
    ap.add_argument("--trials", type=int, default=0, help="0 = run forever")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--refresh-panel", action="store_true")
    args = ap.parse_args()
    max_t = args.trials if args.trials > 0 else None
    run_search(max_trials=max_t, seed=args.seed, refresh_panel=args.refresh_panel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
