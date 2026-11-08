"""W8-E1 复活地球：平行开局（纯函数层，无 IO）。

原版 model/revivalEarth.js v7：单条 rule + 58 个子命令，状态是玩家档顶层
`复活地球` 对象（无 redis / 无全服态）。本移植把它收进 doc.ext["earth"]，
用「惰性 tick」替代原版的后台定时结算，db 仍 v17。

移植版与原版的三处有意差异（见 rules_text）：
1. 原版入口被 model/openingArrival.js 封堵，新玩家无法入界 → 本移植开放入界，
   入界时存主线快照，可随时 `#复活地球 放弃 确认` 恢复（原版无中途退出）。
2. 原版在 active 期间全局拦截其它指令 → 本移植不拦，主线照常可玩，
   离界/放弃按快照恢复，避免改动 773 条既有指令。
3. 原版离界无条件把主线推到 level_id=42 → 本移植只升不降，
   高阶角色离界不会被打落境界。
"""
from __future__ import annotations

import math
import random
import time
from typing import Any

KEY = "earth"
VERSION = 7
MIN = 60.0                      # 原版计时单位：分钟（真实时间）
ASCEND_REALM = 41               # 0-based，对应 level_id=42 地仙

REALMS = ("凡人", "炼气", "筑基", "金丹", "元婴", "化神")
PHASES = ("初期", "中期", "后期", "大圆满")
STUDY_NEED = (0, 100, 180, 300, 480)
TOWER_CLUES = ("规章", "读数", "名册")
ELEMENTS = ("金", "木", "水", "火", "土")

JOBS: dict[str, dict] = {
    "绿植维护": {"credits": 30, "items": {"灵植": 2}, "contrib": 1},
    "工程检修": {"credits": 35, "items": {"工程部件": 1}, "contrib": 1},
    "复活值守": {"credits": 40, "items": {}, "contrib": 2},
}
CONTRACTS: dict[str, dict] = {
    "医疗补给": {"cost": {"灵植": 4}, "credits": 45, "contrib": 3},
    "设备修复": {"cost": {"工程部件": 2, "燃料": 1}, "credits": 65, "contrib": 4},
}
BREAKS: dict[str, dict] = {
    "minor": {"minutes": 5, "credits": 10, "items": {}, "risk": 0.0},
    "foundation": {"minutes": 60, "credits": 60, "items": {"筑基丹": 1}, "risk": 0.0},
    "core": {"minutes": 90, "credits": 80, "items": {}, "risk": 0.0},
    "nascent": {"minutes": 120, "credits": 100, "items": {"金脑丹": 1}, "risk": 0.65},
    "spirit": {"minutes": 120, "credits": 100, "items": {}, "risk": 0.0},
}
PERMITS: dict[str, dict] = {
    "配给": {"field": "rationed", "contrib": 4, "cost": 20},
    "居住": {"field": "resident", "contrib": 8, "cost": 60},
    "接应": {"field": "relay", "contrib": 12, "cost": 40},
}
RECIPES: dict[str, dict] = {
    "探测器": {"realm": 1, "credits": 10, "items": {"工程部件": 1}},
    "丹炉": {"realm": 1, "credits": 80, "items": {"工程部件": 3}, "facility": "丹炉"},
    "筑基丹": {"realm": 1, "credits": 20,
             "items": {"百年大蓟": 1, "百年茯神": 1, "筑基药引": 1}, "need_facility": "丹炉"},
    "本命法器": {"realm": 2, "credits": 100, "items": {"工程部件": 5}, "body": "weapon"},
    "持续火种": {"realm": 2, "credits": 50, "items": {"燃料": 3}, "facility": "持续火种"},
    "接引装置": {"realm": 4, "credits": 500, "items": {"工程部件": 12, "燃料": 6},
             "facility": "接引装置", "need_knowledge": "离界坐标"},
}
EXPEDITIONS: dict[str, dict] = {
    "地表采药": {"realm": 1, "cost": 15, "minutes": 10, "risk": 0.18,
             "items": {"灵植": 5, "百年大蓟": 1, "百年茯神": 1, "筑基药引": 1}},
    "废站勘探": {"realm": 1, "cost": 15, "minutes": 10, "risk": 0.25,
             "items": {"工程部件": 3, "燃料": 3}},
    "古木遗址": {"realm": 2, "cost": 30, "minutes": 20, "risk": 0.30,
             "items": {"千年古木": 1, "五百年灵草": 1}},
    "极寒地带": {"realm": 2, "cost": 30, "minutes": 20, "risk": 0.35,
             "items": {"水灵之气": 1}},
    "塔底调查": {"realm": 2, "cost": 40, "minutes": 20, "risk": 0.40,
             "items": {"黑雾样本": 1}, "unlock": "佛道传承"},
    "道门试炼": {"realm": 3, "cost": 80, "minutes": 30, "risk": 0.55,
             "items": {"金脑丹": 1}, "need": "佛道传承"},
    "图腾寻访": {"realm": 4, "cost": 40, "minutes": 20, "risk": 0.25,
             "items": {"图腾载体": 1}},
    "离界测绘": {"realm": 4, "cost": 50, "minutes": 20, "risk": 0.30,
             "items": {}, "unlock": "离界坐标"},
}
FIELD_MODES: dict[str, dict] = {
    "隐蔽": {"windows": 2, "adj": -0.10},
    "法术": {"windows": 1, "adj": -0.06},
    "科技": {"windows": 1, "adj": -0.12},
}
SIGNALS: dict[str, str] = {
    "回声": "切断广播", "索名": "关闭回传",
    "借影": "遮断镜头", "错时": "锁定时钟",
}
SIGNAL_ORDER = ("回声", "借影", "错时", "索名")
# 原版 TOWER_EVENTS 四组九选项：值 = (分钟, 旧表误差, 同行)
TOWER_EVENTS: dict[str, dict] = {
    "读数矛盾": {"npc": "抄表员陈默", "choices": {
        "共同核验": (15, False, False), "采用旧表": (5, True, False)}},
    "轮换分离": {"npc": "护工周苓", "choices": {
        "共用窗口": (5, False, True), "个人窗口": (10, False, False)}},
    "同号名册": {"npc": "记账员许砚", "choices": {
        "逐页对照": (20, False, False), "借用旧号": (5, True, False)}},
    "熄灯点名": {"npc": "修理工林朔", "choices": {
        "按表独行": (5, True, False), "补录同伴": (10, False, True),
        "手抄核对": (25, False, False)}},
}
TOWER_ORDER = ("读数矛盾", "同号名册", "熄灯点名", "轮换分离")
PATH_STAGES: dict[str, tuple[str, ...]] = {
    "化凡": ("借来的床位", "断药名单", "无回音的接应"),
    "信仰": ("饥年供桌", "病榻祈求", "沉默图腾", "送别之约"),
}
CRISIS_STAGES = ("失压警报", "配给争议", "名册回声")
CRISIS_CHOICES: dict[str, tuple[str, ...]] = {
    "失压警报": ("机械检修", "灵力稳压", "轮班供氧"),
    "配给争议": ("贡献优先", "配给改订", "延长轮值"),
    "名册回声": ("公开核账", "封存名册"),
}

READONLY = {
    "帮助", "规则", "状态", "外勤", "塔规", "事件", "站务", "筹备",
    "异常档案", "履历", "死亡记录", "复盘", "站务危机", "词条",
}
NEED_CONFIRM = {
    "入界", "越狱", "参与危机", "公议", "抉择", "申请", "透支",
    "接受清退", "工作", "探索", "吸收黑雾", "救援", "动用修为",
    "离界", "调查", "核验", "应对", "深入", "地表修炼", "撤离",
    "弃货撤离", "放弃",
}

# ---------------------------------------------------------------- 状态


def _body() -> dict:
    return {"realm": 0, "phase": 0, "cultivation": 0, "weapon": False,
            "elements": {k: 0 for k in ELEMENTS}, "path": "", "mortal_steps": 0,
            "vow": "", "totem": False, "faith": 0, "path_choices": []}


def new_state(doc: Any, ts: float) -> dict:
    return {
        "version": VERSION, "revision": 0, "status": "active", "created_at": ts,
        "place": "塔监狱", "body": _body(), "bag": {}, "storage": {},
        "facilities": {}, "knowledge": {}, "credits": 0, "rescue_budget": 120,
        "addiction": 0, "deaths": 0, "tower_notes": 0, "welcome": False,
        "action": None, "receipts": [], "history": [],
        "tower": {"clues": [], "ally": False, "calibrated": False,
                  "window": 0, "event": None, "stale": False, "escort": False},
        "station": {"contribution": 0, "contract": None, "resident": False,
                    "rationed": False, "relay": False, "debt": 0, "grace": 0,
                    "crisis": None, "crisis_stage": 0, "crisis_choices": []},
        "expedition": None, "life_trace": [], "death_records": [],
        "anomaly_archive": [],
        "snapshot": {
            "realm_index": int(doc.realm_index), "physique_index": int(doc.physique_index),
            "exp": int(doc.exp), "stones": int(doc.stones), "state": str(doc.state),
            "state_start": float(doc.state_start),
        },
    }


def state_of(doc: Any) -> dict | None:
    e = (doc.ext or {}).get(KEY)
    return e if isinstance(e, dict) and e.get("version") else None


def active(e: dict | None) -> bool:
    return bool(e and e.get("status") == "active")


def _restore(doc: Any, e: dict) -> None:
    s = e.get("snapshot") or {}
    for k, v in s.items():
        if hasattr(doc, k):
            setattr(doc, k, v)
    doc.ext.pop(KEY, None)


def realm_name(e: dict) -> str:
    b = e["body"]
    return f"{REALMS[min(b['realm'], 5)]}{PHASES[min(b['phase'], 3)]}"


def _add(bag: dict, name: str, qty: int) -> None:
    bag[name] = max(0, int(bag.get(name, 0) or 0) + int(qty))
    if bag[name] == 0:
        bag.pop(name, None)


def _have(bag: dict, cost: dict) -> bool:
    return all(int(bag.get(k, 0) or 0) >= v for k, v in (cost or {}).items())


def _pay(bag: dict, cost: dict) -> None:
    for k, v in (cost or {}).items():
        _add(bag, k, -v)


def _note(e: dict, text: str, ts: float) -> None:
    e["history"] = (e.get("history") or [])[-15:] + [f"{int(ts)} {text}"]
    e["life_trace"] = (e.get("life_trace") or [])[-23:] + [text]


def tower_risk(e: dict) -> float:
    t = e["tower"]
    return (5 if t["window"] == 2 else 25) / 100 + (0.15 if t["stale"] else 0) + (0.10 if t["escort"] else 0)


def die(e: dict, place: str, ts: float) -> None:
    """死亡重塑：清本世修为/随身/外勤/塔窗口；知识、仓储、设施、贡献、债务永久保留。"""
    rec = {"at": int(ts), "life": int(e["deaths"]) + 1, "realm": realm_name(e),
           "bag": dict(e["bag"])}
    e["death_records"] = (e.get("death_records") or [])[-19:] + [rec]
    e["body"] = _body()
    e["bag"] = {}
    e["expedition"] = None
    e["action"] = None
    e["life_trace"] = []
    e["tower"].update(window=0, calibrated=False, ally=False, event=None,
                      stale=False, escort=False)
    e["place"] = place
    e["deaths"] = int(e["deaths"]) + 1


def rescue(e: dict, rng: random.Random) -> str:
    """死亡/越狱后的接应判定：每轮 60 积分，概率 0.5（接应资格且无债 0.6）。"""
    attempts = min(5, int(min(int(e["credits"]), int(e["rescue_budget"])) // 60))
    if attempts <= 0:
        return "接应预算不足 60 积分，落回塔监狱。"
    p = 0.6 if (e["station"]["relay"] and not e["station"]["debt"]) else 0.5
    roll = rng.random()
    ok = roll < 1 - (1 - p) ** attempts
    hit_round = max(1, math.ceil(math.log(1 - roll) / math.log(1 - p))) if ok else attempts
    used = 60 * min(attempts, hit_round)
    e["credits"] = max(0, int(e["credits"]) - used)
    if ok:
        e["place"] = "空间站"
        if not e.get("welcome"):
            e["welcome"] = True
            e["credits"] += 120
        return f"接应成功（{attempts} 轮机会 / 消耗 {used} 积分），抵达空间站；本世修为不保。"
    return f"接应落空（消耗 {used} 积分），重新落入塔监狱。"


# ---------------------------------------------------------------- 文本


def help_text() -> str:
    return "\n".join([
        "【复活地球·独立凡间路线】",
        "独立六境：凡人→炼气→筑基→金丹→元婴→化神；本版止于化神初期。",
        "单入口：#复活地球 子命令（空参=状态），#复活全人类 亦为状态。",
        "① 塔监狱：塔规/观察/交谈/事件/抉择/推演/候时/越狱 确认",
        "② 空间站：站务/工作/委托/研读/修炼/突破/制作/蕴养/筹备/站务危机",
        "③ 地表：外勤/探索/应对/深入/地表修炼/撤离/调查 信号/核验/异常档案",
        "化神分路：化神 化凡|信仰 → 事件/抉择/立愿/动用修为/凝聚图腾/寻访信众/传道/救援",
        "资格与债务：申请/透支/还款/接受清退/接应预算/存入/取出",
        "毕业：离界 确认（化神+离界坐标+接引装置+无欠款）",
        "只读：规则/状态/复盘/履历/死亡记录；手动结算：结算",
        "移植补位：放弃 确认（恢复入界前主线快照，原版无中途退出）",
    ])


def rules_text() -> str:
    return "\n".join([
        "--- 复活地球 · 规则口径 ---",
        "· 状态：doc.ext['earth'] 单一对象（原版玩家档顶层 复活地球 v7），无全服态、无 redis。",
        "· 计时：全部为真实时间分钟数，惰性 tick（原文设定由 30s cron 扫描）；",
        "  到期后发任意指令或 #复活地球 结算 即结算，行动期间不接受新动作。",
        "· 越狱失败率：推演后 25%，候时后 5%；旧表误差 +15pp、同行 +10pp。",
        "· 观察/越狱都会触发死亡重塑：清本世境界、随身袋、外勤、塔窗口；",
        "  永久保留：knowledge、storage、facilities、塔规线索、站务贡献/债务/资格、成瘾、积分余额。",
        "· 结婴（元婴）风险 0.65 = 35% 成功，原版 docs 的「65% 闭关死亡风险」不是笔误。",
        "· 污染结婴需 突破 确认；其它突破与多数扣费动作无需确认（原版确认规则并不统一）。",
        "· 离界：化神 + 离界坐标 + 接引装置 + 无欠款 + 二次确认；本世六境不换算。",
        "· 原版入口被 openingArrival.js 封堵（新玩家无法入界），本移植开放入界并存主线快照；",
        "  原版 active 期间全局拦截其它指令，本移植不拦（不改动 773 条既有指令）；",
        "  原版离界无条件置 level_id=42，本移植只升不降，高阶角色不会被打落。",
        "· 不做：全账号重开、跨服、图片面板、化魔（原版明确拒绝）、合体/返虚。",
    ])


def status_text(doc: Any, e: dict, ts: float) -> str:
    a = e.get("action")
    act = f"{a['title']}（余 {max(0, int((a['end_at'] - ts) // 60))} 分）" if a else "空闲"
    lines = [
        f"---- 复活地球 · {realm_name(e)} ----",
        f"位置：{e['place']}｜积分 {int(e['credits']):,}｜死亡 {int(e['deaths'])} 世",
        f"主线快照：第 {int(e['snapshot']['realm_index']) + 1} 境（离界/放弃可恢复）",
        f"当前行动：{act}｜状态：{e['status']}",
        f"知识：{'、'.join(e['knowledge']) or '无'}｜设施：{'、'.join(e['facilities']) or '无'}",
        f"仓储：{sum(e['storage'].values())} 件｜随身：{sum(e['bag'].values())} 件｜债务 {int(e['station']['debt'])}",
        f"塔规线索：{len(e['tower']['clues'])}/3｜窗口 {e['tower']['window']}｜贡献 {int(e['station']['contribution'])}",
        f"修为 {int(e['body']['cultivation'])}/{STUDY_NEED[min(e['body']['realm'], 4)]}｜信仰 {int(e['body']['faith'])}",
    ]
    return "\n".join(lines)


def tower_text(e: dict) -> str:
    t = e["tower"]
    ev = t.get("event")
    lines = [
        "---- 塔规 · 第一幕 ----",
        f"线索 {len(t['clues'])}/3：{'、'.join(t['clues']) or '无'}（观察 规章|读数|名册）",
        f"协作 {t['ally']}｜校准 {t['calibrated']}｜窗口 {t['window']}（0 未推演 / 1 粗校 / 2 精校）",
        f"旧表误差 {t['stale']}｜同行 {t['escort']}｜当前失败率 {tower_risk(e):.0%}",
    ]
    if ev:
        lines.append(f"待抉择【{ev}】{TOWER_EVENTS[ev]['npc']}：" +
                     " / ".join(f"{k}({v[0]}分)" for k, v in TOWER_EVENTS[ev]["choices"].items()))
        lines.append("格式：#复活地球 抉择 选项 确认")
    return "\n".join(lines)


def station_text(e: dict) -> str:
    s = e["station"]
    lines = [
        "---- 站务 · 第二幕 ----",
        f"贡献 {int(s['contribution'])}｜委托 {s['contract'] or '无'}｜欠款 {int(s['debt'])}｜缓冲 {int(s['grace'])}/3",
        f"资格：配给 {s['rationed']}｜居住 {s['resident']}｜接应 {s['relay']}（生活费 {5 - 2 * int(s['resident']) - int(s['rationed'])}）",
        f"接应预算 {int(e['rescue_budget'])}｜公共危机 {s['crisis'] or '无'}",
        "岗位：" + " / ".join(f"{k}({v['credits']}积分/贡献{v['contrib']})" for k, v in JOBS.items()),
        "委托：" + " / ".join(f"{k}({v['credits']}积分)" for k, v in CONTRACTS.items()),
        "配方：" + " / ".join(RECIPES),
    ]
    return "\n".join(lines)


def prep_text(e: dict) -> str:
    b = e["body"]
    need = STUDY_NEED[min(b["realm"], 4)]
    br = BREAKS.get({1: "foundation", 2: "core", 3: "nascent", 4: "spirit"}.get(b["realm"], "minor"))
    lines = ["---- 筹备（只读，不扣费）----",
             f"当前 {realm_name(e)}｜修为 {int(b['cultivation'])}/{need}",
             f"下一突破：{br['minutes']} 分 / {br['credits']} 积分 / 材料 {br['items'] or '无'} / 风险 {br['risk']:.0%}"]
    gaps = [f"{k}×{v - int(e['bag'].get(k, 0) or 0)}" for k, v in br["items"].items()
            if int(e["bag"].get(k, 0) or 0) < v]
    lines.append("材料缺口：" + ("、".join(gaps) if gaps else "无（可先 取出 / 制作 / 探索）"))
    lines.append(f"积分缺口：{max(0, br['credits'] - int(e['credits'])):,}（工作 / 委托 / 交付委托）")
    return "\n".join(lines)


def field_text(e: dict) -> str:
    x = e.get("expedition")
    if not x:
        return "---- 地表外勤 ----\n当前无外勤。格式：#复活地球 探索 目标 确认\n目标：" + \
               " / ".join(f"{k}({v['cost']}分)" for k, v in EXPEDITIONS.items())
    sig = x.get("signal")
    lines = [f"---- 地表外勤 · {x['target']} ----",
             f"窗口 {x['window']}｜深入 {x['depth']}/3｜风险 {x['risk']:.0%}｜暂存 {sum(x['cargo'].values())} 件",
             f"施法余量 {x['casts']}｜信号：{(sig or {}).get('pattern') or '未发现'}"]
    if sig:
        lines.append(f"调查 {sig['investigated']}｜核验 {sig['verified']}｜" +
                     ("证据：" + sig["clue"] if sig["verified"] else "先 调查 信号 / 核验 手工|科技"))
    return "\n".join(lines)


def archive_text(e: dict) -> str:
    a = e.get("anomaly_archive") or []
    lines = ["---- 异常档案（死亡保留，最多 4 类）----",
             f"已核验 {len(a)}/4：" + ("、".join(f"{x['pattern']}·{x['method']}" for x in a) or "无"),
             "· 档案只留认知：不减风险、不揭示当前信号、不自动处置。"]
    return "\n".join(lines)


def chronicle_text(e: dict, arg: str) -> str:
    recs = e.get("death_records") or []
    if arg.isdigit():
        n = int(arg)
        hit = [r for r in recs if r["life"] == n]
        if not hit:
            return f"没有第 {n} 世的复盘记录。"
        r = hit[-1]
        return f"---- 第 {n} 世复盘 ----\n境界 {r['realm']}｜随身 {sum(r['bag'].values())} 件｜本世关键选择不随重塑保留。"
    rows = [f"第 {r['life']} 世 · {r['realm']} · 货损 {sum(r['bag'].values())} 件" for r in recs[-20:]]
    return "\n".join(["---- 死亡记录（最近 20 世）----"] + (rows or ["尚无死亡记录。"]))


def trace_text(e: dict) -> str:
    tr = e.get("life_trace") or []
    rows = [f"· {x}" for x in tr[-24:]]
    return "\n".join(["---- 本世履历（最近 24 条，死亡清空）----"] + (rows or ["尚无履历。"]))


# ---------------------------------------------------------------- 行动


def _start(e: dict, act_kind: str, title: str, minutes: float, ts: float, **payload: Any) -> str:
    # 系统字段后写，避免 payload 里的同名键（如突破的 kind）覆盖行动类型
    e["action"] = {**payload, "kind": act_kind, "title": title,
                   "end_at": ts + minutes * MIN, "started_at": ts}
    return f"已开始【{title}】，需 {minutes:g} 分钟，到期后发任意指令或 #复活地球 结算 领取结果。"


def resolve_action(e: dict, a: dict, rng: random.Random) -> str:
    k, p = a["kind"], a
    if k == "observe":
        clue = p["clue"]
        if clue not in e["tower"]["clues"]:
            e["tower"]["clues"].append(clue)
        # 原版：先 die 再重新校准；顺序反了会让 calibrated 被清掉，推演永远卡住
        die(e, "塔监狱", p["end_at"])
        t = e["tower"]
        t["calibrated"] = True
        e["tower_notes"] = len(t["clues"])
        if clue == "读数":
            t["stale"] = False
        return f"观察【{clue}】完成：线索 {len(t['clues'])}/3（永久保留）、本轮已校准。" \
               "本轮周期结束，死亡重塑回塔监狱。"
    if k == "talk":
        ev = TOWER_ORDER[min(int(rng.random() * 4), 3)]
        e["tower"]["event"] = ev
        return f"【{ev}】{TOWER_EVENTS[ev]['npc']}：可 抉择 选项 确认（详见 事件 / 塔规）。"
    if k == "tower_choice":
        t = e["tower"]
        t.update(ally=True, calibrated=True, stale=p["stale"], escort=p["escort"], event=None)
        extra = "；成功到站额外贡献 +3" if p["escort"] else ""
        return f"抉择【{p['choice']}】完成，取得协作。旧表误差 {p['stale']} / 同行 {p['escort']}{extra}。"
    if k == "deduce":
        e["tower"]["window"] = 1
        return f"推演完成：粗校窗口开启，越狱失败率 {tower_risk(e):.0%}。可 候时 降风险。"
    if k == "wait":
        e["tower"]["window"] = 2
        return f"候时完成：精校窗口，越狱失败率 {tower_risk(e):.0%}。"
    if k == "escape":
        risk = p["risk"]
        won = p["roll"] >= risk
        escort = bool(e["tower"]["escort"])
        die(e, "塔监狱", p["end_at"])       # 越狱必须先死亡重塑，本世修为不保
        if won:
            e["place"] = "空间站"
            bonus = ""
            if escort:
                e["station"]["contribution"] += 3
                bonus += "\n带出的同伴名册完成登记，站务贡献 +3。"
            if not e.get("welcome"):
                e["welcome"] = True
                e["credits"] += 120
                bonus += "\n初次登记：安置额度 120 积分（仅一次）。"
            return f"越狱判定 {p['roll']:.2f} vs 风险 {risk:.0%}：成功脱塔，抵达空间站。{bonus}"
        return (f"越狱判定 {p['roll']:.2f} vs 风险 {risk:.0%}：失败收监。\n"
                + rescue(e, rng))
    if k == "work":
        cfg = JOBS[p["job"]]
        cost = 5 - 2 * int(e["station"]["resident"]) - int(e["station"]["rationed"])
        got, debt = 0, 0
        for _ in range(p["rounds"]):
            income = cfg["credits"] - cost
            for n, q in cfg["items"].items():
                _add(e["bag"], n, q)
            d = min(int(e["station"]["debt"]), max(0, income // 4))
            e["station"]["debt"] = max(0, int(e["station"]["debt"]) - d)
            got += income - d
            debt += d
            e["station"]["contribution"] += cfg["contrib"]
        e["credits"] += got
        return (f"工作【{p['job']}】×{p['rounds']} 完成：净得 {got:,} 积分，"
                f"偿债 {debt}，贡献 +{cfg['contrib'] * p['rounds']}，物资已入随身袋。不自动续工。")
    if k == "study":
        e["knowledge"]["功法"] = True
        return "研读完成：永久知识【功法】已解锁，死亡保留。"
    if k == "cultivate":
        b = e["body"]
        b["cultivation"] += p["gain"]
        if b["realm"] == 0:
            b["realm"] = 1
            return "首次修炼：踏入【炼气】。本世独立境界，不参与主线突破。"
        return f"修炼完成：修为 +{p['gain']}（现 {int(b['cultivation'])}）。"
    if k == "fog":
        e["addiction"] += 1
        risk = min(0.9, 0.1 + float(e["addiction"]) * 0.1)
        if p["roll"] < risk:
            die(e, "空间站", p["end_at"])
            return f"黑雾反噬（风险 {risk:.0%}）：本世修为清零，成瘾 {e['addiction']} 永久保留。"
        e["body"]["cultivation"] += 75
        return f"吸收黑雾成功：修为 +75，成瘾 {e['addiction']}（死亡保留，下次风险 {min(0.9, 0.2 + e['addiction'] * 0.1):.0%}）。"
    if k == "craft":
        name = p["name"]
        cfg = RECIPES[name]
        out = []
        if cfg.get("facility"):
            e["facilities"][cfg["facility"]] = True
            out.append(f"设施【{cfg['facility']}】落成")
        elif cfg.get("body"):
            e["body"][cfg["body"]] = True
            out.append("本命法器已佩")
        else:
            _add(e["bag"], name, 1)
            out.append(f"【{name}】×1 入袋")
        return f"制作完成：{'，'.join(out)}。"
    if k == "element":
        b = e["body"]
        b["elements"][p["elem"]] = min(3, int(b["elements"][p["elem"]]) + 1)
        return f"蕴养【{p['elem']}】{b['elements'][p['elem']]}/3；五行各 3 轮方可结丹。"
    if k == "breakthrough":
        b = e["body"]
        kind = p["bt_kind"]
        if p["roll"] < BREAKS[kind]["risk"]:
            die(e, "空间站", p["end_at"])
            return f"污染结婴失败（65% 死亡风险）：本世修为清零，知识/贡献/债务保留。"
        if kind == "minor":
            b["phase"] = min(3, b["phase"] + 1)
            b["cultivation"] = 0
            return f"小境界突破：现 {realm_name(e)}。"
        b["realm"] = min(5, b["realm"] + 1)
        b["phase"] = 0
        b["cultivation"] = 0
        if kind == "spirit":
            e["knowledge"]["佛道传承"] = True
        return f"突破成功：现 {realm_name(e)}（本世独立境界）。"
    if k == "expedition":
        cfg = EXPEDITIONS[p["target"]]
        sig = None
        if p["signal_roll"] < 0.25:
            pat = SIGNAL_ORDER[min(int(p["signal_roll"] * 16), 3)]
            sig = {"pattern": pat, "investigated": False, "verified": False,
                   "clue": "", "choice": ""}
        # shortcut: 原版物资在「深入」逐处抽取；本移植出发即暂存，撤离成功才入袋
        e["expedition"] = {"target": p["target"], "window": 5, "depth": 0,
                           "casts": min(2, e["body"]["realm"]), "risk": cfg["risk"],
                           "cargo": dict(cfg["items"]), "signal": sig,
                           "discoveries": [cfg["unlock"]] if cfg.get("unlock") else []}
        return (f"抵达【{p['target']}】：窗口 5、风险 {cfg['risk']:.0%}。"
                + ("探测到异常信号，建议 调查 信号 → 核验 → 抉择。" if sig else "暂未发现信号。")
                + " 可 应对 / 深入 / 地表修炼 / 撤离 确认。")
    if k in ("field_mode", "deep", "field_cultivate", "investigate", "verify", "signal_choice"):
        x = e.get("expedition")
        if not x:
            return "外勤已结束。"
        if k == "field_mode":
            cfg = FIELD_MODES[p["mode"]]
            x["window"] -= cfg["windows"]
            x["risk"] = max(0.02, min(0.9, x["risk"] + cfg["adj"]))
            if p["mode"] == "法术":
                x["casts"] -= 1
            if p["mode"] == "科技":
                _add(e["bag"], "探测器", -1)
            return f"应对【{p['mode']}】：窗口 {x['window']}、风险 {x['risk']:.0%}。"
        if k == "deep":
            x["window"] -= 1
            x["depth"] += 1
            x["risk"] = min(0.9, x["risk"] + 0.07)
            return f"深入第 {x['depth']} 处：窗口 {x['window']}、风险 {x['risk']:.0%}。"
        if k == "field_cultivate":
            x["window"] -= 2
            x["risk"] = min(0.9, x["risk"] + 0.10)
            e["body"]["cultivation"] += 75
            return f"地表修炼：修为 +75，窗口 {x['window']}、风险 {x['risk']:.0%}。"
        sig = x.get("signal")
        if not sig:
            return "本次外勤没有异常信号。"
        if k == "investigate":
            x["window"] -= 1
            sig["investigated"] = True
            sig["clue"] = f"{sig['pattern']}：接应链路存在可核验的异常，需 核验 手工|科技 取证。"
            return f"调查 信号：{sig['clue']}"
        if k == "verify":
            if p["method"] == "科技":
                _add(e["bag"], "探测器", -1)
            else:
                x["window"] -= 1
            sig["verified"] = True
            sig["clue"] = (f"{sig['pattern']}：离线比对确认正确处置为【{SIGNALS[sig['pattern']]}】，"
                           "其余处置均会暴露。")
            return f"核验【{p['method']}】完成：{sig['clue']}"
        # signal_choice
        sig["choice"] = p["choice"]
        right = SIGNALS[sig["pattern"]]
        if p["choice"] == "追随信号":
            x["risk"] = min(0.9, x["risk"] + 0.15)
            e["addiction"] += 1
            return "追随信号：风险 +15pp，成瘾 +1（永久保留）。"
        if p["choice"] == right and sig["verified"]:
            x["risk"] = max(0.02, x["risk"] - 0.05)
            pat = sig["pattern"]
            if not any(a["pattern"] == pat for a in e["anomaly_archive"]):
                e["anomaly_archive"] = (e["anomaly_archive"] or [])[-3:] + [
                    {"pattern": pat, "method": sig.get("method", "核验"),
                     "at": int(p["end_at"]), "life": int(e["deaths"]) + 1}]
            return f"正确处置【{p['choice']}】：风险 -5pp，异常档案 +1（永久保留）。"
        x["risk"] = min(0.9, x["risk"] + 0.15)
        return f"处置【{p['choice']}】与证据不符：风险 +15pp。"
    if k == "withdraw_field":
        x = e.get("expedition")
        if not x:
            return "外勤已结束。"
        cfg = EXPEDITIONS[x["target"]]
        risk = x["risk"] - (0.15 if p["abandon"] else 0)
        cargo = {} if p["abandon"] else dict(x["cargo"])
        roll = p["roll"]
        lost = roll < risk
        if lost:
            die(e, "空间站", p["end_at"])
            return f"撤离失败（判定 {roll:.2f} vs 风险 {risk:.0%}）：本世修为清零，暂存货物散失。"
        for n, q in cargo.items():
            _add(e["bag"], n, q)
        found = []
        if not p["abandon"]:
            for name in x.get("discoveries") or []:
                e["knowledge"][name] = True
                found.append(name)
        e["expedition"] = None
        e["place"] = "空间站"
        return (f"撤离成功（判定 {roll:.2f} vs 风险 {risk:.0%}）：{sum(cargo.values())} 件物资入袋，"
                + (f"永久知识 +{'、'.join(found)}。" if found else "")
                + "返回空间站。" + ("已弃货，风险 -15pp。" if p["abandon"] else ""))
    if k in ("path", "crisis", "council"):
        s = e["station"]
        if k == "path":
            b = e["body"]
            b["path_choices"].append(p["choice"])
            b["mortal_steps"] += 1
            stages = PATH_STAGES.get(b["path"], ())
            if b["mortal_steps"] >= len(stages):
                return (f"抉择【{p['choice']}】完成，{b['path']} 经历 {b['mortal_steps']}/{len(stages)} 段已满；"
                        "可 立愿 愿文（8~80 字）后 突破 化神。")
            return f"抉择【{p['choice']}】完成，{b['path']} 经历 {b['mortal_steps']}/{len(stages)}。继续 事件 / 抉择。"
        if k == "crisis":
            s["crisis"] = CRISIS_STAGES[0]
            s["crisis_stage"] = 0
            s["crisis_choices"] = []
            return f"公共危机【{s['crisis']}】开启：单人事件，不改全服。可 公议 选项 确认（共 3 段）。"
        s["crisis_choices"].append(p["choice"])
        s["crisis_stage"] += 1
        s["contribution"] += 2
        if s["crisis_stage"] >= len(CRISIS_STAGES):
            s["crisis"] = None
            return f"公议【{p['choice']}】完成，三段危机结束，贡献 +2（合计 +6）。"
        s["crisis"] = CRISIS_STAGES[s["crisis_stage"]]
        return f"公议【{p['choice']}】完成，贡献 +2。下一段：{s['crisis']}。"
    if k == "faith":
        e["body"]["faith"] = min(100, int(e["body"]["faith"]) + p["gain"])
        return f"信众 +{p['gain']}（信仰 {e['body']['faith']}/100）。"
    if k == "totem":
        e["body"]["totem"] = True
        return "图腾凝聚完成（信仰路线化神前置）。"
    if k == "permit":
        cfg = PERMITS[p["name"]]
        e["station"][cfg["field"]] = True
        return f"资格【{p['name']}】登记完成，永久保留。"
    return f"行动【{a.get('title')}】已结算。"


def tick(e: dict, ts: float, rng: random.Random) -> list[str]:
    """惰性结算：替代原版 30s cron，所有入口与手动 结算 共用。"""
    out: list[str] = []
    guard = 0
    while e.get("action") and ts >= e["action"]["end_at"] and guard < 8:
        guard += 1
        a = e["action"]
        e["action"] = None
        out.append(resolve_action(e, a, rng))
        e["revision"] = int(e.get("revision", 0)) + 1
    if out:
        _note(e, f"结算 {len(out)} 项行动", ts)
    return out


# ---------------------------------------------------------------- 指令分发


def enter(doc: Any, ts: float, confirmed: bool) -> tuple[str, bool]:
    if state_of(doc):
        return "已有复活地球记录，发送 #复活地球 状态 查看。", False
    if not confirmed:
        return ("【入界预览】本路线从塔监狱凡人开始，独立六境、死亡清本世修为；"
                "主线数值会存快照，可随时 #复活地球 放弃 确认 恢复。\n"
                "确认请发送：#复活地球 入界 确认"), False
    doc.ext[KEY] = new_state(doc, ts)
    doc.state = "复活地球"
    doc.state_start = ts
    return ("入界成功：你身在塔监狱。本世与主线互不换算，主线快照已保存。\n"
            "先 #复活地球 塔规 / 观察 规章，再 交谈 → 抉择 → 推演 → 候时 → 越狱 确认。"), True


def abandon(doc: Any, e: dict, ts: float, confirmed: bool) -> tuple[str, bool]:
    if not confirmed:
        return ("【放弃确认】将丢弃本世全部进度（含永久知识/仓储/贡献），并恢复入界前主线快照。\n"
                "确认请发送：#复活地球 放弃 确认"), False
    s = e.get("snapshot") or {}
    _restore(doc, e)
    return (f"已放弃复活地球，主线恢复至第 {int(s.get('realm_index', 0)) + 1} 境 / "
            f"灵石 {int(s.get('stones', 0)):,}。本世记录已清除。"), True


def ascend(doc: Any, e: dict, ts: float, confirmed: bool) -> tuple[str, bool]:
    b = e["body"]
    if b["realm"] < 5:
        return f"离界需【化神】，当前 {realm_name(e)}。", False
    if not e["knowledge"].get("离界坐标"):
        return "缺少永久知识【离界坐标】：先 探索 离界测绘。", False
    if not e["facilities"].get("接引装置"):
        return "缺少设施【接引装置】：先 制作 接引装置。", False
    if e["station"]["debt"]:
        return f"尚欠 {int(e['station']['debt'])} 积分，须先 还款。", False
    if not confirmed:
        return ("【离界预览】本世六境不做换算；主线将至少提升至地仙（第 42 境），"
                "高阶角色不降级。档案封存只读。\n"
                "确认请发送：#复活地球 离界 确认"), False
    snap = e.get("snapshot") or {}
    before = int(doc.realm_index)
    if before < ASCEND_REALM:
        doc.realm_index = ASCEND_REALM
        doc.exp = 0
    doc.state = "空闲"
    doc.state_start = ts
    e["status"] = "ascended"
    e["place"] = "仙界"
    e["revision"] = int(e["revision"]) + 1
    _note(e, "离界飞升", ts)
    return (f"离界成功：主线第 {int(doc.realm_index) + 1} 境"
            + ("（不降级，保留原有境界）" if before >= ASCEND_REALM else "（地仙，修为清零）")
            + f"。本世死亡 {int(e['deaths'])} 次、永久知识 {len(e['knowledge'])} 项已封存，"
              "可继续用 状态 / 复盘 / 履历 / 死亡记录 / 异常档案 回看。"), True


def _break_kind(e: dict) -> tuple[str, str]:
    b = e["body"]
    r = b["realm"]
    if r == 0:
        return "", "凡人需先 修炼。"
    if r == 1:
        if b["cultivation"] < STUDY_NEED[r]:
            return "", f"小突破需修为 {STUDY_NEED[r]}（现 {int(b['cultivation'])}）。"
        return ("foundation" if b["phase"] == 3 else "minor"), ""
    if r == 2:
        if all(int(b["elements"][k]) >= 3 for k in ELEMENTS):
            return "core", ""
        return "", "结丹需五行各蕴养 3 轮。"
    if r == 3:
        if not e["knowledge"].get("佛道传承"):
            return "", "污染结婴需永久知识【佛道传承】（道门试炼）。"
        return "nascent", ""
    if r == 4:
        b2 = b
        ok_path = (b2["path"] == "化凡" and b2["mortal_steps"] >= 3 and b2["vow"]) or \
                  (b2["path"] == "信仰" and b2["mortal_steps"] >= 4 and b2["totem"] and b2["faith"] >= 100)
        if not ok_path:
            return "", "化神需完成 化凡（3 段 + 立愿）或 信仰（4 段 + 图腾 + 信仰 100）。"
        return "spirit", ""
    return "", "本版止于化神初期。"


def dispatch(doc: Any, rest: str, ts: float, rng: random.Random) -> tuple[str, bool]:
    """返回 (文案, 是否写档)。所有状态变更只落在 doc.ext['earth']。"""
    parts = (rest or "").strip().split()
    verb = parts[0] if parts else "状态"
    args = parts[1:]
    confirmed = bool(args and args[-1] == "确认")
    if confirmed:
        args = args[:-1]
    target = args[0] if args else ""
    num = args[1] if len(args) > 1 else ""

    e = state_of(doc)
    if not e:
        if verb == "入界":
            return enter(doc, ts, confirmed)
        if verb in ("帮助", "规则"):
            return (help_text() if verb == "帮助" else rules_text()), False
        return (f"尚未入界。发送 #复活地球 入界 预览代价，确认后 #复活地球 入界 确认。\n"
                + help_text()), False

    settled = tick(e, ts, rng)
    prefix = ("\n".join(settled) + "\n\n") if settled else ""

    # ---- 只读视图（action 期间也允许） ----
    if verb in READONLY:
        views = {
            "帮助": help_text, "规则": rules_text,
            "状态": lambda: status_text(doc, e, ts), "外勤": lambda: field_text(e),
            "塔规": lambda: tower_text(e), "事件": lambda: tower_text(e) if e["place"] == "塔监狱"
            else (station_text(e) if e["place"] == "空间站" else field_text(e)),
            "站务": lambda: station_text(e), "筹备": lambda: prep_text(e),
            "异常档案": lambda: archive_text(e), "履历": lambda: trace_text(e),
            "死亡记录": lambda: chronicle_text(e, ""), "复盘": lambda: chronicle_text(e, target),
            "站务危机": lambda: f"公共危机：{e['station']['crisis'] or '无'}｜已议 "
                              f"{e['station']['crisis_stage']}/3 段｜贡献 {e['station']['contribution']}",
            "词条": lambda: "永久知识：" + ("、".join(e["knowledge"]) or "无"),
        }
        return prefix + views[verb](), bool(settled)
    if verb == "结算":
        return (prefix + ("上述行动已结算。" if settled else "当前没有到期行动。"), bool(settled))

    # ---- 退出 / 毕业 ----
    if verb == "入界":
        return prefix + "已有复活地球记录，发送 #复活地球 状态 查看；或 放弃 确认 清除本篇。", bool(settled)
    if verb == "放弃":
        return abandon(doc, e, ts, confirmed)
    if verb == "离界":
        return ascend(doc, e, ts, confirmed)
    if e["status"] != "active":
        return prefix + "本篇已封存（只读）。可 状态 / 复盘 / 履历 / 死亡记录 / 异常档案 / 规则 / 帮助。", bool(settled)

    if e["action"]:
        a = e["action"]
        return prefix + (f"行动【{a['title']}】进行中，尚余 "
                         f"{max(0, int((a['end_at'] - ts) // 60))} 分。到点后自动结算。"), True

    # 欠款审查：只放行原版 REVIEW_ACTIONS
    review = {"工作", "还款", "接受清退", "委托", "交付委托", "取消委托",
              "存入", "取出", "接应预算"}
    if e["station"]["debt"] > 0 and e["station"]["grace"] <= 0 and verb not in review:
        return prefix + "欠款逾期进入清退审查：仅可 工作 / 还款 / 接受清退 / 委托 / 存入 / 取出 / 接应预算。", True

    # 突破只有污染结婴需要确认（在下方单独处理），其余 NEED_CONFIRM 统一二次确认
    if verb in NEED_CONFIRM and verb != "突破" and not confirmed:
        return prefix + f"【{verb}】需二次确认：#复活地球 {verb}" + \
               (f" {target}" if target else "") + (" " + num if num else "") + " 确认", True

    # ---- 即时动作 ----
    if verb == "存入" or verb == "取出":
        src, dst = (e["bag"], e["storage"]) if verb == "存入" else (e["storage"], e["bag"])
        qty = int(num) if str(num).isdigit() else 1
        if qty <= 0 or int(src.get(target, 0) or 0) < qty:
            return prefix + f"{verb}失败：{target} 数量不足。", True
        _add(src, target, -qty)
        _add(dst, target, qty)
        return prefix + f"{verb}【{target}】×{qty} 完成。", True
    if verb == "委托":
        if target not in CONTRACTS:
            return prefix + "可选委托：" + " / ".join(CONTRACTS), True
        if e["station"]["contract"]:
            return prefix + "已有委托，先 交付委托 或 取消委托。", True
        e["station"]["contract"] = target
        return prefix + f"已领【{target}】：材料 {CONTRACTS[target]['cost']}，交付时扣除。", True
    if verb == "取消委托":
        e["station"]["contract"] = None
        return prefix + "委托已取消（不扣费）。", True
    if verb == "交付委托":
        name = e["station"]["contract"]
        if not name:
            return prefix + "当前没有委托。", True
        cfg = CONTRACTS[name]
        if not _have(e["bag"], cfg["cost"]):
            return prefix + f"材料不足：{cfg['cost']}（死亡保留委托）。", True
        _pay(e["bag"], cfg["cost"])
        e["credits"] += cfg["credits"]
        e["station"]["contribution"] += cfg["contrib"]
        e["station"]["contract"] = None
        return prefix + f"交付【{name}】完成：积分 +{cfg['credits']}，贡献 +{cfg['contrib']}。", True
    if verb == "还款":
        qty = int(target) if str(target).isdigit() else 0
        if qty <= 0 or qty > e["station"]["debt"]:
            return prefix + f"还款数须为 1~{int(e['station']['debt'])} 的正整数。", True
        if e["credits"] < qty:
            return prefix + "积分不足。", True
        e["credits"] -= qty
        e["station"]["debt"] -= qty
        e["station"]["grace"] = 3
        return prefix + f"还款 {qty}，欠款 {e['station']['debt']}，缓冲恢复 3。", True
    if verb == "透支":
        qty = int(target) if str(target).isdigit() else 0
        if qty < 10 or qty > 120 or qty % 10:
            return prefix + "透支须为 10~120 的 10 的倍数（含 10% 服务费）。", True
        if e["station"]["debt"] + qty * 1.1 > 132:
            return prefix + "欠款上限 132。", True
        e["credits"] += qty
        e["station"]["debt"] += int(qty * 1.1)
        e["station"]["grace"] = 3
        return prefix + f"透支 {qty} 积分，欠款 {int(e['station']['debt'])}。", True
    if verb == "接应预算":
        qty = int(target) if str(target).isdigit() else -1
        if qty < 0 or qty > 300 or qty % 60:
            return prefix + "接应预算须为 0~300 的 60 的倍数。", True
        e["rescue_budget"] = qty
        return prefix + f"接应预算设为 {qty}（每轮 60 积分，最多 5 轮）。", True
    if verb == "接受清退":
        die(e, "塔监狱", ts)
        msg = "接受清退：死亡回塔，债务与贡献保留。\n" + rescue(e, rng)
        return prefix + msg, True
    if verb == "立愿":
        vow = " ".join(args)
        if not (8 <= len(vow) <= 80):
            return prefix + "愿文须 8~80 字。", True
        if e["body"]["mortal_steps"] < 3:
            return prefix + "需先完成化凡三段经历。", True
        e["body"]["vow"] = vow
        return prefix + f"立愿已记：{vow}", True
    if verb == "化神":
        if target not in PATH_STAGES:
            return prefix + "可选分路：化凡 / 信仰（化魔原版明确拒绝）。", True
        if e["body"]["realm"] < 4:
            return prefix + "化神分路需元婴。", True
        if e["body"]["path"] and e["body"]["path"] != target:
            return prefix + f"本世已选【{e['body']['path']}】，不可改道。", True
        e["body"]["path"] = target
        e["body"]["mortal_steps"] = 0
        return prefix + f"已选【{target}】分路：{len(PATH_STAGES[target])} 段经历，用 事件 / 抉择 选项 确认 推进。", True

    # ---- 计时动作 ----
    if verb == "观察":
        if e["place"] != "塔监狱":
            return prefix + "仅塔监狱可观察。", True
        clue = target or next((c for c in TOWER_CLUES if c not in e["tower"]["clues"]), "规章")
        if clue not in TOWER_CLUES:
            return prefix + "线索：规章 / 读数 / 名册。", True
        e["tower"]["window"] = 0
        e["tower"]["calibrated"] = False
        return prefix + _start(e, "observe", f"观察 {clue}", 5, ts, clue=clue), True
    if verb == "交谈":
        t = e["tower"]
        if e["place"] != "塔监狱" or "规章" not in t["clues"] or t["ally"] or t["event"]:
            return prefix + "交谈需：塔监狱 + 已观察 规章 + 尚无协作/待决事件。", True
        return prefix + _start(e, "talk", "交谈", 5, ts), True
    if verb == "抉择":
        # 塔内 / 信号 / 化神分路三处复用
        x = e.get("expedition")
        sig = (x or {}).get("signal")
        if sig and target in ("绕开信号", "追随信号", *SIGNALS.values()):
            if target == "绕开信号":
                return prefix + "已绕开信号，不减风险也不留档案。", True
            return prefix + _start(e, "signal_choice", f"处置 {target}", 2, ts, choice=target), True
        ev = e["tower"].get("event")
        if ev and e["place"] == "塔监狱":
            if target not in TOWER_EVENTS[ev]["choices"]:
                return prefix + "可选：" + " / ".join(TOWER_EVENTS[ev]["choices"]), True
            minutes, stale, escort = TOWER_EVENTS[ev]["choices"][target]
            return prefix + _start(e, "tower_choice", f"抉择 {target}", minutes, ts,
                                   choice=target, stale=stale, escort=escort), True
        b = e["body"]
        if b["path"] and e["place"] == "空间站":
            if not target:
                return prefix + f"当前【{b['path']}】第 {b['mortal_steps'] + 1} 段：可用 事件 查看选项。", True
            return prefix + _start(e, "path", f"抉择 {target}", 10, ts, choice=target), True
        return prefix + "当前没有待抉择事件（塔监狱 / 信号 / 化神分路）。", True
    if verb == "推演":
        t = e["tower"]
        if not (len(t["clues"]) == 3 and t["ally"] and t["calibrated"] and not t["window"]):
            return prefix + "推演需：三类线索齐备 + 协作 + 校准 + 未开窗口。", True
        return prefix + _start(e, "deduce", "推演", 5, ts), True
    if verb == "候时":
        if e["tower"]["window"] != 1:
            return prefix + "候时需先完成推演（窗口 1）。", True
        return prefix + _start(e, "wait", "候时", 5, ts), True
    if verb == "越狱":
        if e["tower"]["window"] <= 0:
            return prefix + "越狱需先 推演 开启窗口。", True
        risk = tower_risk(e)
        return prefix + _start(e, "escape", "越狱", 10, ts, risk=risk, roll=rng.random()), True
    if verb == "工作":
        if target not in JOBS:
            return prefix + "岗位：" + " / ".join(JOBS), True
        rounds = int(num) if str(num).isdigit() else 1
        if not 1 <= rounds <= 10:
            return prefix + "轮数 1~10（格式：工作 岗位 轮数 确认）。", True
        return prefix + _start(e, "work", f"工作 {target} ×{rounds}", 5 * rounds, ts,
                               job=target, rounds=rounds), True
    if verb == "研读":
        if e["credits"] < 20:
            return prefix + "研读需 20 积分。", True
        e["credits"] -= 20
        return prefix + _start(e, "study", "研读", 5, ts), True
    if verb == "修炼":
        if e["credits"] < 10 or not _have(e["bag"], {"灵植": 1}):
            return prefix + "修炼需 10 积分 + 灵植×1。", True
        e["credits"] -= 10
        _add(e["bag"], "灵植", -1)
        return prefix + _start(e, "cultivate", "修炼", 10, ts, gain=25), True
    if verb == "吸收黑雾":
        if not e["knowledge"].get("佛道传承") or not _have(e["bag"], {"黑雾样本": 1}):
            return prefix + "需永久知识【佛道传承】+ 黑雾样本×1。", True
        _add(e["bag"], "黑雾样本", -1)
        return prefix + _start(e, "fog", "吸收黑雾", 10, ts, roll=rng.random()), True
    if verb == "制作":
        if target not in RECIPES:
            return prefix + "配方：" + " / ".join(RECIPES), True
        cfg = RECIPES[target]
        if e["body"]["realm"] < cfg["realm"]:
            return prefix + f"【{target}】需本世 {REALMS[cfg['realm']]}。", True
        if cfg.get("need_facility") and not e["facilities"].get(cfg["need_facility"]):
            return prefix + f"【{target}】需设施【{cfg['need_facility']}】。", True
        if cfg.get("need_knowledge") and not e["knowledge"].get(cfg["need_knowledge"]):
            return prefix + f"【{target}】需知识【{cfg['need_knowledge']}】。", True
        if e["credits"] < cfg["credits"] or not _have(e["bag"], cfg["items"]):
            return prefix + f"【{target}】需 {cfg['credits']} 积分 + {cfg['items']}。", True
        e["credits"] -= cfg["credits"]
        _pay(e["bag"], cfg["items"])
        return prefix + _start(e, "craft", f"制作 {target}", 15, ts, name=target), True
    if verb == "蕴养":
        if e["body"]["realm"] != 2:
            return prefix + "五行蕴养仅筑基期可做。", True
        if target not in ELEMENTS:
            return prefix + "五行：" + " / ".join(ELEMENTS), True
        if e["credits"] < 20:
            return prefix + "蕴养需 20 积分。", True
        e["credits"] -= 20
        return prefix + _start(e, "element", f"蕴养 {target}", 30, ts, elem=target), True
    if verb == "突破":
        kind, err = _break_kind(e)
        if err:
            return prefix + err, True
        cfg = BREAKS[kind]
        if e["credits"] < cfg["credits"] or not _have(e["bag"], cfg["items"]):
            return prefix + f"突破需 {cfg['credits']} 积分 + {cfg['items'] or '无材料'}。", True
        if kind == "nascent" and not confirmed:
            return prefix + "污染结婴有 65% 死亡风险，确认请发送：#复活地球 突破 确认", True
        e["credits"] -= cfg["credits"]
        _pay(e["bag"], cfg["items"])
        return prefix + _start(e, "breakthrough", f"突破·{kind}", cfg["minutes"], ts,
                               bt_kind=kind, roll=rng.random()), True
    if verb == "申请":
        if target not in PERMITS:
            return prefix + "资格：" + " / ".join(PERMITS), True
        cfg = PERMITS[target]
        if e["station"]["contribution"] < cfg["contrib"] or e["credits"] < cfg["cost"]:
            return prefix + f"【{target}】需贡献 {cfg['contrib']} + 积分 {cfg['cost']}。", True
        e["credits"] -= cfg["cost"]
        return prefix + _start(e, "permit", f"申请 {target}", 5, ts, name=target), True
    if verb == "参与危机":
        return prefix + _start(e, "crisis", "参与危机", 5, ts), True
    if verb == "公议":
        cur = e["station"]["crisis"]
        if not cur:
            return prefix + "先 参与危机 确认。", True
        opts = CRISIS_CHOICES[cur]
        if target not in opts:
            return prefix + "可选：" + " / ".join(opts), True
        return prefix + _start(e, "council", f"公议 {target}", 10, ts, choice=target), True
    if verb == "探索":
        if target not in EXPEDITIONS:
            return prefix + "目标：" + " / ".join(EXPEDITIONS), True
        cfg = EXPEDITIONS[target]
        if e["body"]["realm"] < cfg["realm"] or e["credits"] < cfg["cost"]:
            return prefix + f"【{target}】需 {REALMS[cfg['realm']]} + {cfg['cost']} 积分。", True
        # 原版 unlock 是探索后写入的永久知识，不是门槛；need 才是前置知识
        if cfg.get("need") and not e["knowledge"].get(cfg["need"]):
            return prefix + f"【{target}】需知识【{cfg['need']}】。", True
        e["credits"] -= cfg["cost"]
        return prefix + _start(e, "expedition", f"探索 {target}", cfg["minutes"], ts,
                               target=target, signal_roll=rng.random()), True
    if verb == "应对":
        x = e.get("expedition")
        if not x:
            return prefix + "当前没有外勤。", True
        if target not in FIELD_MODES:
            return prefix + "应对：" + " / ".join(FIELD_MODES), True
        if target == "法术" and x["casts"] <= 0:
            return prefix + "施法余量不足。", True
        if target == "科技" and not _have(e["bag"], {"探测器": 1}):
            return prefix + "科技应对需 探测器×1（可用 制作 探测器）。", True
        return prefix + _start(e, "field_mode", f"应对 {target}", 5, ts, mode=target), True
    if verb == "深入":
        x = e.get("expedition")
        if not x or x["depth"] >= 3 or x["window"] < 1:
            return prefix + "深入需外勤中、窗口 ≥1、至多 3 处。", True
        return prefix + _start(e, "deep", "深入", 5, ts), True
    if verb == "地表修炼":
        x = e.get("expedition")
        if not x or x["window"] < 2:
            return prefix + "地表修炼需外勤中且窗口 ≥2。", True
        return prefix + _start(e, "field_cultivate", "地表修炼", 5, ts), True
    if verb == "调查":
        x = e.get("expedition")
        if not x or not x.get("signal") or x["window"] < 1:
            return prefix + "当前无可调查信号或窗口不足。", True
        x["signal"]["method"] = "手工"
        return prefix + _start(e, "investigate", "调查 信号", 5, ts), True
    if verb == "核验":
        x = e.get("expedition")
        if not x or not (x.get("signal") or {}).get("investigated"):
            return prefix + "需先 调查 信号 确认。", True
        if target not in ("手工", "科技"):
            return prefix + "核验方式：手工 / 科技。", True
        if target == "科技" and not _have(e["bag"], {"探测器": 1}):
            return prefix + "科技核验需 探测器×1。", True
        x["signal"]["method"] = target
        return prefix + _start(e, "verify", f"核验 {target}", 2 if target == "科技" else 5, ts,
                               method=target), True
    if verb in ("撤离", "弃货撤离"):
        x = e.get("expedition")
        if not x:
            return prefix + "当前没有外勤。", True
        if x["window"] < 0:
            x["window"] = 0
        if verb == "弃货撤离":
            x["cargo"] = {}
            x["discoveries"] = []
        return prefix + _start(e, "withdraw_field", verb, 5, ts,
                               abandon=(verb == "弃货撤离"), roll=rng.random()), True
    if verb == "寻访信众":
        if e["credits"] < 30:
            return prefix + "寻访信众需 30 积分。", True
        e["credits"] -= 30
        e["knowledge"]["信众群体"] = True
        return prefix + _start(e, "faith", "寻访信众", 10, ts, gain=15), True
    if verb == "传道":
        if e["credits"] < 30 or not _have(e["bag"], {"灵植": 1}):
            return prefix + "传道需 30 积分 + 灵植×1。", True
        e["credits"] -= 30
        _add(e["bag"], "灵植", -1)
        return prefix + _start(e, "faith", "传道", 10, ts, gain=25), True
    if verb == "凝聚图腾":
        if e["credits"] < 60 or not _have(e["bag"], {"图腾载体": 1}):
            return prefix + "凝聚图腾需 60 积分 + 图腾载体×1。", True
        e["credits"] -= 60
        _add(e["bag"], "图腾载体", -1)
        return prefix + _start(e, "totem", "凝聚图腾", 20, ts), True
    if verb == "救援":
        e["station"]["contribution"] += 2
        return prefix + _start(e, "faith", "救援", 10, ts, gain=5), True
    if verb == "动用修为":
        e["body"]["cultivation"] = 0
        e["body"]["mortal_steps"] = 0
        return prefix + "动用修为：本世悟道重置（境界保留），化神分路可重走。", True
    return prefix + f"未知子命令【{verb}】。发送 #复活地球 帮助 查看全部。", bool(settled)
