"""
scripts/fetch-history.py
Downloads 1 year of daily OHLCV data for all US tickers from the Phase 2
ticker registry using yfinance, then stores the results as sector-chunked
JSON files in data/historical/.

Usage:
    python scripts/fetch-history.py
    python scripts/fetch-history.py --full-fetch

Incremental mode:
    When a manifest already exists, the script defaults to a 5-day incremental
    refresh. Pass --full-fetch to force a 1-year backfill.

Output:
    data/historical/<sector>.json   — one file per sector
    data/historical/manifest.json   — metadata / coordination file
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKERS_FILE = REPO_ROOT / "data" / "tickers" / "us_tickers.json"
HISTORICAL_DIR = REPO_ROOT / "data" / "historical"
MANIFEST_FILE = HISTORICAL_DIR / "manifest.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 50
BATCH_DELAY = 2          # seconds between batches
MAX_RETRIES = 3
RETRY_DELAYS = [5, 10, 20]   # seconds per retry attempt
MIN_DATA_POINTS = 100    # fewer than this → reject ticker
FAILURE_THRESHOLD = 0.50  # exit non-zero if more than 50% of tickers fail
INCREMENTAL_DAYS = 5     # days to fetch in incremental mode
FULL_FETCH_DAYS = 365    # days to fetch in full mode

# ---------------------------------------------------------------------------
# Sector → filename mapping
# ---------------------------------------------------------------------------

SECTOR_FILES = {
    "Technology":             "technology",
    "Healthcare":             "healthcare",
    "Financials":             "financials",
    "Consumer Discretionary": "consumer_discretionary",
    "Consumer Staples":       "consumer_staples",
    "Energy":                 "energy",
    "Industrials":            "industrials",
    "Materials":              "materials",
    "Real Estate":            "real_estate",
    "Utilities":              "utilities",
    "Communication Services": "communication_services",
    "Other":                  "other",
}


def sector_to_filename(sector: str) -> str:
    """Return the base filename (without .json) for a given sector name."""
    return SECTOR_FILES.get(sector, "other")


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and refresh market history.")
    parser.add_argument(
        "--full-fetch",
        action="store_true",
        help="Force a 1-year backfill instead of the default incremental refresh.",
    )
    return parser.parse_args()


def is_incremental_mode(manifest: dict, full_fetch_requested: bool) -> bool:
    """Return True when we should merge a 5-day incremental refresh."""
    return bool(manifest) and not full_fetch_requested


# ---------------------------------------------------------------------------
# Sector file I/O
# ---------------------------------------------------------------------------

def load_sector_file(sector: str) -> dict:
    """Load an existing sector file, or return an empty structure."""
    path = HISTORICAL_DIR / f"{sector_to_filename(sector)}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"sector": sector, "lastUpdated": "", "tickerCount": 0, "stocks": {}}


def save_sector_file(sector: str, data: dict) -> int:
    """Write a sector file and return the file size in bytes."""
    path = HISTORICAL_DIR / f"{sector_to_filename(sector)}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    return path.stat().st_size


# ---------------------------------------------------------------------------
# yfinance download with retry
# ---------------------------------------------------------------------------

def download_batch(symbols: list[str], period_days: int) -> pd.DataFrame | None:
    """
    Download OHLCV data for a list of symbols via yfinance.
    Returns a MultiIndex DataFrame or None on failure.
    """
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=period_days)
    tickers_str = " ".join(symbols)

    for attempt in range(MAX_RETRIES):
        try:
            df = yf.download(
                tickers_str,
                start=str(start_date),
                end=str(end_date),
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if df.empty:
                return None
            return df
        except Exception as exc:
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            print(
                f"[fetch-history] Batch attempt {attempt + 1}/{MAX_RETRIES} failed: {exc}"
                f" - retrying in {delay}s",
                file=sys.stderr,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(delay)
    return None


# ---------------------------------------------------------------------------
# DataFrame → candle list extraction
# ---------------------------------------------------------------------------

def extract_candles(df: pd.DataFrame, symbol: str, min_points: int | None = None) -> list[dict] | None:
    """
    Extract OHLCV candles for a single symbol from the downloaded DataFrame.
    Returns None if the ticker has insufficient data.
    """
    need = min_points if min_points is not None else MIN_DATA_POINTS
    try:
        # yfinance MultiIndex: (Price, Ticker) columns when multiple tickers requested
        if isinstance(df.columns, pd.MultiIndex):
            # Check if symbol exists in the DataFrame
            if symbol not in df.columns.get_level_values(1):
                return None
            ticker_df = df.xs(symbol, axis=1, level=1).dropna(how="all")
        else:
            # Single ticker — columns are just price names
            ticker_df = df.dropna(how="all")

        if len(ticker_df) < need:
            return None

        candles = []
        for date, row in ticker_df.iterrows():
            try:
                candles.append({
                    "date":   str(date)[:10],
                    "open":   round(float(row["Open"]), 4),
                    "high":   round(float(row["High"]), 4),
                    "low":    round(float(row["Low"]), 4),
                    "close":  round(float(row["Close"]), 4),
                    "volume": int(vol) if not math.isnan(vol := float(row["Volume"])) else 0,
                })
            except (KeyError, ValueError, TypeError):
                continue

        if len(candles) < need:
            return None

        return candles
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Incremental merge
# ---------------------------------------------------------------------------

def merge_candles(existing: list[dict], new_candles: list[dict]) -> list[dict]:
    """Merge new candles into existing ones, deduplicating by date."""
    existing_dates = {c["date"] for c in existing}
    merged = list(existing)
    for candle in new_candles:
        if candle["date"] not in existing_dates:
            merged.append(candle)
            existing_dates.add(candle["date"])
    merged.sort(key=lambda c: c["date"])
    return merged


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    start_time = time.time()

    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load ticker registry ---
    if not TICKERS_FILE.exists():
        print(f"[fetch-history] ERROR: Ticker registry not found: {TICKERS_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(TICKERS_FILE, encoding="utf-8") as f:
        registry = json.load(f)

    tickers_list = registry.get("tickers", [])
    total_tickers = len(tickers_list)
    print(f"[fetch-history] Loaded {total_tickers:,} tickers from registry")

    # --- Determine fetch mode ---
    manifest = load_manifest()
    incremental = is_incremental_mode(manifest, args.full_fetch)
    period_days = INCREMENTAL_DAYS if incremental else FULL_FETCH_DAYS
    mode_label = "INCREMENTAL (last 5 days)" if incremental else "FULL (1 year)"
    print(f"[fetch-history] Mode: {mode_label}")

    # --- Group tickers by sector ---
    sector_map: dict[str, dict] = {}   # sector → {symbol: ticker_info}
    for t in tickers_list:
        sector = t.get("sector", "Other")
        if sector not in SECTOR_FILES:
            sector = "Other"
        sector_map.setdefault(sector, {})[t["symbol"]] = t

    # --- Load existing sector data for merging ---
    sector_data: dict[str, dict] = {}
    for sector in sector_map:
        if incremental:
            sector_data[sector] = load_sector_file(sector)
        else:
            sector_data[sector] = {
                "sector": sector,
                "lastUpdated": "",
                "tickerCount": 0,
                "stocks": {},
            }

    # --- Build batches ---
    all_symbols = [t["symbol"] for t in tickers_list]
    batches = [all_symbols[i:i + BATCH_SIZE] for i in range(0, len(all_symbols), BATCH_SIZE)]
    total_batches = len(batches)

    # Build a fast lookup: symbol → ticker info
    symbol_to_info: dict[str, dict] = {t["symbol"]: t for t in tickers_list}

    processed = 0
    failed_tickers: list[str] = []
    total_data_points = 0

    print(f"[fetch-history] Processing {total_batches} batches of up to {BATCH_SIZE} tickers each")

    for batch_num, batch in enumerate(batches, start=1):
        df = download_batch(batch, period_days)

        if df is None:
            print(
                f"[fetch-history] Batch {batch_num}/{total_batches} - download failed, "
                f"marking {len(batch)} tickers as failed",
                file=sys.stderr,
            )
            failed_tickers.extend(batch)
            processed += len(batch)
        else:
            for symbol in batch:
                info = symbol_to_info.get(symbol, {})
                sector = info.get("sector", "Other")
                if sector not in SECTOR_FILES:
                    sector = "Other"

                min_pts = 2 if incremental else MIN_DATA_POINTS
                candles = extract_candles(df, symbol, min_points=min_pts)
                if candles is None:
                    failed_tickers.append(symbol)
                else:
                    if incremental:
                        existing = sector_data[sector]["stocks"].get(symbol, {}).get("candles", [])
                        candles = merge_candles(existing, candles)
                        if len(candles) < MIN_DATA_POINTS:
                            failed_tickers.append(symbol)
                            processed += 1
                            continue

                    sector_data[sector]["stocks"][symbol] = {
                        "name":       info.get("name", ""),
                        "exchange":   info.get("exchange", ""),
                        "dataPoints": len(candles),
                        "dateRange": {
                            "start": candles[0]["date"] if candles else "",
                            "end":   candles[-1]["date"] if candles else "",
                        },
                        "candles": candles,
                    }
                    total_data_points += len(candles)
                processed += 1

        print(
            f"[fetch-history] Batch {batch_num}/{total_batches} complete "
            f"- {processed:,}/{total_tickers:,} tickers processed"
        )

        if batch_num < total_batches:
            time.sleep(BATCH_DELAY)

    # --- Write sector files ---
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sector_file_meta: dict[str, dict] = {}

    for sector, data in sector_data.items():
        stocks = data["stocks"]
        if not stocks:
            continue

        data["lastUpdated"] = now_utc
        data["tickerCount"] = len(stocks)

        size_bytes = save_sector_file(sector, data)
        size_mb = size_bytes / (1024 * 1024)
        key = sector_to_filename(sector)
        sector_file_meta[key] = {
            "file":    f"{key}.json",
            "tickers": len(stocks),
            "size":    f"{size_mb:.1f}MB",
        }

    # Compute overall date range from manifest or freshly fetched data
    all_starts, all_ends = [], []
    for data in sector_data.values():
        for stock in data["stocks"].values():
            dr = stock.get("dateRange", {})
            if dr.get("start"):
                all_starts.append(dr["start"])
            if dr.get("end"):
                all_ends.append(dr["end"])

    date_range = {
        "start": min(all_starts) if all_starts else "",
        "end":   max(all_ends)   if all_ends   else "",
    }

    # --- Write manifest ---
    succeeded = total_tickers - len(failed_tickers)
    new_manifest: dict = dict(manifest)  # preserve existing fields
    if incremental:
        new_manifest["lastIncrementalFetch"] = now_utc
    else:
        new_manifest["lastFullFetch"] = now_utc

    new_manifest["totalTickers"]    = succeeded
    new_manifest["totalDataPoints"] = total_data_points
    new_manifest["failedTickers"]   = failed_tickers
    new_manifest["sectorFiles"]     = sector_file_meta
    new_manifest["dateRange"]       = date_range

    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(new_manifest, f, indent=2)
        f.write("\n")

    # --- Summary ---
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("[fetch-history] OK Historical data pipeline complete")
    print(f"  Mode:            {mode_label}")
    print(f"  Total tickers:   {total_tickers:,}")
    print(f"  Succeeded:       {succeeded:,}")
    print(f"  Failed:          {len(failed_tickers):,}")
    print(f"  Total data pts:  {total_data_points:,}")
    print(f"  Elapsed:         {elapsed:.1f}s")
    print(f"  Sector files:    {len(sector_file_meta)}")
    print("=" * 60)

    # Exit non-zero if more than 50% of tickers failed (incremental: soft-fail — data often still usable)
    if (
        not incremental
        and total_tickers > 0
        and len(failed_tickers) / total_tickers > FAILURE_THRESHOLD
    ):
        print(
            f"[fetch-history] FATAL: {len(failed_tickers)}/{total_tickers} tickers failed "
            f"({100 * len(failed_tickers) / total_tickers:.1f}% > {100 * FAILURE_THRESHOLD:.0f}% threshold). "
            "Something is wrong with yfinance or Yahoo Finance.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
