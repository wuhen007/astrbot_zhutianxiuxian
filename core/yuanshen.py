"""元神体系与精神宇宙（W8-B2b）。

原版依据：
- `apps/User/yuanshen.js`（1224 行，15 条指令）
- `model/spiritUniverse.js`（420 行：心神、抉择、守关战、保留率）
- `data/item/精神宇宙.json`（9 个精神位面 / 28 层 / 54 条掉落）

本模块覆盖：
- 元神数值：`#凝练元神`（16 级境界表）+ `#我的元神` + `#服食天药`
- 15 门法门四类用法：`以X修炼元神`（恢复）/ `以X淬炼元神`（提升上限）/
  `以X元神爆发`（战斗增伤 5 分钟）/ `以X元神护体`（战斗减伤 30 分钟）
- 精神宇宙：`#精神宇宙` / `#神游 位面` / `#观想` / `#抉择 N` / `#深入` / `#归位` / `#神识状态`
- 内景地修炼：`#内景地修炼 [次数]`（与 W8-B2a 的仓库共用同一块地）

shortcut（与原版的差异，均已折算而非省略）：
1. 元神原版靠拍卖行/秘境天药海量产出；本移植首次凝练门槛取原版的 1/10（150 万），
   之后仍走 `1500 万 × 凝练次数`。
2. 内景地修炼原版消耗 `1500万 × 额外体系等级和` 的元神、产出「修为/血气/神识」；
   本移植改为 `15万 ×（元神等级+1）× 次数`，产出「修为/血气/元神」——本移植没有
   神识系统，守关战用元神上限兜底（原版公式本身就有 `max(神识, 上限×0.08, …)`）。
3. 原版「道伤」无对应体系；元神护体改为战斗减伤（`dmg_taken_mult`），爆发改为 `dmg_dealt_mult`。
4. 神游状态原版存 redis，本移植存 `doc.ext["yuanshen"]["shenyou"]`，离线不丢、无需加锁。
5. 未做：问道仙宫（心神 ×2 与恢复加速的伪至宝）、文献令进度、命格消耗倍率、往世乐土联动。
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Mapping, Sequence
from typing import Any

from . import wenxian

# ---------------------------------------------------------------- 心神经脉

HEART_ENTRY = 10              # 每次神游入场消耗
HEART_BASE_MAX = 30
HEART_LEVEL_BONUS = 3         # 每级元神 +3 上限
HEART_HARD_CAP = 100
HEART_RECOVER_SECONDS = 30 * 60

# ---------------------------------------------------------------- 元神境界（16 级）

LEVEL_NAMES: tuple[str, ...] = (
    "紫府元神",
    "仙台/神火/金身·亚圣级元神",
    "王者/真神/圣者级元神",
    "圣人/天神/映照诸天级元神",
    "圣王/虚道/神祇级元神",
    "大圣/斩我/神将级元神",
    "准帝/遁一/神王级元神",
    "大帝/极道至尊/天尊·混元级元神",
    "真仙/大宇·究极级元神",
    "仙王/宇究级元神",
    "仙王巨头级元神",
    "准仙帝/道祖级元神",
    "仙帝/路尽级元神",
    "祭道级元神",
    "祭道之上级元神",
    "超脱/唯一道之上级元神",
)

CONSOLIDATE_BASE = 15_000_000      # 原版：1500 万 × 凝练次数
CONSOLIDATE_FIRST = 1_500_000      # 本移植首次取 1/10，见模块头 shortcut 1
CONSOLIDATE_TIER_BASE = 10         # 晋升门槛：authority_21 >= 10 + 当前等级

# ---------------------------------------------------------------- 15 门法门

SKILLS: dict[str, dict] = {
    # 恢复类：缓慢恢复元神
    "前字秘": {"cd": 240, "ratio": 0.20, "type": "恢复"},
    "太一凝神诀": {"cd": 180, "ratio": 0.08, "type": "恢复"},
    "涅槃法门·残缺": {"cd": 360, "ratio": 0.01, "type": "恢复"},
    "涅槃法门": {"cd": 240, "ratio": 0.10, "type": "恢复"},
    "神火淬魂法": {"cd": 300, "ratio": 0.12, "type": "恢复"},
    "观照经": {"cd": 200, "ratio": 0.06, "type": "恢复"},
    "太虚蕴神经": {"cd": 240, "ratio": 0.10, "type": "恢复"},
    # 淬炼类：消耗元神提升上限
    "九劫玄身": {"cd": 720, "ratio": 0.15, "type": "淬炼", "boost": 0.05},
    "九灭重生经": {"cd": 1440, "ratio": 0.20, "type": "淬炼", "boost": 0.10},
    "帝印炼神诀": {"cd": 1080, "ratio": 0.18, "type": "淬炼", "boost": 0.08},
    "葬仙经": {"cd": 1440, "ratio": 0.25, "type": "淬炼", "boost": 0.12},
    # 爆发类：临时增伤
    "神灵斩劫经": {"cd": 480, "type": "爆发", "cost": 0.15, "dmg_boost": 0.25},
    "劫运神拳": {"cd": 600, "type": "爆发", "cost": 0.20, "dmg_boost": 0.30},
    # 防御类：临时减伤
    "元神盾": {"cd": 360, "type": "防御", "cost": 0.10, "block": 0.5},
    "九劫雷符": {"cd": 600, "type": "防御", "cost": 0.15, "block": 0.7},
    # 神游类：提升探索效率
    "搜魂大法": {"cd": 300, "type": "神游", "event_bonus": 0.15},
    "花粉蜕变经": {"cd": 480, "type": "神游", "depth_bonus": 1},
    "十二万九千六百念经": {"cd": 600, "type": "神游", "event_bonus": 0.20},
}

TYPE_LABEL = {"恢复": "恢复类", "淬炼": "淬炼类", "爆发": "爆发类",
              "防御": "防御类", "神游": "神游类"}

BURST_SECONDS = 5 * 60
SHIELD_SECONDS = 30 * 60

# ---------------------------------------------------------------- 精神位面（运行时注入）

PLACES: list[dict] = []
_LAYER_CACHE: dict[int, list[dict]] = {}

GUARDIANS: dict[int, tuple[str, ...]] = {
    333: ("无名剑修余念", "残宫守印者"),
    334: ("讲经古贤烙印", "护崖道人残魂"),
    335: ("渡劫者残魂", "劫运魔念"),
    336: ("点火古神余念", "失控神火灵", "祭坛守火人"),
    337: ("史前进化者残魂", "畸变花灵", "百世轮回烙印"),
    338: ("无主念头聚合体", "梦中圣者余念", "十二万九千六百念主"),
    339: ("帝印守灵", "败亡帝者残魂", "帝陨恶念", "残帝烙印"),
    340: ("三劫鬼仙余念", "六劫雷魂", "八劫鬼仙残念", "九劫雷灵"),
    341: ("葬仙残魂", "不灭仙念", "万仙怨念", "真仙守墓人", "仙帝投影"),
}

# 强制归位时按层保留收获（第 1 层为 0，与原版一致）
FORCED_RETENTION: tuple[float, ...] = (0.0, 0.8, 0.65, 0.5, 0.35, 0.2)

CHOICES: tuple[tuple[int, str, str, float], ...] = (
    (1, "steady", "镇守心神", 0.5),
    (2, "treasure", "搜寻机缘", 1.0),
    (3, "insight", "参悟道痕", 1.2),
)

EVENT_INTROS = {
    "念头风暴": "无数陌生念头汇成风暴，正在撕扯你的识海边界。",
    "道则碎片": "一枚残缺道则悬在虚空中，周围还有数道危险气息游弋。",
    "古贤烙印": "古贤虚影自岁月中显化，一指点向你的眉心。",
    "心魔幻象": "熟悉的身影从迷雾中走来，你却无法判断它是真是假。",
    "灵光乍现": "一道灵光划破识海，深处似乎藏着更完整的道痕。",
    "天药凝形": "精神能量逐渐凝成天药，虚空也随之开始坍缩。",
}


def load_places(rows: Sequence[Mapping]) -> int:
    """把 data/jingshen/精神宇宙.json 灌进模块（返回位面数）。"""
    PLACES.clear()
    _LAYER_CACHE.clear()
    for row in rows or []:
        if not isinstance(row, Mapping) or not row.get("name"):
            continue
        place = dict(row)
        place["layers"] = [dict(x) for x in (row.get("layers") or [])]
        PLACES.append(place)
        _LAYER_CACHE[int(place.get("id") or 0)] = place["layers"]
    return len(PLACES)


def find_place(name: str) -> dict | None:
    name = str(name or "").strip()
    return next((p for p in PLACES if str(p.get("name")) == name), None)


def find_by_id(pid: Any) -> dict | None:
    return next((p for p in PLACES if int(p.get("id") or 0) == int(pid or 0)), None)


# ---------------------------------------------------------------- 状态

def ensure(doc: Any) -> dict:
    """取元神状态（缺失则建默认值），不写回。"""
    raw = doc.ext.get("yuanshen") if isinstance(doc.ext, Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("level", None)
    st.setdefault("cur", 0)
    st.setdefault("max", 0)
    if int(st.get("max") or 0) > 0 and int(st.get("cur") or 0) > int(st["max"]):
        st["cur"] = int(st["max"])
    st.setdefault("lian", 1)
    st.setdefault("extra_max", 0)
    st.setdefault("first_clear", [])
    st.setdefault("cd", {})
    st.setdefault("buff", None)
    st.setdefault("shield", None)
    st.setdefault("shenyou", None)
    heart = st.get("heart") if isinstance(st.get("heart"), Mapping) else {}
    st["heart"] = {"cur": int(heart.get("cur", 0) or 0),
                   "max": int(heart.get("max", 0) or 0),
                   "last": float(heart.get("last", 0) or 0)}
    return st


def save(doc: Any, st: Mapping) -> None:
    doc.ext["yuanshen"] = dict(st)


def level_of(doc: Any) -> int | None:
    lv = ensure(doc).get("level")
    return None if lv is None else max(0, min(len(LEVEL_NAMES) - 1, int(lv)))


def level_name(doc: Any) -> str:
    lv = level_of(doc)
    return "未凝练" if lv is None else LEVEL_NAMES[lv]


def cur_of(doc: Any) -> int:
    return max(0, int(ensure(doc).get("cur", 0) or 0))


def max_of(doc: Any) -> int:
    return max(0, int(ensure(doc).get("max", 0) or 0))


def add_cur(doc: Any, amount: int) -> int:
    st = ensure(doc)
    cap = max(int(st.get("max", 0) or 0), 0)
    st["cur"] = max(0, min(cap, int(st.get("cur", 0) or 0) + int(amount)))
    save(doc, st)
    return int(st["cur"])


def add_max(doc: Any, amount: int) -> int:
    st = ensure(doc)
    st["max"] = max(0, int(st.get("max", 0) or 0) + int(amount))
    save(doc, st)
    return int(st["max"])


def learned(doc: Any) -> list[str]:
    return [str(x) for x in (doc.ext.get("gongfa") or [])]


def known_skills(doc: Any) -> list[str]:
    return [s for s in learned(doc) if s in SKILLS]


def has_skill(doc: Any, name: str) -> bool:
    return str(name) in learned(doc)


# ---------------------------------------------------------------- 心神

def heart_max(doc: Any, st: Mapping | None = None) -> int:
    st = st or ensure(doc)
    lv = st.get("level")
    base = HEART_BASE_MAX + (0 if lv is None else int(lv) * HEART_LEVEL_BONUS)
    base += max(0, int(st.get("extra_max", 0) or 0))
    try:
        from .mingge import bonus
        fate_extra = int(bonus(doc, "心神额外上限"))
    except (TypeError, ValueError):
        fate_extra = 0
    return max(HEART_BASE_MAX, min(HEART_HARD_CAP + fate_extra, base + fate_extra))


def heart_cost(doc: Any, base: int) -> int:
    """命格修正神游心神消耗；倍率归零可免除成本。"""
    try:
        from .mingge import effects_of
        effects = effects_of(doc)
        multiplier = min(3.0, max(0.0,
            1.0 - float(effects.get("心神消耗减少", 0) or 0)
            + float(effects.get("心神消耗增加", 0) or 0)))
    except (TypeError, ValueError):
        multiplier = 1.0
    return max(0, int(math.ceil(max(0, int(base)) * multiplier)))


def heart_of(doc: Any, now: float | None = None) -> tuple[int, int]:
    """惰性恢复心神，返回 (当前, 上限)；首次访问直接满。"""
    now = time.time() if now is None else float(now)
    st = ensure(doc)
    cap = heart_max(doc, st)
    heart = st["heart"]
    if heart["max"] != cap or heart["last"] <= 0:
        heart["max"] = cap
        if heart["cur"] <= 0 and heart["last"] <= 0:
            heart["cur"] = cap
        heart["last"] = now
    last = float(heart["last"])
    if last > now:
        last = now
    ticks = max(0, int((now - last) // HEART_RECOVER_SECONDS))
    if ticks:
        heart["cur"] = min(cap, int(heart["cur"]) + ticks)
        heart["last"] = now if heart["cur"] >= cap else last + ticks * HEART_RECOVER_SECONDS
    heart["cur"] = max(0, min(cap, int(heart["cur"])))
    st["heart"] = heart
    save(doc, st)
    return int(heart["cur"]), cap


def heart_minutes_left(doc: Any, now: float | None = None) -> int:
    now = time.time() if now is None else float(now)
    st = ensure(doc)
    last = float(st["heart"].get("last", 0) or 0)
    if last <= 0:
        return 0
    left = HEART_RECOVER_SECONDS - ((now - last) % HEART_RECOVER_SECONDS)
    return max(1, int(left // 60))


def consume_heart(doc: Any, cost: int, now: float | None = None) -> tuple[bool, int, int]:
    stamp = time.time() if now is None else float(now)
    cur, cap = heart_of(doc, stamp)
    need = max(0, int(cost))
    if cur < need:
        return False, cur, cap
    st = ensure(doc)
    st["heart"]["cur"] = cur - need
    if int(st["heart"]["cur"]) < cap and float(st["heart"].get("last") or 0) <= 0:
        st["heart"]["last"] = stamp
    save(doc, st)
    if need:
        wx = wenxian.system_of(doc)
        wenxian.record_weekly(wx, "spirit_heart", need, stamp)
        doc.ext["wenxian"] = wx
    return True, cur - need, cap


def raise_heart_limit(doc: Any, amount: int) -> int:
    """首通位面提升心神上限（受 HEART_HARD_CAP 限制），返回实际增量。"""
    st = ensure(doc)
    before = heart_max(doc, st)
    room = max(0, HEART_HARD_CAP - before)
    gain = min(room, max(0, int(amount)))
    if gain:
        st["extra_max"] = int(st.get("extra_max", 0) or 0) + gain
        st["heart"]["max"] = before + gain
        st["heart"]["cur"] = min(before + gain, int(st["heart"]["cur"]) + gain)
        save(doc, st)
    return gain


# ---------------------------------------------------------------- 凝练

def consolidate_cost(doc: Any) -> int:
    st = ensure(doc)
    if st.get("level") is None:
        return CONSOLIDATE_FIRST
    return CONSOLIDATE_BASE * max(1, int(st.get("lian", 1) or 1))


def consolidate(doc: Any) -> tuple[bool, str]:
    """#凝练元神：16 级境界表，晋升受 authority_21 门槛限制。"""
    from .authority import authority_21

    st = ensure(doc)
    lv = st.get("level")
    cost = consolidate_cost(doc)
    cur = int(st.get("cur", 0) or 0)
    if lv is not None and int(lv) >= len(LEVEL_NAMES) - 1:
        return False, "你的元神已凝练至当前最高境界（超脱/唯一道之上）。"
    if lv is not None:
        need_tier = CONSOLIDATE_TIER_BASE + int(lv)
        tier = authority_21(doc)
        if tier < need_tier:
            return False, (f"凝练【{LEVEL_NAMES[int(lv) + 1]}】需主修权柄达 {need_tier} 重天"
                           f"（当前 {tier} 重天）。")
    if cur < cost:
        return False, (f"凝练需元神 {cost:,}（当前 {cur:,}）。\n"
                       f"元神来源：#服食天药（秘境/精神宇宙的天药）、#内景地修炼、"
                       f"以恢复类法门 #以X修炼元神。")
    st["cur"] = cur - cost
    st["level"] = 0 if lv is None else int(lv) + 1
    st["lian"] = int(st.get("lian", 1) or 1) + (1 if lv is None else 0)
    save(doc, st)
    _ = heart_of(doc)      # 等级变化 → 心神上限同步
    return True, (f"紫府洞开，元神凝形！\n"
                  f"元神境界：【{LEVEL_NAMES[int(st['level'])]}】\n"
                  f"消耗元神 {cost:,}，余 {st['cur']:,}/{st['max']:,}。\n"
                  f"心神上限同步为 {heart_max(doc)}。")


# ---------------------------------------------------------------- 天药

def spirit_pills(doc: Any, inv: Mapping[str, int], item_index: Mapping[str, Mapping]) -> list[dict]:
    """背包里可服食的天药（class=丹药 且 type=天药 且带 yuanshen）。"""
    out = []
    for name, qty in (inv or {}).items():
        cnt = int(qty or 0)
        if cnt <= 0:
            continue
        row = item_index.get(str(name)) or {}
        if str(row.get("class") or "") != "丹药" or str(row.get("type") or "") != "天药":
            continue
        gain = int(row.get("yuanshen") or 0)
        if gain <= 0:
            continue
        out.append({"name": str(name), "qty": cnt, "gain": gain,
                    "daoshang": int(row.get("daoshang") or row.get("道伤") or 0)})
    out.sort(key=lambda r: r["gain"])
    return out


def take_pills(doc: Any, inv: Mapping[str, int], item_index: Mapping[str, Mapping],
               which: str = "") -> tuple[bool, str, dict[str, int]]:
    """#服食天药 [名称|全部]：元神与上限同时增加（原版 UserSellAll.js:1770）。"""
    rows = spirit_pills(doc, inv, item_index)
    if not rows:
        return False, "纳戒里没有可服食的天药（天药来自秘境与精神宇宙）。", {}
    which = str(which or "").strip()
    if which and which not in ("全部", "all", "一键"):
        rows = [r for r in rows if r["name"] == which]
        if not rows:
            return False, f"纳戒里没有【{which}】这种天药。", {}
    used: dict[str, int] = {}
    gain = 0
    healed = 0.0
    for row in rows:
        used[row["name"]] = row["qty"]
        gain += row["gain"] * row["qty"]
        healed += float(row.get("daoshang") or 0) * row["qty"]
    st = ensure(doc)
    st["cur"] = int(st.get("cur", 0) or 0) + gain
    st["max"] = int(st.get("max", 0) or 0) + gain
    save(doc, st)
    wnote = ""
    if healed > 0:
        try:
            from . import zhengdao as _dz
            left = _dz.heal(doc, healed, "雷帝道液")
            wnote = f"｜道伤 -{healed:g}（现 {left:.1f}）"
        except Exception:
            pass
    detail = "、".join(f"{k}×{v}" for k, v in used.items())
    return True, (f"服食天药：{detail}\n"
                  f"元神 +{gain:,}，上限 +{gain:,}（现 {st['cur']:,}/{st['max']:,}）{wnote}。"), used


# ---------------------------------------------------------------- 法门四类

def _cd_left(st: Mapping, skill: str, now: float) -> int:
    try:
        last = float((st.get("cd") or {}).get(skill, 0) or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0:            # 从未用过（last=0）
        return 0
    cfg = SKILLS.get(skill) or {}
    span = float(cfg.get("cd") or 0) * 60
    return max(0, int(last + span - now))


def _mark_cd(doc: Any, st: dict, skill: str, now: float) -> None:
    cds = dict(st.get("cd") or {})
    cds[skill] = float(now)
    st["cd"] = cds
    save(doc, st)


def _check(doc: Any, skill: str, want: str, now: float) -> tuple[dict | None, str]:
    name = str(skill or "").strip()
    cfg = SKILLS.get(name)
    if not cfg:
        return None, f"【{name}】不在元神十五法门之列。"
    if not has_skill(doc, name):
        return None, f"你尚未掌握【{name}】（精神宇宙的功法掉落可得）。"
    if str(cfg.get("type")) != want:
        return None, f"【{name}】是{TYPE_LABEL.get(str(cfg.get('type')), '其他')}法门，请用对应指令。"
    st = ensure(doc)
    left = _cd_left(st, name, now)
    if left > 0:
        return None, f"【{name}】尚在冷却，还需 {left // 60} 分 {left % 60} 秒。"
    return cfg, ""


def cultivate(doc: Any, skill: str, now: float | None = None) -> tuple[bool, str]:
    """以X修炼元神：恢复 max × ratio。"""
    now = time.time() if now is None else float(now)
    cfg, err = _check(doc, skill, "恢复", now)
    if not cfg:
        return False, err
    cap = max_of(doc)
    if cap <= 0:
        return False, "元神上限为 0，请先 #凝练元神。"
    add = int(math.ceil(cap * float(cfg["ratio"])))
    st = ensure(doc)
    before = int(st.get("cur", 0) or 0)
    st["cur"] = min(cap, before + add)
    _mark_cd(doc, st, str(skill).strip(), now)
    real = int(st["cur"]) - before
    return True, (f"你运转【{skill}】，紫府中元神之光渐盛。\n"
                  f"元神恢复 {real:,}（当前 {st['cur']:,}/{cap:,}）。")


def refine(doc: Any, skill: str, now: float | None = None) -> tuple[bool, str]:
    """以X淬炼元神：消耗 max × ratio，上限 + max × boost。"""
    now = time.time() if now is None else float(now)
    cfg, err = _check(doc, skill, "淬炼", now)
    if not cfg:
        return False, err
    st = ensure(doc)
    cap = int(st.get("max", 0) or 0)
    if cap <= 0:
        return False, "元神上限为 0，请先 #凝练元神。"
    cost = int(math.ceil(cap * float(cfg["ratio"])))
    if int(st.get("cur", 0) or 0) < cost:
        return False, f"淬炼需消耗 {cost:,} 元神（当前 {int(st.get('cur', 0)):,}）。"
    boost = int(math.ceil(cap * float(cfg.get("boost") or 0)))
    st["cur"] = int(st["cur"]) - cost
    st["max"] = cap + boost
    _mark_cd(doc, st, str(skill).strip(), now)
    return True, (f"你以【{skill}】淬炼元神，元神之火在紫府中熊熊燃烧——\n"
                  f"消耗元神：{cost:,}\n元神上限：+{boost:,}（现 {st['max']:,}）")


def burst(doc: Any, skill: str, now: float | None = None) -> tuple[bool, str]:
    """以X元神爆发：5 分钟内战斗增伤。"""
    now = time.time() if now is None else float(now)
    cfg, err = _check(doc, skill, "爆发", now)
    if not cfg:
        return False, err
    st = ensure(doc)
    cap = int(st.get("max", 0) or 0)
    if cap <= 0:
        return False, "元神上限为 0，请先 #凝练元神。"
    cost = int(math.ceil(cap * float(cfg.get("cost") or 0)))
    if int(st.get("cur", 0) or 0) < cost:
        return False, f"爆发需消耗 {cost:,} 元神（当前 {int(st.get('cur', 0)):,}）。"
    st["cur"] = int(st["cur"]) - cost
    st["buff"] = {"skill": str(skill).strip(), "mult": float(cfg.get("dmg_boost") or 0),
                  "end": now + BURST_SECONDS}
    _mark_cd(doc, st, str(skill).strip(), now)
    return True, (f"【{skill}·元神爆发！】你燃烧元神，精神之火冲天而起——\n"
                  f"消耗元神：{cost:,}｜伤害加成：+{float(cfg['dmg_boost']):.0%}｜持续 5 分钟\n"
                  f"「一念花开，君临天下！」")


def guard(doc: Any, skill: str, now: float | None = None) -> tuple[bool, str]:
    """以X元神护体：30 分钟内战斗减伤。"""
    now = time.time() if now is None else float(now)
    cfg, err = _check(doc, skill, "防御", now)
    if not cfg:
        return False, err
    st = ensure(doc)
    cap = int(st.get("max", 0) or 0)
    if cap <= 0:
        return False, "元神上限为 0，请先 #凝练元神。"
    cost = int(math.ceil(cap * float(cfg.get("cost") or 0)))
    if int(st.get("cur", 0) or 0) < cost:
        return False, f"护体需消耗 {cost:,} 元神（当前 {int(st.get('cur', 0)):,}）。"
    st["cur"] = int(st["cur"]) - cost
    st["shield"] = {"skill": str(skill).strip(), "rate": float(cfg.get("block") or 0),
                    "end": now + SHIELD_SECONDS}
    _mark_cd(doc, st, str(skill).strip(), now)
    return True, (f"【{skill}·元神护体！】无形的精神护罩笼罩周身——\n"
                  f"消耗元神：{cost:,}｜战斗减伤：-{float(cfg['block']) * 0.5:.0%}｜持续 30 分钟\n"
                  f"「万法不侵，诸邪避退！」")


def active_burst(doc: Any, now: float | None = None) -> tuple[float, str]:
    """当前生效的爆发增伤（战斗注入用）。"""
    now = time.time() if now is None else float(now)
    st = ensure(doc)
    buff = st.get("buff")
    if not isinstance(buff, Mapping):
        return 0.0, ""
    if float(buff.get("end") or 0) <= now:
        return 0.0, ""
    return max(0.0, float(buff.get("mult") or 0)), str(buff.get("skill") or "")


def active_shield(doc: Any, now: float | None = None) -> tuple[float, str]:
    """当前生效的护体减伤率（已折算为战斗实际减伤）。"""
    now = time.time() if now is None else float(now)
    st = ensure(doc)
    shield = st.get("shield")
    if not isinstance(shield, Mapping):
        return 0.0, ""
    if float(shield.get("end") or 0) <= now:
        return 0.0, ""
    return min(0.6, max(0.0, float(shield.get("rate") or 0) * 0.5)), str(shield.get("skill") or "")


# ---------------------------------------------------------------- 神游：辅助

def _shenyou_bonus(doc: Any) -> dict:
    event = depth = 0.0
    for name in known_skills(doc):
        cfg = SKILLS.get(name) or {}
        if str(cfg.get("type")) != "神游":
            continue
        event += float(cfg.get("event_bonus") or 0)
        depth += float(cfg.get("depth_bonus") or 0)
    return {"event": event, "depth": int(depth)}


def node_limit(doc: Any) -> int:
    return max(1, 2 - int(_shenyou_bonus(doc)["depth"]))


def journey(doc: Any) -> dict | None:
    st = ensure(doc)
    raw = st.get("shenyou")
    return dict(raw) if isinstance(raw, Mapping) else None


def _save_journey(doc: Any, state: Mapping | None) -> None:
    st = ensure(doc)
    st["shenyou"] = dict(state) if isinstance(state, Mapping) else None
    save(doc, st)


def guardian_name(pid: Any, layer: int, legacy: bool = False) -> str:
    if legacy:
        return "传承强者残魂"
    names = GUARDIANS.get(int(pid or 0)) or ("无名守关余念",)
    idx = min(max(0, int(layer) - 1), len(names) - 1)
    return names[idx]


def _pick_drop(drops: Sequence[Mapping], rng: random.Random) -> Mapping | None:
    pool = [d for d in (drops or []) if d.get("name") and int(d.get("w") or 0) > 0]
    total = sum(int(d["w"]) for d in pool)
    if not total:
        return None
    cursor = rng.random() * total
    for d in pool:
        cursor -= int(d["w"])
        if cursor < 0:
            return d
    return pool[-1]


def _layer_of(place: Mapping, layer: int) -> dict:
    layers = place.get("layers") or []
    idx = min(max(0, int(layer) - 1), max(0, len(layers) - 1))
    return dict(layers[idx]) if layers else {}


def _choice(number: int, layer: Mapping) -> dict | None:
    row = next((c for c in CHOICES if c[0] == int(number)), None)
    if not row:
        return None
    base = max(1, int(layer.get("cost") or 100000))
    return {"number": row[0], "id": row[1], "label": row[2],
            "cost": int(math.ceil(base * row[3]))}


# ---------------------------------------------------------------- 神游：面板

def panel(doc: Any, now: float | None = None) -> str:
    """#精神宇宙：位面列表。"""
    now = time.time() if now is None else float(now)
    cur, cap = heart_of(doc, now)
    lv = level_of(doc)
    lines = ["═══ 精神宇宙·神识云游 ═══",
             f"元神：【{level_name(doc)}】｜{cur_of(doc):,}/{max_of(doc):,}",
             f"心神：{cur}/{cap}｜每次神游消耗 {heart_cost(doc, HEART_ENTRY)} 点（每 {HEART_RECOVER_SECONDS // 60} 分钟恢复 1 点）",
             "每层完成有限观想后，需以元神战胜守关残魂；主动 #归位 保留全部收获。",
             "─────────────────────"]
    for place in PLACES:
        req = int(place.get("require") or 0)
        ok = lv is not None and int(lv) >= req
        best = "、".join(place.get("best") or []) or "未知"
        lines.append(f"{'✅' if ok else '🔒'}【{place['name']}】（{int(place.get('depth') or 0)} 层）")
        lines.append(f"   要求：{LEVEL_NAMES[min(req, len(LEVEL_NAMES) - 1)]}"
                     f"｜入场：{heart_cost(doc, HEART_ENTRY)} 心神 + {int(place.get('entry') or 0):,} 元神")
        lines.append(f"   珍品：{best}")
        lines.append(f"   {'#神游 ' + place['name'] if ok else '元神等级不足'}")
        lines.append("─────────────────────")
    return "\n".join(lines)


def status_text(doc: Any, now: float | None = None) -> str:
    """#神识状态：云游进度或空闲提示。"""
    now = time.time() if now is None else float(now)
    cur, cap = heart_of(doc, now)
    state = journey(doc)
    head = [f"心神：{cur}/{cap}（每 {HEART_RECOVER_SECONDS // 60} 分钟 +1）"]
    if not state:
        return "\n".join(["你的神识并未云游"] + head + ["使用 #精神宇宙 查看可进入的位面。"])
    place = find_by_id(state.get("place_id")) or {}
    layer_no = int(state.get("layer") or 1)
    limit = node_limit(doc)
    lines = ["【神识云游状态】"] + head + [
        f"位面：{state.get('place_name')}（共 {int(place.get('depth') or 0)} 层）",
        f"当前：第 {layer_no} 层「{state.get('layer_name')}」",
        f"本层精神节点：{int(state.get('actions') or 0)}/{limit}",
        f"本层悟痕：{int(state.get('insight') or 0)}",
        f"完成抉择：{int(state.get('guanxiang') or 0)} 次",
        f"累计消耗元神：{int(state.get('consumed') or 0):,}",
        f"临时收获：{len(state.get('findings') or [])} 件",
        f"强制归位保留率：{_retention(layer_no) * 100:.0f}%",
    ]
    if state.get("pending"):
        lines.append(f"待处理异象：{state['pending'].get('type')}（用 #抉择 1/2/3）")
    lines += ["", "可用命令：#观想｜#深入｜#归位"]
    return "\n".join(lines)


def _retention(layer: int) -> float:
    if layer <= 0:
        return 0.0
    idx = min(int(layer), len(FORCED_RETENTION) - 1)
    return FORCED_RETENTION[idx]


# ---------------------------------------------------------------- 神游：流程

def enter(doc: Any, name: str, now: float | None = None) -> tuple[bool, str]:
    """#神游 位面：扣心神与元神，进入第 1 层。"""
    now = time.time() if now is None else float(now)
    place = find_place(name)
    if not place:
        return False, f"未找到精神位面【{name}】。发 #精神宇宙 查看可进入的位面。"
    lv = level_of(doc)
    req = int(place.get("require") or 0)
    if lv is None:
        return False, "你尚未凝练元神（#凝练元神）。"
    if int(lv) < req:
        return False, (f"元神等级不足：需【{LEVEL_NAMES[min(req, len(LEVEL_NAMES) - 1)]}】"
                       f"（当前【{level_name(doc)}】）。")
    if journey(doc):
        return False, "你的神识正在别处云游，先 #归位 再入其他位面。"
    entry = int(place.get("entry") or 0)
    if cur_of(doc) < entry:
        return False, f"神识云游需要 {entry:,} 元神（当前 {cur_of(doc):,}）。"
    entry_cost = heart_cost(doc, HEART_ENTRY)
    ok, left, cap = consume_heart(doc, entry_cost, now)
    if not ok:
        return False, (f"进入精神宇宙需 {entry_cost} 点心神，你当前 {left}/{cap}，"
                       f"约 {heart_minutes_left(doc, now)} 分钟后恢复 1 点。")
    add_cur(doc, -entry)
    first = _layer_of(place, 1)
    _save_journey(doc, {
        "place_id": int(place.get("id") or 0), "place_name": place["name"],
        "layer": 1, "layer_name": first.get("name", "第1层"),
        "consumed": entry, "guanxiang": 0, "max_layer": 1,
        "insight": 0, "actions": 0, "pending": None, "findings": [],
        "start": now,
    })
    return True, (f"{doc.name or doc.uid}盘膝入定，一缕神识越过精神宇宙的边界。\n"
                  f"进入「{place['name']}」·第 1 层「{first.get('name', '')}」\n"
                  f"{place.get('desc') or ''}\n"
                  f"入场消耗：{entry_cost} 心神、{entry:,} 元神（余 {cur_of(doc):,}）\n"
                  f"发送 #观想 寻找当前层的机缘")


def observe(doc: Any, now: float | None = None, rng: random.Random | None = None) -> tuple[bool, str]:
    """#观想：生成当前层的三选一。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    state = journey(doc)
    if not state:
        return False, "你的神识并未云游（#精神宇宙 查看位面）。"
    place = find_by_id(state.get("place_id"))
    if not place:
        _save_journey(doc, None)
        return False, "云游数据异常，已为你强制归位。"
    if state.get("pending"):
        return False, "眼前的异象尚未消散，请先 #抉择 1/2/3。"
    layer = _layer_of(place, int(state.get("layer") or 1))
    limit = node_limit(doc)
    if int(state.get("actions") or 0) >= limit:
        return False, f"本层 {limit} 处精神节点均已探明，守关意识已经显化。\n使用 #深入 发起元神战，或 #归位 保全收获。"
    choices = [_choice(n, layer) for n in (1, 2, 3)]
    if cur_of(doc) < int(choices[0]["cost"]):
        return False, f"你至少需要 {int(choices[0]['cost']):,} 元神才能继续观想（当前 {cur_of(doc):,}）。\n可 #归位 结算已得收益。"
    events = layer.get("events") or ["精神潮汐"]
    etype = str(rng.choice(list(events)))
    state["pending"] = {"type": etype, "layer": int(state.get("layer") or 1)}
    _save_journey(doc, state)
    bonus = _shenyou_bonus(doc)
    chance = min(0.9, 0.65 + float(bonus["event"]))
    lines = [f"【{place['name']}·{state.get('layer_name')}】",
             EVENT_INTROS.get(etype, "前方精神潮汐翻涌，一场未知机缘正在成形。"), "",
             f"精神节点：{int(state.get('actions') or 0) + 1}/{limit}",
             f"1. 镇守心神｜{int(choices[0]['cost']):,} 元神｜稳获道痕",
             f"2. 搜寻机缘｜{int(choices[1]['cost']):,} 元神｜寻宝率 {chance:.0%}",
             f"3. 参悟道痕｜{int(choices[2]['cost']):,} 元神｜可能触发特殊传承",
             "",
             "使用 #抉择 1 / #抉择 2 / #抉择 3"]
    return True, "\n".join(lines)


def choose(doc: Any, number: int, now: float | None = None,
           rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#抉择 N：结算本次观想。返回 (成功, 文案, 待入包物品)。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    state = journey(doc)
    if not state:
        return False, "你的神识并未云游。", {}
    place = find_by_id(state.get("place_id"))
    if not place:
        _save_journey(doc, None)
        return False, "云游数据异常，已为你强制归位。", {}
    pending = state.get("pending") if isinstance(state.get("pending"), Mapping) else None
    if not pending:
        return False, "当前没有等待处理的异象，请先 #观想。", {}
    if int(pending.get("layer") or 0) != int(state.get("layer") or 0):
        state["pending"] = None
        _save_journey(doc, state)
        return False, "旧有异象已经消散，请重新 #观想。", {}
    layer = _layer_of(place, int(state.get("layer") or 1))
    action = _choice(int(number), layer)
    if not action:
        return False, "无效抉择（只有 1/2/3）。", {}
    if cur_of(doc) < int(action["cost"]):
        return False, (f"此抉择需要 {int(action['cost']):,} 元神（当前 {cur_of(doc):,}）。\n"
                       f"可改选其他抉择，或 #归位。"), {}
    etype = str(pending.get("type") or "精神潮汐")
    base = max(1, int(layer.get("cost") or 100000))
    bonus = _shenyou_bonus(doc)

    # ---- 结算（原版 model/spiritUniverse.js:resolveSpiritChoice）----
    insight = 0
    delta = 0
    finding: dict | None = None
    outcome = action["id"]
    if action["id"] == "steady":
        outcome = "steady_success"
        insight = 1
        delta = int(math.ceil(base * 0.1))
    elif action["id"] == "treasure":
        chance = min(0.9, max(0.65, 0.65 + float(bonus["event"])))
        roll = rng.random()
        if roll < chance:
            drop = _pick_drop(layer.get("drops") or [], rng)
            outcome = "treasure_found" if drop else "treasure_empty"
            if drop:
                finding = {"kind": "skill" if str(drop.get("class")) == "功法" else "item",
                           "name": drop["name"], "class": drop.get("class"),
                           "type": drop.get("type")}
                insight = 1
        else:
            outcome = "treasure_hazard" if roll > 0.92 else "treasure_empty"
            if outcome == "treasure_hazard":
                delta = -int(math.ceil(base * 0.25))
    else:
        roll = max(0.0, rng.random() - float(bonus["event"]) * 0.5)
        if roll < 0.42:
            outcome = "insight_recover"
            insight = 2
            delta = int(math.ceil(base * 0.55))
        elif roll < 0.72:
            outcome = "insight_expand"
            insight = 1
            finding = {"kind": "max", "name": "元神上限",
                       "amount": int(math.ceil(base * 0.25))}
        elif roll < 0.9:
            outcome = "insight_trace"
            insight = 2
        else:
            outcome = "insight_backlash"
            delta = -int(math.ceil(base * 0.25))

    # 抉择 3 的特殊传承：保底 9 次未出必触发（原版 shouldTriggerSpiritLegacy）
    legacy_log: list[str] = []
    if int(number) == 3 and cur_of(doc) - int(action["cost"]) > 0:
        skill_drops = [d for d in (layer.get("drops") or []) if str(d.get("class")) == "功法"]
        pity = int(ensure(doc).get("pity", 0) or 0)
        depth = int(place.get("depth") or 1)
        chance = min(0.15, 0.03 + (int(state.get("layer") or 1) - 1) * 0.02
                     + (0.03 if int(state.get("layer") or 1) >= depth else 0))
        if skill_drops and (pity >= 9 or rng.random() < chance):
            drop = _pick_drop(skill_drops, rng)
            battle = guardian_battle(doc, place, layer, legacy=True, rng=rng)
            legacy_log = list(battle["log"])
            st = ensure(doc)
            st["pity"] = 0
            save(doc, st)
            if battle["won"] and drop:
                finding = {"kind": "skill", "name": drop["name"],
                           "class": drop.get("class"), "type": drop.get("type")}
                outcome = "insight_legacy"
                legacy_log.append(f"残魂认可了你的元神，传承「{drop['name']}」化作烙印。")
            else:
                finding = None
                legacy_log.append("你未能承受传承意志，元神投影被逐出此界。")
        else:
            st = ensure(doc)
            st["pity"] = pity + 1
            save(doc, st)

    add_cur(doc, delta - int(action["cost"]))
    state["consumed"] = int(state.get("consumed") or 0) + int(action["cost"])
    state["guanxiang"] = int(state.get("guanxiang") or 0) + 1
    state["insight"] = int(state.get("insight") or 0) + insight
    state["actions"] = int(state.get("actions") or 0) + 1
    state["pending"] = None
    if finding:
        state.setdefault("findings", []).append(finding)
    _save_journey(doc, state)

    label = {"steady_success": f"你不与「{etype}」正面争锋，守住灵台并记下一缕道痕。",
             "treasure_found": f"你循着气机深入其中，将「{(finding or {}).get('name')}」收入神识携带之物。",
             "treasure_empty": "你搜寻许久，只捕捉到几缕迅速消散的精神微光。",
             "treasure_hazard": "你触动了隐藏禁制，机缘化为泡影，神识也被撕裂一角。",
             "insight_recover": "你看破表象，从精神潮汐中炼出纯净念力，道痕接连浮现。",
             "insight_expand": f"你触及元神蜕变之秘，归位后可令元神上限提升 {(finding or {}).get('amount', 0):,}。",
             "insight_trace": "完整传承虽未显现，你仍从残痕中连续悟出两道道痕。",
             "insight_backlash": "你强行追索大道源头，却被混乱意志反噬，神识剧烈震荡。",
             "insight_legacy": f"一道强者残魂从道痕中苏醒，你胜之，承接「{(finding or {}).get('name')}」。"}
    lines = [f"【{etype}·{action['label']}】", label.get(outcome, "这一缕精神异象缓缓消散。"),
             f"消耗元神：{int(action['cost']):,}"]
    if delta:
        lines.append(f"额外元神变化：{'+' if delta > 0 else ''}{delta:,}")
    if legacy_log:
        lines += ["", "【特殊传承】"] + legacy_log
    limit = node_limit(doc)
    lines += [f"本层精神节点：{state['actions']}/{limit}",
              f"本层悟痕：{state['insight']}",
              f"临时收获：{len(state.get('findings') or [])} 件"]
    if int(state["actions"]) >= limit:
        lines.append("本层节点已经探明，使用 #深入 挑战守关意识。")
    items: dict[str, int] = {}
    if cur_of(doc) <= 0:
        _ok, text, extra_items = settle(doc, forced=True, now=now, rng=rng)
        lines += ["", text]
        items.update(extra_items)
    return True, "\n".join(lines), items


def guardian_battle(doc: Any, place: Mapping, layer: Mapping, legacy: bool = False,
                    rng: random.Random | None = None) -> dict:
    """守关元神战（原版 resolveSpiritGuardianBattle 直译，8 回合）。"""
    del rng
    cur = max(1, cur_of(doc))
    cap = max(cur, max_of(doc))
    base = max(1, int(layer.get("cost") or 100000))
    layer_no = max(1, int(layer.get("layer") or 1))
    tier = max(0, int(place.get("require") or 0))
    diff = 1 + tier * 0.04 + (layer_no - 1) * 0.10 + (0.20 if legacy else 0)
    atk_skill, atk_bonus = "", 0.0
    def_skill, def_bonus = "", 0.0
    for name in known_skills(doc):
        cfg = SKILLS.get(name) or {}
        if str(cfg.get("type")) == "爆发" and float(cfg.get("dmg_boost") or 0) > atk_bonus:
            atk_skill, atk_bonus = name, float(cfg["dmg_boost"])
        if str(cfg.get("type")) == "防御" and float(cfg.get("block") or 0) > def_bonus:
            def_skill, def_bonus = name, float(cfg["block"])
    reduction = min(0.75, def_bonus)

    name = guardian_name(place.get("id"), layer_no, legacy)
    hp = int(max(base * 3, cap * 0.35) * diff)
    atk = int(max(base * 0.18, cap * 0.045) * diff)
    defense = int(base * 0.30 * diff)
    base_attack = max(cur, cap * 0.08, base * 0.15)
    mine = cur
    log: list[str] = []
    for rnd in range(1, 9):
        if hp <= 0 or mine <= 0:
            break
        dealt = max(1, int(base_attack * (1 + atk_bonus) - defense * 0.20))
        if atk_skill == "劫运神拳" and mine <= cap * 0.5:
            dealt = int(dealt * 1.15)
        hp = max(0, hp - dealt)
        log.append(f"第{rnd}回合：你以{atk_skill or '神识念刃'}斩去{name}{dealt}点魂力。")
        if hp <= 0:
            break
        taken = max(1, int(atk * (1 - reduction)))
        mine = max(0, mine - taken)
        if def_skill == "九劫雷符":
            hp = max(0, hp - int(taken * 0.15))
        log.append(f"{name}反噬识海，你损失{taken}点元神。")
    add_cur(doc, mine - cur_of(doc))
    return {"won": hp <= 0, "name": name, "log": log, "lost": cur - mine,
            "remaining": mine, "guardian_hp": hp}


def deep(doc: Any, now: float | None = None,
         rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#深入：守关战；通过则进下一层或首通结算。返回 (成功, 文案, 待入包物品)。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    state = journey(doc)
    if not state:
        return False, "你的神识并未云游（#精神宇宙 查看位面）。", {}
    place = find_by_id(state.get("place_id"))
    if not place:
        _save_journey(doc, None)
        return False, "云游数据异常，已为你强制归位。", {}
    if state.get("pending"):
        return False, "眼前异象尚未处理，请先完成 #抉择。", {}
    limit = node_limit(doc)
    if int(state.get("actions") or 0) < limit:
        return False, (f"本层还有精神节点尚未探明：需观想 {limit} 次"
                       f"（当前 {int(state.get('actions') or 0)} 次）。"), {}
    layer_no = int(state.get("layer") or 1)
    depth = int(place.get("depth") or 1)
    if layer_no < depth:
        need = int(place.get("require") or 0) + layer_no
        lv = level_of(doc) or 0
        if lv < need:
            return False, (f"守关意识感知到你的元神尚未圆满：下一层需"
                           f"【{LEVEL_NAMES[min(need, len(LEVEL_NAMES) - 1)]}】"
                           f"（当前【{level_name(doc)}】）。"), {}
    layer = _layer_of(place, layer_no)
    res = guardian_battle(doc, place, layer, rng=rng)
    lines = [f"【{place['name']}·守关元神战】",
             f"{res['name']}挡住了通往下一层的精神通道。"] + res["log"] + \
            [f"元神损耗：{res['lost']:,}"]
    if not res["won"]:
        lines.append(f"{res['name']}仍余 {res['guardian_hp']:,} 点魂力，你的投影被震出精神宇宙。")
        _ok, tail, items = settle(doc, forced=True, now=now, rng=rng)
        return True, "\n".join(lines + ["", tail]), items
    lines.append(f"{res['name']}消散，精神壁垒随之洞开。")
    if layer_no >= depth:
        lines.append(f"你已贯通「{place['name']}」，神识沿完整道标归位。")
        st = ensure(doc)
        clears = [int(x) for x in (st.get("first_clear") or [])]
        if int(place["id"]) not in clears:
            clears.append(int(place["id"]))
            st["first_clear"] = clears
            save(doc, st)
            gain = raise_heart_limit(doc, 2)
            lines.append(f"首次贯通「{place['name']}」，心神上限永久 +{gain}。")
            _ok, tail, items = settle(doc, forced=False, now=now, rng=rng, extra=[
                {"kind": "item", "name": "虚天神钥", "class": "道具", "type": "宝物"}])
            return True, "\n".join(lines + ["守关残念中浮现一枚【虚天神钥】。", "", tail]), items
        _ok, tail, items = settle(doc, forced=False, now=now, rng=rng)
        return True, "\n".join(lines + ["", tail]), items
    nxt = _layer_of(place, layer_no + 1)
    state["layer"] = layer_no + 1
    state["layer_name"] = nxt.get("name", f"第{layer_no + 1}层")
    state["insight"] = 0
    state["actions"] = 0
    state["max_layer"] = max(int(state.get("max_layer") or 1), layer_no + 1)
    _save_journey(doc, state)
    lines.append(f"进入第 {layer_no + 1} 层「{state['layer_name']}」")
    lines.append(f"本层可能遭遇：{'、'.join(nxt.get('events') or []) or '未知异象'}")
    lines.append("发送 #观想 继续探索，或 #归位 保全收获。")
    return True, "\n".join(lines), {}


def _merge_findings(doc: Any, findings: Sequence[Mapping]) -> tuple[list[str], dict[str, int]]:
    """把临时收获并进玩家：功法→ext.gongfa，上限→max，物品→背包清单。"""
    lines: list[str] = []
    items: dict[str, int] = {}
    gained_max = 0
    gained_cur = 0
    for f in findings:
        kind = str(f.get("kind") or "item")
        name = str(f.get("name") or "")
        if kind == "skill":
            owned = learned(doc)
            if name in owned:
                gained_cur += 100_000
                lines.append(f"重复传承「{name}」化为 100,000 元神")
            else:
                doc.ext["gongfa"] = owned + [name]
                lines.append(f"领悟「{name}」")
        elif kind == "max":
            amount = max(0, int(f.get("amount") or 0))
            gained_max += amount
            lines.append(f"元神上限 +{amount:,}")
        else:
            items[name] = items.get(name, 0) + 1
            lines.append(f"{name} ×1")
    if gained_max:
        add_max(doc, gained_max)
    if gained_cur:
        add_cur(doc, gained_cur)
    return lines, items


def settle(doc: Any, forced: bool = False, now: float | None = None,
           rng: random.Random | None = None, extra: Sequence[Mapping] | None = None
           ) -> tuple[bool, str, dict[str, int]]:
    """#归位 / 强制归位：按层保留收获并结算。返回 (成功, 文案, 待入包物品)。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    state = journey(doc)
    if not state:
        return False, "你的神识并未云游。", {}
    layer_no = int(state.get("layer") or 1)
    rate = _retention(layer_no) if forced else 1.0
    findings = list(state.get("findings") or [])
    if extra:
        findings += [dict(x) for x in extra]
    kept = [f for f in findings if rate >= 1 or rng.random() < rate]
    lost = len(findings) - len(kept)
    reward_lines, items = _merge_findings(doc, kept)
    _save_journey(doc, None)

    lines = ["元神投影受创，你被精神宇宙强行排斥！" if forced
             else "你主动收束念头，神识沿来路归位。",
             f"【{state.get('place_name')}·神游结算】",
             f"最深到达：第 {int(state.get('max_layer') or 1)} 层",
             f"完成抉择：{int(state.get('guanxiang') or 0)} 次",
             f"累计消耗：{int(state.get('consumed') or 0):,} 元神",
             f"战利品保留：{rate * 100:.0f}%"]
    if reward_lines:
        lines.append("归位所得：")
        lines += [f"  · {x}" for x in reward_lines]
    else:
        lines.append("归位所得：无")
    if lost:
        lines.append(f"强制归位时遗失：{lost} 件临时收获")
    lines.append("神识没入眉心，你缓缓睁开双眼。")
    return True, "\n".join(lines), items


# ---------------------------------------------------------------- 内景地修炼

INNER_COST_BASE = 150_000          # 单次 15 万 ×（元神等级+1）
INNER_GAIN_RATE = 2.0              # 成功时修为/血气/元神各 +2×消耗（期望约 1.2 倍回本）
INNER_BATCH_MAX = 50


def inner_cost(doc: Any) -> int:
    lv = level_of(doc)
    base = INNER_COST_BASE * ((0 if lv is None else int(lv)) + 1)
    try:
        from .mingge import effects_of
        multiplier = float(effects_of(doc).get("内景地消耗倍率", 1) or 1)
    except (TypeError, ValueError):
        multiplier = 1.0
    return max(1, int(base * min(3.0, max(0.05, multiplier))))


def inner_chance(doc: Any) -> float:
    lv = level_of(doc)
    return max(0.05, min(0.95, 0.10 + 0.10 * (0 if lv is None else int(lv))))


def inner_cultivate(doc: Any, times: int = 1, now: float | None = None,
                    rng: random.Random | None = None) -> tuple[bool, str]:
    """#内景地修炼 [次数]：消耗元神赌一次顿悟，成功得修为/血气/元神。"""
    from . import inner_world

    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    if inner_world.state_of(doc) is None:
        return False, "尚未开辟内景地（#开启内景地）。"
    if level_of(doc) is None:
        return False, "你连元神都未凝练，谈何内景地？（#凝练元神）"
    times = max(1, min(INNER_BATCH_MAX, int(times or 1)))
    cost = inner_cost(doc)
    chance = inner_chance(doc)
    lv = level_of(doc)
    base_cost = INNER_COST_BASE * ((0 if lv is None else int(lv)) + 1)
    try:
        from .mingge import effects_of
        fate = effects_of(doc)
        gain_mult = max(0.0, 1.0 + float(fate.get("内景地收益", 0) or 0)
                        + float(fate.get("元神修炼加成", 0) or 0))
    except (TypeError, ValueError):
        gain_mult = 1.0
    gain = int(base_cost * INNER_GAIN_RATE * gain_mult)
    win = fail = spend = 0
    got = 0
    notes: list[str] = []
    for i in range(times):
        if cur_of(doc) < cost:
            notes.append(f"【中止】第 {i + 1} 次：元神不足（需 {cost:,}，仅剩 {cur_of(doc):,}）")
            break
        add_cur(doc, -cost)
        spend += cost
        if rng.random() < chance:
            win += 1
            doc.exp += gain
            doc.ext["xueqi"] = float(doc.ext.get("xueqi", 0) or 0) + gain
            add_cur(doc, gain)
            got += gain
            if len(notes) < 6:
                notes.append(f"第 {i + 1} 次：开启成功，修为/血气/元神 +{gain:,}")
        else:
            fail += 1
            if len(notes) < 6:
                notes.append(f"第 {i + 1} 次：玄关紧闭，损失元神 {cost:,}")
    lines = [f"--- 内景地修炼 ×{win + fail} ---"]
    lines += notes
    lines.append(f"成功 {win} 次｜失败 {fail} 次｜投入元神 {spend:,}｜"
                 f"修为/血气/元神各 +{got:,}")
    if win:
        try:
            from . import zhengdao as _dz
            heal = round(0.1 * win, 3)
            left = _dz.heal(doc, heal, "内景地修炼")
            lines.append(f"【内景地洗道】道伤 -{heal:g}（现 {left:.1f}）")
        except Exception:
            pass
    lines.append(f"（单次消耗 {cost:,}｜成功率 {chance:.0%}｜#内景地修炼 可继续）")
    return True, "\n".join(lines)
