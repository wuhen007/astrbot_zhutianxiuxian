"""权柄换算（W0-2）：统一双轨境界 → 权柄，替代散落的 realm_index 直读。

原版（model/realmAuthority.js）：权柄 = max(秘境等级, 仙古映射, 花粉映射)，
即**只由三条额外体系决定**，练气/炼体不算权柄。本移植三条额外体系未开放
（秘境/仙古/花粉轨见推进计划 W0-3），故按双轨语义适配：

- authority_of(doc)          原始权柄（0-63）= max(练气 realm_index, 炼体 physique_index)
- authority_21(doc)          原版 0-21 档位（供彼岸等按 21 档判定的系统）
- meets(doc, gate)           门槛判定：双轨任一达标即可（炼体流玩家同样解锁位面/渡劫）

位面门槛（core/plane.GATES）、后续渡劫/轮回门槛一律改走本模块；
shortcut: 原版三体系权威映射表未搬；W8-B 起改为 `register_track()` 注册制，
花粉/岁云/记忆落地时各自注册，避免本模块反向依赖具体体系。
"""

from __future__ import annotations

from typing import Any

MAX_LEVEL = 63
AUTHORITY_TIERS = 21

# W8-B 第三轨注册表：花粉 / 岁云 / 记忆各自 register_track(折算函数) 后自动并入 max 链。
# 只影响门槛与 PVP 天堑（决策 1），不直接给三维乘区——乘区留给套装/至宝/体质。
_TRACK_HOOKS: list = []


def register_track(fn) -> None:
    """登记一条额外体系的等效境界换算（返回 0-63 的境界下标）。"""
    if callable(fn) and fn not in _TRACK_HOOKS:
        _TRACK_HOOKS.append(fn)


def extra_levels(doc: Any) -> list[int]:
    out = []
    for fn in _TRACK_HOOKS:
        try:
            out.append(max(0, min(MAX_LEVEL, int(fn(doc)))))
        except Exception:
            out.append(0)
    return out


def authority_of(doc: Any) -> int:
    """双轨 + 已登记的第三轨取高的原始权柄（0-63）。"""
    realm = int(getattr(doc, "realm_index", 0) or 0)
    physique = int(getattr(doc, "physique_index", 0) or 0)
    return max([realm, physique, *extra_levels(doc)])


def dual_level(doc: Any) -> int:
    """1-based 双轨境界（展示用）。"""
    return authority_of(doc) + 1


def authority_21(doc: Any) -> int:
    """折算到原版 0-21 权柄档（彼岸/高维系统用）。"""
    return min(AUTHORITY_TIERS, authority_of(doc) * AUTHORITY_TIERS // MAX_LEVEL)


def meets(doc: Any, gate: int) -> bool:
    """双轨任一轨达到 gate（0-based 境界下标）即通过。"""
    return authority_of(doc) >= max(0, int(gate))
