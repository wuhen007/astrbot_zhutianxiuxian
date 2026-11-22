"""Shared clock scaling for actions affected by innate treasures."""

from __future__ import annotations

import math

from . import xtzb


def multiplier(doc, now: float) -> float:
    snapshot = doc.model_copy(deep=True)
    return min(1.0, max(0.3, float(xtzb.time_mult(snapshot, now))))


def credited_minutes(started_at: float, now: float, time_multiplier: float) -> int:
    try:
        start = float(started_at)
        multiplier = float(time_multiplier)
    except (TypeError, ValueError):
        return 0
    multiplier = min(1.0, max(0.3, multiplier))
    elapsed_seconds = max(0.0, float(now) - start)
    return max(0, math.floor(elapsed_seconds / (60 * multiplier) + 1e-9))
