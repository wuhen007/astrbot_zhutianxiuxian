"""体质进阶（W12-F1/F2）——原版 `model/zhetianPhysiquePath.js` +
`apps/User/linggenjuexing.js`（太阳/太阴/神王两阶段）、`apps/User/lunhui.js`
（九转轮回体）+ `UserHome.js` L4717/6732（命运神道体 / 光阴三品）+
`apps/motou/motou.js`（极道天魔）的纯函数移植。
至尊线（斩骨/试炼/仙骨/重瞳/瞳骨合一）已在 `core/supreme.py`，不重复。

本移植（shortcut）：
- 两阶段觉醒折算权柄门槛 8/15（原秘境 7/15）；觉醒改写 ext["linggen"] 快照
  （灵根名 + 三维乘数 + eff），base 属性由 handler 调 `linggen.sync_stats`
  按内容表重算；材料：真经为已学功法，神枝/地命果为道具。
- 九转轮回同步化：每转一次判定（成功率 90%），失败寿元 -500 + 道伤 +1；
  转生重置等级等原版惩罚未搬。轮回点由【奇怪的石头】供奉。
- #消耗轮回道果 → 命运神道体（eff 1.75）；武祖权柄进阶未搬。
- 光阴三品：命运神道体/极道天魔可用，每枚三维 +9,000（原 9,000 万 ÷1000），
  总量上限 90,000（原 9 亿 ÷1000），直接写入灵根快照三维。
- 极道天魔：九重魔功（ext.evil.magic ≥9）+【邪神道果】→ 灵根改名（eff 2.0）。
- 神石小玩法（供奉神石/踏入神界/参悟神石/敲开石头）未搬。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .wallet import authority as _authority
from .player import PlayerDoc

EXT_KEY = "physique"

LIGHT_STEP = 9_000            # 原 9,000 万 ÷1000
LIGHT_CAP = 90_000            # 原 9 亿 ÷1000
SAMSARA_MAX = 9
SAMSARA_CHANCE = 0.90
SAMSARA_EFF = {1: 0.45, 2: 0.50, 3: 0.55, 4: 0.60, 5: 0.62, 6: 0.65,
               7: 0.60, 8: 0.65, 9: 1.00}
SAMSARA_EFF[9] = 1.00

# 阶段表：key → (阶段, 灵根名, 三维乘数, eff, 权柄门槛, 需已学功法, 需道具)
SUN_PATH = {
    1: ("太阳神体", 2.0, 1.10, 8, ("太阳真经",), ("扶桑神枝",)),
    2: ("太阳圣皇体", 3.5, 1.25, 15, ("太阳真经·仙台卷", "大日涅槃诀"), ()),
}
MOON_PATH = {
    1: ("太阴神体", 2.0, 1.10, 8, ("太阴真经",), ("地命果",)),
    2: ("太阴圣皇体", 3.5, 1.25, 15, ("太阴真经·仙台卷",), ()),
}
KING_PATH = {
    1: ("神王体·小成", 1.5, 1.05, 8, (), ()),
    2: ("神王体·大成", 2.5, 1.20, 15, ("斗字秘",), ()),
}


def _defaults() -> dict[str, Any]:
    return {"sun": 0, "moon": 0, "king": 0, "samsara": 0, "points": 0,
            "fortune": False, "demon": False, "light_total": 0}


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[EXT_KEY] = dict(st)


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = _defaults()
    if isinstance(raw, dict):
        st.update(raw)
    for k in ("sun", "moon", "king", "samsara", "points", "light_total"):
        st[k] = int(st.get(k, 0) or 0)
    st["fortune"] = bool(st.get("fortune"))
    st["demon"] = bool(st.get("demon"))
    save(doc, st)
    return st


def _lg(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    lg = ext.get("linggen") if isinstance(ext, dict) else None
    return lg if isinstance(lg, dict) else {}


def _learned(doc: Any) -> set[str]:
    return {str(x) for x in ((getattr(doc, "ext", {}) or {}).get("gongfa") or [])}


def _rename(doc: Any, name: str, mult: float, eff: float | None = None) -> str:
    lg = _lg(doc)
    old = str(lg.get("name") or "")
    lg["name"] = name
    if mult != 1.0:
        for k in ("atk", "def", "hp"):
            lg[k] = round(float(lg.get(k, 0) or 0) * mult, 3)
    if eff is not None:
        lg["eff"] = float(eff)
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["linggen"] = lg
    return old


def _generic_awaken(doc: PlayerDoc, path: Mapping[int, tuple], stage_key: str,
                    label: str, inv: Mapping[str, int],
                    now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    cur = int(st[stage_key])
    nxt = cur + 1
    if nxt not in path:
        return False, f"【{label}】已至最终形态（{path[max(path)][0]}）。", {}
    name, mult, eff, gate, gongfas, items = path[nxt]
    lg = _lg(doc)
    base = label.replace("体觉醒", "之体")
    if base not in str(lg.get("name") or "") and not str(lg.get("name") or "").startswith(label[:2]):
        return False, f"你并非{base}血脉，无法走{label}之路。", {}
    if _authority(doc) < gate:
        return False, f"【{label}·第{nxt}阶】需权柄 ≥{gate}，当前 {_authority(doc)}。", {}
    missing_g = [g for g in gongfas if g not in _learned(doc)]
    if missing_g:
        return False, f"需先参悟：{'、'.join(missing_g)}（#学习 功法名）。", {}
    delta: dict[str, int] = {}
    missing_i = []
    for it in items:
        if int((inv or {}).get(it, 0) or 0) < 1:
            missing_i.append(it)
        else:
            delta[it] = -1
    if missing_i:
        return False, f"觉醒材料不足，尚缺：{'、'.join(missing_i)}（#哪里有 {missing_i[0]}）。", {}
    old = _rename(doc, name, mult, eff)
    st[stage_key] = nxt
    save(doc, st)
    return True, (f"≡≡≡ {label}觉醒 ≡≡≡\n{old} → 【{name}】！\n"
                  f"三维 ×{mult:g}｜eff ×{eff:g}"
                  + (f"｜消耗 {'、'.join(items)}" if items else "")
                  + "｜属性面板以 #我的灵根 复核（sync_stats 已由系统刷新）"), delta


def awaken_sun(doc: PlayerDoc, inv: Mapping[str, int], now: float | None = None,
               ) -> tuple[bool, str, dict[str, int]]:
    return _generic_awaken(doc, SUN_PATH, "sun", "太阳体", inv, now)


def awaken_moon(doc: PlayerDoc, inv: Mapping[str, int], now: float | None = None,
                ) -> tuple[bool, str, dict[str, int]]:
    return _generic_awaken(doc, MOON_PATH, "moon", "太阴体", inv, now)


def awaken_king(doc: PlayerDoc, inv: Mapping[str, int], now: float | None = None,
                ) -> tuple[bool, str, dict[str, int]]:
    return _generic_awaken(doc, KING_PATH, "king", "神王体", inv, now)


# ---------------------------------------------------------------- 九转轮回

def offer_stone(doc: Any, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    """#供奉奇怪的石头：轮回点 +1。"""
    if int((inv or {}).get("奇怪的石头", 0) or 0) < 1:
        return False, "你并没有【奇怪的石头】——何处机缘见得，供奉便是轮回之资。", {}
    st = state_of(doc)
    st["points"] = int(st["points"]) + 1
    save(doc, st)
    return True, f"【供奉】轮回碑上又亮一盏灯——轮回点 {st['points']}。", {"奇怪的石头": -1}


def reincarnate(doc: PlayerDoc, now: float | None = None,
                rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#轮回：九转轮回体逐转（成仙后；失败寿元 -500 + 道伤 +1）。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    if st["samsara"] >= SAMSARA_MAX:
        return False, "九转已满——生死簿上你的名字早已划去。", {}
    if int(getattr(doc, "realm_index", 0) or 0) < 41:
        return False, "轮回之门只为仙人而开（登仙后方可 #轮回）。", {}
    if st["points"] < 1:
        return False, "轮回点不足——#供奉奇怪的石头。", {}
    shouyuan = int(float((getattr(doc, "ext", {}) or {}).get("shouyuan", 0) or 0))
    if shouyuan <= 500:
        return False, "轮回一转需燃烧 500 年寿元（现有不足）——先延寿。"
    n = st["samsara"] + 1
    if rng.random() >= SAMSARA_CHANCE:
        ext = getattr(doc, "ext", {})
        from .lifespan import spend as spend_lifespan
        spend_lifespan(doc, 500)
        st["points"] = int(st["points"]) - 1
        save(doc, st)
        try:
            from . import zhengdao as _dz
            _dz.add_wounds(doc, 1.0, "轮回失败", now)
        except Exception:
            pass
        return True, (f"【轮回 · 第 {n} 转】轮回通道崩碎一角——寿元 -500 年、"
                      f"道伤 +1，轮回点已耗。"), {}
    st["points"] = int(st["points"]) - 1
    st["samsara"] = n
    save(doc, st)
    _rename(doc, f"九转轮回体·{n}转", 1.0, SAMSARA_EFF.get(n, 0.5))
    tail = "九转功成！生死已超脱，可 #消耗轮回道果 问鼎命运。" if n == SAMSARA_MAX else ""
    return True, (f"≡≡≡ 轮回 · 第 {n} 转 ≡≡≡\n"
                  f"灵根蜕变为【九转轮回体·{n}转】（eff ×{SAMSARA_EFF.get(n, 0.5):g}）"
                  f"｜寿元 -500 年。{tail}"), {}


def consume_samsara_fruit(doc: Any, inv: Mapping[str, int],
                          ) -> tuple[bool, str, dict[str, int]]:
    """#消耗轮回道果：九转轮回体 → 命运神道体。"""
    st = state_of(doc)
    if st["samsara"] < SAMSARA_MAX:
        return False, "唯有九转轮回体可吞【轮回道果】。", {}
    if st.get("fortune"):
        return False, "你已是【命运神道体】——因果在握，何须再吞。", {}
    if int((inv or {}).get("轮回道果", 0) or 0) < 1:
        return False, "你并没有【轮回道果】。", {}
    _rename(doc, "命运神道体", 1.0, 1.75)
    st["fortune"] = True
    save(doc, st)
    return True, ("≡≡≡ 命运神道体 ≡≡≡\n因果线在你眼中纤毫毕现——"
                  "eff ×1.75，#消耗光阴火/光阴石/光阴水 已解封。"), {"轮回道果": -1}


def consume_light(doc: Any, kind: str, inv: Mapping[str, int],
                  ) -> tuple[bool, str, dict[str, int]]:
    """#消耗光阴火/光阴石/光阴水：三维 +9,000/枚（上限 90,000）。"""
    kind = (kind or "").strip()
    if kind not in ("光阴火", "光阴石", "光阴水"):
        return False, "用法：#消耗光阴火 / #消耗光阴石 / #消耗光阴水。", {}
    st = state_of(doc)
    if not (st.get("fortune") or st.get("demon")):
        return False, "光阴三品唯【命运神道体】与【极道天魔】可炼。", {}
    if st["light_total"] >= LIGHT_CAP:
        return False, f"光阴之力已臻上限（+{LIGHT_CAP:,} 三维）。", {}
    if int((inv or {}).get(kind, 0) or 0) < 1:
        return False, f"你并没有【{kind}】。", {}
    gain = min(LIGHT_STEP, LIGHT_CAP - st["light_total"])
    lg = _lg(doc)
    for k in ("atk", "def", "hp"):
        lg[k] = round(float(lg.get(k, 0) or 0) + gain, 3)
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["linggen"] = lg
    st["light_total"] = int(st["light_total"]) + gain
    save(doc, st)
    return True, (f"【{kind}】化作长河倒灌己身——三维 +{gain:,}"
                  f"（光阴总量 {st['light_total']:,}/{LIGHT_CAP:,}）。"), {kind: -1}


def demon_god(doc: Any, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    """#消耗邪神道果：九重魔功 → 极道天魔。"""
    st = state_of(doc)
    if st.get("demon"):
        return False, "你已是【极道天魔】——魔威滔天，何须再吞。", {}
    try:
        from . import motou as _mt
        if int(_mt.state_of(doc).get("magic", 0) or 0) < 9:
            return False, "邪神道果唯【九重魔功】可吞——#修炼魔功 至九重。", {}
    except Exception:
        return False, "魔功体系（#魔头帮助）未启用。", {}
    if int((inv or {}).get("邪神道果", 0) or 0) < 1:
        return False, "你并没有【邪神道果】。", {}
    _rename(doc, "极道天魔", 1.0, 2.0)
    st["demon"] = True
    save(doc, st)
    return True, ("≡≡≡ 极 道 天 魔 ≡≡≡\n九重魔功轰然合流，魔气撕开天幕——"
                  "eff ×2.0，#消耗光阴火/光阴石/光阴水 已解封。"), {"邪神道果": -1}


def panel(doc: Any) -> str:
    st = state_of(doc)
    lg = _lg(doc)
    lines = ["--- 体质进阶 ---",
             f"当前灵根：【{lg.get('name', '?')}】（eff ×{float(lg.get('eff', 1) or 1):g}）",
             f"太阳体：第 {st['sun']} 阶｜太阴体：第 {st['moon']} 阶｜神王体：第 {st['king']} 阶",
             f"轮回：第 {st['samsara']}/9 转｜轮回点 {st['points']}"
             f"｜命运神道体：{'是' if st['fortune'] else '否'}｜极道天魔：{'是' if st['demon'] else '否'}",
             f"光阴三维加成：+{st['light_total']:,}/{LIGHT_CAP:,}",
             "指令：#太阳体觉醒 / #太阴体觉醒 / #神王体觉醒 / #轮回 / #供奉奇怪的石头 / "
             "#消耗轮回道果 / #消耗光阴火|光阴石|光阴水 / #消耗邪神道果"]
    return "\n".join(lines)
