"""时间长河专属战斗规则，按原版 model/timeRiverAdversary.js 迁移。"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Iterable

DARK_TRIAD_NAMES = ("苍帝", "鸿帝", "羽帝")
TIME_RIVER_ATTRIBUTE_RANGE = (1.5, 3.0)
DARK_TRIAD_REVIVAL_LIMIT = 1
DARK_TRIAD_OPENING_SHIELD_RATE = 0.35
DARK_TRIAD_REVIVED_SHIELD_RATE = 0.25
DARK_TRIAD_DAMAGE_REDUCTION = 0.30
CANG_EMPEROR_ATTRIBUTE_RATE = 0.80
CANG_EMPEROR_SUPPRESSION_ACTIONS = 2
TIME_RIVER_PHASE_DURATION = 15 * 60
TIME_RIVER_RESCUE_WINDOW = 10 * 60
TIME_RIVER_HUANG_REWARD = 15
TIME_RIVER_CORPSE_REWARD = 15
TIME_RIVER_FUTURE_REWARD = 45
TIME_RIVER_FUTURE_EVENT_RATE = 0.30
TIME_RIVER_TEACHING_GAIN = 2
TIME_RIVER_TEACHING_MAX = 30
TIME_RIVER_FUTURE_QUASI_NAMES = ("未来准仙帝·甲", "未来准仙帝·乙", "未来准仙帝·丙")
TIME_RIVER_PEAK_SPEED_NAMES = ("荒天帝", "叶天帝", "狠人大帝", "尸骸仙帝")
TIME_RIVER_BASE_SPEED = 1150
TIME_RIVER_PEAK_SPEED = 1250
TIME_RIVER_COUNTER_SKILLS = (
    "他化自在法", "一气化三清", "皆字秘", "临字秘", "数字秘", "组字秘",
    "前字秘", "行字秘", "斗字秘", "者字秘", "兵字秘",
)

# 这些数值和文案来自原版 model/timeRiverAdversary.js 的技能库。
TIME_RIVER_SKILLS = (
    {"name": "祭天祭地祭英灵", "class": "功法", "pr": 0.20, "cnt": -1,
     "beilv": 20, "other": 0, "不可防御": 1,
     "msg1": "祭天、祭地、祭英灵！苍茫古史中无数残魂回应祭礼，黑暗祭光贯穿时间长河！",
     "msg2": "被祭礼之光锁定，道果与肉身同时承受无法回避的二十倍轰击！", "攻击类型": "元神", "稀有度": 10},
    {"name": "鸿帝死咒·泄帝势", "class": "功法", "pr": 0.34, "cnt": -1,
     "beilv": 1, "other": 0, "时间长河效果": "剥落无敌气魄", "时间长河速度": 200,
     "msg1": "鸿帝身后一望无际的古国突兀浮现，死咒言出即法，冥冥天机搅乱乾坤！",
     "msg2": "磅礴无敌的气势被死咒撕开，盖世帝威不断外泄，攻、防与生命同时削减五成！", "攻击类型": "神通", "稀有度": 10},
    {"name": "苍帝无敌拳印", "class": "功法", "pr": 0.24, "cnt": -1,
     "beilv": 12, "other": 0, "不可防御": 1,
     "msg1": "苍帝断喝，灰发披散，宏大的拳意挤碎天宇，万物凋零；拳印打破万古诸天，踏着岁月河流狂暴轰来！",
     "msg2": "无敌气势被泄之际，这一拳正中道果，震得手臂发麻、帝躯踉跄！", "攻击类型": "近战", "稀有度": 10},
    {"name": "祭灭万物", "class": "功法", "pr": 0.10, "cnt": -1,
     "beilv": 25, "other": 0, "不可防御": 1, "控制": 1,
     "msg1": "祭灭万物！苍帝抬手祭尽诸天万象，黑暗火光将古今未来压成一线！",
     "msg2": "被祭灭之力钉死于岁月源头，神魂与肉身同时崩解，复生印记剧烈震荡！", "攻击类型": "元神", "稀有度": 10},
    {"name": "荒无剑诀", "class": "功法", "pr": 0.12, "cnt": -1,
     "beilv": 18, "other": 0, "真意传授": True,
     "msg1": "荒天帝抬手，帝剑真意横贯古今，一剑斩断万古因果！",
     "msg2": "剑光所至，因果、岁月与万法皆被斩开！", "真意上限": TIME_RIVER_TEACHING_MAX, "传授真意每次": TIME_RIVER_TEACHING_GAIN, "攻击类型": "近战", "稀有度": 10},
    {"name": "岁月之钟", "class": "功法", "pr": 0.10, "cnt": -1,
     "beilv": 16, "other": 0, "真意传授": True,
     "msg1": "钟声自道果深处响起，岁月长河被一圈圈涟漪定住！",
     "msg2": "敌手困于自身因果，寿元、神魂与战意一同衰败！", "真意上限": TIME_RIVER_TEACHING_MAX, "传授真意每次": TIME_RIVER_TEACHING_GAIN, "攻击类型": "时间", "稀有度": 10},
    {"name": "仙帝他化自在法", "class": "功法", "pr": 0.01, "cnt": -1,
     "beilv": 22, "other": 0, "真意传授": True,
     "msg1": "荒天帝映照诸世他我，万古时空中走出一道道无上身影！",
     "msg2": "他化自在，化尽诸世法与身，合击之下帝威镇压万古！", "真意上限": TIME_RIVER_TEACHING_MAX, "传授真意每次": TIME_RIVER_TEACHING_GAIN, "攻击类型": "神通", "稀有度": 10},
)

CORPSE_EMPEROR_SKILL_NAMES = (
    "真龙宝术", "真凰宝术", "鲲鹏宝术", "雷帝宝术", "麒麟宝术",
    "天角蚁宝术", "蛄之宝术", "九幽獓宝术", "打神石宝术", "草字剑诀",
    "原始真解终极篇", "平乱诀", "终极帝剑斩杀",
)
CORPSE_EMPEROR_SKILLS = tuple(
    {"name": name, "class": "功法", "pr": 0.16, "cnt": -1,
     "beilv": 4 + index * 0.25, "other": 0,
     "msg1": f"尸骸仙帝抬手演化{name}，十凶符文照亮终极古地！",
     "msg2": "古老宝术贯穿仙帝场域，肉身与元神同时震颤！", "攻击类型": "神通", "稀有度": 10}
    for index, name in enumerate(CORPSE_EMPEROR_SKILL_NAMES[:10])
) + (
    {"name": "原始真解终极篇", "class": "功法", "pr": 0.14, "cnt": -1,
     "beilv": 8, "other": 0,
     "msg1": "尸骸仙帝诵出原始真解终极篇，诸天最本源的符文在掌指间生灭！",
     "msg2": "万法被还原至最初形态，仙帝符文自源头轰入道果！", "攻击类型": "元神", "稀有度": 10},
    {"name": "平乱诀", "class": "功法", "pr": 0.13, "cnt": -1,
     "beilv": 10, "other": 0,
     "msg1": "尸骸仙帝眉心帝光凝剑，平乱诀化作元神剑胎横扫古今！",
     "msg2": "元神剑胎无视岁月阻隔，径直斩向识海与道果！", "攻击类型": "元神", "稀有度": 10},
    {"name": "终极帝剑斩杀", "class": "功法", "pr": 0.12, "cnt": -1,
     "beilv": 15, "other": 0, "不可复活": 1,
     "msg1": "尸骸仙帝拔出大罗剑胎，终极帝剑横断万古诸天！",
     "msg2": "剑光将肉身与元神一并劈开，复生印记随亿万血雨洒落无尽时空！", "攻击类型": "元神", "稀有度": 10},
)

def attack_rows(names: Iterable[str], *, corpse: bool = False) -> list[dict[str, Any]]:
    """Return copied original time-river/corpse skill rows in requested order."""
    rows = {str(row.get("name")): row for row in (*TIME_RIVER_SKILLS, *CORPSE_EMPEROR_SKILLS)}
    # The sacrifice source labels this speed-opening skill 帝威卸甲; its combat row
    # is the pinned original 鸿帝死咒·泄帝势 entry.
    rows["帝威卸甲"] = {**rows["鸿帝死咒·泄帝势"], "name": "帝威卸甲"}
    return [deepcopy(rows[name]) for name in names if name in rows]


PROFILES = {
    "叶天帝": {"id": "ye-tiandi", "counter": False, "era": "后荒古时代"},
    "荒天帝": {"id": "huang-tiandi", "counter": True, "era": "乱古纪元"},
    "苍帝": {"id": "cang-tiandi", "counter": True, "era": "帝落时代", "reinforcements": ("鸿帝", "羽帝")},
    "鸿帝": {"id": "hong-tiandi", "counter": True, "era": "仙古纪元"},
    "羽帝": {"id": "yu-tiandi", "counter": True, "era": "乱古纪元"},
    "尸骸仙帝": {"id": "corpse-immortal-emperor", "counter": True, "era": "终极古地"},
}


def normalize_name(name: Any) -> str:
    if isinstance(name, dict):
        name = name.get("name") or name.get("名号") or ""
    return str(name or "").strip()


def fixed_speed(name: Any) -> int:
    normalized = str(name or "").strip()
    if normalized == "狠人":
        normalized = "狠人大帝"
    return TIME_RIVER_PEAK_SPEED if normalized in TIME_RIVER_PEAK_SPEED_NAMES else TIME_RIVER_BASE_SPEED


def roll_attribute_multiplier(rng: Any) -> float:
    roll = min(1.0, max(0.0, float(rng.random())))
    value = TIME_RIVER_ATTRIBUTE_RANGE[0] + (TIME_RIVER_ATTRIBUTE_RANGE[1] - TIME_RIVER_ATTRIBUTE_RANGE[0]) * roll
    return math.floor(value * 100 + 0.5) / 100


def is_dark_triad_emperor(name: Any) -> bool:
    return normalize_name(name) in DARK_TRIAD_NAMES


def countered_skill(attacker: Any, skill: dict) -> bool:
    """按原版敌方资料标志，判定临字秘反制与反制列表。"""
    tags = getattr(attacker, "tags", {}) or {}
    name = str(skill.get("name") or skill.get("熟练度归属") or "")
    if tags.get("time_river_lin_counter") and "临字秘" in name:
        return True
    if not tags.get("time_river_counter"):
        return False
    return (str(skill.get("class") or "") == "灵根"
            or any(token in name for token in TIME_RIVER_COUNTER_SKILLS))


def apply_counter_opening(fighter: Any, source: str, *, full: bool = False) -> list[str]:
    """Mark a combatant as targeted by a countering adversary's opening field.

    The combat engine suppresses listed cultivation skills when they are attempted,
    matching the original's per-skill counter timing rather than applying upfront damage.
    """
    name = normalize_name(source)
    profile = PROFILES.get(name)
    if not profile or not profile.get("counter"):
        return []
    fighter.tags["time_river_counter"] = True
    fighter.tags["time_river_counter_source"] = name
    fighter.tags["time_river_relic_suppression"] = True
    fighter.tags["time_river_relics_disabled"] = True
    return []


def apply_dark_triad_battle_kit(fighter: Any) -> Any:
    if not is_dark_triad_emperor(getattr(fighter, "name", "")):
        return fighter
    fighter.tags["time_river_dark_triad"] = True
    fighter.effects["shield"] = max(
        int(fighter.effects.get("shield", 0) or 0), int(fighter.hp_max * DARK_TRIAD_OPENING_SHIELD_RATE))
    fighter.effects["time_river_damage_reduction"] = max(
        float(fighter.effects.get("time_river_damage_reduction", 0) or 0), DARK_TRIAD_DAMAGE_REDUCTION)
    fighter.effects["time_river_damage_reduction_turns"] = max(
        int(fighter.effects.get("time_river_damage_reduction_turns", 0) or 0), 6)
    return fighter


def apply_adversary_rules(fighter: Any, name: str | None = None) -> Any:
    """把原版敌人身份、反制和专属功法装入 Fighter。"""
    name = normalize_name(name or getattr(fighter, "name", ""))
    profile = PROFILES.get(name)
    if profile:
        fighter.tags["time_river_profile"] = profile["id"]
        fighter.tags["time_river_counter"] = bool(profile["counter"])
        fighter.tags["time_river_lin_counter"] = True
        fighter.tags["time_river_relic_suppression"] = bool(profile["counter"])
    fighter.speed = fixed_speed(name)
    skills = list(fighter.tags.get("atk_skills") or [])
    learned = set(sk.get("name") for sk in skills)
    additions = []
    if name == "苍帝":
        additions = [sk for sk in TIME_RIVER_SKILLS if sk["name"] != "鸿帝死咒·泄帝势"]
    elif name == "鸿帝":
        additions = [TIME_RIVER_SKILLS[1]]
    elif name == "尸骸仙帝":
        additions = list(CORPSE_EMPEROR_SKILLS)
    for skill in additions:
        if skill["name"] not in learned:
            skills.append(deepcopy(skill))
            learned.add(skill["name"])
    if name == "尸骸仙帝":
        skills.sort(key=lambda skill: skill.get("name") == "终极帝剑斩杀", reverse=True)
    if skills:
        fighter.tags["atk_skills"] = skills
    apply_dark_triad_battle_kit(fighter)
    return fighter


def mark_party_countered(fighters: Iterable[Any], enemies: Iterable[Any]) -> None:
    foes = list(enemies)
    counter = next((enemy for enemy in foes
                    if (getattr(enemy, "tags", {}) or {}).get("time_river_counter")), None)
    lin = counter or next((enemy for enemy in foes
                           if (getattr(enemy, "tags", {}) or {}).get("time_river_lin_counter")), None)
    if not lin and not counter:
        return
    for fighter in fighters:
        tags = getattr(fighter, "tags", None)
        if tags is None:
            continue
        tags["time_river_lin_counter"] = bool(lin)
        tags["time_river_counter"] = bool(counter)
        tags["time_river_relic_suppression"] = bool(counter)
        if counter:
            tags["time_river_counter_source"] = counter.name
            tags["time_river_relics_disabled"] = True


def apply_cang_emperor_opening_suppression(fighter: Any, *, immune: bool = False) -> str | None:
    if immune:
        return f"【神胎不朽】{fighter.name}己道神胎自成一体，苍帝消解精气神的手段毫无作用！"
    if fighter.effects.get("cang_emperor_suppression"):
        return None
    rate = CANG_EMPEROR_ATTRIBUTE_RATE
    fighter.atk = max(1, int(fighter.atk * rate))
    fighter.defense = max(1, int(fighter.defense * rate))
    fighter.hp_max = max(1, int(fighter.hp_max * rate))
    fighter.hp = min(fighter.hp, fighter.hp_max)
    fighter.effects["cang_emperor_suppression"] = {"remaining_actions": CANG_EMPEROR_SUPPRESSION_ACTIONS}
    return f"【苍帝·一念消神】苍帝开场消解精气神，{fighter.name}前两次行动攻击、防御与生命暂降20%！"


def tick_cang_suppression(fighter: Any) -> str | None:
    state = fighter.effects.get("cang_emperor_suppression")
    if not isinstance(state, dict):
        return None
    if int(state.get("remaining_actions", 0) or 0) > 0:
        state["remaining_actions"] -= 1
        return None
    rate = CANG_EMPEROR_ATTRIBUTE_RATE
    fighter.atk = max(1, int(fighter.atk / rate))
    fighter.defense = max(1, int(fighter.defense / rate))
    fighter.hp_max = max(1, int(fighter.hp_max / rate))
    fighter.hp = min(fighter.hp, fighter.hp_max)
    del fighter.effects["cang_emperor_suppression"]
    return f"【精气神复归】{fighter.name}挣脱苍帝压制，攻击、防御与生命恢复！"


def apply_sacrifice_buff(fighter: Any, bonus: float) -> Any:
    bonus = max(0.0, float(bonus or 0))
    if not bonus:
        fighter.hp = fighter.hp_max
        return fighter
    scale = 1.0 + bonus
    fighter.atk = max(1, int(fighter.atk * scale))
    fighter.defense = max(1, int(fighter.defense * scale))
    fighter.hp_max = max(1, int(fighter.hp_max * scale))
    fighter.hp = fighter.hp_max
    fighter.speed = max(1, int(fighter.speed * scale))
    fighter.tags["time_river_ignore_realm_speed"] = True
    return fighter


def teaching_progress(doc: Any, teaching_name: str, gain: int = TIME_RIVER_TEACHING_GAIN) -> tuple[int, bool]:
    """推进原版长河真意；达到30后将功法加入现有 ext gongfa。"""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict) or teaching_name not in {"荒无剑诀", "岁月之钟", "仙帝他化自在法"}:
        return 0, False
    store = ext.setdefault("river_teachings", {})
    current = max(0, int(store.get(teaching_name, 0) or 0))
    next_value = min(TIME_RIVER_TEACHING_MAX, current + max(0, int(gain)))
    store[teaching_name] = next_value
    learned = ext.setdefault("gongfa", [])
    mastered = next_value >= TIME_RIVER_TEACHING_MAX and teaching_name not in learned
    if mastered:
        learned.append(teaching_name)
    return next_value - current, mastered
