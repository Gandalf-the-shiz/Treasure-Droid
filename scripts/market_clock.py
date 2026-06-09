"""US equity market session helpers (Eastern Time)."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(ET)


def is_weekday(dt: datetime | None = None) -> bool:
    d = dt or now_et()
    return d.weekday() < 5


def is_market_open(dt: datetime | None = None) -> bool:
    d = dt or now_et()
    if not is_weekday(d):
        return False
    t = d.time()
    return time(9, 30) <= t < time(16, 0)


def is_after_close(dt: datetime | None = None) -> bool:
    d = dt or now_et()
    if not is_weekday(d):
        return True
    return d.time() >= time(16, 15)


def minutes_to_close(dt: datetime | None = None) -> int:
    d = dt or now_et()
    close = d.replace(hour=16, minute=0, second=0, microsecond=0)
    return max(0, int((close - d).total_seconds() // 60))


def session_label(dt: datetime | None = None) -> str:
    d = dt or now_et()
    if not is_weekday(d):
        return "closed_weekend"
    t = d.time()
    if t < time(9, 30):
        return "pre_market"
    if t < time(16, 0):
        return "regular"
    return "after_hours"
