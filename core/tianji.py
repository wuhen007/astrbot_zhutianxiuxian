"""天机阁 / 天机符楼（W29 深度核查补漏 II）——原版 `apps/SecretPlace/tianjishop.js`
（441 行，dsc「天机阁模块」）的完整移植。

**与星阁拍卖的关系（核查结论）**：两者是独立玩法——星阁（Xingge）是灵石
竞价拍卖行；天机阁是**代币兑换商店**（仙兽玉/命运仙轮按「出售价」计件兑换），
数据表 `data/item/商店/天机阁.json`(340 行)/`天机阁符楼.json`(133 行) 移植端
早已 1:1 携带但指令未接线（W28 深度核查漏判，本轮补上）。

玩法：
- `#天机阁`：浏览商品表（代币：仙兽玉 / 命运仙轮，二选一优先前者）；
- `#天机阁兑换 物品*数量`：扣出售价×数量 的代币，物品入库存；
- `#创造命运仙轮*N`：旧神印章+仙王残魂+轮回印 各 N → 命运仙轮 N
  （轮回印在端口由仙古 NPC 击杀/原版团本掉落，材料链已通）；
- `#天机符楼`：需纳戒持有「天机符楼邀请函」（只查不耗）；
- `#天机符楼兑换 物品*数量`：daibi 可为「灵石」（走玩家灵石，原版价格
  ÷1000）或物品代币；**全服每日限购**按 日期+商品名 记 calamity_state["tianji"]。
- 「顶级灵石」是符楼内流通代币（灵石 2 亿→端口 20 万/个，日限 50），
  可作其他符楼商品的 daibi（库存在 inventory）。

rng 约定：无随机（纯兑换）。
"""

from __future__ import annotations
from .clock import day_key

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent.parent / "data" / "item" / "商店"
_CACHE: dict[str, list[dict]] = {}

WHEEL_MATERIALS = ("旧神印章", "仙王残魂", "轮回印")
WHEEL_ITEM = "命运仙轮"
FULOU_PASS = "天机符楼邀请函"

# 原版 yijishop2（面板禁制）原文
FULOU_GATE_TEXT = "\n".join([
    "【天机符楼·禁制】",
    "门前浮现金色符文：",
    "「非持函者不得窥视楼内天机！」",
    "",
    "获取方式：",
    "天机阁购买（#天机阁兑换 天机符楼邀请函）",
])
# 原版 daibiduihuan2（兑换拦截）原文
FULOU_EXCHANGE_GATE_TEXT = "\n".join([
    "天机符楼守卫拦住了你",
    "「此地乃天机重地，需持邀请函方可入内！」",
    "请先获取【天机符楼邀请函】后再尝试兑换",
])


def _shop(name: str) -> list[dict]:
    if name not in _CACHE:
        try:
            _CACHE[name] = json.loads((_DIR / f"{name}.json").read_text(encoding="utf-8"))
        except Exception:
            _CACHE[name] = []
    return _CACHE[name]


def ge_list() -> list[dict]:
    return _shop("天机阁")


def fulou_list() -> list[dict]:
    return _shop("天机阁符楼")


def find_item(name: str, table: list[dict]) -> dict | None:
    return next((e for e in table if str(e.get("name")) == str(name or "").strip()), None)


def _price(row: Mapping) -> int:
    """灵石计价 ÷1000；代币计价（仙兽玉/命运仙轮/顶级灵石等）保持原值。"""
    price = int(row.get("出售价", 0) or 0)
    daibi = str(row.get("daibi") or "")
    return price // 1000 if daibi == "灵石" else price


def list_text() -> str:
    rows = ge_list()
    if not rows:
        return "天机阁暂无商品。"
    lines = [f"【天机阁】共 {len(rows)} 件｜代币：仙兽玉 / 命运仙轮", ""]
    for e in rows:
        lines.append(f"· {e.get('name')}（{e.get('class')}/{e.get('type')}）"
                     f"｜{e.get('daibi')} {e.get('出售价')}"
                     + (f" 或 {e.get('daibi2')} {e.get('出售价')}" if e.get("daibi2") else ""))
    lines += ["", "兑换：#天机阁兑换 物品*数量（如 #天机阁兑换 一大袋洗根水*1）",
              "造轮：#创造命运仙轮*N（旧神印章+仙王残魂+轮回印 各 N）"]
    return "\n".join(lines)


def fulou_text(world: Mapping) -> str:
    rows = fulou_list()
    if not rows:
        return "天机符楼暂无商品。"
    bought = _bought_today(world)
    lines = ["【天机符楼】需持「天机符楼邀请函」（#天机阁兑换 获取）｜全服每日限购", ""]
    for e in rows:
        limit = int(e.get("每日限购", 0) or 0)
        used = int(bought.get(str(e.get("name")), 0) or 0)
        daibi = str(e.get("daibi") or "")
        price = _price(e)
        tail = f"｜今日余 {max(0, limit - used)}/{limit}" if limit else ""
        lines.append(f"· {e.get('name')}（{e.get('class')}/{e.get('type')}）"
                     f"｜{daibi} {price:,}{tail}")
    lines += ["", "兑换：#天机符楼兑换 物品*数量"]
    return "\n".join(lines)


def _today_key(now: float | None = None) -> str:
    return day_key(time.time() if now is None else now)


def daily_of(world: Mapping, now: float | None = None) -> dict:
    t = world.setdefault("tianji", {})
    day = str(t.get("day") or "")
    today = _today_key(now)
    if day != today:
        t = {"day": today, "bought": {}}
        world["tianji"] = t
    return t.setdefault("bought", {})


def _bought_today(world: Mapping) -> dict:
    return daily_of(world)


def exchange_ge(doc: Any, inv: Mapping[str, int], item_name: str, qty: int) -> tuple[bool, str, dict[str, int]]:
    """天机阁兑换：仙兽玉优先、命运仙轮次之。返回 (ok, text, 库存变动)。"""
    qty = max(1, int(qty or 1))
    row = find_item(item_name, ge_list())
    if not row:
        return False, f"天机阁中没有【{item_name}】这件宝物", {}
    delta: dict[str, int] = {}
    for token in (str(row.get("daibi") or ""), str(row.get("daibi2") or "")):
        if not token:
            continue
        need = int(row.get("出售价", 0) or 0) * qty
        have = int((inv or {}).get(token, 0) or 0)
        if have >= need:
            delta[token] = -need
            delta[str(row.get("name"))] = delta.get(str(row.get("name")), 0) + qty
            return True, (f"成功兑换【{row.get('name')}】×{qty}，"
                          f"消耗【{token}】×{need}"), delta
    msg = "兑换需要"
    parts = []
    for token in (str(row.get("daibi") or ""), str(row.get("daibi2") or "")):
        if not token:
            continue
        need = int(row.get("出售价", 0) or 0) * qty
        have = int((inv or {}).get(token, 0) or 0)
        parts.append(f"【{token}】×{need}（当前 {have}）")
    msg += " 或 ".join(parts)
    return False, msg, {}


def exchange_fulou(doc: Any, inv: Mapping[str, int], stones_have: int,
                   item_name: str, qty: int,
                   world: dict) -> tuple[bool, str, dict[str, int], int]:
    """符楼兑换：daibi=灵石 走玩家灵石（÷1000），其余走库存代币；
    全服每日限购。返回 (ok, text, 库存变动, 灵石扣款)。"""
    qty = max(1, int(qty or 1))
    row = find_item(item_name, fulou_list())
    if not row:
        return False, f"天机符楼没有【{item_name}】这件宝物", {}, 0
    limit = int(row.get("每日限购", 0) or 0)
    bought = daily_of(world)
    key = str(row.get("name"))
    used = int(bought.get(key, 0) or 0)
    if limit and used + qty > limit:
        return False, (f"全服今日限购已达上限！【{key}】日限 {limit} 个，"
                       f"今日已兑 {used}，剩余 {max(0, limit - used)}。"), {}, 0
    daibi = str(row.get("daibi") or "")
    need = _price(row) * qty
    delta: dict[str, int] = {}
    stones_cost = 0
    if daibi == "灵石":
        if stones_have < need:
            return False, f"灵石不足！需要 {need:,}，当前 {stones_have:,}。", {}, 0
        stones_cost = need
    else:
        have = int((inv or {}).get(daibi, 0) or 0)
        if have < need:
            return False, (f"代币不足！需要【{daibi}】×{need}，"
                           f"当前 {have}。"), {}, 0
        delta[daibi] = -need
    bought[key] = used + qty
    delta[key] = delta.get(key, 0) + qty
    tail = f"｜全服今日余 {max(0, limit - used - qty)}/{limit}" if limit else ""
    return True, (f"成功兑换【{key}】×{qty}，"
                  f"消耗{'灵石' if daibi == '灵石' else f'【{daibi}】'} ×{need:,}{tail}"), delta, stones_cost


def craft_wheel(inv: Mapping[str, int], qty: int) -> tuple[bool, str, dict[str, int]]:
    """#创造命运仙轮*N：三种材料各 N → 命运仙轮 N。"""
    qty = max(1, int(qty or 1))
    delta: dict[str, int] = {}
    for mat in WHEEL_MATERIALS:
        have = int((inv or {}).get(mat, 0) or 0)
        if have < qty:
            return False, (f"缺少至关重要的一样东西（{mat}×{qty}，当前 {have}），"
                           "无法创造命运仙轮！"), {}
        delta[mat] = -qty
    delta[WHEEL_ITEM] = qty
    return True, (f"你将仙王残魂和旧神印章炼化，融入到轮回印中，"
                  f"创造出了【{WHEEL_ITEM}】×{qty}"), delta


def rules_text() -> str:
    return "\n".join([
        "【天机阁·规则】",
        "「天机阁收罗诸天奇物，以仙兽玉/命运仙轮易之；符楼禁制森严，非持函者不得入内。」",
        "",
        "· #天机阁 / #天机阁兑换 物品*数量 —— 代币兑换（仙兽玉优先，命运仙轮次之）",
        "· #创造命运仙轮*N —— 旧神印章+仙王残魂+轮回印 各 N 炼制",
        "· #天机符楼 / #天机符楼兑换 物品*数量 —— 需「天机符楼邀请函」；",
        "  代币为灵石（÷1000 价）或顶级灵石等；全服每日限购，按日刷新",
    ])
