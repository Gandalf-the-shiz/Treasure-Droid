"""Forward rank-IC for v3 live predictions vs realized returns.

Writes canonical gate schema to audit repo AND nostradamus-live (Mega Yacht 0.1).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
LIVE_CSV = REPO / "data" / "predictions_v3" / "live.csv"
HIST_DIR = REPO / "data" / "historical"
OUT_PATH = REPO / "data" / "accuracy" / "v3_live_ic.json"
LIVE_ROOT = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))
LIVE_IC_PATH = LIVE_ROOT / "data" / "accuracy" / "v3_live_ic.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_prices() -> dict[str, pd.DataFrame]:
    prices: dict[str, pd.DataFrame] = {}
    for fp in HIST_DIR.glob("*.json"):
        if fp.name.startswith("manifest"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            candles = (payload or {}).get("candles") or []
            if len(candles) < 5:
                continue
            df = pd.DataFrame(candles)
            if "date" not in df.columns or "close" not in df.columns:
                continue
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["date", "close"]).sort_values("date")
            prices[sym.upper()] = df.set_index("date")["close"]
    return prices


def _to_canonical(daily: list[dict], horizon_days: int) -> dict:
    points = [
        {"date": x["date"], "ic": x["ic"], "breadth": x.get("n", x.get("breadth", 0))}
        for x in daily
    ]
    ics = [p["ic"] for p in points if p["ic"] is not None and np.isfinite(p["ic"])]
    mean_ic = float(np.mean(ics)) if ics else None
    return {
        "updatedAt": _now(),
        "generatedAt": _now(),
        "source": "forward_score_audit",
        "universe": "tradeable",
        "horizonDays": horizon_days,
        "points": points,
        "n_days": len(ics),
        "mean_ic": round(mean_ic, 5) if mean_ic is not None else None,
        "hitRate": round(float(np.mean([i > 0 for i in ics])), 3) if ics else None,
        # Legacy aliases for dashboard bridge
        "nDays": len(ics),
        "meanRankIc": round(mean_ic, 5) if mean_ic is not None else None,
        "daily": daily[-60:],
    }


def _write_all(doc: dict) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if LIVE_ROOT.exists():
        LIVE_IC_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIVE_IC_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def score_live(horizon_days: int = 1) -> dict:
    from intelligence.tradeable_universe import is_tradeable

    if not LIVE_CSV.exists():
        doc = _to_canonical([], horizon_days)
        doc["message"] = "no live.csv"
        _write_all(doc)
        return doc

    preds = pd.read_csv(LIVE_CSV)
    if preds.empty or "symbol" not in preds.columns:
        doc = _to_canonical([], horizon_days)
        _write_all(doc)
        return doc

    score_col = "pred_proba_up" if "pred_proba_up" in preds.columns else "pred_ret"
    if "as_of" in preds.columns:
        preds["date"] = pd.to_datetime(preds["as_of"], errors="coerce")
    elif "date" in preds.columns:
        preds["date"] = pd.to_datetime(preds["date"], errors="coerce")
    else:
        preds["date"] = pd.Timestamp.utcnow().normalize()

    prices = _load_prices()
    ics = []
    for d, g in preds.groupby(preds["date"].dt.normalize()):
        fwd_rets = []
        scores = []
        for _, row in g.iterrows():
            sym = str(row["symbol"]).upper()
            ok, _ = is_tradeable(sym)
            if not ok:
                continue
            if sym not in prices:
                continue
            s = prices[sym]
            if d not in s.index:
                continue
            loc = s.index.get_indexer([d], method="pad")[0]
            if loc < 0 or loc + horizon_days >= len(s):
                continue
            r = float(s.iloc[loc + horizon_days] / s.iloc[loc] - 1.0)
            fwd_rets.append(r)
            scores.append(float(row[score_col]))
        if len(fwd_rets) >= 8:
            sr = pd.Series(scores).rank()
            fr = pd.Series(fwd_rets).rank()
            ic = float(sr.corr(fr))
            if np.isfinite(ic):
                ics.append({"date": str(d.date()), "ic": round(ic, 5), "n": len(fwd_rets)})

    doc = _to_canonical(ics, horizon_days)
    _write_all(doc)
    print(f"[forward-score] days={doc['n_days']} mean_ic={doc['mean_ic']}", flush=True)
    return doc


if __name__ == "__main__":
    score_live()
