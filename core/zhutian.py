"""诸天镜主线系统（对齐原版 model/zhutianMirror.js 的 Python 直译，MVP 脊柱）。

- 镜阶 1-7（每日镜能 energyMax 重置）、淬炼材料表、10 世界投影门槛、探索掉落、化身装载——全部公式对齐原版
- 材料（镜尘/世界残响/位面晶核/时空锚/诸天镜心）、世界印记、库洛牌存 ext["zhutian"]，不入纳戒（原版同）
- 简化：元神资源（我们无此字段）、化身进阶体系、卡组编组/试炼、时间线干涉；投影剧情为原创简化分支（原版为长文案事件链）
"""

from __future__ import annotations
from .clock import day_key

import copy
import random
import time
from typing import Any, Mapping

# ---- 原版配置直译 ----

MIRROR_TIERS: dict[int, dict] = {
    1: {"name": "一阶·初映", "energy": 3},
    2: {"name": "二阶·寻界", "energy": 4},
    3: {"name": "三阶·锚定", "energy": 5},
    4: {"name": "四阶·破界", "energy": 6},
    5: {"name": "五阶·界海", "energy": 8},
    6: {"name": "六阶·诸天", "energy": 10},
    7: {"name": "七阶·彼岸", "energy": 12},
}

WORLD_MIN_TIER: dict[str, int] = {
    "魔卡少女樱": 1, "魔女之旅": 1, "魔法少女小圆": 2, "假面骑士帝骑": 3,
    "星穹铁道·匹诺康尼": 3, "万道争锋": 4, "崩坏宇宙": 4, "剑渊古路": 5,
    "一剑独尊": 5, "星海归墟": 6,
}

REFINE_REQ: dict[int, dict[str, int]] = {
    1: {"镜尘": 50, "世界残响": 10, "世界印记": 1},
    2: {"镜尘": 120, "世界残响": 30, "位面晶核": 1, "世界印记": 2},
    3: {"镜尘": 250, "世界残响": 60, "位面晶核": 3, "世界印记": 3},
    4: {"镜尘": 450, "世界残响": 100, "位面晶核": 6, "时空锚": 1},
    5: {"镜尘": 800, "位面晶核": 10, "时空锚": 3, "世界印记": 5},
    6: {"镜尘": 1500, "世界印记": 7, "诸天镜心": 1},
}
# 6 阶淬炼到 7 阶用 REFINE_REQ[6]；1-5 阶用同键（原版键 = 目标阶-1 亦同构，此处按"升到 N 阶消耗 REQ[N-1]"语义对齐）

PROJECTION_COST = {"exp": 100_000_000, "xueqi": 100_000_000, "energy": 1}
AVATAR_SWITCH_CD = 15 * 60

# 化身灵根快照（原版 ROOT 直译；攻防血为比例加成，我们转 ext["avatar_buff"]）
AVATAR_ROOTS: dict[str, dict] = {
    "木之本樱": {"name": "木之本樱", "type": "魔卡少女", "eff": 0.4, "atk": 0.5, "def": 0.5, "hp": 0.5, "rarity": 5},
    "鹿目圆": {"name": "鹿目圆", "type": "魔法少女", "eff": 1.25, "atk": 1.0, "def": 1.0, "hp": 1.0, "rarity": 5},
    "门矢士": {"name": "门矢士", "type": "假面驾驭", "eff": 1.0, "atk": 0.25, "def": 0.25, "hp": 0.25, "rarity": 5},
}

LOCATIONS: dict[str, dict[str, dict]] = {
    "魔卡少女樱": {
        "友枝小学": {"min": 1, "cards": ["影", "静", "歌", "眠", "声", "灯", "花", "甘", "小"]},
        "企鹅公园": {"min": 1, "cards": ["风", "翔", "跳", "树", "雨", "云", "浮", "力", "泡"]},
        "库洛宅邸": {"min": 2, "cards": ["镜", "锭", "梦", "迷", "幻", "剑", "盾", "替", "秤"]},
        "月峰神社": {"min": 2, "cards": ["光", "暗", "雪", "雾", "岚", "双", "创", "冻"]},
        "东京塔": {"min": 3, "cards": ["火", "水", "地", "雷", "斗", "击", "矢", "波", "砂"]},
        "梦境友枝町": {"min": 4, "cards": ["移", "消", "时", "轮", "戾", "大", "拔", "无"]},
    },
    "魔法少女小圆": {
        "见泷原中学": {"min": 2, "hope": 4, "dust": (5, 4)},
        "蔷薇园魔女结界": {"min": 2, "hope": 6, "dust": (5, 4)},
        "零食魔女结界": {"min": 2, "hope": 7, "dust": (5, 4)},
        "人鱼魔女结界": {"min": 3, "hope": 9, "dust": (5, 4)},
        "魔女之夜": {"min": 4, "hope": 14, "dust": (5, 4)},
    },
    "假面骑士帝骑": {
        "光写真馆": {"min": 3, "cards": ["空我", "亚极陀", "龙骑"]},
        "骑士大战遗迹": {"min": 3, "cards": ["Faiz", "剑", "响鬼"]},
        "世界融合点": {"min": 3, "cards": ["甲斗", "电王", "Kiva"]},
        "大修卡基地": {"min": 4, "cards": ["Decade", "Diend", "王权Decade"]},
        "极光帷幕深处": {"min": 5, "cards": ["Decade", "Diend", "王权Decade"]},
    },
}

# 投影剧情分支（原创简化：3 选项对应 慧/勇/仁 三答，奖励档位不同）
STORIES: dict[str, list[dict]] = {
    "魔卡少女樱": [{
        "title": "库洛牌的试炼",
        "scene": "镜光深处，友枝小学的黄昏教室里浮着一本无字之书。风停下时，书页自己翻开了。",
        "options": [
            "以静制动，读懂书页上的轨迹再出手（慧）",
            "直接以雷之牌轰开书页（勇）",
            "唤出「镜」牌映照书中世界（仁）",
        ],
    }],
    "魔法少女小圆": [{
        "title": "魔女结界的低语",
        "scene": "结界中心的蔷薇缠绕成摇篮，摇篮里传出既像哭又像笑的声音。一只白色的生物注视着你。",
        "options": [
            "观察结界的纹路，寻找核心（慧）",
            "以血气破开蔷薇直入摇篮（勇）",
            "把最后一块点心分给哭泣的声音（仁）",
        ],
    }],
    "假面骑士帝骑": [{
        "title": "世界融合点",
        "scene": "九个世界的天空在头顶互相渗透，一条极光帷幕横亘眼前。帷幕后的身影举起了卡片。",
        "options": [
            "读取帷幕的波动频率（慧）",
            "变身正面突进（勇）",
            "张开手掌示意「我只是过路的旅行者」（仁）",
        ],
    }],
}
STORY_DEFAULT = [{
    "title": "诸天投影",
    "scene": "镜光展开，异界的风扑面而来。这里有属于它的故事，也有属于你的机缘。",
    "options": ["谨慎探查此界规则（慧）", "以力破局，横推而过（勇）", "与相遇之人结善缘（仁）"],
}]


def _now() -> float:
    return time.time()


def _date_key(ts: float) -> str:
    return day_key(ts)


def system_of(doc: Mapping) -> dict:
    """取 ext["zhutian"] 系统档的深拷贝（纯函数：修改返回值不会污染原档案，由调用方写回）。"""
    zt = (doc.ext.get("zhutian") if isinstance(doc.ext, Mapping) else None)
    zt = copy.deepcopy(zt) if isinstance(zt, dict) else {}
    zt.setdefault("bound", False)
    zt.setdefault("tier", 0)
    zt.setdefault("energy", 0)
    zt.setdefault("energy_date", "")
    zt.setdefault("materials", {"镜尘": 0, "世界残响": 0, "位面晶核": 0, "时空锚": 0, "诸天镜心": 0})
    zt.setdefault("imprints", [])
    zt.setdefault("avatars", {})          # name -> {"root": {...}, "stage": 1}
    zt.setdefault("current", "")          # 空 = 本源
    zt.setdefault("origin_root", None)    # 本源灵根快照
    zt.setdefault("switch_ts", 0.0)
    zt.setdefault("clow_cards", [])
    zt.setdefault("rider_cards", [])
    zt.setdefault("hopes", 0)
    zt.setdefault("explored", 0)
    return zt


def daily_reset(zt: dict) -> bool:
    """每日镜能重置到当前镜阶上限。返回是否发生重置。"""
    today = _date_key(_now())
    if zt.get("energy_date") != today:
        zt["energy_date"] = today
        cap = MIRROR_TIERS.get(int(zt.get("tier") or 1), {}).get("energy", 3)
        zt["energy"] = cap
        return True
    return False


def bind(doc: Mapping) -> tuple[bool, str, dict]:
    """使用诸天镜：绑定镜系统（1 阶 + 今日镜能）。"""
    zt = system_of(doc)
    if zt.get("bound"):
        return False, "道友的诸天镜早已认主（镜阶 %s）。" % MIRROR_TIERS[int(zt["tier"])]["name"], zt
    zt["bound"] = True
    zt["tier"] = 1
    zt["energy_date"] = ""
    daily_reset(zt)
    return True, "诸天镜认主！镜光初映——当前一阶·初映，今日镜能 %d 点。用「#诸天世界」看看可以投影哪些世界。", zt


def missing_refine(zt: dict) -> tuple[int, dict[str, int] | None]:
    """下一阶淬炼需求。返回 (目标阶, 需求表)；已满阶返回 (0, None)。
    升到 N 阶消耗 REQ[N-1]（1→2 用 REQ[1]，6→7 用 REQ[6]），与原版键语义一致。
    """
    tier = int(zt.get("tier") or 0)
    nxt = tier + 1
    if nxt > 7:
        return 0, None
    req = REFINE_REQ.get(min(max(nxt - 1, 1), 6))
    return nxt, dict(req) if req else None


def refine(doc: Mapping) -> tuple[bool, str, dict]:
    """淬炼诸天镜：材料满足则升阶。"""
    zt = system_of(doc)
    if not zt.get("bound"):
        return False, "尚未绑定诸天镜。", zt
    nxt, req = missing_refine(zt)
    if not req:
        return False, "诸天镜已臻七阶·彼岸，镜照万界，再无可淬。", zt
    mats = zt["materials"]
    imprints = zt.get("imprints") or []
    lack: dict[str, int] = {}
    for k, v in req.items():
        have = len(imprints) if k == "世界印记" else int(mats.get(k, 0))
        if have < v:
            lack[k] = v - have
    if lack:
        detail = "、".join(f"{k}（缺{v}）" for k, v in lack.items())
        return False, f"淬炼材料不足：{detail}。探索诸天世界可获取。", zt
    for k, v in req.items():
        if k == "世界印记":
            del imprints[:v]
        else:
            mats[k] = int(mats.get(k, 0)) - v
    zt["tier"] = nxt
    info = MIRROR_TIERS[nxt]
    daily_reset(zt)  # 晋阶立即补满镜能
    zt["energy"] = info["energy"]
    return True, (f"镜光大盛！诸天镜淬炼至 {info['name']}，"
                  f"每日镜能上限 {info['energy']}，可投影更多世界（#诸天世界）。"), zt


def explore(doc: Mapping, world: str, place: str, rng: random.Random) -> tuple[bool, str, dict]:
    """探索一个地点：镜能 -1，掉落对齐原版公式。"""
    zt = system_of(doc)
    if not zt.get("bound"):
        return False, "尚未绑定诸天镜。", zt
    daily_reset(zt)
    spots = LOCATIONS.get(world)
    if not spots:
        return False, f"「{world}」暂未开放探索（投影系统已支持）。", zt
    loc = spots.get(place)
    if not loc:
        return False, f"「{world}」的探索地点：{'、'.join(spots)}。", zt
    if int(zt["tier"]) < int(loc["min"]):
        return False, f"镜阶不足：{place} 需 {loc['min']} 阶诸天镜（当前 {zt['tier']} 阶）。", zt
    if int(zt["energy"]) < 1:
        return False, "镜能已尽（每日恢复），明日再来。", zt
    zt["energy"] = int(zt["energy"]) - 1
    zt["explored"] = int(zt.get("explored", 0)) + 1
    mats = zt["materials"]
    parts = []
    if world == "魔卡少女樱":
        dust = 4 + rng.randrange(3)
        mats["镜尘"] += dust
        parts.append(f"镜尘 ×{dust}")
        if rng.random() < 0.35:
            mats["世界残响"] += 1
            parts.append("世界残响 ×1")
        owned = set(zt.get("clow_cards") or [])
        unowned = [c for c in loc["cards"] if c not in owned]
        if unowned and rng.random() < 0.65:
            card = rng.choice(unowned)
            zt.setdefault("clow_cards", []).append(card)
            parts.append(f"封印库洛牌「{card}」！")
        key_in = (int(zt.get("explored", 0)) >= 8) or (rng.random() < 0.14)
        if key_in and "魔法少女小圆" not in zt["imprints"]:
            zt["imprints"].append("魔法少女小圆")
            parts.append("✦ 世界印记「魔法少女小圆」入手！")
        msg = f"探索 {place}：{'，'.join(parts) or '一无所获'}。（镜能余 {zt['energy']}）"
        return True, msg, zt
    if world == "魔法少女小圆":
        dust = 5 + rng.randrange(4)
        mats["镜尘"] += dust
        parts.append(f"镜尘 ×{dust}")
        if rng.random() < 0.45:
            mats["世界残响"] += 1
            parts.append("世界残响 ×1")
        hope = int(loc["hope"])
        zt["hopes"] = int(zt.get("hopes", 0)) + hope
        parts.append(f"希望碎片 ×{hope}")
        if rng.random() < 0.35:
            parts.append("获得悲叹之种×1（污浊净化素材）")
        if "魔法少女小圆" not in zt["imprints"] and int(zt.get("hopes", 0)) >= 30:
            zt["imprints"].append("魔法少女小圆")
            parts.append("✦ 世界印记「魔法少女小圆」入手！")
        msg = f"探索 {place}：{'，'.join(parts)}。（镜能余 {zt['energy']}）"
        return True, msg, zt
    if world == "假面骑士帝骑":
        dust = 6 + rng.randrange(4)
        mats["镜尘"] += dust
        parts.append(f"镜尘 ×{dust}")
        if rng.random() < 0.45:
            mats["世界残响"] += 1
            parts.append("世界残响 ×1")
        owned = set(zt.get("rider_cards") or [])
        unowned = [c for c in loc["cards"] if c not in owned]
        if unowned and rng.random() < 0.6:
            card = rng.choice(unowned)
            zt.setdefault("rider_cards", []).append(card)
            parts.append(f"收录骑士卡「{card}」！")
        if "假面骑士帝骑" not in zt["imprints"] and len(zt.get("rider_cards") or []) >= 9:
            zt["imprints"].append("假面骑士帝骑")
            parts.append("✦ 世界印记「假面骑士帝骑」入手！")
        msg = f"探索 {place}：{'，'.join(parts)}。（镜能余 {zt['energy']}）"
        return True, msg, zt
    return False, "未知世界。", zt


def begin_projection(
    doc: Mapping, world: str, now: float,
) -> tuple[bool, str, dict, dict | None]:
    """投影诸天：扣资源与镜能，返回剧情分支。ext 写入由调用方负责。"""
    zt = system_of(doc)
    if not zt.get("bound"):
        return False, "尚未绑定诸天镜。", zt, None
    daily_reset(zt)
    need_tier = WORLD_MIN_TIER.get(world)
    if not need_tier:
        return False, f"未知世界「{world}」。可用：{'、'.join(WORLD_MIN_TIER)}。", zt, None
    if int(zt["tier"]) < need_tier:
        return False, f"镜阶不足：{world} 需 {need_tier} 阶诸天镜（当前 {zt['tier']} 阶）。", zt, None
    if int(zt["energy"]) < PROJECTION_COST["energy"]:
        return False, "镜能不足（每日恢复）。", zt, None
    from .projection_story import select_event
    story = select_event(zt, world, random.Random(f"{world}:{now}"))
    if story is None:
        return False, f"{world} 当前没有可继续的探索剧情。", zt, None
    zt["energy"] = int(zt["energy"]) - 1
    proj = {"world": world, "ts": now, "event_id": story["id"], "title": story["title"], "scene": story["scene"], "options": [o["text"] for o in story["options"]], "max_choice": len(story["options"])}
    text = (f"神魂没入镜光，投影【{world}】！\n"
            f"【{story['title']}】\n{story['scene']}\n"
            + "\n".join(f"{i + 1}. {o['text']}" for i, o in enumerate(story["options"]))
            + "\n15 分钟内「#选择 序号」作出抉择。")
    return True, text, zt, proj


def rng_story(world: str) -> dict:
    pool = STORIES.get(world) or STORY_DEFAULT
    return pool[0] if len(pool) == 1 else dict(random.Random(world).choice(pool))


def resolve_projection(
    doc: Mapping, proj: Mapping, choice: int, rng: random.Random,
) -> tuple[str, dict]:
    """分支结算：慧/勇/仁 三答给不同档位奖励（镜尘/残响/晶核概率/化身线索）。"""
    zt = system_of(doc)
    if proj.get("event_id"):
        from .projection_story import resolve_event
        resolution_id = f"{getattr(doc, 'uid', '')}:{proj.get('ts', '')}:{int(choice)}"
        ok, tail, _next = resolve_event(
            zt, str(proj["event_id"]), int(choice), resolution_id=resolution_id)
        if not ok:
            return tail, zt
        state = (zt.get("exploration") or {}).get(str(proj.get("world", "")), {})
        pending = str(state.get("pending") or "")
        if pending:
            from .projection_story import event_by_id
            event = event_by_id(str(proj.get("world", "")), pending)
            if event:
                tail += "\n\n" + f"【后续剧情：{event['title']}】\n{event['scene']}\n"
                tail += "\n".join(f"{i}. {o['text']}" for i, o in enumerate(event["options"], 1))
        return tail, zt
    world = str(proj.get("world", "?"))
    mats = zt["materials"]
    tier = int(zt["tier"])
    if choice == 1:      # 慧：稳档
        dust, echo = 30 + rng.randrange(15), 2 + rng.randrange(2)
        core_p, anchor_p = 0.30, 0.12
    elif choice == 2:    # 勇：高风险高回报
        dust, echo = 45 + rng.randrange(25), 3 + rng.randrange(3)
        core_p, anchor_p = 0.40, 0.20
    else:                # 仁：均衡+印记倾向
        dust, echo = 35 + rng.randrange(15), 2 + rng.randrange(3)
        core_p, anchor_p = 0.30, 0.15
    mats["镜尘"] += dust
    parts = [f"镜尘 ×{dust}", f"世界残响 ×{echo}"]
    mats["世界残响"] += echo
    if tier >= 3 and rng.random() < core_p:
        mats["位面晶核"] += 1
        parts.append("位面晶核 ×1")
    if tier >= 4 and rng.random() < anchor_p:
        mats["时空锚"] += 1
        parts.append("时空锚 ×1")
    if tier >= 6 and rng.random() < 0.10:
        mats["诸天镜心"] += 1
        parts.append("诸天镜心 ×1 ✦")
    if world not in zt["imprints"]:
        zt["imprints"].append(world)
        parts.append(f"✦ 首次投影！世界印记「{world}」入手")
    # 仁之答额外：小概率直接收录化身
    avatar_line = ""
    if choice == 3 and rng.random() < 0.35:
        base = {"魔卡少女樱": "木之本樱", "魔法少女小圆": "鹿目圆", "假面骑士帝骑": "门矢士"}.get(world)
        if base and base not in zt["avatars"]:
            zt["avatars"][base] = {"root": dict(AVATAR_ROOTS[base]), "stage": 1}
            avatar_line = f"\n✦ 化身【{base}】收入化身谱！（#装载化身 {base}）"
        elif base:
            avatar_line = f"\n（{base} 的化身之力共鸣了……尚无新收获）"
    tail = f"投影【{world}】归返：{'，'.join(parts)}。{avatar_line}"
    return tail, zt


def load_avatar(doc: Mapping, name: str, now: float) -> tuple[bool, str, dict, dict | None]:
    """装载化身/本源：灵根替换 + 攻防血 buff。返回 (ok, msg, zt, avatar_buff)。
    avatar_buff 非空时调用方写 ext["avatar_buff"]；本源返回 {} 表示清除。
    """
    zt = system_of(doc)
    if not zt.get("bound"):
        return False, "尚未绑定诸天镜。", zt, None
    target = (name or "").strip() or "本源"
    current = zt.get("current") or "本源"
    if target == current:
        return False, f"当前已是「{current}」，无需重复装载。", zt, None
    if now - float(zt.get("switch_ts", 0.0)) < AVATAR_SWITCH_CD:
        remain = int((AVATAR_SWITCH_CD - (now - float(zt.get("switch_ts", 0.0)))) / 60) + 1
        return False, f"化身切换冷却中（约 {remain} 分钟后可再切换）。", zt, None
    if int(zt.get("energy", 0)) < 1:
        return False, "镜能不足（每日恢复）。", zt, None
    zt["energy"] = int(zt["energy"]) - 1
    zt["switch_ts"] = now
    if target == "本源":
        zt["current"] = ""
        return True, "灵根归于本源。化身之力沉眠镜中。", zt, {}
    av = (zt.get("avatars") or {}).get(target)
    if not av:
        return False, (f"化身谱中没有「{target}」。已收录：{'、' .join(zt['avatars']) or '（无）'}。"), zt, None
    zt["current"] = target
    root = dict(av["root"])
    buff = {"atk": float(root.get("atk", 0)), "def": float(root.get("def", 0)), "hp": float(root.get("hp", 0))}
    return True, (f"化身【{target}】降临！修炼效率 +{root.get('eff', 0):g}，"
                  f"三维 +{buff['atk']:.0%}（15 分钟后可切换回本源）。"), zt, buff


def avatar_buff_of(doc: Mapping) -> dict:
    """当前生效的化身三维加成（aggregate 并入）。"""
    zt = doc.ext.get("zhutian") if isinstance(doc.ext, Mapping) else None
    if isinstance(zt, dict) and zt.get("current"):
        av = (zt.get("avatars") or {}).get(str(zt["current"]))
        if av:
            root = av.get("root") or {}
            return {"atk": float(root.get("atk", 0)), "def": float(root.get("def", 0)),
                    "hp": float(root.get("hp", 0))}
    return {}
