"""修炼核心逻辑：签到 / 闭关 / 突破（纯函数，无 IO；时间与随机均由外部注入）。"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from . import timed_action
from .player import PlayerDoc

def _date_key(ts: float) -> str:
    """上海时区日期键（对齐原版 shijianc 按 Y/M/D 判定自然日）。"""
    return time.strftime("%Y-%m-%d", time.gmtime(ts + 8 * 3600))


def sign_in(
    doc: PlayerDoc,
    reward_min: int = 0,
    reward_max: int = 0,
    now: float | None = None,
    rng: random.Random | None = None,
    reward_mult: float = 1.0,
) -> tuple[bool, str, PlayerDoc]:
    """每日签到（对齐原版 daily_gift：自然日判定 + 连续签到递增压值）。

    原版公式（level_id×Physique_id 双轨 → 本插件以 (境界id)² 对标）：
    - 修为 = 连续天数 × 1000 × 境界id²；血气 = 同修为
    - 灵石 = 连续天数 × 300 × 境界id（原版另有源石，此处并入灵石）
    - 秘境之匙由 handler 按奖励发放（原版 ticket=1/天）
    reward_min/reward_max/rng 为旧签名兼容参数，已不参与计算。
    """
    now = now if now is not None else time.time()
    today = _date_key(now)
    yesterday = _date_key(now - 86400)
    last = doc.ext.get("last_sign_date")
    if last == today:
        return False, "道友今日已签到过，明日请早。", doc

    d = doc.model_copy(deep=True)
    streak = int(d.ext.get("sign_streak", 0) or 0) + 1 if last == yesterday else 1
    realm = max(0, d.realm_index) + 1
    xiuwei = streak * 1000 * realm * realm
    stones = max(1, int(streak * 300 * realm * max(0.1, float(reward_mult or 1.0))))
    d.ext["sign_streak"] = streak
    d.ext["last_sign_date"] = today
    d.exp += xiuwei
    d.ext["xueqi"] = int(d.ext.get("xueqi", 0) or 0) + xiuwei
    d.stones += stones
    return True, (
        f"签到成功（连续 {streak} 天）！修为 +{xiuwei}，血气 +{xiuwei}，灵石 +{stones}，"
        f"当前家底 {d.stones} 灵石。"
    ), d


def start_cultivate(
    doc: PlayerDoc,
    minutes: int | None,
    max_minutes: int,
) -> tuple[bool, str, PlayerDoc]:
    """闭关：可选计划时长（分钟），超过 max_minutes 按上限计算并提示。"""
    if doc.state != "空闲":
        return False, f"道友正在「{doc.state}」中，无法分心闭关。", doc

    d = doc.model_copy(deep=True)  # ext 深拷贝：写 cultivate_minutes 不得污染调用方档案
    d.state = "闭关中"
    d.state_start = time.time()
    d.ext["cultivate_time_multiplier"] = timed_action.multiplier(d, d.state_start)

    planned: int | None = None
    hint = ""
    if minutes is not None:
        planned = max(1, int(minutes))
        if planned > max_minutes:
            planned = max_minutes
            hint = f"（最高 {max_minutes} 分钟，已按上限计算）"
        d.ext["cultivate_minutes"] = planned

    plan_txt = f"计划闭关 {planned} 分钟{hint}" if planned else "未设时长，出关时按实际时间结算"
    if planned and d.ext["cultivate_time_multiplier"] < 1:
        real_minutes = math.ceil(planned * d.ext["cultivate_time_multiplier"])
        plan_txt += f"；先天至宝加速后预计实时时长 {real_minutes} 分钟"
    return True, f"道友已入定闭关。{plan_txt}。发送「#出关」结算。", d


def end_cultivate(
    doc: PlayerDoc,
    now: float,
    exp_per_min: int,
    max_minutes: int,
    period_minutes: int = 30,
) -> tuple[bool, str, PlayerDoc]:
    """出关：惰性结算。

    对齐原版 biguan_jiesuan：结算分钟数按 period（原版 30 分钟）向下取整为周期倍数，
    不足一个周期无收益；单次受 max_minutes 上限约束（原版 30×240=7200）。
    """
    if doc.state != "闭关中":
        return False, "道友尚未闭关，何谈出关？", doc

    d = doc.model_copy(deep=True)
    elapsed = max(0.0, (now - d.state_start) / 60)
    time_multiplier = d.ext.pop("cultivate_time_multiplier", 1.0)
    credited = timed_action.credited_minutes(d.state_start, now, time_multiplier)
    counted = min(float(credited), float(max_minutes))
    planned = d.ext.pop("cultivate_minutes", None)
    if planned:
        counted = min(counted, float(planned))
    d.state = "空闲"
    d.state_start = 0.0

    # 周期取整（原版：满足 30 分钟才结算一次，不足不给收益）
    floored = int(counted // period_minutes) * period_minutes if period_minutes > 0 else int(counted)
    if floored < period_minutes:
        return True, "【闭关·周期不足】闭关不足一个周期（30 分钟），未能有所精进。", d

    gained = int(floored * exp_per_min)
    # W8-C2 先天至宝修炼收益倍率；计时缩短已折算进 credited 分钟。
    try:
        from . import xtzb as _xt
        yield_mult = _xt.yield_mult(d, "cultivate")
        if yield_mult > 1:
            gained = int(gained * yield_mult)
    except Exception:
        pass
    # 丹药 buff（原版 dy 体系）：炼神之力 → 修为转血气；辟谷/炼神次数各消耗 1
    buffs = dict(d.ext.get("buffs") or {})
    big = buffs.get("biguan") if isinstance(buffs.get("biguan"), dict) else {}
    lian = buffs.get("lianti") if isinstance(buffs.get("lianti"), dict) else {}
    buff_notes = []
    if int(float(lian.get("times", 0) or 0)) > 0:
        d.ext["xueqi"] = int(d.ext.get("xueqi", 0) or 0) + gained
        buff_notes.append(f"炼神之力发动，本次 {gained} 修为尽数化为血气")
    else:
        d.exp += gained
    if int(float(big.get("times", 0) or 0)) > 0:
        left = int(float(big["times"])) - 1
        if left > 0:
            big["times"] = left
            buffs["biguan"] = big
            buff_notes.append(f"辟谷药效剩余 {left} 次")
        else:
            buffs.pop("biguan", None)
            buff_notes.append("辟谷药效耗尽")
    if int(float(lian.get("times", 0) or 0)) > 0:
        left = int(float(lian["times"])) - 1
        if left > 0:
            lian["times"] = left
            buffs["lianti"] = lian
            buff_notes.append(f"炼神药效剩余 {left} 次")
        else:
            buffs.pop("lianti", None)
            buff_notes.append("炼神药效耗尽")
    if buffs:
        d.ext["buffs"] = buffs
    elif "buffs" in d.ext:
        d.ext.pop("buffs", None)
    notes = []
    if buff_notes:
        notes.append("；".join(buff_notes))
    if planned and credited >= int(planned):
        notes.append("已到计划时长，按计划结算")
    elif elapsed > max_minutes:
        notes.append(f"已达单次上限（{max_minutes} 分钟）")
    tail = f"（{'；'.join(notes)}）" if notes else ""
    return True, (
        f"【闭关·出关】闭关 {int(elapsed)} 分钟（计 {floored} 分钟），"
        f"{'血气增进' if int(float(lian.get('times', 0) or 0)) > 0 else '修为增进'} {gained} 点{tail}。\n"
        f"当前修为：{d.exp}"
    ), d


# ---------------------------------------------------------------- 降妖（原版 PlayerControl.Dagong / endWork）

WORK_PERIOD = 15           # 原版 config work.time：15 分钟一档
WORK_CYCLES = 48           # 原版 config work.cycle：最多 48 档 → 上限 720 分钟
WORK_DEFAULT_MINUTES = 30  # 原版未带时长时默认 30 分钟
WORK_MIN_HP = 200          # 原版当前血量 < 200 拒绝降妖


def start_work(doc: PlayerDoc, minutes: int | None) -> tuple[bool, str, PlayerDoc]:
    """降妖：时长按 15 分钟一档向下取整（原版 Dagong：15×48 档，未带时长默认 30 分钟）。"""
    if doc.state != "空闲":
        return False, f"道友正在「{doc.state}」中，无法分心降妖。", doc

    t = WORK_DEFAULT_MINUTES if minutes is None else max(1, int(minutes))
    for i in range(WORK_CYCLES, 0, -1):
        if t >= WORK_PERIOD * i:
            t = WORK_PERIOD * i
            break
    else:
        t = WORK_PERIOD

    d = doc.model_copy(deep=True)
    d.state = "降妖中"
    d.state_start = time.time()
    multiplier = timed_action.multiplier(d, d.state_start)
    d.ext["work_time_multiplier"] = multiplier
    d.ext["work_minutes"] = t
    timing = f"（先天至宝加速后预计实时时长 {math.ceil(t * multiplier)} 分钟）" if multiplier < 1 else ""
    return True, f"现在开始降妖{t}分钟{timing}，完成后发「#降妖归来」结算。", d


def end_work(
    doc: PlayerDoc,
    now: float,
    stones_per_min: int,
    period_minutes: int = WORK_PERIOD,
) -> tuple[bool, str, PlayerDoc]:
    """降妖归来：惰性结算，分钟数按 15 分钟一档向下取整，不足一档无收益。

    对齐原版 dagong_jiesuan：每分钟灵石 = work.size × 境界id × 效率乘区 × 0.5，
    结算分钟 = min(实际经过, 计划时长, 720)。stones_per_min 由 handler 传入。
    """
    if doc.state != "降妖中":
        return False, "道友并未降妖，何谈归来？", doc

    d = doc.model_copy(deep=True)
    elapsed = max(0.0, (now - d.state_start) / 60)
    time_multiplier = d.ext.pop("work_time_multiplier", 1.0)
    credited = timed_action.credited_minutes(d.state_start, now, time_multiplier)
    counted = min(float(credited), float(WORK_PERIOD * WORK_CYCLES))
    planned = d.ext.pop("work_minutes", None)
    if planned:
        counted = min(counted, float(planned))
    d.state = "空闲"
    d.state_start = 0.0

    floored = int(counted // period_minutes) * period_minutes if period_minutes > 0 else int(counted)
    if floored < period_minutes:
        return True, "降妖不足一个周期（15 分钟），妖物四散，空手而归。", d

    gained = int(floored * stones_per_min)
    # W8-C2 先天至宝修炼收益倍率；计时缩短已折算进 credited 分钟。
    try:
        from . import xtzb as _xt
        yield_mult = _xt.yield_mult(d, "cultivate")
        if yield_mult > 1:
            gained = int(gained * yield_mult)
    except Exception:
        pass
    d.stones += gained
    tail = "（已到计划时长，按计划结算）" if planned and credited >= int(planned) else ""
    return True, (
        f"降妖归来（{int(elapsed)} 分钟，计 {floored} 分钟）：灵石 +{gained:,}{tail}。\n"
        f"当前家底：{d.stones:,} 灵石"
    ), d


def breakthrough(
    doc: PlayerDoc,
    level_table: list[dict],
    success_rate: float,
    fail_penalty: float,
    rng: random.Random,
    cost_factor: float = 1.0,
    rate_bonus: float = 0.0,
    potential_cost: int | None = None,
    cost_reduction: float = 1.0,
    potential_bonus: int = 0,
    luck: bool = False,
    plane_level: int = 10,
) -> tuple[bool, str, PlayerDoc]:
    """练气突破：成功扣除修为与潜力；失败消耗修为并承受额外损失。

    success_rate/fail_penalty 为兼容参数；成功率依原版境界、时代和体质公式计算。
    cost_factor / rate_bonus 来自时代法则（W7-2，原版 Level.js 的 qiCostFactor / qiSuccessRate）。
    """
    if doc.state != "空闲":
        return False, f"道友正在「{doc.state}」中，无法突破。", doc

    i = doc.realm_index + 1
    if i >= len(level_table):
        return False, "道友已臻化境，此界再无更高境界。", doc

    nxt = level_table[i]
    from . import plane
    target_level = int(nxt.get("level_id", i + 1) or i + 1)
    world_gate = plane.world_level_gate_message("qi", target_level, plane_level)
    if world_gate:
        return False, world_gate, doc
    # 语义：境界表当前条目的 exp = 从该境界突破到下一境所需的累计修为
    base_req = int(level_table[doc.realm_index].get("exp", 0))
    talent_cost, talent_rate = physique_breakthrough_bonus(doc)
    if cost_reduction == 1.0:
        cost_reduction = talent_cost
    reduction = min(1.0, max(0.05, float(cost_reduction)))
    req = max(1, int(round(base_req * reduction)))
    req = max(1, int(req * max(0.05, float(cost_factor)) + 0.999))
    need_potential = int(potential_cost if potential_cost is not None else
                         player_breakthrough_potential_cost(doc, doc.realm_index + 1))
    available_potential = max(0, int(float(doc.ext.get("potential", 0) or 0)))
    if available_potential < need_potential:
        return False, f"仙道潜力不足：本次突破需 {need_potential} 点（当前 {available_potential}）。", doc
    if doc.exp < req:
        era_note = f"（时代法则 ×{float(cost_factor):.1f}）" if abs(float(cost_factor) - 1.0) > 1e-9 else ""
        return False, (
            f"修为不足，无法突破【{nxt['level']}】。\n"
            f"需求 {req}{era_note}，当前 {doc.exp}。"
        ), doc

    d = doc.model_copy(deep=True)
    physique_bonus = max(-0.9, float(potential_bonus or 0)) + talent_rate
    base_rate = max(0.01, 1.0 - (doc.realm_index + 1) / 60)
    rate = max(0.01, base_rate + float(rate_bonus) + physique_bonus)
    if luck:
        rate += (1.0 - rate) * 0.5
    rate = max(0.01, rate)
    if rng.random() < rate:
        d.realm_index = i
        d.exp = max(0, d.exp - req)
        d.ext["potential"] = max(0, available_potential - need_potential)
        e = level_table[min(i, len(level_table) - 1)]
        d.ext["base_attack"] = e.get("基础攻击", 0)
        d.ext["base_defense"] = e.get("基础防御", 0)
        d.ext["base_hp"] = e.get("基础血量", 0)
        return True, (
            f"天降异象，突破成功！\n当前境界：【{e['level']}】\n"
            f"攻击 {e.get('基础攻击', 0)} · 防御 {e.get('基础防御', 0)} · 血量 {e.get('基础血量', 0)}"
        ), d

    roll = rng.random()
    loss_rate = 0.4 if roll > 0.9 else 0.2 if roll > 0.8 else 0.1 if roll > 0.7 else 0.05 if roll > 0.6 else 0.0
    lost = int(req * loss_rate)
    d.exp = max(0, d.exp - req - lost)
    return True, (
        f"突破【{nxt['level']}】失败，消耗修为 {req}，额外损失 {lost} 点。\n当前修为：{d.exp}"
    ), d


def breakthrough_potential_cost(level_id: int) -> int:
    """原版 Level.js：境界 1-26 每次 2 点，27-41 每次 4 点，42+ 每次 8 点。"""
    level_id = max(1, int(level_id))
    return 2 if level_id <= 26 else 4 if level_id <= 41 else 8


def player_breakthrough_potential_cost(doc: PlayerDoc, level_id: int) -> int:
    """按命格效果修正潜力消耗，倍率钳制在原版允许的 0..3。"""
    base = breakthrough_potential_cost(level_id)
    try:
        from .mingge import effects_of
        effects = effects_of(doc)
        reduction = max(0.0, float(effects.get("仙道潜力消耗减少", 0) or 0))
        increase = max(0.0, float(effects.get("仙道潜力消耗增加", 0) or 0))
    except (TypeError, ValueError):
        reduction, increase = 0.0, 0.0
    multiplier = min(3.0, max(0.0, 1.0 - reduction + increase))
    adjusted = base * multiplier
    return max(0, int(adjusted) if multiplier <= 1 else int(adjusted + 0.999999))


PHYSIQUE_BREAKTHROUGH = {
    "大成·荒古圣体": (0.75, 0.25), "混沌体": (0.85, 0.15),
    "先天混沌圣体道胎": (0.65, 0.35), "大成·神王体": (0.80, 0.20),
    "天妖体": (0.90, 0.10), "道胎": (0.95, 0.05),
    "小成·荒古圣体": (0.70, 0.30), "小成·苍天霸体": (0.75, 0.25),
    "大成·苍天霸体": (0.65, 0.35), "苍天霸体": (0.75, 0.25),
    "重瞳": (0.85, 0.15), "先天圣体道胎": (0.60, 0.40),
    "彼岸·命运神道体": (0.50, 0.50), "无相·万化天魔体": (0.50, 0.50),
}


def physique_breakthrough_bonus(doc: PlayerDoc) -> tuple[float, float]:
    """返回原版体质突破消耗倍率、成功率加成。"""
    root = doc.ext.get("linggen")
    name = str(root.get("name", "")) if isinstance(root, dict) else ""
    if name in PHYSIQUE_BREAKTHROUGH:
        return PHYSIQUE_BREAKTHROUGH[name]
    if "魔胎" in name:
        return 0.90, 0.10
    if "仙体" in name:
        return 0.85, 0.15
    return 1.0, 0.0


def gate_state(doc: PlayerDoc, allowed: set[str]) -> str | None:
    """状态门：非空闲且当前指令不在放行集合时返回提示。"""
    if doc.state == "空闲" or doc.state in allowed:
        return None
    return f"道友正在「{doc.state}」中，无法分心他顾。"

# ---------------------------------------------------------------- 炼体轨（W0 双轨）

BODY_COST_SCALE = 0.001   # shortcut: 原版炼体 exp 量级 300 亿，按全局缩放约定 ÷1000，见《数值缩放对照表》


def physique_entry(doc: PlayerDoc, table: list[dict]) -> dict:
    """当前炼体境界行（physique_index 0-based，越界钳到最高）。"""
    idx = max(0, min(int(getattr(doc, "physique_index", 0) or 0), len(table) - 1))
    return table[idx]


def body_breakthrough(
    doc: PlayerDoc,
    table: list[dict],
    xueqi: float,
    rng: random.Random,
    success_bonus: float = 0.0,
    cost_scale: float = BODY_COST_SCALE,
    luck: bool = False,
    cost_factor: float = 1.0,
    rate_bonus: float = 0.0,
    potential_cost: int | None = None,
    cost_reduction: float | None = None,
    one_key: bool = False,
    plane_level: int = 10,
) -> tuple[bool, str, int]:
    """炼体突破（原版 Level.js 炼体支线直译，量级按 cost_scale 缩放）。

    - 消耗血气 = 当前境界行 exp × 体质倍率 × cost_scale × 时代系数（向上取整）
    - 成功率 = max(1%, 1 - (境界+1)/60) + 体质 + 时代加成；luck 把失败部分减半
    - 成功：境界 +1，扣全部消耗；失败：单次 40%/20%/10%/0%，一键额外含 5% 档
    返回 (是否成功, 文案, 应扣血气)。境界自增由本函数完成，扣费由调用方执行。
    """
    idx = int(getattr(doc, "physique_index", 0) or 0)
    if idx >= len(table) - 1:
        return False, f"肉身已至【{table[-1]['level']}】，天地再无进境之路。", 0
    row, nxt = table[idx], table[idx + 1]
    from . import plane
    target_level = int(nxt.get("level_id", idx + 2) or idx + 2)
    world_gate = plane.world_level_gate_message("body", target_level, plane_level)
    if world_gate:
        return False, world_gate, 0
    factor = max(0.05, float(cost_factor))
    talent_cost, talent_rate = physique_breakthrough_bonus(doc)
    if cost_reduction is not None:
        talent_cost = min(1.0, max(0.05, float(cost_reduction)))
    if potential_cost is None:
        potential_cost = player_breakthrough_potential_cost(doc, idx + 1)
    potential = max(0, int(float(doc.ext.get("potential", 0) or 0)))
    if potential < potential_cost:
        return False, f"仙道潜力不足：本次破体需 {potential_cost} 点（当前 {potential}）。", 0
    cost = int(round(float(row.get("exp", 0) or 0) * talent_cost) * cost_scale * factor + 0.999)
    if xueqi < cost:
        return False, f"突破【{nxt['level']}】需血气 {cost:,}（当前 {int(xueqi):,}）。", 0
    prob = max(0.01, 1 - (idx + 1) / 60) + max(-0.9, float(success_bonus or 0)) + talent_rate + float(rate_bonus)
    if luck:
        prob += (1 - prob) * 0.5
    prob = max(0.01, prob)
    if rng.random() < prob:
        doc.physique_index = idx + 1
        doc.ext["potential"] = max(0, potential - potential_cost)
        return True, (f"炼体突破成功，肉身升华！\n"
                      f"【{row['level']}】→【{nxt['level']}】｜血气 -{cost:,}｜潜力 -{potential_cost}"), cost
    roll = rng.random()
    if one_key:
        loss_rate = (0.4, 0.2, 0.1, 0.05, 0.0)[min(4, int(roll * 5))]
    else:
        loss_rate = 0.4 if roll > 0.9 else 0.2 if roll > 0.8 else 0.1 if roll > 0.7 else 0.0
    lost = int(cost * loss_rate)
    return False, ("炼体突破失败！" + (f"气血逆冲，损失 {lost:,} 血气。" if lost else "")), lost


def physique_text(doc: PlayerDoc, table: list[dict]) -> str:
    row = physique_entry(doc, table)
    nxt = table[int(doc.physique_index) + 1] if int(doc.physique_index) < len(table) - 1 else None
    cost_reduction, _ = physique_breakthrough_bonus(doc)
    cost = int(round(float(row.get("exp", 0) or 0) * cost_reduction)
               * BODY_COST_SCALE + 0.999)
    lines = [
        "--- 炼体 ---",
        f"境界：{row['level']}（第 {int(doc.physique_index) + 1} 重）",
        f"肉身：攻 {int(row.get('基础攻击', 0)):,}｜防 {int(row.get('基础防御', 0)):,}"
        f"｜血 {int(row.get('基础血量', 0)):,}｜暴 {float(row.get('基础暴击', 0)):.0%}",
    ]
    if nxt:
        lines.append(f"下境：{nxt['level']}｜突破耗血气 {cost:,}"
                     f"｜潜力 {player_breakthrough_potential_cost(doc, int(doc.physique_index) + 1)}"
                     f"｜成功率 ≥{max(1, int((1 - (int(doc.physique_index) + 1) / 60
                                                   + physique_breakthrough_bonus(doc)[1]) * 100))}%")
    else:
        lines.append("已至炼体顶点。")
    lines.append(f"突破：#炼体突破（原版语义：血气支付，失败气血逆冲）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 一键/幸运（W6-1，对齐原版 Level.js）

ONE_KEY_MAX_ROUNDS = 64       # 防呆轮数；原版无硬上限，本移植以境界表长度为界
TRIB_GATE_REALM = 40          # 无妄真劫境：一键到此为止，后续走 #渡劫 / #登仙


def one_key_break(
    doc: PlayerDoc,
    level_table: list[dict],
    success_rate: float,
    fail_penalty: float,
    rng: random.Random,
    luck: bool = False,
    grass: int = 0,
    cost_factor: float = 1.0,
    rate_bonus: float = 0.0,
    era_note: str = "",
    potential_bonus: float = 0.0,
    plane_level: int = 10,
) -> tuple[str, PlayerDoc, int]:
    """一键突破（原版 OneKeyLevelUp 直译）。

    shortcut: 原版仙道潜力、体质减免、仙宠掉落、战报长图未移植；
    仅保留累计制循环、幸运草 p+(1-p)*0.5、终止条件与统计输出。
    cost_factor / rate_bonus 为 W7-2 时代法则，era_note 是显示用的「当前时代」一行。
    返回 (文案, 新档案, 幸运草消耗)。
    """
    d = doc.model_copy(deep=True)
    start = int(d.realm_index)
    win = fail = used = 0
    reason = "已达单次轮数上限"
    for _ in range(ONE_KEY_MAX_ROUNDS):
        if int(d.realm_index) >= TRIB_GATE_REALM:
            reason = "已至无妄真劫境，须先 #渡劫"
            break
        if luck and used >= grass:
            reason = "幸运草用尽"
            break
        allowed, msg, nd = breakthrough(d, level_table, success_rate, fail_penalty, rng,
                                        cost_factor=cost_factor, rate_bonus=rate_bonus,
                                        luck=luck, potential_bonus=potential_bonus,
                                        plane_level=plane_level)
        if not allowed:
            reason = msg.split("\n")[0]
            break
        if int(nd.realm_index) > int(d.realm_index):
            win += 1
        else:
            fail += 1
        d = nd
        if luck:
            used += 1
    lines = ["--- 一键突破 ---"]
    if era_note:
        lines.append(era_note)
    lines += [f"境界：第 {start + 1} 境 → 第 {int(d.realm_index) + 1} 境",
              f"成功 {win} 次｜失败 {fail} 次"]
    if luck:
        lines.append(f"幸运草消耗 {used} 株")
    lines.append(f"结束原因：{reason}")
    return "\n".join(lines), d, used


def one_key_body(
    doc: PlayerDoc,
    table: list[dict],
    rng: random.Random,
    luck: bool = False,
    grass: int = 0,
    cost_scale: float = BODY_COST_SCALE,
    cost_factor: float = 1.0,
    rate_bonus: float = 0.0,
    success_bonus: float = 0.0,
    era_note: str = "",
    plane_level: int = 10,
) -> tuple[str, PlayerDoc, int]:
    """一键破体（原版 OneKeyMaxUp 直译）。返回 (文案, 新档案, 幸运草消耗)。

    shortcut: 同 one_key_break；失败分档沿用 body_breakthrough 的 40/20/10/0%。
    """
    d = doc.model_copy(deep=True)
    start = int(d.physique_index)
    win = fail = used = 0
    reason = "已达单次轮数上限"
    factor = max(0.05, float(cost_factor))
    for _ in range(ONE_KEY_MAX_ROUNDS):
        idx = int(d.physique_index)
        if idx >= len(table) - 1:
            reason = "肉身已至顶点"
            break
        from . import plane
        target_level = int(table[idx + 1].get("level_id", idx + 2) or idx + 2)
        world_gate = plane.world_level_gate_message("body", target_level, plane_level)
        if world_gate:
            reason = world_gate
            break
        if luck and used >= grass:
            reason = "幸运草用尽"
            break
        need_potential = player_breakthrough_potential_cost(d, idx + 1)
        potential = max(0, int(float(d.ext.get("potential", 0) or 0)))
        if potential < need_potential:
            reason = f"仙道潜力不足（需 {need_potential}，现有 {potential}）"
            break
        xueqi = float(d.ext.get("xueqi", 0) or 0)
        talent_cost, _ = physique_breakthrough_bonus(d)
        need = int(round(float(table[idx].get("exp", 0) or 0) * talent_cost)
                    * cost_scale * factor + 0.999)
        if xueqi < need:
            reason = "血气不足"
            break
        good, _msg, cost = body_breakthrough(
            d, table, xueqi, rng, luck=luck, cost_scale=cost_scale,
            cost_factor=cost_factor, rate_bonus=rate_bonus,
            success_bonus=success_bonus, one_key=True, plane_level=plane_level)
        if cost:
            d.ext["xueqi"] = max(0.0, xueqi - cost)
        if int(d.physique_index) > idx:
            win += 1
        else:
            fail += 1
        if luck:
            used += 1
    lines = ["--- 一键破体 ---"]
    if era_note:
        lines.append(era_note)
    lines += [f"炼体：第 {start + 1} 重 → 第 {int(d.physique_index) + 1} 重",
              f"成功 {win} 次｜失败 {fail} 次"]
    if luck:
        lines.append(f"幸运草消耗 {used} 株")
    lines.append(f"结束原因：{reason}")
    return "\n".join(lines), d, used
