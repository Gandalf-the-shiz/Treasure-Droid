#!/usr/bin/env python3
"""
fetch-ipos.py — Upcoming IPO ingestion pipeline.

Fetches upcoming IPO calendar events from Finnhub when FINNHUB_API_KEY is set,
normalises fields, and writes data/ipos/upcoming.json for the frontend IPO view.
Falls back to preserving existing file if API key is not configured.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_PATH = REPO_ROOT / "data" / "ipos" / "upcoming.json"


def _normalise_risk(ipo: dict) -> str:
    amount = float(ipo.get("totalSharesValue") or 0)
    if amount >= 2_000_000_000:
        return "low"
    if amount >= 750_000_000:
        return "medium"
    return "high"


def _normalise_underwriter_tier(lead: str) -> int:
    if not lead:
        return 2
    lead_l = lead.lower()
    if any(k in lead_l for k in ["goldman", "morgan stanley", "jpmorgan", "bofa", "citi"]):
        return 1
    if any(k in lead_l for k in ["barclays", "ubs", "deutsche", "wells", "jefferies"]):
        return 2
    return 3


def _load_existing() -> dict:
    if OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def main() -> int:
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing()
    if not api_key:
        if not existing:
            OUTPUT_PATH.write_text(
                json.dumps(
                    {
                        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "sources": ["manual-seed"],
                        "ipos": [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        print("[fetch-ipos] FINNHUB_API_KEY not configured. Kept existing IPO dataset.")
        return 0

    start = date.today()
    end = start + timedelta(days=90)

    url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "token": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        if existing:
            print(f"[fetch-ipos] API request failed ({exc}). Preserving existing IPO dataset.")
            return 0
        raise

    items = []
    for raw in payload.get("ipoCalendar", []):
        company = raw.get("name") or raw.get("symbol") or "Unknown"
        items.append(
            {
                "company": company,
                "symbol": raw.get("symbol") or "TBD",
                "expectedDate": raw.get("date") or "TBD",
                "exchange": raw.get("exchange") or "Unknown",
                "sector": raw.get("industry") or "Other",
                "expectedDealSizeUsdBn": round(float(raw.get("totalSharesValue") or 0) / 1_000_000_000, 3),
                "underwriterTier": _normalise_underwriter_tier(raw.get("leadUnderwriter") or ""),
                "riskLevel": _normalise_risk(raw),
            }
        )

    items.sort(key=lambda x: str(x.get("expectedDate", "")))

    out = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": ["finnhub-ipo-calendar"],
        "ipos": items[:80],
    }

    OUTPUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[fetch-ipos] Wrote {len(out['ipos'])} IPO rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
