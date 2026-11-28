"""#造化万物：按固定原版承受力、耗时与领取规则创建静态物品。"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1
MAX_SQLITE_INTEGER = 2**63 - 1
BEARING_WARNING = 1_000_000
ANCESTOR_BACKLASH_CHANCE = 0.40
ACTION_KEY = "creation_everything"
ACTION_STATE = "造化万物中"
QUANTITY_THRESHOLDS = (10, 100, 300, 500, 700, 999)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label}不是有效数字。") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label}必须是有限的非负数。")
    return number


def quantity_multiplier(amount: int) -> int:
    count = int(amount)
    if count < 1 or count > MAX_SAFE_INTEGER:
        raise ValueError("造化数量须为正安全整数。")
    multiplier = 1
    for threshold in QUANTITY_THRESHOLDS:
        if count > threshold:
            multiplier *= 2
    if count > 1_200:
        multiplier *= 3
    return multiplier


def quote(authority_level: int, item: Mapping[str, Any] | None,
          sale_item: Mapping[str, Any] | None, amount: int) -> dict[str, int]:
    """Return the original per-item bearing cost and action/debt duration."""
    if not isinstance(item, Mapping) or not isinstance(sale_item, Mapping):
        raise ValueError("物品数据不存在或没有可读取的出售价。")
    if item.get("不可创造") or sale_item.get("不可创造"):
        raise ValueError(f"「{item.get('name') or '该物品'}」属于不可创造之物。")
    if int(authority_level) < 21:
        raise ValueError("造化万物需仙帝境界，权柄至少 21。")
    count = int(amount)
    multiplier = quantity_multiplier(count)
    try:
        rarity_value = Decimal(str(item.get("稀有度", 1) or 1))
    except (InvalidOperation, TypeError, ValueError):
        rarity_value = Decimal(1)
    if not rarity_value.is_finite():
        raise ValueError("物品稀有度必须是有限数字。")
    rarity = max(1, int(rarity_value.to_integral_value(rounding=ROUND_CEILING)))
    sale_price = _decimal(sale_item.get("出售价"), "物品出售价")
    rank = int(authority_level)
    if rank >= 23:
        cost_divisor, minutes_per_rarity = 0, 1
    elif rank >= 22:
        cost_divisor, minutes_per_rarity = 10_000, 3
    else:
        cost_divisor, minutes_per_rarity = 100, 5
    if cost_divisor:
        unit_cost = int((sale_price / cost_divisor).to_integral_value(rounding=ROUND_CEILING))
    else:
        unit_cost = 0
    total_cost = unit_cost * count
    minutes = rarity * minutes_per_rarity * multiplier
    if total_cost > MAX_SQLITE_INTEGER or minutes > MAX_SQLITE_INTEGER:
        raise ValueError("造化数量过大，无法安全登记本次行动。")
    return {"authority_level": rank, "rarity": rarity, "amount": count, "unit_bearing_cost": unit_cost,
            "bearing_cost": total_cost, "quantity_multiplier": multiplier,
            "minutes": minutes, "causal_debt": 0 if rank >= 23 else minutes}


def authority_level_of(doc: Any) -> int:
    """Use the highest mapped secret/ancient/flower realm, plus attained endgame ranks."""
    from . import extra_cultivation, ownway

    state = ownway.state_of(doc)
    level = extra_cultivation.realm_authority_level(doc)
    if state.get("unique"):
        return max(23, level)
    if state.get("jidao"):
        return max(22, level)
    return level


def authority_path_of(doc: Any) -> str:
    """Choose the highest extra route, honoring explicit choice and original tie priority."""
    from . import extra_cultivation

    ext = getattr(doc, "ext", {}) or {}
    selected = str(ext.get("extra_track") or ext.get("cultivation_path") or "")
    if selected in extra_cultivation.TRACKS:
        return selected
    if "花粉" in str(getattr(doc, "realm_table", "")):
        return "huafen"
    if "仙古" in str(getattr(doc, "realm_table", "")):
        return "xiangu"
    levels = {track: extra_cultivation.authority_level(doc, track)
              for track in extra_cultivation.TRACKS}
    highest = max(levels.values())
    if levels["huafen"] == highest:
        return "huafen"
    if levels["xiangu"] > levels["mijing"]:
        return "xiangu"
    return "mijing"

def parse_spec(value: str) -> tuple[str, int]:
    """Parse `物品名 [数量]` plus the common `物品名*数量` spelling."""
    text = str(value or "").strip()
    if not text or "@" in text:
        raise ValueError("格式：#造化万物 物品名 [数量]；不可指定其他玩家。")
    if "*" in text:
        name, raw_amount = text.rsplit("*", 1)
        name, raw_amount = name.strip(), raw_amount.strip()
        if not raw_amount.isdecimal():
            raise ValueError("造化数量须为正整数。")
        amount = int(raw_amount)
    else:
        parts = text.split()
        if parts[-1].isdecimal() and len(parts) > 1:
            name, amount = " ".join(parts[:-1]), int(parts[-1])
        else:
            name, amount = text, 1
    quantity_multiplier(amount)
    return name, amount


def action_of(doc: Any) -> dict[str, Any] | None:
    ext = getattr(doc, "ext", None)
    action = ext.get(ACTION_KEY) if isinstance(ext, dict) else None
    return dict(action) if isinstance(action, Mapping) else None


def begin(doc: Any, item_name: str, quote_result: Mapping[str, Any],
          now: float | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else float(now)
    if str(getattr(doc, "state", "空闲") or "空闲") != "空闲":
        return False, f"你正在「{doc.state}」中，无法开始造化万物。"
    if action_of(doc):
        return False, "已有一件造化万物行动，请先查看进度或领取完成的造物。"
    minutes = max(1, int(quote_result.get("minutes", 0) or 0))
    action = {
        "item": str(item_name), "amount": int(quote_result["amount"]),
        "rarity": int(quote_result["rarity"]),
        "authority_level": int(quote_result.get("authority_level", 0) or 0),
        "bearing_cost": int(quote_result["bearing_cost"]),
        "causal_debt": int(quote_result["causal_debt"]),
        "minutes": minutes, "started_at": now, "ends_at": now + minutes * 60,
    }
    if not isinstance(getattr(doc, "ext", None), dict):
        doc.ext = {}
    doc.ext[ACTION_KEY] = action
    doc.state = ACTION_STATE
    doc.state_start = now
    return True, (f"【造化万物·起炉】将造化「{action['item']}」×{action['amount']}，"
                  f"预计耗时 {minutes:,} 分钟；已预扣现世承受力 "
                  f"{action['bearing_cost']:,}。完成后再次发送「#造化万物」领取。")


def claim(doc: Any, now: float | None = None) -> dict[str, Any] | None:
    now = time.time() if now is None else float(now)
    action = action_of(doc)
    if not action or float(action.get("ends_at", 0) or 0) > now:
        return None
    doc.ext.pop(ACTION_KEY, None)
    if str(getattr(doc, "state", "") or "") == ACTION_STATE:
        doc.state = "空闲"
        doc.state_start = 0.0
    return action


def apply_ancestral_backlash(doc: Any, authority_level: int, bearing: int,
                             roll: float, now: float | None = None) -> bool:
    """Apply the original low-bearing Emperor one-track drop and emperor-state reset."""
    if int(authority_level) >= 22 or int(bearing) >= BEARING_WARNING or float(roll) >= ANCESTOR_BACKLASH_CHANCE:
        return False
    from . import extra_cultivation, ownway, selfdao, zhengdao

    track = authority_path_of(doc)
    levels = extra_cultivation.levels_of(doc)
    previous_authority = extra_cultivation.realm_authority_level(doc)
    extra_cultivation.set_level(doc, track, max(1, levels[track] - 1))
    next_authority = extra_cultivation.realm_authority_level(doc)
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["was_immortal_emperor"] = True
        ext["creation_everything_last_backlash"] = {
            "track": track, "at": float(time.time() if now is None else now)}
    if previous_authority >= 21 and next_authority < 21:
        dao = zhengdao.state_of(doc, now)
        dao.update({"reached": False, "emperor_title": "", "zhengdao_method": "",
                    "peak_realm": 0, "last_prove_at": 0.0,
                    "break_king_failed_at": 0.0})
        zhengdao.save(doc, dao)
        deduction = selfdao.state_of(doc)
        deduction["layers"] = 0
        deduction["terror_triggered"] = False
        deduction["death_until"] = 0.0
        selfdao.save(doc, deduction)
        own = ownway.state_of(doc)
        own["jidao"] = False
        own["unique"] = False
        own["seg"] = min(int(own.get("seg", 0) or 0), 430)
        ownway.save(doc, own)
    return True

def remaining_minutes(action: Mapping[str, Any], now: float | None = None) -> int:
    now = time.time() if now is None else float(now)
    seconds = max(0.0, float(action.get("ends_at", 0) or 0) - now)
    return max(0, math.ceil(seconds / 60))
