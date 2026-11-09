"""人傀 / 外来道果（W8-F6，对齐原版 apps/motou/ForbiddenSoul.js + model/forbiddenSoul.js）。

复用 B5 魔头禁术的 ``ext["evil"]`` 单对象，不新增 ext 键、不升 db。
原版 14 条 rule 中与本批相关的 8 条：炼制人傀 / 我的人傀 / 驱使人傀 / 修复人傀 /
毁去人傀 / 炼化道果 / 熔去外来道果 / 闭关化杂。

三处折算（原版机制在本移植无底座）：
1. 人傀是「下一场主动单人战斗的额外战体」（redis summon 队列 + buildForbiddenCompanion），
   本移植战斗引擎无伙伴位 → 折算为 6 小时三维 +10% 的出战窗口。
2. 原版耐久只有减数检查、全仓无扣减点（死链）→ 本移植每次驱使扣 20 耐久。
3. 原版「夺果」需目标有「自身之道类型/名称」，本移植无该体系 → 折算为境界 ≥40。
   原版闭关化杂占全局 action 锁，本移植无全局行动队列 → 只做本模块互斥。
"""

from __future__ import annotations

import time
from typing import Mapping

CRAFT_ITEMS = {"阴魂木": 3, "神魂结晶": 1}
CRAFT_STONES = 50_000_000
REPAIR_ITEMS = {"阴魂木": 1}
REPAIR_STONES = 10_000_000
REPAIR_GAIN = 40

DURABILITY_MAX = 100
SUMMON_MIN_DURABILITY = 20
SUMMON_DURABILITY_COST = 20
SUMMON_SECONDS = 6 * 3600
PUPPET_BONUS = 0.10

FRUIT_BONUS = 0.03
CRACK_PENALTY = -0.05
CRACK_SECONDS = 6 * 3600
IMPURITY_CAP = 60
IMPURITY_PER_REFINE = 15
MELT_REDUCE = 10
RETREAT_REDUCE = 30
RETREAT_SECONDS = 6 * 3600

MIN_TARGET_REALM = 40       # 夺果门槛，复用 motou.GUO_MIN_REALM
SNAPSHOT_RATIO = 0.30       # 遗蜕 → 人傀三维折算（原版 craftHumanPuppet ×0.3）


def state_of(s: dict) -> dict:
    """补齐人傀链字段。s 由 motou.state_of 深拷贝而来，故可就地写。"""
    s.setdefault("puppet", None)
    s.setdefault("puppet_day", "")
    s.setdefault("puppet_until", 0.0)
    s.setdefault("foreign_fruit", None)
    s.setdefault("impurity", 0)
    s.setdefault("crack_until", 0.0)
    s.setdefault("retreat_until", 0.0)
    return s


def day_key(now: float) -> str:
    """原版 getChinaDateKey：UTC+8 自然日，用于每日一次出战。"""
    return time.strftime("%Y-%m-%d", time.gmtime(float(now) + 8 * 3600))


def tick(s: dict, now: float) -> tuple[bool, str]:
    """惰性结算到期闭关（原版 cron 化杂到期 -30）与过期裂痕。"""
    changed = False
    msg = ""
    if float(s.get("retreat_until", 0) or 0) and float(s["retreat_until"]) <= now:
        before = int(s.get("impurity", 0))
        s["impurity"] = max(0, before - RETREAT_REDUCE)
        s["retreat_until"] = 0.0
        changed = True
        msg = f"闭关化杂已满 6 小时：道果杂质 {before} → {s['impurity']}。"
    if float(s.get("crack_until", 0) or 0) and float(s["crack_until"]) <= now:
        s["crack_until"] = 0.0
        changed = True
    return changed, msg


def cost_gap(stones: int, inv: Mapping, items: Mapping[str, int], stones_cost: int) -> str:
    """返回缺口文案；空串表示付得起。实际扣除由 main 在事务里做。"""
    for name, qty in items.items():
        have = int((inv or {}).get(name, 0) or 0)
        if have < qty:
            return f"还需 {name}×{qty}（现有 {have}）。"
    if int(stones) < stones_cost:
        return f"还需灵石 {stones_cost:,}（现有 {int(stones):,}）。"
    return ""


def craft(s: dict, now: float, owner_stats: Mapping | None = None) -> tuple[bool, str]:
    """消耗待炼遗蜕成傀。旧档遗蜕无快照时退回主人三维 ×0.3。"""
    r = s.get("remains")
    if not r:
        return False, "没有可供炼制的待炼遗蜕（「#处置 灭魂」可得）。"
    if s.get("puppet"):
        return False, "你已持有一尊人傀；如需重炼请先「#毁去人傀 确认」。"
    src = owner_stats or {}
    atk = int(r.get("atk", src.get("atk", 0)) or 0)
    defense = int(r.get("def", src.get("defense", 0)) or 0)
    hp = int(r.get("hp", src.get("hp", 0)) or 0)
    # 原版 buildForbiddenCompanion：出战属性不得超过主人对应属性 35%
    def cap(v: int, own: int) -> int:
        val = int(v * SNAPSHOT_RATIO)
        return min(val, int(own * 0.35)) if own else val

    s["puppet"] = {
        "name": str(r.get("name") or "无名修士"),
        "root": str(r.get("root") or "无"),
        "gongfa": str(r.get("gongfa") or "无"),
        "atk": max(1, cap(atk, int(src.get("atk", 0) or 0))),
        "def": max(0, cap(defense, int(src.get("defense", 0) or 0))),
        "hp": max(1, cap(hp, int(src.get("hp", 0) or 0))),
        "durability": DURABILITY_MAX,
        "crafted_at": float(now),
    }
    s["remains"] = None
    p = s["puppet"]
    return True, (f"【人傀炼成】{p['name']} 的遗蜕化作人傀，耐久 {DURABILITY_MAX}。"
                  f"三维 {p['atk']:,}/{p['def']:,}/{p['hp']:,}（遗蜕 ×30%，不超主人 35%）。")


def repair(s: dict) -> tuple[bool, str]:
    p = s.get("puppet")
    if not p:
        return False, "你尚未炼制人傀（「#炼制人傀」）。"
    before = min(DURABILITY_MAX, max(0, int(p.get("durability", 0))))
    if before >= DURABILITY_MAX:
        return False, "人傀耐久已满，无需修复。"
    p["durability"] = min(DURABILITY_MAX, before + REPAIR_GAIN)
    return True, f"人傀耐久由 {before} 恢复至 {p['durability']}（+{REPAIR_GAIN}）。"


def destroy(s: dict) -> tuple[bool, str]:
    p = s.get("puppet")
    if not p:
        return False, "你尚未炼制人傀。"
    name = str(p.get("name") or "无名修士")
    s["puppet"] = None
    s["puppet_until"] = 0.0
    s["puppet_day"] = ""
    return True, f"人傀【{name}】已被彻底毁去，材料不返还。"


def summon(s: dict, now: float) -> tuple[bool, str]:
    p = s.get("puppet")
    if not p:
        return False, "你尚未炼制人傀（「#炼制人傀」）。"
    if int(p.get("durability", 0)) < SUMMON_MIN_DURABILITY:
        return False, f"人傀耐久不足 {SUMMON_MIN_DURABILITY}，需先「#修复人傀」。"
    key = day_key(now)
    if s.get("puppet_day") == key:
        return False, "人傀今日已经出战过，明日再来。"
    if float(s.get("puppet_until", 0) or 0) > now:
        return False, "人傀已收入战阵，无需重复驱使。"
    p["durability"] = max(0, int(p["durability"]) - SUMMON_DURABILITY_COST)
    s["puppet_day"] = key
    s["puppet_until"] = float(now) + SUMMON_SECONDS
    return True, (f"【{p['name']}·人傀】收入战阵：6 小时内三维 +{PUPPET_BONUS:.0%}，"
                  f"耐久 -{SUMMON_DURABILITY_COST} → {p['durability']}。")


def refine(s: dict, now: float) -> tuple[bool, str]:
    g = s.get("guo")
    if not g:
        return False, "没有待炼道果（「#处置 夺果」可得，目标需境界 ≥40）。"
    if s.get("foreign_fruit"):
        return False, "外来道果槽已有道果，请先「#熔去外来道果」。"
    if int(s.get("impurity", 0)) >= IMPURITY_CAP:
        return False, f"道果杂质已达 {IMPURITY_CAP}，须先「#闭关化杂」。"
    s["foreign_fruit"] = {
        "name": str(g.get("name") or "无名道果"),
        "way": str(g.get("way") or "自身之道"),
        "bonus": FRUIT_BONUS,
        "refined_at": float(now),
    }
    s["guo"] = None
    s["impurity"] = int(s.get("impurity", 0)) + IMPURITY_PER_REFINE
    return True, (f"【{s['foreign_fruit']['name']}】已炼入外来道果槽：全属性 +{FRUIT_BONUS:.0%}，"
                  f"道果杂质 {s['impurity']}/{IMPURITY_CAP}。")


def melt(s: dict) -> tuple[bool, str]:
    if not s.get("foreign_fruit"):
        return False, "外来道果槽为空。"
    s["foreign_fruit"] = None
    s["impurity"] = max(0, int(s.get("impurity", 0)) - MELT_REDUCE)
    return True, f"外来道果已熔去，道果杂质 -{MELT_REDUCE} → {s['impurity']}/{IMPURITY_CAP}。"


def retreat(s: dict, now: float) -> tuple[bool, str]:
    if int(s.get("impurity", 0)) <= 0:
        return False, "体内没有需要化解的道果杂质。"
    if float(s.get("retreat_until", 0) or 0) > now:
        left = int((float(s["retreat_until"]) - now) / 60) + 1
        return False, f"你已经在闭关化杂（约 {left} 分钟后完成）。"
    s["retreat_until"] = float(now) + RETREAT_SECONDS
    return True, f"已闭关化解外来道果杂质：6 小时后杂质 -{RETREAT_REDUCE}。"


def battle_bonus(s: Mapping, now: float) -> float:
    """战斗三维总加成；由 main._stats 消费（纯读，不回写）。"""
    total = 0.0
    if s.get("foreign_fruit"):
        total += float(s["foreign_fruit"].get("bonus", FRUIT_BONUS))
    if float(s.get("crack_until", 0) or 0) > now:
        total += CRACK_PENALTY
    if s.get("puppet") and float(s.get("puppet_until", 0) or 0) > now:
        total += PUPPET_BONUS
    return total


def _hours_left(until: float, now: float) -> int:
    return max(1, int((float(until) - now) / 3600) + 1)


def panel_lines(s: Mapping, now: float) -> list[str]:
    lines = ["--- 人傀 · 外来道果 ---"]
    p = s.get("puppet")
    if isinstance(p, dict):
        lines.append(f"人傀：{p.get('name')}｜灵根 {p.get('root')}｜功法 {p.get('gongfa')}")
        lines.append(f"三维 {int(p.get('atk', 0)):,}/{int(p.get('def', 0)):,}/{int(p.get('hp', 0)):,}"
                     f"｜耐久 {int(p.get('durability', 0))}/{DURABILITY_MAX}")
        if float(s.get("puppet_until", 0) or 0) > now:
            lines.append(f"出战中：三维 +{PUPPET_BONUS:.0%}，约 {_hours_left(s['puppet_until'], now)} 小时")
        else:
            lines.append(f"今日出战：{'已用' if s.get('puppet_day') == day_key(now) else '可用'}"
                         f"（耐久 ≥{SUMMON_MIN_DURABILITY}，「#驱使人傀」）")
    else:
        lines.append("人傀：未炼制（「#炼制人傀」需待炼遗蜕）")
    fruit = s.get("foreign_fruit")
    lines.append(f"外来道果：{fruit['name']}（+{FRUIT_BONUS:.0%}）" if isinstance(fruit, dict)
                 else "外来道果：空（「#炼化道果」）")
    lines.append(f"道果杂质：{int(s.get('impurity', 0))}/{IMPURITY_CAP}｜"
                 f"待炼道果：{'有' if s.get('guo') else '无'}｜"
                 f"待炼遗蜕：{'有' if s.get('remains') else '无'}")
    if float(s.get("retreat_until", 0) or 0) > now:
        lines.append(f"闭关化杂中：约 {_hours_left(s['retreat_until'], now)} 小时后杂质 -{RETREAT_REDUCE}")
    if float(s.get("crack_until", 0) or 0) > now:
        lines.append(f"⚠ 道果裂痕：约 {_hours_left(s['crack_until'], now)} 小时内全属性 -5%")
    return lines


def rules_text() -> str:
    return "\n".join([
        "--- 人傀 · 外来道果 规则 ---",
        f"炼制：待炼遗蜕 + 阴魂木×3 + 神魂结晶×1 + 灵石 {CRAFT_STONES:,}，三维取遗蜕 ×30%，耐久 100。",
        f"修复：阴魂木×1 + 灵石 {REPAIR_STONES:,}，耐久 +{REPAIR_GAIN}（上限 100）。",
        f"驱使：耐久 ≥{SUMMON_MIN_DURABILITY}，每日一次，扣 {SUMMON_DURABILITY_COST} 耐久，"
        f"6 小时内三维 +{PUPPET_BONUS:.0%}。",
        f"道果：「#处置 夺果」（目标境界 ≥{MIN_TARGET_REALM}）得待炼道果 →「#炼化道果」+{FRUIT_BONUS:.0%} 全属性、"
        f"杂质 +{IMPURITY_PER_REFINE}；「#熔去外来道果」清槽并 -{MELT_REDUCE} 杂质。",
        f"杂质 ≥{IMPURITY_CAP} 无法继续炼化；「#闭关化杂」6 小时后 -{RETREAT_REDUCE}。",
        "⚠️ 折算：原版人傀是下一场战斗的额外战体（本移植战斗引擎无伙伴位）→ 改 6 小时三维加成；"
        "原版耐久无扣减点（死链）→ 每次驱使扣 20；原版夺果需「自身之道」→ 改境界门槛；"
        "原版闭关占全局 action 锁 → 本移植只做本模块互斥。",
    ])


def help_text() -> str:
    return ("「#炼制人傀」「#我的人傀」「#驱使人傀」「#修复人傀」"
            "「#毁去人傀 确认」「#炼化道果」「#熔去外来道果」「#闭关化杂」"
            "｜「#我的邪道」查看人傀与道果面板")
