"""
data_sources.py

Layered, vendor-agnostic data adapters for the Nostradamus prediction model
and paper-investing agent. The goal is to give both models a reliable canal of
multi-year, multi-source data without locking the project into one vendor.

Providers (all free, no paid keys required by default):
  - Equity OHLCV: yfinance (primary), Stooq CSV (delisted-tolerant fallback)
  - Macro series: FRED public CSV endpoint (no API key required)
  - News/event tone: GDELT 2.0 GKG daily aggregates

All adapters return normalized data structures so callers (training scripts,
the paper agent, feature builders) do not need to know which source served
the request.

Public API:
  fetch_equity_history(symbol, start, end, providers=None) -> list[candle]
  fetch_macro_series(series_id, start=None) -> list[{date, value}]
  fetch_gdelt_daily_tone(start, end) -> list[{date, avgTone, articleCount}]
  probe_providers() -> dict   (used by verify-data-feeds.py)

Candle shape:
  {"date": "YYYY-MM-DD", "open", "high", "low", "close", "volume"}

This module is intentionally dependency-light and safe to import inside CI
workflows.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable

import requests

try:  # Optional, used by the primary equity provider
    import yfinance as yf  # type: ignore
except Exception:  # pragma: no cover - yfinance is required in prod, optional in tests
    yf = None  # type: ignore

USER_AGENT = "Nostradamus-DataCanal/1.0 (+https://github.com/Gandalf-the-shiz/Nostradamus)"
DEFAULT_TIMEOUT_SECS = 30
MIN_CANDLES_FOR_OK = 60


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return fallback
        return v
    except Exception:
        return fallback


def _normalize_symbol_for_stooq(symbol: str) -> str:
    sym = symbol.strip().lower().replace("/", "-").replace(".", "-")
    return f"{sym}.us"


# ---------------------------------------------------------------------------
# Equity OHLCV providers
# ---------------------------------------------------------------------------


def _fetch_equity_yfinance(symbol: str, start: date, end: date) -> list[dict]:
    if yf is None:
        return []
    try:
        df = yf.download(
            symbol,
            start=str(start),
            end=str(end + timedelta(days=1)),
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception:
        return []
    if df is None or df.empty:
        return []

    candles: list[dict] = []
    for idx, row in df.iterrows():
        try:
            candles.append(
                {
                    "date": str(idx)[:10],
                    "open": round(_safe_float(row.get("Open")), 4),
                    "high": round(_safe_float(row.get("High")), 4),
                    "low": round(_safe_float(row.get("Low")), 4),
                    "close": round(_safe_float(row.get("Close")), 4),
                    "volume": int(_safe_float(row.get("Volume"), 0.0)),
                }
            )
        except Exception:
            continue
    return candles


def _fetch_equity_stooq(symbol: str, start: date, end: date) -> list[dict]:
    sym = _normalize_symbol_for_stooq(symbol)
    api_key = os.getenv("STOOQ_API_KEY", "").strip()
    suffix = f"&apikey={api_key}" if api_key else ""
    url = (
        f"https://stooq.com/q/d/l/?s={sym}"
        f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d{suffix}"
    )
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT_SECS)
    except Exception:
        return []
    text = resp.text or ""
    if resp.status_code != 200 or not text:
        return []
    lowered = text.lower()
    if lowered.startswith("no data") or "get your apikey" in lowered:
        # Stooq now gates anonymous CSV downloads behind a free captcha-issued
        # API key. Treat as "unavailable until configured" and let the next
        # provider take over.
        return []

    candles: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            d = (row.get("Date") or "").strip()
            if not d or len(d) < 10:
                continue
            try:
                candles.append(
                    {
                        "date": d[:10],
                        "open": round(_safe_float(row.get("Open")), 4),
                        "high": round(_safe_float(row.get("High")), 4),
                        "low": round(_safe_float(row.get("Low")), 4),
                        "close": round(_safe_float(row.get("Close")), 4),
                        "volume": int(_safe_float(row.get("Volume"), 0.0)),
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    return candles


def _fetch_equity_tiingo(symbol: str, start: date, end: date) -> list[dict]:
    """Tiingo daily prices (free tier: 500 symbols, 50k calls/mo)."""
    token = os.getenv("TIINGO_API_TOKEN", "").strip()
    if not token:
        return []
    url = (
        f"https://api.tiingo.com/tiingo/daily/{symbol.upper()}/prices"
        f"?startDate={start.isoformat()}&endDate={end.isoformat()}"
    )
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Token {token}", "User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT_SECS,
        )
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        rows = resp.json()
    except Exception:
        return []
    candles: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        d = (row.get("date") or "")[:10]
        if not d:
            continue
        candles.append(
            {
                "date": d,
                "open": round(_safe_float(row.get("open")), 4),
                "high": round(_safe_float(row.get("high")), 4),
                "low": round(_safe_float(row.get("low")), 4),
                "close": round(_safe_float(row.get("close") or row.get("adjClose")), 4),
                "volume": int(_safe_float(row.get("volume"), 0.0)),
            }
        )
    return candles


def _fetch_equity_alphavantage(symbol: str, start: date, end: date) -> list[dict]:
    """Alpha Vantage TIME_SERIES_DAILY_ADJUSTED (25 calls/day free)."""
    key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    if not key:
        return []
    url = (
        "https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol.upper()}"
        f"&outputsize=full&apikey={key}"
    )
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT_SECS)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    series = payload.get("Time Series (Daily)") or payload.get("Time Series (Daily Adjusted)") or {}
    if not isinstance(series, dict):
        return []
    candles: list[dict] = []
    for d, row in series.items():
        if len(d) < 10:
            continue
        try:
            dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if dt < start or dt > end:
            continue
        candles.append(
            {
                "date": d[:10],
                "open": round(_safe_float(row.get("1. open")), 4),
                "high": round(_safe_float(row.get("2. high")), 4),
                "low": round(_safe_float(row.get("3. low")), 4),
                "close": round(_safe_float(row.get("4. close") or row.get("5. adjusted close")), 4),
                "volume": int(_safe_float(row.get("6. volume"), 0.0)),
            }
        )
    candles.sort(key=lambda c: c["date"])
    return candles


EQUITY_PROVIDERS: dict[str, Callable[[str, date, date], list[dict]]] = {
    "yfinance": _fetch_equity_yfinance,
    "tiingo": _fetch_equity_tiingo,
    "alphavantage": _fetch_equity_alphavantage,
    "stooq": _fetch_equity_stooq,
}

# Default provider order when keys are available
DEFAULT_EQUITY_ORDER = ["yfinance", "tiingo", "alphavantage", "stooq"]


def fetch_equity_history(
    symbol: str,
    start: date,
    end: date | None = None,
    providers: Iterable[str] | None = None,
    min_candles: int = MIN_CANDLES_FOR_OK,
) -> tuple[list[dict], str]:
    """
    Fetch daily OHLCV history with provider fallback.

    Returns:
      (candles, provider_used). provider_used is "" when no source succeeded.
    """
    if end is None:
        end = _today_utc()

    if providers:
        order = list(providers)
    else:
        order = [p for p in DEFAULT_EQUITY_ORDER if p in EQUITY_PROVIDERS]
    last_candles: list[dict] = []
    for name in order:
        func = EQUITY_PROVIDERS.get(name)
        if not func:
            continue
        candles = func(symbol, start, end)
        if len(candles) >= min_candles:
            return candles, name
        if len(candles) > len(last_candles):
            last_candles = candles
    return last_candles, ""


# ---------------------------------------------------------------------------
# Macro series provider (no API key required)
# ---------------------------------------------------------------------------

FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="


def fetch_macro_series(series_id: str, start: date | None = None) -> list[dict]:
    """
    Fetch a FRED macroeconomic series via the public CSV endpoint (no key).

    Returns list of {"date", "value"} sorted ascending. Missing values are skipped.
    """
    url = f"{FRED_CSV_BASE}{series_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DEFAULT_TIMEOUT_SECS)
    except Exception:
        return []
    if resp.status_code != 200 or not resp.text:
        return []

    out: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            d = (row.get("DATE") or row.get("observation_date") or "").strip()
            if not d:
                continue
            raw = (row.get(series_id) or row.get("VALUE") or "").strip()
            if raw in {"", "."}:
                continue
            try:
                value = float(raw)
            except Exception:
                continue
            if start is not None:
                try:
                    if datetime.strptime(d[:10], "%Y-%m-%d").date() < start:
                        continue
                except Exception:
                    pass
            out.append({"date": d[:10], "value": value})
    except Exception:
        return []
    out.sort(key=lambda r: r["date"])
    return out


# ---------------------------------------------------------------------------
# GDELT 2.0 daily event tone aggregator (no API key)
# ---------------------------------------------------------------------------


def fetch_gdelt_daily_tone(
    start: date,
    end: date | None = None,
    query: str | None = None,
) -> list[dict]:
    """
    Fetch GDELT 2.0 GKG-derived event tone daily averages via the DOC API.

    Args:
        start, end: inclusive date range.
        query: GDELT search query. Defaults to a broad finance/markets query
            that reliably returns a non-empty timeline.

    Returns list of {"date", "avgTone", "articleCount"}.
    """
    if end is None:
        end = _today_utc()
    q = (query or os.getenv("GDELT_QUERY") or "stock market").strip()
    # GDELT requires OR-clauses to be wrapped in parentheses. If the caller
    # passes a bare OR query we wrap it defensively.
    if " OR " in q and not (q.startswith("(") and q.endswith(")")):
        q = f"({q})"
    encoded = requests.utils.quote(q, safe="")  # type: ignore[attr-defined]
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={encoded}&mode=timelinetone&format=json"
        f"&startdatetime={start.strftime('%Y%m%d')}000000"
        f"&enddatetime={end.strftime('%Y%m%d')}235959"
    )
    # GDELT enforces ~1 request / 5 sec. One bounded retry on 429.
    resp = None
    for attempt in range(2):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=DEFAULT_TIMEOUT_SECS,
            )
        except Exception:
            return []
        if resp.status_code == 429:
            time.sleep(6.0)
            continue
        break
    if resp is None or resp.status_code != 200 or not resp.text:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []

    timeline = payload.get("timeline") or []
    if not isinstance(timeline, list) or not timeline:
        return []

    data = timeline[0].get("data") or []
    out: list[dict] = []
    for row in data:
        ds = "".join(ch for ch in str(row.get("date") or "") if ch.isdigit())
        if len(ds) < 8:
            continue
        formatted = f"{ds[0:4]}-{ds[4:6]}-{ds[6:8]}"
        out.append(
            {
                "date": formatted,
                "avgTone": _safe_float(row.get("value"), 0.0),
                "articleCount": int(_safe_float(row.get("norm") or row.get("count") or 0)),
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


# ---------------------------------------------------------------------------
# Provider health check
# ---------------------------------------------------------------------------


def probe_providers(probe_symbol: str = "AAPL") -> dict:
    """
    Run a tiny probe against each provider and return a structured health doc.
    """
    today = _today_utc()
    lookback_start = today - timedelta(days=14)

    result: dict = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "probeSymbol": probe_symbol,
        "providers": {},
    }

    def _time(fn, *args, **kwargs):
        t0 = time.time()
        try:
            value = fn(*args, **kwargs)
            return value, round((time.time() - t0) * 1000.0, 2), ""
        except Exception as exc:
            return None, round((time.time() - t0) * 1000.0, 2), str(exc)

    # yfinance
    candles, ms, err = _time(_fetch_equity_yfinance, probe_symbol, lookback_start, today)
    result["providers"]["yfinance"] = {
        "ok": bool(candles),
        "rows": len(candles or []),
        "latencyMs": ms,
        "error": err,
    }

    # stooq (manual-import only — its programmatic endpoints are captcha-walled)
    if os.getenv("STOOQ_API_KEY"):
        candles, ms, err = _time(_fetch_equity_stooq, probe_symbol, lookback_start, today)
        result["providers"]["stooq"] = {
            "ok": bool(candles),
            "rows": len(candles or []),
            "latencyMs": ms,
            "error": err,
        }
    else:
        result["providers"]["stooq"] = {
            "ok": False,
            "rows": 0,
            "latencyMs": 0.0,
            "error": "skipped: programmatic access captcha-walled; use import-stooq-bulk-zip.py instead",
            "skipped": True,
        }

    # FRED
    series, ms, err = _time(fetch_macro_series, "DFF", today - timedelta(days=60))
    result["providers"]["fred"] = {
        "ok": bool(series),
        "rows": len(series or []),
        "latencyMs": ms,
        "error": err,
    }

    # GDELT
    tone, ms, err = _time(fetch_gdelt_daily_tone, today - timedelta(days=7), today)
    result["providers"]["gdelt"] = {
        "ok": bool(tone),
        "rows": len(tone or []),
        "latencyMs": ms,
        "error": err,
    }

    # Tiingo (optional key)
    if os.getenv("TIINGO_API_TOKEN", "").strip():
        candles, ms, err = _time(_fetch_equity_tiingo, probe_symbol, lookback_start, today)
        result["providers"]["tiingo"] = {
            "ok": bool(candles),
            "rows": len(candles or []),
            "latencyMs": ms,
            "error": err,
        }
    else:
        result["providers"]["tiingo"] = {
            "ok": False,
            "rows": 0,
            "latencyMs": 0.0,
            "error": "skipped: set TIINGO_API_TOKEN",
            "skipped": True,
        }

    # Alpha Vantage (optional key)
    if os.getenv("ALPHAVANTAGE_API_KEY", "").strip():
        candles, ms, err = _time(_fetch_equity_alphavantage, probe_symbol, lookback_start, today)
        result["providers"]["alphavantage"] = {
            "ok": bool(candles),
            "rows": len(candles or []),
            "latencyMs": ms,
            "error": err,
        }
    else:
        result["providers"]["alphavantage"] = {
            "ok": False,
            "rows": 0,
            "latencyMs": 0.0,
            "error": "skipped: set ALPHAVANTAGE_API_KEY",
            "skipped": True,
        }

    result["summary"] = {
        "okCount": sum(1 for p in result["providers"].values() if p.get("ok")),
        "totalProviders": sum(1 for p in result["providers"].values() if not p.get("skipped")),
        "skippedProviders": sum(1 for p in result["providers"].values() if p.get("skipped")),
    }
    return result


__all__ = [
    "fetch_equity_history",
    "fetch_macro_series",
    "fetch_gdelt_daily_tone",
    "probe_providers",
    "EQUITY_PROVIDERS",
]
