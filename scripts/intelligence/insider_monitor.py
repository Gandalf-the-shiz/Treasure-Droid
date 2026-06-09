"""Fed-style insider activity monitor — legal public filings only.

Uses SEC Form 4 data (already fetched) to detect:
  - Cluster buys (multiple insiders buying within 14d)
  - C-suite purchase clusters
  - Unusual buy/sell imbalance vs baseline

This does NOT detect illegal pre-disclosure insider trading — only patterns
in *public* filings you may legally follow with delay (paper/research default).

Never auto-trade on non-public information.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from insider_signals import build_signals, load_trades, write_artifacts  # noqa: E402

OUT_DIR = REPO / "data" / "insider"
ALERTS_PATH = OUT_DIR / "fed_monitor_alerts.json"
FOLLOW_PATH = OUT_DIR / "follow_insider_signals.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def analyze(trades: list[dict]) -> dict:
    cutoff_14 = (date.today() - timedelta(days=14)).isoformat()
    cutoff_90 = (date.today() - timedelta(days=90)).isoformat()

    recent_14: dict[str, list] = defaultdict(list)
    baseline_90: dict[str, dict] = defaultdict(lambda: {"buy": 0, "sell": 0})

    for t in trades:
        sym = str(t.get("symbol") or "").upper()
        if not sym:
            continue
        fd = t.get("filing_date") or t.get("transaction_date") or ""
        side = t.get("side")
        if fd >= cutoff_90:
            if side == "buy":
                baseline_90[sym]["buy"] += 1
            elif side == "sell":
                baseline_90[sym]["sell"] += 1
        if fd >= cutoff_14 and side == "buy":
            recent_14[sym].append(t)

    alerts: list[dict] = []
    follow: dict[str, dict] = {}

    for sym, buys in recent_14.items():
        n = len(buys)
        insiders = {str(b.get("insider") or "") for b in buys if b.get("insider")}
        c_suite = sum(
            1 for b in buys
            if any(k in str(b.get("insider") or "").lower()
                   for k in ("ceo", "cfo", "chief", "president", "director"))
        )
        base = baseline_90[sym]
        base_total = base["buy"] + base["sell"]
        spike = n >= 3 and n > max(1, base["buy"] * 0.5)

        score = min(1.0, n * 0.15 + c_suite * 0.2 + (0.25 if spike else 0))
        alert_level = "high" if score >= 0.65 else "medium" if score >= 0.4 else "low"

        if n >= 2:
            entry = {
                "symbol": sym,
                "clusterBuys14d": n,
                "uniqueInsiders": len(insiders),
                "cSuiteBuys": c_suite,
                "spikeVs90d": spike,
                "fedMonitorScore": round(score, 4),
                "alertLevel": alert_level,
                "legalNote": "Public Form 4 only — follow with delay; paper default",
                "insiders": list(insiders)[:8],
                "latestFiling": max((b.get("filing_date") or "") for b in buys),
            }
            follow[sym] = {
                **entry,
                "followBoost": round(1.0 + min(0.30, score * 0.35), 4),
                "recommendedSide": "buy" if score >= 0.4 else "watch",
            }
            if score >= 0.4:
                alerts.append(entry)

    alerts.sort(key=lambda x: x["fedMonitorScore"], reverse=True)

    return {
        "generatedAt": _now(),
        "disclaimer": (
            "Monitors public SEC filings only. Does not detect illegal insider trading. "
            "Following disclosed insider buys is legal with filing delay; not guaranteed profit."
        ),
        "nAlerts": len(alerts),
        "alerts": alerts[:50],
        "bySymbol": follow,
    }


def get_follow_boost(symbol: str) -> dict | None:
    if not FOLLOW_PATH.exists():
        return None
    try:
        doc = json.loads(FOLLOW_PATH.read_text(encoding="utf-8"))
        return (doc.get("bySymbol") or {}).get(symbol.upper())
    except (OSError, json.JSONDecodeError):
        return None


def run() -> dict:
    trades = load_trades()
    if not trades:
        print("[insider-monitor] no trades — run fetch-insider-trades.py first", flush=True)
        return {"nAlerts": 0}

    write_artifacts(trades)
    report = analyze(trades)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ALERTS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    FOLLOW_PATH.write_text(json.dumps({
        "generatedAt": report["generatedAt"],
        "bySymbol": report["bySymbol"],
    }, indent=2), encoding="utf-8")

    print(f"[insider-monitor] alerts={report['nAlerts']} "
          f"follow_symbols={len(report['bySymbol'])}", flush=True)
    return report


if __name__ == "__main__":
    run()
