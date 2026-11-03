"""修炼核心逻辑：签到 / 闭关 / 突破（纯函数，无 IO；时间与随机均由外部注入）。"""

from __future__ import annotations

import random
import time
from typing import Any

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
    stones = streak * 300 * realm
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

    planned: int | None = None
    hint = ""
    if minutes is not None:
        planned = max(1, int(minutes))
        if planned > max_minutes:
            planned = max_minutes
            hint = f"（最高 {max_minutes} 分钟，已按上限计算）"
        d.ext["cultivate_minutes"] = planned

    plan_txt = f"计划闭关 {planned} 分钟{hint}" if planned else "未设时长，出关时按实际时间结算"
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
    counted = min(elapsed, max_minutes)
    planned = d.ext.pop("cultivate_minutes", None)
    if planned:
        counted = min(counted, float(planned))
    d.state = "空闲"
    d.state_start = 0.0

    # 周期取整（原版：满足 30 分钟才结算一次，不足不给收益）
    floored = int(counted // period_minutes) * period_minutes if period_minutes > 0 else int(counted)
    if floored < period_minutes:
        return True, "闭关不足一个周期（30 分钟），未能有所精进。", d

    gained = int(floored * exp_per_min)
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
    if planned and elapsed > planned:
        notes.append("已到计划时长，按计划结算")
    elif elapsed > max_minutes:
        notes.append(f"已达单次上限（{max_minutes} 分钟）")
    tail = f"（{'；'.join(notes)}）" if notes else ""
    return True, (
        f"闭关 {int(elapsed)} 分钟（计 {floored} 分钟），"
        f"{'血气增进' if int(float(lian.get('times', 0) or 0)) > 0 else '修为增进'} {gained} 点{tail}。\n"
        f"当前修为：{d.exp}"
    ), d


def breakthrough(
    doc: PlayerDoc,
    level_table: list[dict],
    success_rate: float,
    fail_penalty: float,
    rng: random.Random,
) -> tuple[bool, str, PlayerDoc]:
    """突破：修为达标即可尝试（累计制，成功不扣修为）；失败按比例损耗。

    success_rate/fail_penalty 来自面板配置；原版境界表未含成功率字段。
    """
    if doc.state != "空闲":
        return False, f"道友正在「{doc.state}」中，无法突破。", doc

    i = doc.realm_index + 1
    if i >= len(level_table):
        return False, "道友已臻化境，此界再无更高境界。", doc

    nxt = level_table[i]
    # 语义：境界表当前条目的 exp = 从该境界突破到下一境所需的累计修为
    req = int(level_table[doc.realm_index].get("exp", 0))
    if doc.exp < req:
        return False, (
            f"修为不足，无法突破【{nxt['level']}】。\n"
            f"需求 {req}，当前 {doc.exp}。"
        ), doc

    d = doc.model_copy(deep=True)
    if rng.random() < success_rate:
        d.realm_index = i
        e = level_table[min(i, len(level_table) - 1)]
        d.ext["base_attack"] = e.get("基础攻击", 0)
        d.ext["base_defense"] = e.get("基础防御", 0)
        d.ext["base_hp"] = e.get("基础血量", 0)
        return True, (
            f"天降异象，突破成功！\n当前境界：【{e['level']}】\n"
            f"攻击 {e.get('基础攻击', 0)} · 防御 {e.get('基础防御', 0)} · 血量 {e.get('基础血量', 0)}"
        ), d

    lost = int(req * fail_penalty)
    d.exp = max(0, d.exp - lost)
    return True, (
        f"突破【{nxt['level']}】失败，气息紊乱，修为损耗 {lost} 点。\n当前修为：{d.exp}"
    ), d


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
) -> tuple[bool, str, int]:
    """炼体突破（原版 Level.js 炼体支线直译，量级按 cost_scale 缩放）。

    - 消耗血气 = 当前境界行 exp × cost_scale（向上取整）
    - 成功率 = max(1%, 1 - (境界+1)/60) + success_bonus；luck 把失败部分减半
    - 成功：境界 +1，扣全部消耗；失败：按 40%/20%/10%/0% 分档扣血气
    返回 (是否成功, 文案, 应扣血气)。境界自增由本函数完成，扣费由调用方执行。
    """
    idx = int(getattr(doc, "physique_index", 0) or 0)
    if idx >= len(table) - 1:
        return False, f"肉身已至【{table[-1]['level']}】，天地再无进境之路。", 0
    row, nxt = table[idx], table[idx + 1]
    cost = int(float(row.get("exp", 0) or 0) * cost_scale + 0.999)
    if xueqi < cost:
        return False, f"突破【{nxt['level']}】需血气 {cost:,}（当前 {int(xueqi):,}）。", 0
    prob = max(0.01, 1 - (idx + 1) / 60) + max(0.0, float(success_bonus or 0))
    if luck:
        prob += (1 - prob) * 0.5
    prob = min(0.99, prob)
    if rng.random() < prob:
        doc.physique_index = idx + 1
        return True, (f"炼体突破成功，肉身升华！\n"
                      f"【{row['level']}】→【{nxt['level']}】｜血气 -{cost:,}"), cost
    roll = rng.random()
    if roll > 0.9:
        lost = int(cost * 0.4)
    elif roll > 0.8:
        lost = int(cost * 0.2)
    elif roll > 0.7:
        lost = int(cost * 0.1)
    else:
        lost = 0
    return False, ("炼体突破失败！" + (f"气血逆冲，损失 {lost:,} 血气。" if lost else "")), lost


def physique_text(doc: PlayerDoc, table: list[dict]) -> str:
    row = physique_entry(doc, table)
    nxt = table[int(doc.physique_index) + 1] if int(doc.physique_index) < len(table) - 1 else None
    cost = int(float(row.get("exp", 0) or 0) * BODY_COST_SCALE + 0.999)
    lines = [
        "--- 炼体 ---",
        f"境界：{row['level']}（第 {int(doc.physique_index) + 1} 重）",
        f"肉身：攻 {int(row.get('基础攻击', 0)):,}｜防 {int(row.get('基础防御', 0)):,}"
        f"｜血 {int(row.get('基础血量', 0)):,}｜暴 {float(row.get('基础暴击', 0)):.0%}",
    ]
    if nxt:
        lines.append(f"下境：{nxt['level']}｜突破耗血气 {cost:,}"
                     f"｜成功率 ≥{max(1, int((1 - (int(doc.physique_index) + 1) / 60) * 100))}%")
    else:
        lines.append("已至炼体顶点。")
    lines.append(f"突破：#炼体突破（原版语义：血气支付，失败气血逆冲）")
    return "\n".join(lines)
