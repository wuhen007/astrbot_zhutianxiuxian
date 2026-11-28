"""渡劫 / 登仙 / 功法熟练度（原版 apps/User/Level.js + model/xiuxian.js）。

肉身劫按原版灵根劫数逐波结算、使用原版雷抗/随机区间/体质打散规则，失败后按原版保留 1 点气血、
修为减半；可用复活功法会消耗生命本源并跳过本道，继续后续雷劫。肉身劫通过后保存 power=1，
再单独运行原版九转元神劫；power=2 仅在九转完成时设置。为适配同步消息处理，逐波和九转即时推进，
省略原版每波/每转 60 秒间隔；普通渡劫不再聚合成一次随机判定。

功法熟练度沿用本移植现有六档和感悟规则。
"""

from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

TRIB_REALM = 40            # 无妄真劫境（0-based）
ASCEND_REALM = 41          # 地仙
SPIRIT_CD = 30 * 60        # 元神劫失败 CD
MIN_SPIRIT_RATIO = 0.9     # 血量须 ≥ 上限 90%
THUNDER_N = 11.8           # 原版 11800 ÷1000
THUNDER_P = 2.8            # 原版 2800 ÷1000

PROF_MAX = 1000
PROF_DAILY = 20
INSIGHT_PER_BATTLE = 2

ROOT_ROUNDS = {
    "伪灵根": 3, "真灵根": 6, "天灵根": 9, "体质": 10,
    "转生": 21, "魔头": 21, "妖体": 26, "神体": 26,
    "圣体": 52, "小成圣体": 72, "混沌体": 82, "至尊体": 96,
    "大成圣体": 102, "大道体": 102, "圣体道胎": 128, "神慧者": 1280,
}
DEFAULT_ROUNDS = 12

PROF_STAGES = [
    ("初窥门径", 0, 1.00, 1.00, 1.00),
    ("略有所成", 100, 1.03, 1.02, 1.02),
    ("融会贯通", 250, 1.06, 1.04, 1.04),
    ("炉火纯青", 500, 1.09, 1.07, 1.06),
    ("登峰造极", 750, 1.12, 1.10, 1.08),
    ("出神入化", 1000, 1.15, 1.15, 1.10),
]


def prof_of(doc: Any) -> dict:
    ext = getattr(doc, "ext", None)
    prof = ext.get("prof") if isinstance(ext, dict) else None
    return dict(prof) if isinstance(prof, dict) else {}


def stage_of(prof: float) -> tuple[str, float, float, float]:
    """(档名, trigger, combat, numeric)。"""
    cur = PROF_STAGES[0]
    for row in PROF_STAGES:
        if prof >= row[1]:
            cur = row
    return cur[0], cur[2], cur[3], cur[4]


def best_stage(doc: Any) -> tuple[str, float, float, float]:
    """已学功法中最高档位（battle 装填用）。"""
    learned = set(getattr(doc, "ext", {}).get("gongfa") or [])
    prof = prof_of(doc)
    best = PROF_STAGES[0][0], 1.0, 1.0, 1.0
    for name in learned:
        name = str(name).strip()
        if not name:
            continue
        stage = stage_of(float(prof.get(name, 0) or 0))
        if stage[1] > best[1]:
            best = stage
    return best


def add_insight(doc: Any, amount: int = INSIGHT_PER_BATTLE) -> int:
    """战斗后感悟值 +amount（写 ext["insight"]）。"""
    ext = doc.ext
    cur = int(ext.get("insight", 0) or 0)
    ext["insight"] = cur + max(0, int(amount))
    return ext["insight"]


def allocate(doc: PlayerDoc, name: str, amount: int) -> tuple[bool, str]:
    """感悟值 → 熟练度（1:1，上限 1000）。须已学该功法。"""
    name = name.strip()
    learned = [str(x) for x in (doc.ext.get("gongfa") or [])]
    if name not in learned:
        return False, f"尚未参悟「{name}」，无法分配感悟。"
    balance = int(doc.ext.get("insight", 0) or 0)
    if amount <= 0:
        return False, "分配数量须为正整数。"
    prof = prof_of(doc)
    cur = int(prof.get(name, 0) or 0)
    if cur >= PROF_MAX:
        return False, f"「{name}」已至出神入化（{PROF_MAX}），感悟再难精进。"
    gain = min(amount, PROF_MAX - cur)   # 超额分配只消耗到上限所需
    if balance < gain:
        return False, f"功法感悟不足：需要 {gain} 点，当前仅有 {balance} 点。"
    prof[name] = cur + gain
    doc.ext["prof"] = prof
    doc.ext["insight"] = balance - gain
    st = stage_of(prof[name])
    return True, (f"「{name}」参悟精进：熟练度 {cur} → {prof[name]}（{st[0]}）\n"
                  f"剩余感悟 {doc.ext['insight']} 点。")


def prof_text(doc: PlayerDoc) -> str:
    learned = [str(x) for x in (doc.ext.get("gongfa") or [])]
    prof = prof_of(doc)
    lines = [f"--- 功法参悟 ---",
             f"感悟值：{int(doc.ext.get('insight', 0) or 0)}（战斗每场 +{INSIGHT_PER_BATTLE}）",
             f"分配：#分配功法感悟 功法名*数量"]
    if not learned:
        lines.append("尚未参悟任何功法。")
    for name in learned:
        v = int(prof.get(name, 0) or 0)
        st = stage_of(v)
        lines.append(f"· {name}：{v}/{PROF_MAX}（{st[0]}｜触发 ×{st[1]:.2f} 战斗 ×{st[2]:.2f}）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 渡劫 / 登仙

def thunder_resist(doc: PlayerDoc, stats: Any) -> float:
    """雷抗 dujie 直译（属性 ÷1000 标度，n/p 已同比缩放）。stats 需含 atk/defense/hp。"""
    nb = float(doc.ext.get("hp", stats.hp) or 0) / 100_000
    nd = float(stats.defense) / 100_000
    na = float(stats.atk) / 100_000
    N = nb * 0.4 + nd * 0.6
    return N * (na * 0.2)


def _spirit_current(doc: PlayerDoc) -> int:
    from . import yuanshen
    current = yuanshen.cur_of(doc)
    if current > 0:
        return current
    legacy = doc.ext.get("legacy_source")
    return max(0, int((legacy.get("元神", 0) if isinstance(legacy, dict) else 0) or 0))


def trib_check(doc: PlayerDoc, table: list[dict], stats: Any, hp_cur: float, hp_max: float) -> str | None:
    """Check original realm and attempt gates in source order."""
    if int(doc.realm_index) != TRIB_REALM:
        return "你非无妄真劫境修士！"
    lg = doc.ext.get("linggen")
    if not isinstance(lg, dict) or not lg.get("name"):
        return "你灵根未开，不能渡劫！"
    power = int(doc.ext.get("power", 0) or 0)
    if power >= 2:
        return "你已渡过双重真劫，请感应仙门 #登仙。"
    if power == 1:
        fail_ts = float(doc.ext.get("spirit_fail_ts", 0) or 0)
        if fail_ts and time.time() - fail_ts < SPIRIT_CD:
            left = SPIRIT_CD - (time.time() - fail_ts)
            return f"元神尚未恢复，强行渡劫恐有魂飞魄散之险！还需 {left / 60:.0f} 分钟。"
        spirit = _spirit_current(doc)
        if spirit < 500_000:
            return f"元神强度不足（需至少 500,000，当前 {spirit:,}）。"
        return None
    if hp_cur < hp_max * MIN_SPIRIT_RATIO:
        return "血量亏损，强行渡劫恐有性命之忧（需 90% 满血）。"
    need = int(table[min(TRIB_REALM, len(table) - 1)].get("exp", 0) or 0) if table else 0
    if doc.exp < need:
        return f"修为不足，再积累 {need - doc.exp:,} 修为后方可渡劫。"
    # Dao-wound protection is an additional port-specific gate; surface it before the new spirit gate.
    try:
        from . import zhengdao as _dz
        w = _dz.peek(doc)
        if w >= 3.0:
            return (f"身负道伤 {w:.1f} ≥3，劫云不认残破之基——"
                    "先 #修复道伤 / #道基重塑 / #根源波动 祛伤。")
    except Exception:
        pass
    spirit = _spirit_current(doc)
    if spirit < 500_000:
        return f"元神强度不足（需至少 500,000，当前 {spirit:,}）。"
    return None
def root_bonus_of(doc: PlayerDoc) -> float:
    linggen_type = str((doc.ext.get("linggen") or {}).get("type") or "")
    bonuses = {"伪灵根": 1.0, "真灵根": 1.5, "天灵根": 1.75,
               "转生": 2.5, "魔头": 2.5, "神体": 3.0, "妖体": 3.0,
               "圣体": 4.0, "小成圣体": 5.0, "大成圣体": 8.0,
               "至尊体": 8.0, "命运": 8.0, "天魔": 8.0,
               "混沌体": 8.0, "大道体": 8.0, "圣体道胎": 10.0,
               "神魔体": 12.0, "神慧者": 15.0}
    try:
        from . import suiyun
        if suiyun.effects(doc).get("madoka"):
            return 15.0
    except Exception:
        pass
    return bonuses.get(linggen_type, 1.0)


def body_opening_failure(doc: PlayerDoc, stats: Any, level_exp: int = 0) -> bool:
    """Original pre-wave check; on failure lose one quarter of current realm exp."""
    x = thunder_resist(doc, stats) * root_bonus_of(doc)
    virtual = float(doc.ext.get("virtual_rate", doc.ext.get("虚实转化率", 0)) or 0)
    if virtual > 0:
        reduction = min(0.5, virtual * 0.7)
        x *= min(2.0, 1 + virtual * 5) * (1 + reduction / 2)
        lower = THUNDER_N * (1 - reduction)
    else:
        lower = THUNDER_N
    if x > lower:
        return False
    lost = int(max(0, int(level_exp)) / 4)
    doc.exp = max(0, int(doc.exp) - lost)
    doc.ext["hp"] = 0
    return True


def tribulation_rounds(doc: PlayerDoc) -> int:
    lg = doc.ext.get("linggen") or {}
    return ROOT_ROUNDS.get(str(lg.get("type") or ""), DEFAULT_ROUNDS)


def roll_body_wave(doc: PlayerDoc, stats: Any, rng: random.Random, wave: int,
                    range_shift: int = 0, inventory: dict[str, int] | None = None) -> dict[str, Any]:
    """Resolve the original per-wave body-thunder formula without applying a death penalty."""
    tick_revival_cooldowns(doc)
    current_hp = max(0, int(doc.ext.get("hp", stats.hp) or 0))
    hp_max = max(1, int(stats.hp))
    physique = int(doc.physique_index) + 1
    if physique == 43:
        damage = int(hp_max * 0.25)
        hp_after = current_hp - damage
        # The fixed original always disarms the wave for Physique_id == 43.
        return {"wave": wave, "success": True, "hp": max(1, hp_after),
                "damage": damage, "description": f"肉身打散雷劫，承受气血损失 {damage:,}。",
                "bonus": 100_000 * wave if wave >= tribulation_rounds(doc) else 0}

    x = thunder_resist(doc, stats)
    x *= root_bonus_of(doc)
    effects = doc.ext.get("tribulation_effects")
    effects = effects if isinstance(effects, dict) else {}
    virtual = float(doc.ext.get("virtual_rate", doc.ext.get("虚实转化率", 0)) or 0)
    if virtual > 0:
        x *= min(2.0, 1 + virtual * 5)
    reduction = min(0.5, virtual * 0.7) if virtual > 0 else 0.0
    low = THUNDER_N * (1 - reduction)
    spread = THUNDER_P * (1 - reduction)
    if reduction:
        x *= 1 + reduction / 2
    herbs_used: list[str] = []
    if inventory is not None:
        for index, name in enumerate(("凝血草", "小吉祥草", "大吉祥草")):
            if int(inventory.get(name, 0) or 0) > 0:
                inventory[name] = int(inventory[name]) - 1
                x = int(x * (1 + 0.2 * index))
                herbs_used.append(name)
    # Source adds wave / 10 in raw 11800/2800 units; scale this offset with n/p.
    variable = low + float(rng.random()) * spread + wave / 10_000
    # Preserve the existing formation modifier as a bounded chance shift within this wave.
    variable -= (max(-15, min(15, int(range_shift))) / 100.0) * spread

    if physique > 43:
        # Fixed original high physique bypasses the random thunder roll.
        damage = int(current_hp * 0.05)
        hp_after = max(1, current_hp - damage)
        bonus = 500_000 * wave if wave >= tribulation_rounds(doc) else 0
        return {"wave": wave, "success": True, "hp": hp_after, "damage": damage,
                "herbs_used": herbs_used, "description": f"天劫被肉身炼化，损失 {damage:,} 点气血。",
                "bonus": bonus}
    chip = 0
    after_chip = current_hp
    if x >= variable:
        ratio = max(0.0, min(1.0, (variable - low) / max(spread, 1e-9)))
        original_damage = int(after_chip * ratio)
        damage = float(original_damage)
        current = after_chip
        effect_messages: list[str] = []
        max_hp = max(1, int(stats.hp))
        effects = doc.ext.get("tribulation_effects")
        effects = dict(effects) if isinstance(effects, dict) else {}

        zhe = effects.get("者字秘")
        if isinstance(zhe, dict) and int(zhe.get("remaining", 0) or 0) > 0:
            damage -= original_damage * float(zhe.get("reduction", 0.25) or 0.25)
            heal = min(int(max_hp * float(zhe.get("heal_ratio", 0.05) or 0.05)),
                       max(0, max_hp - current))
            current += heal
            zhe["remaining"] = max(0, int(zhe["remaining"]) - 1)
            effect_messages.append(f"者字秘减伤并恢复 {heal:,} 气血")

        willow = effects.get("柳神法") or effects.get("如月长存")
        if isinstance(willow, dict):
            layers = max(0, int(willow.get("layers", 0) or 0))
            if layers:
                damage -= damage * float(willow.get("reduction", 0.45) or 0.45)
                willow["layers"] = layers - 1
                effect_messages.append("柳神/月华庇护抵伤")

        thunder = effects.get("雷帝宝术")
        if isinstance(thunder, dict) and int(thunder.get("remaining", 0) or 0) > 0:
            convert = min(0.4, max(0.0, float(thunder.get("conversion", 0.4) or 0.4)))
            heal = min(int(original_damage * convert), max(0, max_hp - current))
            current += heal
            # Fixed source stores/displays this value but the ordinary LevelTask
            # path does not use it in later wave resistance checks.
            thunder["current_resist"] = min(0.9, float(thunder.get("current_resist", 0) or 0)
                                            + float(thunder.get("resist_gain", 0.1) or 0.1))
            thunder["remaining"] = max(0, int(thunder.get("remaining", 0) or 0) - 1)
            effect_messages.append(f"雷帝宝术转化伤害并恢复 {heal:,} 气血")

        phoenix = effects.get("真凰宝术")
        if isinstance(phoenix, dict) and phoenix.get("immune") and damage >= current:
            damage = max(0, current - 10_000)
            phoenix["immune"] = False
            effect_messages.append("真凰涅槃触发免死")

        immortal = effects.get("不灭经")
        if isinstance(immortal, dict) and int(immortal.get("remaining", 0) or 0) > 0:
            damage -= original_damage * float(immortal.get("reduction", 0.4) or 0.4)
            heal = min(int(max_hp * float(immortal.get("heal_ratio", 0.3) or 0.3)),
                       max(0, max_hp - current))
            current += heal
            immortal["remaining"] = max(0, int(immortal["remaining"]) - 1)
            effect_messages.append(f"不灭经减伤并恢复 {heal:,} 气血")

        wan = effects.get("万化圣诀")
        if isinstance(wan, dict) and wan.get("immune") and damage >= current:
            damage = max(0, current - 10_000)
            wan["immune"] = False
            effect_messages.append("万化圣诀触发免死")

        nirvana = effects.get("涅槃仙功")
        if isinstance(nirvana, dict) and int(nirvana.get("remaining", 0) or 0) > 0:
            damage -= original_damage * float(nirvana.get("reduction", 0.2) or 0.2)
            nirvana["remaining"] = max(0, int(nirvana.get("remaining", 0) or 0) - 1)
            effect_messages.append("涅槃仙功减伤")

        # Original LevelTask applies the damage then clamps current HP to 1;
        # HP<=1 is the lethal trigger that requests revival/ends the body round.
        hp_after = max(1, int(current - max(0.0, damage)))
        doc.ext["tribulation_effects"] = effects
        # Fixed LevelTask applies 柳神/月华持续恢复 after clamping wave HP to at least 1,
        # then checks whether the survivor remains at the lethal threshold.
        if isinstance(willow, dict):
            regen = max(0, int(willow.get("regen_rounds", 0) or 0))
            if regen:
                heal = min(int(max_hp * float(willow.get("regen_ratio", 0.15) or 0.15)),
                           max(0, max_hp - hp_after))
                hp_after += heal
                willow["regen_rounds"] = regen - 1
                if heal:
                    effect_messages.append(f"柳神/月华持续恢复 {heal:,}")
        survived = hp_after > 1
        bonus = ((500_000 if physique > 43 else 100_000) * wave
                 if survived and wave >= tribulation_rounds(doc) else 0)
        herb_text = (f" 草药护持：{'、'.join(herbs_used)}。" if herbs_used else "")
        effect_text = (" " + "、".join(effect_messages) + "。" if effect_messages else "")
        return {"wave": wave, "success": survived, "hp": hp_after,
                "damage": chip + int(max(0.0, damage)), "herbs_used": herbs_used,
                "description": f"第 {wave} 道雷劫落下，雷抗 {x:.2f}，承伤 {chip + int(max(0.0, damage)):,}。{herb_text}{effect_text}",
                "bonus": bonus}
    return {"wave": wave, "success": False, "hp": 0, "damage": chip + after_chip,
            "description": f"第 {wave} 道雷劫未能抵挡，雷抗 {x:.2f}，气血崩散。"}


def finish_body_wave(doc: PlayerDoc, result: dict[str, Any], selected_skill: str | None = None,
                     require_choice: bool = False) -> tuple[str, str]:
    """Apply one rolled wave; return (continue|success|failed|needs_choice, message)."""
    if result.get("success"):
        doc.ext["hp"] = int(result["hp"])
        bonus = max(0, int(result.get("bonus", 0) or 0))
        if bonus:
            current = doc.ext.get("tribulation_bonus")
            current = dict(current) if isinstance(current, dict) else {}
            for key in ("atk", "defense", "hp"):
                current[key] = max(0, int(current.get(key, 0) or 0)) + bonus
            doc.ext["tribulation_bonus"] = current
            doc.ext["hp"] = int(doc.ext["hp"]) + bonus
            return "success", (f"{result['description']}\n肉身劫圆满，攻击、防御、生命上限各 +{bonus:,}。")
        return "continue", result["description"] + f"剩余气血 {int(result['hp']):,}。"

    choices = available_revival_skills(doc)
    if choices:
        skill = selected_skill if selected_skill in choices else None
        if skill is None and revive_mode(doc) == "自动":
            skill = choices[0]
        if skill is None and require_choice and revive_mode(doc) == "手动":
            return "needs_choice", "可选择复活功法：" + "、".join(choices)
        if skill:
            revive_text = apply_revive(doc, int(doc.exp), float(result.get("hp", 1) or 1), skill)
            if "本次损耗未能挽回" not in revive_text:
                return "continue", result["description"] + "\n" + revive_text + "本道雷劫已避过。"
    # Original LevelTask: unrecovered failure leaves 1 HP and halves current cultivation.
    doc.ext["hp"] = 1
    lost = int(doc.exp) - int(doc.exp * 0.5)
    doc.exp = int(doc.exp * 0.5)
    return "failed", (result["description"] + f"\n渡劫失败，修为 -{lost:,}，气血归一。")


def run_spirit_tribulation(doc: PlayerDoc, rng: random.Random) -> tuple[bool, str]:
    """Resolve the source-defined nine transformations immediately; round delays are presentation-only."""
    from . import yuanshen
    st = yuanshen.ensure(doc)
    legacy = doc.ext.get("legacy_source")
    legacy_spirit = max(0, int((legacy.get("元神", 0) if isinstance(legacy, dict) else 0) or 0))
    spirit = max(int(st.get("cur", 0) or 0), legacy_spirit)
    spirit_max = max(int(st.get("max", 0) or 0), spirit)
    virtual = float(doc.ext.get("virtual_rate", doc.ext.get("虚实转化率", 0.1)) or 0.1)
    factor = spirit / 1_000_000 * (1 + virtual)
    for turn in range(1, 10):
        cost = turn * 50_000
        if spirit < cost:
            # The pinned source ends for insufficient spirit without applying the
            # failed-roll cooldown or damaging spirit/virtual conversion.
            doc.ext["power"] = 1
            yuanshen.save(doc, {**st, "cur": spirit, "max": spirit_max})
            return False, f"元神第 {turn} 转枯竭（需 {cost:,}）；肉身劫已过，补足元神后可重渡。"
        strength = max(0.05, factor + rng.uniform(-0.15, 0.15))
        difficulty = 0.1 * (1.3 ** turn)
        if strength <= difficulty:
            damage = max(0.01, (1 - strength) * 0.1)
            virtual = max(0.01, virtual - damage)
            spirit_damage = damage * spirit * 0.5
            spirit = max(500_000, int(spirit - spirit_damage))
            doc.ext["virtual_rate"] = virtual
            doc.ext["spirit_fail_ts"] = time.time()
            doc.ext["spirit_tribulation_failures"] = int(doc.ext.get("spirit_tribulation_failures", 0) or 0) + 1
            doc.ext["power"] = 1
            yuanshen.save(doc, {**st, "cur": spirit, "max": spirit_max})
            return False, (f"元神化真第 {turn} 转失败，虚实转化率 -{damage:.1%}，"
                           f"元神受损 {spirit_damage:,.0f}；30 分钟后可重渡。")
        spirit -= cost
        spirit_max += int(cost * 0.1)
        virtual += 0.125
        doc.ext["virtual_rate"] = virtual
        if turn >= 7:
            doc.ext["天罗地网感知"] = True
        yuanshen.save(doc, {**st, "cur": spirit, "max": spirit_max})
    yuanshen.save(doc, {**st, "cur": spirit, "max": spirit_max})
    doc.ext["power"] = 2
    doc.ext["真实掌握度"] = 1.0
    doc.ext.pop("spirit_fail_ts", None)
    return True, f"元神化真完成！九转虚实圆满，元神 {spirit:,}/{spirit_max:,}，虚实转化率 {virtual:.1%}。"


def trib_run(doc: PlayerDoc, stats: Any, rng: random.Random,
             range_shift: int = 0, inventory: dict[str, int] | None = None) -> tuple[bool, str]:
    """Run all body waves immediately; the original one-minute intervals are presentation-only here."""
    rows = []
    rounds = tribulation_rounds(doc)
    for wave in range(1, rounds + 1):
        result = roll_body_wave(doc, stats, rng, wave, range_shift, inventory)
        status, text = finish_body_wave(doc, result)
        rows.append(text)
        if status == "failed":
            return False, "\n".join(rows)
    doc.ext["power"] = 1
    return True, "\n".join(rows + ["肉身劫已渡过，接续九转元神劫。"])


# ---------------------------------------------------------------- 渡劫复活设置（W7-1）
# 原版 model/tribulationRevival.js：按固定顺序检查可用功法；手动模式由玩家在 60 秒内选择。
REVIVE_WINDOW = 60
REVIVE_COOLDOWNS = {
    "者字秘": 7, "真凰宝术": 5, "雷帝宝术": 5, "柳神法": 5,
    "如月长存": 5, "不灭经": 4, "补天术": 9, "万化圣诀": 9,
    "涅槃仙功": 12,
}
REVIVE_PRIORITY = (
    "者字秘", "真凰宝术", "雷帝宝术", "柳神法", "如月长存",
    "不灭经", "补天术", "万化圣诀", "涅槃仙功",
)


def revival_cooldowns(doc: PlayerDoc) -> dict[str, int]:
    ext = doc.ext
    raw = ext.get("trib_revive_cooldowns")
    cooldowns = dict(raw) if isinstance(raw, dict) else {}
    legacy = ext.get("legacy_source")
    legacy_gongfa = legacy.get("功法") if isinstance(legacy, dict) else None
    if isinstance(legacy_gongfa, dict):
        for name in REVIVE_COOLDOWNS:
            row = legacy_gongfa.get(name)
            if isinstance(row, dict) and name not in cooldowns:
                cooldowns[name] = max(0, int(row.get("冷却回合", 0) or 0))
    return cooldowns


def tick_revival_cooldowns(doc: PlayerDoc) -> None:
    cooldowns = revival_cooldowns(doc)
    for name, value in tuple(cooldowns.items()):
        cooldowns[name] = max(0, int(value or 0) - 1)
    doc.ext["trib_revive_cooldowns"] = cooldowns


def revival_skill_ready(doc: PlayerDoc, skill: str) -> bool:
    if skill not in REVIVE_COOLDOWNS:
        return False
    return max(0, int(revival_cooldowns(doc).get(skill, 0) or 0)) == 0


def set_revival_cooldown(doc: PlayerDoc, skill: str) -> None:
    if skill not in REVIVE_COOLDOWNS:
        return
    cooldowns = revival_cooldowns(doc)
    cooldowns[skill] = REVIVE_COOLDOWNS[skill]
    doc.ext["trib_revive_cooldowns"] = cooldowns


def revive_mode(doc: PlayerDoc) -> str:
    return "手动" if str(doc.ext.get("trib_revive_mode") or "") == "手动" else "自动"


def set_revive_mode(doc: PlayerDoc, mode: str) -> tuple[bool, str]:
    m = (mode or "").strip()
    if m not in ("自动", "手动"):
        learned = revival_skills(doc, ())
        return False, (f"当前复活模式：{revive_mode(doc)}\n"
                       f"用法：#复活设置 自动 / #复活设置 手动")
    doc.ext["trib_revive_mode"] = m
    return True, (f"复活模式已设为【{m}】：" +
                  ("渡劫失败时自动发动已掌握的复活功法，抵消修为与气血损耗。" if m == "自动"
                   else "渡劫失败后 60 秒内发 #复活选择 序号或功法名，逾期作废。"))


def revival_skills(doc: PlayerDoc, names=REVIVE_PRIORITY) -> list[str]:
    """按原版优先级列出已掌握的复活功法（包括岁云自带的如月长存）。"""
    learned = {str(x) for x in (doc.ext.get("gongfa") or [])}
    legacy = doc.ext.get("legacy_source")
    legacy_gongfa = legacy.get("功法") if isinstance(legacy, dict) else None
    if isinstance(legacy_gongfa, dict):
        learned.update(str(name) for name in legacy_gongfa)
    if "如月长存" not in learned:
        try:
            from . import suiyun
            if suiyun.stage_of(doc) > 0:
                learned.add("如月长存")
        except Exception:
            pass
    allowed = set(str(name) for name in names) if names else set(REVIVE_PRIORITY)
    return [name for name in REVIVE_PRIORITY if name in learned and name in allowed]


def available_revival_skills(doc: PlayerDoc, names=REVIVE_PRIORITY) -> list[str]:
    """原版复活候选：有对应功法、冷却结束且生命本源不少于 50。"""
    from . import life_source
    if life_source.current(doc) < 50:
        return []
    return [name for name in revival_skills(doc, names) if revival_skill_ready(doc, name)]


def apply_revive(doc: PlayerDoc, exp_before: int, hp_before: float, skill: str | None = None) -> str:
    """执行复活并建立后续肉身雷劫可消费的原版效果状态。"""
    from . import life_source
    if skill not in REVIVE_COOLDOWNS:
        return "当前没有可发动的复活功法。"
    if not revival_skill_ready(doc, skill):
        return f"「{skill}」仍在冷却中，本次损耗未能挽回。"
    ok, remaining = life_source.consume(doc, 50)
    if not ok:
        return f"【生命本源不足】复活功法需消耗 50 点，当前 {remaining:g}；本次损耗未能挽回。"
    doc.exp = max(0, int(exp_before))
    doc.ext.pop("spirit_fail_ts", None)
    ratios = {
        "者字秘": 0.70, "真凰宝术": 1.00, "雷帝宝术": 0.40,
        "柳神法": 0.60, "如月长存": 0.60, "不灭经": 1.00,
        "补天术": 0.80, "万化圣诀": 0.50, "涅槃仙功": 0.30,
    }
    hp_max = max(1, int(doc.ext.get("hp_max", hp_before) or hp_before or 1))
    doc.ext["hp"] = max(1, int(hp_max * ratios[skill]))
    active = doc.ext.get("tribulation_effects")
    active = dict(active) if isinstance(active, dict) else {}
    states = {
        "者字秘": {"remaining": 3, "reduction": 0.25, "heal_ratio": 0.05},
        "真凰宝术": {"immune": True},
        "雷帝宝术": {"remaining": 4, "conversion": 0.4, "resist_gain": 0.1, "current_resist": 0.0},
        "柳神法": {"layers": 3, "reduction": 0.45, "regen_rounds": 5, "regen_ratio": 0.15},
        "如月长存": {"layers": 3, "reduction": 0.45, "regen_rounds": 5, "regen_ratio": 0.15},
        "不灭经": {"remaining": 5, "reduction": 0.4, "heal_ratio": 0.3, "extra_revives": 2},
        "补天术": {"cooldown_reduction": 0.2, "remaining": 3},
        "万化圣诀": {"remaining": 3, "immune": True},
        "涅槃仙功": {"remaining": 2, "reduction": 0.2},
    }
    active[skill] = states[skill]
    doc.ext["tribulation_effects"] = active
    set_revival_cooldown(doc, skill)
    doc.ext.pop("pending_revive", None)
    return (f"【复活功法·{skill}】渡劫损耗挽回，恢复气血 {doc.ext['hp']:,}/{hp_max:,}；"
            f"生命本源 -50（剩余 {remaining:g}），功法冷却 {REVIVE_COOLDOWNS[skill]} 回合。")


def arm_revive(doc: PlayerDoc, exp_before: int, hp_before: float, now: float,
               choices: list[str] | None = None) -> None:
    doc.ext["pending_revive"] = {
        "exp": int(exp_before), "hp": float(hp_before),
        "deadline": float(now) + REVIVE_WINDOW,
        "choices": [name for name in (choices or []) if name in REVIVE_PRIORITY],
    }


def consume_revive(doc: PlayerDoc, now: float, selected_skill: str | None = None) -> tuple[bool, str]:
    p = doc.ext.get("pending_revive")
    if not isinstance(p, dict):
        return False, "当前没有待发动的复活（渡劫失败且为手动模式时才会出现）。"
    if float(now) > float(p.get("deadline", 0) or 0):
        doc.ext.pop("pending_revive", None)
        return False, f"复活时机已过（{REVIVE_WINDOW} 秒窗口），本次损耗无法挽回。"
    choices = [name for name in (p.get("choices") or []) if name in REVIVE_PRIORITY]
    if choices:
        if not selected_skill or selected_skill not in choices:
            return False, "请从可用功法中使用 #复活选择 序号或功法名：" + "、".join(choices)
        skill = selected_skill
    else:
        skill = next(iter(available_revival_skills(doc)), None)
        if not skill:
            return False, "当前没有冷却结束且生命本源充足的复活功法。"
    from . import life_source
    if life_source.current(doc) < 50:
        return False, f"生命本源不足，复活需 50 点（当前 {life_source.current(doc):g}），本次损耗未挽回。"
    result = apply_revive(doc, p.get("exp", 0), p.get("hp", 1), skill)
    return "生命本源不足" not in result, result


def ascend_check(doc: PlayerDoc, table: list[dict]) -> str | None:
    if int(doc.realm_index) != TRIB_REALM:
        return "你非无妄真劫境修士！"
    if int(doc.ext.get("power", 0) or 0) < 2:
        return "尚未渡过双重真劫（先 #渡劫）。"
    return None


def ascend_cost(table: list[dict], discount: float = 0.0) -> int:
    """登仙所需修为，与登仙前置校验和实际扣除共用同一口径。"""
    if not table:
        return 1
    need = int(table[min(TRIB_REALM, len(table) - 1)].get("exp", 0) or 0)
    return max(1, int(need * (1.0 - min(0.9, max(0.0, float(discount or 0))))))


def ascend_run(doc: PlayerDoc, table: list[dict], discount: float = 0.0) -> tuple[bool, str]:
    """登仙：无妄真劫境 → 地仙，消耗当前境界 exp（命格·渡劫修为减少可折减）。"""
    need = ascend_cost(table, discount)
    if doc.exp < need:
        return False, f"登仙需修为 {need:,}（当前 {doc.exp:,}）。"
    frm = table[TRIB_REALM].get("level", "无妄真劫境")
    to = table[min(ASCEND_REALM, len(table) - 1)].get("level", "地仙")
    doc.exp -= need
    doc.realm_index = ASCEND_REALM
    return True, (f"≡≡≡ 羽化登仙 ≡≡≡\n"
                  f"仙门大开，{frm} → 【{to}】！\n"
                  f"自此寿元悠长、法力通玄，仙人之下皆蝼蚁。\n"
                  f"消耗修为 {need:,}。")
