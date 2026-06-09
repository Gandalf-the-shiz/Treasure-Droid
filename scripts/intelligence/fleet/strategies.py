"""Per-agent target books from the shared signal frame.

Each strategy turns the explainable signal frame into a list of target
positions (signed weights). Three kinds today; more become sleeves later:
  - alpha_blended : market-neutral L/S from the combined neutralized alpha
  - investor_v3   : long-only top-k, half-Kelly by win probability
  - genome        : an arena genome's selection rule (long + optional short)
"""
from __future__ import annotations

import pandas as pd


def _norm_cap(weights: pd.Series, cap: float, gross: float, sign: float) -> dict[str, float]:
    if weights.empty:
        return {}
    w = weights.clip(lower=0)
    if w.sum() <= 0:
        w = pd.Series(1.0, index=weights.index)
    w = w / w.sum()
    w = w.clip(upper=cap)
    if w.sum() > 0:
        w = w / w.sum()
    return {sym: float(v) * gross * sign for sym, v in w.items()}


def _alpha_blended(df: pd.DataFrame, cfg: dict) -> list[dict]:
    n = len(df)
    if n < 4:
        return []
    top_frac = float(cfg.get("top_frac", 0.10))
    min_side = int(cfg.get("min_names_per_side", 5))
    cap = float(cfg.get("max_name_weight", 0.04))
    gross = float(cfg.get("gross_exposure", 1.0)) / 2.0
    k = max(min_side, int(n * top_frac))
    k = min(k, n // 2)
    s = df.sort_values("alpha", ascending=False)
    longs = s.head(k)
    shorts = s.tail(k)
    out = []
    lw = _norm_cap(longs.set_index("symbol")["alpha"].abs(), cap, gross, +1.0)
    sw = _norm_cap(shorts.set_index("symbol")["alpha"].abs(), cap, gross, -1.0)
    for sym, w in lw.items():
        out.append({"symbol": sym, "side": "long", "weight": round(w, 5),
                    "sizing": "conviction-weighted by blended alpha", "gate": "top-decile blended alpha"})
    for sym, w in sw.items():
        out.append({"symbol": sym, "side": "short", "weight": round(w, 5),
                    "sizing": "conviction-weighted by blended alpha", "gate": "bottom-decile blended alpha"})
    return out


def _investor_v3(df: pd.DataFrame, params: dict) -> list[dict]:
    top_k = int(params.get("top_k", 8))
    min_proba = float(params.get("min_proba", 0.55))
    gross = float(params.get("gross", 0.9))
    elig = df[(df["pred_proba_up"] >= min_proba) & (df["edge"] > 0)].copy()
    if elig.empty:
        return []
    elig = elig.sort_values("edge", ascending=False).head(top_k)
    kelly = (2.0 * elig["pred_proba_up"] - 1.0).clip(lower=0)
    w = _norm_cap(pd.Series(kelly.values, index=elig["symbol"].values), cap=0.25, gross=gross, sign=+1.0)
    return [{"symbol": sym, "side": "long", "weight": round(v, 5),
             "sizing": "half-Kelly by win probability", "gate": f"long gate: proba\u2265{min_proba:.2f}, edge>0"}
            for sym, v in w.items()]


def _genome(df: pd.DataFrame, params: dict) -> list[dict]:
    min_proba = float(params.get("min_proba", 0.58))
    min_pred_ret = float(params.get("min_pred_ret", 0.01))
    top_k = int(params.get("top_k", 8))
    kelly = float(params.get("kelly", 0.5))
    short_on = bool(params.get("short_enabled"))
    short_frac = float(params.get("short_frac", 0.0)) if short_on else 0.0
    gate = f"genome gate: proba\u2265{min_proba:.2f}, |pred_ret|\u2265{min_pred_ret * 100:.1f}%, top-{top_k}"

    longs = df[(df["pred_proba_up"] >= min_proba) & (df["pred_ret"] >= min_pred_ret)].copy()
    longs = longs.sort_values("edge", ascending=False).head(top_k)
    long_gross = 0.9 * (1.0 - short_frac)
    lw_raw = pd.Series((2.0 * longs["pred_proba_up"] - 1.0).clip(lower=0.01).values, index=longs["symbol"].values)
    lw = _norm_cap(lw_raw * kelly + (1 - kelly) * 0.01, cap=0.30, gross=long_gross, sign=+1.0)
    out = [{"symbol": sym, "side": "long", "weight": round(v, 5),
            "sizing": f"Kelly\u00d7{kelly:g}", "gate": gate, "unified": True} for sym, v in lw.items()]

    if short_on and short_frac > 0:
        shorts = df[(df["pred_proba_up"] <= 1 - min_proba) & (df["pred_ret"] <= -min_pred_ret)].copy()
        shorts = shorts.sort_values("edge", ascending=True).head(max(1, int(top_k * short_frac)))
        sw_raw = pd.Series((1.0 - 2.0 * shorts["pred_proba_up"]).clip(lower=0.01).values, index=shorts["symbol"].values)
        sw = _norm_cap(sw_raw * kelly + (1 - kelly) * 0.01, cap=0.30, gross=0.9 * short_frac, sign=-1.0)
        out += [{"symbol": sym, "side": "short", "weight": round(v, 5),
                 "sizing": f"Kelly\u00d7{kelly:g}", "gate": gate, "unified": True} for sym, v in sw.items()]
    return out


def target_book(agent: dict, df: pd.DataFrame, cfg: dict) -> list[dict]:
    kind = agent.get("kind", "")
    params = agent.get("params") or {}
    if kind == "alpha_blended":
        return _alpha_blended(df, cfg)
    if kind == "investor_v3":
        return _investor_v3(df, params)
    if kind == "genome":
        return _genome(df, params)
    return []
