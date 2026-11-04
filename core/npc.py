"""剧情 NPC：狠人大帝 / 苏灵（对齐原版 User/RuthlessEmperor.js、SuLing.js）。

- 好感度：交流 +5~8；关系档位（狠人）：0 时间长河一瞥 / 60 青铜鬼面 / 180 隔世相知 /
  300 道途同行 / 480 护道之约
- 狠人请教：好感 ≥180 隔世相知，随机授一门未拥有的狠人功法
  （飞仙诀/万化圣诀/不灭天功/万化仙诀——均在功法列表）
- 苏灵请教：好感 ≥240 命途相知，每日 1 次，累计 10 次领悟终极「命运终章·移劫夺运」
- 交流每日 3 次上限（原版可无限刷，加限防挂机，标注）
- 凝聚精血：灵根 type 含圣体/神体/道胎/混沌/妖体 → 每 7 天凝聚 1 份「妖体精血」
  （原版「本命精血」不在物品表 → 用妖体精血承载，标注偏差）
"""

from __future__ import annotations
from .clock import day_key

import copy
import random
import time
from typing import Any, Mapping

RELATIONSHIPS = [
    (480, "护道之约"),
    (300, "道途同行"),
    (180, "隔世相知"),
    (60, "青铜鬼面"),
    (0, "时间长河一瞥"),
]

# 苏灵的关系档位与狠人分开（原版二人共用 1~4 级，这里各给一套贴原著的称谓）
SULING_RELATIONSHIPS = [
    (480, "移劫之约"),
    (360, "终幕同行"),
    (240, "命途相知"),
    (120, "并肩劫云"),
    (60, "星河同游"),
    (0, "初识命轮"),
]

RUTHLESS_TEACH_FAVOR = 180
SULING_DEEP_FAVOR = 240
SULING_TOTAL_TEACH = 10
SULING_ULTIMATE = "命运终章·移劫夺运"

RUTHLESS_TEACHINGS = ["飞仙诀", "万化圣诀", "不灭天功", "万化仙诀"]

DAILY_TALK_LIMIT = 3
ESSENCE_CD = 7 * 86400
ESSENCE_ITEM = "妖体精血"
ESSENCE_TYPES = ("圣体", "神体", "道胎", "混沌", "妖体", "魔体", "道体")

RUTHLESS_TALKS = [
    "狠人大帝立于时间长河畔，看了你一眼：「你与我当年……有三分相似。」",
    "他抬手截断一缕时光，淡淡道：「大道无情，人有情。守住你的情。」",
    "青铜鬼面下的声音低沉：「我曾为一个人，逆了整条时间长河。」",
    "他指间缠绕的因果线颤动：「修行不是争，是守。守得住，才走得远。」",
    "「飞仙不是飞升，是把牵挂炼成翅膀。」他转身，衣袍扫过星河。",
]
SULING_TALKS = [
    "苏灵拨动命运轮盘：「你的命线……分岔了三次，有趣。」",
    "她笑着递来一盏茶：「命是自己的，轮盘只是镜子。」",
    "「移劫夺运不是偷，是借。借了要还的。」她眨眨眼。",
    "苏灵望着轮盘出神：「我算过所有人的命，唯独算不出你的。」",
    "「下一幕，你想看哪种结局？」她指尖停在轮盘边缘。",
]

SULING_BEATS = [
    (0, "初识·命运轮盘"),
    (60, "同游·星河渡口"),
    (120, "并肩·劫云之下"),
    (240, "相知·命途共览"),
    (360, "终幕·移劫之约"),
]


def state_of(doc: Mapping) -> dict:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, Mapping):
        ext = doc if isinstance(doc, Mapping) else {}
    n = ext.get("npc") if isinstance(ext, Mapping) else None
    n = copy.deepcopy(n) if isinstance(n, dict) else {}
    for key in ("ruthless", "suling"):
        d = n.get(key) if isinstance(n.get(key), dict) else {}
        d.setdefault("favor", 0)
        d.setdefault("talk_day", "")
        d.setdefault("talk_count", 0)
        d.setdefault("teach_day", "")
        d.setdefault("teach_total", 0)
        d.setdefault("learned", [])
        d.setdefault("ultimate", False)
        n[key] = d
    n.setdefault("essence_ts", 0.0)
    return n


def relation_of(favor: float, who: str = "ruthless") -> str:
    tiers = SULING_RELATIONSHIPS if who == "suling" else RELATIONSHIPS
    for need, name in tiers:
        if favor >= need:
            return name
    return tiers[-1][1]


def _date_key(ts: float) -> str:
    return day_key(ts)


def talk(n: dict, who: str, now: float) -> tuple[bool, str, dict]:
    d = n[who]
    day = _date_key(now)
    if d.get("talk_day") != day:
        d["talk_day"] = day
        d["talk_count"] = 0
    if int(d["talk_count"]) >= DAILY_TALK_LIMIT:
        return False, f"今日已与{'狠人大帝' if who == 'ruthless' else '苏灵'}论道 {DAILY_TALK_LIMIT} 次，明日再来。", n
    gain = 5 + random.randrange(4)
    old = int(d["favor"])
    d["favor"] = old + gain
    d["talk_count"] = int(d["talk_count"]) + 1
    old_rel = relation_of(old, who)
    new_rel = relation_of(d["favor"], who)
    line = random.choice(RUTHLESS_TALKS if who == "ruthless" else SULING_TALKS)
    tail = f"\n好感度 +{gain}（{d['favor']}，{new_rel}）"
    if new_rel != old_rel:
        tail += f"\n✦ 关系提升为「{new_rel}」！"
    return True, line + tail, n


def teach_ruthless(n: dict, owned_gongfa: list[str]) -> tuple[bool, str, dict, str | None]:
    d = n["ruthless"]
    if int(d["favor"]) < RUTHLESS_TEACH_FAVOR:
        return False, f"与狠人大帝关系未至「隔世相知」（需 {RUTHLESS_TEACH_FAVOR} 好感，当前 {d['favor']}）。", n, None
    learned = list(d.get("learned") or [])
    pool = [g for g in RUTHLESS_TEACHINGS if g not in learned and g not in owned_gongfa]
    if not pool:
        d["favor"] = int(d["favor"]) + 3
        return True, "狠人大帝摇头：「我这几部法门，你已尽得。」（好感 +3）", n, None
    pick = random.choice(pool)
    d["learned"] = learned + [pick]
    return True, (f"狠人大帝指间流光化作古卷：「此乃【{pick}】，与你有机缘。」\n"
                  f"（已收入纳戒，可 #学习 功法名 修习）"), n, pick


def teach_suling(n: dict, now: float) -> tuple[bool, str, dict, dict]:
    d = n["suling"]
    if int(d["favor"]) < SULING_DEEP_FAVOR:
        return False, f"与苏灵关系未至「命途相知」（需 {SULING_DEEP_FAVOR} 好感，当前 {d['favor']}）。", n, {}
    day = _date_key(now)
    if d.get("teach_day") == day:
        return False, "苏灵今日已为你推演过一次命运（每日一次）。", n, {}
    if d.get("ultimate"):
        return False, "你已领悟「命运终章·移劫夺运」，再无更高奥义。", n, {}
    d["teach_day"] = day
    d["teach_total"] = int(d.get("teach_total", 0)) + 1
    total = int(d["teach_total"])
    if total >= SULING_TOTAL_TEACH:
        d["ultimate"] = True
        return True, (f"第 {total} 次推演，命运轮盘轰然绽放！\n"
                      f"✦ 你领悟了终极奥义「{SULING_ULTIMATE}」——命运之线在你掌心重编！\n"
                      f"（仙道潜力 +200，修为一举突破）"), n, {"potential": 200, "exp": 200_000_000}
    return True, (f"苏灵为你推演命途（第 {total}/{SULING_TOTAL_TEACH} 次）："
                  f"「你的前路上，有一道劫……在第三幕等你。」\n（修为 +5000 万）"), n, {"exp": 50_000_000}


def beat_of(n: dict) -> str:
    favor = int(n["suling"]["favor"])
    cur = SULING_BEATS[0][1]
    for need, name in SULING_BEATS:
        if favor >= need:
            cur = name
    nxt = next((f"{need} 好感解锁「{name}」" for need, name in SULING_BEATS if favor < need), "五幕剧情均已解锁")
    return f"{cur}｜{nxt}"


def essence(doc: Mapping, n: dict, now: float) -> tuple[bool, str, dict]:
    lg = (doc.ext.get("linggen") or {}) if isinstance(doc.ext, Mapping) else {}
    ltype = str(lg.get("type") or "")
    if not any(k in ltype for k in ESSENCE_TYPES):
        return False, "你的灵根非圣体/神体/道胎/混沌/妖体等特殊体质，无法凝聚本命精血。", n
    if now - float(n.get("essence_ts", 0.0)) < ESSENCE_CD:
        days = int((ESSENCE_CD - (now - float(n["essence_ts"]))) / 86400) + 1
        return False, f"精血刚刚凝聚过，需静养（约 {days} 天）。", n
    n["essence_ts"] = now
    return True, (f"你运转{lg.get('name') or '特殊体质'}之力，逼出一滴晶莹的本命精血……\n"
                  f"（获得 {ESSENCE_ITEM} ×1，7 天后可再凝）"), n


def panel(n: dict, now: float) -> str:
    r, s = n["ruthless"], n["suling"]
    lines = [
        "--- 剧情人物 ---",
        f"【狠人大帝】关系：{relation_of(r['favor'], 'ruthless')}（{r['favor']} 好感）",
        f"  已授法门：{'、'.join(r.get('learned') or []) or '（无）'}｜请教需 {RUTHLESS_TEACH_FAVOR} 好感",
        f"【苏灵】关系：{relation_of(s['favor'], 'suling')}（{s['favor']} 好感）",
        f"  推演进度：{s.get('teach_total', 0)}/{SULING_TOTAL_TEACH}"
        + ("（已领悟终极）" if s.get("ultimate") else f"｜请教需 {SULING_DEEP_FAVOR} 好感、每日一次"),
        f"  剧情：{beat_of(n)}",
        "交流：#狠人交流 / #苏灵交流（每日 3 次）｜请教：#狠人请教 / #苏灵请教｜#凝聚精血",
    ]
    return "\n".join(lines)
