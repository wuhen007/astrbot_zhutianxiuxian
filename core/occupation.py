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
    "金色矿石", "棕色矿石",
)
MINE_POOL_B = (
    "金色妖石", "棕色妖石", "绿色妖石", "红色妖石", "蓝色妖石",
    "金色妖丹", "棕色妖丹", "绿色妖丹", "红色妖丹", "蓝色妖丹",
)

PINJI_NAMES = ("劣", "普", "优", "精", "极", "绝", "顶")


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
    xuanze = rng.randrange(0, 5)  # 五色之一（原版按境界分段，此处取色随机）
    a_name = MINE_POOL_A[xuanze + (5 if occ_level >= 24 else 0)]
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
