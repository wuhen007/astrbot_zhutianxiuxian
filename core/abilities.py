"""境界特技与批量操作（深度核查补漏 W28）——收编原版散件：

- 一键服用 / 一键回血：原版 `apps/User/UserSellAll.js`（6392 行）的一键
  系列精选。端口以 `use_item` 批量结算：`#一键服用 <物品名>` 吃光纳戒内
  该消耗品（单次上限 99，防误操作）；`#一键回血` 依次吃光所有带 HP/HPp
  字段的回复类物品直到血满。shortcut：原版一键赠送/一键卖矿/一键回收等
  与端口「转账/商店/图鉴」体系重叠，不另设。
- 极尽升华：原版 `apps/User/Level.js`——秘境体系 16 级独占路线点燃元神
  之光：攻防血 +300% 持续 30 秒，代价当前人体秘境永久降 1 级。端口换算：
  主轨 realm_index ≥ 40（仙台六层天对应线）；30 秒 → 10 分钟（群聊节奏
  放大，登记 shortcut）；乘区挂插件 `_stats`（全部战斗自动生效）。
- 自封帝号：原版 Level.js——天帝专属自定义帝号（≤12 字、禁词、数字
  拒绝；重定不改道果加成）。端口换算：证道成帝（zhengdao reached）即可。
- 堕入魔界：原版 `apps/motou/motou.js`——魔头挂机冒险（魔道 ≥100，
  60 分钟后归来）。端口按「异步定时→一次性结算」约定收编：扣魔道 100 +
  修为 4,000，立即结算历练收益（原版归来走统一动作结算器，收益按端口
  魔头经济口径合成：修为 800-1500×(1+魔功加成)、灵石 500-1200、魔道 +5）。

rng 约定：只用 rng.random()。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from typing import Any

from . import motou

SUBLIME_GATE = 40            # 主轨门槛（仙台六层天对应线，docstring 换算）
SUBLIME_MULT = 4.0           # 攻防血 ×4（原版 +300%）
SUBLIME_SECONDS = 600        # 原版 30 秒 → 10 分钟（群聊节奏，登记 shortcut）
BATCH_CAP = 99
MOJIE_MODEAO_COST = 100
MOJIE_EXP_COST = 4_000


# ---------------------------------------------------------------- 一键服用 / 一键回血

def batch_use(doc: Any, inv: Mapping[str, int], item_def: dict | None,
              max_hp: int, rng: Callable[[], float] | None = None,
              now: float | None = None, cap: int = BATCH_CAP) -> tuple[bool, str, int]:
    """#一键服用 <物品名>：吃光纳戒内该消耗品。返回 (ok, text, 消耗数量)。"""
    if item_def is None:
        return False, "没有这件物品的图鉴记录（#图鉴楼 查看物品）。", 0
    name = str(item_def.get("name") or "?")
    if item_def.get("class") == "装备" or str(item_def.get("type")) == "装备":
        return False, f"「{name}」是装备，请用 #装备 {name} 穿戴。", 0
    have = int((inv or {}).get(name, 0) or 0)
    if have < 1:
        return False, f"纳戒里没有「{name}」。", 0
    used = 0
    last_msg = ""
    while used < min(have, cap):
        ok, msg, new_doc, consumed = _use_once(doc, item_def, 1, max_hp, rng, now)
        if not ok or not consumed:
            if used == 0:
                return False, msg, 0
            last_msg = msg
            break
        _adopt(doc, new_doc)
        used += 1
        last_msg = msg
    tail = f"（上限 {cap}，剩余 {have - used} 件可继续）" if used >= cap and have > cap else ""
    return True, (f"【一键服用】{name} × {used}。\n{last_msg}{tail}"), used


def batch_heal(doc: Any, inv: Mapping[str, int], item_lookup: Callable[[str], dict | None],
               max_hp: int, rng: Callable[[], float] | None = None,
               now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    """#一键回血：依次吃光回复类物品直到血满。返回 (ok, text, 消耗表)。"""
    from . import wallet  # noqa: F401  (保持与其它模块一致的局部导入风格)
    heal_names = []
    for name in sorted((inv or {}).keys()):
        d = item_lookup(name) or {}
        if d.get("class") == "装备" or str(d.get("type")) == "装备":
            continue
        try:
            if (float(d.get("HP") or 0) > 0 or float(d.get("HPp") or 0) > 0):
                heal_names.append(name)
        except (TypeError, ValueError):
            continue
    if not heal_names:
        return False, "纳戒里没有可回复气血的丹药（#商店 购入血药）。", {}
    used: dict[str, int] = {}
    last_msg = ""
    for name in heal_names:
        item_def = item_lookup(name) or {}
        while int((inv or {}).get(name, 0) or 0) - used.get(name, 0) > 0:
            hp_now = int(float((getattr(doc, "ext", {}) or {}).get("hp", 0) or 0))
            if max_hp > 0 and hp_now >= max_hp:
                break
            ok, msg, new_doc, consumed = _use_once(doc, item_def, 1, max_hp, rng, now)
            if not ok or not consumed:
                last_msg = msg
                break
            _adopt(doc, new_doc)
            used[name] = used.get(name, 0) + 1
            last_msg = msg
    total = sum(used.values())
    if total == 0:
        return False, "气血已满（或丹药均已失效），无需回血。", {}
    detail = "、".join(f"{n}×{q}" for n, q in used.items())
    hp_now = int(float((getattr(doc, "ext", {}) or {}).get("hp", 0) or 0))
    return True, (f"【一键回血】消耗 {detail}。\n{last_msg}\n当前气血 {hp_now:,}/{max_hp:,}"), used


def _use_once(doc: Any, item_def: dict, qty: int, max_hp: int,
              rng: Callable[[], float] | None, now: float | None):
    """延迟导入避免与 items 的包级环；转换 use_item 的四元组。"""
    from . import items
    return items.use_item(doc, item_def, qty, max_hp=max_hp, rng=rng, now=now)


def _adopt(doc: Any, new_doc: Any) -> None:
    """把 use_item 返回的深拷贝档回写到调用方 doc（字段级拷贝）。"""
    for f in ("exp", "stones", "realm_index", "physique_index", "state", "state_start"):
        try:
            setattr(doc, f, getattr(new_doc, f))
        except Exception:
            pass
    ext_new = getattr(new_doc, "ext", None)
    if isinstance(ext_new, dict) and isinstance(getattr(doc, "ext", None), dict):
        doc.ext.clear()
        doc.ext.update(ext_new)


# ---------------------------------------------------------------- 极尽升华

def sublime_gate(doc: Any, now: float | None = None) -> str | None:
    until = float((getattr(doc, "ext", {}) or {}).get("sublime_until", 0) or 0)
    if until > (now if now is not None else time.time()):
        return "你已处于极尽升华状态！"
    ri = int(getattr(doc, "realm_index", 0) or 0)
    if ri < SUBLIME_GATE:
        return (f"【极尽升华·境界不足】只有主轨第 {SUBLIME_GATE + 1} 境"
                f"（仙台六层天对应线）以上的强者才能点燃元神之光。"
                f"当前第 {ri + 1} 境。")
    return None


def sublime_apply(doc: Any, st: dict | None = None, now: float | None = None) -> str:
    """确认升华：攻防血 ×4 持续 10 分钟，主轨永久 -1 境。
    状态写 doc.ext["sublime_until"]（_stats 乘区读同键）。"""
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["sublime_until"] = (now if now is not None else time.time()) + SUBLIME_SECONDS
    doc.realm_index = max(0, int(doc.realm_index) - 1)
    return "\n".join([
        "【极尽升华·终极一跃】",
        "元神之光轰然点燃！攻、防、血量临时提升至巅峰（×4，10 分钟）。",
        f"代价：主轨境界永久下降 1 级（现第 {int(doc.realm_index) + 1} 境）。",
        "升华期间所有战斗自动享受乘区——去 #讨伐boss 一跃封神！"])


def sublime_mult(doc: Any, now: float | None = None) -> float:
    if float((getattr(doc, "ext", {}) or {}).get("sublime_until", 0) or 0) > \
            (now if now is not None else time.time()):
        return SUBLIME_MULT
    return 1.0


# ---------------------------------------------------------------- 自封帝号

TITLE_FORBID = ("玉皇", "始皇帝", "天道", "系统")


def emperor_title_set(doc: Any, st: Mapping, title: str) -> tuple[bool, str]:
    """#自封帝号 X：证道成帝者自定义帝号（≤12 字、禁词、拒数字符号）。"""
    from . import zhengdao
    zst = zhengdao.state_of(doc)
    if not zst.get("reached"):
        return False, "帝威震荡！天道警示：唯有登临帝位者方可自封帝号。"
    title = str(title or "").strip()[:12]
    if not title:
        return False, "请填写帝号！示例：#自封帝号 焚天武帝"
    if any(w in title for w in TITLE_FORBID) or any(c.isdigit() for c in title):
        return False, f"〖天道反噬〗帝号「{title}」触及禁忌（禁词/数字），请重拟！"
    old = str(zst.get("emperor_title") or "")
    zst["emperor_title"] = title
    from . import zhengdao as _zd
    _zd.save(doc, zst)   # state_of 返回合并临时档，必须显式写回
    note = "帝号重定（道果加持仅限初封）。" if old else ""
    return True, "\n".join([
        "🜂 天道敕令·自封帝号 🜂",
        f"{getattr(doc, 'name') or '帝者'} 帝号定为：◈{title}◈" + (f"\n（原帝号：{old}｜{note}）" if old else "")])


# ---------------------------------------------------------------- 堕入魔界

def mojie_gate(doc: Any, s: Mapping) -> str | None:
    if int(getattr(doc, "exp", 0) or 0) < MOJIE_EXP_COST:
        return f"【堕入魔界·修为不足】需修为 {MOJIE_EXP_COST:,}。"
    if float(s.get("modao", 0) or 0) < MOJIE_MODEAO_COST:
        return ("【堕入魔界·非真魔】魔道值不足 100——供奉魔石或洗劫积攒魔道后再入。")
    return None


def mojie_run(doc: Any, s: dict, rng: Callable[[], float]) -> tuple[str, int]:
    """一次性结算魔界历练（shortcut 见模块 docstring）。返回 (text, 灵石)。"""
    s["modao"] = float(s.get("modao", 0) or 0) - MOJIE_MODEAO_COST
    doc.exp = max(0, int(doc.exp) - MOJIE_EXP_COST)
    magic_mult = 1.0 + motou.magic_bonus(s)
    exp_gain = int(rng.uniform(800, 1500) * magic_mult)
    stones_gain = int(rng.uniform(500, 1200))
    doc.exp += exp_gain
    doc.stones = int(getattr(doc, "stones", 0) or 0) + stones_gain
    s["modao"] = float(s.get("modao", 0) or 0) + 5
    return "\n".join([
        "【魔界·历练归来】",
        "血月之下厮杀一宿，魔气淬体，收获颇丰！", "",
        f"修为 +{exp_gain:,}｜灵石 +{stones_gain:,}｜魔道值 +5",
        f"当前魔道值：{float(s['modao']):.0f}"]), stones_gain
