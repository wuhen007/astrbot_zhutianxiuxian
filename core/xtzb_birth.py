"""至宝出世 · 24h 全服择主（W20-F1）——原版 `model/innateTreasureContest.js`
择主之争 + `apps/SecretPlace/SecretPlace.js` 出世试炼的纯函数移植，
复用 `core/xtzb.py` 的 owners/projection 认主模型（本体唯一 + 七日投影）。

原版语义：至宝降世开启 24h 争夺；参与者完成「挑战守护灵 / 参悟先天禁制 /
护持天地灵脉」三试炼（命运乱流为高风险额外位），各立道心；窗口结束按
试炼 + 性情契合 + 天运公开择主——冠军本体、2、3 名七日投影。

本移植（shortcut）：
- 无全服定时器：出世窗口由 `#观摩灵宝 [至宝名]` 手动开启，到期由任一相关
  指令惰性结算（birth_settle）。
- 逐宝性情契合表未搬，改为按至宝名确定性映射四道心之一（契合 +150 分）。
- 试炼为单次判定制（原版为战斗/悟性检定）；命运乱流高风险高收益，
  失败气血归一。
- 择主发放：core 返回 ops 名单，handler 循环 `birth_prize` 写各玩家档
  （同 _raid_settle 先例）；本体唯一性由 xtzb world["owners"] 保证。

跨模块：只 import `.xtzb` 的纯函数/常量（state_of/ensure/save/ALIASES/
CONTESTABLE/PROJECTION_SECONDS），不反向依赖 handler。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc
from .xtzb import ALIASES, CONTESTABLE, PROJECTION_SECONDS, ensure, save, state_of

BIRTH_HOURS = 24
BIRTH_GATE = 12                       # 报名境界（与 CLAIM_REALM 一致）
TRIAL_SCORE: dict[str, tuple[int, int]] = {
    "守护灵": (100, 20), "先天禁制": (120, 20),
    "天地灵脉": (80, 20), "命运乱流": (200, 40),
}
TRIAL_CHANCE_BASE: dict[str, float] = {
    "守护灵": 0.50, "先天禁制": 0.55, "天地灵脉": 0.60, "命运乱流": 0.35,
}
VOWS: tuple[str, ...] = ("镇压诸天", "守护苍生", "参悟大道", "逍遥天地")
VOW_MATCH = 150
FATE_MAX = 50
PRIZE_DEPTH = 3                       # 冠军本体 + 2、3 名七日投影


def _authority(doc: Any) -> int:
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


def _birth_of(world: dict[str, Any], name: str) -> dict[str, Any]:
    births = world.setdefault("birth", {})
    b = births.get(name)
    if not isinstance(b, dict):
        b = {}
    b.setdefault("opened_at", 0.0)
    b.setdefault("expires_at", 0.0)
    b.setdefault("trials", {})        # uid -> {行动名: 得分}
    b.setdefault("vows", {})          # uid -> 道心
    b.setdefault("settled", False)
    b.setdefault("outcome", [])
    births[name] = b
    return b


def birth_vow_of(name: str) -> str:
    """性情契合：按至宝名确定性映射四道心（原版逐宝契合表未搬）。"""
    return VOWS[sum(ord(c) for c in name) % len(VOWS)]


def birth_open(doc: PlayerDoc, world: dict[str, Any], name: str, now: float,
               ) -> tuple[bool, str, bool]:
    """#观摩灵宝 [至宝名]：开启/加入 24h 出世窗口。返回 (ok, msg, changed)。"""
    key = ALIASES.get(name, name)
    if key not in CONTESTABLE:
        if key == "永恒仙图":
            return False, "永恒仙图由九宝合成，不走出世之争。", False
        return False, f"未知至宝【{name}】，#至宝图鉴 查看名录。", False
    realm = max(int(getattr(doc, "realm_index", 0) or 0),
                int(getattr(doc, "physique_index", 0) or 0))
    if realm < BIRTH_GATE:
        return False, f"观看出世需第 {BIRTH_GATE + 1} 境以上（当前第 {realm + 1} 境）。", False
    births = world.setdefault("birth", {})
    b = births.get(key)
    if isinstance(b, dict) and not b.get("settled") and float(b.get("expires_at", 0) or 0) > now:
        trials = b.setdefault("trials", {})
        if str(doc.uid) in trials:
            return False, ("你已在【" + key + "】出世之争中——"
                           "#挑战守护灵 等行动继续积累。"), False
        trials[str(doc.uid)] = {}
        return True, (f"【观摩灵宝 · {key}】你加入争夺！剩余 "
                      f"{int((float(b['expires_at']) - now) / 3600)} 小时。\n"
                      "试炼：#挑战守护灵 / #参悟先天禁制 / #护持天地灵脉 / "
                      "#跃入命运乱流（各一次）｜道心：#立下道心 "
                      + "/".join(VOWS)), False
    b = _birth_of(world, key)
    b.update({"opened_at": now, "expires_at": now + BIRTH_HOURS * 3600,
              "trials": {str(doc.uid): {}}, "vows": {}, "settled": False,
              "outcome": []})
    preferred = birth_vow_of(key)
    return True, (f"≡≡≡ 至宝出世 · {key} ≡≡≡\n"
                  f"天机云动，{key} 降世征主——24 小时内择主！\n"
                  "你已率先入局。三试炼 + 立道心"
                  f"（契合【{preferred}】者 +{VOW_MATCH} 分）。\n"
                  "四行动各一次，见 #灵宝择主榜。"), True


def birth_trial(doc: PlayerDoc, world: dict[str, Any], name: str, trial: str,
                now: float, rng: random.Random) -> tuple[bool, str]:
    """四试炼各一次：守护灵/先天禁制/天地灵脉/命运乱流。"""
    if trial not in TRIAL_SCORE:
        return False, ("试炼限定：#挑战守护灵 / #参悟先天禁制 / "
                       "#护持天地灵脉 / #跃入命运乱流。")
    key = ALIASES.get(name, name)
    births = world.setdefault("birth", {})
    b = births.get(key)
    if not isinstance(b, dict) or b.get("settled") or float(b.get("expires_at", 0) or 0) <= now:
        return False, f"【{key}】当前没有进行中的出世之争——#观摩灵宝 {key} 开启。"
    trials = b.setdefault("trials", {})
    mine = trials.setdefault(str(doc.uid), {})
    if trial in mine:
        return False, f"【{trial}】你已闯过（每项一次）。"
    auth = _authority(doc)
    chance = min(0.9, max(0.10, TRIAL_CHANCE_BASE[trial] + auth * 0.008))
    won = rng.random() < chance
    score = TRIAL_SCORE[trial][0 if won else 1]
    mine[trial] = score
    trials[str(doc.uid)] = mine
    left = max(0, int((float(b["expires_at"]) - now) / 3600))
    total = sum(int(v) for v in mine.values())
    extra = ""
    if trial == "命运乱流" and not won:
        extra = "｜乱流反噬，气血归一"
        ext = getattr(doc, "ext", None)
        if isinstance(ext, dict):
            ext["hp"] = 1
    return True, (f"【{trial} · {key}出世】{'得手' if won else '失利'}——"
                  f"+{score} 分（{chance:.0%}）{extra}\n"
                  f"个人累计 {total} 分｜窗口剩 {left} 小时｜"
                  f"已试炼 {len(mine)}/4 项")


def birth_vow(doc: PlayerDoc, world: dict[str, Any], name: str, vow: str,
              now: float | None = None) -> tuple[bool, str]:
    """#立下道心：四选一，契合者在结算加成。"""
    now = time.time() if now is None else float(now)
    key = ALIASES.get(name, name)
    vow = (vow or "").strip()
    births = world.setdefault("birth", {})
    b = births.get(key)
    if not isinstance(b, dict) or b.get("settled") or float(b.get("expires_at", 0) or 0) <= now:
        return False, f"【{key}】出世之争未在进行中。"
    if vow not in VOWS:
        return False, f"用法：#立下道心 {'/'.join(VOWS)}。"
    trials = b.setdefault("trials", {})
    if str(doc.uid) not in trials:
        return False, "先 #观摩灵宝 报名入局，方可立道心。"
    vows = b.setdefault("vows", {})
    if str(doc.uid) in vows:
        return False, "道心不二——你已立下【" + str(vows[str(doc.uid)]) + "】。"
    vows[str(doc.uid)] = vow
    preferred = birth_vow_of(key)
    note = "（性情契合！结算 +150）" if vow == preferred else f"（契合此宝者为【{preferred}】）"
    return True, f"【立下道心 · {vow}】道音立，誓不回头。{note}"


def birth_settle(world: dict[str, Any], now: float, rng: random.Random,
                 ) -> tuple[str, list[dict[str, Any]]]:
    """惰性结算全部到期窗口。返回 (公告, ops)。

    ops: [{uid, name, treasure, prize}]，prize ∈ {本体, 投影}；
    handler 据此调用 birth_prize 逐人写档（需自行 get_player）。
    """
    births = world.setdefault("birth", {})
    notices: list[str] = []
    ops: list[dict[str, Any]] = []
    for key, b in list(births.items()):
        if not isinstance(b, dict) or b.get("settled"):
            continue
        if float(b.get("expires_at", 0) or 0) > now:
            continue
        scores: list[tuple[int, str, str]] = []
        trials = b.get("trials") or {}
        vows = b.get("vows") or {}
        preferred = birth_vow_of(key)
        for uid, mine in trials.items():
            s = sum(int(v) for v in (mine or {}).values())
            if vows.get(uid) == preferred:
                s += VOW_MATCH
            s += int(rng.random() * FATE_MAX)           # 天运 0~50
            scores.append((s, uid, vows.get(uid) or "未立道心"))
        scores.sort(key=lambda t: -t[0])
        b["settled"] = True
        if not scores:
            b["outcome"] = []
            continue
        outcome = []
        for rank, (s, uid, vow) in enumerate(scores[:PRIZE_DEPTH], 1):
            prize = "本体" if rank == 1 else "投影"
            outcome.append({"rank": rank, "uid": uid, "score": s,
                            "vow": vow, "prize": prize})
            ops.append({"uid": uid, "treasure": key, "prize": prize})
        b["outcome"] = outcome
        champ = outcome[0]
        notices.append(
            f"≡≡≡ 择主之争 · {key} ≡≡≡\n"
            + "\n".join(f"{o['rank']}. {o['uid'][:12]}…｜{o['score']} 分"
                        f"（{o['vow']}）→ {'认主本体' if o['prize'] == '本体' else '七日投影'}"
                        for o in outcome)
            + f"\n【{key}】择主已定！")
    return "\n\n".join(notices), ops


def birth_prize(doc: PlayerDoc, treasure: str, prize: str, now: float) -> None:
    """把择主结果写进本人 xtzb 档（本体 / 七日投影）。"""
    st = state_of(doc, now)
    if prize == "本体":
        if treasure not in st["owned"]:
            st["owned"].append(treasure)
        st["projection"].pop(treasure, None)
    else:
        st.setdefault("projection", {})[treasure] = now + PROJECTION_SECONDS
        if treasure not in st["owned"]:
            st["owned"].append(treasure)
    save(doc, st)


def birth_board(world: Mapping[str, Any], now: float) -> str:
    births = world.get("birth") or {}
    lines = ["--- 灵宝择主榜 ---"]
    live = 0
    for key, b in births.items():
        if not isinstance(b, dict):
            continue
        if not b.get("settled") and float(b.get("expires_at", 0) or 0) > now:
            live += 1
            left = int((float(b["expires_at"]) - now) / 3600)
            scores = []
            for uid, mine in (b.get("trials") or {}).items():
                s = sum(int(v) for v in (mine or {}).values())
                if (b.get("vows") or {}).get(uid) == birth_vow_of(key):
                    s += VOW_MATCH
                scores.append((s, uid))
            scores.sort(key=lambda t: -t[0])
            lines.append(f"【{key}】剩 {left} 小时｜{len(b.get('trials') or {})} 人入局")
            for s, uid in scores[:5]:
                lines.append(f"  · {uid[:12]}… {s} 分")
    if not live:
        lines.append("当前无进行中的出世之争——#观摩灵宝 至宝名 开启。")
    return "\n".join(lines)
