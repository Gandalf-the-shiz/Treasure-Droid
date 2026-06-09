"""Utilities for resolving dated public-data snapshots.

These helpers load daily JSON snapshots (YYYY-MM-DD.json) and provide
date-aware lookups with optional forward-fill windows.
"""

from __future__ import annotations

import json
import os
from datetime import date


def _parse_snapshot_date(filename: str) -> date | None:
    stem, ext = os.path.splitext(filename)
    if ext.lower() != ".json":
        return None
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None


def load_ticker_snapshots(directory: str) -> list[tuple[date, dict[str, dict]]]:
    """Load sorted daily ticker snapshots from a directory.

    Expected payload shape per file:
      {"date": "YYYY-MM-DD", "tickers": {"AAPL": {...}, ...}}
    """
    out: list[tuple[date, dict[str, dict]]] = []
    if not os.path.isdir(directory):
        return out

    for entry in sorted(os.listdir(directory)):
        snap_date = _parse_snapshot_date(entry)
        if snap_date is None:
            continue

        path = os.path.join(directory, entry)
        try:
            with open(path) as f:
                payload = json.load(f)
            tickers = payload.get("tickers", {})
            if isinstance(tickers, dict):
                out.append((snap_date, tickers))
        except Exception:
            continue

    out.sort(key=lambda x: x[0])
    return out


def load_macro_snapshots(directory: str) -> list[tuple[date, dict]]:
    """Load sorted daily macro snapshots from a directory.

    Expected payload shape per file:
      {"date": "YYYY-MM-DD", "normalisedFeatures": {...}}
    """
    out: list[tuple[date, dict]] = []
    if not os.path.isdir(directory):
        return out

    for entry in sorted(os.listdir(directory)):
        snap_date = _parse_snapshot_date(entry)
        if snap_date is None:
            continue

        path = os.path.join(directory, entry)
        try:
            with open(path) as f:
                payload = json.load(f)
            features = payload.get("normalisedFeatures", {})
            if isinstance(features, dict):
                out.append((snap_date, features))
        except Exception:
            continue

    out.sort(key=lambda x: x[0])
    return out


def resolve_ticker_record(
    snapshots: list[tuple[date, dict[str, dict]]],
    ticker: str,
    target_date: date,
    max_age_days: int,
) -> dict | None:
    """Resolve latest ticker record on or before target_date.

    Returns None if no record exists within max_age_days.
    """
    best: dict | None = None
    best_date: date | None = None

    for snap_date, by_ticker in snapshots:
        if snap_date > target_date:
            break
        record = by_ticker.get(ticker)
        if record is not None:
            best = record
            best_date = snap_date

    if best is None or best_date is None:
        return None

    if (target_date - best_date).days > max_age_days:
        return None

    return best


def resolve_macro_features(
    snapshots: list[tuple[date, dict]],
    target_date: date,
    max_age_days: int,
) -> dict | None:
    """Resolve latest macro feature record on or before target_date."""
    best: dict | None = None
    best_date: date | None = None

    for snap_date, features in snapshots:
        if snap_date > target_date:
            break
        best = features
        best_date = snap_date

    if best is None or best_date is None:
        return None

    if (target_date - best_date).days > max_age_days:
        return None

    return best
