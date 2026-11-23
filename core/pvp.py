"""PvP 打劫 / 比武结算（W1-6，对齐原版 apps/Battle/Battle.js + WDT.js）。

原版语义：
- 打劫 `打劫 @目标`：A 胜 → 抢 B 灵石 1/5、A 得血气 100×A境界、魔道值 += 抢获/10000；
  B 有替身人偶（转生/仙人持有）可免疫本次劫掠。
  A 败 → A 灵石 ≥ 3 万则反被劫 1/4；否则被关禁闭 60 分钟（本移植省略禁闭，仅损失）。
  B 得血气 100×B境界。
- 比武 `比武 @目标`：友好切磋——胜者 1000×败者境界 / 败者 500×胜者境界 血气，
  双方各得 10×胜者境界 灵石；胜者魔道值 +1。
- 双方门槛：血量 > 上限/1.2（比武不可趁人之危）、6 小时比武 CD（双向）；
  打劫门槛：B 灵石 ≥ 3 万、B 血量 ≥ 2 万（按缩放表 ÷1000 → 3 万/2 万）。
- 隐身水：B 忙碌（闭关/秘境中）时 A 可消耗一瓶强行开战（物品存在，保留）。

数值标注：血气/灵石固定奖励为原版公式 1:1（原版即小额鼓励，未入缩放表）；
劫掠/反劫为比例制自动适配经济量级。
shortcut：仙帝威严·永寂、禁闭 action、同宗门检查（本移植宗门名可改）未复刻。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

ROB_CD = 30 * 60            # 打劫 CD（原版 cf.CD.rob=30 分钟）
BIWU_CD = 6 * 3600          # 比武 CD（原版 cf.CD.biwu/couple=6 小时，双向）
ROB_MIN_LOOT = 30_000       # B 灵石低于此不可打（原版 30002）
ROB_MIN_HP = 20_000         # B 血量低于此不可打（原版 20000）
BIWU_HP_RATIO = 1.2         # 双方血量需 > 上限/1.2
ROB_STEAL = 5               # 抢 B 灵石的 1/5
ROB_COUNTER = 4             # A 败反被劫 1/4
DAEMON_PER_STONE = 10_000   # 魔道值：抢获灵石 /10000 向下取整


def _realm1(doc: Any) -> int:
    v = doc.get("realm_index", 0) if isinstance(doc, Mapping) else getattr(doc, "realm_index", 0)
    return int(v or 0) + 1


def _xueqi(doc: Any) -> float:
    return float(_ext(doc).get("xueqi", 0) or 0)


def _ext(doc: Any) -> dict:
    """兼容 PlayerDoc 对象与 Mapping。"""
    ext = doc.get("ext") if isinstance(doc, Mapping) else getattr(doc, "ext", None)
    return ext if isinstance(ext, dict) else {}


def _name(doc: Any) -> str:
    return str(doc.get("name") or "对方") if isinstance(doc, Mapping) else str(doc.name or "对方")


def _stones(doc: Any) -> int:
    return int(doc.get("stones", 0) or 0) if isinstance(doc, Mapping) else int(doc.stones or 0)


def sync_health(doc: Any, hp_cur: int, hp_max: int) -> None:
    """Write the resolved current/max health used by the battle gates."""
    ext = _ext(doc)
    hp_max = max(0, int(hp_max or 0))
    ext["hp_max"] = hp_max
    ext["hp"] = min(hp_max, max(0, int(hp_cur or 0)))


def rob_check(a: Any, b: Any, now: float, b_busy: bool = False) -> str | None:
    """打劫前置检查：通过返回 None，否则返回拒绝文案。"""
    if _xueqi(a) < 0:
        return "修为亏损，还是先闭会关再打劫吧。"
    b_stones = _stones(b)
    b_name = _name(b)
    hp_cur = float(_ext(b).get("hp", 0) or 0)
    if hp_cur < ROB_MIN_HP:
        return f"{b_name} 重伤未愈，就不要再打他了。"
    if b_stones < ROB_MIN_LOOT:
        return f"{b_name} 穷得叮当响，就不要再打他了。"
    last = float(_ext(a).get("rob_ts", 0) or 0)
    if now - last < ROB_CD:
        return f"打劫正在 CD 中，剩余 {int((ROB_CD - (now - last)) // 60)} 分 {int((ROB_CD - (now - last)) % 60)} 秒。"
    if b_busy:
        return "__NEED_STEALTH__"     # 哨兵：B 忙碌，需隐身水（main 层判断库存）
    return None


def biwu_check(a: Any, b: Any, now: float) -> str | None:
    """比武前置检查（血量与双向 CD）。"""
    for who, doc in ((a, a), (b, b)):
        ext = _ext(doc)
        name = _name(doc)
        hp_cur = float(ext.get("hp", 0) or 0)
        hp_max = float(ext.get("hp_max", 0) or 0)
        if hp_cur <= hp_max / BIWU_HP_RATIO:
            return ("你" if doc is a else f"{name}") + "血量未满，不能趁人之危哦。"
        last = float(ext.get("biwu_ts", 0) or 0)
        if now - last < BIWU_CD:
            left = BIWU_CD - (now - last)
            return ("比武冷却: " if doc is a else "对方比武冷却: ") \
                + f"{int(left // 60)} 分 {int(left % 60)} 秒。"
    return None


def rob_settle(a: Any, b: Any, winner: int, b_has_dummy: bool = False) -> tuple[str, dict, dict]:
    """打劫结算。winner: 0=A 胜, 1=B 胜；b_has_dummy：B 背包有替身人偶（main 层查库存）。

    返回 (文案, a 的字段增量, b 的字段增量)；增量形如
    {"stones": ±x, "xueqi": +x, "modao": +x}。
    """
    a_name = str(a.name or "劫匪") if not isinstance(a, Mapping) else str(a.get("name") or "劫匪")
    b_name = str(b.name or "苦主") if not isinstance(b, Mapping) else str(b.get("name") or "苦主")
    a_stones = int(a.stones) if not isinstance(a, Mapping) else int(a.get("stones", 0) or 0)
    b_stones = int(b.stones) if not isinstance(b, Mapping) else int(b.get("stones", 0) or 0)
    da: dict = {}
    db: dict = {}
    if winner == 0:
        if b_has_dummy:
            db["dummy"] = -1
            return f"{b_name}使用了道具【替身人偶】，躲过了此次打劫。", da, db
        stolen = b_stones // ROB_STEAL
        qixue = 100 * _realm1(a)
        modao = stolen // DAEMON_PER_STONE
        da.update(stones=stolen, xueqi=qixue, modao=modao)
        db.update(stones=-stolen)
        return (f"经过一番大战，{a_name}击败了{b_name}，"
                f"成功抢走 {stolen:,} 灵石，获得 {qixue:,} 血气"
                + (f"，魔道值 +{modao}" if modao else "") + "。"), da, db
    # A 败：有钱则反被劫 1/4，否则只挨打
    qixue = 100 * _realm1(b)
    db["xueqi"] = qixue
    if a_stones >= ROB_MIN_LOOT:
        lost = a_stones // ROB_COUNTER
        da.update(stones=-lost)
        db.update(stones=lost)
        return (f"经过一番大战，{a_name}被{b_name}击败了，{b_name}获得 {qixue:,} 血气，"
                f"{a_name} 真是偷鸡不成蚀把米，反被劫走 {lost:,} 灵石。"), da, db
    return (f"经过一番大战，{a_name}被{b_name}击败了，{b_name}获得 {qixue:,} 血气，"
            f"{a_name} 偷鸡不成蚀把米，落荒而逃。"), da, db


def biwu_settle(a: Any, b: Any, winner: int) -> tuple[str, dict, dict]:
    """比武结算（友好切磋，双方都有奖励）。winner: 0=A 胜, 1=B 胜。"""
    a_name = str(a.name or "甲") if not isinstance(a, Mapping) else str(a.get("name") or "甲")
    b_name = str(b.name or "乙") if not isinstance(b, Mapping) else str(b.get("name") or "乙")
    win_doc, lose_doc = (a, b) if winner == 0 else (b, a)
    win_name = a_name if winner == 0 else b_name
    lose_name = b_name if winner == 0 else a_name
    win_realm = _realm1(win_doc)
    lose_realm = _realm1(lose_doc)
    q_win = 1000 * lose_realm       # 胜者血气：1000×败者境界
    q_lose = 500 * win_realm        # 败者血气：500×胜者境界
    stones = 10 * win_realm         # 双方各得
    da = {"xueqi": q_win if winner == 0 else q_lose, "stones": stones}
    db = {"xueqi": q_lose if winner == 0 else q_win, "stones": stones}
    if winner == 0:
        da["modao"] = 1
    else:
        db["modao"] = 1
    return (f"经过一番大战，{win_name}击败了{lose_name}获得胜利，"
            f"{win_name} 获得 {q_win:,} 血气，{lose_name} 获得 {q_lose:,} 血气，"
            f"双方各得 {stones:,} 灵石（以武会友）。"), da, db
