"""交易行：冲水堂（直购挂单）+ 聚宝堂（委托悬赏），对齐原版 apps/Exchange。

冲水堂：`#上架 物品*单价*数量` → `#选购 序号*数量` 即时成交，卖家货款入账。
聚宝堂：`#发布 物品*数量*赏金` 先托管赏金 → `#接取 序号` 交付物品，赏金归接单者。
两个市场共用一张单例 JSON（`exchange_state`），24 小时未成交自动下架并退还。
shortcut: 原版装备按品级/背包序号上架，本移植库存按名字记数，统一按名字交易。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

STALL_TTL = 24 * 3600
WANT_TTL = 24 * 3600
CD_SECONDS = 30
CLASSES = ("装备", "丹药", "功法", "道具", "草药", "仙宠", "材料", "宝石", "食材", "盒子")


def _defaults() -> dict[str, Any]:
    return {"stalls": [], "wanted": [], "seq": 0}


def world_of(state: Mapping[str, Any] | None) -> dict[str, Any]:
    w = dict(state or {})
    base = _defaults()
    for key, val in base.items():
        w.setdefault(key, val)
    if not isinstance(w["stalls"], list):
        w["stalls"] = []
    if not isinstance(w["wanted"], list):
        w["wanted"] = []
    return w


def set_world(state: dict[str, Any], w: Mapping[str, Any]) -> None:
    state.clear()
    state.update(w)


def _next_id(w: dict[str, Any]) -> int:
    w["seq"] = int(w.get("seq", 0) or 0) + 1
    return w["seq"]


def expire(w: dict[str, Any], now: float) -> dict[str, Any]:
    """超时下架：返回需要回滚的物品与赏金（按 uid 聚合）。"""
    items: dict[str, dict[str, int]] = {}
    stones: dict[str, int] = {}
    notes: list[str] = []
    keep = []
    for lot in w["stalls"]:
        if now - float(lot.get("ts", now)) > STALL_TTL:
            uid = str(lot.get("uid"))
            bag = items.setdefault(uid, {})
            bag[lot["item"]] = bag.get(lot["item"], 0) + int(lot["qty"])
            notes.append(f"冲水堂 {lot['item']}×{lot['qty']} 超时下架，已退回")
            continue
        keep.append(lot)
    w["stalls"] = keep
    keep = []
    for lot in w["wanted"]:
        if now - float(lot.get("ts", now)) > WANT_TTL:
            uid = str(lot.get("uid"))
            stones[uid] = stones.get(uid, 0) + int(lot["reward"])
            notes.append(f"聚宝堂 {lot['item']}×{lot['qty']} 委托超时，赏金已退回")
            continue
        keep.append(lot)
    w["wanted"] = keep
    return {"items": items, "stones": stones, "notes": notes}


def sell(w: dict[str, Any], doc: Any, inv: Mapping[str, int], arg: str,
         is_restricted, now: float) -> tuple[bool, str, dict[str, int], list[str]]:
    """`#上架 物品*单价*数量` → 扣物品入挂单。"""
    parts = [p.strip() for p in str(arg or "").split("*")]
    if len(parts) < 3 or not parts[0]:
        return False, "格式：#上架 物品*单价*数量（例：#上架 凝气丹*800*5）", {}, []
    name = parts[0]
    try:
        price = int(parts[1])
        qty = int(parts[2])
    except ValueError:
        return False, "单价与数量必须是整数。", {}, []
    if price <= 0 or qty <= 0:
        return False, "单价与数量都必须大于 0。", {}, []
    have = int(inv.get(name, 0) or 0)
    if have < qty:
        return False, f"纳戒中「{name}」只有 {have} 个。", {}, []
    if is_restricted(doc, name):
        return False, f"【{name}】已绑定或不可交易，禁止上架。", {}, []
    lot = {"id": _next_id(w), "uid": str(doc.uid), "name": str(getattr(doc, "name", "") or ""),
           "item": name, "qty": qty, "price": price, "ts": now}
    w["stalls"].append(lot)
    return (True, f"已上架【{name}】×{qty}，单价 {price:,}，#选购 {lot['id']} 可直接买。",
            {name: qty}, [])


def unsell(w: dict[str, Any], doc: Any, arg: str) -> tuple[bool, str, dict[str, int]]:
    """`#下架 序号`。"""
    raw = str(arg or "").strip()
    if not raw.isdigit():
        return False, "格式：#下架 挂单序号", {}
    idx = int(raw)
    for i, lot in enumerate(w["stalls"]):
        if int(lot.get("id", 0)) != idx:
            continue
        if str(lot.get("uid")) != str(doc.uid):
            return False, "这不是你的挂单。", {}
        w["stalls"].pop(i)
        return True, f"已下架【{lot['item']}】×{lot['qty']}，物品已退回。", {lot["item"]: int(lot["qty"])}
    return False, f"没有编号 {idx} 的挂单。", {}


def buy(w: dict[str, Any], doc: Any, arg: str,
        now: float) -> tuple[bool, str, dict[str, int], dict[str, int]]:
    """`#选购 序号*数量` → 返回 (收货, 扣款)。"""
    parts = [p.strip() for p in str(arg or "").split("*")]
    if not parts or not parts[0].isdigit():
        return False, "格式：#选购 挂单序号*数量（例：#选购 3*2）", {}, {}
    idx = int(parts[0])
    for i, lot in enumerate(w["stalls"]):
        if int(lot.get("id", 0)) != idx:
            continue
        if str(lot.get("uid")) == str(doc.uid):
            return False, "不能购买自己的挂单。", {}, {}
        qty = int(lot["qty"])
        want = qty
        if len(parts) > 1:
            if not parts[1].isdigit():
                return False, "数量必须是整数。", {}, {}
            want = min(qty, int(parts[1]))
        if want <= 0:
            return False, "数量必须大于 0。", {}, {}
        cost = want * int(lot["price"])
        if int(getattr(doc, "stones", 0) or 0) < cost:
            return False, f"灵石不足：需 {cost:,}，现有 {int(getattr(doc, 'stones', 0) or 0):,}。", {}, {}
        lot["qty"] = qty - want
        if lot["qty"] <= 0:
            w["stalls"].pop(i)
        return (True, f"购得【{lot['item']}】×{want}，共 {cost:,} 灵石（卖家 #{lot['uid']}）。",
                {lot["item"]: want}, {"stones": cost, "seller": lot["uid"]})
    return False, f"没有编号 {idx} 的挂单。", {}, {}


def publish(w: dict[str, Any], doc: Any, arg: str,
            now: float) -> tuple[bool, str, int]:
    """`#发布 物品*数量*赏金` → 记录委托（赏金托管）。"""
    parts = [p.strip() for p in str(arg or "").split("*")]
    if len(parts) < 3 or not parts[0]:
        return False, "格式：#发布 物品*数量*赏金（例：#发布 凝气丹*5*1000）", 0
    name = parts[0]
    try:
        qty = int(parts[1])
        reward = int(parts[2])
    except ValueError:
        return False, "数量与赏金必须是整数。", 0
    if qty <= 0 or reward <= 0:
        return False, "数量与赏金都必须大于 0。", 0
    if int(getattr(doc, "stones", 0) or 0) < reward:
        return False, f"灵石不足：赏金需 {reward:,}。", 0
    lot = {"id": _next_id(w), "uid": str(doc.uid), "name": str(getattr(doc, "name", "") or ""),
           "item": name, "qty": qty, "reward": reward, "ts": now}
    w["wanted"].append(lot)
    return (True, f"已发布委托【{name}】×{qty}，赏金 {reward:,}（已托管）。", reward)


def cancel(w: dict[str, Any], doc: Any, arg: str) -> tuple[bool, str, int]:
    """`#取消 序号` → 退回赏金。"""
    raw = str(arg or "").strip()
    if not raw.isdigit():
        return False, "格式：#取消 委托序号", 0
    idx = int(raw)
    for i, lot in enumerate(w["wanted"]):
        if int(lot.get("id", 0)) != idx:
            continue
        if str(lot.get("uid")) != str(doc.uid):
            return False, "这不是你的委托。", 0
        w["wanted"].pop(i)
        return True, f"已撤销委托【{lot['item']}】×{lot['qty']}，赏金 {int(lot['reward']):,} 已退回。", int(lot["reward"])
    return False, f"没有编号 {idx} 的委托。", 0


def accept(w: dict[str, Any], doc: Any, inv: Mapping[str, int], arg: str) -> tuple[bool, str, dict[str, int], int, str]:
    """`#接取 序号` → 交付物品，赏金归接单者。"""
    raw = str(arg or "").strip()
    if not raw.isdigit():
        return False, "格式：#接取 委托序号", {}, 0, ""
    idx = int(raw)
    for i, lot in enumerate(w["wanted"]):
        if int(lot.get("id", 0)) != idx:
            continue
        if str(lot.get("uid")) == str(doc.uid):
            return False, "不能接自己的委托。", {}, 0, ""
        item, qty = str(lot["item"]), int(lot["qty"])
        if int(inv.get(item, 0) or 0) < qty:
            return False, f"你只有 {int(inv.get(item, 0) or 0)} 个「{item}」，需要 {qty} 个。", {}, 0, ""
        w["wanted"].pop(i)
        return (True, f"已接取并交付【{item}】×{qty}，赏金 {int(lot['reward']):,} 已入账。",
                {item: qty}, int(lot["reward"]), str(lot["uid"]))
    return False, f"没有编号 {idx} 的委托。", {}, 0, ""


def _fmt(lot: Mapping[str, Any], kind: str) -> str:
    if kind == "stalls":
        return (f"#{lot['id']} 【{lot['item']}】×{lot['qty']} · 单价 {int(lot['price']):,}"
                f" · {lot.get('name') or lot['uid'][:6]}")
    return (f"#{lot['id']} 【{lot['item']}】×{lot['qty']} · 赏金 {int(lot['reward']):,}"
            f" · {lot.get('name') or lot['uid'][:6]}")


def panel_text(w: Mapping[str, Any], kind: str, cls: str = "",
               cls_of: Any = None) -> str:
    rows = w["stalls"] if kind == "stalls" else w["wanted"]
    if cls and cls_of is not None:
        rows = filter_by_class(w, kind, cls, cls_of)
    title = "【冲水堂·直购】" if kind == "stalls" else "【聚宝堂·委托】"
    lines = [title + (f"（{cls}）" if cls else "")]
    if not rows:
        lines.append("当前没有挂单。" if kind == "stalls" else "当前没有委托。")
    else:
        for lot in rows[:20]:
            lines.append(_fmt(lot, kind))
        if len(rows) > 20:
            lines.append(f"……另有 {len(rows) - 20} 单。")
    if kind == "stalls":
        lines.append("上架：#上架 物品*单价*数量｜下架：#下架 序号｜购买：#选购 序号*数量")
    else:
        lines.append("发布：#发布 物品*数量*赏金｜撤销：#取消 序号｜接单：#接取 序号")
    lines.append(f"分类浏览：#冲水堂 装备｜#聚宝堂 丹药（{'/'.join(CLASSES)}）")
    return "\n".join(lines)


def filter_by_class(w: dict[str, Any], kind: str, cls: str, cls_of) -> list[dict[str, Any]]:
    rows = w["stalls"] if kind == "stalls" else w["wanted"]
    if not cls:
        return rows
    return [lot for lot in rows if str(cls_of(str(lot.get("item")))) == cls]
