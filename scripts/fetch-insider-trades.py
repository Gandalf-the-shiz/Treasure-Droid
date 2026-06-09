"""Fetch SEC Form 4 insider trades for priority tickers.

Parses non-derivative transaction codes (P/S) from recent Form 4 XML filings.
Respects SEC rate limits (0.12s between requests).

Usage:
  python scripts/fetch-insider-trades.py
  python scripts/fetch-insider-trades.py --limit 150
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from data_universe import select_priority_tickers  # noqa: E402
from insider_signals import write_artifacts  # noqa: E402

SEC_UA = os.getenv("SEC_USER_AGENT", "Nostradamus-Research contact@nostradamus.app")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"})

CODE_BUY = {"P", "A"}
CODE_SELL = {"S", "D"}


def _cik_map() -> dict[str, str]:
    r = SESSION.get("https://www.sec.gov/files/company_tickers.json", timeout=30)
    r.raise_for_status()
    out: dict[str, str] = {}
    for entry in r.json().values():
        sym = str(entry.get("ticker", "")).upper()
        cik = str(entry.get("cik_str", "")).zfill(10)
        if sym:
            out[sym] = cik
    return out


def _parse_form4_xml(xml_text: str, symbol: str, filing_date: str) -> list[dict]:
    trades: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return trades
    # Strip namespaces
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]

    for txn in root.iter("nonDerivativeTransaction"):
        code_el = txn.find(".//transactionCode")
        code = (code_el.text or "").strip().upper() if code_el is not None else ""
        ad_el = txn.find(".//transactionAcquiredDisposedCode")
        ad = (ad_el.text or "").strip().upper() if ad_el is not None else ""
        if code in CODE_BUY or ad == "A":
            side = "buy"
        elif code in CODE_SELL or ad == "D":
            side = "sell"
        else:
            continue
        td_el = txn.find(".//transactionDate/value")
        td = (td_el.text or filing_date)[:10] if td_el is not None else filing_date
        who_el = txn.find(".//reportingOwner//rptOwnerName")
        who = (who_el.text or "").strip() if who_el is not None else ""
        trades.append({
            "symbol": symbol,
            "insider": who,
            "side": side,
            "transaction_date": td,
            "filing_date": filing_date,
            "transaction_code": code,
            "source": "sec_form4_xml",
        })
    return trades


def fetch_ticker_form4(symbol: str, cik: str, lookback_days: int) -> list[dict]:
    cik_int = str(int(cik))
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        r = SESSION.get(url, timeout=20)
        r.raise_for_status()
        sub = r.json()
    except Exception:
        return []

    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    out: list[dict] = []
    for form, fdate, acc in zip(forms, dates, accessions):
        if form != "4" or fdate < cutoff:
            continue
        acc_nodash = acc.replace("-", "")
        # SEC folder index is index.json (not {accession}-index.json)
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"
        try:
            ir = SESSION.get(idx_url, timeout=20)
            if ir.status_code == 404:
                time.sleep(0.12)
                continue
            ir.raise_for_status()
            index = ir.json()
        except Exception:
            time.sleep(0.12)
            continue
        xml_name = None
        names = [item.get("name", "") for item in index.get("directory", {}).get("item", [])]
        for prefer in ("form4.xml", "form4.htm"):
            if prefer in names:
                xml_name = prefer
                break
        if not xml_name:
            for name in names:
                if name.endswith(".xml") and "form" in name.lower():
                    xml_name = name
                    break
        if not xml_name:
            for name in names:
                if name.endswith(".xml"):
                    xml_name = name
                    break
        if not xml_name:
            time.sleep(0.12)
            continue
        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{xml_name}"
        try:
            xr = SESSION.get(xml_url, timeout=25)
            xr.raise_for_status()
            out.extend(_parse_form4_xml(xr.text, symbol, fdate))
        except Exception:
            pass
        time.sleep(0.12)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.getenv("INSIDER_FETCH_LIMIT", "120")))
    ap.add_argument("--lookback-days", type=int, default=90)
    args = ap.parse_args()

    # Prefer liquid names from live panel, then universe core list
    tickers: list[str] = []
    live_path = REPO / "data" / "predictions_v3" / "live.csv"
    if live_path.exists():
        try:
            import pandas as pd
            live = pd.read_csv(live_path)
            if not live.empty and "symbol" in live.columns:
                sort_col = "pred_ret" if "pred_ret" in live.columns else "pred_proba_up"
                live = live.sort_values(sort_col, ascending=False)
                tickers = [str(s).upper() for s in live["symbol"].head(args.limit * 2)]
        except Exception:
            tickers = []
    if len(tickers) < args.limit:
        tickers = list(dict.fromkeys(tickers + select_priority_tickers(
            limit=args.limit, seed=date.today().isoformat())))
    tickers = tickers[: args.limit]
    cmap = _cik_map()
    all_trades: list[dict] = []
    print(f"[fetch-insider] {len(tickers)} tickers, lookback={args.lookback_days}d", flush=True)
    for i, sym in enumerate(tickers):
        cik = cmap.get(sym)
        if not cik:
            continue
        batch = fetch_ticker_form4(sym, cik, args.lookback_days)
        all_trades.extend(batch)
        if (i + 1) % 20 == 0:
            print(f"[fetch-insider] {i+1}/{len(tickers)} trades={len(all_trades)}", flush=True)

    write_artifacts(all_trades, window_days=30)
    print(f"[fetch-insider] done trades={len(all_trades)}", flush=True)
    return 0 if all_trades else 1


if __name__ == "__main__":
    sys.exit(main())
