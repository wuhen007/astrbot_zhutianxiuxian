"""位面天骄（W7-3）：天机寻踪 / 仇恨 / 共享血条 / 贡献榜 / 污损 / 轮回。

原版依据：
- 踪迹与代价 `apps/User/TianjiLocation.js`（30 亿灵石 / 3000 万源石，24 小时有效）
- 个人冷却 90 分钟、陨落 18 小时轮回、被救走 6 小时、仇恨六档 `apps/Boss/BOSS4.js:172-200`
- 污损：败北 20% 污损一件百分比装备（对应属性 -20%），击杀来源或 5000 万灵石+1000 万源石修复
  `BOSS4.js:1632-1727`；贡献榜按对天骄造成的伤害累计 `BOSS4.js:1373-1400`

本移植：
- 数值按全局 ÷1000 约定缩放（灵石 300 万 / 源石 3 万；修复 5 万灵石 + 1 万源石）
- 天骄共享血条、贡献榜与轮回运行态存 db v17 `tianjiao_state` 单例；玩家侧（踪迹 / 仇恨 / CD / 污损）存 doc.ext
- 一处便利：天骄「在世」时任何玩家都能讨伐，但**必须先有有效踪迹**（#打听天机 或 #神识共享）

当前移植状态（仍有原版差异）：
- 参悟仿制的 12% 触发、绑定仿制装备掉落与 #反哺炼化已接入；私有仿制卡不进入全服动态装备索引。
- 普通讨伐已接入护体法宝每日三次、盘古奖励/碎宝、诛仙仇恨与避战、击杀时护道人真实接战及终结全服仇恨清理。
- 天骄轮回恢复初始模板、独立天骄起始装备并递增世数/踪迹代数、更新称号。
- 旅行伏击中的护道人接战、救援和轮回已接入。
- 黑皇阵纹区间偏移、道伤完整压制、岁云多项权柄细节及帝尊组队线仍有差异；以上本轮接线未验证。
"""

from __future__ import annotations

import copy
import math
import random
import time
from datetime import datetime
from collections.abc import Callable, Mapping
from typing import Any, Mapping

from .player import PlayerDoc
from . import extra_cultivation, motou, wallet

PERSONAL_CD_SECONDS = 90 * 60
REVIVE_SECONDS = 18 * 3600
ESCAPE_SECONDS = 6 * 3600
TRACE_SECONDS = 24 * 3600
MIN_REALM = 32                      # 原版：练气 32（法身境）方可讨伐
TAINT_CHANCE = 0.2                  # 败北污损概率
PROTECTOR_HEAL = 0.15               # 护道人出场：天骄回复 15% 气血
CONTRIB_TOP_BONUS = (0.30, 0.20, 0.10)   # 贡献榜前三额外赏（占基础赏金比例）

COSTS: dict[str, int] = {"灵石": 3_000_000, "源石": 30_000}
REPAIR_LINGSHI = 50_000
REPAIR_YUANSHI = 10_000

# 原版 HATRED_CONFIG.LEVELS：(档名, 下限, 上限, 逃脱概率, 护道人概率)
HATRED_LEVELS: tuple[tuple[str, int, float, float, float], ...] = (
    ("陌生", 0, 10, 0.10, 0.0),
    ("注意", 11, 30, 0.25, 0.15),
    ("敌视", 31, 60, 0.45, 0.35),
    ("仇恨", 61, 100, 0.65, 0.55),
    ("死敌", 101, 200, 0.80, 0.75),
    ("不死不休", 201, float("inf"), 0.95, 0.90),
)
HATRED_GAIN: dict[str, int] = {"挑战失败": 5, "挑战成功": 20, "击杀": 50, "嘲讽": 3, "护道失败": 30}
PROXY_AMBUSH_CHANCE = {"死敌": 0.20, "不死不休": 0.35}

PLANES = ("下界八域", "九天十地", "界海", "仙域", "太初星墟")
TREASURE_RECOVERY_CHANCE = 0.8


def held_treasures(world: Mapping[str, Any] | None, name: str,
                   valid_treasures: Mapping[str, Any] | None = None) -> list[str]:
    """只从全服唯一 owners 记录读取天骄实际持有的至宝。"""
    owners = world.get("owners", {}) if isinstance(world, Mapping) else {}
    if not isinstance(owners, Mapping) or not str(name or "").strip():
        return []
    owner_uid = f"tianjiao:{name}"
    return [str(treasure) for treasure, owner in owners.items()
            if (isinstance(owner, Mapping) and owner.get("uid") == owner_uid
                and owner.get("name") == name
                and (valid_treasures is None or treasure in valid_treasures))]


def recover_tianjiao_treasure(world: dict[str, Any], name: str, treasure: str,
                              uid: str, player_name: str, now: float) -> bool:
    """归还至宝给真人，仅当唯一归属仍是该天骄时成功。"""
    owners = world.get("owners")
    owner = owners.get(treasure) if isinstance(owners, dict) else None
    if not (isinstance(owner, Mapping) and owner.get("uid") == f"tianjiao:{name}"
            and owner.get("name") == name):
        return False
    owners[treasure] = {"uid": str(uid), "name": str(player_name or uid),
                        "at": float(now), "previous": f"tianjiao:{name}"}
    return True


def release_tianjiao_treasure(world: dict[str, Any], name: str, treasure: str) -> bool:
    """轮回释放至宝，仅清除仍归该天骄的唯一归属。"""
    owners = world.get("owners")
    owner = owners.get(treasure) if isinstance(owners, dict) else None
    if not (isinstance(owner, Mapping) and owner.get("uid") == f"tianjiao:{name}"
            and owner.get("name") == name):
        return False
    del owners[treasure]
    return True


# ---------------------------------------------------------------- 仇恨

def hatred_of(doc: Any, name: str) -> int:
    table = doc.ext.get("tianjiao_hatred")
    if not isinstance(table, Mapping):
        return 0
    try:
        return max(0, int(table.get(name, 0) or 0))
    except (TypeError, ValueError):
        return 0


def roll_independent_escape(rng: Any) -> tuple[float, float, bool]:
    """Original travel rule: roll an independent escape chance, then a separate result."""
    chance = min(1.0, max(0.0, float(rng.random())))
    roll = min(1.0, max(0.0, float(rng.random())))
    return chance, roll, roll < chance


def level_of(value: int) -> tuple[str, float, float]:
    """仇恨值 → (档名, 逃脱概率, 护道人概率)。"""
    v = max(0, int(value))
    picked = (HATRED_LEVELS[0][0], HATRED_LEVELS[0][3], HATRED_LEVELS[0][4])
    for name, lo, _hi, escape, protector in HATRED_LEVELS:
        if v >= lo:
            picked = (name, escape, protector)
    return picked


def select_proxy_ambush(doc: Any, tianjiao_list: list[Mapping], world: Mapping | None,
                        now: float, rng: Any) -> dict | None:
    candidates = []
    bosses = world.get("bosses", {}) if isinstance(world, Mapping) else {}
    bosses = bosses if isinstance(bosses, Mapping) else {}
    for row in tianjiao_list:
        name = str(row.get("name") or row.get("名号") or "").strip()
        if not name:
            continue
        hatred = hatred_of(doc, name)
        level = level_of(hatred)[0]
        if level not in PROXY_AMBUSH_CHANCE:
            continue
        raw_boss = bosses.get(name)
        boss = raw_boss if isinstance(raw_boss, Mapping) else {}
        if blocked_until(boss) > float(now) or hp_pct_of(boss) <= 0:
            continue
        candidates.append({"name": name, "hatred": hatred, "level": level})
    if not candidates:
        return None

    total_weight = sum(candidate["hatred"] for candidate in candidates)
    roll = min(1.0, max(0.0, float(rng.random()))) * total_weight
    selected = candidates[-1]
    for candidate in candidates:
        roll -= candidate["hatred"]
        if roll <= 0:
            selected = candidate
            break
    chance = PROXY_AMBUSH_CHANCE[selected["level"]]
    if min(1.0, max(0.0, float(rng.random()))) >= chance:
        return None
    return {**selected, "chance": chance}


def proxy_plunder(items: Mapping[str, int], item_class_of: Callable[[str], str],
                  rng: Any) -> dict[str, int]:
    rate_basis_points = min(
        6_500, 3_500 + math.floor(min(1.0, max(0.0, float(rng.random()))) * 3_001))
    stolen = {}
    for raw_name, raw_qty in items.items():
        name = str(raw_name or "").strip()
        qty = max(0, int(raw_qty or 0))
        if not name or qty <= 0 or not item_class_of(name):
            continue
        stolen[name] = max(1, min(qty, qty * rate_basis_points // 10_000))
    return stolen


def add_hatred(doc: Any, name: str, reason: str) -> tuple[int, int, str]:
    table = doc.ext.get("tianjiao_hatred")
    table = dict(table) if isinstance(table, Mapping) else {}
    old = max(0, int(table.get(name, 0) or 0))
    gain = HATRED_GAIN.get(reason, 5)
    new = old + gain
    table[name] = new
    doc.ext["tianjiao_hatred"] = table
    return old, new, level_of(new)[0]


def clear_hatred(doc: Any, name: str) -> int:
    table = doc.ext.get("tianjiao_hatred")
    if not isinstance(table, Mapping) or name not in table:
        return 0
    table = dict(table)
    removed = int(table.pop(name, 0) or 0)
    doc.ext["tianjiao_hatred"] = table
    return removed


# ---------------------------------------------------------------- 踪迹

def trace_of(doc: Any, name: str, now: float) -> dict | None:
    table = doc.ext.get("tianjiao_trace")
    if not isinstance(table, Mapping):
        return None
    row = table.get(name)
    if not isinstance(row, Mapping):
        return None
    try:
        if float(row.get("expires", 0) or 0) <= now:
            return None
    except (TypeError, ValueError):
        return None
    return dict(row)


def make_trace(name: str, rng: random.Random, now: float) -> dict:
    return {
        "plane": rng.choice(PLANES),
        "x": rng.randint(-40, 40),
        "y": rng.randint(-40, 40),
        "expires": now + TRACE_SECONDS,
        "source": "天机寻踪",
    }


def set_trace(doc: Any, name: str, trace: Mapping) -> None:
    table = doc.ext.get("tianjiao_trace")
    table = dict(table) if isinstance(table, Mapping) else {}
    table[name] = dict(trace)
    doc.ext["tianjiao_trace"] = table


def format_trace(trace: Mapping) -> str:
    return f"{trace.get('plane', '?')}（{int(trace.get('x', 0))},{int(trace.get('y', 0))}）"


def trace_left(trace: Mapping, now: float) -> int:
    return max(0, int((float(trace.get("expires", 0) or 0) - now) // 60))


# ---------------------------------------------------------------- 个人冷却

def cooldown_left(doc: Any, now: float, cd_mult: float = 1.0) -> int:
    """个人冷却剩余秒数；cd_mult < 1 为道法卡等减免（W7-4）。"""
    try:
        last = float(doc.ext.get("tianjiao_cd") or 0)
    except (TypeError, ValueError):
        last = 0.0
    span = PERSONAL_CD_SECONDS * min(1.0, max(0.1, float(cd_mult)))
    return max(0, int(last + span - now))


def mark_fight(doc: Any, now: float) -> None:
    doc.ext["tianjiao_cd"] = float(now)


# ---------------------------------------------------------------- 世界状态（天骄共享血条）

def world_default() -> dict[str, Any]:
    return {"bosses": {}}


def world_ensure(value: Mapping | None) -> dict[str, Any]:
    state = dict(value or {})
    bosses = state.get("bosses")
    state["bosses"] = dict(bosses) if isinstance(bosses, Mapping) else {}
    return state


def boss_of(state: dict, name: str) -> dict:
    row = state["bosses"].get(name)
    if not isinstance(row, Mapping):
        row = {}
    else:
        row = dict(row)
    row.setdefault("hp_pct", 1.0)
    row.setdefault("alive_until", 0.0)      # 轮回归来时间（>now 表示不在世）
    row.setdefault("escaped_until", 0.0)    # 被护道人救走
    row.setdefault("contrib", {})
    row.setdefault("kills", 0)
    row.setdefault("last_killer", "")
    if not isinstance(row.get("contrib"), Mapping):
        row["contrib"] = {}
    state["bosses"][name] = row
    return row


def blocked_until(boss: Mapping) -> float:
    try:
        return max(float(boss.get("alive_until") or 0), float(boss.get("escaped_until") or 0))
    except (TypeError, ValueError):
        return 0.0


def status_of(boss: Mapping, now: float) -> str:
    until = blocked_until(boss)
    if until <= now:
        return "在世"
    left = int(until - now)
    if float(boss.get("alive_until") or 0) >= float(boss.get("escaped_until") or 0):
        return f"轮回中（{left // 3600} 小时 {left % 3600 // 60} 分后归来）"
    return f"失踪（被护道人救走，{left // 3600} 小时 {left % 3600 // 60} 分后再现）"


def hp_pct_of(boss: Mapping) -> float:
    try:
        return min(1.0, max(0.0, float(boss.get("hp_pct", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def add_contribution(boss: dict, uid: str, damage: int) -> int:
    contrib = dict(boss.get("contrib") or {})
    try:
        total = int(contrib.get(uid, 0) or 0) + max(0, int(damage))
    except (TypeError, ValueError):
        total = max(0, int(damage))
    contrib[uid] = total
    boss["contrib"] = contrib
    return total


def ranking(boss: Mapping, limit: int = 10) -> list[tuple[str, int]]:
    contrib = boss.get("contrib")
    if not isinstance(contrib, Mapping):
        return []
    rows = []
    for uid, value in contrib.items():
        try:
            rows.append((str(uid), int(value or 0)))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows[:limit]


REINCARNATION_TEMPLATE_FIELDS = frozenset({
    "境界", "realm", "level_id", "Physique_id", "mijinglevel_id", "xiangulevel_id",
    "huafenlevel_id", "攻击", "atk", "防御", "defense", "当前血量", "血量上限", "hp",
    "暴击率", "暴击伤害", "速度", "闪避率", "首次闪避", "闪避增攻", "闪避增攻上限",
    "灵根", "学习的功法",
})
REINCARNATION_RESET_FIELDS = (
    "攻击加成", "防御加成", "生命加成", "吞噬本源次数", "吞噬本源记录", "公开踪迹",
)
REINCARNATION_PREFIXES = ("紫微", "星墟", "北斗", "天外", "轮回", "太初", "九霄", "万古")
REINCARNATION_SUFFIXES = ("转世身", "归来者", "道胎", "新生", "轮回子", "再世身")
INDEPENDENT_TIANJIAO_PLANES = frozenset({2.0, 2.5, 7.0})

ESCAPE_TREASURES = {
    "猪咪岁岁": "替身猪偶·九命不灭",
    "金翅小鹏王": "鲲鹏翅·血影遁",
    "华云飞": "一念花开·替身笺",
    "王腾": "乱古帝符·虚空替命",
    "霸王浑战": "霸血焚天·紫血替身",
    "十冠王天子": "世界树枝·替劫叶",
    "鹤无双": "不朽王座·虚影遁",
    "逍遥子": "鲲鹏极速·扶摇遁",
    "武疯子": "七死身·光阴替命",
    "谪仙": "仙古玉笛·祭灵替劫",
    "六冠王宁川": "万灵天图·替命道纹",
    "伊轻舞": "八德宝轮·广寒月影",
    "元古": "元光转生轮·皇血替身",
}
PANGU_TALISMAN_SHATTER_CHANCE = 0.30
TALISMAN_DAILY_LIMIT = 3
TIANJIAO_HEALING_YEARS = 1_000
TIANJIAO_HEALING_RECOVERY = 20


def escape_treasure_name(name: str) -> str:
    return ESCAPE_TREASURES.get(str(name or ""), "神秘保命法宝")


def roll_protective_talisman(status: dict, tianjiao_name: str, now: float, rng: Any) -> dict[str, Any]:
    """Resolve the original once-per-day, three-charge talisman save. Mutates status."""
    if status.get("护身法宝已碎"):
        return {"triggered": False, "reason": "shattered", "chance": 0.0}

    day_key = datetime.fromtimestamp(float(now)).strftime("%Y-%m-%d")
    if status.get("护体法宝触发日") != day_key:
        status["护体法宝触发日"] = day_key
        status["护体法宝当日次数"] = 0
    try:
        used = max(0, int(status.get("护体法宝当日次数", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        used = 0
    if used >= TALISMAN_DAILY_LIMIT:
        return {"triggered": False, "reason": "daily_limit", "chance": 0.0, "used": used}

    try:
        hp_pct = min(100.0, max(0.0, float(status.get("currentHP", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        hp_pct = 0.0
    chance = min(0.65, 0.10 + max(0.0, (50.0 - hp_pct) / 50.0) * 0.55)
    if float(rng.random()) > chance:
        return {"triggered": False, "reason": "roll_failed", "chance": chance, "used": used}

    # The original picks its dialogue before rolling the 10–20 point recovery.
    dialogue_index = min(3, int(float(rng.random()) * 4))
    recovered = 10 + min(10, int(float(rng.random()) * 11))
    new_hp = min(100.0, hp_pct + recovered)
    status["currentHP"] = int(new_hp) if new_hp.is_integer() else new_hp
    status["护体法宝当日次数"] = used + 1
    return {"triggered": True, "reason": "triggered", "chance": chance,
            "recovered": recovered, "current_hp": status["currentHP"],
            "used": used + 1, "dialogue_index": dialogue_index,
            "treasure": escape_treasure_name(tianjiao_name)}


def try_pangu_shatter_talisman(status: dict, active: bool, rng: Any) -> bool:
    """Original 30% Pangu chance to permanently break this life’s escape talisman."""
    if not active or status.get("护身法宝已碎"):
        return False
    if float(rng.random()) >= PANGU_TALISMAN_SHATTER_CHANCE:
        return False
    status["护身法宝已碎"] = True
    return True


def protector_profile(tianjiao_name: str, rng: Any) -> dict[str, Any]:
    """Generate the fixed-original protector combat profile (multiplier 50–100)."""
    multiplier = 50 + min(50, int(float(rng.random()) * 51))
    attack_base = 10_000_000_000 + 1_600_000_000 + 1_500_000_000
    defense_base = 10_000_000_000 + 16_500_000_000 + 150_000_000
    hp_base = 20_000_000_000 + 33_500_000_000 + 150_000_000
    name_map = {
        "猪咪岁岁": "猪家护道老祖·猪惊天",
        "王家老祖·猪百万": "王家太上护道·猪霸天",
        "金翅小鹏王": "鹏族大圣护道·鹏万里",
        "金翅大鹏长老·鹏九霄": "鹏族不朽护道·鹏啸天",
        "华云飞": "云飞护道仙·云中君",
        "星峰太上长老·墨云": "星峰护道尊者·墨无极",
        "王腾": "王家护道圣·王天帝",
        "北原王家长老·王靖海": "北原王家护道·王苍穹",
        "霸王浑战": "霸体护道人·浑天圣祖",
        "霸体祖星长老·苍战": "祖星护道尊者·苍天霸皇",
        "十冠王天子": "十冠王护道圣·世无双",
        "仙古遗地长老·十方": "仙古护道长老·十方禁忌",
        "鹤无双": "鹤族护道仙·鹤凌云",
        "异域不朽客·鹤青冥": "异域护道不朽·鹤破虚",
        "逍遥子": "故友·无涯散仙",
        "武疯子": "武皇一脉大能·黎九霄",
        "谪仙": "仙古遗脉护道者·曲无尘",
        "六冠王宁川": "宁族护道神·宁天图",
        "伊轻舞": "广寒宫太上长老·月寒衣",
        "元古": "元皇湖古圣·元玄",
    }
    hp = hp_base * multiplier
    return {
        "名号": name_map.get(tianjiao_name, f"{tianjiao_name}的护道人"),
        "境界": "护道者", "level_id": 64, "exp": 100_000_000_000 * multiplier,
        "攻击": attack_base * multiplier, "防御": defense_base * multiplier,
        "血量上限": hp, "当前血量": hp, "暴击率": 3.0, "暴击伤害": 3.5,
        "灵根": {"name": "护道灵根", "法球倍率": 1.8},
        "学习的功法": ["护道圣诀", "天罡战气", "不灭金身"],
    }


def register_tianjiao_defeat(tianjiao: dict, status: dict, world_year: float,
                             rng: Any) -> dict[str, Any]:
    """Record every defeat; every third nonlethal defeat can cause the original 1,000-year setback."""
    try:
        defeats = max(0, int(float(status.get("本世败绩", 0) or 0))) + 1
    except (TypeError, ValueError, OverflowError):
        defeats = 1
    status["本世败绩"] = defeats
    try:
        current_hp = float(status.get("currentHP", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        current_hp = 0.0
    if status.get("isHealing") or defeats % 3 != 0 or current_hp <= 0:
        return {"defeats": defeats, "setback": None}

    roll = float(rng.random())
    if defeats <= 3:
        kind = "轻伤" if roll < 0.7 else "道心受创" if roll < 0.95 else "道心破碎"
    elif defeats <= 6:
        kind = "轻伤" if roll < 0.4 else "道心受创" if roll < 0.85 else "道心破碎"
    else:
        kind = "轻伤" if roll < 0.2 else "道心受创" if roll < 0.7 else "道心破碎"
    try:
        year = float(world_year or 0)
    except (TypeError, ValueError, OverflowError):
        year = 0.0
    setback = {"type": kind, "startedAtWorldYear": year,
               "untilWorldYear": year + TIANJIAO_HEALING_YEARS}
    status["养伤"] = setback
    status["isHealing"] = True
    if kind == "道心受创":
        status["下次自强倍率"] = 0.7
    elif kind == "道心破碎":
        status["下次自强倍率"] = 0.5
        status["下次证道阻断"] = True

    lost_growth = None
    if kind == "道心破碎":
        candidates = [field for field in ("攻击加成", "防御加成", "生命加成")
                      if float(tianjiao.get(field, 0) or 0) > 0]
        if candidates:
            index = min(len(candidates) - 1, int(float(rng.random()) * len(candidates)))
            field = candidates[index]
            tianjiao[field] = max(0, math.trunc(float(tianjiao[field]) * 0.9))
            lost_growth = f"{field}因道心崩裂衰退10%"
    try:
        tianjiao["踪迹代数"] = max(0, int(float(tianjiao.get("踪迹代数", 0) or 0))) + 1
    except (TypeError, ValueError, OverflowError):
        tianjiao["踪迹代数"] = 1
    tianjiao.pop("公开踪迹", None)
    return {"defeats": defeats, "setback": {**setback, "lostGrowth": lost_growth}}


def recover_tianjiao_from_setback(status: dict, world_year: float) -> dict[str, Any] | None:
    """Resolve the original healing window and its 20-point recovery."""
    if not status.get("isHealing"):
        return None
    setback = status.get("养伤")
    if not isinstance(setback, Mapping):
        return None
    try:
        year = float(world_year)
        until = float(setback.get("untilWorldYear"))
    except (TypeError, ValueError, OverflowError):
        return None
    if until > year:
        return None
    kind = str(setback.get("type") or "")
    try:
        hp = float(status.get("currentHP", 1) or 1)
    except (TypeError, ValueError, OverflowError):
        hp = 1.0
    status["currentHP"] = min(100.0, max(1.0, hp) + TIANJIAO_HEALING_RECOVERY)
    status["isHealing"] = False
    status.pop("养伤", None)
    return {"type": kind, "currentHP": status["currentHP"]}
STARTER_TIANJIAO_EQUIPMENT = {
    "武器": "烂铁匕首", "护具": "破铜护具", "法宝": "廉价炮仗", "帝兵": "废铁",
}


def is_independent_tianjiao(row: Mapping) -> bool:
    try:
        return float(row.get("位面")) in INDEPENDENT_TIANJIAO_PLANES
    except (TypeError, ValueError, OverflowError):
        return False


def starter_equipment_fallback() -> dict[str, dict[str, Any]]:
    return {
        slot: {"name": name, "class": "装备", "type": slot,
               "atk": 0, "def": 0, "HP": 0, "bao": 0, "全属性": 0}
        for slot, name in STARTER_TIANJIAO_EQUIPMENT.items()
    }


def try_create_imitation(doc: PlayerDoc, boss: dict, tianjiao_name: str,
                         item_lookup: Callable[[str], Mapping | None], now: float,
                         rng: Any) -> dict | None:
    """Let a Tianjiao copy one equipped percentage item after defeating its wearer."""
    profile = boss.get("profile")
    if not isinstance(profile, dict) or profile.get("参悟仿制"):
        return None
    daily = doc.ext.get("tianjiao_imitation_daily")
    daily = dict(daily) if isinstance(daily, Mapping) else {}
    try:
        last = float(daily.get(tianjiao_name, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        last = 0.0
    if last > 0 and float(now) - last < 24 * 3600:
        return None

    candidates: list[tuple[str, str, dict[str, float]]] = []
    equipped = doc.ext.get("equipment")
    equipped = equipped if isinstance(equipped, Mapping) else {}
    for slot in ("武器", "护具", "法宝"):
        raw_name = equipped.get(slot)
        item_name = str(raw_name.get("name") if isinstance(raw_name, Mapping) else raw_name or "").strip()
        item = item_lookup(item_name) if item_name else None
        attrs = item.get("归一属性") if isinstance(item, Mapping) else None
        percentages = attrs.get("百分比") if isinstance(attrs, Mapping) else None
        if not isinstance(percentages, Mapping):
            continue
        copied: dict[str, float] = {}
        for key, value in percentages.items():
            try:
                amount = round(float(value) * 0.6, 4)
            except (TypeError, ValueError, OverflowError):
                continue
            if amount > 0:
                copied[str(key)] = amount
        if copied:
            candidates.append((slot, item_name, copied))
    if not candidates or min(1.0, max(0.0, float(rng.random()))) >= 0.12:
        return None

    index = min(len(candidates) - 1,
                int(min(1.0 - math.ulp(1.0), max(0.0, float(rng.random()))) * len(candidates)))
    slot, source_name, copied = candidates[index]
    imitation = {
        "仿制名": f"仿·{source_name}", "来源装备名": source_name, "槽位": slot,
        "来源QQ": str(doc.uid), "来源名号": str(doc.name or doc.uid),
        "天骄": str(tianjiao_name), "时间": float(now), "词条": copied,
    }
    profile["参悟仿制"] = imitation
    daily[tianjiao_name] = float(now)
    doc.ext["tianjiao_imitation_daily"] = daily
    return copy.deepcopy(imitation)


def refeed_imitation(doc: PlayerDoc, source_name: str, inventory: Mapping[str, Any],
                     item_lookup: Callable[[str], Mapping | None]) -> tuple[bool, str, dict[str, Any]]:
    """Return half of one owned imitation's copied ratios to its equipped source item."""
    source_name = str(source_name or "").strip()
    if not source_name:
        return False, "格式：#反哺炼化 装备名。", {}

    private = doc.ext.get("tianjiao_private_equipment")
    private = private if isinstance(private, dict) else {}
    inventory = inventory if isinstance(inventory, Mapping) else {}
    equipped = doc.ext.get("equipment")
    equipped = equipped if isinstance(equipped, Mapping) else {}
    is_equipped = any(
        str(value.get("name") or "") == source_name if isinstance(value, Mapping)
        else str(value or "") == source_name
        for value in equipped.values()
    )
    if not is_equipped:
        return False, f"请先穿戴本体装备「{source_name}」，才能反哺炼化。", {}

    imitation_name = ""
    imitation: Mapping | None = None
    for name, card in private.items():
        if not isinstance(card, Mapping):
            continue
        data = card.get("参悟仿制")
        if not isinstance(data, Mapping) or str(data.get("来源装备名") or "") != source_name:
            continue
        try:
            count = int(inventory.get(str(name), 0) or 0)
        except (TypeError, ValueError, OverflowError):
            count = 0
        if count > 0:
            imitation_name = str(name)
            imitation = data
            break
    if not imitation:
        return False, f"纳戒中没有「{source_name}」的参悟仿制装备。", {}

    card = item_lookup(source_name)
    if not isinstance(card, Mapping):
        return False, f"找不到本体装备「{source_name}」的属性档案。", {}
    copied = imitation.get("词条")
    if not isinstance(copied, Mapping):
        return False, "仿制装备的词条记录不完整，未消耗物品。", {}
    existing_attr = card.get("归一属性")
    existing_attr = dict(existing_attr) if isinstance(existing_attr, Mapping) else {}
    ratios = existing_attr.get("百分比")
    ratios = dict(ratios) if isinstance(ratios, Mapping) else {}

    returned: dict[str, float] = {}
    for key, value in copied.items():
        try:
            amount = math.floor(float(value) * 0.5 * 10_000 + 0.5) / 10_000
        except (TypeError, ValueError, OverflowError):
            continue
        if amount > 0:
            ratios[str(key)] = float(ratios.get(str(key), 0) or 0) + amount
            returned[str(key)] = amount
    if not returned:
        return False, "仿制词条没有可返还的正向增益，物品未消耗。", {}

    updated = dict(card)
    existing_attr["百分比"] = ratios
    updated["归一属性"] = existing_attr
    private[source_name] = updated
    if int(inventory.get(imitation_name, 0) or 0) <= 1:
        private.pop(imitation_name, None)
    doc.ext["tianjiao_private_equipment"] = private
    rendered = "、".join(f"{key} +{amount:.4f}" for key, amount in returned.items())
    return True, f"【反哺炼化】「{imitation_name}」道韵归还「{source_name}」：{rendered}。", {
        "imitation_name": imitation_name, "returned": returned, "item": updated,
    }


def imitation_item_card(imitation: Mapping, owner_uid: str) -> dict[str, Any]:
    name = str(imitation.get("仿制名") or "仿·参悟装备")
    slot = str(imitation.get("槽位") or "武器")
    stats = imitation.get("词条") if isinstance(imitation.get("词条"), Mapping) else {}
    def value(*keys: str) -> float:
        for key in keys:
            try:
                return max(0.0, float(stats.get(key, 0) or 0))
            except (TypeError, ValueError, OverflowError):
                continue
        return 0.0
    copied = copy.deepcopy(dict(imitation))
    return {
        "name": name, "class": "装备", "type": slot, "品阶": "参悟仿制",
        "参悟仿制": copied, "author_name": str(owner_uid), "绑定者": str(owner_uid),
        "atk": value("atk", "攻击"), "def": value("def", "防御"),
        "HP": value("HP", "血量", "生命"), "bao": 0.0,
        "全属性": value("全属性"), "数量": 1, "islockd": 1,
        "归一属性": {"百分比": copy.deepcopy(dict(stats))},
    }


def _initial_profile(boss: dict, source_row: Mapping) -> dict:
    profile = copy.deepcopy(dict(source_row))
    stored_template = source_row.get("初始模板")
    if isinstance(stored_template, Mapping):
        template = copy.deepcopy(dict(stored_template))
    else:
        template = {key: copy.deepcopy(value) for key, value in source_row.items()
                    if key in REINCARNATION_TEMPLATE_FIELDS}
    boss.setdefault("initial_template", template)
    if "装备" in source_row:
        boss.setdefault("initial_equipment", copy.deepcopy(source_row["装备"]))
    boss["profile"] = profile
    return profile


def runtime_row(source_row: Mapping, boss: dict) -> dict:
    """Return the saved reincarnation profile, initializing legacy boss state once."""
    profile = boss.get("profile")
    if not isinstance(profile, dict):
        profile = _initial_profile(boss, source_row)
    if not isinstance(boss.get("initial_template"), Mapping):
        stored_template = source_row.get("初始模板")
        boss["initial_template"] = (
            copy.deepcopy(dict(stored_template)) if isinstance(stored_template, Mapping)
            else {key: copy.deepcopy(value) for key, value in source_row.items()
                 if key in REINCARNATION_TEMPLATE_FIELDS}
        )
    if "装备" in source_row and "initial_equipment" not in boss:
        boss["initial_equipment"] = copy.deepcopy(source_row["装备"])
    row = copy.deepcopy(profile)
    # The compact Python catalog adds these aliases after adapting legacy JSON rows.
    if "mijinglevel_id" in row:
        try:
            row["realm"] = int(row["mijinglevel_id"])
        except (TypeError, ValueError, OverflowError):
            pass
    if "攻击" in row:
        row["atk"] = row["攻击"]
    if "防御" in row:
        row["defense"] = row["防御"]
    if "血量上限" in row:
        row["hp"] = row["血量上限"]
    return row


def roll_contribution_rewards(boss: Mapping, tianjiao: Mapping, killer_uid: str,
                              rng: Any) -> dict[str, dict[str, int]]:
    """Roll original contribution drops and the killer's 50% bonus drop batch."""
    drops = [item for item in (tianjiao.get("掉落物") or []) if isinstance(item, Mapping)]
    base = [item for item in drops if _drop_probability(item.get("概率")) >= 0.5]
    rare = [item for item in drops if _drop_probability(item.get("概率")) < 0.5]
    ranked = ranking(boss, max(10, len(boss.get("contrib") or {})))
    rewards: dict[str, dict[str, int]] = {}

    def random_index(length: int) -> int:
        value = min(1.0 - math.ulp(1.0), max(0.0, float(rng.random())))
        return min(length - 1, int(value * length))

    def give(uid: str, count: int) -> None:
        if count <= 0:
            return
        got: dict[str, int] = {}
        has_dropped = False
        for _ in range(count):
            pool = rare if float(rng.random()) < 0.7 else base
            if not pool:
                pool = base if base else rare
            if not pool:
                continue
            item = pool[random_index(len(pool))]
            chance = 1.0 if _drop_probability(item.get("概率")) >= 0.5 else _drop_probability(item.get("概率"))
            if float(rng.random()) >= chance:
                continue
            amount = _roll_drop_amount(item, rng)
            name = str(item.get("name") or item.get("名称") or "").strip()
            if name and amount > 0:
                got[name] = got.get(name, 0) + amount
                has_dropped = True
        fallback_pool = base if base else rare
        if not has_dropped and fallback_pool:
            item = fallback_pool[random_index(len(fallback_pool))]
            name = str(item.get("name") or item.get("名称") or "").strip()
            amount = _roll_drop_amount(item, rng)
            if name and amount > 0:
                got[name] = got.get(name, 0) + amount
        if got:
            recipient = rewards.setdefault(str(uid), {})
            for name, amount in got.items():
                recipient[name] = recipient.get(name, 0) + amount

    for index, (uid, _damage) in enumerate(ranked):
        rewards.setdefault(str(uid), {})
        if index == 0:
            count = 3 + random_index(3)
        elif index <= 4:
            count = 2 + random_index(3)
        elif index <= 9:
            count = 1 + random_index(3)
        else:
            count = 1
        give(uid, count)

    if str(killer_uid) and float(rng.random()) < 0.5:
        give(str(killer_uid), 1 + random_index(3))
    return rewards


def _drop_probability(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _roll_drop_amount(item: Mapping, rng: Any) -> int:
    try:
        minimum = max(1, int(item.get("最小数量", item.get("数量", 1)) or 1))
        maximum = max(minimum, int(item.get("最大数量", item.get("数量", minimum)) or minimum))
    except (TypeError, ValueError, OverflowError):
        minimum = maximum = 1
    return minimum + min(
        maximum - minimum,
        int(min(1.0 - math.ulp(1.0), max(0.0, float(rng.random())))
            * (maximum - minimum + 1)),
    )


def on_kill(boss: dict, killer: str, now: float, *, source_row: Mapping | None = None,
            starter_equipment: Mapping | None = None, rng: Any = None) -> None:
    """Reset the Tianjiao to its saved original template and start an 18-hour rebirth."""
    if source_row is not None and not isinstance(boss.get("profile"), dict):
        _initial_profile(boss, source_row)
    profile = boss.get("profile")
    if isinstance(profile, dict):
        template = boss.get("initial_template")
        template = template if isinstance(template, Mapping) else {}
        for field in REINCARNATION_TEMPLATE_FIELDS:
            if field in template:
                profile[field] = copy.deepcopy(template[field])
            else:
                profile.pop(field, None)
        for field in REINCARNATION_RESET_FIELDS:
            profile.pop(field, None)
        if source_row is not None and is_independent_tianjiao(source_row):
            profile["装备"] = copy.deepcopy(dict(starter_equipment or starter_equipment_fallback()))
        elif "initial_equipment" in boss:
            profile["装备"] = copy.deepcopy(boss["initial_equipment"])
        else:
            profile.pop("装备", None)
        try:
            profile["轮回世数"] = max(0, int(float(profile.get("轮回世数", 0) or 0))) + 1
        except (TypeError, ValueError, OverflowError):
            profile["轮回世数"] = 1
        try:
            profile["踪迹代数"] = max(0, int(float(profile.get("踪迹代数", 0) or 0))) + 1
        except (TypeError, ValueError, OverflowError):
            profile["踪迹代数"] = 1
        roller = rng or random
        prefix = REINCARNATION_PREFIXES[min(
            len(REINCARNATION_PREFIXES) - 1,
            int(min(1.0, max(0.0, float(roller.random()))) * len(REINCARNATION_PREFIXES)),
        )]
        suffix = REINCARNATION_SUFFIXES[min(
            len(REINCARNATION_SUFFIXES) - 1,
            int(min(1.0, max(0.0, float(roller.random()))) * len(REINCARNATION_SUFFIXES)),
        )]
        profile["轮回称号"] = prefix + suffix

    boss["hp_pct"] = 1.0
    boss["alive_until"] = now + REVIVE_SECONDS
    boss["escaped_until"] = 0.0
    boss["kills"] = int(boss.get("kills", 0) or 0) + 1
    boss["last_killer"] = str(killer)
    boss["contrib"] = {}


def damage_bonus(doc: Any, boss: Mapping, killer: str) -> float:
    """击杀时按贡献名次给额外赏金比例（第一 30% / 第二 20% / 第三 10%）。"""
    for i, (uid, _dmg) in enumerate(ranking(boss, 3)):
        if uid == str(killer):
            return CONTRIB_TOP_BONUS[i]
    return 0.0


# ---------------------------------------------------------------- 污损

def tainted(doc: Any) -> dict[str, dict]:
    raw = doc.ext.get("tainted")
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, Mapping)}


def is_tainted(doc: Any, slot: str) -> bool:
    return slot in tainted(doc)


def apply_taint(doc: Any, slot: str, source: str, now: float) -> None:
    table = tainted(doc)
    table[slot] = {"by": str(source), "at": float(now)}
    doc.ext["tainted"] = table


def repair(doc: Any, slot: str) -> bool:
    table = tainted(doc)
    if slot not in table:
        return False
    table.pop(slot, None)
    if table:
        doc.ext["tainted"] = table
    else:
        doc.ext.pop("tainted", None)
    return True


def repair_by_source(doc: Any, source: str) -> int:
    n = 0
    for slot, row in list(tainted(doc).items()):
        if str(row.get("by") or "") == str(source):
            if repair(doc, slot):
                n += 1
    return n


def pick_taint_slot(doc: Any, item_lookup, rng: random.Random) -> str | None:
    """随机挑一件「百分比装备」且未污损的槽位；没有可污损目标返回 None。

    与 equipment._split 同口径：0 < 数值 ≤ 1 视为比例加成（百分比装备）。
    """
    slots = []
    for slot, name in (doc.ext.get("equipment") or {}).items():
        if is_tainted(doc, slot):
            continue
        item = item_lookup(name)
        if not item:
            continue
        for key in ("atk", "def", "HP", "全属性"):
            try:
                v = float(item.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if 0 < v <= 1:
                slots.append(str(slot))
                break
    return rng.choice(slots) if slots else None


def fight_text(name: str, hp_pct: float) -> str:
    return f"【{name}】气血 {hp_pct:.0%}"


# ── 天骄处置：求饶 / 处决（W22-F2，对齐原版 BOSS4 求饶-执行流） ────────────
#
# 原版语义：天骄战败时 50% 求饶（赔礼 1~20 万，24h 应答，接受→双方仇恨 -30）；
# 拒绝需邪修（魔道 ≥1000 或魔头/天魔）开 5 分钟执行窗口：
# #搜魂天骄（取 2~3 门功法，反噬自爆按境界差）/ #灭杀天骄 / #天魔炼化天骄。
#
# 本移植（shortcut）：
# - 求饶挂在击杀判定点：触发则天骄免死（气血 1%），24h 应答；
# - 搜魂从天骄实学功法中选取一门，已掌握全部功法时按原版改为炼得元神上限 5%；
# - 灭杀不给击杀结算（求饶流程外的处决），魔道 +20、灵宝残片 ×8；
# - 三种处置共用固定原版境界差自爆算法；搜魂奖励按天骄实学功法或元神补偿处理。

OFFER_CHANCE = 0.5
OFFER_HOURS = 24
OFFER_STONES = 5_000             # 赔礼 = 档数 × 5,000
TRAVEL_OFFER_SECONDS = 10 * 60  # 固定原版 TravelTask 的待答时间
TRAVEL_OFFER_CLASSES = frozenset({"材料", "丹药", "道具", "草药", "食材", "宝石"})
EXEC_SECONDS = 300
EXEC_MODAO_GATE = 1000


def maybe_offer(doc: Any, name: str, boss: dict[str, Any], now: float,
                rng: random.Random) -> tuple[bool, str]:
    """击杀判定点：50% 天骄求饶免死。返回 (是否求饶, 文案)。"""
    if rng.random() >= OFFER_CHANCE:
        return False, ""
    if now - float(boss.get("offered_at", 0) or 0) < OFFER_HOURS * 3600:
        return False, ""
    boss["offered_at"] = now
    bounty = 1 + int(rng.random() * 20)
    doc.ext["tianjiao_offer"] = {"name": name, "bounty": bounty,
                                 "until": now + OFFER_HOURS * 3600}
    return True, (f"「{name}」重伤跪地，道音哀鸣：愿以 {bounty * OFFER_STONES:,} 灵石赎命！\n"
                  f"{OFFER_HOURS} 小时内：#接受求饶 收下赔礼 / "
                  f"#拒绝求饶（邪修可开执行窗口）")


def reduce_hatred(doc: Any, name: str, amount: int) -> int:
    table = doc.ext.get("tianjiao_hatred")
    table = dict(table) if isinstance(table, Mapping) else {}
    old = max(0, int(table.get(name, 0) or 0))
    new = max(0, old - max(0, int(amount)))
    table[name] = new
    doc.ext["tianjiao_hatred"] = table
    return new


def _offer_get(doc: Any, name: str, now: float) -> dict[str, Any] | None:
    p = doc.ext.get("tianjiao_offer")
    if isinstance(p, Mapping) and p.get("name") == name and float(p.get("until", 0) or 0) >= now:
        return dict(p)
    return None


def grant_fight_currency(doc: PlayerDoc, stones: int, source: int) -> None:
    from . import yuanshi

    doc.stones += stones
    account = yuanshi.system_of(doc)
    account["amount"] += source
    doc.ext["yuanshi"] = account


def grant_fight_rewards(doc: PlayerDoc, won: bool, reward_multiplier: int = 1) -> dict[str, int]:
    """Apply original BOSS4's per-fight resources at the port's 1/1000 scale."""
    multiplier = max(1, int(reward_multiplier)) if won else 1
    stones = (15_000 if won else 3_000) * multiplier
    source = (5_000 if won else 1_000) * multiplier
    track_sum = sum(extra_cultivation.levels_of(doc).values()) - 1
    qi = max(1, int(doc.realm_index) + 1)
    body = max(1, int(doc.physique_index) + 1)
    coefficient = 10_000 if won else 10
    experience = track_sum * qi * body * coefficient * multiplier // 1_000
    grant_fight_currency(doc, stones, source)
    doc.exp += experience
    wallet.set_xueqi(doc, wallet.xueqi(doc) + experience)
    return {"stones": stones, "source": source, "exp": experience, "xueqi": experience}


def roll_tianjiao_drops(tianjiao: Mapping, rng: Any, *, drop_key: str = "掉落物",
                        multiplier: int = 1) -> dict[str, int]:
    """Roll each normal or special entry once, then multiply the resulting quantity."""
    result: dict[str, int] = {}
    drops = tianjiao.get(drop_key)
    if not isinstance(drops, (list, tuple)):
        return result
    multiplier = max(1, int(multiplier))
    for item in drops:
        if not isinstance(item, Mapping) or _drop_probability(rng.random()) >= _drop_probability(item.get("概率")):
            continue
        name = str(item.get("name") or item.get("名称") or "").strip()
        if name:
            result[name] = result.get(name, 0) + _roll_drop_amount(item, rng) * multiplier
    return result


def roll_travel_rejection_drops(tianjiao: Mapping, rng: Any) -> dict[str, int]:
    """A refused ambush mercy that ends in a kill pays both drop tables."""
    result = roll_tianjiao_drops(tianjiao, rng)
    for name, amount in roll_tianjiao_drops(tianjiao, rng, drop_key="特殊掉落").items():
        result[name] = result.get(name, 0) + amount
    return result


def build_travel_ambush_offer(doc: PlayerDoc, name: str, tianjiao: Mapping,
                              reward_pool: list[Mapping], now: float,
                              rng: random.Random) -> tuple[bool, str]:
    """固定原版 TravelTask 胜利赔礼：天骄掉落 + 5 份不同的常规物品，10 分钟待答。"""
    current = doc.ext.get("tianjiao_offer")
    if isinstance(current, Mapping):
        try:
            if float(current.get("until") or 0) > float(now):
                return False, "已有一份天骄求饶待答，请先处理后再继续。"
        except (TypeError, ValueError):
            pass

    def probability(value: Any) -> float:
        try:
            return min(1.0, max(0.0, float(value or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0.0

    def roll_amount(item: Mapping, cap: int | None = None) -> int:
        try:
            minimum = max(1, int(item.get("最小数量", item.get("数量", 1)) or 1))
            maximum = max(minimum, int(item.get("最大数量", item.get("数量", minimum)) or minimum))
        except (TypeError, ValueError, OverflowError):
            minimum = maximum = 1
        amount = minimum + min(maximum - minimum, int(probability(rng.random()) * (maximum - minimum + 1)))
        return max(1, min(int(cap), amount)) if cap is not None else max(1, amount)

    drops = [item for item in (tianjiao.get("掉落物") or []) if isinstance(item, Mapping)]
    normal = []
    for item in drops:
        if probability(rng.random()) < probability(item.get("概率")):
            normal.append({
                "name": str(item.get("name") or "").strip(),
                "class": str(item.get("class") or "").strip(),
                "amount": roll_amount(item, 20),
                "rarity": max(0, int(item.get("稀有度", 0) or 0)),
            })
    if not normal and drops:
        fallback = max(drops, key=lambda item: probability(item.get("概率")))
        normal.append({
            "name": str(fallback.get("name") or "").strip(),
            "class": str(fallback.get("class") or "").strip(),
            "amount": roll_amount(fallback, 20),
            "rarity": max(0, int(fallback.get("稀有度", 0) or 0)),
        })
    normal = [item for item in normal if item["name"]]
    used_names = {item["name"] for item in normal}
    pool = []
    for item in reward_pool:
        if not isinstance(item, Mapping):
            continue
        item_name = str(item.get("name") or "").strip()
        item_class = str(item.get("class") or "").strip()
        try:
            rarity = int(item.get("稀有度", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if item_name and item_class in TRAVEL_OFFER_CLASSES and 1 <= rarity <= 5:
            pool.append({"name": item_name, "class": item_class, "rarity": rarity})

    available = [item for item in pool if item["name"] not in used_names]
    extras = []
    while len(extras) < 5 and available:
        index = min(len(available) - 1, int(probability(rng.random()) * len(available)))
        item = available.pop(index)
        if item["name"] in used_names:
            continue
        used_names.add(item["name"])
        max_amount = 1 if item["class"] == "装备" else max(1, (6 - item["rarity"]) * 4)
        amount = 1 + min(max_amount - 1, int(probability(rng.random()) * max_amount))
        extras.append({**item, "amount": amount})

    item_counts: dict[str, int] = {}
    for item in (*normal, *extras):
        item_counts[item["name"]] = item_counts.get(item["name"], 0) + int(item["amount"])
    offer = {
        "name": str(name), "source": "travel_ambush", "bounty": 0,
        "items": item_counts, "normal": normal, "extras": extras,
        "until": float(now) + TRAVEL_OFFER_SECONDS,
    }
    doc.ext["tianjiao_offer"] = offer
    normal_text = "、".join(f"{item['name']}×{item['amount']}" for item in normal) or "无"
    extras_text = "、".join(f"{item['name']}×{item['amount']}（稀有度{item['rarity']}）"
                            for item in extras) or "无可用赔礼物品"
    return True, (f"【天骄败退·献宝求饶】{name}交出战利品与五份赔礼。\n"
                  f"本命战利品：{normal_text}\n赔礼：{extras_text}\n"
                  f"10 分钟内发送「#接受求饶 {name}」收下并放其离去，"
                  "或发送「#拒绝求饶 {name}」继续追杀。")


def accept_offer_with_rewards(doc: PlayerDoc, name: str, now: float
                              ) -> tuple[bool, str, dict[str, int]]:
    """#接受求饶：兼容旧灵石赔礼，并返回旅行伏击的物品赔礼供事务发放。"""
    p = _offer_get(doc, name, now)
    if not p:
        return False, f"「{name}」没有向你求饶（或应答已过期）。", {}
    stones = max(0, int(p.get("bounty") or 0)) * OFFER_STONES
    doc.stones = int(getattr(doc, "stones", 0) or 0) + stones
    raw_items = p.get("items")
    items = ({str(k): max(0, int(v or 0)) for k, v in raw_items.items()}
             if isinstance(raw_items, Mapping) else {})
    items = {k: v for k, v in items.items() if k and v > 0}
    reduce_hatred(doc, name, 30)
    doc.ext.pop("tianjiao_offer", None)
    reward_text = "、".join(f"{item}×{qty}" for item, qty in items.items())
    parts = []
    if stones:
        parts.append(f"灵石 {stones:,}")
    if reward_text:
        parts.append(reward_text)
    detail = "、".join(parts) or "赔礼"
    return True, f"【接受求饶】收下{detail}，放其残躯遁走——仇恨 -30（旧怨渐消）。", items


def accept_offer(doc: PlayerDoc, name: str, now: float) -> tuple[bool, str]:
    ok, message, _items = accept_offer_with_rewards(doc, name, now)
    return ok, message


def can_execute_surrender(doc: PlayerDoc) -> bool:
    ext = getattr(doc, "ext", {}) or {}
    try:
        modao = float(ext.get("modao", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        modao = 0.0
    lg = ext.get("linggen")
    lg_type = str(lg.get("type") or "") if isinstance(lg, Mapping) else ""
    return modao >= EXEC_MODAO_GATE or lg_type in ("魔头", "天魔")


def take_travel_ambush_offer(doc: PlayerDoc, name: str, now: float) -> dict[str, Any] | None:
    """Consume a live travel-ambush offer when a non-evil player refuses mercy."""
    offer = _offer_get(doc, name, now)
    if not offer or offer.get("source") != "travel_ambush":
        return None
    doc.ext.pop("tianjiao_offer", None)
    return offer


def reject_offer(doc: PlayerDoc, name: str, now: float) -> tuple[bool, str]:
    """#拒绝求饶：邪修开 5 分钟执行窗口（搜魂/灭杀）。"""
    p = _offer_get(doc, name, now)
    if not p:
        return False, f"「{name}」没有向你求饶（或应答已过期）。"
    if not can_execute_surrender(doc):
        return False, ("你心存善念（魔道不足 1000 且非魔道之身）——下不去手，"
                       "只能 #接受求饶。")
    doc.ext["tianjiao_exec"] = {"name": name, "until": now + EXEC_SECONDS}
    doc.ext.pop("tianjiao_offer", None)
    return True, (f"【拒绝求饶】杀意凛然——{EXEC_SECONDS // 60} 分钟执行窗口开启："
                  "#搜魂天骄 / #灭杀天骄 择一而行。")


def _exec_get(doc: Any, name: str, now: float) -> bool:
    e = doc.ext.get("tianjiao_exec")
    return (isinstance(e, Mapping) and e.get("name") == name
            and float(e.get("until", 0) or 0) >= now)


def _realm_score(entity: Any, player: bool = False) -> int:
    if player:
        tracks = extra_cultivation.levels_of(entity)
        return (max(0, int(getattr(entity, "realm_index", 0) or 0)) + 1
                + max(0, int(getattr(entity, "physique_index", 0) or 0)) + 1
                + 3 * sum(max(0, int(tracks.get(track, 0) or 0))
                          for track in ("mijing", "xiangu", "huafen")))
    row = entity if isinstance(entity, Mapping) else {}
    realm = max(0, int(row.get("mijinglevel_id", row.get("realm", 0)) or 0))
    return (max(0, int(row.get("level_id", 0) or 0))
            + max(0, int(row.get("Physique_id", 0) or 0))
            + 3 * (realm
                   + max(0, int(row.get("xiangulevel_id", 0) or 0))
                   + max(0, int(row.get("huafenlevel_id", 0) or 0))))


def _resolve_soul_backlash(doc: PlayerDoc, target: Mapping[str, Any], rng: Any) -> dict[str, Any]:
    gap = _realm_score(target) - _realm_score(doc, player=True)
    chance = min(0.8, max(0.08, 0.18 + gap * 0.012))
    if min(1.0, max(0.0, float(rng.random()))) >= chance:
        return {"gap": gap, "chance": chance, "self_destructed": False}

    ext = doc.ext if isinstance(doc.ext, dict) else {}
    severity = min(0.85, max(0.2, 0.35 + gap * 0.01))
    hp_max = max(1, int(float(ext.get("hp_max", 0) or ext.get("hp", 1) or 1)))
    spirit_max = max(1, int(float(ext.get("yuanshen_max", 0)
                                 or ext.get("yuanshen", 0) or hp_max * 0.2)))
    hp = max(1, int(float(ext.get("hp", 0) or hp_max)))
    spirit = max(0, int(float(ext.get("yuanshen", 0) or spirit_max)))
    body_damage = max(1, int(hp_max * severity))
    spirit_damage = max(1, int(spirit_max * severity))
    dao_injury = 3 if gap >= 20 else 2 if gap >= 5 else 1
    ext["hp"] = max(1, hp - body_damage)
    ext["yuanshen"] = max(0, spirit - spirit_damage)
    return {"gap": gap, "chance": chance, "self_destructed": True,
            "severity": severity, "body_damage": body_damage,
            "soul_damage": spirit_damage, "dao_injury": dao_injury}


def _execution_gate(doc: PlayerDoc, evil: Mapping[str, Any], name: str,
                    target: Mapping[str, Any], now: float) -> str:
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    root = ext.get("linggen") if isinstance(ext.get("linggen"), Mapping) else {}
    modao = float(evil.get("modao", ext.get("modao", 0)) or 0)
    if modao < EXEC_MODAO_GATE and str(root.get("type") or "") not in ("魔头", "天魔"):
        return "你的魔道修为不足以施展这种处置。"
    if not _exec_get(doc, name, now):
        return "执行窗口未开或已过（先 #拒绝求饶）。"
    if not str(target.get("name") or target.get("名号") or "").strip():
        return "目标天骄资料不完整，无法处置。"
    return ""


def refine_tianjiao(doc: PlayerDoc, evil: dict[str, Any], name: str,
                    target: Mapping[str, Any], now: float, rng: Any,
                    ) -> tuple[bool, str, dict[str, Any]]:
    """炼化已镇压天骄；与搜魂/灭杀共用固定原版境界差反噬。"""
    gate = _execution_gate(doc, evil, name, target, now)
    if gate:
        return False, gate, {}

    details = _resolve_soul_backlash(doc, target, rng)
    doc.ext.pop("tianjiao_exec", None)
    if details["self_destructed"]:
        return True, (f"【神魂自爆·天魔炼化反噬】{name}宁愿自毁真灵，也不肯让你得到其道果。"
                      f"肉身受创 {details['body_damage']:,}，元神受创 {details['soul_damage']:,}，"
                      f"道伤 +{details['dao_injury']}。"), details

    modao = float(evil.get("modao", doc.ext.get("modao", 0)) or 0)
    cultivation = max(1, int(float(doc.exp or 0) * 0.05))
    vitality = max(1, int(float(wallet.xueqi(doc)) * 0.05))
    doc.exp = int(doc.exp or 0) + cultivation
    wallet.set_xueqi(doc, wallet.xueqi(doc) + vitality)
    evil["modao"] = modao + 80
    absorbed, absorb_msg, evolved = motou.absorb_tuntian_source(
        evil, doc, "天骄本源", name, now)
    details.update({"cultivation": cultivation, "vitality": vitality,
                    "modao": evil["modao"], "tuntian": absorb_msg if absorbed else "",
                    "evolved": evolved})
    message = (f"【天魔炼化】炼得修为 +{cultivation:,}、血气 +{vitality:,}、"
               f"魔道值 +80。")
    if absorbed:
        message += f"\n【吞天本源】{absorb_msg}{'，体质蜕变为【混沌体】！' if evolved else ''}"
    return True, message, details

def soul_search(doc: PlayerDoc, name: str, target: Mapping[str, Any], now: float,
                rng: random.Random,
                ) -> tuple[bool, str, dict[str, int], dict[str, Any]]:
    """#搜魂天骄：需搜魂大法；境界差自爆，成功学习目标功法或炼得元神。"""
    gate = _execution_gate(doc, {}, name, target, now)
    if gate:
        return False, gate, {}, {}
    learned = doc.ext.get("gongfa", ()) if isinstance(doc.ext, Mapping) else ()
    if "搜魂大法" not in learned:
        return False, "你尚未掌握【搜魂大法】。", {}, {}
    backlash = _resolve_soul_backlash(doc, target, rng)
    doc.ext.pop("tianjiao_exec", None)
    if backlash["self_destructed"]:
        return True, (f"【搜魂反噬·神魂自爆】{name}宁死也不肯吐露秘密。"
                      f"肉身受创 {backlash['body_damage']:,}，元神受创 {backlash['soul_damage']:,}，"
                      f"道伤 +{backlash['dao_injury']}。"), {}, backlash

    techniques = target.get("学习的功法") or target.get("gongfa") or target.get("skills") or ()
    known = set(learned or ())
    available = [str(item) for item in techniques if str(item) and str(item) not in known]
    if available:
        technique = available[min(len(available) - 1, int(rng.random() * len(available)))]
        doc.ext.setdefault("gongfa", []).append(technique)
        return True, f"【搜魂天骄】搜得功法记忆：【{technique}】。", {}, backlash

    spirit_max = max(1, int(float(doc.ext.get("yuanshen_max", 0)
                               or doc.ext.get("yuanshen", 0) or 100)))
    spirit_gain = max(1, int(spirit_max * 0.05))
    doc.ext["yuanshen"] = max(0, int(float(doc.ext.get("yuanshen", 0) or 0))) + spirit_gain
    return True, f"【搜魂天骄】其功法皆已掌握，转而炼得元神 +{spirit_gain:,}。", {}, backlash

def slay_tianjiao(doc: PlayerDoc, evil: dict[str, Any], name: str,
                  target: Mapping[str, Any], now: float, rng: random.Random,
                  ) -> tuple[bool, str, dict[str, int], dict[str, Any]]:
    """#灭杀天骄：共用原版境界差反噬；存活时魔道 +20、灵宝残片 ×8。"""
    gate = _execution_gate(doc, evil, name, target, now)
    if gate:
        return False, gate, {}, {}
    backlash = _resolve_soul_backlash(doc, target, rng)
    doc.ext.pop("tianjiao_exec", None)
    if backlash["self_destructed"]:
        return True, (f"【灭杀反噬·神魂自爆】{name}临死反扑，与你两败俱伤。"
                      f"肉身受创 {backlash['body_damage']:,}，元神受创 {backlash['soul_damage']:,}，"
                      f"道伤 +{backlash['dao_injury']}。"), {}, backlash
    modao = float(evil.get("modao", doc.ext.get("modao", 0)) or 0) + 20
    evil["modao"] = modao
    doc.ext["modao"] = modao
    return True, "【灭杀天骄】形神俱灭，魔威震世——魔道 +20！", {"灵宝残片": 8}, backlash
