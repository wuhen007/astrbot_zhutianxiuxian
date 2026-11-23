"""W8-D5 若陀龙王竞价团（纯函数，无 IO）。

取证（原版 `apps/TeamBoss/TeamBoss.js` 1159 行）：
- 与 `apps/Battle/tuanben.js` 是**两套互不相通**的团本（29 条活跃 rule = 18 + 11）。
  本模块只做后者 11 条；前者已在 W8-D4 `core/tuanben.py` 落地，勿混用状态。
- 原版状态三处：`resources/data/Exchange/Boss_list.json`（文件）、Redis
  `Xiuxian:GardenBossPlayer|GardenBossStatus|GardenRecord|GardenBossExit<id>`、
  进程内存数组 `WorldBOSSBattleCD`（重启即失效）。本移植统一挂
  `calamity_state["dragon"]` 单例 + 玩家 `ext["dragon"]`，**db 仍 v17**。
- 11 条活跃 rule（`#` 必需、无 alias）：状态 / 龙王榜 / 讨伐 / 加入.* /
  奖励 / 出价.* / 分配.* / 团本 / 退出 / 开启(master) / 关闭(master)。
  另 6 条药园残留 rule 被注释且 fnc 全部缺失 → 双重死链，不搬。

关键纠偏（勿再信旧稿）：
- 掉落池是 `data/item/GroupBoss.json` 的 `one` 36 条，**不是** `团本奖励列表.json`；
  5 件掉落在**建团时**抽定（不是击杀时），起拍价 = `floor(出售价)`。
- Boss 血条 = `平均攻击(境界≥30) × 10 × max(达标人数,5) × 5`；
  胜负折算 = `hp_max×0.25/0.05 + Harm(攻击×0.85, 幻影防御)×6/4`；
  幻影**镜像玩家三维**（各 ×0.8~1.4），走 1v1 而非多人回合。
- 竞价加价 ≥30%，填 1 / 0 / 非法 / 缺价一律自动取最低合规价；
  分配时中标者扣 `last_price`，全队平分 `floor(last_price / 当前成员数)`；
  终结者另得【起死回生丹】×5。战斗 CD 300 秒。
- 原版 `GardenBossExit` **只 set 不 del**（退过一次永久不能再退）、
  击杀后 5 件分完即 del 玩家/记录 key、战斗锁整段注释、CD 只在击杀时写：
  均为缺陷，本移植分别改为「按团本记一次机会 / 保留归档 / 每次出手写 CD」。
- 帮助 yaml 里 `#退出若陀龙王团本$` 的 `$` 是正则锚点误抄；
  `#加入讨伐若陀龙王(1,2,3)` 实际只取第一个数字；`(编号)*(价格)` 的 `*` 是字面分隔符。
- 类名 TeamBoss 却 `name:'Yunzai_Bot_Garden'` / `dsc:'药园模块'`、`Garden*` Redis 前缀
  都是复制残留，与 `apps/Garden/*` 无共享；**不是目录孤儿**（apps 全量扫描会注册）。
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from . import battle
from .combat import Fighter, run_1v1

WORLD_KEY = "dragon"
PLAYER_KEY = "dragon"
BOSS_NAME = "若陀龙王"
PHANTOM = "若陀龙王幻影"

MAX_MEMBERS = 5                 # 原版 Boss_item.length < 5
LOOT_COUNT = 5                  # 原版建团时 for(i<5) RandomGood()
BATTLE_CD = 300.0               # 原版 300000 ms，进程内存；本移植落 ext 持久化
HP_ATK_MULT = 10                # GetAverageDamage: 平均攻击 × 10
HP_PEOPLE_MULT = 5
HP_MIN_PEOPLE = 5               # if (player_quantity < 5) player_quantity = 5
HP_STAT_GATE = 30               # 原版统计样本 level_id >= 30

WIN_FIXED = 0.25
LOSE_FIXED = 0.05
WIN_HARM_MULT = 6
LOSE_HARM_MULT = 4
HEAL_CHANCE = 0.05              # random < 0.05 且玩家胜 → 回 hp_max 的 50%
HEAL_RATIO = 0.5
EXTRA_CHANCE = 0.05             # random > 0.95 且玩家负 → 额外 15% + 满血
EXTRA_RATIO = 0.15
HP_GATE_RATIO = 0.10            # 当前血量 <= 上限 10% → 体力不支
REALM_GATE = 42                 # 原版 level_id >= 42（或轮回过）
AUTH21_GATE = 10                # 移植版与 tuanben 普通队口径对齐的第三选一
MIN_RAISE_NUM = 13              # ceil(price × 1.3)，整数算避免浮点坑
MIN_RAISE_DEN = 10
TERMINATOR_ITEM = "起死回生丹"
TERMINATOR_QTY = 5
RANK_LIMIT = 20

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "next_id": 1,
    "bosses": {},               # str(boss_id) -> team
    "system_log": [],
}

_PLAYER_DEFAULTS: dict[str, Any] = {
    "cd_until": 0.0,
    "exit_ids": [],             # 已用掉退团机会的团本 id
    "battles": 0,
    "kills": 0,
    "last_id": 0,
}


# ------------------------------------------------------------------ 状态单例

def world_of(state: Mapping | None) -> dict[str, Any]:
    """从 calamity_state 取龙王单例；白名单 + 深拷贝，老档缺键自动补默认值。"""
    w = {k: json.loads(json.dumps(v, ensure_ascii=False)) for k, v in DEFAULTS.items()}
    raw = (state or {}).get(WORLD_KEY)
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
                w[key] = int(val)
        elif isinstance(default, list):
            if isinstance(val, list):
                w[key] = list(val)[-20:]
        elif isinstance(default, dict):
            if isinstance(val, dict):
                w[key] = json.loads(json.dumps(val, ensure_ascii=False))
    # 团本对象逐字段归一化，避免旧档/临时视图带进脏类型
    clean: dict[str, Any] = {}
    for key, team in w["bosses"].items():
        if isinstance(team, dict):
            clean[str(key)] = team
    w["bosses"] = clean
    return w


def set_world(state: dict[str, Any], w: Mapping) -> None:
    """回写：白名单 + 深拷贝序列化，避免把可变引用带进 calamity_state。"""
    clean = {k: w.get(k, DEFAULTS[k]) for k in DEFAULTS}
    state[WORLD_KEY] = json.loads(json.dumps(clean, ensure_ascii=False))


def note(w: dict[str, Any], text: str, ts: float) -> None:
    stamp = time.strftime("%m-%d %H:%M", time.gmtime(ts + 8 * 3600))
    w["system_log"] = (list(w["system_log"]) + [f"[{stamp}] {text}"])[-20:]


def player_state_of(doc: Any) -> dict[str, Any]:
    s = dict(_PLAYER_DEFAULTS)
    s["exit_ids"] = []
    raw = (getattr(doc, "ext", None) or {}).get(PLAYER_KEY)
    if isinstance(raw, dict):
        for k, default in _PLAYER_DEFAULTS.items():
            val = raw.get(k)
            if isinstance(default, float) and isinstance(val, (int, float)) and not isinstance(val, bool):
                s[k] = float(val)
            elif isinstance(default, int) and isinstance(val, int) and not isinstance(val, bool):
                s[k] = int(val)
            elif isinstance(default, list) and isinstance(val, list):
                s[k] = [str(x) for x in val][-30:]
    return s


def set_player(doc: Any, s: Mapping) -> None:
    doc.ext[PLAYER_KEY] = json.loads(json.dumps(dict(s), ensure_ascii=False))


def cd_left(doc: Any, ts: float) -> float:
    return max(0.0, float(player_state_of(doc).get("cd_until", 0.0) or 0.0) - float(ts))


def system_on(w: Mapping) -> tuple[bool, str]:
    return (True, "") if bool(w.get("enabled")) else (
        False, "若陀龙王团本已被管理员关闭（#开启若陀龙王 重新苏醒）。")


def gate(doc: Any, auth21: int) -> tuple[bool, str]:
    """原版 `level_id < 42 && lunhui == 0` 拦截；移植版补权柄 ≥10 三选一，避免门槛过高。"""
    level = int(getattr(doc, "realm_index", 0) or 0) + 1
    lunhui = int((getattr(doc, "ext", None) or {}).get("lunhui", 0) or 0)
    if level >= REALM_GATE or lunhui > 0 or int(auth21) >= AUTH21_GATE:
        return True, ""
    return False, (f"仙界之人才可直面若陀龙王：需境界 {REALM_GATE} 境 / 轮回 / "
                   f"权柄 {AUTH21_GATE} 档之一（现 {level} 境、权柄 {auth21}）。")


def min_bid(price: int) -> int:
    """ceil(price × 1.3)：整数算，避免 `ceil(100*1.3)=131` 类浮点边界偏差。"""
    return (max(1, int(price)) * MIN_RAISE_NUM + MIN_RAISE_DEN - 1) // MIN_RAISE_DEN


def boss_hp(avg_atk: int, sample_count: int) -> int:
    """原版 Health = trunc(AverageDamage × player_quantity × 5)，AverageDamage = 平均攻击 × 10。"""
    people = max(int(sample_count), HP_MIN_PEOPLE)
    return max(1, int(int(avg_atk) * HP_ATK_MULT * people * HP_PEOPLE_MULT))


# ------------------------------------------------------------------ 团本辅助

def _team(w: Mapping, bid: Any) -> dict[str, Any] | None:
    team = (w.get("bosses") or {}).get(str(bid))
    return team if isinstance(team, dict) else None


def team_of(w: Mapping, uid: str, active_only: bool = False) -> tuple[str, dict[str, Any]] | None:
    """找玩家所在团本；优先未结算的，其次归档的（龙王榜/状态可读）。"""
    bosses = w.get("bosses") or {}
    found: tuple[str, dict[str, Any]] | None = None
    for key, team in bosses.items():
        if not isinstance(team, dict) or str(uid) not in [str(x) for x in (team.get("members") or [])]:
            continue
        if not team.get("settled") and not active_only:
            return str(key), team
        if not active_only and found is None:
            found = (str(key), team)
        if active_only and not team.get("settled"):
            return str(key), team
    return found


def unassigned(team: Mapping) -> int:
    return sum(1 for lot in (team.get("loot") or [])
               if isinstance(lot, dict) and int(lot.get("amount", 0) or 0) > 0)


def _finish_if_done(team: dict[str, Any]) -> bool:
    """5 件全部分完 → 归档（原版是 del 玩家/记录 key，本移植保留供龙王榜回看）。"""
    if unassigned(team) == 0 and not team.get("settled"):
        team["settled"] = True
        return True
    return False


def _name_of(team: Mapping, uid: str) -> str:
    names = team.get("names") or {}
    return str(names.get(str(uid)) or (str(uid)[:8] if uid else "无名"))


# ------------------------------------------------------------------ 掉落 / 建团

def draw_loot(pool: Sequence[Mapping], rng: random.Random,
              count: int = LOOT_COUNT) -> list[dict[str, Any]]:
    """从 GroupBoss.json[0].one（36 条）等概率抽 5 件，可重复；起拍价 floor(出售价)。"""
    rows = [e for e in (pool or []) if isinstance(e, dict) and e.get("name")]
    out = []
    for i in range(int(count)):
        row = rows[int(rng.random() * len(rows))] if rows else {}
        out.append({
            "no": i + 1,
            "name": str(row.get("name") or "无名遗珍"),
            "cls": str(row.get("class") or "道具"),
            "price": max(1, int(row.get("出售价") or 1)),
            "bidder": "",
            "bidder_name": "",
            "amount": 1,
            "bids": 0,
        })
    return out


def create_boss(w: dict[str, Any], uid: str, name: str, avg_atk: int,
                sample_count: int, ts: float, pool: Sequence[Mapping],
                rng: random.Random) -> tuple[bool, str]:
    """管理员 #开启若陀龙王：新建一支团本（原版每次调用都追加，不是单纯开关）。"""
    if int(avg_atk) <= 0:
        return False, "全服尚无境界达标者，无法为若陀龙王定标（原版此处仍误报成功）。"
    bid = int(w.get("next_id") or 1)
    w["next_id"] = bid + 1
    hp = boss_hp(avg_atk, sample_count)
    existing = team_of(w, uid, active_only=True)
    # 原版：创建者已在别团时，新团 Boss_item 为空且不写其 Player key
    members: list[str] = [] if existing else [str(uid)]
    names: dict[str, str] = {} if existing else {str(uid): str(name or "无名")}
    team = {
        "id": bid,
        "members": members,
        "names": names,
        "hp": hp,
        "hp_max": hp,
        "alive": True,
        "loot": draw_loot(pool, rng),
        "record": {},                  # uid -> [名号, 累计伤害]
        "killer": "",
        "created_at": float(ts),
        "settled": False,
    }
    w["bosses"][str(bid)] = team
    w["enabled"] = True
    note(w, f"{name or uid[:8]} 唤醒 {bid} 号若陀龙王（血条 {hp:,}）", ts)
    tail = "" if not existing else "（你已在别的团本，本团暂空，待他人加入）"
    return True, (f"【团本·开团】若陀龙王 {bid} 号苏醒，共享血条 {hp:,}，已定下 5 件掉落{tail}。\n"
                  f"发 #加入讨伐若陀龙王{bid} 入团，#讨伐若陀龙王 出手，"
                  f"击杀后 #若陀龙王奖励 竞价分配。")


def close_all(w: dict[str, Any], ts: float) -> str:
    """管理员 #关闭若陀龙王：清空全部团本（原版还会残留 GardenBossExit，本移植由分发器清）。"""
    n = len(w.get("bosses") or {})
    w["bosses"] = {}
    w["next_id"] = 1
    w["enabled"] = False
    note(w, f"管理员关闭若陀龙王，清除 {n} 支团本与全部退团标记", ts)
    return f"若陀龙王挑战 {n} 号关闭，全部团本已清空；退团标记一并重置。"


# ------------------------------------------------------------------ 队伍

_ARG_ID = re.compile(r"^\s*(\d+)\s*$")


def parse_id(arg: Any, default: int = 1) -> int:
    """原版 getNumversFromString 取第一个数字，无数字默认 1；`(1,2,3)` 只取 1。"""
    m = re.search(r"(\d+)", str(arg or ""))
    return int(m.group(1)) if m else int(default)


def join_boss(w: dict[str, Any], doc: Any, arg: Any, auth21: int, ts: float) -> str:
    ok, msg = system_on(w)
    if not ok:
        return msg
    ok, msg = gate(doc, auth21)
    if not ok:
        return msg
    bid = parse_id(arg)
    if team_of(w, str(doc.uid), active_only=True):
        return "你已在别的若陀龙王团本中（#退出若陀龙王团本 可离团一次）。"
    team = _team(w, bid)
    if not team or team.get("settled"):
        return f"没有 {bid} 号若陀龙王团本（#若陀龙王团本 查看）。"
    if not team.get("alive"):
        return f"{bid} 号龙王已被斩，只余掉落待分配。"
    members = list(team.get("members") or [])
    if len(members) >= MAX_MEMBERS:
        return f"队伍已满（{MAX_MEMBERS}/{MAX_MEMBERS}）。"
    if str(doc.uid) in [str(x) for x in members]:
        return "你已在这支队伍里。"
    members.append(str(doc.uid))
    team["members"] = members
    names = dict(team.get("names") or {})
    names[str(doc.uid)] = str(getattr(doc, "name", "") or str(doc.uid)[:8])
    team["names"] = names
    s = player_state_of(doc)
    s["last_id"] = bid
    set_player(doc, s)
    note(w, f"{names[str(doc.uid)]} 加入 {bid} 号团本（{len(members)}/{MAX_MEMBERS}）", ts)
    return (f"已加入 {bid} 号若陀龙王团本（{len(members)}/{MAX_MEMBERS}）。\n"
            f"成员：{'、'.join(_name_of(team, str(x)) for x in members)}\n"
            f"团长：{_name_of(team, members[0])}｜发 #讨伐若陀龙王 出手。")


def leave_boss(w: dict[str, Any], doc: Any, ts: float) -> str:
    pair = team_of(w, str(doc.uid), active_only=True)
    if not pair:
        return "你不在任何若陀龙王团本中。"
    bid, team = pair
    s = player_state_of(doc)
    used = [str(x) for x in (s.get("exit_ids") or [])]
    if str(bid) in used:
        return f"磨损缠身，{bid} 号团本已用掉唯一一次脱身机会（原版此处永久锁死，需管理员 #关闭若陀龙王 重置）。"
    members = [str(x) for x in (team.get("members") or [])]
    members = [x for x in members if x != str(doc.uid)]
    team["members"] = members
    used.append(str(bid))
    s["exit_ids"] = used[-30:]
    set_player(doc, s)
    tail = "（队伍已空）" if not members else f"团长顺延为 {_name_of(team, members[0])}。"
    note(w, f"{getattr(doc, 'name', '') or str(doc.uid)[:8]} 退出 {bid} 号团本", ts)
    return f"已脱离 {bid} 号若陀龙王团本。{tail}"


# ------------------------------------------------------------------ 战斗

def fight(w: dict[str, Any], doc: Any, stats: Any, cur_hp: int, hp_max: int,
          auth21: int, ts: float, rng: random.Random) -> tuple[str, list[tuple]]:
    """#讨伐若陀龙王：与镜像幻影 1v1 → 胜负折算固定伤害 → 扣共享血条 → 记账。

    返回 (文案, ops)；ops 由 main._dr_dispatch 统一落库（hp / items / stones）。
    """
    ok, msg = system_on(w)
    if not ok:
        return msg, []
    ok, msg = gate(doc, auth21)
    if not ok:
        return msg, []
    pair = team_of(w, str(doc.uid), active_only=True)
    if not pair:
        return "你不在任何若陀龙王团本中（#若陀龙王团本 查看，再 #加入讨伐若陀龙王编号）。", []
    bid, team = pair
    if not team.get("alive"):
        return f"{bid} 号龙王已被斩，发 #若陀龙王奖励 竞价分配掉落。", []
    left = cd_left(doc, ts)
    if left > 0:
        return f"元素风暴未散，需调息 {int(left)} 秒（原版 5 分钟进程内存 CD）。", []
    hp_cap = max(1, int(hp_max))
    if int(cur_hp) <= hp_cap * HP_GATE_RATIO:
        return "体力不支：当前气血不足上限一成，先疗伤再来。", []

    atk = max(1, int(getattr(stats, "atk", 0) or 0))
    defense = max(1, int(getattr(stats, "defense", 0) or 0))
    bao = float(getattr(stats, "bao", 0.0) or 0.0)
    a = Fighter.from_unit(battle.Unit(
        name=str(getattr(doc, "name", "") or str(doc.uid)[:8]),
        atk=atk, defense=defense, hp=max(1, int(cur_hp)), bao=bao))
    # 原版幻影三维各自独立 ×(0.8 + 0.6×rand)，不读怪物表
    b = Fighter.from_unit(battle.Unit(
        name=PHANTOM,
        atk=max(1, int(atk * (0.8 + 0.6 * rng.random()))),
        defense=max(1, int(defense * (0.8 + 0.6 * rng.random()))),
        hp=max(1, int(hp_cap * (0.8 + 0.6 * rng.random()))),
        bao=bao))
    res = run_1v1(a, b, rng, max_rounds=30)
    win = res.winner == 0
    fixed = int(int(team["hp_max"]) * (WIN_FIXED if win else LOSE_FIXED))
    harm, _crit = battle.harm(int(atk * 0.85), b.defense, rng)
    total = int(fixed + harm * (WIN_HARM_MULT if win else LOSE_HARM_MULT))

    ev = rng.random()
    hp = int(team.get("hp", 0) or 0)
    extras: list[str] = []
    full_heal = False
    if win and ev < HEAL_CHANCE:
        heal = int(int(team["hp_max"]) * HEAL_RATIO)
        hp = min(int(team["hp_max"]), hp + heal)
        extras.append(f"【元素风暴】龙王炼化地脉，回复 {heal:,}（不超过血条上限）。")
    hp -= total
    if (not win) and ev > 1 - EXTRA_CHANCE:
        extra = int(max(0, hp) * EXTRA_RATIO)
        hp -= extra
        total += extra
        full_heal = True
        extras.append(f"【小梦庇护】额外造成 {extra:,} 伤害，气血回满。")
    hp = max(0, hp)
    team["hp"] = hp

    rec = dict(team.get("record") or {})
    row = list(rec.get(str(doc.uid)) or [_name_of(team, str(doc.uid)), 0])
    row[1] = int(row[1] or 0) + total
    rec[str(doc.uid)] = [str(row[0]), int(row[1])]
    team["record"] = rec

    s = player_state_of(doc)
    s["cd_until"] = float(ts) + BATTLE_CD
    s["battles"] = int(s["battles"]) + 1
    s["last_id"] = int(bid)
    set_player(doc, s)

    hp_after = hp_cap if full_heal else min(hp_cap, max(1, int(res.a_hp)))
    ops: list[tuple] = [("hp", str(doc.uid), int(hp_after))]
    lines = [
        f"---- {bid} 号{BOSS_NAME} · 讨伐 ----",
        f"幻影之战：{'胜' if win else '负'}（{res.winner if res.winner is not None else '平'}）",
        f"折算伤害 {total:,}（固定 {fixed:,} + 浮动 {total - fixed:,}）",
        f"共享血条 {hp:,} / {int(team['hp_max']):,}",
    ]
    lines += extras
    if hp <= 0:
        team["alive"] = False
        team["killer"] = str(doc.uid)
        s["kills"] = int(s["kills"]) + 1
        set_player(doc, s)
        ops.append(("items", str(doc.uid), {TERMINATOR_ITEM: TERMINATOR_QTY}))
        lines.append(f"【终结一击】{_name_of(team, str(doc.uid))} 斩下龙首，独得「{TERMINATOR_ITEM}」×{TERMINATOR_QTY}。")
        lines.append("掉落已解锁：#若陀龙王奖励 查看，#若陀龙王出价编号*价格 竞价，团长 #若陀龙王分配编号。")
        note(w, f"{bid} 号龙王被 {_name_of(team, str(doc.uid))} 终结", ts)
    else:
        lines.append(f"你本场累计 {int(row[1]):,} 伤害（#龙王榜 查看占比）。")
    return "\n".join(lines), ops


# ------------------------------------------------------------------ 掉落 / 竞价 / 分配

def loot_text(w: Mapping, doc: Any) -> str:
    pair = team_of(w, str(doc.uid))
    if not pair:
        return "你不在任何若陀龙王团本（含已归档）中。"
    bid, team = pair
    if team.get("alive"):
        return (f"{bid} 号龙王尚有 {int(team.get('hp', 0)):,} 血，击杀后方可竞拍掉落。\n"
                f"掉落已在开团时定下 5 件，#讨伐若陀龙王 继续出手。")
    lines = [f"---- {bid} 号若陀龙王 · 掉落竞拍（团长 {_name_of(team, (team.get('members') or [''])[0])}）----"]
    for lot in (team.get("loot") or []):
        if not isinstance(lot, dict):
            continue
        state = f"【{lot.get('bidder_name') or '无人'} 出价 {int(lot.get('price', 0)):,}】" \
            if lot.get("bidder") else f"起拍 {int(lot.get('price', 0)):,}（最低加价至 {min_bid(int(lot.get('price', 0))):,}）"
        flag = "已分配" if int(lot.get("amount", 0) or 0) <= 0 else "待分配"
        lines.append(f"{lot.get('no')}. [{lot.get('cls')}] {lot.get('name')} ×1｜{state}｜{flag}"
                     f"｜出价 {int(lot.get('bids', 0) or 0)} 次")
    lines.append("格式：#若陀龙王出价编号*价格（价格填 1 = 自动最低加价）；团长 #若陀龙王分配编号。")
    return "\n".join(lines)


_BID_ARG = re.compile(r"^\s*(\d+)\s*[*＊\s]?\s*(\d*)\s*$")


def bid(w: dict[str, Any], doc: Any, arg: Any, ts: float) -> tuple[str, list[tuple]]:
    """原版 #若陀龙王出价<编号>*<价格>；加价 ≥30%，填 1/0/非法/缺价自动取最低合规价。"""
    ok, msg = system_on(w)
    if not ok:
        return msg, []
    pair = team_of(w, str(doc.uid))
    if not pair:
        return "你不在任何若陀龙王团本中。", []
    bid_id, team = pair
    if team.get("alive"):
        return f"{bid_id} 号龙王未倒，掉落尚未开放竞拍。", []
    if team.get("settled") or _finish_if_done(team):
        return "5 件掉落已全部分配完毕，本团本归档。", []
    m = _BID_ARG.match(str(arg or ""))
    if not m:
        return "格式：#若陀龙王出价编号*价格（例：#若陀龙王出价2*5000，价格填 1 自动最低加价）。", []
    idx = int(m.group(1)) - 1
    lots = [x for x in (team.get("loot") or []) if isinstance(x, dict)]
    if idx < 0 or idx >= len(lots):
        return f"不存在编号 {idx + 1}（共 {len(lots)} 件）。", []
    lot = lots[idx]
    if int(lot.get("amount", 0) or 0) <= 0:
        return "该掉落已分配。", []
    raw_price = int(m.group(2)) if m.group(2) else 1
    floor_price = min_bid(int(lot.get("price", 1) or 1))
    price = raw_price if raw_price > 1 else floor_price
    if price < floor_price:
        return (f"出价 {price:,} 低于下限：当前 {int(lot.get('price', 0)):,}，"
                f"每次加价不少于 30%（最低 {floor_price:,}）。"), []
    if int(getattr(doc, "stones", 0) or 0) < price:
        return f"灵石不足：需 {price:,}，现有 {int(getattr(doc, 'stones', 0) or 0):,}。", []
    lot["price"] = int(price)
    lot["bidder"] = str(doc.uid)
    lot["bidder_name"] = str(getattr(doc, "name", "") or str(doc.uid)[:8])
    lot["bids"] = int(lot.get("bids", 0) or 0) + 1
    note(w, f"{lot['bidder_name']} 为 {bid_id} 号第 {lot['no']} 件「{lot['name']}」出价 {price:,}", ts)
    return (f"出价成功：第 {lot['no']} 件「{lot['name']}」现价 {price:,} 灵石"
            f"（{lot['bidder_name']}，第 {lot['bids']} 次出价）。\n"
            f"下一位至少需出 {min_bid(price):,}；分配时中标者付款，全队平分。"), []


def assign(w: dict[str, Any], doc: Any, arg: Any, balances: Mapping[str, int],
           ts: float) -> tuple[str, list[tuple]]:
    """团长 #若陀龙王分配<编号>：中标者付款拿货，全队平分 floor(last_price / 当前人数)。"""
    ok, msg = system_on(w)
    if not ok:
        return msg, []
    pair = team_of(w, str(doc.uid))
    if not pair:
        return "你不在任何若陀龙王团本中。", []
    bid_id, team = pair
    members = [str(x) for x in (team.get("members") or [])]
    if not members or members[0] != str(doc.uid):
        return f"只有 {bid_id} 号团本团长（{_name_of(team, members[0]) if members else '无'}）可以分配掉落。", []
    if team.get("alive"):
        return "龙王未倒，掉落不可分配。", []
    if team.get("settled") or _finish_if_done(team):
        return "5 件掉落已全部分配完毕，本团本归档。", []
    idx = parse_id(arg) - 1
    lots = [x for x in (team.get("loot") or []) if isinstance(x, dict)]
    if idx < 0 or idx >= len(lots):
        return f"不存在编号 {idx + 1}（共 {len(lots)} 件）。", []
    lot = lots[idx]
    if int(lot.get("amount", 0) or 0) <= 0:
        return "该掉落已分配。", []
    buyer = str(lot.get("bidder") or "")
    if not buyer:
        return "该物品尚无人出价，不能分配。", []
    price = int(lot.get("price", 0) or 0)
    have = int(balances.get(buyer, 0) or 0)
    if buyer == str(doc.uid):
        have = int(getattr(doc, "stones", 0) or 0)
    if have < price:
        return (f"中标者 {lot.get('bidder_name') or _name_of(team, buyer)} 灵石不足"
                f"（需 {price:,}，现有 {have:,}），本移植补的验资拦截（原版直接扣成负数）。"), []
    share = price // max(1, len(members))
    ops: list[tuple] = [
        ("stones", buyer, -price),
        ("items", buyer, {str(lot.get("name")): 1}),
    ]
    for uid in members:
        if share > 0:
            ops.append(("stones", uid, share))
    lot["amount"] = 0
    done = _finish_if_done(team)
    note(w, f"{bid_id} 号第 {lot['no']} 件「{lot['name']}」以 {price:,} 归 "
            f"{lot.get('bidder_name')}，{len(members)} 人各分 {share:,}", ts)
    return (f"分配完成：第 {lot['no']} 件「{lot['name']}」归 {lot.get('bidder_name')}，"
            f"付款 {price:,} 灵石。\n全队 {len(members)} 人各得 {share:,} 灵石"
            f"（floor({price:,}/{len(members)})，余数不发）。\n"
            + ("5 件已分完，本团本归档；#龙王榜 仍可回看伤害占比。" if done
               else f"尚有 {unassigned(team)} 件待分配。")), ops


# ------------------------------------------------------------------ 榜单 / 面板

def rank_text(w: Mapping, doc: Any, limit: int = RANK_LIMIT) -> str:
    pair = team_of(w, str(doc.uid))
    if not pair:
        return "今日来此，可是来看看我流云借风真君？"
    bid, team = pair
    rec = team.get("record") or {}
    rows = []
    for uid, val in rec.items():
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            rows.append((str(uid), str(val[0]), int(val[1] or 0)))
    if not rows:
        return f"---- {bid} 号龙王榜 ----\n尚无伤害记录，发 #讨伐若陀龙王 出手。"
    rows.sort(key=lambda x: (-x[2], x[1]))
    total = sum(x[2] for x in rows) or 1
    mine = next((x for x in rows if x[0] == str(doc.uid)), None)
    lines = [f"---- 若陀龙王 {bid} 号 · 龙王榜（前 {min(limit, len(rows))}）----"]
    for i, (_uid, name, dmg) in enumerate(rows[:limit], 1):
        lines.append(f"第 {i} 名｜{name}｜总伤害 {dmg:,}｜占比 {dmg * 100 // total}%")
    if mine:
        pos = rows.index(mine) + 1
        lines.append(f"你排第 {pos} 名，伤害占比 {mine[2] * 100 // total}%。")
    else:
        lines.append("你尚未出手。")
    return "\n".join(lines)


def list_text(w: Mapping) -> str:
    ok, msg = system_on(w)
    if not ok:
        return msg
    bosses = w.get("bosses") or {}
    live = [(k, t) for k, t in bosses.items() if isinstance(t, dict) and not t.get("settled")]
    if not live:
        return "当前没有进行中的若陀龙王团本（管理员 #开启若陀龙王 唤醒一支）。"
    lines = [f"---- 若陀龙王团本（{len(live)} 支）----"]
    for key, team in sorted(live, key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
        members = [str(x) for x in (team.get("members") or [])]
        hp = int(team.get("hp", 0) or 0)
        lines.append(
            f"{key} 号｜{'存活' if team.get('alive') else '已斩'}｜血条 {hp:,}/{int(team.get('hp_max', 0)):,}"
            f"｜{len(members)}/{MAX_MEMBERS} 人｜未分配 {unassigned(team)} 件")
        lines.append("　成员：" + ("、".join(
            _name_of(team, x) + ("（团长）" if i == 0 else "") for i, x in enumerate(members)) or "空"))
    lines.append("#加入讨伐若陀龙王编号 入团｜#讨伐若陀龙王 出手｜#龙王榜 看伤害榜")
    return "\n".join(lines)


def status_text(w: Mapping, doc: Any, ts: float) -> str:
    pair = team_of(w, str(doc.uid))
    s = player_state_of(doc)
    if not pair:
        return (f"---- 若陀龙王 · 个人状态 ----\n当前未在任何团本。\n"
                f"战斗调息：{int(cd_left(doc, ts))} 秒｜累计出手 {s['battles']} 次｜终结 {s['kills']} 次\n"
                f"全服团本 {len(w.get('bosses') or {})} 支｜#若陀龙王团本 查看")
    bid, team = pair
    members = [str(x) for x in (team.get("members") or [])]
    raw = (team.get("record") or {}).get(str(doc.uid))
    mine = int(raw[1] or 0) if isinstance(raw, (list, tuple)) and len(raw) >= 2 else 0
    lines = [
        f"---- 若陀龙王 {bid} 号状态 ----",
        "攻击：????????????",
        "防御：????????????",        # 原版面板攻防各 12 个 ? 打码
        f"血量：{int(team.get('hp', 0)):,} / {int(team.get('hp_max', 0)):,}",
        f"成员：{len(members)}/{MAX_MEMBERS}（团长 {_name_of(team, members[0]) if members else '无'}）",
        f"掉落：{unassigned(team)} 件待分配｜{'存活' if team.get('alive') else '已斩'}",
        f"战斗调息：{int(cd_left(doc, ts))} 秒｜你在本团累计 {mine:,} 伤害",
        f"个人：出手 {s['battles']} 次 / 终结 {s['kills']} 次｜退团机会已用于 "
        f"{len(s.get('exit_ids') or [])} 支团本",
    ]
    return "\n".join(lines)


def system_text(w: Mapping) -> str:
    bosses = w.get("bosses") or {}
    alive = sum(1 for t in bosses.values() if isinstance(t, dict) and t.get("alive"))
    lines = [
        "---- 若陀龙王 · 全服状态 ----",
        f"系统：{'开启' if w.get('enabled') else '关闭'}｜团本 {len(bosses)} 支（存活 {alive}）｜下一编号 {w.get('next_id')}",
        "存储：calamity_state['dragon'] 单例 + ext['dragon']（原版为文件 + Redis + 进程内存）",
    ]
    logs = list(w.get("system_log") or [])[-8:]
    lines += (["管理员留痕："] + [f"· {x}" for x in logs]) if logs else ["管理员留痕：暂无"]
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "【若陀龙王 · 团本竞价规则（对齐原版 TeamBoss.js 11 条 rule）】",
        "1. 两套团本互不相通：本系统是「各自单挑幻影 + 共享血条 + 掉落竞价」；",
        "   #组队迎战帝尊 / #发起讨伐 属于 W8-D4 的另一套（多人回合），状态不共享。",
        f"2. 建团由管理员 #开启若陀龙王 完成，每次新建一支、开团即抽定 {LOOT_COUNT} 件掉落",
        "   （池子为 GroupBoss.json 的 36 条，不是团本奖励列表.json）。",
        f"3. 血条 = 平均攻击(境界≥{HP_STAT_GATE}) × 10 × max(达标人数,5) × 5；",
        "   幻影镜像玩家三维各 ×0.8~1.4，走 1v1，不读怪物表。",
        "4. 出手折算：胜 = 血条上限×25% + Harm(攻击×85%,幻影防御)×6；",
        "   负 = 上限×5% + Harm×4。5% 概率胜利时龙王回血上限 50%；",
        "   另 5% 概率败北触发小梦（额外 15% 伤害 + 气血回满）。",
        f"5. 门槛：境界 {REALM_GATE} / 轮回 / 权柄 {AUTH21_GATE} 档三选一；当前气血需高于上限一成；",
        f"   队伍上限 {MAX_MEMBERS} 人；每次出手 {int(BATTLE_CD)} 秒 CD（原版只在击杀时写、且重启即丢，本移植改为每次写并持久化）。",
        "6. 击杀后开放竞拍：加价不少于 30%，价格填 1 / 0 / 非法 / 缺价一律自动取最低合规价；",
        "   #若陀龙王分配编号 由团长执行，中标者付款拿货，全队平分 floor(成交价 / 当前人数)；",
        f"   终结者独得「{TERMINATOR_ITEM}」×{TERMINATOR_QTY}。",
        "7. 龙王榜取前 20 名按累计伤害降序，附自己占比；5 件分完团本归档但保留榜单可回看。",
        "8. 纠偏：帮助 yaml 的 #退出若陀龙王团本$ 多了个 $；#加入讨伐若陀龙王(1,2,3) 只取首个数字；",
        "   (编号)*(价格) 的 * 是字面分隔符；6 条药园残留 rule 被注释且无实现，不搬；",
        "   原版退团锁 GardenBossExit 只 set 不 del（永久锁死），本移植改为每团一次机会且关闭时重置；",
        "   跨服三指令不做；面板「奖励:皮肤」在掉落池中并不存在。",
    ])


def help_text() -> str:
    return "\n".join([
        "【若陀龙王 · 竞价团指令一览（原版 11 条 + 帮助/规则/系统 3 条补位）】",
        "#若陀龙王帮助 / #若陀龙王规则　本表 / 完整口径",
        "#若陀龙王团本　列出全部进行中的团本与成员",
        "#加入讨伐若陀龙王编号　入团（5 人上限，无数字默认 1 号）",
        "#退出若陀龙王团本　离团（每团仅一次机会，团长顺延）",
        "#讨伐若陀龙王　与镜像幻影单挑，折算伤害扣共享血条",
        "#若陀龙王状态　攻防打码、血条、成员、个人 CD 与伤害",
        "#龙王榜　本团前 20 名累计伤害与自己的占比",
        "#若陀龙王奖励　查看 5 件掉落与当前出价",
        "#若陀龙王出价编号*价格　竞拍（加价 ≥30%，价格填 1 自动最低）",
        "#若陀龙王分配编号　团长分配：中标者付款，全队平分灵石",
        "#开启若陀龙王 / #关闭若陀龙王　管理员：新建团本 / 清空全部",
        "#若陀龙王系统　管理员留痕与全服开关",
        "⚠️ 带参数的三条同时支持空格写法（如「#若陀龙王出价 2*5000」）；",
        "   # 必需；与 W8-D4 帝尊团本状态互不相通。",
    ])
