"""W8-F7 宗门深化：洞天福地 / 灵脉 / 护宗大阵 / 弟子运营（纯函数，无 IO）。

对齐原版 `apps/Association/`（BlessPlace / AssociationAdmin / SectDisciples）：
- 原版宗门是 `resources/data/association/<宗门名>.json` 整档，本移植把深化字段挂
  `calamity_state["sect_deep"][宗门名]`，**宗门灵石池直接复用 sects.fund**（与捐赠/升级/俸禄天然联动），
  db 恒 v17，不新增列。
- 原版「仙宗 power=1 / 凡宗 power=0」分野本移植无对应底座，一律去掉：
  维护倍率恒 5、池上限不 ×10、门槛不钳 41/42（改钳到本移植境界上限）。
- 原版 cron 每日运营 → 本移植惰性 `operate()`，由每个本组指令入口触发。

本模块所有函数只改传入的 dict，不碰 DB / 不 await；返回值里的 fund 变动由调用方统一落库。
"""

from __future__ import annotations

import time
from typing import Any

# ---- 原版常量（1:1） ----

POOL_CAP = (2_000_000, 5_000_000, 8_000_000, 11_000_000,
            15_000_000, 20_000_000, 25_000_000, 30_000_000)
ARRAY_HP_INIT = 114514          # 原版 `大阵血量: 114514 * xian`
ARRAY_HP_PER_STONE = 5          # 原版「#维护护宗大阵」：1 灵石 → 5 点大阵血量
UPKEEP_SECONDS = 7 * 86400      # 原版 CD.association = 7 天
UPKEEP_PER_LEVEL = 50_000       # 原版 `宗门等级 * 50000`
BUILD_COST_PER_LEVEL = 10_000   # 原版 `建设等级 * 10000`
VEIN_BASE = 1200                # 原版 `1200 * 洞天.level * level_id / 2 * 2`

SPECIALTIES = ("采药", "炼丹", "炼器", "阵法", "护山", "外务")
APTITUDE_POOL = (("平庸之资", 60), ("超凡资质", 23), ("天纵之资", 10),
                 ("旷世奇才", 5), ("绝世天骄", 2))
ROOT_TYPE_WEIGHT = {
    "大道体": 0.00001, "至尊体": 0.0001, "圣体": 0.0009, "霸体": 0.001,
    "神王体": 0.0011, "道胎": 0.0012, "神体": 0.002, "妖体": 0.005,
    "天灵根": 0.08, "变异灵根": 0.05, "体质": 0.2, "真灵根": 0.29, "伪灵根": 0.36869,
}
SURNAME = ("沈", "顾", "陆", "苏", "叶", "萧", "楚", "姜", "宁", "林")
GIVEN = ("清", "玄", "长", "昭", "云", "星", "宁", "寒", "月", "川", "瑶", "离")
SPECIALTY_RATE = {"采药": 1.0, "炼丹": 1.15, "炼器": 1.1,
                  "阵法": 1.08, "护山": 1.05, "外务": 1.2}
SPECIALTY_ROOT_KEYS = {
    "采药": ("木", "水", "草", "生命"), "炼丹": ("火", "木", "阴", "阳"),
    "炼器": ("金", "火", "雷", "器"), "阵法": ("土", "水", "空", "道"),
    "护山": ("土", "金", "霸", "体"), "外务": ("风", "雷", "光", "暗", "时"),
}
DAY_SECONDS = 86400
OPERATE_MAX_DAYS = 7
DISCIPLE_TRAIN_MAX = 5

MANAGE_ROLES = ("宗主", "副宗主", "长老")


# ---- 状态存取 ----

def ensure(s: dict) -> dict:
    """补齐宗门深化档字段（就地）。"""
    s.setdefault("place", "")             # 宗门驻地（洞天名）
    s.setdefault("build", 0)              # 宗门建设等级
    s.setdefault("array_hp", ARRAY_HP_INIT)
    s.setdefault("upkeep_at", 0.0)        # 上次宗门维护时间
    s.setdefault("gate", 0)               # 最低加入境界（realm_index，0=不限）
    s.setdefault("beast", "")             # 宗门神兽
    s.setdefault("disciples", [])         # 宗门弟子
    s.setdefault("disciple_seq", 0)
    s.setdefault("store", {"药材": 0, "丹药": 0, "法器": 0})
    s.setdefault("reputation", 0)
    s.setdefault("ops_at", 0.0)           # 宗门运营上次结算
    s.setdefault("ops_streak", 0)
    s.setdefault("ops_log", [])           # 最近 10 条运营回执
    s["build"] = max(0, int(s["build"] or 0))
    s["array_hp"] = max(0, int(s["array_hp"] or 0))
    s["reputation"] = max(0, int(s["reputation"] or 0))
    s["gate"] = max(0, int(s["gate"] or 0))
    s["disciple_seq"] = max(0, int(s["disciple_seq"] or 0))
    if not isinstance(s["disciples"], list):
        s["disciples"] = []
    if not isinstance(s["store"], dict):
        s["store"] = {"药材": 0, "丹药": 0, "法器": 0}
    for k in ("药材", "丹药", "法器"):
        s["store"][k] = max(0, int(s["store"].get(k) or 0))
    if not isinstance(s["ops_log"], list):
        s["ops_log"] = []
    return s


def state_of(cal: dict, name: str) -> dict:
    """取（并就地登记）某宗门的深化档，返回可写引用。"""
    root = cal.setdefault("sect_deep", {})
    if not isinstance(root, dict):
        root = {}
        cal["sect_deep"] = root
    s = root.get(name)
    if not isinstance(s, dict):
        s = {}
        root[name] = s
    return ensure(s)


def commit(cal: dict, name: str, s: dict) -> None:
    cal.setdefault("sect_deep", {})[name] = ensure(s)


def personal_of(doc) -> dict:
    """玩家侧：贡献度复用既有 `ext["sect_contrib"]`（宗门商店消费者），
    灵脉日戳挂 `ext["sect_deep"]["vein_day"]`，避免重复建账。"""
    s = doc.ext.get("sect_deep")
    if not isinstance(s, dict):
        s = {}
    s.setdefault("vein_day", "")
    s["contribution"] = int(doc.ext.get("sect_contrib") or 0)
    return s


def commit_personal(doc, s: dict) -> None:
    doc.ext["sect_deep"] = {"vein_day": s.get("vein_day", "")}
    doc.ext["sect_contrib"] = int(s.get("contribution") or 0)


def day_key(ts: float) -> str:
    """UTC+8 自然日，用于每日一次判定。"""
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts) + 8 * 3600))


def pool_cap(level: int) -> int:
    return POOL_CAP[min(max(int(level), 1), len(POOL_CAP)) - 1]


def find_bless(rows: list[dict], name: str) -> dict | None:
    for r in rows or []:
        if str(r.get("name") or "") == str(name or "").strip():
            return r
    return None


def bless_lines(rows: list[dict], cal: dict) -> list[str]:
    """洞天福地列表 + 归属（纯展示）。"""
    owners: dict[str, str] = {}
    for sect, st in (cal.get("sect_deep") or {}).items():
        if isinstance(st, dict) and st.get("place"):
            owners[str(st["place"])] = sect
    lines = ["--- 洞天福地（15 处） ---"]
    for r in rows or []:
        nm = str(r.get("name") or "?")
        lines.append(f"· {nm}｜{r.get('level', 0)} 阶｜效率 {r.get('efficiency', 0)}｜"
                     f"{('【' + owners[nm] + '】占据') if nm in owners else '无主'}")
    lines.append("宗主可发「#入驻洞天 名称」占据无主洞天，或向有主洞天发起抢夺。")
    return lines


def holder_of(cal: dict, place: str, me: str) -> str | None:
    for sect, st in (cal.get("sect_deep") or {}).items():
        if sect != me and isinstance(st, dict) and st.get("place") == place:
            return sect
    return None


# ---- 洞天入驻 / 抢夺（原版 Settled_Blessed_Place） ----

def settle(cal: dict, row: dict, name: str, my_power: int,
           my_s: dict, holder_power: int, now: float, rng: Any) -> tuple[bool, str]:
    """入驻洞天。无主直接占；有主则按原版战力公式抢夺。

    原版：攻方 = Σ(攻击+血量×0.5) + 建设×100 + 己方大阵/2，
          守方 = Σ(防御+血量×0.5) + 建设×100 + 对方大阵，双方各 ±10% 随机。
    本移植 `_sect_power` 聚合的是 atk+defense+hp（不分攻防），故用随机系数代两侧属性拆分。
    返回 (是否易主/入驻成功, 文案)。cal 内的宗门档会被就地修改。
    """
    s = ensure(my_s)
    place = str(row.get("name") or "")
    if not place:
        return False, "未指定洞天，可发「#洞天福地列表」查看。"
    if s["place"] == place:
        return False, "本宗已驻此地，不必拆了重建。"
    holder = holder_of(cal, place, name)
    if not holder:
        s["place"], s["build"] = place, 0
        return True, f"入驻成功，「{name}」当前驻地为：{place}。"
    hs = state_of(cal, holder)
    atk = int(my_power * (0.9 + 0.2 * rng.random()) + s["build"] * 100 + s["array_hp"] / 2)
    dfn = int(holder_power * (0.9 + 0.2 * rng.random()) + hs["build"] * 100 + hs["array_hp"])
    if atk <= dfn:
        return False, (f"「{name}」攻伐「{holder}」驻地 {place}，造成 {atk:,} 攻势，"
                       f"却被 {dfn:,} 的护宗大阵尽数挡回。")
    old_build = hs["build"]
    hs["place"] = s["place"]              # 原版：败方接手攻方旧驻地
    hs["build"] = max(0, old_build - 10)
    hs["array_hp"] = 0
    s["place"], s["build"] = place, old_build
    commit(cal, name, s)
    commit(cal, holder, hs)
    return True, (f"「{name}」以 {atk:,} 攻势破去「{holder}」{dfn:,} 防御，一举夺下 {place}！"
                  f"建设度继承 {old_build}，对方建设度降为 {hs['build']}、大阵尽碎。")


# ---- 灵脉 / 建设 / 大阵 / 维护 / 门槛 ----

def vein(doc, s: dict, rows: list[dict], fund: int, level: int,
         now: float) -> tuple[bool, str, int, int]:
    """开采灵脉。返回 (ok, msg, 玩家灵石, 宗门池增量)。

    原版 `gift_lingshi = 1200 × 洞天.level × level_id / 2 × 2`；麒麟改用 level+1。
    文案称「上交一半」，实现却是玩家全额入袋、宗门池再加全额（双份）—— 本移植照实现 1:1。
    """
    p = personal_of(doc)
    key = day_key(now)
    if p["vein_day"] == key:
        return False, "今日已经开采过灵脉，不可竭泽而渔，明天再来。", 0, 0
    s = ensure(s)
    if not s["place"]:
        return False, "本宗尚无驻地，没有灵脉可采。可发「#入驻洞天 名称」先立驻地。", 0, 0
    row = find_bless(rows, s["place"]) or find_bless(rows, "昆仑山") or {"level": 5}
    lv = int(row.get("level") or 5) + (1 if s["beast"] == "麒麟" else 0)
    gain = int(VEIN_BASE * lv * (max(0, int(doc.realm_index)) + 1))
    pool_add = max(0, min(gain, pool_cap(level) - max(0, int(fund))))
    p["vein_day"] = key
    p["contribution"] = int(p["contribution"] or 0) + gain
    commit_personal(doc, p)
    return True, (f"开采「{s['place']}」灵脉：入袋 {gain:,} 灵石，宗门灵石池 +{pool_add:,}"
                  f"（池上限 {pool_cap(level):,}）。个人贡献 +{gain:,}。"), gain, pool_add


def build(s: dict, fund: int, realm_index: int) -> tuple[bool, str, int, int]:
    """建设宗门：扣 `建设等级 × 10000`，建设度 +`(realm_index // 7 + 1)`。"""
    s = ensure(s)
    if not s["place"]:
        return False, "本宗尚无驻地，无法建设。", 0, 0
    cost = s["build"] * BUILD_COST_PER_LEVEL
    if int(fund) < cost:
        return False, f"宗门灵石池不足，还需 {cost:,} 灵石。", 0, 0
    add = max(0, int(realm_index)) // 7 + 1
    s["build"] += add
    return True, (f"【宗门·建设】消耗宗门灵石 {cost:,}，建设度 +{add}（当前 {s['build']}）。"
                  "建设度可提升洞天抢夺攻势。"), cost, add


def array_fix(s: dict, fund: int, amount: int) -> tuple[bool, str, int, int]:
    """维护护宗大阵：池扣 X，大阵血量 +5X。"""
    s = ensure(s)
    amount = int(amount)
    if amount <= 0:
        return False, "格式：「#维护护宗大阵 数量」（灵石数须为正整数）。", 0, 0
    if int(fund) < amount:
        return False, f"宗门灵石池只有 {int(fund):,} 灵石，数量不足。", 0, 0
    hp_add = amount * ARRAY_HP_PER_STONE
    s["array_hp"] += hp_add
    return True, (f"维护成功：灵石池 −{amount:,}，护宗大阵 +{hp_add:,} 血量"
                  f"（当前 {s['array_hp']:,}）。"), amount, hp_add


def upkeep(s: dict, fund: int, level: int, now: float) -> tuple[bool, str, int]:
    """宗门维护：7 天一次，扣 `宗门等级 × 50000`。"""
    s = ensure(s)
    left = UPKEEP_SECONDS - (float(now) - float(s["upkeep_at"] or 0))
    if left > 0 and s["upkeep_at"]:
        return False, f"当前无需维护，{int(left // 3600)} 小时后可再维护。", 0
    cost = max(1, int(level)) * UPKEEP_PER_LEVEL
    if int(fund) < cost:
        return False, f"宗门维护需 {cost:,} 灵石，本宗灵石池储量不足。", 0
    s["upkeep_at"] = float(now)
    return True, f"宗门维护成功，扣除 {cost:,} 灵石，七日后需再维护。", cost


def set_gate(s: dict, gate: int, max_realm: int) -> tuple[bool, str]:
    """设置最低加入境界（realm_index）。原版凡宗钳 41 / 仙宗钳 ≥42，本移植改钳境界上限。"""
    s = ensure(s)
    gate = int(gate)
    if gate < 0 or gate > int(max_realm):
        return False, f"门槛须在 1~{int(max_realm)} 境之间（0 表示不限）。"
    s["gate"] = gate
    return True, ("已取消加入门槛。" if gate == 0 else f"已设置宗门门槛：第 {gate} 境。")


def gate_of(s: dict) -> int:
    return max(0, int(ensure(s).get("gate") or 0))


# ---- 宗门弟子 / 运营（原版 model/sectDisciples.js） ----

def disciple_capacity(level: int) -> int:
    return max(3, max(1, int(level)) * 3)


def recruit_cost(level: int) -> int:
    return 10_000 + max(1, int(level)) * 5_000


def affinity(root: dict, specialty: str) -> float:
    nm = str((root or {}).get("name") or "")
    return 1.25 if any(k in nm for k in SPECIALTY_ROOT_KEYS.get(specialty, ())) else 1.0


def _weighted(pairs: list[tuple[Any, float]], rng: Any) -> Any:
    total = sum(max(0.0, float(w)) for _, w in pairs)
    if total <= 0:
        return pairs[0][0]
    cursor = rng.random() * total
    for item, w in pairs:
        cursor -= max(0.0, float(w))
        if cursor < 0:
            return item
    return pairs[-1][0]


def _pick(seq, rng: Any):
    return seq[max(0, min(len(seq) - 1, int(rng.random() * len(seq))))]


def _pick_root(roots: list[dict], rng: Any) -> dict:
    usable = [r for r in (roots or []) if isinstance(r, dict)
              and not r.get("唯一灵根") and not r.get("不可随机获取")]
    if not usable:
        usable = [{"name": "伪灵根", "type": "伪灵根"}]
    groups: dict[str, list[dict]] = {}
    for r in usable:
        groups.setdefault(str(r.get("type") or "伪灵根"), []).append(r)
    pairs = [(t, ROOT_TYPE_WEIGHT.get(t, 0.01)) for t in groups]
    t = _weighted(pairs, rng)
    row = _pick(groups.get(t) or usable, rng)
    return {"name": str(row.get("name") or "无名灵根"), "type": str(row.get("type") or t)}


def recruit(s: dict, fund: int, level: int, roots: list[dict],
            now: float, rng: Any) -> tuple[bool, str, int, dict | None]:
    s = ensure(s)
    if len(s["disciples"]) >= disciple_capacity(level):
        return False, "宗门弟子名额已满，请先「#升级宗门」扩编。", 0, None
    cost = recruit_cost(level)
    if int(fund) < cost:
        return False, f"宗门灵石池不足，招募需 {cost:,} 灵石。", 0, None
    s["disciple_seq"] += 1
    root = _pick_root(roots, rng)
    spec = _pick(SPECIALTIES, rng)
    d = {
        "id": s["disciple_seq"],
        "name": _pick(SURNAME, rng) + _pick(GIVEN, rng) + _pick(GIVEN, rng),
        "root": root,
        "aptitude": _weighted(list(APTITUDE_POOL), rng),
        "specialty": spec,
        "affinity": affinity(root, spec),
        "realm": "练气",
        "train": 0,
        "loyalty": 60 + int(rng.random() * 31),
        "status": "待命",
        "since": float(now),
    }
    s["disciples"].append(d)
    return True, (f"招募弟子 #{d['id']} {d['name']}｜{root['name']}｜{d['aptitude']}｜"
                  f"{spec}｜忠诚 {d['loyalty']}。花费宗门灵石 {cost:,}。"), cost, d


def train(s: dict, fund: int, did: int) -> tuple[bool, str, int]:
    s = ensure(s)
    d = next((x for x in s["disciples"] if int(x.get("id") or 0) == int(did)), None)
    if not d:
        return False, "找不到这名宗门弟子，可发「#宗门弟子名册」查看序号。", 0
    lv = int(d.get("train") or 0)
    if lv >= DISCIPLE_TRAIN_MAX:
        return False, "该弟子已培养至当前上限（5/5）。", 0
    cost = 10_000 * (lv + 1)
    if int(fund) < cost:
        return False, f"宗门灵石池不足，培养需 {cost:,} 灵石。", 0
    d["train"] = lv + 1
    d["loyalty"] = min(100, int(d.get("loyalty") or 60) + 5)
    return True, f"弟子 #{did} 培养至 {lv + 1}/5，忠诚 +5（{d['loyalty']}）。花费 {cost:,} 灵石。", cost


def assign(s: dict, did: int, spec: str) -> tuple[bool, str]:
    s = ensure(s)
    if spec not in SPECIALTIES:
        return False, "专长须为「采药」「炼丹」「炼器」「阵法」「护山」「外务」之一。"
    d = next((x for x in s["disciples"] if int(x.get("id") or 0) == int(did)), None)
    if not d:
        return False, "找不到这名宗门弟子。"
    d["specialty"] = spec
    d["affinity"] = affinity(d.get("root") or {}, spec)
    d["status"] = "任职"
    return True, (f"弟子 #{did} {d['name']} 改任「{spec}」，"
                  f"灵根契合度 ×{d['affinity']}，即刻参与「#宗门运营」结算。")


def operate(s: dict, fund: int, level: int, now: float) -> tuple[bool, str, int]:
    """惰性每日运营结算（最多 7 天）。返回 (ok, msg, fund 净变动)。

    原版：`upkeep=(1000×level + 任职人数×500)×days`，不足则断连续运营；
    任职弟子按专长产出药材/丹药/法器/灵石/声望，忠诚 +1/日。
    """
    s = ensure(s)
    last = float(s["ops_at"] or 0)
    if not last:
        s["ops_at"] = float(now)
        return True, "宗门运营已起算，明日此时结算首日产出。", 0
    days = min(OPERATE_MAX_DAYS, max(0, int((float(now) - last) / DAY_SECONDS)))
    if days <= 0:
        return True, "尚未到每日结算时间。", 0
    active = [d for d in s["disciples"] if d.get("status") == "任职"]
    lv = max(1, int(level))
    cost = (1000 * lv + len(active) * 500) * days
    s["ops_at"] += days * DAY_SECONDS
    if int(fund) < cost:
        s["ops_streak"] = 0
        s["ops_log"] = (s["ops_log"] + [f"运营中断：缺 {cost:,} 灵石"])[-10:]
        return False, f"灵石池不足，无法维持 {days} 日运营（需 {cost:,} 灵石）。", 0
    produced = {"药材": 0, "丹药": 0, "法器": 0, "灵石": 0}
    for d in active:
        mult = (SPECIALTY_RATE.get(d.get("specialty"), 1.0)
                * float(d.get("affinity") or 1.0)
                * (1 + int(d.get("train") or 0) * 0.2))
        amount = max(1, int(mult * days))
        sp = d.get("specialty")
        if sp == "采药":
            produced["药材"] += amount * 10
        elif sp == "炼丹":
            produced["丹药"] += amount * 5
        elif sp == "炼器":
            produced["法器"] += amount * 2
        elif sp == "外务":
            produced["灵石"] += amount * 3000
        elif sp == "阵法":
            s["reputation"] += amount * 2
        elif sp == "护山":
            s["reputation"] += amount
        d["loyalty"] = min(100, int(d.get("loyalty") or 60) + 1)
    for k in ("药材", "丹药", "法器"):
        s["store"][k] += produced[k]
    s["ops_streak"] = int(s["ops_streak"] or 0) + days
    note = (f"结算 {days} 日：维护 −{cost:,}｜药材 +{produced['药材']}｜丹药 +{produced['丹药']}"
            f"｜法器 +{produced['法器']}｜灵石 +{produced['灵石']:,}")
    s["ops_log"] = (s["ops_log"] + [note])[-10:]
    delta = -cost + produced["灵石"]
    return True, (f"【宗门运营】{note}｜连续运营 {s['ops_streak']} 日｜声望 {s['reputation']}。"
                  f"净变动 {delta:+,} 灵石。"), delta


def disciple_lines(s: dict, level: int = 1) -> list[str]:
    s = ensure(s)
    if not s["disciples"]:
        return ["尚无宗门弟子，可发「#宗门弟子招募」招揽门人。"]
    lines = [f"--- 宗门弟子（{len(s['disciples'])}/{disciple_capacity(level)}） ---"]
    for d in s["disciples"][-20:]:
        af = "高契合" if float(d.get("affinity") or 1) > 1 else "普通契合"
        lines.append(f"· #{d.get('id')} {d.get('name')}｜{(d.get('root') or {}).get('name')}"
                     f"｜{d.get('aptitude')}｜{d.get('specialty')}({af})"
                     f"｜培养 {d.get('train')}/5｜忠诚 {d.get('loyalty')}｜{d.get('status')}")
    return lines


def panel_lines(s: dict, fund: int, level: int, member_count: int, now: float) -> list[str]:
    s = ensure(s)
    left = max(0, UPKEEP_SECONDS - (float(now) - float(s["upkeep_at"] or 0)))
    active = sum(1 for d in s["disciples"] if d.get("status") == "任职")
    upkeep_txt = "可维护" if left <= 0 or not s["upkeep_at"] else f"{int(left // 3600)} 小时后"
    gate_txt = "不限" if not s["gate"] else f"第 {s['gate']} 境"
    place_txt = s["place"] or "无（可发「#入驻洞天 名称」占据）"
    return [
        "--- 宗门驻地 · 护宗大阵 ---",
        f"驻地：{place_txt}｜建设度 {s['build']}",
        f"宗门等级 {level}｜成员 {member_count}｜灵石池 {int(fund):,}/{pool_cap(level):,}",
        f"护宗大阵：{s['array_hp']:,} 血量（「#宗门挑战」计入守方战力）",
        f"宗门维护：{upkeep_txt}｜加入门槛：{gate_txt}",
        f"弟子 {len(s['disciples'])} 人（任职 {active}）｜声望 {s['reputation']}｜连续运营 {s['ops_streak']} 日",
        f"仓库：药材 {s['store']['药材']}｜丹药 {s['store']['丹药']}｜法器 {s['store']['法器']}",
        "· 「#开采灵脉」每日一次｜「#建设宗门」涨建设度｜「#维护护宗大阵 数量」涨大阵",
        "· 「#宗门弟子名册」「#宗门运营」「#我的贡献」见弟子与产出",
    ]


def war_bonus(s: dict) -> tuple[int, int]:
    """给既有「#宗门挑战」用：大阵/建设度转化为守方与攻方战力。"""
    s = ensure(s)
    return s["build"] * 100 + s["array_hp"] // 2, s["build"] * 100 + s["array_hp"]


def help_text() -> str:
    return ("【W8-F7 宗门深化】\n"
            "「#洞天福地列表」15 处洞天与归属｜「#入驻洞天 名称」宗主占地/抢夺\n"
            "「#开采灵脉」每日一次｜「#建设宗门」涨建设度｜「#查看护宗大阵」总面板\n"
            "「#维护护宗大阵 数量」灵石换大阵血量｜「#宗门维护」7 日一次｜「#设置门槛 境界」\n"
            "「#宗门弟子招募」「#宗门弟子名册」「#培养宗门弟子 序号」"
            "「#任命宗门弟子 序号 专长」「#宗门运营」「#我的贡献」")


def rules_text() -> str:
    return ("【规则】灵脉 = 1200 × 洞天阶 × 境界数，每日一次，玩家与宗门池双份入账；"
            "建设扣 建设度×1 万、涨 境界÷7+1；大阵 1 灵石 = 5 血量；"
            "弟子容量 3×宗门等级，招募 1 万+5 千×等级，培养 1 万×(培养+1) 上限 5；"
            "运营每日维护 (1000×等级+任职×500)，最多补 7 日。"
            "【折算】原版仙宗 power 分野（倍率 2 / 池 ×10 / 门槛钳 41）本移植无底座，已去除；"
            "宗门灵石池复用 sects.fund，db 恒 v17；"
            "原版 cron 每日结算改惰性 tick；藏宝阁神兽奖励池已接入。")
