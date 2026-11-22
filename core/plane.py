"""凡间坐标 + 位面旅行。

数据：data/位面坐标.json（11 张 1000×1000 方图，158 个地点，region/site 两级）。
原版：model/planeCoords.js + model/weimianTravel.js（1222 行，含维度壁垒/仙帝权柄/岁云套等）。
本移植只取诸天万界这一层（11 个有位图的位面，同层无壁垒）：
- 坐标：每位面独立坐标，界内移动即时，踩到地点首次发现给灵石/修为
- 位面：按境界门槛解锁 + 记忆坐标（星图/求购/每日线索三条获取路径）
- 旅行：航程 = 位面等级差 × 15 分钟 ×（1-境界减免），消耗修为/血气，异步抵达
shortcut: 未做维度壁垒（上苍之上/永恒未知之地等无方图位面）、传送阵令牌、位面毁灭，
         等开放高维位面时再接 DIMENSION_BARRIER_*。
"""

from __future__ import annotations
from .clock import day_key
from . import timed_action

import copy
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_PLANE = "凡间"
CMD_HINT = "#前往"

# 顺序 = 解锁推进顺序，level 即原版 PLACE_LOCATION_MAP 的位面坐标层级
PLANES: tuple[str, ...] = (
    "凡间", "下界八域", "遮天位面", "九天十地", "界海",
    "太初星墟", "小阴间", "大阴间", "仙界", "仙域", "阳间",
)
LEVELS: dict[str, float] = {
    "凡间": 0, "仙界": 1, "下界八域": 1.5, "遮天位面": 2, "九天十地": 2.5,
    "界海": 3, "太初星墟": 3.5, "小阴间": 4, "大阴间": 5, "仙域": 6, "阳间": 7,
}
# 门槛取本插件境界表下标（0 凡人 / 41 地仙 / 46 大罗金仙 / 49 究极仙王）
GATES: dict[str, int] = {
    "凡间": 0, "下界八域": 16, "遮天位面": 21, "九天十地": 26, "界海": 31,
    "太初星墟": 34, "小阴间": 36, "大阴间": 39, "仙界": 41, "仙域": 46, "阳间": 49,
}

# ---------------------------------------------------------------- W7-5b 维度壁垒
# 原版 model/weimianTravel.js:128-162：高维位面无方图，靠「破界强度」而非境界进入
HIGH_DIMENSIONS: dict[str, dict] = {
    "上苍之上": {"layer": 1, "power": 50, "desc": "界壁之上的第一重天，仙帝方可凭权柄触及。"},
    "超维宇宙": {"layer": 2, "power": 30, "desc": "维度褶皱里的残破宇宙，到处是别处的碎片。"},
    "厄土高原": {"layer": 3, "power": 60, "desc": "诡异源头盘踞之地，业力深重者反被吸引。"},
    "永恒未知之地": {"layer": 3, "power": 65, "desc": "时间失去意义，进入者多不再回来。"},
    "百维真界": {"layer": 4, "power": 80, "desc": "百重维度叠成的真界，一沙一世界。"},
    "原初宇宙海": {"layer": 5, "power": 90, "desc": "万物未分之前的宇宙海，混沌翻涌。"},
    "千维宙古界": {"layer": 6, "power": 100, "desc": "千维交织的宙古之界，神纹如网。"},
    "万维梵宇界": {"layer": 7, "power": 120, "desc": "万维梵唱，一花一梵宇。"},
    "神维丝线海": {"layer": 8, "power": 150, "desc": "维度之丝汇成的海，尽头通向不可名状。"},
}
BREAKING_POWER: dict[int, int] = {20: 30, 21: 65, 22: 80, 23: 100, 24: 120, 25: 150}
EMPEROR_FREE_TRAVEL: frozenset[str] = frozenset(
    set(PLANES) | {"上苍之上", "永恒未知之地", "厄土高原"})
MARK_COST = 300_000              # #刻画坐标：原版 3 亿 ÷1000

# 高维位面并入可旅行表：层级即壁垒重数，境界门槛交由破界强度判定
PLANES = PLANES + tuple(HIGH_DIMENSIONS)
LEVELS.update({name: float(cfg["layer"] + 7) for name, cfg in HIGH_DIMENSIONS.items()})
GATES.update({name: 10 ** 9 for name in HIGH_DIMENSIONS})

BASE_MIN_PER_LEVEL = 15
REDUCE_MAX = 0.6
EXP_PER_LEVEL = 800_000
XUEQI_PER_LEVEL = 1_200_000
CLUE_COST = 1_000_000            # #求购位面线索
STAR_MAP_ALT_COST = 500_000      # 无星图时 #记坐标 的灵石替代
CLUE_CHANCE = 0.15               # #探索位面线索 每日一次
SITE_STONES = 5_000              # 首次发现地点
SITE_EXP = 20_000


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）ext["plane"]。直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("plane")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("current", DEFAULT_PLANE)
    st.setdefault("coords", {})
    st.setdefault("known", [DEFAULT_PLANE])
    st.setdefault("discovered", {})
    st.setdefault("clue_day", "")
    st.setdefault("travel", None)
    st.setdefault("marks", {})        # 已刻画坐标：位面 → {x,y,at}
    st.setdefault("destroyed", {})    # 位面毁灭记录：位面 → {source,at}
    ext["plane"] = st
    return st


def current(st: Mapping) -> str:
    return str(st.get("current") or DEFAULT_PLANE)


def known_of(st: Mapping) -> list[str]:
    return [str(x) for x in (st.get("known") or [DEFAULT_PLANE])]


def coord_of(st: Mapping, plane: str | None = None) -> dict | None:
    c = (st.get("coords") or {}).get(plane or current(st))
    if isinstance(c, Mapping) and isinstance(c.get("x"), int) and isinstance(c.get("y"), int):
        return {"x": int(c["x"]), "y": int(c["y"])}
    return None


def discovered_of(st: Mapping, plane: str) -> list[str]:
    got = (st.get("discovered") or {}).get(plane)
    return [str(x) for x in got] if isinstance(got, list) else []


# ---------------------------------------------------------------- 坐标数据

def locations_of(data: Mapping, plane: str) -> list[dict]:
    entry = data.get(plane) if isinstance(data, Mapping) else None
    locs = entry.get("locations") if isinstance(entry, Mapping) else None
    return [x for x in locs if isinstance(x, Mapping)] if isinstance(locs, list) else []


def sites_of(data: Mapping, plane: str) -> list[dict]:
    return [x for x in locations_of(data, plane) if str(x.get("type")) == "site"]


def in_bounds(loc: Mapping, x: int, y: int) -> bool:
    b = loc.get("bounds") or {}
    try:
        return b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"]
    except (KeyError, TypeError):
        return False


def chain_at(data: Mapping, plane: str, x: int, y: int) -> list[dict]:
    """坐标归属链，外→内。空列表表示荒野。"""
    hits = [l for l in locations_of(data, plane) if in_bounds(l, x, y)]
    if not hits:
        return []
    ids = {l.get("id"): l for l in hits}
    leaf = next((h for h in hits if not any(o.get("parent") == h.get("id") for o in hits)), hits[-1])
    chain = [leaf]
    cur = leaf
    while cur.get("parent") in ids:
        cur = ids[cur["parent"]]
        chain.insert(0, cur)
    return chain


def center(loc: Mapping) -> dict:
    b = loc.get("bounds") or {}
    return {"x": (int(b["x1"]) + int(b["x2"])) // 2, "y": (int(b["y1"]) + int(b["y2"])) // 2}


def random_coord(loc: Mapping, rng: Any) -> dict:
    b = loc.get("bounds") or {}
    return {
        "x": int(b["x1"]) + rng.randrange(int(b["x2"]) - int(b["x1"]) + 1),
        "y": int(b["y1"]) + rng.randrange(int(b["y2"]) - int(b["y1"]) + 1),
    }


def chain_names(chain: Sequence[Mapping]) -> str:
    return " › ".join(str(x.get("name")) for x in chain)


# ---------------------------------------------------------------- 旅行

def realm_reduce(doc: Any) -> float:
    return min(REDUCE_MAX, max(0, int(getattr(doc, "realm_index", 0) or 0)) / 63 * 0.7)


def _meets(doc: Any, gate: int) -> bool:
    """双轨任一轨达标即通过（W0-2：位面门槛走 authority 换算）。"""
    from .authority import meets
    return meets(doc, gate)


# ---------------------------------------------------------------- W7-5b 维度壁垒 / 刻画 / 毁灭

def dim_tier(doc: Any) -> int:
    """双轨权柄 → 原版 0-25 破界档（63 境折 25 档，区别于 authority_21 的 0-21 映射）。"""
    from .authority import authority_of
    return min(25, authority_of(doc) * 25 // 63)


def breaking_power(doc: Any) -> int:
    return BREAKING_POWER.get(dim_tier(doc), 0)


def is_high_dim(name: str) -> bool:
    return name in HIGH_DIMENSIONS


def emperor_free_travel(doc: Any, src: str, target: str) -> bool:
    """仙帝（21 档+）可在诸天与三处界壁间自由通行，无视破界强度。"""
    return (dim_tier(doc) >= 21 and src in EMPEROR_FREE_TRAVEL
            and target in EMPEROR_FREE_TRAVEL)


def destroyed_of(st: Mapping, plane: str) -> dict | None:
    row = (st.get("destroyed") or {}).get(plane)
    return dict(row) if isinstance(row, Mapping) else None


def destroy_plane(st: dict, plane: str, source: str, now: float) -> bool:
    if plane not in LEVELS:
        return False
    st.setdefault("destroyed", {})[plane] = {"source": str(source or "未知"), "at": float(now)}
    return True


def repair_plane(st: dict, plane: str) -> bool:
    rows = st.get("destroyed")
    if not isinstance(rows, dict) or plane not in rows:
        return False
    rows.pop(plane, None)
    return True


def barrier_check(doc: Any, src: str, target: str,
                  destroyed: Mapping | None = None) -> tuple[bool, str]:
    """进入目标位面前的维度判定：毁灭记录 → 高维壁垒 → 仙帝通行。

    destroyed：全服毁灭记录（存 calamity_state，由调用方读出来传进来）。
    """
    st = state_of(doc)
    rows = destroyed if isinstance(destroyed, Mapping) else (st.get("destroyed") or {})
    row = rows.get(target)
    dead = dict(row) if isinstance(row, Mapping) else None
    if dead:
        return False, (f"【{target}】已毁灭（{dead.get('source')}），界门永闭，"
                       f"唯有管理员 #修复位面 可重开。")
    if target not in HIGH_DIMENSIONS:
        return True, ""
    if emperor_free_travel(doc, src, target):
        return True, ""
    cfg = HIGH_DIMENSIONS[target]
    power = breaking_power(doc)
    if power < cfg["power"]:
        return False, (f"【维度壁垒】{target} 藏在第 {cfg['layer']} 重界壁之后，"
                       f"需破界强度 {cfg['power']}（当前 {power}，权柄 {dim_tier(doc)}/25）。\n"
                       f"{cfg['desc']}")
    return True, ""


def mark_coordinate(doc: Any, plane: str, x: int, y: int, now: float) -> tuple[bool, str]:
    """#刻画坐标：把一处坐标锚点刻进神魂，之后可据此穿梭（原版已刻画坐标）。"""
    plane = (plane or "").strip()
    if plane not in LEVELS:
        return False, f"没有「{plane}」这个位面。"
    if not (0 <= int(x) <= 999 and 0 <= int(y) <= 999):
        return False, "坐标需在 0-999 之间。"
    st = state_of(doc)
    if plane in (st.get("marks") or {}):
        return False, f"【{plane}】的坐标已刻画过（{st['marks'][plane]['x']}, {st['marks'][plane]['y']}）。"
    if int(doc.stones) < MARK_COST:
        return False, f"刻画坐标需 {MARK_COST:,} 灵石（当前 {int(doc.stones):,}）。"
    doc.stones -= MARK_COST
    st.setdefault("marks", {})[plane] = {"x": int(x), "y": int(y), "at": float(now)}
    known = known_of(st)
    if plane not in known:
        st["known"] = known + [plane]
    return True, (f"你以神识在魂海中刻下【{plane}】（{x}, {y}）的坐标锚点，"
                  f"此后可直接朝此处穿梭（耗 {MARK_COST:,} 灵石）。")


def quote(doc: Any, target: str) -> dict:
    """返回 {distance, minutes, exp, xueqi, gate, ok, reason}。"""
    src = current(state_of(doc))
    gate = GATES.get(target, 10**9)
    if target not in LEVELS:
        return {"ok": False, "reason": "unknown", "gate": gate}
    distance = abs(LEVELS.get(src, 0) - LEVELS[target])
    minutes = max(1, round(distance * BASE_MIN_PER_LEVEL * (1 - realm_reduce(doc))))
    return {
        "ok": True, "reason": "", "distance": distance, "minutes": minutes,
        "exp": int(distance * EXP_PER_LEVEL), "xueqi": int(distance * XUEQI_PER_LEVEL),
        "gate": gate,
        # 高维位面不看境界，改由 barrier_check 的破界强度判定
        "enough_realm": True if target in HIGH_DIMENSIONS else _meets(doc, gate),
    }


def travel_state(st: Mapping, now: float) -> dict | None:
    tr = st.get("travel")
    if not isinstance(tr, Mapping):
        return None
    left = max(0.0, float(tr.get("arrive", 0) or 0) - now)
    out = dict(tr)
    out["left"] = left
    out["done"] = left <= 0
    return out


def begin_travel(doc: Any, target: str, data: Mapping, now: float,
                 destroyed: Mapping | None = None) -> tuple[bool, str]:
    st = state_of(doc)
    src = current(st)
    if target not in LEVELS:
        return False, f"没有「{target}」这个位面。可选：{'、'.join(PLANES)}"
    if target == src:
        return False, f"你已在【{src}】。"
    ok_barrier, why = barrier_check(doc, src, target, destroyed)
    if not ok_barrier:
        return False, why
    if getattr(doc, "state", "空闲") != "空闲":
        return False, f"道友正在「{doc.state}」中，无法分神穿梭。"
    q = quote(doc, target)
    if not q["enough_realm"]:
        from .authority import dual_level
        return False, (f"穿越【{target}】需境界达到第 {q['gate']} 境"
                       f"（当前练气 {doc.realm_index}／炼体 {doc.physique_index}），界壁压力过强。")
    if target not in known_of(st):
        return False, (f"你不知「{target}」的星空坐标。\n"
                       f"可 `#记坐标 {target}`、`#求购位面线索 {target}` 或每日 `#探索位面线索` 获取。")
    if int(doc.exp) < q["exp"]:
        return False, f"横渡【{target}】需修为 {q['exp']:,}（当前 {int(doc.exp):,}）。"
    xueqi = float(doc.ext.get("xueqi", 0) or 0)
    if xueqi < q["xueqi"]:
        return False, f"横渡【{target}】需血气 {q['xueqi']:,}（当前 {int(xueqi):,}）。"

    time_multiplier = timed_action.multiplier(doc, now)
    travel_minutes = max(1, math.ceil(q["minutes"] * time_multiplier))

    doc.exp = int(doc.exp) - q["exp"]
    doc.ext["xueqi"] = xueqi - q["xueqi"]
    doc.state = "穿梭中"
    doc.state_start = now
    st["travel"] = {
        "from": src, "to": target, "depart": float(now),
        "arrive": float(now) + travel_minutes * 60, "minutes": travel_minutes,
        "time_multiplier": time_multiplier,
    }
    return True, (f"【穿梭·{src} → {target}】\n"
                 f"你斩断周身空间涟漪，踏入星空古路。\n"
                 f"预计 {travel_minutes} 分钟后抵达，消耗修为 {q['exp']:,}、血气 {q['xueqi']:,}。\n"
                 f"抵达后发送「#抵达」落位。")


def settle(doc: Any, data: Mapping, now: float) -> tuple[Any, str | None]:
    """旅行到点落位。返回 (doc, 文案)；未到点或不在旅行返回 (doc, None)。"""
    st = state_of(doc)
    tr = travel_state(st, now)
    if not tr:
        return doc, None
    if not tr["done"]:
        return doc, None
    target = str(tr.get("to") or DEFAULT_PLANE)
    pool = sites_of(data, target) or locations_of(data, target)
    if pool:
        import random as _random
        rng = _random.Random(f"{getattr(doc, 'uid', '')}:{target}:{tr.get('arrive')}")
        loc = rng.choice(pool)
        coord = random_coord(loc, rng)
        chain = chain_at(data, target, coord["x"], coord["y"]) or [loc]
        st.setdefault("discovered", {}).setdefault(target, [])
        got = st["discovered"][target]
        if str(loc.get("id")) not in got:
            got.append(str(loc.get("id")))
    else:
        coord, chain = {"x": 500, "y": 500}, []
    st["current"] = target
    st["coords"][target] = coord
    st["travel"] = None
    doc.state = "空闲"
    doc.state_start = 0.0
    where = chain_names(chain) if chain else "荒芜之地"
    return doc, (f"【抵达·{target}】\n"
                 f"星空古路在脚下收束，你落在 {where}（{coord['x']}, {coord['y']}）。\n"
                 f"发送「#位面地图」查看地形，或「#前往 x,y」继续赶路。")


# ---------------------------------------------------------------- 界内移动

def move_to(doc: Any, data: Mapping, x: int, y: int) -> tuple[bool, str]:
    st = state_of(doc)
    plane = current(st)
    if getattr(doc, "state", "空闲") == "穿梭中":
        return False, "尚在穿梭途中，先「#抵达」。"
    if not (0 <= x <= 999 and 0 <= y <= 999):
        return False, "坐标需在 0-999 之间（x 向东、y 向南）。"
    chain = chain_at(data, plane, x, y)
    st["coords"][plane] = {"x": int(x), "y": int(y)}
    if not chain:
        return True, (f"你行至【{plane}】({x}, {y})，四下荒芜，灵气稀薄，"
                      f"并无特别之处。")
    leaf = chain[-1]
    sites = st.setdefault("discovered", {}).setdefault(plane, [])
    first = str(leaf.get("id")) not in sites
    if first:
        sites.append(str(leaf.get("id")))
        doc.stones = int(doc.stones) + SITE_STONES
        doc.exp = int(doc.exp) + SITE_EXP
        bonus = f"\n【初至】灵石 +{SITE_STONES:,}｜修为 +{SITE_EXP:,}"
    else:
        bonus = ""
    desc = str(leaf.get("desc") or "")
    return True, (f"你来到【{leaf.get('name')}】（{chain_names(chain)}）({x}, {y})\n"
                  f"{desc}{bonus}")


# ---------------------------------------------------------------- 记忆坐标

def remember(doc: Any, plane: str) -> tuple[bool, str]:
    st = state_of(doc)
    if plane not in LEVELS:
        return False, f"没有「{plane}」这个位面。"
    if plane in known_of(st):
        return False, f"你已记住「{plane}」的坐标。"
    st["known"].append(plane)
    return True, f"【星路入识】「{plane}」的坐标已烙入识海。"


def buy_clue(doc: Any, plane: str) -> tuple[bool, str]:
    if plane not in LEVELS:
        return False, f"没有「{plane}」这个位面。可求购：{'、'.join(PLANES)}"
    st = state_of(doc)
    if plane in known_of(st):
        return False, f"你已记住「{plane}」的坐标，无需求购。"
    if int(doc.stones) < CLUE_COST:
        return False, f"求购「{plane}」线索需 {CLUE_COST:,} 灵石（当前 {int(doc.stones):,}）。"
    doc.stones = int(doc.stones) - CLUE_COST
    st["known"].append(plane)
    return True, (f"【重金求购·星路入识】\n"
                  f"你从跨界行商手中换得「{plane}」的完整星图线索，神识推演后坐标已烙入识海。\n"
                  f"灵石 -{CLUE_COST:,}")


def explore_clue(doc: Any, now: float, rng: Any) -> tuple[bool, str]:
    st = state_of(doc)
    day = day_key(now)
    if str(st.get("clue_day") or "") == day:
        return False, "今日的星象已被推演过，明日再来。"
    unknown = [p for p in PLANES if p not in known_of(st)]
    if not unknown:
        return False, "诸天位面的坐标你已尽数记住，再无线索可寻。"
    st["clue_day"] = day
    if rng.random() >= CLUE_CHANCE:
        return True, "你在山川间寻得残破星纹，可惜道韵已散，未能补全坐标。"
    pick = rng.choice(unknown)
    st["known"].append(pick)
    return True, f"【石壁参悟·坐标已记】\n你拂去石壁尘埃，以神识补全残缺星纹，记住了「{pick}」的位面坐标。"


# ---------------------------------------------------------------- 文案

def _gate_label(gate: int, realm_names: Sequence[str]) -> str:
    if gate <= 0:
        return "无门槛"
    name = realm_names[gate] if 0 <= gate < len(realm_names) else f"第{gate}境"
    return f"{name}（{gate}境）"


def plane_text(doc: Any, data: Mapping, realm_names: Sequence[str], now: float,
               destroyed: Mapping | None = None) -> str:
    st = state_of(doc)
    plane = current(st)
    coord = coord_of(st, plane)
    known = known_of(st)
    lines = ["--- 位面 · 诸天星路 ---",
             f"当前：{plane}（{coord['x']}, {coord['y']}）" if coord else f"当前：{plane}（未落位｜{CMD_HINT} x,y 定位）"]
    chain = chain_at(data, plane, coord["x"], coord["y"]) if coord else []
    if chain:
        lines.append(f"所在：{chain_names(chain)}")
    lines.append(f"记忆坐标：{'、'.join(known)}（{len(known)}/{len(PLANES)}）")
    lines.append(f"破界强度：{breaking_power(doc)}（权柄 {dim_tier(doc)}/25）")
    marks = st.get("marks") or {}
    if marks:
        lines.append("已刻画坐标：" + "、".join(f"{k}({v.get('x')},{v.get('y')})" for k, v in marks.items()))
    dead = destroyed if isinstance(destroyed, Mapping) else (st.get("destroyed") or {})
    if dead:
        lines.append("已毁灭位面：" + "、".join(f"{k}（{v.get('source')}）" for k, v in dead.items()))
    tr = travel_state(st, now)
    if tr:
        lines.append(f"行程：{tr.get('from')} → {tr.get('to')}，"
                     f"剩余 {int(tr['left'] // 60)} 分 {int(tr['left'] % 60)} 秒" if not tr["done"]
                     else f"行程：{tr.get('from')} → {tr.get('to')}，已抵达（发「#抵达」）")
    else:
        lines.append("行程：无")
    lines.append("")
    for p in PLANES:
        q = quote(doc, p)
        if p in HIGH_DIMENSIONS:
            cfg = HIGH_DIMENSIONS[p]
            if (destroyed if isinstance(destroyed, Mapping) else {}).get(p) or destroyed_of(st, p):
                mark = "✖ 已毁灭"
            elif emperor_free_travel(doc, plane, p) or breaking_power(doc) >= cfg["power"]:
                mark = f"✔ 破界 {breaking_power(doc)}/{cfg['power']}｜第 {cfg['layer']} 重"
            else:
                mark = f"✖ 需破界 {cfg['power']}（现 {breaking_power(doc)}）"
            lines.append(f"· {p}（壁垒 {cfg['layer']} 重）{mark}")
            continue
        if p == plane:
            mark = "● 当前"
        elif not q["enough_realm"]:
            mark = f"✖ 需 {_gate_label(q['gate'], realm_names)}"
        elif p not in known:
            mark = "？ 坐标未知"
        else:
            mark = f"✔ {q['minutes']} 分｜修为 {q['exp']:,}｜血气 {q['xueqi']:,}"
        lines.append(f"· {p}（Lv{LEVELS[p]:g}）{mark}")
    lines.append("")
    lines.append("记忆：#记坐标 位面｜#求购位面线索 位面｜#探索位面线索｜#穿梭 位面")
    lines.append("高维：#刻画坐标 位面 x,y 可越过「坐标未知」，但仍受维度壁垒限制")
    return "\n".join(lines)


def memory_text(doc: Any, data: Mapping, realm_names: Sequence[str], now: float) -> str:
    st = state_of(doc)
    known = known_of(st)
    lines = ["--- 坐标记忆 ---"]
    total_sites = total_found = 0
    for p in PLANES:
        sites = sites_of(data, p)
        found = [x for x in discovered_of(st, p) if x in {str(s.get("id")) for s in sites}]
        total_sites += len(sites)
        total_found += len(found)
        if p in known:
            lines.append(f"· {p}｜已记坐标｜地点 {len(found)}/{len(sites)}")
        else:
            lines.append(f"· {p}｜坐标未知｜{_gate_label(GATES.get(p, 0), realm_names)}")
    lines.append(f"总计：{len(known)}/{len(PLANES)} 位面｜地点探索 {total_found}/{total_sites}")
    day = day_key(now)
    lines.append(f"今日线索：{'已推演' if str(st.get('clue_day') or '') == day else '未推演（#探索位面线索）'}")
    lines.append(f"#记坐标 位面（星图×1 或灵石 {STAR_MAP_ALT_COST:,}）｜#求购位面线索 位面（{CLUE_COST:,} 灵石）")
    return "\n".join(lines)


def map_payload(doc: Any, data: Mapping, plane: str, now: float) -> dict:
    st = state_of(doc)
    coord = coord_of(st, plane)
    found = set(discovered_of(st, plane))
    locs = locations_of(data, plane)
    by_id = {str(l.get("id")): l for l in locs}

    def _depth(loc: Mapping) -> int:
        n, cur = 0, loc
        while cur.get("parent") in by_id and n < 8:
            cur = by_id[str(cur["parent"])]
            n += 1
        return n

    regions, sites = [], []
    for loc in locs:
        b = loc.get("bounds") or {}
        item = {
            "name": str(loc.get("name") or ""),
            "left": round(int(b["x1"]) / 1000 * 100, 2),
            "top": round(int(b["y1"]) / 1000 * 100, 2),
            "w": round((int(b["x2"]) - int(b["x1"])) / 1000 * 100, 2),
            "h": round((int(b["y2"]) - int(b["y1"])) / 1000 * 100, 2),
            "desc": str(loc.get("desc") or ""),
            "known": str(loc.get("id")) in found,
            "id": str(loc.get("id")),
            "depth": _depth(loc),
        }
        (sites if str(loc.get("type")) == "site" else regions).append(item)
    dot = None
    if coord:
        dot = {"left": round(coord["x"] / 1000 * 100, 2), "top": round(coord["y"] / 1000 * 100, 2)}
    chain = chain_at(data, plane, coord["x"], coord["y"]) if coord else []
    site_coords = [
        {"name": str(s["name"]), "known": s["known"], "xy": f"{center(l)['x']},{center(l)['y']}"}
        for l, s in zip([x for x in locs if str(x.get("type")) == "site"], sites) if s["known"]
    ]
    return {
        "title": f"位面地图 · {plane}",
        "sub": "",
        "footer": f"地点 {len(found)}/{len(sites)}",
        "plane": plane,
        "regions": regions,
        "sites": sites,
        "dot": dot,
        "where": chain_names(chain) if chain else "荒野",
        "here": str(chain[-1].get("desc") or "") if chain else "",
        "coords": site_coords[:10],
        "unknown_n": len(sites) - len(site_coords),
    }


def map_text(doc: Any, data: Mapping, plane: str) -> str:
    st = state_of(doc)
    coord = coord_of(st, plane)
    found = set(discovered_of(st, plane))
    lines = [f"--- 位面地图 · {plane} ---"]
    if coord:
        chain = chain_at(data, plane, coord["x"], coord["y"])
        lines.append(f"坐标 ({coord['x']}, {coord['y']})｜{chain_names(chain) if chain else '荒野'}")
    for loc in locations_of(data, plane):
        c = center(loc)
        flag = "已知" if str(loc.get("id")) in found else "未探"
        kind = "地" if str(loc.get("type")) == "site" else "域"
        lines.append(f"[{kind}] {loc.get('name')}（{c['x']},{c['y']}）{flag}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 保存

def save(doc: Any, st: Mapping) -> Any:
    d = doc.model_copy(deep=True)
    d.ext["plane"] = copy.deepcopy(dict(st))
    return d
