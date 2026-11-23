"""图鉴/楼类查询与物品来源（纯函数，无 IO）。

对齐原版 #丹药楼/#装备楼/#功法楼 等图鉴指令与 #哪里有 来源查询：
- 楼类 = 按表分页浏览物品（名称/类型/出售价/关键效果）。
- 来源 = 炼丹配方材料 / 商店货架 / 秘境掉落池 / 坊市可直接购买 四类渠道反查。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

PER_PAGE = 12


def _effect_brief(item: Mapping) -> str:
    """物品关键效果简述（有数值效果字段时展示）。"""
    keys = (
        ("exp", "修为"), ("xueqi", "血气"), ("HP", "血量"), ("linggen", "灵根洗炼"),
        ("HPp", "回血比例"), ("biguan", "闭关"), ("gailv", "仙缘"), ("lianshen", "炼神"),
        ("potential", "潜力"), ("heart", "心神"), ("wudao", "悟道"), ("xingyun", "幸运"),
    )
    parts = []
    for k, label in keys:
        v = item.get(k)
        if v in (None, 0, "", 0.0):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            parts.append(f"{label}+{int(fv) if fv >= 1 else fv:g}")
    return " ".join(parts)


def catalog_page(
    items: Sequence[Mapping], page: int
) -> tuple[list[dict], int, int]:
    """楼类分页：返回 (当前页条目, 总页数, 修正页码)。"""
    pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    page = min(max(1, page), pages)
    start = (page - 1) * PER_PAGE
    cur = []
    for it in items[start : start + PER_PAGE]:
        if not isinstance(it, Mapping) or not it.get("name"):
            continue
        cur.append({
            "name": str(it["name"]),
            "type": str(it.get("type", "") or ""),
            "price": int(it.get("出售价", 0) or 0),
            "rarity": it.get("稀有度", ""),
            "effect": _effect_brief(it),
            "desc": str(it.get("desc", "") or ""),
        })
    return cur, pages, page


def where_to_get(
    item_name: str,
    recipes: Sequence[Mapping],
    shop_names: set[str],
    drop_pool_names: set[str],
) -> list[str]:
    """物品来源反查：炼丹/锻造配方材料、商店货架、秘境掉落。返回来源描述列表。"""
    outs: list[str] = []
    for r in recipes:
        for m in r.get("materials") or []:
            if str(m.get("name")) == item_name:
                outs.append(f"炼丹材料：「{r['name']}」配方需要")
                break
    for r in recipes:
        pass
    if item_name in shop_names:
        outs.append("坊市：#商店 有售")
    if item_name in drop_pool_names:
        outs.append("秘境：#降临秘境 / #秘境寻宝 可得")
    # 产物流：该物品是某配方产物
    for r in recipes:
        if r.get("name") == item_name:
            outs.append("炼丹产物：可直接 #炼丹")
            break
    return outs or ["暂无已知渠道：可试试 #商店 搜索或向道友收购。"]
