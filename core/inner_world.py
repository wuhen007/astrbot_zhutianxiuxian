"""内景地（W8-B2a）：容量型第二仓库。

原版：`apps/User/neijingdi.js` 1019 行（8 条指令）+ `yuanshen.js` 1224（12 条）。
本批只做**仓库本体**，元神数值与「神游」留 B2b。

保留：
- 开启：500 万灵石（原版 500 万，货币口径统一为灵石）
- 容量：等级 × 500，升级消耗 `等级 × 50 万灵石`（原版 `INNER_WORLD_UPGRADE.baseCost=500000`、
  `capacityPerLevel=500`）
- **按物品类型占格**（原版 `ITEM_SPACE_RULES`）：装备 ×2、仙宠 ×3、丹药 ×0.5、草药 ×0.5、
  食材 ×0.5、仙宠口粮 ×0.5，其余 ×1；容量按「占格」算，允许小数累计后向上取整
- 存入 / 取出 / 一键存入 / 一键取出（可按类别）
- 与原版差异：原版内景地还承载元神修炼与神游入口，本批未接；储物本身独立可用

shortcut：元神（凝练/法门/神游/精神宇宙）见 B2b；原版内景地图片面板、命格消耗倍率、
开启概率加成未移植。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

OPEN_COST = 5_000_000
LEVEL_CAP = 20
CAPACITY_PER_LEVEL = 500
UPGRADE_BASE = 500_000

# 物品类别 → 占格权重（原版 ITEM_SPACE_RULES）
WEIGHTS: dict[str, float] = {
    "装备": 2.0,
    "仙宠": 3.0,
    "丹药": 0.5,
    "草药": 0.5,
    "食材": 0.5,
    "仙宠口粮": 0.5,
}
DEFAULT_WEIGHT = 1.0


def weight_of(cls: str | None) -> float:
    return WEIGHTS.get(str(cls or ""), DEFAULT_WEIGHT)


def state_of(doc: Any) -> dict[str, Any] | None:
    raw = doc.ext.get("inner_world") if isinstance(getattr(doc, "ext", None), Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    st = dict(raw)
    st["level"] = max(1, min(LEVEL_CAP, int(st.get("level", 1) or 1)))
    items = st.get("items")
    st["items"] = {str(k): int(v) for k, v in dict(items).items() if int(v) > 0} \
        if isinstance(items, Mapping) else {}
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["inner_world"] = dict(st)


def capacity(st: Mapping[str, Any]) -> int:
    return int(st.get("level", 1) or 1) * CAPACITY_PER_LEVEL


def used(st: Mapping[str, Any], cls_of) -> float:
    total = 0.0
    for name, qty in (st.get("items") or {}).items():
        total += weight_of(cls_of(name)) * int(qty)
    return round(total, 2)


def upgrade_cost(st: Mapping[str, Any]) -> int:
    return int(st.get("level", 1) or 1) * UPGRADE_BASE


def open_text() -> str:
    return (f"【内景地·未开】\n"
            f"以神识在识海开辟一方天地：{OPEN_COST:,} 灵石。\n"
            f"容量 = 等级 × {CAPACITY_PER_LEVEL} 格；升级消耗「等级 × {UPGRADE_BASE:,} 灵石」。\n"
            f"占格：装备 ×2、仙宠 ×3、丹药/草药/食材/仙宠口粮 ×0.5，其余 ×1。")


def open_world(doc: Any) -> tuple[bool, str]:
    if state_of(doc) is not None:
        return False, "内景地已开辟。"
    if int(doc.stones) < OPEN_COST:
        return False, f"开辟内景地需 {OPEN_COST:,} 灵石（当前 {int(doc.stones):,}）。"
    doc.stones -= OPEN_COST
    set_state(doc, {"level": 1, "items": {}})
    return True, (f"识海轰鸣，一方内景地自虚无中展开——容量 {CAPACITY_PER_LEVEL} 格。\n"
                  f"#存入内景地 物品 [数量]｜#一键存入内景地｜#我的内景地")


def upgrade(doc: Any) -> tuple[bool, str]:
    st = state_of(doc)
    if st is None:
        return False, "尚未开辟内景地（#开启内景地）。"
    if int(st["level"]) >= LEVEL_CAP:
        return False, f"内景地已至 {LEVEL_CAP} 级上限。"
    cost = upgrade_cost(st)
    if int(doc.stones) < cost:
        return False, f"【内景地·灵石不足】升级需 {cost:,} 灵石（当前 {int(doc.stones):,}）。"
    doc.stones -= cost
    st["level"] = int(st["level"]) + 1
    set_state(doc, st)
    return True, (f"内景地拓至 {st['level']} 级，容量 {capacity(st)} 格"
                  f"（本次 +{CAPACITY_PER_LEVEL}）。")


def deposit(doc: Any, inv: Mapping[str, int], name: str, qty: int,
            cls_of) -> tuple[bool, str, int]:
    """从纳戒存入内景地；容量不足时按剩余格数尽量存。"""
    st = state_of(doc)
    if st is None:
        return False, "尚未开辟内景地（#开启内景地）。", 0
    name = (name or "").strip()
    have = int(inv.get(name, 0) or 0)
    if have <= 0:
        return False, f"纳戒里没有「{name}」。", 0
    qty = max(1, min(have, int(qty)))
    w = weight_of(cls_of(name))
    free = capacity(st) - used(st, cls_of)
    fit = int(free // w) if w > 0 else qty
    if fit <= 0:
        return False, f"内景地已满（{used(st, cls_of):g}/{capacity(st)} 格）。", 0
    qty = min(qty, fit)
    st["items"][name] = int(st["items"].get(name, 0)) + qty
    set_state(doc, st)
    tail = "" if qty == min(have, int(qty)) else "（余下容量不足，未全存）"
    return True, (f"存入「{name}」×{qty}，占 {w * qty:g} 格；"
                  f"当前 {used(st, cls_of):g}/{capacity(st)} 格{tail}。"), qty


def withdraw(doc: Any, name: str, qty: int, cls_of) -> tuple[bool, str, int]:
    st = state_of(doc)
    if st is None:
        return False, "尚未开辟内景地。", 0
    name = (name or "").strip()
    have = int(st["items"].get(name, 0) or 0)
    if have <= 0:
        return False, f"内景地中没有「{name}」。", 0
    qty = max(1, min(have, int(qty)))
    left = have - qty
    if left > 0:
        st["items"][name] = left
    else:
        st["items"].pop(name, None)
    set_state(doc, st)
    return True, (f"取出「{name}」×{qty}，当前 {used(st, cls_of):g}/{capacity(st)} 格。"), qty


def deposit_all(doc: Any, inv: Mapping[str, int], cls_of) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未开辟内景地。", {}
    free = capacity(st) - used(st, cls_of)
    moved: dict[str, int] = {}
    for name, qty in sorted(inv.items(), key=lambda kv: weight_of(cls_of(kv[0]))):
        if free <= 0:
            break
        q = int(qty)
        if q <= 0:
            continue
        w = weight_of(cls_of(name))
        fit = min(q, int(free // w) if w > 0 else q)
        if fit <= 0:
            continue
        st["items"][name] = int(st["items"].get(name, 0)) + fit
        moved[name] = fit
        free -= fit * w
    if not moved:
        return False, "内景地已满，或纳戒里没有可存之物。", {}
    set_state(doc, st)
    brief = "、".join(f"{k}×{v}" for k, v in list(moved.items())[:8])
    more = f" 等 {len(moved)} 种" if len(moved) > 8 else ""
    return True, (f"一键存入：{brief}{more}；当前 {used(st, cls_of):g}/{capacity(st)} 格。"), moved


def withdraw_all(doc: Any, cls: str, cls_of) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未开辟内景地。", {}
    names = [n for n in st["items"] if not cls or cls_of(n) == cls]
    if not names:
        return False, (f"内景地中没有{'【' + cls + '】类别的' if cls else ''}物品。"), {}
    moved = {n: int(st["items"].pop(n)) for n in names}
    set_state(doc, st)
    return True, (f"取出 {len(moved)} 种："
                  + "、".join(f"{k}×{v}" for k, v in list(moved.items())[:8])
                  + (f" 等 {len(moved)} 种" if len(moved) > 8 else "")
                  + f"；当前 {used(st, cls_of):g}/{capacity(st)} 格。"), moved


def panel(doc: Any, cls_of) -> str:
    st = state_of(doc)
    if st is None:
        return open_text()
    lines = [f"【内景地·{st['level']} 级】",
             f"容量：{used(st, cls_of):g}/{capacity(st)} 格"
             f"（装备 2 格、仙宠 3 格、丹药/草药/食材/口粮 0.5 格）"]
    if not st["items"]:
        lines.append("尚未存放物品。")
    else:
        for i, (name, qty) in enumerate(sorted(st["items"].items(),
                                               key=lambda kv: -int(kv[1]))[:20], 1):
            lines.append(f"{i}. {name} ×{qty}（{weight_of(cls_of(name)):g} 格/件）")
        if len(st["items"]) > 20:
            lines.append(f"……另有 {len(st['items']) - 20} 种。")
    lines.append(f"升级：{upgrade_cost(st):,} 灵石 → {capacity(st) + CAPACITY_PER_LEVEL} 格")
    lines.append("#存入内景地 物品 [数量]｜#取出内景地 物品 [数量]｜#一键存入内景地｜#一键取出内景地 [类别]")
    return "\n".join(lines)


def used_ratio(st: Mapping[str, Any], cls_of) -> float:
    cap = capacity(st)
    return 0.0 if cap <= 0 else min(1.0, used(st, cls_of) / cap)


def cell_text(st: Mapping[str, Any], cls_of) -> str:
    """容量条（面板图用不上时也给纯文本一个直观刻度）。"""
    ratio = used_ratio(st, cls_of)
    filled = int(math.floor(ratio * 10))
    return "█" * filled + "░" * (10 - filled)
