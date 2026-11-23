"""Weekly per-group source-stone king event."""

from __future__ import annotations

import random
from datetime import date
from typing import Any

from .clock import day_key

CONTRIBUTION = 300_000
TARGET = 3

KINGS = (
    {"id": "nine_orifices", "name": "九窍石人", "omen": "九窍天成，疑有圣灵孕生",
     "item": {"name": "神痕紫金残块", "class": "材料", "amount": 1}},
    {"id": "immortal_tomb", "name": "仙坟", "omen": "药香与阴气并存，生死难料",
     "item": {"name": "八万年药王", "class": "丹药", "amount": 1}},
    {"id": "demon_fetus", "name": "魔胎", "omen": "石胎搏动，似有古老生命沉眠",
     "item": {"name": "上古神源液", "class": "丹药", "amount": 1}},
    {"id": "blood_altar", "name": "血祭台", "omen": "血纹如火，封印下杀机不散",
     "item": {"name": "不死神凰血", "class": "材料", "amount": 1}},
)

OUTCOMES = (
    {"id": "source", "name": "源海", "weight": 5_500, "source": 200_000},
    {"id": "treasure", "name": "神华冲霄", "weight": 2_500, "source": 400_000},
    {"id": "jackpot", "name": "无价仙珍", "weight": 800, "source": 900_000,
     "grants_item": True},
    {"id": "danger", "name": "绝世凶变", "weight": 1_200, "source": 0, "damage": 0.2},
)


def week_key(now: float) -> str:
    shanghai_day = date.fromisoformat(day_key(float(now)))
    epoch_day = (shanghai_day - date(1970, 1, 1)).days
    return str((epoch_day + 3) // 7)


def _draw_weighted(rows: tuple[dict, ...], rng: Any) -> dict:
    roll = rng.random() * sum(int(row["weight"]) for row in rows)
    for row in rows:
        roll -= int(row["weight"])
        if roll < 0:
            return dict(row)
    return dict(rows[-1])


def create_state(group_id: str, now: float, rng: Any | None = None) -> dict:
    rng = rng or random.Random()
    key = week_key(now)
    king = KINGS[int(key) % len(KINGS)]
    return {
        "week_key": key,
        "king_id": king["id"],
        "participants": [],
        "opened": False,
        "outcome": _draw_weighted(OUTCOMES, rng),
    }


def state_for(cal: dict, group_id: str, now: float,
              rng: Any | None = None) -> tuple[dict, bool]:
    groups = cal.setdefault("stone_king_groups", {})
    if not isinstance(groups, dict):
        groups = cal["stone_king_groups"] = {}
    key = str(group_id)
    current_week = week_key(now)
    changed = False
    if cal.get("stone_king_cleanup_week") != current_week:
        for group_key, group_state in list(groups.items()):
            if not isinstance(group_state, dict) or group_state.get("week_key") != current_week:
                del groups[group_key]
        cal["stone_king_cleanup_week"] = current_week
        changed = True
    state = groups.get(key)
    if not isinstance(state, dict) or state.get("week_key") != current_week:
        state = create_state(key, now, rng)
        groups[key] = state
        return state, True
    return state, changed


def king_of(state: dict) -> dict:
    return next((dict(row) for row in KINGS if row["id"] == state.get("king_id")),
                dict(KINGS[0]))


def join(state: dict, uid: str, name: str) -> tuple[bool, str]:
    if state.get("opened"):
        return False, "本群本周的镇园石王已经开切。"
    participants = state.setdefault("participants", [])
    if any(str(row.get("uid")) == str(uid) for row in participants):
        return False, "你已经参与本群本周助切。"
    participants.append({"uid": str(uid), "name": str(name or uid)})
    return True, ""


def resolve(state: dict, rng: Any) -> dict:
    participants = state.get("participants") or []
    if state.get("opened") or len(participants) < TARGET:
        raise ValueError("镇园石王尚未达到开切条件。")
    outcome = dict(state.get("outcome") or {})
    king = king_of(state)
    winner = None
    if outcome.get("grants_item"):
        winner = dict(participants[min(len(participants) - 1,
                                       int(rng.random() * len(participants)))])
    state["opened"] = True
    return {"king": king, "outcome": outcome, "item_winner": winner,
            "item": dict(king["item"]) if winner else None}


def view_text(state: dict, group_id: str) -> str:
    king = king_of(state)
    participants = state.get("participants") or []
    names = "、".join(str(row.get("name") or row.get("uid")) for row in participants) or "暂无"
    status = (f"本群本周已经开切：{(state.get('outcome') or {}).get('name', '未知结果')}"
              if state.get("opened") else "发送 #石王助切 参与本群本周群事件")
    return "\n".join([
        f"【本周镇园石王·{king['name']}】", king["omen"],
        f"群号：{group_id}", f"助切代价：每人 {CONTRIBUTION:,} 源石",
        f"开切人数：{len(participants)}/{TARGET}", f"参与者：{names}", status,
    ])
