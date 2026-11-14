"""无尽轮回·剧情组（W16-F2）——原版 `apps/EndlessReincarnation.js` +
`model/endlessReincarnation.js`（雾海市末班车无限列车）的纯函数移植。
注意与 `core/reincarnation.py`（轮回路执掌/遗落纳戒）是两个系统。

原版结构：#开启无尽轮回 4 选 1 职业 → 场景 3 选 1（属性检定）→ 压力/点数
累积 → 9 档结局（D 120 → SSS 9600）→ #轮回强化（潜能 600/次）/ #轮回兑换
（12 项道具）→ #退出无尽轮回 开新档。

本移植（shortcut）：
- 场景压缩为 5 幕（原版更多），每幕 3 选 1，检定 = 特长属性 + rng；
  压力 ≥100 强制结局 D；点数阈值 120/180/600/900/1400/2200/3400/5600/9600
  对应 D/C+/B/A/S/SS/SSS 三段共 9 档评价（名字压缩）。
- #轮回任务（每日悬赏文案）/#轮回小队（NPC 队友）/#轮回怪物（图鉴）/
  #轮回档案（历史最高）为只读面板；强化/兑换持久化在 ext。
- points 为跨局可用钱包，run_points 只用于单局评价；结算只入账本局新赚点数，
  保留权限的开局底分不重复入账。旧档在第一次成功操作时随保存惰性迁移。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

EXT_KEY = "reinc_story"

PROFESSIONS = ("老兵", "学生", "医生", "黑客")
SPECIALTY = {"老兵": "体术", "学生": "心智", "医生": "心智", "黑客": "源能"}
STRESS_CAP = 100

# (幕名, [(选项, 检定属性, 难度, 成功点数, 失败点数, 成功文案, 失败文案)])
SCENES: tuple[tuple[str, tuple[tuple[str, str, int, int, int, str, str], ...]], ...] = (
    ("末班车进站", (
        ("翻窗上车", "体术", 6, 120, 40, "你翻身上车，车门在身后轰然闭合。", "玻璃划破手臂，你滚进车厢——狼狈，但活着。"),
        ("刷旧月卡", "心智", 5, 120, 40, "闸机竟然认了这张三年前的卡。", "闸机死闭。你跟着人流挤了上去。"),
        ("尾行列车员", "源能", 7, 160, 30, "你借着他的权限卡混入首节车厢。", "被电了个趔趄，你爬上了末节。"),
    )),
    ("雾海隧道", (
        ("熄灯静坐", "心智", 6, 200, 60, "雾中有什么绕行了三圈，最终离去。", "它记住了你的呼吸声。压力徒增。"),
        ("点燃信号弹", "体术", 5, 180, 80, "红光撕开浓雾， tunnel 短暂属于人类。", "火光引来了更糟的东西。"),
        ("接入列车电网", "源能", 6, 220, 50, "你让整列车的灯重新亮起。", "电网反噬，你昏迷了三站。"),
    )),
    ("永夜站台", (
        ("与站务员对答案", "心智", 7, 300, 80, "你答对了——站台承认你 existed。", "答案错了。站台的灯一盏盏熄灭。"),
        ("肉身堵门", "体术", 8, 340, 60, "门在你面前认输。", "门没认输，你被夹得很惨。"),
        ("黑入广播系统", "源能", 7, 320, 70, "整座站台听到了真话。", "广播只放出了杂音。"),
    )),
    ("回声车厢", (
        ("直面过去的自己", "心智", 8, 450, 100, "你与自己对坐，谁也没有先眨眼。", "你输给了自己。压力失控。"),
        ("背刺回声", "体术", 7, 400, 120, "回声消散前笑了：'这才是你。'", "它闪开了，并记住了这一刀。"),
        ("改写车厢播报", "源能", 8, 470, 90, "到站语音被你改成了出口。", "播报循环卡死，噪音响彻。"),
    )),
    ("终点站·雾海市", (
        ("按下发车杆", "源能", 9, 800, 200, "列车驶入永不存在的下一站。", "发车杆纹丝不动。"),
        ("带全车人突围", "体术", 9, 900, 150, "你把所有人带出了站台。", "人流冲散了队伍。"),
        ("与列车长对弈", "心智", 10, 960, 180, "你赢了半子——列车长起身让座。", "你输了。棋盘上写着你的名字。"),
    )),
)

ENDINGS: tuple[tuple[str, int], ...] = (
    ("SSS·清醒者", 9600), ("SS·破雾人", 5600), ("S·列车之友", 3400),
    ("A·幸存者", 2200), ("B·同行者", 1400), ("C+·末班车客", 900),
    ("C·雾中人", 600), ("D+·梦游者", 180), ("D·抹杀", 120),
)
ENHANCE_COST = 600
ENHANCE_ATTRS = ("体术", "心智", "源能")
EXCHANGES: tuple[tuple[str, int, str], ...] = (
    ("基因稳定剂·C", 1200, "压力上限 +20"),
    ("神经加速器·B", 2600, "检定 +1（永久）"),
    ("再生因子·A", 5200, "一次濒死挽回（自动触发）"),
    ("世界线锚定·SS", 16000, "结局评价 +一档"),
    ("轮回者权限·SSS", 30000, "开启无尽轮回保留 20% 点数"),
)


def _defaults() -> dict[str, Any]:
    return {"active": False, "job": "", "scene": 0, "stress": 0, "points": 0,
            "run_points": 0, "run_start_points": 0,
            "attrs": {"体术": 0, "心智": 0, "源能": 0}, "grade": "", "best": 0,
            "history": [], "keep_ratio": 0.0, "extra_cap": 0, "check_bonus": 0,
            "revive": False, "rank_up": False}


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
    for k in ("scene", "stress", "points", "best", "extra_cap", "check_bonus"):
        st[k] = int(st.get(k, 0) or 0)
    if not isinstance(st.get("attrs"), dict):
        st["attrs"] = {"体术": 0, "心智": 0, "源能": 0}
    if not isinstance(st.get("history"), list):
        st["history"] = []
    st["active"] = bool(st.get("active"))
    if not isinstance(raw, dict) or "run_points" not in raw:
        # 旧活跃档的余额尚未结算；旧非活跃档已结算，不能再次发放。
        last = st["history"][-1] if st["history"] else {}
        last_points = last.get("points", 0) if isinstance(last, dict) else 0
        st["run_points"] = st["points"] if st["active"] else last_points
        if st["active"]:
            st["points"] = 0
    st["run_points"] = max(0, int(st.get("run_points", 0) or 0))
    st["run_start_points"] = max(0, int(st.get("run_start_points", 0) or 0))
    st["points"] = max(0, st["points"])
    st["revive"] = bool(st.get("revive"))
    st["rank_up"] = bool(st.get("rank_up"))
    return st


def grade_of(points: int) -> str:
    name = ENDINGS[-1][0]
    for g, th in ENDINGS:
        if points >= th:
            name = g
            break
    return name


def start(doc: PlayerDoc, job: str) -> tuple[bool, str]:
    st = state_of(doc)
    if st["active"]:
        return False, "你已身处雾海市末班车——#轮回选择 继续。"
    job = (job or "").strip()
    if job not in PROFESSIONS:
        return False, ("用法：#开启无尽轮回 老兵/学生/医生/黑客\n"
                       "（特长：体术/心智/心智/源能）")
    kept = int(st["run_points"] * float(st.get("keep_ratio", 0) or 0))
    st.update({"active": True, "job": job, "scene": 0, "stress": 0,
               "run_points": kept, "run_start_points": kept, "grade": ""})
    save(doc, st)
    return True, (f"【无尽轮回 · 开启】雾海市，末班车，23:44。\n"
                  f"你的身份：{job}（特长 {SPECIALTY[job]}）\n"
                  "第一幕：#轮回选择 1~3。")


def choose(doc: PlayerDoc, pick: int, now: float | None = None,
           rng: random.Random | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    if not st["active"]:
        return False, "不在轮回之中——#开启无尽轮回 职业。"
    if st["scene"] >= len(SCENES):
        return False, "列车已到终点——#退出无尽轮回 结算评价。"
    sname, options = SCENES[st["scene"]]
    if not (1 <= pick <= len(options)):
        return False, f"用法：#轮回选择 1~{len(options)}。"
    text, attr, diff, p_win, p_lose, win_msg, lose_msg = options[pick - 1]
    value = int(st["attrs"].get(attr, 0) or 0) + int(st.get("check_bonus", 0) or 0)
    ok = (value + int(rng.random() * 10) + 1) >= diff
    st["run_points"] += p_win if ok else max(0, p_lose - 0)
    stress_gain = 8 if ok else 20
    st["stress"] = min(STRESS_CAP + st.get("extra_cap", 0), st["stress"] + stress_gain)
    st["scene"] += 1
    grade_hit = False
    if st["stress"] >= STRESS_CAP and st["scene"] < len(SCENES):
        grade_hit = True
    save(doc, st)
    head = f"【{sname} · {text}】{'成功' if ok else '失败'}（{attr} 检定 {value}+1d10 vs {diff}）"
    body = win_msg if ok else lose_msg
    tail = f"本局点数 {st['run_points']}｜可用点数 {st['points']}｜压力 {st['stress']}/{STRESS_CAP + st.get('extra_cap', 0)}"
    if grade_hit:
        return True, f"{head}\n{body}\n{tail}\n压力爆表——你被列车抹除了。#退出无尽轮回 结算。"
    if st["scene"] >= len(SCENES):
        tail += "\n终点已至——#退出无尽轮回 结算评价。"
    return True, f"{head}\n{body}\n{tail}"


def settle(doc: PlayerDoc) -> tuple[bool, str]:
    st = state_of(doc)
    if not st["active"]:
        return False, "不在轮回之中。"
    st["active"] = False
    earned = max(0, st["run_points"] - st["run_start_points"])
    st["points"] += earned
    pts = st["run_points"]
    if st.get("rank_up"):
        idx = next((i for i, (_, th) in enumerate(ENDINGS) if pts >= th), len(ENDINGS) - 1)
        pts = ENDINGS[max(0, idx - 1)][1]
    grade = grade_of(pts)
    st["grade"] = grade
    st["best"] = max(int(st.get("best", 0) or 0), pts)
    st["history"] = (list(st.get("history") or []) + [{"grade": grade, "points": pts,
                                                       "ts": int(time.time())}])[-10:]
    save(doc, st)
    return True, (f"≡≡≡ 无尽轮回 · 结算 ≡≡≡\n评价：【{grade}】（{pts:,} 点）\n"
                  f"本次获得：{earned:,} 点｜可用点数：{st['points']:,}｜历史最高：{st['best']:,} 点\n"
                  "#轮回强化 / #轮回兑换 使用可用点数，"
                  "#开启无尽轮回 再入列车。")


def enhance(doc: PlayerDoc, attr: str) -> tuple[bool, str]:
    st = state_of(doc)
    if attr not in ENHANCE_ATTRS:
        return False, "用法：#轮回强化 体术/心智/源能（600 点/次，上限 10）。"
    cur = int(st["attrs"].get(attr, 0) or 0)
    if cur >= 10:
        return False, f"【{attr}】已臻化境（10/10）。"
    if st["points"] < ENHANCE_COST:
        return False, f"潜能点不足：需 {ENHANCE_COST}（现有 {st['points']}）。"
    st["points"] -= ENHANCE_COST
    st["attrs"][attr] = cur + 1
    save(doc, st)
    return True, f"【轮回强化 · {attr}】{cur} → {cur + 1}（消耗 {ENHANCE_COST} 点）。"


def exchange(doc: PlayerDoc, name: str) -> tuple[bool, str]:
    st = state_of(doc)
    row = next((r for r in EXCHANGES if r[0] == (name or "").strip()), None)
    if row is None:
        lines = "\n".join(f"· {n}｜{c:,} 点｜{eff}" for n, c, eff in EXCHANGES)
        return False, "--- 轮回兑换 ---\n" + lines + "\n用法：#轮回兑换 名称"
    n, cost, eff = row
    if st["points"] < cost:
        return False, f"点数不足：{n} 需 {cost:,}（现有 {st['points']}）。"
    st["points"] -= cost
    if n.startswith("基因稳定剂"):
        st["extra_cap"] = int(st.get("extra_cap", 0) or 0) + 20
    elif n.startswith("神经加速"):
        st["check_bonus"] = int(st.get("check_bonus", 0) or 0) + 1
    elif n.startswith("再生因子"):
        st["revive"] = True
    elif n.startswith("世界线锚定"):
        st["rank_up"] = True
    elif n.startswith("轮回者权限"):
        st["keep_ratio"] = 0.2
    save(doc, st)
    return True, f"【轮回兑换 · {n}】{eff}（消耗 {cost:,} 点）。"


def panel(doc: Any) -> str:
    st = state_of(doc)
    sname = SCENES[st["scene"]][0] if st["active"] and st["scene"] < len(SCENES) else "—"
    return "\n".join([
        "--- 无尽轮回 · 档案 ---",
        f"状态：{'进行中' if st['active'] else '未在轮回'}｜身份：{st.get('job') or '—'}"
        f"｜当前幕：{sname}",
        f"可用点数 {st['points']:,}｜本局点数 {st['run_points']:,}｜压力 {st['stress']}/{STRESS_CAP + st.get('extra_cap', 0)}"
        f"｜属性 {st['attrs']}",
        f"最高评价：{grade_of(st['best'])}（{st['best']:,} 点）｜最近：{st['grade'] or '—'}",
        "指令：#开启无尽轮回 职业 / #轮回选择 1~3 / #退出无尽轮回 / "
        "#轮回强化 / #轮回兑换 / #轮回任务 / #轮回小队 / #轮回怪物 / #轮回属性",
    ])


def task_text(doc: Any, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    st = state_of(doc)
    jobs = ("给三号车厢的影子送信", "找回丢失的第七节车厢", "替站长撒一个谎",
            "在雾里数清乘客的人数", "把一段记忆押送给对面的自己")
    return "\n".join(["--- 轮回任务（今日悬赏）---"]
                     + [f"· {t}（报酬 {rng.randint(80, 240)} 点）" for t in rng.sample(list(jobs), 3)])


def squad_text() -> str:
    return "\n".join([
        "--- 轮回小队 ---",
        "· 陈默（老兵）：枪法严整，寡言，替所有人断后",
        "· 周苓（医生）：缝合包随身，拒绝放弃任何一人",
        "· 阿鬼（黑客）：耳机不离头，声称听得见列车的想法",
    ])


def monster_text() -> str:
    return "\n".join([
        "--- 轮回怪物图鉴 ---",
        "· 雾枭：模仿人声，只在你回头时存在",
        "· 查票员：查的不是票，是你上车的理由",
        "· 十六号乘客：永远坐在你没选的座位上",
        "· 脱轨者：由半途下车者拧成的长影",
    ])
