"""W8-D2 星阁 · 竞价拍卖（对齐原版 apps/Auction/* 的 16 条 rule）。

取证口径（`Z:/wbsy/.../ref/_zj/zhutianxiuxian1.0-master`）：
- `apps/Auction/Auction.js` 8 条 + `Auction2.js` 8 条 = 16 主指令 / 0 别名。
- 无手续费、无撤拍、无手动结算；后台每分钟按原版配置开拍/结算，单进程锁替代 Redis Lua CAS。
- `last_offer_price` 在原版是「最后一次出价的毫秒时间戳」，本移植另存 `bid_ts`。
- 加价 10%、`interval:2` 分钟且每次出价重置倒计时、上架 24h CD、全服同时仅 1 场玩家外场。
- 内场 NPC 每分钟有 30% 概率按原版类型权重竞价；玩家成功出价后按天骄仇恨概率反价。
- 内场验资 = 1200 万源石验资 + 扣 500 万源石买断**永久**身份；货币为源石，外场为灵石。
- 官方成交不传 sellerId（货币系统回收）；NPC 得标原版不扣款不发货；官方流拍无返还。

shortcut：
- 玩家内场 `xiuxian:auction2` 在原版是死链（无写入者、cron 不结算），本移植跳过，
  `#查看当前内场拍卖` / `#内场竞价` 一律映射到官方内场。
- 官方外场20-21点、内场21-23点按上海时区开拍；每分钟尝试内场 NPC 加价并处理到期结算。
- 全服图片广播未移植，改为向登记群发送文本；天骄仇恨反价已接入官方出价。
- **数值不折算**：本移植源石坊（天字号 200 万源石/块）与原版内场同量级；
  外场灵石亦同量级。与 W8-D1 败天神殿的 ÷1000 不同，那是本移植自建产出节奏的特例。
- 幂等用全服 `claims` 记录 `<kind>:<lot id>`；结算时余额不足按 `defaulted` 退物给卖家。
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Mapping

WORLD_KEY = "auction"
INTERVAL_SECONDS = 120.0          # 原版 Auction.interval = 2 分钟
LIST_CD_SECONDS = 24 * 3600.0     # 原版 24*60*60*1000 ms
MIN_RAISE = 1.1                   # 原版两套判定不一致，统一取 ceil(last*1.1)
VERIFY_MIN = 12_000_000           # 原版 1200 万源石验资
VERIFY_COST = 5_000_000           # 原版扣 500 万源石买断
NPC_CHANCE = 0.30                 # 原版 30%/分钟
INNER_FLAG = "xingge_inner"       # 玩家 ext 里对应原版 player.星阁内场
CLAIM_LIMIT = 200

KINDS = ("player", "official", "inner")
LABELS = {"player": "玩家外场", "official": "星阁", "inner": "星阁内场"}


def _defaults(w: dict[str, Any]) -> dict[str, Any]:
    for key in KINDS:
        if not isinstance(w.get(key), dict):
            w[key] = None
    w["enabled"] = bool(w.get("enabled"))
    w["enabled2"] = bool(w.get("enabled2"))
    for key in ("groups", "groups2"):
        g = w.get(key)
        w[key] = [str(x) for x in g] if isinstance(g, (list, tuple)) else []
    for key in ("claims",):
        c = w.get(key)
        w[key] = [str(x) for x in c] if isinstance(c, (list, tuple)) else []
    for key in ("last_list",):
        m = w.get(key)
        w[key] = dict(m) if isinstance(m, Mapping) else {}
    w["seq"] = int(w.get("seq") or 0)
    return w


def world_of(state: Mapping[str, Any]) -> dict[str, Any]:
    raw = state.get(WORLD_KEY)
    return _defaults(dict(raw) if isinstance(raw, Mapping) else {})


def set_world(state: dict[str, Any], w: Mapping[str, Any]) -> None:
    state[WORLD_KEY] = dict(w)


def currency_of(kind: str) -> str:
    return "源石" if kind == "inner" else "灵石"


def min_raise(price: int) -> int:
    """ceil(price × 1.1)，用整数算避免 100*1.1=110.00000000000001 → 111 的浮点偏差。"""
    return (int(price) * 11 + 9) // 10


def _claim(w: dict[str, Any], kind: str, lot: Mapping[str, Any]) -> bool:
    key = f"{kind}:{lot.get('id')}"
    if key in w["claims"]:
        return False
    w["claims"].append(key)
    w["claims"] = w["claims"][-CLAIM_LIMIT:]
    return True


def _refund(lot: Mapping[str, Any]) -> list[dict[str, Any]]:
    seller = str(lot.get("seller") or "")
    if not seller:
        return []
    return [{"uid": seller, "items": {str(lot.get("name")): int(lot.get("amount") or 1)}}]


def _open(w: dict[str, Any], kind: str, pools: Mapping[str, Any],
          rng: random.Random, now: float) -> str:
    pool = pools.get(kind) or []
    if not pool:
        return f"【{LABELS[kind]}】拍品表为空，无法开拍。"
    item = rng.choice(pool)
    price = max(1, int(item.get("出售价") or 1))
    amount = max(1, int(item.get("数量") or 1)) if kind == "inner" else 1
    w["seq"] += 1
    w[kind] = {
        "id": f"{kind}-{w['seq']}", "kind": kind,
        "name": str(item.get("name") or "无名拍品"),
        "class": str(item.get("class") or "道具"),
        "desc": str(item.get("desc") or ""),
        "rarity": int(item.get("稀有度") or 0),
        "amount": amount, "start": price, "price": price,
        "bid_ts": now, "bidder": "0", "seller": "",
        "groups": list(w.get("groups2" if kind == "inner" else "groups") or []),
    }
    return (f"【{LABELS[kind]}】开拍：{w[kind]['name']}×{amount}（{w[kind]['desc']}）\n"
            f"起拍 {price:,} {currency_of(kind)}，{int(INTERVAL_SECONDS / 60)} 分钟无人加价即成交。")


def _settle(w: dict[str, Any], kind: str, lot: Mapping[str, Any],
            balances: Mapping[str, tuple[int, int]]) -> tuple[str, list[dict[str, Any]]]:
    """结算一场。ops 由 main 落库（可能涉及非当前玩家）。"""
    if not _claim(w, kind, lot):
        return "", []
    name = str(lot.get("name"))
    price = max(0, int(lot.get("price") or 0))
    amount = int(lot.get("amount") or 1)
    bidder = str(lot.get("bidder") or "0")
    label = LABELS[kind]
    cur = currency_of(kind)

    if bidder in ("0", ""):                       # 流拍
        ops = _refund(lot) if kind == "player" else []
        tail = "，物品已退回卖家" if ops else "（官方拍品无卖家）"
        return f"【{label}】{name} 无人出价，流拍{tail}。", ops
    if bidder == "-1":                           # 原版 NPC 得标不扣款不发货
        ops = _refund(lot) if kind == "player" else []
        return f"【{label}】神秘 NPC 得标（{price:,} {cur}），原版不扣款不发货，拍品作废。", ops

    have = (balances.get(bidder) or (0, 0))[1 if kind == "inner" else 0]
    if have < price:                             # defaulted
        ops = _refund(lot) if kind == "player" else []
        return (f"【{label}】{name} 竞得者余额不足（需 {price:,} {cur}），交易取消"
                f"{'，物品已退回卖家' if ops else ''}。", ops)

    ops: list[dict[str, Any]] = [{
        "uid": bidder,
        "yuanshi" if kind == "inner" else "stones": -price,
        "items": {name: amount},
    }]
    if kind == "player" and lot.get("seller"):
        ops.append({"uid": str(lot["seller"]), "stones": price})
    return f"【{label}】{name}×{amount} 以 {price:,} {cur} 成交。", ops


def tick(w: dict[str, Any], now: float, pools: Mapping[str, Any],
         rng: random.Random,
         balances: Mapping[str, tuple[int, int]] | None = None,
         open_kinds: set[str] | None = None,
         allow_player_open: bool = True,
         scheduled: bool = False) -> tuple[list[str], list[dict[str, Any]]]:
    """结算到期场次；官方外/内场仅在各自原版每日窗口开拍。"""
    balances = balances or {}
    notes: list[str] = []
    ops: list[dict[str, Any]] = []
    for kind in KINDS:
        lot = w.get(kind)
        if not isinstance(lot, dict):
            enabled = w["enabled2"] if kind == "inner" else w["enabled"]
            can_open = (kind == "player" and allow_player_open) or (
                kind != "player" and (open_kinds is None or kind in open_kinds))
            has_groups = bool(w["groups2"] if kind == "inner" else w["groups"])
            if kind in ("official", "inner") and enabled and can_open and has_groups:
                note = _open(w, kind, pools, rng, now)
                if note:
                    notes.append(note)
            continue
        if scheduled and kind == "player":
            continue
        if now - float(lot.get("bid_ts") or 0) >= INTERVAL_SECONDS:
            note, more = _settle(w, kind, lot, balances)
            w[kind] = None
            if note:
                notes.append(note)
            ops.extend(more)
            continue
        if kind == "inner" and scheduled and _positive_player_bid(lot.get("bidder")):
            if rng.random() < NPC_CHANCE:
                note = _inner_npc_bid(lot, rng, now)
                if note:
                    notes.append(note)
    return notes, ops


def _positive_player_bid(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _inner_npc_bid(lot: dict[str, Any], rng: random.Random, now: float) -> str:
    npc_types = (
        ("谨慎", 1.05, 1.15, 0.4, ("此物虽好，但价格已高", "再加一次，若不成便放弃")),
        ("激进", 1.15, 1.35, 0.3, ("此物我志在必得！", "再加！我看谁还敢争")),
        ("豪爽", 1.25, 1.50, 0.2, ("这点源石不算什么", "宝物有缘者得之")),
        ("神秘", 1.10, 1.80, 0.1, ("......", "此物与我有缘")),
    )
    npc_type = rng.choices(npc_types, weights=[row[3] for row in npc_types], k=1)[0]
    name = rng.choice(("隐世高人", "仙门长老", "世家公子", "妖族大能", "魔道巨擘", "佛门高僧"))
    comment = rng.choice(npc_type[4])
    price = math.ceil(int(lot.get("price") or 0) * rng.uniform(npc_type[1], npc_type[2]))
    lot.update({"price": price, "bidder": "-1", "bid_ts": now,
                "last_offer_player": -1, "last_offer_price": now * 1000,
                "npcBidder": name, "npcBidType": npc_type[0]})
    return f"【星阁内场】NPC {name}（{npc_type[0]}）加价至 {price:,} 源石：{comment}"


AUCTION_WINDOWS = {"official": (20, 21), "inner": (21, 23)}
AUCTION_EVENT_CHANCE = {"仇恨": 0.25, "死敌": 0.35, "不死不休": 0.50}


def open_kinds_at(now: float) -> set[str]:
    """原版配置：上海时区外场20-21点、内场21-23点。"""
    from datetime import datetime, timedelta, timezone

    hour = datetime.fromtimestamp(float(now), timezone(timedelta(hours=8))).hour
    return {kind for kind, (start, end) in AUCTION_WINDOWS.items()
            if start <= hour < end}


def select_hostile_tianjiao(doc: Any, rows: list[Mapping[str, Any]],
                            world: Mapping[str, Any], now: float,
                            rng: random.Random) -> str | None:
    """按仇恨加权选择一名可用天骄，再按其仇恨档掷拍卖介入率。"""
    from . import tianjiao as tj

    hatred_table = (getattr(doc, "ext", {}) or {}).get("tianjiao_hatred") or {}
    bosses = world.get("bosses") if isinstance(world, Mapping) else {}
    candidates: list[tuple[str, int, str]] = []
    for row in rows:
        name = str(row.get("name") or row.get("名号") or "")
        if not name:
            continue
        try:
            hatred = max(0, int(hatred_table.get(name, 0) or 0))
        except (AttributeError, TypeError, ValueError):
            continue
        level = tj.level_of(hatred)[0]
        if level not in AUCTION_EVENT_CHANCE:
            continue
        boss = bosses.get(name, {}) if isinstance(bosses, Mapping) else {}
        if not isinstance(boss, Mapping):
            boss = {}
        if (float(boss.get("alive_until") or 0) > now
                or float(boss.get("escaped_until") or 0) > now
                or float(boss.get("hp_pct", 1.0) or 0) <= 0):
            continue
        candidates.append((name, hatred, level))
    if not candidates:
        return None
    total = sum(max(1, hatred) for _, hatred, _ in candidates)
    roll = min(1.0, max(0.0, rng.random())) * total
    chosen = candidates[-1]
    for candidate in candidates:
        roll -= max(1, candidate[1])
        if roll <= 0:
            chosen = candidate
            break
    name, _, level = chosen
    return name if rng.random() < AUCTION_EVENT_CHANCE[level] else None


def apply_tianjiao_counterbid(w: dict[str, Any], kind: str, name: str,
                              player_id: str, rng: random.Random,
                              now: float) -> tuple[bool, int]:
    lot = w.get(kind)
    if not isinstance(lot, dict) or not name:
        return False, 0
    targeted = [str(uid) for uid in (lot.get("tianjiaoCounteredPlayers") or [])]
    uid = str(player_id)
    if uid in targeted:
        return False, int(lot.get("price") or 0)
    price = max(1, math.ceil(int(lot.get("price") or 0) * (1.1 + min(1.0, max(0.0, rng.random())) * 0.25)))
    targeted.append(uid)
    lot.update({
        "price": price, "bidder": "-1", "bid_ts": now,
        "last_offer_player": -1, "last_offer_price": now * 1000,
        "tianjiaoBidder": name, "tianjiaoTarget": uid,
        "tianjiaoCounteredPlayers": targeted,
    })
    return True, price


def is_restricted(doc: Any, name: str) -> bool:
    """原版 equipmentTransfer.js 的最小对应：私密/唯一产物禁止上架。"""
    ext = dict(getattr(doc, "ext", None) or {})
    artifacts = (ext.get("forge") or {}).get("artifacts") or {}
    if isinstance(artifacts, Mapping) and name in artifacts:
        return True
    owned = (ext.get("xtzb") or {}).get("owned") or []
    if name in owned:
        return True
    return any(k in name for k in ("岁云的残念", "岁云残念", "无上天阙枝", "不可交易"))


def list_item(w: dict[str, Any], doc: Any, inv: Mapping[str, int],
              arg: str, now: float) -> tuple[bool, str, dict[str, int]]:
    """`#拍卖 物品名*起拍价*数量`（原版无空格 `#拍卖咸鱼宝剑*1000*10`）。"""
    parts = [p.strip() for p in str(arg or "").split("*")]
    if len(parts) < 2 or not parts[0]:
        return False, "格式：#拍卖 物品名*起拍价*数量（数量可省，默认 1）", {}
    name = parts[0]
    try:
        price = int(parts[1])
        amount = int(parts[2]) if len(parts) > 2 else 1
    except (ValueError, IndexError):
        return False, "起拍价与数量必须是正整数（原版 convert2integer 只收 1~13 位）。", {}
    if price <= 0 or price > 9_999_999_999_999 or amount <= 0:
        return False, "起拍价需在 1~13 位正整数，数量需大于 0。", {}
    if isinstance(w.get("player"), dict):
        return False, "玩家拍卖场已有拍品（全服同时仅 1 场），等本场结束再上架。", {}
    last = float(w["last_list"].get(str(doc.uid)) or 0)
    if now - last < LIST_CD_SECONDS:
        left = (LIST_CD_SECONDS - (now - last)) / 3600
        return False, f"【拍卖·上架冷却】上架冷却中，还需 {left:.1f} 小时（原版 24h CD）。", {}
    if int(inv.get(name, 0) or 0) < amount:
        return False, f"纳戒里没有足够的「{name}」（需 {amount} 件）。", {}
    if is_restricted(doc, name):
        return False, f"「{name}」属私密/唯一产物，不可交易。", {}
    w["seq"] += 1
    w["player"] = {
        "id": f"player-{w['seq']}", "kind": "player", "name": name,
        "class": "纳戒", "desc": "玩家寄售", "rarity": 0,
        "amount": amount, "start": price, "price": price,
        "bid_ts": now, "bidder": "0", "seller": str(doc.uid),
    }
    w["last_list"][str(doc.uid)] = now
    return True, (f"已上架「{name}」×{amount}，起拍 {price:,} 灵石。\n"
                  f"{int(INTERVAL_SECONDS / 60)} 分钟无人加价即成交；流拍会退还物品。"), {name: -amount}


def bid(w: dict[str, Any], doc: Any, kind: str, arg: str, now: float,
        rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    lot = w.get(kind)
    if not isinstance(lot, dict):
        return False, f"【{LABELS[kind]}】当前没有拍品。", {}
    min_price = min_raise(int(lot["price"]))
    raw = str(arg or "").strip()
    try:
        price = int(raw) if raw else min_price
    except ValueError:
        return False, "出价需为正整数，或留空自动加价 10%。", {}
    if price < min_price:
        return False, f"每次加价不少于 10%，本次至少 {min_price:,} {currency_of(kind)}。", {}
    uid = str(doc.uid)
    if kind == "player":
        if uid == str(lot.get("seller")):
            return False, "卖家不能给自己抬价。", {}
        if uid == str(lot.get("bidder")):
            return False, "你已是最高出价者，等别人加价。", {}
    ext = dict(getattr(doc, "ext", None) or {})
    if kind == "inner" and not ext.get(INNER_FLAG):
        return False, "星阁内场需先 #星阁内场验资（永久贵宾身份）。", {}
    if kind == "inner":
        from . import yuanshi as _ys
        have = int(_ys.system_of(doc).get("amount") or 0)
    else:
        have = int(getattr(doc, "stones", 0) or 0)
    cur = currency_of(kind)
    if have < price:
        return False, f"{cur}不足：本次需 {price:,}，当前 {have:,}。", {}

    lot["price"] = price
    lot["bidder"] = uid
    lot["bid_ts"] = now
    msg = f"叫价 {price:,} {cur}（{LABELS[kind]}·{lot['name']}），倒计时重置。"

    return True, msg, {}


def verify_inner(doc: Any) -> tuple[bool, str, dict[str, int]]:
    from . import yuanshi as _ys
    ext = getattr(doc, "ext", None)
    if ext is None:
        ext = {}
        doc.ext = ext
    if ext.get(INNER_FLAG):
        return False, "你已是星阁内场贵宾（永久有效，无需续费）。", {}
    y = _ys.system_of(doc)
    have = int(y.get("amount") or 0)
    if have < VERIFY_MIN:
        return False, (f"验资需 {VERIFY_MIN:,} 源石，当前 {have:,}。"
                       f"达标后扣 {VERIFY_COST:,} 源石买断身份。"), {}
    y["amount"] = have - VERIFY_COST
    ext["yuanshi"] = y
    ext[INNER_FLAG] = 1
    return True, f"花费 {VERIFY_COST:,} 源石，获得【星阁内场】永久贵宾身份。", {}


def switch(w: dict[str, Any], action: str, inner: bool, gid: str,
           is_admin: bool) -> tuple[bool, str, dict[str, int]]:
    if not is_admin:
        return False, "星阁开关仅管理员可用。", {}
    key = "enabled2" if inner else "enabled"
    gkey = "groups2" if inner else "groups"
    label = "星阁内场体系" if inner else "星阁体系"
    groups = set(w[gkey])
    if action == "open":
        w[key] = True
        groups.add(gid)
        w[gkey] = sorted(groups)
        return True, (f"【{label}】已在本群开启。\n"
                      "官方拍品将在每日原版时间窗开拍，内场 NPC 每分钟参与竞价。"), {}
    if action == "cancel":
        groups.discard(gid)
        w[gkey] = sorted(groups)
        return True, f"【{label}】已在本群取消广播（全服开关不受影响）。", {}
    w[key] = False
    w[gkey] = []
    w["inner" if inner else "official"] = None
    return True, f"【{label}】已全服关闭，当前官方拍品作废。", {}


def panel(w: dict[str, Any], kind: str, now: float) -> str:
    lot = w.get(kind)
    label = LABELS[kind]
    if not isinstance(lot, dict):
        enabled = w["enabled2"] if kind == "inner" else w["enabled"]
        if kind == "player":
            return "【玩家外场】当前无拍品。发 #拍卖 物品*起拍价*数量 上架。"
        if not enabled:
            return f"【{label}】尚未开启（管理员 #开启{'星阁内场' if kind == 'inner' else '星阁'}体系）。"
        return f"【{label}】已开启，等待每日原版时段（外场20-21点/内场21-23点）定时开拍。"
    left = max(0.0, INTERVAL_SECONDS - (now - float(lot.get("bid_ts") or 0)))
    bidder = str(lot.get("bidder") or "0")
    who = "无人出价" if bidder == "0" else ("神秘 NPC" if bidder == "-1" else bidder)
    return "\n".join([
        f"【{label}】{lot['name']}×{int(lot.get('amount') or 1)}",
        lot.get("desc") or lot.get("class") or "",
        f"起拍 {int(lot['start']):,}｜当前 {int(lot['price']):,} {currency_of(kind)}",
        f"最高：{who}｜剩 {int(left)} 秒（每次出价重置）",
        f"下一次至少 {min_raise(int(lot['price'])):,} {currency_of(kind)}",
    ])


def rules_text() -> str:
    return "\n".join([
        "【星阁 · 规则】对齐原版 apps/Auction/Auction.js + Auction2.js（16 条 rule）",
        "1. 三场独立：玩家外场（灵石，全服仅 1 场）、星阁官方外场（灵石）、星阁内场（源石）。",
        f"2. 加价 ≥10%（ceil 当前价×{MIN_RAISE}）；留空金额即自动按最低加价出价。",
        f"3. 每场 {int(INTERVAL_SECONDS / 60)} 分钟无人加价即结算，每次出价重置倒计时。",
        f"4. 上架 24h CD、全服仅 1 场玩家外场；私密/唯一产物（神兵卡/至宝/岁云残念）禁售。",
        "5. 成交为「最高价全额得标」，**无手续费**；玩家场卖家收全款，官方场货币由系统回收。",
        "6. 流拍退物给卖家；竞得者余额不足按违约取消；NPC 得标不扣款不发货（原版行为）。",
        f"7. 内场验资 {VERIFY_MIN:,} 源石，通过扣 {VERIFY_COST:,} 买断**永久**身份。",
        f"8. 内场 NPC 每分钟有 {int(NPC_CHANCE * 100)}% 概率加价；天骄按个人仇恨档介入外场/内场出价。",
        "9. 官方外场每日20-21点、内场21-23点（上海时区）开拍；后台每分钟处理竞价与结算。",
        "10. 玩家内场（原版 xiuxian:auction2）是死链，未移植；#内场竞价 等同 #星阁内场出价。",
        "11. 数值不折算：本移植源石坊为百万级量级，与原版内场一致。",
    ])


def help_text() -> str:
    return "\n".join([
        "【星阁 · 竞价拍卖】指令一览（本移植统一用带空格写法）",
        "— 玩家外场 —",
        "#拍卖 物品名*起拍价*数量　寄售（24h CD，全服 1 场）",
        "#查看当前拍卖　看本场 + 惰性结算上一场",
        "#竞价 金额　出价（留空自动 +10%）",
        "— 官方星阁（外场 / 灵石） —",
        "#星阁拍卖行　看官方拍品",
        "#星阁出价 金额　对官方拍品出价",
        "#开启星阁体系 / #取消星阁体系 / #关闭星阁体系　管理员开关",
        "— 星阁内场（源石） —",
        "#星阁内场验资　1200 万验资，扣 500 万买断永久身份",
        "#星阁内场拍卖行 / #查看当前内场拍卖　看内场拍品",
        "#星阁内场出价 金额（别名 #内场竞价）　出价",
        "#开启星阁内场体系 / #取消星阁内场体系 / #关闭星阁内场体系　管理员开关",
        "— 其它 —",
        "#星阁帮助　本页　#星阁规则　完整数值口径",
        "详见 #星阁规则：无手续费、无撤拍指令、原版靠 cron 结算。",
    ])
