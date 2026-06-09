"""
score-accuracy.py — Server-Side Accuracy Scoring

Loads yesterday's predictions from data/predictions/, fetches today's actual
close prices from data/historical/ (or via yfinance if not yet available),
computes accuracy metrics, and writes results to data/accuracy/.

Outputs:
  data/accuracy/YYYY-MM-DD.json     — Daily accuracy report
  data/accuracy/accuracy-log.json   — Updated rolling metrics (7/30/90-day)

Run daily after market close, after fetch-history.py has completed
(see .github/workflows/accuracy.yml).
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT       = os.path.join(SCRIPT_DIR, "..")
HISTORICAL_DIR  = os.path.join(REPO_ROOT, "data", "historical")
PREDICTIONS_DIR = os.path.join(REPO_ROOT, "data", "predictions")
ACCURACY_DIR    = os.path.join(REPO_ROOT, "data", "accuracy")
ACCURACY_LOG    = os.path.join(ACCURACY_DIR, "accuracy-log.json")
TICKERS_PATH    = os.path.join(REPO_ROOT, "data", "tickers", "us_tickers.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prev_trading_day(from_date: date) -> date:
    """Return the most recent weekday before from_date."""
    d = from_date - timedelta(days=1)
    while d.weekday() >= 5:   # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def load_ticker_sectors() -> dict[str, str]:
    """
    Build a ticker → sector map.

    Prefer deriving sectors from data/historical/*.json because those files
    already encode sector membership by filename. Fall back to
    data/tickers/us_tickers.json only if no historical mapping can be built.
    Returns an empty dict if neither source is available or usable.
    """
    historical_sectors = {}
    if os.path.isdir(HISTORICAL_DIR):
        try:
            sector_files = [
                f for f in os.listdir(HISTORICAL_DIR)
                if f.endswith(".json") and f != "manifest.json"
            ]
            for filename in sector_files:
                sector_file = os.path.join(HISTORICAL_DIR, filename)
                with open(sector_file) as f:
                    sector_data = json.load(f)

                sector_name = os.path.splitext(filename)[0].replace("-", " ").replace("_", " ").title()
                for ticker in sector_data.get("stocks", {}).keys():
                    historical_sectors[ticker] = sector_name

            if historical_sectors:
                return historical_sectors
        except Exception as e:
            print(f"[score-accuracy] Could not derive ticker sectors from historical files: {e}")

    if not os.path.exists(TICKERS_PATH):
        return {}

    try:
        with open(TICKERS_PATH) as f:
            data = json.load(f)

        fallback_sectors = {}
        for ticker_info in data.get("tickers", []):
            symbol = ticker_info.get("symbol")
            sector = ticker_info.get("sector")
            if symbol and sector and sector != "Other":
                fallback_sectors[symbol] = sector
        return fallback_sectors
    except Exception as e:
        print(f"[score-accuracy] Could not load ticker sectors: {e}")
        return {}


def load_predictions(pred_date_str: str) -> dict | None:
    """Load prediction file for a given date string (YYYY-MM-DD)."""
    path = os.path.join(PREDICTIONS_DIR, f"{pred_date_str}.json")
    if not os.path.exists(path):
        print(f"[score-accuracy] No predictions file for {pred_date_str}: {path}")
        return None
    with open(path) as f:
        return json.load(f)


def load_actual_prices(price_date_str: str) -> dict[str, float]:
    """
    Load actual close prices for a given date from data/historical/ sector files.
    Returns a dict of {ticker: closePrice}.
    """
    prices = {}

    sector_files = [
        os.path.join(HISTORICAL_DIR, f)
        for f in os.listdir(HISTORICAL_DIR)
        if f.endswith(".json") and f != "manifest.json"
    ]

    for sector_file in sector_files:
        with open(sector_file) as f:
            sector_data = json.load(f)

        for ticker, info in sector_data.get("stocks", {}).items():
            for candle in reversed(info.get("candles", [])):
                if candle.get("date") == price_date_str:
                    prices[ticker] = float(candle["close"])
                    break

    return prices


def fetch_actual_prices_yfinance(tickers: list[str], price_date_str: str) -> dict[str, float]:
    """
    Fall back to yfinance to fetch close prices for tickers not found in historical data.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[score-accuracy] yfinance not available; skipping live price fetch.")
        return {}

    if not tickers:
        return {}

    print(f"[score-accuracy] Fetching {len(tickers)} tickers from yfinance for {price_date_str}…")
    prices = {}

    # Batch download
    d_start = price_date_str
    d_end   = (date.fromisoformat(price_date_str) + timedelta(days=1)).isoformat()

    try:
        raw = yf.download(tickers, start=d_start, end=d_end, progress=False, auto_adjust=True)
        if "Close" in raw.columns:
            for ticker in tickers:
                if ticker in raw["Close"].columns:
                    series = raw["Close"][ticker].dropna()
                    if not series.empty:
                        prices[ticker] = float(series.iloc[-1])
    except Exception as e:
        print(f"[score-accuracy] yfinance batch download failed: {e}")

    return prices


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(scored: list[dict]) -> dict:
    """
    Given a list of scored prediction dicts (each with 'correct', 'ticker',
    'sector', 'confidence', 'probability'), compute aggregate accuracy metrics.
    """
    if not scored:
        return {"hitRate": None, "total": 0, "correct": 0}

    total   = len(scored)
    correct = sum(1 for s in scored if s["correct"])
    hit_rate = round(correct / total, 4) if total > 0 else None

    # Confidence-weighted accuracy (predictions with higher confidence should be right more)
    conf_total = sum(s.get("confidence", 0.5) for s in scored)
    conf_weighted = (
        sum(s.get("confidence", 0.5) * int(s["correct"]) for s in scored) / conf_total
        if conf_total > 0 else None
    )

    # Per-sector metrics
    sectors: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for s in scored:
        sec = s.get("sector", "unknown")
        sectors[sec]["total"]   += 1
        sectors[sec]["correct"] += s["correct"]
    sector_metrics = {
        sec: {
            "hitRate": round(v["correct"] / v["total"], 4),
            "total":   v["total"],
            "correct": v["correct"],
        }
        for sec, v in sectors.items() if v["total"] > 0
    }

    reg_abs_errors = [
        abs(float(s.get("predictedReturn", 0.0)) - float(s.get("actualReturn", 0.0)))
        for s in scored
        if s.get("predictedReturn") is not None and s.get("actualReturn") is not None
    ]
    regression_mae = round(sum(reg_abs_errors) / len(reg_abs_errors), 6) if reg_abs_errors else None

    # Phase D: top-20 EV hit rate (the high-conviction subset)
    ev_top_n_metrics = _compute_ev_top_n_metrics(scored, n=20)

    return {
        "hitRate":               hit_rate,
        "confidenceWeightedHitRate": round(conf_weighted, 4) if conf_weighted is not None else None,
        "regressionMAE":         regression_mae,
        "total":                 total,
        "correct":               correct,
        "bySector":              sector_metrics,
        "evTop20":               ev_top_n_metrics,
    }


def _compute_ev_top_n_metrics(scored: list[dict], n: int = 20) -> dict:
    """
    Sort scored predictions by EV (expected value) descending and compute
    hit rate for the top-N subset. Falls back to confidence if EV not present.
    """
    sorted_by_ev = sorted(
        scored,
        key=lambda s: float(s.get("ev", s.get("confidence", 0.0)) or 0.0),
        reverse=True,
    )
    top_n = sorted_by_ev[:n]
    if not top_n:
        return {"n": n, "hitRate": None, "total": 0, "correct": 0}

    correct = sum(1 for s in top_n if s["correct"])
    return {
        "n":       n,
        "hitRate": round(correct / len(top_n), 4),
        "total":   len(top_n),
        "correct": correct,
    }


# ---------------------------------------------------------------------------
# Rolling accuracy log
# ---------------------------------------------------------------------------

def update_accuracy_log(new_entry: dict) -> None:
    """Append a daily entry to accuracy-log.json and recompute rolling windows."""
    os.makedirs(ACCURACY_DIR, exist_ok=True)

    if os.path.exists(ACCURACY_LOG):
        with open(ACCURACY_LOG) as f:
            log_data = json.load(f)
    else:
        log_data = {"entries": []}

    entries = log_data.get("entries", [])

    # Deduplicate by date
    entries = [e for e in entries if e.get("date") != new_entry["date"]]
    entries.append(new_entry)

    # Keep last 365 entries
    entries = sorted(entries, key=lambda e: e.get("date", ""))[-365:]
    log_data["entries"] = entries

    # Compute rolling windows using weighted totals where available.
    def rolling_hit_rate(days: int) -> float | None:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        window = [
            e for e in entries
            if e.get("date", "") >= cutoff and e.get("hitRate") is not None
        ]
        if not window:
            return None

        weighted_total = sum(int(e.get("total", 0) or 0) for e in window)
        weighted_correct = sum(int(e.get("correct", 0) or 0) for e in window)
        if weighted_total > 0:
            return round(weighted_correct / weighted_total, 4)

        return round(sum(float(e["hitRate"]) for e in window) / len(window), 4)

    log_data["rolling"] = {
        "7day":  rolling_hit_rate(7),
        "30day": rolling_hit_rate(30),
        "90day": rolling_hit_rate(90),
    }
    log_data["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(ACCURACY_LOG, "w") as f:
        json.dump(log_data, f, indent=2)

    print(f"[score-accuracy] Updated accuracy-log.json ({len(entries)} entries)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(ACCURACY_DIR, exist_ok=True)

    # Control detail payload size for downstream diagnostics.
    # 0 means full detail (recommended for robust error analysis).
    try:
        max_detail_rows = int(os.getenv("MAX_DETAIL_ROWS", "0") or 0)
    except Exception:
        max_detail_rows = 0

    today      = date.today()
    score_date = prev_trading_day(today)  # yesterday's trading day

    # Prediction file was generated for score_date (predictionFor = today)
    # We look for a predictions file dated score_date - 1 trading day
    pred_date = prev_trading_day(score_date)

    print(f"[score-accuracy] Scoring predictions for {score_date} (generated on {pred_date})")

    # 1. Load prediction file
    pred_data = load_predictions(pred_date.isoformat())
    if pred_data is None:
        print("[score-accuracy] No prediction file found. Exiting.")
        sys.exit(0)

    predictions = pred_data.get("predictions", {})
    prediction_for = pred_data.get("predictionFor", score_date.isoformat())

    if not predictions:
        print("[score-accuracy] Prediction file is empty. Exiting.")
        sys.exit(0)

    print(f"[score-accuracy] Loaded {len(predictions)} predictions (for {prediction_for})")

    # 1b. Load ticker → sector map
    ticker_sectors = load_ticker_sectors()
    print(f"[score-accuracy] Loaded {len(ticker_sectors)} ticker sector mappings")

    # 2. Load actual close prices for prediction_for date
    actual_prices = load_actual_prices(prediction_for)
    print(f"[score-accuracy] Found {len(actual_prices)} actual prices in historical data")

    # Also load previous-day closes once to avoid repeatedly scanning all sector files.
    pred_date_close_map = load_actual_prices(pred_date.isoformat())
    print(f"[score-accuracy] Found {len(pred_date_close_map)} previous closes for {pred_date}")

    # 3. Fill missing prices via yfinance
    missing = [t for t in predictions if t not in actual_prices]
    if missing:
        live = fetch_actual_prices_yfinance(missing, prediction_for)
        actual_prices.update(live)
        print(f"[score-accuracy] Fetched {len(live)} additional prices from yfinance")

    # 4. Score predictions
    scored = []
    no_actual = []

    for ticker, pred in predictions.items():
        actual = actual_prices.get(ticker)
        if actual is None:
            no_actual.append(ticker)
            continue

        # Direction is UP if actual > the day-before close.
        # We approximate "current price at prediction time" as the close on pred_date.
        # Load that from historical data to be precise, but fall back to using
        # a simple heuristic (probability > 0.5 → UP prediction).
        predicted_dir  = pred.get("direction", "UP")
        probability    = pred.get("probability", 0.5)
        confidence     = pred.get("confidence", 0.5)
        predicted_return = pred.get("predictedReturn")

        # Use preloaded previous-day closes to avoid O(tickers * sector_files) scans.
        pred_date_close = pred_date_close_map.get(ticker)

        if pred_date_close is None:
            no_actual.append(ticker)
            continue

        actual_dir = "UP" if actual > pred_date_close else "DOWN"
        correct    = predicted_dir == actual_dir
        actual_return = (actual - pred_date_close) / pred_date_close if pred_date_close else None
        regression_abs_error = (
            abs(float(predicted_return) - float(actual_return))
            if predicted_return is not None and actual_return is not None
            else None
        )

        scored.append({
            "ticker":      ticker,
            "sector":      ticker_sectors.get(ticker, "Other"),
            "correct":     int(correct),
            "predicted":   predicted_dir,
            "actual":      actual_dir,
            "probability": probability,
            "confidence":  confidence,
            "predictedReturn": predicted_return,
            "actualReturn": actual_return,
            "regressionAbsError": regression_abs_error,
            "priceActual": actual,
            "pricePrev":   pred_date_close,
            "ev":          pred.get("ev"),
            "ensembleStd": pred.get("ensembleStd"),
        })

    print(f"[score-accuracy] Scored {len(scored)} predictions ({len(no_actual)} missing actual prices)")

    # 5. Compute metrics
    metrics = compute_metrics(scored)
    print(f"[score-accuracy] Hit rate: {metrics['hitRate']} ({metrics['correct']}/{metrics['total']})")

    # 6. Write daily accuracy report
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = {
        "date":          score_date.isoformat(),
        "predictionFor": prediction_for,
        "scoredAt":      now_utc,
        "modelVersion":  pred_data.get("modelVersion", "unknown"),
        "metrics":       metrics,
        "detail":        (scored[:max_detail_rows] if max_detail_rows > 0 else scored),
        "detailRows":    (min(len(scored), max_detail_rows) if max_detail_rows > 0 else len(scored)),
        "detailTruncated": bool(max_detail_rows > 0 and len(scored) > max_detail_rows),
    }

    report_path = os.path.join(ACCURACY_DIR, f"{score_date.isoformat()}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[score-accuracy] Wrote report: {report_path}")

    # 7. Update rolling accuracy log
    log_entry = {
        "date":         score_date.isoformat(),
        "recordedAt":   now_utc,
        "modelVersion": pred_data.get("modelVersion", "unknown"),
        "hitRate":      metrics["hitRate"],
        "regressionMAE": metrics.get("regressionMAE"),
        "total":        metrics["total"],
        "correct":      metrics["correct"],
        "rolling7day":  None,   # computed by update_accuracy_log
        "rolling30day": None,
    }
    update_accuracy_log(log_entry)

    # 8. Summary
    print()
    print("=" * 60)
    print("[score-accuracy] DONE")
    print(f"  Scored date  : {score_date}")
    print(f"  Predictions  : {metrics['total']}")
    print(f"  Correct      : {metrics['correct']}")
    print(f"  Hit rate     : {metrics['hitRate']}")
    print(f"  Missing data : {len(no_actual)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
