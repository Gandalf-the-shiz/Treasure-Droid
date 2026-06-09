"""Simulation engines for Investor Arena v1 (threshold) and v2 (rank-unified)."""
from __future__ import annotations

from typing import Any

import pandas as pd

STARTING_CASH = 50_000.0


def _unified_score_row(symbol: str, proba: float, pred_ret: float, side: str, alt_scale: float, contrarian: bool) -> float:
    from intelligence.unified_score import composite_score
    sc = composite_score(symbol, pred_proba_up=proba, pred_ret=pred_ret, side=side, alt_scale=alt_scale)
    comp = float(sc["composite"])
    if contrarian:
        comp = -comp
    return comp


def build_portfolio(genome: dict, result: dict, starting_cash: float = STARTING_CASH) -> list[dict]:
    kelly = float(genome.get("kelly") or 0.5)
    short_frac = float(genome.get("short_frac") or 0)
    gross = starting_cash * kelly * 0.9
    n_long = max(int(result.get("nLong") or 0), 1)
    n_short = max(int(result.get("nShort") or 0), 1) if int(result.get("nShort") or 0) else 0
    long_alloc = gross * (1.0 - short_frac) / n_long if n_long else 0
    short_alloc = gross * short_frac / n_short if n_short else 0
    rows = []
    for t in result.get("trades") or []:
        side = t.get("side", "long")
        notional = long_alloc if side == "long" else short_alloc
        rows.append({
            "symbol": t.get("symbol"),
            "side": side,
            "notionalUsd": round(notional, 2),
            "weightPct": round(notional / starting_cash * 100, 2),
            "modelPredRetPct": round(float(t.get("ret") or 0) * 100, 3),
            "unifiedRationale": t.get("rationale") or "",
        })
    return rows


def build_reasoning(genome: dict, result: dict, version: str) -> str:
    mode = genome.get("selection_mode") or version
    parts = [
        f"Arena {version.upper()} ({mode}): {genome.get('family')} genome.",
        f"Rules: top_k={genome.get('top_k')} kelly={genome.get('kelly')} "
        f"shorts={'on' if genome.get('short_enabled') else 'off'} alt_scale={genome.get('alt_scale')}.",
    ]
    if version == "v1":
        parts.append(
            f"Threshold gate: proba>={genome.get('min_proba')} pred_ret>={genome.get('min_pred_ret')}."
        )
    else:
        parts.append("Rank-unified: picks top names by composite score across full ML panel (no starvation).")
    if genome.get("contrarian"):
        parts.append("Contrarian: inverted unified score.")
    for t in (result.get("trades") or [])[:5]:
        parts.append(
            f"  {t.get('symbol')} {t.get('side')}: model pred_ret {float(t.get('ret', 0))*100:+.2f}%"
        )
    return " ".join(parts)


def simulate_v1(genome: dict, panel: pd.DataFrame, starting_cash: float = STARTING_CASH) -> dict[str, Any]:
    """Original threshold + unified tilt selection."""
    if panel.empty:
        return _empty(genome)

    alt_scale = float(genome.get("alt_scale") or 1.0)
    if genome.get("crowd_w") or genome.get("insider_w"):
        alt_scale = max(0.5, min(1.5, alt_scale * (0.7 + float(genome.get("crowd_w", 0)) + float(genome.get("insider_w", 0)))))

    df = panel.copy()
    long_cands = df[
        (df["pred_proba_up"] >= genome["min_proba"]) &
        (df["pred_ret"] >= genome["min_pred_ret"])
    ].copy()
    long_cands["score"] = long_cands.apply(
        lambda r: _unified_score_row(str(r["symbol"]), float(r["pred_proba_up"]), float(r["pred_ret"]), "long", alt_scale, bool(genome.get("contrarian"))),
        axis=1,
    )
    long_cands = long_cands.sort_values("score", ascending=False)

    short_cands = pd.DataFrame()
    if genome.get("short_enabled"):
        short_cands = df[
            (df["pred_proba_up"] <= (1.0 - genome["min_proba"])) &
            (df["pred_ret"] <= -genome["min_pred_ret"])
        ].copy()
        short_cands["score"] = short_cands.apply(
            lambda r: _unified_score_row(str(r["symbol"]), float(r["pred_proba_up"]), float(r["pred_ret"]), "short", alt_scale, bool(genome.get("contrarian"))),
            axis=1,
        )
        short_cands = short_cands.sort_values("score", ascending=False)

    return _allocate(genome, long_cands, short_cands, starting_cash, "v1")


def simulate_v2(genome: dict, panel: pd.DataFrame, starting_cash: float = STARTING_CASH) -> dict[str, Any]:
    """Rank-based selection across full panel — avoids 4-ticker starvation."""
    if panel.empty:
        return _empty(genome)

    alt_scale = float(genome.get("alt_scale") or 1.0)
    k = int(genome.get("top_k") or 10)

    df = panel.copy()
    df["long_score"] = df.apply(
        lambda r: _unified_score_row(str(r["symbol"]), float(r["pred_proba_up"]), float(r["pred_ret"]), "long", alt_scale, bool(genome.get("contrarian"))),
        axis=1,
    )
    longs = df.sort_values("long_score", ascending=False).head(k)

    shorts = pd.DataFrame()
    if genome.get("short_enabled"):
        df["short_score"] = df.apply(
            lambda r: _unified_score_row(str(r["symbol"]), float(r["pred_proba_up"]), float(r["pred_ret"]), "short", alt_scale, bool(genome.get("contrarian"))),
            axis=1,
        )
        n_short = max(1, int(k * float(genome.get("short_frac") or 0.25)))
        shorts = df.sort_values("short_score", ascending=False).head(n_short)

    return _allocate(genome, longs, shorts, starting_cash, "v2")


def _allocate(genome: dict, longs: pd.DataFrame, shorts: pd.DataFrame, starting_cash: float, version: str) -> dict:
    k = int(genome["top_k"])
    longs = longs.head(k)
    shorts = shorts.head(max(1, int(k * float(genome.get("short_frac", 0.2))))) if not shorts.empty else shorts

    gross = starting_cash * float(genome["kelly"]) * 0.9
    n_long = max(len(longs), 1)
    n_short = max(len(shorts), 1) if len(shorts) else 0
    long_alloc = gross * (1.0 - genome.get("short_frac", 0)) / n_long if n_long else 0
    short_alloc = gross * genome.get("short_frac", 0) / n_short if n_short else 0

    pnl = 0.0
    trades = []
    for _, r in longs.iterrows():
        ret = float(r["pred_ret"])
        sym = str(r["symbol"])
        sc = _unified_score_row(sym, float(r["pred_proba_up"]), ret, "long", float(genome.get("alt_scale") or 1), bool(genome.get("contrarian")))
        from intelligence.unified_score import composite_score
        rationale = composite_score(sym, pred_proba_up=float(r["pred_proba_up"]), pred_ret=ret, side="long", alt_scale=float(genome.get("alt_scale") or 1)).get("rationale", "")
        pnl += long_alloc * ret
        trades.append({"symbol": sym, "side": "long", "position_effect": "open", "ret": ret, "rationale": rationale, "score": sc})
    for _, r in shorts.iterrows():
        ret = float(r["pred_ret"])
        sym = str(r["symbol"])
        rationale = ""
        try:
            from intelligence.unified_score import composite_score
            rationale = composite_score(sym, pred_proba_up=float(r["pred_proba_up"]), pred_ret=ret, side="short", alt_scale=float(genome.get("alt_scale") or 1)).get("rationale", "")
        except Exception:
            pass
        pnl += short_alloc * (-ret)
        trades.append({"symbol": sym, "side": "short", "position_effect": "open", "ret": ret, "rationale": rationale})

    ret_pct = (pnl / starting_cash) * 100 if starting_cash else 0.0
    result = {
        "traderId": genome["trader_id"],
        "seed": genome.get("seed"),
        "family": genome.get("family"),
        "arenaVersion": version,
        "selectionMode": genome.get("selection_mode") or version,
        "returnPct": round(ret_pct, 4),
        "nTrades": len(trades),
        "nLong": len(longs),
        "nShort": len(shorts),
        "shortEnabled": genome.get("short_enabled"),
        "trades": trades[:25],
    }
    result["portfolio"] = build_portfolio(genome, result, starting_cash)
    result["reasoning"] = build_reasoning(genome, result, version)
    return result


def _empty(genome: dict) -> dict:
    return {
        "traderId": genome["trader_id"],
        "seed": genome.get("seed"),
        "family": genome.get("family"),
        "returnPct": 0.0,
        "nTrades": 0,
        "nLong": 0,
        "nShort": 0,
        "shortEnabled": genome.get("short_enabled"),
        "trades": [],
        "portfolio": [],
        "reasoning": "No trades — empty panel or filters excluded all names.",
    }


def simulate(genome: dict, panel: pd.DataFrame, version: str, starting_cash: float = STARTING_CASH) -> dict:
    if version == "v2" or genome.get("selection_mode") == "rank_v2":
        return simulate_v2(genome, panel, starting_cash)
    return simulate_v1(genome, panel, starting_cash)
