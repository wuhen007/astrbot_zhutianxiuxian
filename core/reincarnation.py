"""轮回裁定与遗落纳戒（W8-A4）。

固定原版：困难难度寿元耗尽后先等 5 分钟；有执掌者则进入单人裁定，无执掌者自动往生。
简单/普通难度不强制往生。执掌与救援分别需要额外体系权柄 16/11。
遗落纳戒保存 7 天；寻访者需要记忆并抵达记录的位面坐标，领取与奖励入账共用数据库事务。

输出模式「纳戒/归虚」是本端口的遗物输出选项，与三档难度分开存储。
存储：`calamity_state["reincarnation"]`；寿元阶段保存在玩家 ext。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any

CONTROLLER_AUTHORITY = 16   # 原版额外体系轮回权柄
RESCUE_AUTHORITY = 11
DROP_TTL = 7 * 24 * 3600
OWNER_PROTECTION_SECONDS = 60 * 60
DROP_MEMORY_KEY = "reincarnation_drop_memory"
DROP_MEMORY_CAP = 256
DROP_CAP = 30
DROP_STONE_RATE = 0.2
DROP_ITEM_MAX = 3
FORCE_BASE = 0.5
FORCE_MIN, FORCE_MAX = 0.10, 0.90

MODES = {"纳戒": "死者留下遗落纳戒，可被捡取", "归虚": "死者归于虚无，不留遗物"}


def _world(world: Mapping | None) -> dict[str, Any]:
    raw = (world or {}).get("reincarnation") if isinstance(world, Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("controller", None)
    st.setdefault("since", 0.0)
    st.setdefault("mode", "纳戒")
    st.setdefault("drops", [])
    st.setdefault("pending", {})
    if not isinstance(st.get("drops"), list):
        st["drops"] = []
    if not isinstance(st.get("pending"), dict):
        st["pending"] = {}
    return st


def put(world: dict, st: Mapping[str, Any]) -> dict:
    world["reincarnation"] = dict(st)
    return world


def controller_of(world: Mapping | None) -> dict | None:
    row = _world(world).get("controller")
    return dict(row) if isinstance(row, Mapping) else None


def mode_of(world: Mapping | None) -> str:
    return str(_world(world).get("mode") or "纳戒")


def clear_controller(world: dict) -> None:
    st = _world(world)
    st["controller"] = None
    put(world, st)


def refresh_controller(world: dict, doc: Any) -> bool:
    """Revalidate the persisted controller against their current extra authority."""
    st = _world(world)
    current = st.get("controller")
    if not isinstance(current, Mapping) or str(current.get("uid")) != str(doc.uid):
        return False
    from . import extra_cultivation
    authority = extra_cultivation.realm_authority_level(doc)
    if authority < CONTROLLER_AUTHORITY:
        st["controller"] = None
        put(world, st)
        return False
    st["controller"] = {
        "uid": str(doc.uid), "name": doc.name or doc.uid,
        "realm": int(getattr(doc, "realm_index", 0) or 0),
        "authority": authority, "since": float(current.get("since", 0) or 0),
    }
    put(world, st)
    return True


def can_rescue(doc: Any) -> bool:
    from . import extra_cultivation
    return extra_cultivation.realm_authority_level(doc) >= RESCUE_AUTHORITY


def queue_decision(world: dict, doc: Any, now: float) -> tuple[bool, str]:
    """Persist one expired hard-difficulty soul for the active controller."""
    from . import lifespan
    st = _world(world)
    controller = st.get("controller")
    if not isinstance(controller, Mapping):
        return False, "当前无人执掌轮回路。"
    if int(controller.get("authority", 0) or 0) < CONTROLLER_AUTHORITY:
        return False, "当前执掌者的轮回权柄已不足。"
    if not lifespan.pending(doc):
        return False, "目标不在轮回往生状态。"
    if lifespan.rescue_left(doc, now) > 0:
        return False, "五分钟救援期尚未结束。"
    pending = st.setdefault("pending", {})
    key = str(doc.uid)
    row = pending.get(key)
    if not isinstance(row, Mapping):
        pending[key] = {
            "uid": key, "name": doc.name or key, "queued_at": float(now),
            "rescue_deadline": float(doc.ext.get("rescue_deadline") or 0),
            "controller_id": str(controller.get("uid") or ""),
            "controller_name": str(controller.get("name") or "执掌者"),
            "status": "pending",
        }
    else:
        pending[key] = {
            **dict(row), "name": doc.name or key,
            "controller_id": str(controller.get("uid") or ""),
            "controller_name": str(controller.get("name") or "执掌者"),
        }
    doc.ext["reincarnation_phase"] = "decision"
    put(world, st)
    return True, f"{doc.name or doc.uid} 已进入轮回路待裁定名单。"


def forget_pending(world: dict, uid: str) -> bool:
    st = _world(world)
    removed = st["pending"].pop(str(uid), None) is not None
    put(world, st)
    return removed


def decide(world: dict, target_uid: str, actor: Any, decision: str,
           now: float) -> tuple[bool, str, dict | None]:
    if decision not in {"allow", "deny"}:
        return False, "无效的轮回裁定。", None
    st = _world(world)
    controller = st.get("controller")
    if not isinstance(controller, Mapping) or str(controller.get("uid")) != str(actor.uid):
        return False, "只有当前轮回路执掌者可以裁定。", None
    from . import extra_cultivation
    authority = extra_cultivation.realm_authority_level(actor)
    if authority < CONTROLLER_AUTHORITY:
        return False, f"轮回裁定需额外体系权柄达到 {CONTROLLER_AUTHORITY}/24（当前 {authority}）。", None
    row = st["pending"].get(str(target_uid))
    if not isinstance(row, Mapping) or row.get("status") != "pending":
        return False, "目标不在待裁定名单中，或该裁定已处理。", None
    result = dict(row)
    result.update({
        "status": decision, "decided_at": float(now),
        "controller_id": str(actor.uid),
        "controller_name": actor.name or actor.uid,
    })
    st["pending"].pop(str(target_uid), None)
    put(world, st)
    return True, "准许往生。" if decision == "allow" else "驳回往生。", result


def take(world: dict, doc: Any, now: float) -> tuple[bool, str]:
    from . import extra_cultivation
    authority = extra_cultivation.realm_authority_level(doc)
    if authority < CONTROLLER_AUTHORITY:
        return False, f"执掌轮回路需额外体系权柄达到 {CONTROLLER_AUTHORITY}/24（当前 {authority}）。"
    st = _world(world)
    cur = st.get("controller")
    if isinstance(cur, Mapping):
        if str(cur.get("uid")) == doc.uid:
            return False, "轮回路已在你手中。"
        if int(cur.get("authority", 0) or 0) >= authority:
            return False, (f"轮回路在「{cur.get('name')}」手中（权柄 {int(cur.get('authority', 0) or 0)}），"
                           "你的轮回权柄不高于执掌者。")
    st["controller"] = {"uid": doc.uid, "name": doc.name or doc.uid,
                         "realm": int(getattr(doc, "realm_index", 0) or 0),
                         "authority": authority, "since": float(now)}
    st["since"] = float(now)
    put(world, st)
    return True, (f"你踏上轮回路，万灵往生的轨迹在脚下铺开。\n"
                  f"当前遗落纳戒输出：{st['mode']}。寿元耗尽者将在轮回路执掌者处等待裁定。")


def release(world: dict, doc: Any) -> tuple[bool, str]:
    st = _world(world)
    cur = st.get("controller")
    if not isinstance(cur, Mapping) or str(cur.get("uid")) != doc.uid:
        return False, "轮回路不在你手中。"
    st["controller"] = None
    put(world, st)
    return True, "你松开权柄，轮回路重归天地。"


def toggle(world: dict, doc: Any) -> tuple[bool, str]:
    st = _world(world)
    cur = st.get("controller")
    if not isinstance(cur, Mapping) or str(cur.get("uid")) != doc.uid:
        return False, "只有执掌轮回路的人能改往生输出。"
    st["mode"] = "归虚" if st.get("mode") == "纳戒" else "纳戒"
    put(world, st)
    return True, f"往生输出已切为【{st['mode']}】：{MODES[st['mode']]}"


def pending_text(world: Mapping | None) -> str:
    pending = _world(world).get("pending") or {}
    rows = [(uid, row) for uid, row in pending.items() if isinstance(row, Mapping)]
    if not rows:
        return "待裁定往生：无"
    rows.sort(key=lambda item: float(item[1].get("queued_at") or 0))
    return "待裁定往生：" + "、".join(
        f"{row.get('name') or uid}（{uid}）" for uid, row in rows
    )


def status_text(world: Mapping | None) -> str:
    st = _world(world)
    cur = st.get("controller")
    lines = ["【轮回路】"]
    if isinstance(cur, Mapping):
        authority = int(cur.get("authority", 0) or 0)
        lines.append(f"执掌者：{cur.get('name')}（额外体系权柄 {authority}）")
        lines.append(f"执掌至今：{max(0, int((time.time() - float(cur.get('since') or 0)) // 3600))} 小时")
    else:
        lines.append(f"执掌者：空缺（额外体系权柄 {CONTROLLER_AUTHORITY}/24 可执掌）")
    lines.append(f"遗落纳戒输出：{st.get('mode')}——{MODES.get(st.get('mode'), '')}")
    lines.append(f"遗落纳戒：{len(st.get('drops') or [])}/{DROP_CAP}（{DROP_TTL // 86400} 天消散；需有遗物记忆并抵达坐标）")
    lines.append(pending_text({"reincarnation": st}))
    lines.append("#遗落纳戒列表｜#附近纳戒｜#查询纳戒 编号｜#捡取纳戒 编号｜#强闯轮回路 编号")
    lines.append("裁定：#准许往生 @玩家｜#驳回往生 @玩家")
    return "\n".join(lines)


def _purge(st: dict, now: float) -> int:
    before = len(st.get("drops") or [])
    st["drops"] = [d for d in (st.get("drops") or [])
                   if float(d.get("exp") or 0) > now]
    return before - len(st["drops"])


def make_drop(world: dict, doc: Any, plane: str, coords: Mapping | None,
              stones: int, items: Mapping[str, int], now: float,
              source_stones: int = 0) -> dict | None:
    """Transfer old inventory and currencies into a seven-day rebirth drop."""
    st = _world(world)
    if str(st.get("mode")) != "纳戒":
        put(world, st)
        return None
    _purge(st, now)
    contents = {str(name): max(0, int(quantity))
                for name, quantity in items.items() if int(quantity) > 0}
    owner_stones = max(0, int(stones))
    owner_source = max(0, int(source_stones))
    if not contents and not owner_stones and not owner_source:
        put(world, st)
        return None
    row = {"id": uuid.uuid4().hex, "uid": str(doc.uid), "owner_id": str(doc.uid),
           "name": doc.name or doc.uid, "plane": str(plane or "凡间"),
           "owner_level": int(getattr(doc, "realm_index", 0) or 0) + 1,
           "coords": dict(coords or {}), "stones": owner_stones,
           "source_stones": owner_source, "items": contents, "t": float(now),
           "exp": float(now) + DROP_TTL}
    st["drops"] = (list(st.get("drops") or []) + [row])[-DROP_CAP:]
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        memories = [str(value) for value in (ext.get(DROP_MEMORY_KEY) or [])]
        memories.append(row["id"])
        ext[DROP_MEMORY_KEY] = memories[-DROP_MEMORY_CAP:]
    put(world, st)
    return row


def list_text(world: Mapping | None, plane: str | None = None, now: float | None = None,
              coords: Mapping | None = None) -> str:
    st = _world(world)
    if now is not None:
        _purge(st, now)
    rows = [d for d in (st.get("drops") or [])
            if (plane is None or str(d.get("plane")) == plane)
            and (coords is None or (isinstance(d.get("coords"), Mapping)
                 and int(d["coords"].get("x", -1)) == int(coords.get("x", -2))
                 and int(d["coords"].get("y", -1)) == int(coords.get("y", -2))))]
    title = f"--- 遗落纳戒 · {plane} ---" if plane else "--- 遗落纳戒 ---"
    if not rows:
        return title + "\n此处没有遗落纳戒。"
    lines = [title, f"在册 {len(rows)} 枚（{DROP_TTL // 3600} 小时内有效）"]
    for i, d in enumerate(rows, 1):
        coords = d.get("coords") or {}
        pos = f"（{coords.get('x')},{coords.get('y')}）" if coords else ""
        left = max(0, int(float(d.get("exp") or 0) - (now or time.time()))) // 3600
        lines.append(f"{i}. {d.get('name')}｜{d.get('plane')}{pos}｜"
                     f"灵石 {int(d.get('stones', 0)):,}｜剩 {left} 小时｜编号 {d.get('id')}")
    lines.append("查看详情：#查询纳戒 编号｜捡取：#捡取纳戒 编号")
    return "\n".join(lines)


def remember_nearby(world: Mapping | None, doc: Any, plane: str,
                     coords: Mapping | None, now: float) -> list[dict]:
    """Seeing a drop at the current coordinate records its recoverable memory."""
    if not isinstance(coords, Mapping):
        return []
    st = _world(world)
    _purge(st, now)
    rows = [dict(row) for row in st["drops"]
            if str(row.get("plane") or "") == str(plane)
            and isinstance(row.get("coords"), Mapping)
            and int(row["coords"].get("x", -1)) == int(coords.get("x", -2))
            and int(row["coords"].get("y", -1)) == int(coords.get("y", -2))]
    if rows and isinstance(getattr(doc, "ext", None), dict):
        memories = [str(value) for value in (doc.ext.get(DROP_MEMORY_KEY) or [])]
        known = set(memories)
        memories.extend(str(row["id"]) for row in rows if str(row["id"]) not in known)
        doc.ext[DROP_MEMORY_KEY] = memories[-DROP_MEMORY_CAP:]
    return rows


def can_claim(row: Mapping, plane: str, coords: Mapping | None,
              memories: list | tuple | set) -> bool:
    if str(row.get("id") or "") not in {str(value) for value in memories}:
        return False
    if str(row.get("plane") or "") != str(plane):
        return False
    location = row.get("coords")
    if not isinstance(location, Mapping):
        return True
    if not isinstance(coords, Mapping):
        return False
    try:
        return int(location.get("x")) == int(coords.get("x")) and int(location.get("y")) == int(coords.get("y"))
    except (TypeError, ValueError):
        return False


def pick(world: dict, ref: str, now: float, picker_uid: str = "") -> dict | None:
    """Find a live drop and enforce its owner-only protection window."""
    st = _world(world)
    _purge(st, now)
    drops = list(st.get("drops") or [])
    ref = (ref or "").strip()
    row = next((drop for drop in drops if str(drop.get("id")) == ref), None)
    if row is None and ref.isdigit():
        index = int(ref) - 1
        if 0 <= index < len(drops):
            row = drops[index]
    if not isinstance(row, dict):
        return None
    return dict(row)


def detail_text(row: Mapping, now: float) -> str:
    coords = row.get("coords") or {}
    pos = f"（{coords.get('x')},{coords.get('y')}）" if coords else ""
    left = max(0, int(float(row.get("exp") or 0) - now)) // 3600
    lines = [f"【遗落纳戒·{row.get('name')}】",
             f"位面：{row.get('plane')}{pos}｜剩 {left} 小时｜编号 {row.get('id')}",
             f"灵石：{int(row.get('stones', 0)):,}｜源石：{int(row.get('source_stones', 0)):,}"]
    items = row.get("items") or {}
    lines.append("遗物：" + ("、".join(f"{k}×{v}" for k, v in items.items()) or "无"))
    return "\n".join(lines)


def claim(world: dict, row: Mapping, now: float,
          picker_uid: str = "") -> tuple[bool, str, int, dict[str, int]]:
    """Remove a live drop once, after enforcing expiration and owner protection."""
    st = _world(world)
    current = next((drop for drop in (st.get("drops") or [])
                    if str(drop.get("id")) == str(row.get("id"))), None)
    if not isinstance(current, Mapping):
        return False, "这枚纳戒已经不在了（可能被别人捡走）。", 0, {}
    if float(current.get("exp") or 0) <= float(now):
        st["drops"] = [drop for drop in st.get("drops", [])
                       if str(drop.get("id")) != str(row.get("id"))]
        put(world, st)
        return False, "这枚纳戒已过期消散。", 0, {}
    st["drops"] = [drop for drop in st.get("drops", [])
                   if str(drop.get("id")) != str(row.get("id"))]
    put(world, st)
    message = (f"你拾起「{current.get('name')}」的遗落纳戒：灵石 {int(current.get('stones', 0)):,}，"
               f"源石 {int(current.get('source_stones', 0)):,}，"
               f"遗物 {'、'.join(f'{name}×{qty}' for name, qty in (current.get('items') or {}).items()) or '无'}。")
    contents = dict(current.get("items") or {})
    if int(current.get("source_stones", 0) or 0) > 0:
        contents["源石"] = int(current["source_stones"])
    return True, message, int(current.get("stones", 0)), contents


def force_chance(controller: Mapping | None, doc: Any) -> float:
    if not controller:
        return 1.0
    from . import extra_cultivation
    authority = extra_cultivation.realm_authority_level(doc)
    diff = authority - int(controller.get("authority", controller.get("realm", 1)) or 1)
    return max(FORCE_MIN, min(FORCE_MAX, FORCE_BASE + diff * 0.02))
