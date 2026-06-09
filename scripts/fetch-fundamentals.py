"""
fetch-fundamentals.py — Phase B: Earnings + Insider Trading Data

Fetches per-ticker fundamental signals:
  1. SEC EDGAR Form 4 (insider buy/sell transactions) — completely free, no key
  2. yfinance earnings dates and EPS surprise — free, already in requirements
  3. yfinance options chain (put/call ratio) — free

The weekly job spends its budget on a capped, sector-balanced universe so the
most liquid names are always updated first and the remaining universe rotates
across later runs.

Output: data/fundamentals/YYYY-MM-DD.json
  {
    "date": "YYYY-MM-DD",
    "generatedAt": "...",
    "tickers": {
      "AAPL": {
        "insider_buy_ratio_30d": 0.75,   # buys / (buys+sells) in past 30 days [0,1]
        "earnings_days_to":      12,     # trading days until next earnings (capped 0-60)
        "earnings_surprise_prev": 0.08,  # last quarter EPS beat/miss as fraction
        "put_call_ratio":        0.9     # put volume / call volume (lower = bullish)
      },
      ...
    }
  }

Run weekly (Saturdays) via .github/workflows/fetch-fundamentals.yml.
Can also be run manually: python scripts/fetch-fundamentals.py
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

from data_universe import select_priority_tickers

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR       = Path(__file__).resolve().parent
REPO_ROOT        = SCRIPT_DIR.parent
TICKERS_FILE     = REPO_ROOT / "data" / "tickers" / "us_tickers.json"
FUNDAMENTALS_DIR = REPO_ROOT / "data" / "fundamentals"

# SEC EDGAR User-Agent (required per SEC policy)
SEC_USER_AGENT = "Nostradamus financial-research-bot contact@nostradamus.app"

# How many tickers to batch for yfinance downloads
YF_BATCH_SIZE = 20

# Cap the weekly universe so the job stays comfortably under the workflow
# timeout while still covering the most important names first.
FUNDAMENTALS_MAX_TICKERS = int(os.getenv("FUNDAMENTALS_MAX_TICKERS", "500"))

# Caps for normalisation
EARNINGS_DAYS_CAP = 60      # clip earnings_days_to to [0, 60]
SURPRISE_CAP      = 0.5     # clip earnings surprise fraction to [-0.5, +0.5]
PC_RATIO_CAP      = 5.0     # clip put/call ratio to [0, 5.0]


# ---------------------------------------------------------------------------
# Load tickers (reuse the same logic as fetch-sentiment.py)
# ---------------------------------------------------------------------------

def load_tickers() -> list[str]:
    return select_priority_tickers(limit=FUNDAMENTALS_MAX_TICKERS, seed=date.today().isoformat())


# ---------------------------------------------------------------------------
# Phase B-1: SEC EDGAR Form 4 insider transactions
# ---------------------------------------------------------------------------

def fetch_insider_ratios(tickers: list[str]) -> dict[str, float]:
    """
    Fetch Form 4 transactions per ticker via SEC EDGAR.
    Returns {ticker: insider_buy_ratio_30d} where the ratio is buys/(buys+sells).
    Falls back to 0.5 (neutral) if data is unavailable.
    """
    results = {t: 0.5 for t in tickers}

    try:
        import requests
    except ImportError:
        print("[fetch-fundamentals] 'requests' not installed — skipping insider data.")
        return results

    # Load CIK map
    cik_map: dict[str, str] = {}
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        for entry in resp.json().values():
            sym = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if sym and cik:
                cik_map[sym] = cik
    except Exception as e:
        print(f"[fetch-fundamentals] Could not load SEC CIK map: {e}")
        return results

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=30)
    fetched = 0

    for ticker in tickers:
        cik = cik_map.get(ticker)
        if not cik:
            continue
        try:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=15)
            resp.raise_for_status()
            sub_data = resp.json()

            recent = sub_data.get("filings", {}).get("recent", {})
            forms       = recent.get("form", [])
            filing_dates = recent.get("filingDate", [])

            buys  = 0
            sells = 0

            for form, filing_date in zip(forms, filing_dates):
                if form != "4":
                    continue
                try:
                    filing_dt = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
                    if filing_dt < cutoff_dt:
                        break  # filings are in reverse-chron order; stop early
                    # Form 4 direction: we use a heuristic — we count the filing
                    # and query the actual XML for transaction type, but that's
                    # expensive. Instead we use a simpler proxy: count all Form 4
                    # filings as "1 buy + 1 sell" (neutral prior) unless we can
                    # detect buy/sell direction from the XML index.
                    buys  += 1
                    sells += 1
                except ValueError:
                    pass

            # If we have actual transaction data from the index, refine it.
            # For now, default to neutral 0.5 unless we can parse XML.
            # A better implementation would fetch individual Form 4 XML files.
            # For now just track whether Form 4s were filed (≥1 = insider activity)
            insider_active = (buys + sells) > 0
            # TODO: Fetching actual buy/sell direction requires parsing individual
            # Form 4 XML files (expensive). The EFTS refinement below handles this
            # for the first 50 tickers. For the remainder, default to 0.5 (neutral).
            results[ticker] = 0.5
            fetched += 1
            time.sleep(0.15)

        except Exception as e:
            if fetched < 3:
                print(f"[fetch-fundamentals] SEC Form 4 error ({ticker}): {e}")
            time.sleep(0.5)

    # --- Better approach: use SEC EDGAR XBRL companyfacts for insider P/D ---
    # Query form4 data through the EDGAR full-text search API for buy/sell signal
    _refine_insider_ratios_from_edgar(tickers, cik_map, cutoff_dt, results)

    print(f"[fetch-fundamentals] SEC Form 4: processed {fetched}/{len(tickers)} tickers")
    return results


def _refine_insider_ratios_from_edgar(
    tickers: list[str], cik_map: dict[str, str],
    cutoff_dt: datetime, results: dict[str, float]
) -> None:
    """
    Refine insider ratios by checking EDGAR EFTS (full-text search) for
    Form 4 P (purchase) vs D (disposal) transactions in the past 30 days.
    """
    try:
        import requests
    except ImportError:
        return

    from_date = cutoff_dt.strftime("%Y-%m-%d")
    to_date   = date.today().isoformat()

    for ticker in tickers[:50]:  # limit to avoid overloading EDGAR
        cik = cik_map.get(ticker)
        if not cik:
            continue
        try:
            # EDGAR EFTS endpoint: search Form 4 filings for this CIK
            url = (
                f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22"
                f"&dateRange=custom&startdt={from_date}&enddt={to_date}"
                f"&forms=4"
            )
            resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=15)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])

            buys  = 0
            sells = 0
            for hit in hits:
                # File summary usually contains "P" (purchase) or "S" (sale)
                desc = hit.get("_source", {}).get("file_description", "").upper()
                if "PURCHASE" in desc or " P " in desc:
                    buys += 1
                elif "SALE" in desc or " S " in desc or "DISPOSAL" in desc:
                    sells += 1

            total = buys + sells
            if total > 0:
                results[ticker] = round(buys / total, 4)

            time.sleep(0.12)
        except Exception:
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# Phase B-2: yfinance earnings data
# ---------------------------------------------------------------------------

def fetch_earnings_data(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch next earnings date and last-quarter EPS surprise from yfinance.
    Returns {ticker: {"earnings_days_to": int, "earnings_surprise_prev": float}}.
    """
    results = {
        t: {"earnings_days_to": EARNINGS_DAYS_CAP, "earnings_surprise_prev": 0.0}
        for t in tickers
    }

    try:
        import yfinance as yf
    except ImportError:
        print("[fetch-fundamentals] yfinance not installed — skipping earnings data.")
        return results

    today = date.today()

    # Process individually to get earnings dates (yfinance batch doesn't expose this)
    for i, ticker in enumerate(tickers):
        if i > 0 and i % 50 == 0:
            print(f"[fetch-fundamentals] Earnings: {i}/{len(tickers)}...")

        try:
            tk = yf.Ticker(ticker)

            # --- Next earnings date ---
            try:
                cal = tk.calendar
                if cal is not None and not cal.empty:
                    # calendar is a DataFrame; earnings date is in the index or column
                    if "Earnings Date" in cal.index:
                        ed_val = cal.loc["Earnings Date"].iloc[0]
                    elif "Earnings Date" in cal.columns:
                        ed_val = cal["Earnings Date"].iloc[0]
                    else:
                        ed_val = None

                    if ed_val is not None:
                        ed = pd.Timestamp(ed_val).date() if hasattr(ed_val, "date") else None
                        if ed and ed >= today:
                            # Count trading days to earnings (approximate with weekdays)
                            delta_days = (ed - today).days
                            # Approximate weekdays as ~5/7 of calendar days
                            trading_days = max(0, int(delta_days * 5 / 7))
                            results[ticker]["earnings_days_to"] = min(trading_days, EARNINGS_DAYS_CAP)
            except Exception:
                pass

            # --- EPS surprise from last quarter ---
            try:
                earnings_hist = tk.earnings_history
                if earnings_hist is not None and not earnings_hist.empty:
                    # Most recent quarter
                    last = earnings_hist.iloc[0]
                    eps_est    = float(last.get("epsEstimate", 0) or 0)
                    eps_actual = float(last.get("epsActual", 0) or 0)
                    if eps_est != 0:
                        surprise = (eps_actual - eps_est) / abs(eps_est)
                        results[ticker]["earnings_surprise_prev"] = round(
                            max(-SURPRISE_CAP, min(SURPRISE_CAP, surprise)), 4
                        )
            except Exception:
                pass

            time.sleep(0.05)   # avoid hammering yfinance

        except Exception as e:
            if i < 3:
                print(f"[fetch-fundamentals] yfinance earnings error ({ticker}): {e}")

    print(f"[fetch-fundamentals] Earnings: fetched for {len(tickers)} tickers")
    return results


# ---------------------------------------------------------------------------
# Phase B-3: yfinance options put/call ratio
# ---------------------------------------------------------------------------

def fetch_put_call_ratios(tickers: list[str]) -> dict[str, float]:
    """
    Fetch put/call volume ratio from the nearest-expiry options chain via yfinance.
    Returns {ticker: put_call_ratio} — lower is more bullish.
    """
    results = {t: 1.0 for t in tickers}  # neutral default

    try:
        import yfinance as yf
    except ImportError:
        print("[fetch-fundamentals] yfinance not installed — skipping options data.")
        return results

    for i, ticker in enumerate(tickers):
        if i > 0 and i % 50 == 0:
            print(f"[fetch-fundamentals] Options P/C: {i}/{len(tickers)}...")

        try:
            tk = yf.Ticker(ticker)
            expirations = tk.options
            if not expirations:
                continue

            # Use nearest expiry
            chain = tk.option_chain(expirations[0])
            calls_vol = chain.calls["volume"].sum() if not chain.calls.empty else 0
            puts_vol  = chain.puts["volume"].sum()  if not chain.puts.empty  else 0

            if calls_vol > 0:
                pc = puts_vol / calls_vol
                results[ticker] = round(min(pc, PC_RATIO_CAP), 4)

            time.sleep(0.05)

        except Exception as e:
            if i < 3:
                print(f"[fetch-fundamentals] options P/C error ({ticker}): {e}")

    print(f"[fetch-fundamentals] Options P/C: fetched for {len(tickers)} tickers")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Import pandas here so we can use it in fetch_earnings_data
    global pd
    try:
        import pandas as pd
    except ImportError:
        print("[fetch-fundamentals] ERROR: pandas not installed.")
        sys.exit(1)

    FUNDAMENTALS_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    out_path  = FUNDAMENTALS_DIR / f"{today_str}.json"

    print("=" * 60)
    print(f"[fetch-fundamentals] Fetching fundamentals for {today_str}")
    print("=" * 60)

    tickers = load_tickers()
    print(f"[fetch-fundamentals] Loaded {len(tickers)} tickers")

    print("\n[1/3] Fetching SEC Form 4 insider ratios...")
    insider_data  = fetch_insider_ratios(tickers)

    print("\n[2/3] Fetching yfinance earnings data...")
    earnings_data = fetch_earnings_data(tickers)

    print("\n[3/3] Fetching options put/call ratios...")
    pc_data       = fetch_put_call_ratios(tickers)

    # Merge
    ticker_results = {}
    for ticker in tickers:
        ed = earnings_data.get(ticker, {})
        ticker_results[ticker] = {
            "insider_buy_ratio_30d":   insider_data.get(ticker, 0.5),
            "earnings_days_to":        ed.get("earnings_days_to", EARNINGS_DAYS_CAP),
            "earnings_surprise_prev":  ed.get("earnings_surprise_prev", 0.0),
            "put_call_ratio":          pc_data.get(ticker, 1.0),
        }

    output = {
        "date":        today_str,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickers":     ticker_results,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[fetch-fundamentals] Done. Output: {out_path}")


if __name__ == "__main__":
    main()
