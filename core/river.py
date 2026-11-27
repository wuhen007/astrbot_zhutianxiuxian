"""时间长河单人路径与多人同行服务；异步团队状态见 river_team。

原版语义：
- 门槛：准仙帝权柄（auth 20）组队；每阶段 15 分钟异步落雷式结算；敌人三维 = 玩家 ×1.5~3
  （TIME_RIVER_ATTRIBUTE_RANGE）；胜利奖励岁月沉淀（eraAccumulation：三帝 3-5 / 荒天帝 15 /
  未来准仙帝 45）；荒天帝传道 +2 熟练度（上限 30 次）。
- 单人入口暂保留同步事件兼容；多人队伍按原版 15 分钟阶段状态机运行，含待援、献祭续战、敌人续血与阶段奖励。
  原版门槛按权柄 20。随机事件
  （遇敌三帝法身 → 走 1v1 引擎；悟道；拾遗；荒天帝传道）。
- 奖励落点：修为/灵石/感悟值 + **岁月结晶**（ext["river"].crystal，后续兑换接口预留）+ **纪元积累**
  （ext["era_points"]，走 fashan.add_era 封顶入账；原版每场阶段战结算，胜 3-5、败 1-2，
  triad 胜 ×3，shijianchangheTask.js:477-482）。
- 已知的时间长河技能数值和奖励沿用原版数据；当前额外体系模型不足处由状态层记载并报告。
"""

from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

ROAM_CD = 15 * 60
GATE_AUTHORITY = 20
ATTR_RANGE = (1.5, 3.0)          # 原版 TIME_RIVER_ATTRIBUTE_RANGE
CRYSTAL_TRIAD = (3, 5)           # 三帝胜利岁月沉淀
CRYSTAL_HUANG = 15               # 荒天帝
CRYSTAL_LOSE = 1
ERA_WIN = (3, 5)                 # 原版 rollTimeRiverEraReward 胜利 3-5
ERA_LOSE = (1, 2)                # 原版败退 1-2
TRIAD_ERA_MULT = 3               # 原版 triad 阶段胜利 ×3（shijianchangheTask.js:478）
TEACHING_PROF = 2
TEACHING_MAX = 30

DARK_TRIAD = ("苍帝", "鸿帝", "羽帝")
FUTURE_QUASI = ("未来准仙帝·甲", "未来准仙帝·乙", "未来准仙帝·丙")
PEAK_NAMES = ("荒天帝", "叶天帝", "狠人大帝", "尸骸仙帝")

TAUNTS = (
    "羽帝喝吼：「{name}，你能挣扎到几时！？」",
    "苍帝冷幽幽地说道：「等若跟三个自己血战，你能胜出吗？」",
    "鸿帝冷漠地说道：「望穿古今未来，谁还能与我等比肩，来此一战？」",
)


def state_of(doc: PlayerDoc) -> dict:
    ext = doc.ext
    st = ext.get("river")
    return dict(st) if isinstance(st, dict) else {"crystal": 0, "teachings": 0}


def check(doc: PlayerDoc, now: float) -> str | None:
    from .authority import meets
    if not meets(doc, GATE_AUTHORITY):
        return f"时间长河是诸天禁忌，需准仙帝权柄（{GATE_AUTHORITY}/21）。"
    st = state_of(doc)
    last = float(st.get("last", 0) or 0)
    if now - last < ROAM_CD:
        left = ROAM_CD - (now - last)
        return f"神魂尚在长河余波中震荡，{int(left // 60)} 分 {int(left % 60)} 秒后再来。"
    return None


def _crystal_gain(rng: random.Random) -> int:
    return rng.randint(*CRYSTAL_TRIAD)


def _grant_era(doc: PlayerDoc, amount: int) -> int:
    """纪元积累封顶入账（fashan.add_era 为唯一实现，原版 addCappedEraAccumulation）。"""
    from . import fashan as fashan_mod
    return fashan_mod.add_era(doc, amount)


def roam(doc: PlayerDoc, stats: Any, build_fighter_fn: Any, rng: random.Random,
         now: float) -> tuple[str, dict]:
    """一段河程。build_fighter_fn(name, mult) -> Fighter（name=="__me__" 返回我方当前血量单位）。

    返回 (文案, 变化 {"crystal": +x, "exp": +x, "stones": +x, "insight": +x, "hp": h})。
    """
    st = state_of(doc)
    roll = rng.random()
    lines: list[str] = []
    battle_results: list[str] = []
    gains: dict = {"crystal": 0, "exp": 0, "stones": 0, "insight": 0}

    if roll < 0.45:
        # 原版将黑暗三帝作为敌方队伍同时交战，并各自拥有帝辉护盾与复生。
        from .combat.engine import run_team_battle
        mult = int((ATTR_RANGE[0] + (ATTR_RANGE[1] - ATTR_RANGE[0]) * rng.random()) * 100 + 0.5) / 100
        lines.append(rng.choice(TAUNTS).format(name=doc.name or "道友"))
        me_f = build_fighter_fn("__me__", 1.0)
        enemies = [build_fighter_fn(name, mult) for name in DARK_TRIAD]
        from .combat import time_river as river_combat
        for enemy in enemies:
            river_combat.apply_adversary_rules(enemy)
        river_combat.mark_party_countered([me_f], enemies)
        legacy = doc.ext.get("legacy_source") or {}
        ownway = doc.ext.get("ownway") or doc.ext.get("己道推演") or legacy.get("己道推演") or {}
        immune = (int(doc.realm_index) >= 21 or int(doc.physique_index) >= 21
                  or (max(int(doc.realm_index), int(doc.physique_index)) >= 20
                      and ownway.get("divineEmbryo") == "已结出"))
        suppression = river_combat.apply_cang_emperor_opening_suppression(me_f, immune=immune)
        if suppression:
            lines.append(suppression)
        battle = run_team_battle([me_f], enemies, rng)
        for teaching_name in me_f.tags.get("river_teaching_seen", set()):
            gained, mastered = river_combat.teaching_progress(doc, teaching_name)
            if gained:
                lines.append(f"【荒天帝真意】{teaching_name}进度 +{gained}（{doc.ext['river_teachings'][teaching_name]}/{river_combat.TIME_RIVER_TEACHING_MAX}）。")
            if mastered:
                lines.append(f"【真意圆满】你已悟得完整功法「{teaching_name}」。")
        won = battle.winner == 0
        battle_results.append(
            f"{doc.name or '道友'}{'击败' if won else '未能击败'}"
            f"苍、鸿、羽三帝（存活：{'、'.join(battle.b_survivors) or '无'}）"
        )
        lines.append(f"与黑暗三帝同时交战（敌方战力 ×{mult:.2f}）：{'；'.join(battle_results)}。")
        if won:
            c = _crystal_gain(rng)
            exp_g = 800_000 * (int(doc.realm_index) + 1)
            gains["crystal"] = c
            gains["exp"] = exp_g
            # 原版每场阶段战结算纪元积累：基础胜 3-5；本战对应 triad 阶段，胜利 ×3。
            era_gained = _grant_era(doc, rng.randint(*ERA_WIN) * TRIAD_ERA_MULT)
            lines.append(f"苍、鸿、羽三帝败退于长河——岁月沉淀 +{c}，修为 +{exp_g:,}，"
                         f"纪元积累 +{era_gained}。")
        else:
            gains["crystal"] = CRYSTAL_LOSE
            losses = int(doc.exp * 0.1)
            gains["exp"] = -losses
            era_gained = _grant_era(doc, rng.randint(*ERA_LOSE))
            lines.append(f"长河反噬，岁月沉淀 +{CRYSTAL_LOSE}，修为 -{losses:,}，"
                         f"纪元积累 +{era_gained}。")
        gains["hp"] = max(0, int(me_f.hp))
    elif roll < 0.70:
        # 悟道：观长河上游岁月（W7-5c：位面青睐 50 点换 +20% 感悟）
        from . import calamity
        exp_g = 600_000 * (int(doc.realm_index) + 1)
        from . import memory as mem_mod
        wudao = mem_mod.effects(doc)["wudao"] if mem_mod.stage_of(doc) > 0 else 0.0
        try:
            from . import suiyun as _sy
            wudao += _sy.wudao_bonus(doc)         # W8-B4：岁云 +20%~45% 悟道收益
        except Exception:
            pass
        if wudao:
            exp_g = int(exp_g * (1 + wudao))     # W8-B5 / B4：两轨悟道加成相加
        try:
            from . import zhengdao as _dz
            dz_mult = _dz.effects(doc)["dao_multiplier"]
            if dz_mult < 1.0:
                exp_g = int(exp_g * dz_mult)     # W8-B6 道伤：悟道 -10%/层（下限 0.5）
        except Exception:
            pass
        exp_g, favor_used = calamity.consume_favor_for_wudao(doc, exp_g)
        gains["exp"] = exp_g
        gains["insight"] = 3
        lines.append(f"你在长河之畔静观一个纪元的兴衰——修为 +{exp_g:,}，功法感悟 +3。")
        if favor_used:
            lines.append(f"【位面青睐】天地垂青，此番感悟 +20%（消耗青睐 {favor_used} 点）。")
    elif roll < 0.88:
        # 拾遗：上游漂来的时光遗物
        stones = 50_000 * (int(doc.realm_index) + 1) * rng.randint(2, 5)
        gains["stones"] = stones
        gains["crystal"] = 1
        lines.append(f"拾得上游漂来的时光遗物——灵石 +{stones:,}，岁月沉淀 +1。")
    else:
        # 荒天帝传道
        taught = int(st.get("teachings", 0) or 0)
        if taught < TEACHING_MAX and (doc.ext.get("gongfa") or []):
            st["teachings"] = taught + 1
            gains["prof"] = TEACHING_PROF
            lines.append(f"【荒天帝传道】剑意横贯万古——参悟功法熟练度 +{TEACHING_PROF}"
                         f"（传道 {taught + 1}/{TEACHING_MAX}，#功法熟练度 查看）。")
        else:
            exp_g = 1_000_000 * (int(doc.realm_index) + 1)
            gains["exp"] = exp_g
            lines.append(f"荒天帝笑而不语：「传道已足，此番予你岁月造化。」修为 +{exp_g:,}。")
        gains["crystal"] = rng.randint(2, 4)

    st["crystal"] = int(st.get("crystal", 0) or 0) + gains["crystal"]
    st["last"] = float(now)
    doc.ext["river"] = st
    if gains.get("exp"):
        doc.exp = max(0, doc.exp + gains["exp"])
    if gains.get("stones"):
        doc.stones = max(0, int(doc.stones) + gains["stones"])
    if gains.get("insight"):
        doc.ext["insight"] = int(doc.ext.get("insight", 0) or 0) + gains["insight"]
    if "hp" in gains:
        doc.ext["hp"] = gains["hp"]
    if gains.get("prof"):
        name = teach_random_prof(doc, rng)
        if name:
            lines.append(f"传道落定：{name}")
    from . import fashan as fashan_mod
    header = (f"【时间长河·终局战报】\n岁月沉淀：{int(st['crystal']):,}"
              f"｜纪元积累 {fashan_mod.era_of(doc)}/{fashan_mod.ERA_CAP}")
    return header + "\n" + "\n".join(lines), gains


def teach_random_prof(doc: PlayerDoc, rng: random.Random) -> str | None:
    """传道：随机已学功法熟练度 +N（若无功法则忽略）。"""
    from . import trib as trib_mod
    learned = [str(x) for x in (doc.ext.get("gongfa") or [])]
    if not learned:
        return None
    name = rng.choice(learned)
    prof = trib_mod.prof_of(doc)
    cur = int(prof.get(name, 0) or 0)
    prof[name] = min(trib_mod.PROF_MAX, cur + TEACHING_PROF)
    doc.ext["prof"] = prof
    return f"{name} +{min(TEACHING_PROF, trib_mod.PROF_MAX - cur)}"


def text(doc: PlayerDoc) -> str:
    from . import fashan as fashan_mod
    st = state_of(doc)
    return "\n".join([
        "--- 时间长河 ---",
        f"岁月沉淀：{int(st.get('crystal', 0) or 0):,}",
        f"荒天帝传道：{int(st.get('teachings', 0) or 0)}/{TEACHING_MAX} 次",
        f"纪元积累：{fashan_mod.era_of(doc)}/{fashan_mod.ERA_CAP}",
        f"门槛：权柄 {GATE_AUTHORITY}/21｜冷却 {ROAM_CD // 60} 分钟",
        "河程遭遇战结算纪元积累（胜 3-5×3、败 1-2）；法身长河每阶段另结。",
        "多人同行与战败献祭续战暂未开放。",
    ])

# 多人同行状态机纯函数；AstrBot handler 负责在数据库事务内读改写世界状态并触发定时结算。
from .river_team import (  # noqa: E402
    accept_sacrifice,
    apply_team_teachings,
    build_team_battle,
    capture_enemy_state,
    complete_stage,
    create_team,
    disband_team,
    expire_rescue,
    finish_team,
    join_team,
    leave_team,
    phase_due,
    record_battle,
    release_expired_rescue,
    sacrifice_recovery,
    start_team,
    stage_roster,
    view_team,
)
