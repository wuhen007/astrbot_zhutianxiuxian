"""Pure rules for the five-stone source appraisal duel against NPCs."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Mapping
from typing import Any

SOURCE_DUEL_STATE_TTL_SECONDS = 5 * 60
SOURCE_DUEL_COOLDOWN_SECONDS = 6 * 60 * 60

NPCS = (
    {"id": 1, "name": "吴子明", "title": "神城赌徒", "wager": 200_000,
     "stone_fee": 200_000, "skill": 0.12, "opening": "我在石坊混迹多年，还怕你一个生面孔？"},
    {"id": 2, "name": "拓跋昌", "title": "源术世家奇才", "wager": 1_000_000,
     "stone_fee": 1_000_000, "skill": 0.58, "opening": "源术并非儿戏，今日便以三石定高下。"},
    {"id": 3, "name": "南宫奇", "title": "源术宗师", "wager": 5_000_000,
     "stone_fee": 5_000_000, "skill": 0.92, "opening": "天字号石园内，一步看错，便是千万斤源。"},
)

STONE_FORMS = (
    {"name": "青皮石", "appearance": "青褐石皮粗粝，纹路平缓", "bias": -0.04, "weight": 12},
    {"name": "鬼裂石", "appearance": "裂痕宛如鬼口，似曾被人重新封合", "bias": -0.08, "weight": 10},
    {"name": "蜂巢石", "appearance": "细孔密布，偶有微光在孔隙间游走", "bias": 0.01, "weight": 11},
    {"name": "黑玉石", "appearance": "石皮乌黑温润，敲击声沉闷", "bias": 0, "weight": 11},
    {"name": "赤砂石", "appearance": "表面赤砂簌簌脱落，内里坚如精铁", "bias": -0.01, "weight": 11},
    {"name": "龙纹石", "appearance": "天然纹路盘旋如龙，却有数处断裂", "bias": 0.02, "weight": 10},
    {"name": "龙首石", "appearance": "形似昂首古龙，眉心有一点白痕", "bias": 0.03, "weight": 5},
    {"name": "仙音石", "appearance": "风过石窍，隐约传出清越道音", "bias": 0.04, "weight": 5},
    {"name": "烈阳石", "appearance": "日光照射后温度渐升，赤霞一闪即逝", "bias": 0.05, "weight": 4},
    {"name": "月亮石", "appearance": "石皮莹白，背光处浮现淡淡月华", "bias": 0.04, "weight": 4},
    {"name": "白玉龟", "appearance": "形似伏卧白龟，背甲纹路浑然天成", "bias": 0.02, "weight": 6},
    {"name": "紫霞石", "appearance": "紫色石皮间霞丝隐现，触之微有暖意", "bias": 0.02, "weight": 7},
    {"name": "星辰石", "appearance": "深青石皮缀着银白斑点，宛若微缩星空", "bias": 0.04, "weight": 4},
    {"name": "寒髓石", "appearance": "石皮凝霜不化，裂隙间寒气丝丝外溢", "bias": 0, "weight": 8},
    {"name": "火云石", "appearance": "赤纹层叠如云，靠近时可闻细微爆鸣", "bias": 0.01, "weight": 8},
    {"name": "古井石", "appearance": "中央天然凹陷如井，源气入内便杳无回声", "bias": -0.03, "weight": 9},
    {"name": "铜锈石", "appearance": "青绿石衣斑驳，敲击时隐有金铁颤音", "bias": -0.02, "weight": 8},
    {"name": "雷击石", "appearance": "焦黑石皮遍布银色支纹，偶有电芒跳动", "bias": 0.015, "weight": 6},
    {"name": "麒麟石", "appearance": "石身伏卧如麒麟，鳞纹间似有瑞光流转", "bias": 0.045, "weight": 3},
)

OUTCOMES = (
    {"name": "空石", "multiplier": 0, "max_roll": 0.30,
     "clues": ("敲击声发散，石心似有空腔", "源气贴近石皮便悄然消散")},
    {"name": "杂源", "multiplier": 0.5, "max_roll": 0.60,
     "clues": ("裂隙中凝有零星白霜", "石皮下有微弱源气，驳杂不纯")},
    {"name": "纯净源", "multiplier": 1, "max_roll": 0.82,
     "clues": ("纹理向石心收束，隐成聚源之势", "触手温润，源气绵长而平稳")},
    {"name": "异种源", "multiplier": 2, "max_roll": 0.94,
     "clues": ("石皮深处闪过异色霞光", "源气中夹杂陌生而强盛的道韵")},
    {"name": "神源", "multiplier": 4, "max_roll": 0.99,
     "clues": ("石心似有神曦沉浮，靠近时气血共鸣", "细小纹路自行明灭，隐约交织天地道则")},
    {"name": "绝世奇源", "multiplier": 10, "max_roll": 1,
     "clues": ("天机被石皮遮蔽，观之竟令神识刺痛", "石中传来若有若无的生命律动")},
)

STAKE_MODES = {"平注": 1, "加注": 2, "豪赌": 3}
RESONANCES = (
    {"name": "日月同辉", "stones": ("烈阳石", "月亮石"), "multiplier": 1.25},
    {"name": "龙脉共振", "stones": ("龙纹石", "龙首石"), "multiplier": 1.2},
    {"name": "水火同炉", "stones": ("寒髓石", "火云石"), "multiplier": 1.18},
    {"name": "玄白抱一", "stones": ("黑玉石", "白玉龟"), "multiplier": 1.15},
    {"name": "紫气星河", "stones": ("紫霞石", "星辰石"), "multiplier": 1.2},
)

INSIGHT_TEXT = (
    "源纹枯寂，十有八九为空", "仅有驳杂源气，不似重宝", "源气内敛，应有纯净源凝结",
    "异色道韵流转，可能蕴有异种源", "神性精气不散，石心很不寻常",
    "天机混沌难明，此石可能藏有绝世奇源",
)


def get_npc(npc_id: int) -> dict | None:
    try:
        wanted = int(npc_id)
    except (TypeError, ValueError):
        return None
    return next((dict(npc) for npc in NPCS if npc["id"] == wanted), None)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, float(value)))


def _random_index(length: int, rng: Any) -> int:
    return min(length - 1, int(rng.random() * length))


def _draw_forms(count: int, rng: Any) -> list[dict]:
    pool = [dict(form) for form in STONE_FORMS]
    selected = []
    while len(selected) < count and pool:
        roll = rng.random() * sum(int(form["weight"]) for form in pool)
        for index, form in enumerate(pool):
            roll -= int(form["weight"])
            if roll < 0:
                selected.append(pool.pop(index))
                break
    return selected


def _insight_accuracy(player: Mapping | None) -> float:
    player = player if isinstance(player, Mapping) else {}
    base = {"源师": 0.72, "源地师": 0.84, "源天师": 0.94}.get(player.get("occupation"), 0)
    if not base:
        return 0.0
    try:
        level = float(player.get("occupation_level", 1) or 1)
    except (TypeError, ValueError):
        level = 1.0
    return min(0.95, base + min(0.05, max(0.0, level - 1) * 0.001))


def _insight(tier: int, player: Mapping | None, rng: Any) -> str:
    accuracy = _insight_accuracy(player)
    if not accuracy:
        return ""
    estimated = tier
    if rng.random() >= accuracy:
        distance = 1 if rng.random() < 0.8 else 2
        estimated = max(0, min(len(OUTCOMES) - 1,
                               tier + (-distance if rng.random() < 0.5 else distance)))
    return f"源术判断：{INSIGHT_TEXT[estimated]}"


def _draw_outcome(form: Mapping, base_value: int, player: Mapping | None, rng: Any) -> dict:
    roll = _clamp(rng.random() + float(form["bias"]), 0, 0.999999)
    tier = next(index for index, outcome in enumerate(OUTCOMES) if roll < outcome["max_roll"])
    signal_tier = tier
    if rng.random() >= 0.55:
        signal_tier = max(0, min(len(OUTCOMES) - 1,
                                 tier + (1 if rng.random() >= 0.5 else -1)))
    clue_pool = OUTCOMES[signal_tier]["clues"]
    return {
        "outcome_name": OUTCOMES[tier]["name"],
        "outcome_tier": tier,
        "signal_tier": signal_tier,
        "clue": clue_pool[_random_index(len(clue_pool), rng)],
        "insight": _insight(tier, player, rng),
        "source_value": math.floor(base_value * OUTCOMES[tier]["multiplier"]),
    }


def get_resonance(stones: list[Mapping]) -> dict | None:
    names = {stone.get("name") for stone in stones}
    for resonance in RESONANCES:
        if all(name in names for name in resonance["stones"]):
            return dict(resonance)
    return None


def evaluate_cut(stones: list[Mapping]) -> dict:
    base = sum(int(stone["source_value"]) for stone in stones)
    resonance = get_resonance(stones)
    return {"stones": list(stones), "base_source": base,
            "source": math.floor(base * (resonance["multiplier"] if resonance else 1)),
            "resonance": resonance}


def _three_stone_choices(stones: list[dict]) -> list[list[dict]]:
    return [[stones[a], stones[b], stones[c]]
            for a in range(len(stones) - 2)
            for b in range(a + 1, len(stones) - 1)
            for c in range(b + 1, len(stones))]


def _select_npc_stones(npc: Mapping, stones: list[dict], rng: Any) -> list[dict]:
    scores = {}
    for stone in stones:
        if rng.random() < float(npc["skill"]):
            scores[stone["id"]] = int(stone["outcome_tier"]) + rng.random() * 0.49
        else:
            scores[stone["id"]] = rng.random() * len(OUTCOMES)
    ranked = []
    for choice in _three_stone_choices(stones):
        resonance = get_resonance(choice)
        score = sum(scores[stone["id"]] for stone in choice)
        score *= resonance["multiplier"] if resonance else 1
        ranked.append((score, rng.random(), choice))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return ranked[0][2] if ranked else []


def create_session(npc_id: int, player: Mapping, now: float, seed: str) -> dict:
    npc = get_npc(npc_id)
    if not npc:
        raise ValueError("未知的源术对决 NPC。")
    rng = random.Random(str(seed))
    base_value = int(npc["stone_fee"]) // 5

    def batch(insight_player: Mapping | None) -> list[dict]:
        result = []
        for index, form in enumerate(_draw_forms(5, rng), 1):
            result.append({"id": index, **form,
                           **_draw_outcome(form, base_value, insight_player, rng)})
        return result

    return {
        "version": 1, "npc_id": npc["id"], "created_at": float(now),
        "expires_at": float(now) + SOURCE_DUEL_STATE_TTL_SECONDS,
        "stone_fee_paid": True, "seed": str(seed),
        "player_stones": batch(player), "npc_stones": batch(None),
    }


def calculate_settlement(npc: Mapping, result: str, player_source: int,
                         npc_source: int, stake_mode: str = "平注") -> dict:
    if stake_mode not in STAKE_MODES:
        raise ValueError("押注方式只能选择平注、加注或豪赌。")
    fee = int(npc["stone_fee"])
    wager = int(npc["wager"]) * STAKE_MODES[stake_mode]
    credit = 0
    if result == "win":
        credit = wager * 2 + int(player_source) + int(npc_source)
    elif result == "draw":
        credit = wager + int(player_source)
    elif result != "lose":
        raise ValueError("对决结果无效。")
    return {"fee": fee, "wager": wager, "credit": credit,
            "net": credit - fee - wager}


def resolve_session(session: Mapping, choices: list[int], stake_mode: str,
                    now: float | None = None) -> dict:
    if not isinstance(session, Mapping) or session.get("stone_fee_paid") is not True:
        raise ValueError("源术对决状态已经损坏。")
    if now is not None and float(session.get("expires_at", 0) or 0) <= float(now):
        raise ValueError("选石时间已过，石料费不退。")
    npc = get_npc(int(session.get("npc_id", 0) or 0))
    player_stones = session.get("player_stones")
    npc_stones = session.get("npc_stones")
    if not npc or not isinstance(player_stones, list) or not isinstance(npc_stones, list):
        raise ValueError("源术对决状态已经损坏。")
    try:
        selected = [int(value) for value in choices]
    except (TypeError, ValueError):
        selected = []
    if (len(selected) != 3 or len(set(selected)) != 3
            or any(value < 1 or value > 5 for value in selected)):
        raise ValueError("请选择三块不同的源石。")
    player_cut_stones = [next((stone for stone in player_stones
                               if int(stone.get("id", 0)) == value), None)
                         for value in selected]
    if any(stone is None or not isinstance(stone.get("source_value"), (int, float))
           for stone in player_cut_stones):
        raise ValueError("源术对决石池数据已经损坏。")
    seed = str(session.get("seed") or "")
    if not seed:
        raise ValueError("源术对决随机种子缺失。")
    rng = random.Random(seed + ":settlement")
    npc_cut_stones = _select_npc_stones(npc, npc_stones, rng)
    if len(npc_cut_stones) != 3 or any("source_value" not in stone for stone in npc_cut_stones):
        raise ValueError("源术对决 NPC 石池数据已经损坏。")
    player_cut = evaluate_cut(player_cut_stones)
    npc_cut = evaluate_cut(npc_cut_stones)
    result = ("win" if player_cut["source"] > npc_cut["source"] else
              "lose" if player_cut["source"] < npc_cut["source"] else "draw")
    stake_mode = stake_mode or "平注"
    settlement = calculate_settlement(npc, result, player_cut["source"],
                                      npc_cut["source"], stake_mode)
    return {"npc": npc, "result": result,
            "player_cuts": player_cut_stones, "npc_cuts": npc_cut_stones,
            "player_base_source": player_cut["base_source"],
            "npc_base_source": npc_cut["base_source"],
            "player_resonance": player_cut["resonance"],
            "npc_resonance": npc_cut["resonance"],
            "player_source": player_cut["source"], "npc_source": npc_cut["source"],
            "stake_mode": stake_mode, "settlement": settlement}


def duel_state(yuanshi_state: dict, legacy_source: Mapping | None = None) -> dict:
    duel = yuanshi_state.get("duel")
    if not isinstance(duel, dict):
        legacy_source = legacy_source if isinstance(legacy_source, Mapping) else {}
        duel = {
            "wins": max(0, int(legacy_source.get("源石坊对决胜场", 0) or 0)),
            "losses": max(0, int(legacy_source.get("源石坊对决负场", 0) or 0)),
            "draws": max(0, int(legacy_source.get("源石坊对决平局", 0) or 0)),
            "net": int(legacy_source.get("源石坊对决净收益", 0) or 0),
            "total_cut_source": max(0, int(legacy_source.get("源石坊对决累计切源", 0) or 0)),
            "peak_cut_source": max(0, int(legacy_source.get("源石坊对决最高切源", 0) or 0)),
        }
        yuanshi_state["duel"] = duel
    duel.setdefault("session", None)
    duel.setdefault("cooldown_until", 0.0)
    duel.setdefault("wins", 0)
    duel.setdefault("losses", 0)
    duel.setdefault("draws", 0)
    duel.setdefault("net", 0)
    duel.setdefault("total_cut_source", 0)
    duel.setdefault("peak_cut_source", 0)
    return duel


def cooldown_left(yuanshi_state: dict, now: float) -> int:
    duel = duel_state(yuanshi_state)
    try:
        until = float(duel.get("cooldown_until", 0) or 0)
    except (TypeError, ValueError):
        until = 0.0
    return max(0, math.ceil(until - float(now)))


def format_remaining(seconds: int) -> str:
    value = max(0, int(seconds))
    if value >= 3600:
        return f"{value // 3600}小时{(value % 3600) // 60}分"
    return f"{(value + 59) // 60}分"


def format_cut(stones: list[Mapping], base_source: int, source: int,
               resonance: Mapping | None) -> list[str]:
    lines = []
    for stone in stones:
        lines.append(
            f"· [{stone['id']}] {stone['name']}：{stone['outcome_name']}，"
            f"{int(stone['source_value']):,} 源石｜{stone['clue']}")
    if resonance:
        lines.append(
            f"石相【{resonance['name']}】×{float(resonance['multiplier']):g}"
            f"（基础 {int(base_source):,} → {int(source):,} 源石）")
    else:
        lines.append(f"切源合计：{int(source):,} 源石")
    return lines


def active_session(yuanshi_state: dict, now: float) -> tuple[dict | None, bool]:
    """Return a live session and lazily clear expired sessions without a fee refund."""
    duel = duel_state(yuanshi_state)
    session = duel.get("session")
    if not isinstance(session, dict):
        duel["session"] = None
        return None, False
    try:
        expires_at = float(session.get("expires_at", 0) or 0)
    except (TypeError, ValueError):
        expires_at = 0.0
    if expires_at <= float(now):
        duel["session"] = None
        return None, True
    return session, False
