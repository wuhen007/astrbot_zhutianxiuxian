"""沉迷秘境：限时挂机刷秘境，按原版队列逐轮结算并保存奖励。

原版：
- `#沉迷秘境 地点*次数`（1-12），原版每次数进行 10 轮、基础总时长 70 分钟，
  每轮定时结算；原版另按地点 Price/shouyuan 字段与 entryKeys 扣除资源。
- 本地四个沉迷地点是自定义映射，未找到对应原版价格/寿元/钥匙字段；费用沿用现有地点灵石规则，不凭空增加寿元或钥匙扣费。
- `#沉迷收获` 查看结算结果，`#清除沉迷记录`

本移植（B9）：
- 沿用本插件 4 个自定义秘境地点；轮数/基础总时长已对齐原版 10 轮、70 分钟/次
- 原版具体地点 Price/shouyuan/entryKeys 没有与这 4 个地点对应的数据；因此保留现有灵石入口消耗和本地秘境奖励模型，不猜新寿元/钥匙价格
- 每轮到时后独立模拟并落账；战败后停止后续轮次，既有轮次奖励不回滚
- 记录存 `ext["addiction"]`（进行中）与 `ext["addiction_history"]`（最近 5 次）

W7-1：补齐原版结算单记录的 11 个字段（location / location_type / total_count /
settled_count / death_count / xiuwei_gained / xueqi_gained / items_gained /
status / start_time / end_time），逐轮累加并在 #沉迷收获 输出完整面板。
shortcut：法身双 actor、HTML 渲染面板、清除记录锁、寿元/秘境之匙消耗未复刻。
"""

from __future__ import annotations

import copy
import random
import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any

from . import secret
from .battle import Unit

PLACE_COST = 100_000          # 原版地点数据未映射到本地4个自定义秘境，保留现有入口价格
MINUTES_PER_COUNT = 70        # 固定原版 SecretPlaceplus.js：i * 10 * 7 分钟
ROUNDS_PER_COUNT = 10         # 固定原版 SecretPlaceplus.js：10 * i 次逐轮结算
MAX_COUNT = 12
MAX_HISTORY = 5
ROUND_EARLY_SECONDS = 60  # 原版检查 next_settle_time - 1 分钟


def cost_of(place: str, count: int) -> int:
    factor = secret.place_factor(place)
    return int(PLACE_COST * max(1, int(count)) * factor)


def rounds_of(count: int) -> int:
    return max(1, int(count)) * ROUNDS_PER_COUNT


def make(place: str, count: int, now: float, gate: int = 0) -> dict:
    n = max(1, min(MAX_COUNT, int(count or 1)))
    start = float(now)
    rounds = rounds_of(n)
    total_time = n * MINUTES_PER_COUNT
    end = start + total_time * 60
    interval = total_time * 60 / rounds
    return {
        "settlement_id": secrets.token_hex(16),
        "place": place, "count": n, "rounds": rounds, "done": 0,
        "deaths": 0, "stones": 0, "items": {}, "exp": 0, "log": [],
        "session": {"floor": 0, "stones": 0, "items": {}, "factor": 0.0,
                    "sect_name": "", "boss_kills": 0, "dungeon": ""},
        "start": start, "end": end, "total_time": total_time,
        "interval": interval, "next_settle_time": start + interval,
        "remaining_time": end - start, "settled_count": 0,
        "gate": int(gate or 0), "status": "running",
        "location": str(place), "location_type": "秘境",
        "total_count": rounds, "death_count": 0,
        "xiuwei_gained": 0, "xueqi_gained": 0, "items_gained": {},
        "start_time": start, "end_time": end,
    }


def settlement_id(uid: str, rec: Mapping[str, Any]) -> str:
    current = str(rec.get("settlement_id") or "").strip()
    if current:
        return current
    return "legacy:" + ":".join(str(part or "") for part in (
        uid, rec.get("start"), rec.get("end"), rec.get("place"), rec.get("count")))


def accelerate(rec: Mapping[str, Any], requested_seconds: int,
               now: float) -> tuple[dict[str, Any], int]:
    """Reduce the run deadline and rebuild the next scheduled settlement time."""
    out = copy.deepcopy(dict(rec))
    try:
        end = float(out.get("end", 0) or 0)
        now = float(now)
        requested = max(0, int(requested_seconds))
    except (TypeError, ValueError, OverflowError):
        return out, 0
    if end <= now or requested <= 0:
        return out, 0
    actual = min(requested, max(0, int(end - now)))
    out["end"] = max(now, end - actual)
    out["end_time"] = out["end"]
    out["total_time"] = max(0.0, float(out.get("total_time", 0) or 0) - actual / 60)
    total_rounds = max(1, int(out.get("rounds", out.get("total_count", 1)) or 1))
    settled = max(0, int(out.get("settled_count", out.get("done", 0)) or 0))
    interval = float(out["total_time"]) * 60 / total_rounds
    out["interval"] = interval
    out["next_settle_time"] = max(now, float(out.get("start", 0) or 0) + interval * (settled + 1))
    out["remaining_time"] = max(0.0, float(out["end"]) - now)
    return out, actual


def _round_grace(interval: float) -> float:
    # The original scheduler settles up to one minute early; cap that window
    # below half a round so short ported intervals cannot settle at start.
    return min(ROUND_EARLY_SECONDS, max(0.0, interval * 0.5))


def rounds_due(rec: Mapping, now: float) -> int:
    """Count due rounds using the original one-minute scheduler tolerance."""
    total = max(1, int(rec.get("rounds", 1) or 1))
    settled = min(total, max(0, int(rec.get("settled_count", rec.get("done", 0)) or 0)))
    left = total - settled
    if not left or str(rec.get("status") or "running") != "running":
        return 0
    try:
        current = float(now)
        end = float(rec.get("end", 0) or 0)
        next_time = float(rec.get("next_settle_time", end) or end)
        interval = max(0.0, float(rec.get("interval", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
    if current >= end or interval <= 0:
        return left
    grace = _round_grace(interval)
    due = 0
    while due < left and current > next_time - grace:
        due += 1
        next_time += interval
    return due


def seconds_to_next_round(rec: Mapping, now: float) -> float:
    try:
        interval = max(0.0, float(rec.get("interval", 0) or 0))
        target = float(rec.get("next_settle_time", 0) or 0) - _round_grace(interval)
        return max(0.0, min(float(rec.get("end", target) or target), target) - float(now))
    except (TypeError, ValueError, OverflowError):
        return 0.0

def remaining(rec: Mapping, now: float) -> float:
    return max(0.0, float(rec.get("end", 0) or 0) - float(now))


def fmt_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    m, s = divmod(total, 60)
    return f"{m} 分 {s} 秒" if m else f"{s} 秒"


def simulate_round(rec: Mapping, base: Sequence[int], hp: int, bao: float,
                   item_pool: list[Mapping], rng: random.Random, now: float,
                   speed: int = 100, crit_damage: float | None = None,
                   action_bar: int = 0, realm_id: int = 1,
                   physique_id: int = 1) -> tuple[dict[str, Any], int, dict[str, Any]]:
    """Resolve one due layer and return cumulative state plus this round's reward delta."""
    out = copy.deepcopy(dict(rec))
    saved = out.get("session") if isinstance(out.get("session"), Mapping) else {}
    session = secret.Session(
        place=str(out.get("place") or ""),
        floor=max(0, int(saved.get("floor", 0) or 0)),
        stones=max(0, int(saved.get("stones", 0) or 0)),
        items=dict(saved.get("items") or {}),
        factor=float(saved.get("factor", 0.0) or 0.0),
        sect_name=str(saved.get("sect_name") or ""),
        boss_kills=max(0, int(saved.get("boss_kills", 0) or 0)),
        dungeon=str(saved.get("dungeon") or ""),
    )
    before_stones = session.stones
    before_items = dict(session.items)
    me = Unit("道友·沉迷", int(base[0]), int(base[1]), max(1, int(hp)), float(bao),
              speed=max(1, int(speed)), crit_damage=crit_damage,
              action_bar=max(0, int(action_bar)))
    session, me, flavor, fled = secret.explore(
        session, (int(base[0]), int(base[1]), int(base[2])), me, item_pool, rng
    )
    stone_gain = max(0, int(session.stones) - before_stones)
    if fled:
        exp_gain, xueqi_gain = 800, 0
    else:
        # Original SecretPlaceplusTask per-round victory formula. No local
        # encounter quality exposes the original t1/t2, so its source-defined
        # baseline range (0.5..1.0) is used by original_win_rewards.
        original_rewards = secret.original_win_rewards(
            max(1, int(realm_id)), max(1, int(physique_id)), rng)
        exp_gain = int(original_rewards["exp"])
        xueqi_gain = int(original_rewards["xueqi"])
    item_delta = {
        name: max(0, int(quantity) - int(before_items.get(name, 0) or 0))
        for name, quantity in session.items.items()
        if int(quantity) > int(before_items.get(name, 0) or 0)
    }
    out["done"] = max(0, int(out.get("done", 0) or 0)) + 1
    out["settled_count"] = out["done"]
    out["deaths"] = max(0, int(out.get("deaths", 0) or 0)) + int(bool(fled))
    out["death_count"] = out["deaths"]
    out["stones"] = max(0, int(out.get("stones", 0) or 0)) + stone_gain
    out["exp"] = max(0, int(out.get("exp", 0) or 0)) + exp_gain
    out["xiuwei_gained"] = out["exp"]
    out["xueqi_gained"] = max(0, int(out.get("xueqi_gained", 0) or 0)) + xueqi_gain
    cumulative_items = dict(out.get("items_gained") or out.get("items") or {})
    for name, quantity in item_delta.items():
        cumulative_items[name] = int(cumulative_items.get(name, 0) or 0) + quantity
    out["items"] = cumulative_items
    out["items_gained"] = dict(cumulative_items)
    out["session"] = {
        # Cumulative rewards are credited per round, so carry only exploration state.
        "floor": session.floor, "stones": 0, "items": {},
        "factor": session.factor, "sect_name": session.sect_name,
        "boss_kills": session.boss_kills, "dungeon": session.dungeon,
    }
    out["log"] = (list(out.get("log") or []) + [flavor])[-12:]
    out["next_settle_time"] = float(out.get("next_settle_time", now) or now) + max(
        0.0, float(out.get("interval", 0) or 0))
    out["remaining_time"] = max(0.0, float(out.get("end", now) or now) - float(now))
    total_rounds = max(1, int(out.get("rounds", 1) or 1))
    if fled:
        out["status"] = "died"
    elif out["done"] >= total_rounds:
        out["status"] = "completed"
    if out.get("status") in ("completed", "died"):
        out["settled_at"] = float(now)
        out["end"] = float(now)
        out["end_time"] = float(now)
    delta = {"stones": stone_gain, "exp": exp_gain, "xueqi": xueqi_gain,
             "items": item_delta, "fled": bool(fled), "log": flavor}
    return out, int(me.hp), delta


def simulate(rec: Mapping, base: Sequence[int], hp: int, bao: float,
             item_pool: list[Mapping], rng: random.Random, speed: int = 100,
             crit_damage: float | None = None, action_bar: int = 0) -> tuple[dict, int]:
    """模拟全部层数。返回 (结算记录, 剩余气血)。"""
    out = copy.deepcopy(dict(rec))
    sess = secret.Session(place=str(out["place"]))
    me = Unit("道友·沉迷", int(base[0]), int(base[1]), max(1, int(hp)), float(bao),
              speed=max(1, int(speed)), crit_damage=crit_damage,
              action_bar=max(0, int(action_bar)))
    tiers = int(out.get("rounds", 1) or 1)
    prev_stones = 0
    for _ in range(tiers):
        sess, me, flavor, fled = secret.explore(
            sess, (int(base[0]), int(base[1]), int(base[2])), me, item_pool, rng
        )
        out["done"] = int(out.get("done", 0)) + 1
        out["settled_count"] = int(out["done"])
        delta = max(0, int(sess.stones) - prev_stones)
        prev_stones = int(sess.stones)
        out["xiuwei_gained"] = int(out.get("xiuwei_gained", 0) or 0) + delta // 3
        out["log"] = (list(out.get("log") or []) + [flavor])[-12:]
        if fled:
            out["deaths"] = int(out.get("deaths", 0)) + 1
            break
    out["death_count"] = int(out["deaths"])
    out["stones"] = int(sess.stones)
    out["items"] = dict(sess.items)
    out["items_gained"] = dict(out["items"])
    if out["deaths"]:
        out["stones"] = int(out["stones"] * 0.5)
        out["xiuwei_gained"] = int(out["xiuwei_gained"] * 0.5)
    out["xueqi_gained"] = int(out["xiuwei_gained"])
    out["exp"] = int(out["xiuwei_gained"])
    out["status"] = "completed" if not out["deaths"] else "died"
    out["settled_at"] = time.time()
    return out, int(me.hp)


def _ts(ts: float) -> str:
    if not ts:
        return "—"
    return time.strftime("%m-%d %H:%M", time.gmtime(float(ts) + 8 * 3600))


def summary_text(rec: Mapping) -> str:
    """原版 11 字段完整结算面板。"""
    items = rec.get("items_gained") or rec.get("items") or {}
    lines = [
        "--- 沉迷收获 ---",
        f"地点：{rec.get('location') or rec.get('place')}｜类型：{rec.get('location_type', '秘境')}",
        f"发起次数：{int(rec.get('total_count', rec.get('count', 0)) or 0)}"
        f"｜已结算：{int(rec.get('settled_count', rec.get('done', 0)) or 0)}"
        f"/{int(rec.get('rounds', 0) or 0)} 层｜死亡：{int(rec.get('death_count', rec.get('deaths', 0)) or 0)}",
        f"起止：{_ts(float(rec.get('start_time', rec.get('start', 0)) or 0))}"
        f" → {_ts(float(rec.get('end_time', rec.get('end', 0)) or 0))}",
        f"灵石：+{int(rec.get('stones', 0) or 0):,}"
        f"｜修为：+{int(rec.get('xiuwei_gained', rec.get('exp', 0)) or 0):,}"
        f"｜血气：+{int(rec.get('xueqi_gained', 0) or 0):,}",
    ]
    lines.append("掉落：" + ("、".join(f"{n}×{q}" for n, q in items.items()) if items else "无"))
    if rec.get("deaths"):
        lines.append("※ 战败中断；此前逐轮结算的奖励已保留。")
    status = str(rec.get("status") or "running")
    status_label = {"completed": "已完成", "died": "战败中断", "running": "进行中"}.get(status, status)
    lines.append(f"状态：{status_label}")
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
