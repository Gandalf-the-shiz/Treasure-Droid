#!/usr/bin/env python3
"""
scripts/generate-weekly-report.py
Weekly Intelligence Report Generator — Phase 10.

Reads:
  - Latest predictions from data/predictions/
  - Accuracy log from data/accuracy/accuracy-log.json
  - Model metadata from models/v2/metadata.json

Generates data/reports/weekly/YYYY-WW.json with:
  - Top 10 bullish / bearish picks
  - Sector rotation summary
  - Model performance (7d, 30d, 90d rolling)
  - Confidence distribution

Run automatically by .github/workflows/weekly-report.yml every Sunday at 5 AM UTC.
Can also be run manually: python scripts/generate-weekly-report.py
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# ─── Paths ────────────────────────────────────────────────────

PREDICTIONS_DIR  = Path("data/predictions")
ACCURACY_LOG     = Path("data/accuracy/accuracy-log.json")
MODEL_METADATA   = Path("models/v2/metadata.json")
MODEL_PREV_METADATA = Path("models/v2/metadata_prev.json")
REPORTS_DIR      = Path("data/reports/weekly")
ACCURACY_DIR     = Path("data/accuracy")
MACRO_REGIME_PATH = Path("data/macro/current-regime.json")
FUNDAMENTALS_DIR = Path("data/fundamentals")
HISTORICAL_DIR   = Path("data/historical")

# ─── Sector lookup ─────────────────────────────────────────────

# Stock symbol → GICS sector mapping (abbreviated — add more as needed)
SECTOR_LOOKUP = {
    "AAPL":  "Technology",    "GOOGL": "Technology",   "MSFT":  "Technology",
    "AMZN":  "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "META":  "Technology",    "NVDA":  "Technology",   "NFLX":  "Communication Services",
    "JPM":   "Financials",    "V":     "Financials",   "JNJ":   "Healthcare",
    "PFE":   "Healthcare",    "XOM":   "Energy",       "CVX":   "Energy",
    "GS":    "Financials",    "BAC":   "Financials",   "WMT":   "Consumer Staples",
    "KO":    "Consumer Staples", "DIS": "Communication Services", "BA": "Industrials",
}

# ─── Helpers ───────────────────────────────────────────────────

def iso_week_label(dt: datetime) -> str:
    """Return 'YYYY-Www' ISO week label, e.g. '2026-W15'."""
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def load_predictions() -> list[dict]:
    """Load and normalise prediction rows from data/predictions/."""
    preds = []
    if not PREDICTIONS_DIR.exists():
        return preds

    for fpath in sorted(PREDICTIONS_DIR.glob("*.json")):
        try:
            with open(fpath) as f:
                data = json.load(f)

            file_generated_at = None
            if isinstance(data, dict):
                file_generated_at = data.get("generatedAt")

            # Support both list payloads and {predictions: ...} payloads.
            payload = data.get("predictions") if isinstance(data, dict) else data
            if isinstance(payload, dict):
                for symbol, pred in payload.items():
                    if not isinstance(pred, dict):
                        continue
                    row = {
                        "symbol": symbol,
                        "probability": pred.get("probability", 0.5),
                        "confidence": pred.get("confidence", abs(float(pred.get("probability", 0.5)) - 0.5) * 2),
                        "direction": pred.get("direction", "UP" if float(pred.get("probability", 0.5)) >= 0.5 else "DOWN"),
                        "generatedAt": pred.get("generatedAt") or file_generated_at,
                        "ev": pred.get("ev"),
                        "ensembleStd": pred.get("ensembleStd"),
                    }
                    preds.append(row)
            elif isinstance(payload, list):
                for pred in payload:
                    if not isinstance(pred, dict):
                        continue
                    sym = pred.get("symbol")
                    if not sym:
                        continue
                    row = {
                        "symbol": sym,
                        "probability": pred.get("probability", 0.5),
                        "confidence": pred.get("confidence", abs(float(pred.get("probability", 0.5)) - 0.5) * 2),
                        "direction": pred.get("direction", "UP" if float(pred.get("probability", 0.5)) >= 0.5 else "DOWN"),
                        "generatedAt": pred.get("generatedAt") or file_generated_at,
                        "ev": pred.get("ev"),
                        "ensembleStd": pred.get("ensembleStd"),
                    }
                    preds.append(row)
        except Exception as e:
            print(f"  Warning: could not read {fpath}: {e}", file=sys.stderr)

    return preds


def load_accuracy_log() -> list[dict]:
    try:
        with open(ACCURACY_LOG) as f:
            data = json.load(f)
        return data.get("entries", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"  Warning: could not read accuracy log: {e}", file=sys.stderr)
        return []


def load_model_metadata() -> dict:
    try:
        with open(MODEL_METADATA) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  Warning: could not read model metadata: {e}", file=sys.stderr)
        return {}


def load_prev_model_metadata() -> dict:
    try:
        with open(MODEL_PREV_METADATA) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  Warning: could not read previous model metadata: {e}", file=sys.stderr)
        return {}


def load_macro_regime() -> str:
    """Return current macro regime (BULL/BEAR/HIGH_VOL/SIDEWAYS/UNKNOWN)."""
    try:
        with open(MACRO_REGIME_PATH) as f:
            data = json.load(f)
        regime = str(data.get("regime", "UNKNOWN")).upper()
        return regime if regime else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def load_latest_fundamentals() -> dict[str, dict]:
    """Load latest fundamentals snapshot as {ticker: {...}}."""
    try:
        files = sorted(
            f for f in FUNDAMENTALS_DIR.glob("*.json")
            if f.name != ".gitkeep"
        )
        if not files:
            return {}
        with files[-1].open() as f:
            payload = json.load(f)
        tickers = payload.get("tickers") or {}
        return tickers if isinstance(tickers, dict) else {}
    except Exception:
        return {}


def load_recent_volume_spike_map() -> dict[str, float]:
    """
    Build {ticker: volume_spike_ratio} from latest candle data when available.
    Ratio = last_volume / average(previous 20 volumes).
    """
    spikes: dict[str, float] = {}
    if not HISTORICAL_DIR.exists():
        return spikes

    try:
        sector_files = sorted(
            f for f in HISTORICAL_DIR.glob("*.json")
            if f.name != "manifest.json"
        )
    except Exception:
        return spikes

    for fpath in sector_files:
        try:
            with fpath.open() as f:
                payload = json.load(f)
            stocks = payload.get("stocks") or {}
            if not isinstance(stocks, dict):
                continue
            for ticker, info in stocks.items():
                candles = (info or {}).get("candles") or []
                if len(candles) < 25:
                    continue
                try:
                    vols = [float(c.get("volume", 0) or 0) for c in candles]
                except Exception:
                    continue
                tail = vols[-21:]
                prev20 = tail[:-1]
                last = tail[-1]
                denom = sum(prev20) / len(prev20) if prev20 else 0.0
                if denom > 0:
                    spikes[ticker] = round(last / denom, 4)
        except Exception:
            continue

    return spikes


def load_previous_weekly_reports(current_week: str, limit: int = 12) -> list[dict]:
    """Load prior weekly report payloads excluding the current week."""
    if not REPORTS_DIR.exists():
        return []

    out = []
    files = sorted(
        f for f in REPORTS_DIR.glob("*.json")
        if f.name != ".gitkeep"
    )
    for fpath in files:
        if fpath.stem == current_week:
            continue
        try:
            with fpath.open() as f:
                out.append(json.load(f))
        except Exception:
            continue
    return out[-limit:]


def _safe_mean(values: list[float], default: float = 0.0) -> float:
    return (sum(values) / len(values)) if values else default


def _safe_std(values: list[float], default: float = 1.0) -> float:
    if len(values) < 2:
        return default
    m = _safe_mean(values, 0.0)
    var = sum((x - m) ** 2 for x in values) / len(values)
    std = math.sqrt(var)
    return std if std > 1e-9 else default


def _zscore(value: float, population: list[float], default_std: float = 1.0) -> float:
    m = _safe_mean(population, 0.0)
    s = _safe_std(population, default_std)
    return (value - m) / s


def regime_thresholds(regime: str) -> dict:
    """Dynamic alert thresholds by regime (more tolerant in high-vol regimes)."""
    regime = (regime or "UNKNOWN").upper()
    table = {
        "BULL": {"minHitRate30d": 0.54, "maxEce": 0.10},
        "SIDEWAYS": {"minHitRate30d": 0.52, "maxEce": 0.12},
        "BEAR": {"minHitRate30d": 0.50, "maxEce": 0.14},
        "HIGH_VOL": {"minHitRate30d": 0.48, "maxEce": 0.16},
        "UNKNOWN": {"minHitRate30d": 0.52, "maxEce": 0.12},
    }
    return table.get(regime, table["UNKNOWN"])


def activity_thresholds(regime: str) -> dict:
    """Regime-aware thresholds specifically for unusual-flow scanners."""
    regime = (regime or "UNKNOWN").upper()
    table = {
        "BULL": {"unusualHighScore": 0.60, "forwardHighScore": 0.62, "minDisplayScore": 0.30},
        "SIDEWAYS": {"unusualHighScore": 0.55, "forwardHighScore": 0.60, "minDisplayScore": 0.28},
        "BEAR": {"unusualHighScore": 0.52, "forwardHighScore": 0.57, "minDisplayScore": 0.26},
        "HIGH_VOL": {"unusualHighScore": 0.50, "forwardHighScore": 0.55, "minDisplayScore": 0.24},
        "UNKNOWN": {"unusualHighScore": 0.55, "forwardHighScore": 0.60, "minDisplayScore": 0.28},
    }
    return table.get(regime, table["UNKNOWN"])


def _recent_signal_index(prior_reports: list[dict], section: str) -> dict[str, dict]:
    """
    Build recent signal memory by ticker from prior reports.
    section: 'topSignals' or 'forwardWatchlist'.
    """
    idx: dict[str, dict] = {}
    for rpt in prior_reports[-3:]:
        mas = rpt.get("marketActivitySignals") or {}
        if section == "topSignals":
            rows = mas.get("topSignals") or []
        else:
            rows = ((mas.get("forwardWatchlist") or {}).get("topWatchlist") or [])
        for row in rows:
            t = row.get("ticker")
            if not t:
                continue
            prev = idx.get(t, {"count": 0, "lastScore": None, "lastPattern": None})
            prev["count"] += 1
            prev["lastScore"] = row.get("score")
            prev["lastPattern"] = row.get("pattern")
            idx[t] = prev
    return idx


def champion_challenger_summary(champion_meta: dict, challenger_meta: dict) -> dict:
    """Compare current model metadata with previous model metadata."""
    if not champion_meta:
        return {
            "available": False,
            "reason": "Current model metadata unavailable.",
        }
    if not challenger_meta:
        return {
            "available": False,
            "reason": "Previous model metadata unavailable.",
        }

    ch_test = champion_meta.get("testMetrics") or {}
    cl_test = challenger_meta.get("testMetrics") or {}

    def _f(x):
        try:
            return float(x)
        except Exception:
            return None

    ch_acc = _f(ch_test.get("accuracy"))
    cl_acc = _f(cl_test.get("accuracy"))
    ch_auc = _f(ch_test.get("auc"))
    cl_auc = _f(cl_test.get("auc"))

    acc_delta = None if ch_acc is None or cl_acc is None else round(ch_acc - cl_acc, 4)
    auc_delta = None if ch_auc is None or cl_auc is None else round(ch_auc - cl_auc, 4)

    verdict = "unchanged"
    if acc_delta is not None and auc_delta is not None:
        if acc_delta > 0 and auc_delta >= 0:
            verdict = "champion_better"
        elif acc_delta < 0 and auc_delta <= 0:
            verdict = "challenger_better"

    return {
        "available": True,
        "champion": {
            "version": champion_meta.get("version"),
            "trainedAt": champion_meta.get("trainedAt"),
            "testMetrics": ch_test,
        },
        "challenger": {
            "version": challenger_meta.get("version"),
            "trainedAt": challenger_meta.get("trainedAt"),
            "testMetrics": cl_test,
        },
        "delta": {
            "accuracy": acc_delta,
            "auc": auc_delta,
        },
        "verdict": verdict,
    }


def load_recent_accuracy_details(window_days: int = 7) -> list[dict]:
    """Load scored prediction detail rows from recent daily accuracy reports."""
    if not ACCURACY_DIR.exists():
        return []

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=window_days)
    rows: list[dict] = []
    candidate_files: list[Path] = []

    for fpath in sorted(ACCURACY_DIR.glob("*.json")):
        if fpath.name in {"accuracy-log.json"} or fpath.name.startswith("miss-analysis") or fpath.name.startswith("walk-forward"):
            continue

        try:
            report_date = datetime.fromisoformat(fpath.stem).date()
        except ValueError:
            continue
        if report_date < cutoff:
            continue

        candidate_files.append(fpath)

    # If recent window is empty (e.g., sparse updates), use latest available reports.
    if not candidate_files:
        all_daily: list[Path] = []
        for fpath in sorted(ACCURACY_DIR.glob("*.json")):
            if fpath.name in {"accuracy-log.json"} or fpath.name.startswith("miss-analysis") or fpath.name.startswith("walk-forward"):
                continue
            try:
                datetime.fromisoformat(fpath.stem)
            except ValueError:
                continue
            all_daily.append(fpath)
        candidate_files = all_daily[-5:]

    for fpath in candidate_files:
        try:
            with open(fpath) as f:
                report = json.load(f)
            for d in report.get("detail", []):
                if isinstance(d, dict):
                    row = dict(d)
                    row["_date"] = report.get("date") or fpath.stem
                    rows.append(row)
        except Exception as e:
            print(f"  Warning: could not read detail from {fpath}: {e}", file=sys.stderr)

    return rows


def calibration_summary(scored_rows: list[dict], bins: int = 10) -> dict:
    """Compute calibration metrics: Brier score, log-loss, ECE, and per-bin stats."""
    records = []
    for r in scored_rows:
        p = r.get("probability")
        y = r.get("correct")
        if p is None or y is None:
            continue
        try:
            p = float(p)
            y = int(y)
        except Exception:
            continue
        p = max(1e-6, min(1 - 1e-6, p))
        y = 1 if y else 0
        records.append((p, y))

    if not records:
        return {
            "sampleSize": 0,
            "brier": None,
            "logLoss": None,
            "ece": None,
            "bins": [],
        }

    n = len(records)
    brier = sum((p - y) ** 2 for p, y in records) / n
    log_loss = -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in records) / n

    bucket_payload = []
    ece = 0.0
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        members = [(p, y) for p, y in records if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not members:
            continue
        count = len(members)
        mean_p = sum(p for p, _ in members) / count
        mean_y = sum(y for _, y in members) / count
        gap = abs(mean_p - mean_y)
        ece += (count / n) * gap
        bucket_payload.append({
            "range": f"{int(lo*100)}-{int(hi*100)}",
            "count": count,
            "avgProbability": round(mean_p, 4),
            "hitRate": round(mean_y, 4),
            "gap": round(gap, 4),
        })

    return {
        "sampleSize": n,
        "brier": round(brier, 6),
        "logLoss": round(log_loss, 6),
        "ece": round(ece, 6),
        "bins": bucket_payload,
    }


def decision_quality_summary(scored_rows: list[dict], top_n: int = 50) -> dict:
    """Compute EV-oriented decision quality metrics from scored rows."""
    ev_rows = []
    for r in scored_rows:
        if r.get("ev") is None or r.get("correct") is None:
            continue
        try:
            ev = float(r.get("ev"))
            correct = int(r.get("correct"))
        except Exception:
            continue
        ev_rows.append((ev, correct))

    if not ev_rows:
        return {
            "sampleSize": 0,
            "positiveEv": None,
            "topN": None,
        }

    positive = [(ev, c) for ev, c in ev_rows if ev > 0]
    pos_summary = None
    if positive:
        pos_summary = {
            "count": len(positive),
            "avgEv": round(sum(ev for ev, _ in positive) / len(positive), 6),
            "hitRate": round(sum(c for _, c in positive) / len(positive), 4),
        }

    ranked = sorted(ev_rows, key=lambda x: x[0], reverse=True)
    top = ranked[: min(top_n, len(ranked))]
    top_summary = {
        "n": len(top),
        "avgEv": round(sum(ev for ev, _ in top) / len(top), 6),
        "hitRate": round(sum(c for _, c in top) / len(top), 4),
    }

    return {
        "sampleSize": len(ev_rows),
        "positiveEv": pos_summary,
        "topN": top_summary,
    }


def portfolio_proxy_summary(scored_rows: list[dict]) -> dict:
    """
    Compute simple portfolio-level proxies from scored rows.
    Uses sign(actualReturn) based on predicted direction as per-row strategy return.
    """
    pnl = []
    for r in scored_rows:
        actual_ret = r.get("actualReturn")
        direction = str(r.get("predicted", "")).upper()
        if actual_ret is None or direction not in {"UP", "DOWN"}:
            continue
        try:
            ar = float(actual_ret)
        except Exception:
            continue
        sign = 1.0 if direction == "UP" else -1.0
        pnl.append(sign * ar)

    if not pnl:
        return {
            "sampleSize": 0,
            "avgReturn": None,
            "volatility": None,
            "sharpeLike": None,
            "winRate": None,
            "maxDrawdown": None,
        }

    n = len(pnl)
    avg = sum(pnl) / n
    var = sum((x - avg) ** 2 for x in pnl) / n
    vol = math.sqrt(var)
    sharpe_like = (avg / vol) if vol > 0 else None
    win_rate = sum(1 for x in pnl if x > 0) / n

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in pnl:
        equity *= (1 + r)
        if equity > peak:
            peak = equity
        dd = 1 - (equity / peak)
        if dd > max_dd:
            max_dd = dd

    return {
        "sampleSize": n,
        "avgReturn": round(avg, 6),
        "volatility": round(vol, 6),
        "sharpeLike": round(sharpe_like, 6) if sharpe_like is not None else None,
        "winRate": round(win_rate, 4),
        "maxDrawdown": round(max_dd, 6),
    }


def unusual_activity_signals(
    preds_list: list[dict],
    scored_rows: list[dict],
    fundamentals_map: dict[str, dict],
    volume_spike_map: dict[str, float],
    regime: str,
    prior_reports: list[dict],
    top_n: int = 25,
) -> dict:
    """
    Heuristic scan for unusual trading patterns that may indicate large-player flow.
    This is a statistical screening signal, not a legal determination of insider trading.
    """
    th = activity_thresholds(regime)
    if not scored_rows:
        return {
            "method": "heuristic_flow_scan_v1",
            "disclaimer": "Statistical screening only. Not evidence of unlawful insider trading.",
            "thresholds": th,
            "sampleSize": 0,
            "topSignals": [],
            "summary": {
                "highIntensityCount": 0,
                "avgScore": None,
                "volumeCoverage": 0,
            },
        }

    # Latest prediction by symbol for EV/confidence context.
    pred_by_symbol = {p.get("symbol"): p for p in preds_list if p.get("symbol")}

    # Keep latest scored row per ticker.
    latest_by_ticker: dict[str, dict] = {}
    for row in scored_rows:
        ticker = row.get("ticker") or row.get("symbol")
        if not ticker:
            continue
        d = row.get("_date", "")
        prev = latest_by_ticker.get(ticker)
        if prev is None or str(d) > str(prev.get("_date", "")):
            latest_by_ticker[ticker] = row

    # Build historical distributions per ticker and per sector.
    ticker_ret_hist: dict[str, list[float]] = defaultdict(list)
    ticker_err_hist: dict[str, list[float]] = defaultdict(list)
    sector_ret_hist: dict[str, list[float]] = defaultdict(list)
    sector_err_hist: dict[str, list[float]] = defaultdict(list)

    for r in scored_rows:
        ticker = r.get("ticker") or r.get("symbol")
        if not ticker:
            continue
        sector = SECTOR_LOOKUP.get(ticker, r.get("sector", "Other"))
        try:
            ret = abs(float(r.get("actualReturn", 0.0) or 0.0))
            err = abs(float(r.get("regressionAbsError", 0.0) or 0.0))
        except Exception:
            continue
        ticker_ret_hist[ticker].append(ret)
        ticker_err_hist[ticker].append(err)
        sector_ret_hist[sector].append(ret)
        sector_err_hist[sector].append(err)

    latest_rows = list(latest_by_ticker.values())
    abs_returns = [abs(float(r.get("actualReturn", 0.0) or 0.0)) for r in latest_rows]
    abs_errors = [abs(float(r.get("regressionAbsError", 0.0) or 0.0)) for r in latest_rows]
    mean_abs_ret = _safe_mean(abs_returns, 0.01)
    mean_abs_err = _safe_mean(abs_errors, 0.01)

    recent_idx = _recent_signal_index(prior_reports, section="topSignals")
    signals = []
    for r in latest_rows:
        ticker = r.get("ticker") or r.get("symbol")
        if not ticker:
            continue

        sector = SECTOR_LOOKUP.get(ticker, r.get("sector", "Other"))

        actual_ret = float(r.get("actualReturn", 0.0) or 0.0)
        reg_err = abs(float(r.get("regressionAbsError", 0.0) or 0.0))
        pred = pred_by_symbol.get(ticker, {})
        ev = float(pred.get("ev", r.get("ev", 0.0)) or 0.0)
        conf = float(pred.get("confidence", r.get("confidence", 0.0)) or 0.0)
        vol_spike = float(volume_spike_map.get(ticker, 1.0) or 1.0)

        f = fundamentals_map.get(ticker, {}) if isinstance(fundamentals_map, dict) else {}
        insider_ratio = float(f.get("insider_buy_ratio_30d", 0.5) or 0.5)
        put_call = float(f.get("put_call_ratio", 1.0) or 1.0)
        earnings_days = int(f.get("earnings_days_to", 60) or 60)

        # Global baselines
        ret_spike_global = min(abs(actual_ret) / max(1e-6, mean_abs_ret * 2.5), 2.0) / 2.0
        dislocation_global = min(reg_err / max(1e-6, mean_abs_err * 2.5), 2.0) / 2.0

        # Ticker-relative and sector-relative normalization (z-score to [0,1]).
        ticker_ret_z = _zscore(abs(actual_ret), ticker_ret_hist.get(ticker, []), default_std=max(mean_abs_ret, 1e-3))
        ticker_err_z = _zscore(reg_err, ticker_err_hist.get(ticker, []), default_std=max(mean_abs_err, 1e-3))
        sector_ret_z = _zscore(abs(actual_ret), sector_ret_hist.get(sector, []), default_std=max(mean_abs_ret, 1e-3))
        sector_err_z = _zscore(reg_err, sector_err_hist.get(sector, []), default_std=max(mean_abs_err, 1e-3))

        ret_spike_ticker = min(max((ticker_ret_z + 3) / 6, 0.0), 1.0)
        ret_spike_sector = min(max((sector_ret_z + 3) / 6, 0.0), 1.0)
        dislocation_ticker = min(max((ticker_err_z + 3) / 6, 0.0), 1.0)
        dislocation_sector = min(max((sector_err_z + 3) / 6, 0.0), 1.0)

        ret_spike = 0.30 * ret_spike_global + 0.35 * ret_spike_ticker + 0.35 * ret_spike_sector
        dislocation = 0.30 * dislocation_global + 0.35 * dislocation_ticker + 0.35 * dislocation_sector
        flow_conviction = min(abs(ev) / 0.01, 1.0)
        conf_extreme = min(conf / 0.8, 1.0)
        insider_bias = min(abs(insider_ratio - 0.5) * 2, 1.0)
        options_pressure = min(abs(math.log(max(1e-6, put_call))), 1.5) / 1.5
        volume_pressure = min(max(vol_spike - 1.0, 0.0) / 2.0, 1.0)

        event_proximity = 1.0 if earnings_days <= 5 else (0.5 if earnings_days <= 10 else 0.0)

        score_raw = (
            0.28 * ret_spike +
            0.20 * dislocation +
            0.12 * flow_conviction +
            0.10 * conf_extreme +
            0.12 * insider_bias +
            0.10 * options_pressure +
            0.06 * volume_pressure +
            0.02 * event_proximity
        )

        if actual_ret > 0 and (insider_ratio > 0.55 or put_call < 0.9):
            pattern = "possible_accumulation"
        elif actual_ret < 0 and (insider_ratio < 0.45 or put_call > 1.1):
            pattern = "possible_distribution"
        else:
            pattern = "unusual_flow"

        # Cooldown/de-dup: penalize repeated low-novelty signals from recent weeks.
        mem = recent_idx.get(ticker)
        cooldown = False
        novelty = 1.0
        score = score_raw
        if mem:
            prev_score = float(mem.get("lastScore") or score_raw)
            prev_pattern = str(mem.get("lastPattern") or "")
            novelty = min(abs(score_raw - prev_score) / 0.08, 1.0)
            if pattern != prev_pattern:
                novelty = min(1.0, novelty + 0.35)
            repeated = int(mem.get("count", 0) or 0)
            if repeated >= 2 and novelty < 0.35:
                cooldown = True
                score -= 0.12
            elif repeated >= 1 and novelty < 0.25:
                score -= 0.06

        score = max(0.0, min(1.0, score))

        # Short explanation list for why this ticker was flagged.
        reasons = []
        if ret_spike_ticker >= 0.75 or ret_spike_sector >= 0.75:
            reasons.append("return anomaly vs ticker/sector baseline")
        if dislocation_ticker >= 0.75 or dislocation_sector >= 0.75:
            reasons.append("model-vs-market dislocation spike")
        if abs(ev) >= 0.006:
            reasons.append("high expected-value conviction")
        if volume_pressure >= 0.5:
            reasons.append("recent abnormal volume pressure")
        if insider_bias >= 0.4:
            reasons.append("insider-trading ratio bias")
        if options_pressure >= 0.4:
            reasons.append("options put/call pressure")
        if event_proximity >= 0.5:
            reasons.append("near-term earnings event proximity")
        if not reasons:
            reasons.append("multi-factor moderate anomaly")
        if cooldown:
            reasons.append("cooldown applied for repeated low-novelty signal")

        signals.append({
            "ticker": ticker,
            "score": round(score, 4),
            "scoreRaw": round(score_raw, 4),
            "novelty": round(novelty, 4),
            "cooldown": cooldown,
            "pattern": pattern,
            "sector": sector,
            "actualReturn": round(actual_ret, 6),
            "regressionDislocation": round(reg_err, 6),
            "returnZTicker": round(ticker_ret_z, 4),
            "returnZSector": round(sector_ret_z, 4),
            "dislocationZTicker": round(ticker_err_z, 4),
            "dislocationZSector": round(sector_err_z, 4),
            "ev": round(ev, 6),
            "confidence": round(conf, 4),
            "volumeSpikeRatio": round(vol_spike, 4),
            "insiderBuyRatio30d": round(insider_ratio, 4),
            "putCallRatio": round(put_call, 4),
            "earningsDaysTo": earnings_days,
            "reasons": reasons,
        })

    # Filter very weak scores and then apply sector-balanced ranking so 'Other'
    # does not dominate all output slots.
    signals = [s for s in signals if s["score"] >= th["minDisplayScore"]]
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for s in signals:
        by_sector[s.get("sector", "Other")].append(s)
    for sec in by_sector:
        by_sector[sec].sort(key=lambda x: x["score"], reverse=True)

    # Quotas: cap Other and maintain broad sector coverage.
    other_cap = max(6, int(top_n * 0.35))
    default_cap = max(2, int(top_n * 0.20))
    picked = []
    sector_picked = defaultdict(int)

    # Round-robin pass for diversity.
    sectors_order = sorted(by_sector.keys(), key=lambda s: (0 if s != "Other" else 1, s))
    advanced = True
    while len(picked) < top_n and advanced:
        advanced = False
        for sec in sectors_order:
            cap = other_cap if sec == "Other" else default_cap
            if sector_picked[sec] >= cap:
                continue
            bucket = by_sector.get(sec, [])
            if not bucket:
                continue
            picked.append(bucket.pop(0))
            sector_picked[sec] += 1
            advanced = True
            if len(picked) >= top_n:
                break

    # Fill leftovers by global score while respecting hard Other cap.
    if len(picked) < top_n:
        leftovers = []
        for sec, bucket in by_sector.items():
            leftovers.extend(bucket)
        leftovers.sort(key=lambda x: x["score"], reverse=True)
        for s in leftovers:
            sec = s.get("sector", "Other")
            cap = other_cap if sec == "Other" else top_n
            if sector_picked[sec] >= cap:
                continue
            picked.append(s)
            sector_picked[sec] += 1
            if len(picked) >= top_n:
                break

    top = picked[: min(top_n, len(picked))]

    high_intensity = sum(1 for s in signals if s["score"] >= th["unusualHighScore"])
    vol_coverage = sum(1 for s in signals if s.get("volumeSpikeRatio", 1.0) != 1.0)
    avg_score = (sum(s["score"] for s in signals) / len(signals)) if signals else None

    return {
        "method": "heuristic_flow_scan_v1",
        "disclaimer": "Statistical screening only. Not evidence of unlawful insider trading.",
        "thresholds": th,
        "sampleSize": len(signals),
        "topSignals": top,
        "summary": {
            "highIntensityCount": high_intensity,
            "avgScore": round(avg_score, 4) if avg_score is not None else None,
            "volumeCoverage": vol_coverage,
            "sectorPicked": dict(sector_picked),
        },
    }


def forward_big_player_watchlist(
    preds_list: list[dict],
    fundamentals_map: dict[str, dict],
    volume_spike_map: dict[str, float],
    regime: str,
    prior_reports: list[dict],
    top_n: int = 20,
) -> dict:
    """
    Forward-looking heuristic that scores likely near-term large-player activity.
    Uses model conviction, EV, options/fundamentals, and volume pressure.
    """
    th = activity_thresholds(regime)
    recent_idx = _recent_signal_index(prior_reports, section="forwardWatchlist")
    rows = []
    for p in preds_list:
        ticker = p.get("symbol")
        if not ticker:
            continue

        direction = str(p.get("direction", "UP")).upper()
        confidence = float(p.get("confidence", 0.0) or 0.0)
        ev = float(p.get("ev", 0.0) or 0.0)
        prob = float(p.get("probability", 0.5) or 0.5)
        ensemble_std = float(p.get("ensembleStd", 0.0) or 0.0)

        f = fundamentals_map.get(ticker, {}) if isinstance(fundamentals_map, dict) else {}
        insider_ratio = float(f.get("insider_buy_ratio_30d", 0.5) or 0.5)
        put_call = float(f.get("put_call_ratio", 1.0) or 1.0)
        earnings_days = int(f.get("earnings_days_to", 60) or 60)

        vol_spike = float(volume_spike_map.get(ticker, 1.0) or 1.0)

        ev_strength = min(abs(ev) / 0.01, 1.0)
        conf_strength = min(confidence / 0.8, 1.0)
        insider_bias = min(abs(insider_ratio - 0.5) * 2, 1.0)
        options_pressure = min(abs(math.log(max(1e-6, put_call))), 1.5) / 1.5
        volume_pressure = min(max(vol_spike - 1.0, 0.0) / 2.0, 1.0)
        uncertainty_penalty = min(ensemble_std / 0.08, 1.0)

        event_proximity = 1.0 if earnings_days <= 5 else (0.5 if earnings_days <= 10 else 0.0)

        score_raw = (
            0.28 * ev_strength +
            0.24 * conf_strength +
            0.12 * insider_bias +
            0.10 * options_pressure +
            0.12 * volume_pressure +
            0.10 * event_proximity -
            0.08 * uncertainty_penalty
        )

        if direction == "UP" and (insider_ratio >= 0.55 or put_call <= 0.9):
            move_type = "possible_accumulation"
        elif direction == "DOWN" and (insider_ratio <= 0.45 or put_call >= 1.1):
            move_type = "possible_distribution"
        else:
            move_type = "watch_unusual_flow"

        mem = recent_idx.get(ticker)
        novelty = 1.0
        cooldown = False
        score = score_raw
        if mem:
            prev_score = float(mem.get("lastScore") or score_raw)
            prev_pattern = str(mem.get("lastPattern") or "")
            novelty = min(abs(score_raw - prev_score) / 0.08, 1.0)
            if move_type != prev_pattern:
                novelty = min(1.0, novelty + 0.35)
            repeated = int(mem.get("count", 0) or 0)
            if repeated >= 2 and novelty < 0.35:
                cooldown = True
                score -= 0.10
            elif repeated >= 1 and novelty < 0.25:
                score -= 0.05

        score = max(0.0, min(1.0, score))

        if score >= th["forwardHighScore"]:
            window = "next_1_2_sessions"
        elif score >= max(th["forwardHighScore"] - 0.15, 0.40):
            window = "next_1_3_sessions"
        else:
            window = "next_3_5_sessions"

        rows.append({
            "ticker": ticker,
            "score": round(score, 4),
            "scoreRaw": round(score_raw, 4),
            "novelty": round(novelty, 4),
            "cooldown": cooldown,
            "expectedWindow": window,
            "predictedDirection": direction,
            "pattern": move_type,
            "probability": round(prob, 4),
            "confidence": round(confidence, 4),
            "ev": round(ev, 6),
            "ensembleStd": round(ensemble_std, 6),
            "insiderBuyRatio30d": round(insider_ratio, 4),
            "putCallRatio": round(put_call, 4),
            "volumeSpikeRatio": round(vol_spike, 4),
            "earningsDaysTo": earnings_days,
        })

    rows = [r for r in rows if r["score"] >= th["minDisplayScore"]]
    rows.sort(key=lambda x: x["score"], reverse=True)
    top_rows = rows[: min(top_n, len(rows))]
    high_conviction = sum(1 for r in rows if r["score"] >= th["forwardHighScore"])

    return {
        "method": "heuristic_forward_watchlist_v1",
        "thresholds": th,
        "sampleSize": len(rows),
        "highConvictionCount": high_conviction,
        "topWatchlist": top_rows,
    }


def market_signal_tracking(current_activity: dict, prior_reports: list[dict]) -> dict:
    """Track stability/turnover of unusual-flow and forward-watchlist signals."""
    current_top = {
        x.get("ticker")
        for x in (current_activity.get("topSignals") or [])
        if x.get("ticker")
    }
    current_fw = {
        x.get("ticker")
        for x in ((current_activity.get("forwardWatchlist") or {}).get("topWatchlist") or [])
        if x.get("ticker")
    }

    if not prior_reports:
        return {
            "historyWeeks": 0,
            "topSignalsOverlapAvg": None,
            "forwardWatchlistOverlapAvg": None,
            "signalPersistence": {},
            "trend": "insufficient_history",
        }

    overlap_top = []
    overlap_fw = []
    appearances: dict[str, int] = defaultdict(int)

    for rpt in prior_reports:
        mas = rpt.get("marketActivitySignals") or {}
        prev_top = {
            x.get("ticker")
            for x in (mas.get("topSignals") or [])
            if x.get("ticker")
        }
        prev_fw = {
            x.get("ticker")
            for x in ((mas.get("forwardWatchlist") or {}).get("topWatchlist") or [])
            if x.get("ticker")
        }

        for t in prev_top:
            appearances[t] += 1

        if current_top:
            overlap_top.append(len(current_top.intersection(prev_top)) / max(1, len(current_top)))
        if current_fw:
            overlap_fw.append(len(current_fw.intersection(prev_fw)) / max(1, len(current_fw)))

    persistent = {
        t: c for t, c in sorted(appearances.items(), key=lambda kv: kv[1], reverse=True)
        if c >= 2
    }

    avg_top = _safe_mean(overlap_top, 0.0) if overlap_top else None
    avg_fw = _safe_mean(overlap_fw, 0.0) if overlap_fw else None

    if avg_top is None:
        trend = "insufficient_history"
    elif avg_top >= 0.35:
        trend = "stable_signal_regime"
    elif avg_top >= 0.18:
        trend = "moderate_turnover"
    else:
        trend = "high_turnover"

    return {
        "historyWeeks": len(prior_reports),
        "topSignalsOverlapAvg": round(avg_top, 4) if avg_top is not None else None,
        "forwardWatchlistOverlapAvg": round(avg_fw, 4) if avg_fw is not None else None,
        "signalPersistence": dict(list(persistent.items())[:20]),
        "trend": trend,
    }


def forward_watchlist_precision_proxy(prior_reports: list[dict], scored_rows: list[dict]) -> dict:
    """
    Evaluate prior forward watchlist tickers against currently available scored outcomes.
    This is a practical proxy for near-term signal quality.
    """
    if not prior_reports or not scored_rows:
        return {
            "evaluated": False,
            "reason": "Insufficient prior reports or scored outcomes.",
            "sampleSize": 0,
            "hitRate": None,
        }

    # Use latest prior report as the candidate set.
    latest_prior = prior_reports[-1]
    prev_fw = ((latest_prior.get("marketActivitySignals") or {}).get("forwardWatchlist") or {}).get("topWatchlist") or []
    if not prev_fw:
        return {
            "evaluated": False,
            "reason": "No prior forward watchlist entries.",
            "sampleSize": 0,
            "hitRate": None,
        }

    # Latest scored row per ticker.
    latest_scored: dict[str, dict] = {}
    for r in scored_rows:
        t = r.get("ticker") or r.get("symbol")
        if not t:
            continue
        d = str(r.get("_date", ""))
        prev = latest_scored.get(t)
        if prev is None or d > str(prev.get("_date", "")):
            latest_scored[t] = r

    total = 0
    correct = 0
    for entry in prev_fw:
        t = entry.get("ticker")
        expected_dir = str(entry.get("predictedDirection", "")).upper()
        if not t or expected_dir not in {"UP", "DOWN"}:
            continue
        obs = latest_scored.get(t)
        if not obs:
            continue
        actual_ret = obs.get("actualReturn")
        if actual_ret is None:
            continue
        try:
            ar = float(actual_ret)
        except Exception:
            continue
        actual_dir = "UP" if ar > 0 else "DOWN"
        total += 1
        if actual_dir == expected_dir:
            correct += 1

    if total == 0:
        return {
            "evaluated": False,
            "reason": "No overlapping outcomes for prior watchlist tickers.",
            "sampleSize": 0,
            "hitRate": None,
        }

    return {
        "evaluated": True,
        "reason": None,
        "sampleSize": total,
        "hitRate": round(correct / total, 4),
        "correct": correct,
    }


def activity_narratives(activity: dict, top_n: int = 10) -> list[str]:
    """Create concise human-readable narratives for top flagged signals."""
    out = []
    top_signals = (activity.get("topSignals") or [])[:top_n]
    fw_top = ((activity.get("forwardWatchlist") or {}).get("topWatchlist") or [])[: max(1, top_n // 2)]

    for s in top_signals:
        ticker = s.get("ticker")
        if not ticker:
            continue
        reasons = s.get("reasons") or []
        reason_text = "; ".join(reasons[:2]) if reasons else "multi-factor anomaly"
        out.append(
            f"{ticker}: {s.get('pattern')} score={s.get('score')} | {reason_text}."
        )

    for s in fw_top:
        ticker = s.get("ticker")
        if not ticker:
            continue
        out.append(
            f"{ticker}: forward {s.get('pattern')} signal for {s.get('expectedWindow')} "
            f"(score={s.get('score')}, dir={s.get('predictedDirection')})."
        )

    return out


def rolling_performance(entries: list[dict], days: int) -> dict:
    """Compute hit rate over the last `days` calendar days."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    recent = []
    for e in entries:
        try:
            d = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).date()
            if d >= cutoff:
                recent.append(e)
        except Exception:
            pass
    if not recent:
        return {"hitRate": None, "totalPredictions": 0}

    # Prefer weighted aggregation from explicit total/correct counts when present.
    weighted_total = sum(int(e.get("total", 0) or 0) for e in recent)
    weighted_correct = sum(int(e.get("correct", 0) or 0) for e in recent)

    if weighted_total > 0:
        return {
            "hitRate": round(weighted_correct / weighted_total, 4),
            "totalPredictions": weighted_total,
        }

    # Fallback: average daily hitRate values if totals are unavailable.
    daily_rates = [float(e.get("hitRate")) for e in recent if e.get("hitRate") is not None]
    if daily_rates:
        return {
            "hitRate": round(sum(daily_rates) / len(daily_rates), 4),
            "totalPredictions": len(daily_rates),
        }

    # Legacy fallback for boolean per-row records.
    correct = sum(1 for e in recent if e.get("isCorrect", False))
    return {
        "hitRate": round(correct / len(recent), 4),
        "totalPredictions": len(recent),
    }


def confidence_distribution(preds: list[dict]) -> dict:
    """Bucket predictions by confidence band."""
    bands = {"50-60": 0, "60-70": 0, "70-80": 0, "80-90": 0, "90+": 0}
    for p in preds:
        c = p.get("confidence", 0) * 100
        if c >= 90:
            bands["90+"] += 1
        elif c >= 80:
            bands["80-90"] += 1
        elif c >= 70:
            bands["70-80"] += 1
        elif c >= 60:
            bands["60-70"] += 1
        else:
            bands["50-60"] += 1
    return bands


def sector_rotation(preds: list[dict]) -> dict:
    """Aggregate predictions by sector."""
    sector_data: dict[str, list] = defaultdict(list)
    for p in preds:
        symbol = p.get("symbol", "")
        sector = SECTOR_LOOKUP.get(symbol, p.get("sector", "Other"))
        sector_data[sector].append(p)

    result = {}
    for sector, items in sector_data.items():
        probs = [p.get("probability", 0.5) for p in items]
        avg_prob = sum(probs) / len(probs) if probs else 0.5
        sentiment = "bullish" if avg_prob > 0.55 else ("bearish" if avg_prob < 0.45 else "neutral")
        result[sector] = {
            "avgProbability": round(avg_prob, 4),
            "sentiment": sentiment,
            "tickerCount": len(items),
        }

    return dict(sorted(result.items()))


def build_alerts(rolling30: dict, calibration: dict, decision_quality: dict, thresholds: dict, regime: str) -> list[dict]:
    """Generate machine-readable diagnostics to highlight model health risks."""
    alerts = []

    hr30 = rolling30.get("hitRate") if isinstance(rolling30, dict) else None
    min_hr30 = thresholds.get("minHitRate30d", 0.52)
    if hr30 is not None and hr30 < min_hr30:
        alerts.append({
            "severity": "high",
            "code": "LOW_30D_HIT_RATE",
            "message": (
                f"30-day hit rate is weak ({hr30:.2%}) for regime {regime} "
                f"(threshold {min_hr30:.2%})."
            ),
        })

    ece = calibration.get("ece") if isinstance(calibration, dict) else None
    max_ece = thresholds.get("maxEce", 0.12)
    if ece is not None and ece > max_ece:
        alerts.append({
            "severity": "medium",
            "code": "CALIBRATION_DRIFT",
            "message": (
                f"Expected calibration error is elevated ({ece:.3f}) for regime {regime} "
                f"(threshold {max_ece:.3f})."
            ),
        })

    ev = (decision_quality.get("ev") or {}) if isinstance(decision_quality, dict) else {}
    topn = ev.get("topN") if isinstance(ev, dict) else None
    if isinstance(topn, dict) and topn.get("hitRate") is not None and hr30 is not None:
        if topn["hitRate"] < hr30:
            alerts.append({
                "severity": "medium",
                "code": "EV_RANKING_UNDERPERFORM",
                "message": (
                    f"Top-{topn.get('n', 'N')} EV hit rate ({topn['hitRate']:.2%}) is below "
                    f"overall 30-day hit rate ({hr30:.2%})."
                ),
            })

    if not alerts:
        alerts.append({
            "severity": "info",
            "code": "MODEL_HEALTH_OK",
            "message": "No major model-health alerts detected.",
        })

    return alerts


def extend_alerts_with_activity(alerts: list[dict], activity: dict) -> list[dict]:
    """Append suspicious-flow alerts from unusual activity scan."""
    out = list(alerts)
    summary = (activity or {}).get("summary") or {}
    hi = int(summary.get("highIntensityCount", 0) or 0)
    if hi >= 15:
        out.append({
            "severity": "high",
            "code": "ELEVATED_UNUSUAL_FLOW",
            "message": f"Detected {hi} high-intensity unusual-flow tickers in latest window.",
        })
    elif hi >= 5:
        out.append({
            "severity": "medium",
            "code": "MODERATE_UNUSUAL_FLOW",
            "message": f"Detected {hi} medium/high unusual-flow tickers in latest window.",
        })

    fw = (activity or {}).get("forwardWatchlist") or {}
    fw_hi = int(fw.get("highConvictionCount", 0) or 0)
    if fw_hi >= 50:
        out.append({
            "severity": "medium",
            "code": "MANY_FORWARD_FLOW_SIGNALS",
            "message": f"Forward watchlist has {fw_hi} high-conviction potential big-player signals.",
        })

    tracking = (activity or {}).get("tracking") or {}
    trend = tracking.get("trend")
    if trend == "high_turnover":
        out.append({
            "severity": "medium",
            "code": "FLOW_SIGNAL_TURNOVER_HIGH",
            "message": "Unusual-flow signal set shows high week-over-week turnover; reduce confidence until stable.",
        })
    elif trend == "stable_signal_regime":
        out.append({
            "severity": "info",
            "code": "FLOW_SIGNAL_STABLE",
            "message": "Unusual-flow signal set is showing stable overlap across recent weeks.",
        })
    return out


# ─── Main ──────────────────────────────────────────────────────

def generate_report() -> dict:
    now        = datetime.now(timezone.utc)
    week_label = iso_week_label(now)

    print(f"Generating weekly report for {week_label}…")

    preds         = load_predictions()
    entries       = load_accuracy_log()
    meta          = load_model_metadata()
    prev_meta     = load_prev_model_metadata()
    scored_detail = load_recent_accuracy_details(window_days=7)
    regime        = load_macro_regime()
    thresholds    = regime_thresholds(regime)
    fundamentals_map = load_latest_fundamentals()
    volume_spike_map = load_recent_volume_spike_map()
    prior_reports = load_previous_weekly_reports(current_week=week_label, limit=12)

    print(
        f"  Loaded {len(preds)} predictions, {len(entries)} accuracy entries, "
        f"{len(scored_detail)} scored detail rows."
    )

    # Latest prediction per symbol
    latest: dict[str, dict] = {}
    for p in preds:
        sym = p.get("symbol", "")
        if not sym:
            continue
        existing = latest.get(sym)
        if existing is None or p.get("generatedAt", 0) > existing.get("generatedAt", 0):
            latest[sym] = p

    preds_list = list(latest.values())

    # Top bullish / bearish
    bullish = sorted(
        (p for p in preds_list if p.get("direction") == "UP"),
        key=lambda p: p.get("confidence", 0),
        reverse=True,
    )[:10]

    bearish = sorted(
        (p for p in preds_list if p.get("direction") == "DOWN"),
        key=lambda p: p.get("confidence", 0),
        reverse=True,
    )[:10]

    rolling7 = rolling_performance(entries, 7)
    rolling30 = rolling_performance(entries, 30)
    rolling90 = rolling_performance(entries, 90)
    calibration = calibration_summary(scored_detail)
    decision_quality = {
        "windowDays": 7,
        "ev": decision_quality_summary(scored_detail, top_n=50),
        "portfolioProxy": portfolio_proxy_summary(scored_detail),
    }
    model_matchup = champion_challenger_summary(meta, prev_meta)
    activity_signals = unusual_activity_signals(
        preds_list=preds_list,
        scored_rows=scored_detail,
        fundamentals_map=fundamentals_map,
        volume_spike_map=volume_spike_map,
        regime=regime,
        prior_reports=prior_reports,
        top_n=25,
    )
    activity_signals["forwardWatchlist"] = forward_big_player_watchlist(
        preds_list=preds_list,
        fundamentals_map=fundamentals_map,
        volume_spike_map=volume_spike_map,
        regime=regime,
        prior_reports=prior_reports,
        top_n=20,
    )
    activity_signals["tracking"] = market_signal_tracking(activity_signals, prior_reports)
    activity_signals["tracking"]["forwardWatchlistPrecisionProxy"] = forward_watchlist_precision_proxy(
        prior_reports=prior_reports,
        scored_rows=scored_detail,
    )
    activity_signals["narratives"] = activity_narratives(activity_signals, top_n=10)
    base_alerts = build_alerts(rolling30, calibration, decision_quality, thresholds, regime)
    merged_alerts = extend_alerts_with_activity(base_alerts, activity_signals)

    report = {
        "weekNumber":   week_label,
        "generatedAt":  now.isoformat().replace("+00:00", "Z"),
        "topBullish": [
            {
                "symbol":      p["symbol"],
                "probability": round(p.get("probability", 0.5), 4),
                "confidence":  round(p.get("confidence", 0.5), 4),
            }
            for p in bullish
        ],
        "topBearish": [
            {
                "symbol":      p["symbol"],
                "probability": round(p.get("probability", 0.5), 4),
                "confidence":  round(p.get("confidence", 0.5), 4),
            }
            for p in bearish
        ],
        "sectorRotation": sector_rotation(preds_list),
        "modelPerformance": {
            "rolling7d":  rolling7,
            "rolling30d": rolling30,
            "rolling90d": rolling90,
        },
        "calibration": calibration,
        "decisionQuality": decision_quality,
        "macroRegime": regime,
        "regimeThresholds": thresholds,
        "championChallenger": model_matchup,
        "marketActivitySignals": activity_signals,
        "alerts": merged_alerts,
        "confidenceDistribution": confidence_distribution(preds_list),
        "modelMetadata": {
            "version":      meta.get("version", "unknown"),
            "trainedAt":    meta.get("trainedAt", ""),
            "testAccuracy": (meta.get("testMetrics") or {}).get("accuracy", meta.get("testAccuracy", None)),
            "features":     len(meta.get("featureNames", [])) or meta.get("features", 40),
        },
    }

    return report


def save_report(report: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{report['weekNumber']}.json"
    fpath = REPORTS_DIR / fname
    with open(fpath, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved to {fpath}")
    return fpath


if __name__ == "__main__":
    report = generate_report()
    save_report(report)
    print("Done.")
