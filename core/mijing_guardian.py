"""Persistent pure-state helpers for the original 荒古圣体四极护道 flow.

The caller owns database transactions, guardian resource payment, scheduling, and
message delivery. These helpers only mutate the supplied PlayerDoc.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from typing import Any

from . import extra_cultivation, wallet
from .player import PlayerDoc

PENDING_KEY = "mijing_guardian_pending"
PLEDGE_KEY = "mijing_guardian_pledge"
ATTEMPT_SECONDS = 60.0
FAILURE_COST = 9_999_999


def _ext(doc: PlayerDoc) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        raise TypeError("PlayerDoc.ext must be a dict")
    return ext


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    number = _finite_float(value)
    return int(number) if number is not None and number.is_integer() else None


def pending_attempt(doc: PlayerDoc) -> dict[str, Any] | None:
    """Return a valid unsettled attempt, including one whose deadline has passed."""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return None
    record = ext.get(PENDING_KEY)
    if not isinstance(record, Mapping) or record.get("status") != "pending":
        return None
    attempt_id = record.get("attempt_id")
    deadline = _finite_float(record.get("deadline_at"))
    cost = _integer(record.get("cost"))
    platform_id = record.get("platform_id")
    group_id = record.get("group_id")
    if (not isinstance(attempt_id, str) or not attempt_id.strip()
            or deadline is None or cost is None or cost <= 0
            or not isinstance(platform_id, str) or not platform_id.strip()
            or not isinstance(group_id, str) or not group_id.strip()):
        return None
    return dict(record)


def start_attempt(
    doc: PlayerDoc,
    cost: int,
    now: float,
    platform_id: str,
    group_id: str,
) -> dict[str, Any]:
    """Persist a 60-second level-6 attempt; existing attempts are never replaced.

    `cost` is the already era-adjusted cultivation and blood-qi cost. The caller
    charges source stones when starting and applies the delayed energy cost only
    on successful settlement.
    """
    amount = _integer(cost)
    started_at = _finite_float(now)
    platform = str(platform_id or "").strip()
    group = str(group_id or "").strip()
    if amount is None or amount <= 0:
        raise ValueError("breakthrough cost must be a positive integer")
    if started_at is None:
        raise ValueError("attempt start time must be finite")
    if not platform or not group:
        raise ValueError("platform_id and group_id are required for delayed group settlement")
    if extra_cultivation.level_of(doc, "mijing") != 6:
        raise ValueError("荒古圣体四极护道 attempt requires人体秘境第6境")

    existing = pending_attempt(doc)
    if existing is not None:
        return {**existing, "already_pending": True}

    ext = _ext(doc)
    pledge = ext.get(PLEDGE_KEY)
    guardian_uid = ""
    if isinstance(pledge, Mapping):
        candidate = pledge.get("guardian_uid")
        if isinstance(candidate, str):
            guardian_uid = candidate.strip()

    record: dict[str, Any] = {
        "attempt_id": uuid.uuid4().hex,
        "status": "pending",
        "started_at": started_at,
        "deadline_at": started_at + ATTEMPT_SECONDS,
        "platform_id": platform,
        "group_id": group,
        "cost": amount,
        "guardian_uid": guardian_uid or None,
    }
    ext[PENDING_KEY] = record
    ext.pop(PLEDGE_KEY, None)
    return {**record, "already_pending": False}


def pledge(doc: PlayerDoc, guardian_uid: str, now: float) -> tuple[bool, str]:
    """Record one guardian for a level-6 target without charging the guardian.

    The original allows the guardian flag to be set before the 60-second attempt
    begins, so this stores a durable pre-pledge when no attempt is active.
    """
    guardian = str(guardian_uid or "").strip()
    pledged_at = _finite_float(now)
    if not guardian or pledged_at is None:
        return False, "护道记录无效，请重试。"
    try:
        level = extra_cultivation.level_of(doc, "mijing")
    except (TypeError, ValueError):
        return False, "目标当前无法读取人体秘境境界。"
    if level != 6:
        return False, "目标需处于人体秘境第 6 境，才可接受四极护道。"

    ext = _ext(doc)
    pending = pending_attempt(doc)
    raw_pending = ext.get(PENDING_KEY)
    if pending is not None and isinstance(raw_pending, dict):
        if pledged_at >= float(pending["deadline_at"]):
            return False, "护道时限已过，请等待本次四极天劫结算。"
        if str(pending.get("guardian_uid") or "").strip():
            return False, "本次四极天劫已有护道人。"
        raw_pending["guardian_uid"] = guardian
        raw_pending["pledged_at"] = pledged_at
        return True, "护道凭据已记下；待四极天劫结算后生效。"

    prior = ext.get(PLEDGE_KEY)
    if isinstance(prior, Mapping) and str(prior.get("guardian_uid") or "").strip():
        return False, "目标已有人承诺四极护道。"
    ext[PLEDGE_KEY] = {"guardian_uid": guardian, "pledged_at": pledged_at}
    return True, "护道凭据已记下；目标进入四极天劫后将自动生效。"


def settle_attempt(doc: PlayerDoc, now: float) -> dict[str, Any] | None:
    """Settle an expired attempt once; return None until its persisted deadline."""
    settled_at = _finite_float(now)
    if settled_at is None:
        return None
    pending = pending_attempt(doc)
    if pending is None or settled_at < float(pending["deadline_at"]):
        return None

    ext = _ext(doc)
    record = ext.get(PENDING_KEY)
    if not isinstance(record, dict) or record.get("attempt_id") != pending["attempt_id"]:
        return None

    guardian_uid = str(pending.get("guardian_uid") or "").strip() or None
    max_hp = max(1, _integer(ext.get("hp_max")) or _integer(ext.get("base_hp")) or 1)
    if guardian_uid:
        outcome = "success"
        applied_cost = int(pending["cost"])
        doc.exp = max(0, int(getattr(doc, "exp", 0) or 0) - applied_cost)
        wallet.set_xueqi(doc, max(0, wallet.xueqi(doc) - applied_cost))
        extra_cultivation.set_level(doc, "mijing", 7)
        ext["hp"] = max_hp
        message = (
            "【圣体破咒·四极通天】护道人接续了修行断路，成功晋升人体秘境第 7 境。"
            f"修为、血气各消耗 {applied_cost:,}。"
        )
    else:
        outcome = "failure"
        applied_cost = FAILURE_COST
        doc.exp = max(0, int(getattr(doc, "exp", 0) or 0) - FAILURE_COST)
        wallet.set_xueqi(doc, max(0, wallet.xueqi(doc) - FAILURE_COST))
        extra_cultivation.set_level(doc, "mijing", 1)
        ext["hp"] = 1
        message = (
            "【圣体天劫·道基崩毁】60 息内未获护道，境界跌回人体秘境第 1 境，"
            f"修为、血气各损失 {FAILURE_COST:,}，当前血量降至 1。"
        )

    record.update({
        "status": "settled",
        "outcome": outcome,
        "settled_at": settled_at,
        "applied_cost": applied_cost,
    })
    ext.pop(PLEDGE_KEY, None)
    return {
        "outcome": outcome,
        "message": message,
        "attempt_id": pending["attempt_id"],
        "platform_id": pending["platform_id"],
        "group_id": pending["group_id"],
        "guardian_uid": guardian_uid,
        "applied_cost": applied_cost,
        "settled_at": settled_at,
    }