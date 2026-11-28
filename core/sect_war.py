"""圣地大战（原版 RealmEvents sectWar 事件移植，挂 realm_event.active[*].war）。

原版要点：
- 战场行动五种：正面攻伐(军势2)/护送资源(辎重2,封印0.5)/源术勘脉(真相2,封印1)/
  潜入夺证(真相3,封印0.5)/救援伤员(辎重1,军势0.5,封印0.5)，贡献各 2；
  威力 = 玩家权柄钳 1-12，表盘增益与贡献按威力放大。
- 每人 5 次行动、同名行动不可重复；中立修士不可「正面攻伐/护送资源」。
- 表盘：军势/辎重/真相/封印（0-100）；真相 25/50/75 揭示战场线索（矿脉/禁区两套文案）。
- 决议投票：真相 ≥50 开放（矿脉战：继续争夺/停战查真/联军攻禁区；
  禁区战：强攻禁区/稳固封印/撤离伤员），可改票，最终票多者定。
- 结算：矿脉战按攻/守贡献分定胜负（或决议改写结局）；战果按贡献结算。

移植口径（差异已标注）：
- 事件挂在 realm_event.active[*].war（与 contest 同模式），坐标抵达用本地 reach()。
- 结算奖励：原版按贡献发放（明细随结算时点变化）；本移植按贡献占比折算
  修为+灵石，贡献榜首追加 战功徽记×1（差异已标注）。
- 支援（源石资助）与站队后改队未搬（原版支助为独立指令族）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

MAX_ACTIONS = 5
MAX_SUPPORTS = 3
MIN_SUPPORT = 1_000
MAX_SUPPORT = 1_000_000_000_000
POWER_CAP = (1, 12)
CLAMP = (0, 100)

ACTIONS: dict[str, dict[str, float]] = {
    "正面攻伐": {"military": 2, "contribution": 2},
    "护送资源": {"supplies": 2, "seal": 0.5, "contribution": 2},
    "源术勘脉": {"truth": 2, "seal": 1, "contribution": 2},
    "潜入夺证": {"truth": 3, "seal": 0.5, "contribution": 2},
    "救援伤员": {"supplies": 1, "military": 0.5, "seal": 0.5, "contribution": 2},
}
SIDE_LOCKED = ("正面攻伐", "护送资源")          # 中立修士不可执行

CLUES: dict[str, tuple[tuple[int, str], ...]] = {
    "mine": (
        (25, "矿脉深处存在人为凿开的古老甬道，双方最初得到的矿图都不完整。"),
        (50, "所谓神源龙脉其实是一处封印节点，争夺正在削弱地下帝阵。"),
        (75, "封印另一端传来禁区气息；继续大战，可能唤醒沉睡在黑暗中的存在。"),
    ),
    "frontier": (
        (25, "裂缝会吞噬神源并反哺禁区，寻常封禁只能延缓扩张。"),
        (50, "联军发现一座血祭古坛，破坏它可以切断裂缝与禁区深处的联系。"),
        (75, "古坛背后有至尊意志短暂复苏，联军必须在其完全醒来前作出决断。"),
    ),
}

DECISIONS: dict[str, tuple[str, ...]] = {
    "mine": ("继续争夺", "停战查真", "联军攻禁区"),
    "frontier": ("强攻禁区", "稳固封印", "撤离伤员"),
}

METERS = ("military", "supplies", "truth", "seal")
METER_NAMES = {"military": "军势", "supplies": "辎重", "truth": "真相", "seal": "封印"}


def create(mode: str, attacker: Mapping, defender: Mapping,
           coalition: Mapping | None = None, timestamp: float = 0.0) -> dict[str, Any]:
    frontier = mode == "frontier"
    return {
        "mode": mode,
        "status": "open",
        "phase": "禁区外缘联军" if frontier else "神源龙脉争夺",
        "opened_at": float(timestamp),
        "max_actions": MAX_ACTIONS,
        "sides": ({"coalition": {"name": "圣地联军", "members": list(coalition or [])},
                   "neutral": {"name": "观望修士"}} if frontier else
                  {"attacker": dict(attacker or {"name": "攻方圣地"}),
                   "defender": dict(defender or {"name": "守方圣地"}),
                   "neutral": {"name": "中立修士"}}),
        "scores": ({"coalition": 0, "neutral": 0} if frontier else
                   {"attacker": 0, "defender": 0, "neutral": 0}),
        "meters": {"military": 0, "supplies": 0, "truth": 0, "seal": 0},
        "participants": {}, "decision_votes": {}, "clues": [],
        "action_log": [], "support_log": [], "rewarded": [], "outcome": None, "settled_at": 0,
    }


def _clamp(v: float) -> int:
    return max(CLAMP[0], min(CLAMP[1], round(v or 0)))


def _clamp_power(power: Any) -> int:
    try:
        p = int(round(float(power or 1)))
    except (TypeError, ValueError):
        p = 1
    return max(POWER_CAP[0], min(POWER_CAP[1], p))


def join(war: dict, uid: str, name: str, side: str) -> tuple[bool, str]:
    if war.get("status") != "open":
        return False, "本次圣地大战已经结束。"
    allowed = (["coalition", "neutral"] if war.get("mode") == "frontier"
               else ["attacker", "defender", "neutral"])
    if side not in allowed:
        return False, f"站队无效。可选：{'/'.join(allowed)}（{war.get('mode')} 战场）"
    parts = war.setdefault("participants", {})
    key = str(uid)
    if key in parts:
        return False, "你已加入本次圣战。"
    parts[key] = {"uid": key, "name": str(name or key), "side": side,
                  "contribution": 0, "actions": [],
                  "support_count": 0, "source_stones": 0,
                  "joined_at": __import__("time").time()}
    return True, f"【圣战站队】你已加入「{war['sides'][side]['name']}」阵营（{side}）。"


def _reveal_clues(war: dict) -> list[str]:
    mode = war.get("mode") or "mine"
    truth = int(war["meters"]["truth"])
    revealed = [c[1] for c in CLUES.get(mode, ()) if truth >= c[0]
                and c[1] not in war.setdefault("clues", [])]
    war.setdefault("clues", []).extend(revealed)
    return revealed


def record_action(war: dict, uid: str, action: str, power: Any) -> tuple[bool, str]:
    """#调查战端（=潜入夺证）/#战场行动 行动名。"""
    if war.get("status") != "open":
        return False, "本次圣地大战已经结束。"
    parts = war.setdefault("participants", {})
    p = parts.get(str(uid))
    if not p:
        return False, "你尚未加入本次圣战（先 #圣战站队）。"
    effect = ACTIONS.get(action)
    if not effect:
        return False, f"未知的战场行动「{action}」。可选：{'、'.join(ACTIONS)}"
    if len(p.get("actions") or []) >= MAX_ACTIONS:
        return False, "你的五次战场行动已经全部用完。"
    if any(a.get("name") == action for a in (p.get("actions") or [])):
        return False, "这项战场行动你已经完成过了。"
    if p.get("side") == "neutral" and action in SIDE_LOCKED:
        return False, "中立修士不能参加正面攻伐或阵营资源护送，可调查、勘脉或救援。"
    power = _clamp_power(power)
    gains = {}
    for meter in METERS:
        gain = _clamp(round(float(effect.get(meter, 0) or 0) * power))
        if gain:
            war["meters"][meter] = _clamp(float(war["meters"][meter]) + gain)
        gains[meter] = gain
    contribution = max(1, round(float(effect.get("contribution", 1) or 1) * power))
    p["contribution"] = int(p.get("contribution", 0) or 0) + contribution
    p.setdefault("actions", []).append({"name": action, "contribution": contribution})
    war["scores"][p["side"]] = int(war["scores"].get(p["side"], 0) or 0) + contribution
    war.setdefault("action_log", []).append(
        {"uid": str(uid), "name": p["name"], "side": p["side"],
         "action": action, "contribution": contribution})
    if len(war["action_log"]) > 100:
        war["action_log"] = war["action_log"][-100:]
    new_clues = _reveal_clues(war)
    meters_line = "｜".join(f"{METER_NAMES[m]} {int(war['meters'][m])}%"
                            for m in METERS)
    lines = [f"【战场行动·{action}】",
             f"本次获得战功：{contribution}｜个人总贡献：{p['contribution']}",
             meters_line]
    if new_clues:
        lines.append("【战场转折】")
        lines += [f"· {c}" for c in new_clues]
    if int(war["meters"]["truth"]) >= 50:
        lines.append("真相已经足够清晰，可以发送 #提交战场决议 决议名 查看并提交战场决议。")
    return True, "\n".join(lines)


def submit_decision(war: dict, uid: str, choice: str) -> tuple[bool, str]:
    if war.get("status") != "open":
        return False, "本次圣地大战已经结束。"
    p = (war.get("participants") or {}).get(str(uid))
    if not p:
        return False, "你尚未加入本次圣战（先 #圣战站队）。"
    if int(war["meters"]["truth"]) < 50:
        return False, "真相进度达到50%后才能提交战场决议。"
    choices = DECISIONS.get(war.get("mode") or "mine", ())
    if choice not in choices:
        return False, f"这项决议不适用于当前战场。可选：{'/'.join(choices)}"
    war.setdefault("decision_votes", {})[str(uid)] = choice
    return True, (f"【战场决议·已提交】你的选择：{choice}\n"
                  "投票可在事件结束前修改，最终采用票数最多的方案。")


def support(war: dict, uid: str, amount: int, now: float = 0.0) -> tuple[bool, str, dict[str, int]]:
    """#投入战资 源石*数量（对齐原版 RealmEvents.recordSectWarSupport）：最多 3 批，增辎重与贡献。"""
    if war.get("status") != "open":
        return False, "本次圣地大战已经结束。", {}
    parts = war.setdefault("participants", {})
    p = parts.get(str(uid))
    if not p:
        return False, "你尚未加入本次圣战（先 #圣战站队）。", {}
    if int(p.get("support_count", 0) or 0) >= MAX_SUPPORTS:
        return False, f"每场圣战最多投入 {MAX_SUPPORTS} 批战资。", {}
    try:
        amt = int(amount)
    except (TypeError, ValueError):
        amt = 0
    if amt < MIN_SUPPORT or amt > MAX_SUPPORT:
        return False, f"单次战资须为 {MIN_SUPPORT:,} 至 {MAX_SUPPORT:,} 源石。", {}
    contribution = max(1, min(30, round(math.log10(amt / 1000 + 1) * 6)))
    supplies = max(1, round(contribution * 1.5))
    seal = max(1, round(contribution / 3)) if war.get("mode") == "frontier" else 0
    p["source_stones"] = int(p.get("source_stones", 0) or 0) + amt
    p["support_count"] = int(p.get("support_count", 0) or 0) + 1
    p["contribution"] = int(p.get("contribution", 0) or 0) + contribution
    war.setdefault("scores", {})
    war["scores"][p["side"]] = int(war["scores"].get(p["side"], 0) or 0) + contribution
    meters = war.setdefault("meters", {"military": 0, "supplies": 0, "truth": 0, "seal": 0})
    meters["supplies"] = _clamp(float(meters.get("supplies", 0) or 0) + supplies)
    if seal:
        meters["seal"] = _clamp(float(meters.get("seal", 0) or 0) + seal)
    war.setdefault("support_log", []).append(
        {"uid": str(uid), "side": p["side"], "amount": amt,
         "contribution": contribution, "supplies": supplies, "seal": seal,
         "at": float(now or __import__("time").time())})
    if len(war["support_log"]) > 100:
        war["support_log"] = war["support_log"][-100:]
    lines = [
        "【圣战战资·交割完成】",
        f"投入源石：{amt:,}（第 {p['support_count']}/{MAX_SUPPORTS} 批）",
        f"增加辎重：+{supplies}%（当前 {meters['supplies']}%）"
        + (f"｜封印：+{seal}%（{meters['seal']}%）" if seal else ""),
        f"获得战功：+{contribution}｜个人总贡献：{p['contribution']}",
    ]
    return True, "\n".join(lines), {"contribution": contribution, "supplies": supplies, "seal": seal}


def _top_votes(war: dict) -> str | None:
    votes = war.get("decision_votes") or {}
    if not votes:
        return None
    counts: dict[str, int] = {}
    for choice in votes.values():
        counts[choice] = counts.get(choice, 0) + 1
    return max(counts, key=lambda c: counts[c])


def settle(war: dict, now: float) -> dict[str, Any]:
    """到期结算：决议改写结局；矿脉战按贡献分定归属。返回 outcome。"""
    if war.get("status") == "settled":
        return dict(war.get("outcome") or {})
    decision = _top_votes(war)
    mode = war.get("mode") or "mine"
    if mode == "frontier":
        success = decision == "强攻禁区" or (decision == "撤离伤员" and False)
        if decision == "撤离伤员":
            outcome = {"type": "frontier_evac", "title": "联军护送众修士安全撤离",
                       "summary": "联军保住主力后撤，但禁区气息仍在外溢。",
                       "winner": "coalition", "decision": decision}
        elif success:
            outcome = {"type": "frontier_success", "title": "禁区裂缝被暂时镇封",
                       "summary": "联军以重大伤亡镇封裂缝，禁区气息暂缓。",
                       "winner": "coalition", "decision": decision}
        else:
            outcome = {"type": "frontier_failure", "title": "禁区裂缝冲破联军封锁",
                       "summary": "联军保住主力后撤，但禁区气息仍在外溢。",
                       "winner": None, "decision": decision or "稳固封印"}
    elif int(war["meters"]["truth"]) >= 50 and decision in ("停战查真", "联军攻禁区"):
        outcome = {"type": "ceasefire" if decision == "停战查真" else "forbidden_coalition",
                   "title": "双方停战共查封印" if decision == "停战查真" else "两大圣地结成禁区联军",
                   "summary": ("双方共同修补帝阵，神源龙脉免于崩毁。" if decision == "停战查真"
                               else "争夺矿脉的兵锋转向禁区外缘，血战暂时止息。"),
                   "winner": "coalition", "decision": decision}
    else:
        atk = int(war["scores"].get("attacker", 0) or 0)
        dfd = int(war["scores"].get("defender", 0) or 0)
        winner = "draw" if atk == dfd else ("attacker" if atk > dfd else "defender")
        winner_name = "双方" if winner == "draw" else war["sides"][winner]["name"]
        outcome = {"type": "draw" if winner == "draw" else "faction_victory",
                   "title": "双方罢兵，矿脉暂归无主" if winner == "draw"
                   else f"{winner_name}控制神源龙脉",
                   "summary": "双方伤亡惨重，只得各自退回山门。" if winner == "draw"
                   else f"{winner_name}夺得矿权与外围帝阵控制权。",
                   "winner": winner, "decision": decision or "继续争夺"}
    war["status"] = "settled"
    war["settled_at"] = float(now)
    war["outcome"] = outcome
    return outcome


def rank(war: Mapping) -> list[dict]:
    rows = [dict(p) for p in (war.get("participants") or {}).values()]
    rows.sort(key=lambda p: (-int(p.get("contribution", 0) or 0),
                             float(p.get("joined_at") or 0)))
    return rows


def settle_rewards(war: Mapping, total_pool: int) -> list[dict[str, Any]]:
    """按贡献占比折算个人奖励（修为+灵石+圣地战功），榜首追加战功徽记。差异已标注。"""
    rows = rank(war)
    if not rows:
        return []
    total = sum(int(p.get("contribution", 0) or 0) for p in rows) or 1
    out = []
    for i, p in enumerate(rows):
        contrib = int(p.get("contribution", 0) or 0)
        share = contrib / total
        exp = int(total_pool * share)
        stones = max(1, int(exp * 0.05))
        merits = max(1, contrib)
        out.append({"uid": p["uid"], "name": p.get("name"), "exp": exp,
                    "stones": stones, "merits": merits, "top": i == 0})
    return out


def ranking_text(war: Mapping, event: Mapping | None = None, my_merits: int = 0) -> str:
    """#查看战场榜：前 10 战功排行 + 结局 + 个人圣地战功余额。"""
    phase = war.get("phase") or "圣地大战"
    lines = [f"【{phase}·战场榜】"]
    if isinstance(event, Mapping) and event.get("location"):
        loc = event["location"]
        if isinstance(loc, Mapping):
            lines.append(f"地点：{loc.get('plane', '')} ({loc.get('x', '?')},{loc.get('y', '?')})")
    rows = rank(war)[:10]
    sides = war.get("sides") or {}
    if not rows:
        lines.append("尚无人留下战功。")
    for i, entry in enumerate(rows, 1):
        side_name = (sides.get(entry.get("side")) or {}).get("name") or entry.get("side") or "中立"
        lines.append(f"{i}. {entry.get('name', entry.get('uid'))}｜{side_name}｜战功 {int(entry.get('contribution', 0) or 0)}")
    outcome = war.get("outcome")
    if isinstance(outcome, Mapping) and outcome.get("title"):
        lines.append(f"结局：{outcome['title']}")
    lines.append(f"个人圣地战功余额：{int(my_merits or 0):,}（#战功商店 查看可兑）")
    return "\n".join(lines)


def panel(war: dict, now: float, event: Mapping | None = None) -> str:
    meters_line = "｜".join(f"{METER_NAMES[m]} {int(war['meters'][m])}%"
                            for m in METERS)
    status = {"open": "进行中", "settled": "已结算"}.get(war.get("status"), war.get("status"))
    lines = [f"--- 圣地大战·{war.get('phase')} ---",
             f"状态：{status}｜阵营：" + "、".join(s["name"] for s in war["sides"].values())]
    if isinstance(event, Mapping) and event.get("expires_at"):
        mins = max(0, int((float(event["expires_at"]) - now) // 60))
        lines.append(f"剩余 {mins // 60} 时 {mins % 60} 分")
    lines.append(f"表盘：{meters_line}")
    scores = war.get("scores") or {}
    lines.append("贡献分：" + "｜".join(f"{war['sides'][k]['name']} {v}"
                                       for k, v in scores.items()))
    votes = war.get("decision_votes") or {}
    if votes:
        lines.append(f"决议票：{len(votes)} 票")
    if int(war["meters"]["truth"]) >= 50:
        lines.append(f"决议可提交：{'/'.join(DECISIONS.get(war.get('mode') or 'mine', ()))}")
    for clue in (war.get("clues") or [])[-3:]:
        lines.append(f"· 线索：{clue}")
    lines.append("动作：#圣战站队 阵营｜#战场行动 行动名（含 #调查战端）｜"
                 "#投入战资 源石*数量｜#提交战场决议 决议名｜#查看战场榜｜#圣战详情")
    return "\n".join(lines)
