"""小世界经营（移植原版 apps/Garden/xiaoshijie.js 核心链，纯函数无 IO）。

- 开辟：成仙（境界 ≥42）+ 世界石×1；演化 1-5 级（材料表对齐 WORLD_LEVELS）。
- 挂机：#将分身化入小世界（100 万修为）→ #收获 按 96 现实小时封顶 × 时间流速。
- 种植：神药种子 → 收获神药；生长有效秒 = (灵气需求/1000)×4h ÷ 时间流速。
- 浇灌：普通浇灌 -30 分钟生长，6 小时冷却。
- W8-D1 深化：环境创造（8 道具→8 环境，高阶神药门槛）/ 败天神殿（源石+感悟挂机）/
  浇灌道具（草木精华露·岁月流金沙·掌天灵液·乾坤造化瓶）/ 野外仙兽驯服（封灵符三档）/
  仙宠岗位（安置/分配/召回/守卫 + 精力作息 14/7/3 + 类型产出 + 喂食）/ 图中巡游（山河社稷图）。
- 简化项（标注偏差）：月华天宫（岁云月宫权柄栖息位+24）/ 大宇宙升格深化未搬；
  工坊升级仍用本移植「灵石+世界石」经济（原版吃界源矿石/工坊构件，两种材料只在
  宠物产出内循环，见 supplies）；工作掠影文案池未搬。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

WORLD_LEVELS: dict[int, dict[str, Any]] = {
    1: {"name": "混沌初开", "aura": 1000, "fields": 1, "ratio": 1, "habitat": 1,
        "cost": {"世界石": 1}},
    2: {"name": "鸿蒙小界", "aura": 3000, "fields": 3, "ratio": 2, "habitat": 2,
        "cost": {"世界石": 3, "玄渊真水": 1, "元虚罡风": 1, "太初燧火": 1, "须弥神土": 1}},
    3: {"name": "紫府洞天", "aura": 5000, "fields": 5, "ratio": 3, "habitat": 3,
        "cost": {"世界石": 5, "造化玉碟": 1}},
    4: {"name": "太虚仙境", "aura": 10000, "fields": 8, "ratio": 4, "habitat": 5,
        "cost": {"世界石": 10, "混沌母气": 10}},
    5: {"name": "洪荒世界", "aura": 30000, "fields": 12, "ratio": 8, "habitat": 7,
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

# ---- 工坊 / 守卫 / 催熟 / 偷菜（P3-1 补充：原版 Garden 的工坊与偷菜线） ----

WORKSHOP_MAX = 5
WORKSHOPS: dict[str, dict[str, Any]] = {
    "灵田": {"desc": "成熟作物收获 +8%/级", "base_cost": 3_000_000},
    "丹房": {"desc": "炼丹加成（预留，未接线）", "base_cost": 5_000_000},
    "器阁": {"desc": "锻造加成（预留，未接线）", "base_cost": 5_000_000},
    "符台": {"desc": "制符加成（预留，未接线）", "base_cost": 4_000_000},
    "矿脉": {"desc": "灵矿产出 +10%/级", "base_cost": 4_000_000},
}
WORKSHOP_NAME = "世界石"

GUARD_MAX = 5
GUARD_BASE_COST = 4_000_000
GUARD_BLOCK_PER_LEVEL = 0.15   # 每级守卫 -15% 偷菜成功率
STEAL_BASE_RATE = 0.65
STEAL_FAIL_PENALTY = 2_000_000  # 被抓罚灵石

RIPEN_COST = 8_000_000         # 每株催熟灵石
RIPEN_HOURS = 24.0             # 每株催熟推进的现实小时


def _defaults(world: Mapping[str, Any]) -> dict[str, Any]:
    w = dict(world)
    ws = w.get("workshops")
    w["workshops"] = dict(ws) if isinstance(ws, Mapping) else {}
    w["guard"] = int(w.get("guard") or 0)
    # W8-D1 新子键（老档缺省归一，不改动既有键）
    env = w.get("env")
    w["env"] = [str(x) for x in env] if isinstance(env, (list, tuple)) else []
    temple = w.get("temple")
    w["temple"] = dict(temple) if isinstance(temple, Mapping) else {}
    tame = w.get("tame")
    w["tame"] = dict(tame) if isinstance(tame, Mapping) else None
    pets = w.get("pets")
    w["pets"] = [dict(p) for p in pets] if isinstance(pets, (list, tuple)) else []
    sup = w.get("supplies")
    w["supplies"] = dict(sup) if isinstance(sup, Mapping) else {}
    return w


def workshop_cost(kind: str, level: int) -> int:
    cfg = WORKSHOPS[kind]
    nxt = int(level) + 1
    return int(cfg["base_cost"] * nxt * nxt)


def workshop_level(world: Mapping[str, Any], kind: str) -> int:
    ws = world.get("workshops") or {}
    return int(ws.get(kind, 0) or 0) if isinstance(ws, Mapping) else 0


def upgrade_workshop(world: Mapping[str, Any], kind: str, stones: int,
                     world_stones: int) -> tuple[bool, str, dict[str, Any], int]:
    """升一级工坊。返回 (ok, 提示, world, 消耗灵石)。"""
    if kind not in WORKSHOPS:
        return False, f"工坊只有：{'、'.join(WORKSHOPS)}。", dict(world), 0
    w = _defaults(world)
    lv = workshop_level(w, kind)
    if lv >= WORKSHOP_MAX:
        return False, f"{kind} 已至 {WORKSHOP_MAX} 级。", w, 0
    cost = workshop_cost(kind, lv)
    need_ws = lv + 1
    if int(stones) < cost:
        return False, f"【小世界·灵石不足】升级{kind}需灵石 {cost}，道友当前 {int(stones)}。", w, 0
    if int(world_stones) < need_ws:
        return False, f"【小世界·材料不足】升级{kind}还需{WORKSHOP_NAME}×{need_ws}。", w, 0
    w["workshops"][kind] = lv + 1
    return True, f"{kind} 升至 {lv + 1} 级（{WORKSHOPS[kind]['desc']}），耗灵石 {cost}、{WORKSHOP_NAME}×{need_ws}。", w, cost


def workshop_text(world: Mapping[str, Any]) -> str:
    w = _defaults(world)
    lines = [f"「{w.get('name')}·工坊」"]
    for kind, cfg in WORKSHOPS.items():
        lv = workshop_level(w, kind)
        nxt = "已满级" if lv >= WORKSHOP_MAX else f"升级需灵石 {workshop_cost(kind, lv)} + {WORKSHOP_NAME}×{lv + 1}"
        lines.append(f"· {kind} {lv}/{WORKSHOP_MAX}（{cfg['desc']}）— {nxt}")
    lines.append(f"· 守卫 {int(w.get('guard') or 0)}/{GUARD_MAX}（每级偷菜成功率 -{int(GUARD_BLOCK_PER_LEVEL * 100)}%）")
    return "\n".join(lines)


def guard_upgrade(world: Mapping[str, Any], stones: int,
                  world_stones: int) -> tuple[bool, str, dict[str, Any], int]:
    w = _defaults(world)
    lv = int(w["guard"])
    if lv >= GUARD_MAX:
        return False, f"守卫已至 {GUARD_MAX} 级。", w, 0
    cost = GUARD_BASE_COST * (lv + 1) * (lv + 1)
    need_ws = lv + 1
    if int(stones) < cost:
        return False, f"募请守卫需灵石 {cost}，道友当前 {int(stones)}。", w, 0
    if int(world_stones) < need_ws:
        return False, f"募请守卫还需{WORKSHOP_NAME}×{need_ws}。", w, 0
    w["guard"] = lv + 1
    return True, f"小世界守卫扩至 {lv + 1} 级，偷菜成功率再降 {int(GUARD_BLOCK_PER_LEVEL * 100)}%。", w, cost


def ripe_crops(world: Mapping[str, Any]) -> int:
    return sum(1 for f in (world.get("fields") or []) if float(f.get("remaining", 0)) <= 0)


def ripen(world: Mapping[str, Any], stones: int) -> tuple[bool, str, dict[str, Any], int]:
    """催熟：把未成熟作物整体推进 24 小时，按株计费。"""
    w = _defaults(world)
    fields = [dict(f) for f in (w.get("fields") or [])]
    growing = [f for f in fields if float(f.get("remaining", 0)) > 0]
    if not growing:
        return False, "药田里没有在生长的作物。", w, 0
    cost = RIPEN_COST * len(growing)
    if int(stones) < cost:
        return False, f"催熟 {len(growing)} 株需灵石 {cost}，道友当前 {int(stones)}。", w, 0
    for f in growing:
        f["remaining"] = round(max(0.0, float(f["remaining"]) - RIPEN_HOURS), 2)
    w["fields"] = fields
    done = sum(1 for f in fields if float(f["remaining"]) <= 0)
    return True, f"灵雨催熟 {len(growing)} 株（每株 -{int(RIPEN_HOURS)} 小时），耗灵石 {cost}；已成熟 {done} 株。", w, cost


def steal_rate(world: Mapping[str, Any]) -> float:
    """偷菜成功率：守卫阵等级 + 守卫宠数量同轨扣减（W8-D1 起含守卫宠）。"""
    w = _defaults(world)
    n = int(w.get("guard") or 0) + sum(1 for p in w.get("pets") or [] if p.get("guard"))
    return max(0.05, STEAL_BASE_RATE - n * GUARD_BLOCK_PER_LEVEL)


def steal(target: Mapping[str, Any], thief_exp: int,
          rng: Any) -> tuple[bool, str, dict[str, Any], str, int]:
    """偷菜。返回 (成功?, 文案, 新目标世界, 偷到的东西, 罚款)。"""
    w = _defaults(target)
    fields = [dict(f) for f in (w.get("fields") or [])]
    mature = [f for f in fields if float(f.get("remaining", 0)) <= 0]
    if not mature:
        return False, f"「{w.get('name')}」药田里没有成熟的作物。", dict(target), "", 0
    if int(thief_exp) < AVATAR_COST:
        return False, "修为太浅（需 100 万修为），潜不进去。", dict(target), "", 0
    rate = steal_rate(w)
    if rng.random() >= rate:
        return False, (
            f"你潜入「{w.get('name')}」，被守卫察觉（成功率 {int(rate * 100)}%），"
            f"仓皇退回并掉落灵石 {STEAL_FAIL_PENALTY}。"
        ), dict(target), "", STEAL_FAIL_PENALTY
    pick = mature[0]
    seed = str(pick.get("seed", ""))
    item = SEEDS.get(seed, ("?", 0))[0]
    fields.remove(pick)
    w["fields"] = fields
    return True, (
        f"你趁夜摸进「{w.get('name')}」，摘走了一株{item}（守卫 {int(w.get('guard') or 0)} 级，"
        f"成功率 {int(rate * 100)}%）。"
    ), w, item, 0


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
    return True, f"小世界「{name}」开辟成功！（{WORLD_LEVELS[1]['name']}，灵气 1000，药田 1 块）", world


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
        f"小世界演化至 {lv + 1} 级「{cfg['name']}」：灵气 {cfg['aura']}，"
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
    mine_lv = workshop_level(w, "矿脉")
    for k, per_hour in HOURLY_YIELD[lv].items():
        n = int(per_hour * eff_hours)
        if n > 0 and k == "灵矿" and mine_lv:
            n = int(n * (1 + 0.10 * mine_lv))
        if n > 0:
            out[k] = out.get(k, 0) + n
    # 成熟作物收获（灵田每级 +8%，小数部分按概率进位）
    field_lv = workshop_level(w, "灵田")
    fields = [dict(f) for f in (w.get("fields") or [])]
    kept: list[dict[str, Any]] = []
    grown: dict[str, int] = {}
    for f in fields:
        if f.get("remaining", 0) <= 0:
            seed = str(f.get("seed", ""))
            harvest_name = SEEDS.get(seed, ("?", 0))[0]
            n = 1 + 0.08 * field_lv
            amount = int(n) + (1 if random.random() < n - int(n) else 0)
            grown[harvest_name] = grown.get(harvest_name, 0) + amount
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
    """栽种一株神药。失败时原样返回 world（不丢状态）。

    W8-D1：高阶种子有特殊环境门槛（只拦新栽种，不拦已种作物的收获——老档兼容红线）；
    「时间碎片」环境让新栽作物生长 ×0.75。
    """
    w = _defaults(world)
    lv = int(w.get("level", 1))
    cap = WORLD_LEVELS[lv]["fields"]
    fields = list(w.get("fields") or [])
    if len(fields) >= cap:
        return False, f"药田已满（{len(fields)}/{cap}），演化小世界可扩田。", dict(world)
    if seed not in SEEDS:
        return False, f"没有「{seed}」这种种子（#种植指南 查看）。", dict(world)
    need = SEED_ENV.get(seed)
    if need:
        have = set(w["env"])
        missing = [e for e in need if e not in have]
        if missing:
            return False, (
                f"{seed} 需要特殊环境：{'、'.join(need)}；"
                f"当前缺少「{'、'.join(missing)}」（#使用材料名创造环境）。"
            ), dict(world)
    harvest_name, aura_need = SEEDS[seed]
    aura = WORLD_LEVELS[lv]["aura"]
    if aura < aura_need:
        return False, f"{seed} 需要 {aura_need} 灵气，当前世界灵气 {aura}。", dict(world)
    grow_hours = (aura_need / 1000) * 4 / ratio_of(w)  # 有效小时 → 现实小时
    if "时间碎片" in w["env"]:
        grow_hours *= 0.75
    fields.append({"seed": seed, "remaining": round(grow_hours, 2)})
    w["fields"] = fields
    return True, f"【药园·栽种】已栽种 {seed}（{len(fields)}/{cap} 田），预计 {grow_hours:.1f} 现实小时后成熟。", w


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


def view(world: Mapping[str, Any], exp: int, shanhe_bonus: bool = False) -> str:
    w = _defaults(world)
    lv = int(w.get("level", 1))
    cfg = WORLD_LEVELS[lv]
    fields = w.get("fields") or []
    lines = [
        f"「{w.get('name')}」{cfg['name']} {lv} 级",
        f"灵气 {cfg['aura']}｜时间流速 1:{cfg['ratio']}｜药田 {len(fields)}/{cfg['fields']}"
        f"｜栖息地 {len(w['pets'])}/{habitat_capacity(w, shanhe_bonus)}",
        f"分身挂机：{'开启' if w.get('avatar') else '未开启（#将分身化入小世界，需 100 万修为，当前 ' + str(exp) + '）'}",
    ]
    if w["env"]:
        lines.append("特殊环境：" + "、".join(w["env"]))
    if w["temple"].get("built"):
        lines.append(f"「{BAITIAN_TEMPLE_NAME}」已落成（每 {int(BAITIAN_TEMPLE_INTERVAL_HOURS)}h 产出，收获时一并领取）")
    for i, f in enumerate(fields, 1):
        r = float(f.get("remaining", 0))
        if r <= 0:
            state = "已成熟"
        else:
            st = stage_of(w, f)
            state = f"{STAGE_NAMES[st]}（剩 {r:.1f} 现实小时）"
        lines.append(f"· {i}号田：{f.get('seed')}（{state}）")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# W8-D1 灵园深化（对齐原版 xiaoshijie.js 1258-1352 / baitianTemple.js /
# smallWorldPetEnergy.js / smallWorldWorkshop.js / 驯服 2542-2565·3635-3810）
# shortcut：
# - 败天神殿源石按全局 ÷1000（原版 2000 万建 / 500 万每 4h → 2 万 / 5000）
# - 岁云「月宫」权柄栖息位 +24 未搬；工作掠影文案池未搬
# - 仙宠产出走有效小时（原版 2192 行 effectiveHours 同口径）；
#   源石/修为/血气经 extras 通道由 main 落账，物品直接进 out
# ══════════════════════════════════════════════════════════════════

# ---- 环境创造（原版 itemEnvironmentMap :1274，8 道具 → 8 环境） ----

ENVIRONMENTS: dict[str, str] = {
    "混沌源石": "混沌土",
    "仙泉之眼": "仙泉",
    "龙魂精魄": "龙穴",
    "雷池核心": "雷池",
    "仙坟土": "仙坟",
    "星辰核心": "星辰矿脉",
    "生命之种": "生命古树",
    "时间沙漏": "时间碎片",
}
ENVIRONMENT_DESC: dict[str, str] = {
    "混沌土": "提升混沌属性神药生长速度",
    "仙泉": "提升水属性神药生长速度",
    "龙穴": "提升龙属性神药生长速度",
    "雷池": "提升雷属性神药生长速度",
    "仙坟": "提升阴属性神药生长速度",
    "星辰矿脉": "灵矿产出 +50%",
    "生命古树": "仙馐果产出 +50%",
    "时间碎片": "新栽作物生长时间 -25%",
}

# 高阶神药种子的环境门槛（原版 SHENYAO_SEEDS.requirements；大夏神药无要求）
SEED_ENV: dict[str, tuple[str, ...]] = {
    "麒麟神药种子": ("仙泉",),
    "玄武神药种子": ("仙泉",),
    "蟠桃仙种": ("仙泉",),
    "真龙不死药种子": ("龙穴",),
    "九妙不死药种子": ("仙坟",),
    "悟道古茶树幼苗": ("仙坟", "仙泉"),
    "九转天药幼苗": ("仙坟", "仙泉"),
}

ENV_BONUS = {"星辰矿脉": 0.5, "生命古树": 0.5}   # 产出加成（对 应 HOURLY_YIELD 键）
ENV_GROW_CUT = 0.75                              # 时间碎片：新栽生长 ×0.75


def create_environment(world: Mapping[str, Any],
                       item_name: str) -> tuple[bool, str, dict[str, Any]]:
    """使用材料创造小世界环境。返回 (ok, 提示, world)。"""
    w = _defaults(world)
    env_name = ENVIRONMENTS.get(item_name)
    if not env_name:
        return False, (
            f"无法使用「{item_name}」创造环境。可用道具：\n"
            + "\n".join(f"· {k} → {v}（{ENVIRONMENT_DESC[v]}）" for k, v in ENVIRONMENTS.items())
        ), dict(world)
    if env_name in w["env"]:
        return False, f"你的小世界已拥有「{env_name}」环境。", dict(world)
    w["env"].append(env_name)
    return True, f"成功使用「{item_name}」创造「{env_name}」环境！效果：{ENVIRONMENT_DESC[env_name]}", w


def stage_of(world: Mapping[str, Any], field: Mapping[str, Any]) -> int:
    """神药生长阶段 1-5：剩余时间 % ≤20=5（成熟），每 +20% 退一阶（原版 SHENYAO_STAGES）。"""
    seed = str(field.get("seed", ""))
    aura_need = SEEDS.get(seed, ("?", 0))[1]
    if aura_need <= 0:
        return 1
    total = (aura_need / 1000) * 4 / ratio_of(world) or 1.0
    pct = max(0.0, min(1.0, float(field.get("remaining", 0)) / total))
    if pct <= 0.2:
        return 5
    if pct <= 0.4:
        return 4
    if pct <= 0.6:
        return 3
    if pct <= 0.8:
        return 2
    return 1


STAGE_NAMES = {1: "萌芽", 2: "幼苗", 3: "成长期", 4: "开花期", 5: "成熟期"}


# ---- 败天神殿（model/baitianTemple.js 直译，源石 ÷1000） ----

BAITIAN_TEMPLE_NAME = "败天神殿"
BAITIAN_TEMPLE_SOURCE_COST = 20_000        # 原版 20_000_000 源石 ÷1000
BAITIAN_TEMPLE_WORLD_STONE_COST = 15
BAITIAN_TEMPLE_INTERVAL_HOURS = 4.0
BAITIAN_TEMPLE_SOURCE_PER_INTERVAL = 5_000  # 原版 5_000_000 ÷1000
BAITIAN_TEMPLE_INSIGHT_PER_INTERVAL = 5
BAITIAN_TEMPLE_MAX_HOURS = 96.0


def build_temple(world: Mapping[str, Any], yuanshi: int,
                 world_stones: int) -> tuple[bool, str, dict[str, Any], int, int]:
    """建立败天神殿。返回 (ok, 提示, world, 耗源石, 耗世界石)。"""
    w = _defaults(world)
    if w["temple"].get("built"):
        return False, f"你的「{BAITIAN_TEMPLE_NAME}」早已建成。", w, 0, 0
    if int(yuanshi) < BAITIAN_TEMPLE_SOURCE_COST:
        return False, (
            f"建立「{BAITIAN_TEMPLE_NAME}」需源石 {BAITIAN_TEMPLE_SOURCE_COST}"
            f"（当前 {int(yuanshi)}）。"
        ), w, 0, 0
    if int(world_stones) < BAITIAN_TEMPLE_WORLD_STONE_COST:
        return False, f"建立「{BAITIAN_TEMPLE_NAME}」还需{WORKSHOP_NAME}×{BAITIAN_TEMPLE_WORLD_STONE_COST}。", w, 0, 0
    w["temple"] = {"built": True, "last_settle": time.time()}
    return True, (
        f"【{BAITIAN_TEMPLE_NAME}·落成】败天遗法自此有归。\n"
        f"每 {int(BAITIAN_TEMPLE_INTERVAL_HOURS)} 现实小时产出：源石×{BAITIAN_TEMPLE_SOURCE_PER_INTERVAL}、"
        f"功法感悟×{BAITIAN_TEMPLE_INSIGHT_PER_INTERVAL}\n"
        f"发送 #收获小世界资源 一并领取（最多积累 {int(BAITIAN_TEMPLE_MAX_HOURS)} 小时）。"
    ), w, BAITIAN_TEMPLE_SOURCE_COST, BAITIAN_TEMPLE_WORLD_STONE_COST


def settle_temple(world: Mapping[str, Any],
                  real_hours: float) -> tuple[dict[str, int], float]:
    """神殿结算：按自上次结算起的现实小时计轮（上限 96h）。返回 (奖励, 本轮小时)。"""
    w = _defaults(world)
    tp = w["temple"]
    if not tp.get("built"):
        return {}, 0.0
    last = float(tp.get("last_settle") or 0.0) or time.time()
    hours = min(BAITIAN_TEMPLE_MAX_HOURS, max(0.0, real_hours if real_hours else (time.time() - last) / 3600))
    cycles = int(hours // BAITIAN_TEMPLE_INTERVAL_HOURS)
    if cycles <= 0:
        return {}, 0.0
    tp["last_settle"] = time.time()
    return {
        "yuanshi": cycles * BAITIAN_TEMPLE_SOURCE_PER_INTERVAL,
        "insight": cycles * BAITIAN_TEMPLE_INSIGHT_PER_INTERVAL,
    }, cycles * BAITIAN_TEMPLE_INTERVAL_HOURS


# ---- 浇灌道具（原版 :867-908 单株按比例 / :3214 批量按固定小时 / :1020 乾坤造化瓶） ----

WATER_ITEMS: dict[str, float] = {
    "草木精华露": 0.25, "岁月流金沙": 0.50, "掌天灵液": 0.75,
}
WATER_ITEM_BATCH_HOURS: dict[str, float] = {
    "草木精华露": 3.0, "岁月流金沙": 6.0, "掌天灵液": 12.0,   # 原版 10800/21600/43200 秒
}
FORCE_RIPEN_ITEM = "乾坤造化瓶"
FORCE_RIPEN_PCT = 0.25


def _apply_reduce(fields: list[dict[str, Any]], reduce_fn) -> int:
    mature = 0
    for f in fields:
        if float(f.get("remaining", 0)) > 0:
            f["remaining"] = round(max(0.0, reduce_fn(float(f["remaining"]))), 2)
        if float(f.get("remaining", 0)) <= 0:
            mature += 1
    return mature


def water_item(world: Mapping[str, Any], index: int,
               item: str) -> tuple[bool, str, dict[str, Any]]:
    """使用浇灌道具催熟单株（第 index 号田，1 起）。按剩余时间比例减少。"""
    w = _defaults(world)
    pct = WATER_ITEMS.get(item)
    if not pct:
        return False, f"没有「{item}」这种浇灌道具（草木精华露/岁月流金沙/掌天灵液）。", dict(world)
    fields = [dict(f) for f in (w.get("fields") or [])]
    if not fields:
        return False, "药田空空如也，先 #小世界栽种。", dict(world)
    if not (1 <= index <= len(fields)):
        return False, f"药田只有 {len(fields)} 株（1-{len(fields)} 号），没有 {index} 号作物。", dict(world)
    f = fields[index - 1]
    if float(f.get("remaining", 0)) <= 0:
        return False, f"{index} 号作物已经成熟，直接收获即可。", dict(world)
    before = float(f["remaining"])
    f["remaining"] = round(max(0.0, before * (1 - pct)), 2)
    w["fields"] = fields
    return True, (
        f"以「{item}」浇灌 {index} 号 {f.get('seed')}：剩余生长时间 "
        f"{before:.1f} → {f['remaining']:.1f} 现实小时（-{int(pct * 100)}%）。"
    ), w


def batch_water_item(world: Mapping[str, Any],
                     item: str) -> tuple[bool, str, dict[str, Any]]:
    """一键浇灌道具：全部生长中作物 -固定小时（原版 3/6/12h），无冷却（原版如此）。"""
    w = _defaults(world)
    hours = WATER_ITEM_BATCH_HOURS.get(item)
    if not hours:
        return False, f"没有「{item}」这种浇灌道具。", dict(world)
    fields = [dict(f) for f in (w.get("fields") or [])]
    growing = [f for f in fields if float(f.get("remaining", 0)) > 0]
    if not growing:
        return False, "药田里没有在生长的作物。", dict(world)
    mature = _apply_reduce(fields, lambda r: r - hours)
    w["fields"] = fields
    return True, (
        f"一键浇灌「{item}」：{len(growing)} 株各 -{int(hours)} 小时（已成熟 {mature} 株）。"
    ), w


def force_ripen_all(world: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """#浇灌小世界作物：消耗乾坤造化瓶 ×1，全部作物剩余时间 -25%。"""
    w = _defaults(world)
    fields = [dict(f) for f in (w.get("fields") or [])]
    growing = [f for f in fields if float(f.get("remaining", 0)) > 0]
    if not growing:
        return False, "药田里没有在生长的作物。", dict(world)
    mature = _apply_reduce(fields, lambda r: r * (1 - FORCE_RIPEN_PCT))
    w["fields"] = fields
    return True, (
        f"乾坤造化瓶灵光洒落，{len(growing)} 株作物剩余生长时间 -{int(FORCE_RIPEN_PCT * 100)}%"
        f"（已成熟 {mature} 株）。"
    ), w


# ---- 野外仙兽驯服（原版 generateWildBeast :682 / 驯服 :3729-3810） ----

WILD_BEAST_NAMES: tuple[str, ...] = (
    "赤瞳灵狐", "青鳞幼蛟", "金翅大鹏雏", "九尾仙猫", "玄甲龙龟",
    "紫电雷貂", "冰晶雪猿", "噬金仙蚁", "幻影灵蝶", "三足金乌雏",
    "碧水麒麟崽", "幽冥玄虎", "天音仙鹤", "噬灵古藤", "炎阳火凤雏",
)
BEAST_TYPES: tuple[str, ...] = ("战斗", "修炼", "炼丹", "炼器", "幸运", "制符")
BEAST_QUALITIES: tuple[str, ...] = ("仙胎", "仙仔", "仙兽", "仙道", "仙灵")
BEAST_QUALITY_WEIGHTS: tuple[int, ...] = (35, 30, 20, 10, 5)
TAME_EVENT_CHANCE = 0.08        # 每 24 现实小时约 8%
TAME_EVENT_PERIOD_HOURS = 24.0
TAME_VALID_MINUTES = 30
TALISMANS: tuple[tuple[str, float], ...] = (   # 优先用最高档
    ("极品封灵符", 0.90), ("上品封灵符", 0.70), ("普通封灵符", 0.50),
)

PET_TRAITS: dict[str, dict[str, Any]] = {
    "勤勉": {"desc": "工作速度+30%，任劳任怨", "work": 1.3},
    "懒惰": {"desc": "工作速度-20%，能偷懒就偷懒", "work": 0.8},
    "强韧": {"desc": "精力消耗-50%，不知疲倦", "cost": 0.5},
    "贪吃": {"desc": "喂食效果+50%，胃口极好", "feed": 1.5},
    "聪慧": {"desc": "有概率产出高品质额外收获", "quality": 0.15},
    "神速": {"desc": "产出速度+25%，事半功倍", "work": 1.25},
    "灵秀": {"desc": "在灵田工作时产出+40%", "ws": {"灵田": 1.4}},
    "火灵": {"desc": "在丹房工作时产出+40%", "ws": {"丹房": 1.4}},
    "金刚": {"desc": "在矿脉工作时产出+40%", "ws": {"矿脉": 1.4}},
    "符心": {"desc": "在符台工作时产出+40%", "ws": {"符台": 1.4}},
    "匠魂": {"desc": "在器阁工作时产出+40%", "ws": {"器阁": 1.4}},
    "暴食": {"desc": "精力消耗+30%，特别能吃", "cost": 1.3},
}


def _tame_event_chance(elapsed_hours: float) -> float:
    return 1.0 - (1.0 - TAME_EVENT_CHANCE) ** (max(0.0, elapsed_hours) / TAME_EVENT_PERIOD_HOURS)


def maybe_wild_beast(world: Mapping[str, Any], real_hours: float, rng: Any,
                     now: float | None = None) -> tuple[dict[str, Any], str]:
    """收获后掷野外仙兽事件。返回 (world, 文案|空串)。"""
    w = _defaults(world)
    if w["tame"] and w["tame"].get("expires", 0) > (now if now is not None else time.time()):
        return w, ""   # 已有仙兽出没未处理，不叠加
    if rng.random() >= _tame_event_chance(real_hours):
        return w, ""
    roll = rng.random() * sum(BEAST_QUALITY_WEIGHTS)
    qidx = 0
    for i, wt in enumerate(BEAST_QUALITY_WEIGHTS):
        roll -= wt
        if roll <= 0:
            qidx = i
            break
    trait_names = list(PET_TRAITS)
    rng.shuffle(trait_names)
    traits = trait_names[: 2 if rng.random() < 0.3 else 1]
    beast = {
        "name": WILD_BEAST_NAMES[int(rng.random() * len(WILD_BEAST_NAMES))],
        "type": BEAST_TYPES[int(rng.random() * len(BEAST_TYPES))],
        "quality": BEAST_QUALITIES[qidx],
        "traits": traits,
    }
    w["tame"] = {
        "beast": beast,
        "expires": (now if now is not None else time.time()) + TAME_VALID_MINUTES * 60,
    }
    return w, (
        f"【野外仙兽出没！】\n"
        f"一只 {beast['quality']} 级「{beast['name']}」（类型：{beast['type']}）出现在了小世界中！\n"
        f"特性：{'【' + '】【'.join(beast['traits']) + '】' if traits else '无'}\n"
        f"使用 #驯服仙兽 消耗封灵符尝试驯服它！"
        f"（{TAME_VALID_MINUTES} 分钟内有效；普通/上品/极品封灵符成功率 50%/70%/90%）"
    )


def pick_talisman(inv: Mapping[str, int]) -> tuple[str, float] | None:
    """按纳戒库存选最高档封灵符。返回 (符名, 成功率) 或 None。"""
    for name, rate in TALISMANS:
        if int(inv.get(name, 0) or 0) > 0:
            return name, rate
    return None


def tame(world: Mapping[str, Any], talisman: str, rng: Any,
         now: float | None = None) -> tuple[bool, str, dict[str, Any]]:
    """驯服野外仙兽（消耗封灵符在 main 扣）。返回 (ok, 提示, world)。"""
    w = _defaults(world)
    beast_info = w["tame"]
    now = now if now is not None else time.time()
    if not beast_info or float(beast_info.get("expires", 0)) <= now:
        w["tame"] = None
        return False, "没有仙兽出没（或已离开），收获小世界时可能再遇到。", w
    rate = dict(TALISMANS).get(talisman)
    if rate is None:
        return False, "需要封灵符：普通(50%)/上品(70%)/极品(90%)。", w
    beast = dict(beast_info["beast"])
    w["tame"] = None
    if rng.random() >= rate:
        return False, f"💨 {beast['name']}挣脱了封灵符，逃入山林深处…\n{talisman}已被消耗", w
    pet = {
        "name": beast["name"], "type": beast["type"], "quality": beast["quality"],
        "traits": list(beast.get("traits") or []), "energy": 100, "max_energy": 100,
        "workshop": None, "guard": False, "cycle": 0.0,
    }
    cap = habitat_capacity(w)
    if len(w["pets"]) >= cap:
        return False, f"栖息地已满（{len(w['pets'])}/{cap}），无法安置更多仙宠。", w
    w["pets"].append(pet)
    return True, (
        f"封灵符金光暴涨，{beast['quality']} 级「{beast['name']}」俯首帖耳，入驻栖息地！\n"
        f"可用 #分配仙宠{beast['name']}到灵田/丹房/器阁/符台/矿脉 安排工作。"
    ), w


# ---- 仙宠岗位（原版栖息地 / smallWorldWorkshop.js 产出） ----

WORKSHOP_TYPES: dict[str, tuple[str, ...]] = {   # 工坊 → 兼容的宠物类型（不匹配 ×0.5）
    "灵田": ("修炼", "幸运"), "丹房": ("炼丹",), "器阁": ("炼器",),
    "符台": ("制符",), "矿脉": ("战斗",),
}
PINJI_RATE: dict[str, int] = {"仙胎": 1, "仙仔": 2, "仙兽": 3, "仙道": 4, "仙灵": 5}
PET_BASE_ENERGY_COST = 4.0      # 工作每小时精力
PET_REST_RESTORE = 8.0          # 栖息地每小时恢复
PET_CARE_CYCLE = (14.0, 7.0, 3.0)  # 劳作/休息/玩耍（原版 PET_CARE_CYCLE）

# 每有效工作小时产出（原版 WORKSHOP_OUTPUTS 直译；__ 前缀走 extras/灵石通道）
PET_WORK_OUTPUTS: dict[str, dict[str, float]] = {
    "战斗": {"__stones__": 50_000, "__yuanshi__": 1_500, "界源矿石": 24 / 14},
    "修炼": {"__exp__": 3_000_000, "__xueqi__": 3_000_000, "制符草药": 1.0, "仙宠口粮": 0.5},
    "炼丹": {"小界蕴灵丹": 0.05, "洞天造化丹": 0.05},   # SMALL_WORLD_ALCHEMY_RATE=0.05 拆两池
    "炼器": {"灵矿": 0.3, "工坊构件": 24 / 14},
    "幸运": {"稀有机缘": 0.1, "制符草药": 1.0, "仙宠口粮": 0.5},
    "制符": {"符纸": 1.0},
}
LUCKY_REWARDS: tuple[tuple[str, int], ...] = (
    ("劫光令", 5), ("秘境之匙", 20), ("仙舟", 15), ("遣龙令", 10),
    ("仙兽玉", 10), ("世界石", 25), ("混沌母气", 15),
)
TALISMAN_HERBS: tuple[str, ...] = ("定魂草", "固元花", "静心草", "聚灵藤", "灵墨汁", "轮回果")
MEAL_SUBSTITUTES: tuple[str, ...] = (
    "五果", "六斋", "七荤", "八素", "月桂凝露", "紫府灵参", "天地琼浆", "仙馐果", "混沌元液",
)
SUPPLY_KEYS = ("仙宠口粮", "界源矿石", "工坊构件", "欠餐")


def habitat_capacity(world: Mapping[str, Any], shanhe_bonus: bool = False) -> int:
    """栖息地上限 = 世界等级 + 山河社稷图被动 +2（原版 getHabitatSlotBonus）。"""
    lv = int(world.get("level", 1))
    return int(WORLD_LEVELS[lv].get("habitat", 1)) + (2 if shanhe_bonus else 0)


def _ensure_supplies(w: dict[str, Any]) -> dict[str, int]:
    sup = w["supplies"]
    for k in SUPPLY_KEYS:
        sup[k] = max(0, int(sup.get(k) or 0))
    return sup


def place_pet(world: Mapping[str, Any], name: str, pet_type: str, quality: str,
              traits: list[str] | None = None,
              shanhe_bonus: bool = False) -> tuple[bool, str, dict[str, Any]]:
    """安置仙宠入驻栖息地（纳戒仙宠/出战宠由 main 定来源，core 只管名册）。"""
    w = _defaults(world)
    name = (name or "").strip()
    if not name:
        return False, "格式：#安置仙宠 仙宠名", dict(world)
    if any(p.get("name") == name for p in w["pets"]):
        return False, f"「{name}」已在栖息地中。", dict(world)
    cap = habitat_capacity(w, shanhe_bonus)
    if len(w["pets"]) >= cap:
        return False, f"栖息地已满（{len(w['pets'])}/{cap}），演化小世界或执掌「山河社稷图」可扩位。", dict(world)
    w["pets"].append({
        "name": name, "type": pet_type, "quality": quality,
        "traits": list(traits or []), "energy": 100, "max_energy": 100,
        "workshop": None, "guard": False, "cycle": 0.0,
    })
    return True, f"「{name}」入驻栖息地（{len(w['pets'])}/{cap}），可 #分配仙宠{name}到工坊 安排工作。", w


def assign_pet(world: Mapping[str, Any], name: str,
               workshop: str) -> tuple[bool, str, dict[str, Any]]:
    """分配仙宠到工坊。类型不匹配照常安置但效率 ×0.5（原版语义）。"""
    w = _defaults(world)
    if workshop not in WORKSHOPS:
        return False, f"工坊只有：{'、'.join(WORKSHOPS)}。", dict(world)
    pet = next((p for p in w["pets"] if p.get("name") == name), None)
    if not pet:
        return False, f"栖息地里没有「{name}」（#安置仙宠 先入驻）。", dict(world)
    if pet.get("guard"):
        return False, f"「{name}」正在担任守卫，先 #撤下仙宠守卫。", dict(world)
    lv = max(1, workshop_level(w, workshop))
    same = [p for p in w["pets"] if p.get("workshop") == workshop and not p.get("guard")]
    if len(same) >= lv:
        return False, f"{workshop}只能容纳 {lv} 只仙宠（工坊等级=容纳数），先升级工坊或召回。", dict(world)
    matched = pet.get("type") in WORKSHOP_TYPES.get(workshop, ())
    pet["workshop"] = workshop
    tip = "" if matched else f"（{pet.get('type')}系与{workshop}不合，产出效率 ×0.5）"
    return True, f"「{name}」已分配至{workshop}{tip}", w


def recall_pet(world: Mapping[str, Any], name: str) -> tuple[bool, str, dict[str, Any]]:
    """召回休息：从工坊撤回栖息地（原版 #召回休息 / #处理分配 同义）。"""
    w = _defaults(world)
    pet = next((p for p in w["pets"] if p.get("name") == name), None)
    if not pet:
        return False, f"栖息地里没有「{name}」。", dict(world)
    if not pet.get("workshop"):
        return False, f"「{name}」本就在栖息地休息。", dict(world)
    ws = pet["workshop"]
    pet["workshop"] = None
    return True, f"「{name}」已从{ws}召回，在栖息地休息恢复精力。", w


def set_guard(world: Mapping[str, Any], name: str) -> tuple[bool, str, dict[str, Any]]:
    """设置仙宠守卫（每只守卫宠偷菜成功率 -15%，与守卫等级同轨）。"""
    w = _defaults(world)
    pet = next((p for p in w["pets"] if p.get("name") == name), None)
    if not pet:
        return False, f"栖息地里没有「{name}」（#安置仙宠 先入驻）。", dict(world)
    if pet.get("guard"):
        return False, f"「{name}」已经是守卫了。", dict(world)
    if pet.get("workshop"):
        return False, f"「{name}」正在{pet['workshop']}工作，先召回再守卫。", dict(world)
    pet["guard"] = True
    n = sum(1 for p in w["pets"] if p.get("guard"))
    return True, f"「{name}」担任仙宠守卫（守卫宠 {n} 只+守卫阵 {int(w['guard'])} 级，偷菜成功率再降）。", w


def unset_guard(world: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """撤下全部仙宠守卫（原版一次撤一只，此处名册通常只 1-2 只，取最早一只）。"""
    w = _defaults(world)
    pet = next((p for p in w["pets"] if p.get("guard")), None)
    if not pet:
        return False, "当前没有仙宠守卫。", dict(world)
    pet["guard"] = False
    return True, f"【药园·守卫】已撤下仙宠守卫「{pet['name']}」，它回栖息地休息。", w


def energy_period(energy: float, max_energy: float, hours: float,
                  hourly_cost: float) -> dict[str, float]:
    """原版 calculatePetEnergyPeriod 直译。"""
    max_energy = max(1.0, float(max_energy) or 100.0)
    start = max(0.0, min(max_energy, float(energy) if energy is not None else max_energy))
    hours = max(0.0, float(hours) or 0.0)
    cost = float(hourly_cost) or 0.0
    if cost < 0:                                   # 休息：负成本=恢复
        return {"start": start, "end": min(max_energy, start - cost * hours),
                "active": 0.0, "weighted": 0.0}
    if cost == 0:
        eff = 1.0 if start >= 30 else (0.6 if start >= 10 else (0.2 if start > 0 else 0.0))
        return {"start": start, "end": start,
                "active": hours if start > 0 else 0.0, "weighted": hours * eff}
    active = min(hours, start / cost) if cost > 0 else hours
    end = max(0.0, start - cost * active)
    above = lambda th: max(0.0, min(active, (start - th) / cost))   # noqa: E731
    high = above(30)
    medium = max(0.0, above(10) - high)
    low = max(0.0, active - high - medium)
    return {"start": start, "end": end, "active": active,
            "weighted": high + medium * 0.6 + low * 0.2}


def care_period(energy: float, max_energy: float, hours: float, hourly_cost: float,
                cycle_progress: float = 0.0) -> dict[str, float]:
    """原版 calculatePetCarePeriod 直译：14h 劳作/7h 休息/3h 玩耍循环，每整轮 1 餐。"""
    work_h, rest_h, play_h = PET_CARE_CYCLE
    cycle_hours = work_h + rest_h + play_h
    hours = max(0.0, float(hours) or 0.0)
    progress = (float(cycle_progress) or 0.0) % cycle_hours
    remaining = hours
    cur = max(0.0, min(max(1.0, float(max_energy) or 100.0), float(energy) if energy is not None else max_energy))
    active = weighted = rest_total = play_total = meals = 0.0
    while remaining > 1e-9:
        if progress < work_h:
            phase, phase_end = "work", work_h
        elif progress < work_h + rest_h:
            phase, phase_end = "rest", work_h + rest_h
        else:
            phase, phase_end = "play", cycle_hours
        span = min(remaining, phase_end - progress)
        if phase == "work":
            st = energy_period(cur, max_energy, span, hourly_cost)
            cur = st["end"]
            active += st["active"]
            weighted += st["weighted"]
        elif phase == "rest":
            st = energy_period(cur, max_energy, span, -PET_REST_RESTORE)
            cur = st["end"]
            rest_total += span
        else:
            play_total += span
        remaining -= span
        progress += span
        if progress >= cycle_hours - 1e-9:
            progress = 0.0
            meals += 1
    return {"end": cur, "active": active, "weighted": weighted,
            "rest": rest_total, "play": play_total, "meals": meals, "cycle": progress}


def _energy_cost_of(pet: Mapping[str, Any]) -> float:
    cost = PET_BASE_ENERGY_COST
    for t in (pet.get("traits") or []):
        cost *= float(PET_TRAITS.get(t, {}).get("cost", 1.0))
    return cost


def _work_efficiency(pet: Mapping[str, Any], workshop: str) -> float:
    """基础效率 = 类型匹配 ×0.5/1.0 × 特性 work × 特性工坊加成。"""
    eff = 1.0
    if pet.get("type") not in WORKSHOP_TYPES.get(workshop, ()):
        eff *= 0.5
    for t in (pet.get("traits") or []):
        cfg = PET_TRAITS.get(t, {})
        eff *= float(cfg.get("work", 1.0))
        eff *= float((cfg.get("ws") or {}).get(workshop, 1.0))
    return eff


def _quality_bonus(pet: Mapping[str, Any]) -> float:
    return 0.15 if "聪慧" in (pet.get("traits") or []) else 0.0


def settle_pets(world: dict[str, Any], eff_hours: float, inv: Mapping[str, int],
                rng: Any, shanhe_yield: bool = False,
                harvested: dict[str, int] | None = None) -> tuple[dict[str, Any], dict[str, int], list[str], dict[str, int]]:
    """仙宠工坊结算（收获时调用）。返回 (world, extras, 日志, 纳戒扣food)。

    extras 键：__stones__ 进 out、__yuanshi__/__exp__/__xueqi__ 由 main 落账、
    其余为物品。喂食：supplies 口粮 → 本次收获 → 纳戒替代食物 → 欠餐。
    harvested 原地扣除本次食物，meals_used 仅返回旧纳戒扣款，避免重复消费。
    """
    w = world
    sup = _ensure_supplies(w)
    extras: dict[str, int] = {}
    logs: list[str] = []
    meals_used: dict[str, int] = {}
    if not w["pets"]:
        return w, extras, logs, meals_used
    required_meals = 0
    states: list[tuple[dict[str, Any], dict[str, float] | None]] = []
    for pet in w["pets"]:
        if pet.get("guard") or not pet.get("workshop"):
            cost = -PET_REST_RESTORE      # 守卫与休息宠都恢复精力
            st = energy_period(pet.get("energy", 100), pet.get("max_energy", 100), eff_hours, cost)
            pet["energy"] = round(st["end"], 1)
            states.append((pet, None))
            continue
        st = care_period(pet.get("energy", 100), pet.get("max_energy", 100),
                         eff_hours, _energy_cost_of(pet), pet.get("cycle", 0.0))
        pet["energy"] = round(st["end"], 1)
        pet["cycle"] = round(st["cycle"], 3)
        required_meals += int(st["meals"])
        states.append((pet, st))
    # 所有仙宠共用一次食物预算；新收获直接减产物，旧库存通过 meals_used 落账。
    remaining = required_meals + int(sup.get("欠餐") or 0)
    total = remaining
    take_sup = min(remaining, int(sup.get("仙宠口粮") or 0))
    if take_sup > 0:
        sup["仙宠口粮"] -= take_sup
        remaining -= take_sup
    current_food: dict[str, int] = {}
    if harvested is not None:
        for name in ("仙馐果", "混沌元液"):
            used = min(remaining, max(0, int(harvested.get(name, 0))))
            if used > 0:
                harvested[name] -= used
                current_food[name] = used
                remaining -= used
    for name in MEAL_SUBSTITUTES:
        if remaining <= 0:
            break
        have = int(inv.get(name, 0) or 0)
        used = min(remaining, have)
        if used > 0:
            meals_used[name] = meals_used.get(name, 0) + used
            remaining -= used
    sup["欠餐"] = max(0, remaining)
    feeding_eff = (total - remaining) / total if total > 0 else 1.0
    if total > 0:
        eaten = dict(current_food)
        for name, used in meals_used.items():
            eaten[name] = eaten.get(name, 0) + used
        meal_txt = "、".join(f"{k}×{v}" for k, v in eaten.items())
        if take_sup:
            meal_txt = f"仙宠口粮×{take_sup}" + (f"、{meal_txt}" if meal_txt else "")
        meal_txt = meal_txt or "没有食物"
        miss = f"；缺少 {remaining} 份，工坊总效率降至 {int(feeding_eff * 100)}%" if remaining else ""
        logs.append(f"🍚 仙宠用餐：{meal_txt}{miss}")
    # 产出
    for pet, st in states:
        ws = pet.get("workshop")
        if not st or not ws:
            continue
        worked = st["active"]
        if worked <= 0:
            logs.append(f"🔴 {pet['name']}精力耗尽，在{ws}睡了整整一轮…")
            continue
        e_eff = (st["weighted"] / worked) if worked > 0 else 0.0
        level = max(1, min(WORKSHOP_MAX, workshop_level(w, ws)))
        level_bonus = (1.0, 1.2, 1.4, 1.7, 2.0)[level - 1]
        base_eff = _work_efficiency(pet, ws) * level_bonus * e_eff
        eff = base_eff * feeding_eff
        qrate = PINJI_RATE.get(pet.get("quality", "仙胎"), 1)
        innate = 2.0 if shanhe_yield else 1.0
        outputs = PET_WORK_OUTPUTS.get(pet.get("type", ""), {})
        if not outputs:
            continue
        parts = []
        for res, rate in outputs.items():
            n = rate * worked * qrate * eff * innate
            whole = int(n)
            if whole <= 0:
                if rng.random() < n:
                    whole = 1
                else:
                    continue
            if res == "稀有机缘":
                total_w = sum(wt for _, wt in LUCKY_REWARDS)
                roll = rng.random() * total_w
                for rname, wt in LUCKY_REWARDS:
                    roll -= wt
                    if roll <= 0:
                        res = rname
                        break
            elif res == "制符草药":
                res = TALISMAN_HERBS[int(rng.random() * len(TALISMAN_HERBS))]
            if res == "__stones__":
                extras["__stones__"] = extras.get("__stones__", 0) + whole
                parts.append(f"灵石×{whole}")
            elif res == "__yuanshi__":
                extras["__yuanshi__"] = extras.get("__yuanshi__", 0) + whole
                parts.append(f"源石×{whole}")
            elif res == "__exp__":
                extras["__exp__"] = extras.get("__exp__", 0) + whole
                parts.append(f"修为×{whole}")
            elif res == "__xueqi__":
                extras["__xueqi__"] = extras.get("__xueqi__", 0) + whole
                parts.append(f"血气×{whole}")
            elif res in SUPPLY_KEYS:
                sup[res] = int(sup.get(res) or 0) + whole
                parts.append(f"{res}×{whole}")
            else:
                extras[res] = extras.get(res, 0) + whole
                parts.append(f"{res}×{whole}")
        if parts:
            logs.append(f"{pet['name']}在{ws}产出：{'、'.join(parts)}（效率 {int(eff * 100)}%）")
        if _quality_bonus(pet) > 0 and rng.random() < _quality_bonus(pet):
            logs.append(f"✨ {pet['name']}灵光一闪，触发【聪慧】特性！")
    return w, extras, logs, meals_used


def pets_text(world: Mapping[str, Any], shanhe_bonus: bool = False) -> str:
    """栖息地名册面板。"""
    w = _defaults(world)
    cap = habitat_capacity(w, shanhe_bonus)
    sup = _ensure_supplies(w)
    lines = [f"「{w.get('name')}·栖息地」{len(w['pets'])}/{cap}",
             f"工坊物资：仙宠口粮×{sup['仙宠口粮']}、界源矿石×{sup['界源矿石']}、"
             f"工坊构件×{sup['工坊构件']}" + (f"、欠餐×{sup['欠餐']}" if sup['欠餐'] else "")]
    if not w["pets"]:
        lines.append("（还没有仙宠入驻：收获时可能遇到野外仙兽，用 #驯服仙兽 招募；"
                     "或 #安置仙宠 仙宠名）")
    for p in w["pets"]:
        energy = int(p.get("energy", 0))
        bar = "█" * round(8 * energy / max(1, int(p.get("max_energy", 100)))) + "░" * round(
            8 * (1 - energy / max(1, int(p.get("max_energy", 100)))))
        role = "🛡守卫" if p.get("guard") else (f"⚒{p['workshop']}" if p.get("workshop") else "🏠休息")
        traits = "【" + "】【".join(p.get("traits") or []) + "】" if p.get("traits") else ""
        lines.append(
            f"· {p['name']}（{p.get('quality')}·{p.get('type')}系）{role} "
            f"[{bar}] {energy}/{p.get('max_energy', 100)} {traits}")
    return "\n".join(lines)


def harvest_full(world: Mapping[str, Any], now: float | None = None,
                 inv: Mapping[str, int] | None = None,
                 rng: Any = None, shanhe: bool = False) -> tuple[
        bool, str, dict[str, Any], dict[str, int], dict[str, Any]]:
    """W8-D1 深化收获：挂机资源 + 成熟作物 + 败天神殿 + 仙宠工坊 + 野外仙兽事件。

    返回 (ok, 提示, world, out, extras)。
    extras: yuanshi/insight/exp/xueqi 落账键 + pet_logs 日志 + tame_msg 事件文案。
    """
    rng = rng if rng is not None else random
    inv = inv if inv is not None else {}
    w = _defaults(world)
    if not w.get("avatar"):
        return False, "分身尚未化入小世界（#将分身化入小世界，需 100 万修为）。", w, {}, {}
    now = now if now is not None else time.time()
    real_hours = min(ACCUM_HOURS_CAP, max(0.0, (now - float(w.get("last_harvest", now))) / 3600))
    ratio = WORLD_LEVELS[int(w.get("level", 1))]["ratio"]
    eff_hours = real_hours * ratio
    w["last_harvest"] = now
    if eff_hours < 0.02:
        return False, "距离上次收获时间太短，暂无资源可收获。", w, {}, {}
    lv = int(w.get("level", 1))
    out: dict[str, int] = {}
    extras: dict[str, Any] = {}
    mine_lv = workshop_level(w, "矿脉")
    env = set(w["env"])
    for k, per_hour in HOURLY_YIELD[lv].items():
        n = int(per_hour * eff_hours)
        if n > 0 and k == "灵矿":
            if mine_lv:
                n = int(n * (1 + 0.10 * mine_lv))
            if "星辰矿脉" in env:
                n = int(n * (1 + ENV_BONUS["星辰矿脉"]))
        if n > 0 and k == "仙馐果" and "生命古树" in env:
            n = int(n * (1 + ENV_BONUS["生命古树"]))
        if n > 0:
            out[k] = out.get(k, 0) + n
    # 成熟作物收获（灵田每级 +8%，小数部分按概率进位）
    field_lv = workshop_level(w, "灵田")
    fields = [dict(f) for f in (w.get("fields") or [])]
    kept: list[dict[str, Any]] = []
    grown: dict[str, int] = {}
    for f in fields:
        if f.get("remaining", 0) <= 0:
            seed = str(f.get("seed", ""))
            harvest_name = SEEDS.get(seed, ("?", 0))[0]
            n = 1 + 0.08 * field_lv
            amount = int(n) + (1 if rng.random() < n - int(n) else 0)
            grown[harvest_name] = grown.get(harvest_name, 0) + amount
        else:
            kept.append(f)
    w["fields"] = kept
    out.update(grown)
    # 败天神殿
    temple_reward, temple_hours = settle_temple(w, real_hours)
    if temple_reward:
        extras["yuanshi"] = extras.get("yuanshi", 0) + temple_reward["yuanshi"]
        extras["insight"] = extras.get("insight", 0) + temple_reward["insight"]
        extras["temple_hours"] = temple_hours
    # 仙宠工坊
    w, pet_out, pet_logs, meals_used = settle_pets(
        w, eff_hours, inv, rng, shanhe_yield=shanhe, harvested=out)
    for k, v in pet_out.items():
        if k == "__stones__":
            out["__stones__"] = out.get("__stones__", 0) + v
        else:
            extras[k] = extras.get(k, 0) + v
    if pet_logs:
        extras["pet_logs"] = pet_logs
    if meals_used:
        extras["meals_used"] = meals_used
    # 野外仙兽事件（按现实小时掷）
    w, tame_msg = maybe_wild_beast(w, real_hours, rng, now)
    if tame_msg:
        extras["tame_msg"] = tame_msg
    if out.get("__stones__", 0) == 0 and not grown and not extras:
        return False, "资源未凝结成数，稍后再来。", w, {}, {}
    lines = ["--- 小世界收获 ---",
             f"收获（现实 {real_hours:.1f} 小时 × 流速 1:{ratio} = 有效 {eff_hours:.1f} 小时）："]
    lines += [f"· {'灵石' if k == '__stones__' else k}×{v}" for k, v in out.items()]
    if temple_reward:
        lines.append(f"· 「{BAITIAN_TEMPLE_NAME}」供奉 {temple_hours:.0f} 小时："
                     f"源石×{temple_reward['yuanshi']}、功法感悟×{temple_reward['insight']}")
    for key, label in (("yuanshi", "源石"), ("insight", "功法感悟"),
                       ("exp", "修为"), ("xueqi", "血气")):
        if extras.get(key):
            lines.append(f"· {label}×{extras[key]}")
    msg = "\n".join(lines)
    return True, msg, w, out, extras


def harvest(world: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any], dict[str, int]]:
    """兼容入口（W8-D1 前签名）：收获挂机资源 + 成熟作物。"""
    ok, msg, w, out, _extras = harvest_full(world)
    return ok, msg, w, out
