"""功法战斗装填（W1-2）：把玩家已学功法接到战斗引擎上。

原版语义（model/xiuxian.js 复活技能分支 + zd_battle 开场乘区）：
- 已学功法（ext["gongfa"]）在 item_index 中命中 `复活技能 == 1` 的条目 → 死亡时掷 pr
  （默认 1=必发）复活为 血量上限 × 恢复比例，每场一次，战报输出 msg2
- 条目上的 攻击加成/防御加成/生命加成 → 战斗开场三维乘区（1 + 加成）
- 其余功法仍是修炼效率类，不进战斗

数据源：data/item/技能组/复活技能.json（17 条，经 item_index 按名命中）。
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from .. import trib
from . import skills
from .engine import Fighter


def learned_battle_skills(doc: Any, item_lookup: Any) -> list[dict]:
    """已学功法中的战斗条目（复活技能 == 1）。item_lookup 兼容 dict 与 callable。"""
    get = item_lookup.get if hasattr(item_lookup, "get") else item_lookup
    out = []
    for name in (getattr(doc, "ext", {}).get("gongfa") or []):
        item = get(name)
        if item and int(item.get("复活技能", 0) or 0) == 1:
            out.append(dict(item))
    return out


def apply_start_bonuses(f: Fighter, battle_skills: list[dict]) -> Fighter:
    """开场三维乘区：攻/防/血 ×（1 + 对应加成之和）。"""
    atk_b = sum(float(s.get("攻击加成", 0) or 0) for s in battle_skills)
    def_b = sum(float(s.get("防御加成", 0) or 0) for s in battle_skills)
    hp_b = sum(float(s.get("生命加成", 0) or 0) for s in battle_skills)
    f.atk = max(1, int(f.atk * (1 + atk_b)))
    f.defense = max(1, int(f.defense * (1 + def_b)))
    f.hp_max = max(1, int(f.hp_max * (1 + hp_b)))
    f.hp = f.hp_max
    return f


def equip_skill_pool(f: Fighter, doc: Any, tables: Mapping[str, Any] | None) -> None:
    """技能池装配（W1-5）：灵根自带 + 已学功法同名条目。

    - tables：{"atk": 攻击技能, "def": 防御技能, "heal": 治疗技能, "boost": 灵根增幅技能}
    - 命中规则：条目 name == 灵根名（class=灵根 自带）或 ∈ ext["gongfa"]（已学功法）
    - 增幅表与攻击表同名：beilv 取大、控制并集（原版两表对同一灵根重复定义）
    - 池挂 tags：atk_skills / def_skills / heal_skills；次数记账由 engine._uses 管
    """
    if not tables:
        return
    lg_name = str(f.tags.get("linggen_name") or "")
    learned = set(getattr(doc, "ext", {}).get("gongfa") or [])
    if not lg_name and not learned:
        return
    want = ({lg_name} if lg_name else set()) | learned
    if bool(getattr(doc, "ext", {}).get("武道天眼")):
        want.add("大帝之姿")
    try:                                  # W8-B1b：重瞳 / 仙骨 / 瞳骨共鸣附加灵根类技能
        from .. import supreme as _sp
        want |= set(_sp.skill_names(doc))
    except Exception:
        pass

    atk_by_name: dict[str, dict] = {}
    for e in tables.get("atk") or []:
        if isinstance(e, Mapping) and e.get("name") in want:
            atk_by_name[str(e["name"])] = dict(e)
    for e in tables.get("boost") or []:
        if not (isinstance(e, Mapping) and e.get("name") in want):
            continue
        cur = atk_by_name.get(str(e["name"]))
        merged = dict(e)
        if cur:
            if float(cur.get("beilv") or 0) >= float(e.get("beilv") or 0):
                merged = dict(cur)
            for key in ("控制",):
                if int(cur.get(key) or 0) > int(merged.get(key) or 0):
                    merged[key] = cur[key]
        atk_by_name[str(e["name"])] = merged
    if atk_by_name:
        f.tags["atk_skills"] = list(atk_by_name.values())

    def_pool = [dict(e) for e in (tables.get("def") or [])
                if isinstance(e, Mapping) and e.get("name") in want]
    if def_pool:
        f.tags["def_skills"] = def_pool

    heal_pool = [dict(e) for e in (tables.get("heal") or [])
                 if isinstance(e, Mapping) and e.get("name") in want]
    if heal_pool:
        f.tags["heal_skills"] = heal_pool


def apply_proficiency(f: Fighter, doc: Any) -> None:
    """功法熟练度三乘区（W7-0）：combat 开场三维、trigger 技能触发率、
    numeric 出手伤害乘区（此前 numeric 定义了却零消费，PvE 也完全没接）。

    PvP / PvE 统一在 build_fighter 内装配，避免两条战斗路径口径不一致。
    """
    name, trigger, combat, numeric = trib.best_stage(doc)
    if combat > 1.0:
        f.atk = max(1, int(f.atk * combat))
        f.defense = max(1, int(f.defense * combat))
        f.hp_max = max(1, int(f.hp_max * combat))
        f.hp = min(f.hp_max, max(1, int(f.hp * combat)))
    if trigger > 1.0 and isinstance(f.tags.get("atk_skills"), list):
        for sk in f.tags["atk_skills"]:
            sk["pr"] = min(0.95, float(sk.get("pr", 0) or 0) * trigger)
    if numeric > 1.0:
        f.effects["dmg_dealt_mult"] = (float(f.eff("dmg_dealt_mult", 1.0))
                                      * min(1.10, numeric))
    if name in ("融会贯通", "炉火纯青", "登峰造极", "出神入化"):
        f.skills = (*f.skills, "prof_echo")
    if name in ("炉火纯青", "登峰造极", "出神入化"):
        f.skills = (*f.skills, "break_army")      # W7-4 档位特效
    f.tags["prof_stage"] = name


def build_fighter(
    doc: Any, name: str, atk: int, defense: int, hp: int, bao: float,
    item_lookup: Mapping[str, Any],
    base_rows: tuple[dict, dict] | None = None,
    skill_tables: Mapping[str, Any] | None = None,
    crit_damage: float | None = None,
) -> Fighter:
    """从玩家文档构建带功法与灵根法球的战斗单位。

    base_rows：(练气境界行, 炼体境界行)——开场系统（opening.py）做同境裁决时
    按表值差压缩对手；不传则跳过身份挂载。
    skill_tables：四张技能表（equip_skill_pool 装配灵根自带 + 已学功法技能）。
    """
    from .. import linggen
    from .. import authority as authority_mod
    from .. import battle as battle_mod

    f = Fighter(name=name, atk=int(atk), defense=int(defense), hp=int(hp),
                hp_max=int(hp), bao=float(bao or 0.0), speed=battle_mod.speed_of(doc),
                action_bar=battle_mod.initial_action_bar(doc),
                crit_damage=(min(float(bao or 0.0) + battle_mod.CRIT_BASE, battle_mod.CRIT_CAP)
                             if crit_damage is None else float(crit_damage)))
    lg = getattr(doc, "ext", {}).get("linggen")
    try:
        from ..pet import ability_bonus
        pet_combat_bonus = ability_bonus(getattr(doc, "ext", {}).get("pet"), "战斗")
        if pet_combat_bonus > 0:
            f.effects["pet_combat_bonus"] = pet_combat_bonus
    except (AttributeError, TypeError, ValueError):
        pass
    orb = linggen.orb_of(lg)
    if orb > 0:
        f.effects["orb"] = orb
    dodge = control_dodge = damage_reduction = orb_flat = 0.0
    for item_name in (getattr(doc, "ext", {}).get("equipment") or {}).values():
        item = item_lookup(item_name)
        if not item:
            continue
        item_dodge = max(0.0, float(item.get("闪避率", 0) or 0))
        damage_reduction += max(0.0, float(item.get("元神伤害减免", 0) or 0))
        orb_flat += max(0.0, float(item.get("神力", 0) or 0))
        if float(item.get("低血护盾", 0) or 0) > 0:
            f.effects["low_hp_shield_ratio"] = max(
                float(f.eff("low_hp_shield_ratio", 0) or 0),
                float(item["低血护盾"]))
            f.effects["low_hp_shield_threshold"] = max(
                float(f.eff("low_hp_shield_threshold", 0) or 0),
                float(item.get("低血阈值", 0.3) or 0.3))
        if float(item.get("首次免控", 0) or 0) > 0:
            f.effects["first_control_immunity"] = True
            control_dodge += item_dodge
        else:
            dodge += item_dodge
    if dodge:
        f.effects["dodge_chance"] = min(0.45, dodge)
    if control_dodge:
        f.effects["dodge_after_control"] = min(0.45, control_dodge)
    if damage_reduction:
        f.effects["damage_reduction"] = min(0.65, damage_reduction)
    if orb_flat:
        f.effects["orb_damage_flat"] = orb_flat
    # 身份挂载：开场镇杀 / 岁云裁决 / 帝骑助战 依据
    f.tags["auth_of"] = authority_mod.authority_of(doc)
    f.tags["auth21"] = authority_mod.authority_21(doc)
    f.tags["realm_index"] = int(getattr(doc, "realm_index", 0) or 0)
    f.tags["physique_index"] = int(getattr(doc, "physique_index", 0) or 0)
    f.tags["linggen_name"] = str(lg.get("name") or "") if isinstance(lg, Mapping) else ""
    if base_rows:
        f.tags["base_rows"] = base_rows
    battle_skills = learned_battle_skills(doc, item_lookup)
    if battle_skills:
        f = apply_start_bonuses(f, battle_skills)
        revive = battle_skills[0]      # 一场一次；多本取第一本（原版同为单次复活）
        raw_pr = revive.get("pr")
        f.effects["revive"] = {
            "name": str(revive.get("name") or "复活技"),
            "ratio": min(1.0, max(0.05, float(revive.get("恢复比例", 0.7) or 0.7))),
            "pr": 1.0 if raw_pr is None else min(1.0, max(0.0, float(raw_pr))),
            "msg": str(revive.get("msg2") or ""),
            "used": False,
        }
        f.tags["battle_skills"] = [str(s.get("name")) for s in battle_skills]
    try:
        from ..mingge import signed_bonus as _mingge_bonus
        f.tags["speed"] = f.speed
        revive_chance = min(1.0, max(0.0, _mingge_bonus(doc, "复活概率")))
        if revive_chance:
            revive = f.effects.get("revive")
            if isinstance(revive, dict):
                raw = revive.get("pr")
                prior = 1.0 if raw is None else float(raw)
                revive["pr"] = min(1.0, max(0.0, prior + revive_chance))
            else:
                f.effects["revive"] = {
                    "name": "命格·涅槃余烬", "ratio": 0.3, "pr": revive_chance,
                    "msg": "命火未熄，真灵复燃", "used": False,
                }
    except (TypeError, ValueError):
        pass
    equip_skill_pool(f, doc, skill_tables)
    skills.ensure_builtin()
    # W8-A1 诸天遗珍：增伤/减伤/汲取/开战护盾（暴击率已在 equipment.aggregate 里并入 bao）
    try:
        from .. import relic as relic_mod
        rel = relic_mod.combat(relic_mod.state_of(doc))
        if rel["dealt"] > 0:
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * (1 + rel["dealt"])
        if rel["taken"] > 0:
            f.effects["dmg_taken_mult"] = max(0.5, float(f.eff("dmg_taken_mult", 1.0))
                                              * (1 - rel["taken"]))
        if rel.get("dealt_by_type"):
            cur = dict(f.eff("type_dealt", {}) or {})
            for k, v in rel["dealt_by_type"].items():
                cur[k] = float(cur.get(k, 0) or 0) + float(v)
            f.effects["type_dealt"] = cur
        if rel.get("taken_by_type"):
            cur = dict(f.eff("type_taken", {}) or {})
            for k, v in rel["taken_by_type"].items():
                cur[k] = float(cur.get(k, 0) or 0) + float(v)
            f.effects["type_taken"] = cur
        if rel["lifesteal"] > 0:
            f.effects["lifesteal"] = float(f.eff("lifesteal", 0.0)) + rel["lifesteal"]
        if rel["shield"] > 0:
            f.effects["shield"] = int(f.effects.get("shield", 0) or 0) + int(f.hp_max * rel["shield"])
    except Exception:
        pass
    # W8-B2b 元神：爆发 +25%~30% 增伤、护体 -25%~-35% 受伤（各有时效，读时判定）
    try:
        from .. import yuanshen as ys_mod
        burst, _bname = ys_mod.active_burst(doc)
        if burst > 0:
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * (1 + burst)
        shield, _sname = ys_mod.active_shield(doc)
        if shield > 0:
            f.effects["dmg_taken_mult"] = max(0.4, float(f.eff("dmg_taken_mult", 1.0))
                                              * (1 - shield))
    except Exception:
        pass
    # W8-B4 岁云：四战技 + 岁云套开场 + 天阙权柄时效（PvP/PvE 同源）
    try:
        from .. import suiyun as sy_mod
        sy = sy_mod.combat(doc)
        if sy:
            f.tags["suiyun_stage"] = int(sy["stage"])
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * sy["dealt"]
            f.effects["dmg_taken_mult"] = max(0.15, float(f.eff("dmg_taken_mult", 1.0)) * sy["taken"])
            if sy.get("shield"):
                f.effects["shield"] = int(f.effects.get("shield", 0) or 0) + int(f.hp_max * sy["shield"])
            if sy.get("revives"):
                rev = f.effects.get("revive")
                if isinstance(rev, dict):
                    rev["times"] = max(int(rev.get("times", 1) or 1), int(sy["revives"]))
                    rev["ratio"] = max(float(rev.get("ratio", 0.7) or 0.7), 0.6)
                else:
                    f.effects["revive"] = {"name": "白云苍狗", "ratio": 0.6, "pr": 1.0,
                                          "msg": "岁月倒卷，三度归来",
                                          "times": int(sy["revives"]), "used": False}
            sname = sy_mod.stage_name(doc)
            if sname:
                f.tags["linggen_name"] = sname   # 复用 opening.suiyun_verdict 已实装的同境裁决
    except Exception:
        pass
    # W8-B6 证道：帝威增伤（每次证道成功累积 80%，重证 +20%，上限 +300%）
    try:
        from .. import zhengdao as dz_mod
        bonus = dz_mod.power_bonus(doc)
        if bonus > 0:
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * (1 + bonus)
    except Exception:
        pass
    # W8-C1 本命法宝：剑境共鸣（1h）增伤/减伤 + 天赋乘区（原版把这些写进临时属性却无消费者）
    try:
        from .. import bengming as bm_mod
        bm = bm_mod.combat(doc)
        if bm.get("dmg_dealt_mult"):
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * bm["dmg_dealt_mult"]
        if bm.get("dmg_taken_mult"):
            f.effects["dmg_taken_mult"] = max(0.15, float(f.eff("dmg_taken_mult", 1.0))
                                              * bm["dmg_taken_mult"])
    except Exception:
        pass
    # W8-C2 先天至宝：执掌被动 + 6h 蓄势窗口（原版 17 个战斗钩子收敛为单一出口）
    try:
        from .. import xtzb as xt_mod
        cx = xt_mod.combat(doc)
        if cx.get("dealt"):
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * (1 + cx["dealt"])
        if cx.get("taken"):
            f.effects["dmg_taken_mult"] = max(0.15, float(f.eff("dmg_taken_mult", 1.0))
                                              * (1 - cx["taken"]))
        if cx.get("shield"):
            f.effects["shield"] = int(f.effects.get("shield", 0) or 0) + int(f.hp_max * cx["shield"])
        if cx.get("reflect"):
            f.effects["reflect"] = max(float(f.eff("reflect", 0.0) or 0.0), cx["reflect"])
        if cx.get("lifesteal"):
            f.effects["lifesteal"] = float(f.eff("lifesteal", 0.0) or 0.0) + cx["lifesteal"]
        if cx.get("revive"):
            f.effects["revive"] = cx["revive"]
    except Exception:
        pass
    # W8-C3 大道炼器：敕令权柄（须完整）+ 终极功法 + 大道界 + 天资
    try:
        from .. import daotreasure as dt_mod
        c3 = dt_mod.combat(doc)
        if c3.get("dealt"):
            f.effects["dmg_dealt_mult"] = float(f.eff("dmg_dealt_mult", 1.0)) * (1 + c3["dealt"])
        if c3.get("taken"):
            f.effects["dmg_taken_mult"] = max(0.15, float(f.eff("dmg_taken_mult", 1.0))
                                              * (1 - c3["taken"]))
        if c3.get("crit"):
            f.bao = 1.0
        if c3.get("revive"):
            rev = f.effects.get("revive")
            if isinstance(rev, dict):
                rev["pr"] = 1.0
                rev["used"] = False
            else:
                f.effects["revive"] = {"name": "大道生死", "ratio": 0.7, "pr": 1.0,
                                      "msg": "生死权柄，一缕真灵不灭", "used": False}
    except Exception:
        pass
    apply_proficiency(f, doc)   # W7-0：三乘区 + 档位共鸣，PvP/PvE 同源
    if (int(getattr(doc, "realm_index", 0) or 0) >= 10
            and int(getattr(doc, "physique_index", 0) or 0) >= 10):
        f.skills = (*f.skills, "dual_echo")
    if (f.tags.get("heal_skills")
            and int(getattr(doc, "realm_index", 0) or 0) >= 20):
        f.skills = (*f.skills, "rejuvenate")      # W7-4 有治疗技时的续航特效
    return f


def build_xijie_npc_fighter(
    npc: Mapping[str, Any], item_lookup: Any,
    skill_tables: Mapping[str, Any] | None = None,
) -> Fighter:
    """Build a shared-engine fighter from buildXijieNpcCombatant's legacy shape."""
    techniques = npc.get("学习的功法")
    techniques = list(techniques) if isinstance(techniques, list) else []
    linggen = npc.get("灵根")
    lg_name = str(linggen.get("name") or "") if isinstance(linggen, Mapping) else str(linggen or "")
    f = Fighter(
        name=str(npc.get("名号") or "未知守卫"),
        atk=max(1, int(npc.get("攻击", 1) or 1)),
        defense=max(1, int(npc.get("防御", 1) or 1)),
        hp=max(1, int(npc.get("当前血量", npc.get("血量上限", 1)) or 1)),
        hp_max=max(1, int(npc.get("血量上限", 1) or 1)),
        bao=float(npc.get("暴击率", 0) or 0),
        speed=max(1, int(npc.get("速度", 100) or 100)),
        action_bar=0,
        crit_damage=float(npc.get("暴击伤害", 1.5) or 1.5),
    )
    dodge = max(0.0, float(npc.get("闪避率", 0) or 0))
    lifesteal = max(0.0, float(npc.get("吸血率", 0) or 0))
    orb = max(0.0, float(npc.get("法球倍率", 0) or 0))
    if dodge:
        f.effects["dodge_chance"] = dodge
    if lifesteal:
        f.effects["lifesteal"] = lifesteal
    if orb:
        f.effects["orb"] = orb
    f.tags["linggen_name"] = lg_name
    npc_doc = SimpleNamespace(ext={
        "gongfa": techniques,
        "linggen": {"name": lg_name, "orb": orb},
        "prof": {},
    })
    equip_skill_pool(f, npc_doc, skill_tables)
    battle_skills = learned_battle_skills(npc_doc, item_lookup)
    if battle_skills:
        apply_start_bonuses(f, battle_skills)
        revive = battle_skills[0]
        raw_pr = revive.get("pr")
        f.effects["revive"] = {
            "name": str(revive.get("name") or "复活技"),
            "ratio": min(1.0, max(0.05, float(revive.get("恢复比例", 0.7) or 0.7))),
            "pr": 1.0 if raw_pr is None else min(1.0, max(0.0, float(raw_pr))),
            "msg": str(revive.get("msg2") or ""),
            "used": False,
        }
        f.tags["battle_skills"] = [str(s.get("name")) for s in battle_skills]
    return f