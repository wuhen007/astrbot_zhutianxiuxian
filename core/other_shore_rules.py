"""沧澜界 · 彼岸世界/真世界：规则层（纯函数，无 IO）。

对应原版 ``model/otherShoreRules.js``。移植「旅行境界 / 心神路程 / 精神消耗 /
彼岸抑制免疫 / 外部行为限制」等规则，供 ``other_shore_world.calculate_other_shore_travel`` 使用。

境界判断口径（对齐原版）：
- 以名称优先（准仙帝 / 仙帝 / 祭道 / 路尽 / 仙王 / 真仙 / 大帝）判定；
- 其次用 level_id 分档（mijinglevel_id），再叠加 xiangulevel_id、huafenlevel_id，取最强一档。
"""

from __future__ import annotations

from typing import Any

OTHER_SHORE_SUPPRESSION_MULTIPLIER = 0.7

OTHER_SHORE_WORLD_RESTRICTIONS: dict[str, bool] = {
    "externalShop": False,
    "externalPillHealing": False,
}

OTHER_SHORE_TRAVEL_TIERS: dict[str, Any] = {
    "below_emperor": {"name": "大帝以下", "mindPerStep": 5, "stepsPerMind": 1},
    "emperor": {"name": "大帝", "mindPerStep": 1, "stepsPerMind": 1},
    "true_immortal": {"name": "真仙", "mindPerStep": 1, "stepsPerMind": 2},
    "immortal_king": {"name": "仙王至仙王巨头", "mindPerStep": 1, "stepsPerMind": 3},
    "quasi_immortal_emperor": {"name": "准仙帝", "mindPerStep": 1, "stepsPerMind": 10},
    "immortal_emperor": {"name": "仙帝", "mindPerStep": 0, "stepsPerMind": float("inf")},
}

TIER_ORDER: tuple[str, ...] = (
    "below_emperor",
    "emperor",
    "true_immortal",
    "immortal_king",
    "quasi_immortal_emperor",
    "immortal_emperor",
)


def tier_from_realm_name(value: str | None) -> str:
    name = str(value or "").strip()
    if not name:
        return "below_emperor"
    if "准仙帝" in name:
        return "quasi_immortal_emperor"
    if "仙帝" in name or "祭道" in name or "路尽" in name:
        return "immortal_emperor"
    if "仙王" in name or "帝光仙王" in name:
        return "immortal_king"
    if "真仙" in name or "红尘仙" in name:
        return "true_immortal"
    if "大帝" in name:
        return "emperor"
    return "below_emperor"


def tier_from_level(level, thresholds: dict[str, int]) -> str:
    """未配置的更高档位视为不可达（原版阈值缺省即不启用该档）。"""
    value = 0 if level is None else max(0, int(level))
    for key, name in (
        ("immortalEmperor", "immortal_emperor"),
        ("quasiImmortalEmperor", "quasi_immortal_emperor"),
        ("immortalKing", "immortal_king"),
        ("trueImmortal", "true_immortal"),
        ("emperor", "emperor"),
    ):
        limit = thresholds.get(key)
        if limit is None or limit == float("inf"):
            continue
        if value >= int(limit):
            return name
    return "below_emperor"


def stronger_tier(left: str, right: str) -> str:
    return left if TIER_ORDER.index(left) >= TIER_ORDER.index(right) else right


def get_other_shore_travel_tier(player_or_realm: dict[str, Any] | str | None = None) -> str:
    if isinstance(player_or_realm, str):
        return tier_from_realm_name(player_or_realm)
    player = dict(player_or_realm or {})
    tier = tier_from_realm_name(player.get("境界") or player.get("realm") or player.get("realmName"))
    tier = stronger_tier(
        tier,
        tier_from_level(player.get("mijinglevel_id"),
                        {"emperor": 16, "trueImmortal": 17, "immortalKing": 18,
                         "quasiImmortalEmperor": 20, "immortalEmperor": 21}),
    )
    tier = stronger_tier(
        tier,
        tier_from_level(player.get("xiangulevel_id", player.get("xianggulevel_id")),
                        {"emperor": float("inf"), "trueImmortal": 16, "immortalKing": 17,
                         "quasiImmortalEmperor": 21, "immortalEmperor": 22}),
    )
    tier = stronger_tier(
        tier,
        tier_from_level(player.get("huafenlevel_id"),
                        {"emperor": 16, "trueImmortal": 17, "immortalKing": 19,
                         "quasiImmortalEmperor": 21, "immortalEmperor": 22}),
    )
    return tier


def get_other_shore_travel_rule(player_or_realm: dict[str, Any] | str | None = None) -> dict[str, Any]:
    tier = get_other_shore_travel_tier(player_or_realm)
    return {"tier": tier, **OTHER_SHORE_TRAVEL_TIERS[tier]}


def calculate_other_shore_mind_cost(
    player_or_realm,
    unanchored_steps: int,
    remainder: float = 0,
) -> dict[str, Any]:
    steps = int(unanchored_steps)
    carried = float(remainder)
    if steps < 0:
        raise ValueError("未锚定路径格数必须是非负整数")
    if carried < 0:
        raise ValueError("心神路程余数必须是非负整数")
    rule = get_other_shore_travel_rule(player_or_realm)
    if rule.get("mindPerStep", 0) == 0:
        return {"tier": rule["tier"], "name": rule.get("name"), "unanchoredSteps": steps,
                "cost": 0, "remainder": 0}
    if rule.get("stepsPerMind", 1) == 1:
        if carried != 0:
            raise ValueError("当前境界不使用心神路程余数")
        return {"tier": rule["tier"], "name": rule.get("name"), "unanchoredSteps": steps,
                "cost": steps * rule.get("mindPerStep", 1), "remainder": 0}
    if carried >= rule.get("stepsPerMind"):
        raise ValueError("心神路程余数超出当前境界范围")
    total = carried + steps
    return {
        "tier": rule["tier"],
        "name": rule.get("name"),
        "unanchoredSteps": steps,
        "cost": int(total // rule.get("stepsPerMind", 1)),
        "remainder": int(total % rule.get("stepsPerMind", 1)),
    }


def is_other_shore_suppression_immune(player: dict[str, Any] | None = None) -> bool:
    player = dict(player or {})
    has_own = lambda target, key: bool(target) and key in target  # noqa: E731

    system = player.get("自创修炼体系")
    if player.get("xiangu_yishenweizhong") is True:
        return True
    if has_own(system, "name") and str(system.get("name", "")).strip():
        return True
    if has_own(player, "xiangu_yishenweizhong") or has_own(system, "name"):
        return False
    return max(int(player.get("xiangulevel_id") or 0), int(player.get("xianggulevel_id") or 0)) >= 12


def get_other_shore_suppression(player: dict[str, Any] | None = None) -> dict[str, Any]:
    player = dict(player or {})
    immune = is_other_shore_suppression_immune(player)
    multiplier = 1 if immune else OTHER_SHORE_SUPPRESSION_MULTIPLIER
    return {
        "immune": immune,
        "attributeMultiplier": multiplier,
        "techniqueEffectMultiplier": multiplier,
    }


def is_other_shore_external_action_allowed(action: str) -> bool:
    if action not in OTHER_SHORE_WORLD_RESTRICTIONS:
        raise ValueError(f"未知的彼岸外部行为：{action}")
    return OTHER_SHORE_WORLD_RESTRICTIONS[action]
