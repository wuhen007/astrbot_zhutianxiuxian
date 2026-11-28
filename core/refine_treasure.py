"""至宝灵宝熔炼（原版 #熔炼灵宝 功能移植）。

逻辑：
- 指定至宝名（需已执掌本体）。
- 层数 0-10，消耗 20 灵宝残片 + 1e8 灵石 + 2e7 源石，全属性 +8。
- 达到 10 层后圆满。
"""

from __future__ import annotations

from typing import Any

MAX_LAYERS = 10
ATTR_BOOST = 8

def refine(doc: Any, treasure_name: str) -> tuple[bool, str]:
    # 查找持有至宝
    w = doc.ext.get("dibing") or {}
    if not isinstance(w, dict) or w.get("name") != treasure_name:
        return False, f"你尚未执掌「{treasure_name}」本体，无法熔炼。"
    
    layers = int(w.get("灵宝熔炼", 0) or 0)
    if layers >= MAX_LAYERS:
        return False, f"「{treasure_name}」已熔炼至极限（{MAX_LAYERS}/{MAX_LAYERS}），灵性圆满。"
    
    # 消耗：20 灵宝残片 + 1e8 灵石 + 2e7 源石
    fragments = int(doc.ext.setdefault("lingbao_canpian", {}).get(treasure_name, 0) or 0)
    if fragments < 20:
        return False, f"「{treasure_name}」灵宝残片不足（{fragments}/20），多参与择主之争收集吧。"
        
    cost_lingshi = 100_000_000
    cost_yuanshi = 20_000_000
    if int(doc.stones) < cost_lingshi:
        return False, f"熔炼需要灵石 {cost_lingshi:,}，家底不够。"
    if int(doc.ext.get("yuanshi", {}).get("amount", 0)) < cost_yuanshi:
        return False, f"熔炼需要源石 {cost_yuanshi:,}，家底不够。"
        
    # 实际扣费
    doc.ext["lingbao_canpian"][treasure_name] = fragments - 20
    doc.stones -= cost_lingshi
    doc.ext["yuanshi"]["amount"] -= cost_yuanshi
    
    # 实际执行
    w["全属性"] = int(w.get("全属性", 0) or 0) + ATTR_BOOST
    w["灵宝熔炼"] = layers + 1
    
    return True, (f"【灵宝熔炼】\n你以 20 枚「{treasure_name}」灵宝残片为薪，引灵焰温养至宝，{treasure_name}灵性渐复！\n"
                  f"熔炼层数 {layers} → {layers + 1}（全属性 +{ATTR_BOOST}，当前 {w['全属性']}）\n"
                  "「残片归元，至宝通灵」")
