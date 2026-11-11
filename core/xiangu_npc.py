"""仙古秘境 NPC 交互（W26）——原版 `xianguPlace.js` NPC 交互段
（交谈 L9364 / 购买 L9505 / 攻击 L9570 / 击杀掉落 L9768 / 搜魂 L9846 /
组队 L10205 / 好感 L10148）+ `xianguNpc.js` 生态 + `xianguLegacy.js` 执念冠冕。

对齐设计（用户确认：交互全做、生态简化）：
- 三源 NPC：区域静态 NPC（含道种贩者交易表）+ 原著天骄 canon（6 位执念）+
  随机修士（W25 generate_npc）。绑定改为进入碎片时一次性分配（原版每图重抽）。
- NPC 属性：原版按四境界表合成（攻 3 亿级），端口无独立轨 → 相对玩家缩放
  （atk ×1.5 / hp ×1.2 / canon ×2.2 / ×2.6），docstring 登记为 shortcut。
- 生态简化：原版 BFS 寻路 + 每秒世界 tick；端口在移动/探索指令内联触发
  「邻格遭遇」（敌意猎杀 / 诡诈 / 结交），NPC 不再自行移动寻宝。
- 全服幂等：NPC 死亡名额存 calamity_state["xiangu"]["npc_deaths"][scope]
  （原版 Redis claimXianguNpcDeath），先到先得，重复攻击收到「已陨」。
- 搜魂窗口 5 分钟（原版一致），成功率 75%/canon 60%，单门 80%，业力 +20/30。
- 组队：好感≥50 或 friendly；组队后战斗回调由 handler 给玩家 +20% 攻/血
  （原版友方独立单位，端口战斗引擎为 1v1，登记 shortcut）；scheming 且好感
  <100 时 30% 背叛（改为战前反噬：损失 10% 当前血量）。

rng 约定：只用 rng.random()。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from . import xiangu as xg

# ---------------------------------------------------------------- 静态 NPC（原版 XIANGU_NPCS，价格 ÷1000）

STATIC_NPCS: dict[str, tuple[dict, ...]] = {
    "边缘区域": (
        {"id": "wandering_monk", "name": "流浪修士", "faction": "neutral",
         "title": "行走天地间",
         "desc": "一名身着灰袍的修士，目光深沉，似乎在寻找着什么。",
         "dialogs": ("秘境之中，危机四伏，道友当有自保之力。",
                     "你也是来寻机缘的？此地不比凡间，处处凶险。",
                     "听说深处有十凶的遗种，胆大者或可一试。"),
         "trade": None, "hostile": False},
        {"id": "ancient_guide", "name": "古仙引路者", "faction": "good",
         "title": "前路指引",
         "desc": "身形虚幻，似乎是某位古仙的残留意志，散发着柔和的金光。",
         "dialogs": ("有缘人，此处乃仙古秘境边缘，深处机缘无数，但也险象环生。",
                     "道种乃此间最珍贵之物，融合可引燃神火，成就神火境！",
                     "善良之心，可感天地。在此处杀戮过重，天地法则会排斥于你。"),
         "trade": None, "hostile": False},
    ),
    "中层区域": (
        {"id": "dao_seed_trader", "name": "道种贩者", "faction": "neutral",
         "title": "以物易物",
         "desc": "一名神秘的黑衣人，腰间挂满了各色种子，散发着奇异的气息。",
         "dialogs": ("哦？你也有道种？本座可以用灵石换你的。",
                     "想要稀有道种？拿出你认为合适的价格来吧。",
                     "道种乃修道根基，切莫轻易示人，以免招来杀身之祸。"),
         "trade": {"items": (
             {"name": "普通道种碎片", "price": 2_000, "currency": "灵石"},
             {"name": "稀有道种碎片", "price": 20, "currency": "灵石"},
             {"name": "传说道种碎片", "price": 80, "currency": "灵石"})},
         "hostile": False},
        {"id": "ancient_heritage", "name": "古老传承者", "faction": "good",
         "title": "传道解惑",
         "desc": "一名白发苍苍的老者，眼中蕴含着岁月沉淀的智慧。",
         "dialogs": ("老朽在此等待数千年，终于等到有缘人。",
                     "传承不可轻授，心术不正者纵然叩首也难闻一语。"),
         "trade": None, "hostile": False},
        {"id": "fallen_monk", "name": "堕道修士", "faction": "evil",
         "title": "掠夺为生",
         "desc": "双目赤红的修士，周身缠绕着若有若无的黑气。",
         "dialogs": ("哼，将你的东西交出来！",
                     "这秘境中，弱肉强食才是唯一的法则。"),
         "trade": None, "hostile": True, "hostile_threshold": 20},
    ),
    "深层区域": (
        {"id": "ancient_emperor_shadow", "name": "古帝虚影", "faction": "good",
         "title": "帝念残存",
         "desc": "一尊模糊的巨大虚影盘坐虚空，眉心有一点帝光明灭。",
         "dialogs": ("……后来者……执念不可过重……",
                     "帝路尽头，唯『唯一』可存。"),
         "trade": None, "hostile": False},
        {"id": "secret_realm_hunter", "name": "秘境猎手", "faction": "neutral",
         "title": "狩机缘为生",
         "desc": "背负长弓的修士，箭囊里的箭簇都刻着锁灵纹。",
         "dialogs": ("我的箭只射两种东西：凶兽，和挡路的人。",
                     "前方遗迹凶险，要不要买条路子？"),
         "trade": {"items": ({"name": "远古符纸", "price": 3_000, "currency": "灵石"},
                             {"name": "秘境灵药", "price": 5_000, "currency": "灵石"})},
         "hostile": False},
    ),
    "核心区域": (
        {"id": "core_guide", "name": "接引仙官", "faction": "good",
         "title": "归途引渡",
         "desc": "一袭白衣的仙官立于花蕾道台旁，掌中托着归途法则的纹路。",
         "dialogs": ("花蕾核心，归途所系。欲离秘境者，可由此引动法则。",
                     "道种融合亦须在此处道台完成。"),
         "trade": None, "hostile": False},
    ),
}

# ---------------------------------------------------------------- 原著天骄（canon）+ 执念

CANON_NPCS: dict[str, tuple[dict, ...]] = {
    "核心区域": (
        {"id": "shiguanwang_tianzi", "name": "十冠王天子", "title": "仙古十世冠军·真龙传人",
         "faction": "neutral", "tier": "canon", "xg": 11, "crit": 0.3, "crit_dmg": 2.5,
         "skills": ("真龙宝术", "龙拳", "十世轮回经", "真龙困天术", "天子印", "世界树法则"),
         "dialogs": ("仙古十世，皆我为冠。", "世界树在前，第十一世冠冕亦在前。"),
         "hostile": False, "personality": "proud", "is_canon": True,
         "drop_table": (("世界树残叶", "道具", 0.30), ("真龙精血", "丹药", 0.15),
                        ("天子印碎片", "材料", 0.25)),
         "trade": None},
        {"id": "zhexian", "name": "谪仙", "title": "凶巢布局者·无冕之王",
         "faction": "neutral", "tier": "canon", "xg": 8, "crit": 0.35, "crit_dmg": 3.0,
         "skills": ("天角蚁宝术", "真凰宝术", "凶巢杀阵", "天角蚁战角"),
         "dialogs": ("棋局已布，来者皆是棋子。", "凶巢之中，无冕者王。"),
         "hostile": False, "personality": "scheming", "is_canon": True,
         "drop_table": (("天角蚁宝术残卷", "材料", 0.30), ("真凰精血", "丹药", 0.20),
                        ("凶巢阵纹碎片", "材料", 0.20)),
         "trade": None},
    ),
    "深层区域": (
        {"id": "ningchuan", "name": "六冠王宁川", "title": "六世冠王·轮回不灭",
         "faction": "neutral", "tier": "canon", "xg": 7, "crit": 0.28, "crit_dmg": 2.2,
         "skills": ("六道轮回天功", "轮回拳", "轮回诸天拳"),
         "dialogs": ("六世轮回，唯我依旧。", "第七世冠冕，还差一场杀伐。"),
         "hostile": False, "personality": "scheming", "is_canon": True,
         "drop_table": (("轮回印记", "材料", 0.30), ("六道轮回残卷", "材料", 0.20),
                        ("神魂结晶", "材料", 0.25)),
         "trade": None},
        {"id": "gujian_yun", "name": "孤剑云", "title": "剑谷传人·古代怪胎",
         "faction": "neutral", "tier": "canon", "xg": 7, "crit": 0.32, "crit_dmg": 2.6,
         "skills": ("剑谷剑诀", "天晶剑术", "剑道通神", "万剑归宗"),
         "dialogs": ("剑谷三千，唯我负剑而行。", "大罗剑胎的下落，我也在找。"),
         "hostile": False, "personality": "proud", "is_canon": True,
         "drop_table": (("剑谷剑意碎片", "材料", 0.30), ("天晶剑芒", "材料", 0.25),
                        ("古剑残躯", "材料", 0.15)),
         "trade": None},
        {"id": "dichong", "name": "帝冲", "title": "仙殿传人·九头不死鸟",
         "faction": "evil", "tier": "canon", "xg": 7, "crit": 0.30, "crit_dmg": 2.4,
         "skills": ("仙王九封", "人仙印", "虚空战戟", "不死鸟涅槃法"),
         "dialogs": ("仙殿之内，无起我之上者。", "挡我终极造化者，杀无赦。"),
         "hostile": True, "personality": "proud", "is_canon": True,
         "drop_table": (("仙殿秘术残页", "材料", 0.30), ("不死鸟精血", "丹药", 0.20),
                        ("人仙印碎片", "材料", 0.15)),
         "trade": None},
    ),
    "中层区域": (
        {"id": "honghuang", "name": "红凰", "title": "真凰转世·浴火涅槃",
         "faction": "good", "tier": "canon", "xg": 6, "crit": 0.25, "crit_dmg": 2.0,
         "skills": ("真凰宝术", "红凰弑天决", "涅槃经", "凤凰天火"),
         "dialogs": ("凤凰浴火，涅槃而生。", "火道残则，是我涅槃的钥匙。"),
         "hostile": False, "personality": "friendly", "is_canon": True,
         "drop_table": (("真凰翎羽", "道具", 0.30), ("涅槃精血", "丹药", 0.20),
                        ("凤凰泪", "道具", 0.25)),
         "trade": None},
        {"id": "yaoyue", "name": "邀月公主", "title": "广寒仙子·宇宙雏形",
         "faction": "neutral", "tier": "canon", "xg": 6, "crit": 0.26, "crit_dmg": 2.2,
         "skills": ("广寒仙诀", "月华天章", "宇宙雏形"),
         "dialogs": ("月有阴晴圆缺，道亦有盈亏。", "宇宙雏形种，非有缘者不可见。"),
         "hostile": False, "personality": "proud", "is_canon": True,
         "drop_table": (("广寒玉髓", "材料", 0.25), ("月华露", "丹药", 0.20)),
         "trade": None},
    ),
}

CANON_GOALS: dict[str, dict[str, Any]] = {
    "shiguanwang_tianzi": {"name": "十冠王天子", "action": "contest_arena",
                           "location": "仙古擂台",
                           "objective": "携世界树幼苗登临擂台，续写第十一世冠冕",
                           "target": 3, "historical_crowns": 10},
    "zhexian": {"name": "谪仙", "action": "hunt_player", "location": "凶巢",
                "objective": "以凶巢杀局猎取同代修士，谋取天角蚁传承",
                "target": 2, "historical_crowns": 0},
    "ningchuan": {"name": "六冠王宁川", "action": "hunt_player", "location": "深层区域",
                  "objective": "猎取同代天骄，积蓄第七世冠王气运",
                  "target": 2, "historical_crowns": 6},
    "gujian_yun": {"name": "孤剑云", "action": "seek_item", "location": "虚空夹层",
                   "objective": "搜集三道剑谷剑意碎片，追索大罗剑胎的下落",
                   "item": "剑谷剑意碎片", "target": 3, "historical_crowns": 0},
    "dichong": {"name": "帝冲", "action": "hunt_player", "location": "深层区域",
                "objective": "镇杀仙殿宿敌，以不死身争夺终极造化",
                "target": 2, "historical_crowns": 0},
    "honghuang": {"name": "红凰", "action": "seek_item", "location": "火道禁区",
                  "objective": "搜集两枚真凰翎羽，借火道残则完成涅槃",
                  "item": "真凰翎羽", "target": 2, "historical_crowns": 0},
}

NPC_LOOT = ("普通道种碎片", "仙古矿材", "古兽残骨", "秘境灵药", "远古符纸")

TALK_REWARD_LIMIT = 2          # 每轮每 NPC 可给机缘的交谈次数
TALK_REL_GAIN = (5, 8)         # 交谈好感 +5~8
SOUL_WINDOW_MS = 5 * 60 * 1000
TEAM_CD_MS = 30 * 60 * 1000


def relation_desc(val: float) -> str:
    if val >= 200:
        return "生死之交"
    if val >= 100:
        return "莫逆之交"
    if val >= 50:
        return "友善"
    if val >= 20:
        return "有好感"
    if val >= 0:
        return "陌生"
    if val >= -30:
        return "警惕"
    if val >= -80:
        return "敌视"
    return "仇恨"


def faction_desc(faction: str) -> str:
    return {"good": "善良", "evil": "邪恶"}.get(faction, "中立")


# ---------------------------------------------------------------- 绑定 / 属性合成

def _npc_scale(npc: Mapping, doc: Any, rng: Callable[[], float]) -> dict[str, int]:
    """相对玩家缩放：随机 1.1-1.6 / canon 天子 ×2.6、其余 canon ×2.2。"""
    from . import wallet
    atk = max(1, int(wallet.authority(doc) * 800 + 5_000))
    hp = max(1, int((int(float((getattr(doc, "ext", {}) or {}).get("hp_max", 0) or 0))
                     or 10_000)))
    mult = 2.6 if npc.get("id") == "shiguanwang_tianzi" else \
        (2.2 if npc.get("is_canon") else 1.1 + rng.random() * 0.5)
    atk = int(atk * mult)
    hp = int(hp * (mult * 1.15 if npc.get("is_canon") else mult))
    return {"atk": atk, "hp": max(1, hp)}


def npc_battle_data(npc: Mapping, doc: Any, rng: Callable[[], float]) -> dict[str, Any]:
    s = _npc_scale(npc, doc, rng)
    return {"name": str(npc.get("name") or "神秘修士"),
            "atk": s["atk"], "defense": max(1, int(s["atk"] * 0.7)),
            "hp": s["hp"], "hp_max": s["hp"],
            "bao": float(npc.get("crit", 0.1) or 0.1),
            "orb": 0.12, "crit": float(npc.get("crit_dmg", 1.5) or 1.5),
            "skills": list(npc.get("skills") or ()), "xg_level": int(npc.get("xg", 7) or 7)}


def ensure_bindings(doc: Any, st: dict, rng: Callable[[], float]) -> None:
    """为当前碎片绑定 NPC 实体：静态 + canon（15% 概率登场）+ 随机修士补位。"""
    map_st = st.get("map") or {}
    zone = xg.FRAGMENTS.get(map_st.get("fragment_id", ""), {}).get("zone", "边缘区域")
    infamy = int(st.get("infamy", 0) or 0)
    pool: list[dict] = list(STATIC_NPCS.get(zone, ()))
    for c in CANON_NPCS.get(zone, ()):
        if c.get("hostile") and c.get("hostile_threshold") and infamy < c["hostile_threshold"]:
            continue
        if rng.random() < 0.35:
            pool.append(dict(c))
    for spot in map_st.get("npc_locations", ()):
        if spot.get("npc"):
            continue
        if not pool:
            spot["npc"] = xg.generate_npc(zone, infamy, rng)
            continue
        npc = pool.pop(min(len(pool) - 1, int(rng.random() * len(pool)) % max(1, len(pool))))
        spot["npc"] = {**npc, "inventory": []}


def npc_at(st: Mapping) -> dict | None:
    """玩家所站格的 NPC（原版 getCurrentXianguNpc）。"""
    map_st = st.get("map") or {}
    px, py = map_st.get("pos", {}).get("x"), map_st.get("pos", {}).get("y")
    if px is None:
        return None
    for spot in map_st.get("npc_locations", ()):
        if spot.get("x") == px and spot.get("y") == py and (spot.get("npc") or {}).get("is_alive", True):
            return spot
    return None


def _remove_npc(map_st: dict, spot: dict) -> None:
    if map_st["grid"][spot["y"]][spot["x"]] == xg.CELL_NPC:
        map_st["grid"][spot["y"]][spot["x"]] = spot.get("under_cell", xg.CELL_EMPTY)
    map_st.setdefault("npc_locations", []).remove(spot)


def npc_death_scope(st: Mapping, npc_id: str) -> str:
    return xg.claim_scope(str(st.get("world_seed") or ""),
                          (st.get("map") or {}).get("fragment_id", ""), f"npc:{npc_id}")


def claim_npc_death(world: dict, st: Mapping, npc_id: str, claimant_id: str,
                    claimant_name: str, now: float) -> dict | None:
    """NPC 死亡名额先到先得；返回既有名额（他人）或 None（本Claim成功）。"""
    scope = npc_death_scope(st, npc_id)
    prior = xg.world_claim(world, scope)
    if prior:
        return prior
    xg.world_claim_put(world, scope, claimant_id, claimant_name, now)
    return None


# ---------------------------------------------------------------- 交谈

def _talk_reward_state(st: dict, npc_id: str, now_ms: float) -> dict:
    state = st.setdefault("npc_interactions", {})
    rec = state.get(npc_id)
    if not isinstance(rec, dict) or now_ms - float(rec.get("day_start", 0) or 0) > 86_400_000:
        rec = {"day_start": now_ms, "count": 0, "can_reward": True}
        state[npc_id] = rec
    rec["can_reward"] = int(rec.get("count", 0) or 0) < TALK_REWARD_LIMIT
    return rec


def _marrow_trap_chance(npc: Mapping, relation: float) -> float:
    if npc.get("hostile") or npc.get("personality") == "hostile":
        return 0.75
    if npc.get("personality") == "scheming":
        return 0.6
    if relation < 0:
        return 0.4
    if npc.get("personality") == "friendly" or npc.get("faction") == "good":
        return 0.0
    return 0.1


def talk(doc: Any, st: dict, world: dict, rng: Callable[[], float], now_ms: float,
         cfg: Mapping) -> tuple[str, dict]:
    """#与NPC交谈：好感/对话/canone 执念/隐秘邀请/特殊机缘。"""
    events: dict[str, Any] = {}
    spot = npc_at(st)
    if not spot:
        return ("【NPC·距离过远】\n身边没有可以交谈的修士。\n"
                "使用 #寻找NPC 查看坐标，并移动到NPC格后再交谈。"), events
    npc = spot["npc"]
    npc_id = str(npc.get("id") or npc.get("name"))
    location = str(st.get("location") or "边缘区域")
    rels = st.setdefault("npc_relations", {})
    relation = int(rels.get(npc_id, int((st.get("faction_rep") or {}).get(str(npc.get("faction")), 0) or 0)))
    dialogs = list(npc.get("dialogs") or ("此地机缘与杀劫并存，道友还需谨慎。",))
    lines = [
        f"【NPC遭遇·{location}】", "",
        f"{getattr(doc, 'name', '') or '修士'}在此地偶遇了一位修士：", "",
        f"【{npc.get('name')}】{npc.get('title') or ''}",
        f"阵营：{faction_desc(str(npc.get('faction')))}"
        f"｜关系：{relation_desc(relation)}（{relation:+d}）", "",
        f"“{dialogs[int(rng.random() * len(dialogs)) % len(dialogs)]}”", "",
        "━━━━ 可交互操作 ━━━━",
        "· #攻击NPC / #搜魂NPC（击败后 5 分钟内）",
    ]
    if npc.get("trade"):
        lines.append("· #向NPC购买 查看商品 / #向NPC购买 [物品名]")
    goal = CANON_GOALS.get(npc_id) if npc.get("is_canon") else None
    if goal:
        lines.append(f"· 本轮执念：{goal['objective']}（{goal['target']}）")
    # 隐秘邀请：每轮 2 次机缘名额 × NPC 邀请概率
    rewarded = False
    rw = _talk_reward_state(st, npc_id, now_ms)
    pool_cfg = xg.marrow_config()
    if rw.get("can_reward") and rng.random() < float(cfg.get("npcInviteChance", pool_cfg.get("npc_invite", 0.18))):
        placed = xg.place_marrow_pool(st["map"], rng)
        if placed:
            is_trap = rng.random() < _marrow_trap_chance(npc, relation)
            pool_rec = (st["map"]["unique_treasures"]).get(placed["key"])
            if pool_rec is not None:
                pool_rec["is_trap"] = is_trap
                pool_rec["invited_by"] = npc_id
            rw["count"] = int(rw.get("count", 0) or 0) + 1
            rw["can_reward"] = int(rw.get("count", 0) or 0) < TALK_REWARD_LIMIT
            rewarded = True
            lines += ["", "💧【隐秘邀请】",
                      f"{npc.get('name')}压低声音：",
                      "“我发现一方万道仙髓池，其中仙髓可洗炼根骨。你若有胆，便随这道印记前去。”",
                      f"宝池坐标：[{placed['pos']['x']}, {placed['pos']['y']}]",
                      "这份邀请究竟是善意还是杀局，只能到场方知。"]
            events["pool_key"] = placed["key"]
    # 特殊机缘
    if not rewarded and rw.get("can_reward"):
        if npc_id == "ancient_guide" and rng.random() < 0.3:
            rep = st.setdefault("faction_rep", {})
            rep["good"] = int(rep.get("good", 0) or 0) + 5
            rw["count"] = int(rw.get("count", 0) or 0) + 1
            lines += ["", "古仙引路者感受到你的善念，善良阵营好感 +5"]
            rewarded = True
        elif npc_id == "ancient_emperor_shadow" and int((st.get("faction_rep") or {}).get("good", 0) or 0) >= 50:
            gain = 50 + int(rng.random() * 100)
            gains = st.setdefault("gains", {})
            gains["daoyun"] = int(gains.get("daoyun", 0) or 0) + gain
            rw["count"] = int(rw.get("count", 0) or 0) + 1
            lines += ["", f"古帝虚影赐下帝念，道韵领悟 +{gain}！"]
            rewarded = True
    if not rewarded and int(rw.get("count", 0) or 0) >= TALK_REWARD_LIMIT:
        lines += ["", "对方已给出本轮能给的机缘，只留下片语供你参悟。"]
    return "\n".join(lines), events


# ---------------------------------------------------------------- 购买

def trade_text(st: Mapping) -> str:
    spot = npc_at(st)
    npc = (spot or {}).get("npc") or {}
    trade = npc.get("trade") or {}
    if not trade.get("items"):
        return "【NPC购买·无商人】请移动到可交易NPC所在格，再使用购买命令。"
    lines = ["【NPC商店】", "", f"◇ {npc.get('name')}"]
    for item in trade["items"]:
        lines.append(f"  · {item['name']} — {item['price']}{item['currency']}")
    lines += ["", "提示：#向NPC购买 [物品名] 进行购买"]
    return "\n".join(lines)


def buy(doc: Any, st: dict, item_name: str, rng: Callable[[], float]) -> tuple[bool, str, int]:
    """#向NPC购买 [物品名]。返回 (ok, text, 灵石变动-负数)。"""
    spot = npc_at(st)
    npc = (spot or {}).get("npc") or {}
    trade = npc.get("trade") or {}
    if not trade.get("items"):
        return False, "【NPC购买·无商人】请移动到可交易NPC所在格，再使用购买命令。", 0
    if not item_name:
        return False, trade_text(st), 0
    found = next((i for i in trade["items"] if i["name"] == item_name), None)
    if not found:
        return False, f"未找到物品“{item_name}”，使用 #向NPC购买 查看商品列表", 0
    infamy = int(st.get("infamy", 0) or 0)
    mult = 2.0 if infamy >= 200 else 1.5 if infamy >= 100 else 1.2 if infamy >= 50 else 1.0
    price = int(found["price"] * mult)
    if int(getattr(doc, "stones", 0) or 0) < price:
        return False, (f"【购买失败】灵石不足\n需要：{price:,} 灵石\n"
                       f"拥有：{int(getattr(doc, 'stones', 0) or 0):,} 灵石"
                       + (f"\n凶名溢价：×{mult}（凶名 {infamy}）" if mult > 1 else "")), 0
    xg.bag_add_item(st["bag"], {"name": item_name, "type": "道具", "quantity": 1})
    note = f"\n※ 凶名溢价 ×{mult} 已生效" if mult > 1 else ""
    return True, (f"【购买成功】\n\n从{npc.get('name')}处购得：{item_name}\n"
                  f"花费：{price:,} 灵石（收入秘境背包）{note}"), -price


# ---------------------------------------------------------------- 攻击 / 击杀掉落 / 搜魂

def attack(doc: Any, st: dict, world: dict, rng: Callable[[], float], now_ms: float,
           battle: Callable[[dict, str], tuple[bool, list[str]]] | None,
           claims: Mapping | None = None) -> tuple[str, dict]:
    """#攻击NPC：战斗结算 + 死亡幂等 + 掉落 + 搜魂窗口。"""
    events: dict[str, Any] = {}
    spot = npc_at(st)
    if not spot:
        return "【攻击NPC·无目标】此处没有可攻击的NPC，请先 #寻找NPC 并移动到目标所在格。", events
    npc = spot["npc"]
    npc_id = str(npc.get("id") or npc.get("name"))
    prior = claim_npc_death(world, st, npc_id, str(getattr(doc, "uid", "")),
                            str(getattr(doc, "name") or ""), now_ms / 1000)
    if prior and str(prior.get("claimant")) != str(getattr(doc, "uid", "")):
        _remove_npc(st["map"], spot)
        killer = prior.get("name") or prior.get("claimant") or "另一位天骄"
        return f"【NPC已陨】{npc.get('name')}已被{killer}击杀，本轮仙古不会再次出现。", events
    # 攻击善良 NPC：道德警告不进战斗
    if npc.get("faction") == "good" and not npc.get("hostile") and not npc.get("is_canon") \
            and not npc.get("personality"):
        rep = st.setdefault("faction_rep", {})
        rep["good"] = int(rep.get("good", 0) or 0) - 30
        st["infamy"] = int(st.get("infamy", 0) or 0) + 15
        return "\n".join([
            "【攻击NPC·道德警告】", "",
            f"{getattr(doc, 'name', '')}挥拳袭向{npc.get('name')}，",
            "对方虚影闪动，从容避开，但眼中流露出深深的失望...", "",
            "【后果】凶名 +15｜善良阵营好感 -30", "",
            "“你在此间的所作所为，天地皆有记录...”"]), events

    enemy = npc_battle_data(npc, doc, rng)
    if battle is None:
        won, log_lines = True, ["（演武：跳过战斗）"]
    else:
        won, log_lines = battle(enemy, "xiangu_npc")
    if not won:
        hp_loss = max(1, int(xg._hp_of(doc) * 0.25))
        xg._set_hp(doc, max(1, xg._hp_of(doc) - hp_loss))
        st["infamy"] = max(0.0, float(st.get("infamy", 0) or 0) - max(0, int(st.get("infamy", 0) or 0) - 5))
        st["pending_defeat"] = {"npc": str(npc.get("name")), "faction": str(npc.get("faction")),
                                "expires_at": now_ms + 60_000, "source": "attack"}
        events["pending_defeat"] = True
        return "\n".join([
            "【攻击NPC·战败】", "",
            f"{getattr(doc, 'name', '')}主动挑衅{npc.get('name')}，",
            *log_lines[-3:],
            "却低估了对方的实力，被反手重创，重伤倒地！", "",
            f"【损失】血量 -{hp_loss:,}", "",
            xg._defeat_menu(str(npc.get("name"))),
            "", f"“不自量力...” — {npc.get('name')}冷冷道。"]), events

    # === 胜利：掉落 + 幂等名额 ===
    if claims is not None and prior is None:
        # claims 与 world 为同一 dict（handler 传入 calamity_state["xiangu"]），已在上方登记
        pass
    location = str(st.get("location") or "边缘区域")
    loot_lines = ["【战利品搜刮】"]
    kills = st.setdefault("kills", 0)
    st["kills"] = int(kills) + 1
    st["infamy"] = int(st.get("infamy", 0) or 0) + (2 if npc.get("faction") == "evil" else 5)
    if npc.get("faction") == "evil":
        rep = st.setdefault("faction_rep", {})
        rep["good"] = int(rep.get("good", 0) or 0) + 10
    defeated = st.setdefault("defeated_npcs", [])
    if npc_id not in defeated:
        defeated.append(npc_id)
    # 纳戒搜刮
    inventory = npc.get("inventory") or []
    stone_finds = 0
    if inventory:
        loot_lines.append(f"从{npc.get('name')}的纳戒中搜出：")
        for item in inventory:
            name = str(item.get("name") or item)
            if name == "源石":
                stone_finds += max(1, int(item.get("quantity", 1) or 1))
                loot_lines.append("  · 源石机缘（按秘境公式结算）")
            else:
                xg.bag_add_item(st["bag"], {**item, "name": name,
                                            "type": str(item.get("type") or "材料"),
                                            "quantity": int(item.get("quantity", 1) or 1)})
                loot_lines.append(f"  · {name}")
        npc["inventory"] = []
    # 掉落表
    for d_name, d_type, d_chance in (npc.get("drop_table") or ()):
        if rng.random() < float(d_chance):
            xg.bag_add_item(st["bag"], {"name": d_name, "type": d_type,
                                        "desc": f"击败{npc.get('name')}掉落的战利品"})
            loot_lines.append(f"  ✅ {d_name}")
    # 功法掉落 ≤2
    npc_skills = list(npc.get("skills") or ())
    bag_tech = {str(t.get("name") if isinstance(t, dict) else t)
                for t in st["bag"].get("techniques", ())}
    new_gongfa = [g for g in npc_skills if g not in bag_tech]
    if new_gongfa:
        dropped = []
        for _ in range(min(2, len(new_gongfa))):
            dropped.append(new_gongfa.pop(int(rng.random() * len(new_gongfa)) % max(1, len(new_gongfa))))
        for g in dropped:
            xg.bag_add_technique(st["bag"], g)
        loot_lines += ["", "【功法领悟】从战斗中领悟："] + [f"  📖 {g}" for g in dropped]
    rw = xg.grant_growth(st, doc, stone_rolls=1 + stone_finds)
    loot_lines.append(f"💰 源石 +{rw['source_stone']:,}（暂存秘境背包）")

    # 搜魂窗口
    st["soul_target"] = {"name": str(npc.get("name")), "skills": list(npc.get("skills") or ()),
                         "is_canon": bool(npc.get("is_canon")), "expires_at": now_ms + SOUL_WINDOW_MS}
    _remove_npc(st["map"], spot)
    events["npc_killed"] = npc_id
    return "\n".join([
        f"【击杀NPC·{npc.get('name')}】", "",
        f"{getattr(doc, 'name', '')}大展神威，将{npc.get('name')}击败！",
        *log_lines[-3:],
        "对方倒地不起，气息微弱...", "",
        *loot_lines, "",
        "【弥留之际】对方尚有残魂未散，使用 #搜魂NPC 可强行掠夺其功法记忆！",
        "时效：5 分钟", "",
        f"凶名 +{2 if npc.get('faction') == 'evil' else 5}"], ), events


def soul_search(doc: Any, st: dict, rng: Callable[[], float], now_ms: float) -> tuple[str, dict]:
    """#搜魂NPC：5 分钟窗口；成功掠 ≤2 功法（单门 80%），业力 +20/30。"""
    events: dict[str, Any] = {}
    target = st.get("soul_target")
    if not isinstance(target, dict):
        return "【搜魂NPC·无目标】当前没有可搜魂的目标。先击败一位NPC再试。", events
    if now_ms > float(target.get("expires_at", 0) or 0):
        st.pop("soul_target", None)
        return "【搜魂NPC·残魂消散】弥留之际已过，对方的残魂已彻底消散于天地间...", events
    skills = list(target.get("skills") or ())
    if not skills:
        st.pop("soul_target", None)
        return f"【搜魂NPC·神魂空洞】{target.get('name')}的神魂空洞如枯井，搜魂一无所获！", events
    base_rate = 0.6 if target.get("is_canon") else 0.75
    if rng.random() >= base_rate:
        st.pop("soul_target", None)
        st["karma"] = int(st.get("karma", 0) or 0) + 30
        return "\n".join([
            "【搜魂失败·业力反噬】", "",
            f"你施展搜魂大法，欲掠夺{target.get('name')}残魂中的功法记忆...",
            "然而残魂突然崩散，搜魂之术被强行弹开！", "",
            "💀 业力反噬：业力 +30", "", "残魂消散，再无搜魂之机..."]), events
    bag_tech = {str(t.get("name") if isinstance(t, dict) else t)
                for t in st["bag"].get("techniques", ())}
    learned = []
    for _ in range(min(2, len(skills))):
        g = skills[int(rng.random() * len(skills)) % len(skills)]
        if g not in learned and g not in bag_tech and rng.random() < 0.8:
            learned.append(g)
    for g in learned:
        xg.bag_add_technique(st["bag"], g)
    st.pop("soul_target", None)
    st["karma"] = int(st.get("karma", 0) or 0) + 20
    lines = ["【搜魂成功·记忆掠夺】", "",
             f"{getattr(doc, 'name', '')}眸光一冷，神识如刀！", "“搜魂——！！”", "",
             f"{target.get('name')}的残魂被强行撕裂！",
             "在其破碎的记忆长河中，功法烙印如星辰般浮现...", ""]
    if learned:
        lines.append(f"✅ 成功掠夺 {len(learned)} 门功法：")
        lines += [f"  📖 {g}" for g in learned]
    else:
        lines.append("❌ 对方功法过于深奥，无法参悟...")
    lines += ["", "💀 业力缠身：业力 +20", "", "「搜魂之术，虽能速成，却有伤天和」"]
    return "\n".join(lines), events


# ---------------------------------------------------------------- 好感 / 组队

def relation_text(doc: Any, st: Mapping) -> str:
    rels = st.get("npc_relations") or {}
    infamy = int(st.get("infamy", 0) or 0)
    canon_rows = []
    for zone, npcs in CANON_NPCS.items():
        for npc in npcs:
            canon_rows.append({"name": npc["name"], "title": npc.get("title", ""),
                               "region": zone, "relation": int(rels.get(str(npc["id"]), 0) or 0)})
    canon_rows.sort(key=lambda r: -r["relation"])
    lines = ["【NPC好感度·仙古秘境】", "",
             f"修士：{getattr(doc, 'name', '') or '修士'}", f"凶名：{infamy}", "",
             "━━━━ 原著天骄关系 ━━━━", ""]
    if not canon_rows:
        lines.append("暂未与任何原著天骄建立关系")
    else:
        for row in canon_rows:
            icon = "💚" if row["relation"] >= 100 else "💛" if row["relation"] >= 50 \
                else "🔴" if row["relation"] < -30 else "⚪"
            lines.append(f"{icon} {row['name']}（{row['title']}）— "
                         f"{relation_desc(row['relation'])}（{row['relation']:+d}）")
            lines.append(f"  区域：{row['region']}")
    lines += ["", "━━━━ 组队状态 ━━━━"]
    if st.get("teammate"):
        lines.append(f"当前组队：{st.get('teammate_name')}")
        lines.append("使用 #解除组队 可以解散队伍")
    else:
        lines += ["当前无组队NPC", "好感≥50 的NPC可尝试 #NPC组队"]
    return "\n".join(lines)


def team(doc: Any, st: dict, rng: Callable[[], float], now_ms: float) -> str:
    """#NPC组队：好感≥50 或 friendly；scheming 且好感<100 → 30% 背叛标记。"""
    spot = npc_at(st)
    npc = (spot or {}).get("npc") or {}
    if not npc or (not npc.get("is_canon") and not npc.get("personality")) \
            or npc.get("is_alive") is False or npc.get("faction") == "evil":
        return "【组队·无合适NPC】请移动到愿意同行的NPC所在格。"
    if st.get("teammate"):
        return ("【组队·已有队伍】\n"
                f"当前正与 {st.get('teammate_name')} 组队中。\n使用 #解除组队 后再邀请新的NPC。")
    last_team = float(st.get("last_team_at", 0) or 0)
    if last_team > 0 and now_ms < last_team + TEAM_CD_MS:
        return (f"【组队·冷却中】刚组建过队伍，需等待 "
                f"{int((last_team + TEAM_CD_MS - now_ms) / 60000)} 分钟。")
    npc_id = str(npc.get("id") or npc.get("name"))
    rels = st.setdefault("npc_relations", {})
    rel = int(rels.get(npc_id, int((st.get("faction_rep") or {}).get(str(npc.get("faction")), 0) or 0)))
    if rel < 50 and npc.get("personality") != "friendly":
        return "\n".join([
            "【组队·好感不足】", "",
            f"{npc.get('name')}（{npc.get('title') or ''}）：",
            "“你我不过萍水相逢，凭什么要我以身犯险与你组队？”", "",
            "需要好感≥50才能组队。", f"当前好感：{rel}", "",
            "多与该NPC交谈可提升好感。"])
    st["teammate"] = npc_id
    st["teammate_name"] = str(npc.get("name"))
    st["teammate_betch"] = 0.3 if (npc.get("personality") == "scheming" and rel < 100) else 0.0
    st["last_team_at"] = now_ms
    rels[npc_id] = rel + 20
    betray = "⚠ 该NPC心思深沉，战斗中可能背叛！" if st["teammate_betch"] else ""
    return "\n".join([
        "【NPC组队·结成同伴】", "",
        f"{npc.get('name')}（{npc.get('title') or ''}）微微点头：", "",
        ("“你是我认可的战友。”" if npc.get("is_canon") and rel >= 100
         else "“也好，你我同行，相互照应。”"), "",
        "✅ 组队成功！", f"当前同伴：{npc.get('name')}",
        f"好感度 +20（当前：{rel + 20}）", "",
        "【组队效果】",
        "· 下次战斗中，同伴将助战（攻/血 +20%）",
        "· 使用 #解除组队 解散队伍",
        betray])


def team_leave(doc: Any, st: dict) -> str:
    if not st.get("teammate"):
        return "【解除组队·无队伍】你当前没有组队。"
    old = str(st.get("teammate_name") or st.get("teammate"))
    for key in ("teammate", "teammate_name", "teammate_betch"):
        st.pop(key, None)
    return f"【解除组队】\n\n你与 {old} 告别，各自踏上各自的仙途。\n\n“珍重，有缘再会。”"


# ---------------------------------------------------------------- 生态遭遇（简化版 processNPCBehavior）

def ecology_step(doc: Any, st: dict, rng: Callable[[], float], now_ms: float,
                 battle: Callable | None) -> list[str]:
    """邻格遭遇：敌意猎杀 / 诡诈 / 结交。原版每秒世界 tick + BFS 寻路，
    端口简化为移动/探索时对相邻（含脚下）NPC 各掷一次，无 NPC 自主移动。"""
    events: list[str] = []
    map_st = st.get("map") or {}
    px, py = map_st.get("pos", {}).get("x"), map_st.get("pos", {}).get("y")
    if px is None:
        return events
    rels = st.setdefault("npc_relations", {})
    for spot in list(map_st.get("npc_locations", ())):
        npc = spot.get("npc")
        if not npc or npc.get("is_alive") is False:
            continue
        if abs(spot["x"] - px) + abs(spot["y"] - py) > 1:
            continue
        npc_id = str(npc.get("id") or npc.get("name"))
        relation = int(rels.get(npc_id, int((st.get("faction_rep") or {}).get(str(npc.get("faction")), 0) or 0)))
        hostile = npc.get("hostile") is True or npc.get("personality") == "hostile" or relation <= -30
        if hostile:
            # 5 分钟冷却：每 NPC 记 next_encounter
            if now_ms < float(spot.get("next_encounter", 0) or 0):
                continue
            spot["next_encounter"] = now_ms + 300_000
            enemy = npc_battle_data(npc, doc, rng)
            if battle is None:
                won, log_lines = True, ["（演武：跳过战斗）"]
            else:
                won, log_lines = battle(enemy, "xiangu_ecology")
            if won:
                xg.bag_add_growth(st["bag"], source_stone=xg.source_stone_reward(doc, 1))
                st["infamy"] = int(st.get("infamy", 0) or 0) + 3
                events.append(f"⚔️ {npc.get('name')}向你扑杀而来，被你反手击退（源石入包，凶名 +3）。")
            else:
                hp_loss = max(1, int(xg._hp_of(doc) * 0.15))
                xg._set_hp(doc, max(1, xg._hp_of(doc) - hp_loss))
                events.append(f"⚠️ {npc.get('name')}趁乱偷袭得手！血量 -{hp_loss:,}。")
            continue
        fraud = 0.35 if (npc.get("personality") == "scheming" and relation < 100) \
            else (0.25 if relation < 0 and npc.get("personality") != "friendly" else 0.0)
        if fraud > 0 and rng.random() < fraud:
            rels[npc_id] = relation - 10
            events.append(f"🎭 {npc.get('name')}言语间套你根基虚实（好感 -10）。")
            continue
        befriend = 0.35 if (npc.get("personality") == "friendly" or npc.get("faction") == "good") else 0.15
        if rng.random() < befriend:
            delta = 10 if (npc.get("personality") == "friendly" or npc.get("faction") == "good") else 5
            rels[npc_id] = relation + delta
            clue = ""
            nearest = None
            for y in range(int(map_st["h"])):
                for x in range(int(map_st["w"])):
                    if map_st["grid"][y][x] == xg.CELL_TREASURE and \
                            (nearest is None or abs(x - px) + abs(y - py) < abs(nearest[0] - px) + abs(nearest[1] - py)):
                        nearest = (x, y)
            if nearest:
                map_st["revealed"][nearest[1]][nearest[0]] = True
                clue = f"，并指出一处机缘坐标：[{nearest[0]}, {nearest[1]}]。"
            events.append(f"🤝【NPC主动结交】{npc.get('name')}释放善意，好感 +{delta}{clue}")
    return events


# ---------------------------------------------------------------- 凶名执行者视角（供 camp 使用）

def goal_progress_text(st: Mapping) -> str:
    lines = ["【古代怪胎动向】"]
    for npc_id, goal in CANON_GOALS.items():
        prog = (st.get("canon_goals") or {}).get(npc_id) or {}
        status = "已达成" if prog.get("completed") else f"{int(prog.get('progress', 0) or 0)}/{goal['target']}"
        lines.append(f"{goal['name']}｜{goal['location']}｜{goal['objective']}（{status}）")
    return "\n".join(lines)


def bump_goal(doc: Any, st: dict, kind: str, item_name: str = "") -> str | None:
    """canon 执念进度钩子：kind ∈ arena_win / player_kill / npc_kill / item。
    返回完成播报（无则 None）。NPC 侧目标在本插件由玩家行为对位推进（简化）。"""
    mapping = {"arena_win": "shiguanwang_tianzi", "npc_kill": "zhexian",
               "item:剑谷剑意碎片": "gujian_yun", "item:真凰翎羽": "honghuang"}
    npc_id = mapping.get(f"item:{item_name}" if kind == "item" else kind)
    if not npc_id:
        return None
    goals = st.setdefault("canon_goals", {})
    prog = goals.setdefault(npc_id, {"progress": 0, "completed": False})
    goal = CANON_GOALS[npc_id]
    if prog.get("completed"):
        return None
    prog["progress"] = int(prog.get("progress", 0) or 0) + 1
    if prog["progress"] >= goal["target"]:
        prog["completed"] = True
        return f"🏆【天骄执念·你替{npc_id and goal['name']}推进了命途】{goal['objective']}——进度已满！"
    return None


def now_ms() -> float:
    return time.time() * 1000
