"""每日任务系统（移植原版 apps/meirrenwu + model/dailyTask，纯函数无 IO）。

原版公式（level_id + Physique_id 为炼气+炼体双轨之和；本插件单轨境界，以 realm_index×2 对标）：
- 任务1 消耗灵石 = 任务2 获取灵石 = (任务等级×5 + 境界×2) × 20000
- 任务3 秘境次数 = 任务等级 + 1（宗门秘境不计入）
- 每步奖励 = (任务等级 × 境界×2) × 3000 → 修为/血气/灵石；任务经验 = (任务等级×5 + 境界×2) × 8
- 任务升级经验 = (任务等级×2200 + 1000) × 10 + 2333
- 终极奖励 = 修为/血气/灵石 × (任务等级 × 境界×2 × 8000)；秘境之匙 × 任务等级；抽奖次数（无此系统，跳过）
状态机：w1/w2/w3 ∈ {0 未接, 1 进行中, 2 完成}；renwu ∈ {0 未提交, 1 待领奖, 2 已领奖}。
"""

from __future__ import annotations

import time
from typing import Any

TASK_SPEND, TASK_GAIN, TASK_SECRET = 1, 2, 3  # 任务编号


def date_key(ts: float | None = None) -> str:
    """上海时区日期键，每日任务判定"今天"。"""
    return time.strftime("%Y-%m-%d", time.gmtime((ts if ts is not None else time.time()) + 8 * 3600))


def requirements(level: int, realm: int) -> tuple[int, int, int]:
    """返回 (需消耗灵石, 需获取灵石, 需秘境次数)。"""
    base = max(0, int(level)) * 5 + max(0, int(realm)) * 2
    return base * 20000, base * 20000, max(0, int(level)) + 1


def step_reward(level: int, realm: int) -> int:
    """每步完成奖励（修为/血气/灵石 各一份）。"""
    return max(1, int(level)) * max(1, int(realm)) * 2 * 3000


def step_exp(level: int, realm: int) -> int:
    """每步任务经验。"""
    return (max(0, int(level)) * 5 + max(0, int(realm)) * 2) * 8


def level_up_threshold(level: int) -> int:
    """从当前任务等级升到下一级所需经验。"""
    return (max(1, int(level)) * 2200 + 1000) * 10 + 2333


def final_reward(level: int, realm: int) -> dict[str, int]:
    """全部完成后的终极奖励（对齐原版 getDailyFinalReward）。"""
    return {
        "amount": max(1, int(level)) * max(1, int(realm)) * 2 * 8000,
        "task_exp": (max(0, int(level)) * 5 + max(0, int(realm)) * 2) * 12,
        "keys": max(1, int(level)),
    }


def grant_completion_potential(doc: Any, today: str) -> tuple[int, bool]:
    """发放原版每日任务完成潜力，并用日期凭证保证重复结算幂等。"""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return 0, False
    claims = ext.get("_rewardClaims")
    if not isinstance(claims, dict):
        claims = ext["_rewardClaims"] = {}
    key = f"daily-task:{today}:potential"
    prior = claims.get(key)
    if isinstance(prior, dict):
        try:
            return max(0, int(prior.get("amount", 0) or 0)), False
        except (TypeError, ValueError):
            return 0, False

    legacy = ext.get("legacy_source") if isinstance(ext.get("legacy_source"), dict) else {}
    try:
        secret_level = max(0, int(float(legacy.get("mijinglevel_id", 0) or 0)))
        ancient_level = max(0, int(float(legacy.get("xiangulevel_id", 0) or 0)))
    except (TypeError, ValueError):
        secret_level = ancient_level = 0
    if not secret_level and not ancient_level:
        secret_level = max(0, int(getattr(doc, "realm_index", 0) or 0)) + 1
        try:
            from .xiangu import xg_level_of
            ancient_level = max(0, int(xg_level_of(doc)))
        except Exception:
            ancient_level = 0

    base = max(secret_level, ancient_level) * 10
    try:
        from .mingge import effects_of
        effects = effects_of(doc)
        bonus = float(effects.get("仙道潜力收益", 0) or 0)
        extra = int(float(effects.get("仙道潜力额外", 0) or 0))
    except (TypeError, ValueError):
        bonus, extra = 0.0, 0
    amount = max(0, int(base * max(0.0, 1.0 + bonus)) + extra)
    ext["potential"] = max(0, int(float(ext.get("potential", 0) or 0))) + amount
    claims[key] = {"amount": amount, "claimedAt": time.time()}
    return amount, True


def accept_record(rec: dict[str, Any] | None, uid: str, today: str) -> dict[str, Any]:
    """接取/刷新今日任务（原版 add_renwu + Object.assign 刷新）。"""
    base = rec or {"uid": uid, "level": 1, "exp": 0}
    base.update({
        "w1": 1, "w2": 1, "w3": 1,
        "j1": 0, "j2": 0, "j3": 0,
        "renwu": 0, "date": today, "gained": 0, "spent": 0,
    })
    return base


def is_today(rec: dict[str, Any] | None, today: str) -> bool:
    return bool(rec) and rec.get("date") == today


def all_done(rec: dict[str, Any]) -> bool:
    return rec.get("w1") == 2 and rec.get("w2") == 2 and rec.get("w3") == 2


def settle_submit(rec: dict[str, Any], realm: int) -> tuple[list[str], dict[str, Any], int]:
    """提交结算：判定三任务完成、发步进奖励（数值返回给 handler 落账）、任务经验与升级。

    返回 (消息列表, 新记录, 完成数)。
    """
    rec = dict(rec)
    level = int(rec.get("level", 1))
    # 灵石滚动进度并入任务进度（原版 syncLingshiProgress：取历史最大值）
    rec["j1"] = max(int(rec.get("j1", 0)), int(rec.get("spent", 0)))
    rec["j2"] = max(int(rec.get("j2", 0)), int(rec.get("gained", 0)))
    need_spend, need_gain, need_secret = requirements(level, realm)
    rew = step_reward(level, realm)
    texp = step_exp(level, realm)
    msgs: list[str] = []
    completed = 0
    specs = (
        (1, "消耗灵石", need_spend, rec["j1"]),
        (2, "获取灵石", need_gain, rec["j2"]),
        (3, "秘境探索", need_secret, rec["j3"]),
    )
    for no, _label, need, prog in specs:
        if rec.get(f"w{no}") == 1 and prog >= need:
            rec[f"w{no}"] = 2
            rec[f"j{no}"] = 0
            completed += 1
            rec["exp"] = int(rec.get("exp", 0)) + texp
            msgs.append(
                f"任务{no} 完成！修为 +{rew}，血气 +{rew}，灵石 +{rew}，任务经验 +{texp}"
            )
    if all_done(rec):
        rec["renwu"] = 1
    # 任务等级升级（原版：一次提交最多升一级）
    th = level_up_threshold(level)
    if int(rec.get("exp", 0)) >= th:
        rec["level"] = level + 1
        rec["exp"] = int(rec["exp"]) - th
        msgs.append(f"任务等级提升至 {rec['level']} 级！")
    return msgs, rec, completed


def settle_claim(rec: dict[str, Any]) -> dict[str, Any]:
    rec = dict(rec)
    rec["renwu"] = 2
    return rec


def status_label(no: int, rec: dict[str, Any]) -> str:
    w = rec.get(f"w{no}")
    return {0: "未接取", 1: "进行中", 2: "已完成"}.get(w, "未接取")


def view(rec: dict[str, Any], realm: int) -> dict[str, Any]:
    """构造查看面板数据（出图与纯文本同源）。"""
    level = int(rec.get("level", 1))
    need_spend, need_gain, need_secret = requirements(level, realm)
    tasks = [
        {"no": 1, "name": "散财修行", "desc": "消耗灵石", "need": need_spend,
         "prog": max(int(rec.get("j1", 0)), int(rec.get("spent", 0))), "status": status_label(1, rec)},
        {"no": 2, "name": "聚财修行", "desc": "获取灵石", "need": need_gain,
         "prog": max(int(rec.get("j2", 0)), int(rec.get("gained", 0))), "status": status_label(2, rec)},
        {"no": 3, "name": "秘境历练", "desc": "探索秘境（宗门秘境不计）", "need": need_secret,
         "prog": int(rec.get("j3", 0)), "status": status_label(3, rec)},
    ]
    for t in tasks:
        t["pct"] = min(100.0, t["prog"] / t["need"] * 100) if t["need"] else 100.0
        t["done"] = t["status"] == "已完成"
    state = {0: "进行中（完成后 #提交每日任务）", 1: "已全部完成！#领取每日奖励",
             2: "今日奖励已领取"}.get(int(rec.get("renwu", 0)), "")
    fr = final_reward(level, realm)
    exp = int(rec.get("exp", 0))
    exp_need = level_up_threshold(level)
    # 已完成任务显示满进度（结算时进度已清零）
    for t in tasks:
        if t["done"]:
            t["prog"], t["pct"] = t["need"], 100.0
    return {
        "level": level,
        "exp": exp,
        "exp_need": exp_need,
        "exp_pct": min(100.0, exp / exp_need * 100) if exp_need else 100.0,
        "date": rec.get("date", ""),
        "tasks": tasks,
        "state": state,
        "final": {"amount": fr["amount"], "task_exp": fr["task_exp"], "key_n": fr["keys"]},
    }
