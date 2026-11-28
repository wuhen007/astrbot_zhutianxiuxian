"""Route-specific #破王成帝劫 state and combat helpers from the pinned source.

The source runs an asynchronous 30-shackle sequence. This port resolves that
sequence synchronously with its local combat/stat model; the route credential
and source-derived gates remain separate from ordinary Emperor proving.
"""
from __future__ import annotations

import math
import random
import time
from collections.abc import Mapping
from typing import Any

from . import extra_cultivation, life_source, worldline
from .wallet import set_xueqi, xueqi

ROUTES = {
    "mijing": {"realm": 19, "target": 20, "name": "人体秘境"},
    "xiangu": {"realm": 20, "target": 21, "name": "仙古今世法"},
    "huafen": {"realm": 20, "target": 21, "name": "花粉进化路"},
}
ERA_COST = (0.75, 0.8, 1.0, 2.0, 3.0)
KING_DAMAGE_RATIO = 320 / 150
REST_SECONDS = 24 * 3600
SHACKLES = 30

ROOT_REDUCTION = {
    "天生至尊": .25, "涅槃·至尊": .40, "终极涅槃·至尊": .65, "重瞳者": .50,
    "荒古圣体": .15, "小成·荒古圣体": .30, "大成·荒古圣体": .60,
    "苍天霸体": .20, "小成·苍天霸体": .35, "大成·苍天霸体": .55,
    "先天道胎": .10, "先天圣体道胎": .65, "混沌体": .45,
    "先天混沌圣体道胎": .80, "太阳之体": .08, "太阳神体": .25,
    "太阳圣皇体": .40, "太阴之体": .08, "太阴神体": .25,
    "太阴圣皇体": .40, "神王体": .12, "小成·神王体": .28,
    "大成·神王体": .45, "天妖体": .10, "天妖王体": .30,
    "天妖皇体": .50, "伪·魔胎仙体": .35, "魔胎仙体": .70,
    "命运神道体": .30, "极道天魔": .35, "终焉神魔体": .55,
    "彼岸·命运神道体": .75, "无相·万化天魔体": .75,
}
IMMORTAL_KINGS = (("昆谛", 1.0), ("安澜", .9), ("蒲魔王", 1.1), ("无殇", 1.3),
                  ("俞陀", 1.2), ("瞿忡", 1.4), ("刀王", 1.5), ("赤王", .8))


def route_of(doc: Any) -> str | None:
    return extra_cultivation.selected_track(doc)


def gate(doc: Any, now: float | None = None) -> tuple[bool, str, str | None]:
    now = time.time() if now is None else float(now)
    route = route_of(doc)
    if route not in ROUTES:
        return False, "请先明确选择人体秘境、仙古或花粉主修路线。", None
    cfg = ROUTES[route]
    if extra_cultivation.level_of(doc, route) != cfg["realm"]:
        return False, f"破王成帝劫需处于{cfg['name']}准仙帝前一境（第 {cfg['realm']} 境）。", route
    ext = getattr(doc, "ext", {}) or {}
    selfdao = ext.get("selfdao") if isinstance(ext.get("selfdao"), Mapping) else {}
    if not str(selfdao.get("system_name") or "").strip():
        return False, "需先圆满当前路线道则并使用 #合道 开创自创体系。", route
    system_route = str(selfdao.get("route") or "").strip()
    if system_route and system_route != route:
        return False, f"自创体系绑定「{system_route}」路线，不能用于「{route}」破王成帝劫。", route
    state = worldline.state_of(doc)
    if worldline.form_broken_of(doc):
        return False, "你已形神俱灭，需先由仙帝级修士发送 #重塑形神。", route
    if worldline.penalty_of(state.get("debt", 0)).get("suppress", 0) > 0:
        return False, "因果债造成的道果压制尚未解除，请先纪元消债。", route
    records = state.get("tribulations") if isinstance(state.get("tribulations"), dict) else {}
    record = records.get(route)
    if isinstance(record, Mapping) and record.get("status") == "passed":
        return False, "你已通过当前路线破王成帝劫，道果留有完整帝劫烙印。", route
    if isinstance(record, Mapping) and record.get("status") == "failed":
        last = float(record.get("lastAttemptAt", 0) or 0)
        try:
            from . import zhengdao
            raw_dao = (getattr(doc, "ext", {}) or {}).get(zhengdao.EXT_KEY)
            dao = zhengdao.state_of(doc, now)
            # Prefer the shared timestamp if it is actually persisted; #使用无上神物 clears it.
            if isinstance(raw_dao, Mapping) and "break_king_failed_at" in raw_dao:
                last = float(dao.get("break_king_failed_at", 0) or 0)
        except (ImportError, AttributeError, TypeError, ValueError):
            pass
        if last > 0 and now - last < REST_SECONDS:
            left = int(REST_SECONDS - (now - last))
            return False, f"帝劫余波未平，还需 {left // 3600} 小时 {left % 3600 // 60} 分钟。", route
    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), Mapping) else {}
    jiehai_count = int(ext.get("界海历练次数", legacy.get("界海历练次数", 0)) or 0)
    if jiehai_count < 10:
        return False, f"破王成帝劫需先完成界海历练 10 次（当前 {jiehai_count}/10）。", route
    if life_source.current(doc) < 50:
        return False, f"生命本源不足（当前 {life_source.current(doc):g}，需至少 50）。", route
    return True, "", route


def costs(doc: Any, era_index: int, now: float) -> tuple[int, int]:
    """Pinned formula 2^15×250,000 scaled to the port's 1/1000 resource unit."""
    from .mingge import signed_bonus
    rate = ERA_COST[max(0, min(len(ERA_COST) - 1, int(era_index)))]
    ext = getattr(doc, "ext", {}) or {}
    fortune = ext.get("red_dust_fortune")
    if not isinstance(fortune, Mapping):
        legacy = ext.get("legacy_source")
        fortune = legacy.get("红尘仙缘签") if isinstance(legacy, Mapping) else None
    discount = 1.0
    if isinstance(fortune, Mapping) and fortune.get("type") == "question":
        expires = float(fortune.get("expiresAt", fortune.get("expires_at", 0)) or 0)
        if expires > 1_000_000_000_000:
            expires /= 1000
        if expires > float(now):
            discount = .8
    blood_cost = max(1, int(math.ceil(8_192_000 * rate * discount)))
    cultivation_discount = min(.9, max(0.0, float(signed_bonus(doc, "证道修为减少") or 0)))
    exp_cost = max(1, int(math.ceil(blood_cost * (1 - cultivation_discount))))
    return exp_cost, blood_cost


def _damage_reduction(doc: Any) -> float:
    ext = getattr(doc, "ext", {}) or {}
    root = ext.get("linggen") if isinstance(ext.get("linggen"), Mapping) else {}
    reduction = float(ROOT_REDUCTION.get(str(root.get("name") or ""), 0.0))
    try:
        from . import memory, supreme, suiyun, xtzb, selfdao
        reduction = max(reduction, float(suiyun.trib_reduction(doc)),
                        float(supreme.trib_reduction(doc)), float(memory.effects(doc).get("trib", 0) or 0))
        reduction = min(.95, reduction + max(0.0, 1.0 - float(xtzb.guard_mult(doc))))
        reduction = min(.95, reduction + float(selfdao.deduction_bonus(doc).get("damage_reduction", 0) or 0))
    except Exception:
        pass
    return min(.95, max(0.0, reduction))


def damage(doc: Any, stats: Any, raw_damage: float, rng: random.Random) -> tuple[int, str]:
    """Apply source-backed passive reduction and active revival states at local scale."""
    ext = getattr(doc, "ext", {})
    maximum = max(1, int(stats.hp))
    current = max(1, int(ext.get("hp", maximum) or maximum))
    original = max(1.0, float(raw_damage))
    reduction = _damage_reduction(doc)
    value = original * (1 - reduction)
    effects = ext.get("tribulation_effects") if isinstance(ext.get("tribulation_effects"), dict) else {}
    log = [f"基础承压 {int(original):,}，护道减免 {reduction:.0%}。"] if reduction else []
    hp = current
    for name in ("者字秘", "真凰宝术", "柳神法", "如月长存", "雷帝宝术", "不灭经", "补天术", "万化圣诀", "涅槃仙功"):
        state = effects.get(name)
        if not isinstance(state, dict):
            continue
        if name == "者字秘" and int(state.get("remaining", 0) or 0) > 0:
            value *= 1 - float(state.get("reduction", .25) or .25)
            hp = min(maximum, hp + int(maximum * float(state.get("heal_ratio", .05) or .05)))
            state["remaining"] = int(state["remaining"]) - 1
        elif name in ("柳神法", "如月长存"):
            if int(state.get("layers", 0) or 0) > 0:
                value *= 1 - float(state.get("reduction", .45) or .45)
                state["layers"] = int(state["layers"]) - 1
            if int(state.get("regen_rounds", 0) or 0) > 0:
                hp = min(maximum, hp + int(maximum * float(state.get("regen_ratio", .15) or .15)))
                state["regen_rounds"] = int(state["regen_rounds"]) - 1
        elif name == "不灭经" and int(state.get("remaining", 0) or 0) > 0:
            value *= 1 - float(state.get("reduction", .4) or .4)
            hp = min(maximum, hp + int(maximum * float(state.get("heal_ratio", .3) or .3)))
            state["remaining"] = int(state["remaining"]) - 1
        elif name == "涅槃仙功" and int(state.get("remaining", 0) or 0) > 0:
            value *= 1 - float(state.get("reduction", .2) or .2)
            state["remaining"] = int(state.get("remaining")) - 1
    immune = False
    for name in ("真凰宝术", "万化圣诀"):
        state = effects.get(name)
        if isinstance(state, dict) and state.get("immune") and value >= hp:
            immune = True
            state["immune"] = False
            value = max(0, hp - 10_000)
    dealt = max(0, int(value * rng.uniform(.95, 1.05)))
    ext["tribulation_effects"] = effects
    ext["hp"] = max(0, hp - dealt)
    return dealt, ("、".join(log) + (" 复活免死发动。" if immune else ""))


def mark_passed(doc: Any, route: str, now: float) -> None:
    cfg = ROUTES[route]
    state = worldline.state_of(doc)
    records = state.setdefault("tribulations", {})
    prior = records.get(route) if isinstance(records.get(route), Mapping) else {}
    records[route] = {**dict(prior), "attempts": int(prior.get("attempts", 0) or 0) + 1,
                      "status": "passed", "lastAttemptAt": float(now), "passedAt": float(now)}
    extra_cultivation.set_level(doc, route, cfg["target"])
    if route == "xiangu":
        extra_cultivation.sync_xiangu_companion_mijing(doc)
    ext = getattr(doc, "ext", {})
    ext["break_king_route"] = route
    doc.exp = 0
    set_xueqi(doc, 0)
    ext["神明枷锁"] = 0
    ext["神明之光"] = 3
    history = list(state.get("history") or [])
    history.append({"type": "破王成帝劫", "result": "passed", "route": str(route), "at": float(now)})
    state["history"] = history[-worldline.MAX_HISTORY:]


def mark_failed(doc: Any, route: str, outcome: str, now: float) -> None:
    state = worldline.state_of(doc)
    records = state.setdefault("tribulations", {})
    prior = records.get(route) if isinstance(records.get(route), Mapping) else {}
    records[route] = {**dict(prior), "attempts": int(prior.get("attempts", 0) or 0) + 1,
                      "status": "failed", "lastAttemptAt": float(now), "outcome": str(outcome)}
    try:
        from . import zhengdao
        dao = zhengdao.state_of(doc, now)
        dao["last_prove_at"] = float(now)
        dao["break_king_failed_at"] = float(now)
        if outcome == "flaw":
            dao["dao_flaws"] = int(dao.get("dao_flaws", 0) or 0) + 1
        zhengdao.save(doc, dao)
    except (AttributeError, TypeError, ValueError):
        pass
    if outcome == "flaw":
        ext = getattr(doc, "ext", {})
        ext["dao_flaws"] = int(ext.get("dao_flaws", 0) or 0) + 1
        ext["hp"] = 1
    elif outcome == "severe":
        ext = getattr(doc, "ext", {})
        ext["soul_hurt"] = int(ext.get("soul_hurt", 0) or 0) + 1
        ext["hp"] = max(1, int(int(ext.get("hp_max", 1) or 1) * .05))
    else:
        state["form_broken"] = "破王成帝劫失败"
        ext = getattr(doc, "ext", {})
        ext["hp"] = 0
        doc.state = "形神俱灭"
        doc.state_start = float(now)
    history = list(state.get("history") or [])
    history.append({"type": "破王成帝劫", "result": str(outcome), "route": str(route), "at": float(now)})
    state["history"] = history[-worldline.MAX_HISTORY:]
