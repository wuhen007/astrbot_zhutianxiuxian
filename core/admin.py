"""超级管理员 / 诸天初始化（W8-F1，对齐原版 apps/AdminSuper/AdminSuper.js 24 条
+ GlobalInit.js 6 条 = 30 条 rule）。

原版语义已在取证中纠偏，本模块按真实行为移植：

- `#解封` = **解除进行中的行动**（把结算标志全部置 1、结束时间提前到现在），
  不是解封封禁；封禁/赦免另见 `#封禁修仙` / `#解封修仙`。
- `#打落凡间` = 位面位置重置回凡间（原版 `power_place = 0`），不是境界打落。
- `#补发等级` = 补发**副职业等级**（原版 `occupation_level`），不是境界。
- `#打入地狱` = **彻底删档**（原版 `deletePlayerDataBundle`），故必须二次确认。
- `#清除冲水堂` = 把交易行挂单**原物退还**卖家（本移植交易行由星阁拍卖承担）。
- `#全局推送消息` / `#删除全局推送` / `#查看全局推送` / `#同步公告群` 都是
  **公告群名单**维护，不是发消息。
- `#补登唯一机缘` 属仙古遗迹永久认领，本移植不做仙古遗迹 → 不移植。

状态全部落在 `calamity_state["admin"]` 单例，db 当前版本为 v18。
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Mapping

from . import fashan, lifespan, occupation, plane

# ---------------------------------------------------------------- 常量

DEFAULT_DIFFICULTY = "困难"

DIFFICULTIES: dict[str, dict[str, Any]] = {
    "简单": {"decay": False, "forced": False,
             "desc": "寿元不随时间流逝，耗尽也不会被强制踏轮回"},
    "普通": {"decay": True, "forced": False,
             "desc": "寿元随时间流逝，耗尽后停在救援窗口，不强制轮回"},
    "困难": {"decay": True, "forced": True,
             "desc": "寿元随时间流逝，耗尽后救援窗口一过即强制轮回"},
}

JAIL_DEFAULT_MINUTES = 24 * 60        # 原版 #打入天牢 默认 1 天
JAIL_MAX_MINUTES = 30 * 24 * 60
RELIEVE_TIME_KEYS = ("end_at", "end", "end_time", "finish_at", "ready_at", "settle_at")

LOG_CAP = 60
INIT_TIMEOUT = 60.0                   # 原版二次确认 60 秒
INIT_CODE_LEN = 4

# 原版「拉新奖励」基础包 + 三档附加（档 4 原版 reg 允许但 switch 无 case，等价空档）
INVITE_BASE_STONES = 100_000_000
INVITE_BASE_ITEMS: dict[str, int] = {"超越宝盒": 5, "位面传送阵": 3, "轮回命签": 50}
INVITE_TIERS: dict[int, dict[str, int]] = {
    1: {"洗根水": 500, "锁灵仙符": 1},
    2: {"叩仙丹": 25, "天药": 50},
    3: {"超越宝盒": 10, "众生仙钓": 3},
    4: {},
}
# 原版档 1 发的「定灵仙符」在全仓物品表里**零命中**（幽灵物品），本移植换成同作用的锁灵仙符
INVITE_TIER_TEXT = {
    1: "洗根水 ×500｜锁灵仙符 ×1（原版定灵仙符为幽灵物品，已替换）",
    2: "叩仙丹 ×25｜天药 ×50",
    3: "超越宝盒 ×10（共 15）｜众生仙钓 ×3",
    4: "无附加（原版档 4 未实现）",
}

# 诸天初始化要清空的表；db_info 必须保留（版本号）
INIT_TABLES = (
    "players", "inventory", "world_boss", "boss_ledger", "sects", "auction", "item_grants",
    "daily_tasks", "dark_boss", "dark_ledger", "raid_team", "raid_member",
    "rift_state", "ancient_state", "calamity_state", "lingjie_state",
    "other_shore_state", "market_state", "era_state", "tianjiao_state",
    "faction_state",
)


# ---------------------------------------------------------------- 世界状态

def state_of(cal: dict) -> dict:
    """取（并按需初始化）`calamity_state["admin"]`；直接改 cal，调用方负责保存。"""
    st = cal.get("admin")
    if not isinstance(st, dict):
        st = {}
    st.setdefault("masters", [])
    st.setdefault("difficulty", DEFAULT_DIFFICULTY)
    st.setdefault("notify_groups", [])
    st.setdefault("log", [])
    st.setdefault("init", None)
    cal["admin"] = st
    return st


def normalize(state: Mapping[str, Any]) -> dict:
    """只读归一：缺字段时给默认值，不回写。"""
    return {
        "masters": list(state.get("masters") or []),
        "difficulty": str(state.get("difficulty") or DEFAULT_DIFFICULTY),
        "notify_groups": [str(g) for g in (state.get("notify_groups") or [])],
        "log": list(state.get("log") or []),
        "init": state.get("init"),
    }


def is_master(uid: str, bot_admin: bool, state: Mapping[str, Any]) -> bool:
    """机器人管理员恒有权柄；修仙管理员由 `#设置修仙管理员` 追加。"""
    return bool(bot_admin) or str(uid) in normalize(state)["masters"]


def master_add(state: dict, uid: str) -> tuple[bool, str]:
    uid = str(uid)
    if not uid:
        return False, "没识别到目标 uid。"
    masters = state.setdefault("masters", [])
    if uid in masters:
        return False, "此人已是修仙管理员。"
    masters.append(uid)
    return True, f"已授予 {uid} 修仙管理员权柄（共 {len(masters)} 人）。"


def master_del(state: dict, uid: str) -> tuple[bool, str]:
    uid = str(uid)
    masters = state.setdefault("masters", [])
    if uid not in masters:
        return False, "此人本就不是修仙管理员。"
    masters.remove(uid)
    return True, f"已收回 {uid} 的修仙管理员权柄（剩 {len(masters)} 人）。"


def master_text(state: Mapping[str, Any]) -> str:
    masters = normalize(state)["masters"]
    if not masters:
        return "--- 修仙管理员 ---\n当前只有机器人管理员可执权柄。"
    return "--- 修仙管理员 ---\n" + "\n".join(f"· {u}" for u in masters)


# ---------------------------------------------------------------- 难度

def difficulty_of(state: Mapping[str, Any]) -> str:
    name = str(normalize(state)["difficulty"])
    return name if name in DIFFICULTIES else DEFAULT_DIFFICULTY


def flags_of(state: Mapping[str, Any]) -> dict[str, bool]:
    """只回两个开关，供热路径 `self._adm_flags.get(...)` 使用。"""
    cfg = DIFFICULTIES[difficulty_of(state)]
    return {"decay": bool(cfg["decay"]), "forced": bool(cfg["forced"])}


def set_difficulty(state: dict, name: str) -> tuple[bool, str]:
    if name not in DIFFICULTIES:
        return False, "可选难度：简单 / 普通 / 困难。"
    state["difficulty"] = name
    cfg = DIFFICULTIES[name]
    return True, (f"--- 诸天难度 · {name} ---\n{cfg['desc']}\n"
                  f"寿元流逝：{'开' if cfg['decay'] else '关'}｜"
                  f"强制轮回：{'开' if cfg['forced'] else '关'}")


def difficulty_text(state: Mapping[str, Any]) -> str:
    cur = difficulty_of(state)
    lines = [f"--- 诸天难度 · {cur} ---"]
    for name, cfg in DIFFICULTIES.items():
        mark = "▶" if name == cur else "·"
        lines.append(f"{mark} {name}：{cfg['desc']}")
    lines.append(f"发送「#选择难度 简单|普通|困难」切换。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 公告群

def notify_set(state: dict, gid: str) -> tuple[bool, str]:
    gid = str(gid or "").strip()
    if not gid:
        return False, "请在群聊里发送，或改用「#全局推送消息 群号」。"
    state["notify_groups"] = [gid]
    return True, f"已将群 {gid} 设为唯一公告群。"


def notify_add(state: dict, gid: str) -> tuple[bool, str]:
    gid = str(gid or "").strip()
    if not gid.isdigit():
        return False, "格式：「#全局推送消息 群号」（纯数字）。"
    groups = state.setdefault("notify_groups", [])
    if gid in groups:
        return False, f"群 {gid} 已在公告名单里。"
    groups.append(gid)
    return True, f"已把群 {gid} 加入公告名单（共 {len(groups)} 个）。"


def notify_del(state: dict, gid: str) -> tuple[bool, str]:
    gid = str(gid or "").strip()
    groups = state.setdefault("notify_groups", [])
    if gid not in groups:
        return False, f"群 {gid} 不在公告名单里。"
    groups.remove(gid)
    return True, f"已从公告名单移除群 {gid}（剩 {len(groups)} 个）。"


def notify_text(state: Mapping[str, Any]) -> str:
    groups = normalize(state)["notify_groups"]
    if not groups:
        return "--- 公告群 ---\n当前未设置（用「#同步公告群」把本群设为唯一公告群）。"
    return "--- 公告群 ---\n" + "\n".join(f"· {g}" for g in groups)


# ---------------------------------------------------------------- 管理日志

def log_append(state: dict, by: str, text: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    log = state.setdefault("log", [])
    log.append({"at": float(now), "by": str(by), "text": str(text)})
    if len(log) > LOG_CAP:
        del log[: len(log) - LOG_CAP]


def log_text(state: Mapping[str, Any], limit: int = 20) -> str:
    rows = normalize(state)["log"][-limit:]
    if not rows:
        return "--- 管理日志 ---\n暂无记录。"
    lines = ["--- 管理日志 ---"]
    for r in reversed(rows):
        ts = time.strftime("%m-%d %H:%M", time.gmtime(float(r.get("at") or 0) + 8 * 3600))
        lines.append(f"{ts}｜{r.get('by', '?')}｜{r.get('text', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 玩家处置

def relieve_action(doc: Any, now: float) -> tuple[bool, str]:
    """解除进行中的行动：状态归空闲，未来的结束时间一律提到现在。

    等价于原版把 is_jiesuan/shutup/working/power_up/Place_action 全置 1 并
    `end_time = now`；真正的结算仍由各系统自己的惰性 tick 完成。
    """
    touched: list[str] = []
    if str(getattr(doc, "state", "空闲") or "空闲") != "空闲":
        touched.append(str(doc.state))
        doc.state = "空闲"
        doc.state_start = 0.0
    for key, val in list((doc.ext or {}).items()):
        if not isinstance(val, dict):
            continue
        for k in RELIEVE_TIME_KEYS:
            v = val.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > now:
                val[k] = float(now)
                touched.append(str(key))
                break
    if not touched:
        return False, "该道友本就没有进行中的行动。"
    doc.ext["relieved_at"] = float(now)
    return True, "已解除：" + "、".join(dict.fromkeys(touched))


def relieve_fashan(doc: Any) -> bool:
    """清空法身行动（法身本身与血量保留）。返回是否有改动。"""
    st = (doc.ext or {}).get("fashan")
    if not isinstance(st, dict):
        return False
    if not st.get("action") and str(st.get("state") or "空闲") == "空闲":
        return False
    st["action"] = None
    st["state"] = "空闲"
    return True


def knock_to_mortal(doc: Any) -> tuple[bool, str]:
    """打落凡间：位面位置重置回凡间，清掉在途旅行。"""
    st = plane.state_of(doc)
    before = str(st.get("current") or "凡间")
    st["current"] = plane.DEFAULT_PLANE
    st["travel"] = None
    st["coords"][plane.DEFAULT_PLANE] = None
    if not isinstance(st.get("known"), list):
        st["known"] = [plane.DEFAULT_PLANE]
    elif plane.DEFAULT_PLANE not in st["known"]:
        st["known"].append(plane.DEFAULT_PLANE)
    if before == plane.DEFAULT_PLANE and not st.get("travel"):
        return True, f"{getattr(doc, 'name', doc.uid)} 本就在凡间。"
    return True, f"已将 {getattr(doc, 'name', doc.uid)} 从【{before}】打落凡间。"


def jail(doc: Any, minutes: int, now: float) -> tuple[bool, str]:
    """打入天牢：限时封禁，到期由 `_require_player` 自动赦免。"""
    minutes = int(minutes or 0)
    if minutes <= 0:
        minutes = JAIL_DEFAULT_MINUTES
    minutes = min(minutes, JAIL_MAX_MINUTES)
    doc.ext["banned"] = True
    doc.ext["jail_until"] = float(now) + minutes * 60
    hours = minutes / 60
    span = f"{hours:.1f} 小时" if hours >= 1 else f"{minutes} 分钟"
    return True, f"{getattr(doc, 'name', doc.uid)} 已被打入天牢 {span}，期满自动赦免。"


def jail_left(doc: Any, now: float) -> str:
    try:
        until = float((doc.ext or {}).get("jail_until") or 0)
    except (TypeError, ValueError):
        until = 0.0
    if not until:
        return "此权柄为永久封禁，需「#解封修仙」赦免。"
    left = max(0, int(until - now))
    return f"剩余约 {left // 3600} 小时 {left % 3600 // 60} 分。"


def grant_occupation_level(doc: Any, levels: int) -> tuple[bool, str]:
    """补发副职业等级（原版 occupation_level，非境界）。"""
    levels = int(levels or 0)
    if levels <= 0:
        return False, "格式：「#补发职业等级 @玩家 级数」（正整数）。"
    job = str((doc.ext or {}).get("occupation") or "")
    if not job:
        return False, f"{getattr(doc, 'name', doc.uid)} 尚未就职，无处补发等级。"
    cur = int((doc.ext or {}).get("occupation_level", 1) or 1)
    target = min(occupation.MAX_OCC_LEVEL, cur + levels)
    granted = target - cur
    if granted <= 0:
        return False, f"{doc.name} 的 {job} 已达 {occupation.MAX_OCC_LEVEL} 级上限。"
    doc.ext["occupation_level"] = target
    capped = "（已按职业等级上限夹紧）" if granted < levels else ""
    return True, f"{doc.name} 的 {job} 等级 +{granted}，现为 {target} 级。{capped}"


def divorce(doc: Any) -> tuple[bool, str]:
    """拆散道侣：清自己的 daolv。

    返回 (是否成功, 道侣 uid)；对方档案由调用方按 uid 另行清理。
    """
    partner = str((doc.ext or {}).get("daolv") or "")
    if not partner:
        return False, f"{getattr(doc, 'name', doc.uid)} 并无道侣。"
    doc.ext.pop("daolv", None)
    return True, partner


def send_rebirth(doc: Any) -> str:
    """送入轮回：走寿元系统的转世（境界归 1、修为清零、灵石折半）。"""
    return lifespan.rebirth(doc)


# ---------------------------------------------------------------- 纳戒

def wipe_item(inv: dict[str, int], name: str) -> int:
    qty = int(inv.pop(str(name), 0) or 0)
    return qty


def swap_item(inv: dict[str, int], old: str, new: str) -> int:
    qty = int(inv.pop(str(old), 0) or 0)
    if qty > 0 and new:
        inv[str(new)] = int(inv.get(str(new), 0) or 0) + qty
    return qty


def scan_inventory(inv: Mapping[str, int], known: Iterable[str] | None = None) -> dict[str, Any]:
    """纳戒体检：负数/零/非整数数量 + 物品表里查不到的名字。"""
    bad_qty: list[str] = []
    unknown: list[str] = []
    known_set = set(known) if known is not None else None
    for name, qty in inv.items():
        try:
            q = int(qty)
        except (TypeError, ValueError):
            bad_qty.append(str(name))
            continue
        if q <= 0:
            bad_qty.append(str(name))
            continue          # 数量非法的条目会被删掉，不必再报「未知物品」
        if known_set is not None and str(name) not in known_set:
            unknown.append(str(name))
    return {"bad_qty": bad_qty, "unknown": unknown, "total": len(inv)}


def repair_inventory(inv: dict[str, int]) -> tuple[int, list[str]]:
    """删除数量非法（≤0/非整数）的条目。返回 (修复条数, 样本)。"""
    fixed: list[str] = []
    for name in list(inv.keys()):
        try:
            q = int(inv[name])
        except (TypeError, ValueError):
            inv.pop(name, None)
            fixed.append(str(name))
            continue
        if q <= 0:
            inv.pop(name, None)
            fixed.append(str(name))
    return len(fixed), fixed[:8]


# ---------------------------------------------------------------- 拉新奖励

def invite_pack(tier: int) -> tuple[bool, dict[str, int], str]:
    tier = int(tier or 0)
    if tier not in INVITE_TIERS:
        return False, {}, "档位只能是 1-4。"
    items = dict(INVITE_BASE_ITEMS)
    for name, qty in INVITE_TIERS[tier].items():
        items[name] = int(items.get(name, 0)) + int(qty)
    return True, items, INVITE_TIER_TEXT[tier]


def invite_text(tier: int, target: str) -> str:
    _ok, items, bonus = invite_pack(tier)
    lines = [f"--- 拉新奖励 · 档{tier} ---", f"已发放给 {target}："]
    lines += [f"· {n} ×{q}" for n, q in items.items()]
    lines.append(f"· 灵石 ×{INVITE_BASE_STONES:,}")
    lines.append(f"附加：{bonus}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 诸天初始化

def init_warning(code: str) -> str:
    return (
        "--- 灭维之战 · 诸天初始化 ---\n"
        "此举将抹去「全部」修士档案与万界积累：\n"
        "· 玩家存档 / 纳戒 / 每日任务 / 亲密度 / 师徒 / 道侣\n"
        "· 宗门 / 拍卖行 / 讨伐 / 世界 BOSS / 天骄 / 阵营 / 灵界\n"
        "· 时代、位面状态、全服事件、公告群之外的一切世界状态\n"
        "执行前会自动备份当前数据库。\n"
        f"若确认，请在 {int(INIT_TIMEOUT)} 秒内发送「#确认诸天初始化 {code}」。\n"
        "反悔请发送「#取消诸天初始化」。"
    )


def init_request(state: dict, uid: str, code: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    state["init"] = {"by": str(uid), "code": str(code), "start": float(now),
                     "expire": float(now) + INIT_TIMEOUT}
    return init_warning(code)


def init_verify(state: dict, uid: str, code: str, now: float | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else now
    pending = state.get("init")
    if not isinstance(pending, dict):
        return False, "没有待确认的初始化；请先发送「#诸天初始化」。"
    if str(pending.get("by")) != str(uid):
        return False, "只有发起者本人能确认。"
    if float(pending.get("expire") or 0) < now:
        state["init"] = None
        return False, "确认已超时（60 秒），请重新发送「#诸天初始化」。"
    if str(pending.get("code")) != str(code).strip():
        return False, "确认码不对，本次不执行。"
    state["init"] = None
    return True, "确认通过，开始灭维。"


def init_cancel(state: dict) -> tuple[bool, str]:
    if not isinstance(state.get("init"), dict):
        return False, "当前没有待确认的初始化。"
    state["init"] = None
    return True, "已取消本次诸天初始化，万界安然。"


def make_code(seed: int | None = None) -> str:
    n = int(time.time() * 1000) if seed is None else int(seed)
    return f"{n % (10 ** INIT_CODE_LEN):0{INIT_CODE_LEN}d}"


def init_result_text(counts: Mapping[str, int], backup: str | None) -> str:
    total = sum(int(v) for v in counts.values())
    lines = ["--- 灭维完成 · 新纪元 ---",
             f"已清空 {total} 行数据，万物归无。",
             "· " + "｜".join(f"{k} {v}" for k, v in counts.items() if v)]
    if backup:
        lines.append(f"备份：{backup}")
    lines.append("旧世界的余烬已被封存；发送「#踏入仙途」从零开始。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 杂项

def epoch_grant(doc: Any, amount: int) -> tuple[bool, str]:
    """发放纪元积累（原版 Add_纪元积累 封顶写入）。"""
    amount = int(amount or 0)
    if amount <= 0:
        return False, "格式：「#发放纪元积累 数量 @玩家」（正整数）。"
    got = fashan.add_era(doc, amount)
    return True, (f"已发放纪元积累 {got} 点给 {getattr(doc, 'name', doc.uid)}"
                  f"（现 {fashan.era_of(doc)} 点）。")
