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


def _roll_pool(pool: list[dict], rng: random.Random) -> dict:
    """从可用词条池按命格稀有度和负面概率抽取。"""
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


def roll(content: Any, rng: random.Random) -> dict:
    """按稀有度权重抽一条；负面独立概率判定（负面池为空则回退正面池）。"""
    pool = [row for row in _table(content)
            if not row.get("effects")
            or any(key not in _UNSUPPORTED_KEYS for key in row.get("effects", {}))]
    return _roll_pool(pool, rng)


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


_POSITIVE_OMENS = {
    1: "命宫深处，一点星火自混沌中亮起。它虽不曾惊动诸天，却已在无声处为你照见前路。",
    2: "紫气横贯九霄，命星穿过层层天阙。沉寂万载的道钟无风自鸣，似在宣告一位非凡之人的到来。",
    3: "诸天星海骤然黯淡，唯有一颗命星贯穿古今。岁月长河为你停滞半息，三千大道同时垂眸。",
}
_NEGATIVE_OMENS = {
    1: "命轮转动之际，一缕灰雾悄然缠上命星。此厄尚浅，却会在漫漫仙途中如影随形。",
    2: "天机忽乱，命宫染煞，九霄之上的道钟发出一声低沉哀鸣。此命有缺，前路注定多劫。",
    3: "你落名仙籍的一刻，天穹浮现无光黑日，岁月长河倒卷三千丈。大道闭门，诸天星辰皆避其锋。",
}


def _initial_lifespan_delta(doc: PlayerDoc, amount: int, era_index: int | None) -> None:
    if amount == 0:
        return
    from . import lifespan as lifespan_mod

    current = lifespan_mod.shouyuan_of(doc)
    if amount > 0:
        if era_index is not None or "jueling_suppressed_lifespan" in doc.ext:
            from . import era as era_mod
            index = era_mod.JUELING_ERA_INDEX if era_index is None else era_index
            era_mod.add_jueling_aware_lifespan(doc, amount, index)
        else:
            doc.ext["shouyuan"] = current + amount
        return
    if "jueling_suppressed_lifespan" in doc.ext:
        hidden = max(1, int(doc.ext.get("jueling_suppressed_lifespan", current) or 0) + amount)
        doc.ext["jueling_suppressed_lifespan"] = hidden
        doc.ext["shouyuan"] = min(hidden, 9_999)
    else:
        doc.ext["shouyuan"] = max(1, current + amount)


def _initial_effect_delta(doc: PlayerDoc, effects: Mapping[str, Any], sign: int,
                          era_index: int | None = None) -> None:
    ext = doc.ext
    potential = int(float(effects.get("仙道潜力额外", 0) or 0)) * sign
    ext["potential"] = max(0, int(float(ext.get("potential", 0) or 0)) + potential)
    speed = int(float(effects.get("速度", 0) or 0)) * sign
    ext["speed"] = max(1, int(float(ext.get("speed", 100) or 100)) + speed)
    origin = int(float(effects.get("生命本源额外", 0) or 0)) * sign
    ext["mingge_origin"] = max(0, int(ext.get("mingge_origin", 0) or 0) + origin)
    luck = float(effects.get("幸运值", 0) or 0) * sign / 100
    ext["luck"] = float(ext.get("luck", 0) or 0) + luck
    heart_extra = int(float(effects.get("心神额外上限", 0) or 0)) * sign
    ext["mingge_heart_extra"] = max(0, int(ext.get("mingge_heart_extra", 0) or 0) + heart_extra)
    yuanshen_state = ext.get("yuanshen")
    heart = yuanshen_state.get("heart") if isinstance(yuanshen_state, dict) else None
    if heart_extra and isinstance(heart, dict):
        from . import yuanshen as yuanshen_mod
        old_max = int(heart.get("max", 0) or 0)
        old_cap = yuanshen_mod.heart_max(doc) - heart_extra
        old_cap = max(yuanshen_mod.HEART_BASE_MAX, old_cap)
        old_cur = min(old_cap, int(heart.get("cur", 0) or 0))
        heart["max"] = yuanshen_mod.heart_max(doc)
        heart["cur"] = min(int(heart["max"]), max(0, old_cur + heart_extra))
        if old_max <= 0 and heart_extra < 0:
            heart["last"] = 0.0
    _initial_lifespan_delta(
        doc, int(float(effects.get("寿元额外", 0) or 0)) * sign, era_index)


def apply_fate_initial(doc: PlayerDoc, fate: dict[str, Any],
                       era_index: int | None = None) -> bool:
    """Apply one fate snapshot once, including attached fates acquired later."""
    if not fate or fate.get("初始效果已应用"):
        return False
    effects = fate.get("effects") if isinstance(fate.get("effects"), Mapping) else {}
    _initial_effect_delta(doc, effects, 1, era_index)
    fate["初始效果已应用"] = True
    return True


def apply_initial(doc: PlayerDoc, era_index: int | None = None) -> bool:
    """对主命格与旧档附加命格分别补应用一次性初始效果。"""
    changed = False
    fate = identity_of(doc)
    if fate:
        changed = apply_fate_initial(doc, fate, era_index) or changed
        doc.ext["mingge"] = fate
    extras = extra_of(doc)
    for attached in extras:
        changed = apply_fate_initial(doc, attached, era_index) or changed
    if extras:
        doc.ext["mingge_extra"] = extras
    return changed

def rollback_initial(doc: PlayerDoc, fate: Mapping[str, Any], era_index: int | None = None) -> None:
    effects = fate.get("effects") if isinstance(fate.get("effects"), Mapping) else {}
    _initial_effect_delta(doc, effects, -1, era_index)


def draw_message(fate: Mapping[str, Any], player_name: str = "") -> str:
    negative = fate.get("isNegative") is True
    rarity = max(1, min(3, int(fate.get("rarity", 1) or 1)))
    severity = max(1, min(3, int(fate.get("severity", rarity) or rarity)))
    omen = (_NEGATIVE_OMENS[severity] if negative
            else _POSITIVE_OMENS.get(rarity, _POSITIVE_OMENS[1]))
    rank = (f"{fate.get('rarityName', '')}·厄命{('禁忌' if severity == 3 else '深重' if severity == 2 else '微瑕')}"
            if negative else f"{fate.get('rarityName', '')}·{fate.get('category', '')}")
    opening = (f"当【{player_name}】的真名烙入仙籍，沉寂无尽岁月的诸天命盘轰然复苏。"
               if player_name else "当你的真名烙入仙籍，沉寂无尽岁月的诸天命盘轰然复苏。")
    ending = ("「天命有缺，亦非绝路。若敢以凡躯逆伐诸天，厄命终可成为踏碎大道的第一块阶石。」"
              if negative else "「命由天授，道由己争。今日命星归位，自此万劫在前，亦当一念横渡。」")
    lines = ["【诸天命盘·命格初定】", "", opening, omen,
             "一道超越因果的目光自岁月尽头垂落，在你的神魂最深处刻下一枚永世不灭的命印。", "",
             f"命格：【{fate.get('name', '无名命格')}】", f"命阶：【{rank}】",
             f"命格批言：{fate.get('desc', '')}", "", "大道铭文："]
    for key, value in (fate.get("effects") or {}).items():
        try:
            rendered = f"{float(value):+g}" if not isinstance(value, bool) else ("开启" if value else "关闭")
        except (TypeError, ValueError):
            rendered = str(value)
        lines.append(f"  {key}：{rendered}")
    if not fate.get("effects"):
        lines.append("  此命不显于外，唯待岁月印证")
    lines += ["", ending]
    return "\n".join(lines)

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


def extract(doc: PlayerDoc, content: Any, rng: random.Random,
            era_index: int | None = None) -> tuple[bool, str, dict | None]:
    """轮回命签抽一条词条进附加槽（消耗道具由 handler 扣）。"""
    if isinstance(doc.ext.get("mingge_pending"), dict):
        return False, "请先选择或保留当前批量重抽结果，再抽取附加命格。", None
    slots = slots_of(doc)
    if len(extra_of(doc)) >= slots - 1:
        return False, (f"附加命格已满（{max(0, slots - 1)}/{max(0, slots - 1)}）。"
                       f"先用【{SLOT_ITEM}】拓碑或 #改命 换主命格。"), None
    got = roll(content, rng)
    if not got:
        return False, "命格天机暂不可测（词条表缺失）。", None
    rows = list(extra_of(doc))
    apply_fate_initial(doc, got, era_index)
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


def initial_luck(doc: PlayerDoc) -> float:
    """Return accumulated 百分点幸运 while avoiding reliance on unpersisted fate rolls."""
    try:
        return float((doc.ext or {}).get("luck", 0) or 0) * 100.0
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


def reroll(doc: PlayerDoc, content: Any, rng: random.Random,
           era_index: int | None = None) -> tuple[bool, str]:
    """#改命：回滚旧命格初始效果后，再应用新命格一次性属性。"""
    if isinstance(doc.ext.get("mingge_pending"), dict):
        return False, "请先选择或保留当前批量重抽结果，再改换主命格。"
    if int(doc.stones) < REROLL_COST:
        return False, f"改命需 {REROLL_COST:,} 灵石逆天改运（当前 {int(doc.stones):,}）。"
    new = roll(content, rng)
    if not new:
        return False, "命格天机暂不可测（词条表缺失）。"
    old = identity_of(doc)
    old_name = str(old.get("name") or "无名之命")
    if old.get("初始效果已应用"):
        rollback_initial(doc, old, era_index)
    doc.stones -= REROLL_COST
    doc.ext["mingge"] = dict(new)
    apply_initial(doc, era_index)
    return True, (f"【改命】天机重演——{old_name} → 【{new.get('name')}】\n"
                  f"灵石 -{REROLL_COST:,}\n\n{draw_message(new, doc.name or '道友')}")

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
    if isinstance(doc.ext.get("mingge_pending"), dict):
        return False, "当前已有待抉择的批量重抽结果，请先选择或保留后再重抽。"
    count = max(1, min(REROLL_MAX_COUNT, int(count or 1)))
    fates = _fates_of(doc)
    if not fates:
        return False, "你尚无命格（开仙途后自动判定）。"
    if not 1 <= requested <= len(fates):
        return False, f"命格词条序号应为 1 至 {len(fates)}。"
    pool_table = _table(content)
    if not pool_table:
        return False, "命格天机暂不可测（词条表缺失）。"
    # 与单抽一致：排除其它已占用命格与自身，避免重抽回同一条。
    occupied = {str(f.get("id") or f.get("name")) for f in fates}
    pool = [e for e in pool_table
            if (not e.get("effects")
                or any(key not in _UNSUPPORTED_KEYS for key in e.get("effects", {})))
            and str(e.get("id") or e.get("name")) not in occupied]
    if not pool:
        return False, "命格表中没有可替换的未占用词条。"
    # 批量重抽只统计每种命格出现次数，抽样范围必须使用上面的未占用池。
    tally: dict[str, dict] = {}
    for _ in range(count):
        got = _roll_pool(pool, rng)
        if not got:
            return False, "命格天机暂不可测（没有可抽取的词条）。"
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
                        "rarity": int(c["mingge"].get("rarity", 1) or 1),
                        "fate": dict(c["mingge"])}
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


def choose_batch(doc: PlayerDoc, content: Any, pick: int, era_index: int | None = None) -> tuple[bool, str]:
    """批量重抽择定结果；主命格替换时对称回滚/应用一次性初始效果。"""
    pending = doc.ext.get("mingge_pending")
    if not isinstance(pending, dict):
        return False, "当前没有待抉择的轮回命签重抽结果，请先 #消耗轮回命签*序号*次数 批量重抽。"
    cands = pending.get("candidates") or []
    if not 1 <= pick <= len(cands):
        return False, f"请发送 #选择轮回命签*序号（1 至 {len(cands)}），或 #保留轮回命签 保留现有。"
    chosen = cands[pick - 1]
    snapshot = chosen.get("fate")
    if isinstance(snapshot, Mapping):
        mingge = dict(snapshot)
    else:
        table = _table(content)
        mingge = next((e for e in table
                       if str(e.get("id") or e.get("name")) == str(chosen.get("id") or chosen.get("name"))),
                      None)
    if not mingge:
        return False, "所选命格已不在命格表中，当前结果仍保留；可改选其他结果或保留原命格。"
    seq = int(pending.get("seq", 1) or 1)
    old_name = str(pending.get("old_name") or "无名命格")
    current_fates = _fates_of(doc)
    if not 1 <= seq <= len(current_fates):
        return False, "批量重抽目标已变化，当前命格未修改；请保留原命格后重新抽取。"
    old_fate = current_fates[seq - 1]
    old_key = str(pending.get("old_id") or pending.get("old_name") or "")
    current_key = str(old_fate.get("id") or old_fate.get("name") or "")
    if old_key != current_key:
        return False, "批量重抽期间目标命格已变化，当前命格未修改；请先保留旧结果。"
    new_key = str(mingge.get("id") or mingge.get("name") or "")
    if any(i != seq and str(f.get("id") or f.get("name") or "") == new_key
           for i, f in enumerate(current_fates, 1)):
        return False, "所选命格已在其他命格槽中，当前结果不能重复占槽。"
    if old_fate.get("初始效果已应用"):
        rollback_initial(doc, old_fate, era_index)
    doc.ext.pop("mingge_pending", None)
    stored = dict(mingge)
    if seq == 1:
        doc.ext["mingge"] = stored
        apply_fate_initial(doc, stored, era_index)
    else:
        rows = list(extra_of(doc))
        while len(rows) < seq - 1:
            rows.append({})
        rows[seq - 2] = stored
        apply_fate_initial(doc, stored, era_index)
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
