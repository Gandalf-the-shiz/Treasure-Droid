"""Build ML panel: all historical rows where close < max price (penny universe)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HIST, MAX_PRICE, MIN_PRICE, MIN_ADV20, PANEL_CACHE, START_DATE
from .features import FEATURE_NAMES, features_from_candles

SKIP = {"manifest.json", "multiyear-coverage.json", "stooq-bulk-coverage.json"}


def build_panel(*, refresh: bool = False, max_symbols: int | None = None) -> pd.DataFrame:
    if PANEL_CACHE.exists() and not refresh:
        try:
            df = pd.read_parquet(PANEL_CACHE)
            if len(df) > 10_000:
                return df
        except Exception:
            pass

    start = pd.Timestamp(START_DATE)
    chunks: list[pd.DataFrame] = []
    n_sym = 0

    for fp in sorted(HIST.glob("*.json")):
        if fp.name in SKIP:
            continue
        sector = fp.stem
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            if max_symbols and n_sym >= max_symbols:
                break
            candles = (payload or {}).get("candles") or []
            if len(candles) < 80:
                continue
            raw = pd.DataFrame(candles)
            if "date" not in raw.columns or "close" not in raw.columns:
                continue
            raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
            raw = raw.dropna(subset=["date"]).sort_values("date")
            for c in ("open", "high", "low", "close", "volume"):
                if c in raw.columns:
                    raw[c] = pd.to_numeric(raw[c], errors="coerce")
            raw = raw.dropna(subset=["close"])
            if raw.empty:
                continue

            feats = features_from_candles(raw.set_index("date"))
            base = raw.set_index("date")[["close", "volume"]].join(feats)
            base["symbol"] = sym.upper()
            base["sector"] = sector
            base["adv20"] = (base["close"] * base["volume"]).rolling(20).mean()
            base = base.reset_index().rename(columns={"index": "date"})
            base = base[base["date"] >= start]
            base = base[(base["close"] >= MIN_PRICE) & (base["close"] < MAX_PRICE)]
            base = base[base["adv20"] >= MIN_ADV20]
            base = base.dropna(subset=FEATURE_NAMES, how="any")
            if base.empty:
                continue
            chunks.append(base)
            n_sym += 1
        if max_symbols and n_sym >= max_symbols:
            break

    if not chunks:
        return pd.DataFrame()

    panel = pd.concat(chunks, ignore_index=True)
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    PANEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        panel.to_parquet(PANEL_CACHE, index=False)
    except Exception:
        panel.to_csv(PANEL_CACHE.with_suffix(".csv"), index=False)
    return panel


def add_labels(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Forward return labels per symbol."""
    parts = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        g["y_ret"] = g["close"].shift(-horizon) / g["close"] - 1.0
        g["y_up"] = (g["y_ret"] > 0).astype(int)
        g = g.dropna(subset=["y_ret"])
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
