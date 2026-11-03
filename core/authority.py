"""权柄换算（W0-2）：统一双轨境界 → 权柄，替代散落的 realm_index 直读。

原版（model/realmAuthority.js）：权柄 = max(秘境等级, 仙古映射, 花粉映射)，
即**只由三条额外体系决定**，练气/炼体不算权柄。本移植三条额外体系未开放
（秘境/仙古/花粉轨见推进计划 W0-3），故按双轨语义适配：

- authority_of(doc)          原始权柄（0-63）= max(练气 realm_index, 炼体 physique_index)
- authority_21(doc)          原版 0-21 档位（供彼岸等按 21 档判定的系统）
- meets(doc, gate)           门槛判定：双轨任一达标即可（炼体流玩家同样解锁位面/渡劫）

位面门槛（core/plane.GATES）、后续渡劫/轮回门槛一律改走本模块；
shortcut: 原版三体系权威映射表未搬（等 W0-3 开放对应体系时再接入 max 链）。
"""

from __future__ import annotations

from typing import Any

MAX_LEVEL = 63
AUTHORITY_TIERS = 21


def authority_of(doc: Any) -> int:
    """双轨取高的原始权柄（0-63）。"""
    realm = int(getattr(doc, "realm_index", 0) or 0)
    physique = int(getattr(doc, "physique_index", 0) or 0)
    return max(realm, physique)


def dual_level(doc: Any) -> int:
    """1-based 双轨境界（展示用）。"""
    return authority_of(doc) + 1


def authority_21(doc: Any) -> int:
    """折算到原版 0-21 权柄档（彼岸/高维系统用）。"""
    return min(AUTHORITY_TIERS, authority_of(doc) * AUTHORITY_TIERS // MAX_LEVEL)


def meets(doc: Any, gate: int) -> bool:
    """双轨任一轨达到 gate（0-based 境界下标）即通过。"""
    return authority_of(doc) >= max(0, int(gate))
