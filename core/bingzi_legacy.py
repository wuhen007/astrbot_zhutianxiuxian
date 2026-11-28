"""秦门兵字秘传承（原版 model/bingziLegacy.js + RealmEvents 兵字秘事件移植）。

原版要点：
- 限时 24 小时的全服事件：追查蔡族 → 跟踪月灵公主（真山线索=3 山区间+奇偶）→
  辨认石山*1-9（3 次机会，错误提示更近/更远主峰）→ 月下观兵 → 以器证兵（武器名）。
- 评分：追查 +10、跟踪 +10、寻山 max(10, 40-10×已猜次数)、观兵 +25+悟性(≤20)、
  证兵 +15（普通）/ +25（帝兵）。
- 结算排名：完成 > 参悟分 > 完成时间 > 加入时间；魁首习得【兵字秘】功法；
  其余按进度得 兵字秘残卷 ×3/×2/×1（完成/找到真山/仅追查）。

移植口径（差异已标注）：
- 原版挂在 RealmEvents 事件档 cron；本移植懒推进：任何入口先 maybe_tick()
  （到期结算 + 过期 3 天后自动开启新一届，duration 24h）。
- 世界状态存 calamity_state["bingzi_legacy"]（单例，与 realm_event 同库）。
- 观兵悟性取玩家 ext["insight"]（功法感悟值），钳 0-20。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

EXT_KEY = "bingzi_legacy"
TECHNIQUE = "兵字秘"
FRAGMENT = "兵字秘残卷"
MOUNTAIN_COUNT = 9
DURATION = 24 * 3600
RESPAWN_AFTER = 3 * 24 * 3600      # 结算后 3 天开启新一届
GUESS_LIMIT = 3
MAX_INSIGHT = 20


def world_of(world: Mapping) -> dict[str, Any]:
    st = world.get(EXT_KEY) if isinstance(world, Mapping) else None
    if not isinstance(st, Mapping):
        st = {}
    return {
        "events": list(st.get("events") or []),   # 历届（含已结算）
    }


def save_world(world: dict, st: Mapping) -> None:
    world[EXT_KEY] = {"events": list(st.get("events") or [])}


def _active(st: Mapping) -> dict | None:
    for ev in reversed(st.get("events") or []):
        if ev.get("status") == "active":
            return ev
    return None


def _latest(st: Mapping) -> dict | None:
    events = st.get("events") or []
    return events[-1] if events else None


def maybe_tick(world: Mapping, now: float) -> tuple[bool, str]:
    """惰性推进：到期结算；结算超过 3 天则开启新一届。返回 (是否有变化, 提示)。"""
    st = world_of(world)
    events = st["events"]
    act = _active(st)
    if act and now >= float(act.get("expires_at") or 0):
        settle(act, now)
        save_world(world, st)
        return True, "【秦门兵图·显化已终】本届兵字秘传承已结算，#兵字秘榜 查看排名。"
    if not act:
        latest = _latest(st)
        if latest and now < float(latest.get("expires_at") or 0) + RESPAWN_AFTER:
            return False, ""
        spawn(events, now)
        save_world(world, st)
        return True, "【秦门兵图】月华再临，秦门兵字秘传承开启（24 小时）：#秦门兵图 查看详情。"
    return False, ""


def spawn(events: list, now: float) -> dict:
    ev = {
        "opened_at": float(now), "expires_at": float(now) + DURATION,
        "status": "active", "target_mountain": random.randint(1, MOUNTAIN_COUNT),
        "participants": {}, "rankings": [], "winner": None,
        "rewarded": [], "settled_at": 0,
    }
    events.append(ev)
    return ev


def _participant(ev: dict, uid: str, name: str) -> dict:
    parts = ev.setdefault("participants", {})
    key = str(uid)
    if key not in parts:
        parts[key] = {"uid": key, "name": str(name or key), "joined_at": time.time(),
                      "traced": False, "tracked": False, "guesses": [],
                      "found": False, "observed": False, "weapon": "",
                      "completed_at": 0, "score": 0}
    return parts[key]


def _rank(participants: Mapping) -> list[dict]:
    rows = [dict(p) for p in (participants or {}).values()]
    rows.sort(key=lambda p: (-int(bool(p.get("completed_at"))), -int(p.get("score", 0) or 0),
                             float(p.get("completed_at") or float("inf")),
                             float(p.get("joined_at") or 0)))
    return rows


def settle(ev: dict, now: float) -> None:
    if ev.get("status") == "settled":
        return
    ev["status"] = "settled"
    ev["settled_at"] = float(now)
    ev["rankings"] = _rank(ev.get("participants"))
    winner = next((r for r in ev["rankings"] if r.get("completed_at")), None)
    ev["winner"] = {"uid": winner["uid"], "name": winner["name"],
                    "weapon": winner.get("weapon") or ""} if winner else None


def trace_cai_clan(world: Mapping, uid: str, name: str) -> tuple[bool, str]:
    """#追查蔡族。"""
    st = world_of(world)
    ev = _active(st)
    if not ev:
        return False, "秦门兵图已经隐去。"
    p = _participant(ev, uid, name)
    if p["traced"]:
        return False, "你已经查明秦门掌教一脉与蔡族的关系。"
    p["traced"] = True
    p["score"] += 10
    save_world(world, st)
    return True, ("【兵字秘·追查蔡族】\n你翻阅秦岭旧卷，查明秦门掌教一脉正是蔡族后人。\n"
                  "主峰还藏有可度化修士心神的度神诀，贸然潜入风险极高。\n"
                  f"参悟分：{p['score']}\n下一步：#跟踪月灵公主")


def track_moon_princess(world: Mapping, uid: str) -> tuple[bool, str]:
    """#跟踪月灵公主：取得真山区间+奇偶线索。"""
    st = world_of(world)
    ev = _active(st)
    if not ev:
        return False, "月灵公主的踪迹已经消失。"
    p = _participant(ev, uid, "")
    if not p["traced"]:
        return False, "需先发送 #追查蔡族，确定兵字秘确在秦门。"
    if p["tracked"]:
        return False, "你已经记下月灵公主的换山轨迹。"
    p["tracked"] = True
    p["score"] += 10
    target = int(ev.get("target_mountain") or 1)
    start = (target - 1) // 3 * 3 + 1
    parity = "偶数" if target % 2 == 0 else "奇数"
    save_world(world, st)
    return True, ("【兵字秘·月灵踪迹】\n你避开秦门主峰，在外围九座石山间跟随月灵公主留下的月华痕迹。\n"
                  f"真山位于第{start}至第{start + 2}山之间，并且序号是{parity}。\n"
                  "使用 #辨认石山*数字 作出判断，最多三次。")


def identify_mountain(world: Mapping, uid: str, mountain: int) -> tuple[bool, str]:
    """#辨认石山*N：3 次机会，错则提示方向。"""
    st = world_of(world)
    ev = _active(st)
    if not ev:
        return False, "月华消散，秦门兵图已经隐去。"
    p = _participant(ev, uid, "")
    if not p["tracked"]:
        return False, "需先发送 #跟踪月灵公主，取得九山线索。"
    if p["found"]:
        return False, "你已经找到了兵图所在的真山。"
    mountain = int(mountain)
    if mountain < 1 or mountain > MOUNTAIN_COUNT:
        return False, f"石山序号在 1-{MOUNTAIN_COUNT} 之间。"
    if mountain in p["guesses"]:
        return False, "这座石山你已经辨认过。"
    if len(p["guesses"]) >= GUESS_LIMIT:
        return False, "三次辨山机会已经用尽，本次只能带走一份残缺道痕。"
    p["guesses"].append(mountain)
    target = int(ev.get("target_mountain") or 1)
    if mountain != target:
        save_world(world, st)
        direction = "更靠近主峰" if mountain < target else "更远离主峰"
        return False, (f"第{mountain}山只有普通控器刻痕，并非兵字秘真迹。\n"
                       f"余韵表明真山{direction}。\n剩余机会：{GUESS_LIMIT - len(p['guesses'])}")
    p["found"] = True
    p["score"] += max(10, 40 - len(p["guesses"]) * 10)
    save_world(world, st)
    return True, (f"【兵字秘·真山寻获】第{target}山月华汇聚——兵字秘真迹现世！\n"
                  f"参悟分：{p['score']}（辨山 {len(p['guesses'])} 次命中）\n"
                  "下一步：#月下观兵")


def observe_diagram(world: Mapping, uid: str, insight: int) -> tuple[bool, str]:
    """#月下观兵：悟性加成 ≤20。"""
    st = world_of(world)
    ev = _active(st)
    if not ev:
        return False, "月华消散，秦门兵图已经隐去。"
    p = _participant(ev, uid, "")
    if not p["found"]:
        return False, "需先找到兵图所在的真山（#辨认石山*N）。"
    if p["observed"]:
        return False, "你已观得完整兵图。"
    insight = max(0, min(MAX_INSIGHT, int(insight or 0)))
    p["observed"] = True
    p["score"] += 25 + insight
    save_world(world, st)
    return True, (f"【兵字秘·月下观兵】月华映照石壁，完整兵图烙入道心（悟性加成 +{insight}）。\n"
                  f"参悟分：{p['score']}\n"
                  "下一步：#以器证兵 武器名（携帝兵者 +25 分，普通器 +15 分）")


def declare_weapon(world: Mapping, uid: str, weapon: str,
                   is_emperor: bool = False) -> tuple[bool, str]:
    """#以器证兵 武器名：证兵完成。is_emperor 由 handler 按至宝/帝兵佩戴判定。"""
    st = world_of(world)
    ev = _active(st)
    if not ev:
        return False, "月华消散，秦门兵图已经隐去。"
    p = _participant(ev, uid, "")
    if not p["observed"]:
        return False, "需先 #月下观兵，观得完整兵图。"
    if p.get("completed_at"):
        return False, "你已经以此器证兵。"
    weapon = str(weapon or "").strip()
    if not weapon:
        return False, "需报出证兵之器的名字。"
    p["weapon"] = weapon[:40]
    p["score"] += 25 if is_emperor else 15
    p["completed_at"] = time.time()
    save_world(world, st)
    return True, (f"【兵字秘·以器证兵】「{p['weapon']}」与兵图共鸣——证兵完成！\n"
                  f"参悟分：{p['score']}｜事件结束时按完成度、参悟分与完成时间择主。")


def rankings(world: Mapping) -> tuple[dict | None, list[dict]]:
    """#兵字秘榜：先惰性结算，返回 (魁首, 排名表)。"""
    st = world_of(world)
    now = time.time()
    ev = _active(st)
    if ev and now >= float(ev.get("expires_at") or 0):
        settle(ev, now)
        save_world(world, st)
    ev = _latest(st)
    if not ev:
        return None, []
    if ev.get("status") != "settled":
        return None, _rank(ev.get("participants"))
    winner = ev.get("winner")
    return (dict(winner) if isinstance(winner, Mapping) else None), list(ev.get("rankings") or [])


def claim_rewards(world: Mapping, uid: str, name: str) -> tuple[bool, str, dict[str, int], bool]:
    """结算后领取个人奖励：魁首习得兵字秘；余者按进度得残卷 ×3/2/1。"""
    st = world_of(world)
    ev = _latest(st)
    if not ev or ev.get("status") != "settled":
        return False, "兵字秘传承尚未结算。", {}, False
    key = str(uid)
    if key in (ev.get("rewarded") or []):
        return False, "本届兵字秘奖励已经领取。", {}, False
    p = (ev.get("participants") or {}).get(key)
    if not p:
        return False, "你未参与本届兵字秘传承。", {}, False
    winner = ev.get("winner") or {}
    is_winner = str(winner.get("uid")) == key
    items: dict[str, int] = {}
    learns = False
    if is_winner:
        learns = True
        lines = "【兵字秘·魁首】你以【%s】承下完整兵字秘！功法【兵字秘】已入参悟。" % (winner.get("weapon") or "证兵之器")
    else:
        fragments = 3 if p.get("completed_at") else 2 if p.get("found") else 1 if p.get("traced") else 0
        if fragments <= 0:
            ev.setdefault("rewarded", []).append(key)
            save_world(world, st)
            return False, "本届参悟未留下可领取的收获。", {}, False
        items[FRAGMENT] = fragments
        lines = f"【兵字秘】按参悟进度获得 兵字秘残卷 ×{fragments}。"
    ev.setdefault("rewarded", []).append(key)
    save_world(world, st)
    return True, lines, items, learns
