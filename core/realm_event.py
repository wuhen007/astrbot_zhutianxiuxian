"""W8-F9 位面大事件 / 异域叩击帝关（纯函数层，无 IO）。

原版依据：
- `apps/tasks/RealmEvents.js` 1912 行：**无 rule 的服务类**，由 `EraChangeTask` 推进纪元时
  以 0.35 概率触发；`getDefaultEventConfig()` 冷却 2000 世界年、持续 24h、最多 3 个活跃、
  历史 100 条；`getAvailableEvents(eraIndex)` 五时代加权类型池。
- `apps/SecretPlace/SecretPlace.js:415` `参与位面大事件|夺宝|探查遗迹`：必须抵达事件精确
  坐标，每人每事件一次，奖励 `max(10000, (level_id + Physique_id + mijinglevel_id*2 + 2)*5000)`
  修为 + 等额血气。
- `apps/tasks/EraChangeTask.js:132` `#(位面)?大事件(记录)?`：当前事件 / 最近记录 / 统计。
- `apps/tasks/ForeignImperialPass.js` 626 行 **4 rule + 5 分钟 cron**、
  `model/foreignImperialPass.js` 199 行：触发 0.25、击杀目标 100、每波 3000 诸天年、
  每 1000 年告急、休整 5000 年、3 波后帝血决战、城破把九天十地/遮天位面标为毁灭。
- `apps/tasks/TravelTask.js` 1238 行：`rule: []`，是**位面穿梭的延时结算 cron**
  (`xiuxian:travel_task:*`)，不是「游历任务」玩法；本移植「#穿梭」「#抵达」已覆盖，不重复实现。

本移植折算：
- 世界年直接用 `era_state["years_total"]`（本移植只有一条时间线，原版 epoch/era 推导作废）。
- 原版 `RealmEvents` 整档 JSON + redis 锁 → `calamity_state["realm_event"]` 单例；帝关整档
  JSON → `calamity_state["imperial_pass"]`。db 恒 v17。
- cron 触发 / 5 分钟检查 → 指令入口惰性 `maybe_spawn()` / `maybe_tick()`。
- 专属玩法（圣地大战 14 条 / 秦门兵字秘 6 条 / 万化天魔传承 / 先天至宝择主之争）本移植
  无底座 → 事件类型池剔除，保留 8 类通用参与事件；「先天灵宝出世」折为通用参与。
- 原版奖励里的 `mijinglevel_id`（秘境阶）改由独立额外境界状态提供，旧档缺字段时按现行境界投影迁移。
- 帝关门槛使用独立秘境/仙古轨等级 (`mijinglevel_id>=13 || xiangulevel_id>=12`)
  （本移植「九天十地」位面门槛）。原版一次打 12~32 名天骄 → 折算 1 场聚合 `battle.spar`。
- 「帝血」道具在 data 里存在但**全库无产出点** → 第三波进入帝血决战时给威名第一的
  参战者发 1 枚，形成闭环；原版囚禁 999999 分钟 / 云崽广播群推送未搬。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from . import plane

# ---------------------------------------------------------------- 位面大事件常量

ERA_TRIGGER_CHANCE = 0.35          # 原版 DEFAULT_ERA_TRIGGER_CHANCE
DUNGEON_TRIGGER_CHANCE = 0.002     # 原版 DEFAULT_DUNGEON_TRIGGER_CHANCE（本批只留常量，副本未接）
EVENT_COOLDOWN_YEARS = 2000        # 原版 getDefaultEventConfig().eventCooldown
EVENT_DURATION = 24 * 3600         # 原版 DEFAULT_EVENT_DURATION_MS
MAX_ACTIVE_EVENTS = 3              # 原版 DEFAULT_MAX_ACTIVE_EVENTS
HISTORY_LIMIT = 100                # 原版 eventHistory.slice(-100)
REWARD_PER_POINT = 5000
REWARD_MIN = 10000

EVENT_KEY = "realm_event"
PASS_KEY = "imperial_pass"

# 通用参与事件与需专属入口的位面事件；特殊事件不走通用参与奖励。
TIANMO_LEGACY_TYPE = "tianmoHuashengLegacy"
EVENT_NAMES: dict[str, str] = {
    "treasureAppear": "先天灵宝出世",
    "merchantVisit": "云游商人降临",
    "prodigyRise": "天骄崛起",
    "forbiddenZone": "禁区异动",
    "worldChange": "天地异变",
    "mysteriousRuins": "神秘遗迹",
    "coordinateClue": "位面坐标石壁",
    "wenxianClue": "问仙古碑",
    TIANMO_LEGACY_TYPE: "万化天魔传承·万相魔冢",
}

# 原版 getAvailableEvents(eraIndex) 五时代权重；其他未移植专属事件仍剔除。
ERA_WEIGHTS: tuple[dict[str, int], ...] = (
    {"treasureAppear": 3, "merchantVisit": 2, "prodigyRise": 2,
     "worldChange": 3, "tianmoHuashengLegacy": 1,
     "coordinateClue": 2, "wenxianClue": 1},                                   # 神话时代
    {"forbiddenZone": 2, "prodigyRise": 2, "treasureAppear": 2,
     "tianmoHuashengLegacy": 1, "coordinateClue": 2, "wenxianClue": 1},       # 太古时代
    {"prodigyRise": 2, "merchantVisit": 2, "tianmoHuashengLegacy": 1,
     "coordinateClue": 2, "wenxianClue": 1},                                   # 天命时代
    {"mysteriousRuins": 3, "forbiddenZone": 2, "worldChange": 2,
     "tianmoHuashengLegacy": 1,
     "coordinateClue": 2, "wenxianClue": 1},                                   # 末法时代
    {"forbiddenZone": 3, "worldChange": 3, "merchantVisit": 2,
     "mysteriousRuins": 2, "tianmoHuashengLegacy": 1,
     "coordinateClue": 2, "wenxianClue": 1},                                   # 绝灵时代
)

OUTCOMES: dict[str, str] = {
    "treasureAppear": "你穿过争夺此宝的修士洪流，截取到一缕先天道韵。",
    "merchantVisit": "你与云游商人交换见闻，从其口中悟得一段异域修行心得。",
    "prodigyRise": "你亲临天骄扬名之地，与各方俊杰论道争锋。",
    "forbiddenZone": "你在禁区边缘记录大道异变，赶在帝威复苏前全身而退。",
    "worldChange": "你抵达天地异变的源点，捕捉到一缕转瞬即逝的大道轨迹。",
    "mysteriousRuins": "你踏入遗迹外围完成初步探查，带回一份残缺的古史记录。",
    "coordinateClue": "你拓下石壁上的残缺星图，辨出一处未曾记录的位面坐标。",
    "wenxianClue": "古碑道纹入心，你隐约窥见问仙之路的一段残章。",
}

# ---------------------------------------------------------------- 帝关常量

PASS_TRIGGER_CHANCE = 0.25         # IMPERIAL_PASS_TRIGGER_CHANCE
KILL_TARGET = 100                 # IMPERIAL_PASS_KILL_TARGET
WAVE_YEARS = 3000                 # IMPERIAL_PASS_WAVE_YEARS
REMINDER_YEARS = 1000             # IMPERIAL_PASS_REMINDER_INTERVAL_YEARS
REST_YEARS = 5000                 # IMPERIAL_PASS_REST_YEARS
SORTIE_CD = 600                   # SORTIE_COOLDOWN_MS = 10 分钟
SURRENDER_CHANCE = 0.3            # SURRENDER_DEMAND_CHANCE
WAVE_ENEMY_RANGES = {1: (12, 16), 2: (18, 24), 3: (26, 32)}
WAVE_KILLS = {1: 20, 2: 25, 3: 30}   # 折算：一次聚合战斗的斩敌数
WAVE_RATIO = {1: 1.0, 2: 1.25, 3: 1.5}
TARGET_PLANES = ("遮天位面", "九天十地")
PASS_MIJING_GATE = 13
PASS_XIANGU_GATE = 12
PASS_REALM_GATE = 26  # Legacy display constant; checks use the extra tracks.
BLOOD_ITEM = "帝血"
CHAMPION_STONES = 50_000_000      # 帝血决战胜利奖励（折算自原版守城全服收益）


# ---------------------------------------------------------------- 状态

def _default_event(world_year: int = 0) -> dict[str, Any]:
    return {
        "enabled": True,
        "active": [],
        "history": [],
        "last_world_year": int(world_year) - EVENT_COOLDOWN_YEARS,
        "stats": {},
        "spawned_year": int(world_year),
    }


def _default_pass() -> dict[str, Any]:
    return {
        "status": "dormant",       # dormant / active / resting / ended
        "campaign": 0,
        "wave": 0,
        "active": None,
        "prestige": {},
        "prisoners": [],
        "history": [],
        "last_checked_year": None,
        "next_wave_year": None,
        "outcome": None,
    }


def event_state(cal: dict, world_year: int) -> tuple[dict, bool]:
    """取（并按需初始化）全服事件档。返回 (档, 是否新建)。"""
    raw = cal.get(EVENT_KEY)
    fresh = not isinstance(raw, dict) or "spawned_year" not in raw
    if fresh:
        raw = _default_event(world_year)
        cal[EVENT_KEY] = raw
    s = raw
    s.setdefault("enabled", True)
    s.setdefault("active", [])
    s.setdefault("history", [])
    s.setdefault("stats", {})
    s.setdefault("last_world_year", int(world_year) - EVENT_COOLDOWN_YEARS)
    s.setdefault("spawned_year", int(world_year))
    return s, fresh


def pass_state(cal: dict) -> tuple[dict, bool]:
    raw = cal.get(PASS_KEY)
    fresh = not isinstance(raw, dict) or "status" not in raw
    if fresh:
        raw = _default_pass()
        cal[PASS_KEY] = raw
    s = raw
    for k, v in _default_pass().items():
        s.setdefault(k, v if not isinstance(v, (dict, list)) else type(v)())
    return s, fresh


def commit(cal: dict, ev: dict, ps: dict) -> None:
    cal[EVENT_KEY] = ev
    cal[PASS_KEY] = ps


def world_year_of(era_state: Mapping) -> int:
    """本移植只有一条时间线：世界年 = years_total。"""
    try:
        return max(0, int(era_state.get("years_total", 0) or 0))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- 事件：生成与惰性触发

def weighted_types(era_index: int) -> list[str]:
    weights = ERA_WEIGHTS[max(0, min(len(ERA_WEIGHTS) - 1, int(era_index or 0)))]
    return [t for t, w in weights.items() for _ in range(w)]


def _pick_location(plane_data: Mapping, rng: Any,
                   unavailable_planes: Sequence[str] = ()) -> tuple[str, str, dict] | None:
    """从未毁灭且有坐标的位面中挑选事件地点，避免生成不可抵达的事件。"""
    unavailable = {str(name) for name in unavailable_planes}
    candidates: list[tuple[str, list[dict]]] = []
    for name in plane.PLANES:
        if name in unavailable:
            continue
        locs = plane.locations_of(plane_data, name)
        if locs:
            candidates.append((name, locs))
    if not candidates:
        return None
    pname, locs = candidates[rng.randrange(len(candidates))]
    loc = locs[rng.randrange(len(locs))]
    try:
        coord = plane.random_coord(loc, rng)
    except (KeyError, TypeError, ValueError):
        coord = {"x": 0, "y": 0}
    return pname, str(loc.get("name") or "无名之地"), coord


def make_event(kind: str, spot: tuple[str, str, dict], now: float,
               world_year: int, rng: Any) -> dict[str, Any]:
    pname, locname, coord = spot
    eid = f"{int(now * 1000)}:{kind}:{rng.randrange(1 << 30)}"
    return {
        "id": eid,
        "type": kind,
        "plane": pname,
        "location": locname,
        "x": int(coord["x"]),
        "y": int(coord["y"]),
        "started_at": float(now),
        "expires_at": float(now) + EVENT_DURATION,
        "world_year": int(world_year),
        "source": "era",
        "participants": [],
    }


def prune(ev: dict, now: float) -> bool:
    """清掉过期事件；返回是否发生变化。"""
    before = len(ev["active"])
    ev["active"] = [e for e in ev["active"]
                    if isinstance(e, dict) and float(e.get("expires_at") or 0) > now]
    return len(ev["active"]) != before


def spawn_text(e: Mapping) -> str:
    if str(e.get("type")) == TIANMO_LEGACY_TYPE:
        return ("【万化天魔传承·万相魔冢】\n"
                f"{e['plane']} › {e['location']}（{e['x']}, {e['y']}）裂开一道贯穿诸天的魔隙。\n"
                "亿万残破灵根与众生本源在其中沉浮，唯有极道天魔可踏入，直面万灵怨胎。\n"
                "抵达后发送「#进入万相魔冢」接受试炼；魔冢将在 24 小时后闭合。")
    return (f"【位面大事件 · {EVENT_NAMES.get(str(e['type']), '未知事件')}】\n"
            f"异象现于 {e['plane']} › {e['location']}（{e['x']}, {e['y']}）。\n"
            f"抵达精确坐标后发送「#参与位面大事件」，可发「#诸天大事件」查看全部。")


def maybe_spawn(ev: dict, world_year: int, era_index: int, now: float, rng: Any,
                plane_data: Mapping, *, force: bool = False,
                preferred: str | None = None,
                exclude_types: Sequence[str] = (),
                unavailable_planes: Sequence[str] = ()) -> tuple[str, bool]:
    """惰性触发（原版 triggerRandomEvent 的折算）。返回 (广播文案, 是否变化)。"""
    prune(ev, now)
    if not ev["enabled"]:
        return "", False
    if not force:
        if int(world_year) - int(ev["last_world_year"]) < EVENT_COOLDOWN_YEARS:
            return "", False
        if rng.random() >= ERA_TRIGGER_CHANCE:
            return "", False
        if len(ev["active"]) >= MAX_ACTIVE_EVENTS:
            return "", False
    elif len(ev["active"]) >= MAX_ACTIVE_EVENTS:
        ev["active"].pop(0)          # 超管强制：挤掉最老的一条
    pool = weighted_types(era_index)
    used = {str(e.get("type")) for e in ev["active"]}
    excluded = {str(value) for value in exclude_types}
    avail = [t for t in pool if t not in used and t not in excluded]
    if not avail:
        return "", False
    kind = preferred if preferred in avail else avail[rng.randrange(len(avail))]
    spot = _pick_location(plane_data, rng, unavailable_planes)
    if not spot:
        return "", False
    e = make_event(kind, spot, now, world_year, rng)
    if force:
        e["source"] = "admin"
    ev["active"].append(e)
    ev["history"].append(dict(e))
    if len(ev["history"]) > HISTORY_LIMIT:
        ev["history"] = ev["history"][-HISTORY_LIMIT:]
    ev["last_world_year"] = int(world_year)
    ev["stats"][kind] = int(ev["stats"].get(kind, 0)) + 1
    return spawn_text(e), True


def clear_events(ev: dict) -> str:
    ev["active"] = []
    ev["last_world_year"] = int(ev.get("spawned_year") or 0) - EVENT_COOLDOWN_YEARS
    return "已清空当前全部位面大事件（历史记录保留）。"


def type_by_name(text: str) -> str | None:
    for key, name in EVENT_NAMES.items():
        if text.strip() in (key, name):
            return key
    return None


# ---------------------------------------------------------------- 事件：参与与展示

def reach(doc: Any, e: Mapping) -> bool:
    """原版 getRealmEventReach：位面相同且坐标精确一致（只读，不回写玩家档）。"""
    ext = doc.ext if isinstance(getattr(doc, "ext", None), dict) else {}
    st = ext.get("plane")
    if not isinstance(st, Mapping):
        return False
    cur = str(st.get("current") or plane.DEFAULT_PLANE)
    if cur != str(e.get("plane")):
        return False
    c = (st.get("coords") or {}).get(cur)
    if not isinstance(c, Mapping):
        return False
    try:
        return int(c.get("x", -1)) == int(e["x"]) and int(c.get("y", -1)) == int(e["y"])
    except (TypeError, ValueError, KeyError):
        return False



def meets_pass_gate(doc: Any) -> bool:
    from . import extra_cultivation
    tracks = extra_cultivation.levels_of(doc)
    return (tracks["mijing"] >= PASS_MIJING_GATE
            or tracks["xiangu"] >= PASS_XIANGU_GATE)

def reward_of(doc: Any) -> int:
    """原版 (level_id + Physique_id + mijinglevel_id*2 + 2) * 5000，下限 10000。"""
    from . import extra_cultivation
    # PlayerDoc stores both base realms as zero-based indexes; the original uses 1-based IDs.
    realm = max(0, int(getattr(doc, "realm_index", 0) or 0)) + 1
    body = max(0, int(getattr(doc, "physique_index", 0) or 0)) + 1
    secret = extra_cultivation.level_of(doc, "mijing")
    return max(REWARD_MIN, (realm + body + secret * 2 + 2) * REWARD_PER_POINT)


def join(ev: dict, uid: str, name: str, doc: Any, now: float) -> tuple[bool, str, int]:
    """返回 (ok, 文案, 修为/血气奖励)。奖励落库由调用方负责。"""
    prune(ev, now)
    live = [e for e in ev["active"] if float(e.get("expires_at") or 0) > now]
    if not live:
        return False, "当前诸天平静，暂无可参与的位面大事件。可发「#诸天大事件」查看记录。", 0
    reached = [e for e in live if reach(doc, e)]
    if not reached:
        spots = "；".join(f"{e['plane']} › {e['location']}（{e['x']}, {e['y']}）" for e in live[:3])
        return False, f"你尚未抵达任何大事件的精确坐标。可先发「#前往 x,y」赶路：{spots}。", 0
    generic = [e for e in reached if str(e.get("type")) != TIANMO_LEGACY_TYPE]
    if not generic:
        return False, "万相魔冢需通过专属试炼获取传承，请发送「#进入万相魔冢」，不可使用通用参与奖励。", 0
    e = next((x for x in generic if str(uid) not in (x.get("participants") or [])), None)
    if e is None:
        return False, "你已经参与过当前可抵达的位面大事件，每人每事件仅限一次。", 0
    e.setdefault("participants", []).append(str(uid))
    for h in ev["history"]:
        if h.get("id") == e.get("id"):
            h["participants"] = list(e["participants"])
    reward = reward_of(doc)
    kind = str(e["type"])
    msg = (f"【{EVENT_NAMES.get(kind, '未知事件')} · 参与成功】\n"
           f"{OUTCOMES.get(kind, '你亲历这场位面大事件，并从中有所收获。')}\n"
           f"事件地点：{e['plane']} › {e['location']}（{e['x']}, {e['y']}）\n"
           f"获得修为 {reward:,}｜血气 {reward:,}｜当前参与 {len(e['participants'])} 人")
    return True, msg, reward


def _left_text(e: Mapping, now: float) -> str:
    mins = max(1, int((float(e.get("expires_at") or 0) - now) // 60))
    return f"{mins // 60} 小时 {mins % 60} 分" if mins >= 60 else f"{mins} 分钟"


def board_lines(ev: dict, now: float, world_year: int, era_name: str = "") -> list[str]:
    prune(ev, now)
    lines = ["【位面大事件】", f"诸天纪年 {world_year} 年" + (f"｜{era_name}" if era_name else ""),
             "--- 当前事件 ---"]
    if not ev["active"]:
        lines.append("当前诸天平静，暂无正在发生的大事件。")
    for e in ev["active"]:
        lines.append(f"· {EVENT_NAMES.get(str(e['type']), '未知事件')}｜"
                     f"{e['plane']} › {e['location']}（{e['x']}, {e['y']}）")
        command = ("#进入万相魔冢" if str(e.get("type")) == TIANMO_LEGACY_TYPE
                   else "#参与位面大事件")
        lines.append(f"  剩余 {_left_text(e, now)}｜已参与 {len(e.get('participants') or [])} 人"
                     f"｜「{command}」")
    lines.append("--- 最近记录 ---")
    if not ev["history"]:
        lines.append("暂无大事件记录。")
    for e in list(reversed(ev["history"]))[:10]:
        lines.append(f"· {EVENT_NAMES.get(str(e['type']), '未知事件')}｜{e['plane']} › {e['location']}"
                     f"｜纪年 {e.get('world_year', 0)} 年｜{len(e.get('participants') or [])} 人")
    lines.append("--- 统计 ---")
    stats = ev.get("stats") or {}
    lines.append("累计触发 " + str(sum(int(v) for v in stats.values())) + " 次｜"
                 + ("、".join(f"{EVENT_NAMES.get(k, k)}×{v}" for k, v in stats.items()) or "无"))
    return lines


def record_participant(ev: dict, event_id: str, uid: str) -> bool:
    """为专属事件记录尝试者，并同步历史快照；重复调用不重复计数。"""
    uid, event_id = str(uid), str(event_id)
    event = next((row for row in ev.get("active", [])
                  if str(row.get("id") or "") == event_id), None)
    if event is None:
        event = next((row for row in reversed(ev.get("history", []))
                      if str(row.get("id") or "") == event_id), None)
    if event is None:
        return False
    participants = event.setdefault("participants", [])
    if uid in participants:
        return False
    participants.append(uid)
    for row in ev.get("history", []):
        if str(row.get("id") or "") == event_id:
            row["participants"] = list(participants)
    return True


def history_lines(ev: dict, limit: int = 20) -> list[str]:
    rows = list(reversed(ev.get("history") or []))[:max(1, int(limit))]
    if not rows:
        return ["【大事件记录】暂无记录。"]
    return ["【大事件记录】"] + [
        f"· 纪年 {e.get('world_year', 0)} 年｜{EVENT_NAMES.get(str(e['type']), '未知事件')}"
        f"｜{e.get('plane')} › {e.get('location')}（{e.get('x')}, {e.get('y')}）"
        f"｜参与 {len(e.get('participants') or [])} 人" for e in rows]


def rules_text() -> str:
    return ("纪元每推进 2000 诸天年有一次 0.35 概率引动异象；同时最多 3 个活跃事件，"
            "每个持续 24 小时，历史保留 100 条。事件类型按当前时代加权，"
            "同类型不重复出现。参与需先到达事件所在位面的精确坐标（「#前往 x,y」），"
            "再发「#参与位面大事件」，每人每事件一次，"
            "奖励修为与等额血气：max(1 万, (境界+炼体+秘境×2+2)×5000)。"
            "超管可发「#引发位面大事件」强制触发、「#清除位面大事件 确认」清场。")


def help_text() -> str:
    return "「#诸天大事件」看当前/记录/统计，「#大事件记录」看历史，「#参与位面大事件」领取机缘。"


# ---------------------------------------------------------------- 帝关：状态机

def _new_wave(wave: int, world_year: int, eligible: Sequence[str], now: float) -> dict:
    return {
        "id": f"{world_year}:{wave}:{int(now)}",
        "wave": int(wave),
        "phase": "army",                 # army / kingBattle
        "started_at": float(now),
        "started_world_year": int(world_year),
        "deadline_world_year": int(world_year) + WAVE_YEARS,
        "king_deadline_world_year": None,
        "reminded_years": [],
        "eligible": [str(x) for x in dict.fromkeys(eligible)],
        "participants": {},
        "total_kills": 0,
        "morale": KILL_TARGET,
        "kill_target": KILL_TARGET,
        "blood_champion": None,
    }


def start_wave(ps: dict, wave: int, world_year: int,
               eligible: Sequence[str], now: float) -> str:
    if wave == 1:
        ps["campaign"] = int(ps.get("campaign") or 0) + 1
    ps["status"] = "active"
    ps["wave"] = int(wave)
    ps["next_wave_year"] = None
    ps["outcome"] = None
    ps["active"] = _new_wave(wave, world_year, eligible, now)
    a = ps["active"]
    lead = {1: "异域不朽者与至尊亲临阵前，百万异域大军压向原始帝城。",
            2: "五千年休养已毕，更多帝族天骄携不朽法器卷土重来。",
            3: "第三次天渊震荡，安澜、俞陀的法相在异域尽头升起。"}.get(wave, "异域大军再度叩关。")
    return (f"【异域叩击帝关 · 第 {wave} 波】\n{lead}\n"
            f"本波需斩敌 {KILL_TARGET} 名，并让 {len(a['eligible'])} 名守城修士全部驰援。\n"
            f"防守期 {WAVE_YEARS} 诸天年，每 {REMINDER_YEARS} 年燃起一次告急烽火。\n"
            f"发「#驰援帝关」参战，「#帝关战况」查看士气与威名榜。")


def support_of(active: Mapping | None) -> tuple[int, int]:
    if not isinstance(active, Mapping):
        return 0, 0
    need = {str(x) for x in (active.get("eligible") or [])}
    parts = active.get("participants") or {}
    got = sum(1 for uid in need if isinstance(parts.get(uid), Mapping)
              and parts[uid].get("supported"))
    return got, len(need)


def is_wave_complete(active: Mapping | None) -> bool:
    if not isinstance(active, Mapping) or active.get("phase") != "army":
        return False
    got, need = support_of(active)
    return (int(active.get("total_kills") or 0) >= int(active.get("kill_target") or KILL_TARGET)
            and got >= need)


def rank_prestige(ps: Mapping, limit: int = 5) -> list[dict]:
    rows = [dict(v, uid=k) for k, v in (ps.get("prestige") or {}).items()
            if isinstance(v, Mapping)]
    rows.sort(key=lambda r: (-int(r.get("prestige") or 0), -int(r.get("kills") or 0)))
    return rows[:max(1, int(limit))]


def due_reminders(active: Mapping, world_year: int) -> list[int]:
    if active.get("phase") != "army":
        return []
    start = int(active.get("started_world_year") or 0)
    deadline = int(active.get("deadline_world_year") or start)
    sent = {int(x) for x in (active.get("reminded_years") or [])}
    return [n for n in range(REMINDER_YEARS, WAVE_YEARS, REMINDER_YEARS)
            if world_year >= start + n and start + n < deadline and n not in sent]


def complete_wave(ps: dict, world_year: int, rng: Any) -> tuple[str, list[dict]]:
    """波次完成。返回 (广播文案, ops)；ops 里 grant=(uid, {物品: 数量})。"""
    a = ps.get("active") or {}
    wave = int(a.get("wave") or ps.get("wave") or 1)
    ranking = rank_prestige(ps, 100)
    ops: list[dict] = []
    if wave >= 3:
        a["phase"] = "kingBattle"
        a["king_deadline_world_year"] = int(world_year) + REMINDER_YEARS
        parts = a.get("participants") if isinstance(a.get("participants"), dict) else {}
        champ = next((r for r in ranking
                      if (parts.get(str(r["uid"])) or {}).get("supported")), None)
        if champ:
            ops.append({"grant": (str(champ["uid"]), {BLOOD_ITEM: 1})})
            tail = (f"帝关需要那一滴跨越万古的帝血，已落入威名第一的{champ.get('name') or champ['uid']}手中。\n"
                    f"请发「#融合帝血」独战不朽之王。")
        else:
            tail = "【帝血未现】暂无可承接帝血的参战者，帝关危矣。"
        return (f"【第三波 · 不朽之王叩关】\n孟天正强行融合未圆满的神胎，以身战不朽；"
                f"两尊不朽之王仍在逼近。\n{tail}"), ops
    captive = None
    if rng.random() < SURRENDER_CHANCE:
        jailed = {str(x.get("qq") or x.get("uid")) for x in (ps.get("prisoners") or [])}
        captive = next((r for r in ranking if str(r["uid"]) not in jailed), None)
        if captive:
            ps.setdefault("prisoners", []).append(
                {"uid": str(captive["uid"]), "name": captive.get("name") or "", "wave": wave})
    ps.setdefault("history", []).append(
        {"wave": wave, "outcome": "routed", "year": int(world_year),
         "kills": int(a.get("total_kills") or 0), "captive": captive["uid"] if captive else None})
    ps["history"] = ps["history"][-20:]
    ps["status"] = "resting"
    ps["active"] = None
    ps["next_wave_year"] = int(world_year) + REST_YEARS
    tail = (f"异域随后索要威名最盛的{captive['name']}，帝关内部有人屈从，其沦为阶下囚。"
            if captive else "帝关拒绝了异域的一切条件，无人被交出。")
    return (f"【帝关大捷 · 第 {wave} 波退军】\n百名异域天骄伏尸城下，大军士气崩溃。\n"
            f"{tail}\n异域将休养 {REST_YEARS} 年，预计纪年 {ps['next_wave_year']} 年再犯。"), ops


def breach(ps: dict, reason: str, world_year: int) -> tuple[str, list[str]]:
    if ps.get("status") == "ended":
        return "", []
    ps["status"] = "ended"
    ps["outcome"] = "breached"
    ps["active"] = None
    ps.setdefault("history", []).append(
        {"wave": int(ps.get("wave") or 0), "outcome": "breached",
         "year": int(world_year), "reason": reason})
    ps["history"] = ps["history"][-20:]
    return (f"【帝关城破 · 位面残破】\n{reason}\n"
            f"原始帝城防线崩塌，{'与'.join(TARGET_PLANES)}被异域法则撕裂，界门永闭。"), list(TARGET_PLANES)


def maybe_tick(ps: dict, world_year: int, now: float, rng: Any,
               eligible: Sequence[str], threshold_met: bool) -> tuple[str, list[dict], bool]:
    """惰性 5 分钟检查的折算。返回 (广播文案, ops, 是否变化)。"""
    wy = int(world_year)
    status = ps.get("status")
    if status == "dormant":
        if ps.get("last_checked_year") == wy:
            return "", [], False
        ps["last_checked_year"] = wy
        if threshold_met and rng.random() < PASS_TRIGGER_CHANCE:
            return start_wave(ps, 1, wy, eligible, now), [], True
        return "", [], True                    # 首次检查年必须落库，否则每年都会重掷
    if status == "resting":
        if wy >= int(ps.get("next_wave_year") or 0):
            return start_wave(ps, int(ps.get("wave") or 0) + 1, wy, eligible, now), [], True
        return "", [], False
    if status != "active":
        return "", [], False
    a = ps.get("active")
    if not isinstance(a, Mapping):
        ps["status"] = "dormant"
        return "", [], True
    if a.get("phase") == "army" and is_wave_complete(a):
        msg, ops = complete_wave(ps, wy, rng)
        return msg, ops, True
    deadline = int(a.get("king_deadline_world_year") if a.get("phase") == "kingBattle"
                   else a.get("deadline_world_year") or 0)
    if wy >= deadline:
        msg, planes = breach(ps, "帝关援军未能在期限内完成防守", wy)
        return msg, [{"destroy_planes": planes}] if planes else [], True
    due = due_reminders(a, wy)
    if due:
        a["reminded_years"] = sorted(set(int(x) for x in (a.get("reminded_years") or [])) | set(due))
        left = max(0, deadline - wy)
        return (f"【帝关烽火 · 叩关第 {due[-1]} 年】\n"
                f"异域战车遮蔽大地，城砖已被鲜血染红，距防守期限尚余 {left} 诸天年。\n"
                f"发「#驰援帝关」迎战，「#帝关战况」查看战局。"), [], True
    return "", [], False


# ---------------------------------------------------------------- 帝关：出战 / 决战

def sortie_cd_left(ps: Mapping, uid: str, now: float) -> int:
    a = ps.get("active")
    if not isinstance(a, Mapping):
        return 0
    p = (a.get("participants") or {}).get(str(uid))
    if not isinstance(p, Mapping):
        return 0
    return max(0, int(SORTIE_CD - (float(now) - float(p.get("last_sortie_at") or 0))))


def apply_sortie(ps: dict, uid: str, name: str, kills: int,
                 defeated: bool, now: float) -> None:
    """原版 applyImperialPassSortie 直译。"""
    a = ps["active"]
    parts = a.setdefault("participants", {})
    p = parts.get(str(uid)) or {"uid": str(uid), "name": name, "sorties": 0,
                                "kills": 0, "prestige": 0, "deaths": 0, "supported": False}
    k = max(0, int(kills))
    p["name"] = name or p.get("name") or str(uid)
    p["sorties"] = int(p.get("sorties") or 0) + 1
    p["kills"] = int(p.get("kills") or 0) + k
    p["prestige"] = int(p.get("prestige") or 0) + k
    p["deaths"] = int(p.get("deaths") or 0) + (1 if defeated else 0)
    p["supported"] = True
    p["last_sortie_at"] = float(now)
    parts[str(uid)] = p
    a["total_kills"] = int(a.get("total_kills") or 0) + k
    a["morale"] = max(0, int(a.get("kill_target") or KILL_TARGET) - a["total_kills"])
    total = ps.setdefault("prestige", {}).get(str(uid)) or {"name": name, "prestige": 0, "kills": 0}
    total["name"] = name or total.get("name") or str(uid)
    total["prestige"] = int(total.get("prestige") or 0) + k
    total["kills"] = int(total.get("kills") or 0) + k
    ps["prestige"][str(uid)] = total


def fuse(ps: dict, uid: str, name: str, victory: bool,
         world_year: int) -> tuple[bool, str, list[dict]]:
    """帝血决战。返回 (ok, 文案, ops)。"""
    a = ps.get("active")
    if ps.get("status") != "active" or not isinstance(a, Mapping) or a.get("phase") != "kingBattle":
        return False, "孟天正事件尚未触发，帝血此刻没有回应。", []
    if a.get("blood_champion"):
        return False, "帝血已经照耀天渊，仙王之战已有结果。", []
    p = (a.get("participants") or {}).get(str(uid))
    if not isinstance(p, Mapping) or not p.get("supported"):
        return False, "你未曾驰援本次帝关之战，帝血不与城关因果共鸣。", []
    a["blood_champion"] = {"uid": str(uid), "name": name, "at": time.time()}
    if victory:
        ps["status"] = "ended"
        ps["outcome"] = "defended"
        ps["active"] = None
        ps.setdefault("history", []).append(
            {"wave": 3, "outcome": "defended", "year": int(world_year), "champion": str(uid)})
        ps["history"] = ps["history"][-20:]
        return True, ("【帝血融合 · 仙王一战】\n"
                      f"{name}承接那滴跨越万古的帝血，短暂踏入仙王领域，独战安澜、俞陀！\n"
                      "帝血一击横断天渊，两尊不朽之王退回异域，第三波攻势彻底瓦解。\n"
                      "原始帝城守住了。"), [{"stones": (str(uid), CHAMPION_STONES)}]
    msg, planes = breach(ps, "帝血仙王战败，安澜以黄金古矛贯穿帝血法相", int(world_year))
    return True, ("【帝血融合 · 仙王一战】\n"
                  "安澜以黄金古矛贯穿帝血法相，俯视帝关：“纵借他人道果，亦不过败者。”\n"
                  + msg), [{"destroy_planes": planes}] if planes else []


def force(ps: dict, world_year: int, now: float, eligible: Sequence[str]) -> str:
    if ps.get("status") == "active":
        return "异域已经在叩关。"
    if ps.get("status") == "resting":
        wave = int(ps.get("wave") or 0) + 1
    else:
        wave = 1
        if ps.get("status") == "ended":
            ps["history"] = ps["history"][-20:]     # 保留战史，重置战役计数
            ps["campaign"] = 0
    msg = start_wave(ps, wave, int(world_year), eligible, now)
    return "已强制点燃原始帝城烽火。\n" + msg


# ---------------------------------------------------------------- 帝关：面板

def panel_lines(ps: dict, world_year: int) -> list[str]:
    st = ps.get("status")
    if st == "dormant":
        return ["【帝关战况】", "原始帝城烽燧未燃，异域暂未叩关。",
                f"需有修士达到人体秘境第 {PASS_MIJING_GATE} 级或仙古第 {PASS_XIANGU_GATE} 级，且每次纪元推进有 0.25 概率叩关。"]
    if st == "resting":
        return ["【帝关战后】", "异域大军暂退，正在休养生息。",
                f"当前已过第 {ps.get('wave')} 波，下一波将在纪年 {ps.get('next_wave_year')} 年到来。",
                f"距离再犯尚余 {max(0, int(ps.get('next_wave_year') or 0) - int(world_year))} 年。"]
    if st == "ended":
        return ["【帝关战史】",
                "帝血照耀天渊，不朽之王退去，原始帝城守住了。" if ps.get("outcome") == "defended"
                else "城防已破，遮天位面与九天十地皆沦为残破位面。",
                f"超管可发「#强制异域叩关」重开战役。"]
    a = ps.get("active") or {}
    got, need = support_of(a)
    phase = "孟天正融合神胎，帝血决战不朽之王" if a.get("phase") == "kingBattle" else "异域天骄与大军攻城"
    lines = [f"【异域叩击帝关 · 第 {a.get('wave')} 波】", f"阶段：{phase}",
             f"异域士气：{a.get('morale')}/{KILL_TARGET}｜天骄斩敌：{a.get('total_kills')}/{KILL_TARGET}",
             f"帝关应援：{got}/{need}",
             f"防守期限：纪年 {a.get('king_deadline_world_year') if a.get('phase') == 'kingBattle' else a.get('deadline_world_year')} 年",
             "", "--- 帝关威名榜 ---"]
    ranking = rank_prestige(ps, 5)
    if ranking:
        lines += [f"{i + 1}. {r.get('name') or r['uid']}｜威名 {r.get('prestige')}｜斩敌 {r.get('kills')}"
                  for i, r in enumerate(ranking)]
    else:
        lines.append("尚无人出战。")
    if a.get("phase") == "kingBattle" and not a.get("blood_champion"):
        lines += ["", "孟天正以身阻敌，携带「帝血」的参战者请发「#融合帝血」。"]
    return lines


def prestige_lines(ps: dict, limit: int = 20) -> list[str]:
    rows = rank_prestige(ps, limit)
    if not rows:
        return ["【帝关威名榜】尚无人出战。"]
    return ["【帝关威名榜】"] + [
        f"{i + 1}. {r.get('name') or r['uid']}｜威名 {r.get('prestige')}｜斩敌 {r.get('kills')}"
        for i, r in enumerate(rows)]


def pass_rules_text() -> str:
    return ("有人体秘境第 13 级或仙古第 12 级修士后，纪元推进时有 0.25 概率点燃帝关烽火；共 3 波，"
            "每波需发「#驰援帝关」斩敌 100 且全部守城修士驰援，期限 3000 诸天年（每 1000 年告急）。"
            "两波之间休整 5000 年；第三波进入帝血决战，持「帝血」的参战者可发「#融合帝血」。"
            "出战冷却 10 分钟，须身处遮天位面或九天十地，战况看「#帝关战况」。"
            "城破会把这两方位面标为毁灭。"
            "超管可发「#强制异域叩关」直接开战。")


def pass_help_text() -> str:
    return ("「#帝关战况」看士气与威名榜，「#驰援帝关」出战，「#融合帝血」决战，"
            "「#帝关威名榜」看全榜，超管「#强制异域叩关」开战。")
