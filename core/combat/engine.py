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
from collections.abc import Mapping
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


# ------------------------------------------------------- 技能池结算（W1-5）

SKILL_BEILV_CAP = 50.0   # 数据异常钳制（九幽魔体 1e17 / 鹿目圆 100）


def _uses(f: Fighter) -> dict:
    return f.tags.setdefault("skill_uses", {})


def _left(f: Fighter, sk: Mapping) -> int:
    """剩余次数：cnt=-1 无限；cnt≥0 时以 tags.skill_uses 记账。"""
    cnt = int(sk.get("cnt", -1) if sk.get("cnt", -1) is not None else -1)
    if cnt < 0:
        return -1
    return int(_uses(f).get(str(sk.get("name")), cnt))


def _spend(f: Fighter, sk: Mapping) -> None:
    name = str(sk.get("name"))
    left = _left(f, sk)
    if left > 0:
        _uses(f)[name] = left - 1


def try_heal_skills(f: Fighter, hp: list[int], idx: int, rng: random.Random, log: list[str]) -> None:
    """出手前治疗技能：掷 pr → 回复 上限×回复比例（cnt 限次）。"""
    for sk in f.tags.get("heal_skills") or []:
        if _left(f, sk) == 0:
            continue
        pr = float(sk.get("pr", 0) or 0)
        if pr <= 0 or rng.random() >= pr:
            continue
        ratio = min(1.0, max(0.01, float(sk.get("回复比例", 0) or 0)))
        gained = max(1, int(f.hp_max * ratio))
        if hp[idx] >= f.hp_max:
            continue
        hp[idx] = min(f.hp_max, hp[idx] + gained)
        _spend(f, sk)
        log.append(f"【{sk.get('name')}】{sk.get('msg1', '')}"
                   f"｜{f.name} 回复 {min(gained, f.hp_max - hp[idx] + gained):,}，血量 {hp[idx]}")


def roll_attack_skills(
    atk_u: Fighter, def_u: Fighter, dmg: int, rng: random.Random,
) -> tuple[int, list[str]]:
    """出手攻击技能：池内逐条独立掷 pr（对齐原版遍历判定）。

    命中 → 伤害 ×beilv（钳 ≤50，法球不吃倍率）、控制=1 → 定身对手 1 回合、cnt 限次。
    """
    extra: list[str] = []
    for sk in atk_u.tags.get("atk_skills") or []:
        if _left(atk_u, sk) == 0:
            continue
        pr = float(sk.get("pr", 0) or 0)
        if pr <= 0 or rng.random() >= pr:
            continue
        raw_b = sk.get("beilv")
        beilv = 1.0 if raw_b is None else float(raw_b)
        beilv = min(SKILL_BEILV_CAP, max(0.1, beilv))
        dmg = max(1, int(dmg * beilv))
        _spend(atk_u, sk)
        extra.append(f"【{sk.get('name')}】{sk.get('msg1', '')}（伤害 ×{beilv:g}）")
        if int(sk.get("控制", 0) or 0) > 0:
            def_u.effects["stun_turns"] = int(def_u.eff("stun_turns", 0) or 0) + 1
            extra.append(f"【{sk.get('name')}】{sk.get('msg2', '')}（{def_u.name} 被定身）")
    return dmg, extra


def roll_defense_skills(
    def_u: Fighter, dealt: int, rng: random.Random,
) -> tuple[int, list[str]]:
    """受击防御技能：逐条掷 pr → 伤害 ×beilv（beilv=0 完全格挡）；护盾/反弹写效果槽。"""
    extra: list[str] = []
    for sk in def_u.tags.get("def_skills") or []:
        if _left(def_u, sk) == 0:
            continue
        pr = float(sk.get("pr", 0) or 0)
        if pr <= 0 or rng.random() >= pr:
            continue
        _spend(def_u, sk)
        raw_b = sk.get("beilv")
        beilv = 1.0 if raw_b is None else float(raw_b)   # beilv=0 合法：完全格挡（勿用 or 兜底）
        if beilv <= 0:
            extra.append(f"【{sk.get('name')}】{sk.get('msg1', '')}——完全格挡！")
            dealt = 0
        elif beilv < 1.0:
            dealt = max(1, int(dealt * beilv))
            extra.append(f"【{sk.get('name')}】{sk.get('msg1', '')}（{def_u.name} 受伤 ×{beilv:g}）")
        shield_add = int(sk.get("护盾值", 0) or 0)
        if shield_add > 0:
            def_u.effects["shield"] = int(def_u.eff("shield", 0) or 0) + shield_add
        rb = float(sk.get("反弹伤害", 0) or 0)
        if rb > 0:
            def_u.effects["reflect"] = max(float(def_u.eff("reflect", 0) or 0), rb)
    return dealt, extra


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
                # ctx 额外给出当前血量表与出手方下标，供治疗类技能改写真实血量
                spec.on_turn(atk_u, def_u,
                             {"rng": rng, "round": rnd, "log": log, "hp": hp, "side": i})

        # 治疗技能（W1-5）：出手前掷 pr 回血
        try_heal_skills(atk_u, hp, i, rng, log)

        dmg, crit = battle.harm(
            max(1, int(atk_u.atk * float(atk_u.eff("dmg_dealt_mult", 1.0)))),
            max(1, int(def_u.defense * float(def_u.eff("dmg_taken_mult", 1.0)))),
            rng, atk_u.bao,
        )
        # 攻击技能（W1-5）：逐条掷 pr → beilv 乘区（法球不吃倍率）+ 控制定身
        dmg, atk_extra = roll_attack_skills(atk_u, def_u, dmg, rng)
        log.extend(atk_extra)
        # 灵根法球：每击额外 trunc(攻 × 倍率)，不参与暴击放大（原版 伤害 = 暴击伤害 + 法球伤害）
        orb = float(atk_u.eff("orb", 0.0) or 0.0)
        orb_dmg = int(atk_u.atk * orb) if orb > 0 else 0
        dealt = dmg + orb_dmg
        # 防御技能（W1-5）：逐条掷 pr → 减免/格挡；护盾/反弹写效果槽（下次结算生效）
        dealt, def_extra = roll_defense_skills(def_u, dealt, rng)
        log.extend(def_extra)
        # 护盾先吸收（法球并入总伤后一击结算）
        shield = int(def_u.eff("shield", 0) or 0)
        suffix = ""
        if shield > 0:
            absorbed = min(shield, dealt)
            def_u.effects["shield"] = shield - absorbed
            dealt -= absorbed
            if absorbed:
                suffix += f"（护盾吸收 {absorbed}）"
        hp[j] = max(0, hp[j] - dealt)
        if orb_dmg > 0:
            suffix += f"，法球 {orb_dmg}"
        line = (f"第{rnd}回合：{atk_u.name}出手，对{def_u.name}造成 {dealt} 点伤害"
                + ("（暴击！）" if crit else "") + suffix
                + f"，{def_u.name}剩余 {hp[j]}")
        # 反噬 / 汲取（按实际造成的伤害；护盾吸收部分不触发）
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
