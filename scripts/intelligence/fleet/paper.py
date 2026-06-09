"""Per-agent forward paper book: portfolio, trade history, daily reasoning.

Each call to step_agent() marks the agent's book at today's prices (realizing the
forward move since the last run), rebalances to the strategy's new targets, and
records every trade with a full rationale. Track record accumulates forward.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
AGENTS_DIR = REPO / "data" / "fleet" / "agents"

import sys

sys.path.insert(0, str(REPO / "scripts"))
from intelligence.fleet import strategies  # noqa: E402
from intelligence.fleet.reasoning import build_signals, build_why  # noqa: E402


def _adir(aid: str) -> Path:
    d = AGENTS_DIR / aid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def load_state(aid: str, starting_cash: float) -> dict:
    return _load(_adir(aid) / "state.json",
                 {"positions": {}, "cash": starting_cash, "startingCash": starting_cash, "lastDate": None})


def _unified_rationale(sym: str, row: dict, side: str) -> str:
    try:
        from intelligence.unified_score import composite_score
        sc = composite_score(sym, pred_proba_up=float(row.get("pred_proba_up", 0.5) or 0.5),
                             pred_ret=float(row.get("pred_ret", 0) or 0), side=side)
        return sc.get("rationale", "")
    except Exception:
        return ""


def step_agent(agent: dict, df: pd.DataFrame, date: str, sleeve_cols: list[str],
               cfg: dict, starting_cash: float = 100_000.0) -> dict:
    aid = agent["id"]
    state = load_state(aid, starting_cash)
    price = dict(zip(df["symbol"], df["price"]))
    rowmap = {r["symbol"]: r for r in df.to_dict("records")}

    def equity_now() -> float:
        eq = float(state["cash"])
        for sym, p in state["positions"].items():
            px = price.get(sym) or p.get("entryPrice", 0.0)
            eq += p["qty"] * px
        return eq

    eq_hist = _load(_adir(aid) / "equity.json", [])
    prev_equity = float(eq_hist[-1]["equity"]) if eq_hist else starting_cash
    equity_pre = equity_now()

    targets = strategies.target_book(agent, df, cfg)
    tgt = {t["symbol"]: t for t in targets}
    cost_bps = float(cfg.get("cost_bps", 5))

    target_qty = {}
    for t in targets:
        px = price.get(t["symbol"], 0.0)
        if px > 0:
            target_qty[t["symbol"]] = int((t["weight"] * equity_pre) / px)

    trades = []
    for sym in set(state["positions"]) | set(target_qty):
        px = price.get(sym) or state["positions"].get(sym, {}).get("entryPrice", 0.0)
        if px <= 0:
            continue
        cur_q = state["positions"].get(sym, {}).get("qty", 0)
        tq = target_qty.get(sym, 0)
        if cur_q == tq:
            continue
        delta = tq - cur_q
        state["cash"] -= delta * px
        state["cash"] -= abs(delta * px) * cost_bps / 10000.0
        row = rowmap.get(sym, {"symbol": sym})
        if tq == 0:
            state["positions"].pop(sym, None)
            reason = f"Exited {sym} \u2014 no longer selected by strategy."
            action = "close"
        else:
            side = "long" if tq > 0 else "short"
            flip = cur_q == 0 or (cur_q > 0) != (tq > 0)
            prior = state["positions"].get(sym, {})
            entry = px if flip else prior.get("entryPrice", px)
            state["positions"][sym] = {"qty": tq, "entryPrice": round(entry, 4), "side": side,
                                       "openedAt": date if flip else prior.get("openedAt", date)}
            t = tgt.get(sym, {})
            unified = _unified_rationale(sym, row, side) if t.get("unified") else ""
            reason = build_why(row, side, t.get("weight", 0), sleeve_cols,
                               sizing=t.get("sizing", ""), gate=t.get("gate", ""), unified_rationale=unified)
            action = "open" if flip else "adjust"
        trades.append({"date": date, "symbol": sym, "side": "buy" if delta > 0 else "sell",
                       "action": action, "qty": abs(delta), "price": round(px, 4), "reason": reason})

    # Build documented picks (current book)
    picks = []
    for t in targets:
        sym = t["symbol"]
        px = price.get(sym, 0.0)
        if px <= 0:
            continue
        pos = state["positions"].get(sym, {})
        row = rowmap.get(sym, {"symbol": sym})
        unified = _unified_rationale(sym, row, t["side"]) if t.get("unified") else ""
        picks.append({
            "symbol": sym, "side": t["side"], "weight": t["weight"],
            "shares": abs(pos.get("qty", 0)), "notional": round(abs(pos.get("qty", 0)) * px, 2),
            "entryPrice": pos.get("entryPrice", round(px, 2)),
            "signals": build_signals(row, sleeve_cols),
            "why": build_why(row, t["side"], t["weight"], sleeve_cols,
                             sizing=t.get("sizing", ""), gate=t.get("gate", ""), unified_rationale=unified),
        })

    equity = equity_now()
    state["lastDate"] = date
    n_long = sum(1 for p in state["positions"].values() if p["qty"] > 0)
    n_short = sum(1 for p in state["positions"].values() if p["qty"] < 0)

    # Persist
    (_adir(aid) / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    if eq_hist and eq_hist[-1].get("date") == date:
        eq_hist[-1] = {"date": date, "equity": round(equity, 2)}
    else:
        eq_hist.append({"date": date, "equity": round(equity, 2)})
    (_adir(aid) / "equity.json").write_text(json.dumps(eq_hist[-400:], indent=2), encoding="utf-8")
    if trades:
        with (_adir(aid) / "trades.jsonl").open("a", encoding="utf-8") as fh:
            for tr in trades:
                fh.write(json.dumps(tr) + "\n")
    gross = sum(abs(p["qty"]) * (price.get(s) or p["entryPrice"]) for s, p in state["positions"].items())
    net = sum(p["qty"] * (price.get(s) or p["entryPrice"]) for s, p in state["positions"].items())
    today = {
        "date": date, "agentId": aid, "name": agent.get("name"), "kind": agent.get("kind"),
        "equity": round(equity, 2), "cash": round(state["cash"], 2),
        "dayPnl": round(equity - prev_equity, 2),
        "returnPct": round((equity / starting_cash - 1.0) * 100, 3),
        "nLong": n_long, "nShort": n_short,
        "grossExposure": round(gross, 2), "netExposure": round(net, 2),
        "nTrades": len(trades), "picks": picks,
    }
    (_adir(aid) / "today.json").write_text(json.dumps(today, indent=2), encoding="utf-8")

    return {
        "id": aid, "name": agent.get("name"), "kind": agent.get("kind"),
        "status": agent.get("status", "shadow"), "equity": round(equity, 2),
        "returnPct": round((equity / starting_cash - 1.0) * 100, 3),
        "dayPnl": round(equity - prev_equity, 2), "nLong": n_long, "nShort": n_short,
        "nPositions": n_long + n_short, "nTrades": len(trades), "date": date,
    }
