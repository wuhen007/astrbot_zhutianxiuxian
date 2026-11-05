"""舟出海探险（W8-A3）：三阶舟 / 三航线 / 每日三次 / 见闻录收集。

原版：`apps/User/SeaVoyage.js` 650 + `model/seaVoyage.js` 363 + 方案文档 153 行。

保留：
- 三阶舟（一叶轻舟 ×1 / 界河灵舟 ×1.5 / 诸天仙舟 ×2），统一 120 分钟一趟
- 首舟配方（群星之沙 ×20 + 众生愿鳞 ×50），升阶吃「低阶舟 + 材料」
- 出海消耗：众生仙钓 ×1 + 众生愿鳞 ×10（可用 1 枚仙饵替代愿鳞）
- 每日 3 趟；三条航线（凡间河 / 遮天渊 / 界海）各自对应位面组与特产仙饵
- 回港结算：愿鳞 10~20 × 舟倍率（旺潮 ×1.5）+ 材料 + 50% 见闻；12% 恶性事件损舟；
  60% 海域事件三选一（宝箱 / 风暴 / 异兽）
- 见闻录：每航线 3 条（2 普通 + 1 传说），集齐兑换该航线特产仙饵

shortcut：原版「拆解赎回」（装备拆解返还）在本移植无对应体系，折算为愿鳞返还；
出海挂机到点由下一次相关指令惰性结算（无独立定时器），与原版一致。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

ROD_ITEM = "众生仙钓"
SCALE_ITEM = "众生愿鳞"
VOYAGE_MINUTES = 120
VOYAGE_COST_SCALES = 10
DAILY_LIMIT = 3
DISASTER_CHANCE = 0.12
EVENT_CHANCE = 0.60

BOATS: tuple[dict[str, Any], ...] = (
    {"name": "一叶轻舟", "mult": 1.0,
     "upgrade": {"name": "界河灵舟",
                 "mats": {"一叶轻舟": 1, "彼岸星砂": 10, "众生愿鳞": 100}}},
    {"name": "界河灵舟", "mult": 1.5,
     "upgrade": {"name": "诸天仙舟",
                 "mats": {"界河灵舟": 1, "纪元之力": 5, "众生愿鳞": 200}}},
    {"name": "诸天仙舟", "mult": 2.0, "upgrade": None},
)
FIRST_BOAT_MATS = {"群星之沙": 20, "众生愿鳞": 50}

ROUTES: dict[str, dict[str, Any]] = {
    "凡间河": {"planes": ["凡间", "仙界"], "bait": "百草香饵",
              "atlas": [("渔火渡口", "common"), ("浣纱水府", "common"), ("龙门浮影", "legend")]},
    "遮天渊": {"planes": ["遮天位面", "下界八域", "九天十地"], "bait": "神藏仙饵",
              "atlas": [("帝路残碑", "common"), ("沉棺渊涡", "common"), ("仙路残影", "legend")]},
    "界海": {"planes": ["太初星墟", "仙域"], "bait": "矿髓沉饵",
             "atlas": [("星墟潮眼", "common"), ("界海孤灯", "common"), ("万界归流", "legend")]},
}

EVENTS: tuple[dict[str, Any], ...] = (
    {"id": "sea-treasure", "title": "海域奇遇·浮金宝箱",
     "intro": "浪尖浮起一只缠绕海藻的宝箱，锁扣锈迹斑斑，四周灵气氤氲。",
     "choices": (
         ("开箱取宝", {SCALE_ITEM: 8}, None, 0.0, "宝箱里躺着八枚众生愿鳞。"),
         ("拆下沉木", {"群星之沙": 5}, None, 0.0, "你拆下箱板，竟是星墟沉木。"),
         ("任其漂流", {}, "legend", 0.0, "你不愿扰动此物，反而望见远处一道奇异水光。"),
     )},
    {"id": "sea-storm", "title": "海域奇遇·风暴压境",
     "intro": "乌云压顶，巨浪如山，你的舟在风暴眼里打转。",
     "choices": (
         ("全力破浪", {}, None, 0.0, "你以法力破开浪墙，货物无损。"),
         ("降帆漂流", {}, None, 0.3, "风暴卷走三成货物，但舟与人都安然无恙。"),
         ("观望潮眼", {}, "legend", 0.0, "你盯着潮眼深处，隐约望见不该存在之物。"),
     )},
    {"id": "sea-beast", "title": "海域奇遇·异兽拦舟",
     "intro": "一道黑影绕着舟底游弋，水面泛起诡异磷光。",
     "choices": (
         ("投饵引开", {"神藏仙饵": 1}, None, 0.0, "你投下一枚神藏仙饵，黑影满意地沉入水底。"),
         ("出手驱逐", {"彼岸星砂": 1}, None, 0.0, "你击退异兽，拾得一片彼岸星砂。"),
         ("跟随踪迹", {}, "common", 0.0, "你循着磷光追去，记下一段寻常见闻。"),
     )},
)

DISASTERS = (
    "灭世风暴拔海而起，浪墙如山，雷霆劈碎桅杆。",
    "一头沉睡万古的海渊巨兽被舟影惊醒，怒尾横扫。",
    "界海潮汐毫无征兆地倒卷，暗流绞缠舟身，龙骨呻吟。",
)


def boat_tier(name: str | None) -> int:
    for i, row in enumerate(BOATS):
        if row["name"] == name:
            return i
    return -1


def boat_mult(name: str | None) -> float:
    i = boat_tier(name)
    return float(BOATS[i]["mult"]) if i >= 0 else 0.0


def state_of(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get("voyage") if isinstance(getattr(doc, "ext", None), Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("boat", None)
    st.setdefault("day", "")
    st.setdefault("used", 0)
    st.setdefault("voyage", None)
    st.setdefault("atlas", {})
    st.setdefault("claimed", [])
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["voyage"] = dict(st)


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now + 8 * 3600))


# ---------------------------------------------------------------- 造舟

def build_cost(doc: Any) -> tuple[bool, str, dict[str, int]]:
    """→ (是否升阶, 文案, 需求材料)。"""
    boat = state_of(doc).get("boat")
    if not boat:
        return False, f"尚未有舟。首舟需：{'、'.join(f'{k}×{v}' for k, v in FIRST_BOAT_MATS.items())}", dict(FIRST_BOAT_MATS)
    tier = boat_tier(str(boat))
    row = BOATS[tier] if tier >= 0 else None
    up = row.get("upgrade") if row else None
    if not up:
        return False, f"【{boat}】已是诸天仙舟，再无升阶之路。", {}
    return True, (f"【{boat}】可升【{up['name']}】，需："
                  + "、".join(f"{k}×{v}" for k, v in up["mats"].items())), dict(up["mats"])


def build(doc: Any, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    """→ (成功, 文案, 实扣材料)。"""
    upgrade, msg, need = build_cost(doc)
    if not need:
        return False, msg, {}
    lacking = [f"{k}（有 {int(inv.get(k, 0) or 0)}）" for k, v in need.items()
               if int(inv.get(k, 0) or 0) < v]
    if lacking:
        return False, f"{msg}\n缺口：{'、'.join(lacking)}", {}
    st = state_of(doc)
    st["boat"] = (BOATS[boat_tier(str(st.get('boat')))]["upgrade"]["name"]
                  if upgrade else BOATS[0]["name"])
    set_state(doc, st)
    verb = "升阶" if upgrade else "造成"
    return True, f"舟成！【{st['boat']}】{verb}（收益 ×{boat_mult(st['boat']):g}）。", dict(need)


def shed_text(doc: Any) -> str:
    st = state_of(doc)
    boat = st.get("boat")
    lines = ["【舟仓】", f"当前之舟：{boat or '无'}"
             + (f"（收益 ×{boat_mult(boat):g}）" if boat else "")]
    if not boat:
        lines.append(f"首舟配方：{'、'.join(f'{k}×{v}' for k, v in FIRST_BOAT_MATS.items())}")
    else:
        up, msg, _need = build_cost(doc)
        lines.append(msg)
    if st.get("voyage"):
        v = st["voyage"]
        left = max(0, int(float(v.get("end") or 0) - time.time()))
        lines.append(f"出海中：{v.get('route')}｜剩余 {left // 60} 分 {left % 60} 秒")
    lines.append(f"今日已出海 {int(st.get('used', 0) or 0)}/{DAILY_LIMIT} 趟。")
    lines.append("升：#造舟 升级｜出海：#出海 航线｜见闻：#海域见闻")
    return "\n".join(lines)


# ---------------------------------------------------------------- 出海

def sail_cost(inv: Mapping[str, int], use_bait: str | None = None) -> tuple[dict[str, int], str]:
    """→ (实际要扣的物品, 说明)。"""
    cost = {ROD_ITEM: 1}
    if use_bait:
        cost[use_bait] = 1
        note = f"1 根钓竿 + 1 枚{use_bait}"
    else:
        cost[SCALE_ITEM] = VOYAGE_COST_SCALES
        note = f"1 根钓竿 + {VOYAGE_COST_SCALES} 愿鳞"
    lacking = [k for k, v in cost.items() if int(inv.get(k, 0) or 0) < v]
    return cost, note if not lacking else "缺：" + "、".join(lacking)


def can_sail(doc: Any, now: float, inv: Mapping[str, int],
             use_bait: str | None = None) -> tuple[bool, str]:
    st = state_of(doc)
    if not st.get("boat"):
        return False, "你还没有舟（#造舟）。"
    if st.get("voyage"):
        left = int(float(st["voyage"].get("end") or 0) - now)
        if left > 0:
            return False, f"舟还在海上，剩 {left // 60} 分 {left % 60} 秒回港。"
    if str(st.get("day")) == _day(now) and int(st.get("used", 0) or 0) >= DAILY_LIMIT:
        return False, f"今日已出海 {DAILY_LIMIT} 趟，明日再来。"
    cost, note = sail_cost(inv, use_bait)
    if isinstance(note, str) and note.startswith("缺："):
        return False, f"出海需 {note[2:]}。"
    return True, ""


def start(doc: Any, route: str, now: float, inv: Mapping[str, int],
          use_bait: str | None = None) -> tuple[bool, str, dict[str, int]]:
    ok, why = can_sail(doc, now, inv, use_bait)
    if not ok:
        return False, why, {}
    if route not in ROUTES:
        return False, f"没有「{route}」这条航线（{'、'.join(ROUTES)}）。", {}
    st = state_of(doc)
    if str(st.get("day")) != _day(now):
        st["day"], st["used"] = _day(now), 0
    st["used"] = int(st.get("used", 0) or 0) + 1
    st["voyage"] = {"route": route, "start": float(now),
                    "end": float(now) + VOYAGE_MINUTES * 60,
                    "boat": st.get("boat"), "bait": use_bait}
    set_state(doc, st)
    cost, _note = sail_cost(inv, use_bait)
    return True, (f"舟离岸，驶向【{route}】。{VOYAGE_MINUTES} 分钟后回港，"
                  f"届时发 #舟仓 或 #出海 结算。"), cost


# ---------------------------------------------------------------- 回港结算

def _weighted(rows: list[Mapping], rng: random.Random) -> Mapping | None:
    total = sum(float(r.get("weight", 1)) for r in rows) or 0
    if total <= 0:
        return None
    cur = rng.random() * total
    for r in rows:
        cur -= float(r.get("weight", 1))
        if cur < 0:
            return r
    return rows[-1]


def _sighting(route: str, st: dict, rng: random.Random, boosted: bool) -> str | None:
    if rng.random() >= 0.5:
        return None
    entries = ROUTES[route]["atlas"]
    legend = rng.random() < (0.30 if boosted else 0.15)
    pool = [e for e in entries if e[1] == ("legend" if legend else "common")]
    if not pool:
        pool = entries
    name = pool[int(rng.random() * len(pool))][0]
    row = st.setdefault("atlas", {}).setdefault(route, {})
    row[name] = int(row.get(name, 0) or 0) + 1
    return name


def tide_boosted(route: str, world_year: int) -> bool:
    try:
        from . import fishing as fish_mod
        t = fish_mod.tide(world_year)
    except Exception:
        return False
    if not t.get("active"):
        return False
    return any(p in t["planes"] for p in ROUTES[route]["planes"])


def settle(doc: Any, now: float, world_year: int,
           rng: random.Random) -> tuple[bool, str, dict[str, int], dict | None]:
    """到点回港结算 → (是否结算, 文案, 物品, 奇遇事件)。"""
    st = state_of(doc)
    v = st.get("voyage")
    if not isinstance(v, Mapping):
        return False, "当前没有在海上。", {}, None
    if float(v.get("end") or 0) > now:
        left = int(float(v["end"]) - now)
        return False, f"舟还在海上，剩 {left // 60} 分 {left % 60} 秒。", {}, None
    route = str(v.get("route"))
    boat = str(v.get("boat") or st.get("boat") or BOATS[0]["name"])
    st["voyage"] = None
    boosted = tide_boosted(route, world_year)
    items: dict[str, int] = {}
    lines = [f"【回港·{route}】"]
    # 恶性事件：12% 损舟
    if rng.random() < DISASTER_CHANCE:
        text = DISASTERS[int(rng.random() * len(DISASTERS))]
        tier = boat_tier(boat)
        if tier <= 0:
            st["boat"] = None
            for k, val in FIRST_BOAT_MATS.items():
                items[k] = items.get(k, 0) + max(1, int(val * 0.7))
            lines.append(text + "一叶轻舟沉没，残骸里捞回七成首舟材料。")
        else:
            st["boat"] = BOATS[tier - 1]["name"]
            lines.append(text + f"舟体崩解，残骸重组成【{st['boat']}】。")
        set_state(doc, st)
        return True, "\n".join(lines), items, None
    # 基础收益：愿鳞 10~20 × 舟倍率 × 旺潮 1.5
    base = 10 + int(rng.random() * 11)
    scales = max(1, int(base * boat_mult(boat) * (1.5 if boosted else 1)))
    items[SCALE_ITEM] = scales
    mat_table = ([{"name": None, "weight": 20}, {"name": "群星之沙", "weight": 30},
                  {"name": "彼岸星砂", "weight": 25}, {"name": "纪元之力", "weight": 15},
                  {"name": ROUTES[route]["bait"], "weight": 10}]
                 if boosted else
                 [{"name": None, "weight": 40}, {"name": "群星之沙", "weight": 25},
                  {"name": "彼岸星砂", "weight": 20}, {"name": "纪元之力", "weight": 10},
                  {"name": ROUTES[route]["bait"], "weight": 5}])
    mat = _weighted(mat_table, rng)
    if mat and mat.get("name"):
        items[str(mat["name"])] = items.get(str(mat["name"]), 0) + 1
    lines.append(f"愿鳞 ×{scales}" + (f"（旺潮 ×1.5）" if boosted else ""))
    lines.append("随舟带回：" + "、".join(f"{k}×{v}" for k, v in items.items()))
    seen = _sighting(route, st, rng, boosted)
    if seen:
        lines.append(f"见闻录 +1：【{seen}】")
    # 60% 海域事件
    event = None
    if rng.random() < EVENT_CHANCE:
        event = dict(EVENTS[int(rng.random() * len(EVENTS))])
        st["event"] = {"id": event["id"], "exp": now + 1800}
        lines.append(f"海域事件：{event['title']}（#出海 决策 或 #出海 事件 1/2/3）")
    set_state(doc, st)
    return True, "\n".join(lines), items, event


def event_pending(doc: Any, now: float) -> dict | None:
    st = state_of(doc)
    row = st.get("event")
    if not isinstance(row, Mapping):
        return None
    if float(row.get("exp") or 0) <= now:
        st["event"] = None
        set_state(doc, st)
        return None
    return dict(row)


def event_text(doc: Any, now: float) -> str:
    row = event_pending(doc, now)
    if not row:
        return "当前没有待处理的海域事件。"
    ev = next((e for e in EVENTS if e["id"] == row.get("id")), None)
    if not ev:
        return "这段海域事件已随潮散去。"
    lines = [f"【{ev['title']}】", ev["intro"]]
    lines += [f"{i}. {c[0]}" for i, c in enumerate(ev["choices"], 1)]
    lines.append("发送 #出海 事件 1/2/3 作出选择（30 分钟内有效）。")
    return "\n".join(lines)


def choose_event(doc: Any, now: float, choice: int, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    row = event_pending(doc, now)
    if not row:
        return False, "当前没有待处理的海域事件。", {}
    ev = next((e for e in EVENTS if e["id"] == row.get("id")), None)
    if not ev:
        return False, "这段海域事件已随潮散去。", {}
    idx = int(choice) - 1
    if idx < 0 or idx >= len(ev["choices"]):
        return False, "这条事件没有对应选择（1~3）。", {}
    label, items, sighting, lose_ratio, msg = ev["choices"][idx]
    st = state_of(doc)
    st["event"] = None
    if sighting:
        route = ROUTES and list(ROUTES)[0]
        # 见闻记在最近一条航线上；找不到就用第一条
        last = (st.get("voyage") or {}).get("route") if isinstance(st.get("voyage"), Mapping) else None
        route = last if last in ROUTES else list(ROUTES)[0]
        entries = ROUTES[route]["atlas"]
        pool = [e for e in entries if e[1] == sighting] or entries
        name = pool[int(rng.random() * len(pool))][0]
        rec = st.setdefault("atlas", {}).setdefault(route, {})
        rec[name] = int(rec.get(name, 0) or 0) + 1
        msg += f"（见闻录 +1：【{name}】）"
    if lose_ratio:
        msg += f"（本趟收益扣减 {lose_ratio:.0%}，由结算时另行扣除）"
    set_state(doc, st)
    return True, f"【{ev['title']}·{label}】\n{msg}", dict(items)


# ---------------------------------------------------------------- 见闻

def atlas_text(doc: Any) -> str:
    st = state_of(doc)
    lines = ["【海域见闻】"]
    total = got = 0
    for route, cfg in ROUTES.items():
        rec = (st.get("atlas") or {}).get(route) or {}
        entries = []
        for name, kind in cfg["atlas"]:
            n = int(rec.get(name, 0) or 0)
            total += 1
            got += 1 if n else 0
            entries.append(f"{name}{'（传说）' if kind == 'legend' else ''}：{('x' + str(n)) if n else '未发现'}")
        lines.append(f"【{route}】" + "、".join(entries))
    lines.append(f"总进度：{got}/{total}")
    lines.append("集齐一条航线可 #领取见闻奖励（得该航线特产仙饵）。")
    return "\n".join(lines)


def claim_atlas(doc: Any) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    claimed = set(st.get("claimed") or [])
    items: dict[str, int] = {}
    done = []
    for route, cfg in ROUTES.items():
        rec = (st.get("atlas") or {}).get(route) or {}
        if route in claimed:
            continue
        if all(int(rec.get(name, 0) or 0) > 0 for name, _k in cfg["atlas"]):
            claimed.add(route)
            done.append(route)
            items[cfg["bait"]] = items.get(cfg["bait"], 0) + 2
    if not done:
        return False, "没有可领取的见闻奖励（需集齐某条航线的 3 条见闻）。", {}
    st["claimed"] = sorted(claimed)
    set_state(doc, st)
    return True, ("见闻奖励：\n" + "、".join(done) + "\n"
                  + "、".join(f"{k}×{v}" for k, v in items.items())), items
