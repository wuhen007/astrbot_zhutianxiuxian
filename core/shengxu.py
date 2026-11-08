"""场域圣墟（W8-F4，对齐原版 apps/User/ShengxuContent.js 992 行 + ShengxuRank.js 67 行
+ model/shengxuContent.js / flowerPollenField.js / flowerPollenSkill.js）。

玩法闭环：探索 12 处圣墟副本（真身 / 沉迷 / 法身三路）→ 进化花粉 + 异果 + 呼吸法残页 +
神术 + 场域残图 + 石罐线索 → 合成呼吸法（5 残页）→ 参悟场域（5 残图升一重天）→
加入圣墟势力领日俸 → 集齐条件「追寻石罐」→ 圣墟榜。

⚠️ 三处折算（勿当 bug）：

1. **场域不加三维**。原版「每重天 = 花粉基础三维 +3%（九重 +27%）」；本移植沿用 B0 决策
   （第三轨只进门槛与 PVP 天堑，不给三维乘区），改为**圣墟战斗胜率 +2%/重天**（九重 +18%）
   + 圣墟榜排序权重。数值仍在 `FIELD_ATTR_PER_STAGE = 0.03`（用于展示「等效乘区」）。
2. **入场成本不套记忆命途折扣**。原版 `getMemoryDungeonCost` 按记忆命途「门径」给
   100/80/70/60% 折扣，本移植不做该折扣（无记忆命途门径档位）。
3. **探索战斗用胜率模型**。原版跑 `zd_battle` 打镜像生灵；本移植按
   「花粉境 − 副本需求境」差算胜率（`0.5 + 差×0.08`，钳 15%~95%），
   与法身圣墟同一口径，不做逐回合战斗。

状态挂 `doc.ext["shengxu"]`，db 恒 v17。
"""

from __future__ import annotations

import math
import time
from typing import Any, Iterable, Mapping, Sequence

from . import flower, plane

# ---------------------------------------------------------------- 数据

# (章, 名称, 需求花粉境, 生灵, 强度, 媒介, 数量, 积淀, 呼吸法, 传承率, 分钟, 圣药率, 场域残图, 神术池)
DUNGEONS: tuple[dict[str, Any], ...] = (
    {"chapter": "地球篇", "name": "太行山", "req": 2, "monster": "太行苍狼", "scale": 0.68,
     "medium": "普通进化花粉", "amount": 2, "accum": 6, "gongfa": "形意呼吸法", "gongfa_rate": 0.12,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大力牛魔拳", 0.15), ("共振术", 0.08))},
    {"chapter": "地球篇", "name": "昆仑山", "req": 2, "monster": "昆仑兽王", "scale": 0.72,
     "medium": "普通进化花粉", "amount": 2, "accum": 8, "gongfa": "形意呼吸法", "gongfa_rate": 0.18,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("终极拳", 0.15), ("螺旋术", 0.08))},
    {"chapter": "地球篇", "name": "武当山", "req": 3, "monster": "金顶异禽王", "scale": 0.78,
     "medium": "普通进化花粉", "amount": 3, "accum": 8, "gongfa": "太极呼吸法", "gongfa_rate": 0.18,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("闪电拳", 0.15),)},
    {"chapter": "地球篇", "name": "龙虎山", "req": 4, "monster": "枷锁古猿", "scale": 0.86,
     "medium": "灵性进化花粉", "amount": 1, "accum": 10, "gongfa": "太极呼吸法", "gongfa_rate": 0.14,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("火眼金睛", 0.12),)},
    {"chapter": "地球篇", "name": "嵩山", "req": 4, "monster": "嵩山老猿", "scale": 0.88,
     "medium": "灵性进化花粉", "amount": 1, "accum": 10, "gongfa": "大雷音呼吸法", "gongfa_rate": 0.06,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大日如来拳", 0.12),)},
    {"chapter": "地球篇", "name": "终南山", "req": 5, "monster": "异树守卫", "scale": 0.92,
     "medium": "灵性进化花粉", "amount": 1, "accum": 11, "gongfa": "道引呼吸法", "gongfa_rate": 0.04,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("不灭经·护身", 0.12),)},
    {"chapter": "地球篇", "name": "泰山", "req": 5, "monster": "封禅异禽王", "scale": 0.95,
     "medium": "灵性进化花粉", "amount": 2, "accum": 11, "gongfa": "道引呼吸法", "gongfa_rate": 0.05,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大力牛魔拳", 0.10), ("终极拳", 0.08))},
    {"chapter": "地球篇", "name": "顺天玉虚宫", "req": 6, "monster": "失控异变体", "scale": 0.98,
     "medium": "灵性进化花粉", "amount": 2, "accum": 12, "gongfa": "形意呼吸法", "gongfa_rate": 0.10,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("火眼金睛", 0.10), ("闪电拳", 0.08))},
    {"chapter": "地球篇", "name": "大雷音寺遗址", "req": 6, "monster": "雷音尸魔", "scale": 1.00,
     "medium": "灵性进化花粉", "amount": 2, "accum": 12, "gongfa": "大雷音呼吸法", "gongfa_rate": 0.10,
     "minutes": 7, "herb_rate": 0.0, "field_page": False,
     "skills": (("大日如来拳", 0.10), ("不灭经·护身", 0.08))},
    {"chapter": "星路篇", "name": "小阴间星路", "req": 8, "monster": "星路猎杀者", "scale": 1.10,
     "medium": "神性进化花粉", "amount": 1, "accum": 16, "gongfa": "道引呼吸法", "gongfa_rate": 0.07,
     "minutes": 10, "herb_rate": 0.0, "field_page": True,
     "skills": (("寒霜覆地", 0.10), ("七妙宝术·土", 0.10), ("少阴拳", 0.07), ("少阳拳", 0.06))},
    {"chapter": "阳间篇", "name": "阳间名山", "req": 11, "monster": "阳间神祇", "scale": 1.22,
     "medium": "神性进化花粉", "amount": 2, "accum": 20, "gongfa": "道引呼吸法", "gongfa_rate": 0.10,
     "minutes": 15, "herb_rate": 0.05, "field_page": True,
     "skills": (("七妙宝术·金", 0.08), ("七妙宝术·火", 0.08), ("场域法·镇", 0.06),
                ("魂钟精神攻杀术", 0.05), ("五色神光", 0.04), ("金色符文秘术", 0.03))},
    {"chapter": "诡异篇", "name": "魂河古地", "req": 17, "monster": "魂河接引者", "scale": 1.38,
     "medium": "无暇进化花粉", "amount": 1, "accum": 28, "gongfa": "盗引呼吸法", "gongfa_rate": 0.03,
     "minutes": 20, "herb_rate": 0.10, "field_page": True,
     "skills": (("七妙宝术·水", 0.06), ("七妙宝术·木", 0.06), ("七妙宝术·阴", 0.08),
                ("七妙宝术·阳", 0.08), ("时间妙术", 0.05), ("时光术", 0.03),
                ("小六道时光术", 0.03), ("斩千秋", 0.025), ("九宝妙术", 0.015))},
)
DUNGEON_BY_NAME = {d["name"]: d for d in DUNGEONS}

FACTIONS: dict[str, dict[str, Any]] = {
    "菩提基因": {"post": "外勤进化者", "req": 2, "medium": "普通进化花粉",
                 "amount": 3, "dew": 0, "accum": 5},
    "大梦净土": {"post": "外门弟子", "req": 8, "medium": "灵性进化花粉",
                 "amount": 2, "dew": 1, "accum": 10},
    "阳间第一山": {"post": "记名门徒", "req": 12, "medium": "神性进化花粉",
                   "amount": 1, "dew": 2, "accum": 15},
}

# 呼吸法下本提速（分钟）
BREATHING_REDUCTION = {"基础呼吸法": 0, "形意呼吸法": 1, "太极呼吸法": 2,
                       "大雷音呼吸法": 3, "道引呼吸法": 4, "盗引呼吸法": 5}
MIN_MINUTES = 5

ANCESTOR_SEED_CHANCE = 0.0012
PAGE_REQUIRE = 5
LEARNED_PAGE_REWARD = 5          # 已学会时折现进化积淀

FIELD_MAX = 9
FIELD_PAGE_REQUIRE = 5
FIELD_ATTR_PER_STAGE = 0.03      # 原版三维加成（本移植改作胜率加成，见模块说明）
FIELD_WIN_PER_STAGE = 0.02       # 本移植真实消费者：圣墟战斗胜率
FIELD_WEAKEN_PER_STAGE = 0.004

JAR = "神秘石罐"
SEED = "花粉路祖种"
JAR_CLUE_REQUIRE = 9
JAR_EXTREMES = ("无敌画卷", "观想真形")
JAR_RISK_MAX = 50
JAR_CLEARED_REQUIRE = 6

EXPLORE_MINUTES_MAX_COUNT = 12
RANK_LIMIT = 20

# 神术表（原名 1:1；本移植只做「参悟 + 面板 + 七宝进度」，不做战斗触发）
SKILLS: tuple[dict[str, Any], ...] = (
    {"name": "大力牛魔拳", "type": "道与法", "realm": 2, "pr": 0.18, "desc": "黄牛所传金牛拳法，蛮力破敌"},
    {"name": "终极拳", "type": "道与法", "realm": 3, "pr": 0.16, "desc": "楚风自创拳法，人人可学"},
    {"name": "共振术", "type": "道与法", "realm": 3, "pr": 0.14, "desc": "以特殊频率震裂护体能量"},
    {"name": "闪电拳", "type": "道与法", "realm": 4, "pr": 0.16, "desc": "少女曦所授神技，快如电光"},
    {"name": "螺旋术", "type": "道与法", "realm": 4, "pr": 0.13, "desc": "螺旋劲贯穿血肉与魂光"},
    {"name": "火眼金睛", "type": "道与法", "realm": 5, "pr": 0.14, "desc": "神目洞悉破绽"},
    {"name": "不灭经·护身", "type": "道与法", "realm": 6, "pr": 0.14, "desc": "肉身不灭，生机不绝"},
    {"name": "大日如来拳", "type": "盖世杀术", "realm": 7, "pr": 0.14, "desc": "残缺禁忌妙术"},
    {"name": "寒霜覆地", "type": "道与法", "realm": 8, "pr": 0.13, "desc": "寒霜领域压制对手气机"},
    {"name": "少阴拳", "type": "道与法", "realm": 8, "pr": 0.12, "desc": "少阴之力凝于拳锋"},
    {"name": "少阳拳", "type": "道与法", "realm": 9, "pr": 0.12, "desc": "少阳之气炽烈升腾"},
    {"name": "七妙宝术·土", "type": "盖世杀术", "realm": 9, "pr": 0.14, "desc": "七宝之一·土行，凝聚土墙护体"},
    {"name": "七妙宝术·金", "type": "盖世杀术", "realm": 10, "pr": 0.12, "desc": "七宝之一·金行，无坚不摧"},
    {"name": "七妙宝术·火", "type": "盖世杀术", "realm": 11, "pr": 0.12, "desc": "七宝之一·火行，焚尽诸敌"},
    {"name": "七妙宝术·水", "type": "盖世杀术", "realm": 12, "pr": 0.12, "desc": "七宝之一·水行，蚀骨消魂"},
    {"name": "魂钟精神攻杀术", "type": "道与法", "realm": 12, "pr": 0.10, "desc": "钟波直击元神"},
    {"name": "场域法·镇", "type": "道与法", "realm": 13, "pr": 0.12, "desc": "场域体系的镇封秘术"},
    {"name": "七妙宝术·木", "type": "盖世杀术", "realm": 14, "pr": 0.12, "desc": "七宝之一·木行，困敌绞杀"},
    {"name": "一身化七圣", "type": "盖世杀术", "realm": 15, "pr": 0.10, "desc": "化身妙术，一身分化七圣"},
    {"name": "五色神光", "type": "盖世杀术", "realm": 15, "pr": 0.08, "desc": "五色神光横扫，刷落兵器"},
    {"name": "七妙宝术·阴", "type": "盖世杀术", "realm": 16, "pr": 0.10, "desc": "七宝之一·阴行，吞噬生机"},
    {"name": "金色符文秘术", "type": "盖世杀术", "realm": 17, "pr": 0.08, "desc": "金色符文流转，无物不破"},
    {"name": "小六道时光术", "type": "盖世杀术", "realm": 17, "pr": 0.07, "desc": "六道轮转，时光成环"},
    {"name": "七妙宝术·阳", "type": "盖世杀术", "realm": 18, "pr": 0.10, "desc": "七宝之一·阳行，焚尽万法"},
    {"name": "斩千秋", "type": "盖世杀术", "realm": 18, "pr": 0.06, "desc": "金色法页横断岁月"},
    {"name": "时间妙术", "type": "盖世杀术", "realm": 19, "pr": 0.08, "desc": "武疯子一脉秘术，时光锁敌"},
    {"name": "时光术", "type": "盖世杀术", "realm": 20, "pr": 0.08, "desc": "触及时光之力，岁月成刃"},
    {"name": "九宝妙术", "type": "盖世杀术", "realm": 20, "pr": 0.05, "desc": "九色光轮，刷落万物"},
)
SKILL_BY_NAME = {s["name"]: s for s in SKILLS}
SEVEN_TREASURES = ("七妙宝术·土", "七妙宝术·金", "七妙宝术·火", "七妙宝术·水",
                   "七妙宝术·木", "七妙宝术·阴", "七妙宝术·阳")

ITEM_CLASS = {"medium": "道具", "fruit": "道具", "herb": "道具", "gongfa": "功法"}


# ---------------------------------------------------------------- 状态

def state_of(doc: Any) -> dict:
    """取（并按需初始化）`ext["shengxu"]`；直接改 doc，调用方负责保存。"""
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    st = ext.get("shengxu")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("action", None)
    st.setdefault("cleared", {})
    st.setdefault("pages", {})
    st.setdefault("faction", "")
    st.setdefault("faction_day", "")
    st.setdefault("join_reward", False)
    st.setdefault("field_stage", 0)
    st.setdefault("field_pages", 0)
    st.setdefault("clue", 0)
    st.setdefault("jar_claimed", False)
    st.setdefault("runs", 0)
    ext["shengxu"] = st
    return st


def flower_level(doc: Any) -> int:
    st = flower.state_of(doc)
    return int(st["level"]) if st else 0


def flower_accum(doc: Any) -> int:
    st = flower.state_of(doc)
    return int(st["accum"]) if st else 0


def flower_risk(doc: Any) -> int:
    st = flower.state_of(doc)
    return int(st["risk"]) if st else 0


def flower_extremes(doc: Any) -> list[str]:
    st = flower.state_of(doc)
    return list(st["extremes"]) if st else []


def add_accum(doc: Any, amount: int) -> None:
    st = flower.state_of(doc)
    if st is None:
        return
    st["accum"] = int(st["accum"]) + max(0, int(amount))
    flower.set_state(doc, st)


# ---------------------------------------------------------------- 副本

def dungeon_of(name: str) -> dict | None:
    return DUNGEON_BY_NAME.get(str(name or "").strip())


def plane_of(dun: Mapping[str, Any]) -> str:
    return "阳间" if dun.get("chapter") in ("阳间篇", "诡异篇") else "小阴间"


def explore_cost(dun: Mapping[str, Any], count: int = 1) -> dict[str, int]:
    lv = max(1, int(dun.get("req") or 1))
    sc = max(0.1, float(dun.get("scale") or 1.0))
    n = max(1, int(count or 1))
    return {
        "xiuwei": int(round(1_000_000 * lv * sc)) * n,
        "xueqi": int(round(1_000_000 * lv * sc)) * n,
        "lingshi": int(round(500_000 * lv * sc)) * n,
        "shouyuan": max(1, int(math.ceil(float(dun.get("minutes") or 5) / 5))) * n,
    }


def minutes_of(doc: Any, dun: Mapping[str, Any]) -> int:
    learned = set(doc.ext.get("gongfa") or []) if isinstance(doc.ext, dict) else set()
    red = max([v for k, v in BREATHING_REDUCTION.items() if k in learned] or [0])
    return max(MIN_MINUTES, int(dun.get("minutes") or 15) - red)


def shortages(doc: Any, cost: Mapping[str, int]) -> list[str]:
    ext = doc.ext if isinstance(doc.ext, dict) else {}
    have = {
        "修为": int(doc.exp),
        "血气": int(ext.get("xueqi", 0) or 0),
        "灵石": int(doc.stones),
        "寿元": int(ext.get("shouyuan", 0) or 0),
    }
    out = []
    for field, key in (("修为", "xiuwei"), ("血气", "xueqi"), ("灵石", "lingshi"), ("寿元", "shouyuan")):
        if have[field] < int(cost[key]):
            out.append(f"{field}需{int(cost[key]):,}，现有{have[field]:,}")
    return out


def action_of(doc: Any) -> dict | None:
    act = state_of(doc).get("action")
    return act if isinstance(act, dict) else None


def begin(doc: Any, name: str, count: int, now: float) -> tuple[bool, str]:
    """#探索圣墟 / #沉迷圣墟：校验位面与成本，起一个惰性计时行动。"""
    st = state_of(doc)
    dun = dungeon_of(name)
    if not dun:
        return False, "圣墟副本仅：" + "、".join(d["name"] for d in DUNGEONS)
    if flower.state_of(doc) is None:
        return False, "圣墟只向花粉进化路的修士显形（先发送「#踏上花粉路」）。"
    if isinstance(st.get("action"), dict):
        return False, "你正在圣墟中探索，先发送「#探索圣墟」结算。"
    level = flower_level(doc)
    if level < int(dun["req"]):
        return False, (f"【{dun['name']}】需花粉境 {dun['req']} 阶"
                       f"（当前 {level} 阶）。")
    need_plane = plane_of(dun)
    cur = plane.current(plane.state_of(doc))
    if cur != need_plane:
        return False, f"【{dun['name']}】位于【{need_plane}】，你当前在【{cur}】。"
    n = max(1, min(EXPLORE_MINUTES_MAX_COUNT, int(count or 1)))
    cost = explore_cost(dun, n)
    lack = shortages(doc, cost)
    if lack:
        return False, "资源不足：" + "；".join(lack)
    doc.exp -= cost["xiuwei"]
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) - cost["xueqi"]
    doc.stones -= cost["lingshi"]
    doc.ext["shouyuan"] = int(doc.ext.get("shouyuan", 0) or 0) - cost["shouyuan"]
    minutes = minutes_of(doc, dun) * n
    st["action"] = {"dungeon": dun["name"], "count": n, "start": float(now),
                    "end": float(now) + minutes * 60, "minutes": minutes}
    return True, (f"你踏入圣墟【{dun['name']}】（{dun['chapter']}）×{n}。\n"
                  f"消耗：修为 {cost['xiuwei']:,}｜血气 {cost['xueqi']:,}｜"
                  f"灵石 {cost['lingshi']:,}｜寿元 {cost['shouyuan']}\n"
                  f"预计 {minutes} 分钟（呼吸法提速后），到期后再发「#探索圣墟」结算。")


def win_rate(doc: Any, dun: Mapping[str, Any], field_stage: int = 0) -> float:
    edge = flower_level(doc) - int(dun.get("req") or 1)
    base = 0.5 + edge * 0.08 + int(field_stage) * FIELD_WIN_PER_STAGE
    return max(0.15, min(0.95, base))


def settle(doc: Any, st: dict, now: float, rng: Any) -> tuple[bool, str, dict[str, int], list[str]]:
    """结算到期探索：逐次判胜负，胜则发奖（媒介/异果/圣药/呼吸法/残页/神术/场域/线索）。"""
    act = st.get("action")
    if not isinstance(act, dict):
        return False, "", {}, []
    if float(act.get("end") or 0) > now:
        left = int(float(act["end"]) - now)
        return False, f"尚在圣墟中，还需 {left // 60} 分 {left % 60} 秒。", {}, []
    dun = dungeon_of(str(act.get("dungeon")))
    if not dun:
        st["action"] = None
        return False, "该圣墟副本已不可考，行动作废。", {}, []
    st["action"] = None
    count = max(1, int(act.get("count") or 1))
    ext_gongfa = doc.ext.setdefault("gongfa", [])
    if not isinstance(ext_gongfa, list):
        ext_gongfa = doc.ext["gongfa"] = []
    items: dict[str, int] = {}
    learned: list[str] = []
    lines: list[str] = [f"--- 圣墟探索 · {dun['name']} ---"]
    wins = 0
    for i in range(count):
        if rng.random() > win_rate(doc, dun, int(st.get("field_stage") or 0)):
            doc.ext["hp"] = 1
            lines.append(f"第 {i + 1} 次：【探索失败】你被{dun['monster']}重创，血量降至 1。")
            break
        wins += 1
        lv = int(dun["req"])
        doc.exp += 5_000_000 * lv
        doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + 5_000_000 * lv
        doc.stones += 2_000_000 * lv
        add_accum(doc, int(dun["accum"]))
        items[dun["medium"]] = items.get(dun["medium"], 0) + int(dun["amount"])
        # 异果：等级越高品质越好
        if rng.random() < min(0.28, 0.08 + lv * 0.01):
            fruit = "祖种异果" if lv >= 14 else ("本源异果" if lv >= 7 else "进化异果")
            items[fruit] = items.get(fruit, 0) + 1
        if dun["herb_rate"] and rng.random() < float(dun["herb_rate"]):
            items["本源圣药"] = items.get("本源圣药", 0) + 1
        # 呼吸法：直接传承 + 残页收集
        if rng.random() < float(dun["gongfa_rate"]):
            name = str(dun["gongfa"])
            if name not in ext_gongfa:
                ext_gongfa.append(name)
                learned.append(name)
        page = collect_page(st, str(dun["gongfa"]), ext_gongfa)
        # 神术参悟
        for skill, chance in dun["skills"]:
            if rng.random() < float(chance):
                if skill not in ext_gongfa:
                    ext_gongfa.append(skill)
                    learned.append(skill)
                break
        # 场域残图
        field_note = ""
        if dun["field_page"]:
            fp = collect_field_page(st)
            field_note = f"｜场域残图 {fp['pages']}/{FIELD_PAGE_REQUIRE}"
        # 祖种（全服唯一，千分之一量级）
        if rng.random() < ANCESTOR_SEED_CHANCE:
            items[SEED] = items.get(SEED, 0) + 1
            field_note += "｜【全服唯一机缘】花粉路祖种"
        st["clue"] = int(st.get("clue") or 0) + 1
        cleared = st.setdefault("cleared", {})
        cleared[dun["name"]] = int(cleared.get(dun["name"]) or 0) + 1
        st["runs"] = int(st.get("runs") or 0) + 1
        lines.append(f"第 {i + 1} 次：【胜利】{dun['medium']}×{dun['amount']}｜"
                     f"进化积淀 +{dun['accum']}｜石罐线索 +1｜"
                     f"修为+{5_000_000 * lv:,}｜灵石+{2_000_000 * lv:,}"
                     + field_note)
        if page.get("ok"):
            if page.get("learned"):
                add_accum(doc, int(page.get("reward") or 0))
                lines.append(f"　已掌握【{page['gongfa']}】，残页折现进化积淀 +{page.get('reward')}")
            else:
                lines.append(f"　拾取【{page['gongfa']}·残页】{page['count']}/{PAGE_REQUIRE}")
    if wins == 0:
        return True, "\n".join(lines), items, learned
    lines.append(f"本次通关 {wins}/{count} 次｜累计通关 {len(st.get('cleared') or {})} 处不同的圣墟")
    return True, "\n".join(lines), items, learned


# ---------------------------------------------------------------- 呼吸法

def collect_page(st: dict, gongfa: str, learned: Sequence[str]) -> dict:
    if not gongfa:
        return {"ok": False, "reason": "no-gongfa"}
    pages = st.setdefault("pages", {})
    if gongfa in learned:
        return {"ok": True, "gongfa": gongfa, "learned": True,
                "reward": LEARNED_PAGE_REWARD, "count": int(pages.get(gongfa) or 0)}
    pages[gongfa] = int(pages.get(gongfa) or 0) + 1
    return {"ok": True, "gongfa": gongfa, "learned": False,
            "count": pages[gongfa], "need": PAGE_REQUIRE}


def synthesize(doc: Any, st: dict, gongfa: str) -> tuple[bool, str]:
    """#合成呼吸法：5 张残页 → 学会该呼吸法。"""
    gongfa = str(gongfa or "").strip()
    if gongfa not in BREATHING_REDUCTION:
        return False, "可合成呼吸法：" + "、".join(BREATHING_REDUCTION)
    learned = doc.ext.setdefault("gongfa", [])
    if not isinstance(learned, list):
        learned = doc.ext["gongfa"] = []
    if gongfa in learned:
        return False, f"你已掌握【{gongfa}】。"
    pages = st.setdefault("pages", {})
    count = int(pages.get(gongfa) or 0)
    if count < PAGE_REQUIRE:
        return False, f"【{gongfa}】残页 {count}/{PAGE_REQUIRE}，还需 {PAGE_REQUIRE - count} 张。"
    pages[gongfa] = count - PAGE_REQUIRE
    learned.append(gongfa)
    return True, (f"五张残页在你识海中拼合——【{gongfa}】成篇。\n"
                  f"圣墟探索耗时 -{BREATHING_REDUCTION[gongfa]} 分钟（下限 {MIN_MINUTES} 分钟）。")


# ---------------------------------------------------------------- 场域

def collect_field_page(st: dict, amount: int = 1) -> dict:
    st["field_pages"] = int(st.get("field_pages") or 0) + max(1, int(amount))
    stage = int(st.get("field_stage") or 0)
    return {"ok": True, "pages": st["field_pages"], "stage": stage,
            "can_advance": stage < FIELD_MAX and st["field_pages"] >= FIELD_PAGE_REQUIRE}


def advance_field(st: dict) -> tuple[bool, str]:
    stage = int(st.get("field_stage") or 0)
    pages = int(st.get("field_pages") or 0)
    if stage >= FIELD_MAX:
        return False, f"场域已至 {FIELD_MAX} 重天（圆满），无法再参悟。"
    if pages < FIELD_PAGE_REQUIRE:
        return False, f"场域残图 {pages}/{FIELD_PAGE_REQUIRE}，还需 {FIELD_PAGE_REQUIRE - pages} 张。"
    st["field_pages"] = pages - FIELD_PAGE_REQUIRE
    st["field_stage"] = stage + 1
    stage += 1
    return True, (f"参悟场域：{stage} 重天。\n"
                  f"圣墟战斗胜率 +{stage * FIELD_WIN_PER_STAGE:.0%}"
                  f"（等效花粉基础三维 +{stage * FIELD_ATTR_PER_STAGE:.0%}，"
                  f"本移植沿 B0 决策不给三维乘区）\n"
                  f"剩余残图 {st['field_pages']} 张。")


def field_profile(st: Mapping[str, Any]) -> dict:
    stage = max(0, min(FIELD_MAX, int(st.get("field_stage") or 0)))
    return {"stage": stage, "max": FIELD_MAX, "pages": int(st.get("field_pages") or 0),
            "need": FIELD_PAGE_REQUIRE,
            "attr": stage * FIELD_ATTR_PER_STAGE,
            "win": stage * FIELD_WIN_PER_STAGE,
            "weaken": stage * FIELD_WEAKEN_PER_STAGE}


# ---------------------------------------------------------------- 势力

def join_faction(doc: Any, st: dict, name: str, now: float) -> tuple[bool, str, dict[str, int]]:
    name = str(name or "").strip()
    info = FACTIONS.get(name)
    if not info:
        return False, "圣墟势力仅：" + "、".join(FACTIONS), {}
    if st.get("faction"):
        return False, f"你已投身【{st['faction']}】，圣墟不容二主。"
    level = flower_level(doc)
    if level < int(info["req"]):
        return False, f"【{name}】只收花粉境 {info['req']} 阶以上（当前 {level} 阶）。", {}
    st["faction"] = name
    items = {str(info["medium"]): int(info["amount"])}
    if info["dew"]:
        items["净化花露"] = int(info["dew"])
    add_accum(doc, int(info["accum"]))
    lines = [f"你投身【{name}】，位列「{info['post']}」。",
             f"入势力礼：{info['medium']}×{info['amount']}"
             + (f"｜净化花露×{info['dew']}" if info["dew"] else "")
             + f"｜进化积淀 +{info['accum']}"]
    if not st.get("join_reward"):
        st["join_reward"] = True
    return True, "\n".join(lines), items


def salary(doc: Any, st: dict, now: float) -> tuple[bool, str, dict[str, int]]:
    name = str(st.get("faction") or "")
    info = FACTIONS.get(name)
    if not info:
        return False, "你尚未加入圣墟势力（#圣墟势力 查看）。", {}
    day = time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))
    if st.get("faction_day") == day:
        return False, "今日俸禄已领，明日再来。", {}
    st["faction_day"] = day
    items = {str(info["medium"]): int(info["amount"])}
    if info["dew"]:
        items["净化花露"] = int(info["dew"])
    add_accum(doc, int(info["accum"]))
    return True, (f"--- {name}俸禄 ---\n{info['medium']}×{info['amount']}"
                  + (f"｜净化花露×{info['dew']}" if info["dew"] else "")
                  + f"｜进化积淀 +{info['accum']}"), items


# ---------------------------------------------------------------- 石罐

def jar_requirements(doc: Any, st: Mapping[str, Any]) -> dict:
    cleared = len(st.get("cleared") or {})
    clue = int(st.get("clue") or 0)
    extremes = flower_extremes(doc)
    missing = [n for n in JAR_EXTREMES if n not in extremes]
    risk = flower_risk(doc)
    reasons = []
    if flower_level(doc) < 11:
        reasons.append("花粉境需至映照诸天（11 阶）")
    if cleared < JAR_CLEARED_REQUIRE:
        reasons.append(f"需踏破 {JAR_CLEARED_REQUIRE} 处不同圣墟（当前 {cleared}）")
    if clue < JAR_CLUE_REQUIRE:
        reasons.append(f"需石罐线索 {JAR_CLUE_REQUIRE} 枚（当前 {clue}）")
    if missing:
        reasons.append("需极境：" + "、".join(missing))
    if risk > JAR_RISK_MAX:
        reasons.append(f"花粉隐患需不高于 {JAR_RISK_MAX}（当前 {risk}）")
    return {"ok": not reasons, "reasons": reasons, "cleared": cleared,
            "clue": clue, "risk": risk}


def claim_jar(doc: Any, st: dict, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    if st.get("jar_claimed") or int(inv.get(JAR, 0) or 0) > 0:
        return False, f"【{JAR}】已在认主之人的纳戒中，天地间只此一只。", {}
    info = jar_requirements(doc, st)
    if not info["ok"]:
        return False, "石罐机缘未至：\n· " + "\n· ".join(info["reasons"]), {}
    st["jar_claimed"] = True
    return True, (f"你循着 {info['clue']} 枚线索走到圣墟深处，"
                  f"荒芜的祭台上静静立着一只【{JAR}】。\n它认你为主。"), {JAR: 1}


# ---------------------------------------------------------------- 榜单 / 文案

def rank_entries(rows: Iterable[Any], limit: int = RANK_LIMIT) -> list[dict]:
    out = []
    for doc in rows:
        st = flower.state_of(doc)
        if st is None:
            continue
        sx = (doc.ext or {}).get("shengxu") if isinstance(doc.ext, dict) else None
        sx = sx if isinstance(sx, dict) else {}
        out.append({
            "name": doc.name or doc.uid,
            "level": int(st["level"]),
            "extremes": len(st["extremes"]),
            "field": int(sx.get("field_stage") or 0),
            "cleared": len(sx.get("cleared") or {}),
            "accum": int(st["accum"]),
        })
    out.sort(key=lambda r: (-r["level"], -r["field"], -r["cleared"], -r["extremes"], -r["accum"]))
    return out[:max(1, min(RANK_LIMIT, int(limit or RANK_LIMIT)))]


def rank_text(rows: Iterable[Any], limit: int = RANK_LIMIT, me: str = "") -> str:
    entries = rank_entries(rows, limit)
    lines = ["--- 圣墟榜 · 花粉进化路 ---",
             "排序：花粉境界 ＞ 场域重天 ＞ 通关副本数 ＞ 极境数 ＞ 进化积淀", ""]
    if not entries:
        lines.append("当前还没有花粉路修士登榜。")
        return "\n".join(lines)
    for i, e in enumerate(entries, 1):
        mark = "（你）" if me and e["name"] == me else ""
        lines.append(f"{i}. {e['name']}{mark}｜{e['level']} 阶｜场域 {e['field']} 重天｜"
                     f"通关 {e['cleared']} 处｜极境 {e['extremes']}｜积淀 {e['accum']}")
    return "\n".join(lines)


def dungeons_text(doc: Any) -> str:
    level = flower_level(doc)
    lines = ["--- 圣墟副本 · 12 处 ---"]
    cur_chapter = ""
    for d in DUNGEONS:
        if d["chapter"] != cur_chapter:
            cur_chapter = d["chapter"]
            lines.append(f"— {cur_chapter} —")
        cost = explore_cost(d, 1)
        lock = "" if level >= d["req"] else f"（需 {d['req']} 阶）"
        lines.append(f"· {d['name']}{lock}｜位面 {plane_of(d)}｜{minutes_of(doc, d)} 分钟｜"
                     f"修为 {cost['xiuwei']:,}｜灵石 {cost['lingshi']:,}｜寿元 {cost['shouyuan']}")
    lines.append("「#探索圣墟 名称」一次｜「#沉迷圣墟 名称*次数」连探（上限 12 次）")
    return "\n".join(lines)


def factions_text(st: Mapping[str, Any]) -> str:
    lines = ["--- 圣墟势力 ---"]
    cur = str(st.get("faction") or "")
    for name, info in FACTIONS.items():
        mark = "▶" if name == cur else "·"
        lines.append(f"{mark} {name}｜{info['post']}｜需 {info['req']} 阶｜"
                     f"日俸 {info['medium']}×{info['amount']}"
                     + (f"+净化花露×{info['dew']}" if info["dew"] else "")
                     + f"｜积淀 +{info['accum']}")
    lines.append("「#加入菩提基因|大梦净土|阳间第一山」投身｜「#领取圣墟俸禄」领日俸")
    return "\n".join(lines)


def skills_text(doc: Any) -> str:
    learned = set(doc.ext.get("gongfa") or []) if isinstance(doc.ext, dict) else set()
    got = [s for s in SKILLS if s["name"] in learned]
    seven = [n for n in SEVEN_TREASURES if n in learned]
    lines = [f"--- 神术 · 已参悟 {len(got)}/{len(SKILLS)} ---",
             f"七妙宝术：{len(seven)}/7" + ("（七宝圆满）" if len(seven) == 7 else "")]
    if not got:
        lines.append("尚未参悟任何神术——圣墟副本胜利时按概率参悟。")
    else:
        lines += [f"· {s['name']}（{s['type']}·{s['realm']} 阶）{s['desc']}" for s in got]
    return "\n".join(lines)


def field_text(st: Mapping[str, Any]) -> str:
    p = field_profile(st)
    return "\n".join([
        "--- 场域 ---",
        f"境界：{p['stage']}/{p['max']} 重天｜残图 {p['pages']}/{p['need']}",
        f"加成：圣墟战斗胜率 +{p['win']:.0%}"
        f"（等效花粉基础三维 +{p['attr']:.0%}，本移植不给三维乘区）",
        f"场域法·镇 压制强化 +{p['weaken']:.1%}",
        f"「#参悟场域」消耗 {p['need']} 张残图升一重天（上限 {p['max']} 重）",
    ])


def jar_text(doc: Any, st: Mapping[str, Any], inv: Mapping[str, int]) -> str:
    info = jar_requirements(doc, st)
    owned = int(inv.get(JAR, 0) or 0) > 0 or bool(st.get("jar_claimed"))
    lines = ["--- 石罐机缘 ---",
             f"状态：{'已认主' if owned else ('条件已足，可「#追寻石罐」' if info['ok'] else '未至')}",
             f"花粉境：{flower_level(doc)}｜已破副本 {info['cleared']} 处｜"
             f"石罐线索 {info['clue']}/{JAR_CLUE_REQUIRE}｜花粉隐患 {info['risk']}"]
    if info["reasons"]:
        lines.append("尚未满足：")
        lines += [f"· {r}" for r in info["reasons"]]
    elif not owned:
        lines.append("「#追寻石罐」循线索走一趟圣墟深处。")
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 场域圣墟 · 规则 ---",
        "· 12 处副本分四篇（地球 9 / 星路 1 / 阳间 1 / 诡异 1）；"
        "地球篇在小阴间，阳间篇与诡异篇在阳间。",
        "· 入场消耗：修为/血气 = 100 万 × 需求阶 × 强度，灵石 = 50 万 × 需求阶 × 强度，"
        "寿元 = ceil(基础分钟/5)；连探按次数翻倍。",
        "· 耗时：基础 7/10/15/20 分钟 − 呼吸法提速（0~5 分钟），下限 5 分钟；"
        "呼吸法来自副本传承与 5 张残页合成。",
        "· 胜负：沿用本移植法身圣墟的胜率口径 —— 0.5 + (花粉境 − 需求阶) × 0.08 + 场域 × 2%，"
        "钳 15%~95%；失败血量降至 1，不发奖。",
        "· 胜利收益：进化花粉 + 异果（8%~28%，14 阶起祖种异果）+ 本源圣药（仅阳间/魂河 5%/10%）"
        "+ 呼吸法传承 + 残页 + 神术参悟 + 场域残图（星路起）+ 石罐线索 +1。",
        "· 石罐：花粉境 11 阶 + 破 6 处 + 线索 9 枚 + 极境「无敌画卷/观想真形」+ 隐患 ≤50，"
        "且全服只此一只。",
        "· 势力：菩提基因 2 阶 / 大梦净土 8 阶 / 阳间第一山 12 阶；入势力一次性礼包 + 每日俸禄。",
        "⚠️ 折算：场域原版加「花粉基础三维 +3%/重天」，本移植沿 B0 决策改为"
        "「圣墟战斗胜率 +2%/重天」；入场成本不套记忆命途折扣；神术只做参悟与面板，不接战斗触发。",
    ])


def help_text() -> str:
    return "\n".join([
        "--- 场域圣墟 · 指令 ---",
        "「#圣墟副本」12 处副本与成本",
        "「#探索圣墟 名称」真身探索｜「#沉迷圣墟 名称*次数」连探（上限 12）",
        "「#法身探索圣墟 位面」「#法身沉迷圣墟 位面*次数」法身侧（见法身指令）",
        "「#圣墟势力」「#加入菩提基因|大梦净土|阳间第一山」「#领取圣墟俸禄」",
        "「#石罐」「#追寻石罐」石罐机缘与认主",
        "「#合成呼吸法 名称」5 张残页合一本",
        "「#神术」已参悟神术与七宝进度",
        "「#场域」「#参悟场域」场域九重天",
        "「#圣墟榜」花粉路榜单",
    ])
