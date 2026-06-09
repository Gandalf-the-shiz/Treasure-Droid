"""Honest penny-universe metrics (rank IC + quintile spread)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_rank_ic(df: pd.DataFrame, score_col: str = "score", fwd_col: str = "y_ret") -> pd.Series:
    ics = {}
    for d, g in df.groupby("date", sort=True):
        s = g[score_col].to_numpy(dtype="float64")
        f = g[fwd_col].to_numpy(dtype="float64")
        m = np.isfinite(s) & np.isfinite(f)
        if m.sum() < 5:
            ics[d] = np.nan
            continue
        sr = pd.Series(s[m]).rank().to_numpy()
        fr = pd.Series(f[m]).rank().to_numpy()
        if sr.std() == 0 or fr.std() == 0:
            ics[d] = np.nan
        else:
            ics[d] = float(np.corrcoef(sr, fr)[0, 1])
    return pd.Series(ics)


def summarize_ic(ic: pd.Series) -> dict:
    v = ic.dropna().to_numpy()
    if len(v) == 0:
        return {"mean_ic": None, "icir": None, "n_days": 0}
    mean = float(v.mean())
    std = float(v.std(ddof=1)) if len(v) > 1 else np.nan
    icir = mean / std if std and std > 0 else None
    return {"mean_ic": round(mean, 5), "icir": round(icir, 4) if icir else None,
            "n_days": int(len(v)), "hit_rate": round(float((v > 0).mean()), 3)}


def quintile_spread(df: pd.DataFrame, score_col: str = "score", fwd_col: str = "y_ret") -> float | None:
    spreads = []
    for _, g in df.groupby("date", sort=True):
        if len(g) < 10:
            continue
        g = g.dropna(subset=[score_col, fwd_col])
        if len(g) < 10:
            continue
        g = g.assign(q=pd.qcut(g[score_col].rank(method="first"), 5, labels=False))
        top = g.loc[g["q"] == 4, fwd_col].mean()
        bot = g.loc[g["q"] == 0, fwd_col].mean()
        if np.isfinite(top) and np.isfinite(bot):
            spreads.append(top - bot)
    return round(float(np.mean(spreads)), 6) if spreads else None


def evaluate_oos(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"valid": False}
    ic = summarize_ic(daily_rank_ic(df))
    sp = quintile_spread(df)
    score = df["score"].to_numpy()
    thr = np.median(score[np.isfinite(score)])
    acc = float((df["y_up"].to_numpy() == (score > thr)).mean()) if len(df) else None
    return {"valid": True, **ic, "quintile_spread": sp, "accuracy": round(acc, 4) if acc else None,
            "oos_rows": len(df)}


def objective(metrics: dict, horizon: int = 5) -> float:
    if not metrics.get("valid"):
        return -9.0
    sp = metrics.get("quintile_spread")
    icir = metrics.get("icir") or 0.0
    cost = 0.0015 * 2  # ~15bps round trip per leg proxy
    if sp is None:
        return -9.0
    net = float(sp) - cost
    ann = net * (252.0 / max(1, horizon))
    if net <= 0:
        return ann
    stab = max(0.0, min(1.0, (icir or 0) / 0.3))
    return ann * (0.5 + 0.5 * stab)
