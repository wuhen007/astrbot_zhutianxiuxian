"""Restart-safe洞天灵身 and道宫神祇 proxy state with portable settlement slices."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import mingge, occupation, xiangu
from .player import PlayerDoc

EXT_KEY = "idle_proxy"
MINUTES_MAX = 2_880
SPIRIT_COST = 20_000_000
HERB_NAMES = (
    "万年凝血草", "万年何首乌", "万年血精草", "万年甜甜花", "万年清心草",
    "古神藤", "万年太玄果", "炼骨花", "魔蕴花", "万年清灵草",
    "万年天魂菊", "仙蕴花", "仙缘草", "太玄仙草",
)
COMMON_WEIGHTS = (0.2, 0.3, 0.2, 0.2, 0.2, 0, 0, 0, 0, 0, 0, 0, 0, 0)
RARE_WEIGHTS = (0.17, 0.22, 0.17, 0.17, 0.17, 0.024, 0.024, 0.024,
                0.024, 0.024, 0.024, 0.024, 0.012, 0.011)


def state_of(doc: PlayerDoc) -> dict[str, Any]:
    raw = doc.ext.get(EXT_KEY)
    legacy = doc.ext.get("legacy_source")
    legacy = legacy if isinstance(legacy, Mapping) else {}
    if isinstance(raw, dict):
        state = copy.deepcopy(raw)
    else:
        legacy_tier = int(legacy.get("灵身", 0) or 0)
        state = {"spirit": {
            "tier": min(9, max(1, int(legacy.get("灵性", 1) or 1))) if legacy_tier else 0,
            "exp": max(0, int(legacy.get("灵性经验", 0) or 0)),
            "task": None,
        }}
    spirit = state.get("spirit")
    spirit = spirit if isinstance(spirit, dict) else {}
    task = spirit.get("task")
    state["spirit"] = {
        "tier": min(9, max(0, int(spirit.get("tier", 0) or 0))),
        "exp": max(0, int(spirit.get("exp", 0) or 0)),
        "injured_until": _injury_timestamp(
            spirit.get("injured_until", legacy.get("灵身重伤至", 0))),
        "task": copy.deepcopy(task) if isinstance(task, dict) else None,
    }
    deity = state.get("deity")
    if not isinstance(deity, dict):
        legacy_tier = int(legacy.get("神祇", 0) or 0)
        injured_until = _injury_timestamp(legacy.get("神祇重伤至", 0))
        deity = {
            "tier": legacy_tier,
            "exp": max(0, int(legacy.get("神祇经验", 0) or 0)),
            "injured_until": injured_until,
            "task": None,
        }
    task = deity.get("task")
    state["deity"] = {
        "tier": min(9, max(0, int(deity.get("tier", 0) or 0))),
        "exp": max(0, int(deity.get("exp", 0) or 0)),
        "injured_until": _injury_timestamp(
            deity.get("injured_until", legacy.get("神祇重伤至", 0))),
        "task": copy.deepcopy(task) if isinstance(task, dict) else None,
    }
    return state


def _injury_timestamp(value: Any) -> float:
    try:
        timestamp = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if timestamp > 10_000_000_000:
        timestamp /= 1_000
    return max(0.0, timestamp)


def deity_state_of(doc: PlayerDoc) -> dict[str, Any]:
    return copy.deepcopy(state_of(doc)["deity"])


def _secret_level(doc: PlayerDoc) -> int:
    legacy = doc.ext.get("legacy_source")
    if isinstance(legacy, Mapping) and legacy.get("mijinglevel_id") is not None:
        return max(0, int(legacy.get("mijinglevel_id") or 0))
    return max(0, int(doc.realm_index) // 2)


def _save(doc: PlayerDoc, state: dict[str, Any]) -> None:
    doc.ext[EXT_KEY] = state


def parse_duration(raw: str) -> tuple[int, bool]:
    text = str(raw or "").strip()
    if not text:
        return 120, False
    match = re.fullmatch(r"(\d+)\s*(分钟|小时|天)?", text)
    if not match:
        raise ValueError("时长格式：灵身代行采药/采矿/狩猎/寻源/地脉引气/寻脉定源，"
                         "神祇代行采药/采矿/狩猎/寻源/地脉引气/寻脉定源；时长可用分钟/小时/天。")
    value = int(match.group(1))
    minutes = value * {None: 1, "分钟": 1, "小时": 60, "天": 1_440}[match.group(2)]
    if minutes < 1:
        raise ValueError("代行时长至少 1 分钟。")
    return min(minutes, MINUTES_MAX), minutes > MINUTES_MAX


def condense_spirit(doc: PlayerDoc) -> tuple[bool, str, PlayerDoc]:
    if xiangu.xg_level_of(doc) < 3:
        return False, "洞天未开，神曦不显！需达洞天境方可凝聚灵身。", doc
    state = state_of(doc)
    if int(state["spirit"]["tier"]) >= 1:
        return False, "洞天之中已有灵身盘坐，可代行诸事。", doc
    xueqi = float(doc.ext.get("xueqi", 0) or 0)
    if doc.exp < SPIRIT_COST or xueqi < SPIRIT_COST:
        return False, (f"凝聚洞天灵身需修为与血气各 {SPIRIT_COST:,}，"
                       f"当前修为 {doc.exp:,}、血气 {int(xueqi):,}。"), doc
    d = doc.model_copy(deep=True)
    d.exp -= SPIRIT_COST
    d.ext["xueqi"] = xueqi - SPIRIT_COST
    state["spirit"] = {"tier": 1, "exp": 0,
                        "injured_until": float(state["spirit"]["injured_until"]), "task": None}
    _save(d, state)
    return True, "洞天灵身·初成\n耗费两千万修为与血气，以原始符文凝出第一尊灵身。", d


def condense_deity(doc: PlayerDoc) -> tuple[bool, str, PlayerDoc]:
    if _secret_level(doc) < 6:
        return False, "你还没有开辟道宫神藏，无法凝聚道宫神祇。", doc
    state = state_of(doc)
    if int(state["deity"]["tier"]) >= 1:
        return False, "你已经具有神祇了。", doc
    xueqi = float(doc.ext.get("xueqi", 0) or 0)
    if doc.exp < SPIRIT_COST or xueqi < SPIRIT_COST:
        return False, (f"凝聚道宫神祇需修为与血气各 {SPIRIT_COST:,}，"
                       f"当前修为 {doc.exp:,}、血气 {int(xueqi):,}。"), doc
    d = doc.model_copy(deep=True)
    d.exp -= SPIRIT_COST
    d.ext["xueqi"] = xueqi - SPIRIT_COST
    state["deity"] = {"tier": 1, "exp": 0,
                       "injured_until": float(state["deity"]["injured_until"]), "task": None}
    _save(d, state)
    return True, "道宫神祇凝练成功\n耗费两千万修为与血气，于五大神藏中凝聚出第一重神祇。", d


def start_proxy(doc: PlayerDoc, now: float, minutes: int, task_id: str,
                kind: str, group_id: str = "") -> tuple[bool, str, PlayerDoc]:
    occupations = {
        "herb": ("采药师", "采药"), "mine": ("采矿师", "采矿"),
        "hunt": ("猎户", "狩猎"),
        "source": ("源师", "寻源"),
        "earth_qi": ("源地师", "地脉引气"),
        "vein": ("源天师", "寻脉定源"),
    }
    if kind not in occupations:
        return False, "灵身代行任务类型无效。", doc
    required_job, label = occupations[kind]
    state = state_of(doc)
    spirit = state["spirit"]
    if spirit["tier"] < 1:
        return False, "你的洞天尚未蕴养出灵身。", doc
    if doc.ext.get("occupation") != required_job:
        return False, f"需先转职为{required_job}，才能让灵身{label}。", doc
    if float(spirit["injured_until"]) > now:
        left = math.ceil((float(spirit["injured_until"]) - now) / 60)
        return False, f"你的灵身仍在养伤，约 {left} 分钟后才能代行。", doc
    if spirit["task"]:
        task = spirit["task"]
        left = max(0, int(math.ceil((float(task["ends_at"]) - now) / 60)))
        active_label = occupations.get(str(task.get("kind")), ("", "采集"))[1]
        return False, f"灵身正在执行{active_label}任务，预计还需 {left} 分钟。", doc
    minutes = int(minutes)
    if not 1 <= minutes <= MINUTES_MAX or not task_id:
        return False, "代行时长须为 1 至 2880 分钟。", doc
    d = doc.model_copy(deep=True)
    state["spirit"]["task"] = {
        "kind": kind, "task_id": str(task_id), "started_at": float(now),
        "ends_at": float(now) + minutes * 60, "minutes": minutes,
        "group_id": str(group_id or ""),
    }
    _save(d, state)
    return True, f"灵身代行{label}启程，计划 {minutes} 分钟；结束时发送 #结束灵身代行 结算。", d


def start_herb_proxy(doc: PlayerDoc, now: float, minutes: int, task_id: str,
                     group_id: str = "") -> tuple[bool, str, PlayerDoc]:
    return start_proxy(doc, now, minutes, task_id, "herb", group_id)


def start_deity_herb_proxy(doc: PlayerDoc, now: float, minutes: int, task_id: str,
                           group_id: str = "") -> tuple[bool, str, PlayerDoc]:
    return start_deity_proxy(doc, now, minutes, task_id, "herb", group_id)


def start_deity_proxy(doc: PlayerDoc, now: float, minutes: int, task_id: str,
                      kind: str, group_id: str = "") -> tuple[bool, str, PlayerDoc]:
    task_types = {"herb": ("采药师", "采药"), "mine": ("采矿师", "采矿"),
                  "hunt": ("猎户", "狩猎"), "source": ("源师", "寻源"),
                  "earth_qi": ("源地师", "地脉引气"), "vein": ("源天师", "寻脉定源")}
    if kind not in task_types:
        return False, "神祇代行任务类型无效。", doc
    required_job, label = task_types[kind]
    state = state_of(doc)
    deity = state["deity"]
    if deity["tier"] < 1:
        return False, "你没有道宫神祇。", doc
    if doc.ext.get("occupation") != required_job:
        return False, f"需先转职为{required_job}，才能让神祇{label}。", doc
    if float(deity["injured_until"]) > now:
        left = math.ceil((float(deity["injured_until"]) - now) / 60)
        return False, f"你的神祇仍在养伤，约 {left} 分钟后才能代行。", doc
    if deity["task"]:
        task = deity["task"]
        left = max(0, int(math.ceil((float(task.get("ends_at", now)) - now) / 60)))
        return False, f"神祇正在执行代行任务，预计还需 {left} 分钟。", doc
    minutes = int(minutes)
    if not 1 <= minutes <= MINUTES_MAX or not task_id:
        return False, "代行时长须为 1 至 2880 分钟。", doc
    d = doc.model_copy(deep=True)
    state["deity"]["task"] = {
        "kind": kind, "task_id": str(task_id), "started_at": float(now),
        "ends_at": float(now) + minutes * 60, "minutes": minutes,
        "group_id": str(group_id or ""),
    }
    _save(d, state)
    return True, f"神祇代行{label}启程，计划 {minutes} 分钟；结束时发送 #结束神祇代行 结算。", d


def _roll_yield(amount: float, bonus: float, rng: Any) -> int:
    value = max(0.0, float(amount) * max(0.0, 1.0 + float(bonus)))
    whole = math.floor(value)
    return whole + int(rng.random() < value - whole)


def _finish_progress(doc: PlayerDoc, state: dict, minutes: int, items: dict[str, int],
                     exp_table: Sequence[Mapping], factor: float,
                     occupation_exp_per_minute: int = 100,
                     progress_track: str = "spirit") -> tuple[dict, PlayerDoc]:
    d = doc.model_copy(deep=True)
    exp_gain = minutes * int(occupation_exp_per_minute)
    level, exp = occupation.add_exp(
        max(0, int(d.ext.get("occupation_level", 1) or 1)),
        max(0, int(d.ext.get("occupation_exp", 0) or 0)), exp_gain, exp_table)
    d.ext["occupation_level"], d.ext["occupation_exp"] = level, exp
    progress = state[progress_track]
    spirit_exp = int(progress["exp"]) + minutes
    next_tier = int(progress["tier"])
    while next_tier < 9 and spirit_exp >= next_tier * 1_000:
        spirit_exp -= next_tier * 1_000
        next_tier += 1
    if next_tier >= 9:
        spirit_exp = min(spirit_exp, 9_000)
    if progress_track == "deity":
        state["deity"] = {**progress, "tier": next_tier, "exp": spirit_exp, "task": None}
    else:
        state[progress_track] = {
            "tier": next_tier, "exp": spirit_exp,
            "injured_until": _injury_timestamp(progress.get("injured_until")),
            "task": None,
        }
    _save(d, state)
    return {
        "minutes": minutes, "occupation_exp": exp_gain, "items": items,
        "factor": factor, "spirit_tier": next_tier, "spirit_exp": spirit_exp,
        "occupation_level": level,
    }, d


def apply_proxy_ambush(source_doc: PlayerDoc, settled_doc: PlayerDoc, result: dict,
                       progress_track: str, tianjiao_name: str,
                       stolen_items: Mapping[str, int], now: float,
                       exp_table: Sequence[Mapping]) -> str:
    if progress_track not in {"spirit", "deity"}:
        raise ValueError("proxy progress track must be spirit or deity")
    result_items = result.get("items")
    result_items = result_items if isinstance(result_items, dict) else {}
    actual_stolen = {}
    for name, raw_amount in stolen_items.items():
        available = max(0, int(result_items.get(name, 0) or 0))
        amount = min(available, max(0, int(raw_amount or 0)))
        if amount:
            remaining = available - amount
            if remaining:
                result_items[name] = remaining
            else:
                result_items.pop(name, None)
            actual_stolen[name] = amount

    occupation_exp = max(0, int(result.get("occupation_exp", 0) or 0))
    occupation_exp = math.floor(occupation_exp * 0.35)
    level, exp = occupation.add_exp(
        max(0, int(source_doc.ext.get("occupation_level", 1) or 1)),
        max(0, int(source_doc.ext.get("occupation_exp", 0) or 0)),
        occupation_exp, exp_table)
    result["occupation_exp"], result["occupation_level"] = occupation_exp, level
    settled_doc.ext["occupation_level"], settled_doc.ext["occupation_exp"] = level, exp

    state = state_of(settled_doc)
    actor = state[progress_track]
    actor["injured_until"] = max(
        float(actor["injured_until"]), float(now) + 6 * 60 * 60)
    _save(settled_doc, state)

    stolen_line = "、".join(f"{name}×{amount}" for name, amount in actual_stolen.items())
    if not stolen_line:
        stolen_line = "大半职业感悟"
    actor_name = "灵身" if progress_track == "spirit" else "神祇"
    return "\n".join([
        f"【死敌埋伏·{actor_name}重伤】",
        f"{tianjiao_name}早已守在归途，专程截杀你的{actor_name}。",
        f"被夺收益：{stolen_line}；职业经验仅保留35%。",
        f"{actor_name}重伤，需休养6小时后才能再次代行。",
    ])


def apply_overdue_penalty(source_doc: PlayerDoc, settled_doc: PlayerDoc, result: dict,
                          now: float, ends_at: Any,
                          exp_table: Sequence[Mapping]) -> str | None:
    if int(result.get("minutes", 0) or 0) < 1:
        return None
    try:
        end = float(ends_at or 0)
    except (TypeError, ValueError):
        return None
    if end <= 0 or float(now) <= end:
        return None

    overdue_minutes = int((float(now) - end) // 60)
    penalty_rate = min(0.3, overdue_minutes / 60)
    keep_rate = 1.0 - penalty_rate
    result["items"] = {
        name: count for name, qty in result["items"].items()
        if (count := max(0, math.floor(int(qty) * keep_rate))) > 0
    }
    occupation_exp = math.floor(int(result["occupation_exp"]) * keep_rate)
    level, exp = occupation.add_exp(
        max(0, int(source_doc.ext.get("occupation_level", 1) or 1)),
        max(0, int(source_doc.ext.get("occupation_exp", 0) or 0)),
        occupation_exp, exp_table)
    result["occupation_exp"], result["occupation_level"] = occupation_exp, level
    settled_doc.ext["occupation_level"], settled_doc.ext["occupation_exp"] = level, exp
    return f"任务超时{overdue_minutes}分钟，奖励减少{math.floor(penalty_rate * 100)}%"


def finish_deity_herb_proxy(doc: PlayerDoc, now: float, rng: Any,
                            exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    deity = state["deity"]
    task = deity["task"]
    if deity["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "herb":
        return False, {}, doc
    if doc.ext.get("occupation") != "采药师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(deity["tier"])
    factor = 0.5 + tier * 0.05
    items: dict[str, int] = {}
    if minutes:
        realm_id = max(1, int(doc.realm_index) + 1)
        level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
        total = (minutes / 480) * (level * 2 + 12)
        total *= 0.5 if realm_id < 22 else 1.5 if realm_id >= 36 else 1.0
        total = math.floor(total * factor)
        weights = COMMON_WEIGHTS if realm_id < 36 else RARE_WEIGHTS
        bonus = mingge.bonus(doc, "采药加成")
        items = {name: count for name, weight in zip(HERB_NAMES, weights)
                 if (count := _roll_yield(weight * total, bonus, rng)) > 0}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor,
                                 progress_track="deity")
    result.update({"planned_minutes": planned, "kind": "herb"})
    return True, result, d


def finish_deity_mine_proxy(doc: PlayerDoc, now: float, rng: Any,
                            exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    deity = state["deity"]
    task = deity["task"]
    if deity["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "mine":
        return False, {}, doc
    if doc.ext.get("occupation") != "采矿师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    factor = 0.5 + int(deity["tier"]) * 0.05
    items = _mine_items(doc, minutes, factor, rng, exp_table) if minutes else {}
    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor,
                                 progress_track="deity")
    result.update({"planned_minutes": planned, "kind": "mine"})
    return True, result, d


def _hunt_items(doc: PlayerDoc, minutes: int, factor: float,
                exp_table: Sequence[Mapping]) -> dict[str, int]:
    level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
    rate = occupation.rate_of(level, exp_table) * 10 or 1
    rare_amount = minutes // 30
    base_amount = math.floor(4 * (rate + 0.7) * rare_amount)
    realm_id = max(1, int(doc.realm_index) + 1)
    realm_factor = realm_id / (80 if realm_id <= 21 else 40)
    amount = math.floor(math.floor(base_amount * realm_factor) * factor)
    return {name: amount for name in ("野兔", "野猪", "野牛", "野鸡", "野羊")
            if amount > 0}


def finish_deity_hunt_proxy(doc: PlayerDoc, now: float,
                            exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    deity = state["deity"]
    task = deity["task"]
    if deity["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "hunt":
        return False, {}, doc
    if doc.ext.get("occupation") != "猎户":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    factor = 0.5 + int(deity["tier"]) * 0.05
    items = _hunt_items(doc, minutes, factor, exp_table) if minutes else {}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor,
                                 progress_track="deity")
    result.update({"planned_minutes": planned, "kind": "hunt"})
    return True, result, d


def _source_items(doc: PlayerDoc, minutes: int, factor: float, rng: Any,
                  exp_table: Sequence[Mapping]) -> dict[str, int]:
    level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
    rate = occupation.rate_of(level, exp_table) * 10 or 1
    base_amount = math.floor((1.8 + rng.random() * 0.4) * minutes)
    common = math.floor(math.floor(3 * (rate + 1) * base_amount) * factor)
    rare_count = minutes // 30
    upper = math.floor(math.floor(2 * (rate + 0.7) * rare_count) * factor)
    divine = math.floor(math.floor((rate + 0.5) * rare_count) * factor)
    return {name: amount for name, amount in (
        ("下品源石", common), ("中品源石", common), ("上品源石", upper),
        ("神源石", divine), ("凡源药", divine),
    ) if amount > 0}


def finish_deity_source_proxy(doc: PlayerDoc, now: float, rng: Any,
                              exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    deity = state["deity"]
    task = deity["task"]
    if deity["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "source":
        return False, {}, doc
    if doc.ext.get("occupation") != "源师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    factor = 0.5 + int(deity["tier"]) * 0.05
    items = _source_items(doc, minutes, factor, rng, exp_table) if minutes else {}
    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor,
                                 progress_track="deity")
    result.update({"planned_minutes": planned, "kind": "source"})
    return True, result, d


def _deity_vein_items(doc: PlayerDoc, minutes: int, factor: float,
                      rng: Any, exp_table: Sequence[Mapping]) -> dict[str, int]:
    base = math.floor((2.0 + rng.random() * 0.5) * minutes)
    level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
    rate = occupation.rate_of(level, exp_table) * 10 or 1
    high = math.floor(math.floor(0.5 * (rate + 1) * base) * factor)
    middle = math.floor(math.floor(0.3 * (rate + 0.8) * base) * factor)
    low = math.floor(math.floor(0.1 * (rate + 0.6) * base) * factor)
    items = {name: count for name, count in (
        ("超品源石", high), ("上品神源石", middle), ("神源液", middle),
        ("超品神源石", low), ("神源药", low),
    ) if count > 0}
    if rng.random() < 0.15:
        items["龙脉精华"] = 1
    return items


def finish_deity_vein_proxy(doc: PlayerDoc, now: float, rng: Any,
                            exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    deity = state["deity"]
    task = deity["task"]
    if deity["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "vein":
        return False, {}, doc
    if doc.ext.get("occupation") != "源天师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    factor = 0.5 + int(deity["tier"]) * 0.05
    items = _deity_vein_items(doc, minutes, factor, rng, exp_table) if minutes else {}
    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor, 20,
                                 progress_track="deity")
    result.update({"planned_minutes": planned, "kind": "vein"})
    return True, result, d


def _earth_qi_items(doc: PlayerDoc, minutes: int, factor: float,
                    exp_table: Sequence[Mapping]) -> dict[str, int]:
    level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
    rate = occupation.rate_of(level, exp_table) * 10 or 1
    rare_count = minutes // 30
    realm_id = max(1, int(doc.realm_index) + 1)
    realm_factor = realm_id / (80 if realm_id <= 21 else 40)
    upper_base = math.floor(4 * (rate + 0.7) * rare_count)
    medicine_base = math.floor((rate + 0.5) * rare_count)
    upper = math.floor(math.floor(upper_base * realm_factor) * factor)
    medicine = math.floor(math.floor(medicine_base * realm_factor) * factor)
    items = {name: upper for name in ("上品源石", "超品源石", "神源石") if upper > 0}
    if medicine > 0:
        items["地源药"] = medicine
    return items


def finish_deity_earth_qi_proxy(doc: PlayerDoc, now: float,
                                exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    deity = state["deity"]
    task = deity["task"]
    if deity["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "earth_qi":
        return False, {}, doc
    if doc.ext.get("occupation") != "源地师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    factor = 0.5 + int(deity["tier"]) * 0.05
    items = _earth_qi_items(doc, minutes, factor, exp_table) if minutes else {}
    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor,
                                 progress_track="deity")
    result.update({"planned_minutes": planned, "kind": "earth_qi"})
    return True, result, d


def finish_deity_proxy(doc: PlayerDoc, now: float, rng: Any,
                       exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    task = state["deity"].get("task") or {}
    if task.get("kind") == "herb":
        return finish_deity_herb_proxy(doc, now, rng, exp_table)
    if task.get("kind") == "mine":
        return finish_deity_mine_proxy(doc, now, rng, exp_table)
    if task.get("kind") == "hunt":
        return finish_deity_hunt_proxy(doc, now, exp_table)
    if task.get("kind") == "source":
        return finish_deity_source_proxy(doc, now, rng, exp_table)
    if task.get("kind") == "earth_qi":
        return finish_deity_earth_qi_proxy(doc, now, exp_table)
    if task.get("kind") == "vein":
        return finish_deity_vein_proxy(doc, now, rng, exp_table)
    return False, {}, doc


def finish_herb_proxy(doc: PlayerDoc, now: float, rng: Any,
                      exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    spirit = state["spirit"]
    task = spirit["task"]
    if spirit["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "herb":
        return False, {}, doc
    if doc.ext.get("occupation") != "采药师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(spirit["tier"])
    factor = 0.5 + tier * 0.05
    items: dict[str, int] = {}
    if minutes:
        realm_id = max(1, int(doc.realm_index) + 1)
        level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
        total = (minutes / 480) * (level * 2 + 12)
        total *= 0.5 if realm_id < 22 else 1.5 if realm_id >= 36 else 1.0
        total = math.floor(total * factor)
        weights = COMMON_WEIGHTS if realm_id < 36 else RARE_WEIGHTS
        bonus = mingge.bonus(doc, "采药加成")
        items = {name: count for name, weight in zip(HERB_NAMES, weights)
                 if (count := _roll_yield(weight * total, bonus, rng)) > 0}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor)
    result.update({"planned_minutes": planned, "kind": "herb"})
    return True, result, d


def _mine_items(doc: PlayerDoc, minutes: int, factor: float, rng: Any,
                exp_table: Sequence[Mapping]) -> dict[str, int]:
    level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
    rate = occupation.rate_of(level, exp_table) * 10 or 1
    mined = math.floor((1.8 + rng.random() * 0.4) * minutes)
    amount = math.floor(4 * (rate + 1) * mined)
    amount = math.floor(amount * (max(1, int(doc.realm_index) + 1) / 40))
    amount = math.floor(amount * factor)
    count = math.floor(math.floor(((rate / 12) * minutes) / 30) * factor)
    colors = int(rng.random() * len(occupation.MINE_POOL_A))
    bonus = mingge.bonus(doc, "采矿加成")
    values = (
        ("庚金", _roll_yield(amount, bonus, rng)),
        ("玄土", _roll_yield(amount, bonus, rng)),
        (occupation.MINE_POOL_A[colors], _roll_yield(count, bonus, rng)),
        (occupation.MINE_POOL_B[colors], _roll_yield(math.trunc(count / 48), bonus, rng)),
    )
    return {name: qty for name, qty in values if qty > 0}


def finish_mine_proxy(doc: PlayerDoc, now: float, rng: Any,
                      exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    spirit = state["spirit"]
    task = spirit["task"]
    if spirit["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "mine":
        return False, {}, doc
    if doc.ext.get("occupation") != "采矿师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(spirit["tier"])
    factor = 0.5 + tier * 0.05
    items = _mine_items(doc, minutes, factor, rng, exp_table) if minutes else {}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor)
    result.update({"planned_minutes": planned, "kind": "mine"})
    return True, result, d


def finish_hunt_proxy(doc: PlayerDoc, now: float,
                      exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    spirit = state["spirit"]
    task = spirit["task"]
    if spirit["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "hunt":
        return False, {}, doc
    if doc.ext.get("occupation") != "猎户":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(spirit["tier"])
    factor = 0.5 + tier * 0.05
    items = _hunt_items(doc, minutes, factor, exp_table) if minutes else {}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor)
    result.update({"planned_minutes": planned, "kind": "hunt"})
    return True, result, d


def finish_source_proxy(doc: PlayerDoc, now: float, rng: Any,
                        exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    spirit = state["spirit"]
    task = spirit["task"]
    if spirit["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "source":
        return False, {}, doc
    if doc.ext.get("occupation") != "源师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(spirit["tier"])
    factor = 0.5 + tier * 0.05
    items = _source_items(doc, minutes, factor, rng, exp_table) if minutes else {}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor)
    result.update({"planned_minutes": planned, "kind": "source"})
    return True, result, d


def finish_earth_qi_proxy(doc: PlayerDoc, now: float,
                          exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    spirit = state["spirit"]
    task = spirit["task"]
    if spirit["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "earth_qi":
        return False, {}, doc
    if doc.ext.get("occupation") != "源地师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(spirit["tier"])
    factor = 0.5 + tier * 0.05
    items = _earth_qi_items(doc, minutes, factor, exp_table) if minutes else {}

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor)
    result.update({"planned_minutes": planned, "kind": "earth_qi"})
    return True, result, d


def finish_vein_proxy(doc: PlayerDoc, now: float, rng: Any,
                      exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    spirit = state["spirit"]
    task = spirit["task"]
    if spirit["tier"] < 1 or not isinstance(task, dict) or task.get("kind") != "vein":
        return False, {}, doc
    if doc.ext.get("occupation") != "源天师":
        return False, {}, doc

    planned = max(1, min(MINUTES_MAX, int(task.get("minutes", 0) or 0)))
    minutes = min(planned, max(0, int((float(now) - float(task.get("started_at", now))) // 60)))
    tier = int(spirit["tier"])
    factor = 0.5 + tier * 0.05
    items: dict[str, int] = {}
    if minutes:
        level = max(0, int(doc.ext.get("occupation_level", 1) or 1))
        level_row = next((row for row in exp_table if int(row.get("id", -1)) == level), None)
        rate = float(level_row.get("rate", 0) or 0) * 20 if level_row else 20
        base = math.floor((2.0 + rng.random() * 0.5) * minutes)
        high = math.floor(math.floor(0.5 * (rate + 1) * base) * factor)
        middle = math.floor(math.floor(0.3 * (rate + 0.8) * base) * factor)
        low = math.floor(math.floor(0.1 * (rate + 0.6) * base) * factor)
        items = {name: count for name, count in (
            ("超品源石", high), ("上品神源石", middle), ("神源液", middle),
            ("超品神源石", low), ("神源药", low),
        ) if count > 0}
        if rng.random() < 0.15:
            items["龙脉精华"] = 1

    result, d = _finish_progress(doc, state, minutes, items, exp_table, factor, 20)
    result.update({"planned_minutes": planned, "kind": "vein"})
    return True, result, d


def finish_proxy(doc: PlayerDoc, now: float, rng: Any,
                 exp_table: Sequence[Mapping]) -> tuple[bool, dict, PlayerDoc]:
    state = state_of(doc)
    task = state["spirit"].get("task") or {}
    if task.get("kind") == "herb":
        return finish_herb_proxy(doc, now, rng, exp_table)
    if task.get("kind") == "mine":
        return finish_mine_proxy(doc, now, rng, exp_table)
    if task.get("kind") == "hunt":
        return finish_hunt_proxy(doc, now, exp_table)
    if task.get("kind") == "source":
        return finish_source_proxy(doc, now, rng, exp_table)
    if task.get("kind") == "earth_qi":
        return finish_earth_qi_proxy(doc, now, exp_table)
    if task.get("kind") == "vein":
        return finish_vein_proxy(doc, now, rng, exp_table)
    return False, {}, doc
