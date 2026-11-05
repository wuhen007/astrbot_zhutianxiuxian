"""灵根（天资）系统：洗炼重摇 + 修炼效率（纯函数，无 IO）。

数据源：item/灵根列表.json（原版 139 条，含 伪灵根/真灵根/变异灵根/体质/神体 等）。
- 稀有度加权：w = 1/3^(r-1)，同稀有度内均匀；稀有度越高越难洗出。
- eff 字段 = 修炼效率倍率（闭关出关修为 ×eff）；无灵根视为 ×1.0。
- 灵根条目以快照形式存入 ext["linggen"]（id/name/type/eff），表变更不影响老玩家。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

from .player import PlayerDoc

RARITY_BASE = 3.0  # 每高一阶稀有度，权重 ÷3


def _weight(rarity: int) -> float:
    return 1.0 / (RARITY_BASE ** max(0, int(rarity) - 1))


def snapshot(entry: Mapping) -> dict:
    """灵根条目 → 玩家档案快照（含稀有度，表后续改动不影响老玩家展示）。"""
    try:
        rarity = int(entry.get("稀有度", 1) or 1)
    except (TypeError, ValueError):
        rarity = 1
    try:
        orb = float(entry.get("法球倍率", 0) or 0)
    except (TypeError, ValueError):
        orb = 0.0
    def _num(key: str) -> float:
        try:
            return max(0.0, float(entry.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0.0

    return {
        "id": entry.get("id"),
        "name": str(entry.get("name", "?")),
        "type": str(entry.get("type", "?")),
        "eff": float(entry.get("eff", 1.0) or 1.0),
        "orb": orb,
        "rarity": rarity,
        # W7-4 灵根觉醒：四维按比例/本源按扁平（生命本源 ×1000 折算血量）
        "atk": _num("攻击"),
        "def": _num("防御"),
        "hp": _num("生命"),
        "origin": _num("生命本源"),
        "awaken": 0,
    }


def orb_of(snap: Mapping | None) -> float:
    """法球倍率：老快照缺字段时按 0（洗炼一次即补齐）。"""
    if not isinstance(snap, Mapping):
        return 0.0
    try:
        return max(0.0, float(snap.get("orb", 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def roll(entries: Sequence[Mapping], rng: random.Random) -> dict:
    """按稀有度加权随机抽一条灵根，返回快照。"""
    pool = [e for e in entries if isinstance(e, Mapping) and e.get("name")]
    if not pool:
        return {}
    weights = [_weight(e.get("稀有度", 1) or 1) for e in pool]
    return snapshot(rng.choices(pool, weights=weights, k=1)[0])


def eff_of(doc: PlayerDoc) -> float:
    """玩家灵根效率**加成项**（对齐原版 baseCultivationMultiplier = 1 + eff + ...）。

    原版灵根 eff 是效率等式的加法项：伪灵根 eff 0.1 → ×1.1，天灵根 2.0 → ×3.0。
    未洗炼（或异常）时加成为 0。
    """
    lg = doc.ext.get("linggen")
    if not isinstance(lg, Mapping):
        return 0.0
    try:
        return max(0.0, float(lg.get("eff", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def refine(
    doc: PlayerDoc, entries: Sequence[Mapping], rng: random.Random
) -> tuple[dict | None, dict, PlayerDoc]:
    """天资洗炼：重摇灵根（与旧条目相同则再摇一次兜底）。

    返回 (旧快照或 None, 新快照, 新 doc)。洗炼不消耗状态，仅改 ext["linggen"]。
    """
    d = doc.model_copy(deep=True)  # ext 深拷贝，避免共享 dict 污染原档案
    old = d.ext.get("linggen") if isinstance(d.ext.get("linggen"), Mapping) else None
    new = roll(entries, rng)
    if old and new and old.get("id") == new.get("id"):
        new = roll(entries, rng)
    d.ext["linggen"] = new
    return (dict(old) if old else None), new, d


# ---------------------------------------------------------------- 灵根觉醒（W7-4）

AWAKEN_MAX = 3
AWAKEN_REALM = 20          # 破虚境：需先有一定根基
AWAKEN_COST = 5_000_000    # 每档 500 万灵石（第 n 档按 n 倍递进）
AWAKEN_GAIN = 0.25         # 每档把四维比例提升 25%
ORIGIN_SCALE = 1000        # 生命本源 1 点 = 1000 气血


def awaken_level(snap: Mapping | None) -> int:
    if not isinstance(snap, Mapping):
        return 0
    try:
        return min(AWAKEN_MAX, max(0, int(snap.get("awaken", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def awaken_cost(level: int) -> int:
    return AWAKEN_COST * (int(level) + 1)


def stats_of(snap: Mapping | None) -> tuple[float, float, float, float]:
    """灵根四维 → (攻比例, 防比例, 血比例, 气血扁平)。觉醒每档 +25%（加法缩放）。"""
    if not isinstance(snap, Mapping):
        return 0.0, 0.0, 0.0, 0.0
    level = awaken_level(snap)
    mult = 1.0 + AWAKEN_GAIN * level
    try:
        atk = max(0.0, float(snap.get("atk", 0) or 0)) * mult
        dfn = max(0.0, float(snap.get("def", 0) or 0)) * mult
        hp = max(0.0, float(snap.get("hp", 0) or 0)) * mult
        origin = max(0.0, float(snap.get("origin", 0) or 0)) * mult
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0, 0.0
    return atk, dfn, hp, origin * ORIGIN_SCALE


def sync_stats(doc: PlayerDoc, entries: Sequence[Mapping]) -> bool:
    """给老快照补齐四维（按 id/name 回表），返回是否有改动。"""
    snap = doc.ext.get("linggen")
    if not isinstance(snap, Mapping) or "atk" in snap:
        return False
    row = None
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        if snap.get("id") and e.get("id") == snap.get("id") and str(e.get("name")) == str(snap.get("name")):
            row = e
            break
    if row is None:
        row = next((e for e in entries
                    if isinstance(e, Mapping) and str(e.get("name")) == str(snap.get("name"))), None)
    if row is None:
        return False
    fresh = snapshot(row)
    merged = dict(snap)
    for key in ("atk", "def", "hp", "origin"):
        merged[key] = fresh[key]
    merged.setdefault("awaken", 0)
    doc.ext["linggen"] = merged
    return True


def awaken(doc: PlayerDoc, now: float | None = None) -> tuple[bool, str, PlayerDoc]:
    """#灵根觉醒：消耗灵石抬一档觉醒，四维 +25%。"""
    snap = doc.ext.get("linggen")
    if not isinstance(snap, Mapping):
        return False, "你尚未洗炼灵根，何谈觉醒（先去 #洗炼灵根）。", doc
    if int(doc.realm_index) < AWAKEN_REALM:
        return False, f"觉醒需第 {AWAKEN_REALM + 1} 境以上（当前第 {int(doc.realm_index) + 1} 境）。", doc
    level = awaken_level(snap)
    if level >= AWAKEN_MAX:
        return False, f"灵根已至 {AWAKEN_MAX} 阶觉醒（圆满），再无可醒之处。", doc
    cost = awaken_cost(level)
    if int(doc.stones) < cost:
        return False, f"觉醒第 {level + 1} 阶需 {cost:,} 灵石（当前 {int(doc.stones):,}）。", doc
    d = doc.model_copy(deep=True)
    d.stones -= cost
    inner = dict(d.ext["linggen"])
    inner["awaken"] = level + 1
    d.ext["linggen"] = inner
    atk, dfn, hp, origin = stats_of(inner)
    return True, (
        f"【灵根觉醒·第 {level + 1} 阶】{inner.get('name')} 道韵内敛，四维再涨！\n"
        f"攻击 +{atk:.0%}｜防御 +{dfn:.0%}｜生命 +{hp:.0%}｜生命本源 +{origin:,.0f} 气血\n"
        f"消耗 {cost:,} 灵石，余 {int(d.stones):,}。"
    ), d


def awaken_text(doc: PlayerDoc) -> str:
    snap = doc.ext.get("linggen")
    if not isinstance(snap, Mapping):
        return "未洗炼灵根。"
    atk, dfn, hp, origin = stats_of(snap)
    level = awaken_level(snap)
    nxt = "已圆满" if level >= AWAKEN_MAX else f"下一阶 {awaken_cost(level):,} 灵石"
    return (f"--- 灵根 · {snap.get('name')} ---\n"
            f"类型：{snap.get('type')}｜稀有度 {snap.get('rarity')}｜效率加成 +{float(snap.get('eff', 0) or 0):g}\n"
            f"觉醒：{level}/{AWAKEN_MAX} 阶（{nxt}）\n"
            f"四维：攻击 +{atk:.0%}｜防御 +{dfn:.0%}｜生命 +{hp:.0%}｜生命本源 +{origin:,.0f} 气血")


def describe(snap: Mapping | None) -> str:
    """快照 → 展示文本（eff 为效率加成项）。"""
    if not snap:
        return "未洗炼（效率加成 +0）"
    try:
        eff = float(snap.get("eff", 0.0) or 0.0)
    except (TypeError, ValueError):
        eff = 0.0
    tail = f"，稀有度 {snap.get('rarity')}" if snap.get("rarity") else ""
    inner = str(snap.get("type") or "") + tail
    inner = inner.lstrip("，") if inner.startswith("，") else inner
    mid = f"（{inner}）" if inner else ""
    lv = awaken_level(snap)
    tail2 = f" · 觉醒 {lv} 阶" if lv else ""
    return f"{snap.get('name')}{mid} · 修炼效率加成 +{eff:g}{tail2}"
