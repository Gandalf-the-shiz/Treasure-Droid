"""Aggregate congressional trades into per-symbol signals for the investor agent."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CONGRESS_DIR = REPO / "data" / "congress"
TRADES_PATH = CONGRESS_DIR / "trades_recent.json"
SIGNALS_PATH = CONGRESS_DIR / "signals_by_symbol.json"
LEADERBOARD_PATH = CONGRESS_DIR / "leaderboard.json"
NOTABLE_PATH = CONGRESS_DIR / "notable_trades.json"
WATCHLIST_PATH = REPO / "config" / "congress_watchlist.json"

DEFAULT_WINDOW = 90
DEFAULT_MIN_AMOUNT = 15000.0


def _load_watchlist() -> dict:
    if WATCHLIST_PATH.exists():
        try:
            return json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"notable": [], "signalWindowDays": DEFAULT_WINDOW, "minAmountMidUsd": DEFAULT_MIN_AMOUNT}


def _politician_weight(name: str, watchlist: dict) -> float:
    nl = name.lower()
    for entry in watchlist.get("notable") or []:
        main = str(entry.get("name") or "").lower()
        if main and main in nl:
            return float(entry.get("weight") or 1.0)
        for alias in entry.get("aliases") or []:
            if str(alias).lower() in nl:
                return float(entry.get("weight") or 1.0)
    return 1.0


def _is_notable(name: str, watchlist: dict) -> bool:
    return _politician_weight(name, watchlist) > 1.0


def filter_recent_trades(trades: list[dict], window_days: int, min_amount: float) -> list[dict]:
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    out: list[dict] = []
    for t in trades:
        fd = t.get("filing_date") or t.get("transaction_date") or ""
        if fd < cutoff:
            continue
        if float(t.get("amount_mid_usd") or 0) < min_amount:
            continue
        if t.get("side") not in {"buy", "sell"}:
            continue
        out.append(t)
    return out


def build_signals(trades: list[dict], watchlist: dict | None = None) -> dict[str, Any]:
    wl = watchlist or _load_watchlist()
    window = int(wl.get("signalWindowDays") or DEFAULT_WINDOW)
    min_amt = float(wl.get("minAmountMidUsd") or DEFAULT_MIN_AMOUNT)
    recent = filter_recent_trades(trades, window, min_amt)
    watchlist_history = filter_recent_trades(
        [t for t in trades if _is_notable(str(t.get("politician") or ""), wl)],
        int(wl.get("watchlistHistoryDays") or 365),
        min_amt,
    )

    by_symbol: dict[str, dict] = {}
    politician_stats: dict[str, dict] = {}

    for t in recent:
        sym = str(t.get("symbol") or "").upper()
        if not sym:
            continue
        pol = str(t.get("politician") or "")
        side = t.get("side")
        w = _politician_weight(pol, wl)
        amt = float(t.get("amount_mid_usd") or 0) * w

        sig = by_symbol.setdefault(
            sym,
            {
                "symbol": sym,
                "buy_count": 0,
                "sell_count": 0,
                "buy_notional_est": 0.0,
                "sell_notional_est": 0.0,
                "politicians": [],
                "notable_politicians": [],
                "recent_buys": [],
                "pelosi_buy": False,
                "last_filing_date": "",
            },
        )
        if side == "buy":
            sig["buy_count"] += 1
            sig["buy_notional_est"] += amt
        else:
            sig["sell_count"] += 1
            sig["sell_notional_est"] += amt

        if pol and pol not in sig["politicians"]:
            sig["politicians"].append(pol)
        if _is_notable(pol, wl) and pol not in sig["notable_politicians"]:
            sig["notable_politicians"].append(pol)
        if "pelosi" in pol.lower() and side == "buy":
            sig["pelosi_buy"] = True

        fd = t.get("filing_date") or ""
        if fd > sig["last_filing_date"]:
            sig["last_filing_date"] = fd
        if side == "buy":
            sig["recent_buys"].append({
                "politician": pol,
                "date": t.get("transaction_date"),
                "filing_date": fd,
                "amount_label": t.get("amount_label"),
                "weight": w,
            })

        ps = politician_stats.setdefault(pol, {"politician": pol, "buys": 0, "sells": 0, "symbols": set()})
        if side == "buy":
            ps["buys"] += 1
        else:
            ps["sells"] += 1
        ps["symbols"].add(sym)

    # Apply 365d watchlist history (captures Pelosi trades outside 90d window)
    for t in watchlist_history:
        sym = str(t.get("symbol") or "").upper()
        if not sym:
            continue
        pol = str(t.get("politician") or "")
        side = t.get("side")
        sig = by_symbol.setdefault(
            sym,
            {
                "symbol": sym,
                "buy_count": 0,
                "sell_count": 0,
                "buy_notional_est": 0.0,
                "sell_notional_est": 0.0,
                "politicians": [],
                "notable_politicians": [],
                "recent_buys": [],
                "pelosi_buy": False,
                "last_filing_date": "",
            },
        )
        if pol and pol not in sig["politicians"]:
            sig["politicians"].append(pol)
        if _is_notable(pol, wl) and pol not in sig["notable_politicians"]:
            sig["notable_politicians"].append(pol)
        if "pelosi" in pol.lower() and side == "buy":
            sig["pelosi_buy"] = True

    for sym, sig in by_symbol.items():
        total = sig["buy_count"] + sig["sell_count"]
        net = sig["buy_count"] - sig["sell_count"]
        sig["net_flow_score"] = round(net / max(total, 1), 4)
        sig["congress_score"] = round(
            min(1.0, (sig["buy_notional_est"] - sig["sell_notional_est"]) / 500_000.0 + 0.5 * len(sig["notable_politicians"])),
            4,
        )
        sig["congress_boost"] = round(1.0 + min(0.25, sig["congress_score"] * 0.15), 4)
        if sig["pelosi_buy"]:
            sig["congress_score"] = round(min(1.0, sig["congress_score"] + 0.15), 4)
            sig["congress_boost"] = round(min(1.35, sig["congress_boost"] + 0.08), 4)
        sig["recent_buys"] = sorted(sig["recent_buys"], key=lambda x: x.get("filing_date") or "", reverse=True)[:5]

    leaderboard = []
    for pol, ps in politician_stats.items():
        if not pol:
            continue
        leaderboard.append({
            "politician": pol,
            "buys": ps["buys"],
            "sells": ps["sells"],
            "unique_symbols": len(ps["symbols"]),
            "weight": _politician_weight(pol, wl),
            "notable": _is_notable(pol, wl),
        })
    leaderboard.sort(key=lambda x: (x["notable"], x["buys"]), reverse=True)

    notable_trades = [
        t for t in recent
        if _is_notable(str(t.get("politician") or ""), wl)
    ][:200]

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windowDays": window,
        "tradeCount": len(recent),
        "symbolCount": len(by_symbol),
        "bySymbol": by_symbol,
        "leaderboard": leaderboard[:50],
        "notableTrades": notable_trades,
        "watchlistHistory": watchlist_history[:500],
    }


def load_signals() -> dict[str, dict]:
    if not SIGNALS_PATH.exists():
        return {}
    try:
        doc = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
        return doc.get("bySymbol") or doc.get("by_symbol") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_symbol_signal(symbol: str) -> dict | None:
    return load_signals().get(symbol.upper())


def write_artifacts(trades: list[dict], signals_doc: dict) -> None:
    CONGRESS_DIR.mkdir(parents=True, exist_ok=True)
    TRADES_PATH.write_text(
        json.dumps(
            {
                "generatedAt": signals_doc["generatedAt"],
                "count": len(trades),
                "trades": trades[:5000],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    SIGNALS_PATH.write_text(json.dumps(signals_doc, indent=2), encoding="utf-8")
    LEADERBOARD_PATH.write_text(
        json.dumps({"generatedAt": signals_doc["generatedAt"], "leaderboard": signals_doc["leaderboard"]}, indent=2),
        encoding="utf-8",
    )
    NOTABLE_PATH.write_text(
        json.dumps(
            {
                "generatedAt": signals_doc["generatedAt"],
                "trades90d": signals_doc.get("notableTrades") or [],
                "watchlistHistory365d": signals_doc.get("watchlistHistory") or [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
