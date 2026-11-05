"""彼岸 · 大道至宝（W7-5a）：三层位面 + 四配方 + 24 小时开炉。

原版：
- 层级 `model/otherShoreProgression.js:44-108`（沧澜界 / 真世界 / 乾坤界）
- 配方 `OTHER_SHORE_DAO_TREASURE_RECIPES`（三宝归墟法 / 彼岸定法 / 道果五宝法 / 还真编权法）
- 开炉 `model/otherShoreDaoTreasureForge.js`（24 小时，`FORGE_DURATION_MS`）

本移植（最小可用）：
- 层解锁：沧澜界常开 → 完成 1 颗大星开真世界 → 真世界 + 破界 20 档开乾坤界
- 材料五种（真界源晶/大道规则本源/维度锚晶/纪元道髓/诸天母金）；**来源＝完成大星**（每次一包）+ 魔主伏诛补贴
- 四配方保留原版的材料总价与层门槛；原版要求的「先天至宝 3/5 件、自身道果、准仙帝本源 30」在本移植无对应体系，
  折算为：帝兵品阶（器胚）、道心 500（道果）、魔主击杀 3 次（准仙帝本源）
- 开炉 24 小时、同一时刻只能一炉；`#大道出炉` 领取 → 大道至宝（永久全属性/暴击加成，走 equipment.aggregate）
- 第二法（彼岸定法）沿用原版「缺古法正文」的锁定态

shortcut：彼岸古法正文、权柄编辑器、冷却倍率、先天至宝融合动画、真世界战役掉落链未移植。
"""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping
from typing import Any

FORGE_SECONDS = 24 * 3600
TREASURE_CAP = 3          # 最多同时持有 3 件大道至宝
ALL_CAP = 0.60            # 全属性加成上限
BAO_CAP = 0.30            # 暴击加成上限

LAYERS: tuple[dict[str, Any], ...] = (
    {"id": "canglan", "name": "沧澜界", "desc": "彼岸第一层星海，承担开图与前线营地循环。"},
    {"id": "true_world", "name": "真世界", "desc": "古文明主战场，准仙帝敌人留下纪元积累与炼器法。",
     "need": "完成 1 颗大星"},
    {"id": "qiankun", "name": "乾坤界", "desc": "高维战场，盛产维度航路与至宝稳定材料。",
     "need": "抵达真世界 + 破界 20 档"},
)

MATERIALS: tuple[dict[str, Any], ...] = (
    {"id": "true-world-source-crystal", "name": "真界源晶", "desc": "真世界本源凝结的稳定晶核。"},
    {"id": "dao-rule-origin", "name": "大道规则本源", "desc": "用于固定新至宝权柄边界的规则本源。"},
    {"id": "dimension-anchor-crystal", "name": "维度锚晶", "desc": "把炼器过程钉在当前维度，避免新权柄漂移。"},
    {"id": "era-dao-marrow", "name": "纪元道髓", "desc": "从纪元积累中提炼出的器道骨髓。"},
    {"id": "all-heavens-mother-metal", "name": "诸天母金", "desc": "承载多件权柄而不互相湮灭的母材。"},
)
MATERIAL_NAMES = {m["id"]: m["name"] for m in MATERIALS}

# 完成一颗大星的材料包（原版靠真世界战役掉落，这里作为唯一稳定来源）
CLEAR_BUNDLE: dict[str, int] = {
    "true-world-source-crystal": 60,
    "dao-rule-origin": 30,
    "dimension-anchor-crystal": 8,
    "era-dao-marrow": 5,
    "all-heavens-mother-metal": 3,
}
OVERLORD_BUNDLE: dict[str, int] = {"dimension-anchor-crystal": 5, "era-dao-marrow": 3}

# 四配方：material 为原版「基础 + 稳定剂」总价；needs 为本移植的折算门槛
RECIPES: tuple[dict[str, Any], ...] = (
    {
        "index": 1, "id": "three-innate-erasure", "name": "三宝归墟法",
        "desc": "以帝兵为器胚，融三件至宝权柄（本移植折算为帝兵品阶）生成全新大道至宝。",
        "layer": "true_world",
        "materials": {"true-world-source-crystal": 330, "dao-rule-origin": 170,
                      "dimension-anchor-crystal": 30, "era-dao-marrow": 20,
                      "all-heavens-mother-metal": 10},
        "needs": {"dibing_stage": 4},
        "output": {"name": "归墟至宝", "all": 0.15, "bao": 0.05},
    },
    {
        "index": 2, "id": "custom-ancient-method", "name": "彼岸定法",
        "desc": "为持有者预留的第二炼制法，具体权柄需彼岸古法正文补充。",
        "layer": "true_world", "locked": "尚缺彼岸古法正文",
        "materials": {"true-world-source-crystal": 350, "dao-rule-origin": 185,
                      "dimension-anchor-crystal": 50, "era-dao-marrow": 35,
                      "all-heavens-mother-metal": 18},
        "needs": {},
        "output": {"name": "定法至宝", "all": 0.12, "bao": 0.04},
    },
    {
        "index": 3, "id": "dao-fruit-five-treasure", "name": "道果五宝法",
        "desc": "以自身道果与五件至宝强行开炉，新器只继承部分权柄并随机强化一项。",
        "layer": "true_world",
        "materials": {"true-world-source-crystal": 380, "dao-rule-origin": 205,
                      "dimension-anchor-crystal": 110, "era-dao-marrow": 75,
                      "all-heavens-mother-metal": 40},
        "needs": {"dibing_stage": 6, "daoxin": 500},
        "output": {"name": "五宝留史", "all": 0.12, "bao": 0.04, "random": 0.02},
    },
    {
        "index": 4, "id": "return-truth-edit", "name": "还真编权法",
        "desc": "借还真之力，收三位准仙帝本源（本移植折算为魔主战绩），自定义三项强化权柄。",
        "layer": "qiankun",
        "materials": {"true-world-source-crystal": 420, "dao-rule-origin": 240,
                      "dimension-anchor-crystal": 150, "era-dao-marrow": 110,
                      "all-heavens-mother-metal": 70},
        "needs": {"dim_tier": 20, "overlord_kills": 3},
        "output": {"name": "还真编权至宝", "all": 0.20, "bao": 0.08},
    },
)

RECIPE_BY_INDEX = {r["index"]: r for r in RECIPES}


def ensure(doc: Any) -> dict:
    """取（并按需初始化）ext["dao_forge"]。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("dao_forge")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("materials", {})
    if not isinstance(st.get("materials"), dict):
        st["materials"] = {}
    st.setdefault("clears", 0)
    st.setdefault("forge", None)
    st.setdefault("treasures", [])
    if not isinstance(st.get("treasures"), list):
        st["treasures"] = []
    ext["dao_forge"] = st
    return st


def layer_of(st: Mapping, doc: Any) -> str:
    """当前可用最高层（由战绩与破界强度推导，不单独存层号）。"""
    if int(st.get("clears", 0) or 0) < 1:
        return "canglan"
    try:
        from .plane import dim_tier
        tier = dim_tier(doc)
    except Exception:
        tier = 0
    return "qiankun" if tier >= 20 else "true_world"


def layer_name(layer_id: str) -> str:
    return next((x["name"] for x in LAYERS if x["id"] == layer_id), layer_id)


def has_layer(st: Mapping, doc: Any, need: str) -> bool:
    order = [x["id"] for x in LAYERS]
    return order.index(layer_of(st, doc)) >= order.index(need)


def add_materials(st: dict, bundle: Mapping[str, int]) -> dict[str, int]:
    bag = dict(st.get("materials") or {})
    for mid, amount in bundle.items():
        bag[mid] = int(bag.get(mid, 0) or 0) + max(0, int(amount))
    st["materials"] = bag
    return bag


def material_lines(st: Mapping) -> list[str]:
    bag = st.get("materials") or {}
    return [f"{MATERIAL_NAMES[m['id']]} {int(bag.get(m['id'], 0) or 0):,}" for m in MATERIALS]


def treasure_bonus(st: Mapping) -> tuple[float, float]:
    all_b = bao_b = 0.0
    for t in st.get("treasures") or []:
        if not isinstance(t, Mapping):
            continue
        all_b += float(t.get("all", 0) or 0)
        bao_b += float(t.get("bao", 0) or 0)
    return min(ALL_CAP, all_b), min(BAO_CAP, bao_b)


def _needs_state(doc: Any, st: Mapping) -> dict[str, Any]:
    from . import dibing
    try:
        from .plane import dim_tier
        tier = dim_tier(doc)
    except Exception:
        tier = 0
    w = dibing.system_of(doc)
    return {
        "dibing_stage": int(w.get("stage", -1)) if w else -1,
        "daoxin": int(doc.ext.get("daoxin", 0) or 0),
        "dim_tier": tier,
        "overlord_kills": int(st.get("overlord_kills", 0) or 0),
    }


def preview(doc: Any, index: int) -> tuple[bool, list[str], dict]:
    """返回 (是否齐备, 缺口列表, 配方)。"""
    st = ensure(doc)
    recipe = RECIPE_BY_INDEX.get(int(index))
    if not recipe:
        return False, ["没有这个配方（1-4）"], {}
    if recipe.get("locked"):
        return False, [f"未开放：{recipe['locked']}"], dict(recipe)
    missing: list[str] = []
    if not has_layer(st, doc, recipe["layer"]):
        missing.append(f"需抵达【{layer_name(recipe['layer'])}】")
    bag = st.get("materials") or {}
    for mid, need in recipe["materials"].items():
        have = int(bag.get(mid, 0) or 0)
        if have < need:
            missing.append(f"{MATERIAL_NAMES[mid]} {have}/{need}")
    state = _needs_state(doc, st)
    for key, need in (recipe.get("needs") or {}).items():
        have = state.get(key, 0)
        if have < need:
            label = {"dibing_stage": "帝兵品阶", "daoxin": "道心",
                     "dim_tier": "破界档", "overlord_kills": "魔主战绩"}.get(key, key)
            if key == "dibing_stage":
                missing.append(f"{label}未达标（需圣兵以上，当前 {dibing_stage_name(have)}）")
            else:
                missing.append(f"{label} {have}/{need}")
    return (not missing), missing, dict(recipe)


def dibing_stage_name(stage: int) -> str:
    from . import dibing
    if stage < 0:
        return "未炼帝兵"
    return dibing.STAGES[min(stage, len(dibing.STAGES) - 1)]


def start(doc: Any, index: int, now: float | None = None) -> tuple[bool, str]:
    st = ensure(doc)
    now = time.time() if now is None else now
    forge = st.get("forge")
    if isinstance(forge, Mapping) and str(forge.get("status")) == "forging":
        left = max(0, int(float(forge.get("ready_at", 0) or 0) - now))
        return False, (f"丹炉未冷：{forge.get('recipe_name')}尚在炼制中，"
                       f"还需 {left // 3600} 时 {left % 3600 // 60} 分（#大道出炉）。")
    ok, missing, recipe = preview(doc, index)
    if not recipe:
        return False, "没有这个配方（1-4）。"
    if recipe.get("locked"):
        return False, f"【{recipe['name']}】{recipe['locked']}，开炉状态保持锁定。"
    if not ok:
        return False, f"【{recipe['name']}】条件未齐：" + "、".join(missing)
    bag = dict(st.get("materials") or {})
    for mid, need in recipe["materials"].items():
        bag[mid] = int(bag.get(mid, 0) or 0) - int(need)
    st["materials"] = bag
    st["forge"] = {
        "recipe_index": int(index),
        "recipe_id": recipe["id"],
        "recipe_name": recipe["name"],
        "started_at": float(now),
        "ready_at": float(now) + FORGE_SECONDS,
        "status": "forging",
    }
    return True, (f"【大道开炉】{recipe['name']}：材料已投入丹炉，"
                  f"24 小时后发「#大道出炉」领取大道至宝。")


def forge_state(doc: Any, now: float) -> dict | None:
    st = ensure(doc)
    forge = st.get("forge")
    if not isinstance(forge, Mapping):
        return None
    out = dict(forge)
    ready = float(out.get("ready_at", 0) or 0)
    out["left"] = max(0, int(ready - now))
    out["ready"] = ready <= now
    return out


def claim(doc: Any, now: float | None = None) -> tuple[bool, str, dict | None]:
    st = ensure(doc)
    now = time.time() if now is None else now
    forge = st.get("forge")
    if not isinstance(forge, Mapping):
        return False, "丹炉空空，尚未开炉（#大道开炉 1-4）。", None
    ready = float(forge.get("ready_at", 0) or 0)
    if ready > now:
        left = int(ready - now)
        return False, f"炉火未足，还需 {left // 3600} 时 {left % 3600 // 60} 分。", None
    recipe = RECIPE_BY_INDEX.get(int(forge.get("recipe_index", 0) or 0), {})
    output = dict(recipe.get("output") or {})
    all_b = float(output.get("all", 0.0) or 0.0)
    bao_b = float(output.get("bao", 0.0) or 0.0)
    if output.get("random"):
        all_b = round(all_b + float(output["random"]), 3)      # 道果五宝：随机强化一项
    treasures = list(st.get("treasures") or [])
    if len(treasures) >= TREASURE_CAP:
        return False, f"最多持有 {TREASURE_CAP} 件大道至宝，先舍弃旧器（暂未开放）。", None
    treasure = {
        "name": str(output.get("name") or "大道至宝"),
        "recipe": str(forge.get("recipe_name") or ""),
        "all": all_b,
        "bao": bao_b,
        "at": float(now),
    }
    treasures.append(treasure)
    st["treasures"] = treasures
    st["forge"] = None
    total_all, total_bao = treasure_bonus(st)
    return True, (f"【大道出炉】{treasure['name']}器成！\n"
                  f"全属性 +{all_b:.0%}｜暴击 +{bao_b:.0%}（累计 +{total_all:.0%} / +{total_bao:.0%}，"
                  f"持有 {len(treasures)}/{TREASURE_CAP} 件）"), treasure


def panel(doc: Any, now: float) -> str:
    st = ensure(doc)
    layer = layer_of(st, doc)
    total_all, total_bao = treasure_bonus(st)
    lines = ["--- 大道至宝 · 彼岸炼器法 ---",
             f"当前层级：{layer_name(layer)}｜完成大星 {int(st.get('clears', 0) or 0)} 颗"]
    for row in LAYERS:
        mark = "●" if layer == row["id"] else ("○" if row["id"] != "canglan" else "○")
        need = f"（{row['need']}）" if row.get("need") else ""
        lines.append(f"{mark} {row['name']}{need}")
    lines.append("材料：" + "、".join(material_lines(st)))
    lines.append(f"已铸至宝：{len(st.get('treasures') or [])}/{TREASURE_CAP}"
                 f"｜加成 全属性 +{total_all:.0%}、暴击 +{total_bao:.0%}")
    forge = forge_state(doc, now)
    if forge:
        if forge["ready"]:
            lines.append(f"丹炉：{forge.get('recipe_name')}已可出炉（#大道出炉）")
        else:
            lines.append(f"丹炉：{forge.get('recipe_name')}炼制中，"
                         f"还需 {forge['left'] // 3600} 时 {forge['left'] % 3600 // 60} 分")
    else:
        lines.append("丹炉：空")
    lines.append("配方：")
    for r in RECIPES:
        lock = f"（{r['locked']}）" if r.get("locked") else ""
        lines.append(f"{r['index']}. {r['name']}{lock}｜{r['desc']}")
    lines.append("#彼岸铸宝 1-4 看缺口｜#大道开炉 1-4 封材｜#大道出炉 领取")
    return "\n".join(lines)


def treasure_text(doc: Any) -> str:
    st = ensure(doc)
    rows = [t for t in (st.get("treasures") or []) if isinstance(t, Mapping)]
    if not rows:
        return "你尚未铸成大道至宝（#彼岸铸宝）。"
    lines = ["--- 大道至宝 ---"]
    for i, t in enumerate(rows, 1):
        lines.append(f"{i}. {t.get('name')}（{t.get('recipe')}）"
                     f"｜全属性 +{float(t.get('all', 0) or 0):.0%}"
                     f"｜暴击 +{float(t.get('bao', 0) or 0):.0%}")
    total_all, total_bao = treasure_bonus(st)
    lines.append(f"合计：全属性 +{total_all:.0%}、暴击 +{total_bao:.0%}")
    return "\n".join(lines)


def copy_state(doc: Any) -> dict:
    return copy.deepcopy(ensure(doc))
