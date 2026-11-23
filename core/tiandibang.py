"""W8-F8 天地榜：原版 `apps/Tiandibang/Tiandibang.js`（8 rule / 860 行）移植。

原版把整张榜存成 `resources/data/tiandibang/tiandibang.json`（数组，报名时快照三维），
每周一 0 点 cron 结算前三名并把全榜积分清零；天地堂是 `item/商店/天地堂.json` 的
13 件商品，仅周日开放兑换。本移植不落独立文件，状态挂
`calamity_state["tiandibang"]` 单例，**db 恒 v17**。

折算说明见 `rules_text()`；两处指令撞名（原版「#比试」「#天地榜」已被本移植占用）
在 main.py 改名为「#天地榜比试」「#天地榜积分」。
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Iterable, Mapping

TZ = _dt.timezone(_dt.timedelta(hours=8))

FREE_CHANCES = 3          # 原版每日免费三次
HIGH_REALM = 41           # 原版 `境界 > 41` 的高阶档不参与越级筛选
TOP_N = 10
BEAST_NAME = "灵修兽"
TICKET_NAME = "摘榜令"     # 次数耗尽时自动消耗，换 1 次
BOX_NAME = "超越宝盒"      # 周奖励

# model/tiandibang.js: TIANDIBANG_REWARDS（1:1）
REWARDS: list[dict[str, int]] = [
    {"position": 1, "stones": 17_500_000, "box": 5},
    {"position": 2, "stones": 13_000_000, "box": 3},
    {"position": 3, "stones": 9_200_000, "box": 1},
]

# 原版 pk()：胜/负/平 × 真人榜战/灵修兽，积分增量与灵石倍率（灵石 = 结算后积分 × 倍率）
SCORE_GAIN = {
    "win": {"player": 2000, "beast": 1500},
    "lose": {"player": 1000, "beast": 800},
    "draw": {"player": 500, "beast": 500},
}
STONE_MULT = {
    "win": {"player": 4, "beast": 8},
    "lose": {"player": 2, "beast": 6},
    "draw": {"player": 0, "beast": 0},
}


# ---------------------------------------------------------------- 时间键

def _date(ts: float) -> _dt.date:
    return _dt.datetime.fromtimestamp(float(ts), TZ).date()


def day_key(ts: float) -> str:
    """自然日（UTC+8），用于每日次数重置。"""
    return _date(ts).isoformat()


def week_key(ts: float) -> str:
    """所在自然周的周一日期，与原版 getTiandibangWeekKey 一致。"""
    d = _date(ts)
    return (d - _dt.timedelta(days=d.weekday())).isoformat()


def settlement_key(ts: float) -> str:
    """周一 0 点结算的是「上一周」，与原版 getTiandibangSettlementKey 一致。"""
    return week_key(float(ts) - 7 * 86400)


def is_sunday(ts: float) -> bool:
    return _date(ts).weekday() == 6


# ---------------------------------------------------------------- 状态

def state_of(cal: dict, now: float | None = None) -> dict:
    s = cal.get("tiandibang")
    if not isinstance(s, dict):
        s = {}
    if not isinstance(s.get("entries"), list):
        s["entries"] = []
    if not isinstance(s.get("weeks"), dict):
        s["weeks"] = {}
    if not s.get("opened_week"):
        s["opened_week"] = week_key(time.time() if now is None else now)
    return s


def commit(cal: dict, s: dict) -> None:
    cal["tiandibang"] = s


def _norm(e: dict) -> dict:
    e.setdefault("uid", "")
    e.setdefault("name", "无名修士")
    e.setdefault("realm", 0)
    e.setdefault("atk", 1)
    e.setdefault("defense", 1)
    e.setdefault("hp", 1)
    e.setdefault("bao", 0.0)
    e.setdefault("score", 0)
    e.setdefault("chances", FREE_CHANCES)
    e.setdefault("day", "")
    e.setdefault("earned", 0)
    return e


def normalize(s: dict) -> dict:
    s["entries"] = [_norm(e) if isinstance(e, dict) else _norm({}) for e in s["entries"]]
    return s


def find(s: dict, uid: str) -> int:
    for i, e in enumerate(s["entries"]):
        if str(e.get("uid")) == str(uid):
            return i
    return -1


def new_entry(uid: str, name: str, realm: int, stats: Mapping[str, Any], now: float) -> dict:
    """报名时冻结三维快照（原版 cansai 写 Read_player 的攻击/防御/血量上限）。"""
    return _norm({
        "uid": str(uid),
        "name": str(name or "无名修士"),
        "realm": int(realm),
        "atk": max(1, int(stats.get("atk", 1))),
        "defense": max(1, int(stats.get("defense", 1))),
        "hp": max(1, int(stats.get("hp", 1))),
        "bao": float(stats.get("bao", 0.0)),
        "score": 0,
        "chances": 0,          # 原版报名写 `次数: 0`，须等首次挑战跨日刷新为 3
        "day": "",
        "earned": 0,
        "joined_at": float(now),
    })


def join(s: dict, uid: str, name: str, realm: int,
         stats: Mapping[str, Any], now: float) -> tuple[bool, str]:
    if find(s, uid) >= 0:
        return False, "你已报名天地榜，无需重复参赛。"
    s["entries"].append(new_entry(uid, name, realm, stats, now))
    return True, f"参赛成功！{name} 已入天地榜，快照三维 " \
                 f"{int(stats.get('atk', 1)):,}/{int(stats.get('defense', 1)):,}/{int(stats.get('hp', 1)):,}。" \
                 "可发「#天地榜比试」挑战前一名。"


def sync(s: dict, uid: str, name: str, realm: int,
         stats: Mapping[str, Any]) -> tuple[bool, str, dict | None]:
    """原版「#更新属性」：把实时三维刷回榜单档案（积分与次数不动）。"""
    i = find(s, uid)
    if i < 0:
        return False, "请先发「#报名比赛」入榜。", None
    e = _norm(s["entries"][i])
    e.update({
        "name": str(name or e["name"]),
        "realm": int(realm),
        "atk": max(1, int(stats.get("atk", 1))),
        "defense": max(1, int(stats.get("defense", 1))),
        "hp": max(1, int(stats.get("hp", 1))),
        "bao": float(stats.get("bao", 0.0)),
    })
    return True, f"属性已更新：攻击 {e['atk']:,}｜防御 {e['defense']:,}｜血量 {e['hp']:,}" \
                 f"｜暴击 {int(e['bao'] * 100)}%｜积分 {e['score']:,}", e


def refresh_daily(s: dict, idx: int, now: float) -> bool:
    """跨自然日把次数补满 3（原版 pk 里比对 lastbisai_time 的 Y/M/D）。"""
    e = _norm(s["entries"][idx])
    d = day_key(now)
    if e["day"] == d:
        return False
    e["day"] = d
    e["chances"] = FREE_CHANCES
    return True


# ---------------------------------------------------------------- 挑战

def opponent(s: dict, idx: int) -> tuple[str, int, float]:
    """返回 (kind, 对手下标, 挑战者三维补偿倍率)。

    原版从自己前一名往前找第一个「境界 ≤41」的选手；若自己 >41 则直接取前一名。
    找不到就打「灵修兽」。对手攻击高出越多，挑战者三维补偿越高（2 / 1.6 / 1.3）。
    """
    es = s["entries"]
    me = _norm(es[idx])
    k = -1
    for j in range(idx - 1, -1, -1):
        foe = _norm(es[j])
        if int(me["realm"]) > HIGH_REALM or int(foe["realm"]) <= HIGH_REALM:
            k = j
            break
    if k < 0:
        return "beast", -1, 1.0
    foe = _norm(es[k])
    ratio = float(foe["atk"]) / max(1, int(me["atk"]))
    boost = 2.0 if ratio > 2 else 1.6 if ratio > 1.6 else 1.3 if ratio > 1.3 else 1.0
    return "player", k, boost


def mirror(me: Mapping[str, Any], rng: Any) -> dict:
    """灵修兽：以挑战者快照为底，三维各乘 0.8~1.2（原版 0.8 + 0.4*Math.random()）。"""
    return {
        "atk": max(1, int(int(me["atk"]) * (0.8 + 0.4 * rng.random()))),
        "defense": max(1, int(int(me["defense"]) * (0.8 + 0.4 * rng.random()))),
        "hp": max(1, int(int(me["hp"]) * (0.8 + 0.4 * rng.random()))),
        "bao": float(me.get("bao", 0.0)),
    }


def boost_unit(me: Mapping[str, Any], boost: float) -> dict:
    return {
        "atk": max(1, int(int(me["atk"]) * boost)),
        "defense": max(1, int(int(me["defense"]) * boost)),
        "hp": max(1, int(int(me["hp"]) * boost)),
        "bao": float(me.get("bao", 0.0)),
    }


def duel(s: dict, uid: str, outcome: str, kind: str, foe_name: str,
         now: float) -> tuple[bool, str, int]:
    """结算一场挑战。返回 (ok, msg, 灵石增量)；winner 由 main 用 battle.spar 先行判定。"""
    i = find(s, uid)
    if i < 0:
        return False, "请先发「#报名比赛」入榜。", 0
    if outcome not in SCORE_GAIN or kind not in ("player", "beast"):
        return False, "战果异常，未计分。", 0
    refresh_daily(s, i, now)
    e = _norm(s["entries"][i])
    if int(e["chances"]) < 1:
        return False, "今日挑战次数已用光，明日再来（或用「#天地堂」兑「摘榜令」）。", 0
    gain = SCORE_GAIN[outcome][kind]
    e["chances"] -= 1
    e["score"] = int(e["score"]) + gain
    stones = int(e["score"]) * STONE_MULT[outcome][kind]
    e["earned"] = int(e["earned"]) + stones
    s["entries"].sort(key=lambda x: -int(x.get("score", 0)))
    verb = {"win": "击败", "lose": "不敌", "draw": "战平"}[outcome]
    msg = (f"{e['name']}{verb}了「{foe_name}」，积分 +{gain:,} → {e['score']:,}，"
           f"获得灵石 {stones:,}。今日剩余 {e['chances']} 次。")
    return True, msg, stones


def need_ticket(e: Mapping[str, Any]) -> bool:
    return int(e.get("chances", 0)) < 1


def use_ticket(s: dict, uid: str, now: float) -> tuple[bool, str]:
    """背包里有摘榜令时兑换 1 次额外挑战（扣道具由 main 事务完成）。"""
    i = find(s, uid)
    if i < 0:
        return False, "请先发「#报名比赛」入榜。"
    refresh_daily(s, i, now)
    e = _norm(s["entries"][i])
    if int(e["chances"]) > 0:
        return False, "今日尚有挑战次数，无需动用「摘榜令」。"
    e["chances"] = 1
    return True, f"【天机榜·追加】消耗一枚「{TICKET_NAME}」，今日追加 1 次挑战。"


# ---------------------------------------------------------------- 周结算

def winners(s: dict) -> list[dict]:
    """model/tiandibang.js: getTiandibangWinners —— 只奖励积分 > 0 的前三。"""
    rows = [e for e in s["entries"] if int(e.get("score", 0)) > 0]
    rows.sort(key=lambda e: -int(e.get("score", 0)))
    return rows[:len(REWARDS)]


def maybe_settle(s: dict, now: float, force: bool = False) -> tuple[str, list[dict], bool]:
    """惰性周结算（原版 cron `saiji` 每周一 0 点 + 超管「#结算天地榜奖励」）。

    返回 (公告, 发奖 ops, 是否改档)。启用当周不补发上一周，避免插件一上线就清榜。
    """
    cur, key = week_key(now), settlement_key(now)
    if not force and s.get("opened_week") == cur:
        return f"天地榜 {cur} 赛季进行中，周一 0 点结算上一周榜单。", [], False
    done = s["weeks"].get(key)
    if isinstance(done, dict) and done.get("status") == "completed":
        return f"天地榜 {key} 周奖励已结算，无需重复发放。", [], False
    top = winners(s)
    ops: list[dict] = []
    lines = [f"【天地榜每周结算】{key}"]
    for i, e in enumerate(top):
        r = REWARDS[i]
        ops.append({
            "uid": str(e["uid"]), "name": str(e["name"]), "score": int(e["score"]),
            "position": r["position"], "stones": r["stones"], "box": r["box"],
        })
        lines.append(f"第 {r['position']} 名 {e['name']}｜积分 {int(e['score']):,}"
                     f"｜灵石 {r['stones']:,} + 「{BOX_NAME}」×{r['box']}")
    if not top:
        lines.append("本周无正积分玩家，不发放排名奖励。")
    for e in s["entries"]:
        e["score"] = 0
        e["chances"] = FREE_CHANCES
    lines.append("积分已清零，全员挑战次数恢复 3 次。")
    s["weeks"][key] = {
        "status": "completed", "week": key,
        "top": [{"uid": o["uid"], "name": o["name"], "score": o["score"]} for o in ops],
        "rewards": [dict(r) for r in REWARDS[:len(ops)]],
    }
    return "\n".join(lines), ops, True


def reset(s: dict) -> str:
    """超管「#清空积分」：只清积分与次数，不动周结算记录。"""
    for e in s["entries"]:
        e["score"] = 0
        e["chances"] = FREE_CHANCES
    return f"积分已重置！{len(s['entries'])} 名参赛者挑战次数全部恢复 {FREE_CHANCES} 次。"


# ---------------------------------------------------------------- 天地堂

def shop_rows(table: Iterable[Mapping[str, Any]]) -> list[dict]:
    return [{"name": str(r.get("name", "")), "class": str(r.get("class", "")),
             "price": int(r.get("积分", 0)), "desc": str(r.get("desc", ""))}
            for r in table if r.get("name")]


def find_shop(table: Iterable[Mapping[str, Any]], name: str) -> dict | None:
    for r in shop_rows(table):
        if r["name"] == name:
            return r
    return None


def buy(s: dict, uid: str, raw: str, table: Iterable[Mapping[str, Any]],
        now: float) -> tuple[bool, str, str, int, int]:
    """原版 duihuan：仅周日开放、需报名、`名称*数量`、积分足额。

    返回 (ok, msg, 物品名, 数量, 扣减积分)；发物品由 main 落库。
    """
    if not is_sunday(now):
        return False, "天地堂物品筹备中，等到周日再来兑换吧。", "", 0, 0
    i = find(s, uid)
    if i < 0:
        return False, "请先发「#报名比赛」入榜。", "", 0, 0
    name_part, _, qty_part = (raw or "").partition("*")
    name = name_part.strip()
    try:
        qty = max(1, int((qty_part or "1").strip() or "1"))
    except ValueError:
        qty = 1
    row = find_shop(table, name)
    if not row:
        return False, f"天地堂没有「{name}」这样东西，可发「#天地堂」查看货架。", "", 0, 0
    cost = int(row["price"]) * qty
    e = _norm(s["entries"][i])
    if int(e["score"]) < cost:
        return False, f"积分不足，还差 {cost - int(e['score']):,} 分兑换「{name}」×{qty}。", "", 0, 0
    e["score"] = int(e["score"]) - cost
    return True, (f"【天机榜·兑换】兑换成功！获得「{name}」×{qty}，剩余积分 {e['score']:,}。"
                  "可在「#我的纳戒」中查看。"), name, qty, cost


# ---------------------------------------------------------------- 文案

def board_lines(s: dict, uid: str, now: float) -> list[str]:
    """原版 my_point：前十 / 自己附近 / 个人状态三段式。"""
    es = sorted(s["entries"], key=lambda e: -int(e.get("score", 0)))
    lines = [f"--- 天地榜 · 积分赛（每日免费 {FREE_CHANCES} 次／周一 0 点结算）---"]
    if not es:
        lines.append("榜单空无一人，可发「#报名比赛」入榜。")
        return lines
    for i, e in enumerate(es[:TOP_N], 1):
        lines.append(f"{i}. {e['name']} — {int(e['score']):,} 分（第 {int(e['realm'])} 境）")
    my = next((i for i, e in enumerate(es) if str(e.get("uid")) == str(uid)), -1)
    if my >= TOP_N:
        lines.append("--- 我的附近 ---")
        for i in range(max(TOP_N, my - 2), min(len(es), my + 3)):
            mark = " ←我" if i == my else ""
            lines.append(f"{i + 1}. {es[i]['name']} — {int(es[i]['score']):,} 分{mark}")
    if my >= 0:
        e = _norm(es[my])
        lines.append(f"--- 我的名次：第 {my + 1} 名 ---")
        lines.append(f"积分 {int(e['score']):,}｜今日剩余 {int(e['chances'])} 次"
                     f"｜累计灵石 {int(e['earned']):,}｜第 {int(e['realm'])} 境")
    else:
        lines.append("（你尚未报名，可发「#报名比赛」）")
    lines.append(f"下周结算：{week_key(now + 7 * 86400)}｜周奖励前三名得灵石与「{BOX_NAME}」")
    return lines


def panel_lines(e: Mapping[str, Any]) -> list[str]:
    e = dict(e)
    _norm(e)
    return [
        "--- 天地榜 · 我的档案（报名快照）---",
        f"名号：{e['name']}｜第 {int(e['realm'])} 境｜积分 {int(e['score']):,}",
        f"攻击 {int(e['atk']):,}｜防御 {int(e['defense']):,}｜血量 {int(e['hp']):,}｜暴击 {int(float(e['bao']) * 100)}%",
        f"今日剩余 {int(e['chances'])} 次｜累计灵石 {int(e['earned']):,}",
        "三维是报名时冻结的快照，变强后请发「#更新属性」刷新。",
    ]


def shop_lines(table: Iterable[Mapping[str, Any]], score: int, now: float) -> list[str]:
    lines = [f"--- 天地堂（我的积分 {int(score):,}）---",
             "兑换格式：「#积分兑换 名称*数量」；仅周日开放。" if not is_sunday(now)
             else "兑换格式：「#积分兑换 名称*数量」；今日周日，货架开放。"]
    for r in shop_rows(table):
        lines.append(f"{r['name']}（{r['class']}）— {r['price']:,} 分｜{r['desc']}")
    lines.append(f"「{TICKET_NAME}」可在挑战次数归零时自动兑换 1 次额外挑战。")
    return lines


def rules_text() -> str:
    return (
        "【天地榜规则】\n"
        f"· 发「#报名比赛」冻结三维快照入榜；变强后发「#更新属性」刷新。\n"
        f"· 每日免费 {FREE_CHANCES} 次「#天地榜比试」，挑战紧邻的前一名；榜首或前排全为高阶时打「{BEAST_NAME}」。\n"
        "· 对手攻击越高，挑战者三维获 1.3 / 1.6 / 2 倍补偿；本移植复用 battle.spar 判胜负，无战损。\n"
        "· 胜 2000 分（兽 1500）／负 1000 分（兽 800）／平 500 分；灵石 = 结算后积分 × 倍率。\n"
        "· 次数用光可持「摘榜令」自动追加 1 次；「#天地堂」周日开放积分兑换。\n"
        "· 每周一 0 点结算上一周：前三名 1750/1300/920 万灵石 + 5/3/1 个「超越宝盒」，随后全员积分清零。\n"
        "⚠️ 折算：原版整榜 JSON + redis 锁 → calamity_state 单例 + 单事务落库（db 恒 v17）；"
        "原版 cron 周结算 → 指令入口惰性 tick；原版「#比试」「#天地榜」与本移植已有指令撞名 → "
        "改名「#天地榜比试」「#天地榜积分」；原版云崽 isMaster → 沿用 F1 超管名单。"
    )


def help_text() -> str:
    return ("天地榜指令：「#报名比赛」「#天地榜比试」「#天地榜积分」「#更新属性」"
            "「#天地堂」「#积分兑换 名称*数量」「#清空积分」「#结算天地榜奖励」。")
