"""World-year schedule for the original strange-emperor plane destruction clock."""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

DESTRUCTION_INTERVAL = 2_000
FIRST_DESTRUCTION_DELAY = 10
POLL_INTERVAL = 30
MAX_PLANES_PER_ROUND = 2
DESTRUCTION_PLANES = (
    "凡间", "仙界", "下界八域", "遮天位面", "九天十地", "界海", "仙域",
)


def _new_state() -> dict[str, Any]:
    return {
        "active": False, "activity_id": "", "started_at": 0.0,
        "started_world_year": 0, "next_check_at": 0.0,
        "next_world_year": 0, "first_round_pending": False,
        "rounds": 0, "protected_planes": {}, "rescue_used": False,
        "rescue_round": 0, "history": [], "stopped": False,
    }


def state_of(world_state: dict) -> dict[str, Any]:
    state = world_state.get("plane_destruction")
    if not isinstance(state, dict):
        state = _new_state()
        world_state["plane_destruction"] = state
    base = _new_state()
    for key, value in base.items():
        state.setdefault(key, value)
    state["active"] = bool(state.get("active"))
    state["activity_id"] = str(state.get("activity_id") or "")
    for key in ("started_world_year", "next_world_year", "rounds", "rescue_round"):
        try:
            state[key] = max(0, int(state.get(key, 0) or 0))
        except (TypeError, ValueError, OverflowError):
            state[key] = 0
    for key in ("started_at", "next_check_at"):
        try:
            state[key] = max(0.0, float(state.get(key, 0) or 0))
        except (TypeError, ValueError, OverflowError):
            state[key] = 0.0
    if not isinstance(state.get("protected_planes"), dict):
        state["protected_planes"] = {}
    state["history"] = list(state.get("history") or [])[-100:]
    state["rescue_used"] = bool(state.get("rescue_used"))
    state["first_round_pending"] = bool(state.get("first_round_pending"))
    state["stopped"] = bool(state.get("stopped"))
    return state


def sync(world_state: dict, activity_id: str | None, world_year: int,
         now: float) -> dict[str, Any]:
    state = state_of(world_state)
    key = str(activity_id or "")
    year = max(0, int(world_year))
    if not key:
        state["active"] = False
        state["activity_id"] = ""
        state["stopped"] = True
        state["first_round_pending"] = False
        return state
    if state["active"] and state["activity_id"] == key:
        return state
    state.update({
        "active": True, "activity_id": key, "started_at": float(now),
        "started_world_year": year,
        "next_check_at": float(now) + FIRST_DESTRUCTION_DELAY,
        "next_world_year": year + DESTRUCTION_INTERVAL,
        "first_round_pending": True, "rounds": 0,
        "protected_planes": {}, "rescue_used": False, "rescue_round": 0, "stopped": False,
    })
    return state


def tick(state: dict, world_year: int, now: float,
         destroyed_planes: Mapping | None = None,
         rng: random.Random | None = None) -> list[str]:
    """Run at most one round per poll; yearly jumps never replay missed rounds."""
    if not isinstance(state, dict) or not state.get("active"):
        return []
    now = float(now)
    year = max(0, int(world_year))
    if now < float(state.get("next_check_at", 0) or 0):
        return []
    state["next_check_at"] = now + POLL_INTERVAL
    if not state.get("first_round_pending") and year < int(state.get("next_world_year", 0) or 0):
        return []

    destroyed = destroyed_planes if isinstance(destroyed_planes, Mapping) else {}
    protected = state.get("protected_planes")
    protected = protected if isinstance(protected, Mapping) else {}
    candidates = [name for name in DESTRUCTION_PLANES
                  if name not in destroyed and name not in protected]
    rng = rng or random.Random()
    selected = (rng.sample(candidates, min(MAX_PLANES_PER_ROUND, len(candidates)))
                if candidates else [])
    old_threshold = int(state.get("next_world_year", 0) or 0)
    state["first_round_pending"] = False
    state["rounds"] = int(state.get("rounds", 0) or 0) + 1
    state["next_world_year"] = max(old_threshold + DESTRUCTION_INTERVAL, year + 1)
    history = list(state.get("history") or [])
    history.append({"round": state["rounds"], "world_year": year,
                    "planes": list(selected), "at": now})
    state["history"] = history[-100:]
    return selected


def protect(state: dict, plane: str, uid: str, name: str, world_year: int,
            now: float, destroyed_planes: Mapping | None = None) -> tuple[bool, str]:
    if not isinstance(state, dict) or not state.get("active"):
        return False, "当前没有进行中的诸天位面毁灭时钟。"
    if state.get("rescue_used"):
        return False, "本轮黑暗动乱救场机会已经用过。"
    if plane not in DESTRUCTION_PLANES:
        return False, "此位面不在可救场的目标范围内。"
    destroyed = destroyed_planes if isinstance(destroyed_planes, Mapping) else {}
    if plane in destroyed:
        return False, f"【{plane}】已经毁灭，无法再次保护。"
    protected = state.get("protected_planes")
    if not isinstance(protected, dict):
        protected = {}
        state["protected_planes"] = protected
    if plane in protected:
        return False, f"【{plane}】已经有人护持。"
    protected[plane] = {"uid": str(uid), "name": str(name),
                        "world_year": max(0, int(world_year)), "at": float(now)}
    state["rescue_used"] = True
    return True, f"【帝境救场】你护住【{plane}】，本轮毁灭时钟将跳过该位面。"
