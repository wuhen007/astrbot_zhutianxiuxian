"""位面天骄（W7-3）：天机寻踪 / 仇恨 / 共享血条 / 贡献榜 / 污损 / 轮回。

原版依据：
- 踪迹与代价 `apps/User/TianjiLocation.js`（30 亿灵石 / 3000 万源石，24 小时有效）
- 个人冷却 90 分钟、陨落 18 小时轮回、被救走 6 小时、仇恨六档 `apps/Boss/BOSS4.js:172-200`
- 污损：败北 20% 污损一件百分比装备（对应属性 -20%），击杀来源或 5000 万灵石+1000 万源石修复
  `BOSS4.js:1632-1727`；贡献榜按对天骄造成的伤害累计 `BOSS4.js:1373-1400`

本移植：
- 数值按全局 ÷1000 约定缩放（灵石 300 万 / 源石 3 万；修复 5 万灵石 + 1 万源石）
- 天骄共享血条与贡献榜存 db v17 `tianjiao_state` 单例；玩家侧（踪迹 / 仇恨 / CD / 污损）存 doc.ext
- 一处便利：天骄「在世」时任何玩家都能讨伐，但**必须先有有效踪迹**（#打听天机 或 #神识共享）

shortcut（与原版差异）：
- 参悟仿制（12% 生成仿制装备）与 #反哺炼化 未移植 —— 需要装备词条仿制体系，留到 W7-4
- 护体法宝碎毁、道伤压制、岁云/诛仙等权柄加成、帝尊组队线未移植
- 击杀只清自己的仇恨（原版清全服）；护道人改为「天骄回复 15% 气血」而非额外参战单位
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any, Mapping

from .player import PlayerDoc

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

PLANES = ("下界八域", "九天十地", "界海", "仙域", "太初星墟")


# ---------------------------------------------------------------- 仇恨

def hatred_of(doc: Any, name: str) -> int:
    table = doc.ext.get("tianjiao_hatred")
    if not isinstance(table, Mapping):
        return 0
    try:
        return max(0, int(table.get(name, 0) or 0))
    except (TypeError, ValueError):
        return 0


def level_of(value: int) -> tuple[str, float, float]:
    """仇恨值 → (档名, 逃脱概率, 护道人概率)。"""
    v = max(0, int(value))
    picked = (HATRED_LEVELS[0][0], HATRED_LEVELS[0][3], HATRED_LEVELS[0][4])
    for name, lo, _hi, escape, protector in HATRED_LEVELS:
        if v >= lo:
            picked = (name, escape, protector)
    return picked


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


def on_kill(boss: dict, killer: str, now: float) -> None:
    """陨落：清空血条与贡献榜，18 小时轮回，记录击杀者。"""
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
# - 搜魂奖励折为随机上品功法 ×2（原版按 SOUL_SEARCH_PROFILES 取已学表）；
# - 灭杀不给击杀结算（求饶流程外的处决），魔道 +20、灵宝残片 ×8；
# - 反噬固定 20%/25%（原版按境界差浮动）；#天魔炼化天骄 未搬。

OFFER_CHANCE = 0.5
OFFER_HOURS = 24
OFFER_STONES = 5_000             # 赔礼 = 档数 × 5,000
EXEC_SECONDS = 300
EXEC_MODAO_GATE = 1000
SOUL_BACKLASH = 0.20
SLAY_BACKLASH = 0.25
SOUL_GONGFA = ("飞仙诀", "万化圣诀", "不灭天功", "万化仙诀")


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


def accept_offer(doc: PlayerDoc, name: str, now: float) -> tuple[bool, str]:
    """#接受求饶：收赔礼、双方仇恨 -30、天骄免死遁走。"""
    p = _offer_get(doc, name, now)
    if not p:
        return False, f"「{name}」没有向你求饶（或应答已过期）。"
    stones = int(p["bounty"]) * OFFER_STONES
    doc.stones = int(getattr(doc, "stones", 0) or 0) + stones
    reduce_hatred(doc, name, 30)
    doc.ext.pop("tianjiao_offer", None)
    return True, (f"【接受求饶】收下 {stones:,} 灵石赔礼，放其残躯遁走——"
                  f"仇恨 -30（旧怨渐消）。")


def reject_offer(doc: PlayerDoc, name: str, now: float) -> tuple[bool, str]:
    """#拒绝求饶：邪修开 5 分钟执行窗口（搜魂/灭杀）。"""
    p = _offer_get(doc, name, now)
    if not p:
        return False, f"「{name}」没有向你求饶（或应答已过期）。"
    modao = float((getattr(doc, "ext", {}) or {}).get("modao", 0) or 0)
    lg = (getattr(doc, "ext", {}) or {}).get("linggen")
    lg_type = str(lg.get("type") or "") if isinstance(lg, Mapping) else ""
    if modao < EXEC_MODAO_GATE and lg_type not in ("魔头", "天魔"):
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


def soul_search(doc: PlayerDoc, name: str, now: float, rng: random.Random,
                ) -> tuple[bool, str, dict[str, int], bool]:
    """#搜魂天骄：搜功法；反噬 20%（调用方落道伤与气血）。"""
    if not _exec_get(doc, name, now):
        return False, "执行窗口未开或已过（先 #拒绝求饶）。", {}, False
    doc.ext.pop("tianjiao_exec", None)
    if rng.random() < SOUL_BACKLASH:
        return True, "【搜魂天骄】其神魂自爆反噬——你神识重创！", {}, True
    pool = list(SOUL_GONGFA)
    picks = [pool.pop(int(rng.random() * len(pool)) % len(pool)) for _ in range(2)]
    items = {g: 1 for g in picks}
    return True, (f"【搜魂天骄】神魂被翻开——搜得功法："
                  f"{'、'.join(picks)}（已入纳戒）。"), items, False


def slay_tianjiao(doc: PlayerDoc, name: str, now: float, rng: random.Random,
                  ) -> tuple[bool, str, dict[str, int], bool]:
    """#灭杀天骄：彻底抹杀；反噬 25%。魔道 +20、灵宝残片 ×8。"""
    if not _exec_get(doc, name, now):
        return False, "执行窗口未开或已过（先 #拒绝求饶）。", {}, False
    doc.ext.pop("tianjiao_exec", None)
    if rng.random() < SLAY_BACKLASH:
        return True, "【灭杀天骄】临死反扑——两败俱伤！", {}, True
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["modao"] = float(ext.get("modao", 0) or 0) + 20
    return True, "【灭杀天骄】形神俱灭，魔威震世——魔道 +20！", {"灵宝残片": 8}, False
