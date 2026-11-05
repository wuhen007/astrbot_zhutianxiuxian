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
    if int(doc.exp) < CREATE_EXP or int(doc.ext.get("xueqi", 0) or 0) < CREATE_XUEQI:
        return False, (f"凝聚需修为 {CREATE_EXP:,}、血气 {CREATE_XUEQI:,}"
                       f"（当前 {int(doc.exp):,} / {int(doc.ext.get('xueqi', 0) or 0):,}）。")
    doc.exp -= CREATE_EXP
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - CREATE_XUEQI
    st.update({"owned": True, "plane": INITIAL_PLANE, "state": "空闲",
               "hp_max": 1_000_000, "hp": 1_000_000, "action": None,
               "created_at": float(now)})
    return True, (f"无上法身凝聚成功！初始驻于【{INITIAL_PLANE}】。\n"
                  f"消耗修为 {CREATE_EXP:,}、血气 {CREATE_XUEQI:,}；法身独立行动，不占真身状态。")


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
             f"独立血量：{int(st['hp']):,}/{int(st['hp_max']):,}（与真身分离）"]
    act = st.get("action")
    if act:
        left = remaining(st, now)
        lines.append(f"行动：{act['kind']} {act['plane']} ×{act['count']}（{act['rounds']} 层）"
                     f"｜剩余 {int(left // 60)} 分 {int(left % 60)} 秒")
    lines.append("指令：#法身穿梭 位面｜#法身探索 位面｜#法身沉迷 位面*次数｜#法身沉迷收获｜#法身疗伤")
    return "\n".join(lines)
