"""寿元 / 轮回（W2-2，对齐原版 apps/User/shouyuan.js + shouyuantask.js）。

原版语义：
- 寿元初始化 = 境界 id × 500（一键同步）；
- 流逝：定时任务每 3 小时（困难难度）——本移植无定时器，改为**每日签到时结算一次**；
  量级：未登仙（realm<41）固定 10 / 登仙后 100 / realm≥50 折半（原版 100/1000/500 同比 ÷100）；
  体质减免直译：圆环之理 ×0.1、圣体道胎/大成圣体/混沌体 ×0.5、小成圣体/大道体 ×0.6、
  圣体 ×0.7、神体/转生/魔头 ×0.8。
- 寿元 ≤0 → 轮回往生（原版 5 分钟救援窗口+执掌者，shortcut 未复刻）：境界归 1、修为血气清零、
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


def daily_decay(doc: PlayerDoc, now: float, decay: bool = True,
                era_index: int | None = None) -> tuple[int, bool]:
    """签到时调用：自然日一次流逝。隐藏寿元与绝灵压制显示同步扣减。"""
    day = day_key(now)
    if doc.ext.get("shouyuan_day") == day:
        return 0, False
    doc.ext["shouyuan_day"] = day
    if not decay:
        return 0, False
    if era_index is not None:
        from . import era as era_mod
        era_mod.sync_jueling_lifespan(doc, era_index)
    hidden_key = "jueling_suppressed_lifespan"
    if hidden_key in doc.ext:
        cur = max(0, int(doc.ext.get(hidden_key, 0) or 0))
        left = max(0, cur - decay_amount(doc))
        doc.ext[hidden_key] = left
        doc.ext["shouyuan"] = min(left, 9_999)
    else:
        cur = shouyuan_of(doc)
        left = max(0, cur - decay_amount(doc))
        doc.ext["shouyuan"] = left
    return cur - left, cur > 0 and left <= 0


# ---------------------------------------------------------------- 濒死救援（W7-4）

RESCUE_SECONDS = 5 * 60        # 固定上游寿元耗尽任务：5 分钟后进入往生裁定
RESCUE_LIFESPAN = 1000          # 救回后寿元重续
RESCUE_COST = 5_000_000         # 救人者代为续命的代价（灵石）


TRAVEL_AMBUSH_REBIRTH = "travel_ambush_rebirth"


def pending(doc: PlayerDoc) -> bool:
    """真灵离体、等待救援或转世。"""
    return bool(doc.ext.get("awaiting_rescue")) and (
        bool(doc.ext.get(TRAVEL_AMBUSH_REBIRTH)) or int(shouyuan_of(doc)) <= 0)


def rescue_left(doc: PlayerDoc, now: float) -> int:
    if not pending(doc):
        return 0
    try:
        deadline = float(doc.ext.get("rescue_deadline") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, int(deadline - now))


def mark_death(doc: PlayerDoc, now: float) -> str:
    """困难难度寿元耗尽 → 进入五分钟救援窗口。"""
    doc.ext["awaiting_rescue"] = True
    doc.ext["rescue_deadline"] = float(now) + RESCUE_SECONDS
    if "jueling_suppressed_lifespan" in doc.ext:
        doc.ext["jueling_suppressed_lifespan"] = 0
    doc.ext["shouyuan"] = 0
    return (f"【真灵离体】寿元已尽，你的真灵被天地拘入轮回路。\n"
            f"5 分钟内可由额外体系权柄达到 {11}/24 的道友发「#轮回救人 @你」接引；"
            f"期满后由轮回路执掌者裁定；无人执掌时自动往生。")


def mark_travel_ambush_death(doc: PlayerDoc, now: float) -> str:
    """位面旅行被天骄伏杀：五分钟救援窗，到期强制往生但不扣寿元。"""
    doc.ext[TRAVEL_AMBUSH_REBIRTH] = True
    doc.ext["awaiting_rescue"] = True
    doc.ext["rescue_deadline"] = float(now) + RESCUE_SECONDS
    doc.ext["hp"] = max(1, int(float(doc.ext.get("hp", 0) or 0)))
    return ("【伏杀陨落·真灵离体】天骄伏击令你身死道消，真灵坠入轮回路。\n"
            "5 分钟内可由额外体系权柄达到 11/24 的道友发送「#轮回救人 @你」接引；"
            "期满后按轮回路执掌者裁定，或无人执掌时自动往生。")



def restore_expired_rescue(doc: PlayerDoc) -> bool:
    """难度改为不强制往生或执掌者驳回后恢复阳世。"""
    if not pending(doc):
        return False
    travel_ambush = bool(doc.ext.pop(TRAVEL_AMBUSH_REBIRTH, None))
    doc.ext.pop("awaiting_rescue", None)
    doc.ext.pop("rescue_deadline", None)
    doc.ext.pop("reincarnation_phase", None)
    if not travel_ambush:
        doc.ext["shouyuan"] = RESCUE_LIFESPAN
        if "jueling_suppressed_lifespan" in doc.ext:
            doc.ext["jueling_suppressed_lifespan"] = RESCUE_LIFESPAN
    if int(doc.ext.get("hp", 0) or 0) <= 0:
        doc.ext["hp"] = 1
    return True

def rescue(doc: PlayerDoc, now: float, controller_pending: bool = False) -> tuple[bool, str]:
    """#轮回救人：权柄足够者在救援期或裁定期将真灵拉回。"""
    if not pending(doc):
        return False, "此人真灵尚未离体，无需救援。"
    if rescue_left(doc, now) <= 0 and not controller_pending:
        return False, "五分钟救援期已过，只有轮回路执掌者可裁定是否往生。"
    travel_ambush = bool(doc.ext.pop(TRAVEL_AMBUSH_REBIRTH, None))
    doc.ext.pop("awaiting_rescue", None)
    doc.ext.pop("rescue_deadline", None)
    doc.ext.pop("reincarnation_phase", None)
    if travel_ambush:
        if int(doc.ext.get("hp", 0) or 0) <= 0:
            doc.ext["hp"] = 1
        return True, f"真灵归位！{doc.name or doc.uid} 被道友从伏杀轮回路中接回，原有寿元保留。"
    doc.ext["shouyuan"] = RESCUE_LIFESPAN
    if "jueling_suppressed_lifespan" in doc.ext:
        doc.ext["jueling_suppressed_lifespan"] = RESCUE_LIFESPAN
    doc.ext["rescued_count"] = int(doc.ext.get("rescued_count", 0) or 0) + 1
    return True, f"真灵归位！{doc.name or doc.uid} 自轮回路被拉回，寿元重续 {RESCUE_LIFESPAN} 年。"


def resolve_if_due(doc: PlayerDoc, now: float, forced: bool = True) -> str | None:
    """无执掌者时惰性结算已到期的强制轮回状态；化身仍在时暂缓处理。"""
    if not pending(doc):
        return None
    zt = doc.ext.get("zhutian")
    stage = "travel_avatar" if isinstance(zt, dict) and bool(zt.get("current")) else ""
    if stage == "travel_avatar":
        return None
    if not forced and not doc.ext.get(TRAVEL_AMBUSH_REBIRTH):
        return None
    try:
        deadline = float(doc.ext.get("rescue_deadline") or 0)
    except (TypeError, ValueError):
        deadline = 0.0
    if deadline > now:
        return None
    doc.ext.pop("awaiting_rescue", None)
    doc.ext.pop("rescue_deadline", None)
    doc.ext.pop("reincarnation_phase", None)
    doc.ext.pop(TRAVEL_AMBUSH_REBIRTH, None)
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
    if "jueling_suppressed_lifespan" in doc.ext:
        doc.ext["jueling_suppressed_lifespan"] = REBIRTH_LIFESPAN
    doc.ext.pop("shouyuan_day", None)
    doc.ext.pop("power", None)
    doc.ext.pop("awaiting_rescue", None)
    doc.ext.pop("rescue_deadline", None)
    doc.ext.pop("reincarnation_phase", None)
    doc.ext.pop(TRAVEL_AMBUSH_REBIRTH, None)
    doc.state = "空闲"
    return (f"【轮回往生】寿元已尽，真灵入轮回路——第 {count} 世开启。\n"
            f"境界与修为尽归尘土，灵石折半随身，寿元重续 {REBIRTH_LIFESPAN}。\n"
            f"前尘记忆不灭，道友重头再来。")


def grant(doc: PlayerDoc, amount: int, era_index: int | None = None) -> int:
    """增寿（渡劫/登仙等），同步绝灵期间的隐藏真实寿元。"""
    amount = int(amount)
    amount = max(0, int(amount))
    if era_index is not None or "jueling_suppressed_lifespan" in doc.ext:
        from . import era as era_mod
        use_index = (era_index if era_index is not None else era_mod.JUELING_ERA_INDEX)
        era_mod.add_jueling_aware_lifespan(doc, amount, use_index)
    else:
        doc.ext["shouyuan"] = shouyuan_of(doc) + amount
    return int(doc.ext["shouyuan"])


def spend(doc: PlayerDoc, amount: int) -> int:
    """支付寿元；若在绝灵压制中，同时扣除隐藏真实值。返回实际支付量。"""
    cost = max(0, int(amount))
    hidden_key = "jueling_suppressed_lifespan"
    if hidden_key in doc.ext:
        current = max(0, int(doc.ext.get(hidden_key, 0) or 0))
        paid = min(current, cost)
        left = current - paid
        doc.ext[hidden_key] = left
        doc.ext["shouyuan"] = min(left, 9_999)
        return paid
    current = shouyuan_of(doc)
    paid = min(current, cost)
    doc.ext["shouyuan"] = current - paid
    return paid


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
