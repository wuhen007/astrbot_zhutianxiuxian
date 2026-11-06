"""本命法宝（W8-C1）：三器炼化 / 淬炼 / 升华 / 六类镶嵌 / 器灵 / 共鸣 / 形态 / 终极强化。

原版：`apps/Auction/bengming.js` 2572 行 / 43 条 reg。

移植口径（以源码为准，规划稿有 5 处冲突已订正）：
- **43 条 reg 不是 39 条**；三器每类各有独立 reg，靠 fnc 参数分派，不是单指令。
- **全文件无 CD / 无冷却判定**；升华 **无成功率、无材料、无失败惩罚**，只有淬炼值门槛 +
  终境魂魄圆满门禁；唯一的成功率公式在「终极强化」（1 - 等级*0.045 - 成功次数*0.012）。
- **剑境共鸣是单器独立触发**（契合≥100 + 已命名性别），源码没有「三槽同系」判定；
  规划里的「同系」实际对应「天赋」（按镶嵌材料投票 5 类）。源码把结果写进
  `player.临时攻击/临时防御/临时血量` + 1 小时过期戳，但**全库无战斗消费者**——
  本移植把它接进 `build_fighter`，让这套玩法真正有收益。
- 原版状态写在**装备文档**（`equipment.武器/护具/法宝` 同一对象）；本移植 `ext["equipment"]`
  只存物品名，因此另立 `ext["bengming"]` 子字典，**炼化即生效、无需穿戴**。
- 原版 20 件材料**没有任何发放点**（商店/副本/掉落全无，只有器灵对战胜利随机 1 件）；
  本移植补一条秘境结算投放，否则整套系统不可玩。

shortcut：
- 原版三维是 1e8~1e10 量级，本移植境界基础 8e5（中期）~1e10（末境），统一 **÷1000** 折算，
  避免前期一件材料碾压全境。写在本模块 `SCALE`。
- 原版五行/阴阳/时空/因果/生命五维法则无对应战斗通道，统一折算成 flat 三维（`LAW_SCALE`）。
- 器灵对战原版是「房间号 + 6 回合 + 私聊奖惩」的自洽小游戏，本移植保留 6 回合判定与材料奖励，
  去掉房间匹配（本移植无房间制）。
- 化剑为鞘/化鞘为剑原版直接改装备 atk/def 并同步玩家上限；本移植在 `bonus()` 里按形态乘算，
  不落盘改写（可逆且无浮点残留）。
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Mapping
from typing import Any

PARTS: tuple[str, ...] = ("武器", "护具", "法宝")
SPIRIT: dict[str, str] = {"武器": "剑灵", "护具": "护灵", "法宝": "宝灵"}
CORE_SLOT: dict[str, str] = {"武器": "三魂", "护具": "核心", "法宝": "灵韵"}
AUX_SLOT: dict[str, str] = {"武器": "七魄", "护具": "辅魂", "法宝": "灵纹"}
CORE_CAP, AUX_CAP = 3, 7
BATCH_MAX = 10             # 淬炼 / 终极强化批量上限（BM:1234 / 2097）
EMBER_MAX = 5              # 淬炼余烬上限（BM:722）
ECHO_MAX = 4               # 终极强化残响上限（BM:772）
NAME_MAX = 10
AFFINITY_MAX, MOOD_MAX = 1000, 100
RESONANCE_SECONDS = 3600   # 共鸣 1 小时（BM:2010）
ULT_DECAY_LEVEL = 0.045    # BM:25
ULT_DECAY_WIN = 0.012      # BM:26
SCALE = 1 / 1000           # 原版数值 → 本移植量级
LAW_SCALE = 1 / 10_000_000  # 法则值 → flat 三维

# 品质档位（BM:146-150 / 218-221 / 282-285）
LEVELS: dict[str, tuple[str, ...]] = {
    "武器": ("凡铁", "剑胎", "利剑", "灵剑", "宝器", "法器", "灵器", "仙器", "神器",
             "道器", "先天灵宝", "混沌至宝", "鸿蒙道胚", "太初源器"),
    "护具": ("凡布", "护心", "精钢甲", "宝甲", "灵甲", "仙甲", "神甲", "道甲",
             "先天甲", "混沌甲", "鸿蒙圣甲", "太初祖甲"),
    "法宝": ("凡器", "法器", "宝器", "灵器", "仙器", "神器", "道器",
             "先天灵宝", "混沌至宝", "鸿蒙道宝", "太初源宝"),
}
# 淬炼上限需求（BM:185-199 / 253-265 / 316-327）
QUENCH_CAP: dict[str, tuple[int, ...]] = {
    "武器": (0, 100000, 300000, 500000, 800000, 1200000, 2000000, 3000000, 5000000,
             8000000, 12000000, 20000000, 36000000, 60000000),
    "护具": (0, 80000, 150000, 300000, 500000, 800000, 1200000, 2000000, 5000000,
             10000000, 18000000, 32000000),
    "法宝": (0, 100000, 200000, 400000, 800000, 1500000, 3000000, 8000000,
             15000000, 28000000, 52000000),
}
# 终境门禁：这些档位要求 core≥3 且 aux≥7（BM:154 / 225 / 289）
FINAL_GATE = {"武器": ("鸿蒙道胚", "太初源器"), "护具": ("鸿蒙圣甲", "太初祖甲"),
              "法宝": ("鸿蒙道宝", "太初源宝")}
# 模块偏置（BM:538-544）
BIAS: dict[str, tuple[float, float, float]] = {
    "武器": (1.25, 0.75, 0.85), "护具": (0.75, 1.25, 1.05), "法宝": (0.9, 0.9, 1.25),
}
# 共鸣分模块比例（BM:1971-1983）
RESONANCE_RATIO: dict[str, tuple[float, float, float]] = {
    "武器": (0.6, 0.2, 0.2), "护具": (0.2, 0.6, 0.4), "法宝": (0.3, 0.3, 0.8),
}
# 初始属性（BM:155-168 / 226-238 / 290-302）
INITIAL: dict[str, tuple[int, int, int, int, int]] = {
    "武器": (10000, 5000, 50000, 1000, 5000),
    "护具": (3000, 10000, 80000, 1500, 8000),
    "法宝": (5000, 5000, 100000, 800, 3000),
}

# ── 材料表（20 件，原版 resources/data/item/道具列表.json:3500-3678）──────────
# 名称 -> (攻, 防, 血, 暴击, 法则dict, 契合, 心情, 淬炼值)
CORE_MATS: dict[str, tuple] = {
    "太初魂晶": (1500000000, 500000000, 1000000000, 0.08, {"五行": 5000, "生命": 3000}, 0, 0, 0),
    "九霄灵髓": (2000000000, 200000000, 500000000, 0.15, {"五行": 2500, "时空": 4500}, 0, 0, 0),
    "幽冥月露": (1200000000, 800000000, 1500000000, 0.05,
                {"阴阳": 3500, "因果": 3500, "生命": 1500}, 0, 0, 0),
}
AUX_MATS: dict[str, tuple] = {
    "天狼牙砂": (300000000, 1800000000, 1200000000, 0.02, {"阴阳": 1800, "因果": 1200}, 0, 0, 0),
    "玄武铁鳞": (500000000, 1500000000, 2000000000, 0.0, {"阴阳": 2400, "生命": 2200}, 0, 0, 0),
    "凤凰火羽": (800000000, 1000000000, 1500000000, 0.05, {"五行": 2200, "生命": 2000}, 0, 0, 0),
    "饕餮骨玉": (1000000000, 1200000000, 1000000000, 0.03, {"因果": 2600, "五行": 1200}, 0, 0, 0),
    "麒麟角粉": (600000000, 2000000000, 800000000, 0.01, {"生命": 2400, "阴阳": 1600}, 0, 0, 0),
    "建木心屑": (400000000, 1600000000, 1800000000, 0.0, {"生命": 2600, "五行": 1400}, 0, 0, 0),
    "鲲鹏绒羽": (700000000, 1000000000, 1500000000, 0.04, {"时空": 2600, "五行": 1200}, 0, 0, 0),
}
QUENCH_MATS: dict[str, tuple] = {
    # 攻/防/血/百分比(攻,防,血)/淬炼值/法则dict/契合/心情
    "五行聚灵晶": (1200000000, 1200000000, 1200000000, (.004, .004, .004), 70000,
                {"五行": 9000}, 2, 0),
    "阴阳两极砂": (1600000000, 1600000000, 700000000, (.005, .005, .002), 60000,
                {"阴阳": 11000}, 1, 0),
    "时空凝滞石": (900000000, 900000000, 900000000, (.003, .003, .003), 95000,
                {"时空": 13000}, 0, -1),
    "因果纠缠丝": (1400000000, 800000000, 1200000000, (.005, .002, .004), 55000,
                {"因果": 14000}, 3, 0),
    "生命本源露": (700000000, 1200000000, 2200000000, (.002, .004, .007), 60000,
                {"生命": 15000}, 2, 4),
}
REPAIR_MATS: dict[str, tuple] = {
    "青岚髓": (0, 0, 0, 0.0, {}, 4, 8, 0),
    "玄水丝": (0, 0, 0, 0.0, {}, 3, 10, 0),
    "劫火红绒": (0, 0, 0, 0.0, {}, 2, 14, 0),
    "木灵胶": (0, 0, 0, 0.0, {}, 3, 12, 0),
    "星尘砂": (0, 0, 0, 0.0, {}, 5, 16, 0),
}
# 终极强化：别名 -> (部位, 材料, 攻, 防, 血, 法则, 契合)（BM:2101-2117）
ULTIMATE: dict[str, tuple] = {
    "引雷淬火": ("武器", "劫火红绒", 2400000000, 600000000, 600000000,
              {"五行": 3000, "阴阳": 1000}, 0),
    "玄铁精炼": ("护具", "木灵胶", 500000000, 2400000000, 1500000000,
              {"阴阳": 3000, "生命": 2000}, 0),
    "法则滋养": ("法宝", "星尘砂", 1100000000, 1100000000, 2200000000,
              {"五行": 1500, "阴阳": 1500, "时空": 3500, "因果": 2500, "生命": 2500}, 2),
}
# 天赋（BM:905-931）：核心材料投票决定
TALENTS: dict[str, tuple[str, str, dict[str, float]]] = {
    "时空先手": ("spacetime", "先手夺势，攻击 +8%", {"atk": 1.08}),
    "因果逆命": ("causality", "逆命改运，攻击/血量 +5%", {"atk": 1.05, "hp": 1.05}),
    "玄甲生息": ("guard", "玄甲护体，防御 +12% / 血量 +8%", {"def": 1.12, "hp": 1.08}),
    "炎羽追击": ("flame", "炎羽追击，攻击 +12%", {"atk": 1.12}),
    "五行归元": ("origin", "五行归元，三维 +6%", {"atk": 1.06, "def": 1.06, "hp": 1.06}),
}
TALENT_VOTE = {
    "太初魂晶": "五行归元", "九霄灵髓": "时空先手", "幽冥月露": "因果逆命",
    "天狼牙砂": "因果逆命", "玄武铁鳞": "玄甲生息", "凤凰火羽": "炎羽追击",
    "饕餮骨玉": "玄甲生息", "麒麟角粉": "五行归元", "建木心屑": "五行归元",
    "鲲鹏绒羽": "时空先手",
}
# 契合度阶段（BM:1866-1874）
STAGES = ((0, "形同陌路"), (100, "略有感应"), (200, "心意相通"), (300, "人器相融"),
          (500, "魂器合一"), (700, "道器同归"), (900, "混沌一体"))
PERSONALITIES = ("清冷", "傲娇", "沉稳", "活泼", "寡言", "炽烈", "温润", "狡黠",
                 "孤高", "赤诚", "慵懒", "端方", "率真", "幽邃", "飒爽", "护主")
# 淬炼异象（BM:733-739）：(权重, 属性倍率, 法则倍率, 火候倍率, 名称)
OMENS = ((66, 1.0, 1.0, 1.0, "稳火淬炼"), (20, 1.5, 1.2, 1.1, "精炼成功"),
         (8, 2.0, 1.5, 1.25, "淬炼大成"), (4, 2.8, 2.0, 1.3, "过载淬炼"),
         (2, 0.45, 0.6, 0.55, "灵火余烬"))
# 性别觉醒加成（BM:589-604），按部位 × 性别：(攻, 防, 血, 法则)
BIRTH_BONUS = {
    "武器": {"男": (350000000, 120000000, 180000000, {"五行": 3000, "时空": 1500}),
             "女": (220000000, 300000000, 220000000, {"阴阳": 2500, "生命": 2000})},
    "护具": {"男": (120000000, 380000000, 260000000, {"阴阳": 2200, "生命": 2400}),
             "女": (160000000, 300000000, 320000000, {"五行": 1800, "生命": 3000})},
    "法宝": {"男": (280000000, 180000000, 300000000, {"时空": 2600, "因果": 1800}),
             "女": (200000000, 240000000, 380000000, {"五行": 2200, "因果": 2400})},
}
# 磨合事件（BM:1794-1840）：(概率, 倍率, 名称)
TEMPER_EVENTS = ((0.40, 1.0, "静心相对"), (0.30, 7.5, "心念相通"),
                 (0.20, 5.0, "道顿悟"), (0.08, 5.0, "人器合一"),
                 (0.02, 5.0, "反噬离心"))

ALL_MATS: dict[str, tuple] = {**CORE_MATS, **AUX_MATS, **QUENCH_MATS, **REPAIR_MATS}


def is_core(name: str) -> bool:
    return name in CORE_MATS


def is_aux(name: str) -> bool:
    return name in AUX_MATS


def is_quench(name: str) -> bool:
    return name in QUENCH_MATS


def is_repair(name: str) -> bool:
    return name in REPAIR_MATS


def part_of_spirit(name: str) -> str | None:
    for p, s in SPIRIT.items():
        if s == name:
            return p
    return None


def _defaults(part: str) -> dict[str, Any]:
    atk, dfn, hp, dura, dura_max = INITIAL[part]
    return {
        "level": 0, "refined": 0, "tries": 0, "sense": 0.0,
        "quench": 0, "embers": 0,
        "durability": dura, "dura_max": dura_max,
        "atk": atk, "def": dfn, "hp": hp, "bao": 0.0, "law": 0.0,
        "core": [], "aux": [], "sheath": 0,
        "ult_success": 0, "echo": {},
        "spirit": {"name": None, "gender": None, "personality": None,
                   "affinity": 0, "mood": 50, "atk": 0, "def": 0, "hp": 0,
                   "talent": None},
        "resonance_until": 0.0, "resonance": {"atk": 0, "def": 0, "hp": 0},
    }


def _norm(raw: Any, part: str) -> dict[str, Any]:
    d = _defaults(part)
    if not isinstance(raw, Mapping):
        return d
    for k, v in raw.items():
        if k == "spirit" and isinstance(v, Mapping):
            d["spirit"].update({kk: vv for kk, vv in v.items() if kk in d["spirit"]})
        elif k == "resonance" and isinstance(v, Mapping):
            d["resonance"].update({kk: vv for kk, vv in v.items() if kk in d["resonance"]})
        elif k in d:
            d[k] = v
    lv = LEVELS[part]
    try:
        d["level"] = max(0, min(int(d["level"] or 0), len(lv) - 1))
    except (TypeError, ValueError):
        d["level"] = 0
    d["core"] = [str(x) for x in (d["core"] or [])][:CORE_CAP]
    d["aux"] = [str(x) for x in (d["aux"] or [])][:AUX_CAP]
    return d


def state_of(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get("bengming")
    raw = raw if isinstance(raw, Mapping) else {}
    return {p: _norm(raw.get(p), p) for p in PARTS}


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["bengming"] = {p: dict(st[p]) for p in PARTS}


def one(doc: Any, part: str) -> dict[str, Any]:
    """取单个器并写回（调用方在结果成功后必须 set_state）。"""
    return state_of(doc)[part]


def commit(doc: Any, st: Mapping[str, Any], part: str, one_state: Mapping[str, Any]) -> None:
    out = {p: dict(st[p]) for p in PARTS}
    out[part] = dict(one_state)
    set_state(doc, out)


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, dict(delta or {})


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


def _need(part: str | None) -> str | None:
    if part not in PARTS:
        return "格式有误：本命分武器 / 护具 / 法宝三器。"
    return None


def _refined(d: Mapping[str, Any], part: str) -> str | None:
    if not int(d["refined"] or 0):
        return f"尚未炼化本命{part}，先发 #炼化本命{part}。"
    return None


def level_name(part: str, lv: int) -> str:
    return LEVELS[part][max(0, min(lv, len(LEVELS[part]) - 1))]


def soul_multiplier(d: Mapping[str, Any]) -> float:
    c, a = len(d["core"]), len(d["aux"])
    return 1 + c * 0.04 + a * 0.02 + (0.25 if c >= CORE_CAP and a >= AUX_CAP else 0)


def complete(d: Mapping[str, Any]) -> bool:
    return len(d["core"]) >= CORE_CAP and len(d["aux"]) >= AUX_CAP


def _add_law(d: dict, law: Mapping[str, Any]) -> None:
    for _k, v in (law or {}).items():
        try:
            d["law"] = float(d["law"] or 0) + float(v or 0)
        except (TypeError, ValueError):
            pass


def _talent(d: Mapping[str, Any]) -> str | None:
    vote: dict[str, int] = {}
    for n in list(d["core"]) + list(d["aux"]):
        t = TALENT_VOTE.get(n)
        if t:
            vote[t] = vote.get(t, 0) + 1
    return max(vote, key=lambda k: vote[k]) if vote else None


def _refresh_talent(d: dict) -> None:
    d["spirit"]["talent"] = _talent(d)


# ── 1. 炼化（BM:1081-1129 / 668-682）───────────────────────────────────────

def refine_chance(doc: Any, part: str, d: Mapping[str, Any]) -> float:
    """成功率：品级 + 三轨境界 + 器性暴击 + 本命感应，硬顶 92%。"""
    try:
        realm = (int(getattr(doc, "realm_index", 0) or 0)
                 + int(getattr(doc, "physique_index", 0) or 0)) / 180
    except (TypeError, ValueError):
        realm = 0.0
    pinji = 0.0   # 本移植装备槽存名称，无 pinji 字段；按已穿装备件数折算
    worn = (doc.ext.get("equipment") or {})
    pinji = min(len(worn) * 0.04, 0.24)
    realm_b = min(realm / 2, 0.22)
    crit_b = min(float(d["bao"] or 0) * 0.18, 0.12)
    sense_b = min(float(d["sense"] or 0) / 1000, 0.5)
    return min(0.22 + pinji + realm_b + crit_b + sense_b, 0.92)


def refine(doc: Any, part: str, rng: random.Random,
           now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    err = _need(part)
    if err:
        return _no(err)
    st = state_of(doc)
    d = st[part]
    if int(d["refined"] or 0):
        return _no(f"本命{part}已炼化（{level_name(part, d['level'])}），无需重复。")
    chance = refine_chance(doc, part, d)
    gain = int(180 + min(len(doc.ext.get("equipment") or {}) * 0.04, 0.24) * 250
               + 0.22 * 180)
    d["tries"] = int(d["tries"] or 0) + 1
    win = float(d["sense"] or 0) >= 1000 or rng.random() < chance
    if not win:
        d["sense"] = min(1000.0, float(d["sense"] or 0) + gain)
        commit(doc, st, part, d)
        return _ok(f"【炼化未成】本命{part}与神魂未能相合（成功率 {chance:.0%}）。\n"
                   f"本命感应 +{gain}（{d['sense']:.0f}/1000，满值必成）｜累计 {d['tries']} 次。")
    d["level"] = 1
    d["refined"] = 1
    d["sense"] = 1000.0
    commit(doc, st, part, d)
    return _ok(f"≡≡≡ 本命{part}·炼化功成 ≡≡≡\n"
               f"【{level_name(part, 1)}】已与你神魂相合，本命感应 1000。\n"
               f"下一步：#淬炼{_quench_cmd(part)} 材料名 攒淬炼值 → #升华本命{_ascend_cmd(part)}")


def _quench_cmd(part: str) -> str:
    return {"武器": "剑身", "护具": "护具", "法宝": "法宝"}[part]


def _ascend_cmd(part: str) -> str:
    return {"武器": "剑", "护具": "护具", "法宝": "法宝"}[part]


# ── 2. 修复 / 温养（BM:1140-1211）───────────────────────────────────────────

def repair(doc: Any, part: str, mat: str, inv: Mapping[str, int],
           rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    if not is_repair(mat):
        return _no(f"【{mat}】不是修复/温养材料。发 #本命材料 看名录。")
    if int(inv.get(mat, 0) or 0) < 1:
        return _no(f"纳戒里没有【{mat}】。")
    st = state_of(doc)
    d = st[part]
    cap = int(d["dura_max"] or 5000)
    if int(d["durability"] or 0) >= cap:
        return _no(f"本命{part}耐久已满（{d['durability']}/{cap}）。")
    *_rest, aff, mood, _q = REPAIR_MATS[mat]
    heal = int(cap * (0.18 + rng.random() * 0.22))
    d["durability"] = min(cap, int(d["durability"] or 0) + heal)
    d["spirit"]["mood"] = min(MOOD_MAX, int(d["spirit"]["mood"] or 0) + mood)
    d["spirit"]["affinity"] = min(AFFINITY_MAX, int(d["spirit"]["affinity"] or 0) + aff)
    commit(doc, st, part, d)
    return _ok(f"【{'温养' if part == '法宝' else '修复'}成功】消耗【{mat}】×1\n"
               f"耐久 +{heal}（{d['durability']}/{cap}）｜器灵心情 +{mood}｜契合 +{aff}",
               {mat: -1})


# ── 3. 淬炼（BM:1224-1355）──────────────────────────────────────────────────

def _omen(rng: random.Random) -> tuple:
    total = sum(x[0] for x in OMENS)
    r = rng.random() * total
    for row in OMENS:
        r -= row[0]
        if r <= 0:
            return row
    return OMENS[0]


def quench(doc: Any, part: str, mat: str, count: int, inv: Mapping[str, int],
           rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    if not is_quench(mat):
        return _no(f"【{mat}】不是淬炼材料。发 #本命材料 看名录。")
    count = max(1, min(int(count or 1), BATCH_MAX))
    if int(inv.get(mat, 0) or 0) < count:
        return _no(f"纳戒里【{mat}】不足 {count} 件（现有 {int(inv.get(mat, 0) or 0)}）。")
    st = state_of(doc)
    d = st[part]
    atk, dfn, hp, rates, qv, law, aff, mood = QUENCH_MATS[mat]
    caps = QUENCH_CAP[part]
    lv = int(d["level"] or 0)
    cap = caps[lv] if lv < len(caps) else caps[-1]
    bias = BIAS[part]
    sm = soul_multiplier(d)
    used, gained, omen_lines = 0, 0, []
    for _ in range(count):
        if int(d["quench"] or 0) >= cap:
            break
        used += 1
        o = _omen(rng)
        mult, law_mult = o[1], o[2]
        if o[4] == "灵火余烬":
            d["embers"] = min(EMBER_MAX, int(d["embers"] or 0) + 1)
        if int(d["embers"] or 0) >= EMBER_MAX and o[4] != "稳火淬炼":
            d["embers"] = 0
            mult, law_mult = max(mult, 2.2), max(law_mult, 1.6)
            omen_lines.append("余烬爆燃")
        if o[4] == "过载淬炼":
            d["dura_max"] = max(1, int(d["dura_max"] or 5000) * 0.96)
            d["spirit"]["mood"] = max(0, int(d["spirit"]["mood"] or 0) - 2)
        add = [atk * bias[0] * mult * sm, dfn * bias[1] * mult * sm,
               hp * bias[2] * mult * sm]
        d["atk"] = float(d["atk"] or 0) + add[0]
        d["def"] = float(d["def"] or 0) + add[1]
        d["hp"] = float(d["hp"] or 0) + add[2]
        # 百分比加成折算成比例成长（BM:933-953 的 1.75×1.6 倍率）
        for i, key in enumerate(("atk", "def", "hp")):
            d[key] = float(d[key]) * (1 + rates[i] * bias[i] * 1.75 * 1.6 * mult * sm)
        _add_law(d, {k: v * law_mult for k, v in law.items()})
        d["quench"] = int(d["quench"] or 0) + int(qv * o[3])
        gained += int(qv * o[3])
        d["spirit"]["affinity"] = min(AFFINITY_MAX, int(d["spirit"]["affinity"] or 0) + aff)
        d["spirit"]["mood"] = min(MOOD_MAX, max(0, int(d["spirit"]["mood"] or 0) + mood))
        omen_lines.append(o[4])
    if used == 0:
        return _no(f"淬炼值已达【{level_name(part, lv)}】上限 {cap:,}，先 #升华本命{_ascend_cmd(part)}。")
    commit(doc, st, part, d)
    nxt = caps[lv] if lv < len(caps) else cap
    from collections import Counter
    summary = "、".join(f"{k}×{v}" for k, v in Counter(omen_lines).items())
    return _ok(f"【淬炼·{level_name(part, lv)}】投入【{mat}】×{used}\n"
               f"异象：{summary}\n"
               f"淬炼值 +{gained:,}（{d['quench']:,}/{nxt:,}）｜"
               f"三维提升至 {int(d['atk']):,}/{int(d['def']):,}/{int(d['hp']):,}\n"
               f"（数值按原版 ÷1000 折算进实际战力）",
               {mat: -used})


# ── 4. 升华（BM:1391-1490）──────────────────────────────────────────────────

def ascend(doc: Any, part: str) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    st = state_of(doc)
    d = st[part]
    lv = int(d["level"] or 0)
    lvls, caps = LEVELS[part], QUENCH_CAP[part]
    if lv >= len(lvls) - 1:
        return _no(f"本命{part}已臻【{lvls[-1]}】，道器圆满。")
    cap = caps[lv]
    if int(d["quench"] or 0) < cap:
        return _no(f"淬炼值不足：{int(d['quench'] or 0):,}/{cap:,}，继续 #淬炼{_quench_cmd(part)}。")
    nxt = lvls[lv + 1]
    if nxt in FINAL_GATE[part] and not complete(d):
        return _no(f"❌ 终境升华条件不足：【{nxt}】需三魂 {CORE_CAP}/{CORE_CAP}、"
                   f"七魄 {AUX_CAP}/{AUX_CAP} 全满（现 {len(d['core'])}/{len(d['aux'])}）。")
    old = lvls[lv]
    # 升华倍数作用于三维（本移植用固定 1.35 倍代替原版逐档表，见 shortcut）
    d["level"] = lv + 1
    for k in ("atk", "def", "hp"):
        d[k] = float(d[k] or 0) * 1.35
    d["dura_max"] = int(d["dura_max"] or 5000) * 1.25
    d["durability"] = int(d["dura_max"])
    d["ult_success"] = 0
    commit(doc, st, part, d)
    return _ok(f"🎉 【升华成功】{old} → {nxt}\n"
               f"三维 ×1.35｜耐久上限 {d['dura_max']:,}（已回满）｜"
               f"下一档淬炼需求 {caps[lv + 1]:,}｜终极强化计数已重置")


# ── 5. 六类镶嵌（BM:1501-1564 / 997-1055）──────────────────────────────────

def _embed_one(doc: Any, part: str, kind: str, mat: str,
               inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    d = state_of(doc)[part]
    pool = CORE_MATS if kind == "core" else AUX_MATS
    slot, cap = (CORE_SLOT[part], CORE_CAP) if kind == "core" else (AUX_SLOT[part], AUX_CAP)
    if mat not in pool:
        return False, f"【{mat}】不是该槽材料", {}
    bag = d["core" if kind == "core" else "aux"]
    if len(bag) >= cap:
        return False, f"{slot}已满 {cap}/{cap}", {}
    if mat in bag:
        return False, f"【{mat}】已镶过（唯一材料）", {}
    if int(inv.get(mat, 0) or 0) < 1:
        return False, f"缺【{mat}】", {}
    atk, dfn, hp, bao, law, _a, _m, _q = pool[mat]
    bias = BIAS[part]
    scale = 0.45 if kind == "core" else 0.24
    sm = soul_multiplier(d)
    d["atk"] = float(d["atk"] or 0) + atk * bias[0] * scale * sm
    d["def"] = float(d["def"] or 0) + dfn * bias[1] * scale * sm
    d["hp"] = float(d["hp"] or 0) + hp * bias[2] * scale * sm
    d["bao"] = float(d["bao"] or 0) + bao * (0.35 if kind == "core" else 0.2)
    _add_law(d, law)
    bag.append(mat)
    # 阶段奖励（BM:847-903）
    extra = []
    if kind == "core" and len(bag) == CORE_CAP:
        d["spirit"]["affinity"] = min(AFFINITY_MAX, int(d["spirit"]["affinity"] or 0) + 45)
        d["sense"] = min(1000.0, float(d["sense"] or 0) + 160)
        _add_law(d, {"五行": 3000, "时空": 2200, "因果": 1200})
        extra.append("三魂成型")
    if kind == "aux" and len(bag) == 4:
        d["spirit"]["mood"] = min(MOOD_MAX, int(d["spirit"]["mood"] or 0) + 12)
        _add_law(d, {"阴阳": 2600, "生命": 3200})
        extra.append("七魄过半")
    if kind == "aux" and len(bag) == AUX_CAP:
        d["spirit"]["affinity"] = min(AFFINITY_MAX, int(d["spirit"]["affinity"] or 0) + 60)
        _add_law(d, {"阴阳": 4000, "因果": 2600, "生命": 4200})
        extra.append("七魄归位")
    if complete(d):
        d["sense"] = 1000.0
        d["spirit"]["affinity"] = min(AFFINITY_MAX, int(d["spirit"]["affinity"] or 0) + 120)
        d["spirit"]["mood"] = MOOD_MAX
        _add_law(d, {"五行": 12000, "阴阳": 12000, "时空": 9000,
                     "因果": 9000, "生命": 12000})
        extra.append("魂魄圆满")
    _refresh_talent(d)
    sp = SPIRIT[part]
    st = state_of(doc)
    st[part] = d
    set_state(doc, st)
    tail = "｜" + "·".join(extra) if extra else ""
    return True, f"成功{part}{slot}镶嵌【{mat}】 {len(bag)}/{cap}{tail}", {mat: -1}


def embed(doc: Any, part: str, kind: str, mat: str,
          inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    ok, msg, delta = _embed_one(doc, part, kind, mat.strip(), inv)
    return (True, f"【{CORE_SLOT[part] if kind == 'core' else AUX_SLOT[part]}镶嵌】{msg}", delta) if ok else _no(msg)


EMBED_TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "本命": tuple((p, k) for p in PARTS for k in ("core", "aux")),
    "本命武器": (("武器", "core"), ("武器", "aux")),
    "本命护具": (("护具", "core"), ("护具", "aux")),
    "本命法宝": (("法宝", "core"), ("法宝", "aux")),
    "剑魂": (("武器", "core"),), "剑魄": (("武器", "aux"),),
    "护灵核心": (("护具", "core"),), "护灵辅魂": (("护具", "aux"),),
    "宝灵灵韵": (("法宝", "core"),), "宝灵灵纹": (("法宝", "aux"),),
}
# 一键镶嵌的材料优先顺序（BM:966-981）
EMBED_PRIORITY = {
    ("武器", "core"): ("太初魂晶", "九霄灵髓", "幽冥月露"),
    ("护具", "core"): ("幽冥月露", "太初魂晶", "九霄灵髓"),
    ("法宝", "core"): ("九霄灵髓", "幽冥月露", "太初魂晶"),
    ("武器", "aux"): tuple(AUX_MATS),
    ("护具", "aux"): ("玄武铁鳞", "麒麟角粉", "建木心屑", "天狼牙砂",
                    "凤凰火羽", "鲲鹏绒羽", "饕餮骨玉"),
    ("法宝", "aux"): ("鲲鹏绒羽", "凤凰火羽", "饕餮骨玉", "天狼牙砂",
                    "玄武铁鳞", "建木心屑", "麒麟角粉"),
}


def embed_all(doc: Any, key: str, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    targets = EMBED_TARGETS.get(key)
    if not targets:
        return _no(f"未知一键镶嵌目标【{key}】。发 #本命帮助 看 10 种写法。")
    st = state_of(doc)
    total, lines, delta = 0, [], {}
    bag = dict(inv)
    for part, kind in targets:
        if not int(st[part]["refined"] or 0):
            continue
        for mat in EMBED_PRIORITY[(part, kind)]:
            if int(bag.get(mat, 0) or 0) <= 0:
                continue
            ok, msg, d = _embed_one(doc, part, kind, mat, bag)
            if ok:
                total += 1
                lines.append(msg)
                for k, v in d.items():
                    delta[k] = delta.get(k, 0) + v
                    bag[k] = int(bag.get(k, 0) or 0) + v
            st = state_of(doc)
    if total == 0:
        return _no(f"【一键镶嵌】{key}：无可镶嵌材料或该器尚未炼化/槽已满。")
    return _ok(f"【一键镶嵌完成】目标：{key}｜成功镶嵌 {total} 个\n" + "\n".join(lines), delta)


# ── 6. 器灵：召唤 / 命名 / 性别 / 状态 / 磨合（BM:1614-1913）────────────────

def summon(doc: Any, part: str, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    st = state_of(doc)
    d = st[part]
    if not complete(d):
        return _no(f"魂魄未圆满：三魂 {len(d['core'])}/{CORE_CAP}、七魄 {len(d['aux'])}/{AUX_CAP}。"
                   f"集齐后方可 #召唤{SPIRIT[part]}。")
    sp = d["spirit"]
    if sp.get("name") and sp.get("gender"):
        return _ok(f"{SPIRIT[part]}【{sp['name']}】已在侧（{sp['gender']}），"
                   f"契合 {sp['affinity']}｜阶段 {stage_of(d)}。")
    sp["personality"] = sp.get("personality") or rng.choice(PERSONALITIES)
    sp["affinity"] = min(AFFINITY_MAX, int(sp["affinity"] or 0) + 80)
    _refresh_talent(d)
    commit(doc, st, part, d)
    if not sp.get("name"):
        return _ok(f"≡≡≡ {SPIRIT[part]}·应召而来 ≡≡≡\n"
                   f"一缕灵识自{level_name(part, d['level'])}中睁开眼，性格【{sp['personality']}】。\n"
                   f"请发 #{SPIRIT[part]}命名 名字（≤{NAME_MAX} 字）")
    return _ok(f"{SPIRIT[part]}已具名【{sp['name']}】，请发 #{SPIRIT[part]}性别 男|女 定其形。")


def name_spirit(doc: Any, part: str, name: str) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX:
        return _no(f"名字需 1~{NAME_MAX} 字。")
    st = state_of(doc)
    d = st[part]
    sp = d["spirit"]
    if not sp.get("personality"):
        return _no(f"请先 #召唤{SPIRIT[part]}。")
    if sp.get("name"):
        return _no(f"{SPIRIT[part]}已命名【{sp['name']}】，不可更改。")
    sp["name"] = name
    commit(doc, st, part, d)
    return _ok(f"命名为【{name}】，请用 #{SPIRIT[part]}性别 男|女 设定性别。")


def set_gender(doc: Any, part: str, gender: str) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    gender = (gender or "").strip()
    if gender not in ("男", "女"):
        return _no("性别只能填 男 / 女。")
    st = state_of(doc)
    d = st[part]
    sp = d["spirit"]
    if not sp.get("name"):
        return _no(f"请先 #{SPIRIT[part]}命名。")
    if sp.get("gender"):
        return _no(f"性别已定为【{sp['gender']}】，不可更改。")
    atk, dfn, hp, law = BIRTH_BONUS[part][gender]
    sp["gender"] = gender
    sp["atk"] = float(sp["atk"] or 0) + atk
    sp["def"] = float(sp["def"] or 0) + dfn
    sp["hp"] = float(sp["hp"] or 0) + hp
    _add_law(d, law)
    _refresh_talent(d)
    commit(doc, st, part, d)
    return _ok(f"性别设定为【{gender}】｜觉醒加成：攻 {atk:,} / 防 {dfn:,} / 血 {hp:,}"
               f"（÷1000 折算入战力）\n"
               f"天赋：【{sp['talent'] or '未醒'}】｜现在可 #{SPIRIT[part]}状态 / #磨合{SPIRIT[part]}")


def stage_of(d: Mapping[str, Any]) -> str:
    a = int(d["spirit"]["affinity"] or 0)
    out = STAGES[0][1]
    for lo, name in STAGES:
        if a >= lo:
            out = name
    return out


def spirit_status(doc: Any, part: str) -> str:
    d = state_of(doc)[part]
    sp = d["spirit"]
    lines = [f"≡≡≡ {SPIRIT[part]}·{level_name(part, d['level'])} ≡≡≡",
             f"姓名：{sp['name'] or '未命名'}｜性别：{sp['gender'] or '未定'}｜性格：{sp['personality'] or '未醒'}",
             f"契合度：{sp['affinity']}/{AFFINITY_MAX}（{stage_of(d)}）｜心情：{sp['mood']}/{MOOD_MAX}",
             f"魂魄：三魂 {len(d['core'])}/{CORE_CAP}（{'、'.join(d['core']) or '空'}）",
             f"　　　七魄 {len(d['aux'])}/{AUX_CAP}（{'、'.join(d['aux']) or '空'}）",
             f"天赋：{sp['talent'] or '未醒'}｜魂魄特性：{'魂魄圆满' if complete(d) else '未满'}",
             f"觉醒加成：攻 {int(sp['atk']):,} / 防 {int(sp['def']):,} / 血 {int(sp['hp']):,}"]
    return "\n".join(lines)


def temper(doc: Any, part: str, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    st = state_of(doc)
    d = st[part]
    sp = d["spirit"]
    if not sp.get("name") or not sp.get("gender"):
        return _no(f"请先 #召唤{SPIRIT[part]} 并完成命名与性别设定。")
    lv = int(d["level"] or 0)
    sm = soul_multiplier(d)
    base = max(10, int(lv * 4 * sm))
    mood = int(sp["mood"] or 0)
    weights = [p * (1.5 if mood > 70 else 0.7 if mood < 30 else 1.0)
               for p, _m, _n in TEMPER_EVENTS]
    r, chosen = rng.random() * sum(weights), TEMPER_EVENTS[0]
    for i, w in enumerate(weights):
        r -= w
        if r <= 0:
            chosen = TEMPER_EVENTS[i]
            break
    _p, mult, title = chosen
    gain = int(base * mult)
    if title == "反噬离心":
        sp["affinity"] = max(0, int(sp["affinity"] or 0) - gain)
        sp["mood"] = max(0, mood - 5)
    else:
        sp["affinity"] = min(AFFINITY_MAX, int(sp["affinity"] or 0) + gain)
        sp["mood"] = min(MOOD_MAX, mood + 2)
        if title == "道顿悟":
            sp["atk"] = float(sp["atk"] or 0) + lv * 30_000_000 * sm
        elif title == "人器合一":
            for k, v in (("atk", 55_000_000), ("def", 42_000_000), ("hp", 65_000_000)):
                sp[k] = float(sp[k] or 0) + lv * v * sm
    commit(doc, st, part, d)
    return _ok(f"【磨合·{title}】契合 {'+' if title != '反噬离心' else '-'}{gain}"
               f"（现 {sp['affinity']}/{AFFINITY_MAX}，{stage_of(d)}）｜心情 {sp['mood']}")


# ── 7. 剑境共鸣 / 形态 / 终极强化 / 器灵对战 ────────────────────────────────

def resonance(doc: Any, part: str, now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    now = time.time() if now is None else now
    st = state_of(doc)
    d = st[part]
    sp = d["spirit"]
    if not sp.get("name") or not sp.get("gender"):
        return _no("器灵尚未具名定形，无法共鸣。")
    if int(sp["affinity"] or 0) < 100:
        return _no(f"契合不足 100（现 {sp['affinity']}），多 #磨合{SPIRIT[part]}。")
    sm = 1 + len(d["core"]) * 0.05 + len(d["aux"]) * 0.025 + (0.35 if complete(d) else 0)
    fit = 1 + int(sp["affinity"] or 0) / 1800
    ratio = RESONANCE_RATIO[part]
    vals = (float(d["atk"] or 0), float(d["def"] or 0), float(d["hp"] or 0))
    bonus = {k: int(v * ratio[i] * sm * fit * (0.1 + int(sp["affinity"] or 0) / 9000))
             for i, (k, v) in enumerate(zip(("atk", "def", "hp"), vals))}
    tname = sp.get("talent")
    if tname and tname in TALENTS:
        for k, m in TALENTS[tname][2].items():
            bonus[k] = int(bonus[k] * m)
    d["resonance"] = bonus
    d["resonance_until"] = now + RESONANCE_SECONDS
    commit(doc, st, part, d)
    return _ok(f"【{'剑' if part == '武器' else '护' if part == '护具' else '宝'}境共鸣成功】\n"
               f"魂魄共鸣 ×{sm:.2f}｜契合共鸣 ×{fit:.2f}｜天赋【{tname or '无'}】\n"
               f"临时三维 +{bonus['atk']:,}/{bonus['def']:,}/{bonus['hp']:,}（1 小时内进战斗乘区）")


def sheath(doc: Any, on: bool) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    d = st["武器"]
    err = _refined(d, "武器")
    if err:
        return _no(err)
    if on and int(d["sheath"] or 0):
        return _no("本命剑已归鞘。发 #化鞘为剑 出鞘。")
    if not on and not int(d["sheath"] or 0):
        return _no("本命剑已在鞘外。发 #化剑为鞘 归鞘。")
    d["sheath"] = 1 if on else 0
    commit(doc, st, "武器", d)
    return _ok("【化剑为鞘】锋芒内敛：攻击 ×0.4、防御 ×1.6（可逆，#化鞘为剑 复原）" if on
               else "【化鞘为剑】锋芒尽出：攻击 ×2.5、防御 ×0.625（可逆，#化剑为鞘 归鞘）")


def ultimate_chance(d: Mapping[str, Any]) -> float:
    return max(0.0, 1 - int(d["level"] or 0) * ULT_DECAY_LEVEL
               - int(d["ult_success"] or 0) * ULT_DECAY_WIN)


def ultimate(doc: Any, key: str, count: int, inv: Mapping[str, int],
             rng: random.Random, now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    row = ULTIMATE.get(key)
    if not row:
        return _no(f"未知强化【{key}】。可用 #引雷淬火 / #玄铁精炼 / #法则滋养。")
    part, mat = row[0], row[1]
    st = state_of(doc)
    d = st[part]
    err = _refined(d, part)
    if err:
        return _no(err)
    count = max(1, min(int(count or 1), BATCH_MAX))
    if int(inv.get(mat, 0) or 0) < count:
        return _no(f"纳戒里【{mat}】不足 {count} 件（现有 {int(inv.get(mat, 0) or 0)}）。")
    bias = BIAS[part]
    sm = soul_multiplier(d)
    win, fail, lines = 0, 0, []
    echo = dict(d["echo"] or {})
    for _ in range(count):
        chance = ultimate_chance(d)
        if rng.random() < chance:
            win += 1
            d["ult_success"] = int(d["ult_success"] or 0) + 1
            for k, v in zip(("atk", "def", "hp"), row[2:5]):
                d[k] = float(d[k] or 0) + v * bias[("atk", "def", "hp").index(k)] * sm
            _add_law(d, row[5])
            d["spirit"]["affinity"] = min(AFFINITY_MAX,
                                          int(d["spirit"]["affinity"] or 0) + row[6])
            lines.append("成")
        else:
            fail += 1
            echo[key] = min(ECHO_MAX, int(echo.get(key, 0) or 0) + 1)
            lines.append("失")
    if int(echo.get(key, 0) or 0) >= ECHO_MAX:
        echo[key] = 0
        for k, v in zip(("atk", "def", "hp"), row[2:5]):
            d[k] = float(d[k] or 0) + v * 2 * sm
        lines.append("天工回响")
    d["echo"] = echo
    commit(doc, st, part, d)
    return _ok(f"【{key}】完成：成功 {win} / 失败 {fail}（消耗【{mat}】×{count}）\n"
               f"异象：{'、'.join(lines)}\n"
               f"当前成功率 {ultimate_chance(d):.0%}｜残响 {int(echo.get(key, 0) or 0)}/{ECHO_MAX}",
               {mat: -count})


def spirit_battle(doc: Any, part: str, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    err = _need(part) or _refined(state_of(doc)[part], part)
    if err:
        return _no(err)
    st = state_of(doc)
    d = st[part]
    sp = d["spirit"]
    if not complete(d) or not sp.get("name") or not sp.get("gender"):
        return _no("需魂魄圆满 + 器灵具名定形方可出战。")
    if int(sp["affinity"] or 0) < 300 or int(sp["mood"] or 0) < 20:
        return _no(f"出战条件：契合≥300、心情≥20（现 {sp['affinity']}/{sp['mood']}）。")
    ours = float(d["atk"] or 0) + float(sp["atk"] or 0)
    sm = soul_multiplier(d)
    log, hp_a, hp_b = [], 1e9, ours * (8 + rng.random() * 6)
    for turn in range(1, 7):
        a = ours * (0.8 + rng.random() * 0.4) * sm
        b = ours * 0.12 * (0.8 + rng.random() * 0.4)
        hp_b -= a
        hp_a -= b
        log.append(f"第{turn}回合：{sp['name']} 斩 {a:,.0f}｜受 {b:,.0f}")
        if hp_b <= 0:
            break
    win = hp_b <= 0 and hp_a > 0
    if win:
        mat = rng.choice(list(ALL_MATS))
        sp["affinity"] = min(AFFINITY_MAX, int(sp["affinity"] or 0) + 30)
        sp["mood"] = min(MOOD_MAX, int(sp["mood"] or 0) + 8)
        commit(doc, st, part, d)
        return _ok(f"≡≡≡ 器灵对战·{sp['name']} 胜 ≡≡≡\n" + "\n".join(log)
                   + f"\n战利品：【{mat}】×1｜契合 +30｜心情 +8", {mat: 1})
    sp["mood"] = max(0, int(sp["mood"] or 0) - 6)
    commit(doc, st, part, d)
    return _ok(f"≡≡≡ 器灵对战·{sp['name']} 未竟全功 ≡≡≡\n" + "\n".join(log)
               + "\n心情 -6，无战利品。")


# ── 8. 消费点：属性聚合 / 战斗 / 投放 / 面板 ────────────────────────────────

def bonus(doc: Any, now: float | None = None) -> tuple[float, float, float, float]:
    """给 equipment.aggregate 的 flat 三维 + bao（已 ÷1000 折算、含化剑为鞘形态）。"""
    now = time.time() if now is None else now
    st = state_of(doc)
    atk = dfn = hp = bao = 0.0
    for part in PARTS:
        d = st[part]
        if not int(d["refined"] or 0):
            continue
        a, f, h = float(d["atk"] or 0), float(d["def"] or 0), float(d["hp"] or 0)
        if part == "武器" and int(d["sheath"] or 0):
            a, f = a * 0.4, f * 1.6
        sp = d["spirit"]
        a += float(sp["atk"] or 0)
        f += float(sp["def"] or 0)
        h += float(sp["hp"] or 0)
        atk += a + float(d["law"] or 0) * LAW_SCALE
        dfn += f + float(d["law"] or 0) * LAW_SCALE
        hp += h + float(d["law"] or 0) * LAW_SCALE
        bao += float(d["bao"] or 0)
        # 共鸣 1 小时内的临时三维（原版写 player.临时攻击 等，本移植并入 flat）
        if float(d["resonance_until"] or 0) > now:
            r = d["resonance"] or {}
            atk += float(r.get("atk", 0) or 0)
            dfn += float(r.get("def", 0) or 0)
            hp += float(r.get("hp", 0) or 0)
    return atk * SCALE, dfn * SCALE, hp * SCALE, bao


def combat(doc: Any, now: float | None = None) -> dict[str, float]:
    """给 build_fighter 的限时乘区：共鸣（1h）+ 天赋。原版共鸣无消费者，本移植补上。"""
    now = time.time() if now is None else now
    out: dict[str, float] = {}
    st = state_of(doc)
    deal, take = 0.0, 0.0
    for part in PARTS:
        d = st[part]
        if float(d["resonance_until"] or 0) <= now:
            continue
        # 按魂魄进度给乘区（不依赖绝对值，避免量级漂移后共鸣失效）
        deal += min(0.30, 0.08 + len(d["core"]) * 0.03 + len(d["aux"]) * 0.015
                    + (0.10 if complete(d) else 0))
        take += min(0.20, 0.04 + len(d["core"]) * 0.015
                    + (0.06 if complete(d) else 0))
        tname = d["spirit"].get("talent")
        if tname and tname in TALENTS:
            m = TALENTS[tname][2]
            deal += max(0.0, float(m.get("atk", 1.0)) - 1) * 0.5
            take += max(0.0, 1 - float(m.get("def", 1.0))) * 0.5
    if deal:
        out["dmg_dealt_mult"] = 1 + min(0.5, deal)
    if take:
        out["dmg_taken_mult"] = max(0.5, 1 - min(0.4, take))
    return out


def roll_drop(rng: random.Random) -> str | None:
    """秘境投放：原版无任何发放点，本移植按 12% 投 1 件随机本命材料。"""
    if rng.random() >= 0.12:
        return None
    return rng.choice(list(ALL_MATS))


def panel(doc: Any, now: float | None = None) -> str:
    now = time.time() if now is None else now
    st = state_of(doc)
    a, f, h, bao = bonus(doc)
    lines = ["≡≡≡ 本命法宝 ≡≡≡",
             f"实际加成（÷1000 折算）：攻 {int(a):,} · 防 {int(f):,} · 血 {int(h):,} · 暴击 +{bao:.1%}"]
    for part in PARTS:
        d = st[part]
        if not int(d["refined"] or 0):
            lines.append(f"【{part}】未炼化 → #炼化本命{part}")
            continue
        lv = int(d["level"] or 0)
        caps = QUENCH_CAP[part]
        cap = caps[lv] if lv < len(caps) else caps[-1]
        left = max(0, float(d["resonance_until"] or 0) - now)
        lines.append(
            f"【{part}·{level_name(part, lv)}】三魂 {len(d['core'])}/{CORE_CAP} "
            f"七魄 {len(d['aux'])}/{AUX_CAP}｜淬炼 {int(d['quench'] or 0):,}/{cap:,}｜"
            f"耐久 {int(d['durability'] or 0):,}/{int(d['dura_max'] or 0):,}")
        reso_txt = ("剩 %d 分钟" % (left / 60)) if left > 0 else "未激活"
        lines.append(f"　三维 {int(d['atk']):,}/{int(d['def']):,}/{int(d['hp']):,}｜"
                     f"法则 {int(d['law'] or 0):,}｜暴击 +{float(d['bao'] or 0):.1%}｜"
                     f"共鸣 {reso_txt}")
        sp = d["spirit"]
        if sp.get("name"):
            lines.append(f"　{SPIRIT[part]}【{sp['name']}】{sp['gender'] or '?'}｜"
                         f"契合 {sp['affinity']}（{stage_of(d)}）｜心情 {sp['mood']}｜"
                         f"天赋 {sp['talent'] or '未醒'}")
    if int(st["武器"]["sheath"] or 0):
        lines.append("形态：化剑为鞘（攻 ×0.4 / 防 ×1.6）")
    lines.append("发 #本命规则 看流程｜#本命材料 看 20 件材料名录")
    return "\n".join(lines)


def materials_text() -> str:
    lines = ["≡≡≡ 本命材料名录（20 件）≡≡≡",
             "获取：秘境探索 12% 随机投放 1 件；器灵对战胜利也可得。"]
    for title, pool in (("三魂核心（3 种 · 唯一 · 上限 3）", CORE_MATS),
                        ("七魄辅材（7 种 · 唯一 · 上限 7）", AUX_MATS),
                        ("淬炼材料（5 种）", QUENCH_MATS),
                        ("修复温养材料（5 种）", REPAIR_MATS)):
        lines.append(f"【{title}】")
        lines.append("　" + "、".join(pool))
    lines.append("终极强化：#引雷淬火(劫火红绒) / #玄铁精炼(木灵胶) / #法则滋养(星尘砂)")
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "≡≡≡ 本命法宝·规则 ≡≡≡",
        "1) 三器独立：武器 / 护具 / 法宝。炼化即生效，无需穿戴；与帝兵、遗珍、先天至宝并存。",
        "2) 炼化：无消耗、无 CD。成功率 22% + 已穿装备 + 双轨境界 + 器性暴击 + 本命感应，"
        "硬顶 92%；失败累积感应，满 1000 必成。",
        "3) 淬炼：消耗淬炼材料（可 *10 批量），攒淬炼值并涨三维；五种异象含过载（扣耐久上限）"
        "与灵火余烬（满 5 触发爆燃）。达当前档上限后不再扣料。",
        "4) 升华：无成功率、无材料。淬炼值达档位需求即 100% 进阶；最后两档需三魂 3/3 + 七魄 7/7。",
        "5) 镶嵌：六类槽（三魂/七魄 等），核心 3 格、辅材 7 格，同名材料唯一。"
        "阶段奖励：三魂成型 / 七魄过半 / 七魄归位 / 魂魄圆满。",
        "6) 器灵：魂魄圆满后 #召唤剑灵 → 命名 → 性别（觉醒实数值）→ 磨合涨契合（7 阶段）"
        "→ 契合≥100 可共鸣（1 小时战斗乘区）；契合≥300 且心情≥20 可出战 6 回合。",
        "7) 形态：仅武器可 #化剑为鞘（攻 ×0.4 / 防 ×1.6）与 #化鞘为剑，可逆、无 CD。",
        "8) 终极强化：成功率 = 1 − 品质档×0.045 − 已成功次数×0.012，升华后重置计数；"
        "失败攒残响，满 4 触发天工回响。",
        "9) 数值按原版 ÷1000 折算；五维法则折算为固定三维。全系统无 CD（与原版一致）。",
    ])


def parse_arg(text: str) -> tuple[str, int]:
    """解析「材料名 *N」/「材料名*N」/「材料名 N」，返回 (材料名, 次数 1~10)。"""
    s = (text or "").strip()
    count = 1
    m = re.search(r"[*×xX](\d+)\s*$", s)
    if m:
        count = max(1, min(int(m.group(1)), BATCH_MAX))
        s = s[:m.start()].strip()
    else:
        m2 = re.search(r"\s+(\d+)\s*$", s)
        if m2:
            count = max(1, min(int(m2.group(1)), BATCH_MAX))
            s = s[:m2.start()].strip()
    return s, count


def parse_embed_key(raw: str) -> str:
    """从 `#一键剑魂镶嵌` 等消息里取出 targetMap 的 key。"""
    s = (raw or "").strip()
    m = re.match(r"^#?一键(.+?)镶嵌$", s)
    return m.group(1) if m else "本命"


def parse_ultimate_key(raw: str) -> tuple[str, int]:
    """从 `#引雷淬火*3` 等消息里取出 (指令名, 次数)。"""
    s = (raw or "").strip().lstrip("#")
    for key in ULTIMATE:
        if s.startswith(key):
            return key, parse_arg(s[len(key):])[1]
    return "引雷淬火", 1


def parse_battle_part(arg: str) -> str | None:
    """从 `剑灵 123` / `剑灵` / `护灵` 里解析部位。"""
    s = (arg or "").strip()
    for part, name in SPIRIT.items():
        if s.startswith(name):
            return part
    for part in PARTS:
        if s.startswith(part):
            return part
    return None


def help_text() -> str:
    return "\n".join([
        "≡≡≡ 本命帮助 ≡≡≡",
        "【入门】#炼化本命武器/护具/法宝 → #淬炼剑身|护具|法宝 材料名 → #升华本命剑|护具|法宝",
        "【修复】#修复爱剑 / #修复护具 / #温养法宝 材料名",
        "【镶嵌】#剑魂镶嵌 #剑魄镶嵌 #护灵核心镶嵌 #护灵辅魂镶嵌 #宝灵灵韵镶嵌 #宝灵灵纹镶嵌",
        "【一键】#一键本命镶嵌（全六槽）；也可 #一键剑魂镶嵌 / #一键宝灵灵纹镶嵌 等 10 种",
        "【器灵】#召唤剑灵/护灵/宝灵 → #剑灵命名 名字 → #剑灵性别 男|女 → #剑灵状态",
        "　　　　#磨合心性（= #磨合剑灵）/ #磨合护灵 / #磨合宝灵",
        "【共鸣】#剑境共鸣 / #护境共鸣 / #宝境共鸣（1 小时进战斗乘区）",
        "【形态】#化剑为鞘 / #化鞘为剑　【强化】#引雷淬火 / #玄铁精炼 / #法则滋养（可 *10）",
        "【对战】#召唤灵体战斗 剑灵|护灵|宝灵　【查询】#本命状态 #本命规则 #本命材料",
    ])
