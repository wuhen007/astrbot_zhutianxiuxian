"""天道赐福 / 每日抽奖（对齐原版 apps/User/UserStart.js，W6-1）。

shortcut: 原版道法仙术 30 天订阅、时代系数、自动任务版本未移植；
赐福保留境界门槛 + 命格倍率 + 职业分支，抽奖按原版 41 项等概率。
"""
from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

GATE_LEVEL_ID = 22          # 原版 level_id>=22（破虚境初期）；本移植 realm_index 0-based，故 +1 对齐
MAX_LOTTERY = 50            # 原版 UserStart.js:559-569 单次连抽上限
TICKETS_PER_CLAIM = 3       # #领取每日奖励 发放次数，原版 meirrenwu.js:473

# 原版 UserStart.js:576-619，顺序即权重（Math.random 等概率，41 项）
LOTTERY_POOL: list[tuple[str, int]] = [
    ("秘境之匙", 3), ("秘境之匙", 5),
    ("残卷", 3), ("残卷", 5), ("残卷", 10),
    ("摘榜令", 3), ("摘榜令", 5),
    ("灵矿", 7), ("灵矿", 10),
    ("洗根水", 5), ("洗根水", 10), ("洗根水", 20),
    ("岩浆", 3), ("岩浆", 5), ("食材盒", 3),
    ("龙血锻体丹", 1), ("龙血锻体丹", 5),
    ("冰心丹", 1), ("冰心丹", 5),
    ("仙品福源丹", 1), ("仙品福源丹", 3),
    ("幸运草", 3), ("幸运草", 5),
    ("1级仙石", 1), ("2级仙石", 1),
    ("玄品秘境结算卡", 1), ("玄品秘境结算卡", 3),
    ("寿命丹", 5), ("寿命丹", 10),
    ("打工券", 5), ("打工券", 10),
    ("世界石", 5), ("世界石", 10),
    ("造化神果", 1),
    ("九阶淬体丹", 3), ("九阶玄元丹", 3),
    ("豆子的加持", 3), ("琴笙的加持", 1),
    ("天命轮回丹", 1), ("太素蕴灵丹", 5), ("玄黄造化丹", 5),
]


def day_key(now: float) -> str:
    """北京时间自然日键（与签到/每日任务同口径）。"""
    return time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))


def tiandao_gift(doc: PlayerDoc, now: float, mult: float = 1.0,
                 daofa: bool = False) -> tuple[bool, str, PlayerDoc, dict[str, int]]:
    """天道赐福：境界达标、每日一次，按境界与命格倍率发道具。

    返回 (是否成功, 文案, 新档案, 物品)。
    """
    level_id = int(doc.realm_index) + 1
    if level_id < GATE_LEVEL_ID:
        return False, f"境界未达破虚境（需第 {GATE_LEVEL_ID} 境，当前第 {level_id} 境），天道不赐福。", doc, {}
    today = day_key(now)
    if doc.ext.get("tiandao_day") == today:
        return False, "你今日已经领过天道赐福了。", doc, {}

    d = doc.model_copy(deep=True)
    d.ext["tiandao_day"] = today
    count = max(1, int(level_id * 0.1 * max(0.1, float(mult or 1.0))))
    got: dict[str, int] = {"秘境之匙": count, "打工券": count}
    if level_id > 41:
        got["仙舟"] = count
    if level_id > 54:
        got["神域令牌"] = count
    job = str(d.ext.get("occupation") or "")
    if job == "侠客":
        got["侠客令"] = 3
    elif job == "唤魔者":
        got["唤魔令"] = 3
    if daofa:   # 原版 UserStart.js:770-776 道法仙术额外四类
        for name in ("秘境之匙", "打工券", "九阶玄元丹", "九阶淬体丹"):
            got[name] = got.get(name, 0) + count

    lines = ["天道赐福：", f"秘境之匙 ×{count}｜打工券 ×{count}"]
    if level_id > 41:
        lines.append(f"仙舟 ×{count}（仙人加持）")
    if level_id > 54:
        lines.append(f"神域令牌 ×{count}（万界之上）")
    if job in ("侠客", "唤魔者"):
        lines.append(f"职业【{job}】额外 {'侠客令' if job == '侠客' else '唤魔令'} ×3")
    if daofa:
        lines.append("【道法仙术】额外 秘境之匙/打工券/九阶玄元丹/九阶淬体丹 各 ×" + str(count))
    if float(mult or 1.0) != 1.0:
        lines.append(f"【命格】签到奖励倍率 ×{mult} 生效")
    return True, "\n".join(lines), d, got


def lottery(doc: PlayerDoc, count: int, rng: random.Random,
            per_draw: int = 1) -> tuple[bool, str, PlayerDoc, dict[str, int]]:
    """每日抽奖：奖池 41 项等概率；per_draw=2 为道法仙术权益（每次抽 2 份，只扣 1 次券）。

    返回 (是否成功, 文案, 新档案, 物品)。
    """
    tickets = int(doc.ext.get("lottery_tickets", 0) or 0)
    count = int(count)
    if count < 1:
        return False, "格式：#每日抽奖 或 #每日抽奖*次数。", doc, {}
    count = min(count, tickets, MAX_LOTTERY)
    if count < 1:
        return False, f"抽奖次数不足（当前 {tickets} 次，#领取每日奖励 可 +{TICKETS_PER_CLAIM}）。", doc, {}

    d = doc.model_copy(deep=True)
    d.ext["lottery_tickets"] = tickets - count
    got: dict[str, int] = {}
    for _ in range(count * max(1, int(per_draw))):
        name, qty = LOTTERY_POOL[int(rng.random() * len(LOTTERY_POOL))]
        got[name] = got.get(name, 0) + qty
    lines = [f"每日抽奖 ×{count}" + ("（道法仙术双份）" if per_draw > 1 else "") + "："] + [f"· {n} ×{q}" for n, q in got.items()]
    lines.append(f"剩余抽奖次数：{d.ext['lottery_tickets']}")
    return True, "\n".join(lines), d, got


def grant_tickets(doc: PlayerDoc, amount: int = TICKETS_PER_CLAIM) -> PlayerDoc:
    """#领取每日奖励 时发放抽奖次数（原版 +3，纯累加不重置）。"""
    d = doc.model_copy(deep=True)
    d.ext["lottery_tickets"] = int(d.ext.get("lottery_tickets", 0) or 0) + int(amount)
    return d
