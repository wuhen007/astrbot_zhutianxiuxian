"""渡劫 / 登仙 / 功法熟练度（W2-1，对齐原版 apps/User/Level.js + GongfaProficiency）。

原版语义：
- 无妄真劫境（realm_index 40）突破前必须渡劫：血量 ≥90% 上限、修为 ≥当前境界 exp、
  灵根已开；劫数按灵根 type（伪灵根 3 道 → 圣体道胎 128 道）。
- 雷抗 dujie：血/10万×0.4 + 防/10万×0.6 求和后 ×(攻/10万×0.2)；成功率
  = (雷抗 − n) / (p + 劫数×0.1) × 100，n=11800、p=2800（本移植属性 ÷1000，n/p 同比 ÷1000）。
- 渡劫分肉身劫/元神劫两段（原版异步定时器逐道落雷）——本移植同步化：一次判定双劫，
  失败血量归 1、修为扣 1/4、元神劫 30 分钟 CD；成功 ext["power"]=2，`#登仙` 解锁。
- `#登仙`：power==2 且无妄真劫境 → 地仙（realm_index 41），消耗当前境界 exp 修为。
- 功法熟练度：上限 1000，六档（初窥门径 0 / 略有所成 100 / 融会贯通 250 /
  炉火纯青 500 / 登峰造极 750 / 出神入化 1000），档位加成 trigger/combat/numeric。
  感悟值：战斗每场 +2（原版功法感悟值）；`#分配功法感悟 功法名*数量` 1:1 转熟练度。

W7-1：补 #复活设置（自动/手动）、已学复活功法抵消渡劫失败损耗、手动 60 秒窗口。
shortcut：虚实转化率减免、打散雷劫（肉身劫分支）、悟道减免、原版逐本功法优先级选择未复刻。
"""

from __future__ import annotations

import random
import time
from typing import Any

from .player import PlayerDoc

TRIB_REALM = 40            # 无妄真劫境（0-based）
ASCEND_REALM = 41          # 地仙
SPIRIT_CD = 30 * 60        # 元神劫失败 CD
MIN_SPIRIT_RATIO = 0.9     # 血量须 ≥ 上限 90%
THUNDER_N = 11.8           # 原版 11800 ÷1000
THUNDER_P = 2.8            # 原版 2800 ÷1000

PROF_MAX = 1000
PROF_DAILY = 20
INSIGHT_PER_BATTLE = 2

ROOT_ROUNDS = {
    "伪灵根": 3, "真灵根": 6, "天灵根": 9, "体质": 10,
    "转生": 21, "魔头": 21, "妖体": 26, "神体": 26,
    "圣体": 52, "小成圣体": 72, "混沌体": 82, "至尊体": 96,
    "大成圣体": 102, "大道体": 102, "圣体道胎": 128, "神慧者": 1280,
}
DEFAULT_ROUNDS = 12

PROF_STAGES = [
    ("初窥门径", 0, 1.00, 1.00, 1.00),
    ("略有所成", 100, 1.03, 1.02, 1.02),
    ("融会贯通", 250, 1.06, 1.04, 1.04),
    ("炉火纯青", 500, 1.09, 1.07, 1.06),
    ("登峰造极", 750, 1.12, 1.10, 1.08),
    ("出神入化", 1000, 1.15, 1.15, 1.10),
]


def prof_of(doc: Any) -> dict:
    ext = getattr(doc, "ext", None)
    prof = ext.get("prof") if isinstance(ext, dict) else None
    return dict(prof) if isinstance(prof, dict) else {}


def stage_of(prof: float) -> tuple[str, float, float, float]:
    """(档名, trigger, combat, numeric)。"""
    cur = PROF_STAGES[0]
    for row in PROF_STAGES:
        if prof >= row[1]:
            cur = row
    return cur[0], cur[2], cur[3], cur[4]


def best_stage(doc: Any) -> tuple[str, float, float, float]:
    """已学功法中最高档位（battle 装填用）。"""
    learned = set(getattr(doc, "ext", {}).get("gongfa") or [])
    prof = prof_of(doc)
    best = PROF_STAGES[0][0], 1.0, 1.0, 1.0
    for name in learned:
        name = str(name).strip()
        if not name:
            continue
        stage = stage_of(float(prof.get(name, 0) or 0))
        if stage[1] > best[1]:
            best = stage
    return best


def add_insight(doc: Any, amount: int = INSIGHT_PER_BATTLE) -> int:
    """战斗后感悟值 +amount（写 ext["insight"]）。"""
    ext = doc.ext
    cur = int(ext.get("insight", 0) or 0)
    ext["insight"] = cur + max(0, int(amount))
    return ext["insight"]


def allocate(doc: PlayerDoc, name: str, amount: int) -> tuple[bool, str]:
    """感悟值 → 熟练度（1:1，上限 1000）。须已学该功法。"""
    name = name.strip()
    learned = [str(x) for x in (doc.ext.get("gongfa") or [])]
    if name not in learned:
        return False, f"尚未参悟「{name}」，无法分配感悟。"
    balance = int(doc.ext.get("insight", 0) or 0)
    if amount <= 0:
        return False, "分配数量须为正整数。"
    prof = prof_of(doc)
    cur = int(prof.get(name, 0) or 0)
    if cur >= PROF_MAX:
        return False, f"「{name}」已至出神入化（{PROF_MAX}），感悟再难精进。"
    gain = min(amount, PROF_MAX - cur)   # 超额分配只消耗到上限所需
    if balance < gain:
        return False, f"功法感悟不足：需要 {gain} 点，当前仅有 {balance} 点。"
    prof[name] = cur + gain
    doc.ext["prof"] = prof
    doc.ext["insight"] = balance - gain
    st = stage_of(prof[name])
    return True, (f"「{name}」参悟精进：熟练度 {cur} → {prof[name]}（{st[0]}）\n"
                  f"剩余感悟 {doc.ext['insight']} 点。")


def prof_text(doc: PlayerDoc) -> str:
    learned = [str(x) for x in (doc.ext.get("gongfa") or [])]
    prof = prof_of(doc)
    lines = [f"--- 功法参悟 ---",
             f"感悟值：{int(doc.ext.get('insight', 0) or 0)}（战斗每场 +{INSIGHT_PER_BATTLE}）",
             f"分配：#分配功法感悟 功法名*数量"]
    if not learned:
        lines.append("尚未参悟任何功法。")
    for name in learned:
        v = int(prof.get(name, 0) or 0)
        st = stage_of(v)
        lines.append(f"· {name}：{v}/{PROF_MAX}（{st[0]}｜触发 ×{st[1]:.2f} 战斗 ×{st[2]:.2f}）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 渡劫 / 登仙

def thunder_resist(doc: PlayerDoc, stats: Any) -> float:
    """雷抗 dujie 直译（属性 ÷1000 标度，n/p 已同比缩放）。stats 需含 atk/defense/hp。"""
    nb = float(stats.hp) / 100_000
    nd = float(stats.defense) / 100_000
    na = float(stats.atk) / 100_000
    N = nb * 0.4 + nd * 0.6
    return N * (na * 0.2)


def trib_check(doc: PlayerDoc, table: list[dict], stats: Any, hp_cur: float, hp_max: float) -> str | None:
    """渡劫前置：通过返回 None。"""
    if int(doc.realm_index) != TRIB_REALM:
        return "你非无妄真劫境修士！"
    lg = doc.ext.get("linggen")
    if not isinstance(lg, dict) or not lg.get("name"):
        return "你灵根未开，不能渡劫！"
    if int(doc.ext.get("power", 0) or 0) >= 2:
        return "你已渡过双重真劫，请感应仙门 #登仙。"
    if hp_cur < hp_max * MIN_SPIRIT_RATIO:
        return "血量亏损，强行渡劫恐有性命之忧（需 90% 满血）。"
    need = int(table[min(TRIB_REALM, len(table) - 1)].get("exp", 0) or 0)
    fail_ts = float(doc.ext.get("spirit_fail_ts", 0) or 0)
    if fail_ts and time.time() - fail_ts < SPIRIT_CD:
        left = SPIRIT_CD - (time.time() - fail_ts)
        return f"元神尚未恢复，强行渡劫恐有魂飞魄散之险！还需 {left / 60:.0f} 分钟。"
    if doc.exp < need:
        return f"修为不足，再积累 {need - doc.exp:,} 修为后方可渡劫。"
    return None


def trib_run(doc: PlayerDoc, stats: Any, rng: random.Random) -> tuple[bool, str]:
    """同步化双劫：一次判定。成功 ext["power"]=2；失败扣修为/血量并记 CD。"""
    lg = doc.ext.get("linggen") or {}
    rounds = ROOT_ROUNDS.get(str(lg.get("type") or ""), DEFAULT_ROUNDS)
    x = thunder_resist(doc, stats)
    prob = (x - THUNDER_N) / (THUNDER_P + rounds * 0.1)
    prob = min(0.95, max(0.05, prob))
    try:
        from . import suiyun as _sy
        sy_red = float(_sy.trib_reduction(doc))    # W8-B4 岁云：20%~85% 渡劫减伤 + 七夜祈愿
    except Exception:
        sy_red = 0.0
    if sy_red:
        prob = min(0.99, prob * (1 + sy_red))
    ok = rng.random() < prob
    if ok:
        doc.ext["power"] = 2
        doc.ext.pop("spirit_fail_ts", None)
        return True, (f"≡≡≡ 无妄真劫启 ≡≡≡\n"
                      f"天道：就凭这肉身，也敢逆天改命？\n"
                      f"雷抗 {x:.1f}｜需渡 {rounds} 道雷劫｜成功率 {prob:.0%}\n"
                      f"天雷淬体，元神化真——双重真劫皆渡！\n"
                      f"肉身与元神已臻圆满，可感应仙门 #登仙。")
    cost = int(doc.exp * 0.25 * (1 - min(0.8, sy_red)))
    doc.exp = max(0, doc.exp - cost)
    doc.ext["hp"] = 1
    doc.ext["spirit_fail_ts"] = time.time()
    return False, (f"≡≡≡ 无妄真劫启 ≡≡≡\n"
                   f"雷抗 {x:.1f}｜需渡 {rounds} 道雷劫｜成功率 {prob:.0%}\n"
                   f"雷劫轰落，肉身崩碎、元神重创——渡劫失败！\n"
                   f"修为 -{cost:,}，气血归一，元神 30 分钟后方可再战。")


# ---------------------------------------------------------------- 渡劫复活设置（W7-1）
# 原版 zhetiandujie.js:180,284-309：渡劫濒死时按已掌握复活功法发动；
# 自动=直接发动，手动=60 秒内由玩家选择。本移植简化为「任一已学复活功法即可」，
# 不做逐本优先级列表（已写进 shortcut）。
REVIVE_WINDOW = 60


def revive_mode(doc: PlayerDoc) -> str:
    return "手动" if str(doc.ext.get("trib_revive_mode") or "") == "手动" else "自动"


def set_revive_mode(doc: PlayerDoc, mode: str) -> tuple[bool, str]:
    m = (mode or "").strip()
    if m not in ("自动", "手动"):
        learned = revival_skills(doc, ())
        return False, (f"当前复活模式：{revive_mode(doc)}\n"
                       f"用法：#复活设置 自动 / #复活设置 手动")
    doc.ext["trib_revive_mode"] = m
    return True, (f"复活模式已设为【{m}】：" +
                  ("渡劫失败时自动发动已掌握的复活功法，抵消修为与气血损耗。" if m == "自动"
                   else "渡劫失败后 60 秒内发 #复活发动 才会抵消损耗，逾期作废。"))


def revival_skills(doc: PlayerDoc, names) -> list[str]:
    """已学功法 ∩ 复活功法表。names 为空时返回已学功法（仅用于展示）。"""
    learned = {str(x) for x in (doc.ext.get("gongfa") or [])}
    allowed = {str(n) for n in names}
    return sorted(learned & allowed) if allowed else sorted(learned)


def apply_revive(doc: PlayerDoc, exp_before: int, hp_before: float) -> str:
    """复活功法抵消本次渡劫失败的修为/气血损耗（CD 保留，避免反复刷）。"""
    doc.exp = max(0, int(exp_before))
    doc.ext["hp"] = float(hp_before)
    doc.ext.pop("pending_revive", None)
    return "【复活功法】一缕真灵不灭，肉身重聚——修为与气血尽数复归（元神 CD 仍在）。"


def arm_revive(doc: PlayerDoc, exp_before: int, hp_before: float, now: float) -> None:
    doc.ext["pending_revive"] = {
        "exp": int(exp_before), "hp": float(hp_before),
        "deadline": float(now) + REVIVE_WINDOW,
    }


def consume_revive(doc: PlayerDoc, now: float) -> tuple[bool, str]:
    p = doc.ext.get("pending_revive")
    if not isinstance(p, dict):
        return False, "当前没有待发动的复活（渡劫失败且为手动模式时才会出现）。"
    if float(now) > float(p.get("deadline", 0) or 0):
        doc.ext.pop("pending_revive", None)
        return False, f"复活时机已过（{REVIVE_WINDOW} 秒窗口），本次损耗无法挽回。"
    return True, apply_revive(doc, p.get("exp", 0), p.get("hp", 1))


def ascend_check(doc: PlayerDoc, table: list[dict]) -> str | None:
    if int(doc.realm_index) != TRIB_REALM:
        return "你非无妄真劫境修士！"
    if int(doc.ext.get("power", 0) or 0) < 2:
        return "尚未渡过双重真劫（先 #渡劫）。"
    return None


def ascend_run(doc: PlayerDoc, table: list[dict], discount: float = 0.0) -> tuple[bool, str]:
    """登仙：无妄真劫境 → 地仙，消耗当前境界 exp（命格·渡劫修为减少可折减）。"""
    need = int(table[min(TRIB_REALM, len(table) - 1)].get("exp", 0) or 0)
    need = max(1, int(need * (1.0 - min(0.9, max(0.0, float(discount or 0))))))
    if doc.exp < need:
        return False, f"登仙需修为 {need:,}（当前 {doc.exp:,}）。"
    frm = table[TRIB_REALM].get("level", "无妄真劫境")
    to = table[min(ASCEND_REALM, len(table) - 1)].get("level", "地仙")
    doc.exp -= need
    doc.realm_index = ASCEND_REALM
    return True, (f"≡≡≡ 羽化登仙 ≡≡≡\n"
                  f"仙门大开，{frm} → 【{to}】！\n"
                  f"自此寿元悠长、法力通玄，仙人之下皆蝼蚁。\n"
                  f"消耗修为 {need:,}。")
