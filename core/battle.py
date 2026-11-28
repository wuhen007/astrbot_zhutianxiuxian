"""原版战斗伤害原语与 1v1 兼容入口。

`harm` 对应 xiuxian.js `Harm` 的固定倍数；`calculate_harm` 对应
`calculateHarm`（包含其超安全整数分支）。暴击机会由 `baojishanghai`
单独抽取，`attack_harm` 保持原版先暴击抽样、再伤害浮动的随机调用顺序。
"""

from __future__ import annotations

import math
import random
from math import floor
from dataclasses import dataclass

CRIT_BASE = 1.5
CRIT_CAP = 2.5
JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991
ACTION_BAR_MAX = 5_000
ACTION_BAR_ADVANCE_LIMIT = 100
MAX_ROUNDS = 100


@dataclass
class Unit:
    name: str
    atk: int
    defense: int
    hp: int
    bao: float = 0.0
    speed: int = 100
    action_bar: int = 0
    crit_damage: float | None = None


def speed_of(doc: Any) -> int:
    """将原版 getBattleUnitSpeed 的已移植字段合成为本场基础行动速度。"""
    ext = getattr(doc, "ext", {}) or {}
    ext = ext if isinstance(ext, dict) else {}
    legacy = ext.get("legacy_source") or {}
    legacy = legacy if isinstance(legacy, dict) else {}

    def value(key: str, default: float = 0.0) -> float:
        legacy_key = "速度" if key == "speed" else key
        raw = ext.get(key, legacy.get(legacy_key, default))
        try:
            return float(raw if raw is not None else default)
        except (TypeError, ValueError):
            return default

    base = value("speed", 100.0)
    ignore_tracks = bool(ext.get("ignore_realm_speed") or legacy.get("_忽略境界速度加成"))
    track_speed = 0.0
    if not ignore_tracks:
        from . import extra_cultivation
        tracks = extra_cultivation.levels_of(doc)
        track_speed = (tracks["mijing"] + tracks["xiangu"]
                       + max(0, tracks["huafen"] - 1)) * 50
    evergreen = 0.0
    try:
        from . import suiyun
        if suiyun.stage_of(doc) > 0:
            evergreen = 200.0
    except (AttributeError, TypeError, ValueError):
        pass
    mingge_speed = 0.0
    try:
        from . import mingge
        mingge_speed = float(mingge.bonus(doc, "速度") or 0)
    except (AttributeError, TypeError, ValueError):
        pass
    innate_speed = 1.0
    xtzb_state = ext.get("xtzb") or {}
    if isinstance(xtzb_state, dict) and xtzb_state.get("current") == "逐日仙辇":
        innate_speed = 1.1
    return max(1, math.floor((base + track_speed + evergreen + mingge_speed) * innate_speed))


def _raid_ready_units(units, bars: dict[str, int], limit: int = ACTION_BAR_ADVANCE_LIMIT):
    """原版团本每大回合推进行动条，达到阈值的全体按源规则排序行动。"""
    for _ in range(max(1, int(limit))):
        for unit in units:
            key = str(unit.tags.get("key") or id(unit))
            if unit.hp <= 0:
                continue
            down = max(0.0, float(unit.eff("speed_down_pct", 0) or 0))
            speed = max(1, int(unit.speed * unit.speed_boost * (1 - down)))
            bars[key] = bars.get(key, int(unit.action_bar or 0)) + speed
        ready = [unit for unit in units
                 if unit.hp > 0 and bars.get(str(unit.tags.get("key") or id(unit)), 0) >= ACTION_BAR_MAX]
        if ready:
            ready.sort(key=lambda unit: (
                -int(bool(unit.tags.get("absolute_first"))),
                -int(unit.speed),
                -int(bars.get(str(unit.tags.get("key") or id(unit)), 0)),
            ))
            return ready
    return []


def initial_action_bar(doc: Any) -> int:
    """原版行字秘/鲲鹏宝术出神入化时获得开局满行动条。"""
    ext = getattr(doc, "ext", {}) or {}
    if not isinstance(ext, dict):
        return 0
    legacy = ext.get("legacy_source") or {}
    legacy = legacy if isinstance(legacy, dict) else {}
    learned = {str(name) for name in (ext.get("gongfa") or legacy.get("学习的功法") or [])}
    if not learned.intersection(("行字秘", "鲲鹏宝术")):
        return 0
    prof = ext.get("prof") or legacy.get("功法熟练度") or {}
    if not isinstance(prof, dict):
        return 0
    bar = ACTION_BAR_MAX if any(float(prof.get(name, 0) or 0) >= 1000
                                for name in learned.intersection(("行字秘", "鲲鹏宝术"))) else 0
    if bool(ext.get("乱古战意") or legacy.get("乱古战意")):
        bar += int(ACTION_BAR_MAX * 0.5)
    return bar


def _damage_factor(atk: float, defense: float) -> float:
    ratio = atk / defense if defense else float("inf")
    if ratio < 1:
        return 0.1
    if ratio > 2.5:
        return 1.0
    return 0.6 * ratio - 0.5


def _random_damage(atk: float, defense: float, rng, multiplier: float) -> int:
    rand = int(rng.random() * 11) / 100 + 0.95
    return int(_damage_factor(atk, defense) * atk * rand * multiplier)


def harm(atk: int | float, defense: int | float, rng: random.Random,
         baoji: float = 1.0) -> tuple[int, bool]:
    """原版 `Harm`：baoji 是固定伤害倍率；暴击概率由调用方另行抽取。"""
    multiplier = float(baoji)
    return _random_damage(atk, defense, rng, multiplier), multiplier > 1.0


def calculate_harm(atk: int | float, defense: int | float, rng: random.Random,
                   baoji: float = 1.0) -> int:
    """原版 `calculateHarm`，包括 JS 安全整数以上的 BigInt 计算分支。"""
    atk_num, defense_num = float(atk), float(defense)
    if atk_num > JS_MAX_SAFE_INTEGER or defense_num > JS_MAX_SAFE_INTEGER:
        big_atk = floor(atk_num + 0.5)
        big_defense = floor(defense_num + 0.5)
        numerator = big_atk * 850
        big_damage = abs(numerator) // 1000 * (1 if numerator >= 0 else -1) - big_defense
        return max(0, big_damage)
    return _random_damage(atk_num, defense_num, rng, float(baoji))


def baojishanghai(bao: float, rng: random.Random, crit_damage: float = CRIT_BASE) -> float:
    """原版暴击倍率抽样；暴击率钳制到 0..1，伤害倍率下限为 1。"""
    rate = min(1.0, max(0.0, float(bao or 0)))
    multiplier = max(float(crit_damage or CRIT_BASE), 1.0)
    return multiplier if rng.random() < rate else 1.0


def attack_harm(atk: int | float, defense: int | float, rng: random.Random,
                bao: float = 0.0, crit_damage: float | None = None) -> tuple[int, bool]:
    """组合原版独立暴击抽样与 Harm；保留原版 RNG 消耗顺序。"""
    rate = min(1.0, max(0.0, float(bao or 0)))
    multiplier = (min(rate + CRIT_BASE, CRIT_CAP)
                  if crit_damage is None else max(float(crit_damage), 1.0))
    rolled = baojishanghai(rate, rng, multiplier)
    damage, _ = harm(atk, defense, rng)
    return int(damage * rolled), rolled > 1.0


def spar_full(
    a: Unit, b: Unit, rng: random.Random, max_rounds: int = MAX_ROUNDS,
    skip_first: tuple[int, ...] = (),
) -> tuple[int | None, list[str], int, int]:
    """同 spar，另返回双方剩余血量 (winner, log, a_hp_left, b_hp_left)。

    `run_1v1` 按原版 5000 点行动条和速度选择出手；新效果（护盾/反噬/汲取/技能）
    请使用 `combat.run_1v1` 与 `Fighter.effects`。
    skip_first：首回合无法出手的一方下标（0=a，1=b），用于「山河困龙阵」等定身效果。
    """
    from .combat import Fighter, run_1v1

    fa, fb = Fighter.from_unit(a), Fighter.from_unit(b)
    return run_1v1(fa, fb, rng, max_rounds=max_rounds, skip_first=skip_first).as_tuple()


def spar(
    a: Unit, b: Unit, rng: random.Random, max_rounds: int = MAX_ROUNDS
) -> tuple[int | None, list[str]]:
    """切磋模拟：A 先手轮流出手，先打空对方血者胜；打满回合按剩余血量比例判定。

    返回 (胜者索引 0/1 或 None=平局, 战报行)。
    """
    winner, log, _, _ = spar_full(a, b, rng, max_rounds)
    return winner, log
