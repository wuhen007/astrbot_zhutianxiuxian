"""命格（W2-3，对齐原版 model/mingge.js）。

原版语义：
- 75 条词条（data/item/命格词条.json）：rarity 1-3 权重 70/25/5，13 条负面
  （默认负面概率 12%），effects 多字段（ attack/defense/hp/暴击/突破成功率/签到倍率…）。
- getMinggeEffects：主命格 + 附加命格合并（bonus 加法 / direct-multiplier 乘法 / boolean 或）。

本移植接入消费点：战斗三维+暴击（_pvp_battle）、境界突破成功率（#突破）、
签到奖励倍率（#修仙签到）、渡劫修为减少（#渡劫）。
shortcut：附加命格、速度/生命本源/心神/悟道/采集炼丹等其余消费点登记未接
（见《珠天修仙-python-port后续推进计划》W2 段）。
"""

from __future__ import annotations

import random
from typing import Any

from .player import PlayerDoc

RARITY_WEIGHTS = {1: 70, 2: 25, 3: 5}
NEGATIVE_CHANCE = 0.12
REROLL_COST = 100_000          # #改命 灵石（原版无重抽通道，自定）

_CONSUMED_KEYS = {
    "攻击加成": 1.0, "防御加成": 1.0, "生命加成": 1.0,
    "暴击加成": 1.0, "境界突破成功率": 1.0, "渡劫修为减少": 1.0,
}


def _table(content: Any) -> list[dict]:
    t = content.table("item/命格词条") if content else None
    return t if isinstance(t, list) else []


def roll(content: Any, rng: random.Random) -> dict:
    """按稀有度权重抽一条；负面独立概率判定（负面池为空则回退正面池）。"""
    pool = _table(content)
    if not pool:
        return {}
    rarities = sorted({int(e.get("rarity", 1) or 1) for e in pool})
    weights = [(r, RARITY_WEIGHTS.get(r, 0)) for r in rarities if RARITY_WEIGHTS.get(r, 0) > 0]
    total = sum(w for _, w in weights) or 1
    pick_r, roll_v = rarities[0], rng.random() * total
    acc = 0.0
    for r, w in weights:
        acc += w
        if roll_v < acc:
            pick_r = r
            break
    tier = pick_r if rng.random() >= NEGATIVE_CHANCE else -pick_r
    sub = [e for e in pool
           if int(e.get("rarity", 1) or 1) == pick_r
           and (bool(e.get("isNegative")) if tier < 0 else not bool(e.get("isNegative")))]
    if not sub:
        sub = [e for e in pool if int(e.get("rarity", 1) or 1) == pick_r]
    return dict(rng.choice(sub) if sub else pool[0])


def identity_of(doc: PlayerDoc) -> dict:
    """当前命格（ext["mingge"]，存整条词条快照）。"""
    v = doc.ext.get("mingge")
    return dict(v) if isinstance(v, dict) else {}


def ensure(doc: PlayerDoc, content: Any, rng: random.Random) -> dict:
    """无命格则补抽（开仙途/首次查看时）。"""
    cur = identity_of(doc)
    if cur:
        return cur
    cur = roll(content, rng)
    if cur:
        doc.ext["mingge"] = cur
    return cur


def effects_of(doc: PlayerDoc) -> dict:
    """效果合并（单命格直取；接口留附加命格扩展）。"""
    return dict(identity_of(doc).get("effects") or {})


def bonus(doc: PlayerDoc, key: str) -> float:
    """bonus-rate/chance 类取值（加法合并）。"""
    v = effects_of(doc).get(key, 0)
    try:
        return max(0.0, float(v) if not isinstance(v, bool) else float(v))
    except (TypeError, ValueError):
        return 0.0


def multiplier(doc: PlayerDoc, key: str) -> float:
    """direct-multiplier 类取值（乘法，缺省 1）。"""
    v = effects_of(doc).get(key, 1)
    try:
        f = float(v)
        return f if f > 0 else 1.0
    except (TypeError, ValueError):
        return 1.0


def reroll(doc: PlayerDoc, content: Any, rng: random.Random) -> tuple[bool, str]:
    """#改命：花灵石重抽（负面命格也能改）。"""
    if int(doc.stones) < REROLL_COST:
        return False, f"改命需 {REROLL_COST:,} 灵石逆天改运（当前 {int(doc.stones):,}）。"
    new = roll(content, rng)
    if not new:
        return False, "命格天机暂不可测（词条表缺失）。"
    old_name = str(identity_of(doc).get("name") or "无名之命")
    doc.stones -= REROLL_COST
    doc.ext["mingge"] = new
    neg = "（此命有缺，多劫多磨）" if new.get("isNegative") else ""
    return True, (f"【改命】天机重演——{old_name} → 【{new.get('name')}】{neg}\n"
                  f"{new.get('desc', '')}\n"
                  f"效果：{'、'.join(f'{k}+{v:g}' if not isinstance(v, bool) else k for k, v in (new.get('effects') or {}).items())}\n"
                  f"灵石 -{REROLL_COST:,}")


def text(doc: PlayerDoc) -> str:
    m = identity_of(doc)
    if not m:
        return "--- 命格 ---\n命格未定（#改命 可窥探天机）。"
    neg = "⚠ 负面命格" if m.get("isNegative") else f"{m.get('rarityName', '')}命格"
    eff = m.get("effects") or {}
    eff_txt = "、".join(f"{k} {'+' if not isinstance(v, bool) else ''}{v:g}"
                        if not isinstance(v, bool) else k for k, v in eff.items())
    return "\n".join([
        "--- 命格 ---",
        f"【{m.get('name')}】（{neg}｜{m.get('category', '')}）",
        str(m.get("desc") or ""),
        f"效果：{eff_txt or '无'}",
        f"改命：#改命（{REROLL_COST:,} 灵石重演天机）",
    ])
