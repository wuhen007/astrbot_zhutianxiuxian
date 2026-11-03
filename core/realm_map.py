"""玩家属性映射层（P0-06）：原版双轨 level_id/Physique_id ↔ 本插件单轨 realm_index。

原版境界为双轨（炼气轨 level_id + 炼体轨 Physique_id）；本插件合并为单轨 realm_index
（0-based，默认取炼气轨境界表）。本模块只提供显式映射与统一取属性接口，**不修改任何既有公式与数据**，
公式仍以 realm_index 表达，双轨对照值经本模块获取（与 quest.py 等处 realm_index×2 对标一致）。

映射约定：
- realm_index 为 0-based；原版 level_id / Physique_id 均为 1-based。
- 境界表自带 level_id 字段，映射直接读取表内 level_id，避免硬编码偏移（无该字段时按 realm_index+1 回退）。
- 炼体轨 Physique_id 与单轨同境界索引对齐（合并时以同一境界索引取炼体轨 level_id）；
  后续如提供独立炼体表，可将 realm_to_physique_id 改为读取对应表。
- 双轨合并口径 realm_of_dual 取两轨较小值，作为单轨等价对照，与现有 realm_index×2 对标不冲突。
- 本模块为纯函数（无 IO），供成长/战斗/任务公式在需要双轨对照时调用。
"""
from __future__ import annotations

from typing import Any

LEVEL_ID_FIELD = "level_id"


def realm_to_level_id(realm_index: int, level_table: list[dict]) -> int:
    """单轨 realm_index(0-based) → 原版炼气轨 level_id(1-based)。"""
    if not level_table:
        return 0
    i = max(min(int(realm_index), len(level_table) - 1), 0)
    entry = level_table[i]
    lid = entry.get(LEVEL_ID_FIELD) if isinstance(entry, dict) else None
    if lid is None:
        return i + 1
    return int(lid)


def realm_to_physique_id(realm_index: int, level_table: list[dict]) -> int:
    """单轨 realm_index(0-based) → 原版炼体轨 Physique_id(1-based)。

    单轨合并时以同一境界索引对齐炼体轨；独立炼体表可用同签名传入。
    """
    return realm_to_level_id(realm_index, level_table)


def realm_from_level_id(level_id: Any, level_table: list[dict]) -> int:
    """原版炼气轨 level_id(1-based) → 单轨 realm_index(0-based)。"""
    if not level_table:
        return 0
    i = max(min(int(level_id) - 1, len(level_table) - 1), 0)
    return i


def realm_from_physique_id(physique_id: Any, level_table: list[dict]) -> int:
    """原版炼体轨 Physique_id(1-based) → 单轨 realm_index(0-based)（同索引对齐）。"""
    return realm_from_level_id(physique_id, level_table)


def realm_of_dual(level_id: Any, physique_id: Any, level_table: list[dict]) -> int:
    """原版双轨 (level_id, Physique_id) → 单轨 realm_index（取两轨较小值，合并口径）。"""
    if level_table:
        a = realm_from_level_id(level_id, level_table)
        b = realm_from_physique_id(physique_id, level_table)
    else:
        a = realm_from_level_id(level_id, []) if level_id is not None else 0
        b = realm_from_physique_id(physique_id, []) if physique_id is not None else 0
    return min(a, b)


def dual_realm(level_id: Any, physique_id: Any, level_table: list[dict]) -> int:
    """别名：原版双轨 → 单轨 realm_index，与 realm_of_dual 同义，便于调用方命名。"""
    return realm_of_dual(level_id, physique_id, level_table)


def realm_entry_attr(realm_index: int, level_table: list[dict], field: str) -> Any:
    """统一取属性接口：realm_index → 该境界条目的指定属性字段。"""
    if not level_table:
        return None
    i = max(min(int(realm_index), len(level_table) - 1), 0)
    entry = level_table[i]
    return entry.get(field) if isinstance(entry, dict) else None
