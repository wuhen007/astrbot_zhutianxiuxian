"""己道推演 · 合道 · 红尘仙九世（W10-F1/F2）——原版
`apps/User/SelfDaoDeduction.js` + `model/selfDaoDeduction.js`（推演 20 层 / 体系命名）、
`apps/User/RedDustPath.js` + `model/redDustPath.js` + `model/daoHeart.js`（红尘仙九世）、
`Level.js 合道` 的纯函数移植。#祭道 依赖 W11 自身之道，随 W11 落地。

原版语义：
- #推演己道：准仙帝 20 层；10 层=极巅（减伤）、15 层=神胎（每战额外复活）、
  20 层=战尸骸仙帝；单次消耗纪元积累 50 / 心神 50 / 元神 100 亿 / 潜力 3000 /
  寿元 30 亿年 / 修为=血气 3 万亿；身灭道消后 320 分钟真血重聚。
- #合道：三体系任一到准仙帝前一境 + 圆满对应道则，命名 1~5 字自创体系。
- #设立体系境界：五次推演后为自创体系命名六个大境界（1~8 字）。
- 红尘仙：#打听天机 红尘仙（500 万源石）→ #立下世愿（化凡 0.85/争渡 1.0/
  逆天 1.15 消耗，心魔 0.9/1.0/1.1）→ #逆活九世 每世
  15 亿×2^(世数-1)×时代×世愿×道心，另潜力=世数、元神=世数×2 亿、
  寿元=世数×500×倍率；第 9 世需大圆满；每世有心魔，失败劫灰 +1。

本移植（shortcut，两级折算说明）：
- 原版量级 ÷1000 后仍远超本移植经济曲线（universe 红尘仙档 cultivation 仅
  5,000,000），故按「相对成帝成本（zhengdao.PROVE_COST=8,192,000）」二次折算：
  推演单次修为=血气 5,000,000（≈0.6×成帝）、潜力 300、寿元 30,000 年、
  心神 50（yuanshen.heart）、纪元积累 5（fashan.era_points，上限 1000）；
  元神值消耗挪到红尘仙九世（每世 2 万×世数）。
- 逐层异步推演同步化：每层一次判定；身灭道消折算为 320 分钟真实冷却。
- 红尘仙九世：每世 50,000×2^(世数-1)×时代×世愿（累计约 2,550 万 ≈ 3×成帝）；
  心魔折算为成功率 -5pp×心魔倍率；冷却 5000 游戏年折算 30 分钟/世。
- 击杀仙帝计数、天资/理想加成未搬（写进 shortcut；祭道门槛在 W11 相应折算）。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .wallet import authority as _authority, set_xueqi as _set_xueqi, xueqi as _xueqi
from .player import PlayerDoc

EXT_KEY = "selfdao"

LAYERS = 20
LAYER_COST = {"exp": 5_000_000, "potential": 300, "shouyuan": 30_000,
              "heart": 10, "era": 5}   # 心神 50→10：本移植心神上限 30~100（原版亿元级），÷量级后取 10/层
FINAL_FOE_CHANCE = 0.35          # 第 20 层直面尸骸仙帝
MILESTONE_10 = 10                # 极巅：PVE 减伤 +10%
MILESTONE_15 = 15                # 神胎：每战额外满血复活一次
DEATH_CD = 320 * 60              # 原版身灭道消 320 分钟真血重聚

HEDAO_GATE = 19                  # 准仙帝前一境折算
HEDAO_NODE = "红尘仙道"          # 需圆满的己道节点（wudao）
DIVINE_COST_STONES = 500_000     # 原版 500 万源石折算灵石
LIVES = 9
LIFE_BASE_COST = 50_000          # 每世基础修为=血气（两级折算后）
LIFE_YUANSHEN = 20_000           # 每世元神值（原 2 亿 ÷1000，再折）
LIFE_SHOUYUAN = 500              # 原版即 500 年/世×倍率，不缩放
LIFE_COOLDOWN = 30 * 60          # 5000 游戏年折算
VOWS = {
    "化凡": {"cost": 0.85, "demon": 0.90},
    "争渡": {"cost": 1.00, "demon": 1.00},
    "逆天": {"cost": 1.15, "demon": 1.10},
}
DIVINE_PROMPTS = ("渡尽劫波", "红莲业火", "念念不住", "万世为峰")

EXT_REALM_NAMES_DEFAULT = ("我道一", "我道二", "我道三", "我道四", "我道五", "我道六")


def _defaults() -> dict[str, Any]:
    return {"layers": 0, "system_name": "", "realms": [], "unlocked": False,
            "vow": "", "life": 0, "ash": 0, "last_life_at": 0.0,
            "death_until": 0.0, "hongchen": False, "title": ""}


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
    for k in ("layers", "life", "ash"):
        st[k] = int(st.get(k, 0) or 0)
    for k in ("unlocked", "hongchen"):
        st[k] = bool(st.get(k))
    st["realms"] = list(st.get("realms") or [])
    st["last_life_at"] = float(st.get("last_life_at", 0) or 0)
    st["death_until"] = float(st.get("death_until", 0) or 0)
    save(doc, st)
    return st


def _reached(doc: Any) -> bool:
    try:
        from . import zhengdao as _dz
        return bool(_dz.state_of(doc).get("reached"))
    except Exception:
        return False


def _wound_ok(doc: Any) -> tuple[bool, str]:
    try:
        from . import zhengdao as _dz
        w = _dz.peek(doc)
        if w > 0:
            return False, f"身负道伤 {w:.1f}，大道不容——先 #修复道伤 归零。"
    except Exception:
        pass
    return True, ""


# ---------------------------------------------------------------- 推演己道

def deduction_bonus(doc: Any) -> dict[str, float]:
    """里程碑加成（战斗/渡劫注入用）：10 层减伤、15 层神胎。"""
    st = state_of(doc)
    return {
        "damage_reduction": 0.10 if st["layers"] >= MILESTONE_10 else 0.0,
        "extra_rebirth": 1.0 if st["layers"] >= MILESTONE_15 else 0.0,
    }


def deduce(doc: PlayerDoc, now: float | None = None,
           rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#推演己道：20 层逐层推演，同步化单层结算。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    if st["hongchen"] or st["layers"] >= LAYERS:
        return False, "二十层己道已推演圆满——半步仙帝，可问 #祭道 / #唯一道之上。", {}
    if not (_reached(doc) or _authority(doc) >= 20):
        return False, "推演己道需先 #证道成帝（路尽级仙帝）。", {}
    if now < float(st.get("death_until", 0) or 0):
        left = (float(st["death_until"]) - now) / 60
        return False, f"上次推演身灭道消，真血重聚尚需 {left:.0f} 分钟。", {}
    ok, why = _wound_ok(doc)
    if not ok:
        return False, why, {}

    if _xueqi(doc) < LAYER_COST["exp"] or int(getattr(doc, "exp", 0) or 0) < LAYER_COST["exp"]:
        return False, (f"推演需修为与血气各 {LAYER_COST['exp']:,}（当前 "
                       f"{int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}）。"), {}
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < LAYER_COST["potential"]:
        return False, f"仙道潜力不足：需 {LAYER_COST['potential']}（现有 {pot}）。", {}
    shouyuan = int(float((getattr(doc, "ext", {}) or {}).get("shouyuan", 0) or 0))
    if shouyuan <= LAYER_COST["shouyuan"]:
        return False, f"推演需燃烧 {LAYER_COST['shouyuan']:,} 年寿元（现有 {shouyuan:,}）——先延寿。", {}
    try:
        from . import fashan as _fs
        if _fs.era_of(doc) < LAYER_COST["era"]:
            return False, f"纪元积累不足：需 {LAYER_COST['era']}（现有 {_fs.era_of(doc)}），镇守永恒未知之地可得。", {}
    except Exception:
        pass
    try:
        from . import yuanshen as _ys
        ok_h, _, _ = _ys.consume_heart(doc, LAYER_COST["heart"], now)
        if not ok_h:
            return False, f"心神不足：需 {LAYER_COST['heart']} 点——精神宇宙归位后再来。", {}
    except Exception:
        pass
    try:
        from . import fashan as _fs
        doc.ext["era_points"] = _fs.era_of(doc) - LAYER_COST["era"]   # 心神扣稳后再扣纪元
    except Exception:
        pass
    ext = getattr(doc, "ext", {})
    ext["potential"] = pot - LAYER_COST["potential"]
    ext["shouyuan"] = shouyuan - LAYER_COST["shouyuan"]
    doc.exp = int(getattr(doc, "exp", 0) or 0) - LAYER_COST["exp"]
    _set_xueqi(doc, _xueqi(doc) - LAYER_COST["exp"])

    layer = st["layers"] + 1
    if layer == LAYERS:
        ok = rng.random() < FINAL_FOE_CHANCE
    else:
        ok = rng.random() < 0.75
    if not ok:
        st["death_until"] = now + DEATH_CD
        st["ash"] = int(st["ash"]) + 1
        save(doc, st)
        try:
            from . import zhengdao as _dz
            _dz.add_wounds(doc, 1.0, "推演身灭道消", now)
        except Exception:
            pass
        return True, (f"【推演己道 · 第 {layer}/{LAYERS} 层】"
                      + ("尸骸仙帝一掌镇压——" if layer == LAYERS else "推演歧路，神魂重创——")
                      + f"身灭道消！真血重聚需 {DEATH_CD // 60} 分钟（劫灰 {st['ash']}）。"
                        "已耗潜力/寿元/心神/纪元不退，修为血气各损一半。"), {}
    st["layers"] = layer
    save(doc, st)
    try:
        from . import zhengdao as _dz
        _s = _dz.state_of(doc, now)
        _s["power_bonus"] = round(min(3.0, float(_s.get("power_bonus", 0) or 0) + 0.05), 3)
        _dz.save(doc, _s)
    except Exception:
        pass
    marks = []
    if layer == MILESTONE_10:
        marks.append("【极巅】PVE 减伤 +10%")
    if layer == MILESTONE_15:
        marks.append("【己道神胎】每战额外满血复活一次")
    tail = ("　".join(marks)) if marks else ""
    if layer == LAYERS:
        tail = "尸骸仙帝败退——【半步仙帝】！可 #祭道 / #唯一道之上。"
    return True, (f"【推演己道 · 第 {layer}/{LAYERS} 层】道则如星图展开，"
                  f"己道又坚一层（帝威 +5%）。{tail}"), {}


# ---------------------------------------------------------------- 合道 / 体系境界

def hedao(doc: PlayerDoc, name: str, now: float | None = None,
          ) -> tuple[bool, str, dict[str, int]]:
    """#合道：准仙帝前一境 + 红尘仙道圆满，开创 1~5 字自创体系。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if st.get("system_name"):
        return False, f"你已开创自创体系【{st['system_name']}】，万道不二。", {}
    if _authority(doc) < HEDAO_GATE:
        return False, f"合道需权柄 ≥{HEDAO_GATE}（准仙帝前一境），当前 {_authority(doc)}。", {}
    try:
        from . import wudao as _wd
        wst = _wd.state_of(doc)
        if HEDAO_NODE not in (wst.get("completed") or []):
            return False, "合道需【红尘仙道】节点圆满——先 #悟道 圆满该节点。", {}
    except Exception:
        return False, "合道需己道节点体系（#悟道）支持。", {}
    ok, why = _wound_ok(doc)
    if not ok:
        return False, why, {}
    name = (name or "").strip()
    if not (1 <= len(name) <= 5):
        return False, "用法：#合道 体系名（1~5 字，例：#合道 岁月剑河）。", {}
    st["system_name"] = name
    save(doc, st)
    try:
        from . import zhengdao as _dz
        _s = _dz.state_of(doc, now)
        _s["power_bonus"] = round(min(3.0, float(_s.get("power_bonus", 0) or 0) + 0.3), 3)
        _dz.save(doc, _s)
    except Exception:
        pass
    return True, (f"≡≡≡ 合道 ≡≡≡\n万道让路，你以自身之道开天——"
                  f"自创体系【{name}】铭入古史！\n帝威 +30%；"
                  "五层推演后可 #设立体系境界 为六大境界命名。"), {}


def set_realms(doc: Any, arg: str) -> tuple[bool, str]:
    """#设立体系境界：六境界命名（/ 分隔，各 1~8 字），需推演 ≥5 层。"""
    st = state_of(doc)
    if not st.get("system_name"):
        return False, "尚未 #合道 开创自创体系。"
    if st["layers"] < 5:
        return False, f"设立体系境界需推演 ≥5 层（当前 {st['layers']}）——#推演己道。"
    if st.get("realms"):
        return False, "六大境界已命名：" + "、".join(st["realms"])
    parts = [p.strip() for p in (arg or "").replace("｜", "/").split("/") if p.strip()]
    if len(parts) != 6 or any(not (1 <= len(p) <= 8) for p in parts):
        return False, "用法：#设立体系境界 境界一/境界二/境界三/境界四/境界五/境界六（各 1~8 字）。"
    st["realms"] = parts
    save(doc, st)
    return True, (f"【{st['system_name']}】六大境界铭定：\n"
                  + " → ".join(parts) + "\n万道众生，从此按你的道行走。")


# ---------------------------------------------------------------- 红尘仙九世

def divine(doc: PlayerDoc, now: float | None = None,
           rng: random.Random | None = None) -> tuple[bool, str]:
    """#推演红尘仙：折算 50 万灵石，解锁九世仙路并展示命题与三愿。"""
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    if st.get("unlocked"):
        return True, ("红尘仙路已开。当前世愿：" + (st["vow"] or "未立") +
                      f"｜已逆活 {st['life']}/9 世——#立下世愿 化凡/争渡/逆天。")
    if _authority(doc) < 16:
        return False, "红尘仙路需权柄 ≥16（红尘仙境折算）方可窥探。"
    if int(getattr(doc, "stones", 0) or 0) < DIVINE_COST_STONES:
        return False, (f"推演红尘仙需灵石 {DIVINE_COST_STONES:,}（原 500 万源石折算，"
                       f"现有 {int(getattr(doc, 'stones', 0) or 0):,}）。")
    doc.stones = int(getattr(doc, "stones", 0) or 0) - DIVINE_COST_STONES
    st["unlocked"] = True
    save(doc, st)
    prompt = DIVINE_PROMPTS[int(now) % len(DIVINE_PROMPTS)]
    return True, ("【天机 · 红尘仙】岁月长河倒卷，仙路旧命题浮现——\n"
                  f"本世命题：「{prompt}」｜生门：入世，再出世。\n"
                  "立世愿择途：#立下世愿 化凡（消耗-15%，心魔-10%）｜"
                  "争渡（中道）｜逆天（消耗+15%，心魔+10%）。")


def vow(doc: Any, name: str) -> tuple[bool, str]:
    st = state_of(doc)
    if not st.get("unlocked"):
        return False, "红尘仙路未开——先 #推演红尘仙。"
    if st.get("vow"):
        return False, f"本世已立愿【{st['vow']}】——世愿不二，逆活中不可更改。"
    v = VOWS.get((name or "").strip())
    if not v:
        return False, "用法：#立下世愿 化凡/争渡/逆天。"
    st["vow"] = (name or "").strip()
    save(doc, st)
    return True, (f"【立下世愿 · {st['vow']}】道音入骨，九世为期——"
                  f"消耗 ×{v['cost']:g}、心魔 ×{v['demon']:g}。可 #逆活九世。")


def _era_cost(era: Mapping[str, Any] | None) -> float:
    try:
        return max(0.1, float((era or {}).get("qi_cost", 1.0) or 1.0))
    except Exception:
        return 1.0


def live(doc: PlayerDoc, era: Mapping[str, Any] | None, now: float | None = None,
         rng: random.Random | None = None) -> tuple[bool, str]:
    """#逆活九世：一世一结算；九世归一成红尘仙。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    st = state_of(doc)
    if not (st.get("unlocked") and st.get("vow")):
        return False, "红尘仙路未启或世愿未立——#推演红尘仙 → #立下世愿。"
    if st.get("hongchen"):
        return False, "九世道果已归一，你即红尘仙——岁月再无可逆。"
    if st["life"] >= LIVES:
        return False, "九世已尽（有未成之世再发 #逆活九世 即重走当世）。"
    left = LIFE_COOLDOWN - (now - float(st.get("last_life_at", 0) or 0))
    if st["life"] > 0 and left > 0:
        return False, f"前世道果未沉，还需 {left / 60:.0f} 分钟方可再入一世。"
    ok, why = _wound_ok(doc)
    if not ok:
        return False, why, {}
    v = VOWS[st["vow"]]
    n = st["life"] + 1
    cost = max(1, int(LIFE_BASE_COST * (2 ** (n - 1)) * _era_cost(era)
                      * v["cost"] * min(2.0, 1 + st["ash"] * 0.1)))
    if int(getattr(doc, "exp", 0) or 0) < cost or _xueqi(doc) < cost:
        return False, (f"第 {n} 世需修为与血气各 {cost:,}（当前 "
                       f"{int(getattr(doc, 'exp', 0) or 0):,} / {_xueqi(doc):,}）。")
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < n:
        return False, f"第 {n} 世需仙道潜力 {n} 点（现有 {pot}）。"
    shouyuan = int(float((getattr(doc, "ext", {}) or {}).get("shouyuan", 0) or 0))
    sy_cost = int(LIFE_SHOUYUAN * v["demon"] * n)
    if shouyuan <= sy_cost:
        return False, f"第 {n} 世需燃烧 {sy_cost:,} 年寿元（现有 {shouyuan:,}）——先延寿。"
    try:
        from . import yuanshen as _ys
        _yst = _ys.ensure(doc)
        if int(_yst.get("cur", 0) or 0) < LIFE_YUANSHEN * n:
            return False, (f"第 {n} 世需元神值 {LIFE_YUANSHEN * n:,}"
                           f"（现有 {int(_yst.get('cur', 0) or 0):,}）。")
        _yst["cur"] = int(_yst["cur"]) - LIFE_YUANSHEN * n
        _ys.save(doc, _yst)
    except Exception:
        pass
    ext = getattr(doc, "ext", {})
    ext["potential"] = pot - n
    ext["shouyuan"] = shouyuan - sy_cost
    doc.exp = int(getattr(doc, "exp", 0) or 0) - cost
    _set_xueqi(doc, _xueqi(doc) - cost)

    chance = max(0.15, 0.80 * v["demon"] - st["ash"] * 0.02)
    if n == LIVES:
        chance = min(chance, 0.5)     # 第 9 世需大圆满
    if rng.random() >= chance:
        st["ash"] = int(st["ash"]) + 1
        save(doc, st)
        try:
            from . import zhengdao as _dz
            _dz.add_wounds(doc, 1.0, f"红尘第 {n} 世心魔劫", now)
        except Exception:
            pass
        return True, (f"【逆活九世 · 第 {n} 世】心魔趁虚而入，一世积累崩散"
                      f"（成功率 {chance:.0%}，劫灰 {st['ash']}）。\n"
                      "修为血气已耗于世中；再发 #逆活九世 重走当世。"), {}
    st["life"] = n
    st["last_life_at"] = now
    if n >= LIVES:
        st["hongchen"] = True
        st["title"] = "红尘仙"
        save(doc, st)
        try:
            from . import wudao as _wd
            _wst = _wd.state_of(doc)
            _wst["completed"] = [node["name"] for node in _wd.DAO_NODES]
            _wd.save(doc, _wst)
            from . import zhengdao as _dz
            _s = _dz.state_of(doc, now)
            _s["power_bonus"] = round(min(3.0, float(_s.get("power_bonus", 0) or 0) + 1.0), 3)
            _dz.clear(doc, "红尘仙九世归一")
            _dz.save(doc, _s)
        except Exception:
            pass
        return True, ("≡≡≡ 九世归一 · 红尘仙 ≡≡≡\n"
                      "九世道果归一，此前大道自动圆满——岁月长河中，你走了出来。\n"
                      "帝威 +100%｜八重己道尽皆圆满｜道伤尽消｜称号【红尘仙】。"), {}
    save(doc, st)
    return True, (f"【逆活九世 · 第 {n} 世】一世沉浮，道果入腹"
                  f"（成功率 {chance:.0%}）——已逆活 {n}/9 世。\n"
                  f"消耗修为血气各 {cost:,}、潜力 {n}、寿元 {sy_cost:,} 年、"
                  f"元神 {LIFE_YUANSHEN * n:,}。冷却 30 分钟后 #逆活九世 继续。"), {}


def panel(doc: Any, now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    st = state_of(doc)
    lines = ["--- 己道 · 红尘仙 ---",
             f"推演层数：{st['layers']}/{LAYERS}"
             + ("（极巅减伤+10%）" if st["layers"] >= MILESTONE_10 else "")
             + ("（神胎）" if st["layers"] >= MILESTONE_15 else "")
             + f"｜劫灰 {st['ash']}"]
    if st.get("death_until") and now < float(st["death_until"]):
        lines.append(f"身灭道消恢复中：{int((float(st['death_until']) - now) / 60)} 分钟")
    lines.append(f"自创体系：{('【' + st['system_name'] + '】' + ' → '.join(st['realms'])) if st.get('system_name') else '未开创（#合道）'}")
    lines.append(f"红尘仙路：{'已解锁' if st.get('unlocked') else '未解锁（#推演红尘仙）'}"
                 f"｜世愿：{st.get('vow') or '未立'}｜已逆活 {st['life']}/9 世"
                 + ("｜【红尘仙】" if st.get("hongchen") else ""))
    lines.append("指令：#推演己道 ｜ #合道 ｜ #设立体系境界 ｜ #逆活九世 ｜ #我的红尘仙路")
    return "\n".join(lines)
