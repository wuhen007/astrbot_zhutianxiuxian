"""1v1 回合引擎（W1-1 骨架）。

行为契约：与旧 battle.spar_full **完全等价**——同一 rng 种子、无效果时，
胜者/战报/剩余血量逐一相同（自检 16s 等价断言兜底）。在其上新增效果槽：

- stun_turns        定身 N 个己方回合（黑皇困龙阵等），跳过出手
- shield            护盾值，先于血量吸收伤害
- dmg_dealt_mult    出手伤害倍率（乘区）
- dmg_taken_mult    受击伤害倍率（乘区）
- reflect           反噬比例：受击方按造成伤害的百分比反弹给出手方
- lifesteal         汲取比例：出手方按造成伤害的百分比回血（不超上限）

技能（skills 注册表）在每次出手前触发 on_turn 钩子，可修改双方效果槽或直接写战报。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .. import battle
from . import skills

DEFAULT_MAX_ROUNDS = battle.MAX_ROUNDS


@dataclass
class Fighter:
    """战斗单位：数值来自 battle.Unit，战斗内临时状态放 effects。"""

    name: str
    atk: int
    defense: int
    hp: int
    hp_max: int
    bao: float = 0.0
    effects: dict[str, Any] = field(default_factory=dict)
    skills: tuple[str, ...] = ()
    tags: dict[str, Any] = field(default_factory=dict)   # 帝骑/宿云/黑皇等旗标（W1-4）

    @classmethod
    def from_unit(cls, u: battle.Unit) -> "Fighter":
        return cls(name=u.name, atk=int(u.atk), defense=int(u.defense),
                   hp=int(u.hp), hp_max=int(u.hp), bao=float(u.bao or 0.0))

    def eff(self, key: str, default: Any = 0) -> Any:
        return self.effects.get(key, default)


@dataclass
class BattleResult:
    winner: int | None          # 0=A，1=B，None=平局
    log: list[str]
    a_hp: int
    b_hp: int

    def as_tuple(self) -> tuple[int | None, list[str], int, int]:
        return self.winner, self.log, self.a_hp, self.b_hp


def _try_revive(f: Fighter, hp: list[int], idx: int, log: list[str], rng: random.Random) -> bool:
    """致死一击的复活判定（原版 performRevival：掷 pr，恢复 上限×比例，一场一次）。"""
    rev = f.eff("revive")
    if not isinstance(rev, dict) or rev.get("used"):
        return False
    raw_pr = rev.get("pr")
    pr = 1.0 if raw_pr is None else min(1.0, max(0.0, float(raw_pr)))   # pr=0 合法：永不触发
    if rng.random() >= pr:
        return False
    rev["used"] = True
    hp[idx] = max(1, int(f.hp_max * min(1.0, max(0.05, float(rev.get("ratio", 0.7) or 0.7)))))
    msg = str(rev.get("msg") or "")
    name = str(rev.get("name") or "复活技")
    log.append(f"【{name}】{msg}" + (f"｜{f.name} 复活，血量 {hp[idx]}" if hp[idx] else ""))
    return True


def run_1v1(
    a: Fighter, b: Fighter, rng: random.Random,
    max_rounds: int = DEFAULT_MAX_ROUNDS, skip_first: tuple[int, ...] = (),
) -> BattleResult:
    """A 先手轮流出手；先清空对方血者胜，打满按剩余血量比例判定。"""
    sides = [a, b]
    hp = [a.hp, b.hp]
    winner: int | None = None
    skipped: set[int] = set()
    log: list[str] = []

    for rnd in range(1, max_rounds + 1):
        i, j = (0, 1) if rnd % 2 else (1, 0)
        atk_u, def_u = sides[i], sides[j]
        if i in skip_first and i not in skipped:
            skipped.add(i)
            log.append(f"第{rnd}回合：{atk_u.name}被大阵困住，无法出手")
            continue
        stun = int(atk_u.eff("stun_turns", 0) or 0)
        if stun > 0:
            atk_u.effects["stun_turns"] = stun - 1
            log.append(f"第{rnd}回合：{atk_u.name}被定身，无法出手")
            continue

        # 技能钩子（W1-2 起有注册项；现在为空注册表的扩展点）
        for sid in atk_u.skills:
            spec = skills.get(sid)
            if spec and spec.on_turn:
                spec.on_turn(atk_u, def_u, {"rng": rng, "round": rnd, "log": log})

        dmg, crit = battle.harm(
            max(1, int(atk_u.atk * float(atk_u.eff("dmg_dealt_mult", 1.0)))),
            max(1, int(def_u.defense * float(def_u.eff("dmg_taken_mult", 1.0)))),
            rng, atk_u.bao,
        )
        # 护盾先吸收
        shield = int(def_u.eff("shield", 0) or 0)
        suffix = ""
        if shield > 0:
            absorbed = min(shield, dmg)
            def_u.effects["shield"] = shield - absorbed
            dmg -= absorbed
            if absorbed:
                suffix += f"（护盾吸收 {absorbed}）"
        hp[j] = max(0, hp[j] - dmg)
        line = (f"第{rnd}回合：{atk_u.name}出手，对{def_u.name}造成 {dmg} 点伤害"
                + ("（暴击！）" if crit else "") + suffix
                + f"，{def_u.name}剩余 {hp[j]}")
        # 反噬 / 汲取（按实际造成的伤害；护盾吸收部分不触发）
        dealt = dmg
        reflect = float(def_u.eff("reflect", 0.0) or 0.0)
        if reflect > 0 and dealt > 0:
            back = min(int(dealt * reflect), hp[i])
            if back > 0:
                hp[i] -= back
                line += f"，反噬 {back}"
        lifesteal = float(atk_u.eff("lifesteal", 0.0) or 0.0)
        if lifesteal > 0 and dealt > 0:
            heal = min(int(dealt * lifesteal), atk_u.hp_max - hp[i])
            if heal > 0:
                hp[i] += heal
                line += f"，汲取 {heal}"
        log.append(line)
        if hp[j] <= 0:
            if _try_revive(def_u, hp, j, log, rng):
                continue
            winner = i
            break
        if hp[i] <= 0:      # 反噬致死
            if _try_revive(atk_u, hp, i, log, rng):
                continue
            winner = j
            break

    if winner is None:
        ratio_a = hp[0] / a.hp if a.hp > 0 else 0.0
        ratio_b = hp[1] / b.hp if b.hp > 0 else 0.0
        if abs(ratio_a - ratio_b) >= 1e-9:
            winner = 0 if ratio_a > ratio_b else 1
    return BattleResult(winner, log, hp[0], hp[1])
