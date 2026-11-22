"""证道与道伤（W8-B6）——原版 `xiangujinshi.js` / `zhetiandujie.js` /
`zhengdaoRules.js` / `SelfDaoDeduction.js` / `UserHome.js` 的纯函数移植。

三层结构（规划稿把三者混写成「3 指令」，按源码拆开）：
1. **道伤经济**：`player.道伤`（浮点，无硬上限）从渡劫失败 / 花粉渡劫失败 /
   秘境道则 / 天骄一掌累积；唯一有精确每层数值的是 `model/flowerPollenPath.js:539`：
   成功率 -8pp/层（上限 0.4）、悟道 -10%/层（下限 0.5）、属性 -5%/层（下限 0.7）。
   每 10 分钟自然恢复 -0.1（`SecretPlaceTask.js:2512`），本移植用读时惰性结算。
2. **祛伤**：`#道基重塑`（5 五行本源 + 灵石，-1）、`#修复道伤`（8 门功法效率表，
   一次性归零）、雷帝道液（天药 daoshang 字段）、岁云 `#根源波动` / `#月华救赎`、
   `#内景地修炼`（每次成功 -0.1）。
3. **证道**：`#证道成帝`（三路线 + 9 波万道枷锁 + 7 古帝）+ `#证道`（路尽重证）
   + `#冲关 / #冲关极境`（仙古突破）+ `#护法`（1h 护道窗口）。

shortcut:
- 原版成帝是「多阶段战斗制」（9 波雷劫 + 7 位古帝连战，basePower 7.5e8~9.5e8），
  本移植无多阶段战斗引擎，折算为逐波同 rng 判定；难度 ×1.5 只作用于每波成功率。
- 原版 `道伤修复度` 渐进修复、神药/雷池道液全表、天骄待处置/搜魂禁术链、
  己道推演 20 层、祭道 50% 成功率、唯一道之上、因果债时间线均未搬。
- 数值按本移植量级折算：道基重塑灵石 50,000,000→500,000（÷100）、
  修复基数 5,000,000→5,000（÷1000）、成帝修为 8,192,000,000→8,192,000（÷1000）。
- 原版 `天心印记` 是玩家字段 + 时代更替重置；本移植改为全服唯一
  `calamity_state["zhengdao_registry"]["heart_holder"]`，避免同时多位天心合道。
- `#证道成帝` 前置用 `authority_of >= 20` 折算原版准帝九重天（mijing 15）；
  仙道潜力 6 点、悟道道则门、七夜祈愿等前置在本移植无对应体系，改为修为/血气门槛。
- 道伤的 `attr_multiplier` 在本移植作用于**全三维**（原版只作用于花粉属性倍率），
  因为本移植没有「花粉属性」独立乘区；写进 `equipment.aggregate`。
- 护道窗口登记在全服注册表（按 uid），不写目标玩家档，避免跨档并发。
"""

from __future__ import annotations

from .wallet import set_xueqi as _set_xueqi, xueqi as _xueqi

import math
import random
import time
from typing import Any, Mapping

EXT_KEY = "daoshang"

# ---------------------------------------------------------------- 道伤数值（源码原值）
WOUND_CHANCE_STEP = 0.08       # 成功率 -8 个百分点/层
WOUND_CHANCE_CAP = 0.40
WOUND_DAO_STEP = 0.10          # 悟道 -10%/层
WOUND_DAO_FLOOR = 0.50
WOUND_ATTR_STEP = 0.05         # 属性 -5%/层
WOUND_ATTR_FLOOR = 0.70
WOUND_LEVEL_CAP = 5            # 惩罚分级上限（SecretPlaceTask.js:2457）
DECAY_INTERVAL = 600.0         # 每 10 分钟
DECAY_STEP = 0.1               # -0.1

# ---------------------------------------------------------------- 祛伤 / 冲关 / 成帝
RESHAPE_ITEM = "五行本源"
RESHAPE_QTY = 5
RESHAPE_STONES = 500_000
REPAIR_BASE = 5_000
REPAIR_GONGFA: dict[str, float] = {
    "柳神法": 1.0, "不灭经": 1.0, "真凰宝术": 1.0,
    "补天术": 0.7, "者字秘": 0.7,
    "万化圣诀": 0.45,
    "涅槃经": 0.3, "凰劫再生术": 0.3,
}
REALM_CAP = 63                 # 练气境界表 64 阶，顶境「无境」
CHARGE_BASE = 120_000
EXTREME_BLOODS = ("真龙真血", "真凰真血", "朱雀真血")
EXTREME_XUEQI = 1_000_000
PROVE_GATE = 20                # 折算准帝九重天
PROVE_WOUND_GATE = 2.0
PROVE_COST = 8_192_000
PROVE_CD = 24 * 3600
EMPEROR_WAVES = 9
EMPEROR_FOES = 7
GUARD_WINDOW = 3600.0
ROUTE_DIFFICULTY = {"天心合道": 1.0, "凌驾万道": 1.5, "护道成帝": 1.0}
SPECIAL_PHYSIQUES = (
    "大成·荒古圣体", "大成·苍天霸体", "先天圣体道胎", "混沌体", "先天混沌圣体道胎",
)
EMPEROR_SURNAMES = ("叶", "狠", "无", "荒", "辰", "青", "玄", "姬")
EMPEROR_TITLES = ("天帝", "大帝", "圣皇", "道尊")


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, dict(delta or {})


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


def _defaults(now: float = 0.0) -> dict[str, Any]:
    return {
        "wounds": 0.0,
        "repair_progress": 0.0,
        "cannot_prove": False,
        "cannot_zhundi_trib": False,
        "zhengdao_method": "",
        "reached": False,
        "peak_realm": 0,
        "emperor_title": "",
        "power_bonus": 0.0,
        "last_decay_at": now,
        "last_prove_at": 0.0,
        "dao_flaws": 0,
        "break_king_failed_at": 0.0,
        "reshapes": 0,
        "repairs": 0,
        "history": [],
    }


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[EXT_KEY] = dict(st)


def state_of(doc: Any, now: float | None = None) -> dict[str, Any]:
    """读时惰性结算自然恢复（-0.1 / 10 分钟），并保证 ext 子字典存在。"""
    now = time.time() if now is None else float(now)
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = _defaults(now)
    if isinstance(raw, dict):
        st.update(raw)
    st["wounds"] = max(0.0, float(st.get("wounds", 0) or 0))
    st["dao_flaws"] = max(0, int(st.get("dao_flaws", 0) or 0))
    st["break_king_failed_at"] = float(st.get("break_king_failed_at", 0) or 0)
    st["repair_progress"] = max(0.0, float(st.get("repair_progress", 0) or 0))
    st["power_bonus"] = max(0.0, float(st.get("power_bonus", 0) or 0))
    st["last_decay_at"] = float(st.get("last_decay_at", 0) or 0)
    if not isinstance(st.get("history"), list):
        st["history"] = []
    last = st["last_decay_at"]
    if last <= 0 or now < last:
        # 时间倒退（自检/回档/系统时钟）不做恢复，直接对齐，避免误把道伤清光
        st["last_decay_at"] = now
    elif st["wounds"] > 0 and now - last >= DECAY_INTERVAL:
        steps = int((now - last) // DECAY_INTERVAL)
        st["wounds"] = round(max(0.0, st["wounds"] - steps * DECAY_STEP), 3)
        st["last_decay_at"] = last + steps * DECAY_INTERVAL
        if st["wounds"] <= 0:
            st["cannot_prove"] = False
            st["cannot_zhundi_trib"] = False
    save(doc, st)
    return st


def peek(doc: Any) -> float:
    """只读原始道伤值（不写 ext、不结算），供高频聚合调用。"""
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    if not isinstance(raw, dict):
        return 0.0
    return max(0.0, float(raw.get("wounds", 0) or 0))


def effects(doc: Any, now: float | None = None) -> dict[str, float]:
    """三层惩罚（`model/flowerPollenPath.js:539-547`）+ 帝威加成。"""
    st = state_of(doc, now)
    w = st["wounds"]
    return {
        "wounds": w,
        "level": float(min(WOUND_LEVEL_CAP, int(w))),
        "chance_penalty": min(WOUND_CHANCE_CAP, w * WOUND_CHANCE_STEP),
        "dao_multiplier": max(WOUND_DAO_FLOOR, 1 - w * WOUND_DAO_STEP),
        "attr_multiplier": max(WOUND_ATTR_FLOOR, 1 - w * WOUND_ATTR_STEP),
        "power_bonus": st["power_bonus"],
    }


def _log(st: dict[str, Any], reason: str, delta: float, now: float) -> None:
    h = list(st.get("history") or [])
    h.append({"t": int(now), "reason": str(reason), "delta": round(delta, 3),
              "wounds": round(st["wounds"], 3)})
    st["history"] = h[-20:]


def _write_wounds(doc: Any, st: dict[str, Any], value: float, reason: str,
                  delta: float, now: float) -> float:
    st["wounds"] = round(max(0.0, float(value)), 3)
    st["last_decay_at"] = now
    if st["wounds"] <= 0:
        st["repair_progress"] = 0.0
        st["cannot_prove"] = False
        st["cannot_zhundi_trib"] = False
    _log(st, reason, delta, now)
    save(doc, st)
    return st["wounds"]


def add_wounds(doc: Any, amount: float, reason: str, now: float | None = None,
               halve: bool = False) -> float:
    """累积道伤。halve=True 对应岁云「霜华」被动（损失 -50%）。"""
    now = time.time() if now is None else float(now)
    delta = max(0.0, float(amount)) * (0.5 if halve else 1.0)
    if delta <= 0:
        return peek(doc)
    st = state_of(doc, now)
    return _write_wounds(doc, st, st["wounds"] + delta, reason, delta, now)


def heal(doc: Any, amount: float, reason: str, now: float | None = None) -> float:
    """祛除道伤，返回剩余值。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    before = st["wounds"]
    delta = min(before, max(0.0, float(amount)))
    if delta <= 0:
        return before
    return _write_wounds(doc, st, before - delta, reason, -delta, now)


def clear(doc: Any, reason: str, now: float | None = None) -> float:
    return heal(doc, 1e9, reason, now)


def use_supreme_divine_item(doc: Any, now: float | None = None) -> tuple[bool, str]:
    """Repair one failed emperor-proof flaw and release its 24-hour retry lock."""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    cooling = (st["break_king_failed_at"] > 0
               and now - st["last_prove_at"] < PROVE_CD)
    if st["dao_flaws"] <= 0 and not cooling:
        return False, "道基无瑕且帝劫余波已散，无需使用无上神物。"
    if st["dao_flaws"] > 0:
        st["dao_flaws"] -= 1
        save(doc, st)
        heal(doc, 1.0, "无上神物·弥合道基", now)
        st = state_of(doc, now)
    lines = ["【无上神物·道基重铸】"]
    if cooling:
        st["last_prove_at"] = now - PROVE_CD
        st["break_king_failed_at"] = 0.0
        lines.append("帝劫修养冷却已解除，可再次证道。")
    lines.append(f"道果瑕疵：修复后剩余 {st['dao_flaws']} 处。")
    save(doc, st)
    return True, "\n".join(lines)


def power_bonus(doc: Any) -> float:
    """证道成功累积的三维/增伤加成（战斗注入用）。"""
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    if not isinstance(raw, dict):
        return 0.0
    return min(3.0, max(0.0, float(raw.get("power_bonus", 0) or 0)))


# ---------------------------------------------------------------- 全服注册表（天心印记 / 帝榜 / 护道）

def registry_of(calamity: Mapping[str, Any]) -> dict[str, Any]:
    r = calamity.get("zhengdao_registry")
    out = dict(r) if isinstance(r, dict) else {}
    out.setdefault("heart_holder", "")
    out.setdefault("emperors", [])
    out.setdefault("guards", {})
    if not isinstance(out["emperors"], list):
        out["emperors"] = []
    if not isinstance(out["guards"], dict):
        out["guards"] = {}
    return out


def guard_left(reg: Mapping[str, Any], uid: str, now: float) -> float:
    return max(0.0, float((reg.get("guards") or {}).get(str(uid), 0) or 0) - now)


def guard(reg: dict[str, Any], uid: str, target: str, now: float) -> tuple[bool, str]:
    if not target:
        return False, "需 @ 一位道友为其护道（#护法 @目标）。"
    g = dict(reg.get("guards") or {})
    g[str(target)] = now + GUARD_WINDOW
    reg["guards"] = g
    return True, (f"【护法】{target} 的护道法阵已立，1 小时内若天心印记已被他人占据，"
                  f"仍可走「护道成帝」路线证道。")


def unguard(reg: dict[str, Any], uid: str, target: str) -> tuple[bool, str]:
    g = dict(reg.get("guards") or {})
    key = str(target or uid)
    if key not in g:
        return False, "当前没有可解除的护道法阵。"
    g.pop(key, None)
    reg["guards"] = g
    return True, f"【解除护法】{key} 的护道法阵已散去。"


# ---------------------------------------------------------------- 面板 / 规则

def rules_text() -> str:
    return "\n".join([
        "--- 道伤规则 ---",
        "【累积】渡劫失败 +1｜花粉渡劫失败 +1（岁云霜华减半）｜秘境道则 +1｜天骄一掌 +1",
        "【自然恢复】每 10 分钟 -0.1（读档时结算）",
        f"【惩罚】成功率 -{WOUND_CHANCE_STEP:.0%}/层（上限 {WOUND_CHANCE_CAP:.0%}）｜"
        f"悟道 -{WOUND_DAO_STEP:.0%}/层（下限 {WOUND_DAO_FLOOR:.0%}）｜"
        f"三维 -{WOUND_ATTR_STEP:.0%}/层（下限 {WOUND_ATTR_FLOOR:.0%}）",
        "【硬门槛】道伤 ≥2 禁证道成帝｜≥3 禁渡无妄真劫｜>0 禁开创大道",
        "【祛伤】#道基重塑（-1）｜#修复道伤（归零）｜雷帝道液（-1/枚）｜"
        "#根源波动 / #月华救赎（归零）｜#内景地修炼（每次成功 -0.1）",
        "【证道】#证道成帝（三路线）→ #证道（路尽重证）｜#冲关 / #冲关极境｜#护法 @目标",
    ])


def heart_panel(doc: Any, reg: Mapping[str, Any], now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    holder = str(reg.get("heart_holder") or "")
    emperors = list(reg.get("emperors") or [])
    lines = [
        "--- 天心印记 · 帝榜 ---",
        f"当前天心印记：{('【' + holder + '】执掌' if holder else '无主（可走天心合道）')}",
        f"历代证道者：{len(emperors)} 位",
    ]
    for i, e in enumerate(reversed(emperors[-8:]), 1):
        if isinstance(e, dict):
            lines.append(f"{i}. {e.get('name') or e.get('uid')}｜{e.get('title', '')}"
                         f"｜{e.get('method', '')}")
    mine = [e for e in emperors if isinstance(e, dict) and e.get("uid") == getattr(doc, "uid", "")]
    lines.append(f"你的证道记录：{len(mine)} 次"
                 + (f"，帝号【{mine[-1].get('title', '')}】" if mine else ""))
    left = guard_left(reg, getattr(doc, "uid", ""), now)
    lines.append(f"你的护道窗口：{'剩余 ' + str(int(left // 60)) + ' 分钟' if left else '无'}")
    return "\n".join(lines)


def panel(doc: Any, reg: Mapping[str, Any] | None = None,
          now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    e = effects(doc, now)
    w = st["wounds"]
    r = registry_of(reg or {})
    retry_left = max(0, int(PROVE_CD - (now - float(st.get("last_prove_at", 0) or 0))))
    lines = [
        "--- 道伤 · 证道 ---",
        f"道伤：{w:.1f}（惩罚 {int(e['level'])}/{WOUND_LEVEL_CAP} 级）｜自然恢复 -{DECAY_STEP}/10 分钟",
        f"成功率 -{e['chance_penalty']:.0%}｜悟道 ×{e['dao_multiplier']:.2f}｜三维 ×{e['attr_multiplier']:.2f}",
        f"证道方式：{st['zhengdao_method'] or '未证道'}｜帝号：{st['emperor_title'] or '无'}",
        f"道果瑕疵：{st['dao_flaws']} 处｜帝劫修养：{retry_left // 3600} 小时 {retry_left % 3600 // 60} 分",
        f"帝威加成：+{st['power_bonus']:.0%}（战斗增伤）｜历史峰值：第 {int(st['peak_realm']) + 1} 境",
        f"已重塑 {int(st['reshapes'])} 次｜已修复 {int(st['repairs'])} 次",
        f"禁证道：{'是' if st['cannot_prove'] else '否'}｜禁准帝劫：{'是' if st['cannot_zhundi_trib'] else '否'}",
        f"天心印记：{('【' + str(r['heart_holder']) + '】执掌' if r['heart_holder'] else '无主')}",
        "近况：" + ("；".join(
            f"{h.get('reason', '')}{h.get('delta', 0):+g}→{h.get('wounds', 0):g}"
            for h in list(st.get("history") or [])[-4:]) or "道基完好"),
        "祛伤：#道基重塑 / #修复道伤 / 雷帝道液｜规则：#道伤规则｜帝榜：#天心印记",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 祛伤指令

def reshape(doc: Any, inv: Mapping[str, int], now: float | None = None,
            ) -> tuple[bool, str, dict[str, int]]:
    """#道基重塑：5 枚五行本源 + 灵石，道伤 -1（xiangujinshi.js:108-135）。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    if st["wounds"] <= 0:
        return _no("你的道基稳固无伤，无需重塑。（当前道伤为 0）")
    have = int((inv or {}).get(RESHAPE_ITEM, 0) or 0)
    if have < RESHAPE_QTY:
        return _no(f"道基重塑需【{RESHAPE_ITEM}】×{RESHAPE_QTY}（现有 {have}），"
                   "九天十地·五行州可得。")
    if int(getattr(doc, "stones", 0) or 0) < RESHAPE_STONES:
        return _no(f"道基重塑需灵石 {RESHAPE_STONES:,}（现有 {int(getattr(doc, 'stones', 0) or 0):,}）。")
    doc.stones = int(getattr(doc, "stones", 0) or 0) - RESHAPE_STONES
    left = _write_wounds(doc, st, st["wounds"] - 1.0, "道基重塑", -1.0, now)
    st = state_of(doc, now)
    st["reshapes"] = int(st["reshapes"]) + 1
    save(doc, st)
    return _ok(f"【道基重塑】以 5 枚【{RESHAPE_ITEM}】为薪柴，五行流转，道基弥合——\n"
               f"道伤 -1（当前 {left:.1f}）｜消耗灵石 {RESHAPE_STONES:,}",
               {RESHAPE_ITEM: -RESHAPE_QTY})


def repair_cost(doc: Any, w: float, eff: float) -> int:
    """原版 `UserHome.js:439`：Σ(四轨等级)×基数×(1+道伤×0.5)÷功法效率。"""
    lv = int(getattr(doc, "realm_index", 0) or 0) + int(getattr(doc, "physique_index", 0) or 0) + 2
    return max(1, math.ceil(lv * REPAIR_BASE * (1 + max(0.0, w) * 0.5) / max(0.01, eff)))


def repair_efficiency(doc: Any) -> tuple[float, str]:
    learned = {str(x) for x in ((getattr(doc, "ext", {}) or {}).get("gongfa") or [])}
    best, name = 0.0, ""
    for g, v in REPAIR_GONGFA.items():
        if g in learned and v > best:
            best, name = v, g
    return best, name


def repair(doc: Any, now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    """#修复道伤：8 门功法取最强效率，一次性归零（UserHome.js:383-555）。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    if st["wounds"] <= 0:
        return _no("道基无伤，无需修复。")
    eff, gname = repair_efficiency(doc)
    if eff <= 0:
        return _no("修复道伤需习得八门疗伤功法之一："
                   + "、".join(REPAIR_GONGFA) + "。")
    need = repair_cost(doc, st["wounds"], eff)
    if int(getattr(doc, "exp", 0) or 0) < need or _xueqi(doc) < need:
        return _no(f"以《{gname}》修复（效率 {eff:.0%}）需修为与血气各 {need:,}，"
                   f"当前 {int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}。")
    doc.exp = int(getattr(doc, "exp", 0) or 0) - need
    _set_xueqi(doc, _xueqi(doc) - need)
    _write_wounds(doc, st, 0.0, f"修复道伤·{gname}", -st["wounds"], now)
    st = state_of(doc, now)
    st["repairs"] = int(st["repairs"]) + 1
    save(doc, st)
    return _ok(f"【修复道伤】以《{gname}》（效率 {eff:.0%}）逆转岁月、补全道基——\n"
               f"道伤归零，禁证道/禁准帝劫一并解除｜消耗修为与血气各 {need:,}")


# ---------------------------------------------------------------- 冲关（仙古）

def charge(doc: Any, inv: Mapping[str, int], now: float | None = None,
           rng: random.Random | None = None, extreme: bool = False
           ) -> tuple[bool, str, dict[str, int]]:
    """#冲关 / #冲关极境：消耗修为血气冲境，失败累积道伤。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc, now)
    cur = int(getattr(doc, "realm_index", 0) or 0)
    step = 2 if extreme else 1
    if cur >= REALM_CAP:
        return _no("已至【无境】，诸天再无可冲之关。")
    cost = int(CHARGE_BASE * (cur + 1) * (3 if extreme else 1))
    delta: dict[str, int] = {}
    if extreme:
        missing = [b for b in EXTREME_BLOODS if int((inv or {}).get(b, 0) or 0) < 1]
        if missing:
            return _no("极境冲关需三种太古遗种真血各 1 份，尚缺：" + "、".join(missing) + "。")
        if _xueqi(doc) < EXTREME_XUEQI:
            return _no(f"极境冲关需血气 ≥{EXTREME_XUEQI:,}（当前 {_xueqi(doc):,}）。")
        for b in EXTREME_BLOODS:
            delta[b] = -1
    if int(getattr(doc, "exp", 0) or 0) < cost or _xueqi(doc) < cost:
        return _no(f"冲关需修为与血气各 {cost:,}（当前 "
                   f"{int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}）。")
    doc.exp = int(getattr(doc, "exp", 0) or 0) - cost
    _set_xueqi(doc, _xueqi(doc) - cost)
    e = effects(doc, now)
    base = 0.45 if extreme else 0.70
    chance = max(0.10, base - e["chance_penalty"] * 0.5)
    won = rng.random() < chance
    if won:
        doc.realm_index = min(REALM_CAP, cur + step)
        st["peak_realm"] = max(int(st["peak_realm"] or 0), int(doc.realm_index))
        save(doc, st)
        gain = int(cost * 0.5)
        doc.exp += gain
        return _ok(f"【{'极境' if extreme else '仙古'}冲关成功】连破 {step} 境，"
                   f"现第 {int(doc.realm_index) + 1} 境！\n"
                   f"成功率 {chance:.0%}｜消耗修为与血气各 {cost:,}，天道回赠修为 {gain:,}", delta)
    add_wounds(doc, 2.0 if extreme else 1.0,
               "极境冲关失守" if extreme else "仙古冲关失守", now,
               halve=frost_active(doc))
    return _ok(f"【{'极境' if extreme else '仙古'}冲关失利】道基震动，境界未动（成功率 {chance:.0%}）。\n"
               f"消耗修为与血气各 {cost:,}｜道伤 +{2 if extreme else 1}"
               "（岁云霜华可减半）", delta)


# ---------------------------------------------------------------- 岁云「霜华」被动（局部导入避免包级环）

def frost_active(doc: Any) -> bool:
    try:
        from . import suiyun as _sy
        st = _sy.state_of(doc)
        return bool(st) and len(st.get("seals") or {}) >= len(_sy.SEALS)
    except Exception:
        return False


# ---------------------------------------------------------------- 证道成帝（三路线）

def resolve_route(doc: Any, reg: Mapping[str, Any], now: float) -> str:
    """`zhengdaoRules.js`：无印记→天心合道；有印记+特殊体质→凌驾万道；
    有印记+护道窗口→护道成帝；其余→帝路断绝。"""
    holder = str(reg.get("heart_holder") or "")
    if not holder:
        return "天心合道"
    lg = (getattr(doc, "ext", {}) or {}).get("linggen")
    name = str(lg.get("name") or "") if isinstance(lg, dict) else ""
    if name in SPECIAL_PHYSIQUES:
        return "凌驾万道"
    if guard_left(reg, getattr(doc, "uid", ""), now) > 0:
        return "护道成帝"
    return "帝路断绝"


def prove(doc: Any, reg: dict[str, Any], now: float | None = None,
          rng: random.Random | None = None) -> tuple[bool, str, dict[str, int], dict[str, Any]]:
    """#证道成帝：9 波万道枷锁 + 7 位古帝意志，全过方成。返回 (ok,msg,delta,reg)。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc, now)
    try:
        from . import authority as _auth
        power = _auth.authority_of(doc)
    except Exception:
        power = max(int(getattr(doc, "realm_index", 0) or 0),
                    int(getattr(doc, "physique_index", 0) or 0))
    if power < PROVE_GATE:
        return *_no(f"证道需权柄 ≥{PROVE_GATE}（准帝九重天），当前 {power}。"), reg
    if st["wounds"] >= PROVE_WOUND_GATE:
        return *_no(f"身负道伤 {st['wounds']:.1f} ≥{PROVE_WOUND_GATE:.0f}，"
                    "帝路已断——先 #修复道伤 / #道基重塑。"), reg
    if st["dao_flaws"] > 0:
        return *_no(f"道果尚有 {st['dao_flaws']} 处瑕疵，帝路未通；可用无上神物修复。"), reg
    if st.get("cannot_prove"):
        return *_no("你的证道资格已被剥夺（#月华救赎 / #根源波动 可解除）。"), reg
    left = PROVE_CD - (now - float(st.get("last_prove_at", 0) or 0))
    if left > 0:
        return *_no(f"帝路余波未平，还需 {left / 3600:.1f} 小时方可再证。"), reg
    route = resolve_route(doc, reg, now)
    if route == "帝路断绝":
        return *_no("【天心印记·帝路断绝】当世已有天心印记执掌者，你既非五大特殊体质，"
                    "又无道友护道——请 #护法 @道友 为你立下 1 小时护道法阵，"
                    "或待印记易主。"), reg
    if int(getattr(doc, "exp", 0) or 0) < PROVE_COST or _xueqi(doc) < PROVE_COST:
        return *_no(f"证道需修为与血气各 {PROVE_COST:,}（当前 "
                    f"{int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}）。"), reg
    doc.exp = int(getattr(doc, "exp", 0) or 0) - PROVE_COST
    _set_xueqi(doc, _xueqi(doc) - PROVE_COST)
    mult = ROUTE_DIFFICULTY[route]
    chance = max(0.12, 0.62 / mult)
    waves = 0
    for _ in range(EMPEROR_WAVES):
        if rng.random() >= chance:
            break
        waves += 1
    foes = 0
    if waves == EMPEROR_WAVES:
        for _ in range(EMPEROR_FOES):
            if rng.random() >= chance * 0.9:
                break
            foes += 1
    won = waves == EMPEROR_WAVES and foes == EMPEROR_FOES
    if not won:
        add_wounds(doc, 2.0, "大帝意志劫失败", now, halve=frost_active(doc))
        st = state_of(doc, now)
        st["dao_flaws"] += 1
        st["break_king_failed_at"] = now
        st["last_prove_at"] = now
        save(doc, st)
        doc.exp = int(doc.exp * 0.6)
        _set_xueqi(doc, int(_xueqi(doc) * 0.6))
        return *_ok(f"【证道·{route}】万道枷锁渡过 {waves}/{EMPEROR_WAVES} 波、"
                    f"古帝意志胜 {foes}/{EMPEROR_FOES} 位（单波 {chance:.0%}，难度 ×{mult:g}）。\n"
                    "道基受损，修为与血气再损 40%｜道伤 +2（霜华减半）｜"
                    "道果瑕疵 +1｜需修养 24 小时，或使用无上神物修复后再战。"), reg
    title = (rng.choice(EMPEROR_SURNAMES) + rng.choice(EMPEROR_TITLES))
    _write_wounds(doc, st, 0.0, "证道成帝", -st["wounds"], now)
    st = state_of(doc, now)
    st["break_king_failed_at"] = 0.0
    st["dao_flaws"] = 0
    st["reached"] = True
    st["zhengdao_method"] = route
    st["emperor_title"] = title
    st["peak_realm"] = max(int(st["peak_realm"] or 0), int(getattr(doc, "realm_index", 0) or 0))
    st["power_bonus"] = round(min(3.0, st["power_bonus"] + 0.8), 3)
    st["last_prove_at"] = now
    save(doc, st)
    r = registry_of(reg)
    if route == "天心合道":
        r["heart_holder"] = str(getattr(doc, "uid", "") or "")
    else:
        r["heart_holder"] = ""
    emperors = list(r["emperors"])
    emperors.append({"uid": str(getattr(doc, "uid", "") or ""),
                     "name": str(getattr(doc, "name", "") or ""),
                     "title": title, "method": route, "ts": int(now)})
    r["emperors"] = emperors[-30:]
    g = dict(r.get("guards") or {})
    g.pop(str(getattr(doc, "uid", "") or ""), None)
    r["guards"] = g
    return *_ok(f"≡≡≡ 证道成功 · {route} ≡≡≡\n"
                f"9 波万道枷锁尽碎，7 位古帝意志俯首（难度 ×{mult:g}）。\n"
                f"帝号【{title}】｜道伤尽消｜帝威 +80%（战斗增伤）｜"
                f"天心印记：{'归于你手' if route == '天心合道' else '碎散'}。\n"
                "此后可 #证道 重证路尽，或 #冲关 再进一境。"), r


def reprove(doc: Any, now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    """#证道：路尽级仙帝跌落重证（SelfDaoDeduction.js:112-150）。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    if not st.get("reached"):
        return _no("你尚未证得仙帝道果，无从重证（先 #证道成帝）。")
    left = PROVE_CD - (now - float(st.get("last_prove_at", 0) or 0))
    if left > 0:
        return _no(f"道果余韵未散，还需 {left / 3600:.1f} 小时方可重证。")
    peak = int(st["peak_realm"] or getattr(doc, "realm_index", 0) or 0)
    before = int(getattr(doc, "realm_index", 0) or 0)
    doc.exp = 0
    _set_xueqi(doc, 0)
    if before < peak:
        doc.realm_index = peak
    _write_wounds(doc, st, 0.0, "路尽重证", -st["wounds"], now)
    st = state_of(doc, now)
    st["power_bonus"] = round(min(3.0, st["power_bonus"] + 0.2), 3)
    st["last_prove_at"] = now
    save(doc, st)
    back = f"境界自第 {before + 1} 境重登第 {int(doc.realm_index) + 1} 境" if before < peak else "境界未跌，道果再淬"
    return _ok(f"【路尽重证】昔日仙帝道果再现，万道同俯——{back}。\n"
               "修为、血气已清空，元神/心神/寿元/道伤尽数复归；帝威再 +20%。")
