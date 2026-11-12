"""剑云海机缘 + 一键出售（W33c：原版 replyOfficialMessage 玩法对齐）。

- 剑云海机缘：原版 `apps/User/shili.js` L1227——成仙修士持「剑云海令牌」造访，
  三选一（修炼资源 / 拜师传人 / 帝主庇护），一次性永不可重选。
  shortcut：原版「传人」服务器唯一且与势力冲突校验、帝主庇护联动黑暗牢笼——
  端口物化：传人=功法《永恒终极剑道》入库存+称号；庇护=【帝主庇护】印记物品
  （库存，说明留待对应系统使用）；资源=灵石 150 万（1.5 亿 ÷1000）+圣药×3。
- 一键出售：原版 `apps/User/UserSellAll.js` L1619——纳戒可售物品按图鉴出售价
  折算灵石，两步确认（清单 MD + 按钮）。
  shortcut：原版跳过锁定/帝兵；端口库存无装备混存（equipment 独立表），排除
  「不可交易/唯一」图鉴标记 + 关键道具白名单外全部出售。

rng 约定：无随机。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

# ---------------------------------------------------------------- 剑云海机缘

JYH_ITEM = "剑云海令牌"
JYH_FLAG = "jyh_chosen"
JYH_STONES = 1_500_000        # 原版 1.5 亿 ÷1000
JYH_PILL = "剑云海圣药"
JYH_SWORD = "永恒终极剑道"
JYH_SHIELD = "帝主庇护"


def jyh_done(doc: Any) -> bool:
    ext = getattr(doc, "ext", {}) or {}
    return bool(ext.get(JYH_FLAG))


def jyh_visit(doc: Any, inv: Mapping[str, int], realm_index: int,
              stones_have: int) -> tuple[bool, str, int]:
    """#造访剑云海：成仙 + 令牌×1。返回 (ok, text, 令牌消耗)。"""
    if jyh_done(doc):
        return False, "剑云海的机缘你早已做出抉择，万顷剑海再无你的涟漪。", 0
    if realm_index < 41:
        return False, "造访剑云海需成仙（主轨第 42 境）方可承受剑魔帝主之威。", 0
    if int((inv or {}).get(JYH_ITEM, 0) or 0) < 1:
        return False, f"需持【{JYH_ITEM}】×1 方可入海（诸天掉落）。", 0
    return True, "\n".join([
        "**剑云海机缘**",
        "",
        "剑魔帝主负手立于万顷剑海之前，静候你的选择。",
        "",
        "- **修炼资源：** 灵石与剑云海圣药",
        "- **拜师传人：** 继承《永恒终极剑道》",
        "- **帝主庇护：** 黑暗牢笼豁免与副本增益",
        "",
        "> 此次机缘仅可选择一次。（点击或 #剑云海选择1/2/3）"]), 1


def jyh_choose(doc: Any, choice: int, consume_token: Callable[[str, int], bool]) -> tuple[bool, str, dict[str, int], int]:
    """#剑云海选择1/2/3。返回 (ok, text, 库存变动, 灵石)。"""
    if jyh_done(doc):
        return False, "机缘已做出抉择，不可重选。", {}, 0
    if choice not in (1, 2, 3):
        return False, "请选择 1/2/3。", {}, 0
    if not consume_token(JYH_ITEM, 1):
        return False, f"【{JYH_ITEM}】已不在纳戒，机缘作废。", {}, 0
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[JYH_FLAG] = True
    delta: dict[str, int] = {}
    if choice == 1:
        stones = JYH_STONES
        delta[JYH_PILL] = 3
        doc.stones = int(getattr(doc, "stones", 0) or 0) + stones
        text = (f"你选了**修炼资源**——灵石 {stones:,} 与剑云海圣药 ×3 归入纳戒，"
                "剑海之水滋养道基。")
        return True, text, delta, stones
    if choice == 2:
        delta[JYH_SWORD] = 1
        text = ("剑魔帝主抬手认你为**传人**——《永恒终极剑道》化为剑印落入识海，"
                "万剑齐鸣，自此你的剑即是剑海之剑。")
        return True, text, delta, 0
    delta[JYH_SHIELD] = 1
    text = ("帝主垂眸一顾——**帝主庇护**印记烙入命轮，"
            "黑暗牢笼亦不敢轻易困你（印记留待对应领域生效）。")
    return True, text, delta, 0


def jyh_rules() -> str:
    return "\n".join([
        "【剑云海机缘·规则】",
        "「成仙修士持剑云海令牌造访剑海，剑魔帝主予你一次三选机缘，永不可重选。」",
        "",
        "· 修炼资源：灵石 150 万 + 剑云海圣药 ×3",
        "· 拜师传人：《永恒终极剑道》功法",
        "· 帝主庇护：【帝主庇护】印记（留待黑暗牢笼领域）",
        "",
        "触发：#造访剑云海（需主轨 42 境 + 剑云海令牌 ×1）",
    ])


# ---------------------------------------------------------------- 一键出售

# 关键道具白名单（永不自动出售）
KEEP_ITEMS = {"轮回命签", "命宫拓碑", "剑云海令牌", "天机符楼邀请函",
              "帝主庇护", "仙兽玉", "命运仙轮", "剑云海圣药"}


def preview(doc: Any, inv: Mapping[str, int],
            item_lookup: Callable[[str], Mapping | None]) -> tuple[str, int, dict[str, int]]:
    """清点可售物品。返回 (清单文本, 总价, 可售表)。"""
    rows: list[str] = []
    total = 0
    sellable: dict[str, int] = {}
    for name in sorted((inv or {}).keys()):
        qty = int((inv or {}).get(name, 0) or 0)
        if qty <= 0 or name in KEEP_ITEMS:
            continue
        item = item_lookup(name) or {}
        if item.get("不可交易") or item.get("unique"):
            continue
        price = int(item.get("出售价", 0) or 0)
        if price <= 0:
            continue
        sellable[name] = qty
        sub = price * qty
        total += sub
        rows.append(f"· {name} × {qty} = {sub:,} 灵石")
    text = "\n".join(rows[:12]) or "（无可售物品）"
    if len(rows) > 12:
        text += f"\n... 等 {len(rows)} 类"
    return text, total, sellable
    return text, total, sellable


def execute(doc: Any, inv: Mapping[str, int], sellable: Mapping[str, int],
            item_lookup: Callable[[str], Mapping | None]) -> tuple[str, int, dict[str, int]]:
    """执行出售（以确认时的可售表为准）。返回 (text, 灵石, 扣减表)。"""
    total = 0
    delta: dict[str, int] = {}
    n = 0
    for name, qty in (sellable or {}).items():
        cur = int((inv or {}).get(name, 0) or 0)
        if cur < qty:
            qty = cur
        if qty <= 0:
            continue
        price = int((item_lookup(name) or {}).get("出售价", 0) or 0)
        total += price * qty
        delta[name] = -qty
        n += qty
    doc.stones = int(getattr(doc, "stones", 0) or 0) + total
    return (f"【一键出售】共售出 {n} 件，灵石 +{total:,}（当前 {int(doc.stones):,}）。"), total, delta
