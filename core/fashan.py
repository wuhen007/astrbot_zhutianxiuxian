"""独立法身系统（最小可用子集，对齐原版 model/fashanProxy.js + apps/SecretPlace/SecretPlaceplus.js）。

shortcut: 原版完整版牵涉 10+ 文件（时间长河/界海/永恒未知之地/圣墟分支、双 actor
快照合并、镇守巡查、位面毁灭、权柄换算），本移植只做闭环：
凝聚 → 穿梭 → 探索/沉迷 → 收获，独立 ext["fashan"] 状态，不占用真身 doc.state。
保留的硬规则：法身位置必须等于副本地点所在位面。
"""
from __future__ import annotations

import random
import time
from typing import Any, Mapping

from . import plane

GATE_AUTHORITY = 45          # 原版准仙帝权柄；本移植与时间长河同门槛（双轨取高）
CREATE_EXP = 10_000_000      # 替代原版「纪元积累 10」（本移植无纪元积累系统）
CREATE_XUEQI = 10_000_000
INITIAL_PLANE = "仙界"       # 原版初凝绑定仙界
TRAVEL_EXP = 800_000         # 每次穿梭按位面等级差
TRAVEL_XUEQI = 1_200_000
MAX_COUNT = 12               # 沉迷次数上限（原版 1-12）
MINUTES_PER_COUNT = 3
ROUNDS_PER_COUNT = 3
HP_COST_PER_ROUND = 0.02     # 每层消耗法身最大血量的比例


def state_of(doc: Any) -> dict:
    """取（并按需初始化）ext["fashan"]；直接改 doc，调用方负责保存。"""
    st = doc.ext.get("fashan")
    if not isinstance(st, dict):
        st = {"owned": False, "plane": "", "state": "空闲", "hp": 0, "hp_max": 0,
              "action": None, "created_at": 0.0}
        doc.ext["fashan"] = st
    return st


def authority_of(doc: Any) -> int:
    return max(int(getattr(doc, "realm_index", 0) or 0),
               int(getattr(doc, "physique_index", 0) or 0))


def create(doc: Any, now: float) -> tuple[bool, str]:
    """#凝聚无上法身：准仙帝级 + 修为/血气消耗。"""
    st = state_of(doc)
    if st["owned"]:
        return False, "你已凝聚无上法身（#法身状态 查看）。"
    if authority_of(doc) < GATE_AUTHORITY:
        return False, f"需准仙帝权柄（双轨境界 ≥{GATE_AUTHORITY}），当前 {authority_of(doc)}。"
    # 原版：扣 10 纪元积累；本移植 W6-2 起纪元积累由时间长河/镇守产出，不足时回退资源消耗
    if era_of(doc) >= 10:
        doc.ext["era_points"] = era_of(doc) - 10
        cost = "纪元积累 ×10"
    else:
        if int(doc.exp) < CREATE_EXP or int(doc.ext.get("xueqi", 0) or 0) < CREATE_XUEQI:
            return False, (f"凝聚需纪元积累 10 点，或修为 {CREATE_EXP:,} + 血气 {CREATE_XUEQI:,}"
                           f"（当前纪元 {era_of(doc)}、修为 {int(doc.exp):,}、"
                           f"血气 {int(doc.ext.get('xueqi', 0) or 0):,}）。")
        doc.exp -= CREATE_EXP
        doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - CREATE_XUEQI
        cost = f"修为 {CREATE_EXP:,}、血气 {CREATE_XUEQI:,}"
    st.update({"owned": True, "plane": INITIAL_PLANE, "state": "空闲",
               "hp_max": 1_000_000, "hp": 1_000_000, "action": None,
               "created_at": float(now)})
    return True, (f"无上法身凝聚成功！初始驻于【{INITIAL_PLANE}】。\n"
                  f"消耗 {cost}；法身独立行动，不占真身状态。")


def travel(doc: Any, target: str, now: float) -> tuple[bool, str]:
    """#法身穿梭 位面：校验门槛，扣资源，立即抵达（不占真身 state）。"""
    st = state_of(doc)
    if not st["owned"]:
        return False, "尚未凝聚法身，请发送 #凝聚无上法身。"
    if st["state"] == "行动中":
        return False, "法身正在行动中，请先 #法身沉迷收获 结算。"
    target = (target or "").strip()
    if target not in plane.GATES:
        return False, f"未知位面「{target}」。可选：{'、'.join(plane.PLANES)}"
    if plane.GATES[target] > authority_of(doc):
        return False, f"【{target}】需双轨境界 ≥{plane.GATES[target]}，当前 {authority_of(doc)}。"
    if target == st["plane"]:
        return False, f"法身已驻【{target}】。"
    diff = abs(float(plane.LEVELS.get(target, 0)) - float(plane.LEVELS.get(st["plane"], 0)))
    need_exp = int(TRAVEL_EXP * max(1.0, diff))
    need_xq = int(TRAVEL_XUEQI * max(1.0, diff))
    if int(doc.exp) < need_exp or int(doc.ext.get("xueqi", 0) or 0) < need_xq:
        return False, f"穿梭需修为 {need_exp:,}、血气 {need_xq:,}，资源不足。"
    doc.exp -= need_exp
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - need_xq
    st["plane"] = target
    return True, f"法身已抵达【{target}】（耗修为 {need_exp:,}、血气 {need_xq:,}）。"


def begin(doc: Any, plane_name: str, count: int, now: float) -> tuple[bool, str]:
    """#法身探索 / #法身沉迷：法身位置必须等于目标位面。"""
    st = state_of(doc)
    if not st["owned"]:
        return False, "尚未凝聚法身，请发送 #凝聚无上法身。"
    if st["state"] == "行动中":
        return False, "法身正在行动中，请先 #法身沉迷收获 结算。"
    plane_name = (plane_name or "").strip()
    if plane_name not in plane.GATES:
        return False, f"未知位面「{plane_name}」。可选：{'、'.join(plane.PLANES)}"
    if plane_name != st["plane"]:
        return False, f"法身当前在【{st['plane']}】，需先 #法身穿梭 {plane_name}。"
    if int(st["hp"]) <= 0:
        return False, "法身血量耗尽，先 #法身疗伤。"
    count = max(1, min(MAX_COUNT, int(count or 1)))
    rounds = count * ROUNDS_PER_COUNT
    st["action"] = {"kind": "沉迷" if count > 1 else "探索", "plane": plane_name,
                    "count": count, "rounds": rounds, "start": float(now),
                    "end": float(now) + count * MINUTES_PER_COUNT * 60}
    st["state"] = "行动中"
    kind = st["action"]["kind"]
    return True, (f"法身开始【{kind} {plane_name}】×{count}（共 {rounds} 层，"
                  f"{count * MINUTES_PER_COUNT} 分钟）。到期发 #法身沉迷收获 结算；"
                  f"真身仍可自由行动。")


def remaining(st: Mapping, now: float) -> float:
    act = st.get("action") or {}
    return max(0.0, float(act.get("end", 0) or 0) - float(now))


def settle(doc: Any, now: float, rng: random.Random) -> tuple[bool, str]:
    """#法身沉迷收获：到点一次性模拟，收益写回真身，法身独立扣血。"""
    st = state_of(doc)
    act = st.get("action")
    if not st["owned"] or st["state"] != "行动中" or not act:
        return False, "法身当前没有待结算的行动。"
    left = remaining(st, now)
    if left > 0:
        return False, f"尚需 {int(left // 60)} 分 {int(left % 60)} 秒，未到结算时辰。"
    if act.get("kind") in ("时间长河", "界海", "圣墟"):
        return _settle_special(doc, st, act, rng)
    factor = 1.0 + float(plane.LEVELS.get(act["plane"], 0)) * 0.5
    realm = authority_of(doc) + 1
    rounds = int(act["rounds"])
    # 原版 SecretPlaceplusTask.js:1841 收益式：2000 + 100×境²×系数×0.1/5
    exp = int((2000 + 100 * realm * realm * factor / 50) * rounds)
    xueqi = int((2000 + 100 * realm * realm * factor / 10) * rounds)
    stones = int(2000 * factor * rounds)
    hp_cost = int(int(st["hp_max"]) * HP_COST_PER_ROUND * rounds)
    died = hp_cost >= int(st["hp"])
    if died:
        exp, xueqi, stones = exp // 2, xueqi // 2, stones // 2
        st["hp"] = 0
    else:
        st["hp"] = int(st["hp"]) - hp_cost
    doc.exp += exp
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + xueqi
    doc.stones += stones
    st["state"] = "空闲"
    st["action"] = None
    lines = [f"--- 法身{act['kind']}收获（{act['plane']} ×{act['count']}）---",
             f"修为 +{exp:,}｜血气 +{xueqi:,}｜灵石 +{stones:,}",
             f"法身血量 {int(st['hp']):,}/{int(st['hp_max']):,}（-{hp_cost:,}）"]
    if died:
        lines.append("法身力竭溃散，收益减半（#法身疗伤 恢复）。")
    return True, "\n".join(lines)


def heal(doc: Any) -> tuple[bool, str]:
    """#法身疗伤：花灵石回满独立血量（不占真身行动）。"""
    st = state_of(doc)
    if not st["owned"]:
        return False, "尚未凝聚法身。"
    if int(st["hp"]) >= int(st["hp_max"]):
        return False, "法身血量已满。"
    cost = max(1000, int(st["hp_max"]) // 100)
    if int(doc.stones) < cost:
        return False, f"疗伤需 {cost:,} 灵石。"
    doc.stones -= cost
    st["hp"] = int(st["hp_max"])
    return True, f"法身血量回满，花费 {cost:,} 灵石。"


def status_text(doc: Any, now: float) -> str:
    st = state_of(doc)
    if not st["owned"]:
        return (f"--- 无上法身 ---\n尚未凝聚。\n"
                f"条件：双轨境界 ≥{GATE_AUTHORITY}、修为 {CREATE_EXP:,}、血气 {CREATE_XUEQI:,}\n"
                f"指令：#凝聚无上法身")
    lines = ["--- 无上法身 ---",
             f"驻位面：{st['plane']}｜状态：{st['state']}",
             f"独立血量：{int(st['hp']):,}/{int(st['hp_max']):,}（与真身分离）",
             f"纪元积累：{era_of(doc)}/{ERA_CAP}"]
    act = st.get("action")
    if act:
        left = remaining(st, now)
        lines.append(f"行动：{act['kind']} {act['plane']} ×{act['count']}（{act['rounds']} 层）"
                     f"｜剩余 {int(left // 60)} 分 {int(left % 60)} 秒")
    guard_tick(doc, now)
    g = doc.ext.get("guard")
    if g and not g.get("ended"):
        lines.append(f"永恒镇守：进行中（{g.get('actor')}）｜累计纪元 +{int(g.get('total', 0))}")
    lines.append("指令：#法身穿梭 位面｜#法身探索 位面｜#法身沉迷 位面*次数｜#法身沉迷收获｜#法身疗伤")
    lines.append("分支：#法身遨游时间长河｜#法身探索界海 地点｜#法身探索圣墟 位面｜#法身镇守永恒未知之地")
    return "\n".join(lines)


# ---------------------------------------------------------------- W6-2 四分支

ERA_CAP = 1000                # 原版 ERA_ACCUMULATION_CAPS 五档，本移植取单一上限
CREATE_ERA_COST = 10
GUARD_GATE = 50               # 原版权柄 21（仙帝）
GUARD_ERA_PER_HOUR = 10       # 原版 ETERNAL_GUARD_ERA_REWARD
RIVER_GATE = GATE_AUTHORITY   # 原版权柄 20（准仙帝）
RIVER_MINUTES = 15
JIEHAI_MINUTES = 30
JIEHAI_PRICE_SCALE = 0.001    # 原版 Price 1.5e8 / 1e7，按数值缩放对照表 ÷1000
JIEHAI_SITES = {
    "接引古殿": {"price": 150_000_000, "gate": 45, "best": "柳神法"},
    "终极古地": {"price": 10_000_000, "gate": 50, "best": "大罗仙剑"},
}
SHENGXU_SITES = {            # 原版圣墟三级；本移植无花粉体系，改按位面门槛
    "小阴间": {"gate": 36, "price": 2_000_000},
    "大阴间": {"gate": 39, "price": 5_000_000},
    "阳间": {"gate": 49, "price": 10_000_000},
}


def era_of(doc: Any) -> int:
    return int(doc.ext.get("era_points", 0) or 0)


def add_era(doc: Any, amount: int) -> int:
    """纪元积累封顶写入，返回实际增加量。"""
    old = era_of(doc)
    new = min(ERA_CAP, old + max(0, int(amount)))
    doc.ext["era_points"] = new
    return new - old


def _ready(st: Mapping, doc: Any, gate: int) -> str | None:
    if not st["owned"]:
        return "尚未凝聚法身，请发送 #凝聚无上法身。"
    if st["state"] == "行动中":
        return "法身正在行动中，请先 #法身沉迷收获 结算。"
    if authority_of(doc) < gate:
        return f"需双轨境界 ≥{gate}，当前 {authority_of(doc)}。"
    if int(st["hp"]) <= 0:
        return "法身血量耗尽，先 #法身疗伤。"
    return None


def begin_river(doc: Any, now: float) -> tuple[bool, str]:
    """#法身遨游时间长河：单次 15 分钟，独立血量，不占真身行动。

    shortcut: 原版帝战多阶段/技能库、组队、待援、图片战报未移植，结算用随机胜负。
    """
    st = state_of(doc)
    err = _ready(st, doc, RIVER_GATE)
    if err:
        return False, err
    st["action"] = {"kind": "时间长河", "plane": "时间长河", "count": 1, "rounds": 1,
                    "start": float(now), "end": float(now) + RIVER_MINUTES * 60}
    st["state"] = "行动中"
    return True, f"法身独入时间长河（{RIVER_MINUTES} 分钟），真身仍可自由行动。到期 #法身沉迷收获。"


def begin_jiehai(doc: Any, site: str, now: float) -> tuple[bool, str]:
    """#法身探索界海 接引古殿/终极古地：只单次，不开放沉迷。"""
    st = state_of(doc)
    info = JIEHAI_SITES.get((site or "").strip())
    if not info:
        return False, f"界海地点仅：{'、'.join(JIEHAI_SITES)}（且只开放单次探索）"
    if st["plane"] != "界海":
        return False, "法身需先 #法身穿梭 界海。"
    err = _ready(st, doc, info["gate"])
    if err:
        return False, err
    cost = int(info["price"] * JIEHAI_PRICE_SCALE)
    if int(doc.stones) < cost:
        return False, f"【{site}】需灵石 {cost:,}，当前 {int(doc.stones):,}。"
    doc.stones -= cost
    st["action"] = {"kind": "界海", "plane": "界海", "place": site, "count": 1,
                    "rounds": 1, "cost": cost, "start": float(now),
                    "end": float(now) + JIEHAI_MINUTES * 60}
    st["state"] = "行动中"
    return True, f"法身入界海【{site}】（{JIEHAI_MINUTES} 分钟，灵石 -{cost:,}）。到期 #法身沉迷收获。"


def begin_shengxu(doc: Any, site: str, count: int, now: float) -> tuple[bool, str]:
    """#法身探索/沉迷圣墟 位面*次数：位面匹配、1-12 次。

    shortcut: 原版花粉进化路门槛、呼吸法提速、祖种/石罐机缘未移植。
    """
    st = state_of(doc)
    site = (site or "").strip()
    info = SHENGXU_SITES.get(site)
    if not info:
        return False, f"圣墟位面仅：{'、'.join(SHENGXU_SITES)}"
    if st["plane"] != site:
        return False, f"法身当前在【{st['plane']}】，需先 #法身穿梭 {site}。"
    err = _ready(st, doc, info["gate"])
    if err:
        return False, err
    count = max(1, min(MAX_COUNT, int(count or 1)))
    cost = int(info["price"] * count)
    if int(doc.stones) < cost:
        return False, f"需灵石 {cost:,}，当前 {int(doc.stones):,}。"
    doc.stones -= cost
    st["action"] = {"kind": "圣墟", "plane": site, "count": count, "rounds": count * 10,
                    "cost": cost, "start": float(now),
                    "end": float(now) + count * MINUTES_PER_COUNT * 60}
    st["state"] = "行动中"
    return True, (f"法身入圣墟【{site}】×{count}（{count * MINUTES_PER_COUNT} 分钟，"
                  f"灵石 -{cost:,}）。到期 #法身沉迷收获。")


def _settle_special(doc: Any, st: dict, act: dict, rng: random.Random) -> tuple[bool, str]:
    """时间长河 / 界海 / 圣墟 结算（共用 #法身沉迷收获）。"""
    kind = act["kind"]
    realm = authority_of(doc) + 1
    lines = [f"--- 法身{kind}结算 ---"]
    if kind == "时间长河":
        win = rng.random() < 0.6
        era = add_era(doc, rng.randint(3, 5) if win else 1)
        hp_cost = int(int(st["hp_max"]) * (0.05 if win else 0.15))
        st["hp"] = max(0, int(st["hp"]) - hp_cost)
        lines.append(f"帝战{'得胜' if win else '败退'}｜纪元积累 +{era}（现 {era_of(doc)}/{ERA_CAP}）")
        lines.append(f"法身血量 -{hp_cost:,}（现 {int(st['hp']):,}）；败退不送真身待援")
    elif kind == "界海":
        exp = 500_000 * realm
        doc.exp += exp
        doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + exp
        st["hp"] = max(0, int(st["hp"]) - int(int(st["hp_max"]) * 0.08))
        best = JIEHAI_SITES.get(act.get("place", ""), {}).get("best", "")
        lines.append(f"修为 +{exp:,}｜血气 +{exp:,}｜法身血量 {int(st['hp']):,}")
        lines.append(f"原版极品掉落【{best}】：本移植折算为修为/血气，未发道具")
    else:  # 圣墟
        exp = int(300_000 * realm * int(act["count"]))
        stones = int(200_000 * realm * int(act["count"]))
        doc.exp += exp
        doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + exp
        doc.stones += stones
        st["hp"] = max(0, int(st["hp"]) - int(int(st["hp_max"]) * 0.05 * int(act["count"])))
        lines.append(f"修为 +{exp:,}｜血气 +{exp:,}｜灵石 +{stones:,}")
        lines.append("原版进化花粉/异果/呼吸法：本移植折算为资源，未发道具")
    st["state"] = "空闲"
    st["action"] = None
    return True, "\n".join(lines)


def guard_tick(doc: Any, now: float) -> int:
    """镇守懒结算：每满 1 小时补发 10 纪元（无 cron，发指令时补算）。"""
    g = doc.ext.get("guard")
    if not isinstance(g, dict) or g.get("ended"):
        return 0
    last = float(g.get("last", now) or now)
    hours = int((float(now) - last) // 3600)
    if hours <= 0:
        return 0
    g["last"] = last + hours * 3600
    gained = add_era(doc, hours * GUARD_ERA_PER_HOUR)
    g["total"] = int(g.get("total", 0) or 0) + gained
    return gained


def start_guard(doc: Any, now: float, actor: str = "fashan") -> tuple[bool, str]:
    """#法身镇守 / #镇守永恒未知之地：双 actor 归一，只记一份。"""
    guard_tick(doc, now)
    g = doc.ext.get("guard")
    if isinstance(g, dict) and not g.get("ended"):
        return False, "已在镇守中（双身不重复领取，#永恒镇守状态 查看）。"
    if authority_of(doc) < GUARD_GATE:
        return False, f"镇守需仙帝权柄（双轨境界 ≥{GUARD_GATE}），当前 {authority_of(doc)}。"
    if actor == "fashan":
        st = state_of(doc)
        if not st["owned"]:
            return False, "尚未凝聚法身。"
        if st["state"] == "行动中":
            return False, "法身正在行动中，先结算再镇守。"
    doc.ext["guard"] = {"actor": actor, "start": float(now), "last": float(now),
                        "ended": False, "total": 0}
    return True, f"开始镇守永恒未知之地（{actor}），每满 1 小时 +{GUARD_ERA_PER_HOUR} 纪元积累（上限 {ERA_CAP}）。"


def stop_guard(doc: Any, now: float) -> tuple[bool, str]:
    gained = guard_tick(doc, now)
    g = doc.ext.get("guard")
    if not isinstance(g, dict) or g.get("ended"):
        return False, "当前没有进行中的镇守。"
    g["ended"] = True       # 原版：结束后暂停自动接管，须手动重发
    return True, (f"结束镇守，本次补发纪元 +{gained}（累计 +{int(g.get('total', 0))}）。"
                  f"结束后不再自动接管，需重新发送镇守指令。")


def guard_text(doc: Any, now: float) -> str:
    guard_tick(doc, now)
    g = doc.ext.get("guard")
    if not isinstance(g, dict) or g.get("ended"):
        return f"--- 永恒镇守 ---\n当前未镇守｜纪元积累 {era_of(doc)}/{ERA_CAP}"
    return (f"--- 永恒镇守 ---\n状态：进行中（{g.get('actor')}）"
            f"｜累计纪元 +{int(g.get('total', 0))}｜纪元积累 {era_of(doc)}/{ERA_CAP}\n"
            f"每小时 +{GUARD_ERA_PER_HOUR}，上限 {ERA_CAP}；#结束法身镇守永恒未知之地 可结束")
