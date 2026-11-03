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
    return {
        "id": entry.get("id"),
        "name": str(entry.get("name", "?")),
        "type": str(entry.get("type", "?")),
        "eff": float(entry.get("eff", 1.0) or 1.0),
        "rarity": rarity,
    }


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
    return f"{snap.get('name')}{mid} · 修炼效率加成 +{eff:g}"
