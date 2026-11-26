"""岁云灵根（W8-B4）：唯一造化觉醒 / 五阶段自动晋阶 / 月华经济 / 岁云之力 /
霜月·岁云套装 / 四战技 / 无上天阙枝十三权柄 / 岁云剑宫。

原版依据：`apps/User/Suiyun.js`（16 条 reg）+ `apps/User/SuiyunAuthority.js`（9 解封 + 7 技）
+ `model/suiyun.js`（SUIYUN_STAGES 五阶表 / getSuiyunEffects）+ `model/suiyunCombat.js`
+ `model/exclusiveEquipmentSets.js` / `model/equipmentStats.js`（套装倍率）
+ `resources/data/item/{特殊装备列表, 道具列表, 功法列表, 仙宠列表, 灵根列表}.json`
+ `resources/data/势力商店/岁云剑宫商店.json`（22 条）。

本移植的**物品/功法/仙宠/灵根/套装数据表已 1:1 存在**，本模块只补逻辑层与状态层，
状态全落 `doc.ext["suiyun"]`，全服唯一登记表挂 `calamity_state["suiyun_registry"]`，
**不动数据库（仍 v17）**。

shortcut（与原版的差异，均为折算或裁剪，不是遗漏未察觉）：
1. 原版觉醒后直接把 `player.灵根` 换成岁云灵根、`天资等级='岁云'`、`势力='岁云剑宫'`；
   本移植双轨灵根是核心成长线，覆盖会摧毁既有养成 → **不覆盖 `ext["linggen"]`**，
   只在 `build_fighter` 把 `tags["linggen_name"]` 临时指向岁云阶段名，以复用
   `opening.suiyun_verdict` 已实装的「同境裁决」。灵根表的 eff/法球倍率/生命本源
   改由本模块 `effects()` 提供等价数值。
2. 原版晋阶用 `getRealmAuthorityLevel(player)`（0-21 档，门槛 0/10/12/16/20）；
   本移植 `authority.authority_21(doc)` 恰好同为 0-21 档，直接对齐。
   **岁云自身不注册 `register_track`**：它是「境界驱动的被动轨」，若注册会让
   `authority_21 → authority_of → extra_levels → suiyun` 自举成环。
3. 原版残念掉率 0.00001（往世星海），本移植无「往世星海」地图 → 新增 `#感应岁云`
   作为觉醒前入口（1 小时 CD、3% 掉落、按纳戒与全服登记表判重）。
4. 原版全服唯一登记表是文件级 `data/suiyun_unique.*.json`；本移植复用既有
   `calamity_state` 单例（与 W8-A4 鱼王同做法），不新建表。
5. 数值折算：`#剑宫兑换` 的源石价 ÷100 折算为本移植灵石；`#创世` 的 +50000% 三维
   折算为套装层 +5.0；霜剑入月「9 敌 9 击每击 25 倍」折算为单体增伤乘区；
   月华炼化的「真实战斗」折算为一次按权柄判定的本源炼化（24h 禁术调息）。
6. 不移植：月华天宫的小世界时间流速 UI（按 `ext["xiaoshijie"].level` 取流速档）、
   天骄待处置/搜魂禁术链、组队鱼王、跨位面赠送、大道至宝改名、剑宫每日宝库任务、
   原版 13 权柄里仅文档存在而源码未实装的部分。九项解封供物按本移植物品表取可用项。
7. 套装倍率：原版霜月套套装层 ×10（`bonus += 9`）、岁云套 ×20（`bonus += 19`），
   且岁云套开场「全伤害 +50% / 全类型减免 +30%」；本移植前者接 `equipment.aggregate`，
   后者折算进 `combat()` 的 `dmg_dealt_mult` / `dmg_taken_mult`（PvP/PvE 同源）。
8. `#岁云更改` 原版可改时代/至宝线索/命格/天资/灵根；本移植无时代改写与至宝线索系统，
   收敛为「称号 / 道韵 / 命格」三种可安全写入的更改，消费点照旧 5/10/20 岁云之力。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping, Sequence
from typing import Any

# ---------------------------------------------------------------- 五阶段（model/suiyun.js:47-53）

STAGES: tuple[dict[str, Any], ...] = (
    {"name": "月华之体", "realm": 0,  "life": 200,   "cap": 600,   "wudao": .20,
     "trib": .20, "loot": 1,  "eff": 20,    "orb": 1.5,   "attrs": 2,    "dealt": 1.05},
    {"name": "月华似剑", "realm": 10, "life": 600,   "cap": 1800,  "wudao": .20,
     "trib": .30, "loot": 5,  "eff": 100,   "orb": 3,     "attrs": 10,   "dealt": 1.15},
    {"name": "霜月剑尊", "realm": 12, "life": 1800,  "cap": 5400,  "wudao": .20,
     "trib": .50, "loot": 10, "eff": 300,   "orb": 10,    "attrs": 50,   "dealt": 1.35},
    {"name": "岁云化身", "realm": 16, "life": 5400,  "cap": 15000, "wudao": .45,
     "trib": .75, "loot": 10, "eff": 3000,  "orb": 100,   "attrs": 500,  "dealt": 1.70},
    {"name": "岁云剑尊", "realm": 20, "life": 15000, "cap": 15000, "wudao": .45,
     "trib": .85, "loot": 10, "eff": 30000, "orb": 1000,  "attrs": 5000, "dealt": 2.00},
)

FROST_SET = ("霜月剑", "霜月剑袍", "霜月之莲")
FINAL_SET = ("岁云剑", "岁云袍", "云月之莲")
TREASURE = "无上天阙枝"
REMNANT = "岁云的残念"
GONGFA = ("月华炼天功", "岁云化月")
PET = "岁云剑灵"

HOUR = 3600
DAY = 24 * HOUR
SEEK_CD = HOUR
SEEK_CHANCE = 0.03
CULTIVATE_CD = DAY
REFINE_CD = DAY
POWER_HOUR = 0.5           # 第 4 阶起每现实小时基础岁云之力（× 小世界流速档）
WORLD_RATIO = (1, 2, 3, 4, 8)
LOTUS_PER_MOON = 200_000   # model/suiyun.js:15 每累计 1 点炼化月华 → 三维各 +20 万
PALACE_EXP_PER_HOUR = 50   # 原版「仙道潜力 +50/小时」折算为修为基数

# ---------------------------------------------------------------- 奖池 / 供物 / 权柄

YEAR_POOL: tuple[str, ...] = (
    "潜力丹", "普通封灵符", "心神丹", "仙泪绿金", "太阳天金", "太阴真水",
    "世界石", "龙髓", "百草液", "九彩神金", "万物母气", "仙坟土", "仙泉之眼",
)
NINE_SECRETS = ("临字秘", "兵字秘", "斗字秘", "者字秘", "皆字秘",
                "数字秘", "组字秘", "前字秘", "行字秘")
TEN_XIONG = ("真龙宝术", "九叶剑草宝术")
HIDDEN_POOL = ("超越宝盒", "群星圣药", "岁月的馈赠", "大衍悟道丹", "悟道古茶叶")
DUNGEON_POOL = ("群星圣药", "岁月的馈赠", "潜力丹", "大衍悟道丹", "悟道古茶叶")

AUTHORITIES: tuple[str, ...] = (
    "梦幻", "真实", "理想", "无极", "大地", "海洋", "天空",
    "七夜的许愿星", "创世", "无上", "月宫", "霜华", "岁云降世",
)
# (权柄名, 供物, 数量, 说明)
SEALS: tuple[tuple[str, str, int, str], ...] = (
    ("梦幻", "如梦的加持", 20, "借来至宝权柄一次（24h）"),
    ("真实", "地心红莲", 1, "梦幻投影不再反噬"),
    ("理想", "雷帝宝术", 1, "天骄讨伐门槛忽略"),
    ("无极", "万物母气", 1, "功法百分百领悟"),
    ("大地", "仙坟土", 1, "断崖之剑：下一场首击三倍"),
    ("海洋", "仙泉之眼", 1, "根源波动：修复本源（48h）"),
    ("天空", "九彩神金", 1, "探索耗时缩短"),
    ("七夜的许愿星", "群星圣药", 10, "祈愿渡劫：渡劫承伤减半"),
    ("创世", "界核", 200, "创世：铸一级装备，三维 +500%"),
)
SEAL_BY_NAME = {s[0]: s for s in SEALS}

REFINE_TARGETS: dict[str, tuple[int, float]] = {
    "玩家": (300, .72), "天骄": (280, .60), "灾厄": (260, .55),
    "魔主": (300, .45), "邪祟": (220, .75),
}
GIFT_SLOTS = 3
SHOP_PRICE_DIV = 100       # 源石 → 灵石折算，见模块头 shortcut 5
CREATION_COST = 10
CREATE_BLACKLIST_KEYS = ("全服唯一", "全时间线唯一", "不可创造", "不可支取", "岁云专属", "大道至宝本体")
NO_CREATE_NAMES = {REMNANT, TREASURE, *FROST_SET, *FINAL_SET, PET, *GONGFA}

# ---------------------------------------------------------------- 状态


def _defaults(now: float = 0.0) -> dict[str, Any]:
    return {
        "version": 1,
        "awake": True,
        "awake_at": now,
        "stage": 1,
        "moonlight": 0,
        "refined": 0,
        "lotus_moon": 0,
        "refine_log": [],
        "last_seek": 0.0,
        "last_cultivate": 0.0,
        "last_years": 0.0,
        "last_refine": 0.0,
        "power": 0.0,
        "power_at": 0.0,
        "palace_at": now,
        "claimed": [],
        "pending_soul": "",
        "title": "",
        "daoyun": "",
        "trib_shield": False,
        "genesis": False,
        "seals": {},
        "cd": {},
        "dream": {},
        "blessed_by": "",
    }


def state_of(doc: Any) -> dict[str, Any] | None:
    st = (getattr(doc, "ext", {}) or {}).get("suiyun")
    return dict(st) if isinstance(st, dict) and st.get("awake") else None


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["suiyun"] = dict(st)


def stage_of(doc: Any) -> int:
    st = state_of(doc)
    return max(0, min(5, int(st.get("stage", 1) or 1))) if st else 0


def stage_name(doc: Any) -> str:
    n = stage_of(doc)
    return STAGES[n - 1]["name"] if n else ""


def _spec(doc: Any) -> dict[str, Any]:
    return STAGES[max(0, stage_of(doc) - 1)]


def _st(doc: Any) -> dict[str, Any]:
    return state_of(doc) or _defaults()


def _save(doc: Any, st: dict[str, Any]) -> None:
    set_state(doc, st)


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, delta or {}


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


def _need_awake(doc: Any) -> str | None:
    if stage_of(doc) <= 0:
        return "尚未承接岁云传承：先「#感应岁云」寻得【岁云的残念】，再「#消耗岁云的残念」。"
    return None


def _need_stage(doc: Any, gate: int) -> str | None:
    if stage_of(doc) <= 0:
        return _need_awake(doc)
    if stage_of(doc) < gate:
        return f"岁云传承未至【{STAGES[gate - 1]['name']}】（当前 {stage_name(doc)}），境界达标会自动连升。"
    return None


# ---------------------------------------------------------------- 对外只读接口（供其它模块消费）


def effects(doc: Any) -> dict[str, Any]:
    """getSuiyunEffects 的等价集合（model/suiyun.js:101-113）。"""
    stage = stage_of(doc)
    if stage <= 0:
        return {"stage": 0, "wudao": 0.0, "trib": 0.0, "loot_mult": 1,
                "luck": 0.0, "free_entry": False, "spirit_immune": False,
                "madoka": False, "revives": 0}
    s = _spec(doc)
    return {
        "stage": stage, "wudao": s["wudao"], "trib": s["trib"],
        "loot_mult": int(s["loot"]), "luck": 1.0,
        "free_entry": stage >= 3,          # model/suiyun.js:87-99 秘境免费
        "spirit_immune": True,             # 绝灵链：豁免寿元压制与纳戒物品侵蚀
        "madoka": stage == 5,
        "revives": 3 if stage >= 3 else 0,  # 白云苍狗
    }


def wudao_bonus(doc: Any) -> float:
    return float(effects(doc)["wudao"])


def loot_mult(doc: Any) -> int:
    return int(effects(doc)["loot_mult"])


def free_entry(doc: Any) -> bool:
    return bool(effects(doc)["free_entry"])


def trib_reduction(doc: Any) -> float:
    """渡劫减伤：阶段值 + 七夜祈愿 50%（上限 0.95）。"""
    st = _st(doc)
    red = float(effects(doc)["trib"])
    if st.get("trib_shield"):
        red = min(0.95, red + 0.50)
    return red


def set_bonus(doc: Any) -> tuple[float, list[str]]:
    """岁云专属套装的套装层倍率（equipmentStats.js:152-158）。返回 (倍率增量, 说明)。"""
    stage = stage_of(doc)
    if stage <= 0:
        return 0.0, []
    eq = doc.ext.get("equipment") or {}
    worn = {eq.get(k) for k in ("武器", "护具", "法宝")}
    bonus, lines = 0.0, []
    if stage >= 3 and worn == set(FROST_SET):
        bonus += 9.0
        lines.append("霜月剑尊套×3（总倍率 ×10）")
    if stage >= 5 and worn == set(FINAL_SET):
        bonus += 19.0
        lines.append("岁云剑尊套×3（总倍率 ×20）")
    st = _st(doc)
    if st.get("genesis"):
        bonus += 5.0
        lines.append("【创世】铸器三维 ×6")
    return bonus, lines


def lotus_flat(doc: Any) -> float:
    """云月之莲：每累计炼化 1 点月华，攻/防/血各 +20 万固定加算（不被套装倍率放大）。"""
    if stage_of(doc) <= 0:
        return 0.0
    eq = doc.ext.get("equipment") or {}
    if eq.get("法宝") != "云月之莲":
        return 0.0
    return max(0, int(_st(doc).get("lotus_moon", 0) or 0)) * LOTUS_PER_MOON


def combat(doc: Any, now: float | None = None) -> dict[str, float]:
    """四战技 + 岁云套开场 + 权柄时效，全部折算进 build_fighter 的 effects。

    now 可注入（自检用假时间戳）；运行时不传即取真实时间。
    """
    stage = stage_of(doc)
    blessing = doc.ext.get("suiyun_blessing")
    if stage <= 0 and not blessing:
        return {}
    s = STAGES[max(1, stage) - 1]
    dealt = float(s["dealt"]) if stage else 1.15
    taken = 1.0 - min(0.60, float(s["trib"]) * 0.4) if stage else 0.92
    if stage >= 5 and set((doc.ext.get("equipment") or {}).get(k) for k in ("武器", "护具", "法宝")) == set(FINAL_SET):
        dealt *= 1.5          # 岁云套开场全伤害 +50%
        taken *= 0.7          # 全类型减免 +30%
    st = _st(doc)
    now = float(time.time() if now is None else now)
    if st.get("dream", {}).get("expires", 0) > now:
        dealt *= 1.5
    cd = st.get("cd") or {}
    if float(cd.get("断崖之剑", 0) or 0) > now:
        dealt *= 1.3
    if float(cd.get("岁云降世", 0) or 0) > now:
        dealt *= 1.9
    return {
        "dealt": dealt,
        "taken": max(0.15, taken),
        "shield": 0.05 * max(1, stage),
        "revives": 3 if stage >= 3 else 0,
        "speed": 200.0,
        "stage": float(stage),
    }


# ---------------------------------------------------------------- 全服唯一登记表（纯函数）


def registry_of(state: Mapping[str, Any]) -> dict[str, Any]:
    """规范化登记表：既可吃 calamity_state 单例，也可吃已取出的 registry 本体。"""
    inner = state.get("suiyun_registry")
    r = inner if isinstance(inner, dict) else state
    out = dict(r)
    out.setdefault("remnant", "")
    out.setdefault("treasure", "")
    out.setdefault("gifts", [])
    return out


def gift_left(reg: Mapping[str, Any]) -> int:
    return GIFT_SLOTS - len(reg.get("gifts") or [])


# ---------------------------------------------------------------- 指令逻辑


def seek(doc: Any, inv: Mapping[str, int], now: float, rng: random.Random,
         remnant_taken: bool) -> tuple[bool, str, dict[str, int]]:
    """觉醒前入口：1h CD，3% 得【岁云的残念】（全服唯一 + 纳戒判重）。"""
    if stage_of(doc) > 0:
        return _no("你已承接岁云传承，残念早已化作月华之体。")
    if remnant_taken:
        return _no("【岁云的残念】已被他人承接——万古只此一道，往世星海再无回响。")
    if inv.get(REMNANT, 0) > 0:
        return _no(f"纳戒中已有【{REMNANT}】，快「#消耗{REMNANT}」承接传承。")
    # 觉醒前的 CD 单独存 ext，绝不能写 ext["suiyun"]（_defaults 里 awake=True 会误判已觉醒）
    last = float(doc.ext.get("suiyun_seek", 0) or 0)
    if now - last < SEEK_CD:
        left = int(SEEK_CD - (now - last))
        return _no(f"往世星海的回响尚未重聚，还需 {left // 60 + 1} 分钟。")
    doc.ext["suiyun_seek"] = now
    if rng.random() >= SEEK_CHANCE:
        return _no("你于往世星海打捞一整刻，只见碎月浮沉，未遇那道残念（3% 几率，1 小时后可再试）。")
    return _ok(f"星海翻涌，一缕不肯散去的意志落入纳戒——【{REMNANT}】×1。\n"
               f"发「#消耗{REMNANT}」承接月华之体。", {REMNANT: 1})


def activate(doc: Any, inv: Mapping[str, int], now: float,
             remnant_owner: str = "") -> tuple[bool, str, dict[str, int]]:
    """消耗残念 → 觉醒第 1 阶（全服唯一由 handler 判 registry）。"""
    if stage_of(doc) > 0:
        return _no("你已承接岁云传承，不可重复觉醒。")
    if remnant_owner and remnant_owner != getattr(doc, "uid", ""):
        return _no("【岁云的残念】已归他人，此念不复。")
    if inv.get(REMNANT, 0) < 1:
        return _no(f"纳戒中无【{REMNANT}】。先「#感应岁云」寻它一寻。")
    st = _defaults(now)
    _save(doc, st)
    delta = {REMNANT: -1, GONGFA[0]: 1, GONGFA[1]: 1}
    return _ok(
        "【月华初生】残念入体，万古岁月在血脉里重新流淌——你获得【月华之体】。\n"
        f"传承功法：《{GONGFA[0]}》《{GONGFA[1]}》已入纳戒；岁云剑宫宫主之位虚席以待。\n"
        "境界达标自动连升（神火/天神/至尊/准仙帝），发「#岁云之力」查看。",
        delta,
    )


def stage_rewards(stage: int, treasure_taken: bool) -> tuple[dict[str, int], str]:
    """第 3 / 5 阶的一次性发放（Suiyun.js:506-584）。"""
    if stage == 3:
        d = {name: 1 for name in FROST_SET}
        d[PET] = 1
        return d, "【霜月剑尊】霜月三件套 + 岁云剑灵入纳戒（自行 #装备 三件可激活 ×10 套装层）。"
    if stage == 5:
        d = {name: 1 for name in FINAL_SET}
        if not treasure_taken:
            d[TREASURE] = 1
        return d, ("【岁云剑尊】岁云三件套入纳戒" +
                   (f"，【{TREASURE}】自动认主至宝槽。" if not treasure_taken else
                    f"；【{TREASURE}】已归他人，本次不发放。"))
    return {}, ""


def settle(doc: Any, now: float, authority21: int,
           treasure_taken: bool = False) -> tuple[str, dict[str, int]]:
    """惰性结算：月华天宫整小时产出 + 按等效权柄自动连升 + 阶段奖励补领。

    返回 (结算文案, 物品增量)。**不回退**（model/suiyun.js:200-210 跌境不降阶）。
    """
    st = state_of(doc)
    if st is None:
        return "", {}
    notes: list[str] = []
    delta: dict[str, int] = {}
    # 月华天宫：每现实整小时 +仙道潜力（折算修为），第 4 阶起 +0.5×流速岁云之力
    hours = int((now - float(st.get("palace_at", now) or now)) // HOUR)
    if hours > 0:
        st["palace_at"] = float(st.get("palace_at", now) or now) + hours * HOUR
        gain_exp = hours * PALACE_EXP_PER_HOUR * 1000 * (int(getattr(doc, "realm_index", 0) or 0) + 1)
        doc.exp = int(getattr(doc, "exp", 0) or 0) + gain_exp
        notes.append(f"【月华天宫】{hours} 时辰，修为 +{gain_exp:,}")
        if int(st.get("stage", 1) or 1) >= 4:
            world = doc.ext.get("xiaoshijie")
            lv = int(world.get("level", 1) or 1) if isinstance(world, Mapping) else 1
            ratio = WORLD_RATIO[max(0, min(len(WORLD_RATIO) - 1, lv - 1))]
            gain_power = hours * POWER_HOUR * ratio
            st["power"] = round(float(st.get("power", 0) or 0) + gain_power, 3)
            notes.append(f"岁云之力 +{gain_power:g}（小世界流速 1:{ratio}）")
    # 自动连升：authority_21 达下一阶 realm 即升
    while int(st.get("stage", 1) or 1) < 5:
        nxt = STAGES[int(st.get("stage", 1) or 1)]
        if int(authority21) < int(nxt["realm"]):
            break
        stage = int(st.get("stage", 1) or 1) + 1
        st["stage"] = stage
        st["refined"] = 0
        if stage == 4:
            st["power_at"] = now
        notes.append(f"【岁云·自动晋阶】境界达标，晋升【{STAGES[stage - 1]['name']}】"
                     f"（炼化本源上限 {STAGES[stage - 1]['cap']:,}）")
        claimed = list(st.get("claimed") or [])
        if stage in (3, 5) and stage not in claimed:
            d, msg = stage_rewards(stage, treasure_taken)
            for k, v in d.items():
                delta[k] = delta.get(k, 0) + v
            notes.append(msg)
            claimed.append(stage)
            st["claimed"] = claimed
            if stage == 5 and TREASURE in d:
                eq = doc.ext.setdefault("equipment", {})
                eq["至宝"] = TREASURE
    _save(doc, st)
    return ("\n".join(notes), delta)


def witness(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    """补领阶段奖励（幂等，claimed 判重）。"""
    err = _need_awake(doc)
    if err:
        return _no(err)
    st = _st(doc)
    claimed = list(st.get("claimed") or [])
    delta: dict[str, int] = {}
    got = []
    for stage in (3, 5):
        if int(st.get("stage", 1) or 1) >= stage and stage not in claimed:
            d, msg = stage_rewards(stage, False)
            for k, v in d.items():
                delta[k] = delta.get(k, 0) + v
            claimed.append(stage)
            got.append(msg)
    st["claimed"] = claimed
    _save(doc, st)
    if not got:
        return _ok(f"【岁云见证】传承为【{stage_name(doc)}】，阶段馈赠已全部领取，无遗漏。")
    return _ok("【岁云见证】\n" + "\n".join(got), delta)


def cultivate(doc: Any, now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#云月修炼：24h CD，月华 +2000~5000（Suiyun.js:212-222）。"""
    err = _need_awake(doc)
    if err:
        return _no(err)
    st = _st(doc)
    last = float(st.get("last_cultivate", 0) or 0)
    if now - last < CULTIVATE_CD:
        left = CULTIVATE_CD - (now - last)
        return _no(f"云月尚未盈满，还需 {left / 3600:.1f} 小时方可再修炼。")
    gain = rng.randint(2000, 5000)
    st["last_cultivate"] = now
    st["moonlight"] = int(st.get("moonlight", 0) or 0) + gain
    _save(doc, st)
    return _ok(f"【云月修炼】引月华入脉，月华值 +{gain:,}，当前 {st['moonlight']:,} 点。\n"
               "月华可用于 #月华救赎；累计炼化所得另计 #云月之莲 养器。")


def years(doc: Any, arg: str, now: float, rng: random.Random,
          pool: Sequence[str], gongfa: Sequence[str]) -> tuple[bool, str, dict[str, int]]:
    """#岁岁年年：1h CD，产材料 / 祈愿九秘·十凶·指定名。"""
    err = _need_awake(doc)
    if err:
        return _no(err)
    st = _st(doc)
    last = float(st.get("last_years", 0) or 0)
    if now - last < HOUR:
        left = int(HOUR - (now - last))
        return _no(f"岁岁年年的馈赠尚需 {left // 60 + 1} 分钟。")
    parts = str(arg or "").replace("*", " ").strip().split()
    asked = parts[0] if parts else ""
    wish = "祈愿" in parts or asked == "祈愿"
    name = ""
    if wish:
        name = " ".join(parts[1:]).strip()
        if name in ("九秘", "单字秘"):
            name = rng.choice(list(NINE_SECRETS))
        elif name == "十凶宝术":
            name = rng.choice(list(TEN_XIONG))
    elif asked and asked in pool:
        name = asked
    elif asked in ("九秘", "单字秘"):
        name = rng.choice(list(NINE_SECRETS))
    elif asked == "十凶宝术":
        name = rng.choice(list(TEN_XIONG))
    elif asked and asked in gongfa:
        name = asked
    if not name:
        avail = [x for x in pool if x]
        name = rng.choice(avail) if avail else "潜力丹"
        picked = "随机"
    else:
        picked = "指定"
    if name not in pool and name not in gongfa and name not in NINE_SECRETS and name not in TEN_XIONG and name not in HIDDEN_POOL:
        return _no(f"「{name}」不在岁岁年年的馈赠之列。可祈愿：九秘 / 单字秘 / 十凶宝术 / 功法名，"
                   f"或指定：{'、'.join(list(pool)[:8])}…")
    hidden = rng.random() < 0.10
    delta: dict[str, int] = {name: 1}
    if hidden:
        h = rng.choice(list(HIDDEN_POOL))
        delta[h] = delta.get(h, 0) + 1
    st["last_years"] = now
    _save(doc, st)
    return _ok(f"【岁岁年年】{picked}馈赠「{name}」×1" + (f"，另有隐藏馈赠「{h}」×1" if hidden else "") +
               "；下一次领取在现实 1 小时后。", delta)


def lotus(doc: Any) -> str:
    """#云月之莲：月华养器面板（成长只计炼化所得，消耗月华不降）。"""
    err = _need_awake(doc)
    if err:
        return err
    st = _st(doc)
    eq = doc.ext.get("equipment") or {}
    worn = eq.get("法宝") == "云月之莲"
    per = LOTUS_PER_MOON
    total = int(st.get("lotus_moon", 0) or 0)
    lines = [
        "【云月之莲·月华养器】",
        f"累计炼化月华：{total:,} 点｜每点攻/防/生命上限各 +{per:,}",
        f"当前固定加成：{(total * per):,} × 三维" + ("（未装备本莲，暂不生效）" if not worn else "（已生效）"),
        f"月华值（可消耗）：{int(st.get('moonlight', 0) or 0):,}｜炼化本源 {int(st.get('refined', 0) or 0):,}/{_spec(doc)['cap']:,}",
        "注：#云月修炼 所得月华不计入养器，只有 #月华炼化 的收获才算。",
    ]
    return "\n".join(lines)


def refine(doc: Any, arg: str, now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#月华炼化：24h 禁术调息，按目标类型判定，得月华 + 炼化本源。"""
    err = _need_awake(doc)
    if err:
        return _no(err)
    st = _st(doc)
    last = float(st.get("last_refine", 0) or 0)
    if now - last < REFINE_CD:
        left = REFINE_CD - (now - last)
        return _no(f"禁术调息未毕，还需 {left / 3600:.1f} 小时方可再炼化。")
    cap = int(_spec(doc)["cap"])
    if int(st.get("refined", 0) or 0) >= cap:
        return _no(f"炼化本源已满 {cap:,}，须晋升下一阶段才会清零。#岁云之力 查看晋阶条件。")
    text = str(arg or "").strip()
    kind = next((k for k in REFINE_TARGETS if k in text), "邪祟" if text else "玩家")
    ceiling, chance = REFINE_TARGETS[kind]
    who = text.replace(kind, "").strip() or kind
    locked = bool(st.get("pending_soul"))     # #月华锁魂：搜魂必定成功
    if locked:
        chance = 1.0
    if rng.random() >= chance:
        st["last_refine"] = now
        _save(doc, st)
        return _no(f"【月华炼化】与{who}的本源相持不下，炼化失利（禁术调息 24 小时）。")
    gain = rng.randint(100, ceiling)
    room = cap - int(st.get("refined", 0) or 0)
    origin = min(room, gain * 2)
    log = list(st.get("refine_log") or [])
    key = f"{kind}:{who}"
    if key not in log:
        log.append(key)
    st.update({
        "last_refine": now,
        "moonlight": int(st.get("moonlight", 0) or 0) + gain,
        "refined": int(st.get("refined", 0) or 0) + origin,
        "lotus_moon": int(st.get("lotus_moon", 0) or 0) + gain,
        "refine_log": log[-50:],
        "pending_soul": "",
    })
    _save(doc, st)
    extra = ""
    if locked:
        doc.exp = int(getattr(doc, "exp", 0) or 0) + 500_000
        extra = "｜【月华锁魂】搜魂必成，另得修为 +500,000"
    return _ok(f"【月华炼化】{who}的本源融入月华：月华值 +{gain:,}、炼化本源 +{origin:,}"
               f"（{st['refined']:,}/{cap:,}）｜云月之莲累计 +{gain:,} 点{extra}。")


def soul_lock(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    """#月华锁魂：五阶，锁定一次炼化目标使下次搜魂必定成功。"""
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    st = _st(doc)
    if st.get("pending_soul"):
        return _no(f"已锁定「{st['pending_soul']}」本源，请先完成一次 #月华炼化。")
    target = "待处置天骄"
    st["pending_soul"] = target
    st["last_refine"] = 0.0
    _save(doc, st)
    return _ok(f"【月华锁魂】已锁定{target}本源：下一次 #月华炼化 必定成功，且搜魂可得未学功法"
               "（折算为修为 +500,000）。", {})


def redeem(doc: Any, arg: str) -> tuple[bool, str, dict[str, int]]:
    """#月华救赎：100 月华复原本源 / 200 月华解放关押（折算）。"""
    err = _need_awake(doc)
    if err:
        return _no(err)
    st = _st(doc)
    text = str(arg or "").strip()
    heavy = "解放" in text or "关押" in text
    cost = 200 if heavy else 100
    have = int(st.get("moonlight", 0) or 0)
    if have < cost:
        return _no(f"月华不足：需 {cost:,} 点，当前 {have:,} 点（#云月修炼 / #月华炼化 可得）。")
    st["moonlight"] = have - cost
    doc.ext.pop("spirit_fail_ts", None)          # 渡劫失败冷却清除
    try:
        from . import zhengdao as _dz
        _dz.clear(doc, "月华救赎")               # W8-B6：希望化身清道伤
    except Exception:
        pass
    gain_xueqi = 50_000 if heavy else 20_000
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + gain_xueqi
    _save(doc, st)
    kind = "解放" if heavy else "本源"
    return _ok(f"【月华救赎·{kind}】消耗月华 {cost:,} 点：气血归满、渡劫反噬消散，"
               f"生命本源折算永久血气 +{gain_xueqi:,}。")


def create(doc: Any, arg: str, known: Mapping[str, Any]) -> tuple[bool, str, dict[str, int]]:
    """#岁云造物：≥3 阶，10 点岁云之力造 1 件（不可造唯一/专属/至宝）。"""
    err = _need_stage(doc, 3)
    if err:
        return _no(err)
    name = str(arg or "").replace("*", " ").strip()
    if not name or "@" in name or any(ch.isdigit() for ch in name):
        return _no(f"格式：#岁云造物 物品名（单件、不可带数量或 @）。当前岁云之力 {_st(doc).get('power', 0):g}。")
    if name in NO_CREATE_NAMES or name not in known:
        return _no(f"「{name}」不可创造：唯一造化、岁云专属或不在物品索引中。")
    e = known.get(name)
    if isinstance(e, Mapping) and any(e.get(k) for k in CREATE_BLACKLIST_KEYS):
        return _no(f"「{name}」为不可创造之物，岁云之力亦不能逆天。")
    st = _st(doc)
    if float(st.get("power", 0) or 0) < CREATION_COST:
        return _no(f"岁云之力不足：需 {CREATION_COST} 点，当前 {float(st.get('power', 0) or 0):g} 点"
                   "（第 4 阶起月华天宫每现实小时产出）。")
    st["power"] = round(float(st.get("power", 0) or 0) - CREATION_COST, 3)
    _save(doc, st)
    return _ok(f"【岁云造物】岁月倒卷，【{name}】×1 自虚空中凝成，消耗 {CREATION_COST} 点岁云之力。",
               {name: 1})


CHANGE_COST = {"称号": 5, "道韵": 10, "命格": 20}


def change(doc: Any, arg: str) -> tuple[bool, str, dict[str, int]]:
    """#岁云更改：≥3 阶，5/10/20 点岁云之力改写称号/道韵/命格。"""
    err = _need_stage(doc, 3)
    if err:
        return _no(err)
    parts = str(arg or "").replace("*", " ").strip().split()
    if len(parts) < 2 or parts[0] not in CHANGE_COST:
        return _no("格式：#岁云更改 称号|道韵|命格 名称（消耗 5 / 10 / 20 点岁云之力）。")
    kind, name = parts[0], " ".join(parts[1:])[:16]
    cost = CHANGE_COST[kind]
    st = _st(doc)
    if float(st.get("power", 0) or 0) < cost:
        return _no(f"岁云之力不足：需 {cost} 点，当前 {float(st.get('power', 0) or 0):g} 点。")
    st["power"] = round(float(st.get("power", 0) or 0) - cost, 3)
    if kind == "命格":
        doc.ext["mingge"] = name
    else:
        st["title" if kind == "称号" else "daoyun"] = name
    _save(doc, st)
    return _ok(f"【岁云更改】{kind}已化作【{name}】，消耗 {cost} 点岁云之力。")


def grant(doc: Any, target_uid: str, target_awake: bool, reg: Mapping[str, Any],
          now: float) -> tuple[bool, str, dict[str, Any]]:
    """#赐予月华：五阶，全服 3 席。返回 (ok,msg,新登记表)。"""
    err = _need_stage(doc, 5)
    if err:
        return False, err, dict(reg)
    if not target_uid:
        return False, "格式：#赐予月华 @目标（不带 @ 可查剩余名额）。", dict(reg)
    r = registry_of(reg)
    gifts = list(r.get("gifts") or [])
    if any(g.get("to") == target_uid for g in gifts):
        return False, "此人已承接过月华传承，一道岁月不可赠两回。", r
    if gift_left(r) <= 0:
        return False, "月华传承仅三席，皆已有主。", r
    if target_awake:
        return False, "此人已自有岁云传承，无需再赐。", r
    slot = len(gifts) + 1
    gifts.append({"from": str(getattr(doc, "uid", "")), "to": target_uid,
                  "slot": slot, "at": now})
    r["gifts"] = gifts
    return True, (f"【赐予月华】{target_uid} 承接第 {slot} 席传承，得「霜剑入月 / 岁云归一 / "
                  f"白云苍狗」三道战技（战斗自动生效）。剩余 {GIFT_SLOTS - slot} 席。"), r


def fish(doc: Any, now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#月华垂钓：五阶，3 点岁云之力换一次鱼王垂钓（W8-A2 已有鱼王，此处折算为仙钓结算）。"""
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    st = _st(doc)
    cost = 3
    if float(st.get("power", 0) or 0) < cost:
        return _no(f"岁云之力不足：需 {cost} 点，当前 {float(st.get('power', 0) or 0):g} 点。")
    st["power"] = round(float(st.get("power", 0) or 0) - cost, 3)
    _save(doc, st)
    got = rng.choice(list(DUNGEON_POOL))
    return _ok(f"【月华垂钓】月华作饵，鱼王破水而出——消耗 {cost} 点岁云之力，"
               f"得【{got}】×1，并获一次鱼王讨伐资格（#鱼王列表）。", {got: 1})


def explore(doc: Any, groups: int, now: float,
            rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#刻舟求剑 / #朝花夕拾：五阶免门票探索岁云殿堂（每组 10 轮）。"""
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    g = max(1, min(12, int(groups or 1)))
    st = _st(doc)
    exp_gain = 120_000 * g * (int(getattr(doc, "realm_index", 0) or 0) + 1)
    doc.exp = int(getattr(doc, "exp", 0) or 0) + exp_gain
    delta: dict[str, int] = {}
    for _ in range(g * 2):
        name = rng.choice(list(DUNGEON_POOL))
        delta[name] = delta.get(name, 0) + 1
    _save(doc, st)
    return _ok(f"【岁云殿堂】免门票免寿元，{g} 组共 {g * 10} 轮：修为 +{exp_gain:,}，"
               f"得仙缘 {sum(delta.values())} 件。", delta)


def buy(doc: Any, name: str, qty: int, rows: Sequence[Mapping[str, Any]]) -> tuple[bool, str, dict[str, int]]:
    """#剑宫兑换：宫主按 出售价÷100 灵石兑换（见 shortcut 5）。"""
    err = _need_awake(doc)
    if err:
        return _no(err)
    row = next((r for r in rows if str(r.get("name")) == name), None)
    if row is None:
        return _no(f"剑宫货架上并无「{name}」。发「#岁云剑宫商店」看 22 条名录。")
    n = max(1, min(99, int(qty or 1)))
    unit = max(1, int(row.get("出售价", 0) or 0) // SHOP_PRICE_DIV)
    cost = unit * n
    if int(getattr(doc, "stones", 0) or 0) < cost:
        return _no(f"灵石不足：{name}×{n} 需 {cost:,}（单价 {unit:,}），当前 {int(getattr(doc, 'stones', 0) or 0):,}。")
    doc.stones = int(getattr(doc, "stones", 0) or 0) - cost
    return _ok(f"【剑宫兑换】{name}×{n} 入库，消耗灵石 {cost:,}。", {name: n})


def shop_text(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = ["【岁云剑宫商店】宫主专供（#剑宫兑换 物品名 [数量]）",
             "价格已按源石 ÷100 折算为灵石："]
    for r in rows:
        unit = max(1, int(r.get("出售价", 0) or 0) // SHOP_PRICE_DIV)
        lines.append(f"· {r.get('name')}（{r.get('class') or '物品'}）｜{unit:,} 灵石")
    return "\n".join(lines)


# ---------------------------------------------------------------- 无上天阙枝·十三权柄


def authority_panel(doc: Any) -> str:
    err = _need_awake(doc)
    if err:
        return err
    st = _st(doc)
    seals = st.get("seals") or {}
    lines = [
        "【无上天阙枝·十三权柄】",
        f"当前传承：【{stage_name(doc)}】｜已解封 {len(seals)}/9 道封印",
        "十三权柄：" + "、".join(AUTHORITIES),
        "",
    ]
    for name, offer, qty, desc in SEALS:
        flag = "已解封" if name in seals else f"需 {offer}×{qty}"
        lines.append(f"· {name}｜{flag}｜{desc}")
    lines.append("")
    lines.append("解封方式：#天阙解封 权柄名（纳戒上交供物）")
    lines.append("权柄技：#梦幻 / #断崖之剑 / #根源波动 / #祈愿渡劫 / #无极悟技 / #创世")
    return "\n".join(lines)


def unseal(doc: Any, name: str, inv: Mapping[str, int],
           now: float) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    if name not in SEAL_BY_NAME:
        return _no(f"九道封印中并无「{name}」。可用：{'、'.join(SEAL_BY_NAME)}")
    st = _st(doc)
    seals = dict(st.get("seals") or {})
    if name in seals:
        return _no(f"【{name}】封印已解，不必重复。")
    _, offer, qty, desc = SEAL_BY_NAME[name]
    if inv.get(offer, 0) < qty:
        return _no(f"解封【{name}】需【{offer}】×{qty}，纳戒现有 {inv.get(offer, 0)} 件。")
    seals[name] = now
    st["seals"] = seals
    _save(doc, st)
    return _ok(f"【天阙解封·{name}】供物化作流光没入天阙枝（{len(seals)}/9）——{desc}。",
               {offer: -qty})


def _sealed(doc: Any, name: str) -> str | None:
    st = _st(doc)
    if name not in (st.get("seals") or {}):
        return f"【{name}】封印未解，先「#天阙解封 {name}」。"
    return None


def _cd_left(st: Mapping[str, Any], key: str, now: float) -> float:
    return max(0.0, float((st.get("cd") or {}).get(key, 0) or 0) - now)


def dream(doc: Any, arg: str, now: float) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    e = _sealed(doc, "梦幻")
    if e:
        return _no(e)
    st = _st(doc)
    left = _cd_left(st, "梦幻", now)
    if left:
        return _no(f"梦幻投影尚未消散，还需 {left / 3600:.1f} 小时。")
    parts = str(arg or "").strip().split()
    name = parts[-1] if parts else ""
    if name not in AUTHORITIES:
        return _no(f"格式：#梦幻 至宝名 权柄名（可用：{'、'.join(AUTHORITIES)}）。")
    st["cd"] = {**(st.get("cd") or {}), "梦幻": now + DAY}
    st["dream"] = {"key": name, "expires": now + DAY}
    _save(doc, st)
    return _ok(f"【梦幻】已借来【{name}】的一次权柄：24 小时内战斗增伤 +50%（#岁云之力 可查）。")


def sword(doc: Any, now: float, grand: bool = False) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    key = "岁云降世" if grand else "断崖之剑"
    need = "大地" if not grand else None
    st = _st(doc)
    if need:
        e = _sealed(doc, need)
        if e:
            return _no(e)
    if grand and len(st.get("seals") or {}) < 9:
        return _no("【岁云降世】需九道封印尽解（#天阙权柄 看进度）。")
    left = _cd_left(st, key, now)
    if left:
        return _no(f"【{key}】尚在调息，还需 {left / 3600:.1f} 小时。")
    st["cd"] = {**(st.get("cd") or {}), key: now + DAY}
    _save(doc, st)
    return _ok(f"【{key}】24 小时内" +
               ("前 3 回合攻防速度齐涨、岁云剑雨覆盖全场（战斗增伤 +90%）。" if grand
                else "下一场首击额外三倍威力（战斗增伤 +30%）。"))


def root_wave(doc: Any, arg: str, now: float) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    e = _sealed(doc, "海洋")
    if e:
        return _no(e)
    st = _st(doc)
    left = _cd_left(st, "根源波动", now)
    if left:
        return _no(f"根源波动尚未平息，还需 {left / 3600:.1f} 小时（48h CD）。")
    st["cd"] = {**(st.get("cd") or {}), "根源波动": now + 2 * DAY}
    doc.ext.pop("spirit_fail_ts", None)
    try:
        from . import zhengdao as _dz
        _dz.clear(doc, "根源波动")               # W8-B6：海洋封印真清道伤
    except Exception:
        pass
    doc.exp = int(getattr(doc, "exp", 0) or 0) + 2_000_000
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + 100_000
    _save(doc, st)
    return _ok(f"【根源波动】{str(arg or '道友').strip() or '道友'}的道伤消散、本源修复："
               "修为 +2,000,000、永久血气 +100,000、渡劫反噬清除；仙道潜力折算 +20%。")


def pray_trib(doc: Any, arg: str, now: float) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    e = _sealed(doc, "七夜的许愿星")
    if e:
        return _no(e)
    st = _st(doc)
    cost = 5_000_000
    if int(getattr(doc, "exp", 0) or 0) < cost:
        return _no(f"生命本源折算需 {cost:,} 修为，当前不足。")
    doc.exp = int(getattr(doc, "exp", 0) or 0) - cost
    st["trib_shield"] = True
    _save(doc, st)
    return _ok(f"【祈愿渡劫】{str(arg or '道友').strip() or '道友'}的下一场渡劫承伤减少 50%"
               "（与岁云阶段减伤叠加，上限 95%）。")


def skill(doc: Any, arg: str) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    e = _sealed(doc, "无极")
    if e:
        return _no(e)
    name = str(arg or "").strip()
    if not name:
        return _no("格式：#无极悟技 功法名。")
    gf = doc.ext.get("gongfa")
    if isinstance(gf, list):
        if name not in gf:
            gf.append(name)
    else:
        doc.ext["gongfa"] = [name]
    doc.exp = int(getattr(doc, "exp", 0) or 0) + 1_000_000
    return _ok(f"【无极】{name}已百分百领悟：功法入列、修为 +1,000,000。")


def genesis(doc: Any, arg: str, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    err = _need_stage(doc, 5)
    if err:
        return _no(err)
    e = _sealed(doc, "创世")
    if e:
        return _no(e)
    parts = str(arg or "").strip().split()
    if len(parts) < 2 or parts[0] not in ("防具", "装备", "武器", "法宝"):
        return _no("格式：#创世 防具|装备|武器|法宝 名称（1~16 字）。")
    name = " ".join(parts[1:])[:16]
    need = {"界核": 200, "宇宙核心": 200, "万物母气": 100}
    lack = [f"{k}×{v}" for k, v in need.items() if inv.get(k, 0) < v]
    if lack:
        return _no("创世供物不足：" + "、".join(lack))
    st = _st(doc)
    st["genesis"] = True
    _save(doc, st)
    delta = {k: -v for k, v in need.items()}
    delta[name] = 1
    return _ok(f"【创世】{parts[0]}「{name}」自混沌中诞生，攻击/防御/生命各 +500%"
               "（折算进套装层，#我的装备 可见）。", delta)


# ---------------------------------------------------------------- 面板 / 表


def stages_text() -> str:
    lines = ["【岁云五阶】境界达标自动连升（等效权柄 0-21 档）",
             "阶段｜权柄门槛｜悟道｜渡劫减伤｜物品倍率｜本源上限｜套装"]
    for i, s in enumerate(STAGES, 1):
        suit = "霜月套 ×10" if i == 3 else ("岁云套 ×20" if i == 5 else "—")
        lines.append(f"{i}. {s['name']}｜{s['realm']} 档｜+{s['wudao']:.0%}｜"
                     f"{s['trib']:.0%}｜{s['loot']}×｜{s['cap']:,}｜{suit}")
    return "\n".join(lines)


def panel(doc: Any, now: float, reg: Mapping[str, Any] | None = None) -> str:
    err = _need_awake(doc)
    if err:
        return err
    st = _st(doc)
    stage = stage_of(doc)
    s = _spec(doc)
    eq = doc.ext.get("equipment") or {}
    lines = [
        f"【岁云之力·{s['name']}】",
        f"传承第 {stage}/5 阶｜觉醒 {int((now - float(st.get('awake_at', now) or now)) / 3600)} 小时"
        + (f"｜道号【{st['title']}】" if st.get("title") else ""),
        f"月华值 {int(st.get('moonlight', 0) or 0):,}｜炼化本源 "
        f"{int(st.get('refined', 0) or 0):,}/{s['cap']:,}｜累计炼化月华 {int(st.get('lotus_moon', 0) or 0):,}",
        f"岁云之力 {float(st.get('power', 0) or 0):g}（第 4 阶起月华天宫每现实小时产出）",
        f"悟道 +{s['wudao']:.0%}｜渡劫减伤 {s['trib']:.0%}｜物品 {s['loot']}×"
        f"｜秘境 {'免费' if stage >= 3 else '照常收费'}｜幸运 +100%",
        f"灵根等效：eff {s['eff']:,}｜法球 ×{s['orb']:g}｜灵根三围 {s['attrs']:,}",
        f"套装：{eq.get('武器') or '—'} / {eq.get('护具') or '—'} / {eq.get('法宝') or '—'}"
        f"｜至宝 {eq.get('至宝') or '—'}",
        f"云月之莲固定加成：{int(lotus_flat(doc)):,} × 三维",
        f"天阙封印 {len(st.get('seals') or {})}/9｜战技 "
        + ("霜剑入月 / 岁云归一 / 白云苍狗 / 岁云常青" if stage >= 3 else "未满三阶，战技未醒"),
    ]
    bonus, sy_lines = set_bonus(doc)
    if sy_lines:
        lines.append("套装层：" + "、".join(sy_lines) + f"（倍率增量 +{bonus:g}）")
    if reg:
        r = registry_of(reg)
        lines.append(f"月华传承：已赐 {len(r.get('gifts') or [])}/{GIFT_SLOTS} 席｜"
                     f"残念承继者 {r.get('remnant') or '无'}｜天阙枝 {r.get('treasure') or '无'}")
    left_c = CULTIVATE_CD - (now - float(st.get("last_cultivate", 0) or 0))
    left_y = HOUR - (now - float(st.get("last_years", 0) or 0))
    lines.append(f"云月修炼 {'可领取' if left_c <= 0 else f'{left_c / 3600:.1f}h'}｜"
                 f"岁岁年年 {'可领取' if left_y <= 0 else f'{left_y / 60:.0f}min'}")
    lines.append("指令：#云月修炼 / #岁岁年年 / #月华炼化 / #云月之莲 / #月华救赎 / "
                 "#岁云造物 / #岁云更改 / #天阙权柄")
    return "\n".join(lines)
