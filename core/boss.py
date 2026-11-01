"""世界 Boss：轮次递进的共享实体（纯函数部分，无 IO）。

对齐原版 apps/Boss/BOSS.js 的核心规则：
- 幻影属性 = 讨伐者属性 × (0.8 + 0.6×随机)，人人打的是"自己的妖王幻影"
- 胜：对 Boss 本体伤害 = 上限×5% + Harm(攻×0.85, 幻影防)×6
- 负：上限×3% + Harm(攻×0.85, 幻影防)×4
- 参战门槛：当前血量 > 上限×10%
- 击杀者额外奖励（原版固定 100w → 这里改为奖池加成比例，可配）
轮次递进：血量/奖池 = 基数 × 1.5^(轮次-1)。
"""

from __future__ import annotations

import random
from collections.abc import Mapping

from .battle import Unit, harm

BASE_HEALTH = 1_000_000
BASE_REWARD = 500_000
GROWTH = 1.5
SHADOW_RANGE = (0.8, 1.4)   # 幻影属性浮动区间（原版 0.8 + 0.6×random）
WIN_RATE, LOSE_RATE = 0.05, 0.03
WIN_MULT, LOSE_MULT = 6, 4
KILLER_BONUS = 0.10         # 击杀者额外奖励（占奖池比例）


def boss_specs(round_no: int) -> tuple[int, int]:
    """第 round_no 轮的 (血量, 奖池)。"""
    factor = GROWTH ** (round_no - 1)
    return int(BASE_HEALTH * factor), int(BASE_REWARD * factor)


def make_shadow(atk: int, defense: int, hp: int, rng: random.Random) -> Unit:
    """按讨伐者属性生成妖王幻影。"""
    lo, hi = SHADOW_RANGE

    def roll(v: int) -> int:
        return max(1, int(v * (lo + (hi - lo) * rng.random())))

    return Unit("妖王幻影", roll(atk), roll(defense), roll(hp))


def boss_damage(won: bool, atk: int, shadow_def: int, health_max: int, rng: random.Random) -> int:
    """讨伐对 Boss 本体造成的伤害（无论幻影战胜负都有产出，对齐原版）。"""
    base = health_max * (WIN_RATE if won else LOSE_RATE)
    mult = WIN_MULT if won else LOSE_MULT
    raw, _ = harm(int(atk * 0.85), shadow_def, rng)
    return int(base + raw * mult)


def split_rewards(
    reward: int,
    ledger: Mapping[str, tuple[str, int]],
    killer_uid: str | None,
) -> list[tuple[str, str, int]]:
    """按贡献比例分奖池；击杀者额外 +KILLER_BONUS。返回 (uid, 名字, 灵石)。"""
    total = sum(d for _, d in ledger.values())
    if total <= 0 or not ledger:
        return []
    out: list[tuple[str, str, int]] = []
    for uid, (name, dmg) in ledger.items():
        share = int(reward * dmg / total)
        if killer_uid and uid == killer_uid:
            share += int(reward * KILLER_BONUS)
        if share > 0:
            out.append((uid, name, share))
    out.sort(key=lambda x: -x[2])
    return out
