"""帝路五档雷劫（W9-F1）——原版 `apps/User/zhetiandujie.js` L657-2341
（duzhendaoLeijie / shengrenleijie / shengrenwangleijie / dashengleijie / zhundileijie）
的纯函数移植，衔接 `core/zhengdao` 的证道成帝链。

原版语义：
- 五档雷劫是秘境体系的进阶劫：斩道（秘境 10 圣主巅峰）→ 圣人 → 圣人王 →
  大圣 → 准帝，逐档消耗仙道潜力 1~5 点 + 修为血气（斩道档 2^9×500000，
  乘时代系数 eraCostRates=[0.7,0.8,1.0,1.5,2.0]）。
- 每档 3~4 阶段（道心拷问 9 波 / 法则枷锁 9 波 / 古今道影 9 波 / 斩道天刀…），
  渡劫中禁外物，可 #打散雷劫、#复活设置 自动/手动。

本移植（shortcut）：
- 秘境等级轨未开放（core/authority.py 注册制），五档折算为**权柄门槛**
  10/12/14/16/18（衔接 zhengdao.PROVE_GATE=20 准帝九重天）；同档不可重复渡。
- 多阶段异步雷劫同步化：每阶段一次判定，逐段文案聚合输出；威力按双轨境界
  折算，不读「理论最大攻击」。
- 修为血气 = 256,000（原 2^9×50万 ÷1000）× 2^档 × 时代 qi_cost；
  潜力 1~5 点（doc.ext["potential"]）。
- 成功不抬秘境等级，改为**帝威 +0.1/档**（写入 zhengdao.power_bonus，复用既有
  战斗增伤乘区）；失败道伤 +1（霜华减半）、修为血气 -25%，复活功法链复用 trib。
- #打散雷劫：权柄 ≥16 者对本档**保底通过**，消耗 ×2、帝威翻倍（原版为
  渡劫中提前结束+奖励翻倍，本移植无进行时状态，折算为保底速通）。
"""

from __future__ import annotations

from .wallet import authority as _authority, set_xueqi as _set_xueqi, xueqi as _xueqi

import random
import time
from typing import Any, Mapping

EXT_KEY = "daolu"

BASE_COST = 256_000           # 原版 2^9 × 500,000 ÷1000（斩道档）
MIGHT_PER_TIER = 0.1          # 每档帝威加成
DISPERSE_GATE = 16            # #打散雷劫 折算门槛（原版肉身玄圣/道宫五重天）
WOUND_ON_FAIL = 1.0
EXP_LOSS_RATIO = 0.25

TIERS: tuple[dict[str, Any], ...] = (
    {"key": "zhanchao", "name": "斩道", "gate": 10, "potential": 1, "mult": 1,
     "waves": ("道心拷问", "法则枷锁", "斩道天刀")},
    {"key": "shengren", "name": "圣人", "gate": 12, "potential": 2, "mult": 2,
     "waves": ("道心拷问", "法则枷锁", "古今道影")},
    {"key": "shengrenwang", "name": "圣人王", "gate": 14, "potential": 3, "mult": 4,
     "waves": ("道心拷问", "法则枷锁", "古今道影", "圣人王天罚")},
    {"key": "dasheng", "name": "大圣", "gate": 16, "potential": 4, "mult": 8,
     "waves": ("道心拷问", "法则枷锁", "古今道影", "大圣雷池")},
    {"key": "zhundi", "name": "准帝", "gate": 18, "potential": 5, "mult": 16,
     "waves": ("道心拷问", "法则枷锁", "古今道影", "准帝劫云")},
)
TIER_INDEX = {t["name"]: t for t in TIERS}

# 每阶段成功率乘数（后段愈险）
STAGE_MULT = (1.0, 0.85, 0.7, 0.55)
BASE_CHANCE = 0.62


def _defaults() -> dict[str, Any]:
    return {"passed": -1, "fails": 0, "dispersed": 0, "history": []}


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[EXT_KEY] = dict(st)


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = _defaults()
    if isinstance(raw, dict):
        st.update(raw)
    raw_passed = st.get("passed", -1)
    st["passed"] = -1 if raw_passed is None else int(raw_passed)
    st["fails"] = int(st.get("fails", 0) or 0)
    st["dispersed"] = int(st.get("dispersed", 0) or 0)
    if not isinstance(st.get("history"), list):
        st["history"] = []
    save(doc, st)
    return st


def panel(doc: Any) -> str:
    st = state_of(doc)
    nxt = TIERS[st["passed"] + 1] if st["passed"] + 1 < len(TIERS) else None
    lines = [
        "--- 帝路雷劫 ---",
        f"已渡：{'、'.join(t['name'] for t in TIERS[:st['passed'] + 1]) or '尚未开渡'}"
        f"｜失败 {st['fails']} 次｜速通 {st['dispersed']} 次",
        ("下一档：" f"【{nxt['name']}雷劫】权柄 ≥{nxt['gate']}｜仙道潜力 {nxt['potential']} 点"
         f"｜修为血气各 {BASE_COST * nxt['mult']:,}×时代系数") if nxt else "五档尽渡——可 #证道成帝（权柄 ≥20）",
        "规则：#帝路规则",
    ]
    return "\n".join(lines)


def rules_text() -> str:
    rows = "\n".join(
        f"· 【{t['name']}雷劫】权柄 ≥{t['gate']}｜潜力 {t['potential']} 点｜"
        f"修为血气各 {BASE_COST * t['mult']:,}×时代｜阶段：{'→'.join(t['waves'])}"
        for t in TIERS
    )
    return "\n".join([
        "--- 帝路雷劫规则 ---", rows,
        "· 同档不可重复渡；成功帝威 +0.1/档（战斗增伤）；失败道伤 +1、修为血气 -25%",
        "· 复活：#复活设置 自动/手动；#打散雷劫（权柄 ≥16 保底速通，消耗 ×2、帝威翻倍）",
        "· 五档尽渡后 #证道成帝（权柄 ≥20）",
    ])


def _era_cost_rate(era: Mapping[str, Any] | None) -> float:
    try:
        return max(0.1, float((era or {}).get("qi_cost", 1.0) or 1.0))
    except Exception:
        return 1.0


def find_tier(name: str) -> dict[str, Any] | None:
    n = (name or "").strip().removeprefix("渡").removesuffix("雷劫")
    return TIER_INDEX.get(n)


def _charge(doc: Any, tier: dict[str, Any], era: Mapping[str, Any] | None) -> int:
    return max(1, int(BASE_COST * tier["mult"] * _era_cost_rate(era)))


def _pay(doc: Any, tier: dict[str, Any], cost: int,
         delta: dict[str, int]) -> str | None:
    """扣潜力/修为/血气；不足返回错误文案。"""
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < tier["potential"]:
        return f"仙道潜力不足：本档需 {tier['potential']} 点（现有 {pot}），每日任务与剧情支线可得。"
    if int(getattr(doc, "exp", 0) or 0) < cost or _xueqi(doc) < cost:
        return (f"渡【{tier['name']}雷劫】需修为与血气各 {cost:,}（当前 "
                f"{int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}）。")
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["potential"] = pot - tier["potential"]
    doc.exp = int(getattr(doc, "exp", 0) or 0) - cost
    _set_xueqi(doc, _xueqi(doc) - cost)
    return None


def run(doc: Any, tier_name: str, era: Mapping[str, Any] | None = None,
        now: float | None = None, rng: random.Random | None = None,
        ) -> tuple[bool, str, dict[str, int]]:
    """#渡斩道雷劫 等：五档帝路雷劫，逐阶段判定、文案聚合。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    tier = find_tier(tier_name)
    if tier is None:
        return False, "帝路五档：#渡斩道雷劫 / #渡圣人雷劫 / #渡圣人王雷劫 / #渡大圣雷劫 / #渡准帝雷劫。", {}
    st = state_of(doc)
    cur_idx = int(st["passed"])
    cur = TIERS[cur_idx] if 0 <= cur_idx < len(TIERS) else None
    if cur is not None and cur["name"] == tier["name"]:
        return False, f"【{tier['name']}雷劫】你已渡过此档，无需重渡。", {}
    nxt = TIERS[cur_idx + 1] if 0 <= cur_idx + 1 < len(TIERS) else None
    if nxt is None or nxt["name"] != tier["name"]:
        if nxt is None:
            return False, "帝路五档皆渡——大道在前，可 #证道成帝（权柄 ≥20）。", {}
        return False, (f"帝路须逐档而进：下一档为【{nxt['name']}雷劫】，"
                       f"不可越级挑战【{tier['name']}雷劫】。"), {}
    if _authority(doc) < tier["gate"]:
        return False, f"【{tier['name']}雷劫】需权柄 ≥{tier['gate']}，当前 {_authority(doc)}。", {}
    try:
        from . import zhengdao as _dz
        w = _dz.peek(doc)
        if w >= 3.0:
            return False, (f"身负道伤 {w:.1f} ≥3，劫云不认残破之基——"
                           "先 #修复道伤 / #道基重塑 祛伤。"), {}
    except Exception:
        pass
    cost = _charge(doc, tier, era)
    err = _pay(doc, tier, cost, {})
    if err:
        return False, err, {}

    try:
        from . import zhengdao as _dz
        penalty = float(_dz.effects(doc, now)["chance_penalty"])
    except Exception:
        penalty = 0.0
    base = max(0.12, BASE_CHANCE - penalty * 0.5)
    stages = list(zip(tier["waves"], STAGE_MULT))
    log: list[str] = []
    for i, (wname, sm) in enumerate(stages):
        p = max(0.08, base * sm)
        won = rng.random() < p
        mark = "✔" if won else "✘"
        log.append(f"{mark} {wname}（{p:.0%}）")
        if not won:
            st = state_of(doc)
            st["fails"] = int(st["fails"]) + 1
            st["history"] = (list(st["history"]) + [f"{tier['name']}·{wname} 失守"])[:10]
            save(doc, st)
            exp_before = int(getattr(doc, "exp", 0) or 0)
            hp_before = float((getattr(doc, "ext", {}) or {}).get("hp", 1) or 1)
            loss = int(exp_before * EXP_LOSS_RATIO)
            doc.exp = exp_before - loss
            _set_xueqi(doc, int(_xueqi(doc) * (1 - EXP_LOSS_RATIO)))
            wnote = ""
            try:
                from . import zhengdao as _dz
                wound = _dz.add_wounds(doc, WOUND_ON_FAIL, f"{tier['name']}雷劫失败", now,
                                       halve=_dz.frost_active(doc))
                wnote = f"｜道伤 +{WOUND_ON_FAIL:g}（现 {wound:.1f}）"
            except Exception:
                pass
            revive_note = ""
            try:
                from . import trib as _tb
                choices = _tb.available_revival_skills(doc)
                if choices and _tb.revive_mode(doc) == "自动":
                    revive_note = "\n" + _tb.apply_revive(doc, exp_before, hp_before, choices[0])
                elif choices:
                    _tb.arm_revive(doc, exp_before, hp_before, now, choices)
                    revive_note = "\n60 秒内使用 #复活选择 序号或功法名可抵消本次损耗。"
            except Exception:
                pass
            log_text = "\n".join(log)
            msg = (f"≡≡≡ {tier['name']}雷劫 · 失败 ≡≡≡\n{log_text}\n"
                   f"雷劫轰体，道基震动——修为 -{loss:,}、血气同损{wnote}。{revive_note}")
            return False, msg, {}
    st = state_of(doc)
    st["passed"] = next(i for i, t in enumerate(TIERS) if t["name"] == tier["name"])
    st["history"] = (list(st["history"]) + [f"{tier['name']}雷劫 渡过"])[:10]
    save(doc, st)
    try:
        from . import zhengdao as _dz
        _st = _dz.state_of(doc, now)
        _st["power_bonus"] = round(min(3.0, float(_st.get("power_bonus", 0) or 0) + MIGHT_PER_TIER), 3)
        _dz.save(doc, _st)
        might_note = f"｜帝威 +{MIGHT_PER_TIER:.0%}"
    except Exception:
        might_note = ""
    log_text = "\n".join(log)
    return True, (f"≡≡≡ {tier['name']}雷劫 · 渡过 ≡≡≡\n{log_text}\n"
                  f"雷劫淬道，法则让路——【{tier['name']}】之境已成！\n"
                  f"消耗潜力 {tier['potential']} 点、修为血气各 {cost:,}{might_note}"), {}


def disperse(doc: Any, tier_name: str, era: Mapping[str, Any] | None = None,
             now: float | None = None, rng: random.Random | None = None,
             ) -> tuple[bool, str, dict[str, int]]:
    """#打散雷劫：权柄 ≥16 者保底速通本档，消耗 ×2、帝威翻倍。"""
    now = time.time() if now is None else float(now)
    tier = find_tier(tier_name)
    if tier is None:
        return False, "用法：#打散雷劫 斩道/圣人/圣人王/大圣/准帝。", {}
    if _authority(doc) < DISPERSE_GATE:
        return False, f"打散雷劫需权柄 ≥{DISPERSE_GATE}（当前 {_authority(doc)}），肉身不够硬会当场炸开。", {}
    st = state_of(doc)
    cur_idx = int(st["passed"])
    cur = TIERS[cur_idx] if 0 <= cur_idx < len(TIERS) else None
    if cur is not None and cur["name"] == tier["name"]:
        return False, f"【{tier['name']}雷劫】已渡过，无需打散。", {}
    nxt = TIERS[cur_idx + 1] if 0 <= cur_idx + 1 < len(TIERS) else None
    if nxt is None or nxt["name"] != tier["name"]:
        return False, "帝路须逐档而进，不可越级打散。", {}
    cost = _charge(doc, tier, era) * 2
    err = _pay(doc, tier, cost, {})
    if err:
        return False, err, {}
    st = state_of(doc)
    st["passed"] = next(i for i, t in enumerate(TIERS) if t["name"] == tier["name"])
    st["dispersed"] = int(st["dispersed"]) + 1
    st["history"] = (list(st["history"]) + [f"{tier['name']}雷劫 打散速通"])[:10]
    save(doc, st)
    try:
        from . import zhengdao as _dz
        _st = _dz.state_of(doc, now)
        _st["power_bonus"] = round(min(3.0, float(_st.get("power_bonus", 0) or 0) + MIGHT_PER_TIER * 2), 3)
        _dz.save(doc, _st)
        might_note = f"｜帝威 +{MIGHT_PER_TIER * 2:.0%}"
    except Exception:
        might_note = ""
    return True, (f"【打散雷劫 · {tier['name']}】一拳轰散九霄劫云，此档保底而过！\n"
                  f"消耗潜力 {tier['potential']} 点、修为血气各 {cost:,}（双倍）{might_note}"), {}
