"""独立当前生命本源；灵根 origin 仅作为上限来源，不与当前值混存。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CURRENT_KEY = "life_source"
BASE = 100.0
PRECISION = 3


def maximum(doc: Any) -> float:
    ext = getattr(doc, "ext", {}) or {}
    root = ext.get("linggen") if isinstance(ext, Mapping) else None
    root = root if isinstance(root, Mapping) else {}
    try:
        from . import memory
        stage = memory.stage_of(doc)
        if stage:
            return float(memory.life_max(memory.state_of(doc), stage))
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        from . import suiyun
        stage = suiyun.stage_of(doc)
        if stage:
            state = suiyun.state_of(doc) or {}
            spec = suiyun.STAGES[stage - 1]
            refined = max(0.0, float(state.get("refined", 0) or 0))
            return round(min(float(spec["cap"]), float(spec["life"]) + refined), PRECISION)
    except (AttributeError, TypeError, ValueError, IndexError):
        pass
    evil = ext.get("evil") if isinstance(ext, Mapping) else None
    tianmo = evil.get("tianmo") if isinstance(evil, Mapping) else None
    cumulative = tianmo.get("cumulative") if isinstance(tianmo, Mapping) else None
    try:
        refined = max(0.0, float((cumulative or {}).get("生命本源", 0) or 0))
        origin = max(0.0, float(root.get("origin", 0) or 0))
        extra = max(0.0, float(ext.get("mingge_origin", 0) or 0))
    except (TypeError, ValueError):
        refined = origin = extra = 0.0
    return round(BASE + origin + refined + extra, PRECISION)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, number) if number == number and number not in (float("inf"), float("-inf")) else default


def ensure(doc: Any) -> bool:
    """只在字段缺失时迁移一次；缺失/旧版 0 按原版境界初始化，显式 0 保留。"""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return False
    if CURRENT_KEY in ext:
        normalized = round(_number(ext.get(CURRENT_KEY)), PRECISION)
        if ext.get(CURRENT_KEY) != normalized:
            ext[CURRENT_KEY] = normalized
            return True
        return False
    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), Mapping) else {}
    supreme = ext.get("supreme") if isinstance(ext.get("supreme"), Mapping) else {}
    old = _number(legacy.get("生命本源")) or _number(supreme.get("life"))
    ext[CURRENT_KEY] = round(old if old > 0 else maximum(doc), PRECISION)
    return True


def current(doc: Any) -> float:
    ensure(doc)
    ext = getattr(doc, "ext", {}) or {}
    return round(_number(ext.get(CURRENT_KEY)), PRECISION)


def set_current(doc: Any, value: Any) -> float:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return 0.0
    amount = round(_number(value), PRECISION)
    ext[CURRENT_KEY] = amount
    supreme = ext.get("supreme")
    if isinstance(supreme, dict):
        supreme["life"] = amount
    legacy = ext.get("legacy_source")
    if isinstance(legacy, dict) and "生命本源" in legacy:
        legacy["生命本源"] = amount
    return amount


def reset_to_root_base(doc: Any) -> float:
    """原版灵根变化/支线结局规则：当前本源恢复至 100 + 当前灵根本源。"""
    ext = getattr(doc, "ext", {}) or {}
    root = ext.get("linggen") if isinstance(ext, Mapping) else None
    root = root if isinstance(root, Mapping) else {}
    return set_current(doc, BASE + _number(root.get("origin")))


def restore_to_max(doc: Any) -> float:
    return set_current(doc, maximum(doc))


def consume(doc: Any, amount: Any) -> tuple[bool, float]:
    cost = round(_number(amount), PRECISION)
    if cost <= 0:
        return False, current(doc)
    balance = current(doc)
    if balance < cost:
        return False, balance
    return True, set_current(doc, balance - cost)
