"""Achievement checks, progress, and reward-claim planning (pure logic)."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from typing import Any

_MISSING = object()
_TRACK_THRESHOLDS = {
    9: (1, 1, 1),
    10: (15, 13, 14),
    11: (16, 14, 16),
    12: (17, 15, 17),
    13: (19, 19, 20),
    14: (20, 20, 21),
    15: (21, 21, 22),
    16: (22, 22, 23),
}


def _get(value: Any, key: str, default: Any = _MISSING) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _ext(player: Any) -> Mapping:
    value = _get(player, "ext", {})
    return value if isinstance(value, Mapping) else {}


def _player_value(player: Any, key: str, default: Any = _MISSING) -> Any:
    value = _get(player, key)
    if value is not _MISSING:
        return value
    ext = _ext(player)
    if key in ext:
        return ext[key]
    legacy = ext.get("legacy_source")
    if isinstance(legacy, Mapping) and key in legacy:
        return legacy[key]
    return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _realm_id(player: Any) -> int:
    value = _player_value(player, "level_id")
    if value is not _MISSING:
        return _integer(value, -1)
    return _integer(_get(player, "realm_index"), -1) + 1


def _physique_id(player: Any) -> int:
    value = _player_value(player, "Physique_id")
    if value is _MISSING:
        value = _player_value(player, "physique_id")
    if value is not _MISSING:
        return _integer(value, -1)
    return _integer(_get(player, "physique_index"), -1) + 1


def _extra_tracks(player: Any) -> tuple[int, int, int]:
    """Read live extra-track levels without allowing the legacy adapter to mutate player state."""
    try:
        from .extra_cultivation import levels_of

        levels = levels_of(deepcopy(player))
        return tuple(_integer(levels.get(track), 1) for track in ("mijing", "xiangu", "huafen"))
    except (AttributeError, TypeError, ValueError):
        ext = _ext(player)
        legacy = ext.get("legacy_source")
        legacy = legacy if isinstance(legacy, Mapping) else {}
        state = ext.get("extra_cultivation")
        state_levels = state.get("levels") if isinstance(state, Mapping) else {}
        state_levels = state_levels if isinstance(state_levels, Mapping) else {}
        keys = (
            ("mijing", "mijinglevel_id"),
            ("xiangu", "xiangulevel_id"),
            ("huafen", "huafenlevel_id"),
        )
        out = []
        for track, key in keys:
            raw = state_levels.get(track, ext.get(key, legacy.get(key, 1)))
            out.append(max(1, _integer(raw, 1)))
        return tuple(out)


def _current_plane(player: Any) -> Any:
    value = _player_value(player, "power_place")
    if value is not _MISSING:
        return value
    plane = _ext(player).get("plane")
    if isinstance(plane, Mapping):
        return plane.get("current", "")
    return ""


def _used_zhutian_mirror(player: Any) -> bool:
    value = _player_value(player, "使用过诸天镜")
    return value is True or _ext(player).get("used_zhutian_mirror") is True


def grant(player: Any, achievement_id: int | str) -> bool:
    """Record one automatic original achievement unlock without adding rewards."""
    ext = _get(player, "ext", {})
    if not isinstance(ext, MutableMapping):
        return False
    aid = str(achievement_id)
    owned = _owned_ids(player)
    if aid in owned:
        return False
    owned.append(aid)
    ext["achievements"] = owned
    return True


def _weapons(equipment: Any) -> list[Mapping]:
    if not isinstance(equipment, Mapping):
        return []
    weapon = equipment.get("帝兵", equipment.get("imperial_weapon"))
    if isinstance(weapon, Mapping):
        return [weapon]
    if isinstance(weapon, Sequence) and not isinstance(weapon, (str, bytes)):
        return [item for item in weapon if isinstance(item, Mapping)]
    if "author_name" in equipment or "品阶" in equipment or "rank" in equipment:
        return [equipment]
    return []


def _condition_met(achievement_id: int, player: Any, equipment: Any) -> bool:
    if achievement_id == 1:
        return _realm_id(player) > 7
    if achievement_id == 2:
        return _physique_id(player) > 7
    if achievement_id == 3:
        occupation = _player_value(player, "occupation", "")
        return bool(occupation) and len(str(occupation)) > 0
    if achievement_id == 4:
        shown = _player_value(player, "linggenshow")
        if shown is not _MISSING:
            return _integer(shown, 1) == 0
        root = _ext(player).get("linggen")
        return isinstance(root, Mapping) and bool(root.get("name"))
    if achievement_id == 5:
        return _realm_id(player) > 41
    if achievement_id == 6:
        return _physique_id(player) > 41
    if achievement_id in (7, 8):
        place = _current_plane(player)
        target = "遮天位面" if achievement_id == 7 else "下界八域"
        if isinstance(place, str):
            return place == target
        return _integer(place, -1) == (2 if achievement_id == 7 else 1)
    if achievement_id in _TRACK_THRESHOLDS:
        levels = _extra_tracks(player)
        return any(level > threshold for level, threshold in zip(levels, _TRACK_THRESHOLDS[achievement_id]))
    if achievement_id == 22:
        return _used_zhutian_mirror(player)
    weapons = _weapons(equipment)
    if achievement_id == 34:
        player_id = _player_value(player, "id", _player_value(player, "uid", ""))
        return any(str(weapon.get("author_name", "")) == str(player_id) for weapon in weapons)
    if achievement_id == 35:
        return any(weapon.get("品阶", weapon.get("rank")) in ("极道帝兵", "至尊兵") for weapon in weapons)
    return False


def _achievement_id(item: Mapping) -> str:
    value = item.get("id")
    return "" if value is None else str(value)


def _owned_ids(player: Any) -> list[str]:
    values = _player_value(player, "成就")
    if values is _MISSING:
        values = _player_value(player, "achievements", ())
    if not isinstance(values, (list, tuple, set)):
        return []
    return [str(value) for value in values if value not in (None, "", "undefined")]


def _catalog_rows(catalog: Any) -> list[Mapping]:
    if not isinstance(catalog, Sequence) or isinstance(catalog, (str, bytes)):
        return []
    return [item for item in catalog if isinstance(item, Mapping)]


def achievement_text(player: Any, catalog: Sequence[Mapping], equipment: Any = None) -> tuple[str, dict[str, Any]]:
    scan = scan_achievements(player, catalog, equipment)
    unlocked = set(scan["unlocked_ids"])
    progress = scan["progress"]
    lines = [f"【成就自查】已解锁 {progress['unlocked']}/{progress['total']}（{progress['percent']}%）"]
    lines.extend(f"· {kind}：{value['unlocked']}/{value['total']}"
                 for kind, value in progress["by_type"].items())
    lines.append("")
    for item in _catalog_rows(catalog):
        aid = _achievement_id(item)
        marker = "✅" if aid in unlocked else "🔒"
        lines.append(f"{marker} {item.get('name') or '未命名'}｜{item.get('desc') or ''}")
    if scan["new_items"]:
        lines.insert(1, "本次新解锁：" + "、".join(str(item.get("name")) for item in scan["new_items"]))
    lines.append("")
    lines.append("原版成就表未配置领奖奖励，解锁记录会自动保存。")
    return "\n".join(lines), scan

def scan_achievements(
    player: Any,
    catalog: Sequence[Mapping],
    equipment: Any = None,
) -> dict[str, Any]:
    """Return newly earned IDs and progress; never mutate the player or catalog."""
    rows = _catalog_rows(catalog)
    unlocked_ids = _owned_ids(player)
    unlocked = set(unlocked_ids)
    new_ids: list[str] = []
    new_items: list[dict[str, Any]] = []

    for item in rows:
        aid = _achievement_id(item)
        if not aid or aid in unlocked:
            continue
        if _condition_met(_integer(aid, -1), player, equipment):
            unlocked.add(aid)
            unlocked_ids.append(aid)
            new_ids.append(aid)
            new_items.append(deepcopy(dict(item)))

    by_type: dict[str, dict[str, int]] = {}
    for item in rows:
        category = str(item.get("type") or "其他")
        stats = by_type.setdefault(category, {"unlocked": 0, "total": 0})
        stats["total"] += 1
        if _achievement_id(item) in unlocked:
            stats["unlocked"] += 1

    total = len(rows)
    count = len(unlocked_ids)
    percent = int(count * 100 / total + 0.5) if total else 0
    return {
        "new_ids": new_ids,
        "unlocked_ids": unlocked_ids,
        "new_items": new_items,
        "progress": {
            "unlocked": count,
            "total": total,
            "percent": percent,
            "by_type": by_type,
        },
    }


def plan_achievement_claim(
    player: Any,
    achievement_id: int | str,
    catalog: Sequence[Mapping],
    rewards: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan an idempotent claim; the caller persists the receipt and applies rewards atomically."""
    aid = str(achievement_id)
    receipt = f"achievement:{aid}"
    item = next((row for row in _catalog_rows(catalog) if _achievement_id(row) == aid), None)
    if item is None:
        return {"ok": False, "reason": "unknown_achievement", "receipt": receipt, "reward": {}}
    if aid not in set(_owned_ids(player)):
        return {"ok": False, "reason": "not_unlocked", "receipt": receipt, "reward": {}}

    claims = _ext(player).get("_rewardClaims")
    prior = claims.get(receipt) if isinstance(claims, Mapping) else None
    if prior is not None:
        reward = prior.get("reward", {}) if isinstance(prior, Mapping) else {}
        return {
            "ok": False,
            "reason": "already_claimed",
            "receipt": receipt,
            "reward": deepcopy(dict(reward)) if isinstance(reward, Mapping) else {},
        }

    configured = rewards.get(aid, _MISSING) if isinstance(rewards, Mapping) else _MISSING
    if configured is _MISSING:
        configured = item.get("reward", {})
    reward = deepcopy(dict(configured)) if isinstance(configured, Mapping) else {}
    if not reward:
        return {"ok": False, "reason": "no_reward_configured", "receipt": receipt, "reward": {}}
    return {"ok": True, "reason": "claimable", "receipt": receipt, "reward": reward}
