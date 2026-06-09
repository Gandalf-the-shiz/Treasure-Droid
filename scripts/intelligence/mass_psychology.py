"""Mass psychology / crowd sentiment from public web sources.

Scrapes Reddit finance communities + news RSS to estimate retail mood and
map tickers → trader-sentiment tilt. Paper/research only — not investment advice.

Sources (no API keys required):
  - Reddit public .json feeds (r/wallstreetbets, r/stocks, r/investing)
  - Reuters markets RSS (headline tone)
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "mass_psychology"
INDEX_PATH = OUT_DIR / "index.json"
TICKER_PATH = OUT_DIR / "ticker_sentiment.json"

REDDIT_SUBS = ("wallstreetbets", "stocks", "investing", "StockMarket")
USER_AGENT = "NostradamusResearch/1.0 (mass psychology; educational)"
TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
TICKER_BARE_RE = re.compile(r"\b([A-Z]{2,5})\b")

STOP_TICKERS = frozenset({
    "I", "A", "IT", "OR", "ON", "FOR", "THE", "AND", "USD", "CEO", "IPO", "ARE", "TO", "IN",
    "IS", "AT", "BE", "BY", "AN", "AS", "OF", "IF", "UP", "SO", "NO", "WE", "US", "AI", "DD",
    "YOLO", "ETF", "GDP", "CPI", "FED", "SEC", "LLC", "INC", "TOP", "NEW", "ALL", "OUT", "NOW",
    "COM", "WATCH", "STOCK", "JOB", "HOW", "MORE", "THAT", "HERE", "ROLE", "PLAY", "ORIES",
    "EKERS", "TIATE", "ALARY", "OWARD", "ECORD", "GAIN", "SOARS", "HPE", "SAYS", "WILL",
})

BULL_WORDS = frozenset(
    "moon rocket squeeze bullish buy calls green pump rip breakout rally soar "
    "undervalued gem bull long yolo".split()
)
BEAR_WORDS = frozenset(
    "crash bearish puts short dump red tank collapse recession fear sell "
    "overvalued bubble rug bear down".split()
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_json(url: str, timeout: int = 15) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _score_text(text: str) -> float:
    """Return sentiment in [-1, 1]."""
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return 0.0
    bull = sum(1 for w in words if w in BULL_WORDS)
    bear = sum(1 for w in words if w in BEAR_WORDS)
    total = bull + bear
    if total == 0:
        return 0.0
    return max(-1.0, min(1.0, (bull - bear) / total))


def _load_valid_symbols() -> set[str]:
    syms: set[str] = set()
    live = REPO / "data" / "predictions_v3" / "live.csv"
    if live.exists():
        try:
            import pandas as pd
            df = pd.read_csv(live, usecols=["symbol"])
            syms.update(str(s).upper() for s in df["symbol"].dropna())
        except Exception:
            pass
    try:
        from data_universe import CORE_TICKERS
        syms.update(CORE_TICKERS)
    except Exception:
        pass
    return syms


def _extract_tickers(text: str, valid: set[str] | None = None) -> list[str]:
    valid = valid or _load_valid_symbols()
    found: list[str] = []
    upper = text.upper()
    for m in TICKER_RE.finditer(upper):
        sym = m.group(1)
        if sym not in STOP_TICKERS:
            found.append(sym)
    # Bare tickers only when they are in the live universe (avoids RSS word soup)
    if valid:
        for m in TICKER_BARE_RE.finditer(upper):
            sym = m.group(1)
            if sym in valid and sym not in STOP_TICKERS and sym not in found:
                found.append(sym)
    return found[:15]


def scrape_reddit(valid: set[str] | None = None) -> list[dict]:
    posts: list[dict] = []
    for sub in REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=50"
        data = _fetch_json(url)
        time.sleep(0.4)
        if not data or not isinstance(data, dict):
            continue
        children = (data.get("data") or {}).get("children") or []
        for ch in children:
            d = ch.get("data") or {}
            title = str(d.get("title") or "")
            selftext = str(d.get("selftext") or "")[:500]
            text = f"{title} {selftext}"
            score = _score_text(text)
            tickers = _extract_tickers(text, valid=valid)
            posts.append({
                "source": f"reddit/{sub}",
                "title": title[:200],
                "score": round(score, 4),
                "upvotes": int(d.get("ups") or 0),
                "tickers": tickers[:15],
                "createdUtc": d.get("created_utc"),
            })
    return posts


def scrape_news_rss(valid: set[str] | None = None) -> list[dict]:
    """Lightweight RSS headline scrape (Reuters markets)."""
    url = "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best"
    text = _fetch_text(url)
    if not text or "<item>" not in text:
        # Fallback: marketwatch top stories page snippet
        text = _fetch_text("https://www.marketwatch.com/rss/topstories")
    headlines: list[dict] = []
    for block in re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", text, re.I):
        h = re.sub(r"<[^>]+>", "", block).strip()
        if not h or h.lower() in {"top stories", "reuters"}:
            continue
        if len(h) < 12:
            continue
        headlines.append({
            "source": "rss/headlines",
            "title": h[:240],
            "score": round(_score_text(h), 4),
            "tickers": _extract_tickers(h, valid=valid),
        })
        if len(headlines) >= 40:
            break
    return headlines


def _ml_panel_crowd_proxy(valid: set[str], limit: int = 40) -> dict[str, dict]:
    """When Reddit is blocked, proxy retail tilt from live ML panel + congress buzz."""
    live = REPO / "data" / "predictions_v3" / "live.csv"
    if not live.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_csv(live)
    except Exception:
        return {}
    if df.empty or "symbol" not in df.columns:
        return {}
    if "pred_ret" in df.columns:
        df = df.sort_values("pred_ret", ascending=False)
    out: dict[str, dict] = {}
    try:
        from congress_signals import get_symbol_signal
    except Exception:
        get_symbol_signal = lambda s: None  # type: ignore

    for _, row in df.head(limit * 2).iterrows():
        sym = str(row.get("symbol") or "").upper()
        if not sym or (valid and sym not in valid):
            continue
        pr = float(row.get("pred_ret") or 0)
        proba = float(row.get("pred_proba_up") or 0.5)
        score = max(-1.0, min(1.0, pr * 25.0 + (proba - 0.5) * 1.5))
        cg = get_symbol_signal(sym) or {}
        if cg.get("pelosi_buy"):
            score = min(1.0, score + 0.15)
        if float(cg.get("congress_score") or 0) > 0.3:
            score = min(1.0, score + 0.08)
        out[sym] = {
            "symbol": sym,
            "crowdScore": round(score, 4),
            "mentions": 1,
            "traderSentiment": "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral",
            "followCrowdBoost": round(1.0 + max(-0.15, min(0.20, score * 0.25)), 4),
            "source": "ml_panel_proxy",
        }
        if len(out) >= limit:
            break
    return out


def aggregate(posts: list[dict], headlines: list[dict]) -> dict:
    valid = _load_valid_symbols()
    ticker_scores: dict[str, list[float]] = {}
    ticker_mentions: Counter = Counter()

    for item in posts + headlines:
        s = float(item.get("score") or 0)
        weight = 1.0 + min(3.0, (int(item.get("upvotes") or 0)) / 1000.0)
        raw_tickers = item.get("tickers") or []
        if valid:
            raw_tickers = [t for t in raw_tickers if t in valid]
        for sym in raw_tickers:
            ticker_scores.setdefault(sym, []).append(s * weight)
            ticker_mentions[sym] += 1

    by_ticker = {}
    for sym, scores in ticker_scores.items():
        if len(scores) < 1:
            continue
        mean = sum(scores) / len(scores)
        by_ticker[sym] = {
            "symbol": sym,
            "crowdScore": round(mean, 4),
            "mentions": ticker_mentions[sym],
            "traderSentiment": "bullish" if mean > 0.15 else "bearish" if mean < -0.15 else "neutral",
            "followCrowdBoost": round(1.0 + max(-0.15, min(0.20, mean * 0.25)), 4),
        }

    if not by_ticker:
        proxy = _ml_panel_crowd_proxy(valid)
        by_ticker.update(proxy)

    all_scores = [float(p.get("score") or 0) for p in posts] + [float(h.get("score") or 0) for h in headlines]
    if by_ticker:
        all_scores.extend(float(v.get("crowdScore") or 0) for v in by_ticker.values())
    market_mood = sum(all_scores) / len(all_scores) if all_scores else 0.0

    return {
        "generatedAt": _now(),
        "marketMood": round(market_mood, 4),
        "marketMoodLabel": (
            "euphoria" if market_mood > 0.25 else
            "fear" if market_mood < -0.25 else
            "mixed"
        ),
        "nPosts": len(posts),
        "nHeadlines": len(headlines),
        "topMentioned": [s for s, _ in ticker_mentions.most_common(30)] or list(by_ticker.keys())[:30],
        "bySymbol": by_ticker,
        "proxyUsed": bool(not posts and by_ticker),
    }


def get_symbol_boost(symbol: str) -> dict | None:
    if not TICKER_PATH.exists():
        return None
    try:
        doc = json.loads(TICKER_PATH.read_text(encoding="utf-8"))
        return (doc.get("bySymbol") or {}).get(symbol.upper())
    except (OSError, json.JSONDecodeError):
        return None


def run() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    valid = _load_valid_symbols()
    posts = scrape_reddit(valid)
    headlines = scrape_news_rss(valid)
    agg = aggregate(posts, headlines)

    INDEX_PATH.write_text(json.dumps({
        "generatedAt": agg["generatedAt"],
        "marketMood": agg["marketMood"],
        "marketMoodLabel": agg["marketMoodLabel"],
        "nPosts": agg["nPosts"],
        "nHeadlines": agg["nHeadlines"],
        "samplePosts": posts[:20],
        "sampleHeadlines": headlines[:15],
    }, indent=2), encoding="utf-8")

    TICKER_PATH.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    print(f"[mass-psych] mood={agg['marketMoodLabel']} ({agg['marketMood']}) "
          f"tickers={len(agg['bySymbol'])}", flush=True)
    return agg


if __name__ == "__main__":
    run()
