"""还原版切磋技能对局（原版 apps/Battle/biwu.js 机制）。

原版 10 技能只写死在 biwu.js 的名单里，`data.jineng` 从未定义，所以效果数值是
本移植自定的（见下表），机制按原版代码分支还原：

- 每人开场带同一套 10 技能，战前 `#选择技能 1,2,3` 选 3 个进场
- 每回合双方各行动一次（速度高者先手）：放一个技能 + 照常普攻
- 技能必中（原版切磋无触发概率判定），`pr` 是效果比例不是概率
- `cd` 按回合递减，`last` 是效果持续回合数
- 超时未选按普攻结算

shortcut: 10 条数值无上游出处（data.jineng 缺失），按同档位技能手感自定；
原版减攻/减防是永久累乘（后期攻击趋零），这里改成按 last 到期恢复。
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

from .. import battle

TURN_SECONDS = 60          # 单回合决策窗口（原版 40s，放宽到 60s）
MAX_ROUNDS = 100
PICK_LIMIT = 3

# (name, cd, last, pr, kind)  kind: seal/heal_both/heal_self/hot/atk_down/def_down/crit_zero/dmg_up
SKILLS: tuple[dict[str, Any], ...] = (
    {"name": "四象封印", "cd": 4, "last": 1, "pr": 0.0, "kind": "seal",
     "msg": "四象封印落下，四象之力锁死对方神通！"},
    {"name": "桃园结义", "cd": 5, "last": 0, "pr": 0.15, "kind": "heal_both",
     "msg": "桃园之谊化作暖流，双方气血同升！"},
    {"name": "长生诀", "cd": 4, "last": 0, "pr": 0.20, "kind": "heal_self",
     "msg": "长生诀运转，生机自涌！"},
    {"name": "祝水咒", "cd": 4, "last": 2, "pr": 0.08, "kind": "hot",
     "msg": "水神洗礼加身，伤势持续平复。"},
    {"name": "阴风蚀骨", "cd": 3, "last": 2, "pr": 0.12, "kind": "atk_down",
     "msg": "阴风蚀骨，对方攻势被侵蚀！"},
    {"name": "万年俱灰", "cd": 3, "last": 2, "pr": 0.10, "kind": "atk_down",
     "msg": "万年俱灰之意压落，对方战意消沉！"},
    {"name": "心烦意乱", "cd": 3, "last": 2, "pr": 0.12, "kind": "def_down",
     "msg": "心烦意乱，对方守势散乱！"},
    {"name": "失魂落魄", "cd": 3, "last": 2, "pr": 0.10, "kind": "def_down",
     "msg": "失魂落魄，对方护体真元松动！"},
    {"name": "玄冰封印", "cd": 4, "last": 1, "pr": 0.0, "kind": "crit_zero",
     "msg": "玄冰封印冻结气机，对方再难打出暴击！"},
    {"name": "诛仙三剑", "cd": 3, "last": 2, "pr": 0.30, "kind": "dmg_up",
     "msg": "诛仙剑影临身，锋芒大盛！"},
)
BY_NAME = {s["name"]: s for s in SKILLS}


def _side(uid: str, name: str, atk: int, defense: int, hp: int, bao: float,
          orb: float = 0.0) -> dict[str, Any]:
    return {
        "uid": uid, "name": name,
        "atk": max(1, int(atk)), "defense": max(1, int(defense)),
        "hp": int(hp), "hp_max": int(hp), "bao": float(bao or 0.0),
        "orb": float(orb or 0.0),
        "picks": [], "pick_done": False,
        "cd": {s["name"]: 0 for s in SKILLS},
        # buff 值统一为 {"v": 比例, "until": 末回合}；同键取大取远
        "buff": {},
    }


def new_duel(uid_a: str, name_a: str, stats_a: Mapping[str, Any],
             uid_b: str, name_b: str, stats_b: Mapping[str, Any],
             now: float) -> dict[str, Any]:
    return {
        "id": uid_a, "phase": "pick",
        "a": _side(uid_a, name_a, **stats_a),
        "b": _side(uid_b, name_b, **stats_b),
        "round": 1, "deadline": now + TURN_SECONDS,
        "actions": {}, "log": [], "winner": None, "start": now,
    }


def side_of(duel: Mapping[str, Any], uid: str) -> str | None:
    for k in ("a", "b"):
        if duel[k]["uid"] == uid:
            return k
    return None


def pick(duel: dict[str, Any], uid: str, picks: list[int],
         now: float) -> tuple[bool, str]:
    """#选择技能 1,2,3：索引按 10 技能表，去重、限 3 个。"""
    key = side_of(duel, uid)
    if not key:
        return False, "你不在这一局里。"
    if duel["phase"] != "pick":
        return False, "本局已经开打了。"
    chosen: list[str] = []
    for i in picks:
        if not 1 <= i <= len(SKILLS):
            return False, f"技能序号需在 1~{len(SKILLS)}。"
        name = SKILLS[i - 1]["name"]
        if name not in chosen:
            chosen.append(name)
        if len(chosen) == PICK_LIMIT:
            break
    if not chosen:
        return False, "至少要选一个技能。"
    duel[key]["picks"] = chosen
    duel[key]["pick_done"] = True
    if all(duel[k]["pick_done"] for k in ("a", "b")):
        duel["phase"] = "fight"
        duel["deadline"] = now + TURN_SECONDS
        return True, "双方技能已定，第 1 回合开始！"
    return True, f"已选定：{'、'.join(chosen)}。等对方选技能。"


def auto_pick(duel: dict[str, Any]) -> None:
    """超时未选：取前 3 个技能。"""
    for k in ("a", "b"):
        if not duel[k]["pick_done"]:
            duel[k]["picks"] = [s["name"] for s in SKILLS[:PICK_LIMIT]]
            duel[k]["pick_done"] = True


def act(duel: dict[str, Any], uid: str, idx: int, now: float) -> tuple[bool, str]:
    """#释放技能 N：0 = 普攻，1~3 = 已选的技能。"""
    key = side_of(duel, uid)
    if not key:
        return False, "你不在这一局里。"
    if duel["phase"] != "fight":
        return False, "本局当前不在出招阶段。"
    if key in duel["actions"]:
        return False, "本回合你已经出过手了。"
    if idx == 0:
        name = ""
    else:
        picks = duel[key]["picks"]
        if not 1 <= idx <= len(picks):
            return False, f"本局你只带了 {len(picks)} 个技能，序号需在 0~{len(picks)}。"
        name = picks[idx - 1]
        if int(duel[key]["cd"].get(name, 0) or 0) > 0:
            return False, f"【{name}】还需 {duel[key]['cd'][name]} 回合冷却。"
    duel["actions"][key] = name
    label = name or "普攻"
    return True, f"你本回合出招：{label}。" + ("" if len(duel["actions"]) == 2 else "等对方出招。")


def tick(duel: dict[str, Any], now: float) -> list[str]:
    """惰性推进：补超时动作、结算已齐回合，直到需要人输入或分出胜负。"""
    log: list[str] = []

    def note(text: str) -> None:
        log.append(text)
        duel["log"] = (list(duel.get("log") or []) + [text])[-40:]

    if duel["phase"] == "pick":
        if now >= float(duel["deadline"]) and not all(duel[k]["pick_done"] for k in ("a", "b")):
            auto_pick(duel)
            duel["phase"] = "fight"
            duel["deadline"] = now + TURN_SECONDS
            note("选技能超时，未选者按默认技能进场。")
        else:
            return log
    while duel["phase"] == "fight":
        if len(duel["actions"]) < 2 and now >= float(duel["deadline"]):
            for k in ("a", "b"):
                duel["actions"].setdefault(k, "")
            note("出招超时，未出招者按普攻结算。")
        if len(duel["actions"]) < 2:
            break
        log.extend(resolve_round(duel, random.Random(f"{duel['id']}:{duel['round']}"), now))
        if duel["phase"] != "fight":
            break
    return log


def _active(buff: Mapping[str, Any], key: str, rnd: int) -> float:
    row = buff.get(key)
    if not isinstance(row, Mapping) or int(row.get("until", 0) or 0) < rnd:
        return 0.0
    return float(row.get("v", 0) or 0)


def _stack(side: dict[str, Any], key: str, value: float, until: int) -> None:
    row = side["buff"].get(key)
    best = float(row.get("v", 0) or 0) if isinstance(row, Mapping) else 0.0
    far = int(row.get("until", 0) or 0) if isinstance(row, Mapping) else 0
    side["buff"][key] = {"v": max(best, value), "until": max(far, until)}


def _stats(side: Mapping[str, Any], rnd: int) -> tuple[int, int, float, float]:
    """(攻击, 防御, 暴击率, 伤害倍率)，含到期 buff。"""
    buff = side["buff"]
    atk = side["atk"] * max(0.2, 1 - _active(buff, "atk_down", rnd))
    defense = side["defense"] * max(0.2, 1 - _active(buff, "def_down", rnd))
    bao = 0.0 if _active(buff, "crit_zero", rnd) > 0 else float(side["bao"])
    return int(atk), int(defense), bao, 1 + _active(buff, "dmg_up", rnd)


def _apply_skill(duel: dict[str, Any], key: str, name: str, rnd: int,
                 log: list[str]) -> None:
    me, foe_key = duel[key], "b" if key == "a" else "a"
    foe = duel[foe_key]
    sk = BY_NAME[name]
    kind, pr, last = sk["kind"], float(sk["pr"]), int(sk["last"])
    until = rnd + last          # 本回合已过，从下一回合起算 last 回合
    log.append(f"【{name}】{sk['msg']}")
    if kind == "seal":
        _stack(foe, "sealed", 1.0, until)
    elif kind == "heal_both":
        for side in (me, foe):
            gain = max(1, int(side["hp"] * pr))   # 原版按"当前血量"比例回
            side["hp"] = min(side["hp_max"], side["hp"] + gain)
        log.append(f"双方各回气血 {int(pr * 100)}%。")
    elif kind == "heal_self":
        gain = max(1, int(me["hp_max"] * pr))
        me["hp"] = min(me["hp_max"], me["hp"] + gain)
        log.append(f"{me['name']} 回复 {gain:,} 气血。")
    elif kind == "hot":
        _stack(me, "hot", pr, until)
    elif kind in ("atk_down", "def_down"):
        _stack(foe, kind, pr, until)
        log.append(f"{foe['name']}{'攻击' if kind == 'atk_down' else '防御'}"
                   f"下降 {int(pr * 100)}%，持续 {last} 回合。")
    elif kind == "crit_zero":
        _stack(foe, "crit_zero", 1.0, until)
    elif kind == "dmg_up":
        _stack(me, "dmg_up", pr, until)
        log.append(f"{me['name']} 伤害提升 {int(pr * 100)}%，持续 {last} 回合。")


def _act(duel: dict[str, Any], key: str, rnd: int, log: list[str],
         rng: random.Random) -> str:
    """执行一方行动，返回本回合释放的技能名（普攻返回 ""）。"""
    me, foe_key = duel[key], "b" if key == "a" else "a"
    foe = duel[foe_key]
    if foe["hp"] <= 0 or me["hp"] <= 0:
        return ""
    # 祝水咒等持续回复在自身行动前结算
    hot = _active(me["buff"], "hot", rnd)
    if hot > 0:
        gain = max(1, int(me["hp_max"] * hot))
        me["hp"] = min(me["hp_max"], me["hp"] + gain)
        log.append(f"{me['name']} 受祝水咒滋养，回复 {gain:,} 气血。")

    name = str(duel["actions"].get(key) or "")
    if name and _active(me["buff"], "sealed", rnd) > 0:
        log.append(f"{me['name']} 神通被封，本回合只能普攻。")
        name = ""
    if name:
        _apply_skill(duel, key, name, rnd, log)
        me["cd"][name] = int(BY_NAME[name]["cd"])
    else:
        log.append(f"{me['name']} 未出神通，挥出一记普攻。")

    atk, _my_def, bao, mult = _stats(me, rnd)
    _foe_atk, foe_def, _foe_bao, _foe_mult = _stats(foe, rnd)
    dmg, crit = battle.harm(atk, foe_def, rng, bao)
    # 原版切磋：暴击伤害 + 法球伤害 + 防御*0.1
    orb = int(atk * float(me.get("orb") or 0.0))
    dmg = int((dmg + orb + int(me["defense"] * 0.1)) * mult)
    foe["hp"] = max(0, int(foe["hp"]) - dmg)
    log.append(f"{me['name']} {'暴击' if crit else '普攻'}造成 {dmg:,} 伤害，"
               f"{foe['name']} 剩余 {foe['hp']:,}/{foe['hp_max']:,}。")
    return name


def resolve_round(duel: dict[str, Any], rng: random.Random, now: float) -> list[str]:
    """结算一回合：发起方先手（原版切磋固定 A 先），双方各行动一次。"""
    rnd = int(duel["round"])
    log = [f"—— 第 {rnd} 回合 ——"]
    released = {key: _act(duel, key, rnd, log, rng) for key in ("a", "b")}
    for key in ("a", "b"):
        # 本回合刚放的技能不参与递减，否则 CD 会凭空少一回合
        duel[key]["cd"] = {k: (int(v) if k == released[key] else max(0, int(v) - 1))
                           for k, v in duel[key]["cd"].items()}
        duel[key]["buff"] = {k: v for k, v in duel[key]["buff"].items()
                             if int(v.get("until", 0) or 0) >= rnd}
    duel["actions"] = {}
    a_hp, b_hp = int(duel["a"]["hp"]), int(duel["b"]["hp"])
    if a_hp <= 0 or b_hp <= 0:
        duel["phase"] = "done"
        duel["winner"] = 0 if b_hp <= 0 and a_hp > 0 else 1 if a_hp <= 0 and b_hp > 0 else -1
    elif rnd >= MAX_ROUNDS:
        duel["phase"] = "done"
        ra = a_hp / max(1, int(duel["a"]["hp_max"]))
        rb = b_hp / max(1, int(duel["b"]["hp_max"]))
        duel["winner"] = 0 if ra > rb else 1 if rb > ra else -1
    else:
        duel["round"] = rnd + 1
        duel["deadline"] = max(float(duel.get("deadline", 0) or 0), now) + TURN_SECONDS
    duel["log"] = (list(duel.get("log") or []) + log)[-40:]
    return log


def pool_text() -> str:
    lines = ["【切磋技能表】（#选择技能 1,2,3 选三个进场）"]
    for i, s in enumerate(SKILLS, 1):
        extra = f"持续{s['last']}回合" if s["last"] else "立即"
        pct = f"{int(s['pr'] * 100)}%" if s["pr"] else "—"
        lines.append(f"{i}. {s['name']}｜CD{s['cd']}｜{extra}｜{pct}")
    return "\n".join(lines)


def status_text(duel: Mapping[str, Any], uid: str, now: float) -> str:
    key = side_of(duel, uid)
    me = duel[key] if key else duel["a"]
    foe = duel["b" if key == "a" else "a"]
    lines = [f"【斗法】第 {duel['round']} 回合｜{duel['phase']}",
             f"{me['name']} {me['hp']:,}/{me['hp_max']:,}（{int(me['hp'] / max(1, me['hp_max']) * 100)}%）",
             f"{foe['name']} {foe['hp']:,}/{foe['hp_max']:,}（{int(foe['hp'] / max(1, foe['hp_max']) * 100)}%）"]
    if me["picks"]:
        lines.append("你的技能：" + "｜".join(
            f"{n}(CD{me['cd'].get(n, 0)})" for n in me["picks"]))
    if duel["phase"] == "fight":
        lines.append(f"本回合剩 {max(0, int(float(duel['deadline']) - now))} 秒")
        lines.append("#释放技能 N（0 普攻）")
    if duel["phase"] == "done":
        lines.append(result_text(duel))
    return "\n".join(lines)


def result_text(duel: Mapping[str, Any]) -> str:
    w = duel.get("winner")
    if w == 0:
        return f"胜者：{duel['a']['name']}"
    if w == 1:
        return f"胜者：{duel['b']['name']}"
    if w == -1:
        return "势均力敌，平局。"
    return "本局未结束。"
