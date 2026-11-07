"""组队迎战帝尊 / 团本深化（W8-D4）——纯函数层，无 IO。

取证（原版 `apps/Battle/tuanben.js` 4354 行 + `apps/TeamBoss/TeamBoss.js` 1160 行）：

- 原版有**两套互不相通**的团本：tuanben（多人同场行动条回合制、24h CD、
  队长 `#结算团本奖励` 发等额随机奖励、帝尊线不计奖励不占 CD）、TeamBoss
  （若陀龙王各自单挑累加 + 竞价分配 + 5 分钟内存 CD）。本批只做前者，
  后者（11 条竞价指令）留 W8-D5。
- 原版活跃 rule 合计 29 条（tuanben 18 + TeamBoss 11），**不是**旧规划写的 32 条；
  其中 3 条跨服（`#发布跨服团本` / `#跨服团本列表` / `#化身跨服加入团本`）本移植不做。
- 原版帝尊战是剧情/位面结算，没有伤害账本、没有 DPS 榜、没有 phase 字段；
  本批按取证补成真实多人回合（复用 `combat.engine.run_raid`），并补上
  伤害榜（借鉴 TeamBoss 的 `GardenRecord`）与战报。
- 原版 CD 文案写「16 小时」，实际 `CD_DURATION = 24*3600*1000`；以 24h 为准。
  九幽魔君不吃 24h CD，改「讨伐令 + 每人自然周 10 次」。

本移植改编（写进《缺失玩法规划-W8》）：

- db 仍 v17：队伍/成员沿用 B7 的 `raid_team` / `raid_member` 两张表，
  帝尊队用 `calamity_state["tuanben"]["emperor_codes"]` 标记，不改表结构。
- 全服单例 `calamity_state["tuanben"]`，玩家档 `ext["tuanben"]`；
  B7 原有的 12h/1h 结算 CD 不改动，24h CD 口径只在帝尊/魔君周常线生效。
- 原版 Boss 属性是 `系数 × Math.floor(rand × 1e11)` 的随机天文数字，
  本移植按全队均攻定标（沿用 B7 `raid.boss_stats` 的模型），避免必败。
- 原版 100 回合 / 5 分钟行动条，本移植 30 回合、按速度降序固定出手序。
- 数值折算：原版魔君每轮每人 4 项各 +1000 万，本移植改 1 万灵石/轮 + 随机奖励。
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .combat import Fighter

EMPEROR = "帝尊"
MOJUN = "九幽魔君"
TOKEN = "魔君讨伐令"

MAX_MEMBERS = 5
EMPEROR_GATE_21 = 16          # 原版 getRealmAuthorityLevel >= 16（大帝权柄）
WEEKLY_LIMIT = 10             # 原版 WEEKLY_LIMIT（自然周，周一 0 点北京时间重置）
BATCH_LIMIT = 999             # 原版 batch > 999 拒绝
CD_DURATION = 24 * 3600       # 原版 CD_DURATION（勿信奖励文案里的 16 小时）
DEFEAT_SLEEP = 2 * 3600       # 原版 EMPEROR_DEFEAT_SLEEP_MS
TEAM_TTL = 24 * 3600
RAID_ROUNDS = 30
PHASE_MULT = 1.3              # 帝尊者字秘·极尽：满血复活且三维 ×1.3
MOJUN_STONES = 10_000         # 原版每轮 1000 万，本移植折算

# 全服单例：键白名单即「落库白名单」，临时视图（如 boss 镜像）不会被 set_world 写入。
DEFAULTS: dict[str, Any] = {
    "enabled": True,                # 系统开关（原版 Xiuxian:Tuanben:System:Status）
    "emperor_codes": [],            # 复用 raid_team 表，但只有列在这里的才是帝尊队
    "awareness": "reclaim",         # reclaim 可挑战 / confront 需遮天位面未毁
    "emperor_defeated": False,      # 帝尊被斩后不可再开（管理员 #复苏帝尊 回滚）
    "defeated_at": 0.0,
    "weekly": {},                   # uid -> {周一日期: 本周已结算轮数}
    "battle_log": [],               # [{code,boss,result,at,rounds,phases,members}]
    "dps": {},                      # code -> [[name, dmg], ...]  原版 tuanben 缺此账本
    "system_log": [],               # 管理员开关/重置留痕（原版无）
    "cd_reset_at": 0.0,             # #重置所有讨伐CD 的时间闸（B7 CD 读此值豁免）
}

STATUS_LABEL = {
    "recruiting": "招募中", "fighting": "讨伐中", "victory": "已讨伐",
    "defeated": "帝尊未斩", "closed": "已解散",
}


# ------------------------------------------------------------------ 全服状态

def world_of(state: Mapping | None) -> dict[str, Any]:
    """从 calamity_state 取团本单例；只保留 DEFAULTS 键并做类型归一化。"""
    raw = (state or {}).get("tuanben")
    w = {k: json.loads(json.dumps(v, ensure_ascii=False)) for k, v in DEFAULTS.items()}
    if not isinstance(raw, dict):
        return w
    for key, default in DEFAULTS.items():
        if key not in raw:
            continue
        val = raw[key]
        if isinstance(default, bool):
            if isinstance(val, bool):
                w[key] = val
        elif isinstance(default, float):
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                w[key] = float(val)
        elif isinstance(default, int):
            if isinstance(val, int) and not isinstance(val, bool):
                w[key] = val
        elif isinstance(default, list):
            if isinstance(val, list):
                w[key] = list(val)[-40:]
        elif isinstance(default, dict):
            if isinstance(val, dict):
                w[key] = dict(val)
        elif isinstance(default, str):
            if isinstance(val, str):
                w[key] = val
    if w["awareness"] not in ("reclaim", "confront"):
        w["awareness"] = "reclaim"
    return w


def set_world(state: dict[str, Any], w: Mapping) -> None:
    """回写：白名单 + 深拷贝序列化，避免把临时视图/可变引用带进 calamity_state。"""
    clean = {k: w.get(k, DEFAULTS[k]) for k in DEFAULTS}
    state["tuanben"] = json.loads(json.dumps(clean, ensure_ascii=False))


def note(w: dict[str, Any], text: str, ts: float) -> None:
    w["system_log"] = (list(w["system_log"]) + [f"[{time.strftime('%m-%d %H:%M', time.gmtime(ts + 8 * 3600))}] {text}"])[-20:]


def week_key(ts: float) -> str:
    """自然周键：北京时间周一 00:00 所在日期（对齐原版 weekKey）。"""
    local = time.gmtime(ts + 8 * 3600)
    monday = ts + 8 * 3600 - int(local.tm_wday) * 86400
    return time.strftime("%Y-%m-%d", time.gmtime(monday))


def weekly_left(w: Mapping, uid: str, ts: float) -> int:
    slot = w.get("weekly", {}).get(str(uid)) or {}
    used = int(slot.get(week_key(ts), 0) or 0)
    return max(0, WEEKLY_LIMIT - used)


def consume_weekly(w: dict[str, Any], uid: str, rounds: int, ts: float) -> int:
    """记账并顺手清掉旧周（惰性，无需 cron）。返回本周已用轮数。"""
    key = week_key(ts)
    slot = {k: int(v) for k, v in (w["weekly"].get(str(uid)) or {}).items() if k == key}
    slot[key] = int(slot.get(key, 0) or 0) + max(0, int(rounds))
    w["weekly"][str(uid)] = slot
    return slot[key]


# ------------------------------------------------------------------ 玩家档

def player_state_of(doc: Any) -> dict[str, Any]:
    raw = (getattr(doc, "ext", None) or {}).get("tuanben")
    s = {"sleep_until": 0.0, "wins": 0, "losses": 0, "zhezi": 0, "last_code": ""}
    if isinstance(raw, dict):
        for k, default in s.items():
            val = raw.get(k)
            if isinstance(default, float) and isinstance(val, (int, float)) and not isinstance(val, bool):
                s[k] = float(val)
            elif isinstance(default, int) and isinstance(val, int) and not isinstance(val, bool):
                s[k] = int(val)
            elif isinstance(default, str) and isinstance(val, str):
                s[k] = val
    return s


def set_player(doc: Any, s: Mapping) -> None:
    doc.ext["tuanben"] = json.loads(json.dumps(dict(s), ensure_ascii=False))


def sleep_left(doc: Any, ts: float) -> float:
    return max(0.0, float(player_state_of(doc).get("sleep_until", 0.0) or 0.0) - float(ts))


def defeat_penalty(doc: Any, s: dict[str, Any], ts: float) -> str:
    """原版 applyEmperorDefeatPenalty：道伤 +5、生命本源/元神/寿元减半、沉眠 2h。

    本移植只接既有 `zhengdao.add_wounds` 的道伤与「沉眠」，不删玩家主档；
    寿元减半改记为团本档里的 `losses` 次数（避免破坏主线寿元经济）。
    """
    s["losses"] = int(s.get("losses", 0) or 0) + 1
    s["sleep_until"] = float(ts) + DEFEAT_SLEEP
    wound = ""
    try:
        from . import zhengdao as _dz
        wound = f"｜道伤 +5（现 {_dz.add_wounds(doc, 5.0, '帝尊战败'):.1f}）"
    except Exception:
        wound = ""
    return f"帝尊未斩：全队道基受损、沉眠 {DEFEAT_SLEEP // 3600} 小时{wound}"


def victory_effect(w: dict[str, Any], s: dict[str, Any], ts: float) -> str:
    s["wins"] = int(s.get("wins", 0) or 0) + 1
    w["emperor_defeated"] = True
    w["defeated_at"] = float(ts)
    note(w, "帝尊被斩，感知归寂", ts)
    return "帝尊伏诛！感知归寂，此后不可再组队迎战（管理员 #复苏帝尊 可回滚）。"


# ------------------------------------------------------------------ 门槛

def emperor_gate(auth21: int) -> bool:
    return int(auth21) >= EMPEROR_GATE_21


def awareness_available(w: Mapping, plane_alive: bool) -> tuple[bool, str]:
    if bool(w.get("emperor_defeated")):
        return False, "帝尊已被斩，感知归寂，诸天再无其影（需管理员 #复苏帝尊）。"
    mode = str(w.get("awareness") or "reclaim")
    if mode == "reclaim":
        return True, ""
    if mode == "confront" and plane_alive:
        return True, ""
    return False, "帝尊感知未至：当前为 confront 态且遮天位面已毁，需管理员切回 reclaim。"


def system_on(w: Mapping) -> tuple[bool, str]:
    return (True, "") if bool(w.get("enabled")) else (False, "团本系统已被管理员关闭（#开启团本系统 恢复）。")


def _sleep_msg(doc: Any, ts: float) -> str:
    left = sleep_left(doc, ts)
    return (f"帝尊战败后沉眠未醒，还需 {int(left // 3600)} 小时 {int(left % 3600 // 60)} 分。"
            if left > 0 else "")


def can_create_emperor(
    doc: Any, w: Mapping, active: bool, auth21: int, plane_alive: bool, ts: float,
) -> tuple[bool, str]:
    ok, msg = system_on(w)
    if not ok:
        return False, msg
    if active:
        return False, "你已在别的讨伐队伍中（#查看队伍信息 / #离开队伍）。"
    if not emperor_gate(auth21):
        return False, f"迎战帝尊需大帝权柄 {EMPEROR_GATE_21} 档（现 {auth21}），道友尚未至。"
    ok, msg = awareness_available(w, plane_alive)
    if not ok:
        return False, msg
    sleep = _sleep_msg(doc, ts)
    if sleep:
        return False, sleep
    return True, ""


def is_emperor_team(w: Mapping, code: str) -> bool:
    return str(code) in [str(c) for c in (w.get("emperor_codes") or [])]


def can_join_emperor(
    doc: Any, w: Mapping, team: Mapping, count: int, active: bool,
    auth21: int, ts: float,
) -> tuple[bool, str]:
    ok, msg = system_on(w)
    if not ok:
        return False, msg
    if not team or not is_emperor_team(w, team.get("code")):
        return False, "没有这支迎战帝尊的队伍（#组队迎战帝尊 新建）。"
    if str(team.get("status")) != "recruiting":
        return False, "该队伍已不在招募阶段。"
    if active:
        return False, "你已在别的讨伐队伍中。"
    if int(count) >= MAX_MEMBERS:
        return False, f"队伍已满（{MAX_MEMBERS}/{MAX_MEMBERS}）。"
    if not emperor_gate(auth21):
        return False, f"迎战帝尊需大帝权柄 {EMPEROR_GATE_21} 档（现 {auth21}）。"
    sleep = _sleep_msg(doc, ts)
    if sleep:
        return False, sleep
    return True, ""


def can_start_emperor(
    doc: Any, w: Mapping, team: Mapping, count: int, auth21: int,
    plane_alive: bool, ts: float, is_leader: bool,
) -> tuple[bool, str]:
    ok, msg = system_on(w)
    if not ok:
        return False, msg
    if not is_leader:
        return False, "只有队长可以发起 #迎战帝尊。"
    if str(team.get("status")) != "recruiting":
        return False, "队伍已发起过讨伐。"
    if int(count) < 1:
        return False, "队伍里还没有人。"
    if not emperor_gate(auth21):
        return False, f"队长需大帝权柄 {EMPEROR_GATE_21} 档。"
    ok, msg = awareness_available(w, plane_alive)
    if not ok:
        return False, msg
    sleep = _sleep_msg(doc, ts)
    if sleep:
        return False, sleep
    return True, ""


# ------------------------------------------------------------------ 战斗装配

def boss_fighter(avg_atk: int, member_count: int, rng: random.Random) -> Fighter:
    """帝尊按全队均攻定标；二阶段者字秘·极尽由 run_raid 消费。"""
    avg = max(1, int(avg_atk or 1))
    n = max(1, min(MAX_MEMBERS, int(member_count or 1)))
    jitter = 0.9 + rng.random() * 0.2
    hp = max(1, int(avg * (4.0 + 3.0 * n) * jitter))
    f = Fighter(
        name=EMPEROR, atk=max(1, int(avg * 1.05 * jitter)),
        defense=max(1, int(avg * 0.42 * jitter)), hp=hp, hp_max=hp, bao=0.35,
        tags={"key": "boss", "speed": 1500, "aoe": True,
              "phase_revive": 1, "phase_mult": PHASE_MULT,
              "phase_name": "者字秘·极尽"},
    )
    # 世界鼎·炼化万道（原版开场 ×1.5）：折算成 1.15，避免 1v5 必败
    f.effects["dmg_dealt_mult"] = 1.15
    return f


def player_fighter(
    uid: str, name: str, atk: int, defense: int, hp: int, hp_max: int,
    bao: float, zhezi: int, speed: int = 100,
) -> Fighter:
    """者字秘次数来自玩家团本档；复活比例对齐原版特殊档 [1, 0.55]。"""
    f = Fighter(
        name=name or uid[:8], atk=max(1, int(atk)), defense=max(1, int(defense)),
        hp=max(1, int(hp)), hp_max=max(1, int(hp_max)), bao=float(bao or 0.0),
        tags={"key": str(uid), "speed": int(speed), "revives": max(0, int(zhezi)),
              "revive_ratio": 0.55 if int(zhezi) > 1 else 1.0},
    )
    return f


def settle_battle(
    w: dict[str, Any], code: str, result: Any, members: Sequence[Mapping],
    ts: float, plane_alive: bool,
) -> str:
    """把 run_raid 结果写进全服单例（战报 + DPS 账本 + 感知状态）。"""
    name_of = {str(m.get("uid")): str(m.get("name") or m.get("uid")) for m in members}
    rows = [[name_of.get(uid, uid), int(dmg)] for uid, dmg in result.damage.items()]
    rows.sort(key=lambda r: -r[1])
    w["dps"][str(code)] = rows
    w["battle_log"] = (list(w["battle_log"]) + [{
        "code": str(code), "boss": EMPEROR,
        "result": "玩家胜利" if result.win else "BOSS胜利",
        "at": float(ts), "rounds": int(result.rounds),
        "phases": list(result.phases), "members": len(members),
        "boss_hp": int(result.boss_hp),
    }])[-20:]
    codes = [str(c) for c in w["emperor_codes"] if str(c) != str(code)]
    w["emperor_codes"] = codes
    if result.win:
        w["emperor_defeated"] = True
        w["defeated_at"] = float(ts)
        note(w, f"队伍 {code} 斩帝尊（{result.rounds} 回合）", ts)
        return "帝尊伏诛，诸天感知归寂。"
    note(w, f"队伍 {code} 迎战帝尊败北（{result.rounds} 回合）", ts)
    return "帝尊未斩，全队道基受损。"


def rank_text(w: Mapping, code: str, limit: int = 20) -> str:
    rows = [list(r) for r in (w.get("dps", {}).get(str(code)) or []) if isinstance(r, (list, tuple))]
    if not rows:
        return "--- 团本伤害榜 ---\n尚无战报。发 #迎战帝尊 打一场，或直接看 #团本战报。"
    total = sum(max(0, int(r[1])) for r in rows) or 1
    lines = [f"--- 团本伤害榜 · 队伍 {code} ---", f"总伤害：{total:,}"]
    for i, (name, dmg) in enumerate(rows[:max(1, int(limit))], 1):
        lines.append(f"{i:>2}. {name}｜{int(dmg):,}｜{int(dmg) * 100 / total:.1f}%")
    return "\n".join(lines)


def log_text(w: Mapping, limit: int = 10) -> str:
    rows = list(w.get("battle_log") or [])[-max(1, int(limit)):]
    if not rows:
        return "--- 团本战报 ---\n尚无讨伐记录。"
    lines = ["--- 团本战报（最近 %d 场）---" % len(rows)]
    for r in reversed(rows):
        at = time.strftime("%m-%d %H:%M", time.gmtime(float(r.get("at", 0) or 0) + 8 * 3600))
        phases = "、".join(r.get("phases") or []) or "无"
        lines.append(
            f"· {at}｜队伍 {r.get('code')}｜{r.get('boss')}｜{r.get('result')}"
            f"｜{r.get('rounds')} 回合｜{r.get('members')} 人｜阶段：{phases}"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ 奖励池

def draw_loot(pool: Sequence[Mapping], rng: random.Random, count: int) -> dict[str, int]:
    """原版 distributeRewards：从奖励表不重复抽 N 组（按索引去重，物品名可重）。"""
    n = max(0, min(int(count), len(pool)))
    if n <= 0:
        return {"秘境之匙": 5}
    picked = rng.sample(range(len(pool)), n)
    out: dict[str, int] = {}
    for i in picked:
        row = pool[i] if isinstance(pool[i], Mapping) else {}
        name = str(row.get("name") or "秘境之匙")
        qty = max(1, int(row.get("数量", 1) or 1))
        out[name] = int(out.get(name, 0)) + qty
    return out


def loot_text(pool: Sequence[Mapping]) -> str:
    lines = [f"--- 团本奖励一览（{len(pool)} 组，原版 1:1）---"]
    for i, row in enumerate(pool[:18], 1):
        lines.append(f"· {row.get('name')} ×{int(row.get('数量', 1) or 1)}"
                     f"（稀有度 {int(row.get('稀有度', 1) or 1)}）")
    if len(pool) > 18:
        lines.append(f"…… 其余 {len(pool) - 18} 组略")
    lines.append("普通团本：仙帝 8 组 / 其它 4 组，每人等额随机、不按贡献。")
    lines.append("帝尊：不计奖励、不占 CD（原版口径）。")
    return "\n".join(lines)


def mojun_settle(
    w: dict[str, Any], uid: str, rounds: int, tokens: int, ts: float,
    pool: Sequence[Mapping], rng: random.Random,
) -> tuple[bool, str, dict[str, Any]]:
    """`#结算魔君奖励*N`：令牌数 × 本周剩余额度取小；返回 (ok,msg,delta)。

    原版按队长剩余额度给全队结算；本移植改为「谁结算谁领」，避免替他人
    扣令牌 / 写他人档（沿用 D2 的惰性结算 + 单玩家落库模式）。
    """
    ok, msg = system_on(w)
    if not ok:
        return False, msg, {}
    n = int(rounds)
    if n <= 0 or n > BATCH_LIMIT:
        return False, f"轮数需在 1~{BATCH_LIMIT} 之间（原版 batch > 999 拒绝）。", {}
    free = weekly_left(w, uid, ts)
    if free <= 0:
        return False, f"本周 {WEEKLY_LIMIT} 次额度已用尽，下周一（北京时间 0 点）重置。", {}
    if int(tokens) <= 0:
        return False, f"没有【{TOKEN}】，无法结算魔君奖励。", {}
    real = min(n, free, int(tokens))
    items: dict[str, int] = {}
    for _ in range(real):
        for name, qty in draw_loot(pool, rng, 5).items():
            items[name] = int(items.get(name, 0)) + int(qty)
    consume_weekly(w, uid, real, ts)
    used = WEEKLY_LIMIT - weekly_left(w, uid, ts)
    note(w, f"{uid} 结算魔君奖励 ×{real}", ts)
    msg = (f"结算 {real} 轮（请求 {n}｜本周余 {free}｜令牌 {tokens}）："
           f"灵石 +{MOJUN_STONES * real:,}，物品 {sum(items.values()):,} 件，"
           f"消耗【{TOKEN}】×{real}。本周已用 {used}/{WEEKLY_LIMIT}。")
    return True, msg, {
        "stones": MOJUN_STONES * real, "items": items,
        "tokens": real, "rounds": real,
    }


# ------------------------------------------------------------------ 管理员

def system_switch(w: dict[str, Any], on: bool, ts: float) -> str:
    w["enabled"] = bool(on)
    note(w, "开启团本系统" if on else "关闭团本系统", ts)
    return "团本系统已开启。" if on else "团本系统已关闭（既有队伍仍可 #查看队伍信息）。"


def reset_cd(w: dict[str, Any], ts: float) -> str:
    """原版删全部 PlayerCD:*；本移植 CD 在玩家 ext，改用全服时间闸豁免。"""
    w["cd_reset_at"] = float(ts)
    note(w, "重置所有讨伐 CD", ts)
    return f"所有讨伐 CD 已重置（时间闸 {time.strftime('%m-%d %H:%M', time.gmtime(ts + 8 * 3600))}）。"


def shutdown(w: dict[str, Any], ts: float) -> str:
    """原版清队伍/关联/Boss 缓存；本移植清帝尊队标记 + DB 里招募中队伍由接线关闭。"""
    n = len(w["emperor_codes"])
    w["emperor_codes"] = []
    note(w, f"关闭所有讨伐（清 {n} 支帝尊队标记）", ts)
    return f"已清除 {n} 支帝尊队标记；接线层会关闭全部招募中 / 讨伐中的队伍。"


def awareness_switch(w: dict[str, Any], mode: str, ts: float) -> str:
    mode = "confront" if str(mode).strip() in ("confront", "对抗", "对峙") else "reclaim"
    w["awareness"] = mode
    note(w, f"帝尊感知切至 {mode}", ts)
    return (f"帝尊感知：{mode}。"
            + ("confront 下需遮天位面未毁方可挑战。" if mode == "confront" else "reclaim 下可直接组队迎战。"))


def revive_emperor(w: dict[str, Any], ts: float) -> str:
    if not w["emperor_defeated"]:
        return "帝尊仍在世，无需复苏。"
    w["emperor_defeated"] = False
    w["defeated_at"] = 0.0
    w["awareness"] = "reclaim"
    note(w, "复苏帝尊（回滚永久击杀）", ts)
    return "帝尊复苏，感知重开（emperor_defeated / defeated_at / awareness 三处同清）。"


# ------------------------------------------------------------------ 文本

def status_text(
    w: Mapping, doc: Any, auth21: int, plane_alive: bool, ts: float,
    team: Mapping | None, last_code: str,
) -> str:
    s = player_state_of(doc)
    ok, why = awareness_available(w, plane_alive)
    lines = [
        "--- 帝尊状态 ---",
        f"团本系统：{'开启' if w.get('enabled') else '关闭'}｜感知：{w.get('awareness')}"
        f"｜遮天位面：{'存' if plane_alive else '毁'}",
        f"可迎战：{'是' if ok else '否'}" + ("" if ok else f"（{why}）"),
        f"你的权柄：{auth21}/{EMPEROR_GATE_21}（大帝门槛）｜胜 {s['wins']} / 败 {s['losses']}",
    ]
    left = sleep_left(doc, ts)
    lines.append(f"沉眠：{'清醒' if left <= 0 else f'还剩 {int(left // 3600)} 小时 {int(left % 3600 // 60)} 分'}")
    lines.append(f"魔君本周额度：{weekly_left(w, getattr(doc, 'uid', ''), ts)}/{WEEKLY_LIMIT}"
                 f"（周键 {week_key(ts)}）")
    if team:
        lines.append(f"当前队伍：{team.get('code')}｜{STATUS_LABEL.get(str(team.get('status')), team.get('status'))}"
                     f"｜{team.get('boss')}")
    if last_code:
        lines.append(f"最近战报队伍码：{last_code}（#团本伤害榜 队伍码）")
    return "\n".join(lines)


def system_text(w: Mapping) -> str:
    lines = [
        "--- 团本系统状态 ---",
        f"开关：{'开启' if w.get('enabled') else '关闭'}｜感知：{w.get('awareness')}",
        f"帝尊被斩：{'是' if w.get('emperor_defeated') else '否'}｜帝尊队标记：{len(w.get('emperor_codes') or [])}",
        f"战报 {len(w.get('battle_log') or [])} 场｜DPS 榜 {len(w.get('dps') or {})} 队｜周额度记录 {len(w.get('weekly') or {})} 人",
        f"最近留痕：{' / '.join(list(w.get('system_log') or [])[-3:]) or '无'}",
    ]
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 迎战帝尊规则（原版取证口径）---",
        f"· 门槛：大帝权柄 {EMPEROR_GATE_21} 档；感知 reclaim 可直接开，confront 需遮天位面未毁。",
        f"· 队伍上限 {MAX_MEMBERS} 人、下限 1 人；队伍码 6 位数字，{TEAM_TTL // 3600}h 逾期自动解散。",
        "· 帝尊线：不计奖励、不占 24h CD；败则道伤 +5 并沉眠 2h，胜则帝尊感知归寂（唯一回滚 #复苏帝尊）。",
        f"· 战斗：真实多人回合（速度降序出手、Boss 按仇恨点名、每 5 回合群体秘术），上限 {RAID_ROUNDS} 回合。",
        f"· 二阶段：者字秘·极尽，Boss 首次被打空时满血复活且三维 ×{PHASE_MULT:g}。",
        "· 者字秘：玩家致死复活，次数取团本档 zhezi（2 次时第二次仅回 55%）。",
        "· 伤害榜：原版 tuanben 不落伤害账本，本移植补 DPS 账本 + 战报（借鉴 TeamBoss 的 GardenRecord）。",
        f"· 普通讨伐 CD 24h（原版奖励文案误写 16h）；{MOJUN} 不吃 24h，改令牌 + 自然周 {WEEKLY_LIMIT} 次。",
        f"· 魔君批量结算：#结算魔君奖励*N（# 可省，N ≤ {BATCH_LIMIT}），每轮 {MOJUN_STONES:,} 灵石 + 5 组奖励。",
        "· 不做：跨服三指令（#发布跨服团本 / #跨服团本列表 / #化身跨服加入团本）。",
        "· 不做：若陀龙王竞价团（TeamBoss 11 条）→ W8-D5；两套状态模型不兼容，勿混用。",
        "· 原版死链不搬：KilledTime / Reward / Boss_time / list_num / now_time / over_time / checkDateUpdate。",
    ])


def help_text() -> str:
    return "\n".join([
        "--- 组队迎战帝尊 · 指令一览 ---",
        "#迎战帝尊帮助 / #迎战帝尊规则　本页 / 完整口径",
        "#组队迎战帝尊　建帝尊队（权柄 16 档、感知可用、无沉眠）",
        "#加入迎战帝尊 队伍码　入队（5 人上限）",
        "#迎战帝尊　队长开战：多人回合 + 伤害榜 + 战报",
        "#离开队伍 / #解散队伍　退队 / 队长解散（普通队与帝尊队通用）",
        "#查看队伍信息 / #团本列表　复用 B7 队伍面板",
        "#帝尊状态 / #团本系统状态　个人门槛沉眠 / 全服开关",
        "#团本伤害榜 [队伍码] / #团本战报　DPS 与最近 10 场",
        "#魔君周常 / #结算魔君奖励*N　周额度 / 批量结算（N ≤ 999）",
        "#团本奖励一览　41 组原版奖励池",
        "管理员：#开启团本系统 / #关闭团本系统 / #重置所有讨伐CD / #关闭所有讨伐",
        "管理员：#帝尊感知 reclaim|confront / #复苏帝尊（回滚永久击杀）",
        "⚠️ 帝尊线无奖励、无 24h CD；普通团本仍走 #创建讨伐队伍 / #讨伐出手 / #结算团本奖励。",
    ])
