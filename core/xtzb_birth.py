"""纯逻辑层：先天至宝公开择主（对齐 model/innateTreasureContest.js）。

状态直接存放在 realm_event.active[*].contest。此模块不做 IO，也不自动装备奖励：
调用方持有事件/玩家事务并负责真实守护战、资源扣款和落库。
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from functools import cmp_to_key
from typing import Any

from .extra_cultivation import level_of as extra_level_of
from .xtzb import ALIASES, CONTESTABLE, PROJECTION_SECONDS, ensure, save, state_of

TREASURE_TRIAL_LIMIT = 3
TREASURE_CONTEST_DURATION = 24 * 60 * 60
TIANJI_INFO_BONUS = 8
DAO_HEARTS = ("镇压诸天", "守护苍生", "参悟大道", "逍遥天地")
TRIAL_TAGS = {"battle": "力", "insight": "悟", "support": "德", "fate": "险"}
ALL_TRIALS = tuple(TRIAL_TAGS)

# 逐件公开画像、天象、试炼偏好、契合道心、禁制答案及封印线索来自原版。
_PROFILES: dict[str, dict[str, Any]] = {
    "混沌珠": {"omen": "混沌无相，万物未生而万象已具。", "favoredTags": ["悟", "险", "德"], "daoHeart": "逍遥天地", "insightOptions": ["归一", "开辟", "流转"], "correctInsight": 0, "clues": ["此宝亲近能从无中见有之人。", "大道无定形，强求反而失其真意。"]},
    "太极图": {"omen": "阴阳二气彼此纠缠，却始终没有真正相融。", "favoredTags": ["悟", "德", "险"], "daoHeart": "参悟大道", "insightOptions": ["阴", "阳", "衡"], "correctInsight": 2, "clues": ["刚柔并济者更易引动道图。", "它所求并非一阴一阳，而是二者归衡。"]},
    "盘古幡": {"omen": "混沌如铁幕压下，唯有一道裂隙贯穿天地。", "favoredTags": ["力", "险", "悟"], "daoHeart": "镇压诸天", "insightOptions": ["固守", "劈开", "绕行"], "correctInsight": 1, "clues": ["此宝不拒绝锋芒毕露之人。", "开天并非蛮力，其中亦有大道轨迹。"]},
    "诛仙四剑": {"omen": "四道杀机纵横交错，阵中却留有一线生门。", "favoredTags": ["力", "险", "悟"], "daoHeart": "镇压诸天", "insightOptions": ["止杀", "困敌", "退避"], "correctInsight": 0, "clues": ["杀伐果决者可闻剑鸣。", "真正的杀剑知晓何时止戈。"]},
    "山河社稷图": {"omen": "图卷中万灵繁衍，山河兴替皆在一念之间。", "favoredTags": ["德", "悟", "险"], "daoHeart": "守护苍生", "insightOptions": ["独占", "共生", "封藏"], "correctInsight": 1, "clues": ["万灵愿意亲近护持山河之人。", "此图重众生，不重一人之得失。"]},
    "天地玄黄玲珑塔": {"omen": "玄黄气垂落万重，任凭劫光冲刷而不动。", "favoredTags": ["德", "悟", "力"], "daoHeart": "守护苍生", "insightOptions": ["攻伐", "守御", "舍弃"], "correctInsight": 1, "clues": ["不争并非怯弱，而是有所守护。", "承受劫难仍不退者最合塔意。"]},
    "东皇钟": {"omen": "钟声未响，四方时空已经凝固。", "favoredTags": ["力", "德", "悟"], "daoHeart": "镇压诸天", "insightOptions": ["镇", "破", "遁"], "correctInsight": 0, "clues": ["它欣赏能够定鼎秩序之人。", "钟声为镇世而鸣，并非只为杀伐。"]},
    "混沌钟": {"omen": "钟体外日月星辰流转，钟内地水火风反复开灭。", "favoredTags": ["力", "悟", "险"], "daoHeart": "镇压诸天", "insightOptions": ["静止", "开灭", "隐匿"], "correctInsight": 1, "clues": ["敢在开灭之间前行者可得回应。", "攻守一体，方为混沌钟的真意。"]},
    "六道轮回盘": {"omen": "六道轮转不息，每一道生门之后皆藏死意。", "favoredTags": ["悟", "德", "险"], "daoHeart": "守护苍生", "insightOptions": ["永生", "轮回", "寂灭"], "correctInsight": 1, "clues": ["它看重知生死而不滥掌生死之人。", "轮回不是终点，而是众生再行一步。"]},
    "炼妖壶": {"omen": "壶中万灵气息交融，却没有任何一道气息被彻底抹去。", "favoredTags": ["悟", "险", "德"], "daoHeart": "逍遥天地", "insightOptions": ["吞噬", "融合", "禁锢"], "correctInsight": 1, "clues": ["它偏爱理解万灵变化之人。", "造化在融合，不在单纯吞噬。"]},
    "崆峒印": {"omen": "人道气运如长河汇聚，亿万呼声共同托起古印。", "favoredTags": ["德", "力", "悟"], "daoHeart": "守护苍生", "insightOptions": ["一人", "宗门", "众生"], "correctInsight": 2, "clues": ["独强不足以承人皇之重。", "众生愿力才是古印真正的根基。"]},
}
_DEFAULT_PROFILE = {"omen": "先天气机沉浮不定，似在审视每一位来者。", "favoredTags": ["力", "悟", "德"], "daoHeart": "参悟大道", "insightOptions": ["强取", "参悟", "守候"], "correctInsight": 1, "clues": ["器灵并不只看境界高低。", "顺应其性情比强取更易得到认可。"]}


def get_profile(treasure_name: str) -> dict[str, Any]:
    """返回原版画像的独立副本；未知名称使用原版通用画像。"""
    return dict(_PROFILES.get(ALIASES.get(str(treasure_name or ""), str(treasure_name or "")), _DEFAULT_PROFILE))


def contest_create(treasure_name: str, event_seed: Any = "", now: float | None = None) -> dict[str, Any]:
    now = _now(now)
    return {"version": 1, "status": "open", "startedAt": now,
            "sealProgress": 0, "participants": {}, "rewardedQqs": [],
            "eventSeed": str(event_seed), "profile": {"omen": get_profile(treasure_name)["omen"]}}


def _now(value: float | None) -> float:
    import time
    return time.time() if value is None else float(value)


def _contest_is_open(contest: Mapping, now: float | None = None,
                     expires_at: float | None = None) -> bool:
    if contest.get("status") != "open":
        return False
    deadline = expires_at
    if deadline is None:
        deadline = contest.get("expires_at", contest.get("expiresAt"))
    return deadline is None or float(deadline or 0) > _now(now)


def _participant(contest: Mapping, uid: Any) -> dict[str, Any] | None:
    row = (contest.get("participants") or {}).get(str(uid))
    return row if isinstance(row, dict) else None


def contest_join(contest: dict[str, Any], uid: Any, name: str,
                 now: float | None = None, expires_at: float | None = None) -> dict[str, Any]:
    if not _contest_is_open(contest, now, expires_at):
        deadline = expires_at if expires_at is not None else contest.get("expires_at", contest.get("expiresAt"))
        return {"ok": False, "reason": "expired" if deadline is not None and float(deadline) <= _now(now) else "closed"}
    key = str(uid)
    participants = contest.setdefault("participants", {})
    if key in participants:
        return {"ok": False, "reason": "duplicate", "participant": participants[key]}
    participant = {"qq": key, "name": str(name or key), "joinedAt": _now(now),
                   "trials": {}, "trialScore": 0, "contribution": 0, "daoHeart": ""}
    participants[key] = participant
    return {"ok": True, "participant": participant}


def get_revealed_clues(treasure_name: str, seal_progress: int | float) -> list[str]:
    count = 2 if float(seal_progress or 0) >= 75 else 1 if float(seal_progress or 0) >= 25 else 0
    return list(get_profile(treasure_name)["clues"][:count])


def support_contribution(resource_name: str, amount: int, rarity: int = 0) -> int | None:
    """按原版 #护持天地灵脉 的源石/材料公式算贡献；返回 None 表示输入不合法。"""
    try:
        amount = int(amount)
        rarity = int(rarity)
    except (TypeError, ValueError, OverflowError):
        return None
    if amount < 1:
        return None
    if resource_name == "源石":
        return min(10, math.ceil(amount / 200_000)) if 10_000 <= amount <= 2_000_000 else None
    return min(10, 1 + math.floor(math.log10(amount)) + max(0, rarity))


def contest_trial(contest: dict[str, Any], treasure_name: str, uid: Any,
                  trial: str, options: Mapping[str, Any] | None = None,
                  rng: Any = random) -> dict[str, Any]:
    """结算一项试炼；战斗由调用方真实执行后通过 battleWon 回传。"""
    options = options or {}
    if not _contest_is_open(contest, options.get("now"), options.get("expires_at")):
        return {"ok": False, "reason": "closed"}
    player = _participant(contest, uid)
    if not player:
        return {"ok": False, "reason": "not_joined"}
    if trial not in TRIAL_TAGS:
        return {"ok": False, "reason": "invalid_trial"}
    trials = player.setdefault("trials", {})
    if trial in trials:
        return {"ok": False, "reason": "duplicate_trial"}
    if len(trials) >= TREASURE_TRIAL_LIMIT:
        return {"ok": False, "reason": "limit"}

    profile = get_profile(treasure_name)
    score = progress = 0
    detail = ""
    health_penalty_rate = 0.0
    if trial == "battle":
        difficulty = {"普通": (0.9, 12, 7, 0.12), "凶险": (0.7, 17, 9, 0.22), "绝境": (0.45, 20, 12, 0.35)}.get(options.get("difficulty"))
        if not difficulty:
            return {"ok": False, "reason": "invalid_option"}
        chance, win_score, win_progress, fail_penalty = difficulty
        health_ratio = min(1.0, max(0.0, float(options.get("healthRatio", 0) or 0)))
        chance = max(0.15, chance - (1 - health_ratio) * 0.25)
        external_battle = isinstance(options.get("battleWon"), bool)
        won = options["battleWon"] if external_battle else rng.random() < chance
        score = win_score if won else max(4, math.floor(win_score * 0.4))
        progress = win_progress if won else 4
        health_penalty_rate = 0 if external_battle else (0.05 if won else fail_penalty)
        detail = (f"你通过了{options['difficulty']}守护灵试炼。" if won
                  else f"你败于{options['difficulty']}守护灵，但仍带回部分破封道痕。")
    elif trial == "insight":
        choice_index = profile["insightOptions"].index(options.get("choice")) if options.get("choice") in profile["insightOptions"] else -1
        if choice_index < 0:
            return {"ok": False, "reason": "invalid_option"}
        correct = choice_index == profile["correctInsight"]
        score, progress = (20, 10) if correct else (9, 6)
        detail = "先天禁制与你的答案共鸣，显露出完整道纹。" if correct else "禁制并未完全认可答案，只逸散出少量道纹。"
    elif trial == "support":
        try:
            contribution = min(10, max(1, int(options.get("contribution", 0))))
        except (TypeError, ValueError, OverflowError):
            return {"ok": False, "reason": "invalid_option"}
        score = 18
        progress = 8 + math.ceil(contribution / 2)
        player["contribution"] = min(10, int(player.get("contribution", 0) or 0) + contribution)
        detail = f"你以{options.get('resourceLabel') or '资源'}护住灵脉，获得{contribution}点破封贡献。"
    else:
        roll = rng.random()
        if roll < 0.2:
            score, progress, health_penalty_rate = 6, 5, 0.3
            detail = "命运乱流骤然反噬，你负伤脱身，只截留少量道痕。"
        elif roll < 0.8:
            score, progress, health_penalty_rate = 14, 9, 0.1
            detail = "你穿过一段破碎未来，带回了完整的命运道痕。"
        else:
            score, progress = 20, 13
            detail = "乱流深处的器灵投影主动与你同行，留下罕见机缘。"

    completed_at = _now(options.get("now"))
    trial_result = {"tag": TRIAL_TAGS[trial], "score": score, "detail": detail, "completedAt": completed_at}
    trials[trial] = trial_result
    player["trialScore"] = min(60, int(player.get("trialScore", 0) or 0) + score)
    before = int(contest.get("sealProgress", 0) or 0)
    contest["sealProgress"] = min(100, before + progress)
    milestones = [value for value in (25, 50, 75, 100) if before < value <= contest["sealProgress"]]
    return {"ok": True, "score": score, "progress": progress, "detail": detail,
            "healthPenaltyRate": health_penalty_rate, "milestones": milestones,
            "trial": trial_result, "participant": player, "sealProgress": contest["sealProgress"]}


def contest_vow(contest: dict[str, Any], uid: Any, choice: str,
                now: float | None = None, expires_at: float | None = None) -> dict[str, Any]:
    if not _contest_is_open(contest, now, expires_at):
        return {"ok": False, "reason": "closed"}
    player = _participant(contest, uid)
    if not player:
        return {"ok": False, "reason": "not_joined"}
    if len(player.get("trials") or {}) < TREASURE_TRIAL_LIMIT:
        return {"ok": False, "reason": "trials_required"}
    if choice not in DAO_HEARTS:
        return {"ok": False, "reason": "invalid_option"}
    if player.get("daoHeart"):
        return {"ok": False, "reason": "duplicate"}
    player["daoHeart"] = choice
    player["daoHeartAt"] = _now(now)
    return {"ok": True, "participant": player}


def _hash_luck(value: Any) -> int:
    value_hash = 2166136261
    for char in str(value):
        value_hash ^= ord(char)
        value_hash = (value_hash * 16777619) & 0xFFFFFFFF
        if value_hash >= 0x80000000:
            value_hash -= 0x100000000
    return abs(value_hash) % 6


def _locale_compare(left: str, right: str) -> int:
    # QQ 通常为数字；字典序作为跨主机确定性 tie-break。
    return (left > right) - (left < right)


def contest_rank(contest: Mapping[str, Any], treasure_name: str,
                 event_seed: Any = "") -> list[dict[str, Any]]:
    profile = get_profile(treasure_name)
    buyer_uid = str((contest.get("tianjiBuyer") or {}).get("qq") or "")
    rankings = []
    for player in (contest.get("participants") or {}).values():
        trials = player.get("trials") or {}
        if len(trials) != TREASURE_TRIAL_LIMIT or not player.get("daoHeart"):
            continue
        route_affinity = min(15, sum(5 for row in trials.values() if row.get("tag") in profile["favoredTags"]))
        heart_affinity = 10 if player["daoHeart"] == profile["daoHeart"] else 3
        affinity = route_affinity + heart_affinity
        luck = _hash_luck(f"{event_seed}:{player.get('qq', '')}")
        trial_score = min(60, int(player.get("trialScore", 0) or 0))
        contribution = min(10, int(player.get("contribution", 0) or 0))
        tianji_bonus = TIANJI_INFO_BONUS if buyer_uid and str(player.get("qq")) == buyer_uid else 0
        rankings.append({"qq": str(player.get("qq", "")), "name": player.get("name", ""),
                         "trialScore": trial_score, "affinity": affinity,
                         "contribution": contribution, "luck": luck,
                         "tianjiBonus": tianji_bonus,
                         "total": trial_score + affinity + contribution + luck + tianji_bonus,
                         "joinedAt": float(player.get("joinedAt", 0) or 0)})
    def compare(a: Mapping, b: Mapping) -> int:
        for left, right in ((b["total"], a["total"]), (b["trialScore"], a["trialScore"]),
                            (a["joinedAt"], b["joinedAt"])):
            if left != right:
                return -1 if left < right else 1
        return _locale_compare(str(a["qq"]), str(b["qq"]))
    return sorted(rankings, key=cmp_to_key(compare))


def contest_settle(contest: dict[str, Any] | None, treasure_name: str,
                   event_seed: Any = "", now: float | None = None,
                   expires_at: float | None = None) -> dict[str, Any]:
    if contest is None:
        return {"ok": False, "reason": "missing"}
    if contest.get("status") == "settled":
        return {"ok": True, "alreadySettled": True,
                "rankings": contest.get("rankings") or [], "winner": contest.get("winner")}
    if _contest_is_open(contest, now, expires_at):
        return {"ok": False, "reason": "open"}
    rankings = contest_rank(contest, treasure_name, event_seed)
    contest["status"] = "settled"
    contest["settledAt"] = _now(now)
    contest["rankings"] = rankings
    contest["winner"] = rankings[0] if rankings else None
    return {"ok": True, "rankings": rankings, "winner": contest["winner"]}


def contest_grant_op(contest: Mapping[str, Any], treasure_name: str, uid: Any,
                     player_doc: Any) -> dict[str, Any]:
    """生成一名已存在真人档案的结算 op；天骄、未参赛者由此显式排除。"""
    key = str(uid)
    if key.startswith("tianjiao:"):
        return {"ok": False, "reason": "tianjiao"}
    entrant = _participant(contest, key)
    if not entrant:
        return {"ok": False, "reason": "not_joined"}
    rankings = contest.get("rankings") or []
    rank_by_uid = {str(row.get("qq")): index for index, row in enumerate(rankings, 1)}
    rank = rank_by_uid.get(key, 0)
    realm_index = max(0, int(getattr(player_doc, "realm_index", 0) or 0))
    physique_index = max(0, int(getattr(player_doc, "physique_index", 0) or 0))
    secret_level = max(1, int(extra_level_of(player_doc, "mijing")))
    realm_power = (realm_index + 1) + (physique_index + 1) + secret_level * 2 + 2
    multiplier = 5 if rank == 1 else 3 if 1 < rank <= 3 else 2 if rank > 3 else 1
    reward = realm_power * 10_000 * multiplier
    traces = 30 if rank == 1 else 20 if rank == 2 else 15 if rank == 3 else 8 if rank else 3
    if int(contest.get("sealProgress", 0) or 0) >= 50:
        traces += 5
    fragments = 10 if rank == 1 else 6 if rank == 2 else 4 if rank == 3 else 2 if rank else 0
    return {"ok": True, "uid": key, "name": entrant.get("name", key),
            "treasure": ALIASES.get(treasure_name, treasure_name),
            "rank": rank or None, "qualified": bool(rank),
            "cultivation_base": reward, "xueqi": reward,
            "resources": {"先天道痕": traces, "灵宝残片": fragments},
            "prize": "本体" if rank == 1 else "投影" if rank in (2, 3) else None}


def grant_treasure(player_doc: Any, world: dict[str, Any], treasure_name: str,
                   rank: int, now: float) -> dict[str, Any]:
    """只更新 xtzb 认主/投影状态；不自动装备，也不覆盖已有本体/投影。"""
    key = ALIASES.get(treasure_name, treasure_name)
    if key not in CONTESTABLE or rank not in (1, 2, 3):
        return {"ok": False, "granted": False, "reason": "invalid_prize"}
    state = state_of(player_doc, now)
    owners = world.setdefault("owners", {})
    owner = owners.get(key)
    projection = state.get("projection") or {}
    if rank == 1:
        if owner:
            return {"ok": True, "granted": False, "reason": "already_owned", "prize": None}
        if key in state.get("owned", []) and key not in projection:
            owners[key] = {"uid": str(player_doc.uid), "name": getattr(player_doc, "name", "") or str(player_doc.uid), "at": now}
            return {"ok": True, "granted": False, "reason": "already_owned", "prize": None}
        owners[key] = {"uid": str(player_doc.uid), "name": getattr(player_doc, "name", "") or str(player_doc.uid), "at": now}
        state.setdefault("owned", []).append(key)
        state.get("projection", {}).pop(key, None)
        save(player_doc, state)
        return {"ok": True, "granted": True, "prize": "本体", "expires_at": None}
    if key in state.get("owned", []) and (key not in projection or float(projection.get(key, 0) or 0) > now):
        return {"ok": True, "granted": False, "reason": "already_owned", "prize": None}
    state.setdefault("owned", []).append(key) if key not in state.get("owned", []) else None
    expires_at = float(now) + PROJECTION_SECONDS
    state.setdefault("projection", {})[key] = expires_at
    save(player_doc, state)
    return {"ok": True, "granted": True, "prize": "投影", "expires_at": expires_at}


def create_guardian(player: Mapping[str, Any], difficulty: str,
                    treasure_name: str = "先天至宝") -> dict[str, Any] | None:
    """按原版三档倍率创建战斗守护灵；战斗引擎由调用方执行。"""
    scale = {"普通": (0.7, 0.7, 0.75), "凶险": (0.95, 0.95, 1.0), "绝境": (1.2, 1.15, 1.25)}.get(difficulty)
    if not scale:
        return None
    attack, defense, hp = scale
    guardian = dict(player)
    guardian.pop("id", None)
    guardian.update({
        "名号": f"{treasure_name}·{difficulty}守护灵",
        "攻击": max(1, math.floor((float(player.get("攻击", 1) or 1)) * attack)),
        "防御": max(1, math.floor((float(player.get("防御", 1) or 1)) * defense)),
        "血量上限": max(1, math.floor((float(player.get("血量上限", 1) or 1)) * hp)),
        "暴击率": 0.05, "暴击伤害": 1.5,
        "灵根": {"name": "先天器灵", "type": "器灵", "法球倍率": 0.1, "攻击": 0, "防御": 0, "生命": 0},
        "法球倍率": 0.1, "学习的功法": [], "当前使用的功法": "", "仙宠": [],
        "分身": [], "当前先天至宝": "", "先天权柄": {},
    })
    guardian["当前血量"] = guardian["血量上限"]
    return guardian


def inject_tianjiao_contestants(contest: dict[str, Any], treasure_name: str,
                                tianjiao_list: Sequence[Mapping[str, Any]],
                                options: Mapping[str, Any] | None = None,
                                rng: Any = random) -> list[dict[str, Any]]:
    """为赛事加入原版规则的独立天骄 AI；不推进破封度，也不产生玩家奖励。"""
    if contest.get("status") != "open":
        return []
    options = options or {}
    profile = get_profile(treasure_name)
    excluded = set(options.get("excludeNames") or [])
    pool = [tj for tj in (tianjiao_list or [])
            if tj.get("名号") and tj.get("名号") not in excluded and float(tj.get("位面", 0) or 0) >= 2]
    if not pool:
        return []
    max_count = min(int(options.get("count") or 3), len(pool))
    count = max_count if max_count <= 2 else 2 + (rng.random() < 0.6)
    # 原版用随机比较器打乱；稳定比较排序保留其“随机排序”行为。
    shuffled = sorted(pool, key=cmp_to_key(lambda _a, _b: -1 if rng.random() < 0.5 else 1))[:int(count)]
    now = float(options.get("now") or _now(None))
    entrants = []
    participants = contest.setdefault("participants", {})
    favored_trials = [trial for trial in ALL_TRIALS if TRIAL_TAGS[trial] in profile["favoredTags"]]
    ordered_trials = favored_trials + [trial for trial in ALL_TRIALS if trial not in favored_trials]
    for tianjiao in shuffled:
        name = str(tianjiao["名号"])
        key = f"tianjiao:{name}"
        if key in participants:
            continue
        trials = {}
        for trial in ordered_trials[:TREASURE_TRIAL_LIMIT]:
            completed_at = _now(None)
            if trial == "battle":
                path_level = max(float(tianjiao.get("mijinglevel_id") or 1), float(tianjiao.get("xiangulevel_id") or 1))
                success = rng.random() < min(0.95, 0.55 + path_level * 0.02)
                score = 16 + math.floor(rng.random() * 4) if success else 4 + math.floor(rng.random() * 4)
                detail = "力压守护灵，势如破竹。" if success else "强攻守护灵，稍落下风。"
            elif trial == "insight":
                correct = rng.random() < 0.65
                score, detail = (18 + math.floor(rng.random() * 2), "一眼洞悉禁制真意。") if correct else (9, "参悟有失，仅得皮毛。")
            elif trial == "support":
                score, detail = 16 + math.floor(rng.random() * 2), "以本源护住灵脉，泽被一方。"
            else:
                roll = rng.random()
                score = 6 if roll < 0.2 else 14 if roll < 0.8 else 20
                detail = "于命运乱流中夺得上苍机缘。" if score >= 20 else "穿越破碎未来，截留道痕。" if score >= 14 else "为命运乱流所扰，负伤而返。"
            trials[trial] = {"tag": TRIAL_TAGS[trial], "score": score, "detail": detail, "completedAt": completed_at}
        raw_score = sum(row["score"] for row in trials.values())
        preferred = profile["daoHeart"]
        dao_heart = preferred if rng.random() < 0.55 else DAO_HEARTS[math.floor(rng.random() * len(DAO_HEARTS))]
        entrant = {"qq": key, "name": name, "joinedAt": now, "trials": trials,
                   "trialScore": max(40, min(60, raw_score)),
                   "contribution": 3 + math.floor(rng.random() * 6),
                   "daoHeart": dao_heart, "isTianjiao": True, "tianjiaoName": name}
        participants[key] = entrant
        entrants.append(entrant)
    return entrants


def is_tianjiao_contestant(uid: Any) -> bool:
    return str(uid or "").startswith("tianjiao:")


def migrate_legacy_birth(world: dict[str, Any], treasure_name: str,
                         now: float | None = None) -> dict[str, Any] | None:
    """把旧 world.birth[宝名] 的持久化报名/试炼迁入新 contest，并留存迁移副本。

    调用方可把返回值挂到对应 RealmEvent 的 event.contest；旧档从活动入口移除，
    副本保存在 world.birth_legacy_archive，重复调用不会重复迁移或发奖。
    """
    name = ALIASES.get(treasure_name, treasure_name)
    births = world.get("birth")
    old = births.get(name) if isinstance(births, dict) else None
    if not isinstance(old, dict):
        return None
    now = _now(now)
    contest = contest_create(name, f"legacy:{name}", float(old.get("opened_at") or now))
    contest["expires_at"] = float(old.get("expires_at") or 0)
    contest["sealProgress"] = 0
    participants = contest["participants"]
    tag_by_legacy = {"守护灵": "battle", "先天禁制": "insight", "天地灵脉": "support", "命运乱流": "fate"}
    for uid, old_trials in (old.get("trials") or {}).items():
        if not isinstance(old_trials, Mapping):
            continue
        trials = {}
        for legacy_name, score in old_trials.items():
            trial = tag_by_legacy.get(legacy_name)
            if trial and len(trials) < TREASURE_TRIAL_LIMIT:
                trials[trial] = {"tag": TRIAL_TAGS[trial], "score": int(score or 0),
                                 "detail": "旧版择主存档迁移记录。",
                                 "completedAt": float(old.get("opened_at") or now)}
        vow = str((old.get("vows") or {}).get(str(uid), ""))
        participants[str(uid)] = {"qq": str(uid), "name": str(uid),
                                  "joinedAt": float(old.get("opened_at") or now),
                                  "trials": trials,
                                  "trialScore": min(60, sum(int(row["score"]) for row in trials.values())),
                                  "contribution": 0, "daoHeart": vow if vow in DAO_HEARTS else ""}
    settled = bool(old.get("settled")) or float(old.get("expires_at") or 0) <= now
    if settled:
        contest["status"] = "settled"
        contest["settledAt"] = float(old.get("expires_at") or now)
        contest["rankings"] = []
        contest["winner"] = None
    archive = world.setdefault("birth_legacy_archive", {})
    archive[name] = {**old, "migrationVersion": 2, "migratedAt": now}
    births.pop(name, None)
    if not births:
        world.pop("birth", None)
    return contest


# Earlier Python call sites used “birth” terminology. These direct aliases ease the
# main.py transition while keeping all contest data in the event-owned dictionary.
create_contest = contest_create
join_contest = contest_join
perform_treasure_trial = contest_trial
place_treasure_dao_heart = contest_vow
rank_treasure_contest = contest_rank
settle_treasure_contest = contest_settle
