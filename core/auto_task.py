"""自动任务（W21-F1）——原版 `apps/tasks/AutoDailyTask.js`（每天 00:05 为
道法仙术玩家自动执行 签到 / 势力俸禄 / 天道赐福 / 道法赐福）的纯函数移植。

本移植（shortcut）：
- 无后台定时器：开启后，**当日第一条指令**在 `_require_player` 挂钩点惰性
  补领（与 lifespan 惰性结算同位），结果写入 `#签到记录` 可查（近 7 天）。
- 自动范围：签到（道法翻倍）/ 天道赐福 / 道法赐福 / 每日抽奖不自动（需次数
  手动）；势力俸禄未纳入（势力模块走独立全服态，shortcut）。
- 奖励参数由调用方传入（handler 侧 `_val`），与手动签到同源同倍率。
"""

from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

EXT_KEY = "auto_task"
LOG_DAYS = 7


def _day_key(now: float) -> str:
    return time.strftime("%Y%m%d", time.localtime(now))


def _defaults() -> dict[str, Any]:
    return {"on": False, "day": "", "log": {}}


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[EXT_KEY] = dict(st)


def state_of(doc: Any) -> dict[str, Any]:
    from typing import Mapping as _M
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = _defaults()
    if isinstance(raw, dict):
        st.update(raw)
    st["on"] = bool(st.get("on"))
    if not isinstance(st.get("log"), dict):
        st["log"] = {}
    return st


def set_enabled(doc: PlayerDoc, on: bool, now: float,
                daofa_active: bool) -> tuple[bool, str]:
    st = state_of(doc)
    if on and not daofa_active:
        return False, "自动任务为道法仙术玩家专享——先 #消耗道法仙术一日卡。"
    st["on"] = bool(on)
    save(doc, st)
    return True, ("【自动任务 · 开启】此后每日第一条指令将自动补领："
                  "签到 / 天道赐福 / 道法赐福（防漏，不替代手动核对；"
                  "#签到记录 查看近况）。"
                  if on else "【自动任务 · 关闭】回到手动领取。")


def run_if_due(doc: PlayerDoc, now: float, rng: random.Random,
               sign_min: int, sign_max: int,
               mingge_mult: float, card_sign_bonus: float,
               ) -> tuple[list[str], dict[str, int], PlayerDoc]:
    """当日首条指令惰性补领。返回 (汇报行, 物品增量, 新档)。"""
    from typing import Mapping as _M
    st = state_of(doc)
    if not st.get("on"):
        return [], {}, doc
    day = _day_key(now)
    if st.get("day") == day:
        return [], {}, doc
    try:
        from . import daofa as _df
        if not _df.active(doc, now):
            return [], {}, doc
    except Exception:
        return [], {}, doc

    from . import cultivate as _cu
    from . import blessing as _bl
    lines: list[str] = []
    items: dict[str, int] = {}
    st["day"] = day

    ok, msg, doc = _cu.sign_in(doc, sign_min, sign_max, now, rng,
                               reward_mult=mingge_mult * 2 * (1 + card_sign_bonus))
    lines.append("自动签到：" + (msg.splitlines()[0] if msg else "已领"))
    if ok:
        lines.append("　" + (msg.splitlines()[1] if len(msg.splitlines()) > 1 else ""))

    try:
        from . import blessing as _bl
        ok_t, msg_t, doc, it_t = _bl.tiandao_gift(doc, now, mult=mingge_mult)
        if ok_t:
            lines.append("自动天道赐福：" + msg_t.splitlines()[0])
            for k, v in (it_t or {}).items():
                items[k] = items.get(k, 0) + int(v)
        else:
            lines.append("自动天道赐福：" + msg_t.splitlines()[0])
    except Exception:
        pass

    try:
        from . import daofa as _df
        ok_d, msg_d, doc, it_d = _df.gift(doc, now)
        if ok_d:
            lines.append("自动道法赐福：" + msg_d.splitlines()[0])
            for k, v in (it_d or {}).items():
                items[k] = items.get(k, 0) + int(v)
        else:
            lines.append("自动道法赐福：" + msg_d.splitlines()[0])
    except Exception:
        pass

    log = st["log"]
    log[day] = lines
    st["log"] = {k: log[k] for k in sorted(log)[-LOG_DAYS:]}
    save(doc, st)
    return lines, items, doc


def record_text(doc: Any) -> str:
    st = state_of(doc)
    lines = [f"--- 签到记录（自动任务：{'开启' if st.get('on') else '关闭'}）---"]
    if not st.get("log"):
        lines.append("暂无自动补领记录。")
    for day in sorted(st["log"], reverse=True)[:LOG_DAYS]:
        lines.append(f"· {day}")
        lines += [f"　{ln}" for ln in st["log"][day]]
    lines.append("开关：#开启自动任务 / #关闭自动任务")
    return "\n".join(lines)


# ---------------------------------------------------------------- 兑换码（W21-F1）

def _rewards_of(entry: Mapping[str, Any]) -> tuple[str, dict[str, int], int, str]:
    """兼容多种表结构：items{} / thing[{name,数量}] / stones；返回 (名, 物品, 灵石, 描述)。"""
    name = str(entry.get("code") or entry.get("name") or "?")
    items: dict[str, int] = dict(entry.get("items") or {})
    for t in entry.get("thing") or []:
        if isinstance(t, dict) and t.get("name"):
            items[str(t["name"])] = items.get(str(t["name"]), 0) + int(t.get("数量", 1) or 1)
    stones = int(entry.get("stones", 0) or 0)
    desc = str(entry.get("desc") or entry.get("说明") or "")
    return name, items, stones, desc


def redeem_list(rows: Any) -> str:
    rows = rows if isinstance(rows, list) else []
    lines = ["--- 兑换码图鉴 ---"]
    if not rows:
        lines.append("（暂无可用兑换码——服主在 data/item/兑换码.json 发布后此处刷新）")
    for e in rows:
        if not isinstance(e, dict):
            continue
        name, items, stones, desc = _rewards_of(e)
        code = str(e.get("code") or name)
        masked = code[:2] + "****" + code[-2:] if len(code) > 5 else code[:2] + "****"
        brief = "、".join(f"{k}×{v}" for k, v in items.items())
        if stones:
            brief += f"｜灵石×{stones:,}" if brief else f"灵石×{stones:,}"
        lines.append(f"· {name}｜码 {masked}｜{brief or desc or '神秘奖励'}")
    lines.append("兑换：#兑换码兑换 完整码")
    return "\n".join(lines)


def redeem(doc: PlayerDoc, rows: Any, code: str, now: float,
           ) -> tuple[bool, str, dict[str, int], int]:
    """#兑换码兑换 完整码：每人每码一次。返回 (ok, msg, 物品, 灵石)。"""
    st = state_of(doc)
    rows = rows if isinstance(rows, list) else []
    code = (code or "").strip()
    if not code:
        return False, "用法：#兑换码兑换 完整码。", {}, 0
    entry = None
    for e in rows:
        if isinstance(e, dict) and \
                str(e.get("code") or e.get("name") or "").strip().upper() == code.upper():
            entry = e
            break
    if entry is None:
        return False, "兑换码无效（#兑换码图鉴 查看在册名单）。", {}, 0
    name, items, stones, _ = _rewards_of(entry)
    redeemed = list(st.get("redeemed") or [])
    if code.upper() in redeemed or name in redeemed:
        return False, f"「{name}」你已经兑换过了——每人每码一次。", {}, 0
    redeemed.append(code.upper())
    st["redeemed"] = redeemed[-30:]
    save(doc, st)
    doc.stones = int(getattr(doc, "stones", 0) or 0) + stones
    return True, (f"【兑换成功 · {name}】"
                  + "、".join(f"{k}×{v}" for k, v in items.items())
                  + (f"｜灵石 +{stones:,}" if stones else "")), items, stones
