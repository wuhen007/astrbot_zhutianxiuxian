"""副本目录（W7-5b）：把 #禁地 / #仙境 / #下界八域 / #九天十地 / #探索仙府 的查询
接到**真实进入与掉落**，而不是只列一行说明。

数据：
- `item/副本/禁地列表.json`(4) / `仙境列表.json`(12) / `下界八域列表.json` / `九天十地.json`(2)
- `Timelimit/限定仙府.json`(2)
条目字段：name / Grade / Price / experience / shouyuan / one·two·three（掉落池）/ Best

本移植口径：
- 门槛按 Price 分档（越贵越凶险），进入交 `Price × 2%` 灵石（最低 5000）
- 地图系数由 Price 推算：`0.6 + 0.7×log10(Price/5万)`，钳在 0.6~3.2（与 secret.PLACES 同量级）
- 掉落池 = one+two+three 合并；缺 稀有度 的按所在档补 2/4/6
- 撤离结算时按「探明层数/10」折算副本表里的 experience / shouyuan

shortcut：原版副本的剧情节点、多阶段 Boss、法身双人同探未移植；掉落走 secret 的程序化遭遇。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

# 与 core/extras.DUNGEON_TABLES 同一批表；此处按「可进入顺序」排序
TABLES: dict[str, str] = {
    "仙府": "Timelimit/限定仙府",
    "禁地": "item/副本/禁地列表",
    "仙境": "item/副本/仙境列表",
    "下界八域": "item/副本/下界八域列表",
    "九天十地": "item/副本/九天十地",
}

FEE_RATE = 0.02
FEE_MIN = 5_000
# (Price 上限, 境界门槛) —— 未达到则不许进
GATE_TIERS: tuple[tuple[int, int], ...] = (
    (100_000, 0),
    (1_000_000, 12),
    (10_000_000, 25),
    (100_000_000, 38),
    (10 ** 18, 50),
)
RARITY_BY_TIER = {"one": 2, "two": 4, "three": 6}


def find(name: str, content: Callable[[str], Any]) -> tuple[dict, str] | None:
    """按副本名在五张表里查找，返回 (条目, 类别)。"""
    target = (name or "").strip()
    if not target:
        return None
    for kind, path in TABLES.items():
        for row in (content(path) or []):
            if isinstance(row, Mapping) and str(row.get("name")) == target:
                return dict(row), kind
    return None


def gate_of(price: int) -> int:
    price = max(0, int(price))
    for limit, gate in GATE_TIERS:
        if price < limit:
            return gate
    return GATE_TIERS[-1][1]


def fee_of(price: int) -> int:
    return max(FEE_MIN, int(int(price) * FEE_RATE))


def factor_of(price: int) -> float:
    price = max(1, int(price))
    raw = 0.6 + 0.7 * math.log10(price / 50_000)
    return round(min(3.2, max(0.6, raw)), 2)


def pool_of(row: Mapping) -> list[dict]:
    """合并 one/two/three 掉落池，补齐稀有度供 secret.roll_drop 过滤。"""
    pool: list[dict] = []
    seen: set[str] = set()
    for tier in ("one", "two", "three"):
        for item in (row.get(tier) or []):
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            try:
                rarity = int(item.get("稀有度") or 0)
            except (TypeError, ValueError):
                rarity = 0
            pool.append({
                "name": name,
                "class": item.get("class") or "道具",
                "稀有度": rarity or RARITY_BY_TIER[tier],
            })
    return pool


def rewards_of(row: Mapping, floor: int) -> tuple[int, int]:
    """撤离结算的额外修为/寿元：按「探明层数/10」折算（最多全额）。"""
    ratio = min(1.0, max(0.0, int(floor) / 10))
    exp = int(float(row.get("experience") or 0) * ratio)
    shou = int(float(row.get("shouyuan") or 0) * ratio)
    return exp, shou


def brief(row: Mapping) -> str:
    return (f"{row.get('name')}（{row.get('Grade') or '副本'}）｜"
            f"门票 {fee_of(row.get('Price', 0)):,} 灵石｜门槛第 {gate_of(row.get('Price', 0)) + 1} 境")
