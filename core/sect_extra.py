"""宗门深层补全：召唤神兽 / 神兽赐福 / 药园（W23-F1）——原版
`apps/Association/Association.js` 中 beast/herb 系列指令的纯函数移植。

原版语义：
- #召唤神兽：宗门等级 ≥5 且宗门基金 ≥50,000 → 随机获得一只护山神兽
  （青龙/白虎/朱雀/玄武/麒麟），每位成员按北京时间自然日各可领取一次赐福。
- #神兽赐福：消耗宗门基金 10,000 → 随机 buff（三维加成/修为/灵石/洗根水）。
- #药园：宗门药园种植草药，成员可收获；#拔苗助长 偷拔加速成熟。

本移植（shortcut）：
- 神兽为宗门级共享（全服唯一 per 宗门），无独立成长线。
- 药园简化为 6 块地、4 种种子、按小时成熟；#拔苗助长 有 30% 品质惩罚。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc
from .clock import day_key

BEASTS = ("青龙", "白虎", "朱雀", "玄武", "麒麟")
BEAST_COST = 50_000
BEAST_LEVEL = 5
BLESS_COST = 10_000
BLESS_POOL = (
    ("三维加成", "全属性 +5%（24h）"),
    ("修为暴涨", "修为 +50,000"),
    ("灵石雨", "灵石 +20,000"),
    ("洗根水", "洗根水 ×2"),
    ("幸运草", "幸运草 ×3"),
)
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
    """#召唤神兽：宗门等级 ≥5 + 基金 50,000 → 随机神兽。返回 (ok,msg,新基金)。"""
    if level < BEAST_LEVEL:
        return False, f"召唤神兽需宗门等级 ≥{BEAST_LEVEL}（当前 {level}）。", fund
    if fund < BEAST_COST:
        return False, f"召唤神兽需宗门基金 {BEAST_COST:,}（当前 {fund:,}）。"
    if s.get("beast"):
        return False, f"本宗已有护山神兽【{s['beast']}】。", fund
    bl = list(BEASTS)
    s["beast"] = bl[int(rng.random() * len(bl)) % len(bl)]
    s["beast_bless_ts"] = 0.0
    new_fund = fund - BEAST_COST
    return True, (f"≡≡≡ 神兽降世 ≡≡≡\n"
                  f"{doc.name or doc.uid[:8]} 以宗门气运为引，"
                  f"【{s['beast']}】自虚空中降临，俯首于山门！\n"
                  f"消耗基金 {BEAST_COST:,}。每日 #神兽赐福 一次。"), new_fund


def beast_bless(doc: PlayerDoc, s: dict[str, Any], fund: int, now: float,
                rng: random.Random,
                ) -> tuple[bool, str, dict[str, int], int]:
    """#神兽赐福：每日一次，基金 10,000 → 随机奖励。"""
    if not s.get("beast"):
        return False, "本宗尚无护山神兽——#召唤神兽 先。", {}, fund
    left = beast_cd_left(doc, now)
    if left > 0:
        return False, f"【{s['beast']}】尚在沉睡，{int(left // 3600)} 小时后方可赐福。", {}, fund
    if fund < BLESS_COST:
        return False, f"神兽赐福需基金 {BLESS_COST:,}（当前 {fund:,}）。", {}, fund
    bp = list(BLESS_POOL)
    name, desc = bp[int(rng.random() * len(bp)) % len(bp)]
    delta: dict[str, int] = {}
    detail = ""
    if name == "修为暴涨":
        doc.exp = int(getattr(doc, "exp", 0) or 0) + 50_000
        detail = "修为 +50,000"
    elif name == "灵石雨":
        doc.stones = int(getattr(doc, "stones", 0) or 0) + 20_000
        detail = "灵石 +20,000"
    elif name == "三维加成":
        s["beast_buff_until"] = now + 86400
        detail = "全属性 +5%（24h）"
    else:
        delta[name] = 2
        detail = f"{name} ×2"
    doc.ext["beast_bless_day"] = day_key(now)
    new_fund = fund - BLESS_COST
    return True, (f"【{s['beast']}·赐福】{desc}——{detail}"), delta, new_fund


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
