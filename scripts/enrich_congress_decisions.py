"""Attach congressional trade intelligence to investor picks in decisions.json."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from congress_signals import get_symbol_signal, load_signals  # noqa: E402

DECISIONS_PATH = REPO / "data" / "investor_v3" / "decisions.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DECISIONS_PATH.exists():
        raise SystemExit(f"missing {DECISIONS_PATH}")
    decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    signals = load_signals()
    if not signals:
        print("[enrich-congress] no signals — run fetch-congress-trades.py first", flush=True)
        return

    days = decisions.get("days") or []
    target = [d for d in days if d.get("date") != "FINAL"][-args.last_days :]
    attached = 0
    for d in target:
        for p in d.get("picks") or []:
            sym = str(p.get("symbol") or "").upper()
            sig = get_symbol_signal(sym)
            if not sig:
                continue
            p["congress"] = {
                "score": sig.get("congress_score"),
                "boost": sig.get("congress_boost"),
                "net_flow_score": sig.get("net_flow_score"),
                "buy_count": sig.get("buy_count"),
                "sell_count": sig.get("sell_count"),
                "notable_politicians": sig.get("notable_politicians"),
                "pelosi_buy": sig.get("pelosi_buy"),
                "recent_buys": sig.get("recent_buys", [])[:3],
            }
            if sig.get("pelosi_buy"):
                why = p.get("why")
                if isinstance(why, list):
                    why.append("Nancy Pelosi disclosed a purchase in this symbol within the signal window.")
                elif isinstance(why, str):
                    p["why"] = why + " Pelosi buy flagged."
            attached += 1

    print(f"[enrich-congress] attached to {attached} picks across {len(target)} days", flush=True)
    if args.dry_run:
        return

    tmp = DECISIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(decisions, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, DECISIONS_PATH)


if __name__ == "__main__":
    main()
