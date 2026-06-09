"""Enrich the investor decisions JSON with per-symbol news sentiment.

Pipeline:
  1. Load `data/investor_v3/decisions.json`.
  2. Find unique symbols across the last N days that have picks.
  3. Fetch recent headlines from Yahoo Finance RSS (no API key needed).
  4. Score each headline with the ONNX FinBERT encoder (NPU/QNN when available).
  5. Aggregate per symbol: mean score, label distribution, top headlines.
  6. Attach a `sentiment` object to each pick in those days.
  7. Write the file back atomically.

Usage:
    python scripts/enrich_decisions.py                  # default: last 10 days
    python scripts/enrich_decisions.py --last-days 30
    python scripts/enrich_decisions.py --max-headlines 8 --workers 8
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DECISIONS_PATH = ROOT / "data" / "investor_v3" / "decisions.json"
CACHE_PATH = ROOT / "data" / "sentiment" / "per_symbol.json"

RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
USER_AGENT = "Mozilla/5.0 (compatible; Nostradamus/1.0)"

_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_PUBDATE_RE = re.compile(r"<pubDate>(.*?)</pubDate>", re.DOTALL | re.IGNORECASE)
_LINK_RE = re.compile(r"<link>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def _strip_cdata(s: str) -> str:
    m = _CDATA_RE.search(s)
    return (m.group(1) if m else s).strip()


def fetch_headlines(symbol: str, max_headlines: int = 6, timeout: float = 8.0) -> list[dict]:
    """Yahoo Finance RSS — public, no key, ~6 headlines per ticker."""
    url = RSS_URL.format(symbol=symbol)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            xml = r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return []
    items = []
    for chunk in _ITEM_RE.findall(xml)[:max_headlines]:
        t = _TITLE_RE.search(chunk)
        p = _PUBDATE_RE.search(chunk)
        l = _LINK_RE.search(chunk)
        if not t:
            continue
        title = unescape(_strip_cdata(t.group(1)))
        # The first <item> in Yahoo RSS is sometimes a duplicate of the feed
        # title — skip if it equals the symbol verbatim.
        if title.strip().lower() in {symbol.lower(), f"{symbol.lower()} news"}:
            continue
        link = unescape(_strip_cdata(l.group(1))) if l else None
        items.append({
            "title": title,
            "published": unescape(_strip_cdata(p.group(1))) if p else None,
            "url": link or None,
        })
    return items


def collect_symbols(decisions: dict, last_days: int) -> tuple[list[str], list[dict]]:
    """Return unique symbols + the day-records they appear in (last N days with picks)."""
    days = decisions.get("days") or []
    days_with_picks = [d for d in days if d.get("picks")]
    target_days = days_with_picks[-last_days:] if last_days > 0 else days_with_picks
    syms: dict[str, None] = {}
    for d in target_days:
        for p in (d.get("picks") or []):
            sym = p.get("symbol")
            if sym:
                syms.setdefault(sym, None)
    return list(syms.keys()), target_days


def aggregate(results: list) -> dict:
    """Per-symbol summary from a list of (headline, score, label, proba) dicts."""
    if not results:
        return {
            "score": 0.0,
            "label": "neutral",
            "n_headlines": 0,
            "distribution": {"positive": 0.0, "negative": 0.0, "neutral": 1.0},
            "headlines": [],
        }
    scores = [r["score"] for r in results]
    mean = sum(scores) / len(scores)
    dist = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    for r in results:
        dist[r["label"]] = dist.get(r["label"], 0.0) + 1.0
    total = sum(dist.values()) or 1.0
    dist = {k: round(v / total, 3) for k, v in dist.items()}
    if mean > 0.15:
        label = "positive"
    elif mean < -0.15:
        label = "negative"
    else:
        label = "neutral"
    return {
        "score": round(mean, 4),
        "label": label,
        "n_headlines": len(results),
        "distribution": dist,
        "headlines": [
            {"title": r["headline"], "label": r["label"], "score": round(r["score"], 3)}
            for r in results
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last-days", type=int, default=10, help="enrich picks from the last N days that have picks (default 10)")
    ap.add_argument("--max-headlines", type=int, default=6, help="max headlines per symbol")
    ap.add_argument("--workers", type=int, default=8, help="parallel RSS fetchers")
    ap.add_argument("--dry-run", action="store_true", help="don't write decisions.json back")
    args = ap.parse_args()

    if not DECISIONS_PATH.exists():
        sys.exit(f"missing {DECISIONS_PATH}")

    print(f"[enrich] loading {DECISIONS_PATH.relative_to(ROOT)}", flush=True)
    decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    symbols, target_days = collect_symbols(decisions, args.last_days)
    if not symbols:
        sys.exit("no symbols to enrich (no picks in selected window)")
    print(f"[enrich] {len(symbols)} unique symbols across {len(target_days)} days", flush=True)

    # 1. Fetch headlines in parallel
    t0 = time.perf_counter()
    headlines_by_symbol: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_headlines, s, args.max_headlines): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                headlines_by_symbol[sym] = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[enrich] {sym}: fetch failed: {e}", flush=True)
                headlines_by_symbol[sym] = []
    fetch_ms = (time.perf_counter() - t0) * 1000
    total_headlines = sum(len(v) for v in headlines_by_symbol.values())
    covered = sum(1 for v in headlines_by_symbol.values() if v)
    print(f"[enrich] fetched {total_headlines} headlines for {covered}/{len(symbols)} symbols in {fetch_ms:.0f} ms", flush=True)

    # 2. Score all headlines in a single batch (FinBERT is happiest with big batches)
    from sentiment_encoder import SentimentEncoder

    enc = SentimentEncoder()
    flat: list[tuple[str, str]] = []
    for sym, items in headlines_by_symbol.items():
        for it in items:
            flat.append((sym, it["title"]))
    print(f"[enrich] scoring {len(flat)} headlines via FinBERT...", flush=True)
    t0 = time.perf_counter()
    scored = enc.score([h for _, h in flat])
    score_ms = (time.perf_counter() - t0) * 1000
    print(f"[enrich] scored in {score_ms:.0f} ms ({score_ms/max(1,len(flat)):.1f} ms/headline, provider={enc.active_provider})", flush=True)

    # 3. Aggregate per symbol
    per_symbol: dict[str, list] = {s: [] for s in symbols}
    for (sym, _), r in zip(flat, scored):
        per_symbol[sym].append({
            "headline": r.headline,
            "label": r.label,
            "score": r.score,
            "proba": r.proba,
        })
    summaries = {sym: aggregate(per_symbol[sym]) for sym in symbols}

    # Cache per-symbol summary for inspection / other scripts
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "yahoo_finance_rss",
        "encoder": "FinBERT-ONNX",
        "provider": enc.active_provider,
        "symbols": summaries,
    }, indent=2))
    print(f"[enrich] wrote {CACHE_PATH.relative_to(ROOT)}", flush=True)

    # 4. Attach to picks in target days
    attached = 0
    for d in target_days:
        for p in (d.get("picks") or []):
            sym = p.get("symbol")
            if sym and sym in summaries:
                p["sentiment"] = summaries[sym]
                attached += 1
    print(f"[enrich] attached sentiment to {attached} picks", flush=True)

    if args.dry_run:
        print("[enrich] dry-run: not writing decisions.json", flush=True)
        return

    # Atomic write
    tmp = DECISIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(decisions, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, DECISIONS_PATH)
    print(f"[enrich] updated {DECISIONS_PATH.relative_to(ROOT)} ({DECISIONS_PATH.stat().st_size/1024:.0f} KiB)", flush=True)


if __name__ == "__main__":
    main()
