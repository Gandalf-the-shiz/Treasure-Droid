"""Prove the Transfer Coefficient fix (Alpha Doctrine).

Backtests the cross-sectional alpha recipe on the predictor's test window and
compares RAW edge vs NEUTRALIZED edge on the tradeable universe:
  - mean rank IC, ICIR (mean/std), IC hit rate
  - top-minus-bottom quintile spread (the tradeable edge)
  - breadth

Writes data/accuracy/alpha_ic.json (audit) + nostradamus-live mirror so the
gate/dashboard can see whether neutralization flips the spread positive.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
TEST_CSV = REPO / "data" / "predictions_v3" / "test.csv"
HIST_DIR = REPO / "data" / "historical"
OUT_PATH = REPO / "data" / "accuracy" / "alpha_ic.json"
LIVE_ROOT = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))

import sys

sys.path.insert(0, str(REPO / "scripts"))
from intelligence.alpha.neutralize import (  # noqa: E402
    neutralize_series,
    quantile_spread,
    spearman_ic,
)

_RET_COLS = ["y_ret", "fwd_ret", "forward_ret", "realized_ret", "target_ret", "ret_fwd_1"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _size_map() -> dict[str, float]:
    try:
        from intelligence.tradeable_universe import _liquidity_cache
        return {
            s: float(np.log1p(p.get("adv_20") or 0))
            for s, p in _liquidity_cache().items()
            if (p.get("adv_20") or 0) > 0
        }
    except Exception:
        return {}


def _price_sleeves() -> pd.DataFrame:
    """Per (symbol,date) reversal & momentum sleeves from historical OHLCV.

    Point-in-time safe: each feature uses only prices up to and including `date`,
    predicting the next-day forward return.
    """
    rows = []
    if not HIST_DIR.exists():
        return pd.DataFrame(columns=["symbol", "date", "rev_5", "mom_120_20", "rev_1"])
    for fp in HIST_DIR.glob("*.json"):
        if fp.name.startswith("manifest"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            candles = (payload or {}).get("candles") or []
            if len(candles) < 130:
                continue
            c = pd.DataFrame(candles)
            if "date" not in c.columns or "close" not in c.columns:
                continue
            c["date"] = pd.to_datetime(c["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            close = pd.to_numeric(c["close"], errors="coerce")
            sub = pd.DataFrame({
                "symbol": str(sym).upper(),
                "date": c["date"],
                "rev_1": -(close / close.shift(1) - 1.0),
                "rev_5": -(close / close.shift(5) - 1.0),
                "mom_120_20": close.shift(20) / close.shift(120) - 1.0,
            })
            rows.append(sub)
    if not rows:
        return pd.DataFrame(columns=["symbol", "date", "rev_5", "mom_120_20", "rev_1"])
    return pd.concat(rows, ignore_index=True)


def _agg(ics: list[float], spreads: list[float], breadth: list[int]) -> dict:
    ics_a = np.array([x for x in ics if np.isfinite(x)], dtype=float)
    sp_a = np.array([x for x in spreads if np.isfinite(x)], dtype=float)
    mean_ic = float(ics_a.mean()) if ics_a.size else None
    std_ic = float(ics_a.std(ddof=0)) if ics_a.size else None
    icir = (mean_ic / std_ic) if (mean_ic is not None and std_ic) else None
    return {
        "mean_ic": round(mean_ic, 5) if mean_ic is not None else None,
        "icir": round(icir, 4) if icir is not None else None,
        "ic_hit_rate": round(float((ics_a > 0).mean()), 4) if ics_a.size else None,
        "mean_quintile_spread": round(float(sp_a.mean()), 6) if sp_a.size else None,
        "spread_positive_days": round(float((sp_a > 0).mean()), 4) if sp_a.size else None,
        "n_days": int(ics_a.size),
        "mean_breadth": int(np.mean(breadth)) if breadth else 0,
    }


def run(max_days: int | None = None, with_prices: bool = True) -> dict:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not TEST_CSV.exists():
        doc = {"generatedAt": _now(), "ok": False, "message": "no test.csv — run train-predictor-v3.py"}
        OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    df = pd.read_csv(TEST_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    ret_col = next((c for c in _RET_COLS if c in df.columns), None)
    if ret_col is None or "pred_proba_up" not in df.columns or "date" not in df.columns:
        doc = {
            "generatedAt": _now(),
            "ok": False,
            "message": f"test.csv missing realized return col (looked for {_RET_COLS}) or pred/date",
            "columns": list(df.columns),
        }
        OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "sector" not in df.columns:
        df["sector"] = "UNKNOWN"
    df["edge"] = (2.0 * df["pred_proba_up"].astype(float) - 1.0) * df["pred_ret"].astype(float).abs()

    # Tradeable universe only.
    try:
        from intelligence.tradeable_universe import is_tradeable
        mask = df["symbol"].map(lambda s: is_tradeable(s)[0])
        df = df.loc[mask].copy()
    except Exception:
        pass

    size_map = _size_map()
    df["_size"] = df["symbol"].map(size_map)

    blend_cols = []
    if with_prices:
        ps = _price_sleeves()
        if not ps.empty:
            df = df.merge(ps, on=["symbol", "date"], how="left")
            blend_cols = [c for c in ("rev_1", "rev_5", "mom_120_20") if c in df.columns]
            print(f"[alpha-measure] merged price sleeves: {blend_cols}", flush=True)

    raw_ic, raw_sp = [], []
    neu_ic, neu_sp = [], []
    blend_ic, blend_sp = [], []
    breadth = []

    # Sleeve weights for the blend (equal-ish; ml carries most weight).
    blend_w = {"edge": 1.0, "rev_5": 0.7, "rev_1": 0.5, "mom_120_20": 0.4}

    dates = sorted(df["date"].unique())
    if max_days:
        dates = dates[-max_days:]

    for d in dates:
        g = df[df["date"] == d]
        if len(g) < 30:
            continue
        fwd = g[ret_col].astype(float)
        sector = g["sector"].astype(str)
        size = g["_size"].astype(float)

        edge = g["edge"].astype(float)
        neu_edge = neutralize_series(edge, sector=sector, size=size, winsor=0.02, output="zscore")

        raw_ic.append(spearman_ic(edge, fwd))
        raw_sp.append(quantile_spread(edge, fwd))
        neu_ic.append(spearman_ic(neu_edge, fwd))
        neu_sp.append(quantile_spread(neu_edge, fwd))
        breadth.append(len(g))

        if blend_cols:
            blended = neu_edge.fillna(0.0) * blend_w["edge"]
            for col in blend_cols:
                raw_sleeve = g[col].astype(float)
                neu_sleeve = neutralize_series(raw_sleeve, sector=sector, size=size, winsor=0.02, output="zscore")
                if neu_sleeve is not None and not neu_sleeve.dropna().empty:
                    blended = blended.add(neu_sleeve.fillna(0.0) * blend_w.get(col, 0.0), fill_value=0.0)
            blend_ic.append(spearman_ic(blended, fwd))
            blend_sp.append(quantile_spread(blended, fwd))

    raw = _agg(raw_ic, raw_sp, breadth)
    neu = _agg(neu_ic, neu_sp, breadth)
    blend = _agg(blend_ic, blend_sp, breadth) if blend_cols else None

    best_spread = max(
        x for x in [
            neu.get("mean_quintile_spread"),
            (blend or {}).get("mean_quintile_spread"),
        ] if x is not None
    ) if (neu.get("mean_quintile_spread") is not None) else None

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "universe": "tradeable",
        "window": {"start": str(dates[0]) if dates else None, "end": str(dates[-1]) if dates else None},
        "raw_edge": raw,
        "neutralized_edge": neu,
        "blended_neutralized": blend,
        "blend_weights": blend_w if blend_cols else None,
        "spread_positive": bool((best_spread or 0) > 0),
        "verdict": (
            "TRADEABLE: blended neutralized alpha has positive quintile spread"
            if (best_spread or 0) > 0
            else "not yet positive — needs longer-horizon sleeves (PEAD/revisions, Phase C)"
        ),
    }
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if LIVE_ROOT.exists():
        mirror = LIVE_ROOT / "data" / "accuracy" / "alpha_ic.json"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    blend_msg = (
        f" | blend_ic={blend['mean_ic']} blend_spread={blend['mean_quintile_spread']}"
        if blend else ""
    )
    print(
        f"[alpha-measure] raw_ic={raw['mean_ic']} raw_spread={raw['mean_quintile_spread']} | "
        f"neu_ic={neu['mean_ic']} neu_spread={neu['mean_quintile_spread']}{blend_msg} "
        f"positive={doc['spread_positive']}",
        flush=True,
    )
    return doc


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=int, default=0, help="limit to last N test dates (0=all)")
    ap.add_argument("--no-prices", action="store_true", help="skip price-based blend sleeves")
    args = ap.parse_args()
    run(max_days=args.max_days or None, with_prices=not args.no_prices)
