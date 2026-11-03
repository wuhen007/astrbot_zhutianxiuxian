"""技能注册表（W1-1 扩展点，W1-2 起填充）。

技能 = 出手前的 on_turn 钩子：可修改双方 effects（上盾/定身/乘区）、直接写战报，
也可通过 ctx["rng"] 做概率判定。注册项来自原版技能池（daofa/功法/天赋），W1-2 落第一批。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅类型标注，避免与 engine 循环导入
    from .engine import Fighter

OnTurn = Callable[["Fighter", "Fighter", dict[str, Any]], None]


@dataclass(frozen=True)
class SkillSpec:
    id: str
    name: str
    on_turn: OnTurn | None = None
    meta: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, SkillSpec] = {}


def register(spec: SkillSpec) -> None:
    _REGISTRY[spec.id] = spec


def get(skill_id: str) -> SkillSpec | None:
    return _REGISTRY.get(skill_id)


def all_skills() -> dict[str, SkillSpec]:
    return dict(_REGISTRY)


def clear() -> None:
    """仅测试用：清空注册表。"""
    _REGISTRY.clear()
