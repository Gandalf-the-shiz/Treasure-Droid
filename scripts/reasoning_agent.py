"""Paper-trading reasoning agent — strategy + journal with NPU LLM when available."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "reasoning"
STRATEGY_PATH = OUT / "strategy.json"
JOURNAL_PATH = OUT / "journal.jsonl"
PORTFOLIO_PATH = OUT / "paper_portfolio.json"

sys.path.insert(0, str(REPO / "scripts"))
from market_clock import is_market_open, now_et, session_label  # noqa: E402
from npu_llm import complete  # noqa: E402


def _load_live() -> pd.DataFrame:
    p = REPO / "data" / "predictions_v3" / "live.csv"
    if p.exists():
        return pd.read_csv(p)
    p2 = REPO / "data" / "predictions_v3" / "test.csv"
    if not p2.exists():
        return pd.DataFrame()
    df = pd.read_csv(p2, parse_dates=["date"])
    last = df["date"].max()
    return df[df["date"] == last].copy()


def _load_regime() -> dict:
    p = REPO / "data" / "regime" / "current-regime.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _top_picks(df: pd.DataFrame, k: int = 12) -> list[dict]:
    if df.empty:
        return []
    d = df.copy()
    d["edge"] = (d["pred_proba_up"] - 0.5) * 2.0 * d["pred_ret"].abs()
    d = d.sort_values("edge", ascending=False).head(k)
    picks = []
    for _, r in d.iterrows():
        sym = str(r["symbol"]).upper()
        picks.append({
            "symbol": sym,
            "proba_up": float(r["pred_proba_up"]),
            "pred_ret": float(r["pred_ret"]),
            "edge": float(r["edge"]),
            "rationale": (
                f"ML edge {float(r['edge'])*100:.2f}% — "
                f"P(up)={float(r['pred_proba_up']):.1%}, E[ret]={float(r['pred_ret'])*100:+.2f}%"
            ),
        })
    return picks


def _append_journal(entry: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def tick() -> dict:
    et = now_et()
    live = _load_live()
    regime = _load_regime()
    picks = _top_picks(live, k=int(os.getenv("REASONING_TOP_K", "12")))

    prompt_lines = [
        "You are a paper-trading equity strategist. Respond in 6-8 sentences.",
        f"Session: {session_label(et)} market_open={is_market_open(et)}",
        f"Regime: {json.dumps(regime.get('label') or regime.get('regime') or 'unknown')}",
    ]
    for p in picks[:6]:
        prompt_lines.append(f"PICK: {p['symbol']} edge={p['edge']:.4f} proba={p['proba_up']:.3f}")
    prompt = "\n".join(prompt_lines)
    narrative, backend = complete(prompt, max_tokens=int(os.getenv("REASONING_MAX_TOKENS", "400")))

    strategy = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session_label(et),
        "marketOpen": is_market_open(et),
        "regime": regime,
        "name": os.getenv("REASONING_STRATEGY_NAME", "nostradamus_overlay_momentum"),
        "horizon": "intraday_to_swing",
        "maxPositions": int(os.getenv("REASONING_MAX_POSITIONS", "12")),
        "riskBudget": float(os.getenv("REASONING_RISK_BUDGET", "0.85")),
        "narrative": narrative,
        "llmBackend": backend,
        "watchlist": [p["symbol"] for p in picks],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    STRATEGY_PATH.write_text(json.dumps(strategy, indent=2), encoding="utf-8")

    cash = float(os.getenv("REASONING_PAPER_CASH", "100000"))
    port = {"cash": cash, "positions": {}, "updatedAt": strategy["updatedAt"]}
    if PORTFOLIO_PATH.exists():
        try:
            port = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    for p in picks[: strategy["maxPositions"]]:
        sym = p["symbol"]
        notional = cash * 0.08 / max(len(picks), 1)
        port["positions"][sym] = {
            "notional": round(notional, 2),
            "proba_up": p["proba_up"],
            "pred_ret": p["pred_ret"],
            "reason": p["rationale"],
            "openedAt": strategy["updatedAt"],
        }
    port["updatedAt"] = strategy["updatedAt"]
    PORTFOLIO_PATH.write_text(json.dumps(port, indent=2), encoding="utf-8")

    entry = {
        "ts": strategy["updatedAt"],
        "session": strategy["session"],
        "picks": picks,
        "narrative": narrative,
        "backend": backend,
    }
    _append_journal(entry)
    print(f"[reasoning] {len(picks)} picks backend={backend} session={strategy['session']}")
    return strategy


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--loop-minutes", type=float, default=0.0)
    args = ap.parse_args()
    if args.loop_minutes > 0:
        import time

        while True:
            tick()
            time.sleep(max(args.loop_minutes, 1.0) * 60.0)
    tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
