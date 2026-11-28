"""道具发单与领取（公益防诈通道；原版 model/itemGrantStore.js + apps/User/ItemGrant.js）。

原版规则：
- 群主 `#派单 @玩家 道具名[xN] 理由`：单次 1-3 件、每周 10 单/人（周一 04:00 重置，撤销退回）、
  单人同道具同时只能 1 张待领单、全服单道具 30 件/日熔断、7 天过期作废。
- 玩家本人 `#领取`（仅私聊）：一次结清名下全部待领单，到账即锁定（islockd=1，不可出售/转移）。
- `#撤单 单号`：未领取可撤，额度即退。`#举报 内容`：留痕。`#我的单`：列待领。
- 哈希链事件账本（sha256(prev + payload)）供事后核账。

移植口径（与原版一致，宿主差异处已标注）：
- 账本存 SQLite（v23：grant_orders + grant_events），哈希链同公式。
- 「到账即锁定」：本地纳戒是 名字→数量 模型，锁定量记 ext["grant_locks"]，
  #出售 校验可卖量 = 持有 − 锁定；交换/转移类入口本地无对应玩法（差异已标注）。
- 领取仅限私聊：AstrBot 无 get_group_id 即私聊，语义一致。
- 防诈提示：每号第一次领取弹完整版，之后一行简版（原版同）。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any
from datetime import datetime, timedelta

WEEKLY_QUOTA = 10
DAILY_POOL = 30
TTL_DAYS = 7
TTL_SECONDS = TTL_DAYS * 86400
MAX_QTY = 3
GRANT_PREFIX = "N-"


def _sha(prev: str, payload: str) -> str:
    return hashlib.sha256(f"{prev}|{payload}".encode("utf-8")).hexdigest()[:16]


def _week_key(now: float) -> str:
    """原版周一 04:00 重置：取时间所在的 ISO 周。"""
    dt = datetime.fromtimestamp(now)
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week}"


def _day_key(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def defaults() -> dict[str, Any]:
    return {"orders": {}, "events": [], "weekly": {}, "daily": {}, "seq": 0}


def _log_event(state: dict, kind: str, payload: Mapping) -> None:
    prev = state["events"][-1]["hash"] if state["events"] else "GENESIS"
    body = json.dumps({"kind": kind, **dict(payload)}, ensure_ascii=False, sort_keys=True)
    state["events"].append({"kind": kind, **dict(payload),
                            "prevHash": prev, "hash": _sha(prev, body)})


def new_id(state: dict, now: float) -> str:
    state["seq"] = int(state.get("seq", 0) or 0) + 1
    return f"{GRANT_PREFIX}{state['seq']:04d}-{_sha(str(now), str(state['seq']))[:6].upper()}"


def _expire(state: dict, now: float) -> None:
    """过期作废 + 额度退回（惰性，任何入口先跑）。"""
    for oid, o in list(state["orders"].items()):
        if o.get("claimed_at") or o.get("revoked_at") or o.get("expired_at"):
            continue
        if now >= float(o.get("expires_at") or 0):
            o["expired_at"] = now
            wk = str(o.get("week_key") or "")
            iss = str(o.get("issuer_uid") or "")
            state["weekly"][wk] = state["weekly"].get(wk, {})
            state["weekly"][wk][iss] = max(0, int(state["weekly"][wk].get(iss, 0) or 0) - 1)
            dk = str(o.get("day_key") or "")
            state["daily"][dk] = state["daily"].get(dk, {})
            state["daily"][dk][o["item"]] = max(0, int(state["daily"][dk].get(o["item"], 0) or 0) - 1)
            _log_event(state, "expire", {"order": oid, "item": o["item"]})


def quota_of(state: dict, issuer: str, now: float) -> int:
    wk = _week_key(now)
    return WEEKLY_QUOTA - int(state["weekly"].get(wk, {}).get(issuer, 0) or 0)


def place_order(state: dict, issuer: str, target: str, item: str, qty: int,
                reason: str, platform_id: str, group_id: str,
                now: float) -> tuple[bool, str]:
    """#派单：校验额度/熔断/待领单唯一，登记待领单（不入包）。"""
    _expire(state, now)
    qty = max(1, min(MAX_QTY, int(qty or 1)))
    if not issuer or not target:
        return False, "需要 @ 玩家才能发单。"
    if issuer == target:
        return False, "不能给自己发单（直接放纳戒即可）。"
    left = quota_of(state, issuer, now)
    if left <= 0:
        return False, f"本周发单额度已用完（{WEEKLY_QUOTA}/{WEEKLY_QUOTA}）。"
    dk = _day_key(now)
    used = int(state["daily"].get(dk, {}).get(item, 0) or 0)
    if used + qty > DAILY_POOL:
        return False, f"全服今日「{item}」发放已达熔断线 {DAILY_POOL} 件，明日再试。"
    for o in state["orders"].values():
        if (o.get("target_uid") == target and o.get("item") == item
                and not o.get("claimed_at") and not o.get("revoked_at") and not o.get("expired_at")):
            return False, f"该玩家已有 1 张「{item}」待领单（{o['id']}），领取后才能再发。"
    oid = new_id(state, now)
    state["orders"][oid] = {
        "id": oid, "issuer_uid": issuer, "target_uid": target, "item": item,
        "qty": qty, "reason": (reason or "未填写")[:120],
        "platform_id": platform_id, "group_id": group_id,
        "created_at": now, "expires_at": now + TTL_SECONDS,
        "week_key": _week_key(now), "day_key": dk,
    }
    state["weekly"].setdefault(_week_key(now), {})[issuer] = \
        int(state["weekly"].get(_week_key(now), {}).get(issuer, 0) or 0) + 1
    state["daily"].setdefault(dk, {})[item] = used + qty
    _log_event(state, "place", {"order": oid, "issuer": issuer, "target": target,
                                "item": item, "qty": qty})
    return True, oid


def revoke_order(state: dict, oid: str, issuer: str, now: float) -> tuple[bool, str]:
    """#撤单：只有发单人本人、且未领取时可撤；额度立即退回。"""
    _expire(state, now)
    o = state["orders"].get(oid)
    if not o:
        return False, f"没有单号 {oid} 的发放单。"
    if o.get("claimed_at"):
        return False, "该单已被领取，撤销无效（只能走管理员回收）。"
    if o.get("revoked_at") or o.get("expired_at"):
        return False, "该单已作废。"
    if str(o.get("issuer_uid")) != str(issuer):
        return False, "只能撤销自己发出的单。"
    o["revoked_at"] = now
    state["weekly"].setdefault(str(o["week_key"]), {})[issuer] = \
        max(0, int(state["weekly"].get(str(o["week_key"]), {}).get(issuer, 0) or 0) - 1)
    state["daily"].setdefault(str(o["day_key"]), {})[o["item"]] = \
        max(0, int(state["daily"].get(str(o["day_key"]), {}).get(o["item"], 0) or 0) - 1)
    _log_event(state, "revoke", {"order": oid, "by": issuer})
    return True, o


def pending_of(state: dict, target: str, now: float) -> list[dict]:
    """#我的单 / #领取 的待领清单。"""
    _expire(state, now)
    return [o for o in state["orders"].values()
            if o.get("target_uid") == str(target) and not o.get("claimed_at")
            and not o.get("revoked_at") and not o.get("expired_at")]


def claim_all(state: dict, target: str, now: float) -> tuple[bool, str, list[dict]]:
    """#领取：一次结清名下全部待领单，返回 (ok, 文案, 交付清单)。"""
    pending = pending_of(state, target, now)
    if not pending:
        return False, "当前没有待领取的道具。", []
    delivered = []
    for o in pending:
        o["claimed_at"] = now
        delivered.append(o)
        _log_event(state, "claim", {"order": o["id"], "by": target,
                                    "item": o["item"], "qty": o["qty"]})
    return True, "", delivered


def verify_chain(state: Mapping) -> tuple[bool, int]:
    """核账：重放哈希链，返回 (是否完整, 事件数)。"""
    prev = "GENESIS"
    for i, ev in enumerate(state.get("events") or []):
        payload = {k: v for k, v in ev.items() if k not in ("prevHash", "hash")}
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if ev.get("prevHash") != prev or ev.get("hash") != _sha(prev, body):
            return False, i
        prev = ev["hash"]
    return True, len(state.get("events") or [])


def locked_of(doc: Any) -> dict[str, int]:
    ext = getattr(doc, "ext", {}) or {}
    raw = ext.get("grant_locks")
    return {str(k): int(v) for k, v in raw.items()} if isinstance(raw, Mapping) else {}


def add_lock(doc: Any, item: str, qty: int) -> None:
    ext = getattr(doc, "ext", {}) or {}
    locks = ext.get("grant_locks") if isinstance(ext.get("grant_locks"), Mapping) else {}
    locks = dict(locks)
    locks[item] = int(locks.get(item, 0) or 0) + max(0, int(qty))
    ext["grant_locks"] = locks
    doc.ext = ext


def sellable_of(doc: Any, item: str, held: int) -> int:
    """可卖量 = 持有 − 发单锁定（防「领了就卖」）。"""
    return max(0, int(held) - int(locked_of(doc).get(item, 0)))
