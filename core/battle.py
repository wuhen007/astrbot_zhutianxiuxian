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

    skip_first：首回合无法出手的一方下标（0=a，1=b），用于「山河困龙阵」等定身效果。
    """
    log: list[str] = []
    units = [a, b]
    hp = [a.hp, b.hp]
    winner: int | None = None
    skipped: set[int] = set()

    for rnd in range(1, max_rounds + 1):
        i, j = (0, 1) if rnd % 2 else (1, 0)
        if i in skip_first and i not in skipped:
            skipped.add(i)
            log.append(f"第{rnd}回合：{units[i].name}被大阵困住，无法出手")
            continue
        atk_u, def_u = units[i], units[j]
        dmg, crit = harm(atk_u.atk, def_u.defense, rng, atk_u.bao)
        hp[j] = max(0, hp[j] - dmg)
        log.append(
            f"第{rnd}回合：{atk_u.name}出手，对{def_u.name}造成 {dmg} 点伤害"
            + ("（暴击！）" if crit else "")
            + f"，{def_u.name}剩余 {hp[j]}"
        )
        if hp[j] <= 0:
            winner = i
            break

    if winner is None:
        ratio_a = hp[0] / a.hp if a.hp > 0 else 0.0
        ratio_b = hp[1] / b.hp if b.hp > 0 else 0.0
        if abs(ratio_a - ratio_b) < 1e-9:
            winner = None
        else:
            winner = 0 if ratio_a > ratio_b else 1
    return winner, log, hp[0], hp[1]


def spar(
    a: Unit, b: Unit, rng: random.Random, max_rounds: int = MAX_ROUNDS
) -> tuple[int | None, list[str]]:
    """切磋模拟：A 先手轮流出手，先打空对方血者胜；打满回合按剩余血量比例判定。

    返回 (胜者索引 0/1 或 None=平局, 战报行)。
    """
    winner, log, _, _ = spar_full(a, b, rng, max_rounds)
    return winner, log
