"""悟道与道途（W9-F2）——原版 `apps/User/wudaoRules.js`（规则核心）+
`Level.js wudao / nihuojiushi` + `wudaoTea.js` 的纯函数移植。

原版语义：
- 斩道王者后 `#悟道` 参悟当前己道节点：王者道则→圣道→圣王→大圣→准帝→
  红尘仙道→仙王道则→诸天道则；每节点 targetExp 600~76800，阶段
  初悟(0~1/6)→小成(1/6)→大成(1/2)→圆满(targetExp)。
- 每日 3 次（【大衍悟道丹】可续 1 次）；成功率 `0.7+元神超额×0.05` 封顶 0.95；
  失败按 0~100% 比例损失资源（【悟道古茶】减半、顿悟 +10pp）；顿悟
  `0.02+命格+0.1(茶)` ≤0.25，双倍收益。
- 消耗：潜力=(秘境+仙古)×100、修为=血气 2,000,000×levelSum²、
  灵石 10,000,000×levelSum、寿元 20万~12亿（按节点）。
- 收益 = base ×(1+体质/时代/天资/功法/命格/理想 0.2 加成，clamp 0.5~2.5)
  ×随机 0.9~1.1；`#悟道古茶` 消耗后下次悟道生效。

本移植（shortcut）：
- 潜力 = 100×(节点序+1)（原版按秘境+仙古等级，本移植无独立等级轨）；
  修为=血气 = 2,000×levelSum²、灵石 = 10,000×levelSum（÷1000）；
  节点寿元 200~1,200,000 年（原 20万~12亿 ÷1000），寿元不足直接拒绝。
- 元神超额 = `yuanshen.level_of(doc)` − 节点元神需求（原版为元神值档位）。
- 体质加成取六档圣体系数（+5%~+45%），功法加成取 `trib.best_stage` 数值档；
  时代/天资/理想加成暂不接入（shortcut）。
- 道伤联动：成功率 −chance_penalty、收益 ×dao_multiplier（复用 zhengdao）。
- `#悟道古茶` 折算为消耗 1 枚置一次性 buff，下次悟道结算时消耗。
"""

from __future__ import annotations
from .clock import day_key

import math
import random
import time
from typing import Any, Mapping

from .wallet import authority as _authority
from .player import PlayerDoc

EXT_KEY = "wudao"

DAILY_LIMIT = 3
DAILY_EXTEND_ITEM = "大衍悟道丹"
TEA_ITEM = "悟道古茶"
BASE_CHANCE = 0.70
CHANCE_CAP = 0.95
INSIGHT_BASE = 0.02
INSIGHT_TEA = 0.10
INSIGHT_CAP = 0.25
GAIN_CLAMP = (0.5, 2.5)

# 节点表：name, targetExp, 寿元(年,原值÷1000), 元神需求, 基础收益
DAO_NODES: tuple[dict[str, Any], ...] = (
    {"name": "王者道则", "exp": 600, "shouyuan": 200, "yuan_min": 2, "gain": 20},
    {"name": "圣道", "exp": 1200, "shouyuan": 5_000, "yuan_min": 3, "gain": 40},
    {"name": "圣王道则", "exp": 2400, "shouyuan": 10_000, "yuan_min": 4, "gain": 80},
    {"name": "大圣道则", "exp": 4800, "shouyuan": 20_000, "yuan_min": 5, "gain": 160},
    {"name": "准帝道则", "exp": 9600, "shouyuan": 150_000, "yuan_min": 6, "gain": 320},
    {"name": "红尘仙道", "exp": 19200, "shouyuan": 300_000, "yuan_min": 8, "gain": 640},
    {"name": "仙王道则", "exp": 38400, "shouyuan": 600_000, "yuan_min": 9, "gain": 1280},
    {"name": "诸天道则", "exp": 76800, "shouyuan": 1_200_000, "yuan_min": 10, "gain": 2560},
)

# 体质悟道加成（wudaoRules 体质表）
PHYSIQUE_BONUS: tuple[tuple[str, float], ...] = (
    ("先天混沌圣体道胎", 1.45), ("混沌体", 1.35), ("先天圣体道胎", 1.30),
    ("先天道胎", 1.25), ("大成·荒古圣体", 1.10), ("小成·荒古圣体", 1.05),
)

STAGE_NAMES = ("未悟", "初悟", "小成", "大成", "圆满")


def _defaults() -> dict[str, Any]:
    return {"exp": {}, "day": "", "count": 0, "tea": False,
            "completed": [], "last_at": 0.0}


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
    if not isinstance(st.get("exp"), dict):
        st["exp"] = {}
    if not isinstance(st.get("completed"), list):
        st["completed"] = []
    st["count"] = int(st.get("count", 0) or 0)
    return st


def _day_key(now: float) -> str:
    return day_key(now).replace("-", "")


def _node_exp(st: Mapping[str, Any], name: str) -> int:
    return int((st.get("exp") or {}).get(name, 0) or 0)


def current_node(st: Mapping[str, Any]) -> dict[str, Any] | None:
    """当前参悟节点：第一个未圆满的。"""
    done = set(st.get("completed") or [])
    for node in DAO_NODES:
        if node["name"] not in done:
            return node
    return None


def stage_of(node_exp: int, target: int) -> str:
    if node_exp >= target:
        return STAGE_NAMES[4]
    ratio = node_exp / max(1, target)
    if ratio >= 0.5:
        return STAGE_NAMES[3]
    if ratio >= 1 / 6:
        return STAGE_NAMES[2]
    if ratio > 0:
        return STAGE_NAMES[1]
    return STAGE_NAMES[0]


def _level_sum(doc: Any) -> int:
    return (int(getattr(doc, "realm_index", 0) or 0)
            + int(getattr(doc, "physique_index", 0) or 0) + 2)


def _physique_mult(doc: Any) -> float:
    lg = (getattr(doc, "ext", {}) or {}).get("linggen")
    name = str(lg.get("name") or "") if isinstance(lg, dict) else ""
    for key, mult in PHYSIQUE_BONUS:
        if key in name:
            return mult
    return 1.0


def costs_of(doc: Any, node_idx: int) -> dict[str, int]:
    """单次悟道消耗。潜力/修为/血气/灵石按 levelSum；寿元按节点表。"""
    ls = _level_sum(doc)
    base_shouyuan = int(DAO_NODES[node_idx]["shouyuan"])
    try:
        from .mingge import effects_of
        effects = effects_of(doc)
        shouyuan_mult = min(3.0, max(0.0,
            1.0 - float(effects.get("悟道寿元消耗减少", 0) or 0)
            + float(effects.get("悟道寿元消耗增加", 0) or 0)))
    except (TypeError, ValueError):
        shouyuan_mult = 1.0
    return {
        "potential": 100 * (node_idx + 1),
        "exp": 2_000 * ls * ls,
        "xueqi": 2_000 * ls * ls,
        "stones": 10_000 * ls,
        "shouyuan": int(math.ceil(base_shouyuan * shouyuan_mult)),
    }


def attempt(doc: PlayerDoc, inv: Mapping[str, int], now: float | None = None,
            rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#悟道：参悟当前己道节点，成功累积道则进度，失败按比例损失。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    node = current_node(st)
    if node is None:
        return False, "八重己道尽皆圆满——道途已至尽头，可问 #我的道途 回顾。", {}
    idx = next(i for i, n in enumerate(DAO_NODES) if n["name"] == node["name"])

    # 门槛：斩道级权柄
    if _authority(doc) < 10:
        return False, "悟道需先历【斩道】之境（权柄 ≥10）——先 #渡斩道雷劫。", {}
    try:
        from . import zhengdao as _dz
        w = _dz.peek(doc)
        if w >= 3.0:
            return False, f"身负道伤 {w:.1f} ≥3，神识浑浊无法参悟——先祛伤。", {}
    except Exception:
        pass

    # 每日次数
    day = _day_key(now)
    if st.get("day") != day:
        st["day"] = day
        st["count"] = 0
    delta: dict[str, int] = {}
    if st["count"] >= DAILY_LIMIT:
        have = int((inv or {}).get(DAILY_EXTEND_ITEM, 0) or 0)
        if have < 1:
            return False, (f"今日悟道 {DAILY_LIMIT} 次已尽，神识疲惫。"
                           f"可服用【{DAILY_EXTEND_ITEM}】续 1 次。"), {}
        delta[DAILY_EXTEND_ITEM] = -1

    # 消耗与门槛
    c = costs_of(doc, idx)
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    xueqi = int(float((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0))
    shouyuan = int(float((getattr(doc, "ext", {}) or {}).get("shouyuan", 0) or 0))
    if pot < c["potential"]:
        return False, f"仙道潜力不足：需 {c['potential']} 点（现有 {pot}）。", {}
    if int(getattr(doc, "exp", 0) or 0) < c["exp"] or xueqi < c["xueqi"]:
        return False, (f"悟道需修为与血气各 {c['exp']:,}（当前 "
                       f"{int(getattr(doc, 'exp', 0) or 0):,} / {xueqi:,}）。"), {}
    if int(getattr(doc, "stones", 0) or 0) < c["stones"]:
        return False, f"悟道需灵石 {c['stones']:,}（现有 {int(getattr(doc, 'stones', 0) or 0):,}）。", {}
    if shouyuan <= c["shouyuan"]:
        return False, (f"参悟一次需燃烧 {c['shouyuan']:,} 年寿元（现有 {shouyuan:,}）——"
                       "寿元将尽，先服寿命丹。")

    # 古茶 buff：本次结算消耗
    use_tea = bool(st.get("tea"))
    if not use_tea and int((inv or {}).get(TEA_ITEM, 0) or 0) > 0:
        delta[TEA_ITEM] = delta.get(TEA_ITEM, 0) - 1
        use_tea = True
    st["tea"] = False

    # 扣资源
    ext = getattr(doc, "ext", {})
    ext["potential"] = pot - c["potential"]
    ext["shouyuan"] = shouyuan - c["shouyuan"]
    doc.exp = int(getattr(doc, "exp", 0) or 0) - c["exp"]
    ext["xueqi"] = xueqi - c["xueqi"]
    doc.stones = int(getattr(doc, "stones", 0) or 0) - c["stones"]

    # 成功率 / 收益
    chance = BASE_CHANCE
    excess = 0
    try:
        from . import yuanshen as _ys
        lv = _ys.level_of(doc)
        excess = max(0, (int(lv) if lv is not None else 0) - int(node["yuan_min"]))
    except Exception:
        pass
    chance = min(CHANCE_CAP, chance + excess * 0.05)
    try:
        from . import zhengdao as _dz
        e = _dz.effects(doc, now)
        chance = max(0.05, chance - e["chance_penalty"])
        dao_mult = e["dao_multiplier"]
    except Exception:
        dao_mult = 1.0
    try:
        from .mingge import signed_bonus as _mingge_bonus
        dao_mult *= max(0.0, 1.0 + _mingge_bonus(doc, "悟道收益"))
    except (TypeError, ValueError):
        pass
    try:
        from .plane_events import sign_bonus as _sign_bonus
        dao_mult *= 1.0 + _sign_bonus(doc, "悟道收益", now)
    except (TypeError, ValueError):
        pass
    won = rng.random() < chance
    st["count"] = int(st["count"]) + 1
    st["last_at"] = now
    if not won:
        frac = rng.random() * (0.5 if use_tea else 1.0)
        refund_exp = int(c["exp"] * (1 - frac))
        refund_stones = int(c["stones"] * (1 - frac))
        doc.exp += refund_exp
        ext["xueqi"] = xueqi - c["xueqi"] + int(c["xueqi"] * (1 - frac))
        doc.stones += refund_stones
        save(doc, st)
        return True, (f"【悟道 · {node['name']}】神游太虚，道则晦暗——参悟失败。\n"
                      f"成功率 {chance:.0%}｜损失 {frac:.0%}：修为 -{c['exp'] - refund_exp:,}、"
                      f"灵石 -{c['stones'] - refund_stones:,}（潜力与寿元不退）"
                      + ("｜古茶护道，损失减半" if use_tea else "")), delta

    try:
        from .mingge import signed_bonus as _mingge_bonus
        fate_insight = _mingge_bonus(doc, "顿悟概率")
    except (TypeError, ValueError):
        fate_insight = 0.0
    insight_p = min(INSIGHT_CAP, INSIGHT_BASE + (INSIGHT_TEA if use_tea else 0.0)
                    + fate_insight)
    epiphany = rng.random() < insight_p
    try:
        from . import trib as _tb
        prof_mult = float(_tb.best_stage(doc)[3])
    except Exception:
        prof_mult = 1.0
    mult = max(GAIN_CLAMP[0], min(GAIN_CLAMP[1],
               _physique_mult(doc) * prof_mult * dao_mult)) * rng.uniform(0.9, 1.1)
    if epiphany:
        mult *= 2.0
    gain = max(1, int(node["gain"] * mult))
    cur = _node_exp(st, node["name"])
    st["exp"][node["name"]] = cur + gain
    done_msg = ""
    if st["exp"][node["name"]] >= node["exp"]:
        st["completed"] = list(st.get("completed") or []) + [node["name"]]
        done_msg = f"\n≡ 【{node['name']}】圆满！己道再进一步。"
    save(doc, st)
    head = "顿悟！道则如江河灌顶" if epiphany else "静参道则，有所精进"
    return True, (f"【悟道 · {node['name']}】{head}（成功率 {chance:.0%}）\n"
                  f"道则进度 {_node_exp(st, node['name'])}/{node['exp']}"
                  f"｜收益 +{gain}{'（双倍）' if epiphany else ''}"
                  f"｜潜力 -{c['potential']}、寿元 -{c['shouyuan']:,} 年{done_msg}"), delta


def tea(doc: Any, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    """#悟道古茶：消耗 1 枚，下次悟道损失减半、顿悟 +10pp。"""
    st = state_of(doc)
    if st.get("tea"):
        return False, "悟道古茶之力已在体内酝酿，下次 #悟道 自动生效。", {}
    have = int((inv or {}).get(TEA_ITEM, 0) or 0)
    if have < 1:
        return False, f"你并没有【{TEA_ITEM}】——悟道古茶可于 #刻舟求剑 高级档获取。", {}
    st["tea"] = True
    save(doc, st)
    return True, "【悟道古茶】茶汤入喉，神台清明——下次 #悟道 损失减半、顿悟 +10%。", {TEA_ITEM: -1}


def _stage_label(st: Mapping[str, Any], node: Mapping[str, Any]) -> str:
    return stage_of(_node_exp(st, node["name"]), node["exp"])


def panel(doc: Any) -> str:
    """#我的道途：己道节点进度与寿元。"""
    st = state_of(doc)
    node = current_node(st)
    shouyuan = int(float((getattr(doc, "ext", {}) or {}).get("shouyuan", 0) or 0))
    lines = ["--- 我的道途 ---",
             f"真实寿元：{shouyuan:,} 年（悟道会燃烧寿元，量入为出）"]
    if node is None:
        lines.append("八重己道尽皆圆满——红尘仙道已至尽头。")
    else:
        idx = next(i for i, n in enumerate(DAO_NODES) if n["name"] == node["name"])
        c = costs_of(doc, idx)
        cur = _node_exp(st, node["name"])
        lines.append(f"当前节点：【{node['name']}】{stage_of(cur, node['exp'])}"
                     f"｜道则 {cur}/{node['exp']}")
        lines.append(f"单次消耗：潜力 {c['potential']}｜修为血气各 {c['exp']:,}"
                     f"｜灵石 {c['stones']:,}｜寿元 {c['shouyuan']:,} 年")
        lines.append(f"今日已悟 {st.get('count', 0)}/{DAILY_LIMIT} 次"
                     f"｜古茶：{'已酝酿' if st.get('tea') else '未服'}")
    done = list(st.get("completed") or [])
    if done:
        lines.append("已圆满：" + "、".join(done))
    lines.append("用法：#悟道 ｜ #悟道古茶 ｜ #我的道途")
    return "\n".join(lines)
