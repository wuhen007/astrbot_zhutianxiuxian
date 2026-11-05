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


# ---------------------------------------------------------------- 内置技能（W7-0）
# W1-1 留了 on_turn 扩展点，但注册表一直为空、Fighter.skills 也从未被赋值，
# 整条技能链路从未真正跑过。先注册两个「纯观测型」钩子把链路接通：只写战报、
# 不改任何战斗数值；有数值的档位特效留 W7-4 往同一注册表里加。
def _echo_once(atk_u, def_u, ctx) -> None:
    title = str(ctx.get("title", "功法共鸣"))
    key = "_echo_" + title
    if atk_u.tags.get(key):
        return
    atk_u.tags[key] = True
    log = ctx.get("log")
    if isinstance(log, list):
        log.append(f"【{title}】{atk_u.name} 与所修功法相合"
                   f"（第 {ctx.get('round', 1)} 回合）")


BUILTIN_SKILLS = (
    SkillSpec(id="prof_echo", name="功法共鸣",
              on_turn=lambda a, b, c: _echo_once(a, b, {**c, "title": "功法共鸣"}),
              meta={"kind": "observe", "gate": "prof>=250"}),
    SkillSpec(id="dual_echo", name="双轨共鸣",
              on_turn=lambda a, b, c: _echo_once(a, b, {**c, "title": "双轨共鸣"}),
              meta={"kind": "observe", "gate": "both_tracks>=10"}),
)


def ensure_builtin() -> None:
    """幂等注册（自检里 clear() 之后再次装填会自动恢复）。"""
    for spec in BUILTIN_SKILLS:
        if spec.id not in _REGISTRY:
            _REGISTRY[spec.id] = spec
