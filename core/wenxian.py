"""问仙令通行证（对齐原版 model/wenxianling.js + apps/WenXianLing.js，MVP 版）。

- 线索激活制：求取线索（300 万灵石，原版 30 亿 ÷1000）→ 探索线索（3 步）→ 激活
- 通行证：1000 exp/级、上限 60 级；升级奖修为 800 万×1.12^level×波动
- 每日任务（每项 500 exp，每日重置）：闭关 1 次 / 讨伐 1 次 / 炼丹 1 次
  （原版 spiritHeart 30 / tianjiao 1 / dungeon 3 → 按本插件动作映射，标注偏差）
- 问仙试炼：持有线索后完成 7 日每日任务、开辟内景地、击败天骄、探索最终线索
- 每周任务（3000 exp）：问仙令日常 3 天 / 每日修行任务 5 次 / 讨伐 3 次 / 炼丹 5 次
  （原版 spiritHeart / tianjiao / stoneMarket / dungeon 周目标仍按现有模块简化）
- 5 级节点大奖：仙道潜力 + 丹药
"""

from __future__ import annotations
from .clock import day_key

import copy
import math
import time
from typing import Any, Mapping

EXP_PER_LEVEL = 1000
MAX_LEVEL = 60
CLUE_COST = 3_000_000
CLUE_STEPS = 3
MIN_REALM = 5

DAILY_EXP = 500
WEEKLY_EXP = 3000
TRIAL_DAILY_TASK_TARGET = 7
DAILY_GOALS = {"seclusion": 1, "raid": 1, "alchemy": 1}
WEEKLY_GOALS = {"daily": 3, "daily_task": 5, "raid": 3, "alchemy": 5}

DAILY_LABELS = {"seclusion": "闭关出关", "raid": "讨伐/战斗", "alchemy": "炼丹/打造"}
WEEKLY_LABELS = {"daily": "领取问仙令每日任务(天)", "daily_task": "完成每日修行任务",
                 "raid": "讨伐/战斗", "alchemy": "炼丹/打造"}

BONUS_REWARDS = {
    5: {"name": "初入仙途", "potential": 20},
    10: {"name": "洗髓铸骨", "potential": 25},
    20: {"name": "道种感悟", "potential": 30},
    30: {"name": "九转玲珑", "potential": 50},
    40: {"name": "先天元灵", "potential": 60},
    50: {"name": "万法归宗", "potential": 80},
}


def _date_key(ts: float) -> str:
    return day_key(ts)


def _week_key(ts: float) -> str:
    t = time.gmtime(ts + 8 * 3600)
    monday_offset = (t.tm_wday) % 7  # tm_wday: 周一=0
    monday = ts - monday_offset * 86400
    return _date_key(monday)


def system_of(doc: Mapping) -> dict:
    w = doc.ext.get("wenxian") if isinstance(doc.ext, Mapping) else None
    w = copy.deepcopy(w) if isinstance(w, dict) else {}
    w.setdefault("active", False)
    w.setdefault("clue", False)
    w.setdefault("step", 0)
    w.setdefault("level", 0)
    w.setdefault("exp", 0)
    w.setdefault("claimed", [])
    w.setdefault("daily", {})
    w.setdefault("weekly", {})
    raw_trial = w.get("trial") if isinstance(w.get("trial"), dict) else {}
    w["trial"] = {
        "dailyTasks": min(TRIAL_DAILY_TASK_TARGET, max(0, int(raw_trial.get("dailyTasks", 0) or 0))),
        "lastDailyTaskDate": str(raw_trial.get("lastDailyTaskDate") or ""),
        "innerWorldOpened": bool(raw_trial.get("innerWorldOpened")),
        "tianjiaoDefeated": bool(raw_trial.get("tianjiaoDefeated")),
        "clueExplored": bool(raw_trial.get("clueExplored")),
    }
    return w


def daily_of(w: dict, now: float) -> dict:
    day = _date_key(now)
    d = w.get("daily") if isinstance(w.get("daily"), dict) else {}
    if d.get("date") != day:
        d = {"date": day, "prog": {k: 0 for k in DAILY_GOALS}, "claimed": []}
    d.setdefault("prog", {k: 0 for k in DAILY_GOALS})
    d.setdefault("claimed", [])
    w["daily"] = d
    return d


def weekly_of(w: dict, now: float) -> dict:
    wk = _week_key(now)
    d = w.get("weekly") if isinstance(w.get("weekly"), dict) else {}
    if d.get("week") != wk:
        d = {"week": wk, "prog": {k: 0 for k in WEEKLY_GOALS}, "claimed": False}
    d.setdefault("prog", {k: 0 for k in WEEKLY_GOALS})
    for key, goal in WEEKLY_GOALS.items():
        d["prog"][key] = min(goal, max(0, int(d["prog"].get(key, 0) or 0)))
    w["weekly"] = d
    return d


def trial_complete(w: Mapping) -> bool:
    trial = w.get("trial") if isinstance(w.get("trial"), Mapping) else {}
    return bool(
        w.get("clue")
        and int(trial.get("dailyTasks", 0) or 0) >= TRIAL_DAILY_TASK_TARGET
        and trial.get("innerWorldOpened")
        and trial.get("tianjiaoDefeated")
        and trial.get("clueExplored")
    )


def record_trial(w: dict, kind: str, now: float) -> dict:
    """Record one source trial mark while the clue is held and the pass is locked."""
    trial = w["trial"]
    if not w.get("clue") or w.get("active"):
        return {"changed": False, "trial": trial, "ready": trial_complete(w)}
    changed = False
    if kind == "daily":
        today = _date_key(now)
        if (trial["lastDailyTaskDate"] != today
                and trial["dailyTasks"] < TRIAL_DAILY_TASK_TARGET):
            trial["lastDailyTaskDate"] = today
            trial["dailyTasks"] += 1
            changed = True
    elif kind == "inner-world" and not trial["innerWorldOpened"]:
        trial["innerWorldOpened"] = True
        changed = True
    elif kind == "tianjiao" and not trial["tianjiaoDefeated"]:
        trial["tianjiaoDefeated"] = True
        changed = True
    elif kind == "explore" and not trial["clueExplored"]:
        trial["clueExplored"] = True
        changed = True
    return {"changed": changed, "trial": trial, "ready": trial_complete(w)}


def record_daily_task_completion(w: dict, now: float) -> dict:
    """Record a completed daily quest for both the seven-day trial and weekly goal."""
    trial_result = record_trial(w, "daily", now)
    week = weekly_of(w, now)
    before = int(week["prog"].get("daily_task", 0) or 0)
    week["prog"]["daily_task"] = min(WEEKLY_GOALS["daily_task"], before + 1)
    return {**trial_result, "weeklyDailyTask": week["prog"]["daily_task"]}


def track(w: dict, kind: str, n: int = 1, now: float | None = None) -> None:
    """任务进度埋桩（闭关/讨伐/炼丹）。"""
    now = now or time.time()
    d = daily_of(w, now)
    if kind in d["prog"]:
        d["prog"][kind] = min(DAILY_GOALS[kind], int(d["prog"][kind]) + n)
    wk = weekly_of(w, now)
    if kind in wk["prog"]:
        wk["prog"][kind] = min(WEEKLY_GOALS[kind], int(wk["prog"][kind]) + n)


def buy_clue(w: dict, stones: int) -> tuple[bool, str, dict]:
    if w.get("active"):
        return False, "问仙令已激活，无需求取线索。", w
    if w.get("clue"):
        return False, "你已有问仙线索（#探索问仙线索）。", w
    if stones < CLUE_COST:
        return False, f"求取线索需 {CLUE_COST:,} 灵石（当前 {stones:,}）。", w
    w["clue"] = True
    w["step"] = 0
    return True, (f"你重金求取，一位老者在雨夜留下一卷残图——问仙线索入手！\n"
                  f"（消耗灵石 {CLUE_COST:,}；#探索问仙线索 循迹 {CLUE_STEPS} 处）"), w


def explore_clue(w: dict) -> tuple[bool, str, dict]:
    if w.get("active"):
        return False, "问仙令已激活，无需再探索。", w
    if not w.get("clue"):
        return False, "尚无问仙线索（#重金求取问仙线索 或秘境机缘）。", w
    step = int(w.get("step", 0))
    places = ("断崖古字", "荒村残碑", "云海仙门")
    if step < CLUE_STEPS:
        w["step"] = step + 1
        trial_result = record_trial(w, "explore", time.time()) if w["step"] == CLUE_STEPS else None
        suffix = ""
        if trial_result and trial_result["ready"]:
            suffix = "全部问仙试炼已完成，可发送 #激活问仙令。"
        return True, (f"循迹第 {step + 1}/{CLUE_STEPS} 处：你抵达【{places[step]}】，"
                      + ("线索指向更深处的迷雾……" if step + 1 < CLUE_STEPS
                         else "残图拼合完整。" + suffix)), w
    return False, "线索已探索完毕（#激活问仙令）。", w


def activate(w: dict, realm_index: int) -> tuple[bool, str, dict]:
    if w.get("active"):
        return False, "问仙令已经激活。", w
    if realm_index < MIN_REALM:
        return False, f"境界不足：需 {MIN_REALM} 境起。", w
    if not w.get("clue"):
        return False, "尚未获得问仙线索（#重金求取问仙线索）。", w
    if int(w.get("step", 0)) < CLUE_STEPS:
        return False, f"线索尚未探索完整（{w.get('step', 0)}/{CLUE_STEPS}，#探索问仙线索）。", w
    if not trial_complete(w):
        t = w["trial"]
        lines = ["问仙试炼未完成：",
                 f"· 每日任务 {t['dailyTasks']}/{TRIAL_DAILY_TASK_TARGET}",
                 f"· 开辟内景地：{'已完成' if t['innerWorldOpened'] else '未完成'}",
                 f"· 击败位面天骄：{'已完成' if t['tianjiaoDefeated'] else '未完成'}",
                 f"· 探索最终线索：{'已完成' if t['clueExplored'] else '未完成'}"]
        return False, "\n".join(lines), w
    w["active"] = True
    w["level"] = max(1, int(w.get("level", 0)))
    return True, (f"问仙令归位！当前等级 {w['level']}。\n"
                  "每日任务每项首次完成 +500 经验（#问仙令任务），升级后 #领取问仙令 级 领奖。"), w


def add_exp(w: dict, amount: int) -> tuple[int, int]:
    """加经验并结算升级。返回 (新等级, 新经验)。"""
    lv = int(w.get("level", 1))
    exp = int(w.get("exp", 0)) + max(0, int(amount))
    while exp >= EXP_PER_LEVEL and lv < MAX_LEVEL:
        exp -= EXP_PER_LEVEL
        lv += 1
    if lv >= MAX_LEVEL:
        exp = min(exp, EXP_PER_LEVEL - 1)
    w["level"] = lv
    w["exp"] = exp
    return lv, exp


def level_reward(level: int) -> dict:
    """原版升级奖：修为 800 万×1.12^level×确定性波动（s1 公式直译）。"""
    mult = 1 + int(level) * 0.12
    s1 = ((int(level) * 17 + 31) % 13) / 26 + 0.75
    return {
        "exp_gain": int(8_000_000 * mult * s1),
        "xueqi": int(4_000_000 * mult * (((int(level) * 23 + 47) % 13) / 26 + 0.75)),
        "stones": int(15_000_000 * mult * (((int(level) * 29 + 59) % 13) / 26 + 0.75)),
        "potential": BONUS_REWARDS.get(int(level), {}).get("potential", 0),
    }


def claim_level(w: dict, level: int) -> tuple[bool, str, dict, dict]:
    if not w.get("active"):
        return False, "问仙令未激活。", w, {}
    cur = int(w.get("level", 0))
    if level < 1 or level > cur:
        return False, f"只能领取已达到的等级（当前 {cur} 级）。", w, {}
    claimed = set(int(x) for x in (w.get("claimed") or []))
    if level in claimed:
        return False, f"{level} 级奖励已领取。", w, {}
    claimed.add(level)
    w["claimed"] = sorted(claimed)
    r = level_reward(level)
    bonus = BONUS_REWARDS.get(level)
    tail = f"，额外「{bonus['name']}」仙道潜力 +{bonus['potential']}" if bonus else ""
    return True, (f"领取 {level} 级问仙令奖励：修为 +{r['exp_gain']:,}、血气 +{r['xueqi']:,}、"
                  f"灵石 +{r['stones']:,}{tail}"), w, r


def claim_daily(w: dict, key: str, now: float) -> tuple[bool, str, dict]:
    if not w.get("active"):
        return False, "问仙令未激活。", w
    d = daily_of(w, now)
    if key not in DAILY_GOALS:
        return False, "未知任务。", w
    if key in (d.get("claimed") or []):
        return False, f"「{DAILY_LABELS[key]}」今日已领。", w
    if int(d["prog"].get(key, 0)) < DAILY_GOALS[key]:
        return False, f"「{DAILY_LABELS[key]}」未完成（{d['prog'].get(key, 0)}/{DAILY_GOALS[key]}）。", w
    d["claimed"] = list(d.get("claimed") or []) + [key]
    # 每周任务「完成每日任务天数」：每天首次领每日任务时 +1
    if not d.get("counted"):
        wk = weekly_of(w, now)
        wk["prog"]["daily"] = min(WEEKLY_GOALS["daily"], int(wk["prog"].get("daily", 0)) + 1)
        d["counted"] = True
    lv, exp = add_exp(w, DAILY_EXP)
    return True, f"每日任务「{DAILY_LABELS[key]}」完成，问仙令经验 +{DAILY_EXP}（{lv} 级 {exp}/1000）。", w


def claim_weekly(w: dict, now: float) -> tuple[bool, str, dict]:
    if not w.get("active"):
        return False, "问仙令未激活。", w
    wk = weekly_of(w, now)
    if wk.get("claimed"):
        return False, "本周奖励已领取。", w
    lack = [f"{WEEKLY_LABELS[k]}({wk['prog'].get(k, 0)}/{v})" for k, v in WEEKLY_GOALS.items()
            if int(wk["prog"].get(k, 0)) < v]
    if lack:
        return False, "周任务未完成：\n· " + "\n· ".join(lack), w
    wk["claimed"] = True
    lv, exp = add_exp(w, WEEKLY_EXP)
    return True, f"周任务全部完成，问仙令经验 +{WEEKLY_EXP}（当前 {lv} 级 {exp}/1000）。", w


def panel(w: dict, now: float) -> str:
    if not w.get("active"):
        state = "已获线索（#探索问仙线索）" if w.get("clue") else "未获线索（#重金求取问仙线索）"
        lines = ["--- 问仙令 · 未激活 ---", f"状态：{state}"]
        if w.get("clue"):
            t = w["trial"]
            lines += ["【问仙试炼】",
                      f"· 每日任务：{t['dailyTasks']}/{TRIAL_DAILY_TASK_TARGET}",
                      f"· 开辟内景地：{'已完成' if t['innerWorldOpened'] else '未完成'}",
                      f"· 击败位面天骄：{'已完成' if t['tianjiaoDefeated'] else '未完成'}",
                      f"· 探索最终线索：{'已完成' if t['clueExplored'] else '未完成'}"]
            lines.append("全部完成后发送 #激活问仙令。" if trial_complete(w)
                         else "完成全部试炼后方可激活问仙令。")
        else:
            lines.append(f"流程：求取线索 → 探索 {CLUE_STEPS} 处 → 完成试炼 → #激活问仙令")
        return "\n".join(lines)
    d = daily_of(w, now)
    wk = weekly_of(w, now)
    daily_lines = "\n".join(
        f"· {DAILY_LABELS[k]}：{d['prog'].get(k, 0)}/{v}"
        + ("（已领）" if k in (d.get("claimed") or []) else "")
        for k, v in DAILY_GOALS.items()
    )
    weekly_lines = "\n".join(
        f"· {WEEKLY_LABELS[k]}：{wk['prog'].get(k, 0)}/{v}" for k, v in WEEKLY_GOALS.items()
    )
    claimed = len(w.get("claimed") or [])
    return (
        f"--- 问仙令 · {w['level']} 级 ---\n"
        f"经验：{w['exp']}/{EXP_PER_LEVEL}｜上限 {MAX_LEVEL} 级｜已领奖励 {claimed} 档\n"
        f"【每日任务（每项 {DAILY_EXP} 经验）】\n{daily_lines}\n"
        f"【每周任务（{WEEKLY_EXP} 经验）】\n{weekly_lines}"
        + ("（已领）" if wk.get("claimed") else "")
        + f"\n#领取问仙令 级 领升级奖｜#问仙令任务 领每日｜#领取每周任务"
    )
