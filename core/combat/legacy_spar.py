"""旧版 apps/Battle/biwu.js 双方选技切磋状态与结算。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from ..battle import harm as original_harm

SKILL_NAMES = (
    "四象封印", "桃园结义", "长生诀", "祝水咒", "阴风蚀骨",
    "万年俱灰", "心烦意乱", "失魂落魄", "玄冰封印", "诛仙三剑",
)


# PORT_DESIGNED_VALUES: original data.jineng is absent from the published source/data.
# These are intentionally conservative values for the existing legacy effects.
PORT_DESIGNED_SKILLS: tuple[dict[str, Any], ...] = (
    {"name": "四象封印", "cd": 4, "pr": 0.0, "last": 1,
     "msg": "发动四象封印，下一次对手技能失效。"},
    {"name": "桃园结义", "cd": 5, "pr": 0.08, "last": 0,
     "msg": "施展桃园结义，双方气血各增 8%。"},
    {"name": "长生诀", "cd": 4, "pr": 0.12, "last": 0,
     "msg": "运转长生诀，回复自身上限气血的 12%。"},
    {"name": "祝水咒", "cd": 5, "pr": 0.05, "last": 3,
     "msg": "施展祝水咒，接下来 3 次行动各回复 5% 上限气血。"},
    {"name": "阴风蚀骨", "cd": 4, "pr": 0.08, "last": 3,
     "msg": "阴风蚀骨侵袭对手，接下来 3 次行动降低其攻击 8%。"},
    {"name": "万年俱灰", "cd": 6, "pr": 0.12, "last": 2,
     "msg": "万年俱灰压制对手，接下来 2 次行动降低其攻击 12%。"},
    {"name": "心烦意乱", "cd": 4, "pr": 0.08, "last": 3,
     "msg": "心烦意乱扰动对手，接下来 3 次行动降低其防御 8%。"},
    {"name": "失魂落魄", "cd": 6, "pr": 0.12, "last": 2,
     "msg": "失魂落魄震慑对手，接下来 2 次行动降低其防御 12%。"},
    {"name": "玄冰封印", "cd": 5, "pr": 0.05, "last": 2,
     "msg": "玄冰封印冻结对手，接下来 2 次行动将其暴击率设为 5%。"},
    {"name": "诛仙三剑", "cd": 5, "pr": 0.20, "last": 3,
     "msg": "诛仙三剑加持，接下来 3 次攻击伤害提高 20%。"},
)


def normalize_catalog(rows: Any = None) -> dict[str, dict[str, Any]]:
    """Use audited port values by default; preserve first-row source override semantics."""
    if isinstance(rows, Mapping):
        values = list(rows.values())
    elif isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        values = list(rows)
    else:
        values = []
    overrides: dict[str, dict[str, Any]] = {}
    for row in values:
        if not isinstance(row, Mapping):
            continue
        name = row.get("name")
        if name in SKILL_NAMES and name not in overrides:
            overrides[str(name)] = dict(row)
    catalog = {str(row["name"]): dict(row) for row in PORT_DESIGNED_SKILLS}
    for name, row in overrides.items():
        catalog[name].update(row)
    return catalog


def _valid_number(value: Any, *, integer: bool = False, minimum: float | None = None, maximum: float | None = None) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return (isfinite(number) and (not integer or number.is_integer())
            and (minimum is None or number >= minimum)
            and (maximum is None or number <= maximum))


def missing_definitions(catalog: Mapping[str, Any]) -> list[str]:
    """Return rows missing fields or valid values consumed by original biwu.js."""
    missing = []
    for name in SKILL_NAMES:
        row = catalog.get(name)
        if not isinstance(row, Mapping):
            missing.append(name)
            continue
        numeric_fields = {"cd": (True, 0, None), "last": (True, 0, None), "pr": (False, 0, 1)}
        if (not isinstance(row.get("msg"), str) or not row.get("msg")
                or any(field not in row or not _valid_number(row[field], integer=integer,
                                                   minimum=minimum, maximum=maximum)
                       for field, (integer, minimum, maximum) in numeric_fields.items())):
            missing.append(name)
    return missing

def choose_skills(state: dict[str, Any], uid: str, indexes: Sequence[int], now: float) -> tuple[bool, str]:
    side = "a" if str(uid) == str(state["player_a"]) else "b" if str(uid) == str(state["player_b"]) else ""
    if not side:
        return False, "你不在本场切磋中。"
    if state.get("status") != "active" or state.get("phase") == "finished":
        return False, "本场切磋已结束。"
    selected = []
    for value in list(indexes)[:3]:
        index = int(value) - 1
        if not 0 <= index < len(SKILL_NAMES):
            return False, "技能序号超出可选范围（1—10）。"
        definition = state["skill_catalog"].get(SKILL_NAMES[index])
        if definition:
            selected.append(dict(definition))
    if not selected:
        return False, "请发送 #选择技能 序号,序号（每次最多3个）。"
    current = state["choices"].setdefault(side, [])
    current.extend(selected)
    return True, f"已追加 {len(selected)} 个技能，当前携带{len(current)}项。"

def create_session(session_id: str, platform_id: str, group_id: str,
                   player_a: str, player_b: str, units: dict[str, dict[str, Any]],
                   catalog: Mapping[str, Mapping[str, Any]], now: float) -> dict[str, Any]:
    return {
        "session_id": str(session_id), "platform_id": str(platform_id),
        "group_id": str(group_id), "player_a": str(player_a), "player_b": str(player_b),
        "status": "active", "phase": "select", "round": 1, "rounds_left": None,
        "created_at": float(now), "expires_at": float(now) + 40.0,
        "units": units,
        "base_attrs": {side: {key: units[side][key] for key in ("atk", "defense", "bao")}
                       for side in ("a", "b")},
        "skill_catalog": {name: dict(catalog[name]) for name in SKILL_NAMES},
        "choices": {"a": [], "b": []}, "release": {"a": None, "b": None},
        "buffs": {"a": {}, "b": {}}, "log": [],
    }


def begin_round(state: dict[str, Any], now: float) -> None:
    state["phase"] = "release"
    state["release"] = {"a": None, "b": None}
    for side in ("a", "b"):
        for skill in state["choices"].get(side) or []:
            skill["cd"] = int(skill.get("cd", 0) or 0) + 1
    state["expires_at"] = float(now) + 20


def release_skill(state: dict[str, Any], uid: str, index: int, now: float) -> tuple[bool, str]:
    side = "a" if str(uid) == str(state["player_a"]) else "b" if str(uid) == str(state["player_b"]) else ""
    if not side:
        return False, "你不在本场切磋中。"
    if state.get("status") != "active" or state.get("phase") != "release":
        return False, "当前还不能提交释放技能。"
    requested = int(index)
    skills = state["choices"].get(side) or []
    if requested < 1 or requested > len(skills):
        return False, "技能序号超出本局携带范围。"
    slot = requested - 1
    skill = skills[slot]
    definition = state["skill_catalog"].get(skill.get("name"), {})
    cooldown = max(0, int(definition.get("cd", 0) or 0))
    if int(skill.get("cd", 0) or 0) < cooldown:
        return False, f"{skill.get('name')} 技能冷却中。"
    state["release"][side] = slot
    return True, "已提交本回合行动（结算前可修改）。"

def _value(catalog: Mapping[str, Mapping[str, Any]], name: str, key: str, default: float = 0) -> float:
    try:
        return float((catalog.get(name) or {}).get(key, default) or 0)
    except (TypeError, ValueError):
        return default


def _buff_tick(state: dict[str, Any], attacker: str, defender: str, log: list[str]) -> bool:
    units, buffs = state["units"], state["buffs"]
    source, target = units[attacker], units[defender]
    cancelled = False
    seal = buffs[defender]
    if int(seal.get("四象封印", 0) or 0) > 0:
        seal["四象封印"] -= 1
        cancelled = True
        log.append(f"{source['name']}因为四象封印之力，技能失效，剩余回合{seal['四象封印']}")
    for name in ("阴风蚀骨", "万年俱灰"):
        turns = int(buffs[defender].get(name, 0) or 0)
        if turns > 0:
            rate = _value(state["skill_catalog"], name, "pr")
            source["atk"] *= 1 - rate
            buffs[defender][name] = turns - 1
            log.append(f"{source['name']}受到侵蚀，攻击力降低{rate * 100:g}%，剩余回合{turns - 1}")
    turns = int(buffs[defender].get("玄冰封印", 0) or 0)
    if turns > 0:
        rate = _value(state["skill_catalog"], "玄冰封印", "pr")
        source["bao"] = rate
        buffs[defender]["玄冰封印"] = turns - 1
        log.append(f"{source['name']}因为玄冰封印之力，暴击率降至{rate * 100:g}%，剩余回合{turns - 1}")
    for name in ("心烦意乱", "失魂落魄"):
        turns = int(buffs[attacker].get(name, 0) or 0)
        if turns > 0:
            rate = _value(state["skill_catalog"], name, "pr")
            target["defense"] *= 1 - rate
            buffs[attacker][name] = turns - 1
            log.append(f"{target['name']}防御降低{rate * 100:g}%，剩余回合{turns - 1}")
    heal_turns = int(buffs[attacker].get("祝水咒", 0) or 0)
    if heal_turns > 0:
        rate = _value(state["skill_catalog"], "祝水咒", "pr")
        before = source["hp"]
        source["hp"] += int(source["hp_max"] * rate)
        buffs[attacker]["祝水咒"] = heal_turns - 1
        log.append(f"{source['name']}受到祝水咒治疗 {source['hp'] - before}，剩余回合{heal_turns - 1}")
    return cancelled


def _resolve_attack(state: dict[str, Any], side: str, rng, log: list[str]) -> bool:
    target_side = "b" if side == "a" else "a"
    source, target = state["units"][side], state["units"][target_side]
    released = state["release"].get(side)
    action = -1 if released is None else int(released)
    skills = state["choices"].get(side) or []
    unit = state.get("units", {}).get(side) or {}
    if unit.get("suppressed"):
        log.append(f"【超维压制】{source['name']}本回合无可用功法，只能普通攻击。")
        action = -1
    # The source clears the selected skill cooldown before checking active seals.
    if 0 <= action < len(skills):
        skills[action]["cd"] = 0
    cancelled = _buff_tick(state, side, target_side, log)
    if cancelled:
        action = -1
    orb = float(source.get("orb", 0) or 0)
    crit_rate = min(1.0, max(0.0, float(source["bao"])))
    # Legacy biwu.js calls baojishanghai(rate) with the default fixed 1.5 multiplier.
    crit_mult = 1.5 if rng.random() < crit_rate else 1.0
    damage = int(crit_mult * original_harm(source["atk"], target["defense"], rng)[0]
                 + int(source["atk"] * orb) + source["defense"] * 0.1)
    if 0 <= action < len(skills):
        skill = skills[action]
        name = str(skill.get("name") or "")
        definition = state["skill_catalog"].get(name) or {}
        pr = float(definition.get("pr", 0) or 0)
        last = int(definition.get("last", 0) or 0)
        if name == "四象封印":
            state["buffs"][side][name] = last
        elif name == "桃园结义":
            if side == "a":
                target["hp"] += int(target["hp"] * pr)
                source["hp"] += int(source["hp"] * pr)
            else:
                source["hp"] += int(source["hp"] * pr)
                # 原版 B-side 分支给 A 加 A_hp * (1+pr)。
                unit_a = state["units"]["a"]
                unit_a["hp"] += int(unit_a["hp"] * (1 + pr))
        elif name == "长生诀":
            source["hp"] += int(source["hp_max"] * pr)
        elif name in ("祝水咒", "阴风蚀骨", "万年俱灰", "心烦意乱", "失魂落魄", "玄冰封印", "诛仙三剑"):
            state["buffs"][side][name] = last
        message = skill.get("msg") or definition.get("msg") or f"发动【{name}】。"
        log.append(f"{source['name']}{message}")
    sword_turns = int(state["buffs"][side].get("诛仙三剑", 0) or 0)
    if sword_turns > 0:
        rate = _value(state["skill_catalog"], "诛仙三剑", "pr")
        damage *= 1 + rate
        state["buffs"][side]["诛仙三剑"] = sword_turns - 1
    damage = int(damage)
    target["hp"] -= damage
    crit_text = "触发暴击，" if crit_mult != 1.0 else ""
    log.append(f"第{state['round']}回合：{source['name']}普通攻击，{crit_text}造成伤害{damage}，{target['name']}剩余血量{target['hp']}")
    return target["hp"] > 0


def resolve_round(state: dict[str, Any], rng) -> dict[str, Any]:
    """原版 A 先手；A 击杀后跳过 B；双方出手属性每个外层回合重置。"""
    log: list[str] = []
    if _resolve_attack(state, "a", rng, log):
        _resolve_attack(state, "b", rng, log)
    for side in ("a", "b"):
        for key in ("atk", "defense", "bao"):
            state["units"][side][key] = state["base_attrs"][side][key]
    state["round"] += 1
    if state.get("rounds_left") is not None:
        state["rounds_left"] -= 1
    state["log"].extend(log)
    state["release"] = {"a": None, "b": None}
    winner = "a" if state["units"]["b"]["hp"] <= 0 else (
        "b" if state["units"]["a"]["hp"] <= 0 else None)
    if winner or (state.get("rounds_left") is not None and state["rounds_left"] <= 0):
        state["phase"] = "finished"
    return {"log": log, "winner": winner}
