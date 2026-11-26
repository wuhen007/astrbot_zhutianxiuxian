"""魔头禁术（对齐原版 model/forbiddenSoul.js，PvP 平衡版）。

- 镇魂资格：魔道值 ≥100（邪道身份）+ 双方气血 >0 + 攻击方境界 ≥30 + **境界差保护**（对方低你 >8 境拒绝）
  + **7 天受镇魂保护期** + 24h 冷却 + 消耗魔道值 30
- 处置三选一（10 分钟窗口）：烙印（对方魂印 3 天、闭关效率 -30%，你得魂奴+10% 三维）/ 灭魂（得遗蜕）/
  夺果（对方需境界 ≥40，你得道果可炼化修为+潜力）
- 魂印可花代价提前冲击解除（12h 冷却）
- 魔功：魔道值换永久三维加成（每级递增消耗）；供奉魔石：魔石→魔道值
- 吞天本源、万相魔冢、天魔化生灾厄炼化及原版星阁献祭领域规则
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any, Mapping

MIN_MODAO = 100           # 邪道身份门槛
MIN_REALM = 30            # 斩道王者级（映射）
REALM_GAP_PROTECT = 8     # 目标低你超过 8 境 → 天道弱者保护
COOLDOWN = 24 * 3600
PROTECTION = 7 * 86400
BRAND_DURATION = 3 * 86400
DISPOSITION_TTL = 10 * 60
BREAK_CD = 12 * 3600
SLAY_MODAO_COST = 30
GUO_MIN_REALM = 40

MAGIC_COST = 80           # 魔功每级消耗魔道值（递增 ×1.5）
MAGIC_ATK_PCT = 0.08      # 每级三维 +8%
MAGIC_MAX = 10

MOSHI_MODAO = 20          # 每颗魔石供奉得魔道值
XIANJI_COST = 8
XIANJI_DIVINE_ROOT_COST = 1
TIANMO_CALAMITY_WEIGHT = 0.1

# 原版 motou.js / 灵根列表.json：魔根晋级与转世静态表。
MAGIC_ROOTS = (
    {"id": 100991, "name": "一重魔功", "type": "魔头", "eff": 0.36, "orb": 0.23, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 2, "awaken": 0},
    {"id": 100992, "name": "二重魔功", "type": "魔头", "eff": 0.42, "orb": 0.27, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 3, "awaken": 0},
    {"id": 100993, "name": "三重魔功", "type": "魔头", "eff": 0.48, "orb": 0.31, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 4, "awaken": 0},
    {"id": 100994, "name": "四重魔功", "type": "魔头", "eff": 0.54, "orb": 0.36, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 5, "awaken": 0},
    {"id": 100995, "name": "五重魔功", "type": "魔头", "eff": 0.60, "orb": 0.40, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 6, "awaken": 0},
    {"id": 100996, "name": "六重魔功", "type": "魔头", "eff": 0.66, "orb": 0.43, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 7, "awaken": 0},
    {"id": 100997, "name": "七重魔功", "type": "魔头", "eff": 0.72, "orb": 0.47, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 8, "awaken": 0},
    {"id": 100998, "name": "八重魔功", "type": "魔头", "eff": 0.78, "orb": 0.50, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 9, "awaken": 0},
    {"id": 100999, "name": "九重魔功", "type": "魔头", "eff": 1.20, "orb": 1.20, "atk": 0, "def": 0, "hp": 0, "origin": 0, "rarity": 10, "awaken": 0},
)
MAGIC_ROOT_COSTS = (20, 30, 30, 40, 40, 40, 50, 50)
MAGIC_ROOT_CHANCES = (0.90, 0.70, 0.60, 0.50, 0.40, 0.30, 0.25, 0.20)
MAGIC_ROOT_REINCARNATION_COST = 10

TUNTIAN_TECHNIQUE = "吞天魔功"
TUNTIAN_SOURCE_TARGET = 10
TUNTIAN_REMAINS_COOLDOWN = 24 * 3600
TUNTIAN_REMAINS_CHANCE = 0.40
TUNTIAN_HOLY_LANDS = ("摇光圣地", "姬家", "姜家", "瑶池圣地", "紫府圣地", "万初圣地")
TUNTIAN_ROOTS = frozenset(("伪·魔胎仙体", "魔胎仙体"))
TUNTIAN_CHAOS_ROOT = {
    "id": 70051, "name": "混沌体", "type": "混沌体", "category": "遮天位面",
    "eff": 72, "orb": 1.45, "atk": 5, "def": 5, "hp": 5, "origin": 200,
    "rarity": 8, "awaken": 0,
}

TIANMO_TECHNIQUE = "天魔化生功"
JIDAO_TIANMO = "极道天魔"
WANHUA_TIANMO = "无相·万化天魔体"
TIANMO_ORB_GAIN = 0.1
TIANMO_ATTRIBUTE_GAIN = 0.05
TIANMO_ORB_TARGET = 5.0
TIANMO_SAME_TARGET_COOLDOWN = 7 * 86400
TIANMO_WANHUA_ROOT = {
    "id": 7010020, "name": WANHUA_TIANMO, "type": "天魔", "category": "神魔",
    "eff": 5, "orb": 5, "atk": 8, "def": 3.5, "hp": 8, "origin": 500,
    "rarity": 8, "awaken": 0,
}
TIANMO_ROOT_TEMPLATES = {
    JIDAO_TIANMO: {"orb": 2, "atk": 3, "def": 2, "hp": 2, "origin": 150},
    WANHUA_TIANMO: {"orb": 5, "atk": 8, "def": 3.5, "hp": 8, "origin": 500},
}
TIANMO_TRANSFER_RULES = (
    ("仙道潜力", "potential", 0.2, 0),
    ("修为", "exp", 0.2, 0),
    ("血气", "xueqi", 0.2, 0),
    ("寿元", "shouyuan", 0.1, 1),
    ("生命本源", "life_source", 0.2, 1),
)


def state_of(doc: Mapping) -> dict:
    s = doc.ext.get("evil") if isinstance(doc.ext, Mapping) else None
    s = copy.deepcopy(s) if isinstance(s, dict) else {}
    s.setdefault("modao", float(doc.ext.get("modao", 0) or 0) if isinstance(doc.ext, Mapping) else 0.0)
    s.setdefault("magic", 0)
    s.setdefault("soul_slave", None)   # {"name":..., "until": ts}
    s.setdefault("remains", None)      # 待炼遗蜕
    s.setdefault("guo", None)          # 待炼道果
    s.setdefault("brand", None)        # 自身魂印 {"until": ts}
    s.setdefault("protected_until", 0.0)
    s.setdefault("slay_ts", 0.0)
    s.setdefault("pending", None)      # 待处置战果 {"target":..., "ts":..., "win":bool}
    s.setdefault("break_ts", 0.0)
    s.setdefault("tuntian", {})
    s.setdefault("tianmo", {})
    return s


def is_magic_root(root: Mapping | None) -> bool:
    return isinstance(root, Mapping) and str(root.get("type") or "") in ("魔头", "天魔")


def advance_magic_root(root: Mapping, stones: int, rng: Any) -> tuple[bool, str, dict, int]:
    name = str((root or {}).get("name") or "")
    index = next((i for i, row in enumerate(MAGIC_ROOTS) if row["name"] == name), -1)
    if index < 0:
        return False, "当前灵根不是可晋级的魔功灵根。", dict(root or {}), 0
    if index >= len(MAGIC_ROOT_COSTS):
        return False, "九重魔功已圆满。", dict(root), 0
    cost = MAGIC_ROOT_COSTS[index]
    if int(stones or 0) < cost:
        return False, f"魔石不足{cost}个,当前魔石数量{int(stones or 0)}个", dict(root), 0
    if rng.random() >= MAGIC_ROOT_CHANCES[index]:
        return False, "灵根突破失败", dict(root), cost
    next_root = copy.deepcopy(MAGIC_ROOTS[index + 1])
    return True, f"恭喜你,灵根突破成功,当前灵根{next_root['name']}!", next_root, cost


def reincarnate_magic_root(root: Mapping, modao: float, stones: int) -> tuple[bool, str, dict, int]:
    if is_magic_root(root):
        return False, "你已身负魔根，无需转世魔根。", dict(root or {}), 0
    if float(modao or 0) < 1000:
        return False, "魔道值不足1000，尚不能转世魔根。", dict(root or {}), 0
    if int(stones or 0) < MAGIC_ROOT_REINCARNATION_COST:
        return False, "你魔石不足10个", dict(root or {}), 0
    return True, "恭喜你,转世魔头成功!", copy.deepcopy(MAGIC_ROOTS[0]), MAGIC_ROOT_REINCARNATION_COST


def _tuntian_state(s: dict) -> dict:
    state = s.get("tuntian")
    if not isinstance(state, dict):
        state = s["tuntian"] = {}
    state["count"] = min(TUNTIAN_SOURCE_TARGET, max(0, int(state.get("count", 0) or 0)))
    state["last_remains"] = max(0.0, float(state.get("last_remains", 0) or 0))
    state["records"] = list(state.get("records") or [])[-10:]
    return state


def tuntian_eligibility(s: dict, doc: Any) -> str:
    root = doc.ext.get("linggen") if isinstance(doc.ext, Mapping) else {}
    if str((root or {}).get("name") or "") == TUNTIAN_CHAOS_ROOT["name"]:
        return "【吞天魔功】万般本源归一，你已蜕变为【混沌体】。"
    techniques = doc.ext.get("gongfa", []) if isinstance(doc.ext, Mapping) else []
    if TUNTIAN_TECHNIQUE not in techniques:
        return "你尚未学会【吞天魔功】。"
    if str((root or {}).get("name") or "") not in TUNTIAN_ROOTS:
        return "唯有魔胎仙体能够承载吞天本源。"
    return ""


def tuntian_status(s: dict, doc: Any, now: float) -> str:
    gate = tuntian_eligibility(s, doc)
    if gate:
        return gate
    state = _tuntian_state(s)
    wait = state["last_remains"] + TUNTIAN_REMAINS_COOLDOWN - now
    remains = f"祖陵潜入冷却：{int((wait + 3599) // 3600)}小时" if wait > 0 else "祖陵潜入：可行动"
    root = doc.ext.get("linggen") or {}
    return "\n".join((
        "【吞天魔功·本源之路】",
        f"当前体质：{root.get('name', '?')}",
        f"吞天本源：{state['count']}/{TUNTIAN_SOURCE_TARGET}",
        f"魔道值：{int(float(s.get('modao', 0) or 0))}",
        remains,
        "本源来源：#吞噬遗骸 [圣地]，或彻底击杀位面天骄。",
    ))


def absorb_tuntian_source(s: dict, doc: Any, source_type: str, target: str,
                           now: float) -> tuple[bool, str, bool]:
    gate = tuntian_eligibility(s, doc)
    if gate:
        return False, gate, False
    state = _tuntian_state(s)
    if state["count"] >= TUNTIAN_SOURCE_TARGET:
        return False, "吞天本源已经圆满。", False
    state["count"] += 1
    state["records"].append({"type": source_type, "target": target, "at": now})
    state["records"] = state["records"][-10:]
    s["modao"] = max(0.0, float(s.get("modao", 0) or 0)) + 20
    evolved = state["count"] >= TUNTIAN_SOURCE_TARGET
    if evolved:
        old = doc.ext.get("linggen") or {}
        root = copy.deepcopy(TUNTIAN_CHAOS_ROOT)
        for key in ("eff", "orb", "atk", "def", "hp", "origin"):
            try:
                root[key] = max(float(root[key]), float(old.get(key, 0) or 0))
            except (TypeError, ValueError):
                pass
        doc.ext["linggen"] = root
        state["evolved"] = True
        state["evolved_at"] = now
    return True, f"吞天本源：{state['count']}/{TUNTIAN_SOURCE_TARGET}｜魔道值 +20", evolved


def attempt_tuntian_remains(s: dict, doc: Any, holy_land: str | None,
                             now: float, rng: Any) -> dict:
    gate = tuntian_eligibility(s, doc)
    if gate:
        return {"attempted": False, "success": False, "message": gate}
    if holy_land and holy_land not in TUNTIAN_HOLY_LANDS:
        return {"attempted": False, "success": False,
                "message": f"可潜入的圣地：{'、'.join(TUNTIAN_HOLY_LANDS)}"}
    state = _tuntian_state(s)
    wait = state["last_remains"] + TUNTIAN_REMAINS_COOLDOWN - now
    if wait > 0:
        return {"attempted": False, "success": False,
                "message": f"今日已经潜入过圣地祖陵，还需{int((wait + 3599) // 3600)}小时"}
    holy_land = holy_land or rng.choice(TUNTIAN_HOLY_LANDS)
    state["last_remains"] = now
    if rng.random() >= TUNTIAN_REMAINS_CHANCE:
        return {"attempted": True, "success": False, "holy_land": holy_land,
                "message": f"【{holy_land}·祖陵惊变】圣地守陵阵纹骤然复苏，你只得斩断气机退走。"}
    ok, message, evolved = absorb_tuntian_source(
        s, doc, "先贤遗骸", f"{holy_land}先贤遗骸", now)
    return {"attempted": True, "success": ok, "holy_land": holy_land,
            "message": message, "evolved": evolved,
            "count": _tuntian_state(s)["count"], "target": TUNTIAN_SOURCE_TARGET}


def is_tianmo_physique(doc: Any) -> bool:
    root = doc.ext.get("linggen") if isinstance(doc.ext, Mapping) else {}
    return str((root or {}).get("name") or "") in TIANMO_ROOT_TEMPLATES


def has_tianmo_technique(doc: Any) -> bool:
    techniques = doc.ext.get("gongfa", []) if isinstance(doc.ext, Mapping) else []
    return TIANMO_TECHNIQUE in techniques


def tianmo_status(s: dict, doc: Any) -> str:
    if not is_tianmo_physique(doc):
        return "你的根骨无法承载天魔化生之道。"
    if not has_tianmo_technique(doc):
        return "你尚未获得【天魔化生功】传承，需等待万相魔冢现世。"
    root = doc.ext.get("linggen") or {}
    state = s.get("tianmo") if isinstance(s.get("tianmo"), dict) else {}
    orb = float(root.get("orb", 0) or 0)
    remaining = max(0, int((TIANMO_ORB_TARGET - orb + TIANMO_ORB_GAIN - 1e-9) // TIANMO_ORB_GAIN))
    from . import life_source
    return "\n".join((
        f"【{TIANMO_TECHNIQUE}】",
        f"当前体质：{root.get('name', '?')}",
        f"法球倍率：{orb * 100:.0f}% / 500%",
        f"攻防生：{root.get('atk', 0)} / {root.get('def', 0)} / {root.get('hp', 0)}",
        f"当前生命本源：{life_source.current(doc):g}/{life_source.maximum(doc):g}",
        f"已炼化：{float(state.get('count', 0) or 0):g}人",
        f"距离蜕变：{'还需' + str(remaining) + '次' if remaining else '已成' + WANHUA_TIANMO}",
    ))


def can_refine_tianmo(s: dict, attacker: Any, target: Any,
                       target_s: dict, now: float) -> tuple[bool, str]:
    if not is_tianmo_physique(attacker):
        return False, "只有【极道天魔】一脉能够施展天魔化生功。"
    if not has_tianmo_technique(attacker):
        return False, "你尚未获得【天魔化生功】传承。"
    a_realm, t_realm = int(attacker.realm_index), int(target.realm_index)
    if (a_realm > 41 and t_realm <= 41) or (a_realm >= 12 and t_realm < 12):
        return False, "天魔亦有傲骨，不可炼化境界相差过大的弱小修士。"
    protected_until = float(target_s.get("protected_until", 0) or 0)
    if now < protected_until:
        days = int((protected_until - now) / 86400) + 1
        return False, f"目标仍受禁忌侵害保护（约 {days} 天）。"
    last = float(s.get("slay_ts", 0) or 0)
    if now - last < COOLDOWN:
        remain = int((COOLDOWN - (now - last)) / 3600) + 1
        return False, f"禁术因果尚未消散，还需 {remain} 小时。"
    state = s.get("tianmo") if isinstance(s.get("tianmo"), dict) else {}
    target_ts = float((state.get("targets") or {}).get(str(target.uid), 0) or 0)
    wait = target_ts + TIANMO_SAME_TARGET_COOLDOWN - now
    if wait > 0:
        return False, f"此人的本源烙印尚未恢复，还需{int((wait + 3599) // 3600)}小时。"
    return True, ""


def record_tianmo_failure(s: dict, now: float) -> None:
    s["slay_ts"] = now


def _drain_resource(value: Any, rate: float, reserve: int) -> int:
    try:
        available = max(0, int(float(value or 0)) - reserve)
    except (TypeError, ValueError):
        available = 0
    return min(available, max(1, int(available * rate))) if available else 0


def _set_lifespan(doc: Any, value: int) -> None:
    hidden = "jueling_suppressed_lifespan"
    value = max(0, int(value))
    if hidden in doc.ext:
        doc.ext[hidden] = value
        doc.ext["shouyuan"] = min(value, 9_999)
    else:
        doc.ext["shouyuan"] = value


def _round_growth(value: float) -> float:
    return math.floor(float(value) * 1000 + 0.5) / 1000


def _grow_tianmo_root(doc: Any, weight: float = 1.0) -> bool:
    root = dict(doc.ext.get("linggen") or {})
    name = str(root.get("name") or "")
    template = TIANMO_ROOT_TEMPLATES.get(name)
    if not template:
        return False
    weight = max(0.0, float(weight))
    root["orb"] = min(TIANMO_ORB_TARGET,
                      _round_growth(float(root.get("orb", 0) or 0) + TIANMO_ORB_GAIN * weight))
    for key in ("atk", "def", "hp"):
        current = max(0.0, float(root.get(key, 0) or 0))
        cap = template[key] * 1.5
        root[key] = _round_growth(min(current + TIANMO_ATTRIBUTE_GAIN * weight, max(current, cap)))
    if root["orb"] >= TIANMO_ORB_TARGET and name != WANHUA_TIANMO:
        old_origin = max(0.0, float(root.get("origin", 0) or 0))
        from . import life_source
        current_life_source = life_source.current(doc)
        doc.ext["linggen"] = copy.deepcopy(TIANMO_WANHUA_ROOT)
        origin_gain = max(0.0, float(TIANMO_WANHUA_ROOT["origin"]) - old_origin)
        life_source.set_current(doc, current_life_source + origin_gain)
        return True
    doc.ext["linggen"] = root
    return False


def apply_tianmo_refinement(s: dict, attacker: Any, target_s: dict,
                             target: Any, now: float) -> tuple[dict[str, int], bool]:
    gains: dict[str, int] = {}
    for label, key, rate, reserve in TIANMO_TRANSFER_RULES:
        if key == "exp":
            value = target.exp
        elif key in {"potential", "xueqi", "shouyuan"}:
            fallback = (int(target.realm_index) + 1) * 500 if key == "shouyuan" else 0
            value = target.ext.get(key, fallback)
        else:
            from . import life_source
            value = life_source.current(target)
        gains[label] = _drain_resource(value, rate, reserve)
    drained = dict(gains)
    for label, key, _rate, _reserve in TIANMO_TRANSFER_RULES:
        amount = drained[label]
        if key == "exp":
            target.exp = max(0, int(target.exp) - amount)
            attacker.exp = int(attacker.exp) + amount
        elif key == "potential" or key == "xueqi":
            target.ext[key] = max(0.0, float(target.ext.get(key, 0) or 0) - amount)
            attacker.ext[key] = max(0.0, float(attacker.ext.get(key, 0) or 0)) + amount
        elif key == "life_source":
            from . import life_source
            target_before = life_source.current(target)
            life_source.set_current(target, max(0.0, target_before - amount))
            credited = amount
            if is_tianmo_physique(attacker):
                root_name = str((attacker.ext.get("linggen") or {}).get("name") or "")
                root_cap = float(TIANMO_ROOT_TEMPLATES.get(root_name, {}).get("origin", 0) or 0) * 2
                attacker_before = life_source.current(attacker)
                credited = max(0.0, min(float(amount), root_cap - attacker_before))
            life_source.set_current(attacker, life_source.current(attacker) + credited)
            gains[label] = int(credited)
        else:
            _set_lifespan(target, int(target.ext.get("shouyuan", 0) or 0) - amount)
            _set_lifespan(attacker, int(attacker.ext.get("shouyuan", (int(attacker.realm_index) + 1) * 500) or 0) + amount)
    state = s.get("tianmo")
    if not isinstance(state, dict):
        state = s["tianmo"] = {}
    state["count"] = round(float(state.get("count", 0) or 0) + 1, 3)
    cumulative = state.get("cumulative") if isinstance(state.get("cumulative"), dict) else {}
    state["cumulative"] = cumulative
    for label, amount in gains.items():
        cumulative[label] = int(cumulative.get(label, 0) or 0) + amount
    state.setdefault("targets", {})[str(target.uid)] = now
    s["slay_ts"] = now
    target_s["protected_until"] = now + PROTECTION
    target.ext["hp"] = 0
    evolved = _grow_tianmo_root(attacker)
    return gains, evolved



def calamity_refinement_resource_gains(doc: Any) -> dict[str, int]:
    """Original calamity refinement rewards: current exp/blood 2%, spirit 1%."""
    from . import yuanshen, wallet

    spirit = int(yuanshen.ensure(doc).get("cur", 0) or 0)
    return {
        "cultivation": max(1, int(max(0, int(getattr(doc, "exp", 0) or 0)) * 0.02)),
        "blood": max(1, int(wallet.xueqi(doc) * 0.02)),
        "spirit": max(1, int(spirit * 0.01)),
    }

def apply_tianmo_calamity_refinement(s: dict, executor: Any, source_life_source: Any,
                                     weight: float = TIANMO_CALAMITY_WEIGHT,
                                     now: float | None = None) -> dict[str, Any]:
    """Apply the original calamity/Boss life-source harvest and weighted growth.

    The caller owns the pending-source claim and persists this player mutation
    atomically with that claim. The Boss is not represented as a fake player.
    """
    now = time.time() if now is None else float(now)
    ext = getattr(executor, "ext", {}) or {}
    zhutian = ext.get("zhutian") if isinstance(ext, Mapping) else None
    avatar = str((zhutian or {}).get("current") or "") if isinstance(zhutian, Mapping) else ""
    if avatar:
        return {"applied": False, "reason": "avatar_loaded", "avatar": avatar}
    if not is_tianmo_physique(executor) or not has_tianmo_technique(executor):
        return {"applied": False, "reason": "tianmo_required"}
    try:
        weight = max(0.0, float(weight))
        source = max(1, int(float(source_life_source or 100)))
    except (TypeError, ValueError, OverflowError):
        weight, source = TIANMO_CALAMITY_WEIGHT, 100
    available = max(0, source - 1)
    drained = min(available, max(1, int(available * 0.2))) if available else 0
    raw_gain = _round_growth(drained * weight)
    root_name = str((ext.get("linggen") or {}).get("name") or "") if isinstance(ext, Mapping) else ""
    root_cap = float(TIANMO_ROOT_TEMPLATES.get(root_name, {}).get("origin", 0) or 0) * 2
    from . import life_source
    before = life_source.current(executor)
    credited = raw_gain if root_cap <= 0 else min(raw_gain, max(0.0, root_cap - before))
    life_source.set_current(executor, before + credited)

    tianmo = s.get("tianmo") if isinstance(s.get("tianmo"), dict) else {}
    s["tianmo"] = tianmo
    tianmo["count"] = _round_growth(float(tianmo.get("count", 0) or 0) + weight)
    tianmo["disaster_refinements"] = max(0, int(tianmo.get("disaster_refinements", 0) or 0)) + 1
    cumulative = tianmo.get("cumulative") if isinstance(tianmo.get("cumulative"), dict) else {}
    tianmo["cumulative"] = cumulative
    cumulative["生命本源"] = _round_growth(float(cumulative.get("生命本源", 0) or 0) + credited)
    evolved = _grow_tianmo_root(executor, weight)
    root = executor.ext.get("linggen") or {}
    cap = float(TIANMO_ROOT_TEMPLATES.get(str(root.get("name") or ""), {}).get("origin", 0) or 0) * 2
    return {
        "applied": True,
        "life_source_gain": _round_growth(credited),
        "raw_life_source_gain": raw_gain,
        "weight": weight,
        "evolved": evolved,
        "life_source_capped": bool(cap and life_source.current(executor) >= cap),
        "refinement_count": tianmo["count"],
    }


def sacrifice_magic_stones(doc: Any, inventory: Mapping[str, int], reward_pool: Any,
                           times: int, rng: Any) -> dict[str, Any]:
    """Plan #献祭魔石 from the original shared xingge pool; caller commits costs/rewards."""
    try:
        times = int(times)
    except (TypeError, ValueError, OverflowError):
        times = 0
    if times <= 0:
        return {"ok": False, "reason": "times", "cost": 0, "rewards": {}}
    root = (getattr(doc, "ext", {}) or {}).get("linggen") or {}
    root_type = str(root.get("type") or "")
    divine_root = root_type == "神慧者"
    state = state_of(doc)
    if not divine_root and float(state.get("modao", 0) or 0) < MIN_MODAO and root_type not in {"魔头", "天魔"}:
        return {"ok": False, "reason": "not_magic", "cost": 0, "rewards": {}}
    cost = times * (XIANJI_DIVINE_ROOT_COST if divine_root else XIANJI_COST)
    try:
        stones = max(0, int((inventory or {}).get("魔石", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        stones = 0
    if stones < cost:
        return {"ok": False, "reason": "stones", "cost": cost, "stones": stones, "rewards": {}}
    rows = [row for row in (reward_pool or ())
            if isinstance(row, Mapping) and row.get("name") and row.get("class")]
    if not rows:
        return {"ok": False, "reason": "empty_pool", "cost": 0, "rewards": {}}
    rewards: dict[str, int] = {}
    for _ in range(times):
        item = rows[rng.randrange(len(rows))]
        name = str(item["name"])
        rewards[name] = rewards.get(name, 0) + 1
    return {"ok": True, "reason": "", "cost": cost, "divine_root": divine_root,
            "rewards": rewards, "pool_count": len(rows)}


def magic_cost(level: int) -> int:
    return int(MAGIC_COST * (1.5 ** int(level)))


def magic_bonus(s: Mapping) -> float:
    return MAGIC_ATK_PCT * int(s.get("magic", 0))


def train_magic(s: dict) -> tuple[bool, str, dict]:
    lv = int(s.get("magic", 0))
    if lv >= MAGIC_MAX:
        return False, f"魔功已至第 {MAGIC_MAX} 层（魔气满盈，再练恐道消）。", s
    cost = magic_cost(lv)
    if float(s.get("modao", 0)) < cost:
        return False, f"魔道值不足：修至第 {lv + 1} 层需 {cost}（当前 {int(s['modao'])}）。", s
    s["modao"] = float(s["modao"]) - cost
    s["magic"] = lv + 1
    return True, (f"魔功精进至第 {lv + 1} 层！三维永久 +{MAGIC_ATK_PCT:.0%}×{lv + 1}"
                  f"（累计 +{MAGIC_ATK_PCT * (lv + 1):.0%}，魔道值 -{cost}）"), s


def offer_moshi(s: dict, qty: int) -> tuple[bool, str, dict]:
    qty = max(1, int(qty))
    gain = MOSHI_MODAO * qty
    s["modao"] = float(s["modao"]) + gain
    return True, f"魔石 ×{qty} 化作精纯魔气——魔道值 +{gain}（当前 {int(s['modao'])}）。", s


def can_slay(attacker_s: dict, atk_realm: int, hp: int,
             target_s: dict, tgt_realm: int, tgt_hp: int, now: float) -> tuple[bool, str]:
    if float(attacker_s.get("modao", 0)) < MIN_MODAO:
        return False, f"你尚未真正踏入邪道（魔道值需 ≥{MIN_MODAO}）。"
    if hp <= 0:
        return False, "你已身受重创，无力施展禁术。"
    if tgt_hp <= 0:
        return False, "目标真灵沉寂（气血为 0），无法镇魂。"
    if atk_realm < MIN_REALM:
        return False, f"境界不足：需 {MIN_REALM} 境（斩道王者级）。"
    if tgt_realm < atk_realm - REALM_GAP_PROTECT:
        return False, "目标境界低你太多，受天道弱者保护，禁术反噬。"
    if now < float(target_s.get("protected_until", 0.0)):
        days = int((float(target_s["protected_until"]) - now) / 86400) + 1
        return False, f"目标仍受禁忌侵害保护（约 {days} 天）。"
    if now - float(attacker_s.get("slay_ts", 0.0)) < COOLDOWN:
        remain = int((COOLDOWN - (now - float(attacker_s["slay_ts"]))) / 3600) + 1
        return False, f"禁术因果未消，还需 {remain} 小时。"
    if attacker_s.get("pending"):
        return False, "你有一份尚未处置的战果（#处置 烙印/灭魂/夺果）。"
    return True, ""


def record_result(s: dict, target_name: str, win: bool, now: float) -> dict:
    s["slay_ts"] = now
    s["modao"] = max(0.0, float(s["modao"]) - SLAY_MODAO_COST)
    if win:
        s["pending"] = {"target": target_name, "ts": now}
    return s


def dispose(s: dict, kind: str, target_s: dict, now: float,
            target_snapshot: dict | None = None, target_realm: int = 0) -> tuple[bool, str, dict, dict]:
    """处置战果。返回 (ok, msg, 自己档, 对方档变更)。

    W8-F6：新增两个可选参数，供人傀链写遗蜕快照 / 开放夺果；不传时保持 B5 旧行为。
    """
    p = s.get("pending")
    if not p:
        return False, "没有待处置的镇魂战果。", s, {}
    if now - float(p.get("ts", 0)) > DISPOSITION_TTL:
        s["pending"] = None
        return False, "战果已消散（超过 10 分钟未处置）。", s, {}
    tname = p.get("target", "?")
    if kind == "烙印":
        if s.get("soul_slave"):
            return False, "你已有尚未消散的魂奴。", s, {}
        if target_s.get("brand"):
            return False, "目标已有魂印。", s, {}
        s["soul_slave"] = {"name": tname, "until": now + BRAND_DURATION}
        s["pending"] = None
        return True, (f"你在{tname}的真灵上烙下魂印！\n"
                      f"{tname} 魂印缠身 3 天（闭关效率 -30%）；你获魂奴「{tname}」（三维 +10%，3 天）。"), s, {
            "brand": {"until": now + BRAND_DURATION, "by": "镇魂"},
            "protected_until": now + PROTECTION,
        }
    if kind == "灭魂":
        if s.get("remains"):
            return False, "你已有一具待炼遗蜕。", s, {}
        s["remains"] = {"name": tname, "ts": now, **(target_snapshot or {})}
        s["pending"] = None
        return True, (f"你斩灭{tname}一缕真灵，收得一具遗蜕（可「#炼化遗蜕」得修为，"
                      f"或「#炼制人傀」成傀）。"), s, {
            "protected_until": now + PROTECTION,
        }
    if kind == "夺果":
        if s.get("guo"):
            return False, "你已有一枚待炼道果，请先「#炼化道果」。", s, {}
        if int(target_realm) < GUO_MIN_REALM:
            return False, f"目标尚未凝成可剥取的高阶道果（需境界 ≥{GUO_MIN_REALM}）。", s, {}
        # W8-F6：原版取目标「自身之道类型/名称」，本移植无该体系 → 折算为目标名号
        s["guo"] = {"name": f"{tname}·道果", "way": "自身之道", "ts": now}
        s["pending"] = None
        return True, (f"你剥取{tname}一枚道果（「#炼化道果」可炼入外来道果槽）；"
                      f"对方道果裂痕 6 小时（全属性 -5%）。"), s, {
            "protected_until": now + PROTECTION,
            "crack_until": now + 6 * 3600,
        }
    return False, "可选处置：烙印 / 灭魂 / 夺果。", s, {}


def refine_remains(s: dict, realm_index: int) -> tuple[bool, str, dict, dict]:
    r = s.get("remains")
    if not r:
        return False, "没有待炼遗蜕。", s, {}
    gain = 20_000_000 * (max(1, realm_index) // 10 + 1)
    s["remains"] = None
    s["modao"] = float(s["modao"]) + 40
    return True, (f"炼化「{r['name']}」遗蜕：修为 +{gain:,}，魔道值 +40。"), s, {
        "exp": gain, "modao": 40,
    }


def break_brand(doc: Mapping, s: dict, now: float, stones: int) -> tuple[bool, str, dict]:
    b = s.get("brand")
    if not b:
        return False, "你身上没有魂印。", s
    if now - float(s.get("break_ts", 0.0)) < BREAK_CD:
        return False, "冲击魂印失败的后遗症未消，稍后再试。", s
    cost = 500_000
    if stones < cost:
        return False, f"冲击魂印需 {cost:,} 灵石（丹药/灵石护持）。", s
    s["brand"] = None
    s["break_ts"] = now
    return True, f"你以秘法冲击魂印，真灵震颤——魂印溃散！（灵石 -{cost:,}）", s


def brand_penalty(s: Mapping, now: float) -> float:
    """魂印在身时闭关效率惩罚（0.7 表示 -30%）。"""
    b = s.get("brand")
    if isinstance(b, dict) and now < float(b.get("until", 0)):
        return 0.7
    return 1.0


def slave_bonus(s: Mapping, now: float) -> float:
    """魂奴在侧的三维加成。"""
    sl = s.get("soul_slave")
    if isinstance(sl, dict) and now < float(sl.get("until", 0)):
        return 0.10
    return 0.0


def panel(s: Mapping, now: float) -> str:
    lines = [f"--- 邪道 · 魔头之路 ---",
             f"魔道值：{int(s.get('modao', 0))}｜魔功：第 {int(s.get('magic', 0))} 层（三维 +{magic_bonus(s):.0%}）"]
    brand = s.get("brand")
    if isinstance(brand, dict):
        left = int((float(brand.get("until", 0)) - now) / 3600) + 1
        lines.append(f"⚠ 魂印缠身：约 {left} 小时（闭关效率 -30%，#冲击魂印 可解）")
    slave = s.get("soul_slave")
    if isinstance(slave, dict):
        left = int((float(slave.get("until", 0)) - now) / 3600) + 1
        lines.append(f"魂奴：{slave.get('name')}（三维 +10%，约 {left} 小时）")
    if s.get("remains"):
        lines.append(f"待炼遗蜕：{s['remains'].get('name')}（#炼化遗蜕）")
    if s.get("pending"):
        lines.append("有待处置战果：#处置 烙印 / #处置 灭魂（10 分钟内）")
    lines.append(f"镇魂冷却：{'就绪' if now - float(s.get('slay_ts', 0)) >= COOLDOWN else '未消'}"
                 f"｜魔石供奉：#供奉魔石")
    lines.append("#镇魂 @目标（魔道 100+ / 境界 30+ / 无 7 天保护）｜#修炼魔功｜#冲击魂印")
    return "\n".join(lines)
