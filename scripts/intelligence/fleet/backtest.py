"""Historical walk-forward — weed out genomes on a real out-of-sample year.

Predictor v3 is trained on <=2023 (9 years). test.csv holds the 2025+ forward
year with predictions AND realized next-day returns. We spawn a pool of genomes
and walk EACH forward day-by-day over that year using REAL realized returns
(not pred_ret), then rank by forward Sharpe/return. Survivors are genomes whose
decision rules actually made money out-of-sample.

  python scripts/intelligence/fleet/backtest.py --genomes 200
  python scripts/intelligence/fleet/backtest.py --genomes 200 --promote 3

--promote N: add the top N survivors to the live fleet (they then walk forward
on the current panel too).
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
TEST_CSV = REPO / "data" / "predictions_v3" / "test.csv"
OUT = REPO / "data" / "intelligence" / "fleet" / "walkforward.json"
RET_COLS = ["y_ret", "fwd_ret", "forward_ret", "realized_ret", "target_ret", "ret_fwd_1"]
FAMILIES = ("momentum_long", "contrarian", "ml_edge", "short_bias",
            "long_short_neutral", "high_conviction", "low_vol", "diversified",
            "sentiment_rider", "earnings_drift", "mean_reverter", "breakout")
COST_BPS = 7.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _spawn_genomes(n: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        fam = rng.choice(FAMILIES)
        short_on = fam in {"short_bias", "long_short_neutral", "mean_reverter"} or rng.random() < 0.45
        out.append({
            "id": f"wf_{i:04d}",
            "family": fam,
            # Wider search space to discover new strategy regimes.
            "min_proba": round(rng.uniform(0.50, 0.70), 3),
            "min_pred_ret": round(rng.uniform(0.002, 0.04), 4),
            "top_k": rng.randint(3, 30),
            "kelly": round(rng.uniform(0.15, 1.0), 3),
            "short_enabled": short_on,
            "short_frac": round(rng.uniform(0.05, 0.60) if short_on else 0.0, 3),
        })
    return out


def _per_date_arrays(df: pd.DataFrame, ret_col: str) -> list[tuple]:
    days = []
    for d, g in df.groupby("date", sort=True):
        proba = g["pred_proba_up"].to_numpy(dtype="float64")
        pr = g["pred_ret"].to_numpy(dtype="float64")
        # Clip realized returns to +/-15%/day — kills data-artifact / illiquid blowups
        # that would otherwise make compounded returns fantasy.
        ret = np.clip(g[ret_col].to_numpy(dtype="float64"), -0.15, 0.15)
        edge = (2.0 * proba - 1.0) * np.abs(pr)
        days.append((str(d), proba, pr, ret, edge))
    return days


def _metrics(arr: np.ndarray) -> dict:
    if arr.size == 0:
        return {"sharpe": None, "totalReturnPct": None, "hitRate": None, "maxDrawdownPct": None, "nDays": 0}
    eq = np.cumprod(1.0 + arr)
    total = (eq[-1] - 1.0) * 100.0
    sd = arr.std(ddof=0)
    sharpe = float(arr.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min() * 100.0)
    active = arr[arr != 0]
    hit = float((active > 0).mean()) if active.size else 0.0
    return {"sharpe": round(sharpe, 3), "totalReturnPct": round(total, 2),
            "hitRate": round(hit, 3), "maxDrawdownPct": round(mdd, 2),
            "nDays": int((arr != 0).sum())}


def _side_return(mask, edge, ret, proba, top_k, sign):
    idx = np.where(mask)[0]
    if idx.size == 0:
        return 0.0, 0.0
    if idx.size > top_k:
        # top_k by |edge|
        sel = idx[np.argsort(edge[idx])[::-1][:top_k]]
    else:
        sel = idx
    w = np.clip(2.0 * proba[sel] - 1.0, 0.01, None) if sign > 0 else np.clip(1.0 - 2.0 * proba[sel], 0.01, None)
    if w.sum() <= 0:
        return 0.0, 0.0
    w = w / w.sum()
    # long: +ret; short: profit when ret<0 -> -ret
    contrib = float(np.sum(w * (ret[sel] if sign > 0 else -ret[sel])))
    return contrib, 1.0


def _walk(genome: dict, days: list[tuple]) -> np.ndarray:
    short_frac = genome["short_frac"] if genome["short_enabled"] else 0.0
    long_gross = 0.9 * (1.0 - short_frac)
    short_gross = 0.9 * short_frac
    mp, mpr, tk = genome["min_proba"], genome["min_pred_ret"], genome["top_k"]
    daily = []
    for _, proba, pr, ret, edge in days:
        lr, lon = _side_return((proba >= mp) & (pr >= mpr), edge, ret, proba, tk, +1)
        sr = son = 0.0
        if short_gross > 0:
            sr, son = _side_return((proba <= 1 - mp) & (pr <= -mpr), edge, ret, proba, max(1, int(tk * short_frac)), -1)
        gross = long_gross * lon + short_gross * son
        day_ret = long_gross * lr + short_gross * sr - gross * COST_BPS / 1e4
        daily.append(day_ret)
    return np.array(daily, dtype="float64")


def run(n_genomes: int = 200, promote: int = 0) -> dict:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not TEST_CSV.exists():
        doc = {"generatedAt": _now(), "ok": False, "message": "no test.csv — train predictor first"}
        OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    df = pd.read_csv(TEST_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    ret_col = next((c for c in RET_COLS if c in df.columns), None)
    if ret_col is None or "pred_proba_up" not in df.columns or "date" not in df.columns:
        doc = {"generatedAt": _now(), "ok": False, "message": f"test.csv missing realized return / pred / date (cols={list(df.columns)})"}
        OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date", "pred_proba_up", "pred_ret", ret_col])

    # Tradeable universe only (realism).
    try:
        from intelligence.tradeable_universe import is_tradeable
        ok_syms = {s for s in df["symbol"].unique() if is_tradeable(s)[0]}
        df = df[df["symbol"].isin(ok_syms)]
    except Exception:
        pass

    days = _per_date_arrays(df, ret_col)
    # Honest split: SELECT genomes on the first 60%, JUDGE them on the held-out tail
    # they never influenced. This is what separates real rules from curve-fits.
    split = int(len(days) * 0.6)
    sel_days, hold_days = days[:split], days[split:]
    genomes = _spawn_genomes(n_genomes)

    rows = []
    for g in genomes:
        full = _walk(g, days)
        sel = _metrics(full[:split])
        hold = _metrics(full[split:])
        if sel["nDays"] >= 15 and hold["nDays"] >= 10:
            rows.append({**g, "selection": sel, "holdout": hold})

    # Rank by SELECTION sharpe (what we'd pick on), then read the HOLDOUT truth.
    rows.sort(key=lambda r: (r["selection"]["sharpe"] if r["selection"]["sharpe"] is not None else -9), reverse=True)
    # Survivors = strong in selection AND still positive on the unseen holdout.
    survivors = [r for r in rows if (r["selection"]["sharpe"] or 0) >= 0.5 and (r["holdout"]["sharpe"] or 0) > 0][:max(1, int(len(rows) * 0.15))]
    held_up = sum(1 for r in rows[:max(1, int(len(rows) * 0.15))] if (r["holdout"]["sharpe"] or 0) > 0)
    top_sel = max(1, int(len(rows) * 0.15))

    def _lead(r, i):
        return {"rank": i + 1, "id": r["id"], "family": r["family"],
                "selSharpe": r["selection"]["sharpe"], "holdSharpe": r["holdout"]["sharpe"],
                "holdReturnPct": r["holdout"]["totalReturnPct"], "holdHitRate": r["holdout"]["hitRate"],
                "holdMaxDdPct": r["holdout"]["maxDrawdownPct"], "holdDays": r["holdout"]["nDays"],
                "top_k": r["top_k"], "kelly": r["kelly"], "short_enabled": r["short_enabled"]}

    best_hold = max(rows, key=lambda r: (r["holdout"]["sharpe"] or -9)) if rows else None
    doc = {
        "generatedAt": _now(), "ok": True,
        "window": {"start": days[0][0] if days else None, "end": days[-1][0] if days else None,
                   "nDays": len(days), "selectionDays": len(sel_days), "holdoutDays": len(hold_days)},
        "nGenomes": len(genomes), "nScored": len(rows), "costBps": COST_BPS,
        "method": "Select on first 60% of the OOS year; judge on the held-out 40%. Returns clipped \u00b115%/day.",
        "caveat": "All genomes consume the SAME predictor signal on the SAME test window, so they are highly correlated \u2014 'survivors' ride one persisting predictor edge, not independent skill. This window is also the predictor's own test set. Treat holdout Sharpe as an UPPER BOUND. The only real proof is forward paper on unseen future data: promote survivors to the live fleet and let them earn it.",
        "topSelectionHeldUp": f"{held_up}/{top_sel}",
        "leaderboard": [_lead(r, i) for i, r in enumerate(rows[:25])],
        "survivors": survivors,
        "verdict": (
            f"Of the top {top_sel} genomes picked on selection, {held_up} stayed positive on the unseen holdout. "
            f"Best holdout: Sharpe {best_hold['holdout']['sharpe']}, {best_hold['holdout']['totalReturnPct']}% over {best_hold['holdout']['nDays']}d."
            if rows else "no genomes scored"
        ),
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[walk-forward] {len(genomes)} genomes | top-{top_sel} held up {held_up}/{top_sel} on holdout | "
          f"best holdout Sharpe={best_hold['holdout']['sharpe'] if best_hold else '-'} "
          f"ret={best_hold['holdout']['totalReturnPct'] if best_hold else '-'}%", flush=True)

    if promote and survivors:
        _promote_survivors(survivors[:promote])
    try:
        from intelligence.brain.journal import log_fleet_walkforward
        log_fleet_walkforward(doc)
    except Exception as exc:
        print(f"[brain-journal] skip walkforward log: {exc}", flush=True)
    return doc


def _sig(s: dict) -> str:
    import hashlib
    raw = "|".join(str(s.get(k)) for k in ("family", "min_proba", "min_pred_ret", "top_k", "kelly", "short_enabled", "short_frac"))
    return hashlib.sha1(raw.encode()).hexdigest()[:6]


def _promote_survivors(survivors: list[dict]) -> None:
    """Add top walk-forward survivors to the live fleet so they walk forward live too.

    Stable params-hash id => re-promoting the same genome is a no-op (keeps its
    forward track record); only genuinely new survivors are added.
    """
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    from intelligence.fleet import registry
    reg = registry.load_registry()
    existing = {a["id"] for a in reg.get("agents", [])}
    names = ["Blackfin", "Hex", "Cog", "Bolt", "Salty", "Rivet", "Gizmo", "Patch"]
    added = 0
    for i, s in enumerate(survivors):
        sig = _sig(s)
        aid = f"wf_{sig}"
        if aid in existing:
            continue
        existing.add(aid)
        ho = s.get("holdout", {})
        reg["agents"].append({
            "id": aid, "name": f"WF-{names[i % len(names)]}-{sig[:3]}", "kind": "genome",
            "status": "shadow", "capital": 100000.0,
            "blurb": f"Walk-forward survivor ({s['family']}): held up out-of-sample "
                     f"(holdout Sharpe {ho.get('sharpe')}, {ho.get('totalReturnPct')}% over {ho.get('nDays')}d).",
            "params": {k: s[k] for k in ("family", "min_proba", "min_pred_ret", "top_k", "kelly", "short_enabled", "short_frac")},
            "createdAt": _now(), "origin": "walkforward",
        })
        added += 1
    registry.save_registry(reg)
    print(f"[walk-forward] promoted {added} survivors into the live fleet", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--genomes", type=int, default=200)
    ap.add_argument("--promote", type=int, default=0)
    args = ap.parse_args()
    run(n_genomes=args.genomes, promote=args.promote)
