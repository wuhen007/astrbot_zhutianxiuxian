"""W8-D3 诡异大祭 / 厄土高原 / 位面毁灭 / 永寂名单（纯函数 + 惰性 tick，无 cron）。

取证：apps/Boss/StrangeSacrifice.js(796) + BOSS3.js(2086) + YongJiList.js(458)
      + model/strangeSacrifice.js(725) + model/planeDestruction.js(269)。
原版两套系统并存且 3 条指令重叠，本移植只取「新系统流程 + 旧系统位面后果」。

shortcut（与原版差异，写清楚便于以后升级）：
1. 无 cron：自动开祭/到期结算挂在每条祭礼指令入口的 advance()；24h 无活动兜底关闭。
2. 世界年周期按本移植 era 量级 ÷10（原版 40 万/10 万 → 4 万/1 万；era 每次推进 1000 年）。
3. 原版权柄 21/22/23 三档在本移植 authority_21(0-21) 折算为 18/19/21。
4. 原版 zd_battle 多回合 5 帝/10 始祖 → 本移植 battle.spar_full 镜像战 + 累计伤害贡献榜，
   不新增 run_raid（那是 D4）。
5. 原版位面毁灭会删玩家主档并送进 Redis 永寂名单；本移植只记名单、不删档、不传送，
   #恢复诸天位面 时清空。被毁位面本身由 W7-5b 的 destroyed_planes 封闭界门（真消费者）。
6. 天意一刀原版回退境界进阶（侵入渡劫流程），本移植折算为 24h 身灭道消 + 迎战门槛，
   由 ext["sacrifice"]["deathlock_until"] 消费，不留无消费者的全服死字段。
7. 原版空间泡影 720min 超脱 / 绝灵寿元压制 / FileRollbackTransaction 双文件事务未搬。
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
ACTIVE_YEARS = 2_000             # 原版同值
HEAVEN_SLASH_YEARS = 3_000       # 原版 3 万，本移植 ÷10
DEATHLOCK_SEC = 86_400           # 24h，毫秒口径原版 86400000
INACTIVE_SEC = 86_400            # 24h 无活动自动关闭
FIGHT_CD_SEC = 300               # 5 分钟

GATE_SMALL = 18                  # authority_21 档；原版 21 仙帝
GATE_BIG = 19                    # 原版 22 祭道
GATE_FINALE = 21                 # 原版 23 祭道之上（本移植满档）
GATE_YONGJI = 16                 # 低于此档且在被毁位面 → 记入永寂名单

HIGHLAND = "厄土高原"
# 可毁位面：不含「凡间」（默认位面，毁掉会卡死全部旅行）与高维位面
SACRIFICE_PLANES = ("下界八域", "遮天位面", "九天十地", "界海", "太初星墟")

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "phase": "dormant",              # dormant / small / big / destroyed
    "plateau_destroyed": False,      # 三重永久标记之①（本移植另两处见 plane ops）
    "small_count": 0,
    "big_count": 0,
    "rewinds": 0,
    "cycle_start": 0,
    "first_emperor": None,            # 首位权柄达标者出现的世界年
    "small_due": None,
    "big_due": None,
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
    scale = 120 if typ == "big" else 48
    hpmax = max(500_000, int(int(getattr(stats, "atk", 0) or 0) * scale))
    w["active"] = {
        "type": typ, "first": bool(first), "start": int(years),
        "end": int(years) + ACTIVE_YEARS,
        "id": f"{typ}-{w['small_count' if typ == 'small' else 'big_count']}-{years}",
        "hp": hpmax, "hpmax": hpmax, "reward": 30_000_000 if typ == "big" else 15_000_000,
    }
    w["phase"] = typ
    w["participants"], w["damage"], w["defenders"] = {}, {}, 0
    w["last_activity"] = now
    return (f"【诡异{'小祭' if typ == 'small' else '大祭'}·{w['active']['id']}】"
            f"诸天震颤，始祖自厄土高原苏醒（本源 {hpmax:,}）。"
            f"发 #迎战诡异{'小祭' if typ == 'small' else '大祭'} 迎战。"), []


def _close(w: dict, years: int, now: float, defended: bool, rng: random.Random,
           reason: str) -> tuple[str, list]:
    """结算：不发奖励（原版新系统如此），守界失败才毁位面并记永寂名单。"""
    typ = (w["active"] or {}).get("type") or "small"
    ops: list = []
    note = f"【祭礼结算 · {reason}】"
    if not defended and typ == "big":
        victims = rng.sample(list(SACRIFICE_PLANES), k=2)
        for name in victims:
            ops.append(("mark", name, f"诡异大祭·{reason}"))
            w["plane_log"].append(name)
        note += f"守界失利，{('、'.join(victims))} 崩灭，界门永闭；管理员可 #恢复诸天位面。"
    else:
        note += "守界功成，诸天位面安然。"
    w["active"] = None
    w["participants"], w["damage"], w["defenders"] = {}, {}, 0
    w["last_activity"] = now
    w["heaven_slash_until"] = max(int(w["heaven_slash_until"]), int(years) + HEAVEN_SLASH_YEARS)
    w["last_outcome"] = {"type": typ, "defended": bool(defended), "at": now,
                         "reason": reason, "year": int(years)}
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
            rng: random.Random | None = None) -> tuple[list[str], list]:
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
            n, o = _close(w, years, now, int(w["defenders"]) >= 3, rng, "世界年到期")
            notes.append(n); ops += o
        elif now - float(w["last_activity"] or 0) > INACTIVE_SEC:
            n, o = _close(w, years, now, int(w["defenders"]) >= 3, rng, "24h 无活动")
            notes.append(n); ops += o
        return notes, ops
    if w["phase"] == "destroyed":
        return notes, ops
    if w["small_due"] is None and w["big_due"] is None:
        w["small_due"] = int(w["cycle_start"] or 0) + SMALL_INTERVAL
    if w["big_due"] is not None and years >= int(w["big_due"]):
        n, o = _begin(w, "big", years, now, stats)
        notes.append(n); ops += o
    elif w["small_due"] is not None and years >= int(w["small_due"]):
        n, o = _begin(w, "small", years, now, stats)
        notes.append(n); ops += o
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
    msg, ops = _close(w, years, now, int(w["defenders"]) >= 3,
                      rng or random.Random(), "管理员结算")
    return _ok(msg, ops)


def close_event(w: dict, typ: str, years: int, now: float, is_admin: bool,
                rng: random.Random | None = None) -> tuple[bool, str, dict, list]:
    if not is_admin:
        return _no("关闭祭礼唯管理员可执。")
    act = w["active"]
    if not isinstance(act, dict) or act.get("type") != typ:
        return _no(f"当前没有进行中的{'小祭' if typ == 'small' else '大祭'}。")
    msg, ops = _close(w, years, now, int(w["defenders"]) >= 3,
                      rng or random.Random(), f"管理员关闭{'小祭' if typ == 'small' else '大祭'}")
    return _ok("已关闭。" + msg, ops)


def fight(w: dict, doc: Any, stats: Any, years: int, now: float, rng: random.Random,
          typ: str) -> tuple[bool, str, dict, list]:
    """镜像战 + 累计贡献。原版 5 帝/10 始祖折算为一个 statScale 3/5 的始祖镜像。"""
    from . import battle as battle_mod

    st = state_of(doc)
    act = w["active"]
    if not isinstance(act, dict):
        return _no("当前没有进行中的祭礼，等待世界年推进或管理员开启。")
    if act.get("type") != typ:
        cur = "小祭" if act.get("type") == "small" else "大祭"
        return _no(f"当前是【诡异{cur}】，请发 #迎战诡异{cur}。")
    if float(st.get("deathlock_until") or 0) > now:
        left = int(float(st["deathlock_until"]) - now) // 60
        return _no(f"身灭道消尚未消散（余 {left} 分钟），此期间不可迎战。")
    if now - float(st.get("last_fight") or 0) < FIGHT_CD_SEC:
        return _no(f"迎战调息中，{FIGHT_CD_SEC} 秒后再战。")
    tier = authority_mod.authority_21(doc)
    gate = GATE_SMALL if typ == "small" else GATE_BIG
    if tier < gate:
        return _no(f"迎战诡异{'小祭' if typ == 'small' else '大祭'}需权柄 {gate}/21"
                   f"（当前 {tier}/21）。")
    uid = str(doc.uid)
    row = w["participants"].get(uid)
    if isinstance(row, Mapping) and row.get("result") in ("win", "loss"):
        return _no("本轮祭礼你已留下一战结果，待下轮再战。")

    scale = 3 if typ == "small" else 5
    atk = max(1, int(getattr(stats, "atk", 0) or 0))
    defense = max(1, int(getattr(stats, "defense", 0) or 0))
    hp = max(1, int(getattr(stats, "hp", 0) or 0))
    bao = float(getattr(stats, "bao", 0) or 0)
    me = battle_mod.Unit("道友", atk, defense, hp, bao)
    # 原版是「玩家 + NPC 盟友」打 N 个 statScale 倍敌人；1v1 时 ×scale 必败，
    # 折算为单体始祖：攻防 0.8 倍、血量 (0.5+0.1×scale) 倍，难度仍随祭礼等级递增。
    foe = battle_mod.Unit("诡异始祖", int(atk * 0.8), int(defense * 0.8),
                          int(hp * (0.5 + 0.1 * scale)), 0.35)
    winner, _log, _a_hp, _b_hp = battle_mod.spar_full(me, foe, rng)
    won = winner == 0
    st["last_fight"] = now
    w["last_activity"] = now

    dealt = max(1, int(atk * (8 + rng.random() * 6)))
    w["damage"][uid] = int(w["damage"].get(uid, 0) or 0) + dealt
    act["hp"] = max(0, int(act["hp"]) - dealt)

    if not won:
        st["deathlock_until"] = now + DEATHLOCK_SEC
        st["slash_count"] = int(st.get("slash_count") or 0) + 1
        w["participants"][uid] = {"result": "loss", "killed": 0, "at": now}
        return _ok(f"【迎战失利】造成 {dealt:,} 伤害（本源余 {act['hp']:,}）。"
                   f"身灭道消 24 小时，天意一刀已斩 {st['slash_count']} 次。")

    st["kills"] = int(st.get("kills") or 0) + 1
    st["dao_gain"] = int(st.get("dao_gain") or 0) + 1
    w["defenders"] = int(w["defenders"]) + 1
    w["participants"][uid] = {"result": "win", "killed": 1, "at": now}
    gain = 30_000 + 10_000 * scale
    doc.stones = int(doc.stones or 0) + gain
    doc.exp = int(doc.exp or 0) + 50_000
    msg = (f"【迎战功成】造成 {dealt:,} 伤害（本源余 {act['hp']:,}），"
           f"灵石 +{gain:,}、修为 +50,000。守界者 {w['defenders']}/3。")
    ops: list = []
    if act["hp"] <= 0:
        if tier >= GATE_FINALE:
            w["plateau_destroyed"] = True
            ops.append(("mark", HIGHLAND, "始祖彻底永祭（永久）"))
            w["plane_log"].append(HIGHLAND)
            note, o2 = _close(w, years, now, True, rng, "始祖彻底永祭")
            msg += f"\n【高原彻底覆灭】三重永久标记已落下，祭礼永不复启。{note}"
            ops += o2
        else:
            w["rewinds"] = int(w["rewinds"]) + 1
            act["hp"] = int(act["hpmax"])
            w["participants"] = {}
            msg += (f"\n权柄未至 {GATE_FINALE}/21，高原因果回溯（第 {w['rewinds']} 次），"
                    f"本源复原、本轮战绩清空，可再战。")
    return _ok(msg, ops)


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
        return _no("恢复诸天位面唯管理员可执。")
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
        lines += [f"本场：{act['id']}　本源 {act['hp']:,}/{act['hpmax']:,}",
                  f"守界者 {w['defenders']}/3　参战 {len(w['participants'])} 人",
                  f"世界年 {act['start']:,} → {act['end']:,}（到期自动结算）"]
    else:
        due = w["big_due"] if w["big_due"] is not None else w["small_due"]
        lines.append(f"下轮：{'大祭' if w['big_due'] is not None else '小祭'}"
                     f" 世界年 {int(due or 0):,}")
    lines.append(f"天意一刀：{'生效至世界年 ' + format(int(w['heaven_slash_until']), ',') if int(w['heaven_slash_until']) > int(years) else '未生效'}")
    return "\n".join(lines)


def ancestor_text(w: dict) -> str:
    act = w["active"]
    if not isinstance(act, dict):
        return "【诡异始祖状态】始祖沉眠，未开启祭礼。" if not w["plateau_destroyed"] \
            else "【诡异始祖状态】厄土高原已彻底覆灭，始祖永不复生。"
    pct = int(act["hp"]) * 100 // max(1, int(act["hpmax"]))
    return (f"【诡异始祖状态】{act['id']}\n"
            f"本源 {act['hp']:,}/{act['hpmax']:,}（{pct}%）　"
            f"{'狂暴（本源低于三成）' if pct < 30 else '常态'}\n"
            f"十祖存活 {max(1, (pct + 9) // 10)}/10　"
            f"贡献榜首：{next(iter(sorted(w['damage'], key=lambda k: -int(w['damage'][k]))), '暂无')}")


def rank_text(w: dict) -> str:
    rows = sorted(w["damage"].items(), key=lambda kv: -int(kv[1] or 0))[:20]
    if not rows:
        return "【扫平厄土高原贡献榜】本轮尚无战果。"
    act = w["active"] or {}
    reward = int(act.get("reward") or 0)
    total = max(1, sum(int(v or 0) for _, v in w["damage"].items()))
    out = ["【扫平厄土高原贡献榜】"]
    for i, (uid, dmg) in enumerate(rows, 1):
        share = int(dmg) * 100 // total
        # 原版发奖 clamp(5000, 5_000_000) 与展示 clamp(10000, 1_000_000) 不一致，统一取发奖口径
        pay = max(5_000, min(5_000_000, int(dmg) * reward // total))
        out.append(f"{i:>2}. {uid}　伤害 {int(dmg):,}（{share}%）　预计灵石 {pay:,}")
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
        "#扫平厄土高原贡献榜 / #位面毁灭状态 / #永寂名单",
        "管理员：#恢复诸天位面（修复界门） / #复苏厄土高原（唯一解除永久覆灭）",
    ])


def rules_text() -> str:
    return "\n".join([
        "【诡异大祭 · 规则】",
        f"1. 世界年周期：小祭每 {SMALL_INTERVAL:,} 年、大祭滞后 {BIG_DELAY:,} 年，"
        f"每场持续 {ACTIVE_YEARS:,} 世界年；本移植 era 每次推进 1000 年（原版 ÷10）。",
        "2. 无 cron：自动开祭、到期结算、24h 无活动关闭均挂在每个祭礼指令入口惰性执行；"
        "没人发指令的场次会一直挂着。",
        f"3. 迎战门槛：小祭权柄 {GATE_SMALL}/21、大祭 {GATE_BIG}/21（原版 21/22/23 折算）；"
        f"迎战 CD {FIGHT_CD_SEC} 秒，本轮每人只留一次结果。",
        "4. 镜像战：原版「玩家+盟友 打 5 帝 / 10 始祖」折算为单体镜像"
        "（攻防 0.8 倍、血量 0.5+0.1×scale 倍，scale 小祭 3 / 大祭 5）；"
        "胜者累计伤害入贡献榜、得灵石与修为；败者身灭道消 24h。",
        "5. 守界：累计 3 名守界者即功成（不毁位面）；失败的大祭随机崩灭 2 处位面，"
        "由 W7-5b destroyed_planes 封闭界门，并登记永寂名单。",
        f"6. 终局：打空本源且权柄 {GATE_FINALE}/21 → 高原彻底覆灭三重标记（不可逆）；"
        "未达标则因果回溯、本源复原、战绩清空可再战。",
        "7. 回滚：#恢复诸天位面 修复界门并清空永寂名单；#复苏厄土高原 是唯一解除"
        "永久覆灭、重置祭礼纪年的入口。两者均限管理员、无消耗。",
        "8. 简化：不删玩家档、不传送、不做 720min 空间泡影超脱、不做绝灵寿元压制、"
        "不做全服广播。天意一刀折算为个人 24h 身灭道消，不留无消费者死字段。",
        "9. 数值：贡献榜奖励按发奖口径 clamp(5,000, 5,000,000) 统一（原版展示与实发两套 clamp）。",
    ])
