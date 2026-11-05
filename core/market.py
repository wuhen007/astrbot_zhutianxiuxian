"""万界灵市（W5-1，对齐原版 model/lingshiMarket.js 直译）。

措辞约定：对外文案一律规避股市字眼——标的称「灵票」、量词用「张」、
股价称「市价」；仅代码注释保留原版术语对照。

机制：
- 全服共享市场：确定性 xorshift PRNG（state.rng），10 分钟一个 slot，
  任意指令触发 `advance` 懒推进（最多回放 1008 tick，交易时段 = 北京时间 8 点后）；
- 8 张灵票（低/中/高风险，涨跌停 500~1500bps，波动率 65~210），事件冲击
  （24%/tick，±70~250bps）+ 8 位 NPC 交易流（value/broker/operator/momentum/
  retail/contrarian 六种风格，operator 墨九有 pump/distribute 计划）+
  商会周期（boom/slump/crisis）→ 每 tick 价格步进钳涨跌停；
- 玩家账户（ext["market"]）：持仓/成本/已实现盈亏/手续费/借款；
  买入 30bps 手续费、30 秒 CD、持仓成本上限 10 亿（÷1000 标度 → 100 万）；
- 借款：1 万~5000 万（标度后 1 万~500 万），资产 ×2 上限，日息 10bps、7 天期；
- NPC 交互轻量：#打听（1000 灵石买倾向线索）、#交谈（语录+线索）；
  查账/追问/债务追讨 shortcut（社交深度省略，docstring 标注）。

数值标度：灵票初始价 10000 → 1 万灵石/张 = 原版字面价（灵石本身已缩放），
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
    "operator": ["独乐乐不如众乐乐，道友不妨与在下同持一张？", "人气所至，价格所向——懂的都懂。"],
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
            realized=0, fees=0, plan=None, trades=[],
        ))
    state = {"version": 1, "slot": slot, "rng": rng.s, "stocks": stocks, "npcs": npcs, "news": []}
    add_news(state, "万界灵市开张。初始每张一万灵石；消息与邀约皆含交易对手的立场。")
    return state


def add_news(state: dict, text: str, stock_id: str | None = None, speaker: str | None = None) -> None:
    state["news"].append({"slot": state["slot"], "text": text, "stockId": stock_id, "speaker": speaker})
    state["news"] = state["news"][-80:]


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
    npc.setdefault("trades", []).append(
        {"slot": state["slot"], "stockId": stock["id"], "side": side,
         "shares": shares, "price": price})
    npc["trades"] = npc["trades"][-8:]
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
    # W6-1 社交/债务扩展键；旧档缺键时补齐，不覆盖已有值
    acc.setdefault("intelCost", 0)      # 打听/查账累计支出
    acc.setdefault("financeCost", 0)    # 已付利息
    acc.setdefault("contacts", {})      # npcId -> {favor, verified, wrong}
    acc.setdefault("tips", [])          # 打听/查账记录（追问核验用）
    acc.setdefault("chats", {})         # npcId -> {slot, message}，同报价时段缓存
    acc.setdefault("trades", [])        # 本人最近成交
    return acc


def find_stock(state: dict, value: str) -> dict | None:
    return next((s for s in state["stocks"] if s["id"] == value.strip() or s["name"] == value.strip()), None)


def buy(state: dict, doc: PlayerDoc, stock: dict, shares: int, now: float) -> tuple[bool, str]:
    if stock.get("delistedAt") is not None:
        return False, f"【{stock['name']}】已摘牌，无法交易。"
    shares = int(shares)
    if shares <= 0 or shares > 100_000:
        return False, "买入张数须在 1~100000 之间。"
    acc = account_of(doc)
    ds = debt_status(state, doc)
    if ds["overdue"] or ds["insolvent"]:
        return False, "【钱万三】逾期或资不抵债，暂停新买入（#还款 后可恢复）。"
    if now - float(acc.get("last_trade") or 0) < TRADE_CD:
        return False, f"交易过于频繁，{TRADE_CD} 秒冷却。"
    price = int(stock["price"])
    cost = shares * price
    fee = _fee(cost)
    if doc.stones < cost + fee:
        return False, f"灵石不足：需 {cost + fee:,}（市价 {price:,}×{shares} 张 + 手续费 {fee:,}）。"
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
    return True, (f"买入【{stock['name']}】{shares:,} 张 @ {price:,}，花费 {cost + fee:,} 灵石（含手续费 {fee:,}）。\n"
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
        return False, "卖出张数须为正（填 -1 清仓）。"
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
    return True, (f"卖出【{stock['name']}】{shares:,} 张 @ {price:,}，回款 {gross - fee:,}（手续费 {fee:,}）。\n"
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
    acc["loan"] = {"principal": amount, "initialPrincipal": amount,
                   "interest": 0, "interestCharged": 0,
                   "startSlot": state["slot"], "dueSlot": state["slot"] + LOAN_TERM_TICKS}
    return True, (f"【钱万三】拍板借你 {amount:,} 灵石——日息 {LOAN_DAILY_BPS}bps，"
                  f"7 天内连本带息 #还款，逾期利滚利，莫怪商号无情。")


def accrue_loan(state: dict, doc: PlayerDoc) -> None:
    """按经过的 slot 计单利（离线同样计息，息不生息，封顶本金）。"""
    acc = account_of(doc)
    loan = acc.get("loan")
    if not loan:
        return
    cap = int(loan.get("initialPrincipal", loan["principal"]))
    days = max(0, min(state["slot"], loan["dueSlot"]) - loan["startSlot"]) / 144
    total = min(cap, int(cap * LOAN_DAILY_BPS / 10000 * days))
    loan["interest"] = max(0, total - int(loan.get("interestCharged", 0)))


def debt_status(state: dict, doc: PlayerDoc) -> dict:
    """原版 debtStatus：逾期 / 资不抵债判定（buy 前置检查）。"""
    acc = account_of(doc)
    loan = acc.get("loan")
    if not loan:
        return {"has": False, "overdue": False, "insolvent": False, "debt": 0,
                "net": int(doc.stones), "principal": 0, "interest": 0}
    accrue_loan(state, doc)
    principal = int(loan["principal"])
    interest = int(loan["interest"])
    debt = principal + interest
    liquidation = 0
    for sid, h in acc["holdings"].items():
        s = find_stock(state, sid)
        if s and s.get("delistedAt") is None:
            liquidation += int(h["shares"]) * int(s["price"])
    net = int(doc.stones) + liquidation - debt
    return {"has": True, "overdue": state["slot"] > loan["dueSlot"],
            "insolvent": net < 0, "debt": debt, "net": net,
            "principal": principal, "interest": interest}


def repay(state: dict, doc: PlayerDoc, amount: int | None = None) -> tuple[bool, str]:
    """还款：不传 amount = 全额结清（沿用本移植 1.5 倍逾期罚息）；
    传 amount = 部分还款，先息后本（原版 M:445-458）。
    """
    acc = account_of(doc)
    loan = acc.get("loan")
    if not loan:
        return False, "你没有未结清的借款。"
    accrue_loan(state, doc)
    principal, interest = int(loan["principal"]), int(loan["interest"])
    debt = principal + interest
    overdue = state["slot"] > loan["dueSlot"]
    if amount is None:
        owed = int(debt * 1.5) if overdue else debt
        if doc.stones < owed:
            return False, f"还款需 {owed:,} 灵石（本金 {principal:,} + 利息 {interest:,}），当前 {doc.stones:,}。"
        doc.stones -= owed
        acc["loan"] = None
        return True, (f"还清 {owed:,} 灵石（{'逾期罚息 1.5 倍' if overdue else '按期'}）。"
                      f"【钱万三】笑道：「好信誉，下次再来。」")
    pay = min(int(amount), int(doc.stones), debt)
    if pay < 1:
        return False, "还款数量须为正，或灵石不足。"
    ip = min(pay, interest)
    pp = pay - ip
    loan["interest"] = interest - ip
    loan["interestCharged"] = int(loan.get("interestCharged", 0)) + ip
    loan["principal"] = max(0, principal - pp)
    doc.stones -= pay
    acc["financeCost"] = int(acc.get("financeCost", 0)) + ip
    if loan["principal"] <= 0 and loan["interest"] <= 0:
        acc["loan"] = None
        return True, f"已还清 {pay:,} 灵石（先息后本），【钱万三】收起借据。"
    return True, (f"还款 {pay:,} 灵石（先息 {ip:,} / 后本 {pp:,}）。"
                  f"剩余本金 {loan['principal']:,}、利息 {loan['interest']:,}。")


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
    lines.append("交易：#买入 名称*张数｜#卖出 名称*张数（-1 清仓）｜#我的灵票｜#灵票走势 名称")
    lines.append("情报：#灵市人物｜#打听 人物名 商会｜#灵市查账 人物名｜#灵市追问 人物名｜#灵市消息")
    lines.append("钱庄：#借款 数量｜#还款 数量/全部｜#灵市债务｜榜单：#灵市收益榜")
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
        lines.append(f"· {stock['name']}：{h['shares']:,} 张｜成本 {h['cost']:,}｜"
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
        return f"灵市没有「{value}」这家商会。可选：{'、'.join(s['name'] for s in state['stocks'])}"
    his = stock["history"][-16:]
    spark = " ".join(str(p["price"]) for p in his)
    lines = [f"--- {stock['name']} 走势 ---",
             f"现价：{stock['price']:,}｜今日涨跌：{stock['changeBps'] / 100:+.2f}%",
             f"近 {len(his)} tick：{spark}",
             f"今日成交量：{stock['volume']:,}｜净流：{stock['netVolume']:+,}"]
    if stock.get("cycle"):
        lines.append(f"商会周期：{stock['cycle']['type']}（至第 {stock['cycle']['endSlot']} tick）")
    return "\n".join(lines)


def find_npc(value: str) -> dict | None:
    return next((n for n in NPCS if n["name"] == (value or "").strip()
                 or n["id"] == (value or "").strip()), None)


def tip(state: dict, doc: PlayerDoc, npc_name: str | None = None,
        stock_name: str | None = None) -> tuple[bool, str]:
    """#打听 / #灵市打听：1000 灵石买倾向线索，留档供 #灵市追问 30 分钟后核验。

    shortcut: 原版 adverse 立场欺骗的完整文案省略，改为 favor 决定 60%~70% 命中率。
    """
    if doc.stones < TIP_COST:
        return False, f"打听完需 {TIP_COST:,} 灵石茶水费。"
    npc = find_npc(npc_name) if npc_name else None
    if npc_name and not npc:
        return False, f"灵市没有「{npc_name}」这位人物（#灵市人物 查名单）。"
    stock = find_stock(state, stock_name) if stock_name else None
    if stock_name and (not stock or stock.get("delistedAt") is not None):
        return False, f"「{stock_name}」已摘牌或不存在，打听无门。"
    tag = f"{npc['id'] if npc else ''}:{stock['id'] if stock else ''}"
    rng = random.Random(f"{doc.uid}:tip:{state['slot']}:{tag}")
    npc = npc or rng.choice(NPCS)
    stock = stock or rng.choice([s for s in state["stocks"] if s.get("delistedAt") is None])
    bull = (stock["changeBps"] < 0 and npc["style"] == "contrarian") or \
           (stock["changeBps"] > 0 and npc["style"] in ("momentum", "retail"))
    direction = 1 if bull else -1
    favor = int(account_of(doc)["contacts"].get(npc["id"], {}).get("favor", 0) or 0)
    if rng.random() >= 0.60 + favor / 1000:   # 熟悉度把命中率从 60% 提到 70%
        direction = -direction
    lean = "看多" if direction > 0 else "看空"
    hint = rng.choice(CHAT_LINES[npc["style"]])
    acc = account_of(doc)
    doc.stones -= TIP_COST
    acc["intelCost"] = int(acc.get("intelCost", 0) or 0) + TIP_COST
    acc["tips"].append({"id": f"{state['slot']}:{npc['id']}:{len(acc['tips'])}",
                        "at": state["slot"] * TICK_MS, "npcId": npc["id"],
                        "stockId": stock["id"], "price": int(stock["price"]),
                        "direction": direction, "resolved": False, "kind": "tip",
                        "message": lean})
    acc["tips"] = acc["tips"][-40:]
    return True, (f"【{npc['name']}·{npc['title']}】压低声音：\n"
                  f"「{stock['name']}嘛……老夫近来{lean}。」\n"
                  f"「{hint}」\n"
                  f"（茶水费 {TIP_COST:,} 灵石；30 分钟后 #灵市追问 {npc['name']} 可核验）")


def chat(state: dict, name: str, doc: PlayerDoc | None = None) -> str:
    npc = find_npc(name)
    if not npc:
        return f"灵市没有「{name}」这位人物。可选：{'、'.join(n['name'] for n in NPCS)}"
    rng = random.Random(f"chat:{state['slot']}:{name}")
    line = rng.choice(CHAT_LINES[npc["style"]])
    stock = rng.choice([s for s in state["stocks"] if s.get("delistedAt") is None])
    note = ""
    if doc is not None:
        acc = account_of(doc)
        c = acc["contacts"].setdefault(npc["id"], {"favor": 0, "verified": 0, "wrong": 0})
        cache = acc["chats"].get(npc["id"])
        if cache and cache.get("slot") == state["slot"]:
            note = f"\n（熟悉度 {c['favor']}/100；同一报价时段重复交谈不涨好感）"
        else:
            c["favor"] = min(100, int(c["favor"]) + 1)
            acc["chats"][npc["id"]] = {"slot": state["slot"], "message": line}
            note = f"\n（熟悉度 +1 → {c['favor']}/100）"
    return (f"【{npc['name']}·{npc['title']}】\n"
            f"「{line}」\n"
            f"（此人近来常在{stock['name']}进出，风格：{npc['style']}）" + note)


# ---------------------------------------------------------------- W6-1 社交 / 查账 / 追问 / 债务

def people_text(state: dict, doc: PlayerDoc) -> str:
    """#灵市人物：8 位 NPC 与熟悉度、兑现记录。"""
    acc = account_of(doc)
    lines = ["--- 灵市人物 ---"]
    for n in NPCS:
        c = acc["contacts"].get(n["id"], {})
        lines.append(f"· {n['name']}（{n['title']}·{n['style']}）｜熟悉度 {int(c.get('favor', 0))}/100"
                     f"｜兑现 {int(c.get('verified', 0))} / 未兑现 {int(c.get('wrong', 0))}")
    lines.append("交谈：#交谈 人物名｜打听：#打听 人物名 商会｜核验：#灵市追问 人物名")
    return "\n".join(lines)


def audit(state: dict, doc: PlayerDoc, npc_name: str,
          stock_name: str | None = None) -> tuple[bool, str]:
    """#灵市查账：5000 灵石查 NPC 真实成交（同一报价时段同一人只收一次费）。"""
    npc = find_npc(npc_name)
    if not npc:
        return False, f"灵市没有「{npc_name}」这位人物（#灵市人物 查名单）。"
    stock = find_stock(state, stock_name) if stock_name else None
    acc = account_of(doc)
    cache_id = f"{state['slot']}:{npc['id']}:audit"
    cached = any(t.get("cacheId") == cache_id for t in acc["tips"])
    fee = 0 if cached else AUDIT_COST
    if fee and doc.stones < fee:
        return False, f"查账需 {fee:,} 灵石，当前 {doc.stones:,}。"
    if fee:
        doc.stones -= fee
        acc["intelCost"] = int(acc.get("intelCost", 0) or 0) + fee
        acc["tips"].append({"id": cache_id, "at": state["slot"] * TICK_MS,
                            "npcId": npc["id"], "stockId": (stock or {}).get("id", ""),
                            "resolved": True, "kind": "audit", "cacheId": cache_id})
        acc["tips"] = acc["tips"][-40:]
    ns = next((n for n in state["npcs"] if n["id"] == npc["id"]), {})
    trades = [t for t in ns.get("trades", [])
              if not stock or t["stockId"] == stock["id"]][-4:]
    lines = [f"--- 查账 · {npc['name']} ---",
             f"（查账费 {fee:,} 灵石{'，本时段已付免收' if cached else ''}；只披露已发生成交，不含下一步计划）"]
    if trades:
        for t in trades:
            nm = next((s["name"] for s in state["stocks"] if s["id"] == t["stockId"]), t["stockId"])
            lines.append(f"· 第 {t['slot']} tick｜{nm}｜{'买' if t['side'] == 'buy' else '卖'}"
                         f" {t['shares']:,} 张 @ {t['price']:,}")
    else:
        lines.append("· 暂无成交记录。")
    hold = (ns.get("holdings", {}).get(stock["id"], {}) if stock else {})
    if stock:
        lines.append(f"· 当前持有【{stock['name']}】{int(hold.get('shares', 0)):,} 张")
    lines.append(f"· 可用灵石 {int(ns.get('cash', 0)):,}｜历史已实现盈亏 {int(ns.get('realized', 0)):+,}")
    return True, "\n".join(lines)


def followup(state: dict, doc: PlayerDoc, npc_name: str) -> tuple[bool, str]:
    """#灵市追问：满 30 分钟且未核验的打听，按首个开市报价核验方向。"""
    npc = find_npc(npc_name)
    if not npc:
        return False, f"灵市没有「{npc_name}」这位人物。"
    acc = account_of(doc)
    now_ms = state["slot"] * TICK_MS
    pend = [t for t in acc["tips"] if t.get("npcId") == npc["id"]
            and t.get("kind") == "tip" and not t.get("resolved")
            and now_ms - float(t.get("at", 0)) >= 30 * 60 * 1000]
    if not pend:
        return False, "尚无满 30 分钟且未核验的消息（打听后等 3 个 tick 再追问）。"
    t = pend[0]
    t["resolved"] = True
    stock = next((s for s in state["stocks"] if s["id"] == t["stockId"]), None)
    ref_slot = -(-int(t["at"] + 30 * 60 * 1000) // TICK_MS)   # ceil
    point = next((h for h in (stock or {}).get("history", []) if h["slot"] >= ref_slot), None)
    if stock and stock.get("delistedAt") is not None:
        point = {"price": 0, "slot": ref_slot}
    c = acc["contacts"].setdefault(npc["id"], {"favor": 0, "verified": 0, "wrong": 0})
    if point is None:
        return True, "历史已超出保存范围（160 tick），本条结案但不计兑现。"
    correct = (int(point["price"]) - int(t["price"])) * int(t["direction"]) > 0
    if correct:
        c["verified"] = int(c["verified"]) + 1
        c["favor"] = min(100, int(c["favor"]) + 1)
        verdict = "兑现（熟悉度 +1）"
    else:
        c["wrong"] = int(c["wrong"]) + 1
        c["favor"] = max(0, int(c["favor"]) - 3)
        verdict = "未兑现（熟悉度 -3）"
    return True, (f"追问【{npc['name']}】：当时报价 {int(t['price']):,} → 核验价 {int(point['price']):,}，"
                  f"方向「{'看多' if t['direction'] > 0 else '看空'}」{verdict}。")


def news_text(state: dict) -> str:
    """#灵市消息：最近 10 条商会风声（全服共享，容量 80）。"""
    news = state["news"][-10:]
    if not news:
        return "灵市暂无风声。"
    lines = ["--- 灵市消息 ---"]
    for n in news:
        stamp = time.strftime("%m-%d %H:%M", time.gmtime(n["slot"] * TICK_MS / 1000 + 8 * 3600))
        lines.append(f"· [{stamp}] {n['text']}")
    return "\n".join(lines)


def debt_text(state: dict, doc: PlayerDoc) -> str:
    """#灵市债务：借据四态与催债文案（原版 debtStatus）。"""
    ds = debt_status(state, doc)
    if not ds["has"]:
        return "【钱万三】账上干净，无欠款。"
    lines = ["--- 灵市债务 ---",
             f"本金 {ds['principal']:,}｜未付利息 {ds['interest']:,}｜合计 {ds['debt']:,}",
             f"净资产（含持仓市值）{ds['net']:+,}"]
    if ds["insolvent"]:
        lines.append("【钱万三】收起笑容：「资不抵债，先还钱再谈别的。」")
    elif ds["overdue"]:
        lines.append("【钱万三】叩了叩借据：「期限已过，先把账结了。」")
    else:
        lines.append("【钱万三】笑道：「借据尚在期内，按时还便是。」")
    lines.append("逾期或资不抵债时暂停新买入；仍可卖出、还款、继续修炼。")
    lines.append("还款：#还款 全部 / #还款 数量（部分还款先息后本）")
    return "\n".join(lines)
