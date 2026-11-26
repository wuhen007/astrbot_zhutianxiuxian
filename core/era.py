"""时代系统（W7-2）：五时代轮转 / 突破修正 / 秘境出金率 / 禁仙六封。

原版依据：
- 轮转与历法 `apps/tasks/EraChangeTask.js`（每 2 小时推进 1000 年，一时代 1 万年，五时代一轮）
- 修正值 `apps/tasks/EraStatusPlugin.js:56-105`
- 封印 `apps/Occupation/Occupation.js:409-451`（源天师 100 万源石，目标境界不得高出 2 境）

本移植：
- **只用一条时间线**：`years_total`（世界总年数）。时代 index、时代内年份、纪元 epoch 全部推导，
  不存冗余副本 —— 历史上多份真相最容易漂移。
- **懒推进**：读时按 `last_tick` 结算，不引入 cron（与灵市 tick / 镇守结算同思路）。
  离线补算上限 `MAX_CATCHUP_TICKS`，防挂机几个月后一次跳完十几轮。
- **修正值取 EraStatusPlugin**：原版 `Level.js` 炼体支线把练气表整段复制过去（bodySuccessRate
  25/10/0/-10/-30 与 qi 完全一致），属笔误；炼体应当是「太古 +25 / 末法 +15」的非对称设计。

shortcut（与原版差异）：
- 绝灵物品侵蚀在 1000 年节点惰性结算；日历跳过多个节点时按世界年序补账，跨启动通过时代表与玩家事件标记恢复。
- 位面自修复、高阶仙帝时代权限和 RealmEvents(1912 行) 的专属分支不属于此模块，本地仅由其他系统部分承担。
- 天心印记重置未做（本移植无大帝天心系统）。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

ERA_YEARS = 10_000          # 一个时代 1 万年
DEFAULT_TICK_HOURS = 2.0    # 原版 cron：每 2 小时
DEFAULT_YEARS_PER_TICK = 1_000
MAX_CATCHUP_TICKS = 720     # 最多补 60 天
SEAL_KEY = "seal"
DEFAULT_SEAL = {"one": 0.99, "two": 0.5, "three": 0.25}   # 原版 SecretPlace.one/two/three

ERAS: tuple[dict[str, Any], ...] = (
    {
        "name": "神话时代", "icon": "✨",
        "desc": "天地初开，神灵显化。灵药遍地，异兽横行。大道法则清晰可见，凡人亦可感悟天道至理。",
        "qi_rate": 0.25, "body_rate": 0.10, "qi_cost": 0.4, "body_cost": 0.3,
    },
    {
        "name": "太古时代", "icon": "⚔️",
        "desc": "神魔大战，万族并起。武道昌盛，血脉之力如江河奔涌。顶级修士可掌阴阳五行，移山填海。",
        "qi_rate": 0.10, "body_rate": 0.25, "qi_cost": 0.6, "body_cost": 0.5,
    },
    {
        "name": "天命时代", "icon": "🌌",
        "desc": "天命既明，规则既定。各族鼎立，宗门林立。灵气平稳有序，强者辈出。",
        "qi_rate": 0.0, "body_rate": 0.0, "qi_cost": 1.0, "body_cost": 0.9,
    },
    {
        "name": "末法时代", "icon": "🌑",
        "desc": "天道倾斜，灵气枯竭。规则崩坏，修行之途日渐艰难。仙路渐闭，凡人武道崛起。",
        "qi_rate": -0.10, "body_rate": 0.15, "qi_cost": 1.8, "body_cost": 1.6,
    },
    {
        "name": "绝灵时代", "icon": "💀",
        "desc": "天地寂灭，灵气断绝。末法终结，万物归凡。曾经的修仙之道已成传说。",
        "qi_rate": -0.30, "body_rate": -0.35, "qi_cost": 3.0, "body_cost": 2.8,
    },
)


# ---------------------------------------------------------------- 状态与推导

def default_state(now: float | None = None) -> dict[str, Any]:
    return {
        "years_total": 0,
        "last_tick": float(now if now is not None else time.time()),
        SEAL_KEY: dict(DEFAULT_SEAL),
    }


def _clamp_rate(value: Any, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, f))


def ensure(value: Mapping | None, now: float | None = None) -> dict[str, Any]:
    """补齐缺字段（旧档 / 空库都得能跑）；非法出金率钳回 0-1。"""
    state = dict(value or {})
    base = default_state(now)
    state.setdefault("years_total", 0)
    try:
        state["years_total"] = max(0, int(state["years_total"]))
    except (TypeError, ValueError):
        state["years_total"] = 0
    try:
        state["last_tick"] = float(state.get("last_tick") or 0)
    except (TypeError, ValueError):
        state["last_tick"] = 0.0
    if state["last_tick"] <= 0:
        state["last_tick"] = base["last_tick"]
    seal = state.get(SEAL_KEY)
    seal = dict(seal) if isinstance(seal, Mapping) else {}
    state[SEAL_KEY] = {
        "one": _clamp_rate(seal.get("one"), DEFAULT_SEAL["one"]),
        "two": _clamp_rate(seal.get("two"), DEFAULT_SEAL["two"]),
        "three": _clamp_rate(seal.get("three"), DEFAULT_SEAL["three"]),
    }
    return state


def state_of(years_total: int) -> dict[str, Any]:
    """由世界总年数推导 (index, 时代内年份, epoch)。"""
    years = max(0, int(years_total))
    cycle = ERA_YEARS * len(ERAS)
    cycles, rem = divmod(years, cycle)
    idx = min(len(ERAS) - 1, rem // ERA_YEARS)
    row = dict(ERAS[idx])
    row.update({
        "index": idx,
        "years": rem % ERA_YEARS,
        "epoch": 1 + cycles,
        "years_total": years,
    })
    return row


def era_key(state: Mapping) -> str:
    """时代身份键：跨时代/跨纪元即变化（封印以此为解封判据）。"""
    cur = state_of(int(state.get("years_total", 0) or 0))
    return f"{cur['epoch']}:{cur['index']}"


def seal_rates(state: Mapping) -> tuple[float, float, float]:
    s = state.get(SEAL_KEY) or {}
    return (
        _clamp_rate(s.get("one"), DEFAULT_SEAL["one"]),
        _clamp_rate(s.get("two"), DEFAULT_SEAL["two"]),
        _clamp_rate(s.get("three"), DEFAULT_SEAL["three"]),
    )


def advice(row: Mapping) -> str:
    """修炼建议。

    原版 `getEraAdvice` 用「成功率 − 消耗×10」的差值判断，在神话（21 对 7）与天命
    （−10 对 −9）两个时代都落进「维艰」分支，与实际体感相反。这里改按主导项判断：
    先看两轨成功率差，再看双轨是否都为正 —— 指令面板上的话得对得上玩家看到的数据。
    """
    qi_rate, body_rate = float(row["qi_rate"]), float(row["body_rate"])
    qi_cost, body_cost = float(row["qi_cost"]), float(row["body_cost"])
    if qi_rate - body_rate > 0.05:
        return "此时代适宜专注练气之道"
    if body_rate - qi_rate > 0.05:
        return "此时代适宜专注炼体之道"
    if qi_rate >= 0 and body_rate >= 0 and qi_cost <= 1.2 and body_cost <= 1.2:
        return "双修并进，大道可期"
    return "修行之路维艰，需谨慎选择"


# ---------------------------------------------------------------- 推进

def tick(
    state: Mapping,
    now: float,
    tick_seconds: float = DEFAULT_TICK_HOURS * 3600,
    years_per_tick: int = DEFAULT_YEARS_PER_TICK,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """懒推进：按流逝时间结算若干 tick。返回 (新状态, 变化摘要)。

    只补整 tick，余数留在 last_tick 里，不吞时间。停服再久也只补 MAX_CATCHUP_TICKS 个。
    """
    st = ensure(state, now)
    step = max(1, int(years_per_tick))
    span = max(1.0, float(tick_seconds))
    elapsed = float(now) - float(st["last_tick"])
    ticks = int(elapsed // span) if elapsed > 0 else 0
    info: dict[str, Any] = {"ticks": 0, "years": 0, "old": state_of(st["years_total"]),
                            "new": state_of(st["years_total"]), "changed": False}
    if ticks <= 0:
        return st, info
    ticks = min(ticks, MAX_CATCHUP_TICKS)
    before = state_of(st["years_total"])
    st["years_total"] = int(st["years_total"]) + ticks * step
    st["last_tick"] = float(st["last_tick"]) + ticks * span
    after = state_of(st["years_total"])
    info.update({
        "ticks": ticks,
        "years": ticks * step,
        "old": before,
        "new": after,
        "changed": after["index"] != before["index"] or after["epoch"] != before["epoch"],
    })
    return st, info


def advance_years(state: Mapping, years: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """人为推进若干年（管理员 #下一千年 / #下一个时代）。"""
    st = ensure(state)
    before = state_of(st["years_total"])
    st["years_total"] = max(0, int(st["years_total"]) + int(years))
    after = state_of(st["years_total"])
    return st, {"years": int(years), "old": before, "new": after,
                "changed": after["index"] != before["index"] or after["epoch"] != before["epoch"]}


def to_next_era(state: Mapping) -> tuple[dict[str, Any], dict[str, Any]]:
    """跳到下一个时代的起点（不足一年按一年算，避免原地踏步）。"""
    cur = state_of(int(ensure(state).get("years_total", 0) or 0))
    remain = ERA_YEARS - int(cur["years"])
    return advance_years(state, remain if remain > 0 else ERA_YEARS)


def set_era(state: Mapping, index: int, years: int = 0) -> tuple[dict[str, Any], dict[str, Any]]:
    """直接把世界拨到第 index 个时代（年份可指定）。epoch 按总年数自动推。"""
    st = ensure(state)
    idx = min(len(ERAS) - 1, max(0, int(index)))
    cycle = ERA_YEARS * len(ERAS)
    before = state_of(st["years_total"])
    epoch0 = int(st["years_total"]) // cycle
    st["years_total"] = epoch0 * cycle + idx * ERA_YEARS + min(ERA_YEARS - 1, max(0, int(years)))
    after = state_of(st["years_total"])
    return st, {"old": before, "new": after, "changed": True}


def set_seal_rates(state: Mapping, one: float, two: float,
                   three: float) -> tuple[dict[str, Any], dict[str, Any]]:
    st = ensure(state)
    old = dict(st[SEAL_KEY])
    st[SEAL_KEY] = {"one": _clamp_rate(one, old["one"]),
                    "two": _clamp_rate(two, old["two"]),
                    "three": _clamp_rate(three, old["three"])}
    return st, {"old": old, "new": dict(st[SEAL_KEY])}


# ---------------------------------------------------------------- 修正值消费

def qi_mods(state: Mapping) -> tuple[float, float]:
    """练气：(成功率加成, 消耗系数)。"""
    row = state_of(int(state.get("years_total", 0) or 0))
    return float(row["qi_rate"]), float(row["qi_cost"])


def body_mods(state: Mapping) -> tuple[float, float]:
    """炼体：(成功率加成, 消耗系数)。"""
    row = state_of(int(state.get("years_total", 0) or 0))
    return float(row["body_rate"]), float(row["body_cost"])


# ---------------------------------------------------------------- 禁仙六封

def seal_of(doc: Any) -> dict | None:
    raw = doc.ext.get(SEAL_KEY)
    return dict(raw) if isinstance(raw, Mapping) else None


def is_sealed(doc: Any, state: Mapping) -> bool:
    """封在「黄金大世」里：时代一变（跨时代或跨纪元）自动解封。"""
    seal = seal_of(doc)
    return bool(seal) and str(seal.get("era") or "") == era_key(state)


def seal(doc: Any, by_name: str, by_uid: str, state: Mapping, now: float) -> None:
    doc.ext[SEAL_KEY] = {
        "by": str(by_name or "无名源天师"),
        "uid": str(by_uid or ""),
        "at": float(now),
        "era": era_key(state),
        "text": "禁仙六封",
    }


def unseal(doc: Any) -> bool:
    return doc.ext.pop(SEAL_KEY, None) is not None


def seal_block(doc: Any, state: Mapping, action: str = "行动") -> str | None:
    """被封印时的统一拦截文案；未封印返回 None。"""
    if not is_sealed(doc, state):
        return None
    seal = seal_of(doc) or {}
    cur = state_of(int(state.get("years_total", 0) or 0))
    return (f"你已被「{seal.get('by') or '源天师'}」以禁仙六封镇入神源，{action}无从谈起。\n"
            f"解封条件：黄金大世开启（{cur['name']}结束）或源天师亲手解封。")


# ---------------------------------------------------------------- 展示

def panel(state: Mapping, now: float, tick_seconds: float = DEFAULT_TICK_HOURS * 3600,
          years_per_tick: int = DEFAULT_YEARS_PER_TICK, sealed_count: int = 0) -> str:
    st = ensure(state, now)
    cur = state_of(st["years_total"])
    nxt = ERAS[(cur["index"] + 1) % len(ERAS)]
    filled = min(10, max(0, int(cur["years"] / (ERA_YEARS / 10))))
    bar = "█" * filled + "░" * (10 - filled)
    remain = ERA_YEARS - int(cur["years"])
    ticks_left = -(-remain // max(1, int(years_per_tick)))
    hours_left = ticks_left * (tick_seconds / 3600)
    one, two, three = seal_rates(st)
    lines = [
        "--- 当前时代 ---",
        f"{cur['icon']} {cur['name']}｜第 {cur['epoch']} 纪元·第 {cur['years']:,} 年",
        f"{cur['desc']}",
        f"时代进度：{bar} {cur['years'] / ERA_YEARS:.1%}"
        f"（{remain:,} 年后入{nxt['name']}，约 {hours_left:.1f} 小时）",
        "--- 天地法则 ---",
        f"练气：突破成功率 {cur['qi_rate'] * 100:+.0f}%｜消耗 ×{cur['qi_cost']:.1f}",
        f"炼体：突破成功率 {cur['body_rate'] * 100:+.0f}%｜消耗 ×{cur['body_cost']:.1f}",
        f"秘境出金：低 {one:.2f}｜中 {two:.2f}｜高 {three:.2f}",
        f"修行建议：{advice(cur)}",
        f"世界总年数：{st['years_total']:,}｜被封印修士：{sealed_count} 人",
    ]
    return "\n".join(lines)


def change_text(info: Mapping) -> str:
    """时代更迭播报；未跨时代返回空串。"""
    old, new = info.get("old"), info.get("new")
    if not info.get("changed") or not old or not new:
        return ""
    if old["index"] == new["index"] and old["epoch"] == new["epoch"]:
        return ""
    lines = [
        "【天地巨变·时代更迭】",
        f"{old['icon']} {old['name']} → {new['icon']} {new['name']}",
        f"第 {new['epoch']} 纪元·第 {new['years']} 年",
        f"{new['desc']}",
        f"天地法则：练气 {new['qi_rate'] * 100:+.0f}% / ×{new['qi_cost']:.1f}｜"
        f"炼体 {new['body_rate'] * 100:+.0f}% / ×{new['body_cost']:.1f}",
        "所有修士请适应新的天地法则。",
    ]
    return "\n".join(lines)


def push_text(info: Mapping) -> str:
    """时代变迁主动推送（对齐原版 EraChangeTask.broadcastNewEra 原文）。

    原版：`天地巨变！修仙世界已从【旧】进入【新】！`；跨纪元时加一行
    `纪元更迭！当前纪元：第N纪元`，再跟新时代 icon+desc 与应对提示。
    """
    old, new = info.get("old"), info.get("new")
    if not info.get("changed") or not old or not new:
        return ""
    lines = [f"天地巨变！修仙世界已从【{old['name']}】进入【{new['name']}】！"]
    if int(old["epoch"]) != int(new["epoch"]):
        lines.append(f"纪元更迭！当前纪元：第{new['epoch']}纪元")
    lines += [f"{new['icon']} {new['desc']}",
              "天道法则转变，所有修士请做好应对准备！"]
    return "\n".join(lines)


def progress_text(row: Mapping, advanced_years: int) -> str:
    """每千年进度播报（对齐原版 EraChangeTask 每千年通知原文，含 ▰▱ 进度条）。

    进度条与百分比对齐 createProgressBar：filled = min(100, 年份//100) // 10。
    """
    years = max(0, min(ERA_YEARS, int(row.get("years", 0) or 0)))
    progress = min(100, years // 100)
    filled = min(10, progress // 10)
    bar = "▰" * filled + "▱" * (10 - filled)
    return "\n".join([
        f"时代自动推进 {int(advanced_years)} 年！",
        f"当前纪元: 第{int(row.get('epoch', 1) or 1)}纪元",
        f"当前时代: {row.get('name', '')} {row.get('icon', '')}",
        f"年份: {years}/{ERA_YEARS} 年",
        f"进度: {bar} {progress}%",
    ])

# ---------------------------------------------------------------- 绝灵时代生命周期

JUELING_ERA_INDEX = 4
JUELING_LIFESPAN_LIMIT = 9_999
JUELING_LIFESPAN_KEY = "jueling_suppressed_lifespan"
JUELING_LOSS_EVENT_KEY = "jueling_loss_event"
JUELING_LOSS_IMMUNITY_KEY = "jueling_loss_immune"
JUELING_LOSS_CATEGORIES = (
    "丹药", "道具", "功法", "草药", "材料", "食材", "仙宠", "仙宠口粮", "盒子",
)


def _jueling_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _jueling_immune(doc: Any, authority: int) -> bool:
    """原版寿元门槛为 18、物品损失门槛为 19；岁云任一阶段绝灵免疫。"""
    from .extra_cultivation import realm_authority_level
    from .suiyun import effects as suiyun_effects

    return (realm_authority_level(doc) >= authority
            or bool(suiyun_effects(doc).get("spirit_immune")))


def has_jueling_lifespan(doc: Any) -> bool:
    return JUELING_LIFESPAN_KEY in doc.ext


def restore_jueling_lifespan(doc: Any) -> bool:
    """恢复进入绝灵时代前保存的寿元；重复调用不再改动角色。"""
    if not has_jueling_lifespan(doc):
        return False
    saved = doc.ext.pop(JUELING_LIFESPAN_KEY)
    try:
        doc.ext["shouyuan"] = int(float(saved))
    except (TypeError, ValueError, OverflowError):
        pass
    return True


def sync_jueling_lifespan(doc: Any, era_index: int) -> bool:
    """按当前时代同步寿元压制，供进入、在线结算及重启恢复时调用。"""
    try:
        active = int(era_index) == JUELING_ERA_INDEX
    except (TypeError, ValueError, OverflowError):
        active = False
    if not active or _jueling_immune(doc, 18):
        return restore_jueling_lifespan(doc)

    from .lifespan import shouyuan_of

    current = shouyuan_of(doc)
    was_suppressed = has_jueling_lifespan(doc)
    if not was_suppressed:
        doc.ext[JUELING_LIFESPAN_KEY] = current
    else:
        doc.ext[JUELING_LIFESPAN_KEY] = _jueling_int(
            doc.ext[JUELING_LIFESPAN_KEY], current)
    suppressed = min(current, JUELING_LIFESPAN_LIMIT)
    doc.ext["shouyuan"] = suppressed
    return not was_suppressed or suppressed != current


def add_jueling_aware_lifespan(doc: Any, amount: int, era_index: int) -> dict[str, Any]:
    """增寿时同步真实值与受压显示值，避免绝灵期间的增益在离开时丢失。"""
    added = max(0, _jueling_int(amount))
    try:
        active = int(era_index) == JUELING_ERA_INDEX
    except (TypeError, ValueError, OverflowError):
        active = False
    if not active or _jueling_immune(doc, 18):
        sync_jueling_lifespan(doc, era_index)
        from .lifespan import shouyuan_of

        visible_before = shouyuan_of(doc)
        doc.ext["shouyuan"] = visible_before + added
        return {"added": added, "visible_added": added, "suppressed": False}

    sync_jueling_lifespan(doc, era_index)
    visible_before = _jueling_int(doc.ext.get("shouyuan"))
    true_before = _jueling_int(doc.ext.get(JUELING_LIFESPAN_KEY), visible_before)
    doc.ext[JUELING_LIFESPAN_KEY] = true_before + added
    doc.ext["shouyuan"] = min(JUELING_LIFESPAN_LIMIT, visible_before + added)
    return {
        "added": added,
        "visible_added": doc.ext["shouyuan"] - visible_before,
        "suppressed": True,
    }


def grant_jueling_loss_immunity(doc: Any, layers: int = 1) -> int:
    """记录可抵挡的绝灵损失次数；扣除护符由调用方与此变更同事务完成。"""
    amount = max(0, _jueling_int(layers))
    current = max(0, _jueling_int(doc.ext.get(JUELING_LOSS_IMMUNITY_KEY)))
    doc.ext[JUELING_LOSS_IMMUNITY_KEY] = current + amount
    return current + amount


def apply_jueling_item_loss(
    doc: Any,
    inventory: Mapping[str, int],
    item_categories: Mapping[str, str],
    state: Mapping,
    rng: Any = None,
) -> dict[str, Any]:
    """计算本个绝灵时代年节点的纳戒损失；持久化及事务由调用方负责。

    `inventory` 是扁平的物品数量表，`item_categories` 将物品名映射到原版纳戒类别。
    角色状态中的事件键使同一纪元/时代/年份的重放幂等；调用方须把角色状态和物品扣减
    放在同一事务，并按世界年份串行处理时代节点。
    """
    current = state_of(_jueling_int(state.get("years_total")))
    result: dict[str, Any] = {
        "items": [], "inventory_delta": {}, "groups": 0,
        "immune": False, "sealed": False, "shielded": False, "replayed": False,
    }
    if current["index"] != JUELING_ERA_INDEX:
        return result

    event_id = f"{current['epoch']}:{current['index']}:{current['years']}"
    last_year = _jueling_int(doc.ext.get(JUELING_LOSS_EVENT_KEY), -1)
    event_year = _jueling_int(state.get("years_total"), 0)
    if event_year <= last_year:
        result["replayed"] = True
        return result
    doc.ext[JUELING_LOSS_EVENT_KEY] = event_year

    if is_sealed(doc, state):
        result["sealed"] = True
        return result
    if _jueling_immune(doc, 19):
        result["immune"] = True
        return result
    immune_layers = max(0, _jueling_int(doc.ext.get(JUELING_LOSS_IMMUNITY_KEY)))
    if immune_layers:
        doc.ext[JUELING_LOSS_IMMUNITY_KEY] = immune_layers - 1
        result["shielded"] = True
        return result

    randomizer = rng or random
    categories = {
        category: [
            str(name) for name, owned in inventory.items()
            if str(item_categories.get(str(name)) or "") == category
            and _jueling_int(owned) > 0
        ]
        for category in JUELING_LOSS_CATEGORIES
    }
    loss_categories = [category for category, names in categories.items() if names]
    extra_groups = max(0, int(current["years"]) // 1_000) * 2
    groups = 3 + randomizer.randrange(3) + extra_groups
    result["groups"] = groups
    if not loss_categories:
        return result

    from .items import locked_of

    locked = locked_of(doc)
    remaining = {str(name): max(0, _jueling_int(qty)) for name, qty in inventory.items()}
    deltas: dict[str, int] = {}
    for _ in range(groups):
        if not loss_categories:
            break
        category = randomizer.choice(loss_categories)
        candidates = [
            name for name in categories[category]
            if remaining.get(name, 0) > 0
        ]
        if not candidates:
            loss_categories.remove(category)
            continue
        name = randomizer.choice(candidates)
        if name in locked:
            continue

        owned = remaining[name]
        amount = max(1, min(owned // 10, owned))
        remaining[name] = owned - amount
        deltas[name] = deltas.get(name, 0) + amount
        result["items"].append({"name": name, "category": category, "amount": amount})
        if not any(remaining.get(item, 0) > 0 for item in categories[category]):
            loss_categories.remove(category)

    result["inventory_delta"] = deltas
    return result
