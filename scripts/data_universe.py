"""Helpers for selecting a high-value ticker universe for free data jobs.

The goal is to keep expensive upstream calls focused on liquid names first while
still rotating through the broader registry so the free sources eventually cover
the whole market.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKERS_FILE = REPO_ROOT / "data" / "tickers" / "us_tickers.json"

CORE_TICKERS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "JPM",
    "AVGO",
    "LLY",
    "UNH",
    "V",
    "XOM",
    "MA",
]


def _normalise_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def load_ticker_records() -> list[dict[str, str]]:
    """Return registry records with symbol and sector metadata when available."""
    if not TICKERS_FILE.exists():
        return [{"symbol": ticker, "sector": "Other"} for ticker in CORE_TICKERS]

    with open(TICKERS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    records: list[dict[str, str]] = []

    def add_record(symbol: str, sector: str = "Other") -> None:
        cleaned = _normalise_symbol(symbol)
        if cleaned:
            records.append({"symbol": cleaned, "sector": sector or "Other"})

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                add_record(item)
            elif isinstance(item, dict):
                symbol = item.get("symbol") or item.get("ticker")
                if symbol:
                    add_record(symbol, str(item.get("sector") or item.get("industry") or "Other"))
    elif isinstance(data, dict):
        for key, value in data.items():
            if key == "metadata":
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        add_record(item, key)
                    elif isinstance(item, dict):
                        symbol = item.get("symbol") or item.get("ticker")
                        if symbol:
                            add_record(symbol, str(item.get("sector") or item.get("industry") or key))
            elif isinstance(value, dict):
                symbol = value.get("symbol") or value.get("ticker")
                if not symbol and key:
                    symbol = key
                if symbol:
                    add_record(symbol, str(value.get("sector") or value.get("industry") or "Other"))
            elif isinstance(value, str):
                add_record(key, value)

    deduped: dict[str, dict[str, str]] = {}
    for record in records:
        symbol = record["symbol"]
        if symbol not in deduped:
            deduped[symbol] = record
    return list(deduped.values())


def _seed_text(seed: str | None) -> str:
    return seed or date.today().isoformat()


def _sector_sort_key(seed: str, sector: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{sector}".encode("utf-8")).hexdigest()
    return digest, sector


def select_priority_tickers(limit: int | None = None, seed: str | None = None) -> list[str]:
    """Return a sector-balanced ticker list with liquid names first."""
    records = load_ticker_records()
    seed_text = _seed_text(seed)

    by_symbol: dict[str, str] = {}
    by_sector: dict[str, list[str]] = {}
    for record in records:
        symbol = _normalise_symbol(record["symbol"])
        sector = record.get("sector") or "Other"
        by_symbol[symbol] = sector
        by_sector.setdefault(sector, []).append(symbol)

    for symbols in by_sector.values():
        symbols.sort()

    ordered: list[str] = []
    seen: set[str] = set()

    for symbol in CORE_TICKERS:
        if symbol in by_symbol and symbol not in seen:
            ordered.append(symbol)
            seen.add(symbol)

    sectors = sorted(by_sector.keys(), key=lambda sector: _sector_sort_key(seed_text, sector))
    active = True
    while active and (limit is None or len(ordered) < limit):
        active = False
        for sector in sectors:
            bucket = by_sector.get(sector, [])
            while bucket and bucket[0] in seen:
                bucket.pop(0)
            if not bucket:
                continue
            symbol = bucket.pop(0)
            ordered.append(symbol)
            seen.add(symbol)
            active = True
            if limit is not None and len(ordered) >= limit:
                return ordered[:limit]

    if limit is None:
        return ordered

    return ordered[:limit]