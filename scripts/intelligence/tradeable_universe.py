"""Tradeable universe filter — Mega Yacht plan single source of truth."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "tradeable_universe.json"
HIST_DIR = REPO / "data" / "historical"


@lru_cache(maxsize=1)
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "min_price_usd": 5.0,
        "min_adv_usd": 1_000_000.0,
        "exclude_suffixes": ["W", "WW", "WS", "WI", "WT", "RT", "U"],
        "exclude_symbols": [],
        "exclude_pattern": "",
    }


def _suffix_blocked(sym: str, cfg: dict) -> bool:
    for suf in cfg.get("exclude_suffixes") or []:
        if sym.endswith(suf):
            return True
    return False


def _pattern_blocked(sym: str, cfg: dict) -> bool:
    pat = cfg.get("exclude_pattern") or ""
    if not pat:
        return False
    try:
        return bool(re.match(pat, sym, re.I))
    except re.error:
        return False


@lru_cache(maxsize=1)
def _liquidity_cache() -> dict[str, dict]:
    """Last close + adv_20 from historical shards (best-effort)."""
    out: dict[str, dict] = {}
    if not HIST_DIR.exists():
        return out
    for fp in sorted(HIST_DIR.glob("*.json")):
        if fp.name.startswith("manifest"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            sym_u = str(sym).upper()
            if sym_u in out:
                continue
            candles = (payload or {}).get("candles") or []
            if not candles:
                continue
            last = candles[-1]
            close = float(last.get("close") or 0)
            vol = float(last.get("volume") or 0)
            adv = close * vol if close and vol else 0.0
            out[sym_u] = {"close": close, "adv_20": adv, "vol_20": 0.02}
    return out


def is_tradeable(
    symbol: str,
    *,
    close: float | None = None,
    adv_20: float | None = None,
    cfg: dict | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason)."""
    cfg = cfg or load_config()
    sym = str(symbol or "").strip().upper()
    if not sym or sym == "—":
        return False, "empty"
    if sym in {s.upper() for s in (cfg.get("exclude_symbols") or [])}:
        return False, "excluded_symbol"
    if _suffix_blocked(sym, cfg):
        return False, "warrant_or_unit_suffix"
    if _pattern_blocked(sym, cfg):
        return False, "exclude_pattern"

    if close is None or adv_20 is None:
        prof = _liquidity_cache().get(sym) or {}
        close = close if close is not None else prof.get("close")
        adv_20 = adv_20 if adv_20 is not None else prof.get("adv_20")

    min_px = float(cfg.get("min_price_usd") or 0)
    min_adv = float(cfg.get("min_adv_usd") or 0)
    if cfg.get("require_liquidity_profile") and close is None:
        return False, "no_liquidity_profile"
    if close is not None and min_px and close < min_px:
        return False, f"price<{min_px}"
    if adv_20 is not None and min_adv and adv_20 < min_adv:
        return False, f"adv<{min_adv}"
    return True, "ok"


def filter_symbols(symbols: list[str], *, cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    out = []
    for s in symbols:
        ok, _ = is_tradeable(s, cfg=cfg)
        if ok:
            out.append(str(s).upper())
    return out


def filter_dataframe(df: pd.DataFrame, symbol_col: str = "symbol", *, cfg: dict | None = None) -> pd.DataFrame:
    if df is None or df.empty or symbol_col not in df.columns:
        return df
    cfg = cfg or load_config()
    mask = []
    for sym in df[symbol_col].astype(str):
        ok, _ = is_tradeable(sym, cfg=cfg)
        mask.append(ok)
    filtered = df.loc[mask].copy()
    dropped = len(df) - len(filtered)
    if dropped:
        print(f"[tradeable] dropped {dropped}/{len(df)} symbols", flush=True)
    return filtered


def filter_picks(picks: list[dict], symbol_key: str = "symbol", *, cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    out = []
    for p in picks:
        sym = p.get(symbol_key) or p.get("sym")
        ok, reason = is_tradeable(str(sym or ""), cfg=cfg)
        if ok:
            out.append(p)
        else:
            print(f"[tradeable] drop {sym}: {reason}", flush=True)
    return out
