"""众生仙钓 + 鱼王（W8-A2）。

原版：`apps/User/ImmortalFishing.js` 469 + `model/immortalFishing.js` 611 +
`apps/User/ImmortalFishKing.js` 614 + `model/immortalFishKing.js` 436。

本移植保留：
- **垂纶签到**：每日一次，给众生仙钓（钓竿/次数道具）+ 连续天数加赠仙饵
- **垂钓**：`#垂钓 [仙饵]`，40 分钟 CD（引潮灯减半、道法仙术再减 10 分），气血 <200 不可下竿
  - 无饵：按位面鱼表掷鱼（潮汐旺潮时稀有鱼权重 50/30/20、鱼王率 1%→2%），记入鱼谱
  - 有饵：按仙饵奖池掷材料/丹药（1~5 份，引潮灯翻倍）
  - 8% 触发位面奇遇（三选一，10 分钟内有效）
- **万界潮汐**：每 5000 世界年一轮，前 2000 年为旺潮；旺潮位面由纪元数确定性抽取
- **鱼谱**：7 位面 ×（3 鱼 + 1 鱼王），收集 3/4 可领愿鳞，集齐额外奖励
- **愿鳞兑换**：13 种（含唯一物品引潮灯/大衍悟道丹配方）
- **鱼王**：全服共享血条（存 `calamity_state["fish_king"]`，不新建表），按位面各一尊；
  加入 → 讨伐（单次至多削 10% 气血，逼多人接力）→ 榜 → 宝箱（愿鳞 + 遗珍）

shortcut：原版鱼王按玩家血量缩放、宝箱五组不放回抽奖、仙武界坐标/彼岸轮回果唯一掉落、
位面专属奇遇文案（7 套）未移植，统一走通用奇遇；签到按钮 UI 不移植。
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROD_ITEM = "众生仙钓"
SCALE_ITEM = "众生愿鳞"
LAMP_ITEM = "万界引潮灯"
COOLDOWN_SECONDS = 40 * 60
EVENT_CHANCE = 0.08
FISH_KING_CHANCE = 0.01
EVENT_TTL = 600
HP_MIN = 200
SIGN_BAIT_EVERY = 3          # 连续 3 天加赠一份仙饵
KING_STRIKE_CAP = 0.10       # 单次至多削 10% 气血

_DATA: dict[str, Any] | None = None


def data() -> dict[str, Any]:
    global _DATA
    if _DATA is None:
        p = Path(__file__).resolve().parent.parent / "data" / "fishing" / "immortal.json"
        _DATA = json.loads(p.read_text(encoding="utf-8"))
    return _DATA


def planes() -> list[str]:
    return list(data()["planes"])


def baits() -> list[str]:
    return list(data()["baits"])


def bait_config(name: str) -> dict | None:
    return data()["baits"].get(name)


def king_of(plane: str) -> dict | None:
    cfg = data()["planes"].get(plane)
    return cfg.get("king") if cfg else None


# ---------------------------------------------------------------- 潮汐

def _seeded(seed: int):
    value = ((int(seed) + 1) * 2654435761) & 0xFFFFFFFF

    def nxt() -> float:
        nonlocal value
        value = (value * 1664525 + 1013904223) & 0xFFFFFFFF
        return value / 4294967296

    return nxt


TIDE_NAMES = ("界海潮生", "万界归流", "星墟涨落", "众生潮信", "轮回叠浪")


def tide(world_year: int) -> dict[str, Any]:
    year = max(0, int(world_year or 0))
    interval, duration = 5000, 2000
    cycle = year // interval
    elapsed = year - cycle * interval
    active = elapsed < duration
    rnd = _seeded(cycle)
    pool = planes()
    first = pool.pop(int(rnd() * len(pool)))
    second = pool.pop(int(rnd() * len(pool)))
    return {
        "active": active, "cycle": cycle,
        "name": TIDE_NAMES[int(rnd() * len(TIDE_NAMES))],
        "planes": [first, second],
        "remaining": (duration - elapsed) if active else (interval - elapsed),
    }


def tide_text(world_year: int) -> str:
    t = tide(world_year)
    if not t["active"]:
        return (f"【万界潮汐·沉寂期】\n当前世界年份：{int(world_year)}\n"
                f"下一轮潮汐将在 {t['remaining']} 年后刷新，持续 2000 年。")
    return (f"【万界潮汐·{t['name']}】\n当前世界年份：{int(world_year)}\n"
            f"旺潮位面：{'、'.join(t['planes'])}\n剩余时间：{t['remaining']} 年\n"
            "旺潮位面的珍稀鱼概率提高，鱼王出现率由 1% 提升至 2%。")


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get("fishing") if isinstance(getattr(doc, "ext", None), Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("atlas", {})
    st.setdefault("sign_day", "")
    st.setdefault("streak", 0)
    st.setdefault("cd", 0.0)
    st.setdefault("pending", None)
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["fishing"] = dict(st)


def _day_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now + 8 * 3600))


# ---------------------------------------------------------------- 签到

def sign(doc: Any, now: float, rng: random.Random) -> tuple[bool, str, dict[str, int], int]:
    """垂纶签到 → (是否成功, 文案, 物品, 连续天数)。"""
    st = state_of(doc)
    today = _day_key(now)
    if str(st.get("sign_day")) == today:
        return False, f"今日已垂纶于诸天界河，已连续 {st.get('streak', 0)} 日。", {}, int(st.get("streak", 0))
    yesterday = _day_key(now - 86400)
    streak = int(st.get("streak", 0)) + 1 if str(st.get("sign_day")) == yesterday else 1
    items: dict[str, int] = {ROD_ITEM: 1}
    if streak % SIGN_BAIT_EVERY == 0:
        items[rng.choice(baits())] = 1
    st["sign_day"], st["streak"] = today, streak
    set_state(doc, st)
    lines = [f"【垂纶·第 {streak} 日】", "一纶垂入诸天界河，潮声裹挟着机缘而来——"]
    lines += [f"{k} ×{v}" for k, v in items.items()]
    if streak % SIGN_BAIT_EVERY == 0:
        lines.append("连续垂纶，界潮加赠仙饵一份。")
    return True, "\n".join(lines), items, streak


# ---------------------------------------------------------------- 垂钓

def _roll_weighted(rewards: list[Mapping], rng: random.Random) -> Mapping:
    total = sum(float(r.get("weight", 1)) for r in rewards) or 1.0
    cursor = rng.random() * total
    for row in rewards:
        cursor -= float(row.get("weight", 1))
        if cursor < 0:
            return row
    return rewards[-1]


def cooldown_left(doc: Any, now: float, lamp: bool = False, daofa: bool = False) -> int:
    minutes = 40.0
    if lamp:
        minutes /= 2
    if daofa:
        minutes -= 10
    span = max(60, minutes * 60)
    return max(0, int(float(state_of(doc).get("cd") or 0) + span - now))


def roll_catch(plane: str, world_year: int, has_bait: str | None,
               rng: random.Random) -> dict[str, Any]:
    """一次垂钓的结算（不含 CD / 道具校验）。"""
    t = tide(world_year)
    boosted = bool(t["active"] and plane in t["planes"])
    if has_bait:
        cfg = bait_config(has_bait)
        row = dict(_roll_weighted(list(cfg.get("rewards") or []), rng))
        amount = 1 + int(rng.random() * 5)
        return {"kind": "bait", "item": row.get("name"), "cls": row.get("class") or "道具",
                "amount": amount, "plane": plane}
    cfg = data()["planes"].get(plane) or {}
    fish = list(cfg.get("fish") or [])
    king = cfg.get("king") or {}
    king_chance = FISH_KING_CHANCE * (2 if boosted else 1)
    if king and rng.random() < king_chance:
        return {"kind": "king", "item": king.get("name"), "cls": "鱼王",
                "amount": 1, "plane": plane, "boosted": boosted}
    weights = [50, 30, 20] if boosted else [int(f.get("weight", 1)) for f in fish]
    roll = rng.random() * sum(weights)
    picked = fish[-1] if fish else {"name": "无名游鱼"}
    for i, row in enumerate(fish):
        roll -= weights[i] if i < len(weights) else 1
        if roll < 0:
            picked = row
            break
    return {"kind": "fish", "item": picked.get("name"), "cls": "食材",
            "amount": 1 + int(rng.random() * 3), "plane": plane, "boosted": boosted}


def record(st: dict, plane: str, name: str) -> None:
    row = st.setdefault("atlas", {}).setdefault(plane, {})
    row[name] = int(row.get(name, 0) or 0) + 1


def do_cast(doc: Any, now: float, world_year: int, plane: str, bait: str | None,
            rng: random.Random) -> tuple[bool, str, dict[str, int], dict[str, Any]]:
    """垂钓主流程（调用方先校验钓竿/仙饵/气血）。返回 (成功, 文案, 物品, 附加)。"""
    st = state_of(doc)
    st["cd"] = float(now)
    res = roll_catch(plane, world_year, bait, rng)
    items = {str(res["item"]): int(res["amount"])}
    record(st, plane, str(res["item"]))
    lines = []
    if res["kind"] == "king":
        lines.append(f"钓竿骤然弯成满月——【{res['item']}】自界潮中翻涌而出！")
        lines.append("鱼王现世，可发 #鱼王列表 查看讨伐入口。")
        items[SCALE_ITEM] = 5
    elif res["kind"] == "bait":
        lines.append(f"仙饵散作星屑，{res['item']} ×{res['amount']} 随潮而来。")
    else:
        tag = "（旺潮·珍稀鱼）" if res.get("boosted") else ""
        lines.append(f"浮标沉浮，{res['item']} ×{res['amount']}{tag} 上钩。")
        items.setdefault("鱼肉", int(res["amount"]))
    event = None
    if rng.random() < EVENT_CHANCE:
        event = {"id": "realm-drift", "exp": now + EVENT_TTL}
        st["pending"] = event
    set_state(doc, st)
    if event:
        lines.append("界潮掠过钓线，一件漂流物沉浮（#垂钓奇遇 查看）。")
    return True, "\n".join(lines), items, res


# ---------------------------------------------------------------- 奇遇

EVENT = {
    "id": "realm-drift",
    "title": "诸天奇遇·界潮漂流物",
    "intro": "未知位面的潮声掠过钓线，一件漂流物在浪间沉浮。",
    "choices": [
        ("立即打捞", {SCALE_ITEM: 1}, 0, "你从浪间拾得众生愿鳞 ×1。"),
        ("追踪来处", {"群星之沙": 3}, 0, "你沿界潮追索，获得群星之沙 ×3。"),
        ("任其远去", {}, 1_000_000, "漂流物远去后，一小片源矿搁浅岸边，获得源石 100 万。"),
    ],
}


def pending_event(doc: Any, now: float) -> dict | None:
    st = state_of(doc)
    row = st.get("pending")
    if not isinstance(row, Mapping):
        return None
    try:
        if float(row.get("exp") or 0) <= now:
            st["pending"] = None
            set_state(doc, st)
            return None
    except (TypeError, ValueError):
        st["pending"] = None
        set_state(doc, st)
        return None
    return dict(row)


def choose_event(doc: Any, choice: int, now: float) -> tuple[bool, str, dict[str, int], int]:
    """→ (成功, 文案, 物品, 源石)。"""
    if not pending_event(doc, now):
        return False, "当前没有等待选择的垂钓奇遇。", {}, 0
    idx = int(choice) - 1
    if idx < 0 or idx >= len(EVENT["choices"]):
        return False, "这条奇遇没有对应选择（1~3）。", {}, 0
    label, items, stones, msg = EVENT["choices"][idx]
    st = state_of(doc)
    st["pending"] = None
    set_state(doc, st)
    return True, f"【{EVENT['title']}·{label}】\n{msg}", dict(items), int(stones)


def event_text(doc: Any, now: float) -> str:
    if not pending_event(doc, now):
        return "当前没有等待选择的垂钓奇遇。"
    lines = [f"【{EVENT['title']}】", EVENT["intro"]]
    lines += [f"{i}. {c[0]}" for i, c in enumerate(EVENT["choices"], 1)]
    lines.append("发送 #垂钓奇遇 1/2/3 作出选择（10 分钟内有效）。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 鱼谱

def atlas_of(doc: Any, plane: str) -> dict[str, Any] | None:
    cfg = data()["planes"].get(plane)
    if not cfg:
        return None
    rec = (state_of(doc).get("atlas") or {}).get(plane) or {}
    entries = []
    for f in list(cfg.get("fish") or []) + [cfg.get("king") or {}]:
        name = str(f.get("name") or "")
        if not name:
            continue
        entries.append({"name": name, "count": int(rec.get(name, 0) or 0),
                        "king": name == (cfg.get("king") or {}).get("name")})
    return {"plane": plane, "entries": entries,
            "collected": sum(1 for e in entries if e["count"] > 0), "total": len(entries)}


def atlas_text(doc: Any, plane: str) -> str:
    a = atlas_of(doc, plane)
    if not a:
        return f"【{plane}】尚未收录众生鱼谱。"
    lines = [f"【众生鱼图鉴·{plane}】{a['collected']}/{a['total']}"]
    lines += [f"{'鱼王' if e['king'] else '渔获'}｜{e['name']}：{('x' + str(e['count'])) if e['count'] else '未发现'}"
              for e in a["entries"]]
    return "\n".join(lines)


def atlas_all(doc: Any) -> str:
    lines = ["【众生鱼图鉴·诸天总览】"]
    got = total = 0
    for p in planes():
        a = atlas_of(doc, p)
        if not a:
            continue
        got += a["collected"]
        total += a["total"]
        lines.append(f"{p}：{a['collected']}/{a['total']}")
    lines.append(f"总进度：{got}/{total}")
    lines.append("集齐一个位面（含鱼王）可 #领取鱼谱奖励。")
    return "\n".join(lines)


def claim_atlas(doc: Any) -> tuple[bool, str, dict[str, int]]:
    """每位面集齐 4 项 → 愿鳞 ×10（一次性）。"""
    st = state_of(doc)
    claimed = set(st.get("claimed") or [])
    items: dict[str, int] = {}
    done = []
    for p in planes():
        a = atlas_of(doc, p)
        if not a or a["collected"] < a["total"] or p in claimed:
            continue
        claimed.add(p)
        done.append(p)
    if not done:
        return False, "当前没有可领取的鱼谱奖励（需集齐某一位面的 3 鱼 + 鱼王）。", {}
    items[SCALE_ITEM] = 10 * len(done)
    st["claimed"] = sorted(claimed)
    set_state(doc, st)
    return True, ("鱼谱奖励领取成功：\n" + "、".join(done) +
                  f"\n{SCALE_ITEM} ×{items[SCALE_ITEM]}"), items


# ---------------------------------------------------------------- 愿鳞兑换

def wish_cost(name: str) -> tuple[int, dict] | None:
    row = data()["wish"].get(name)
    if not row:
        return None
    return int(row.get("cost") or 0), dict(row.get("reward") or {})


def exchange(doc: Any, name: str, qty: int) -> tuple[bool, str, dict[str, int]]:
    cfg = wish_cost(name)
    if not cfg:
        return False, f"愿鳞兑换单里没有「{name}」（#愿鳞兑换 看清单）。", {}
    cost, reward = cfg
    qty = max(1, min(99, int(qty)))
    need = cost * qty
    items = {str(reward.get("name")): int(reward.get("amount") or 1) * qty}
    return True, (f"以 {need} 枚{SCALE_ITEM} 换得 "
                  f"{reward.get('name')} ×{items[str(reward.get('name'))]}。"), items


def wish_text() -> str:
    lines = [f"【愿鳞兑换】消耗{SCALE_ITEM}，格式：#愿鳞兑换 名称 [份数]"]
    for name, row in data()["wish"].items():
        rw = row.get("reward") or {}
        flag = "（唯一）" if row.get("unique") else ""
        lines.append(f"{name}｜{int(row.get('cost') or 0)} 愿鳞 → "
                     f"{rw.get('name')}×{rw.get('amount')}{flag}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 鱼王（全服）

def fk_default() -> dict[str, Any]:
    return {}


def fk_state(world: Mapping) -> dict[str, Any]:
    raw = world.get("fish_king") if isinstance(world, Mapping) else None
    return dict(raw) if isinstance(raw, Mapping) else {}


def fk_row(world: Mapping, plane: str, avg_hp: float) -> dict[str, Any]:
    st = fk_state(world)
    row = st.get(plane)
    if isinstance(row, Mapping):
        return dict(row)
    king = king_of(plane) or {}
    bar = int(max(50_000, avg_hp * 30))
    return {"plane": plane, "name": king.get("name") or f"{plane}鱼王",
            "hp": bar, "hp_max": bar, "damage": {}, "joined": [],
            "killed": 0, "chest": {}}


def fk_put(world: dict, row: Mapping) -> dict:
    row = dict(row)
    world.setdefault("fish_king", {})
    world["fish_king"][str(row["plane"])] = row
    return world


def fk_list(world: Mapping, avg_hp: float) -> str:
    lines = ["【鱼王列表】"]
    for i, p in enumerate(planes(), 1):
        row = fk_row(world, p, avg_hp)
        pct = 0 if row["hp_max"] <= 0 else int(100 * row["hp"] / row["hp_max"])
        state = "已伏诛（可开箱）" if row["hp"] <= 0 else f"{pct}%"
        lines.append(f"{i}. {p}·{row['name']}｜{state}｜击杀 {row['killed']}")
    lines.append("加入：#加入鱼王讨伐 编号｜出手：#讨伐鱼王 编号｜榜：#鱼王榜 编号｜开箱：#打开鱼王宝箱 编号")
    return "\n".join(lines)


def fk_status(world: Mapping, plane: str, avg_hp: float) -> str:
    row = fk_row(world, plane, avg_hp)
    pct = 0 if row["hp_max"] <= 0 else int(100 * row["hp"] / row["hp_max"])
    lines = [f"【{row['name']}】{plane}",
             f"气血：{row['hp']:,}/{row['hp_max']:,}（{pct}%）",
             f"参战：{len(row.get('joined') or [])} 人｜击杀记录：{row['killed']}"]
    if row["hp"] <= 0:
        lines.append("鱼王已伏诛，参战者可 #打开鱼王宝箱。")
    return "\n".join(lines)


def fk_join(world: dict, plane: str, uid: str, avg_hp: float) -> tuple[bool, str]:
    row = fk_row(world, plane, avg_hp)
    if row["hp"] <= 0:
        return False, "这尊鱼王已伏诛，等待下一次潮汐再战。"
    joined = list(row.get("joined") or [])
    if uid in joined:
        return False, "你已在此战中。"
    joined.append(uid)
    row["joined"] = joined
    fk_put(world, row)
    return True, f"你已加入【{row['name']}】讨伐（现 {len(joined)} 人）。"


def fk_strike(world: dict, plane: str, uid: str, atk: int, rng: random.Random,
              avg_hp: float) -> tuple[bool, str, int, bool]:
    """一次讨伐出手 → (成功, 文案, 伤害, 是否击杀)。单次至多削 10% 上限。"""
    row = fk_row(world, plane, avg_hp)
    if row["hp"] <= 0:
        return False, "鱼王已伏诛，无需再战。", 0, False
    if uid not in (row.get("joined") or []):
        return False, "先 #加入鱼王讨伐 再来出手。", 0, False
    cap = max(1, int(row["hp_max"] * KING_STRIKE_CAP))
    dmg = max(1, min(cap, int(atk * (0.8 + rng.random() * 0.6))))
    row["hp"] = max(0, int(row["hp"]) - dmg)
    dmg_map = dict(row.get("damage") or {})
    dmg_map[uid] = int(dmg_map.get(uid, 0) or 0) + dmg
    row["damage"] = dmg_map
    killed = row["hp"] <= 0
    if killed:
        row["killed"] = int(row.get("killed", 0) or 0) + 1
        chest = dict(row.get("chest") or {})
        for pid in row.get("joined") or []:
            chest[pid] = False
        row["chest"] = chest
    fk_put(world, row)
    tail = "——鱼王气息断绝，海面归于死寂。" if killed else f"，余 {row['hp']:,} 气血。"
    return True, f"你一击削去 {dmg:,} 点气血{tail}", dmg, killed


def fk_rank(world: Mapping, plane: str, avg_hp: float) -> str:
    row = fk_row(world, plane, avg_hp)
    rows = sorted((row.get("damage") or {}).items(), key=lambda kv: -int(kv[1]))
    if not rows:
        return f"【{row['name']}·伤害榜】尚无人出手。"
    lines = [f"【{row['name']}·伤害榜】"]
    for i, (uid, dmg) in enumerate(rows[:10], 1):
        lines.append(f"{i}. {uid}｜{int(dmg):,}")
    return "\n".join(lines)


def fk_open(world: dict, plane: str, uid: str, rng: random.Random,
            avg_hp: float) -> tuple[bool, str, dict[str, int], dict | None]:
    """开箱 → (成功, 文案, 物品, 遗珍)。"""
    row = fk_row(world, plane, avg_hp)
    if row["hp"] > 0:
        return False, "鱼王尚未伏诛，宝箱还锁在潮底。", {}, None
    chest = dict(row.get("chest") or {})
    if uid not in chest:
        return False, "你没有参与这一战，捞不到宝箱。", {}, None
    if chest.get(uid):
        return False, "你的宝箱已经开过了。", {}, None
    chest[uid] = True
    row["chest"] = chest
    fk_put(world, row)
    scales = 15 + int(rng.random() * 16)
    items = {SCALE_ITEM: scales}
    if rng.random() < 0.45:
        items[ROD_ITEM] = 1
    relic = None
    relic_line = ""
    if rng.random() < 0.35:
        from . import relic as relic_mod
        relic = relic_mod.roll_fish_king(plane, rng)
        relic_line = relic_mod.line(relic)
    lines = [f"【鱼王宝箱·{plane}】", f"{SCALE_ITEM} ×{scales}"]
    if ROD_ITEM in items:
        lines.append(f"{ROD_ITEM} ×1")
    if relic_line:
        lines.append(f"潮底遗珍：{relic_line}")
    return True, "\n".join(lines), items, relic
