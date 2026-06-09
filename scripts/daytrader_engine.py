"""Intraday daytrading ranker — momentum + ML edge for fastest Robinhood turnover."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]


def load_predictions() -> pd.DataFrame:
    for name in ("live.csv", "test.csv"):
        p = REPO / "data" / "predictions_v3" / name
        if not p.exists():
            continue
        df = pd.read_csv(p, parse_dates=["date"] if name == "test.csv" else None)
        if name == "test.csv":
            last = df["date"].max()
            df = df[df["date"] == last]
        return df
    return pd.DataFrame()


def fetch_intraday_momentum(symbols: list[str]) -> dict[str, float]:
    """Return intraday return proxy (today vs prev close) when yfinance is available."""
    out: dict[str, float] = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    if not symbols:
        return out
    chunk = 40
    for i in range(0, len(symbols), chunk):
        batch = symbols[i : i + chunk]
        try:
            data = yf.download(
                " ".join(batch),
                period="2d",
                interval="5m",
                group_by="ticker",
                progress=False,
                threads=True,
            )
        except Exception:
            continue
        for sym in batch:
            try:
                if len(batch) == 1:
                    sub = data
                else:
                    sub = data[sym]
                if sub is None or sub.empty:
                    continue
                closes = sub["Close"].dropna()
                if len(closes) < 2:
                    continue
                out[sym] = float((closes.iloc[-1] / closes.iloc[0]) - 1.0)
            except Exception:
                continue
    return out


def rank_daytrades(
    df: pd.DataFrame,
    *,
    top_k: int = 15,
    min_proba: float = 0.55,
    min_edge: float = 0.001,
) -> list[dict]:
    if df.empty:
        return []
    d = df.copy()
    d["edge"] = (d["pred_proba_up"] - 0.5) * 2.0 * d["pred_ret"].abs()
    d = d[(d["pred_proba_up"] >= min_proba) & (d["edge"] >= min_edge)]
    try:
        from intelligence.tradeable_universe import filter_dataframe
        d = filter_dataframe(d)
    except Exception:
        pass
    use_unified = os.getenv("UNIFIED_SCORE_ENABLED", "true").lower() in {"1", "true", "yes"}
    if use_unified:
        try:
            from intelligence.unified_score import apply_panel_scores, load_unified_config
            if load_unified_config().get("enabled"):
                d = apply_panel_scores(d, side="long", alt_scale=1.0, score_col="unified_score")
        except Exception:
            d["unified_score"] = d["edge"]
    else:
        d["unified_score"] = d["edge"]
    syms = d["symbol"].astype(str).str.upper().tolist()[: max(top_k * 4, 60)]
    mom = fetch_intraday_momentum(syms)
    d["mom_5m"] = d["symbol"].map(lambda s: mom.get(str(s).upper(), 0.0))
    d["day_score"] = d["unified_score"] * (1.0 + d["mom_5m"].clip(-0.05, 0.15) * 8.0)
    d = d.sort_values("day_score", ascending=False).head(top_k)
    picks = []
    for _, r in d.iterrows():
        sym = str(r["symbol"]).upper()
        picks.append({
            "symbol": sym,
            "proba_up": float(r["pred_proba_up"]),
            "pred_ret": float(r["pred_ret"]),
            "edge": float(r["edge"]),
            "momentum_intraday": float(r["mom_5m"]),
            "day_score": float(r["day_score"]),
            "hold_minutes": int(os.getenv("DAYTRADE_MAX_HOLD_MIN", "240")),
            "unified_score": float(r.get("unified_score") or 0),
            "rationale": (
                f"Daytrade score {float(r['day_score']):.3f} — "
                f"unified intel + intraday mom {float(r['mom_5m'])*100:+.2f}%"
            ),
        })
    try:
        from intelligence.tradeable_universe import filter_picks
        picks = filter_picks(picks)
    except Exception:
        pass
    return picks
