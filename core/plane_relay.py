"""位面中转：接引与送往采用限时同意；阵牌则消耗一次并开始异步旅行。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from . import extra_cultivation, plane as plane_mod, timed_action
from .player import PlayerDoc
from .wallet import authority, pay_exp_xq

RELAY_AUTH = 18
WUXI_GATE = 14
WUXI_COST = 500_000
WUXI_PLANE = "遮天位面"
PORTAL_ITEM = "位面传送阵"
HIGH_PORTAL_ITEM = "高级传送阵令牌"
TRAVEL_WIND_ITEM = "天外清风"
TRAVEL_WIND_REDUCTION_MINUTES = 5
PORTAL_ITEM_COUNTS = {
    "位面传送阵": ("low", 1),
    "大位面传送阵": ("low", 3),
    "高级传送阵令牌": ("high", 1),
}
TOKEN_BASE_MINUTES = {"high": 3, "low": 12}
TOKEN_ACCIDENT_BASE = {"high": 0.05, "low": 0.40}
TOKEN_ACCIDENT_REALM_REDUCE = 0.30
OFFER_SECONDS = 60
SPECIAL_PLANES = frozenset({
    "仙域", "异域", "时间长河", "永恒未知之地", "小阴间", "大阴间", "阳间",
    "厄土高原", "上苍之上", "超维宇宙", "百维真界", "原初宇宙海",
    "千维宙古界", "万维梵宇界", "神维丝线海", "彼岸世界", "复活地球",
    "试炼宇宙", "剑与魔法",
})


def _destination_check(doc: PlayerDoc, src: str, target: str,
                       destroyed: Mapping | None = None) -> tuple[bool, str]:
    if target not in plane_mod.LEVELS:
        return False, f"没有「{target}」这个位面。"
    ok, why = plane_mod.barrier_check(doc, src, target, destroyed)
    if not ok:
        return False, why
    if target == "异域":
        level = extra_cultivation.realm_authority_level(doc)
        if level < RELAY_AUTH:
            return False, f"异域法则排斥仙王以下的真身，需达到仙王级权柄（18/18），当前 {level}。"
    if target != "异域":
        quote = plane_mod.quote(doc, target)
        if not quote.get("ok"):
            return False, f"无法锚定「{target}」：{quote.get('reason') or '位面未知'}。"
        if not quote.get("enough_target", quote.get("enough_realm", False)):
            return False, f"当前境界无法承受「{target}」的位面法则（需达到第 {quote.get('gate')} 境）。"
    return True, ""


def _coordinate_anchor(st: Mapping, target: str) -> dict | None:
    if not plane_mod.has_square_map(target):
        return None
    coords = st.get("coords")
    coord = coords.get(target) if isinstance(coords, Mapping) else None
    if not isinstance(coord, Mapping):
        return None
    if not isinstance(coord.get("x"), int) or not isinstance(coord.get("y"), int):
        return None
    return {"x": int(coord["x"]), "y": int(coord["y"])}


def _open_offer(sender: PlayerDoc, sender_st: Mapping, target: PlayerDoc,
                target_st: dict[str, Any], target_name: str, location: str,
                kind: str, now: float, destroyed: Mapping | None = None,
                ) -> tuple[bool, str]:
    sender_level = extra_cultivation.realm_authority_level(sender)
    if sender_level < RELAY_AUTH:
        label = "接引" if kind == "jieyin" else "送往"
        return False, f"{label}需仙王之力（权柄 ≥{RELAY_AUTH}），当前 {sender_level}。"
    if getattr(target, "state", "空闲") != "空闲":
        return False, f"「{target.name or target.uid[:8]}」正在「{target.state}」中，暂不能响应接引/送往。"
    if not plane_mod.has_coordinate(sender, location):
        return False, f"你尚未记下「{location}」的位面坐标，无法锚定通道；先 #记坐标 {location}。"
    src = plane_mod.current(plane_mod.state_of(target))
    ok, why = _destination_check(target, src, location, destroyed)
    if not ok:
        return False, f"「{target.name or target.uid[:8]}」无法承受「{location}」的位面法则：{why}"
    old = target_st.get("plane_offer")
    if isinstance(old, dict) and float(old.get("until", 0) or 0) > now:
        return False, f"「{target_name}」尚有待应答的接引/送往请求（60 秒内）。"
    target_st["plane_offer"] = {
        "from_uid": str(sender.uid), "target_uid": str(target.uid),
        "from_name": sender.name or sender.uid[:8], "type": kind,
        "from_plane": plane_mod.current(plane_mod.state_of(sender)),
        "plane": location, "coord": _coordinate_anchor(sender_st, location),
        "until": float(now) + OFFER_SECONDS,
    }
    label = "接引" if kind == "jieyin" else "送往"
    action = "接引至" if kind == "jieyin" else "送往"
    return True, (f"【{label}请求】你欲将「{target_name}」{action}「{location}」。"
                  f"对方须在 60 秒内 #同意接引，或发送 #拒绝接引。")


# ---------------------------------------------------------------- 五色祭坛

def wuxi_activate(doc: PlayerDoc, st: dict[str, Any], now: float,
                  ) -> tuple[bool, str]:
    """#激活五色祭坛：圣人以下记下遮天位面坐标。"""
    if authority(doc) >= WUXI_GATE:
        return False, "你已是圣人之境——穿梭遮天无需借祭坛之力。"
    if plane_mod.has_coordinate(doc, WUXI_PLANE):
        return False, "五色祭坛早已激活——遮天坐标在册（#穿梭 遮天位面）。"
    err = pay_exp_xq(doc, WUXI_COST)
    if err:
        return False, f"【位面中继·条件不足】激活需修为与血气各 {WUXI_COST:,}。{err}"
    known = st.setdefault("known", [])
    if WUXI_PLANE not in known:
        known.append(WUXI_PLANE)
    return True, ("【五色祭坛】五彩灵光冲天而起——遮天位面坐标已刻入识海！\n"
                  "此后 #穿梭 遮天位面 直达，无需记坐标。")


# ---------------------------------------------------------------- 接引 / 送往

def jiesong_offer(sender: PlayerDoc, sender_st: Mapping, target: PlayerDoc,
                  target_st: dict[str, Any], target_name: str, now: float,
                  destroyed: Mapping | None = None) -> tuple[bool, str]:
    """#接引：锚定发起者当前位面，写入目标档案的 60 秒待确认请求。"""
    location = plane_mod.current(plane_mod.state_of(sender))
    return _open_offer(sender, sender_st, target, target_st, target_name,
                       location, "jieyin", now, destroyed)


def songwang_offer(sender: PlayerDoc, sender_st: Mapping, target: PlayerDoc,
                   target_st: dict[str, Any], location: str, target_name: str,
                   now: float, destroyed: Mapping | None = None,
                   ) -> tuple[bool, str]:
    """#送往：由发起者已知坐标锚定目的位面，等待受方同意。"""
    location = str(location or "").strip()
    return _open_offer(sender, sender_st, target, target_st, target_name,
                       location, "songwang", now, destroyed)


def pending_sender(st: Mapping) -> str:
    offer = st.get("plane_offer")
    return str(offer.get("from_uid") or "") if isinstance(offer, Mapping) else ""


def jiesong_accept(doc: PlayerDoc, st: dict[str, Any], now: float,
                   destroyed: Mapping | None = None,
                   sender: PlayerDoc | None = None) -> tuple[bool, str]:
    offer = st.get("plane_offer")
    if not isinstance(offer, dict):
        return False, "当前没有需要你确认的接引/送往请求。"
    if str(offer.get("target_uid") or "") != str(doc.uid):
        return False, "这份接引/送往请求不属于当前角色。"
    if float(offer.get("until", 0) or 0) <= now:
        st.pop("plane_offer", None)
        return False, "接引/送往请求已超时（60 秒未应答），请让对方重新发起。"
    if sender is None or str(sender.uid) != str(offer.get("from_uid") or ""):
        st.pop("plane_offer", None)
        return False, "接引/送往发起者已不可用，请让对方重新发起。"
    if extra_cultivation.realm_authority_level(sender) < RELAY_AUTH:
        st.pop("plane_offer", None)
        return False, "发起者已不具备仙王级接引/送往之力，请重新发起。"
    if getattr(doc, "state", "空闲") != "空闲":
        return False, f"你正在「{doc.state}」中，暂无法响应接引/送往。"
    location = str(offer.get("plane") or "")
    if not plane_mod.has_coordinate(sender, location):
        st.pop("plane_offer", None)
        return False, f"发起者已无法锚定「{location}」的坐标，通道散去。"
    if offer.get("type") == "jieyin" and plane_mod.current(plane_mod.state_of(sender)) != location:
        st.pop("plane_offer", None)
        return False, "接引者已离开原定位面，仙光散去，请重新发起。"
    src = plane_mod.current(st)
    ok, why = _destination_check(doc, src, location, destroyed)
    if not ok:
        st.pop("plane_offer", None)
        return False, f"你已无法承受「{location}」的位面法则，通道散去。{why}"
    st.pop("plane_offer", None)
    if src == location:
        return True, f"你已身处「{location}」，接引/送往通道无需开启。"
    st["current"] = location
    coord = offer.get("coord")
    if plane_mod.has_square_map(location) and isinstance(coord, Mapping):
        if isinstance(coord.get("x"), int) and isinstance(coord.get("y"), int):
            st.setdefault("coords", {})[location] = {
                "x": int(coord["x"]), "y": int(coord["y"])}
    label = "接引" if offer.get("type") == "jieyin" else "送往"
    quest_note = ""
    if location == "异域":
        from . import story_quest
        quest_note = story_quest.record_foreign_hunt_arrival(doc, location)
    return True, f"【同意{label}】仙光卷身——你已抵达「{location}」！" + (f"\n{quest_note}" if quest_note else "")


def jiesong_reject(st: dict[str, Any], target_uid: str | None = None,
                   now: float | None = None) -> tuple[bool, str]:
    offer = st.get("plane_offer")
    if not isinstance(offer, dict):
        return False, "当前没有需要你确认或拒绝的接引/送往请求。"
    if target_uid is not None and str(offer.get("target_uid") or "") != str(target_uid):
        return False, "这份接引/送往请求不属于当前角色。"
    if now is not None and float(offer.get("until", 0) or 0) <= now:
        st.pop("plane_offer", None)
        return False, "接引/送往请求已超时失效，无需拒绝。"
    st.pop("plane_offer", None)
    return True, "【拒绝接引/送往】仙光散去——通道请求已作废。"


# ---------------------------------------------------------------- 传送阵

def activate_portal_item(doc: PlayerDoc, st: dict[str, Any], item_name: str,
                          quantity: int) -> tuple[bool, str, int]:
    """Original #使用 converts a portal item into reusable travel charges."""
    item_name = str(item_name or "").strip()
    spec = PORTAL_ITEM_COUNTS.get(item_name)
    qty = int(quantity or 0)
    if spec is None:
        return False, f"「{item_name}」不是位面传送阵道具。", 0
    if qty < 1:
        return False, "使用数量必须大于 0。", 0
    tier, per_item = spec
    uses = st.setdefault("portal_uses", {"low": 0, "high": 0})
    if not isinstance(uses, dict):
        uses = st["portal_uses"] = {"low": 0, "high": 0}
    added = qty * per_item
    uses[tier] = max(0, int(uses.get(tier, 0) or 0)) + added
    label = "高级传送" if tier == "high" else "位面传送"
    return True, f"【传送阵认主】{label}次数 +{added}（当前 {uses[tier]} 次）。", added


def activate_travel_wind(doc: PlayerDoc, st: dict[str, Any], quantity: int,
                         ) -> tuple[bool, str, int]:
    try:
        qty = int(quantity or 0)
    except (TypeError, ValueError, OverflowError):
        qty = 0
    if qty < 1:
        return False, "使用数量必须大于 0。", 0
    uses = max(0, int(st.get("wind_uses", 0) or 0)) + qty
    st["wind_uses"] = uses
    return True, f"清风引路已生效，可使接下来 {uses} 次跨位面穿梭各缩短 5 分钟（最低 1 分钟）。", qty


def _barrier_count(src: str, target: str) -> int:
    if src == target:
        return 0
    def layer(name: str) -> int:
        if name == plane_mod.TIME_RIVER_PLANE:
            return -1
        return int((plane_mod.HIGH_DIMENSIONS.get(name) or {}).get("layer", 0))
    return abs(layer(src) - layer(target))


def _equipped_treasure(doc: PlayerDoc, name: str) -> bool:
    ext = getattr(doc, "ext", {}) or {}
    equipment = ext.get("equipment") if isinstance(ext, Mapping) else None
    slot = equipment.get("至宝") if isinstance(equipment, Mapping) else None
    if isinstance(slot, Mapping):
        slot = slot.get("name") or slot.get("先天至宝本体") or ""
    state = ext.get("xtzb") if isinstance(ext, Mapping) else None
    current = state.get("current") if isinstance(state, Mapping) else ""
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    legacy_current = legacy.get("当前先天至宝") if isinstance(legacy, Mapping) else ""
    return name in (str(slot or ""), str(current or ""), str(legacy_current or ""))


def apply_travel_time_modifiers(doc: PlayerDoc, st: dict[str, Any], minutes: int,
                                now: float, rng: Any, src: str, target: str,
                                ) -> tuple[int, list[str], bool, float]:
    """Apply source order: wind, timed-action speed, then the equipped travel treasure."""
    travel_minutes = max(0, int(minutes or 0))
    if travel_minutes == 0:
        return 0, [], False, 1.0
    notes: list[str] = []
    wind_uses = max(0, int(st.get("wind_uses", 0) or 0))
    if wind_uses and travel_minutes > 1:
        before = travel_minutes
        travel_minutes = max(1, travel_minutes - TRAVEL_WIND_REDUCTION_MINUTES)
        st["wind_uses"] = wind_uses - 1
        notes.append(f"天外清风引路，行程缩短 {before - travel_minutes} 分钟（剩余 {st['wind_uses']} 次）。")
    multiplier = timed_action.multiplier(doc, now)
    travel_minutes = max(1, math.ceil(travel_minutes * multiplier))
    barrier = _barrier_count(src, target) > 0
    protected = _equipped_treasure(doc, "虚天舟")
    if _equipped_treasure(doc, "逐日仙辇"):
        before = travel_minutes
        roll = min(max(float(rng.random()), 0.0), 1.0 - math.ulp(1.0))
        if barrier and roll < 0.01:
            travel_minutes = 0
            notes.append("逐日仙辇·光阴一瞬，本次航程瞬间横渡。")
        elif barrier:
            rate = 0.15 + math.floor(roll * 11) / 100
            travel_minutes = max(1, math.ceil(before * (1 - rate)))
        else:
            travel_minutes = max(1, math.ceil(before * 0.85))
        if travel_minutes and before > travel_minutes:
            notes.append(f"逐日仙辇护持，行程缩短 {before - travel_minutes} 分钟。")
    elif protected:
        before = travel_minutes
        if barrier:
            travel_minutes = max(1, math.ceil(before * 0.8))
        else:
            reduction = 5 + math.floor(min(max(float(rng.random()), 0.0), 1.0 - math.ulp(1.0)) * 6)
            travel_minutes = max(1, before - reduction)
        if before > travel_minutes:
            notes.append(f"虚天舟护持，行程缩短 {before - travel_minutes} 分钟。")
    else:
        state = (getattr(doc, "ext", {}) or {}).get("xtzb", {})
        try:
            passenger_until = float(state.get("ship_passenger", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            passenger_until = 0.0
        if passenger_until > now:
            before = travel_minutes
            travel_minutes = max(1, math.ceil(before * 0.6))
            notes.append(f"虚天舟乘员同行，行程缩短 {before - travel_minutes} 分钟。")
    return travel_minutes, notes, protected, multiplier


def token_accident_chance(doc: PlayerDoc, tier: str) -> float:
    reduction = plane_mod.realm_reduce(doc)
    return max(0.0, TOKEN_ACCIDENT_BASE[tier]
               - reduction * (TOKEN_ACCIDENT_REALM_REDUCE / plane_mod.REDUCE_MAX))


def token_travel_minutes(doc: PlayerDoc, src: str, target: str, tier: str,
                         kunpeng_minutes: float = 0.0) -> int:
    """Original token travel speed; dimension barriers use the shared barrier quote."""
    if _barrier_count(src, target) > 0:
        return int(plane_mod.quote(doc, target)["minutes"])
    source_level = plane_mod.ORIGINAL_TRAVEL_LEVELS.get(src, plane_mod.LEVELS.get(src, 0))
    target_level = plane_mod.ORIGINAL_TRAVEL_LEVELS.get(target, plane_mod.LEVELS.get(target, 0))
    distance = abs(float(source_level) - float(target_level))
    if distance <= 0:
        return 0
    reduction = plane_mod.realm_reduce(doc)
    raw = distance * TOKEN_BASE_MINUTES[tier] * (1 - reduction)
    return max(1, math.floor(raw + 0.5))


def _begin_token_travel(doc: PlayerDoc, st: dict[str, Any], target: str,
                        now: float, rng: Any) -> tuple[bool, str]:
    src = plane_mod.current(st)
    uses = st.setdefault("portal_uses", {"low": 0, "high": 0})
    tier = "high" if int(uses.get("high", 0) or 0) > 0 else "low"
    if int(uses.get(tier, 0) or 0) <= 0:
        return False, "你没有可消耗的位面传送次数。"
    if target in SPECIAL_PLANES:
        return False, f"「{target}」属于特殊位面，须使用 #穿梭 {target} 横渡。"
    if not plane_mod.has_coordinate(doc, target):
        return False, f"你尚未记下「{target}」的坐标——先 #记坐标 {target}。"
    marks = st.get("marks")
    if not isinstance(marks, Mapping) or target not in marks:
        return False, f"传送阵上尚未刻画「{target}」坐标——先 #刻画坐标 {target}。"
    q = plane_mod.quote(doc, target)
    if not q.get("enough_base", True):
        return False, "【肉身横渡·承载不足】普通穿梭要求练气和炼体都达到地仙阶段。"
    if getattr(doc, "state", "空闲") != "空闲":
        return False, f"你正在「{doc.state}」中，无法启动位面传送阵。"

    accident = rng.random() < token_accident_chance(doc, tier)
    minutes = token_travel_minutes(doc, src, target, tier)
    if accident:
        minutes += math.ceil(minutes * 0.5)
    minutes, travel_notes, travel_protected, multiplier = apply_travel_time_modifiers(
        doc, st, minutes, now, rng, src, target)
    uses[tier] = int(uses.get(tier, 0) or 0) - 1
    st["travel"] = {
        "from": src, "to": target, "depart": float(now),
        "arrive": float(now) + minutes * 60, "minutes": minutes,
        "time_multiplier": multiplier, "used_token": True,
        "token_tier": tier, "accident": accident,
        "tianwai_wind": any("天外清风" in line for line in travel_notes),
        "travel_protected": travel_protected,
    }
    doc.state = "穿梭中"
    doc.state_start = float(now)
    tier_name = "高级传送阵" if tier == "high" else "位面传送阵"
    note = "星路震荡，虚空乱流使航程延长。" if accident else "星路平稳，时空法则有序流转。"
    extra = ("\n" + "\n".join(travel_notes)) if travel_notes else ""
    return True, (f"【{tier_name}·横渡星域】阵纹交织出星空古路，预计 {minutes} 分钟后抵达「{target}」。\n"
                  f"{note}本次消耗一次传送次数（剩余 {uses[tier]} 次）；抵达后发送「#抵达」落位。"
                  f"{extra}")


def portal_use(doc: PlayerDoc, st: dict[str, Any], target: str,
               inv: Mapping[str, int], now: float, rng: Any,
               destroyed: Mapping | None = None,
               ) -> tuple[bool, str, dict[str, int]]:
    """消耗一次已激活传送次数；传送阵道具须先经 #使用 转为次数。"""
    target = (target or "").strip()
    if target not in plane_mod.LEVELS:
        return False, f"没有「{target}」这个位面。", {}
    ok, why = plane_mod.barrier_check(doc, plane_mod.current(st), target, destroyed)
    if not ok:
        return False, why, {}
    ok, message = _begin_token_travel(doc, st, target, now, rng)
    return ok, message, {}
