"""彼岸真世界主链（原版 model/otherShoreTrueWorld.js 移植，每玩家会话制）。

原版要点：
- 半径 48 的六边形世界，扇区按需 materialize（观测/移动/探索才落账）；6 生物群系
  （威胁 3-6）+ 6 地标（真世界门户/先秦炼气祖庭/灵界裂隙源庭/禁宝清算庭/纪元墓海/
  纪元主宰观测台）。
- 敌群四档（真仙/仙王/仙王巨头/准仙帝灾厄变异体），三维逐档翻倍；准仙帝档
  eraReward 1、sourceReward 4 —— 即纪元积累的第四个原版产出点。
- 战利品按 buildEnemyReward：真界源晶 1+tierIndex；tier≥1 加大道规则本源；
  tier≥2 加维度锚晶；tier≥3 加纪元道髓+诸天母金（全部进彼岸铸宝材料袋）。
- 门户文案：入口未开放时提示「请先完成沧澜关键战役并锚定裂界母锚」。

移植口径（差异已标注）：
- 原版为全服共享大地图（Redis + web 网关）；本移植为每玩家会话（ext["true_world"]），
  扇区观测/探索状态随玩家走，全服计数留空结构。
- 解锁门槛：原版按战役进度前置；本移植取 `#完成大星` clears ≥ 7（other_shore_forge）。
- 遇敌战斗由 handler 回调（共享战斗引擎 run_1v1），模块保持纯函数。
- 战败：当前血量降至 1（原版真世界败退同口径）；纪元积累在领取战果时走
  fashan.add_era 封顶入账。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from typing import Any

RADIUS = 48
MAX_OBSERVE_RANGE = 3
EXT_KEY = "true_world"
UNLOCK_CLEARS = 7                 # 本地解锁门槛：完成大星 ≥7（原版战役前置的等价刻度）
ENCOUNTER_CHANCE = 0.42           # 探索未探明扇区的遇敌概率

ENEMY_TIERS: tuple[dict[str, Any], ...] = (
    {"id": "true_immortal", "name": "真仙灾厄变异体", "realm": "真仙",
     "hp": 1_200_000_000_000_000, "atk": 480_000_000_000_000, "def": 420_000_000_000_000,
     "era": 0, "sources": 0},
    {"id": "immortal_king", "name": "仙王灾厄变异体", "realm": "仙王",
     "hp": 2_800_000_000_000_000, "atk": 980_000_000_000_000, "def": 860_000_000_000_000,
     "era": 0, "sources": 1},
    {"id": "immortal_king_giant", "name": "仙王巨头灾厄变异体", "realm": "仙王巨头",
     "hp": 4_800_000_000_000_000, "atk": 1_600_000_000_000_000, "def": 1_450_000_000_000_000,
     "era": 0, "sources": 2},
    {"id": "quasi_immortal_emperor", "name": "准仙帝灾厄变异体", "realm": "准仙帝",
     "hp": 8_400_000_000_000_000, "atk": 3_000_000_000_000_000, "def": 2_800_000_000_000_000,
     "era": 1, "sources": 4},
)
TIER_BY_ID = {t["id"]: t for t in ENEMY_TIERS}

BIOMES: tuple[dict[str, Any], ...] = (
    {"id": "qin-ancient-court", "name": "先秦炼气遗都", "threat": 3,
     "desc": "古炼气士以星辰为炉、以裂隙为舟的残存道场。"},
    {"id": "spirit-rift-wilds", "name": "灵界裂隙荒原", "threat": 4,
     "desc": "裂隙像河流一样改道，来自彼岸的邪魔在此留下巢穴。"},
    {"id": "era-tomb-sea", "name": "纪元墓海", "threat": 5,
     "desc": "沉没纪元的道果在黑潮下缓慢呼吸。"},
    {"id": "forbidden-treasure-waste", "name": "违禁至宝荒境", "threat": 5,
     "desc": "宇宙规则在这里断裂，先天至宝的残响会主动择主。"},
    {"id": "transdimensional-corridor", "name": "超维回廊", "threat": 6,
     "desc": "纪元主宰投下观测影子的狭长节点。"},
    {"id": "true-source-starfield", "name": "真界源海", "threat": 4,
     "desc": "真界源晶从星海深处析出，守护者从未离开。"},
)
BIOME_BY_ID = {b["id"]: b for b in BIOMES}

LANDMARKS: tuple[dict[str, Any], ...] = (
    {"id": "true-world-gate", "q": 0, "r": 0, "name": "真世界门户", "kind": "gate",
     "biome": "true-source-starfield",
     "lore": "太初星墟记忆中的彼岸入口，所有远征从此重新计算坐标。"},
    {"id": "qin-qi-refiner-ancestral-court", "q": 7, "r": -3, "name": "先秦炼气祖庭",
     "kind": "civilization", "biome": "qin-ancient-court",
     "lore": "消失的先秦炼气士曾在这里留下以身为种的道种炉。"},
    {"id": "spirit-rift-source", "q": -9, "r": 4, "name": "灵界裂隙源庭",
     "kind": "rift", "biome": "spirit-rift-wilds",
     "lore": "诸天灵界裂缝的旧源谱，记录着彼岸修士第一次越界。"},
    {"id": "forbidden-treasure-citadel", "q": 13, "r": -8, "name": "禁宝清算庭",
     "kind": "citadel", "biome": "forbidden-treasure-waste",
     "lore": "彼岸古文明派出销毁先天至宝的超规格清算中枢。"},
    {"id": "era-tomb-sea", "q": -16, "r": 12, "name": "纪元墓海",
     "kind": "tomb", "biome": "era-tomb-sea",
     "lore": "击败准仙帝敌群后，可从此处提取纪元积累。"},
    {"id": "overlord-observatory", "q": 21, "r": -13, "name": "纪元主宰观测台",
     "kind": "observatory", "biome": "transdimensional-corridor",
     "lore": "逻辑彼岸的超维强者借此投下化身，观察禁宝清算。"},
)
LANDMARK_BY_COORD = {f"{l['q']},{l['r']}": l for l in LANDMARKS}

MATERIAL_REWARDS = (
    ("true-world-source-crystal", 0, "真界源晶"),
    ("dao-rule-origin", 1, "大道规则本源"),
    ("dimension-anchor-crystal", 2, "维度锚晶"),
    ("era-dao-marrow", 3, "纪元道髓"),
    ("all-heavens-mother-metal", 3, "诸天母金"),
)


def hex_distance(q1: int, r1: int, q2: int, r2: int) -> int:
    return max(abs(q1 - q2), abs(r1 - r2), abs((q1 + r1) - (q2 + r2)))


def in_radius(q: int, r: int) -> bool:
    return hex_distance(q, r, 0, 0) <= RADIUS


def _sector_hash(q: int, r: int) -> int:
    return int(hashlib.sha256(f"tw:{q},{r}".encode("utf-8")).hexdigest()[:8], 16)


def biome_of(q: int, r: int) -> dict[str, Any]:
    """地标格覆盖所属群系；其余按 (q,r) 确定性取样。"""
    lm = LANDMARK_BY_COORD.get(f"{q},{r}")
    if lm:
        return BIOME_BY_ID[lm["biome"]]
    if q == 0 and r == 0:
        return BIOME_BY_ID["true-source-starfield"]
    return BIOMES[_sector_hash(q, r) % len(BIOMES)]


def sector_name(q: int, r: int) -> str:
    lm = LANDMARK_BY_COORD.get(f"{q},{r}")
    if lm:
        return lm["name"]
    biome = biome_of(q, r)
    idx = _sector_hash(q, r) % 99 + 1
    return f"{biome['name']}·扇区{idx:02d}"


def unlock_gate(doc: Any) -> tuple[bool, int]:
    """解锁检查：完成大星 clears（other_shore_forge 材料袋计数）。"""
    try:
        from . import other_shore_forge as osf_mod
        clears = int(osf_mod.ensure(doc).get("clears", 0) or 0)
    except Exception:
        clears = 0
    return clears >= UNLOCK_CLEARS, clears


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = {
        "active": False, "q": 0, "r": 0, "era_acc": 0, "sources": 0,
        "victories": 0, "quasi_defeated": 0,
        "sectors": {}, "enemy": None, "pending": [],
    }
    if isinstance(raw, Mapping):
        st.update({k: v for k, v in raw.items() if k in st})
        st.setdefault("sectors", {})
        st.setdefault("pending", [])
    return st


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = {}
        doc.ext = ext
    ext[EXT_KEY] = dict(st)


def observe_sector(st: dict, q: int, r: int) -> dict[str, Any]:
    key = f"{q},{r}"
    sectors = st.setdefault("sectors", {})
    if key not in sectors:
        biome = biome_of(q, r)
        lm = LANDMARK_BY_COORD.get(key)
        sectors[key] = {"name": sector_name(q, r), "biome": biome["id"],
                        "landmark": lm["id"] if lm else None, "explored": False,
                        "threat": int(biome["threat"])}
    return sectors[key]


def unlock_check(doc: Any) -> tuple[bool, str]:
    ok, clears = unlock_gate(doc)
    if not ok:
        return False, (f"【真世界】入口尚未开放：请先完成沧澜关键战役并锚定裂界母锚"
                       f"（完成大星 ≥{UNLOCK_CLEARS}，当前 {clears}）。")
    return True, ""


def enter(doc: Any) -> tuple[bool, str]:
    ok, why = unlock_check(doc)
    if not ok:
        return False, why
    st = state_of(doc)
    if st.get("active"):
        return False, "你已身处真世界（#真世界状态 查看）。"
    st["active"] = True
    st["q"], st["r"] = 0, 0
    gate = observe_sector(st, 0, 0)
    gate["explored"] = True
    save(doc, st)
    return True, ("【真世界】你踏过太初星墟的记忆，降临真世界门户（0,0）。\n"
                  "动作：#观测真世界 q,r｜#前往真世界 q,r｜#探索真世界｜#迎战真世界敌群｜"
                  "#领取真世界战果｜#返回沧澜界")


def leave(doc: Any) -> tuple[bool, str]:
    st = state_of(doc)
    if not st.get("active"):
        return False, "你并不在真世界。"
    st["active"] = False
    st["enemy"] = None
    save(doc, st)
    return True, "【返回沧澜界】你从真世界撤回彼岸（进度保留，再次 #进入真世界 续行）。"


def observe(doc: Any, q: int, r: int) -> tuple[bool, str]:
    st = state_of(doc)
    if not st.get("active"):
        return False, "先 #进入真世界。"
    q, r = int(q), int(r)
    if not in_radius(q, r):
        return False, f"（{q},{r}）在半径 {RADIUS} 的真世界之外。"
    dist = hex_distance(st["q"], st["r"], q, r)
    if dist > MAX_OBSERVE_RANGE:
        return False, f"观测范围 {MAX_OBSERVE_RANGE} 格，目标距离 {dist} 格。"
    row = observe_sector(st, q, r)
    biome = BIOME_BY_ID[row["biome"]]
    save(doc, st)
    lines = [f"【观测 {q},{r}】{row['name']}（{biome['name']}）", biome["desc"]]
    lm = LANDMARK_BY_COORD.get(f"{q},{r}")
    if lm:
        lines.append(f"★ 地标「{lm['name']}」：{lm['lore']}")
    lines.append(f"威胁 {row['threat']}｜{'已探明' if row['explored'] else '未探明'}｜"
                 f"前往：#前往真世界 {q},{r}")
    return True, "\n".join(lines)


def move(doc: Any, q: int, r: int) -> tuple[bool, str]:
    st = state_of(doc)
    if not st.get("active"):
        return False, "先 #进入真世界。"
    q, r = int(q), int(r)
    if not in_radius(q, r):
        return False, f"（{q},{r}）在真世界之外。"
    dist = hex_distance(st["q"], st["r"], q, r)
    if dist != 1:
        return False, f"每步只可移动 1 格（当前 {st['q']},{st['r']}，目标距离 {dist}）。"
    st["q"], st["r"] = q, r
    row = observe_sector(st, q, r)
    save(doc, st)
    biome = BIOME_BY_ID[row["biome"]]
    lm = LANDMARK_BY_COORD.get(f"{q},{r}")
    lines = [f"【前往 {q},{r}】{row['name']}（{biome['name']}）"]
    if lm:
        lines.append(f"★ 地标「{lm['name']}」：{lm['lore']}")
    lines.append("#探索真世界 查明此扇区。")
    return True, "\n".join(lines)


def _tier_roll(threat: int, rng: Any) -> dict[str, Any]:
    """敌群档位随群系威胁抬升（威胁 3→1 档起步，6→四档可遇）。"""
    weights = {3: (70, 30, 0, 0), 4: (40, 45, 15, 0), 5: (15, 40, 33, 12),
               6: (5, 25, 40, 30)}[threat]
    tiers = [w for _t, w in zip(ENEMY_TIERS, weights)]
    pick = rng.choices(ENEMY_TIERS, weights=tiers)[0]
    return pick


def explore(doc: Any, now: float, rng: Any) -> tuple[bool, str]:
    """探索当前扇区：首次探明 + 概率遇敌（生成敌群快照，等待 #迎战）。"""
    st = state_of(doc)
    if not st.get("active"):
        return False, "先 #进入真世界。"
    q, r = int(st["q"]), int(st["r"])
    row = observe_sector(st, q, r)
    first = not row["explored"]
    row["explored"] = True
    lines = []
    if first:
        lines.append(f"【探明 {q},{r}】{row['name']}已记入星图。")
    if st.get("enemy"):
        lines.append("当前敌群尚未击退，先 #迎战真世界敌群。")
        save(doc, st)
        return True, "\n".join(lines)
    if rng.random() >= ENCOUNTER_CHANCE:
        lines.append("此扇区暂无异动，星图已更新。")
        save(doc, st)
        return True, "\n".join(lines)
    tier = _tier_roll(int(row["threat"]), rng)
    st["enemy"] = {"tier": tier["id"], "hp": int(tier["hp"]), "max": int(tier["hp"]),
                   "sector": f"{q},{r}", "at": float(now)}
    save(doc, st)
    lines.append(f"【遭遇】{tier['name']}（{tier['realm']}）自扇区深处逼近！")
    lines.append(f"血量 {tier['hp']:,}｜攻 {tier['atk']:,}｜防 {tier['def']:,}")
    lines.append("#迎战真世界敌群 展开决战。")
    return True, "\n".join(lines)


def battle_outcome(doc: Any, won: bool, rng: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    """战果结算：胜 → buildEnemyReward 掉落进 pending；败 → 撤离扇区（血量由 handler 处理）。"""
    st = state_of(doc)
    enemy = st.get("enemy")
    if not isinstance(enemy, Mapping):
        return False, "当前没有敌群。", {}
    tier = TIER_BY_ID[str(enemy["tier"])]
    if won:
        tier_index = ENEMY_TIERS.index(tier)
        materials: dict[str, int] = {}
        for mid, min_tier, _name in MATERIAL_REWARDS:
            if tier_index >= min_tier:
                materials[mid] = materials.get(mid, 0) + (1 + tier_index if mid == "true-world-source-crystal" else 1)
        era = int(tier["era"])
        sources = int(tier["sources"])
        st["victories"] = int(st.get("victories", 0) or 0) + 1
        st["era_acc"] = int(st.get("era_acc", 0) or 0) + era
        st["sources"] = int(st.get("sources", 0) or 0) + sources
        if tier["id"] == "quasi_immortal_emperor":
            st["quasi_defeated"] = int(st.get("quasi_defeated", 0) or 0) + 1
        st.setdefault("pending", []).append({
            "tier": tier["id"], "materials": materials, "era": era,
            "sources": sources, "sector": str(enemy.get("sector")), "at": float(now),
        })
        st["enemy"] = None
        save(doc, st)
        mat_text = "、".join(f"{n}×{materials.get(mid, 0)}"
                             for mid, _t, n in MATERIAL_REWARDS if mid in materials)
        return True, (f"【真世界大捷】{tier['name']}伏诛！战利已入战果待领（#领取真世界战果）：\n{mat_text}"
                      + (f"\n纪元积累 +{era}（领取时入账）" if era else "")), materials
    st["enemy"] = None
    save(doc, st)
    return True, "【真世界败退】你被敌群击溃，狼狈撤出扇区（气血降至 1），敌群散去。", {}


def claim(doc: Any) -> tuple[bool, str, dict[str, int], int]:
    """领取战果：材料入彼岸铸宝袋，纪元积累走 fashan.add_era 封顶入账。"""
    st = state_of(doc)
    pending = st.get("pending") or []
    if not pending:
        return False, "没有待领取的真世界战果。", {}, 0
    from . import other_shore_forge as osf_mod, fashan as fashan_mod
    forge_st = osf_mod.ensure(doc)
    total_era = 0
    items: dict[str, int] = {}
    lines = ["--- 真世界战果领取 ---"]
    for p in pending:
        bundle = dict(p.get("materials") or {})
        osf_mod.add_materials(forge_st, bundle)
        for mid, qty in bundle.items():
            items[mid] = items.get(mid, 0) + qty
        total_era += int(p.get("era", 0) or 0)
    era_gained = fashan_mod.add_era(doc, total_era) if total_era else 0
    st["pending"] = []
    save(doc, st)
    lines.append(f"结算 {len(pending)} 份战果：材料已注入彼岸铸宝材料袋。")
    lines.append("材料：" + "、".join(f"{osf_mod.MATERIAL_NAMES.get(k, k)}×{v}"
                                     for k, v in items.items()))
    if total_era:
        lines.append(f"纪元积累 +{era_gained}（{fashan_mod.era_of(doc)}/{fashan_mod.ERA_CAP}）"
                     + ("" if era_gained == total_era else f"，超出上限{total_era - era_gained}点散逸"))
    return True, "\n".join(lines), items, era_gained


def panel(doc: Any, now: float) -> str:
    st = state_of(doc)
    if not st.get("active"):
        return "--- 真世界 ---\n未进入。完成大星 ≥7 后 #进入真世界。"
    q, r = int(st["q"]), int(st["r"])
    row = observe_sector(st, q, r)
    biome = BIOME_BY_ID[row["biome"]]
    enemy = st.get("enemy")
    lines = ["--- 彼岸世界·真世界 ---",
             f"当前坐标：{q},{r}｜{row['name']}（{biome['name']}｜威胁 {row['threat']}）",
             f"个人战果：纪元 {st.get('era_acc', 0)}｜准仙帝本源 {st.get('sources', 0)}"
             f"｜伏诛 {st.get('victories', 0)}（准仙帝敌群 {st.get('quasi_defeated', 0)}）",
             f"待领战果：{len(st.get('pending') or [])} 份"]
    if enemy:
        tier = TIER_BY_ID[str(enemy["tier"])]
        lines.append(f"当前敌群：{tier['name']}｜{int(enemy['hp']):,}/{int(enemy['max']):,}")
    lines.append("动作：#观测真世界 q,r｜#前往真世界 q,r｜#探索真世界｜#迎战真世界敌群｜"
                 "#领取真世界战果｜#返回沧澜界")
    return "\n".join(lines)
