"""Pinned-source Xiangu tribulation schedules and pure wave planning.

Stage schedules/result metadata follow commit 04af6a9a7ec11e700a0aedb85a5981e48826035c
(`apps/SecretPlace/xianguTribulation.js`). Damage follows the original theoretical
attack/era/horror pipeline if supplied; current main call sites provide only local
aggregate attack, which is reported as an adapter.
"""
from __future__ import annotations

import math
import random
from typing import Any

# Exact fixed-source BODY_EFFECTS reductions/specials from xianguTribulation.js.
_BODY_EFFECTS: dict[str, tuple[float, str | None]] = {
    "天生至尊": (.25, "至尊初现"), "涅槃·至尊": (.40, None),
    "终极涅槃·至尊": (.65, "终极至尊"), "重瞳者": (.50, "重瞳开天"),
    "荒古圣体": (.15, None), "小成·荒古圣体": (.30, "圣体异象"),
    "大成·荒古圣体": (.60, "圣体异象"),
    "苍天霸体": (.20, "霸钟护体"), "小成·苍天霸体": (.35, "霸钟护体"),
    "大成·苍天霸体": (.55, "霸钟护体"), "先天道胎": (.10, "道法自然"),
    "先天圣体道胎": (.65, "混沌青莲"), "混沌体": (.45, "混沌护体"),
    "先天混沌圣体道胎": (.80, "混沌开天"),
    "太阳之体": (.08, None), "太阳神体": (.25, "太阳真火"),
    "太阳圣皇体": (.40, "太阳圣皇"), "太阴之体": (.08, None),
    "太阴神体": (.25, "太阴真水"), "太阴圣皇体": (.40, "太阴圣皇"),
    "神王体": (.12, None), "小成·神王体": (.28, "神王净土"),
    "大成·神王体": (.45, "神王再生术"), "天妖体": (.10, None),
    "天妖王体": (.30, "妖王真身"), "天妖皇体": (.50, "妖皇真身"),
    "伪·魔胎仙体": (.35, "魔气护体"), "魔胎仙体": (.70, "魔主降世"),
    "命运神道体": (.30, "命运长河"), "极道天魔": (.35, "天魔真身"),
    "终焉神魔体": (.55, "终焉降临"), "彼岸·命运神道体": (.75, "彼岸金桥"),
    "无相·万化天魔体": (.75, "万化魔胎"),
    "爱莉希雅": (.35, "真我刻印"), "人之律者·爱莉希雅": (.60, "始源领域"),
    "始源之律者·爱莉希雅": (.85, "始源之理"),
    "木之本樱": (.10, "库洛牌"), "星之杖·木之本樱": (.25, "星之杖"),
    "梦之杖·木之本樱": (.45, "梦之杖"), "鹿目圆": (.20, "祈愿之力"),
    "许愿者·圆": (.35, "祈愿之力"), "希望之光·圆": (.60, "希望之光"),
    "圆神": (.85, "圆环之理"), "门矢士": (.15, "骑士降临"),
    "帝骑": (.25, "帝骑之力"), "帝骑·神主": (.45, "神主形态"),
    "帝骑·终极神主": (.65, "破坏神"), "伊蕾娜": (.20, "魔女扫帚"),
    "少女流萤": (.30, "星穹之力"), "流萤萨姆机甲": (.55, "机甲武装"),
    "天命青儿": (.70, "天命一剑"),
}
_BODY_SPECIALS: dict[str, tuple[float, float]] = {
    # special: (chance, remaining-damage reduction); chance=1 is guaranteed.
    "圣体异象": (.30, .15), "霸钟护体": (.25, .50), "道法自然": (1, .10),
    "混沌青莲": (.40, .25), "混沌护体": (1, .20), "混沌开天": (.50, .35),
    "太阳真火": (1, .15), "太阳圣皇": (.30, .25), "太阴真水": (1, .15),
    "太阴圣皇": (.30, .25), "神王净土": (.15, 1.0), "妖王真身": (1, .20),
    "妖皇真身": (.35, .30), "魔气护体": (1, .15), "魔主降世": (.40, .40),
    "至尊初现": (.25, .15), "终极至尊": (.40, .30), "重瞳开天": (1, .15),
    "命运长河": (1, .10), "天魔真身": (.30, .25), "终焉降临": (1, .20),
    "彼岸金桥": (1, .25), "库洛牌": (.30, .20), "星之杖": (1, .15),
    "梦之杖": (.35, .30), "祈愿之力": (1, .10), "圆环之理": (.50, .40),
    "骑士降临": (.25, .30), "帝骑之力": (1, .15), "神主形态": (.35, .35),
    "破坏神": (1, .25), "魔女扫帚": (1, .10), "星穹之力": (1, .15),
    "机甲武装": (.40, .30), "天命一剑": (1, .25),
}


def apply_wave_defenses(doc: Any, raw_damage: int, rng: random.Random) -> dict[str, Any]:
    """Apply the pinned-source body, special, revival-passive and treasure defenses.

    Returns `damage`, explanatory `messages`, and explicit `adaptations`. Lethal
    revival selection remains the caller's responsibility so it can await chat input.
    """
    ext = getattr(doc, "ext", {})
    if not isinstance(ext, dict):
        ext = {}
    hp_max = max(1, int(ext.get("hp_max", 0) or ext.get("base_hp", 0) or 1))
    hp = max(0, min(hp_max, int(ext.get("hp", hp_max) or 0)))
    damage = max(1, int(raw_damage))
    messages: list[str] = []
    adaptations = ["欺天阵纹区间偏移按比例伤害映射；原版改变雷劫判定区间。", "帝兵采用本地本命帝兵阶段表近似原版仙古专属阶梯。"]

    root = ext.get("linggen") if isinstance(ext.get("linggen"), dict) else {}
    name = str(root.get("name") or "")
    reduction = 0.0
    special: str | None = None
    special_label = name or "体质"
    # The original prefers Suiyun, then Memory, then the static body table.
    try:
        from . import suiyun
        suiyun_reduction = max(0.0, float(suiyun.trib_reduction(doc)))
        if suiyun_reduction > 0:
            reduction = min(.95, suiyun_reduction)
            special = "圆环之理" if bool(suiyun.effects(doc).get("madoka")) else None
            special_label = "岁云传承"
    except Exception:
        pass
    if reduction <= 0:
        try:
            from . import memory
            memory_reduction = max(0.0, float(memory.effects(doc).get("trib", 0) or 0))
            if memory_reduction > 0:
                reduction = min(.95, memory_reduction)
                special_label = "记忆因子"
        except Exception:
            pass
    if reduction <= 0:
        body = _BODY_EFFECTS.get(name)
        if body:
            reduction, special = body
    if special_label not in {"岁云传承", "记忆因子"}:
        try:
            from . import supreme
            reduction = max(reduction, float(supreme.trib_reduction(doc)))
        except Exception:
            pass
    if reduction > 0:
        saved = int(damage * min(.95, reduction))
        damage -= saved
        messages.append(f"【{special_label}】体质/本源减伤 {saved:,}。")

    if special and special not in {"真我刻印", "始源领域", "始源之理", "希望之光"}:
        if special == "神王再生术":
            if hp < hp_max * .30:
                heal = min(hp_max - hp, int(hp_max * .25))
                ext["hp"] = hp + heal
                messages.append(f"【神王再生术】恢复 {heal:,} 气血。")
        elif special == "神灵之泪":
            heal = min(hp_max - hp, int(hp_max * .08))
            ext["hp"] = hp + heal
            messages.append(f"【神灵之泪】恢复 {heal:,} 气血。")
        elif special in _BODY_SPECIALS:
            chance, rate = _BODY_SPECIALS[special]
            if rng.random() < chance:
                saved = int(damage * rate)
                damage -= saved
                messages.append(f"【{special}】异象护体，额外减免 {saved:,} 劫伤。")

    # The source consumes a queued Black Emperor formation once per tribulation.
    try:
        from . import story_npc
        formation_state = story_npc.state_of(doc)
        formation = story_npc.resolve_tribulation_formation(formation_state, rng)
        if formation.get("message"):
            messages.append(str(formation["message"]))
        damage = max(1, int(damage * float(formation.get("damage_multiplier", 1.0) or 1.0)))
        shift = max(-15, min(15, int(formation.get("range_shift", 0) or 0)))
        if shift:
            before = damage
            damage = max(1, int(damage * (1 + shift / 100)))
            messages.append(f"欺天阵纹区间偏移 {shift:+d} 点，伤害映射 {before:,}→{damage:,}。")
    except Exception:
        adaptations.append("欺天阵纹读取失败，本波未应用阵纹效果。")

    # A personal imperial weapon is represented by the locally-owned Dibing record.
    try:
        from . import dibing
        weapon = dibing.system_of(doc)
        worn = ext.get("equipment") if isinstance(ext.get("equipment"), dict) else {}
        weapon_name = str(dibing.item_card(weapon).get("name") or "") if weapon else ""
        if weapon and weapon_name and str(worn.get("帝兵") or "") == weapon_name:
            rank = str(dibing.item_card(weapon).get("品阶") or "")
            rank_index = dibing.STAGES.index(rank)
            if rank_index >= 1:
                probability = min(.95, .30 + rank_index * .08)
                reduction_rate = min(.70, .15 + rank_index * .06)
                if rng.random() < probability:
                    saved = int(damage * reduction_rate)
                    damage = max(1, damage - saved)
                    messages.append(f"【本命帝兵护主·{rank}】自主复苏，减免 {saved:,} 劫伤。")
    except (ValueError, TypeError, AttributeError):
        adaptations.append("本命帝兵品阶读取失败，本波未应用帝兵护主。")

    # The source applies these passives only from the wave after a revival.
    states = ext.get("tribulation_effects")
    if ext.get("_xiangu_tribulation_revived") and isinstance(states, dict):
        states = dict(states)
        current_hp = max(0, min(hp_max, int(ext.get("hp", hp) or 0)))
        factor = max(.01, float(era_factor or 1.0))
        zhe = states.get("者字秘")
        if isinstance(zhe, dict) and int(zhe.get("remaining", 0) or 0) > 0:
            rate = max(0.0, min(.95, float(zhe.get("reduction", .25) or 0))) * factor
            saved = int(damage * rate)
            damage = max(0, damage - saved)
            heal = min(hp_max - current_hp, int(hp_max * float(zhe.get("heal_ratio", .05) or 0)))
            current_hp += max(0, heal)
            zhe["remaining"] = max(0, int(zhe["remaining"]) - 1)
            messages.append(f"【者字秘】减伤 {saved:,}，恢复 {max(0, heal):,} 气血。")
        immortal = states.get("不灭经")
        if isinstance(immortal, dict) and int(immortal.get("remaining", 0) or 0) > 0:
            rate = max(0.0, min(.95, float(immortal.get("reduction", .4) or 0)))
            saved = int(damage * rate)
            damage = max(0, damage - saved)
            heal = min(hp_max - current_hp, int(hp_max * float(immortal.get("heal_ratio", .3) or 0)))
            current_hp += max(0, heal)
            immortal["remaining"] = max(0, int(immortal["remaining"]) - 1)
            messages.append(f"【不灭经】减伤 {saved:,}，恢复 {max(0, heal):,} 气血。")
        phoenix = states.get("真凰宝术")
        if isinstance(phoenix, dict) and float(phoenix.get("stage_reduction", 0) or 0) > 0:
            saved = int(damage * min(.95, float(phoenix["stage_reduction"])))
            damage = max(0, damage - saved)
            phoenix["stage_reduction"] = 0
            messages.append(f"【真凰宝术】阶段减伤 {saved:,}。")
        for key in ("柳神法", "如月长存"):
            willow = states.get(key)
            if not isinstance(willow, dict):
                continue
            if int(willow.get("layers", 0) or 0) > 0:
                saved = int(damage * max(0.0, min(.95, float(willow.get("reduction", .45) or 0))))
                damage = max(0, damage - saved)
                willow["layers"] = max(0, int(willow["layers"]) - 1)
                messages.append(f"【{key}】护道减伤 {saved:,}，剩余护持 {willow['layers']} 层。")
            regen_rounds = int(willow.get("regen_rounds", 0) or 0)
            if regen_rounds > 0:
                heal = min(hp_max - current_hp,
                           int(hp_max * float(willow.get("regen_ratio", .15) or 0)))
                current_hp += max(0, heal)
                willow["regen_rounds"] = regen_rounds - 1
                messages.append(f"【{key}】持续恢复 {max(0, heal):,} 气血。")
            ext["hp"] = current_hp
            break
        nirvana = states.get("涅槃仙功")
        if isinstance(nirvana, dict) and int(nirvana.get("remaining", 0) or 0) > 0:
            saved = int(damage * max(0.0, min(.95, float(nirvana.get("reduction", .2) or 0))))
            damage = max(0, damage - saved)
            nirvana["remaining"] = max(0, int(nirvana["remaining"]) - 1)
            messages.append(f"【涅槃仙功】减伤 {saved:,}。")
        leidi = states.get("雷帝宝术")
        if isinstance(leidi, dict) and int(leidi.get("remaining", 0) or 0) > 0:
            rate = min(.4, max(0.0, float(leidi.get("conversion", .4) or 0)))
            heal = min(int(max(0, int(raw_damage)) * rate), hp_max - current_hp)
            current_hp += max(0, heal)
            leidi["remaining"] = max(0, int(leidi["remaining"]) - 1)
            messages.append(f"【雷帝宝术】转化治疗 {max(0, heal):,} 气血。")
        phoenix_trial = ext.get("凰劫效果")
        if isinstance(phoenix_trial, dict) and float(phoenix_trial.get("阶段减伤", 0) or 0) > 0:
            saved = int(damage * max(0.0, min(.95, float(phoenix_trial["阶段减伤"]))))
            damage = max(0, damage - saved)
            phoenix_trial["阶段减伤"] = 0
            messages.append(f"【凰劫再生术】减伤 {saved:,}。")
        ext["hp"] = current_hp
        ext["tribulation_effects"] = states
    try:
        from . import xtzb
        guard = min(1.0, max(.3, float(xtzb.guard_mult(doc))))
        if guard < 1.0:
            saved = int(damage * (1.0 - guard))
            damage -= saved
            messages.append(f"【先天至宝护劫】减伤 {saved:,}。")
    except Exception:
        adaptations.append("先天至宝渡劫减伤状态读取失败，未应用该层护劫效果。")

    return {"damage": max(1, int(damage)), "messages": messages,
            "adaptations": adaptations}

ROUTES: dict[int, tuple[tuple[tuple[tuple[float, str], ...], ...], bool]] = {
    8: ((((.07, "山岳雷霆倾落，雷海淬体"), (.08, "饕餮等雷霆凶兽扑杀"),
          (.10, "金色天碑镇压肉身"), (.13, "大道铡刀斩断肉身与元神")),
         ((.055, "古代铁骑与太古凶兽围杀"), (.06, "青铜古殿、九重塔与神秘大钟镇压"),
          (.065, "黑暗牢笼拘禁元神，时间碎片割魂"), (.07, "连续击穿九重雷天"),
          (.08, "第十雷域与斩仙台余波"))), True),
    9: ((((.04, "法则斩落左臂修为，跌回神火层次"), (.045, "道痕洞穿胸膛"),
          (.05, "元神与肉身反复跌境、重塑"), (.055, "全身十度圣祭")),
         ((.045, "山岳铜锣合击"), (.05, "雷泽翻涌，鳄祖扑杀"), (.055, "金色大日横空"),
          (.06, "古代骑士与九名同阶强者围攻"), (.065, "飞仙之光横斩躯体"),
          (.075, "雷霆骨炉熬炼肉身元神"), (.075, "万灵古木袭杀"),
          (.08, "第十重天真龙真凰与古台终极镇压"))), True),
    10: ((), True),
    11: ((((.025, "秩序神链缠身，分解大道本质"), (.03, "规则粒子冲击体内仙门"),
          (.035, "大道巨锤轰击肉身")),
         ((.07, "金色天锤粉碎血肉骨骼"), (.08, "神塔与大道钟波镇压元神"),
          (.095, "天刀仙剑密布虚空"), (.12, "雷海与秩序汪洋执行最终抹杀"))), True),
    12: ((((.035, "雷霆凶兽与同阶古代强者围杀"), (.04, "大道古器横空"),
          (.045, "时间碎片斩落旧日道痕"), (.05, "九重雷天镇压"),
          (.06, "仙光贯体，至尊术护主")),
         ((.045, "雷灵穿梭雷海"), (.05, "仙道劫光洗去旧我"),
          (.055, "雷池毁灭本源灌入元神"), (.06, "道躯再碎，真我执道"),
          (.075, "最后一层天合拢"))), True),
    13: ((((.04, "皓丰与帝族强者血战"), (.05, "血战中牵引天劫"),
          (.06, "雷霆洗礼与帝族杀招交织")),
         ((.045, "万道雷霆压落"), (.05, "法则汪洋冲刷肉身"),
          (.055, "大道锁链贯穿元神"), (.065, "雷海倾覆，道躯重组"),
          (.075, "天地万法只留一线生机"), (.085, "踏出斩我境最后一步"))), True),
    14: ((((.04, "万念与红尘业火反噬"), (.045, "业火焚身"),
          (.055, "因果化焰，元神近枯"), (.07, "斩尽杂念")),
         ((.05, "赤色意志光拷问肉身"), (.055, "紫色意志光震荡元神"),
          (.06, "金色审判光镇压道果"), (.07, "时光碎片切割真我"),
          (.085, "乾坤本源拒绝成道")),
         ((.055, "至尊尸骨路死气侵蚀"), (.065, "规则神矛洞穿元神"),
          (.075, "历代失败烙印拖拽真我"), (.085, "大道本源拷问"),
          (.10, "九天九夜最后一击")),
         ((.055, "天地大道试图同化道躯"), (.065, "道音侵蚀自身之道"),
          (.085, "大天地意志压顶"))), True),
    15: ((((.08, "仙道法则冲刷真我道基"), (.10, "万古仙王烙印围杀"),
          (.12, "帝光劫火震动道果"), (.15, "高阶仙道壁垒最终审判")),), False),
    16: ((((.08, "仙道法则冲刷真我道基"), (.10, "万古仙王烙印围杀"),
          (.12, "帝光劫火震动道果"), (.15, "高阶仙道壁垒最终审判")),), False),
    17: ((((.08, "仙道法则冲刷真我道基"), (.10, "万古仙王烙印围杀"),
          (.12, "帝光劫火震动道果"), (.15, "高阶仙道壁垒最终审判")),), False),
    18: ((((.08, "仙道法则冲刷真我道基"), (.10, "万古仙王烙印围杀"),
          (.12, "帝光劫火震动道果"), (.15, "高阶仙道壁垒最终审判")),), False),
    19: ((((.08, "仙道法则冲刷真我道基"), (.10, "万古仙王烙印围杀"),
          (.12, "帝光劫火震动道果"), (.15, "高阶仙道壁垒最终审判")),), False),
}
OFFSETS = {8: (0, 4), 9: (0, 4), 10: (), 11: (0, 3), 12: (0, 5),
           13: (0, 3), 14: (0, 4, 9, 14), 15: (0,), 16: (0,),
           17: (0,), 18: (0,), 19: (0,)}
RESULTS: dict[int | str, dict[str, Any]] = {
    8: {"target_level_id": 9, "reward": "雷池真液"},
    9: {"target_level_id": 10, "reward": "雷池真液"},
    10: {"target_level_id": 11, "no_tribulation": True},
    11: {"target_level_id": 12, "path": "以身为种"},
    12: {"target_level_id": 13, "path": "斩我明道", "reward": "雷池真液", "thunder_spirits": 3},
    13: {"target_level_id": 14, "path": "遁去其一", "reward": "雷池真液"},
    14: {"target_level_id": 15, "path": "至尊路", "carry_dao_decision_required": True},
    15: {"target_level_id": 16, "path": "高阶仙道冲关"},
    16: {"target_level_id": 17, "path": "高阶仙道冲关"},
    17: {"target_level_id": 18, "path": "高阶仙道冲关"},
    18: {"target_level_id": 19, "path": "高阶仙道冲关"},
    19: {"target_level_id": 20, "path": "高阶仙道冲关"},
    "九天十地": {"target_level_id": 12, "path": "九天十地劫", "reward": "雷池真液", "ni_fa_zhanwo": True},
    "斩仙铡刀": {"target_level_id": 13, "path": "斩仙铡刀", "reward": "雷池真液", "zhanwo_peak": True},
}
EXTREMES = {
    "九天十地": ((((.035, "异域大军压境"), (.04, "古代强者烙印围杀"),
                  (.045, "帝族年轻至尊烙印"), (.05, "九天十地大战重现"),
                  (.06, "大道古器镇压")),
                ((.05, "最后一层天合拢"), (.06, "雷池毁灭本源"),
                 (.07, "万雷归一轰击道种"), (.085, "雷池之巅逆伐斩我之力"))), True),
    "斩仙铡刀": ((((.04, "雷渊万劫磨灭斩我道痕"), (.045, "雷池古台锁定肉身元神"),
                   (.055, "斩仙铡刀斩开元神印记"), (.07, "不朽印记与旧束缚尽断")),
                 ((.05, "肉身被铡刀斩断"), (.06, "六位真仙不朽印记崩解"),
                  (.075, "雷劫液重塑道躯"))), True),
}
EXTREME_OFFSETS = {"九天十地": (0, 5), "斩仙铡刀": (0, 4)}


def result_metadata(from_level: int | None = None, route: str | None = None) -> dict[str, Any]:
    """Pinned completion metadata for a normal or named extreme route."""
    key: int | str = route if route else int(from_level or 0)
    return dict(RESULTS.get(key) or {})


def horror_multiplier(from_level: int) -> int:
    level = int(from_level)
    if level >= 14:
        return 30
    return {11: 15, 12: 20, 13: 25}.get(level, 1)


def _horror_damage(base_damage: float, max_hp: int, multiplier: float,
                   final_wave: bool, max_damage_rate: float | None) -> tuple[int, str]:
    raw = max(1.0, float(base_damage)) * max(1.0, float(multiplier))
    if multiplier <= 1:
        return max(1, int(raw)), "uncapped"
    progress = max(0.0, min(1.0, (float(multiplier) - 15) / 15))
    default_cap = .55 + progress * .30 if final_wave else .18 + progress * .27
    cap_rate = (min(default_cap, float(max_damage_rate))
                if max_damage_rate is not None and float(max_damage_rate) > 0 else default_cap)
    cap = max(1, int(max_hp)) * cap_rate
    damage = cap * (1 - math.exp(-raw / cap))
    return max(1, int(damage)), f"cap={cap_rate:.1%}"


def wave_events(*, max_hp: int, attack: int, from_level: int,
                rng: random.Random, route: str | None = None,
                theoretical_attack: int | None = None, era_factor: float = 1.0,
                dao_heart_multiplier: float = 1.0, horror: float | None = None) -> list[dict[str, Any]]:
    """Pure wave/refill plan suitable for an async handler to await per event.

    Each event is `kind=wave` with route/result metadata and calculated damage,
    or `kind=refill` marking the source's stage intermission restoration. This
    function does not mutate player state or settle rewards.
    """
    route_key: int | str = route if route else int(from_level)
    schedule = EXTREMES.get(route) if route else ROUTES.get(int(from_level))
    if schedule is None:
        return []
    stages, refill = schedule
    hp_max = max(1, int(max_hp))
    source_attack = max(1, int(theoretical_attack)) if theoretical_attack is not None else max(1, int(attack))
    proxy = theoretical_attack is None
    multiplier = float(horror if horror is not None else horror_multiplier(from_level))
    offsets = EXTREME_OFFSETS.get(route, ()) if route else OFFSETS.get(int(from_level), ())
    meta = result_metadata(from_level=from_level, route=route)
    events: list[dict[str, Any]] = []
    wave_count = 0
    for stage_index, stage in enumerate(stages):
        offset = offsets[stage_index] if stage_index < len(offsets) else wave_count
        weight_total = max(1, len(stage) - 1) + 1.5
        for index, (fraction, note) in enumerate(stage):
            wave_count += 1
            wave_id = offset + index + 1
            base = source_attack * fraction * (1 + .03 * wave_id) * max(.01, float(era_factor)) * max(0.0, float(dao_heart_multiplier))
            final = index == len(stage) - 1
            cap_rate = 1.1 * (1.5 if final else 1.0) / weight_total if multiplier > 1 else None
            damage, cap_note = _horror_damage(base, hp_max, multiplier, final, cap_rate)
            events.append({"kind": "wave", "route": route_key, "result": meta,
                           "stage": stage_index + 1, "wave": wave_id, "fraction": fraction,
                           "note": note, "damage": damage, "cap": cap_note,
                           "damage_model": "local_attack_proxy" if proxy else "theoretical_attack",
                           "adaptation": "入口未提供原版理论攻击，使用本地聚合攻击替代。" if proxy else "原版理论攻击公式已由调用方传入。"})
        if refill and stage_index < len(stages) - 1:
            events.append({"kind": "refill", "route": route_key, "result": meta,
                           "stage": stage_index + 1, "hp": hp_max, "note": "原版阶段间复苏至满血"})
    return events


def resolve(doc: Any, max_hp: int, attack: int, rng: random.Random,
            from_level: int, *, theoretical_attack: int | None = None,
            era_factor: float = 1.0, dao_heart_multiplier: float = 1.0,
            horror: float | None = None) -> dict[str, Any]:
    """Synchronous compatibility wrapper over `wave_events` for normal routes."""
    level = int(from_level)
    meta = result_metadata(from_level=level)
    if level not in ROUTES:
        return {"supported": False, "success": False, "log": [], **meta}
    max_hp = max(1, int(max_hp))
    events = wave_events(max_hp=max_hp, attack=attack, from_level=level, rng=rng,
                         theoretical_attack=theoretical_attack, era_factor=era_factor,
                         dao_heart_multiplier=dao_heart_multiplier, horror=horror)
    if not ROUTES[level][0]:
        doc.ext["hp"] = max_hp
        return {"supported": True, "success": True, "hp": max_hp, "waves": 0,
                "log": ["原版天神阶段不降雷劫，仙气道果自然晋阶。"],
                "damage_model": "no_tribulation", "result": meta}
    hp = max(1, int(doc.ext.get("hp", max_hp) or max_hp))
    logs: list[str] = []
    completed = 0
    for event in events:
        if event["kind"] == "refill":
            hp = int(event["hp"])
            logs.append(event["note"])
            continue
        hp -= int(event["damage"])
        completed += 1
        logs.append(f"第{event['wave']}道（阶段{event['stage']}）{event['note']}，承受 {event['damage']:,} 劫伤，剩余 {max(0,hp):,}/{max_hp:,}（{event['cap']}）。")
        if hp <= 0:
            doc.ext["hp"] = 1
            return {"supported": True, "success": False, "hp": 1, "waves": completed,
                    "log": logs, "result": meta, "damage_model": event["damage_model"],
                    "adaptation": event["adaptation"]}
    doc.ext["hp"] = hp
    last = next((event for event in reversed(events) if event["kind"] == "wave"), {})
    return {"supported": True, "success": True, "hp": hp, "waves": completed,
            "log": logs, "result": meta, "damage_model": last.get("damage_model"),
            "adaptation": last.get("adaptation")}
