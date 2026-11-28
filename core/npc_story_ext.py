"""柳神 / 张五爷（对齐原版 apps/User/ExamplePlugin.js 两个交互函数）。

- 柳神：论道 / 交流 / 请教，每日 3 次，好感 → 关系 1~4 级，高关系掉「柳神法残篇」
- 张五爷：交流 / 请教 / 论源，每日 3 次，给源石，高关系掉「源天神觉」「超品源石/神源石」
对齐要点：
1. 修为/血气 = 仙古等级 × 练气等级 × 体质等级 × 基数（原版三元组乘积，已按本地等价等级接入）。
3. 关系等级 min(4, 好感 // 120 + 1)。
shortcut: 原版靠剧情解锁（搬血极境 / 石村、源术事件），本移植用境界门槛近似。
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

DAILY_LIMIT = 3
LIUSHEN = "liushen"
ZHANG = "zhangwuye"
NAMES = {LIUSHEN: "柳神", ZHANG: "张五爷"}
GATES = {LIUSHEN: 10, ZHANG: 20}
REL_UNLOCK = 120

# 动作 → {关系等级: (基数, 好感下限, 好感上限, 掉落概率, 掉落物)}
LIUSHEN_ACTS: dict[str, dict[int, tuple[int, int, int, float, str]]] = {
    "论道": {4: (10000, 15, 24, 0.40, "柳神法残篇"),
             3: (8000, 10, 17, 0.0, ""),
             1: (5000, 5, 9, 0.0, "")},
    "交流": {4: (8000, 12, 19, 0.30, "柳神法残篇"),
             3: (6000, 8, 13, 0.0, ""),
             1: (4000, 5, 8, 0.0, "")},
    "请教": {4: (12000, 18, 29, 0.50, "柳神法残篇"),
             3: (9000, 12, 20, 0.0, ""),
             1: (6000, 7, 11, 0.0, "")},
}
ZHANG_ACTS: dict[str, dict[int, tuple[int, int, int, float, str]]] = {
    "交流": {2: (300000, 8, 13, 0.40, "超品源石"),
             1: (100000, 4, 6, 0.0, "")},
    "请教": {3: (500000, 12, 19, 0.30, "源天神觉"),
             1: (200000, 6, 9, 0.0, "")},
    "论源": {4: (800000, 15, 24, 0.60, "超品神源石"),
             3: (500000, 10, 17, 0.0, ""),
             1: (300000, 7, 11, 0.0, "")},
}
LINES = {
    (LIUSHEN, "论道"): ["你与柳神论及「{topic}」，柳神点拨一二，你获益匪浅。",
                        "你与柳神论及「{topic}」，柳神深入浅出，为你解析大道奥秘。",
                        "你与柳神论及「{topic}」，柳神毫无保留，倾囊相授。"],
    (LIUSHEN, "交流"): ["你与柳神闲谈，柳神给予一些修炼上的建议。",
                        "你与柳神闲谈，柳神讲述上古轶事，你收获良多。",
                        "你与柳神闲谈，柳神谈及历劫与重生，你深感震撼。"],
    (LIUSHEN, "请教"): ["你向柳神请教「{q}」，柳神简要作答。",
                        "你向柳神请教「{q}」，柳神详细讲解。",
                        "你向柳神请教「{q}」，柳神亲自演示相关法门。"],
    (ZHANG, "交流"): ["你与张五爷闲谈，他分享寻源的基本技巧。",
                      "你与张五爷闲谈，他讲述源天师一脉的传奇。"],
    (ZHANG, "请教"): ["你向张五爷请教「{q}」，他简要回答。",
                      "你向张五爷请教「{q}」，他倾囊相授源术精要。"],
    (ZHANG, "论源"): ["你与张五爷论及源术大道，他讲解基础，你有所领悟。",
                      "你与张五爷论及源术大道，他深入讲解精妙之处。",
                      "你与张五爷论及源术大道，他将核心秘传倾囊相授。"],
}
TOPICS = ("天地大道", "肉身极境", "元神修炼", "法则感悟", "上古秘辛", "仙骨纪元", "异域起源", "成仙之路")


def state_of(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get("npc_story_ext") if isinstance(getattr(doc, "ext", None), Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    for key in (LIUSHEN, ZHANG):
        row = st.get(key)
        if not isinstance(row, dict):
            row = {}
        row.setdefault("favor", 0)
        row.setdefault("day", "")
        row.setdefault("count", 0)
        st[key] = row
    return st


def save(doc: Any, st: Mapping[str, Any]) -> Any:
    if isinstance(getattr(doc, "ext", None), dict):
        doc.ext["npc_story_ext"] = dict(st)
    return doc


def relation_level(favor: float) -> int:
    return max(1, min(4, int(float(favor) // REL_UNLOCK) + 1))


def _date_key(ts: float) -> str:
    import time as _t
    return _t.strftime("%Y%m%d", _t.gmtime(ts + 8 * 3600))


def unlocked(doc: Any, who: str) -> bool:
    return int(getattr(doc, "realm_index", 0) or 0) >= GATES.get(who, 0)


def _triple_scale(doc: Any) -> int:
    """原版 xiangulevel_id × level_id × Physique_id：仙古等级 × 练气等级 × 体质等级。"""
    try:
        from . import extra_cultivation as ec
        xiangu = max(1, int(ec.levels_of(doc).get("xiangu", 1) or 1))
    except Exception:
        xiangu = 1
    level = max(1, int(getattr(doc, "realm_index", 0) or 0) + 1)
    physique = max(1, int(getattr(doc, "physique_index", 0) or 0) + 1)
    return xiangu * level * physique


def _tier(level: int, table: Mapping[int, tuple]) -> tuple:
    """取不大于当前关系等级的最高档。"""
    keys = sorted((k for k in table if k <= level), reverse=True)
    return table[keys[0] if keys else min(table)]


def talk(doc: Any, who: str, action: str, question: str, now: float,
         rng: random.Random | None = None
         ) -> tuple[bool, str, dict[str, int], int, dict[str, int]]:
    """→ (ok, msg, 物品收益, 好感增量, 资源收益 {exp/xueqi/yuanshi})。"""
    rng = rng or random
    st = state_of(doc)
    name = NAMES.get(who, who)
    if not unlocked(doc, who):
        return False, f"你尚未获得{name}赏识（需境界 {GATES.get(who, 0)} 以上）。", {}, 0, {}
    table = LIUSHEN_ACTS if who == LIUSHEN else ZHANG_ACTS
    if action not in table:
        return False, f"{name}这里没有「{action}」这种说法。可发：{' / '.join(table)}。", {}, 0, {}
    if action in ("请教",) and not str(question or "").strip():
        return False, "请指明请教的内容，例如：#张五爷请教 源石辨识", {}, 0, {}
    row = st[who]
    day = _date_key(now)
    if row.get("day") != day:
        row["day"] = day
        row["count"] = 0
    if int(row["count"]) >= DAILY_LIMIT:
        return False, f"今日与{name}交流次数已用完（{DAILY_LIMIT}/{DAILY_LIMIT}），明日再来。", {}, 0, {}
    level = relation_level(row["favor"])
    base, lo, hi, drop_rate, drop_item = _tier(level, table[action])
    favor_gain = rng.randint(lo, hi)
    row["favor"] = int(row["favor"]) + favor_gain
    row["count"] = int(row["count"]) + 1
    idx = min(2, max(0, level - 2))
    line = LINES.get((who, action), ["你与{name}交谈。"])[idx]
    line = line.format(topic=rng.choice(TOPICS), q=str(question or "").strip() or "修行")
    gain: dict[str, int] = {}
    if drop_item and rng.random() < drop_rate:
        gain[drop_item] = 1
    amount = int(base) * _triple_scale(doc)
    if who == LIUSHEN:
        res = {"exp": amount, "xueqi": amount}
        tail = f"修为 +{amount:,}，血气 +{amount:,}，好感 +{favor_gain}（{row['favor']}）"
    else:
        res = {"yuanshi": amount}
        tail = f"源石 +{amount:,}，好感 +{favor_gain}（{row['favor']}）"
    if gain:
        tail += "；另得 " + "、".join(f"{k}×{v}" for k, v in gain.items())
    msg = f"{line}\n{tail}"
    return True, msg, gain, favor_gain, res


def progress(doc: Any, who: str) -> tuple[int, str, int, int]:
    """→ (好感, 关系名, 今日已用, 每日上限)。"""
    st = state_of(doc)
    row = st[who]
    from .story_npc import relation_of
    return (int(row["favor"]), relation_of(NAMES[who], row["favor"]),
            int(row["count"]), DAILY_LIMIT)


def panel(doc: Any, now: float) -> str:
    lines = ["【剧情人物·柳神与张五爷】"]
    for who in (LIUSHEN, ZHANG):
        favor, rel, used, limit = progress(doc, who)
        gate = "已结识" if unlocked(doc, who) else f"未结识（需境界 {GATES[who]}）"
        lines.append(f"{NAMES[who]}：{rel}（好感 {favor}）｜今日 {used}/{limit}｜{gate}")
    lines.append("柳神：#柳神论道 / #柳神交流 / #柳神请教 问题")
    lines.append("张五爷：#张五爷交流 / #张五爷请教 问题 / #张五爷论源")
    return "\n".join(lines)


def claim_level_rewards(doc: Any, who: str) -> tuple[bool, str, int, str]:
    """关系等级里程碑补发：每升一级补一份资源，返回 (ok, msg, 数量, 资源类型)。"""
    st = state_of(doc)
    row = st[who]
    if not unlocked(doc, who):
        return False, f"你尚未结识{NAMES[who]}。", 0, ""
    level = relation_level(row["favor"])
    claimed = int(row.get("claimed_level", 1) or 1)
    if level <= claimed:
        return False, f"{NAMES[who]}处没有可补发的奖励（当前关系 {claimed} 级）。", 0, ""
    row["claimed_level"] = level
    scale = _triple_scale(doc)
    if who == LIUSHEN:
        amount = 10000 * scale * (level - claimed)
        return True, (f"【柳神奖励补发】关系提升至 {level} 级，"
                      f"补发修为与血气各 {amount:,}。"), amount, "exp_xueqi"
    amount = 200000 * scale * (level - claimed)
    return True, f"【张五爷奖励补发】关系提升至 {level} 级，补发源石 {amount:,}。", amount, "yuanshi"
