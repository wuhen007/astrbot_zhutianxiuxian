"""独立法身状态与单人行动（对齐原版 model/fashanProxy.js / ShengxuContent.js）。

时间长河/界海法身均提供原版单人结算 helper，仍需主入口传入战斗与数据回调；完整时间长河多阶段、镇守懒结算仍有差异。法身圣墟复用共享战斗与奖励规则；按范围不含法身同行。
"""
from __future__ import annotations

import copy
import random
import secrets
import time
from typing import Any, Mapping, Sequence

from . import plane, shengxu as shengxu_mod
from .clock import day_key

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
    if plane.is_high_dim(target):
        # 原版高维位面走维度壁垒（破界强度/仙帝通行），不走双轨境界门槛（plane.py barrier_check）。
        ok, why = plane.barrier_check(doc, st["plane"], target)
        if not ok:
            return False, why
    elif plane.GATES[target] > authority_of(doc):
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


def begin_shangcang(doc: Any, row: Mapping, count: int, now: float) -> tuple[bool, str]:
    """#法身探索/沉迷上苍之上（原版 startFashanShangcang）：法身须在上苍之上，消耗走 shangcang 口径。"""
    from . import shangcang as sc_mod
    st = state_of(doc)
    if not st["owned"]:
        return False, "尚未凝聚法身，请发送 #凝聚无上法身。"
    if st["state"] == "行动中":
        return False, "法身正在行动中，请先 #法身沉迷收获 结算。"
    if st["plane"] != "上苍之上":
        return False, "法身当前不在上苍之上，先 #法身穿梭 上苍之上。"
    if int(st["hp"]) <= 0:
        return False, "法身血量耗尽，先 #法身疗伤。"
    if authority_of(doc) < sc_mod.GATE_AUTHORITY:
        return False, (f"【{row.get('name')}】需仙帝权柄（{sc_mod.GATE_AUTHORITY} 档），"
                       f"当前 {authority_of(doc)} 档。")
    count = max(1, min(MAX_COUNT, int(count or 1)))
    unit = sc_mod.cost_of(row)
    total = {k: v * count for k, v in unit.items()}
    lack = sc_mod.shortages(doc, total)
    if lack:
        return False, "资源不足：" + "；".join(lack)
    sc_mod.pay(doc, total)
    minutes, notes = sc_mod.duration_minutes(doc)
    st["action"] = {"kind": "上苍之上", "plane": "上苍之上",
                    "place": str(row.get("name")), "count": count, "rounds": count,
                    "row": dict(row), "start": float(now),
                    "end": float(now) + minutes * count * 60}
    st["state"] = "行动中"
    tail = f"（{'｜'.join(notes)}）" if notes else ""
    return True, (f"法身降临上苍之上【{row.get('name')}】×{count}，"
                  f"消耗 {sc_mod.cost_text(total)}，预计 {minutes * count} 分钟{tail}，"
                  f"到期发 #法身沉迷收获 结算；真身仍可自由行动。")


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


def spend_era(doc: Any, amount: int) -> int:
    """扣除纪元积累，最多扣到 0（原版突破处无门槛会扣成负数，按移植口径封底）。"""
    take = min(max(0, int(amount)), era_of(doc))
    doc.ext["era_points"] = era_of(doc) - take
    return take


ERA_CONVERT_BASE = 100_000_000   # 原版 zhengdaotixi.jiyuanjilei baseReward


def convert_era(doc: Any, count: int) -> tuple[bool, str]:
    """#消耗/转化纪元积累（原版 zhengdaotixi.js jiyuanjilei）：

    N 点纪元积累 → 修为与血气各 +1e8 × max(1,权柄) × 练气境界 × 炼体境界。
    """
    from .extra_cultivation import realm_authority_level
    count = max(1, int(count or 1))
    if era_of(doc) < count:
        return False, f"你的纪元积累不足！当前剩余：{era_of(doc)}，需要消耗：{count}"
    authority = max(1, int(realm_authority_level(doc)))
    realm = max(1, int(getattr(doc, "realm_index", 0) or 0) + 1)
    body = max(1, int(getattr(doc, "physique_index", 0) or 0) + 1)
    reward = int(ERA_CONVERT_BASE * authority * realm * body * count)
    doc.exp = int(getattr(doc, "exp", 0) or 0) + reward
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + reward
    doc.ext["era_points"] = era_of(doc) - count
    efficiency = authority * realm * body * 100
    return True, (f"【纪元积累转化】\n消耗 {count} 个纪元积累，获得：\n"
                  f"修为：+{reward:,}\n血气：+{reward:,}\n"
                  f"当前纪元积累剩余：{era_of(doc)}\n"
                  f"（转化效率：{efficiency}%）")


def condense_breakthrough(doc: Any, now: float) -> tuple[bool, str]:
    """路尽级仙帝突破自带法身凝聚（原版 Level.js:1389）：已凝聚则不重复发，不另扣凝聚资源。"""
    st = state_of(doc)
    if st["owned"]:
        return False, ""
    st.update({"owned": True, "plane": INITIAL_PLANE, "state": "空闲",
               "hp_max": 1_000_000, "hp": 1_000_000, "action": None,
               "created_at": float(now)})
    return True, ("【法身凝聚】你盘坐永恒未知之地，万古不动，"
                  "一缕神念自天灵冲出，化作与真身无异的法身！")


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
    """#法身遨游时间长河：锁定准仙帝法身，15 分钟后进入独立帝战结算。"""
    st = state_of(doc)
    err = _ready(st, doc, RIVER_GATE)
    if err:
        return False, err
    if st.get("plane") != plane.TIME_RIVER_PLANE:
        return False, "请先使用 #法身穿梭 时间长河，让法身抵达时间长河。"
    st["action"] = {"kind": "时间长河", "plane": plane.TIME_RIVER_PLANE,
                    "settlement_id": f"fashan-river:{getattr(doc, 'uid', '')}:{secrets.token_hex(8)}",
                    "count": 1, "rounds": 1, "start": float(now),
                    "end": float(now) + RIVER_MINUTES * 60,
                    "actor_snapshot": doc.model_dump(),
                    "actor_baseline": doc.model_dump()}
    st["state"] = "行动中"
    return True, (f"【法身遨游时间长河】法身已逆流而上，首段探索 {RIVER_MINUTES} 分钟后结算；"
                  "真身保持原有行动。胜出时可能进入后续帝战阶段。")


def begin_jiehai(doc: Any, site: str, now: float, *,
                 place_definition: Mapping[str, Any] | None = None) -> tuple[bool, str]:
    """#法身探索界海：原版仅单次，传入副本地点静态档案供奖励/敌手结算。"""
    st = state_of(doc)
    place_definition = place_definition if isinstance(place_definition, Mapping) else None
    info = JIEHAI_SITES.get((site or "").strip())
    if place_definition is not None:
        if str(place_definition.get("Grade") or "") != "界海":
            return False, "所选副本并非原版界海地点。"
        info = {"price": max(0, int(place_definition.get("Price", 0) or 0)),
                "gate": 50 if (site or "").strip() == "终极古地" else 45,
                "best": str((place_definition.get("Best") or [""])[0]).strip("[]")}
    if not info:
        return False, f"界海地点仅：{'、'.join(JIEHAI_SITES)}（且只开放单次探索）"
    err = _ready(st, doc, int(info["gate"]))
    if err:
        return False, err
    if st["plane"] != "界海":
        return False, "法身需先 #法身穿梭 界海。"
    if place_definition is None:
        return False, "界海副本静态档案尚未接入，未扣除灵石；请稍后再试。"
    price = max(0, int(place_definition.get("Price", info["price"]) or 0))
    cost = int(price * JIEHAI_PRICE_SCALE)
    if int(doc.stones) < cost:
        return False, f"【{site}】需灵石 {cost:,}，当前 {int(doc.stones):,}。"
    doc.stones -= cost
    definition = dict(place_definition) if isinstance(place_definition, Mapping) else None
    st["action"] = {"kind": "界海", "plane": "界海", "place": site, "count": 1,
                    "settlement_id": f"fashan-jiehai:{getattr(doc, 'uid', '')}:{secrets.token_hex(8)}",
                    "rounds": 1, "cost": cost, "start": float(now),
                    "end": float(now) + JIEHAI_MINUTES * 60,
                    "place_definition": definition,
                    "actor_snapshot": doc.model_dump(),
                    "actor_baseline": doc.model_dump()}
    st["state"] = "行动中"
    return True, f"法身入界海【{site}】（{JIEHAI_MINUTES} 分钟，灵石 -{cost:,}）。到期 #法身沉迷收获。"


def begin_shengxu(doc: Any, dungeon_name: str, count: int, now: float, *,
                  addiction: bool | None = None) -> tuple[bool, str]:
    """Start an original-style Fashan Shengxu round using the named dungeon.

    `count` is the user's 1–12 batch count for the addiction command; each batch
    settles ten individual dungeon rounds. Single exploration is one round.
    The caller must pass `addiction=True` for the addiction command, including ×1.
    """
    st = state_of(doc)
    if not st["owned"]:
        return False, "尚未凝聚法身，请发送 #凝聚无上法身。"
    if st["state"] == "行动中":
        return False, "法身正在行动中，请先 #法身沉迷收获 结算。"
    dungeon = shengxu_mod.dungeon_of(dungeon_name)
    if not dungeon:
        return False, "未知圣墟副本。可用：" + "、".join(d["name"] for d in shengxu_mod.DUNGEONS)
    if addiction is None:
        addiction = int(count or 1) > 1
    batches = max(1, min(shengxu_mod.EXPLORE_MINUTES_MAX_COUNT, int(count or 1)))
    total_count = batches * 10 if addiction else 1

    from . import extra_cultivation
    if not extra_cultivation.is_overridden(doc, "huafen"):
        return False, "圣墟只向花粉进化路的修士显形（先发送 #踏上花粉路）。"
    flower_level = shengxu_mod.flower_level(doc)
    if flower_level < int(dungeon["req"]):
        return False, (f"【{dungeon['name']}】需花粉境 {dungeon['req']} 阶"
                       f"（当前 {flower_level} 阶）。")
    required_plane = shengxu_mod.plane_of(dungeon)
    if st.get("plane") != required_plane:
        return False, (f"【法身位面不符】{dungeon['name']}位于【{required_plane}】，"
                       f"当前法身位于【{st.get('plane') or '未知之地'}】。")

    daily = st.setdefault("shengxu_daily", {})
    day = day_key(float(now))
    if not addiction and daily.get(dungeon["name"]) == day:
        return False, f"你今日已经探索过{dungeon['name']}。"
    cost = shengxu_mod.explore_cost(dungeon, total_count, doc=doc)
    shortage = shengxu_mod.shortages(doc, cost)
    if shortage:
        return False, "【圣墟探索·资源不足】\n" + "\n".join(shortage)
    from . import lifespan
    paid_lifespan = lifespan.spend(doc, int(cost["shouyuan"]))
    if paid_lifespan < int(cost["shouyuan"]):
        lifespan.grant(doc, paid_lifespan)
        return False, f"寿元不足，需 {int(cost['shouyuan'])} 年。"

    doc.exp -= int(cost["xiuwei"])
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - int(cost["xueqi"])
    doc.stones -= int(cost["lingshi"])
    if not addiction:
        daily[dungeon["name"]] = day
    minutes_each = shengxu_mod.minutes_of(doc, dungeon)
    total_minutes = minutes_each * total_count
    start = float(now)
    # The snapshot holds the actor's combat/proficiency state; rewards are merged
    # into the live player on settlement so unrelated real-body progress survives.
    snapshot = doc.model_dump() if hasattr(doc, "model_dump") else copy.deepcopy(doc)
    snapshot_ext = snapshot.get("ext") if isinstance(snapshot, dict) else None
    if isinstance(snapshot_ext, dict):
        fashan_snapshot = copy.deepcopy(st)
        fashan_snapshot["action"] = None
        fashan_snapshot["state"] = "空闲"
        fashan_snapshot["shengxu_actor_hp_ratio"] = (
            min(1.0, max(0.0, float(st.get("hp", 0) or 0)
                         / max(1, int(st.get("hp_max", 1) or 1))))
        )
        fashan_snapshot["shengxu_actor_max_hp"] = 0
        snapshot_ext["fashan"] = fashan_snapshot
    st["action"] = {
        "kind": "圣墟", "plane": required_plane, "dungeon": dungeon["name"],
        "count": total_count, "batches": batches, "addiction": bool(addiction),
        "rounds": total_count, "start": start, "end": start + total_minutes * 60,
        "minutes_each": minutes_each, "cost": dict(cost),
        "settlement_id": f"fashan-shengxu:{getattr(doc, 'uid', '')}:{secrets.token_hex(8)}",
        "actor_snapshot": snapshot,
    }
    st["state"] = "行动中"
    label = "沉迷" if addiction else "探索"
    return True, (f"【{dungeon['name']}·法身开始{label}】法身踏入{dungeon['name']}，"
                  f"{dungeon['monster']}的气息在深处隐现。"
                  + (f"将连续探索 {total_count} 轮（{batches} 组）。" if addiction else "")
                  + f"\n入场消耗：修为 -{cost['xiuwei']:,}｜血气 -{cost['xueqi']:,}｜"
                    f"灵石 -{cost['lingshi']:,}｜寿元 -{cost['shouyuan']} 年"
                  + f"\n探索耗时：每轮 {minutes_each} 分钟，共 {total_minutes} 分钟；"
                    "到期后发送 #法身沉迷收获。")


def _merge_fashan_shengxu_progress(live: Any, before: Any, after: Any) -> None:
    """Merge only activity progress/rewards; HP remains in the independent Fashan actor slot."""
    before_ext = getattr(before, "ext", {})
    after_ext = getattr(after, "ext", {})
    live_ext = getattr(live, "ext", {})

    before_xueqi = int(before_ext.get("xueqi", 0) or 0)
    after_xueqi = int(after_ext.get("xueqi", 0) or 0)
    live.exp = max(0, int(live.exp) + int(after.exp) - int(before.exp))
    live.stones += max(0, int(after.stones) - int(before.stones))
    live_ext["xueqi"] = int(live_ext.get("xueqi", 0) or 0) + max(0, after_xueqi - before_xueqi)

    before_gongfa = set(str(x) for x in (before_ext.get("gongfa") or []))
    learned = [str(x) for x in (after_ext.get("gongfa") or []) if str(x) not in before_gongfa]
    live_gongfa = live_ext.setdefault("gongfa", [])
    if not isinstance(live_gongfa, list):
        live_gongfa = live_ext["gongfa"] = []
    for name in learned:
        if name not in live_gongfa:
            live_gongfa.append(name)

    for store_key in ("river_teachings", "prof"):
        before_values = before_ext.get(store_key) if isinstance(before_ext.get(store_key), Mapping) else {}
        after_values = after_ext.get(store_key) if isinstance(after_ext.get(store_key), Mapping) else {}
        live_values = live_ext.get(store_key)
        if isinstance(live_values, dict):
            for name, value in after_values.items():
                try:
                    delta = max(0, int(value or 0) - int(before_values.get(name, 0) or 0))
                except (TypeError, ValueError, OverflowError):
                    continue
                if delta:
                    live_values[name] = min(30, int(live_values.get(name, 0) or 0) + delta) if store_key == "river_teachings" else int(live_values.get(name, 0) or 0) + delta
        elif store_key == "river_teachings" and after_values:
            live_ext[store_key] = dict(after_values)

    before_flower = before_ext.get("flower") if isinstance(before_ext.get("flower"), Mapping) else {}
    after_flower = after_ext.get("flower") if isinstance(after_ext.get("flower"), Mapping) else {}
    live_flower = live_ext.get("flower") if isinstance(live_ext.get("flower"), Mapping) else None
    if live_flower is not None:
        merged = dict(live_flower)
        delta = max(0, int(after_flower.get("accum", 0) or 0)
                    - int(before_flower.get("accum", 0) or 0))
        if delta:
            merged["accum"] = int(merged.get("accum", 0) or 0) + delta
            shengxu_mod.flower.set_state(live, merged)

    before_sx = before_ext.get("shengxu") if isinstance(before_ext.get("shengxu"), Mapping) else {}
    after_sx = after_ext.get("shengxu") if isinstance(after_ext.get("shengxu"), Mapping) else {}
    live_sx = shengxu_mod.state_of(live)
    for key in ("clue", "runs", "field_pages"):
        delta = max(0, int(after_sx.get(key, 0) or 0) - int(before_sx.get(key, 0) or 0))
        if delta:
            live_sx[key] = int(live_sx.get(key, 0) or 0) + delta
    for key in ("pages", "cleared"):
        before_map = before_sx.get(key) if isinstance(before_sx.get(key), Mapping) else {}
        after_map = after_sx.get(key) if isinstance(after_sx.get(key), Mapping) else {}
        live_map = live_sx.get(key)
        if not isinstance(live_map, dict):
            live_map = live_sx[key] = {}
        for name, value in after_map.items():
            delta = max(0, int(value or 0) - int(before_map.get(name, 0) or 0))
            if delta:
                live_map[name] = int(live_map.get(name, 0) or 0) + delta


def _settle_fashan_river(doc: Any, st: dict, act: dict, now: float,
                         rng: random.Random, battle_runner=None
                         ) -> tuple[bool, str, dict[str, int], list[str]]:
    """Settle one original solo Fashan time-river stage via host-built fighters.

    Callback: battle_runner(snapshot_doc, river_state, rng) -> mapping with winner
    (0/1/None), a_hp/a_hp_max, primary_name, enemy_names, enemy_multiplier,
    log, teaching_seen and optional suppression.
    """
    from .player import PlayerDoc
    from . import river as river_mod, river_team
    from .combat import time_river as river_combat

    if battle_runner is None:
        return False, "法身时间长河需读取原版敌人表并使用共享战斗引擎；当前未接入该战斗回调，行动保留。", {}, []
    snapshot = act.get("actor_snapshot")
    baseline_snapshot = act.get("actor_baseline") or snapshot
    if not isinstance(snapshot, Mapping) or not isinstance(baseline_snapshot, Mapping):
        return False, "法身时间长河缺少开场战斗快照，行动保留待修复。", {}, []
    actor = PlayerDoc(**copy.deepcopy(dict(snapshot)))
    before = PlayerDoc(**copy.deepcopy(dict(baseline_snapshot)))
    river_state = act.get("river_state")
    river_state = river_state if isinstance(river_state, dict) else {
        "status": "exploring", "members": [str(doc.uid)], "leader": str(doc.uid),
        "stage": str(act.get("stage") or "initial"), "enemy_names": [],
        "cumulative_reward": 0,
    }
    act["river_state"] = river_state
    stage_before = str(river_state.get("stage") or act.get("stage") or "initial")
    result = battle_runner(actor, river_state, rng)
    if not isinstance(result, Mapping) or result.get("winner") not in (0, 1, None):
        return False, "法身时间长河帝战未能判定胜负，行动保留以避免丢失进度。", {}, []
    try:
        winner = int(result["winner"]) if result.get("winner") is not None else None
        hp_after = max(0, int(result.get("a_hp", 0) or 0))
        hp_max = max(1, int(result.get("a_hp_max", 1) or 1))
    except (TypeError, ValueError, OverflowError):
        return False, "法身时间长河战斗结果异常，行动保留。", {}, []

    river_state["stage"] = stage_before
    primary_name = str(result.get("primary_name") or river_state.get("primary_name") or "")
    enemy_names = list(result.get("enemy_names") or river_state.get("enemy_names") or ())
    if not primary_name:
        return False, "法身时间长河战斗结果缺少敌手名号，行动保留。", {}, []
    event = river_team.complete_stage(
        river_state, winner, primary_name, enemy_names, rng, now)
    stage_reward = max(0, int(event.get("reward_delta", 0) or 0))
    # complete_stage already advances the action's cumulative reward receipt.
    era = add_era(doc, stage_reward)
    body_max = max(1, int(st.get("hp_max", 0) or 1))
    st["hp"] = min(body_max, int(body_max * min(1.0, hp_after / hp_max)))
    notes = [str(line) for line in (result.get("log") or [])][-16:]
    lines = [f"【法身时间长河·{stage_before}阶段】{primary_name}"
             f"（战力倍率 ×{float(result.get('enemy_multiplier', 1.0) or 1.0):.2f}）",
             f"战果：{'胜' if winner == 0 else '败'}｜法身气血 {st['hp']:,}/{body_max:,}",
             *notes]
    if result.get("suppression"):
        lines.append(str(result["suppression"]))
    lines.append(f"纪元积累 +{era}（本次法身长河累计 +{int(river_state['cumulative_reward'])}）。")

    if winner == 0:
        # The original grants only the stage-specific era reward here; it does not
        # grant the local placeholder's additional per-realm cultivation reward.
        for teaching_name in result.get("teaching_seen", ()):
            gained, mastered = river_combat.teaching_progress(
                actor, str(teaching_name), river_combat.TIME_RIVER_TEACHING_GAIN)
            if gained:
                lines.append(f"【荒天帝真意】{teaching_name}进度 +{gained}。")
            if mastered:
                lines.append(f"【真意圆满】已领悟「{teaching_name}」。")
        if event.get("kind") == "next_stage":
            river_state["stage_started"] = float(now)
            # Keep the one-person action alive until each original 15-minute segment resolves.
            act["river_state"] = river_state
            act["stage"] = river_state["stage"]
            act["start"] = float(now)
            act["end"] = float(now) + RIVER_MINUTES * 60
            st["state"] = "行动中"
            _merge_fashan_shengxu_progress(doc, before, actor)
            act["actor_snapshot"] = actor.model_dump()
            act["actor_baseline"] = actor.model_dump()
            act["settlement_id"] = f"fashan-river:{getattr(doc, 'uid', '')}:{secrets.token_hex(8)}"
            lines.append(str(event.get("message") or "后续帝战已排期。"))
            return True, "\n".join(lines), {}, []
    elif winner == 1:
        loss = int(before.exp * 0.10)
        actor.exp = max(0, int(actor.exp) - loss)
        stage_reward = max(0, int(event.get("reward_delta", 1) or 0))
        era = add_era(doc, stage_reward)
        lines.append(f"败退岁月沉淀 +{stage_reward}（现纪元积累 +{era}）。")
        lines.append(f"法身败退，修为 -{loss:,}；不触发真身待援、炼化或过去身抹除。")
    else:
        lines.append("双方战势未分，依原版本段结算岁月沉淀；本次不扣修为。")

    st["state"] = "空闲"
    st["action"] = None
    _merge_fashan_shengxu_progress(doc, before, actor)
    lines.append("法身长河行动已结束；战败只结算法身气血，不触发真身待援、炼化或过去身抹除。")
    return True, "\n".join(lines), {}, []


def _settle_fashan_jiehai(doc: Any, st: dict, act: dict, now: float,
                          rng: random.Random, *, battle_runner=None, tier_rates=None
                          ) -> tuple[bool, str, dict[str, int], list[str]]:
    """Resolve one original Fashan Jiehai round using the saved static location row.

    Callback: battle_runner(snapshot_doc, place_row, rng) -> winner/a_hp/a_hp_max/log.
    """
    place = act.get("place_definition")
    snapshot = act.get("actor_snapshot")
    if not isinstance(place, Mapping) or not isinstance(snapshot, Mapping):
        return False, "界海探索缺少原版地点/法身快照，行动保留待接线。", {}, []
    if battle_runner is None:
        return False, "法身界海需要共享回合战斗回调，行动保留待接线。", {}, []
    from .player import PlayerDoc
    from . import memory, suiyun
    actor = PlayerDoc(**copy.deepcopy(dict(snapshot)))
    before = PlayerDoc(**copy.deepcopy(dict(snapshot)))
    result = battle_runner(actor, dict(place), rng)
    if not isinstance(result, Mapping) or result.get("winner") not in (0, 1):
        return False, "法身界海战斗未能判定胜负，行动保留。", {}, []
    winner = int(result["winner"])
    body_max = max(1, int(st.get("hp_max", 0) or 1))
    actor_hp_max = max(1, int(result.get("a_hp_max", 1) or 1))
    actor_hp = max(0, int(result.get("a_hp", 0) or 0))
    st["hp"] = min(body_max, int(body_max * min(1.0, actor_hp / actor_hp_max)))
    lines = [f"--- 法身界海【{str(place.get('name') or act.get('place'))}】结算 ---",
             f"法身战斗{'胜利' if winner == 0 else '失败'}｜血量 {st['hp']:,}/{body_max:,}"]
    lines.extend(str(line) for line in (result.get("log") or [])[-12:])
    items: dict[str, int] = {}
    if winner == 0:
        from . import secret as secret_mod
        rates_map = tier_rates if isinstance(tier_rates, Mapping) else {}
        rates = tuple(float(rates_map.get(key, default) or 0.0)
                      for key, default in (("one", 0.99), ("two", 0.5), ("three", 0.25)))
        loot = secret_mod.original_drop(place, rng, rates)
        reward = secret_mod.original_win_rewards(
            int(actor.realm_index) + 1, int(actor.physique_index) + 1, rng, loot)
        actor.exp += int(reward["exp"])
        actor.ext["xueqi"] = int(actor.ext.get("xueqi", 0) or 0) + int(reward["xueqi"])
        name = str(loot.get("name") or "").strip() if isinstance(loot, Mapping) else ""
        if name:
            multiplier = max(1, int(memory.effects(actor).get("item_mult", 1) or 1))
            multiplier *= max(1, int(suiyun.loot_mult(actor)))
            items[name] = multiplier * max(1, int(loot.get("quantity", 1) or 1))
        lines.append(f"修为 +{reward['exp']:,}｜血气 +{reward['xueqi']:,}" +
                     (f"｜获得【{name}】×{items[name]}（{loot.get('tier', 'none')}档）" if name
                      else "｜本次未获得额外道具"))
    else:
        # Original ordinary exploration losses set the actor health to zero; the real body is unaffected.
        st["hp"] = 0
        lines.append("法身被界海生灵击败，真身不受伤害；本次未获得战利品。")
    _merge_fashan_shengxu_progress(doc, before, actor)
    st["state"] = "空闲"
    st["action"] = None
    return True, "\n".join(lines), items, []


def _settle_special(doc: Any, st: dict, act: dict, now: float, rng: random.Random,
                    *, battle_runner=None, river_battle_runner=None,
                    jiehai_battle_runner=None, tier_rates=None, item_lookup=None
                    ) -> tuple[bool, str, dict[str, int], list[str]]:
    """Settle Fashan-specific routes; Shengxu requires the shared real battle engine."""
    kind = act["kind"]
    realm = authority_of(doc) + 1
    lines = [f"--- 法身{kind}结算 ---"]
    if kind == "上苍之上":
        # 原版 startFashanShangcang：逐轮胜率判定 → 四档池掉落 → 胜场/纪元进度写 ext["shangcang"]；
        # 法身败退只扣法身，真身不受伤害。
        from . import shangcang as sc_mod
        row = act.get("row") if isinstance(act.get("row"), Mapping) else {"name": act.get("place")}
        count = max(1, int(act.get("count") or 1))
        gains: dict[str, int] = {}
        sc_state = sc_mod.state_of(doc)
        wins = 0
        for i in range(count):
            if rng.random() > sc_mod.win_rate(doc):
                st["hp"] = 0
                lines.append(f"第 {i + 1} 轮：败。法身被上苍生灵击退，法身力竭（真身无伤）。")
                break
            wins += 1
            got = sc_mod.roll_rewards(row, rng)
            for name, qty in got.items():
                gains[name] = gains.get(name, 0) + qty
            sc_state["wins"] = int(sc_state.get("wins") or 0) + 1
            sc_state["progress"] = int(sc_state.get("progress") or 0) + 1
            era_note = ""
            if sc_state["progress"] >= sc_mod.ERA_PER_WINS:
                sc_state["progress"] -= sc_mod.ERA_PER_WINS
                gained = add_era(doc, sc_mod.ERA_REWARD)
                era_note = f"｜纪元积累 +{gained}"
            lines.append(f"第 {i + 1} 轮：胜。战利："
                         + ("、".join(f"{n}×{q}" for n, q in got.items()) or "无") + era_note)
        if wins:
            receipt = f"{act.get('place')}:{int(now)}:法身{wins}"
            receipts = [str(r) for r in (sc_state.get("receipts") or [])]
            if receipt not in receipts:
                receipts.append(receipt)
            sc_state["receipts"] = receipts[-sc_mod.RECEIPT_CAP:]
            lines.append(f"本次 {wins}/{count} 胜｜累计胜场 {sc_state['wins']}｜"
                         f"纪元进度 {sc_state['progress']}/{sc_mod.ERA_PER_WINS}")
        st["state"] = "空闲"
        st["action"] = None
        lines[0] = f"--- 法身上苍之上结算（{act.get('place')}）---"
        return True, "\n".join(lines), gains, []
    if kind == "圣墟":
        if battle_runner is None:
            return False, ("法身圣墟需要共享回合战斗结算；当前缺少战斗回调，行动保留待接线。"), {}, []
        snapshot = act.get("actor_snapshot")
        if not isinstance(snapshot, Mapping):
            return False, "法身圣墟缺少开场战斗快照，行动保留待修复。", {}, []
        from .player import PlayerDoc
        from . import memory
        actor = PlayerDoc(**copy.deepcopy(dict(snapshot)))
        actor_before = PlayerDoc(**copy.deepcopy(dict(snapshot)))
        actor_st = state_of(actor)
        actor_st["action"] = None
        sx_state = shengxu_mod.state_of(actor)
        sx_state["action"] = {
            "settlement_id": str(act.get("settlement_id") or ""),
            "dungeon": str(act.get("dungeon") or ""),
            "count": max(1, int(act.get("count", 1) or 1)),
            "start": float(act.get("start", now) or now),
            "end": float(act.get("end", now) or now),
            "minutes": max(0, int(act.get("minutes_each", 0) or 0)
                            * int(act.get("count", 1) or 1)),
        }
        ok, message, items, learned = shengxu_mod.settle(
            actor, sx_state, float(now), rng, battle_runner=battle_runner,
            tier_rates=tier_rates, item_lookup=item_lookup)
        if not ok:
            return False, message or "法身圣墟尚未到期，行动保留。", {}, []
        actor_sx_before = actor_before.ext.get("shengxu")
        actor_sx_before = actor_sx_before if isinstance(actor_sx_before, Mapping) else {}
        actor_sx_after = actor.ext.get("shengxu")
        actor_sx_after = actor_sx_after if isinstance(actor_sx_after, Mapping) else {}
        won_rounds = max(0, int(actor_sx_after.get("runs", 0) or 0)
                         - int(actor_sx_before.get("runs", 0) or 0))
        completed_rounds = won_rounds + (1 if "【探索失败】" in message else 0)
        if completed_rounds:
            memory.add_sim(doc, completed_rounds * memory.SIM_PER_RUN)
        actor_fashan = actor.ext.get("fashan") if isinstance(actor.ext.get("fashan"), Mapping) else {}
        actor_max_hp = max(0, int(actor_fashan.get("shengxu_actor_hp_max", 0) or 0))
        actor_hp = max(0, int(actor.ext.get("hp", actor_fashan.get("shengxu_actor_hp", 0)) or 0))
        if actor_max_hp:
            ratio = min(1.0, max(0.0, actor_hp / actor_max_hp))
            st["hp"] = int(max(0, int(st.get("hp_max", 0) or 0)) * ratio)
        _merge_fashan_shengxu_progress(doc, actor_before, actor)
        st["state"] = "空闲"
        st["action"] = None
        header = (f"--- 法身圣墟结算（{act.get('dungeon')} ×{act.get('count')}）---\n"
                  "探索副本使用独立法身快照战斗；结算进度合并回真身。")
        return True, header + "\n" + message, dict(items or {}), list(learned or [])

    if kind == "时间长河":
        return _settle_fashan_river(doc, st, act, now, rng, river_battle_runner)
    elif kind == "界海":
        return _settle_fashan_jiehai(doc, st, act, now, rng,
                                     battle_runner=jiehai_battle_runner,
                                     tier_rates=tier_rates)
    st["state"] = "空闲"
    st["action"] = None
    return True, "\n".join(lines), {}, []


def settle_detailed(doc: Any, now: float, rng: random.Random, *, battle_runner=None,
                    river_battle_runner=None, jiehai_battle_runner=None,
                    tier_rates=None, item_lookup=None
                    ) -> tuple[bool, str, dict[str, int], list[str]]:
    """结算法身行动。

    Host callbacks are needed for the shared combat/loadout layer:
    * battle_runner(doc, dungeon, rng, round_no) for Shengxu;
    * river_battle_runner(doc, river_state, rng) for the original solo river stages;
    * jiehai_battle_runner(doc, place_row, rng) for Jiehai.
    Returned item counts are committed by the main entrypoint in the same DB
    transaction as player/action state.
    """
    st = state_of(doc)
    act = st.get("action")
    if not st["owned"] or st["state"] != "行动中" or not act:
        return False, "法身当前没有待结算的行动。", {}, []
    left = remaining(st, now)
    if left > 0:
        return False, f"尚需 {int(left // 60)} 分 {int(left % 60)} 秒，未到结算时辰。", {}, []
    if act.get("kind") in ("时间长河", "界海", "圣墟", "上苍之上"):
        return _settle_special(doc, st, act, now, rng, battle_runner=battle_runner,
                               river_battle_runner=river_battle_runner,
                               jiehai_battle_runner=jiehai_battle_runner,
                               tier_rates=tier_rates, item_lookup=item_lookup)
    factor = 1.0 + float(plane.LEVELS.get(act["plane"], 0)) * 0.5
    realm = authority_of(doc) + 1
    rounds = int(act["rounds"])
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
    return True, "\n".join(lines), {}, []


def settle(doc: Any, now: float, rng: random.Random) -> tuple[bool, str]:
    """向后兼容旧的双返回值调用；新圣墟入口应使用 settle_detailed。"""
    ok, message, _items, _learned = settle_detailed(doc, now, rng)
    return ok, message


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
