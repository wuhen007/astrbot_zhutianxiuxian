"""寿元 / 轮回（W2-2，对齐原版 apps/User/shouyuan.js + shouyuantask.js）。

原版语义：
- 寿元初始化 = 境界 id × 500（一键同步）；
- 流逝：定时任务每 3 小时（困难难度）——本移植无定时器，改为**每日签到时结算一次**；
  量级：未登仙（realm<41）固定 10 / 登仙后 100 / realm≥50 折半（原版 100/1000/500 同比 ÷100）；
  体质减免直译：圆环之理 ×0.1、圣体道胎/大成圣体/混沌体 ×0.5、小成圣体/大道体 ×0.6、
  圣体 ×0.7、神体/转生/魔头 ×0.8。
- 寿元 ≤0 → 轮回往生（原版 24h 救援窗口+执掌者，shortcut 未复刻）：境界归 1、修为血气清零、
  灵石折半、轮回次数 +1、寿元重置 500。
- 增补：渡劫成功 +5000、登仙 +10000（原版 Add_寿元 通道，无对应物品表）。
"""

from __future__ import annotations
from .clock import day_key

import time
from typing import Any

from .player import PlayerDoc

BASE_PER_REALM = 500
DECAY_MORTAL = 10        # 未登仙每日
DECAY_IMMORTAL = 100     # 登仙后每日
ASCEND_DISCOUNT_REALM = 50
DECAY_DISCOUNT = 0.5

TYPE_DISCOUNT = {
    "圆环之理": 0.1,
    "圣体道胎": 0.5, "大成圣体": 0.5, "混沌体": 0.5,
    "小成圣体": 0.6, "大道体": 0.6,
    "圣体": 0.7,
    "神体": 0.8, "转生": 0.8, "魔头": 0.8, "魔女": 0.8,
    "魔法少女": 0.8, "魔卡少女": 0.8,
}
REBIRTH_LIFESPAN = 500
TRIB_BONUS = 5000
ASCEND_BONUS = 10000


def shouyuan_of(doc: PlayerDoc) -> int:
    """当前寿元；旧档惰性初始化为 (realm_index+1)×500。"""
    v = doc.ext.get("shouyuan")
    if v is None:
        v = (int(doc.realm_index) + 1) * BASE_PER_REALM
        doc.ext["shouyuan"] = v
    return int(v)


def _type_of(doc: PlayerDoc) -> str:
    lg = doc.ext.get("linggen")
    return str(lg.get("type") or "") if isinstance(lg, dict) else ""


def decay_amount(doc: PlayerDoc) -> int:
    """本日流逝量（体质减免直译）。"""
    realm = int(doc.realm_index)
    if realm < 41:
        base = DECAY_MORTAL
    elif realm >= ASCEND_DISCOUNT_REALM:
        base = int(DECAY_IMMORTAL * DECAY_DISCOUNT)
    else:
        base = DECAY_IMMORTAL
    disc = TYPE_DISCOUNT.get(_type_of(doc))
    if disc is not None:
        base = max(1, int(base * disc))
    return base


def daily_decay(doc: PlayerDoc, now: float, decay: bool = True) -> tuple[int, bool]:
    """签到时调用：自然日一次流逝。返回 (本次流逝, 是否触发轮回)。

    `decay=False`（W8-F1 诸天难度「简单」）只盖章当天日期、不扣寿元。
    """
    day = day_key(now)
    if doc.ext.get("shouyuan_day") == day:
        return 0, False
    doc.ext["shouyuan_day"] = day
    if not decay:
        return 0, False
    cur = shouyuan_of(doc)
    left = max(0, cur - decay_amount(doc))
    doc.ext["shouyuan"] = left
    return cur - left, left <= 0


# ---------------------------------------------------------------- 濒死救援（W7-4）

RESCUE_SECONDS = 24 * 3600      # 原版 24 小时救援窗口
RESCUE_LIFESPAN = 1000          # 救回后寿元重续
RESCUE_COST = 5_000_000         # 救人者代为续命的代价（灵石）


def pending(doc: PlayerDoc) -> bool:
    """真灵离体、等待救援或转世。"""
    return bool(doc.ext.get("awaiting_rescue")) and int(shouyuan_of(doc)) <= 0


def rescue_left(doc: PlayerDoc, now: float) -> int:
    if not pending(doc):
        return 0
    try:
        deadline = float(doc.ext.get("rescue_deadline") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, int(deadline - now))


def mark_death(doc: PlayerDoc, now: float) -> str:
    """寿元耗尽 → 进入 24 小时救援窗口（不立即转世）。"""
    doc.ext["awaiting_rescue"] = True
    doc.ext["rescue_deadline"] = float(now) + RESCUE_SECONDS
    doc.ext["shouyuan"] = 0
    return (f"【真灵离体】寿元已尽，你的真灵被天地拘入轮回路。\n"
            f"24 小时内若有道友发「#轮回救人 @你」（耗 {RESCUE_COST:,} 灵石），"
            f"可把你从轮回路上拉回来；逾期则自动转世。")


def rescue(doc: PlayerDoc, now: float) -> tuple[bool, str]:
    """#轮回救人：把濒死修士拉回人间。"""
    if not pending(doc):
        return False, "此人真灵尚未离体，无需救援。"
    doc.ext.pop("awaiting_rescue", None)
    doc.ext.pop("rescue_deadline", None)
    doc.ext["shouyuan"] = RESCUE_LIFESPAN
    doc.ext["rescued_count"] = int(doc.ext.get("rescued_count", 0) or 0) + 1
    return True, f"真灵归位！{doc.name or doc.uid} 自轮回路被拉回，寿元重续 {RESCUE_LIFESPAN} 年。"


def resolve_if_due(doc: PlayerDoc, now: float, forced: bool = True) -> str | None:
    """读时惰性结算：过期的救援窗口 → 转世。返回转世文案或 None。

    `forced=False`（W8-F1 诸天难度「简单/普通」）不强制轮回，真灵会一直
    停在救援窗口里，等道友救回。
    """
    if not pending(doc):
        return None
    if not forced:
        return None
    try:
        deadline = float(doc.ext.get("rescue_deadline") or 0)
    except (TypeError, ValueError):
        deadline = 0.0
    if deadline > now:
        return None
    doc.ext.pop("awaiting_rescue", None)
    doc.ext.pop("rescue_deadline", None)
    return rebirth(doc)


def rebirth(doc: PlayerDoc) -> str:
    """寿元耗尽转世：境界/修为/血气归零，灵石折半，轮回 +1。"""
    count = int(doc.ext.get("rebirths", 0) or 0) + 1
    doc.ext["rebirths"] = count
    doc.realm_index = 0
    doc.physique_index = 0
    doc.exp = 0
    doc.stones = int(doc.stones) // 2
    doc.ext["hp"] = 0
    doc.ext["xueqi"] = 0.0
    doc.ext["shouyuan"] = REBIRTH_LIFESPAN
    doc.ext.pop("shouyuan_day", None)
    doc.ext.pop("power", None)
    doc.state = "空闲"
    return (f"【轮回往生】寿元已尽，真灵入轮回路——第 {count} 世开启。\n"
            f"境界与修为尽归尘土，灵石折半随身，寿元重续 {REBIRTH_LIFESPAN}。\n"
            f"前尘记忆不灭，道友重头再来。")


def grant(doc: PlayerDoc, amount: int) -> int:
    """增寿（渡劫/登仙等）。返回新值。"""
    cur = shouyuan_of(doc)
    doc.ext["shouyuan"] = cur + max(0, int(amount))
    return doc.ext["shouyuan"]


# W7-0：丹药表的 shouyuan 字段此前零消费（寿命丹服下不增寿），补上真实结算。
PILL_DAILY_CAP = 4                       # 每自然日最多生效的枚数
PILL_DECAY = (1.0, 0.5, 0.25, 0.125)   # 同日第 n 枚药力递减（抗药性）


def grant_pill(doc: PlayerDoc, base: int, now: float) -> tuple[int, str]:
    """服用增寿丹药：同日药力递减、超过上限不再生效。

    返回 (实际增寿, 说明)。增寿为 0 时调用方应拒绝消耗物品，避免白吃。
    """
    day = day_key(now)
    if doc.ext.get("pill_day") != day:
        doc.ext["pill_day"] = day
        doc.ext["pill_taken"] = 0
    n = int(doc.ext.get("pill_taken", 0) or 0)
    if n >= PILL_DAILY_CAP:
        return 0, (f"今日药力已饱和（每日上限 {PILL_DAILY_CAP} 枚），"
                   f"再服也是暴殄天物，明日再来吧。")
    factor = PILL_DECAY[min(n, len(PILL_DECAY) - 1)]
    gained = max(1, int(int(base) * factor))
    doc.ext["pill_taken"] = n + 1
    cur = grant(doc, gained)
    return gained, (f"寿元 +{gained:,} 年（今日第 {n + 1} 枚，药力 ×{factor:g}，"
                    f"现共 {cur:,} 年）")


def text(doc: PlayerDoc) -> str:
    cur = shouyuan_of(doc)
    t = _type_of(doc)
    disc = TYPE_DISCOUNT.get(t)
    lines = [
        "--- 寿元 ---",
        f"寿元：{cur:,} 年（第 {int(doc.ext.get('rebirths', 0) or 0) + 1} 世）",
        f"每日流逝：{decay_amount(doc)} 年（签到时结算）",
    ]
    if disc is not None:
        lines.append(f"体质「{t}」岁月侵蚀 ×{disc:g}")
    if pending(doc):
        lines.append("⚠ 真灵离体：等待道友 #轮回救人，逾期将转世")
    elif cur <= 100:
        lines.append("⚠ 寿元将尽，大限将至……")
    return "\n".join(lines)
