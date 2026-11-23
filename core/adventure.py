"""A 档玩法纯函数：镇妖塔 / 仙宠寻宝 / 洗劫（对齐原版 tzzyt.js、Pokemon.js、Xijie.js）。

- 镇妖塔公式直译：Boss 血 50000×层+1万、攻 22000×层+1万、防 36000×层+1万；
  奖励分段（<100 层 100×层+100，<200 层 200×层+1000，其余 300×层+1000）封顶 40 万；
  胜 → 层+5 + 灵石 + 回血 Reward×21；败 → 灵石 −Reward×2
- 仙宠寻宝：800 万灵石门票、120 分钟必须时长、次数 = min(分钟//4, 8)，每次按概率从池抽
- 洗劫：原版为 15 分钟定时动作 + 商店锁，此处即时化（战斗 vs 档位守卫）；
  强化费 = price×Grade、魔道值 +25×Grade、探查 = 0.3×price、CD 2h（劫光令可清）
"""

from __future__ import annotations

import copy
import math
import random
import time
from typing import Any, Mapping

TOWER_MAX = 50_000
TOWER_CD = 2 * 60
PET_EXPLORE_COST = 8_000_000
PET_EXPLORE_MIN_MINUTES = 120
PET_EXPLORE_MAX_COUNT = 8
RAID_CD = 2 * 3600
RAID_MODAO_PER_GRADE = 25

TOWER_PLACES = ("葬仙古域", "龙血秘境", "天渊海眼", "虚神界外域")

AURA_POOL_HINT = ("修为丹", "血气丹", "灵石袋", "万年何首乌", "庚金", "玄土", "太玄仙草",
                  "起死回生丹", "圣品辟谷丹", "仙梦之匙")


# ---- 镇妖塔（tzzyt.js 直译） ----

def tower_boss(floor: int) -> dict:
    f = max(0, int(floor))
    return {"hp": 50_000 * f + 10_000, "atk": 22_000 * f + 10_000, "defense": 36_000 * f + 10_000}


def tower_reward(floor: int) -> int:
    f = max(0, int(floor))
    if f < 100:
        r = 100 * f + 100
    elif f < 200:
        r = 200 * f + 1000
    else:
        r = 300 * f + 1000
    return min(r, 400_000)


def tower_fight(
    doc: Mapping, stats: Mapping, rng: random.Random,
) -> tuple[bool, str, dict, dict]:
    """单次挑战。返回 (ok, msg, doc2, consume)：consume={"stones": ±, "heal": n}。"""
    ext = doc.ext if isinstance(doc.ext, Mapping) else {}
    floor = int(ext.get("tower_floor", 0) or 0)
    if floor >= TOWER_MAX:
        return False, "【镇妖塔·已达上限】已达到镇妖塔最高层数（50000 层）。", {}, {}
    boss = tower_boss(floor)
    reward = tower_reward(floor)
    from . import battle as battle_mod
    me_hp = int(stats.get("hp", 1))
    en_hp = boss["hp"]
    log: list[str] = []
    won = False
    for rnd in range(1, 31):
        dmg, crit = battle_mod.harm(int(stats.get("atk", 1)), boss["defense"], rng,
                                    float(stats.get("bao", 0)))
        en_hp -= dmg
        log.append(f"第{rnd}合：你造成 {dmg}{'（暴击）' if crit else ''}，妖物余 {max(0, en_hp)}")
        if en_hp <= 0:
            won = True
            break
        back, _ = battle_mod.harm(boss["atk"], int(stats.get("defense", 1)), rng)
        me_hp -= back
        log.append(f"        妖物反击 {back}，你余 {max(0, me_hp)}")
        if me_hp <= 0:
            break
    d2 = dict(ext)
    if won:
        d2["tower_floor"] = min(floor + 5, TOWER_MAX)
        msg = (f"镇妖塔第 {floor + 1} 层·未知妖物被斩落！\n"
               + "\n".join(log[-4:])
               + f"\n✅ 层数 +5（当前 {d2['tower_floor']}），灵石 +{reward:,}，气血回复 {reward * 21:,}")
        return True, msg, d2, {"stones": reward, "heal": reward * 21}
    penalty = reward * 2
    msg = (f"镇妖塔第 {floor + 1} 层·不敌未知妖物……\n"
           + "\n".join(log[-4:])
           + f"\n❌ 灵石 −{penalty:,}（养伤费用），层数不变。变强再来！")
    return True, msg, d2, {"stones": -penalty, "heal": 0}


# ---- 仙宠寻宝（Pokemon.js 直译） ----

def pet_explore_start(doc: Mapping, now: float, rng: random.Random) -> tuple[bool, str, dict]:
    ext = doc.ext if isinstance(doc.ext, Mapping) else {}
    pet = ext.get("pet") or {}
    if not pet.get("name"):
        return False, "请先认养一只仙宠再派它寻宝！", {}
    if ext.get("pet_explore"):
        return False, f"{ext['pet_explore'].get('name')} 正在秘境探索中，耐心等候其归来！", {}
    if int(doc.stones) < PET_EXPLORE_COST:
        return False, f"需要 {PET_EXPLORE_COST:,} 灵石作为寻宝资费！", {}
    place = rng.choice(TOWER_PLACES)
    st = {"name": str(pet["name"]), "ts": now, "place": place}
    lines = (
        f"{pet['name']}长啸一声，化作一道流光遁入「{place}」寻访仙缘！\n"
        f"（消耗灵石 {PET_EXPLORE_COST:,}；{PET_EXPLORE_MIN_MINUTES} 分钟后可 #结束仙宠寻宝，"
        f"每 4 分钟计 1 次收获，最多 {PET_EXPLORE_MAX_COUNT} 次）"
    )
    return True, lines, st


def pet_explore_collect(
    doc: Mapping, pool: list[Mapping], now: float, rng: random.Random,
) -> tuple[bool, str, dict, dict[str, int]]:
    """结算寻宝：返回 (ok, msg, 状态清理, 收获表)。"""
    ext = doc.ext if isinstance(doc.ext, Mapping) else {}
    st = ext.get("pet_explore") or {}
    if not st:
        return False, "没有仙宠在外寻宝。", {}, {}
    minutes = (now - float(st.get("ts", now))) / 60
    if minutes < PET_EXPLORE_MIN_MINUTES:
        return False, f"天地禁制未消！还需 {int(PET_EXPLORE_MIN_MINUTES - minutes)} 分钟才能召回 {st.get('name')}。", {}, {}
    count = min(int(minutes // 4), PET_EXPLORE_MAX_COUNT)
    gains: dict[str, int] = {}
    for _ in range(max(1, count)):
        item = pool and rng.choice(pool)
        if item:
            gains[item["name"]] = gains.get(item["name"], 0) + int(item.get("数量", 1) or 1)
    parts = "，".join(f"{k} ×{v}" for k, v in gains.items()) or "一缕仙缘之气"
    msg = f"{st.get('name')} 自「{st.get('place')}」归来！\n收获：{parts}（{count} 次探查）"
    return True, msg, {}, gains


def build_pet_pool(item_index: Mapping[str, Mapping]) -> list[dict]:
    """从物品索引构建寻宝奖励池（加权：低稀有度多数、高稀有度少量）。"""
    pool: list[dict] = []
    for name, item in item_index.items():
        try:
            rar = int(float(item.get("稀有度") or 0))
        except (TypeError, ValueError):
            rar = 0
        if name in AURA_POOL_HINT or rar <= 6:
            weight = max(1, 10 - rar)
            pool.extend([{"name": name, "class": item.get("class", "材料"),
                          "数量": 1 + (3 if rar <= 3 else 0)}] * min(weight, 4))
    return pool


# ---- 洗劫（Xijie.js 即时化） ----

def raid_guard(grade: int) -> dict:
    g = max(1, int(grade))
    return {"atk": 60_000 * g, "defense": 45_000 * g, "hp": 900_000 * g, "bao": 0.08}


def raid_fight(
    stats: Mapping, guard: Mapping, rng: random.Random,
) -> tuple[bool, list[str]]:
    from . import battle as battle_mod
    me_hp, en_hp = int(stats.get("hp", 1)), int(guard["hp"])
    log: list[str] = []
    for rnd in range(1, 31):
        dmg, crit = battle_mod.harm(int(stats.get("atk", 1)), int(guard["defense"]), rng,
                                    float(stats.get("bao", 0)))
        en_hp -= dmg
        log.append(f"第{rnd}合：你造成 {dmg}{'（暴击）' if crit else ''}，守卫余 {max(0, en_hp)}")
        if en_hp <= 0:
            return True, log
        back, _ = battle_mod.harm(int(guard["atk"]), int(stats.get("defense", 1)), rng)
        me_hp -= back
        log.append(f"        守卫反击 {back}，你余 {max(0, me_hp)}")
        if me_hp <= 0:
            return False, log
    return me_hp * 3 >= en_hp * 2, log
