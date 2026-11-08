"""上苍之上（W8-F5，对齐原版 apps/SecretPlace/SecretPlace.js 的上苍分支
+ model/shangcangDungeon.js 119 行 + apps/SecretPlace/ShangcangTask.js 472 行）。

玩法：两处上苍禁地（魂河 / 天帝葬坑）→ 交六项资源 → 60 分钟历练 → 判胜负 →
四档掉落池（guaranteed / chance）→ 胜场 +1、纪元进度 +1（每满 3 胜领 5 纪元积累）。

⚠️ 三处折算（勿当 bug）：

1. **成本按本移植量级折算**。原版六项：灵石 100 亿 / 源石 20 亿 / 修为 3 亿 / 血气 3 亿 /
   元神 1.2 亿 / 寿元 2000 万。本移植：灵石照原值（Price），**源石 ÷1000 → 200 万**
   （与星阁天字号赌石同量级），修为/血气照原值，**寿元 ÷1000 → 2 万**
   （本移植寿元上限约 3.2 万），**元神不实现**（无独立元神池）。
2. **战斗按权柄差折算胜率**。原版 `zd_battle` 打按地点生成的生灵；本移植
   `0.55 + (权柄 − 50) × 0.02`，钳 25%~90%，与法身圣墟同一口径，不跑逐回合。
3. **结算改惰性 tick + 回执**。原版由 `ShangcangTask` cron 每 15 秒扫 redis；
   本移植挂在「#上苍之上」入口，并把每次结算写进 `ext["shangcang"]["receipts"]`（保留 20 条）
   防重放，等价于原版的 `_shangcangSettlements` 幂等键。

状态挂 `doc.ext["shangcang"]`，db 恒 v17。
"""

from __future__ import annotations

from typing import Any, Mapping

from . import authority, fashan

TABLE = "item/副本/上苍之上列表"
GATE_AUTHORITY = 50                  # 与 plane.GATES["上苍之上"] 同门槛（仙帝）
BASE_MINUTES = 60
MAX_COUNT = 12
RECEIPT_CAP = 20
ERA_PER_WINS = 3
ERA_REWARD = 5

TIERS = ("one", "two", "three", "four")
# 成本折算：源石 / 寿元 ÷1000；元神本移植无池，忽略
COST_DIVISOR = {"源石": 1000, "寿元": 1000}
COST_SKIP = ("元神",)
COST_FIELDS = (
    ("灵石", "Price"),
    ("源石", "源石"),
    ("修为", "experience"),
    ("血气", "血气"),
    ("元神", "元神"),
    ("寿元", "shouyuan"),
)
# 提速：行字秘 / 天璇步法 / 道法仙术
REDUCTION_SKILLS = {"行字秘": 2, "天璇步法": 1}
DAOFA_REDUCTION = 2


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）`ext["shangcang"]`；直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("shangcang")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("action", None)
    st.setdefault("wins", 0)
    st.setdefault("progress", 0)
    st.setdefault("receipts", [])
    ext["shangcang"] = st
    return st


def place_rows(content: Any) -> list[dict]:
    rows = content if isinstance(content, list) else []
    return [dict(r) for r in rows if isinstance(r, Mapping) and r.get("name")]


def find_place(content: Any, name: str) -> dict | None:
    target = str(name or "").strip()
    for row in place_rows(content):
        if str(row.get("name")) == target:
            return row
    return None


# ---------------------------------------------------------------- 成本

def cost_of(row: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for label, key in COST_FIELDS:
        if label in COST_SKIP:
            continue
        try:
            value = int(float(row.get(key) or 0))
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            continue
        div = int(COST_DIVISOR.get(label, 1))
        out[label] = max(1, value // div)
    return out


def have_of(doc: Any) -> dict[str, int]:
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    return {
        "灵石": int(doc.stones),
        "源石": int(ext.get("yuanshi", 0) or 0),
        "修为": int(doc.exp),
        "血气": int(ext.get("xueqi", 0) or 0),
        "寿元": int(ext.get("shouyuan", 0) or 0),
    }


def shortages(doc: Any, cost: Mapping[str, int]) -> list[str]:
    have = have_of(doc)
    return [f"{k}需{v:,}，现有{have.get(k, 0):,}" for k, v in cost.items() if have.get(k, 0) < v]


def pay(doc: Any, cost: Mapping[str, int]) -> None:
    for label, value in cost.items():
        if label == "灵石":
            doc.stones -= value
        elif label == "修为":
            doc.exp -= value
        elif label == "源石":
            doc.ext["yuanshi"] = int(doc.ext.get("yuanshi", 0) or 0) - value
        elif label == "血气":
            doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - value
        elif label == "寿元":
            doc.ext["shouyuan"] = int(doc.ext.get("shouyuan", 0) or 0) - value


def cost_text(cost: Mapping[str, int]) -> str:
    def fmt(n: int) -> str:
        if n >= 100_000_000:
            return f"{n / 100_000_000:g} 亿"
        if n >= 10_000:
            return f"{n / 10_000:g} 万"
        return str(n)
    return "｜".join(f"{k} {fmt(v)}" for k, v in cost.items())


# ---------------------------------------------------------------- 时长

def duration_minutes(doc: Any, daofa_active: bool = False) -> tuple[int, list[str]]:
    learned = set(doc.ext.get("gongfa") or []) if isinstance(doc.ext, dict) else set()
    cut, notes = 0, []
    for name, minutes in REDUCTION_SKILLS.items():
        if name in learned:
            cut += minutes
            notes.append(f"{name} −{minutes} 分")
    if daofa_active:
        cut += DAOFA_REDUCTION
        notes.append(f"道法仙术 −{DAOFA_REDUCTION} 分")
    return max(1, BASE_MINUTES - cut), notes


# ---------------------------------------------------------------- 起 / 结算

def begin(doc: Any, st: dict, row: Mapping[str, Any], count: int, now: float,
          daofa_active: bool = False) -> tuple[bool, str]:
    name = str(row.get("name"))
    if authority.authority_of(doc) < GATE_AUTHORITY:
        return False, (f"【{name}】需仙帝权柄（{GATE_AUTHORITY} 档），"
                       f"当前 {authority.authority_of(doc)} 档。")
    if isinstance(st.get("action"), dict):
        return False, "你已在上苍之上历练中，先发送「#上苍之上」结算。"
    n = max(1, min(MAX_COUNT, int(count or 1)))
    unit = cost_of(row)
    total = {k: v * n for k, v in unit.items()}
    lack = shortages(doc, total)
    if lack:
        return False, "资源不足：" + "；".join(lack)
    pay(doc, total)
    minutes, notes = duration_minutes(doc, daofa_active)
    st["action"] = {"place": name, "count": n, "start": float(now),
                    "end": float(now) + minutes * n * 60, "minutes": minutes * n}
    tail = f"（{'｜'.join(notes)}）" if notes else ""
    return True, (f"你踏上【{name}】，往赴{row.get('Grade') or '上苍禁地'} ×{n}。\n"
                  f"消耗：{cost_text(total)}\n"
                  f"预计 {minutes * n} 分钟{tail}，到期后再发「#上苍之上」结算。")


def win_rate(doc: Any) -> float:
    edge = authority.authority_of(doc) - GATE_AUTHORITY
    return max(0.25, min(0.90, 0.55 + edge * 0.02))


def roll_rewards(row: Mapping[str, Any], rng: Any, mult: int = 1) -> dict[str, int]:
    """四档池：guaranteed 必得 1~3 份，其余按 chance 判定。"""
    out: dict[str, int] = {}
    for tier in TIERS:
        for drop in (row.get(tier) or []):
            if not isinstance(drop, Mapping) or not drop.get("name"):
                continue
            name = str(drop["name"])
            if drop.get("guaranteed"):
                got = max(1, (1 + int(rng.random() * 3))) * max(1, int(mult))
            else:
                chance = max(0.0, min(1.0, float(drop.get("chance") or 0)))
                if rng.random() >= chance:
                    continue
                got = max(1, int(mult))
            out[name] = out.get(name, 0) + got
    return out


def settle(doc: Any, st: dict, now: float, rng: Any, content: Any = None) -> tuple[bool, str, dict[str, int]]:
    """结算到期历练：逐次判胜负 → 掉落 → 胜场 / 纪元进度 → 写回执。"""
    act = st.get("action")
    if not isinstance(act, dict):
        return False, "", {}
    if float(act.get("end") or 0) > now:
        left = int(float(act["end"]) - now)
        return False, f"仍在【{act.get('place')}】中，还需 {left // 60} 分 {left % 60} 秒。", {}
    place = str(act.get("place"))
    row = find_place(content, place) or {"name": place}
    return settle_now(doc, st, place, int(act.get("count") or 1), now, rng, row)


def settle_now(doc: Any, st: dict, place: str, count: int, now: float, rng: Any,
               content_row: Mapping[str, Any] | None = None) -> tuple[bool, str, dict[str, int]]:
    st["action"] = None
    row = content_row if isinstance(content_row, Mapping) else {"name": place}
    items: dict[str, int] = {}
    lines = [f"--- 上苍之上 · {place} ---"]
    wins = 0
    for i in range(max(1, int(count))):
        if rng.random() > win_rate(doc):
            doc.ext["hp"] = 1
            lines.append(f"第 {i + 1} 次：败。你在{place}被上苍生灵击退，血量降至 1。")
            break
        wins += 1
        got = roll_rewards(row, rng)
        for name, qty in got.items():
            items[name] = items.get(name, 0) + qty
        st["wins"] = int(st.get("wins") or 0) + 1
        st["progress"] = int(st.get("progress") or 0) + 1
        era_note = ""
        if st["progress"] >= ERA_PER_WINS:
            st["progress"] -= ERA_PER_WINS
            gained = fashan.add_era(doc, ERA_REWARD)
            era_note = f"｜纪元积累 +{gained}"
        lines.append(f"第 {i + 1} 次：胜。战利："
                     + ("、".join(f"{n}×{q}" for n, q in got.items()) or "无")
                     + era_note)
    if wins:
        receipt = f"{place}:{int(now)}:{wins}"
        receipts = [str(r) for r in (st.get("receipts") or [])]
        if receipt not in receipts:
            receipts.append(receipt)
        st["receipts"] = receipts[-RECEIPT_CAP:]
        lines.append(f"本次 {wins}/{count} 胜｜累计胜场 {st['wins']}｜"
                     f"纪元进度 {st['progress']}/{ERA_PER_WINS}")
    return True, "\n".join(lines), items


# ---------------------------------------------------------------- 文案

def panel_text(doc: Any, st: Mapping[str, Any], now: float, content: Any,
               daofa_active: bool = False) -> str:
    rows = place_rows(content)
    gate = authority.authority_of(doc)
    minutes, notes = duration_minutes(doc, daofa_active)
    lines = [
        "--- 上苍之上 ---",
        f"权柄 {gate} 档（需 {GATE_AUTHORITY}）｜胜率 {win_rate(doc):.0%}"
        f"｜历练 {minutes} 分钟" + (f"（{'｜'.join(notes)}）" if notes else ""),
        f"胜场 {int(st.get('wins') or 0)}｜纪元进度 {int(st.get('progress') or 0)}/{ERA_PER_WINS}"
        f"（每满 {ERA_PER_WINS} 胜 +{ERA_REWARD} 纪元积累）",
    ]
    act = st.get("action")
    if isinstance(act, dict):
        left = max(0, int(float(act.get("end") or 0) - now))
        lines.append(f"⏳ 历练中：{act.get('place')} ×{act.get('count')}，"
                     f"还需 {left // 60} 分 {left % 60} 秒")
    else:
        lines.append("— 两处禁地 —")
        for row in rows:
            lines.append(f"· {row.get('name')}（{row.get('Grade')}）"
                         f"｜{cost_text(cost_of(row))}")
        lines.append("「#上苍之上 魂河」起一次｜「#沉迷上苍之上 魂河*3」连探（上限 12）")
    receipts = list(st.get("receipts") or [])[-3:]
    if receipts:
        lines.append("最近回执：" + "、".join(receipts))
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 上苍之上 · 规则 ---",
        f"· 门槛：仙帝权柄（{GATE_AUTHORITY} 档）；两处禁地 魂河 / 天帝葬坑。",
        "· 成本（原值 → 本移植）：灵石 100 亿照原值；源石 20 亿 ÷1000 = 200 万；"
        "修为 3 亿 / 血气 3 亿照原值；**元神 1.2 亿不实现**（无独立元神池）；寿元 2000 万 ÷1000 = 2 万。",
        f"· 时长 {BASE_MINUTES} 分钟 − 行字秘 2 / 天璇步法 1 / 道法仙术 2，下限 1 分钟；连探按次数叠加。",
        f"· 胜率 `0.55 + (权柄 − {GATE_AUTHORITY}) × 0.02`，钳 25%~90%；失败血量降至 1、不掉落。",
        "· 掉落走上苍四档池（one/two/three/four）：guaranteed 必得 1~3 份，其余按 chance。",
        f"· 每胜 纪元进度 +1，满 {ERA_PER_WINS} 换 {ERA_REWARD} 点纪元积累（封顶）。",
        "· 结算惰性：任何「#上苍之上」入口都会补结算到期历练，并写回执（保留 20 条）防重放。",
        "⚠️ 原版由 ShangcangTask cron 每 15 秒扫 redis 结算，本移植改惰性 tick。",
    ])


def help_text() -> str:
    return "\n".join([
        "--- 上苍之上 · 指令 ---",
        "「#上苍之上」面板 / 结算到期历练",
        "「#上苍之上 魂河」或「#上苍之上 天帝葬坑」起一次历练",
        "「#沉迷上苍之上 魂河*3」连探（1~12 次）",
    ])
