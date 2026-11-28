"""时间线权柄（W8-F2，对齐原版 apps/User/WorldlineAuthority.js + model/worldlineAuthority.js）。

原版玩法闭环：支取时间线（把**别的世界线**里你曾拥有的东西提前取出）→ 形成因果债 →
因果债过 200 触发时间长河雷劫 → 古史打击改写他人既定事实 → 纪元消债 → 重塑形神。

⚠️ 与原版的三处结构性差异（本移植无对应底座，已折算，勿误判为 bug）：

1. **时间线不是备份快照**。原版扫 `resources/data/backup/<lineId>/` 里其它世界线的
   玩家存档，本移植没有多线备份。改为**锚点投影**：以「你在现世确实拥有过该物品」
   为因果锚点，投影出 6 条古史线（太初…现世前夜），每线份数由
   `sha256(uid|线号|物品名)` 确定，同人同物结果稳定、可去重、不可回滚。
2. **绝灵侵蚀未搬**。原版雷劫累计 ≥3 次后有 50%~85% 概率引出 11000~14000 年的
   个人级绝灵抹物；本移植无「绝灵抹物」底座，只保留雷劫本体。
3. **全时间线尽灭 → 永寂** 未搬（会变成删档），只登记 `古史创伤` 与 `道果瑕疵`。

状态挂在 `doc.ext["worldline"]`，db 恒 v17。
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import authority, zhengdao

# ---------------------------------------------------------------- 门槛

GATE_WITHDRAW = 42      # 支取：随机一条线，限 1 份（原版权柄 20）
GATE_TARGET = 45        # 指定线号，份数不限（原版权柄 21，与法身/时间长河同门槛）
GATE_SCOPE = 47         # 可一次「全部」支取（原版权柄 22）
GATE_FREE = 49          # 祭道之上：因果债恒 0、纪元消债免费（原版权柄 23）

# ---------------------------------------------------------------- 因果债

DEBT_TIERS = (
    (1000, 4, "厄土大祭", "厄土高原大祭可能提前降临"),
    (600, 3, "古史清算", "诸天位面与自身道果一同受损"),
    (300, 2, "众生代偿", "与自身有关之人被卷入因果惩罚"),
    (100, 1, "绝灵回响", "绝灵时代可能提前或延长"),
)
TIER0 = (0, 0, "因果平稳", "尚未形成显著反噬")

# 档位 → (血量上限削减, 支取加价率, 境界压制)
PENALTIES = {
    0: (0.00, 0.00, 0),
    1: (0.00, 0.05, 0),
    2: (0.05, 0.10, 0),
    3: (0.15, 0.25, 1),
    4: (0.30, 0.50, 2),
}

BACKLASH_THRESHOLD = 200
BACKLASH_BOLTS = 20
BACKLASH_RATIO = 1.2            # 每道雷劫 = 血量上限 120% → 20 道必死
BLOCK_HOURS = 12                # 支取封锁基准
EXTRA_BLOCK_HOURS = 5           # 每次雷劫额外叠加

MAX_HISTORY = 30
SESSION_TTL = 600               # 原版 10 分钟
MAX_CLAIMS = 200

# ---------------------------------------------------------------- 古史线

LINES: tuple[tuple[str, str, float], ...] = (
    ("L1", "太初混沌纪", 0.45),
    ("L2", "洪荒龙汉纪", 0.75),
    ("L3", "上古神庭纪", 1.10),
    ("L4", "中古绝灵纪", 1.50),
    ("L5", "近古黑暗纪", 1.95),
    ("L6", "现世前夜", 2.50),
)
LINE_LABEL = {lid: label for lid, label, _dev in LINES}

FACT_WEIGHT = {
    "证道": 180, "创道": 160, "造化": 140,
    "功法": 50, "物品": 70, "至宝": 150, "关系": 90,
}

# 原版 8 类可支取物品（本移植无「纳戒灵石」独立槽位，故不收灵石）
ITEM_CATEGORIES = ("装备", "丹药", "道具", "功法", "草药", "材料", "盒子", "仙宠", "宝石")

# 众生代偿（原版 32 人上限；本移植群服规模小，取 8）
COMPENSATION_RATIO_MAX = 0.35
COMPENSATION_RATIO_MIN = 0.05
COMPENSATION_MAX_TARGETS = 8


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）`ext["worldline"]`；直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("worldline")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("debt", 0)
    st.setdefault("claims", [])
    st.setdefault("blocked_until", 0.0)
    st.setdefault("backlashes", 0)
    st.setdefault("history", [])
    st.setdefault("pending", [])
    st.setdefault("session", None)
    st.setdefault("destroyed", [])
    st.setdefault("form_broken", "")
    st.setdefault("strikes", 0)
    st.setdefault("compensation", {})
    ext["worldline"] = st
    return st


def _log(st: dict, kind: str, now: float, **extra: Any) -> None:
    rows = list(st.get("history") or [])
    rows.append({"type": kind, "at": float(now), **extra})
    st["history"] = rows[-MAX_HISTORY:]


# ---------------------------------------------------------------- 权柄 / 档位

def gate_of(doc: Any) -> dict:
    """支取权限：mode = none / random / target / scope / free。"""
    level = authority.authority_of(doc)
    if level >= GATE_FREE:
        return {"level": level, "mode": "free", "limit": 99, "reveal": True}
    if level >= GATE_SCOPE:
        return {"level": level, "mode": "scope", "limit": 99, "reveal": True}
    if level >= GATE_TARGET:
        return {"level": level, "mode": "target", "limit": 99, "reveal": True}
    if level >= GATE_WITHDRAW:
        return {"level": level, "mode": "random", "limit": 1, "reveal": False}
    return {"level": level, "mode": "none", "limit": 0, "reveal": False}


def gate_text(gate: Mapping[str, Any]) -> str:
    return {
        "none": f"权柄 {gate['level']}，未到支取门槛（需 {GATE_WITHDRAW} 档）",
        "random": f"权柄 {gate['level']}，可支取 1 条线（线号不可见）",
        "target": f"权柄 {gate['level']}，可指定线号，份数不限",
        "scope": f"权柄 {gate['level']}，可一次支取全部线",
        "free": f"权柄 {gate['level']}，祭道之上不沾因果（债恒 0、消债免费）",
    }.get(str(gate.get("mode")), "权柄状态未知")


def tier_of(debt: float) -> dict:
    value = max(0.0, float(debt or 0))
    for need, level, name, effect in DEBT_TIERS:
        if value >= need:
            return {"level": level, "name": name, "effect": effect, "need": need}
    return {"level": TIER0[1], "name": TIER0[2], "effect": TIER0[3], "need": TIER0[0]}


def penalty_of(debt: float) -> dict:
    tier = tier_of(debt)
    hp, tax, suppress = PENALTIES.get(tier["level"], PENALTIES[0])
    return {"hp": hp, "tax": tax, "suppress": suppress, **tier}


def block_left(st: Mapping[str, Any], now: float) -> int:
    return max(0, int(float(st.get("blocked_until") or 0) - now))


# ---------------------------------------------------------------- 古史线（投影）

def _seed(uid: str, line_id: str, name: str) -> float:
    raw = hashlib.sha256(f"{uid}|{line_id}|{name}".encode("utf-8")).hexdigest()[:8]
    return int(raw, 16) / 0xFFFFFFFF


def line_offers(uid: str, name: str, base_qty: int,
                claims: Iterable[str], destroyed: Iterable[str]) -> list[dict]:
    """把「现世锚点」投影成 6 条古史线的可支取份数；已支取/已灭的线剔除。"""
    taken = set(str(c) for c in claims)
    dead = set(str(d) for d in destroyed)
    base = max(1, int(base_qty))
    out: list[dict] = []
    for line_id, label, dev in LINES:
        if line_id in dead:
            continue
        if f"{line_id}|{name}" in taken:
            continue
        roll = _seed(uid, line_id, name)
        qty = max(1, int(round(base * dev * (0.6 + roll * 0.8))))
        out.append({"line": line_id, "label": label, "qty": qty, "dev": dev,
                    "roll": round(roll, 3)})
    return out


def offers_text(offers: Sequence[Mapping[str, Any]], reveal: bool) -> str:
    if not offers:
        return "本次没有可支取的线（全部已支取或已从古史抹去）。"
    lines = []
    for i, o in enumerate(offers, 1):
        if reveal:
            lines.append(f"{i}. {o['label']}｜×{o['qty']}")
        else:
            lines.append(f"{i}. 混沌线影｜×{o['qty']}（权柄不足，看不穿是哪一纪）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 会话

def open_session(st: dict, category: str, name: str,
                 offers: Sequence[Mapping[str, Any]], now: float) -> dict:
    st["session"] = {"at": float(now), "expire": float(now) + SESSION_TTL,
                     "category": str(category), "name": str(name),
                     "offers": [dict(o) for o in offers]}
    return st["session"]


def session_of(st: Mapping[str, Any], now: float) -> dict | None:
    sess = st.get("session")
    if not isinstance(sess, dict):
        return None
    if float(sess.get("expire") or 0) <= now:
        return None
    return sess


def cancel_session(st: dict) -> tuple[bool, str]:
    if not isinstance(st.get("session"), dict):
        return False, "当前没有待确认的支取。"
    st["session"] = None
    return True, "【时间线·已取消】已取消本次支取，时间长河复归平静。"


def parse_picks(arg: str, count: int) -> tuple[bool, list[int], str]:
    """解析「1,3」/「全部」→ 0-based 下标列表。"""
    raw = str(arg or "").strip()
    if not raw:
        return False, [], "请给出线号（如 1,3）或「全部」。"
    if raw in ("全部", "全", "all"):
        return True, list(range(count)), ""
    picks: list[int] = []
    for token in raw.replace("，", ",").replace("、", ",").replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if not token.isdigit():
            return False, [], f"线号「{token}」不是数字。"
        idx = int(token) - 1
        if idx < 0 or idx >= count:
            return False, [], f"线号 {int(token)} 超范围（本次共 {count} 条）。"
        if idx not in picks:
            picks.append(idx)
    if not picks:
        return False, [], "没解析到有效线号。"
    return True, picks, ""


# ---------------------------------------------------------------- 因果债结算

def add_debt(doc: Any, st: dict, amount: float, reason: str, now: float,
             max_hp: int = 0, rng: Any = None) -> dict:
    """加因果债并即时判定雷劫。返回 {delta, debt, tier, penalty, backlash, free}。"""
    free = authority.authority_of(doc) >= GATE_FREE
    delta = 0 if free else max(0, int(math.ceil(float(amount or 0))))
    st["debt"] = int(st.get("debt") or 0) + delta
    debt = int(st["debt"])
    tier = tier_of(debt)
    if delta:
        _log(st, "因果债", now, amount=delta, reason=str(reason), debt=debt)
    backlash = {"triggered": False}
    if delta > 0 and debt > BACKLASH_THRESHOLD:
        backlash = _backlash(doc, st, now, max_hp, rng)
    return {"delta": delta, "debt": debt, "tier": tier,
            "penalty": penalty_of(debt), "backlash": backlash, "free": free}


def _backlash(doc: Any, st: dict, now: float, max_hp: int, rng: Any = None) -> dict:
    hp_max = max(1, int(max_hp or 0))
    per_bolt = int(math.ceil(hp_max * BACKLASH_RATIO))
    total = per_bolt * BACKLASH_BOLTS
    cur = int(getattr(doc, "ext", {}).get("hp", hp_max) or 0) if isinstance(doc.ext, dict) else hp_max
    doc.ext["hp"] = max(0, cur - total)
    killed = int(doc.ext["hp"]) <= 0
    if killed:
        zhengdao.add_wounds(doc, 2, "因果雷罚", now)
        st["blocked_until"] = max(float(now) + BLOCK_HOURS * 3600,
                                  float(st.get("blocked_until") or 0.0)) \
            + EXTRA_BLOCK_HOURS * 3600
    else:
        st["blocked_until"] = max(float(now), float(st.get("blocked_until") or 0.0)) \
            + EXTRA_BLOCK_HOURS * 3600
    st["backlashes"] = int(st.get("backlashes") or 0) + 1
    result = {"triggered": True, "bolts": BACKLASH_BOLTS, "damage_per_bolt": per_bolt,
              "total_damage": total, "killed": killed,
              "count": int(st["backlashes"]),
              "blocked_until": float(st["blocked_until"])}
    _log(st, "时间长河雷劫", now, **{k: v for k, v in result.items() if k != "triggered"})
    return result


def debt_lines(res: Mapping[str, Any]) -> list[str]:
    """把 add_debt 结果转成文案行。"""
    tier = res.get("tier") or tier_of(0)
    if res.get("free"):
        lines = ["祭道之上不沾因果，本次因果债为 0。"]
    else:
        lines = [f"因果债 +{res.get('delta', 0)}，当前 {res.get('debt', 0)}（{tier['name']}）。"]
    back = res.get("backlash") or {}
    if not back.get("triggered"):
        return lines
    lines.append(f"【时间长河·因果雷罚】因果债已过 {BACKLASH_THRESHOLD}，"
                 f"连续降下 {back['bolts']} 道雷劫。")
    lines.append(f"每道雷劫造成血量上限 120% 的伤害：{back['damage_per_bolt']:,} 点。")
    if back.get("killed"):
        lines.append("你被因果雷罚击杀，道伤 +2；12 小时内不得再次支取时间线。")
    return lines


def deduct_rate(doc: Any) -> float:
    """每点纪元积累可消多少因果债；999 = 免费全清（祭道之上）。"""
    level = authority.authority_of(doc)
    if level >= GATE_FREE:
        return 999.0
    if level >= GATE_SCOPE:
        return 5.0
    if level >= GATE_TARGET:
        return 3.0
    if level >= GATE_WITHDRAW:
        return 1.5
    return 0.0


def reduce_debt(doc: Any, st: dict, requested: int, now: float) -> tuple[bool, str]:
    """纪元消债：花纪元积累按倍率抵消因果债。"""
    rate = deduct_rate(doc)
    debt = int(st.get("debt") or 0)
    if rate <= 0:
        return False, (f"权柄不足：需 {GATE_WITHDRAW} 档才可消债"
                       f"（当前 {authority.authority_of(doc)}）。")
    if debt <= 0:
        return False, "因果债已清零，不必再消。"
    if rate >= 999:
        st["debt"] = 0
        _log(st, "纪元消债", now, spent=0, reduced=debt, rate="free")
        return True, (f"祭道之上不沾因果：因果债 {debt} → 0，未耗纪元积累。\n"
                      f"{_tier_line(st)}")
    available = int((doc.ext or {}).get("era_points", 0) or 0)
    if available <= 0:
        return False, "纪元积累为 0，无法消债（法身镇守 / 时间长河可积累）。"
    want = max(1, int(requested or 1)) if requested else math.ceil(debt / rate)
    spend = min(want, available, math.ceil(debt / rate))
    if spend <= 0:
        return False, "所需纪元积累不足 1 点。"
    reduced = min(debt, int(spend * rate))
    doc.ext["era_points"] = available - spend
    st["debt"] = max(0, debt - reduced)
    _log(st, "纪元消债", now, spent=spend, reduced=reduced, rate=rate)
    return True, (f"耗纪元积累 {spend} 点，抵消因果债 {reduced}（倍率 ×{rate:g}）。\n"
                  f"{_tier_line(st)}")


def _tier_line(st: Mapping[str, Any]) -> str:
    debt = int(st.get("debt") or 0)
    tier = tier_of(debt)
    pen = penalty_of(debt)
    return (f"当前因果债 {debt}（{tier['name']}）：{tier['effect']}｜"
            f"血量上限 -{pen['hp']:.0%}、支取加价 +{pen['tax']:.0%}")


# ---------------------------------------------------------------- 支取结算

def settle_withdraw(doc: Any, st: dict, picks: Sequence[int], unit_weight: int,
                    now: float, max_hp: int = 0, rng: Any = None,
                    debt_results: list[dict] | None = None) -> tuple[bool, str, dict[str, int]]:
    """确认支取：入包清单 + 逐线登记 claim + 加因果债。"""
    sess = session_of(st, now)
    if not sess:
        return False, "支取会话已过期（10 分钟），请重新发送「#支取时间线」。", {}
    offers = list(sess.get("offers") or [])
    chosen = [offers[i] for i in picks if 0 <= i < len(offers)]
    if not chosen:
        return False, "没有选中任何古史线。", {}
    name = str(sess.get("name"))
    total = sum(int(o["qty"]) for o in chosen)
    claims = list(st.get("claims") or [])
    for o in chosen:
        tag = f"{o['line']}|{name}"
        if tag not in claims:
            claims.append(tag)
    st["claims"] = claims[-MAX_CLAIMS:]
    st["session"] = None
    weight = max(1, int(unit_weight or 1))
    res = add_debt(doc, st, weight * total, f"支取「{name}」×{total}", now, max_hp, rng)
    if debt_results is not None:
        debt_results.append(res)
    lines = [f"【时间线·支取】时间线支取成功：「{name}」×{total} 已落入纳戒。",
             "挪用自：" + "、".join(f"{o['label']}(×{o['qty']})" for o in chosen),
             f"因果债计价：{weight} × {total} = {weight * total} 点。"]
    lines += debt_lines(res)
    return True, "\n".join(lines), {name: total}


# ---------------------------------------------------------------- 古史打击

def compare_authority(attacker: Any, target: Any) -> dict:
    atk = authority.authority_of(attacker)
    tgt = authority.authority_of(target)
    if atk < GATE_WITHDRAW:
        return {"ok": False, "reason": "authority", "atk": atk, "tgt": tgt}
    if tgt > atk:
        return {"ok": False, "reason": "higher_target", "atk": atk, "tgt": tgt}
    if tgt == atk:
        return {"ok": False, "reason": "same_level", "atk": atk, "tgt": tgt}
    return {"ok": True, "reason": "suppressed", "atk": atk, "tgt": tgt}


def parse_fact(arg: str) -> tuple[str | None, str]:
    """解析「功法*九转玄功」→ (类型, 名称)。"""
    raw = str(arg or "").strip().replace("＊", "*")
    if "*" not in raw:
        return None, ""
    ftype, name = raw.split("*", 1)
    ftype, name = ftype.strip(), name.strip()
    if ftype not in FACT_WEIGHT or not name:
        return None, ""
    return ftype, name


def parse_item_spec(arg: str) -> tuple[str | None, str]:
    """解析「装备*青锋剑」/「装备 青锋剑」→ (类别, 物品名)。"""
    raw = str(arg or "").strip().replace("＊", "*")
    if not raw:
        return None, ""
    if "*" in raw:
        cat, name = raw.split("*", 1)
    else:
        parts = raw.split(None, 1)
        if len(parts) != 2:
            return None, ""
        cat, name = parts
    cat, name = cat.strip(), name.strip()
    if cat not in ITEM_CATEGORIES or not name:
        return None, ""
    return cat, name


def strike(attacker: Any, atk_st: dict, target: Any, tgt_st: dict,
           ftype: str, name: str, now: float,
           max_hp: int = 0, rng: Any = None,
           debt_results: list[dict] | None = None) -> tuple[bool, str, dict | None]:
    """古史打击：改写目标的既定事实。

    返回 (ok, msg, plan)；plan = {"erase_item": name} 时由调用方做全服抹除。
    """
    cmp = compare_authority(attacker, target)
    ftype = ftype if ftype in FACT_WEIGHT else "物品"
    weight = FACT_WEIGHT[ftype]

    if not cmp["ok"]:
        if cmp["reason"] == "same_level":
            debt_amount, reason = 45, "强行触碰同阶古史"
        elif cmp["reason"] == "higher_target":
            debt_amount, reason = 80, "强行触碰受护持的古史"
        else:
            debt_amount, reason = 0, ""
        if cmp["reason"] == "authority":
            return False, (f"权柄不足：古史打击需 {GATE_WITHDRAW} 档"
                           f"（当前 {cmp['atk']}）。"), None
        res = add_debt(attacker, atk_st, debt_amount, reason, now, max_hp, rng)
        if debt_results is not None:
            debt_results.append(res)
        if cmp["reason"] == "same_level":
            lines = [f"古史反噬：目标权柄与你同为 {cmp['tgt']} 档，两股道果相撞，"
                     f"既定事实纹丝不动。"]
        else:
            lines = [f"古史反噬：目标权柄 {cmp['tgt']} 高于你（{cmp['atk']}），"
                     f"你的古史之力被原样弹回。"]
        if cmp["reason"] == "higher_target" and cmp["tgt"] >= GATE_SCOPE:
            atk_st["form_broken"] = "触碰路尽级古史遭本体抹杀"
            if isinstance(getattr(attacker, "ext", {}), dict):
                attacker.ext["hp"] = 0
            _log(atk_st, "形神俱灭", now, reason=atk_st["form_broken"])
            lines.append("【形神俱灭】路尽级古史反震，你的形神当场崩解，须他人「#重塑形神」相救。")
        lines += debt_lines(res)
        return False, "\n".join(lines), None

    atk_st["strikes"] = int(atk_st.get("strikes") or 0) + 1
    tgt_level = cmp["tgt"]
    plan: dict | None = None
    lines: list[str] = []

    if tgt_level >= GATE_SCOPE:
        lines.append(f"目标道果已成路尽，你只能抹去其在「{LINE_LABEL['L6']}」的既定痕迹。")
        if isinstance(target.ext, dict):
            target.ext["ancient_wound"] = int(target.ext.get("ancient_wound") or 0) + 1
        _push_destroyed(tgt_st, "L6", now)
    else:
        lines.append(_apply_fact(target, tgt_st, ftype, name, now))
        _push_destroyed(tgt_st, "L6", now)
        if isinstance(target.ext, dict):
            target.ext["ancient_wound"] = int(target.ext.get("ancient_wound") or 0) + 1
        if ftype in ("物品", "至宝"):
            plan = {"erase_item": name}

    multiplier = 1.5 if tgt_level >= GATE_TARGET else 1.0
    res = add_debt(attacker, atk_st, int(math.ceil(weight * multiplier)),
                   f"改写{ftype}既定事实", now, max_hp, rng)
    if debt_results is not None:
        debt_results.append(res)
    lines.append(f"因果债计价：{ftype} 权重 {weight}"
                 + (f" ×1.5（目标 {tgt_level} 档道果）" if multiplier > 1 else "") + "。")
    lines += debt_lines(res)
    return True, "\n".join(lines), plan



def collapse_past_artifacts(doc: Any, rng: random.Random,
                            item_lookup: Callable[[str], Mapping | None]) -> dict[str, Any]:
    """原版过去身被抹杀时，有 35% 概率摧毁一件未锁定的帝兵/至宝。"""
    ext = getattr(doc, "ext", {}) or {}
    equipment = ext.get("equipment") if isinstance(ext.get("equipment"), dict) else {}
    candidates = []
    for slot in ("至宝", "帝兵"):
        raw = equipment.get(slot)
        name = str(raw.get("name") or "") if isinstance(raw, Mapping) else str(raw or "")
        if not name:
            continue
        item = item_lookup(name) or (raw if isinstance(raw, Mapping) else {})
        if item.get("islockd") or item.get("锁定") or item.get("大道至宝本体"):
            continue
        candidates.append((slot, name))
    if not candidates or rng.random() >= 0.35:
        return {"destroyed": False, "candidates": len(candidates)}
    slot, name = candidates[min(len(candidates) - 1, int(rng.random() * len(candidates)))]
    equipment.pop(slot, None)
    if slot == "至宝":
        treasure = ext.get("xtzb")
        if isinstance(treasure, dict) and treasure.get("current") == name:
            treasure["current"] = ""
    return {"destroyed": True, "slot": slot, "name": name,
            "reason": "过去时间线被厄土仙帝打灭，道果锚点松动"}


def destroy_past(doc: Any, source: str, now: float) -> dict[str, Any]:
    """记录过去时间线毁灭及其对准仙帝/以下现世道果的创伤。"""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = {}
        if hasattr(doc, "ext"):
            doc.ext = ext
    try:
        from . import suiyun
        if bool(suiyun.effects(doc).get("absoluteSpiritImmune")):
            return {"protected": True, "line_id": "", "present_effect": "protected"}
    except (AttributeError, TypeError, ValueError):
        pass
    state = state_of(doc)
    line_id = f"{source}:{int(float(now) * 1000)}"
    destroyed = list(state.get("destroyed_lines") or [])
    if line_id not in destroyed:
        destroyed.append(line_id)
    state["destroyed_lines"] = destroyed[-MAX_HISTORY:]
    tier = authority.authority_21(doc)
    if tier == 20:
        ext["dao_flaw"] = int(ext.get("dao_flaw") or 0) + 1
        ext["ancient_wound"] = int(ext.get("ancient_wound") or 0) + 1
        present_effect = "quasi_emperor_flaw"
    elif tier < 20:
        ext["ancient_wound"] = int(ext.get("ancient_wound") or 0) + 1
        present_effect = "causal_wound"
    else:
        present_effect = "none"
    _log(state, "时间线毁灭", now, line_id=line_id, source=source,
         present_effect=present_effect)
    return {"protected": False, "line_id": line_id, "present_effect": present_effect}

def _push_destroyed(st: dict, line_id: str, now: float) -> None:
    dead = list(st.get("destroyed") or [])
    if line_id not in dead:
        dead.append(line_id)
        _log(st, "时间线毁灭", now, line=line_id)
    st["destroyed"] = dead[-len(LINES):]


def _apply_fact(target: Any, tgt_st: dict, ftype: str, name: str, now: float) -> str:
    ext = target.ext if isinstance(target.ext, dict) else {}
    if ftype == "功法":
        learned = [g for g in (ext.get("gongfa") or []) if str(g) != name]
        removed = len(ext.get("gongfa") or []) - len(learned)
        ext["gongfa"] = learned
        return (f"{target.name} 遗忘了「{name}」。" if removed
                else f"「{name}」的习得事实已被抹去（其本就未曾习得）。")
    if ftype == "创道":
        if str(ext.get("own_dao") or "") == name:
            ext["dao_broken"] = name
            ext.pop("own_dao", None)
        return f"「{name}」的开创事实被改写，{target.name} 的道果根基出现断层。"
    if ftype == "证道":
        before = int(target.realm_index or 0)
        target.realm_index = max(0, before - 1)
        target.exp = 0
        ext["dao_flaw"] = int(ext.get("dao_flaw") or 0) + 1
        return (f"证道事实被击穿：{target.name} 的境界由第 {before + 1} 境跌落至 "
                f"第 {target.realm_index + 1} 境，修为尽散。")
    if ftype == "造化":
        lost = list(ext.get("unique_lost") or [])
        if name not in lost:
            lost.append(name)
        ext["unique_lost"] = lost[-32:]
        return f"「{name}」的获得事实被改写，{target.name} 的唯一性权柄失去锚点。"
    if ftype == "关系":
        ext["bond_broken"] = int(ext.get("bond_broken") or 0) + 1
        return f"{target.name} 的一段因果牵连被剪断（道侣/师徒/宗门关系出现裂痕）。"
    return f"「{name}」的获得事实正从现世松动。"


# ---------------------------------------------------------------- 众生代偿

def related_of(doc: Any) -> list[tuple[str, str]]:
    """因果牵连：道侣 / 师父 / 弟子（宗门由调用方补，需要查表）。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    out: list[tuple[str, str]] = []
    daolv = str(ext.get("daolv") or "")
    if daolv:
        out.append(("道侣", daolv))
    shifu = str(ext.get("shifu") or "")
    if shifu:
        out.append(("师父", shifu))
    for uid in (ext.get("tudi") or [])[:COMPENSATION_MAX_TARGETS]:
        if uid:
            out.append(("弟子", str(uid)))
    return out[:COMPENSATION_MAX_TARGETS]


def compensate(target: Any, amount: float, event_id: str, source_name: str,
               now: float, max_hp: int = 0) -> dict:
    """把因果代偿落到一个牵连者身上（按事件 ID 去重，重试不会二次受罚）。"""
    st = state_of(target)
    rec = st.get("compensation") if isinstance(st.get("compensation"), dict) else {}
    events = [str(e) for e in (rec.get("events") or [])]
    if event_id and event_id in events:
        return {"dedup": True, "damage": 0, "wound": 0, "name": getattr(target, "name", "")}
    ratio = min(COMPENSATION_RATIO_MAX,
                max(COMPENSATION_RATIO_MIN, float(amount) / 1000.0))
    hp_max = max(1, int(max_hp or 0))
    damage = max(1, int(math.ceil(hp_max * ratio)))
    cur = int(target.ext.get("hp", hp_max) or 0) if isinstance(target.ext, dict) else hp_max
    target.ext["hp"] = max(0, cur - damage)
    wound = max(1, int(math.ceil(float(amount) / 300.0)))
    zhengdao.add_wounds(target, wound, "因果代偿", now)
    if event_id:
        events.append(event_id)
    rec.update({
        "source": str(source_name), "amount": float(amount),
        "count": int(rec.get("count") or 0) + 1,
        "total_damage": int(rec.get("total_damage") or 0) + damage,
        "total_wound": float(rec.get("total_wound") or 0) + wound,
        "last_damage": damage, "last_wound": wound, "at": float(now),
        "events": events[-64:],
    })
    st["compensation"] = rec
    return {"dedup": False, "damage": damage, "wound": wound,
            "name": getattr(target, "name", ""), "hp": int(target.ext["hp"])}


def push_pending(st: dict, uid: str, relation: str, amount: float,
                 event_id: str, now: float) -> None:
    """牵连者不在场 → 挂起，等「#重试因果代偿」。"""
    rows = [r for r in (st.get("pending") or []) if isinstance(r, dict)]
    rows.append({"uid": str(uid), "relation": str(relation),
                 "amount": float(amount), "event": str(event_id), "at": float(now)})
    st["pending"] = rows[-COMPENSATION_MAX_TARGETS * 4:]


def take_pending(st: dict) -> list[dict]:
    rows = [r for r in (st.get("pending") or []) if isinstance(r, dict)]
    st["pending"] = []
    return rows


def compensation_text(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "没有挂起的因果代偿。"
    lines = ["--- 因果代偿 · 结算 ---"]
    for r in rows:
        if r.get("dedup"):
            lines.append(f"· {r.get('name', r.get('uid'))}：本事件已代偿过，跳过")
        else:
            lines.append(f"· {r.get('name', r.get('uid'))}"
                         f"（{r.get('relation', '因果关联')}）："
                         f"血气 -{r.get('damage', 0):,}、道伤 +{r.get('wound', 0)}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 形神

def form_broken_of(doc: Any) -> str:
    return str(state_of(doc).get("form_broken") or "")


def rebuild_form(target: Any, healer_name: str, now: float,
                 max_hp: int = 0) -> tuple[bool, str]:
    st = state_of(target)
    reason = str(st.get("form_broken") or "")
    if not reason:
        return False, f"{getattr(target, 'name', target.uid)} 形神完好，无需重塑。"
    st["form_broken"] = ""
    hp = max(1, int(int(max_hp or 0) * 0.2))
    if isinstance(target.ext, dict):
        target.ext["hp"] = hp
        target.ext["soul_hurt"] = max(0, int(target.ext.get("soul_hurt") or 0) - 1)
    if getattr(target, "state", "") == "形神俱灭":
        target.state = "空闲"
        target.state_start = 0.0
    _log(st, "重塑形神", now, by=str(healer_name))
    return True, (f"{healer_name} 以大道之力重塑 "
                  f"{getattr(target, 'name', target.uid)} 的形神"
                  f"（原由：{reason}），血气恢复至 {hp}。")


# ---------------------------------------------------------------- 文案

def status_text(doc: Any, st: Mapping[str, Any], now: float) -> str:
    gate = gate_of(doc)
    debt = int(st.get("debt") or 0)
    pen = penalty_of(debt)
    lines = [
        "--- 时间线权能 ---",
        gate_text(gate),
        f"因果债：{debt}（{pen['name']}）｜{pen['effect']}",
        "反噬：" + ("｜".join(filter(None, [
            f"血量上限 -{pen['hp']:.0%}" if pen["hp"] else "",
            f"支取加价 +{pen['tax']:.0%}" if pen["tax"] else "",
            f"境界压制 {pen['suppress']} 档" if pen["suppress"] else "",
        ])) or "无"),
        f"消债倍率：×{deduct_rate(doc):g} 纪元积累（当前 {int((doc.ext or {}).get('era_points', 0) or 0)} 点）",
    ]
    left = block_left(st, now)
    if left:
        lines.append(f"⛔ 支取封锁中：剩余 {left // 3600} 小时 {left % 3600 // 60} 分")
    dead = list(st.get("destroyed") or [])
    lines.append("古史线：" + "、".join(
        f"{label}{'(已灭)' if lid in dead else ''}" for lid, label, _d in LINES))
    sess = session_of(st, now)
    if sess:
        lines.append(f"⏳ 待确认支取：{sess['category']}*{sess['name']}"
                     f"（剩 {int(float(sess['expire']) - now)} 秒）")
    form = form_broken_of(doc)
    if form:
        lines.append(f"⚠️ 形神俱灭：{form}（请他人「#重塑形神」相救）")
    hist = list(st.get("history") or [])[-6:]
    if hist:
        lines.append("— 最近古史 —")
        for r in reversed(hist):
            ts = time.strftime("%m-%d %H:%M", time.gmtime(float(r.get("at") or 0) + 8 * 3600))
            detail = "，".join(f"{k}={v}" for k, v in r.items() if k not in ("type", "at"))
            lines.append(f"{ts}｜{r.get('type')}｜{detail}")
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 时间线权柄 · 规则 ---",
        f"· 权柄门槛：{GATE_WITHDRAW} 档起可支取（随机 1 条线）；"
        f"{GATE_TARGET} 档可指定线号；{GATE_SCOPE} 档可一次全取；{GATE_FREE} 档不沾因果。",
        "· 支取对象必须是你「现世已拥有」的物品（因果锚点），每条古史线的份数由"
        "「线偏差 × 确定性哈希」算出，同一人同一物结果恒定。",
        f"· 因果债每 {BACKLASH_THRESHOLD} 点以上触发时间长河雷劫：{BACKLASH_BOLTS} 道 ×"
        f"血量上限 {BACKLASH_RATIO:.0%} = 必死，道伤 +2，支取封锁 {BLOCK_HOURS} 小时"
        f"（每次雷劫再叠 {EXTRA_BLOCK_HOURS} 小时）。",
        "· 因果债四档：100 绝灵回响 / 300 众生代偿 / 600 古史清算 / 1000 厄土大祭；"
        "档位越高血量上限削减、支取加价、境界压制越重。",
        "· 古史打击：只改写权柄低于自己的目标；同阶反噬 +45 债，越级 +80 债，"
        f"撞 {GATE_SCOPE} 档以上会被打成形神俱灭。",
        "· 纪元消债：倍率 1.5 / 3 / 5 / 免费，按权柄档位提升，消耗纪元积累。",
        "· 众生代偿：债 ≥300 时，道侣/师父/弟子分摊惩罚；不在场者挂起，"
        "由「#重试因果代偿」补结算（同一事件不二次受罚）。",
        "⚠️ 移植差异：时间线由**锚点投影**生成（原版读多线备份快照）；"
        "绝灵侵蚀抹物、全时间线尽灭→永寂、岁云无上庇护均未搬。",
    ])


def help_text() -> str:
    return "\n".join([
        "--- 时间线权柄 · 指令 ---",
        "「#时间线权能」状态面板（别名「#古史状态」「#因果债」）",
        "「#支取时间线 类别*物品名」列可支取古史线（10 分钟内有效）",
        "「#确认支取时间线 1,3」或「#确认支取时间线 全部」结算",
        "「#取消支取时间线」放弃本次",
        "「#消减因果债 N」花纪元积累降债（别名「#纪元消债」）",
        "「#古史打击 类型*名称 @道友」改写他人既定事实",
        "类型：证道 / 创道 / 造化 / 功法 / 物品 / 至宝 / 关系",
        "「#重塑形神 @道友」救回形神俱灭者（自身债 +60，需 42 档）",
        "「#重试因果代偿」补结算挂起的众生代偿",
    ])
