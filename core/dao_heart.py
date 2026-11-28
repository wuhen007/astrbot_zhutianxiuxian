"""Shared dao-heart recovery and ratios for original gameplay consumers."""
from __future__ import annotations

import math
from typing import Any

INITIAL = 100
MAXIMUM = 500
RECOVERY_INTERVAL = 30 * 60


def ensure(doc: Any, now: float) -> int:
    ext = doc.ext
    legacy = ext.get("legacy_source")
    legacy = legacy if isinstance(legacy, dict) else {}
    raw = ext.get("daoxin", legacy.get("道心", legacy.get("道心值", INITIAL)))
    try:
        value = min(MAXIMUM, max(0, int(float(raw))))
    except (TypeError, ValueError, OverflowError):
        value = INITIAL
    try:
        last = float(ext.get("daoxin_recovery_at", now) or now)
    except (TypeError, ValueError, OverflowError):
        last = float(now)
    ticks = max(0, math.floor((float(now) - last) / RECOVERY_INTERVAL))
    value = min(MAXIMUM, value + ticks)
    ext["daoxin"] = value
    ext["daoxin_recovery_at"] = last + ticks * RECOVERY_INTERVAL if ticks else last
    return value


def learning_chance_multiplier(doc: Any, now: float) -> float:
    return round(0.55 + ensure(doc, now) / MAXIMUM * 0.45, 4)


def adjust(doc: Any, delta: int, reason: str = "道心变动", now: float | None = None) -> dict[str, int | str]:
    """Apply the original bounded Dao-heart change and retain a short audit history."""
    stamp = float(time.time() if now is None else now)
    before = ensure(doc, stamp)
    after = min(MAXIMUM, max(0, before + int(delta)))
    doc.ext["daoxin"] = after
    if after != before:
        rows = doc.ext.get("daoxin_history")
        rows = list(rows) if isinstance(rows, list) else []
        rows.append({"at": stamp, "before": before, "after": after,
                     "change": after - before, "reason": str(reason)})
        doc.ext["daoxin_history"] = rows[-30:]
    return {"before": before, "after": after, "change": after - before,
            "reason": str(reason)}