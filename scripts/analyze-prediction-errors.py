"""
analyze-prediction-errors.py — Phase E: Automated Prediction Error Analysis

Reads the last N days of accuracy data and prediction files to surface
systematic patterns in misses. Outputs a structured JSON report that the
GitHub Copilot agent workflow uses to open a GitHub Issue.

Output: data/accuracy/miss-analysis-YYYY-MM-DD.json
  {
    "analysisDate": "...",
    "windowDays": 7,
    "overallHitRate": 0.548,
    "totalPredictions": 1240,
    "totalCorrect": 680,
    "sectorMisses": {
      "Energy": {"hitRate": 0.41, "total": 44, "correct": 18, "flag": "UNDERPERFORMING"},
      ...
    },
    "confidenceBucketAnalysis": [
      {"bucket": "high (>0.6)", "hitRate": 0.62, "total": 200, "correct": 124},
      ...
    ],
    "topMissPatterns": [
      "Energy sector significantly underperforming (41% vs 55% overall) — consider regime filter",
      "High-confidence predictions not outperforming base rate — calibration may be needed",
      ...
    ],
    "evTopN": {
      "n": 20,
      "hitRate": 0.71,
      "total": 140,
      "correct": 99
    }
  }

Run weekly (Monday mornings) via .github/workflows/analyze-misses.yml.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR      = Path(__file__).resolve().parent
REPO_ROOT       = SCRIPT_DIR.parent
ACCURACY_DIR    = REPO_ROOT / "data" / "accuracy"
PREDICTIONS_DIR = REPO_ROOT / "data" / "predictions"
ACCURACY_LOG    = ACCURACY_DIR / "accuracy-log.json"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANALYSIS_WINDOW_DAYS = 7     # look back this many days
UNDERPERFORM_THRESH  = 0.05  # flag a sector if its hit rate is this much below overall
EV_TOP_N             = 20    # evaluate EV-filtered top N predictions per day


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_recent_accuracy_entries(window_days: int) -> list[dict]:
    """Load accuracy log entries from the past window_days days."""
    if not ACCURACY_LOG.exists():
        print(f"[analyze-errors] Accuracy log not found: {ACCURACY_LOG}")
        return []

    with open(ACCURACY_LOG) as f:
        log = json.load(f)

    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    entries = [
        e for e in log.get("entries", [])
        if e.get("date", "") >= cutoff and e.get("hitRate") is not None
    ]
    return entries


def load_recent_accuracy_reports(window_days: int) -> list[dict]:
    """Load per-day accuracy report files from data/accuracy/YYYY-MM-DD.json."""
    reports = []
    cutoff  = date.today() - timedelta(days=window_days)

    for fpath in sorted(ACCURACY_DIR.glob("*.json")):
        if fpath.stem == "accuracy-log" or fpath.name.startswith("miss-analysis"):
            continue
        try:
            report_date = date.fromisoformat(fpath.stem)
        except ValueError:
            continue
        if report_date < cutoff:
            continue
        try:
            with open(fpath) as f:
                reports.append(json.load(f))
        except Exception as e:
            print(f"[analyze-errors] WARN: could not read {fpath}: {e}")

    return reports


def load_recent_predictions(window_days: int) -> list[dict]:
    """Load all individual scored predictions from recent daily reports."""
    reports  = load_recent_accuracy_reports(window_days)
    all_preds: list[dict] = []
    for report in reports:
        detail = report.get("detail", [])
        date_str = report.get("date", "")
        for pred in detail:
            pred_copy = dict(pred)
            pred_copy["_report_date"] = date_str
            all_preds.append(pred_copy)
    return all_preds


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def sector_analysis(predictions: list[dict], overall_hit_rate: float) -> dict:
    """Compute per-sector hit rates and flag underperforming sectors."""
    sectors: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})

    for pred in predictions:
        sector = pred.get("sector") or pred.get("ticker", "UNKNOWN")[:3]
        sectors[sector]["total"]   += 1
        sectors[sector]["correct"] += int(pred.get("correct", 0))

    result = {}
    for sec, counts in sectors.items():
        total, correct = counts["total"], counts["correct"]
        if total < 5:
            continue
        hr = round(correct / total, 4)
        flag = "OK"
        if hr < overall_hit_rate - UNDERPERFORM_THRESH:
            flag = "UNDERPERFORMING"
        elif hr > overall_hit_rate + UNDERPERFORM_THRESH:
            flag = "OUTPERFORMING"

        result[sec] = {
            "hitRate": hr,
            "total":   total,
            "correct": correct,
            "flag":    flag,
        }

    return dict(sorted(result.items(), key=lambda x: x[1]["hitRate"]))


def confidence_bucket_analysis(predictions: list[dict]) -> list[dict]:
    """Break predictions into confidence buckets and compute hit rates per bucket."""
    buckets = {
        "low (<0.3)":    {"min": 0.0, "max": 0.3, "total": 0, "correct": 0},
        "medium (0.3-0.5)": {"min": 0.3, "max": 0.5, "total": 0, "correct": 0},
        "high (>0.5)":   {"min": 0.5, "max": 1.01, "total": 0, "correct": 0},
    }

    for pred in predictions:
        conf = float(pred.get("confidence", 0.5) or 0.5)
        correct = int(pred.get("correct", 0))
        for bucket_name, b in buckets.items():
            if b["min"] <= conf < b["max"]:
                b["total"]   += 1
                b["correct"] += correct
                break

    result = []
    for bucket_name, b in buckets.items():
        if b["total"] == 0:
            continue
        result.append({
            "bucket":  bucket_name,
            "hitRate": round(b["correct"] / b["total"], 4),
            "total":   b["total"],
            "correct": b["correct"],
        })
    return result


def ev_top_n_analysis(predictions: list[dict], n_per_day: int) -> dict:
    """
    Group predictions by report date, take top-N by EV (or confidence),
    compute hit rate on that high-conviction subset.
    """
    by_date: dict[str, list[dict]] = defaultdict(list)
    for pred in predictions:
        by_date[pred.get("_report_date", "")].append(pred)

    total   = 0
    correct = 0

    for day_preds in by_date.values():
        # Sort by EV if available, else by confidence (higher = better)
        sorted_preds = sorted(
            day_preds,
            key=lambda p: float(p.get("ev", p.get("confidence", 0.0)) or 0.0),
            reverse=True,
        )
        top = sorted_preds[:n_per_day]
        total   += len(top)
        correct += sum(int(p.get("correct", 0)) for p in top)

    return {
        "n":       n_per_day,
        "hitRate": round(correct / total, 4) if total > 0 else None,
        "total":   total,
        "correct": correct,
    }


def build_miss_patterns(
    overall_hit_rate: float,
    sector_data: dict,
    confidence_data: list[dict],
    ev_data: dict,
) -> list[str]:
    """Generate human-readable pattern strings for the GitHub Issue."""
    patterns = []

    # Sector underperformers
    for sec, data in sector_data.items():
        if data["flag"] == "UNDERPERFORMING":
            patterns.append(
                f"{sec} sector significantly underperforming "
                f"({data['hitRate']:.0%} vs {overall_hit_rate:.0%} overall) "
                f"— n={data['total']}. Consider regime-conditional filtering."
            )

    # Confidence calibration check
    for bucket in confidence_data:
        if "high" in bucket["bucket"] and bucket["hitRate"] is not None:
            if bucket["hitRate"] < overall_hit_rate + 0.03 and bucket["total"] > 20:
                patterns.append(
                    f"High-confidence predictions ({bucket['bucket']}) not outperforming "
                    f"base rate ({bucket['hitRate']:.0%} vs {overall_hit_rate:.0%} overall). "
                    f"Platt calibration or threshold tuning recommended."
                )

    # EV filter value
    ev_hr = ev_data.get("hitRate")
    if ev_hr is not None and ev_data["total"] > 10:
        if ev_hr > overall_hit_rate + 0.05:
            patterns.append(
                f"Top-{ev_data['n']} EV predictions achieve {ev_hr:.0%} hit rate "
                f"(vs {overall_hit_rate:.0%} overall). "
                f"EV-filtered trading signal is working well."
            )
        else:
            patterns.append(
                f"Top-{ev_data['n']} EV predictions ({ev_hr:.0%}) not beating overall "
                f"({overall_hit_rate:.0%}). EV scoring needs review."
            )

    if not patterns:
        patterns.append(
            f"No significant systematic patterns detected this week. "
            f"Overall hit rate: {overall_hit_rate:.0%}. Model performing normally."
        )

    return patterns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ACCURACY_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    out_path  = ACCURACY_DIR / f"miss-analysis-{today_str}.json"

    print("=" * 60)
    print(f"[analyze-errors] Running miss analysis for past {ANALYSIS_WINDOW_DAYS} days")
    print("=" * 60)

    # Load data
    log_entries  = load_recent_accuracy_entries(ANALYSIS_WINDOW_DAYS)
    predictions  = load_recent_predictions(ANALYSIS_WINDOW_DAYS)

    if not log_entries and not predictions:
        print("[analyze-errors] No accuracy data found for the past week. Exiting.")
        output = {
            "analysisDate": today_str,
            "windowDays":   ANALYSIS_WINDOW_DAYS,
            "error":        "No accuracy data available for analysis window.",
        }
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        sys.exit(0)

    # Overall metrics
    total_preds   = sum(int(e.get("total", 0) or 0) for e in log_entries)
    total_correct = sum(int(e.get("correct", 0) or 0) for e in log_entries)
    overall_hr    = round(total_correct / total_preds, 4) if total_preds > 0 else 0.0

    print(f"[analyze-errors] Overall: {total_correct}/{total_preds} = {overall_hr:.1%}")

    # Per-sector analysis (from detail records)
    sector_data     = sector_analysis(predictions, overall_hr)
    confidence_data = confidence_bucket_analysis(predictions)
    ev_data         = ev_top_n_analysis(predictions, EV_TOP_N)
    patterns        = build_miss_patterns(overall_hr, sector_data, confidence_data, ev_data)

    # Log entries summary
    daily_rates = [
        {"date": e["date"], "hitRate": e["hitRate"], "total": e.get("total", 0)}
        for e in log_entries
    ]

    output = {
        "analysisDate":            today_str,
        "generatedAt":             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windowDays":              ANALYSIS_WINDOW_DAYS,
        "overallHitRate":          overall_hr,
        "totalPredictions":        total_preds,
        "totalCorrect":            total_correct,
        "dailyRates":              daily_rates,
        "sectorMisses":            sector_data,
        "confidenceBucketAnalysis": confidence_data,
        "evTopN":                  ev_data,
        "topMissPatterns":         patterns,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n[analyze-errors] Patterns found:")
    for p in patterns:
        print(f"  • {p}")

    print(f"\n[analyze-errors] Report written to {out_path}")


if __name__ == "__main__":
    main()
