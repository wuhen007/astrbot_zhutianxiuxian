"""诡异小祭 / 大祭团队战、泡影败退、时间线伤害与位面尾声。

玩法数值优先沿用原版 apps/Boss/StrangeSacrifice.js 与 model/strangeSacrifice.js；
战斗继续使用本插件团队引擎和现有安全世界线状态。维持无 cron 的惰性推进，
玩家主档及备份从不删除。遇战门槛沿用本地 0—21 档的 GATE_SMALL / GATE_BIG；
准仙帝门槛在 GATE_SMALL 下移一档，以映射原版 20 / 21 / 22 的相邻三个权柄段。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

from . import authority as authority_mod

WORLD_KEY = "sacrifice"
EXT_KEY = "sacrifice"

SMALL_INTERVAL = 40_000          # 世界年；原版 8 纪元 × 5 万 = 40 万，本移植 ÷10
BIG_DELAY = 10_000               # 原版 2 纪元 × 5 万 = 10 万，本移植 ÷10
EMPEROR_WARNING_YEARS = 2_000    # 原版首位仙帝出现后的小祭预警
WARNING_YEARS = 2_000           # 原版大小祭预警窗口
ACTIVE_YEARS = 2_000             # 原版同值
HEAVEN_SLASH_YEARS = 3_000       # 原版 3 万，本移植 ÷10
DEATHLOCK_SEC = 86_400           # 24h，毫秒口径原版 86400000
INACTIVE_SEC = 86_400            # 24h 无活动自动关闭
FIGHT_CD_SEC = 300               # 5 分钟
ENEMY_SPEED = 100 + 21 * 50      # 原版 1150；仙帝敌军固定速度
BUBBLE_SECONDS = 720 * 60        # 原版泡影现实时间 720 分钟
REWIND_LINE_COUNT = 3
REWIND_LINE_EXTRA_COUNT = 3
ETERNAL_REWRITE_SECONDS = 10 * 86_400

GATE_SMALL = 18                  # authority_21 档；原版 21 仙帝
GATE_BIG = 19                    # 原版 22 祭道
GATE_FINALE = 21                 # 原版 23 祭道之上（本移植满档）
GATE_QUASI_EMPEROR = GATE_SMALL - 1  # 原版大祭允许权柄 20 的准仙帝
GATE_YONGJI = 16                 # 低于此档且在被毁位面 → 记入永寂名单

HIGHLAND = "厄土高原"
# 可毁位面：不含「凡间」（默认位面，毁掉会卡死全部旅行）与高维位面
SACRIFICE_PLANES = ("下界八域", "遮天位面", "九天十地", "界海", "太初星墟")
ANCESTOR_NAMES = ("黑祖", "白祖", "灰祖", "金祖", "赤祖", "青祖", "蓝祖", "紫祖", "银祖", "幽祖")
FIRST_EMPEROR_ALLIES = ("狠人大帝", "无始残尸", "仙帝柳神", "叶倾仙虚影")
SMALL_EMPEROR_COUNT = 5
BIG_ENCOUNTER_COUNT = 10
IMMORTAL_EMPEROR_COUNT = 30

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "phase": "dormant",              # dormant / small / big / destroyed
    "plateau_destroyed": False,      # 三重永久标记之①（本移植另两处见 plane ops）
    "plateau_destroyed_at": 0.0,
    "plateau_destroyed_by": "",
    "small_count": 0,
    "big_count": 0,
    "rewinds": 0,
    "cycle_start": 0,
    "first_emperor": None,            # 首位权柄达标者出现的世界年
    "small_due": None,
    "big_due": None,
    "warned_small_due": None,
    "warned_big_due": None,
    "active": None,                   # {type,first,start,end,id,hp,hpmax,reward}
    "participants": {},               # uid → {result,killed,at}
    "damage": {},                     # uid → 累计伤害（贡献榜）
    "defenders": 0,
    "heaven_slash_until": 0,          # 世界年
    "last_activity": 0.0,
    "last_outcome": {},
    "plane_log": [],                  # 本次祭礼毁掉的位面名（回滚依据）
    "yongji": {},                     # uid → {name,plane,at}；只记名单不删档
}


# ---------------------------------------------------------------- 状态

def world_of(state: Mapping | None) -> dict[str, Any]:
    raw = (state or {}).get(WORLD_KEY)
    w = dict(DEFAULTS)
    if isinstance(raw, Mapping):
        w.update({k: v for k, v in raw.items() if k in DEFAULTS})
    for k in ("participants", "damage", "last_outcome", "yongji"):
        if not isinstance(w[k], dict):
            w[k] = {}
    if not isinstance(w["plane_log"], list):
        w["plane_log"] = []
    if not isinstance(w["active"], dict):
        w["active"] = None
    w["plateau_destroyed"] = w["plateau_destroyed"] is True
    for k in ("small_count", "big_count", "rewinds", "cycle_start", "defenders",
              "heaven_slash_until", "version"):
        w[k] = max(0, int(w[k] or 0))
    w["last_activity"] = float(w["last_activity"] or 0.0)
    return w


def set_world(state: dict, w: Mapping) -> None:
    # destroyed_view 是分发器塞进来的临时只读视图，不落库
    state[WORLD_KEY] = {k: v for k, v in w.items() if k in DEFAULTS}


def state_of(doc: Any) -> dict[str, Any]:
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get(EXT_KEY)
    if not isinstance(st, dict):
        st = {}
    st.setdefault("kills", 0)
    st.setdefault("dao_gain", 0)
    st.setdefault("deathlock_until", 0.0)
    st.setdefault("slash_count", 0)
    st.setdefault("last_fight", 0.0)
    st.setdefault("bubble", None)
    st.setdefault("reflection_revives", 0)
    ext[EXT_KEY] = st
    return st


# ---------------------------------------------------------------- 内部

def _ok(msg: str, ops: list | None = None) -> tuple[bool, str, dict, list]:
    return True, msg, {}, ops or []


def _no(msg: str) -> tuple[bool, str, dict, list]:
    return False, msg, {}, []


def _begin(w: dict, typ: str, years: int, now: float, stats: Any) -> tuple[str, list]:
    first = (w["small_count"] == 0) if typ == "small" else (w["big_count"] == 0)
    w["small_count" if typ == "small" else "big_count"] += 1
    w["active"] = {
        "type": typ, "first": bool(first), "start": int(years),
        "end": int(years) + ACTIVE_YEARS,
        "id": f"{typ}-{w['small_count' if typ == 'small' else 'big_count']}-{years}",
    }
    w["phase"] = typ
    if typ == "small":
        w["warned_small_due"] = None
        w["small_due"] = None
    else:
        w["warned_big_due"] = None
        w["big_due"] = None
    w["participants"], w["damage"], w["defenders"] = {}, {}, 0
    w["last_activity"] = now
    return (f"【诡异{'小祭' if typ == 'small' else '大祭'}·{w['active']['id']}】"
            "诡异族群与始祖自厄土高原降临。"
            f"发 #迎战诡异{'小祭' if typ == 'small' else '大祭'} 迎战。"), []


def _close(w: dict, years: int, now: float, defended: bool, rng: random.Random,
           reason: str) -> tuple[str, list]:
    """结算：不发奖励（原版新系统如此），守界失败才毁位面并记永寂名单。"""
    typ = (w["active"] or {}).get("type") or "small"
    first = bool((w.get("active") or {}).get("first"))
    participants = dict(w.get("participants") or {})
    ops: list = []
    note = f"【祭礼结算 · {reason}】"
    if not defended and typ == "big":
        victims = list(SACRIFICE_PLANES) if first else rng.sample(list(SACRIFICE_PLANES), k=2)
        for name in victims:
            ops.append(("mark", name, f"诡异大祭·{reason}"))
            if name not in w["plane_log"]:
                w["plane_log"].append(name)
        if first:
            note += "首轮大祭覆灭，现有位面界门尽闭，诸天坠入绝灵时代。"
        else:
            note += f"守界失利，{('、'.join(victims))} 崩灭，界门永闭；管理员可 #恢复诸天位面。"
    elif typ == "small" and first:
        note += "首轮小祭由荒天帝映照诸天；参战仙帝的身灭结果照常结算。"
    else:
        note += "守界功成，诸天位面安然。"
    w["active"] = None
    w["participants"], w["damage"], w["defenders"] = {}, {}, 0
    w["last_activity"] = now
    w["heaven_slash_until"] = max(int(w["heaven_slash_until"]), int(years) + HEAVEN_SLASH_YEARS)
    w["last_outcome"] = {"type": typ, "first": first, "defended": bool(defended), "at": now,
                         "reason": reason, "year": int(years)}
    ops.append(("settle_players", {
        "type": typ, "first": first, "defended": bool(defended),
        "destroyed": bool(w["plateau_destroyed"]), "participants": participants,
    }))
    if w["plateau_destroyed"]:
        w["phase"] = "destroyed"
        w["small_due"] = w["big_due"] = None
    elif typ == "small":
        w["phase"] = "dormant"
        w["big_due"] = int(years) + BIG_DELAY
        w["small_due"] = None
        note += f" 大祭将于世界年 {w['big_due']:,} 降临。"
    else:
        w["phase"] = "dormant"
        w["cycle_start"] = int(years)
        w["small_due"] = int(years) + SMALL_INTERVAL
        w["big_due"] = None
        note += f" 下一轮小祭将于世界年 {w['small_due']:,} 降临。"
    return note, ops


# ---------------------------------------------------------------- 惰性推进

def advance(w: dict, years: int, now: float, stats: Any,
            rng: random.Random | None = None,
            has_immortal_emperor: bool = False) -> tuple[list[str], list]:
    """每个祭礼指令入口先跑：按世界年自动开/结算 + 24h 无活动兜底关闭。"""
    rng = rng or random.Random()
    notes: list[str] = []
    ops: list = []
    years = max(0, int(years))
    if w["plateau_destroyed"] and w["phase"] != "destroyed":
        w["phase"], w["active"] = "destroyed", None
    act = w["active"]
    if isinstance(act, dict):
        if years >= int(act.get("end") or 0):
            n, o = _close(w, years, now, int(w["defenders"]) > 0, rng, "世界年到期")
            notes.append(n); ops += o
        elif now - float(w["last_activity"] or 0) > INACTIVE_SEC:
            n, o = _close(w, years, now, int(w["defenders"]) > 0, rng, "24h 无活动")
            notes.append(n); ops += o
        return notes, ops
    if w["phase"] == "destroyed":
        return notes, ops
    if int(w["small_count"]) > int(w["big_count"]):
        if w["big_due"] is None:
            w["big_due"] = years + BIG_DELAY
            w["warned_big_due"] = None
        due = int(w["big_due"])
        if years >= due:
            n, o = _begin(w, "big", years, now, stats)
            notes.append(n); ops += o
        elif due - years <= WARNING_YEARS and w.get("warned_big_due") != due:
            w["warned_big_due"] = due
            notes.append(f"【大祭万界·两千年预警】十口古棺同时震动，大祭将在世界年 {due:,} 降临。")
        return notes, ops

    regular_due = int(w["cycle_start"] or 0) + SMALL_INTERVAL
    if (int(w["small_count"]) == 0 and has_immortal_emperor
            and w.get("first_emperor") is None):
        w["first_emperor"] = years
    emperor_due = (int(w["first_emperor"]) + EMPEROR_WARNING_YEARS
                   if int(w["small_count"]) == 0 and w.get("first_emperor") is not None
                   else None)
    due = min(regular_due, emperor_due) if emperor_due is not None else regular_due
    w["small_due"] = due
    if years >= due:
        n, o = _begin(w, "small", years, now, stats)
        notes.append(n); ops += o
    elif due - years <= WARNING_YEARS and w.get("warned_small_due") != due:
        w["warned_small_due"] = due
        notes.append(f"【小祭万界·两千年预警】厄土高原黑雾翻涌，小祭将在世界年 {due:,} 降临。")
    return notes, ops


# ---------------------------------------------------------------- 指令函数

def open_event(w: dict, typ: str, years: int, now: float, stats: Any,
               is_admin: bool) -> tuple[bool, str, dict, list]:
    if not is_admin:
        return _no("开启祭礼唯管理员可执。")
    if w["plateau_destroyed"]:
        return _no("厄土高原已彻底覆灭，祭礼永不复启。需 #复苏厄土高原 回滚。")
    if isinstance(w["active"], dict):
        return _no(f"当前已有{'小祭' if w['active']['type'] == 'small' else '大祭'}进行中，"
                   f"可先 #结算诡异祭礼。")
    msg, ops = _begin(w, typ, years, now, stats)
    return _ok(msg, ops)


def settle(w: dict, years: int, now: float, is_admin: bool,
           rng: random.Random | None = None) -> tuple[bool, str, dict, list]:
    if not is_admin:
        return _no("结算祭礼唯管理员可执。")
    if not isinstance(w["active"], dict):
        return _no("当前没有进行中的祭礼。")
    msg, ops = _close(w, years, now, int(w["defenders"]) > 0,
                      rng or random.Random(), "管理员结算")
    return _ok(msg, ops)


def close_event(w: dict, typ: str, years: int, now: float, is_admin: bool,
                rng: random.Random | None = None) -> tuple[bool, str, dict, list]:
    if not is_admin:
        return _no("关闭祭礼唯管理员可执。")
    act = w["active"]
    if not isinstance(act, dict) or act.get("type") != typ:
        return _no(f"当前没有进行中的{'小祭' if typ == 'small' else '大祭'}。")
    msg, ops = _close(w, years, now, int(w["defenders"]) > 0,
                      rng or random.Random(), f"管理员关闭{'小祭' if typ == 'small' else '大祭'}")
    return _ok("已关闭。" + msg, ops)


def get_encounter(doc: Any, typ: str, first: bool = False) -> dict[str, Any]:
    """按原版权柄档选择真实敌方人数与属性倍率。"""
    tier = authority_mod.authority_21(doc)
    if typ == "small":
        if tier < GATE_SMALL:
            return {"allowed": False, "reason": "npc_front" if first else "realm",
                    "authority": tier, "first": first}
        return {"allowed": True, "enemy_type": "immortal_emperor",
                "enemy_count": SMALL_EMPEROR_COUNT, "stat_scale": 3, "first": first}
    if tier >= GATE_BIG:
        enemy_type, scale = "ancestor", 5
    elif tier >= GATE_SMALL:
        enemy_type, scale = "immortal_emperor", 3
    elif tier >= GATE_QUASI_EMPEROR:
        enemy_type, scale = "quasi_immortal_emperor", 2
    else:
        return {"allowed": False, "reason": "realm", "authority": tier, "first": first}
    return {"allowed": True, "enemy_type": enemy_type, "enemy_count": BIG_ENCOUNTER_COUNT,
            "stat_scale": scale, "first": first}


def _time_river_rows(names: list[str], corpse: bool = False) -> list[dict]:
    from .combat.time_river import attack_rows
    return [dict(row) for row in attack_rows(names, corpse=corpse) if isinstance(row, Mapping)]


def _npc_fighter(template: Any, name: str, scale: float = 1.5) -> Any:
    from .combat.engine import Fighter
    hp = max(1, int(template.hp_max * scale))
    skills = ["【仙帝】他化自在法"] if name == "荒天帝" else []
    return Fighter(
        name=name, atk=max(1, int(template.atk * scale)),
        defense=max(1, int(template.defense * scale)), hp=hp, hp_max=hp,
        speed=max(1, int(template.speed)), crit_damage=template.crit_damage,
        tags={"auth21": GATE_BIG if name in ("荒天帝", "叶天帝") else GATE_SMALL,
              "mijing_level": GATE_BIG if name in ("荒天帝", "叶天帝") else GATE_SMALL,
              "linggen_name": "诸天映照", "time_river_ally": True,
              "atk_skills": _time_river_rows(skills) if skills else []},
    )


def build_encounter_teams(doc: Any, challenger: Any, encounter: Mapping) -> tuple[list, list]:
    """构造原版定额阵容；人数有限，团队战延续插件的分轮引擎。"""
    from .combat.engine import Fighter
    if not encounter.get("allowed"):
        return [], []
    scale = max(1, int(encounter.get("stat_scale", 1)))
    kind = str(encounter.get("enemy_type") or "immortal_emperor")
    if kind == "ancestor":
        names = ANCESTOR_NAMES
        level, emperor = GATE_BIG, True
    elif kind == "quasi_immortal_emperor":
        names = tuple(f"诡异道祖·{index}" for index in range(1, 201))
        level, emperor = GATE_QUASI_EMPEROR, False
    else:
        names = tuple(f"厄土仙帝·{index}" for index in range(1, 31))
        level, emperor = GATE_SMALL, True
    special_names = ["祭天祭地祭英灵", "帝威卸甲", "祭灭万物"]
    enemies = []
    for index, name in enumerate(names[:int(encounter.get("enemy_count", 0))], 1):
        hp = max(1, int(challenger.hp_max * scale))
        enemies.append(Fighter(
            name=name, atk=max(1, int(challenger.atk * scale)),
            defense=max(1, int(challenger.defense * scale)), hp=hp, hp_max=hp,
            bao=0.35, speed=ENEMY_SPEED,
            tags={"auth21": level, "mijing_level": level, "boss": True,
                  "immortal_emperor": emperor, "time_river_identity": "尸骸仙帝",
                  "time_river_counter": True, "time_river_no_treasure": True,
                  "time_river_no_soul_revival": True, "linggen_name": "诡异本源",
                  "atk_skills": _time_river_rows(special_names, corpse=True)},
        ))
    allies = []
    if encounter.get("first") and encounter.get("enemy_type") == "ancestor":
        allies = [_npc_fighter(challenger, name, 2) for name in ("荒天帝", "叶天帝")]
    elif encounter.get("first") and encounter.get("enemy_type") == "immortal_emperor" and encounter.get("enemy_count") == BIG_ENCOUNTER_COUNT:
        allies = [_npc_fighter(challenger, name) for name in FIRST_EMPEROR_ALLIES]
    return [challenger, *allies], enemies


def _route_of(doc: Any) -> str:
    ext = getattr(doc, "ext", {}) or {}
    chosen = str(ext.get("extra_track") or ext.get("cultivation_path") or "")
    if chosen in ("mijing", "xiangu", "huafen"):
        return chosen
    table = str(getattr(doc, "realm_table", ""))
    if "花粉" in table:
        return "huafen"
    if "仙古" in table:
        return "xiangu"
    try:
        from . import flower
        st = flower.state_of(doc)
        if st and int(st.get("level", 1) or 1) > 1 and flower.equivalent_level(doc) >= authority_mod.authority_21(doc):
            return "huafen"
    except (AttributeError, TypeError, ValueError):
        pass
    return "mijing"


def _transcended(doc: Any) -> bool:
    bubble = state_of(doc).get("bubble")
    return isinstance(bubble, Mapping) and bubble.get("status") == "transcended"


def _player_tier(doc: Any) -> int:
    return GATE_FINALE if _transcended(doc) else authority_mod.authority_21(doc)


def apply_strange_sacrifice_victory(doc: Any, encounter: Mapping, killed_count: int) -> dict[str, int]:
    killed = max(0, int(killed_count))
    emperor_kills = 0 if encounter.get("enemy_type") == "quasi_immortal_emperor" else killed
    st = state_of(doc)
    st["kills"] = int(st.get("kills") or 0) + emperor_kills
    st["dao_gain"] = int(st.get("dao_gain") or 0) + emperor_kills
    doc.ext["厄土仙帝击杀数"] = int(doc.ext.get("厄土仙帝击杀数") or 0) + emperor_kills
    doc.ext["仙帝道行精进"] = int(doc.ext.get("仙帝道行精进") or 0) + emperor_kills
    return {"killed": killed, "emperor_kills": emperor_kills,
            "total_emperor_kills": int(doc.ext["厄土仙帝击杀数"])}


def resolve_highland_finale(w: dict, doc: Any, years: int, now: float,
                            rng: random.Random) -> tuple[bool, str, list]:
    if _player_tier(doc) < GATE_FINALE:
        w["rewinds"] = int(w.get("rewinds") or 0) + 1
        w["last_outcome"] = {"reason": "高原意志回溯", "at": now, "year": int(years)}
        return False, "【覆灭回溯】高原意志令十大始祖与诡异族群复归；本次击杀与守界结果未落定。", []
    w["plateau_destroyed"] = True
    w["plateau_destroyed_at"] = now
    w["plateau_destroyed_by"] = str(getattr(doc, "uid", "") or getattr(doc, "name", ""))
    w["phase"] = "destroyed"
    w["plane_log"].append(HIGHLAND)
    ops = [("mark", HIGHLAND, "始祖彻底永祭（永久）")]
    note, extra = _close(w, years, now, True, rng, "始祖彻底永祭")
    return True, "【高原永灭】祭道之上的意志彻底摧毁厄土本源。\n" + note, ops + extra


def _rewrite_with_eternal_map(doc: Any, now: float) -> bool:
    from . import xtzb, yuanshen
    if xtzb.current(doc, now) != "永恒仙图":
        return False
    st = xtzb.state_of(doc, now)
    if float(st["cd"].get("永恒改命", 0) or 0) > now:
        return False
    st["cd"]["永恒改命"] = now + ETERNAL_REWRITE_SECONDS
    history = list(st.get("history") or [])
    history.append({"reason": "诡异祭礼身灭道消", "state": "rewritten", "at": now})
    st["history"] = history[-10:]
    xtzb.save(doc, st)
    spirit = yuanshen.ensure(doc)
    spirit["cur"] = max(1, int(spirit.get("cur") or 0))
    spirit["max"] = max(1, int(spirit.get("max") or 1))
    yuanshen.save(doc, spirit)
    doc.ext["hp"] = max(1, int(doc.ext.get("hp") or 1))
    doc.state = "空闲"
    doc.ext["sacrifice_fate_rewritten"] = now
    return True


def apply_strange_sacrifice_defeat(doc: Any, now: float, rng: random.Random,
                                   enemy_type: str) -> dict[str, Any]:
    """身灭只改玩家文档状态和安全世界线记录，不删档、不触碰备份。"""
    from . import worldline
    try:
        from . import suiyun
        if bool(suiyun.effects(doc).get("absoluteSpiritImmune")):
            return {"protected": True, "destroyed_lines": []}
    except (AttributeError, TypeError, ValueError):
        pass
    if _rewrite_with_eternal_map(doc, now):
        return {"rewritten": True, "destroyed_lines": []}
    if enemy_type == "ancestor" and _player_tier(doc) == GATE_BIG:
        st = state_of(doc)
        bubble = st.get("bubble")
        if not isinstance(bubble, Mapping) or bubble.get("status") != "bubble":
            st["bubble"] = {"status": "bubble", "source": "始祖彻底永祭",
                             "route": _route_of(doc), "started_at": now,
                             "ready_at": now + BUBBLE_SECONDS}
        doc.ext["hp"] = 0
        doc.state = "空间泡影"
        return {"bubble": True, "destroyed_lines": []}
    count = REWIND_LINE_COUNT + rng.randrange(REWIND_LINE_EXTRA_COUNT)
    line_ids = rng.sample([line[0] for line in worldline.LINES], count)
    timeline = worldline.state_of(doc)
    destroyed = list(timeline.get("destroyed") or [])
    history = list(timeline.get("history") or [])
    tier = _player_tier(doc)
    for line_id in line_ids:
        if line_id not in destroyed:
            destroyed.append(line_id)
        history.append({"type": "时间线毁灭", "line": line_id, "at": now,
                        "source": "诡异祭礼·厄土仙帝围猎"})
    timeline["destroyed"] = destroyed[-len(worldline.LINES):]
    timeline["history"] = history[-worldline.MAX_HISTORY:]
    if tier == GATE_QUASI_EMPEROR:
        doc.ext["dao_flaw"] = int(doc.ext.get("dao_flaw") or 0) + 1
        doc.ext["ancient_wound"] = int(doc.ext.get("ancient_wound") or 0) + 1
    elif tier < GATE_QUASI_EMPEROR:
        doc.ext["ancient_wound"] = int(doc.ext.get("ancient_wound") or 0) + 1
    st = state_of(doc)
    st["deathlock_until"] = now + DEATHLOCK_SEC
    st["slash_count"] = int(st.get("slash_count") or 0) + 1
    doc.ext["hp"] = 0
    doc.state = "身灭道消"
    doc.ext["sacrifice_status"] = "身灭道消·过去时间线崩灭"
    return {"destroyed_lines": line_ids, "deathlock_until": st["deathlock_until"]}


def interaction_lock(doc: Any, now: float, hp_max: int = 1) -> str | None:
    st = state_of(doc)
    bubble = st.get("bubble")
    if isinstance(bubble, Mapping) and bubble.get("status") == "bubble":
        left = max(0, int(float(bubble.get("ready_at") or 0) - now))
        if left:
            return f"【始祖永祭】空间泡影尚需 {((left + 3599) // 3600)} 小时；届时发送 #挣脱空间泡影。"
        return "【始祖永祭】720 分钟已满，发送 #挣脱空间泡影即可挣脱。"
    until = float(st.get("deathlock_until") or 0)
    if until > now:
        return f"【身灭道消】过去时间线尚未重聚，{int((until - now) // 3600) + 1} 小时内不可交互。"
    if st.get("deathlock_until"):
        st["deathlock_until"] = 0.0
        doc.state = "空闲"
        doc.ext["hp"] = max(1, int(hp_max) // 10)
        doc.ext["sacrifice_status"] = "真血重聚"
    return None


def escape_bubble(doc: Any, now: float, hp_max: int) -> tuple[bool, str]:
    st = state_of(doc)
    bubble = st.get("bubble")
    if not isinstance(bubble, dict) or bubble.get("status") != "bubble":
        return False, "你尚未陷入空间泡影。"
    ready = max(float(bubble.get("ready_at") or 0), float(bubble.get("started_at") or 0) + BUBBLE_SECONDS)
    if now < ready:
        return False, f"泡影尚未解脱，还需 {int(ready - now) // 60} 分钟。"
    bubble.update({"status": "transcended", "completed_at": now})
    st["deathlock_until"] = 0.0
    doc.state = "空闲"
    doc.ext["hp"] = max(1, int(hp_max))
    doc.ext["sacrifice_status"] = "祭道之上·超脱一切"
    return True, "【泡影挣脱】你踏入祭道之上，真身与道果重归现世。"


def settle_player(doc: Any, outcome: Mapping[str, Any], now: float,
                  rng: random.Random) -> tuple[bool, str]:
    """祭礼落幕阶段的玩家胜败结算；调用方只在 changed 时保存玩家档。"""
    typ = str(outcome.get("type") or "small")
    first = bool(outcome.get("first"))
    destroyed = bool(outcome.get("destroyed"))
    participants = outcome.get("participants") if isinstance(outcome.get("participants"), Mapping) else {}
    tier = _player_tier(doc)
    uid = str(getattr(doc, "uid", ""))
    row = participants.get(uid)
    doomed = not destroyed and not (typ == "small" and first) and (
        (typ == "big" and first) or not outcome.get("defended"))
    if typ == "small" and first and tier < GATE_SMALL:
        st = state_of(doc)
        st["reflection_revives"] = int(st.get("reflection_revives") or 0) + 1
        doc.ext["sacrifice_reflection_revives"] = int(doc.ext.get("sacrifice_reflection_revives") or 0) + 1
        return True, "荒天帝映照诸天，你获得一次映照复生记录。"
    threshold = GATE_SMALL if typ == "small" else GATE_QUASI_EMPEROR
    if tier < threshold or row or destroyed or interaction_lock(doc, now):
        return False, ""
    if not doomed:
        return False, ""
    enemy_type = "ancestor" if typ == "big" and tier == GATE_BIG else ""
    result = apply_strange_sacrifice_defeat(doc, now, rng, enemy_type)
    return True, ("永恒仙图改写了身灭道消。" if result.get("rewritten") else
                  "你被始祖永祭，坠入空间泡影。" if result.get("bubble") else
                  f"身灭道消：{len(result.get('destroyed_lines') or [])} 条过去时间线崩灭；24 小时内交互封锁。")


def fight(w: dict, doc: Any, stats: Any, years: int, now: float, rng: random.Random,
          typ: str, fighter: Any = None) -> tuple[bool, str, dict, list]:
    """原版人数 / 敌我阵容 / 技能反制与胜败结算，接现有团队战引擎。"""
    from .combat.engine import Fighter, run_team_battle
    st = state_of(doc)
    active = w.get("active")
    if not isinstance(active, dict):
        return _no("当前没有进行中的祭礼，等待世界年推进或管理员开启。")
    if active.get("type") != typ:
        return _no(f"当前是【诡异{'小祭' if active.get('type') == 'small' else '大祭'}】，请迎战对应祭礼。")
    lock = interaction_lock(doc, now, max(1, int(getattr(stats, "hp", 1) or 1)))
    if lock:
        return _no(lock)
    if w["plateau_destroyed"]:
        return _no("厄土高原与诡异族群已被彻底摧毁。")
    if now - float(st.get("last_fight") or 0) < FIGHT_CD_SEC:
        return _no(f"迎战调息中，{FIGHT_CD_SEC} 秒后再战。")
    encounter = get_encounter(doc, typ, bool(active.get("first")))
    if not encounter["allowed"]:
        if encounter.get("reason") == "npc_front":
            return _no("你尚未踏入仙帝领域，此刻由荒天帝、仙帝柳神与追随者挡在最前方。")
        required = GATE_SMALL if typ == "small" else GATE_QUASI_EMPEROR
        return _no(f"迎战诡异{'小祭' if typ == 'small' else '大祭'}需权柄 {required}/21（当前 {encounter['authority']}/21）。")
    uid = str(doc.uid)
    previous = w["participants"].get(uid)
    if isinstance(previous, Mapping) and previous.get("result") in ("win", "loss"):
        return _no("本轮祭礼你已留下战斗结果，待下轮再战。")
    if fighter is None:
        hpmax = max(1, int(getattr(stats, "hp", 1) or 1))
        fighter = Fighter(name=getattr(doc, "name", "") or "道友",
                          atk=max(1, int(getattr(stats, "atk", 1) or 1)),
                          defense=max(1, int(getattr(stats, "defense", 1) or 1)),
                          hp=min(hpmax, max(1, int(getattr(doc, "ext", {}).get("hp", hpmax) or hpmax))),
                          hp_max=hpmax, bao=float(getattr(stats, "bao", 0) or 0),
                          speed=max(1, int(getattr(stats, "speed", 100) or 100)))
    fighter.hp_max = max(1, int(fighter.hp_max))
    fighter.hp = min(fighter.hp_max, max(1, int(fighter.hp)))
    fighter.tags["time_river_counter"] = True
    opening_log = [f"【{'五帝围猎' if typ == 'small' else '大祭决战'}】敌军速度固定为 {ENEMY_SPEED}。"]
    from .combat.time_river import apply_counter_opening
    opening_log.extend(apply_counter_opening(fighter, "尸骸仙帝", full=True))
    a_team, b_team = build_encounter_teams(doc, fighter, encounter)
    battle = run_team_battle(a_team, b_team, rng, opening_log=opening_log, timeout_draw=True)
    challenger_alive = fighter.hp > 0
    won = challenger_alive and battle.b_hp <= 0
    killed = sum(1 for enemy in b_team if enemy.hp <= 0 and enemy.tags.get("immortal_emperor"))
    damage = int(battle.damage_by_side[0])
    st["last_fight"] = now
    w["last_activity"] = now
    finale_destroyed = False
    ops: list = []
    if won and encounter["enemy_type"] == "ancestor":
        finale_destroyed, finale_text, finale_ops = resolve_highland_finale(w, doc, years, now, rng)
        ops.extend(finale_ops)
        if not finale_destroyed:
            w["participants"] = {}
            w["damage"] = {}
            w["defenders"] = 0
            w["last_activity"] = now
            w["active"] = dict(active)
            conclusion = "【覆灭回溯】" + finale_text + " 本次击杀收益与守界成功不落定，可再次迎战。"
            w["participants"][uid] = {"result": "rewound", "killed": 0, "at": now}
            return _ok("\n".join([*battle.log[-20:], conclusion]), ops)
        w["participants"][uid] = {"result": "win", "killed": killed, "at": now}
        doc.ext["hp"] = min(fighter.hp_max, fighter.hp)
        progress = apply_strange_sacrifice_victory(doc, encounter, killed)
        conclusion = finale_text
        ops.extend([("mark", HIGHLAND, "始祖彻底永祭（永久）")])
        save_text = f"仙帝级击杀 {progress['emperor_kills']}，累计 {progress['total_emperor_kills']}/10。"
        conclusion += "\n" + save_text
        return _ok("\n".join([*battle.log[-20:], conclusion]), ops)
    if won:
        doc.ext["hp"] = min(fighter.hp_max, fighter.hp)
        progress = apply_strange_sacrifice_victory(doc, encounter, killed)
        w["participants"][uid] = {"result": "win", "killed": killed, "at": now}
        w["defenders"] = int(w["defenders"]) + 1
        w["damage"][uid] = int(w["damage"].get(uid) or 0) + max(0, damage)
        conclusion = (f"【守界成功】击溃 {len(b_team)} 名敌军，斩杀 {progress['emperor_kills']} 位仙帝级强者；"
                     f"累计仙帝击杀 {progress['total_emperor_kills']}/10。"
                     f"守界者 {w['defenders']} 人，实战伤害 {damage:,}。")
    else:
        defeat = apply_strange_sacrifice_defeat(doc, now, rng, encounter["enemy_type"])
        w["participants"][uid] = {"result": "loss", "killed": killed, "at": now}
        w["damage"][uid] = int(w["damage"].get(uid) or 0) + max(0, damage)
        if defeat.get("bubble"):
            conclusion = f"【始祖永祭】{doc.name or uid} 被始祖彻底永祭，进入现实时间 {BUBBLE_SECONDS // 60} 分钟的空间泡影。"
        elif defeat.get("rewritten"):
            conclusion = "【永恒改命】永恒仙图改写了身灭道消，保留了真身。"
        else:
            conclusion = (f"【身灭道消】{len(defeat.get('destroyed_lines') or [])} 条过去时间线崩灭，"
                          f"24 小时交互封锁；仙帝级击杀不结算。")
    return _ok("\n".join([*battle.log[-20:], conclusion]), ops)


def restore_highland(w: dict, years: int, now: float,
                     is_admin: bool) -> tuple[bool, str, dict, list]:
    """唯一解除永久覆灭的回滚：三重标记同清（原版分三个文件，本移植同一 state）。"""
    if not is_admin:
        return _no("复苏高原唯管理员可执。")
    if not w["plateau_destroyed"]:
        return _no("厄土高原未被彻底覆灭，无需复苏。")
    ops = [("clear", HIGHLAND)]
    for name in list(w["plane_log"]):
        if name != HIGHLAND:
            ops.append(("clear", name))
    w.update({
        "plateau_destroyed": False, "phase": "dormant", "active": None,
        "participants": {}, "damage": {}, "defenders": 0, "plane_log": [],
        "yongji": {}, "last_activity": now, "cycle_start": int(years),
        "small_due": int(years) + SMALL_INTERVAL, "big_due": None,
        "heaven_slash_until": 0, "last_outcome": {"reason": "管理员复苏", "at": now},
    })
    return _ok(f"【复苏厄土高原】三重永久标记已同清，祭礼纪年重置。"
               f"下一轮小祭世界年 {w['small_due']:,}。", ops)


def repair_all(w: dict, is_admin: bool) -> tuple[bool, str, dict, list]:
    if not is_admin:
        return _no("恢复诸天位面唯群主或修仙管理员可执。")
    names = list(w["plane_log"])
    ops = [("clear", n) for n in names if n != HIGHLAND or not w["plateau_destroyed"]]
    ops.append(("clear_all",))       # W7-5b 其它来源的毁灭记录也一并修复
    n = len(w["yongji"])
    w["plane_log"] = []
    w["yongji"] = {}
    return _ok(f"【恢复诸天位面】{len(names)} 处祭礼创伤与全部界门毁灭记录已修复，"
               f"永寂名单 {n} 人归位。", ops)


def record_yongji(w: dict, players: list[tuple[str, str, str, int]], now: float) -> int:
    """位面被毁时登记名单（不删档、不传送）。players: (uid, name, current_plane, tier)。"""
    dead = set(w["plane_log"])
    n = 0
    for uid, name, plane, tier in players:
        if plane in dead and tier < GATE_YONGJI and uid not in w["yongji"]:
            w["yongji"][uid] = {"name": name, "plane": plane, "at": now}
            n += 1
    return n


# ---------------------------------------------------------------- 面板

def status_text(w: dict, years: int) -> str:
    act = w["active"]
    lines = [f"【诡异祭礼状态】世界年 {int(years):,}",
             f"阶段：{ {'dormant': '沉寂', 'small': '小祭进行中', 'big': '大祭进行中', 'destroyed': '高原永灭'}.get(w['phase'], w['phase'])}",
             f"累计：小祭 {w['small_count']} 轮 / 大祭 {w['big_count']} 轮 / 因果回溯 {w['rewinds']} 次",
             f"高原：{'彻底覆灭（不可逆，需 #复苏厄土高原）' if w['plateau_destroyed'] else '尚存'}"]
    if isinstance(act, dict):
        lines += [f"本场：{act['id']}　参战 {len(w['participants'])} 人　守界成功 {w['defenders']} 人",
                  f"世界年 {act['start']:,} → {act['end']:,}（到期自动结算）",
                  f"累计实战伤害 {sum(int(value or 0) for value in w['damage'].values()):,}"]
    else:
        due = w["big_due"] if w["big_due"] is not None else w["small_due"]
        lines.append(f"下轮：{'大祭' if w['big_due'] is not None else '小祭'} 世界年 {int(due or 0):,}")
    destruction = w.get("destruction_view")
    if isinstance(destruction, Mapping) and destruction.get("active"):
        protected = list((destruction.get("protected_planes") or {}).keys())
        if destruction.get("first_round_pending"):
            lines.append("自动位面毁灭：首轮待触发（10 秒）")
        else:
            next_year = int(destruction.get("next_world_year", 0) or 0)
            lines.append(f"自动位面毁灭：下轮世界年 {next_year:,}；"
                         f"本场救场 {'已用' if destruction.get('rescue_used') else '可用'}；"
                         f"护持 {'、'.join(protected) if protected else '无'}")
    lines.append(f"天意一刀：{'生效至世界年 ' + format(int(w['heaven_slash_until']), ',') if int(w['heaven_slash_until']) > int(years) else '未生效'}")
    return "\n".join(lines)


def ancestor_text(w: dict) -> str:
    act = w["active"]
    if not isinstance(act, dict):
        return "【诡异始祖状态】始祖沉眠，未开启祭礼。" if not w["plateau_destroyed"] else "【诡异始祖状态】厄土高原已彻底覆灭，始祖永不复生。"
    leaders = sorted(w.get("damage", {}).items(), key=lambda row: -int(row[1] or 0))[:3]
    contribution = "、".join(f"{uid} {int(damage):,}" for uid, damage in leaders) or "暂无"
    return (f"【诡异始祖状态】{act['id']}\n"
            f"{ '首轮' if act.get('first') else '后续轮次'}　成功守界 {w['defenders']} 人\n"
            f"实战伤害榜：{contribution}")


def rank_text(w: dict) -> str:
    rows = sorted(w["damage"].items(), key=lambda kv: -int(kv[1] or 0))[:20]
    if not rows:
        return "【扫平厄土高原贡献榜】本轮尚无实战伤害。"
    total = max(1, sum(int(v or 0) for _, v in w["damage"].items()))
    out = ["【扫平厄土高原贡献榜】按团队战实际造成伤害统计"]
    for i, (uid, damage) in enumerate(rows, 1):
        share = int(damage) * 100 // total
        out.append(f"{i:>2}. {uid}　伤害 {int(damage):,}（{share}%）")
    return "\n".join(out)


def slash_text(w: dict, doc: Any, years: int, now: float) -> str:
    st = state_of(doc)
    left_y = int(w["heaven_slash_until"]) - int(years)
    left_m = max(0, int(float(st.get("deathlock_until") or 0) - now) // 60)
    return (f"【天意一刀状态】\n"
            f"诸天期限：{'尚余 ' + format(max(0, left_y), ',') + ' 世界年' if left_y > 0 else '已过'}\n"
            f"你被斩道 {int(st.get('slash_count') or 0)} 次　"
            f"身灭道消：{'余 ' + str(left_m) + ' 分钟' if left_m else '无'}\n"
            f"斩道期间迎战门槛不变，但身灭道消 24h 内不可再战。")


def planes_text(w: dict) -> str:
    rows = w.get("destroyed_view") or {}
    lines = [f"【位面毁灭状态】界门永闭 {len(rows)} 处"]
    for name, row in list(rows.items())[:20]:
        src = row.get("source", "未知") if isinstance(row, Mapping) else "未知"
        lines.append(f"· {name}　来源：{src}")
    lines.append(f"祭礼创伤记录：{'、'.join(w['plane_log']) or '无'}")
    lines.append(f"高原永久覆灭：{'是' if w['plateau_destroyed'] else '否'}"
                 f"（普通 #恢复诸天位面 无法解除，须 #复苏厄土高原）")
    return "\n".join(lines)


def yongji_text(w: dict) -> str:
    rows = w["yongji"]
    if not rows:
        return "【永寂名单】空。本移植只登记、不删档；#恢复诸天位面 时归位。"
    lines = [f"【永寂名单】{len(rows)} 人"]
    for uid, row in list(rows.items())[:20]:
        lines.append(f"· {row.get('name') or uid}（{uid}）　{row.get('plane')}")
    return "\n".join(lines)


def help_text() -> str:
    return "\n".join([
        "【诡异大祭 · 指令一览】",
        "#诡异大祭帮助 / #诡异大祭规则　全部指令 / 数值口径",
        "#诡异祭礼状态（别名 #诡异始祖状态）　纪年与本场进度",
        "#天意一刀状态　个人被斩次数与身灭道消倒计时",
        "#迎战诡异小祭 / #迎战诡异大祭（别名 #迎战厄土高原）",
        "管理员：#开启诡异小祭万界 / #开启诡异大祭万界",
        "管理员：#关闭诡异小祭万界 / #关闭诡异大祭万界 / #结算诡异祭礼",
        "#救场黑暗动乱（权柄16+，黑暗动乱与大祭毁灭时钟同时活动时可用一次）",
        "#扫平厄土高原贡献榜 / #位面毁灭状态 / #永寂名单",
        "群主/修仙管理员：#恢复诸天位面（修复界门） / #复苏厄土高原（唯一解除永久覆灭）",
    ])


def rules_text() -> str:
    return "\n".join([
        "【诡异大祭 · 规则】",
        f"1. 世界年周期：小祭每 {SMALL_INTERVAL:,} 年、大祭滞后 {BIG_DELAY:,} 年，"
        f"每场持续 {ACTIVE_YEARS:,} 世界年；本移植纪年按原版 ÷10。",
        "2. 小祭：权柄 18/21 起独战 5 位仙帝，敌方攻、防、生命为玩家基值 ×3。",
        "3. 大祭：权柄 17/21 起迎战 10 名敌军；准仙帝战道祖军（×2），仙帝战仙帝军（×3），"
        "祭道战十大始祖（×5）。17 为本移植沿用相邻仙帝门槛，为原版权柄 20 准仙帝留出一档。",
        "4. 首轮大祭按对阵带援军：祭道对始祖由荒天帝、叶天帝以 ×2 属性助战；仙帝对仙帝由狠人、"
        "无始残尸、柳神与叶倾仙虚影以 ×1.5 属性助战。其它轮次没有这批 NPC 援军。",
        f"5. 尸骸仙帝的原版技能与反制由时间长河战斗规则处理；敌军固定速度 {ENEMY_SPEED}。"
        "击杀数、守界结果和贡献伤害来自实际团队战；准仙帝击杀不计仙帝道行。",
        f"6. 击溃敌军且挑战者存活才算守界成功；本轮至少一名守界者成功，诸天免于大祭摧毁。"
        f"全灭始祖后，权柄 {GATE_FINALE}/21 可永久覆灭高原，否则回溯、始祖复归且战绩不落定。",
        f"7. 战败会按原版随机摧毁 {REWIND_LINE_COUNT}—{REWIND_LINE_COUNT + REWIND_LINE_EXTRA_COUNT - 1} 条时间线，"
        f"并进入 {DEATHLOCK_SEC // 3600} 小时交互封锁；永恒仙图可按其 {ETERNAL_REWRITE_SECONDS // 86400} 天冷却改命。"
        f"祭道强者遭始祖永祭会进入 {BUBBLE_SECONDS // 60} 分钟空间泡影，之后可挣脱晋入祭道之上。",
        "8. 玩家档与备份文件始终保留；时间线创伤只记入本角色的现有安全状态。",
        "9. 祭礼时间到期或管理员结算时，若大祭首轮或无人成功守界，按原版结局处理；"
        "首轮小祭由荒天帝映照复生低境界角色。",
        "10. 大祭 Boss 活动启动 10 秒后触发首轮位面毁灭，此后每 2,000 世界年最多随机封闭 2 个目标；每场黑暗动乱仅可通过 #救场黑暗动乱 护持 1 个未毁位面。",
    ])
