"""沧澜界 · 彼岸世界/真世界：基础世界层（纯函数，无 IO）。

对应原版 ``apps/SecretPlace/OtherShoreWorld.js`` + ``model/otherShoreWorld.js``。
本批只移植「世界 / 坐标 / 星辰观测 / 移动路径 / 探索贡献 / 道标与通关」等
基础世界层纯函数，世界状态由 SQLite 单例表（``other_shore_state``）承载，
未接 redis / web session 的部分由 ``other_shore_state`` 单进程原子更新代替。

关键契约（对齐原版）：
- 世界半径 ``OTHER_SHORE_MAP_RADIUS = 4``；中心星坐标 (0,0)；
- 阶段序列 ``unobserved → sensed → visited → anchored → cleared``；
- 中心星 (0,0) 初始即 ``anchored``；
- 坐标为六边形坐标 ``(q, r)``，距离 = 六边形最短距离；
- 移动路径必须由相邻大星（距离 1）组成；
- 踏足（visited）后才可贡献探索度与建立道标，完成（anchored）后才能通关。
"""

from __future__ import annotations

import math
from typing import Any

OTHER_SHORE_MAP_RADIUS = 4

# 星辰阶段顺序（PHASE_RANK）
OTHER_SHORE_PHASES: tuple[str, ...] = (
    "unobserved",
    "sensed",
    "visited",
    "anchored",
    "cleared",
)

# 六边形方向 (q, r)
OTHER_SHORE_HEX_DIRECTIONS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
)


def _other_shore_coordinate_id(coordinate_or_q, maybe_r) -> str:
    return f"{int(coordinate_or_q)},{int(maybe_r)}"


# 公开别名：内部 create 等函数按原版 API 名引用该函数
other_shore_coordinate_id = _other_shore_coordinate_id


def get_other_shore_hex_distance(left, right) -> int:
    a = _normalize_coordinate(left)
    b = _normalize_coordinate(right)
    dq = a["q"] - b["q"]
    dr = a["r"] - b["r"]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def _normalize_coordinate(coordinate_or_q, maybe_r=None) -> dict[str, int]:
    import re

    if isinstance(coordinate_or_q, str):
        full = re.fullmatch(r"(-?\d+),(-?\d+)", coordinate_or_q)
        if not full:
            raise ValueError(f"无效的沧澜界坐标：{coordinate_or_q}")
        return {"q": int(full.group(1)), "r": int(full.group(2))}
    if isinstance(coordinate_or_q, (list, tuple)):
        return {"q": int(coordinate_or_q[0]), "r": int(coordinate_or_q[1])}
    if coordinate_or_q and isinstance(coordinate_or_q, dict):
        return {"q": int(coordinate_or_q["q"]), "r": int(coordinate_or_q["r"])}
    return {"q": int(coordinate_or_q), "r": int(maybe_r)}


def _hash(value: str) -> int:
    result = 2166136261
    for character in str(value):
        result ^= ord(character)
        result = (result * 16777619) & 0xFFFFFFFF
    return result & 0xFFFFFFFF


def _coordinates_within_radius(radius: int) -> list[dict[str, int]]:
    coords: list[dict[str, int]] = []
    for q in range(-radius, radius + 1):
        min_r = max(-radius, -q - radius)
        max_r = min(radius, -q + radius)
        for r in range(min_r, max_r + 1):
            coords.append({"q": q, "r": r})
    return coords


# ---- 大星数据（含关键星与程序生成星池） ----

OTHER_SHORE_KEY_STARS: tuple[dict[str, Any], ...] = (
    {
        "q": 0,
        "r": 0,
        "name": "沧澜祖星",
        "kind": "origin",
        "risk": 0,
        "anchorRequirement": 0,
        "description": "先秦炼气士曾由此借灵界裂缝返乡，初始道标仍记录着那条古航路。",
    },
    {
        "q": 4,
        "r": 0,
        "name": "观潮天门",
        "kind": "gate",
        "risk": 4,
        "anchorRequirement": 8,
        "description": "观测诸世界潮汐的古老天门。",
    },
    {
        "q": 0,
        "r": 4,
        "name": "归墟海眼",
        "kind": "abyss",
        "risk": 5,
        "anchorRequirement": 9,
        "description": "无数星海法则在此沉降。",
    },
    {
        "q": -4,
        "r": 4,
        "name": "万古葬星",
        "kind": "tomb",
        "risk": 5,
        "anchorRequirement": 9,
        "description": "葬着多个纪元的大星残骸。",
    },
    {
        "q": -4,
        "r": 0,
        "name": "纪元碑林",
        "kind": "archive",
        "risk": 3,
        "anchorRequirement": 7,
        "description": "彼岸古文明留下的纪元记录库。",
    },
    {
        "q": 0,
        "r": -4,
        "name": "裂界母锚",
        "kind": "anchor",
        "risk": 5,
        "anchorRequirement": 10,
        "description": "诸灵界裂缝的源头母锚，残存坐标指向先秦炼气士失落的彼岸道场。",
    },
    {
        "q": 4,
        "r": -4,
        "name": "彼岸渡口",
        "kind": "harbor",
        "risk": 4,
        "anchorRequirement": 8,
        "description": "先秦炼气士横渡两岸的古渡口，复原渡碑可反向校准灵界裂缝。",
    },
    {
        "q": 2,
        "r": -1,
        "name": "无相神墟",
        "kind": "ruin",
        "risk": 3,
        "anchorRequirement": 6,
        "description": "神形与法则均已磨灭的遗墟。",
    },
    {
        "q": 1,
        "r": -1,
        "name": "玄阙神炉",
        "kind": "forge",
        "risk": 4,
        "anchorRequirement": 7,
        "description": "亦称太初熔星，先秦炼气士曾在此锻造星路阵眼，如今炉心孕育着同源灾核。",
    },
    {
        "q": 1,
        "r": 2,
        "name": "太初熔星",
        "kind": "forge",
        "risk": 4,
        "anchorRequirement": 7,
        "description": "仍在锻造未知物质的燃烧大星。",
    },
    {
        "q": -2,
        "r": 3,
        "name": "帝落残庭",
        "kind": "palace",
        "risk": 4,
        "anchorRequirement": 8,
        "description": "某位古帝最后一座星空王庭。",
    },
    {
        "q": -3,
        "r": 1,
        "name": "超维观测站",
        "kind": "observatory",
        "risk": 5,
        "anchorRequirement": 9,
        "description": "从更高维度记录沧澜界的废弃设施。",
    },
    {
        "q": 1,
        "r": -3,
        "name": "禁宝司旧都",
        "kind": "citadel",
        "risk": 5,
        "anchorRequirement": 10,
        "description": "古文明禁宝司曾经的清算中枢。",
    },
)

OTHER_SHORE_PROCEDURAL_STAR_POOL: tuple[dict[str, Any], ...] = (
    {
        "id": "life",
        "names": ("青禾大星", "九叶大星", "长生大星"),
        "kind": "life",
        "risk": 1,
        "anchorRequirement": 3,
    },
    {
        "id": "ruin",
        "names": ("断垣大星", "沉碑大星", "灰殿大星"),
        "kind": "ruin",
        "risk": 2,
        "anchorRequirement": 4,
    },
    {
        "id": "tide",
        "names": ("潮鸣大星", "叠浪大星", "回澜大星"),
        "kind": "tide",
        "risk": 3,
        "anchorRequirement": 5,
    },
    {
        "id": "rift",
        "names": ("破界大星", "缝天大星", "裂光大星"),
        "kind": "rift",
        "risk": 4,
        "anchorRequirement": 6,
    },
    {
        "id": "civilization",
        "names": ("古城大星", "铸文大星", "众王大星"),
        "kind": "civilization",
        "risk": 2,
        "anchorRequirement": 5,
    },
    {
        "id": "dead",
        "names": ("寂灭大星", "暗烬大星", "无昼大星"),
        "kind": "dead",
        "risk": 3,
        "anchorRequirement": 4,
    },
)

_PHASE_RANK: dict[str, int] = {phase: index for index, phase in enumerate(OTHER_SHORE_PHASES)}


def _procedural_star(seed: str, coordinate: dict[str, int]) -> dict[str, Any]:
    id_str = other_shore_coordinate_id(coordinate["q"], coordinate["r"])
    value = _hash(f"{seed}:{id_str}")
    template = OTHER_SHORE_PROCEDURAL_STAR_POOL[value % len(OTHER_SHORE_PROCEDURAL_STAR_POOL)]
    base_name = template["names"][(value // 17) % len(template["names"])]
    return {
        "id": id_str,
        "q": coordinate["q"],
        "r": coordinate["r"],
        "keyStar": False,
        "templateId": template["id"],
        "name": f"{base_name}·{format(value, 'x')[:3].upper()}",
        "kind": template["kind"],
        "risk": template["risk"],
        "anchorRequirement": template["anchorRequirement"],
        "description": "尚未录入古星图的沧澜大星。",
    }


def create_other_shore_world(seed: str = "canglan") -> dict[str, Any]:
    """创建沧澜界世界（键星表 + 程序星 + 初始状态）。"""
    seed_str = str(seed)
    key_stars = {other_shore_coordinate_id(star["q"], star["r"]): dict(star) for star in OTHER_SHORE_KEY_STARS}
    stars = []
    for c in _coordinates_within_radius(OTHER_SHORE_MAP_RADIUS):
        id_str = other_shore_coordinate_id(c["q"], c["r"])
        if id_str in key_stars:
            star = dict(key_stars[id_str])
            star["id"] = id_str
            star["q"] = c["q"]
            star["r"] = c["r"]
            star["keyStar"] = True
        else:
            star = _procedural_star(seed_str, c)
            star["keyStar"] = False
        stars.append(star)
    states: dict[str, dict[str, Any]] = {}
    for star in stars:
        is_center = star["id"] == "0,0"
        states[star["id"]] = {
            "phase": "anchored" if is_center else "unobserved",
            "contribution": star["anchorRequirement"] if is_center else 0,
            "contributors": {},
        }
    return {
        "version": 1,
        "seed": seed_str,
        "radius": OTHER_SHORE_MAP_RADIUS,
        "centerId": "0,0",
        "stars": stars,
        "states": states,
    }


def require_star(world: dict[str, Any], coordinate) -> dict[str, Any]:
    if isinstance(coordinate, str):
        id_str = coordinate
        stars = world.get("stars")
        if not stars or not any(item.get("id") == id_str for item in stars):
            raise ValueError(f"沧澜界坐标不存在：{id_str}")
        return next(item for item in stars if item.get("id") == id_str)
    id_str = other_shore_coordinate_id(coordinate["q"], coordinate["r"])
    stars = world.get("stars")
    if not stars or not any(item.get("id") == id_str for item in stars):
        raise ValueError(f"沧澜界坐标不存在：{id_str}")
    return next(item for item in stars if item.get("id") == id_str)


def find_star(world: dict[str, Any], coordinate) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a player-supplied coordinate without leaking a handler exception."""
    try:
        return require_star(world, coordinate), None
    except (KeyError, TypeError, ValueError) as exc:
        return None, str(exc)


def state_for(world: dict[str, Any], coordinate) -> tuple[dict[str, Any], dict[str, Any]]:
    star = require_star(world, coordinate)
    state = world.get("states", {}).get(star["id"])
    if not state or _PHASE_RANK.get(state.get("phase")) is None:
        raise ValueError(f"沧澜界星辰状态无效：{star['id']}")
    return star, state


def update_state(world: dict[str, Any], star_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return {**world, "states": {**world.get("states", {}), star_id: state}}


def advance_phase(world: dict[str, Any], coordinate, target_phase: str) -> dict[str, Any]:
    star, state = state_for(world, coordinate)
    if _PHASE_RANK.get(target_phase, 99) <= _PHASE_RANK.get(state.get("phase"), -1):
        return world
    return update_state(world, star["id"], {**state, "phase": target_phase})


def get_other_shore_neighbors(world: dict[str, Any], coordinate) -> list[dict[str, Any]]:
    origin = _normalize_coordinate(coordinate["q"], coordinate["r"])
    require_star(world, origin)
    by_id = {item["id"]: item for item in world.get("stars", [])}
    return [
        _hit
        for _hit in (
            by_id.get(other_shore_coordinate_id(origin["q"] + dq, origin["r"] + dr))
            for dq, dr in OTHER_SHORE_HEX_DIRECTIONS
        )
        if _hit is not None
    ]


def find_other_shore_shortest_path(world: dict[str, Any], from_, to) -> list[str] | None:
    start_id = require_star(world, from_).get("id")
    goal_id = require_star(world, to).get("id")
    if start_id == goal_id:
        return [start_id]
    queue = [start_id]
    previous: dict[str, str | None] = {start_id: None}
    for _ in range(len(queue) + 1):
        if not queue:
            return None
        current = queue.pop(0)
        for neighbor in get_other_shore_neighbors(world, current):
            nid = neighbor["id"]
            if nid in previous:
                continue
            previous[nid] = current
            if nid == goal_id:
                path = [goal_id]
                while previous.get(path[0]) is not None:
                    path.insert(0, previous[path[0]])
                return path
            queue.append(nid)
    return None


def observe_other_shore_stars(world: dict[str, Any], origin, range_=1) -> dict[str, Any]:
    center = _normalize_coordinate(origin["q"], origin["r"])
    require_star(world, center)
    distance = int(range_)
    if not isinstance(distance, int) or distance < 0:
        raise ValueError("观测范围必须是非负整数")
    next_world = world
    for star in world.get("stars", []):
        if get_other_shore_hex_distance(center, star) <= distance:
            next_world = advance_phase(next_world, star["id"], "sensed")
    return next_world


def visit_other_shore_star(world: dict[str, Any], coordinate) -> dict[str, Any]:
    star, state = state_for(world, coordinate)
    if _PHASE_RANK.get(state.get("phase"), -1) < _PHASE_RANK["sensed"]:
        raise ValueError("需先观测该大星才能踏足")
    return advance_phase(world, coordinate, "visited")


def contribute_other_shore_exploration(
    world: dict[str, Any],
    coordinate,
    contributor_id: str,
    amount: float = 1,
) -> dict[str, Any]:
    star, state = state_for(world, coordinate)
    if _PHASE_RANK.get(state.get("phase"), -1) < _PHASE_RANK["visited"]:
        raise ValueError("踏足该大星后才能贡献探索度")
    value = float(amount)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("探索贡献必须大于0")
    contributor = str(contributor_id or "").strip()
    if not contributor:
        raise ValueError("探索贡献者不能为空")
    existing = max(0.0, float(state.get("contributors", {}).get(contributor, 0) or 0))
    remaining = max(0.0, float(star.get("anchorRequirement", 0)) - float(state.get("contribution", 0)))
    granted = min(value, max(0.0, 1 - existing), remaining)
    if granted <= 0:
        return world
    contributors = dict(state.get("contributors", {}))
    contributors[contributor] = existing + granted
    return update_state(world, star["id"], {
        **state,
        "contribution": float(state.get("contribution", 0)) + granted,
        "contributors": contributors,
    })


def anchor_other_shore_star(world: dict[str, Any], coordinate) -> dict[str, Any]:
    star, state = state_for(world, coordinate)
    if _PHASE_RANK.get(state.get("phase"), -1) < _PHASE_RANK["visited"]:
        raise ValueError("踏足该大星后才能建立道标")
    if float(state.get("contribution", 0)) < float(star.get("anchorRequirement", 0)):
        raise ValueError(
            f"探索贡献不足：{state.get('contribution', 0)}/{star.get('anchorRequirement', 0)}"
        )
    return advance_phase(world, star["id"], "anchored")


def clear_other_shore_star(world: dict[str, Any], coordinate) -> dict[str, Any]:
    star, state = state_for(world, coordinate)
    if _PHASE_RANK.get(state.get("phase"), -1) < _PHASE_RANK["anchored"]:
        raise ValueError("建立道标后才能完成该大星")
    return advance_phase(world, coordinate, "cleared")


def clear_other_shore_campaign_star(world: dict[str, Any], coordinate) -> dict[str, Any]:
    star, state = state_for(world, coordinate)
    if _PHASE_RANK.get(state.get("phase"), -1) < _PHASE_RANK["visited"]:
        raise ValueError("踏足该大星后才能完成战役")
    if _PHASE_RANK.get(state.get("phase"), -1) >= _PHASE_RANK["anchored"]:
        return clear_other_shore_star(world, star["id"])
    contributed = update_state(world, star["id"], {
        **state,
        "contribution": max(float(state.get("contribution", 0)), float(star.get("anchorRequirement", 0))),
    })
    return clear_other_shore_star(anchor_other_shore_star(contributed, star["id"]), star["id"])


def calculate_other_shore_travel(
    world: dict[str, Any], path, player_or_realm, remainder: float = 0
) -> dict[str, Any]:
    if not isinstance(path, list) or len(path) < 1:
        raise ValueError("移动路径不能为空")
    ids = [require_star(world, coordinate).get("id") for coordinate in path]
    for index in range(1, len(ids)):
        if get_other_shore_hex_distance(ids[index - 1], ids[index]) != 1:
            raise ValueError("移动路径必须由相邻大星组成")
    entered = ids[1:]
    unanchored_steps = sum(
        1
        for id_str in entered
        if _PHASE_RANK.get(world.get("states", {}).get(id_str, {}).get("phase"), -1)
        not in ("anchored", "cleared")
    )
    result = {
        "path": ids,
        "totalSteps": len(entered),
        "anchoredSteps": len(entered) - unanchored_steps,
    }
    result.update(_calculate_other_shore_mind_cost_from_rules(player_or_realm, unanchored_steps, remainder))
    return result


def serialize_other_shore_world(world: dict[str, Any]) -> dict[str, Any]:
    stars = []
    for star in world.get("stars", []):
        state = world.get("states", {}).get(star.get("id"))
        if state is None:
            state = {}
        phase = state.get("phase")
        discovered = phase != "unobserved"
        stars.append({
            "id": star.get("id"),
            "q": star.get("q"),
            "r": star.get("r"),
            "phase": phase,
            "discovered": discovered,
            "visited": _PHASE_RANK.get(phase, -1) >= _PHASE_RANK["visited"],
            "anchored": _PHASE_RANK.get(phase, -1) >= _PHASE_RANK["anchored"],
            "cleared": phase == "cleared",
            "contribution": state.get("contribution", 0),
            "contributors": dict(state.get("contributors", {}) or {}),
            **({"name": star["name"], "kind": star["kind"], "risk": star["risk"],
               "keyStar": star.get("keyStar", False), "anchorRequirement": star.get("anchorRequirement", 0),
               "description": star.get("description", "")}
              if discovered else {}),
        })
    return {
        "version": world.get("version"),
        "seed": world.get("seed"),
        "radius": world.get("radius"),
        "centerId": world.get("centerId"),
        "stars": stars,
    }


def _calculate_other_shore_mind_cost_from_rules(player_or_realm, unanchored_steps, remainder=0):  # noqa: D401
    from .other_shore_rules import calculate_other_shore_mind_cost

    return calculate_other_shore_mind_cost(player_or_realm, unanchored_steps, remainder)
