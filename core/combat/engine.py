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
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .. import battle
from . import skills

DEFAULT_MAX_ROUNDS = battle.MAX_ROUNDS
TEAM_ACTION_LIMIT = 1000  # 保护机器人运行；阵营战到达上限时按平局保留气血


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
    speed: int = 100
    speed_boost: float = 1.0
    action_bar: int = 0
    crit_damage: float | None = None

    @classmethod
    def from_unit(cls, u: battle.Unit) -> "Fighter":
        return cls(name=u.name, atk=int(u.atk), defense=int(u.defense),
                   hp=int(u.hp), hp_max=int(u.hp), bao=float(u.bao or 0.0),
                   speed=max(1, int(u.speed or 100)), action_bar=max(0, int(u.action_bar or 0)),
                   crit_damage=u.crit_damage)

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
    if f.tags.get("time_river_dark_triad") and not f.effects.get("triad_revived"):
        f.effects["triad_revived"] = True
        hp[idx] = f.hp_max
        f.effects["shield"] = f.hp_max // 4
        f.effects["time_river_damage_reduction"] = 0.3
        f.effects["time_river_damage_reduction_turns"] = max(
            3, int(f.eff("time_river_damage_reduction_turns")))
        log.append(f"【黑暗帝血】{f.name}满血复生，并重新凝聚护盾。")
        return True
    rev = f.eff("revive")
    if f.eff("revive_disabled") or not isinstance(rev, dict) or rev.get("used"):
        return False
    raw_pr = rev.get("pr")
    pr = 1.0 if raw_pr is None else min(1.0, max(0.0, float(raw_pr)))   # pr=0 合法：永不触发
    if rng.random() >= pr:
        return False
    times = max(1, int(rev.get("times", 1) or 1))   # W8-B4 白云苍狗：一场三次复活
    if times > 1:
        rev["times"] = times - 1
    else:
        rev["used"] = True
    hp[idx] = max(1, int(f.hp_max * min(1.0, max(0.05, float(rev.get("ratio", 0.7) or 0.7)))))
    msg = str(rev.get("msg") or "")
    name = str(rev.get("name") or "复活技")
    log.append(f"【{name}】{msg}" + (f"｜{f.name} 复活，血量 {hp[idx]}" if hp[idx] else ""))
    return True


def _apply_control(target: Fighter, name: str, message: str) -> str:
    if target.eff("first_control_immunity", False):
        target.effects["first_control_immunity"] = False
        bonus = float(target.eff("dodge_after_control", 0) or 0)
        target.effects["dodge_chance_once"] = max(
            float(target.eff("dodge_chance_once", 0) or 0), bonus)
        tail = f"并获得一次 {bonus:.0%} 闪避" if bonus else ""
        return f"【{name}】{target.name} 首次免疫控制{tail}"
    target.effects["stun_turns"] = int(target.eff("stun_turns", 0) or 0) + 1
    return f"【{name}】{message}（{target.name} 被定身）"


def _dodges_next_attack(target: Fighter, rng: random.Random) -> bool:
    once = min(0.45, max(0.0, float(target.eff("dodge_chance_once", 0) or 0)))
    chance = min(0.45, max(0.0, float(target.eff("dodge_chance", 0) or 0)) + once)
    if once:
        target.effects["dodge_chance_once"] = 0.0
    return bool(chance and rng.random() < chance)


def _low_hp_shield(target: Fighter, hp_before: int, damage: int) -> tuple[int, int, str]:
    ratio = max(0.0, float(target.eff("low_hp_shield_ratio", 0) or 0))
    if (ratio <= 0 or target.eff("low_hp_shield_used", False)):
        hp_after = max(0, hp_before - damage)
        return hp_after, hp_before - hp_after, ""
    threshold = min(0.95, max(0.0, float(target.eff("low_hp_shield_threshold", 0.3) or 0.3)))
    threshold_hp = max(1, int(target.hp_max * threshold))
    if hp_before <= threshold_hp or hp_before - damage > threshold_hp:
        hp_after = max(0, hp_before - damage)
        return hp_after, hp_before - hp_after, ""
    spill = max(0, damage - (hp_before - threshold_hp))
    shield = max(1, int(target.hp_max * ratio))
    absorbed = min(shield, spill)
    target.effects["shield"] = int(target.eff("shield", 0) or 0) + shield - absorbed
    target.effects["low_hp_shield_used"] = True
    hp_after = max(0, threshold_hp - (spill - absorbed))
    return hp_after, hp_before - hp_after, f"（低血护盾触发，生成 {shield:,}）"


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
    *, triggered: list[Mapping] | None = None, action_index: int | None = None,
) -> tuple[int, list[str]]:
    """出手攻击技能：池内逐条独立掷 pr（对齐原版遍历判定）。

    命中 → 伤害 ×beilv（钳 ≤50，法球不吃倍率）、控制=1 → 定身对手 1 回合、cnt 限次。
    """
    extra: list[str] = []
    pool = atk_u.tags.get("atk_skills") or []
    shared_roll = rng.random() if pool and action_index is not None else None
    counter_shown = False
    for sk in pool:
        if action_index is None:
            if _left(atk_u, sk) == 0:
                continue
        elif int(sk.get("cnt", -1) or 0) not in (-1, action_index):
            continue
        pr = float(sk.get("pr", 0) or 0)
        if pr <= 0 or (shared_roll if shared_roll is not None else rng.random()) >= pr:
            continue
        from .time_river import countered_skill
        if countered_skill(atk_u, sk):
            if not counter_shown:
                extra.append(f"【时间长河反制】{atk_u.name}的{sk['name']}被截断。")
                counter_shown = True
            continue
        raw_b = sk.get("beilv")
        beilv = 1.0 if raw_b is None else float(raw_b)
        beilv = min(SKILL_BEILV_CAP, max(0.1, beilv))
        dmg = max(1, int(dmg * beilv + float(sk.get("other", 0) or 0)))
        if action_index is None:
            _spend(atk_u, sk)
        extra.append(f"【{sk.get('name')}】{sk.get('msg1', '')}（伤害 ×{beilv:g}）")
        if int(sk.get("控制", 0) or 0) > 0:
            extra.append(_apply_control(def_u, str(sk.get("name") or "控制技能"),
                                        str(sk.get("msg2") or "")))
        if triggered is not None:
            triggered.append(sk)
            if action_index is not None and len(triggered) >= 3:
                break
    return dmg, extra


def _apply_hit_effects(attacker, defender, hp, index, triggered, log):
    for skill in triggered:
        if int(skill.get("不可复活", 0) or 0) == 1:
            defender.effects["revive_disabled"] = True
        if skill.get("时间长河效果") == "剥落无敌气魄":
            defender.atk = max(1, defender.atk // 2)
            defender.defense = max(1, defender.defense // 2)
            defender.hp_max = max(1, defender.hp_max // 2)
            hp[index] = max(1, hp[index] // 2)
            defender.hp = hp[index]
            log.append(f"【{skill['name']}】{defender.name}的攻、防、生命上限与当前气血减半。")
        teaching = skill.get("真意传授")
        if teaching:
            used = defender.tags.setdefault("river_teaching_seen", set())
            used.add(str(skill["name"]))


def _tick_action_effects(unit, hp, index, log):
    from .time_river import tick_cang_suppression
    unit.hp = hp[index]
    note = tick_cang_suppression(unit)
    if note:
        hp[index] = unit.hp
        log.append(note)
    duration = int(unit.eff("time_river_damage_reduction_turns"))
    if duration:
        unit.effects["time_river_damage_reduction_turns"] = duration - 1
        if duration == 1:
            unit.effects["time_river_damage_reduction"] = 0.0


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


def _next_action(sides: list[Fighter], bars: list[int], advance_limit: int) -> tuple[int | None, list[int]]:
    """推进原版 5000 点行动条，返回行动方和本次有效速度。"""
    for _ in range(max(1, int(advance_limit))):
        for idx, fighter in enumerate(sides):
            if fighter.effects.get("immediate_action"):
                fighter.effects["immediate_action"] = False
                speeds = [max(0, int(unit.speed * unit.speed_boost)) for unit in sides]
                return idx, speeds
        speeds = [
            int(unit.speed * unit.speed_boost *
                (1 - max(0.0, float(unit.eff("speed_down_pct", 0) or 0))))
            for unit in sides
        ]
        bars[0] += speeds[0]
        bars[1] += speeds[1]
        ready = [idx for idx, bar in enumerate(bars) if bar >= battle.ACTION_BAR_MAX]
        if len(ready) == 2:
            abs_a = bool(sides[0].tags.get("absolute_first"))
            abs_b = bool(sides[1].tags.get("absolute_first"))
            if abs_a != abs_b:
                return (0 if abs_a else 1), speeds
            return (0 if speeds[0] >= speeds[1] else 1), speeds
        if ready:
            return ready[0], speeds
    return None, [0, 0]


def run_1v1(
    a: Fighter, b: Fighter, rng: random.Random,
    max_rounds: int = DEFAULT_MAX_ROUNDS, skip_first: tuple[int, ...] = (),
    *, opening_log: Sequence[str] = (),
) -> BattleResult:
    """按原版速度行动条驱动；满 100 次行动时按双方剩余绝对气血裁决。"""
    sides = [a, b]
    hp = [max(0, a.hp), max(0, b.hp)]
    if not all(hp):
        winner = 0 if hp[0] else 1 if hp[1] else None
        return BattleResult(winner, list(opening_log), hp[0], hp[1])
    bars = [max(0, int(a.action_bar)), max(0, int(b.action_bar))]
    winner: int | None = None
    skipped: set[int] = set()
    log = list(opening_log)
    rage_stacks = [0, 0]
    action_limit = max(1, int(max_rounds))
    timed_out = False

    for rnd in range(1, action_limit + 1):
        i, speeds = _next_action(sides, bars, battle.ACTION_BAR_ADVANCE_LIMIT)
        if i is None:
            log.append("天地元气紊乱，强制结束战斗！")
            break
        j = 1 - i
        atk_u, def_u = sides[i], sides[j]
        bars[i] = 0
        _tick_action_effects(atk_u, hp, i, log)
        if i in skip_first and i not in skipped:
            skipped.add(i)
            log.append(f"第{rnd}回合：{atk_u.name}被大阵困住，无法出手")
            continue
        stun = int(atk_u.eff("stun_turns", 0) or 0)
        if stun > 0:
            atk_u.effects["stun_turns"] = stun - 1
            log.append(f"第{rnd}回合：{atk_u.name}被定身，无法出手")
            continue

        if atk_u.eff("cang_emperor_suppression", False):
            from .time_river import tick_cang_suppression
            suppression_note = tick_cang_suppression(atk_u)
            if suppression_note:
                hp[i] = max(0, min(atk_u.hp_max, int(atk_u.hp)))
                log.append(suppression_note)
        for sid in atk_u.skills:
            spec = skills.get(sid)
            if spec and spec.on_turn:
                spec.on_turn(atk_u, def_u,
                             {"rng": rng, "round": rnd, "log": log, "hp": hp, "side": i})

        try_heal_skills(atk_u, hp, i, rng, log)
        can_bypass = any(sk.get("不可防御") for sk in atk_u.tags.get("atk_skills") or ())
        if not can_bypass and _dodges_next_attack(def_u, rng):
            log.append(f"第{rnd}回合：{def_u.name}看穿攻势，避开一击")
            continue
        pet_bonus = max(0.0, float(atk_u.eff("pet_combat_bonus", 0) or 0))
        if pet_bonus and not atk_u.tags.get("_pet_combat_bonus_used") and rng.random() < 0.35:
            atk_u.tags["_pet_combat_bonus_used"] = True
            atk_u.atk = max(1, int(atk_u.atk * (1 + pet_bonus)))
            atk_u.defense = max(1, int(atk_u.defense * (1 + pet_bonus)))
            hp[i] = min(atk_u.hp_max, int(hp[i] * (1 + pet_bonus)))
            log.append(f"仙宠【{atk_u.name}】辅佐出战，攻防与当前气血提升 {pet_bonus:.0%}。")
        take_damage_pct = max(0.0, float(atk_u.eff("take_damage_attack_pct", 0) or 0))
        combo_pct = max(0.0, float(atk_u.eff("combo_attack_pct", 0) or 0))
        rage_mult = 1 + take_damage_pct * rage_stacks[i]
        combo_mult = 1 + combo_pct * min(10, max(0, rnd - 1))
        attack = max(1, int(atk_u.atk * rage_mult * combo_mult + 0.5))
        dmg, crit = battle.attack_harm(
            max(1, attack * 0.85), max(1, def_u.defense),
            rng, atk_u.bao, atk_u.crit_damage,
        )
        execute = max(0.0, float(atk_u.eff("execute_pct", 0) or 0))
        if execute and hp[j] / max(1, def_u.hp_max) <= 0.15:
            dmg = int(dmg * (1 + execute))
        summon = max(0.0, float(atk_u.eff("summon_pct", 0) or 0))
        dmg += int(attack * summon)
        triggered: list[Mapping] = []
        dmg, atk_extra = roll_attack_skills(atk_u, def_u, dmg, rng, triggered=triggered)
        log.extend(atk_extra)
        _apply_hit_effects(atk_u, def_u, hp, j, triggered, log)
        unblockable = any(sk.get("不可防御") == 1 for sk in triggered)
        if can_bypass and not unblockable and _dodges_next_attack(def_u, rng):
            log.append(f"第{rnd}回合：{def_u.name}看穿攻势，避开一击")
            continue
        orb = float(atk_u.eff("orb", 0.0) or 0.0)
        orb_dmg = (int(atk_u.atk * orb) if orb > 0 else 0)
        orb_dmg += max(0, int(atk_u.eff("orb_damage_flat", 0) or 0))
        dealt = dmg + orb_dmg
        if not unblockable:
            dealt, def_extra = roll_defense_skills(def_u, dealt, rng)
            log.extend(def_extra)
        damage_mult = max(0.0, float(atk_u.eff("dmg_dealt_mult", 1.0) or 0))
        damage_mult *= max(0.0, float(def_u.eff("dmg_taken_mult", 1.0) or 0))
        if damage_mult != 1.0:
            dealt = max(0, int(dealt * damage_mult))
        reduction = min(0.65, max(0.0, float(def_u.eff("damage_reduction", 0) or 0),
                      float(def_u.eff("time_river_damage_reduction", 0) or 0)))
        if reduction:
            dealt = max(0, int(round(dealt * (1 - reduction))))
        shield = int(def_u.eff("shield", 0) or 0)
        suffix = ""
        if shield > 0:
            absorbed = min(shield, dealt)
            def_u.effects["shield"] = shield - absorbed
            dealt -= absorbed
            if absorbed:
                suffix += f"（护盾吸收 {absorbed}）"
        hp[j], dealt, shield_note = _low_hp_shield(def_u, hp[j], dealt)
        suffix += shield_note
        if dealt > 0:
            rage_stacks[j] = min(10, rage_stacks[j] + 1)
        if orb_dmg > 0:
            suffix += f"，法球 {orb_dmg}"
        line = (f"第{rnd}回合：{atk_u.name}出手，对{def_u.name}造成 {dealt} 点伤害"
                + ("（暴击！）" if crit else "") + suffix
                + f"，{def_u.name}剩余 {hp[j]}")
        reflect = float(def_u.eff("reflect", 0.0) or 0.0)
        reflect_chance = min(0.45, max(0.0, float(def_u.eff("reflect_chance", 0) or 0)))
        if reflect_chance and rng.random() < reflect_chance:
            reflect = max(reflect, min(1.0, max(0.0, float(def_u.eff("reflect_pct", 0) or 0))))
        if reflect > 0 and dealt > 0:
            back = min(int(dealt * reflect), hp[i])
            if back > 0:
                hp[i] -= back
                rage_stacks[i] = min(10, rage_stacks[i] + 1)
                line += f"，反噬 {back}"
        lifesteal = float(atk_u.eff("lifesteal", 0.0) or 0.0)
        if lifesteal > 0 and dealt > 0:
            heal = min(int(dealt * lifesteal), atk_u.hp_max - hp[i])
            if heal > 0:
                hp[i] += heal
                line += f"，汲取 {heal}"
        extra_chance = min(0.55, max(0.0, float(atk_u.eff("extra_action_chance", 0) or 0)))
        if extra_chance and hp[j] > 0 and rng.random() < extra_chance:
            extra_damage = max(1, int(dmg * 0.55))
            extra_damage = max(0, int(round(extra_damage * (1 - reduction))))
            hp[j], extra_damage, extra_shield_note = _low_hp_shield(def_u, hp[j], extra_damage)
            dealt += extra_damage
            line += f"，额外行动追击 {extra_damage}{extra_shield_note}"
        log.append(line)
        if hp[j] <= 0:
            if _try_revive(def_u, hp, j, log, rng):
                continue
            winner = i
            break
        if hp[i] <= 0:
            if _try_revive(atk_u, hp, i, log, rng):
                continue
            winner = j
            break
    else:
        timed_out = True

    if winner is None and timed_out:
        if action_limit < DEFAULT_MAX_ROUNDS:
            ratio_a = hp[0] / a.hp if a.hp > 0 else 0.0
            ratio_b = hp[1] / b.hp if b.hp > 0 else 0.0
            if abs(ratio_a - ratio_b) >= 1e-9:
                winner = 0 if ratio_a > ratio_b else 1
        else:
            log.append(f"战局陷入僵持，已达{action_limit}回合上限，天道降下裁决！")
            if hp[0] > hp[1]:
                winner = 0
                hp[1] = 0
                log.append(f"{a.name}略占上风，险胜！")
            elif hp[1] > hp[0]:
                winner = 1
                hp[0] = 0
                log.append(f"{b.name}略占上风，险胜！")
            else:
                hp[0] = hp[1] = 0
                log.append("双方战至力竭，平局收场！")
    a.hp, b.hp = hp
    return BattleResult(winner, log, hp[0], hp[1])


@dataclass
class TeamBattleResult:
    winner: int | None
    log: list[str]
    a_hp: int
    b_hp: int
    a_survivors: list[str]
    b_survivors: list[str]
    damage_by_side: tuple[int, int] = (0, 0)
    damage_by_unit: dict[int, int] = field(default_factory=dict)
    timed_out: bool = False


def _team_strike(atk_u: Fighter, def_u: Fighter, rng: random.Random,
                 round_no: int, log: list[str], hp_table: list[int],
                 indexes: dict[int, int], rage_stacks: dict[int, int], action_index: int) -> int:
    """zd_battle_team 命中主链：0.85 Harm、独立暴击、法球、技能和防御结算。"""
    atk_idx, def_idx = indexes[id(atk_u)], indexes[id(def_u)]
    stun = int(atk_u.eff("stun_turns", 0) or 0)
    if stun > 0:
        atk_u.effects["stun_turns"] = stun - 1
        log.append(f"第{round_no}回合：{atk_u.name}被定身，无法出手")
        return 0
    for sid in atk_u.skills:
        spec = skills.get(sid)
        if spec and spec.on_turn:
            spec.on_turn(atk_u, def_u,
                         {"rng": rng, "round": round_no, "log": log, "hp": hp_table, "side": atk_idx})
    try_heal_skills(atk_u, hp_table, atk_idx, rng, log)
    atk_u.hp = hp_table[atk_idx]
    take_damage_pct = max(0.0, float(atk_u.eff("take_damage_attack_pct", 0) or 0))
    combo_pct = max(0.0, float(atk_u.eff("combo_attack_pct", 0) or 0))
    attack = max(1, int(atk_u.atk * (1 + take_damage_pct * rage_stacks[id(atk_u)])
                        * (1 + combo_pct * min(10, max(0, round_no - 1))) + 0.5))
    crit_mult = battle.baojishanghai(
        atk_u.bao, rng, atk_u.crit_damage if atk_u.crit_damage is not None
        else min(max(0.0, atk_u.bao) + battle.CRIT_BASE, battle.CRIT_CAP))
    damage = battle.harm(max(1, attack * 0.85), max(1, def_u.defense), rng)[0]
    damage = int(damage * crit_mult)
    if hp_table[def_idx] / max(1, def_u.hp_max) <= 0.15:
        damage = int(damage * (1 + max(0.0, float(atk_u.eff("execute_pct", 0) or 0))))
    damage += max(0, int(attack * float(atk_u.eff("summon_pct", 0) or 0)))
    orb = max(0.0, float(atk_u.eff("orb", 0) or 0))
    damage += int(atk_u.atk * orb) + max(0, int(atk_u.eff("orb_damage_flat", 0) or 0))
    triggered: list[Mapping] = []
    damage, attack_log = roll_attack_skills(atk_u, def_u, damage, rng,
                                             triggered=triggered, action_index=action_index)
    log.extend(attack_log)
    _apply_hit_effects(atk_u, def_u, hp_table, def_idx, triggered, log)
    if not any(sk.get("不可防御") == 1 for sk in triggered):
        if _dodges_next_attack(def_u, rng):
            log.append(f"第{round_no}回合：{def_u.name}看穿攻势，避开一击")
            return 0
        damage, defense_log = roll_defense_skills(def_u, damage, rng)
        log.extend(defense_log)
    damage_mult = max(0.0, float(atk_u.eff("dmg_dealt_mult", 1.0) or 0))
    damage_mult *= max(0.0, float(def_u.eff("dmg_taken_mult", 1.0) or 0))
    damage = max(0, int(damage * damage_mult))
    reduction = min(0.65, max(0.0, float(def_u.eff("damage_reduction", 0) or 0),
                      float(def_u.eff("time_river_damage_reduction", 0) or 0)))
    if reduction:
        damage = max(0, int(round(damage * (1 - reduction))))
    shield = max(0, int(def_u.eff("shield", 0) or 0))
    absorbed = min(shield, damage)
    if absorbed:
        def_u.effects["shield"] = shield - absorbed
    damage -= absorbed
    hp_table[def_idx], damage, shield_note = _low_hp_shield(def_u, hp_table[def_idx], damage)
    def_u.hp = hp_table[def_idx]
    if absorbed:
        log.append(f"【护盾】{def_u.name}吸收 {absorbed} 点伤害。")
    if shield_note:
        log.append(shield_note)
    if damage > 0:
        rage_stacks[id(def_u)] = min(10, rage_stacks[id(def_u)] + 1)
    log.append(f"第{round_no}回合：{atk_u.name}出手，对{def_u.name}造成 {damage} 点伤害"
               f"{'（暴击）' if crit_mult > 1 else ''}，余 {def_u.hp}")
    reflect = max(0.0, float(def_u.eff("reflect", 0) or 0))
    if reflect and damage:
        reflected = min(hp_table[atk_idx], int(damage * reflect))
        hp_table[atk_idx] -= reflected
        atk_u.hp = hp_table[atk_idx]
        if reflected:
            rage_stacks[id(atk_u)] = min(10, rage_stacks[id(atk_u)] + 1)
            log.append(f"{def_u.name}反噬 {reflected} 点伤害。")
    lifesteal = max(0.0, float(atk_u.eff("lifesteal", 0) or 0))
    if lifesteal and damage and hp_table[atk_idx] > 0:
        healed = min(int(damage * lifesteal), atk_u.hp_max - hp_table[atk_idx])
        hp_table[atk_idx] += healed
        atk_u.hp = hp_table[atk_idx]
    extra = min(0.55, max(0.0, float(atk_u.eff("extra_action_chance", 0) or 0)))
    if extra and atk_u.hp > 0 and def_u.hp > 0 and rng.random() < extra:
        follow = max(1, int(damage * 0.55))
        follow = max(0, int(round(follow * (1 - reduction))))
        hp_table[def_idx], follow, _ = _low_hp_shield(def_u, hp_table[def_idx], follow)
        def_u.hp = hp_table[def_idx]
        damage += follow
        log.append(f"{atk_u.name}额外追击 {follow}，{def_u.name}余 {def_u.hp}")
    return damage


def run_team_battle(a_team: Sequence[Fighter], b_team: Sequence[Fighter],
                    rng: random.Random, *, opening_log: Sequence[str] = ()) -> TeamBattleResult:
    """每轮仅一名就绪者行动，余下行动条累计到下一轮。"""
    a, b = list(a_team), list(b_team)
    units = a + b
    indexes = {id(unit): i for i, unit in enumerate(units)}
    bars = [max(0, int(unit.action_bar)) for unit in units]
    hp = [max(0, int(unit.hp)) for unit in units]
    rage = {id(unit): 0 for unit in units}
    damage = dict.fromkeys(indexes, 0)
    actions = [0] * len(units)
    log = list(opening_log)
    timed_out = False
    for round_no in range(1, TEAM_ACTION_LIMIT + 1):
        if not any(hp[:len(a)]) or not any(hp[len(a):]):
            break
        living = [i for i, value in enumerate(hp) if value > 0]
        ready = []
        for _ in range(battle.ACTION_BAR_ADVANCE_LIMIT):
            for i in living:
                unit = units[i]
                speed_down = min(0.95, max(0.0, float(unit.eff("speed_down_pct"))))
                bars[i] += int(unit.speed * unit.speed_boost * (1 - speed_down))
            ready = [i for i in living if bars[i] >= battle.ACTION_BAR_MAX]
            if ready:
                break
        if not ready:
            log.append("行动条无法继续推进，双方保留气血。")
            break
        i = max(ready, key=lambda index: (bool(units[index].tags.get("absolute_first")),
                                          units[index].speed, bars[index]))
        bars[i] -= battle.ACTION_BAR_MAX
        attacker = units[i]
        _tick_action_effects(attacker, hp, i, log)
        foes = [j for j in living if (j < len(a)) != (i < len(a))]
        j = foes[int(rng.random() * len(foes))]
        defender = units[j]
        log.append(f"【第{round_no}回合】{attacker.name}抢占先机！")
        damage[id(attacker)] += _team_strike(attacker, defender, rng, round_no, log,
                                             hp, indexes, rage, actions[i])
        actions[i] += 1
        for index in (j, i):
            unit = units[index]
            if hp[index] == 0:
                _try_revive(unit, hp, index, log, rng)
            unit.hp = hp[index]
    else:
        if any(hp[:len(a)]) and any(hp[len(a):]):
            timed_out = True
            log.append(f"战斗达到 {TEAM_ACTION_LIMIT} 次行动上限，双方保留气血。")
    a_alive = [unit for unit in a if unit.hp > 0]
    b_alive = [unit for unit in b if unit.hp > 0]
    winner = 0 if a_alive and not b_alive else 1 if b_alive and not a_alive else None
    return TeamBattleResult(winner, log, sum(hp[:len(a)]), sum(hp[len(a):]),
                            [unit.name for unit in a_alive], [unit.name for unit in b_alive],
                            (sum(damage[id(unit)] for unit in a), sum(damage[id(unit)] for unit in b)),
                            damage, timed_out)


# ------------------------------------------------------- 多人团本（W8-D4）

def _advance_raid_bars(units: Sequence[Fighter], bars: dict[str, int]) -> list[Fighter]:
    """原版团本每大回合推进一次行动条，返回本拍可行动单位。"""
    for unit in units:
        key = _raid_key(unit, str(id(unit)))
        if unit.hp <= 0:
            continue
        base_speed = int(unit.tags.get("speed", unit.speed) or unit.speed or 100)
        speed_down = max(0.0, float(unit.eff("speed_down_pct", 0) or 0))
        bars[key] = bars.get(key, int(unit.action_bar or 0)) + int(
            base_speed * unit.speed_boost * (1 - speed_down))
    ready = [unit for unit in units
             if unit.hp > 0 and bars.get(_raid_key(unit, str(id(unit))), 0) >= battle.ACTION_BAR_MAX]
    ready.sort(key=lambda unit: (
        -int(bool(unit.tags.get("absolute_first"))),
        -int(unit.tags.get("speed", unit.speed) or unit.speed),
        -bars.get(_raid_key(unit, str(id(unit))), 0),
    ))
    return ready


@dataclass
class RaidResult:
    """多人对单 Boss 的回合结算结果。

    key 为 Fighter.tags['key']（玩家 uid / 'boss'），damage 只统计对 Boss 本体
    造成的伤害（不含反弹、治疗与溢出），即伤害账本口径。
    """

    win: bool
    log: list[str]
    damage: dict[str, int]
    boss_hp: int
    rounds: int
    phases: list[str]
    survivors: list[str]
    player_hp: dict[str, int]

    def top(self, limit: int = 20) -> list[tuple[str, int]]:
        return sorted(self.damage.items(), key=lambda kv: -kv[1])[:max(1, int(limit))]


def _raid_key(f: Fighter, fallback: str) -> str:
    return str(f.tags.get("key") or fallback)


def _raid_strike(
    atk_u: Fighter, def_u: Fighter, hp: dict[str, int], rng: random.Random,
    log: list[str], rnd: int,
) -> int:
    """一次出手：复用 1v1 的技能池 / 护盾 / 反噬 / 汲取链，返回对 def 的实际伤害。

    与 run_1v1 的差别：血量表用 key 寻址（多名玩家共享一份），且不做胜负判定。
    """
    ka, kd = _raid_key(atk_u, "atk"), _raid_key(def_u, "def")
    stun = int(atk_u.eff("stun_turns", 0) or 0)
    if stun > 0:
        atk_u.effects["stun_turns"] = stun - 1
        log.append(f"第{rnd}回合：{atk_u.name}被定身，无法出手")
        return 0
    if _dodges_next_attack(def_u, rng):
        log.append(f"第{rnd}回合：{def_u.name}看穿攻势，避开一击")
        return 0
    crit_mult = battle.baojishanghai(atk_u.bao, rng,
                                    atk_u.crit_damage if atk_u.crit_damage is not None
                                    else min(max(0.0, atk_u.bao) + battle.CRIT_BASE, battle.CRIT_CAP))
    base = battle.calculate_harm(
        atk_u.atk * 0.85,
        max(1, int(def_u.defense * float(def_u.eff("dmg_taken_mult", 1.0)))),
        rng,
    )
    dmg = base
    # 原版 tuanben 计算暴击标记但不把倍率乘入伤害。
    # 伤害采用 Harm(攻×0.85)、法球、攻击方防御10%附加，最后进入圣体增伤乘区。
    orb = float(atk_u.eff("orb", 0.0) or 0.0)
    orb_dmg = int(atk_u.atk * orb) if orb > 0 else 0
    orb_dmg += max(0, int(atk_u.eff("orb_damage_flat", 0) or 0))
    dmg = int((dmg + orb_dmg + int(atk_u.defense * 0.1))
              * float(atk_u.eff("dmg_dealt_mult", 1.0)))
    dmg, atk_extra = roll_attack_skills(atk_u, def_u, dmg, rng)
    log.extend(atk_extra)
    dealt = dmg
    dealt, def_extra = roll_defense_skills(def_u, dealt, rng)
    log.extend(def_extra)
    reduction = min(0.65, max(0.0, float(def_u.eff("damage_reduction", 0) or 0),
                      float(def_u.eff("time_river_damage_reduction", 0) or 0)))
    if reduction:
        dealt = max(0, int(round(dealt * (1 - reduction))))
    suffix = ""
    shield = int(def_u.eff("shield", 0) or 0)
    if shield > 0:
        absorbed = min(shield, dealt)
        def_u.effects["shield"] = shield - absorbed
        dealt -= absorbed
        if absorbed:
            suffix += f"（护盾吸收 {absorbed}）"
    hp[kd], dealt, shield_note = _low_hp_shield(def_u, hp[kd], dealt)
    suffix += shield_note
    if orb_dmg > 0:
        suffix += f"，法球 {orb_dmg}"
    line = (f"第{rnd}回合：{atk_u.name}出手，对{def_u.name}造成 {dealt} 点伤害"
            + ("（暴击！）" if crit_mult > 1.0 else "") + suffix
            + f"，{def_u.name}剩余 {hp[kd]}")
    reflect = float(def_u.eff("reflect", 0.0) or 0.0)
    if reflect > 0 and dealt > 0:
        back = min(int(dealt * reflect), hp[ka])
        if back > 0:
            hp[ka] -= back
            line += f"，反噬 {back}"
    lifesteal = float(atk_u.eff("lifesteal", 0.0) or 0.0)
    if lifesteal > 0 and dealt > 0:
        heal = min(int(dealt * lifesteal), atk_u.hp_max - hp[ka])
        if heal > 0:
            hp[ka] += heal
            line += f"，汲取 {heal}"
    log.append(line)
    atk_u.hp = hp[ka]
    def_u.hp = hp[kd]
    return max(0, dealt)


def run_raid(
    players: Sequence[Fighter], boss: Fighter, rng: random.Random,
    max_rounds: int = 100,
) -> RaidResult:
    """多人对单 Boss 的回合战（W8-D4，对齐原版 tuanben.tb_battle 的语义骨架）。

    每个大回合按原版推进5000点行动条，并让全部就绪角色按超维先手、速度与行动条溢出排序出手。
    Boss 按仇恨（累计伤害）最高的存活玩家单体攻击；`boss.tags['aoe']=True`
    时每5个大回合执行全体攻击。战斗最多100个大回合并受5分钟保护。

    阶段与复活：
    - `boss.tags['phase_revive']`：Boss 首次被打空时满血复活、三维 ×mult（帝尊者字秘·极尽）
    - `player.tags['revives']` + `tags['revive_ratio']`：者字秘致死复活（一场 N 次）
    """
    units: list[Fighter] = [boss, *players]
    for i, p in enumerate(players):
        p.tags.setdefault("key", f"p{i}")
        p.tags.setdefault("speed", int(p.speed or 100))
    boss.tags.setdefault("key", "boss")
    boss.tags.setdefault("speed", int(boss.speed or 100))

    keys = {_raid_key(u, f"u{i}"): u for i, u in enumerate(units)}
    hp: dict[str, int] = {k: int(u.hp) for k, u in keys.items()}
    damage: dict[str, int] = {_raid_key(p, f"p{i}"): 0 for i, p in enumerate(players)}
    hatred: dict[str, int] = {k: 0 for k in damage}
    revives: dict[str, int] = {
        _raid_key(p, f"p{i}"): max(
            max(0, int(p.tags.get("revives", 0) or 0)),
            max(0, int((p.eff("revive") or {}).get("times", 1) or 1))
            if isinstance(p.eff("revive"), dict) and not p.eff("revive").get("used")
            else 0,
        )
        for i, p in enumerate(players)
    }
    ratio: dict[str, float] = {
        _raid_key(p, f"p{i}"): min(1.0, max(0.05, float(
            p.tags.get("revive_ratio", (p.eff("revive") or {}).get("ratio", 1.0)
                       if isinstance(p.eff("revive"), dict) else 1.0) or 1.0)))
        for i, p in enumerate(players)
    }
    phase_left = max(0, int(boss.tags.get("phase_revive", 0) or 0))
    phase_mult = max(1.0, float(boss.tags.get("phase_mult", 1.3) or 1.3))
    phase_name = str(boss.tags.get("phase_name") or "者字秘·极尽")
    bkey = _raid_key(boss, "boss")
    raid_bars = { _raid_key(u, f"u{i}"): max(0, int(u.action_bar or 0))
                  for i, u in enumerate(units) }

    log: list[str] = []
    phases: list[str] = []
    win = False
    rounds = 0
    round_limit = max(1, min(int(max_rounds), 100))
    started_at = time.monotonic()
    for rnd in range(1, round_limit + 1):
        if time.monotonic() - started_at >= 300:
            break
        rounds = rnd
        ready_units = _advance_raid_bars(units, raid_bars)
        for u in ready_units:
            uk = _raid_key(u, "unit")
            raid_bars[uk] = max(0, raid_bars[uk] - battle.ACTION_BAR_MAX)
            u.action_bar = raid_bars[uk]
            if hp[uk] <= 0 or win:
                continue
            alive = [p for p in players if hp[_raid_key(p, "p")] > 0]
            if not alive:
                break
            if uk == bkey:
                targets = ([p for p in alive] if boss.tags.get("aoe") and rnd % 5 == 0
                           else [max(alive, key=lambda p: hatred[_raid_key(p, "p")])])
                if boss.tags.get("aoe") and rnd % 5 == 0:
                    log.append(f"第{rnd}回合：【{boss.name}】催动群体秘术，全队承压！")
                for t in targets:
                    if hp[_raid_key(t, "p")] <= 0:
                        continue
                    tkey = _raid_key(t, "p")
                    _raid_strike(boss, t, hp, rng, log, rnd)
                    t.hp = hp[tkey]
            else:
                before = hp[bkey]
                dealt = _raid_strike(u, boss, hp, rng, log, rnd)
                boss.hp = hp[bkey]
                got = min(dealt, before)
                damage[uk] += got
                hatred[uk] += got
                if hp[bkey] <= 0 and phase_left > 0:
                    phase_left -= 1
                    boss.atk = max(1, int(boss.atk * phase_mult))
                    boss.defense = max(1, int(boss.defense * phase_mult))
                    boss.hp_max = max(1, int(boss.hp_max * phase_mult))
                    hp[bkey] = boss.hp_max
                    boss.hp = boss.hp_max
                    phases.append(phase_name)
                    log.append(
                        f"【{phase_name}】{boss.name} 气血尽而复生，三维 ×{phase_mult:g}，"
                        f"满血 {hp[bkey]:,}！（剩余复活 {phase_left} 次）"
                    )
                elif hp[bkey] <= 0:
                    win = True
                    break
            # 玩家侧者字秘：致死一击后立刻判定，不影响本回合后续单位
            for p in players:
                pk = _raid_key(p, "p")
                if hp[pk] <= 0 and revives[pk] > 0:
                    revive = p.eff("revive")
                    legacy_times = max(0, int(p.tags.get("revives", 0) or 0))
                    if legacy_times:
                        remaining = revives[pk]
                        revives[pk] -= 1
                        revive_ratio = ratio[pk] if remaining <= 1 else 1.0
                        hp[pk] = max(1, int(p.hp_max * revive_ratio))
                        p.hp = hp[pk]
                        log.append(f"【者字秘】{p.name} 生机重燃，回复至 {hp[pk]:,}"
                                   f"（余 {revives[pk]} 次）")
                    elif isinstance(revive, dict) and not revive.get("used"):
                        chance = 1.0 if revive.get("pr") is None else min(
                            1.0, max(0.0, float(revive.get("pr", 0) or 0)))
                        if rng.random() < chance:
                            revives[pk] -= 1
                            times = max(1, int(revive.get("times", 1) or 1))
                            revive["times"] = max(0, times - 1)
                            if revive["times"] <= 0:
                                revive["used"] = True
                            hp[pk] = max(1, int(p.hp_max * ratio[pk]))
                            p.hp = hp[pk]
                            log.append(f"【{revive.get('name') or '命格复生'}】{p.name} "
                                       f"生机重燃，回复至 {hp[pk]:,}（余 {revives[pk]} 次）")
                        else:
                            revive["used"] = True
                            revives[pk] = 0
        if win or all(hp[_raid_key(p, "p")] <= 0 for p in players):
            break
    if rounds >= round_limit:
        log.append(f"战斗超过{round_limit}回合，强制结束！")
    if time.monotonic() - started_at >= 300:
        log.append("战斗超时（5分钟），强制结束！")

    survivors = [_raid_key(p, "p") for p in players if hp[_raid_key(p, "p")] > 0]
    log.append("--- 讨伐结束 ---")
    log.append(f"【{'玩家胜利' if win else 'BOSS胜利'}】共 {rounds} 回合，"
               f"{boss.name} 剩余气血 {hp[bkey]:,} / {boss.hp_max:,}，"
               f"存活 {len(survivors)}/{len(players)} 人")
    return RaidResult(
        win=win, log=log, damage=damage, boss_hp=max(0, hp[bkey]),
        rounds=rounds, phases=phases, survivors=survivors,
        player_hp={_raid_key(p, "p"): max(0, hp[_raid_key(p, "p")]) for p in players},
    )
