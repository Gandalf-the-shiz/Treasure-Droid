"""Explainability — turn a signal-frame row into a documented rationale.

Every pick records the ML predictions (proba, expected return, edge), the
neutralized contribution of each alpha sleeve, and a plain-English "why" that
traces the decision back to those numbers. For genome agents we also surface the
genome gate that let the name through and the unified score breakdown.
"""
from __future__ import annotations

from typing import Any

# Human phrases for each sleeve (the "why" behind the math).
SLEEVE_PHRASES = {
    "ml_edge": "model edge",
    "ml_proba": "model probability",
    "reversal_1d": "1-day mean-reversion",
    "reversal_5d": "5-day mean-reversion",
    "momentum_120_20": "6-month momentum",
    "pead": "post-earnings drift",
    "revisions": "analyst revisions",
}


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def sleeve_contributions(row: dict, sleeve_cols: list[str]) -> dict[str, float]:
    out = {}
    for col in sleeve_cols:
        name = col[2:] if col.startswith("n_") else col
        v = row.get(col)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv == fv:  # not NaN
            out[name] = round(fv, 3)
    return out


def build_signals(row: dict, sleeve_cols: list[str]) -> dict[str, Any]:
    return {
        "pred_proba_up": round(float(row.get("pred_proba_up", 0) or 0), 4),
        "pred_ret": round(float(row.get("pred_ret", 0) or 0), 5),
        "edge": round(float(row.get("edge", 0) or 0), 5),
        "alpha_z": round(float(row.get("alpha", 0) or 0), 4),
        "sector": row.get("sector", "—"),
        "sleeves": sleeve_contributions(row, sleeve_cols),
    }


def _top_drivers(sleeves: dict[str, float], side: str, n: int = 3) -> list[str]:
    """Sleeves that most support this side, as readable phrases."""
    sign = 1.0 if side == "long" else -1.0
    ranked = sorted(sleeves.items(), key=lambda kv: kv[1] * sign, reverse=True)
    out = []
    for name, z in ranked[:n]:
        if z * sign <= 0.05:
            continue
        phrase = SLEEVE_PHRASES.get(name, name)
        out.append(f"{phrase} {z:+.1f}\u03c3")
    return out


def build_why(
    row: dict,
    side: str,
    weight: float,
    sleeve_cols: list[str],
    *,
    sizing: str = "",
    gate: str = "",
    unified_rationale: str = "",
) -> str:
    sym = row.get("symbol", "?")
    proba = float(row.get("pred_proba_up", 0) or 0)
    pred_ret = float(row.get("pred_ret", 0) or 0)
    sector = row.get("sector", "—")
    sleeves = sleeve_contributions(row, sleeve_cols)
    drivers = _top_drivers(sleeves, side)
    drivers_txt = "; ".join(drivers) if drivers else "broad signal blend"

    verb = "Long" if side == "long" else "Short"
    lead = (
        f"{verb} {sym}: model {proba * 100:.0f}% up, {_pct(pred_ret)} expected next move."
        if side == "long"
        else f"{verb} {sym}: model only {proba * 100:.0f}% up, {_pct(pred_ret)} expected \u2014 expected to lag peers."
    )
    parts = [lead, f"Drivers: {drivers_txt}."]
    if gate:
        parts.append(gate)
    if unified_rationale:
        parts.append(f"Unified: {unified_rationale}.")
    sizing_txt = f" \u2014 {sizing}" if sizing else ""
    parts.append(
        f"Sized {abs(weight) * 100:.1f}% of book{sizing_txt}, "
        f"sector-neutralized vs {sector} peers."
    )
    return " ".join(parts)
