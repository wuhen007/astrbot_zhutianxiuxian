"""花粉进化路（W8-B3）：25 境进化链 / 异变污染 / 道则悟道 / 祖种孕育 / 花粉渡劫 / 极尽蜕变。

原版依据：`apps/User/FlowerPollenPath.js`（16 条 reg）+ `model/flowerPollenPath.js`（1121 行）
+ `resources/data/Level/花粉进化路体系.json`（25 境）+ `model/shengxuContent.js`。

本移植按 `Z:/dsh/缺失玩法规划-W8.md` 的 B3 决策只做「进化链 + 渡劫」两期：
- 指令 14 条：踏上 / 面板 / 境界表 / 花粉位面 / 感应异变 / 进化 / 服用异果 /
  净化隐患 / 重塑进化根基 / 花粉悟道 / 祖种悟道 / 孕育超级异果 / 服用超级异果 /
  花粉渡劫 / 极尽蜕变（面板含别名，渡劫状态并入面板）。
- 花粉战斗神术与圣墟九重场域由 `core/shengxu.py` 管理；本模块仍未实现六呼吸法卡与七妙宝术。

shortcut（与原版的差异，均已在数值上折算而非省略）：
1. 原版踏上需 `level_id≥42 且 Physique_id≥42`；本移植境界下标为 0-63，折算为双轨各 ≥15。
2. 原版进化 cost = `1 亿 × 2^level × 时代系数`；本移植修为量级小三档，
   `EVOLUTION_BASE_COST` 取 10 万（÷1000），时代系数固定 1.0（天命）——全服时代状态在 db 单例，
   纯函数拿不到，接时代需改调用链，等 W8-D 全服状态统一后再接。
3. 原版祖种/石罐全服唯一、掉率 0.0012；本移植改为「感应异变在花粉 10/12 境后各 3% 掉落，
   按玩家纳戒判重」——全服唯一登记表未搬。
4. 原版极境每项 +3% 花粉基础三维；本移植按 B0 决策「第三轨不给三维乘区」，
   改为每项 +1% 进化成功率 / +3% 悟道收益 / +1 等效权柄。
5. 原版三级圣墟位面靠副本坐标穿梭；本移植收敛为 `#花粉位面` 选择所在位面，
   位面只决定进化上限（小阴间 11 / 大阴间 13 / 阳间 17）与感应异变的媒介品阶。
6. 原版 `道伤` / `仙道潜力` / 护道药 / 大衍悟道丹续次在本移植无对应体系，
   超级异果改为清空根基损伤与始祖污染、补满未圆满道则。
7. 原版超级异果收益 `2,000,000 × 三体系等级乘积`；本移植按 ÷10 折算为
   `2_000_000 × 花粉境 × (炼体境+1) // 10`。
"""

from __future__ import annotations
from .clock import day_key

import random
import time
from collections.abc import Mapping
from typing import Any

# ---------------------------------------------------------------- 25 境

LEVELS: tuple[str, ...] = (
    "普通人", "觉醒境", "枷锁境", "逍遥境", "观想境", "餐霞境", "塑形境", "金身境",
    "亚圣境", "圣者境", "映照诸天", "神祇境", "神将境", "神王境", "天尊境",
    "混元境——大能", "大宇境/究极境", "宇究境", "仙王", "仙王巨头",
    "道祖——准仙帝", "路尽级仙帝", "祭道", "祭道之上", "唯一道之上",
)

# ---------------------------------------------------------------- 媒介 / 异果 / 净化

MEDIA: dict[str, dict[str, int | float]] = {
    "普通进化花粉": {"quality": 1, "chance": 0.05, "risk": 12, "accum": 10},
    "灵性进化花粉": {"quality": 2, "chance": 0.12, "risk": 8, "accum": 14},
    "神性进化花粉": {"quality": 3, "chance": 0.20, "risk": 4, "accum": 20},
    "无暇进化花粉": {"quality": 4, "chance": 0.30, "risk": 1, "accum": 28},
}
MEDIA_GATES: tuple[tuple[int, int], ...] = ((2, 1), (6, 2), (11, 3), (18, 4))

FRUITS: dict[str, dict[str, int]] = {
    "进化异果": {"accum": 20, "risk": 6, "pollution": 2, "root": 2},
    "本源异果": {"accum": 45, "risk": 12, "pollution": 5, "root": 5},
    "祖种异果": {"accum": 90, "risk": 20, "pollution": 9, "root": 9},
}
PURIFY: dict[str, dict[str, int]] = {
    "净化花露": {"risk": 30, "pollution": 20, "root": 12},
    "本源圣药": {"risk": 60, "pollution": 60, "root": 45},
}
SEED = "花粉路祖种"
JAR = "神秘石罐"
SUPER = "超级异果"

PLANES: dict[str, int] = {"小阴间": 11, "大阴间": 13, "阳间": 17}

EVOLUTION_BASE_COST = 100_000       # 原版 1 亿 ÷1000，见模块头 shortcut 2
ACTIVATE_GATE = 15                  # 双轨各 ≥15
RISK_MAX = 200
POLLUTION_MAX = 100
POLLUTED_THRESHOLD = 60
ROOT_MAX = 100
MARK_SECONDS = 24 * 3600
BREED_SECONDS = 8 * 3600
DORMANT_SECONDS = 24 * 3600
WUDAO_DAILY_LIMIT = 3
SEED_WUDAO_LIMIT = 3
SENSE_ACCUM = 8
PURIFY_CLEAR_BONUS = 50

# 道则：花粉境 → (名称, 圆满所需道韵, 单次基础收益)
DAO_RULES: dict[int, tuple[str, int, int]] = {
    9: ("圣者花粉道则", 600, 24),
    11: ("映照法则", 1200, 40),
    14: ("神王道则", 2400, 80),
    16: ("混元本源法则", 4800, 160),
    19: ("仙王道则", 9600, 320),
    21: ("道祖法则", 19200, 640),
    22: ("路尽法则", 38400, 1280),
    23: ("祭道法则", 76800, 2560),
    24: ("超脱法则", 153600, 5120),
}

# 渡劫：花粉境 → (劫名, 阶段数, 单阶段成功率, cost 比率, 失败隐患, 失败污染,
#                 成功积淀, 成功隐患减, 成功污染减)
TRIB_RULES: dict[int, tuple[str, int, float, float, int, int, int, int, int]] = {
    5: ("观想花劫", 3, 0.82, 0.04, 6, 4, 24, 8, 4),
    7: ("王境花劫", 3, 0.78, 0.05, 8, 5, 32, 10, 5),
    9: ("圣者花劫", 3, 0.72, 0.06, 10, 7, 45, 14, 7),
    11: ("映照诸天劫", 4, 0.68, 0.07, 12, 8, 60, 16, 8),
    14: ("神王生命劫", 4, 0.64, 0.08, 14, 9, 80, 18, 9),
    16: ("混元本源劫", 4, 0.60, 0.09, 16, 10, 100, 20, 10),
    17: ("大宇究极分岔劫", 3, 0.58, 0.10, 18, 12, 120, 22, 12),
    19: ("仙王不朽劫", 4, 0.54, 0.11, 20, 14, 150, 24, 14),
    21: ("道祖开路劫", 4, 0.50, 0.12, 22, 16, 190, 26, 16),
    22: ("路尽终极劫", 4, 0.46, 0.13, 24, 18, 240, 28, 18),
    23: ("祭道焚因果劫", 4, 0.42, 0.14, 26, 20, 300, 30, 20),
    24: ("超脱离尘劫", 4, 0.38, 0.15, 28, 22, 360, 32, 22),
}

# 极境：(所需花粉境, 名称, 消耗积淀, 隐患上限)
EXTREMES: tuple[tuple[int, str, int, int], ...] = (
    (2, "本源觉醒", 40, 200),
    (3, "十二枷锁尽断", 60, 200),
    (4, "无敌画卷", 100, 200),
    (5, "观想真形", 120, 200),
    (10, "大圣道果", 160, 100),
    (14, "恒王道果", 200, 80),
    (16, "究极根基", 240, 35),
    (17, "大宇净化", 260, 35),
    (21, "道祖道果", 320, 70),
    (22, "路尽道果", 380, 60),
    (23, "祭道蜕变", 450, 50),
)

# 原版 model/realmAuthority.js：花粉境 → 等效权柄（本移植同量级下标）
AUTHORITY_MAP: dict[int, int] = {
    4: 6, 7: 9, 8: 10, 10: 11, 11: 12, 12: 13, 13: 14, 14: 15, 15: 16,
    17: 17, 18: 18, 20: 19, 21: 20, 22: 21, 23: 22, 24: 23, 25: 24,
}


# ---------------------------------------------------------------- 状态

def _defaults() -> dict[str, Any]:
    return {
        "level": 1, "accum": 0, "risk": 0, "pollution": 0, "mark_until": 0.0,
        "root": 0, "extremes": [], "dao": {}, "dao_date": "", "dao_count": 0,
        "completed": [], "trib_fail": {}, "seed_wudao": 0,
        "breed_at": 0.0, "dormant_until": 0.0, "ready": 0, "super_used": 0,
        "sense_date": "", "plane": "小阴间",
    }


def state_of(doc: Any) -> dict[str, Any] | None:
    raw = doc.ext.get("flower") if isinstance(getattr(doc, "ext", None), Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    st = dict(_defaults())
    st.update({k: v for k, v in raw.items() if k in st})
    st["extremes"] = list(st["extremes"] or [])
    st["completed"] = list(st["completed"] or [])
    st["dao"] = dict(st["dao"] or {})
    st["trib_fail"] = dict(st["trib_fail"] or {})
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["flower"] = dict(st)
    from . import extra_cultivation
    extra_cultivation.set_level(doc, "huafen", int(st.get("level", 1) or 1))


def _date_key(now: float) -> str:
    return day_key(now)


def _have(inv: Mapping[str, int], name: str, qty: int = 1) -> bool:
    return int(inv.get(name, 0) or 0) >= qty


def _xueqi(doc: Any) -> int:
    return int(doc.ext.get("xueqi", 0) or 0)


def _set_xueqi(doc: Any, value: int) -> None:
    doc.ext["xueqi"] = max(0, int(value))


def _clamp(st: dict[str, Any]) -> None:
    st["level"] = max(1, min(25, int(st["level"])))
    st["accum"] = max(0, int(st["accum"]))
    st["risk"] = max(0, min(RISK_MAX, int(st["risk"])))
    st["pollution"] = max(0, min(POLLUTION_MAX, int(st["pollution"])))
    st["root"] = max(0, min(ROOT_MAX, int(st["root"])))


def _settle_breed(st: dict[str, Any], now: float) -> str:
    """祖种孕育惰性结算：8h 产出 → 24h 沉寂。"""
    if st["breed_at"] > 0 and now >= float(st["breed_at"]) + BREED_SECONDS:
        st["ready"] = int(st["ready"] or 0) + 1
        st["breed_at"] = 0.0
        st["dormant_until"] = now + DORMANT_SECONDS
        st["seed_wudao"] = 0
        return "祖种孕育完成，可领取超级异果×1（#服用超级异果）；祖种进入 24 小时沉寂。"
    return ""


def required_quality(target: int) -> int:
    q = 1
    for low, quality in MEDIA_GATES:
        if target >= low:
            q = quality
    return q


def media_of_quality(quality: int) -> str:
    for name, row in MEDIA.items():
        if int(row["quality"]) == quality:
            return name
    return "无暇进化花粉"


def evo_cost(level: int) -> int:
    return EVOLUTION_BASE_COST * (2 ** max(1, int(level)))


def dao_progress(st: Mapping[str, Any], level: int) -> tuple[int, int]:
    rule = DAO_RULES.get(level)
    if not rule:
        return 0, 0
    return int(st["dao"].get(str(level), 0) or 0), int(rule[1])


def equivalent_level(doc: Any) -> int:
    """第三轨：花粉境换算的等效境界（B0 注册制），极境每项 +1。"""
    st = state_of(doc)
    if st is None:
        return 0
    lv = int(st["level"])
    out = 0
    for key, val in AUTHORITY_MAP.items():
        if key <= lv:
            out = max(out, val)
    return min(63, out + len(st["extremes"]))


def level_name(level: int) -> str:
    return LEVELS[max(1, min(25, int(level))) - 1]


# ---------------------------------------------------------------- 指令逻辑

def activate(doc: Any, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    if state_of(doc) is not None:
        return False, "【花粉进化路·已开启】已踏上花粉进化路，无需重复开启。", {}
    if doc.realm_index < ACTIVATE_GATE or doc.physique_index < ACTIVATE_GATE:
        return False, (f"踏上花粉路需练气/炼体双轨各达第 {ACTIVATE_GATE + 1} 境"
                       f"（当前 {doc.realm_index + 1} / {doc.physique_index + 1}）。"), {}
    initial = _defaults()
    from . import extra_cultivation
    initial["level"] = extra_cultivation.level_of(doc, "huafen")
    set_state(doc, initial)
    return True, ("【花粉路开启】自今日起以花粉为舟、以异果为薪，另证一条进化之路。\n"
                  "赠【普通进化花粉】×3。\n"
                  "下一步：#感应异变 取媒介 → #进化 提升花粉境。"), {"普通进化花粉": 3}


def set_plane(doc: Any, name: str) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    if name not in PLANES:
        return False, f"未知位面。可选：{' / '.join(PLANES)}。", {}
    st["plane"] = name
    set_state(doc, st)
    return True, f"已置身「{name}」，该位面法则允许的花粉进化上限为第 {PLANES[name]} 境。", {}


def sense(doc: Any, inv: Mapping[str, int], now: float,
          rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#感应异变：每日一次，按下一境需求产媒介 / 净化物 / 异果 / 祖种石罐。"""
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    today = _date_key(now)
    if st["sense_date"] == today:
        return False, "今日已感应过异变，明日再来。", {}
    target = min(25, int(st["level"]) + 1)
    medium = media_of_quality(required_quality(target))
    delta: dict[str, int] = {medium: 3 + rng.randrange(3)}
    lines = [f"【感应异变】冥冥中捕捉到一缕进化道韵｜进化积淀 +{SENSE_ACCUM}",
             f"获得「{medium}」×{delta[medium]}（下一境第 {target} 境所需品阶）"]
    if rng.random() < 0.35:
        delta["净化花露"] = 1
        lines.append("额外获得「净化花露」×1")
    if rng.random() < 0.18:
        fruit = "祖种异果" if int(st["level"]) >= 14 else (
            "本源异果" if int(st["level"]) >= 7 else "进化异果")
        delta[fruit] = 1
        lines.append(f"异变凝出「{fruit}」×1")
    for item, gate, extra in ((SEED, 10, "祖种"), (JAR, 12, "石罐")):
        if int(st["level"]) >= gate and not _have(inv, item) and rng.random() < 0.03:
            delta[item] = 1
            lines.append(f"圣墟机缘显现：「{item}」×1（{extra}已认主）")
    st["sense_date"] = today
    st["accum"] = int(st["accum"]) + SENSE_ACCUM
    _clamp(st)
    set_state(doc, st)
    return True, "\n".join(lines), delta


def _high_progression_gate(doc: Any, current_level: int) -> str | None:
    """Keep the four source-specialized high flower ascensions behind their own state."""
    if current_level < 21 or current_level > 24:
        return None
    from . import ownway, sacrifice, selfdao
    ow = ownway.state_of(doc)
    if current_level == 21:
        sd = selfdao.state_of(doc)
        ready = (int(ow.get("seg", 0) or 0) >= 300
                 and int(sd.get("layers", 0) or 0) >= selfdao.LAYERS
                 and bool(sd.get("system_name"))
                 and len(sd.get("realms") or []) == 6)
        if not ready:
            return ("【道祖绝巅·专用晋升】此境必须完成自身之道与己道推演前置，"
                    "普通进化不能替代；请按 #推演己道 / #合道 的门槛继续。")
    elif current_level == 22 and not ow.get("jidao"):
        return "【路尽仙帝·专用晋升】须先完成自身之道祭道（#祭道），普通进化不能替代。"
    elif current_level == 23:
        bubble = sacrifice.state_of(doc).get("bubble")
        if not isinstance(bubble, Mapping) or bubble.get("status") != "transcended":
            return ("【祭道绝巅·专用晋升】须经历始祖永祭并挣脱空间泡影"
                    "（#空间泡影状态 / #挣脱空间泡影），普通进化不能替代。")
    elif current_level == 24 and not ow.get("unique"):
        return "【祭道之上·专用晋升】须先完成唯一道之上证道（#唯一道之上），普通进化不能替代。"
    return None


def _chance(st: Mapping[str, Any], medium: Mapping, now: float,
            wound_penalty: float = 0.0) -> float:
    level = int(st["level"])
    base = 0.75 - min(0.35, (level - 1) * 0.018)
    chance = (base + float(medium["chance"])
              + min(0.2, int(st["accum"]) / 1000)
              - min(0.35, int(st["risk"]) * 0.0035)
              - min(0.25, int(st["root"]) * 0.0025)
              + 0.01 * len(st["extremes"]))
    if int(st["pollution"]) >= POLLUTED_THRESHOLD:
        chance -= 0.15
    if now < float(st["mark_until"] or 0):
        chance -= 0.20
    chance -= max(0.0, float(wound_penalty))   # W8-B6 道伤：成功率 -8pp/层
    return max(0.1, min(0.95, chance))


def _mutation(st: Mapping[str, Any]) -> float:
    level = int(st["level"])
    return max(0.03, min(0.25, 0.03 + int(st["risk"]) / 200 * 0.15 + (level - 1) * 0.004))


def _pick_medium(inv: Mapping[str, int], quality: int, asked: str) -> str | None:
    if asked:
        return asked if asked in MEDIA else None
    usable = [n for n, r in MEDIA.items()
              if int(r["quality"]) >= quality and _have(inv, n)]
    if not usable:
        return None
    return min(usable, key=lambda n: int(MEDIA[n]["quality"]))


def evolve(doc: Any, inv: Mapping[str, int], asked: str, now: float,
           rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#进化：扣修为/血气 + 媒介；成功跃迁，失败扣 30%，异变累积始祖污染。"""
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    level = int(st["level"])
    if level >= 25:
        return False, "已至「唯一道之上」，花粉路再无进阶。", {}
    if int(st["root"]) >= ROOT_MAX:
        return False, f"进化根基损伤已满 {ROOT_MAX}，先用 #重塑进化根基 修复。", {}
    high_gate = _high_progression_gate(doc, level)
    if high_gate:
        return False, high_gate, {}
    target = level + 1
    cap = PLANES.get(str(st["plane"]), 11)
    if target <= 17 and target > cap:
        return False, (f"「{st['plane']}」法则上限第 {cap} 境，第 {target} 境需前往更高位面"
                       "（#花粉位面 大阴间 / 阳间）。"), {}
    if target >= 18 and doc.realm_index < 30:
        return False, f"第 {target} 境需主修权柄达第 31 境（当前 {doc.realm_index + 1}）。", {}
    cur, need = dao_progress(st, level)
    if need and cur < need:
        return False, f"「{DAO_RULES[level][0]}」未圆满（{cur}/{need}），先 #花粉悟道。", {}
    if level in TRIB_RULES and level not in st["completed"]:
        return False, f"「{TRIB_RULES[level][0]}」未渡尽，先 #花粉渡劫。", {}
    quality = required_quality(target)
    medium = _pick_medium(inv, quality, asked)
    if medium is None:
        return False, f"缺少「{media_of_quality(quality)}」（或更高品阶）进化媒介，#感应异变 可得。", {}
    if int(MEDIA[medium]["quality"]) < quality:
        return False, f"「{medium}」品阶不足，第 {target} 境需 {media_of_quality(quality)}。", {}
    if not _have(inv, medium):
        return False, f"纳戒里没有「{medium}」。", {}
    cost = evo_cost(level)
    if doc.exp < cost or _xueqi(doc) < cost:
        return False, f"进化需修为与血气各 {cost:,}（当前 {int(doc.exp):,} / {_xueqi(doc):,}）。", {}

    doc.exp = int(doc.exp) - cost
    _set_xueqi(doc, _xueqi(doc) - cost)
    delta = {medium: -1}
    try:
        from . import zhengdao as _dz
        dz_pen = _dz.effects(doc)["chance_penalty"]
    except Exception:
        dz_pen = 0.0
    chance = _chance(st, MEDIA[medium], now, dz_pen)
    st["accum"] = int(st["accum"]) + int(MEDIA[medium]["accum"])
    st["risk"] = int(st["risk"]) + int(MEDIA[medium]["risk"])

    if rng.random() < chance:
        st["level"] = target
        _clamp(st)
        set_state(doc, st)
        return True, (f"【生命跃迁】花粉进化路 第 {target} 境 · {level_name(target)}！\n"
                      f"成功率 {chance:.0%}｜进化积淀 +{MEDIA[medium]['accum']}｜"
                      f"隐患 +{MEDIA[medium]['risk']}"), delta

    doc.exp = int(int(doc.exp) * 0.7)
    _set_xueqi(doc, int(_xueqi(doc) * 0.7))
    st["accum"] = int(st["accum"]) + 12
    st["risk"] = int(st["risk"]) + 6
    lines = [f"【进化受阻·道基受损】成功率 {chance:.0%}，修为与血气再损三成。",
             "进化积淀 +12｜花粉隐患 +6"]
    if rng.random() < _mutation(st):
        gain = 10 + level // 2
        st["pollution"] = int(st["pollution"]) + gain
        lines.append(f"【始祖异变】始祖污染 +{gain}（异变率 {_mutation(st):.1%}）")
        if int(st["pollution"]) >= POLLUTION_MAX:
            doc.exp = int(int(doc.exp) * 0.5)
            _set_xueqi(doc, int(_xueqi(doc) * 0.5))
            st["pollution"] = 60
            st["mark_until"] = now + MARK_SECONDS
            lines.append("【始祖接引】修为与血气被夺五成，烙下 24 小时始祖印记（成功率 -20%），污染回落 60。")
    _clamp(st)
    set_state(doc, st)
    return True, "\n".join(lines), delta


def eat_fruit(doc: Any, inv: Mapping[str, int], asked: str) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    if int(st["root"]) >= ROOT_MAX:
        return False, f"进化根基损伤已满 {ROOT_MAX}，先 #重塑进化根基。", {}
    name = asked or next((f for f in FRUITS if _have(inv, f)), "")
    if name not in FRUITS:
        return False, "纳戒里没有可服用的花粉路异果。", {}
    if not _have(inv, name):
        return False, f"纳戒里没有「{name}」。", {}
    row = FRUITS[name]
    st["accum"] = int(st["accum"]) + row["accum"]
    st["risk"] = int(st["risk"]) + row["risk"]
    st["pollution"] = int(st["pollution"]) + row["pollution"]
    st["root"] = int(st["root"]) + row["root"]
    _clamp(st)
    set_state(doc, st)
    return True, (f"服下「{name}」｜进化积淀 +{row['accum']}｜隐患 +{row['risk']}｜"
                  f"始祖污染 +{row['pollution']}｜根基损伤 +{row['root']}"), {name: -1}


def purify(doc: Any, inv: Mapping[str, int], asked: str) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    if int(st["risk"]) <= 0 and int(st["pollution"]) <= 0:
        return False, "隐患与始祖污染皆为空，无需净化。", {}
    name = asked or next((p for p in ("净化花露", "本源圣药") if _have(inv, p)), "")
    if name not in PURIFY:
        return False, "缺少「净化花露」或「本源圣药」。", {}
    if not _have(inv, name):
        return False, f"纳戒里没有「{name}」。", {}
    row = PURIFY[name]
    before = int(st["pollution"])
    st["risk"] = max(0, int(st["risk"]) - row["risk"])
    st["pollution"] = max(0, before - row["pollution"])
    lines = [f"【本源净化】以「{name}」洗去花粉隐患 -{row['risk']}、始祖污染 -{row['pollution']}"]
    if before > 0 and int(st["pollution"]) == 0:
        st["accum"] = int(st["accum"]) + PURIFY_CLEAR_BONUS
        lines.append(f"破而后立！污染清零，进化积淀 +{PURIFY_CLEAR_BONUS}")
    _clamp(st)
    set_state(doc, st)
    return True, "\n".join(lines), {name: -1}


def reshape(doc: Any, inv: Mapping[str, int], asked: str) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    if int(st["root"]) <= 0:
        return False, "进化根基完好，无需重塑。", {}
    name = asked or next((p for p in ("净化花露", "本源圣药") if _have(inv, p)), "")
    if name not in PURIFY:
        return False, "缺少「净化花露」或「本源圣药」。", {}
    if not _have(inv, name):
        return False, f"纳戒里没有「{name}」。", {}
    cut = int(PURIFY[name]["root"])
    st["root"] = max(0, int(st["root"]) - cut)
    _clamp(st)
    set_state(doc, st)
    return True, f"【重塑进化根基】以「{name}」修复损伤 -{cut}，当前根基损伤 {st['root']}/{ROOT_MAX}。", {name: -1}


def wudao(doc: Any, inv: Mapping[str, int], now: float, rng: random.Random,
          ancestor: bool = False) -> tuple[bool, str, dict[str, int]]:
    """#花粉悟道（每日 3 次）/ #祖种悟道（每轮 3 次，收益三倍）。"""
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    level = int(st["level"])
    if level not in DAO_RULES:
        return False, f"当前花粉境「{level_name(level)}」无道则可悟（道则自第 9 境起）。", {}
    cur, need = dao_progress(st, level)
    if cur >= need:
        return False, f"「{DAO_RULES[level][0]}」已圆满，可尝试 #进化。", {}
    if ancestor:
        if not (_have(inv, SEED) and _have(inv, JAR)):
            return False, f"祖种悟道需持有「{SEED}」与「{JAR}」。", {}
        if int(st["seed_wudao"]) >= SEED_WUDAO_LIMIT:
            return False, f"本轮祖种悟道已用尽 {SEED_WUDAO_LIMIT} 次，待祖种沉寂结束后刷新。", {}
        st["seed_wudao"] = int(st["seed_wudao"]) + 1
        mult, rate, label = 3, 0.9, "祖种共鸣三倍道韵"
    else:
        today = _date_key(now)
        if st["dao_date"] != today:
            st["dao_date"], st["dao_count"] = today, 0
        if int(st["dao_count"]) >= WUDAO_DAILY_LIMIT:
            return False, f"今日悟道已用尽 {WUDAO_DAILY_LIMIT} 次，明日再来。", {}
        st["dao_count"] = int(st["dao_count"]) + 1
        mult, rate, label = 1, 1.0, "参悟花粉道则"
    cost = max(100_000, int(evo_cost(level) * 0.08 * rate))
    if doc.exp < cost or _xueqi(doc) < cost:
        return False, f"悟道需修为与血气各 {cost:,}。", {}
    doc.exp = int(doc.exp) - cost
    _set_xueqi(doc, _xueqi(doc) - cost)
    gain = int(DAO_RULES[level][2] * rng.uniform(0.9, 1.1) * mult
               * (1 + 0.03 * len(st["extremes"])))
    st["dao"][str(level)] = cur + gain
    _clamp(st)
    set_state(doc, st)
    tail = "道则圆满！可 #花粉渡劫 / #进化。" if cur + gain >= need else f"道韵 {cur + gain}/{need}"
    return True, (f"「{label}」悟得道韵 +{gain}（{tail}）｜消耗修为与血气各 {cost:,}"
                  + (f"｜今日 {st['dao_count']}/{WUDAO_DAILY_LIMIT}" if not ancestor
                     else f"｜本轮祖种 {st['seed_wudao']}/{SEED_WUDAO_LIMIT}")), {}


def breed(doc: Any, inv: Mapping[str, int], now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    if not (_have(inv, SEED) and _have(inv, JAR)):
        return False, f"孕育需持有「{SEED}」与「{JAR}」。", {}
    settled = _settle_breed(st, now)
    if settled:
        set_state(doc, st)
        return True, settled, {}
    if st["breed_at"] > 0:
        left = int(float(st["breed_at"]) + BREED_SECONDS - now)
        return False, f"祖种孕育中，尚需 {max(1, left // 3600)} 小时。", {}
    if now < float(st["dormant_until"] or 0):
        left = int(float(st["dormant_until"]) - now)
        return False, f"祖种沉寂中，尚需 {max(1, left // 3600)} 小时方可再次孕育。", {}
    st["breed_at"] = now
    set_state(doc, st)
    return True, "【祖种孕育】祖种入罐，孕育 8 小时；完成后可得超级异果×1，祖种沉寂 24 小时。", {}


def super_fruit(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    _settle_breed(st, now)
    if int(st["ready"]) <= 0:
        set_state(doc, st)
        return False, "暂无可领取的超级异果（先 #孕育超级异果 并等待 8 小时）。", {}
    level = int(st["level"])
    gain = 2_000_000 * level * max(1, int(doc.physique_index) + 1) // 10
    doc.exp = int(doc.exp) + gain
    _set_xueqi(doc, _xueqi(doc) + gain)
    for lv, rule in DAO_RULES.items():
        if lv <= level:
            st["dao"][str(lv)] = max(int(st["dao"].get(str(lv), 0) or 0), rule[1])
    st["ready"] = int(st["ready"]) - 1
    st["root"] = 0
    st["pollution"] = 0
    st["super_used"] = int(st["super_used"] or 0) + 1
    _clamp(st)
    set_state(doc, st)
    return True, (f"【服用超级异果】修为与血气各 +{gain:,}｜未圆满道则尽数补齐｜"
                  f"根基损伤与始祖污染清零｜已服 {st['super_used']} 枚"), {}


def tribulation(doc: Any, now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#花粉渡劫：每阶段 10 道雷劫，逐阶段判定，全过方成。"""
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    level = int(st["level"])
    rule = TRIB_RULES.get(level)
    if not rule:
        return False, f"第 {level} 境无专属花劫，无需渡劫。", {}
    if level in st["completed"]:
        return False, f"「{rule[0]}」已渡尽，可尝试 #进化。", {}
    cur, need = dao_progress(st, level)
    if need and cur < need:
        return False, f"「{DAO_RULES[level][0]}」未圆满（{cur}/{need}），先 #花粉悟道。", {}
    cost = max(100_000, int(evo_cost(level) * rule[3]))
    if doc.exp < cost or _xueqi(doc) < cost:
        return False, f"渡劫需修为与血气各 {cost:,}。", {}
    doc.exp = int(doc.exp) - cost
    _set_xueqi(doc, _xueqi(doc) - cost)
    fails = int(st["trib_fail"].get(str(level), 0) or 0)
    try:
        from . import zhengdao as _dz
        dz_pen = _dz.effects(doc)["chance_penalty"]
        dz_frost = _dz.frost_active(doc)
    except Exception:
        dz_pen, dz_frost = 0.0, False
    chance = max(0.1, min(0.95, rule[2] + min(0.15, fails * 0.03) - dz_pen))
    passed = 0
    for _ in range(int(rule[1])):
        if rng.random() >= chance:
            break
        passed += 1
    waves = int(rule[1]) * 10
    if passed == int(rule[1]):
        st["completed"].append(level)
        st["accum"] = int(st["accum"]) + rule[6]
        st["risk"] = max(0, int(st["risk"]) - rule[7])
        st["pollution"] = max(0, int(st["pollution"]) - rule[8])
        _clamp(st)
        set_state(doc, st)
        try:
            from . import zhengdao as _dz2
            _dz2.clear(doc, "花劫淬炼")           # W8-B6：淬炼成功清空道伤
        except Exception:
            pass
        return True, (f"【{rule[0]}·渡尽】{rule[1]} 阶段 {waves} 道雷劫尽数扛过！\n"
                      f"进化积淀 +{rule[6]}｜隐患 -{rule[7]}｜始祖污染 -{rule[8]}｜"
                      f"消耗修为与血气各 {cost:,}"), {}
    doc.exp = int(int(doc.exp) * 0.85)
    _set_xueqi(doc, int(_xueqi(doc) * 0.85))
    st["risk"] = int(st["risk"]) + rule[4]
    st["pollution"] = int(st["pollution"]) + rule[5]
    st["accum"] = int(st["accum"]) + max(6, rule[6] // 5)
    st["trib_fail"][str(level)] = fails + 1
    _clamp(st)
    set_state(doc, st)
    try:
        from . import zhengdao as _dz3
        wound = _dz3.add_wounds(doc, 1.0, "花粉渡劫失败", halve=dz_frost)
        wnote = f"｜道伤 +{0.5 if dz_frost else 1:g}（现 {wound:.1f}）"
    except Exception:
        wnote = ""
    return True, (f"【{rule[0]}·未渡尽】第 {passed + 1}/{rule[1]} 阶段雷劫失守（单阶段 {chance:.0%}）。\n"
                  f"修为与血气再损 15%｜隐患 +{rule[4]}｜污染 +{rule[5]}{wnote}｜"
                  f"失败保护：下次渡劫单阶段成功率 +3%（累计 {fails + 1} 次）"), {}


def extreme(doc: Any) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st is None:
        return False, "尚未踏上花粉路（#踏上花粉路）。", {}
    level, accum, risk = int(st["level"]), int(st["accum"]), int(st["risk"])
    for need_level, name, cost, max_risk in EXTREMES:
        if name in st["extremes"] or level < need_level:
            continue
        if accum < cost:
            return False, f"下一极境「{name}」需进化积淀 {cost}（当前 {accum}）。", {}
        if risk > max_risk:
            return False, f"「{name}」要求花粉隐患 ≤{max_risk}（当前 {risk}），先 #净化隐患。", {}
        st["accum"] = accum - cost
        st["risk"] = max(0, risk - 12)
        st["extremes"].append(name)
        _clamp(st)
        set_state(doc, st)
        n = len(st["extremes"])
        return True, (f"【极尽蜕变·{name}】进化积淀 -{cost}｜隐患 -12\n"
                      f"极境 {n} 项：进化成功率 +{n}%｜悟道收益 +{3 * n}%｜等效权柄 +{n}"), {}
    return False, "【花粉极境·已达上限】已达当前可挑战的极境尽头，继续提升花粉境。", {}


def levels_text() -> str:
    lines = ["【花粉进化路·二十五境】"]
    for i, name in enumerate(LEVELS, 1):
        q = required_quality(i)
        tail = f"｜媒介 {media_of_quality(q)}" if i >= 2 else "｜起点"
        lines.append(f"{i:>2}. {name}{tail}")
    return "\n".join(lines)


def panel(doc: Any, now: float) -> str:
    st = state_of(doc)
    if st is None:
        return "尚未踏上花粉路。双轨各达第 16 境后可发送 #踏上花粉路 开启第三轨。"
    settled = _settle_breed(st, now)
    set_state(doc, st)
    level = int(st["level"])
    target = min(25, level + 1)
    cur, need = dao_progress(st, level)
    trib = TRIB_RULES.get(level)
    if st["breed_at"] > 0:
        seed_txt = f"孕育中（还需 {max(1, int(float(st['breed_at']) + BREED_SECONDS - now) // 3600)}h）"
    elif now < float(st["dormant_until"] or 0):
        seed_txt = f"沉寂中（还需 {max(1, int(float(st['dormant_until']) - now) // 3600)}h）"
    elif int(st["ready"]) > 0:
        seed_txt = f"可领超级异果 {st['ready']} 枚"
    else:
        seed_txt = f"祖种悟道 {st['seed_wudao']}/{SEED_WUDAO_LIMIT}"
    lines = [
        "--- 花粉进化路 ---" + (f"（{settled}）" if settled else ""),
        f"境界：第 {level} 境 · {level_name(level)}｜等效权柄 {equivalent_level(doc)} 重天",
        f"进化积淀 {st['accum']}｜花粉隐患 {st['risk']}/{RISK_MAX}｜"
        f"始祖污染 {st['pollution']}/{POLLUTION_MAX}｜根基损伤 {st['root']}/{ROOT_MAX}",
        f"极境 {len(st['extremes'])}/{len(EXTREMES)} 项｜所在位面 {st['plane']}"
        f"（进化上限第 {PLANES.get(str(st['plane']), 11)} 境）",
        ("道则：" + (f"{DAO_RULES[level][0]} {cur}/{need}" if need else "当前境界无道则")),
        ("渡劫：" + (f"「{trib[0]}」" + ("已渡尽" if level in st["completed"] else "未渡尽")
                    if trib else "当前境界无花劫")),
        f"祖种：{seed_txt}",
        f"今日感应：{'已感应' if st['sense_date'] == _date_key(now) else '可感应'}｜"
        f"今日悟道 {st['dao_count'] if st['dao_date'] == _date_key(now) else 0}/{WUDAO_DAILY_LIMIT}",
    ]
    if int(st["mark_until"] or 0) > now:
        lines.append(f"始祖印记：剩余 {int((float(st['mark_until']) - now) // 3600)} 小时（进化成功率 -20%）")
    if level < 25:
        lines.append(f"下一境：第 {target} 境 · {level_name(target)}｜"
                     f"媒介 {media_of_quality(required_quality(target))}｜"
                     f"修为与血气各 {evo_cost(level):,}")
    lines.append("指令：#感应异变 / #进化 / #服用异果 / #净化隐患 / #花粉悟道 / #花粉渡劫 / #极尽蜕变")
    return "\n".join(lines)
