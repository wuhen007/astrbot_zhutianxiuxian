"""诸天镜补充玩法（W14-F1）——原版 `apps/zhutianjing/mofashaonv.js`
（魔法少女进阶/净化灵魂宝石/重置时间线）、`apps/User/UserHome.js`
（#消耗诸天镜 → 位面主角灵根）、`linggenhelp`（#诸天一念）的纯函数移植。

更正：对比报告曾判「见泷原/骑士世界未移植」——实际两世界探索、库洛牌、
月之审判、小樱进阶、帝骑卡组、最终攻击驾驭、救赎已在 `core/zhutian.py`
与 main.py B2 落地；本模块只补五条缺口指令。

本移植（shortcut）：
- 魔法少女进阶：需装载【鹿目圆】化身；四阶 魔法少女→愿望化身→希望化身→
  圆环之理；消耗希望碎片 100/500/1000 + 已获「魔法少女小圆」印记；
  每阶化身 eff ×1.6/×2.8/×4.8（原版全属性 +150%/+500% 折算）。
- 净化灵魂宝石：消耗【悲叹之种】×1 → 希望碎片 +3、本世污浊 -3（初始 20）。
- 重置见泷原时间线：污浊 ≤5 时可重置（镜能 -2），时间线干涉 +1、希望 +10。
- #消耗诸天镜：修为血气各 5,000,000（两级折算），随机获得位面主角灵根
  （小樱/帝骑/伊蕾娜/流萤/天命青儿/鹿目圆，id 7010015 族），覆盖当前灵根。
- #诸天一念：岁云五阶专属（suiyun seals 满）跨位面赠送物品（转移由 handler 落库）。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

MG_STAGES = (
    ("魔法少女", 0, 1.0),
    ("愿望化身·圆", 100, 1.6),
    ("希望之光·圆", 500, 2.8),
    ("圆环之理", 1000, 4.8),
)
DUST_INIT = 20
PURIFY_ITEM = "悲叹之种"
MIRROR_COST = 5_000_000
PROTAGONISTS: tuple[dict[str, Any], ...] = (
    {"name": "木之本樱", "type": "魔卡少女", "eff": 1.0},
    {"name": "门矢士", "type": "骑士", "eff": 1.0},
    {"name": "伊蕾娜", "type": "魔女", "eff": 1.0},
    {"name": "少女流萤", "type": "星铁", "eff": 1.0},
    {"name": "天命青儿", "type": "修仙", "eff": 1.0},
    {"name": "鹿目圆", "type": "魔法少女", "eff": 1.25},
)


def _zt(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    zt = ext.get("zhutian") if isinstance(ext, dict) else None
    return zt if isinstance(zt, dict) else {}


def _st(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    st = ext.get("zhutian_extra") if isinstance(ext, dict) else None
    st = dict(st) if isinstance(st, dict) else {}
    st.setdefault("dust", DUST_INIT)
    st.setdefault("timeline", 0)
    st.setdefault("mg_stage", 0)
    st.setdefault("protagonist", "")
    return st


def _save_extra(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["zhutian_extra"] = dict(st)


def magic_girl_advance(doc: PlayerDoc) -> tuple[bool, str]:
    """#魔法少女进阶：鹿目圆化身四阶（希望碎片 + 小圆印记）。"""
    st = _st(doc)
    zt = _zt(doc)
    stage = int(st.get("mg_stage", 0) or 0)
    if str(zt.get("current") or "") != "鹿目圆":
        return False, "魔法少女进阶需装载【鹿目圆】化身——#装载化身 鹿目圆。"
    if stage >= len(MG_STAGES) - 1:
        return False, "你已是【圆环之理】——宇宙法则的终极权限在手。"
    nxt_name, cost, eff = MG_STAGES[stage + 1]
    hopes = int(zt.get("hopes", 0) or 0)
    if hopes < cost:
        return False, f"进阶【{nxt_name}】需希望碎片 {cost}（现有 {hopes}）——探索见泷原可得。"
    if "魔法少女小圆" not in list(zt.get("imprints") or []):
        return False, "需先完成「魔法少女小圆」投影（获得世界印记）。"
    zt["hopes"] = hopes - cost
    zt["current"] = "鹿目圆"
    st["mg_stage"] = stage + 1
    avatars = zt.get("avatars") or {}
    if "鹿目圆" in avatars and isinstance(avatars["鹿目圆"], dict):
        avatars["鹿目圆"]["eff"] = eff
        zt["avatars"] = avatars
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["zhutian"] = zt
    _save_extra(doc, st)
    return True, (f"≡≡≡ 魔法少女进阶 ≡≡≡\n{MG_STAGES[stage][0]} → 【{nxt_name}】！\n"
                  f"化身 eff ×{eff:g}｜希望碎片 -{cost}｜"
                  + ("宇宙法则的终极权限已在你手。" if stage + 1 == len(MG_STAGES) - 1 else
                     "救赎之力更进一层。"))


def purify(doc: PlayerDoc, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    """#净化灵魂宝石：悲叹之种 -1 → 希望 +3、污浊 -3。"""
    st = _st(doc)
    zt = _zt(doc)
    if int((inv or {}).get(PURIFY_ITEM, 0) or 0) < 1:
        return False, f"你并没有【{PURIFY_ITEM}】——见泷原探索可得。", {}
    dust = max(0, int(st.get("dust", 0) or 0) - 3)
    st["dust"] = dust
    zt["hopes"] = int(zt.get("hopes", 0) or 0) + 3
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["zhutian"] = zt
    _save_extra(doc, st)
    return True, (f"【净化灵魂宝石】悲叹消散，希望重燃——\n"
                  f"希望碎片 +3（现 {zt['hopes']}）｜污浊 -3（现 {dust}/20）。"), {PURIFY_ITEM: -1}


def reset_timeline(doc: PlayerDoc) -> tuple[bool, str]:
    """#重置见泷原时间线：污浊 ≤5 可重置，镜能 -2。"""
    st = _st(doc)
    zt = _zt(doc)
    dust = int(st.get("dust", 0) or 0)
    if dust > 5:
        return False, f"灵魂宝石污浊 {dust}/20 尚重——先 #净化灵魂宝石 压至 ≤5。"
    if int(zt.get("energy", 0) or 0) < 2:
        return False, "重置时间线需镜能 2 点（每日重置）。"
    zt["energy"] = int(zt.get("energy", 0) or 0) - 2
    st["dust"] = DUST_INIT
    st["timeline"] = int(st.get("timeline", 0) or 0) + 1
    zt["hopes"] = int(zt.get("hopes", 0) or 0) + 10
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["zhutian"] = zt
    _save_extra(doc, st)
    return True, (f"【重置见泷原时间线】第 {st['timeline']} 次轮回重启——\n"
                  "希望碎片 +10｜污浊回到 20/20｜时间线干涉 +1。")


def consume_mirror(doc: PlayerDoc, now: float | None = None,
                   rng: random.Random | None = None) -> tuple[bool, str]:
    """#消耗诸天镜：投影诸天获取随机位面主角灵根（覆盖当前灵根）。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    if int(getattr(doc, "realm_index", 0) or 0) + 1 < 10:
        return False, "神魂投影诸天需仙阶之体（练气 10 境起）。"
    if int(getattr(doc, "exp", 0) or 0) < MIRROR_COST:
        return False, f"投影需修为与血气各 {MIRROR_COST:,}。"
    xq = int(float((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0))
    if xq < MIRROR_COST:
        return False, f"投影需修为与血气各 {MIRROR_COST:,}（血气不足）。"
    doc.exp = int(getattr(doc, "exp", 0) or 0) - MIRROR_COST
    ext = getattr(doc, "ext", {})
    ext["xueqi"] = xq - MIRROR_COST
    pick = PROTAGONISTS[int(rng.random() * len(PROTAGONISTS)) % len(PROTAGONISTS)]
    lg = ext.get("linggen") if isinstance(ext.get("linggen"), dict) else {}
    old = str(lg.get("name") or "无名灵根")
    lg.update({"id": 7010015, "name": pick["name"], "type": pick["type"],
               "eff": float(pick["eff"]), "rarity": 5,
               "atk": round(float(lg.get("atk", 0) or 0) or 1.0, 3),
               "def": round(float(lg.get("def", 0) or 0) or 1.0, 3),
               "hp": round(float(lg.get("hp", 0) or 0) or 1.0, 3)})
    ext["linggen"] = lg
    st = _st(doc)
    st["protagonist"] = pick["name"]
    _save_extra(doc, st)
    return True, (f"【消耗诸天镜】神魂离体，投影诸天——归位时你已是别人故事的主角。\n"
                  f"灵根 {old} → 【{pick['name']}】（{pick['type']}｜eff ×{pick['eff']:g}）。\n"
                  "属性面板以 #我的灵根 复核。")


def one_thought_gate(doc: Any) -> tuple[bool, str]:
    """#诸天一念：岁云五阶专属（五印齐）。"""
    try:
        from . import suiyun as _sy
        st = _sy.state_of(doc)
        if len(st.get("seals") or {}) >= len(_sy.SEALS):
            return True, ""
    except Exception:
        pass
    return False, "诸天一念为岁云五阶权柄——#岁云见证 查看进度。"


def panel(doc: Any) -> str:
    st = _st(doc)
    zt = _zt(doc)
    mg = MG_STAGES[int(st.get("mg_stage", 0) or 0)][0]
    return "\n".join([
        "--- 诸天镜 · 补充玩法 ---",
        f"魔法少女进阶：{mg}（{'圆环之理已至' if st.get('mg_stage', 0) >= 3 else '需装载鹿目圆'}）",
        f"希望碎片：{int(zt.get('hopes', 0) or 0)}｜污浊：{st.get('dust', 0)}/20"
        f"｜时间线干涉：{st.get('timeline', 0)}",
        f"位面主角灵根：{st.get('protagonist') or '未获得（#消耗诸天镜）'}",
        "指令：#魔法少女进阶 ｜ #净化灵魂宝石 ｜ #重置见泷原时间线 ｜ #消耗诸天镜 ｜ #诸天一念",
    ])
