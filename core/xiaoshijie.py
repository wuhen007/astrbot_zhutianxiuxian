"""小世界经营（移植原版 apps/Garden/xiaoshijie.js 核心链，纯函数无 IO）。

- 开辟：成仙（境界 ≥42）+ 世界石×1；演化 1-5 级（材料表对齐 WORLD_LEVELS）。
- 挂机：#将分身化入小世界（100 万修为）→ #收获 按 96 现实小时封顶 × 时间流速。
- 种植：神药种子 → 收获神药；生长有效秒 = (灵气需求/1000)×4h ÷ 时间流速。
- 浇灌：普通浇灌 -30 分钟生长，6 小时冷却。
- 简化项（标注偏差）：偷菜/工坊/守卫/环境/月华天宫/大宇宙延后。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

WORLD_LEVELS: dict[int, dict[str, Any]] = {
    1: {"name": "混沌初开", "aura": 1000, "fields": 1, "ratio": 1,
        "cost": {"世界石": 1}},
    2: {"name": "鸿蒙小界", "aura": 3000, "fields": 3, "ratio": 2,
        "cost": {"世界石": 3, "玄渊真水": 1, "元虚罡风": 1, "太初燧火": 1, "须弥神土": 1}},
    3: {"name": "紫府洞天", "aura": 5000, "fields": 5, "ratio": 3,
        "cost": {"世界石": 5, "造化玉碟": 1}},
    4: {"name": "太虚仙境", "aura": 10000, "fields": 8, "ratio": 4,
        "cost": {"世界石": 10, "混沌母气": 10}},
    5: {"name": "洪荒世界", "aura": 30000, "fields": 12, "ratio": 8,
        "cost": {"世界石": 20}},
}

REALM_GATE = 42          # 开辟门槛：原版 level_id ≥ 42（成仙）
AVATAR_COST = 1_000_000  # 分身化入修为
ACCUM_HOURS_CAP = 96     # 挂机现实小时封顶

# 每小时基础产量（对齐 calculateResources）
HOURLY_YIELD: dict[int, dict[str, int]] = {
    1: {"__stones__": 100_000, "仙馐果": 50},
    2: {"__stones__": 200_000, "仙馐果": 100, "灵矿": 5},
    3: {"__stones__": 300_000, "仙馐果": 100, "灵矿": 10, "仙果": 5},
    4: {"__stones__": 500_000, "仙馐果": 200, "灵矿": 10, "仙果": 10, "混沌元液": 3},
    5: {"__stones__": 800_000, "仙馐果": 300, "灵矿": 20, "仙果": 15, "混沌元液": 5},
}

# 神药种子（对齐 SHENYAO_SEEDS，种子名 → (收获物, 灵气需求)）
SEEDS: dict[str, tuple[str, int]] = {
    "麒麟神药种子": ("麒麟神药", 3000),
    "玄武神药种子": ("玄武神药", 3000),
    "蟠桃仙种": ("蟠桃仙果", 3000),
    "真龙不死药种子": ("真龙不死药", 5000),
    "大夏神药种子": ("大夏神药", 3000),
    "九妙不死药种子": ("九妙不死药", 8000),
    "悟道古茶树幼苗": ("悟道古茶", 10000),
    "九转天药幼苗": ("九转天药", 12000),
}

WATER_CD_HOURS = 6        # 普通浇灌冷却
WATER_REDUCE_HOURS = 0.5  # 普通浇灌减少的生长时间（有效小时）


def create_world(name: str, realm_id: int, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, Any]]:
    """开辟小世界。返回 (ok, 提示, world)。"""
    if realm_id < REALM_GATE:
        return False, f"开辟小世界需要成仙（第 {REALM_GATE} 境以上），道友当前第 {realm_id} 境。", {}
    for item, amount in WORLD_LEVELS[1]["cost"].items():
        if int(inv.get(item, 0)) < amount:
            return False, f"开辟小世界需要{item}×{amount}。", {}
    world = {
        "name": name, "level": 1, "avatar": False,
        "last_harvest": time.time(), "fields": [], "water_ts": 0.0,
    }
    return True, f"小世界【{name}】开辟成功！（{WORLD_LEVELS[1]['name']}，灵气 1000，药田 1 块）", world


def upgrade_cost(level: int) -> dict[str, int]:
    """升到 level+1 级的材料。"""
    nxt = WORLD_LEVELS.get(int(level) + 1)
    return dict(nxt["cost"]) if nxt else {}


def upgrade_world(world: Mapping[str, Any], inv: Mapping[str, int]) -> tuple[bool, str, dict[str, Any]]:
    lv = int(world.get("level", 1))
    cost = upgrade_cost(lv)
    if not cost:
        return False, "小世界已至 5 级（洪荒世界），无法再演化。", {}
    for item, amount in cost.items():
        if int(inv.get(item, 0)) < amount:
            return False, f"演化需要{item}×{amount}。", {}
    d = dict(world)
    d["level"] = lv + 1
    cfg = WORLD_LEVELS[lv + 1]
    return True, (
        f"小世界演化至 {lv + 1} 级【{cfg['name']}】：灵气 {cfg['aura']}，"
        f"时间流速 1:{cfg['ratio']}，药田 {cfg['fields']} 块。"
    ), d


def bind_avatar(world: Mapping[str, Any], exp: int) -> tuple[bool, str, dict[str, Any]]:
    """分身化入：100 万修为开启挂机。"""
    w = dict(world)
    if w.get("avatar"):
        return False, "分身早已化入小世界。", {}
    if int(exp) < AVATAR_COST:
        return False, f"分身化入需要 100 万修为，道友当前 {int(exp)}。", {}
    w["avatar"] = True
    w["last_harvest"] = time.time()
    return True, "分身化入小世界，开始自动收集灵气（记得常来 #收获小世界资源）。", w


def harvest(world: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any], dict[str, int]]:
    """收获挂机资源 + 成熟作物。返回 (ok, 提示, world, 产出)。"""
    w = dict(world)
    if not w.get("avatar"):
        return False, "分身尚未化入小世界（#将分身化入小世界，需 100 万修为）。", w, {}
    now = time.time()
    real_hours = min(ACCUM_HOURS_CAP, max(0.0, (now - float(w.get("last_harvest", now))) / 3600))
    ratio = WORLD_LEVELS[int(w.get("level", 1))]["ratio"]
    eff_hours = real_hours * ratio
    w["last_harvest"] = now
    if eff_hours < 0.02:
        return False, "距离上次收获时间太短，暂无资源可收获。", w, {}
    lv = int(w.get("level", 1))
    out: dict[str, int] = {}
    for k, per_hour in HOURLY_YIELD[lv].items():
        n = int(per_hour * eff_hours)
        if n > 0:
            out[k] = out.get(k, 0) + n
    # 成熟作物收获 + 50% 概率返种
    fields = [dict(f) for f in (w.get("fields") or [])]
    kept: list[dict[str, Any]] = []
    grown: dict[str, int] = {}
    for f in fields:
        if f.get("remaining", 0) <= 0:
            seed = str(f.get("seed", ""))
            harvest_name = SEEDS.get(seed, ("?", 0))[0]
            grown[harvest_name] = grown.get(harvest_name, 0) + 1
        else:
            kept.append(f)
    w["fields"] = kept
    out.update(grown)
    if out.get("__stones__", 0) == 0 and not grown:
        return False, "资源未凝结成数，稍后再来。", w, {}
    msg = f"收获（现实 {real_hours:.1f} 小时 × 流速 1:{ratio} = 有效 {eff_hours:.1f} 小时）：\n" + "\n".join(
        f"· {k if k == '__stones__' else k}×{v}" for k, v in out.items())
    return True, msg, w, out


def plant(world: Mapping[str, Any], seed: str) -> tuple[bool, str, dict[str, Any]]:
    """栽种一株神药。失败时原样返回 world（不丢状态）。"""
    w = dict(world)
    lv = int(w.get("level", 1))
    cap = WORLD_LEVELS[lv]["fields"]
    fields = list(w.get("fields") or [])
    if len(fields) >= cap:
        return False, f"药田已满（{len(fields)}/{cap}），演化小世界可扩田。", dict(world)
    if seed not in SEEDS:
        return False, f"没有「{seed}」这种种子（#种植指南 查看）。", dict(world)
    harvest_name, aura_need = SEEDS[seed]
    aura = WORLD_LEVELS[lv]["aura"]
    if aura < aura_need:
        return False, f"{seed} 需要 {aura_need} 灵气，当前世界灵气 {aura}。", dict(world)
    grow_hours = (aura_need / 1000) * 4 / ratio_of(w)  # 有效小时 → 现实小时
    fields.append({"seed": seed, "remaining": round(grow_hours, 2)})
    w["fields"] = fields
    return True, f"已栽种 {seed}（{len(fields)}/{cap} 田），预计 {grow_hours:.1f} 现实小时后成熟。", w


def water(world: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """普通浇灌：全部作物生长 -30 分钟，6 小时冷却。"""
    w = dict(world)
    now = time.time()
    if now - float(w.get("water_ts", 0) or 0) < WATER_CD_HOURS * 3600:
        left = int(WATER_CD_HOURS * 3600 - (now - float(w.get("water_ts", 0))))
        return False, f"甘霖未聚（冷却中，剩 {left // 3600} 小时 {left % 3600 // 60} 分）。", {}
    fields = [dict(f) for f in (w.get("fields") or [])]
    if not fields:
        return False, "药田空空如也，先 #小世界栽种。", {}
    w["water_ts"] = now
    for f in fields:
        f["remaining"] = round(max(0.0, float(f.get("remaining", 0)) - WATER_REDUCE_HOURS), 2)
    w["fields"] = fields
    mature = sum(1 for f in fields if f["remaining"] <= 0)
    return True, f"普降甘霖，全部作物生长时间 -30 分钟（已成熟 {mature} 株，收获时一并结算）。", w


def ratio_of(world: Mapping[str, Any]) -> int:
    return WORLD_LEVELS[int(world.get("level", 1))]["ratio"]


def view(world: Mapping[str, Any], exp: int) -> str:
    lv = int(world.get("level", 1))
    cfg = WORLD_LEVELS[lv]
    fields = world.get("fields") or []
    lines = [
        f"【{world.get('name')}】{cfg['name']} {lv} 级",
        f"灵气 {cfg['aura']}｜时间流速 1:{cfg['ratio']}｜药田 {len(fields)}/{cfg['fields']}",
        f"分身挂机：{'开启' if world.get('avatar') else '未开启（#将分身化入小世界，需 100 万修为，当前 ' + str(exp) + '）'}",
    ]
    for i, f in enumerate(fields, 1):
        r = float(f.get("remaining", 0))
        state = "已成熟" if r <= 0 else f"生长中（剩 {r:.1f} 现实小时）"
        lines.append(f"· {i}号田：{f.get('seed')}（{state}）")
    return "\n".join(lines)
