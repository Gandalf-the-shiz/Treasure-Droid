"""Per-sleeve forward IC measurement + ICIR-weighted blending (Mega Yacht 3.5).

Scores each alpha sleeve independently:
  - **research**: neutralized rank IC / ICIR on predictor test window (upper bound)
  - **forward**: daily rank IC from dated alpha snapshots vs next-day realized returns

Writes data/accuracy/sleeve_ic.json and recommends ICIR weights for the alpha engine.
Snapshots neutralized sleeve columns daily under data/intelligence/alpha/snapshots/.
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
LIVE_CSV = REPO / "data" / "predictions_v3" / "live.csv"
HIST_DIR = REPO / "data" / "historical"
SNAP_DIR = REPO / "data" / "intelligence" / "alpha" / "snapshots"
OUT_PATH = REPO / "data" / "accuracy" / "sleeve_ic.json"
CONFIG_PATH = REPO / "config" / "alpha_engine.json"
LIVE_ROOT = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))

import sys

sys.path.insert(0, str(REPO / "scripts"))
from intelligence.alpha.neutralize import neutralize_series, spearman_ic  # noqa: E402
from intelligence.alpha.measure import _price_sleeves, _size_map  # noqa: E402

_RET_COLS = ["y_ret", "fwd_ret", "forward_ret", "realized_ret", "target_ret", "ret_fwd_1"]
SLEEVE_COL_PREFIX = "n_"
MIN_FORWARD_DAYS = 5
DECAY_WINDOW = 10
TRAILING_ICIR_WINDOW = 20

# Human labels for the dashboard.
SLEEVE_LABELS = {
    "ml_edge": "ML edge",
    "reversal_1d": "1-day reversal",
    "reversal_5d": "5-day reversal",
    "momentum_120_20": "Residual momentum",
    "pead": "PEAD (earnings drift)",
    "revisions": "Analyst revisions",
    "sentiment": "News + gossip",
    "ml_proba": "ML probability",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agg_daily(ics: list[float]) -> dict:
    arr = np.array([x for x in ics if np.isfinite(x)], dtype=float)
    if arr.size == 0:
        return {
            "mean_ic": None,
            "icir": None,
            "ic_hit_rate": None,
            "n_days": 0,
        }
    mean_ic = float(arr.mean())
    std_ic = float(arr.std(ddof=0))
    icir = (mean_ic / std_ic) if std_ic > 0 else None
    return {
        "mean_ic": round(mean_ic, 5),
        "icir": round(icir, 4) if icir is not None else None,
        "ic_hit_rate": round(float((arr > 0).mean()), 4),
        "n_days": int(arr.size),
    }


def _trailing_mean(ics: list[float], window: int = DECAY_WINDOW) -> float | None:
    arr = [x for x in ics if np.isfinite(x)]
    if not arr:
        return None
    tail = arr[-window:]
    return float(np.mean(tail))


def snapshot_daily(as_of: str | None = None) -> dict | None:
    """Persist today's neutralized sleeve frame for forward IC accrual."""
    from intelligence.alpha.engine import build_alpha_frame  # noqa: E402

    df, used, _cfg = build_alpha_frame()
    if df is None or df.empty:
        print("[sleeve-ic] snapshot skipped — no alpha frame", flush=True)
        return None

    if as_of is None:
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    sleeve_cols = [c for c in df.columns if c.startswith(SLEEVE_COL_PREFIX)]
    rows = []
    for _, row in df.iterrows():
        entry = {"symbol": str(row["symbol"]).upper()}
        for col in sleeve_cols:
            val = row.get(col)
            if val is not None and np.isfinite(float(val)):
                entry[col] = round(float(val), 6)
        if len(entry) > 1:
            rows.append(entry)

    doc = {
        "date": as_of,
        "generatedAt": _now(),
        "universe": len(rows),
        "sleeves": [c.replace(SLEEVE_COL_PREFIX, "") for c in sleeve_cols],
        "rows": rows,
    }
    path = SNAP_DIR / f"{as_of}.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[sleeve-ic] snapshot {as_of} symbols={len(rows)} sleeves={doc['sleeves']}", flush=True)
    return doc


def _load_prices() -> dict[str, pd.Series]:
    """Close series indexed by date string YYYY-MM-DD per symbol."""
    prices: dict[str, pd.Series] = {}
    if not HIST_DIR.exists():
        return prices
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
            c = pd.DataFrame(candles)
            if "date" not in c.columns or "close" not in c.columns:
                continue
            c["date"] = pd.to_datetime(c["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            close = pd.to_numeric(c["close"], errors="coerce")
            sub = pd.DataFrame({"date": c["date"], "close": close}).dropna()
            if len(sub) >= 5:
                prices[str(sym).upper()] = sub.set_index("date")["close"]
    return prices


def _fwd_return(prices: dict[str, pd.Series], sym: str, date: str, horizon: int = 1) -> float | None:
    s = prices.get(str(sym).upper())
    if s is None or date not in s.index:
        return None
    idx = s.index.get_loc(date)
    if idx + horizon >= len(s):
        return None
    p0 = float(s.iloc[idx])
    p1 = float(s.iloc[idx + horizon])
    if p0 <= 0:
        return None
    return p1 / p0 - 1.0


def _score_cross_section(
    g: pd.DataFrame,
    sleeve_cols: list[str],
    ret_col: str,
    sector_col: str,
    size_col: str,
    winsor: float,
) -> dict[str, float]:
    """Per-sleeve rank IC on one date cross-section."""
    fwd = g[ret_col].astype(float)
    sector = g[sector_col].astype(str)
    size = g[size_col].astype(float)
    out: dict[str, float] = {}
    for col in sleeve_cols:
        raw = g[col].astype(float)
        neu = neutralize_series(raw, sector=sector, size=size, winsor=winsor, output="zscore")
        if neu is None or neu.dropna().empty:
            continue
        ic = spearman_ic(neu, fwd)
        if np.isfinite(ic):
            out[col] = ic
    return out


def score_backtest(max_days: int | None = None) -> dict:
    """Research (test-window) per-sleeve IC — upper bound, not forward proof."""
    if not TEST_CSV.exists():
        return {"ok": False, "message": "no test.csv"}

    df = pd.read_csv(TEST_CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    ret_col = next((c for c in _RET_COLS if c in df.columns), None)
    if ret_col is None or "pred_proba_up" not in df.columns:
        return {"ok": False, "message": "test.csv missing return or prediction cols"}

    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "sector" not in df.columns:
        df["sector"] = "UNKNOWN"
    df["ml_edge"] = (2.0 * df["pred_proba_up"].astype(float) - 1.0) * df["pred_ret"].astype(float).abs()

    try:
        from intelligence.tradeable_universe import is_tradeable
        df = df.loc[df["symbol"].map(lambda s: is_tradeable(s)[0])].copy()
    except Exception:
        pass

    size_map = _size_map()
    df["_size"] = df["symbol"].map(size_map)

    ps = _price_sleeves()
    if not ps.empty:
        df = df.merge(ps, on=["symbol", "date"], how="left")
        df = df.rename(columns={"rev_1": "reversal_1d", "rev_5": "reversal_5d", "mom_120_20": "momentum_120_20"})

    sleeve_cols = [c for c in ("ml_edge", "reversal_1d", "reversal_5d", "momentum_120_20") if c in df.columns]
    daily_by_sleeve: dict[str, list[float]] = {c: [] for c in sleeve_cols}

    dates = sorted(df["date"].dropna().unique())
    if max_days:
        dates = dates[-max_days:]

    for d in dates:
        g = df[df["date"] == d]
        if len(g) < 30:
            continue
        scored = _score_cross_section(g, sleeve_cols, ret_col, "sector", "_size", 0.02)
        for col, ic in scored.items():
            daily_by_sleeve[col].append(ic)

    by_sleeve = {}
    for name, ics in daily_by_sleeve.items():
        agg = _agg_daily(ics)
        agg["label"] = SLEEVE_LABELS.get(name, name)
        agg["decayed"] = False
        by_sleeve[name] = agg

    return {
        "ok": True,
        "kind": "research",
        "window": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "by_sleeve": by_sleeve,
        "n_days": max((v["n_days"] for v in by_sleeve.values()), default=0),
    }


def score_forward(horizon_days: int = 1) -> dict:
    """Forward per-sleeve IC from dated snapshots vs realized next-day returns."""
    if not SNAP_DIR.exists():
        return {"ok": False, "kind": "forward", "message": "no snapshots yet", "by_sleeve": {}, "n_days": 0}

    prices = _load_prices()
    snap_files = sorted(SNAP_DIR.glob("*.json"))
    if not snap_files:
        return {"ok": False, "kind": "forward", "message": "no snapshot files", "by_sleeve": {}, "n_days": 0}

    try:
        from intelligence.tradeable_universe import is_tradeable
    except Exception:
        is_tradeable = lambda s: (True, "")  # noqa: E501

    daily_ics: dict[str, list[dict]] = {}
    scored_dates: list[str] = []

    for fp in snap_files:
        try:
            snap = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        d = snap.get("date") or fp.stem
        rows = snap.get("rows") or []
        if not rows:
            continue

        records = []
        for row in rows:
            sym = str(row.get("symbol", "")).upper()
            ok, _ = is_tradeable(sym)
            if not ok:
                continue
            r = _fwd_return(prices, sym, d, horizon_days)
            if r is None or not np.isfinite(r):
                continue
            rec = {"symbol": sym, "fwd_ret": r}
            for k, v in row.items():
                if k.startswith(SLEEVE_COL_PREFIX):
                    rec[k] = float(v)
            if len(rec) > 2:
                records.append(rec)

        if len(records) < 30:
            continue

        g = pd.DataFrame(records)
        sleeve_cols = [c for c in g.columns if c.startswith(SLEEVE_COL_PREFIX)]
        for col in sleeve_cols:
            neu = g[col].astype(float)
            ic = spearman_ic(neu, g["fwd_ret"].astype(float))
            if not np.isfinite(ic):
                continue
            name = col.replace(SLEEVE_COL_PREFIX, "")
            daily_ics.setdefault(name, []).append({"date": d, "ic": round(ic, 5), "n": len(g)})
        scored_dates.append(d)

    by_sleeve = {}
    all_daily: list[dict] = []
    for name, points in daily_ics.items():
        ics = [p["ic"] for p in points]
        agg = _agg_daily(ics)
        trailing = _trailing_mean(ics, DECAY_WINDOW)
        agg["label"] = SLEEVE_LABELS.get(name, name)
        agg["trailing_mean_ic"] = round(trailing, 5) if trailing is not None else None
        agg["decayed"] = bool(trailing is not None and trailing < 0)
        agg["daily"] = points[-60:]
        by_sleeve[name] = agg
        all_daily.extend(points)

    n_unique_days = len({p["date"] for p in all_daily})
    return {
        "ok": n_unique_days > 0,
        "kind": "forward",
        "horizonDays": horizon_days,
        "window": {
            "start": scored_dates[0] if scored_dates else None,
            "end": scored_dates[-1] if scored_dates else None,
        },
        "by_sleeve": by_sleeve,
        "n_days": n_unique_days,
    }


def compute_icir_weights(
    forward: dict,
    config_weights: dict[str, float],
    *,
    min_days: int = MIN_FORWARD_DAYS,
) -> tuple[dict[str, float], str, list[str]]:
    """ICIR-weighted blend with auto-decay for sleeves with negative trailing IC."""
    n_days = forward.get("n_days") or 0
    by_sleeve = forward.get("by_sleeve") or {}
    notes: list[str] = []

    if n_days < min_days:
        return dict(config_weights), "static_config", [
            f"forward days {n_days}/{min_days} — using config weights until enough live proof"
        ]

    raw: dict[str, float] = {}
    for name, base_w in config_weights.items():
        if base_w <= 0:
            raw[name] = 0.0
            continue
        stats = by_sleeve.get(name) or {}
        if stats.get("decayed"):
            raw[name] = 0.0
            notes.append(f"{name}: decayed (trailing IC {stats.get('trailing_mean_ic')})")
            continue
        icir = stats.get("icir")
        if icir is None or icir <= 0:
            raw[name] = 0.0
            if name in by_sleeve:
                notes.append(f"{name}: zeroed (forward ICIR {icir})")
            continue
        raw[name] = float(base_w) * float(icir)

    total = sum(v for v in raw.values() if v > 0)
    if total <= 0:
        return dict(config_weights), "static_fallback", notes + ["all ICIR weights zero — config fallback"]

    config_total = sum(v for v in config_weights.values() if v > 0)
    scale = config_total / total
    effective = {k: round(v * scale, 4) for k, v in raw.items() if v > 0}
    # Preserve explicit zero-weight sleeves from config.
    for k, v in config_weights.items():
        if v <= 0:
            effective[k] = 0.0
        elif k not in effective:
            effective[k] = 0.0
    return effective, "icir_forward", notes


def load_effective_weights() -> tuple[dict[str, float], str]:
    """Read sleeve_ic.json and return weights for the alpha engine."""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    config_weights = dict(cfg.get("sleeve_weights") or {})

    if not OUT_PATH.exists():
        return config_weights, "static_config"

    try:
        doc = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return config_weights, "static_config"

    eff = doc.get("effective_weights") or {}
    mode = doc.get("weight_mode") or "static_config"
    if eff:
        return eff, mode
    return config_weights, "static_config"


def run(*, snapshot: bool = True, horizon_days: int = 1) -> dict:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if snapshot:
        snapshot_daily()

    research = score_backtest()
    forward = score_forward(horizon_days=horizon_days)

    config_weights: dict[str, float] = {}
    if CONFIG_PATH.exists():
        try:
            config_weights = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("sleeve_weights") or {}
        except (OSError, json.JSONDecodeError):
            pass

    effective, weight_mode, weight_notes = compute_icir_weights(forward, config_weights)

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "research": research,
        "forward": forward,
        "config_weights": config_weights,
        "effective_weights": effective,
        "weight_mode": weight_mode,
        "weight_notes": weight_notes,
        "min_forward_days": MIN_FORWARD_DAYS,
        "decay_window": DECAY_WINDOW,
    }
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    if LIVE_ROOT.exists():
        mirror = LIVE_ROOT / "data" / "accuracy" / "sleeve_ic.json"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    fwd_n = forward.get("n_days") or 0
    active = [k for k, v in effective.items() if v > 0]
    print(
        f"[sleeve-ic] forward_days={fwd_n} mode={weight_mode} "
        f"active_sleeves={active} notes={len(weight_notes)}",
        flush=True,
    )
    return doc


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Per-sleeve IC measure + ICIR weights")
    ap.add_argument("--no-snapshot", action="store_true", help="skip today's snapshot write")
    ap.add_argument("--snapshot-only", action="store_true", help="only write snapshot")
    ap.add_argument("--horizon", type=int, default=1, help="forward return horizon days")
    args = ap.parse_args()

    if args.snapshot_only:
        snapshot_daily()
    else:
        run(snapshot=not args.no_snapshot, horizon_days=args.horizon)
