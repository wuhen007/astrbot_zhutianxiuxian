"""势力弟子派遣（原版 #派遣势力弟子 功能移植）。

逻辑：
- 根据副本名（`didian_list` 中符合 `DISPATCH_DUNGEON_NAMES` 的）派遣。
- 消耗：灵石 + 打工券(1) + 秘境之匙(1)；每次 30 分钟。
- 收益：副本产出的 30%。
- 限制：单次 max 10 轮。
"""

from __future__ import annotations
import time
from typing import Any

MAX_COUNT = 10
MINUTES_PER_COUNT = 30
YIELD_RATE = 0.3
DUNGEON_NAMES = ["大千世界", "苍穹秘境", "深渊魔域"] # 原版示例，实际读取 data

def get_status(doc: Any) -> dict | None:
    return doc.ext.get("dispatch_task")

def start(doc: Any, dungeon_name: str, count: int) -> tuple[bool, str]:
    if get_status(doc):
        return False, "已有势力弟子在外执行任务，请先 #召回势力弟子 或等待完成。"
    if not (1 <= count <= MAX_COUNT):
        return False, f"派遣次数必须在 1-{MAX_COUNT} 之间。"
    
    # 此处假设存在 data.didian_list（待在主函数中读取）
    # 暂校验名称
    if dungeon_name not in DUNGEON_NAMES:
        return False, f"当前只可派遣弟子前往：{'、'.join(DUNGEON_NAMES)}。"
        
    # 模拟消耗校验与扣除
    # 实际项目中需对接具体的扣费/道具检查
    # ...
    
    task = {
        "dungeon": dungeon_name,
        "count": count,
        "started_at": time.time(),
        "total_time": count * MINUTES_PER_COUNT * 60
    }
    doc.ext["dispatch_task"] = task
    return True, f"【势力弟子派遣】{dungeon_name} 已出发，执行 {count} 轮任务（约 {count * MINUTES_PER_COUNT} 分钟）。"

def recall(doc: Any) -> tuple[bool, str]:
    task = doc.ext.pop("dispatch_task", None)
    if not task:
        return False, "当前无任务执行。"
    return True, f"【召回】弟子已撤离，任务中止。"

def claim(doc: Any) -> tuple[bool, str]:
    task = doc.ext.get("dispatch_task")
    if not task:
        return False, "无收获可领取。"
    if time.time() < task["started_at"] + task["total_time"]:
        return False, "弟子仍在任务中。"
    
    # 结算收益
    doc.ext.pop("dispatch_task")
    return True, f"【收获】弟子带回了 {task['dungeon']} 的探索成果。"
