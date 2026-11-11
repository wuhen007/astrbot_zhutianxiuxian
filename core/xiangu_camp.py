"""仙古秘境 阵营 / 擂台 / 凶名（W26）——原版 `xianguPlace.js`
阵营系统段（XIANGU_FACTIONS L8513 / XianguFaction L10311 / 阵营任务 L10647 /
排行 L10724 / 献祭道种 L10359）+ 擂台（XianguArena L9226 / 参与 L9330 /
结算 checkArenaSettlement L10541）+ 凶名簿 / 悬赏榜 / 杀戮榜（L6219-6420）
+ `xianguArenaState.js` 擂台持久化。

shortcut：
- 阵营任务进度原版挂内存 FACTION_QUEST_TRACK（重启即失）+ updateFactionQuestProgress
  外部钩子；端口改存玩家 ext["xiangu"]["quest"]，进度由各交互点显式 bump
  （npc_kill→降魔卫道 / npc_talk→引渡迷途 / explore→秘境巡礼 / offer_seed→
  灵物供奉 / soul_search→搜魂猎手 / npc_attack→弱肉强食）。
- 阵营排行原版扫全服玩家档；端口把各玩家三系声望登记进
  calamity_state["xiangu"]["boards"]["reps"]，排行直接读榜（60s 缓存省略）。
- 擂台状态原版存 Redis（xianguArenaState.js 141 行）；端口挂
  calamity_state["xiangu"]["arena"][round_id]；30 分钟到期的结算由
  #仙古擂台 查看时懒触发；「本轮仙古第一」= 胜场第一名且 ≥1 胜 →
  crown 登记（st["crowned"]=round_id），解锁终极造化地（W25 终极门复用）。
- #秘境攻击 在擂台报名表内按名字寻敌（同服跨玩家），双方 per-uid 锁由
  handler 按 uid 排序获取；PvP 胜场计入擂台 wins，凶名 +10~30（区域加成）。
- 凶名 >100 主动 PvP 需消耗 50 道韵镇压杀意（原版一致）。

rng 约定：只用 rng.random()。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import xiangu as xg

# ---------------------------------------------------------------- 阵营定义

FACTIONS: dict[str, dict[str, Any]] = {
    "good": {
        "name": "善良阵营", "icon": "✦",
        "npc_types": ("古仙引路者", "古老传承者", "古帝虚影"),
        "desc": "仙古秘境中守护传承、引渡有缘人的存在",
        "ranks": ((500, "崇拜"), (200, "信任"), (100, "友善"), (50, "熟识"),
                  (0, "陌生"), (-50, "警惕"), (-150, "敌视"), (-10**9, "仇恨")),
        "quests": (
            {"name": "降魔卫道", "desc": "击败3位邪恶阵营NPC", "target": "npc_kill",
             "count": 3, "reward": (80, 30), "icon": "⚔️"},
            {"name": "引渡迷途", "desc": "与3位中立NPC交谈", "target": "npc_talk",
             "count": 3, "reward": (50, 20), "icon": "💬"},
            {"name": "秘境巡礼", "desc": "探索5次秘境区域", "target": "explore",
             "count": 5, "reward": (60, 25), "icon": "🗺️"},
            {"name": "灵物供奉", "desc": "献祭1枚道种", "target": "offer_seed",
             "count": 1, "reward": (100, 40), "icon": "🔥"}),
    },
    "neutral": {
        "name": "中立阵营", "icon": "◆",
        "npc_types": ("流浪修士", "道种贩者", "仙古兽灵"),
        "desc": "在秘境中独善其身的存在，讲究等价交换",
        "ranks": ((200, "知己"), (100, "信赖"), (50, "友好"), (0, "陌生"),
                  (-50, "疏远"), (-10**9, "排斥")),
        "quests": (
            {"name": "秘境见闻", "desc": "探索中触发3次NPC交谈", "target": "npc_talk",
             "count": 3, "reward": (40, 15), "icon": "💬"},
            {"name": "道种交易", "desc": "收集2枚普通道种", "target": "collect_seed",
             "count": 2, "reward": (70, 25), "icon": "💎"}),
    },
    "evil": {
        "name": "邪恶阵营", "icon": "▼",
        "npc_types": ("堕道修士",),
        "desc": "被邪念侵蚀的修士，在秘境中以掠夺为生",
        "ranks": ((500, "魔王"), (200, "霸主"), (100, "恶客"), (0, "猎物"), (-10**9, "仇敌")),
        "quests": (
            {"name": "弱肉强食", "desc": "掠夺3位其他NPC", "target": "npc_kill",
             "count": 3, "reward": (70, 30), "icon": "⚔️"},
            {"name": "巧取豪夺", "desc": "击败任意NPC并搜刮战利品", "target": "npc_kill",
             "count": 1, "reward": (50, 20), "icon": "💰"},
            {"name": "搜魂猎手", "desc": "对NPC搜魂1次", "target": "soul_search",
             "count": 1, "reward": (100, 40), "icon": "👻"}),
    },
}

OFFER_REWARDS = {"普通": (15, 10, 5_000), "稀有": (35, 25, 15_000),
                 "传说": (80, 60, 50_000), "神话": (200, 150, 200_000)}

ARENA_DURATION_MS = 30 * 60 * 1000
ARENA_COOLDOWN_MS = 2 * 60 * 60 * 1000
ARENA_REWARDS = {"winner": 500, "top3": 200, "runner": 50}


def rep_level(faction: str, val: float) -> str:
    for min_val, name in FACTIONS.get(faction, FACTIONS["good"])["ranks"]:
        if val >= min_val:
            return name
    return "陌生"


def boards_of(world: dict) -> dict:
    boards = world.setdefault("boards", {})
    boards.setdefault("reps", {})
    boards.setdefault("kills", {})
    return boards


def sync_rep_board(world: dict, doc: Any, st: Mapping) -> None:
    """把玩家三系声望登记上全服榜。"""
    reps = boards_of(world)["reps"]
    reps[str(getattr(doc, "uid", ""))] = {
        "name": str(getattr(doc, "name") or "无名修士"),
        "good": int((st.get("faction_rep") or {}).get("good", 0) or 0),
        "neutral": int((st.get("faction_rep") or {}).get("neutral", 0) or 0),
        "evil": int((st.get("faction_rep") or {}).get("evil", 0) or 0)}


def record_kill(world: dict, doc: Any, n: int = 1) -> None:
    kills = boards_of(world)["kills"]
    rec = kills.setdefault(str(getattr(doc, "uid", "")), {"name": str(getattr(doc, "name") or "无名修士"),
                                                          "kills": 0})
    rec["kills"] = int(rec.get("kills", 0) or 0) + int(n)


# ---------------------------------------------------------------- 阵营面板 / 任务

def faction_text(doc: Any, st: Mapping) -> str:
    rep = st.get("faction_rep") or {}
    infamy = int(st.get("infamy", 0) or 0)
    lines = ["【仙古秘境·阵营关系】", "",
             f"修士：{getattr(doc, 'name', '') or '修士'}", f"当前凶名：{infamy}", "",
             "━━━━ 阵营好感度 ━━━━", ""]
    effects = {
        "good": lambda v: ("NPC可传授秘法、赐予帝念" if v >= 200 else
                           "NPC交易优惠10%" if v >= 100 else
                           "NPC态度友善" if v >= 50 else
                           "NPC拒绝交易" if v < 0 else "NPC正常交互"),
        "neutral": lambda v: ("NPC可提供特殊情报" if v >= 100 else
                              "NPC拒绝交易" if v < -50 else "正常交互"),
        "evil": lambda v: ("邪恶NPC交易优惠30%" if v >= 200 else
                           "邪恶NPC不主动攻击" if v >= 100 else
                           "邪恶NPC保持警惕" if v >= 0 else "邪恶NPC视你为猎物"),
    }
    for key in ("good", "neutral", "evil"):
        val = int(rep.get(key, 0) or 0)
        f = FACTIONS[key]
        lines.append(f"{f['icon']} {f['name']} — {rep_level(key, val)}（{val:+d}）")
        lines.append(f"  包括：{'、'.join(f['npc_types'])}")
        lines.append(f"  当前效果：{effects[key](val)}")
        lines.append("")
    lines += ["━━━━ 提升方式 ━━━━",
              "· 与该阵营NPC交谈（+5/次，每日上限）",
              "· 完成阵营任务（+15~40）",
              "· 降魔（击败邪恶NPC）→ 善良+10",
              "· #献祭道种 → 善良声望 +15~200"]
    return "\n".join(lines)


def faction_quest(doc: Any, st: dict, rng: Callable[[], float], now_ms: float) -> str:
    """#阵营任务：按最高声望阵营接取/查看。"""
    rep = st.get("faction_rep") or {"good": 0, "neutral": 0, "evil": 0}
    fkey = max(rep, key=lambda k: int(rep.get(k, 0) or 0))
    fdef = FACTIONS[fkey]
    quest = st.get("quest")
    if isinstance(quest, dict) and quest.get("faction") == fkey and not quest.get("completed"):
        pct = min(100, int(quest["progress"] * 100 / max(1, quest["max"])))
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        return "\n".join([
            "【阵营任务·进行中】", "",
            f"{fdef['icon']} {fdef['name']}任务：{quest['name']}",
            f"{quest['desc']}", "",
            f"进度：{bar} {pct}%（{quest['progress']}/{quest['max']}）", "",
            f"奖励：道韵 +{quest['reward'][0]}｜好感 +{quest['reward'][1]}"])
    pool = [q for q in fdef["quests"]]
    if not pool:
        return f"【阵营任务·无可接】当前无可接取的{fdef['name']}任务。"
    q = pool[int(rng.random() * len(pool)) % len(pool)]
    st["quest"] = {"faction": fkey, "name": q["name"], "desc": q["desc"],
                   "target": q["target"], "progress": 0, "max": q["count"],
                   "reward": list(q["reward"]), "started_at": now_ms}
    return "\n".join([
        "【阵营任务·已接取】", "",
        f"{fdef['icon']} {fdef['name']}",
        f"{q['icon']} {q['name']}",
        q["desc"], "",
        f"目标：{q['count']} 次",
        f"奖励：道韵 +{q['reward'][0]}｜好感 +{q['reward'][1]}"])


def quest_bump(doc: Any, st: dict, action: str, n: int = 1) -> str | None:
    """阵营任务进度钩子。返回完成播报（无则 None）。"""
    quest = st.get("quest")
    if not isinstance(quest, dict) or quest.get("completed") or quest.get("target") != action:
        return None
    quest["progress"] = min(int(quest["max"]), int(quest.get("progress", 0) or 0) + int(n))
    if quest["progress"] >= int(quest["max"]):
        quest["completed"] = True
        daoyun, rep = quest["reward"]
        gains = st.setdefault("gains", {})
        gains["daoyun"] = int(gains.get("daoyun", 0) or 0) + daoyun
        fkey = str(quest.get("faction") or "good")
        frep = st.setdefault("faction_rep", {})
        frep[fkey] = int(frep.get(fkey, 0) or 0) + rep
        fdef = FACTIONS.get(fkey) or FACTIONS["good"]
        return "\n".join([
            "✅【阵营任务·完成】", "",
            f"{fdef['icon']} {quest['name']} 已完成！", "",
            f"道韵 +{daoyun}", f"{fdef['name']}好感 +{rep}", "",
            "使用 #阵营任务 接取新任务"])
    return None


def faction_rank_text(world: Mapping) -> str:
    reps = ((world.get("boards") or {}).get("reps") or {})
    lines = ["【仙古秘境·阵营排行】", ""]
    if not reps:
        lines.append("尚无修士在秘境中结识各方势力。")
        return "\n".join(lines)
    for key, fdef in FACTIONS.items():
        rows = sorted(((r.get("name", "?"), int(r.get(key, 0) or 0))
                       for r in reps.values()), key=lambda t: -t[1])[:5]
        lines.append(f"{fdef['icon']} {fdef['name']} Top5")
        if not rows or all(v == 0 for _, v in rows):
            lines.append("  暂无记录")
        for i, (name, val) in enumerate(rows, 1):
            lines.append(f"  {i}. {name} — {rep_level(key, val)}（{val:+d}）")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------- 献祭道种

def offer_seed(doc: Any, st: dict, seed_name: str, rng: Callable[[], float]) -> tuple[bool, str, dict]:
    """#献祭道种 [名]：从秘境背包/常驻道种库取一种，换声望+道韵+源石。"""
    bag = st.get("bag") or {}
    seeds = list(bag.get("seeds", ()))
    if not seeds:
        return False, "【献祭道种·无道种】你目前没有可献祭的道种，先去探索获取道种。", {}
    idx = -1
    if seed_name:
        for i, s in enumerate(seeds):
            nm = str(s.get("名称") if isinstance(s, dict) else s)
            if nm == seed_name or seed_name in nm:
                idx = i
                break
        if idx < 0:
            return False, f"未找到名为“{seed_name}”的道种，使用 #查看道种 查看列表", {}
    else:
        idx = next((i for i, s in enumerate(seeds)
                    if isinstance(s, dict) and s.get("品质") == "普通"), 0)
    target = seeds.pop(idx)
    bag["seeds"] = seeds
    quality = str(target.get("品质") if isinstance(target, dict) else "普通") or "普通"
    rep, daoyun, lingshi = OFFER_REWARDS.get(quality, OFFER_REWARDS["普通"])
    shenhuo = st.get("shenhuo") or {}
    if shenhuo.get("已点燃"):
        daoyun *= 2
    frep = st.setdefault("faction_rep", {})
    frep["good"] = int(frep.get("good", 0) or 0) + rep
    gains = st.setdefault("gains", {})
    gains["daoyun"] = int(gains.get("daoyun", 0) or 0) + daoyun
    rw = xg.grant_growth(doc, stone_rolls=0)
    xg.bag_add_growth(st["bag"], source_stone=lingshi)
    name = str(target.get("名称") if isinstance(target, dict) else target)
    return True, "\n".join([
        "【献祭道种】", "",
        f"{getattr(doc, 'name', '')}将 {name} [{quality}] 献祭于仙古秘境...",
        "道种化作金光，融入这片古老土地！", "",
        "【收益】",
        f"善良阵营声望 +{rep}",
        f"道韵 +{daoyun}" + ("（神火已燃，双倍回收！）" if shenhuo.get("已点燃") else ""),
        f"源石 +{lingshi:,}（暂存秘境背包）", "",
        f"当前善良声望：{frep['good']}"]), {"rep": rep, "daoyun": daoyun}


# ---------------------------------------------------------------- 擂台

def arena_of(world: dict, round_id: str) -> dict:
    arenas = world.setdefault("arena", {})
    a = arenas.get(round_id)
    if not isinstance(a, dict):
        a = {"state": None, "last_end_at": 0, "participants": [], "settled": False}
        arenas[round_id] = a
    return a


def in_arena_fragment(st: Mapping) -> bool:
    return (st.get("map") or {}).get("fragment_id") == xg.ARENA_FRAGMENT


def arena_settle_if_due(world: dict, round_id: str, now_ms: float,
                        crown_cb: Callable[[str, str, float], str | None] | None = None) -> str | None:
    """擂台到期懒结算：第一 500 / 前三 200 / 其余 50；冠军登记 crown。"""
    a = arena_of(world, round_id)
    state = a.get("state")
    if not state or state.get("ends_at", 0) > now_ms or a.get("settled"):
        return None
    a["settled"] = True
    a["last_end_at"] = state.get("ends_at", now_ms)
    parts = sorted(a.get("participants", ()), key=lambda p: -int(p.get("wins", 0) or 0))
    lines = ["【仙古擂台·尘埃落定】", ""]
    for i, p in enumerate(parts):
        place = "🥇" if i == 0 else ("🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}.")
        reward = ARENA_REWARDS["winner"] if i == 0 else \
            ARENA_REWARDS["top3"] if i < 3 else ARENA_REWARDS["runner"]
        lines.append(f"{place} {p.get('name')} — {p.get('wins', 0)} 胜 — 道韵 +{reward}")
    crown_note = None
    if parts and int(parts[0].get("wins", 0) or 0) > 0 and crown_cb:
        crown_note = crown_cb(str(parts[0].get("uid")), str(parts[0].get("name")),
                              now_ms / 1000)
        if crown_note:
            lines += ["", crown_note]
    a["state"] = None
    a["participants"] = parts
    return "\n".join(lines)


def arena_text(doc: Any, st: dict, world: dict, round_id: str, now_ms: float,
               crown_cb: Callable | None = None) -> tuple[str, dict]:
    """#仙古擂台：开擂 / 展示状态。返回 (text, events)。"""
    events: dict[str, Any] = {}
    settle_msg = arena_settle_if_due(world, round_id, now_ms, crown_cb)
    a = arena_of(world, round_id)
    state = a.get("state")
    parts = a.get("participants", ())
    if state and state.get("ends_at", 0) > now_ms:
        remaining = int((state["ends_at"] - now_ms) / 60000)
        lines = ["【仙古擂台·进行中】", "",
                 f"剩余时间：{remaining} 分钟", f"参赛人数：{len(parts)}", "", "【当前参赛者】"]
        for i, p in enumerate(parts, 1):
            lines.append(f"{i}. {p.get('name')} — 胜场：{p.get('wins', 0)}")
        lines += ["", "使用 #参与仙古擂台 加入擂台",
                  "使用 #秘境攻击 [名字] 与擂台参与者交战"]
        if settle_msg:
            lines = [f"{settle_msg}", ""] + lines
        return "\n".join(lines), events
    if settle_msg:
        events["settle_msg"] = settle_msg
    # 未开擂
    if not in_arena_fragment(st):
        return ("【仙古擂台·尚未抵达】请先循深层区域出口进入仙古擂台，"
                "亲临战台后方可开擂。"), events
    last_end = float(a.get("last_end_at", 0) or 0)
    cooldown_left = int((last_end + ARENA_COOLDOWN_MS - now_ms) / 60000)
    if last_end > 0 and cooldown_left > 0:
        return ("\n".join(["【仙古擂台·冷却中】", "",
                           "上一届擂台已结束，仙古之地尚未积蓄足够的道韵，",
                           "无法开启新的擂台争霸！", "",
                           f"冷却剩余：{cooldown_left} 分钟", "",
                           "提示：届时使用 #仙古擂台 开启"])), events
    # 开擂
    a["state"] = {"opened_by": str(getattr(doc, "uid", "")),
                  "opened_name": str(getattr(doc, "name") or "修士"),
                  "ends_at": now_ms + ARENA_DURATION_MS}
    a["participants"] = [{"uid": str(getattr(doc, "uid", "")),
                          "name": str(getattr(doc, "name") or "修士"), "wins": 0}]
    events["broadcast"] = "\n".join([
        "【仙古秘境·大事件！】", "",
        "═══════════════════", "仙古擂台 横空出世！", "═══════════════════", "",
        "仙古秘境深处，一块古老的擂台浮现于虚空之中。先贤曾在此论道比剑，"
        "今日再现，诸位修士皆可参与，夺得“仙古第一”之名！", "",
        f"由{getattr(doc, 'name') or '修士'}率先踏上擂台，引动古阵运转！", "",
        "【参与方式】使用 #参与仙古擂台 报名",
        "【对决方式】#秘境攻击 [名字]",
        "", "擂台持续：30 分钟",
        "胜者将获得丰厚道韵奖励及“本轮仙古第一”冠冕（解锁终极造化地）！"])
    return "\n".join([
        "【仙古擂台·开启！】", "",
        f"{getattr(doc, 'name') or '修士'}踏上擂台，引动古阵！",
        "全秘境修士已收到通知！", "",
        "你已成为第一位参与者，等待其他修士挑战...", "",
        "使用 #秘境攻击 [名字] 进行擂台对决"]), events


def arena_join(doc: Any, st: dict, world: dict, round_id: str, now_ms: float) -> str:
    """#参与仙古擂台：须亲临擂台碎片。"""
    a = arena_of(world, round_id)
    state = a.get("state")
    if not state or state.get("ends_at", 0) <= now_ms:
        return "【参与失败】当前没有进行中的擂台。可在擂台碎片使用 #仙古擂台 开启。"
    if not in_arena_fragment(st):
        return "【参与失败】只有身处仙古擂台碎片才能报名。"
    uid = str(getattr(doc, "uid", ""))
    for p in a["participants"]:
        if p.get("uid") == uid:
            return f"【已在擂台】你已报名本届擂台（当前胜场 {p.get('wins', 0)}）。"
    a["participants"].append({"uid": uid, "name": str(getattr(doc, "name") or "修士"), "wins": 0})
    return "\n".join([
        "【参与仙古擂台·报名成功】", "",
        f"{getattr(doc, 'name') or '修士'}踏入古阵，本届擂台参赛者 +1。", "",
        "使用 #秘境攻击 [名字] 向其他参赛者发起对决。",
        f"擂台剩余：{int((state['ends_at'] - now_ms) / 60000)} 分钟"])


def arena_pvp(doc: Any, st: dict, world: dict, round_id: str, target_name: str,
              now_ms: float, rng: Callable[[], float],
              battle: Callable[[dict, str], tuple[bool, list[str]]] | None) -> tuple[str, dict | None]:
    """#秘境攻击 [名字]：擂台报名者之间 PvP。返回 (text, rival_st 或 None)。

    rival_st：对手的 ext["xiangu"]（handler 持锁读对方档后传入并落库）。
    """
    events: dict[str, Any] = {}
    a = arena_of(world, round_id)
    state = a.get("state")
    on_stage = in_arena_fragment(st)
    if not state or state.get("ends_at", 0) <= now_ms or not on_stage:
        if not on_stage:
            return "【秘境攻击】只有身处仙古擂台碎片，方可进行擂台对决。", None
        return "【秘境攻击】当前没有进行中的擂台对决。", None
    # 凶名镇压
    infamy = int(st.get("infamy", 0) or 0)
    gains = st.setdefault("gains", {})
    if infamy > 100:
        if int(gains.get("daoyun", 0) or 0) < 50:
            return ("\n".join(["【PvP·道韵不足】",
                               "你凶名赫赫，欲再行杀戮，却被秘境法则排斥——"
                               "道韵不足以镇压杀意！", "",
                               f"凶名值：{infamy}｜当前道韵：{gains.get('daoyun', 0)}",
                               "攻击所需：50 道韵"]), None)
        gains["daoyun"] = int(gains["daoyun"]) - 50
    me_uid = str(getattr(doc, "uid", ""))
    me = next((p for p in a["participants"] if p.get("uid") == me_uid), None)
    if me is None:
        return "【秘境攻击】你未报名本届擂台——先 #参与仙古擂台。", events
    rival = next((p for p in a["participants"]
                  if p.get("uid") != me_uid and target_name and target_name in str(p.get("name"))), None)
    if rival is None:
        names = "、".join(str(p.get("name")) for p in a["participants"] if p.get("uid") != me_uid) or "无"
        return f"【秘境攻击·无此对手】擂台上的其他参赛者：{names}", None
    events["rival_uid"] = str(rival.get("uid"))
    events["rival_name"] = str(rival.get("name"))
    zone = str(st.get("location") or "擂台区域")
    return "", events  # handler 组装双方战斗后调 arena_pvp_apply


def arena_pvp_apply(doc: Any, st: dict, rival_doc: Any, rival_st: dict | None,
                    world: dict, round_id: str, won: bool, log_lines: list[str],
                    rng: Callable[[], float]) -> tuple[str, dict]:
    """战斗结果写回：胜场/凶名/道韵/杀戮榜（原版 XianguPvPAttack 结算段）。"""
    events: dict[str, Any] = {}
    a = arena_of(world, round_id)
    me_uid = str(getattr(doc, "uid", ""))
    me = next((p for p in a["participants"] if p.get("uid") == me_uid), None)
    rival_name = str(getattr(rival_doc, "name") or "对手")
    zone = "擂台区域"
    if won:
        infamy_gain = 10 + int(rng.random() * 20)
        st["infamy"] = int(st.get("infamy", 0) or 0) + infamy_gain
        gains = st.setdefault("gains", {})
        gains["daoyun"] = int(gains.get("daoyun", 0) or 0) + 30
        st["kills"] = int(st.get("kills", 0) or 0) + 1
        record_kill(world, doc)
        if me is not None:
            me["wins"] = int(me.get("wins", 0) or 0) + 1
        qb = quest_bump(doc, st, "npc_kill")  # 擂台击杀按原版不推进阵营，保留 None
        text = "\n".join([
            f"【擂台对决·胜】", "",
            f"{getattr(doc, 'name', '')}与{rival_name}在仙古擂台上展开死斗！",
            *log_lines[-4:], "",
            f"凶名 +{infamy_gain}｜道韵 +30｜杀戮榜 +1",
            f"擂台胜场：{me['wins'] if me else 1}"])
        if qb:
            text += "\n\n" + qb
        return text, events
    hp_loss = max(1, int(xg._hp_of(doc) * 0.3))
    xg._set_hp(doc, max(1, xg._hp_of(doc) - hp_loss))
    return "\n".join([
        "【擂台对决·败】", "",
        f"{getattr(doc, 'name', '')}与{rival_name}在仙古擂台上展开死斗！",
        *log_lines[-4:], "",
        f"【损失】血量 -{hp_loss:,}｜擂台胜负未变。"]), events


# ---------------------------------------------------------------- 凶名簿 / 悬赏榜 / 杀戮榜

def infamy_text(doc: Any, st: Mapping) -> str:
    infamy = int(st.get("infamy", 0) or 0)
    if infamy >= 300:
        title, desc = "煞神降世", "杀性滔天，连古纪遗灵都对你退避三舍"
    elif infamy >= 200:
        title, desc = "凶名赫赫", "杀戮成性，已在秘境中留下赫赫凶名"
    elif infamy >= 100:
        title, desc = "恶名远扬", "各方势力已将你记入黑名单"
    elif infamy >= 50:
        title, desc = "凶徒", "凶名渐起，善良之辈见你绕道而行"
    elif infamy >= 20:
        title, desc = "小有凶名", "秘境中的修士开始对你有所耳闻"
    else:
        title, desc = "无名之辈", "你尚未在秘境中留下恶名"
    return "\n".join([
        "【仙古秘境·凶名簿】", "",
        f"修士：{getattr(doc, 'name', '') or '修士'}",
        f"凶名值：{infamy}", f"凶名等级：{title}", f"{desc}", "",
        "凶名影响：",
        "· 凶名越高，探索遇敌概率越高，NPC 购买有溢价",
        "· 凶名 >100 时主动 PvP 需消耗 50 道韵镇压杀意",
        "· 凶名 ≥50 自动登上悬赏榜（赏金 = 凶名 × 100 灵石）",
        *( ["【悬赏】高危凶名！你已可被其他修士追杀"] if infamy >= 100 else
           ["提示：保持低凶名值有利于秘境探索"])])


def bounty_text(world: Mapping, doc: Any, st: Mapping) -> str:
    """悬赏榜：全服凶名 ≥50 登榜（杀戮榜 kills 附带）。凶名存在 ext，端口
    把榜内玩家登记进 boards["infamy"]（每次查看凶名时登记）。"""
    rows = ((world.get("boards") or {}).get("infamy") or {})
    me_uid = str(getattr(doc, "uid", ""))
    rows = dict(rows)
    rows[me_uid] = {"name": str(getattr(doc, "name") or "无名修士"),
                    "infamy": int(st.get("infamy", 0) or 0),
                    "zone": str(st.get("location") or "边缘区域")}
    ranked = sorted(((v.get("name", "?"), int(v.get("infamy", 0) or 0), v.get("zone", "?"))
                     for v in rows.values() if int(v.get("infamy", 0) or 0) >= 50),
                    key=lambda t: -t[1])
    lines = ["【仙古秘境·悬赏榜】", "",
             "· 凶名值≥50 的修士自动上榜", "· 赏金 = 凶名值 × 100 灵石", ""]
    if not ranked:
        lines.append("暂无修士达到悬赏线（凶名 ≥50）。")
        return "\n".join(lines)
    lines.append("排名  修士          凶名    赏金      位置")
    for i, (name, val, zone) in enumerate(ranked[:10], 1):
        lines.append(f"{i:<4}  {name:<10}  {val:<6}  {val * 100:<8}  {zone}")
    return "\n".join(lines)


def kill_rank_text(world: Mapping) -> str:
    kills = ((world.get("boards") or {}).get("kills") or {})
    ranked = sorted(((v.get("name", "?"), int(v.get("kills", 0) or 0))
                     for v in kills.values()), key=lambda t: -t[1])[:10]
    if not ranked:
        return "【杀戮榜】暂无数据"
    lines = ["【仙古秘境·杀戮榜】", "",
             "排名  修士          击杀", ""]
    for i, (name, n) in enumerate(ranked, 1):
        mark = " 🔥" if i == 1 else ""
        lines.append(f"{i:<4}  {name:<10}  {n}{mark}")
    return "\n".join(lines)


def register_infamy(world: dict, doc: Any, st: Mapping) -> None:
    boards = boards_of(world)
    boards.setdefault("infamy", {})[str(getattr(doc, "uid", ""))] = {
        "name": str(getattr(doc, "name") or "无名修士"),
        "infamy": int(st.get("infamy", 0) or 0),
        "zone": str(st.get("location") or "边缘区域")}
