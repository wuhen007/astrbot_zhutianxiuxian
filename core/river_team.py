"""时间长河多人同行状态机（纯函数，状态由调用方与现有数据库事务一并保存）。

原版参考：apps/SecretPlace/shijianchanghe.js、shijianchangheTask.js。
本模块将 Redis 队伍索引与异步 action 合并为一个 JSON 状态，供 AstrBot 层原子读改写。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import authority
from .combat import time_river as river_combat

TEAM_MIN = 2
TEAM_MAX = 4
AUTHORITY_GATE = 20
TEAM_TTL = 24 * 60 * 60
PHASE_SECONDS = river_combat.TIME_RIVER_PHASE_DURATION
RESCUE_SECONDS = river_combat.TIME_RIVER_RESCUE_WINDOW
DARK_TRIAD = river_combat.DARK_TRIAD_NAMES
FUTURE_QUASI = river_combat.TIME_RIVER_FUTURE_QUASI_NAMES


def _root(state: dict) -> dict:
    root = state.get("time_river")
    if not isinstance(root, dict):
        root = {"teams": {}, "player_team": {}}
        state["time_river"] = root
    root.setdefault("teams", {})
    root.setdefault("player_team", {})
    return root


def _uid(value: Any) -> str:
    return str(value or "").strip()


def _team(root: dict, uid: str) -> dict | None:
    team_id = root["player_team"].get(_uid(uid))
    team = root["teams"].get(str(team_id)) if team_id else None
    if not isinstance(team, dict) or _uid(uid) not in team.get("members", []):
        root["player_team"].pop(_uid(uid), None)
        return None
    return team


def _eligible(doc: Any) -> bool:
    return bool(doc and authority.meets(doc, AUTHORITY_GATE))


def _expire(root: dict, now: float) -> None:
    expired = [key for key, team in root["teams"].items()
               if float(team.get("expires_at", 0) or 0) <= now]
    for key in expired:
        team = root["teams"].pop(key, {})
        for uid in team.get("members", []):
            if root["player_team"].get(_uid(uid)) == key:
                root["player_team"].pop(_uid(uid), None)


def create_team(state: dict, uid: str, doc: Any, group_id: str, now: float | None = None,
                rng: random.Random | None = None) -> tuple[dict | None, str]:
    """创建招募队伍；只允许准仙帝权柄，最多四人。"""
    uid = _uid(uid)
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    if not uid or not _eligible(doc):
        return None, "组队踏入时间长河，仍须拥有准仙帝及以上权柄。"
    root = _root(state)
    _expire(root, now)
    existing = _team(root, uid)
    if existing:
        return None, f"你已在时间长河队伍【{existing['id']}】中。"
    for _ in range(100):
        team_id = f"{rng.randrange(100000, 1000000)}"
        if team_id not in root["teams"]:
            break
    else:
        return None, "暂时无法锚定新的古史坐标，请稍后再试。"
    team = {
        "id": team_id, "leader": uid, "members": [uid], "status": "recruiting",
        "group_id": str(group_id or ""), "created_at": now,
        "expires_at": now + TEAM_TTL,
    }
    root["teams"][team_id] = team
    root["player_team"][uid] = team_id
    return team, (f"【时间长河·帝者结盟】\n{getattr(doc, 'name', '') or uid}以准仙帝道果锚定一处古史坐标。\n"
                  f"队伍编号：{team_id}｜当前人数：1/4\n加入：#加入时间长河队伍 {team_id}\n"
                  "集齐至少两人后，由队长发送 #组队遨游时间长河。")


def join_team(state: dict, uid: str, doc: Any, team_id: str,
              now: float | None = None) -> tuple[dict | None, str]:
    uid, team_id = _uid(uid), str(team_id or "").strip()
    now = time.time() if now is None else float(now)
    if not uid or not _eligible(doc):
        return None, "组队踏入时间长河，仍须拥有准仙帝及以上权柄。"
    root = _root(state)
    _expire(root, now)
    if _team(root, uid):
        return None, "你已经加入了其他时间长河队伍。"
    team = root["teams"].get(team_id)
    if not team:
        return None, "这个时间长河队伍不存在或已经失效。"
    if team.get("status") != "recruiting":
        return None, "这支队伍已经踏入时间长河，古史坐标现已封闭。"
    if len(team.get("members", [])) >= TEAM_MAX:
        return None, "时间长河队伍最多容纳四位准仙帝。"
    team.setdefault("members", []).append(uid)
    team["expires_at"] = now + TEAM_TTL
    root["player_team"][uid] = team_id
    return team, f"【帝者入列】{getattr(doc, 'name', '') or uid}加入队伍【{team_id}】，当前{len(team['members'])}/4人。"


def view_team(state: dict, uid: str, names: Mapping[str, str] | None = None) -> str:
    root = _root(state)
    team = _team(root, _uid(uid))
    if not team:
        return "你当前没有时间长河队伍。"
    names = names or {}
    status = {"recruiting": "招募中", "exploring": "横渡古史中", "rescue": "战败待援"}.get(
        str(team.get("status")), "已结束")
    lines = [f"【时间长河队伍·{team['id']}】", f"状态：{status}｜人数：{len(team['members'])}/4"]
    for member in team["members"]:
        prefix = "【队长】" if _uid(member) == _uid(team.get("leader")) else "【成员】"
        lines.append(f"{prefix}{names.get(_uid(member), _uid(member))}")
    if team.get("status") == "exploring":
        remain = max(0, int(float(team.get("phase_end", 0) or 0) - time.time()))
        lines.append(f"阶段：{team.get('stage', 'initial')}｜距结算 {remain // 60} 分 {remain % 60} 秒")
    if team.get("status") == "rescue":
        remain = max(0, int(float(team.get("rescue_end", 0) or 0) - time.time()))
        lines.append(f"待援剩余：{remain // 60} 分 {remain % 60} 秒")
    if team.get("status") == "recruiting" and _uid(uid) == _uid(team.get("leader")):
        lines.append("发起：#组队遨游时间长河")
    return "\n".join(lines)


def leave_team(state: dict, uid: str) -> tuple[bool, str]:
    uid = _uid(uid)
    root = _root(state)
    team = _team(root, uid)
    if not team:
        return False, "你当前没有时间长河队伍。"
    if team.get("status") in {"exploring", "rescue"}:
        return False, "真身已被古史节点锁定，探索或待援结束前不可退出队伍。"
    team["members"] = [member for member in team["members"] if _uid(member) != uid]
    root["player_team"].pop(uid, None)
    if not team["members"]:
        root["teams"].pop(str(team["id"]), None)
        return True, "你已退出，时间长河队伍随之解散。"
    if _uid(team.get("leader")) == uid:
        team["leader"] = team["members"][0]
    return True, f"你已退出时间长河队伍【{team['id']}】。"


def disband_team(state: dict, uid: str) -> tuple[bool, str]:
    uid = _uid(uid)
    root = _root(state)
    team = _team(root, uid)
    if not team:
        return False, "你当前没有时间长河队伍。"
    if _uid(team.get("leader")) != uid:
        return False, "只有队长可以解散时间长河队伍。"
    if team.get("status") in {"exploring", "rescue"}:
        return False, "真身已踏入时间长河，探索或待援结束前不可解散。"
    for member in team.get("members", []):
        root["player_team"].pop(_uid(member), None)
    root["teams"].pop(str(team["id"]), None)
    return True, f"时间长河队伍【{team['id']}】已经解散。"


def start_team(state: dict, uid: str, players: Mapping[str, Any], now: float | None = None,
               *, in_river: Callable[[Any], bool] | None = None,
               is_busy: Callable[[str, Any], bool] | None = None) -> tuple[dict | None, str]:
    """验证并锁定2-4名成员进入首个15分钟异步阶段。"""
    uid = _uid(uid)
    now = time.time() if now is None else float(now)
    root = _root(state)
    team = _team(root, uid)
    if not team:
        return None, "请先使用 #组队时间长河 创建队伍。"
    if _uid(team.get("leader")) != uid:
        return None, "只有队长可以锚定古史并发起探索。"
    if team.get("status") != "recruiting":
        return None, "队伍已经在时间长河中。"
    members = list(map(_uid, team.get("members", [])))
    if not TEAM_MIN <= len(members) <= TEAM_MAX:
        return None, "组队探索需要2至4位准仙帝。"
    for member in members:
        doc = players.get(member)
        if not doc:
            return None, f"成员 {member} 的修仙存档不存在。"
        if not _eligible(doc):
            return None, f"成员【{getattr(doc, 'name', '') or member}】尚未达到准仙帝。"
        if in_river and not in_river(doc):
            return None, f"成员【{getattr(doc, 'name', '') or member}】当前不在时间长河，请先使用 #穿梭时间长河。"
        if is_busy and is_busy(member, doc):
            return None, f"成员【{getattr(doc, 'name', '') or member}】正在其他行动中。"
    team.update({
        "status": "exploring", "started_at": now, "stage": "initial",
        "stage_started": now, "phase_end": now + PHASE_SECONDS,
        "retry_stage": None, "enemy_state": None, "sacrifice_buff": 0.0,
        "member_hp": {}, "last_result": None, "stage_reports": [],
        "cumulative_reward": 0, "expires_at": now + TEAM_TTL,
    })
    return team, (f"【共赴古史】{ '、'.join(getattr(players[m], 'name', '') or m for m in members)}同时踏入时间长河！\n"
                  "队伍已被同一古史节点锁定，首段探索将在15分钟后统一结算。")


def start_solo(state: dict, uid: str, doc: Any, now: float | None = None,
               *, is_busy: Callable[[str, Any], bool] | None = None) -> tuple[dict | None, str]:
    """开始原版单人15分钟异步河程；与多人状态共用阶段和结算语义。"""
    uid = _uid(uid)
    now = time.time() if now is None else float(now)
    if not uid or not _eligible(doc):
        return None, "遨游时间长河需拥有准仙帝及以上权柄。"
    root = _root(state)
    _expire(root, now)
    if _team(root, uid):
        return None, "你已在时间长河队伍中，请使用队伍对应的同行指令。"
    if is_busy and is_busy(uid, doc):
        return None, "你正在其他行动中，暂时无法遨游时间长河。"
    team_id = f"solo-{uid}"
    if team_id in root["teams"]:
        return None, "你的上一段时间长河记录仍在结算，请稍后重试。"
    team = {
        "id": team_id, "leader": uid, "members": [uid], "status": "exploring",
        "group_id": "", "created_at": now, "started_at": now,
        "stage": "initial", "stage_started": now, "phase_end": now + PHASE_SECONDS,
        "retry_stage": None, "enemy_state": None, "sacrifice_buff": 0.0,
        "member_hp": {}, "last_result": None, "expires_at": now + TEAM_TTL,
        "solo": True,
    }
    root["teams"][team_id] = team
    root["player_team"][uid] = team_id
    return team, ("【独行时间长河】你已锚定古史节点，首段探索将在15分钟后统一结算。")


def phase_due(team: Mapping, now: float | None = None) -> bool:
    now = time.time() if now is None else float(now)
    return team.get("status") == "exploring" and float(team.get("phase_end", 0) or 0) <= now


def stage_roster(stage: str, rng: random.Random | None = None,
                 initial_names: Sequence[str] = (), primary_name: str = "",
                 enemy_names: Sequence[str] = (), imperial_pill: bool = False) -> list[str]:
    rng = rng or random.Random()
    if stage == "initial":
        return [str(rng.choice(initial_names))] if initial_names else []
    if stage == "solo":
        return [primary_name] if primary_name else []
    if stage == "triad":
        return list(DARK_TRIAD)
    if stage == "old_man":
        return ["灭世老人", *DARK_TRIAD] if imperial_pill else ["灭世老人"]
    if stage == "future_quasi":
        return ["灭世老人", *DARK_TRIAD, *FUTURE_QUASI]
    if enemy_names:
        return list(map(str, enemy_names))
    return []


def build_team_battle(team: dict, players: Mapping[str, Any],
                      build_player: Callable[[str, Any], Any],
                      build_enemy: Callable[[str, Mapping, Mapping[str, int], float], Any],
                      templates: Mapping[str, Mapping], rng: random.Random,
                      initial_names: Sequence[str] = ()) -> tuple[list, list, list[str]]:
    """构造原版多人共同战斗：队伍最高三维为基准，敌人乘1.5~3倍率。"""
    from .combat.engine import Fighter

    ids = list(map(_uid, team.get("members", [])))
    party = [build_player(uid, players[uid]) for uid in ids]
    if not party:
        return [], [], []
    benchmark = {
        "attack": max(f.atk for f in party),
        "defense": max(f.defense for f in party),
        "hp": max(f.hp_max for f in party),
        "speed": max(f.speed for f in party),
    }
    stage = str(team.get("stage") or "initial")
    names = stage_roster(stage, rng, initial_names,
                         primary_name=str(team.get("primary_name") or ""),
                         enemy_names=team.get("enemy_names") or (),
                         imperial_pill=bool(team.get("imperial_pill")))
    saved_by_name = {str(row.get("name")): row for row in team.get("enemy_state") or ()
                     if isinstance(row, Mapping)}
    enemies = []
    team["last_roster"] = list(names)
    team["enemy_multipliers"] = {}
    for name in names:
        template = templates.get(name)
        if template is None and name.startswith("未来准仙帝·"):
            template = templates.get("未来准仙帝")
        if template is None:
            raise KeyError(f"时间长河敌人配置缺失：{name}")
        mult = river_combat.roll_attribute_multiplier(rng)
        team["enemy_multipliers"][name] = mult
        enemy = build_enemy(name, template, benchmark, mult)
        enemy.atk = max(1, int(benchmark["attack"] * mult))
        enemy.defense = max(1, int(benchmark["defense"] * mult))
        enemy.hp_max = max(1, int(benchmark["hp"] * mult))
        enemy.hp = enemy.hp_max
        river_combat.apply_adversary_rules(enemy, name)
        if team.get("imperial_pill") and name in DARK_TRIAD:
            for attr in ("atk", "defense", "hp_max", "speed"):
                setattr(enemy, attr, max(1, int(getattr(enemy, attr) * 0.7)))
            enemy.hp = enemy.hp_max
            if enemy.effects.get("shield"):
                enemy.effects["shield"] = int(enemy.effects["shield"] * 0.7)
        saved = saved_by_name.get(name)
        if saved:
            for key, attr in (("atk", "atk"), ("defense", "defense"),
                              ("hp_max", "hp_max"), ("hp", "hp")):
                if key in saved:
                    setattr(enemy, attr, max(0 if key == "hp" else 1, int(saved[key])))
            enemy.effects["shield"] = max(0, int(saved.get("shield", enemy.effects.get("shield", 0))))
            enemy.effects["time_river_damage_reduction_turns"] = max(
                0, int(saved.get("reduction_turns", enemy.effects.get("time_river_damage_reduction_turns", 0))))
            if "revives_used" in saved:
                enemy.effects["triad_revived"] = int(saved["revives_used"]) >= 1
        enemies.append(enemy)
    river_combat.mark_party_countered(party, enemies)
    opening = []
    if any(enemy.name == "苍帝" for enemy in enemies):
        for uid, doc, fighter in zip(ids, (players[m] for m in ids), party):
            ext = getattr(doc, "ext", {}) or {}
            legacy = ext.get("legacy_source") or {}
            ownway = ext.get("ownway") or ext.get("己道推演") or legacy.get("己道推演") or {}
            immune = (authority.meets(doc, 21)
                      or (authority.meets(doc, 20) and ownway.get("divineEmbryo") == "已结出"))
            note = river_combat.apply_cang_emperor_opening_suppression(fighter, immune=immune)
            if note:
                opening.append(note)
    if team.get("sacrifice_buff"):
        for fighter in party:
            river_combat.apply_sacrifice_buff(fighter, float(team["sacrifice_buff"]))
    return party, enemies, opening


def capture_enemy_state(enemies: Sequence[Any]) -> list[dict]:
    """保留续战敌人剩余血量、护盾、减伤回合和帝血复生标记。"""
    rows = []
    for enemy in enemies:
        rows.append({
            "name": enemy.name, "atk": int(enemy.atk), "defense": int(enemy.defense),
            "hp_max": int(enemy.hp_max), "hp": max(0, int(enemy.hp)),
            "speed": int(enemy.speed), "shield": max(0, int(enemy.eff("shield", 0) or 0)),
            "reduction": float(enemy.eff("time_river_damage_reduction", 0) or 0),
            "reduction_turns": max(0, int(enemy.eff("time_river_damage_reduction_turns", 0) or 0)),
            "revives_used": int(bool(enemy.eff("triad_revived", False))),
        })
    return rows


def record_battle(team: dict, party: Sequence[Any], enemies: Sequence[Any], result: Any,
                  now: float | None = None) -> dict:
    """存放同一阶段内的结果快照；调用者应在玩家与 world JSON 同一事务内提交。"""
    now = time.time() if now is None else float(now)
    member_ids = list(map(_uid, team.get("members", [])))
    team["member_hp"] = {uid: max(0, int(fighter.hp)) for uid, fighter in zip(member_ids, party)}
    team["enemy_state"] = capture_enemy_state(enemies)
    result_doc = {
        "winner": result.winner,
        "rounds": sum(line.startswith("【第") for line in result.log),
        "party_survivors": list(result.a_survivors),
        "enemy_survivors": list(result.b_survivors),
        "enemy_state": team["enemy_state"], "member_hp": team["member_hp"], "at": now,
    }
    team["last_result"] = result_doc
    return result_doc


def _reward(stage: str, outcome: str, primary_name: str, team: Mapping,
            rng: random.Random) -> int:
    gain = rng.randint(3, 5) if outcome == "victory" else rng.randint(1, 2)
    if outcome == "victory" and stage == "triad":
        gain *= 3
    if outcome == "victory" and stage == "old_man":
        gain = int(team.get("old_man_reward") or (30 if team.get("imperial_pill") else 10))
    if outcome == "victory" and stage == "future_quasi":
        gain = river_combat.TIME_RIVER_FUTURE_REWARD
    if outcome == "victory" and primary_name in {"荒天帝", "尸骸仙帝"}:
        gain = (river_combat.TIME_RIVER_HUANG_REWARD if primary_name == "荒天帝"
                else river_combat.TIME_RIVER_CORPSE_REWARD)
    return gain


def complete_stage(team: dict, winner: int | None, primary_name: str,
                   enemy_names: Sequence[str], rng: random.Random,
                   now: float | None = None) -> dict:
    """15分钟到期后的阶段转移。reward_delta 是每名成员应结算的原版数值。"""
    now = time.time() if now is None else float(now)
    stage = str(team.get("stage") or "initial")
    outcome = "victory" if winner == 0 else "defeat" if winner == 1 else "draw"
    reward = _reward(stage, outcome, primary_name, team, rng)
    event: dict[str, Any] = {"outcome": outcome, "reward_delta": reward,
                             "stage": stage, "members": list(team.get("members", []))}
    team["last_outcome"] = outcome
    team["pending_reward"] = reward
    team["cumulative_reward"] = max(0, int(team.get("cumulative_reward", 0) or 0)) + reward
    is_chain = stage != "initial" or river_combat.is_dark_triad_emperor(primary_name)
    if outcome == "defeat" and is_chain:
        retry = "solo" if stage == "initial" else stage
        team.update({"status": "rescue", "retry_stage": retry,
                    "primary_name": primary_name, "enemy_names": list(enemy_names),
                    "rescue_end": now + RESCUE_SECONDS, "phase_end": 0,
                    "settlement": {"kind": "rescue_window", "reward_delta": reward}})
        event.update({"kind": "rescue_window", "deadline": team["rescue_end"],
                      "message": "全队进入十分钟待援窗口；同灵根且至少一条额外体系成仙的队外玩家可献祭魂血续战。"})
        return event
    if outcome == "victory" and stage == "initial" and river_combat.is_dark_triad_emperor(primary_name):
        next_stage = "triad"
        team.update({"stage": next_stage, "stage_started": now,
                    "phase_end": now + PHASE_SECONDS, "primary_name": primary_name,
                    "enemy_names": list(DARK_TRIAD), "enemy_state": None,
                    "pending_reward": reward,
                    "settlement": {"kind": "next_stage", "reward_delta": reward}})
        event.update({"kind": "next_stage", "next_stage": next_stage,
                      "deadline": team["phase_end"],
                      "message": "苍、鸿、羽三帝并立，十五分钟后结算三帝围杀。"})
        return event
    if outcome == "victory" and stage == "triad" and rng.random() < 0.30:
        imperial_pill = rng.random() < 0.50
        old_reward = 30 if imperial_pill else 10
        team.update({"stage": "old_man", "stage_started": now,
                    "phase_end": now + PHASE_SECONDS, "primary_name": "灭世老人",
                    "enemy_names": ["灭世老人", *DARK_TRIAD] if imperial_pill else ["灭世老人"],
                    "enemy_state": None, "imperial_pill": imperial_pill,
                    "old_man_reward": old_reward, "pending_reward": reward,
                    "settlement": {"kind": "next_stage", "reward_delta": reward}})
        event.update({"kind": "next_stage", "next_stage": "old_man",
                      "imperial_pill": imperial_pill, "deadline": team["phase_end"],
                      "message": "灭世老人已降临，十五分钟后进行下一阶段帝战。"})
        return event
    if outcome == "victory" and stage == "old_man" and team.get("imperial_pill") \
            and rng.random() < river_combat.TIME_RIVER_FUTURE_EVENT_RATE:
        team.update({"stage": "future_quasi", "stage_started": now,
                    "phase_end": now + PHASE_SECONDS, "primary_name": "灭世老人",
                    "enemy_names": ["灭世老人", *DARK_TRIAD, *FUTURE_QUASI],
                    "enemy_state": None, "pending_reward": reward,
                    "settlement": {"kind": "next_stage", "reward_delta": reward}})
        event.update({"kind": "next_stage", "next_stage": "future_quasi",
                      "deadline": team["phase_end"],
                      "message": "未来三位准仙帝逆流而来，十五分钟后进入七尊黑暗围杀。"})
        return event
    team.update({"status": "settled", "phase_end": 0, "settled_at": now,
                 "settlement": {"kind": "settled", "reward_delta": reward}})
    event.update({"kind": "settled", "message": "时间长河本段探索结束；请发放本阶段纪元积累并解除队员行动锁。"})
    return event


def expire_rescue(team: dict, now: float | None = None) -> dict | None:
    now = time.time() if now is None else float(now)
    if team.get("status") != "rescue" or float(team.get("rescue_end", 0) or 0) > now:
        return None
    team.update({"status": "refined", "phase_end": 0, "refined_at": now,
                 "settlement": {"kind": "refined", "reward_delta": 0}})
    return {"kind": "refined", "members": list(team.get("members", [])),
            "message": "待援时限已过，按原版进入黑暗古国炼化道果的失败结局。"}


def sacrifice_recovery(doc: Any) -> dict:
    """原版同灵根魂血献祭档位，读取独立持久化的额外体系等级。"""
    from . import extra_cultivation
    levels = extra_cultivation.levels_of(doc)
    candidates = []
    tiers = {
        "mijing": ((20, 0.75, "帝光仙王及以上"), (19, 0.50, "仙王巨头"),
                   (18, 0.35, "仙王"), (17, 0.15, "红尘仙")),
        "xiangu": ((20, 0.75, "帝光仙王及以上"), (19, 0.50, "仙王巨头"),
                   (17, 0.35, "仙王"), (16, 0.15, "真仙")),
        "huafen": ((21, 0.75, "帝光仙王及以上"), (20, 0.50, "仙王巨头"),
                   (19, 0.35, "仙王"), (17, 0.15, "大宇/究极")),
    }
    for path, level in levels.items():
        tier = next((row for row in tiers[path] if level >= row[0]), None)
        if tier:
            candidates.append({"eligible": True, "path": path, "field": path,
                               "ratio": tier[1], "tier": tier[2], "level": level})
    return max(candidates, key=lambda item: item["ratio"]) if candidates else {
        "eligible": False, "path": "", "field": "", "ratio": 0.0, "tier": "未成仙", "level": 0}

def accept_sacrifice(team: dict, donor: Any, target: Any,
                     now: float | None = None) -> tuple[dict | None, str]:
    """验收外援并原子记录跌境代价；队伍回血/计时由事务调用方一起落库。"""
    now = time.time() if now is None else float(now)
    if team.get("status") != "rescue" or float(team.get("rescue_end", 0) or 0) <= now:
        return None, "时间长河十分钟献祭窗口已经结束。"
    donor_uid = _uid(getattr(donor, "uid", ""))
    target_uid = _uid(getattr(target, "uid", ""))
    members = set(map(_uid, team.get("members", [])))
    if not target_uid or target_uid not in members:
        return None, "献祭目标必须是当前待援队伍中的成员。"
    if not donor_uid or donor_uid in members:
        return None, "战败队伍成员此刻同陷败亡节点，需由队伍外玩家献祭。"
    donor_ext = getattr(donor, "ext", {}) or {}
    target_ext = getattr(target, "ext", {}) or {}
    donor_root = donor_ext.get("linggen") if isinstance(donor_ext.get("linggen"), Mapping) else {}
    target_root = target_ext.get("linggen") if isinstance(target_ext.get("linggen"), Mapping) else {}
    if not donor_root.get("name") or donor_root.get("name") != target_root.get("name"):
        return None, (f"灵根不相同：献祭者为【{donor_root.get('name') or '未知'}】，"
                      f"战败者为【{target_root.get('name') or '未知'}】。")
    info = sacrifice_recovery(donor)
    if not info["eligible"]:
        return None, "三大额外体系至少有一条成仙，方能承受献祭魂与血的反噬。"
    info["donor_uid"] = donor_uid
    info["root_name"] = str(donor_root.get("name") or "")
    info["target_uid"] = target_uid
    info["member_ids"] = list(team.get("members", []))
    info["buff"] = float(info["ratio"])
    next_level = max(1, int(info["level"]) - 1)
    from . import extra_cultivation
    extra_cultivation.set_level(donor, info["path"], next_level)
    if info["path"] == "huafen":
        flower_state = donor_ext.get("flower")
        if isinstance(flower_state, dict):
            flower_state["level"] = next_level
            flower_state["extremes"] = []
    elif info["path"] == "xiangu":
        xiangu_state = donor_ext.get("xiangu")
        if isinstance(xiangu_state, dict):
            xiangu_state["extremes"] = []
            shenhuo = xiangu_state.get("shenhuo")
            if next_level < 8:
                xiangu_state.pop("shenhuo", None)
            elif isinstance(shenhuo, dict):
                shenhuo["极境达成"] = False
                shenhuo.pop("极境名称", None)
            xiangu_state["xianqi"] = 0
            xiangu_state["xianqi_detail"] = []
    donor.realm_index = 0
    donor.physique_index = 0
    team.update({"status": "exploring", "stage": str(team.get("retry_stage") or "initial"),
                 "primary_name": str(team.get("primary_name") or ""),
                 "phase_started": now, "phase_end": now + PHASE_SECONDS,
                 "enemy_state": team.get("enemy_state"), "sacrifice_buff": info["buff"],
                 "rescue_end": 0})
    return info, (f"【献祭魂与血·古史续接】\n{getattr(donor, 'name', '') or donor_uid}献出魂与血，"
                  f"队伍恢复并获得{round(info['ratio'] * 100)}%攻、防、生命与速度加成。\n"
                  f"代价：{info['path']}体系跌落一层，练气与炼体归一；十五分钟后从败亡节点续战。")

def finish_team(state: dict, team_id: str, now: float | None = None) -> bool:
    """完成结算后解除队员行动锁并恢复原版可再次招募状态。"""
    now = time.time() if now is None else float(now)
    root = _root(state)
    team = root["teams"].get(str(team_id))
    if not isinstance(team, dict) or team.get("status") not in {"settled", "refined"}:
        return False
    if team.get("solo"):
        for uid in team.get("members", []):
            if root["player_team"].get(_uid(uid)) == str(team_id):
                root["player_team"].pop(_uid(uid), None)
        root["teams"].pop(str(team_id), None)
        return True
    for key in ("started_at", "stage", "stage_started", "phase_end", "retry_stage",
                "primary_name", "enemy_names", "enemy_state", "member_hp", "rescue_end",
                "sacrifice_buff", "imperial_pill", "old_man_reward", "settlement",
                "last_result", "last_outcome", "pending_reward", "last_roster",
                "enemy_multipliers", "cumulative_reward", "stage_reports"):
        team.pop(key, None)
    team["status"] = "recruiting"
    team["expires_at"] = now + TEAM_TTL
    return True


def apply_team_teachings(party: Sequence[Any], players: Mapping[str, Any],
                         member_ids: Sequence[str]) -> dict[str, list[dict]]:
    """结算遭受荒天帝真意命中的成员；达到30进度后学习对应功法。"""
    result: dict[str, list[dict]] = {}
    for uid, fighter in zip(map(_uid, member_ids), party):
        doc = players.get(uid)
        if doc is None:
            continue
        outcomes = []
        for name in sorted(fighter.tags.get("river_teaching_seen", set())):
            gained, mastered = river_combat.teaching_progress(doc, name)
            if gained:
                outcomes.append({"name": name, "gained": gained,
                                 "progress": int((doc.ext.get("river_teachings") or {}).get(name, 0)),
                                 "mastered": mastered})
        if outcomes:
            result[uid] = outcomes
    return result


def release_expired_rescue(state: dict, team_id: str, now: float | None = None) -> dict | None:
    """将一支超时待援队伍转换为炼化结局，并保留供入口执行的逐成员惩罚名单。"""
    root = _root(state)
    team = root["teams"].get(str(team_id))
    if not isinstance(team, dict):
        return None
    result = expire_rescue(team, now)
    if result:
        result["team_id"] = str(team_id)
        result["member_ids"] = list(map(_uid, team.get("members", [])))
    return result
