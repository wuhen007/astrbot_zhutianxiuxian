"""时间长河·单人遨游（W3-1，对齐原版 shijianchanghe.js + timeRiverAdversary.js 轻量适配）。

原版语义：
- 门槛：准仙帝权柄（auth 20）组队；每阶段 15 分钟异步落雷式结算；敌人三维 = 玩家 ×1.5~3
  （TIME_RIVER_ATTRIBUTE_RANGE）；胜利奖励岁月沉淀（eraAccumulation：三帝 3-5 / 荒天帝 15 /
  未来准仙帝 45）；荒天帝传道 +2 熟练度（上限 30 次）。
- shortcut：组队/法身遨游/救援窗口/苍帝精气神压制/纪元积蓄消费 全部砍——
  本移植改为**单人同步结算**：每次遨游一段河程（30 分钟 CD），随机事件
  （遇敌三帝法身 → 走 1v1 引擎；悟道；拾遗；荒天帝传道）。
- 奖励落点：修为/灵石/感悟值 + **岁月结晶**（ext["river_crystal"]，后续兑换接口预留）。
- 门槛：双轨取高 ≥45（authority.meets），对齐原版高权柄定位的量级。
"""

from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

ROAM_CD = 30 * 60
GATE_REALM = 45
ATTR_RANGE = (1.5, 3.0)          # 原版 TIME_RIVER_ATTRIBUTE_RANGE
CRYSTAL_TRIAD = (3, 5)           # 三帝胜利岁月沉淀
CRYSTAL_HUANG = 15               # 荒天帝
CRYSTAL_LOSE = 1
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
    if max(int(doc.realm_index), int(doc.physique_index)) < GATE_REALM:
        return (f"时间长河唯有界海以上的修士方可踏足"
                f"（需第 {GATE_REALM + 1} 重，当前 练气 {doc.realm_index}／炼体 {doc.physique_index}）。")
    st = state_of(doc)
    last = float(st.get("last", 0) or 0)
    if now - last < ROAM_CD:
        left = ROAM_CD - (now - last)
        return f"神魂尚在长河余波中震荡，{int(left // 60)} 分 {int(left % 60)} 秒后再来。"
    return None


def _crystal_gain(rng: random.Random) -> int:
    return rng.randint(*CRYSTAL_TRIAD)


def roam(doc: PlayerDoc, stats: Any, build_fighter_fn: Any, run_1v1: Any, rng: random.Random,
         now: float) -> tuple[str, dict]:
    """一段河程。build_fighter_fn(name, mult) -> Fighter（name=="__me__" 返回我方当前血量单位）。

    返回 (文案, 变化 {"crystal": +x, "exp": +x, "stones": +x, "insight": +x, "hp": h})。
    """
    st = state_of(doc)
    roll = rng.random()
    lines: list[str] = []
    gains: dict = {"crystal": 0, "exp": 0, "stones": 0, "insight": 0}

    if roll < 0.45:
        # 遇敌：三帝法身（三维 = 玩家 × 系数）——群战折为连战，赢两场算胜
        mult = rng.uniform(*ATTR_RANGE)
        lines.append(rng.choice(TAUNTS).format(name=doc.name or "道友"))
        lines.append(f"三帝法身自岁月上游逆流而来，三维为你之 {mult:.2f} 倍！")
        me_f = build_fighter_fn("__me__", 1.0)
        wins = 0
        for i, foe_name in enumerate(DARK_TRIAD):
            res = run_1v1(me_f, build_fighter_fn(f"{foe_name}法身", mult), rng)
            if res.winner == 0:
                wins += 1
                lines.append(f"第 {i + 1} 战：击败 {foe_name}法身！")
            else:
                lines.append(f"第 {i + 1} 战：不敌 {foe_name}法身，退入时光褶皱。")
                break
        if wins >= 2:
            c = _crystal_gain(rng)
            exp_g = 800_000 * (int(doc.realm_index) + 1)
            gains["crystal"] = c
            gains["exp"] = exp_g
            lines.append(f"三帝法身溃散于长河——岁月沉淀 +{c}，修为 +{exp_g:,}。")
        else:
            gains["crystal"] = CRYSTAL_LOSE
            losses = int(doc.exp * 0.1)
            gains["exp"] = -losses
            lines.append(f"长河反噬，岁月沉淀 +{CRYSTAL_LOSE}，修为 -{losses:,}。")
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
    header = f"--- 遨游时间长河 ---\n岁月沉淀：{int(st['crystal']):,}"
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
    st = state_of(doc)
    return "\n".join([
        "--- 时间长河 ---",
        f"岁月沉淀：{int(st.get('crystal', 0) or 0):,}",
        f"荒天帝传道：{int(st.get('teachings', 0) or 0)}/{TEACHING_MAX} 次",
        f"门槛：第 {GATE_REALM + 1} 重（双轨取高）｜冷却：30 分钟",
        f"遨游：#遨游时间长河",
        "shortcut：组队/法身遨游/救援窗口/苍帝压制未复刻（重度组队内容）。",
    ])
