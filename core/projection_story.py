"""Original-data projection stories with per-world progress in the mirror save."""
from __future__ import annotations

import copy
import json
import random
from collections.abc import Mapping
from pathlib import Path

with Path(__file__).with_name("projection_events.json").open("r", encoding="utf-8") as _file:
    _raw_events = json.load(_file)

WORLD_DATA = {"魔卡少女樱": "魔法少女樱"}
EVENTS = dict(_raw_events)
EVENTS["魔卡少女樱"] = EVENTS.pop("魔法少女樱")


def _world_key(world: str) -> str:
    return WORLD_DATA.get(world, world)


def state_of(zt: dict, world: str) -> dict:
    root = zt.setdefault("exploration", {})
    raw = root.get(world)
    if not isinstance(raw, dict):
        raw = {}
    state = {
        "relations": dict(raw.get("relations") or {}),
        "flags": list(dict.fromkeys(raw.get("flags") or [])),
        "done": list(dict.fromkeys(raw.get("done") or [])),
        "recent": list(raw.get("recent") or [])[-3:],
        "pending": str(raw.get("pending") or ""),
        "count": max(0, int(raw.get("count", 0) or 0)),
        "stats": dict(raw.get("stats") or {}),
        "resolved": list(dict.fromkeys(raw.get("resolved") or []))[-100:],
    }
    root[world] = state
    return state


def _eligible(event: dict, state: dict, location: str = "", ignore_location: bool = False) -> bool:
    if not ignore_location and event.get("locations") and location not in event["locations"]:
        return False
    flags = set(state["flags"])
    if event.get("once") and event["id"] in state["done"]:
        return False
    if any(flag not in flags for flag in event.get("requires", [])):
        return False
    if event.get("requiresAny") and not flags.intersection(event["requiresAny"]):
        return False
    if flags.intersection(event.get("excludes", [])):
        return False
    return all(int(state["relations"].get(name, 0) or 0) >= int(value)
               for name, value in (event.get("minRelations") or {}).items())


def select_event(zt: dict, world: str, rng: random.Random, location: str = "") -> dict | None:
    events = EVENTS.get(world) or EVENTS.get(_world_key(world)) or []
    state = state_of(zt, world)
    pending = next((event for event in events if event["id"] == state["pending"]), None)
    if pending and _eligible(pending, state, location, ignore_location=True):
        return copy.deepcopy(pending)
    state["pending"] = ""
    eligible = [event for event in events if _eligible(event, state, location)]
    fresh = [event for event in eligible if event["id"] not in state["recent"]]
    if fresh:
        eligible = fresh
    if not eligible:
        return None
    weights = [max(1, int(event.get("weight", 1) or 1)) for event in eligible]
    roll = max(0.0, min(0.999999, float(rng.random() or 0))) * sum(weights)
    for event, weight in zip(eligible, weights):
        roll -= weight
        if roll < 0:
            return copy.deepcopy(event)
    return copy.deepcopy(eligible[-1])


def _apply_stat(zt: dict, world: str, stat: dict, changes: list[str]) -> None:
    path = list(stat.get("path") or [])
    if not path:
        return
    if path[0] == "诸天镜系统":
        target = zt
        path = path[1:]
    else:
        target = zt.setdefault("story_stats", {})
    if not path:
        return
    for key in path[:-1]:
        if not isinstance(target.get(key), dict):
            target[key] = {}
        target = target[key]
    key = path[-1]
    before = float(target.get(key, 0) or 0)
    minimum = float(stat.get("min", 0))
    maximum = float(stat.get("max", 9_007_199_254_740_991))
    after = max(minimum, min(maximum, before + float(stat.get("amount", 0) or 0)))
    target[key] = int(after) if after.is_integer() else after
    delta = after - before
    if delta:
        label = str(stat.get("label") or key)
        changes.append(f"{label} {delta:+g}")


def resolve_event(
    zt: dict, event_id: str, choice: int, resolution_id: str = ""
) -> tuple[bool, str, dict | None]:
    world = next((key for key, events in EVENTS.items()
                  if any(event["id"] == event_id for event in events)), None)
    if world is None:
        return False, "剧情事件已失效。", None
    events = EVENTS[world]
    event = next(event for event in events if event["id"] == event_id)
    options = event.get("options") or []
    if choice < 1 or choice > len(options):
        return False, f"请输入 1-{len(options)} 作出抉择。", None
    state = state_of(zt, world)
    if resolution_id and resolution_id in state["resolved"]:
        pending = next((item for item in events if item["id"] == state["pending"]), None)
        return True, "该选择已结算。", copy.deepcopy(pending)

    selected = options[choice - 1]
    effect = selected.get("effect") or {}
    changes = []
    for name, amount in (effect.get("relations") or {}).items():
        before = int(state["relations"].get(name, 0) or 0)
        after = max(-100, min(100, before + int(amount)))
        state["relations"][name] = after
        if after != before:
            changes.append(f"{name}关系 {after - before:+d}")
    for flag in effect.get("flags", []):
        if flag not in state["flags"]:
            state["flags"].append(flag)

    materials = zt.setdefault("materials", {})
    for name, amount in (effect.get("materials") or {}).items():
        before = int(materials.get(name, 0) or 0)
        after = max(0, before + int(amount))
        materials[name] = after
        if after != before:
            changes.append(f"{name} {after - before:+d}")
    for stat in effect.get("stats", []):
        _apply_stat(zt, world, stat, changes)

    if state["pending"] == event_id:
        state["pending"] = ""
    state["pending"] = str(effect.get("nextEvent") or "")
    if event.get("once") and event_id not in state["done"]:
        state["done"].append(event_id)
    state["recent"] = (state["recent"] + [event_id])[-3:]
    state["count"] += 1
    if resolution_id:
        state["resolved"] = (state["resolved"] + [resolution_id])[-100:]
    zt["story_version"] = int(zt.get("story_version", 0) or 0) + 1

    text = selected.get("result", "")
    if changes:
        text += "\n" + "；".join(changes)
    pending = next((item for item in events if item["id"] == state["pending"]), None)
    return True, text, copy.deepcopy(pending)


def event_by_id(world: str, event_id: str) -> dict | None:
    events = EVENTS.get(world) or EVENTS.get(_world_key(world)) or []
    return copy.deepcopy(next((event for event in events if event["id"] == event_id), None))
