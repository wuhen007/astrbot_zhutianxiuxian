"""Configurable daily quiet window for scheduled world activity."""

from __future__ import annotations

from datetime import datetime, time as day_time, timedelta, timezone
from typing import Any


def is_quiet(now: float, enabled: Any, start_hour: Any, end_hour: Any,
             utc_offset: Any = 8) -> bool:
    if not enabled:
        return False
    try:
        start, end, offset = int(start_hour), int(end_hour), int(utc_offset)
    except (TypeError, ValueError):
        return False
    if not (0 <= start < 24 and 0 <= end < 24 and -12 <= offset <= 14) or start == end:
        return False
    local = datetime.fromtimestamp(float(now), timezone(timedelta(hours=offset))).time()
    hour = local.hour + local.minute / 60 + local.second / 3600
    return start <= hour < end if start < end else hour >= start or hour < end


def window_start(now: float, start_hour: int, end_hour: int, utc_offset: int = 8) -> float:
    """Start timestamp of the quiet window containing now; caller must verify is_quiet."""
    tz = timezone(timedelta(hours=utc_offset))
    local = datetime.fromtimestamp(now, tz)
    day = local.date()
    if start_hour > end_hour and local.hour < end_hour:
        day -= timedelta(days=1)
    start = datetime.combine(day, day_time(start_hour), tzinfo=tz)
    return start.timestamp()
