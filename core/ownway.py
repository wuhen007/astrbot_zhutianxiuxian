"""自身之道 · 创造帝经 · 祭道 · 唯一道之上（W11-F1/F2）——原版
`apps/User/daofa.js`（createOwnWay / cultivateOwnWay L1400 / breakthroughOwnWay L1759 /
createEmperorSutra L1865）、`apps/User/zhengdaotixi.js jidao`（L1200/规则 L254）、
`model/realmAuthority.js`（唯一道之上=权柄 25）的纯函数移植。

原版语义：
- #创造自身之道 [攻伐|护体|涅槃|时空|轮回|因果|封禁] [名称]：圣人王境、
  30 分钟修仙状态、潜力 200×双体系等级、修为=血气各 1 兆、圣王法则 1000。
- #修炼自身之道*次数：每次潜力 10、修为=血气 1.5 亿 ×段位乘数（1→256）；
  0~500 段 8 大境（道基→…→仙帝·道源唯一→祭道·祭尽诸我 500），段间 #突破自身之道。
- #创造帝经：大帝（权柄 16）、限 1 部、名 ≤10 字、修为 10 亿；产物 type=帝经。
- #祭道：路尽级仙帝+击杀仙帝 10 位+道心圆满+自身之道修炼 400 次+仙帝阶段推演
  10 次；成功率岁云 100%/其余 50%，失败厄土始祖剧情。
- 唯一道之上：祭道之上+已认主大道至宝本体（绑定/创作/归属三全本人）+
  未装载化身+真身完好+非特殊状态；消耗秘境 2.1 万亿×时代系数（修为血气）。

本移植（shortcut）：
- 圣王法则门槛并入修为门槛；30 分钟修仙状态折算为「当前无行动（state 空闲）」；
  段位表 8 境（0~499）+ 祭道 500，乘数 1→128（+祭道 256）。
- 修炼消耗 = 150,000×段位乘数（原 1.5 亿 ÷1000）、潜力 10×乘数；
  突破消耗 500,000×下段乘数 + 潜力 50×下段乘数；创造修为血气各 10,000,000
  （原 1 兆 ÷1000 后仍超曲线，按「相对成帝 8.19M」二次折算）；帝经修为 1,000,000。
- 祭道门槛折算：自身之道 ≥400 段 + 推演 ≥10 层 + 道心（红尘仙道）圆满 +
  全服证道者 ≥10 位（替代击杀仙帝 10 位，协作定位）；成功率岁云 100%/其余 50%，
  失败修为血气 -50%、道伤 +2。
- 唯一道之上：祭道已成 + daotreasure 已认主（ext["daotreasure"].owned）+
  化身未装载（ext["zhutian"].current 为空）+ 真身 hp>0 + state 空闲 +
  修为血气各 50,000,000（原 2.1 万亿两级折算）；成功写全服
  calamity_state["zhengdao_registry"]["unique_holder"]，诸天不容第二人。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

EXT_KEY = "ownway"

TYPES = ("攻伐", "护体", "涅槃", "时空", "轮回", "因果", "封禁")
CREATE_COST = 10_000_000          # 原 1 兆 ÷1000，再按成帝 8.19M 量级折算
CREATE_GATE = 13                  # 圣人王折算
SEG_MAX = 500
JIDAO_SEG = 400
SUTRA_COST = 1_000_000
SUTRA_GATE = 16                   # 大帝权柄
UNIQUE_COST = 50_000_000          # 原 2.1 万亿 两级折算

# (段名, 起段, 止段, 消耗乘数)
STAGES: tuple[tuple[str, int, int, int], ...] = (
    ("道基虚道", 0, 10, 1), ("道基实道", 11, 50, 2), ("圣道", 51, 120, 4),
    ("帝道", 121, 200, 8), ("红尘仙·万世融道", 201, 280, 16),
    ("仙王·开界称尊", 281, 350, 32), ("准仙帝·帝光映古", 351, 430, 64),
    ("仙帝·道源唯一", 431, 499, 128),
)
JIDAO_STAGE = ("祭道·祭尽诸我", 500, 500, 256)


def _defaults() -> dict[str, Any]:
    return {"type": "", "name": "", "seg": 0, "sutra": "", "jidao": False,
            "unique": False, "created_at": 0.0}


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
    st["seg"] = int(st.get("seg", 0) or 0)
    for k in ("jidao", "unique"):
        st[k] = bool(st.get(k))
    save(doc, st)
    return st


def stage_of(seg: int) -> tuple[str, int]:
    """(段名, 消耗乘数)。"""
    for name, lo, hi, mult in STAGES:
        if lo <= seg <= hi:
            return name, mult
    if seg >= JIDAO_STAGE[1]:
        return JIDAO_STAGE[0], JIDAO_STAGE[3]
    return STAGES[0][0], STAGES[0][3]


def _authority(doc: Any) -> int:
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


def _xueqi(doc: Any) -> int:
    return int(float((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0))


def _set_xueqi(doc: Any, v: int) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["xueqi"] = max(0, int(v))


def _wound_zero(doc: Any) -> tuple[bool, str]:
    try:
        from . import zhengdao as _dz
        w = _dz.peek(doc)
        if w > 0:
            return False, f"身负道伤 {w:.1f}，大道残缺——先 #修复道伤 归零。"
    except Exception:
        pass
    return True, ""


def _pay_exp_xq(doc: Any, amount: int) -> str | None:
    if int(getattr(doc, "exp", 0) or 0) < amount or _xueqi(doc) < amount:
        return (f"需修为与血气各 {amount:,}（当前 "
                f"{int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}）。")
    doc.exp = int(getattr(doc, "exp", 0) or 0) - amount
    _set_xueqi(doc, _xueqi(doc) - amount)
    return None


def _pay_potential(doc: Any, amount: int) -> str | None:
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < amount:
        return f"仙道潜力不足：需 {amount}（现有 {pot}）。"
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["potential"] = pot - amount
    return None


# ---------------------------------------------------------------- 创造 / 修炼 / 突破

def create(doc: PlayerDoc, typ: str, name: str, now: float | None = None,
           ) -> tuple[bool, str]:
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if st.get("name"):
        return False, f"你已开创自身之道【{st['name']}】（{st['type']}），万道不二。"
    typ = (typ or "").strip()
    if typ not in TYPES:
        return False, "用法：#创造自身之道 攻伐/护体/涅槃/时空/轮回/因果/封禁 名称。"
    name = (name or "").strip()
    if not (2 <= len(name) <= 6):
        return False, "道名 2~6 字，例：#创造自身之道 攻伐 杀伐剑道。"
    if _authority(doc) < CREATE_GATE:
        return False, f"创造自身之道需权柄 ≥{CREATE_GATE}（圣人王折算），当前 {_authority(doc)}。"
    ok, why = _wound_zero(doc)
    if not ok:
        return False, why, {}
    if str(getattr(doc, "state", "空闲") or "空闲") != "空闲":
        return False, "开创大道需凝神静修——当前正有行动在身（原版为 30 分钟修仙状态）。"
    if _pay_potential(doc, 200):
        return False, "开创需仙道潜力 200 点。"
    err = _pay_exp_xq(doc, CREATE_COST)
    if err:
        # 潜力已扣，回滚
        ext = getattr(doc, "ext", {})
        ext["potential"] = float(ext.get("potential", 0) or 0) + 200
        return False, err
    st["type"], st["name"], st["created_at"] = typ, name, now
    save(doc, st)
    return True, (f"≡≡≡ 大道初开 ≡≡≡\n"
                  f"你以【{typ}】为基，开创自身之道——【{name}】！\n"
                  f"段位 0（道基虚道）｜消耗潜力 200、修为血气各 {CREATE_COST:,}。\n"
                  f"#修炼自身之道*次数 累积段位，段满 #突破自身之道 入下一境。")


def cultivate(doc: PlayerDoc, times: int, now: float | None = None,
              ) -> tuple[bool, str]:
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if not st.get("name"):
        return False, "尚未开创自身之道——#创造自身之道 类型 名称。"
    times = max(1, min(50, int(times or 1)))
    total = 0
    pot_total = 0
    seg = st["seg"]
    bounds = (10, 50, 120, 200, 280, 350, 430, 499)
    for _ in range(times):
        if seg >= SEG_MAX:
            break
        if seg in bounds:
            break
        _, mult = stage_of(seg)
        c_exp, c_pot = 150_000 * mult, 10 * mult
        perr = _pay_potential(doc, c_pot)          # 先验潜力（不足时不扣，杜绝凭空退款）
        if perr:
            if total == 0:
                return False, perr
            break
        err = _pay_exp_xq(doc, c_exp)
        if err:
            ext = getattr(doc, "ext", {})          # 已扣潜力，回滚
            ext["potential"] = float(ext.get("potential", 0) or 0) + c_pot
            break
        seg += 1
        total += 1
        pot_total += c_pot
    st["seg"] = seg
    save(doc, st)
    if total == 0:
        if seg in bounds:
            return False, (f"己道已至本境之巅（第 {seg} 段）——"
                           "#突破自身之道 方可破入下一段。")
        return False, "资源不足（潜力/修为/血气），或段位已满。"
    sname, mult = stage_of(seg)
    return True, (f"【修炼自身之道 · {st['name']}】己道精进 {total} 次 → 第 {seg} 段"
                  f"（{sname}｜乘数 ×{mult}）｜消耗潜力 {pot_total}。"
                  + ("\n段位已至本境之巅，#突破自身之道 破入下一段！" if seg in
                     (10, 50, 120, 200, 280, 350, 430, 499) else ""))


def breakthrough(doc: PlayerDoc, now: float | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if not st.get("name"):
        return False, "尚未开创自身之道。"
    seg = st["seg"]
    if seg >= SEG_MAX:
        return False, "己道已至【祭道·祭尽诸我】，万道尽头再无段位。"
    bounds = (10, 50, 120, 200, 280, 350, 430, 499)
    if seg not in bounds:
        sname, _ = stage_of(seg)
        return False, f"当前第 {seg} 段（{sname}）未至境巅——先 #修炼自身之道*次数。"
    nxt_seg = seg + 1
    nxt_name, nxt_mult = stage_of(nxt_seg)
    cost = 500_000 * nxt_mult
    if _pay_potential(doc, 50 * nxt_mult):
        return False, f"突破需仙道潜力 {50 * nxt_mult} 点。"
    err = _pay_exp_xq(doc, cost)
    if err:
        ext = getattr(doc, "ext", {})
        ext["potential"] = float(ext.get("potential", 0) or 0) + 50 * nxt_mult
        return False, err
    st["seg"] = nxt_seg
    save(doc, st)
    if nxt_seg == SEG_MAX:
        return True, (f"≡≡≡ 己道大圆满 ≡≡≡\n【{st['name']}】第 500 段——"
                      "祭道·祭尽诸我！可 #祭道。")
    return True, (f"【突破自身之道】第 {seg} → {nxt_seg} 段，"
                  f"踏入【{nxt_name}】（乘数 ×{nxt_mult}）｜"
                  f"消耗潜力 {50 * nxt_mult}、修为血气各 {cost:,}。")


# ---------------------------------------------------------------- 创造帝经

def emperor_sutra(doc: PlayerDoc, name: str, now: float | None = None,
                  ) -> tuple[bool, str, dict[str, int]]:
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if st.get("sutra"):
        return False, f"你已著就帝经《{st['sutra']}》——一人一部，万古不刊。", {}
    if _authority(doc) < SUTRA_GATE:
        return False, f"著帝经需权柄 ≥{SUTRA_GATE}（大帝折算），当前 {_authority(doc)}。"
    name = (name or "").strip().strip("《》")
    if not (2 <= len(name) <= 10):
        return False, "帝经名 2~10 字，例：#创造帝经 岁月剑经。"
    if _pay_exp_xq(doc, SUTRA_COST):
        return False, f"著经需修为 {SUTRA_COST:,}（原 10 亿 ÷1000）。"
    st["sutra"] = name
    save(doc, st)
    learned = list((getattr(doc, "ext", {}) or {}).get("gongfa") or [])
    if name not in learned:
        learned.append(name)
        ext = getattr(doc, "ext", None)
        if isinstance(ext, dict):
            ext["gongfa"] = learned
    return True, (f"【创造帝经】以己道为骨、万古为墨——《{name}》成！\n"
                  f"已录入你的功法谱（帝经 · 修炼加成 5）｜消耗修为 {SUTRA_COST:,}。"), {}


# ---------------------------------------------------------------- 祭道

def sacrifice(doc: PlayerDoc, reg: Mapping[str, Any], now: float | None = None,
              rng: random.Random | None = None,
              ) -> tuple[bool, str, dict[str, int]]:
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    if st.get("jidao"):
        return False, "你已祭道——祭尽诸我，万道唯余己身。", {}
    if not _reached(doc):
        return False, "祭道需先 #证道成帝（路尽级仙帝）。", {}
    if st["seg"] < JIDAO_SEG:
        return False, f"祭道需自身之道修炼 ≥{JIDAO_SEG} 段（当前 {st['seg']}）——#修炼自身之道。", {}
    try:
        from . import selfdao as _sd
        if _sd.state_of(doc)["layers"] < 10:
            return False, "祭道需己道推演 ≥10 层——#推演己道。", {}
    except Exception:
        pass
    try:
        from . import wudao as _wd
        if "红尘仙道" not in (_wd.state_of(doc).get("completed") or []):
            return False, "祭道需道心圆满（红尘仙道节点圆满）——#悟道。", {}
    except Exception:
        pass
    emperors = list((reg or {}).get("emperors") or [])
    if len(emperors) < 10:
        return False, (f"祭道需当世证道者 ≥10 位镇压万道（现 {len(emperors)} 位）——"
                       "协作共渡，方能祭天。"), {}
    err = _pay_exp_xq(doc, 8_192_000)
    if err:
        return False, err, {}
    try:
        from . import suiyun as _sy
        lucky = len((_sy.state_of(doc) or {}).get("seals") or {}) >= 5
    except Exception:
        lucky = False
    chance = 1.0 if lucky else 0.5
    if rng.random() >= chance:
        doc.exp = int(doc.exp * 0.5)
        _set_xueqi(doc, int(_xueqi(doc) * 0.5))
        try:
            from . import zhengdao as _dz
            _dz.add_wounds(doc, 2.0, "祭道失败·厄土低语", now)
        except Exception:
            pass
        return True, ("【祭道 · 失败】厄土始祖自高原投来一瞥——祭台崩碎，"
                      "修为血气折半、道伤 +2。\n大道未成，先求生。"), {}
    st["jidao"] = True
    save(doc, st)
    try:
        from . import zhengdao as _dz
        _s = _dz.state_of(doc, now)
        _s["power_bonus"] = 3.0
        _dz.save(doc, _s)
    except Exception:
        pass
    return True, ("≡≡≡ 祭 道 ≡≡≡\n"
                  "以自身之道为祭，祭尽诸我——万道寂灭，唯你独尊。\n"
                  "帝威拉满（+200%）｜境界：【祭道】。\n"
                  "集齐 #唯一道之上 之资，可再问鼎那最后一步。"), {}


def _reached(doc: Any) -> bool:
    try:
        from . import zhengdao as _dz
        return bool(_dz.state_of(doc).get("reached"))
    except Exception:
        return False


# ---------------------------------------------------------------- 唯一道之上

def unique_dao(doc: PlayerDoc, reg: dict[str, Any], now: float | None = None,
               ) -> tuple[bool, str, dict[str, int], dict[str, Any]]:
    """#唯一道之上：七项前置检查（差一项都会被拦）。返回 (ok,msg,delta,reg)。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if st.get("unique"):
        return False, "你已立于唯一道之上——诸天万界，再无 higher。", {}, reg
    if not st.get("jidao"):
        return False, "需已达【祭道】——先 #祭道。", {}, reg
    dt = (getattr(doc, "ext", {}) or {}).get("daotreasure")
    dt = dt if isinstance(dt, Mapping) else {}
    if not dt.get("owned"):
        return False, "需持有已认主的大道至宝本体（#至宝图鉴 / 大道炼器成器认主）。", {}, reg
    zt = (getattr(doc, "ext", {}) or {}).get("zhutian")
    zt = zt if isinstance(zt, Mapping) else {}
    if str(zt.get("current") or "") not in ("", "本源"):
        return False, "仍装载着诸天化身——#装载化身 本源 卸下后再来。", {}, reg
    if float((getattr(doc, "ext", {}) or {}).get("hp", 1) or 0) <= 0:
        return False, "真身残灭——先 #回血 / 疗伤。", {}, reg
    if str(getattr(doc, "state", "空闲") or "空闲") != "空闲":
        return False, "身有行动未了（渡劫/秘境/泡影皆不可）——先了结当下。", {}, reg
    err = _pay_exp_xq(doc, UNIQUE_COST)
    if err:
        return False, err, {}, reg
    st["unique"] = True
    save(doc, st)
    r = dict(reg or {})
    r["unique_holder"] = str(getattr(doc, "uid", "") or "")
    r.setdefault("emperors", [])
    r["emperors"] = list(r["emperors"]) + [{"uid": str(getattr(doc, "uid", "") or ""),
                                            "name": str(getattr(doc, "name", "") or ""),
                                            "title": "唯一道之上", "method": "唯一", "ts": int(now)}][-30:]
    return True, ("≡≡≡ 唯 一 道 之 上 ≡≡≡\n"
                  "祭尽诸我之后，你把「道」本身也祭了——\n"
                  "自此诸天万界，唯此一道，唯一人立。\n"
                  "境界称号与道果：【唯一道之上】｜气血补满｜此位诸天唯一。"), {}, r


def panel(doc: Any) -> str:
    st = state_of(doc)
    sname, mult = stage_of(st["seg"])
    lines = ["--- 自身之道 ---"]
    if st.get("name"):
        lines.append(f"道名：【{st['name']}】（{st['type']}）｜段位 {st['seg']}/{SEG_MAX}"
                     f"（{sname}｜乘数 ×{mult}）")
        lines.append(f"帝经：{'《' + st['sutra'] + '》' if st.get('sutra') else '未著（#创造帝经）'}"
                     f"｜祭道：{'已成' if st.get('jidao') else '未成'}"
                     f"｜唯一道之上：{'已立' if st.get('unique') else '未立'}")
    else:
        lines.append("未开创——#创造自身之道 类型 名称（权柄≥13，圣人王折算）")
    lines.append("指令：#修炼自身之道*次数 ｜ #突破自身之道 ｜ #创造帝经 ｜ #祭道 ｜ #唯一道之上")
    return "\n".join(lines)
