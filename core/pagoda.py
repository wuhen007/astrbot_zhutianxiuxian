"""镇妖塔 / 炼神魄 数值门面（实现在 core/adventure.py 与 core/boss.py）。

`#挑战镇妖塔` / `#一键挑战镇妖塔` 走 `adventure.tower_fight`（ext["tower_floor"]），
`#炼神魄` / `#一键炼神魄` 走 `boss.shenpo_specs` + main.py 的 `_shenpo_round`（ext["shenpo"]）。
本模块只把同一组数值以统一签名导出，供自检做一致性断言（防两处数值漂移），
以及 `#镇妖塔榜` 复用层数上限常量。

数值（原版 apps/pata/tzzyt.js、apps/pata/DSC.js）：
· 镇妖塔 第 f 层：血 50000f+10000、攻 22000f+10000、防 36000f+10000；
  奖励 f<100 → 100f+100；100≤f<200 → 200f+1000；f≥200 → 300f+1000；上限 400000。
· 炼神魄 第 s 段：血 100000s、攻 250000s、防 200000s；奖励 1200s（上限 400000）。
败北惩罚均为 2× 奖励；层数/段数每次 +5，硬上限 50000。
"""

from __future__ import annotations

from typing import Any

from .adventure import TOWER_MAX, tower_boss, tower_reward
from .boss import shenpo_specs

MAX_FLOOR = TOWER_MAX      # 50000，原版硬上限
FLOOR_STEP = 5

KIND_ZYT = "zyt"
KIND_SHENPO = "shenpo"

NAMES = {
    KIND_ZYT: ("镇妖塔", "未知妖物", "层", "灵石"),
    KIND_SHENPO: ("炼神魄", "锻神池", "段", "血气"),
}


def clamp_floor(value: Any) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_FLOOR, n))


def boss_spec(kind: str, stage: int) -> tuple[int, int, int]:
    """(气血, 攻击, 防御)，与实装同源。"""
    s = max(0, int(stage))
    if kind == KIND_ZYT:
        b = tower_boss(s)
        return b["hp"], b["atk"], b["defense"]
    hp, atk, defense, _reward = shenpo_specs(s)
    return hp, atk, defense


def reward_of(kind: str, stage: int) -> int:
    s = max(0, int(stage))
    if kind == KIND_SHENPO:
        return shenpo_specs(s)[3]
    return tower_reward(s)


def penalty_of(kind: str, stage: int) -> int:
    return 2 * reward_of(kind, stage)


def status_text(kind: str, stage: int) -> str:
    title, foe, unit, currency = NAMES[kind]
    hp, atk, defense = boss_spec(kind, stage)
    return (
        f"【{title}】第 {stage} {unit}\n"
        f"下一战·{foe}：气血 {hp:,} 攻击 {atk:,} 防御 {defense:,}\n"
        f"通关可得 {reward_of(kind, stage):,} {currency}，失败扣除 {penalty_of(kind, stage):,} {currency}"
    )
