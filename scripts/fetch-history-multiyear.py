"""
fetch-history-multiyear.py

Multi-year, multi-source backfill for daily OHLCV data. Reuses the
data_sources adapter so it can transparently fall back between yfinance and
Stooq, and writes into the same sector-chunked schema already used by
fetch-history.py and the rest of the pipeline.

Usage:
  python scripts/fetch-history-multiyear.py --years 5
  python scripts/fetch-history-multiyear.py --years 10 --limit 250
  python scripts/fetch-history-multiyear.py --tickers AAPL MSFT NVDA

Notes:
  - Designed to be incremental-safe: new candles are merged into the existing
    sector files without dropping older history.
  - Free providers only by default. Paid providers (Polygon/Tiingo/EODHD)
    can be added in data_sources.py without changing this script.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from data_sources import fetch_equity_history  # noqa: E402

TICKERS_FILE = REPO_ROOT / "data" / "tickers" / "us_tickers.json"
HISTORICAL_DIR = REPO_ROOT / "data" / "historical"
MANIFEST_FILE = HISTORICAL_DIR / "manifest.json"
COVERAGE_FILE = HISTORICAL_DIR / "multiyear-coverage.json"

SECTOR_FILES = {
    "Technology": "technology",
    "Healthcare": "healthcare",
    "Financials": "financials",
    "Consumer Discretionary": "consumer_discretionary",
    "Consumer Staples": "consumer_staples",
    "Energy": "energy",
    "Industrials": "industrials",
    "Materials": "materials",
    "Real Estate": "real_estate",
    "Utilities": "utilities",
    "Communication Services": "communication_services",
    "Other": "other",
}


def sector_filename(sector: str) -> str:
    return SECTOR_FILES.get(sector, "other")


def load_sector_file(sector: str) -> dict:
    path = HISTORICAL_DIR / f"{sector_filename(sector)}.json"
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sector": sector, "lastUpdated": "", "tickerCount": 0, "stocks": {}}


def save_sector_file(sector: str, payload: dict) -> int:
    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORICAL_DIR / f"{sector_filename(sector)}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    return path.stat().st_size


def merge_candles(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_date: dict[str, dict] = {c.get("date"): c for c in existing if c.get("date")}
    for c in incoming:
        d = c.get("date")
        if not d:
            continue
        by_date[d] = c
    merged = list(by_date.values())
    merged.sort(key=lambda c: c["date"])
    return merged


def load_universe() -> list[dict]:
    if not TICKERS_FILE.exists():
        raise SystemExit(f"[multiyear] ticker registry missing: {TICKERS_FILE}")
    with TICKERS_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    tickers = data.get("tickers") if isinstance(data, dict) else data
    if not isinstance(tickers, list):
        raise SystemExit("[multiyear] ticker registry has unexpected schema")
    return tickers


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Multi-year backfill for Nostradamus.")
    ap.add_argument("--years", type=int, default=5, help="Years of history to backfill")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap on number of tickers (0=all)")
    ap.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help="Optional explicit list of tickers (skips registry)",
    )
    ap.add_argument("--sleep-ms", type=int, default=120, help="Inter-symbol throttle in ms")
    ap.add_argument(
        "--min-candles",
        type=int,
        default=200,
        help="Required candle count to accept a symbol",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=int(args.years * 365.25))

    if args.tickers:
        universe = [{"ticker": t.upper(), "sector": "Other"} for t in args.tickers]
    else:
        universe = load_universe()
        if args.limit and args.limit > 0:
            universe = universe[: args.limit]

    print(
        f"[multiyear] start={start} end={end} symbols={len(universe)} "
        f"min_candles={args.min_candles}"
    )

    sector_payloads: dict[str, dict] = {}
    coverage = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rangeStart": str(start),
        "rangeEnd": str(end),
        "yearsRequested": args.years,
        "tickers": {},
        "providersUsed": {},
        "failed": [],
    }

    processed = 0
    succeeded = 0

    for entry in universe:
        symbol = str(entry.get("ticker") or "").strip().upper()
        sector = str(entry.get("sector") or "Other").strip() or "Other"
        if not symbol:
            continue

        candles, provider = fetch_equity_history(
            symbol,
            start,
            end,
            providers=["yfinance", "stooq"],
            min_candles=args.min_candles,
        )
        processed += 1

        if not candles or len(candles) < args.min_candles:
            coverage["failed"].append(symbol)
        else:
            succeeded += 1
            coverage["tickers"][symbol] = {
                "sector": sector,
                "rows": len(candles),
                "firstDate": candles[0]["date"],
                "lastDate": candles[-1]["date"],
                "provider": provider,
            }
            coverage["providersUsed"][provider] = coverage["providersUsed"].get(provider, 0) + 1

            if sector not in sector_payloads:
                sector_payloads[sector] = load_sector_file(sector)
            stocks = sector_payloads[sector].setdefault("stocks", {})
            existing = stocks.get(symbol, {}).get("candles") or []
            stocks[symbol] = {"candles": merge_candles(existing, candles)}

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

        if processed % 25 == 0:
            print(
                f"[multiyear] progress {processed}/{len(universe)} ok={succeeded} "
                f"providers={coverage['providersUsed']}"
            )

    for sector, payload in sector_payloads.items():
        payload["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["tickerCount"] = len(payload.get("stocks") or {})
        size = save_sector_file(sector, payload)
        print(f"[multiyear] wrote sector={sector} bytes={size}")

    COVERAGE_FILE.write_text(f"{json.dumps(coverage, indent=2)}\n", encoding="utf-8")
    print(
        f"[multiyear] complete ok={succeeded}/{processed} "
        f"failed={len(coverage['failed'])} coverage={COVERAGE_FILE}"
    )


if __name__ == "__main__":
    main()
