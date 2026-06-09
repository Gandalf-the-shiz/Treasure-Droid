"""Fetch U.S. congressional stock trades (Pelosi-tracker style) into data/congress/.

Sources: Quiver (optional), capitol-api (optional), kadoa open dataset (default).

Usage:
  python scripts/fetch-congress-trades.py
  python scripts/fetch-congress-trades.py --window-days 90
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from congress_sources import fetch_all_congress_trades  # noqa: E402
from congress_signals import build_signals, filter_recent_trades, write_artifacts, _load_watchlist  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-days", type=int, default=0, help="override watchlist window")
    args = ap.parse_args()

    print("[fetch-congress] pulling trades from all configured sources…", flush=True)
    all_trades = fetch_all_congress_trades()
    if not all_trades:
        print("[fetch-congress] WARNING: no trades fetched", flush=True)
        return 1

    wl = _load_watchlist()
    if args.window_days:
        wl["signalWindowDays"] = args.window_days
    window = int(wl.get("signalWindowDays") or 90)
    min_amt = float(wl.get("minAmountMidUsd") or 15000)

    recent = filter_recent_trades(all_trades, window, min_amt)
    signals_doc = build_signals(all_trades, wl)
    write_artifacts(recent, signals_doc)
    # Full normalized history for point-in-time ML overlays
    norm_path = REPO / "data" / "congress" / "trades_normalized.json"
    norm_path.write_text(
        json.dumps(
            {
                "generatedAt": signals_doc["generatedAt"],
                "count": len(all_trades),
                "trades": all_trades,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[fetch-congress] wrote {norm_path}", flush=True)

    hist = signals_doc.get("watchlistHistory") or []
    pelosi = [t for t in hist if "pelosi" in (t.get("politician") or "").lower()]
    print(f"[fetch-congress] total={len(all_trades):,} recent({window}d)={len(recent):,} "
          f"symbols={signals_doc['symbolCount']} watchlist_365d={len(hist)} pelosi_365d={len(pelosi)}",
          flush=True)
    top = signals_doc["leaderboard"][:5]
    for row in top:
        print(f"  · {row['politician']}: {row['buys']} buys / {row['sells']} sells", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
