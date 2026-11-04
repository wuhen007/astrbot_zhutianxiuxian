"""灵市·修仙股市（W5-1，对齐原版 model/lingshiMarket.js 直译）。

机制：
- 全服共享市场：确定性 xorshift PRNG（state.rng），10 分钟一个 slot，
  任意指令触发 `advance` 懒推进（最多回放 1008 tick，交易时段 = 北京时间 8 点后）；
- 8 只股票（低/中/高风险，涨跌停 500~1500bps，波动率 65~210），事件冲击
  （24%/tick，±70~250bps）+ 8 位 NPC 交易流（value/broker/operator/momentum/
  retail/contrarian 六种风格，operator 墨九有 pump/distribute 计划）+
  商会周期（boom/slump/crisis）→ 每 tick 价格步进钳涨跌停；
- 玩家账户（ext["market"]）：持仓/成本/已实现盈亏/手续费/借款；
  买入 30bps 手续费、30 秒 CD、持仓成本上限 10 亿（÷1000 标度 → 100 万）；
- 借款：1 万~5000 万（标度后 1 万~500 万），资产 ×2 上限，日息 10bps、7 天期；
- NPC 交互轻量：#打听（1000 灵石买倾向线索）、#交谈（语录+线索）；
  查账/追问/债务追讨 shortcut（社交深度省略，docstring 标注）。

数值标度：股票初始价 10000 → 1 万灵石/股 = 原版字面价（灵石本身已缩放），
买入上限原版 10 亿持仓成本 → 100 万灵石（按《数值缩放对照表》）。
"""

from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

TICK_MS = 600_000                      # 10 分钟/slot
FEE_BPS = 30
MAX_HOLDING_COST = 1_000_000           # 原版 10 亿 ÷1000
TRADE_CD = 30
MAX_REPLAY = 1008
LOAN_MIN, LOAN_MAX = 10_000, 5_000_000
LOAN_ASSET_MULT = 2
LOAN_DAILY_BPS = 10
LOAN_TERM_TICKS = 7 * 144              # 7 天 ÷ 10 分钟
TIP_COST = 1_000
AUDIT_COST = 5_000

STOCKS = [
    {"id": "1", "name": "丹鼎阁", "sector": "丹药", "risk": "低", "limitBps": 500, "volatility": 65},
    {"id": "2", "name": "天工坊", "sector": "炼器", "risk": "低", "limitBps": 500, "volatility": 75},
    {"id": "3", "name": "灵矿商会", "sector": "矿脉", "risk": "中", "limitBps": 1000, "volatility": 120},
    {"id": "4", "name": "万兽山", "sector": "灵兽", "risk": "中", "limitBps": 1000, "volatility": 130},
    {"id": "5", "name": "四海商盟", "sector": "商路", "risk": "中", "limitBps": 1000, "volatility": 110},
    {"id": "6", "name": "太虚符行", "sector": "符箓", "risk": "中", "limitBps": 1000, "volatility": 130},
    {"id": "7", "name": "问天秘境", "sector": "秘境", "risk": "高", "limitBps": 1500, "volatility": 210},
    {"id": "8", "name": "渡劫仙舟", "sector": "仙舟", "risk": "高", "limitBps": 1500, "volatility": 200},
]

NPCS = [
    {"id": "qian", "name": "钱万三", "title": "四海掌柜", "style": "value"},
    {"id": "bai", "name": "白知微", "title": "丹道客卿", "style": "value"},
    {"id": "lu", "name": "陆听风", "title": "百晓消息贩", "style": "broker"},
    {"id": "mo", "name": "墨九", "title": "黑金操盘客", "style": "operator"},
    {"id": "shen", "name": "沈红绫", "title": "逐浪游资", "style": "momentum"},
    {"id": "han", "name": "韩小满", "title": "散修新客", "style": "retail"},
    {"id": "ning", "name": "宁不争", "title": "逆势老修", "style": "contrarian"},
    {"id": "yan", "name": "燕归鸿", "title": "商路行脚客", "style": "broker"},
]

EVENTS = [
    ("新矿脉现世，商会组织勘探", 1),
    ("宗门采购增加，订单传来利好", 1),
    ("护送商队遇袭，货物损失待核", -1),
    ("炼制失手，交货延期引来质疑", -1),
    ("大宗订单流言四起，尚待商会证实", 1),
    ("账目争议发酵，几家客商暂缓合作", -1),
]

CHAT_LINES = {
    "value": ["低处纳货，高处予人——这是老朽四百年的功课。", "价格终究会回到价值身边，急什么。"],
    "broker": ["嘿嘿，消息嘛……收了钱也只保证一半是真的。", "听说某家商号最近账目不太干净，信不信由你。"],
    "operator": ["独乐乐不如众乐乐，道友不妨与在下同持一股？", "人气所至，价格所向——懂的都懂。"],
    "momentum": ["强势的板块就要追！撤退也要快！", "这波行情还没走完，我再加一点。"],
    "retail": ["涨了涨了！全押全押！", "怎么又跌了……我先撤，呜呜。"],
    "contrarian": ["跌下去的都是黄金坑，越跌我越买。", "别人恐惧我贪婪，仅此而已。"],
}


# ---------------------------------------------------------------- PRNG（xorshift32 直译）

class Rng:
    """原版 state.rng 的 xorshift32——保证同种子全服行情一致。"""

    __slots__ = ("s",)

    def __init__(self, seed: int):
        self.s = int(seed) & 0xFFFFFFFF or 1

    def next(self) -> float:
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x & 0xFFFFFFFF
        return self.s / 0x100000000

    def choice(self, values):
        return values[int(self.next() * len(values)) % len(values)]


def slot_of(now: float) -> int:
    return int(now * 1000) // TICK_MS


def hour_of(slot: int) -> int:
    return time.gmtime(slot * TICK_MS / 1000 + 8 * 3600).tm_hour


def trading_open(slot: int) -> bool:
    return hour_of(slot) >= 8


# ---------------------------------------------------------------- 市场状态

def create_market(now: float, seed: int | None = None) -> dict:
    slot = slot_of(now)
    rng = Rng(seed or random.randrange(1, 0xFFFFFFFF))
    stocks = [dict(item, price=10000, close=10000, day="", changeBps=0, volume=0,
                   netVolume=0, history=[{"slot": slot, "price": 10000}]) for item in STOCKS]
    npcs = []
    for index, item in enumerate(NPCS):
        npcs.append(dict(
            item,
            cash=100_000_000 if item["style"] == "operator" else 20_000_000,
            holdings={s["id"]: {"shares": 100 + index * 20, "cost": (100 + index * 20) * 10000} for s in STOCKS},
            realized=0, fees=0, plan=None,
        ))
    state = {"version": 1, "slot": slot, "rng": rng.s, "stocks": stocks, "npcs": npcs, "news": []}
    add_news(state, "万界灵市开张。初始每股一万灵石；消息与邀约皆含交易对手的立场。")
    return state


def add_news(state: dict, text: str, stock_id: str | None = None, speaker: str | None = None) -> None:
    state["news"].append({"slot": state["slot"], "text": text, "stockId": stock_id, "speaker": speaker})
    state["news"] = state["news"][-40:]


def _limits(stock: dict) -> tuple[int, int]:
    return (max(1, stock["close"] * (10000 - stock["limitBps"]) // 10000),
            max(1, stock["close"] * (10000 + stock["limitBps"]) // 10000))


def _fee(value: int) -> int:
    return -(-int(value) * FEE_BPS // 10000)   # ceil


def _npc_trade(state: dict, npc: dict, stock: dict, side: str, wanted: int, rng: Rng) -> int:
    price = stock["price"]
    shares = min(wanted, int(npc["cash"] // price) if side == "buy" else
                 npc["holdings"].get(stock["id"], {}).get("shares", 0))
    shares = max(0, min(shares, 100_000))
    if shares <= 0:
        return 0
    cost = shares * price
    fee = _fee(cost)
    hold = npc["holdings"].setdefault(stock["id"], {"shares": 0, "cost": 0})
    if side == "buy":
        npc["cash"] -= cost + fee
        hold["cost"] += cost
        hold["shares"] += shares
    else:
        avg = hold["cost"] // max(1, hold["shares"])
        npc["cash"] += cost - fee
        npc["realized"] += cost - fee - avg * shares
        hold["cost"] -= avg * shares
        hold["shares"] -= shares
    npc["fees"] += fee
    stock["volume"] += shares
    stock["netVolume"] += shares if side == "buy" else -shares
    return shares if side == "buy" else -shares


def _operator_action(state: dict, npc: dict, flows: dict, rng: Rng) -> None:
    plan = npc.get("plan")
    active = [s for s in state["stocks"] if s.get("delistedAt") is None]
    if not plan:
        if active and rng.next() < 0.2:
            target = rng.choice(active)
            npc["plan"] = {"stockId": target["id"], "phase": "accumulate", "left": 3}
            add_news(state, f"【{npc['name']}】近日频频出入{target['name']}。", target["id"], npc["name"])
        return
    stock = next((s for s in state["stocks"] if s["id"] == plan["stockId"]), None)
    if not stock or stock.get("delistedAt") is not None:
        npc["plan"] = None
        return
    phase = plan["phase"]
    if phase == "accumulate":
        flows[stock["id"]] += _npc_trade(state, npc, stock, "buy", 200, rng)
        plan["phase"] = "pump"
    elif phase == "pump":
        flows[stock["id"]] += _npc_trade(state, npc, stock, "buy", 500, rng)
        add_news(state, f"【{npc['name']}】邀约持仓者共同「护盘」{stock['name']}。", stock["id"], npc["name"])
        plan["phase"] = "distribute"
    elif phase == "distribute":
        flows[stock["id"]] -= _npc_trade(state, npc, stock, "sell", 600, rng)
        plan["phase"] = "cooldown"
    else:
        npc["plan"] = None


def _update_cycle(state: dict, stock: dict, rng: Rng) -> None:
    cyc = stock.get("cycle")
    if cyc:
        if state["slot"] >= cyc["endSlot"]:
            if cyc["outcome"] == "bankruptcy":
                stock["delistedAt"] = state["slot"]
                add_news(state, f"【{stock['name']}】资不抵债，商会破产摘牌！", stock["id"])
            else:
                add_news(state, f"【{stock['name']}】走出阴霾，生意重回正轨。", stock["id"])
            stock["cycle"] = None
        return
    if rng.next() < 0.002:
        kind = rng.choice(["boom", "slump", "crisis"])
        length = 6 + int(rng.next() * 18)
        stock["cycle"] = {
            "type": kind, "startSlot": state["slot"], "endSlot": state["slot"] + length,
            "outcome": "recovery" if kind != "crisis" else ("bankruptcy" if rng.next() < 0.5 else "recovery"),
            "driftBps": {"boom": 30 + int(rng.next() * 90),
                         "slump": -(30 + int(rng.next() * 90)),
                         "crisis": -(80 + int(rng.next() * 220))}[kind],
        }
        add_news(state, {"boom": f"【{stock['name']}】风口已至，行情启动！",
                         "slump": f"【{stock['name']}】行业寒潮，生意日渐惨淡。",
                         "crisis": f"【{stock['name']}】爆发商会危机，前景未卜！"}[kind], stock["id"])


def tick_market(state: dict) -> None:
    rng = Rng(state["rng"])
    for stock in state["stocks"]:
        if stock.get("delistedAt") is None and stock.get("day") != _day_of(state["slot"]):
            stock["close"] = stock["price"]
            stock["day"] = _day_of(state["slot"])
            stock["volume"] = 0
    if not trading_open(state["slot"]):
        state["rng"] = rng.s
        return
    for stock in state["stocks"]:
        _update_cycle(state, stock, rng)
    active = [s for s in state["stocks"] if s.get("delistedAt") is None]
    if not active:
        state["rng"] = rng.s
        return
    flows = {s["id"]: 0 for s in state["stocks"]}
    shocks = {s["id"]: 0 for s in state["stocks"]}
    if rng.next() < 0.24:
        stock = rng.choice(active)
        text, direction = rng.choice(EVENTS)
        shocks[stock["id"]] = direction * (70 + int(rng.next() * 180))
        add_news(state, f"{stock['name']}：{text}。", stock["id"])
    for npc in state["npcs"]:
        state["rng"] = rng.s
        if npc["style"] == "operator":
            _operator_action(state, npc, flows, rng)
            continue
        if rng.next() < 0.28:
            continue
        bai_first = npc["id"] == "bai" and state["stocks"][0].get("delistedAt") is None and rng.next() < 0.65
        stock = state["stocks"][0] if bai_first else rng.choice(active)
        trend = stock["changeBps"]
        offset = (stock["price"] / stock["close"] - 1) * 10000
        buying = rng.next() < 0.5
        if npc["style"] == "value":
            buying = offset < -50 or (offset < 80 and rng.next() < 0.55)
        elif npc["style"] == "contrarian":
            buying = trend < 0
        elif npc["style"] in ("momentum", "retail"):
            buying = trend >= 0
        shares = 30 + int(rng.next() * (400 if npc["style"] == "momentum" else 150))
        flows[stock["id"]] += _npc_trade(state, npc, stock, "buy" if buying else "sell", shares, rng)
    common = round((rng.next() - 0.5) * 60)
    for stock in active:
        previous = stock["price"]
        lower, upper = _limits(stock)
        pressure = max(-180, min(180, round(flows[stock["id"]] / 4)))
        step = round((rng.next() - 0.5) * stock["volatility"] * 2 + common
                     + shocks[stock["id"]] + pressure + (stock.get("cycle") or {}).get("driftBps", 0))
        stock["price"] = max(lower, min(upper, round(previous * (10000 + step) / 10000)))
        stock["changeBps"] = round((stock["price"] / previous - 1) * 10000)
        stock["netVolume"] = flows[stock["id"]]
        stock["history"].append({"slot": state["slot"], "price": stock["price"]})
        stock["history"] = stock["history"][-160:]
    state["rng"] = rng.s


def _day_of(slot: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(slot * TICK_MS / 1000 + 8 * 3600))


def advance(state: dict, now: float) -> dict:
    """懒推进到当前 slot（最多回放 MAX_REPLAY）。返回同引用。"""
    target = slot_of(now)
    steps = 0
    while state["slot"] < target and steps < MAX_REPLAY:
        state["slot"] += 1
        tick_market(state)
        steps += 1
    return state


# ---------------------------------------------------------------- 玩家账户

def account_of(doc: PlayerDoc) -> dict:
    acc = doc.ext.get("market")
    if not isinstance(acc, dict) or acc.get("version") != 1:
        acc = {"version": 1, "holdings": {}, "invested": 0, "realized": 0, "fees": 0,
               "last_trade": 0.0, "loan": None}
        doc.ext["market"] = acc
    return acc


def find_stock(state: dict, value: str) -> dict | None:
    return next((s for s in state["stocks"] if s["id"] == value.strip() or s["name"] == value.strip()), None)


def buy(state: dict, doc: PlayerDoc, stock: dict, shares: int, now: float) -> tuple[bool, str]:
    if stock.get("delistedAt") is not None:
        return False, f"【{stock['name']}】已摘牌，无法交易。"
    shares = int(shares)
    if shares <= 0 or shares > 100_000:
        return False, "买入股数须在 1~100000 之间。"
    acc = account_of(doc)
    if now - float(acc.get("last_trade") or 0) < TRADE_CD:
        return False, f"交易过于频繁，{TRADE_CD} 秒冷却。"
    price = int(stock["price"])
    cost = shares * price
    fee = _fee(cost)
    if doc.stones < cost + fee:
        return False, f"灵石不足：需 {cost + fee:,}（股价 {price:,}×{shares} + 手续费 {fee:,}）。"
    invested = sum(h["shares"] * find_stock(state, sid)["price"] for sid, h in acc["holdings"].items())
    if invested + cost > MAX_HOLDING_COST:
        return False, f"持仓市值上限 {MAX_HOLDING_COST:,} 灵石，当前已达 {invested:,}。"
    doc.stones -= cost + fee
    hold = acc["holdings"].setdefault(stock["id"], {"shares": 0, "cost": 0})
    hold["shares"] += shares
    hold["cost"] += cost
    acc["invested"] += cost
    acc["fees"] += fee
    acc["last_trade"] = now
    return True, (f"买入【{stock['name']}】{shares:,} 股 @ {price:,}，花费 {cost + fee:,} 灵石（含手续费 {fee:,}）。\n"
                  f"现价涨跌：{stock['changeBps']:+.0f}bps")


def sell(state: dict, doc: PlayerDoc, stock: dict, shares: int, now: float) -> tuple[bool, str]:
    if stock.get("delistedAt") is not None:
        return False, f"【{stock['name']}】已摘牌，持仓作废。"
    acc = account_of(doc)
    hold = acc["holdings"].get(stock["id"])
    if not hold or hold["shares"] <= 0:
        return False, f"你没有【{stock['name']}】持仓。"
    shares = min(int(shares), hold["shares"]) if int(shares) > 0 else hold["shares"]
    if shares <= 0:
        return False, "卖出股数须为正（填 -1 清仓）。"
    if now - float(acc.get("last_trade") or 0) < TRADE_CD:
        return False, f"交易过于频繁，{TRADE_CD} 秒冷却。"
    price = int(stock["price"])
    gross = shares * price
    fee = _fee(gross)
    avg = hold["cost"] // max(1, hold["shares"])
    profit = gross - avg * shares - fee
    doc.stones += gross - fee
    hold["shares"] -= shares
    hold["cost"] -= avg * shares
    acc["realized"] += profit
    acc["fees"] += fee
    acc["last_trade"] = now
    if hold["shares"] == 0:
        acc["holdings"].pop(stock["id"], None)
    return True, (f"卖出【{stock['name']}】{shares:,} 股 @ {price:,}，回款 {gross - fee:,}（手续费 {fee:,}）。\n"
                  f"本笔盈亏：{profit:+,} 灵石｜累计已实现：{acc['realized']:+,}")


def take_loan(state: dict, doc: PlayerDoc, amount: int, now: float) -> tuple[bool, str]:
    acc = account_of(doc)
    if acc.get("loan"):
        return False, "你已有未结清的借款（#还款 或 #债务 查看）。"
    amount = int(amount)
    if not LOAN_MIN <= amount <= LOAN_MAX:
        return False, f"借款额度 {LOAN_MIN:,} ~ {LOAN_MAX:,} 灵石。"
    net_worth = doc.stones + sum(h["shares"] * find_stock(state, sid)["price"]
                                 for sid, h in account_of(doc)["holdings"].items())
    if amount > net_worth * LOAN_ASSET_MULT:
        return False, f"借款不得超过身家（{net_worth:,}）的 2 倍。"
    doc.stones += amount
    acc["loan"] = {"principal": amount, "startSlot": state["slot"], "dueSlot": state["slot"] + LOAN_TERM_TICKS}
    return True, (f"【钱万三】拍板借你 {amount:,} 灵石——日息 {LOAN_DAILY_BPS}bps，"
                  f"7 天内连本带息 #还款，逾期利滚利，莫怪商号无情。")


def repay(state: dict, doc: PlayerDoc) -> tuple[bool, str]:
    acc = account_of(doc)
    loan = acc.get("loan")
    if not loan:
        return False, "你没有未结清的借款。"
    days = max(0, (min(state["slot"], loan["dueSlot"]) - loan["startSlot"])) / 144
    owed = int(loan["principal"] * (1 + LOAN_DAILY_BPS / 10000 * days))
    overdue = state["slot"] > loan["dueSlot"]
    if overdue:
        owed = int(owed * 1.5)
    if doc.stones < owed:
        return False, f"还款需 {owed:,} 灵石（本金 {loan['principal']:,} + 利息），当前 {doc.stones:,}。"
    doc.stones -= owed
    acc["loan"] = None
    return True, (f"还清 {owed:,} 灵石（{'逾期罚息 1.5 倍' if overdue else '按期'}）。"
                  f"【钱万三】笑道：「好信誉，下次再来。」")


def text(state: dict, doc: PlayerDoc | None = None) -> str:
    lines = ["--- 万界灵市 ---",
             f"行情时段：{'开市' if trading_open(state['slot']) else '休市（8 点后开市）'}"]
    for s in state["stocks"]:
        if s.get("delistedAt") is not None:
            lines.append(f"· {s['name']}［已摘牌］")
            continue
        pct = s["changeBps"] / 100
        lines.append(f"· {s['name']}（{s['sector']}·{s['risk']}险）：{s['price']:,} 灵石"
                     f"（{pct:+.2f}%）")
    news = state["news"][-3:]
    if news:
        lines.append("近日行情：")
        lines += [f"  · {n['text']}" for n in news]
    if doc:
        acc = account_of(doc)
        if acc.get("loan"):
            lines.append("⚠ 你有未结清借款（#还款）。")
    lines.append("交易：#买入 名称*股数｜#卖出 名称*股数（-1 清仓）｜#我的股票｜#股票走势 名称")
    lines.append("情报：#打听（1000 灵石）｜#交谈 人物名｜#借款 数量｜#还款｜#灵市收益榜")
    return "\n".join(lines)


def account_text(state: dict, doc: PlayerDoc) -> str:
    acc = account_of(doc)
    lines = ["--- 我的灵市账户 ---"]
    total_value = 0
    for sid, h in acc["holdings"].items():
        stock = find_stock(state, sid)
        if not stock:
            continue
        value = h["shares"] * stock["price"]
        total_value += value
        lines.append(f"· {stock['name']}：{h['shares']:,} 股｜成本 {h['cost']:,}｜"
                     f"市值 {value:,}｜浮盈 {value - h['cost']:+,}")
    if not acc["holdings"]:
        lines.append("暂无持仓。")
    lines.append(f"已实现盈亏：{acc['realized']:+,}｜累计手续费：{acc['fees']:,}")
    if acc.get("loan"):
        lines.append(f"借款：{acc['loan']['principal']:,}（到期 #还款）")
    lines.append(f"持仓总市值：{total_value:,}｜灵石：{int(doc.stones):,}")
    return "\n".join(lines)


def trend_text(state: dict, value: str) -> str:
    stock = find_stock(state, value)
    if not stock:
        return f"灵市没有「{value}」这只票。可选：{'、'.join(s['name'] for s in state['stocks'])}"
    his = stock["history"][-16:]
    spark = " ".join(str(p["price"]) for p in his)
    lines = [f"--- {stock['name']} 走势 ---",
             f"现价：{stock['price']:,}｜今日涨跌：{stock['changeBps'] / 100:+.2f}%",
             f"近 {len(his)} tick：{spark}",
             f"今日成交量：{stock['volume']:,}｜净流：{stock['netVolume']:+,}"]
    if stock.get("cycle"):
        lines.append(f"商会周期：{stock['cycle']['type']}（至第 {stock['cycle']['endSlot']} tick）")
    return "\n".join(lines)


def tip(state: dict, doc: PlayerDoc) -> tuple[bool, str]:
    """#打听：花 1000 灵石向百晓消息贩买一条倾向线索。"""
    if doc.stones < TIP_COST:
        return False, f"打听完需 {TIP_COST:,} 灵石茶水费。"
    doc.stones -= TIP_COST
    rng = random.Random(f"{doc.uid}:tip:{state['slot']}")
    npc = rng.choice(NPCS)
    stock = rng.choice([s for s in state["stocks"] if s.get("delistedAt") is None])
    lean = "看多" if (stock["changeBps"] < 0 and npc["style"] == "contrarian") or \
                     (stock["changeBps"] > 0 and npc["style"] in ("momentum", "retail")) else "看空"
    hint = rng.choice(CHAT_LINES[npc["style"]])
    return True, (f"【{npc['name']}·{npc['title']}】压低声音：\n"
                  f"「{stock['name']}嘛……老夫近来{lean}。」\n"
                  f"「{hint}」\n"
                  f"（茶水费 {TIP_COST:,} 灵石；消息真假，概不保证）")


def chat(state: dict, name: str) -> str:
    npc = next((n for n in NPCS if n["name"] == name.strip() or n["id"] == name.strip()), None)
    if not npc:
        return f"灵市没有「{name}」这位人物。可选：{'、'.join(n['name'] for n in NPCS)}"
    rng = random.Random(f"chat:{state['slot']}:{name}")
    line = rng.choice(CHAT_LINES[npc["style"]])
    stock = rng.choice([s for s in state["stocks"] if s.get("delistedAt") is None])
    return (f"【{npc['name']}·{npc['title']}】\n"
            f"「{line}」\n"
            f"（此人近来常在{stock['name']}进出，风格：{npc['style']}）")
