"""师徒阶段、原版任务奖励和共享虚影试炼规则。"""

from __future__ import annotations

import math
import random
from typing import Any, Mapping

from . import mingge, motou, physique
from .player import PlayerDoc
from .pvp import sync_health

TRIAL_HP = 100_000_000
TRIAL_MIN_HP = 10_000
TRIAL_ROUNDS = 6
TRIAL_MASTER_DAMAGE_VARIANCE = 50_000_000
TRIAL_MAX_DAMAGE_MULTIPLIER = 5
TRIAL_FAILURE_HP = 0
GRADUATE_STAGE = 6

# level_id / Physique_id 来自原版存档；PlayerDoc 的境界和炼体等级是零基索引。
STAGES: tuple[dict[str, Any], ...] = (
    {"realm": 10, "physique": 10, "task": "学习任意一本功法",
     "exp": 10_000, "xueqi": 10_000, "stones": 10_000, "points": 5, "items": {}},
    {"realm": 18, "physique": 17, "task": "消耗一颗定灵珠显露灵根",
     "exp": 40_000, "xueqi": 40_000, "stones": 40_000, "points": 15,
     "items": {"功法盒": 1, "药水盒": 1}},
    {"realm": 26, "physique": 24, "task": "灵石达到 4,000,000（不消耗）",
     "exp": 50_000, "xueqi": 50_000, "stones": 50_000, "points": 20,
     "items": {"道具盒": 1, "功法盒": 1}},
    {"realm": 34, "physique": 31, "task": "转职且职业等级超过 9 级",
     "exp": 150_000, "xueqi": 150_000, "stones": 150_000, "points": 30,
     "items": {"药水盒": 1, "道具盒": 1}},
    {"realm": 42, "physique": 38, "task": "击败师徒试炼道祖虚影",
     "exp": 250_000, "xueqi": 250_000, "stones": 250_000, "points": 50,
     "items": {"功法盒": 3, "药水盒": 3, "道具盒": 3}},
)


def _legacy(doc: PlayerDoc) -> dict[str, Any]:
    source = doc.ext.get("legacy_source")
    return source if isinstance(source, dict) else {}


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def stage_of(doc: PlayerDoc) -> int:
    stored = doc.ext.get("shitu_stage")
    if stored is not None:
        return min(GRADUATE_STAGE, max(0, _int(stored)))
    return min(GRADUATE_STAGE, max(0, _int(_legacy(doc).get("师徒任务阶段"))))


def _linggen_id(doc: PlayerDoc) -> int:
    snap = doc.ext.get("linggen")
    if isinstance(snap, Mapping):
        return _int(snap.get("id"))
    source = _legacy(doc).get("灵根")
    return _int(source.get("id")) if isinstance(source, Mapping) else 0


def recruitment_error(doc: PlayerDoc) -> str | None:
    """Return the original eligibility error for opening recruitment."""
    if doc.ext.get("shifu"):
        return "等你先出师再来收徒吧。"
    if stage_of(doc) == GRADUATE_STAGE or _legacy(doc).get("师徒任务阶段") == GRADUATE_STAGE:
        return "你已经毕业了，就别来做师徒任务了吧。"
    legacy_lunhui = _int(_legacy(doc).get("lunhui"))
    samsara = _int(physique.state_of(doc).get("samsara"))
    if legacy_lunhui != 9 and samsara != 9 and _linggen_id(doc) != 100999:
        if _linggen_id(doc) != 100999 and not _has_nine_layer_magic(doc):
            return "没有轮回过九世的人不能收徒!"
    return None


def _has_nine_layer_magic(doc: PlayerDoc) -> bool:
    return _int(motou.state_of(doc).get("magic")) >= 9 or _linggen_id(doc) == 100999


def apprentice_error(doc: PlayerDoc) -> str | None:
    """Return the original eligibility error for taking a master."""
    if int(doc.realm_index) >= 50:
        return "你这修为都能当师傅了，拜师？"
    if doc.ext.get("shitu_graduated") or stage_of(doc) == GRADUATE_STAGE:
        return "你曾拜入师门且已出师"
    return None


def _milestone_met(doc: PlayerDoc, stage: int, hp: int) -> bool:
    rule = STAGES[stage - 1]
    if stage == 1:
        return bool(doc.ext.get("gongfa"))
    if stage == 2:
        return _int(_legacy(doc).get("linggenshow", 1)) == 0
    if stage == 3:
        return int(doc.stones) >= 4_000_000
    if stage == 4:
        job = doc.ext.get("occupation", _legacy(doc).get("occupation"))
        has_job = bool(job) and job not in ("0", "0.0", "无业游民")
        return has_job and _int(doc.ext.get("occupation_level", _legacy(doc).get("occupation_level"))) > 9
    return hp == 0


def task_text(doc: PlayerDoc, master: PlayerDoc, hp: int | None = None) -> str:
    """Refresh sticky milestones and return progress for the active disciple."""
    stage = stage_of(doc)
    if stage == GRADUATE_STAGE:
        doc.ext["shitu_stage"] = GRADUATE_STAGE
        return "师徒五阶段任务已完成，你已成功出师。"
    if not doc.ext.get("shifu"):
        return "你还没有正在进行的师徒任务。"
    if stage == 0:
        stage = 1
        doc.ext["shitu_stage"] = stage
        doc.ext["shitu_tasks"] = [1, 1, 1]
    if hp is None:
        hp = trial_hp(master, doc)
    tasks = doc.ext.get("shitu_tasks")
    tasks = list(tasks) if isinstance(tasks, (list, tuple)) else []
    if len(tasks) != 3 or any(_int(status, -1) not in (0, 1, 2) for status in tasks):
        tasks = [1, 1, 1]
    for index, status in enumerate(tasks):
        if status == 1 and _milestone_met(doc, stage, hp):
            tasks[index] = 2
    doc.ext["shitu_stage"] = stage
    doc.ext["shitu_tasks"] = tasks
    rule = STAGES[stage - 1]
    realm = max(0, int(doc.realm_index)) + 1
    body = max(0, int(doc.physique_index)) + 1
    active = ("已完成" if tasks[0] == 2 else
              f"未完成（当前 {realm}，需达到原版境界等级 {rule['realm']}）",
              "已完成" if tasks[1] == 2 else
              f"未完成（当前 {body}，需达到原版炼体等级 {rule['physique']}）",
              "已完成" if tasks[2] == 2 else f"未完成（{rule['task']}）")
    return (f"--- 师徒任务·阶段 {stage}/5 ---\n"
            f"1. 练气等级 ≥{rule['realm']}：{active[0]}\n"
            f"2. 炼体等级 ≥{rule['physique']}：{active[1]}\n"
            f"3. {rule['task']}：{active[2]}\n"
            "三个目标全部完成后，徒弟发送「#提交师徒任务」领取本阶段奖励。")


def trial_hp(master: PlayerDoc, student: PlayerDoc | None = None) -> int:
    """The master owns the shared original boss HP; migrate prior Python snapshots."""
    value = master.ext.get("shitu_trial_hp")
    if value is None and student is not None:
        value = student.ext.get("shitu_trial_hp")
    hp = max(0, _int(value, TRIAL_HP))
    master.ext["shitu_trial_hp"] = hp
    return hp


def reveal_linggen(doc: PlayerDoc) -> tuple[bool, str]:
    """Apply the stage-two original 定灵珠 effect; inventory consumption is atomic at the handler."""
    legacy = doc.ext.setdefault("legacy_source", {})
    if not isinstance(legacy, dict):
        legacy = {}
        doc.ext["legacy_source"] = legacy
    if _int(legacy.get("linggenshow", 1)) == 0:
        return False, "你的灵根已经显露，无需再次使用定灵珠。"
    legacy["linggenshow"] = 0
    return True, f"你眼前一亮，看到了自己的灵根：「{str((doc.ext.get('linggen') or {}).get('name') or '未知')}」。"


def share_trial_hp(master: PlayerDoc, value: int) -> int:
    hp = max(0, int(value))
    master.ext["shitu_trial_hp"] = hp
    return hp


def resolve_trial(actor: PlayerDoc, master: PlayerDoc, attack: int,
                  rng: Any | None = None) -> dict[str, Any]:
    """Resolve the original six-round role split against the master's shared boss."""
    rng = rng or random.Random()
    hp = trial_hp(master, actor if actor.ext.get("shifu") else None)
    learner = bool(actor.ext.get("shifu"))
    rounds = []
    for round_no in range(1, TRIAL_ROUNDS + 1):
        if hp <= 0:
            break
        if learner:
            multiplier = math.floor(rng.random() * TRIAL_MAX_DAMAGE_MULTIPLIER + 0.5)
            damage = max(0, int(attack)) * multiplier
        else:
            mitigation = math.floor(rng.random() * TRIAL_MASTER_DAMAGE_VARIANCE + 0.5)
            damage = max(0, int(attack) - mitigation)
        dealt = min(hp, damage)
        hp = max(0, hp - damage)
        rounds.append(f"第{round_no}回合你对道祖虚影造成{dealt:,}点伤害")
    share_trial_hp(master, hp)
    won = hp == 0
    if not won:
        _, max_hp = _actor_hp = (None, None)
    return {"won": won, "hp": hp, "rounds": rounds, "learner": learner}


def apply_failure_hp(actor: PlayerDoc) -> None:
    max_hp = _int(actor.ext.get("hp_max"))
    sync_health(actor, 0, max_hp)


def eligible_graduation(doc: PlayerDoc, master: PlayerDoc, hp: int | None = None) -> tuple[bool, str]:
    text = task_text(doc, master, hp)
    tasks = doc.ext.get("shitu_tasks") or []
    if stage_of(doc) == GRADUATE_STAGE:
        return False, "你已经成功出师。"
    if len(tasks) != 3 or any(_int(status) != 2 for status in tasks):
        return False, text + "\n你还有任务没完成哦~"
    return True, text


def complete_stage(doc: PlayerDoc, master: PlayerDoc) -> dict[str, Any]:
    """Grant exactly one completed stage and advance its source-of-truth state."""
    stage = stage_of(doc)
    rule = STAGES[stage - 1]
    effects = mingge.effects_of(doc)

    def gain(base: int, key: str) -> int:
        try:
            multiplier = max(0.0, 1.0 + float(effects.get(key, 0) or 0))
        except (TypeError, ValueError):
            multiplier = 1.0
        return max(0, math.floor(base * multiplier))

    granted = {
        "stage": stage,
        "exp": gain(rule["exp"], "修炼加成"),
        "xueqi": int(rule["xueqi"]),
        "stones": gain(rule["stones"], "灵石收益"),
        "points": int(rule["points"]),
        "items": dict(rule["items"]),
        "graduated": stage == len(STAGES),
    }
    doc.exp += granted["exp"]
    doc.ext["xueqi"] = max(0, _int(doc.ext.get("xueqi"))) + granted["xueqi"]
    doc.stones += granted["stones"]
    master.ext["shitu_points"] = max(0, _int(master.ext.get("shitu_points"))) + granted["points"]
    if granted["graduated"]:
        doc.ext["shitu_stage"] = GRADUATE_STAGE
        doc.ext["shitu_graduated"] = True
        doc.ext["shitu_tasks"] = [0, 0, 0]
        master.ext["tudi"] = [str(uid) for uid in master.ext.get("tudi", [])
                               if str(uid) != str(doc.uid)]
        graduates = [str(uid) for uid in master.ext.get("graduated_tudi", [])]
        if str(doc.uid) not in graduates:
            graduates.append(str(doc.uid))
        master.ext["graduated_tudi"] = graduates
        doc.ext["shifu"] = None
    else:
        doc.ext["shitu_stage"] = stage + 1
        doc.ext["shitu_tasks"] = [1, 1, 1]
    return granted


def grant_summary(grant: Mapping[str, Any]) -> str:
    stage = int(grant["stage"])
    lines = [
        f"已完成阶段任务{stage}{'，恭喜你成功出师！' if grant['graduated'] else ''}",
        "获得奖励：",
        f"1. 修为×{int(grant['exp']):,}",
        f"2. 血气×{int(grant['xueqi']):,}",
        f"3. 灵石×{int(grant['stones']):,}",
        f"师傅获得师徒积分×{int(grant['points'])}",
    ]
    if grant["items"]:
        lines.append("徒弟获得：" + "、".join(
            f"{name}×{int(qty)}" for name, qty in grant["items"].items()))
    return "\n".join(lines)

def open_boxes(box_rows: Any, name: str, qty: int, rng: Any | None = None) -> dict[str, Any]:
    """Apply the original weighted box contents to inventory-ready item counts."""
    if qty < 1 or qty > 9_999:
        return {"ok": False, "error": "一次只能打开 1 至 9999 个盒子。", "rewards": {}}
    box = next((row for row in box_rows if isinstance(row, Mapping) and row.get("name") == name), None)
    if box is None or not isinstance(box.get("contents"), list):
        return {"ok": False, "error": f"未知的盒子：{name}。", "rewards": {}}
    rng = rng or random.Random()
    rewards: dict[str, int] = {}
    for _ in range(qty):
        roll = rng.random()
        cumulative = 0.0
        outcome = None
        for entry in box["contents"]:
            try:
                cumulative += max(0.0, float(entry.get("rate") or 0))
            except (TypeError, ValueError):
                continue
            if roll < cumulative:
                outcome = entry
                break
        if outcome is None:
            continue
        items = outcome.get("items")
        if not isinstance(items, list) or not items:
            continue
        item = rng.choice(items)
        item_name = str(item.get("name") or "").strip()
        amount = max(0, _int(item.get("amount", item.get("数量", 1)), 1))
        if item_name and amount:
            rewards[item_name] = rewards.get(item_name, 0) + amount
    return {"ok": True, "error": "", "rewards": rewards}
