"""先天至宝 · 权柄（W8-C2）。

原版取证（以源码为准，规划稿有 6 处冲突，见文末「移植口径」）：
- `apps/User/InnateTreasureAuthorities.js` 1237 行 / **36 条 rule**（别名展开 42 个字符串）。
- `model/innateTreasure.js` 1114 行：**23 件**至宝目录（不是规划稿的 8 件）、24 个 CD key、
  全服唯一 `owners` 状态、17 个战斗钩子（只定义不在此文件调用）。
- `apps/User/xiantianzhibao.js` **与先天至宝无关**，是「功极无相塔」玩法，本移植不搬。
- `model/innateTreasureContest.js` 408 行：24h 择主之争评分逻辑（本移植简化为单人守护灵挑战）。
- 全服状态 `resources/data/innate_treasure_state.json`：
  `{owners, equipped, decree, landscapeRealms, eternalMap}`。

移植口径（重要偏离，全部记录在 `Z:/dsh/缺失玩法规划-W8.md`）：
1. **没有「每纪元 N 次」计数器，也没有全服公告代码**（取证范围内）。限量靠毫秒 CD 时间戳
   + 一次性「待用」flag + 记录数组；本移植 CD 改成秒，直接落 `ext["xtzb"]["cd"]`。
2. **「待用」flag 原版无清理/消费点**，只在战斗钩子里被读。本移植将其实现为
   **6~24 小时蓄势窗口**（窗口内所有战斗生效），不做一次性消费——因为 `build_fighter`
   是纯读函数，在多处 PvE/PvP 入口被调用，回写会造成整档竞态。
3. **原版 22 件本体靠 24h 全服「择主之争」发放**（冠军本体 / 2、3 名七日投影），
   本移植没有全服定时事件，改为 `#至宝择主 <名>` 单人守护灵挑战 + 秘境投放「先天道痕」。
   否则整套系统不可玩（与 W8-C1 本命材料同样的问题）。
4. **原版至宝本体固定三维 1 亿 / 全属性 100**，本移植境界基础 8e5~1e10，
   统一 **÷1000 折算**（`SCALE`），避免前期一件至宝碾压全境。
5. 原版被动散落在 17 个战斗钩子（PVE 无视防御、速度、治疗、修炼倍率…），本移植
   统一收敛成 `combat()` / `yield_mult()` / `guard_mult()` / `time_mult()` 四个出口。
6. `#图中巡游` 是**目录孤儿**（有 CD key、无 rule 注册、无 handler），本移植不建指令。
7. 原版「移交」用 FileRollbackTransaction + 双层玩家锁 + 事务回滚；本移植单连接
   aiosqlite，用一次 `transaction()` 写双方档 + 全服状态即可，语义等价。
8. 无 redis：虚天舟 60 秒邀请 / 山河投影每小时 cron / 截断岁月改全局 action key
   都改成玩家档内的时间戳状态，由显式指令结算。

shortcut：
- 全服状态沿用 `calamity_state` 单例 JSON 的 `xtzb` 子键，不新建表、不做 db 迁移。
- 不注册第三轨：原版 `realmAuthority` 不含先天至宝，执掌与否不影响境界权威。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any, Callable

EXT_KEY = "xtzb"
WORLD_KEY = "xtzb"

SCALE = 1 / 1000                # 原版 1 亿三维 → 本移植 10 万
FLAT_ALL = 100_000             # 1e8 × SCALE
BAO_FLAT = 0.10                # 原版「全属性 100」折算为暴击率
PROJECTION_SECONDS = 7 * 86400
GUARD_WINDOW = 6 * 3600        # 蓄势窗口（原版「待用」无过期，本移植限 6h）
DECREE_SECONDS = 24 * 3600
CLAIM_COST = 30                # 择主消耗「先天道痕」
CLAIM_REALM = 12               # 择主最低境界（realm_index 0-based）
ETERNAL_COST = {"界核": 9, "宇宙核心": 1, "鸿蒙道火": 90}
ETERNAL_GESTATION = 9000       # 原版 9000 世界年 → 本移植 9000 点「界痕」

# ── 至宝目录（23 件，原版 INNATE_TREASURE_CATALOG :91-316） ─────────────────
# combat：加法增量（dealt/taken 为乘区增量，shield/reflect/lifesteal 为比例）
# yield ：收益倍率增量（键见 YIELD_KINDS）
# guard ：渡劫伤害倍率乘数；time：计时行动耗时倍率乘数
CATALOG: dict[str, dict[str, Any]] = {
    "混沌珠": {"title": "万象之源", "passive": "无（权柄：复制 / 演化 / 变幻）",
             "auth": ("混沌复制", "混沌演化", "混沌变幻")},
    "太极图": {"title": "阴阳之宗", "passive": "阴相 30% 化伤反击｜阳相吸血",
             "auth": ("切换太极", "阴阳逆转"), "combat": {"taiji": True}},
    "盘古幡": {"title": "开天圣器", "passive": "PVE 无视 30% 防御",
             "auth": ("开天",), "combat": {"dealt": 0.30},
             "yield": {"raid": 1.0}},
    "诛仙四剑": {"title": "杀伐之极", "passive": "禁疗 + 残血斩杀",
              "auth": ("布诛仙剑阵",), "combat": {"dealt": 0.20}},
    "山河社稷图": {"title": "万里山河", "passive": "小世界产出翻倍 / 栖息位 +2",
               "auth": ("收摄山河", "邀请山河投影"),
               "yield": {"smallworld": 1.0}},
    "天地玄黄玲珑塔": {"title": "玄黄不灭", "passive": "渡劫 / 内景地 -30%",
                 "auth": ("玄黄护道",), "guard": 0.70},
    "东皇钟": {"title": "镇世天音", "passive": "计时行动耗时 -20%",
             "auth": ("东皇镇世",), "time": 0.80},
    "混沌钟": {"title": "岁月禁器", "passive": "计时行动耗时 -30%",
             "auth": ("截断岁月",), "time": 0.70},
    "六道轮回盘": {"title": "生死之枢", "passive": "免强制轮回 / 敌速 -20%",
              "auth": ("执掌轮回",), "combat": {"taken": 0.10}},
    "炼妖壶": {"title": "万灵造化", "passive": "寻宝收益翻倍",
             "auth": ("炼妖融合",), "yield": {"treasure": 1.0}},
    "崆峒印": {"title": "人皇正统", "passive": "本人修炼 ×2 / 内景地 +30%",
             "auth": ("人皇敕令", "借人皇气运修炼"),
             "yield": {"cultivate": 1.0, "innerworld": 0.30}},
    "虚天舟": {"title": "诸界无碍", "passive": "穿梭缩时 / 免疫截杀",
             "auth": ("邀请登舟", "同意登舟", "虚天舟乘员", "离开虚天舟"),
             "time": 0.60},
    "太初仙刃": {"title": "太初裁道", "passive": "PVE 无视 15% 防御",
             "auth": ("太初一斩",), "combat": {"dealt": 0.15}},
    "无量天尺": {"title": "无量护世", "passive": "每战首次受击 ≤45% 最大生命",
             "auth": ("无量护身",), "combat": {"taken": 0.10}},
    "逐日仙辇": {"title": "逐光巡天", "passive": "战斗速度 +10% / 穿梭 -15%",
             "auth": (), "combat": {"dealt": 0.10}, "time": 0.85},
    "造化仙池": {"title": "造化回春", "passive": "治疗 +25%",
             "auth": ("造化回春",), "combat": {"lifesteal": 0.10}},
    "周天星辰旗": {"title": "周天列宿", "passive": "队伍速度 +8%",
              "auth": ("星辰护界",), "combat": {"dealt": 0.08}},
    "万道神炉": {"title": "万道归炉", "passive": "炼丹炼器耗时 -20% / 炉容 +5",
             "auth": ("万道开炉",), "yield": {"alchemy": 0.20}},
    "菩提祖树": {"title": "菩提道祖", "passive": "修炼大幅加成（本移植压到 ×3）",
             "auth": ("菩提悟道",), "yield": {"cultivate": 2.0}},
    "因果神灯": {"title": "照见因果", "passive": "因果债获取 -25%",
             "auth": ("因果净照",), "yield": {"debt": -0.25}},
    "万劫天碑": {"title": "万劫留痕", "passive": "渡劫伤害 -15%",
             "auth": ("万劫淬神",), "guard": 0.85},
    "定海珠": {"title": "诸海之宗", "passive": "开局 20% 生命护盾 / 首次控制免疫",
            "auth": ("演化诸天",), "combat": {"shield": 0.20}},
}
CATALOG["永恒仙图"] = {
    "title": "大道至宝", "passive": "三维固定 +1 万亿（折算）｜九宝权能全保留",
    "auth": ("永恒古史", "永恒改命"),
    "combat": {"dealt": 0.50, "shield": 0.10}, "flat_mult": 10,
}
NAMES: tuple[str, ...] = tuple(CATALOG)
CONTESTABLE: tuple[str, ...] = tuple(n for n in NAMES if n not in ("虚天舟", "永恒仙图"))
ETERNAL_COMPONENTS: tuple[str, ...] = (
    "太初仙刃", "无量天尺", "逐日仙辇", "造化仙池", "周天星辰旗",
    "万道神炉", "菩提祖树", "因果神灯", "万劫天碑",
)
YIELD_KINDS = ("cultivate", "dungeon", "raid", "smallworld", "innerworld",
               "treasure", "alchemy", "debt")

# ── CD（原版毫秒 → 本移植秒；AUTHORITY_COOLDOWNS :318-343） ─────────────────
CD: dict[str, int] = {
    "混沌复制": 12 * 3600, "混沌演化": 24 * 3600, "混沌变幻": 6 * 3600,
    "炼妖融合": 30 * 86400, "玄黄护道": 24 * 3600, "图中巡游": 72 * 3600,
    "收摄山河": 72 * 3600, "开天": 6 * 3600, "诛仙剑阵": 24 * 3600,
    "东皇镇世": 24 * 3600, "截断岁月": 7 * 86400, "人皇敕令": 7 * 86400,
    "执掌轮回": 24 * 3600, "阴阳逆转": 24 * 3600, "太初一斩": 24 * 3600,
    "无量护身": 24 * 3600, "造化回春": 7 * 86400, "星辰护界": 24 * 3600,
    "万道开炉": 72 * 3600, "菩提悟道": 72 * 3600, "因果净照": 7 * 86400,
    "万劫淬神": 7 * 86400, "演化诸天": 24 * 3600, "永恒改命": 10 * 86400,
}

# ── 一次性「待用」蓄势（原版 TREASURE_AUTHORITY_STATE_KEYS :810-821） ────────
# 本移植统一改为带过期戳的窗口，见文件头「移植口径」第 2 条。
FLAGS: dict[str, dict[str, Any]] = {
    "玄黄护道待用": {"treasure": "天地玄黄玲珑塔", "cd": "玄黄护道",
               "guard": 0.70, "note": "渡劫伤害 / 内景地失败率 -30%"},
    "盘古开天待用": {"treasure": "盘古幡", "cd": "开天",
               "combat": {"dealt": 0.60}, "note": "敌防御归零 + 削血 + 洗劫翻倍"},
    "诛仙剑阵待用": {"treasure": "诛仙四剑", "cd": "诛仙剑阵",
               "combat": {"dealt": 0.50, "reflect": 0.20}, "note": "四剑齐鸣，增伤 50% + 反噬 20%"},
    "东皇镇世待用": {"treasure": "东皇钟", "cd": "东皇镇世",
               "combat": {"taken": 0.30}, "note": "镇世三回合，受伤 -30%"},
    "阴阳逆转待用": {"treasure": "太极图", "cd": "阴阳逆转",
               "combat": {"revive": 0.60}, "note": "首次致命伤害转治疗并等量返还"},
    "太初仙刃首击待用": {"treasure": "太初仙刃", "cd": "太初一斩",
                 "combat": {"dealt": 1.50}, "note": "首击 ×2.5（折算为窗口内增伤）"},
    "无量护身待用": {"treasure": "无量天尺", "cd": "无量护身",
               "combat": {"taken": 0.20}, "note": "前三次受击 -20%"},
    "星辰护界待用": {"treasure": "周天星辰旗", "cd": "星辰护界",
               "combat": {"shield": 0.25}, "note": "己方 25% 最大生命护盾"},
    "定海珠演化待用": {"treasure": "定海珠", "cd": "演化诸天",
                "combat": {"shield": 0.50, "reflect": 0.30}, "note": "50% 护盾 + 30% 反噬"},
    "万道开炉待用": {"treasure": "万道神炉", "cd": "万道开炉",
               "yield": {"alchemy": 1.0}, "note": "下次炼丹 / 炼器产出 +100%"},
}
# 权柄 → 蓄势 flag / 立即结算类型
AUTH_FLAG: dict[str, str] = {
    "开天": "盘古开天待用", "布诛仙剑阵": "诛仙剑阵待用",
    "东皇镇世": "东皇镇世待用", "阴阳逆转": "阴阳逆转待用",
    "太初一斩": "太初仙刃首击待用", "无量护身": "无量护身待用",
    "星辰护界": "星辰护界待用", "演化诸天": "定海珠演化待用",
    "玄黄护道": "玄黄护道待用", "万道开炉": "万道开炉待用",
}
AUTH_TREASURE: dict[str, str] = {f: v["treasure"] for f, v in FLAGS.items()}
for _n, _info in CATALOG.items():
    for _a in _info.get("auth", ()):
        AUTH_TREASURE.setdefault(_a, _n)
# 别名 → 正规权柄名（原版 6 组）
ALIASES: dict[str, str] = {
    "太初斩道": "太初一斩", "无量封界": "无量护身", "周天列阵": "星辰护界",
    "菩提顿悟": "菩提悟道", "燃灯解因": "因果净照", "先天至宝图鉴": "至宝图鉴",
}

# ── 信物（原版材料无发放点，本移植补秘境投放） ────────────────────────────
SIGILS: dict[str, str] = {
    "先天道痕": "择主之争留下的道痕，#至宝择主 消耗 30 枚",
    "灵宝残片": "择主失败亦可积累，用于合成永恒仙图时抵扣鸿蒙道火",
    "界核": "永恒仙图合成材料",
    "宇宙核心": "永恒仙图合成材料",
    "鸿蒙道火": "永恒仙图合成材料",
}


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, dict(delta or {})


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


# ── 状态读写 ────────────────────────────────────────────────────────────────
def _defaults() -> dict[str, Any]:
    return {
        "owned": [],             # 纳戒中的至宝（本体或投影）
        "current": "",           # 执掌中的至宝
        "projection": {},        # 名 -> 投影到期秒
        "cd": {},                # 权柄 key -> CD 到期秒
        "flags": {},             # 蓄势 flag -> 到期秒
        "taiji": "阴",
        "temper": 0,            # 万劫淬神累计次数
        "history": [],          # 永恒改命记录（≤10）
        "ship": [],             # 虚天舟乘员 uid
        "landscape_invite": [],  # 山河投影受邀 uid
        "decree_borrow": [],     # 已领敕令的 owner stamp
        "potential": 0,         # 造化回春累计仙道潜力
        "inherit": 0,           # 炼妖融合次数
    }


def ensure(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get(EXT_KEY) if isinstance(doc.ext, Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    for k, v in _defaults().items():
        if k not in st:
            st[k] = v.copy() if isinstance(v, (list, dict)) else v
    if not isinstance(st.get("cd"), dict):
        st["cd"] = {}
    if not isinstance(st.get("flags"), dict):
        st["flags"] = {}
    if not isinstance(st.get("projection"), dict):
        st["projection"] = {}
    if not isinstance(st.get("owned"), list):
        st["owned"] = []
    return st


def save(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext[EXT_KEY] = dict(st)


def _equipment_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("name") or value.get("先天至宝本体") or "")
    return str(value or "")


def is_innate_item_name(name: Any) -> bool:
    return str(name or "").strip() in CATALOG


def is_innate_item(item: Any) -> bool:
    return isinstance(item, Mapping) and (
        is_innate_item_name(item.get("name"))
        or is_innate_item_name(item.get("先天至宝本体"))
    )


def set_equipped_slot(doc: Any, name: str, st: dict[str, Any] | None = None) -> str:
    """写独立至宝槽并同步当前执掌；返回被替换的槽位名。"""
    ext = doc.ext if isinstance(getattr(doc, "ext", None), dict) else {}
    doc.ext = ext
    equipment = ext.setdefault("equipment", {})
    if not isinstance(equipment, dict):
        equipment = ext["equipment"] = {}
    old = _equipment_name(equipment.get("至宝"))
    equipment["至宝"] = name
    st = st or ensure(doc)
    st["current"] = name
    save(doc, st)
    return old


def clear_equipped_slot(doc: Any, name: str = "") -> str:
    """清空匹配的独立至宝槽及当前执掌，保留已认主记录。"""
    ext = doc.ext if isinstance(getattr(doc, "ext", None), dict) else {}
    doc.ext = ext
    equipment = ext.get("equipment")
    equipment = equipment if isinstance(equipment, dict) else {}
    old = _equipment_name(equipment.get("至宝"))
    if old and (not name or old == name):
        equipment.pop("至宝", None)
        st = ensure(doc)
        if st.get("current") == old:
            st["current"] = ""
        save(doc, st)
    return old


def _reconcile_equipment(doc: Any, st: dict[str, Any], now: float,
                         expired: set[str] | None = None) -> bool:
    """迁移旧帝兵槽中的至宝，并让独立至宝槽成为当前执掌的唯一来源。"""
    ext = doc.ext if isinstance(getattr(doc, "ext", None), dict) else {}
    doc.ext = ext
    equipment = ext.get("equipment")
    if not isinstance(equipment, dict):
        return False
    changed = False
    expired = set(expired or ())
    expired.update(name for name, until in st["projection"].items()
                   if float(until or 0) <= now)

    legacy = equipment.get("帝兵")
    legacy_name = _equipment_name(legacy)
    if is_innate_item_name(legacy_name):
        equipment.pop("帝兵", None)
        changed = True
        legacy_expiry = (legacy.get("先天投影截止")
                         if isinstance(legacy, Mapping) else None)
        if legacy_name not in expired and not (
            legacy_expiry is not None and float(legacy_expiry or 0) <= now
        ):
            if legacy_name not in st["owned"]:
                st["owned"].append(legacy_name)
                changed = True
            if not equipment.get("至宝"):
                equipment["至宝"] = legacy_name
                st["current"] = legacy_name
                changed = True

    slot_value = equipment.get("至宝")
    slot_name = _equipment_name(slot_value)
    item_expiry = (slot_value.get("先天投影截止")
                   if isinstance(slot_value, Mapping) else None)
    if slot_name in expired or (
        item_expiry is not None and float(item_expiry or 0) <= now
    ):
        equipment.pop("至宝", None)
        slot_name = ""
        changed = True

    current_name = str(st.get("current") or "")
    if is_innate_item_name(slot_name):
        if slot_name not in st["owned"]:
            st["owned"].append(slot_name)
            changed = True
        if current_name != slot_name:
            st["current"] = slot_name
            changed = True
    elif slot_name:
        if is_innate_item_name(current_name):
            st["current"] = ""
            changed = True
    elif is_innate_item_name(current_name) and current_name not in expired:
        equipment["至宝"] = current_name
        if current_name not in st["owned"]:
            st["owned"].append(current_name)
        changed = True
    elif current_name:
        st["current"] = ""
        changed = True
    return changed


def world_of(calamity: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = (calamity or {}).get(WORLD_KEY) if isinstance(calamity, Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("owners", {})
    st.setdefault("decree", None)
    st.setdefault("landscapes", [])
    st.setdefault("eternal", None)
    st.setdefault("board", [])
    if not isinstance(st["owners"], dict):
        st["owners"] = {}
    if not isinstance(st["landscapes"], list):
        st["landscapes"] = []
    if not isinstance(st["board"], list):
        st["board"] = []
    return st


def set_world(calamity: dict[str, Any], st: Mapping[str, Any]) -> None:
    calamity[WORLD_KEY] = dict(st)


def state_of(doc: Any, now: float | None = None) -> dict[str, Any]:
    """读取并顺手清理过期 CD / 蓄势 / 投影（写回 doc）。"""
    now = time.time() if now is None else float(now)
    st = ensure(doc)
    changed = False
    for key, exp in list(st["cd"].items()):
        if float(exp or 0) <= now:
            del st["cd"][key]
            changed = True
    for key, exp in list(st["flags"].items()):
        if float(exp or 0) <= now:
            del st["flags"][key]
            changed = True
    expired = set()
    for name, exp in list(st["projection"].items()):
        if float(exp or 0) <= now:
            del st["projection"][name]
            expired.add(name)
            changed = True
            if name in st["owned"]:
                st["owned"].remove(name)
            if st["current"] == name:
                st["current"] = ""
    changed = _reconcile_equipment(doc, st, now, expired) or changed
    if changed:
        save(doc, st)
    return st


def current(doc: Any, now: float | None = None) -> str:
    return str(state_of(doc, now).get("current") or "")


def _eternal_formed(world: Mapping[str, Any]) -> bool:
    e = world.get("eternal")
    return isinstance(e, dict) and e.get("status") == "formed"


def has(doc: Any, name: str, now: float | None = None,
        world: Mapping[str, Any] | None = None) -> bool:
    """原版 hasEquippedInnateTreasure：永恒仙图成形后九宝权能全保留。"""
    st = state_of(doc, now)
    if st.get("current") == name:
        return True
    if name == "永恒仙图":
        return st.get("current") == "永恒仙图"
    if world and _eternal_formed(world):
        e = world.get("eternal") or {}
        if e.get("owner") == doc.uid and name in ETERNAL_COMPONENTS:
            return True
    return False


def cd_left(st: Mapping[str, Any], key: str, now: float) -> float:
    return max(0.0, float(st.get("cd", {}).get(key, 0) or 0) - now)


def fmt_cd(seconds: float) -> str:
    s = int(max(0, seconds))
    if s >= 86400:
        return f"{s // 86400}天{(s % 86400) // 3600}小时"
    if s >= 3600:
        return f"{s // 3600}小时{(s % 3600) // 60}分"
    return f"{(s + 59) // 60}分"


def _gate(doc: Any, name: str, world: Mapping[str, Any], now: float,
          cd_key: str = "") -> tuple[bool, str, dict[str, Any]]:
    """原版 context() 统一网关：玩家 → 持有 → CD。"""
    st = state_of(doc, now)
    if not st.get("current"):
        return False, "尚未执掌任何先天至宝，先 #至宝择主 与 #执掌先天至宝。", st
    if not has(doc, name, now, world):
        cur = st.get("current")
        return False, (f"此权柄需执掌【{name}】，当前执掌【{cur}】。\n"
                       f"一人同时只可执掌一件（#执掌先天至宝 名 可切换）。"), st
    if cd_key and cd_left(st, cd_key, now) > 0:
        return False, f"【{cd_key}】尚在冷却，剩余 {fmt_cd(cd_left(st, cd_key, now))}。", st
    return True, "", st


def _mark_cd(st: dict[str, Any], key: str, now: float) -> None:
    if key in CD:
        st["cd"][key] = now + CD[key]


def _authority_of(doc: Any) -> int:
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


# ── 图鉴 / 面板 / 帮助 ─────────────────────────────────────────────────────
def catalog(name: str = "") -> str:
    if name:
        key = ALIASES.get(name, name)
        if key not in CATALOG:
            return f"图鉴中无【{name}】。发送 #至宝图鉴 查看全部 {len(CATALOG)} 件。"
        info = CATALOG[key]
        lines = [f"【{key}】{info['title']}",
                 f"被动：{info['passive']}",
                 f"本体：三维各 +{int(FLAT_ALL * info.get('flat_mult', 1)):,}｜暴击 +{BAO_FLAT:.0%}"]
        auths = info.get("auth") or ()
        lines.append("权柄：" + ("、".join(auths) if auths else "无主动权柄（纯被动）"))
        for a in auths:
            cd = CD.get(ALIASES.get(a, a))
            lines.append(f"  #{a}" + (f"｜CD {fmt_cd(cd)}" if cd else "｜无 CD"))
        return "\n".join(lines)
    lines = [f"【先天至宝图鉴】共 {len(CATALOG)} 件（一人同时只可执掌 1 件）"]
    for i, (n, info) in enumerate(CATALOG.items(), 1):
        lines.append(f"{i:>2}. {n}·{info['title']}｜{info['passive']}")
    lines.append("详情：#至宝图鉴 名｜获取：#至宝择主 名（30 先天道痕）｜规则：#至宝规则")
    return "\n".join(lines)


def panel(doc: Any, world: Mapping[str, Any], now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    cur = st.get("current") or "无"
    info = CATALOG.get(cur, {})
    lines = ["【先天至宝 · 权柄】",
             f"执掌：{cur}" + (f"·{info.get('title', '')}" if info else ""),
             f"被动：{info.get('passive', '—')}",
             f"纳戒：{len(st['owned'])} 件" + ("（" + "、".join(st["owned"][:6]) + "）" if st["owned"] else ""),
             f"太极相：{st['taiji']}｜万劫淬神：{st['temper']} 次｜仙道潜力：{st['potential']}"]
    e = world.get("eternal")
    if isinstance(e, dict):
        lines.append(f"永恒仙图：{e.get('status')}（{e.get('owner_name') or '—'}）")
    dec = world.get("decree")
    if isinstance(dec, dict) and float(dec.get("expires", 0) or 0) > now:
        lines.append(f"人皇敕令：{dec.get('type')} 生效中，剩余 {fmt_cd(dec['expires'] - now)}")
    alive = {k: v for k, v in st["cd"].items() if float(v or 0) > now}
    if alive:
        lines.append("冷却：" + "、".join(f"{k} {fmt_cd(float(v) - now)}" for k, v in list(alive.items())[:8]))
    flags = {k: v for k, v in st["flags"].items() if float(v or 0) > now}
    if flags:
        lines.append("蓄势：" + "、".join(f"{k.replace('待用', '')} {fmt_cd(float(v) - now)}"
                                  for k, v in list(flags.items())[:6]))
    lines.append("切换：#执掌先天至宝 名｜权柄：#至宝帮助｜图鉴：#至宝图鉴")
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "【先天至宝规则】",
        f"· 共 {len(CATALOG)} 件；本体三维各 +{FLAT_ALL:,}（原版 1 亿 ÷1000 折算），暴击 +{BAO_FLAT:.0%}。",
        "· 一人同时只执掌 1 件；全服本体唯一（owners 单键），重复择主只能得 7 日投影（属性为 0）。",
        "· 获取：参与「#观摩灵宝」或「#至宝择主」加入位面坐标上的 24 小时公开争夺；冠军得本体、次席与第三名得七日投影。",
        "· 权柄统一网关：执掌校验 → CD（原版毫秒，本移植秒）→ 落库。",
        "· 蓄势权柄（开天 / 剑阵 / 镇世 / 太初一斩 / 无量护身 / 星辰护界 / 演化诸天 / 阴阳逆转…）"
        f"生效 {GUARD_WINDOW // 3600} 小时，窗口内所有战斗共享增益；原版「待用」无清理也无过期。",
        "· 世界级：#人皇敕令（全服 24h）、#收摄山河（全服投影）、#合成永恒仙图（全服唯一）。"
        "原版无「每纪元 N 次」计数器、无全服公告，只有 CD + flag + 记录数组。",
        "· 永恒仙图：九宝齐聚 + 界核×9 / 宇宙核心×1 / 鸿蒙道火×90，孕育后由器主 #合成永恒仙图 成形。",
        "· #图中巡游 是原版目录孤儿（有 CD key 无指令），本移植不提供。",
        "· 不注册第三轨：执掌至宝不改变境界权威（原版 realmAuthority 不含至宝）。",
    ])


def help_text() -> str:
    return "\n".join([
        "【先天至宝 · 指令】",
        "图鉴 #至宝图鉴 [名]｜状态 #先天至宝｜帮助 #至宝帮助｜规则 #至宝规则",
        "参与公开择主 #至宝择主 [名] / #观摩灵宝 [名]｜执掌 #执掌先天至宝 名｜移交 #移交至宝归属 @人 名",
        "【混沌珠】#混沌复制 物品*数｜#混沌演化 材料*数｜#混沌变幻 物品*数",
        "【太极图】#切换太极 阴/阳｜#阴阳逆转",
        "【盘古幡/诛仙四剑/东皇钟】#开天｜#布诛仙剑阵｜#东皇镇世",
        "【山河社稷图】#收摄山河 灵界裂缝|副本｜#邀请山河投影 @人｜#山河收获",
        "【玲珑塔/混沌钟】#玄黄护道｜#截断岁月",
        "【六道轮回盘/炼妖壶/崆峒印】#执掌轮回 @人｜#炼妖融合 副宠｜"
        "#人皇敕令 修炼|历练｜#借人皇气运修炼",
        "【虚天舟】#邀请登舟 @人｜#同意登舟｜#虚天舟乘员｜#离开虚天舟",
        "【九宝】#太初一斩(太初斩道)｜#无量护身(无量封界)｜#星辰护界(周天列阵)｜"
        "#造化回春｜#万道开炉｜#菩提悟道(菩提顿悟)｜#因果净照(燃灯解因)｜"
        "#万劫淬神｜#演化诸天",
        "【永恒仙图】#合成永恒仙图｜#永恒古史｜#永恒改命 编号",
        f"CD / 蓄势 / 持有状态见 #先天至宝；全部 {len(CD)} 个 CD key 见 #至宝规则",
    ])


# ── 战斗 / 收益出口（供 equipment.aggregate / loadout / 秘境结算调用） ───────
def bonus(doc: Any, now: float | None = None) -> tuple[float, float, float, float]:
    """执掌至宝的固定三维 + 暴击（原版 1 亿 / 全属性 100，÷1000 折算）。"""
    st = state_of(doc, now)
    name = st.get("current") or ""
    if not name or name not in CATALOG:
        return 0.0, 0.0, 0.0, 0.0
    if name in st.get("projection", {}):
        return 0.0, 0.0, 0.0, 0.0       # 投影属性为 0（原版 createInnateTreasureProjection）
    mult = float(CATALOG[name].get("flat_mult", 1))
    return FLAT_ALL * mult, FLAT_ALL * mult, FLAT_ALL * mult, BAO_FLAT * mult


def _merge(dst: dict[str, float], src: Mapping[str, Any] | None,
           skip: tuple[str, ...] = ()) -> None:
    if not src:
        return
    for k, v in src.items():
        if k in skip or isinstance(v, bool):
            continue
        try:
            dst[k] = float(dst.get(k, 0.0)) + float(v)
        except (TypeError, ValueError):
            pass


def combat(doc: Any, now: float | None = None) -> dict[str, Any]:
    """被动 + 蓄势窗口 → 战斗增量；返回 dealt/taken/shield/reflect/lifesteal/revive。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    out: dict[str, float] = {"dealt": 0.0, "taken": 0.0, "shield": 0.0,
                             "reflect": 0.0, "lifesteal": 0.0}
    revive = 0.0
    name = st.get("current") or ""
    if name in CATALOG:
        _merge(out, CATALOG[name].get("combat"))
        if CATALOG[name].get("combat", {}).get("taiji"):
            if st.get("taiji") == "阴":
                out["reflect"] += 0.30
            else:
                out["lifesteal"] += 0.25
    for flag, exp in st.get("flags", {}).items():
        if float(exp or 0) <= now or flag not in FLAGS:
            continue
        spec = FLAGS[flag]
        _merge(out, spec.get("combat"))
        rv = (spec.get("combat") or {}).get("revive")
        if rv:
            try:
                revive = max(revive, float(rv))
            except (TypeError, ValueError):
                pass
    # 炼妖融合：仙宠继承能力折算成小幅汲取
    if int(st.get("inherit", 0) or 0) > 0:
        out["lifesteal"] += min(0.15, 0.05 * int(st["inherit"]))
    res: dict[str, Any] = {k: max(0.0, v) for k, v in out.items()}
    if revive > 0:
        res["revive"] = {"name": "阴阳逆转", "ratio": revive, "pr": 1.0,
                         "msg": "阴阳倒转，死生互换", "used": False}
    return res


def yield_mult(doc: Any, kind: str, now: float | None = None) -> float:
    """收益倍率（1.0 = 无加成）。kind ∈ YIELD_KINDS。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    name = st.get("current") or ""
    total = 0.0
    if name in CATALOG:
        total += float((CATALOG[name].get("yield") or {}).get(kind, 0) or 0)
    for flag, exp in st.get("flags", {}).items():
        if float(exp or 0) > now and flag in FLAGS:
            total += float((FLAGS[flag].get("yield") or {}).get(kind, 0) or 0)
    return max(0.1, 1.0 + total)


def guard_mult(doc: Any, now: float | None = None) -> float:
    """渡劫 / 内景地伤害倍率。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc, now)
    name = st.get("current") or ""
    m = float(CATALOG.get(name, {}).get("guard", 1.0))
    for flag, exp in st.get("flags", {}).items():
        if float(exp or 0) > now and flag in FLAGS and FLAGS[flag].get("guard"):
            m *= float(FLAGS[flag]["guard"])
    # 万劫天碑淬神：每次 -2%，下限 0.6
    m = max(0.4, m - 0.02 * min(20, int(st.get("temper", 0) or 0)))
    return max(0.3, m)


def time_mult(doc: Any, now: float | None = None) -> float:
    """计时行动耗时倍率（闭关 / 穿梭 / 寻宝）。"""
    st = state_of(doc, now)
    name = st.get("current") or ""
    return max(0.3, float(CATALOG.get(name, {}).get("time", 1.0)))


def roll_drop(rng: random.Random) -> dict[str, int] | None:
    """择主物资由位面公开赛事结算，不从普通秘境额外掉落。"""
    return None


# ── 获取 / 执掌 / 移交 ─────────────────────────────────────────────────────
def claim(doc: Any, name: str, inv: Mapping[str, int], world: dict[str, Any],
          now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """单人守护灵挑战（原版 24h 择主之争的简化版）。"""
    key = ALIASES.get(name, name)
    if key not in CONTESTABLE:
        if key == "虚天舟":
            return _no("虚天舟不由择主之争产生（原版需虚天宝库传承），本移植暂不开放该通道。")
        if key == "永恒仙图":
            return _no("永恒仙图由九宝合成：#合成永恒仙图。")
        return _no(f"未知至宝【{name}】，发送 #至宝图鉴 查看名录。")
    have = int(inv.get("先天道痕", 0) or 0)
    if have < CLAIM_COST:
        return _no(f"择主需【先天道痕】×{CLAIM_COST}，现有 {have} 枚（秘境偶得）。")
    realm = max(int(getattr(doc, "realm_index", 0) or 0),
                int(getattr(doc, "physique_index", 0) or 0))
    if realm < CLAIM_REALM:
        return _no(f"择主需第 {CLAIM_REALM + 1} 境以上（当前第 {realm + 1} 境）。")
    # 守护灵难度：auth 越高越稳，最低 0.25 / 最高 0.85（原版 battle 试炼 0.15~0.9）
    auth = _authority_of(doc)
    pr = min(0.85, max(0.25, 0.35 + auth * 0.012))
    delta = {"先天道痕": -CLAIM_COST}
    if rng.random() >= pr:
        delta["灵宝残片"] = 2
        return _ok(f"【择主之争】{key} 守护灵难缠，你惜败（胜率 {pr:.0%}）。\n"
                   f"消耗先天道痕×{CLAIM_COST}，获灵宝残片×2 聊作补偿。", delta)
    st = state_of(doc, now)
    owner = (world.get("owners") or {}).get(key)
    projection = bool(owner and owner.get("uid") != doc.uid)
    if projection:
        st.setdefault("projection", {})[key] = now + PROJECTION_SECONDS
        note = (f"【{key}】本体已在【{owner.get('name') or '他人'}】手中，\n"
                f"你争得七日投影（属性为 0，但可执掌并施用权柄）。")
    else:
        world.setdefault("owners", {})[key] = {
            "uid": doc.uid, "name": doc.name or doc.uid, "at": now,
        }
        if key in st.get("projection", {}):
            st["projection"].pop(key, None)
        note = f"【{key}】认主成功，全服唯一本体归于你。"
    if key not in st["owned"]:
        st["owned"].append(key)
    if not st.get("current"):
        st["current"] = key
    save(doc, st)
    board = world.setdefault("board", [])
    board.append({"uid": doc.uid, "name": doc.name or doc.uid,
                  "treasure": key, "projection": projection, "at": now})
    world["board"] = board[-20:]
    return _ok(f"【择主之争】胜率 {pr:.0%}，一击破阵！\n{note}\n"
               f"（#执掌先天至宝 {key} 可切换执掌）", delta)


def equip(doc: Any, name: str, world: Mapping[str, Any],
          now: float) -> tuple[bool, str, dict[str, int]]:
    key = ALIASES.get(name, name)
    if key not in CATALOG:
        return _no(f"未知至宝【{name}】。")
    st = state_of(doc, now)
    if key not in st["owned"]:
        return _no(f"纳戒中没有【{key}】；先 #至宝择主 {key}（或由他人 #移交至宝归属）。")
    owner = (world.get("owners") or {}).get(key)
    if owner and owner.get("uid") != doc.uid and key not in st.get("projection", {}):
        return _no(f"【{key}】本体已归属【{owner.get('name') or '他人'}】，无法执掌。")
    old = set_equipped_slot(doc, key, st)
    if old == key:
        return _ok(f"【{key}】已在执掌中。\n{CATALOG[key]['passive']}")
    returned = {old: 1} if old and not is_innate_item_name(old) else {}
    note = f"\n原至宝位装备「{old}」已回到纳戒。" if returned else ""
    return _ok(f"执掌【{key}·{CATALOG[key]['title']}】。\n"
               f"被动：{CATALOG[key]['passive']}\n"
               f"权柄：{'、'.join(CATALOG[key].get('auth') or ()) or '无主动权柄'}{note}", returned)


def transfer(doc: Any, target_uid: str, name: str, world: dict[str, Any],
             target_doc: Any | None, now: float) -> tuple[bool, str, dict[str, int]]:
    """全服归属移交（源档 + 目标档 + owners 同步，调用方在同一事务里落库）。"""
    key = ALIASES.get(name, name)
    if key not in CATALOG:
        return _no(f"未知至宝【{name}】。")
    if not target_uid or target_uid == doc.uid:
        return _no("请 @ 一位其他道友作为移交对象。")
    if target_doc is None:
        return _no("对方尚未踏入仙途（#踏入仙途 后才能接掌至宝）。")
    st = state_of(doc, now)
    if key not in st["owned"]:
        return _no(f"你并没有【{key}】。")
    if key in st.get("projection", {}):
        return _no("七日投影不可移交，只能移交本体。")
    owner = (world.get("owners") or {}).get(key)
    if not owner or owner.get("uid") != doc.uid:
        return _no(f"【{key}】本体不在你名下（全服唯一归属已易主）。")
    if key in ETERNAL_COMPONENTS:
        e = world.get("eternal")
        if isinstance(e, dict) and e.get("status") in ("gestating", "formed"):
            return _no("九宝已参与永恒仙图孕育 / 成形，原版禁止此时移交。")
    t_st = state_of(target_doc, now)
    # 目标若只持有同名七日投影，允许「升级为本体」；仅本体重复才拒绝
    if t_st.get("current") == key and key not in t_st.get("projection", {}):
        return _no("对方已在执掌同名至宝。")
    # 至宝位只能有一件；普通装备由调用方按旧槽名退回目标纳戒。
    source_equipment = doc.ext.get("equipment") if isinstance(doc.ext, Mapping) else None
    if isinstance(source_equipment, dict) and _equipment_name(source_equipment.get("至宝")) == key:
        source_equipment.pop("至宝", None)
    target_equipment = target_doc.ext.setdefault("equipment", {})
    if not isinstance(target_equipment, dict):
        target_equipment = target_doc.ext["equipment"] = {}
    old = t_st.get("current") or _equipment_name(target_equipment.get("至宝"))
    old_slot = _equipment_name(target_equipment.get("至宝"))
    if old_slot and is_innate_item_name(old_slot) and old_slot != key:
        t_st["current"] = ""
    target_equipment["至宝"] = key
    st["owned"].remove(key)
    if st.get("current") == key:
        st["current"] = ""
    if key not in t_st["owned"]:
        t_st["owned"].append(key)
    # 目标若先前只持有同名七日投影，接掌本体后应撤掉投影标记（否则属性仍为 0）
    t_st.get("projection", {}).pop(key, None)
    t_st["current"] = key
    # CD 与蓄势随归属迁移（原版 transferInnateTreasureAuthorityState）
    for bucket in ("cd", "flags"):
        t_st[bucket] = dict(st.get(bucket) or {})
        st[bucket] = {}
    save(doc, st)
    save(target_doc, t_st)
    world.setdefault("owners", {})[key] = {
        "uid": target_uid, "name": getattr(target_doc, "name", "") or target_uid,
        "at": now, "previous": doc.uid,
    }
    tail = f"；对方原执掌【{old}】已退回纳戒" if old else ""
    return _ok(f"【{key}】烙印散去，认主于【{getattr(target_doc, 'name', '') or target_uid}】{tail}。\n"
               f"CD 与蓄势状态一并迁移。")


# ── 权柄：蓄势类 ───────────────────────────────────────────────────────────
def prepare(doc: Any, world: Mapping[str, Any], auth: str,
            now: float) -> tuple[bool, str, dict[str, int]]:
    key = ALIASES.get(auth, auth)
    flag = AUTH_FLAG.get(key)
    if not flag:
        return _no(f"【{key}】不是蓄势权柄。")
    treasure = FLAGS[flag]["treasure"]
    ok, err, st = _gate(doc, treasure, world, now, FLAGS[flag]["cd"])
    if not ok:
        return _no(err)
    st["flags"][flag] = now + GUARD_WINDOW
    _mark_cd(st, FLAGS[flag]["cd"], now)
    save(doc, st)
    return _ok(f"【{key}】{FLAGS[flag]['note']}\n"
               f"蓄势 {GUARD_WINDOW // 3600} 小时｜CD {fmt_cd(CD[FLAGS[flag]['cd']])}")


# ── 权柄：物品类（混沌珠） ─────────────────────────────────────────────────
def _parse_item(arg: str) -> tuple[str, int]:
    raw = (arg or "").strip().replace("*", "＊").replace("×", "＊")
    if "＊" not in raw:
        name = raw.strip()
        return name, 1
    name, _, num = raw.rpartition("＊")
    try:
        return name.strip(), max(1, min(999, int(num.strip())))
    except ValueError:
        return name.strip(), 1


def chaos_copy(doc: Any, inv: Mapping[str, int], world: Mapping[str, Any],
               arg: str, now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "混沌珠", world, now, "混沌复制")
    if not ok:
        return _no(err)
    name, num = _parse_item(arg)
    if not name:
        return _no("格式：#混沌复制 物品*数量")
    have = int(inv.get(name, 0) or 0)
    if have <= 0:
        return _no(f"纳戒中没有【{name}】。")
    if name in SIGILS or name in CATALOG:
        return _no("至宝与择主信物不可复制（全服唯一 / 不可创造）。")
    cap = 999
    add = min(num, max(0, cap - have))
    if add <= 0:
        return _no(f"【{name}】已达复制上限 {cap}。")
    _mark_cd(st, "混沌复制", now)
    save(doc, st)
    return _ok(f"【混沌复制】{name} ×{have} → ×{have + add}（+{add}）。", {name: add})


MATERIAL_RANKS = ("凡材", "灵材", "仙材", "神材", "道材", "先天材")


def chaos_evolve(doc: Any, inv: Mapping[str, int], world: Mapping[str, Any],
                 arg: str, now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "混沌珠", world, now, "混沌演化")
    if not ok:
        return _no(err)
    name, num = _parse_item(arg)
    if not name or int(inv.get(name, 0) or 0) < num:
        return _no(f"格式：#混沌演化 材料*数量（需持有足量【{name}】）")
    delta: dict[str, int] = {name: -num}
    up = 0
    for _ in range(num):
        if rng.random() < 0.5:
            up += 1
    if up:
        # 本移植无跨表品阶链，统一折算成高一阶「先天道痕」等通用资源
        delta["先天道痕"] = up
        msg = f"【混沌演化】投入 {name}×{num}，{up} 份蜕变为先天道痕。"
    else:
        delta["灵宝残片"] = 1
        msg = f"【混沌演化】{num} 份材料尽数归于混沌，仅余灵宝残片×1。"
    _mark_cd(st, "混沌演化", now)
    save(doc, st)
    return _ok(msg, delta)


def chaos_transform(doc: Any, inv: Mapping[str, int], world: Mapping[str, Any],
                    arg: str, now: float, rng: random.Random,
                    item_lookup: Callable[[str], Mapping[str, Any] | None] | None = None
                    ) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "混沌珠", world, now, "混沌变幻")
    if not ok:
        return _no(err)
    name, num = _parse_item(arg)
    if not name or int(inv.get(name, 0) or 0) < num:
        return _no(f"格式：#混沌变幻 物品*数量（需持有足量【{name}】）")
    if name in SIGILS or name in CATALOG:
        return _no("至宝与择主信物不可变幻。")
    pool = [k for k in SIGILS if k not in (name, "先天道痕")]
    if not pool:
        pool = ["灵宝残片"]
    target = rng.choice(pool)
    _mark_cd(st, "混沌变幻", now)
    save(doc, st)
    return _ok(f"【混沌变幻】{name}×{num} 化作 {target}×{num}（同阶随机变换）。",
               {name: -num, target: num})


def fuse_pet(doc: Any, inv: Mapping[str, int], world: Mapping[str, Any],
             arg: str, now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "炼妖壶", world, now, "炼妖融合")
    if not ok:
        return _no(err)
    name = (arg or "").strip()
    pet = doc.ext.get("pet") if isinstance(doc.ext, Mapping) else None
    if not isinstance(pet, dict) or not pet.get("name"):
        return _no("尚未育有主宠，无法炼妖融合。")
    if not name:
        return _no("格式：#炼妖融合 副宠名（消耗副宠，继承其 50% 能力）")
    if int(inv.get(name, 0) or 0) <= 0:
        return _no(f"纳戒中没有副宠【{name}】。")
    if int(st.get("inherit", 0) or 0) >= 5:
        return _no("主宠已融合 5 次（本移植上限，原版每主宠限 1 次）。")
    st["inherit"] = int(st.get("inherit", 0) or 0) + 1
    _mark_cd(st, "炼妖融合", now)
    save(doc, st)
    return _ok(f"【炼妖融合】{pet.get('name')} 继承【{name}】五成能力，"
               f"汲取 +{min(15, 5 * st['inherit'])}%。", {name: -1})


# ── 权柄：世界级 ───────────────────────────────────────────────────────────
def capture_landscape(doc: Any, world: dict[str, Any], arg: str,
                      now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "山河社稷图", world, now, "收摄山河")
    if not ok:
        return _no(err)
    src = "副本" if "副本" in (arg or "") else "灵界裂缝"
    auth = _authority_of(doc)
    base = max(1, auth) * (50_000 if src == "灵界裂缝" else 30_000)
    items = world.setdefault("landscapes", [])
    items[:] = [x for x in items if x.get("owner") != doc.uid]
    items.append({"owner": doc.uid, "name": doc.name or doc.uid, "src": src,
                  "created": now, "expires": now + 6 * 3600,
                  "last": now, "hourly": {"exp": base, "stones": base // 2},
                  "invited": list(st.get("landscape_invite") or [])})
    _mark_cd(st, "收摄山河", now)
    save(doc, st)
    return _ok(f"【收摄山河】{src} 投影展开 6 小时，每小时修为 +{base:,} / 灵石 +{base // 2:,}。\n"
               f"#山河收获 领取累计产出（受邀者共享）。")


def invite_landscape(doc: Any, world: dict[str, Any], target: str,
                     now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "山河社稷图", world, now)
    if not ok:
        return _no(err)
    if not target:
        return _no("请 @ 一位道友共享山河投影。")
    if len(st.get("landscape_invite") or []) >= 2:
        return _no("山河投影最多邀请 2 人（原版 ≤2）。")
    st.setdefault("landscape_invite", []).append(target)
    save(doc, st)
    for x in world.get("landscapes", []):
        if x.get("owner") == doc.uid:
            x["invited"] = list(st["landscape_invite"])
    return _ok(f"已邀请 {target} 共览山河（当前 {len(st['landscape_invite'])}/2 人）。")


def landscape_harvest(doc: Any, world: dict[str, Any],
                      now: float) -> tuple[bool, str, dict[str, int]]:
    """原版是 cron 每小时自动结算，本移植改显式领取（无定时循环）。"""
    st = state_of(doc, now)
    mine = None
    for x in world.get("landscapes", []):
        if x.get("owner") == doc.uid:
            mine = x
            break
    if not mine:
        # 受邀者也可领（共享完整收益）
        for x in world.get("landscapes", []):
            if doc.uid in (x.get("invited") or []):
                mine = x
                break
    if not mine:
        return _no("当前没有你可领取的山河投影（先 #收摄山河 或让器主 #邀请山河投影）。")
    end = min(float(mine.get("expires", now)), now)
    hours = max(0, int((end - float(mine.get("last", mine.get("created", now)))) // 3600))
    mine["last"] = mine["last"] + hours * 3600
    if hours <= 0:
        return _no("投影尚未满一个时辰，稍后再来。")
    exp = int(mine["hourly"]["exp"]) * hours
    stones = int(mine["hourly"]["stones"]) * hours
    doc.exp = int(getattr(doc, "exp", 0) or 0) + exp
    doc.stones = int(getattr(doc, "stones", 0) or 0) + stones
    return _ok(f"【山河收获】{hours} 个时辰：修为 +{exp:,}｜灵石 +{stones:,}。")


def decree(doc: Any, world: dict[str, Any], arg: str,
           now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "崆峒印", world, now, "人皇敕令")
    if not ok:
        return _no(err)
    kind = "历练" if "历练" in (arg or "") else "修炼"
    world["decree"] = {"owner": doc.uid, "name": doc.name or doc.uid, "type": kind,
                       "started": now, "expires": now + DECREE_SECONDS, "borrowed": []}
    _mark_cd(st, "人皇敕令", now)
    save(doc, st)
    return _ok(f"【人皇敕令 · {kind}】全服位面 {DECREE_SECONDS // 3600} 小时生效：\n"
               f"修炼 / 悟道 +50% 并附带 35% 血气，或副本收益 +100%。\n"
               f"道友可 #借人皇气运修炼 领 1200 分钟闭关收益（每人每敕令 1 次）。")


def decree_active(world: Mapping[str, Any], now: float) -> bool:
    d = world.get("decree")
    return isinstance(d, dict) and float(d.get("expires", 0) or 0) > now


def borrow_decree(doc: Any, world: dict[str, Any],
                  now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "崆峒印", world, now)
    if not ok:
        # 原版「借」不要求自己执掌崆峒印，只要有生效敕令；这里放宽网关
        st = state_of(doc, now)
    d = world.get("decree")
    if not decree_active(world, now):
        return _no("当前没有生效的人皇敕令。")
    if d.get("type") != "修炼":
        return _no("当前是【历练】敕令，只有【修炼】敕令可借气运。")
    if doc.uid in (d.get("borrowed") or []):
        return _no("本次敕令的气运你已领过（每人每敕令 1 次）。")
    d.setdefault("borrowed", []).append(doc.uid)
    auth = max(1, _authority_of(doc))
    gain = 1200 * 60 * auth * 1.5
    exp = int(gain)
    doc.exp = int(getattr(doc, "exp", 0) or 0) + exp
    doc.stones = int(getattr(doc, "stones", 0) or 0) + int(exp * 0.35)
    return _ok(f"【借人皇气运修炼】1200 分钟闭关收益：修为 +{exp:,}｜灵石 +{int(exp * 0.35):,}。")


def protect_reincarnation(doc: Any, world: Mapping[str, Any], target: str,
                          now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "六道轮回盘", world, now, "执掌轮回")
    if not ok:
        return _no(err)
    who = target or doc.uid
    st.setdefault("reincarnation_protect", {})[who] = now + 24 * 3600
    _mark_cd(st, "执掌轮回", now)
    save(doc, st)
    return _ok(f"【执掌轮回】已为 {who} 加护 24 小时，期间免疫强制寿元轮回。")


def reincarnation_protected(doc: Any, uid: str, now: float) -> bool:
    st = ensure(doc)
    return float((st.get("reincarnation_protect") or {}).get(uid, 0) or 0) > now


def cut_time(doc: Any, world: Mapping[str, Any],
             now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "混沌钟", world, now, "截断岁月")
    if not ok:
        return _no(err)
    if str(getattr(doc, "state", "")) != "闭关中":
        return _no("当前没有可截断的计时行动（需正在 #闭关）。")
    _mark_cd(st, "截断岁月", now)
    save(doc, st)
    # 把闭关起点前推 120 分钟：结算时按实际 elapsed 计算，等价于「立即拉到结算时刻」
    doc.state_start = min(float(getattr(doc, "state_start", now) or now), now - 120 * 60)
    return _ok("【截断岁月】岁月长河被一刀截断，闭关行动即刻抵达结算时刻。\n"
               "发送 #出关 领取 120 分钟收益。")


# ── 权柄：虚天舟（轻量社交，原版 60 秒 redis 邀请改为直接入列） ─────────────
def ship_invite(doc: Any, world: Mapping[str, Any], target: str,
                now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "虚天舟", world, now)
    if not ok:
        return _no(err)
    if not target:
        return _no("请 @ 一位道友登舟。")
    if len(st.get("ship") or []) >= 3:
        return _no("虚天舟乘员已满 3 人（#虚天舟乘员 查看）。")
    if target in st["ship"]:
        return _no("对方已在舟上。")
    st["ship"].append(target)
    save(doc, st)
    return _ok(f"【邀请登舟】{target} 已登舟（{len(st['ship'])}/3）；乘员共享穿梭缩时。")


def ship_accept(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc, now)
    st["ship_passenger"] = now + 6 * 3600
    save(doc, st)
    return _ok("【同意登舟】你已就座，6 小时内穿梭耗时 -40%（原版虚天舟被动）。")


def ship_panel(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc, now)
    members = st.get("ship") or []
    return _ok("【虚天舟乘员】" + ("、".join(members) if members else "空舟")
               + f"（{len(members)}/3）\n#离开虚天舟 可离舟。")


def ship_leave(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc, now)
    st["ship"] = []
    st["ship_passenger"] = 0
    save(doc, st)
    return _ok("【离开虚天舟】舟上空无一人，虚天之主独行诸界。")


# ── 权柄：太极 / 立即结算类 ────────────────────────────────────────────────
def switch_taiji(doc: Any, world: Mapping[str, Any], arg: str,
                 now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "太极图", world, now)
    if not ok:
        return _no(err)
    phase = "阳" if "阳" in (arg or "") else "阴"
    st["taiji"] = phase
    save(doc, st)
    return _ok(f"【切换太极 · {phase}相】" +
               ("吸血 +25%（阳相）" if phase == "阳" else "化伤反击 +30%（阴相）") +
               "｜原版此指令无 CD。")


def creation_spring(doc: Any, world: Mapping[str, Any],
                    now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "造化仙池", world, now, "造化回春")
    if not ok:
        return _no(err)
    try:
        from . import zhengdao as _dz
        _dz.clear(doc, "造化回春", now=now)
    except Exception:
        pass
    try:
        from . import yuanshen as _ys
        y = _ys.ensure(doc)
        y["cur"] = int(y.get("max", 0) or 0)
        _ys.save(doc, y)
    except Exception:
        pass
    from . import life_source
    restored = life_source.restore_to_max(doc)
    st["potential"] = int(st.get("potential", 0) or 0) + 500
    _mark_cd(st, "造化回春", now)
    save(doc, st)
    return _ok(f"【造化回春】生命本源复满至 {restored:g}、道伤尽祛、元神回满，仙道潜力 +500（现 {st['potential']}）。")


def bodhi(doc: Any, world: Mapping[str, Any],
          now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "菩提祖树", world, now, "菩提悟道")
    if not ok:
        return _no(err)
    auth = max(1, _authority_of(doc))
    exp = 72 * 60 * auth * 2
    doc.exp = int(getattr(doc, "exp", 0) or 0) + exp
    _mark_cd(st, "菩提悟道", now)
    save(doc, st)
    return _ok(f"【菩提悟道】72 时辰闭关顿悟（收益 ×2）：修为 +{exp:,}。")


def cleanse_causality(doc: Any, world: Mapping[str, Any],
                      now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "因果神灯", world, now, "因果净照")
    if not ok:
        return _no(err)
    st["debt_cleanse"] = int(st.get("debt_cleanse", 0) or 0) + 40
    _mark_cd(st, "因果净照", now)
    save(doc, st)
    return _ok(f"【因果净照】燃灯解因，消减 40 点因果债（累计 {st['debt_cleanse']}）。")


def temper_spirit(doc: Any, world: Mapping[str, Any],
                  now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "万劫天碑", world, now, "万劫淬神")
    if not ok:
        return _no(err)
    try:
        from . import yuanshen as _ys
        y = _ys.ensure(doc)
        cur_max = int(y.get("max", 0) or 0)
        gain = max(1, int(cur_max * 0.10))
        y["max"] = cur_max + gain
        y["cur"] = min(int(y["max"]), int(y.get("cur", 0) or 0) + max(1, int(y["max"] * 0.5)))
        _ys.save(doc, y)
        txt = f"元神上限 +{gain:,}（现 {y['max']:,}），回 50% 元神"
    except Exception:
        txt = "元神尚未凝练，权柄暂存为淬神层数"
    st["temper"] = int(st.get("temper", 0) or 0) + 1
    _mark_cd(st, "万劫淬神", now)
    save(doc, st)
    return _ok(f"【万劫淬神】第 {st['temper']} 次：{txt}｜渡劫伤害再 -2%（原版次数不限）。")


# ── 永恒仙图 ───────────────────────────────────────────────────────────────
def synthesize_eternal(doc: Any, inv: Mapping[str, int], world: dict[str, Any],
                       now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc, now)
    e = world.get("eternal")
    if isinstance(e, dict) and e.get("status") == "gestating":
        if e.get("owner") != doc.uid:
            return _no("永恒仙图正在他人手中孕育。")
        if now - float(e.get("started", 0)) < ETERNAL_GESTATION:
            return _ok("【永恒仙图】仍在孕育（原版 9000 世界年，本移植折算为孕育进度）。")
        e["status"] = "formed"
        e["formed"] = now
        world["eternal"] = e
        if "永恒仙图" not in st["owned"]:
            st["owned"].append("永恒仙图")
        st["current"] = "永恒仙图"
        save(doc, st)
        return _ok("【永恒仙图 · 成形】九宝权能归一，全服唯一大道至宝归于你。\n"
                   "九宝原有 CD 与权柄全部保留，三维固定加成 ×10。")
    if isinstance(e, dict) and e.get("status") == "formed":
        return _no("永恒仙图已成形（全服唯一），不可重复合成。")
    missing = [n for n in ETERNAL_COMPONENTS if n not in st["owned"]]
    if missing:
        return _no("九宝未齐，尚缺：" + "、".join(missing))
    shards = int(inv.get("灵宝残片", 0) or 0)
    need = dict(ETERNAL_COST)
    need["鸿蒙道火"] = max(0, need["鸿蒙道火"] - shards // 2)
    lack = [f"{k}×{v - int(inv.get(k, 0) or 0)}" for k, v in need.items()
            if int(inv.get(k, 0) or 0) < v]
    if lack:
        return _no("合成材料不足：" + "、".join(lack) + "（灵宝残片可 2:1 抵扣鸿蒙道火）")
    delta = {k: -v for k, v in need.items() if v > 0}
    world["eternal"] = {"owner": doc.uid, "name": doc.name or doc.uid,
                        "status": "gestating", "started": now}
    save(doc, st)
    return _ok("【合成永恒仙图】九宝归位、界核×9 / 宇宙核心×1 / 鸿蒙道火入炉，\n"
               "仙图开始孕育；再次发送 #合成永恒仙图 令其成形。", delta)


def eternal_history(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc, now)
    rec = st.get("history") or []
    if not rec:
        return _ok("【永恒古史】尚无「身灭道消」记录。\n"
                   "（本移植在道伤满层时留档，见 #永恒改命 编号）")
    lines = ["【永恒古史】可改写记录"]
    for i, r in enumerate(rec[-10:], 1):
        lines.append(f"{i}. {r.get('reason') or '身灭道消'}｜{r.get('state')}")
    lines.append("#永恒改命 编号 可回滚该快照")
    return _ok("\n".join(lines))


def note_erasure(doc: Any, reason: str, now: float) -> None:
    """供渡劫失败等处调用：留一份可改写快照（原版 ≤10 条 slice(-10)）。"""
    st = ensure(doc)
    rec = list(st.get("history") or [])
    rec.append({"id": len(rec) + 1, "reason": reason, "state": "erased", "at": now,
                "snapshot": {"realm_index": int(getattr(doc, "realm_index", 0) or 0),
                             "physique_index": int(getattr(doc, "physique_index", 0) or 0),
                             "exp": int(getattr(doc, "exp", 0) or 0)}})
    st["history"] = rec[-10:]
    save(doc, st)


def eternal_rewrite(doc: Any, world: Mapping[str, Any], arg: str,
                    now: float) -> tuple[bool, str, dict[str, int]]:
    ok, err, st = _gate(doc, "永恒仙图", world, now, "永恒改命")
    if not ok:
        return _no(err)
    try:
        idx = max(1, int((arg or "1").strip()))
    except ValueError:
        return _no("格式：#永恒改命 编号（见 #永恒古史）")
    rec = list(st.get("history") or [])
    view = rec[-10:]
    if idx > len(view) or view[idx - 1].get("state") != "erased":
        return _no("该记录不存在或已被改写（每条仅可改写 1 次）。")
    snap = view[idx - 1].get("snapshot") or {}
    doc.realm_index = int(snap.get("realm_index", doc.realm_index) or doc.realm_index)
    doc.physique_index = int(snap.get("physique_index", doc.physique_index) or doc.physique_index)
    doc.exp = int(snap.get("exp", doc.exp) or doc.exp)
    view[idx - 1]["state"] = "rewritten"
    view[idx - 1]["at"] = now
    st["history"] = rec[-10:]
    _mark_cd(st, "永恒改命", now)
    save(doc, st)
    return _ok("【永恒改命】古史一页被改写，境界与修为回滚至身灭道消之前。")
