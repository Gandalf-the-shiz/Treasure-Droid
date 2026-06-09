"""Alpaca PAPER executor for the market-neutral alpha book (Alpha Doctrine D).

Reads data/intelligence/alpha/book.json and turns the long/short weights into
Alpaca **paper** orders. Safe by default:
  - Always uses the PAPER endpoint (paper-api.alpaca.markets).
  - Dry-run unless you pass --execute AND keys are present.
  - Refuses to touch a live account.

This is the forward-paper scoreboard for the alpha book. Live capital still only
flows through the readiness gate / Mega Yacht ladder.

Keys: set ALPACA_API_KEY / ALPACA_API_SECRET in config/secrets.json (gitignored)
or env. Generate PAPER keys from the Alpaca dashboard (Trading API → Paper).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
from app_secrets import get_secret  # noqa: E402

BOOK_PATH = REPO / "data" / "intelligence" / "alpha" / "book.json"
STATE_PATH = REPO / "data" / "intelligence" / "alpha" / "alpaca_state.json"
PAPER_BASE = "https://paper-api.alpaca.markets"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _headers() -> dict | None:
    key = get_secret("ALPACA_API_KEY")
    sec = get_secret("ALPACA_API_SECRET")
    if not key or not sec:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}


def _load_book() -> dict:
    if not BOOK_PATH.exists():
        return {}
    try:
        return json.loads(BOOK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_account(headers: dict) -> dict:
    r = requests.get(f"{PAPER_BASE}/v2/account", headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def eligible_assets(headers: dict) -> dict[str, dict]:
    """Map symbol -> {tradable, shortable, etb} from Alpaca's active asset list."""
    try:
        r = requests.get(f"{PAPER_BASE}/v2/assets?status=active&asset_class=us_equity",
                          headers=headers, timeout=40)
        r.raise_for_status()
        out = {}
        for a in r.json():
            out[a.get("symbol", "").upper()] = {
                "tradable": bool(a.get("tradable")),
                "shortable": bool(a.get("shortable")),
                "etb": bool(a.get("easy_to_borrow")),
            }
        return out
    except requests.RequestException:
        return {}


def flatten(headers: dict) -> None:
    """Close all positions and cancel open orders (clean slate before rebalance)."""
    requests.delete(f"{PAPER_BASE}/v2/orders", headers=headers, timeout=20)
    requests.delete(f"{PAPER_BASE}/v2/positions", headers=headers, timeout=30)


def _orders_from_book(
    book: dict, equity: float, gross: float, eligible: dict | None = None
) -> list[dict]:
    """Whole-share qty orders, dollar-neutral, filtered to tradeable/shortable names.

    Each side is independently renormalized to gross/2 of equity so dropping a
    non-shortable name doesn't tilt the book net-long (preserves neutrality).
    """
    b = book.get("book") or {}
    eligible = eligible or {}

    def _ok(sym: str, is_short: bool) -> bool:
        if not eligible:
            return True  # no asset list -> trust the engine, let Alpaca reject edge cases
        e = eligible.get(sym.upper())
        if not e or not e["tradable"]:
            return False
        return (e["shortable"] and e["etb"]) if is_short else True

    def _side_orders(rows: list[dict], is_short: bool) -> list[dict]:
        keep = [
            p for p in rows
            if float(p.get("price") or 0) > 0
            and float(p.get("weight") or 0) != 0
            and _ok(p["symbol"], is_short)
        ]
        wsum = sum(abs(float(p["weight"])) for p in keep)
        if wsum <= 0:
            return []
        target_side = (gross / 2.0) * equity
        out = []
        for p in keep:
            w = abs(float(p["weight"])) / wsum
            qty = int((w * target_side) // float(p["price"]))
            if qty < 1:
                continue
            out.append({
                "symbol": p["symbol"],
                "qty": qty,
                "side": "sell" if is_short else "buy",
                "type": "market",
                "time_in_force": "day",
                "_notional": round(qty * float(p["price"]), 2),
            })
        return out

    return _side_orders(b.get("longs") or [], False) + _side_orders(b.get("shorts") or [], True)


def run(execute: bool = False, gross: float = 1.0, capital: float | None = None) -> dict:
    book = _load_book()
    if not book.get("ok"):
        return {"ok": False, "message": "no valid alpha book — run alpha/engine.py first"}

    headers = _headers()
    if headers is None:
        orders = _orders_from_book(book, capital or 100_000.0, gross)
        doc = {
            "generatedAt": _now(),
            "ok": True,
            "mode": "dry_run_no_keys",
            "message": "Set ALPACA_API_KEY/SECRET (paper) to enable. Showing intended orders.",
            "nOrders": len(orders),
            "sample": orders[:10],
        }
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"[alpaca] dry-run (no keys): {len(orders)} intended orders", flush=True)
        return doc

    if os.getenv("ALPACA_PAPER", "true").lower() == "false":
        return {"ok": False, "message": "refusing: ALPACA_PAPER=false. This executor is paper-only."}

    acct = get_account(headers)
    equity = capital if capital else float(acct.get("equity") or acct.get("cash") or 100_000.0)
    eligible = eligible_assets(headers)
    orders = _orders_from_book(book, equity, gross, eligible)
    n_long = sum(1 for o in orders if o["side"] == "buy")
    n_short = sum(1 for o in orders if o["side"] == "sell")
    gross_long = sum(o["_notional"] for o in orders if o["side"] == "buy")
    gross_short = sum(o["_notional"] for o in orders if o["side"] == "sell")

    if not execute:
        doc = {
            "generatedAt": _now(), "ok": True, "mode": "dry_run",
            "accountEquity": equity, "nOrders": len(orders),
            "nLong": n_long, "nShort": n_short,
            "grossLong": round(gross_long, 2), "grossShort": round(gross_short, 2),
            "netExposure": round(gross_long - gross_short, 2),
            "sample": orders[:10],
            "message": "Dry run. Pass --execute to place paper orders.",
        }
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print(f"[alpaca] dry-run: {n_long}L/{n_short}S, grossL=${gross_long:,.0f} "
              f"grossS=${gross_short:,.0f} net=${gross_long-gross_short:,.0f}", flush=True)
        return doc

    flatten(headers)
    import time as _t
    _t.sleep(2)  # let flatten settle before re-entering
    placed, failed, errors = 0, 0, []
    for o in orders:
        payload = {k: v for k, v in o.items() if not k.startswith("_")}
        try:
            r = requests.post(f"{PAPER_BASE}/v2/orders", headers=headers, json=payload, timeout=20)
            if r.status_code in (200, 201):
                placed += 1
            else:
                failed += 1
                if len(errors) < 8:
                    errors.append({"symbol": o["symbol"], "code": r.status_code, "msg": r.text[:160]})
        except requests.RequestException as exc:
            failed += 1
            if len(errors) < 8:
                errors.append({"symbol": o["symbol"], "error": str(exc)[:160]})
    doc = {
        "generatedAt": _now(), "ok": True, "mode": "executed_paper",
        "accountEquity": equity, "placed": placed, "failed": failed, "nOrders": len(orders),
        "nLong": n_long, "nShort": n_short,
        "grossLong": round(gross_long, 2), "grossShort": round(gross_short, 2),
        "netExposure": round(gross_long - gross_short, 2),
        "errors": errors,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[alpaca] PAPER executed: placed={placed} failed={failed}", flush=True)
    return doc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="place paper orders (default dry-run)")
    ap.add_argument("--gross", type=float, default=1.0, help="gross exposure multiplier")
    ap.add_argument("--capital", type=float, default=0.0, help="override capital base")
    args = ap.parse_args()
    print(json.dumps(run(execute=args.execute, gross=args.gross, capital=args.capital or None), indent=2))
