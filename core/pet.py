"""仙宠对战：宠物独立三维战斗（纯函数，无 IO）。

原版 Pokemon 模块只有"出战切换"（宠物按类型给主人加成），无宠物 PVP——本模块为自创玩法：
- 宠物战斗三维 = 图鉴 atk/def/HP × (1 + (等级-1)×0.1)，品级差保留（仙灵碾压仙胎）
- 对战为友情赛（无战损）；胜 +3 成长、平 +1、负 +0；每 9 点成长自动 +1 级（上限图鉴）
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .battle import spar, Unit

LEVEL_SCALE = 0.10      # 每级战斗三维 +10%
EXP_PER_LEVEL = 9       # 每级所需成长值
GAIN_WIN, GAIN_DRAW = 3, 1

# 品级链（对齐原版）：等级上限 / 进阶所需口粮 / 品级觉醒暴击（自创技能体系）
GRADE_CHAIN = ("仙胎", "仙仔", "仙兽", "仙道", "仙灵")
GRADE_CAPS = {"仙胎": 20, "仙仔": 40, "仙兽": 60, "仙道": 80, "仙灵": 100}
GRADE_CRIT = {"仙胎": 0.0, "仙仔": 0.05, "仙兽": 0.10, "仙道": 0.20, "仙灵": 0.30}
ADVANCE_FOOD = {"仙胎": ("五果", 3), "仙仔": ("六斋", 3), "仙兽": ("七荤", 3), "仙道": ("八素", 3)}
ADVANCE_STONE = 100_000  # 进阶契约灵石（品级递增见 advance_cost）

# 随机天赋（进阶时觉醒）：效果作用在属性层，不改战斗引擎
# rarity: 普通(60%) / 稀有(30%) / 史诗(10%)；mult 三维乘区、bao 加值、exp_mult 成长速度
TALENTS = (
    {"id": "balanced", "name": "均衡成长", "rarity": "普通", "mult": 1.08, "bao": 0.0, "exp_mult": 1.0},
    {"id": "savage", "name": "蛮荒之力", "rarity": "稀有", "mult": 0.0, "atk": 1.20, "bao": 0.0, "exp_mult": 1.0},
    {"id": "rock", "name": "磐石之躯", "rarity": "稀有", "mult": 0.0, "defense": 1.25, "hp": 1.25, "bao": 0.0, "exp_mult": 1.0},
    {"id": "vital", "name": "不灭血脉", "rarity": "稀有", "mult": 0.0, "hp": 1.40, "bao": 0.0, "exp_mult": 1.0},
    {"id": "claw", "name": "天生锐爪", "rarity": "史诗", "mult": 0.0, "bao": 0.12, "exp_mult": 1.0},
    {"id": "koi", "name": "锦鲤附体", "rarity": "史诗", "mult": 1.0, "bao": 0.0, "exp_mult": 1.5},
)
TALENT_BY_NAME = {t["name"]: t for t in TALENTS}


def roll_talent(rng: random.Random) -> dict:
    """加权随机：普通 60 / 稀有 30 / 史诗 10。"""
    x = rng.random() * 100
    rarity = "普通" if x < 60 else "稀有" if x < 90 else "史诗"
    pool = [t for t in TALENTS if t["rarity"] == rarity]
    return rng.choice(pool)


def talent_of(pet: Mapping) -> dict | None:
    return TALENT_BY_NAME.get(str((pet or {}).get("talent") or ""))


@dataclass
class PetBattle:
    unit: Unit
    level: int
    cap: int
    exp: int


def build(
    pet: Mapping, item_lookup: Callable[[str], Mapping | None]
) -> PetBattle | None:
    """从宠物会话 {name, level, exp} 构建战斗单位（含品级觉醒暴击）。"""
    info = item_lookup(str(pet.get("name", "")))
    if not info or info.get("class") != "仙宠":
        return None
    try:
        grade = str(info.get("品级", "仙胎"))
        cap = GRADE_CAPS.get(grade, int(info.get("等级上限", 100) or 100))
        level = min(max(int(pet.get("level", 1) or 1), 1), cap)
        scale = 1.0 + LEVEL_SCALE * (level - 1)
        atk = float(info.get("atk") or 1) * scale
        defense = float(info.get("def") or 1) * scale
        hp = float(info.get("HP") or 1) * scale
        bao = GRADE_CRIT.get(grade, 0.0)
        talent = talent_of(pet)
        if talent:
            m = talent.get("mult") or 1.0
            atk *= m * float(talent.get("atk") or 1.0)
            defense *= m * float(talent.get("defense") or 1.0)
            hp *= m * float(talent.get("hp") or 1.0)
            bao += float(talent.get("bao") or 0.0)
        unit = Unit(
            str(info.get("name", "?")),
            max(1, int(atk)), max(1, int(defense)), max(1, int(hp)), bao,
        )
        return PetBattle(unit=unit, level=level, cap=cap, exp=int(pet.get("exp", 0) or 0))
    except (TypeError, ValueError):
        return None


def advance_cost(current_grade: str) -> int:
    """进阶契约灵石：品级序号 × 10 万。"""
    try:
        idx = GRADE_CHAIN.index(current_grade)
    except ValueError:
        return 0
    return ADVANCE_STONE * (idx + 1)


def next_form(
    info: Mapping, pet_by_id: Mapping[int, Mapping]
) -> Mapping | None:
    """进阶形态：图鉴 id+1 且品级为下一档（对齐原版同系升级形态）。"""
    try:
        pid = int(info.get("id") or 0)
    except (TypeError, ValueError):
        return None
    nxt = pet_by_id.get(pid + 1)
    if not nxt or nxt.get("name") == info.get("name"):
        return None
    if nxt.get("品级") not in GRADE_CHAIN:
        return None
    cur_idx = GRADE_CHAIN.index(str(info.get("品级", "仙胎")))
    if GRADE_CHAIN.index(str(nxt.get("品级"))) != cur_idx + 1:
        return None
    return nxt


def gain_exp(pet: Mapping, amount: int, item_lookup: Callable[[str], Mapping | None]) -> tuple[dict, int]:
    """累计成长并自动升级（锦鲤附体：成长 +50%）。返回 (新宠物会话, 升级数)。"""
    info = item_lookup(str(pet.get("name", "")))
    try:
        cap = int((info or {}).get("等级上限", 100) or 100)
    except (TypeError, ValueError):
        cap = 100
    talent = talent_of(pet)
    if talent and talent.get("exp_mult"):
        amount = int(amount * float(talent["exp_mult"]))
    exp = int(pet.get("exp", 0) or 0) + max(0, amount)
    level = min(max(int(pet.get("level", 1) or 1), 1), cap)
    up = 0
    while exp >= EXP_PER_LEVEL and level < cap:
        exp -= EXP_PER_LEVEL
        level += 1
        up += 1
    if level >= cap:
        exp = 0
    out = dict(pet)
    out["exp"] = exp
    out["level"] = level
    return out, up


def duel(
    a: PetBattle, b: PetBattle, rng: random.Random
) -> tuple[int | None, list[str]]:
    """宠物对战：复用切磋引擎（无战损）。返回 (胜者索引/None, 战报)。"""
    return spar(a.unit, b.unit, rng)
