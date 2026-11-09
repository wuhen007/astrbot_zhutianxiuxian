"""活动系统：星海之缘 / 周年庆（W16-F1）——原版 `apps/Anniversary/Anniversary.js`
（星海之缘签到 L162 / 召唤爱莉希雅 L267 / 周年签到）纯函数移植。

本移植（shortcut）：
- 签到奖励 ÷1000 折算：修为=血气 `100×天数`（原 10 万×天数，999 天封顶）、
  群星秘钥 ×1、召唤次数 +1；连续 7 天里程碑：灵石 200,000 + 魔君讨伐令 ×3
  + 真我宝盒 ×1 + 群星秘钥 ×5。
- 召唤池：往世乐土之章 4%、真我宝盒 1%、天药/潜力丹/群星秘钥/灵石若干；
  「无化如是」为天资彩蛋文案（本移植无天资洗炼池）。
- #真我觉醒：往世乐土之章 ×3 → 爱莉希雅·真我（称号，战斗加成留给装备乘区）。
- 周年庆仅 #周年签到（遣龙/虎十连彩蛋未搬）。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

EXT_KEY = "activity"

DAILY_EXP = 100               # 原 10 万 × 天数 ÷1000
STREAK_MILESTONE = 7
GACHA_POOL: tuple[tuple[str, int, str], ...] = (
    ("往世乐土之章", 4, "★4"),
    ("真我宝盒", 1, "★5"),
    ("九转天药", 8, "★3"),
    ("洗髓丹", 15, "★3"),
    ("群星秘钥", 22, "★2"),
    ("灵石袋", 50, "★1"),
)


def _defaults() -> dict[str, Any]:
    return {"xh_day": "", "xh_streak": 0, "draws": 0, "chapters": 0,
            "zhenwo": False, "zn_day": "", "zn_streak": 0}


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
    for k in ("xh_streak", "draws", "chapters", "zn_streak"):
        st[k] = int(st.get(k, 0) or 0)
    st["zhenwo"] = bool(st.get("zhenwo"))
    save(doc, st)
    return st


def _day_key(now: float) -> str:
    return time.strftime("%Y%m%d", time.localtime(now))


def xinghai_sign(doc: PlayerDoc, now: float | None = None,
                 ) -> tuple[bool, str, dict[str, int]]:
    """#星海之缘签到：修为血气×天数 + 群星秘钥 + 召唤次数；7 天里程碑。"""
    now = time.time() if now is None else float(now)
    if int(getattr(doc, "realm_index", 0) or 0) < 41:
        return False, "星海之缘需成仙方可参与（#登仙）。", {}
    st = state_of(doc)
    day = _day_key(now)
    if st.get("xh_day") == day:
        return False, "今日已在往世星海签到——明天再来。", {}
    yesterday = time.strftime("%Y%m%d", time.localtime(now - 86400))
    streak = int(st.get("xh_streak", 0) or 0) + 1 if st.get("xh_day") == yesterday else 1
    days = min(999, streak)
    gain = DAILY_EXP * days
    doc.exp = int(getattr(doc, "exp", 0) or 0) + gain
    xq = int(float((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0)) + gain
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["xueqi"] = xq
    st["xh_day"] = day
    st["xh_streak"] = streak
    st["draws"] = int(st.get("draws", 0) or 0) + 1
    delta: dict[str, int] = {"群星秘钥": 1}
    msg = (f"【星海之缘签到 · 第 {streak} 天】\n"
           f"修为与血气各 +{gain:,}｜群星秘钥 ×1｜召唤次数 +1（现有 {st['draws']}）")
    if streak % STREAK_MILESTONE == 0:
        delta.update({"魔君讨伐令": 3, "真我宝盒": 1, "群星秘钥": 5})
        doc.stones = int(getattr(doc, "stones", 0) or 0) + 200_000
        msg += (f"\n≡ 连续 {streak} 天里程碑 ≡\n灵石 +200,000｜魔君讨伐令 ×3｜"
                "真我宝盒 ×1｜群星秘钥 ×5")
    save(doc, st)
    return True, msg, delta


def gacha(doc: PlayerDoc, times: int, now: float | None = None,
          rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#召唤爱莉希雅（1）/ #疯狂召唤爱莉希雅（10）。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    times = max(1, min(10, int(times or 1)))
    if st["draws"] < times:
        return False, f"召唤次数不足（现有 {st['draws']}，需 {times}）——先 #星海之缘签到。", {}
    st["draws"] -= times
    delta: dict[str, int] = {}
    lines: list[str] = []
    weights = [w for _, w, _ in GACHA_POOL]
    for _ in range(times):
        roll = rng.random() * sum(weights) * 100 / 100
        acc = 0.0
        picked = GACHA_POOL[-1][0]
        for name, w, star in GACHA_POOL:
            acc += w
            if roll <= acc:
                picked = name
                break
        delta[picked] = delta.get(picked, 0) + 1
        if picked == "往世乐土之章":
            st["chapters"] = int(st.get("chapters", 0) or 0) + 1
        star = dict((n, s) for n, _, s in GACHA_POOL).get(picked, "")
        lines.append(f"{star} {picked}")
    save(doc, st)
    head = "【疯狂召唤 · 爱莉希雅】" if times > 1 else "【召唤 · 爱莉希雅】"
    extra = ""
    if st["chapters"] >= 3 and not st["zhenwo"]:
        extra = "\n（乐土之章 ×3 已集齐——#真我觉醒 吧！）"
    return True, (f"{head}×{times}\n" + "\n".join(lines)
                  + f"\n剩余召唤次数 {st['draws']}｜乐土之章 {st['chapters']}/3{extra}"), delta


def awaken_zhenwo(doc: PlayerDoc) -> tuple[bool, str]:
    """#真我觉醒：乐土之章 ×3。"""
    st = state_of(doc)
    if st.get("zhenwo"):
        return False, "你已是【爱莉希雅·真我】——人之美好，由你证明。"
    if st.get("chapters", 0) < 3:
        return False, f"真我觉醒需【往世乐土之章】×3（现有 {st.get('chapters', 0)}）。"
    st["zhenwo"] = True
    st["chapters"] = int(st["chapters"]) - 3
    save(doc, st)
    return True, ("≡≡≡ 真我觉醒 ≡≡≡\n「人として、美しいものを」——\n"
                  "爱莉希雅·真我 与你同行：称号【真我】录入，往世乐土自此有主。")


def anniversary_sign(doc: PlayerDoc, now: float | None = None,
                     rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#周年签到：灵石 + 遣龙令/遣虎令。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    day = _day_key(now)
    if st.get("zn_day") == day:
        return False, "今日已行周年签到。", {}
    yesterday = time.strftime("%Y%m%d", time.localtime(now - 86400))
    streak = int(st.get("zn_streak", 0) or 0) + 1 if st.get("zn_day") == yesterday else 1
    st["zn_day"] = day
    st["zn_streak"] = streak
    delta: dict[str, int] = {}
    picks = []
    for _ in range(min(4, 1 + streak // 3)):
        picks.append(["遣龙令", "遣虎令"][int(rng.random() * 2) % 2])
    for p in picks:
        delta[p] = delta.get(p, 0) + 1
    doc.stones = int(getattr(doc, "stones", 0) or 0) + 50_000 * streak
    save(doc, st)
    return True, (f"【周年签到 · 第 {streak} 天】灵石 +{50_000 * streak:,}｜"
                  + "、".join(f"{p}×{delta[p]}" for p in delta)), delta


def panel(doc: Any) -> str:
    st = state_of(doc)
    return "\n".join([
        "--- 活动 · 星海之缘 / 周年庆 ---",
        f"星海连签 {st.get('xh_streak', 0)} 天（今日{'已' if st.get('xh_day') == _day_key(time.time()) else '未'}签）"
        f"｜召唤次数 {st.get('draws', 0)}｜乐土之章 {st.get('chapters', 0)}/3"
        f"｜真我：{'已觉醒' if st.get('zhenwo') else '未觉醒'}",
        f"周年连签 {st.get('zn_streak', 0)} 天",
        "指令：#星海之缘签到 / #召唤爱莉希雅 / #疯狂召唤爱莉希雅 / #真我觉醒 / #周年签到",
    ])
