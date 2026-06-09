"""
scripts/fetch-tickers.py
Downloads the SEC EDGAR company tickers exchange file, filters to NYSE/NASDAQ/AMEX,
maps SIC codes to GICS-like sectors, and outputs data/tickers/us_tickers.json.

Usage:
    python scripts/fetch-tickers.py

Output:
    data/tickers/us_tickers.json
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
USER_AGENT = "Nostradamus/2.0 bot@nostradamus.app"

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tickers")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "us_tickers.json")

ALLOWED_EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


# ---------------------------------------------------------------------------
# SIC → Sector mapping
# ---------------------------------------------------------------------------

def sic_to_sector(sic: int | None) -> str:
    """Map an SEC SIC code to a GICS-like sector string."""
    if sic is None:
        return "Other"

    # Government — exclude (handled by caller)
    if 9000 <= sic <= 9999:
        return "Government"

    # Agriculture → Materials
    if 100 <= sic <= 999:
        return "Materials"

    # Mining → Materials
    if 1000 <= sic <= 1499:
        return "Materials"

    # Construction → Industrials
    if 1500 <= sic <= 1799:
        return "Industrials"

    # Manufacturing (2000-3999) — split by sub-range
    if 2000 <= sic <= 3999:
        # Healthcare (pharma/medical)
        if (2830 <= sic <= 2836) or (3841 <= sic <= 3851):
            return "Healthcare"
        # Technology (computers, electronics, instruments)
        if (3570 <= sic <= 3579) or (3660 <= sic <= 3679) or (3812 <= sic <= 3825):
            return "Technology"
        # Consumer Staples (food & tobacco)
        if 2000 <= sic <= 2111:
            return "Consumer Staples"
        # Consumer Discretionary (apparel, autos, appliances, instruments misc.)
        if (2200 <= sic <= 2599) or (3000 <= sic <= 3199) or (3600 <= sic <= 3699) or \
           (3700 <= sic <= 3799) or (3800 <= sic <= 3999):
            return "Consumer Discretionary"
        # Remaining manufacturing → Industrials
        return "Industrials"

    # Transportation & Utilities (4000-4999)
    if 4000 <= sic <= 4999:
        if 4900 <= sic <= 4999:
            return "Utilities"
        if 4800 <= sic <= 4899:
            return "Communication Services"
        return "Industrials"

    # Wholesale Trade → Industrials
    if 5000 <= sic <= 5199:
        return "Industrials"

    # Retail Trade → Consumer Discretionary
    if 5200 <= sic <= 5999:
        return "Consumer Discretionary"

    # Finance / Insurance / Real Estate
    if 6000 <= sic <= 6799:
        if 6500 <= sic <= 6799:
            return "Real Estate"
        return "Financials"

    # Services (7000-8999)
    if 7000 <= sic <= 8999:
        # Technology (data processing / software)
        if 7370 <= sic <= 7379:
            return "Technology"
        # Healthcare (medical services)
        if 8000 <= sic <= 8099:
            return "Healthcare"
        # Communication Services (motion pictures / broadcast)
        if (7810 <= sic <= 7819) or (7820 <= sic <= 7829) or (7830 <= sic <= 7841):
            return "Communication Services"
        # Remaining services → Consumer Discretionary
        return "Consumer Discretionary"

    return "Other"


# ---------------------------------------------------------------------------
# Symbol validation
# ---------------------------------------------------------------------------

_DIGITS_ONLY = re.compile(r"^\d+$")
# Warrant suffixes: W, WS, WI, WT — allow symbols up to 6 chars if they end with W/WS/WI/WT
_WARRANT_SUFFIX = re.compile(r"[WwIiTtSs]+$")


def is_valid_symbol(symbol: str) -> bool:
    """Return True if the ticker symbol looks like a real, tradeable security."""
    if not symbol:
        return False
    sym = symbol.strip().upper()
    # Must be 1-6 characters
    if len(sym) < 1 or len(sym) > 6:
        return False
    # Digits-only symbols are test artifacts
    if _DIGITS_ONLY.match(sym):
        return False
    # Symbols > 5 chars must look like warrants (e.g. AAPLWS, XYZWT)
    if len(sym) > 5 and not _WARRANT_SUFFIX.search(sym[-2:]):
        return False
    # Must contain at least one letter
    if not re.search(r"[A-Za-z]", sym):
        return False
    return True


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_with_retry(url: str, headers: dict, max_retries: int = MAX_RETRIES) -> dict:
    """GET a JSON URL with retry logic. Returns parsed JSON."""
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[fetch] Attempt {attempt}/{max_retries}: {url}")
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            print(f"[fetch] HTTP error {e.response.status_code}: {e}", file=sys.stderr)
            last_err = e
        except requests.exceptions.RequestException as e:
            print(f"[fetch] Request error: {e}", file=sys.stderr)
            last_err = e
        if attempt < max_retries:
            print(f"[fetch] Retrying in {RETRY_DELAY}s…")
            time.sleep(RETRY_DELAY)
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts") from last_err


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    print(f"[Phase 2] Fetching SEC EDGAR tickers from: {SEC_URL}")
    raw = fetch_with_retry(SEC_URL, headers)

    # SEC EDGAR format: {"fields": [...], "data": [[...], ...]}
    fields = raw.get("fields", [])
    data_rows = raw.get("data", [])

    print(f"[Phase 2] Raw rows: {len(data_rows)}, Fields: {fields}")

    # Build field index lookup
    idx = {name: i for i, name in enumerate(fields)}

    if "sic" not in idx:
        print("[Phase 2] WARNING: 'sic' field not present in SEC EDGAR response — all tickers will be classified as 'Other'", file=sys.stderr)

    tickers = []
    skipped_exchange = 0
    skipped_symbol = 0
    skipped_government = 0

    for row in data_rows:
        try:
            cik_raw   = row[idx["cik"]]
            name_raw  = row[idx["name"]]
            ticker    = row[idx["ticker"]]
            exchange  = row[idx["exchange"]]
            # SIC may or may not be present in this endpoint
            sic_raw   = row[idx["sic"]] if "sic" in idx else None
        except (IndexError, KeyError):
            continue

        exchange = (exchange or "").strip().upper()
        if exchange not in ALLOWED_EXCHANGES:
            skipped_exchange += 1
            continue

        symbol = (ticker or "").strip().upper()
        if not is_valid_symbol(symbol):
            skipped_symbol += 1
            continue

        sic = int(sic_raw) if sic_raw is not None else None
        sector = sic_to_sector(sic)

        # Exclude government entities
        if sector == "Government":
            skipped_government += 1
            continue

        # Zero-pad CIK to 10 digits
        cik_str = str(cik_raw).zfill(10)

        tickers.append({
            "symbol":   symbol,
            "name":     str(name_raw).strip(),
            "cik":      cik_str,
            "exchange": exchange,
            "sector":   sector,
            "sicCode":  sic,
        })

    # Sort alphabetically by symbol (deterministic output)
    tickers.sort(key=lambda t: t["symbol"])

    # Deduplicate (keep first occurrence after sort — same symbol same exchange)
    seen = set()
    unique_tickers = []
    for t in tickers:
        key = (t["symbol"], t["exchange"])
        if key not in seen:
            seen.add(key)
            unique_tickers.append(t)

    # Build summary counts
    exchange_counts: dict[str, int] = {}
    sector_counts: dict[str, int] = {}
    for t in unique_tickers:
        exchange_counts[t["exchange"]] = exchange_counts.get(t["exchange"], 0) + 1
        sector_counts[t["sector"]] = sector_counts.get(t["sector"], 0) + 1

    output = {
        "metadata": {
            "source":       "SEC EDGAR",
            "url":          SEC_URL,
            "fetchedAt":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "totalTickers": len(unique_tickers),
            "exchanges":    exchange_counts,
            "sectors":      sector_counts,
        },
        "tickers": unique_tickers,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # --- Summary ---
    print("\n" + "=" * 60)
    print(f"[Phase 2] OK Ticker registry written to: {OUTPUT_FILE}")
    print(f"  Total tickers:      {len(unique_tickers):,}")
    print(f"  Skipped (exchange): {skipped_exchange:,}")
    print(f"  Skipped (symbol):   {skipped_symbol:,}")
    print(f"  Skipped (govt):     {skipped_government:,}")
    print("\n  By Exchange:")
    for exch, count in sorted(exchange_counts.items()):
        print(f"    {exch:<8} {count:,}")
    print("\n  By Sector:")
    for sect, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        print(f"    {sect:<30} {count:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
