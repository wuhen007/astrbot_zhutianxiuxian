"""本命帝兵炼制（对齐原版 Occupation.js forgeEmperorWeapon 系，量级适配版）。

原版公式：
- 炼制：仙金稀有度 9 → atk=def=HP=稀有度×800=7200；全属性 0.9；暴击 0.03；潜力 2.7
- 品阶链（遮天）：雏形→通灵→铭刻道与理→斩道王兵→圣兵→准帝兵→极道帝兵→仙器→仙王器→准仙帝器→仙帝器→祭道器
- 融合：每种仙金限一次提潜力（MAX 40）；**九金齐备是雷劫进阶硬前提**
- 蕴养：原版/次修为血气各 200 亿 + 本源 50，三维各 +50 亿 → 我们 ÷1000 修为血气、三维再 ÷10
  （→ 2000 万修为血气 / 三维各 +50 万），本源砍（本插件无此资源）
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any, Mapping

FORMS = ("剑", "鼎", "枪", "钟", "塔", "镜", "印", "刀", "斧", "戟", "鞭", "琴", "扇")

GOLD_RARITY = {
    "仙泪绿金": 9, "凰血赤金": 9, "龙纹黑金": 9, "永恒蓝金": 9, "神痕紫金": 9,
    "道劫黄金": 9, "羽化青金": 9, "混沌石精": 9, "大罗银精": 9,
    "九彩神金": 12, "万物母气": 10, "太初源金": 11, "混沌母金": 11, "万物源金": 11,
}

STAGES = ("雏形", "通灵", "铭刻道与理", "斩道王兵", "圣兵", "准帝兵", "极道帝兵",
          "仙器", "仙王器", "准仙帝器", "仙帝器", "祭道器")

MAX_POTENTIAL = 40
NURTURE_COST = 20_000_000        # 修为/血气各（原版 200 亿 ÷1000）
NURTURE_BOOST = 500_000          # 三维各（原版 50 亿 ÷1000 再 ÷10 适配量级）
TRIBULATION_COST = 50_000_000    # 雷劫洗礼修为/血气各


def system_of(doc: Mapping) -> dict:
    d = doc.ext.get("dibing") if isinstance(doc.ext, Mapping) else None
    return copy.deepcopy(d) if isinstance(d, dict) else {}


def name_ok(name: str) -> bool:
    return any(f in (name or "") for f in FORMS)


def forge(gold: str, name: str) -> tuple[bool, str, dict]:
    """以仙金炼制本命帝兵。"""
    if gold not in GOLD_RARITY:
        return False, f"「{gold}」不是可用仙金。可用：{'、'.join(GOLD_RARITY)}。", {}
    if not name_ok(name):
        return False, f"帝兵名称必须含形态字之一：{'、'.join(FORMS)}（如「混沌剑」）。", {}
    rar = GOLD_RARITY[gold]
    d = {
        "name": name, "gold": gold, "stage": 0,
        "atk": rar * 800, "def": rar * 800, "hp": rar * 800,
        "all": round(rar * 0.1, 2), "bao": 0.03,
        "potential": round(rar * 0.3, 2), "nurture": 0, "fused": [],
    }
    return True, (
        f"神纹交织，炉火冲霄——本命帝兵【{name}】出世！\n"
        f"品阶：雏形｜三维 {rar * 800:,}｜全属性 +{d['all']}｜暴击 +3%｜潜力 {d['potential']}/40\n"
        f"九金融合可提升潜力，齐备后 #雷劫洗礼帝兵 终极一跃。"
    ), d


def fuse(d: Mapping, gold: str) -> tuple[bool, str, dict]:
    """以仙金融合帝兵：潜力 +3，每种仙金限一次。"""
    w = copy.deepcopy(dict(d))
    if gold not in GOLD_RARITY:
        return False, f"「{gold}」不是可用仙金。", w
    if gold == w.get("gold"):
        return False, "主材仙金不可再次融合。", w
    fused = list(w.get("fused") or [])
    if gold in fused:
        return False, f"「{gold}」已融合过了（每种仙金限一次）。", w
    if float(w.get("potential", 0)) >= MAX_POTENTIAL:
        return False, f"帝兵潜力已达上限（{MAX_POTENTIAL}）。", w
    fused.append(gold)
    w["fused"] = fused
    w["potential"] = min(MAX_POTENTIAL, round(float(w.get("potential", 0)) + 3, 2))
    total = len(set(fused) | {w.get("gold")})
    return True, (
        f"【{w['name']}】熔入「{gold}」，器身再凝一道仙纹！\n"
        f"潜力 {w['potential']}/40｜已融仙金 {total}/9"
        + ("\n九金齐备！可 #雷劫洗礼帝兵 终极一跃。" if total >= 9 else "")
    ), w


def tribulation(d: Mapping, exp: int, xueqi: float) -> tuple[bool, str, dict]:
    """雷劫洗礼：需九金全融合，消耗修为血气，品阶 +1（必成，原版语义即"齐备即跃迁"）。"""
    w = copy.deepcopy(dict(d))
    stage = int(w.get("stage", 0))
    if stage >= len(STAGES) - 1:
        return False, f"「{w['name']}」已至最高品阶【{STAGES[-1]}】。", w
    total = len(set(list(w.get("fused") or []) + [w.get("gold")]))
    if total < 9:
        need = [g for g in GOLD_RARITY if g not in (set(list(w.get('fused') or []) + [w.get('gold')]))]
        return False, (f"「{w['name']}」需融合全部九种仙金才能承受雷劫洗礼。\n"
                       f"缺少：{'、'.join(need[:9])}"), w
    if exp < TRIBULATION_COST or xueqi < TRIBULATION_COST:
        return False, f"雷劫洗礼需修为/血气各 {TRIBULATION_COST:,}（当前 {exp:,}/{int(xueqi):,}）。", w
    w["stage"] = stage + 1
    return True, (
        f"九金共鸣，天雷灌顶——【{w['name']}】渡过雷劫，进阶【{STAGES[stage + 1]}】！\n"
        f"（当前品阶 {stage + 2}/{len(STAGES)}，蕴养上限提升）"
    ), w


def nurture_limit(stage: int) -> int:
    return 5 + int(stage) * 3


def nurture(d: Mapping, times: int, exp: int, xueqi: float) -> tuple[bool, str, dict, dict]:
    """蕴养帝兵：/次修为血气各 2000 万，三维各 +50 万、全属性 +1。"""
    w = copy.deepcopy(dict(d))
    stage = int(w.get("stage", 0))
    cap = nurture_limit(stage)
    done = int(w.get("nurture", 0))
    if done >= cap:
        return False, f"蕴养已达上限（{done}/{cap}），雷劫进阶可提升上限。", w, {}
    times = max(1, min(int(times or 1), cap - done))
    cost = NURTURE_COST * times
    if exp < cost or xueqi < cost:
        return False, f"蕴养需修为/血气各 {cost:,}（当前 {exp:,}/{int(xueqi):,}）。", w, {}
    w["nurture"] = done + times
    boost = NURTURE_BOOST * times
    w["atk"] = int(w.get("atk", 0)) + boost
    w["def"] = int(w.get("def", 0)) + boost
    w["hp"] = int(w.get("hp", 0)) + boost
    w["all"] = round(float(w.get("all", 0)) + times, 2)
    return True, (
        f"温养 {times} 次，【{w['name']}】器灵渐醒：三维 +{boost:,}，全属性 +{times}"
        f"（蕴养 {w['nurture']}/{cap}）"
    ), w, {"exp": cost, "xueqi": cost}


def rename(d: Mapping, new_name: str) -> tuple[bool, str, dict]:
    w = copy.deepcopy(dict(d))
    if not name_ok(new_name):
        return False, f"新名称必须含形态字：{'、'.join(FORMS)}。", w
    old = w.get("name")
    w["name"] = new_name
    return True, f"帝兵「{old}」更名為「{new_name}」，器灵铭刻新名。", w


def item_card(d: Mapping) -> dict:
    """帝兵档 → 物品卡（供 #装备 穿戴与 aggregate 聚合）。"""
    return {
        "name": d.get("name"),
        "class": "装备",
        "type": "帝兵",
        "atk": int(d.get("atk", 0)),
        "def": int(d.get("def", 0)),
        "HP": int(d.get("hp", 0)),
        "全属性": float(d.get("all", 0)),
        "bao": float(d.get("bao", 0)),
        "出售价": int(d.get("atk", 0)) * 20,
        "品阶": STAGES[int(d.get("stage", 0))],
    }


def summary(d: Mapping) -> str:
    stage = int(d.get("stage", 0))
    fused = list(d.get("fused") or [])
    total = len(set(fused + [d.get("gold")]))
    cap = nurture_limit(stage)
    return (
        f"--- 本命帝兵 · {d.get('name')} ---\n"
        f"品阶：{STAGES[stage]}（{stage + 1}/{len(STAGES)}）\n"
        f"三维：{int(d.get('atk', 0)):,}｜全属性 +{d.get('all', 0)}｜暴击 +{float(d.get('bao', 0)):.0%}\n"
        f"潜力：{d.get('potential', 0)}/{MAX_POTENTIAL}｜主材：{d.get('gold')}\n"
        f"已融仙金 {total}/9：{'、'.join(fused) or '（仅主材）'}\n"
        f"蕴养：{d.get('nurture', 0)}/{cap}\n"
        f"#装备 {d.get('name')} 穿戴｜#蕴养帝兵*次数｜#融合帝兵 仙金｜#雷劫洗礼帝兵｜#为帝兵更名 新名"
    )
