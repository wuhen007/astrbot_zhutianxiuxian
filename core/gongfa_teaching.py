"""Pure rules for teaching learned gongfa between players."""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from . import dao_heart, extra_cultivation

TEACH_MIN_MIJING_LEVEL = 12
TEACH_MIN_XIANGU_LEVEL = 11
TEACH_MIN_AUTHORITY_LEVEL = 12
TEACH_COUNT_THRESHOLD = 10
TEACH_COOLDOWN_HOURS = 24

GONGFA_HIERARCHY: dict[str, int] = {
    "武学": 0, "限定功法": 0,
    "修炼功法": 1, "炼器": 1, "炼丹": 1, "推演": 1, "技能": 1,
    "天魔法": 2, "命运法": 2, "天赋": 2,
    "道与法": 3, "宝术": 3, "精神法门": 3,
    "九秘": 4, "盖世杀术": 4,
    "帝经": 5, "十凶宝术": 6, "仙王法": 7, "仙帝法": 8, "神慧者": 9,
}

APTITUDE_LEVELS: dict[str, int] = {
    "生而愚痴": 0, "天弃之人": 1, "先天不足": 2, "平庸之资": 2,
    "超凡资质": 3, "天纵之资": 4, "旷世奇才": 5, "绝世天骄": 7,
    "万古无双": 8, "无演无尽": 9, "岁云": 9, "无化如是": -1,
}
APTITUDE_REQUIREMENT_NAMES: tuple[str, ...] = (
    "生而愚痴", "天弃之人", "平庸之资", "超凡资质", "天纵之资",
    "旷世奇才", "绝世天骄", "绝世天骄", "万古无双", "无演无尽",
)


def can_teach_gongfa(doc: Any) -> bool:
    """The original gate compares the mapped 1-based track authority directly."""
    return extra_cultivation.realm_authority_level(doc) >= TEACH_MIN_AUTHORITY_LEVEL


def gongfa_level(gongfa_type: str | None) -> int:
    """Return the original hierarchy level; unrecognized categories default to 8."""
    return GONGFA_HIERARCHY.get(gongfa_type or "", 8)


def aptitude_level(aptitude: str | None) -> int:
    return APTITUDE_LEVELS.get(aptitude or "平庸之资", 2)


def aptitude_requirement_name(level: int) -> str:
    index = max(0, min(len(APTITUDE_REQUIREMENT_NAMES) - 1, int(level)))
    return APTITUDE_REQUIREMENT_NAMES[index]


def base_teaching_success_rate(level: int, aptitude: str | None) -> float:
    if aptitude == "生而愚痴":
        return 0.3
    if level >= 6:
        return 0.7
    if level >= 4:
        return 0.8
    return 1.0


def teaching_success_rate(
    level: int, aptitude: str | None, chance_multiplier: float = 1.0,
) -> float:
    """Original base rate multiplied by any caller-supplied dao-heart modifier."""
    try:
        multiplier = max(0.0, float(chance_multiplier))
    except (TypeError, ValueError):
        multiplier = 1.0
    return min(1.0, max(0.0, base_teaching_success_rate(level, aptitude) * multiplier))


def learning_chance_multiplier(learner: Any, now: float) -> float:
    return dao_heart.learning_chance_multiplier(learner, now)


def learning_potential_cost(learner: Any, base_cost: Any) -> int:
    try:
        base = max(0.0, float(base_cost or 0))
    except (TypeError, ValueError):
        base = 0.0
    from . import memory
    multiplier = float(memory.effects(learner).get("learn_cost_multiplier", 1.0))
    return max(0, math.ceil(base * multiplier))


def teaching_costs(level: int, learner: Any) -> dict[str, int]:
    level = max(0, int(level))
    return {
        "potential": learning_potential_cost(learner, level + 1),
        "spirit": 100_000 * (level + 1) * (level + 1),
    }


def reserve_teaching_costs(
    state: Mapping[str, Any], level: int, learner: Any,
) -> dict[str, Any]:
    """Reserve both costs only after a successful learning roll; input remains untouched."""
    costs = teaching_costs(level, learner)
    potential = state.get("remaining_potential", 0) or 0
    spirit = state.get("remaining_spirit", 0) or 0
    if potential < costs["potential"]:
        return {**dict(state), "ok": False, "reason": "potential", "costs": costs}
    if spirit < costs["spirit"]:
        return {**dict(state), "ok": False, "reason": "spirit", "costs": costs}
    return {
        "ok": True,
        "remaining_potential": potential - costs["potential"],
        "remaining_spirit": spirit - costs["spirit"],
        "costs": costs,
    }


def teaching_cooldown_hours(teacher: Any) -> float:
    from . import memory
    multiplier = float(memory.effects(teacher).get("teach_cooldown_multiplier", 1.0))
    return TEACH_COOLDOWN_HOURS * multiplier


def teaching_count_progress(current_count: int, successful_count: int) -> dict[str, Any]:
    """Match the original 10-success threshold, including a batch that crosses it."""
    count = max(0, int(current_count)) + max(0, int(successful_count))
    triggered = count >= TEACH_COUNT_THRESHOLD
    return {"count": count, "stored_count": 0 if triggered else count,
            "cooldown_triggered": triggered}


def _root_snapshot(target: Any, target_root: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if target_root is not None:
        return target_root
    ext = getattr(target, "ext", None)
    if isinstance(ext, Mapping) and isinstance(ext.get("linggen"), Mapping):
        return ext["linggen"]
    return {}


def check_teaching_requirement(
    name: str,
    gongfa_type: str | None,
    aptitude: str | None,
    target: Any = None,
    *,
    gongfa_data: Mapping[str, Any] | None = None,
    target_root: Mapping[str, Any] | None = None,
    batch: bool = False,
) -> dict[str, Any]:
    """Check original aptitude, seal, and bloodline rules before a learning roll.

    ``batch`` preserves the app's historical behavior: 愚钝真经 and 混沌道经
    restrictions were enforced by the all-gongfa path only.
    """
    level = gongfa_level(gongfa_type or "修炼功法")
    grade = aptitude or "平庸之资"
    if grade == "无化如是":
        return {"ok": False, "reason": "sealed_aptitude", "level": level}
    if gongfa_data and (gongfa_data.get("不可外传") or gongfa_data.get("untransferable")):
        return {"ok": False, "reason": "untransferable", "level": level}
    max_level = aptitude_level(grade)
    if max_level < level:
        return {
            "ok": False, "reason": "aptitude", "level": level,
            "required_level": level,
            "required_aptitude": aptitude_requirement_name(level),
        }

    root = _root_snapshot(target, target_root)
    root_name = str(root.get("name") or "")
    root_type = str(root.get("type") or "")
    allowed_natural = {"平庸之资", "先天不足", "天弃之人", "生而愚痴"}
    if name == "自然大道" and grade not in allowed_natural:
        return {"ok": False, "reason": "natural_dao_aptitude", "level": level}
    if batch and name == "愚钝真经" and grade != "生而愚痴":
        return {"ok": False, "reason": "foolish_script_aptitude", "level": level}
    if batch and name == "混沌道经" and "混沌" not in root_type:
        return {"ok": False, "reason": "chaos_root", "level": level}
    if name == "无始经" and not (
        root_name in {"先天圣体道胎", "混沌圣体道胎"}
        or root_type in {"先天圣体道胎", "混沌圣体道胎"}
    ):
        return {"ok": False, "reason": "primordial_body", "level": level}
    if name == "西皇经" and root_type not in {"道胎", "圣体道胎", "混沌圣体道胎"}:
        return {"ok": False, "reason": "dao_embryo", "level": level}
    if name in {"妖帝古经", "万龙古经"} and root_type not in {"妖体", "小成妖体", "大成妖体"}:
        return {"ok": False, "reason": "demon_body", "level": level}
    return {"ok": True, "reason": "", "level": level}


def split_known_gongfa(
    teacher_gongfa: Sequence[str] | None,
    learner_gongfa: Sequence[str] | None,
) -> tuple[list[str], list[str]]:
    """Deduplicate the teacher's list in source order and separate learner duplicates."""
    learner_known = set(learner_gongfa or ())
    seen: set[str] = set()
    pending: list[str] = []
    already_known: list[str] = []
    for name in teacher_gongfa or ():
        if name in seen:
            continue
        seen.add(name)
        (already_known if name in learner_known else pending).append(name)
    return pending, already_known


def evaluate_teaching_attempt(
    name: str,
    gongfa_type: str | None,
    learner: Any,
    target_aptitude: str | None,
    remaining_potential: float,
    remaining_spirit: float,
    random_roll: float,
    *,
    gongfa_data: Mapping[str, Any] | None = None,
    target_root: Mapping[str, Any] | None = None,
    chance_multiplier: float = 1.0,
    batch: bool = False,
) -> dict[str, Any]:
    """Evaluate one item; chance failures and unaffordable attempts spend nothing."""
    requirement = check_teaching_requirement(
        name, gongfa_type, target_aptitude,
        gongfa_data=gongfa_data, target_root=target_root, batch=batch,
    )
    level = int(requirement["level"])
    costs = teaching_costs(level, learner)
    unchanged = {
        "remaining_potential": remaining_potential,
        "remaining_spirit": remaining_spirit,
    }
    if not requirement["ok"]:
        return {**requirement, "success_rate": 0.0, "costs": costs, **unchanged}

    rate = teaching_success_rate(level, target_aptitude, chance_multiplier)
    if random_roll > rate:
        return {"ok": False, "reason": "chance", "level": level,
                "success_rate": rate, "costs": costs, **unchanged}
    reserved = reserve_teaching_costs(
        {"remaining_potential": remaining_potential, "remaining_spirit": remaining_spirit},
        level, learner,
    )
    if not reserved["ok"]:
        return {**reserved, "level": level, "success_rate": rate, **unchanged}
    return {**reserved, "reason": "", "level": level, "success_rate": rate}


def apply_teaching_result(
    target: Any,
    gongfa_names: Sequence[str],
    remaining_potential: float,
) -> Any:
    """Copy learned names to the receiver; the teacher's learned list is unchanged."""
    ext = getattr(target, "ext", None)
    if not isinstance(ext, MutableMapping):
        raise TypeError("target must expose a mutable ext mapping")
    learned = ext.get("gongfa")
    if not isinstance(learned, list):
        learned = []
        ext["gongfa"] = learned
    for name in gongfa_names:
        if name not in learned:
            learned.append(name)
    ext["potential"] = remaining_potential
    return target
