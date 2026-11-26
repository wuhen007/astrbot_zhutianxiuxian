"""场域圣墟（W8-F4，对齐原版 apps/User/ShengxuContent.js 992 行 + ShengxuRank.js 67 行
+ model/shengxuContent.js / flowerPollenField.js / flowerPollenSkill.js）。

玩法闭环：探索 12 处圣墟副本（真身 / 沉迷 / 法身三路）→ 进化花粉 + 异果 + 呼吸法残页 +
神术 + 场域残图 + 石罐线索 → 合成呼吸法（5 残页）→ 参悟场域（5 残图升一重天）→
加入圣墟势力领日俸 → 集齐条件「追寻石罐」→ 圣墟榜。

原版场域每重天增加花粉基础三维 3%，最高 9 重；本模块提供 field_attribute_bonus
供角色属性装配调用。神术触发器挂在共享战斗引擎的 on_turn 注册表上；主入口需按文末契约
注册并装配花粉技能。未提供战斗 callback 的旧调用保留胜率估算兼容，但不再额外虚构场域胜率。
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import battle, flower, memory, plane, suiyun

# ---------------------------------------------------------------- 数据

# (章, 名称, 需求花粉境, 生灵, 强度, 媒介, 数量, 积淀, 呼吸法, 传承率, 分钟, 圣药率, 场域残图, 神术池)
DUNGEONS: tuple[dict[str, Any], ...] = (
    {"chapter": "地球篇", "name": "太行山", "req": 2, "monster": "太行苍狼", "scale": 0.68,
     "medium": "普通进化花粉", "amount": 2, "accum": 6, "gongfa": "形意呼吸法", "gongfa_rate": 0.12,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大力牛魔拳", 0.15), ("共振术", 0.08))},
    {"chapter": "地球篇", "name": "昆仑山", "req": 2, "monster": "昆仑兽王", "scale": 0.72,
     "medium": "普通进化花粉", "amount": 2, "accum": 8, "gongfa": "形意呼吸法", "gongfa_rate": 0.18,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("终极拳", 0.15), ("螺旋术", 0.08))},
    {"chapter": "地球篇", "name": "武当山", "req": 3, "monster": "金顶异禽王", "scale": 0.78,
     "medium": "普通进化花粉", "amount": 3, "accum": 8, "gongfa": "太极呼吸法", "gongfa_rate": 0.18,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("闪电拳", 0.15),)},
    {"chapter": "地球篇", "name": "龙虎山", "req": 4, "monster": "枷锁古猿", "scale": 0.86,
     "medium": "灵性进化花粉", "amount": 1, "accum": 10, "gongfa": "太极呼吸法", "gongfa_rate": 0.14,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("火眼金睛", 0.12),)},
    {"chapter": "地球篇", "name": "嵩山", "req": 4, "monster": "嵩山老猿", "scale": 0.88,
     "medium": "灵性进化花粉", "amount": 1, "accum": 10, "gongfa": "大雷音呼吸法", "gongfa_rate": 0.06,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大日如来拳", 0.12),)},
    {"chapter": "地球篇", "name": "终南山", "req": 5, "monster": "异树守卫", "scale": 0.92,
     "medium": "灵性进化花粉", "amount": 1, "accum": 11, "gongfa": "道引呼吸法", "gongfa_rate": 0.04,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("不灭经·护身", 0.12),)},
    {"chapter": "地球篇", "name": "泰山", "req": 5, "monster": "封禅异禽王", "scale": 0.95,
     "medium": "灵性进化花粉", "amount": 2, "accum": 11, "gongfa": "道引呼吸法", "gongfa_rate": 0.05,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大力牛魔拳", 0.10), ("终极拳", 0.08))},
    {"chapter": "地球篇", "name": "顺天玉虚宫", "req": 6, "monster": "失控异变体", "scale": 0.98,
     "medium": "灵性进化花粉", "amount": 2, "accum": 12, "gongfa": "形意呼吸法", "gongfa_rate": 0.10,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("火眼金睛", 0.10), ("闪电拳", 0.08))},
    {"chapter": "地球篇", "name": "大雷音寺遗址", "req": 6, "monster": "雷音尸魔", "scale": 1.00,
     "medium": "灵性进化花粉", "amount": 2, "accum": 12, "gongfa": "大雷音呼吸法", "gongfa_rate": 0.10,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大日如来拳", 0.10), ("不灭经·护身", 0.08))},
    {"chapter": "星路篇", "name": "小阴间星路", "req": 8, "monster": "星路猎杀者", "scale": 1.10,
     "medium": "神性进化花粉", "amount": 1, "accum": 16, "gongfa": "道引呼吸法", "gongfa_rate": 0.07,
     "minutes": 10, "herb_rate": 0.0, "field_page": True,
     "skills": (("寒霜覆地", 0.10), ("七妙宝术·土", 0.10), ("少阴拳", 0.07), ("少阳拳", 0.06))},
    {"chapter": "阳间篇", "name": "阳间名山", "req": 11, "monster": "阳间神祇", "scale": 1.22,
     "medium": "神性进化花粉", "amount": 2, "accum": 20, "gongfa": "道引呼吸法", "gongfa_rate": 0.10,
     "minutes": 15, "herb_rate": 0.05, "field_page": True,
     "skills": (("七妙宝术·金", 0.08), ("七妙宝术·火", 0.08), ("场域法·镇", 0.06),
                ("魂钟精神攻杀术", 0.05), ("五色神光", 0.04), ("金色符文秘术", 0.03))},
    {"chapter": "诡异篇", "name": "魂河古地", "req": 17, "monster": "魂河接引者", "scale": 1.38,
     "medium": "无暇进化花粉", "amount": 1, "accum": 28, "gongfa": "盗引呼吸法", "gongfa_rate": 0.03,
     "minutes": 20, "herb_rate": 0.10, "field_page": True,
     "skills": (("七妙宝术·水", 0.06), ("七妙宝术·木", 0.06), ("七妙宝术·阴", 0.08),
                ("七妙宝术·阳", 0.08), ("时间妙术", 0.05), ("时光术", 0.03),
                ("小六道时光术", 0.03), ("斩千秋", 0.025), ("九宝妙术", 0.015))},
)
DUNGEON_BY_NAME = {d["name"]: d for d in DUNGEONS}

FACTIONS: dict[str, dict[str, Any]] = {
    "菩提基因": {"post": "外勤进化者", "req": 2, "medium": "普通进化花粉",
                 "amount": 3, "dew": 0, "accum": 5},
    "大梦净土": {"post": "外门弟子", "req": 8, "medium": "灵性进化花粉",
                 "amount": 2, "dew": 1, "accum": 10},
    "阳间第一山": {"post": "记名门徒", "req": 12, "medium": "神性进化花粉",
                   "amount": 1, "dew": 2, "accum": 15},
}

# 呼吸法下本提速（分钟）
BREATHING_REDUCTION = {"基础呼吸法": 0, "形意呼吸法": 1, "太极呼吸法": 2,
                       "大雷音呼吸法": 3, "道引呼吸法": 4, "盗引呼吸法": 5}
MIN_MINUTES = 5
TIER_REWARD_RATES = {"one": 0.99, "two": 0.5, "three": 0.25}

ANCESTOR_SEED_CHANCE = 0.0012
PAGE_REQUIRE = 5
LEARNED_PAGE_REWARD = 5          # 已学会时折现进化积淀

FIELD_MAX = 9
FIELD_PAGE_REQUIRE = 5
FIELD_ATTR_PER_STAGE = 0.03
FIELD_WEAKEN_PER_STAGE = 0.04    # 原版场域法·镇：基础压制系数每重天相对提高 4%

JAR = "神秘石罐"
SEED = "花粉路祖种"
JAR_CLUE_REQUIRE = 9
JAR_EXTREMES = ("无敌画卷", "观想真形")
JAR_RISK_MAX = 50
JAR_CLEARED_REQUIRE = 6

EXPLORE_MINUTES_MAX_COUNT = 12
RANK_LIMIT = 20

# 神术数值与回合触发规则来自固定原版 flowerPollenSkill.js。
SKILLS: tuple[dict[str, Any], ...] = (
    {"name": "大力牛魔拳", "type": "道与法", "realm": 2, "pr": 0.18, "effect": "attack", "multiplier": 1.8, "desc": "黄牛所传金牛拳法，蛮力破敌，同阶难挡"},
    {"name": "终极拳", "type": "道与法", "realm": 3, "pr": 0.16, "effect": "attack", "multiplier": 1.6, "desc": "楚风自创拳法，人人可学，随境界升华"},
    {"name": "共振术", "type": "道与法", "realm": 3, "pr": 0.14, "effect": "attack", "multiplier": 1.65, "desc": "由牛魔拳推演而成，以特殊频率震裂护体能量"},
    {"name": "闪电拳", "type": "道与法", "realm": 4, "pr": 0.16, "effect": "attack", "multiplier": 1.5, "desc": "少女曦所授神技，快如电光神霞"},
    {"name": "螺旋术", "type": "道与法", "realm": 4, "pr": 0.13, "effect": "attack", "multiplier": 1.8, "desc": "由蛟魔拳演化，螺旋劲贯穿血肉与魂光"},
    {"name": "火眼金睛", "type": "道与法", "realm": 5, "pr": 0.14, "effect": "attack", "multiplier": 1.9, "desc": "神目洞悉破绽，一击致命"},
    {"name": "不灭经·护身", "type": "道与法", "realm": 6, "pr": 0.14, "effect": "heal", "multiplier": 0.15, "desc": "天地至高经文化用，肉身不灭，生机不绝"},
    {"name": "大日如来拳", "type": "盖世杀术", "realm": 7, "pr": 0.14, "effect": "attack", "multiplier": 2.2, "desc": "残缺禁忌妙术，完整版为阳间最强神技之一"},
    {"name": "寒霜覆地", "type": "道与法", "realm": 8, "pr": 0.13, "effect": "weaken", "multiplier": 0.08, "desc": "斗篷秘术，寒霜领域压制对手气机"},
    {"name": "少阴拳", "type": "道与法", "realm": 8, "pr": 0.12, "effect": "attack", "multiplier": 2.0, "desc": "少阴之力凝于拳锋，寒彻魂光，消磨生机"},
    {"name": "少阳拳", "type": "道与法", "realm": 9, "pr": 0.12, "effect": "attack", "multiplier": 2.1, "desc": "少阳之气炽烈升腾，拳光如日，破尽阴邪"},
    {"name": "七妙宝术·土", "type": "盖世杀术", "realm": 9, "pr": 0.14, "effect": "heal", "multiplier": 0.12, "desc": "七宝之一·土行，凝聚土墙护体，汲取大地生机"},
    {"name": "七妙宝术·金", "type": "盖世杀术", "realm": 10, "pr": 0.12, "effect": "attack", "multiplier": 2.0, "desc": "七宝之一·金行，庚金锋锐，无坚不摧"},
    {"name": "七妙宝术·火", "type": "盖世杀术", "realm": 11, "pr": 0.12, "effect": "attack", "multiplier": 2.2, "desc": "七宝之一·火行，离火燎原，焚尽诸敌"},
    {"name": "七妙宝术·水", "type": "盖世杀术", "realm": 12, "pr": 0.12, "effect": "attack", "multiplier": 2.2, "desc": "七宝之一·水行，癸水滔天，蚀骨消魂"},
    {"name": "魂钟精神攻杀术", "type": "道与法", "realm": 12, "pr": 0.10, "effect": "attack", "multiplier": 2.4, "desc": "魂光凝钟，钟波直击元神，肉身防御难阻"},
    {"name": "场域法·镇", "type": "道与法", "realm": 13, "pr": 0.12, "effect": "weaken", "multiplier": 0.12, "desc": "以身立道、场域体系的镇封秘术，压敌战力"},
    {"name": "七妙宝术·木", "type": "盖世杀术", "realm": 14, "pr": 0.12, "effect": "attack", "multiplier": 2.4, "desc": "七宝之一·木行，乙木生发，困敌绞杀"},
    {"name": "一身化七圣", "type": "盖世杀术", "realm": 15, "pr": 0.10, "effect": "multi", "multiplier": 0.7, "hits": 3, "desc": "化身妙术，一身分化七圣，群起攻之"},
    {"name": "五色神光", "type": "盖世杀术", "realm": 15, "pr": 0.08, "effect": "multi", "multiplier": 0.95, "hits": 3, "desc": "五色神光横扫而过，刷落兵器，磨灭诸法"},
    {"name": "七妙宝术·阴", "type": "盖世杀术", "realm": 16, "pr": 0.10, "effect": "attack", "multiplier": 2.6, "desc": "七宝之一·阴行，太阴化育，吞噬生机"},
    {"name": "金色符文秘术", "type": "盖世杀术", "realm": 17, "pr": 0.08, "effect": "attack", "multiplier": 2.6, "desc": "金色符文流转，无物不破"},
    {"name": "小六道时光术", "type": "盖世杀术", "realm": 17, "pr": 0.07, "effect": "time", "multiplier": 3.1, "desc": "六道轮转，时光成环，将敌手锁在刹那之间"},
    {"name": "七妙宝术·阳", "type": "盖世杀术", "realm": 18, "pr": 0.10, "effect": "attack", "multiplier": 2.8, "desc": "七宝之一·阳行，太阳神光，焚尽万法"},
    {"name": "斩千秋", "type": "盖世杀术", "realm": 18, "pr": 0.06, "effect": "time", "multiplier": 3.3, "desc": "金色法页横断岁月，一击斩落千秋道果"},
    {"name": "时间妙术", "type": "盖世杀术", "realm": 19, "pr": 0.08, "effect": "time", "multiplier": 2.8, "desc": "武疯子一脉秘术，时光锁敌，定身斩魂"},
    {"name": "时光术", "type": "盖世杀术", "realm": 20, "pr": 0.08, "effect": "attack", "multiplier": 3.0, "desc": "触及时光之力，一念之间岁月成刃"},
    {"name": "九宝妙术", "type": "盖世杀术", "realm": 20, "pr": 0.05, "effect": "multi", "multiplier": 1.2, "hits": 3, "desc": "九种祖物质化作九色光轮，刷落万物，摧毁万法"},
)
SKILL_BY_NAME = {s["name"]: s for s in SKILLS}
FLOWER_BATTLE_SKILL_ID = "shengxu_flower_pollen"
SEVEN_TREASURES = ("七妙宝术·土", "七妙宝术·金", "七妙宝术·火", "七妙宝术·水",
                   "七妙宝术·木", "七妙宝术·阴", "七妙宝术·阳")


def _field_stage(value: Any) -> int:
    try:
        return max(0, min(FIELD_MAX, int(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def field_attribute_bonus(flower_realm: Mapping[str, Any], stage: int,
                          path_multiplier: float = 1.0) -> dict[str, int]:
    """原版 calculateFlowerFieldBonus：花粉境基础三维每重天 +3%，最高九重。"""
    try:
        multiplier = max(0.0, float(path_multiplier))
    except (TypeError, ValueError, OverflowError):
        multiplier = 0.0
    if not math.isfinite(multiplier):
        multiplier = 0.0
    rate = _field_stage(stage) * FIELD_ATTR_PER_STAGE * multiplier
    return {
        "atk": math.trunc(float(flower_realm.get("基础攻击", 0) or 0) * rate),
        "defense": math.trunc(float(flower_realm.get("基础防御", 0) or 0) * rate),
        "hp": math.trunc(float(flower_realm.get("基础血量", 0) or 0) * rate),
    }


def flower_skill_names(learned: Any) -> tuple[str, ...]:
    """已学花粉神术按原版固定表顺序返回。"""
    if isinstance(learned, str) or not isinstance(learned, Sequence):
        return ()
    known = {str(name) for name in learned}
    return tuple(skill["name"] for skill in SKILLS if skill["name"] in known)


def _flower_pollen_on_turn(attacker: Any, defender: Any, context: dict[str, Any]) -> None:
    trigger_flower_pollen_skill(attacker, defender, context)


def register_flower_battle_skill() -> None:
    """注册共享战斗引擎使用的唯一聚合花粉技能钩子。"""
    from .combat.skills import SkillSpec, get, register

    if get(FLOWER_BATTLE_SKILL_ID) is None:
        register(SkillSpec(
            id=FLOWER_BATTLE_SKILL_ID,
            name="花粉神术",
            on_turn=_flower_pollen_on_turn,
        ))


def attach_flower_battle_skill(fighter: Any, doc: Any) -> tuple[str, ...]:
    """给共享战斗 Fighter 装配原版逐回合花粉技能。"""
    ext = getattr(doc, "ext", {})
    learned = flower_skill_names(ext.get("gongfa") if isinstance(ext, Mapping) else None)
    if not learned:
        return ()
    register_flower_battle_skill()
    tags = getattr(fighter, "tags", None)
    if not isinstance(tags, dict):
        tags = {}
        fighter.tags = tags
    tags["shengxu_flower_skills"] = learned
    st = ext.get("shengxu") if isinstance(ext, Mapping) else None
    tags["shengxu_field_stage"] = _field_stage(st.get("field_stage", 0) if isinstance(st, Mapping) else 0)
    current = tuple(getattr(fighter, "skills", ()) or ())
    if FLOWER_BATTLE_SKILL_ID not in current:
        fighter.skills = (*current, FLOWER_BATTLE_SKILL_ID)
    return learned


def trigger_flower_pollen_skill(attacker: Any, defender: Any,
                               context: Mapping[str, Any]) -> bool:
    """每次出手按固定神术表逐个掷 pr，并与原版一样至多触发一种。"""
    tags = getattr(attacker, "tags", {})
    tags = tags if isinstance(tags, Mapping) else {}
    learned = set(tags.get("shengxu_flower_skills") or ())
    hp = context.get("hp")
    side = context.get("side")
    rng = context.get("rng")
    log = context.get("log")
    if not learned or not isinstance(hp, list) or side not in (0, 1) or rng is None or not isinstance(log, list):
        return False
    foe = 1 - side
    for skill in SKILLS:
        if skill["name"] not in learned:
            continue
        if float(rng.random()) >= float(skill["pr"]):
            continue
        attack = max(0, int(getattr(attacker, "atk", 0) or 0))
        multiplier = float(skill.get("multiplier", 1.0) or 1.0)
        seven_bonus = 1.0
        if skill["name"] in SEVEN_TREASURES:
            seven_count = sum(name in learned for name in SEVEN_TREASURES)
            seven_bonus += min(0.60, seven_count * 0.15)
        effect = skill["effect"]
        if effect == "heal":
            before = max(0, int(hp[side]))
            wanted = math.floor(attack * multiplier)
            hp[side] = min(int(getattr(attacker, "hp_max", before) or before), before + wanted)
            gained = hp[side] - before
            log.append(f"【{skill['name']}】{attacker.name}周身宝光流转，汲取生机，恢复{gained:,}点生命！")
        elif effect == "weaken":
            stage = _field_stage(tags.get("shengxu_field_stage", 0))
            weakened = math.floor(max(0, int(getattr(defender, "atk", 0) or 0))
                                  * multiplier * (1 + stage * FIELD_WEAKEN_PER_STAGE))
            defender.atk = max(0, int(getattr(defender, "atk", 0) or 0) - weakened)
            log.append(f"【{skill['name']}】{attacker.name}以场域镇压{defender.name}（场域{stage}重天），其攻击降低{weakened:,}！")
        elif effect == "multi":
            hits = max(2, int(skill.get("hits", 2) or 2))
            damage = sum(math.floor(attack * multiplier * seven_bonus) for _ in range(hits))
            hp[foe] = max(0, int(hp[foe]) - damage)
            bonus_text = f"（七妙加成×{seven_bonus:.2f}）" if seven_bonus > 1 else ""
            log.append(f"【{skill['name']}】{attacker.name}化身{hits}道神影轮番轰击，对{defender.name}共造成{damage:,}点伤害{bonus_text}！")
        elif effect == "time":
            damage = math.floor(attack * multiplier * seven_bonus)
            hp[foe] = max(0, int(hp[foe]) - damage)
            effects = getattr(defender, "effects", None)
            if isinstance(effects, dict):
                effects["stun_turns"] = max(1, int(effects.get("stun_turns", 0) or 0))
            bonus_text = f"（七妙加成×{seven_bonus:.2f}）" if seven_bonus > 1 else ""
            log.append(f"【{skill['name']}】{attacker.name}禁锢{defender.name}，造成{damage:,}点伤害并定身一瞬{bonus_text}！")
        else:
            damage = math.floor(attack * multiplier * seven_bonus)
            hp[foe] = max(0, int(hp[foe]) - damage)
            bonus_text = f"（七妙加成×{seven_bonus:.2f}）" if seven_bonus > 1 else ""
            log.append(f"【{skill['name']}】{attacker.name}施展神术，对{defender.name}造成{damage:,}点伤害{bonus_text}！")
        return True
    return False

ITEM_CLASS = {"medium": "道具", "fruit": "道具", "herb": "道具", "gongfa": "功法"}


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）`ext["shengxu"]`；直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("shengxu")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("action", None)
    st.setdefault("daily", {})
    st.setdefault("cleared", {})
    st.setdefault("pages", {})
    st.setdefault("faction", "")
    st.setdefault("faction_day", "")
    st.setdefault("join_reward", False)
    st.setdefault("field_stage", 0)
    st.setdefault("field_pages", 0)
    st.setdefault("clue", 0)
    st.setdefault("jar_claimed", False)
    st.setdefault("runs", 0)
    ext["shengxu"] = st
    return st


def flower_level(doc: Any) -> int:
    st = flower.state_of(doc)
    return int(st["level"]) if st else 0


def flower_accum(doc: Any) -> int:
    st = flower.state_of(doc)
    return int(st["accum"]) if st else 0


def flower_risk(doc: Any) -> int:
    st = flower.state_of(doc)
    return int(st["risk"]) if st else 0


def flower_extremes(doc: Any) -> list[str]:
    st = flower.state_of(doc)
    return list(st["extremes"]) if st else []


def add_accum(doc: Any, amount: int) -> None:
    st = flower.state_of(doc)
    if st is None:
        return
    st["accum"] = int(st["accum"]) + max(0, int(amount))
    flower.set_state(doc, st)


# ---------------------------------------------------------------- 副本

def dungeon_of(name: str) -> dict | None:
    return DUNGEON_BY_NAME.get(str(name or "").strip())


def reward_tiers_of(dun: Mapping[str, Any]) -> dict[str, tuple[tuple[str, int], ...]]:
    level = max(1, int(dun.get("req") or 1))
    fruit = "祖种异果" if level >= 14 else "本源异果" if level >= 7 else "进化异果"
    three = [(str(dun["gongfa"]), 1)]
    if dun.get("herb_rate"):
        three.append(("本源圣药", 1))
    return {
        "one": ((str(dun["medium"]), 1),),
        "two": ((fruit, 1),),
        "three": tuple(three),
    }


def resolve_tier_reward(dun: Mapping[str, Any], rng: Any,
                         rates: Mapping[str, Any] | Sequence[Any] | None = None) -> dict[str, Any] | None:
    configured = dict(TIER_REWARD_RATES)
    if isinstance(rates, Mapping):
        supplied = (rates.get("one"), rates.get("two"), rates.get("three"))
    elif isinstance(rates, Sequence) and not isinstance(rates, (str, bytes)) and len(rates) >= 3:
        supplied = rates[:3]
    else:
        supplied = ()
    for key, value in zip(("one", "two", "three"), supplied):
        try:
            configured[key] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError, OverflowError):
            pass
    if rng.random() > configured["one"]:
        return None
    tier = "one"
    if rng.random() <= configured["two"]:
        tier = "three" if rng.random() <= configured["three"] else "two"
    pool = reward_tiers_of(dun)[tier]
    index = min(len(pool) - 1, math.floor(max(0.0, float(rng.random() or 0.0)) * len(pool)))
    name, amount = pool[index]
    return {"tier": tier, "name": name, "amount": amount}



def _positive(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def _permanently_nontradeable(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    name = str(item.get("name") or "")
    return (name in {"无上天阙枝", "岁云的残念", "岁云残念"}
            or bool(item.get("全时间线唯一"))
            or item.get("不可交易") is True
            or _positive(item.get("不可交易"))
            or item.get("全服唯一") is True
            or _positive(item.get("全服唯一"))
            or bool(item.get("大道至宝本体"))
            or item.get("品阶") == "先天至宝"
            or (item.get("type") == "帝兵" and bool(item.get("author_name"))))


def _guaranteed_recollection(dun: Mapping[str, Any], already_awarded: set[str],
                             tiers: Sequence[str], settlement_id: str,
                             item_lookup: Callable[[str], Mapping[str, Any] | None] | None,
                             multiplier: int) -> list[tuple[str, int, str]]:
    """原版律法因子：确定性保底掉落，并跳过全服唯一/不可交易物品。"""
    drops: list[tuple[str, int, str]] = []
    for tier in tiers:
        pool = [item for item in reward_tiers_of(dun).get(str(tier), ())
                if item[0] not in already_awarded]
        if item_lookup is not None:
            pool = [item for item in pool if not _permanently_nontradeable(item_lookup(item[0]))]
        if not pool:
            continue
        token = f"memory-law:shengxu:{settlement_id}:{tier}"
        seed = 0
        for char in token:
            seed = (seed * 31 + ord(char)) & 0xFFFFFFFF
        name, amount = pool[seed % len(pool)]
        drops.append((name, int(amount) * max(1, int(multiplier)), str(tier)))
        already_awarded.add(name)
    return drops

def plane_of(dun: Mapping[str, Any]) -> str:
    return "阳间" if dun.get("chapter") in ("阳间篇", "诡异篇") else "小阴间"


def explore_cost(dun: Mapping[str, Any], count: int = 1, doc: Any = None) -> dict[str, int]:
    lv = max(1, int(dun.get("req") or 1))
    sc = max(0.1, float(dun.get("scale") or 1.0))
    n = max(1, int(count or 1))
    gate = float(memory.effects(doc).get("gate") or 0.0) if doc is not None else 0.0
    multiplier = 1.0 - max(0.0, min(1.0, gate))
    unit = {
        "xiuwei": int(round(1_000_000 * lv * sc)),
        "xueqi": int(round(1_000_000 * lv * sc)),
        "lingshi": int(round(500_000 * lv * sc)),
        "shouyuan": max(1, int(math.ceil(float(dun.get("minutes") or 5) / 5))),
    }
    return {key: int(math.ceil(value * multiplier)) * n for key, value in unit.items()}


def minutes_of(doc: Any, dun: Mapping[str, Any]) -> int:
    learned = set(doc.ext.get("gongfa") or []) if isinstance(doc.ext, dict) else set()
    red = max([v for k, v in BREATHING_REDUCTION.items() if k in learned] or [0])
    minutes = max(MIN_MINUTES, int(dun.get("minutes") or 15) - red)
    sky = suiyun.state_of(doc)
    seals = sky.get("seals") if isinstance(sky, Mapping) else None
    if isinstance(seals, Mapping) and "天空" in seals:
        minutes = max(1, minutes - 1)
    return minutes


def shortages(doc: Any, cost: Mapping[str, int]) -> list[str]:
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    have = {
        "修为": int(doc.exp),
        "血气": int(ext.get("xueqi", 0) or 0),
        "灵石": int(doc.stones),
        "寿元": int(ext.get("shouyuan", 0) or 0),
    }
    out = []
    for field, key in (("修为", "xiuwei"), ("血气", "xueqi"), ("灵石", "lingshi"), ("寿元", "shouyuan")):
        if have[field] < int(cost[key]):
            out.append(f"{field}需{int(cost[key]):,}，现有{have[field]:,}")
    return out



def action_settlement_id(uid: str, action: Mapping[str, Any]) -> str:
    current = str(action.get("settlement_id") or "").strip()
    if current:
        return current
    raw = f"{uid}|{action.get('start')}|{action.get('end')}|{action.get('dungeon')}|{action.get('count')}"
    return "legacy:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
def action_of(doc: Any) -> dict | None:
    act = state_of(doc).get("action")
    return act if isinstance(act, dict) else None


def begin(doc: Any, name: str, count: int, now: float, era_index: int | None = None) -> tuple[bool, str]:
    """#探索圣墟 / #沉迷圣墟：校验位面与成本，起一个惰性计时行动。"""
    st = state_of(doc)
    if era_index is not None:
        from . import era as era_mod
        era_mod.sync_jueling_lifespan(doc, era_index)
    dun = dungeon_of(name)
    if not dun:
        return False, "圣墟副本仅：" + "、".join(d["name"] for d in DUNGEONS)
    if flower.state_of(doc) is None:
        return False, "圣墟只向花粉进化路的修士显形（先发送「#踏上花粉路」）。"
    if isinstance(st.get("action"), dict):
        return False, "你正在圣墟中探索，先发送「#探索圣墟」结算。"
    level = flower_level(doc)
    if level < int(dun["req"]):
        return False, (f"【{dun['name']}】需花粉境 {dun['req']} 阶"
                       f"（当前 {level} 阶）。")
    need_plane = plane_of(dun)
    cur = plane.current(plane.state_of(doc))
    if cur != need_plane:
        return False, f"【{dun['name']}】位于【{need_plane}】，你当前在【{cur}】。"
    n = max(1, min(EXPLORE_MINUTES_MAX_COUNT, int(count or 1)))
    daily = st.get("daily")
    if not isinstance(daily, dict):
        daily = st["daily"] = {}
    day = time.strftime("%Y%m%d", time.gmtime(float(now) + 8 * 60 * 60))
    if n == 1 and daily.get(dun["name"]) == day:
        return False, f"你今日已经探索过{dun['name']}。"
    cost = explore_cost(dun, n, doc=doc)
    lack = shortages(doc, cost)
    if lack:
        return False, "资源不足：" + "；".join(lack)
    if n == 1:
        daily[dun["name"]] = day
    doc.exp -= cost["xiuwei"]
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - cost["xueqi"]
    doc.stones -= cost["lingshi"]
    from .lifespan import spend as spend_lifespan
    spend_lifespan(doc, cost["shouyuan"])
    minutes = minutes_of(doc, dun) * n
    st["action"] = {"settlement_id": secrets.token_hex(16), "dungeon": dun["name"], "count": n, "start": float(now),
                    "end": float(now) + minutes * 60, "minutes": minutes}
    return True, (f"你踏入圣墟【{dun['name']}】（{dun['chapter']}）×{n}。\n"
                  f"消耗：修为 {cost['xiuwei']:,}｜血气 {cost['xueqi']:,}｜"
                  f"灵石 {cost['lingshi']:,}｜寿元 {cost['shouyuan']}\n"
                  f"预计 {minutes} 分钟（呼吸法与「天空」权柄提速后），到期后再发「#探索圣墟」结算。")


def win_rate(doc: Any, dun: Mapping[str, Any], field_stage: int = 0) -> float:
    """Legacy settlement estimate; field-stage bonuses are applied to real stats."""
    edge = flower_level(doc) - int(dun.get("req") or 1)
    return max(0.15, min(0.95, 0.5 + edge * 0.08))


def monster_unit(doc: Any, dun: Mapping[str, Any], stats: Any) -> Any:
    """原版 `createShengxuMonster` 镜像：按本轮真身属性缩放，不携带功法。"""
    from .battle import Unit
    scale = max(0.1, float(dun.get("scale") or 1))
    hp_max = max(1, int(getattr(stats, "hp", 0) or 0))
    return Unit(
        str(dun.get("monster") or "异变生灵"),
        max(1, int(max(1, int(getattr(stats, "atk", 0) or 0)) * scale)),
        max(1, int(max(1, int(getattr(stats, "defense", 0) or 0)) * scale)),
        max(1, int(hp_max * scale)),
        max(0.1, float(getattr(stats, "bao", 0.1) or 0.1)),
        speed=max(100, int(max(100, int(getattr(stats, "speed", 100) or 100)) * scale)),
        crit_damage=max(1.5, float(getattr(stats, "crit_damage", 1.5) or 1.5)),
    )


def settle(doc: Any, st: dict, now: float, rng: Any,
           battle_runner: Callable[[Any, Mapping[str, Any], Any, int], Any] | None = None,
           tier_rates: Mapping[str, Any] | Sequence[Any] | None = None,
           item_lookup: Callable[[str], Mapping[str, Any] | None] | None = None
           ) -> tuple[bool, str, dict[str, int], list[str]]:
    """结算到期探索；传入 callback 时逐轮进行真实共享战斗。Callback 参数为 `(doc, dungeon, rng, one_based_round)`，可返回 BattleResult 或 `(winner, log, a_hp, b_hp)`。
    tier_rates 接收原版 SecretPlace 的 one/two/three 配置或时代系统的三元组；
    item_lookup 用于跳过原版律法保底池中的永久唯一/不可交易物。
    未传 callback 时仅兼容旧的胜率结算入口。
    """
    act = st.get("action")
    if not isinstance(act, dict):
        return False, "", {}, []
    if float(act.get("end") or 0) > now:
        left = int(float(act["end"]) - now)
        return False, f"尚在圣墟中，还需 {left // 60} 分 {left % 60} 秒。", {}, []
    dun = dungeon_of(str(act.get("dungeon")))
    if not dun:
        st["action"] = None
        return False, "该圣墟副本已不可考，行动作废。", {}, []
    st["action"] = None
    count = max(1, int(act.get("count") or 1))
    ext_gongfa = doc.ext.setdefault("gongfa", [])
    if not isinstance(ext_gongfa, list):
        ext_gongfa = doc.ext["gongfa"] = []
    items: dict[str, int] = {}
    learned: list[str] = []
    lines: list[str] = [f"--- 圣墟探索 · {dun['name']} ---"]
    wins = 0
    for i in range(count):
        battle_log: list[str] = []
        player_hp = 0
        if battle_runner is None:
            won = rng.random() <= win_rate(doc, dun)
        else:
            result = battle_runner(doc, dun, rng, i + 1)
            if isinstance(result, tuple):
                parts = list(result) + [0, 0, 0, 0]
                winner, battle_log, player_hp, _enemy_hp = parts[:4]
            else:
                winner = getattr(result, "winner", None)
                battle_log = list(getattr(result, "log", []) or [])
                player_hp = int(getattr(result, "a_hp", 0) or 0)
            won = winner == 0
        if battle_log:
            lines.extend(str(line) for line in battle_log[-8:])
        if not won:
            doc.ext["hp"] = 1
            lines.append(f"第 {i + 1} 次：【探索失败】你被{dun['monster']}重创，血量降至 1。")
            break
        if battle_runner is not None:
            doc.ext["hp"] = max(1, int(player_hp or 1))
        wins += 1
        lv = int(dun["req"])
        doc.exp += 5_000_000 * lv
        doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + 5_000_000 * lv
        doc.stones += 2_000_000 * lv
        add_accum(doc, int(dun["accum"]))
        items[dun["medium"]] = items.get(dun["medium"], 0) + int(dun["amount"])
        # 异果：等级越高品质越好
        if rng.random() < min(0.28, 0.08 + lv * 0.01):
            fruit = "祖种异果" if lv >= 14 else ("本源异果" if lv >= 7 else "进化异果")
            items[fruit] = items.get(fruit, 0) + 1
        if dun["herb_rate"] and rng.random() < float(dun["herb_rate"]):
            items["本源圣药"] = items.get("本源圣药", 0) + 1
        # 呼吸法：直接传承 + 残页收集
        if rng.random() < float(dun["gongfa_rate"]):
            name = str(dun["gongfa"])
            if name not in ext_gongfa:
                ext_gongfa.append(name)
                learned.append(name)
        page = collect_page(st, str(dun["gongfa"]), ext_gongfa)
        # 神术参悟
        for skill, chance in dun["skills"]:
            if rng.random() < float(chance):
                if skill not in ext_gongfa:
                    ext_gongfa.append(skill)
                    learned.append(skill)
                break
        # 场域残图
        field_note = ""
        if dun["field_page"]:
            fp = collect_field_page(st)
            field_note = f"｜场域残图 {fp['pages']}/{FIELD_PAGE_REQUIRE}"
        # 祖种（全服唯一，千分之一量级）
        if rng.random() < ANCESTOR_SEED_CHANCE:
            items[SEED] = items.get(SEED, 0) + 1
            field_note += "｜【全服唯一机缘】花粉路祖种"
        tier_reward = resolve_tier_reward(dun, rng, tier_rates)
        tier_note = ""
        if tier_reward:
            reward_name = str(tier_reward["name"])
            reward_amount = int(tier_reward["amount"])
            items[reward_name] = items.get(reward_name, 0) + reward_amount
            tier_note = f"｜{tier_reward['tier']}档奖励 {reward_name}×{reward_amount}"
        guaranteed_tiers = ("one", "two", "three")[:memory.memory_factor_tier(doc, "律法")]
        if guaranteed_tiers:
            loot_multiplier = max(1, int(memory.effects(doc).get("item_mult", 1) or 1)) * max(1, int(suiyun.loot_mult(doc)))
            settlement_id = action_settlement_id(str(getattr(doc, "uid", "")), act)
            already_awarded = set(items) | set(learned)
            for guaranteed_name, guaranteed_amount, guaranteed_tier in _guaranteed_recollection(
                    dun, already_awarded, guaranteed_tiers, f"{settlement_id}:round:{i + 1}",
                    item_lookup, loot_multiplier):
                items[guaranteed_name] = items.get(guaranteed_name, 0) + guaranteed_amount
                lines.append(f"律法因子保底获得【{guaranteed_name}】×{guaranteed_amount}（{guaranteed_tier}档）。")
        st["clue"] = int(st.get("clue") or 0) + 1
        cleared = st.setdefault("cleared", {})
        cleared[dun["name"]] = int(cleared.get(dun["name"]) or 0) + 1
        st["runs"] = int(st.get("runs") or 0) + 1
        lines.append(f"第 {i + 1} 次：【胜利】{dun['medium']}×{dun['amount']}｜"
                     f"进化积淀 +{dun['accum']}｜石罐线索 +1｜"
                     f"修为+{5_000_000 * lv:,}｜血气+{5_000_000 * lv:,}｜"
                     f"灵石+{2_000_000 * lv:,}" + field_note + tier_note)
        if page.get("ok"):
            if page.get("learned"):
                add_accum(doc, int(page.get("reward") or 0))
                lines.append(f"　已掌握【{page['gongfa']}】，残页折现进化积淀 +{page.get('reward')}")
            else:
                lines.append(f"　拾取【{page['gongfa']}·残页】{page['count']}/{PAGE_REQUIRE}")
    if wins == 0:
        return True, "\n".join(lines), items, learned
    lines.append(f"本次通关 {wins}/{count} 次｜累计通关 {len(st.get('cleared') or {})} 处不同的圣墟")
    return True, "\n".join(lines), items, learned


# ---------------------------------------------------------------- 呼吸法

def collect_page(st: dict, gongfa: str, learned: Sequence[str]) -> dict:
    if not gongfa:
        return {"ok": False, "reason": "no-gongfa"}
    pages = st.setdefault("pages", {})
    if gongfa in learned:
        return {"ok": True, "gongfa": gongfa, "learned": True,
                "reward": LEARNED_PAGE_REWARD, "count": int(pages.get(gongfa) or 0)}
    pages[gongfa] = int(pages.get(gongfa) or 0) + 1
    return {"ok": True, "gongfa": gongfa, "learned": False,
            "count": pages[gongfa], "need": PAGE_REQUIRE}


def synthesize(doc: Any, st: dict, gongfa: str) -> tuple[bool, str]:
    """#合成呼吸法：5 张残页 → 学会该呼吸法。"""
    gongfa = str(gongfa or "").strip()
    if gongfa not in BREATHING_REDUCTION:
        return False, "可合成呼吸法：" + "、".join(BREATHING_REDUCTION)
    learned = doc.ext.setdefault("gongfa", [])
    if not isinstance(learned, list):
        learned = doc.ext["gongfa"] = []
    if gongfa in learned:
        return False, f"你已掌握【{gongfa}】。"
    pages = st.setdefault("pages", {})
    count = int(pages.get(gongfa) or 0)
    if count < PAGE_REQUIRE:
        return False, f"【{gongfa}】残页 {count}/{PAGE_REQUIRE}，还需 {PAGE_REQUIRE - count} 张。"
    pages[gongfa] = count - PAGE_REQUIRE
    learned.append(gongfa)
    return True, (f"五张残页在你识海中拼合——【{gongfa}】成篇。\n"
                  f"圣墟探索耗时 -{BREATHING_REDUCTION[gongfa]} 分钟（下限 {MIN_MINUTES} 分钟）。")


# ---------------------------------------------------------------- 场域

def collect_field_page(st: dict, amount: int = 1) -> dict:
    st["field_pages"] = int(st.get("field_pages") or 0) + max(1, int(amount))
    stage = int(st.get("field_stage") or 0)
    return {"ok": True, "pages": st["field_pages"], "stage": stage,
            "can_advance": stage < FIELD_MAX and st["field_pages"] >= FIELD_PAGE_REQUIRE}


def advance_field(st: dict) -> tuple[bool, str]:
    stage = int(st.get("field_stage") or 0)
    pages = int(st.get("field_pages") or 0)
    if stage >= FIELD_MAX:
        return False, f"场域已至 {FIELD_MAX} 重天（圆满），无法再参悟。"
    if pages < FIELD_PAGE_REQUIRE:
        return False, f"场域残图 {pages}/{FIELD_PAGE_REQUIRE}，还需 {FIELD_PAGE_REQUIRE - pages} 张。"
    st["field_pages"] = pages - FIELD_PAGE_REQUIRE
    st["field_stage"] = stage + 1
    stage += 1
    return True, (f"参悟场域：{stage} 重天。\n"
                  f"花粉基础三维 +{stage * FIELD_ATTR_PER_STAGE:.0%}\n"
                  f"剩余残图 {st['field_pages']} 张。")


def field_profile(st: Mapping[str, Any]) -> dict:
    stage = max(0, min(FIELD_MAX, int(st.get("field_stage") or 0)))
    return {"stage": stage, "max": FIELD_MAX, "pages": int(st.get("field_pages") or 0),
            "need": FIELD_PAGE_REQUIRE, "attr": stage * FIELD_ATTR_PER_STAGE,
            "win": 0.0, "weaken": stage * FIELD_WEAKEN_PER_STAGE}


# ---------------------------------------------------------------- 势力

def join_faction(doc: Any, st: dict, name: str, now: float) -> tuple[bool, str, dict[str, int]]:
    name = str(name or "").strip()
    info = FACTIONS.get(name)
    if not info:
        return False, "圣墟势力仅：" + "、".join(FACTIONS), {}
    if st.get("faction"):
        return False, f"你已投身【{st['faction']}】，圣墟不容二主。"
    level = flower_level(doc)
    if level < int(info["req"]):
        return False, f"【{name}】只收花粉境 {info['req']} 阶以上（当前 {level} 阶）。", {}
    st["faction"] = name
    items = {str(info["medium"]): int(info["amount"])}
    if info["dew"]:
        items["净化花露"] = int(info["dew"])
    add_accum(doc, int(info["accum"]))
    lines = [f"你投身【{name}】，位列「{info['post']}」。",
             f"入势力礼：{info['medium']}×{info['amount']}"
             + (f"｜净化花露×{info['dew']}" if info["dew"] else "")
             + f"｜进化积淀 +{info['accum']}"]
    if not st.get("join_reward"):
        st["join_reward"] = True
    return True, "\n".join(lines), items


def salary(doc: Any, st: dict, now: float) -> tuple[bool, str, dict[str, int]]:
    name = str(st.get("faction") or "")
    info = FACTIONS.get(name)
    if not info:
        return False, "你尚未加入圣墟势力（#圣墟势力 查看）。", {}
    day = time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))
    if st.get("faction_day") == day:
        return False, "今日俸禄已领，明日再来。", {}
    st["faction_day"] = day
    items = {str(info["medium"]): int(info["amount"])}
    if info["dew"]:
        items["净化花露"] = int(info["dew"])
    add_accum(doc, int(info["accum"]))
    return True, (f"--- {name}俸禄 ---\n{info['medium']}×{info['amount']}"
                  + (f"｜净化花露×{info['dew']}" if info["dew"] else "")
                  + f"｜进化积淀 +{info['accum']}"), items


# ---------------------------------------------------------------- 石罐

def jar_requirements(doc: Any, st: Mapping[str, Any]) -> dict:
    cleared = len(st.get("cleared") or {})
    clue = int(st.get("clue") or 0)
    extremes = flower_extremes(doc)
    missing = [n for n in JAR_EXTREMES if n not in extremes]
    risk = flower_risk(doc)
    reasons = []
    if flower_level(doc) < 11:
        reasons.append("花粉境需至映照诸天（11 阶）")
    if cleared < JAR_CLEARED_REQUIRE:
        reasons.append(f"需踏破 {JAR_CLEARED_REQUIRE} 处不同圣墟（当前 {cleared}）")
    if clue < JAR_CLUE_REQUIRE:
        reasons.append(f"需石罐线索 {JAR_CLUE_REQUIRE} 枚（当前 {clue}）")
    if missing:
        reasons.append("需极境：" + "、".join(missing))
    if risk > JAR_RISK_MAX:
        reasons.append(f"花粉隐患需不高于 {JAR_RISK_MAX}（当前 {risk}）")
    return {"ok": not reasons, "reasons": reasons, "cleared": cleared,
            "clue": clue, "risk": risk}


def claim_jar(doc: Any, st: dict, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    if st.get("jar_claimed") or int(inv.get(JAR, 0) or 0) > 0:
        return False, f"【{JAR}】已在认主之人的纳戒中，天地间只此一只。", {}
    info = jar_requirements(doc, st)
    if not info["ok"]:
        return False, "石罐机缘未至：\n· " + "\n· ".join(info["reasons"]), {}
    st["jar_claimed"] = True
    return True, (f"你循着 {info['clue']} 枚线索走到圣墟深处，"
                  f"荒芜的祭台上静静立着一只【{JAR}】。\n它认你为主。"), {JAR: 1}


# ---------------------------------------------------------------- 榜单 / 文案

def rank_entries(rows: Iterable[Any], limit: int = RANK_LIMIT) -> list[dict]:
    out = []
    for doc in rows:
        st = flower.state_of(doc)
        if st is None:
            continue
        sx = (doc.ext or {}).get("shengxu") if isinstance(doc.ext, dict) else None
        sx = sx if isinstance(sx, dict) else {}
        out.append({
            "name": doc.name or doc.uid,
            "level": int(st["level"]),
            "extremes": len(st["extremes"]),
            "field": int(sx.get("field_stage") or 0),
            "cleared": len(sx.get("cleared") or {}),
            "accum": int(st["accum"]),
        })
    out.sort(key=lambda r: (-r["level"], -r["field"], -r["cleared"], -r["extremes"], -r["accum"]))
    return out[:max(1, min(RANK_LIMIT, int(limit or RANK_LIMIT)))]


def rank_text(rows: Iterable[Any], limit: int = RANK_LIMIT, me: str = "") -> str:
    entries = rank_entries(rows, limit)
    lines = ["--- 圣墟榜 · 花粉进化路 ---",
             "排序：花粉境界 ＞ 场域重天 ＞ 通关副本数 ＞ 极境数 ＞ 进化积淀", ""]
    if not entries:
        lines.append("当前还没有花粉路修士登榜。")
        return "\n".join(lines)
    for i, e in enumerate(entries, 1):
        mark = "（你）" if me and e["name"] == me else ""
        lines.append(f"{i}. {e['name']}{mark}｜{e['level']} 阶｜场域 {e['field']} 重天｜"
                     f"通关 {e['cleared']} 处｜极境 {e['extremes']}｜积淀 {e['accum']}")
    return "\n".join(lines)


def dungeons_text(doc: Any) -> str:
    level = flower_level(doc)
    current_plane = plane.current(plane.state_of(doc))
    lines = [f"--- 圣墟副本 · {len(DUNGEONS)} 处 ---",
             f"当前位面：{current_plane}｜花粉境：{level} 阶"]
    cur_chapter = ""
    for d in DUNGEONS:
        if d["chapter"] != cur_chapter:
            cur_chapter = d["chapter"]
            lines.append(f"— {cur_chapter} —")
        cost = explore_cost(d, 1, doc=doc)
        shortages_now = shortages(doc, cost)
        realm_ready = level >= int(d["req"])
        need_plane = plane_of(d)
        plane_ready = current_plane == need_plane
        status = ("可探索" if not shortages_now else shortages_now[0])
        if not realm_ready:
            status = f"花粉序列不足（需 {d['req']} 阶）"
        elif not plane_ready:
            status = f"需身处{need_plane}"
        lines.append(f"· {d['name']}｜需花粉境 {d['req']} 阶｜位面 {need_plane}｜"
                     f"{minutes_of(doc, d)} 分钟｜{status}")
        lines.append(f"  入场消耗：修为 {cost['xiuwei']:,}｜血气 {cost['xueqi']:,}｜"
                     f"灵石 {cost['lingshi']:,}｜寿元 {cost['shouyuan']}")
        fruit_chance = min(0.28, 0.08 + int(d["req"]) * 0.01)
        chances = [f"异果 {fruit_chance:.0%}", f"{d['gongfa']}传承 {float(d['gongfa_rate']):.0%}",
                   f"祖种 {ANCESTOR_SEED_CHANCE:.2%}"]
        if d.get("herb_rate"):
            chances.append(f"本源圣药 {float(d['herb_rate']):.0%}")
        if d.get("skills"):
            chances.append("神术：" + "、".join(name for name, _chance in d["skills"]))
        guaranteed = f"通关保底：{d['medium']}×{d['amount']}｜修为+{5_000_000 * int(d['req']):,}｜"
        guaranteed += f"血气+{5_000_000 * int(d['req']):,}｜灵石+{2_000_000 * int(d['req']):,}｜积淀+{d['accum']}"
        if d.get("field_page"):
            guaranteed += "｜场域残图"
        lines.append(guaranteed + "；随机机缘：" + "、".join(chances))
        tiers = reward_tiers_of(d)
        tier_text = "｜".join(f"{tier}档：" + "、".join(f"{name}×{amount}" for name, amount in pool)
                              for tier, pool in tiers.items())
        lines.append(f"  额外奖励池：{tier_text}（按原版 one/two/three 级联抽取）")
    lines.append("「#探索圣墟 名称」一次｜「#沉迷圣墟 名称*次数」连探（上限 12 次）")
    return "\n".join(lines)


def factions_text(st: Mapping[str, Any]) -> str:
    lines = ["--- 圣墟势力 ---"]
    cur = str(st.get("faction") or "")
    for name, info in FACTIONS.items():
        mark = "▶" if name == cur else "·"
        lines.append(f"{mark} {name}｜{info['post']}｜需 {info['req']} 阶｜"
                     f"日俸 {info['medium']}×{info['amount']}"
                     + (f"+净化花露×{info['dew']}" if info["dew"] else "")
                     + f"｜积淀 +{info['accum']}")
    lines.append("「#加入菩提基因|大梦净土|阳间第一山」投身｜「#领取圣墟俸禄」领日俸")
    return "\n".join(lines)


def skills_text(doc: Any) -> str:
    learned = set(doc.ext.get("gongfa") or []) if isinstance(doc.ext, dict) else set()
    got = [s for s in SKILLS if s["name"] in learned]
    seven = [n for n in SEVEN_TREASURES if n in learned]
    lines = [f"--- 神术 · 已参悟 {len(got)}/{len(SKILLS)} ---",
             f"七妙宝术：{len(seven)}/7" + ("（七宝圆满）" if len(seven) == 7 else "")]
    if not got:
        lines.append("尚未参悟任何神术——圣墟副本胜利时按概率参悟。")
    else:
        lines += [f"· {s['name']}（{s['type']}·{s['realm']} 阶）{s['desc']}" for s in got]
    return "\n".join(lines)


def field_text(st: Mapping[str, Any]) -> str:
    p = field_profile(st)
    return "\n".join([
        "--- 场域 ---",
        f"境界：{p['stage']}/{p['max']} 重天｜残图 {p['pages']}/{p['need']}",
        f"花粉境基础三维 +{p['attr']:.0%}",
        f"场域法·镇 压制强化 +{p['weaken']:.1%}",
        f"「#参悟场域」消耗 {p['need']} 张残图升一重天（上限 {p['max']} 重）",
    ])


def jar_text(doc: Any, st: Mapping[str, Any], inv: Mapping[str, int]) -> str:
    info = jar_requirements(doc, st)
    owned = int(inv.get(JAR, 0) or 0) > 0 or bool(st.get("jar_claimed"))
    lines = ["--- 石罐机缘 ---",
             f"状态：{'已认主' if owned else ('条件已足，可「#追寻石罐」' if info['ok'] else '未至')}",
             f"花粉境：{flower_level(doc)}｜已破副本 {info['cleared']} 处｜"
             f"石罐线索 {info['clue']}/{JAR_CLUE_REQUIRE}｜花粉隐患 {info['risk']}"]
    if info["reasons"]:
        lines.append("尚未满足：")
        lines += [f"· {r}" for r in info["reasons"]]
    elif not owned:
        lines.append("「#追寻石罐」循线索走一趟圣墟深处。")
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 场域圣墟 · 规则 ---",
        "· 12 处副本分四篇（地球 9 / 星路 1 / 阳间 1 / 诡异 1）；"
        "地球篇在小阴间，阳间篇与诡异篇在阳间。",
        "· 入场消耗：修为/血气 = 100 万 × 需求阶 × 强度，灵石 = 50 万 × 需求阶 × 强度，"
        "寿元 = ceil(基础分钟/5)；记忆命途门径再减 0/20/30/40%；连探按次数翻倍。",
        "· 耗时：基础 7/10/15/20 分钟 − 呼吸法提速（0~5 分钟），再由「天空」权柄减 1 分钟，"
        "下限 1 秒；呼吸法来自副本传承与 5 张残页合成。",
        "· 胜负：镜像生灵按副本强度缩放，接入共享逐回合战斗；失败血量降至 1，不发奖。",
        "· 胜利收益：进化花粉 + 修为/血气/灵石 + 进化积淀 + 石罐线索；另有异果、圣药、呼吸法、祖种、"
        "残页与神术机缘，并按 one/two/three 级联概率抽一项额外奖池。",
        "· 石罐：花粉境 11 阶 + 破 6 处 + 线索 9 枚 + 极境「无敌画卷/观想真形」+ 隐患 ≤50，"
        "且全服只此一只。",
        "· 势力：菩提基因 2 阶 / 大梦净土 8 阶 / 阳间第一山 12 阶；入势力一次性礼包 + 每日俸禄。",
        "· 场域每重天让花粉境基础三维增加 3%（九重上限 +27%），场域法·镇压制每重强化 4%。",
        "· 已掌握神术每次攻击按原版顺序独立掷触发概率，每次行动至多触发一种；七妙宝术依七宝数量增伤。",
        "· 记忆命途律法因子逐级保证一/二/三档各一份可交易奖池物品；不可交易与全服唯一物品不进保底池。",
    ])


def help_text() -> str:
    return "\n".join([
        "--- 场域圣墟 · 指令 ---",
        "「#圣墟副本」12 处副本与成本",
        "「#探索圣墟 名称」真身探索｜「#沉迷圣墟 名称*次数」连探（上限 12）",
        "「#法身探索圣墟 位面」「#法身沉迷圣墟 位面*次数」法身侧（见法身指令）",
        "「#圣墟势力」「#加入菩提基因|大梦净土|阳间第一山」「#领取圣墟俸禄」",
        "「#石罐」「#追寻石罐」石罐机缘与认主",
        "「#合成呼吸法 名称」5 张残页合一本",
        "「#神术」已参悟神术与七宝进度",
        "「#场域」「#参悟场域」场域九重天",
        "「#圣墟榜」花粉路榜单",
    ])
