"""剧情人物全集：图鉴 / 邂逅 / 好感 / 护道之约 / 黑皇阵道。

对齐原版：
- data/item/剧情人物列表.json 10 位人物（图鉴按位面分组，立绘 + 解锁状态）
- model/planeStoryCharacters.js：盖九幽（遮天）、孟天正（九天十地）随机邂逅
- SecretPlaceTask.js：张五爷（遮天荒古禁地，赠源师转职凭证）、柳神（石村，修为 +10%）
- model/blackEmperor.js：黑皇（副本 3%）、段德（遮天 0.1% 掉欺天石）
- model/npcProtector.js：柳神/苏灵/狠人大帝 480 好感可立护道之约，24 小时一次

本移植的改编（均在文档标注）：
- 原版按「位面」判定邂逅；本插件秘境只有 4 个地点，改为按地点映射位面
- 原版柳神需「石村 + 搬血极境」，本插件无极境体系，改为青冥山第 3 层初遇
- 原版黑皇在「副本通关」3% 触发，本插件无副本，改为太古战场第 5 层
- 原版护道人在战斗中直接秒杀来敌；本插件在秘境战败瞬间出手，保你不死、不损收益
- 原版位面传送阵给「位面传送次数」；本插件无位面旅行，改为秘境战败自动脱身
"""

from __future__ import annotations

import copy
import random
import time
from typing import Any, Mapping

# ---------------------------------------------------------------- 通用关系档


GENERIC_TIERS = [
    (480, None),          # 480 档按人物定制（见 TIER_480）
    (300, "知己"),
    (180, "倾盖如故"),
    (60, "相识"),
    (0, "初识"),
]

TIER_480 = {
    "柳神": "护道者",
    "张五爷": "忘年交",
    "盖九幽": "九幽知音",
    "孟天正": "大长老门生",
}

HEI_TIERS = [
    (360, "帝阵传人"),
    (240, "生死之交"),
    (120, "自己人"),
    (40, "熟人"),
    (0, "初识"),
]

# 好感门槛（护道之约，原版三人皆 480）
PROTECTOR_FAVOR = 480
PROTECTOR_CD = 24 * 3600

# 黑皇
HEI_TEACH_FAVOR = 80
HEI_TALK_LIMIT = 3

# 普通邂逅人物重复相遇概率
REPEAT_CHANCE = 0.12
# 段德盗墓客串概率
DUANDE_CHANCE = 0.008

# ---------------------------------------------------------------- 人物配置

STORY: dict[str, dict[str, Any]] = {
    "柳神": {
        "place": "青冥山",
        "floor": 3,
        "relation": "护道者",
        "identity": "仙古祖祭灵",
        "hint": "青冥山 · 第 3 层",
        "protector": True,
    },
    "孟天正": {
        "place": "落霞谷",
        "floor": 3,
        "relation": "大长老门生",
        "identity": "九天十地守护者",
        "hint": "落霞谷 · 第 3 层",
        "protector": False,
    },
    "盖九幽": {
        "place": "幽冥渊",
        "floor": 4,
        "relation": "九幽知音",
        "identity": "人族绝代准帝",
        "hint": "幽冥渊 · 第 4 层",
        "protector": False,
    },
    "张五爷": {
        "place": "幽冥渊",
        "floor": 6,
        "relation": "忘年交",
        "identity": "源天师后人",
        "hint": "幽冥渊 · 第 6 层",
        "protector": False,
    },
    "黑皇": {
        "place": "太古战场",
        "floor": 5,
        "relation": "帝阵传人",
        "identity": "无始大帝的仙宠",
        "hint": "太古战场 · 第 5 层",
        "protector": False,
    },
    "段德": {
        "place": "太古战场",
        "floor": 1,
        "relation": "初识",
        "identity": "曹雨生转世",
        "hint": "太古战场 · 随机（盗墓贼）",
        "protector": False,
        "cameo": True,
    },
}

# 每个地点会重复出现的人物
PLACE_CANDS = {
    "青冥山": ["柳神"],
    "落霞谷": ["孟天正"],
    "幽冥渊": ["盖九幽", "张五爷"],
    "太古战场": ["黑皇"],
}

# 图鉴里永远可查、无需邂逅的人物（原版直接开放）
ALWAYS_OPEN = {"苏灵", "狠人大帝"}
# 只存于传说的图鉴人物
LEGEND_ONLY = {"石昊", "叶萧", "莫晓羽"}

# ---------------------------------------------------------------- 文本

LIUSHEN_FIRST = (
    "你在青冥山深处误入一处荒村废墟。村口焦黑的柳树桩忽生异象，一抹嫩绿新芽破桩而出，"
    "浩瀚生命精气席卷四野。虚空颤动，一道朦胧身影自柳树中显化，眸若星辰，俯瞰苍生：\n"
    "「肉身根基竟扎实至此……想不到在这荒僻之地，也能见到如此苗子。」\n"
    "「吾乃柳神，曾历大劫，蛰伏于此。汝既有此根基，可愿承吾之道统？」\n"
    "柳神指尖轻点，一缕生命精气没入你体内，修为暴涨（+10%）。\n"
    "剧情人物「柳神」关系已建立，好感度 +10。"
)

LIUSHEN_LINES = [
    ("你于柳树下静坐，柳神虚影再现：「极境非终点，大道在前方……」柳枝轻拂，道韵流转。", 5, 0.0),
    ("柳神声音缥缈：「上古年间，大劫起于界海，仙王喋血，天地崩裂……」你聆听秘辛，道心更坚。", 5, 0.0),
    ("柳神折下一截柳枝按在你眉心，生命精气灌体，伤势尽复，修为随之精进。", 3, 0.05),
    ("「莫要只学我的法，要学我为何而战。」柳神望向界海方向，久久不语。", 4, 0.0),
]

MENG_FIRST = (
    "【大长老巡关】落霞谷上空弓弦轻鸣，压得群山万壑一时无声。孟天正巡视归来，见你独自历练，"
    "出言指点了几处修行缺漏。\n剧情人物「孟天正」关系已建立，好感度 +10。"
)

MENG_LINES = [
    ("孟天正考校你的修行进境，指出三处真气运转的滞涩，你依言修正，只觉浑身通透。", 5),
    ("「守得住这一界，才谈得上守得住自己。」孟天正的话像一张拉满的弓。", 4),
    ("他抬手一箭射穿云层：「看清楚了，这一箭叫不退。」", 5),
]

GAI_FIRST = (
    "【九幽仙曲】幽冥渊深处传来一缕如泣如诉的仙音，沿途凶煞尽皆沉寂。"
    "一位病容老人立于星辉下，轻声提醒你前路杀机。\n剧情人物「盖九幽」关系已建立，好感度 +10。"
)

GAI_LINES = [
    ("你在幽冥渊再次听见九幽仙曲。盖九幽替你点破一处隐伏杀局。", 4),
    ("老人咳了两声，却笑着指向星空：「这天地病了，可总得有人替它撑着。」", 5),
    ("「我这身子撑不了多久了。你若走得远，替我看看仙路尽头是什么。」", 5),
]

ZHANG_FIRST = (
    "【荒古禁地·偶遇源天师后人】你在幽冥渊边缘发现一位须发皆白的老者正在勘测地势。"
    "老者手持罗盘，口中念念有词：「龙脉潜行，源气汇聚，此地必有大源！」\n"
    "他抬头打量你一番：「老夫张五，源天师一脉传人。观小友气运不凡，可愿听老夫一言？」\n"
    "张五爷赠你「源师转职凭证」：「持此凭证可前往源术世家转职为源师。」\n"
    "剧情人物「张五爷」关系已建立，好感度 +10。"
)

ZHANG_LINES = [
    ("张五爷蹲在地上划拉半天，忽然拍腿：「这底下有货！」你跟着挖出一枚源石。", 4),
    ("「源术不是赌运气，是读地脉。」张五爷把罗盘塞给你，让你自己走一遍。", 5),
    ("老人眯眼打量你：「你身上气运太盛，容易招劫。记住，财不露白。」", 4),
]

HEI_FIRST = (
    "太古战场深处忽然传来金属碰撞声，一条壮硕黑犬正蹲在残阵前研究道纹。"
    "它以阵纹替你封住退路上的虚空裂隙，却顺手收走几块边角料。\n"
    "「汪——这阵纹画得跟狗爬似的。」它嫌弃地刨了两爪，又回头瞥你一眼，"
    "「小子，看你根骨还行，要不要跟本皇学点真东西？」\n"
    "剧情人物「黑皇」关系已建立，好感度 +5。"
)

HEI_LINES = [
    ("黑皇趴在阵纹上打滚：「此阵叫作……叫作……反正很厉害就对了。」", 5),
    ("它叼走你一块灵石，含糊道：「学费。」然后真的教了你一手。", 6),
    ("「无始那老东西当年也没本皇聪明。」黑皇说这话时，尾巴翘得老高。", 5),
    ("黑皇对着虚空裂隙狂吠三声，裂隙居然真的合上了。", 6),
]

DUANDE_TEXT = (
    "一声惊天雷响，前方坟丘炸出焦黑大坑，一个灰头土脸的身影被天雷劈得骂骂咧咧——"
    "正是盗墓狂人段德！他怀里滚落一块奇石，恰好滚到你脚下。\n"
    "你顺手捡起【欺天石】×1。段德骂骂咧咧扒开焦土，头也不回地跑了。"
)

# ---------------------------------------------------------------- 黑皇阵法

FORMATIONS: list[dict[str, Any]] = [
    {
        "name": "聚灵道阵", "favor": 30, "cost": 5_000_000, "kind": "exp",
        "amount": 1000, "mats": {},
        "desc": "阵法师独享：立即获得 1000 点职业经验",
    },
    {
        "name": "欺天阵纹", "favor": 60, "cost": 15_000_000, "kind": "tribulation",
        "mats": {"混沌源石": 5, "欺天石": 1},
        "desc": "下一次帝兵雷劫：修为/血气消耗减半（欺天瞒机）",
    },
    {
        "name": "山河困龙阵", "favor": 100, "cost": 30_000_000, "kind": "seal",
        "charges": 1, "mats": {"五行神石": 1},
        "desc": "下一场秘境战斗：敌首回合被困，攻击 -15%、防御 -45%",
    },
    {
        "name": "位面传送阵", "favor": 160, "cost": 50_000_000, "kind": "escape",
        "charges": 1, "mats": {},
        "desc": "秘境战败时自动传送脱身：不损收益、气血全复（1 次）",
    },
    {
        "name": "无始杀阵", "favor": 240, "cost": 100_000_000, "kind": "kill",
        "charges": 5, "mats": {"五行神石": 3},
        "desc": "接下来 5 场秘境战斗：攻击 ×2、暴击 +20%",
    },
    {
        "name": "高级位面传送阵", "favor": 360, "cost": 300_000_000, "kind": "escape",
        "charges": 3, "mats": {},
        "desc": "同上，可自动脱身 3 次",
    },
]

FORMATION_MAP = {f["name"]: f for f in FORMATIONS}


# ---------------------------------------------------------------- 状态


def _ext(doc: Any) -> dict:
    ext = getattr(doc, "ext", None)
    return ext if isinstance(ext, dict) else doc if isinstance(doc, dict) else {}


def state_of(doc: Any) -> dict:
    """剧情状态（深拷贝）：chars 好感/事件 + 护道 + 阵纹。"""
    ext = _ext(doc)
    raw = ext.get("story") if isinstance(ext.get("story"), Mapping) else {}
    s = copy.deepcopy(dict(raw))
    chars = s.get("chars") if isinstance(s.get("chars"), dict) else {}
    for name in list(STORY) + ["段德", "苏灵", "狠人大帝"]:
        c = chars.get(name)
        if not isinstance(c, dict):
            continue
        c.setdefault("favor", 0)
        c.setdefault("met", False)
        c.setdefault("unlock_ts", 0.0)
        c.setdefault("events", [])
        c.setdefault("talk_day", "")
        c.setdefault("talk_count", 0)
        c.setdefault("engrave_day", "")
        c.setdefault("engrave_count", 0)
        c.setdefault("taught", False)
    s["chars"] = chars
    s.setdefault("protector", "")
    s.setdefault("protector_cd", 0.0)
    s.setdefault("protector_uses", 0)
    s.setdefault("arrays", [])
    s.setdefault("arrays_off", False)
    s.setdefault("trib_pending", False)
    return s


def save(doc: Any, s: dict) -> Any:
    """把状态写回玩家文档副本（调用方负责落库）。"""
    d = doc.model_copy(deep=True) if hasattr(doc, "model_copy") else copy.deepcopy(doc)
    d.ext["story"] = s
    return d


def _date_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _c(s: dict, name: str) -> dict:
    chars = s.setdefault("chars", {})
    c = chars.get(name)
    if not isinstance(c, dict):
        c = {"favor": 0, "met": False, "unlock_ts": 0.0, "events": [], "talk_day": "",
             "talk_count": 0, "engrave_day": "", "engrave_count": 0, "taught": False}
        chars[name] = c
    return c


def _event(c: dict, text: str) -> None:
    ev = c.setdefault("events", [])
    ev.append(text)
    if len(ev) > 12:
        del ev[0:len(ev) - 12]


# ---------------------------------------------------------------- 关系


def relation_of(name: str, favor: float) -> str:
    value = max(0, int(favor or 0))
    if name == "黑皇":
        for need, label in HEI_TIERS:
            if value >= need:
                return label
        return "初识"
    if name in ("狠人大帝", "苏灵"):
        from . import npc as _npc

        return _npc.relation_of(value, "suling" if name == "苏灵" else "ruthless")
    for need, label in GENERIC_TIERS:
        if value >= need:
            return label or TIER_480.get(name, "生死同命")
    return "初识"


def favor_of(doc: Any, name: str) -> int:
    if name in ("狠人大帝", "苏灵"):
        try:
            from . import npc as _npc

            n = _npc.state_of(doc)
            key = "ruthless" if name == "狠人大帝" else "suling"
            return int(n[key]["favor"])
        except Exception:
            return 0
    return int(_c(state_of(doc), name).get("favor", 0))


def is_unlocked(doc: Any, name: str) -> bool:
    if name in ALWAYS_OPEN:
        return True
    s = state_of(doc)
    c = s["chars"].get(name)
    return bool(c and c.get("met"))


# ---------------------------------------------------------------- 邂逅


def _unlock(s: dict, name: str, now: float, favor: int, event: str) -> dict:
    c = _c(s, name)
    c["met"] = True
    c["unlock_ts"] = float(now)
    c["favor"] = int(c.get("favor", 0) or 0) + int(favor)
    _event(c, event)
    return c


def meet(s: dict, place: str, floor: int, now: float, rng: random.Random) -> dict | None:
    """秘境寻宝后的剧情邂逅。返回 {name, first, gain, text, item, exp_pct} 或 None。

    首次：到达配置层数必遇（可发现性优先；原版为概率/条件触发，已在文档标注）。
    重复：每次 12% 概率遇到该地点已结缘的一位，好感 +3~6。
    段德：太古战场任意层 0.8%，只掉欺天石，不计好感。
    """
    place = str(place or "")

    # 1) 首次邂逅（必遇）
    for name in PLACE_CANDS.get(place, []):
        cfg = STORY.get(name) or {}
        if int(cfg.get("floor", 0)) != int(floor):
            continue
        c = s["chars"].get(name)
        if c and c.get("met"):
            continue
        gain = 5 if name == "黑皇" else 10
        _unlock(s, name, now, gain, f"{place}第{floor}层初遇")
        text = {"柳神": LIUSHEN_FIRST, "孟天正": MENG_FIRST, "盖九幽": GAI_FIRST,
                "张五爷": ZHANG_FIRST, "黑皇": HEI_FIRST}.get(name, "")
        out = {"name": name, "first": True, "gain": gain, "text": text}
        if name == "张五爷":
            out["item"] = "源师转职凭证"
        elif name == "柳神":
            out["exp_pct"] = 0.10
        return out

    # 2) 段德客串（太古战场）
    if place == "太古战场" and rng.random() < DUANDE_CHANCE:
        c = _c(s, "段德")
        first = not bool(c.get("met"))
        if first:
            c["met"] = True
            c["unlock_ts"] = float(now)
            _event(c, f"{place}遇盗墓贼段德")
        else:
            _event(c, f"{place}再遇段德")
        return {"name": "段德", "first": first, "gain": 0,
                "text": DUANDE_TEXT, "item": "欺天石"}

    # 3) 重复邂逅
    cands = [n for n in PLACE_CANDS.get(place, []) if (s["chars"].get(n) or {}).get("met")]
    if cands and rng.random() < REPEAT_CHANCE:
        name = rng.choice(cands)
        c = _c(s, name)
        if name == "柳神":
            line, gain, pct = rng.choice(LIUSHEN_LINES)
        elif name == "孟天正":
            line, gain = rng.choice(MENG_LINES)
            pct = 0.0
        elif name == "盖九幽":
            line, gain = rng.choice(GAI_LINES)
            pct = 0.0
        elif name == "张五爷":
            line, gain = rng.choice(ZHANG_LINES)
            pct = 0.0
        else:
            line, gain = rng.choice(HEI_LINES)
            pct = 0.0
        old_rel = relation_of(name, c.get("favor", 0))
        c["favor"] = int(c.get("favor", 0) or 0) + int(gain)
        new_rel = relation_of(name, c["favor"])
        _event(c, f"{place}再遇，好感+{gain}")
        text = line + f"\n好感度 +{gain}（{c['favor']}｜{new_rel}）"
        if new_rel != old_rel:
            text += f"\n✦ 关系提升为「{new_rel}」！"
        return {"name": name, "first": False, "gain": gain, "text": text, "exp_pct": pct}

    return None


# ---------------------------------------------------------------- 图鉴


def gallery_rows(doc: Any, roster: list[Mapping]) -> list[dict]:
    """按位面分组。roster 为 data/item/剧情人物列表.json。"""
    s = state_of(doc)
    groups: dict[str, list[dict]] = {}
    for entry in roster or []:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("名号") or "")
        if not name:
            continue
        unlocked = is_unlocked(doc, name)
        if name in ("狠人大帝", "苏灵"):
            favor = favor_of(doc, name)
            rel = relation_of(name, favor)
        else:
            c = s["chars"].get(name) or {}
            favor = int(c.get("favor", 0) or 0)
            rel = relation_of(name, favor)
        cfg = STORY.get(name) or {}
        hint = cfg.get("hint") or ("传说中人 · 暂无线索" if name in LEGEND_ONLY else "机缘未至")
        row = {
            "name": name,
            "identity": entry.get("身份") or "",
            "realm": entry.get("境界") or "",
            "plane": entry.get("位面") or "诸天",
            "desc": entry.get("人物描述") or "",
            "look": entry.get("容貌") or "",
            "portrait": entry.get("立绘") or "",
            "unlocked": unlocked,
            "favor": favor,
            "relation": rel,
            "hint": hint,
        }
        for plane in str(row["plane"]).split("/"):
            groups.setdefault(plane.strip() or "诸天", []).append(row)
    order = ["下界八域", "九天十地", "遮天位面", "任何位面"]
    out = [{"plane": p, "chars": groups[p]} for p in order if p in groups]
    for plane, chars in groups.items():
        if plane not in order:
            out.append({"plane": plane, "chars": chars})
    if roster:
        # 狠人大帝不在原版 JSON 图鉴里，但玩家剧情人物中有，补一节「隐世」
        favor = favor_of(doc, "狠人大帝")
        out.append({"plane": "诸天隐世（图鉴未载）", "chars": [{
            "name": "狠人大帝",
            "identity": "红尘仙",
            "realm": "红尘仙",
            "plane": "任何位面",
            "desc": "青铜鬼面，万古独行。为一人逆了整条时间长河。",
            "look": "青铜鬼面覆面，衣袍扫过星河。",
            "portrait": "",
            "unlocked": True,
            "favor": favor,
            "relation": relation_of("狠人大帝", favor),
            "hint": "",
        }]})
    return out


def gallery_text(doc: Any, roster: list[Mapping]) -> str:
    rows = gallery_rows(doc, roster)
    total = sum(len(g["chars"]) for g in rows)
    unlocked = sum(1 for g in rows for c in g["chars"] if c["unlocked"])
    lines = ["--- 剧情人物图鉴 ---", f"结缘 {unlocked}/{total}"]
    for g in rows:
        lines.append(f"【{g['plane']}】")
        for c in g["chars"]:
            if c["unlocked"]:
                lines.append(f"· {c['name']}（{c['identity']}）｜{c['relation']} · {c['favor']} 好感")
            else:
                lines.append(f"· {c['name']}（未结缘）｜线索：{c['hint']}")
    lines.append("※ 详情：#剧情人物 名字")
    return "\n".join(lines)


def detail_text(doc: Any, roster: list[Mapping], name: str) -> str:
    entry = None
    for e in roster or []:
        if isinstance(e, Mapping) and str(e.get("名号")) == name:
            entry = e
            break
    if entry is None and name not in ("狠人大帝",):
        names = [str(e.get("名号")) for e in roster or [] if isinstance(e, Mapping)]
        return f"图鉴里没有「{name}」。可查：{'、'.join(names)}"

    if name == "狠人大帝":
        from . import npc as _npc

        return _npc.panel(_npc.state_of(doc), time.time())

    if name == "苏灵" and entry:
        from . import npc as _npc

        n = _npc.state_of(doc)
        sv = n["suling"]
        favor = int(sv.get("favor", 0) or 0)
        lines = [
            "--- 苏灵 ---",
            f"身份：{entry.get('身份')}｜境界：{entry.get('境界')}｜位面：{entry.get('位面')}",
            f"容貌：{entry.get('容貌')}",
            f"生平：{entry.get('人物描述')}",
            "",
            f"好感：{favor}｜关系：{relation_of(name, favor)}",
            f"剧情：{_npc.beat_of(n)}",
            f"推演：{sv.get('teach_total', 0)}/{_npc.SULING_TOTAL_TEACH}"
            + ("（已领悟终极）" if sv.get("ultimate") else f"｜请教需 {_npc.SULING_DEEP_FAVOR} 好感、每日一次"),
            "指令：#苏灵交流｜#苏灵请教｜#请苏灵护道（480 好感）",
        ]
        return "\n".join(lines)

    unlocked = is_unlocked(doc, name)
    s = state_of(doc)
    c = s["chars"].get(name) or {}
    cfg = STORY.get(name) or {}
    lines = [f"--- {name} ---"]
    if entry:
        lines.append(f"身份：{entry.get('身份')}｜境界：{entry.get('境界')}｜位面：{entry.get('位面')}")
        lines.append(f"容貌：{entry.get('容貌')}")
        lines.append(f"生平：{entry.get('人物描述')}")
    lines.append("")
    if not unlocked:
        hint = cfg.get("hint") or ("传说中人 · 暂无线索" if name in LEGEND_ONLY else "机缘未至")
        lines.append(f"状态：未结缘｜线索：{hint}")
        return "\n".join(lines)
    favor = int(c.get("favor", 0) or 0)
    lines.append(f"好感：{favor}｜关系：{relation_of(name, favor)}")
    ev = c.get("events") or []
    if ev:
        lines.append("近事：" + "；".join(str(x) for x in ev[-4:]))
    if name == "黑皇":
        lines.append(f"阵道传承：{'已获' if c.get('taught') else f'需 {HEI_TEACH_FAVOR} 好感（#黑皇请教阵道）'}")
        lines.append("指令：#黑皇交流｜#黑皇阵法｜#请黑皇刻阵 阵法名｜#黑皇请教阵道")
    elif name in ("柳神", "苏灵", "狠人大帝"):
        lines.append("护道：480 好感可立护道之约（#请柳神护道 / #请苏灵护道 / #请狠人护道）")
        if name == "柳神":
            lines.append("机缘：深入青冥山，柳神会指点修行、赠柳枝淬体")
    elif name == "张五爷":
        lines.append("机缘：幽冥渊再遇可听源术讲解；已赠源师转职凭证（#转职 源师）")
    elif name in ("盖九幽", "孟天正"):
        lines.append(f"机缘：{cfg.get('place')}再遇，可得其指点")
    elif name == "段德":
        lines.append("机缘：太古战场随机出没，掉「欺天石」")
    elif name in LEGEND_ONLY:
        lines.append("机缘：原著气运所钟之人，行踪不定，暂无固定机缘")
    return "\n".join(lines)


# ---------------------------------------------------------------- 护道之约


def protector_of(s: dict) -> str:
    return str(s.get("protector") or "")


def protector_cd_left(s: dict, now: float) -> float:
    return max(0.0, float(s.get("protector_cd", 0) or 0) - float(now))


def assign_protector(doc: Any, s: dict, name: str) -> tuple[bool, str, dict]:
    if name not in ("柳神", "苏灵", "狠人大帝"):
        return False, "此人无意护道。可选：柳神 / 苏灵 / 狠人。", s
    favor = favor_of(doc, name)
    if favor < PROTECTOR_FAVOR:
        return False, (f"与{name}好感 {favor}/{PROTECTOR_FAVOR}，未至「生死同命」，"
                       f"护道之约无从谈起。"), s
    cur = protector_of(s)
    if cur == name:
        return False, f"「{name}」已是你的护道人。", s
    if cur:
        return False, f"你已有护道人「{cur}」，先发「#解除护道」。", s
    s["protector"] = name
    return True, (f"【护道之约】你与{name}立下护道之约。\n"
                  f"此后秘境濒死，{name}将跨越因果出手一次（24 小时一次）。\n"
                  f"查询：#我的护道人｜解除：#解除护道"), s


def clear_protector(s: dict) -> tuple[str, dict]:
    old = protector_of(s) or "无"
    s["protector"] = ""
    return old, s


def try_protect(s: dict, now: float) -> tuple[str, str] | None:
    """秘境战败瞬间调用。返回 (护道人, 文案) 或 None（不触发）。"""
    name = protector_of(s)
    if not name:
        return None
    if protector_cd_left(s, now) > 0:
        return None
    s["protector_cd"] = float(now) + PROTECTOR_CD
    s["protector_uses"] = int(s.get("protector_uses", 0) or 0) + 1
    if name == "苏灵":
        line = "命运轮盘转过一格，所有能够伤及你的未来同时被删去。苏灵自星辉中走出，挡在你身前。"
    elif name == "柳神":
        line = "一根翠绿柳枝贯穿虚空，三千神国在枝叶间明灭。柳神的法相挡在你身前。"
    else:
        line = "青铜面具自时间长河尽头浮现，万千仙葩同时绽放。狠人大帝一步落在你身前。"
    msg = (f"【护道之约·{name}】\n{line}\n"
           f"来敌攻势随因果一同消散，你被护送出险境，气血尽复。\n"
           f"（护道神念需休养 24 小时）")
    return name, msg


def protect_status(s: dict, now: float) -> str:
    name = protector_of(s)
    if not name:
        return "护道人：无（480 好感后可立约：#请柳神护道 / #请苏灵护道 / #请狠人护道）"
    left = protector_cd_left(s, now)
    if left > 0:
        hours = int(left // 3600)
        mins = int(left % 3600 // 60)
        return f"护道人：{name}｜休养中（{hours} 小时 {mins} 分）｜累计出手 {s.get('protector_uses', 0)} 次"
    return f"护道人：{name}｜可出手｜累计出手 {s.get('protector_uses', 0)} 次"


# ---------------------------------------------------------------- 黑皇阵道


def hei_talk(s: dict, now: float) -> tuple[bool, str, dict]:
    c = s["chars"].get("黑皇")
    if not c or not c.get("met"):
        return False, "你尚未遇见黑皇。深入秘境【太古战场】第 5 层，或有机缘。", s
    day = _date_key(now)
    if c.get("talk_day") != day:
        c["talk_day"] = day
        c["talk_count"] = 0
    if int(c.get("talk_count", 0)) >= HEI_TALK_LIMIT:
        return False, "黑皇已经不耐烦地趴下了。今日交流次数已用完（3/3）。", s
    gain = 5 + random.randrange(5)
    old = relation_of("黑皇", c.get("favor", 0))
    c["favor"] = int(c.get("favor", 0) or 0) + gain
    c["talk_count"] = int(c.get("talk_count", 0)) + 1
    new = relation_of("黑皇", c["favor"])
    _event(c, f"阵道交流，好感+{gain}")
    line = random.choice(HEI_LINES)[0]
    msg = f"{line}\n好感度 +{gain}（{c['favor']}｜{new}）"
    if new != old:
        msg += f"\n✦ 关系提升为「{new}」！"
    return True, msg, s


def hei_teach(s: dict) -> tuple[bool, str, dict]:
    c = s["chars"].get("黑皇")
    if not c or not c.get("met"):
        return False, "你尚未遇见黑皇。", s
    if c.get("taught"):
        return False, "黑皇已经把能教你的阵道都教了（可用 #黑皇阵法 查看）。", s
    if int(c.get("favor", 0)) < HEI_TEACH_FAVOR:
        return False, f"黑皇斜眼看你：「跟本皇才 {c.get('favor', 0)} 点交情，也想学阵？」（需 {HEI_TEACH_FAVOR} 好感）", s
    c["taught"] = True
    _event(c, "获黑皇阵道传承")
    return True, ("黑皇用爪子在地上划出一道完整阵纹：「看好了，只教一遍。」\n"
                  "✦ 你获得【黑皇阵道传承】，可发「#黑皇阵法」查看六阵，"
                  "以「#请黑皇刻阵 阵法名」请它出手。"), s


def _engrave_limit(s: dict) -> int:
    c = s["chars"].get("黑皇") or {}
    return max(1, {"初识": 1, "熟人": 2, "自己人": 3, "生死之交": 4, "帝阵传人": 5}.get(
        relation_of("黑皇", c.get("favor", 0)), 1))


def engrave_check(s: dict, name: str, now: float, stones: int) -> tuple[bool, str, dict | None]:
    c = s["chars"].get("黑皇")
    if not c or not c.get("met"):
        return False, "你尚未遇见黑皇。", None
    if not c.get("taught"):
        return False, "你尚未得黑皇阵道传承（#黑皇请教阵道，需 80 好感）。", None
    f = FORMATION_MAP.get(name)
    if not f:
        return False, f"黑皇不会「{name}」。可刻：{'、'.join(FORMATION_MAP)}", None
    if int(c.get("favor", 0)) < f["favor"]:
        return False, f"「{name}」需 {f['favor']} 好感（当前 {c.get('favor', 0)}）。", None
    day = _date_key(now)
    if c.get("engrave_day") != day:
        c["engrave_day"] = day
        c["engrave_count"] = 0
    limit = _engrave_limit(s)
    if int(c.get("engrave_count", 0)) >= limit:
        return False, f"黑皇今日已刻 {limit} 阵，累得直吐舌头。明日再来。", None
    if stones < int(f["cost"]):
        return False, f"刻「{name}」需 {int(f['cost']):,} 灵石（当前 {stones:,}）。", None
    return True, "", f


def apply_engrave(s: dict, name: str, now: float) -> tuple[dict, dict]:
    """扣好感次数并记阵。返回 (效果 dict, 更新后的状态)。"""
    f = FORMATION_MAP[name]
    c = s["chars"]["黑皇"]
    c["engrave_count"] = int(c.get("engrave_count", 0)) + 1
    _event(c, f"请黑皇刻下{name}")
    effect: dict[str, Any] = {"name": name, "kind": f["kind"], "cost": int(f["cost"])}
    if f["kind"] == "exp":
        effect["job_exp"] = int(f["amount"])
    elif f["kind"] == "tribulation":
        s["trib_pending"] = True
    else:
        arrays = s.setdefault("arrays", [])
        for a in arrays:
            if a.get("name") == name:
                a["left"] = int(a.get("left", 0)) + int(f["charges"])
                break
        else:
            arrays.append({"name": name, "left": int(f["charges"])})
    return effect, s


def arrays_text(s: dict) -> list[str]:
    names = {"山河困龙阵": "困龙", "无始杀阵": "杀阵", "位面传送阵": "传送",
             "高级位面传送阵": "高级传送"}
    out = []
    for a in s.get("arrays") or []:
        if int(a.get("left", 0)) > 0:
            out.append(f"{a['name']}×{a['left']}（{names.get(a['name'], '阵')}）")
    return out


def battle_mods(s: dict) -> tuple[dict, list[str]]:
    """秘境战斗前取阵法加成，并消耗次数。返回 (mods, 生效阵法名)。"""
    if s.get("arrays_off"):
        return {}, []
    mods: dict[str, Any] = {}
    used: list[str] = []
    for a in list(s.get("arrays") or []):
        if int(a.get("left", 0)) <= 0:
            continue
        if a.get("name") == "山河困龙阵":
            mods["enemy"] = {"atk": 0.85, "def": 0.55}
            mods["stun"] = True
            used.append(a["name"])
            a["left"] = int(a["left"]) - 1
        elif a.get("name") == "无始杀阵":
            mods["atk_mult"] = 2.0
            mods["bao_add"] = 0.2
            used.append(a["name"])
            a["left"] = int(a["left"]) - 1
    s["arrays"] = [a for a in (s.get("arrays") or []) if int(a.get("left", 0)) > 0]
    return mods, used


def consume_escape(s: dict) -> str | None:
    """秘境战败时消耗一张传送阵。返回阵名或 None。"""
    if s.get("arrays_off"):
        return None
    for a in s.get("arrays") or []:
        if a.get("name") in ("位面传送阵", "高级位面传送阵") and int(a.get("left", 0)) > 0:
            a["left"] = int(a["left"]) - 1
            s["arrays"] = [x for x in (s.get("arrays") or []) if int(x.get("left", 0)) > 0]
            return a["name"]
    return None


def consume_tribulation(s: dict) -> bool:
    if not s.get("trib_pending"):
        return False
    s["trib_pending"] = False
    return True


def formations_text(s: dict, stones: int) -> str:
    c = s["chars"].get("黑皇") or {}
    favor = int(c.get("favor", 0) or 0)
    lines = ["--- 黑皇阵法 ---"]
    lines.append(f"黑皇好感：{favor}｜{relation_of('黑皇', favor)}"
                 f"｜阵道传承：{'已获' if c.get('taught') else '未获'}")
    lines.append(f"今日刻阵：{c.get('engrave_count', 0)}/{_engrave_limit(s)}")
    for f in FORMATIONS:
        if favor >= f["favor"]:
            mark = "✅"
        else:
            mark = f"🔒{f['favor']}"
        mats = "、".join(f"{k}×{v}" for k, v in (f.get("mats") or {}).items())
        lines.append(f"{mark} {f['name']}｜{int(f['cost']):,} 灵石"
                     + (f"＋{mats}" if mats else ""))
        lines.append(f"    {f['desc']}")
    cur = arrays_text(s)
    lines.append("在身阵纹：" + ("、".join(cur) if cur else "无"))
    if s.get("trib_pending"):
        lines.append("待渡劫：欺天阵纹已布下")
    if s.get("arrays_off"):
        lines.append("※ 阵法已停用（#启用阵法 恢复）")
    lines.append("指令：#请黑皇刻阵 阵法名｜#停用阵法 / #启用阵法")
    return "\n".join(lines)


def hei_panel(s: dict) -> str:
    c = s["chars"].get("黑皇")
    if not c or not c.get("met"):
        return ("--- 剧情人物·黑皇 ---\n"
                "你尚未遇见黑皇。\n线索：深入秘境【太古战场】第 5 层。\n"
                "（原版为位面副本 3% 概率，本插件改为固定层首遇）")
    favor = int(c.get("favor", 0) or 0)
    lines = [
        "--- 剧情人物·黑皇 ---",
        f"关系：{relation_of('黑皇', favor)}（{favor} 好感）",
        f"阵道传承：{'已获' if c.get('taught') else f'需 {HEI_TEACH_FAVOR} 好感（#黑皇请教阵道）'}",
        f"今日交流：{c.get('talk_count', 0)}/{HEI_TALK_LIMIT}｜今日刻阵：{c.get('engrave_count', 0)}/{_engrave_limit(s)}",
        "在身阵纹：" + ("、".join(arrays_text(s)) or "无"),
        "指令：#黑皇交流｜#黑皇阵法｜#请黑皇刻阵 阵法名",
    ]
    return "\n".join(lines)
