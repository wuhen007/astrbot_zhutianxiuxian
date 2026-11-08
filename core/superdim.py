"""超维造物（W8-F3，对齐原版 apps/User/Superdimensional.js + model/shengfaFragment.js）。

原版闭环：炼化「圣法碎片」（480 分钟）→ 得到超维之力 → 超维星界每现实小时产出 0.01 点 →
每次行使权柄消耗 5 点：造物 / 修复位面 / 引发大事件 / 改写时代·命格·天资·灵根。

⚠️ 与原版的一处结构性差异（务必按此口径）：

原版前置是**纳戒里的「圣法碎片」道具**（合成需「圣法残片」×1000，掉率 1/1,000,000）。
本移植的 `data/` 与源仓库 1:1 对齐（`verify_data.py` 校验），**圣法残片没有任何产出点**，
若照搬道具前置，整个超维系统会是死链。故改为等价的高门槛：
**权柄 ≥ 48（不朽真仙）+ 已开辟小世界**即可 `#炼化圣法碎片`，
炼化时长（480 分钟）、奖励（三功法 / 神慧者灵根 / 无演无尽天资 / 超维星界）与产出速率全部照原版。

状态挂 `doc.ext["superdim"]`，db 恒 v17。
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from . import authority, era, linggen, mingge

GATE_LEVEL = 48                  # 原版靠道具，本移植折算为权柄 + 小世界
REFINE_MINUTES = 480             # 原版 SHENGFA_REFINE_MS = 480 分钟
POWER_COST = 5                   # SUPERDIMENSIONAL_POWER_COST
POWER_PER_HOUR = 0.01            # 超维星界每现实小时产出
CREATE_MAX_RARITY = 8            # canCreateWithSuperdimensionalPower: 稀有度 < 8
ERA_NAMES = ("神话时代", "太古时代", "天命时代", "末法时代", "绝灵时代")

SHENGFA_GONGFA = ("星指维宇崩", "击宇碎维", "维宙星灭诀")
SHENHUI_NAME = "神慧者"
SHENHUI_APTITUDE = "无演无尽"
# 原版在代码里直接构造「神慧者」灵根（灵根表无此条），这里照抄同一份数值
SHENHUI_LINGGEN: dict[str, Any] = {
    "id": 7010015, "name": SHENHUI_NAME, "type": SHENHUI_NAME, "eff": 300,
    "法球倍率": 4, "攻击": 5, "防御": 5, "生命": 5, "生命本源": 150,
    "稀有度": 10, "超维之光": True,
}
SUPERDIM_WORLD_NAME = "超维星界"


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）`ext["superdim"]`；直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("superdim")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("owned", False)
    st.setdefault("refining", None)
    st.setdefault("power", 0.0)
    st.setdefault("last", 0.0)
    st.setdefault("awakened_at", 0.0)
    st.setdefault("rewrites", 0)
    st.setdefault("creates", 0)
    ext["superdim"] = st
    return st


def gate_of(doc: Any) -> dict:
    """觉醒前置：权柄 ≥48 且已开辟小世界（原版为持有圣法碎片）。"""
    level = authority.authority_of(doc)
    has_world = bool((doc.ext or {}).get("xiaoshijie"))
    reasons = []
    if level < GATE_LEVEL:
        reasons.append(f"权柄需 {GATE_LEVEL} 档（当前 {level}）")
    if not has_world:
        reasons.append("需先开辟小世界")
    return {"ok": not reasons, "level": level, "world": has_world,
            "reason": "｜".join(reasons)}


def power_of(st: Mapping[str, Any]) -> float:
    return round(max(0.0, float(st.get("power") or 0.0)), 2)


def spend(st: dict, cost: int = POWER_COST) -> bool:
    cur = power_of(st)
    if cur < cost:
        return False
    st["power"] = round(cur - cost, 2)
    return True


def accrue(doc: Any, st: dict, now: float) -> float:
    """超维星界惰性产出（原版只在 15s cron 结算，本移植挂在每个超维入口）。"""
    if not st.get("owned"):
        return 0.0
    last = float(st.get("last") or 0.0) or float(now)
    hours = int(max(0.0, now - last) // 3600)
    if hours <= 0:
        st["last"] = last or float(now)
        return 0.0
    gain = round(hours * POWER_PER_HOUR, 2)
    st["power"] = round(power_of(st) + gain, 2)
    st["last"] = last + hours * 3600
    return gain


# ---------------------------------------------------------------- 觉醒 / 炼化

def begin_refine(doc: Any, st: dict, now: float) -> tuple[bool, str]:
    if st.get("owned"):
        return False, "你已炼化圣法碎片，超维权柄在握。"
    pend = st.get("refining")
    if isinstance(pend, dict):
        left = int(float(pend.get("end") or 0) - now)
        if left > 0:
            return False, f"圣法碎片炼化中，还需 {left // 60} 分钟。"
    gate = gate_of(doc)
    if not gate["ok"]:
        return False, f"超维之力尚未与你共鸣：{gate['reason']}。"
    st["refining"] = {"start": float(now), "end": float(now) + REFINE_MINUTES * 60}
    return True, (f"你以神念包裹圣法碎片，开始炼化超脱至宝。\n"
                  f"需 {REFINE_MINUTES // 60} 小时（真实时间），期间可正常行动；"
                  f"完成后再发「#超维之力」即可结算。")


def settle_refine(doc: Any, st: dict, now: float) -> tuple[bool, str]:
    """惰性结算炼化：到期则授予三功法 / 神慧者灵根 / 无演无尽天资 / 超维星界。"""
    pend = st.get("refining")
    if not isinstance(pend, dict) or float(pend.get("end") or 0) > now:
        return False, ""
    st["refining"] = None
    st["owned"] = True
    st["awakened_at"] = float(now)
    st["last"] = float(now)
    st["power"] = round(power_of(st), 2)

    ext = doc.ext if isinstance(doc.ext, dict) else {}
    learned = [str(g) for g in (ext.get("gongfa") or [])]
    added = [g for g in SHENGFA_GONGFA if g not in learned]
    ext["gongfa"] = learned + added
    ext["linggen"] = dict(SHENHUI_LINGGEN)
    apt = ext.get("daotreasure")
    if not isinstance(apt, dict):
        apt = {}
    apt["aptitude"] = SHENHUI_APTITUDE
    ext["daotreasure"] = apt
    ext["shenhui"] = 1

    world_note = "待开辟小世界后，它会自动升华为【超维星界】。"
    world = ext.get("xiaoshijie")
    if isinstance(world, dict):
        if not world.get("超维星界"):
            old_name = str(world.get("name") or "无名小界")
            world.setdefault("原世界名", old_name)
            world["name"] = SUPERDIM_WORLD_NAME
            world["超维星界"] = True
            world["超维星界上次结算时间"] = float(now)
            world_note = f"小世界【{old_name}】已升华为【{SUPERDIM_WORLD_NAME}】。"
        else:
            world_note = f"小世界【{world.get('name')}】本即超维星界。"
    return True, "\n".join([
        "--- 超脱至宝 · 炼化完成 ---",
        f"你明悟【{SHENGFA_GONGFA[0]}】【{SHENGFA_GONGFA[1]}】【{SHENGFA_GONGFA[2]}】。",
        "大道至理、维度真理与万界音声如群臣朝贡般涌入识海。",
        f"灵根蜕变为【{SHENHUI_NAME}】，天资化作【{SHENHUI_APTITUDE}】。",
        world_note,
        f"超维星界每现实小时产出 {POWER_PER_HOUR} 点超维之力。",
    ])


# ---------------------------------------------------------------- 造物

def can_create(item: Mapping[str, Any] | None) -> bool:
    if not isinstance(item, Mapping):
        return False
    try:
        return int(item.get("稀有度")) < CREATE_MAX_RARITY
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- 改写

def find_linggen(rows: Any, name: str) -> tuple[dict | None, str]:
    """灵根表查名：拒绝唯一灵根 / 不可随机获取（岁云一脉）。"""
    pool = rows if isinstance(rows, list) else []
    hit = next((r for r in pool if isinstance(r, dict) and str(r.get("name") or "") == name), None)
    if not hit:
        return None, f"灵根表里没有【{name}】。"
    if hit.get("唯一灵根") or hit.get("不可随机获取"):
        return None, f"【{name}】属唯一传承（岁云一脉），只能以其自身途径开启。"
    return dict(hit), ""


def same_linggen(doc: Any, name: str) -> bool:
    cur = (doc.ext or {}).get("linggen")
    return isinstance(cur, dict) and str(cur.get("name") or "") == name


def apply_linggen(doc: Any, row: Mapping[str, Any]) -> str:
    """改写灵根：整条快照替换（生命本源走 linggen 的 ×1000 折算）。"""
    doc.ext["linggen"] = dict(row)
    d = linggen.describe(doc.ext["linggen"]) if hasattr(linggen, "describe") else ""
    return f"灵根改写为【{row.get('name')}】" + (f"（{d}）" if d else "") + "。"


def find_fate(rows: Any, name: str) -> dict | None:
    pool = rows if isinstance(rows, list) else []
    hit = next((r for r in pool if isinstance(r, dict)
                and (str(r.get("name") or "") == name or str(r.get("id") or "") == name)), None)
    return dict(hit) if hit else None


def apply_fate(doc: Any, snap: Mapping[str, Any]) -> str:
    row = dict(snap)
    row["大道改写"] = True
    doc.ext["mingge"] = row
    return f"命格改写为【{row.get('name')}】。"


def rewrite_name(arg: str) -> str:
    """从尾部文本取名称（去掉 @ 标记残留与括号说明）。"""
    raw = str(arg or "").strip()
    if not raw:
        return ""
    return raw.split()[0].strip()


# ---------------------------------------------------------------- 时代

def era_apply(state: Any, name: str, now: float) -> tuple[bool, str]:
    """覆写时代锚点：整表切到该时代、当年清零（原版 settings.Era.current.index = index）。"""
    idx = ERA_NAMES.index(name) if name in ERA_NAMES else -1
    if idx < 0:
        return False, "可改写时代：" + " / ".join(ERA_NAMES)
    new_state, _row = era.set_era(state, idx, 0)
    if isinstance(state, dict):
        state.clear()
        state.update(new_state)
    return True, f"超维之光覆写时代锚点，诸天进入【{name}】，时代年内计数归零。"


# ---------------------------------------------------------------- 文案

def panel_text(doc: Any, st: Mapping[str, Any], now: float) -> str:
    gate = gate_of(doc)
    if not st.get("owned"):
        pend = st.get("refining")
        lines = ["--- 超维之力 ---", "尚未炼化圣法碎片，超维权柄沉睡。"]
        if isinstance(pend, dict):
            left = max(0, int(float(pend.get("end") or 0) - now))
            lines.append(f"炼化中：还需 {left // 3600} 小时 {left % 3600 // 60} 分。")
        else:
            lines.append("觉醒前置：" + (gate["reason"] or "已满足"))
            lines.append("满足后发送「#炼化圣法碎片」，炼化需 "
                         f"{REFINE_MINUTES // 60} 小时真实时间。")
        return "\n".join(lines)
    power = power_of(st)
    world = (doc.ext or {}).get("xiaoshijie")
    online = isinstance(world, dict) and world.get("超维星界")
    lines = [
        "--- 超维之力 ---",
        f"当前：{power:,.2f} 点｜每次行使权柄消耗 {POWER_COST} 点",
        f"产出：超维星界每现实小时 +{POWER_PER_HOUR} 点"
        + ("" if online else "（小世界尚未升华，产出为 0）"),
        f"累计：造物 {int(st.get('creates') or 0)} 次｜改写 {int(st.get('rewrites') or 0)} 次",
        "— 权柄 —",
        "「#超维造物 物品名」造一件稀有度 <8 的物品",
        "「#超维修复位面」弥合诸天裂隙，修复全部破碎位面",
        "「#超维引发大事件」强行推演一场域外灾劫",
        "「#超维改写时代 时代名」神话 / 太古 / 天命 / 末法 / 绝灵",
        "「#超维改写命格 命格名 [@道友]」「#超维改写天资 天资名 [@道友]」"
        "「#超维改写灵根 灵根名 [@道友]」",
    ]
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 超维造物 · 规则 ---",
        f"· 觉醒：权柄 ≥{GATE_LEVEL} 档 + 已开辟小世界 → 「#炼化圣法碎片」（{REFINE_MINUTES // 60} 小时真实时间）。",
        f"· 原版前置是纳戒「圣法碎片」道具（合成需圣法残片×1000，掉率百万分之一）；"
        f"本移植 data 与源仓库 1:1 对齐、圣法残片无产出点，故折算为权柄 + 小世界门槛。",
        f"· 超维之力：超维星界每现实小时 +{POWER_PER_HOUR} 点，惰性结算（每个超维指令入口）。",
        f"· 每次权柄消耗 {POWER_COST} 点；不足时一律拒绝且不扣任何资源。",
        f"· 造物：只能造「确实存在且稀有度 <{CREATE_MAX_RARITY}」的物品，每次一件。",
        "· 修复位面：清全服 `destroyed_planes` 与每个玩家档内的位面毁灭记录。",
        "· 引发大事件：直接调用灾厄生成（等同 «#召唤域外灾厄 1»，不受存世上限以外的限制）。",
        "· 改写：可 @他人；命格按词条快照整条替换，天资走大道至宝同一张十级表（三维乘区同源），"
        "灵根拒绝唯一/不可随机获取（岁云一脉）。",
        "· 改写灵根不校验化身装载（本移植 `#装载化身` 无独立本源档）。",
    ])


def help_text() -> str:
    return "\n".join([
        "--- 超维造物 · 指令 ---",
        "「#超维之力」面板（力量 / 产出 / 消耗 / 入口；未觉醒则显示前置）",
        "「#炼化圣法碎片」觉醒入口（权柄 48 档 + 小世界）",
        "「#超维造物 物品名」造物（稀有度 <8）",
        "「#超维修复位面」修复全部破碎位面",
        "「#超维引发大事件」强行推演一场域外灾劫",
        f"「#超维改写时代 时代名」{' / '.join(ERA_NAMES)}",
        "「#超维改写命格 命格名 [@道友]」",
        "「#超维改写天资 天资名 [@道友]」",
        "「#超维改写灵根 灵根名 [@道友]」",
    ])
