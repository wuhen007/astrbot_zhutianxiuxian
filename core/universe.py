"""大宇宙体系（对齐原版 model/grandUniverse.js，Python 直译 MVP）。

- 小世界 5 级圆满 + 境界（映射权柄 18 → 我们 46 金仙）+ 仙道潜力 ≥151（替代"自身之道+道行"门槛，标注偏差）
- 法则阶段 0-5（宇宙初生→帝光诸天）：potential/aura 直用原版，修为血气 ÷1000 换算（原版 50-800 亿，我们体系量级不同）
- 灵韵折算公式直译：clamp(10, 5000, 20 + 稀有度×25 + log10(出售价+1)×10)
- 宇宙秘境：铸造 100 灵韵、12 座上限、进入 8h CD；演绎代价 ÷1000
- 简化：源石（我们无此资源，演绎代价去掉源石项）、访客记录、UGC 秘境编辑
"""

from __future__ import annotations

import copy
import math
import random
import time
from typing import Any, Mapping

MIN_REALM = 46          # 原版 GRAND_UNIVERSE_MIN_AUTHORITY=18（仙王）→ 我们 46 金仙
MIN_POTENTIAL = 151     # 原版 LAW_STAGES[0].daoRequired（道行 151 次）→ 潜力门槛（偏差标注）
MAX_DUNGEONS = 12
DUNGEON_CD = 8 * 3600
FORGE_AURA_COST = 100

LAW_STAGES: list[dict] = [
    {"level": 0, "name": "宇宙初生", "capacity": "真仙", "potential": 0, "cultivation": 0, "aura": 0},
    {"level": 1, "name": "红尘天则", "capacity": "红尘仙", "potential": 500, "cultivation": 5_000_000, "aura": 200},
    {"level": 2, "name": "王境法域", "capacity": "仙王", "potential": 1_000, "cultivation": 10_000_000, "aura": 300},
    {"level": 3, "name": "绝顶王域", "capacity": "绝顶仙王", "potential": 2_000, "cultivation": 20_000_000, "aura": 500},
    {"level": 4, "name": "巨头天宇", "capacity": "仙王巨头", "potential": 4_000, "cultivation": 40_000_000, "aura": 800},
    {"level": 5, "name": "帝光诸天", "capacity": "帝光仙王", "potential": 8_000, "cultivation": 80_000_000, "aura": 1_200},
]

AURA_CATEGORIES = {"装备", "丹药", "道具", "功法", "草药", "食材", "材料", "仙宠口粮", "盒子", "宝石"}

DERIVE_COST = {"exp": 10_000_000, "xueqi": 10_000_000, "aura": 1_000}  # 原版 10 万亿 ÷1000，源石项砍


def system_of(doc: Mapping) -> dict:
    """取 ext["universe"] 深拷贝（纯函数，调用方写回）。"""
    u = doc.ext.get("universe") if isinstance(doc.ext, Mapping) else None
    u = copy.deepcopy(u) if isinstance(u, dict) else None
    return u or {}


def aura_value(item: Mapping) -> int:
    """灵韵折算（原版 getItemAuraValue 直译）。"""
    try:
        rarity = max(0, int(float(item.get("稀有度", item.get("pinji", item.get("品级", 0))) or 0)))
    except (TypeError, ValueError):
        rarity = 0
    try:
        price = max(0.0, float(item.get("出售价", item.get("售价", item.get("price", 0))) or 0))
    except (TypeError, ValueError):
        price = 0.0
    return max(10, min(5_000, round(20 + rarity * 25 + math.log10(price + 1) * 10)))


def can_ascend(doc: Mapping) -> dict:
    """升格条件检查。返回 {ok, reason?, required?}。"""
    world = doc.ext.get("xiaoshijie") or {}
    if not world:
        return {"ok": False, "reason": "world"}
    if doc.ext.get("universe"):
        return {"ok": False, "reason": "ascended"}
    if int(world.get("level", 0) or 0) < 5:
        return {"ok": False, "reason": "world-level", "current": int(world.get("level", 0) or 0)}
    if doc.realm_index < MIN_REALM:
        return {"ok": False, "reason": "authority", "current": doc.realm_index, "required": MIN_REALM}
    potential = float(doc.ext.get("potential", 0) or 0)
    if potential < MIN_POTENTIAL:
        return {"ok": False, "reason": "potential", "current": potential, "required": MIN_POTENTIAL}
    return {"ok": True}


def ascend(doc: Mapping, now: float) -> tuple[bool, str, dict]:
    """小世界升格大宇宙。"""
    check = can_ascend(doc)
    if not check["ok"]:
        why = {
            "world": "你尚未开辟小世界（#开辟小世界）。",
            "ascended": "你的小世界早已升格为大宇宙。",
            "world-level": f"小世界尚未演化圆满（当前 {check.get('current', 0)}/5 级）。",
            "authority": f"境界不足：需金仙（{check['required']} 境），当前 {check.get('current', 0)} 境。",
            "potential": f"仙道潜力不足：当前 {check.get('current', 0):g}，需 {check['required']}（凝聚精血可提升）。",
        }.get(check["reason"], "条件未满足。")
        return False, why, {}
    world = doc.ext.get("xiaoshijie") or {}
    u = {
        "name": str(world.get("name") or "无名大宇宙"),
        "ascend_ts": now,
        "dao_name": "自身之道",
        "law": 0,
        "law_refined": 0,
        "aura": 0,
        "open": True,
        "dungeons": [],
        "visits": 0,
    }
    return True, (f"轰——小世界「{u['name']}」升格为大宇宙！\n"
                  "宇宙初生，法则初成（承载上限：真仙）。\n"
                  "以「#炼化宇宙灵韵 物品*数量」喂养宇宙，#完善宇宙法则 提升承载上限，"
                  "#铸造宇宙秘境 开辟创世试炼。"), u


def refine_law(doc: Mapping, u: dict) -> tuple[bool, str, dict, dict]:
    """完善宇宙法则 *档位（默认下一档）。返回 (ok, msg, u, consume)。"""
    law = int(u.get("law", 0))
    nxt = law + 1
    if nxt >= len(LAW_STAGES):
        return False, "宇宙法则已臻帝光诸天，万道俯首，无可再完善。", u, {}
    stage = LAW_STAGES[nxt]
    potential = float(doc.ext.get("potential", 0) or 0)
    if potential < stage["potential"]:
        return False, f"仙道潜力不足：需 {stage['potential']}，当前 {potential:g}。", u, {}
    if u.get("aura", 0) < stage["aura"]:
        return False, f"宇宙灵韵不足：需 {stage['aura']}，当前 {u.get('aura', 0)}（#炼化宇宙灵韵 积累）。", u, {}
    consume = {"exp": stage["cultivation"], "xueqi": stage["cultivation"], "potential": stage["potential"], "aura": stage["aura"]}
    u["law"] = nxt
    u["law_refined"] = int(u.get("law_refined", 0)) + 1
    u["aura"] = int(u.get("aura", 0)) - stage["aura"]
    msg = (f"法则完善！宇宙升至【{stage['name']}】，承载上限提升至 {stage['capacity']}。"
           f"（消耗修为/血气各 {stage['cultivation']:,}、仙道潜力 {stage['potential']}、灵韵 {stage['aura']}）")
    return True, msg, u, consume


def refine_aura(item: Mapping, qty: int) -> int:
    """炼化 n 件物品的灵韵总额。"""
    return aura_value(item) * max(1, int(qty))


def forge_dungeon(u: dict, name: str, intro: str, enemy: str) -> tuple[bool, str, dict]:
    """铸造宇宙秘境（100 灵韵）。"""
    dungeons: list[dict] = u.setdefault("dungeons", [])
    if len(dungeons) >= MAX_DUNGEONS:
        return False, f"宇宙秘境数量已达 {MAX_DUNGEONS} 座上限。", u
    if any(d["name"] == name for d in dungeons):
        return False, "大宇宙中已有同名秘境。", u
    if int(u.get("aura", 0)) < FORGE_AURA_COST:
        return False, f"宇宙灵韵不足：需 {FORGE_AURA_COST}，当前 {u.get('aura', 0)}。", u
    u["aura"] = int(u["aura"]) - FORGE_AURA_COST
    dungeons.append({"name": name, "intro": intro[:60], "enemy": enemy[:16], "cleared": 0})
    return True, (f"宇宙秘境【{name}】铸造完成！（消耗灵韵 {FORGE_AURA_COST}，"
                  f"余 {u['aura']}）\n简介：{intro[:60]}\n守关者：{enemy[:16]}\n"
                  f"挑战：#进入宇宙秘境 {name}"), u


def dungeon_enemy(law: int, rng: random.Random) -> dict:
    """守关者数值（按法则阶段定标）。"""
    base = 80_000 * (law + 1)
    return {"atk": int(base * 1.1), "defense": int(base * 0.9), "hp": base * 30, "bao": 0.1}


def enter_dungeon(doc: Mapping, u: dict, name: str, now: float,
                  stats: Mapping, rng: random.Random) -> tuple[bool, str, dict, dict | None]:
    """挑战宇宙秘境（8h CD，复用切磋引擎单挑）。consume/exp 由调用方落盘。"""
    d = next((x for x in u.get("dungeons", []) if x["name"] == name), None)
    if not d:
        return False, "大宇宙中没有这座秘境。", u, None
    last = float(doc.ext.get("udungeon_ts", 0.0))
    if now - last < DUNGEON_CD:
        remain_h = int((DUNGEON_CD - (now - last)) / 3600) + 1
        return False, f"神魂尚未恢复（约 {remain_h} 小时后可再入秘境）。", u, None
    enemy = dungeon_enemy(int(u.get("law", 0)), rng)
    won, log = quick_duel(stats, enemy, rng)
    u["visits"] = int(u.get("visits", 0)) + 1
    if won:
        d["cleared"] = int(d.get("cleared", 0)) + 1
        aura_gain = 80 + rng.randrange(50)
        u["aura"] = int(u.get("aura", 0)) + aura_gain
        msg = (f"踏入秘境【{name}】——{d.get('intro', '')}\n"
               f"守关者【{d.get('enemy', '?')}】被你击败！宇宙反馈灵韵 ×{aura_gain}。")
    else:
        msg = (f"踏入秘境【{name}】——{d.get('intro', '')}\n"
               f"不敌守关者【{d.get('enemy', '?')}】，神魂重创被送出（无损失，8 小时后再战）。")
    return True, msg, u, {"won": won, "log": log}


def quick_duel(stats: Mapping, enemy: Mapping, rng: random.Random) -> tuple[bool, list[str]]:
    """轻量单挑（复用 harm 公式的速算版）：返回 (胜负, 战报)。"""
    from . import battle as battle_mod
    me_hp, en_hp = int(stats.get("hp", 1)), int(enemy["hp"])
    log: list[str] = []
    for rnd in range(1, 31):
        dmg, crit = battle_mod.harm(int(stats.get("atk", 1)), int(enemy["defense"]), rng,
                                    float(stats.get("bao", 0)))
        en_hp -= dmg
        log.append(f"第{rnd}合：你打出 {dmg}{'（暴击）' if crit else ''}，守关者余 {max(0, en_hp)}")
        if en_hp <= 0:
            return True, log
        back, _ = battle_mod.harm(int(enemy["atk"]), int(stats.get("defense", 1)), rng)
        me_hp -= back
        log.append(f"        守关者反击 {back}，你余 {max(0, me_hp)}")
        if me_hp <= 0:
            return False, log
    return me_hp * 3 >= en_hp * 2, log  # 30 合未分胜负按剩余战力判


def derive_dungeon(u: dict, name: str, rng: random.Random) -> tuple[bool, str, dict, dict]:
    """演绎宇宙秘境：随机生成一座新秘境（消耗修为/血气/灵韵）。"""
    dungeons: list[dict] = u.setdefault("dungeons", [])
    if len(dungeons) >= MAX_DUNGEONS:
        return False, f"宇宙秘境数量已达 {MAX_DUNGEONS} 座上限。", u, {}
    if any(d["name"] == name for d in dungeons):
        return False, "大宇宙中已有同名秘境。", u, {}
    if int(u.get("aura", 0)) < DERIVE_COST["aura"]:
        return False, f"宇宙灵韵不足：需 {DERIVE_COST['aura']}，当前 {u.get('aura', 0)}。", u, {}
    u["aura"] = int(u["aura"]) - DERIVE_COST["aura"]
    prefixes = ["太初", "鸿蒙", "寂灭", "万象", "归墟", "周天"]
    enemies = ["古道残魂", "纪元兽", "法则傀儡", "混沌遗种", "劫灰之主"]
    enemy = f"{rng.choice(prefixes)}{rng.choice(enemies)}"
    intro = f"万物轮回演绎而生的秘境，藏有宇宙本源的馈赠。"
    dungeons.append({"name": name, "intro": intro, "enemy": enemy, "cleared": 0})
    return True, (f"万物轮回，演绎成真！秘境【{name}】自虚空中浮现。\n"
                  f"守关者：{enemy}（消耗修为/血气各 {DERIVE_COST['exp']:,}、灵韵 {DERIVE_COST['aura']}）"), u, {
        "exp": DERIVE_COST["exp"], "xueqi": DERIVE_COST["xueqi"]}
