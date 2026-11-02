"""秘境探索：地点分级 + 程序化遭遇（纯函数，无 IO）。

借鉴原版 SecretPlace 的骨架（地点/门槛/逃离）与 huaxianhu 的标签式生成：
怪物属性 = 玩家境界基础值 × 地点系数 × 深度系数 × 词缀标签；掉落按稀有度过滤物品池。
收益累积在探索会话里，撤离（或被打出局）时由调用方一次性发放。
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .battle import spar_full, Unit

# 秘境地点：名称 → (境界门槛 realm_index, 地点系数, 描述)
PLACES: dict[str, tuple[int, float, str]] = {
    "青冥山": (0, 0.6, "入门试炼地，妖兽横行的青翠山脉。"),
    "落霞谷": (2, 1.0, "落霞与孤鹜齐飞，谷中机缘与凶险并存。"),
    "幽冥渊": (5, 1.8, "终年不见天日的深渊，遍地灵物，遍地枯骨。"),
    "太古战场": (9, 3.0, "上古大能陨落之地，一步一机缘，一步一杀机。"),
}

MONSTER_PREFIX = ("受伤的", "凶暴的", "远古的", "嗜血的", "变异的")
MONSTER_KIND = ("妖狼", "妖狐", "石魔", "血蝠", "藤妖", "骷髅兵")

# 遭遇权重：怪物 / 精英 / 宝箱 / 灵物 / 无事
ENCOUNTER_WEIGHTS = (45, 8, 20, 15, 12)

# 程序化怪物词缀系数
ELITE_MULT = 2.2
PREFIX_MULT = {"受伤的": 0.7, "凶暴的": 1.15, "远古的": 1.4, "嗜血的": 1.25, "变异的": 1.3}


@dataclass
class Session:
    """一次秘境探索会话（序列化到玩家 ext["explore"]）。

    factor > 0 时覆盖地点系数（宗门秘境等动态地点用）。
    """

    place: str
    floor: int = 0
    stones: int = 0
    items: dict[str, int] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    factor: float = 0.0
    sect_name: str = ""    # 非空 = 宗门秘境（每 5 层守关 Boss）
    boss_kills: int = 0    # 本会话击杀守关 Boss 数（结算时宗门基金加成）


def place_factor(name: str) -> float:
    return PLACES.get(name, PLACES["青冥山"])[1]


def depth_mult(floor: int) -> float:
    return 1.0 + 0.15 * max(0, floor)


def make_monster(
    place: str,
    floor: int,
    base: tuple[int, int, int],
    rng: random.Random,
    elite: bool = False,
    factor_override: float = 0.0,
) -> Unit:
    """程序化怪物：基础三维 × 地点系数 × 深度系数 × 词缀。"""
    patk, pdef, php = base
    pf = factor_override if factor_override > 0 else place_factor(place)
    factor = pf * depth_mult(floor) * (ELITE_MULT if elite else 1.0)
    prefix = rng.choice(MONSTER_PREFIX)
    kind = rng.choice(MONSTER_KIND)
    m = PREFIX_MULT[prefix]
    name = f"{prefix}{kind}"
    return Unit(
        name,
        max(1, int(patk * factor * m * (0.85 + 0.3 * rng.random()))),
        max(1, int(pdef * factor * m * (0.85 + 0.3 * rng.random()))),
        max(1, int(php * factor * m * (0.9 + 0.2 * rng.random()))),
    )


def roll_encounter(rng: random.Random) -> str:
    """掷遭遇类型。"""
    total = sum(ENCOUNTER_WEIGHTS)
    x = rng.random() * total
    acc = 0.0
    for kind, w in zip(("monster", "elite", "chest", "herb", "calm"), ENCOUNTER_WEIGHTS):
        acc += w
        if x < acc:
            return kind
    return "monster"


def roll_drop(
    item_pool: list[Mapping], rng: random.Random, floor: int, elite: bool
) -> Mapping | None:
    """按稀有度过滤掉落：深度与精英提升可掉稀有度上限。"""
    if not item_pool:
        return None
    cap = 2 + floor // 3 + (2 if elite else 0)
    candidates = [e for e in item_pool if int(e.get("稀有度", 1) or 1) <= cap]
    pool = candidates or [e for e in item_pool if int(e.get("稀有度", 1) or 1) <= 2]
    return rng.choice(pool) if pool else None


def _scale_enemy(monster: Unit, mods: Mapping | None) -> None:
    """黑皇阵法对敌方的削弱（原地修改）。"""
    if not mods:
        return
    atk_scale = float(mods.get("atk", 1) or 1)
    def_scale = float(mods.get("def", 1) or 1)
    monster.atk = max(1, int(monster.atk * atk_scale))
    monster.defense = max(0, int(monster.defense * def_scale))


def _battle_buff(me: Unit, monster: Unit, buff: Any) -> tuple[int, ...]:
    """战斗开始时结算阵法：返回 spar_full 的 skip_first。"""
    if not buff:
        return ()
    b = buff() or {}
    if b.get("atk_mult"):
        me.atk = max(1, int(me.atk * float(b["atk_mult"])))
    if b.get("bao_add"):
        me.bao = min(1.0, float(me.bao) + float(b["bao_add"]))
    _scale_enemy(monster, b.get("enemy"))
    return (1,) if b.get("stun") else ()


def explore(
    session: Session,
    base: tuple[int, int, int],
    me: Unit,
    item_pool: list[Mapping],
    rng: random.Random,
    stone_scale: float = 1.0,
    sect_mode: bool = False,
    buff: Any = None,
    protect: Any = None,
) -> tuple[Session, Unit, str, bool]:
    """寻宝一次。返回 (更新后的会话, 战斗后的我, 文本, 是否被打出局)。

    宗门秘境（sect_mode）每 5 层强制遭遇守关 Boss（强度 ×3、奖励 ×5）。
    我方血量由调用方以 Unit.hp 传入（当前气血），战斗后同步回 ext。
    buff：战斗开始时的阵法回调 () -> {atk_mult, bao_add, enemy:{atk,def}, stun}；
    只在真正进入战斗时调用，避免空探索白烧次数。
    protect：护道回调 (place, floor, enemy) -> (护道人, 文案) | None；
    战败瞬间调用，触发则气血全复、收益不减、留在秘境。
    """
    session.floor += 1
    boss_floor = sect_mode and (session.floor % 5 == 0)
    kind = roll_encounter(rng)
    depth = depth_mult(session.floor)
    pf = session.factor if session.factor > 0 else place_factor(session.place)

    if boss_floor:
        monster = make_monster(
            session.place, session.floor - 1, base, rng,
            elite=False, factor_override=pf * 3.0,
        )
        skip = _battle_buff(me, monster, buff)
        winner, log, hp_left, _ = spar_full(me, monster, rng, skip_first=skip)
        me.hp = max(0, hp_left)
        tail = log[-1] if log else ""
        if winner == 0:
            stones = int((1500 + 800 * session.floor) * depth * pf)
            session.stones += stones
            session.boss_kills += 1
            drops = []
            for _ in range(2):
                drop = roll_drop(item_pool, rng, session.floor + 4, elite=True)
                if drop:
                    session.items[drop["name"]] = session.items.get(drop["name"], 0) + 1
                    drops.append(drop["name"])
            got = f"，掉落「{'」「'.join(drops)}」" if drops else ""
            session.log.append(f"第{session.floor}层：击败守关Boss·{monster.name}{tail}，得 {stones} 灵石{got}")
            return session, me, tail, False
        saved = protect(session.place, session.floor, monster.name) if protect else None
        if saved:
            name, msg = saved
            me.hp = base[2]
            session.log.append(f"第{session.floor}层：不敌守关Boss·{monster.name}，护道人「{name}」出手相护")
            return session, me, msg, False
        lost = session.stones // 3
        session.stones -= lost
        session.log.append(f"第{session.floor}层：守关Boss·{monster.name}太强{tail}，败退，散失 {lost} 灵石")
        return session, me, tail, True

    if kind in ("monster", "elite"):
        monster = make_monster(
            session.place, session.floor - 1, base, rng,
            elite=(kind == "elite"), factor_override=pf,
        )
        skip = _battle_buff(me, monster, buff)
        winner, log, hp_left, _ = spar_full(me, monster, rng, skip_first=skip)
        me.hp = max(0, hp_left)
        tail = log[-1] if log else ""
        if winner == 0:
            stones = int((300 + 200 * session.floor) * depth * pf * stone_scale * (3 if kind == "elite" else 1))
            session.stones += stones
            drop = roll_drop(item_pool, rng, session.floor, elite=(kind == "elite"))
            got = ""
            if drop:
                session.items[drop["name"]] = session.items.get(drop["name"], 0) + 1
                got = f"，掉落「{drop['name']}」"
            session.log.append(f"第{session.floor}层：击败{monster.name}{tail}，得 {stones} 灵石{got}")
            return session, me, tail, False
        saved = protect(session.place, session.floor, monster.name) if protect else None
        if saved:
            name, msg = saved
            me.hp = base[2]
            session.log.append(f"第{session.floor}层：不敌{monster.name}，护道人「{name}」出手相护")
            return session, me, msg, False
        # 战败：损失全部带入收益的一半灵石（物品保留），被传送出秘境
        lost = session.stones // 2
        session.stones -= lost
        session.log.append(f"第{session.floor}层：不敌{monster.name}{tail}，血战脱身，散失 {lost} 灵石")
        return session, me, tail, True

    if kind == "chest":
        stones = int((500 + 300 * session.floor) * depth * pf * stone_scale)
        session.stones += stones
        session.log.append(f"第{session.floor}层：发现古旧宝箱，开出 {stones} 灵石")
        return session, me, "古旧宝箱中灵光一闪。", False

    if kind == "herb":
        drop = roll_drop(item_pool, rng, session.floor, elite=False)
        if drop:
            session.items[drop["name"]] = session.items.get(drop["name"], 0) + 1
            session.log.append(f"第{session.floor}层：采得灵物「{drop['name']}」")
            return session, me, "灵气扑面，有所收获。", False

    session.log.append(f"第{session.floor}层：静观云海，心神澄明（无事发生）")
    return session, me, "此地灵气平和，并无异动。", False
