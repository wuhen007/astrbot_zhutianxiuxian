"""千年灾劫·域外来敌（B11）：千年灾厄 / 灾厄魔主 / 天魔炼化 / 域外功法 / 纪元。

原版：apps/Boss/ForeignCalamity.js + model/foreignCalamity.js + apps/tasks/EraChangeTask.js。

本移植：
- 灾厄按全服玩家均值 × 类型倍率生成，共享存世上限 100 尊；超额由 NPC 天骄「巡猎」退场
- 自然刷新：每跨过一个千年生成 1-10 尊（#下一千年 推进）；管理员可 #召唤灾厄 主动召唤
- 讨伐：15 分钟调息；胜则伏诛，败则按实际打掉的气血留伤，可多次磨血
- 击杀累计 9-12 尊触发【灾厄魔主】：共享血条，按打掉本体气血计贡献，按名次发奖
- 纪元：#下一千年 推进 1000 年，绝灵压制逐纪元加深（-5%/千年，上限 50%），位面损失入档

shortcut（与原版的差异，均在此声明）：
- 业力 / 位面青睐未建体系 → 改为修为 / 血气奖励
- 遗珍（FishKing relic）、魔主「化外身」分身、「逆命劫生经」复活 未做
- 绝灵压制只作用于灾厄奖励（不改全局修炼效率）
- 星宇护身符 = 个人免压制符（一次性，抵消一个纪元的减益）
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

from .battle import Unit, spar_full

MAX_ACTIVE = 100
PAGE_REQUIREMENT = 10
BATTLE_CD_SECONDS = 15 * 60
REFINE_WINDOW_SECONDS = 5 * 60
NATURAL_YEAR = 1000
OVERLORD_BASE_KILLS = 10
# W7-5c：域外业力 / 位面青睐 / 魔主逆命复生
KARMA_PER_100_PENALTY = 0.10      # 每 100 业力，突破成功率 -10%
KARMA_PENALTY_CAP = 0.30          # 最多 -30%
KARMA_REWARD_RANGE = (5, 10)      # 击杀普通灾厄：业力 -5~10
KARMA_OVERLORD = 20               # 击杀魔主：业力 -20
FAVOR_REWARD_RANGE = (5, 20)      # 击杀普通灾厄：位面青睐 +5~20
FAVOR_OVERLORD = 50               # 击杀魔主：位面青睐 +50
PLANE_FAVOR_WUDAO_COST = 50       # 悟道消耗 50 点青睐换 +20% 感悟
PLANE_FAVOR_WUDAO_BONUS = 0.20
REVIVE_MULT = 1.25                # 魔主逆命复生：全属性永久 +25%

PLANE_NAMES = ("下界八域", "遮天", "九天十地", "界海", "太初星墟", "小阴间", "大阴间", "仙界", "仙域", "阳间")

TECHNIQUES: tuple[dict, ...] = (
    {"name": "太虚观界经", "category": "道与法"},
    {"name": "万星归墟法", "category": "道与法"},
    {"name": "彼岸照神典", "category": "道与法"},
    {"name": "无相天罗经", "category": "道与法"},
    {"name": "因果断流法", "category": "道与法"},
    {"name": "葬界指", "category": "盖世杀术"},
    {"name": "逆星河", "category": "盖世杀术"},
    {"name": "斩道天轮", "category": "盖世杀术"},
    {"name": "寂灭魔瞳", "category": "盖世杀术"},
    {"name": "破纪元枪", "category": "盖世杀术"},
    {"name": "周天噬灵诀", "category": "修炼功法"},
    {"name": "太初锻神录", "category": "修炼功法"},
    {"name": "九转外道经", "category": "修炼功法"},
)

STRENGTHEN_ITEMS = ("大道传承", "不朽传承", "轮回传承", "森罗万象", "天命之力", "纪元加护")
TOKENS = ("遣龙令", "遣虎令")

PROFILES: tuple[dict, ...] = (
    {
        "type": "孽兽",
        "names": ("吞界孽犼", "腐星狰", "噬道天蜈", "血月狻猊"),
        "mult": {"atk": 1.05, "defense": 0.95, "hp": 1.35},
        "extra": "太古血脉",
    },
    {
        "type": "域外邪魔",
        "names": ("无相天魔", "蚀界魔胎", "六欲邪主", "黑日魔君"),
        "mult": {"atk": 1.2, "defense": 0.9, "hp": 1.1},
        "extra": "域外魔躯",
    },
    {
        "type": "外道修士",
        "names": ("逆律道人", "葬星散人", "断因老祖", "无归客"),
        "mult": {"atk": 1.0, "defense": 1.12, "hp": 1.0},
        "extra": "外道法身",
    },
)


def default_state() -> dict[str, Any]:
    return {
        "seq": 0,
        "calamities": [],
        "kills": 0,
        "next_spawn": OVERLORD_BASE_KILLS,
        "overlord": None,
        "report": None,
        "era": {
            "index": 0,
            "years": 0,
            "suppression": 0.0,
            "losses": [],
            "events": [],
        },
    }


# ---------------------------------------------------------------- 业力 / 青睐

def karma_of(doc: Any) -> int:
    try:
        return max(0, int(doc.ext.get("karma", 0) or 0))
    except (TypeError, ValueError):
        return 0


def add_karma(doc: Any, amount: int) -> int:
    value = max(0, karma_of(doc) + int(amount))
    doc.ext["karma"] = value
    return value


def reduce_karma(doc: Any, amount: int) -> tuple[int, int]:
    """返回 (实际消减, 剩余)。业力不为负。"""
    before = karma_of(doc)
    after = max(0, before - max(0, int(amount)))
    doc.ext["karma"] = after
    return before - after, after


def karma_penalty(doc: Any) -> float:
    """业力对突破成功率的减益（负值，最多 -30%）。"""
    return -min(KARMA_PENALTY_CAP,
                (karma_of(doc) // 100) * KARMA_PER_100_PENALTY)


def favor_of(doc: Any) -> int:
    try:
        return max(0, int(doc.ext.get("plane_favor", 0) or 0))
    except (TypeError, ValueError):
        return 0


def add_favor(doc: Any, amount: int) -> int:
    value = max(0, favor_of(doc) + int(amount))
    doc.ext["plane_favor"] = value
    return value


def consume_favor_for_wudao(doc: Any, gain: int, remaining: int | None = None) -> tuple[int, int]:
    """悟道结算：青睐 ≥50 时消耗 50 点，本次感悟 +20%（不超过剩余可补量）。

    返回 (实际获得, 消耗点数)。不足 50 或没有增益空间时不消耗。
    """
    base = max(0, int(gain))
    cap = base if remaining is None else max(0, min(base, int(remaining)))
    favor = favor_of(doc)
    enhanced = int(base * (1 + PLANE_FAVOR_WUDAO_BONUS))
    if remaining is not None:
        enhanced = min(enhanced, max(0, int(remaining)))
    if favor < PLANE_FAVOR_WUDAO_COST or enhanced <= cap:
        return cap, 0
    doc.ext["plane_favor"] = favor - PLANE_FAVOR_WUDAO_COST
    return enhanced, PLANE_FAVOR_WUDAO_COST


def ensure(value: Mapping | None) -> dict[str, Any]:
    state = dict(value or {})
    base = default_state()
    for key, default in base.items():
        state.setdefault(key, default)
    if not isinstance(state.get("calamities"), list):
        state["calamities"] = []
    if not isinstance(state.get("era"), dict):
        state["era"] = base["era"]
    era = state["era"]
    for key, default in base["era"].items():
        era.setdefault(key, default)
    era["losses"] = list(era.get("losses") or [])[-12:]
    era["events"] = list(era.get("events") or [])[-12:]
    return state


def average_stats(players: list[Mapping]) -> dict[str, float]:
    """全服玩家均值；无有效样本时用保底（对应原版 FALLBACK_AVERAGE）。"""
    valid = [p for p in players if float(p.get("atk") or 0) > 0 and float(p.get("hp") or 0) > 0]
    if not valid:
        return {"atk": 5_000, "defense": 5_000, "hp": 15_000, "bao": 0.2, "samples": 0}
    n = len(valid)
    return {
        "atk": sum(float(p.get("atk") or 0) for p in valid) / n,
        "defense": sum(float(p.get("defense") or 0) for p in valid) / n,
        "hp": sum(float(p.get("hp") or 0) for p in valid) / n,
        "bao": sum(float(p.get("bao") or 0) for p in valid) / n,
        "samples": n,
    }


def suppression_of(state: Mapping) -> float:
    return float(state.get("era", {}).get("suppression") or 0.0)


# ---------------------------------------------------------------- 灾厄生成 / 巡猎

def spawn_wave(state: dict, world_year: int, count: int, avg: Mapping,
               rng: random.Random, source: str = "natural") -> list[dict]:
    """生成 1-10 尊灾厄并写入 state；返回本批实体。"""
    count = max(1, min(10, int(count)))
    year = max(0, int(world_year))
    made: list[dict] = []
    for _ in range(count):
        profile = rng.choice(PROFILES)
        swing = 0.9 + rng.random() * 0.2
        mult = profile["mult"]
        hp = max(1, int(avg["hp"] * mult["hp"] * swing))
        state["seq"] = int(state.get("seq", 0)) + 1
        name = f"{rng.choice(profile['names'])}·{source[:2].upper()}{state['seq']:03d}"
        entity = {
            "id": f"calamity-{state['seq']}",
            "name": name,
            "type": profile["type"],
            "extra": profile["extra"],
            "world_year": year,
            "source": source,
            "atk": max(1, int(avg["atk"] * mult["atk"] * swing)),
            "defense": max(1, int(avg["defense"] * mult["defense"] * swing)),
            "hp": hp,
            "max_hp": hp,
            "bao": max(0.0, min(0.95, float(avg["bao"]) * swing)),
            "status": "active",
            "spawned_at": float(year) + len(made) * 0.001,
        }
        made.append(entity)
    state["calamities"].extend(made)
    state["report"] = cull(state, rng)
    return [e for e in made if any(c["id"] == e["id"] for c in state["calamities"])]


def cull(state: dict, rng: random.Random) -> dict:
    """超出上限时由 NPC 天骄巡猎最旧的存世灾厄。返回巡猎报告。"""
    active = [e for e in state["calamities"] if e.get("status") == "active"]
    active.sort(key=lambda e: (float(e.get("spawned_at") or 0), str(e.get("id"))))
    report = {"count": 0, "victims": [], "remaining": len(active)}
    while len(active) > MAX_ACTIVE:
        victim = active.pop(0)
        killer = rng.choice(("巡天的绝世天骄", "镇界的诸天强者"))
        victim["status"] = "culled"
        report["count"] += 1
        report["victims"] = (report["victims"] + [
            {"name": victim["name"], "type": victim["type"], "killer": killer}
        ])[-5:]
    report["remaining"] = len(active)
    # 被巡猎 / 已领奖的旧记录只保留最近 200 条，避免全局档无限膨胀
    keep = [e for e in state["calamities"] if e.get("status") == "active"]
    keep += [e for e in state["calamities"] if e.get("status") != "active"][-200:]
    state["calamities"] = keep
    return report


def active_calamities(state: Mapping) -> list[dict]:
    items = [e for e in state.get("calamities", []) if e.get("status") == "active"]
    items.sort(key=lambda e: (float(e.get("spawned_at") or 0), str(e.get("id"))), reverse=True)
    return items


def resolve(state: Mapping, keyword: str) -> dict | None:
    key = str(keyword or "").strip()
    if not key:
        return None
    active = active_calamities(state)
    if key.isdigit():
        i = int(key) - 1
        return active[i] if 0 <= i < len(active) else None
    for e in active:
        if e.get("id") == key or e.get("name") == key:
            return e
    for e in active:
        if key in str(e.get("name", "")):
            return e
    return None


def cull_report_text(report: Mapping | None) -> str:
    if not report or not report.get("count"):
        return ""
    lines = [f"【诸天巡猎】天骄与诸天强者出手，已击杀 {report['count']} 尊超额域外灾厄。"]
    lines += [f"{v['killer']}斩灭了【{v['name']}】。" for v in report.get("victims", [])]
    lines.append(f"巡猎后存世 {report.get('remaining', 0)} 尊；普通灾厄上限 {MAX_ACTIVE} 尊。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 讨伐

def battle_calamity(doc: Any, entity: dict, stats: Mapping,
                    rng: random.Random, now: float) -> dict:
    """玩家与一尊灾厄单挑。胜则伏诛；败则留伤并保留实体气血。"""
    me = Unit(str(getattr(doc, "name", "") or "道友"), int(stats["atk"]),
              int(stats["defense"]), max(1, int(stats["hp"])), float(stats.get("bao") or 0))
    foe = Unit(entity["name"], int(entity["atk"]), int(entity["defense"]),
               max(1, int(entity["hp"])), float(entity.get("bao") or 0))
    winner, log, a_hp, b_hp = spar_full(me, foe, rng)
    won = winner == 0
    before = int(entity["hp"])
    entity["hp"] = 0 if won else max(1, int(b_hp or 1))
    if won:
        entity["status"] = "defeated"
        entity["defeated_at"] = float(now)
        entity["defeated_by"] = str(doc.uid)
        entity["defeated_by_name"] = str(getattr(doc, "name", "") or doc.uid)
        before = max(before, 1)
    return {
        "won": won,
        "log": list(log),
        "damage": max(0, before - int(entity["hp"])),
        "a_hp": max(1, int(a_hp or 1)) if won else 1,
    }


# ---------------------------------------------------------------- 灾厄魔主

def maybe_spawn_overlord(state: dict, avg: Mapping, rng: random.Random, now: float) -> dict | None:
    """击杀数达到阈值时降临魔主。返回新魔主或 None。"""
    ov = state.get("overlord")
    if isinstance(ov, Mapping) and ov.get("status") == "active":
        return None
    if int(state.get("kills", 0)) < int(state.get("next_spawn", OVERLORD_BASE_KILLS)):
        return None
    base = max(1.0, float(avg["atk"]))
    hp = max(1, int(base * 120))
    state["seq"] = int(state.get("seq", 0)) + 1
    overlord = {
        "id": f"overlord-{state['seq']}",
        "name": rng.choice(("裂界吞星魔主", "万劫覆世魔主", "葬道天渊魔主")),
        "type": "灾厄魔主",
        "hp": hp,
        "max_hp": hp,
        "atk": max(1, int(base * 1.2)),
        "defense": max(1, int(base * 0.8)),
        "status": "active",
        "spawned_at": float(now),
        "contributions": {},
        "claims": {},
        "defeated_by": None,
        "defeated_at": None,
    }
    state["overlord"] = overlord
    state["next_spawn"] = int(state.get("kills", 0)) + rng.randint(9, 12)
    state["era"]["events"] = (state["era"].get("events") or [])[-11:] + [
        {"at": float(now), "text": f"【裂界魔临】{overlord['name']}降临诸天。"}
    ]
    return overlord


def battle_overlord(state: dict, doc: Any, stats: Mapping,
                    rng: random.Random, now: float) -> dict:
    ov = state.get("overlord")
    if not isinstance(ov, Mapping) or ov.get("status") != "active":
        return {"error": "当前没有灾厄魔主降临。"}
    me = Unit(str(getattr(doc, "name", "") or "道友"), int(stats["atk"]),
              int(stats["defense"]), max(1, int(stats["hp"])), float(stats.get("bao") or 0))
    boss = Unit(ov["name"], int(ov["atk"]), int(ov["defense"]), max(1, int(ov["hp"])), 1.0)
    winner, log, a_hp, b_hp = spar_full(me, boss, rng)
    before = int(ov["hp"])
    after = max(0, int(b_hp or 0))
    damage = max(0, before - after)
    ov["hp"] = after
    uid = str(doc.uid)
    if damage > 0:
        contrib = dict(ov.get("contributions") or {})
        prev = contrib.get(uid) or {"name": str(getattr(doc, "name", "") or uid), "damage": 0, "challenges": 0}
        contrib[uid] = {
            "name": prev.get("name") or uid,
            "damage": int(prev.get("damage") or 0) + damage,
            "challenges": int(prev.get("challenges") or 0) + 1,
        }
        ov["contributions"] = contrib
    defeated = after <= 0
    revived = False
    if defeated and not ov.get("revived"):
        # 逆命劫生经：首次伏诛时满血复生，全属性永久 +25%
        revived = True
        ov["revived"] = True
        ov["revived_at"] = float(now)
        ov["max_hp"] = max(1, int(int(ov.get("max_hp", 1)) * REVIVE_MULT))
        ov["hp"] = ov["max_hp"]
        ov["atk"] = max(1, int(int(ov.get("atk", 1)) * REVIVE_MULT))
        ov["defense"] = max(1, int(int(ov.get("defense", 1)) * REVIVE_MULT))
        ov["status"] = "active"
        after = int(ov["hp"])          # 返回给调用方的血量要反映复生后的真实值
        state["era"]["events"] = (state["era"].get("events") or [])[-11:] + [
            {"at": float(now), "text": f"【逆命劫生】{ov['name']}满血复生，全属性 +25%！"}
        ]
        defeated = False
    if defeated:
        ov["status"] = "defeated"
        ov["defeated_by"] = uid
        ov["defeated_at"] = float(now)
        state["era"]["events"] = (state["era"].get("events") or [])[-11:] + [
            {"at": float(now), "text": f"【魔主伏诛】{ov['name']}被诸天修士镇压。"}
        ]
    return {
        "won": winner == 0,
        "log": list(log),
        "damage": damage,
        "defeated": defeated,
        "revived": revived,
        "hp": after,
        "max_hp": int(ov["max_hp"]),
        "a_hp": max(1, int(a_hp or 1)),
    }


def overlord_rank(ov: Mapping) -> list[dict]:
    rows = []
    for uid, c in (ov.get("contributions") or {}).items():
        dmg = max(0, int(c.get("damage") or 0))
        if dmg > 0:
            rows.append({"uid": uid, "name": c.get("name") or uid, "damage": dmg,
                         "challenges": int(c.get("challenges") or 1)})
    rows.sort(key=lambda r: (-r["damage"], r["uid"]))
    return rows


def overlord_reward(ov: Mapping, uid: str) -> dict | None:
    ranking = overlord_rank(ov)
    rank = next((i + 1 for i, r in enumerate(ranking) if r["uid"] == uid), 0)
    if not rank:
        return None
    page_amount = 3 + (2 if rank == 1 else 0) + (1 if ov.get("defeated_by") == uid else 0)
    technique = TECHNIQUES[(hash(str(ov.get("id"))) + rank) % len(TECHNIQUES)]
    return {
        "rank": rank,
        "damage": ranking[rank - 1]["damage"],
        "page": f"{technique['name']}残页",
        "amount": page_amount,
        "karma": KARMA_OVERLORD,
        "favor": FAVOR_OVERLORD,
    }


def deterministic_roll(boss_id: str, uid: str) -> float:
    h = 2166136261
    for ch in f"{boss_id}:{uid}":
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h / 0x100000000


def rift_memory(doc: Any, boss_id: str) -> dict:
    """裂界残忆：35% 概率，3 次保底。"""
    state = dict(doc.ext.get("rift_memory") or {})
    state.setdefault("unlocked", False)
    state.setdefault("pity", 0)
    if state.get("unlocked"):
        return {"state": state, "granted": False, "already": True, "pity": 0}
    attempts = int(state.get("pity") or 0) + 1
    roll = deterministic_roll(boss_id, str(doc.uid))
    granted = attempts >= 3 or roll < 0.35
    if granted:
        state = {"unlocked": True, "pity": 0, "source": boss_id}
    else:
        state = {"unlocked": False, "pity": attempts}
    return {"state": state, "granted": granted, "already": False, "pity": state.get("pity", 0)}


# ---------------------------------------------------------------- 炼化 / 纪元

def grant_refine(doc: Any, entity: Mapping, now: float) -> None:
    doc.ext["calamity_refine"] = {
        "entity_id": entity.get("id"),
        "name": entity.get("name"),
        "expires_at": float(now) + REFINE_WINDOW_SECONDS,
    }


def take_refine(doc: Any, now: float) -> dict | None:
    pending = doc.ext.get("calamity_refine")
    if not isinstance(pending, Mapping):
        return None
    if float(pending.get("expires_at") or 0) < now:
        doc.ext.pop("calamity_refine", None)
        return None
    return dict(pending)


def advance_era(state: dict, avg: Mapping, rng: random.Random,
                now: float, protected: bool = False) -> dict:
    """推进一千年：绝灵压制加深 + 自然灾厄 + 位面损失（或护身符抵消）。"""
    era = state["era"]
    era["index"] = int(era.get("index", 0)) + 1
    era["years"] = int(era.get("years", 0)) + NATURAL_YEAR
    era["suppression"] = min(0.5, round(0.05 * era["index"], 4))
    spawned = spawn_wave(state, era["years"], rng.randint(1, 10), avg, rng, source="natural")
    if protected:
        loss = {"year": era["years"], "plane": "—", "damage": 0, "note": "星宇护身符护持，位面无恙"}
    else:
        plane = rng.choice(PLANE_NAMES)
        loss = {
            "year": era["years"],
            "plane": plane,
            "damage": rng.randint(1, 5),
            "note": f"绝灵潮汐冲蚀【{plane}】，灵脉受损 {rng.randint(1, 5)} 成",
        }
    era["losses"] = (list(era.get("losses") or []) + [loss])[-12:]
    era["events"] = (list(era.get("events") or []) + [
        {"at": float(now), "text": f"第 {era['index']} 纪元（第 {era['years']} 年）："
                                   f"绝灵压制 {int(era['suppression'] * 100)}%，"
                                   f"新增灾厄 {len(spawned)} 尊。"}
    ])[-12:]
    return {"index": era["index"], "years": era["years"],
            "suppression": era["suppression"], "loss": loss, "spawned": len(spawned)}


def reward_multiplier(doc: Any, state: Mapping, now: float) -> float:
    """绝灵压制对灾厄奖励的折算；星宇护身符（ext["era_charm"]）按纪元豁免。"""
    suppression = suppression_of(state)
    charm_until = int(doc.ext.get("era_charm_until") or 0)
    if charm_until >= int(state["era"].get("index", 0)):
        return 1.0
    return max(0.5, 1.0 - suppression)
