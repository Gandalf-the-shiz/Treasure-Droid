"""Unified ML overlays: regime + congress + insider (point-in-time safe)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from regime_features import attach_regime_features, REGIME_FEATURE_COLS
from insider_signals import INSIDER_FEATURE_COLS

REPO = Path(__file__).resolve().parents[1]
CONGRESS_TRADES = REPO / "data" / "congress" / "trades_normalized.json"
INSIDER_TRADES = REPO / "data" / "insider" / "trades_normalized.json"

CONGRESS_FEATURE_COLS = [
    "congress_buy_count_90d",
    "congress_sell_count_90d",
    "congress_net_score",
    "congress_score",
    "congress_pelosi_buy",
    "congress_notable_count",
]

OVERLAY_FEATURE_COLS = REGIME_FEATURE_COLS + CONGRESS_FEATURE_COLS + INSIDER_FEATURE_COLS


def _load_trades(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("trades") or []
    except (OSError, json.JSONDecodeError):
        return []


def _agg_overlay(trades: list[dict], window_days: int, as_of: date) -> dict[str, dict]:
    cutoff = (as_of - timedelta(days=window_days)).isoformat()
    as_of_s = as_of.isoformat()
    by_sym: dict[str, dict] = {}
    for t in trades:
        fd = t.get("filing_date") or t.get("transaction_date") or ""
        if fd < cutoff or fd > as_of_s:
            continue
        sym = str(t.get("symbol") or "").upper()
        if not sym:
            continue
        side = t.get("side")
        sig = by_sym.setdefault(sym, {"buy": 0, "sell": 0, "notable": set(), "pelosi": False})
        if side == "buy":
            sig["buy"] += 1
        elif side == "sell":
            sig["sell"] += 1
        pol = str(t.get("politician") or t.get("insider") or "")
        if "pelosi" in pol.lower() and side == "buy":
            sig["pelosi"] = True
        if pol:
            sig["notable"].add(pol)
    out: dict[str, dict] = {}
    for sym, sig in by_sym.items():
        total = sig["buy"] + sig["sell"]
        net = (sig["buy"] - sig["sell"]) / max(total, 1)
        out[sym] = {
            "buy": sig["buy"],
            "sell": sig["sell"],
            "net": net,
            "pelosi": sig["pelosi"],
            "notable_n": len(sig["notable"]),
        }
    return out


def attach_congress_features(df: pd.DataFrame, date_col: str = "date", window_days: int = 90) -> pd.DataFrame:
    trades = _load_trades(CONGRESS_TRADES)
    if not trades:
        for c in CONGRESS_FEATURE_COLS:
            df[c] = 0.0
        return df

    dates = pd.to_datetime(df[date_col], errors="coerce").dt.date
    for c in CONGRESS_FEATURE_COLS:
        df[c] = 0.0

    for idx, d in enumerate(dates):
        if d is None or pd.isna(d):
            continue
        panel = _agg_overlay(trades, window_days, d)
        sym = str(df.at[idx, "symbol"]).upper() if "symbol" in df.columns else ""
        if not sym or sym not in panel:
            continue
        p = panel[sym]
        df.at[idx, "congress_buy_count_90d"] = float(p["buy"])
        df.at[idx, "congress_sell_count_90d"] = float(p["sell"])
        df.at[idx, "congress_net_score"] = float(p["net"])
        df.at[idx, "congress_score"] = float(min(1.0, p["buy"] * 0.15 + p["notable_n"] * 0.1))
        df.at[idx, "congress_pelosi_buy"] = 1.0 if p["pelosi"] else 0.0
        df.at[idx, "congress_notable_count"] = float(p["notable_n"])
    return df


def attach_insider_features(df: pd.DataFrame, date_col: str = "date", window_days: int = 30) -> pd.DataFrame:
    trades = _load_trades(INSIDER_TRADES)
    for c in INSIDER_FEATURE_COLS:
        df[c] = 0.0
    if not trades:
        return df

    dates = pd.to_datetime(df[date_col], errors="coerce").dt.date
    for idx, d in enumerate(dates):
        if d is None or pd.isna(d):
            continue
        sym = str(df.at[idx, "symbol"]).upper() if "symbol" in df.columns else ""
        if not sym:
            continue
        cutoff = (d - timedelta(days=window_days)).isoformat()
        as_of = d.isoformat()
        buys = sells = 0
        ceo_buy = False
        for t in trades:
            if str(t.get("symbol") or "").upper() != sym:
                continue
            fd = t.get("filing_date") or t.get("transaction_date") or ""
            if fd < cutoff or fd > as_of:
                continue
            if t.get("side") == "buy":
                buys += 1
                who = str(t.get("insider") or "").lower()
                if any(x in who for x in ("ceo", "chief executive", "cfo")):
                    ceo_buy = True
            elif t.get("side") == "sell":
                sells += 1
        total = buys + sells
        df.at[idx, "insider_buy_count_30d"] = float(buys)
        df.at[idx, "insider_sell_count_30d"] = float(sells)
        df.at[idx, "insider_net_ratio_30d"] = float(buys / max(total, 1))
        df.at[idx, "insider_cluster_score"] = float(min(1.0, buys * 0.25 + (0.35 if ceo_buy else 0)))
        df.at[idx, "insider_ceo_buy_flag"] = 1.0 if ceo_buy else 0.0
    return df


def attach_all_overlays(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    df = attach_regime_features(df, date_col=date_col)
    df = attach_congress_features(df, date_col=date_col)
    df = attach_insider_features(df, date_col=date_col)
    return df
