"""诸天世界深度玩法（对齐原版 model/zhutianMirror.js + zhutianjing/mokashaonv.js）。

- 库洛牌：4 组合（疾风封印/元素共鸣/月华守护/梦境回廊）、3 卡编组
- 月之审判：10 牌 + 境界，成功率 = min(0.95, 0.3 + 熟练度/100×0.5 + 月华守护 0.25)，失败 2 次后第 3 次必成
- 梦之试炼：月之审判 + 52 牌全 + 境界，逐重梦境进度
- 小樱进阶：星之杖（10 牌+审判+熟练度 50）→ 梦之杖（试炼通过）
- 帝骑：3 卡编组、融合度（探索涨，≥100 危机）、最终攻击驾驭（镜阶≥3+卡组+融合度≥60 → -70）
- 救赎：装载鹿目圆系化身 + 希望碎片 ≥ 门槛 → 净化自己/他人（消耗希望碎片）

境界映射：原版「仙台秘境大能」→ 本插件 realm_index ≥ 40（标注偏差）。
"""

from __future__ import annotations

import random
from typing import Any, Mapping

CARD_COMBOS: dict[str, list[str]] = {
    "疾风封印": ["风", "翔", "影"],
    "元素共鸣": ["火", "水", "地"],
    "月华守护": ["光", "暗", "盾"],
    "梦境回廊": ["镜", "梦", "时"],
}

MIN_REALM = 40
MOON_MIN_CARDS = 10
DREAM_MIN_CARDS = 52
STAR_WAND_PROF = 50

DECADE_MIN_TIER = 3
FUSION_MAX = 100
FUSION_CRISIS = 100
FINAL_RIDE_MIN_FUSION = 60
FINAL_RIDE_CUT = 70
REDEEM_HOPE_COST = 10


def sakura_of(zt: Mapping) -> dict:
    s = zt.get("sakura") if isinstance(zt, Mapping) else None
    if not isinstance(s, dict):
        s = {}
    s.setdefault("deck", [])
    s.setdefault("combo", "")
    s.setdefault("prof", 0)
    s.setdefault("moon_pass", False)
    s.setdefault("moon_tries", 0)
    s.setdefault("dream", 0)
    s.setdefault("dream_pass", False)
    s.setdefault("wand", "初始封印杖")
    return s


def decade_of(zt: Mapping) -> dict:
    d = zt.get("decade") if isinstance(zt, Mapping) else None
    if not isinstance(d, dict):
        d = {}
    d.setdefault("deck", [])
    d.setdefault("fusion", 0)
    d.setdefault("explore", 0)
    d.setdefault("resonance", 0)
    return d


def combo_of(cards: list[str]) -> str:
    sel = set(cards)
    for name, need in CARD_COMBOS.items():
        if all(c in sel for c in need):
            return name
    return ""


# ---- 库洛牌 ----

def set_clow_deck(zt: dict, cards: list[str]) -> tuple[bool, str, dict]:
    s = sakura_of(zt)
    names = [c.strip() for c in cards if c and c.strip()]
    if len(names) != 3:
        return False, "需编组恰好 3 张库洛牌（#库洛牌组合 风*翔*影）。", s
    owned = list(zt.get("clow_cards") or [])
    missing = [c for c in names if c not in owned]
    if missing:
        return False, f"尚未封印：{'、'.join(missing)}（#探索友枝町 收集）。", s
    s["deck"] = names
    s["combo"] = combo_of(names)
    tail = f"激活组合【{s['combo']}】！" if s["combo"] else "三牌未成组合（组合表见 #库洛牌组合 无参查看）。"
    return True, f"出战卡组已编组：{'、'.join(names)}。{tail}", s


def moon_trial(zt: dict, realm_index: int, rng: random.Random) -> tuple[bool, str, dict]:
    s = sakura_of(zt)
    if s["moon_pass"]:
        return False, "已通过月之审判（#小樱进阶 继续）。", s
    cards = list(zt.get("clow_cards") or [])
    if len(cards) < MOON_MIN_CARDS:
        return False, f"月之审判需至少封印 {MOON_MIN_CARDS} 张库洛牌（当前 {len(cards)}）。", s
    if realm_index < MIN_REALM:
        return False, f"境界不足：需 {MIN_REALM} 境（仙台大能级），当前 {realm_index}。", s
    combo_bonus = 0.25 if s.get("combo") == "月华守护" else 0.0
    rate = min(0.95, 0.3 + (int(s["prof"]) / 100) * 0.5 + combo_bonus)
    pity = int(s["moon_tries"]) >= 2
    head = (f"【月之审判】审判者月的法阵展开……\n"
            + ("库洛牌组合【月华守护】展开，成功率 +25%。\n" if combo_bonus else "")
            + (f"两次审判的经验共鸣，本次必定通过。\n" if pity else f"当前审判成功率 {rate:.0%}。\n"))
    if pity or rng.random() < rate:
        s["moon_pass"] = True
        s["prof"] = int(s["prof"]) + 30
        return True, (head + "「树牌！」你尝试束缚月却被反射回来——\n"
                      "「星之杖」绽放光芒，你用「风牌」温柔地包裹住月！\n"
                      "月宣布：你已成为库洛牌的新主人，不是因为力量，而是因为你的心！\n"
                      f"（魔法熟练度 +30 → {s['prof']}）"), s
    s["moon_tries"] = int(s["moon_tries"]) + 1
    return True, (head + "月的审判之刃斩落——你被击退了。\n"
                  f"（修为损失 10%；审判失败 {s['moon_tries']}/2 次，第 3 次必定通过）"), s


def dream_trial(zt: dict, realm_index: int) -> tuple[bool, str, dict]:
    s = sakura_of(zt)
    if s["dream_pass"]:
        return False, "已通过梦之试炼。", s
    if not s["moon_pass"]:
        return False, "需先通过月之审判（#月之审判）。", s
    cards = len(list(zt.get("clow_cards") or []))
    if cards < DREAM_MIN_CARDS:
        return False, f"需收集全部 {DREAM_MIN_CARDS} 张库洛牌（当前 {cards}）。", s
    if realm_index < MIN_REALM:
        return False, f"境界不足：需 {MIN_REALM} 境，当前 {realm_index}。", s
    step = int(s["dream"])
    stages = [
        ("第一重梦境：友枝小学的众人化作卡牌！", "以「镜」牌看破幻觉", "镜" in (zt.get("clow_cards") or [])),
        ("第二重梦境：库洛的虚影要求你展现与卡牌的羁绊", "52 张基础牌齐备", cards >= DREAM_MIN_CARDS),
        ("最终梦境：透明卡牌环绕，创造属于你的新卡牌",
         "魔法熟练度 ≥100", int(s["prof"]) >= 100),
    ]
    if step >= len(stages):
        s["dream_pass"] = True
        s["wand"] = "梦之杖"
        s["dream"] = step + 1
        return True, "梦境破碎，晨光洒落——你通过了梦之试炼！魔杖化作「梦之杖」。", s
    title, need, ok = stages[step]
    if not ok:
        return False, f"【{title}】\n需要：{need}（当前不满足）。", s
    s["dream"] = step + 1
    bonus = "（梦之杖共鸣，进度额外 +1）" if s["wand"] == "梦之杖" else ""
    if step == len(stages) - 1:
        s["dream_pass"] = True
        s["wand"] = "梦之杖"
        return True, f"【{title}】\n{need} 达成{bonus}——梦之试炼通过！魔杖化作「梦之杖」。", s
    return True, f"【{title}】\n{need} 达成{bonus}——进入下一重梦境。", s


def advance_sakura(zt: dict, realm_index: int) -> tuple[bool, str, dict]:
    s = sakura_of(zt)
    wand = s["wand"]
    if wand == "梦之杖":
        return False, "木之本樱已至「梦之杖」形态，登峰造极。", s
    if wand == "星之杖":
        if not s["dream_pass"]:
            return False, "进阶梦之杖需先通过梦之试炼（#梦之试炼）。", s
        s["wand"] = "梦之杖"
        return True, "星之杖在梦中蜕变——「梦之杖」形态达成！", s
    cards = len(list(zt.get("clow_cards") or []))
    lacks = []
    if realm_index < MIN_REALM:
        lacks.append(f"境界 {MIN_REALM}（当前 {realm_index}）")
    if cards < MOON_MIN_CARDS:
        lacks.append(f"库洛牌 {MOON_MIN_CARDS} 张（当前 {cards}）")
    if not s["moon_pass"]:
        lacks.append("通过月之审判")
    if int(s["prof"]) < STAR_WAND_PROF:
        lacks.append(f"魔法熟练度 {STAR_WAND_PROF}（当前 {s['prof']}）")
    if lacks:
        return False, "进阶星之杖条件未满足：\n· " + "\n· ".join(lacks), s
    s["wand"] = "星之杖"
    return True, "光芒万丈——「星之杖」形态达成！继续收集 52 张牌并通过梦之试炼可进阶梦之杖。", s


# ---- 帝骑 ----

def set_decade_deck(zt: dict, cards: list[str]) -> tuple[bool, str, dict]:
    d = decade_of(zt)
    names = [c.strip() for c in cards if c and c.strip()]
    if len(names) != 3:
        return False, "需编组恰好 3 张骑士卡（#编组骑士卡片 空我*龙骑*Faiz）。", d
    owned = list(zt.get("rider_cards") or [])
    missing = [c for c in names if c not in owned]
    if missing:
        return False, f"尚未收录：{'、'.join(missing)}（#探索骑士世界 收集）。", d
    d["deck"] = names
    return True, f"骑士卡组已编组：{'、'.join(names)}。卡组决定帝骑终结技的技能池。", d


def final_ride(zt: dict, tier: int) -> tuple[bool, str, dict]:
    d = decade_of(zt)
    if tier < DECADE_MIN_TIER:
        return False, f"镜阶不足：需 {DECADE_MIN_TIER} 阶（当前 {tier}）。", d
    if not d["deck"]:
        return False, "尚未编组骑士卡片（#编组骑士卡片）。", d
    if int(d["fusion"]) < FINAL_RIDE_MIN_FUSION:
        return False, f"世界融合度不足：需 {FINAL_RIDE_MIN_FUSION}（当前 {d['fusion']}，探索骑士世界可积累）。", d
    before = int(d["fusion"])
    d["fusion"] = max(0, before - FINAL_RIDE_CUT)
    return True, (f"「最终攻击驾驭！」三卡共鸣，{ '、'.join(d['deck']) } 的力量汇聚一斩——\n"
                  f"世界融合危机压下：融合度 {before} → {d['fusion']}。"), d


def redeem(zt: dict, cur_avatar: str, target_is_self: bool) -> tuple[bool, str, dict]:
    """救赎：装载鹿目圆系化身，消耗希望碎片净化。"""
    if "鹿目圆" not in (cur_avatar or ""):
        return False, "需装载鹿目圆系化身（#装载化身 鹿目圆）才能施展希望之力。", zt
    hopes = int(zt.get("hopes", 0) or 0)
    if hopes < REDEEM_HOPE_COST:
        return False, f"希望碎片不足：需 {REDEEM_HOPE_COST}（当前 {hopes}，探索见泷原积累）。", zt
    zt = dict(zt)
    zt["hopes"] = hopes - REDEEM_HOPE_COST
    who = "自身" if target_is_self else "指定的道友"
    return True, (f"希望之光自灵魂宝石绽放，{who}的污浊被净化——绝望散去，因果归于平静。\n"
                  f"（希望碎片 -{REDEEM_HOPE_COST}，余 {zt['hopes']}）"), zt
