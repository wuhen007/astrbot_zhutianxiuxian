"""诸天遗珍（W8-A1）：五品质 / 六套装 / 十二副词条 / 三部位双铭刻位 / 共鸣。

原版：`apps/RelicSystem.js` 329 行 + `model/relicSystem.js` 408 行。

移植口径：
- 完整保留：品质（凡耀/灵玄/至圣/大道/超脱，1~5 条副词条）、六套装、十二副词条、
  武器/护具/法宝各两个铭刻位、同套三件共鸣、碎片分解与定向合成、界纹拓印拓展第二槽。
- **战斗字段适配**（本移植引擎只有 atk/def/hp/bao + dmg_dealt_mult/dmg_taken_mult/
  lifesteal/shield，没有独立的近战/神通/速度/治疗/闪避通道）：
  | 原版字段 | 本移植落点 | 权重 |
  |---|---|---|
  | 暴击率 | `bao` | 1.0 |
  | 暴击伤害 | `bao` | 0.5（引擎 crit 倍率与 bao 同源，直接相加会双重加成） |
  | 近战/神通/全伤害加成 | `dmg_dealt_mult` | 1.0 |
  | 穿透 | `dmg_dealt_mult` | 0.5 |
  | 近战/神通/全类型减免 | `dmg_taken_mult` | 1.0 |
  | 闪避率 / 速度加成 | `dmg_taken_mult` | 0.5 / 0.25 |
  | 治疗效果加成 | `lifesteal` | 0.5 |
  | 吸血率 | `lifesteal` | 1.0 |
  | 开战护盾率 | `shield`（build_fighter 注入 hp_max×比例） | 1.0 |
- 上限按其原版 `RELIC_EFFECT_CAPS` 折算：bao ≤0.35、增伤 ≤0.55、减伤 ≤0.50、
  汲取 ≤0.15、护盾 ≤0.30。

shortcut：遗珍产出的「位面鱼王/域外灾厄」两条掉落链只接了鱼王宝箱（W8-A2）；
域外灾厄掉遗珍、待领奖幂等凭证、`已分解奖励` 去重表未移植（本移植无重试发奖链路）。
"""

from __future__ import annotations

import copy
import random
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

PARTS: tuple[str, ...] = ("武器", "护具", "法宝")
EXPANSION_ITEM = "界纹拓印"
BAG_MAX = 200
PENDING_TTL = 120          # 分解预览有效期（秒），原版 120 秒

# 品质 → (副词条条数, 分解得碎片, 合成耗碎片)
QUALITIES: dict[str, tuple[int, int, int]] = {
    "凡耀": (1, 1, 10),
    "灵玄": (2, 3, 30),
    "至圣": (3, 10, 100),
    "大道": (4, 30, 300),
    "超脱": (5, 100, 1000),
}

# 副词条 → (原版字段, 下限, 上限)
AFFIXES: dict[str, tuple[str, float, float]] = {
    "迅行": ("速度加成", 0.02, 0.04),
    "护道": ("开战护盾率", 0.04, 0.08),
    "武极": ("近战伤害加成", 0.03, 0.06),
    "万法": ("神通伤害加成", 0.03, 0.06),
    "金身": ("近战伤害减免", 0.02, 0.05),
    "破法": ("神通伤害减免", 0.02, 0.05),
    "洞虚": ("暴击率", 0.01, 0.03),
    "绝杀": ("暴击伤害", 0.04, 0.08),
    "破界": ("穿透", 0.01, 0.03),
    "逍遥": ("闪避率", 0.01, 0.02),
    "生生": ("治疗效果加成", 0.03, 0.06),
    "饮血": ("吸血率", 0.01, 0.03),
}

# 套装 → (描述, {字段: 值})
SETS: dict[str, tuple[str, dict[str, float]]] = {
    "荒古战血": ("战血沸腾，专精近身征伐。", {"近战伤害加成": 0.12, "暴击率": 0.03}),
    "万法天章": ("万法归流，强化神通与破界之力。", {"神通伤害加成": 0.12, "穿透": 0.03}),
    "玄黄不灭": ("玄黄护体，开战凝盾并抵御两类伤害。",
                 {"开战护盾率": 0.15, "近战伤害减免": 0.05, "神通伤害减免": 0.05}),
    "虚空行者": ("踏空而行，以极速与闪避争夺先机。", {"速度加成": 0.08, "闪避率": 0.03}),
    "阴阳道图": ("阴阳流转，兼顾近战与神通抗性。", {"近战伤害减免": 0.08, "神通伤害减免": 0.08}),
    "诸世归一": ("诸世道韵归于一身，攻守均衡。", {"全伤害类型加成": 0.06, "全类型减免": 0.04}),
}

# 原版上限（仅保留本移植有落点的字段）
CAPS: dict[str, float] = {
    "开战护盾率": 0.30,
    "近战伤害加成": 0.40,
    "神通伤害加成": 0.40,
    "近战伤害减免": 0.35,
    "神通伤害减免": 0.35,
    "暴击率": 0.15,
    "暴击伤害": 0.40,
    "穿透": 0.15,
    "闪避率": 0.15,
    "治疗效果加成": 0.30,
    "吸血率": 0.15,
    "全伤害类型加成": 0.15,
    "全类型减免": 0.15,
    "速度加成": 0.25,
}

# 本移植落点与权重（第三项为攻击类型：非空则只对该类型生效，空则通用）
FIELD_MAP: dict[str, tuple[str, float, str | None]] = {
    "暴击率": ("bao", 1.0, None),
    "暴击伤害": ("bao", 0.5, None),
    "近战伤害加成": ("dealt", 1.0, "近战"),
    "神通伤害加成": ("dealt", 1.0, "神通"),
    "全伤害类型加成": ("dealt", 1.0, None),
    "穿透": ("dealt", 0.5, None),
    "近战伤害减免": ("taken", 1.0, "近战"),
    "神通伤害减免": ("taken", 1.0, "神通"),
    "全类型减免": ("taken", 1.0, None),
    "闪避率": ("taken", 0.5, None),
    "速度加成": ("taken", 0.25, None),
    "治疗效果加成": ("lifesteal", 0.5, None),
    "吸血率": ("lifesteal", 1.0, None),
    "开战护盾率": ("shield", 1.0, None),
}

# 落点上限（按原版caps折算）
CAP_TOTAL: dict[str, float] = {
    "bao": 0.35,
    "dealt": 0.55,
    "taken": 0.50,
    "lifesteal": 0.15,
    "shield": 0.30,
}

# 鱼王宝箱的位面 → 套装
FISH_KING_SETS: dict[str, str] = {
    "凡间": "玄黄不灭",
    "仙界": "万法天章",
    "遮天位面": "荒古战血",
    "下界八域": "阴阳道图",
    "九天十地": "诸世归一",
    "太初星墟": "虚空行者",
}
FISH_KING_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("凡耀", 0.50), ("灵玄", 0.28), ("至圣", 0.15), ("大道", 0.06), ("超脱", 0.01),
)


# ---------------------------------------------------------------- 状态

def default_state() -> dict[str, Any]:
    return {
        "bag": [],
        "fragments": 0,
        "engrave": {p: [None, None] for p in PARTS},
        "expanded": {p: False for p in PARTS},
    }


def _norm_relic(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    quality = str(raw.get("quality") or "")
    set_name = str(raw.get("set") or "")
    if quality not in QUALITIES or set_name not in SETS:
        return None
    affixes = []
    for item in list(raw.get("affixes") or [])[: QUALITIES[quality][0]]:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "")
        if name not in AFFIXES:
            continue
        try:
            value = float(item.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            affixes.append({"name": name, "value": round(value, 4)})
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
        "name": str(raw.get("name") or f"{set_name}遗珍"),
        "quality": quality,
        "set": set_name,
        "affixes": affixes,
        "t": float(raw.get("t") or time.time()),
    }


def normalize(raw: Any) -> dict[str, Any]:
    """容错归一：老档/坏档补齐字段，未拓展的第二铭刻位物品退回背包。"""
    st = default_state()
    if not isinstance(raw, Mapping):
        return st
    try:
        frag = int(raw.get("fragments") or 0)
    except (TypeError, ValueError):
        frag = 0
    st["fragments"] = max(0, frag)
    st["bag"] = [r for r in (_norm_relic(x) for x in list(raw.get("bag") or [])[:BAG_MAX]) if r]
    eng = raw.get("engrave") if isinstance(raw.get("engrave"), Mapping) else {}
    exp = raw.get("expanded") if isinstance(raw.get("expanded"), Mapping) else {}
    for part in PARTS:
        slots = eng.get(part) if isinstance(eng.get(part), Sequence) else []
        slots = list(slots)[:2] + [None, None]
        st["engrave"][part] = [_norm_relic(slots[0]), _norm_relic(slots[1])]
        st["expanded"][part] = bool(exp.get(part))
        if not st["expanded"][part] and st["engrave"][part][1]:
            if len(st["bag"]) < BAG_MAX:
                st["bag"].append(st["engrave"][part][1])
            st["engrave"][part][1] = None
    return st


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    return normalize(ext.get("relics") if isinstance(ext, Mapping) else None)


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["relics"] = copy.deepcopy(dict(st))


# ---------------------------------------------------------------- 生成

def create(quality: str, set_name: str, rng: random.Random) -> dict[str, Any]:
    if quality not in QUALITIES:
        raise ValueError(f"未知遗珍品质：{quality}")
    if set_name not in SETS:
        raise ValueError(f"未知遗珍套装：{set_name}")
    pool = list(AFFIXES)
    affixes = []
    for _ in range(QUALITIES[quality][0]):
        name = pool.pop(rng.randrange(len(pool))) if pool else "洞虚"
        lo, hi = AFFIXES[name][1], AFFIXES[name][2]
        affixes.append({"name": name, "value": round(lo + (hi - lo) * rng.random(), 4)})
    return {
        "id": uuid.uuid4().hex[:8],
        "name": f"{set_name}遗珍",
        "quality": quality,
        "set": set_name,
        "affixes": affixes,
        "t": time.time(),
    }


def roll_fish_king(plane: str, rng: random.Random) -> dict[str, Any]:
    roll = min(0.999999, max(0.0, rng.random()))
    acc = 0.0
    quality = FISH_KING_WEIGHTS[-1][0]
    for name, weight in FISH_KING_WEIGHTS:
        acc += weight
        if roll < acc:
            quality = name
            break
    set_name = FISH_KING_SETS.get(plane) or rng.choice(list(SETS))
    return create(quality, set_name, rng)


def add(st: Mapping[str, Any], relic: Mapping[str, Any]) -> dict[str, Any]:
    cur = normalize(st)
    if len(cur["bag"]) >= BAG_MAX:
        raise ValueError("遗珍背包已满（200 件），请先分解")
    row = _norm_relic(relic)
    if not row:
        raise ValueError("遗珍数据无效")
    cur["bag"].append(row)
    return cur


# ---------------------------------------------------------------- 分解 / 合成

def salvage(st: Mapping[str, Any], ids: Sequence[str]) -> tuple[dict[str, Any], list[dict], int]:
    cur = normalize(st)
    if not ids:
        raise ValueError("请选择要分解的遗珍")
    engraved = {r["id"] for p in PARTS for r in cur["engrave"][p] if r}
    if any(i in engraved for i in ids):
        raise ValueError("已铭刻的遗珍请先 #卸下遗珍 再分解")
    picked: list[dict] = []
    for rid in ids:
        row = next((r for r in cur["bag"] if r["id"] == rid), None)
        if row is None:
            raise ValueError(f"背包中没有这件遗珍：{rid}")
        picked.append(row)
    fragments = sum(QUALITIES[r["quality"]][1] for r in picked)
    drop = set(ids)
    cur["bag"] = [r for r in cur["bag"] if r["id"] not in drop]
    cur["fragments"] += fragments
    return cur, picked, fragments


def select_for_salvage(st: Mapping[str, Any], selector: str) -> list[str]:
    """`编号`（1 起）或 `品质`（批量）→ 遗珍 id 列表。"""
    cur = normalize(st)
    sel = (selector or "").strip()
    if sel in QUALITIES:
        ids = [r["id"] for r in cur["bag"] if r["quality"] == sel]
        if not ids:
            raise ValueError(f"背包中没有【{sel}】品质的遗珍")
        return ids
    if not sel.isdigit():
        raise ValueError("用法：#分解遗珍 编号 或 #分解遗珍 品质")
    idx = int(sel) - 1
    if idx < 0 or idx >= len(cur["bag"]):
        raise ValueError("背包中没有这个编号，请先 #遗珍背包")
    return [cur["bag"][idx]["id"]]


def synthesize(st: Mapping[str, Any], set_name: str, quality: str, count: int,
               rng: random.Random) -> tuple[dict[str, Any], list[dict], int]:
    cur = normalize(st)
    if set_name not in SETS:
        raise ValueError(f"未知遗珍套装：{set_name}（可选：{'、'.join(SETS)}）")
    if quality not in QUALITIES:
        raise ValueError(f"未知遗珍品质：{quality}（可选：{'、'.join(QUALITIES)}）")
    count = max(1, min(BAG_MAX, int(count)))
    if len(cur["bag"]) + count > BAG_MAX:
        raise ValueError("背包空位不足，请先分解遗珍")
    cost = QUALITIES[quality][2] * count
    if cur["fragments"] < cost:
        raise ValueError(f"遗珍碎片不足：需 {cost}，当前 {cur['fragments']}")
    relics = [create(quality, set_name, rng) for _ in range(count)]
    cur["fragments"] -= cost
    cur["bag"].extend(relics)
    return cur, relics, cost


# ---------------------------------------------------------------- 铭刻

def engrave(st: Mapping[str, Any], bag_index: int, part: str, slot: int = 1) -> tuple[dict, dict, dict | None]:
    cur = normalize(st)
    if part not in PARTS:
        raise ValueError("铭刻部位必须是武器、护具或法宝")
    if slot not in (1, 2):
        raise ValueError("铭刻位只能是 1 或 2")
    if slot == 2 and not cur["expanded"][part]:
        raise ValueError(f"{part}的第二铭刻位尚未拓展（需 {EXPANSION_ITEM}）")
    idx = int(bag_index) - 1
    if idx < 0 or idx >= len(cur["bag"]):
        raise ValueError("背包中没有这个编号")
    relic = cur["bag"].pop(idx)
    replaced = cur["engrave"][part][slot - 1]
    cur["engrave"][part][slot - 1] = relic
    if replaced and len(cur["bag"]) < BAG_MAX:
        cur["bag"].append(replaced)
    return cur, relic, replaced


def unequip(st: Mapping[str, Any], part: str, slot: int = 1) -> tuple[dict, dict]:
    cur = normalize(st)
    if part not in PARTS:
        raise ValueError("卸下部位必须是武器、护具或法宝")
    if slot not in (1, 2):
        raise ValueError("铭刻位只能是 1 或 2")
    relic = cur["engrave"][part][slot - 1]
    if not relic:
        raise ValueError(f"{part}第{slot}位没有遗珍")
    if len(cur["bag"]) >= BAG_MAX:
        raise ValueError("背包已满，无法卸下")
    cur["engrave"][part][slot - 1] = None
    cur["bag"].append(relic)
    return cur, relic


def expand(st: Mapping[str, Any], part: str) -> dict[str, Any]:
    cur = normalize(st)
    if part not in PARTS:
        raise ValueError("拓展部位必须是武器、护具或法宝")
    if cur["expanded"][part]:
        raise ValueError(f"{part}的第二铭刻位已经开启")
    cur["expanded"][part] = True
    return cur


# ---------------------------------------------------------------- 结算

def resonances(st: Mapping[str, Any]) -> list[str]:
    cur = normalize(st)
    by_part = [{r["set"] for r in cur["engrave"][p] if r} for p in PARTS]
    return [name for name in SETS if all(name in s for s in by_part)]


def effects(st: Mapping[str, Any]) -> tuple[dict[str, float], list[str]]:
    """副词条 + 共鸣 → 原版字段汇总（已按 CAPS 钳制）。"""
    cur = normalize(st)
    out: dict[str, float] = {}
    for part in PARTS:
        for relic in cur["engrave"][part]:
            if not relic:
                continue
            for affix in relic["affixes"]:
                field = AFFIXES[affix["name"]][0]
                out[field] = out.get(field, 0.0) + float(affix["value"])
    reso = resonances(cur)
    for name in reso:
        for field, value in SETS[name][1].items():
            out[field] = out.get(field, 0.0) + float(value)
    for field, cap in CAPS.items():
        if field in out:
            out[field] = round(min(cap, max(0.0, out[field])), 4)
    return out, reso


def combat(st: Mapping[str, Any]) -> dict[str, Any]:
    """→ {bao, dealt, taken, lifesteal, shield, dealt_by_type, taken_by_type}。

    近战/神通类加成只对同类型技能生效（原版类型桶），全类型/穿透仍为通用乘区。
    """
    eff, _ = effects(st)
    acc: dict[str, Any] = {"bao": 0.0, "dealt": 0.0, "taken": 0.0,
                           "lifesteal": 0.0, "shield": 0.0,
                           "dealt_by_type": {}, "taken_by_type": {}}
    for field, value in eff.items():
        target = FIELD_MAP.get(field)
        if not target:
            continue
        slot, weight, kind = target
        v = float(value) * weight
        if kind:
            bucket = acc["dealt_by_type" if slot == "dealt" else "taken_by_type"]
            bucket[kind] = bucket.get(kind, 0.0) + v
        else:
            acc[slot] += v
    for key, cap in CAP_TOTAL.items():
        acc[key] = round(min(cap, max(0.0, acc[key])), 4)
    for bucket, cap in (("dealt_by_type", CAP_TOTAL["dealt"]),
                        ("taken_by_type", CAP_TOTAL["taken"])):
        acc[bucket] = {k: round(min(cap, max(0.0, v)), 4)
                       for k, v in acc[bucket].items() if v > 0}
    return acc


def bao_of(doc: Any) -> float:
    """装备聚合用：遗珍贡献的暴击率（已含暴击伤害折算）。"""
    return combat(state_of(doc))["bao"]


def effects_text(st: Mapping[str, Any]) -> list[str]:
    eff, _ = effects(st)
    rows = [f"{field}+{value:.1%}" for field, value in eff.items() if value > 0]
    return rows


def line(relic: Mapping[str, Any] | None) -> str:
    if not relic:
        return "空"
    affixes = "、".join(
        f"{a['name']}·{AFFIXES[a['name']][0]}+{float(a['value']):.1%}"
        for a in relic.get("affixes") or [] if a.get("name") in AFFIXES
    )
    return f"【{relic['quality']}】{relic['set']}（{affixes or '无副词条'}）"


# ---------------------------------------------------------------- 文案

def panel(doc: Any) -> str:
    st = state_of(doc)
    eff, reso = effects(st)
    lines = ["【诸天遗珍·铭刻】"]
    for part in PARTS:
        second = line(st["engrave"][part][1]) if st["expanded"][part] else "未拓展"
        lines.append(f"{part}① {line(st['engrave'][part][0])}")
        lines.append(f"{part}② {second}")
    lines.append(f"道韵共鸣：{'、'.join(reso) or '无'}")
    lines.append(f"遗珍总效：{'、'.join(effects_text(st)) or '无'}")
    lines.append("操作：#遗珍背包｜#铭刻遗珍 编号 部位 [1/2]｜#拓展遗珍槽 部位")
    return "\n".join(lines)


def bag_text(doc: Any) -> str:
    st = state_of(doc)
    lines = [f"【遗珍背包 {len(st['bag'])}/{BAG_MAX}】", f"遗珍碎片：{st['fragments']}"]
    if not st["bag"]:
        lines.append("当前没有未铭刻的遗珍（#合成遗珍 套装 品质 可定向合成）。")
    for i, relic in enumerate(st["bag"][:40], 1):
        lines.append(f"{i}. {line(relic)}")
    if len(st["bag"]) > 40:
        lines.append(f"……另有 {len(st['bag']) - 40} 件，先分解或铭刻后再看。")
    lines.append("铭刻：#铭刻遗珍 编号 武器/护具/法宝 [1/2]")
    lines.append("分解：#分解遗珍 编号｜#分解遗珍 品质（批量）")
    lines.append("合成：#合成遗珍 套装 品质 [数量]")
    return "\n".join(lines)


def atlas_text(doc: Any) -> str:
    lines = ["【诸天遗珍图鉴】"]
    lines.append("品质：" + "、".join(f"{k}{v[0]}词条" for k, v in QUALITIES.items()))
    lines.append("副词条：" + "、".join(f"{k}·{v[0]}" for k, v in AFFIXES.items()))
    lines.append("")
    lines.append("三件共鸣必须由武器、护具、法宝各承载一件同套遗珍：")
    for name, (desc, eff) in SETS.items():
        lines.append(f"【{name}】{desc}")
        lines.append("共鸣：" + "、".join(f"{k}+{v:.0%}" for k, v in eff.items()))
    lines.append(f"第二铭刻位：消耗【{EXPANSION_ITEM}】，每个部位各一次。")
    lines.append("获得：鱼王宝箱（按位面定套装）或碎片定向合成。")
    return "\n".join(lines)


def fragments_text(doc: Any) -> str:
    st = state_of(doc)
    lines = ["【遗珍碎片】", f"当前持有：{st['fragments']}", "品质｜分解所得｜合成消耗"]
    for name, (_n, salvage, synth) in QUALITIES.items():
        lines.append(f"{name}｜{salvage}｜{synth}")
    lines.append("批量分解只按品质选；已铭刻的遗珍不参与分解。")
    lines.append(f"套装：{'、'.join(SETS)}")
    lines.append("示例：#合成遗珍 荒古战血 至圣 3")
    return "\n".join(lines)
