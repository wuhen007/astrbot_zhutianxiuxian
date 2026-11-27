"""寻宝地点（对齐原版 apps/SecretPlace 的 5 个寻宝类目 + model/xiuxian.js 结算）。

数据源 `item/寻宝列表.json`：mapCategories 5 类 14 地点，treasureMaps 给需求与奖励。
规则：
- 境界门槛取 levelRequirements（0 或 41=无妄真劫境）
- 口粮取 foodRequirements，字符串形如 "1000,仙人" 表示额外要求地仙以上
- 地图道具按 amount 消耗；工具只校验持有，不消耗（原版无耐久字段）
- 奖励 = base 全给 + random 逐组按 chance 累积判定，命中一组即停
shortcut: 原版数据没有冷却字段，故不设地点冷却；奖励组改为等概率抽取（原版未给权重）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CD_SECONDS = 0   # 原版数据无冷却字段，置 0 表示不设限
IMMORTAL_REALM = 42          # 地仙及以上视为「仙人」
CATEGORIES = {
    "mining": "寻宝挖矿",
    "logging": "寻宝砍树",
    "farming": "寻宝种植",
    "fishing": "寻宝钓鱼",
    "special": "寻宝特殊",
}
ACTS = {
    "mining": "挖掘", "logging": "砍伐", "farming": "耕作",
    "fishing": "垂钓", "special": "探寻",
}


def _tables(data: Mapping[str, Any]) -> tuple[dict, dict, dict, dict]:
    return (data.get("treasureMaps") or {}, data.get("mapCategories") or {},
            data.get("foodRequirements") or {}, data.get("levelRequirements") or {})


def label_of(category: str) -> str:
    return CATEGORIES.get(category, category)


def places(data: Mapping[str, Any], category: str) -> list[str]:
    _maps, cats, _food, _lv = _tables(data)
    return [str(x) for x in (cats.get(category) or [])]


def price_of(data: Mapping[str, Any], name: str) -> tuple[int, bool]:
    """→ (灵石, 是否要求仙人)。原版字符串形如 "1000,仙人"。"""
    _maps, _cats, food, _lv = _tables(data)
    raw = food.get(name)
    if isinstance(raw, (int, float)):
        return int(raw), False
    text = str(raw or "0")
    parts = [p.strip() for p in text.split(",")]
    try:
        cost = int(parts[0])
    except ValueError:
        cost = 0
    return cost, len(parts) > 1 and parts[1] == "仙人"


def realm_need(data: Mapping[str, Any], name: str) -> int:
    _maps, _cats, _food, lv = _tables(data)
    try:
        return int(lv.get(name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def state_of(doc: Any) -> dict[str, Any]:
    st = doc.ext.get("treasure_hunt")
    return st if isinstance(st, dict) else {}


def cooldown_left(doc: Any, name: str, now: float) -> int:
    last = float((state_of(doc).get("last") or {}).get(name, 0) or 0)
    left = int(last + CD_SECONDS - now)
    return left if left > 0 else 0


def mark(doc: Any, name: str, now: float) -> None:
    st = doc.ext.setdefault("treasure_hunt", {})
    if not isinstance(st, dict):
        st = {}
        doc.ext["treasure_hunt"] = st
    last = st.setdefault("last", {})
    last[name] = float(now)
    st["total"] = int(st.get("total", 0) or 0) + 1


def check(doc: Any, inv: Mapping[str, int], data: Mapping[str, Any],
          name: str, now: float) -> tuple[bool, str, dict[str, int], int]:
    """→ (ok, msg, 需扣物品, 口粮灵石)。"""
    maps, _cats, _food, _lv = _tables(data)
    place = maps.get(name)
    if not isinstance(place, Mapping):
        return False, f"没有「{name}」这个寻宝地点。", {}, 0
    need_realm = realm_need(data, name)
    if need_realm and int(getattr(doc, "realm_index", 0) or 0) < need_realm:
        return False, f"「{name}」需更高境界（当前不足）。", {}, 0
    cost, immortal = price_of(data, name)
    if immortal and int(getattr(doc, "realm_index", 0) or 0) < IMMORTAL_REALM:
        return False, f"「{name}」要仙人以上才能涉足。", {}, 0
    left = cooldown_left(doc, name, now)
    if left:
        return False, f"「{name}」刚去过，{left // 60} 分 {left % 60} 秒后可再往。", {}, 0
    req = place.get("requirements") or {}
    take: dict[str, int] = {}
    for row in req.get("map") or []:
        item = str(row.get("name") or "")
        amount = max(1, int(row.get("amount", 1) or 1))
        if int(inv.get(item, 0) or 0) < amount:
            return False, f"缺少寻宝图【{item}】×{amount}。", {}, 0
        take[item] = amount
    for row in req.get("tools") or []:
        item = str(row.get("name") or "")
        if int(inv.get(item, 0) or 0) < 1:
            return False, f"缺少工具【{item}】。", {}, 0
    if int(getattr(doc, "stones", 0) or 0) < cost:
        return False, f"口粮不足：需 {cost:,} 灵石。", {}, 0
    return True, "", take, cost


def settle(place: Mapping[str, Any], rng: Any) -> dict[str, int]:
    """base 全给；random 逐组累积判定，命中一组即停。"""
    gain: dict[str, int] = {}
    rewards = place.get("rewards") or {}
    for row in rewards.get("base") or []:
        item = str(row.get("name") or "")
        if item:
            gain[item] = gain.get(item, 0) + max(1, int(row.get("amount", 1) or 1))
    groups = [g for g in (rewards.get("random") or []) if g.get("items")]
    if groups:
        group = rng.choice(groups)
        for row in group.get("items") or []:
            item = str(row.get("name") or "")
            if item:
                gain[item] = gain.get(item, 0) + max(1, int(row.get("amount", 1) or 1))
    return gain


def panel(data: Mapping[str, Any], category: str, doc: Any,
          inv: Mapping[str, int], now: float) -> str:
    names = places(data, category)
    lines = [f"【寻宝·{label_of(category)}】共 {len(names)} 处"]
    maps, _c, _f, _l = _tables(data)
    for name in names:
        place = maps.get(name) or {}
        cost, immortal = price_of(data, name)
        need = realm_need(data, name)
        tags = []
        if need:
            tags.append(f"境界 {need}+")
        if immortal:
            tags.append("仙人")
        take = (place.get("requirements") or {}).get("map") or []
        hold = all(int(inv.get(str(r.get("name")), 0) or 0) >= max(1, int(r.get("amount", 1) or 1))
                   for r in take)
        left = cooldown_left(doc, name, now)
        state = "冷却中" if left else ("可往" if hold else "缺寻宝图")
        lines.append(f"· {name}（{place.get('grade', '?')}）口粮 {cost:,}"
                     + (f"｜{'、'.join(tags)}" if tags else "")
                     + f"｜{state}")
        best = place.get("bestRewards") or []
        if best:
            lines.append(f"   头奖：{'、'.join(str(x) for x in best[:3])}")
    lines.append(f"前往：#前往寻宝 地点名（例：#前往寻宝 {names[0] if names else '天臂池'}）")
    return "\n".join(lines)


def result_text(name: str, gain: Mapping[str, int]) -> str:
    body = "、".join(f"{k}×{v}" for k, v in gain.items()) or "一无所获"
    return f"【寻宝·{name}】\n铲开泥土，收获：{body}。"
