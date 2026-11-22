"""彩蛋玩法（W21-F2）——原版 Games.js / UserHome.js 杂项的轻量移植：
#打桩（运气小游戏）、#怡红院（灵石消费彩蛋）、#偷取纳戒 @目标（对抗互动）。

本移植（shortcut）：
- 打桩：随机成绩文案 + 小额灵石输赢，10 分钟 CD（原版细节台词删减）。
- 怡红院：灵石 5,000 消费 → 随机彩蛋文案，10% 「头牌」返双倍（原版无战斗收益）。
- 偷取纳戒：35% 得手随机偷一件未锁定物品（锁定/绑定保护未搬，shortcut），
  失败气血归一 + 魔道 +5；每日 3 次。目标档写走 handler 的 per-uid 锁。
- 遣龙/遣虎（周年令牌抽取）在 core/activity.py。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc
from .clock import day_key

EXT_KEY = "eggs"

ZHUANG_CD = 600
YIHONG_COST = 5_000
STEAL_CHANCE = 0.35
STEAL_CD = 0.0
STEAL_DAILY = 3
STEAL_MODAO = 5.0

ZHUANG_TEXT = (
    "一杆入魂，观者喝彩！", "稳如老桩，纹丝不动。", "半途而废，桩倒人仰。",
    "深浅有度，恰到好处。", "晃了三晃，勉强立住。",
)
YIHONG_TEXT = (
    "听了一曲《雾海残月》，心绪平和。", "姑娘只是斟茶，什么都没发生（真的）。",
    "推牌九赢了掌柜两坛酒。", "隔壁包间剑气纵横，你装作没看见。",
    "头牌今夜不接客，你被赠了一壶清茶。",
)


def _st(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = dict(raw) if isinstance(raw, dict) else {}
    st.setdefault("zhuang_ts", 0.0)
    st.setdefault("zhuang_wins", 0)
    st.setdefault("steal_day", "")
    st.setdefault("steal_used", 0)
    return st


def _save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[EXT_KEY] = dict(st)


def da_zhuang(doc: PlayerDoc, now: float | None = None,
              rng: random.Random | None = None) -> tuple[bool, str]:
    """#打桩：随机成绩，两成概率赢 3,000 灵石，10 分钟 CD。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = _st(doc)
    left = ZHUANG_CD - (now - float(st.get("zhuang_ts", 0) or 0))
    if left > 0:
        return False, f"桩还热着——休息 {int(left // 60) + 1} 分钟再来。"
    st["zhuang_ts"] = now
    zt_list = list(ZHUANG_TEXT)
    text = zt_list[int(rng.random() * len(zt_list)) % len(zt_list)]
    if rng.random() < 0.2:
        doc.stones = int(getattr(doc, "stones", 0) or 0) + 3_000
        st["zhuang_wins"] = int(st.get("zhuang_wins", 0) or 0) + 1
        _save(doc, st)
        return True, f"【打桩】{text}——围观群众打赏灵石 +3,000！"
    _save(doc, st)
    return True, f"【打桩】{text}（纯手艺，无收益；战绩 {st['zhuang_wins']} 胜）"


def yihongyuan(doc: PlayerDoc, now: float | None = None,
               rng: random.Random | None = None) -> tuple[bool, str]:
    """#怡红院：灵石 5,000 彩蛋消费，10% 头牌返双倍。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    if int(getattr(doc, "stones", 0) or 0) < YIHONG_COST:
        return False, f"怡红院消费 {YIHONG_COST:,} 灵石起——身上不够。"
    doc.stones = int(getattr(doc, "stones", 0) or 0) - YIHONG_COST
    yh_list = list(YIHONG_TEXT)
    text = yh_list[int(rng.random() * len(yh_list)) % len(yh_list)]
    if rng.random() < 0.10:
        doc.stones += YIHONG_COST * 2
        return True, (f"【怡红院】{text}\n头牌亲自相送——灵石 {YIHONG_COST:,} "
                      f"翻倍奉还（+{YIHONG_COST:,}）！")
    return True, f"【怡红院】{text}（消费 {YIHONG_COST:,} 灵石）"


def steal(doc: PlayerDoc, target_inv: Mapping[str, int], now: float | None = None,
          rng: random.Random | None = None) -> tuple[bool, str, str | None, int]:
    """#偷取纳戒：35% 得手随机一件。返回 (ok, msg, 被偷物品名, 数量1)。

    目标纳戒由 handler 读取（per-uid 锁内），扣减也由 handler 落库。
    """
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = _st(doc)
    day = day_key(now).replace("-", "")
    if st.get("steal_day") != day:
        st["steal_day"] = day
        st["steal_used"] = 0
    if int(st.get("steal_used", 0) or 0) >= STEAL_DAILY:
        return False, f"今日已伸手 {STEAL_DAILY} 次——江湖风声紧，明日再来。", None, 0
    st["steal_used"] = int(st["steal_used"]) + 1
    _save(doc, st)
    pool = [(k, v) for k, v in (target_inv or {}).items()
            if int(v or 0) > 0 and k != "灵石"]
    if not pool:
        return True, "对方纳戒空空如也——你空手而归（计数已耗）。", None, 0
    if rng.random() >= STEAL_CHANCE:
        ext = getattr(doc, "ext", None)
        if isinstance(ext, dict):
            ext["hp"] = 1
            ext["modao"] = float(ext.get("modao", 0) or 0) + STEAL_MODAO
        return True, (f"【偷取纳戒】被当场抓获！气血归一、魔道 +{STEAL_MODAO:g}"
                      f"（今日 {st['steal_used']}/{STEAL_DAILY}）。"), None, 0
    item, have = pool[int(rng.random() * len(pool)) % len(pool)]
    return True, (f"【偷取纳戒】得手——【{item}】×1 已入你纳戒"
                  f"（今日 {st['steal_used']}/{STEAL_DAILY}）。"), item, 1
