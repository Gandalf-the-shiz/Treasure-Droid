"""
fetch-macro.py — Phase C: Macroeconomic Regime Data via FRED API

Fetches key macroeconomic time series from the Federal Reserve Economic Data (FRED)
API and writes a snapshot to data/macro/YYYY-MM-DD.json.

Series fetched:
  DFF     — Fed Funds Rate (daily)
  T10Y2Y  — 10Y-2Y Treasury yield spread (yield curve)
  VIXCLS  — CBOE Volatility Index (VIX)
  UMCSENT — University of Michigan Consumer Sentiment
  ICSA    — Initial Jobless Claims (weekly)
  SP500   — S&P 500 Price Index (monthly)
  M2SL    — M2 Money Supply (monthly)

Output: data/macro/YYYY-MM-DD.json
  {
    "date": "YYYY-MM-DD",
    "generatedAt": "...",
    "series": {
      "DFF": 5.33,
      "T10Y2Y": -0.22,
      "VIXCLS": 18.4,
      "UMCSENT": 67.8,
      "ICSA": 220000,
      "SP500": 5100.0,
      "M2SL": 20900.0
    },
    "regime": "BULL"  | "BEAR" | "HIGH_VOL" | "SIDEWAYS"
  }

FRED API key: free at https://fred.stlouisfed.org/docs/api/api_key.html
Set as FRED_API_KEY GitHub secret.

Run weekly via .github/workflows/fetch-macro.yml.
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent
MACRO_DIR  = REPO_ROOT / "data" / "macro"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"
FRED_GRAPH_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
MACRO_BACKFILL_YEARS = int(os.getenv("MACRO_BACKFILL_YEARS", "10"))
STRICT_PUBLIC_DATA = os.getenv("STRICT_PUBLIC_DATA", "false").strip().lower() in {"1", "true", "yes"}

# Which FRED series to pull and their default values when unavailable
FRED_SERIES = {
    "DFF":     {"description": "Fed Funds Rate (%)",        "default": 5.0},
    "T10Y2Y":  {"description": "10Y-2Y Yield Spread (%)",   "default": 0.0},
    "VIXCLS":  {"description": "VIX Volatility Index",      "default": 20.0},
    "UMCSENT": {"description": "Consumer Sentiment Index",  "default": 70.0},
    "ICSA":    {"description": "Initial Jobless Claims",    "default": 230000.0},
    "SP500":   {"description": "S&P 500 Price Index",       "default": 4500.0},
    "M2SL":    {"description": "M2 Money Supply (B$)",      "default": 20000.0},
    "T10Y3M":  {"description": "10Y-3M Treasury Spread (%)", "default": 0.0},
    "BAMLH0A0HYM2": {"description": "HY OAS spread (%)",   "default": 4.0},
    "UNRATE":  {"description": "Unemployment Rate (%)",     "default": 4.0},
    "CPIAUCSL": {"description": "CPI Index",                "default": 300.0},
    "INDPRO":  {"description": "Industrial Production Index", "default": 100.0},
}

YF_MACRO_PROXY_SYMBOLS = {
    "VIXCLS": "^VIX",
    "T10Y2Y": None,
    "DFF": "^IRX",
    "SP500": "^GSPC",
}

PUBLIC_SERIES_IDS = tuple(FRED_SERIES.keys())

# Regime thresholds (tuned to empirical historical distributions)
VIX_HIGH_THRESHOLD  = 25.0    # VIX > 25 → HIGH_VOL
VIX_BEAR_THRESHOLD  = 18.0    # VIX > this while yield curve inverted → BEAR
SPREAD_BEAR_THRESH  = -0.30   # Inverted yield curve below -0.30% → BEAR signal
SPREAD_BULL_THRESH  =  0.50   # Positive spread > 0.50% → BULL signal


# ---------------------------------------------------------------------------
# Public historical data fetch
# ---------------------------------------------------------------------------

def _load_fred_graph_series(series_id: str) -> dict[date, float]:
    """Load a full public historical series from FRED's CSV graph endpoint."""
    try:
        import requests
    except ImportError:
        return {}

    try:
        resp = requests.get(f"{FRED_GRAPH_BASE}{series_id}", timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[fetch-macro] FRED graph CSV error ({series_id}): {exc}")
        return {}

    history: dict[date, float] = {}
    try:
        reader = csv.DictReader(resp.text.splitlines())
        for row in reader:
            raw_date = (row.get("observation_date") or row.get("DATE") or row.get("date") or "").strip()
            raw_value = (row.get(series_id) or row.get("VALUE") or row.get("value") or "").strip()
            if not raw_date or not raw_value or raw_value == ".":
                continue
            try:
                history[date.fromisoformat(raw_date)] = float(raw_value)
            except ValueError:
                continue
    except Exception as exc:
        print(f"[fetch-macro] Could not parse FRED CSV for {series_id}: {exc}")
        return {}

    return history


def load_public_series_history() -> dict[str, dict[date, float]]:
    """Load all public macro history sources available to the training pipeline."""
    histories: dict[str, dict[date, float]] = {}
    for series_id in PUBLIC_SERIES_IDS:
        series_history = _load_fred_graph_series(series_id)
        if series_history:
            histories[series_id] = series_history
            print(f"[fetch-macro] Loaded public history for {series_id}: {len(series_history)} points")
    return histories


def resolve_series_value(series_history: dict[date, float], target_date: date) -> float | None:
    """Return the latest observed value on or before target_date."""
    best_date = None
    best_value = None
    for obs_date, value in series_history.items():
        if obs_date <= target_date and (best_date is None or obs_date > best_date):
            best_date = obs_date
            best_value = value
    return best_value


def build_macro_snapshot(series_by_id: dict[str, dict[date, float]], target_date: date) -> dict[str, float] | None:
    """Build a dated macro snapshot from public series histories."""
    snapshot: dict[str, float] = {}
    for series_id, default_cfg in FRED_SERIES.items():
        value = resolve_series_value(series_by_id.get(series_id, {}), target_date)
        if value is None:
            if STRICT_PUBLIC_DATA:
                return None
            value = default_cfg["default"]
        snapshot[series_id] = round(float(value), 4)
    return snapshot


def backfill_public_macro_snapshots() -> tuple[dict[str, float], dict[str, str]]:
    """Write daily macro snapshots using public historical FRED data."""
    histories = load_public_series_history()
    if not histories:
        raise RuntimeError("No public macro histories could be loaded from FRED graph CSV endpoints.")

    date_min = min(min(hist.keys()) for hist in histories.values())
    date_max = date.today()

    last_series: dict[str, float] | None = None
    last_sources: dict[str, str] | None = None

    for current in (date_min + timedelta(days=offset) for offset in range((date_max - date_min).days + 1)):
        series = build_macro_snapshot(histories, current)
        if series is None:
            continue
        regime = classify_regime(series)
        norm_features = compute_normalised_features(series)
        payload = {
            "date": current.isoformat(),
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fredApiAvailable": bool(FRED_API_KEY),
            "series": series,
            "seriesSource": {series_id: "fred-graph" for series_id in series.keys()},
            "regime": regime,
            "normalisedFeatures": norm_features,
        }

        out_path = MACRO_DIR / f"{current.isoformat()}.json"
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)
        last_series = series
        last_sources = payload["seriesSource"]

    if last_series is None or last_sources is None:
        raise RuntimeError("Public macro backfill produced no snapshots.")

    latest_payload = {
        "date": date.today().isoformat(),
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fredApiAvailable": bool(FRED_API_KEY),
        "series": last_series,
        "seriesSource": last_sources,
        "regime": classify_regime(last_series),
        "normalisedFeatures": compute_normalised_features(last_series),
    }

    with open(MACRO_DIR / f"{date.today().isoformat()}.json", "w") as f:
        json.dump(latest_payload, f, indent=2)

    return last_series, last_sources

def fetch_fred_series(series_id: str, lookback_days: int = 90) -> float | None:
    """
    Fetch the most recent non-null value for a FRED series.
    Returns the float value or None on failure.
    """
    if not FRED_API_KEY:
        return None

    try:
        import requests
    except ImportError:
        return None

    observation_start = (date.today() - timedelta(days=lookback_days)).isoformat()

    try:
        resp = requests.get(
            FRED_BASE,
            params={
                "series_id":         series_id,
                "api_key":           FRED_API_KEY,
                "file_type":         "json",
                "observation_start": observation_start,
                "sort_order":        "desc",
                "limit":             10,
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])

        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str != ".":
                return float(val_str)

        return None

    except Exception as e:
        print(f"[fetch-macro] FRED error ({series_id}): {e}")
        return None


def load_previous_series() -> dict[str, float]:
    """Load the latest existing macro snapshot series, if present."""
    candidates = []
    if not MACRO_DIR.exists():
        return {}
    for fpath in MACRO_DIR.glob("*.json"):
        if fpath.name == "current-regime.json":
            continue
        try:
            date.fromisoformat(fpath.stem)
            candidates.append(fpath)
        except ValueError:
            continue
    if not candidates:
        return {}
    candidates.sort()
    latest = candidates[-1]
    try:
        with open(latest) as f:
            payload = json.load(f)
        series = payload.get("series", {})
        return series if isinstance(series, dict) else {}
    except Exception:
        return {}


def fetch_yfinance_macro_proxies() -> dict[str, float]:
    """Fetch real macro proxies from Yahoo symbols when FRED series are unavailable."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    proxies: dict[str, float] = {}
    symbols = [s for s in {v for v in YF_MACRO_PROXY_SYMBOLS.values()} if s]
    if not symbols:
        return proxies

    try:
        hist = yf.download(symbols, period="7d", interval="1d", auto_adjust=True, progress=False)
    except Exception:
        return proxies

    def _last_close(sym: str) -> float | None:
        try:
            if getattr(hist.columns, "nlevels", 1) > 1:
                if "Close" in hist.columns.get_level_values(0) and sym in hist["Close"].columns:
                    s = hist["Close"][sym].dropna()
                    return float(s.iloc[-1]) if not s.empty else None
            elif "Close" in hist.columns:
                s = hist["Close"].dropna()
                return float(s.iloc[-1]) if not s.empty else None
        except Exception:
            return None
        return None

    # VIXCLS proxy from ^VIX close.
    vix = _last_close("^VIX")
    if vix is not None:
        proxies["VIXCLS"] = vix

    # Fed funds proxy from 13-week Treasury yield (^IRX, percent * 0.1).
    irx = _last_close("^IRX")
    if irx is not None:
        proxies["DFF"] = irx / 10.0

    # SP500 proxy from ^GSPC close.
    gspc = _last_close("^GSPC")
    if gspc is not None:
        proxies["SP500"] = gspc

    # Yield spread proxy from ^TNX - ^IRX if both available.
    tnx = _last_close("^TNX")
    if tnx is not None and irx is not None:
        # ^TNX and ^IRX are quoted in 10x percent units.
        ten_year = tnx / 10.0
        three_month = irx / 10.0
        proxies["T10Y2Y"] = ten_year - three_month

    return proxies


def fetch_all_series() -> tuple[dict[str, float], dict[str, str]]:
    """Fetch all configured macro series from public sources with fallback order.

    Fallback order per series:
      1) FRED API (if key present)
      2) Yahoo market proxy (when supported)
      3) Previous local macro snapshot
      4) Static default constant
    """
    values: dict[str, float] = {}
    sources: dict[str, str] = {}

    prev_series = load_previous_series()
    market_proxies = fetch_yfinance_macro_proxies()

    if not FRED_API_KEY:
        print("[fetch-macro] FRED_API_KEY not set — using public proxy and previous snapshots before defaults.")

    for series_id, cfg in FRED_SERIES.items():
        val = fetch_fred_series(series_id) if FRED_API_KEY else None
        if val is not None:
            print(f"[fetch-macro] {series_id}: {val}")
            sources[series_id] = "fred"
        elif series_id in market_proxies:
            val = market_proxies[series_id]
            print(f"[fetch-macro] {series_id}: using Yahoo market proxy {val}")
            sources[series_id] = "yahoo-proxy"
        elif series_id in prev_series:
            val = float(prev_series[series_id])
            print(f"[fetch-macro] {series_id}: using previous snapshot value {val}")
            sources[series_id] = "previous-snapshot"
        else:
            print(f"[fetch-macro] {series_id}: no public source available — using default {cfg['default']}")
            val = cfg["default"]
            sources[series_id] = "default"
        values[series_id] = round(val, 4)
        time.sleep(0.2)   # be polite to FRED API

    return values, sources


# ---------------------------------------------------------------------------
# Regime detection (rule-based, deterministic)
# ---------------------------------------------------------------------------

def classify_regime(series: dict[str, float]) -> str:
    """
    Classify the current macro regime from FRED data.
    Returns one of: "BULL", "BEAR", "HIGH_VOL", "SIDEWAYS"

    Rules (applied in priority order):
    1. HIGH_VOL: VIX > 25
    2. BEAR:     Yield curve deeply inverted (T10Y2Y < -0.30) AND VIX elevated
    3. BULL:     Yield curve positive (T10Y2Y > 0.50) AND VIX moderate (<20)
    4. SIDEWAYS: Everything else
    """
    vix     = series.get("VIXCLS",  FRED_SERIES["VIXCLS"]["default"])
    spread  = series.get("T10Y2Y",  FRED_SERIES["T10Y2Y"]["default"])
    fed_rate = series.get("DFF",     FRED_SERIES["DFF"]["default"])
    claims  = series.get("ICSA",    FRED_SERIES["ICSA"]["default"])

    # HIGH_VOL regime: fear spike
    if vix > VIX_HIGH_THRESHOLD:
        return "HIGH_VOL"

    # BEAR regime: inverted yield curve + elevated stress
    if spread < SPREAD_BEAR_THRESH and vix > VIX_BEAR_THRESHOLD:
        return "BEAR"

    # BULL regime: positive yield curve + low volatility
    if spread > SPREAD_BULL_THRESH and vix < 20.0:
        return "BULL"

    return "SIDEWAYS"


# ---------------------------------------------------------------------------
# Normalised macro feature vector (for injection into model features)
# ---------------------------------------------------------------------------

def compute_normalised_features(series: dict[str, float]) -> dict[str, float]:
    """
    Convert raw FRED values into normalised features suitable for model input.
    All outputs are clipped to a reasonable range and scaled to roughly [0, 1].
    """
    # VIX: normalise [10, 80] → [0, 1]
    vix_norm = max(0.0, min(1.0, (series.get("VIXCLS", 20.0) - 10.0) / 70.0))

    # Yield spread: normalise [-2, 2] → [0, 1]
    spread_norm = max(0.0, min(1.0, (series.get("T10Y2Y", 0.0) + 2.0) / 4.0))

    # Fed rate: normalise [0, 10] → [0, 1]
    fed_norm = max(0.0, min(1.0, series.get("DFF", 5.0) / 10.0))

    # Consumer sentiment: normalise [50, 110] → [0, 1]
    sentiment_norm = max(0.0, min(1.0, (series.get("UMCSENT", 70.0) - 50.0) / 60.0))

    # Initial claims: normalise [150k, 600k] → [0, 1], inverted (high claims = bad)
    claims_norm = max(0.0, min(1.0, 1.0 - (series.get("ICSA", 230000.0) - 150000.0) / 450000.0))

    # Extended regime features (v3 predictor + Robinhood prep)
    t10y3m_norm = max(0.0, min(1.0, (series.get("T10Y3M", 0.0) + 2.0) / 4.0))
    hy_oas_norm = max(0.0, min(1.0, (series.get("BAMLH0A0HYM2", 4.0) - 2.0) / 8.0))
    unrate_norm = max(0.0, min(1.0, 1.0 - (series.get("UNRATE", 4.0) - 3.0) / 7.0))
    cpi_norm = max(0.0, min(1.0, (series.get("CPIAUCSL", 300.0) - 250.0) / 100.0))
    indpro_norm = max(0.0, min(1.0, (series.get("INDPRO", 100.0) - 90.0) / 20.0))
    sp500_norm = max(0.0, min(1.0, (series.get("SP500", 4500.0) - 3000.0) / 3000.0))
    m2_norm = max(0.0, min(1.0, (series.get("M2SL", 20000.0) - 18000.0) / 6000.0))

    return {
        "macro_vix_norm":      round(vix_norm, 4),
        "macro_spread_norm":   round(spread_norm, 4),
        "macro_fed_norm":      round(fed_norm, 4),
        "macro_sentiment_norm": round(sentiment_norm, 4),
        "macro_claims_norm":   round(claims_norm, 4),
        "macro_t10y3m_norm":   round(t10y3m_norm, 4),
        "macro_hy_oas_norm":   round(hy_oas_norm, 4),
        "macro_unrate_norm":   round(unrate_norm, 4),
        "macro_cpi_norm":      round(cpi_norm, 4),
        "macro_indpro_norm":   round(indpro_norm, 4),
        "macro_sp500_norm":    round(sp500_norm, 4),
        "macro_m2_norm":       round(m2_norm, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    MACRO_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    out_path  = MACRO_DIR / f"{today_str}.json"
    regime_path = MACRO_DIR / "current-regime.json"

    print("=" * 60)
    print(f"[fetch-macro] Fetching macroeconomic data for {today_str}")
    print("=" * 60)

    # Build daily public-history snapshots from FRED's public CSV endpoint.
    # This avoids synthetic defaults/proxies and gives the training pipeline
    # dated public macro features for the available history.
    series, sources = backfill_public_macro_snapshots()

    # Classify regime
    regime = classify_regime(series)
    print(f"\n[fetch-macro] Regime classification: {regime}")

    # Compute normalised features
    norm_features = compute_normalised_features(series)
    print(f"[fetch-macro] Normalised macro features: {norm_features}")

    # Build output
    output = {
        "date":              today_str,
        "generatedAt":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fredApiAvailable":  bool(FRED_API_KEY),
        "series":            series,
        "seriesSource":      sources,
        "regime":            regime,
        "normalisedFeatures": norm_features,
    }

    # Write dated snapshot
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[fetch-macro] Wrote snapshot: {out_path}")

    # Overwrite current-regime.json (always points to the latest)
    with open(regime_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[fetch-macro] Updated current regime: {regime_path}")

    print()
    print("=" * 60)
    print(f"[fetch-macro] DONE — Regime: {regime}")
    print("=" * 60)


if __name__ == "__main__":
    main()
