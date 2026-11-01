"""宗门系统：创建/加入/退出/捐献/升级（纯函数，无 IO）。

对齐原版规则：创建需境界门槛 + 灵石（原版化神 + 1 万）；成员关系存玩家 ext["sect"]。
升级费用取自宗门基金：level² × LEVEL_COST_BASE；等级上限 MAX_LEVEL。
"""

from __future__ import annotations

CREATE_GATE = 5            # 创建宗门的境界序号门槛（原版化神，此处对应第 6 境）
CREATE_COST = 10_000       # 创建费用（灵石）
MAX_LEVEL = 9
LEVEL_COST_BASE = 5_000    # 升级费用 = LEVEL_COST_BASE × 目标等级²
MEMBER_LIMIT_BASE = 8      # 成员上限 = 基数 + 等级 × 2


def member_limit(level: int) -> int:
    return MEMBER_LIMIT_BASE + level * 2


def upgrade_cost(current_level: int) -> int:
    """从 current_level 升到 current_level+1 的费用。"""
    return LEVEL_COST_BASE * (current_level + 1) ** 2


def can_create(doc, stones_cost: int = CREATE_COST) -> tuple[bool, str]:
    if doc.ext.get("sect"):
        return False, "道友已有宗门。"
    if doc.realm_index < CREATE_GATE:
        return False, f"修为不足：创建宗门需达到第 {CREATE_GATE + 1} 境。"
    if doc.stones < stones_cost:
        return False, f"灵石不足：创建宗门需 {stones_cost} 灵石。"
    return True, ""


def level_title(level: int) -> str:
    titles = ("不入流", "三流", "二流", "一流", "顶尖", "超凡", "绝世", "圣地", "至尊")
    return titles[min(max(level, 1), MAX_LEVEL) - 1]
