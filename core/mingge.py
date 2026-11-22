"""命格（W2-3，对齐原版 model/mingge.js）。

原版语义：
- 75 条词条（data/item/命格词条.json）：rarity 1-3 权重 70/25/5，13 条负面
  （默认负面概率 12%），effects 多字段（ attack/defense/hp/暴击/突破成功率/签到倍率…）。
- getMinggeEffects：主命格 + 附加命格合并（bonus 加法 / direct-multiplier 乘法 / boolean 或）。

本移植按效果键接入战斗、修炼、生活职业、源石坊、元神与秘境消费点；
新增效果应同步补齐消费端与回归用例，避免只展示不生效。
W7-1：补命宫拓碑扩槽（≤3）、轮回命签抽取附加词条、主+附加 effects 合并。
"""

from __future__ import annotations

import random
from typing import Any, Mapping

from .player import PlayerDoc

RARITY_WEIGHTS = {1: 70, 2: 25, 3: 5}
NEGATIVE_CHANCE = 0.12
REROLL_COST = 100_000          # #改命 灵石（原版无重抽通道，自定）
MAX_SLOTS = 3                  # 原版「命宫拓碑」最多 3 条命格
SLOT_ITEM = "命宫拓碑"
EXTRACT_ITEM = "轮回命签"
_MULT_KEYS = {"签到奖励倍率", "内景地消耗倍率", "出售价格倍率"}   # 同类倍率相乘；其余数值字段按加法
_UNSUPPORTED_KEYS = {"内景地开启概率"}  # 内景地开辟为付费必成，不提供虚假的成功率效果

_CONSUMED_KEYS = {
    "攻击加成": 1.0, "防御加成": 1.0, "生命加成": 1.0,
    "暴击加成": 1.0, "境界突破成功率": 1.0, "渡劫修为减少": 1.0,
}


def _table(content: Any) -> list[dict]:
    t = content.table("item/命格词条") if content else None
    return t if isinstance(t, list) else []


def roll(content: Any, rng: random.Random) -> dict:
    """按稀有度权重抽一条；负面独立概率判定（负面池为空则回退正面池）。"""
    pool = [row for row in _table(content)
            if not row.get("effects")
            or any(key not in _UNSUPPORTED_KEYS for key in row.get("effects", {}))]
    if not pool:
        return {}
    rarities = sorted({int(e.get("rarity", 1) or 1) for e in pool})
    weights = [(r, RARITY_WEIGHTS.get(r, 0)) for r in rarities if RARITY_WEIGHTS.get(r, 0) > 0]
    total = sum(w for _, w in weights) or 1
    pick_r, roll_v = rarities[0], rng.random() * total
    acc = 0.0
    for r, w in weights:
        acc += w
        if roll_v < acc:
            pick_r = r
            break
    tier = pick_r if rng.random() >= NEGATIVE_CHANCE else -pick_r
    sub = [e for e in pool
           if int(e.get("rarity", 1) or 1) == pick_r
           and (bool(e.get("isNegative")) if tier < 0 else not bool(e.get("isNegative")))]
    if not sub:
        sub = [e for e in pool if int(e.get("rarity", 1) or 1) == pick_r]
    return dict(rng.choice(sub) if sub else pool[0])


def identity_of(doc: PlayerDoc) -> dict:
    """当前命格（ext["mingge"]，存整条词条快照）。"""
    v = doc.ext.get("mingge")
    return dict(v) if isinstance(v, dict) else {}


def ensure(doc: PlayerDoc, content: Any, rng: random.Random) -> dict:
    """无命格则补抽（开仙途/首次查看时）。"""
    cur = identity_of(doc)
    if cur:
        return cur
    cur = roll(content, rng)
    if cur:
        doc.ext["mingge"] = cur
    return cur


def slots_of(doc: PlayerDoc) -> int:
    """当前命格槽位数（默认 1，命宫拓碑最多扩到 3）。"""
    try:
        return min(MAX_SLOTS, max(1, int(doc.ext.get("mingge_slots", 1) or 1)))
    except (TypeError, ValueError):
        return 1


def extra_of(doc: PlayerDoc) -> list[dict]:
    """附加命格（最多 slots-1 条）。"""
    v = doc.ext.get("mingge_extra")
    rows = [dict(x) for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    return rows[:max(0, slots_of(doc) - 1)]


def effects_of(doc: PlayerDoc) -> dict:
    """主命格 + 附加命格合并（数值加法 / 倍率乘法 / bool 或）。"""
    out: dict = {}
    for m in [identity_of(doc), *extra_of(doc)]:
        for k, v in (m.get("effects") or {}).items():
            if k in _UNSUPPORTED_KEYS:
                continue
            if k not in out:
                out[k] = v
                continue
            a = out[k]
            if isinstance(a, bool) or isinstance(v, bool):
                out[k] = bool(a) or bool(v)
            elif k in _MULT_KEYS:
                try:
                    out[k] = float(a) * float(v)
                except (TypeError, ValueError):
                    out[k] = v
            else:
                try:
                    out[k] = float(a) + float(v)
                except (TypeError, ValueError):
                    out[k] = v
    return out


def expand_slot(doc: PlayerDoc) -> tuple[bool, str]:
    """命宫拓碑：扩 1 槽（消耗道具由 handler 扣）。"""
    cur = slots_of(doc)
    if cur >= MAX_SLOTS:
        return False, f"命宫已拓至 {MAX_SLOTS} 碑，再无余位。"
    doc.ext["mingge_slots"] = cur + 1
    return True, (f"【命宫拓碑】碑文再开一页，命格槽位 {cur} → {cur + 1}（上限 {MAX_SLOTS}）。"
                  f"消耗【{SLOT_ITEM}】×1，可用【{EXTRACT_ITEM}】抽取附加词条。")


def extract(doc: PlayerDoc, content: Any, rng: random.Random) -> tuple[bool, str, dict | None]:
    """轮回命签抽一条词条进附加槽（消耗道具由 handler 扣）。"""
    slots = slots_of(doc)
    if len(extra_of(doc)) >= slots - 1:
        return False, (f"附加命格已满（{max(0, slots - 1)}/{max(0, slots - 1)}）。"
                       f"先用【{SLOT_ITEM}】拓碑或 #改命 换主命格。"), None
    got = roll(content, rng)
    if not got:
        return False, "命格天机暂不可测（词条表缺失）。", None
    rows = list(extra_of(doc))
    rows.append(got)
    doc.ext["mingge_extra"] = rows
    neg = "（此命有缺）" if got.get("isNegative") else ""
    return True, (f"【轮回命签】命轮一转，得附加命格【{got.get('name')}】{neg}\n"
                  f"{got.get('desc', '')}\n"
                  f"当前 {len(rows)}/{slots - 1} 个附加槽已用，效果与主命格合并生效。"), got


def bonus(doc: PlayerDoc, key: str) -> float:
    """bonus-rate/chance 类取值（加法合并）。"""
    v = effects_of(doc).get(key, 0)
    try:
        return max(0.0, float(v) if not isinstance(v, bool) else float(v))
    except (TypeError, ValueError):
        return 0.0


def signed_bonus(doc: PlayerDoc, key: str) -> float:
    """读取可正可负的命格修正（突破成功率等）。"""
    v = effects_of(doc).get(key, 0)
    try:
        return float(v) if not isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return 0.0


def multiplier(doc: PlayerDoc, key: str) -> float:
    """direct-multiplier 类取值（乘法，缺省 1）。"""
    v = effects_of(doc).get(key, 1)
    try:
        f = float(v)
        return f if f > 0 else 1.0
    except (TypeError, ValueError):
        return 1.0


def reroll(doc: PlayerDoc, content: Any, rng: random.Random) -> tuple[bool, str]:
    """#改命：花灵石重抽（负面命格也能改）。"""
    if int(doc.stones) < REROLL_COST:
        return False, f"改命需 {REROLL_COST:,} 灵石逆天改运（当前 {int(doc.stones):,}）。"
    new = roll(content, rng)
    if not new:
        return False, "命格天机暂不可测（词条表缺失）。"
    old_name = str(identity_of(doc).get("name") or "无名之命")
    doc.stones -= REROLL_COST
    doc.ext["mingge"] = new
    neg = "（此命有缺，多劫多磨）" if new.get("isNegative") else ""
    return True, (f"【改命】天机重演——{old_name} → 【{new.get('name')}】{neg}\n"
                  f"{new.get('desc', '')}\n"
                  f"效果：{'、'.join(f'{k}+{v:g}' if not isinstance(v, bool) else k for k, v in (new.get('effects') or {}).items())}\n"
                  f"灵石 -{REROLL_COST:,}")


def text(doc: PlayerDoc) -> str:
    m = identity_of(doc)
    if not m:
        return "--- 命格 ---\n命格未定（#改命 可窥探天机）。"
    neg = "⚠ 负面命格" if m.get("isNegative") else f"{m.get('rarityName', '')}命格"
    eff = m.get("effects") or {}
    eff_txt = "、".join(f"{k} {'+' if not isinstance(v, bool) else ''}{v:g}"
                        if not isinstance(v, bool) else k for k, v in eff.items())
    slots = slots_of(doc)
    extras = extra_of(doc)
    lines = ["--- 命格 ---",
             f"命宫：{slots}/{MAX_SLOTS} 槽（主 1 + 附加 {len(extras)}/{max(0, slots - 1)}）",
             f"主命格【{m.get('name')}】（{neg}｜{m.get('category', '')}）",
             str(m.get("desc") or ""),
             f"总效果：{'、'.join(f'{k} {v:g}' if not isinstance(v, bool) else k for k, v in effects_of(doc).items()) or '无'}"]
    for i, e in enumerate(extras, 1):
        lines.append(f"· 附加 {i}【{e.get('name')}】{'⚠负面' if e.get('isNegative') else ''}")
    lines.append(f"改命：#改命（{REROLL_COST:,} 灵石）｜拓碑：#命宫拓碑（{SLOT_ITEM}×1）"
                 f"｜抽词条：#抽取命格词条（{EXTRACT_ITEM}×1）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 轮回命签·批量重抽（W29 补漏：原版 UserHome.js batchRerollFate）

REROLL_MAX_COUNT = 999


def _fates_of(doc: PlayerDoc) -> list[dict]:
    """[主命格, *附加命格] 统一序号视图（原版 fates 数组）。"""
    return [identity_of(doc), *extra_of(doc)] if identity_of(doc) else extra_of(doc)


def _fmt_effects(m: Mapping) -> str:
    return "，".join(f"{k}+{v:g}" if not isinstance(v, bool) else k
                     for k, v in (m.get("effects") or {}).items()
                     if k not in _UNSUPPORTED_KEYS)


def batch_reroll(doc: PlayerDoc, content: Any, rng: random.Random,
                 requested: int, count: int) -> tuple[bool, str]:
    """#消耗轮回命签*序号*次数：批量重抽只统计分布、不改动命格；
    结果暂存 ext["mingge_pending"]，待 #选择轮回命签 / #保留轮回命签 抉择。
    消耗道具由 handler 扣。"""
    count = max(1, min(REROLL_MAX_COUNT, int(count or 1)))
    fates = _fates_of(doc)
    if not fates:
        return False, "你尚无命格（开仙途后自动判定）。"
    if not 1 <= requested <= len(fates):
        return False, f"命格词条序号应为 1 至 {len(fates)}。"
    pool_table = _table(content)
    if not pool_table:
        return False, "命格天机暂不可测（词条表缺失）。"
    # 与单抽一致：排除其它已占用命格与自身，避免重抽回同一条
    occupied = {str(f.get("id") or f.get("name"))
                for i, f in enumerate(fates) if i != requested - 1}
    occupied.add(str(fates[requested - 1].get("id") or fates[requested - 1].get("name")))
    pool = [e for e in pool_table
            if str(e.get("id") or e.get("name")) not in occupied] or pool_table
    # 批量重抽，只统计每种命格出现次数
    tally: dict[str, dict] = {}
    for _ in range(count):
        got = roll(content, rng)
        key = str(got.get("id") or got.get("name"))
        entry = tally.setdefault(key, {"mingge": got, "count": 0})
        entry["count"] += 1
    candidates = sorted(tally.values(),
                        key=lambda c: (-int(c["mingge"].get("rarity", 1) or 1),
                                       -c["count"]))
    doc.ext["mingge_pending"] = {
        "seq": requested, "count": count,
        "candidates": [{"name": c["mingge"].get("name"),
                        "id": c["mingge"].get("id"),
                        "count": c["count"],
                        "isNegative": bool(c["mingge"].get("isNegative")),
                        "rarity": int(c["mingge"].get("rarity", 1) or 1)}
                       for c in candidates],
        "old_name": str(fates[requested - 1].get("name") or "无名命格"),
        "old_id": fates[requested - 1].get("id"),
    }
    list_text = "\n".join(
        f"{i}. {c['mingge'].get('name')}"
        f"（{'稀有度' + str(c['mingge'].get('rarity', 1))}"
        f"{'·厄' if c['mingge'].get('isNegative') else ''}）×{c['count']}"
        + (f"\n    {_fmt_effects(c['mingge'])}" if c["mingge"].get("effects") else "")
        for i, c in enumerate(candidates, 1))
    return True, ("\n".join([
        "【轮回命签·批量重抽】",
        f"对第{requested}命格【{fates[requested - 1].get('name')}】重抽了 {count} 次"
        f"（消耗轮回命签 {count} 枚）。", "",
        "本次抽中命格分布：",
        list_text, "",
        "请抉择（命签已消耗，二选一）：",
        "· #选择轮回命签*序号 保留重抽结果中你想要的那条",
        "· #保留轮回命签 保留现有命格不变"]))


def choose_batch(doc: PlayerDoc, content: Any, pick: int) -> tuple[bool, str]:
    """#选择轮回命签*N：从分布中择一条替换该命格（旧初始效果即词条快照整体
    替换，端口 effects 全部读快照、无一次性「获得时」副作用，无需回滚）。"""
    pending = doc.ext.get("mingge_pending")
    if not isinstance(pending, dict):
        return False, "当前没有待抉择的轮回命签重抽结果，请先 #消耗轮回命签*序号*次数 批量重抽。"
    cands = pending.get("candidates") or []
    if not 1 <= pick <= len(cands):
        return False, f"请发送 #选择轮回命签*序号（1 至 {len(cands)}），或 #保留轮回命签 保留现有。"
    chosen = cands[pick - 1]
    table = _table(content)
    mingge = next((e for e in table
                   if str(e.get("id") or e.get("name")) == str(chosen.get("id") or chosen.get("name"))),
                  None)
    seq = int(pending.get("seq", 1) or 1)
    old_name = str(pending.get("old_name") or "无名命格")
    doc.ext.pop("mingge_pending", None)
    if not mingge:
        return False, "所选命格已不在命盘之中，暂存已清除。"
    stored = dict(mingge)
    if seq == 1:
        doc.ext["mingge"] = stored
    else:
        rows = list(extra_of(doc))
        while len(rows) < seq - 1:
            rows.append({})
        rows[seq - 2] = stored
        doc.ext["mingge_extra"] = rows[:max(0, slots_of(doc) - 1)]
    neg = "（此命有缺，多劫多磨）" if mingge.get("isNegative") else ""
    return True, ("\n".join([
        "【轮回命签·重定命数】",
        f"第{seq}命格：{old_name} → 【{mingge.get('name')}】{neg}",
        str(mingge.get("desc") or ""),
        f"效果：{_fmt_effects(mingge) or '无'}"]))


def keep_batch(doc: PlayerDoc) -> str:
    """#保留轮回命签：弃结果保现状（命签已由批量重抽时消耗）。"""
    pending = doc.ext.pop("mingge_pending", None)
    if not isinstance(pending, dict):
        return "当前没有待抉择的轮回命签重抽结果。"
    return (f"【轮回命签·纹丝不动】你选择保留现有第{pending.get('seq')}命格"
            f"【{pending.get('old_name')}】，重抽结果已舍弃（命签已消耗）。")


def switch_reroll(doc: PlayerDoc, seq: int | None) -> str:
    """#切换重抽命格 序号：设默认重抽目标（#消耗轮回命签 不带序号时用）。"""
    fates = _fates_of(doc)
    if seq is None:
        cur = doc.ext.get("mingge_reroll_seq")
        return (f"当前默认重抽目标：第 {cur} 命格【{_fates_of(doc)[int(cur) - 1].get('name') if cur and _fates_of(doc) and int(cur) <= len(_fates_of(doc)) else '?'}】"
                if cur else "尚未设置默认重抽目标（#切换重抽命格 序号）。")
    if not fates or not 1 <= seq <= len(fates):
        return f"命格词条序号应为 1 至 {len(fates)}。"
    doc.ext["mingge_reroll_seq"] = int(seq)
    return (f"默认重抽目标已切换为第 {seq} 命格【{fates[seq - 1].get('name')}】。\n"
            f"发送 #消耗轮回命签*次数 即可对其批量重抽。")
