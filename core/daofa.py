"""道法仙术订阅体系（W6-2，对齐原版 XiuxianData.js / AdminSuper.js / UserStart.js）。

shortcut: 原版三体系 extraCultivationLevelSum 用常数 2；原版 6 种令简化为本移植
道具表实际存在的「遣龙令/遣虎令」；到期用读时惰性判定（无 0 点 cron）；
开卡道具（日/周/月卡）与自动任务全套未移植。
"""
from __future__ import annotations

import time
from typing import Any

from .blessing import day_key
from .player import PlayerDoc

FLAG = 2
SUBSCRIBE_MS = 30 * 86400 * 1000      # 原版 2592000000 毫秒 = 30 天
EXTRA_SUM = 2                          # shortcut: getExtraCultivationLevelSum 默认值
GIFT_ITEMS = ("遣龙令", "遣虎令", "灵品秘境结算卡")


def expire_if_needed(doc: PlayerDoc, now: float | None = None) -> PlayerDoc:
    """读时惰性到期：过期清零 flag（原版由 0 点 cron 批量做）。"""
    now = time.time() if now is None else now
    if int(doc.ext.get("daofaxianshu", 0) or 0) == FLAG and \
            float(doc.ext.get("daofaxianshu_endtime", 0) or 0) <= now * 1000:
        doc.ext["daofaxianshu"] = 0
    return doc


def active(doc: PlayerDoc, now: float) -> bool:
    return (int(doc.ext.get("daofaxianshu", 0) or 0) == FLAG
            and float(doc.ext.get("daofaxianshu_endtime", 0) or 0) > now * 1000)


def remaining_days(doc: PlayerDoc, now: float) -> float:
    if not active(doc, now):
        return 0.0
    return max(0.0, (float(doc.ext["daofaxianshu_endtime"]) - now * 1000) / 86400000)


def open_for(doc: PlayerDoc, now: float) -> tuple[bool, str]:
    """#开通道法仙术 @玩家：叠加 30 天（原版重复开通即续期）。"""
    d = expire_if_needed(doc, now)
    end = float(d.ext.get("daofaxianshu_endtime", 0) or 0)
    base = max(now * 1000, end) if end > now * 1000 else now * 1000
    d.ext["daofaxianshu"] = FLAG
    d.ext["daofaxianshu_endtime"] = base + SUBSCRIBE_MS
    d.ext.setdefault("daofa_days", 0)
    return True, (f"已为 {d.name or d.uid} 开通道法仙术 30 天"
                  f"（累计剩余 {remaining_days(d, now):.1f} 天）。")


def gift(doc: PlayerDoc, now: float, mult: float = 1.0) -> tuple[bool, str, PlayerDoc, dict[str, int]]:
    """#道法赐福：每日一次，连续 7 天一轮，修为/血气 + 令/传送阵/结算卡。

    原版 UserStart.js:1622-1744；shortcut: 手动版断签不归 1（与自动版口径不同）。
    """
    if not active(doc, now):
        return False, "道法仙术未开通或已过期（管理员 #开通道法仙术 @玩家）。", doc, {}
    today = day_key(now)
    if doc.ext.get("daofa_day") == today:
        return False, "今日已领过道法赐福。", doc, {}
    d = doc.model_copy(deep=True)
    d.ext["daofa_day"] = today
    days = int(d.ext.get("daofa_days", 0) or 0) + 1
    bonus_box = False
    if days >= 7:
        days, bonus_box = 1, True
    d.ext["daofa_days"] = days
    level_id = int(d.realm_index) + 1
    physique_id = int(d.physique_index) + 1
    amount = int(days * 10000 * level_id * physique_id * EXTRA_SUM * max(0.1, float(mult or 1.0)))
    tickets = max(1, int(days * 2 * max(0.1, float(mult or 1.0))))
    d.exp += amount
    d.ext["xueqi"] = int(d.ext.get("xueqi", 0) or 0) + amount
    items = {name: tickets for name in GIFT_ITEMS}
    items["位面传送阵"] = 1
    if bonus_box:
        items["超越宝盒"] = 5
    lines = ["道法赐福：",
             f"连续第 {days} 天｜修为 +{amount:,}｜血气 +{amount:,}",
             f"遣龙令/遣虎令/灵品秘境结算卡 各 ×{tickets}｜位面传送阵 ×1"]
    if bonus_box:
        lines.append("满 7 天轮回：超越宝盒 ×5")
    if float(mult or 1.0) != 1.0:
        lines.append(f"【命格】签到奖励倍率 ×{mult} 生效")
    return True, "\n".join(lines), d, items


# ---------------------------------------------------------------- 道法卡（W7-4）

CARDS: dict[str, dict] = {
    "日卡": {"days": 1, "price": 2_000_000, "loot": 1, "sign": 0.10, "tianjiao_cd": 0.05},
    "周卡": {"days": 7, "price": 12_000_000, "loot": 1, "sign": 0.20, "tianjiao_cd": 0.10},
    "月卡": {"days": 30, "price": 40_000_000, "loot": 2, "sign": 0.30, "tianjiao_cd": 0.20},
}


def card_of(doc: PlayerDoc, now: float) -> tuple[str | None, dict]:
    """当前生效的道法卡（读时惰性到期）。"""
    raw = doc.ext.get("daofa_card")
    if not isinstance(raw, dict):
        return None, {}
    tier = str(raw.get("tier") or "")
    cfg = CARDS.get(tier)
    if not cfg:
        return None, {}
    try:
        end = float(raw.get("end") or 0)
    except (TypeError, ValueError):
        end = 0.0
    if end <= now:
        return None, {}
    return tier, cfg


def buy_card(doc: PlayerDoc, tier: str, now: float) -> tuple[bool, str, PlayerDoc]:
    """#购买道法卡：按天叠加续期，灵石支付。"""
    cfg = CARDS.get(tier)
    if not cfg:
        return False, f"没有「{tier}」这种卡（可选：{'、'.join(CARDS)}）。", doc
    price = int(cfg["price"])
    if int(doc.stones) < price:
        return False, f"{tier}需 {price:,} 灵石（当前 {int(doc.stones):,}）。", doc
    d = doc.model_copy(deep=True)
    d.stones -= price
    cur = d.ext.get("daofa_card") if isinstance(d.ext.get("daofa_card"), dict) else {}
    base = max(now, float(cur.get("end") or 0)) if str(cur.get("tier") or "") == tier else now
    d.ext["daofa_card"] = {"tier": tier, "end": base + int(cfg["days"]) * 86400}
    left = (base + int(cfg["days"]) * 86400 - now) / 86400
    return True, (f"购得【{tier}】×{int(cfg['days'])} 天：秘境出金档 +{cfg['loot']}、"
                  f"签到灵石 +{cfg['sign']:.0%}、天骄冷却 -{cfg['tianjiao_cd']:.0%}"
                  f"（剩余 {left:.1f} 天，花费 {price:,} 灵石）。"), d


def card_bonus(doc: PlayerDoc, now: float) -> dict:
    """卡权益汇总：{loot: 稀有档加成, sign: 签到倍率, cd: 天骄 CD 减免}。"""
    _tier, cfg = card_of(doc, now)
    if not cfg:
        return {"loot": 0, "sign": 0.0, "cd": 0.0}
    return {"loot": int(cfg["loot"]), "sign": float(cfg["sign"]), "cd": float(cfg["tianjiao_cd"])}


def status_text(doc: PlayerDoc, now: float) -> str:
    tier, cfg = card_of(doc, now)
    card_line = ""
    if tier:
        left = (float(doc.ext["daofa_card"]["end"]) - now) / 86400
        card_line = (f"\n道法卡：{tier}（剩 {left:.1f} 天）｜出金档 +{cfg['loot']}、"
                     f"签到 +{cfg['sign']:.0%}、天骄冷却 -{cfg['tianjiao_cd']:.0%}")
    if active(doc, now):
        return (f"--- 道法仙术 ---\n状态：生效中｜剩余 {remaining_days(doc, now):.1f} 天"
                f"｜连续赐福 {int(doc.ext.get('daofa_days', 0) or 0)} 天\n"
                f"权益：#道法赐福、签到 ×2、每日抽奖每抽双份、天道赐福额外四类" + card_line)
    return ("--- 道法仙术 ---\n状态：未开通或已过期（管理员 #开通道法仙术 @玩家 可开通 30 天）"
            + card_line)
