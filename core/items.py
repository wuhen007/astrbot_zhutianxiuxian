"""物品/坊市/使用逻辑（纯函数；物品索引由 main 从内容表构建后传入）。"""

from __future__ import annotations

import math
import time
from typing import Any

# W7-1：原版「道心果按品阶加道心、上限 500、按需服用不浪费」；数据表已有 6 种道心果。
DAOXIN_CAP = 500
RARITY_LABELS = {1: "凡", 2: "凡", 3: "玄", 4: "玄", 5: "灵",
                 6: "灵", 7: "仙", 8: "圣", 9: "圣", 10: "帝"}


def rarity_of(item: dict[str, Any]) -> int:
    """稀有度 1-10，钳制后返回（数据表已有字段，此前零消费）。"""
    try:
        return min(10, max(1, int(float(item.get("稀有度") or 1))))
    except (TypeError, ValueError):
        return 1


def daoxin_qty(doc, item: dict[str, Any], qty: int) -> tuple[int, str]:
    """道心果按需服用：返回 (实际服用颗数, 提示)。非道心丹药原样返回。

    道心近满时只取需要的几颗，剩余留在纳戒；已满则返回 0（调用方不扣物品）。
    """
    try:
        per = int(float(item.get("道心") or 0))
    except (TypeError, ValueError):
        per = 0
    if per <= 0 or str(item.get("type") or "") != "道心":
        return max(1, int(qty)), ""
    cur = int(doc.ext.get("daoxin", 0) or 0)
    if cur >= DAOXIN_CAP:
        return 0, f"道心已圆满（{cur}/{DAOXIN_CAP}），不必再服【{item.get('name', '道心果')}】。"
    need = min(max(1, int(qty)), max(1, math.ceil((DAOXIN_CAP - cur) / per)))
    note = (f"道心将满，只取 {need} 颗（余 {int(qty) - need} 颗留在纳戒）。"
            if need < int(qty) else "")
    return need, note


def locked_of(doc) -> set[str]:
    v = doc.ext.get("locked_items")
    return {str(x) for x in v} if isinstance(v, (list, tuple, set)) else set()


def set_lock(doc, name: str, on: bool) -> tuple[bool, str]:
    """#锁定 / #解锁：纳戒物品防误卖（锁定不阻止正常使用）。"""
    name = (name or "").strip()
    if not name:
        return False, "格式：#锁定 物品名 / #解锁 物品名"
    cur = locked_of(doc)
    if on:
        if name in cur:
            return False, f"「{name}」已在锁定名单。"
        cur.add(name)
        verb = "锁定"
    else:
        if name not in cur:
            return False, f"「{name}」不在锁定名单。"
        cur.discard(name)
        verb = "解锁"
    doc.ext["locked_items"] = sorted(cur)
    return True, (f"已{verb}「{name}」——{'出售时会被拦下，正常使用不受影响' if on else '可正常出售'}。"
                  f"当前锁定 {len(cur)} 件。")


def item_buy_price(item: dict[str, Any], markup: float) -> int:
    return max(1, math.ceil(float(item.get("出售价", 0)) * markup))


def shop_page(
    stock: list[dict[str, Any]],
    page: int,
    per_page: int,
    markup: float,
) -> tuple[list[dict], int, int]:
    """坊市分页：返回 (当前页条目, 总页数, 修正后页码)。"""
    pages = max(1, math.ceil(len(stock) / per_page))
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    return stock[start : start + per_page], pages, page


def buy(
    doc, item: dict[str, Any], qty: int, markup: float
) -> tuple[bool, str, Any, dict[str, int]]:
    """购买。返回 (ok, msg, doc, 背包增量)。扣款由调用方在事务内完成。"""
    if qty < 1:
        return False, "至少购买 1 件。", doc, {}
    unit = item_buy_price(item, markup)
    total = unit * qty
    if doc.stones < total:
        return False, (
            f"灵石不足：{item['name']} 单价 {unit}（坊市价），×{qty} 共需 {total}，"
            f"当前 {doc.stones}。"
        ), doc, {}
    d = doc.model_copy(deep=True)
    d.stones -= total
    return True, (
        f"购得「{item['name']}」×{qty}，花费 {total} 灵石，剩余 {d.stones}。"
    ), d, {item["name"]: qty}


def sell(doc, item: dict[str, Any], qty: int) -> tuple[bool, str, Any]:
    """出售给系统：按出售价回收。"""
    if qty < 1:
        return False, "至少出售 1 件。", doc
    total = int(float(item.get("出售价", 0)) * qty)
    if total <= 0:
        return False, f"「{item['name']}」无人收购（出售价为 0）。", doc
    d = doc.model_copy(deep=True)
    d.stones += total
    return True, f"出售「{item['name']}」×{qty}，获得 {total} 灵石，当前 {d.stones}。", d


def use_item(
    doc,
    item: dict[str, Any],
    qty: int,
    max_hp: int = 0,
    linggen_table: list[dict[str, Any]] | None = None,
    rng: Any = None,
    now: float | None = None,
) -> tuple[bool, str, Any, bool]:
    """使用物品。返回 (ok, msg, doc, 是否消耗)。

    多字段叠加结算（原版丹药可能同时带多种字段）：
    - exp    修为增进（累计制，直接入账）
    - xueqi  血气打熬：气血上限永久 +值（累计存 ext["xueqi"]，聚合时并入血量）
    - HP/HPp 气血回复（固定值 / 上限比例），需调用方传聚合后 max_hp
    - linggen / type=天资洗炼  天资洗炼：重摇灵根（如 天命轮回丹、神心丹）
    - type=闭关/凝仙/炼神/仙缘/神赐/魔道值/入魔  品质丹 buff（ext["buffs"]，次数消耗制）
    - potential/heart/wudao/xingyun/道心  直投累计字段
    - shouyuan / type=寿命  增寿丹药（W7-0：同日耐药递减，见 lifespan.grant_pill）
    """
    if qty < 1:
        return False, "至少使用 1 件。", doc, False
    name = item.get("name", "?")

    if item.get("class") == "装备":
        return False, f"「{name}」是装备，请使用「#装备 {name}」穿戴。", doc, False

    # deep=True：ext 是嵌套 dict，浅拷贝会与原 doc 共享同一 dict，
    # 写 ext["xueqi"]/["hp"] 会污染调用方档案（纯函数性）。
    d = doc.model_copy(deep=True)
    parts: list[str] = []

    # 1) 修为
    if item.get("exp"):
        gained = int(item["exp"]) * qty
        d.exp += gained
        parts.append(f"修为增进 {gained} 点（当前 {d.exp}）")

    # 2) 血气：永久血上限
    try:
        xueqi = float(item.get("xueqi") or 0)
    except (TypeError, ValueError):
        xueqi = 0.0
    if xueqi > 0:
        add = int(xueqi) * qty
        d.ext["xueqi"] = int(d.ext.get("xueqi", 0)) + add
        parts.append(f"血气打熬，气血上限永久 +{add}")

    # 3) 气血回复（固定值 / 上限比例）
    try:
        hp_field = float(item.get("HP") or 0)
    except (TypeError, ValueError):
        hp_field = 0.0
    try:
        hpp_field = float(item.get("HPp") or 0)
    except (TypeError, ValueError):
        hpp_field = 0.0
    healed: int | None = None
    if hp_field > 1 or 0 < hpp_field <= 1:
        if not max_hp or max_hp <= 0:
            return False, "当前无法评估气血回复量。", doc, False
        cur = float(d.ext.get("hp", max_hp))
        if cur >= max_hp:
            healed = 0  # 满血不回，但不阻断其它效果
        else:
            want = 0
            if hp_field > 1:
                want = int(hp_field) * qty
            if 0 < hpp_field <= 1:
                want = max(want, int(max_hp * hpp_field) * qty)
            healed = int(min(want, max_hp - cur))
            d.ext["hp"] = cur + healed
            parts.append(f"气血回复 {healed} 点（当前 {int(d.ext['hp'])} / {max_hp}）")

    # 4) 天资洗炼（重摇灵根）
    try:
        ling = float(item.get("linggen") or 0)
    except (TypeError, ValueError):
        ling = 0.0
    if (ling > 0 or item.get("type") == "天资洗炼") and linggen_table and rng is not None:
        from . import linggen as _lg

        old, new, d = _lg.refine(d, linggen_table, rng)
        parts.append(f"天资洗炼：{_lg.describe(old) if old else '未洗炼'} → {_lg.describe(new)}")

    # 5) 品质丹 buff（原版 dy 存档体系，次数消耗制）
    t = str(item.get("type") or "")
    buffs = dict(d.ext.get("buffs") or {})
    if t == "闭关" and float(item.get("biguan") or 0) > 0:
        buffs["biguan"] = {"times": int(qty), "bonus": float(item["biguan"])}
        parts.append(f"辟谷药力：接下来 {qty} 次闭关效率 +{float(item['biguan']) * 100:.0f}%")
    elif t == "凝仙" and float(item.get("机缘") or 0) > 0:
        extend = int(item["机缘"]) * qty
        hit = 0
        for k in ("biguan", "lianti", "ped", "shenci"):
            b = buffs.get(k)
            if isinstance(b, dict) and float(b.get("times", 0) or 0) > 0:
                b["times"] = int(float(b["times"])) + extend
                buffs[k] = b
                hit += extend
        parts.append(f"丹韵入体，体内丹药药效延长 {hit} 次" if hit else "体内并无丹药药效，丹韵散逸了")
    elif t == "炼神" and float(item.get("lianshen") or 0) > 0:
        buffs["lianti"] = {"times": int(qty), "ratio": float(item["lianshen"])}
        parts.append(f"炼神之力 {float(item['lianshen']) * 100:.0f}%：接下来 {qty} 次闭关修为尽数化为血气")
    elif t == "仙缘" and float(item.get("gailv") or 0) > 0:
        buffs["ped"] = {"times": 5 * qty, "bonus": float(item["gailv"])}
        parts.append(f"仙兽祝福 {float(item['gailv']) * 100:.0f}%：{5 * qty} 次机缘加成（秘境扩展后生效）")
    elif t == "神赐" and float(item.get("概率") or 0) > 0:
        buffs["shenci"] = {"times": int(qty), "bonus": float(item["概率"])}
        parts.append(f"神兽恩赐 {float(item['概率']) * 100:.0f}%：{qty} 次祝福待机（对应系统开放后生效）")
    elif t == "魔道值" and float(item.get("modao") or 0) > 0:
        d.ext["modao"] = int(d.ext.get("modao", 0) or 0) - int(item["modao"]) * qty
        parts.append(f"转生之力：魔道值 -{int(item['modao']) * qty}（当前 {d.ext['modao']}）")
    elif t == "入魔" and float(item.get("modao") or 0) > 0:
        d.ext["modao"] = int(d.ext.get("modao", 0) or 0) + int(item["modao"]) * qty
        parts.append(f"{qty} 道魔气入体：魔道值 +{int(item['modao']) * qty}（当前 {d.ext['modao']}）")
    elif t in ("器灵", "锻造上限"):
        return False, f"「{name}」的效果需炼器/锻造格子系统（后续开放），暂无法服用。", doc, False
    if buffs:
        d.ext["buffs"] = buffs

    # 6) 直投累计字段（原版：潜力/心神/幸运/道心）
    for key, label, store in (
        ("potential", "仙道潜力", "potential"),
        ("heart", "心神", "heart"),
        ("wudao", "悟道", "wudao"),
    ):
        if float(item.get(key) or 0) > 0:
            add = int(float(item[key])) * qty
            d.ext[store] = int(d.ext.get(store, 0) or 0) + add
            parts.append(f"{label} +{add}（累计 {d.ext[store]}）")
    if float(item.get("xingyun") or 0) > 0:
        buffs2 = dict(d.ext.get("buffs") or {})
        buffs2["lucky"] = {"times": 10 * qty, "bonus": float(item["xingyun"])}
        d.ext["buffs"] = buffs2
        parts.append(f"幸运 +{float(item['xingyun']):g}：接下来 {10 * qty} 次冒险生效")
    if float(item.get("道心") or 0) > 0:
        per = int(float(item["道心"]))
        before = int(d.ext.get("daoxin", 0) or 0)
        after = min(DAOXIN_CAP, before + per * qty)
        d.ext["daoxin"] = after
        parts.append(f"道心 +{after - before}（累计 {after}/{DAOXIN_CAP}）")

    # 7) 寿元类丹药（W7-0）：数据表 shouyuan 字段 / type=寿命
    try:
        sy = float(item.get("shouyuan") or 0)
    except (TypeError, ValueError):
        sy = 0.0
    if sy > 0 or t == "寿命":
        from . import lifespan as _lp

        base = int(sy) if sy > 0 else 10
        gained, note = _lp.grant_pill(
            d, base * qty, now if now is not None else time.time())
        if gained <= 0:
            if parts:
                parts.append(note)
            else:
                return False, note, doc, False   # 药力饱和：不消耗物品
        else:
            parts.append(note)

    if not parts:
        if hp_field > 1 or 0 < hpp_field <= 1:
            return False, f"「{name}」无需使用，气血正满。", doc, False
        return False, f"「{name}」暂时无法直接使用。", doc, False

    rarity_note = (f"【{RARITY_LABELS.get(rarity_of(item), '凡')}品·稀有度 {rarity_of(item)}/10】"
                   if item.get("class") == "丹药" else "")
    msg = f"服下「{name}」{rarity_note}×{qty}：" + "；".join(parts) + "。"
    return True, msg, d, True
