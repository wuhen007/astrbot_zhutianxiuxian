"""禁地 / 仙境（原版 apps/SecretPlace `Goforbiddenarea` 与仙境同构）。

对齐原版的三处关键行为：
1. **先前往、后结算**：出发即扣寿元，30 分钟后归来才发奖励（不是即点即得）
2. **境界门槛**：禁地 22 起，诸神黄昏·旧神界 46，始源·混沌初开之地 64
3. **法身代行**：法身存在且不在行动中时，由法身代行，真身不受行动锁定

shortcut: 原版用 redis action 队列 + 定时任务结算；本移植落在 ext["forbidden_trip"]，
由任意入口惰性结算（查看列表 / 再次前往时触发），不依赖后台定时器。
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

KINDS = {"forbidden": ("禁地列表", "禁地"), "fairy": ("仙境列表", "仙境")}
TIERS = (("one", 60), ("two", 30), ("three", 10))
TRIP_MINUTES = 30
GATES = {"诸神黄昏·旧神界": 46, "始源·混沌初开之地": 64}
DEFAULT_GATE = 22
EXT_KEY = "forbidden_trip"
# 原版沉迷（SecretPlaceplus.js:1408 Goforbiddenarea）：N 组 = 10N 轮，总时长 N*10*7 分钟，
# 资源按单程的 10*N 计（灵石 Price / 寿元 shouyuan / 修为 experience）+ 秘境之匙 N 把。
ADDICT_ROUNDS_PER_COUNT = 10
ADDICT_MINUTES_PER_ROUND = 7
ADDICT_COST_MULT = 10
ADDICT_MAX_COUNT = 12


def table_of(content: Any, kind: str) -> list[dict[str, Any]]:
    fname, _label = KINDS[kind]
    rows = content.table(f"item/副本/{fname}")
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []


def names(rows: list[Mapping[str, Any]]) -> list[str]:
    return [str(r.get("name")) for r in rows if r.get("name")]


def find(rows: list[Mapping[str, Any]], name: str) -> dict[str, Any] | None:
    key = str(name or "").strip()
    return next((dict(r) for r in rows if str(r.get("name")) == key), None)


def label_of(kind: str) -> str:
    return KINDS[kind][1]


def gate_of(land: Mapping[str, Any]) -> int:
    return GATES.get(str(land.get("name")), DEFAULT_GATE)


def panel(rows: list[Mapping[str, Any]], kind: str) -> str:
    label = label_of(kind)
    lines = [f"【{label}】共 {len(rows)} 处｜单程 {TRIP_MINUTES} 分钟，归来结算"]
    for r in rows:
        pools = [len(r.get(k) or []) for k, _w in TIERS]
        lines.append(f"· {r.get('name')}（{r.get('Grade') or '?'}）"
                     f"境界 {gate_of(r)}｜寿元 {int(r.get('shouyuan', 0) or 0)}"
                     f"｜奖池 {'/'.join(str(x) for x in pools)}")
    lines.append(f"前往：#前往{label} 地点名（法身闲暇时代行）")
    return "\n".join(lines)


def trip_of(doc: Any) -> dict[str, Any] | None:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return None
    trip = ext.get(EXT_KEY)
    return trip if isinstance(trip, Mapping) and trip.get("end_at") else None


def _fashan_ready(doc: Any) -> bool:
    """法身已凝聚、不在行动中（真身是否同位面不强制，原版亦只校验法身可用）。"""
    try:
        from . import fashan
        st = fashan.state_of(doc)
        return bool(st.get("owned")) and st.get("state") != "行动中"
    except Exception:
        return False


def _lifespan_of(doc: Any) -> int:
    try:
        from . import lifespan
        return int(lifespan.shouyuan_of(doc))
    except Exception:
        return int((getattr(doc, "ext", {}) or {}).get("shouyuan", 0) or 0)


def _set_lifespan(doc: Any, value: int) -> None:
    try:
        from . import lifespan
        if lifespan.set_shouyuan(doc, value):
            return
    except Exception:
        pass
    doc.ext["shouyuan"] = max(1, int(value))


def _costs_of(land: Mapping[str, Any], mult: int) -> tuple[int, int, int]:
    """(灵石, 寿元, 修为) 单程费用 × mult；空字段按 0。"""
    price = int(land.get("Price", 0) or 0) * mult
    sy = int(land.get("shouyuan", 0) or 0) * mult
    exp = int(land.get("experience", 0) or 0) * mult
    return price, sy, exp


def begin(doc: Any, land: Mapping[str, Any], kind: str, now: float) -> tuple[bool, str]:
    """出发：校验境界与灵石/寿元/修为（原版三者不足均拦截），扣费，登记 30 分钟行程。"""
    label = label_of(kind)
    name = str(land.get("name") or "")
    realm = int(getattr(doc, "realm_index", 0) or 0)
    need = gate_of(land)
    if realm < need:
        hint = "化神" if need == DEFAULT_GATE else ("金仙" if need == 46 else "无境")
        return False, f"没有达到{hint}之前还是不要去了（需境界 {need}，当前 {realm}）。"
    if trip_of(doc):
        return False, "你已在前往途中，归来后才能再出发。"
    stones, sy_cost, exp_cost = _costs_of(land, 1)
    if stones and int(getattr(doc, "stones", 0) or 0) < stones:
        return False, f"没有灵石寸步难行，攒到 {stones:,} 灵石才够哦～"
    if exp_cost and int(getattr(doc, "exp", 0) or 0) < exp_cost:
        return False, f"你需要积累 {exp_cost:,} 修为，才能抵抗{label}魔气！"
    cur_sy = _lifespan_of(doc)
    if sy_cost and cur_sy < sy_cost:
        return False, "道友这点寿元就不要去了吧，免得原地坐化了。"
    doc.stones = max(0, int(getattr(doc, "stones", 0) or 0) - stones)
    doc.exp = max(0, int(getattr(doc, "exp", 0) or 0) - exp_cost)
    if sy_cost:
        _set_lifespan(doc, cur_sy - sy_cost)
    cost_note = "、".join(t for t, v in (("寿元", sy_cost), ("灵石", stones), ("修为", exp_cost)) if v)
    actor = "fashan" if _fashan_ready(doc) else "self"
    doc.ext[EXT_KEY] = {
        "kind": kind, "name": name, "actor": actor,
        "land": dict(land),
        "start_at": float(now), "end_at": float(now) + TRIP_MINUTES * 60,
    }
    if actor == "fashan":
        return True, (f"【法身代行】\n{doc.name} 盘坐不动，一缕法身降临{label}，"
                      f"代真身探索{name}！\n法身行动：{TRIP_MINUTES} 分钟后归来"
                      f"（消耗 {cost_note}）。")
    return True, (f"开始前往{label}「{name}」，{TRIP_MINUTES} 分钟后归来"
                  f"（消耗 {cost_note}）。")


def begin_addiction(doc: Any, land: Mapping[str, Any], kind: str, count: int,
                    now: float, keys: int = 0, free_entry: bool = False,
                    consume_keys: Any = None) -> tuple[bool, str]:
    """沉迷连刷（原版 Goforbiddenarea 沉迷分支）：10N 轮、7 分钟一轮，资源 10N 计 + 秘境之匙 N。

    consume_keys(数量) 由 handler 提供纳戒扣钥匙回调；free_entry（岁云）免钥匙。
    """
    label = label_of(kind)
    name = str(land.get("name") or "")
    count = max(1, min(ADDICT_MAX_COUNT, int(count or 1)))
    realm = int(getattr(doc, "realm_index", 0) or 0)
    need = gate_of(land)
    if realm < need:
        hint = "化神" if need == DEFAULT_GATE else ("金仙" if need == 46 else "无境")
        return False, f"没有达到{hint}之前还是不要去了（需境界 {need}，当前 {realm}）。"
    if trip_of(doc):
        return False, "你已在前往途中，归来后才能再出发。"
    entry_keys = 0 if free_entry else max(0, int(count))
    if entry_keys and int(keys or 0) < entry_keys:
        return False, f"你需要 {entry_keys} 个秘境之匙才能沉迷此{label}。"
    mult = ADDICT_COST_MULT * count
    stones, sy_cost, exp_cost = _costs_of(land, mult)
    if stones and int(getattr(doc, "stones", 0) or 0) < stones:
        return False, f"没有灵石寸步难行，攒到 {stones:,} 灵石才够哦～"
    if exp_cost and int(getattr(doc, "exp", 0) or 0) < exp_cost:
        return False, f"你需要积累 {exp_cost:,} 修为，才能抵抗{label}魔气！"
    cur_sy = _lifespan_of(doc)
    if sy_cost and cur_sy < sy_cost:
        return False, "道友这点寿元就不要去了吧，免得原地坐化了。"
    if entry_keys and consume_keys is not None and not consume_keys(entry_keys):
        return False, "秘境之匙数量已变化，本次未扣费。"
    doc.stones = max(0, int(getattr(doc, "stones", 0) or 0) - stones)
    doc.exp = max(0, int(getattr(doc, "exp", 0) or 0) - exp_cost)
    if sy_cost:
        _set_lifespan(doc, cur_sy - sy_cost)
    rounds = ADDICT_ROUNDS_PER_COUNT * count
    interval = ADDICT_MINUTES_PER_ROUND * 60
    cost_note = "、".join(t for t, v in (("寿元", sy_cost), ("灵石", stones), ("修为", exp_cost)) if v)
    if entry_keys:
        cost_note += f"、秘境之匙×{entry_keys}"
    actor = "fashan" if _fashan_ready(doc) else "self"
    doc.ext[EXT_KEY] = {
        "kind": kind, "name": name, "actor": actor, "land": dict(land),
        "addict": True, "start_at": float(now),
        "end_at": float(now) + rounds * interval,
        "rounds_total": rounds, "rounds_done": 0,
        "interval": float(interval),
    }
    total_min = ADDICT_MINUTES_PER_ROUND * rounds
    head = "【法身代行】" if actor == "fashan" else ""
    return True, (f"{head}开始沉迷{label}「{name}」×{count} 组：共 {rounds} 轮，"
                  f"每轮 {ADDICT_MINUTES_PER_ROUND} 分钟（总 {total_min} 分钟），逐轮自动结算。\n"
                  f"消耗 {cost_note}。发送 #沉迷禁地/{label}任意指令 或 #沉迷收获 查看进度。")


def _roll_round(land: Mapping[str, Any], rng: Any, gains: dict[str, int]) -> int:
    """一轮奖励：抽档取物 + 修为（与单程同模型），返回本轮修为增量。"""
    tier = rng.choices([t for t, _w in TIERS], weights=[w for _t, w in TIERS])[0]
    pool = land.get(tier) or []
    if pool:
        row = rng.choice(list(pool))
        item = str(row.get("name") or "")
        if item:
            gains[item] = gains.get(item, 0) + max(1, int(row.get("amount", 1) or 1))
    return int(land.get("experience", 0) or 0)


def settle(doc: Any, now: float, rng: Any | None = None) -> tuple[bool, str, dict[str, int]]:
    """归来/逐轮结算：单程到点整趟发奖；沉迷按已到轮次批量落账。未到点返回 (False, "", {})。"""
    rng = rng or random
    trip = trip_of(doc)
    if not trip:
        return False, "", {}
    kind = str(trip.get("kind") or "forbidden")
    label = label_of(kind)
    name = str(trip.get("name") or "")
    land = trip.get("land") if isinstance(trip.get("land"), Mapping) else {}
    who = "法身" if trip.get("actor") == "fashan" else "你"
    gains: dict[str, int] = {}
    if not trip.get("addict"):
        if float(trip.get("end_at", 0) or 0) > now:
            return False, "", {}
        exp_gain = _roll_round(land, rng, gains)
        if exp_gain:
            doc.exp = int(getattr(doc, "exp", 0) or 0) + exp_gain
        doc.ext.pop(EXT_KEY, None)
        body = "、".join(f"{k}×{v}" for k, v in gains.items()) or "空手而归"
        return True, (f"【{label}·{name}】{who}归来：\n{body}"
                      + (f"\n修为 +{exp_gain:,}" if exp_gain else "")), gains
    # 沉迷：按 7 分钟/轮批量结算已到轮次（原版首结算点在出发后一个间隔）
    interval = max(60.0, float(trip.get("interval") or ADDICT_MINUTES_PER_ROUND * 60))
    start_at = float(trip.get("start_at") or now)
    total = max(1, int(trip.get("rounds_total") or 1))
    done = max(0, int(trip.get("rounds_done") or 0))
    due = min(total, int((now - start_at) // interval))
    if due <= done:
        return False, "", {}
    exp_sum = 0
    for _ in range(due - done):
        exp_sum += _roll_round(land, rng, gains)
    trip["rounds_done"] = due
    if exp_sum:
        doc.exp = int(getattr(doc, "exp", 0) or 0) + exp_sum
    body = "、".join(f"{k}×{v}" for k, v in gains.items()) or "空手而归"
    if due >= total:
        doc.ext.pop(EXT_KEY, None)
        return True, (f"【{label}·{name}】沉迷完成（{total} 轮）：\n{body}"
                      + (f"\n修为 +{exp_sum:,}" if exp_sum else "")), gains
    left_min = int((start_at + interval * total - now) // 60) + 1
    return True, (f"【{label}·{name}】沉迷进度 {due}/{total} 轮，本轮收获：\n{body}"
                  + (f"\n修为 +{exp_sum:,}" if exp_sum else "")
                  + f"\n剩余约 {left_min} 分钟自动结算。"), gains


def remaining_text(doc: Any, now: float) -> str:
    trip = trip_of(doc)
    if not trip:
        return ""
    left = max(0, int(float(trip.get("end_at", 0) or 0) - now))
    who = "法身" if trip.get("actor") == "fashan" else "你"
    if trip.get("addict"):
        total = max(1, int(trip.get("rounds_total") or 1))
        done = max(0, int(trip.get("rounds_done") or 0))
        return (f"{who}正在沉迷{label_of(str(trip.get('kind') or 'forbidden'))}"
                f"「{trip.get('name')}」，进度 {done}/{total} 轮，"
                f"约 {left // 60} 分后全部归来。")
    return (f"{who}正在前往{label_of(str(trip.get('kind') or 'forbidden'))}"
            f"「{trip.get('name')}」，约 {left // 60} 分后归来。")
