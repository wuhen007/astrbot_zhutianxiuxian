"""大道炼器 / 文明大道至宝（W8-C3，纯函数无 IO）。

原版取证：`apps/duanzao/DaoTreasure.js`（702 行 / 15 条 rule）、
`model/daoTreasure.js`（584 行 / 状态机）、`model/realmEventClock.js`。

落地口径：
- 全服 `{project, treasure, invites}` 挂 `calamity_state["daotreasure"]`，玩家状态挂 `ext["dt"]`；
  不改表、不注册第三轨、不引入 cron（沿用 `era.years_total` 惰性推进）。
- 世界年 = `era` 的 `years_total`。原版 `((epoch-1)*5+index)*10000+years` 与本移植
  五时代 × 10000 年线性时间线**完全等价**，故直接取总年数。
- 50_000 年 / 5 阶段，每阶段需 ≥3 人镇守；第 5 阶段只能打镜像。
- 燃料在点炉前一次性收齐；阶段本身不耗材料。

shortcut（与原版差异，写清楚便于以后升级）：
1. `#大道至宝` 已被 W7-5a「彼岸铸宝」占用，本批改用 `#大道权柄`（别名 `#文明至宝`）。
2. 原版要求 `炉阶∈{混沌炉,造化仙炉}` + `炉火=道火` + `炼器功法=无上炼器道/熟练度100`；
   C4 锻炉落地后由 `duanzao.gate()` 回填这三项（见 `open_forge`）；未建档的旧存档
   仍回退「炼器师职业等级 ≥20（炉火纯青）」，避免卡死 C3 已有进度。
3. 至宝三维：原版固定 +1e12 与套装乘区 +300，按本移植 C1/C2 的 ÷1000 口径折算为
   flat 300_000 / ratio 0.30 / bao 0.15；超纲的 1e12 会碾平全部既有体系。
4. 原版「永寂之界复活 / 指定命格表 / 小世界升格大道界」依赖三套本移植没有的外部系统，
   折算为：清寿元救援倒计时 + 道伤 + 渡劫损耗、按 `item/命格词条` 换整条快照、
   记 `dao_world` 旗标（由战斗装配消费，不留无消费者的死字段）。
5. 原版 redis 60 秒改命邀请改用全服 `invites` + 时间戳；无 Promise 串行锁、
   无 cron 成器发放（改由 `#大道权柄` 主动触发），无全服广播。
6. 器劫失败**不降阶也不扣血**（原版同样如此，规划稿「失败降阶」是取证错误）。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any

WORLD_KEY = "daotreasure"
EXT_KEY = "dt"

FORGE_YEARS = 50_000
STAGE_YEARS = 10_000
EPOCH_YEARS = 50_000
MAX_ORIGIN = 12
EPOCH_RECOVERY = 4
GUARD_TARGET = 3
INVITE_SECONDS = 60.0

# (阶段名, 绑定的权柄/本体)
STAGES: tuple[tuple[str, str], ...] = (
    ("熔薪", "本体"), ("铸胚", "生死"), ("铭权", "命运"),
    ("养道", "万法"), ("渡劫", "世界"),
)
AUTHORITIES: tuple[str, ...] = ("生死", "命运", "万法", "世界")
REPAIR_TARGETS: tuple[str, ...] = ("本体", *AUTHORITIES)
TECH_TYPES: tuple[str, ...] = ("攻伐", "护道", "轮回", "悟道")

FUEL: dict[str, int] = {
    "众生念力": 1000, "鸿蒙道火": 100, "界核": 50, "宇宙核心": 10,
}
FUEL_SCORE: dict[str, int] = {
    "众生念力": 1, "鸿蒙道火": 10, "界核": 20, "宇宙核心": 100,
}
REPAIR_COST: dict[str, int] = {
    "众生念力": 200, "鸿蒙道火": 20, "界核": 10, "宇宙核心": 2,
}

# 原版 APTITUDE_EVALUATIONS（DaoTreasure.js:51-64），由高到低 10 级
APTITUDES: dict[str, str] = {
    "无演无尽": "亘古绝今从未有，演尽诸天万界，已超脱天道束缚",
    "万古无双": "横推古今未来无对手，为修道而生，为应劫而至",
    "绝世天骄": "惊才绝艳，具备帝姿，注定成为一个时代的主角",
    "旷世奇才": "万年难遇，放眼九天十地亦难寻其一",
    "天纵之资": "天赋异禀，足以比肩上古大教最杰出的传人",
    "超凡资质": "资质超凡，道基之上已有异象显化",
    "平庸之资": "资质平平，尚需以岁月与心志弥补",
    "先天不足": "先天有缺，修炼事倍功半",
    "天弃之人": "被天道抛弃，每一步修行皆有劫难",
    "生而愚痴": "识海混沌，修行之路极其艰难",
}
# 天资 → 三维乘区增量（本移植自定，让「#重塑天资」有真实消费者）
APTITUDE_MULT: dict[str, float] = {
    "无演无尽": 0.30, "万古无双": 0.24, "绝世天骄": 0.18, "旷世奇才": 0.13,
    "天纵之资": 0.09, "超凡资质": 0.05, "平庸之资": 0.0, "先天不足": -0.05,
    "天弃之人": -0.10, "生而愚痴": -0.15,
}

COST_LIFE, COST_FATE, COST_APT = 6, 3, 3
COST_APT_TOP, COST_TECH, COST_WORLD = 6, 8, 12

# 至宝三维（原版 1e12 / +300 / 1.0 ÷1000 再按本移植量级收敛）
FLAT_ALL, RATIO_ALL, BAO_FLAT = 300_000.0, 0.30, 0.15


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, dict(delta or {})


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


# ── 状态 ────────────────────────────────────────────────────────────────────
def world_of(calamity: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = (calamity or {}).get(WORLD_KEY) if isinstance(calamity, Mapping) else None
    w = dict(raw) if isinstance(raw, Mapping) else {}
    w.setdefault("project", None)
    w.setdefault("treasure", None)
    w.setdefault("invites", {})
    w.setdefault("history", [])
    for key in ("invites",):
        if not isinstance(w[key], dict):
            w[key] = {}
    if not isinstance(w["history"], list):
        w["history"] = []
    return w


def set_world(calamity: dict[str, Any], w: Mapping[str, Any]) -> None:
    calamity[WORLD_KEY] = dict(w)


def _player(doc: Any) -> dict[str, Any]:
    st = doc.ext.get(EXT_KEY)
    st = dict(st) if isinstance(st, Mapping) else {}
    st.setdefault("owned", "")
    st.setdefault("authority", "")
    st.setdefault("aptitude", "")
    st.setdefault("technique", None)
    st.setdefault("dao_world", "")
    st.setdefault("traces", 0)
    st.setdefault("contribution", 0)
    st.setdefault("rewrites", [])
    return st


def _save(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext[EXT_KEY] = dict(st)


def epoch_of(years_total: int) -> int:
    return 1 + max(0, int(years_total)) // EPOCH_YEARS


def _new_project(doc: Any, name: str, years_total: int) -> dict[str, Any]:
    return {
        "name": name,
        "owner_id": str(doc.uid), "owner_name": doc.name or doc.uid[:8],
        "status": "gathering",
        "created_year": int(years_total), "start_year": 0,
        "stage_index": 0,
        "fuel": {k: 0 for k in FUEL},
        "contributors": {},
        "stages": [{"name": s[0], "authority": s[1], "guardians": [],
                    "closed": False, "complete": False} for s in STAGES],
        "completed_year": 0,
    }


def advance(w: dict[str, Any], years_total: int, now: float | None = None) -> list[str]:
    """惰性推进状态机：按当前世界年关阶段 / 成器 / 补算本源。返回事件文案。"""
    notes: list[str] = []
    years = max(0, int(years_total))
    clock = time.time() if now is None else float(now)
    p = w.get("project")
    if isinstance(p, dict) and p.get("status") == "forging":
        start = int(p.get("start_year") or 0)
        target = min(len(STAGES), max(0, (years - start) // STAGE_YEARS))
        stages = p.get("stages") or []
        while int(p.get("stage_index") or 0) < target:
            i = int(p["stage_index"])
            if i < len(stages):
                row = stages[i]
                row["closed"] = True
                row["complete"] = len(row.get("guardians") or []) >= GUARD_TARGET
                notes.append(f"【{row['name']}】阶段闭合：镇守 {len(row.get('guardians') or [])}/3，"
                             f"{'完整' if row['complete'] else '残缺'}")
            p["stage_index"] = i + 1
        if int(p["stage_index"]) >= len(STAGES):
            done = sum(1 for s in stages if s.get("complete"))
            auth = {s.get("authority"): ("完整" if s.get("complete") else "残缺")
                    for s in stages if s.get("authority") != "本体"}
            t = {
                "name": p["name"], "owner_id": p["owner_id"], "owner_name": p["owner_name"],
                "completed_year": years, "completed_epoch": epoch_of(years),
                "integrity": done * 20,
                "body": "完整" if stages and stages[0].get("complete") else "残缺",
                "authorities": auth,
                "origin": MAX_ORIGIN, "last_recovery_epoch": epoch_of(years),
                "uses": {}, "ultimate_technique": None, "dao_world": None,
                "delivery": "pending",
            }
            w["treasure"] = t
            p["status"] = "completed"
            p["completed_year"] = years
            notes.append(f"【大道至宝·{t['name']}】出世！完整度 {t['integrity']}%，"
                         f"器主 {t['owner_name']} 可发 #大道权柄 领取。")
    t = w.get("treasure")
    if isinstance(t, dict):
        ep = epoch_of(years)
        last = int(t.get("last_recovery_epoch") or 1)
        if ep > last:
            t["origin"] = min(MAX_ORIGIN, int(t.get("origin") or 0)
                              + (ep - last) * EPOCH_RECOVERY)
            t["last_recovery_epoch"] = ep
            notes.append(f"【文明本源】跨 {(ep - last)} 纪元恢复，现 {t['origin']}/{MAX_ORIGIN}。")
    for uid, inv in list((w.get("invites") or {}).items()):
        if float(inv.get("exp") or 0) <= clock:
            w["invites"].pop(uid, None)
    return notes


# ── 校验 ────────────────────────────────────────────────────────────────────
def _owner_ok(doc: Any, w: Mapping[str, Any]) -> str | None:
    t = w.get("treasure")
    if not isinstance(t, dict):
        return "诸天尚无文明大道至宝出世。"
    st = _player(doc)
    if str(t.get("owner_id")) != str(doc.uid) or not st.get("owned"):
        return f"唯有器主【{t.get('owner_name')}】且已领取【{t.get('name')}】方能役使大道。"
    return None


def _authority_ok(doc: Any, w: Mapping[str, Any], key: str) -> str | None:
    err = _owner_ok(doc, w)
    if err:
        return err
    t = w["treasure"]
    if t.get("authorities", {}).get(key) != "完整":
        return f"【{key}】权柄残缺，请先 #修复大道权柄 {key}。"
    return None


def _spend(w: dict[str, Any], cost: int, use_key: str | None = None) -> str | None:
    t = w.get("treasure")
    if not isinstance(t, dict):
        return "诸天尚无文明大道至宝出世。"
    if use_key and (t.get("uses") or {}).get(use_key):
        return "这件大道至宝已经用过此等大道伟力（每件仅一次）。"
    if int(t.get("origin") or 0) < cost:
        return f"文明本源不足，当前 {int(t.get('origin') or 0)}/{MAX_ORIGIN} 点（需 {cost}）。"
    t["origin"] = int(t["origin"]) - cost
    if use_key:
        t.setdefault("uses", {})[use_key] = {"cost": cost, "year": t.get("completed_year")}
    return None


# ── 面板 / 帮助 ─────────────────────────────────────────────────────────────
def forge_panel(w: Mapping[str, Any], years_total: int) -> str:
    p = w.get("project")
    cur = epoch_of(years_total)
    lines = [f"【大道熔炉】世界年 {years_total:,}（第 {cur} 纪元）",
             f"历法：五阶段 × {STAGE_YEARS:,} 年 = {FORGE_YEARS:,} 年成器；每阶段需 ≥{GUARD_TARGET} 人镇守。"]
    if not isinstance(p, dict):
        lines.append("大道炉尚未立起。开铸条件见 #大道炼器规则，先由炼器师 #开铸大道至宝 名。")
        return "\n".join(lines)
    lines.append(f"工程【{p.get('name')}】｜器主 {p.get('owner_name')}｜状态 {p.get('status')}")
    if p.get("status") == "gathering":
        for k, need in FUEL.items():
            lines.append(f"　{k}：{int((p.get('fuel') or {}).get(k, 0))}/{need}")
        lines.append("四种燃料齐备即自动点炉（#献祭文明 材料*数）。")
    elif p.get("status") == "forging":
        idx = int(p.get("stage_index") or 0)
        elapsed = max(0, years_total - int(p.get("start_year") or 0))
        lines.append(f"　已历 {elapsed:,}/{FORGE_YEARS:,} 世界年，当前阶段 {idx + 1}/5"
                     f"（{STAGES[min(idx, 4)][0]}）")
        for i, s in enumerate(p.get("stages") or []):
            mark = "✔完整" if s.get("complete") else ("✘残缺" if s.get("closed") else "进行中")
            lines.append(f"　{i + 1}. {s.get('name')}（{s.get('authority')}）："
                         f"镇守 {len(s.get('guardians') or [])}/3　{mark}")
        lines.append("第 5 阶段【渡劫】不接受镇守，须 #渡大道器劫 胜过大道路化身。")
    else:
        lines.append(f"　已于世界年 {int(p.get('completed_year') or 0):,} 成器。")
    if w.get("history"):
        lines.append("近期：" + "；".join(str(x) for x in w["history"][-3:]))
    return "\n".join(lines)


def treasure_panel(doc: Any, w: dict[str, Any], years_total: int) -> str:
    t = w.get("treasure")
    if not isinstance(t, dict):
        return "文明大道至宝尚未出世。发 #大道炼器 查看熔炉进度。"
    # 成器发放：原版靠 10 分钟 cron，本移植改由本指令主动触发（一次性）
    if t.get("delivery") == "pending" and str(t.get("owner_id")) == str(doc.uid):
        st = _player(doc)
        st["owned"] = t["name"]
        _save(doc, st)
        t["delivery"] = "delivered"
    lines = [
        f"【文明大道至宝 · {t.get('name')}】",
        f"器主：{t.get('owner_name')}｜成器世界年 {int(t.get('completed_year') or 0):,}",
        f"本体：{t.get('body')}｜完整度 {int(t.get('integrity') or 0)}%",
        "权柄：" + "、".join(f"{k} {v}" for k, v in (t.get("authorities") or {}).items()),
        f"文明本源：{int(t.get('origin') or 0)}/{MAX_ORIGIN}（每纪元恢复 {EPOCH_RECOVERY}）",
    ]
    st = _player(doc)
    if str(t.get("owner_id")) == str(doc.uid):
        lines.append(f"已领取：{'是' if st.get('owned') else '否（再发一次本指令即可）'}"
                     f"｜敕令权柄：{st.get('authority') or '未设'}")
        lines.append(f"天资：{st.get('aptitude') or '未重塑'}｜终极功法："
                     f"{(st.get('technique') or {}).get('name') if isinstance(st.get('technique'), dict) else '未推演'}"
                     f"｜大道界：{st.get('dao_world') or '未开辟'}")
        lines.append(f"文明道痕 {int(st.get('traces') or 0)}｜薪火贡献 "
                     f"{int(st.get('contribution') or 0)}｜改写记录 {len(st.get('rewrites') or [])}")
    return "\n".join(lines)


def help_text() -> str:
    return "\n".join([
        "【大道炼器 · 指令一览】",
        "#大道炼器 / #大道炼器规则 / #大道炼器帮助　熔炉进度与全部规则",
        "#开铸大道至宝 名　炼器师立炉（1-10 字，全服唯一）",
        "#献祭文明 材料*数　投入四种燃料：众生念力1000 / 鸿蒙道火100 / 界核50 / 宇宙核心10",
        "#镇守大道炉　前四阶段各留一道文明道痕（每阶段需 3 人）",
        "#渡大道器劫　第五阶段打自身镜像，胜者计为镇守",
        "#大道权柄（别名 #文明至宝）　领取成器 + 完整度 / 权柄 / 本源面板",
        "#大道至宝改名 名　改器名（填本名可复原）",
        "#敕令大道 生死|命运|万法|世界　选定战斗开场权柄",
        "#修复大道权柄 本体|生死|命运|万法|世界　耗燃料补残缺、完整度 +20",
        "#改写生死 [目标]　耗 6 本源，消寿元救援倒计时 / 道伤 / 渡劫损耗",
        "#改写命格 命格名 [目标]　耗 3 本源，换整条命格快照",
        "#重塑天资 十级天资名 [目标]　耗 3 本源（无演无尽 6），改三维乘区",
        "#同意大道改命　他人在 60 秒内确认改命邀请",
        "#推演终极功法 名 [攻伐|护道|轮回|悟道]　耗 8 本源，每件至宝一次",
        "#开辟大道界 名　耗 12 本源，每件至宝一次",
        "注：原版 #大道至宝 已被本插件「彼岸铸宝」占用，此处改名为 #大道权柄。",
    ])


def rules_text() -> str:
    return "\n".join([
        "【大道炼器 · 规则】",
        "1. 开铸：职业=炼器师、权柄境界≥22（祭道）、职业等级≥20（炉火纯青）。"
        "原版还要求混沌炉/造化仙炉 + 道火 + 无上炼器道 100 熟练度，本移植 C4 前折算为职业等级。",
        f"2. 燃料：四种一次性收齐，齐备自动点炉；每阶段 {STAGE_YEARS:,} 世界年，"
        f"共 {FORGE_YEARS:,} 年（= 一整轮五时代 ≈ 现实 100 小时）。",
        f"3. 镇守：前四阶段每阶段 ≥{GUARD_TARGET} 人，闭合时判定完整；"
        "少一人则对应权柄残缺、完整度 -20%。第五阶段须胜镜像。",
        "4. 器劫：敌方 = 己方攻击 ×(1.05+权柄×0.005)、防御 ×0.9、血量 ×1.25；"
        "失败无任何惩罚、可无限重试；同一人胜利后不可重复渡劫。",
        f"5. 本源：成器 {MAX_ORIGIN} 点，每跨一纪元恢复 {EPOCH_RECOVERY} 点（懒计算，上限 {MAX_ORIGIN}）。"
        "改命 6/3/3（无演无尽 6）、终极功法 8（一次）、大道界 12（一次）。",
        "6. 改命他人：@目标 后须由对方 60 秒内发 #同意大道改命；改自己立即生效。",
        "7. 三维：成器本体按完整度给固定三维 + 全属性乘区（原版 1e12/+300 已按本移植量级折算）。",
        "8. 权柄需「完整」方能敕令生效：生死=复活、命运=必暴、万法=增伤、世界=减伤。",
        "shortcut：未做全服广播 / 10 分钟 cron 发放 / Promise 串行锁 / 梦幻权柄旁路。",
    ])


def materials_text() -> str:
    return "\n".join([
        "【文明薪火 · 四种燃料】",
        *[f"{k}：目标 {v}（献祭权重 {FUEL_SCORE[k]}/份）" for k, v in FUEL.items()],
        "修复权柄另需：" + "、".join(f"{k}×{v}" for k, v in REPAIR_COST.items()),
        "获取：秘境结算 12% 概率成批投放；界核 / 宇宙核心 / 鸿蒙道火 亦可用愿鳞兑换。",
    ])


# ── 玩法 ────────────────────────────────────────────────────────────────────
def open_forge(doc: Any, name: str, w: dict[str, Any], years_total: int
               ) -> tuple[bool, str, dict[str, int]]:
    name = (name or "").strip()
    if not (1 <= len(name) <= 10) or any(c in name for c in "\r\n<>"):
        return _no("至宝名称需为 1 至 10 个字符，且不可包含换行或尖括号。")
    if isinstance(w.get("treasure"), dict):
        return _no(f"大道至宝【{w['treasure'].get('name')}】已经出世，诸天不容第二件同阶之器。")
    p = w.get("project")
    if isinstance(p, dict) and p.get("status") != "completed":
        return _no(f"大道炉已由 {p.get('owner_name')} 立下，当前正在炼制【{p.get('name')}】。")
    from . import authority as auth_mod
    if str(doc.ext.get("occupation") or "") != "炼器师":
        return _no("唯有炼器师能够立下大道熔炉。")
    if auth_mod.authority_of(doc) < 22:
        return _no("开铸大道至宝需要达到祭道境（权柄境界 ≥22）。")
    # W8-C4 回填：锻炉落地后走原版三项校验（炉阶/炉火/无上炼器道熟练度），
    # 未建档的旧存档仍回退职业等级 ≥20，避免卡死 C3 已有进度。
    try:
        from . import duanzao as _dzl
        gate_ok, gate_msg, strict = _dzl.gate(doc)
    except Exception:
        gate_ok, gate_msg, strict = True, "", False
    if strict:
        if not gate_ok:
            return _no(gate_msg)
    elif int(doc.ext.get("occupation_level") or 0) < 20:
        return _no("需将炼器之道修至「炉火纯青」（职业等级 ≥20），方能承受文明炉火。")
    w["project"] = _new_project(doc, name, years_total)
    w.setdefault("history", []).append(f"世界年 {years_total:,}：{doc.name or doc.uid[:8]} 立炉【{name}】")
    w["history"] = w["history"][-10:]
    return _ok(f"【大道熔炉·{name}】立炉成功！\n" + forge_panel(w, years_total))


def _parse_fuel(arg: str) -> tuple[str, int] | None:
    raw = (arg or "").strip().replace("×", "*").replace("x", "*")
    if "*" not in raw:
        return None
    name, _, num = raw.rpartition("*")
    name = name.strip()
    try:
        n = int(num.strip())
    except ValueError:
        return None
    if name not in FUEL or n <= 0:
        return None
    return name, n


def contribute(doc: Any, inv: Mapping[str, int], arg: str, w: dict[str, Any],
               years_total: int, now: float) -> tuple[bool, str, dict[str, int]]:
    p = w.get("project")
    if not isinstance(p, dict) or p.get("status") != "gathering":
        return _no("当前没有正在募集薪火的大道熔炉。")
    parsed = _parse_fuel(arg)
    if not parsed:
        return _no("格式：#献祭文明 众生念力*100（四种燃料见 #大道炼器规则）")
    name, amount = parsed
    have = int(inv.get(name, 0) or 0)
    if have <= 0:
        return _no(f"纳戒中没有【{name}】。")
    need = int(FUEL[name]) - int((p.get("fuel") or {}).get(name, 0) or 0)
    accepted = min(have, amount, max(0, need))
    if accepted <= 0:
        return _no(f"【{name}】已集满 {FUEL[name]}，无需再献。")
    p.setdefault("fuel", {})[name] = int(p["fuel"].get(name, 0) or 0) + accepted
    c = p.setdefault("contributors", {}).setdefault(str(doc.uid), {"name": doc.name or doc.uid[:8],
                                                                   "total": 0, "fuel": {}})
    c["total"] = int(c.get("total") or 0) + accepted * FUEL_SCORE[name]
    c["fuel"][name] = int((c.get("fuel") or {}).get(name, 0) or 0) + accepted
    st = _player(doc)
    if not int(st.get("contribution") or 0):
        st["traces"] = int(st.get("traces") or 0) + 1       # 首次献祭 +1 文明道痕
    st["contribution"] = int(st.get("contribution") or 0) + accepted * FUEL_SCORE[name]
    _save(doc, st)
    lines = [f"献祭【{name}】×{accepted}，文明薪火贡献 +{accepted * FUEL_SCORE[name]}。"]
    ready = all(int((p["fuel"]).get(k, 0) or 0) >= v for k, v in FUEL.items())
    if ready:
        p["status"] = "forging"
        p["start_year"] = int(years_total)
        p["stage_index"] = 0
        w.setdefault("history", []).append(f"世界年 {years_total:,}：薪火齐备，大道炉点燃")
        lines.append("四种燃料齐备，大道炉点燃！此后按世界年推进五阶段。")
    lines.append(forge_panel(w, years_total))
    return _ok("\n".join(lines), {name: -accepted})


def guard_forge(doc: Any, w: dict[str, Any], years_total: int, now: float
                ) -> tuple[bool, str, dict[str, int]]:
    p = w.get("project")
    if not isinstance(p, dict) or p.get("status") != "forging":
        return _no("大道炉尚未点燃，先集齐四种燃料。")
    idx = int(p.get("stage_index") or 0)
    if idx >= 4:
        return _no("第五阶段【渡劫】不接受镇守，请发 #渡大道器劫。")
    stages = p.get("stages") or []
    row = stages[idx]
    guards = row.setdefault("guardians", [])
    if str(doc.uid) in guards:
        return _no(f"你已在【{row['name']}】阶段留下文明道痕。")
    guards.append(str(doc.uid))
    st = _player(doc)
    st["traces"] = int(st.get("traces") or 0) + 1
    _save(doc, st)
    return _ok(f"【{row['name']}】阶段镇守成功：{len(guards)}/{GUARD_TARGET} 人。"
               + ("　本阶段已稳固。" if len(guards) >= GUARD_TARGET else "　尚需更多道友。")
               + f"｜文明道痕 {st['traces']}")


def tribulation(doc: Any, w: dict[str, Any], years_total: int, stats: Any,
                rng: random.Random, now: float) -> tuple[bool, str, dict[str, int]]:
    from . import authority as auth_mod
    from . import battle
    p = w.get("project")
    if not isinstance(p, dict) or p.get("status") != "forging":
        return _no("大道炉尚未点燃。")
    idx = int(p.get("stage_index") or 0)
    if idx != 4:
        return _no("大道器劫只在第五阶段【渡劫】开放。")
    row = (p.get("stages") or [])[4]
    guards = row.setdefault("guardians", [])
    if str(doc.uid) in guards:
        return _no("你已击破本纪元的大道化身，无需重复渡劫。")
    auth = auth_mod.authority_of(doc)
    me = battle.Unit(doc.name or doc.uid[:8], int(stats.atk), int(stats.defense),
                     int(stats.hp), float(stats.bao))
    foe = battle.Unit(
        f"大道化身·{p.get('name')}",
        max(1, int(stats.atk * (1.05 + auth * 0.005))),
        max(1, int(stats.defense * 0.9)),
        max(1, int(stats.hp * 1.25)),
        float(stats.bao),
    )
    winner, _log, _hp, _ = battle.spar_full(me, foe, rng)
    if winner != 0:
        return _no("【大道器劫·未破】你的道果未能胜过大道镜像，本阶段仍可再次挑战（无惩罚）。")
    guards.append(str(doc.uid))
    st = _player(doc)
    st["traces"] = int(st.get("traces") or 0) + 1
    _save(doc, st)
    return _ok(f"【大道器劫·斩道功成】击破大道化身！渡劫镇守 {len(guards)}/{GUARD_TARGET}，"
               f"文明道痕 {st['traces']}。")


def rename(doc: Any, arg: str, w: dict[str, Any]) -> tuple[bool, str, dict[str, int]]:
    err = _owner_ok(doc, w)
    if err:
        return _no(err)
    t = w["treasure"]
    new = (arg or "").strip()
    if not new:
        return _no("格式：#大道至宝改名 新名称（1-10 字；填本名可复原）")
    if not (1 <= len(new) <= 10) or any(c in new for c in "\r\n<>"):
        return _no("名称需为 1 至 10 个字符，且不可包含换行或尖括号。")
    old = str(t.get("name") or "")
    t["name"] = new
    st = _player(doc)
    st["owned"] = new
    _save(doc, st)
    return _ok(f"【大道至宝】更名：{old} → {new}。")


def decree(doc: Any, arg: str, w: dict[str, Any]) -> tuple[bool, str, dict[str, int]]:
    err = _owner_ok(doc, w)
    if err:
        return _no(err)
    key = (arg or "").strip()
    if key not in AUTHORITIES:
        return _no("格式：#敕令大道 生死|命运|万法|世界")
    if w["treasure"].get("authorities", {}).get(key) != "完整":
        return _no(f"【{key}】权柄残缺，请先 #修复大道权柄 {key}。")
    st = _player(doc)
    st["authority"] = key
    _save(doc, st)
    return _ok(f"【敕令大道·{key}】已定为战斗开场权柄。"
               + {"生死": "一场一次复活", "命运": "必定暴击", "万法": "增伤 +25%",
                  "世界": "受伤 -35%"}[key])


def repair(doc: Any, inv: Mapping[str, int], arg: str, w: dict[str, Any]
           ) -> tuple[bool, str, dict[str, int]]:
    err = _owner_ok(doc, w)
    if err:
        return _no(err)
    key = (arg or "").strip()
    if key not in REPAIR_TARGETS:
        return _no("格式：#修复大道权柄 本体|生死|命运|万法|世界")
    t = w["treasure"]
    if key == "本体":
        if t.get("body") == "完整":
            return _no("【本体】已然完整。")
    elif t.get("authorities", {}).get(key) == "完整":
        return _no(f"【{key}】权柄已经完整。")
    lack = {k: v - int(inv.get(k, 0) or 0) for k, v in REPAIR_COST.items()
            if int(inv.get(k, 0) or 0) < v}
    if lack:
        return _no("材料不足：" + "、".join(f"{k} 缺 {v}" for k, v in lack.items()))
    if key == "本体":
        t["body"] = "完整"
    else:
        t.setdefault("authorities", {})[key] = "完整"
    t["integrity"] = min(100, int(t.get("integrity") or 0) + 20)
    return _ok(f"【修复大道权柄·{key}】已补为完整，完整度 {t['integrity']}%。",
               {k: -v for k, v in REPAIR_COST.items()})


# ── 改命 ────────────────────────────────────────────────────────────────────
def _apply_life(target: Any, now: float) -> str:
    target.ext.pop("rescue_deadline", None)
    target.ext.pop("daoshang", None)
    try:
        from . import trib
        trib.consume_revive(target, now)
    except Exception:
        pass
    try:
        from . import xtzb
        st = xtzb.ensure(target)
        for row in st.get("history") or []:
            if row.get("state") == "erased":
                row["state"] = "rewritten"
        xtzb.save(target, st)
    except Exception:
        pass
    return "生死簿上一页被抹去：寿元救援倒计时、道伤与渡劫损耗尽数消解。"


def _apply_fate(target: Any, arg: str, content: Any) -> str | None:
    rows = content.table("item/命格词条") if content else None
    pool = rows if isinstance(rows, list) else []
    hit = next((r for r in pool if str(r.get("name") or "") == arg
                or str(r.get("id") or "") == arg), None)
    if not hit:
        return None
    snap = dict(hit)
    snap["大道改写"] = True
    target.ext["mingge"] = snap
    return f"命格改写为【{snap.get('name')}】。"


def _apply_aptitude(target: Any, arg: str) -> str | None:
    if arg not in APTITUDES:
        return None
    st = _player(target)
    st["aptitude"] = arg
    _save(target, st)
    return f"天资重塑为【{arg}】：{APTITUDES[arg]}｜三维乘区 {APTITUDE_MULT[arg]:+.0%}。"


def _rewrite_apply(kind: str, arg: str, target: Any, w: dict[str, Any],
                   content: Any, now: float) -> tuple[bool, str]:
    if kind == "life":
        return True, _apply_life(target, now)
    if kind == "fate":
        msg = _apply_fate(target, arg, content)
        return (True, msg) if msg else (False, f"没有名为【{arg}】的命格词条。")
    msg = _apply_aptitude(target, arg)
    return (True, msg) if msg else (False, "天资名须为十级之一（见 #大道炼器规则）。")


def rewrite(doc: Any, target: Any, arg: str, kind: str, w: dict[str, Any],
            content: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    key = {"life": "生死", "fate": "命运", "apt": "命运"}[kind]
    err = _authority_ok(doc, w, key)
    if err:
        return _no(err)
    cost = {"life": COST_LIFE, "fate": COST_FATE,
            "apt": COST_APT_TOP if (arg or "").strip() == "无演无尽" else COST_APT}[kind]
    if kind == "apt" and (arg or "").strip() not in APTITUDES:
        return _no("格式：#重塑天资 " + "|".join(APTITUDES))
    if kind == "fate" and not (arg or "").strip():
        return _no("格式：#改写命格 命格名 [@目标]")
    if int(w["treasure"].get("origin") or 0) < cost:
        return _no(f"文明本源不足，当前 {int(w['treasure'].get('origin') or 0)}/{MAX_ORIGIN}（需 {cost}）。")
    if target is not None and str(target.uid) != str(doc.uid):
        w.setdefault("invites", {})[str(target.uid)] = {
            "by": str(doc.uid), "kind": kind, "arg": arg, "exp": now + INVITE_SECONDS,
        }
        return _ok(f"已向【{target.name or target.uid[:8]}】发出大道改命邀请（{kind}，"
                   f"耗 {cost} 本源）。请对方在 {int(INVITE_SECONDS)} 秒内发 #同意大道改命 生效。")
    err = _spend(w, cost)
    if err:
        return _no(err)
    who = target if target is not None else doc
    ok, msg = _rewrite_apply(kind, arg, who, w, content, now)
    if not ok:
        w["treasure"]["origin"] = int(w["treasure"]["origin"]) + cost   # 回滚本源
        return _no(msg)
    st = _player(doc)
    st.setdefault("rewrites", []).append({"kind": kind, "target": str(who.uid), "at": now})
    _save(doc, st)
    return _ok(f"【大道改命·{kind}】耗 {cost} 本源。\n{msg}")


def accept_rewrite(doc: Any, w: dict[str, Any], content: Any, now: float
                   ) -> tuple[bool, str, dict[str, int]]:
    inv = (w.get("invites") or {}).pop(str(doc.uid), None)
    if not inv:
        return _no("当前没有等待确认的大道改命邀请。")
    if float(inv.get("exp") or 0) <= now:
        return _no("大道改命邀请已经消散。")
    kind = inv.get("kind")
    cost = {"life": COST_LIFE, "fate": COST_FATE,
            "apt": COST_APT_TOP if inv.get("arg") == "无演无尽" else COST_APT}.get(kind, COST_LIFE)
    err = _spend(w, cost)
    if err:
        return _no(err)
    ok, msg = _rewrite_apply(str(kind), str(inv.get("arg") or ""), doc, w, content, now)
    if not ok:
        w["treasure"]["origin"] = int(w["treasure"]["origin"]) + cost
        return _no(msg)
    return _ok(f"【同意大道改命】已应允器主之请（耗 {cost} 本源）。\n{msg}")


def deduce(doc: Any, arg: str, w: dict[str, Any]) -> tuple[bool, str, dict[str, int]]:
    err = _owner_ok(doc, w)
    if err:
        return _no(err)
    parts = (arg or "").split()
    if not parts:
        return _no("格式：#推演终极功法 功法名 [攻伐|护道|轮回|悟道]")
    name = parts[0]
    kind = parts[1] if len(parts) > 1 and parts[1] in TECH_TYPES else "悟道"
    err = _spend(w, COST_TECH, "ultimate-technique")
    if err:
        return _no(err)
    st = _player(doc)
    st["technique"] = {"name": name, "type": kind}
    _save(doc, st)
    w["treasure"]["ultimate_technique"] = name
    return _ok(f"【推演终极功法】耗 {COST_TECH} 本源，《{name}》（{kind}）成书，"
               "此后战斗出手伤害 +20%。")


def create_world(doc: Any, arg: str, w: dict[str, Any]) -> tuple[bool, str, dict[str, int]]:
    err = _owner_ok(doc, w)
    if err:
        return _no(err)
    name = (arg or "").strip()
    if not (1 <= len(name) <= 10) or any(c in name for c in "\r\n<>"):
        return _no("格式：#开辟大道界 界名（1-10 字）")
    err = _spend(w, COST_WORLD, "dao-world")
    if err:
        return _no(err)
    st = _player(doc)
    st["dao_world"] = name
    _save(doc, st)
    w["treasure"]["dao_world"] = name
    return _ok(f"【开辟大道界】耗 {COST_WORLD} 本源，【{name}】自成位面，"
               "器主此后受伤 -15%。")


# ── 消费点（装备聚合 / 战斗装配 / 秘境投放） ─────────────────────────────────
def bonus(doc: Any) -> tuple[float, float, float]:
    """成器至宝给 aggregate 的 (flat 三维, 全属性比例, 暴击)，按完整度缩放。"""
    st = _player(doc)
    if not st.get("owned"):
        return 0.0, 0.0, 0.0
    scale = max(0.2, min(1.0, float((doc.ext.get("dt_integrity") or 100)) / 100))
    return FLAT_ALL * scale, RATIO_ALL * scale, BAO_FLAT * scale


def combat(doc: Any) -> dict[str, Any]:
    """战斗装配出口：敕令权柄（须完整）+ 终极功法 + 大道界 + 天资。"""
    st = _player(doc)
    if not st.get("owned"):
        return {}
    out: dict[str, Any] = {"dealt": 0.0, "taken": 0.0, "crit": False, "revive": False}
    key = str(st.get("authority") or "")
    full = doc.ext.get("dt_authorities") or {}
    if key and full.get(key) == "完整":
        if key == "生死":
            out["revive"] = True
        elif key == "命运":
            out["crit"] = True
        elif key == "万法":
            out["dealt"] += 0.25
        elif key == "世界":
            out["taken"] += 0.35
    if isinstance(st.get("technique"), dict):
        out["dealt"] += 0.20
    if st.get("dao_world"):
        out["taken"] += 0.15
    apt = str(st.get("aptitude") or "")
    if apt in APTITUDE_MULT:
        out["dealt"] += APTITUDE_MULT[apt]
    return out


def sync_treasure(doc: Any, w: Mapping[str, Any]) -> None:
    """每次 dispatch 把全服至宝的完整度 / 权柄完整状态镜像进玩家档，
    使 aggregate / build_fighter 这类纯读函数无需接触全服状态。"""
    t = w.get("treasure")
    if isinstance(t, dict) and str(t.get("owner_id")) == str(doc.uid):
        doc.ext["dt_integrity"] = int(t.get("integrity") or 0)
        doc.ext["dt_authorities"] = dict(t.get("authorities") or {})
    else:
        doc.ext.pop("dt_integrity", None)
        doc.ext.pop("dt_authorities", None)


def roll_drop(rng: random.Random) -> dict[str, int] | None:
    """秘境结算 12% 成批投放燃料（原版四种燃料无发放点，本移植补通道）。"""
    if rng.random() >= 0.12:
        return None
    name = rng.choices(tuple(FUEL), weights=(60, 25, 12, 3), k=1)[0]
    qty = {"众生念力": rng.randint(10, 30), "鸿蒙道火": rng.randint(2, 6),
           "界核": rng.randint(1, 3), "宇宙核心": 1}[name]
    return {name: qty}
