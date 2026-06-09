"""
import-stooq-bulk-zip.py

One-shot importer for the Stooq ASCII regional ZIP dump (e.g. d_us_txt.zip).

Stooq's per-symbol CSV endpoint AND the bulk download URL are both
captcha-gated, so this script does NOT try to download the ZIP. Instead, you
download it once through a browser (one captcha solve) and point this script
at the local file. From there we get years of delisted-safe daily OHLCV with
zero ongoing rate-limit drama.

How to use:
  1. Open https://stooq.com/db/h/?b=d_us_txt in a browser.
  2. Click the "us" / d_us_txt link, solve the captcha, save d_us_txt.zip.
  3. Run:
       python scripts/import-stooq-bulk-zip.py --zip "C:/path/to/d_us_txt.zip"
     Optional filters:
       --years 10              keep only the last N years of candles
       --tickers AAPL MSFT     restrict to a subset
       --limit 2000            cap the number of symbols processed
       --min-candles 200       reject symbols with fewer rows

Output:
  data/historical/<sector>.json   (merged into existing sector files)
  data/historical/stooq-bulk-coverage.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_DIR = REPO_ROOT / "data" / "historical"
TICKERS_FILE = REPO_ROOT / "data" / "tickers" / "us_tickers.json"
COVERAGE_FILE = HISTORICAL_DIR / "stooq-bulk-coverage.json"

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
        by_date.setdefault(d, c)
    merged = list(by_date.values())
    merged.sort(key=lambda c: c["date"])
    return merged


def load_ticker_sectors() -> dict[str, str]:
    if not TICKERS_FILE.exists():
        return {}
    try:
        data = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    tickers = data.get("tickers") if isinstance(data, dict) else data
    if not isinstance(tickers, list):
        return {}
    out: dict[str, str] = {}
    for row in tickers:
        sym = str(row.get("symbol") or row.get("ticker") or "").upper()
        sec = str(row.get("sector") or "Other") or "Other"
        if sym:
            out[sym] = sec
    return out


def parse_stooq_csv(text: str, cutoff: date | None) -> list[dict]:
    """Parse a single Stooq per-symbol .txt file into our candle schema."""
    candles: list[dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        d = (row.get("<DATE>") or row.get("Date") or "").strip()
        if not d or len(d) < 8:
            continue
        # Stooq uses YYYYMMDD with no separators
        if d.isdigit() and len(d) == 8:
            iso = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        else:
            iso = d[:10]
        try:
            row_date = datetime.strptime(iso, "%Y-%m-%d").date()
        except Exception:
            continue
        if cutoff is not None and row_date < cutoff:
            continue
        try:
            candles.append(
                {
                    "date": iso,
                    "open": round(float(row.get("<OPEN>") or row.get("Open") or 0), 4),
                    "high": round(float(row.get("<HIGH>") or row.get("High") or 0), 4),
                    "low": round(float(row.get("<LOW>") or row.get("Low") or 0), 4),
                    "close": round(float(row.get("<CLOSE>") or row.get("Close") or 0), 4),
                    "volume": int(float(row.get("<VOL>") or row.get("Volume") or 0)),
                }
            )
        except Exception:
            continue
    return candles


def symbol_from_name(name: str) -> str:
    # e.g. "data/daily/us/nasdaq stocks/1/aapl.us.txt" → "AAPL"
    base = Path(name).name.lower()
    if base.endswith(".us.txt"):
        return base[:-7].upper()
    if base.endswith(".txt"):
        return base[:-4].upper()
    return base.upper()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Import a Stooq bulk ZIP dump.")
    ap.add_argument("--zip", required=True, help="Path to the manually-downloaded Stooq ZIP")
    ap.add_argument("--years", type=int, default=10, help="Keep only the last N years of candles")
    ap.add_argument("--tickers", nargs="*", default=None, help="Restrict to a subset of tickers")
    ap.add_argument("--limit", type=int, default=0, help="Cap on number of symbols to import (0=all)")
    ap.add_argument(
        "--min-candles",
        type=int,
        default=200,
        help="Drop symbols with fewer than N candles after the cutoff",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    zip_path = Path(args.zip).expanduser().resolve()
    if not zip_path.exists():
        raise SystemExit(f"[stooq-bulk] ZIP not found: {zip_path}")

    cutoff = None
    if args.years and args.years > 0:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=int(args.years * 365.25))

    ticker_sectors = load_ticker_sectors()
    allow: set[str] | None = None
    if args.tickers:
        allow = {t.upper() for t in args.tickers}

    print(
        f"[stooq-bulk] zip={zip_path.name} years={args.years} cutoff={cutoff} "
        f"allow={'(custom)' if allow else 'all'} limit={args.limit}"
    )

    sector_payloads: dict[str, dict] = {}
    coverage = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": str(zip_path),
        "yearsRequested": args.years,
        "cutoffDate": str(cutoff) if cutoff else None,
        "tickers": {},
        "rejected": {"too_few_candles": 0, "parse_error": 0, "filtered_out": 0},
    }

    processed = 0
    accepted = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".us.txt") or m.lower().endswith(".txt")]
        print(f"[stooq-bulk] scanning {len(members):,} files in archive")

        for name in members:
            symbol = symbol_from_name(name)
            if not symbol:
                continue
            if allow is not None and symbol not in allow:
                coverage["rejected"]["filtered_out"] += 1
                continue

            processed += 1
            try:
                with zf.open(name) as fp:
                    text = fp.read().decode("utf-8", errors="replace")
            except Exception:
                coverage["rejected"]["parse_error"] += 1
                continue

            candles = parse_stooq_csv(text, cutoff)
            if len(candles) < args.min_candles:
                coverage["rejected"]["too_few_candles"] += 1
                continue

            sector = ticker_sectors.get(symbol, "Other")
            if sector not in sector_payloads:
                sector_payloads[sector] = load_sector_file(sector)
            stocks = sector_payloads[sector].setdefault("stocks", {})
            existing = stocks.get(symbol, {}).get("candles") or []
            stocks[symbol] = {"candles": merge_candles(existing, candles)}

            accepted += 1
            coverage["tickers"][symbol] = {
                "sector": sector,
                "rows": len(candles),
                "firstDate": candles[0]["date"],
                "lastDate": candles[-1]["date"],
                "source": "stooq-bulk",
            }

            if accepted % 500 == 0:
                print(
                    f"[stooq-bulk] progress accepted={accepted} processed={processed} "
                    f"sectors={len(sector_payloads)}"
                )

            if args.limit and accepted >= args.limit:
                print(f"[stooq-bulk] hit --limit {args.limit}, stopping")
                break

    for sector, payload in sector_payloads.items():
        payload["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["tickerCount"] = len(payload.get("stocks") or {})
        size = save_sector_file(sector, payload)
        print(f"[stooq-bulk] wrote sector={sector} bytes={size}")

    COVERAGE_FILE.write_text(f"{json.dumps(coverage, indent=2)}\n", encoding="utf-8")
    print(
        f"[stooq-bulk] complete accepted={accepted} processed={processed} "
        f"rejected={coverage['rejected']} coverage={COVERAGE_FILE}"
    )


if __name__ == "__main__":
    main()
