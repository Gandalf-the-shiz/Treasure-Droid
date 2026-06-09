"""Mad Scientist Lab — day-by-day walk-forward on the historical panel.

Train window: predictor v3 trained on <=2023 (8 years of OHLCV).
Walk-forward: 2024-2025 panel with ML preds + alpha frame + realized returns.

Spawns hundreds of genomes, selects on first 60% of walk-forward days, judges on
held-out tail, promotes survivors to the live fleet.

Usage:
  python scripts/intelligence/historical/panel_builder.py
  python scripts/intelligence/historical/walkforward_lab.py --genomes 500 --promote 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
PANEL_PARQUET = REPO / "data" / "intelligence" / "historical" / "panel.parquet"
PANEL_CSV = REPO / "data" / "intelligence" / "historical" / "panel.csv.gz"


def _load_panel() -> pd.DataFrame:
    if PANEL_PARQUET.exists():
        return pd.read_parquet(PANEL_PARQUET)
    if PANEL_CSV.exists():
        return pd.read_csv(PANEL_CSV, compression="gzip")
    raise FileNotFoundError("no panel — run panel_builder.py")
META_PATH = REPO / "data" / "intelligence" / "historical" / "panel_meta.json"
OUT_PATH = REPO / "data" / "intelligence" / "historical" / "lab_results.json"
CONFIG_PATH = REPO / "config" / "mad_scientist_lab.json"

sys.path.insert(0, str(REPO / "scripts"))

FAMILIES = (
    "alpha_neutral", "ml_edge", "momentum_long", "contrarian", "ml_edge", "short_bias",
    "long_short_neutral", "high_conviction", "mean_reverter", "breakout",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_config() -> dict:
    defaults = {
        "genomes": 500,
        "promote_top": 5,
        "selection_frac": 0.6,
        "cost_bps": 7.0,
        "return_clip": 0.15,
        "min_selection_days": 20,
        "min_holdout_days": 15,
    }
    if CONFIG_PATH.exists():
        try:
            defaults.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return defaults


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
    return {
        "sharpe": round(sharpe, 3),
        "totalReturnPct": round(total, 2),
        "hitRate": round(hit, 3),
        "maxDrawdownPct": round(mdd, 2),
        "nDays": int((arr != 0).sum()),
    }


def _per_date_arrays(df: pd.DataFrame) -> list[tuple]:
    days = []
    for d, g in df.groupby("date", sort=True):
        if len(g) < 30:
            continue
        proba = g["pred_proba_up"].to_numpy(dtype="float64")
        pr = g["pred_ret"].to_numpy(dtype="float64")
        ret = np.clip(g["y_ret"].to_numpy(dtype="float64"), -0.15, 0.15)
        edge = (2.0 * proba - 1.0) * np.abs(pr)
        alpha = g["alpha"].to_numpy(dtype="float64") if "alpha" in g.columns else edge.copy()
        days.append((str(d), proba, pr, ret, edge, alpha))
    return days


def _side_return(mask, signal, ret, proba, top_k, sign):
    idx = np.where(mask)[0]
    if idx.size == 0:
        return 0.0, 0.0
    if idx.size > top_k:
        sel = idx[np.argsort(signal[idx])[::-1][:top_k]]
    else:
        sel = idx
    w = np.clip(2.0 * proba[sel] - 1.0, 0.01, None) if sign > 0 else np.clip(1.0 - 2.0 * proba[sel], 0.01, None)
    if w.sum() <= 0:
        return 0.0, 0.0
    w = w / w.sum()
    contrib = float(np.sum(w * (ret[sel] if sign > 0 else -ret[sel])))
    return contrib, 1.0


def _walk(genome: dict, days: list[tuple], cost_bps: float) -> np.ndarray:
    short_frac = genome["short_frac"] if genome["short_enabled"] else 0.0
    long_gross = 0.9 * (1.0 - short_frac)
    short_gross = 0.9 * short_frac
    mp, mpr, tk = genome["min_proba"], genome["min_pred_ret"], genome["top_k"]
    use_alpha = genome.get("signal") == "alpha"
    daily = []
    for _, proba, pr, ret, edge, alpha in days:
        sig = alpha if use_alpha else edge
        lr, lon = _side_return((proba >= mp) & (pr >= mpr), sig, ret, proba, tk, +1)
        sr = son = 0.0
        if short_gross > 0:
            sr, son = _side_return(
                (proba <= 1 - mp) & (pr <= -mpr), -sig, ret, proba, max(1, int(tk * short_frac)), -1
            )
        gross = long_gross * lon + short_gross * son
        day_ret = long_gross * lr + short_gross * sr - gross * cost_bps / 1e4
        daily.append(day_ret)
    return np.array(daily, dtype="float64")


def _spawn_genomes(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        fam = rng.choice(FAMILIES)
        short_on = fam in {"short_bias", "long_short_neutral", "alpha_neutral", "mean_reverter"} or rng.random() < 0.5
        signal = "alpha" if fam in {"alpha_neutral", "long_short_neutral"} or rng.random() < 0.35 else "edge"
        out.append({
            "id": f"ms_{i:04d}",
            "family": fam,
            "signal": signal,
            "min_proba": round(rng.uniform(0.50, 0.68), 3),
            "min_pred_ret": round(rng.uniform(0.002, 0.035), 4),
            "top_k": rng.randint(5, 35),
            "kelly": round(rng.uniform(0.2, 1.0), 3),
            "short_enabled": short_on,
            "short_frac": round(rng.uniform(0.3, 0.55) if short_on else 0.0, 3),
        })
    return out


def _sig(s: dict) -> str:
    raw = "|".join(str(s.get(k)) for k in ("family", "signal", "min_proba", "min_pred_ret", "top_k", "kelly", "short_enabled", "short_frac"))
    return hashlib.sha1(raw.encode()).hexdigest()[:8]


def _promote_survivors(survivors: list[dict]) -> int:
    from intelligence.fleet.registry import load_registry, save_registry

    reg = load_registry()
    agents = reg.get("agents") or []
    existing = {a["id"] for a in agents}
    added = 0
    for s in survivors:
        sig = _sig(s)
        aid = f"ms_{sig}"
        if aid in existing:
            continue
        agents.append({
            "id": aid,
            "name": f"MS-{s['family'][:8]}-{sig}",
            "strategy": "genome",
            "status": "shadow",
            "spawnedBy": "mad_scientist_lab",
            "params": {
                "family": s["family"],
                "signal": s.get("signal", "edge"),
                "min_proba": s["min_proba"],
                "min_pred_ret": s["min_pred_ret"],
                "top_k": s["top_k"],
                "kelly": s["kelly"],
                "short_enabled": s["short_enabled"],
                "short_frac": s["short_frac"],
            },
            "labHoldoutSharpe": s.get("holdout", {}).get("sharpe"),
            "labHoldoutReturnPct": s.get("holdout", {}).get("totalReturnPct"),
        })
        existing.add(aid)
        added += 1
    reg["agents"] = agents
    save_registry(reg)
    print(f"[mad-scientist] promoted {added} survivors to fleet (shadow)", flush=True)
    return added


def run(*, genomes: int | None = None, promote: int = 0, rebuild_panel: bool = False) -> dict:
    cfg = _load_config()
    genomes = genomes or int(cfg.get("genomes") or 500)
    cost_bps = float(cfg.get("cost_bps") or 7.0)
    sel_frac = float(cfg.get("selection_frac") or 0.6)

    if rebuild_panel or (not PANEL_PARQUET.exists() and not PANEL_CSV.exists()):
        from intelligence.historical.panel_builder import build_panel
        build_panel()

    try:
        df = _load_panel()
    except FileNotFoundError:
        doc = {"generatedAt": _now(), "ok": False, "message": "no panel — run panel_builder.py"}
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc
    df.columns = [c.strip().lower() for c in df.columns]
    days = _per_date_arrays(df)
    if len(days) < 30:
        doc = {"generatedAt": _now(), "ok": False, "message": f"too few days ({len(days)})"}
        OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    split = max(1, int(len(days) * sel_frac))
    sel_days, hold_days = days[:split], days[split:]
    pool = _spawn_genomes(genomes)

    rows = []
    for g in pool:
        full = _walk(g, days, cost_bps)
        sel = _metrics(full[:split])
        hold = _metrics(full[split:])
        if sel["nDays"] >= int(cfg.get("min_selection_days") or 20) and hold["nDays"] >= int(cfg.get("min_holdout_days") or 15):
            rows.append({**g, "selection": sel, "holdout": hold})

    rows.sort(key=lambda r: (r["selection"]["sharpe"] if r["selection"]["sharpe"] is not None else -9), reverse=True)
    top_n = max(1, int(len(rows) * 0.15))
    survivors = [r for r in rows if (r["selection"]["sharpe"] or 0) >= 0.5 and (r["holdout"]["sharpe"] or 0) > 0][:top_n]
    held_up = sum(1 for r in rows[:top_n] if (r["holdout"]["sharpe"] or 0) > 0)
    best_hold = max(rows, key=lambda r: (r["holdout"]["sharpe"] or -9)) if rows else None

    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    def _lead(r, i):
        return {
            "rank": i + 1, "id": r["id"], "family": r["family"], "signal": r.get("signal"),
            "selSharpe": r["selection"]["sharpe"], "holdSharpe": r["holdout"]["sharpe"],
            "holdReturnPct": r["holdout"]["totalReturnPct"], "holdDays": r["holdout"]["nDays"],
            "top_k": r["top_k"], "short_enabled": r["short_enabled"],
        }

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "mantra": "mad_scientist",
        "panel": {"rows": int(len(df)), "days": len(days), "meta": meta.get("walkforward")},
        "method": (
            f"8yr-trained predictor v3 (<= {cfg.get('train_end', '2023-12-31')}) "
            f"+ 2yr walk-forward panel with alpha frame. "
            f"Select genomes on first {sel_frac:.0%} of days; judge on held-out tail."
        ),
        "caveat": (
            "Mad Scientist upper bound: all genomes share the same predictor + panel. "
            "Survivors must still prove forward on live paper. But this panel NOW matches "
            "live Treasure Droid outputs (preds + neutralized sleeves + alpha)."
        ),
        "window": {
            "start": days[0][0], "end": days[-1][0],
            "nDays": len(days), "selectionDays": len(sel_days), "holdoutDays": len(hold_days),
        },
        "nGenomes": genomes, "nScored": len(rows), "costBps": cost_bps,
        "topSelectionHeldUp": f"{held_up}/{top_n}",
        "leaderboard": [_lead(r, i) for i, r in enumerate(rows[:30])],
        "survivors": survivors[:20],
        "verdict": (
            f"Mad Scientist Lab: {held_up}/{top_n} top genomes held up on holdout. "
            f"Best holdout Sharpe {best_hold['holdout']['sharpe']}, "
            f"{best_hold['holdout']['totalReturnPct']}% ({best_hold['holdout']['nDays']}d)."
            if best_hold else "no genomes scored"
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[mad-scientist] {genomes} genomes | {len(rows)} scored | held up {held_up}/{top_n} | "
          f"best holdout Sharpe={best_hold['holdout']['sharpe'] if best_hold else '-'}", flush=True)

    promote_n = promote or int(cfg.get("promote_top") or 0)
    if promote_n and survivors:
        _promote_survivors(survivors[:promote_n])
    try:
        from intelligence.brain.journal import log_mad_scientist
        log_mad_scientist(doc)
    except Exception as exc:
        print(f"[brain-journal] skip mad_scientist log: {exc}", flush=True)
    return doc


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Mad Scientist historical walk-forward lab")
    ap.add_argument("--genomes", type=int, default=0)
    ap.add_argument("--promote", type=int, default=0)
    ap.add_argument("--rebuild-panel", action="store_true")
    args = ap.parse_args()
    run(genomes=args.genomes or None, promote=args.promote, rebuild_panel=args.rebuild_panel)
