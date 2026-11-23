"""轮回路与遗落纳戒（W8-A4）。

原版：`apps/SecretPlace/ZhuanshiTask.js` 2278 + `apps/User/lunhui.js` 458（9 指令）。

保留的闭环：
- **执掌轮回路**：第 50 境以上可争此位（全服唯一）；执掌者可切换「往生输出」——
  `纳戒`（死者留下遗落纳戒，供人捡取）或 `归虚`（不留）。
- **遗落纳戒**：转世时按生前纳戒生成（20% 灵石 + 至多 3 件道具），落在此前所在位面，
  72 小时后消散；全服最多保留 30 枚。
- **捡取 / 强闯**：执掌者在位时须 `#强闯轮回路`（按双方境界差判定成败，失败伤及气血）；
  无人执掌或输出为「归虚」时可直接 `#捡取纳戒`。
- 与 W7-4 的关系：寿元耗尽先进 24 小时救援窗口，逾期才转世并留下纳戒——救援优先，轮回路兜底。

存储：`calamity_state["reincarnation"]`（沿用世界状态单例，不新建表、不做迁移）。

shortcut：原版 Redis 级锁与任务 TTL、往生者实时接管（controller 决定放行/拒绝单个往生）、
遗物 72 小时扫盘任务、纳戒所有权追溯未移植；本移植的「拒绝往生」等价于把输出切到「归虚」。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Any

CONTROLLER_REALM = 50        # 第 51 境起可执掌
DROP_TTL = 72 * 3600
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
    if not isinstance(st.get("drops"), list):
        st["drops"] = []
    return st


def put(world: dict, st: Mapping[str, Any]) -> dict:
    world["reincarnation"] = dict(st)
    return world


def controller_of(world: Mapping | None) -> dict | None:
    row = _world(world).get("controller")
    return dict(row) if isinstance(row, Mapping) else None


def mode_of(world: Mapping | None) -> str:
    return str(_world(world).get("mode") or "纳戒")


def take(world: dict, doc: Any, now: float) -> tuple[bool, str]:
    realm = int(getattr(doc, "realm_index", 0) or 0)
    if realm < CONTROLLER_REALM:
        return False, f"执掌轮回路需第 {CONTROLLER_REALM + 1} 境以上（当前第 {realm + 1} 境）。"
    st = _world(world)
    cur = st.get("controller")
    if isinstance(cur, Mapping):
        if str(cur.get("uid")) == doc.uid:
            return False, "轮回路已在你手中。"
        if int(cur.get("realm", 0) or 0) >= realm:
            return False, (f"轮回路在「{cur.get('name')}」手中（第 {int(cur.get('realm', 0)) + 1} 境），"
                           f"境界不高于他，夺不来。")
        st["drops"] = list(st.get("drops") or [])
    st["controller"] = {"uid": doc.uid, "name": doc.name or doc.uid,
                        "realm": realm, "since": float(now)}
    st["since"] = float(now)
    put(world, st)
    return True, (f"你踏上轮回路，万灵往生的轨迹在脚下铺开。\n"
                  f"当前输出：{st['mode']}——{MODES.get(st['mode'], '')}\n"
                  f"执掌者可发 #轮回往生输出切换 决定死者是否留下遗物。")


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


def status_text(world: Mapping | None) -> str:
    st = _world(world)
    cur = st.get("controller")
    drops = list(st.get("drops") or [])
    lines = ["【轮回路】"]
    if isinstance(cur, Mapping):
        lines.append(f"执掌者：{cur.get('name')}（第 {int(cur.get('realm', 0)) + 1} 境）")
        lines.append(f"执掌至今：{max(0, int((time.time() - float(cur.get('since') or 0)) // 3600))} 小时")
    else:
        lines.append("执掌者：空缺（第 51 境以上可 #执掌轮回路）")
    lines.append(f"往生输出：{st.get('mode')}——{MODES.get(st.get('mode'), '')}")
    lines.append(f"遗落纳戒：{len(drops)}/{DROP_CAP}（{DROP_TTL // 3600} 小时消散）")
    lines.append("#遗落纳戒列表｜#附近纳戒｜#查询纳戒 编号｜#捡取纳戒 编号｜#强闯轮回路 编号")
    return "\n".join(lines)


# ---------------------------------------------------------------- 纳戒

def _purge(st: dict, now: float) -> int:
    before = len(st.get("drops") or [])
    st["drops"] = [d for d in (st.get("drops") or [])
                   if float(d.get("exp") or 0) > now]
    return before - len(st["drops"])


def make_drop(world: dict, doc: Any, plane: str, coords: Mapping | None,
              stones: int, items: Mapping[str, int], now: float) -> dict | None:
    """转世时生成遗落纳戒；输出为「归虚」时不生成。"""
    st = _world(world)
    if str(st.get("mode")) != "纳戒":
        put(world, st)
        return None
    _purge(st, now)
    picked = {str(k): int(v) for k, v in list(items.items())[:DROP_ITEM_MAX] if int(v) > 0}
    row = {
        "id": uuid.uuid4().hex[:6],
        "uid": doc.uid,
        "name": doc.name or doc.uid,
        "plane": plane,
        "coords": dict(coords or {}),
        "stones": max(0, int(stones)),
        "items": picked,
        "t": float(now),
        "exp": float(now) + DROP_TTL,
    }
    st["drops"] = (list(st.get("drops") or []) + [row])[-DROP_CAP:]
    put(world, st)
    return row


def list_text(world: Mapping | None, plane: str | None = None, now: float | None = None) -> str:
    st = _world(world)
    if now is not None:
        _purge(st, now)
    rows = [d for d in (st.get("drops") or [])
            if plane is None or str(d.get("plane")) == plane]
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


def pick(world: dict, ref: str, now: float) -> dict | None:
    """按编号或序号取一枚（不改状态）。"""
    st = _world(world)
    _purge(st, now)
    drops = list(st.get("drops") or [])
    ref = (ref or "").strip()
    row = next((d for d in drops if str(d.get("id")) == ref), None)
    if row is None and ref.isdigit():
        idx = int(ref) - 1
        if 0 <= idx < len(drops):
            row = drops[idx]
    return dict(row) if row else None


def detail_text(row: Mapping, now: float) -> str:
    coords = row.get("coords") or {}
    pos = f"（{coords.get('x')},{coords.get('y')}）" if coords else ""
    left = max(0, int(float(row.get("exp") or 0) - now)) // 3600
    lines = [f"【遗落纳戒·{row.get('name')}】",
             f"位面：{row.get('plane')}{pos}｜剩 {left} 小时｜编号 {row.get('id')}",
             f"灵石：{int(row.get('stones', 0)):,}"]
    items = row.get("items") or {}
    lines.append("遗物：" + ("、".join(f"{k}×{v}" for k, v in items.items()) or "无"))
    return "\n".join(lines)


def claim(world: dict, row: Mapping, now: float) -> tuple[bool, str, int, dict[str, int]]:
    """从世界状态移除并返回 (成功, 文案, 灵石, 物品)。"""
    st = _world(world)
    drops = [d for d in (st.get("drops") or []) if str(d.get("id")) != str(row.get("id"))]
    if len(drops) == len(st.get("drops") or []):
        return False, "这枚纳戒已经不在了（可能被别人捡走）。", 0, {}
    st["drops"] = drops
    put(world, st)
    return (True,
            (f"你拾起「{row.get('name')}」的遗落纳戒：灵石 {int(row.get('stones', 0)):,}，"
             f"遗物 {'、'.join(f'{k}×{v}' for k, v in (row.get('items') or {}).items()) or '无'}。"),
            int(row.get("stones", 0)), dict(row.get("items") or {}))


def force_chance(controller: Mapping | None, doc: Any) -> float:
    if not controller:
        return 1.0
    diff = int(getattr(doc, "realm_index", 0) or 0) - int(controller.get("realm", 0) or 0)
    return max(FORCE_MIN, min(FORCE_MAX, FORCE_BASE + diff * 0.02))
