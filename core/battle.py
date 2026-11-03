"""回合制切磋：原版 Harm 伤害公式的 Python 直译 + 轮流出手。

原版 model/xiuxian.js Harm()：
    s = atk / def
    x = 0.1 (s<1) | 1.0 (s>2.5) | 0.6s-0.5
    dmg = trunc(x * atk * rand * baoji)，rand = trunc(rng*11)/100 + 0.95 ∈ [0.95, 1.05]
暴击（对齐原版）：出手按攻击方 bao 概率触发；暴击伤害倍率 = bao + 1.5，封顶 2.5
（原版：player.暴击伤害 = player.暴击率 + 1.5，>2.5 截断）。
战斗为友好切磋：不分生死奖励、不落持久血量，只出胜负与战报。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

CRIT_BASE = 1.5   # 原版：暴击伤害 = 暴击率 + 1.5
CRIT_CAP = 2.5
MAX_ROUNDS = 30


@dataclass
class Unit:
    name: str
    atk: int
    defense: int
    hp: int
    bao: float = 0.0


def harm(atk: int, defense: int, rng: random.Random, bao: float = 0.0) -> tuple[int, bool]:
    """原版伤害公式直译。返回 (伤害, 是否暴击)。低攻高防时伤害趋近攻击的 10%。"""
    s = atk / defense if defense > 0 else float("inf")
    if s < 1:
        x = 0.1
    elif s > 2.5:
        x = 1.0
    else:
        x = 0.6 * s - 0.5
    rand = int(rng.random() * 11) / 100 + 0.95
    crit = rng.random() < bao
    mult = min(bao + CRIT_BASE, CRIT_CAP) if crit else 1.0
    return int(x * atk * rand * mult), crit


def spar_full(
    a: Unit, b: Unit, rng: random.Random, max_rounds: int = MAX_ROUNDS,
    skip_first: tuple[int, ...] = (),
) -> tuple[int | None, list[str], int, int]:
    """同 spar，另返回双方剩余血量 (winner, log, a_hp_left, b_hp_left)。

    W1-1 起为薄壳：逻辑迁入 core/combat/engine.py（行为等价，自检兜底），
    新效果（护盾/反噬/汲取/技能）请直接用 combat.run_1v1 + Fighter.effects。
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
