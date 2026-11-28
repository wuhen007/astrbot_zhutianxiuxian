"""Portable equivalents for the legacy all-player ranking commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from . import xiangu
from .equipment import Stats
from .motou import state_of as motou_state
from .player import PlayerDoc

BOARDS = {
    "天榜": "total_exp", "灵榜": "stones", "封神榜": "immortal_power",
    "完美世界榜": "xiangu_power", "至尊榜": "mortal_power",
    "遮天榜": "immortal_power", "神魄榜": "shenpo", "魔道榜": "modao",
    "强化榜": "legacy_attribute_bonus", "洗根榜": "legacy_wash_count",
}


def _level_id(doc: PlayerDoc) -> int:
    return max(1, int(doc.realm_index) + 1)


def _score(board: str, doc: PlayerDoc, level_table: list[dict],
           player_stats: Stats | None) -> tuple[int, str] | None:
    ext = doc.ext if isinstance(doc.ext, Mapping) else {}
    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), Mapping) else {}
    from . import extra_cultivation
    tracks = extra_cultivation.levels_of(doc)
    if board == "强化榜":
        fields = ("攻击加成", "防御加成", "生命加成")
        if not any(key in legacy for key in fields):
            return None
        try:
            score = int(sum(float(legacy.get(key, 0) or 0) for key in fields))
        except (TypeError, ValueError):
            return None
        return score, f"强化值 {score:,}"
    if board == "洗根榜":
        if "洗根次数" not in legacy:
            return None
        try:
            score = max(0, int(float(legacy.get("洗根次数") or 0)))
        except (TypeError, ValueError):
            return None
        if score <= 0:
            return None
        root = legacy.get("灵根")
        if isinstance(root, Mapping):
            root_name = str(root.get("name") or root.get("type") or "未记录")
        else:
            root_name = str(root or "未记录")
        return score, f"洗根次数 {score}｜灵根 {root_name}"
    if board == "天榜":
        level_id = _level_id(doc)
        if level_id >= 65:
            return None
        prior = sum(int(row.get("exp", 0) or 0) for row in level_table
                    if int(row.get("level_id", 0) or 0) < level_id)
        score = prior + max(0, int(doc.exp))
        return score, f"总修为 {score:,}"
    if board == "灵榜":
        return int(doc.stones), f"灵石 {int(doc.stones):,}"
    if board == "魔道榜":
        score = int(float(motou_state(doc).get("modao", 0) or 0))
        return score, f"魔道值 {score:,}"
    if board == "神魄榜":
        score = int(float(ext.get("shenpo", legacy.get("神魄段数", 0)) or 0))
        return score, f"神魄段数 {score:,}"
    if board == "完美世界榜":
        level = xiangu.xg_level_of(doc)
        if level < 2:
            return None
        if player_stats is None:
            return None
        score = int((player_stats.atk + player_stats.defense + player_stats.hp)
                    * (player_stats.bao + 1))
        return score, f"战力 {score:,}"

    level_id = _level_id(doc)
    if board == "至尊榜" and level_id >= 42:
        return None
    if board == "封神榜" and level_id < 42:
        return None
    if board == "遮天榜":
        secret_level = tracks["mijing"]
        if secret_level < 2:
            return None
        if player_stats is None:
            return None
        score = int((player_stats.atk + player_stats.defense + player_stats.hp)
                    * (player_stats.bao + 1))
        return score, f"战力 {score:,}"
    if player_stats is None:
        return None
    power = ((player_stats.atk + player_stats.defense * 0.8 + player_stats.hp * 0.6)
             if board == "至尊榜" else
             (player_stats.atk + player_stats.defense + player_stats.hp))
    score = int(power * (player_stats.bao + 1))
    return score, f"战力 {score:,}"


def board_text(board: str, players: Sequence[PlayerDoc | Mapping], uid: str,
               level_table_for: Callable[[PlayerDoc], list[dict]],
               stats_for: Callable[[PlayerDoc], Stats] | None = None) -> str:
    if board not in BOARDS:
        raise ValueError("未知榜单。")
    rows = []
    needs_stats = board in {"封神榜", "完美世界榜", "至尊榜", "遮天榜"}
    for raw in players:
        doc = raw if isinstance(raw, PlayerDoc) else PlayerDoc.model_validate(raw)
        table = level_table_for(doc)
        player_stats = stats_for(doc) if needs_stats and stats_for else None
        score_row = _score(board, doc, table, player_stats)
        if score_row is not None:
            score, label = score_row
            rows.append((score, doc.name or "无名道友", doc.uid, label, table, doc))
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    own_rank = next((pos for pos, row in enumerate(rows, 1) if row[2] == str(uid)), None)
    lines = [f"--- {board}（前十）---"]
    for position, (_, name, _, label, table, doc) in enumerate(rows[:10], 1):
        if board == "完美世界榜":
            realm = xiangu.realm_name(xiangu.xg_level_of(doc))
        elif board == "遮天榜":
            from . import extra_cultivation
            realm = f"人体秘境 {extra_cultivation.level_of(doc, 'mijing')}"
        elif board in {"天榜", "封神榜", "至尊榜"}:
            level = min(_level_id(doc) - 1, len(table) - 1) if table else 0
            realm = str(table[level].get("level", "未知境")) if table else "未知境"
        else:
            realm = ""
        suffix = f"（{realm}）" if realm else ""
        lines.append(f"{position}. {name}{suffix}｜{label}")
    if own_rank is None:
        lines.append("你的名次：未上榜")
    else:
        lines.append(f"你的名次：第 {own_rank} 名｜{rows[own_rank - 1][3]}")
    return "\n".join(lines)
