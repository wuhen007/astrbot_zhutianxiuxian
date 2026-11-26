"""副本目录（W7-5b）：把 #禁地 / #仙境 / #下界八域 / #九天十地 / #探索仙府 的查询
接到**真实进入与掉落**，而不是只列一行说明。

数据：
- `item/副本/禁地列表.json`(4) / `仙境列表.json`(12) / `下界八域列表.json` / `九天十地.json`(2)
- `Timelimit/限定仙府.json`(2)
条目字段：name / Grade / Price / experience / shouyuan / one·two·three（掉落池）/ Best

本移植口径：
- 门槛按 Price 分档（越贵越凶险），进入交 `Price × 2%` 灵石（最低 5000）
- 地图系数由 Price 推算：`0.6 + 0.7×log10(Price/5万)`，钳在 0.6~3.2（与 secret.PLACES 同量级）
- 掉落池 = one+two+three 合并；缺 稀有度 的按所在档补 2/4/6
- 撤离结算时按「探明层数/10」折算副本表里的 experience / shouyuan

shortcut：原版副本的剧情节点、多阶段 Boss、法身双人同探未移植；掉落走 secret 的程序化遭遇。
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping
from typing import Any

# 与 core/extras.DUNGEON_TABLES 同一批表；此处按「可进入顺序」排序
TABLES: dict[str, str] = {
    "仙府": "Timelimit/限定仙府",
    "禁地": "item/副本/禁地列表",
    "仙境": "item/副本/仙境列表",
    "下界八域": "item/副本/下界八域列表",
    "九天十地": "item/副本/九天十地",
}

FEE_RATE = 0.02
FEE_MIN = 5_000
# (Price 上限, 境界门槛) —— 未达到则不许进
GATE_TIERS: tuple[tuple[int, int], ...] = (
    (100_000, 0),
    (1_000_000, 12),
    (10_000_000, 25),
    (100_000_000, 38),
    (10 ** 18, 50),
)
RARITY_BY_TIER = {"one": 2, "two": 4, "three": 6}

# 原版 SecretPlace 的定时历练入口。此目录独立于逐层寻宝 TABLES，
# 避免旧 #降临秘境 命令把定时玩法悄悄变成新的随机地层玩法。
ORIGINAL_TABLES: dict[str, str] = {
    "秘境": "item/副本/地点列表",
    "禁地": "item/副本/禁地列表",
    "仙境": "item/副本/仙境列表",
    "下界八域": "item/副本/下界八域列表",
    "九天十地": "item/副本/九天十地",
    "遮天位面": "item/副本/遮天宇宙列表",
    "界海": "item/副本/界海列表",
    "仙府": "Timelimit/限定仙府",
}

# 月份及未衰减费用取原版 config/xiuxian/xiuxian.yaml 和 SecretPlace.js。
# 仙府与长河初始仍随机抽图，数据条目只作为实际战斗/掉落目标。
ORIGINAL_ROUTE_RULES: dict[str, dict[str, Any]] = {
    "秘境": {"minutes": 7, "plane": "凡间"},
    "禁地": {"minutes": 7, "min_level": 22},
    "仙境": {"minutes": 7, "min_level": 42, "plane": "仙界"},
    "下界八域": {"minutes": 10, "plane": "下界八域"},
    "九天十地": {"minutes": 10, "plane": "九天十地"},
    "遮天位面": {"minutes": 10, "plane": "遮天位面", "min_level": 22},
    "界海": {"minutes": 30, "plane": "界海"},
    "上苍之上": {"minutes": 60, "plane": "上苍之上"},
    "仙府": {"minutes": 7, "min_level": 21, "fixed_price": 50_000,
              "experience_cost": 100_000},
}
ORIGINAL_PLACE_LEVELS: dict[str, int] = {
    "永恒海": 55,
    "永恒海尽头": 63,
    "诸神黄昏·旧神界": 46,
    "始源·混沌初开之地": 64,
    "接引古殿": 18,
    "终极古地": 21,
    "鲲鹏巢": 0,
    "百断山脉": 0,
    "杀神崖": 50,
}


SETTLEMENT_CARD_SECONDS = {
    "帝品秘境结算卡": 1800,
    "圣品秘境结算卡": 600,
    "仙品秘境结算卡": 300,
    "灵品秘境结算卡": 180,
    "玄品秘境结算卡": 60,
    "凡品秘境结算卡": 30,
}


def allocate_settlement_cards(inventory: Mapping[str, int], remaining_seconds: int
                             ) -> tuple[dict[str, int], int]:
    remaining = max(0, int(remaining_seconds))
    used: dict[str, int] = {}
    total = 0
    for name, seconds in sorted(SETTLEMENT_CARD_SECONDS.items(), key=lambda row: row[1]):
        owned = max(0, int(inventory.get(name, 0) or 0))
        count = min(owned, remaining // seconds)
        if count <= 0:
            continue
        used[name] = count
        reduction = count * seconds
        total += reduction
        remaining -= reduction
    return used, total


def accelerate_original_expedition(action: Mapping[str, Any], requested_seconds: int,
                                   now: float) -> tuple[dict[str, Any], int]:
    """Shorten the existing timed action deadline without changing its reward seed."""
    updated = copy.deepcopy(dict(action))
    try:
        ends_at = float(updated.get("ends_at") or 0)
        now = float(now)
        requested = max(0, int(requested_seconds))
    except (TypeError, ValueError, OverflowError):
        return updated, 0
    if ends_at <= now or requested <= 0:
        return updated, 0
    reduced = min(requested, max(0, int(ends_at - now)))
    updated["ends_at"] = max(now, ends_at - reduced)
    if "end_time" in updated:
        updated["end_time"] = updated["ends_at"]
    updated["remaining_time"] = max(0.0, updated["ends_at"] - now)
    if "next_settle_time" in updated:
        updated["next_settle_time"] = min(float(updated["next_settle_time"] or updated["ends_at"]),
                                           updated["ends_at"])
    return updated, reduced


def original_duration_minutes(doc: Any, kind: str, daofa_active: bool = False,
                              extra_reduction: float = 0.0,
                              configured_minutes: int | None = None) -> int:
    """config/xiuxian CD 和 SecretPlace.calculateTimeReduction 的基础历练计时。"""
    rule = ORIGINAL_ROUTE_RULES.get(str(kind), {})
    base = max(0, int(configured_minutes if configured_minutes is not None
                      else rule.get("minutes", 0)))
    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source", {}) if isinstance(ext, Mapping) else {}
    legacy = legacy if isinstance(legacy, Mapping) else {}
    learned = legacy.get("学习的功法") or ext.get("gongfa") or []
    learned = {str(name) for name in learned} if isinstance(learned, (list, tuple, set)) else set()
    from . import extra_cultivation
    secret_level = extra_cultivation.level_of(doc, "mijing")
    reduction = 0
    if "行字秘" in learned:
        reduction = 2 + int(secret_level >= 9) + int(secret_level >= 16)
    elif "天璇步法" in learned:
        reduction = 1
    reduction += 2 if daofa_active else 0
    reduction += max(0, int(extra_reduction))
    return max(0, base - reduction)


def begin_original_expedition(
    doc: Any,
    name: str,
    kind: str,
    content: Callable[[str], Any],
    rng: random.Random,
    now: float,
    *,
    plane: str | None = None,
    free_entry: bool = False,
    pass_available: bool = False,
    coupon_available: bool = False,
    partner_intimacy: int | None = None,
    daofa_active: bool = False,
    extra_reduction: float = 0.0,
    configured_minutes: int | None = None,
    experience_discount: float = 1.0,
) -> tuple[bool, str, dict | None]:
    """对 bundled original-place rows 预检并建立带怪物快照的定时历练行动。"""
    from . import secret

    palace_random = kind == "仙府" and str(name).strip() in ("", "随机", "地图")
    map_place = str(name).strip()
    fake_map = False
    map_fee = 0
    if palace_random:
        map_roll = rng.random()
        fake_map = rng.random() > 0.9
        map_place = "无欲天仙" if map_roll < 0.5 else "仙遗之地"
        # 原版 10% 假地图在门槛/入府价格核对前收走地图费并结束。
        if fake_map:
            map_fee = 0 if pass_available or free_entry else 50_000
            if int(getattr(doc, "stones", 0) or 0) < map_fee:
                return False, f"购买地图需 {map_fee:,} 灵石。", None
            doc.stones = int(doc.stones) - map_fee
            return False, f"仙府地图显示「{map_place}」，实为游乐场，损失 {map_fee:,} 灵石后未能入府。", None
        name = map_place

    found = original_find(name, content)
    if not found or found[1] != str(kind):
        return False, f"没有找到「{name}」的{kind}地点。", None
    row, _kind = found
    quote = original_entry_quote(doc, row, kind, plane,
                                free_entry=free_entry,
                                pass_available=(pass_available or kind == "仙府"),
                                coupon_available=coupon_available,
                                partner_intimacy=partner_intimacy,
                                experience_discount=experience_discount)
    if not quote["ok"]:
        return False, str(quote.get("reason") or "当前条件不满足。"), None
    if kind == "仙府":
        # 成功地图只收地点 Price；50,000 灵石只在原版的假地图分支扣除。
        quote["price"] = 0 if free_entry or pass_available else int(row.get("Price", 0) or 0)
        quote["experience"] = 0 if free_entry or pass_available else 100_000
        quote["xueqi"] = 0
        quote["shouyuan"] = 0
        if int(getattr(doc, "stones", 0) or 0) < int(quote["price"]):
            return False, f"仙府入府需 {int(quote['price']):,} 灵石。", None
        if int(getattr(doc, "exp", 0) or 0) < int(quote["experience"]):
            return False, f"进入仙府需积累 {int(quote['experience']):,} 修为。", None
    route = quote.get("route") or {}
    minutes = original_duration_minutes(doc, kind, daofa_active, extra_reduction,
                                         configured_minutes or int(route.get("minutes", 0) or 0))
    seconds = minutes * 60
    duration_multiplier = 1.0
    try:
        from . import timed_action
        duration_multiplier = timed_action.multiplier(doc, float(now))
    except (ImportError, TypeError, ValueError):
        pass
    expires = float(now) + seconds * duration_multiplier
    place_id = row.get("id")
    xianfu_tier = int(row.get("XF", -1)) if row.get("XF") is not None else -1
    encounter = secret.original_monster(map_place, rng, content, xianfu_tier,
                                        int(place_id) if place_id is not None else None)
    action = secret.original_session(map_place, kind, row, encounter,
                                     float(now), expires,
                                     f"{getattr(doc, 'uid', '')}:{kind}:{name}:{float(now)}")
    action["settlement_id"] = str(action.get("seed") or f"{getattr(doc, 'uid', '')}:{float(now)}")
    action["loot"] = secret.original_drop(row, rng)
    action["encounter_table"] = secret.original_monster_table(
        map_place, xianfu_tier, int(place_id) if place_id is not None else None)
    action["price_paid"] = int(quote.get("price", 0) or 0)
    action["minutes"] = minutes
    action["expected_plane"] = str(route.get("plane") or "")
    action["experience_paid"] = int(quote.get("experience", 0) or 0)
    action["xueqi_paid"] = int(quote.get("xueqi", 0) or 0)
    action["shouyuan_paid"] = int(quote.get("shouyuan", 0) or 0)
    doc.stones = int(doc.stones) - action["price_paid"]
    doc.exp = max(0, int(doc.exp) - action["experience_paid"])
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    ext["xueqi"] = max(0, int(ext.get("xueqi", 0) or 0) - action["xueqi_paid"])
    if action["shouyuan_paid"]:
        from .lifespan import spend as spend_lifespan
        spend_lifespan(doc, action["shouyuan_paid"])
    ext["original_expedition"] = action
    ext["last_dungeon"] = map_place
    doc.ext = ext
    doc.state = "秘境中"
    return True, (f"已开始「{map_place}」历练，预计 {minutes} 分钟后归来；"
                  f"消耗 {action['price_paid']:,} 灵石、{action['experience_paid']:,} 修为、"
                  f"{action['xueqi_paid']:,} 血气、{action['shouyuan_paid']:,} 寿元。"), action


def original_palace_map(rng: random.Random) -> dict[str, Any]:
    """抽原版 #探索仙府 两张地图，并保留冲水堂 10% 假图分支。"""
    place = rng.choice(("无欲天仙", "仙遗之地"))
    return {"place": place, "fake_map": rng.random() > 0.9,
            "map_cost": 50_000}


def original_find(name: str, content: Callable[[str], Any]) -> tuple[dict, str] | None:
    """按原版一次性历练地点名精确查表，返回 (地点, 路线类型)。"""
    target = (name or "").strip()
    if not target:
        return None
    for kind, path in ORIGINAL_TABLES.items():
        for row in (content(path) or []):
            if isinstance(row, Mapping) and str(row.get("name") or "") == target:
                return dict(row), kind
    return None


def original_entry_quote(
    doc: Any, row: Mapping, kind: str, plane: str | None = None,
    *, free_entry: bool = False, pass_available: bool = False,
    coupon_available: bool = False, partner_intimacy: int | None = None,
) -> dict[str, Any]:
    """核对原版定时历练所需的境界、当前位面与费用，不扣款/写档。

    境界 ID 是原版 1-based，所以接口统一比较 `realm_index + 1`。
    上苍之上的独立多类资源账单由 Shangcang 模块负责；此处仅返回其路线与基础时长。
    """
    rule = ORIGINAL_ROUTE_RULES.get(str(kind))
    if not rule or not row:
        return {"ok": False, "reason": "地点配置不存在。"}
    realm_id = max(1, int(getattr(doc, "realm_index", 0) or 0) + 1)
    body_id = max(1, int(getattr(doc, "physique_index", 0) or 0) + 1)
    place_name = str(row.get("name") or "")
    minimum = int(rule.get("min_level", 1) or 1)
    place_gate = ORIGINAL_PLACE_LEVELS.get(place_name)
    if kind == "禁地":
        minimum = max(minimum, 22)
        if place_name == "始源·混沌初开之地":
            minimum = 64
        elif place_name == "诸神黄昏·旧神界":
            minimum = 46
    if kind == "遮天位面" and place_name == "诸神黄昏·旧神界":
        minimum = max(minimum, 46)
    if kind == "秘境" and place_gate is not None and place_name in ("永恒海", "永恒海尽头"):
        minimum = max(minimum, place_gate)
    if kind == "界海" and place_gate is not None and place_name in ("接引古殿", "终极古地"):
        minimum = max(minimum, place_gate)
    if minimum > 1 and realm_id < minimum:
        return {"ok": False, "reason": f"「{place_name}」需练气境界达到第 {minimum} 境。",
                "minimum_level": minimum}
    if place_name in ("鲲鹏巢", "百断山脉"):
        xiangu_level = extra_cultivation.level_of(doc, "xiangu")
        max_xiangu = 4 if place_name == "鲲鹏巢" else 3
        if xiangu_level > max_xiangu:
            return {"ok": False, "reason": f"「{place_name}」仅开放给仙古第 {max_xiangu} 境及以下修士。"}
    expected_plane = str(rule.get("plane") or "")
    if expected_plane and plane and expected_plane != plane:
        return {"ok": False, "reason": f"请先穿梭到「{expected_plane}」再进入「{place_name}」。",
                "expected_plane": expected_plane}
    if kind == "上苍之上":
        return {"ok": True, "kind": kind, "place": place_name,
                "route": dict(rule), "minutes": int(rule["minutes"])}

    current = max(0, int(getattr(doc, "stones", 0) or 0))
    price = int(rule.get("fixed_price", row.get("Price", 0)) or 0)
    if kind == "仙境" and place_name == "杀神崖":
        # 原版杀神崖通行证免票；通用仙境优惠券在其余地点减半。
        price = 0 if pass_available else (price // 2 if coupon_available else price)
    elif kind == "仙境" and coupon_available:
        price //= 2
    if free_entry:
        price = 0
    elif kind == "仙府" and pass_available:
        price = 0
    experience = int(rule.get("experience_cost", row.get("experience", 0)) or 0)
    if free_entry and kind == "仙府":
        experience = 0
    if not free_entry:
        experience = int(experience * min(1.0, max(0.0, float(experience_discount))))
    xueqi = (experience if kind in ("下界八域", "九天十地")
             or (kind in ("禁地", "遮天位面")
                 and str(row.get("Grade") or "") == "生命禁区") else 0)
    lifespan = int(row.get("shouyuan", 0) or 0) if kind in {
        "秘境", "禁地", "仙境", "下界八域", "九天十地"} else 0
    # 位面天骄独占专属零费用位面等规则由上层依据完整装备/体系状态判断。
    shortages = []
    if current < price:
        shortages.append(f"灵石不足：需 {price:,}，当前 {current:,}。")
    if max(0, int(getattr(doc, "exp", 0) or 0)) < experience:
        shortages.append(f"修为不足：需 {experience:,}。")
    blood = int((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0)
    if blood < xueqi:
        shortages.append(f"血气不足：需 {xueqi:,}。")
    ext = getattr(doc, "ext", {}) or {}
    current_lifespan = int(ext.get("shouyuan", (int(getattr(doc, "realm_index", 0) or 0) + 1) * 500)
                            or 0) if isinstance(ext, Mapping) else 0
    if current_lifespan < lifespan:
        shortages.append(f"寿元不足：需 {lifespan:,}。")
    if shortages:
        return {"ok": False, "reason": "\n".join(shortages), "price": price,
                "experience": experience, "xueqi": xueqi, "shouyuan": lifespan}
    if kind == "秘境" and place_name == "桃花岛":
        if partner_intimacy is None:
            return {"ok": False, "reason": "桃花岛仅接纳已结为道侣且亲密度达到 550 的修士。"}
        if int(partner_intimacy) < 550:
            return {"ok": False, "reason": f"桃花岛需要道侣亲密度至少 550（当前 {int(partner_intimacy)}）。"}
    # 原版 #仙境 的专属门槛。
    if kind == "仙境" and place_name in ("诸天", "真魔殿", "光阴之外"):
        root = (getattr(doc, "ext", {}) or {}).get("linggen") or {}
        legacy = (getattr(doc, "ext", {}) or {}).get("legacy_source") or {}
        root = root if isinstance(root, Mapping) else {}
        legacy = legacy if isinstance(legacy, Mapping) else {}
        root_type = str(root.get("type") or legacy.get("灵根", {}).get("type") or "")
        root_name = str(root.get("name") or legacy.get("灵根", {}).get("name") or "")
        is_exempt = (root_name in ("九转轮回体", "命运神道体") or root_type == "神魔体"
                     if place_name == "诸天" else
                     root_name in ("九重魔功", "极道天魔") or root_type == "神魔体"
                     if place_name == "真魔殿" else root_type in ("命运", "天魔", "神魔体"))
        if not is_exempt:
            return {"ok": False, "reason": f"「{place_name}」仅接纳对应的特殊灵根传承。"}
    return {"ok": True, "kind": kind, "place": place_name, "price": price,
            "experience": experience, "xueqi": xueqi, "shouyuan": lifespan,
            "route": dict(rule), "minutes": int(rule["minutes"])}


def find(name: str, content: Callable[[str], Any]) -> tuple[dict, str] | None:
    """按副本名在五张表里查找，返回 (条目, 类别)。"""
    target = (name or "").strip()
    if not target:
        return None
    for kind, path in TABLES.items():
        for row in (content(path) or []):
            if isinstance(row, Mapping) and str(row.get("name")) == target:
                return dict(row), kind
    return None


def gate_of(price: int) -> int:
    price = max(0, int(price))
    for limit, gate in GATE_TIERS:
        if price < limit:
            return gate
    return GATE_TIERS[-1][1]


def fee_of(price: int) -> int:
    return max(FEE_MIN, int(int(price) * FEE_RATE))


def factor_of(price: int) -> float:
    price = max(1, int(price))
    raw = 0.6 + 0.7 * math.log10(price / 50_000)
    return round(min(3.2, max(0.6, raw)), 2)


def pool_of(row: Mapping) -> list[dict]:
    """合并 one/two/three 掉落池，补齐稀有度供 secret.roll_drop 过滤。"""
    pool: list[dict] = []
    seen: set[str] = set()
    for tier in ("one", "two", "three"):
        for item in (row.get(tier) or []):
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            try:
                rarity = int(item.get("稀有度") or 0)
            except (TypeError, ValueError):
                rarity = 0
            pool.append({
                "name": name,
                "class": item.get("class") or "道具",
                "稀有度": rarity or RARITY_BY_TIER[tier],
            })
    return pool


def rewards_of(row: Mapping, floor: int) -> tuple[int, int]:
    """撤离结算的额外修为/寿元：按「探明层数/10」折算（最多全额）。"""
    ratio = min(1.0, max(0.0, int(floor) / 10))
    exp = int(float(row.get("experience") or 0) * ratio)
    shou = int(float(row.get("shouyuan") or 0) * ratio)
    return exp, shou


def brief(row: Mapping) -> str:
    return (f"{row.get('name')}（{row.get('Grade') or '副本'}）｜"
            f"门票 {fee_of(row.get('Price', 0)):,} 灵石｜门槛第 {gate_of(row.get('Price', 0)) + 1} 境")
