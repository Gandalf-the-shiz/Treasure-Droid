"""Convert investor decisions into Robinhood-ready trade manifests.

Reads data/investor_v3/decisions.json, extracts the latest (or requested) day's
picks, and writes data/trading/robinhood_manifest.json.

Usage:
  python scripts/generate_trade_signals.py
  python scripts/generate_trade_signals.py --date 2026-05-20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from broker.adapter import (  # noqa: E402
    ContractType,
    OrderSide,
    PositionEffect,
    PositionSide,
    RobinhoodAgentBridge,
    TradeIntent,
)
from congress_signals import get_symbol_signal  # noqa: E402
from intelligence.unified_score import composite_score, load_unified_config  # noqa: E402

DECISIONS_PATH = REPO / "data" / "investor_v3" / "decisions.json"
SIGNALS_PATH = REPO / "data" / "trading" / "signals.json"


def _load_decisions() -> dict:
    if not DECISIONS_PATH.exists():
        raise SystemExit(f"missing {DECISIONS_PATH} — run train-investor-v3.py first")
    return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))


def _pick_day(decisions: dict, target: str | None) -> dict | None:
    days = decisions.get("days") or []
    if not days:
        return None
    if target:
        for d in days:
            if d.get("date") == target:
                return d
        return None
    # Latest non-FINAL day with picks
    for d in reversed(days):
        if d.get("date") == "FINAL":
            continue
        if d.get("picks"):
            return d
    return days[-1] if days else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="YYYY-MM-DD (default: latest day with picks)")
    ap.add_argument("--portfolio-value", type=float, default=float(os.getenv("BROKER_PORTFOLIO_VALUE", "10000")))
    ap.add_argument("--cash", type=float, default=0.0, help="override cash; 0 = use day record")
    ap.add_argument("--unified-score", action="store_true",
                    default=os.getenv("UNIFIED_SCORE_ENABLED", "true").lower() in {"1", "true", "yes"},
                    help="Use composite ML+congress+insider+crowd score for sizing (default on)")
    ap.add_argument("--alt-scale", type=float, default=float(os.getenv("UNIFIED_ALT_SCALE", "1.0")),
                    help="Multiplier on non-ML score components")
    ap.add_argument("--allow-shorts", action="store_true",
                    default=os.getenv("ALLOW_SHORTS", "true").lower() in {"1", "true", "yes"})
    ap.add_argument("--max-short-positions", type=int, default=int(os.getenv("MAX_SHORT_POSITIONS", "3")))
    args = ap.parse_args()

    decisions = _load_decisions()
    day = _pick_day(decisions, args.date or None)
    if not day:
        raise SystemExit("no trading day found in decisions.json")

    trade_date = day["date"]
    cash = args.cash if args.cash > 0 else float(day.get("cash") or 0)
    equity = float(day.get("equity") or args.portfolio_value)
    picks = day.get("picks") or []
    try:
        from intelligence.tradeable_universe import filter_picks
        picks = filter_picks(picks)
    except Exception:
        pass

    intents: list[TradeIntent] = []
    prices: dict[str, float] = {}
    for p in picks:
        sym = str(p.get("symbol") or "").upper()
        if not sym:
            continue
        px = float(p.get("entry_price") or 0)
        if px > 0:
            prices[sym] = px
        notional = float(p.get("notional") or 0)
        proba = float(p.get("pred_proba_up") or 0)
        pred_ret = float(p.get("pred_ret") or 0)
        rationale = str(p.get("why") or "investor_v3 pick")
        unified_meta = None
        if args.unified_score and load_unified_config().get("enabled"):
            unified_meta = composite_score(
                sym, pred_proba_up=proba, pred_ret=pred_ret, side="long", alt_scale=args.alt_scale,
            )
            notional = round(notional * float(unified_meta["notionalMultiplier"]), 2)
            rationale += f" | Unified: {unified_meta['rationale']}"
        else:
            congress_meta = p.get("congress") or get_symbol_signal(sym)
            if isinstance(congress_meta, dict) and congress_meta.get("notable_politicians"):
                pols = ", ".join(congress_meta["notable_politicians"][:3])
                rationale += f" | Congress: {pols} recently active"

        intents.append(
            TradeIntent(
                symbol=sym,
                side=OrderSide.BUY,
                notional_usd=notional,
                proba_up=proba,
                pred_ret=pred_ret,
                edge=float(p.get("edge") or 0),
                rationale=rationale,
                trade_date=trade_date,
                position_side=PositionSide.LONG,
                position_effect=PositionEffect.OPEN,
                contract_type=ContractType.EQUITY,
            )
        )

    if args.allow_shorts:
        live_path = REPO / "data" / "predictions_v3" / "live.csv"
        if live_path.exists():
            import pandas as pd
            live = pd.read_csv(live_path)
            if not live.empty and "pred_ret" in live.columns:
                short_df = live[
                    (live["pred_ret"] <= -0.02) &
                    (live["pred_proba_up"] <= 0.42)
                ].copy()
                if args.unified_score and load_unified_config().get("enabled"):
                    from intelligence.unified_score import apply_panel_scores
                    short_df = apply_panel_scores(short_df, side="short", alt_scale=args.alt_scale)
                    short_df = short_df.sort_values("unified_score", ascending=False)
                else:
                    short_df = short_df.sort_values("pred_ret")
                short_df = short_df.head(args.max_short_positions)
                short_budget = equity * 0.15 / max(len(short_df), 1)
                for _, r in short_df.iterrows():
                    sym = str(r["symbol"]).upper()
                    px = float(r.get("last_px") or r.get("close") or 0)
                    if px <= 0:
                        continue
                    prices[sym] = px
                    proba = float(r.get("pred_proba_up") or 0)
                    pred_ret = float(r.get("pred_ret") or 0)
                    short_rationale = "ML short candidate — negative expected return"
                    short_notional = short_budget
                    if args.unified_score and load_unified_config().get("enabled"):
                        us = composite_score(
                            sym, pred_proba_up=proba, pred_ret=pred_ret, side="short", alt_scale=args.alt_scale,
                        )
                        short_notional = round(short_budget * float(us["notionalMultiplier"]), 2)
                        short_rationale += f" | Unified: {us['rationale']}"
                    intents.append(
                        TradeIntent(
                            symbol=sym,
                            side=OrderSide.SELL,
                            notional_usd=short_notional,
                            proba_up=proba,
                            pred_ret=pred_ret,
                            edge=float(r.get("edge") or 0),
                            rationale=short_rationale,
                            trade_date=trade_date,
                            position_side=PositionSide.SHORT,
                            position_effect=PositionEffect.OPEN,
                            contract_type=ContractType.EQUITY,
                        )
                    )

    # Sells from prior-day settlements (T+1 close)
    for s in day.get("settled") or []:
        sym = str(s.get("symbol") or "").upper()
        if not sym:
            continue
        # Approximate sell notional from pnl + unknown entry — skip if no price
        intents.append(
            TradeIntent(
                symbol=sym,
                side=OrderSide.SELL,
                notional_usd=0.0,
                proba_up=0.0,
                pred_ret=float(s.get("ret") or 0),
                edge=0.0,
                rationale="close prior position (T+1 settle)",
                trade_date=trade_date,
            )
        )

    bridge = RobinhoodAgentBridge()
    trade_intents = [i for i in intents if i.notional_usd >= 50]
    orders = bridge.intents_to_orders(trade_intents, prices)
    buy_intents = [i for i in trade_intents if i.side == OrderSide.BUY]
    for order, intent in zip(orders, buy_intents):
        sig = get_symbol_signal(intent.symbol)
        if sig:
            order.metadata["congress"] = {
                "score": sig.get("congress_score"),
                "boost": sig.get("congress_boost"),
                "notable_politicians": sig.get("notable_politicians"),
                "pelosi_buy": sig.get("pelosi_buy"),
                "recent_buys": sig.get("recent_buys", [])[:2],
            }
    risk_notes = []
    summary = decisions.get("summary") or {}
    if float(summary.get("total_return_pct") or 0) < 0:
        risk_notes.append("investor backtest return negative on full window — review before live")
    cfg = decisions.get("config") or {}
    risk_notes.append(f"policy min_proba={cfg.get('min_proba')} mode={cfg.get('policy_mode')}")

    manifest = bridge.build_manifest(
        orders,
        portfolio_value=equity,
        cash_available=cash,
        risk_notes=risk_notes,
    )
    manifest["tradeDate"] = trade_date
    manifest["signalCount"] = len(orders)
    ucfg = load_unified_config()
    manifest["unifiedScore"] = {
        "enabled": bool(args.unified_score and ucfg.get("enabled")),
        "altScale": args.alt_scale,
        "weights": ucfg.get("weights"),
        "maxNotionalBoost": ucfg.get("maxNotionalBoost"),
    }
    manifest["congressIntel"] = {
        "enabled": True,
        "symbolsWithSignals": sum(1 for i in buy_intents if get_symbol_signal(i.symbol)),
    }
    manifest["intelligence"] = {
        "unifiedScore": bool(args.unified_score and ucfg.get("enabled")),
        "allowShorts": bool(args.allow_shorts),
        "legalNote": "Insider signals use public SEC Form 4 filings only — not illegal front-running",
    }
    manifest["capabilities"] = {
        "positionSides": ["long", "short"],
        "contractTypes": ["equity", "etf", "option", "spread"],
        "orderTypes": ["market", "limit", "stop", "stop_limit"],
    }
    path = bridge.write_manifest(manifest)

    signals_doc = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tradeDate": trade_date,
        "intents": [
            {
                "symbol": i.symbol,
                "side": i.side.value,
                "notional_usd": i.notional_usd,
                "proba_up": i.proba_up,
                "pred_ret": i.pred_ret,
                "edge": i.edge,
                "rationale": i.rationale,
                "trade_date": i.trade_date,
                "agent": i.agent,
            }
            for i in intents
        ],
        "manifestPath": str(path.relative_to(REPO)),
    }
    SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_PATH.write_text(json.dumps(signals_doc, indent=2), encoding="utf-8")

    print(f"[signals] trade_date={trade_date} orders={len(orders)} manifest={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
