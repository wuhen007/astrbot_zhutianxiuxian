"""Independent cultivation-track state shared by gates, rewards, and reforge."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = 2
MAX_TRACK_LEVEL = 25
TRACKS = ("mijing", "xiangu", "huafen")
SOURCE_KEYS = {
    "mijing": ("mijinglevel_id",),
    "xiangu": ("xiangulevel_id", "xianggulevel_id"),
    "huafen": ("huafenlevel_id",),
}
TRACK_NAMES = {"mijing": "人体秘境", "xiangu": "仙古今世法", "huafen": "花粉进化路"}
INITIAL_TRACK_LEVELS = {"mijing": 1, "xiangu": 2, "huafen": 1}


def _ext(doc: Any) -> dict[str, Any]:
    if isinstance(doc, dict):
        raw = doc.get("ext")
        if not isinstance(raw, dict):
            raw = {}
            doc["ext"] = raw
        return raw
    raw = getattr(doc, "ext", None)
    if not isinstance(raw, dict):
        raw = {}
        setattr(doc, "ext", raw)
    return raw


def _level(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _projected_level(doc: Any, track: str) -> int:
    if track == "mijing":
        realm = int(doc.get("realm_index", 0) if isinstance(doc, Mapping)
                    else getattr(doc, "realm_index", 0) or 0)
        return max(1, realm // 2)
    if track == "xiangu":
        # Read the old main-realm projection directly. Calling xiangu.xg_level_of
        # here recurses through is_overridden -> state_of during one-time migration.
        ext = _ext(doc)
        realm = int(doc.get("realm_index", 0) if isinstance(doc, Mapping)
                    else getattr(doc, "realm_index", 0) or 0)
        try:
            from .xiangu import XG_LEVEL_DIV
            projected = max(1, min(11, 2 + max(0, realm) // XG_LEVEL_DIV))
        except (ImportError, AttributeError, TypeError, ValueError):
            projected = max(1, min(11, 2 + max(0, realm) // 4))
        xiangu = ext.get("xiangu")
        shenhuo = xiangu.get("shenhuo") if isinstance(xiangu, Mapping) else None
        if isinstance(shenhuo, Mapping) and shenhuo.get("已点燃"):
            projected = max(projected, 8)
        return projected
    ext = _ext(doc)
    flower = ext.get("flower")
    return _level(flower.get("level")) if isinstance(flower, Mapping) else 1


def _legacy_level(ext: Mapping[str, Any], track: str) -> int | None:
    source = ext.get("legacy_source")
    if not isinstance(source, Mapping):
        return None
    for key in SOURCE_KEYS[track]:
        if key in source and source[key] not in (None, ""):
            return _level(source[key])
    return None


def _explicit_track(doc: Any) -> str | None:
    ext = _ext(doc)
    legacy = ext.get("legacy_source")
    state = ext.get("extra_cultivation")
    values = [
        state.get("selected_track") if isinstance(state, Mapping) else None,
        ext.get("extra_track"), ext.get("cultivation_path"),
    ]
    if isinstance(legacy, Mapping):
        values.extend((legacy.get("额外体系"), legacy.get("extra_track"),
                       legacy.get("cultivation_path")))
    return next((str(value) for value in values if str(value or "") in TRACKS), None)


def _infer_migrated_track(doc: Any, levels: Mapping[str, Any],
                          overrides: Mapping[str, Any]) -> str | None:
    """Infer only a unique legacy route; ambiguous historical progress is preserved."""
    explicit = _explicit_track(doc)
    if explicit:
        return explicit
    ext = _ext(doc)
    flower = ext.get("flower")
    if isinstance(flower, Mapping) and _level(flower.get("level")) > INITIAL_TRACK_LEVELS["huafen"]:
        return "huafen"

    xiangu = _level(levels.get("xiangu"), INITIAL_TRACK_LEVELS["xiangu"])
    mijing = _level(levels.get("mijing"), INITIAL_TRACK_LEVELS["mijing"])
    huafen_level = _level(levels.get("huafen"), INITIAL_TRACK_LEVELS["huafen"])
    if xiangu >= 12 and mijing in (5, 6, 7, 8) and huafen_level == 1:
        milestone_track = {5: 12, 6: 13, 7: 14, 8: 15}[mijing]
        if xiangu >= milestone_track:
            return "xiangu"

    progressed = [track for track in TRACKS
                  if bool(overrides.get(track))
                  and _level(levels.get(track)) > INITIAL_TRACK_LEVELS[track]]
    return progressed[0] if len(progressed) == 1 else None


def _new_state(doc: Any) -> dict[str, Any]:
    ext = _ext(doc)
    levels: dict[str, int] = {}
    synced: dict[str, int] = {}
    overrides: dict[str, bool] = {}
    for track in TRACKS:
        projected = _projected_level(doc, track)
        flower = ext.get("flower")
        flower_level = (_level(flower.get("level"))
                        if track == "huafen" and isinstance(flower, Mapping) else None)
        source_level = _legacy_level(ext, track)
        levels[track] = min(MAX_TRACK_LEVEL, flower_level or source_level or projected)
        synced[track] = projected
        overrides[track] = flower_level is not None or source_level is not None
    return {
        "version": SCHEMA_VERSION, "levels": levels, "synced": synced,
        "overrides": overrides,
        "selected_track": _infer_migrated_track(doc, levels, overrides),
    }


def state_of(doc: Any) -> dict[str, Any]:
    """Migrate legacy projections once, then keep every route independent."""
    ext = _ext(doc)
    raw = ext.get("extra_cultivation")
    if not isinstance(raw, dict):
        state = _new_state(doc)
    elif int(raw.get("version", 0) or 0) == SCHEMA_VERSION:
        state = raw
    elif int(raw.get("version", 0) or 0) == 1:
        # Preserve the last level the old projection logic would have produced,
        # including any unobserved realm gain before this migration is first read.
        old_levels = raw.get("levels") if isinstance(raw.get("levels"), Mapping) else {}
        old_synced = raw.get("synced") if isinstance(raw.get("synced"), Mapping) else {}
        old_overrides = raw.get("overrides") if isinstance(raw.get("overrides"), Mapping) else {}
        levels, synced, overrides = {}, {}, {}
        for track in TRACKS:
            projected = _projected_level(doc, track)
            prior_projection = _level(old_synced.get(track), projected)
            pending_projection_gain = max(0, projected - prior_projection)
            levels[track] = min(
                MAX_TRACK_LEVEL,
                _level(old_levels.get(track), projected) + pending_projection_gain,
            )
            synced[track] = projected
            overrides[track] = bool(old_overrides.get(track))
        state = {
            "version": SCHEMA_VERSION, "levels": levels, "synced": synced,
            "overrides": overrides,
            "selected_track": _infer_migrated_track(doc, levels, overrides),
        }
    else:
        state = _new_state(doc)

    levels = state.setdefault("levels", {})
    synced = state.setdefault("synced", {})
    overrides = state.setdefault("overrides", {})
    if not isinstance(levels, dict):
        levels = state["levels"] = {}
    if not isinstance(synced, dict):
        synced = state["synced"] = {}
    if not isinstance(overrides, dict):
        overrides = state["overrides"] = {}
    selected = state.get("selected_track")
    if selected not in TRACKS:
        state["selected_track"] = selected = _explicit_track(doc)
    selected = state.get("selected_track")
    for track in TRACKS:
        projected = _projected_level(doc, track)
        prior_projection = _level(synced.get(track), projected)
        projection_gain = max(0, projected - prior_projection)
        overrides.setdefault(track, False)
        if not overrides[track] and selected != track:
            levels[track] = min(
                MAX_TRACK_LEVEL,
                _level(levels.get(track), projected) + projection_gain,
            )
        else:
            levels[track] = min(MAX_TRACK_LEVEL, _level(levels.get(track), projected))
        # Unselected native routes continue to project realm growth; once a
        # route has independent progress, its persisted level remains authoritative.
        synced[track] = projected
    state["version"] = SCHEMA_VERSION
    ext["extra_cultivation"] = state
    return state


def authority_level(doc: Any, track: str) -> int:
    level = level_of(doc, track)
    if track == "mijing":
        return max(0, level - 1)
    if track == "xiangu":
        mapping = ((25, 24), (24, 23), (23, 22), (22, 21), (21, 20),
                   (19, 19), (17, 18), (16, 17), (15, 16), (14, 15),
                   (13, 14), (12, 13), (11, 12), (9, 11), (8, 10))
    else:
        from . import flower
        mapping = tuple(sorted(flower.AUTHORITY_MAP.items(), reverse=True))
    rank = next((mapped for required, mapped in mapping if level >= required), level)
    return max(0, int(rank) - 1)

def realm_authority_level(doc: Any) -> int:
    return max(authority_level(doc, track) for track in TRACKS) + 1


def level_of(doc: Any, track: str) -> int:
    if track not in SOURCE_KEYS:
        raise ValueError(f"unknown extra cultivation track: {track}")
    return int(state_of(doc)["levels"][track])


def is_overridden(doc: Any, track: str) -> bool:
    """Whether a route has persisted independent progress or is explicitly selected."""
    if track not in SOURCE_KEYS:
        return False
    state = state_of(doc)
    return (bool(state.get("overrides", {}).get(track))
            or state.get("selected_track") == track)


def selected_track(doc: Any) -> str | None:
    """Return the single explicitly selected route, if the save has one."""
    value = state_of(doc).get("selected_track")
    return str(value) if value in TRACKS else None


def select_track(doc: Any, track: str) -> tuple[bool, str]:
    """Select a route after its caller has validated original gates/resources."""
    if track not in SOURCE_KEYS:
        raise ValueError(f"unknown extra cultivation track: {track}")
    state = state_of(doc)
    current = state.get("selected_track")
    if current and current != track:
        return False, f"已选择{TRACK_NAMES[current]}，不可兼修{TRACK_NAMES[track]}。"
    state["selected_track"] = track
    state["selection_source"] = "breakthrough"
    # Existing consumers (authority route selection, etc.) use this compatibility key.
    _ext(doc)["extra_track"] = track
    return True, ""


def levels_of(doc: Any) -> dict[str, int]:
    return {track: level_of(doc, track) for track in TRACKS}


def set_level(doc: Any, track: str, value: int) -> int:
    """Set one route's persisted level without implicitly selecting another route."""
    if track not in SOURCE_KEYS:
        raise ValueError(f"unknown extra cultivation track: {track}")
    state = state_of(doc)
    level = min(MAX_TRACK_LEVEL, _level(value))
    state["levels"][track] = level
    state["synced"][track] = _projected_level(doc, track)
    state.setdefault("overrides", {})[track] = True
    if track == "huafen":
        flower = _ext(doc).get("flower")
        if isinstance(flower, dict):
            flower["level"] = level
    return level


def advance_track(doc: Any, track: str, amount: int = 1) -> int:
    """Advance a validated route explicitly; call only after its success conditions pass."""
    if track not in SOURCE_KEYS:
        raise ValueError(f"unknown extra cultivation track: {track}")
    amount = int(amount)
    if amount < 1:
        raise ValueError("route breakthrough amount must be positive")
    current = level_of(doc, track)
    target = min(MAX_TRACK_LEVEL, current + amount)
    if target == current:
        raise ValueError(f"{TRACK_NAMES[track]}已达移植数据等级上限 {MAX_TRACK_LEVEL}")
    ok, reason = select_track(doc, track)
    if not ok:
        raise ValueError(reason)
    set_level(doc, track, target)
    if track == "xiangu":
        sync_xiangu_companion_mijing(doc)
    return target


def xiangu_extremes(doc: Any) -> list[int]:
    """Return this save's completed Ancient-method extremes as 1-based route IDs."""
    state = state_of(doc)
    raw = state.get("xiangu_extreme_ids")
    if not isinstance(raw, (list, tuple, set)):
        ext = _ext(doc)
        legacy = ext.get("legacy_source")
        raw = legacy.get("极境") if isinstance(legacy, Mapping) else None
    if not isinstance(raw, (list, tuple, set)):
        return []
    values = set()
    for value in raw:
        try:
            stage = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if 1 <= stage <= 6:
            values.add(stage)
    return sorted(values)


def mark_xiangu_extreme(doc: Any, stage: int) -> list[int]:
    """Persist an achieved original Ancient-method extreme (route stages 1–6)."""
    stage = int(stage)
    if not 1 <= stage <= 6:
        raise ValueError("仙古极境编号必须在 1 至 6 之间")
    state = state_of(doc)
    values = set(xiangu_extremes(doc))
    values.add(stage)
    state["xiangu_extreme_ids"] = sorted(values)
    # xiangu_dao.extremes_completed and the original-compatible reforge path
    # consume a scalar count; preserve IDs separately so prerequisites stay exact.
    state["xiangu_extremes"] = len(values)
    return list(state["xiangu_extreme_ids"])


def xiangu_companion_mijing_target(doc: Any) -> int:
    """Original Xiangu 12–15 milestones and Red Dust lives' Mijing projection."""
    xiangu_level = level_of(doc, "xiangu")
    target = 1
    for required, mijing_level in ((12, 5), (13, 6), (14, 7), (15, 8)):
        if xiangu_level >= required:
            target = mijing_level
    if xiangu_level >= 15:
        selfdao = _ext(doc).get("selfdao")
        raw_lives = selfdao.get("life", 0) if isinstance(selfdao, Mapping) else 0
        completed_lives = max(0, min(9, _level(raw_lives, 0)))
        target = max(target, min(17, 8 + completed_lives))
    return target


def sync_xiangu_companion_mijing(doc: Any) -> int:
    """Apply original Xiangu companion milestones without selecting Mijing as a second route."""
    if selected_track(doc) != "xiangu":
        return level_of(doc, "mijing")
    target = xiangu_companion_mijing_target(doc)
    current = level_of(doc, "mijing")
    if target > current:
        set_level(doc, "mijing", target)
        state_of(doc).setdefault("companion_tracks", {})["mijing"] = "xiangu"
        return target
    return current



def legacy_fields(doc: Any) -> dict[str, int]:
    levels = levels_of(doc)
    return {"mijinglevel_id": levels["mijing"],
            "xiangulevel_id": levels["xiangu"],
            "huafenlevel_id": levels["huafen"]}

def _preserve_flower_branch_after_reforge(doc: Any, previous_level: int, next_level: int) -> None:
    ext = _ext(doc)
    legacy = ext.get("legacy_source")
    if not isinstance(legacy, dict):
        return
    former = legacy.get("花粉路前身分支")
    branch = legacy.get("花粉路分支")
    if previous_level >= 17:
        if former not in ("大宇", "究极"):
            former = branch if branch in ("大宇", "究极") else ""
        if next_level < 17:
            legacy.pop("花粉路分支", None)
            legacy.pop("花粉路前身分支", None)
        else:
            legacy["花粉路分支"] = "宇究" if next_level >= 18 else former
            legacy["花粉路前身分支"] = former
    history = legacy.get("花粉分支回炉记录")
    if history is None:
        history = legacy["花粉分支回炉记录"] = []
    if isinstance(history, list) and previous_level >= 17 and previous_level != next_level:
        history.append({"fromLevel": previous_level, "toLevel": next_level,
                        "branch": branch or "", "formerBranch": former or ""})
        del history[:-100]


def reforge(doc: Any) -> dict[str, Any]:
    """Drop each independent track once, preserve route history, clear attained extremes."""
    state = state_of(doc)
    previous = dict(state["levels"])
    next_levels = {
        track: max(1, min(INITIAL_TRACK_LEVELS[track], previous[track]),
                   min(MAX_TRACK_LEVEL, previous[track]) - 1)
        for track in TRACKS
    }
    changed = [track for track in TRACKS if next_levels[track] < previous[track]]
    if not changed:
        return {"changed": False, "previous": previous, "next": next_levels, "changed_tracks": []}

    for track in TRACKS:
        if track in changed:
            state["levels"][track] = next_levels[track]
            state.setdefault("overrides", {})[track] = True
        state["synced"][track] = _projected_level(doc, track)

    ext = _ext(doc)
    flower = ext.get("flower")
    if isinstance(flower, dict):
        if "huafen" in changed:
            flower["level"] = next_levels["huafen"]
        flower["extremes"] = []
        _preserve_flower_branch_after_reforge(
            doc, previous["huafen"], next_levels["huafen"])

    # The original clears achieved extremes and fire/immortal-qi bonuses after
    # every successful reforge, even when the rolled-back track was another path.
    state["xiangu_extremes"] = 0
    state.pop("xiangu_extreme_ids", None)
    xiangu = ext.get("xiangu")
    if isinstance(xiangu, dict):
        xiangu["extremes"] = []
        shenhuo = xiangu.get("shenhuo")
        if next_levels["xiangu"] < 8:
            xiangu.pop("shenhuo", None)
        elif isinstance(shenhuo, dict):
            shenhuo["极境达成"] = False
            shenhuo.pop("极境名称", None)
        xiangu["xianqi"] = 0
        xiangu["xianqi_detail"] = []
        xiangu.pop("xianqi_three_complete", None)
        xiangu.pop("jiutian_shidi", None)
        xiangu.pop("zhanxian_zhadao", None)

    selected = state.get("selected_track")
    if selected == "huafen" and next_levels["huafen"] > INITIAL_TRACK_LEVELS["huafen"]:
        pass
    else:
        state["selected_track"] = None
        if selected in TRACKS:
            for key in ("extra_track", "cultivation_path"):
                if ext.get(key) == selected:
                    ext.pop(key, None)

    return {"changed": True, "previous": previous, "next": next_levels,
            "changed_tracks": changed}


def reforge_text(result: Mapping[str, Any], doc: Any) -> str:
    changed = result.get("changed_tracks") or []
    lines = ["【回炉重造·额外境界回退】"]
    for track in changed:
        lines.append(f"· {TRACK_NAMES[track]}：{result['previous'][track]} → {result['next'][track]}")
    if "huafen" in changed:
        lines.append("花粉极境已清空，可按新境界重新追求。")
    if "xiangu" in changed:
        lines.append("仙古极境已清空；按回退后的境界重置神火与仙气状态。")
    lines.append("练气和炼体境界未变。")
    return "\n".join(lines)
