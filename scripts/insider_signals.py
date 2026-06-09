"""Insider (SEC Form 4) signals per symbol for ML overlays and Robinhood agent."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
INSIDER_DIR = REPO / "data" / "insider"
TRADES_PATH = INSIDER_DIR / "trades_normalized.json"
SIGNALS_PATH = INSIDER_DIR / "signals_by_symbol.json"

INSIDER_FEATURE_COLS = [
    "insider_buy_count_30d",
    "insider_sell_count_30d",
    "insider_net_ratio_30d",
    "insider_cluster_score",
    "insider_ceo_buy_flag",
]


def load_trades() -> list[dict]:
    if not TRADES_PATH.exists():
        return []
    try:
        doc = json.loads(TRADES_PATH.read_text(encoding="utf-8"))
        return doc.get("trades") or []
    except (OSError, json.JSONDecodeError):
        return []


def build_signals(trades: list[dict], window_days: int = 30) -> dict[str, Any]:
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    recent = [
        t for t in trades
        if (t.get("filing_date") or t.get("transaction_date") or "") >= cutoff
        and t.get("side") in {"buy", "sell"}
    ]
    by_sym: dict[str, dict] = {}
    for t in recent:
        sym = str(t.get("symbol") or "").upper()
        if not sym:
            continue
        sig = by_sym.setdefault(
            sym,
            {
                "symbol": sym,
                "buy_count": 0,
                "sell_count": 0,
                "buyers": [],
                "ceo_buy": False,
            },
        )
        side = t.get("side")
        if side == "buy":
            sig["buy_count"] += 1
        else:
            sig["sell_count"] += 1
        who = str(t.get("insider") or "")
        if who and who not in sig["buyers"]:
            sig["buyers"].append(who)
        if side == "buy" and any(x in who.lower() for x in ("ceo", "chief executive", "cfo", "president")):
            sig["ceo_buy"] = True

    for sym, sig in by_sym.items():
        total = sig["buy_count"] + sig["sell_count"]
        net = (sig["buy_count"] - sig["sell_count"]) / max(total, 1)
        sig["insider_buy_count_30d"] = sig["buy_count"]
        sig["insider_sell_count_30d"] = sig["sell_count"]
        sig["insider_net_ratio_30d"] = round((sig["buy_count"] / max(total, 1)), 4)
        sig["insider_cluster_score"] = round(min(1.0, sig["buy_count"] * 0.2 + (0.3 if sig["ceo_buy"] else 0)), 4)
        sig["insider_ceo_buy_flag"] = 1.0 if sig["ceo_buy"] else 0.0

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windowDays": window_days,
        "tradeCount": len(recent),
        "symbolCount": len(by_sym),
        "bySymbol": by_sym,
    }


def load_signals() -> dict[str, dict]:
    if not SIGNALS_PATH.exists():
        return {}
    try:
        doc = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
        return doc.get("bySymbol") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_artifacts(trades: list[dict], window_days: int = 30) -> None:
    INSIDER_DIR.mkdir(parents=True, exist_ok=True)
    TRADES_PATH.write_text(
        json.dumps(
            {
                "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "count": len(trades),
                "trades": trades,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    sig_doc = build_signals(trades, window_days)
    SIGNALS_PATH.write_text(json.dumps(sig_doc, indent=2), encoding="utf-8")


def get_symbol_signal(symbol: str) -> dict | None:
    return load_signals().get(symbol.upper())
