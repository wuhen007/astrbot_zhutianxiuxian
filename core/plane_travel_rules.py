"""Pure travel rules for journeys that involve the Foreign Realm.

Rules mirror the pinned original snapshot 04af6a9a7ec11e700a0aedb85a5981e48826035c:
model/weimianTravel.js and apps/SecretPlace/SecretPlace.js. The Foreign Realm
is an abstract known destination (plane id 3.2), not a map.
"""
from __future__ import annotations

import math

FOREIGN_REALM = "异域"
TIME_RIVER = "时间长河"
FOREIGN_REALM_LEVEL = 3.2
TIME_RIVER_LEVEL = 3.6
BASE_TRAVEL_MINIMUM_INDEX = 41  # Original level_id/Physique_id 42, stored 0-based here.
FOREIGN_AUTHORITY_GATE = 18
INSTANT_ALL_HEAVENS_GATE = 20
EMPEROR_FREE_TRAVEL_GATE = 21
REALM_REDUCTION_MAX = 0.7
REALM_REDUCTION_MAX_LEVEL = 21
BASE_MINUTES_PER_LEVEL = 15
EXP_PER_LEVEL = 10_000_000
XUEQI_PER_LEVEL = 15_000_000
LIFESPAN_PER_LEVEL = 10_000
BARRIER_EXP_PER_LAYER = 1_000_000_000
BARRIER_XUEQI_PER_LAYER = 1_500_000_000
BARRIER_LIFESPAN_PER_LAYER = 100_000

ALL_HEAVENS = frozenset({
    "凡间", "仙界", "下界八域", "遮天位面", "九天十地", "界海", FOREIGN_REALM,
    "太初星墟", "小阴间", "大阴间", "仙域", "阳间",
})
EMPEROR_FREE_LOCATIONS = ALL_HEAVENS | frozenset({
    "上苍之上", "永恒未知之地", "厄土高原", TIME_RIVER,
})
EMPEROR_INSTANT_LOCATIONS = ALL_HEAVENS | frozenset({"上苍之上"})


def _js_round(value: float) -> int:
    """Match JavaScript Math.round for the non-negative travel values here."""
    return math.floor(value + 0.5)


def _finite(value: float | int | None) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _flower_authority(level: int) -> int:
    """Original flower-route mapping from model/realmAuthority.js."""
    mapping = (
        (25, 24), (24, 23), (23, 22), (22, 21), (21, 20), (20, 19),
        (18, 18), (17, 17), (15, 16), (14, 15), (13, 14), (12, 13),
        (11, 12), (10, 11), (8, 10), (7, 9), (6, 8), (5, 7), (4, 6),
    )
    return next((rank for required, rank in mapping if level >= required), level)


def quote_foreign_travel(
    source: str,
    target: str,
    *,
    authority: int,
    realm_index: int,
    physique_index: int,
    coordinate_known: bool,
    suiyun_set: bool,
    kunpeng_minutes: float = 0,
    source_level: float,
    source_barrier_layer: int = 0,
    target_level: float | None = None,
    target_barrier_layer: int = 0,
    realm_reduce_level: int | None = None,
    route_levels: tuple[int, int, int] | None = None,
) -> dict[str, bool | str | int | float | None]:
    """Quote a journey to or from the Foreign Realm.

    `authority` is the original 1-based equivalent authority rank. The two
    base indices are this port's 0-based Qi/physique indices. `route_levels`
    contains the original 1-based (mijing, xiangu, huafen) levels; when
    provided, it reproduces both the time-river gate and original trip discount.
    `realm_reduce_level` is a fallback for the original discount. The optional
    target level/layer supports journeys leaving the Foreign Realm.
    """
    empty = {
        "ok": False,
        "reason": "",
        "enough_base": False,
        "enough_authority": False,
        "needs_coordinate": False,
        "instant": False,
        "distance": 0.0,
        "exp": 0,
        "xueqi": 0,
        "shouyuan": 0,
        "minutes": 0,
        "time_river_gate": None,
    }
    source = str(source or "")
    target = str(target or "")
    if FOREIGN_REALM not in (source, target):
        empty["reason"] = "unsupported-route"
        return empty

    involves_time_river = TIME_RIVER in (source, target)
    if source == FOREIGN_REALM:
        source_level, source_barrier_layer = FOREIGN_REALM_LEVEL, 0
    elif source == TIME_RIVER:
        source_level, source_barrier_layer = TIME_RIVER_LEVEL, -1
    if target == FOREIGN_REALM:
        target_level, target_barrier_layer = FOREIGN_REALM_LEVEL, 0
    elif target == TIME_RIVER:
        target_level, target_barrier_layer = TIME_RIVER_LEVEL, -1
    elif target_level is None or not _finite(target_level):
        empty["reason"] = "missing-target-level"
        return empty
    if not _finite(source_level):
        empty["reason"] = "missing-source-level"
        return empty

    try:
        rank = max(0, int(authority))
        source_layer = int(source_barrier_layer)
        target_layer = int(target_barrier_layer)
        qi_index = int(realm_index)
        body_index = int(physique_index)
        route = tuple(max(1, int(value)) for value in route_levels) if route_levels is not None else None
        if route is not None and len(route) != 3:
            raise ValueError("route_levels must contain exactly three levels")
        if route is not None:
            raw_realm = max(route[0], route[1], _flower_authority(route[2]))
        else:
            raw_realm = max(0, int(realm_reduce_level if realm_reduce_level is not None else rank))
        kunpeng = max(0.0, float(kunpeng_minutes))
    except (TypeError, ValueError, OverflowError):
        empty["reason"] = "invalid-travel-input"
        return empty

    emperor_free = (
        rank >= EMPEROR_FREE_TRAVEL_GATE
        and source in EMPEROR_FREE_LOCATIONS
        and target in EMPEROR_FREE_LOCATIONS
    )
    instant = (
        rank >= INSTANT_ALL_HEAVENS_GATE
        and source in ALL_HEAVENS
        and target in ALL_HEAVENS
    ) or (
        rank >= EMPEROR_FREE_TRAVEL_GATE
        and source in EMPEROR_INSTANT_LOCATIONS
        and target in EMPEROR_INSTANT_LOCATIONS
    )
    enough_base = emperor_free or (
        qi_index >= BASE_TRAVEL_MINIMUM_INDEX
        and body_index >= BASE_TRAVEL_MINIMUM_INDEX
    )
    if target == TIME_RIVER:
        time_river_gate = (
            route[0] >= 20 or route[1] >= 20 or route[2] >= 21
            if route is not None else rank >= 20
        ) or emperor_free
    else:
        time_river_gate = None
    enough_authority = (
        (target != FOREIGN_REALM or rank >= FOREIGN_AUTHORITY_GATE)
        and (target != TIME_RIVER or bool(time_river_gate))
    ) or emperor_free
    needs_coordinate = not (emperor_free or bool(suiyun_set))
    coordinate_ok = not needs_coordinate or bool(coordinate_known)

    barriers = abs(source_layer - target_layer)
    level_distance = abs(float(source_level) - float(target_level))
    distance = float(barriers) if barriers else level_distance
    ok = enough_base and coordinate_ok and enough_authority
    reason = (
        "" if ok else "base-gate" if not enough_base else
        "coordinate-unknown" if not coordinate_ok else
        "time-river-gate" if target == TIME_RIVER and not time_river_gate else
        "authority-gate"
    )
    if distance == 0:
        return {
            **empty,
            "ok": ok,
            "reason": reason,
            "enough_base": enough_base,
            "enough_authority": enough_authority,
            "needs_coordinate": needs_coordinate,
            "instant": instant,
            "time_river_gate": time_river_gate,
        }

    realm_multiplier = 1 - min(
        REALM_REDUCTION_MAX,
        raw_realm / REALM_REDUCTION_MAX_LEVEL * REALM_REDUCTION_MAX,
    )
    if barriers:
        exp = _js_round(barriers * BARRIER_EXP_PER_LAYER * realm_multiplier)
        xueqi = _js_round(barriers * BARRIER_XUEQI_PER_LAYER * realm_multiplier)
        shouyuan = _js_round(barriers * BARRIER_LIFESPAN_PER_LAYER * realm_multiplier)
        if involves_time_river:
            travel_multiplier = (
                0.2 if rank >= 24 else 0.35 if rank >= 23 else
                0.55 if rank >= 22 else 0.75
            )
            if rank >= EMPEROR_FREE_TRAVEL_GATE:
                travel_multiplier = min(travel_multiplier, 0.3)
            barrier_minutes = max(1, _js_round(barriers * 60 * travel_multiplier))
        else:
            barrier_minutes = max(1, _js_round(
                max(2, level_distance * BASE_MINUTES_PER_LEVEL * realm_multiplier)
                * barriers
            ))
        minutes = 0 if instant else max(1, barrier_minutes - kunpeng)
    else:
        exp = _js_round(distance * EXP_PER_LEVEL * realm_multiplier)
        xueqi = _js_round(distance * XUEQI_PER_LEVEL * realm_multiplier)
        shouyuan = _js_round(distance * LIFESPAN_PER_LEVEL * realm_multiplier)
        minutes = 0 if instant else _js_round(max(
            1,
            max(2, distance * BASE_MINUTES_PER_LEVEL * realm_multiplier) - kunpeng,
        ))

    if suiyun_set:
        shouyuan = 0
        minutes = 0
    return {
        "ok": ok,
        "reason": reason,
        "enough_base": enough_base,
        "enough_authority": enough_authority,
        "needs_coordinate": needs_coordinate,
        "instant": instant,
        "distance": distance,
        "exp": exp,
        "xueqi": xueqi,
        "shouyuan": shouyuan,
        "minutes": minutes,
        "time_river_gate": time_river_gate,
    }
