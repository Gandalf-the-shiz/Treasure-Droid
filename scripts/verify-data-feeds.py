"""
verify-data-feeds.py

Run lightweight live probes against every data provider Nostradamus uses,
then write a health snapshot that downstream models and CI can rely on.

Outputs:
  data/feeds/health.json
  data/feeds/health-history.json   (rolling history, last 90 entries)

Exit code:
  0 if at least the minimum-required equity provider is healthy
  1 otherwise (so CI can fail fast on broken canals)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from data_sources import probe_providers  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "feeds"
OUT_PATH = OUT_DIR / "health.json"
HISTORY_PATH = OUT_DIR / "health-history.json"
HISTORY_MAX = int(os.getenv("DATA_FEEDS_HISTORY_MAX", "90") or "90")
MIN_REQUIRED_EQUITY = os.getenv("DATA_FEEDS_MIN_EQUITY_PROVIDER", "yfinance").strip().lower()
ALT_EQUITY_PROVIDER = os.getenv("DATA_FEEDS_ALT_EQUITY_PROVIDER", "stooq").strip().lower()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    health = probe_providers(probe_symbol=os.getenv("DATA_FEEDS_PROBE_SYMBOL", "AAPL"))

    providers = health.get("providers") or {}
    primary_ok = bool((providers.get(MIN_REQUIRED_EQUITY) or {}).get("ok"))
    alt_info = providers.get(ALT_EQUITY_PROVIDER) or {}
    alt_ok = bool(alt_info.get("ok")) and not alt_info.get("skipped")

    health["criticalReady"] = primary_ok or alt_ok
    health["criteria"] = {
        "minRequiredEquityProvider": MIN_REQUIRED_EQUITY,
        "altEquityProvider": ALT_EQUITY_PROVIDER,
    }

    OUT_PATH.write_text(f"{json.dumps(health, indent=2)}\n", encoding="utf-8")

    history = {"entries": []}
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) or {"entries": []}
        except Exception:
            history = {"entries": []}
    entries = history.get("entries") or []
    entries.append(
        {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "criticalReady": health["criticalReady"],
            "providers": {
                name: {"ok": p.get("ok"), "rows": p.get("rows"), "latencyMs": p.get("latencyMs")}
                for name, p in providers.items()
            },
        }
    )
    history["entries"] = entries[-HISTORY_MAX:]
    HISTORY_PATH.write_text(f"{json.dumps(history, indent=2)}\n", encoding="utf-8")

    print("[verify-data-feeds] complete")
    for name, info in providers.items():
        flag = "OK " if info.get("ok") else "FAIL"
        print(
            f"[verify-data-feeds] {flag} {name:>10} rows={info.get('rows'):<5} "
            f"latencyMs={info.get('latencyMs')} error={info.get('error') or ''}"
        )
    print(f"[verify-data-feeds] criticalReady={health['criticalReady']}")

    if not health["criticalReady"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
