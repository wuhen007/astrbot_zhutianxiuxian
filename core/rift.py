"""裂界副本（B10）：全服共享裂界 + 三条探索路线 + 界源兑换。

原版：apps/PlaneRiftFestival.js + model/planeRiftFestival.js（RIFT_ROUTES/anchor/expedition）。
本移植：
- 原版的「千年纪元每 2000 年刷新」未做（纪元系统在 B11），改为**每 6 小时一个窗口**，
  窗口内全服共享 1 处裂界，仙界 / 太初星墟轮换；坐标直接落在 B9.5 的位面方图上
- 进入裂界需本人身处该位面（#穿梭 先到）
- 每人每处裂界一次远征，最多 3 层；失败折半、通关/撤离全得、过期自动结算
- 界源 = 战利品 ×（1 + 全服锚定度/200），另按境界折算修为/血气
shortcut: 未做巡界签到加成、元神门槛、管理员强制开关（自动窗口已覆盖）。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from . import battle, plane

WINDOW_SECONDS = 6 * 3600
MAX_DEPTH = 3
PLANES = ("仙界", "太初星墟")

DEFINITIONS: dict[str, list[dict]] = {
    "仙界": [
        {"name": "斩岁仙府", "location": "冥寒仙府", "x": 242, "y": 116},
        {"name": "万象丹庭", "location": "广寒界", "x": 90, "y": 745},
        {"name": "天河兵冢", "location": "永恒之花", "x": 625, "y": 720},
    ],
    "太初星墟": [
        {"name": "归零舰墓", "location": "归零舰墓", "x": 180, "y": 180},
        {"name": "太初矿心", "location": "太初矿心", "x": 500, "y": 500},
        {"name": "无光观测站", "location": "无光观测站", "x": 820, "y": 180},
    ],
}

ROUTES: dict[str, dict] = {
    "稳阵": {"base": 0.92, "penalty": 0.08, "anchor": 6, "contribution": 4,
            "loot": lambda d: 3 + d,
            "desc": "布阵稳界，成功率高、收益低，锚定度涨得最快"},
    "寻宝": {"base": 0.74, "penalty": 0.11, "anchor": 3, "contribution": 3,
            "loot": lambda d: 5 + d * 2,
            "desc": "潜行取宝，可能惊动守护灵（收益 ×1.3 或 ×0.6）"},
    "强攻": {"base": 0.6, "penalty": 0.12, "anchor": 4, "contribution": 6,
            "loot": lambda d: 8 + d * 3,
            "desc": "每层硬撼裂界守卫，胜负即成败，收益最高"},
}

EXCHANGES: dict[str, dict] = {
    "真我宝盒": {"cost": 10, "qty": 1},
    "超越宝盒": {"cost": 10, "qty": 1},
    "星图": {"cost": 40, "qty": 1},
    "巡界玉符": {"cost": 18, "qty": 2},
    "定神丹": {"cost": 25, "qty": 1},
    "无尽秘钥": {"cost": 50, "qty": 1},
    "无尽秘钥配方": {"cost": 100, "qty": 1},
    "无上神物": {"cost": 80, "qty": 1},
}

EXP_PER_SOURCE = 20_000


# ---------------------------------------------------------------- 全服状态

def default_state() -> dict:
    return {"window": -1, "rift": None, "history": []}


def ensure(g: Mapping | None, now: float, rng: Any) -> tuple[dict, dict, bool]:
    """保证当前窗口有裂界。返回 (全服状态, 裂界, 是否新开)。"""
    state = dict(g or default_state())
    state.setdefault("history", [])
    win = int(now // WINDOW_SECONDS)
    rift = state.get("rift")
    if isinstance(rift, Mapping) and float(rift.get("expires_at", 0) or 0) > now \
            and int(state.get("window", -1)) == win:
        return state, dict(rift), False

    if isinstance(rift, Mapping):
        state["history"] = (list(state["history"]) + [
            {"id": rift.get("id"), "name": rift.get("name"), "plane": rift.get("plane"),
             "anchor": rift.get("anchor", 0)}
        ])[-8:]

    plane_name = PLANES[win % len(PLANES)]
    defs = DEFINITIONS[plane_name]
    definition = defs[rng.randrange(len(defs))]
    opened = win * WINDOW_SECONDS
    rift = {
        "id": f"rift-{win}", "plane": plane_name, **definition,
        "opened_at": float(opened), "expires_at": float(opened + WINDOW_SECONDS),
        "anchor": 0, "contribution": {}, "participants": [],
    }
    state["window"] = win
    state["rift"] = rift
    return state, rift, True


def current_rift(g: Mapping | None, now: float) -> dict | None:
    rift = (g or {}).get("rift")
    if not isinstance(rift, Mapping):
        return None
    return dict(rift) if float(rift.get("expires_at", 0) or 0) > now else None


# ---------------------------------------------------------------- 玩家状态

def expedition_of(doc: Any) -> dict | None:
    exp = doc.ext.get("rift")
    return exp if isinstance(exp, dict) and exp.get("id") else None


def source_of(doc: Any) -> int:
    return int(doc.ext.get("rift_source", 0) or 0)


def join(g: dict, doc: Any, now: float) -> tuple[bool, str]:
    rift = current_rift(g, now)
    if not rift:
        return False, "当前没有开启中的裂界。"
    exp = expedition_of(doc)
    if exp and exp.get("id") == rift["id"] and exp.get("status") == "active":
        return False, "你已在这处裂界中，直接选路线即可。"
    here = plane.current(plane.state_of(doc))
    if here != rift["plane"]:
        return False, (f"裂界开在【{rift['plane']}】的{rift['location']}，你目前在【{here}】。\n"
                       f"先 `#穿梭 {rift['plane']}` 再 `#进入裂界`。")
    doc.ext["rift"] = {
        "id": rift["id"], "depth": 0, "loot": 0, "contribution": 0,
        "status": "active", "started_at": float(now), "secured": 0,
    }
    parts = list(g["rift"].get("participants") or [])
    if doc.uid not in parts:
        parts.append(doc.uid)
    g["rift"]["participants"] = parts
    return True, (f"【裂界·{rift['name']}】\n"
                  f"你踏入【{rift['plane']}·{rift['location']}】的裂口，界壁在身后合拢。\n"
                  f"共 {MAX_DEPTH} 层，任选路线：#裂界稳阵 / #裂界寻宝 / #裂界强攻；随时可 #撤离裂界。")


# ---------------------------------------------------------------- 探索

def _payout(g: dict, doc: Any, rift: Mapping, status: str) -> str:
    exp = doc.ext["rift"]
    loot = int(exp.get("loot", 0) or 0)
    secured = loot if status in ("cleared", "withdrew", "expired") else loot // 2
    anchor = min(100, max(0, int(rift.get("anchor", 0) or 0)))
    mult = 1 + anchor / 200
    source = int(secured * mult)
    realm = max(0, int(getattr(doc, "realm_index", 0) or 0))
    gain = int(source * EXP_PER_SOURCE * (1 + realm / 10))
    doc.ext["rift_source"] = source_of(doc) + source
    doc.exp = int(doc.exp) + gain
    doc.ext["xueqi"] = float(doc.ext.get("xueqi", 0) or 0) + gain
    doc.ext["rift_last"] = {
        "name": rift.get("name"), "status": status, "depth": exp.get("depth", 0),
        "source": source, "gain": gain, "at": time.time(),
    }
    doc.ext["rift"] = None
    label = {"cleared": "通关", "withdrew": "撤离", "expired": "裂界闭合", "failed": "远征失败"}.get(status, status)
    return (f"【{label}】战利品 {secured} × 锚定加成 {mult:.2f} → 界源 +{source}\n"
            f"修为 +{gain:,}｜血气 +{gain:,}（现有界源 {source_of(doc)}）")


def settle_if_needed(g: dict, doc: Any, now: float) -> str | None:
    """裂界已关闭而远征未结束时自动结算。"""
    exp = expedition_of(doc)
    if not exp or exp.get("status") != "active":
        return None
    rift = (g or {}).get("rift")
    if isinstance(rift, Mapping) and rift.get("id") == exp["id"] \
            and float(rift.get("expires_at", 0) or 0) > now:
        return None
    return _payout(g, doc, rift or {"name": exp["id"], "anchor": 0}, "expired")


def explore(g: dict, doc: Any, route_name: str, stats: Mapping, rng: Any,
            now: float) -> tuple[bool, str]:
    rift = current_rift(g, now)
    exp = expedition_of(doc)
    if not rift or not exp or exp.get("status") != "active" or exp.get("id") != rift["id"]:
        return False, "你不在进行中的裂界里（#裂界副本 查看，#进入裂界 加入）。"
    route = ROUTES.get(route_name)
    if not route:
        return False, "路线只有：稳阵 / 寻宝 / 强攻。"
    depth = int(exp.get("depth", 0) or 0)
    if depth >= MAX_DEPTH:
        return False, "本次远征已到底，先 #撤离裂界 结算。"
    realm = max(0, int(getattr(doc, "realm_index", 0) or 0))
    bonus = min(0.15, max(0.0, (realm - 16) * 0.02))
    chance = route["base"] - depth * route["penalty"] + bonus
    notes: list[str] = []
    loot_scale = 1.0
    contribution_bonus = 0
    forced_fail = False

    if route_name == "强攻":
        factor = 0.55 + depth * 0.15
        guard = battle.Unit(
            f"裂界守卫·{rift['name']}", max(1, int(stats["atk"] * factor)),
            max(1, int(stats["defense"] * factor * 0.9)),
            max(1, int(stats["hp"] * (0.35 + depth * 0.15))), 0.1,
            speed=100,  # 原版 createRiftGuardian 固定 GUARD_BASE_SPEED=100
        )
        me = battle.Unit(str(getattr(doc, "name", "") or "道友"), int(stats["atk"]),
                         int(stats["defense"]), max(1, int(stats.get("hp_cur", stats["hp"]))),
                         float(stats.get("bao", 0) or 0),
                         speed=int(stats.get("speed", battle.speed_of(doc))),
                         crit_damage=stats.get("crit_damage"),
                         action_bar=int(stats.get("action_bar", battle.initial_action_bar(doc))))
        winner, log, hp_left, _ = battle.spar_full(me, guard, rng)
        doc.ext["hp"] = max(0, int(hp_left))
        tail = log[-1] if log else ""
        if winner != 0:
            forced_fail = True
            notes.append(f"守卫碾压了你的攻势{tail}")
        else:
            notes.append(f"你击破守卫{tail}")
            if hp_left > stats["hp"] * 0.8:
                contribution_bonus = 2
                notes.append("无伤破阵，贡献 +2")
    elif route_name == "稳阵" and rng.random() < 0.35:
        anchor = int(rift.get("anchor", 0) or 0)
        relieved = anchor >= 60
        penalty = 0.1 if relieved else 0.2
        chance -= penalty
        notes.append(f"界潮涌动，成功率 -{int(penalty * 100)}%"
                     + ("（锚定度压住了大半）" if relieved else ""))
    elif route_name == "寻宝" and rng.random() < 0.45:
        stealth = min(0.95, max(0.05, 0.5 + bonus / 2))
        if rng.random() < stealth:
            loot_scale = 1.3
            notes.append("潜行绕过守护灵，本层收益 ×1.3")
        else:
            loot_scale = 0.6
            chance -= 0.1
            notes.append("破阵失手惊动守护灵，收益 ×0.6、成功率 -10%")

    chance = min(0.98, max(0.05, chance))
    success = (not forced_fail) and (rng.random() < chance or route_name == "强攻")
    if not success:
        exp["depth"] = depth
        msg = _payout(g, doc, rift, "failed")
        return True, (f"第 {depth + 1} 层·{route_name} 失败（成功率 {chance:.0%}）。\n"
                      + ("\n".join(notes) + "\n" if notes else "") + msg)

    gained = max(1, round(route["loot"](depth) * loot_scale))
    exp["loot"] = int(exp.get("loot", 0)) + gained
    exp["depth"] = depth + 1
    exp["contribution"] = int(exp.get("contribution", 0)) + route["contribution"] + contribution_bonus
    g["rift"]["anchor"] = min(100, int(rift.get("anchor", 0) or 0) + route["anchor"])
    contrib = dict(g["rift"].get("contribution") or {})
    contrib[doc.uid] = int(contrib.get(doc.uid, 0)) + route["contribution"] + contribution_bonus
    g["rift"]["contribution"] = contrib

    body = (f"第 {depth + 1} 层·{route_name} 成功（成功率 {chance:.0%}），战利品 +{gained}。\n"
            + ("\n".join(notes) + "\n" if notes else "")
            + f"累计 {exp['loot']}｜全服锚定度 {g['rift']['anchor']}%")
    if exp["depth"] >= MAX_DEPTH:
        return True, body + "\n" + _payout(g, doc, rift, "cleared")
    return True, body + f"\n继续：#裂界{route_name}，或换路线 / #撤离裂界"


def withdraw(g: dict, doc: Any, now: float) -> tuple[bool, str]:
    exp = expedition_of(doc)
    if not exp or exp.get("status") != "active":
        return False, "你没有进行中的裂界远征。"
    rift = (g or {}).get("rift") or {"name": exp["id"], "anchor": 0}
    return True, _payout(g, doc, rift, "withdrew")


# ---------------------------------------------------------------- 兑换

def exchange(doc: Any, name: str) -> tuple[bool, str, dict]:
    item = EXCHANGES.get(name)
    if not item:
        return False, f"可兑换：{'、'.join(EXCHANGES)}（#界源兑换 名字）", {}
    have = source_of(doc)
    if have < item["cost"]:
        return False, f"「{name}」需界源 {item['cost']}（当前 {have}）。", {}
    doc.ext["rift_source"] = have - item["cost"]
    return True, (f"【界源兑换】{name} ×{item['qty']}，界源 -{item['cost']}"
                  f"（剩余 {source_of(doc)}）"), {name: item["qty"]}


# ---------------------------------------------------------------- 文案

def fmt_left(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h} 小时 {m} 分" if h else f"{m} 分"


def status_text(g: Mapping, doc: Any, now: float) -> str:
    rift = current_rift(g, now)
    lines = ["--- 裂界副本 ---"]
    if not rift:
        lines.append("当前没有开启中的裂界。")
    else:
        left = float(rift["expires_at"]) - now
        lines += [
            f"裂界：{rift['name']}（{rift['plane']}）",
            f"位置：{rift['location']}（{rift['x']}, {rift['y']}）",
            f"剩余：{fmt_left(left)}｜全服锚定度：{int(rift.get('anchor', 0))}%",
            f"参与者：{len(rift.get('participants') or [])} 人",
        ]
    exp = expedition_of(doc)
    if exp and exp.get("status") == "active":
        lines.append(f"你的远征：第 {int(exp.get('depth', 0))}/{MAX_DEPTH} 层｜战利品 {int(exp.get('loot', 0))}")
    else:
        last = doc.ext.get("rift_last")
        if isinstance(last, Mapping):
            lines.append(f"上次：{last.get('name')}·{last.get('status')}，界源 +{last.get('source')}")
        else:
            lines.append("你的远征：未进入（#进入裂界）")
    lines.append(f"界源：{source_of(doc)}")
    lines.append("路线：" + "｜".join(f"{k}（{v['desc']}）" for k, v in ROUTES.items()))
    lines.append("兑换：#界源兑换 名字（" + "、".join(f"{k} {v['cost']}" for k, v in EXCHANGES.items()) + "）")
    return "\n".join(lines)
