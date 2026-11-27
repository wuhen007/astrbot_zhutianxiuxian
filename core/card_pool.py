"""仙宠卡池（对齐原版 apps/User/UserHome.js `sk()`）。

天地卡池：耗天罗地网，全量随机；10% 额外掉落「金红的蛋」。
灵界/凡界卡池：耗金丝仙网 / 银丝仙网，按 5 只一档取档首（原版 ceil((i+1)/5)-1)*5）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

POOLS: dict[str, tuple[str, str]] = {
    "天地卡池": ("天罗地网", "all"),
    "灵界卡池": ("金丝仙网", "tier"),
    "凡界卡池": ("银丝仙网", "tier"),
}

BONUS_ITEM = "金红的蛋"
BONUS_RATE = 0.1


def draw(pool_name: str, pets: Sequence[Mapping[str, Any]], rng: Any) -> dict[str, Any]:
    """返回 {"pet": 仙宠行, "bonus": 额外道具名或 ""}。"""
    if pool_name not in POOLS:
        raise ValueError(f"未知卡池：{pool_name}")
    _item, mode = POOLS[pool_name]
    if not pets:
        raise ValueError("仙宠列表为空")
    idx = int(rng.randrange(len(pets)))
    if mode == "tier":
        idx = (math.ceil((idx + 1) / 5) - 1) * 5
    idx = max(0, min(idx, len(pets) - 1))
    bonus = ""
    if pool_name == "天地卡池" and rng.random() >= 1 - BONUS_RATE:
        bonus = BONUS_ITEM
    return {"pet": dict(pets[idx]), "bonus": bonus}


def need_item(pool_name: str) -> str:
    return POOLS[pool_name][0]


def text_of(pool_name: str, result: Mapping[str, Any]) -> str:
    pet = result.get("pet") or {}
    lines = [f"【{pool_name}】一道金光从天而降。",
             f"走近一看，是【{pet.get('品级', '?')}】{pet.get('name', '?')}。",
             f"已收入纳戒，可发「#领养仙宠 {pet.get('name', '')}」结契。"]
    if result.get("bonus"):
        lines.append(f"凤鸣齐天、流光四溢——额外获得【{result['bonus']}】。")
    return "\n".join(lines)
