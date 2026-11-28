"""Pinned original rules for arrival encounters during plane travel."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

SUPREME_NOTICE_CHANCE = {"body": 0.50, "low": 0.25, "high": 0.05}
SUPREME_EXEMPT_PHYSIQUES = frozenset({"圣体", "霸体", "圣体道胎", "混沌体"})
SUPREME_NOTICE_THRESHOLD = 10
SUPREME_WARNINGS = {
    1: "虚空深处似有一道冰冷眸光扫过，位面阵纹已被某位禁区至尊记住。",
    2: "北斗生命禁区传来帝兵复苏之音，那道目光再次锁定了你的穿梭轨迹。",
    3: "禁区方向垂落一缕杀意，星路上被推演的气息越来越重。",
    4: "不死山与光暗禁区同时亮起，注视已如附骨之疽。",
    5: "你的每一次穿梭都在禁区眼中留下痕迹，有至尊开始推算你的落脚点。",
    6: "帝兵锋芒隔着星域遥遥锁定，虚空深处的杀机已凝成实质。",
    7: "数道至尊神念交织成网，你每一次跨界都要穿过他们的视线。",
    8: "禁区震颤，有古皇在沉睡中睁眼——留给你的时间不多了。",
    9: "最后一次警告：下一次穿梭，禁区至尊将横断星路截杀于界壁之间。",
}
FORBIDDEN_SUPREMES = (
    {"name": "石皇", "weight": 45, "root": {"name": "大圆满圣灵皇体", "type": "大成圣体", "法球倍率": 3.4, "攻击": 4.5, "防御": 5.2, "生命": 5.8}, "techniques": ("石皇经·天荒镇世", "行字秘·极尽", "者字秘"), "equipment": "不死山古皇战装", "weapon": "天荒戟"},
    {"name": "光暗至尊", "weight": 30, "root": {"name": "光暗双生至尊体", "type": "光暗皇体", "法球倍率": 3.4, "攻击": 4, "防御": 4, "生命": 4.9}, "techniques": ("光暗古经·两仪葬界", "维宙星灭诀", "皆字秘"), "equipment": "光暗古皇战装", "weapon": "光暗至尊器"},
    {"name": "神墟之主", "weight": 15, "root": {"name": "神墟万域古皇体", "type": "古皇体", "法球倍率": 3.3, "攻击": 3.7, "防御": 4.7, "生命": 5.1}, "techniques": ("神墟古经·万域放逐", "永恒的放逐", "临字秘"), "equipment": "神墟古皇战装", "weapon": "神墟古皇兵"},
    {"name": "长生天尊", "weight": 5, "root": {"name": "长生仙体·不死药身", "type": "至尊体", "法球倍率": 3.2, "攻击": 3.6, "防御": 4.2, "生命": 4.8}, "techniques": ("长生天功·万古不朽", "者字秘", "长生仙光·极尽升华"), "equipment": "仙陵长生战装", "weapon": "长生剑"},
    {"name": "轮回之主", "weight": 3, "root": {"name": "九转轮回至尊体", "type": "至尊体", "法球倍率": 3.1, "攻击": 3.8, "防御": 4.1, "生命": 4.6}, "techniques": ("轮回古经·九世葬天", "六道轮回拳", "者字秘"), "equipment": "轮回海至尊战装", "weapon": "轮回刀"},
    {"name": "弃天至尊", "weight": 2, "root": {"name": "弃天灭世至尊体", "type": "至尊体", "法球倍率": 3.5, "攻击": 4.2, "防御": 4.3, "生命": 5.2}, "techniques": ("弃天古经·灭世劫", "皆字秘", "弃天九斩"), "equipment": "弃天至尊战装", "weapon": "弃天神矛"},
)
POWER_GEAR_BASE = {"攻击": 120_000_000, "防御": 120_000_000, "血量": 180_000_000}
POWER_WEAPON_BASE = {"攻击": 50_000_000, "防御": 50_000_000, "血量": 50_000_000, "全属性": 12}

# TravelTask's own six hatred ranges and ambush table; these intentionally do not
# use core.tianjiao.level_of, whose bands serve the normal world-boss loop.
AMBUSH_LEVELS = ((0, 0, "陌生", 0.00), (1, 30, "注意", 0.05),
                 (31, 60, "敌视", 0.10), (61, 120, "仇恨", 0.20),
                 (121, 200, "死敌", 0.35), (201, math.inf, "不死不休", 0.50))
AMBUSH_TYPES = {
    "陌生": (("单人偷袭", 100, 0),),
    "注意": (("单人偷袭", 70, 0), ("带人围攻", 30, 15)),
    "敌视": (("单人偷袭", 40, 0), ("带人围攻", 50, 30), ("大阵围困", 10, 45)),
    "仇恨": (("单人偷袭", 20, 0), ("带人围攻", 50, 60), ("大阵围困", 30, 80)),
    "死敌": (("带人围攻", 40, 100), ("大阵围困", 60, 150)),
    "不死不休": (("大阵围困", 100, 200),),
}
AMBUSH_MULTIPLIER = {"单人偷袭": 0.8, "带人围攻": 0.6, "大阵围困": 0.4}
FORMATION_BONUS = {"攻击": 1.5, "防御": 2.0, "血量": 3.0}
FORMATION_NAMES = ("九幽锁魂阵", "万剑诛仙阵", "阴阳逆乱阵", "虚空囚笼阵", "血海轮回阵", "天罡地煞阵", "五行灭绝阵", "星辰陨落阵", "混沌灭世阵")


def _legacy(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return {}
    raw = ext.get("legacy_source")
    if not isinstance(raw, dict):
        raw = {}
        ext["legacy_source"] = raw
    return raw


def _integer(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _weighted(rows: tuple[dict, ...], rng: Any) -> dict:
    total = sum(int(row["weight"]) for row in rows)
    roll = min(1.0 - math.ulp(1.0), max(0.0, float(rng.random()))) * total
    for row in rows:
        roll -= int(row["weight"])
        if roll < 0:
            return row
    return rows[-1]


def forbidden_supreme_notice(doc: Any, travel: Mapping, rng: Any) -> dict | None:
    if travel.get("travel_protected"):
        return None
    if "遮天位面" not in (str(travel.get("from") or ""), str(travel.get("to") or "")):
        return None
    from . import extra_cultivation
    legacy = _legacy(doc)
    mijing = extra_cultivation.level_of(doc, "mijing")
    root = doc.ext.get("linggen") if isinstance(doc.ext.get("linggen"), Mapping) else {}
    if not root:
        root = legacy.get("灵根") if isinstance(legacy.get("灵根"), Mapping) else {}
    if mijing >= 16:
        return {"kind": "exempt", "message": "你横渡遮天位面，万古禁区一片死寂——大帝意志所及，无人敢窥伺你的星路。"}
    if mijing >= 15 and str(root.get("type") or "") in SUPREME_EXEMPT_PHYSIQUES:
        return {"kind": "exempt", "message": "你撕裂界壁的气息让禁区至尊侧目，但感应到你的体质与帝道之威后，那道冰冷眸光悄然退散。"}
    tier = str(travel.get("token_tier") or "low") if travel.get("used_token") else "body"
    chance = SUPREME_NOTICE_CHANCE.get(tier, SUPREME_NOTICE_CHANCE["low"])
    if float(rng.random()) >= chance:
        return None
    count = min(SUPREME_NOTICE_THRESHOLD, _integer(legacy.get("禁区至尊注视")) + 1)
    legacy["禁区至尊注视"] = count
    if count >= SUPREME_NOTICE_THRESHOLD:
        supreme = _weighted(FORBIDDEN_SUPREMES, rng)
        return {"kind": "intercept", "count": count, "supreme": supreme}
    return {"kind": "notice", "count": count, "message": SUPREME_WARNINGS[count]}


def resolve_forbidden_attention(doc: Any, kind: str) -> None:
    legacy = _legacy(doc)
    legacy["禁区至尊注视"] = 0
    if kind == "victory":
        legacy["击退禁区至尊次数"] = _integer(legacy.get("击退禁区至尊次数")) + 1
    elif kind == "defeat":
        legacy["禁区至尊堵截次数"] = _integer(legacy.get("禁区至尊堵截次数")) + 1


def forbidden_supreme_stats(supreme: Mapping, tables: Mapping[str, Any]) -> dict[str, Any]:
    def max_row(rows):
        valid = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
        return max(valid, key=lambda row: _integer(row.get("level_id")), default={})
    def level_row(rows, level_id):
        return next((row for row in rows if isinstance(row, Mapping)
                     and _integer(row.get("level_id")) == level_id), {}) if isinstance(rows, list) else {}
    cultivation = max_row(tables.get("Level_list"))
    physique = max_row(tables.get("LevelMax_list"))
    secret = level_row(tables.get("Levelmijing_list"), 16)
    ancient = level_row(tables.get("xiangujinshi_list"), 1)
    root = supreme.get("root") if isinstance(supreme.get("root"), Mapping) else {}
    all_attribute = 75_000_000_000
    gear_multiplier = 150
    weapon_realm = {key: _integer(secret.get(f"基础{key}")) + _integer(ancient.get(f"基础{key}"))
                    for key in ("攻击", "防御", "血量")}
    def stat(key: str) -> int:
        base = (_integer(cultivation.get(f"基础{key}")) + _integer(physique.get(f"基础{key}"))
                + _integer(secret.get(f"基础{key}")) + _integer(ancient.get(f"基础{key}"))
                + all_attribute)
        return int(base * (1 + float(root.get(key, 0) or 0))
                   + (POWER_GEAR_BASE[key] + POWER_WEAPON_BASE[key]) * gear_multiplier
                   + weapon_realm[key] * POWER_WEAPON_BASE["全属性"] * gear_multiplier)
    return {"name": str(supreme.get("name") or "禁区至尊"), "atk": max(1, stat("攻击")),
            "defense": max(1, stat("防御")), "hp": max(1, stat("血量")),
            "bao": max(0.0, float(cultivation.get("基础暴击", 0) or 0)
                      + float(physique.get("基础暴击", 0) or 0)),
            "speed": 100 + 16 * 50 + 1 * 50, "crit_damage": 2.5,
            "root": dict(root), "techniques": tuple(supreme.get("techniques") or ())}


def _hatred_level(value: int) -> tuple[str, float]:
    for low, high, name, bonus in AMBUSH_LEVELS:
        if low <= value <= high:
            return name, bonus
    return "陌生", 0.0


def select_tianjiao_ambush(doc: Any, travel: Mapping, rows: list[Mapping],
                            world: Mapping, now: float, rng: Any) -> dict | None:
    if travel.get("travel_protected"):
        return None
    offer = doc.ext.get("tianjiao_offer")
    if isinstance(offer, Mapping) and _integer(offer.get("until")) > now:
        return None
    fear = doc.ext.get("tianjiao_fear")
    fear = fear if isinstance(fear, Mapping) else {}
    bosses = world.get("bosses") if isinstance(world, Mapping) else {}
    bosses = bosses if isinstance(bosses, Mapping) else {}
    from . import tianjiao
    candidates = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or row.get("名号") or "").strip()
        if not name:
            continue
        hatred = tianjiao.hatred_of(doc, name)
        if hatred <= 0:
            continue
        if _integer(fear.get(name)) > now:
            continue
        boss = bosses.get(name) if isinstance(bosses.get(name), Mapping) else {}
        if tianjiao.blocked_until(boss) > now or tianjiao.hp_pct_of(boss) <= 0:
            continue
        candidates.append((row, hatred, max(1, math.ceil(hatred / 10))))
    if not candidates:
        return None
    total_weight = sum(weight for _row, _hatred, weight in candidates)
    roll = min(1.0 - math.ulp(1.0), max(0.0, float(rng.random()))) * total_weight
    selected = candidates[-1]
    for candidate in candidates:
        roll -= candidate[2]
        if roll < 0:
            selected = candidate
            break
    row, hatred, _weight = selected
    level, bonus = _hatred_level(hatred)
    if float(rng.random()) > 0.15 + bonus:
        return None
    valid_types = [(kind, weight) for kind, weight, min_hatred in AMBUSH_TYPES[level]
                   if hatred >= min_hatred]
    if not valid_types:
        return None
    type_total = sum(weight for _kind, weight in valid_types)
    type_roll = min(1.0 - math.ulp(1.0), max(0.0, float(rng.random()))) * type_total
    ambush_type = valid_types[-1][0]
    for kind, weight in valid_types:
        type_roll -= weight
        if type_roll <= 0:
            ambush_type = kind
            break
    plan = {"kind": "ambush", "row": row, "name": str(row.get("name") or row.get("名号")),
            "hatred": hatred, "hatred_level": level, "ambush_type": ambush_type,
            "multiplier": AMBUSH_MULTIPLIER[ambush_type]}
    if ambush_type == "带人围攻":
        plan["minions"] = int(rng.randint(2, 5))
    elif ambush_type == "大阵围困":
        plan["minions"] = int(rng.randint(5, 9))
        plan["formation"] = str(rng.choice(FORMATION_NAMES))
    return plan
