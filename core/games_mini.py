"""金银坊（W18-F1）——原版 `apps/Game/Games.js` Moneynumber（媚娘的赌坊）
简化移植：#金银坊 大|小 [注额]。两枚骰子 2~12：8~12 大、2~6 小、7 庄家吃、
围骰（2/12 双同）庄家通吃。赢返 ×1.9（含本）。入场默认 10,000 灵石，
上限 1,000,000；冷却由调用方控制（原版 CD.gambling=3 分钟）。

shortcut：梭哈/连庄/媚娘台词部分删减；金银坊记录字段 ext["jinyinfang"]。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

EXT_KEY = "jinyinfang"
DEFAULT_BET = 10_000
MAX_BET = 1_000_000
CD_SECONDS = 180


def _defaults() -> dict[str, Any]:
    return {"last": 0.0, "wins": 0, "rounds": 0}


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
    for k in ("last", "wins", "rounds"):
        st[k] = st.get(k, 0) or 0
    return st


def bet(doc: PlayerDoc, side: str, amount: int | None, now: float | None = None,
        rng: random.Random | None = None) -> tuple[bool, str]:
    """#金银坊 大|小 [注额]。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    left = CD_SECONDS - (now - float(st.get("last", 0) or 0))
    if left > 0:
        return False, f"媚娘摇着扇子：「急什么，还需 {int(left / 60) + 1} 分钟。」"
    side = (side or "").strip()
    if side not in ("大", "小"):
        return False, "用法：#金银坊 大|小 [注额]（默认 1 万，上限 100 万）。"
    amount = int(amount or DEFAULT_BET)
    amount = max(1_000, min(MAX_BET, amount))
    if int(getattr(doc, "stones", 0) or 0) < amount:
        return False, f"本钱不够：需灵石 {amount:,}（现有 {int(getattr(doc, 'stones', 0) or 0):,}）。"
    d1, d2 = int(rng.random() * 6) + 1, int(rng.random() * 6) + 1
    total = d1 + d2
    st["last"] = now
    st["rounds"] = int(st["rounds"]) + 1
    if d1 == d2:
        doc.stones = int(getattr(doc, "stones", 0) or 0) - amount
        save(doc, st)
        return True, (f"【金银坊】媚娘掷出 {d1}·{d2} —— 围骰！庄家通吃。\n"
                      f"灵石 -{amount:,}（围骰不认大小）")
    result = "大" if total >= 8 else ("小" if total <= 6 else "七")
    if result == side:
        win = int(amount * 0.9)
        doc.stones = int(getattr(doc, "stones", 0) or 0) + win
        st["wins"] = int(st["wins"]) + 1
        save(doc, st)
        return True, (f"【金银坊】媚娘掷出 {d1}·{d2} —— {total} 点，{result}！\n"
                      f"你赢了：灵石 +{win:,}（战绩 {st['wins']}/{st['rounds']}）")
    doc.stones = int(getattr(doc, "stones", 0) or 0) - amount
    save(doc, st)
    return True, (f"【金银坊】媚娘掷出 {d1}·{d2} —— {total} 点，{result}。\n"
                  f"灵石 -{amount:,}（战绩 {st['wins']}/{st['rounds']}）")
