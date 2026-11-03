"""彼岸古文明 · 四章贡献链（P2 独立系统）

对位原版 `model/otherShoreAncientEvents.js`(448 行)：
- 四位章节按 order 串行解锁，全服共享一条进度（原版挂在 world.ancientEvents 上）；
- 玩家对「已解锁且未完成」的章节贡献，进度累计到章节阈值即通关，解锁下一章；
- 章节完成后，贡献过该章的玩家可各领一次本章奖励。

shortcut（相对原版）：
- 原版贡献量由真世界扇区战斗结算派生，并带 operationId 幂等回执；本插件没有真世界扇区，
  改为「与章节敌群打一场，按战果折算贡献」，幂等交给 AstrBot 单进程事件循环 + 单行 JSON 保证。
- 原版奖励是「古史/配方/线索/权柄」四类解锁表，这里落成可入纳戒的物品名 + 灵石/修为。
"""

from __future__ import annotations

from typing import Any

from . import battle

VERSION = 1
CHAIN_ID = "other-shore-ancient-civilization"
CONTRIBUTE_CD_SECONDS = 10 * 60
MIN_CONTRIBUTION = 30
MAX_CONTRIBUTION = 120

# order 从 1 开始，必须连续；reward 里的 items 以 (名称, 数量) 表示
CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "qin-qi-refiner-ancestral-court",
        "order": 1,
        "name": "先秦炼气祖庭",
        "coordinate": "7,-3",
        "required": 120,
        "description": "复原先秦炼气士以星辰为炉、以身为种的祖庭古史。",
        "opposition": ("祖庭道火残灵", "裂界守史人"),
        "items": (("先秦炼气古史·祖庭道火录", 1),),
        "stones": 3000,
        "exp": 5000,
    },
    {
        "id": "spirit-rift-source-court",
        "order": 2,
        "name": "灵界裂隙源庭",
        "coordinate": "-9,4",
        "required": 180,
        "description": "沿旧源谱追溯灵界裂隙，拼合彼岸古文明第一次越界的炼制术。",
        "opposition": ("裂界巡猎者", "源庭校正阵"),
        "items": (("炼器配方残卷·裂界归源篇", 1),),
        "stones": 5000,
        "exp": 8000,
    },
    {
        "id": "forbidden-treasure-cleansing-court",
        "order": 3,
        "name": "禁宝清算庭",
        "coordinate": "13,-8",
        "required": 260,
        "description": "攻入清算中枢，截获尚未被无尽商店收录的先天至宝天机。",
        "opposition": ("禁宝司清算舰队", "违禁因果裁定者"),
        "items": (("先天至宝线索·太初界舟", 1),),
        "stones": 8000,
        "exp": 12000,
    },
    {
        "id": "era-overlord-observatory-finale",
        "order": 4,
        "name": "纪元主宰观测台",
        "coordinate": "21,-13",
        "required": 400,
        "description": "切断逻辑彼岸的观测链，同时迎战纪元主宰投影与超维清算者。",
        "opposition": ("纪元主宰·逻辑投影", "超维清算者·断律使"),
        "items": (("纪元主宰观测权柄残片", 1), ("超维清算者断律印记", 1)),
        "stones": 15000,
        "exp": 20000,
    },
)

BY_ORDER = {entry["order"]: entry for entry in CATALOG}
BY_ID = {entry["id"]: entry for entry in CATALOG}


# ---------------------------------------------------------------- 状态

def _blank_record(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "active" if entry["order"] == 1 else "locked",
        "progress": 0,
        "contributions": {},
        "completedAt": None,
        "completedBy": None,
        "claims": {},
    }


def default_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "chainId": CHAIN_ID,
        "events": {entry["id"]: _blank_record(entry) for entry in CATALOG},
        "updatedAt": 0,
    }


def ensure(value: Any) -> dict[str, Any]:
    """把库里可能缺字段/被手改过的 JSON 修复成完整状态。"""
    state = value if isinstance(value, dict) else {}
    state["version"] = VERSION
    state["chainId"] = CHAIN_ID
    events = state.get("events")
    if not isinstance(events, dict):
        events = {}
    for entry in CATALOG:
        record = events.get(entry["id"])
        if not isinstance(record, dict):
            record = _blank_record(entry)
        record["progress"] = max(0, min(entry["required"], int(record.get("progress") or 0)))
        if not isinstance(record.get("contributions"), dict):
            record["contributions"] = {}
        if not isinstance(record.get("claims"), dict):
            record["claims"] = {}
        events[entry["id"]] = record
    state["events"] = events
    state["updatedAt"] = int(state.get("updatedAt") or 0)
    recalculate(state)
    return state


def recalculate(state: dict[str, Any]) -> dict[str, Any]:
    """按 order 串行重算 completed / active / locked 与链条整体状态。"""
    previous_done = True
    completed = 0
    for entry in CATALOG:
        record = state["events"][entry["id"]]
        done = int(record["progress"]) >= entry["required"] or record.get("completedAt")
        if done:
            record["progress"] = entry["required"]
            record["status"] = "completed"
            completed += 1
        elif previous_done:
            record["status"] = "active"
        else:
            record["status"] = "locked"
        previous_done = bool(done)
    state["completedCount"] = completed
    state["activeEventId"] = next(
        (entry["id"] for entry in CATALOG if state["events"][entry["id"]]["status"] == "active"),
        None,
    )
    state["status"] = "completed" if completed == len(CATALOG) else "active"
    return state


def resolve_chapter(keyword: Any) -> dict[str, Any] | None:
    """支持序号 / 章节名 / 部分名 / id。"""
    text = str(keyword or "").strip()
    if not text:
        return None
    if text.isdigit():
        return BY_ORDER.get(int(text))
    if text in BY_ID:
        return BY_ID[text]
    for entry in CATALOG:
        if text == entry["name"] or text in entry["name"]:
            return entry
    return None


def active_chapter(state: dict[str, Any]) -> dict[str, Any] | None:
    return BY_ID.get(state.get("activeEventId") or "")


# ---------------------------------------------------------------- 战斗

def enemy_units(entry: dict[str, Any], stats: Any) -> list[battle.Unit]:
    """按玩家面板推敌群：两只，一攻一守，总量约为玩家的 1.6 倍。"""
    hp = max(1000, int(getattr(stats, "hp", 0) or 0))
    atk = max(100, int(getattr(stats, "atk", 0) or 0))
    defense = max(50, int(getattr(stats, "defense", 0) or 0))
    return [
        battle.Unit(entry["opposition"][0], int(atk * 0.95), int(defense * 0.9), int(hp * 0.85), 0.15),
        battle.Unit(entry["opposition"][1], int(atk * 0.8), int(defense * 1.1), int(hp * 0.75), 0.1),
    ]


def fight_chapter(entry: dict[str, Any], stats: Any, rng: Any) -> dict[str, Any]:
    """连战两场，两场全胜才算推进成功。

    每场都以满血开打（不把上一场的残血带进下一场，否则高境玩家两战必躺），
    最终气血按两场里最惨的剩余比例折算，保留战损的压力。
    """
    full_hp = max(1, int(getattr(stats, "hp", 0) or 0))
    logs: list[str] = []
    wins = 0
    worst_ratio = 1.0
    for unit in enemy_units(entry, stats):
        me = battle.Unit(
            "你",
            int(getattr(stats, "atk", 1)),
            int(getattr(stats, "defense", 0)),
            full_hp,
            float(getattr(stats, "bao", 0.0) or 0.0),
        )
        winner, log, a_hp, _b_hp = battle.spar_full(me, unit, rng)
        if isinstance(log, (list, tuple)):
            logs.extend(str(line) for line in log)
        else:
            logs.append(str(log))
        worst_ratio = min(worst_ratio, max(0.0, min(1.0, int(a_hp) / full_hp)))
        if winner == 0:
            wins += 1
        else:
            break
    return {
        "won": wins == 2,
        "wins": wins,
        "hp_left": max(1, int(full_hp * worst_ratio)),
        "log": "\n".join(logs),
    }


def contribution_amount(entry: dict[str, Any], wins: int, realm_index: int) -> int:
    """两战全胜给满额，一胜给四成；随境界略涨，但不超过章节阈值的 1/3。"""
    if wins <= 0:
        return 0
    base = MIN_CONTRIBUTION + max(0, int(realm_index)) * 2
    if wins == 1:
        base = int(base * 0.4)
    bonus = (entry["order"] - 1) * 10
    return max(1, min(MAX_CONTRIBUTION, entry["required"] // 3, base + bonus))


# ---------------------------------------------------------------- 贡献 / 领取

def contribute(state: dict[str, Any], entry: dict[str, Any], uid: str, name: str,
               amount: int, now: int) -> dict[str, Any]:
    record = state["events"][entry["id"]]
    if record["status"] == "locked":
        return {"ok": False, "reason": "前置章节尚未完成。"}
    if record["status"] == "completed":
        return {"ok": False, "reason": f"「{entry['name']}」已经通关，无需再推进。"}
    applied = max(0, min(int(amount), entry["required"] - int(record["progress"])))
    if applied <= 0:
        return {"ok": False, "reason": "本次没有产生有效贡献。"}
    book = record["contributions"].get(uid)
    if not isinstance(book, dict):
        book = {"playerName": name, "amount": 0, "lastAt": 0}
        record["contributions"][uid] = book
    book["playerName"] = name
    book["amount"] = int(book.get("amount") or 0) + applied
    book["lastAt"] = now
    record["progress"] = int(record["progress"]) + applied
    state["updatedAt"] = now
    finished = record["progress"] >= entry["required"]
    if finished:
        record["status"] = "completed"
        record["completedAt"] = now
        record["completedBy"] = uid
        recalculate(state)
    return {
        "ok": True,
        "applied": applied,
        "progress": record["progress"],
        "required": entry["required"],
        "chapterCompleted": finished,
        "chainCompleted": state.get("status") == "completed",
        "nextEventId": state.get("activeEventId"),
        "playerContribution": book["amount"],
    }


def claim(state: dict[str, Any], entry: dict[str, Any], uid: str, now: int) -> dict[str, Any]:
    record = state["events"][entry["id"]]
    if record["status"] != "completed":
        return {"ok": False, "reason": f"「{entry['name']}」尚未通关。"}
    book = record["contributions"].get(uid)
    if not isinstance(book, dict) or int(book.get("amount") or 0) <= 0:
        return {"ok": False, "reason": "你在本章没有贡献，无法领取。"}
    if record["claims"].get(uid):
        return {"ok": False, "reason": "本章奖励你已经领过了。"}
    record["claims"][uid] = now
    state["updatedAt"] = now
    return {
        "ok": True,
        "items": list(entry["items"]),
        "stones": entry["stones"],
        "exp": entry["exp"],
        "contribution": int(book["amount"]),
    }


# ---------------------------------------------------------------- 文案

_STATUS_MARK = {"completed": "✅", "active": "▶", "locked": "🔒"}


def progress_bar(progress: int, required: int, width: int = 10) -> str:
    ratio = 0.0 if required <= 0 else min(1.0, progress / required)
    filled = int(round(ratio * width))
    return "▰" * filled + "▱" * (width - filled)


def status_text(state: dict[str, Any], uid: str = "") -> str:
    state = ensure(state)
    lines = [f"【彼岸古文明】{state['completedCount']}/{len(CATALOG)} 章已通关", ""]
    for entry in CATALOG:
        record = state["events"][entry["id"]]
        mark = _STATUS_MARK.get(record["status"], "?")
        bar = progress_bar(int(record["progress"]), entry["required"])
        lines.append(f"{mark} {entry['order']}. {entry['name']}（{entry['coordinate']}）")
        lines.append(f"   {bar} {record['progress']}/{entry['required']}")
        if record["status"] == "active":
            lines.append(f"   敌群：{'、'.join(entry['opposition'])}")
        mine = record["contributions"].get(uid) if uid else None
        if isinstance(mine, dict) and int(mine.get("amount") or 0) > 0:
            tail = "（已领）" if record["claims"].get(uid) else "（可领取）" if record["status"] == "completed" else ""
            lines.append(f"   你的贡献：{int(mine['amount'])}{tail}")
    lines.append("")
    active = active_chapter(state)
    if state.get("status") == "completed":
        lines.append("四章已尽，逻辑彼岸的观测链就此断绝。")
    elif active:
        lines.append(f"当前章节：{active['name']} —— #推进古文明事件 {active['order']}")
    lines.append("通关后：#领取古文明奖励 序号")
    return "\n".join(lines)


def brief_text(entry: dict[str, Any], result: dict[str, Any]) -> str:
    return (
        f"【{entry['name']}】贡献 +{result['applied']}\n"
        f"进度：{progress_bar(result['progress'], result['required'])} "
        f"{result['progress']}/{result['required']}"
    )
