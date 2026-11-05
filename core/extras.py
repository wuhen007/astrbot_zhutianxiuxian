"""补齐 help.json 中「有指令、无玩法」的条目（W6-3）。

shortcut: 图鉴类只读现有数据表，无表则明确说明未收录；天骄/副本为最小可用实现
（复用 battle.spar 与现有副本表，未复刻原版完整掉落链与 aeon 引擎）；
时代轮转、皮肤、跨服仍不做，相关条目从 help.json 移除。
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Mapping

from .battle import Unit, spar
from .player import PlayerDoc

# 帮助页 → _help_groups() 分组关键词
HELP_TOPICS: dict[str, tuple[str, ...]] = {
    "#基础帮助": ("基础修炼", "修行之路", "每天日常"),
    "#修仙扩展": ("气运之子", "仙人之资", "遨游万界"),
    "#修仙管理": ("管理",),
    "#宗门管理": ("宗门",),
    "#师徒帮助": ("师徒", "道侣"),
    "#小世界帮助": ("小世界", "灵园"),
    "#职业帮助": ("职业", "炼丹", "锻造"),
    "#诸天帮助": ("诸天", "位面", "裂界"),
    "#活动帮助": ("活动", "灾", "Boss", "劫境"),
    "#三周目帮助": ("三周目", "轮回"),
    "#无尽轮回帮助": ("无尽", "轮回"),
    "#灵根帮助": ("灵根", "命格"),
}

CATALOG_TABLES: dict[str, str] = {
    "#命格图鉴": "item/命格词条",
    "#合成图鉴": "item/合成列表",
    "#位面天骄图鉴": "item/位面天骄",
    "#兑换码图鉴": "item/兑换码",
    "#成就图鉴": "item/成就列表",
}

DUNGEON_TABLES: dict[str, str] = {
    "仙府": "Timelimit/限定仙府",
    "禁地": "item/副本/禁地列表",
    "仙境": "item/副本/仙境列表",
    "下界八域": "item/副本/下界八域列表",
    "九天十地": "item/副本/九天十地",
}

TIANJIAO: list[dict] = [
    {"name": "青冥剑子", "realm": 12, "atk": 60_000, "defense": 45_000, "hp": 500_000, "reward": 20_000},
    {"name": "太虚神女", "realm": 20, "atk": 180_000, "defense": 130_000, "hp": 1_600_000, "reward": 80_000},
    {"name": "九幽魔子", "realm": 28, "atk": 520_000, "defense": 380_000, "hp": 5_000_000, "reward": 250_000},
    {"name": "仙古遗种", "realm": 36, "atk": 1_400_000, "defense": 1_000_000, "hp": 14_000_000, "reward": 700_000},
    {"name": "无上天骄", "realm": 44, "atk": 4_000_000, "defense": 3_000_000, "hp": 40_000_000, "reward": 2_000_000},
]

CHANGELOG = [
    "W6-1：幸运/一键突破、天道赐福、每日抽奖、灵市社交、独立法身",
    "W6-2：道法仙术订阅、灵市双榜、法身时间长河/界海/圣墟/镇守",
    "W6-3：补齐帮助页、图鉴、境界查询、天骄与副本查询",
]


def _rows(content: Callable[[str], Any], path: str) -> list[dict]:
    data = content(path) or []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def help_topic(cmd: str, groups: list[dict]) -> str:
    keys = HELP_TOPICS.get(cmd, ())
    picked = [g for g in groups if any(k in str(g.get("title", "")) for k in keys)]
    if not picked:
        picked = groups[:3]
    lines = [f"--- {cmd} ---"]
    for g in picked:
        lines.append(f"[{g.get('title')}]")
        for row in g.get("lines", [])[:20]:
            if isinstance(row, (tuple, list)) and len(row) >= 2:
                lines.append(f"· {row[0]} → {row[1]}")
    return "\n".join(lines)


def catalog(cmd: str, content: Callable[[str], Any]) -> str:
    path = CATALOG_TABLES.get(cmd, "")
    rows = _rows(content, path)
    lines = [f"--- {cmd} ---"]
    if not rows:
        lines.append("本移植未收录该图鉴数据（原版表未搬运）。")
        lines.append("已开放的相关指令：#我的命格、#我的纳戒、#图鉴楼 类目 页码。")
        return "\n".join(lines)
    lines.append(f"共 {len(rows)} 条：")
    for r in rows[:20]:
        name = r.get("name") or r.get("名称") or r.get("level") or "?"
        desc = str(r.get("desc") or r.get("描述") or r.get("效果") or "")[:40]
        lines.append(f"· {name}" + (f"｜{desc}" if desc else ""))
    if len(rows) > 20:
        lines.append(f"…（余 {len(rows) - 20} 条，用 #图鉴楼 类目 页码 翻页）")
    return "\n".join(lines)


def realm_list(doc: PlayerDoc, content: Callable[[str], Any], body: bool = False) -> str:
    path = "Level/炼体境界" if body else doc.realm_table
    rows = _rows(content, path)
    idx = int(doc.physique_index) if body else int(doc.realm_index)
    lines = [f"--- {'炼体' if body else '练气'}境界（共 {len(rows)} 境）---",
             f"当前：第 {idx + 1} 境【{rows[idx]['level'] if idx < len(rows) else '未知'}】"]
    for i, r in enumerate(rows):
        mark = " ★" if i == idx else ""
        if abs(i - idx) <= 2 or i % 10 == 0:
            lines.append(f"{i + 1:2d}. {r.get('level', '?')}{mark}")
    return "\n".join(lines)


def my_realm(doc: PlayerDoc, content: Callable[[str], Any]) -> str:
    rows = _rows(content, doc.realm_table)
    cur = rows[min(int(doc.realm_index), len(rows) - 1)] if rows else {}
    nxt = rows[int(doc.realm_index) + 1] if int(doc.realm_index) + 1 < len(rows) else None
    lines = ["--- 我的练气 ---",
             f"境界：{cur.get('level', '?')}（第 {int(doc.realm_index) + 1} 境）",
             f"修为：{int(doc.exp):,}" + (f" / 下境需 {int(cur.get('exp', 0)):,}" if nxt else ""),
             f"基础三维：攻 {cur.get('基础攻击', 0):,}｜防 {cur.get('基础防御', 0):,}"
             f"｜血 {cur.get('基础血量', 0):,}"]
    if nxt:
        lines.append(f"下境：{nxt.get('level')}（#突破）")
    return "\n".join(lines)


def assistant(doc: PlayerDoc) -> str:
    r = max(int(doc.realm_index), int(doc.physique_index))
    if r < 5:
        plan = ["#修仙签到 领修为与秘境之匙", "#获取每日任务 并做完三任务", "#突破 / #炼体突破 推境界"]
    elif r < 16:
        plan = ["#降临秘境 青冥山 → #寻宝 → #逃离", "#创建宗门（第 6 境 + 1 万灵石）",
                "#切磋 刷功法感悟 → #分配功法感悟", "#装备 / #强化 / #镶嵌 拉战力"]
    elif r < 31:
        plan = ["#位面 / #穿梭 开图，#探索位面线索 每日一次", "#进入裂界（6 小时窗口）",
                "#讨伐域外灾厄（管理员先召唤）", "#开启无尽劫境（第 15 境 + 20 万灵石）"]
    elif r < 41:
        plan = ["攒修为 2000 万、气血 90%+ 备 #渡劫", "#改命 洗「渡劫修为减少」命格", "#法身/时间长河 前置准备"]
    else:
        plan = ["#登仙（渡劫成功后）", "#凝聚无上法身 → #法身穿梭 / 分支玩法",
                "#遨游时间长河（30 分 CD）", "#法身镇守永恒未知之地 攒纪元"]
    return "\n".join(["--- 修仙助手 ---", f"当前双轨境界 {r}（第 {r + 1} 境），建议顺序："]
                     + [f"{i}. {x}" for i, x in enumerate(plan, 1)])


def break_trib_cd(doc: PlayerDoc, now: float) -> tuple[str, bool]:
    """#打散雷劫：消耗 5000 灵石清除元神劫失败 CD（原版为速通双劫）。"""
    ts = float(doc.ext.get("spirit_fail_ts", 0) or 0)
    if not ts or now - ts >= 30 * 60:
        return "当前没有需要打散的雷劫（渡劫失败后 30 分钟内可用）。", False
    cost = 5_000
    if int(doc.stones) < cost:
        return f"打散雷劫需 {cost:,} 灵石，当前 {int(doc.stones):,}。", False
    doc.stones -= cost
    doc.ext.pop("spirit_fail_ts", None)
    return f"雷劫已打散，渡劫冷却清除（花费 {cost:,} 灵石）。可立即再发 #渡劫。", True


def tianjiao_list(doc: PlayerDoc) -> str:
    done = set(doc.ext.get("tianjiao_defeated") or [])
    lines = ["--- 位面天骄 ---"]
    for i, t in enumerate(TIANJIAO, 1):
        lines.append(f"{i}. {t['name']}（第 {t['realm'] + 1} 境）"
                     f"{' ✅已讨伐' if t['name'] in done else ''}｜赏 {t['reward']:,}")
    lines.append("指令：#天骄状态 姓名｜#讨伐天骄 姓名")
    return "\n".join(lines)


def tianjiao_status(doc: PlayerDoc, name: str) -> str:
    t = next((x for x in TIANJIAO if x["name"] == (name or "").strip()), None)
    if not t:
        return f"没有「{name}」这位天骄。#天骄列表 查看。"
    done = set(doc.ext.get("tianjiao_defeated") or [])
    return (f"--- {t['name']} ---\n境界：第 {t['realm'] + 1} 境｜"
            f"攻 {t['atk']:,}｜防 {t['defense']:,}｜血 {t['hp']:,}\n"
            f"状态：{'已讨伐' if t['name'] in done else '未讨伐'}｜赏金 {t['reward']:,}")


def tianjiao_fight(doc: PlayerDoc, name: str, stats: Any, rng: random.Random) -> tuple[str, bool, dict]:
    t = next((x for x in TIANJIAO if x["name"] == (name or "").strip()), None)
    if not t:
        return f"没有「{name}」这位天骄。#天骄列表 查看。", False, {}
    done = set(doc.ext.get("tianjiao_defeated") or [])
    if t["name"] in done:
        return f"【{t['name']}】已讨伐过。", False, {}
    me = Unit(doc.name or "道友", int(stats.atk), int(stats.defense), int(stats.hp), float(stats.bao))
    foe = Unit(t["name"], t["atk"], t["defense"], t["hp"], 0.05)
    winner, log = spar(me, foe, rng)
    if winner == 0:
        doc.stones += t["reward"]
        doc.exp += t["reward"] * 10
        done.add(t["name"])
        doc.ext["tianjiao_defeated"] = sorted(done)
        return (f"讨伐【{t['name']}】成功！灵石 +{t['reward']:,}、修为 +{t['reward'] * 10:,}。\n"
                + "\n".join(str(x) for x in log[:4])), True, {}
    return (f"讨伐【{t['name']}】失利，无战损，可再战。\n"
            + "\n".join(str(x) for x in log[:4])), False, {}


def dungeon_list(kind: str, content: Callable[[str], Any]) -> str:
    rows = _rows(content, DUNGEON_TABLES[kind])
    lines = [f"--- {kind}（{len(rows)} 处）---"]
    for r in rows:
        lines.append(f"· {r.get('name', '?')}｜价 {int(r.get('Price', 0) or 0):,}"
                     f"｜极品 {','.join(r.get('Best') or []) or '—'}")
    lines.append("掉落查询：#副本掉落 地点名；进入探索：#降临秘境 名字（本移植 4 处秘境）")
    return "\n".join(lines)


def dungeon_drop(place: str, content: Callable[[str], Any], doc: PlayerDoc | None = None) -> str:
    place = (place or "").strip()
    for kind, path in DUNGEON_TABLES.items():
        for r in _rows(content, path):
            if r.get("name") == place:
                lines = [f"--- {place}（{kind}）掉落 ---"]
                for tier in ("one", "two", "three"):
                    items = r.get(tier) or []
                    names = [str(x.get("name", "?")) for x in items if isinstance(x, dict)]
                    lines.append(f"· {tier}：{'、'.join(names[:6]) or '—'}")
                lines.append(f"极品：{'、'.join(r.get('Best') or []) or '—'}")
                if doc is not None:
                    doc.ext["last_dungeon"] = place
                return "\n".join(lines)
    return f"没有「{place}」的掉落记录。#禁地 / #仙境 / #下界八域 / #九天十地 看地点列表。"


def guard_xianjing(doc: PlayerDoc, now: float) -> tuple[str, bool]:
    """#镇守仙境：懒结算，每满 1 小时给修为/血气。"""
    g = doc.ext.get("xianjing_guard")
    if not isinstance(g, dict):
        doc.ext["xianjing_guard"] = {"start": now, "last": now, "total": 0}
        return "开始镇守仙境，每满 1 小时结算一次修为/血气（再次发送本指令即可领取）。", True
    hours = int((now - float(g.get("last", now))) // 3600)
    if hours < 1:
        return (f"镇守中（累计 {int(g.get('total', 0)):,} 修为）。"
                f"距下次结算 {60 - int((now - float(g['last'])) // 60 % 60)} 分钟。"), False
    g["last"] = float(g["last"]) + hours * 3600
    gain = hours * 200_000 * (max(int(doc.realm_index), 1) + 1)
    g["total"] = int(g.get("total", 0)) + gain
    doc.exp += gain
    doc.ext["xueqi"] = int(doc.ext.get("xueqi", 0) or 0) + gain
    return f"镇守结算：{hours} 小时，修为 +{gain:,}、血气 +{gain:,}（累计 {g['total']:,}）。", True


def sacrifice(doc: PlayerDoc) -> tuple[str, bool]:
    """#献祭魂与血：消耗 30% 灵石回复气血（原版为战败 10 分钟内队友献祭）。"""
    cost = int(int(doc.stones) * 0.3)
    if cost < 1:
        return "灵石不足，无法献祭。", False
    doc.stones -= cost
    doc.ext["hp"] = int(doc.ext.get("hp_max") or doc.ext.get("base_hp") or 100_000)
    return f"献祭魂与血：灵石 -{cost:,}，气血回满。", True


def dispatch(cmd: str, doc: PlayerDoc, arg: str, content: Callable[[str], Any],
             groups: list[dict], stats: Any, rng: random.Random,
             now: float) -> tuple[str, bool, dict]:
    """统一入口：返回 (文案, 是否改了档案, 额外物品)。"""
    changed, items = False, {}
    if cmd in HELP_TOPICS:
        text = help_topic(cmd, groups)
    elif cmd in CATALOG_TABLES:
        text = catalog(cmd, content)
    elif cmd in ("#练气境界", "#炼体境界"):
        text = realm_list(doc, content, body=cmd == "#炼体境界")
    elif cmd == "#我的练气":
        text = my_realm(doc, content)
    elif cmd == "#查看时代":
        text = "--- 当前时代 ---\n天命时代（本移植未实现时代轮转，时代系数恒为 1.0 / 成功率加成 0）。"
    elif cmd == "#修仙助手":
        text = assistant(doc)
    elif cmd == "#打散雷劫":
        text, changed = break_trib_cd(doc, now)
    elif cmd == "#灵市帮助":
        text = ("--- 灵市帮助 ---\n#灵市 行情｜#买入 名称*张数｜#卖出 名称*-1｜"
                "#我的灵票｜#灵票走势 名称｜#灵市人物｜#打听｜#灵市查账｜#灵市追问｜"
                "#灵市消息｜#借款｜#还款 数量｜#灵市债务｜#灵市排行榜｜#灵市收益榜")
    elif cmd == "#天骄列表":
        text = tianjiao_list(doc)
    elif cmd == "#天骄状态":
        text = tianjiao_status(doc, arg)
    elif cmd == "#讨伐天骄":
        text, changed, items = tianjiao_fight(doc, arg, stats, rng)
    elif cmd in ("#禁地", "#仙境", "#下界八域", "#九天十地"):
        text = dungeon_list(cmd[1:], content)
    elif cmd == "#探索仙府":
        text = dungeon_list("仙府", content) if not (arg or "").strip() else \
            dungeon_drop(arg, content, doc)
        changed = bool((arg or "").strip())
    elif cmd == "#副本掉落":
        text = dungeon_drop(arg, content, doc)
        changed = True
    elif cmd == "#去":
        last = str(doc.ext.get("last_dungeon") or "")
        text = dungeon_drop(last, content) if last else "还没有副本记录，先 #副本掉落 地点名 或 #降临秘境。"
    elif cmd == "#镇守仙境":
        text, changed = guard_xianjing(doc, now)
    elif cmd == "#献祭魂与血":
        text, changed = sacrifice(doc)
    elif cmd == "#更新公告" or cmd == "#公告网页":
        text = "--- 更新公告 ---\n" + "\n".join(f"· {x}" for x in CHANGELOG)
    elif cmd == "#查看日志":
        text = "--- 更新日志 ---\n" + "\n".join(f"· {x}" for x in CHANGELOG)
    elif cmd == "#传音给作者":
        msg = (arg or "").strip()
        if not msg:
            text = "格式：#传音给作者 内容"
        else:
            doc.ext["author_msg"] = msg[-200:]
            text = "留言已记录（存于你的存档 ext.author_msg），作者查看档案可见。"
            changed = True
    elif cmd in ("#位面天骄图鉴",):
        text = catalog(cmd, content)
    else:
        text = f"「{cmd}」本移植暂未提供（详见 #帮助）。"
    return text, changed, items
