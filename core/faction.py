"""势力（W7-3）：三大势力的加入 / 退出 / 贡献 / 分级俸禄。

原版 `apps/User/shili.js`（1403 行，瑶池 / 摇光 + 剑云海，职位表与每日俸禄）。

主流程接入固定原版职位升迁、入门奖励、源石日俸、退出冷却、剑云海唯一传人与五次副本掉落庇护；势力基金供奉仍保留移植版适配。
- 基础适配俸禄：`等级 × 1200 灵石 ×（宗主 ×2）`，22 小时一次，从势力基金支出
- 基础适配等级：累计贡献 `1 + 总贡献 // 200000`，上限 9
- 基础适配供奉：1 灵石折 2 点贡献

shortcut：剑云海宝库按固定原版已有入口与三选机缘接线；原版地盘战与 NPC 剧情仍未移植。势力供奉基金与总贡献等级继续按移植版口径运行。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import random
import time
from typing import Any

LEVEL_MAX = 9
CONTRIB_PER_LEVEL = 200_000
SALARY_PER_LEVEL = 1200
SALARY_COOLDOWN = 22 * 3600
CONTRIB_RATE = 2          # 1 灵石 = 2 点贡献
FACTION_EXIT_COOLDOWN = 72 * 3600
FACTION_ELITE_EXIT_COOLDOWN = 7 * 24 * 3600
ELITE_POSITIONS = frozenset({"圣子", "圣女", "传人", "宫主"})
POSITION_ORDER = {
    "瑶池圣地": ("记名女弟子", "正式女弟子", "亲传女弟子", "真传女弟子", "圣女"),
    "摇光圣地": ("记名弟子", "外门弟子", "内门弟子", "核心弟子", "真传弟子", "圣子", "圣女"),
    "剑云海": ("传人",),
}
APTITUDE_ORDER = ("天弃之人", "先天不足", "平庸之资", "超凡资质", "天纵之资",
                  "旷世奇才", "绝世天骄", "万古无双", "无演无尽")
POSITION_RULES = {
    "瑶池圣地": {
        "记名女弟子": {"next": "正式女弟子", "cost": 5_000, "realm": 2, "aptitude": 2},
        "正式女弟子": {"next": "亲传女弟子", "cost": 10_000, "realm": 3, "aptitude": 3},
        "亲传女弟子": {"next": "真传女弟子", "cost": 50_000, "realm": 5, "aptitude": 4},
        "真传女弟子": {"next": "圣女", "cost": 200_000, "realm": 6, "aptitude": 5},
        "圣女": {"next": "", "cost": 0, "realm": 8, "aptitude": 6},
    },
    "摇光圣地": {
        "记名弟子": {"next": "外门弟子", "cost": 3_000, "realm": 2, "aptitude": 3, "exam": True, "test": "通过基础圣光术考核"},
        "外门弟子": {"next": "内门弟子", "cost": 8_000, "realm": 3, "aptitude": 3, "exam": True, "test": "完成宗门任务并掌握混元圣光术基础"},
        "内门弟子": {"next": "核心弟子", "cost": 20_000, "realm": 4, "aptitude": 4, "exam": True, "test": "通过圣光塔三层试炼"},
        "核心弟子": {"next": "真传弟子", "cost": 50_000, "realm": 5, "aptitude": 5, "exam": True, "test": "获得至少三位长老认可"},
        "真传弟子": {"next": "圣女/圣子", "cost": 150_000, "realm": 6, "aptitude": 6, "exam": True, "test": "通过龙纹黑金鼎的认可"},
        "圣子": {"next": "", "cost": 0, "realm": 8, "aptitude": 7, "exam": False, "test": "击败当代其他圣子候选人"},
        "圣女": {"next": "", "cost": 0, "realm": 8, "aptitude": 7, "exam": False, "test": "击败当代其他圣女候选人"},
    },
}
POSITION_SALARIES = {
    # Original raw sources are divided by 100, matching this plugin's yuanshi currency scale.
    "瑶池圣地": {"记名女弟子": 1_000, "正式女弟子": 5_000,
                   "亲传女弟子": 20_000, "真传女弟子": 50_000, "圣女": 120_000},
    "摇光圣地": {"记名弟子": 1_000, "外门弟子": 5_000,
                   "内门弟子": 20_000, "核心弟子": 50_000,
                   "真传弟子": 80_000, "圣子": 120_000, "圣女": 120_000},
}
PROMOTION_REWARDS = {
    "瑶池圣地": {
        "正式女弟子": (("西皇经·道宫卷", "功法", 1),),
        "亲传女弟子": (("蟠桃仙种", "草药", 3),),
        "真传女弟子": (("西皇经", "功法", 1),),
        "圣女": (("瑶池仙令", "道具", 1),),
    },
    "摇光圣地": {
        "外门弟子": (("摇光经·道宫卷", "功法", 1),),
        "内门弟子": (("中品源石", "道具", 100),),
        "核心弟子": (("混元圣光术", "功法", 1),),
        "真传弟子": (("摇光圣典", "功法", 1), ("上品源石", "道具", 50)),
        "圣子": (("圣子令", "道具", 1), ("超品源石", "道具", 20), ("龙纹黑金鼎仿品", "装备", 1)),
        "圣女": (("圣女令", "道具", 1), ("超品源石", "道具", 20), ("龙纹黑金鼎仿品", "装备", 1)),
    },
}
JOIN_REWARDS = {
    "瑶池圣地": {
        "base": (("西皇经·轮海卷", "功法", 1), ("下品源石", "道具", 100)),
        "超凡资质": (("瑶池筑基丹", "丹药", 3), ("百草液", "道具", 5)),
        "旷世奇才": (("太阴缚灵诀", "功法", 1), ("百草液", "道具", 10)),
    },
    "摇光圣地": {
        "base": (("摇光经·轮海卷", "功法", 1), ("下品源石", "道具", 100)),
        "超凡资质": (("百草液", "道具", 1),),
        "天纵之资": (("百草液", "道具", 3),),
        "旷世奇才": (("中品源石", "道具", 50), ("百草液", "道具", 5)),
    },
}

DEFAULT_FACTIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "瑶池圣地", "icon": "🌸",
        "desc": "西昆仑遗脉，以灵泉与丹术闻名，门下多女修。",
        "focus": "疗伤与丹药",
        "requirement": 0,
    },
    {
        "name": "摇光圣地", "icon": "⚜️",
        "desc": "东荒七大圣地之首，圣主坐镇，攻伐之术冠绝诸天。",
        "focus": "攻伐与炼器",
        "requirement": 0,
    },
    {
        "name": "剑云海", "icon": "⚔️",
        "desc": "剑修圣地，一剑破万法，只问剑心不问出身。",
        "focus": "剑道与暴击",
        "requirement": 0,
    },
)


def default_state() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for f in DEFAULT_FACTIONS:
        rows[f["name"]] = {
            "level": 1,
            "contribution": 0,
            "fund": 0,
            "members": {},
        }
    return {"factions": rows}


def ensure(value: Mapping | None) -> dict[str, Any]:
    state = dict(value or {})
    rows = state.get("factions")
    state["factions"] = dict(rows) if isinstance(rows, Mapping) else {}
    cooldowns = state.get("exit_cooldowns")
    state["exit_cooldowns"] = dict(cooldowns) if isinstance(cooldowns, Mapping) else {}
    for f in DEFAULT_FACTIONS:
        row = state["factions"].get(f["name"])
        row = dict(row) if isinstance(row, Mapping) else {}
        row.setdefault("contribution", 0)
        row.setdefault("fund", 0)
        row.setdefault("members", {})
        if not isinstance(row.get("members"), Mapping):
            row["members"] = {}
        row["level"] = level_of(int(row.get("contribution", 0) or 0))
        state["factions"][f["name"]] = row
    return state


def info_of(name: str) -> dict[str, Any] | None:
    target = canonical_name(name)
    return next((dict(f) for f in DEFAULT_FACTIONS if f["name"] == target), None)


def names() -> list[str]:
    return [f["name"] for f in DEFAULT_FACTIONS]


def level_of(contribution: int) -> int:
    return min(LEVEL_MAX, 1 + max(0, int(contribution)) // CONTRIB_PER_LEVEL)


def next_level_at(contribution: int) -> int | None:
    lv = level_of(contribution)
    if lv >= LEVEL_MAX:
        return None
    return lv * CONTRIB_PER_LEVEL


def faction_of(state: Mapping, uid: str) -> str | None:
    for name, row in (state.get("factions") or {}).items():
        if uid in (row.get("members") or {}):
            return str(name)
    return None


def member_of(state: Mapping, name: str, uid: str) -> dict | None:
    row = (state.get("factions") or {}).get(name) or {}
    m = (row.get("members") or {}).get(uid)
    return dict(m) if isinstance(m, Mapping) else None


def is_leader(state: Mapping, name: str, uid: str) -> bool:
    m = member_of(state, name, uid)
    return bool(m) and m.get("role") == "宗主"


def canonical_name(name: str) -> str:
    return {"瑶池": "瑶池圣地", "摇光": "摇光圣地"}.get(str(name or "").strip(), str(name or "").strip())


def aptitude_rank(value: Any) -> int:
    """Original promotion order; `岁云` is treated as 无演无尽."""
    name = str(value or "").strip()
    if name == "岁云":
        name = "无演无尽"
    return APTITUDE_ORDER.index(name) if name in APTITUDE_ORDER else -1


def original_daily_salary_by_position(name: str, position: str) -> int:
    return int(POSITION_SALARIES.get(canonical_name(name), {}).get(str(position or ""), 0))


def promotion_reward_rows(name: str, position: str) -> tuple[tuple[str, str, int], ...]:
    faction_name = canonical_name(name)
    return tuple(PROMOTION_REWARDS.get(faction_name, {}).get(str(position or ""), ()))


def original_daily_salary(state: Mapping, uid: str) -> tuple[int, str, str]:
    """Original position-based daily salary, in 源石; existing port pay() stays scaled/adapted."""
    name = faction_of(state, uid)
    if name not in POSITION_SALARIES:
        return 0, "", ""
    member = member_of(state, name, uid) or {}
    position = str(member.get("position") or ("记名女弟子" if name == "瑶池圣地" else "记名弟子"))
    table = POSITION_SALARIES[name]
    return int(table.get(position, next(iter(table.values())))), name, position


def promotion_info(name: str, current_position: str, sex: Any = None) -> dict[str, Any] | None:
    faction_name = canonical_name(name)
    data = POSITION_RULES.get(faction_name, {}).get(str(current_position or ""))
    if not data:
        return None
    result = dict(data)
    if faction_name == "摇光圣地" and current_position == "真传弟子":
        result["next"] = "圣女" if str(sex) in ("1", "女", "female") else "圣子"
    return result


def promotion_rewards(name: str, position: str, player: Any | None = None) -> dict[str, int]:
    """Exact original per-position rewards, returned as inventory deltas."""
    faction_name = canonical_name(name)
    role = str(position or "")
    if faction_name == "摇光圣地" and role == "圣女/圣子":
        ext = getattr(player, "ext", {}) or {}
        legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
        sex = (getattr(player, "sex", None) or ext.get("sex")
               or (legacy or {}).get("sex"))
        role = "圣女" if str(sex) in ("1", "女", "female") else "圣子"
    return {item: qty for item, _kind, qty in PROMOTION_REWARDS.get(faction_name, {}).get(role, ())}


def check_promotion(name: str, current_position: str, realm_level: int,
                    aptitude: Any, yuan_stones: int, *, sex: Any = None,
                    exam_roll: float | None = None) -> dict[str, Any]:
    """Evaluate source gates without guessing task/exam completion. Caller supplies original exam roll if wired."""
    faction_name = canonical_name(name)
    info = promotion_info(faction_name, current_position, sex)
    if not info or not info.get("next") or int(info.get("cost", 0) or 0) <= 0:
        return {"ok": False, "reason": "max_position", "required": info}
    rank = aptitude_rank(aptitude)
    if int(realm_level) < int(info["realm"]):
        return {"ok": False, "reason": "realm", "required": info}
    if rank < int(info["aptitude"]):
        return {"ok": False, "reason": "aptitude", "required": info}
    cost = int(info["cost"])
    if int(yuan_stones) < cost:
        return {"ok": False, "reason": "currency", "cost": cost, "required": info}
    if info.get("exam"):
        if exam_roll is None:
            return {"ok": False, "reason": "exam_required", "required": info,
                    "exam_pass_rate": min(0.95, 0.70 + (rank - 3) * 0.05)}
        chance = min(0.95, 0.70 + (rank - 3) * 0.05)
        if float(exam_roll) > chance:
            # The fixed original source only mentions a 10% exam fee in its reply;
            # it returns before mutating/saving the player's yuan-stone balance.
            return {"ok": False, "reason": "exam_failed", "cost": 0,
                    "required": info, "exam_pass_rate": chance}
    return {"ok": True, "reason": "ready", "cost": cost,
            "position": str(info["next"]), "reward": promotion_rewards(faction_name, str(info["next"]))}


def apply_promotion(state: dict, uid: str, position: str) -> bool:
    name = faction_of(state, uid)
    if not name:
        return False
    row = state["factions"][name]
    members = dict(row.get("members") or {})
    member = dict(members.get(uid) or {})
    if not member:
        return False
    member["position"] = str(position)
    members[uid] = member
    row["members"] = members
    state["factions"][name] = row
    return True


def promote(state: dict, doc: Any, *, realm_level: int, aptitude: Any,
            yuan_stones: int, exam_roll: float | None = None,
            sex: Any = None) -> dict[str, Any]:
    """Apply an eligible original Yaochi/Yaoguang rank promotion.

    Currency deduction and inventory grant are returned to the caller for one DB
    transaction. Any unimplemented exam remains a hard stop; this helper never
    skips a task gate or refunds an already-consumed exam cost.
    """
    uid = str(getattr(doc, "uid", ""))
    name = faction_of(state, uid)
    if not name:
        return {"ok": False, "reason": "not_member", "cost": 0, "items": {}}
    member = member_of(state, name, uid) or {}
    position = str(member.get("position") or ("记名女弟子" if name == "瑶池圣地" else "记名弟子"))
    checked = check_promotion(name, position, realm_level, aptitude, yuan_stones,
                              sex=sex, exam_roll=exam_roll)
    if not checked.get("ok"):
        return {**checked, "items": {}}
    next_position = str(checked["position"])
    if not apply_promotion(state, uid, next_position):
        return {"ok": False, "reason": "not_member", "cost": 0, "items": {}}
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["势力"] = name
        ext["势力职位"] = next_position
    items = promotion_reward_once(doc, name, next_position)
    return {**checked, "items": items}


def promotion_reward_once(doc: Any, faction_name: str, position: str) -> dict[str, int]:
    """Return and record one-time original rewards in the player document."""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return {}
    history = ext.setdefault("势力履历", {})
    if not isinstance(history, dict):
        history = ext["势力履历"] = {}
    history_key = "瑶池" if canonical_name(faction_name) == "瑶池圣地" else canonical_name(faction_name)
    entry = history.setdefault(history_key, {"已领取入门奖励": False, "已领取晋升奖励": []})
    claimed = list(entry.get("已领取晋升奖励") or [])
    if position in claimed:
        return {}
    claimed.append(position)
    entry["已领取晋升奖励"] = claimed
    entry["最高职位"] = position
    return promotion_rewards(faction_name, position, doc)


def join_player(state: dict, doc: Any, name: str, *, place: str, realm_level: int,
                aptitude: Any, sex: Any = None, now: float | None = None,
                rng: Any = None) -> tuple[bool, str, dict[str, int]]:
    """Original restricted Yaochi/Yaoguang recruitment with once-per-lifetime rewards."""
    faction_name = canonical_name(name)
    info = info_of(faction_name)
    if not info:
        return False, f"没有「{name}」这个势力。#势力列表 查看。", {}
    if faction_name == "剑云海":
        return False, "剑云海不接受普通拜入；成仙后持令造访，并在机缘中选择成为传人。", {}
    if str(place or "") != "遮天位面":
        return False, ("你不在遮天位面，无法感应圣地接引。"), {}
    ext = getattr(doc, "ext", {}) or {}
    uid = str(getattr(doc, "uid", ""))
    now = time.time() if now is None else float(now)
    state_cooldown = float((state.get("exit_cooldowns") or {}).get(uid, 0) or 0)
    personal_cooldown = float(ext.get("势力脱离冷却至", 0) or 0)
    if faction_of(state, uid):
        return False, f"你已在「{faction_of(state, uid)}」，先 #退出势力 再改换门庭。", {}
    cooldown_until = max(state_cooldown, personal_cooldown)
    if cooldown_until > now:
        return False, f"脱离势力后的冷却尚未结束，还需 {max(1, int((cooldown_until-now+59)//60))} 分钟。", {}
    rank = aptitude_rank(aptitude)
    if faction_name == "瑶池圣地":
        if str(sex) not in ("1", "女", "female"):
            return False, "瑶池圣地自古只招收女修。", {}
        if rank < 2:
            return False, "瑶池入门需至少平庸之资。", {}
        if int(realm_level) > 6:
            return False, "当前道基已固，瑶池暂不接纳高境界修士。", {}
        roller = rng or random
        if float(roller.random()) < 0.30:
            return False, "心境未臻：瑶池仙镜映照心念，未通过入门考核。", {}
    elif faction_name == "摇光圣地":
        if rank < 3:
            return False, "摇光入门需至少超凡资质。", {}
    history = ext.get("势力履历") if isinstance(ext, Mapping) else None
    legacy_name = "瑶池" if faction_name == "瑶池圣地" else faction_name
    prior = (history.get(faction_name) or history.get(legacy_name)) if isinstance(history, Mapping) else None
    first_join = not bool(prior.get("已领取入门奖励")) if isinstance(prior, Mapping) else True
    # The original Yaochi/Yaoguang invitation handlers do not share a numeric realm gate.
    ok, message = join(state, faction_name, uid, str(getattr(doc, "name", "") or uid),
                       int(info["requirement"]))
    if not ok:
        return False, message, {}
    row = state["factions"][faction_name]
    members = dict(row.get("members") or {})
    member = dict(members[uid])
    member["position"] = "记名女弟子" if faction_name == "瑶池圣地" else "记名弟子"
    # Preserve the collective leader role assigned by join(); position is a separate rank field.
    members[uid] = member
    row["members"] = members
    if isinstance(ext, dict):
        ext["势力"] = faction_name
        ext["势力职位"] = member["position"]
        history = dict(ext.get("势力履历") or {})
        history_key = "瑶池" if faction_name == "瑶池圣地" else faction_name
        entry = dict(history.get(history_key) or history.get(faction_name) or {})
        entry.setdefault("已领取晋升奖励", [])
        entry["已领取入门奖励"] = True
        entry["最近加入时间"] = now
        entry["最高职位"] = member["position"]
        history[history_key] = entry
        ext["势力履历"] = history
    rewards: dict[str, int] = {}
    if first_join:
        rewards = {item: qty for item, _kind, qty in JOIN_REWARDS[faction_name]["base"]}
        aptitude_name = "无演无尽" if aptitude == "岁云" else str(aptitude or "")
        extra = JOIN_REWARDS[faction_name].get(aptitude_name)
        if faction_name == "瑶池圣地":
            # APTITUDE_ORDER omits the original two lowest grades; original index >=7 maps to rank >=5.
            extra = (JOIN_REWARDS[faction_name]["旷世奇才"] if rank >= 5 else
                     JOIN_REWARDS[faction_name]["超凡资质"] if rank >= 3 else ())
        for item, _kind, qty in extra or ():
            rewards[item] = rewards.get(item, 0) + qty
    return True, message, rewards


def join(state: dict, name: str, uid: str, player_name: str, realm: int) -> tuple[bool, str]:
    name = canonical_name(name)
    info = info_of(name)
    if not info:
        return False, f"没有「{name}」这个势力。#势力列表 查看。"
    if faction_of(state, uid):
        return False, f"你已在「{faction_of(state, uid)}」，先 #退出势力 再改换门庭。"
    cooldown_until = float((state.get("exit_cooldowns") or {}).get(str(uid), 0) or 0)
    if cooldown_until > time.time():
        return False, f"脱离势力后的冷却尚未结束，还需 {max(1, int((cooldown_until-time.time()+59)//60))} 分钟。"
    if int(realm) < int(info["requirement"]):
        return False, f"「{name}」只收第 {int(info['requirement']) + 1} 境以上的修士（你第 {int(realm) + 1} 境）。"
    row = state["factions"][name]
    members = dict(row.get("members") or {})
    role = "宗主" if not members else "门人"
    position = ("记名女弟子" if name == "瑶池圣地" else "记名弟子")
    members[uid] = {"name": player_name, "role": role, "position": position, "contrib": 0}
    row["members"] = members
    state["factions"][name] = row
    tag = "成为开山宗主" if role == "宗主" else "成为门人"
    return True, f"你加入「{info['icon']}{name}」，{tag}。"


def leave(state: dict, uid: str, now: float | None = None) -> tuple[bool, str]:
    name = faction_of(state, uid)
    if not name:
        return False, "你尚未加入任何势力。"
    now = time.time() if now is None else float(now)
    row = state["factions"][name]
    members = dict(row.get("members") or {})
    member = dict(members.get(uid) or {})
    was_leader = member.get("role") == "宗主"
    position = str(member.get("position") or "")
    cooldown = FACTION_ELITE_EXIT_COOLDOWN if position in ELITE_POSITIONS else FACTION_EXIT_COOLDOWN
    state.setdefault("exit_cooldowns", {})[str(uid)] = now + cooldown
    members.pop(uid, None)
    if was_leader and members:
        heir = max(members.items(), key=lambda kv: int((kv[1] or {}).get("contrib", 0) or 0))[0]
        members[heir] = {**members[heir], "role": "宗主"}
    row["members"] = members
    state["factions"][name] = row
    note = "，宗主之位已传给贡献最高者" if was_leader and members else ""
    return True, f"你已脱离「{name}」{note}。"


def leave_player(state: dict, doc: Any, now: float | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else float(now)
    uid = str(getattr(doc, "uid", ""))
    name = faction_of(state, uid)
    member = member_of(state, name, uid) if name else None
    ok, message = leave(state, uid, now)
    if not ok:
        return ok, message
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict) and name:
        position = str((member or {}).get("position") or "")
        history = dict(ext.get("势力履历") or {})
        key = "瑶池" if name == "瑶池圣地" else name
        entry = dict(history.get(key) or {})
        entry.setdefault("已领取晋升奖励", [])
        entry["已领取入门奖励"] = True
        entry["最近脱离时间"] = now
        order = POSITION_ORDER.get(name, ())
        if position and position in order:
            current = order.index(position)
            for completed in order[1:current + 1]:
                if completed not in entry["已领取晋升奖励"]:
                    entry["已领取晋升奖励"].append(completed)
            prior = entry.get("最高职位")
            if not prior or order.index(prior) < current:
                entry["最高职位"] = position
        history[key] = entry
        ext["势力履历"] = history
        ext["势力脱离冷却至"] = float((state.get("exit_cooldowns") or {}).get(uid, 0) or 0)
        ext.pop("势力", None)
        ext.pop("势力职位", None)
    return ok, message


def contribute(state: dict, uid: str, stones: int) -> tuple[bool, str, int]:
    name = faction_of(state, uid)
    if not name:
        return False, "你尚未加入任何势力，何谈贡献。", 0
    amount = int(stones)
    if amount <= 0:
        return False, "【势力·供奉数量无效】供奉数量需大于 0。", 0
    row = state["factions"][name]
    points = amount * CONTRIB_RATE
    before = int(row.get("contribution", 0) or 0)
    row["contribution"] = before + points
    row["fund"] = int(row.get("fund", 0) or 0) + amount
    row["level"] = level_of(row["contribution"])
    members = dict(row.get("members") or {})
    m = dict(members.get(uid) or {"name": uid, "role": "门人", "contrib": 0})
    m["contrib"] = int(m.get("contrib", 0) or 0) + points
    members[uid] = m
    row["members"] = members
    state["factions"][name] = row
    if row["level"] > level_of(before):
        return True, (f"【势力·供奉】供奉 {amount:,} 灵石 → 贡献 +{points:,}；「{name}」升为 {row['level']} 级！"
                      f"基金 {row['fund']:,}。"), points
    return True, (f"【势力·供奉】供奉 {amount:,} 灵石 → 贡献 +{points:,}（势力共 {row['contribution']:,}）；"
                  f"基金 {row['fund']:,}。"), points


def salary(state: dict, uid: str) -> tuple[int, str, str]:
    """移植版基金俸禄（返回灵石额、势力名、身份）；原版源石日俸另见 original_daily_salary。"""
    name = faction_of(state, uid)
    if not name:
        return 0, "", ""
    row = state["factions"][name]
    m = member_of(state, name, uid) or {}
    role = str(m.get("position") or m.get("role") or "门人")
    is_leader_role = str(m.get("role") or "") == "宗主"
    amount = int(row.get("level", 1) or 1) * SALARY_PER_LEVEL * (2 if is_leader_role else 1)
    return amount, str(name), role


def pay(state: dict, uid: str) -> tuple[bool, str, int]:
    amount, name, role = salary(state, uid)
    if not name:
        return False, "你尚未加入任何势力，无俸可领。", 0
    row = state["factions"][name]
    if int(row.get("fund", 0) or 0) < amount:
        return False, (f"「{name}」基金不足发俸（需 {amount:,}，现存 {int(row.get('fund', 0)):,}），"
                       f"快去 #势力贡献 数量 添些香火。"), 0
    row["fund"] = int(row["fund"]) - amount
    state["factions"][name] = row
    return True, f"领取「{name}」俸禄 {amount:,} 灵石（{role}·{int(row.get('level', 1))} 级）。", amount


def list_text(state: Mapping, uid: str = "") -> str:
    mine = faction_of(state, uid) if uid else None
    lines = ["--- 三大势力 ---"]
    for info in DEFAULT_FACTIONS:
        name = info["name"]
        row = (state.get("factions") or {}).get(name) or {}
        members = row.get("members") or {}
        lines.append(
            f"{info['icon']}「{name}」{int(row.get('level', 1))} 级"
            f"｜成员 {len(members)} 人｜基金 {int(row.get('fund', 0)):,}"
            f"｜门槛 第 {int(info['requirement']) + 1} 境"
            f"{' ← 你在此' if mine == name else ''}"
        )
        lines.append(f"   {info['desc']}（偏重：{info['focus']}）")
    lines.append("指令：#加入势力 名字｜#退出势力｜#势力贡献 灵石数｜#势力俸禄｜#势力状态")
    return "\n".join(lines)


def status_text(state: Mapping, uid: str) -> str:
    name = faction_of(state, uid)
    if not name:
        return "你尚未加入任何势力。#势力列表 可看三大势力。"
    row = state["factions"][name]
    m = member_of(state, name, uid) or {}
    amount, _n, role = salary(state, uid)
    nxt = next_level_at(int(row.get("contribution", 0) or 0))
    progress = (f"距 {level_of(row['contribution']) + 1} 级还需 {nxt - int(row['contribution']):,} 贡献"
                if nxt is not None else "已至 9 级（满）")
    return (f"--- {name} · {role} ---\n"
            f"势力等级：{int(row.get('level', 1))} 级｜总贡献 {int(row.get('contribution', 0)):,}｜"
            f"基金 {int(row.get('fund', 0)):,}\n"
            f"你的贡献：{int(m.get('contrib', 0) or 0):,}｜每日俸禄 {amount:,} 灵石\n"
            f"{progress}")


def original_salary_claimed_today(doc: Any, now: float | None = None) -> bool:
    """Original rule: one faction salary claim per Beijing game day across factions."""
    from .clock import day_key
    ext = getattr(doc, "ext", {}) or {}
    value = ext.get("faction_salary_date") or ext.get("faction_salary_ts")
    if value in (None, ""):
        return False
    if isinstance(value, (int, float)):
        # Port legacy timestamp may already have been claimed today.
        return day_key(float(value)) == day_key(time.time() if now is None else float(now))
    today = day_key(time.time() if now is None else float(now))
    stored = str(value)
    return stored == today or (stored.isdigit() and len(stored) <= 2 and int(stored) == int(today[-2:]))


def record_original_salary_claim(doc: Any, now: float | None = None) -> None:
    from .clock import day_key
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["faction_salary_date"] = day_key(time.time() if now is None else float(now))


def original_vault_reward(rng: Any, *, settlement_card: str | None = None,
                          source_stones: int = 30_000_000) -> dict[str, Any]:
    """Original Sword Sea vault: coin first, then card quality, then 70/20/10 tier."""
    card = settlement_card or ("仙品秘境结算卡" if float(rng.random()) < 0.5 else "圣品秘境结算卡")
    roll = float(rng.random())
    amount = 3 if roll < 0.70 else 5
    bonus_boxes = 10 if roll >= 0.90 else 0
    items = {"众生仙钓": amount, "剑云海圣药": amount, card: amount}
    if bonus_boxes:
        items["超越宝盒"] = bonus_boxes
    tier = "基础赏赐" if roll < 0.70 else "鸿运嘉赏" if roll < 0.90 else "天选厚赐"
    rows = [(name, "道具" if name in ("众生仙钓", "超越宝盒", card) else "丹药", count)
            for name, count in items.items()]
    return {"source_stones": int(source_stones), "settlement_card": card,
            "tier": tier, "items": items, "item_rows": rows}


# ---------------------------------------------------------- 剑云海机缘（W33c：原版 shili.js L1227）

JYH_ITEM = "剑云海令牌"
JYH_FLAG = "jyh_chosen"
JYH_STONES = 1_500_000        # 原版 1.5 亿按本项目 ÷100 折算
JYH_PILL = "剑云海圣药"
JYH_SWORD = "永恒终极剑道"
JYH_SHIELD = "帝主庇护"


def jyh_done(doc: Any) -> bool:
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    return bool(ext.get(JYH_FLAG) or ext.get("剑云海已选择")
                or (legacy or {}).get("剑云海已选择"))


def jyh_member(doc: Any) -> bool:
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    return any(str(value or "") == "剑云海" for value in (
        ext.get("势力"), (legacy or {}).get("势力")))


def jyh_choice_record_pending(record: Mapping[str, Any]) -> bool:
    ext = record.get("ext") if isinstance(record.get("ext"), Mapping) else {}
    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), Mapping) else {}
    return bool(ext.get("剑云海选择中") or ext.get("jyh_choice_pending")
                or legacy.get("剑云海选择中"))


def jyh_heir_record(record: Mapping[str, Any], uid: str = "") -> bool:
    if str(record.get("uid") or "") == str(uid):
        return False
    ext = record.get("ext") if isinstance(record.get("ext"), Mapping) else {}
    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), Mapping) else {}
    faction_name = ext.get("势力", legacy.get("势力", record.get("势力")))
    position = ext.get("势力职位", legacy.get("势力职位", record.get("势力职位")))
    return str(faction_name or "") == "剑云海" and str(position or "") == "传人"


def jyh_choice_pending(doc: Any) -> bool:
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
    return bool(ext.get("剑云海选择中") or ext.get("jyh_choice_pending")
                or (legacy or {}).get("剑云海选择中"))


def _jyh_offer_text() -> str:
    return "\n".join([
        "**剑云海机缘**", "",
        "剑魔帝主负手立于万顷剑海之前，静候你的选择。", "",
        "· **修炼资源：** 灵石与剑云海圣药",
        "· **拜师传人：** 继承《永恒终极剑道》",
        "· **帝主庇护：** 黑暗牢笼豁免与副本增益", "",
        "> 此次机缘仅可选择一次。（点击或 #剑云海选择1/2/3）",
    ])


def jyh_visit(doc: Any, inv: Mapping[str, int], realm_index: int,
              stones_have: int) -> tuple[bool, str, int]:
    """#造访剑云海：成仙 + 令牌×1；pending 重试只重显选项，不重复扣牌。"""
    if jyh_done(doc):
        return False, "剑云海的机缘你早已做出抉择，万顷剑海再无你的涟漪。", 0
    if jyh_choice_pending(doc):
        return True, _jyh_offer_text(), 0
    if realm_index < 41:
        return False, "造访剑云海需成仙（主轨第 42 境）方可承受剑魔帝主之威。", 0
    if int((inv or {}).get(JYH_ITEM, 0) or 0) < 1:
        return False, f"需持「{JYH_ITEM}」×1 方可入海（诸天掉落）。", 0
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["剑云海选择中"] = True
        ext["jyh_choice_pending"] = True
    return True, _jyh_offer_text(), 1


def jyh_choose(doc: Any, choice: int,
               consume_token: Callable[[str, int], bool], *,
               faction_state: dict | None = None,
               now: float | None = None,
               token_preconsumed: bool = False,
               existing_heir: bool = False) -> tuple[bool, str, dict[str, int], int]:
    """#剑云海选择1/2/3；仅在确认选择时扣令牌，并可用共享势力态约束传人唯一。"""
    if jyh_done(doc):
        return False, "机缘已做出抉择，不可重选。", {}, 0
    if choice not in (1, 2, 3):
        return False, "请选择 1/2/3。", {}, 0
    if token_preconsumed:
        if not jyh_choice_pending(doc):
            return False, "你尚未持令进入剑云海机缘。", {}, 0
    elif not consume_token(JYH_ITEM, 1):
        return False, f"「{JYH_ITEM}」已不在纳戒，机缘作废。", {}, 0
    if choice == 2:
        uid = str(getattr(doc, "uid", ""))
        ext = getattr(doc, "ext", {}) or {}
        legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
        if (isinstance(faction_state, Mapping) and faction_of(faction_state, uid)) or (
                ext.get("势力") not in (None, "", "无")) or (
                isinstance(legacy, Mapping) and legacy.get("势力") not in (None, "", "无")):
            return False, "你已投身其他势力或仍在脱离冷却，暂不能拜为剑云海传人。", {}, 0
        now = time.time() if now is None else float(now)
        cooldown_until = max(
            float(ext.get("势力脱离冷却至", 0) or 0),
            float(((faction_state or {}).get("exit_cooldowns") or {}).get(uid, 0) or 0),
        )
        if cooldown_until > now:
            return False, "你仍处于脱离势力后的冷却期，尚不能拜为剑云海传人。", {}, 0
        heir = existing_heir
        if isinstance(faction_state, Mapping):
            heir = heir or any(
                str(member_uid) != uid and str((member or {}).get("position") or "") == "传人"
                for row in (faction_state.get("factions") or {}).values()
                for member_uid, member in (row.get("members") or {}).items())
        if heir:
            if isinstance(ext, dict):
                ext.pop("剑云海选择中", None)
                ext.pop("jyh_choice_pending", None)
            return False, "剑云海已有传人，已返还令牌并取消本次选择；可重新造访选择其他机缘。", {JYH_ITEM: 1}, 0
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[JYH_FLAG] = True
        ext["剑云海已选择"] = True
        ext.pop("剑云海选择中", None)
        ext.pop("jyh_choice_pending", None)
    delta: dict[str, int] = {}
    if choice == 1:
        stones = JYH_STONES
        delta[JYH_PILL] = 3
        doc.stones = int(getattr(doc, "stones", 0) or 0) + stones
        text = ("你选了**修炼资源**——灵石 {stones:,} 与剑云海圣药 ×3 归入纳戒，"
                .format(stones=stones) + "剑海之水滋养道基。")
        return True, text, delta, stones
    if choice == 2:
        delta[JYH_SWORD] = 1
        if isinstance(ext, dict):
            ext["势力"] = "剑云海"
            ext["势力职位"] = "传人"
        if isinstance(faction_state, dict):
            ok, _join_message = join(
                faction_state, "剑云海", str(getattr(doc, "uid", "")),
                str(getattr(doc, "name", "") or getattr(doc, "uid", "修士")), 20)
            if not ok:
                if isinstance(ext, dict):
                    ext.pop("势力", None)
                    ext.pop("势力职位", None)
                    ext.pop("剑云海已选择", None)
                    ext.pop(JYH_FLAG, None)
                    ext["剑云海选择中"] = True
                    ext["jyh_choice_pending"] = True
                return False, "无法加入剑云海；本次选择保留，请解除势力/冷却限制后重试。", {}, 0
            members = faction_state["factions"]["剑云海"]["members"]
            members[str(getattr(doc, "uid", ""))]["position"] = "传人"
        learned = list(ext.get("gongfa") or []) if isinstance(ext, dict) else []
        if JYH_SWORD not in learned:
            learned.append(JYH_SWORD)
        if isinstance(ext, dict):
            ext["gongfa"] = learned
        text = ("剑魔帝主抬手认你为**传人**——《永恒终极剑道》化为剑印落入识海，"
                "万剑齐鸣，自此你的剑即是剑海之剑。")
        return True, text, delta, 0
    if isinstance(ext, dict):
        ext["剑云海庇护"] = {"黑暗牢笼": 5, "副本奖励": 5}
    text = ("帝主垂眸一顾——**帝主庇护**印记烙入命轮，获得黑暗牢笼豁免 ×5 与副本奖励 ×5。")
    return True, text, delta, 0



def apply_jyh_dungeon_reward(doc: Any, rewards: Mapping[str, Any]) -> tuple[dict[str, int], int]:
    """Apply the original five-use ×5 Jianyunhai item-drop blessing, per drop."""
    remaining_state = getattr(doc, "ext", {}).get("剑云海庇护")
    remaining = (max(0, int(remaining_state.get("副本奖励", 0) or 0))
                 if isinstance(remaining_state, dict) else 0)
    result: dict[str, int] = {}
    used = 0
    for raw_name, raw_count in (rewards or {}).items():
        name = str(raw_name)
        try:
            count = max(0, min(100_000, int(raw_count or 0)))
        except (TypeError, ValueError, OverflowError):
            continue
        if count <= 0:
            continue
        if remaining > 0:
            result[name] = count * 5
            remaining -= 1
            used += 1
        else:
            result[name] = count
    if used and isinstance(remaining_state, dict):
        remaining_state["副本奖励"] = remaining
    return result, used

def consume_jyh_dark_cage_protection(doc: Any, *, has_ideal_authority: bool = False) -> tuple[bool, int, str]:
    """Original Level.js gate order: Ideal authority wins first; otherwise spend one sword-sea ward."""
    if has_ideal_authority:
        return True, 0, "理想"
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return False, 0, ""
    ward = ext.get("剑云海庇护")
    if not isinstance(ward, dict):
        return False, 0, ""
    remaining = max(0, int(ward.get("黑暗牢笼", 0) or 0))
    if remaining <= 0:
        return False, 0, ""
    remaining -= 1
    ward["黑暗牢笼"] = remaining
    ext["剑云海庇护"] = ward
    return True, remaining, "剑云海"


def consume_jyh_dungeon_reward(doc: Any) -> tuple[int, int]:
    """Consume one of the original five 5× dungeon-item rewards, if any remain."""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return 1, 0
    ward = ext.get("剑云海庇护")
    if not isinstance(ward, dict):
        return 1, 0
    remaining = max(0, int(ward.get("副本奖励", 0) or 0))
    if remaining <= 0:
        return 1, 0
    remaining -= 1
    ward["副本奖励"] = remaining
    ext["剑云海庇护"] = ward
    return 5, remaining


def jyh_rules() -> str:
    nl = chr(10)
    return nl.join([
        "【剑云海机缘·规则】",
        "「成仙修士持剑云海令牌造访剑海，剑魔帝主予你一次三选机缘，永不可重选。」",
        "",
        "· 修炼资源：灵石 150 万 + 剑云海圣药 ×3",
        "· 拜师传人：《永恒终极剑道》功法",
        "· 帝主庇护：【帝主庇护】印记（黑暗牢笼豁免 ×5；秘境单次道具掉落五倍 ×5）",
        "",
        "触发：#造访剑云海（需主轨 42 境 + 剑云海令牌 ×1）",
    ])
