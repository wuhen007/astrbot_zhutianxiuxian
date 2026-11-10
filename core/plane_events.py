"""位面大事件：帝关 / 圣地大战 / 游商（W17-F1）——原版
`apps/tasks/ForeignImperialPass.js` + `model/foreignImperialPass.js`（帝关）、
`apps/SecretPlace/SecretPlace.js` L416-520（圣地大战/战功商店/游商）的纯函数移植。
先天至宝本体争夺已在 xtzb（单人守护灵挑战）；污损/求饶已在 tianjiao/战斗链。

本移植（shortcut）：
- 帝关：触发折算为玩家 #驰援帝关 直接触发（原 0.25 概率位面事件）；
  击杀目标 30（原 100）；期限折算 3 天实时；每胜 +1~3 杀、威名 +10；
  平定后开「帝血」窗口 1 小时，#融合帝血 借仙王战力（帝威 +20% 永久）。
  全服态存 calamity_state["imperial_pass"]。
- 圣地大战：轮次制——#圣战站队 攻|守|观（一轮一次）→ #战场行动（检定，
  胜战功 +12 败 -6 且气血归 1）→ #投入战资 源石*N（战功 +2N、军资累计）；
  军资达 1000 触发轮末奖励（战功 +30 全站队者）。个人战功 ext["sect_war"]。
  #战功商店 表取 data/圣地战功商店.json，#战功兑换 名称 扣战功发物品。
- 游商：不做位面坐标校验（原文需抵达坐标，本移植折算为每日限量）：
  白须仙翁（唯一百分比装备×3，源石计价）、黑衣神秘人（神药/潜力丹/禁物）、
  绝美仙子（问道/历练/寻缘签，50 万灵石，24h 红尘仙缘签效果待挂）。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

KILL_TARGET = 30
PASS_HOURS = 72
FUND_GOAL = 1000
IMPERIAL_BONUS = 0.2

IMPERIAL_GOODS: tuple[tuple[str, int, str], ...] = (
    ("仙尊战袍·拓本", 1_200_000, "全属性 +18%（唯一百分比）"),
    ("弑帝枪·拓本", 1_500_000, "攻击 +25%（唯一百分比）"),
    ("万劫不侵钟·拓本", 1_800_000, "防御 +25%（唯一百分比）"),
)
BLACK_GOODS: tuple[tuple[str, int, str], ...] = (
    ("九转天药", 600_000, "元神大涨"),
    ("叩仙丹", 400_000, "仙道潜力 +50"),
    ("诸天禁物·断念", 900_000, "来历不明的禁物"),
)
XIANGZI_SIGNS = ("问道签", "历练签", "寻缘签")
XIANGZI_COST = 500_000


def _authority(doc: Any) -> int:
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


def _xueqi(doc: Any) -> int:
    return int(float((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0))


def _set_xueqi(doc: Any, v: int) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["xueqi"] = max(0, int(v))


# ---------------------------------------------------------------- 帝关

def pass_state(calamity: Mapping[str, Any], now: float) -> dict[str, Any]:
    st = calamity.get("imperial_pass") if isinstance(calamity.get("imperial_pass"), dict) else {}
    st = dict(st)
    st.setdefault("active", False)
    st.setdefault("kills", 0)
    st.setdefault("until", 0.0)
    st.setdefault("defenders", {})
    st.setdefault("blood_open_until", 0.0)
    st.setdefault("blood_taken", [])
    if st["active"] and now > float(st["until"]):
        st["active"] = False
    return st


def pass_text(st: Mapping[str, Any], now: float) -> str:
    lines = ["--- 帝关战况 ---"]
    if st.get("active"):
        left = int((float(st["until"]) - now) / 3600)
        lines.append(f"异域叩关！士气：{st.get('kills', 0)}/{KILL_TARGET}"
                     f"（剩余 {max(0, left)} 小时）")
        top = sorted((st.get("defenders") or {}).items(), key=lambda kv: -kv[1])[:5]
        if top:
            lines.append("威名榜：" + "、".join(f"{n}({p})" for n, p in top))
        if now < float(st.get("blood_open_until", 0) or 0):
            lines.append("帝血已现——#融合帝血（1 小时窗口）")
        lines.append("驰援：#驰援帝关")
    else:
        lines.append("帝关平静。异域叩关由 #驰援帝关 触发。")
    return "\n".join(lines)


def reinforce(doc: PlayerDoc, st: dict[str, Any], now: float,
              rng: random.Random) -> tuple[bool, str, int]:
    """#驰援帝关：未开则触发；迎战一批同境异域天骄。返回 (ok,msg,威名增量)。"""
    if not st.get("active"):
        st["active"] = True
        st["kills"] = 0
        st["until"] = now + PASS_HOURS * 3600
        return True, ("【帝关告急】异域大军叩关——全服需斩杀 "
                      f"{KILL_TARGET} 名异域天骄（{PASS_HOURS // 24} 天为期）！\n"
                      "你第一时间赶到了城墙。#驰援帝关 再战。"), 10
    auth = _authority(doc)
    chance = min(0.9, 0.45 + auth * 0.01)
    if rng.random() >= chance:
        _set_xueqi(doc, 1)
        return True, (f"【驰援 · 帝关】异域天骄一波齐射——你被轰下城墙！\n"
                      f"（胜率 {chance:.0%}）气血归一，威名不减。"), 2
    kills = 1 + int(rng.random() * 3) % 3
    st["kills"] = int(st.get("kills", 0) or 0) + kills
    fame = 10 * kills
    uid = str(doc.uid)
    st["defenders"] = dict(st.get("defenders") or {})
    st["defenders"][str(doc.name or doc.uid[:8])] = int(st["defenders"].get(str(doc.name or doc.uid[:8]), 0) or 0) + fame
    msg = (f"【驰援 · 帝关】枪出如龙，斩异域天骄 {kills} 名！"
           f"（士气 {st['kills']}/{KILL_TARGET}｜威名 +{fame}）")
    if st["kills"] >= KILL_TARGET:
        st["active"] = False
        st["blood_open_until"] = now + 3600
        msg += "\n≡ 帝关大捷 ≡ 帝血显现——1 小时内 #融合帝血 可借仙王战力！"
    return True, msg, fame


def fuse_blood(doc: PlayerDoc, st: dict[str, Any], now: float) -> tuple[bool, str]:
    """#融合帝血：平定后 1 小时窗口，永久帝威 +20%。"""
    if now > float(st.get("blood_open_until", 0) or 0):
        return False, "帝血已散——下一场帝关再取。"
    if str(doc.uid) in list(st.get("blood_taken") or []):
        return False, "你已融合过这波帝血。"
    st["blood_taken"] = list(st.get("blood_taken") or []) + [str(doc.uid)]
    try:
        from . import zhengdao as _dz
        _s = _dz.state_of(doc, now)
        _s["power_bonus"] = round(min(3.0, float(_s.get("power_bonus", 0) or 0) + IMPERIAL_BONUS), 3)
        _dz.save(doc, _s)
    except Exception:
        pass
    return True, ("【融合帝血】滚烫的帝血入体——仙王之力短暂加身并留下永久烙印："
                  "帝威 +20%。")


# ---------------------------------------------------------------- 圣地大战

def _sw(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    st = ext.get("sect_war") if isinstance(ext, dict) else None
    st = dict(st) if isinstance(st, dict) else {}
    st.setdefault("merits", 0)
    st.setdefault("side", "")
    st.setdefault("round", 0)
    return st


def _sw_save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["sect_war"] = dict(st)


def war_text(doc: PlayerDoc, calamity: Mapping[str, Any]) -> str:
    w = calamity.get("sect_war") if isinstance(calamity.get("sect_war"), dict) else {}
    mine = _sw(doc)
    return "\n".join([
        "--- 圣地大战 ---",
        f"轮次：{int(w.get('round', 0) or 0)}｜全服军资：{int(w.get('fund', 0) or 0):,}/{FUND_GOAL:,}",
        f"你的阵营：{mine.get('side') or '未站队'}｜个人战功：{int(mine.get('merits', 0) or 0):,}",
        "指令：#圣战站队 攻|守|观 → #战场行动 → #投入战资 源石数 → "
        "#查看战场榜 / #战功商店 / #战功兑换 名称",
    ])


def war_side(doc: PlayerDoc, calamity: dict[str, Any], side: str,
             now: float) -> tuple[bool, str]:
    side = (side or "").strip()
    if side not in ("攻", "守", "观"):
        return False, "用法：#圣战站队 攻|守|观。"
    w = calamity.get("sect_war") if isinstance(calamity.get("sect_war"), dict) else {}
    st = _sw(doc)
    if int(st.get("round", 0) or 0) >= int(w.get("round", 0) or 0) and st.get("side"):
        return False, "本轮已站队——#战场行动 / #投入战资。"
    st["side"] = side
    st["round"] = int(w.get("round", 0) or 0)
    _sw_save(doc, st)
    w.setdefault("participants", [])
    if str(doc.uid) not in w["participants"]:
        w["participants"].append(str(doc.uid))          # 审计修复9：轮末奖励对象
    calamity["sect_war"] = w
    return True, f"【圣战站队 · {side}】已登记本轮阵营——#战场行动 开始积累战功。"


def war_act(doc: PlayerDoc, calamity: dict[str, Any], now: float,
            rng: random.Random) -> tuple[bool, str]:
    w = calamity.get("sect_war") if isinstance(calamity.get("sect_war"), dict) else {}
    st = _sw(doc)
    if not st.get("side"):
        return False, "先 #圣战站队 攻|守|观。"
    auth = _authority(doc)
    chance = min(0.9, 0.5 + auth * 0.01)
    if rng.random() < chance:
        st["merits"] = int(st.get("merits", 0) or 0) + 12
        _sw_save(doc, st)
        return True, (f"【战场行动 · {st['side']}】阵斩敌将——战功 +12"
                      f"（现 {st['merits']:,}｜胜率 {chance:.0%}）。")
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["hp"] = 1
    st["merits"] = max(0, int(st.get("merits", 0) or 0) - 6)
    _sw_save(doc, st)
    return True, (f"【战场行动 · {st['side']}】遭遇伏兵——战功 -6、气血归一！"
                  f"（胜率 {chance:.0%}）")


def war_fund(doc: PlayerDoc, calamity: dict[str, Any], qty: int,
             inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    qty = max(0, int(qty or 0))
    if qty <= 0:
        return False, "用法：#投入战资 源石数（如 #投入战资 50）。", {}
    if int((inv or {}).get("源石", 0) or 0) < qty:
        return False, f"你并没有【源石】×{qty}。", {}
    w = calamity.get("sect_war") if isinstance(calamity.get("sect_war"), dict) else {}
    w["fund"] = int(w.get("fund", 0) or 0) + qty
    st = _sw(doc)
    st["merits"] = int(st.get("merits", 0) or 0) + 2 * qty
    _sw_save(doc, st)
    msg = (f"【投入战资】源石 ×{qty} 入账——个人战功 +{2 * qty}"
           f"（全服军资 {w['fund']:,}/{FUND_GOAL:,}）。")
    if w["fund"] >= FUND_GOAL:
        w["fund"] = 0
        w["round"] = int(w.get("round", 0) or 0) + 1
        w["pending_bonus"] = list(w.get("participants") or [])   # 审计修复9：handler 据此 +30
        w["participants"] = []
        msg += f"\n≡ 军资达成 ≡ 本轮补给落地——{len(w['pending_bonus'])} 名站队者战功 +30。"
    calamity["sect_war"] = w
    return True, msg, {"源石": -qty}


def war_shop(doc: Any, content: Mapping[str, Any]) -> str:
    rows = content.get("圣地战功商店") if isinstance(content.get("圣地战功商店"), list) else []
    if not rows:
        return "--- 战功商店 ---\n（商店表暂空——#战功兑换 名称 仍可尝试）"
    lines = ["--- 战功商店 ---"]
    for r in rows[:12]:
        if isinstance(r, dict):
            lines.append(f"· {r.get('name', '?')}｜{int(r.get('price', 0) or 0):,} 战功"
                         f"｜{r.get('desc', '')}")
    lines.append("兑换：#战功兑换 名称")
    return "\n".join(lines)


def war_exchange(doc: PlayerDoc, calamity: Mapping[str, Any], name: str,
                 content: Mapping[str, Any]) -> tuple[bool, str, dict[str, int]]:
    rows = content.get("圣地战功商店") if isinstance(content.get("圣地战功商店"), list) else []
    row = next((r for r in rows if isinstance(r, dict) and str(r.get("name")) == (name or "").strip()), None)
    if row is None:
        return False, "战功商店无此物——#战功商店 查看列表。", {}
    cost = int(row.get("price", 0) or 0)
    st = _sw(doc)
    if int(st.get("merits", 0) or 0) < cost:
        return False, f"战功不足：{row.get('name')} 需 {cost:,}（现有 {st.get('merits', 0):,}）。", {}
    st["merits"] = int(st["merits"]) - cost
    _sw_save(doc, st)
    return True, (f"【战功兑换】{row.get('name')} ×1 已入纳戒"
                  f"（消耗战功 {cost:,}｜余 {st['merits']:,}）。"), {str(row.get("name")): 1}


# ---------------------------------------------------------------- 游商

def merchant_text() -> str:
    lines = ["--- 白须仙翁（唯一百分比装备）---"]
    lines += [f"· #{i + 1} {n}｜{p:,} 源石｜{d}" for i, (n, p, d) in enumerate(IMPERIAL_GOODS)]
    lines.append("购买：#购买仙翁商品 编号（源石计价，每日不限但看缘分刷新）")
    lines.append("")
    lines.append("--- 黑衣神秘人（神药与禁物）---")
    lines += [f"· #{i + 1} {n}｜{p:,} 源石｜{d}" for i, (n, p, d) in enumerate(BLACK_GOODS)]
    lines.append("购买：#购买黑市商品 编号")
    lines.append("")
    lines.append("--- 绝美仙子（红尘仙缘签）---")
    lines.append(f"· #求取问道签|历练签|寻缘签（{XIANGZI_COST:,} 灵石，24h 缘签）")
    return "\n".join(lines)


def buy(doc: PlayerDoc, catalog: tuple[tuple[str, int, str], ...], idx: int,
        inv: Mapping[str, int], currency: str = "源石") -> tuple[bool, str, dict[str, int]]:
    if not (1 <= idx <= len(catalog)):
        return False, f"编号须为 1~{len(catalog)}。", {}
    name, price, desc = catalog[idx - 1]
    if currency == "源石":
        if int((inv or {}).get("源石", 0) or 0) < price:
            return False, f"{name} 需源石 {price:,}（现有 {int((inv or {}).get('源石', 0) or 0):,}）。", {}
        return True, f"【仙缘一掷】{name} 已入纳戒——{desc}。", {"源石": -price, name: 1}
    if int(getattr(doc, "stones", 0) or 0) < price:
        return False, f"{name} 需灵石 {price:,}。", {}
    doc.stones = int(getattr(doc, "stones", 0) or 0) - price
    return True, f"【仙缘一掷】{name} 已入纳戒——{desc}。", {name: 1}


def ask_sign(doc: PlayerDoc, sign: str) -> tuple[bool, str]:
    sign = (sign or "").strip()
    if sign not in XIANGZI_SIGNS:
        return False, "用法：#求取问道签 / #求取历练签 / #求取寻缘签。"
    if int(getattr(doc, "stones", 0) or 0) < XIANGZI_COST:
        return False, f"求签需灵石 {XIANGZI_COST:,}（原 200 万源石折算）。"
    doc.stones = int(getattr(doc, "stones", 0) or 0) - XIANGZI_COST
    eff = {"问道签": "悟道收益 +10%", "历练签": "副本出金率 +10%",
           "寻缘签": "奇遇概率 +10%"}[sign]
    return True, (f"【红尘仙缘签 · {sign}】仙子莞尔，一签入手——24 小时内 {eff}。\n"
                  "（缘签效果挂接在后续版本生效，先收好签文）")
