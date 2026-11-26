"""凡间坐标 + 位面旅行。

数据：data/位面坐标.json（11 张 1000×1000 方图，178 个地点，region/site 两级；异域无方图）。
原版：model/planeCoords.js + model/weimianTravel.js（1222 行，含维度壁垒/仙帝权柄/岁云套等）。
本移植只取诸天万界这一层（11 个有位图的位面，同层无壁垒）：
- 坐标：每位面独立坐标，界内移动即时，踩到地点首次发现给灵石/修为
- 位面：按境界门槛解锁 + 记忆坐标（星图/求购/每日线索三条获取路径）
- 旅行：航程 = 位面等级差 × 15 分钟 ×（1-境界减免），消耗修为/血气，异步抵达
shortcut：无方图高维位面只应用维度壁垒/仙帝权柄规则；传送阵令牌等级仍未完整分级。
全服位面毁灭由主入口传入 barrier_check；在途目的地崩灭时折返出发位面且不返还旅费。
"""

from __future__ import annotations
from .clock import day_key
from . import timed_action
from . import plane_travel_rules

import copy
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_PLANE = "凡间"
FOREIGN_REALM = plane_travel_rules.FOREIGN_REALM
TIME_RIVER_PLANE = "时间长河"
TIME_RIVER_AUTHORITY_GATE = 20
TIME_RIVER_BARRIER_MINUTES = 60
TIME_RIVER_EXP_COST = 1_000_000_000
TIME_RIVER_XUEQI_COST = 1_500_000_000
CMD_HINT = "#前往"

# 顺序 = 解锁推进顺序，level 即原版 PLACE_LOCATION_MAP 的位面坐标层级
PLANES: tuple[str, ...] = (
    "凡间", "下界八域", "遮天位面", "九天十地", "异域", "界海",
    "太初星墟", "小阴间", "大阴间", "仙界", "仙域", "阳间",
)
LEVELS: dict[str, float] = {
    "凡间": 0, "仙界": 1, "下界八域": 1.5, "遮天位面": 2, "九天十地": 2.5,
    "异域": plane_travel_rules.FOREIGN_REALM_LEVEL,
    "界海": 3, "太初星墟": 3.5, "小阴间": 4, "大阴间": 5, "仙域": 6, "阳间": 7,
}
# 门槛取本插件境界表下标（0 凡人 / 41 地仙 / 46 大罗金仙 / 49 究极仙王）
GATES: dict[str, int] = {
    "凡间": 0, "下界八域": 16, "遮天位面": 21, "九天十地": 26, "界海": 31,
    "太初星墟": 34, "小阴间": 36, "大阴间": 39, "仙界": 41, "仙域": 46, "阳间": 49,
    "异域": plane_travel_rules.FOREIGN_AUTHORITY_GATE,
}

# ---------------------------------------------------------------- W7-5b 维度壁垒
# 原版 model/weimianTravel.js:128-162：高维位面无方图，靠「破界强度」而非境界进入
HIGH_DIMENSIONS: dict[str, dict] = {
    "上苍之上": {"layer": 1, "power": 50, "desc": "界壁之上的第一重天，仙帝方可凭权柄触及。"},
    "超维宇宙": {"layer": 2, "power": 30, "desc": "维度褶皱里的残破宇宙，到处是别处的碎片。"},
    "厄土高原": {"layer": 3, "power": 60, "desc": "诡异源头盘踞之地，业力深重者反被吸引。"},
    "永恒未知之地": {"layer": 3, "power": 65, "desc": "时间失去意义，进入者多不再回来。"},
    "百维真界": {"layer": 4, "power": 80, "desc": "百重维度叠成的真界，一沙一世界。"},
    "原初宇宙海": {"layer": 5, "power": 90, "desc": "万物未分之前的宇宙海，混沌翻涌。"},
    "千维宙古界": {"layer": 6, "power": 100, "desc": "千维交织的宙古之界，神纹如网。"},
    "万维梵宇界": {"layer": 7, "power": 120, "desc": "万维梵唱，一花一梵宇。"},
    "神维丝线海": {"layer": 8, "power": 150, "desc": "维度之丝汇成的海，尽头通向不可名状。"},
}
BREAKING_POWER: dict[int, int] = {20: 30, 21: 65, 22: 80, 23: 100, 24: 120, 25: 150}
EMPEROR_FREE_TRAVEL: frozenset[str] = frozenset(
    set(PLANES) | {"上苍之上", "永恒未知之地", "厄土高原"})
MARK_COST = 50_000_000           # 原版 ENGRAVE_LINGSHI_COST = 5e7

# 高维位面并入可旅行表：层级即壁垒重数，境界门槛交由破界强度判定
PLANES = PLANES + tuple(HIGH_DIMENSIONS) + (TIME_RIVER_PLANE,)
LEVELS.update({name: float(cfg["layer"] + 7) for name, cfg in HIGH_DIMENSIONS.items()})
GATES.update({name: 10 ** 9 for name in HIGH_DIMENSIONS})
LEVELS[TIME_RIVER_PLANE] = -1.0  # 原版独立时序域层级
GATES[TIME_RIVER_PLANE] = TIME_RIVER_AUTHORITY_GATE

BASE_MIN_PER_LEVEL = 15
REDUCE_MAX = plane_travel_rules.REALM_REDUCTION_MAX
EXP_PER_LEVEL = 800_000
XUEQI_PER_LEVEL = 1_200_000
CLUE_COST = 1_000_000            # #求购位面线索
STAR_MAP_ALT_COST = 500_000      # 无星图时 #记坐标 的灵石替代
CLUE_CHANCE = 0.15               # #探索位面线索 每日一次
SITE_STONES = 5_000              # 首次发现地点
SITE_EXP = 20_000

# 原版 model/weimianTravel.js 中有实体方图的位面；异域及高维地点只保留抽象锚点。
SHENGXU_PLANES = frozenset({"小阴间", "大阴间", "阳间"})
SQUARE_MAP_PLANES = frozenset({
    "凡间", "仙界", "下界八域", "遮天位面", "九天十地", "界海",
    "太初星墟", "仙域", "小阴间", "大阴间", "阳间",
})
ORIGINAL_TRAVEL_LEVELS = {
    "凡间": 0, "仙界": 1, "下界八域": 1.5, "遮天位面": 2,
    "九天十地": 2.5, "界海": 3, "异域": 3.2, "太初星墟": 3.5,
    "时间长河": 3.6, "小阴间": 4, "大阴间": 5, "仙域": 6, "阳间": 7,
    "上苍之上": 40, "永恒未知之地": 42, "厄土高原": 20,
    "超维宇宙": 45, "百维真界": 60, "原初宇宙海": 80,
    "千维宙古界": 100, "万维梵宇界": 120, "神维丝线海": 150,
}


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）ext["plane"]。直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("plane")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("current", DEFAULT_PLANE)
    st.setdefault("coords", {})
    for name in list(st["coords"]):
        if not has_square_map(str(name)):
            st["coords"].pop(name, None)
    st.setdefault("known", [DEFAULT_PLANE])
    st.setdefault("discovered", {})
    st.setdefault("clue_day", "")
    st.setdefault("travel", None)
    if "portal_uses" not in st:
        legacy = ext.get("legacy_source")
        legacy = legacy if isinstance(legacy, Mapping) else {}
        def _legacy_uses(key: str) -> int:
            try:
                return max(0, int(legacy.get(key, 0) or 0))
            except (TypeError, ValueError, OverflowError):
                return 0
        st["portal_uses"] = {
            "low": _legacy_uses("位面传送次数"),
            "high": _legacy_uses("高级传送次数"),
        }
    if "wind_uses" not in st:
        legacy = ext.get("legacy_source")
        legacy = legacy if isinstance(legacy, Mapping) else {}
        try:
            st["wind_uses"] = max(0, int(legacy.get("天外清风加速次数", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            st["wind_uses"] = 0
    st.setdefault("marks", {})        # 已刻画坐标：位面 → {at}；坐标锚点本身不是二维坐标
    for anchor in st["marks"].values():
        if isinstance(anchor, dict):
            anchor.pop("x", None)
            anchor.pop("y", None)
    st.setdefault("destroyed", {})    # 位面毁灭记录：位面 → {source,at}
    ext["plane"] = st
    return st


def current(st: Mapping) -> str:
    return str(st.get("current") or DEFAULT_PLANE)


def known_of(st: Mapping) -> list[str]:
    return [str(x) for x in (st.get("known") or [DEFAULT_PLANE])]


def coord_of(st: Mapping, plane: str | None = None) -> dict | None:
    plane = plane or current(st)
    if plane not in SQUARE_MAP_PLANES:
        return None
    c = (st.get("coords") or {}).get(plane)
    if isinstance(c, Mapping) and isinstance(c.get("x"), int) and isinstance(c.get("y"), int):
        return {"x": int(c["x"]), "y": int(c["y"])}
    return None


def discovered_of(st: Mapping, plane: str) -> list[str]:
    got = (st.get("discovered") or {}).get(plane)
    return [str(x) for x in got] if isinstance(got, list) else []


# ---------------------------------------------------------------- 坐标数据

def has_square_map(plane: str) -> bool:
    return plane in SQUARE_MAP_PLANES


def has_coordinate(doc: Any, plane: str) -> bool:
    """记忆锚点是位面级的；异域等无方图位面不需要也不生成 x/y。"""
    from . import flower
    from .extra_cultivation import realm_authority_level
    authority = realm_authority_level(doc)
    if authority >= plane_travel_rules.EMPEROR_FREE_TRAVEL_GATE and plane in plane_travel_rules.EMPEROR_FREE_LOCATIONS:
        return True
    if plane in SHENGXU_PLANES and (authority >= 20 or flower.state_of(doc) is not None):
        return True
    return plane in known_of(state_of(doc))


def locations_of(data: Mapping, plane: str) -> list[dict]:
    entry = data.get(plane) if isinstance(data, Mapping) else None
    locs = entry.get("locations") if isinstance(entry, Mapping) else None
    return [x for x in locs if isinstance(x, Mapping)] if isinstance(locs, list) else []


def sites_of(data: Mapping, plane: str) -> list[dict]:
    return [x for x in locations_of(data, plane) if str(x.get("type")) == "site"]


def in_bounds(loc: Mapping, x: int, y: int) -> bool:
    b = loc.get("bounds") or {}
    try:
        return b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"]
    except (KeyError, TypeError):
        return False


def chain_at(data: Mapping, plane: str, x: int, y: int) -> list[dict]:
    """坐标归属链，外→内。空列表表示荒野。"""
    hits = [l for l in locations_of(data, plane) if in_bounds(l, x, y)]
    if not hits:
        return []
    ids = {l.get("id"): l for l in hits}
    leaf = next((h for h in hits if not any(o.get("parent") == h.get("id") for o in hits)), hits[-1])
    chain = [leaf]
    cur = leaf
    while cur.get("parent") in ids:
        cur = ids[cur["parent"]]
        chain.insert(0, cur)
    return chain


def center(loc: Mapping) -> dict:
    b = loc.get("bounds") or {}
    return {"x": (int(b["x1"]) + int(b["x2"])) // 2, "y": (int(b["y1"]) + int(b["y2"])) // 2}


def random_coord(loc: Mapping, rng: Any) -> dict:
    b = loc.get("bounds") or {}
    return {
        "x": int(b["x1"]) + rng.randrange(int(b["x2"]) - int(b["x1"]) + 1),
        "y": int(b["y1"]) + rng.randrange(int(b["y2"]) - int(b["y1"]) + 1),
    }


def chain_names(chain: Sequence[Mapping]) -> str:
    return " › ".join(str(x.get("name")) for x in chain)


# ---------------------------------------------------------------- 旅行

def realm_reduce(doc: Any) -> float:
    """Original travel reduction: max raw Mijing/Xiangu/flower authority, 0–70%."""
    from . import extra_cultivation
    levels = extra_cultivation.levels_of(doc)
    realm = max(levels["mijing"], levels["xiangu"],
                extra_cultivation.authority_level(doc, "huafen") + 1)
    return min(plane_travel_rules.REALM_REDUCTION_MAX,
               max(0, realm) / plane_travel_rules.REALM_REDUCTION_MAX_LEVEL
               * plane_travel_rules.REALM_REDUCTION_MAX)


def kunpeng_reduction(doc: Any) -> float:
    """原版鲲鹏宝术按额外修炼轨与功法熟练度减少旅行分钟。"""
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    legacy = legacy if isinstance(legacy, Mapping) else {}
    learned = ext.get("gongfa") or legacy.get("学习的功法") or []
    if not isinstance(learned, (list, tuple, set)) or "鲲鹏宝术" not in learned:
        return 0.0

    from . import extra_cultivation, trib
    tracks = extra_cultivation.levels_of(doc)
    reduction = 3
    if tracks["mijing"] >= 15 or tracks["xiangu"] >= 13 or tracks["huafen"] >= 14:
        reduction += 1
    if tracks["mijing"] >= 18 or tracks["xiangu"] >= 16 or tracks["huafen"] >= 17:
        reduction += 1
    prof = ext.get("prof") if isinstance(ext, Mapping) else None
    if not isinstance(prof, Mapping):
        prof = legacy.get("功法熟练度")
    try:
        numeric = trib.stage_of(float((prof or {}).get("鲲鹏宝术", 0) or 0))[3]
    except (TypeError, ValueError, OverflowError):
        numeric = 1.0
    return round(reduction * numeric, 2)


def _meets(doc: Any, gate: int) -> bool:
    """双轨任一轨达标即通过（W0-2：位面门槛走 authority 换算）。"""
    from .authority import meets
    return meets(doc, gate)


# ---------------------------------------------------------------- W7-5b 维度壁垒 / 刻画 / 毁灭

def dim_tier(doc: Any) -> int:
    """双轨权柄 → 原版 0-25 破界档（63 境折 25 档，区别于 authority_21 的 0-21 映射）。"""
    from .authority import authority_of
    return min(25, authority_of(doc) * 25 // 63)


def breaking_power(doc: Any) -> int:
    return BREAKING_POWER.get(dim_tier(doc), 0)


def is_high_dim(name: str) -> bool:
    return name in HIGH_DIMENSIONS


def emperor_free_travel(doc: Any, src: str, target: str) -> bool:
    """仙帝权柄 (21+) 可自由通行原版帝境免检位面集合。"""
    from .extra_cultivation import realm_authority_level
    return (src != target
            and realm_authority_level(doc) >= plane_travel_rules.EMPEROR_FREE_TRAVEL_GATE
            and src in plane_travel_rules.EMPEROR_FREE_LOCATIONS
            and target in plane_travel_rules.EMPEROR_FREE_LOCATIONS)


def _target_realm_gate(doc: Any, target: str) -> bool:
    """Route-specific admission gates ported from the pinned getLocationThreshold."""
    from .extra_cultivation import levels_of, realm_authority_level
    tracks = levels_of(doc)
    mijing, xiangu, huafen = (tracks["mijing"], tracks["xiangu"], tracks["huafen"])
    authority = realm_authority_level(doc)
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    legacy = legacy if isinstance(legacy, Mapping) else {}
    flower_active = isinstance(ext.get("flower"), Mapping)
    if target == TIME_RIVER_PLANE:
        return mijing >= 20 or xiangu >= 20 or huafen >= 21
    if target == "仙界":
        return int(getattr(doc, "realm_index", 0) or 0) >= 41 or bool(
            _legacy_int(legacy.get("lunhui", legacy.get("轮回次数", 0))))
    if target == "遮天位面":
        return authority >= 12 or int(legacy.get("五色祭坛激活", 0) or 0) == 1
    if target == "仙域":
        return (mijing >= 18 or xiangu >= 16 or huafen >= 18
                or (flower_active and huafen >= 17))
    if target == FOREIGN_REALM:
        return authority >= plane_travel_rules.FOREIGN_AUTHORITY_GATE
    if target == "太初星墟":
        return mijing >= 16 or xiangu >= 16 or huafen >= 15
    if target == "小阴间":
        return authority >= 20 or (flower_active and huafen >= 2)
    if target == "大阴间":
        return authority >= 20 or (flower_active and huafen >= 11)
    if target == "阳间":
        return authority >= 20 or (flower_active and huafen >= 13)
    if target == "凡间":
        return authority >= 20 or (mijing <= 20 and xiangu <= 20 and huafen <= 21)
    if target in HIGH_DIMENSIONS:
        return breaking_power(doc) >= int(HIGH_DIMENSIONS[target]["power"])
    return True


def _legacy_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def destroyed_of(st: Mapping, plane: str) -> dict | None:
    row = (st.get("destroyed") or {}).get(plane)
    return dict(row) if isinstance(row, Mapping) else None


def destroy_plane(st: dict, plane: str, source: str, now: float) -> bool:
    if plane not in LEVELS:
        return False
    st.setdefault("destroyed", {})[plane] = {"source": str(source or "未知"), "at": float(now)}
    return True


def repair_plane(st: dict, plane: str) -> bool:
    rows = st.get("destroyed")
    if not isinstance(rows, dict) or plane not in rows:
        return False
    rows.pop(plane, None)
    return True


WORLD_REPAIR_INTERVAL = 2_000
WORLD_REPAIR_LEVEL_MAX = 10
WORLD_REPAIR_BEARING_BASE = 9_999_999
WORLD_REPAIR_BEARING_PER_AUTHORITY = 10_000
WORLD_REPAIR_RESOURCE_BASE = 100_000_000_000
NATURAL_REPAIR_SOURCES = frozenset({"dark_revolt", "foreign_imperial_pass"})


def _world_level(value: Any) -> int:
    try:
        return int(value or 10)
    except (TypeError, ValueError, OverflowError):
        return 10


def world_level_caps(level: int | None) -> dict[str, int]:
    """Fixed-original growth caps derived from pressure = 10 - 诸天位面等级."""
    world_level = _world_level(level)
    pressure = 10 - world_level
    return {"mijing": 21 - pressure, "qi": 64 - pressure,
            "body": 63 - pressure, "xiangu": 19 - pressure}


def world_level_gate_message(track: str, target_level: int, world_level: int | None) -> str | None:
    world_level = _world_level(world_level)
    cap = world_level_caps(world_level).get(str(track))
    if cap is None or int(target_level) <= cap:
        return None
    return ("诸天破碎，天地大道残缺，已经难以诞生至高强者。"
            f"当前位面等级 {world_level}，{track}最高可达第 {cap} 境；"
            "诸天复苏后方可继续突破。")


def world_repair_state(calamity_state: dict) -> dict:
    """Shared analogues of the original world-bearing and plane-level fields."""
    state = calamity_state.get("plane_world")
    if not isinstance(state, dict):
        state = {"level": 5, "bearing": WORLD_REPAIR_BEARING_BASE,
                 "last_repair_world_year": 0}
        calamity_state["plane_world"] = state
    state.setdefault("level", 5)
    state.setdefault("bearing", WORLD_REPAIR_BEARING_BASE)
    state.setdefault("last_repair_world_year", 0)
    return state


def world_repair_cost(exp: int, blood: int) -> tuple[int, int]:
    """Original #修复位面 consumes half the current resource plus 100 billion."""
    return (int(max(0, int(exp)) * 0.5 + WORLD_REPAIR_RESOURCE_BASE),
            int(max(0, int(blood)) * 0.5 + WORLD_REPAIR_RESOURCE_BASE))


def apply_world_repair(world: dict, authority_level: int) -> tuple[int, int]:
    """Raise global plane-bearing and plane-level counters for仙帝 #修复位面."""
    authority = max(0, int(authority_level))
    world["bearing"] = max(0, int(world.get("bearing", WORLD_REPAIR_BEARING_BASE) or 0)) + (
        authority * WORLD_REPAIR_BEARING_PER_AUTHORITY)
    world["level"] = max(0, int(world.get("level", 5) or 0)) + 1
    return authority * WORLD_REPAIR_BEARING_PER_AUTHORITY, 1


SELFDAO_DAMAGE_PLANES = (
    "仙域", "九天十地", "遮天位面", "下界八域", "小阴间",
    "大阴间", "阳间", "仙界", "凡间", "界海",
)
PLANE_DAMAGE_PER_EVENT = 10
PLANE_DAMAGE_CAP = 100
PLANE_DAMAGE_BEARING_COST = 100_000


def damage_planes(calamity_state: dict, names: Sequence[str], source: str,
                  actor: str, now: float) -> dict[str, Any]:
    """Record original-style plane damage and deduct bearing without destroying gates."""
    records = calamity_state.get("plane_damage")
    if not isinstance(records, dict):
        records = {}
        calamity_state["plane_damage"] = records
    world = world_repair_state(calamity_state)
    bearing_before = max(0, int(world.get("bearing", WORLD_REPAIR_BEARING_BASE) or 0))
    damaged: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = str(raw_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        raw_record = records.get(name)
        record = dict(raw_record) if isinstance(raw_record, Mapping) else {}
        record["damage"] = min(PLANE_DAMAGE_CAP,
                              max(0, int(record.get("damage", 0) or 0)) + PLANE_DAMAGE_PER_EVENT)
        record["count"] = max(0, int(record.get("count", 0) or 0)) + 1
        record.update({"source": str(source), "actor": str(actor), "updated_at": float(now)})
        records[name] = record
        damaged.append(name)
    bearing_loss = min(bearing_before, PLANE_DAMAGE_BEARING_COST * len(damaged))
    world["bearing"] = bearing_before - bearing_loss
    try:
        cosmic_loss = max(0, int(calamity_state.get("cosmic_essence_loss", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        cosmic_loss = 0
    cosmic_loss += bearing_loss
    calamity_state["cosmic_essence_loss"] = cosmic_loss
    return {"planes": damaged, "bearing_before": bearing_before,
            "bearing_loss": bearing_loss, "bearing_after": int(world["bearing"]),
            "cosmic_essence_loss": cosmic_loss}


CAUSAL_DAMAGE_PLANES = (
    "凡间", "仙界", "下界八域", "太初星墟", "遮天位面",
    "九天十地", "界海", "时间长河", "仙域",
)
CAUSAL_DAMAGE_MAX_PER_PASS = 3
CAUSAL_DAMAGE_HISTORY_LIMIT = 100


def apply_causal_plane_impact(calamity_state: dict, debt_result: Mapping,
                              actor: str, now: float) -> dict[str, Any] | None:
    """Persist the original shared causal-damage quota and rotate eligible planes."""
    tier = debt_result.get("tier")
    debt = max(0, int(debt_result.get("debt", 0) or 0))
    tier_level = int(tier.get("level", 0) or 0) if isinstance(tier, Mapping) else 0
    if tier_level < 3 or debt < 600:
        return None
    target_units = max(1, (debt - 599) // 100)
    state = calamity_state.get("causal_plane_impact")
    if not isinstance(state, dict):
        state = {"cursor": 0, "processed_units": 0,
                 "pending_units": 0, "history": []}
        calamity_state["causal_plane_impact"] = state
    cursor = max(0, int(state.get("cursor", 0) or 0)) % len(CAUSAL_DAMAGE_PLANES)
    processed = max(0, int(state.get("processed_units", 0) or 0))
    pending = max(0, target_units - processed)
    if pending == 0:
        state["pending_units"] = 0
        return None

    to_process = min(CAUSAL_DAMAGE_MAX_PER_PASS, pending)
    destroyed = calamity_state.get("destroyed_planes")
    destroyed = destroyed if isinstance(destroyed, Mapping) else {}
    records = calamity_state.get("plane_damage")
    records = records if isinstance(records, Mapping) else {}
    selected: list[str] = []
    checked = 0
    while checked < len(CAUSAL_DAMAGE_PLANES) and len(selected) < to_process:
        name = CAUSAL_DAMAGE_PLANES[cursor]
        cursor = (cursor + 1) % len(CAUSAL_DAMAGE_PLANES)
        checked += 1
        if name not in LEVELS or name in destroyed:
            continue
        record = records.get(name)
        try:
            damage = max(0, int(record.get("damage", 0) or 0)) if isinstance(record, Mapping) else 0
        except (TypeError, ValueError, OverflowError):
            damage = 0
        if damage >= PLANE_DAMAGE_CAP:
            continue
        selected.append(name)

    state["cursor"] = cursor
    impact = damage_planes(calamity_state, selected, "causal_backlash", actor, now) if selected else {
        "planes": [], "bearing_before": int(world_repair_state(calamity_state).get("bearing", 0) or 0),
        "bearing_loss": 0,
        "bearing_after": int(world_repair_state(calamity_state).get("bearing", 0) or 0),
        "cosmic_essence_loss": max(0, int(calamity_state.get("cosmic_essence_loss", 0) or 0)),
    }
    processed += len(selected)
    pending = max(0, target_units - processed)
    state["processed_units"] = processed
    state["pending_units"] = pending
    history = list(state.get("history") or [])
    history.append({"at": float(now), "actor": str(actor), "debt": debt,
                    "requested_units": to_process, "processed_units": len(selected),
                    "planes": list(selected), "pending_units": pending,
                    "bearing_loss": int(impact["bearing_loss"])})
    state["history"] = history[-CAUSAL_DAMAGE_HISTORY_LIMIT:]
    return {**impact, "target_units": target_units, "processed_units": len(selected),
            "pending_units": pending, "debt": debt}


def advance_world_repair(world: dict, destroyed: dict, world_year: int) -> tuple[list[str], int, int]:
    """Apply crossed 2,000-year repair nodes and restore age-qualified plane records.

    Returns (naturally restored planes, old global level, new global level). Old records
    without an original world_year are intentionally left for manual repair.
    """
    current = max(0, int(world_year))
    due = current // WORLD_REPAIR_INTERVAL * WORLD_REPAIR_INTERVAL
    last = max(0, int(world.get("last_repair_world_year", 0) or 0))
    old_level = max(0, int(world.get("level", 5) or 0))
    if due <= last:
        return [], old_level, old_level
    steps = (due - last) // WORLD_REPAIR_INTERVAL
    new_level = old_level if old_level >= WORLD_REPAIR_LEVEL_MAX else min(
        WORLD_REPAIR_LEVEL_MAX, old_level + steps)
    world["level"] = new_level
    world["last_repair_world_year"] = due
    repaired: list[str] = []
    for name, raw in list(destroyed.items()):
        if not isinstance(raw, Mapping):
            continue
        source = str(raw.get("source") or "")
        try:
            destroyed_year = int(raw["world_year"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (source not in NATURAL_REPAIR_SOURCES or destroyed_year < 0
                or due - destroyed_year < WORLD_REPAIR_INTERVAL
                or raw.get("permanent")):
            continue
        destroyed.pop(name, None)
        repaired.append(str(name))
    return repaired, old_level, new_level


def barrier_check(doc: Any, src: str, target: str,
                  destroyed: Mapping | None = None) -> tuple[bool, str]:
    """进入目标位面前的维度判定：毁灭记录 → 高维壁垒 → 仙帝通行。

    destroyed：全服毁灭记录（存 calamity_state，由调用方读出来传进来）。
    """
    st = state_of(doc)
    rows = destroyed if isinstance(destroyed, Mapping) else (st.get("destroyed") or {})
    row = rows.get(target)
    dead = dict(row) if isinstance(row, Mapping) else None
    if dead:
        return False, (f"【{target}】已毁灭（{dead.get('source')}），界门永闭，"
                       f"唯有管理员 #修复位面 可重开。")
    if (target == TIME_RIVER_PLANE
            and not emperor_free_travel(doc, src, target)):
        from .extra_cultivation import levels_of
        tracks = levels_of(doc)
        if not (tracks["mijing"] >= 20 or tracks["xiangu"] >= 20 or tracks["huafen"] >= 21):
            return False, "时间长河是独立时序域，需秘境 20、仙古 20 或花粉 21 方可穿越时序界壁。"
    if target == FOREIGN_REALM:
        from .extra_cultivation import realm_authority_level
        authority = realm_authority_level(doc)
        if authority < plane_travel_rules.FOREIGN_AUTHORITY_GATE:
            return False, (f"【异域界壁】异域法则排斥仙王以下的真身，需等效权柄 "
                           f"{plane_travel_rules.FOREIGN_AUTHORITY_GATE}（当前 {authority}）。")
        return True, ""
    if target not in HIGH_DIMENSIONS:
        return True, ""
    if emperor_free_travel(doc, src, target):
        return True, ""
    cfg = HIGH_DIMENSIONS[target]
    power = breaking_power(doc)
    if power < cfg["power"]:
        return False, (f"【维度壁垒】{target} 藏在第 {cfg['layer']} 重界壁之后，"
                       f"需破界强度 {cfg['power']}（当前 {power}，权柄 {dim_tier(doc)}/25）。\n"
                       f"{cfg['desc']}")
    return True, ""


def mark_coordinate(doc: Any, plane: str, now: float) -> tuple[bool, str]:
    """在传送阵上刻入已知位面锚点；不记录虚构的二维坐标。"""
    plane = (plane or "").strip()
    if plane not in LEVELS:
        return False, f"没有「{plane}」这个位面。"
    if plane in {"彼岸世界", "复活地球", "试炼宇宙", "剑与魔法"}:
        return False, f"「{plane}」不受诸天传送阵承认，无法刻入阵纹。"
    if not has_coordinate(doc, plane):
        return False, f"你尚未记录「{plane}」的位面坐标，无法在阵上刻画；先 #记坐标 {plane}。"
    st = state_of(doc)
    if plane in st["marks"]:
        return False, f"传送阵上已刻画「{plane}」坐标，无需重复刻画。"
    if int(doc.stones) < MARK_COST:
        return False, f"在传送阵上刻画「{plane}」坐标需 {MARK_COST:,} 灵石（当前 {int(doc.stones):,}）。"
    doc.stones -= MARK_COST
    st["marks"][plane] = {"at": float(now)}
    return True, (f"【阵纹刻画·坐标已镌】你将已知位面「{plane}」的抽象星路锚点刻入传送阵，"
                  f"灵石 -{MARK_COST:,}。")


def _quote_foreign_route(doc: Any, src: str, target: str, st: Mapping) -> dict:
    from . import extra_cultivation, suiyun

    tracks = extra_cultivation.levels_of(doc)
    route_realm = max(
        tracks["mijing"], tracks["xiangu"],
        extra_cultivation.authority_level(doc, "huafen") + 1,
    )
    equipment = (getattr(doc, "ext", {}) or {}).get("equipment") or {}
    suiyun_set = set(equipment.get(key) for key in ("武器", "护具", "法宝")) == set(suiyun.FINAL_SET)
    source_layer = -1 if src == TIME_RIVER_PLANE else int((HIGH_DIMENSIONS.get(src) or {}).get("layer", 0))
    target_layer = -1 if target == TIME_RIVER_PLANE else int((HIGH_DIMENSIONS.get(target) or {}).get("layer", 0))
    result = plane_travel_rules.quote_foreign_travel(
        src, target,
        authority=extra_cultivation.realm_authority_level(doc),
        realm_index=int(getattr(doc, "realm_index", 0) or 0),
        physique_index=int(getattr(doc, "physique_index", 0) or 0),
        coordinate_known=target in known_of(st),
        suiyun_set=suiyun_set,
        kunpeng_minutes=kunpeng_reduction(doc),
        source_level=ORIGINAL_TRAVEL_LEVELS.get(src, LEVELS.get(src, 0)),
        source_barrier_layer=source_layer,
        target_level=ORIGINAL_TRAVEL_LEVELS.get(target, LEVELS.get(target, 0)),
        target_barrier_layer=target_layer,
        route_levels=(tracks["mijing"], tracks["xiangu"], tracks["huafen"]),
    )
    target_gate_ok = (
        target in HIGH_DIMENSIONS or target == TIME_RIVER_PLANE or
        target == FOREIGN_REALM or _meets(doc, GATES.get(target, 0))
    )
    return {
        **result,
        "gate": GATES.get(target, plane_travel_rules.FOREIGN_AUTHORITY_GATE),
        "enough_target": target_gate_ok,
        "enough_realm": bool(result.get("enough_base")
                              and result.get("enough_authority")
                              and target_gate_ok),
    }


def quote(doc: Any, target: str) -> dict:
    """返回 {distance, minutes, exp, xueqi, gate, ok, reason}。"""
    st = state_of(doc)
    src = current(st)
    gate = GATES.get(target, 10**9)
    if target not in LEVELS:
        return {"ok": False, "reason": "unknown", "gate": gate}
    if target == src:
        return {"ok": True, "reason": "", "distance": 0, "minutes": 0,
                "exp": 0, "xueqi": 0, "shouyuan": 0, "gate": gate,
                "enough_realm": True, "enough_target": True,
                "enough_base": True, "needs_coordinate": False}
    if FOREIGN_REALM in (src, target):
        return _quote_foreign_route(doc, src, target, st)
    multiplier = 1 - realm_reduce(doc)
    crossing_time_river = target == TIME_RIVER_PLANE or src == TIME_RIVER_PLANE
    kunpeng = kunpeng_reduction(doc)
    imperial_free = emperor_free_travel(doc, src, target)
    from .extra_cultivation import realm_authority_level
    equivalent_authority = realm_authority_level(doc)
    instant = ((equivalent_authority >= plane_travel_rules.INSTANT_ALL_HEAVENS_GATE
                and src in plane_travel_rules.ALL_HEAVENS
                and target in plane_travel_rules.ALL_HEAVENS)
               or (equivalent_authority >= plane_travel_rules.EMPEROR_FREE_TRAVEL_GATE
                   and src in plane_travel_rules.EMPEROR_INSTANT_LOCATIONS
                   and target in plane_travel_rules.EMPEROR_INSTANT_LOCATIONS))
    equipment = (getattr(doc, "ext", {}) or {}).get("equipment") or {}
    from . import suiyun
    suiyun_set = set(equipment.get(key) for key in ("武器", "护具", "法宝")) == set(suiyun.FINAL_SET)
    needs_coordinate = not (imperial_free or suiyun_set)
    enough_base = (int(doc.realm_index) >= 41 and int(doc.physique_index) >= 41) or imperial_free
    if crossing_time_river:
        distance = 1
        barrier_count = abs((-1 if src == TIME_RIVER_PLANE else 0)
                            - (-1 if target == TIME_RIVER_PLANE else 0))
        exp = math.floor(barrier_count * plane_travel_rules.BARRIER_EXP_PER_LAYER * multiplier + 0.5)
        xueqi = math.floor(barrier_count * plane_travel_rules.BARRIER_XUEQI_PER_LAYER * multiplier + 0.5)
        lifespan_cost = math.floor(barrier_count * plane_travel_rules.BARRIER_LIFESPAN_PER_LAYER * multiplier + 0.5)
        travel_multiplier = (0.2 if equivalent_authority >= 24 else
                             0.35 if equivalent_authority >= 23 else
                             0.55 if equivalent_authority >= 22 else 0.75)
        if equivalent_authority >= plane_travel_rules.EMPEROR_FREE_TRAVEL_GATE:
            travel_multiplier = min(travel_multiplier, 0.3)
        raw_minutes = max(1, math.floor(barrier_count * TIME_RIVER_BARRIER_MINUTES
                                        * travel_multiplier + 0.5)) - kunpeng
        enough_target = (target != TIME_RIVER_PLANE
                         or _meets(doc, TIME_RIVER_AUTHORITY_GATE) or imperial_free)
    else:
        src_level = ORIGINAL_TRAVEL_LEVELS.get(src, LEVELS.get(src, 0))
        dst_level = ORIGINAL_TRAVEL_LEVELS.get(target, LEVELS[target])
        source_layer = int((HIGH_DIMENSIONS.get(src) or {}).get("layer", 0))
        target_layer = int((HIGH_DIMENSIONS.get(target) or {}).get("layer", 0))
        barriers = abs(source_layer - target_layer)
        raw_distance = abs(float(src_level) - float(dst_level))
        distance = float(barriers) if barriers else raw_distance
        if barriers:
            exp = math.floor(barriers * plane_travel_rules.BARRIER_EXP_PER_LAYER * multiplier + 0.5)
            xueqi = math.floor(barriers * plane_travel_rules.BARRIER_XUEQI_PER_LAYER * multiplier + 0.5)
            lifespan_cost = math.floor(barriers * plane_travel_rules.BARRIER_LIFESPAN_PER_LAYER * multiplier + 0.5)
            barrier_minutes = max(1, math.floor(
                max(2, raw_distance * BASE_MIN_PER_LEVEL * multiplier) * barriers + 0.5))
            raw_minutes = max(1, barrier_minutes - kunpeng)
        else:
            exp = math.floor(raw_distance * plane_travel_rules.EXP_PER_LEVEL * multiplier + 0.5)
            xueqi = math.floor(raw_distance * plane_travel_rules.XUEQI_PER_LEVEL * multiplier + 0.5)
            lifespan_cost = math.floor(raw_distance * plane_travel_rules.LIFESPAN_PER_LEVEL * multiplier + 0.5)
            raw_minutes = max(1, max(2, raw_distance * BASE_MIN_PER_LEVEL * multiplier) - kunpeng)
        enough_target = _target_realm_gate(doc, target)
        if suiyun_set:
            lifespan_cost = 0
            raw_minutes = 0
        elif instant:
            raw_minutes = 0
    enough_realm = enough_base and enough_target
    minutes = 0 if raw_minutes <= 0 else max(1, math.floor(max(1, raw_minutes) + 0.5))
    return {
        "ok": True, "reason": "", "distance": distance, "minutes": minutes,
        "exp": exp, "xueqi": xueqi,
        "shouyuan": lifespan_cost,
        "instant": instant,
        "needs_coordinate": needs_coordinate,
        "suiyun_instant": suiyun_set,
        "gate": gate,
        # 高维位面依壁垒判定；时间长河使用原版 20 档独立门槛。
        "enough_realm": enough_realm,
        "enough_base": enough_base,
        "enough_target": enough_target,
    }


def travel_state(st: Mapping, now: float) -> dict | None:
    tr = st.get("travel")
    if not isinstance(tr, Mapping):
        return None
    left = max(0.0, float(tr.get("arrive", 0) or 0) - now)
    out = dict(tr)
    out["left"] = left
    out["done"] = left <= 0
    return out


def record_unfettered_journey(doc: Any) -> int:
    """Advance the original side quest only while task 4 is active in stage 1."""
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    if not isinstance(legacy, dict):
        return 0
    tasks = legacy.get("支线任务")
    if not isinstance(tasks, list) or not any(str(task) == "4" for task in tasks):
        return 0
    progress = legacy.get("支线任务进度")
    if not isinstance(progress, dict):
        return 0
    row = progress.get(4, progress.get("4"))
    if not isinstance(row, dict):
        return 0
    try:
        if int(row.get("阶段", 0) or 0) != 1:
            return 0
        current_progress = max(0, int(row.get("横渡位面", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        current_progress = 0
    row["横渡位面"] = min(3, current_progress + 1)
    return row["横渡位面"]

def _unfettered_source(doc: Any, create: bool = False) -> dict[str, Any] | None:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return None
    legacy = ext.get("legacy_source")
    if not isinstance(legacy, dict) and create:
        legacy = ext["legacy_source"] = {}
    return legacy if isinstance(legacy, dict) else None


def unfettered_completed(doc: Any) -> bool:
    legacy = _unfettered_source(doc)
    if legacy is None:
        return False
    records = legacy.get("支线任务完成记录")
    if isinstance(records, Mapping) and (records.get(4) or records.get("4")):
        return True
    titles = legacy.get("称号列表")
    return isinstance(titles, list) and "世外逍遥客" in titles


def activate_unfettered(doc: Any) -> tuple[bool, str]:
    legacy = _unfettered_source(doc, create=True)
    if legacy is None:
        return False, "支线任务档案缺失，无法启用无拘仙印。"
    if unfettered_completed(doc):
        return False, "你已走完天地无拘之路，无需再次启印。"
    tasks = legacy.get("支线任务")
    if not isinstance(tasks, list):
        tasks = legacy["支线任务"] = []
    if any(str(value) == "4" for value in tasks):
        return False, "无拘仙印已化作星路指引，任务正在进行中。"
    progress = legacy.get("支线任务进度")
    if not isinstance(progress, dict):
        progress = legacy["支线任务进度"] = {}
    tasks.append(4)
    progress["4"] = {"阶段": 1, "横渡位面": 0}
    return True, ("【隐藏任务触发：天地无拘】\n"
                  "仙印化作一缕清风，引出三条横贯诸天的星路。\n"
                  "完成三次跨位面穿梭，体悟鲲鹏遨游万界的无拘真意。\n"
                  "发送「#我的支线任务」查看任务详情。")


def unfettered_progress(doc: Any) -> int:
    legacy = _unfettered_source(doc)
    if legacy is None:
        return 0
    progress = legacy.get("支线任务进度")
    if not isinstance(progress, Mapping):
        return 0
    row = progress.get(4, progress.get("4"))
    if not isinstance(row, Mapping):
        return 0
    try:
        return min(3, max(0, int(row.get("横渡位面", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def finish_unfettered(doc: Any, now: float | None = None) -> tuple[bool, str]:
    legacy = _unfettered_source(doc)
    if legacy is None:
        return False, "支线任务档案缺失。"
    if unfettered_completed(doc):
        return False, "天地无拘已完成，奖励不会重复领取。"
    tasks = legacy.get("支线任务")
    if not isinstance(tasks, list) or not any(str(value) == "4" for value in tasks):
        return False, "你尚未接取天地无拘任务。"
    if unfettered_progress(doc) < 3:
        return False, f"横渡位面尚未完成三次（{unfettered_progress(doc)}/3）。"
    records = legacy.get("支线任务完成记录")
    if not isinstance(records, dict):
        records = legacy["支线任务完成记录"] = {}
    tasks[:] = [value for value in tasks if str(value) != "4"]
    progress = legacy.get("支线任务进度")
    if isinstance(progress, dict):
        progress.pop(4, None)
        progress.pop("4", None)
    records["4"] = {"完成时间": float(now if now is not None else time.time()),
                     "选择": 0, "奖励状态": "已领取"}
    titles = legacy.get("称号列表")
    if not isinstance(titles, list):
        titles = legacy["称号列表"] = []
    if "世外逍遥客" not in titles:
        titles.append("世外逍遥客")
    ext = doc.ext
    ext_titles = ext.get("titles")
    if not isinstance(ext_titles, list):
        ext_titles = ext["titles"] = []
    if "世外逍遥客" not in ext_titles:
        ext_titles.append("世外逍遥客")
    gongfa = ext.get("gongfa")
    if not isinstance(gongfa, list):
        gongfa = ext["gongfa"] = []
    if "逍遥游" not in gongfa:
        gongfa.append("逍遥游")
    legacy_gongfa = legacy.get("学习的功法")
    if not isinstance(legacy_gongfa, list):
        legacy_gongfa = legacy["学习的功法"] = []
    if "逍遥游" not in legacy_gongfa:
        legacy_gongfa.append("逍遥游")
    return True, ("【天地无拘·任务完成】三界清风汇入仙印，鲲鹏道纹在你识海中徐徐展开。\n"
                  "无拘仙印随风消散，你走出了自己的逍遥路。\n"
                  "获得永久称号【世外逍遥客】与功法《逍遥游》。")

def begin_travel(doc: Any, target: str, data: Mapping, now: float,
                 destroyed: Mapping | None = None) -> tuple[bool, str]:
    st = state_of(doc)
    src = current(st)
    if target not in LEVELS:
        return False, f"没有「{target}」这个位面。可选：{'、'.join(PLANES)}"
    if target == src:
        return False, f"你已在【{src}】。"
    ok_barrier, why = barrier_check(doc, src, target, destroyed)
    if not ok_barrier:
        return False, why
    if getattr(doc, "state", "空闲") != "空闲":
        return False, f"道友正在「{doc.state}」中，无法分神穿梭。"
    q = quote(doc, target)
    portal_uses = st.get("portal_uses") if isinstance(st.get("portal_uses"), Mapping) else {}
    token_available = (int(portal_uses.get("high", 0) or 0) > 0
                       or int(portal_uses.get("low", 0) or 0) > 0)
    special_destination = target in {
        "仙域", FOREIGN_REALM, TIME_RIVER_PLANE, "上苍之上", "永恒未知之地",
        "厄土高原", *HIGH_DIMENSIONS.keys(), "彼岸世界", "复活地球", "试炼宇宙", "剑与魔法",
    }
    if (token_available and not special_destination and not q.get("instant")
            and not q.get("suiyun_instant") and not emperor_free_travel(doc, src, target)):
        from . import plane_relay
        return plane_relay._begin_token_travel(
            doc, st, target, now, random.Random(f"{getattr(doc, 'uid', '')}:portal:{now}"))
    if not q.get("enough_base", True):
        return False, ("【肉身横渡·承载不足】普通穿梭要求练气和炼体都达到地仙阶段。"
                       f"当前练气第 {doc.realm_index + 1} 境／炼体第 {doc.physique_index + 1} 境。")
    if not q.get("enough_target", q["enough_realm"]):
        return False, (f"穿越【{target}】需境界达到第 {q['gate']} 境"
                       f"（当前练气 {doc.realm_index}／炼体 {doc.physique_index}），界壁压力过强。")
    if q.get("needs_coordinate", True) and target not in known_of(st):
        return False, (f"你不知「{target}」的星空坐标。\n"
                       f"可 `#记坐标 {target}`、`#求购位面线索 {target}` 或每日 `#探索位面线索` 获取。")
    if int(doc.exp) < q["exp"]:
        return False, f"横渡【{target}】需修为 {q['exp']:,}（当前 {int(doc.exp):,}）。"
    xueqi = float(doc.ext.get("xueqi", 0) or 0)
    if xueqi < q["xueqi"]:
        return False, f"横渡【{target}】需血气 {q['xueqi']:,}（当前 {int(xueqi):,}）。"
    lifespan_cost = int(q.get("shouyuan", 0) or 0)
    if lifespan_cost:
        from . import lifespan
        lifespan_now = lifespan.shouyuan_of(doc)
        if lifespan_now < lifespan_cost:
            return False, f"横渡【{target}】需寿元 {lifespan_cost:,}（当前 {lifespan_now:,}）。"

    from . import plane_relay
    import random
    quoted_minutes = float(q["minutes"] or 0)
    travel_minutes, travel_notes, travel_protected, time_multiplier = (
        plane_relay.apply_travel_time_modifiers(
            doc, st, max(0, math.ceil(quoted_minutes)), now,
            random.Random(f"{getattr(doc, 'uid', '')}:travel:{now}"), src, target)
    )

    doc.exp = int(doc.exp) - q["exp"]
    doc.ext["xueqi"] = xueqi - q["xueqi"]
    if lifespan_cost:
        lifespan.spend(doc, lifespan_cost)
    if travel_minutes == 0:
        st["current"] = target
        st["travel"] = None
        doc.state = "空闲"
        doc.state_start = 0.0
        progress = record_unfettered_journey(doc)
        quest_note = ""
        if target == FOREIGN_REALM:
            from . import story_quest
            quest_note = story_quest.record_foreign_hunt_arrival(doc, target)
        if q.get("instant"):
            arrival_style = "【仙帝权能·诸天无距】你一念横渡"
        else:
            arrival_style = "【岁云剑尊·云月横渡】你御岁云剑光横渡"
        lines = [f"{arrival_style}，【{src}】→【{target}】。",
                 f"修为 -{q['exp']:,}｜血气 -{q['xueqi']:,}｜寿元 -{lifespan_cost:,}。",
                 *travel_notes]
        if progress:
            lines.append(f"【天地无拘】横渡位面：{progress}/3。")
        if quest_note:
            lines.append(quest_note)
        return True, "\n".join(lines)
    doc.state = "穿梭中"
    doc.state_start = now
    st["travel"] = {
        "from": src, "to": target, "depart": float(now),
        "arrive": float(now) + travel_minutes * 60, "minutes": travel_minutes,
        "time_multiplier": time_multiplier, "used_token": False,
        "accident": False, "tianwai_wind": any("天外清风" in line for line in travel_notes),
        "travel_protected": travel_protected,
    }
    travel_note_text = ("\n" + "\n".join(travel_notes)) if travel_notes else ""
    return True, (f"【穿梭·{src} → {target}】\n"
                 f"你斩断周身空间涟漪，踏入星空古路。\n"
                 f"预计 {travel_minutes} 分钟后抵达，消耗修为 {q['exp']:,}、血气 {q['xueqi']:,}、寿元 {lifespan_cost:,}。"
                 f"{travel_note_text}\n抵达后发送「#抵达」落位。")


def settle(doc: Any, data: Mapping, now: float,
           destroyed: Mapping | None = None) -> tuple[Any, str | None]:
    """旅行到点落位；在途目的位面若已毁灭，则折返出发位面（已付资源不返还）。"""
    st = state_of(doc)
    tr = travel_state(st, now)
    if not tr:
        return doc, None
    if not tr["done"]:
        return doc, None
    target = str(tr.get("to") or DEFAULT_PLANE)
    dead = destroyed if isinstance(destroyed, Mapping) else {}
    if isinstance(dead.get(target), Mapping):
        source = str(tr.get("from") or DEFAULT_PLANE)
        st["travel"] = None
        st["current"] = source
        doc.state = "空闲"
        doc.state_start = 0.0
        return doc, (f"【星路折返】穿梭途中传来「{target}」位面崩灭的消息，"
                     f"你已退回出发位面「{source}」。已支付的修为与血气不返还。")
    coord = None
    chain = []
    if has_square_map(target):
        pool = sites_of(data, target) or locations_of(data, target)
        if pool:
            import random as _random
            rng = _random.Random(f"{getattr(doc, 'uid', '')}:{target}:{tr.get('arrive')}")
            loc = rng.choice(pool)
            coord = random_coord(loc, rng)
            chain = chain_at(data, target, coord["x"], coord["y"]) or [loc]
            st.setdefault("discovered", {}).setdefault(target, [])
            got = st["discovered"][target]
            if str(loc.get("id")) not in got:
                got.append(str(loc.get("id")))
    st["current"] = target
    if coord is not None:
        st["coords"][target] = coord
    st["travel"] = None
    doc.state = "空闲"
    doc.state_start = 0.0
    quest_progress = record_unfettered_journey(doc)
    if coord is None:
        message = (f"【抵达·{target}】\n"
                   f"星空古路在脚下收束，你已进入无常规方图坐标的【{target}】。")
    else:
        where = chain_names(chain) if chain else "荒芜之地"
        message = (f"【抵达·{target}】\n"
                   f"星空古路在脚下收束，你落在 {where}（{coord['x']}，{coord['y']}）。\n"
                   f"发送「#位面地图」查看地形，或「#前往 x,y」继续赶路。")
    if quest_progress:
        message += f"\n【天地无拘】横渡位面：{quest_progress}/3。"
    if tr.get("used_token") and tr.get("accident"):
        exp_loss = min(max(0, int(doc.exp)), 5_000_000)
        current_xueqi = max(0, int(float((doc.ext or {}).get("xueqi", 0) or 0)))
        xueqi_loss = min(current_xueqi, 5_000_000)
        doc.exp = max(0, int(doc.exp) - exp_loss)
        doc.ext["xueqi"] = current_xueqi - xueqi_loss
        message += f"\n【虚空乱流·星路偏移】修为 -{exp_loss:,}｜血气 -{xueqi_loss:,}。"
    if target == FOREIGN_REALM:
        from . import story_quest
        quest_note = story_quest.record_foreign_hunt_arrival(doc, target)
        if quest_note:
            message += "\n" + quest_note
    return doc, message


# ---------------------------------------------------------------- 界内移动

def move_to(doc: Any, data: Mapping, x: int, y: int) -> tuple[bool, str]:
    st = state_of(doc)
    plane = current(st)
    if getattr(doc, "state", "空闲") == "穿梭中":
        return False, "尚在穿梭途中，先「#抵达」。"
    if not has_square_map(plane):
        return False, f"【{plane}】没有二维方图坐标，不能使用「{CMD_HINT} x,y」界内移动。"
    if not (0 <= x <= 999 and 0 <= y <= 999):
        return False, "坐标需在 0-999 之间（x 向东、y 向南）。"
    chain = chain_at(data, plane, x, y)
    st["coords"][plane] = {"x": int(x), "y": int(y)}
    if not chain:
        return True, (f"你行至【{plane}】({x}, {y})，四下荒芜，灵气稀薄，"
                      f"并无特别之处。")
    leaf = chain[-1]
    sites = st.setdefault("discovered", {}).setdefault(plane, [])
    first = str(leaf.get("id")) not in sites
    if first:
        sites.append(str(leaf.get("id")))
        doc.stones = int(doc.stones) + SITE_STONES
        doc.exp = int(doc.exp) + SITE_EXP
        bonus = f"\n【初至】灵石 +{SITE_STONES:,}｜修为 +{SITE_EXP:,}"
    else:
        bonus = ""
    desc = str(leaf.get("desc") or "")
    return True, (f"你来到【{leaf.get('name')}】（{chain_names(chain)}）({x}, {y})\n"
                  f"{desc}{bonus}")


# ---------------------------------------------------------------- 记忆坐标

def remember(doc: Any, plane: str) -> tuple[bool, str]:
    st = state_of(doc)
    if plane not in LEVELS:
        return False, f"没有「{plane}」这个位面。"
    if plane in {"彼岸世界", "复活地球", "试炼宇宙", "剑与魔法"}:
        return False, f"「{plane}」是封闭裂界，没有可记忆的常规位面坐标。"
    if plane in SHENGXU_PLANES:
        return False, f"「{plane}」是圣墟专属位面，不能通过普通记坐标获得；花粉路或仙王级权柄可直接锚定。"
    if plane in known_of(st):
        return False, f"你已记住「{plane}」的坐标。"
    st["known"].append(plane)
    return True, f"【星路入识】「{plane}」的坐标已烙入识海。"


def buy_clue(doc: Any, plane: str) -> tuple[bool, str]:
    if plane not in LEVELS:
        return False, f"没有「{plane}」这个位面。可求购：{'、'.join(PLANES)}"
    if plane in {"彼岸世界", "复活地球", "试炼宇宙", "剑与魔法"}:
        return False, f"「{plane}」是封闭裂界，没有可购买的常规位面坐标。"
    if plane in SHENGXU_PLANES:
        return False, f"「{plane}」是圣墟专属位面，不能购买普通坐标；花粉路或仙王级权柄可直接锚定。"
    st = state_of(doc)
    if plane in known_of(st):
        return False, f"你已记住「{plane}」的坐标，无需求购。"
    if int(doc.stones) < CLUE_COST:
        return False, f"求购「{plane}」线索需 {CLUE_COST:,} 灵石（当前 {int(doc.stones):,}）。"
    doc.stones = int(doc.stones) - CLUE_COST
    st["known"].append(plane)
    return True, (f"【重金求购·星路入识】\n"
                  f"你从跨界行商手中换得「{plane}」的完整星图线索，神识推演后坐标已烙入识海。\n"
                  f"灵石 -{CLUE_COST:,}")


def explore_clue(doc: Any, now: float, rng: Any) -> tuple[bool, str]:
    st = state_of(doc)
    day = day_key(now)
    if str(st.get("clue_day") or "") == day:
        return False, "今日的星象已被推演过，明日再来。"
    unknown = [p for p in PLANES if p not in known_of(st)
               and p not in SHENGXU_PLANES
               and p not in {"彼岸世界", "复活地球", "试炼宇宙", "剑与魔法"}]
    if not unknown:
        return False, "诸天位面的坐标你已尽数记住，再无线索可寻。"
    st["clue_day"] = day
    if rng.random() >= CLUE_CHANCE:
        return True, "你在山川间寻得残破星纹，可惜道韵已散，未能补全坐标。"
    pick = rng.choice(unknown)
    st["known"].append(pick)
    return True, f"【石壁参悟·坐标已记】\n你拂去石壁尘埃，以神识补全残缺星纹，记住了「{pick}」的位面坐标。"


# ---------------------------------------------------------------- 文案

def _gate_label(gate: int, realm_names: Sequence[str]) -> str:
    if gate <= 0:
        return "无门槛"
    name = realm_names[gate] if 0 <= gate < len(realm_names) else f"第{gate}境"
    return f"{name}（{gate}境）"


def plane_text(doc: Any, data: Mapping, realm_names: Sequence[str], now: float,
               destroyed: Mapping | None = None) -> str:
    st = state_of(doc)
    plane = current(st)
    coord = coord_of(st, plane)
    known = known_of(st)
    current_text = (f"当前：{plane}（{coord['x']}，{coord['y']}）" if coord else
                    f"当前：{plane}（无方图坐标）" if not has_square_map(plane) else
                    f"当前：{plane}（未落位｜{CMD_HINT} x,y 定位）")
    lines = ["--- 位面 · 诸天星路 ---", current_text]
    chain = chain_at(data, plane, coord["x"], coord["y"]) if coord else []
    if chain:
        lines.append(f"所在：{chain_names(chain)}")
    lines.append(f"记忆坐标：{'、'.join(known)}（{len(known)}/{len(PLANES)}）")
    lines.append(f"破界强度：{breaking_power(doc)}（权柄 {dim_tier(doc)}/25）")
    marks = st.get("marks") or {}
    if marks:
        lines.append("已刻画传送阵锚点：" + "、".join(str(name) for name in marks))
    dead = destroyed if isinstance(destroyed, Mapping) else (st.get("destroyed") or {})
    if dead:
        lines.append("已毁灭位面：" + "、".join(f"{k}（{v.get('source')}）" for k, v in dead.items()))
    tr = travel_state(st, now)
    if tr:
        lines.append(f"行程：{tr.get('from')} → {tr.get('to')}，"
                     f"剩余 {int(tr['left'] // 60)} 分 {int(tr['left'] % 60)} 秒" if not tr["done"]
                     else f"行程：{tr.get('from')} → {tr.get('to')}，已抵达（发「#抵达」）")
    else:
        lines.append("行程：无")
    lines.append("")
    for p in PLANES:
        q = quote(doc, p)
        if p in HIGH_DIMENSIONS:
            cfg = HIGH_DIMENSIONS[p]
            if (destroyed if isinstance(destroyed, Mapping) else {}).get(p) or destroyed_of(st, p):
                mark = "✖ 已毁灭"
            elif not q.get("enough_base", True):
                mark = "✖ 需练气、炼体都达到地仙（第 42 境）"
            elif emperor_free_travel(doc, plane, p) or breaking_power(doc) >= cfg["power"]:
                mark = f"✔ 破界 {breaking_power(doc)}/{cfg['power']}｜第 {cfg['layer']} 重"
            else:
                mark = f"✖ 需破界 {cfg['power']}（现 {breaking_power(doc)}）"
            lines.append(f"· {p}（壁垒 {cfg['layer']} 重）{mark}")
            continue
        if p == plane:
            mark = "● 当前"
        elif p == FOREIGN_REALM and not q.get("enough_authority", False):
            from .extra_cultivation import realm_authority_level
            mark = (f"✖ 需等效权柄 ≥{plane_travel_rules.FOREIGN_AUTHORITY_GATE} "
                    f"（当前 {realm_authority_level(doc)}）")
        elif not q.get("enough_base", True):
            mark = "✖ 需练气、炼体都达到地仙（第 42 境）"
        elif not q.get("enough_target", q["enough_realm"]):
            mark = f"✖ 需 {_gate_label(q['gate'], realm_names)}"
        elif q.get("needs_coordinate", True) and p not in known:
            mark = "？ 抽象锚点未知（#记坐标）" if p == FOREIGN_REALM else "？ 坐标未知"
        elif p == FOREIGN_REALM:
            mark = f"✔ 无方图横渡｜{q['minutes']} 分｜修为 {q['exp']:,}｜血气 {q['xueqi']:,}｜寿元 {q['shouyuan']:,}"
        else:
            mark = f"✔ {q['minutes']} 分｜修为 {q['exp']:,}｜血气 {q['xueqi']:,}"
        lines.append(f"· {p}（Lv{LEVELS[p]:g}）{mark}")
    lines.append("")
    lines.append("记忆：#记坐标 位面｜#求购位面线索 位面｜#探索位面线索｜#穿梭 位面")
    lines.append("高维：#刻画坐标 位面 x,y 可越过「坐标未知」，但仍受维度壁垒限制")
    return "\n".join(lines)


def memory_text(doc: Any, data: Mapping, realm_names: Sequence[str], now: float) -> str:
    st = state_of(doc)
    known = known_of(st)
    lines = ["--- 坐标记忆 ---"]
    total_sites = total_found = 0
    for p in PLANES:
        sites = sites_of(data, p)
        found = [x for x in discovered_of(st, p) if x in {str(s.get("id")) for s in sites}]
        total_sites += len(sites)
        total_found += len(found)
        if not has_square_map(p):
            lines.append(f"· {p}｜{'已记抽象锚点' if p in known else '抽象锚点未知'}｜无方图坐标")
        elif p in known:
            lines.append(f"· {p}｜已记坐标｜地点 {len(found)}/{len(sites)}")
        else:
            lines.append(f"· {p}｜坐标未知｜{_gate_label(GATES.get(p, 0), realm_names)}")
    lines.append(f"总计：{len(known)}/{len(PLANES)} 位面｜地点探索 {total_found}/{total_sites}")
    day = day_key(now)
    lines.append(f"今日线索：{'已推演' if str(st.get('clue_day') or '') == day else '未推演（#探索位面线索）'}")
    lines.append(f"#记坐标 位面（星图×1 或灵石 {STAR_MAP_ALT_COST:,}）｜#求购位面线索 位面（{CLUE_COST:,} 灵石）")
    return "\n".join(lines)


def map_payload(doc: Any, data: Mapping, plane: str, now: float) -> dict:
    st = state_of(doc)
    coord = coord_of(st, plane)
    found = set(discovered_of(st, plane))
    locs = locations_of(data, plane)
    by_id = {str(l.get("id")): l for l in locs}

    def _depth(loc: Mapping) -> int:
        n, cur = 0, loc
        while cur.get("parent") in by_id and n < 8:
            cur = by_id[str(cur["parent"])]
            n += 1
        return n

    regions, sites = [], []
    for loc in locs:
        b = loc.get("bounds") or {}
        item = {
            "name": str(loc.get("name") or ""),
            "left": round(int(b["x1"]) / 1000 * 100, 2),
            "top": round(int(b["y1"]) / 1000 * 100, 2),
            "w": round((int(b["x2"]) - int(b["x1"])) / 1000 * 100, 2),
            "h": round((int(b["y2"]) - int(b["y1"])) / 1000 * 100, 2),
            "desc": str(loc.get("desc") or ""),
            "known": str(loc.get("id")) in found,
            "id": str(loc.get("id")),
            "depth": _depth(loc),
        }
        (sites if str(loc.get("type")) == "site" else regions).append(item)
    dot = None
    if coord:
        dot = {"left": round(coord["x"] / 1000 * 100, 2), "top": round(coord["y"] / 1000 * 100, 2)}
    chain = chain_at(data, plane, coord["x"], coord["y"]) if coord else []
    site_coords = [
        {"name": str(s["name"]), "known": s["known"], "xy": f"{center(l)['x']},{center(l)['y']}"}
        for l, s in zip([x for x in locs if str(x.get("type")) == "site"], sites) if s["known"]
    ]
    return {
        "title": f"位面地图 · {plane}",
        "sub": "",
        "footer": f"地点 {len(found)}/{len(sites)}",
        "plane": plane,
        "regions": regions,
        "sites": sites,
        "dot": dot,
        "where": chain_names(chain) if chain else "荒野",
        "here": str(chain[-1].get("desc") or "") if chain else "",
        "coords": site_coords[:10],
        "unknown_n": len(sites) - len(site_coords),
    }


def map_text(doc: Any, data: Mapping, plane: str) -> str:
    if not has_square_map(plane):
        detail = ("异域需记住抽象锚点并达到仙王级等效权柄，才能横渡界壁。"
                  if plane == FOREIGN_REALM else "此位面只记录抽象锚点，不提供界内二维移动。")
        return (f"--- 位面地图 · {plane} ---\n"
                f"【{plane}】没有实体二维方图，不提供虚构坐标。\n{detail}")
    st = state_of(doc)
    coord = coord_of(st, plane)
    found = set(discovered_of(st, plane))
    lines = [f"--- 位面地图 · {plane} ---"]
    if coord:
        chain = chain_at(data, plane, coord["x"], coord["y"])
        lines.append(f"坐标 ({coord['x']}, {coord['y']})｜{chain_names(chain) if chain else '荒野'}")
    for loc in locations_of(data, plane):
        c = center(loc)
        flag = "已知" if str(loc.get("id")) in found else "未探"
        kind = "地" if str(loc.get("type")) == "site" else "域"
        lines.append(f"[{kind}] {loc.get('name')}（{c['x']},{c['y']}）{flag}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 保存

def save(doc: Any, st: Mapping) -> Any:
    d = doc.model_copy(deep=True)
    d.ext["plane"] = copy.deepcopy(dict(st))
    return d
