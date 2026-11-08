"""W8-E2 剑与魔法·艾瑟兰：平行开局（纯函数层，无 IO）。

原版 apps/User/SwordMagic.js 只有 1 条 rule，model/swordMagic.js 里 27 个子命令；
状态是玩家档顶层 `剑与魔法` 对象（无 redis，`cargo` 恒空无生产者）。本移植收进
doc.ext["sword"]，用惰性 tick 替代原版 30s cron，db 仍 v17。

取证纠偏（勿再信旧稿）：
- 「地脉点 / 地脉技能」全仓零命中，是旧稿臆造；实际资源是「古代晶片」+ 4 熟练度。
- 计时是真实毫秒 endAt，不是回合数；`SwordMagicTask` 是 rule: [] 的 cron 孤儿。
- 飞升信物按 name 入库（id 9600501 与「月华仙炉」撞号）。
"""
from __future__ import annotations

import random
from typing import Any

KEY = "sword"
VERSION = 1
MIN = 60.0
ASCEND_REALM = 38               # 0-based，level_id=39 真界境后期
COIN_RATE = 100                 # 飞升：铜币 ×100 → 灵石
BAG_CAP = 12

TRAITS: dict[str, dict] = {
    "spirit":   {"name": "精灵亲和", "weight": 12, "desc": "解锁精灵交涉；交涉威力 +14；风鸣林交涉得风精灵契约"},
    "element":  {"name": "元素亲和", "weight": 18, "desc": "魔法训练 +2；法术魔力消耗 -3"},
    "mana":     {"name": "魔力超群", "weight": 8,  "desc": "魔力上限 +35"},
    "silent":   {"name": "无吟唱者", "weight": 2,  "desc": "解锁静默解析；该应对威力 +14；法术应对 3 分钟"},
    "sword":    {"name": "剑术直觉", "weight": 18, "desc": "剑术威力 +6；剑术训练 +2"},
    "holy":     {"name": "圣印共鸣", "weight": 12, "desc": "祷告训练 +2；净化魔力 -3"},
    "wanderer": {"name": "旅人洞察", "weight": 20, "desc": "探索 -1 分钟；调查额外 +1 古代晶片"},
    "will":     {"name": "逆境意志", "weight": 10, "desc": "每次受伤 -4（不免战败）"},
}
PROFESSIONS: dict[str, str] = {
    "剑士": "剑术", "魔法师": "魔法", "僧侣": "祷告", "游侠": "侦察",
}
SKILLS = ("剑术", "魔法", "祷告", "侦察")
GOODS: dict[str, int] = {
    "野营口粮": 8, "疗伤药": 18, "魔力药": 22, "古代晶片": 0,  # 0 = 不可购买
}
# index, level, minutes, threat, reward, items, choices
REGIONS: list[dict] = [
    {"name": "风鸣林", "level": 1, "minutes": 6, "threat": 12, "reward": 45, "item": 2,
     "mystery": "树根里的王室魔力钉，异变源自征收旧约",
     "choices": ("救援", "调查", "精灵交涉")},
    {"name": "灰钟地窟", "level": 2, "minutes": 8, "threat": 18, "reward": 60, "item": 2,
     "mystery": "古钟曾为王国抽取地脉计时，亡灵守着被抹名的工程师",
     "choices": ("强攻", "净化", "调查")},
    {"name": "雾桥驿", "level": 3, "minutes": 10, "threat": 25, "reward": 75, "item": 2,
     "mystery": "魔族难民的旧地图把灾变中心标在王都",
     "choices": ("救援", "调查", "强攻")},
    {"name": "断冠遗迹", "level": 4, "minutes": 12, "threat": 32, "reward": 90, "item": 3,
     "mystery": "无声大厅的咒文触发封印，唯无吟唱者可静默解析",
     "choices": ("法术", "静默解析", "调查")},
    {"name": "黑曜边城", "level": 5, "minutes": 14, "threat": 40, "reward": 110, "item": 3,
     "mystery": "魔王守军抵挡裂隙，城外军旗纹章与勇者武装同源",
     "choices": ("救援", "法术", "净化")},
    {"name": "裂月王庭", "level": 6, "minutes": 16, "threat": 48, "reward": 150, "item": 4,
     "mystery": "地脉炉所在，三份残章拼出解法：谁是敌人，要靠证据判断",
     "choices": ("重铸勇者誓约", "织补地脉", "继承守隙王冠")},
]
CHOICE_SKILL: dict[str, str] = {
    "救援": "剑术", "强攻": "剑术", "重铸勇者誓约": "剑术",
    "法术": "魔法", "织补地脉": "魔法",
    "净化": "祷告", "继承守隙王冠": "祷告",
    "调查": "侦察", "精灵交涉": "魔法", "静默解析": "魔法",
}
MAGIC_CHOICES = {"法术", "静默解析", "净化", "重铸勇者誓约", "织补地脉", "继承守隙王冠"}
ENDINGS: dict[str, dict] = {
    "重铸勇者誓约": {"name": "黎明勇者", "fate": "dawn_oath", "gift": "黎明誓约剑"},
    "织补地脉": {"name": "地脉贤者", "fate": "leyline_promise", "gift": "地脉织针"},
    "继承守隙王冠": {"name": "守隙魔王", "fate": "riftward_vow", "gift": "守隙王冠"},
}
READONLY = {"帮助", "规则", "世界观", "状态", "背包", "词条", "地图", "见闻", "回顾", "商店"}


# ---------------------------------------------------------------- 状态


def _hp_cap(s: dict) -> int:
    return 100 + (int(s["level"]) - 1) * 8


def _mp_cap(s: dict) -> int:
    return 60 + (int(s["level"]) - 1) * 6 + (35 if "mana" in s["traits"] else 0)


def new_state(doc: Any, ts: float) -> dict:
    return {
        "version": VERSION, "revision": 0, "status": "active", "created_at": ts,
        "profession": "", "traits": [], "drawn_at": None,
        "level": 1, "exp": 0, "coins": 120, "hp": 100, "mp": 60, "wounded": False,
        "skills": {k: 0 for k in SKILLS}, "place": "白桦镇", "chapter": 0,
        "bag": {"野营口粮": 2, "疗伤药": 2, "魔力药": 1},
        "storage": {}, "weapon": False, "companion": False, "pact": False,
        "action": None, "encounter": None, "lore": [], "ending": "",
        "defeats": 0, "commissions": 0, "history": [], "receipts": [],
        "snapshot": {
            "realm_index": int(doc.realm_index), "physique_index": int(doc.physique_index),
            "exp": int(doc.exp), "stones": int(doc.stones), "state": str(doc.state),
            "state_start": float(doc.state_start),
        },
    }


def state_of(doc: Any) -> dict | None:
    v = (doc.ext or {}).get(KEY)
    return v if isinstance(v, dict) and v.get("version") else None


def active(s: dict | None) -> bool:
    return bool(s and s.get("status") == "active")


def _restore(doc: Any, s: dict) -> None:
    for k, v in (s.get("snapshot") or {}).items():
        if hasattr(doc, k):
            setattr(doc, k, v)
    doc.ext.pop(KEY, None)


def load(s: dict) -> int:
    return sum(int(v or 0) for v in s["bag"].values())


def _add(bag: dict, name: str, qty: int) -> None:
    bag[name] = max(0, int(bag.get(name, 0) or 0) + int(qty))
    if bag[name] == 0:
        bag.pop(name, None)


def _note(s: dict, text: str, ts: float) -> None:
    s["history"] = (s.get("history") or [])[-15:] + [f"{int(ts)} {text}"]


def _gain_exp(s: dict, amount: int) -> str:
    s["exp"] += int(amount)
    ups = 0
    while s["level"] < 10 and s["exp"] >= s["level"] * 35:
        s["exp"] -= s["level"] * 35
        s["level"] += 1
        ups += 1
        s["hp"] = _hp_cap(s)
        s["mp"] = _mp_cap(s)
    return f"，等级提升至 {s['level']}" if ups else ""


def trait_names(s: dict) -> str:
    return "、".join(TRAITS[t]["name"] for t in s["traits"]) or "尚未抽取"


# ---------------------------------------------------------------- 文本


def help_text() -> str:
    return "\n".join([
        "【剑与魔法·艾瑟兰】独立开局，六地区计时冒险、三终局、飞升接仙界",
        "单入口「#剑与魔法」+ 空格子命令（空参=状态）；「#剑与魔法帮助」「#抽取异界词条」亦可用",
        "开局：入界 确认 → 抽取词条（8 选 2，仅一次）→ 就职 剑士|魔法师|僧侣|游侠",
        "白桦镇：训练 剑术|魔法|祷告|侦察 / 帮工 / 休养 / 锻造 / 购买|存入|取出 物品 数量 / 使用 药 / 丢弃 / 商店",
        "冒险：地图 → 探索 地区名 → 抉择 选项（真实时间到期结算）→ 撤离 可中止",
        "终局：裂月王庭三选一（对应熟练度 ≥10 且已锻造职业武装）→ 飞升 确认",
        "只读：帮助 / 规则 / 世界观 / 状态 / 结算 / 背包 / 词条 / 地图 / 见闻 / 回顾 / 商店",
        "移植补位：放弃 确认（恢复入界前主线快照，原版只能转世清档）",
        "通用别名：「#我」「#我的练气」= 状态，「#背包」= 异界背包；未开局时自动回主线状态 / 纳戒",
        "「#我的纳戒」「#纳戒」在 E2 进行中转异界背包；「#抽取命格词条」仍走主线命格抽取",
    ])


def rules_text() -> str:
    return "\n".join([
        "--- 剑与魔法 · 规则口径 ---",
        "· 状态：doc.ext['sword'] 单对象（原版玩家档顶层 剑与魔法 v1），无 redis；",
        "  power_place=0.7 位面锚在移植版无对应字段，改用 doc.state 标记。",
        "· 计时：**真实时间分钟数 endAt**（不是回合数），原版靠 30s cron 扫描，",
        "  本移植用惰性 tick：发任意指令，或发送「#剑与魔法 结算」；行动期间不接受新动作。",
        "· 取证纠偏：「地脉点 / 地脉技能」全仓零命中，是旧稿臆造；实际是古代晶片 + 4 熟练度。",
        "· 8 天赋加权合计 100，两次不重复加权抽；4 职业只给主熟练度 5 + 应对 +7。",
        "· 6 地区按顺序开放（index ≤ chapter 且 level ≥ region.level），每次消耗野营口粮×1；",
        "  随身 12 格上限；重伤需先执行子命令「休养」。重复探索收益减半但记一次委托。",
        "· 战力 = 等级×5 + 熟练度 + 主职 7 + 武装 8 + 天赋加成；",
        "  危险率钳制 3%~65%，战败 hp 归 1 + 重伤 + 暂获清空 + 铜币 -15。",
        "· 三终局均需对应熟练度 ≥10 且已锻造武装；终局本身不发数值奖励，只写 ending。",
        "· 飞升：六地区通关 + ending + 武装 + 等级 ≥8 + 二次确认；",
        "  主线至 39 境（只升不降）、灵石 +铜币×100、附加命格 +2、命格槽 +2、1 件信物。",
        "· 原版与复活地球互斥、active 期间四层全局指令拦截；本移植沿用互斥但不拦截，",
        "  主线旁路共存，入界存快照，可随时 放弃 确认 回滚。飞升后档案封存只读。",
        "· 不做：仙宠赠礼（原版 3 只，需独立 najie 档）、图片面板、cargo 暂存（无生产者恒空）、",
        "  五条未落地扩展钩子（矮人锻匠/学院/古树议会/裂隙/历代勇者残影）。",
    ])


def lore_text() -> str:
    return "\n".join([
        "--- 艾瑟兰大陆 ---",
        "地脉如世界的血液循环；魔法、斗气、圣术、侦察是四种取用方式。",
        "白桦镇是边境公会分站，也是所有冒险的起点与归处。",
        "六地区见闻都指向同一命题：谁是敌人，要靠证据判断，而不是史书。",
        "三条终局没有高下，只有代价不同——重铸勇者誓约 / 织补地脉 / 继承守隙王冠。",
    ])


def status_text(doc: Any, s: dict, ts: float) -> str:
    a = s.get("action")
    act = f"{a['title']}（余 {max(0, int((a['end_at'] - ts) // 60))} 分）" if a else "空闲"
    return "\n".join([
        f"---- 剑与魔法 · {s['profession'] or '未就职'} Lv{s['level']} ----",
        f"位置 {s['place']}｜铜币 {int(s['coins']):,}｜HP {int(s['hp'])}/{_hp_cap(s)}｜MP {int(s['mp'])}/{_mp_cap(s)}"
        + ("｜重伤" if s["wounded"] else ""),
        f"经验 {int(s['exp'])}/{s['level'] * 35}｜熟练度 " +
        " ".join(f"{k}{v}" for k, v in s["skills"].items()),
        f"天赋 {trait_names(s)}｜职业武装 {s['weapon']}｜同伴 {s['companion']}｜风精灵契约 {s['pact']}",
        f"主线进度 {s['chapter']}/6｜终局 {ENDINGS.get(s['ending'], {}).get('name', s['ending']) or '未定'}"
        f"｜重伤撤回 {int(s['defeats'])}｜委托 {int(s['commissions'])}",
        f"当前行动：{act}｜状态 {s['status']}｜主线快照：第 {int(s['snapshot']['realm_index']) + 1} 境",
    ])


def bag_text(s: dict) -> str:
    return "\n".join([
        f"---- 背包（{load(s)}/{BAG_CAP} 格）----",
        "随身：" + ("、".join(f"{k}×{v}" for k, v in s["bag"].items()) or "空"),
        "仓储：" + ("、".join(f"{k}×{v}" for k, v in s["storage"].items()) or "空"),
        # 原版 cargo 无生产者恒为空，本移植直接不设该字段
        f"职业武装 {'已成' if s['weapon'] else '未锻造'}｜见闻 {len(s['lore'])}/6",
    ])


def traits_text(s: dict) -> str:
    lines = ["---- 天赋（8 选 2，权重合计 100）----",
             f"已获得：{trait_names(s)}"]
    lines += [f"· {v['name']}({v['weight']})：{v['desc']}" for v in TRAITS.values()]
    return "\n".join(lines)


def map_text(s: dict) -> str:
    lines = ["---- 六地区地图 ----", f"当前进度 {s['chapter']}/6（等级 {s['level']}）"]
    for i, r in enumerate(REGIONS):
        open_ = "已开放" if i <= s["chapter"] and s["level"] >= r["level"] else "未开放"
        lines.append(f"{i + 1}. {r['name']}｜Lv{r['level']}｜{r['minutes']}分+应对5分｜"
                     f"威胁{r['threat']}｜{open_}")
    lines.append("· 静默解析 / 法术应对在「无吟唱者」下为 3 分钟（地图文案统一按 5 分钟展示）")
    return "\n".join(lines)


def lore_view(s: dict) -> str:
    rows = [f"{i + 1}. {x}" for i, x in enumerate(s["lore"])]
    return "\n".join(["---- 见闻（按地区解锁）----"] + (rows or ["尚未出发。"]))


def review_text(s: dict) -> str:
    rows = [f"· {x}" for x in (s.get("history") or [])[-16:]]
    return "\n".join(["---- 回顾（最近 16 条）----"] + (rows or ["尚无履历。"]))


def shop_text() -> str:
    return "\n".join(["---- 白桦镇商店 ----"] +
                     [f"· {k}：{v} 铜币" for k, v in GOODS.items() if v > 0] +
                     ["· 古代晶片不可购买，只能探索取得（锻造消耗 4 枚）",
                      "格式：购买 物品 数量（数量 1~99，默认 1）"])


# ---------------------------------------------------------------- 行动


def _start(s: dict, act_kind: str, title: str, minutes: float, ts: float, **payload: Any) -> str:
    # 系统字段后写，避免 payload 同名键覆盖行动类型
    s["action"] = {**payload, "kind": act_kind, "title": title,
                   "end_at": ts + minutes * MIN, "started_at": ts}
    return f"已开始【{title}】，需 {minutes:g} 分钟；到期后发任意指令，或发送「#剑与魔法 结算」领取结果。"


def _power(s: dict, skill: str, choice: str) -> int:
    p = int(s["level"]) * 5 + int(s["skills"].get(skill, 0))
    if s["profession"] and PROFESSIONS[s["profession"]] == skill:
        p += 7
    if s["weapon"]:
        p += 8
    if skill == "剑术" and "sword" in s["traits"]:
        p += 6
    if choice == "精灵交涉" and "spirit" in s["traits"]:
        p += 14
    if choice == "静默解析" and "silent" in s["traits"]:
        p += 14
    return p


def _magic_cost(s: dict, choice: str) -> int:
    if choice not in MAGIC_CHOICES:
        return 0
    cost = 12
    if "element" in s["traits"] and choice in ("法术", "重铸勇者誓约", "织补地脉"):
        cost -= 3
    if "holy" in s["traits"] and choice in ("净化", "继承守隙王冠"):
        cost -= 3
    if s["pact"]:
        cost -= 2
    return max(3, cost)


def resolve_action(s: dict, a: dict, rng: random.Random) -> str:
    k = a["kind"]
    if k == "train":
        skill = a["target"]
        gain = 1
        if skill == "魔法" and "element" in s["traits"]:
            gain += 1
        if skill == "剑术" and "sword" in s["traits"]:
            gain += 1
        if skill == "祷告" and "holy" in s["traits"]:
            gain += 1
        s["skills"][skill] = min(30, int(s["skills"][skill]) + gain)
        return f"训练【{skill}】完成：熟练度 {s['skills'][skill]}/30（+{gain}）。"
    if k == "work":
        s["coins"] += 15
        return "帮工完成：铜币 +15。"
    if k == "rest":
        s["hp"], s["mp"], s["wounded"] = _hp_cap(s), _mp_cap(s), False
        return f"休养完成：HP/MP 回满，重伤解除（{s['hp']}/{s['mp']}）。"
    if k == "use":
        name = a["target"]
        if name == "疗伤药":
            s["hp"] = min(_hp_cap(s), int(s["hp"]) + 50)
        else:
            s["mp"] = min(_mp_cap(s), int(s["mp"]) + 40)
        return f"使用【{name}】完成：HP {int(s['hp'])} / MP {int(s['mp'])}。"
    if k == "forge":
        s["weapon"] = True
        return "锻造完成：职业武装已成（应对威力 +8，三终局前置）。"
    if k == "return":
        s["encounter"] = None
        s["place"] = "白桦镇"
        return "已撤回白桦镇，本次行进/遭遇中止。"
    if k == "explore":
        r = REGIONS[a["index"]]
        s["encounter"] = {"region": a["index"], "repeat": a["repeat"]}
        s["place"] = r["name"]
        return (f"抵达【{r['name']}】。遭遇待抉择，可发：\n"
                + " / ".join(r["choices"]) + "\n格式：「#剑与魔法 抉择 选项」")
    if k == "choice":
        idx = a["index"]
        r = REGIONS[idx]
        choice = a["target"]
        skill = CHOICE_SKILL.get(choice, "侦察")
        power = _power(s, skill, choice)
        threat = r["threat"]
        danger = max(0.03, min(0.65, (threat - power + 18) / 100))
        hurt = max(2, threat - power // 3 - (4 if "will" in s["traits"] else 0))
        if a["roll"] < danger:
            hurt += 30
        s["hp"] = int(s["hp"]) - hurt
        head = f"【{r['name']}】{choice}：战力 {power} vs 威胁 {threat}，危险率 {danger:.0%}，受伤 {hurt}。"
        if s["hp"] <= 0:
            s["hp"] = 1
            s["wounded"] = True
            s["defeats"] += 1
            s["coins"] = max(0, int(s["coins"]) - 15)
            s["place"] = "白桦镇"
            s["encounter"] = None
            return head + "\n战败撤回：HP 1、重伤、铜币 -15，需先执行子命令「休养」。"
        repeat = bool(a["repeat"])
        bonus = (1 if choice == "调查" else 0) + (1 if choice == "调查" and "wanderer" in s["traits"] else 0)
        amount = min(r["item"] + bonus, BAG_CAP - load(s))
        if amount > 0:
            _add(s["bag"], "古代晶片", amount)
        coins = r["reward"] // 2 if repeat else r["reward"]
        s["coins"] += coins
        up = _gain_exp(s, 22 if repeat else 45)
        if repeat:
            s["commissions"] += 1
        if idx == 0 and choice == "救援":
            s["companion"] = True
        if idx == 0 and choice == "精灵交涉":
            s["pact"] = True
        s["chapter"] = max(int(s["chapter"]), idx + 1)
        if r["mystery"] not in s["lore"]:
            s["lore"].append(r["mystery"])
        s["place"] = "白桦镇"
        s["encounter"] = None
        tail = ""
        if idx == 5 and choice in ENDINGS:
            s["ending"] = choice
            tail = f"\n【断冠纪元终章】{ENDINGS[choice]['name']}：三条路没有高下，只有代价不同。"
        return (f"{head}\n获得 古代晶片×{amount}、铜币 +{coins}、经验 +{22 if repeat else 45}{up}。"
                f"当前进度 {s['chapter']}/6。{tail}")
    return f"行动【{a.get('title')}】已结算。"


def tick(s: dict, ts: float, rng: random.Random) -> list[str]:
    """惰性结算：替代原版 30s cron，所有入口与手动 结算 共用。"""
    out: list[str] = []
    guard = 0
    while s.get("action") and ts >= s["action"]["end_at"] and guard < 8:
        guard += 1
        a = s["action"]
        s["action"] = None
        out.append(resolve_action(s, a, rng))
        s["revision"] = int(s.get("revision", 0)) + 1
    if out:
        _note(s, f"结算 {len(out)} 项行动", ts)
    return out


# ---------------------------------------------------------------- 分发


def enter(doc: Any, ts: float, confirmed: bool) -> tuple[str, bool, list]:
    if state_of(doc):
        return "已有剑与魔法记录，发送「#剑与魔法 状态」查看。", False, []
    if active_earth(doc):
        return "复活地球进行中，两条平行开局互斥；先发送「#复活地球 放弃 确认」，或完成离界。", False, []
    if not confirmed:
        return ("【入界预览】从白桦镇凡人开始，独立等级/熟练度/六地区计时冒险；"
                "主线数值会存快照，入界后可随时发送「#剑与魔法 放弃 确认」恢复。\n"
                "确认请发送「#剑与魔法 入界 确认」。"), False, []
    doc.ext[KEY] = new_state(doc, ts)
    doc.state = "剑与魔法"
    doc.state_start = ts
    return ("入界成功：抵达白桦镇。主线快照已保存。\n"
            "先发送「#剑与魔法 抽取词条」（8 选 2），再发送「#剑与魔法 就职 剑士」（另有 魔法师/僧侣/游侠）。"), True, []


def active_earth(doc: Any) -> bool:
    e = (doc.ext or {}).get("earth")
    return bool(isinstance(e, dict) and e.get("status") == "active")


def abandon(doc: Any, s: dict, confirmed: bool) -> tuple[str, bool, list]:
    if not active(s):
        return "本篇已飞升封存，主线奖励已入账，不可再放弃回滚。", False, []
    if not confirmed:
        return ("【放弃确认】将丢弃本篇全部进度并恢复入界前主线快照。\n"
                "确认请发送「#剑与魔法 放弃 确认」。"), False, []
    snap = s.get("snapshot") or {}
    _restore(doc, s)
    return (f"已放弃剑与魔法，主线恢复至第 {int(snap.get('realm_index', 0)) + 1} 境 / "
            f"灵石 {int(snap.get('stones', 0)):,}。本篇记录已清除。"), True, []


def ascend(doc: Any, s: dict, ts: float, confirmed: bool,
           fates: list[dict] | None = None) -> tuple[str, bool, list]:
    if s["chapter"] < 6 or not s["ending"]:
        return f"飞升需六地区通关（现 {s['chapter']}/6）并定下终局。", False, []
    if not s["weapon"]:
        return "飞升需职业武装，发送「#剑与魔法 锻造」。", False, []
    if s["level"] < 8:
        return f"飞升需等级 ≥8（现 {s['level']}）。", False, []
    if not confirmed:
        return ("【飞升预览】主线至少提升至 39 境（只升不降）、灵石 +铜币×100、"
                "附加命格 +2、命格槽 +2、1 件终局信物；本篇档案封存只读。\n"
                "确认请发送「#剑与魔法 飞升 确认」。"), False, []
    before = int(doc.realm_index)
    if before < ASCEND_REALM:
        doc.realm_index = ASCEND_REALM
        doc.exp = 0
    doc.stones = int(doc.stones) + int(s["coins"]) * COIN_RATE
    doc.state = "空闲"
    doc.state_start = ts
    # 原版 +2 命格槽上限（本移植 MAX_SLOTS=3），已满则不重复扩
    slots = int(doc.ext.get("mingge_slots", 1) or 1)
    doc.ext["mingge_slots"] = min(3, slots + 2)
    rows = [dict(x) for x in (doc.ext.get("mingge_extra") or []) if isinstance(x, dict)]
    cap = max(0, int(doc.ext["mingge_slots"]) - 1)
    added = 0
    for f in (fates or []):
        if f and len(rows) < cap and not any(x.get("id") == f.get("id") for x in rows):
            rows.append(dict(f))
            added += 1
    doc.ext["mingge_extra"] = rows
    gift = ENDINGS.get(s["ending"], {}).get("gift", "")
    s["status"] = "ascended"
    s["place"] = "仙界"
    s["revision"] = int(s["revision"]) + 1
    _note(s, "飞升封存", ts)
    return (f"飞升成功：主线第 {int(doc.realm_index) + 1} 境"
            + ("（不降级，保留原有境界）" if before >= ASCEND_REALM else "（真界境后期，修为清零）")
            + f"、灵石 +{int(s['coins']) * COIN_RATE:,}、附加命格 +{added}、命格槽 {doc.ext['mingge_slots']}、"
              f"信物【{gift}】入纳戒。本篇封存只读。"), True, [("items", {gift: 1})] if gift else []


def dispatch(doc: Any, rest: str, ts: float, rng: random.Random,
             fates: list[dict] | None = None) -> tuple[str, bool, list]:
    """返回 (文案, 是否写档, ops)。ops 目前只有 ("items", {name: qty})。"""
    parts = (rest or "").strip().split()
    verb = parts[0] if parts else "状态"
    args = parts[1:]
    confirmed = bool(args and args[-1] == "确认")
    if confirmed:
        args = args[:-1]
    target = args[0] if args else ""
    num = args[1] if len(args) > 1 else ""
    qty = int(num) if str(num).isdigit() else 1

    s = state_of(doc)
    if not s:
        if verb == "入界":
            return enter(doc, ts, confirmed)
        if verb in ("帮助", "规则", "世界观"):
            return ({"帮助": help_text, "规则": rules_text, "世界观": lore_text}[verb])(), False, []
        return ("尚未入界。发送「#剑与魔法 入界」预览代价，确认后发送「#剑与魔法 入界 确认」。\n"
                + help_text()), False, []

    settled = tick(s, ts, rng)
    prefix = ("\n".join(settled) + "\n\n") if settled else ""

    if verb in READONLY:
        views = {
            "帮助": help_text, "规则": rules_text, "世界观": lore_text,
            "状态": lambda: status_text(doc, s, ts), "背包": lambda: bag_text(s),
            "词条": lambda: traits_text(s), "地图": lambda: map_text(s),
            "见闻": lambda: lore_view(s), "回顾": lambda: review_text(s),
            "商店": shop_text,
        }
        return prefix + views[verb](), bool(settled), []
    if verb == "结算":
        return prefix + ("上述行动已结算。" if settled else "当前没有到期行动。"), bool(settled), []

    if verb == "入界":
        return prefix + "已有剑与魔法记录，发送「#剑与魔法 状态」查看；或发送「#剑与魔法 放弃 确认」清除本篇。", bool(settled), []
    if verb == "放弃":
        return abandon(doc, s, confirmed)
    if not active(s):
        return prefix + "本篇已封存（只读）。可 状态 / 背包 / 词条 / 地图 / 见闻 / 回顾 / 帮助 / 规则。", bool(settled), []
    if s["action"]:
        a = s["action"]
        return prefix + (f"行动【{a['title']}】进行中，尚余 "
                         f"{max(0, int((a['end_at'] - ts) // 60))} 分。到点后自动结算。"), True, []
    if verb == "飞升":
        return ascend(doc, s, ts, confirmed, fates)

    # ---- 即时动作 ----
    if verb == "抽取词条":
        if s["drawn_at"] is not None:
            return prefix + f"天赋已抽取：{trait_names(s)}（仅一次）。", True, []
        pool = list(TRAITS)
        weights = [TRAITS[t]["weight"] for t in pool]
        first = rng.choices(pool, weights=weights, k=1)[0]
        rest_pool = [t for t in pool if t != first]
        rw = [TRAITS[t]["weight"] for t in rest_pool]
        second = rng.choices(rest_pool, weights=rw, k=1)[0]
        s["traits"] = [first, second]
        s["drawn_at"] = ts
        s["mp"] = _mp_cap(s)
        return prefix + f"抽取完成：{trait_names(s)}。下一步 就职 职业。", True, []
    if verb == "就职":
        if target not in PROFESSIONS:
            return prefix + "职业：" + " / ".join(PROFESSIONS), True, []
        if s["drawn_at"] is None:
            return prefix + "须先执行子命令「抽取词条」。", True, []
        if s["profession"]:
            return prefix + f"已就职【{s['profession']}】，本世不可改。", True, []
        s["profession"] = target
        s["skills"][PROFESSIONS[target]] = 5
        return prefix + f"就职【{target}】完成，主熟练度 {PROFESSIONS[target]} = 5。", True, []
    if verb in ("购买", "存入", "取出", "丢弃"):
        if not target:
            return prefix + f"{verb} 物品 数量（数量默认 1）。", True, []
        if verb == "购买":
            price = GOODS.get(target)
            if not price:
                return prefix + f"【{target}】不可购买（" + " / ".join(k for k, v in GOODS.items() if v > 0) + "）。", True, []
            qty = max(1, min(99, qty))
            cost = price * qty
            if s["coins"] < cost:
                return prefix + f"铜币不足：需 {cost:,}。", True, []
            if load(s) + qty > BAG_CAP:
                return prefix + f"背包不足（{load(s)}/{BAG_CAP}），先执行子命令「存入」腾位。", True, []
            s["coins"] -= cost
            _add(s["bag"], target, qty)
            return prefix + f"购买【{target}】×{qty}，花费 {cost:,} 铜币。", True, []
        src, dst = (s["bag"], s["storage"]) if verb == "存入" else (s["storage"], s["bag"])
        if verb != "存入" and verb == "取出" and load(s) + qty > BAG_CAP:
            return prefix + f"背包不足（{load(s)}/{BAG_CAP}）。", True, []
        qty = max(1, min(99, qty))
        if int(src.get(target, 0) or 0) < qty:
            return prefix + f"{verb}失败：{target} 数量不足。", True, []
        if verb == "丢弃":
            _add(s["bag"], target, -qty)
            return prefix + f"丢弃【{target}】×{qty}。", True, []
        _add(src, target, -qty)
        _add(dst, target, qty)
        return prefix + f"{verb}【{target}】×{qty} 完成。", True, []

    # ---- 计时动作 ----
    if verb == "训练":
        if not s["profession"] or s["drawn_at"] is None:
            return prefix + "须先执行子命令「抽取词条」「就职」。", True, []
        if target not in SKILLS:
            return prefix + "熟练度：" + " / ".join(SKILLS), True, []
        if s["coins"] < 10:
            return prefix + "训练需预付 10 铜币。", True, []
        s["coins"] -= 10
        return prefix + _start(s, "train", f"训练 {target}", 5, ts, target=target), True, []
    if verb == "帮工":
        return prefix + _start(s, "work", "帮工", 5, ts), True, []
    if verb == "休养":
        return prefix + _start(s, "rest", "休养", 10, ts), True, []
    if verb == "使用":
        if target not in ("疗伤药", "魔力药"):
            return prefix + "可用：疗伤药 / 魔力药。", True, []
        if not _has(s["bag"], target, 1):
            return prefix + f"没有【{target}】。", True, []
        _add(s["bag"], target, -1)
        return prefix + _start(s, "use", f"使用 {target}", 3, ts, target=target), True, []
    if verb == "锻造":
        if s["weapon"]:
            return prefix + "职业武装已锻造。", True, []
        if not _has(s["bag"], "古代晶片", 4) or s["coins"] < 60:
            return prefix + "锻造需 古代晶片×4 + 60 铜币。", True, []
        _add(s["bag"], "古代晶片", -4)
        s["coins"] -= 60
        return prefix + _start(s, "forge", "锻造职业武装", 15, ts), True, []
    if verb == "撤离":
        return prefix + _start(s, "return", "撤回白桦镇", 3, ts), True, []
    if verb == "探索":
        if not s["profession"] or s["drawn_at"] is None:
            return prefix + "须先执行子命令「抽取词条」「就职」。", True, []
        if s["wounded"]:
            return prefix + "重伤未愈，先执行子命令「休养」。", True, []
        if not _has(s["bag"], "野营口粮", 1) or load(s) > BAG_CAP - 1:
            return prefix + "探索需 野营口粮×1 且留 1 格背包空间。", True, []
        idx = next((i for i, r in enumerate(REGIONS) if r["name"] == target), -1)
        if idx < 0:
            return prefix + "地区：" + " / ".join(r["name"] for r in REGIONS), True, []
        r = REGIONS[idx]
        if idx > s["chapter"] or s["level"] < r["level"]:
            return prefix + f"【{r['name']}】未开放（需进度 {idx}/6、等级 ≥{r['level']}）。", True, []
        _add(s["bag"], "野营口粮", -1)
        minutes = r["minutes"] - (1 if "wanderer" in s["traits"] else 0)
        return prefix + _start(s, "explore", f"探索 {r['name']}", minutes, ts,
                               index=idx, repeat=idx < s["chapter"]), True, []
    if verb == "抉择":
        enc = s.get("encounter")
        if not enc:
            return prefix + "当前没有待抉择遭遇（先发送「#剑与魔法 探索 地区名」）。", True, []
        r = REGIONS[enc["region"]]
        if target not in r["choices"]:
            return prefix + "可选：" + " / ".join(r["choices"]), True, []
        if target == "精灵交涉" and "spirit" not in s["traits"]:
            return prefix + "【精灵交涉】需天赋「精灵亲和」。", True, []
        if target == "静默解析" and "silent" not in s["traits"]:
            return prefix + "【静默解析】需天赋「无吟唱者」。", True, []
        if target in ENDINGS:
            need = CHOICE_SKILL[target]
            if int(s["skills"][need]) < 10 or not s["weapon"]:
                return prefix + f"终局【{target}】需 {need} ≥10（现 {s['skills'][need]}）且已锻造职业武装。", True, []
        cost = _magic_cost(s, target)
        if s["mp"] < cost:
            return prefix + f"魔力不足：需 {cost}（现 {int(s['mp'])}），可 休养 / 使用 魔力药。", True, []
        s["mp"] -= cost
        minutes = 3 if target == "法术" and "silent" in s["traits"] else 5
        return prefix + _start(s, "choice", f"抉择 {target}", minutes, ts,
                               index=enc["region"], target=target,
                               repeat=enc["repeat"], roll=rng.random()) + \
               (f"（魔力 -{cost}）" if cost else ""), True, []

    return prefix + f"未知子命令【{verb}】。发送「#剑与魔法 帮助」查看全部。", bool(settled), []


def _has(bag: dict, name: str, qty: int) -> bool:
    return int(bag.get(name, 0) or 0) >= qty
