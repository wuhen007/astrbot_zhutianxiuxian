"""至宝灵宝熔炼（原版 #熔炼灵宝 功能移植）。

逻辑：
- 指定至宝名（需已执掌本体）。
- 层数 0-10，每层消耗递增（灵石+源石），全属性 +8。
- 达到 10 层后圆满。
"""

from __future__ import annotations

from typing import Any

MAX_LAYERS = 10
ATTR_BOOST = 8

def get_cost(layers: int) -> tuple[int, int]:
    """消耗：灵石 (1000w * (layers+1)^2) + 源石 (50 * (layers+1)^2)"""
    factor = (layers + 1) ** 2
    return 10_000_000 * factor, 50 * factor


def refine(doc: Any, treasure_name: str) -> tuple[bool, str]:
    from . import dibing as db_mod
    
    # 查找持有至宝
    w = db_mod.system_of(doc)
    if not w or w.get("name") != treasure_name:
        # 需检查是否在至宝表里，代码仅检查当前持有
        return False, f"你尚未执掌「{treasure_name}」本体，无法熔炼。"
    
    layers = int(w.get("灵宝熔炼", 0) or 0)
    if layers >= MAX_LAYERS:
        return False, f"「{treasure_name}」已熔炼至极限（{MAX_LAYERS}/{MAX_LAYERS}），灵性圆满。"
    
    # 扣费校验
    cost_lingshi, cost_yuanshi = get_cost(layers)
    if int(doc.stones) < cost_lingshi:
        return False, f"熔炼需要灵石 {cost_lingshi:,}，家底不够。"
    # 源石处理（需明确其存储位置）
    # 假设源石在 ext['materials']['yuan-shi']
    mats = doc.ext.setdefault("materials", {})
    if int(mats.get("yuan-shi", 0)) < cost_yuanshi:
        return False, f"熔炼需要源石 {cost_yuanshi:,}，家底不够。"
        
    # 实际扣费
    doc.stones -= cost_lingshi
    mats["yuan-shi"] -= cost_yuanshi
    
    # 实际执行
    w = doc.ext.setdefault("dibing", {})
    w["全属性"] = int(w.get("全属性", 0) or 0) + ATTR_BOOST
    w["灵宝熔炼"] = layers + 1
    
    return True, f"【灵宝熔炼】「{treasure_name}」熔炼层数 {layers} → {layers + 1}（全属性 +{ATTR_BOOST}）。"
