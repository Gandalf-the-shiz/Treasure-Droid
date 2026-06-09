"""Congressional stock trade data adapters (Pelosi-tracker apps style).

Sources (priority order):
  1. Quiver Quantitative API (QUIVER_API_KEY) — highest quality if subscribed
  2. Self-hosted capitol-api (CAPITOL_API_URL) — House PTR parser
  3. kadoa congress-trading-monitor GitHub dataset (free, no key)
  4. House/Senate Stock Watcher S3 (may 403; retried with User-Agent)

Normalized trade shape:
  id, symbol, politician, chamber, party, side, transaction_date, filing_date,
  amount_mid_usd, amount_label, is_late, source
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

USER_AGENT = "Nostradamus-CongressCanal/1.0 (+https://github.com/Gandalf-the-shiz/Nostradamus)"
TIMEOUT = 60

KADOA_TRADES_URL = os.getenv(
    "CONGRESS_KADOA_TRADES_URL",
    "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data/trades.json",
)
HOUSE_S3_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_S3_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")


def _parse_date(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _amount_mid(low: float | None, high: float | None, label: str = "") -> float:
    if low is not None and high is not None and low > 0 and high > 0:
        return (float(low) + float(high)) / 2.0
    # House watcher string tiers
    tiers = {
        "$1,001 - $15,000": 8000.0,
        "$15,001 - $50,000": 32500.0,
        "$50,001 - $100,000": 75000.0,
        "$100,001 - $250,000": 175000.0,
        "$250,001 - $500,000": 375000.0,
        "$500,001 - $1,000,000": 750000.0,
        "$1,000,001 - $5,000,000": 3000000.0,
    }
    return tiers.get(label.strip(), 25000.0)


def _normalize_side(tx_type: str) -> str:
    t = (tx_type or "").strip().lower()
    if any(x in t for x in ("purchase", "buy", "p ")):
        return "buy"
    if any(x in t for x in ("sale", "sell", "s ")):
        return "sell"
    return "other"


def _extract_ticker(raw_ticker: object, asset_name: str = "") -> str | None:
    if raw_ticker and str(raw_ticker).strip() not in {"", "--", "N/A", "null"}:
        sym = str(raw_ticker).strip().upper()
        if 1 <= len(sym) <= 5 and sym.isalpha():
            return sym
    # Try bracket ticker e.g. "Apple Inc [AAPL]"
    m = re.search(r"\[([A-Z]{1,5})\]", asset_name or "")
    if m:
        return m.group(1).upper()
    return None


def normalize_kadoa_trade(row: dict) -> dict | None:
    sym = _extract_ticker(row.get("ticker"), str(row.get("asset_name") or ""))
    if not sym:
        return None
    side = _normalize_side(str(row.get("transaction_type") or ""))
    if side == "other":
        return None
    td = _parse_date(row.get("transaction_date"))
    fd = _parse_date(row.get("filing_date"))
    if not td:
        return None
    return {
        "id": str(row.get("id") or ""),
        "symbol": sym,
        "politician": str(row.get("filer_name") or "").strip(),
        "chamber": str(row.get("chamber") or row.get("branch") or "").lower(),
        "party": str(row.get("party") or "").upper()[:1],
        "side": side,
        "transaction_date": td,
        "filing_date": fd or td,
        "amount_mid_usd": _amount_mid(row.get("amount_range_low"), row.get("amount_range_high"),
                                     str(row.get("amount_range_label") or "")),
        "amount_label": str(row.get("amount_range_label") or ""),
        "is_late": bool(row.get("is_late")),
        "source": "kadoa_congress_monitor",
    }


def normalize_house_watcher_trade(row: dict) -> dict | None:
    sym = _extract_ticker(row.get("ticker"), str(row.get("asset_description") or row.get("asset_name") or ""))
    if not sym:
        return None
    side = _normalize_side(str(row.get("type") or row.get("transaction_type") or ""))
    if side == "other":
        return None
    td = _parse_date(row.get("transaction_date"))
    fd = _parse_date(row.get("disclosure_date"))
    if not td:
        return None
    rep = str(row.get("representative") or row.get("politician") or "").strip()
    return {
        "id": f"house_{rep}_{td}_{sym}_{side}",
        "symbol": sym,
        "politician": rep,
        "chamber": "house",
        "party": "",
        "side": side,
        "transaction_date": td,
        "filing_date": fd or td,
        "amount_mid_usd": _amount_mid(None, None, str(row.get("amount") or row.get("amount_range") or "")),
        "amount_label": str(row.get("amount") or ""),
        "is_late": False,
        "source": "house_stock_watcher",
    }


def normalize_senate_watcher_trade(row: dict) -> dict | None:
    sym = _extract_ticker(row.get("ticker"), str(row.get("asset_description") or ""))
    if not sym:
        return None
    side = _normalize_side(str(row.get("type") or ""))
    if side == "other":
        return None
    td = _parse_date(row.get("transaction_date"))
    fd = _parse_date(row.get("disclosure_date"))
    if not td:
        return None
    senator = str(row.get("senator") or row.get("politician") or "").strip()
    return {
        "id": f"senate_{senator}_{td}_{sym}_{side}",
        "symbol": sym,
        "politician": senator,
        "chamber": "senate",
        "party": "",
        "side": side,
        "transaction_date": td,
        "filing_date": fd or td,
        "amount_mid_usd": _amount_mid(None, None, str(row.get("amount") or "")),
        "amount_label": str(row.get("amount") or ""),
        "is_late": False,
        "source": "senate_stock_watcher",
    }


def fetch_kadoa_trades() -> list[dict]:
    try:
        resp = requests.get(KADOA_TRADES_URL, headers={"User-Agent": USER_AGENT}, timeout=180)
    except Exception as exc:
        print(f"[congress] kadoa fetch error: {exc}", flush=True)
        return []
    if resp.status_code != 200:
        print(f"[congress] kadoa HTTP {resp.status_code}", flush=True)
        return []
    try:
        rows = resp.json()
    except Exception:
        return []
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        norm = normalize_kadoa_trade(row)
        if norm:
            out.append(norm)
    print(f"[congress] kadoa normalized {len(out):,} equity trades", flush=True)
    return out


def fetch_stock_watcher(url: str, normalizer) -> list[dict]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        rows = resp.json()
    except Exception:
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        norm = normalizer(row)
        if norm:
            out.append(norm)
    return out


def fetch_quiver_trades() -> list[dict]:
    key = os.getenv("QUIVER_API_KEY", "").strip()
    if not key:
        return []
    url = os.getenv(
        "QUIVER_CONGRESS_URL",
        "https://api.quiverquant.com/beta/live/congresstrading",
    )
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    except Exception as exc:
        print(f"[congress] quiver error: {exc}", flush=True)
        return []
    if resp.status_code != 200:
        print(f"[congress] quiver HTTP {resp.status_code}", flush=True)
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    rows = payload if isinstance(payload, list) else payload.get("data") or []
    out: list[dict] = []
    for row in rows:
        sym = _extract_ticker(row.get("Ticker") or row.get("ticker"), "")
        if not sym:
            continue
        side = _normalize_side(str(row.get("Transaction") or row.get("transaction") or ""))
        if side == "other":
            continue
        td = _parse_date(row.get("TransactionDate") or row.get("transaction_date"))
        if not td:
            continue
        out.append({
            "id": f"quiver_{row.get('Representative', '')}_{td}_{sym}",
            "symbol": sym,
            "politician": str(row.get("Representative") or row.get("Name") or "").strip(),
            "chamber": str(row.get("House") or row.get("chamber") or "").lower(),
            "party": "",
            "side": side,
            "transaction_date": td,
            "filing_date": _parse_date(row.get("ReportDate")) or td,
            "amount_mid_usd": float(row.get("Amount") or 50000),
            "amount_label": str(row.get("Range") or ""),
            "is_late": False,
            "source": "quiver",
        })
    print(f"[congress] quiver {len(out):,} trades", flush=True)
    return out


def fetch_capitol_api_trades() -> list[dict]:
    base = os.getenv("CAPITOL_API_URL", "").strip().rstrip("/")
    if not base:
        return []
    url = f"{base}/api/trades"
    params = {"assetType": "ST", "limit": 5000}
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    rows = payload.get("trades") or payload.get("data") or payload
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        sym = _extract_ticker(row.get("ticker"), str(row.get("assetName") or ""))
        if not sym:
            continue
        side = _normalize_side(str(row.get("category") or row.get("type") or ""))
        if side == "other":
            continue
        td = _parse_date(row.get("tradeDate") or row.get("transaction_date"))
        if not td:
            continue
        out.append({
            "id": str(row.get("id") or ""),
            "symbol": sym,
            "politician": str(row.get("person") or row.get("name") or "").strip(),
            "chamber": "house",
            "party": str(row.get("party") or "")[:1].upper(),
            "side": side,
            "transaction_date": td,
            "filing_date": _parse_date(row.get("filedDate")) or td,
            "amount_mid_usd": 50000.0,
            "amount_label": "",
            "is_late": False,
            "source": "capitol_api",
        })
    return out


def fetch_all_congress_trades() -> list[dict]:
    """Merge trades from all providers; dedupe by (symbol, politician, date, side)."""
    merged: dict[str, dict] = {}
    for batch in (
        fetch_quiver_trades(),
        fetch_capitol_api_trades(),
        fetch_kadoa_trades(),
        fetch_stock_watcher(HOUSE_S3_URL, normalize_house_watcher_trade),
        fetch_stock_watcher(SENATE_S3_URL, normalize_senate_watcher_trade),
    ):
        for t in batch:
            key = f"{t['symbol']}|{t['politician']}|{t['transaction_date']}|{t['side']}"
            if key not in merged or t.get("source") == "quiver":
                merged[key] = t
    out = list(merged.values())
    out.sort(key=lambda x: (x.get("filing_date") or "", x.get("transaction_date") or ""), reverse=True)
    return out
