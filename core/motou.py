"""魔头禁术（对齐原版 model/forbiddenSoul.js，PvP 平衡版）。

- 镇魂资格：魔道值 ≥100（邪道身份）+ 双方气血 >0 + 攻击方境界 ≥30 + **境界差保护**（对方低你 >8 境拒绝）
  + **7 天受镇魂保护期** + 24h 冷却 + 消耗魔道值 30
- 处置三选一（10 分钟窗口）：烙印（对方魂印 3 天、闭关效率 -30%，你得魂奴+10% 三维）/ 灭魂（得遗蜕）/
  夺果（对方需境界 ≥40，你得道果可炼化修为+潜力）
- 魂印可花代价提前冲击解除（12h 冷却）
- 魔功：魔道值换永久三维加成（每级递增消耗）；供奉魔石：魔石→魔道值
- 简化砍：人傀链、万相魔冢/天魔化生/吞天魔功
"""

from __future__ import annotations

import copy
import time
from typing import Any, Mapping

MIN_MODAO = 100           # 邪道身份门槛
MIN_REALM = 30            # 斩道王者级（映射）
REALM_GAP_PROTECT = 8     # 目标低你超过 8 境 → 天道弱者保护
COOLDOWN = 24 * 3600
PROTECTION = 7 * 86400
BRAND_DURATION = 3 * 86400
DISPOSITION_TTL = 10 * 60
BREAK_CD = 12 * 3600
SLAY_MODAO_COST = 30
GUO_MIN_REALM = 40

MAGIC_COST = 80           # 魔功每级消耗魔道值（递增 ×1.5）
MAGIC_ATK_PCT = 0.08      # 每级三维 +8%
MAGIC_MAX = 10

MOSHI_MODAO = 20          # 每颗魔石供奉得魔道值


def state_of(doc: Mapping) -> dict:
    s = doc.ext.get("evil") if isinstance(doc.ext, Mapping) else None
    s = copy.deepcopy(s) if isinstance(s, dict) else {}
    s.setdefault("modao", float(doc.ext.get("modao", 0) or 0) if isinstance(doc.ext, Mapping) else 0.0)
    s.setdefault("magic", 0)
    s.setdefault("soul_slave", None)   # {"name":..., "until": ts}
    s.setdefault("remains", None)      # 待炼遗蜕
    s.setdefault("guo", None)          # 待炼道果
    s.setdefault("brand", None)        # 自身魂印 {"until": ts}
    s.setdefault("protected_until", 0.0)
    s.setdefault("slay_ts", 0.0)
    s.setdefault("pending", None)      # 待处置战果 {"target":..., "ts":..., "win":bool}
    s.setdefault("break_ts", 0.0)
    return s


def magic_cost(level: int) -> int:
    return int(MAGIC_COST * (1.5 ** int(level)))


def magic_bonus(s: Mapping) -> float:
    return MAGIC_ATK_PCT * int(s.get("magic", 0))


def train_magic(s: dict) -> tuple[bool, str, dict]:
    lv = int(s.get("magic", 0))
    if lv >= MAGIC_MAX:
        return False, f"魔功已至第 {MAGIC_MAX} 层（魔气满盈，再练恐道消）。", s
    cost = magic_cost(lv)
    if float(s.get("modao", 0)) < cost:
        return False, f"魔道值不足：修至第 {lv + 1} 层需 {cost}（当前 {int(s['modao'])}）。", s
    s["modao"] = float(s["modao"]) - cost
    s["magic"] = lv + 1
    return True, (f"魔功精进至第 {lv + 1} 层！三维永久 +{MAGIC_ATK_PCT:.0%}×{lv + 1}"
                  f"（累计 +{MAGIC_ATK_PCT * (lv + 1):.0%}，魔道值 -{cost}）"), s


def offer_moshi(s: dict, qty: int) -> tuple[bool, str, dict]:
    qty = max(1, int(qty))
    gain = MOSHI_MODAO * qty
    s["modao"] = float(s["modao"]) + gain
    return True, f"魔石 ×{qty} 化作精纯魔气——魔道值 +{gain}（当前 {int(s['modao'])}）。", s


def can_slay(attacker_s: dict, atk_realm: int, hp: int,
             target_s: dict, tgt_realm: int, tgt_hp: int, now: float) -> tuple[bool, str]:
    if float(attacker_s.get("modao", 0)) < MIN_MODAO:
        return False, f"你尚未真正踏入邪道（魔道值需 ≥{MIN_MODAO}）。"
    if hp <= 0:
        return False, "你已身受重创，无力施展禁术。"
    if tgt_hp <= 0:
        return False, "目标真灵沉寂（气血为 0），无法镇魂。"
    if atk_realm < MIN_REALM:
        return False, f"境界不足：需 {MIN_REALM} 境（斩道王者级）。"
    if tgt_realm < atk_realm - REALM_GAP_PROTECT:
        return False, "目标境界低你太多，受天道弱者保护，禁术反噬。"
    if now < float(target_s.get("protected_until", 0.0)):
        days = int((float(target_s["protected_until"]) - now) / 86400) + 1
        return False, f"目标仍受禁忌侵害保护（约 {days} 天）。"
    if now - float(attacker_s.get("slay_ts", 0.0)) < COOLDOWN:
        remain = int((COOLDOWN - (now - float(attacker_s["slay_ts"]))) / 3600) + 1
        return False, f"禁术因果未消，还需 {remain} 小时。"
    if attacker_s.get("pending"):
        return False, "你有一份尚未处置的战果（#处置 烙印/灭魂/夺果）。"
    return True, ""


def record_result(s: dict, target_name: str, win: bool, now: float) -> dict:
    s["slay_ts"] = now
    s["modao"] = max(0.0, float(s["modao"]) - SLAY_MODAO_COST)
    if win:
        s["pending"] = {"target": target_name, "ts": now}
    return s


def dispose(s: dict, kind: str, target_s: dict, now: float) -> tuple[bool, str, dict, dict]:
    """处置战果。返回 (ok, msg, 自己档, 对方档变更)。"""
    p = s.get("pending")
    if not p:
        return False, "没有待处置的镇魂战果。", s, {}
    if now - float(p.get("ts", 0)) > DISPOSITION_TTL:
        s["pending"] = None
        return False, "战果已消散（超过 10 分钟未处置）。", s, {}
    tname = p.get("target", "?")
    if kind == "烙印":
        if s.get("soul_slave"):
            return False, "你已有尚未消散的魂奴。", s, {}
        if target_s.get("brand"):
            return False, "目标已有魂印。", s, {}
        s["soul_slave"] = {"name": tname, "until": now + BRAND_DURATION}
        s["pending"] = None
        return True, (f"你在{tname}的真灵上烙下魂印！\n"
                      f"{tname} 魂印缠身 3 天（闭关效率 -30%）；你获魂奴「{tname}」（三维 +10%，3 天）。"), s, {
            "brand": {"until": now + BRAND_DURATION, "by": "镇魂"},
            "protected_until": now + PROTECTION,
        }
    if kind == "灭魂":
        if s.get("remains"):
            return False, "你已有一具待炼遗蜕。", s, {}
        s["remains"] = {"name": tname, "ts": now}
        s["pending"] = None
        return True, f"你斩灭{tname}一缕真灵，收得一具遗蜕（#炼化遗蜕 可得修为）。", s, {
            "protected_until": now + PROTECTION,
        }
    if kind == "夺果":
        if s.get("guo"):
            return False, "你已有一枚待炼道果。", s, {}
        return False, "目标尚未凝成可剥取的高阶道果（本插件未开放道果体系）。", s, {}
    return False, "可选处置：烙印 / 灭魂。", s, {}


def refine_remains(s: dict, realm_index: int) -> tuple[bool, str, dict, dict]:
    r = s.get("remains")
    if not r:
        return False, "没有待炼遗蜕。", s, {}
    gain = 20_000_000 * (max(1, realm_index) // 10 + 1)
    s["remains"] = None
    s["modao"] = float(s["modao"]) + 40
    return True, (f"炼化「{r['name']}」遗蜕：修为 +{gain:,}，魔道值 +40。"), s, {
        "exp": gain, "modao": 40,
    }


def break_brand(doc: Mapping, s: dict, now: float, stones: int) -> tuple[bool, str, dict]:
    b = s.get("brand")
    if not b:
        return False, "你身上没有魂印。", s
    if now - float(s.get("break_ts", 0.0)) < BREAK_CD:
        return False, "冲击魂印失败的后遗症未消，稍后再试。", s
    cost = 500_000
    if stones < cost:
        return False, f"冲击魂印需 {cost:,} 灵石（丹药/灵石护持）。", s
    s["brand"] = None
    s["break_ts"] = now
    return True, f"你以秘法冲击魂印，真灵震颤——魂印溃散！（灵石 -{cost:,}）", s


def brand_penalty(s: Mapping, now: float) -> float:
    """魂印在身时闭关效率惩罚（0.7 表示 -30%）。"""
    b = s.get("brand")
    if isinstance(b, dict) and now < float(b.get("until", 0)):
        return 0.7
    return 1.0


def slave_bonus(s: Mapping, now: float) -> float:
    """魂奴在侧的三维加成。"""
    sl = s.get("soul_slave")
    if isinstance(sl, dict) and now < float(sl.get("until", 0)):
        return 0.10
    return 0.0


def panel(s: Mapping, now: float) -> str:
    lines = [f"--- 邪道 · 魔头之路 ---",
             f"魔道值：{int(s.get('modao', 0))}｜魔功：第 {int(s.get('magic', 0))} 层（三维 +{magic_bonus(s):.0%}）"]
    brand = s.get("brand")
    if isinstance(brand, dict):
        left = int((float(brand.get("until", 0)) - now) / 3600) + 1
        lines.append(f"⚠ 魂印缠身：约 {left} 小时（闭关效率 -30%，#冲击魂印 可解）")
    slave = s.get("soul_slave")
    if isinstance(slave, dict):
        left = int((float(slave.get("until", 0)) - now) / 3600) + 1
        lines.append(f"魂奴：{slave.get('name')}（三维 +10%，约 {left} 小时）")
    if s.get("remains"):
        lines.append(f"待炼遗蜕：{s['remains'].get('name')}（#炼化遗蜕）")
    if s.get("pending"):
        lines.append("有待处置战果：#处置 烙印 / #处置 灭魂（10 分钟内）")
    lines.append(f"镇魂冷却：{'就绪' if now - float(s.get('slay_ts', 0)) >= COOLDOWN else '未消'}"
                 f"｜魔石供奉：#供奉魔石")
    lines.append("#镇魂 @目标（魔道 100+ / 境界 30+ / 无 7 天保护）｜#修炼魔功｜#冲击魂印")
    return "\n".join(lines)
