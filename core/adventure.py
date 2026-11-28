"""A 档玩法纯函数：镇妖塔 / 仙宠寻宝 / 洗劫（对齐原版 tzzyt.js、Pokemon.js、Xijie.js）。

- 镇妖塔公式直译：Boss 血 50000×层+1万、攻 22000×层+1万、防 36000×层+1万；
  奖励分段（<100 层 100×层+100，<200 层 200×层+1000，其余 300×层+1000）封顶 40 万；
  胜 → 层+5 + 灵石 + 回血 Reward×21；败 → 灵石 −Reward×2
- 仙宠寻宝：800 万灵石门票、120 分钟必须时长、次数 = min(分钟//4, 8)，每次按概率从池抽
- 洗劫：原版为 15 分钟定时动作 + 商店锁，此处即时化（按地点档位抽 NPC 并调用共用战斗引擎）；
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
    """镇妖塔单层战斗（tzzyt.js WorldBossBattle，含交锋随机事件）。"""
    ext = doc.ext if isinstance(doc.ext, Mapping) else {}
    floor = int(ext.get("tower_floor", 0) or 0)
    if floor > TOWER_MAX:
        return False, "【镇妖塔·已达上限】已达到镇妖塔最高层数（50000 层）。", {}, {}
    boss = tower_boss(floor)
    reward = tower_reward(floor)
    from . import battle as battle_mod
    atk = int(stats.get("atk", 1))
    defense = int(stats.get("defense", 1))
    me_hp = int(stats.get("hp_cur", stats.get("hp", 1)))
    en_hp = boss["hp"]
    orb = max(0.0, float(stats.get("orb", 0) or 0))
    bao = max(0.0, float(stats.get("bao", 0) or 0))
    log: list[str] = []
    won = False
    for rnd in range(1, 1001):
        event_roll = rng.random()
        player_damage = (battle_mod.harm(atk, boss["defense"], rng)[0]
                         + int(atk * orb))
        super_attack = 1.5 if rng.random() < bao else 1.0
        if event_roll > 0.5 and rnd == 1:
            player_damage = int(player_damage * 0.3)
        elif event_roll > 0.94:
            player_damage = int(player_damage * 6)
        elif event_roll > 0.9:
            player_damage = int(player_damage * 0.8)
        elif event_roll < 0.1:
            player_damage = int(player_damage * 1.2)
        player_damage = int(player_damage * super_attack + rng.random() * 100)
        en_hp = max(0, en_hp - player_damage)
        log.append(f"第{rnd}合：你造成 {player_damage}{'（暴击）' if super_attack > 1 else ''}，妖物余 {en_hp}")
        if en_hp <= 0:
            won = True
            break

        event_roll = rng.random()
        boss_damage = battle_mod.harm(boss["atk"], int(defense * 0.1), rng)[0]
        if event_roll > 0.94:
            boss_damage = int(boss_damage * 0.6)
        elif event_roll > 0.9:
            boss_damage = int(boss_damage * 0.8)
        elif event_roll < 0.1:
            boss_damage = int(boss_damage * 1.2)
        me_hp = max(0, me_hp - boss_damage)
        log.append(f"        妖物反击 {boss_damage}，你余 {me_hp}")
        if me_hp <= 0:
            break
    d2 = dict(ext)
    d2["hp"] = me_hp
    if won:
        d2["tower_floor"] = floor + 5
        d2["hp"] = me_hp + reward * 21  # 原版直接加气血，不截到血量上限
        msg = (f"镇妖塔第 {floor + 1} 层·未知妖物被斩落！\n"
               + "\n".join(log[-4:])
               + f"\n✅ 层数 +5（当前 {d2['tower_floor']}），灵石 +{reward:,}，气血回复 {reward * 21:,}")
        return True, msg, d2, {"stones": reward}
    if me_hp > 0:  # 1000-round implementation guard; no loss/reward on a stalled fight
        return True, f"【镇妖塔】战斗达到1000合安全上限，未结算损失。\n" + "\n".join(log[-4:]), d2, {"stones": 0}
    d2["hp"] = 0
    penalty = reward * 2
    msg = (f"镇妖塔第 {floor + 1} 层·不敌未知妖物……\n"
           + "\n".join(log[-4:])
           + f"\n❌ 灵石 −{penalty:,}（养伤费用），层数不变。变强再来！")
    return True, msg, d2, {"stones": -penalty}


def tower_batch_fight(doc: Mapping, stats: Mapping, rng: random.Random) -> tuple[bool, str, dict, dict, int]:
    """简化连战（tzzyt.js all_WorldBossBattle）：每层一次伤害检查，胜即满血。"""
    ext = doc.ext if isinstance(doc.ext, Mapping) else {}
    floor = max(0, int(ext.get("tower_floor", 0) or 0))
    hp = max(1, int(stats.get("hp_cur", stats.get("hp", 1))))
    hp_max = max(1, int(stats.get("hp", 1)))
    total_reward = passed = 0
    for _ in range(max(0, (TOWER_MAX - floor + 4) // 5)):
        if floor >= TOWER_MAX or hp <= 0:
            break
        boss = tower_boss(floor)
        reward = tower_reward(floor)
        player_damage = (battle.harm(int(stats.get("atk", 1)), boss["defense"], rng)[0]
                         + int(int(stats.get("atk", 1)) * float(stats.get("orb", 0) or 0)))
        boss_damage = battle.harm(boss["atk"], int(int(stats.get("defense", 1)) * 0.1), rng)[0]
        if player_damage >= boss["hp"]:
            floor += 5
            passed += 5
            total_reward += reward
            hp = hp_max
        elif boss_damage >= hp:
            hp = 0
            break
        else:
            # Source simplified mode declares victory if neither side can one-shot.
            floor += 5
            passed += 5
            total_reward += reward
            hp = hp_max
    out = dict(ext)
    out.update(tower_floor=floor, hp=hp)
    msg = (f"本次挑战结果：\n通过层数：{passed}层\n获得灵石：{total_reward}\n"
           f"当前镇妖塔层数：{floor}"
           + ("\n※ 已达到镇妖塔最高层数 ※" if floor >= TOWER_MAX else ""))
    return True, msg, out, {"stones": total_reward}, passed


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

def raid_guard_preview(grade: int) -> dict:
    """洗劫探查文案沿用原有的粗略血量提示；实际战斗不使用此估值。"""
    g = max(1, int(grade))
    return {"hp": 900_000 * g}


def raid_npc(place: str, grade: int, npc_rows: Any, rng: random.Random) -> dict | None:
    """按原版地点与档位，从 npc_list 的 one/two/three 池抽取守卫。"""
    if not isinstance(npc_rows, (list, tuple)):
        return None
    row = next((x for x in npc_rows if isinstance(x, Mapping) and x.get("name") == place), None)
    pool_name = "one" if int(grade) == 1 else "two" if int(grade) == 2 else "three"
    pool = row.get(pool_name) if row else None
    if not isinstance(pool, list) or not pool:
        return None
    monster = rng.choice(pool)
    return dict(monster) if isinstance(monster, Mapping) else None


def _raid_number(value: Any, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else fallback
    except (TypeError, ValueError):
        return fallback


def raid_guard(monster: Mapping, player: Mapping, grade: int) -> dict:
    """将 NPC 表条目按 xijieNpc.buildXijieNpcCombatant 公式转换。"""
    safe_grade = max(1, math.trunc(_raid_number(grade, 1)))
    grade_scale = 1 + safe_grade * 0.05
    player_atk = _raid_number(player.get("atk"), 1)
    player_def = _raid_number(player.get("defense"), 1)
    player_hp = _raid_number(player.get("current_hp"), _raid_number(player.get("hp_max"), 1))
    techniques = monster.get("学习的功法")
    linggen = monster.get("灵根")
    extra_realms = monster.get("额外体系境界")
    return {
        "id": f"xijie-npc-{monster.get('id') or monster.get('name') or 'unknown'}",
        "名号": monster.get("name") or "未知守卫",
        "攻击": max(1, math.trunc(_raid_number(monster.get("atk"), 1) * player_atk)),
        "防御": max(1, math.trunc(_raid_number(monster.get("def"), 1) * player_def / grade_scale)),
        "血量上限": max(1, math.trunc(_raid_number(monster.get("blood"), 1) * player_hp / grade_scale)),
        "暴击率": _raid_number(monster.get("baoji"), 1),
        "暴击伤害": _raid_number(monster.get("暴击伤害"), 1.5),
        "速度": max(1, math.trunc(_raid_number(monster.get("速度"), 100))),
        "闪避率": _raid_number(monster.get("闪避率")),
        "吸血率": _raid_number(monster.get("吸血率")),
        "穿透": _raid_number(monster.get("穿透")),
        "灵根": copy.deepcopy(linggen) if isinstance(linggen, (Mapping, str)) else linggen,
        "法球倍率": _raid_number(
            linggen.get("法球倍率") if isinstance(linggen, Mapping) else None,
            _raid_number(monster.get("法球倍率")),
        ),
        "学习的功法": list(techniques) if isinstance(techniques, list) else [],
        "当前使用的功法": monster.get("当前使用的功法") or (
            techniques[0] if isinstance(techniques, list) and techniques else ""
        ),
        "level_id": _raid_number(monster.get("level_id")),
        "Physique_id": _raid_number(monster.get("Physique_id")),
        "mijinglevel_id": _raid_number(monster.get("mijinglevel_id")),
        "xiangulevel_id": _raid_number(monster.get("xiangulevel_id")),
        "huafenlevel_id": _raid_number(monster.get("huafenlevel_id")),
        "额外体系境界": copy.deepcopy(extra_realms) if isinstance(extra_realms, Mapping) else {},
        "帝道规则": bool(monster.get("帝道规则")),
        "皇道法则": bool(monster.get("皇道法则")),
        "道途压制": bool(monster.get("道途压制")),
        "法则压制比例": _raid_number(monster.get("法则压制比例")),
    }


def raid_fight(player, guard, rng: random.Random):
    """洗劫使用共用 1v1 战斗引擎，调用方按 A/B 顺序读取玩家剩余气血。"""
    from .combat import run_1v1
    return run_1v1(player, guard, rng)