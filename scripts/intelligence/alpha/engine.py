"""Cross-sectional alpha engine — live market-neutral book (Alpha Doctrine A).

Reads the live predictor panel, builds multiple sleeves, neutralizes each
(sector + size), combines them, and constructs a market-neutral long/short
book. Writes data/intelligence/alpha/book.json.

This does NOT trade live — it produces a candidate book whose forward IC must
be proven before any capital (see readiness gate / Mega Yacht ladder).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
LIVE_CSV = REPO / "data" / "predictions_v3" / "live.csv"
HIST_DIR = REPO / "data" / "historical"
OUT_PATH = REPO / "data" / "intelligence" / "alpha" / "book.json"
CONFIG_PATH = REPO / "config" / "alpha_engine.json"

import sys

sys.path.insert(0, str(REPO / "scripts"))
from intelligence.alpha.neutralize import neutralize_series  # noqa: E402


DEFAULT_CONFIG = {
    "top_frac": 0.10,
    "gross_exposure": 1.0,
    "max_name_weight": 0.04,
    "min_names_per_side": 5,
    "sleeve_weights": {
        "ml_edge": 1.0,
        "reversal_5d": 0.7,
        "reversal_1d": 0.5,
        "momentum_120_20": 0.4,
        "pead": 0.8,
        "revisions": 0.6,
        "sentiment": 0.5,
        "ml_proba": 0.0,
    },
    "winsor": 0.02,
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    try:
        from intelligence.alpha.sleeve_ic import load_effective_weights

        eff, mode = load_effective_weights()
        if eff and mode in {"icir_forward", "static_fallback"}:
            cfg["sleeve_weights"] = eff
            cfg["weight_mode"] = mode
    except Exception:
        cfg["weight_mode"] = "static_config"
    return cfg


def _load_prices(max_tail: int = 130) -> dict[str, pd.Series]:
    """Recent close series per symbol from historical shards (best-effort)."""
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
            if len(candles) < 25:
                continue
            df = pd.DataFrame(candles)
            if "close" not in df.columns:
                continue
            close = pd.to_numeric(df["close"], errors="coerce").dropna()
            if len(close) >= 25:
                prices[str(sym).upper()] = close.tail(max_tail).reset_index(drop=True)
    return prices


def _finnhub_signals() -> dict[str, dict]:
    """Load normalized PEAD + revision signals if the feed has run."""
    path = REPO / "data" / "finnhub" / "signals_by_symbol.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc.get("bySymbol") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sentiment_signals() -> dict[str, dict]:
    """Load market-sentiment (news + Reddit gossip) signals if the feed has run."""
    path = REPO / "data" / "sentiment_feed" / "signals_by_symbol.json"
    if not path.exists():
        return {}
    try:
        return (json.loads(path.read_text(encoding="utf-8")).get("bySymbol")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _size_proxy() -> dict[str, float]:
    """log(20d avg dollar volume) per symbol from tradeable universe cache."""
    try:
        from intelligence.tradeable_universe import _liquidity_cache
        out = {}
        for sym, prof in _liquidity_cache().items():
            adv = float(prof.get("adv_20") or 0)
            out[sym] = float(np.log1p(adv)) if adv > 0 else 0.0
        return out
    except Exception:
        return {}


def _build_sleeves(df: pd.DataFrame, prices: dict[str, pd.Series], *, panel_mode: bool = False) -> dict[str, pd.Series]:
    """Raw (un-neutralized) sleeve signals indexed by symbol."""
    sleeves: dict[str, pd.Series] = {}
    idx = df.index

    proba = df["pred_proba_up"].astype(float)
    pred_ret = df["pred_ret"].astype(float)
    sleeves["ml_edge"] = (2.0 * proba - 1.0) * pred_ret.abs()
    sleeves["ml_proba"] = proba - 0.5

    # Historical panel: use pre-merged point-in-time price sleeve columns.
    if panel_mode:
        for src, name in (
            ("reversal_1d", "reversal_1d"),
            ("reversal_5d", "reversal_5d"),
            ("momentum_120_20", "momentum_120_20"),
        ):
            if src in df.columns and df[src].notna().any():
                sleeves[name] = df[src].astype(float).set_axis(idx)

    if prices and not panel_mode:
        rev5, rev1, mom = {}, {}, {}
        for sym in df["symbol"]:
            s = prices.get(str(sym).upper())
            if s is None or len(s) < 25:
                continue
            if s.iloc[-1] <= 0:
                continue
            # short-term reversal: negative of recent return (mean-reversion)
            r1 = s.iloc[-1] / s.iloc[-2] - 1.0 if len(s) >= 2 else np.nan
            r5 = s.iloc[-1] / s.iloc[-6] - 1.0 if len(s) >= 6 else np.nan
            rev1[sym] = -r1 if np.isfinite(r1) else np.nan
            rev5[sym] = -r5 if np.isfinite(r5) else np.nan
            # residual momentum: 120d return excluding most recent 20d
            mom[sym] = (s.iloc[-21] / s.iloc[-121] - 1.0) if len(s) >= 121 else np.nan
        if rev5:
            sleeves["reversal_5d"] = df["symbol"].map(rev5).astype(float).set_axis(idx)
        if rev1:
            sleeves["reversal_1d"] = df["symbol"].map(rev1).astype(float).set_axis(idx)
        if mom:
            sleeves["momentum_120_20"] = df["symbol"].map(mom).astype(float).set_axis(idx)

    # Finnhub fundamental sleeves (PEAD + analyst revisions) — sparse, neutralized.
    fh = _finnhub_signals()
    if fh:
        pead = df["symbol"].map(lambda s: fh.get(str(s).upper(), {}).get("pead_score"))
        revs = df["symbol"].map(lambda s: fh.get(str(s).upper(), {}).get("revision_score"))
        if pead.notna().any():
            sleeves["pead"] = pead.astype(float).set_axis(idx)
        if revs.notna().any():
            sleeves["revisions"] = revs.astype(float).set_axis(idx)

    # Market-sentiment sleeve (news + Reddit gossip) — sparse, neutralized.
    sf = _sentiment_signals()
    if sf:
        sent = df["symbol"].map(lambda s: sf.get(str(s).upper(), {}).get("sentiment_score"))
        if sent.notna().any():
            sleeves["sentiment"] = sent.astype(float).set_axis(idx)
    return sleeves


def _combine(
    sleeves: dict[str, pd.Series],
    sector: pd.Series,
    size: pd.Series,
    weights: dict[str, float],
    winsor: float,
) -> tuple[pd.Series, dict]:
    combined = None
    used = {}
    for name, raw in sleeves.items():
        w = float(weights.get(name, 0.0))
        if w == 0.0 or raw is None or raw.dropna().empty:
            continue
        neu = neutralize_series(raw, sector=sector, size=size, winsor=winsor, output="zscore")
        if neu is None or neu.dropna().empty:
            continue
        contrib = (neu.fillna(0.0) * w)
        combined = contrib if combined is None else combined.add(contrib, fill_value=0.0)
        used[name] = w
    if combined is None:
        combined = pd.Series(0.0, index=sector.index)
    return combined, used


def _enrich_cross_section(
    g: pd.DataFrame,
    cfg: dict,
    *,
    panel_mode: bool = False,
    size_col: str | None = None,
) -> pd.DataFrame:
    """Add edge, n_<sleeve>, and alpha to one date cross-section."""
    g = g.copy()
    sector = g["sector"].astype(str) if "sector" in g.columns else pd.Series("UNKNOWN", index=g.index)
    if size_col and size_col in g.columns:
        size = g[size_col].astype(float)
    else:
        size = g["symbol"].map(_size_proxy()).astype(float)
    prices = {} if panel_mode else _load_prices()
    if "price" not in g.columns:
        price_map = {sym: float(s.iloc[-1]) for sym, s in prices.items() if len(s)}
        g["price"] = g["symbol"].map(lambda s: price_map.get(str(s).upper(), 0.0)).astype(float)
    g["pred_proba_up"] = g["pred_proba_up"].astype(float)
    g["pred_ret"] = g["pred_ret"].astype(float)
    g["edge"] = (2.0 * g["pred_proba_up"] - 1.0) * g["pred_ret"].abs()

    sleeves = _build_sleeves(g, prices, panel_mode=panel_mode)
    weights = cfg["sleeve_weights"]
    combined = None
    for name, raw in sleeves.items():
        w = float(weights.get(name, 0.0))
        if w == 0.0 or raw is None or raw.dropna().empty:
            continue
        neu = neutralize_series(raw, sector=sector, size=size, winsor=float(cfg["winsor"]), output="zscore")
        if neu is None or neu.dropna().empty:
            continue
        g["n_" + name] = neu.reindex(g.index)
        contrib = neu.fillna(0.0) * w
        combined = contrib if combined is None else combined.add(contrib, fill_value=0.0)
    g["alpha"] = (combined if combined is not None else pd.Series(0.0, index=g.index)).reindex(g.index).fillna(0.0)
    return g


def enrich_panel_alpha(df: pd.DataFrame, size_col: str = "_size") -> pd.DataFrame:
    """Enrich a multi-date historical panel with alpha frame columns (Mad Scientist Lab)."""
    cfg = _load_config()
    if "date" not in df.columns:
        return _enrich_cross_section(df, cfg, panel_mode=True, size_col=size_col)
    parts = []
    dates = sorted(df["date"].unique())
    for i, d in enumerate(dates):
        g = df[df["date"] == d]
        if len(g) < 20:
            continue
        parts.append(_enrich_cross_section(g, cfg, panel_mode=True, size_col=size_col))
        if (i + 1) % 50 == 0:
            print(f"[alpha-panel] enriched {i + 1}/{len(dates)} dates", flush=True)
    if not parts:
        return df
    return pd.concat(parts, ignore_index=True)


def build_alpha_frame(cfg: dict | None = None, panel: pd.DataFrame | None = None):
    """Shared, explainable signal frame for the whole fleet.

    Returns (df, used_sleeves, cfg). df has one row per tradeable symbol with:
    symbol, sector, price, pred_proba_up, pred_ret, edge, alpha (combined),
    and one neutralized z-score column per sleeve named ``n_<sleeve>``.
    Returns (None, [], cfg) when no data.

    Pass ``panel`` to score a historical cross-section (latest date in panel).
    """
    cfg = cfg or _load_config()
    if panel is not None:
        df = panel.copy()
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" in df.columns:
            latest = df["date"].max()
            df = df[df["date"] == latest].copy()
    else:
        if not LIVE_CSV.exists():
            return None, [], cfg
        df = pd.read_csv(LIVE_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
    if df.empty or "symbol" not in df.columns:
        return None, [], cfg
    df["symbol"] = df["symbol"].astype(str).str.upper()
    if "sector" not in df.columns:
        df["sector"] = "UNKNOWN"
    try:
        from intelligence.tradeable_universe import filter_dataframe
        df = filter_dataframe(df).reset_index(drop=True)
    except Exception:
        df = df.reset_index(drop=True)
    if df.empty:
        return None, [], cfg

    df = _enrich_cross_section(df, cfg, panel_mode=False)
    used = [c[2:] for c in df.columns if c.startswith("n_")]
    return df, used, cfg


def _build_book(df: pd.DataFrame, alpha: pd.Series, cfg: dict, price_map: dict | None = None) -> dict:
    price_map = price_map or {}
    work = df.copy()
    work["alpha"] = alpha.reindex(work.index).fillna(0.0)
    work = work.sort_values("alpha", ascending=False).reset_index(drop=True)
    n = len(work)
    k = max(int(cfg["min_names_per_side"]), int(n * float(cfg["top_frac"])))
    k = min(k, n // 2) if n >= 2 * cfg["min_names_per_side"] else min(cfg["min_names_per_side"], n)

    longs = work.head(k).copy()
    shorts = work.tail(k).copy()

    def _weights(side: pd.DataFrame, sign: float) -> list[dict]:
        if side.empty:
            return []
        raw = side["alpha"].abs()
        if raw.sum() == 0:
            w = pd.Series(1.0 / len(side), index=side.index)
        else:
            w = raw / raw.sum()
        cap = float(cfg["max_name_weight"])
        w = w.clip(upper=cap)
        w = w / w.sum() if w.sum() > 0 else w
        gross = float(cfg["gross_exposure"]) / 2.0
        out = []
        for (_, row), wt in zip(side.iterrows(), w):
            out.append({
                "symbol": row["symbol"],
                "sector": row.get("sector", "—"),
                "side": "long" if sign > 0 else "short",
                "weight": round(float(wt) * gross * sign, 5),
                "price": round(float(price_map.get(str(row["symbol"]).upper(), 0.0)), 2),
                "alpha": round(float(row["alpha"]), 5),
                "pred_proba_up": round(float(row.get("pred_proba_up", 0)), 4),
                "pred_ret": round(float(row.get("pred_ret", 0)), 5),
            })
        return out

    long_book = _weights(longs, +1.0)
    short_book = _weights(shorts, -1.0)
    net = sum(p["weight"] for p in long_book + short_book)
    gross = sum(abs(p["weight"]) for p in long_book + short_book)
    return {
        "longs": long_book,
        "shorts": short_book,
        "nLong": len(long_book),
        "nShort": len(short_book),
        "netExposure": round(net, 4),
        "grossExposure": round(gross, 4),
    }


def run() -> dict:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df, used, cfg = build_alpha_frame()
    if df is None or df.empty:
        doc = {"generatedAt": _now(), "ok": False, "message": "no tradeable live data"}
        OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    price_map = dict(zip(df["symbol"], df["price"]))
    book = _build_book(df, df["alpha"], cfg, price_map)

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "universe": int(len(df)),
        "sleevesUsed": {n: cfg["sleeve_weights"].get(n) for n in used},
        "weightMode": cfg.get("weight_mode", "static_config"),
        "config": cfg,
        "book": book,
        "note": "Market-neutral candidate. Forward IC must be proven before capital.",
    }
    OUT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(
        f"[alpha-engine] universe={len(df)} sleeves={used} "
        f"long={book['nLong']} short={book['nShort']} net={book['netExposure']}",
        flush=True,
    )
    return doc


if __name__ == "__main__":
    run()
