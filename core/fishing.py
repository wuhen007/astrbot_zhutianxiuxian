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

与固定原版已核对：鱼王本体血量按垂钓者战力×20，潮汐化身攻防血分别按出战者属性随机乘 0.8–1.4；宝箱额外奖励池以 55% 概率触发，每箱从九项池不放回抽五组，另保底愿鳞 15–30。三项规则现已分别由 `fk_spawn`、`main.handle_fk_fight`、`fk_roll_chest` 接通。仅签到按钮 UI 未移植。
"""

from __future__ import annotations
from .clock import day_key

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
XIANWU_COORD_CHANCE = 0.025
OTHER_SHORE_FRUIT_CHANCE = 0.001
BASE_FISHING_REWARDS = (
    {"name": "仙晶矿", "class": "道具", "amount": 100, "weight": 50},
    {"name": "七彩流晶矿", "class": "道具", "amount": 10, "weight": 10},
    {"name": "玄品秘境结算卡", "class": "道具", "amount": 5, "weight": 5},
    {"name": "帝品真器丹", "class": "丹药", "amount": 3, "weight": 10},
    {"name": "遣龙令", "class": "道具", "amount": 10, "weight": 5},
    {"name": "遣虎令", "class": "道具", "amount": 10, "weight": 5},
    {"name": "天命轮回丹", "class": "丹药", "amount": 5, "weight": 2},
    {"name": "天药", "class": "丹药", "amount": 30, "weight": 8, "catalyst": "无上九转仙丹药引"},
    {"name": "超越宝盒", "class": "盒子", "amount": 10, "weight": 5},
)

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
    return day_key(now)


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

class _FixedRandom:
    def __init__(self, value: float):
        self.value = float(value)

    def random(self) -> float:
        return self.value


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


def _basic_fishing_rewards(doc: Any, rng: random.Random,
                           ) -> tuple[dict[str, int], int, int, int]:
    """Original always-on base pool, scales, and cultivation/blood-qi rewards."""
    from . import extra_cultivation, memory, suiyun

    ext = getattr(doc, "ext", {}) or {}
    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), Mapping) else {}
    root = ext.get("linggen") if isinstance(ext.get("linggen"), Mapping) else {}
    legacy_root = legacy.get("灵根") if isinstance(legacy.get("灵根"), Mapping) else {}
    root_type = str(root.get("type") or legacy_root.get("type") or "")
    try:
        luck = min(1.0, max(0.0, float(ext.get("luck", 0) or 0)
                              + float(legacy.get("幸运", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        luck = 0.0
    suiyun_effects = suiyun.effects(doc)
    suiyun_madoka = bool(suiyun_effects.get("madoka"))
    branch_roll = rng.random()  # Original draws the basic sea-pool roll first.
    luck_roll = rng.random()
    lucky = root_type == "圆环之理" or bool(suiyun_effects.get("luck")) or luck_roll < luck
    if root_type == "圆环之理" or suiyun_madoka:
        base = 1 if suiyun_madoka else 5
    elif lucky:
        base = 2
    else:
        base = 1
    mstate = memory.state_of(doc)
    mstage = memory.stage_of(doc)
    sea_tier = max(0, min(3, int((mstate.get("factors") or {}).get("海洋", 0) or 0)))
    fishing = 1 if sea_tier == 0 else sea_tier + 1
    multiplier = max(1, int(base * suiyun.loot_mult(doc)
                            * memory.item_mult(mstate, mstage) * fishing))
    branch = _roll_weighted(list(BASE_FISHING_REWARDS), _FixedRandom(branch_roll))
    rewards = {str(branch["name"]): int(branch["amount"]) * multiplier}
    if branch.get("catalyst"):
        rewards[str(branch["catalyst"])] = multiplier
    tracks = extra_cultivation.levels_of(doc)
    realm = int(getattr(doc, "realm_index", 0) or 0) + 1
    physique = int(getattr(doc, "physique_index", 0) or 0) + 1
    exp = int(500 * 3 * tracks["mijing"] * realm * physique) * multiplier
    xueqi = int(800 * 4 * tracks["mijing"] * realm * physique) * multiplier
    return rewards, exp, xueqi, multiplier


def _choice_parts(choice: tuple) -> tuple[str, Mapping[str, int], int, str, Mapping[str, Any]]:
    label, items, stones, message = choice[:4]
    effects = choice[4] if len(choice) > 4 and isinstance(choice[4], Mapping) else {}
    return str(label), items, int(stones), str(message), effects

def roll_catch(plane: str, world_year: int, has_bait: str | None,
               rng: random.Random, allow_fish_king: bool = True,
               owns_xianwu_coordinate: bool = False,
               has_lamp: bool = False) -> dict[str, Any]:
    """一次垂钓的结算（不含 CD / 道具校验）。"""
    t = tide(world_year)
    boosted = bool(t["active"] and plane in t["planes"])
    if has_bait:
        cfg = bait_config(has_bait)
        if has_bait == "轮回冥饵":
            roll = rng.random()
            if not owns_xianwu_coordinate and roll < XIANWU_COORD_CHANCE:
                return {"kind": "bait", "item": "仙武界坐标", "cls": "道具", "amount": 1,
                        "plane": plane, "unique_flag": "xianwu_coordinate_obtained"}
            fruit_start = 0 if owns_xianwu_coordinate else XIANWU_COORD_CHANCE
            if roll < fruit_start + OTHER_SHORE_FRUIT_CHANCE:
                row = {"name": "彼岸轮回果", "class": "材料", "amount": 1}
            else:
                normalized = (roll - fruit_start - OTHER_SHORE_FRUIT_CHANCE) / (1 - fruit_start - OTHER_SHORE_FRUIT_CHANCE)
                row = dict(_roll_weighted(list(cfg.get("rewards") or []), _FixedRandom(normalized)))
        else:
            row = dict(_roll_weighted(list(cfg.get("rewards") or []), rng))
        unique_reward = has_bait == "轮回冥饵" and row.get("name") in ("仙武界坐标", "彼岸轮回果")
        amount = 1 if unique_reward else (1 + int(rng.random() * 5)) * (2 if has_lamp else 1)
        return {"kind": "bait", "item": row.get("name"), "cls": row.get("class") or "道具",
                "amount": amount, "plane": plane, "unique_flag": row.get("unique_flag")}
    cfg = data()["planes"].get(plane) or {}
    fish = list(cfg.get("fish") or [])
    king = cfg.get("king") or {}
    king_chance = FISH_KING_CHANCE * (2 if boosted else 1)
    if king and allow_fish_king and rng.random() < king_chance:
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
            "amount": 1, "plane": plane, "boosted": boosted}


def record(st: dict, plane: str, name: str) -> None:
    row = st.setdefault("atlas", {}).setdefault(plane, {})
    row[name] = int(row.get(name, 0) or 0) + 1


def do_cast(doc: Any, now: float, world_year: int, plane: str, bait: str | None,
            rng: random.Random, allow_fish_king: bool = True,
            owns_xianwu_coordinate: bool = False, has_lamp: bool = False
            ) -> tuple[bool, str, dict[str, int], dict[str, Any]]:
    """垂钓主流程（调用方先校验钓竿/仙饵/气血）。返回 (成功, 文案, 物品, 附加)。"""
    st = state_of(doc)
    st["cd"] = float(now)
    base_items, bonus_exp, bonus_xueqi, multiplier = _basic_fishing_rewards(doc, rng)
    res = roll_catch(plane, world_year, bait, rng, allow_fish_king,
                     owns_xianwu_coordinate, has_lamp)
    items = dict(base_items)
    scale = 1 + int(rng.random() * 5)
    items[SCALE_ITEM] = scale * (2 if has_lamp else 1)
    if res["kind"] == "bait":
        items[str(res["item"])] = items.get(str(res["item"]), 0) + int(res["amount"])
        unique_flag = res.get("unique_flag")
        if unique_flag:
            st[unique_flag] = True
    res["bonus_exp"] = bonus_exp
    res["bonus_xueqi"] = bonus_xueqi
    res["loot_multiplier"] = multiplier
    if res["kind"] not in ("king", "bait"):
        record(st, plane, str(res["item"]))
    lines = []
    if res["kind"] == "king":
        lines.append(f"钓竿骤然弯成满月——【{res['item']}】自界潮中翻涌而出！")
        lines.append("鱼王现世，可发 #鱼王列表 查看讨伐入口。")
        items[SCALE_ITEM] += 5
    elif res["kind"] == "bait":
        lines.append(f"仙饵散作星屑，{res['item']} ×{res['amount']} 随潮而来。")
    else:
        tag = "（旺潮·珍稀鱼）" if res.get("boosted") else ""
        lines.append(f"浮标沉浮，{res['item']} ×{res['amount']}{tag} 上钩。")
        items.setdefault("鱼肉", int(res["amount"]))
    event = None
    if rng.random() < EVENT_CHANCE:
        cfg = PLANE_EVENTS.get(plane, EVENT)
        event = {"id": str(cfg["id"]), "plane": plane, "exp": now + EVENT_TTL}
        st["pending"] = event
    set_state(doc, st)
    if event:
        lines.append(f"{PLANE_EVENTS.get(plane, EVENT)['title']}（#垂钓奇遇 查看）。")
    lines.append(f"基础海钓：修为 +{bonus_exp:,}｜血气 +{bonus_xueqi:,}｜愿鳞已入纳戒；珍宝倍率 ×{multiplier}。")
    return True, "\n".join(lines), items, res


# ---------------------------------------------------------------- 奇遇

PLANE_EVENTS = {
    "凡间": {
        "id": "mortal-rescue", "title": "凡间奇遇·护众道友",
        "intro": "你循水声发现一位将众人护至身前的道友，他被大妖追杀，已然重伤。",
        "choices": [
            ("救起道友", {}, 0, "你替他稳住伤势。他醒后以残血刻阵，高级位面传送阵次数 +1。", {"portal_high": 1}),
            ("引走大妖", {"遣虎令": 2}, 0, "你将大妖引入群山，反夺其御兽法印，获得遣虎令×2。", None),
            ("守护众人", {}, 3_000_000, "你留下护住众人，百姓献出珍藏的古矿，获得源石 300 万。", None),
        ],
    },
    "仙界": {
        "id": "immortal-old-man", "title": "仙界奇遇·老壁灯",
        "intro": "一位怎么看都不靠谱的老者说你天资尚可，非要收你做关门弟子。",
        "choices": [
            ("婉言拒绝", {"功法参悟丹": 1}, 12_000_000, "老者叹了声可惜，留下功法参悟丹×1与源石 1200 万。", None),
            ("请他演法", {"心神丹": 2}, 0, "老者随手演化一段残法，你勉强跟上，获得心神丹×2。", None),
            ("追问来历", {"潜力丹": 1}, 6_000_000, "老者笑而不答，只留下一枚潜力丹与源石 600 万。", None),
        ],
    },
    "遮天位面": {
        "id": "duan-de", "title": "遮天奇遇·段德",
        "intro": "水下钻出个胖道士，嘴上喊着无量天尊，问你要不要合伙探一处阴坟。",
        "choices": [
            ("交换秘辛", {"渡劫天功残页": 1}, 0, "段德给你渡劫天功残页×1，并留下探索古地府的秘辛。十页可合成《渡劫天功》。", {"ancient_underworld_secret": True}),
            ("合力破阵", {"欺天石": 1}, 0, "你与段德合力破去欺天阵纹，分得欺天石×1。", None),
            ("趁机夺图", {"世界石": 1}, 0, "你夺到半角残图，图卷迎风化去，只剩世界石×1。", None),
        ],
    },
    "九天十地": {
        "id": "academy-warship", "title": "九天十地奇遇·书院巡河",
        "intro": "一艘天神书院战船遭异域风暴冲击，正在界河中倾覆。",
        "choices": [
            ("扶正战船", {"功法参悟丹": 1}, 5_000_000, "船上长老赠你功法参悟丹×1与源石 500 万。", None),
            ("打捞船舱", {"彼岸星砂": 1}, 0, "你从破损船舱中打捞出彼岸星砂×1。", None),
            ("追击异域生灵", {"遣龙令": 3}, 0, "你追击异域生灵，夺得遣龙令×3。", None),
        ],
    },
    "下界八域": {
        "id": "willow-waterway", "title": "下界八域奇遇·柳叶定脉",
        "intro": "一片焦黑柳叶落在钓线上，前方水脉随之剧烈暴动。",
        "choices": [
            ("借柳叶定脉", {"九转天药幼苗": 1}, 0, "潮退之后，你寻得九转天药幼苗×1。", None),
            ("追寻水脉源头", {"悟道古茶树幼苗": 1}, 0, "你在水脉源头发现悟道古茶树幼苗×1。", None),
            ("放生受困生灵", {"众生愿鳞": 5}, 0, "受困生灵重归大泽，众生愿力凝成众生愿鳞×5。", None),
        ],
    },
    "太初星墟": {
        "id": "primordial-tide", "title": "太初星墟奇遇·残界潮汐",
        "intro": "钓线牵动一片破碎宇宙，残界正在星墟潮汐中解体。",
        "choices": [
            ("凝聚残界", {}, 0, "星骸凝为五缕太初界源，太初界源 +5。", {"rift_source": 5}),
            ("打捞星骸", {"万古虚空铁": 1}, 0, "你从星骸深处取得万古虚空铁×1。", None),
            ("稳住宇宙胎膜", {"世界石": 1}, 0, "残界最终没有彻底崩碎，回赠你世界石×1。", None),
        ],
    },
    "仙域": {
        "id": "immortal-king-boat", "title": "仙域奇遇·仙王旧舟",
        "intro": "一叶残舟自界海归来，舟上古老剑痕仍在发光。",
        "choices": [
            ("登舟探查", {"彼岸星砂": 1, "纪元之力": 1}, 0, "船舱只余彼岸星砂×1与纪元之力×1。", None),
            ("参悟剑痕", {"功法参悟丹": 2}, 0, "剑痕中残留的仙王道韵凝成功法参悟丹×2。", None),
            ("打捞船底星砂", {"群星之沙": 10}, 0, "你从船底打捞出群星之沙×10。", None),
        ],
    },
}


def event_config(event_id: str) -> Mapping[str, Any] | None:
    for row in PLANE_EVENTS.values():
        if row["id"] == event_id:
            return row
    if event_id == EVENT["id"]:
        return EVENT
    return None


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
    pending = pending_event(doc, now)
    cfg = event_config(str(pending.get("id") or "")) or EVENT
    if idx < 0 or idx >= len(cfg["choices"]):
        return False, f"这条奇遇没有对应选择（1~{len(cfg['choices'])}）。", {}, 0
    label, items, stones, msg, effects = _choice_parts(cfg["choices"][idx])
    st = state_of(doc)
    st["pending"] = None
    for key, value in effects.items():
        if key == "portal_high":
            plane_state = doc.ext.setdefault("plane", {})
            uses = plane_state.setdefault("portal_uses", {"low": 0, "high": 0})
            uses["high"] = int(uses.get("high", 0) or 0) + int(value)
        elif key == "rift_source":
            doc.ext["rift_source"] = int(doc.ext.get("rift_source", 0) or 0) + int(value)
        elif key == "ancient_underworld_secret":
            flags = doc.ext.setdefault("fishing_flags", {})
            flags[key] = bool(value)
    set_state(doc, st)
    return True, f"【{cfg['title']}·{label}】\n{msg}", dict(items), int(stones)


def event_text(doc: Any, now: float) -> str:
    pending = pending_event(doc, now)
    if not pending:
        return "当前没有等待选择的垂钓奇遇。"
    cfg = event_config(str(pending.get("id") or "")) or EVENT
    lines = [f"【{cfg['title']}】", str(cfg["intro"])]
    lines += [f"{i}. {_choice_parts(c)[0]}" for i, c in enumerate(cfg["choices"], 1)]
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


# ---------------------------------------------------------------- 鱼王（按群、召唤者与五人队伍隔离）

FISH_KING_MAX_MEMBERS = 5
FISH_KING_TTL_SECONDS = 24 * 60 * 60
FISH_KING_BATTLE_CD_SECONDS = 30 * 60
FISH_KING_DAO_ART_REDUCTION_SECONDS = 10 * 60
FISH_KING_DAMAGE_CAP_RATIO = 0.20
FISH_KING_RESCUE_CHANCE = 0.03
FISH_KING_KILL_LINGSHI = 25_000_000
FISH_KING_KILL_SOURCE_STONE = 25_000_000
FISH_KING_KILL_CULTIVATION_BASE = 20_000_000
FISH_KING_KILL_GROUPS = 3
FISH_KING_CHEST_REWARD_CHANCE = 0.55
FISH_KING_CHEST_GROUPS = 5
FISH_KING_CHEST_SCALE_RANGE = (15, 30)
FISH_KING_KILL_POOL = (
    {"name": "遣龙令", "class": "道具", "range": (1, 5)},
    {"name": "超越宝盒", "class": "盒子", "range": (1, 5)},
    {"name": "遣虎令", "class": "道具", "range": (1, 5)},
    {"name": "遗珍", "special": "relic", "amount": 1},
    {"name": "随机饵料", "special": "bait", "range": (1, 3)},
    {"name": "一叶轻舟", "class": "道具", "amount": 1},
    {"name": "群星秘钥", "class": "道具", "range": (1, 3)},
    {"name": "仙舟", "class": "道具", "range": (1, 5)},
)
FISH_KING_CHEST_POOL = (
    {"name": "无尽扫荡券", "class": "道具", "range": (1, 3)},
    {"name": "定神丹", "class": "丹药", "range": (1, 5)},
    {"name": "群星秘钥", "class": "道具", "range": (1, 6)},
    {"name": "超越宝盒", "class": "盒子", "range": (3, 10)},
    {"name": "众生仙钓", "class": "道具", "range": (2, 10)},
    {"name": "随机饵料", "special": "bait", "range": (2, 10)},
    {"name": "一叶轻舟", "class": "道具", "range": (1, 3)},
    {"name": "界河灵舟", "class": "道具", "amount": 1},
    {"name": "仙舟", "class": "道具", "range": (3, 5)},
)


def fk_default() -> dict[str, Any]:
    return {"teams": {}, "group_active": {}, "member_team": {}, "legacy": {}}


def fk_state(world: Mapping) -> dict[str, Any]:
    raw = world.get("fish_king") if isinstance(world, Mapping) else None
    state = dict(raw) if isinstance(raw, Mapping) else {}
    # Upgrade the prior world-wide plane dictionary without deleting or overwriting it.
    legacy = state.get("legacy") if isinstance(state.get("legacy"), dict) else {}
    for key, row in state.items():
        if key not in {"teams", "group_active", "member_team", "legacy"} and isinstance(row, Mapping):
            legacy.setdefault(str(key), dict(row))
    state["legacy"] = legacy
    state["teams"] = dict(state.get("teams") or {})
    state["group_active"] = dict(state.get("group_active") or {})
    state["member_team"] = dict(state.get("member_team") or {})
    return state


def _fk_expire(state: dict, now: float) -> None:
    for team_id, team in list(state["teams"].items()):
        if float(team.get("expires_at", 0) or 0) > now:
            continue
        state["teams"].pop(team_id, None)
        group = str(team.get("group_id") or "")
        if state["group_active"].get(group) == team_id:
            state["group_active"].pop(group, None)
        for member in team.get("members", []):
            uid = str(member.get("id") if isinstance(member, Mapping) else member)
            if state["member_team"].get(uid) == team_id:
                state["member_team"].pop(uid, None)


def fk_team(world: Mapping, team_id: str = "", group_id: str = "", uid: str = "",
            now: float | None = None) -> dict[str, Any] | None:
    state = fk_state(world)
    now = time.time() if now is None else float(now)
    _fk_expire(state, now)
    team_id = str(team_id or "").strip()
    if not team_id and uid:
        team_id = str(state["member_team"].get(str(uid)) or "")
    if not team_id and group_id:
        team_id = str(state["group_active"].get(str(group_id)) or "")
    team = state["teams"].get(team_id) if team_id else None
    return dict(team) if isinstance(team, Mapping) and float(team.get("expires_at", 0) or 0) > now else None


def fk_spawn(world: dict, group_id: str, owner_id: str, owner_name: str, plane: str,
             owner_power: int, rng: random.Random, now: float | None = None) -> tuple[dict | None, str]:
    now = time.time() if now is None else float(now)
    group_id, owner_id = str(group_id or "").strip(), str(owner_id or "").strip()
    if not group_id or not owner_id:
        return None, "召唤鱼王必须在群聊中指定垂钓者。"
    state = fk_state(world)
    _fk_expire(state, now)
    if state["group_active"].get(group_id):
        active = state["teams"].get(str(state["group_active"][group_id]), {})
        return None, f"本群已有【{active.get('owner_name', '垂钓者')}的{active.get('name', '鱼王')}】讨伐，需先完成当前战斗。"
    if state["member_team"].get(owner_id):
        return None, "该垂钓者已加入另一支鱼王讨伐队。"
    king = king_of(plane)
    if not king:
        return None, f"【{plane}】尚未孕育可召唤的鱼王。"
    team_id = ""
    for _ in range(100):
        candidate = f"{rng.randrange(100000, 1000000)}"
        if candidate not in state["teams"]:
            team_id = candidate
            break
    if not team_id:
        return None, "界潮正在紊乱，暂时无法生成讨伐队伍编号。"
    health = max(1_000_000, int(max(0, owner_power) * 20))
    team = {
        "id": f"{int(now * 1000)}-{owner_id}", "team_id": team_id,
        "group_id": group_id, "owner_id": owner_id, "owner_name": str(owner_name or owner_id),
        "plane": plane, "name": str(king.get("name") or f"{plane}鱼王"),
        "speed": max(1, int(king.get("speed") or 100)),
        "linggen": dict(king.get("灵根") or {}), "skills": list(king.get("skills") or []),
        "health": health, "health_max": health,
        "members": [{"id": owner_id, "name": str(owner_name or owner_id)}],
        "damage": {}, "battle_cd": {}, "status": "active", "created_at": now,
        "expires_at": now + FISH_KING_TTL_SECONDS, "reward_assignments": None,
        "relic_rewards": None, "settled_members": [], "chests_opened": {},
    }
    state["teams"][team_id] = team
    state["group_active"][group_id] = team_id
    state["member_team"][owner_id] = team_id
    world["fish_king"] = state
    return team, (f"【诸天召王·{plane}】{owner_name}垂钓因果牵引【{team['name']}】现世！\n"
                  f"讨伐队伍编号：{team_id}｜本体血量：{health:,}\n"
                  f"发送「#加入鱼王讨伐 {team_id}」并使用「#讨伐鱼王」；队伍最多 {FISH_KING_MAX_MEMBERS} 人。")


def fk_row(world: Mapping, plane: str, avg_hp: float, group_id: str = "") -> dict[str, Any]:
    state = fk_state(world)
    group_id = str(group_id or "")
    if group_id:
        team_id = str(state["group_active"].get(group_id) or "")
        row = state["teams"].get(team_id) if team_id else None
        if isinstance(row, Mapping) and str(row.get("plane")) == plane:
            return dict(row)
        king = king_of(plane) or {}
        return {"plane": plane, "name": king.get("name") or f"{plane}鱼王",
                "health": 0, "health_max": 0, "members": [], "damage": {},
                "status": "inactive", "group_id": group_id}
    legacy = state["legacy"].get(plane)
    if isinstance(legacy, Mapping):
        return dict(legacy)
    king = king_of(plane) or {}
    bar = int(max(50_000, avg_hp * 30))
    return {"plane": plane, "name": king.get("name") or f"{plane}鱼王",
            "health": bar, "health_max": bar, "damage": {}, "members": [],
            "status": "inactive"}


def fk_put(world: dict, row: Mapping, group_id: str = "") -> dict:
    row = dict(row)
    if group_id and row.get("team_id"):
        state = fk_state(world)
        team_id = str(row["team_id"])
        active_members = {
            str(member.get("id") if isinstance(member, Mapping) else member)
            for member in row.get("members", [])
        }
        for member_id, current_team in list(state["member_team"].items()):
            if str(current_team) == team_id and str(member_id) not in active_members:
                state["member_team"].pop(member_id, None)
        for member_id in active_members:
            state["member_team"][member_id] = team_id
        state["teams"][team_id] = row
        group = str(group_id)
        if row.get("status") != "defeated":
            state["group_active"][group] = team_id
        elif state["group_active"].get(group) == team_id:
            state["group_active"].pop(group, None)
        world["fish_king"] = state
    else:
        world.setdefault("fish_king", {})
        world["fish_king"][str(row["plane"])] = row
    return world


def fk_list(world: Mapping, avg_hp: float = 0, group_id: str = "") -> str:
    if group_id:
        state = fk_state(world)
        team = fk_team(world, group_id=group_id)
        if not team:
            return "本群当前没有鱼王讨伐；鱼王因果可由垂钓引动，或由修仙管理员召唤。"
        members = team.get("members") or []
        return (f"【{team.get('owner_name', '垂钓者')}的{team.get('name')}讨伐队伍】编号 {team.get('team_id')}\n"
                f"位面：{team.get('plane')}｜血量 {int(team.get('health', 0)):,}/{int(team.get('health_max', 0)):,}\n"
                f"队员：{'、'.join(str(m.get('name') or m.get('id')) for m in members)}（{len(members)}/{FISH_KING_MAX_MEMBERS}）\n"
                "出手：#讨伐鱼王｜伤害榜：#鱼王榜｜离队：#退出鱼王讨伐")
    lines = ["【活跃鱼王讨伐】"]
    state = fk_state(world)
    _fk_expire(state, time.time())
    teams = sorted(state["teams"].values(), key=lambda t: float(t.get("created_at", 0) or 0))
    if not teams:
        return "当前没有正在讨伐的鱼王。钓起鱼王后将在本群创建讨伐队。"
    for team in teams:
        lines.append(f"编号 {team.get('team_id')}｜{team.get('group_id')}群｜{team.get('owner_name')}的{team.get('name')}｜"
                     f"{int(team.get('health', 0)):,}/{int(team.get('health_max', 0)):,}｜队员 {len(team.get('members') or [])}/{FISH_KING_MAX_MEMBERS}")
    return "\n".join(lines)


def fk_status(world: Mapping, plane: str, avg_hp: float, group_id: str = "") -> str:
    row = fk_row(world, plane, avg_hp, group_id)
    if row.get("status") == "inactive":
        return "本群当前没有该位面的鱼王讨伐。"
    pct = 0 if row["health_max"] <= 0 else int(100 * row["health"] / row["health_max"])
    return (f"【{row.get('owner_name', '垂钓者')}的{row['name']}】{plane}\n"
            f"气血：{int(row['health']):,}/{int(row['health_max']):,}（{pct}%）\n"
            f"队伍：{row.get('team_id', '?')}｜成员 {len(row.get('members') or [])}/{FISH_KING_MAX_MEMBERS}")


def fk_join(world: dict, plane: str, uid: str, avg_hp: float,
            group_id: str = "", team_id: str = "", name: str = "") -> tuple[bool, str]:
    state = fk_state(world)
    _fk_expire(state, time.time())
    team_id = str(team_id or "").strip()
    if not team_id and group_id:
        team_id = str(state["group_active"].get(str(group_id)) or "")
    row = state["teams"].get(team_id) if team_id else None
    if not isinstance(row, dict) or row.get("status") != "active":
        return False, "鱼王讨伐队不存在、已结束或已过期。"
    uid = str(uid)
    current_team = state["member_team"].get(uid)
    if current_team and str(current_team) != team_id:
        return False, f"你已加入鱼王队伍【{current_team}】，请先退出。"
    members = list(row.get("members") or [])
    if any(str(m.get("id")) == uid for m in members):
        return False, "你已在此战中。"
    if len(members) >= FISH_KING_MAX_MEMBERS:
        return False, f"鱼王讨伐队最多 {FISH_KING_MAX_MEMBERS} 人。"
    members.append({"id": uid, "name": str(name or uid)})
    row["members"] = members
    state["member_team"][uid] = team_id
    fk_put(world, row, str(row.get("group_id") or ""))
    return True, f"你已加入【{row['name']}】讨伐队伍 {team_id}（{len(members)}/{FISH_KING_MAX_MEMBERS}）。"


def fk_leave(world: dict, uid: str) -> tuple[bool, str]:
    state = fk_state(world)
    team_id = str(state["member_team"].get(str(uid)) or "")
    row = state["teams"].get(team_id)
    if not isinstance(row, dict):
        return False, "你当前没有鱼王讨伐队伍。"
    if row.get("status") != "active":
        return False, "鱼王已进入结算，不能退出队伍。"
    if str(row.get("owner_id")) == str(uid):
        return False, "你是钓起鱼王的人，必须留在岸边维持钓线。"
    row["members"] = [m for m in row.get("members", []) if str(m.get("id")) != str(uid)]
    state["member_team"].pop(str(uid), None)
    fk_put(world, row, str(row.get("group_id") or ""))
    return True, f"已退出鱼王讨伐队伍 {team_id}。"


def _sample_without_replacement(pool: list[Mapping], count: int, rng: random.Random) -> list[Mapping]:
    remaining = list(pool)
    selected = []
    while remaining and len(selected) < count:
        idx = min(len(remaining) - 1, int(rng.random() * len(remaining)))
        selected.append(remaining.pop(idx))
    return selected


def _range_amount(item: Mapping, rng: random.Random) -> int:
    bounds = item.get("range") or (1, 1)
    return int(bounds[0]) + int(rng.random() * (int(bounds[1]) - int(bounds[0]) + 1))


def fk_kill_rewards(row: dict, rng: random.Random) -> tuple[dict[str, dict[str, int]], dict[str, list[dict]]]:
    if isinstance(row.get("reward_assignments"), dict) and isinstance(row.get("relic_rewards"), dict):
        return row["reward_assignments"], row["relic_rewards"]
    assignments: dict[str, dict[str, int]] = {}
    relics: dict[str, list[dict]] = {}
    for member in row.get("members") or []:
        uid = str(member.get("id") or "")
        rewards: dict[str, int] = {}
        relic_list = []
        for item in _sample_without_replacement(list(FISH_KING_KILL_POOL), FISH_KING_KILL_GROUPS, rng):
            if item.get("special") == "relic":
                from . import relic as relic_mod
                relic_list.append(relic_mod.roll_fish_king(str(row.get("plane") or ""), rng))
                continue
            if item.get("special") == "bait":
                name, cls = rng.choice(baits()), "道具"
            else:
                name, cls = str(item["name"]), str(item["class"])
            qty = int(item.get("amount") or _range_amount(item, rng))
            rewards[name] = rewards.get(name, 0) + qty
        assignments[uid] = rewards
        relics[uid] = relic_list
    row["reward_assignments"] = assignments
    row["relic_rewards"] = relics
    return assignments, relics


def fk_member_currency(doc: Any) -> dict[str, int]:
    from . import extra_cultivation
    tracks = extra_cultivation.levels_of(doc)
    levels = [int(doc.realm_index) + 1, int(doc.physique_index) + 1,
              tracks["mijing"], tracks["xiangu"], tracks["huafen"]]
    multiplier = 1
    for level in levels:
        multiplier *= max(1, level)
    cultivation = FISH_KING_KILL_CULTIVATION_BASE * multiplier
    return {"stones": FISH_KING_KILL_LINGSHI, "yuanshi": FISH_KING_KILL_SOURCE_STONE,
            "exp": cultivation, "xueqi": cultivation}

def fk_resolve_battle(world: dict, team_id: str, uid: str, won: bool, bonus_damage: int,
                      now: float, rng: random.Random, cooldown_reduction: int = 0
                      ) -> tuple[bool, str, dict[str, Any]]:
    state = fk_state(world)
    row = state["teams"].get(str(team_id))
    if not isinstance(row, dict) or row.get("status") != "active":
        return False, "鱼王队伍不存在或已经结束。", {}
    uid = str(uid)
    if uid not in {str(m.get("id")) for m in row.get("members", [])}:
        return False, "你不是本场鱼王讨伐队员。", {}
    cd = max(0, FISH_KING_BATTLE_CD_SECONDS - min(
        FISH_KING_DAO_ART_REDUCTION_SECONDS, int(cooldown_reduction)))
    last = float((row.get("battle_cd") or {}).get(uid, 0) or 0)
    if now - last < cd:
        return False, f"鱼王之战后尚需 {int(cd - (now - last)) // 60 + 1} 分钟调息。", {}
    health_max = max(1, int(row.get("health_max") or 1))
    base = int(health_max * (0.15 if won else 0.05))
    damage = max(1, min(int(health_max * FISH_KING_DAMAGE_CAP_RATIO), base + max(0, int(bonus_damage))))
    row["health"] = max(0, int(row.get("health", 0) or 0) - damage)
    row.setdefault("damage", {})[uid] = int((row.get("damage") or {}).get(uid, 0) or 0) + damage
    row.setdefault("battle_cd", {})[uid] = now
    rescue = None
    rescue_damage = 0
    if not won and rng.random() < FISH_KING_RESCUE_CHANCE:
        rescue = "如梦" if rng.random() < 0.5 else "莫晓羽"
        rescue_damage = min(int(row["health"]), int(health_max * FISH_KING_DAMAGE_CAP_RATIO))
        row["health"] = max(0, int(row["health"]) - rescue_damage)
        row["damage"][uid] += rescue_damage
    killed = int(row.get("health", 0) or 0) <= 0
    payload = {"team_id": str(team_id), "damage": damage, "rescue": rescue,
               "rescue_damage": rescue_damage, "killed": killed,
               "members": list(row.get("members") or [])}
    if killed:
        row["status"] = "settling"
        row["killed_at"] = now
        assignments, relics = fk_kill_rewards(row, rng)
        payload.update({"assignments": assignments, "relics": relics, "owner_id": str(row.get("owner_id") or "")})
    fk_put(world, row, str(row.get("group_id") or ""))
    result = (f"你{'击败' if won else '不敌'}【{row['name']}·潮汐化身】，为鱼王本体造成 {damage:,} 伤害。"
              f"{f'【{rescue}救场】额外削去 {rescue_damage:,}。' if rescue else ''}"
              f"鱼王本体剩余 {int(row['health']):,}/{health_max:,}。")
    if killed:
        result += " 鱼王气息断绝，队伍击杀奖励已生成。"
    return True, result, payload


def fk_mark_member_settled(world: dict, team_id: str, uid: str) -> None:
    state = fk_state(world)
    row = state["teams"].get(str(team_id))
    if isinstance(row, dict):
        paid = set(str(x) for x in row.get("settled_members", []))
        paid.add(str(uid))
        row["settled_members"] = sorted(paid)
        if {str(m.get("id")) for m in row.get("members", [])} <= paid:
            row["status"] = "defeated"
            state["group_active"].pop(str(row.get("group_id") or ""), None)
            for member in row.get("members", []):
                member_uid = str(member.get("id") or "")
                if state["member_team"].get(member_uid) == str(team_id):
                    state["member_team"].pop(member_uid, None)
        fk_put(world, row, str(row.get("group_id") or ""))


def fk_rank(world: Mapping, plane: str = "", avg_hp: float = 0, group_id: str = "",
            team_id: str = "") -> str:
    row = fk_team(world, team_id=team_id, group_id=group_id) if (team_id or group_id) else None
    if row is None and plane:
        row = fk_row(world, plane, avg_hp, group_id)
    if not row:
        return "未找到鱼王讨伐战绩。"
    rows = sorted((row.get("damage") or {}).items(), key=lambda kv: -int(kv[1]))
    members = {str(m.get("id")): str(m.get("name") or m.get("id")) for m in row.get("members", [])}
    lines = [f"【{row.get('name', '鱼王')}·伤害榜】队伍 {row.get('team_id', '?')}"]
    lines.extend(f"{i}. {members.get(str(uid), str(uid))}｜{int(dmg):,}"
                 for i, (uid, dmg) in enumerate(rows[:10], 1))
    return "\n".join(lines)


def fk_roll_chest(rng: random.Random, count: int = 1) -> tuple[dict[str, int], str]:
    count = max(1, min(9999, int(count)))
    rewards: dict[str, int] = {SCALE_ITEM: 0}
    for _ in range(count):
        rewards[SCALE_ITEM] += _range_amount({"range": FISH_KING_CHEST_SCALE_RANGE}, rng)
        if rng.random() < FISH_KING_CHEST_REWARD_CHANCE:
            for item in _sample_without_replacement(list(FISH_KING_CHEST_POOL), FISH_KING_CHEST_GROUPS, rng):
                if item.get("special") == "bait":
                    name = rng.choice(baits())
                else:
                    name = str(item["name"])
                rewards[name] = rewards.get(name, 0) + int(item.get("amount") or _range_amount(item, rng))
    return {k: v for k, v in rewards.items() if v > 0}, f"鱼王宝箱 ×{count} 开启完成。愿鳞为每箱保底奖励。"
