"""Regime feature panel for Predictor v3 and trade-signal gating.

Merges:
  - data/macro/YYYY-MM-DD.json  (FRED normalised features + regime label)
  - data/regime/gdelt_timeline.json (GDELT daily tone + rolling deltas)

Public API:
  load_regime_timeline() -> dict[str, dict]
  attach_regime_features(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame
  REGIME_FEATURE_COLS -> list[str]
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
MACRO_DIR = REPO / "data" / "macro"
REGIME_DIR = REPO / "data" / "regime"
GDELT_PATH = REGIME_DIR / "gdelt_timeline.json"
TIMELINE_PATH = REGIME_DIR / "timeline.json"

REGIME_FEATURE_COLS = [
    "gdelt_tone_norm",
    "gdelt_tone_delta_5d",
    "gdelt_article_z",
    "macro_t10y3m_norm",
    "macro_hy_oas_norm",
    "macro_unrate_norm",
    "macro_cpi_norm",
    "macro_indpro_norm",
    "macro_sp500_norm",
    "macro_m2_norm",
    "regime_bull",
    "regime_bear",
    "regime_high_vol",
    "regime_sideways",
]

_REGIME_ONEHOT = {
    "BULL": {"regime_bull": 1.0, "regime_bear": 0.0, "regime_high_vol": 0.0, "regime_sideways": 0.0},
    "BEAR": {"regime_bull": 0.0, "regime_bear": 1.0, "regime_high_vol": 0.0, "regime_sideways": 0.0},
    "HIGH_VOL": {"regime_bull": 0.0, "regime_bear": 0.0, "regime_high_vol": 1.0, "regime_sideways": 0.0},
    "SIDEWAYS": {"regime_bull": 0.0, "regime_bear": 0.0, "regime_high_vol": 0.0, "regime_sideways": 1.0},
}


def _parse_macro_snapshots() -> dict[str, dict]:
    """Build date -> merged macro+regime features from data/macro/*.json."""
    out: dict[str, dict] = {}
    if not MACRO_DIR.is_dir():
        return out
    for fp in sorted(MACRO_DIR.glob("*.json")):
        if fp.name == "current-regime.json":
            continue
        stem = fp.stem
        try:
            datetime.strptime(stem, "%Y-%m-%d")
        except ValueError:
            continue
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        norm = payload.get("normalisedFeatures") or {}
        regime = str(payload.get("regime") or "SIDEWAYS").upper()
        row = {k: float(v) for k, v in norm.items() if isinstance(v, (int, float))}
        row.update(_REGIME_ONEHOT.get(regime, _REGIME_ONEHOT["SIDEWAYS"]))
        out[stem] = row
    return out


def _parse_gdelt_timeline() -> dict[str, dict]:
    if not GDELT_PATH.exists():
        return {}
    try:
        payload = json.loads(GDELT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("rows") or []
    out: dict[str, dict] = {}
    for r in rows:
        d = (r.get("date") or "")[:10]
        if not d:
            continue
        out[d] = {
            "gdelt_tone_norm": float(r.get("gdelt_tone_norm", 0.5) or 0.5),
            "gdelt_tone_delta_5d": float(r.get("gdelt_tone_delta_5d", 0.0) or 0.0),
            "gdelt_article_z": float(r.get("gdelt_article_z", 0.0) or 0.0),
        }
    return out


def load_regime_timeline() -> dict[str, dict]:
    """Return date -> feature dict. Prefers cached timeline.json if fresh."""
    if TIMELINE_PATH.exists():
        try:
            cached = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))
            rows = cached.get("by_date") or {}
            if isinstance(rows, dict) and len(rows) >= 30:
                return {k: dict(v) for k, v in rows.items()}
        except (OSError, json.JSONDecodeError):
            pass

    macro = _parse_macro_snapshots()
    gdelt = _parse_gdelt_timeline()
    all_dates = sorted(set(macro.keys()) | set(gdelt.keys()))
    merged: dict[str, dict] = {}
    defaults_gdelt = {"gdelt_tone_norm": 0.5, "gdelt_tone_delta_5d": 0.0, "gdelt_article_z": 0.0}
    defaults_macro = {k: 0.5 for k in REGIME_FEATURE_COLS if k.startswith("macro_")}
    defaults_macro.update(_REGIME_ONEHOT["SIDEWAYS"])

    last_macro: dict = dict(defaults_macro)
    last_gdelt: dict = dict(defaults_gdelt)
    for d in all_dates:
        if d in macro:
            last_macro = {**defaults_macro, **macro[d]}
        if d in gdelt:
            last_gdelt = {**defaults_gdelt, **gdelt[d]}
        merged[d] = {**last_macro, **last_gdelt}
    return merged


def attach_regime_features(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Left-join regime features onto a ticker feature dataframe."""
    timeline = load_regime_timeline()
    if not timeline:
        for col in REGIME_FEATURE_COLS:
            df[col] = 0.5 if col.startswith("macro_") or col.startswith("gdelt_tone_norm") else 0.0
        if "regime_sideways" in REGIME_FEATURE_COLS:
            df["regime_sideways"] = 1.0
        return df

    dates = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    rows = []
    last: dict | None = None
    for d in dates:
        if d and d in timeline:
            last = timeline[d]
        rows.append(last or {})
    panel = pd.DataFrame(rows, index=df.index)
    for col in REGIME_FEATURE_COLS:
        df[col] = panel.get(col, pd.Series(0.5, index=df.index)).fillna(0.5).astype("float32")
    if "regime_sideways" in df.columns:
        missing = (df["regime_bull"] + df["regime_bear"] + df["regime_high_vol"] + df["regime_sideways"]) < 0.01
        df.loc[missing, "regime_sideways"] = 1.0
    return df


def write_timeline_cache() -> Path:
    """Persist merged timeline for fast training loads."""
    REGIME_DIR.mkdir(parents=True, exist_ok=True)
    by_date = load_regime_timeline()
    doc = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rowCount": len(by_date),
        "featureColumns": REGIME_FEATURE_COLS,
        "by_date": by_date,
    }
    TIMELINE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return TIMELINE_PATH
