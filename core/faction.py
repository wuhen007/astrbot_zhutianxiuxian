"""势力（W7-3）：三大势力的加入 / 退出 / 贡献 / 分级俸禄。

原版 `apps/User/shili.js`（1403 行，瑶池 / 摇光 + 剑云海，职位表与每日俸禄）。

本移植（按 W7-3 规划的裁剪口径）：
- 只保留「加入 / 退出 / 捐贡献 / 每日俸禄 / 状态」五个动作，砍掉职位晋升、秘库、剑云海抉择、NPC 剧情
- 俸禄口径复用插件内已有的宗门俸禄：`等级 × 1200 灵石 ×（宗主 ×2）`，22 小时一次，从势力基金支出
- 等级由累计贡献推导：`1 + 总贡献 // 200000`，上限 9；不另存等级字段（单一真相）
- 供奉按 1:2 折算贡献（1 灵石 = 2 点贡献），避免与宗门 1:1 的直觉冲突时不好调

shortcut：职位（记名弟子→圣女）与势力专属法宝 / 秘库 / 地盘战未移植；成员加成仅为面板展示。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

LEVEL_MAX = 9
CONTRIB_PER_LEVEL = 200_000
SALARY_PER_LEVEL = 1200
SALARY_COOLDOWN = 22 * 3600
CONTRIB_RATE = 2          # 1 灵石 = 2 点贡献

DEFAULT_FACTIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "瑶池圣地", "icon": "🌸",
        "desc": "西昆仑遗脉，以灵泉与丹术闻名，门下多女修。",
        "focus": "疗伤与丹药",
        "requirement": 0,
    },
    {
        "name": "摇光圣地", "icon": "⚜️",
        "desc": "东荒七大圣地之首，圣主坐镇，攻伐之术冠绝诸天。",
        "focus": "攻伐与炼器",
        "requirement": 10,
    },
    {
        "name": "剑云海", "icon": "⚔️",
        "desc": "剑修圣地，一剑破万法，只问剑心不问出身。",
        "focus": "剑道与暴击",
        "requirement": 20,
    },
)


def default_state() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for f in DEFAULT_FACTIONS:
        rows[f["name"]] = {
            "level": 1,
            "contribution": 0,
            "fund": 0,
            "members": {},
        }
    return {"factions": rows}


def ensure(value: Mapping | None) -> dict[str, Any]:
    state = dict(value or {})
    rows = state.get("factions")
    state["factions"] = dict(rows) if isinstance(rows, Mapping) else {}
    for f in DEFAULT_FACTIONS:
        row = state["factions"].get(f["name"])
        row = dict(row) if isinstance(row, Mapping) else {}
        row.setdefault("contribution", 0)
        row.setdefault("fund", 0)
        row.setdefault("members", {})
        if not isinstance(row.get("members"), Mapping):
            row["members"] = {}
        row["level"] = level_of(int(row.get("contribution", 0) or 0))
        state["factions"][f["name"]] = row
    return state


def info_of(name: str) -> dict[str, Any] | None:
    return next((dict(f) for f in DEFAULT_FACTIONS if f["name"] == name), None)


def names() -> list[str]:
    return [f["name"] for f in DEFAULT_FACTIONS]


def level_of(contribution: int) -> int:
    return min(LEVEL_MAX, 1 + max(0, int(contribution)) // CONTRIB_PER_LEVEL)


def next_level_at(contribution: int) -> int | None:
    lv = level_of(contribution)
    if lv >= LEVEL_MAX:
        return None
    return lv * CONTRIB_PER_LEVEL


def faction_of(state: Mapping, uid: str) -> str | None:
    for name, row in (state.get("factions") or {}).items():
        if uid in (row.get("members") or {}):
            return str(name)
    return None


def member_of(state: Mapping, name: str, uid: str) -> dict | None:
    row = (state.get("factions") or {}).get(name) or {}
    m = (row.get("members") or {}).get(uid)
    return dict(m) if isinstance(m, Mapping) else None


def is_leader(state: Mapping, name: str, uid: str) -> bool:
    m = member_of(state, name, uid)
    return bool(m) and m.get("role") == "宗主"


def join(state: dict, name: str, uid: str, player_name: str, realm: int) -> tuple[bool, str]:
    info = info_of(name)
    if not info:
        return False, f"没有「{name}」这个势力。#势力列表 查看。"
    if faction_of(state, uid):
        return False, f"你已在【{faction_of(state, uid)}】，先 #退出势力 再改换门庭。"
    if int(realm) < int(info["requirement"]):
        return False, f"【{name}】只收第 {int(info['requirement']) + 1} 境以上的修士（你第 {int(realm) + 1} 境）。"
    row = state["factions"][name]
    members = dict(row.get("members") or {})
    role = "宗主" if not members else "门人"
    members[uid] = {"name": player_name, "role": role, "contrib": 0}
    row["members"] = members
    state["factions"][name] = row
    tag = "成为开山宗主" if role == "宗主" else "成为门人"
    return True, f"你加入【{info['icon']}{name}】，{tag}。"


def leave(state: dict, uid: str) -> tuple[bool, str]:
    name = faction_of(state, uid)
    if not name:
        return False, "你尚未加入任何势力。"
    row = state["factions"][name]
    members = dict(row.get("members") or {})
    was_leader = (members.get(uid) or {}).get("role") == "宗主"
    members.pop(uid, None)
    if was_leader and members:
        heir = max(members.items(), key=lambda kv: int((kv[1] or {}).get("contrib", 0) or 0))[0]
        members[heir] = {**members[heir], "role": "宗主"}
    row["members"] = members
    state["factions"][name] = row
    note = "，宗主之位已传给贡献最高者" if was_leader and members else ""
    return True, f"你已脱离【{name}】{note}。"


def contribute(state: dict, uid: str, stones: int) -> tuple[bool, str, int]:
    name = faction_of(state, uid)
    if not name:
        return False, "你尚未加入任何势力，何谈贡献。", 0
    amount = int(stones)
    if amount <= 0:
        return False, "供奉数量需大于 0。", 0
    row = state["factions"][name]
    points = amount * CONTRIB_RATE
    before = int(row.get("contribution", 0) or 0)
    row["contribution"] = before + points
    row["fund"] = int(row.get("fund", 0) or 0) + amount
    row["level"] = level_of(row["contribution"])
    members = dict(row.get("members") or {})
    m = dict(members.get(uid) or {"name": uid, "role": "门人", "contrib": 0})
    m["contrib"] = int(m.get("contrib", 0) or 0) + points
    members[uid] = m
    row["members"] = members
    state["factions"][name] = row
    if row["level"] > level_of(before):
        return True, (f"供奉 {amount:,} 灵石 → 贡献 +{points:,}；【{name}】升为 {row['level']} 级！"
                      f"基金 {row['fund']:,}。"), points
    return True, (f"供奉 {amount:,} 灵石 → 贡献 +{points:,}（势力共 {row['contribution']:,}）；"
                  f"基金 {row['fund']:,}。"), points


def salary(state: dict, uid: str) -> tuple[int, str, str]:
    """返回 (俸禄额, 势力名, 身份)；未入势力返回 (0, "", "")。"""
    name = faction_of(state, uid)
    if not name:
        return 0, "", ""
    row = state["factions"][name]
    m = member_of(state, name, uid) or {}
    role = str(m.get("role") or "门人")
    amount = int(row.get("level", 1) or 1) * SALARY_PER_LEVEL * (2 if role == "宗主" else 1)
    return amount, str(name), role


def pay(state: dict, uid: str) -> tuple[bool, str, int]:
    amount, name, role = salary(state, uid)
    if not name:
        return False, "你尚未加入任何势力，无俸可领。", 0
    row = state["factions"][name]
    if int(row.get("fund", 0) or 0) < amount:
        return False, (f"【{name}】基金不足发俸（需 {amount:,}，现存 {int(row.get('fund', 0)):,}），"
                       f"快去 #势力贡献 数量 添些香火。"), 0
    row["fund"] = int(row["fund"]) - amount
    state["factions"][name] = row
    return True, f"领取【{name}】俸禄 {amount:,} 灵石（{role}·{int(row.get('level', 1))} 级）。", amount


def list_text(state: Mapping, uid: str = "") -> str:
    mine = faction_of(state, uid) if uid else None
    lines = ["--- 三大势力 ---"]
    for info in DEFAULT_FACTIONS:
        name = info["name"]
        row = (state.get("factions") or {}).get(name) or {}
        members = row.get("members") or {}
        lines.append(
            f"{info['icon']}【{name}】{int(row.get('level', 1))} 级"
            f"｜成员 {len(members)} 人｜基金 {int(row.get('fund', 0)):,}"
            f"｜门槛 第 {int(info['requirement']) + 1} 境"
            f"{' ← 你在此' if mine == name else ''}"
        )
        lines.append(f"   {info['desc']}（偏重：{info['focus']}）")
    lines.append("指令：#加入势力 名字｜#退出势力｜#势力贡献 灵石数｜#势力俸禄｜#势力状态")
    return "\n".join(lines)


def status_text(state: Mapping, uid: str) -> str:
    name = faction_of(state, uid)
    if not name:
        return "你尚未加入任何势力。#势力列表 可看三大势力。"
    row = state["factions"][name]
    m = member_of(state, name, uid) or {}
    amount, _n, role = salary(state, uid)
    nxt = next_level_at(int(row.get("contribution", 0) or 0))
    progress = (f"距 {level_of(row['contribution']) + 1} 级还需 {nxt - int(row['contribution']):,} 贡献"
                if nxt is not None else "已至 9 级（满）")
    return (f"--- {name} · {role} ---\n"
            f"势力等级：{int(row.get('level', 1))} 级｜总贡献 {int(row.get('contribution', 0)):,}｜"
            f"基金 {int(row.get('fund', 0)):,}\n"
            f"你的贡献：{int(m.get('contrib', 0) or 0):,}｜每日俸禄 {amount:,} 灵石\n"
            f"{progress}")
