"""职业体系（移植原版 apps/Occupation，纯函数无 IO）。

- 12 职业（occupation/职业列表.json）；初始无职业；#转职 消耗「X转职凭证」。
- 职业等级：occupation/experience.json 38 档（id 0-37），Add_职业经验 while 升级。
- 副职：转职时旧职业快照（职业名/经验/等级）入副职列表；#转换副职 主副互换。
- 门槛：采矿师境界 ≥17、猎户 ≥25（原版 level_id 1 起算 → 本插件 realm_index+1）。
- 采药：15 分钟档 ×48（上限 720），<15 无收益；采矿：30 分钟档 ×24。
- 制符：符师专属，必成；炼器：成功率 = 图纸 rate × (1 + 等级 rate)，≥24 级封顶 0.8。
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

MAX_OCC_LEVEL = 37  # experience 表最高档（黑袍下品，经验天文数字 = 实际封顶）

# 原版 plant_jiesuan 的草药池
HERB_NAMES = (
    "万年凝血草", "万年何首乌", "万年血精草", "万年甜甜花", "万年清心草",
    "古神藤", "万年太玄果", "炼骨花", "魔蕴花", "万年清灵草",
    "万年天魂菊", "仙蕴花", "仙缘草", "太玄仙草",
)
HERB_W_LOW = (0.2, 0.2, 0.2, 0.2, 0.2, 0, 0, 0, 0, 0, 0, 0, 0, 0)   # 境界 <36
HERB_W_HIGH = (0.17, 0.22, 0.17, 0.17, 0.17, 0.024, 0.024, 0.024, 0.024, 0.024, 0.024, 0.024, 0.012, 0.011)

MINE_POOL_A = (
    "金色石胚", "棕色石胚", "绿色石胚", "红色石胚", "蓝色石胚",
    "金色石料", "棕色石料", "绿色石料", "红色石料", "蓝色石料",
)
MINE_POOL_B = (
    "金色妖石", "棕色妖石", "绿色妖石", "红色妖石", "蓝色妖石",
    "金色妖丹", "棕色妖丹", "绿色妖丹", "红色妖丹", "蓝色妖丹",
)

PINJI_NAMES = ("劣", "普", "优", "精", "极", "绝", "顶")

# ---------------------------------------------------------------- 12 职业产线（W7-4）
# 已有产线：采药师 #采药 / 采矿师 #采矿 / 符师 #制符 / 炼器师 #炼器 / 炼丹师 #炼丹
# 这里补齐余下 7 个职业的「时长换产出」，统一由 #职业产出 分钟 驱动。
PRODUCE: dict[str, dict] = {
    "猎户": {
        "action": "狩猎", "period": 30, "cycles": 24,
        "pool": (("兽皮", 45), ("凶兽骨", 32), ("红色妖丹", 16), ("金色妖丹", 7)),
    },
    "侠客": {
        "action": "行侠", "period": 60, "cycles": 12,
        "stones": (12_000, 30_000),
        "pool": (("兽皮", 70), ("凶兽骨", 30)),
    },
    "唤魔者": {
        "action": "召魔", "period": 45, "cycles": 16,
        "pool": (("神魂结晶", 18), ("凶兽骨", 52), ("凶兽精肉", 30)),
    },
    "源师": {
        "action": "寻源", "period": 40, "cycles": 18,
        "source": (400, 1_200),
        "pool": (("下品源石", 70), ("中品源石", 30)),
    },
    "源地师": {
        "action": "布阵寻源", "period": 60, "cycles": 12,
        "source": (900, 2_400),
        "pool": (("中品源石", 62), ("上品源石", 30), ("八卦阵盘", 8)),
    },
    "源天师": {
        "action": "观星定源", "period": 90, "cycles": 8,
        "source": (2_000, 6_000),
        "pool": (("上品源石", 60), ("神源石", 32), ("八卦阵盘", 8)),
    },
    "阵法师": {
        "action": "布阵", "period": 60, "cycles": 12,
        "pool": (("符纸", 62), ("八卦阵盘", 26), ("轮回阵旗", 12)),
    },
}

# 职业等级解锁：达到等级后产线额外 +1 档权重（展示用，同时给 rate 加成）
SKILL_UNLOCKS: tuple[tuple[int, str, str], ...] = (
    (5, "初窥门径", "产线经验 +10%"),
    (12, "登堂入室", "产线经验 +25%，稀有产出权重 +1"),
    (20, "炉火纯青", "产线经验 +40%，稀有产出权重 +2"),
    (30, "出神入化", "产线经验 +60%，稀有产出权重 +3"),
)


def produce_skill(level: int) -> tuple[str, float, int]:
    """等级 → (称号, 经验加成, 稀有产出入权重)。"""
    title, exp_bonus, rare_bonus = "初学乍练", 0.0, 0
    for need, name, desc in SKILL_UNLOCKS:
        if int(level) >= need:
            title = name
            exp_bonus = {5: 0.10, 12: 0.25, 20: 0.40, 30: 0.60}[need]
            rare_bonus = {5: 0, 12: 1, 20: 2, 30: 3}[need]
    return title, exp_bonus, rare_bonus


def produce_line(job: str) -> dict | None:
    return PRODUCE.get(str(job or ""))


def produce(
    job: str, minutes: int, level: int, rng: random.Random,
) -> tuple[dict[str, int], int, int, str]:
    """结算产线：返回 (物品, 源石, 灵石, 说明)。

    cycles = 分钟 // 周期；每次产出按权重掷一件。职业等级给额外轮次与稀有偏好。
    """
    line = produce_line(job)
    if not line:
        return {}, 0, 0, ""
    title, exp_bonus, rare_bonus = produce_skill(level)
    cycles = max(0, int(minutes)) // max(1, int(line["period"]))
    if cycles <= 0:
        return {}, 0, 0, title
    rolls = cycles + int(cycles * min(0.5, 0.02 * int(level)))
    pool = list(line.get("pool") or [])
    weights = []
    for i, (_name, w) in enumerate(pool):
        # 越靠后的条目越稀有：稀有偏好把它们的权重抬高
        weights.append(max(1, int(w) + (rare_bonus if i >= max(0, len(pool) - 2) else 0)))
    items: dict[str, int] = {}
    for _ in range(rolls):
        name = rng.choices([p[0] for p in pool], weights=weights, k=1)[0]
        items[name] = items.get(name, 0) + 1
    source = 0
    if line.get("source"):
        lo, hi = line["source"]
        source = int(rng.randint(int(lo), int(hi)) * cycles * (1.0 + exp_bonus))
    stones = 0
    if line.get("stones"):
        lo, hi = line["stones"]
        stones = int(rng.randint(int(lo), int(hi)) * cycles * (1.0 + exp_bonus))
    exp = int(cycles * 12 * (1 + int(level)) * (1.0 + exp_bonus))
    return items, source, stones, title


def plant_period() -> int:
    """采药周期分钟（原版 y=15）。"""
    return 15


def plant_cycles() -> int:
    """采药最大周期数（原版 x=48 → 上限 720 分钟）。"""
    return 48


def mine_period() -> int:
    """采矿周期分钟（原版 y=30）。"""
    return 30


def mine_cycles() -> int:
    """采矿最大周期数（原版 x=24 → 上限 720 分钟）。"""
    return 24


def job_gate_ok(job: str, realm_id: int) -> bool:
    """转职境界门槛（realm_id = realm_index + 1，1 起算）。"""
    if job == "采矿师":
        return realm_id >= 17
    if job == "猎户":
        return realm_id >= 25
    return True


def add_exp(level: int, exp: int, gain: int, exp_table: Sequence[Mapping]) -> tuple[int, int]:
    """职业经验结算（对齐原版 Add_职业经验：while 升级，37 级封顶）。

    返回 (新等级, 新经验)。exp_table = occupation/experience.json（按 id 索引）。
    """
    exp = int(exp) + int(gain)
    level = int(level)
    by_id = {int(e.get("id", -1)): e for e in exp_table}
    while level <= MAX_OCC_LEVEL:
        row = by_id.get(level)
        if not row:
            break
        need = int(row.get("experience", 0) or 0)
        if need > exp:
            break
        exp -= need
        level += 1
    return level, exp


def rate_of(level: int, exp_table: Sequence[Mapping]) -> float:
    """当前职业等级的 rate（原版采矿/炼器加成基准）。"""
    by_id = {int(e.get("id", -1)): e for e in exp_table}
    row = by_id.get(int(level))
    if not row:
        return 0.0
    try:
        return float(row.get("rate", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def plant_yield(
    minutes: int, occ_level: int, realm_id: int, rng: random.Random
) -> tuple[dict[str, int], int]:
    """采药结算（对齐 plant_jiesuan）。返回 (草药数量表, 职业经验)。"""
    t = max(0, int(minutes))
    exp = t * 10
    if int(realm_id) >= 36:
        total = (t / 480) * (occ_level * 3 + 11)
        weights = HERB_W_HIGH
    else:
        k = 0.5 if int(realm_id) < 22 else 1.0
        total = (t / 480) * (occ_level * 2 + 12) * k
        weights = HERB_W_LOW
    out: dict[str, int] = {}
    for name, w in zip(HERB_NAMES, weights):
        n = math.floor(w * total)
        if n >= 1:
            out[name] = n
    return out, exp


def mine_yield_full(
    minutes: int, occ_level: int, exp_table: Sequence[Mapping], rng: random.Random
) -> tuple[dict[str, int], int]:
    """采矿完整结算（需要经验表算 rate）。返回 (材料数量表, 职业经验)。"""
    t = max(0, int(minutes))
    exp = t * 10
    ore = math.floor((1.8 + rng.random() * 0.4) * t)
    rate = rate_of(occ_level, exp_table) * 10
    out: dict[str, int] = {
        "庚金": math.floor(4 * (rate + 1) * ore),
        "玄土": math.floor(4 * (rate + 1) * ore),
    }
    xuanze = rng.randrange(0, len(MINE_POOL_B))
    a_name = MINE_POOL_A[xuanze]
    b_name = MINE_POOL_B[xuanze]
    out[a_name] = math.floor((rate / 12) * t / 30)
    out[b_name] = math.floor((rate / 12) * t / 30 / 48)
    out = {k: v for k, v in out.items() if v >= 1}
    return out, exp


def talisman_make(
    fufang: Mapping, occ_level: int, qty: int
) -> tuple[bool, str, int]:
    """制符（对齐 zhizuo_fu：符师专属、必成）。返回 (ok, 提示, 数量)。"""
    if int(occ_level) < int(fufang.get("level_limit", 0) or 0):
        return False, f"需达「符师{fufang.get('level_limit')}重境」方可制作", 0
    return True, "", max(1, int(qty))


def forge_rate(tuzhi_rate: float, occ_level: int, exp_table: Sequence[Mapping]) -> float:
    """炼器成功率（对齐 lianqi）：rate × (1 + 等级rate×10×0.025)，≥24 级 0.8 封顶，clamp[0.01,0.95]。"""
    suc = float(tuzhi_rate or 0)
    r = rate_of(occ_level, exp_table) * 10 * 0.025
    suc *= 1 + r
    if occ_level >= 24:
        suc = 0.8
    return max(0.01, min(0.95, suc))


def forge_pinji(rng: random.Random) -> int:
    """品级掷骰（原版 pinji = trunc(rand×7)，仅文本 flavor，装备无品级维度——标注偏差）。"""
    return min(6, int(rng.random() * 7))
