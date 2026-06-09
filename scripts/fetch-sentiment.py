"""
fetch-sentiment.py — Phase A: Real Sentiment Data Fetch

Fetches per-ticker sentiment from three free sources:
  1. NewsAPI (newsapi.org) — financial news headlines, scored with VADER
  2. Reddit PRAW — r/wallstreetbets, r/stocks, r/investing mention counts + sentiment
  3. SEC EDGAR full-text search — recent 8-K filing counts as event signal

The nightly job spends its quota on a rotating, sector-balanced subset so the
app keeps broad coverage without re-querying the same universe every day.

Output: data/sentiment/YYYY-MM-DD.json
  {
    "date": "YYYY-MM-DD",
    "generatedAt": "...",
    "tickers": {
      "AAPL": {
        "news_sentiment": 0.12,    # VADER compound score avg across headlines [-1,1]
        "reddit_mentions": 5,       # post+comment mentions in past 24h
        "reddit_sentiment": 0.08,   # VADER compound avg over Reddit text [-1,1]
        "sec_filing_count": 1       # 8-K/NT 10-K filings in past 7 days
      },
      ...
    }
  }

Required environment variables (set as GitHub Secrets):
  NEWSAPI_KEY  — free tier at newsapi.org (100 req/day)
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET — optional; script falls back to
                    unauthenticated scraping of public RSS feeds if absent.
  FRED_API_KEY — not used here; used by fetch-macro.py

Run after market close, before build-features.py.
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

SCRIPT_DIR   = Path(__file__).resolve().parent
REPO_ROOT    = SCRIPT_DIR.parent
TICKERS_FILE = REPO_ROOT / "data" / "tickers" / "us_tickers.json"
SENTIMENT_DIR = REPO_ROOT / "data" / "sentiment"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEWSAPI_KEY          = os.getenv("NEWSAPI_KEY", "")
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = "Nostradamus/1.0 (financial research bot; github.com/Gandalf-the-shiz/Nostradamus)"

# SEC EDGAR User-Agent (required per SEC policy)
SEC_USER_AGENT = "Nostradamus financial-research-bot contact@nostradamus.app"

# How many tickers to send per NewsAPI request (saves quota)
NEWS_BATCH_SIZE  = 5
NEWS_MAX_TICKERS = 100   # stop after N tickers to stay in free-tier limits
REDDIT_SUBS      = ["wallstreetbets", "stocks", "investing"]

# ---------------------------------------------------------------------------
# VADER sentiment scoring
# ---------------------------------------------------------------------------

def _get_vader():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except ImportError:
        print("[fetch-sentiment] WARN: vaderSentiment not installed. Returning 0 for all scores.")
        return None


def score_text(analyzer, text: str) -> float:
    """Return VADER compound score in [-1, 1], or 0.0 if analyzer is None."""
    if analyzer is None or not text:
        return 0.0
    scores = analyzer.polarity_scores(text)
    return round(scores["compound"], 4)


# ---------------------------------------------------------------------------
# Load ticker list
# ---------------------------------------------------------------------------

def load_tickers() -> list[str]:
    """Load a prioritized ticker subset for the nightly sentiment sweep."""
    return select_priority_tickers(limit=NEWS_MAX_TICKERS, seed=date.today().isoformat())


# ---------------------------------------------------------------------------
# Phase A-1: NewsAPI sentiment
# ---------------------------------------------------------------------------

def fetch_news_sentiment(tickers: list[str], analyzer) -> dict[str, dict]:
    """
    Fetch financial news from NewsAPI and score each headline with VADER.
    Returns {ticker: {"news_sentiment": float, "news_count": int}}.
    Falls back to zeros if NEWSAPI_KEY is not set or quota is exceeded.
    """
    results = {t: {"news_sentiment": 0.0, "news_count": 0} for t in tickers}

    if not NEWSAPI_KEY:
        print("[fetch-sentiment] NEWSAPI_KEY not set — skipping NewsAPI fetch.")
        return results

    try:
        import requests
    except ImportError:
        print("[fetch-sentiment] 'requests' not installed — skipping NewsAPI fetch.")
        return results

    base_url = "https://newsapi.org/v2/everything"
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # Process in batches to conserve quota
    processed = 0
    for i in range(0, min(len(tickers), NEWS_MAX_TICKERS), NEWS_BATCH_SIZE):
        batch = tickers[i : min(i + NEWS_BATCH_SIZE, NEWS_MAX_TICKERS)]
        query = " OR ".join(f'"{t}"' for t in batch)

        try:
            resp = requests.get(
                base_url,
                params={
                    "q": query,
                    "from": yesterday,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 100,
                    "apiKey": NEWSAPI_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

            for article in articles:
                title       = article.get("title", "") or ""
                description = article.get("description", "") or ""
                combined    = f"{title}. {description}"

                for ticker in batch:
                    if ticker.lower() in combined.lower():
                        s = score_text(analyzer, combined)
                        prev = results[ticker]
                        n    = prev["news_count"] + 1
                        # Running average
                        results[ticker]["news_sentiment"] = round(
                            (prev["news_sentiment"] * (n - 1) + s) / n, 4
                        )
                        results[ticker]["news_count"] = n

            processed += len(batch)
            # Respect rate limits
            time.sleep(0.5)

        except Exception as e:
            print(f"[fetch-sentiment] NewsAPI error (batch {batch}): {e}")
            time.sleep(2)

    print(f"[fetch-sentiment] NewsAPI: scored {processed} tickers")
    return results


# ---------------------------------------------------------------------------
# Phase A-2: Reddit sentiment
# ---------------------------------------------------------------------------

def fetch_reddit_sentiment(tickers: list[str], analyzer) -> dict[str, dict]:
    """
    Fetch Reddit mentions from r/wallstreetbets, r/stocks, r/investing.
    Uses PRAW if credentials are available, otherwise RSS fallback.
    Returns {ticker: {"reddit_mentions": int, "reddit_sentiment": float}}.
    """
    results = {t: {"reddit_mentions": 0, "reddit_sentiment": 0.0} for t in tickers}
    ticker_set = set(tickers)

    # Build a set of strings to search for (both "$TICK" and "TICK" patterns)
    search_patterns = {t: [f"${t}", t] for t in tickers}

    if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
        results = _reddit_praw(tickers, ticker_set, search_patterns, analyzer, results)
    else:
        results = _reddit_rss(tickers, ticker_set, search_patterns, analyzer, results)

    return results


def _reddit_praw(tickers, ticker_set, search_patterns, analyzer, results):
    try:
        import praw
    except ImportError:
        print("[fetch-sentiment] praw not installed — using RSS fallback for Reddit.")
        return _reddit_rss(tickers, ticker_set, search_patterns, analyzer, results)

    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            check_for_async=False,
        )
        for sub_name in REDDIT_SUBS:
            sub = reddit.subreddit(sub_name)
            for post in sub.new(limit=500):
                text = f"{post.title} {post.selftext}"
                _score_reddit_text(text, ticker_set, search_patterns, analyzer, results)
            time.sleep(0.5)
        print(f"[fetch-sentiment] Reddit (PRAW): fetched from {REDDIT_SUBS}")
    except Exception as e:
        print(f"[fetch-sentiment] PRAW error: {e} — trying RSS fallback")
        results = _reddit_rss(tickers, ticker_set, search_patterns, analyzer, results)
    return results


def _reddit_rss(tickers, ticker_set, search_patterns, analyzer, results):
    """RSS feed fallback — no auth required."""
    try:
        import requests
        import xml.etree.ElementTree as ET
    except ImportError:
        print("[fetch-sentiment] 'requests' not available — skipping Reddit.")
        return results

    for sub_name in REDDIT_SUBS:
        try:
            url  = f"https://www.reddit.com/r/{sub_name}/new.json?limit=100"
            resp = requests.get(
                url,
                headers={"User-Agent": REDDIT_USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for post_wrap in posts:
                post = post_wrap.get("data", {})
                text = f"{post.get('title', '')} {post.get('selftext', '')}"
                _score_reddit_text(text, ticker_set, search_patterns, analyzer, results)
            time.sleep(1.0)   # be polite to Reddit
        except Exception as e:
            print(f"[fetch-sentiment] Reddit RSS error ({sub_name}): {e}")

    print(f"[fetch-sentiment] Reddit (RSS): fetched from {REDDIT_SUBS}")
    return results


def _score_reddit_text(text, ticker_set, search_patterns, analyzer, results):
    text_upper = text.upper()
    for ticker in ticker_set:
        for pat in search_patterns.get(ticker, [ticker]):
            if pat.upper() in text_upper:
                s = score_text(analyzer, text)
                prev = results[ticker]
                n = prev["reddit_mentions"] + 1
                results[ticker]["reddit_sentiment"] = round(
                    (prev["reddit_sentiment"] * (n - 1) + s) / n, 4
                )
                results[ticker]["reddit_mentions"] = n
                break


# ---------------------------------------------------------------------------
# Phase A-3: SEC EDGAR 8-K filing count
# ---------------------------------------------------------------------------

def fetch_sec_filing_counts(tickers: list[str]) -> dict[str, int]:
    """
    Count 8-K filings in the past 7 days per ticker from SEC EDGAR full-text search.
    Returns {ticker: filing_count}.
    """
    results = {t: 0 for t in tickers}

    try:
        import requests
    except ImportError:
        print("[fetch-sentiment] 'requests' not installed — skipping SEC filings.")
        return results

    # First fetch CIK map from EDGAR company_tickers.json (free, no auth)
    cik_map: dict[str, str] = {}
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": SEC_USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        for entry in raw.values():
            sym = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if sym and cik:
                cik_map[sym] = cik
        print(f"[fetch-sentiment] SEC EDGAR: loaded {len(cik_map)} CIK mappings")
    except Exception as e:
        print(f"[fetch-sentiment] Could not load CIK map: {e}")
        return results

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=7)

    # Query submissions endpoint for each ticker
    fetched = 0
    for ticker in tickers:
        cik = cik_map.get(ticker)
        if not cik:
            continue
        try:
            url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            resp = requests.get(
                url,
                headers={"User-Agent": SEC_USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
            sub_data = resp.json()

            recent = sub_data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])

            count = 0
            for form, filing_date in zip(forms, dates):
                if form in ("8-K", "8-K/A", "NT 10-K", "NT 10-Q"):
                    try:
                        filing_dt = datetime.fromisoformat(filing_date).replace(
                            tzinfo=timezone.utc
                        )
                        if filing_dt >= cutoff_dt:
                            count += 1
                    except ValueError:
                        pass

            results[ticker] = count
            fetched += 1
            # SEC asks for no more than 10 req/sec
            time.sleep(0.15)

        except Exception as e:
            # Non-fatal — just log and continue
            if fetched < 5:   # only log first few errors to avoid log spam
                print(f"[fetch-sentiment] SEC EDGAR error ({ticker}): {e}")
            time.sleep(0.5)

    print(f"[fetch-sentiment] SEC EDGAR: fetched filings for {fetched}/{len(tickers)} tickers")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    SENTIMENT_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    out_path  = SENTIMENT_DIR / f"{today_str}.json"

    print("=" * 60)
    print(f"[fetch-sentiment] Fetching sentiment for {today_str}")
    print("=" * 60)

    # Load tickers
    tickers = load_tickers()
    print(f"[fetch-sentiment] Loaded {len(tickers)} tickers")

    # Initialize VADER
    analyzer = _get_vader()

    # Fetch all three sources
    print("\n[1/3] Fetching NewsAPI sentiment...")
    news_data = fetch_news_sentiment(tickers, analyzer)

    print("\n[2/3] Fetching Reddit sentiment...")
    reddit_data = fetch_reddit_sentiment(tickers, analyzer)

    print("\n[3/3] Fetching SEC EDGAR filing counts...")
    sec_data = fetch_sec_filing_counts(tickers)

    # Merge into output dict
    ticker_results = {}
    for ticker in tickers:
        nd = news_data.get(ticker, {"news_sentiment": 0.0, "news_count": 0})
        rd = reddit_data.get(ticker, {"reddit_mentions": 0, "reddit_sentiment": 0.0})
        sc = sec_data.get(ticker, 0)

        ticker_results[ticker] = {
            "news_sentiment":   nd["news_sentiment"],
            "news_count":       nd["news_count"],
            "reddit_mentions":  rd["reddit_mentions"],
            "reddit_sentiment": rd["reddit_sentiment"],
            "sec_filings_7d":   sc,
        }

    # Write output
    output = {
        "date":        today_str,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {
            "newsapi":  bool(NEWSAPI_KEY),
            "reddit":   True,
            "sec_edgar": True,
        },
        "tickers": ticker_results,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    covered = sum(1 for v in ticker_results.values() if any([
        v["news_count"] > 0,
        v["reddit_mentions"] > 0,
        v["sec_filings_7d"] > 0,
    ]))
    print(f"\n[fetch-sentiment] Done. {covered}/{len(tickers)} tickers have at least one signal.")
    print(f"[fetch-sentiment] Output: {out_path}")


if __name__ == "__main__":
    main()
