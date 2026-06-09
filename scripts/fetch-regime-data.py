"""Fetch and persist market-regime data (GDELT tone + macro merge cache).

Outputs:
  data/regime/gdelt_timeline.json
  data/regime/timeline.json   (merged panel for train-predictor-v3)

Run nightly after fetch-macro.py. GDELT is rate-limited (~1 req / 5s).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from data_sources import fetch_gdelt_daily_tone  # noqa: E402
from regime_features import REGIME_FEATURE_COLS, write_timeline_cache  # noqa: E402

REGIME_DIR = REPO / "data" / "regime"
GDELT_PATH = REGIME_DIR / "gdelt_timeline.json"
LOOKBACK_DAYS = int(os.getenv("REGIME_GDELT_LOOKBACK_DAYS", "365") or "365")
CHUNK_DAYS = int(os.getenv("REGIME_GDELT_CHUNK_DAYS", "30") or "30")
GDELT_SLEEP = float(os.getenv("REGIME_GDELT_SLEEP_SECS", "6.0") or "6.0")


def _normalize_tone(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    tones = [float(r.get("avgTone", 0.0) or 0.0) for r in rows]
    counts = [float(r.get("articleCount", 0.0) or 0.0) for r in rows]
    t_min, t_max = min(tones), max(tones)
    t_rng = max(t_max - t_min, 1e-6)
    c_mean = sum(counts) / max(len(counts), 1)
    c_std = max((sum((c - c_mean) ** 2 for c in counts) / max(len(counts), 1)) ** 0.5, 1e-6)

    out: list[dict] = []
    prev_norm: float | None = None
    window: list[float] = []
    for i, r in enumerate(rows):
        d = r["date"]
        norm = (tones[i] - t_min) / t_rng
        window.append(norm)
        if len(window) > 5:
            window.pop(0)
        delta_5d = norm - (sum(window[:-1]) / max(len(window) - 1, 1)) if len(window) > 1 else 0.0
        article_z = (counts[i] - c_mean) / c_std
        out.append(
            {
                "date": d,
                "avgTone": round(tones[i], 4),
                "articleCount": int(counts[i]),
                "gdelt_tone_norm": round(norm, 4),
                "gdelt_tone_delta_5d": round(delta_5d, 4),
                "gdelt_article_z": round(article_z, 4),
            }
        )
        prev_norm = norm
    return out


def fetch_gdelt_history() -> list[dict]:
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    merged: dict[str, dict] = {}
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
        print(f"[fetch-regime] GDELT {cursor} -> {chunk_end}", flush=True)
        rows = fetch_gdelt_daily_tone(cursor, chunk_end)
        for r in rows:
            merged[r["date"]] = r
        cursor = chunk_end + timedelta(days=1)
        if cursor <= end:
            time.sleep(GDELT_SLEEP)
    ordered = [merged[k] for k in sorted(merged.keys())]
    return _normalize_tone(ordered)


def main() -> int:
    REGIME_DIR.mkdir(parents=True, exist_ok=True)
    print("[fetch-regime] Fetching GDELT daily tone…", flush=True)
    gdelt_rows = fetch_gdelt_history()
    doc = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookbackDays": LOOKBACK_DAYS,
        "rowCount": len(gdelt_rows),
        "rows": gdelt_rows,
    }
    GDELT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[fetch-regime] Wrote {GDELT_PATH} ({len(gdelt_rows)} rows)", flush=True)

    cache_path = write_timeline_cache()
    print(f"[fetch-regime] Merged timeline -> {cache_path}", flush=True)
    print(f"[fetch-regime] Feature columns: {REGIME_FEATURE_COLS}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
