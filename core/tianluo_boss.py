"""Shared ascension-intercept boss translated from the pinned Tianluo source."""
from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from .plane_travel_rules import ALL_HEAVENS

STATE_KEY = "tianluo_jailer"
BOSS_NAME = "囚牢之主·无面冥葬"
BONUS = 75_000_000
MAX_ROUNDS = 8
SPIRIT_CAPTURE_MIN = 100_000
ALL_HEAVENS_LOCATION_VALUES = frozenset({0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.2, 3.5, 4.0, 5.0, 6.0, 7.0})

SKILLS = (
    {"name": "天罗缚魂", "damage": .75, "bind": True},
    {"name": "无面凝视", "damage": .85, "seal_crit": True},
    {"name": "万灵噬魂", "damage": 1.0, "spirit_drain": .1},
    {"name": "葬世之门", "damage": 1.25, "defense_ignore": .35},
)


def boss_stats(cultivation_rows: Sequence[Mapping], physique_rows: Sequence[Mapping]) -> dict[str, int | float]:
    qi = next((row for row in cultivation_rows if int(row.get("level_id", 0) or 0) == 42), None)
    body = next((row for row in physique_rows if int(row.get("level_id", 0) or 0) == 50), None)
    if not qi or not body:
        raise ValueError("囚牢之主需要练气第42境和炼体第50境的原版属性行")
    return {
        "atk": int(qi["基础攻击"]) + int(body["基础攻击"]) + BONUS,
        "defense": int(qi["基础防御"]) + int(body["基础防御"]) + BONUS,
        "hp": int(qi["基础血量"]) + int(body["基础血量"]) + BONUS,
        "bao": min(1.0, float(qi.get("基础暴击", 0) or 0) + float(body.get("基础暴击", 0) or 0)),
    }


def ensure_state(world: dict, max_hp: int, initial_alive: bool = True) -> dict[str, Any]:
    """Keep one durable full-server health bar in calamity_state.

    The pinned original has no in-code activation writer and requires its world
    file flag to be 1; this port deliberately enables a fresh install once so
    the encounter remains reachable. Any persisted alive/defeated state wins.
    """
    row = world.get(STATE_KEY)
    if not isinstance(row, dict):
        row = {"alive": bool(initial_alive), "hp": int(max_hp) if initial_alive else 0,
               "max_hp": int(max_hp), "defeated_by": "", "defeated_at": 0.0}
        world[STATE_KEY] = row
    old_max = max(1, int(row.get("max_hp", max_hp) or max_hp))
    hp = max(0, min(old_max, int(row.get("hp", old_max if row.get("alive") else 0) or 0)))
    row["max_hp"] = int(max_hp)
    row["hp"] = min(int(max_hp), math.floor(hp * int(max_hp) / old_max)) if old_max != max_hp else hp
    row["alive"] = bool(row.get("alive", initial_alive)) and row["hp"] > 0
    if not row["alive"]:
        row["hp"] = 0
    return row


def damage_shared(state: dict, requested: int, now: float, killer_uid: str = "") -> dict[str, Any]:
    if not state.get("alive"):
        return {"damage": 0, "hp": 0, "defeated": False, "already_defeated": True}
    before = max(0, int(state.get("hp", 0) or 0))
    damage = min(before, max(0, int(requested)))
    state["hp"] = before - damage
    defeated = state["hp"] <= 0
    if defeated:
        state["hp"] = 0
        state["alive"] = False
        state["defeated_by"] = str(killer_uid or "")
        state["defeated_at"] = float(now)
    return {"damage": damage, "hp": int(state["hp"]), "defeated": defeated, "already_defeated": False}


def player_damage(player_atk: int, player_crit: float, boss_defense: int,
                  bind_layers: int, sealed_crit: bool, rng: random.Random) -> tuple[int, bool]:
    effective_atk = math.floor(int(player_atk) * max(.4, 1 - max(0, bind_layers) * .1))
    variance = .85 + rng.random() * .3
    critical = not sealed_crit and rng.random() < float(player_crit or 0)
    crit_multiplier = 1.8 if critical else 1.0
    requested = math.floor(effective_atk * variance * crit_multiplier *
                            (1 - boss_defense / (boss_defense + effective_atk * 5)))
    return max(0, requested), critical


def boss_damage(round_no: int, boss_atk: int, boss_crit: float,
                player_defense: int, rng: random.Random) -> tuple[int, dict[str, Any]]:
    skill = SKILLS[min(max(1, int(round_no)) // 2 - 1, len(SKILLS) - 1)]
    effective_def = int(player_defense) * (1 - float(skill.get("defense_ignore", 0) or 0))
    variance = .9 + rng.random() * .2
    critical = rng.random() < float(boss_crit or 0)
    multiplier = 2.0 if critical else 1.0
    damage = math.floor(boss_atk * float(skill["damage"]) * variance * multiplier *
                        (1 - effective_def / (effective_def + boss_atk * 3)))
    return max(0, damage), {**skill, "critical": critical}


def is_all_heavens_location(location: Any) -> bool:
    """原版 #登仙 只允许诸天万界位面，兼容旧存档的数值 power_place。"""
    if location is None:
        return True  # 原版使用 power_place ?? PLACE_LOCATION_MAP.凡间
    if isinstance(location, str):
        name = location.strip()
        if name in ALL_HEAVENS:
            return True
        try:
            location = float(name)
        except (TypeError, ValueError, OverflowError):
            return False
    try:
        return float(location) in ALL_HEAVENS_LOCATION_VALUES
    except (TypeError, ValueError, OverflowError):
        return False
