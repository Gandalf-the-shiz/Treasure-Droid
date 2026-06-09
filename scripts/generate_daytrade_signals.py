"""Robinhood fast-path manifest for intraday daytrading."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from broker.adapter import OrderSide, OrderType, RobinhoodAgentBridge, TradeIntent  # noqa: E402
from daytrader_engine import load_predictions, rank_daytrades  # noqa: E402

MANIFEST = REPO / "data" / "trading" / "daytrade_manifest.json"
SIGNALS = REPO / "data" / "trading" / "daytrade_signals.json"


def main() -> int:
    df = load_predictions()
    top_k = int(os.getenv("DAYTRADE_TOP_K", "15"))
    min_proba = float(os.getenv("DAYTRADE_MIN_PROBA", "0.55"))
    picks = rank_daytrades(df, top_k=top_k, min_proba=min_proba)
    if not picks:
        print("[daytrade] no picks — skipping manifest")
        return 0

    cash = float(os.getenv("DAYTRADE_PORTFOLIO", "25000"))
    per = cash * float(os.getenv("DAYTRADE_POSITION_FRAC", "0.06"))
    bridge = RobinhoodAgentBridge(mode=os.getenv("BROKER_MODE", "manifest_only"))
    intents: list[TradeIntent] = []
    prices: dict[str, float] = {}
    for p in picks:
        sym = p["symbol"]
        intents.append(
            TradeIntent(
                symbol=sym,
                side=OrderSide.BUY,
                notional_usd=per,
                proba_up=p["proba_up"],
                pred_ret=p["pred_ret"],
                edge=p["edge"],
                rationale=p["rationale"],
                trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                agent="daytrader_v1",
            )
        )
        prices[sym] = 1.0  # qty from notional only for market orders

    orders = bridge.intents_to_orders(intents, prices)
    for o in orders:
        o.time_in_force = "day"
        o.order_type = OrderType.MARKET
        o.metadata["style"] = "intraday_aggressive"
        o.metadata["max_hold_minutes"] = picks[0].get("hold_minutes", 240) if picks else 240
        o.metadata["allow_flip"] = True

    manifest = bridge.build_manifest(
        orders,
        portfolio_value=cash,
        cash_available=cash * 0.1,
        risk_notes=[
            "INTRADAY_AGGRESSIVE — highest turnover Robinhood path",
            f"top_k={top_k} min_proba={min_proba}",
            "Exit same session; POST ack to /api/trading/ack",
        ],
    )
    manifest["schema"] = "nostradamus.trading.manifest/v1-daytrade"
    manifest["style"] = "intraday_aggressive"
    manifest["refreshSeconds"] = int(os.getenv("DAYTRADE_REFRESH_SEC", "300"))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    SIGNALS.write_text(
        json.dumps({"generatedAt": manifest["generatedAt"], "picks": picks}, indent=2),
        encoding="utf-8",
    )
    print(f"[daytrade] manifest {len(orders)} orders -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
