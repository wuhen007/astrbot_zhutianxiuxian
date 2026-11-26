"""凡间限时副本·灵界裂缝（移植 apps/SecretPlace/LingjieRift.js + model/lingjieRift.js）。

原版要素（保持一致）：6 小时现世窗口、15 分钟探索、每人 2~5 重界印、
2000 年里程碑 30% 概率现世、0.12 锚符掉落、探索后 18%/8% 伏杀、14% 尸骸余波。

shortcut: 原版怪物是写死的 30 级数值（攻 220~480 万），本插件改为按玩家三维 ×0.85
缩放 —— 单轨境界（realm_index 1..64）下写死数值会随境界脱节。
shortcut: 原版三人伏杀走 zd_battle 团战，这里按顺序单挑（血量延续），
避免为单一副本引入团战引擎；三人全胜才算通关。
"""

from __future__ import annotations

import random
from typing import Any, Mapping

from .battle import Unit

RIFT_DURATION = 6 * 3600          # 现世 6 小时
EXPLORE_SECONDS = 15 * 60         # 基础探索 15 分钟
MIN_EXPLORE_SECONDS = 60          # 加速下限 1 分钟
SPAWN_CHANCE = 0.3                # 里程碑现世概率
COORD_MAX = 999                   # 凡间坐标 0..999
ATTEMPT_MIN, ATTEMPT_MAX = 2, 5   # 每人基础界印
ANCHOR_DROP = 0.12                # 探索掉落界隙锚符
ANCHOR_ITEM = "界隙锚符"
REALM_GATE = 26                   # 紫府元神 ≈ 本插件洞照境初期（realm_index 26）
MONSTER_FACTOR = 0.85             # 裂缝生灵相对玩家三维的强度
MAX_ANCHOR_EXTRA = 1              # 锚符只能重新锚定一次

MONSTER_NAMES = ("裂界噬魂兽", "虚空魔蜕", "失乡界灵", "裂隙守门者")

XIUXEI_PILLS = ("裂隙凝元丹", "裂隙化元丹", "裂隙天元丹")
XUEQI_PILLS = ("裂隙锻血丹", "裂隙血髓丹", "裂隙龙髓丹")
POTENTIAL_PILLS = ("叩仙丹", "问道丹", "化仙丹")

AMBUSH_NAMES = ("陆沉", "顾玄", "姜离", "秦烬", "宁无尘", "谢长庚")


# ---- 裂缝本体 ----

def default_state() -> dict[str, Any]:
    return {"rift": None, "tasks": {}, "visits": {}, "milestone": ""}


def ensure(value: Mapping | None) -> dict[str, Any]:
    state = dict(value or {})
    for key, default in default_state().items():
        state.setdefault(key, default)
    if not isinstance(state.get("tasks"), dict):
        state["tasks"] = {}
    if not isinstance(state.get("visits"), dict):
        state["visits"] = {}
    return state


def create_rift(era: Mapping | None, rng: random.Random, now: float) -> dict[str, Any]:
    era = era or {}
    return {
        "id": f"lingjie_{int(era.get('epoch', 1) or 1)}_{int(era.get('index', 0) or 0)}_"
              f"{int(era.get('years', 0) or 0)}_{int(now)}",
        "x": rng.randint(0, COORD_MAX),
        "y": rng.randint(0, COORD_MAX),
        "base_attempts": rng.randint(ATTEMPT_MIN, ATTEMPT_MAX),
        "created_at": now,
        "expires_at": now + RIFT_DURATION,
    }


def base_attempts(rift: Mapping) -> int:
    n = int(rift.get("base_attempts") or 0)
    return n if n > 0 else ATTEMPT_MIN


def is_milestone(years: Any) -> bool:
    try:
        v = int(years)
    except (TypeError, ValueError):
        return False
    return v > 0 and v % 2000 == 0


def parse_coordinate(text: str) -> tuple[int, int] | None:
    """`#前往 12,34` / `#探索 12，34` → (12, 34)。"""
    import re

    m = re.match(r"^#(?:前往|探索)\s*(\d{1,3})\s*[,，]\s*(\d{1,3})$", (text or "").strip())
    if not m:
        return None
    x, y = int(m.group(1)), int(m.group(2))
    if x > COORD_MAX or y > COORD_MAX:
        return None
    return x, y


def is_at(player_pos: Any, rift: Mapping) -> bool:
    if not player_pos:
        return False
    try:
        return int(player_pos[0]) == int(rift.get("x")) and int(player_pos[1]) == int(rift.get("y"))
    except (TypeError, ValueError, IndexError):
        return False


def can_start(
    doc, rift: Mapping | None, now: float, required: int = EXPLORE_SECONDS
) -> tuple[bool, str]:
    """准入判定。返回 (ok, 原因)。原因码与文案由 handler 映射。"""
    if not rift or float(rift.get("expires_at", 0) or 0) <= now:
        return False, "collapsed"
    if int(getattr(doc, "realm_index", 0) or 0) < REALM_GATE:
        return False, "realm"
    if not is_at(doc.ext.get("lingjie_pos"), rift):
        return False, "coordinate"
    if float(rift.get("expires_at", 0) or 0) - now < required:
        return False, "time"
    return True, ""


def explore_duration(doc) -> tuple[int, list[str]]:
    """探索耗时（秒）+ 加速说明。行字秘/天璇步法按原版减时。"""
    skills = list(doc.ext.get("gongfa") or [])
    msgs: list[str] = []
    cut = 0
    if "行字秘" in skills:
        minutes = 2
        realm = int(getattr(doc, "realm_index", 0) or 0)
        if realm >= 9:
            minutes += 1
        if realm >= 16:
            minutes += 1
        cut += minutes * 60
        msgs.append(f"行字秘贯穿界壁：-{minutes} 分钟")
    elif "天璇步法" in skills:
        cut += 60
        msgs.append("天璇步法踏过乱流：-1 分钟")
    return max(MIN_EXPLORE_SECONDS, EXPLORE_SECONDS - cut), msgs


# ---- 探索结算材料 ----

def make_monster(base: tuple[int, int, int], rng: random.Random, speed: int = 100) -> Unit:
    """裂缝生灵：玩家三维 × 0.85，±15% 浮动。"""
    patk, pdef, php = base
    f = MONSTER_FACTOR
    return Unit(
        rng.choice(MONSTER_NAMES),
        max(1, int(patk * f * (0.85 + 0.3 * rng.random()))),
        max(1, int(pdef * f * (0.85 + 0.3 * rng.random()))),
        max(1, int(php * f * (0.9 + 0.2 * rng.random()))),
        bao=0.12, speed=max(1, int(speed)),
    )


def make_ambusher(base: tuple[int, int, int], rng: random.Random, name: str,
                  speed: int = 100) -> Unit:
    """伏杀者：原版 30 级 NPC（三维 +150 万），改为玩家三维 ×0.9。"""
    patk, pdef, php = base
    return Unit(
        f"{name}（伏杀者）",
        max(1, int(patk * 0.9)),
        max(1, int(pdef * 0.9)),
        max(1, int(php * 0.9)),
        bao=0.16, speed=max(1, int(speed)),
    )


def roll_aftermath(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.18:
        return "ambush"
    if r < 0.26:
        return "triple_ambush"
    if r < 0.40:
        return "corpse"
    return "none"


def roll_corpse_extras(rng: random.Random) -> dict[str, bool]:
    return {
        "grass": rng.random() < 0.3,
        "water": rng.random() < 0.12,
        "fate_reroll": rng.random() < 0.005,
        "fate_slot": rng.random() < 0.001,
    }


def reward_multiplier(doc) -> tuple[float, list[str]]:
    """奖励倍率：灵根天赋（魔卡少女系列/神慧者）+ 幸运丹 buff。"""
    root = doc.ext.get("linggen") or {}
    root_type = str((root or {}).get("type") or "")
    mult = 1.0
    msgs: list[str] = []
    if root_type == "魔卡少女":
        mult += 1
        msgs.append("魔卡少女灵根：物品数量 ×2")
    elif root_type == "魔卡少女·觉醒":
        mult += 1
        msgs.append("星之杖觉醒：物品数量 ×2")
    elif root_type == "魔卡少女·完全":
        mult += 3
        msgs.append("梦之杖完全解放：物品数量 ×5")
    elif root_type == "神慧者":
        mult *= 10
        msgs.append("神慧之光：物品数量 ×10")
    buffs = dict(doc.ext.get("buffs") or {})
    lucky = buffs.get("lucky")
    if isinstance(lucky, dict) and float(lucky.get("times", 0) or 0) > 0:
        mult *= 1 + float(lucky.get("bonus", 0) or 0)
        lucky["times"] = int(float(lucky["times"])) - 1
        buffs["lucky"] = lucky
        doc.ext["buffs"] = buffs
        msgs.append(f"幸运显化：物品数量 ×{1 + float(lucky.get('bonus', 0) or 0):g}")
    return mult, msgs


def roll_rewards(rng: random.Random, mult: float) -> list[dict[str, Any]]:
    """主奖励：三种裂隙丹 + 道心果/天药/功法/锚符按概率追加。"""
    out: list[dict[str, Any]] = [
        {"name": rng.choice(POTENTIAL_PILLS), "cls": "丹药", "count": max(1, int(mult))},
        {"name": rng.choice(XIUXEI_PILLS), "cls": "丹药", "count": max(1, int(mult))},
        {"name": rng.choice(XUEQI_PILLS), "cls": "丹药", "count": max(1, int(mult))},
    ]
    heart = rng.random()
    if heart < 0.08:
        out.append({"name": "玄品道心果", "cls": "丹药", "count": 1})
    elif heart < 0.35:
        out.append({"name": "凡品道心果", "cls": "丹药", "count": 1})
    if rng.random() < 0.25:
        out.append({"name": "九转天药" if rng.random() < 0.1 else "天药", "cls": "丹药", "count": 1})
    if rng.random() < 0.08:
        out.append({"name": "太虚蕴神经", "cls": "功法", "count": 1})
    if rng.random() < ANCHOR_DROP:
        out.append({"name": ANCHOR_ITEM, "cls": "道具", "count": 1})
    return out


def attempt_state(state: Mapping, uid: str, rift: Mapping) -> dict[str, int]:
    """当前裂缝下该玩家的界印使用情况（换裂缝自动清零）。"""
    visits = (state.get("visits") or {}).get(str(uid))
    if not isinstance(visits, dict) or visits.get("rift") != rift.get("id"):
        return {"used": 0, "extra": 0}
    return {"used": int(visits.get("used", 0) or 0), "extra": int(visits.get("extra", 0) or 0)}


def remaining_attempts(state: Mapping, uid: str, rift: Mapping) -> int:
    st = attempt_state(state, uid, rift)
    return max(0, base_attempts(rift) + st["extra"] - st["used"])


def bump_attempt(state: dict, uid: str, rift: Mapping, kind: str = "used") -> dict[str, int]:
    """记录一次探索（kind='used'）或一次锚符（kind='extra'）。原地修改 state。"""
    visits = state.setdefault("visits", {})
    cur = visits.get(str(uid))
    if not isinstance(cur, dict) or cur.get("rift") != rift.get("id"):
        cur = {"rift": rift.get("id"), "used": 0, "extra": 0}
    cur[kind] = int(cur.get(kind, 0) or 0) + 1
    visits[str(uid)] = cur
    return cur


def status_text(rift: Mapping | None, now: float, doc=None, rem: int | None = None) -> str:
    if not rift or float(rift.get("expires_at", 0) or 0) <= now:
        return (
            "【灵界裂缝】\n当前凡间没有现世的灵界裂缝。\n"
            "每逢两千年，界壁皆有概率松动（每个里程碑 30%）。"
        )
    left = max(0, int(float(rift["expires_at"]) - now))
    h, m = left // 3600, left % 3600 // 60
    lines = [
        "【灵界裂缝·现世】",
        f"凡间坐标：{rift.get('x')},{rift.get('y')}",
        f"距离坍塌：{h} 小时 {m} 分钟" if h else f"距离坍塌：{m} 分钟",
        f"基础界印：每位修士 {base_attempts(rift)} 重",
        f"准入：洞照境及以上（realm_index ≥ {REALM_GATE}）",
        f"前往：#前往 {rift.get('x')},{rift.get('y')}",
        "抵达后发送：#探索灵界裂缝",
        f"追加次数：#使用{ANCHOR_ITEM}",
    ]
    if doc is not None and rem is not None:
        lines.append(f"你的界印：剩余 {rem} 次")
    return "\n".join(lines)


def describe(rift: Mapping, now: float, doc=None, rem: int | None = None) -> str:
    return status_text(rift, now, doc, rem)
