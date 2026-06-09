"""Finnhub free-tier feed: earnings surprises (PEAD/SUE) + analyst revisions.

Powers two of the most robust documented anomalies (Alpha Doctrine sleeves):
  - PEAD  : stocks drift in the direction of an earnings surprise for 30-60d.
  - Revisions: analyst upgrade/downgrade breadth predicts continuation.

Free tier = 60 calls/min. We cache aggressively (earnings change quarterly,
recommendations monthly) and refresh incrementally within a per-run call budget
so the whole universe gets covered over a few days, then maintained.

Outputs:
  data/finnhub/cache.json              raw per-symbol earnings + reco (+ fetchedAt)
  data/finnhub/signals_by_symbol.json  normalized pead_score / revision_score
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from app_secrets import get_secret  # noqa: E402

OUT_DIR = REPO / "data" / "finnhub"
CACHE_PATH = OUT_DIR / "cache.json"
SIGNALS_PATH = OUT_DIR / "signals_by_symbol.json"
LIVE_CSV = REPO / "data" / "predictions_v3" / "live.csv"
BASE = "https://finnhub.io/api/v1"

REFRESH_DAYS = float(os.getenv("FINNHUB_REFRESH_DAYS", "5"))
MAX_SYMBOLS = int(os.getenv("FINNHUB_MAX_SYMBOLS", "200"))
CALL_SLEEP = float(os.getenv("FINNHUB_CALL_SLEEP", "1.05"))  # ~57 calls/min
PEAD_WINDOW_DAYS = 90


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _universe() -> list[str]:
    """Tradeable symbols, prioritized by liquidity (size proxy)."""
    syms: list[str] = []
    if LIVE_CSV.exists():
        try:
            import pandas as pd
            df = pd.read_csv(LIVE_CSV)
            df.columns = [c.strip().lower() for c in df.columns]
            if "symbol" in df.columns:
                syms = df["symbol"].astype(str).str.upper().tolist()
        except Exception:
            syms = []
    try:
        from intelligence.tradeable_universe import filter_symbols, _liquidity_cache
        syms = filter_symbols(syms)
        liq = _liquidity_cache()
        syms.sort(key=lambda s: (liq.get(s) or {}).get("adv_20", 0), reverse=True)
    except Exception:
        pass
    # de-dup preserving order
    seen, out = set(), []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _get(url: str) -> object | None:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(1.0 * (attempt + 1))
    return None


def _stale(entry: dict) -> bool:
    if not entry or "fetchedAt" not in entry:
        return True
    try:
        ts = datetime.strptime(entry["fetchedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return (datetime.now(timezone.utc) - ts).total_seconds() > REFRESH_DAYS * 86400


def _pead_score(earnings: list[dict]) -> dict:
    """SUE = latest surprise% / std(history), decayed by recency of the report."""
    rows = [e for e in (earnings or []) if e.get("surprisePercent") is not None and e.get("period")]
    if not rows:
        return {}
    rows = sorted(rows, key=lambda e: e["period"], reverse=True)
    latest = rows[0]
    sp = [float(e["surprisePercent"]) for e in rows]
    sd = statistics.pstdev(sp) if len(sp) > 1 else (abs(sp[0]) or 1.0)
    sue = float(sp[0]) / sd if sd else 0.0
    try:
        period = datetime.strptime(latest["period"], "%Y-%m-%d").date()
        days = (datetime.now(timezone.utc).date() - period).days
    except (ValueError, TypeError):
        days = 999
    # Drift lives ~announce(period+~25d) .. period+~85d. Recency weight in [0,1].
    recency = max(0.0, 1.0 - max(0, days - 25) / float(PEAD_WINDOW_DAYS))
    if days > PEAD_WINDOW_DAYS + 30:
        recency = 0.0
    return {
        "sue": round(sue, 4),
        "surprise_pct": round(float(sp[0]), 4),
        "days_since_period": days,
        "pead_score": round(sue * recency, 4),
    }


def _revision_score(reco: list[dict]) -> dict:
    """Net analyst tilt + month-over-month revision (the actual alpha)."""
    rows = [r for r in (reco or []) if r.get("period")]
    if not rows:
        return {}
    rows = sorted(rows, key=lambda r: r["period"], reverse=True)

    def net(r: dict) -> float:
        sb, b = float(r.get("strongBuy", 0)), float(r.get("buy", 0))
        h = float(r.get("hold", 0))
        s, ss = float(r.get("sell", 0)), float(r.get("strongSell", 0))
        total = sb + b + h + s + ss
        if total <= 0:
            return 0.0
        return (2 * sb + b - s - 2 * ss) / total

    latest = net(rows[0])
    prev = net(rows[1]) if len(rows) > 1 else latest
    delta = latest - prev
    return {
        "revision_net": round(latest, 4),
        "revision_delta": round(delta, 4),
        "revision_score": round(0.5 * latest + 1.0 * delta, 4),  # emphasize the change
    }


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = get_secret("FINNHUB_API_KEY")
    if not key:
        doc = {"generatedAt": _now(), "ok": False, "message": "no FINNHUB_API_KEY (config/secrets.json or env)"}
        SIGNALS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    cache = _load_json(CACHE_PATH, {})
    universe = _universe()
    # Refresh stale/missing first, oldest-priority, within budget.
    todo = [s for s in universe if _stale(cache.get(s, {}))][:MAX_SYMBOLS]
    fetched = 0
    for sym in todo:
        earn = _get(f"{BASE}/stock/earnings?symbol={sym}&token={key}")
        time.sleep(CALL_SLEEP)
        reco = _get(f"{BASE}/stock/recommendation?symbol={sym}&token={key}")
        time.sleep(CALL_SLEEP)
        if earn is None and reco is None:
            continue
        cache[sym] = {
            "fetchedAt": _now(),
            "earnings": earn if isinstance(earn, list) else [],
            "reco": reco if isinstance(reco, list) else [],
        }
        fetched += 1
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    # Recompute normalized signals for everything we have cached.
    signals = {}
    for sym, entry in cache.items():
        pead = _pead_score(entry.get("earnings"))
        rev = _revision_score(entry.get("reco"))
        if not pead and not rev:
            continue
        signals[sym] = {**pead, **rev}

    doc = {
        "generatedAt": _now(),
        "ok": True,
        "fetchedThisRun": fetched,
        "cachedSymbols": len(cache),
        "signalSymbols": len(signals),
        "bySymbol": signals,
    }
    SIGNALS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(
        f"[finnhub] fetched={fetched} cached={len(cache)} signals={len(signals)} "
        f"(budget={MAX_SYMBOLS}, refresh={REFRESH_DAYS}d)",
        flush=True,
    )
    return doc


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-symbols", type=int, default=0, help="override per-run fetch budget")
    args = ap.parse_args()
    if args.max_symbols:
        os.environ["FINNHUB_MAX_SYMBOLS"] = str(args.max_symbols)
        MAX_SYMBOLS = args.max_symbols
    run()
