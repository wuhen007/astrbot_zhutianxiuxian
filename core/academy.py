"""天神书院（仙古学院）——原版 `apps/User/XianguAcademy.js`(223 行) +
`model/xianguAcademy.js`(185 行) 的完整移植（深度核查补漏 W28）。

玩法：尊者境（仙古 7 境）+ 九天十地可申请入院；五阶院籍（外院弟子→内院弟子→
核心弟子→长老亲传→书院首席）逐阶晋升，每阶有境界门与源石消耗，并解锁
每日俸禄；入院后一次性择院（仙院/圣院，不可更改）：
- 仙院：道种掉落判定 ×1.1，仙气战斗乘区 ×1.15；
- 圣院：战斗乘区 +20%（今世法全极境词条），解锁 #涅槃重塑道基（端口等价
  #道基重塑 增益，登记 shortcut）。

数值 ÷1000：晋升消耗 100/500/2000/8000/20000 源石；日俸禄 100/500/2000/
5000/12000 源石。俸禄每日一次（原版 Redis 按日期键 NX → 端口按本地日期键
存院籍档案）。

源石口径：端口「源石」为库存物品（inv["源石"]），晋升/俸禄走库存增减。
rng 约定：只用 rng.random()。
"""

from __future__ import annotations

import time
from typing import Any

ACADEMY_NAME = "天神书院"

# (身份, 仙古境界门, 晋升消耗源石, 日俸禄源石)——原版表 ÷1000
RANKS: tuple[dict, ...] = (
    {"name": "外院弟子", "xg": 7, "realm": "尊者境", "cost": 0, "salary": 100},
    {"name": "内院弟子", "xg": 8, "realm": "神火境", "cost": 500, "salary": 500},
    {"name": "核心弟子", "xg": 9, "realm": "真一境", "cost": 2_000, "salary": 2_000},
    {"name": "长老亲传", "xg": 11, "realm": "天神境", "cost": 8_000, "salary": 5_000},
    {"name": "书院首席", "xg": 12, "realm": "虚道境", "cost": 20_000, "salary": 12_000},
)

BRANCH_EFFECTS: dict[str, dict] = {
    "仙院": {"seed_rate": 0.10, "xianqi_mult": 1.15, "combat_mult": 1.0,
             "desc": "道种掉落判定 ×1.1，仙气压制与护体减伤 +15%"},
    "圣院": {"seed_rate": 0.0, "xianqi_mult": 1.0, "combat_mult": 1.20,
             "desc": "今世法全极境属性与战斗词条 +20%（战斗乘区），#涅槃重塑道基 开启"},
}


def state_of(doc: Any) -> dict:
    """取（并按需初始化）ext["xiangu"]["academy"]。直接改 doc，调用方负责保存。"""
    from . import xiangu as xg
    st = xg.state_of(doc)
    rec = st.get("academy")
    if not isinstance(rec, dict):
        rec = {}
        st["academy"] = rec
    return rec


def rank_of(rec: dict) -> dict | None:
    name = str(rec.get("身份") or "")
    return next((r for r in RANKS if r["name"] == name), None)


def next_rank(rec: dict) -> dict | None:
    name = str(rec.get("身份") or "")
    for i, r in enumerate(RANKS):
        if r["name"] == name:
            return RANKS[i + 1] if i + 1 < len(RANKS) else None
    return None


def branch_of(doc: Any) -> str:
    return str(state_of(doc).get("分院") or "")


def seed_rate_bonus(doc: Any) -> float:
    """道种掉落判定加成（仙院 +10%）。"""
    return float(BRANCH_EFFECTS.get(branch_of(doc), {}).get("seed_rate", 0.0) or 0.0)


def combat_mult(doc: Any) -> float:
    """择院战斗乘区（圣院 1.2 / 仙院仙气部分由 combat 层另算）。"""
    return float(BRANCH_EFFECTS.get(branch_of(doc), {}).get("combat_mult", 1.0) or 1.0)


def branch_text(doc: Any) -> str:
    b = branch_of(doc)
    if not b:
        return "尚未择院"
    return f"{b}｜{BRANCH_EFFECTS[b]['desc']}"


def panel(doc: Any) -> str:
    rec = state_of(doc)
    lines = ["【天神书院】",
             "九天十地汇聚英才之地，尊者境修士可申请入院。", ""]
    if rec.get("学院"):
        rank = rank_of(rec) or RANKS[0]
        lines.append(f"你的身份：{ACADEMY_NAME}·{rec.get('分院') or '未择院'} {rec.get('身份')}")
        lines.append(f"流派：{branch_text(doc)}")
        lines.append(f"每日俸禄：{rank['salary']:,} 源石"
                     f"（{'今日已领' if str(rec.get('salary_day') or '') == _day_key() else '今日可领'}）")
    else:
        lines.append("你的状态：尚未入院")
    lines += ["", "#申请入院｜#我的院籍｜#院籍晋升",
              "#选择仙院 / #选择圣院｜#领取书院俸禄"]
    return "\n".join(lines)


def _day_key(now: float | None = None) -> str:
    return time.strftime("%Y%m%d", time.localtime(now if now is not None else time.time()))


def apply(doc: Any, xg_level: int, plane_name: str) -> tuple[bool, str]:
    """#申请入院：尊者境（7）+ 九天十地。"""
    rec = state_of(doc)
    if rec.get("学院"):
        return False, "你已经拥有天神书院院籍。"
    if plane_name != "九天十地":
        return False, "天神书院位于九天十地，请先前往九天十地。"
    if xg_level < RANKS[0]["xg"]:
        return False, (f"申请天神书院至少需要达到{RANKS[0]['realm']}。"
                       f"（当前仙古境界 {xg_level}/11）")
    rec.update({"学院": ACADEMY_NAME, "分院": "", "身份": RANKS[0]["name"],
                "入院时间": time.time(), "salary_day": ""})
    return True, "\n".join([
        "【天神书院·入院】",
        "书院山门开启，大长老法相自九天之上投来目光。",
        f"院籍：{ACADEMY_NAME}｜身份：外院弟子",
        "可使用 #选择仙院 或 #选择圣院确定后续修行方向。"])


def my_text(doc: Any, xg_level: int, stones_have: int) -> str:
    rec = state_of(doc)
    if not rec.get("学院"):
        return "你尚无院籍，可在九天十地使用 #申请入院。"
    rank = rank_of(rec) or RANKS[0]
    nxt = next_rank(rec)
    claimed = str(rec.get("salary_day") or "") == _day_key()
    lines = ["【我的院籍】",
             f"学院：{rec.get('学院')}",
             f"分院：{rec.get('分院') or '尚未选择'}",
             f"流派：{branch_text(doc)}",
             f"身份：{rec.get('身份')}",
             f"当前境界：仙古 {xg_level}/11 境",
             f"每日俸禄：{rank['salary']:,} 源石｜今日俸禄：{'已领取' if claimed else '可领取'}"]
    if nxt:
        lines.append(f"下一身份：{nxt['name']}（{nxt['realm']}、{nxt['cost']:,} 源石）")
    else:
        lines.append("下一身份：已达最高院籍")
    lines.append(f"持有源石：{stones_have:,}")
    return "\n".join(lines)


def promote(doc: Any, xg_level: int, stones_have: int) -> tuple[bool, str, int]:
    """#院籍晋升。返回 (ok, text, 源石消耗)——扣费由 handler 动账。"""
    rec = state_of(doc)
    if not rec.get("学院"):
        return False, "你尚未加入天神书院。", 0
    nxt = next_rank(rec)
    if not nxt:
        return False, "你已经是天神书院首席。", 0
    if xg_level < int(nxt["xg"]):
        return False, f"晋升{nxt['name']}需要达到{nxt['realm']}（仙古 {nxt['xg']} 境）。", 0
    if stones_have < int(nxt["cost"]):
        return False, f"晋升{nxt['name']}需要 {nxt['cost']:,} 源石（持有 {stones_have:,}）。", 0
    cur = rank_of(rec) or RANKS[0]
    rec["身份"] = nxt["name"]
    rec["最近晋升时间"] = time.time()
    return True, ("\n".join([
        "【院籍晋升】",
        f"你由{cur['name']}晋升为{nxt['name']}。",
        f"消耗：{nxt['cost']:,} 源石",
        f"每日俸禄提升至：{nxt['salary']:,} 源石"])), int(nxt["cost"])


def choose_branch(doc: Any, branch: str) -> tuple[bool, str]:
    """#选择仙院 / #选择圣院（不可更改）。"""
    rec = state_of(doc)
    if not rec.get("学院"):
        return False, "请先使用 #申请入院 加入天神书院。"
    if branch not in BRANCH_EFFECTS:
        return False, "只能选择仙院或圣院。"
    if rec.get("分院"):
        if rec["分院"] == branch:
            return False, f"你已经选择了{branch}。"
        return False, f"你已经选择{rec['分院']}，修行方向不可重复选择。"
    rec["分院"] = branch
    rec["择院时间"] = time.time()
    eff = BRANCH_EFFECTS[branch]
    flavor = ("仙院重仙古法，道种孕育全属性率额外 +10%，三道仙气压制与护体减伤提升 +15%！"
              if branch == "仙院" else
              "圣院重今世法，全极境属性与战斗词条效果提升 +20%，并解锁 #涅槃重塑道基 消除至尊外道隐患！")
    return True, "\n".join([
        f"【{branch}·择院】",
        f"你已选择{branch}作为后续修行方向。",
        flavor,
        f"当前流派被动：{eff['desc']}",
        "当前选择不可重复更改。"])


def claim_salary(doc: Any, stones_have: int) -> tuple[bool, str, int]:
    """#领取书院俸禄（每日一次）。返回 (ok, text, 俸禄源石)。"""
    rec = state_of(doc)
    if not rec.get("学院"):
        return False, "你尚无天神书院院籍，无法领取俸禄。", 0
    rank = rank_of(rec)
    if not rank:
        return False, "院籍身份异常，暂时无法领取俸禄。", 0
    today = _day_key()
    if str(rec.get("salary_day") or "") == today:
        return False, "今日书院俸禄已经领取，请明日再来。", 0
    rec["salary_day"] = today
    return True, ("\n".join([
        "【书院俸禄】",
        f"院籍：{ACADEMY_NAME}·{rec.get('分院') or '未择院'} {rec['身份']}",
        f"领取：{rank['salary']:,} 源石"])), int(rank["salary"])


def rules_text() -> str:
    ranks = "｜".join(f"{r['name']}（{r['realm']}·{r['cost']:,}源石·日俸{r['salary']:,}）"
                      for r in RANKS)
    return "\n".join([
        "【天神书院·规则】",
        "「九天十地汇聚英才之地，尊者境修士可申请入院。」",
        "",
        f"院籍五阶：{ranks}",
        "择院（不可更改）：",
        f"✦ 仙院——{BRANCH_EFFECTS['仙院']['desc']}",
        f"▼ 圣院——{BRANCH_EFFECTS['圣院']['desc']}",
        "",
        "俸禄每日一次；晋升需要境界与源石（源石来自秘境撤离/宝地收取）。",
    ])
