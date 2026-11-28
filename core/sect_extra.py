"""宗门深层补全：召唤神兽 / 神兽赐福 / 药园（W23-F1）——原版, fund
`apps/Association/Association.js` 中 beast/herb 系列指令的纯函数移植。

原版语义：
- #召唤神兽：宗门等级 ≥8、建设等级 ≥50、有驻地且基金 ≥2,000,000
  （青龙/白虎/朱雀/玄武/麒麟），每位成员按北京时间自然日各可领取一次赐福。
- #神兽赐福：每日一次；默认 30% 掉落，神赐丹按剩余次数提高掉落概率。
- #药园：宗门药园种植草药，成员可收获；#拔苗助长 偷拔加速成熟。

本移植（shortcut）：
- 神兽为宗门级共享（全服唯一 per 宗门），无独立成长线；原版自动日常仍需主入口调度接线，赐福领域函数手动/自动共用。
- 药园简化为 6 块地、4 种种子、按小时成熟；#拔苗助长 有 30% 品质惩罚。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc
from .clock import day_key

BEASTS = ("青龙", "白虎", "朱雀", "玄武", "麒麟")
BEAST_COST = 2_000_000
BEAST_LEVEL = 8
BEAST_BUILD = 50
HERB_SLOTS = 6
HERBS = ("万年凝血草", "万年何首乌", "万年血精草", "万年清心草")
GROW_HOURS = 8
def beast_of(s: Mapping[str, Any]) -> str:
    return str(s.get("beast") or "")


def beast_cd_left(doc: PlayerDoc, now: float) -> float:
    if doc.ext.get("beast_bless_day") != day_key(now):
        return 0.0
    return 86400 - (now + 8 * 3600) % 86400


def summon_beast(doc: PlayerDoc, s: dict[str, Any], fund: int, level: int,
                 now: float, rng: random.Random,
                 ) -> tuple[bool, str, int]:
    """召唤神兽：宗门等级 8、建设 50、有驻地、基金 200 万。"""
    if level < BEAST_LEVEL:
        return False, f"召唤神兽需宗门等级 ≥{BEAST_LEVEL}（当前 {level}）。", fund
    if int(s.get("build") or 0) < BEAST_BUILD:
        return False, f"召唤神兽需建设等级 ≥{BEAST_BUILD}（当前 {int(s.get('build') or 0)}）。", fund
    if str(s.get("place") or "").strip() in ("", "0"):
        return False, "召唤神兽需先建立宗门驻地。", fund
    if fund < BEAST_COST:
        return False, f"召唤神兽需宗门基金 {BEAST_COST:,}（当前 {fund:,}）。", fund
    if s.get("beast"):
        return False, f"本宗已有护山神兽【{s['beast']}】。", fund
    roll = rng.random()
    s["beast"] = ("麒麟" if roll > 0.8 else "青龙" if roll > 0.6 else
                  "玄武" if roll > 0.4 else "朱雀" if roll > 0.2 else "白虎")
    s["beast_bless_ts"] = 0.0
    new_fund = fund - BEAST_COST
    return True, (f"召唤成功，神兽{s['beast']}投下一道分身，开始守护宗门；绑定后不可更换。"
                  f"宗门基金 −{BEAST_COST:,}。"), new_fund

def _beast_reward_pool(beast: str, preferred: bool,
                       pools: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if beast == "麒麟":
        rows = pools.get("qilin") if preferred else pools.get("danyao")
        max_rarity = 4
    elif beast == "青龙":
        rows = pools.get("qinglong") if preferred else pools.get("gongfa")
        max_rarity = 4
    elif beast in {"玄武", "朱雀", "白虎"}:
        rows = pools.get("xuanwu") if preferred else pools.get("equipment")
        max_rarity = None
    else:
        return []
    result = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, Mapping) or not item.get("name") or not item.get("class"):
            continue
        if beast in {"麒麟", "青龙"}:
            try:
                if int(item.get("稀有度")) > max_rarity:
                    continue
            except (TypeError, ValueError):
                continue
        elif item.get("name") == "大罗剑胎":
            continue
        result.append(item)
    return result


def beast_bless(doc: PlayerDoc, s: dict[str, Any], fund: int, now: float,
                rng: random.Random, reward_pools: Mapping[str, Any] | None = None,
                ) -> tuple[bool, str, dict[str, int], int]:
    """每日赐福；按原版机缘 buff 决定掉落，并从对应神兽物品池取 1 件。"""
    beast = str(s.get("beast") or "")
    if not beast:
        return False, "本宗尚无护山神兽——#召唤神兽 先。", {}, fund
    left = beast_cd_left(doc, now)
    if left > 0:
        return False, f"【{beast}】尚在沉睡，{int(left // 3600)} 小时后方可赐福。", {}, fund

    buffs = dict(doc.ext.get("buffs") or {})
    favor = dict(buffs.get("shenci") or {})
    uses = max(0, int(float(favor.get("times", 0) or 0)))
    bonus = float(favor.get("bonus", 0) or 0) if uses else 0.0
    if uses:
        uses -= 1
        favor.update({"times": uses, "bonus": bonus if uses else 0.0})
        buffs["shenci"] = favor

    if rng.random() + bonus <= 0.7:
        doc.ext["beast_bless_day"] = day_key(now)
        if buffs:
            doc.ext["buffs"] = buffs
        return True, f"{beast}今日无意赐下宝物，明日再来。", {}, fund

    preferred = rng.random() > 0.9
    pool = _beast_reward_pool(beast, preferred, reward_pools or {})
    if not pool and preferred:
        pool = _beast_reward_pool(beast, False, reward_pools or {})
        preferred = False
    if not pool:
        return False, f"{beast}的赐福物品池暂不可用，本次未消耗每日次数。", {}, fund
    item = pool[min(len(pool) - 1, int(rng.random() * len(pool)))]

    doc.ext["beast_bless_day"] = day_key(now)
    if buffs:
        doc.ext["buffs"] = buffs
    label = "仔细挑选" if preferred else "随手赐下"
    return True, f"【{beast}赐福】{label}「{item['name']}」×1。", {str(item["name"]): 1}, fund

# ---------------------------------------------------------------- 药园

def herb_garden(s: dict[str, Any]) -> dict[str, Any]:
    g = s.get("herb_garden")
    if not isinstance(g, dict):
        g = {}
    for i in range(HERB_SLOTS):
        g.setdefault(f"slot_{i}", None)   # {"herb": 名, "planted_at": ts}
    s["herb_garden"] = g
    return g


def plant(doc: PlayerDoc, s: dict[str, Any], slot: int, herb: str, now: float,
          ) -> tuple[bool, str]:
    """#药园栽种 药名（种入空地块）。"""
    g = herb_garden(s)
    if not (0 <= slot < HERB_SLOTS):
        return False, f"药园共 {HERB_SLOTS} 块地（0~{HERB_SLOTS - 1}）。"
    if herb not in HERBS:
        return False, f"可选药草：{'、'.join(HERBS)}。"
    if g[f"slot_{slot}"]:
        return False, f"{slot} 号地已有作物。"
    g[f"slot_{slot}"] = {"herb": herb, "planted_at": now}
    return True, f"【药园】{herb} 已种入 {slot} 号地（{GROW_HOURS} 小时后成熟）。"


def harvest(doc: PlayerDoc, s: dict[str, Any], slot: int, now: float,
            rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#药园收获 slot：成熟产出 2~4 株。"""
    g = herb_garden(s)
    entry = g.get(f"slot_{slot}")
    if not isinstance(entry, dict):
        return False, f"{slot} 号地是空的。", {}
    elapsed = (now - float(entry["planted_at"])) / 3600
    if elapsed < GROW_HOURS:
        return False, f"{entry['herb']} 还需 {GROW_HOURS - elapsed:.1f} 小时成熟。"
    qty = 2 + int(rng.random() * 3) % 3
    g[f"slot_{slot}"] = None
    return True, f"【药园收获】{entry['herb']} ×{qty} 已入纳戒。", {entry["herb"]: qty}


def uproot(doc: PlayerDoc, s: dict[str, Any], slot: int, now: float,
           rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#拔苗助长 slot：30% 品质惩罚（只出 1 株），70% 正常收获 3 株。"""
    g = herb_garden(s)
    entry = g.get(f"slot_{slot}")
    if not isinstance(entry, dict):
        return False, f"{slot} 号地是空的。", {}
    if rng.random() < 0.30:
        g[f"slot_{slot}"] = None
        return True, f"【拔苗助长】用力过猛——{entry['herb']} 连根拔坏了！", {}
    qty = 1 if rng.random() < 0.5 else 3
    g[f"slot_{slot}"] = None
    return True, f"【拔苗助长】催熟成功！{entry['herb']} ×{qty} 已入纳戒。", {entry["herb"]: qty}


def garden_text(s: dict[str, Any], now: float) -> str:
    g = herb_garden(s)
    lines = [f"--- 药园（{HERB_SLOTS} 块地）---"]
    for i in range(HERB_SLOTS):
        e = g.get(f"slot_{i}")
        if isinstance(e, dict):
            left = max(0.0, GROW_HOURS - (now - float(e["planted_at"])) / 3600)
            lines.append(f"  {i} 号：{e['herb']}（{'已成熟' if left <= 0 else f'剩 {left:.1f}h'}）")
        else:
            lines.append(f"  {i} 号：（空）")
    lines.append("栽种：#药园栽种 地块编号 药名｜收获：#药园收获 地块编号｜"
                 "催熟：#拔苗助长 地块编号")
    lines.append(f"可选药草：{'、'.join(HERBS)}")
    return "\n".join(lines)
