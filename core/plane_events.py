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
- 游商：不做位面坐标校验；仙翁拓本进入装备索引，求签收益记入玩家 24h 状态。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .wallet import authority as _authority, set_xueqi as _set_xueqi, xueqi as _xueqi
from .player import PlayerDoc

FUND_GOAL = 1000

IMPERIAL_GOODS: tuple[tuple[str, int, str], ...] = (
    ("仙尊战袍·拓本", 1_200_000, "全属性 +18%"),
    ("弑帝枪·拓本", 1_500_000, "攻击 +25%"),
    ("万劫不侵钟·拓本", 1_800_000, "防御 +25%"),
)
BLACK_GOODS: tuple[tuple[str, int, str], ...] = (
    ("九转天药", 600_000, "元神大涨"),
    ("叩仙丹", 400_000, "仙道潜力 +10"),
)
XIANGZI_SIGNS = ("问道签", "历练签", "寻缘签")
SIGN_EFFECTS = {
    "问道签": ("悟道收益", "悟道收益 +10%"),
    "历练签": ("副本出金率", "副本出金率 +10%"),
    "寻缘签": ("奇遇概率", "秘境奇遇概率 +10%"),
}
SIGN_DURATION = 24 * 3600
XIANGZI_COST = 500_000


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


def _war_products(content: Any) -> list[Mapping[str, Any]]:
    if isinstance(content, Mapping):
        rows = content.get("products", content.get("圣地战功商店", []))
    else:
        rows = content
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []


def war_shop(doc: Any, content: Mapping[str, Any]) -> str:
    rows = _war_products(content)
    if not rows:
        return "--- 战功商店 ---\n（商店表暂空——#战功兑换 名称 仍可尝试）"
    lines = ["--- 战功商店 ---"]
    for r in rows[:12]:
        if isinstance(r, dict):
            lines.append(f"· {r.get('name', '?')}｜{int(r.get('price', 0) or 0):,} 战功"
                         f"｜{r.get('description', r.get('desc', ''))}")
    lines.append("兑换：#战功兑换 名称")
    return "\n".join(lines)


def war_exchange(doc: PlayerDoc, calamity: Mapping[str, Any], name: str,
                 content: Mapping[str, Any]) -> tuple[bool, str, dict[str, int]]:
    rows = _war_products(content)
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
    lines.append("购买：#购买仙翁商品 编号（源石计价）")
    lines.append("")
    lines.append("--- 黑衣神秘人（神药与潜力丹）---")
    lines += [f"· #{i + 1} {n}｜{p:,} 源石｜{d}" for i, (n, p, d) in enumerate(BLACK_GOODS)]
    lines.append("购买：#购买黑市商品 编号")
    lines.append("")
    lines.append("--- 绝美仙子（红尘仙缘签）---")
    lines.append(f"· #求取问道签|历练签|寻缘签（{XIANGZI_COST:,} 灵石，效果持续 24 小时）")
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


def ask_sign(doc: PlayerDoc, sign: str, now: float | None = None) -> tuple[bool, str]:
    sign = (sign or "").strip()
    if sign not in XIANGZI_SIGNS:
        return False, "用法：#求取问道签 / #求取历练签 / #求取寻缘签。"
    if int(getattr(doc, "stones", 0) or 0) < XIANGZI_COST:
        return False, f"求签需灵石 {XIANGZI_COST:,}（当前 {int(getattr(doc, 'stones', 0) or 0):,}）。"
    now = time.time() if now is None else float(now)
    key, label = SIGN_EFFECTS[sign]
    raw_active = doc.ext.get("red_dust_signs")
    active = dict(raw_active) if isinstance(raw_active, Mapping) else {}
    active[key] = {"bonus": 0.1, "expires_at": now + SIGN_DURATION, "name": sign}
    doc.ext["red_dust_signs"] = active
    doc.stones -= XIANGZI_COST
    return True, (f"【红尘仙缘签·{sign}】一签入手：{label}，持续 24 小时。"
                  f"已消耗灵石 {XIANGZI_COST:,}，剩余 {doc.stones:,}。")


def sign_bonus(doc: Any, effect: str, now: float | None = None) -> float:
    now = time.time() if now is None else float(now)
    ext = getattr(doc, "ext", {})
    signs = ext.get("red_dust_signs", {}) if isinstance(ext, Mapping) else {}
    row = signs.get(effect) if isinstance(signs, Mapping) else None
    if not isinstance(row, Mapping):
        return 0.0
    try:
        if float(row.get("expires_at", 0) or 0) <= now:
            return 0.0
        return max(0.0, float(row.get("bonus", 0) or 0))
    except (TypeError, ValueError):
        return 0.0
