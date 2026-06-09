"""Unified per-symbol score — ML edge + congress + insider + crowd (+ optional penny ML).

Single source of truth for ranking and notional sizing across arena, manifests,
Penny Wolf, and daytrader. Paper/research default; does not prove forward profit.

Usage:
  from intelligence.unified_score import composite_score, apply_panel_scores
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO / "config" / "trading_policy.json"

DEFAULT_WEIGHTS = {
    "mlEdge": 1.0,
    "congress": 0.35,
    "insider": 0.30,
    "crowd": 0.20,
    "pennyMl": 0.15,
}


def _load_policy() -> dict:
    if POLICY_PATH.exists():
        try:
            return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


@lru_cache(maxsize=1)
def load_unified_config() -> dict:
    cfg = _load_policy().get("unifiedScore") or {}
    env_on = os.getenv("UNIFIED_SCORE_ENABLED", "").strip().lower()
    enabled = cfg.get("enabled", True)
    if env_on in {"0", "false", "no"}:
        enabled = False
    elif env_on in {"1", "true", "yes"}:
        enabled = True
    weights = {**DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}
    return {
        "enabled": enabled,
        "weights": weights,
        "maxNotionalBoost": float(cfg.get("maxNotionalBoost") or 1.40),
        "maxNotionalCut": float(cfg.get("maxNotionalCut") or 0.72),
        "minCongressScore": float(cfg.get("minCongressScore") or 0.0),
    }


def _congress_signal(symbol: str) -> dict | None:
    try:
        from congress_signals import get_symbol_signal
        return get_symbol_signal(symbol)
    except Exception:
        return None


def _crowd_signal(symbol: str) -> dict | None:
    try:
        from intelligence.mass_psychology import get_symbol_boost
        return get_symbol_boost(symbol)
    except Exception:
        return None


def _insider_signal(symbol: str) -> dict | None:
    try:
        from intelligence.insider_monitor import get_follow_boost
        return get_follow_boost(symbol)
    except Exception:
        return None


def _ml_edge(pred_proba_up: float, pred_ret: float, side: str) -> float:
    """Signed ML edge; higher = better for the given side."""
    p = float(pred_proba_up or 0.5)
    r = float(pred_ret or 0.0)
    if side == "short":
        p = 1.0 - p
        r = -r
    return (p - 0.5) * 2.0 + r * 5.0


def _congress_contrib(sig: dict | None, side: str, min_score: float) -> float:
    if not sig:
        return 0.0
    score = float(sig.get("congress_score") or sig.get("score") or 0.0)
    if score < min_score:
        return 0.0
    net = float(sig.get("net_flow_score") or 0.0)
    if side == "short":
        net = -net
        score = score * (0.5 if float(sig.get("sell_count") or 0) > float(sig.get("buy_count") or 0) else -0.25)
    else:
        if sig.get("pelosi_buy"):
            score = min(1.0, score + 0.12)
    # Normalize to roughly -1..1
    return max(-1.0, min(1.0, net * 0.8 + (score - 0.3) * 0.6))


def _insider_contrib(sig: dict | None, side: str) -> float:
    if not sig:
        return 0.0
    fed = float(sig.get("fedMonitorScore") or 0.0)
    rec = str(sig.get("recommendedSide") or "watch")
    if side == "long":
        if rec == "buy" or fed >= 0.4:
            return min(1.0, fed + 0.1)
        if fed < 0.2:
            return -0.15
        return fed * 0.5
    # Short: insider buy clusters argue against shorting
    if fed >= 0.4:
        return -min(1.0, fed + 0.15)
    if fed < 0.2:
        return 0.1
    return -fed * 0.3


def _crowd_contrib(sig: dict | None, side: str) -> float:
    if not sig:
        return 0.0
    raw = float(sig.get("crowdScore") or 0.0)
    if side == "short":
        raw = -raw
    return max(-1.0, min(1.0, raw * 2.5))


def _penny_ml_contrib(score: float | None, side: str) -> float:
    if score is None:
        return 0.0
    v = max(-1.0, min(1.0, float(score) * 20.0))
    return -v if side == "short" else v


def composite_score(
    symbol: str,
    *,
    pred_proba_up: float = 0.5,
    pred_ret: float = 0.0,
    side: str = "long",
    alt_scale: float = 1.0,
    penny_ml_score: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return component scores and composite (higher = stronger conviction for side)."""
    sym = str(symbol or "").upper()
    cfg = load_unified_config()
    w = {**cfg["weights"], **(weights or {})}
    side = "short" if side == "short" else "long"

    if not cfg["enabled"]:
        ml = _ml_edge(pred_proba_up, pred_ret, side)
        return {
            "symbol": sym,
            "side": side,
            "enabled": False,
            "mlEdge": round(ml, 4),
            "congress": 0.0,
            "insider": 0.0,
            "crowd": 0.0,
            "pennyMl": 0.0,
            "composite": round(ml, 4),
            "notionalMultiplier": 1.0,
            "rationale": "unified score disabled",
        }

    cg = _congress_signal(sym)
    ig = _insider_signal(sym)
    rg = _crowd_signal(sym)

    ml = _ml_edge(pred_proba_up, pred_ret, side)
    cong = _congress_contrib(cg, side, cfg["minCongressScore"])
    ins = _insider_contrib(ig, side)
    crd = _crowd_contrib(rg, side)
    pml = _penny_ml_contrib(penny_ml_score, side)

    scale = max(0.25, float(alt_scale))
    alt = scale * (
        w["congress"] * cong + w["insider"] * ins + w["crowd"] * crd + w["pennyMl"] * pml
    )
    composite = w["mlEdge"] * ml + alt

    # Map composite to notional multiplier (smooth, capped)
    boost = cfg["maxNotionalBoost"]
    cut = cfg["maxNotionalCut"]
    if composite >= 0:
        mult = 1.0 + min(boost - 1.0, composite * 0.12)
    else:
        mult = max(cut, 1.0 + max(-(1.0 - cut), composite * 0.10))

    parts = [f"ML {ml:+.2f}"]
    if abs(cong) > 0.05:
        parts.append(f"Congress {cong:+.2f}")
    if abs(ins) > 0.05:
        parts.append(f"Insider {ins:+.2f}")
    if abs(crd) > 0.05:
        sent = (rg or {}).get("traderSentiment", "neutral")
        parts.append(f"Crowd {crd:+.2f} ({sent})")
    if abs(pml) > 0.05:
        parts.append(f"PennyML {pml:+.2f}")
    if cg and cg.get("pelosi_buy") and side == "long":
        parts.append("Pelosi buy")
    if ig and ig.get("alertLevel"):
        parts.append(f"Form4 {ig.get('alertLevel')}")

    return {
        "symbol": sym,
        "side": side,
        "enabled": True,
        "mlEdge": round(ml, 4),
        "congress": round(cong, 4),
        "insider": round(ins, 4),
        "crowd": round(crd, 4),
        "pennyMl": round(pml, 4),
        "composite": round(composite, 4),
        "notionalMultiplier": round(mult, 4),
        "altScale": round(scale, 3),
        "rationale": " | ".join(parts),
        "congressMeta": {
            "score": cg.get("congress_score") if cg else None,
            "pelosi_buy": bool(cg.get("pelosi_buy")) if cg else False,
            "notable_politicians": (cg.get("notable_politicians") or [])[:3] if cg else [],
        },
        "insiderMeta": {
            "fedMonitorScore": ig.get("fedMonitorScore") if ig else None,
            "alertLevel": ig.get("alertLevel") if ig else None,
        },
        "crowdMeta": {
            "traderSentiment": rg.get("traderSentiment") if rg else None,
            "crowdScore": rg.get("crowdScore") if rg else None,
        },
    }


def apply_panel_scores(
    df,
    *,
    side: str = "long",
    alt_scale: float = 1.0,
    score_col: str = "unified_score",
):
    """Add unified_score column to a predictions panel DataFrame."""
    import pandas as pd

    if df is None or (hasattr(df, "empty") and df.empty):
        return df

    rows = []
    for _, r in df.iterrows():
        sym = str(r.get("symbol", "")).upper()
        sc = composite_score(
            sym,
            pred_proba_up=float(r.get("pred_proba_up", 0.5) or 0.5),
            pred_ret=float(r.get("pred_ret", 0) or 0),
            side=side,
            alt_scale=alt_scale,
        )
        rows.append(sc["composite"])
    out = df.copy()
    out[score_col] = rows
    return out


def rank_panel_long(df, alt_scale: float = 1.0):
    """Sort panel for long candidates by unified composite."""
    import pandas as pd

    if df is None or df.empty:
        return df
    return apply_panel_scores(df, side="long", alt_scale=alt_scale).sort_values(
        "unified_score", ascending=False
    )


def rank_panel_short(df, alt_scale: float = 1.0):
    """Sort panel for short candidates by unified composite (short-oriented)."""
    import pandas as pd

    if df is None or df.empty:
        return df
    return apply_panel_scores(df, side="short", alt_scale=alt_scale).sort_values(
        "unified_score", ascending=False
    )
