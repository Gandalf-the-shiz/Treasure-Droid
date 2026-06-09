"""Spawn, pulse, and leaderboard for Investor Arena v1 / v2."""
from __future__ import annotations

import json
import random

import numpy as np
import pandas as pd

from .ledger import compare_series, ranked_traders, record_pulse, version_summary
from .paths import (
    MASTER_SEEDS,
    VERSIONS,
    _now,
    backup_frozen_snapshot,
    ensure_experiment,
    is_frozen,
    leaderboard_path,
    list_versions,
    traders_path,
    version_panel_path,
)
from .simulate import STARTING_CASH, simulate

STRATEGY_FAMILIES = (
    "momentum_long", "contrarian", "ml_edge", "short_bias", "long_short_neutral",
    "crowd_follow", "insider_follow", "low_vol", "high_conviction",
)


def _load_panel(version: str | None = None) -> pd.DataFrame:
    path = version_panel_path(version) if version else version_panel_path("v1")
    if path.exists():
        df = pd.read_csv(path)
    else:
        return pd.DataFrame()
    if df.empty:
        return df
    df["symbol"] = df["symbol"].astype(str).str.upper()
    from intelligence.tradeable_universe import filter_dataframe
    return filter_dataframe(df)


def spawn_traders(version: str, n: int = 100, *, selection_mode: str | None = None) -> list[dict]:
    if is_frozen(version) and traders_path(version).exists():
        raise ValueError(f"Arena {version} is frozen — spawn a new version (v3+) instead of respawn")
    if version not in MASTER_SEEDS:
        nnum = int(version[1:]) if version[1:].isdigit() else 99
        MASTER_SEEDS[version] = 20260700 + nnum * 17
    master = MASTER_SEEDS[version]
    sel = selection_mode or ("threshold_v1" if version == "v1" else "rank_v2")
    rng = random.Random(master)
    traders = []
    for i in range(n):
        seed = master + i
        tr = random.Random(seed)
        family = tr.choice(STRATEGY_FAMILIES)
        short_on = family in {"short_bias", "long_short_neutral"} or tr.random() < (0.45 if version == "v2" else 0.35)
        g = {
            "trader_id": i,
            "seed": seed,
            "family": family,
            "arena_version": version,
            "selection_mode": sel,
            "min_proba": round(tr.uniform(0.52, 0.68), 3),
            "min_pred_ret": round(tr.uniform(0.005, 0.035 if version == "v1" else 0.012), 4),
            "short_enabled": short_on,
            "short_frac": round(tr.uniform(0.1, 0.45) if short_on else 0.0, 3),
            "top_k": tr.randint(5, 20 if version == "v2" else 15),
            "kelly": round(tr.uniform(0.25, 0.8), 3),
            "crowd_w": round(tr.uniform(0, 0.4) if family == "crowd_follow" else tr.uniform(0, 0.15), 3),
            "insider_w": round(tr.uniform(0, 0.5) if family == "insider_follow" else tr.uniform(0, 0.1), 3),
            "alt_scale": round(
                tr.uniform(0.85, 1.35) if family in {"crowd_follow", "insider_follow", "ml_edge"}
                else tr.uniform(0.65, 1.15),
                3,
            ),
            "contrarian": family == "contrarian",
        }
        traders.append(g)
    doc = {"generatedAt": _now(), "count": n, "masterSeed": master, "arenaVersion": version, "traders": traders}
    path = traders_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return traders


def run_pulse(version: str, n_traders: int = 100) -> dict:
    ensure_experiment()
    if is_frozen(version):
        backup_frozen_snapshot(version)
    tpath = traders_path(version)
    if not tpath.exists():
        spawn_traders(version, n_traders)
    doc = json.loads(tpath.read_text(encoding="utf-8"))
    traders = doc.get("traders") or []
    panel = _load_panel(version)
    genomes = {int(t["trader_id"]): t for t in traders}

    results = [simulate(t, panel, version, STARTING_CASH) for t in traders]
    results.sort(key=lambda x: x["returnPct"], reverse=True)

    baseline = simulate({
        "trader_id": -1, "seed": 0, "family": "single_champion",
        "min_proba": 0.60, "min_pred_ret": 0.02, "short_enabled": False,
        "short_frac": 0, "top_k": 5, "kelly": 0.5, "crowd_w": 0, "insider_w": 0,
        "alt_scale": 1.0, "contrarian": False,
        "selection_mode": "threshold_v1" if version == "v1" else "rank_v2",
    }, panel, version, 100_000.0)

    record_pulse(version, results, genomes)
    ranked = ranked_traders(version)

    top10 = ranked[:10]
    bottom5 = ranked[-5:] if len(ranked) >= 5 else ranked[-len(ranked):]

    arena = {
        "generatedAt": _now(),
        "arenaVersion": version,
        "nTraders": len(results),
        "panelSymbols": len(panel),
        "baselineSingleTrader": baseline,
        "top10": [{**r, "returnPct": r.get("cumulativeReturnPct"), "dailyReturnPct": (r.get("daily") or [{}])[-1].get("returnPct")} for r in top10],
        "bottom5": bottom5,
        "best": top10[0] if top10 else None,
        "medianCumulativePct": round(float(np.median([float(x.get("cumulativeReturnPct") or 0) for x in ranked])), 4) if ranked else 0,
        "pctBeatingBaseline": round(
            100 * sum(1 for r in ranked if float(r.get("cumulativeReturnPct") or 0) > float(baseline.get("returnPct") or 0)) / max(len(ranked), 1),
            2,
        ),
        "promotionHint": top10[0] if top10 else None,
        "summary": version_summary(version),
    }
    leaderboard_path(version).write_text(json.dumps(arena, indent=2), encoding="utf-8")
    print(
        f"[arena-{version}] {len(results)} traders | best=#{arena['best']['traderId'] if arena.get('best') else 'n/a'} "
        f"cum={arena['best'].get('cumulativeReturnPct') if arena.get('best') else 0}% | "
        f"{arena['pctBeatingBaseline']}% beat baseline",
        flush=True,
    )
    return arena


def run_all_pulses(n: int = 100, versions: list[str] | None = None) -> dict:
    out = {}
    for v in versions or list_versions():
        out[v] = run_pulse(v, n)
    out["compare"] = compare_series()
    return out


def run_active_pulses(n: int = 100) -> dict:
    """Pulse v1, v2, champion (+ optional challenger) per operating model."""
    from .operating import ensure_operating_model, pulse_versions

    ensure_operating_model()
    vers = pulse_versions()
    out = run_all_pulses(n, versions=vers)
    out["pulseVersions"] = vers
    out["operatingModel"] = True
    return out


def ensure_both_versions(n: int = 100) -> None:
    ensure_experiment()
    for v in VERSIONS:
        if not traders_path(v).exists():
            spawn_traders(v, n)
