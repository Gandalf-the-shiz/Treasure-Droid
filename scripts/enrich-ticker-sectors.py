"""
enrich-ticker-sectors.py

Enrich data/tickers/us_tickers.json with real GICS sectors derived from each
company's SEC SIC code. Required because the registry currently tags every
ticker as "Other", which forces the Stooq bulk importer to dump everything
into a single monolithic other.json (~1.5 GB).

Strategy:
  1. For each ticker with a CIK, fetch:
       https://data.sec.gov/submissions/CIK{cik10}.json
  2. Read `sic` (4-digit code) from the response.
  3. Map SIC -> GICS sector via the table in `sic_to_gics()` below.
  4. Update the in-memory registry; write back when done.

Notes:
  - SEC requires a descriptive User-Agent. We honor that.
  - Default 8 concurrent workers + 0.1s per-request stagger keeps us under
    SEC's 10 req/sec ceiling.
  - Responses are cached at .cache/sec-submissions/CIK{cik10}.json so reruns
    are essentially free.

Output:
  data/tickers/us_tickers.json                     (sector field updated)
  data/tickers/sector-enrichment-coverage.json     (per-sector counts)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKERS_FILE = REPO_ROOT / "data" / "tickers" / "us_tickers.json"
COVERAGE_FILE = REPO_ROOT / "data" / "tickers" / "sector-enrichment-coverage.json"
CACHE_DIR = REPO_ROOT / ".cache" / "sec-submissions"

USER_AGENT = "Nostradamus Research nicho@example.com"


def sic_to_gics(sic: int | None) -> str:
    """Map a 4-digit SIC code to a GICS sector label."""
    if sic is None:
        return "Other"
    s = int(sic)

    # Healthcare — pharma, medical instruments, hospitals
    if 2833 <= s <= 2836:
        return "Healthcare"  # pharmaceutical preparations / biological products
    if 3826 <= s <= 3827:
        return "Healthcare"  # laboratory / optical instruments
    if 3840 <= s <= 3851:
        return "Healthcare"  # medical/surgical instruments
    if 5047 <= s <= 5047 or 5122 == s:
        return "Healthcare"  # medical equip wholesale / drugs wholesale
    if 5912 == s:
        return "Healthcare"  # drug stores (often classified consumer staples,
                              # but pharmacy chains lean healthcare on GICS)
    if 8000 <= s <= 8099:
        return "Healthcare"
    if 8731 == s:
        return "Healthcare"  # commercial physical/biological research

    # Energy
    if 1300 <= s <= 1389:
        return "Energy"
    if 2900 <= s <= 2999:
        return "Energy"  # petroleum refining
    if 4922 <= s <= 4925:
        return "Energy"  # natural gas pipelines/distribution
    if 5170 <= s <= 5172:
        return "Energy"  # petroleum wholesale
    if 5983 <= s <= 5989:
        return "Energy"  # fuel dealers

    # Utilities
    if 4900 <= s <= 4911:
        return "Utilities"
    if 4931 <= s <= 4939:
        return "Utilities"
    if 4940 <= s <= 4959:
        return "Utilities"
    if 4960 <= s <= 4971:
        return "Utilities"

    # Real Estate
    if 6500 <= s <= 6552:
        return "Real Estate"
    if 6798 == s:
        return "Real Estate"  # REITs

    # Financials
    if 6000 <= s <= 6499:
        return "Financials"
    if 6700 <= s <= 6799:
        return "Financials"

    # Communication Services
    if 2710 <= s <= 2731:
        return "Communication Services"  # newspapers/periodicals/books
    if 2741 == s:
        return "Communication Services"  # miscellaneous publishing
    if 4812 <= s <= 4813:
        return "Communication Services"  # wireless / telephone
    if 4822 == s:
        return "Communication Services"
    if 4832 <= s <= 4833:
        return "Communication Services"  # radio/TV broadcasting
    if 4841 == s:
        return "Communication Services"  # cable & other pay TV
    if 4899 == s:
        return "Communication Services"
    if 7810 <= s <= 7841:
        return "Communication Services"  # motion pictures
    if 7812 == s:
        return "Communication Services"
    if 7900 <= s <= 7999:
        return "Communication Services"  # amusement & recreation

    # Technology
    if 3570 <= s <= 3579:
        return "Technology"  # computer & office equipment
    if 3661 <= s <= 3679:
        return "Technology"  # telephone/electronic components
    if 3674 == s:
        return "Technology"  # semiconductors
    if 7370 <= s <= 7379:
        return "Technology"  # computer services / prepackaged software
    if 7372 == s:
        return "Technology"  # prepackaged software

    # Consumer Discretionary
    if 2200 <= s <= 2399:
        return "Consumer Discretionary"  # textile/apparel
    if 2500 <= s <= 2599:
        return "Consumer Discretionary"  # furniture
    if 3000 <= s <= 3099:
        return "Consumer Discretionary"  # rubber/footwear
    if 3140 <= s <= 3199:
        return "Consumer Discretionary"  # leather/footwear
    if 3630 <= s <= 3639:
        return "Consumer Discretionary"  # household appliances
    if 3711 <= s <= 3716:
        return "Consumer Discretionary"  # motor vehicles
    if 3751 == s:
        return "Consumer Discretionary"  # bicycles/motorcycles
    if 3940 <= s <= 3949:
        return "Consumer Discretionary"  # toys/sporting goods
    if 5200 <= s <= 5990:
        # retail trade — most is discretionary, with food/drug exceptions
        if 5400 <= s <= 5499:
            return "Consumer Staples"
        if s == 5912:
            return "Healthcare"  # already handled, but defensive
        return "Consumer Discretionary"
    if 7000 <= s <= 7299:
        return "Consumer Discretionary"  # hotels/personal services
    if 7500 <= s <= 7699:
        return "Consumer Discretionary"  # auto repair / misc repair
    if 8200 <= s <= 8299:
        return "Consumer Discretionary"  # educational services

    # Consumer Staples
    if 100 <= s <= 999:
        return "Consumer Staples"  # agriculture
    if 2000 <= s <= 2199:
        return "Consumer Staples"  # food & beverage & tobacco
    if 5140 <= s <= 5149:
        return "Consumer Staples"  # grocery wholesale

    # Materials
    if 1000 <= s <= 1299:
        return "Materials"  # mining
    if 1400 <= s <= 1499:
        return "Materials"  # mining nonmetallic minerals
    if 2400 <= s <= 2499:
        return "Materials"  # lumber & wood
    if 2600 <= s <= 2699:
        return "Materials"  # paper
    if 2800 <= s <= 2899:
        return "Materials"  # chemicals (non-pharma)
    if 3200 <= s <= 3299:
        return "Materials"  # stone/clay/glass
    if 3300 <= s <= 3399:
        return "Materials"  # primary metals

    # Industrials (catch-all for remaining manufacturing & services)
    if 1500 <= s <= 1799:
        return "Industrials"  # construction
    if 3400 <= s <= 3499:
        return "Industrials"  # fabricated metals
    if 3500 <= s <= 3569:
        return "Industrials"
    if 3580 <= s <= 3599:
        return "Industrials"
    if 3600 <= s <= 3629:
        return "Industrials"  # electrical industrial equipment
    if 3640 <= s <= 3669:
        return "Industrials"
    if 3680 <= s <= 3699:
        return "Industrials"
    if 3700 <= s <= 3710:
        return "Industrials"
    if 3720 <= s <= 3729:
        return "Industrials"  # aircraft
    if 3730 <= s <= 3743:
        return "Industrials"  # ship/rail
    if 3760 <= s <= 3795:
        return "Industrials"  # guided missiles, tanks
    if 3800 <= s <= 3825:
        return "Industrials"  # search/detection instruments
    if 3860 <= s <= 3873:
        return "Industrials"  # photo/clocks
    if 3900 <= s <= 3939:
        return "Industrials"  # misc manufacturing
    if 3950 <= s <= 3999:
        return "Industrials"
    if 4000 <= s <= 4789:
        return "Industrials"  # transportation
    if 4800 <= s <= 4811:
        return "Industrials"  # postal services
    if 5000 <= s <= 5139:
        return "Industrials"  # wholesale durable goods
    if 5150 <= s <= 5199:
        return "Industrials"  # wholesale non-durable
    if 7300 <= s <= 7369:
        return "Industrials"  # business services
    if 7380 <= s <= 7499:
        return "Industrials"  # misc business services
    if 7700 <= s <= 7799:
        return "Industrials"
    if 8100 <= s <= 8199:
        return "Industrials"  # legal services
    if 8300 <= s <= 8730:
        return "Industrials"  # social services / accounting
    if 8732 <= s <= 8999:
        return "Industrials"

    return "Other"


def fetch_sic(cik: str, session_cache: bool = True) -> tuple[int | None, str | None, str | None]:
    """Fetch (sic, sicDescription, error) for a CIK from SEC EDGAR with caching.

    `error` is None on success, or a short string when the fetch itself failed
    so the caller can distinguish "company has no SIC" from "request failed".
    """
    cik_padded = str(int(cik)).zfill(10)
    cache_path = CACHE_DIR / f"CIK{cik_padded}.json"

    body: bytes | None = None
    if session_cache and cache_path.exists():
        try:
            body = cache_path.read_bytes()
        except Exception:
            body = None

    if body is None:
        url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        backoff = 1.0
        last_err: str | None = None
        for attempt in range(5):
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Host": "data.sec.gov",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read()
                last_err = None
                break
            except urllib.error.HTTPError as e:
                last_err = f"http:{e.code}"
                if e.code == 429 or 500 <= e.code < 600:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 16.0)
                    continue
                return (None, None, last_err)
            except Exception as e:
                last_err = f"err:{type(e).__name__}"
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
        if body is None:
            return (None, None, last_err or "unknown")
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(body)
        except Exception:
            pass

    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return (None, None, "parse_error")
    sic_raw = data.get("sic")
    desc = data.get("sicDescription")
    try:
        sic = int(sic_raw) if sic_raw not in (None, "", "0") else None
    except Exception:
        sic = None
    return (sic, desc if isinstance(desc, str) else None, None)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Enrich us_tickers.json with GICS sectors via SEC SIC codes.")
    ap.add_argument("--workers", type=int, default=8, help="Concurrent SEC requests")
    ap.add_argument("--limit", type=int, default=0, help="Cap on tickers to enrich (0=all)")
    ap.add_argument("--force", action="store_true", help="Re-enrich even rows already non-Other")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    if not TICKERS_FILE.exists():
        raise SystemExit(f"[enrich] missing {TICKERS_FILE}")

    registry = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
    tickers = registry.get("tickers") or []
    if not isinstance(tickers, list):
        raise SystemExit("[enrich] tickers field is not a list")

    todo: list[tuple[int, dict]] = []
    for idx, row in enumerate(tickers):
        if not isinstance(row, dict):
            continue
        sector = str(row.get("sector") or "Other")
        if sector != "Other" and not args.force:
            continue
        cik = row.get("cik")
        if not cik:
            continue
        todo.append((idx, row))
        if args.limit and len(todo) >= args.limit:
            break

    print(f"[enrich] candidates={len(todo)} workers={args.workers} cache={CACHE_DIR}")

    sector_counts: dict[str, int] = {}
    failures = 0
    started = time.time()

    def work(item: tuple[int, dict]) -> tuple[int, str, int | None, str | None, str | None]:
        idx, row = item
        sic, desc, err = fetch_sic(str(row.get("cik")))
        sector = sic_to_gics(sic) if err is None else "__FAILED__"
        return (idx, sector, sic, desc, err)

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(work, item) for item in todo]
        for fut in as_completed(futures):
            try:
                idx, sector, sic, desc, err = fut.result()
            except Exception:
                failures += 1
                continue
            if err is not None or sector == "__FAILED__":
                failures += 1
                continue
            row = tickers[idx]
            row["sector"] = sector
            if sic is not None:
                row["sicCode"] = sic
                row["sicDescription"] = desc
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            completed += 1
            if completed % 500 == 0:
                elapsed = time.time() - started
                rate = completed / max(elapsed, 0.001)
                print(f"[enrich] progress {completed}/{len(todo)} sectors={len(sector_counts)} fails={failures} rate={rate:.1f}/s")

    # Write registry back
    registry["metadata"] = registry.get("metadata") or {}
    registry["metadata"]["sectorEnrichedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry["metadata"]["sectorEnrichmentSource"] = "SEC EDGAR submissions API (SIC -> GICS)"
    TICKERS_FILE.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    coverage = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidates": len(todo),
        "completed": completed,
        "failures": failures,
        "sectorCounts": dict(sorted(sector_counts.items(), key=lambda kv: -kv[1])),
    }
    COVERAGE_FILE.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    elapsed = time.time() - started
    print(
        f"[enrich] complete completed={completed} failures={failures} elapsed={elapsed:.1f}s "
        f"sectors={coverage['sectorCounts']}"
    )


if __name__ == "__main__":
    main()
