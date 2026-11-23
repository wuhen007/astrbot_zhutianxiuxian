"""记忆命途（W8-B5）：四阶 / 十二因子 / 逐火与泰坦。

原版：`apps/User/MemoryPath.js` 390 + `model/memoryPath.js`（活跃指令只有 5 条）。
**星神觐见 / 记忆碎片 / 六相冰封 / 记忆更改 / 记忆造物 / 记忆回溯在原版已暂停**（入口注释掉、
调用直接回「已暂停」），故本移植不实现这 6 条，只做仍开放的：模拟、逐火、泰坦、行进、因子。

机制：
- 四阶：金血之体（cap 3 / 本源 50）→ 逐火行者（6 / 150，需仙台大能）→ 半神之体（9 / 300，需圣人）
  → 无漏净子（12 / 500，需大帝）；晋升直接换灵根快照（`linggen.stats_of` 消费）
- 十二因子（门径/浪漫/理性/纷争/诡计/死亡/天空/海洋/大地/律法/时间/负世），三档黄金/强化/泰坦
- 模拟值：每次真实秘境结算 +2%（上限 100），`#命途模拟` 消耗 100 抽一个未持有因子
- 逐火之旅：6 小时一次 ×12，把黄金因子升强化；泰坦试炼：1 小时一次 ×12，把强化升泰坦
- 效应：生命本源（一二阶每因子 +10，三阶起每泰坦 +20）、悟道 +3%/因子、渡劫减伤 +3%/因子
  （逐火行者起另加 30%）、物品倍率 2 倍起、每 6 个泰坦 +1 倍（上限 4 倍）

shortcut：原版靠 0.01% 掉落的【奇怪的数据】开启（该入口本身已注释掉），本移植改为
`#开启记忆命途`（第 21 境 + 500 万灵石）以免绝版；`#命途模拟` 的秘境记录去重表未搬
（本移植每层只结算一次，天然不重复）；门径的副本代价减免只接在「秘境门票」上。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

STAGES: tuple[dict[str, Any], ...] = (
    {"name": "金血之体", "realm": 0, "cap": 3, "life": 50, "eff": 20, "orb": 1.5, "stats": 0.2},
    {"name": "逐火行者", "realm": 10, "cap": 6, "life": 150, "eff": 100, "orb": 3, "stats": 1},
    {"name": "半神之体", "realm": 12, "cap": 9, "life": 300, "eff": 300, "orb": 10, "stats": 5},
    {"name": "无漏净子", "realm": 16, "cap": 12, "life": 500, "eff": 3000, "orb": 100, "stats": 10},
)

FACTORS: tuple[str, ...] = ("门径", "浪漫", "理性", "纷争", "诡计", "死亡",
                            "天空", "海洋", "大地", "律法", "时间", "负世")
TIER_NAMES = {1: "黄金", 2: "强化", 3: "泰坦"}
FACTOR_DESC: dict[str, str] = {
    "门径": "副本入场代价 -20/30/40%",
    "浪漫": "逐火 / 泰坦 / 星神三件套（本移植只发属性，不发装备）",
    "理性": "学习消耗减半 / 免消耗 / 免消耗并缩短传功冷却",
    "纷争": "每 3 回合 +开战生命 2/4/8%",
    "诡计": "每 6/4/2 次攻击取消敌方下次攻击",
    "死亡": "每 12/8/4 次攻击叠印记，满 12/12/8 层处决",
    "天空": "隔绝境界差 ≤3/4/5 的本源炼化",
    "海洋": "钓鱼收益 2/3/4 倍",
    "大地": "种植生长与返种 1.5/2/3 倍",
    "律法": "逐级保证副本一/二/三档掉落",
    "时间": "每次渡劫至多一次满血复苏（消耗 500/400/300 本源）",
    "负世": "每回合 +开战攻击 1/2/3%，线性累积",
}

SIM_PER_RUN = 2
SIM_MAX = 100
JOURNEY_CD = 6 * 3600
TITAN_CD = 3600
JOURNEY_TOTAL = 12
TITAN_TOTAL = 12
ACTIVATE_REALM = 20
ACTIVATE_COST = 5_000_000


def state_of(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get("memory") if isinstance(getattr(doc, "ext", None), Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("factors", {})
    if not isinstance(st["factors"], dict):
        st["factors"] = {}
    st.setdefault("journey", 0)
    st.setdefault("last_journey", 0.0)
    st.setdefault("titan", 0)
    st.setdefault("last_titan", 0.0)
    st.setdefault("sim", 0)
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["memory"] = dict(st)


def stage_of(doc: Any) -> int:
    """1-4；未开启返回 0（按灵根名判定，与原版一致）。"""
    snap = doc.ext.get("linggen")
    if not isinstance(snap, Mapping):
        return 0
    name = str(snap.get("name") or "")
    for i, row in enumerate(STAGES, 1):
        if row["name"] == name:
            return i
    return 0


# 记忆命途的等效境界（只用于门槛/天堑，不给三维乘区）
EQUIV = (0, 0, 10, 25, 40, 55)


def equivalent_level(doc: Any) -> int:
    return EQUIV[min(5, max(0, stage_of(doc)))]


def root_of(stage: int) -> dict[str, Any]:
    spec = STAGES[max(0, min(len(STAGES) - 1, int(stage) - 1))]
    return {
        "id": 7092000 + int(stage),
        "name": spec["name"],
        "type": "记忆命途",
        "归类": "记忆命途",
        "eff": spec["eff"],
        "法球倍率": spec["orb"],
        "攻击": spec["stats"],
        "防御": spec["stats"],
        "生命": spec["stats"],
        "生命本源": spec["life"],
        "稀有度": 10,
    }


def sync_root(doc: Any) -> None:
    """把生命本源写回灵根快照（灵根聚合只认快照里的 origin）。"""
    stage = stage_of(doc)
    snap = doc.ext.get("linggen")
    if stage <= 0 or not isinstance(snap, Mapping):
        return
    doc.ext["linggen"] = {**dict(snap), "origin": float(life_max(state_of(doc), stage))}


def life_max(st: Mapping[str, Any], stage: int) -> int:
    if stage <= 0:
        return 0
    spec = STAGES[stage - 1]
    tiers = [int(v) for v in (st.get("factors") or {}).values()]
    if stage <= 2:
        return int(spec["life"]) + sum(1 for t in tiers if t) * 10
    return int(spec["life"]) + sum(1 for t in tiers if t >= 3) * 20


def item_mult(st: Mapping[str, Any], stage: int) -> int:
    """普通物品倍率：逐火行者起 2 倍，每 6 个泰坦 +1，上限 4。"""
    if stage < 2:
        return 1
    titan = sum(1 for v in (st.get("factors") or {}).values() if int(v) >= 3)
    return min(4, 2 + titan // 6)


def effects(doc: Any) -> dict[str, float]:
    st = state_of(doc)
    stage = stage_of(doc)
    tiers = [int(v) for v in (st.get("factors") or {}).values()]
    n = len(tiers)
    gate = 0.0
    if "门径" in (st.get("factors") or {}):
        gate = {1: 0.20, 2: 0.30, 3: 0.40}.get(int(st["factors"]["门径"]), 0.0)
    return {
        "stage": float(stage),
        "origin": float(life_max(st, stage)),
        "wudao": 0.03 * n,
        "trib": 0.03 * n + (0.30 if stage >= 2 else 0.0),
        "item_mult": float(item_mult(st, stage)),
        "gate": gate,
        "factors": float(n),
    }


def add_sim(doc: Any, amount: int = SIM_PER_RUN) -> int:
    """秘境结算累加模拟值；未开启命途不累计。"""
    if stage_of(doc) <= 0:
        return 0
    st = state_of(doc)
    before = int(st.get("sim", 0) or 0)
    st["sim"] = min(SIM_MAX, before + max(0, int(amount)))
    set_state(doc, st)
    return st["sim"] - before


def activate(doc: Any, now: float | None = None) -> tuple[bool, str]:
    if stage_of(doc) > 0:
        return False, "你已在记忆命途中。"
    if int(getattr(doc, "realm_index", 0) or 0) < ACTIVATE_REALM:
        return False, f"【记忆命途·境界不足】开启记忆命途需第 {ACTIVATE_REALM + 1} 境以上。"
    if int(doc.stones) < ACTIVATE_COST:
        return False, f"【记忆命途·灵石不足】开启需 {ACTIVATE_COST:,} 灵石（当前 {int(doc.stones):,}）。"
    from . import linggen
    doc.stones -= ACTIVATE_COST
    snap = linggen.snapshot(root_of(1))
    snap["awaken"] = 0
    doc.ext["linggen"] = snap
    st = state_of(doc)
    st["factors"] = {}
    set_state(doc, st)
    return True, (
        "【金血之体】记忆的潮声在识海深处响起，你的灵根化作记忆命途之根。\n"
        "此后每次真实秘境结算 +2% 模拟值，满 100 可 #命途模拟 抽取不重复因子。"
    )


def simulate(doc: Any, rng: random.Random) -> tuple[bool, str]:
    stage = stage_of(doc)
    if stage <= 0:
        return False, "尚未开启记忆命途（#开启记忆命途）。"
    st = state_of(doc)
    if len(st["factors"]) >= STAGES[stage - 1]["cap"]:
        return False, "【记忆命途·因子已满】已达本阶段因子上限，请先 #命途行进。"
    if int(st.get("sim", 0) or 0) < SIM_MAX:
        return False, f"模拟值不足 100%（当前 {int(st.get('sim', 0))}%）。"
    left = [f for f in FACTORS if f not in st["factors"]]
    name = left[rng.randrange(len(left))]
    tier = 3 if int(st.get("titan", 0)) >= TITAN_TOTAL else (2 if int(st.get("journey", 0)) >= JOURNEY_TOTAL else 1)
    st["factors"][name] = tier
    st["sim"] = int(st["sim"]) - SIM_MAX
    set_state(doc, st)
    sync_root(doc)
    return True, (f"【{TIER_NAMES[tier]}·{name}】\n"
                  f"{FACTOR_DESC.get(name, '')}\n"
                  f"因子 {len(st['factors'])}/{STAGES[stage - 1]['cap']}｜"
                  f"生命本源 {life_max(st, stage)}")


def advance(doc: Any) -> tuple[bool, str]:
    stage = stage_of(doc)
    if stage <= 0:
        return False, "尚未开启记忆命途。"
    if stage >= len(STAGES):
        return False, "无漏净子已是最终阶段。"
    nxt = STAGES[stage]
    if int(getattr(doc, "realm_index", 0) or 0) < int(nxt["realm"]):
        return False, f"下一阶段「{nxt['name']}」需第 {int(nxt['realm']) + 1} 境。"
    st = state_of(doc)
    need = (3, 6, 9, 12)[stage - 1]
    if len(st["factors"]) < need:
        return False, f"晋升需 {need} 个因子（现有 {len(st['factors'])}）。"
    if stage == 2 and int(st.get("journey", 0)) < JOURNEY_TOTAL:
        return False, f"逐火之旅需完成 {JOURNEY_TOTAL} 次（现 {int(st.get('journey', 0))}）。"
    if stage == 3 and int(st.get("titan", 0)) < TITAN_TOTAL:
        return False, f"泰坦试炼需完成 {TITAN_TOTAL} 次（现 {int(st.get('titan', 0))}）。"
    from . import linggen
    snap = linggen.snapshot(root_of(stage + 1))
    snap["awaken"] = int(doc.ext.get("linggen", {}).get("awaken", 0) or 0)
    doc.ext["linggen"] = snap
    return True, (f"「{nxt['name']}」命途向前一步，灵根与生命本源重塑。\n"
                  f"生命本源 {life_max(st, stage + 1)}｜物品 {item_mult(st, stage + 1)} 倍"
                  f"｜悟道 +{effects(doc)['wudao']:.0%}")


def journey(doc: Any, now: float, rng: random.Random) -> tuple[bool, str]:
    stage = stage_of(doc)
    if stage < 2:
        return False, "逐火行者起可踏上逐火之旅。"
    st = state_of(doc)
    if int(st.get("journey", 0)) >= JOURNEY_TOTAL:
        return False, "十二次逐火之旅已圆满。"
    if not st["factors"]:
        return False, "请先获得至少一个黄金因子。"
    if float(st.get("last_journey") or 0) + JOURNEY_CD > now:
        left = int(float(st["last_journey"]) + JOURNEY_CD - now)
        return False, f"逐火之旅每现实 6 小时一次（还需 {left // 3600} 时 {left % 3600 // 60} 分）。"
    cands = [f for f, t in st["factors"].items() if int(t) == 1]
    name = cands[rng.randrange(len(cands))] if cands else ""
    if name:
        st["factors"][name] = 2
    st["journey"] = int(st.get("journey", 0)) + 1
    st["last_journey"] = float(now)
    set_state(doc, st)
    sync_root(doc)
    msg = f"{name}因子强化完成。" if name else "已持因子皆获强化，本次巩固逐火印记。"
    return True, (f"【逐火之旅·{st['journey']}/{JOURNEY_TOTAL}】{msg}\n"
                  f"生命本源 {life_max(st, stage)}")


def titan_check(doc: Any, now: float) -> tuple[bool, str]:
    stage = stage_of(doc)
    if stage < 3:
        return False, "半神之体起可进行泰坦试炼。"
    st = state_of(doc)
    if int(st.get("titan", 0)) >= TITAN_TOTAL:
        return False, "十二道泰坦试炼已圆满。"
    if float(st.get("last_titan") or 0) + TITAN_CD > now:
        left = int(float(st["last_titan"]) + TITAN_CD - now)
        return False, f"泰坦试炼每现实小时一次（还需 {left // 60} 分）。"
    return True, ""


def titan_scale(doc: Any) -> float:
    return 0.65 + int(state_of(doc).get("titan", 0)) * 0.04


def titan_apply(doc: Any, won: bool, now: float, rng: random.Random) -> tuple[bool, str]:
    ok, why = titan_check(doc, now)
    if not ok:
        return False, why
    st = state_of(doc)
    st["last_titan"] = float(now)
    if not won:
        set_state(doc, st)
        return True, (f"本次泰坦试炼失利，进度保留（{st['titan']}/{TITAN_TOTAL}）。"
                      "一小时后再来。")
    cands = [f for f, t in st["factors"].items() if int(t) == 2]
    name = cands[rng.randrange(len(cands))] if cands else ""
    if name:
        st["factors"][name] = 3
    st["titan"] = int(st.get("titan", 0)) + 1
    set_state(doc, st)
    sync_root(doc)
    msg = f"{name}蜕变为泰坦因子。" if name else "已持强化因子皆化泰坦，本次巩固泰坦见证。"
    return True, (f"【泰坦试炼·{st['titan']}/{TITAN_TOTAL}】{msg}\n"
                  f"生命本源 {life_max(st, stage_of(doc))}｜物品 {item_mult(st, stage_of(doc))} 倍")


def status_text(doc: Any) -> str:
    stage = stage_of(doc)
    if stage <= 0:
        return (f"【记忆命途】尚未开启。\n"
                f"#开启记忆命途（第 {ACTIVATE_REALM + 1} 境 / {ACTIVATE_COST:,} 灵石）")
    st = state_of(doc)
    eff = effects(doc)
    rows = [f"{name}·{TIER_NAMES[int(t)]}" for name, t in st["factors"].items()]
    lines = [f"【记忆命途·{STAGES[stage - 1]['name']}】",
             f"生命本源：{life_max(st, stage)}｜模拟值：{int(st.get('sim', 0))}/100",
             f"因子（{len(st['factors'])}/{STAGES[stage - 1]['cap']}）：{'、'.join(rows) or '尚未模拟'}",
             f"逐火 {int(st.get('journey', 0))}/{JOURNEY_TOTAL}｜泰坦 {int(st.get('titan', 0))}/{TITAN_TOTAL}",
             f"悟道 +{eff['wudao']:.0%}｜渡劫减伤 {eff['trib']:.0%}｜物品 {eff['item_mult']:.0f} 倍"
             f"｜副本代价 -{eff['gate']:.0%}",
             "每次真实秘境结算 +2% 模拟值；#命途模拟 抽因子，#命途行进 晋升。"]
    if stage >= 2:
        lines.append("#逐火之旅：6 小时一次 ×12（黄金→强化）")
    if stage >= 3:
        lines.append("#泰坦试炼：1 小时一次 ×12（强化→泰坦）")
    return "\n".join(lines)


def factors_text(doc: Any) -> str:
    st = state_of(doc)
    lines = ["【记忆因子·十二相】"]
    for name in FACTORS:
        tier = int(st["factors"].get(name, 0) or 0)
        mark = f"·{TIER_NAMES[tier]}" if tier else ""
        lines.append(f"{name}{mark}｜{FACTOR_DESC.get(name, '')}")
    lines.append("模拟值满 100 可 #命途模拟 抽一个未持有因子。")
    return "\n".join(lines)
