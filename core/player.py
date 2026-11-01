"""玩家文档模型与创建逻辑（纯函数，无 IO）。"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_REALM_TABLE = "Level/练气境界"


class PlayerDoc(BaseModel):
    """玩家聚合文档。后续系统（命格/纳戒/小世界…）只往 ext 里加键，不再改表。"""

    uid: str
    name: str = ""
    realm_table: str = DEFAULT_REALM_TABLE
    realm_index: int = 0
    exp: int = 0
    stones: int = 0
    state: str = "空闲"
    state_start: float = 0.0
    created_at: float = Field(default_factory=time.time)
    ext: dict[str, Any] = Field(default_factory=dict)


def create_player(uid: str, name: str, level_table: list[dict]) -> PlayerDoc:
    """从境界表生成初始玩家：固定从第 0 境开始，属性取表内基础值。"""
    entry = level_table[0] if level_table else {}
    return PlayerDoc(
        uid=uid,
        name=name,
        realm_index=0,
        stones=100,
        ext={"base_attack": entry.get("基础攻击", 0), "base_defense": entry.get("基础防御", 0),
             "base_hp": entry.get("基础血量", 0)},
    )


def realm_entry(doc: PlayerDoc, level_table: list[dict]) -> dict:
    """玩家当前境界条目；表越界时回退到最后一境。"""
    if not level_table:
        return {}
    i = min(max(doc.realm_index, 0), len(level_table) - 1)
    return level_table[i]


def next_realm_entry(doc: PlayerDoc, level_table: list[dict]) -> dict | None:
    i = doc.realm_index + 1
    return level_table[i] if 0 < i < len(level_table) else None
