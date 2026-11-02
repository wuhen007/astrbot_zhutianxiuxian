"""沉迷秘境：限时挂机刷秘境，到点一次性结算（对齐原版 SecretPlaceplus 沉迷）。

原版：
- `#沉迷秘境 地点*次数`（1-12），消耗寿元/灵石/秘境之匙，`次数×10` 次结算，
  总时长 `次数×70` 分钟，期间定时结算，死亡会中断
- `#沉迷收获` 查看/结算，`#清除沉迷记录`

本移植（B9）：
- 沿用本插件 4 个秘境地点，`次数×5` 层，`次数×3` 分钟（3-36 分钟）
- 只收灵石 + 按层数给修为，掉落沿用秘境物品池；没有寿元/秘境之匙体系（文档标注）
- 到点后一次性模拟全部层数；战败即中断，灵石减半、物品保留
- 记录存 `ext["addiction"]`（进行中）与 `ext["addiction_history"]`（最近 5 次）
"""

from __future__ import annotations

import copy
import random
import time
from collections.abc import Mapping, Sequence
from typing import Any

from . import secret
from .battle import Unit

PLACE_COST = 100_000          # 每「次数」基础灵石
MINUTES_PER_COUNT = 3         # 每「次数」耗时（分钟）
ROUNDS_PER_COUNT = 3          # 每「次数」模拟层数
MAX_COUNT = 12
MAX_HISTORY = 5


def cost_of(place: str, count: int) -> int:
    factor = secret.place_factor(place)
    return int(PLACE_COST * max(1, int(count)) * factor)


def rounds_of(count: int) -> int:
    return max(1, int(count)) * ROUNDS_PER_COUNT


def make(place: str, count: int, now: float, gate: int = 0) -> dict:
    n = max(1, min(MAX_COUNT, int(count or 1)))
    return {
        "place": place, "count": n, "rounds": rounds_of(n), "done": 0,
        "deaths": 0, "stones": 0, "items": {}, "exp": 0, "log": [],
        "start": float(now), "end": float(now) + n * MINUTES_PER_COUNT * 60,
        "gate": int(gate or 0), "status": "running",
    }


def remaining(rec: Mapping, now: float) -> float:
    return max(0.0, float(rec.get("end", 0) or 0) - float(now))


def fmt_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    m, s = divmod(total, 60)
    return f"{m} 分 {s} 秒" if m else f"{s} 秒"


def simulate(rec: Mapping, base: Sequence[int], hp: int, bao: float,
             item_pool: list[Mapping], rng: random.Random) -> tuple[dict, int]:
    """模拟全部层数。返回 (结算记录, 剩余气血)。"""
    out = copy.deepcopy(dict(rec))
    sess = secret.Session(place=str(out["place"]))
    me = Unit("道友·沉迷", int(base[0]), int(base[1]), max(1, int(hp)), float(bao))
    tiers = int(out.get("rounds", 1) or 1)
    for _ in range(tiers):
        sess, me, flavor, fled = secret.explore(
            sess, (int(base[0]), int(base[1]), int(base[2])), me, item_pool, rng
        )
        out["done"] = int(out.get("done", 0)) + 1
        out["log"] = (list(out.get("log") or []) + [flavor])[-12:]
        if fled:
            out["deaths"] = int(out.get("deaths", 0)) + 1
            break
    out["stones"] = int(sess.stones)
    out["items"] = dict(sess.items)
    out["exp"] = max(0, int(sess.stones) // 3)
    if out["deaths"]:
        out["stones"] = int(out["stones"] * 0.5)
    out["status"] = "completed" if not out["deaths"] else "died"
    out["settled_at"] = time.time()
    return out, int(me.hp)


def summary_text(rec: Mapping) -> str:
    items = rec.get("items") or {}
    lines = [
        "--- 沉迷收获 ---",
        f"地点：{rec.get('place')}｜进度：{rec.get('done', 0)}/{rec.get('rounds', 0)} 层",
        f"耗时：{fmt_duration(float(rec.get('end', 0) or 0) - float(rec.get('start', 0) or 0))}"
        f"｜死亡：{int(rec.get('deaths', 0) or 0)} 次",
        f"灵石：+{int(rec.get('stones', 0) or 0):,}｜修为：+{int(rec.get('exp', 0) or 0):,}",
    ]
    if items:
        lines.append("掉落：" + "、".join(f"{n}×{q}" for n, q in items.items()))
    else:
        lines.append("掉落：无")
    if rec.get("deaths"):
        lines.append("※ 战败中断，灵石减半（物品保留）。")
    lines.append(f"状态：{'已完成' if rec.get('status') == 'completed' else '已中断'}")
    return "\n".join(lines)


def history_of(doc: Any) -> list[dict]:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = doc if isinstance(doc, dict) else {}
    hist = ext.get("addiction_history")
    return [h for h in hist if isinstance(h, Mapping)] if isinstance(hist, list) else []


def push_history(doc: Any, rec: Mapping) -> Any:
    d = doc.model_copy(deep=True) if hasattr(doc, "model_copy") else copy.deepcopy(doc)
    hist = list(d.ext.get("addiction_history") or [])
    hist.insert(0, dict(rec))
    d.ext["addiction_history"] = hist[:MAX_HISTORY]
    return d
