"""源石坊赌石（对齐原版 apps/Game/stoneMarketRules.js）。

- 三档：外园（5 万灵石/日限 3/凶源伤 5%，池 COMMON）、地字号（30 万源石/日限 2/12%，池 GROUND）、
  天字号（200 万源石/日限 1/15%，池 SKY）
- 池权重与 ratio 直译；结算 sourceValue = 石价 × ratio ÷ 汇率（外园汇率 10，地/天 1）
- 名称/表面线索：70% 真实线索 + 30% 误导（原版 makeSignal 0.52 真，此处放宽便于体验）
- 源石为本插件自建数值货币（ext["yuanshi"]，原版为独立资源）
- 简化：石王/石师对决（五选三）、石相克制、地形对齐、封石/解封 → 延后
"""

from __future__ import annotations

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
              "sealCost": 500_000, "danger": 0.15},
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
INSPECT_COST = 10_000
STONES_PER_MARKET = 5

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
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def system_of(doc: Mapping) -> dict:
    y = doc.ext.get("yuanshi") if isinstance(doc.ext, Mapping) else None
    if isinstance(y, dict):
        return copy.deepcopy({"amount": int(y.get("amount", 0) or 0),
                              "day": y.get("day") or {}})
    return {"amount": 0, "day": {}}


def daily_of(y: dict, now: float) -> dict:
    day = _date_key(now)
    d = y.get("day") if isinstance(y.get("day"), dict) else {}
    if d.get("date") != day:
        d = {"date": day, "count": {}}
    d.setdefault("count", {})
    y["day"] = d
    return d


def make_market(doc_uid: str, garden: str, now: float) -> list[dict]:
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
        if rng.random() < 0.7:
            surface = rng.choice(SURFACES.get(picked[0], ["石皮寻常"]))
        else:
            decoy = rng.choice([e for e in pool if e[0] != picked[0]] or pool)
            surface = rng.choice(SURFACES.get(decoy[0], ["石皮寻常"]))
        stones.append({
            "no": i + 1, "price": price, "surface": surface,
            "outcome": picked[0], "name": picked[1], "ratio": picked[3],
            "item": picked[4], "danger": picked[5],
        })
    return stones


def buy_and_cut(
    doc: Mapping, y: dict, garden: str, stones: list[dict], no: int,
    stones_have: int, hp: int, max_hp: int, now: float, rng: random.Random,
) -> tuple[bool, str, dict, dict]:
    """购石并切开。返回 (ok, msg, y2, consume)：consume={"cost", "currency", "hp_pct", "gains", "source"}。
    """
    cfg = GARDENS[garden]
    d = daily_of(y, now)
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
    price = int(stone["price"])
    outcome = stone["outcome"]
    lines = [f"刀锋落下——{stone['name']}！"]
    gains: dict[str, int] = {}
    hp_pct = 0.0
    if stone["danger"]:
        hp_pct = cfg["danger"]
        lines.append(f"石中封着的凶物骤然反噬，气血被削去 {cfg['danger']:.0%}，你狼狈退出石园。")
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
    return True, "\n".join(lines), y, {
        "cost": cost, "hp_pct": hp_pct, "gains": gains, "source": source,
    }


def market_text(garden: str, stones: list[dict], y: dict, now: float) -> str:
    cfg = GARDENS[garden]
    d = daily_of(copy.deepcopy(y), now)
    used = int(d["count"].get(garden, 0))
    lines = [f"--- 源石坊 · {garden}（{cfg['currency']}计价｜今日 {used}/{cfg['dailyLimit']}）---",
             f"源石余额：{int(y.get('amount', 0)):,}"]
    for s in stones:
        lines.append(f"[{s['no']}] 石价 {s['price']:,} {cfg['currency']}｜{s['surface']}")
    lines.append(f"#勘石 1-{len(stones)}（1 万灵石看线索）｜#购石 1-{len(stones)}（切石）")
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
