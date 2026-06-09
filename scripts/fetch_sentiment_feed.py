"""Market sentiment feed — "listen for the gossip" across news + Reddit.

Per-symbol sentiment from free sources, blended into one score that becomes an
alpha sleeve and influences the fleet:
  - Finnhub company-news (free) -> VADER headline sentiment + buzz (article count)
  - Reddit / crowd via intelligence.mass_psychology (already scraped)
  - Google Trends (optional, via pytrends if installed)

Cached + rate-limited (Finnhub 60/min). Each run also writes a dated snapshot to
data/sentiment_feed/history/ so we accumulate historical sentiment to compare
against returns in ML runs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from app_secrets import get_secret  # noqa: E402

OUT_DIR = REPO / "data" / "sentiment_feed"
CACHE_PATH = OUT_DIR / "cache.json"
SIGNALS_PATH = OUT_DIR / "signals_by_symbol.json"
HIST_DIR = OUT_DIR / "history"
LIVE_CSV = REPO / "data" / "predictions_v3" / "live.csv"
BASE = "https://finnhub.io/api/v1"

REFRESH_DAYS = float(os.getenv("SENTIMENT_REFRESH_DAYS", "2"))
MAX_SYMBOLS = int(os.getenv("SENTIMENT_MAX_SYMBOLS", "150"))
CALL_SLEEP = float(os.getenv("SENTIMENT_CALL_SLEEP", "1.1"))
NEWS_LOOKBACK_DAYS = 7


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _vader():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except Exception:
        return None


def _universe() -> list[str]:
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
    seen, out = set(), []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _stale(entry: dict) -> bool:
    if not entry or "fetchedAt" not in entry:
        return True
    try:
        ts = datetime.strptime(entry["fetchedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return (datetime.now(timezone.utc) - ts).total_seconds() > REFRESH_DAYS * 86400


def _fetch_news(sym: str, key: str) -> list[dict]:
    to = datetime.now(timezone.utc).date()
    frm = to - timedelta(days=NEWS_LOOKBACK_DAYS)
    url = f"{BASE}/company-news?symbol={sym}&from={frm}&to={to}&token={key}"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1)); continue
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except requests.RequestException:
            time.sleep(1.0 * (attempt + 1))
    return []


def _news_sentiment(news: list[dict], sia) -> dict:
    heads = [str(n.get("headline") or "") for n in (news or []) if n.get("headline")]
    if not heads:
        return {"news_sentiment": 0.0, "news_count": 0}
    if sia is not None:
        scores = [sia.polarity_scores(h)["compound"] for h in heads[:60]]
        mean = sum(scores) / len(scores)
    else:
        mean = 0.0
    return {"news_sentiment": round(mean, 4), "news_count": len(heads)}


def _reddit_score(sym: str) -> dict:
    try:
        from intelligence.mass_psychology import get_symbol_boost
        b = get_symbol_boost(sym) or {}
        return {"reddit_score": round(float(b.get("crowdScore") or 0.0), 4),
                "reddit_sentiment": b.get("traderSentiment")}
    except Exception:
        return {"reddit_score": 0.0, "reddit_sentiment": None}


def _blend(news_s: float, reddit_s: float, buzz: int) -> float:
    # News carries most weight; reddit adds crowd gossip; tiny buzz tilt.
    base = 0.6 * float(news_s) + 0.4 * max(-1.0, min(1.0, float(reddit_s)))
    buzz_tilt = min(0.1, buzz / 500.0) * (1 if base >= 0 else -1)
    return round(max(-1.0, min(1.0, base + buzz_tilt)), 4)


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    key = get_secret("FINNHUB_API_KEY")
    sia = _vader()
    cache = _load(CACHE_PATH, {})
    universe = _universe()

    fetched = 0
    if key:
        todo = [s for s in universe if _stale(cache.get(s, {}))][:MAX_SYMBOLS]
        for sym in todo:
            news = _fetch_news(sym, key)
            time.sleep(CALL_SLEEP)
            cache[sym] = {"fetchedAt": _now(), **_news_sentiment(news, sia)}
            fetched += 1
        CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    signals = {}
    for sym in (universe or list(cache.keys())):
        c = cache.get(sym, {})
        rd = _reddit_score(sym)
        ns = float(c.get("news_sentiment") or 0.0)
        buzz = int(c.get("news_count") or 0)
        if buzz == 0 and rd["reddit_score"] == 0.0:
            continue
        signals[sym] = {
            "news_sentiment": ns, "news_count": buzz,
            "reddit_score": rd["reddit_score"], "reddit_sentiment": rd["reddit_sentiment"],
            "sentiment_score": _blend(ns, rd["reddit_score"], buzz),
        }

    doc = {"generatedAt": _now(), "ok": True, "fetchedThisRun": fetched,
           "cachedSymbols": len(cache), "signalSymbols": len(signals),
           "sources": ["finnhub_news", "reddit", "vader"], "bySymbol": signals}
    SIGNALS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    # Dated snapshot for historical comparison in ML runs.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap = {sym: v["sentiment_score"] for sym, v in signals.items()}
    (HIST_DIR / f"{today}.json").write_text(
        json.dumps({"date": today, "generatedAt": _now(), "bySymbol": snap}, indent=2), encoding="utf-8")

    print(f"[sentiment] fetched={fetched} signals={len(signals)} (news+reddit, snapshot {today})", flush=True)
    return doc


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-symbols", type=int, default=0)
    args = ap.parse_args()
    if args.max_symbols:
        MAX_SYMBOLS = args.max_symbols
        os.environ["SENTIMENT_MAX_SYMBOLS"] = str(args.max_symbols)
    run()
