"""源石坊赌石（对齐原版 apps/Game/stoneMarketRules.js）。

- 三档：外园（5 万灵石/日限 3/凶源伤 5%，池 COMMON）、地字号（30 万源石/日限 2/12%，池 GROUND）、
  天字号（200 万源石/日限 1/15%，池 SKY）
- 池权重与 ratio 直译；结算 sourceValue = 石价 × ratio ÷ 汇率（外园汇率 10，地/天 1）
- 名称/表面线索：70% 真实线索 + 30% 误导（原版 makeSignal 0.52 真，此处放宽便于体验）
- 源石为本插件自建数值货币（ext["yuanshi"]，原版为独立资源）
- 石园购买、每日免费勘石、天师辨伪、三种切法和层剥回购均持久保存在玩家源石状态。
- 简化：石师对决（五选三）、石相克制和地形对齐仍未移植；镇园石王为群本地每周事件，不共享跨群参与或状态。
"""

from __future__ import annotations
from .clock import day_key

import copy
import random
import time
from typing import Any, Mapping

GARDENS: dict[str, dict] = {
    "外园": {"currency": "灵石", "basePrice": 50_000, "dailyLimit": 3, "rate": 10,
            "sealCost": 5_000, "danger": 0.05},
    "地字号": {"currency": "源石", "basePrice": 300_000, "dailyLimit": 2, "rate": 1,
              "sealCost": 100_000, "danger": 0.12},
    "天字号": {"currency": "源石", "basePrice": 2_000_000, "dailyLimit": 1, "rate": 1,
              "sealCost": 500_000, "danger": 0.15, "cooldownHours": 20},
}

# (id, 名称, 权重, ratio, 物品名/None, danger)
POOL_COMMON = [
    ("empty", "空石", 2500, 0.0, None, False),
    ("mixed", "杂源", 3500, 0.5, None, False),
    ("pure", "纯净源", 2500, 1.0, None, False),
    ("different", "异种源", 1100, 2.0, None, False),
    ("divine", "神源", 350, 4.0, None, False),
    ("wonder", "绝世奇源", 50, 8.0, None, False),
]
POOL_GROUND = [
    ("empty", "空石", 2500, 0.0, None, False),
    ("ominous", "凶源", 800, 0.0, None, True),
    ("different", "异种源", 2700, 0.6, None, False),
    ("divine", "神源", 2500, 1.1, None, False),
    ("divine_liquid", "神源液", 1000, 0.0, "神源液", False),
    ("immortal_fragment", "仙金残块", 400, 0.0, "仙泪绿金残块", False),
    ("scripture_page", "羽化仙经残页", 100, 0.0, "羽化仙经残页", False),
]
POOL_SKY = [
    ("empty", "空石", 2300, 0.0, None, False),
    ("ominous", "凶源", 1500, 0.0, None, True),
    ("ancient", "封印太古生物", 700, 0.0, None, True),
    ("divine", "大块神源", 3000, 0.9, None, False),
    ("divine_liquid", "神源液", 1500, 0.0, "神源液", False),
    ("herb_king", "八万年药王", 600, 0.0, "万年何首乌", False),
    ("immortal_fragment", "仙金残块", 300, 0.0, "仙泪绿金残块", False),
    ("scripture_page", "羽化仙经残页", 100, 0.0, "羽化仙经残页", False),
    ("qitian", "欺天石", 40, 0.0, None, False),
]

POOLS = {"外园": POOL_COMMON, "地字号": POOL_GROUND, "天字号": POOL_SKY}
PRICE_FACTORS = [0.78, 0.9, 1.0, 1.15, 1.35]
STONES_PER_MARKET = 5
INSPECTS_PER_GARDEN = 2
HEAVENLY_CHECKS_PER_DAY = 1

SURFACES = {
    "empty": ["敲击声发散，石心似有空腔", "源气贴近石皮便悄然消散"],
    "mixed": ["裂隙凝有零星白霜", "石皮温凉交替，气机驳杂"],
    "pure": ["纹理向石心收束", "触手温润，气息绵长"],
    "different": ["石皮深处闪过异色霞光", "细纹明灭，隐有道韵流转"],
    "divine": ["靠近时气血微微共鸣", "石纹自行明灭，似有神曦沉浮"],
    "wonder": ["观之竟令神识微痛", "石中传来若有若无的生命律动"],
    "ominous": ["石皮存在封合痕迹", "阴气贴地不散"],
    "ancient": ["石中传来古老的心跳声", "封印纹路层层叠叠"],
    "divine_liquid": ["石皮湿润，缝隙中凝有金色露珠", "轻晃时石心似有水声"],
    "herb_king": ["石缝间透出草木清香", "石皮内似有根须舒展"],
    "immortal_fragment": ["石中偶有金属颤音", "石皮局部坚逾精铁"],
    "scripture_page": ["石纹如羽，似在缓慢舒展", "偶有诵经声从石心传出"],
    "qitian": ["天机混沌，望之不透", "所有源纹都在避开石心"],
}


def _date_key(ts: float) -> str:
    return day_key(ts)


def system_of(doc: Mapping) -> dict:
    """源石账户快照。除 amount/day 外还带回账本与冷却（W7-3），避免回写时被抹掉。"""
    y = doc.ext.get("yuanshi") if isinstance(doc.ext, Mapping) else None
    if isinstance(y, dict):
        out = copy.deepcopy(dict(y))
        out["amount"] = int(y.get("amount", 0) or 0)
        out["day"] = y.get("day") or {}
        out.setdefault("ledger", [])
        out.setdefault("cooldown", {})
        out.setdefault("empty_streak", 0)
        out.setdefault("cuts", 0)
        return out
    return {"amount": 0, "day": {}, "ledger": [], "cooldown": {}, "empty_streak": 0, "cuts": 0}


def daily_of(y: dict, now: float) -> dict:
    day = _date_key(now)
    d = y.get("day") if isinstance(y.get("day"), dict) else {}
    if d.get("date") != day:
        d = {"date": day, "count": {}}
    d.setdefault("count", {})
    y["day"] = d
    return d


def market_state(y: dict, now: float) -> dict:
    """Per-day source market state; a purchased stone survives a day rollover."""
    date = _date_key(now)
    current = y.get("market")
    if not isinstance(current, dict) or current.get("date") != date:
        pending = current.get("pending") if isinstance(current, dict) else None
        current = {
            "date": date, "active_garden": "外园", "purchased": {},
            "inspected": {}, "heavenly_check_used": False, "pending": pending,
        }
        y["market"] = current
    current.setdefault("active_garden", "外园")
    if not isinstance(current.get("purchased"), dict):
        current["purchased"] = {}
    if not isinstance(current.get("inspected"), dict):
        current["inspected"] = {}
    current.setdefault("heavenly_check_used", False)
    current.setdefault("pending", None)
    return current


def set_active_garden(y: dict, garden: str, now: float) -> None:
    if garden not in GARDENS:
        raise ValueError("石园仅支持外园、地字号或天字号。")
    market_state(y, now)["active_garden"] = garden


def make_market(doc_uid: str, garden: str, now: float, y: dict | None = None) -> list[dict]:
    """生成当日市场 5 块石头（种子 = uid+日期+档位，当天刷新前固定）。"""
    rng = random.Random(f"{doc_uid}:stone:{_date_key(now)}:{garden}")
    cfg = GARDENS[garden]
    pool = POOLS[garden]
    total_w = sum(x[2] for x in pool)
    factors = list(PRICE_FACTORS)
    rng.shuffle(factors)
    stones = []
    for i in range(STONES_PER_MARKET):
        roll = rng.uniform(0, total_w)
        acc = 0.0
        picked = pool[0]
        for entry in pool:
            acc += entry[2]
            if roll <= acc:
                picked = entry
                break
        price = int(cfg["basePrice"] * factors[i] / 1000) * 1000
        # 70% 真实表面线索，30% 误导
        surface_truthful = rng.random() < 0.7
        if surface_truthful:
            surface = rng.choice(SURFACES.get(picked[0], ["石皮寻常"]))
        else:
            decoy = rng.choice([e for e in pool if e[0] != picked[0]] or pool)
            surface = rng.choice(SURFACES.get(decoy[0], ["石皮寻常"]))
        stones.append({
            "no": i + 1, "price": price, "surface": surface,
            "outcome": picked[0], "name": picked[1], "ratio": picked[3],
            "item": picked[4], "danger": picked[5], "surface_truthful": surface_truthful,
        })
    if y is not None:
        state = market_state(y, now)
        purchased = set(state["purchased"].get(garden) or [])
        inspected = state["inspected"].get(garden) or {}
        for stone in stones:
            stone["purchased"] = stone["no"] in purchased
            stone["inspection"] = inspected.get(str(stone["no"]))
    return stones


def _stone_extra_cost(stone: Mapping, garden: str, method: str) -> dict[str, int | str]:
    cfg = GARDENS[garden]
    if method == "layered":
        return {"currency": cfg["currency"], "amount": (int(stone["price"]) + 9) // 10}
    if method == "sealed":
        return {"currency": "源石", "amount": int(cfg["sealCost"])}
    return {"currency": cfg["currency"], "amount": 0}


def _layered_preview(stone: Mapping, garden: str) -> dict:
    outcome = str(stone.get("outcome") or "")
    fragile = outcome in {"divine_liquid", "scripture_page"}
    dangerous = bool(stone.get("danger"))
    ratio = float(stone.get("ratio", 0) or 0)
    if not (dangerous or fragile or ratio >= 2):
        return {"needs_decision": False}
    rate = 1.05 if dangerous else 0.95 if ratio >= 4 else 0.8
    offer = int(int(stone["price"]) * rate)
    return {"needs_decision": True, "offer": offer, "currency": GARDENS[garden]["currency"],
            "anomaly": f"石中异象显现：{stone.get('name', '源石')}。"}


def _record_market_result(y: dict, pending: Mapping, now: float, *, source: int = 0,
                          item: str = "", empty: bool = False, extra: Mapping | None = None,
                          refund: int = 0, refund_currency: str = "") -> None:
    stone = pending["stone"]
    _record(y, str(pending["garden"]), int(pending["purchase_price"]),
            str(pending["purchase_currency"]), int(source),
            {"item": item, "name": stone.get("name", "")}, now, empty=empty,
            extra=extra, cut=not refund_currency, refund=refund, refund_currency=refund_currency)


def cut_pending(y: dict, method: str, occupation: str, stones_have: int,
                rng: random.Random, now: float,
                source_bonus: float = 0.0) -> tuple[bool, str, dict, dict]:
    """Apply a cut method to the persisted pending stone; mutations are returned in y/settlement."""
    state = market_state(y, now)
    pending = state.get("pending")
    if not isinstance(pending, dict) or pending.get("phase") != "choose":
        return False, "你当前没有等待开切的源石。", y, {}
    if method not in {"one", "layered", "sealed"}:
        return False, "切石方式无效。", y, {}
    if method == "sealed" and str(occupation or "") != "源天师":
        return False, "封源切法只有源天师能够施展。", y, {}

    stone = pending["stone"]
    garden = str(pending["garden"])
    extra = _stone_extra_cost(stone, garden, method)
    currency = str(extra["currency"])
    amount = int(extra["amount"])
    balance = int(stones_have) if currency == "灵石" else int(y.get("amount", 0) or 0)
    if balance < amount:
        return False, f"此切法还需 {amount:,}{currency}。", y, {}
    if currency == "源石":
        y["amount"] = balance - amount

    if method == "layered":
        preview = _layered_preview(stone, garden)
        if preview["needs_decision"]:
            state["pending"] = {**pending, "phase": "peeling", "offer": preview["offer"],
                                "offer_currency": preview["currency"], "method": method,
                                "extra_cost": extra}
            return True, (f"【层层剥石·异象初现】\n{preview['anomaly']}\n"
                          f"石坊愿以 {int(preview['offer']):,}{preview['currency']} 回购。\n"
                          "发送 #继续切 或 #石坊回购。"), y, {
                "finished": False, "extra_cost": extra, "gains": {},
            }

    return _finish_pending_cut(y, state, pending, method, extra, rng, now, source_bonus)


def continue_peeling(y: dict, rng: random.Random, now: float,
                     source_bonus: float = 0.0) -> tuple[bool, str, dict]:
    state = market_state(y, now)
    pending = state.get("pending")
    if not isinstance(pending, dict) or pending.get("phase") != "peeling":
        return False, "当前没有等待决断的切石异象。", {}
    ok, text, _, settlement = _finish_pending_cut(
        y, state, pending, "layered", pending.get("extra_cost") or {}, rng, now,
        source_bonus)
    return ok, text, settlement


def _finish_pending_cut(y: dict, state: dict, pending: dict, method: str,
                        extra: Mapping, rng: random.Random, now: float,
                        source_bonus: float = 0.0):
    stone = pending["stone"]
    garden = str(pending["garden"])
    cfg = GARDENS[garden]
    outcome = str(stone.get("outcome") or "")
    source = 0
    gains: dict[str, int] = {}
    damage_rate = 0.0
    damaged = suppressed = empty = False
    if stone.get("danger"):
        if method == "sealed":
            source = int(int(stone["price"]) * 0.35 / cfg["rate"])
            suppressed = True
        else:
            damage_rate = float(cfg["danger"])
    elif outcome == "empty":
        empty = True
    elif stone.get("item"):
        fragile = outcome in {"divine_liquid", "scripture_page"}
        damaged = method == "one" and fragile and rng.random() < 0.35
        if damaged:
            source = int(int(stone["price"]) * 0.15 / cfg["rate"])
        else:
            gains[str(stone["item"])] = 1
    else:
        source = int(int(stone["price"]) * float(stone.get("ratio", 0) or 0) / cfg["rate"])
    source = max(0, int(source * max(0.0, 1.0 + float(source_bonus or 0))))
    y["amount"] = int(y.get("amount", 0) or 0) + source
    _record_market_result(y, pending, now, source=source, item=next(iter(gains), ""),
                          empty=empty, extra=extra)
    state["pending"] = None
    lines = [f"【开石·{stone.get('name', '源石')}】", f"切石结果：{stone.get('name', '源石')}"]
    if source:
        lines.append(f"获得源石 {source:,} 斤。")
    if gains:
        lines.append("石心藏珍：" + "、".join(f"{name} ×{qty}" for name, qty in gains.items()) + "。")
    if damage_rate:
        lines.append(f"石中凶物反噬，损失气血上限的 {damage_rate:.0%}。")
    if suppressed:
        lines.append("封源术镇住凶机，从封印边缘剥离出少量源。")
    if damaged:
        lines.append("刀势过猛，脆弱仙珍损毁，只抢救出少量源。")
    if empty:
        lines.append("石心空空，未能切出任何源。")
    settlement = {"finished": True, "source": source, "gains": gains,
                  "damage_rate": damage_rate, "damaged": damaged,
                  "suppressed": suppressed, "empty": empty, "extra_cost": extra}
    return True, "\n".join(lines), y, settlement


def resolve_buyback(y: dict, now: float) -> tuple[bool, str, dict]:
    state = market_state(y, now)
    pending = state.get("pending")
    if not isinstance(pending, dict) or pending.get("phase") != "peeling":
        return False, "当前没有等待决断的切石异象。", {}
    currency = str(pending["offer_currency"])
    amount = int(pending["offer"])
    if currency == "源石":
        y["amount"] = int(y.get("amount", 0) or 0) + amount
    _record_market_result(y, pending, now, extra=pending.get("extra_cost"),
                          refund=amount, refund_currency=currency)
    state["pending"] = None
    return True, f"石坊回购已支付 {amount:,}{currency}。", {
        "currency": currency, "amount": amount,
    }


def inspect_market(y: dict, garden: str, stones: list[dict], no: int,
                   player: Mapping, now: float, rng: random.Random) -> tuple[bool, str, dict]:
    if garden not in GARDENS:
        return False, "石园档位无效。", y
    state = market_state(y, now)
    stone = next((item for item in stones if int(item.get("no", 0)) == int(no)), None)
    if stone is None:
        return False, f"没有第 {no} 块石头（1-{len(stones)}）。", y
    if stone.get("purchased") or int(no) in set(state["purchased"].get(garden) or []):
        return False, "这块源石已经离开石架。", y
    inspected = state["inspected"].setdefault(garden, {})
    if str(no) in inspected:
        return False, "这块源石今日已经勘验过。", y
    if len(inspected) >= INSPECTS_PER_GARDEN:
        return False, f"{garden}今日两次勘石机会已经用尽。", y

    occupation = str(player.get("occupation") or "")
    rank = {"源师": 1, "源地师": 2, "源天师": 3}.get(occupation, 0)
    level = int(player.get("occupation_level", 0) or 0)
    accuracy = min(0.85, {0: 0.55, 1: 0.65, 2: 0.75, 3: 0.8}[rank]
                   + (min(0.05, max(0, level - 1) * 0.001) if rank else 0))
    promising = not bool(stone.get("danger")) and float(stone.get("ratio") or 0) >= 1
    clues = ["源气内敛而绵长", "石心传来细微回响", "五行精气向内部汇聚"]
    poor = ["源纹在中途断裂", "石心气机外散", "内部波动驳杂而微弱"]
    lines = []
    for i in range(2 if rank else 1):
        truthful = rng.random() < accuracy
        pool = clues if (promising == truthful) else poor
        lines.append(f"线索{i + 1}：{rng.choice(pool)}")
    if rank >= 1:
        truthful = rng.random() < max(0.55, accuracy - 0.15)
        value_promising = promising if truthful else not promising
        lines.append("价值判断：" + ("价值约在石价上下，或有溢价" if value_promising else "价值多半低于石价"))
    if rank >= 2:
        aligned = rng.random() < accuracy
        dangerous = rng.random() < accuracy
        lines.append("地势判断：" + ("石与本园地势相合" if aligned else "石与本园地势相冲"))
        lines.append("凶机判断：" + ("阴煞不散，须防凶源" if dangerous else "暂未察觉明显凶机"))
    result = {"lines": lines, "accuracy": accuracy}
    inspected[str(no)] = result
    return True, f"【勘石·{stone.get('name', '原石')}】\n" + "\n".join(lines), y


def heavenly_check(y: dict, garden: str, stones: list[dict], no: int,
                   player: Mapping, now: float) -> tuple[bool, str, dict]:
    state = market_state(y, now)
    if str(player.get("occupation") or "") != "源天师":
        return False, "只有源天师能够施展辨伪源术。", y
    if state["heavenly_check_used"]:
        return False, "今日的天师辨石机会已经用过。", y
    stone = next((item for item in stones if int(item.get("no", 0)) == int(no)), None)
    if stone is None:
        return False, f"没有第 {no} 块石头。", y
    if stone.get("purchased") or int(no) in set(state["purchased"].get(garden) or []):
        return False, "这块源石已经离开石架。", y
    state["heavenly_check_used"] = True
    if stone.get("danger"):
        return True, "源天眼示警：石皮确有后天封合，内部生命或凶源尚未寂灭。", y
    if stone.get("surface_truthful") is False:
        return True, f"源天眼辨伪：「{stone['surface']}」是一条假象。", y
    return True, "源天眼扫过石皮：未见封合，当前所见线索没有作伪。", y


def purchase_stone(y: dict, garden: str, stones: list[dict], no: int,
                   stones_have: int, now: float) -> tuple[bool, str, dict]:
    if garden not in GARDENS:
        return False, "石园档位无效。", {"currency": "", "amount": 0}
    state = market_state(y, now)
    if state.get("pending"):
        return False, "请先切开已经买下的源石。", {"currency": "", "amount": 0}
    cfg = GARDENS[garden]
    if garden == "天字号":
        last = float((y.get("cooldown") or {}).get(garden, 0) or 0)
        if now - last < float(cfg["cooldownHours"]) * 3600:
            return False, "天字号石园尚未开放，需等待 20 小时冷却。", {"currency": "", "amount": 0}
    bought = state["purchased"].setdefault(garden, [])
    if len(bought) >= int(cfg["dailyLimit"]):
        return False, f"{garden}今日只能购买{cfg['dailyLimit']}块源石。", {"currency": "", "amount": 0}
    stone = next((item for item in stones if int(item.get("no", 0)) == int(no)), None)
    if stone is None or stone.get("purchased") or int(no) in set(bought):
        return False, "这块源石已经不在石架上。", {"currency": "", "amount": 0}
    currency, price = cfg["currency"], int(stone["price"])
    balance = int(stones_have) if currency == "灵石" else int(y.get("amount", 0) or 0)
    if balance < price:
        return False, f"购买{stone['name']}需要 {price:,}{currency}。", {"currency": "", "amount": 0}
    if currency == "源石":
        y["amount"] = balance - price
    bought.append(int(no))
    if garden == "天字号":
        y.setdefault("cooldown", {})[garden] = float(now)
    state["pending"] = {
        "garden": garden, "stone": copy.deepcopy(stone), "phase": "choose",
        "purchase_currency": currency, "purchase_price": price,
        "purchased_at": float(now),
    }
    return True, f"已购【{stone['name']}】。选择 #一刀切、#层层剥石 或 #封源切法。", {
        "currency": currency, "amount": price,
    }


def buy_and_cut(
    doc: Mapping, y: dict, garden: str, stones: list[dict], no: int,
    stones_have: int, hp: int, max_hp: int, now: float, rng: random.Random,
) -> tuple[bool, str, dict, dict]:
    """购石并切开。返回 (ok, msg, y2, consume)：consume={"cost", "currency", "hp_pct", "gains", "source"}。
    """
    cfg = GARDENS[garden]
    d = daily_of(y, now)
    cd_hours = float(cfg.get("cooldownHours") or 0)
    if cd_hours > 0:
        last_ts = float((y.get("cooldown") or {}).get(garden, 0) or 0)
        if now - last_ts < cd_hours * 3600:
            left = cd_hours * 3600 - (now - last_ts)
            return (False, f"{garden}刚切过一块，需 {int(left // 3600)} 时 "
                           f"{int(left % 3600 // 60)} 分后才能再购（原版 20 小时冷却）。", y, {})
    used = int(d["count"].get(garden, 0))
    if used >= cfg["dailyLimit"]:
        return False, f"{garden}今日已切 {used} 块（限额 {cfg['dailyLimit']} 块，明日再来）。", y, {}
    stone = next((s for s in stones if s["no"] == int(no)), None)
    if not stone:
        return False, f"没有第 {no} 块石头（1-{len(stones)}）。", y, {}
    price = int(stone["price"])
    if cfg["currency"] == "灵石":
        if stones_have < price:
            return False, f"灵石不足：此石价 {price:,}（当前 {stones_have:,}）。", y, {}
        cost = {"currency": "灵石", "amount": price}
    else:
        if int(y.get("amount", 0)) < price:
            return False, f"源石不足：此石价 {price:,}（当前 {int(y.get('amount', 0)):,}）。", y, {}
        y["amount"] = int(y.get("amount", 0)) - price
        cost = {"currency": "源石", "amount": price}
    d["count"][garden] = used + 1
    y["day"] = d
    if cd_hours > 0:
        y["cooldown"] = {**(y.get("cooldown") or {}), garden: float(now)}
    price = int(stone["price"])
    outcome = stone["outcome"]
    lines = [f"刀锋落下——{stone['name']}！"]
    gains: dict[str, int] = {}
    hp_pct = 0.0
    if stone["danger"]:
        hp_pct = cfg["danger"]
        lines.append(f"石中封着的凶物骤然反噬，气血被削去 {cfg['danger']:.0%}，你狼狈退出石园。")
        _record(y, garden, price, cost["currency"], 0, stone, now)
        return True, "\n".join(lines), y, {
            "cost": cost, "hp_pct": hp_pct, "gains": {}, "source": 0,
        }
    source = 0
    if stone["item"]:
        gains[stone["item"]] = 1
        lines.append(f"石心藏珍：{stone['item']} ×1！")
    if stone["ratio"] > 0:
        source = int(price * stone["ratio"] / cfg["rate"])
        y["amount"] = int(y.get("amount", 0)) + source
        lines.append(f"源石入账 +{source:,}（石价 {price:,} × {stone['ratio']:g} ÷ 汇率 {cfg['rate']}）")
    if not stone["item"] and stone["ratio"] == 0:
        lines.append("石心空空如也……赌石有风险，切石需谨慎。")
    _record(y, garden, price, cost["currency"], source, stone, now)
    return True, "\n".join(lines), y, {
        "cost": cost, "hp_pct": hp_pct, "gains": gains, "source": source,
    }


LEDGER_KEEP = 20


def _record(y: dict, garden: str, price: int, currency: str,
            source: int, stone: Mapping, now: float, *, empty: bool | None = None,
            extra: Mapping | None = None, cut: bool = True,
            refund: int = 0, refund_currency: str = "") -> None:
    """记一笔切石账：最近 20 笔 + 连续空石 + 累计次数（原版 sourceStoneForms 的轻量版）。"""
    if empty is None:
        empty = (not stone.get("item")) and float(stone.get("ratio") or 0) <= 0
    ledger = list(y.get("ledger") or [])
    ledger.append({
        "t": float(now), "garden": garden, "price": int(price), "cur": currency,
        "source": int(source), "item": str(stone.get("item") or ""),
        "name": str(stone.get("name") or ""), "empty": bool(empty), "cut": bool(cut),
        "extra": dict(extra or {}),
        "refund": int(refund), "refund_cur": str(refund_currency or ""),
    })
    y["ledger"] = ledger[-LEDGER_KEEP:]
    if cut:
        y["empty_streak"] = int(y.get("empty_streak", 0) or 0) + 1 if empty else 0
        y["cuts"] = int(y.get("cuts", 0) or 0) + 1


def record_duel_ledger(y: dict, now: float, *, price: int, source: int,
                       name: str, extra: Mapping | None = None) -> None:
    """Append duel accounting without counting it as a stone purchase/cut."""
    ledger = list(y.get("ledger") or [])
    ledger.append({
        "t": float(now), "garden": "源术对决", "price": int(price), "cur": "源石",
        "source": int(source), "item": "", "name": str(name), "empty": False,
        "cut": False, "extra": dict(extra or {}), "refund": 0, "refund_cur": "",
    })
    y["ledger"] = ledger[-LEDGER_KEEP:]


def ledger_text(y: Mapping) -> str:
    ledger = list(y.get("ledger") or [])
    if not ledger:
        return ("--- 源石坊账本 ---\n尚无切石记录。#源石坊 外园/地字号/天字号 看石，"
                "#购石 编号 切石。")
    spend = {"灵石": 0, "源石": 0}
    gained = 0
    items: dict[str, int] = {}
    for row in ledger:
        cur = str(row.get("cur") or "灵石")
        spend[cur] = spend.get(cur, 0) + int(row.get("price", 0) or 0)
        extra = row.get("extra") or {}
        if extra.get("amount"):
            extra_cur = str(extra["currency"])
            spend[extra_cur] = spend.get(extra_cur, 0) + int(extra["amount"])
        gained += int(row.get("source", 0) or 0)
        if row.get("refund"):
            refund_cur = str(row.get("refund_cur") or "灵石")
            spend[refund_cur] = spend.get(refund_cur, 0) - int(row.get("refund", 0) or 0)
        if row.get("item"):
            items[str(row["item"])] = items.get(str(row["item"]), 0) + 1
    lines = ["--- 源石坊账本（最近 %d 笔）---" % len(ledger)]
    for row in ledger[-8:]:
        t = time.strftime("%m-%d %H:%M", time.localtime(float(row.get("t", 0) or 0)))
        extra = row.get("extra") or {}
        fee = f"＋{int(extra['amount']):,}{extra['currency']}切法费" if extra.get("amount") else ""
        refund = int(row.get("refund", 0) or 0)
        got = (f"回购 +{refund:,}{row.get('refund_cur', '灵石')}" if refund else
               f"源石 +{int(row.get('source', 0)):,}" if int(row.get("source", 0) or 0)
               else ("【" + str(row["item"]) + "】" if row.get("item") else "空石"))
        lines.append(f"{t}｜{row.get('garden')}｜{int(row.get('price', 0)):,}"
                     f"{row.get('cur')}{fee} → {got}")
    lines.append(f"累计切石 {int(y.get('cuts', len(ledger)) or 0)} 块｜近 {len(ledger)} 笔："
                 f"灵石净支出 {spend.get('灵石', 0):,}、源石净支出 {spend.get('源石', 0):,}"
                 f"｜回收源石 {gained:,}")
    lines.append(f"连续空石：{int(y.get('empty_streak', 0) or 0)} 块")
    if items:
        lines.append("所得奇珍：" + "、".join(f"{k}×{v}" for k, v in items.items()))
    duel = y.get("duel") if isinstance(y.get("duel"), Mapping) else {}
    duels = sum(int(duel.get(key, 0) or 0) for key in ("wins", "losses", "draws"))
    if duels:
        lines.append(
            f"源术对决 {duels} 场（胜/负/平 {int(duel.get('wins', 0) or 0)}/"
            f"{int(duel.get('losses', 0) or 0)}/{int(duel.get('draws', 0) or 0)}）｜"
            f"净收益 {int(duel.get('net', 0) or 0):+,} 源石｜"
            f"累计切源 {int(duel.get('total_cut_source', 0) or 0):,}｜"
            f"单局最高 {int(duel.get('peak_cut_source', 0) or 0):,}")
    return "\n".join(lines)


def market_text(garden: str, stones: list[dict], y: dict, now: float) -> str:
    cfg = GARDENS[garden]
    state = market_state(y, now)
    used = len(state["purchased"].get(garden) or [])
    inspected = len(state["inspected"].get(garden) or {})
    lines = [f"--- 源石坊 · {garden}（{cfg['currency']}计价｜今日 {used}/{cfg['dailyLimit']}）---",
             f"灵石：使用 #源石坊外园购买｜源石余额：{int(y.get('amount', 0)):,}",
             f"今日免费勘石：{inspected}/{INSPECTS_PER_GARDEN}"]
    for s in stones:
        suffix = "（已购）" if s.get("purchased") else ""
        lines.append(f"[{s['no']}] 石价 {s['price']:,} {cfg['currency']}｜{s['surface']}{suffix}")
        if s.get("inspection"):
            lines.extend(s["inspection"].get("lines") or [])
    lines.append("#勘石 序号｜#天师辨石 序号｜#购石 序号")
    if state.get("pending"):
        lines.append("你有一块已购源石待切，请先完成当前切石。")
    else:
        lines.append("购石后选 #一刀切 / #层层剥石 / #封源切法；异象可 #继续切 / #石坊回购。")
    return "\n".join(lines)


def inspect(stones: list[dict], no: int) -> tuple[bool, str]:
    stone = next((s for s in stones if s["no"] == int(no)), None)
    if not stone:
        return False, f"没有第 {no} 块石头。"
    hint = "源气内敛" if stone["ratio"] >= 1 else "气机寻常"
    if stone["item"]:
        hint = f"似有异物（可能出 {stone['item']}）"
    if stone["danger"]:
        hint = "封纹不祥，恐有凶险！"
    return True, f"[{stone['no']}] {stone['surface']}——{hint}。"


def exchange(n_source: int, y: dict) -> tuple[bool, str, dict]:
    """源石兑换为灵石（外园汇率 10，供流通）。"""
    if n_source <= 0 or int(y.get("amount", 0)) < n_source:
        return False, f"源石不足（当前 {int(y.get('amount', 0)):,}）。", y
    y["amount"] = int(y.get("amount", 0)) - n_source
    gain = n_source * 10
    return True, f"源石 {n_source:,} 兑换灵石 {gain:,}（汇率 10）。", y
