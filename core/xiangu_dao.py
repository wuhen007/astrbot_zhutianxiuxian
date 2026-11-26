"""仙古秘境 道种融合·神火四路·祭炼真我（W27）——原版 `xianguPlace.js`
道种查看 L4553 / 融合确认 L4662 / 取消 L4693 / 借助道种点燃 L4701 /
神火查看 L5121 / 苦修点燃 L5226 / 服丹点燃 L5357 / 祭炼真我 L5514 /
以身为种 L5744 + `xianguTribulation.js` 三千道火五幕（成功率 L145：
30% + 10%×极境 + min(道韵/5000, 10%)）+ 仙气（xianguXianqi.js）。

shortcut：
- 神火点燃成功 → 仙古境界钉到神火境（xg_level_of 对已点燃者取 max(推导, 8)）；
  端口主轨不动，属性走 ext["shenhuo"] 战斗乘区（handler 战斗回调套用）。
- 三千道火五幕同步推进，保留逐道伤疗、假死与复苏次序并汇成一条结算文本；
  原版异步逐条推播、装备/灵根防御及手动复活选择仍待入口和战斗接口移植。
- 六大极境：端口无独立极境旗标 → 极境数 = clamp(realm_index - 24, 0, 6)
  （神火境 8 = 主轨 24+；六大极境圆满 ≈ 主轨 30+），docstring 登记换算。
- 仙气：第一道由顶级仙种精确极境（仙古今世法 level 8 极境表存在同名配置）
  或祭炼真我修出；第二/三道由 #冲关极境 在神火境分流试炼（主轨冲关照旧）。
  仙气战斗加成简化为固定 +30%/道（原版仅对无仙气者生效）。
- 道火精粹液提纯：下品→中品→上品→极品→唯一，每档 1 份；提纯至极品/唯一
  且无仙气时补生第一道仙气（原版 #炼化道火精粹 等效）。

rng 约定：只用 rng.random()。
"""

from __future__ import annotations

import json
import inspect
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from . import xiangu as xg

FLAME_RATE = {"下品": 0.3, "中品": 0.5, "上品": 1.0, "极品": 1.5, "唯一": 2.0}
DAOZHONG_TO_SHENHUO = {"普通": "下品", "稀有": "中品", "传说": "上品", "神话": "极品"}
FLAME_LADDER = ("下品", "中品", "上品", "极品", "唯一")

FUSION_BASE = 0.5
FUSION_DAOYUN_BONUS = 0.005
FUSION_CORE_BONUS = 0.15
FUSION_INTERRUPT = 0.3
POTENTIAL_COST = 10
TRIB_ENERGY = 300_000            # 祭炼真我修为/血气（3 亿 ÷1000）
TRIB_DAOYUN = 500
IGNITE_ENERGY = 50_000           # 苦修根基（5000 万 ÷1000）

MEDICINE_MAP = {"神火丹": ("中品", 0.70), "九转神丹": ("上品", 0.85)}

# 五幕波次（占当前血量比例；负数为淬炼回血）
TRIB_WAVES: tuple[tuple[str, float], ...] = (
    ("第一重·引动道火·割肉裂魂", -0.10), ("大道符号缭绕，烧出大窟窿", -0.12),
    ("道火焚躯干、燃其精魂", -0.14), ("伤势加重，几近断开", -0.16),
    ("第二重·乾坤为炉·虚空凝鼎", 0.11), ("鼎内温养，肌体生辉", 0.11),
    ("道火反哺，道基凝实", 0.11),
    ("第三重·再疑·以火锻己", -0.09), ("几十种道火齐至，伤又出现", -0.11),
    ("以火锻己，再踏死地", -0.13),
    ("第四重·炉火纯青·一百零八道", -0.12), ("浑身焦黑如炭，窟窿上百处", -0.13),
    ("天地为熔炉·肉身即熔炉", -0.15),
    ("天地寂灭·如化石骸（三日假死）", -0.0), ("第五日·真我复苏", 0.50),
    ("第五重·三千道火齐现·上苍窥伺", -0.10), ("万道齐焚·终极洗礼", -0.12),
    ("道火灌顶，真我临界", -0.13),
)


# ---------------------------------------------------------------- 仙古境界（神火钉高）

def xg_level_of(doc: Any) -> int:
    """独立仙古轨优先；未导入/回炉前沿用现有主轨投影。"""
    from . import extra_cultivation
    if extra_cultivation.is_overridden(doc, "xiangu"):
        base = extra_cultivation.level_of(doc, "xiangu")
    else:
        base = xg.xg_level_of(doc)
    st = (getattr(doc, "ext", {}) or {}).get("xiangu") or {}
    sh = st.get("shenhuo") if isinstance(st, dict) else {}
    if isinstance(sh, dict) and sh.get("已点燃"):
        base = max(base, 8)
    return max(1, min(11, int(base)))
def extremes_completed(doc: Any) -> int:
    ext = getattr(doc, "ext", {}) or {}
    cultivation = ext.get("extra_cultivation") if isinstance(ext, dict) else None
    if isinstance(cultivation, dict) and "xiangu_extremes" in cultivation:
        try:
            return max(0, min(6, int(cultivation["xiangu_extremes"])))
        except (TypeError, ValueError):
            return 0
    ri = int(getattr(doc, "realm_index", 0) or 0)
    return max(0, min(6, ri - 24))
def extreme_name_of(doc: Any, seed_name: str, cfg: Mapping | None = None) -> str | None:
    """顶级仙种 → 神火极境名（需仙古今世法 level 8 极境表存在同名配置）。"""
    top = xg.find_top_seed(seed_name, cfg)
    if not top:
        return None
    extreme = f"神火极境·{top['名称']}"
    row8 = next((r for r in xg.load_xg_levels()
                 if int(r.get("level_id", 0) or 0) == 8), None) or {}
    if extreme in (row8.get("极境") or {}):
        return extreme
    return None


# ---------------------------------------------------------------- 神火状态

def shenhuo_of(st: Mapping) -> dict:
    sh = st.get("shenhuo")
    return sh if isinstance(sh, dict) else {}


def ignite(doc: Any, st: dict, way: str, quality: str, *, root: str = "",
           skill: str | None = None, extra: str | None = None,
           attrs: Mapping | None = None, extreme_name: str | None = None,
           now: float | None = None) -> dict:
    """写入神火状态（四路点燃共用）。"""
    st["shenhuo"] = {
        "已点燃": True, "点燃方式": way, "根基": root or way,
        "神火品质": quality, "属性倍率": FLAME_RATE.get(quality, 0.3),
        "专属技能": skill, "额外效果": extra,
        "属性加成": dict(attrs or {}),
        "极境达成": bool(extreme_name), "极境名称": extreme_name or "",
        "点燃时间": now if now is not None else time.time(),
    }
    st.setdefault("xianqi", 0)
    st.setdefault("xianqi_detail", [])
    return st["shenhuo"]


def xianqi_count(st: Mapping) -> int:
    return int(st.get("xianqi", 0) or 0)


def grant_xianqi(doc: Any, st: dict, src: str) -> bool:
    """修出一道仙气（≤3）。返回是否新增。"""
    n = xianqi_count(st)
    if n >= 3:
        return False
    st["xianqi"] = n + 1
    detail = st.setdefault("xianqi_detail", [])
    detail.append({"name": f"第{'一二三'[n]}道仙气", "src": src})
    return True


# 原版 xianguXianqi.js 试炼费率；本移植修为/血气统一为原版 /1000 单位。
XIANQI_TRIAL_COST_MULTIPLIERS = {2: 20, 3: 30}
XIANQI_TRIAL_POTENTIAL_COST = 10
XIANQI_TRIAL_CURRENCY_SCALE = 1_000


def _question_fortune_active(doc: Any, now: float | None = None) -> bool:
    """原版 applyQuestionFortuneCost：有效问道签将消耗乘 0.8 后向上取整。"""
    now = time.time() if now is None else float(now)
    ext = getattr(doc, "ext", {}) or {}
    fortune = ext.get("red_dust_fortune") if isinstance(ext, Mapping) else None
    if not isinstance(fortune, Mapping):
        legacy = ext.get("legacy_source") if isinstance(ext, Mapping) else None
        fortune = legacy.get("红尘仙缘签") if isinstance(legacy, Mapping) else None
    if not isinstance(fortune, Mapping) or fortune.get("type") != "question":
        return False
    try:
        expires = float(fortune.get("expiresAt", fortune.get("expires_at", 0)) or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    if expires > 1_000_000_000_000:
        expires /= 1000
    return expires > now


def _question_cost(doc: Any, amount: int, now: float | None = None) -> int:
    amount = max(0, int(amount))
    return int(math.ceil(amount * 0.8)) if _question_fortune_active(doc, now) else amount


def xianqi_trial_gate(doc: Any, st: Mapping[str, Any],
                      target_strand: int | None = None) -> dict[str, Any]:
    """Check original #冲关极境 order without mutating player or trial state."""
    current = xianqi_count(st)
    try:
        target = current + 1 if target_strand is None else int(target_strand)
    except (TypeError, ValueError, OverflowError):
        return {"allowed": False, "reason": "invalid_target", "current_strand": current,
                "target_strand": 0, "level": 0,
                "message": "【仙气极境·参数无效】请依次挑战第二、第三道仙气。"}
    level = xg_level_of(doc)
    if level != 8:
        return {"allowed": False, "reason": "realm", "current_strand": current,
                "target_strand": target, "level": level,
                "message": "【仙气极境·境界未至】第二、第三道仙气须在神火境挑战。"}
    if current < 1:
        return {"allowed": False, "reason": "first_strand_required", "current_strand": current,
                "target_strand": target, "level": level,
                "message": "【仙气极境·次序不合】须先取得第一道仙气。"}
    if current >= 3:
        return {"allowed": False, "reason": "complete", "current_strand": current,
                "target_strand": target, "level": level,
                "message": "【仙气极境·已圆满】三道仙气已成。"}
    expected = current + 1
    if target != expected or target not in XIANQI_TRIAL_COST_MULTIPLIERS:
        return {"allowed": False, "reason": "order", "current_strand": current,
                "target_strand": target, "expected_strand": expected, "level": level,
                "message": f"【仙气极境·次序不合】当前有 {current} 道仙气，只能挑战第 {expected} 道。"}
    return {"allowed": True, "reason": "ok", "current_strand": current,
            "target_strand": target, "level": level}


def xianqi_trial_requirements(doc: Any, st: Mapping[str, Any],
                              target_strand: int | None = None,
                              now: float | None = None) -> dict[str, Any]:
    """Return source-exact trial requirements and port-scaled currency amounts.

    Fixed source calculates 500000 * 2^(Xiangu level - 1), then multiplies by
    20/30 for the second/third strand and applies the active question-fortune
    discount. The port retains both original-unit values and its /1000 wallet
    amounts so a future command handler cannot confuse the two domains.
    """
    gate = xianqi_trial_gate(doc, st, target_strand)
    if not gate["allowed"]:
        return {**gate, "ready": False, "base_energy_original": 0,
                "energy_cost_original": 0, "energy_cost": 0,
                "potential_cost": 0, "missing_exp": 0, "missing_xueqi": 0,
                "missing_potential": 0}
    from . import wallet

    target = int(gate["target_strand"])
    base = 500_000 * (2 ** (int(gate["level"]) - 1))
    multiplier = XIANQI_TRIAL_COST_MULTIPLIERS[target]
    original_cost = _question_cost(doc, base * multiplier, now)
    energy_cost = int(math.ceil(original_cost / XIANQI_TRIAL_CURRENCY_SCALE))
    potential_cost = _question_cost(doc, XIANQI_TRIAL_POTENTIAL_COST, now)
    exp = max(0, int(getattr(doc, "exp", 0) or 0))
    xueqi = max(0, wallet.xueqi(doc))
    potential = max(0, int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0)))
    missing_exp = max(0, energy_cost - exp)
    missing_xueqi = max(0, energy_cost - xueqi)
    missing_potential = max(0, potential_cost - potential)
    ready = not (missing_exp or missing_xueqi or missing_potential)
    return {
        **gate, "ready": ready,
        "base_energy_original": base,
        "cost_multiplier": multiplier,
        "energy_cost_original": original_cost,
        "energy_cost": energy_cost,
        "potential_cost": potential_cost,
        "missing_exp": missing_exp,
        "missing_xueqi": missing_xueqi,
        "missing_potential": missing_potential,
    }


def pay_xianqi_trial_entry(doc: Any, st: Mapping[str, Any],
                           target_strand: int | None = None,
                           now: float | None = None) -> tuple[bool, dict[str, Any]]:
    """Validate all original gates, spend exp/xueqi before waves, and start full HP.

    Potential is only a gate here; as in the pinned source it is deducted after a
    successful trial. A failed trial keeps the existing strand count and potential.
    """
    from . import wallet

    requirements = xianqi_trial_requirements(doc, st, target_strand, now)
    if not requirements["allowed"] or not requirements["ready"]:
        return False, requirements
    cost = int(requirements["energy_cost"])
    doc.exp = max(0, int(doc.exp) - cost)
    wallet.set_xueqi(doc, wallet.xueqi(doc) - cost)
    hp_max = max(1, int((getattr(doc, "ext", {}) or {}).get("hp_max", 0) or xg._hp_max_of(doc)))
    doc.ext["hp_max"] = hp_max
    doc.ext["hp"] = hp_max
    requirements["resources_paid"] = True
    return True, requirements


def settle_xianqi_trial(doc: Any, st: dict, target_strand: int,
                        success: bool, max_hp: int | None = None,
                        now: float | None = None,
                        entry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Settle an already-paid strand trial; failure grants nothing, success records source.

    The command caller invokes this once after the pure wave schedule resolves.
    Failure preserves existing immortal qi and leaves 10% HP. Success debits the
    10 (or question-sign discounted 8) potential and grants the next strand; the
    third successful strand records the source completion marker.
    """
    if not isinstance(entry, dict) or not entry.get("resources_paid") or entry.get("settled"):
        return {"settled": False, "success": False, "reward": None,
                "message": "仙气试炼尚未支付入场资源，或该次结算已使用。"}
    requirements = entry
    current_gate = xianqi_trial_gate(doc, st, target_strand)
    if (not current_gate["allowed"]
            or int(requirements.get("target_strand", -1)) != int(target_strand)
            or int(requirements.get("current_strand", -1)) != xianqi_count(st)):
        entry["settled"] = True
        return {"settled": False, "success": False, "reward": None,
                "message": current_gate.get("message") or "仙气次序已变化，本次不会重复结算。"}
    hp_max = max(1, int(max_hp or (getattr(doc, "ext", {}) or {}).get("hp_max", 0)
                        or xg._hp_max_of(doc)))
    if not success:
        entry["settled"] = True
        doc.ext["hp_max"] = hp_max
        doc.ext["hp"] = max(1, int(hp_max * 0.10))
        return {"settled": True, "success": False, "reward": None,
                "target_strand": int(target_strand), "current_strand": xianqi_count(st),
                "potential_cost": 0, "message":
                f"试炼失败，既有 {xianqi_count(st)} 道仙气保留；境界不变，气血恢复至 10%。"}
    ext = getattr(doc, "ext", {}) or {}
    potential = max(0, int(float(ext.get("potential", 0) or 0)))
    potential_cost = int(requirements["potential_cost"])
    if potential < potential_cost:
        entry["settled"] = True
        # Resources are already committed before battle; the source potential gate
        # is checked on entry. Refuse a malformed/raced settlement without granting.
        return {"settled": False, "success": False, "reward": None,
                "target_strand": int(target_strand), "current_strand": xianqi_count(st),
                "potential_cost": potential_cost, "message":
                f"仙道潜力不足（需 {potential_cost}），仙气不会发放。"}
    ext["potential"] = potential - potential_cost
    source = f"神火境极境试炼·第{int(target_strand)}道"
    granted = grant_xianqi(doc, st, source)
    if not granted:
        entry["settled"] = True
        ext["potential"] = potential
        return {"settled": False, "success": False, "reward": None,
                "target_strand": int(target_strand), "current_strand": xianqi_count(st),
                "potential_cost": potential_cost, "source": source,
                "message": "仙气次序已变化，未发放重复仙气。"}
    entry["settled"] = True
    if int(target_strand) == 3:
        st["xianqi_three_complete"] = True
        doc.ext["xiangu_xianqi_three_complete"] = True
        detail = st.get("shenhuo")
        if isinstance(detail, dict):
            detail["三道仙气圆满"] = True
    doc.ext["hp_max"] = hp_max
    return {"settled": True, "success": True,
            "target_strand": int(target_strand), "current_strand": xianqi_count(st),
            "potential_cost": potential_cost, "source": source,
            "reward": {"仙气": 1, "道数": xianqi_count(st), "来源": source},
            "message": f"第 {target_strand} 道仙气修成（仙道潜力 −{potential_cost}，共 {xianqi_count(st)} 道）。"}


def combat_mult(st: Mapping) -> float:
    """神火 + 仙气战斗乘区（handler 战斗回调套用）。"""
    sh = shenhuo_of(st)
    mult = 1.0
    if sh.get("已点燃"):
        mult += 0.10 * float(sh.get("属性倍率", 0.3) or 0.3)
    mult += 0.30 * xianqi_count(st)
    return mult


# ---------------------------------------------------------------- 面板

def shenhuo_text(doc: Any, st: Mapping) -> str:
    sh = shenhuo_of(st)
    if not sh.get("已点燃"):
        return "\n".join([
            "【神火查看·尚未点燃】", "",
            f"{getattr(doc, 'name', '') or '修士'}感应体内...丹田空空如也，神火尚未点燃！", "",
            "【点燃神火方式】",
            "• #点燃神火（自身苦修·下品）",
            "• #服用XXX点燃神火（天材地宝·中品/上品）",
            "• #借助XX道种点燃神火（核心区域，品质对应，顶级仙种修仙气）",
            "• #祭炼真我（三千道火淬炼·唯一，火道禁区·修仙气）"])
    n = xianqi_count(st)
    detail = st.get("xianqi_detail") or []
    elapsed = max(0, int(time.time() - float(sh.get("点燃时间", 0) or 0)))
    attrs = sh.get("属性加成") or {}
    attr_text = "、".join(f"{k}+{v}" for k, v in attrs.items()) if attrs else "无"
    lines = ["【神火状态】🔥", "",
             f"{getattr(doc, 'name', '') or '修士'}体内神火熊熊燃烧...", "",
             "【神火信息】",
             f"根基：{sh.get('根基') or '自身神火'}",
             f"品质：{sh.get('神火品质', '下品')}（×{float(sh.get('属性倍率', 0.3)):.1f} 倍率）",
             f"仙气：{n}/3 道",
             f"道火精粹液：{int(st.get('daohuo_jingcui', 0) or 0)} 份（#炼化道火精粹 提纯）",
             f"点燃于 {elapsed // 3600} 小时 {(elapsed % 3600) // 60} 分钟前", "",
             "【仙气道果】" + ("；".join(f"{d.get('name')}（{d.get('src')}）" for d in detail)
                             if detail else "尚未修出仙气"),
             "",
             f"【专属技能】{sh.get('专属技能') or '无专属技能'}",
             f"【属性加成】{attr_text}",
             f"【额外效果】{sh.get('额外效果') or '无'}", "",
             ("• 三道仙气已在神火境内圆满" if n >= 3 else
              "• 神火境使用 #冲关极境，可依次挑战下一道仙气" if n > 0 else
              "• 只有极品仙种或三千道火点燃神火时能修出第一道仙气")]
    return "\n".join(lines)


def seed_detail_text(doc: Any, st: Mapping, cfg: Mapping | None = None) -> str:
    """#查看道种 分品质详表（W27 增强版）。"""
    seeds = usable_seeds(doc, st, cfg)
    if not seeds:
        return ("【道种查看·空空如也】\n尚未获得任何道种。\n\n【获取途径】\n"
                "• #秘境探索 机缘格\n• 击杀秘境 Boss\n• 唯一机缘 / NPC 交易")
    buckets: dict[str, list[dict]] = {"神话": [], "传说": [], "稀有": [], "普通": []}
    for rec in seeds:
        buckets.setdefault(str(rec.get("品质") or "普通"), []).append(rec)
    lines = ["【道种查看】", "",
             "感应体内道种...", "",
             f"【道种统计】总计 {len(seeds)} 枚｜" +
             "｜".join(f"{q}：{len(buckets.get(q, ()))}" for q in ("神话", "传说", "稀有", "普通"))]
    icons = {"神话": "★", "传说": "◆", "稀有": "○", "普通": "·"}
    for q in ("神话", "传说", "稀有", "普通"):
        bucket = buckets.get(q) or []
        if not bucket:
            continue
        lines.append("")
        lines.append(f"【{q}道种】")
        for rec in bucket:
            lines.append(f"{icons[q]} {rec['名称']} [{rec.get('类型') or '?'}]"
                         f"｜融合成功率 {float(rec.get('融合成功率', 0.6)) * 100:.0f}%")
            if rec.get("专属技能"):
                lines.append(f"  专属技能：{rec['专属技能']}")
            if rec.get("额外效果"):
                lines.append(f"  额外效果：{rec['额外效果']}")
            if rec.get("顶级道种"):
                lines.append("  顶级仙种：可在核心区域融合达成神火极境（第一道仙气）")
    lines += ["", "【融合提示】核心区域 #借助XX道种点燃神火；道种品质越高成功率越高"]
    return "\n".join(lines)



# ---------------------------------------------------------------- 融合（道种孕育路线）

def usable_seeds(doc: Any, st: Mapping, cfg: Mapping | None = None) -> list[dict]:
    """秘境背包 + 常驻道种库（ext["xiangu_seeds"]，撤离时转入）的可用道种档案。"""
    out: list[dict] = []
    for s in (st.get("bag") or {}).get("seeds", ()):
        rec = xg.resolve_seed_record(s, cfg)
        if rec:
            out.append(rec)
    ext = getattr(doc, "ext", {}) or {}
    for raw in ext.get("xiangu_seeds", ()) or ():
        try:
            rec = xg.resolve_seed_record(json.loads(raw), cfg) if isinstance(raw, str) \
                else xg.resolve_seed_record(raw, cfg)
        except Exception:
            rec = None
        if rec:
            out.append(rec)
    return out


def fusion_rate(doc: Any, st: Mapping, seed: Mapping, in_core: bool) -> float:
    daoyun = int((st.get("gains") or {}).get("daoyun", 0) or 0)
    rate = (FUSION_BASE + daoyun * FUSION_DAOYUN_BONUS
            + (FUSION_CORE_BONUS if in_core else 0.0)
            + (float(seed.get("融合成功率", 0.6) or 0.6) - 0.6))
    return max(0.05, min(0.95, rate))


def fusion_intent(doc: Any, st: dict, name_or_idx: str,
                  cfg: Mapping | None = None, now_ms: float = 0.0) -> tuple[str, dict | None]:
    """#借助XX道种点燃神火：校验 + 记录 60 秒确认意图。返回 (text, intent)。"""
    map_st = st.get("map") or {}
    if not st.get("active"):
        return "【道种融合·未入秘境】需先进入仙古秘境才可进行道种融合。", None
    if str(st.get("location") or "") != "核心区域" and \
            xg.FRAGMENTS.get(map_st.get("fragment_id", ""), {}).get("zone") != "核心区域":
        return ("【道种融合·位置不符】道种融合必须在核心区域进行！\n"
                f"当前区域：{st.get('location')}（#秘境移动 前往核心）"), None
    if shenhuo_of(st).get("已点燃"):
        return "【道种融合·神火已燃】神火既已点燃，便不可再次融合道种（#查看神火）。", None
    seeds = usable_seeds(doc, st, cfg)
    if not seeds:
        return "【道种融合·无种可融】体内空空如也——探索机缘格 / 击杀 Boss 获取道种。", None
    selected: dict | None = None
    arg = str(name_or_idx or "").strip()
    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(seeds):
            selected = seeds[idx]
    else:
        canon = xg.normalize_seed_name(arg)
        selected = next((s for s in seeds
                         if canon in xg.normalize_seed_name(str(s.get("名称")))
                         or str(s.get("名称")) in arg), None)
    if selected is None:
        lines = ["【道种融合·选择道种】", ""]
        for i, s in enumerate(seeds, 1):
            mark = {"神话": "★", "传说": "◆", "稀有": "○"}.get(str(s.get("品质")), "·")
            lines.append(f"【{i}】{mark} {s['名称']}｜{s.get('品质')}｜"
                         f"成功率 {float(s.get('融合成功率', 0.6)) * 100:.0f}%")
        lines += ["", "发送 #借助XX道种点燃神火（核心区域成功率 +15%）"]
        return "\n".join(lines), None
    in_core = xg.FRAGMENTS.get(map_st.get("fragment_id", ""), {}).get("zone") == "核心区域"
    rate = fusion_rate(doc, st, selected, in_core)
    ext = extreme_name_of(doc, str(selected.get("名称")), cfg)
    st["fusion"] = {"seed": str(selected.get("名称")), "expires_at": now_ms + 60_000}
    return "\n".join([
        "【道种融合·确认】", "",
        f"准备融合：{'★' if selected.get('顶级道种') else '·'} {selected['名称']}",
        f"品质：{selected.get('品质')}｜类型：{selected.get('类型')}",
        f"专属技能：{selected.get('专属技能') or '无'}", "",
        f"【最终成功率】：{rate * 100:.1f}%（基础 50% + 道韵加成 + 核心区域 +15% + 品质加成）",
        f"【失败惩罚】道种损毁（三成概率遭禁制打断，另损血气）",
        (f"【顶级仙种】融合达成 → {ext}（修出第一道仙气）" if ext else ""), "",
        "【确认提示】60 秒内发送 #确认融合道种 或 #取消融合道种"]), st["fusion"]


def fusion_confirm(doc: Any, st: dict, rng: Callable[[], float], now_ms: float,
                   cfg: Mapping | None = None) -> tuple[str, dict]:
    """#确认融合道种：打断/失败/成功三态。返回 (text, events)。"""
    events: dict[str, Any] = {}
    intent = st.get("fusion")
    if not isinstance(intent, dict) or now_ms > float(intent.get("expires_at", 0) or 0):
        st.pop("fusion", None)
        return "当前没有待确认的道种融合，或确认已超时。", events
    seed_name = str(intent.get("seed") or "")
    st.pop("fusion", None)
    seeds = usable_seeds(doc, st, cfg)
    seed = next((s for s in seeds if s.get("名称") == seed_name), None)
    if seed is None:
        return f"道种【{seed_name}】已不在身，融合作废。", events
    # 消耗：背包与常驻库两处同名道种一并移除（损毁/融合只此一份）
    bag_seeds = st["bag"].get("seeds", [])
    for i, s in enumerate(bag_seeds):
        nm = str(s.get("名称") if isinstance(s, dict) else s)
        if nm == seed_name:
            bag_seeds.pop(i)
            break
    _doc_ext = getattr(doc, "ext", None)
    if isinstance(_doc_ext, dict) and isinstance(_doc_ext.get("xiangu_seeds"), list):
        kept = []
        for raw in _doc_ext["xiangu_seeds"]:
            try:
                nm = str((json.loads(raw) if isinstance(raw, str) else raw).get("名称") or "")
            except Exception:
                nm = ""
            if nm != seed_name:
                kept.append(raw)
        _doc_ext["xiangu_seeds"] = kept
    in_core = xg.FRAGMENTS.get((st.get("map") or {}).get("fragment_id", ""), {}).get("zone") == "核心区域"
    rate = fusion_rate(doc, st, seed, in_core)
    # 三成概率禁制打断
    if rng.random() < FUSION_INTERRUPT:
        hp_loss = max(1, int(xg._hp_of(doc) * 0.2))
        xg._set_hp(doc, max(1, xg._hp_of(doc) - hp_loss))
        return "\n".join([
            "【道种融合·被打断！】", "",
            "一股狂暴气息袭来——有人在附近触发秘境禁制！",
            "你心神失守，融合失败！", "",
            f"【损失】道种：{seed_name}（已损毁）｜血气 -{hp_loss:,}"]), events
    if rng.random() >= rate:
        return "\n".join([
            "【道种融合·失败】", "",
            "道种与道果的共鸣突然中断！", "",
            f"【损失】道种：{seed_name}（已损毁）", "",
            "提示：道韵越高，融合成功率越高（每点道韵 +0.5%）"]), events
    # 成功
    extreme = extreme_name_of(doc, seed_name, cfg)
    quality = "极品" if extreme else DAOZHONG_TO_SHENHUO.get(str(seed.get("品质")), "下品")
    sh = ignite(doc, st, "道种孕育", quality, root=seed_name,
                skill=seed.get("专属技能"), extra=seed.get("额外效果"),
                attrs=seed.get("属性加成") or {}, extreme_name=extreme)
    if extreme and xianqi_count(st) == 0:
        grant_xianqi(doc, st, f"神火点燃·{seed_name}")
    events["ignited"] = True
    return "\n".join([
        "【道种融合·成功！！！】", "",
        f"体内道果轰然震动！{seed_name}化作一道流光冲入丹田！",
        "在光芒中，神火熊熊燃起，经久不熄！", "",
        "【神火点燃】",
        f"品质：{sh['神火品质']}（×{sh['属性倍率']:.1f} 倍率）",
        f"专属技能：{sh.get('专属技能') or '无'}",
        (f"【道种极境】{extreme}（修出第一道仙气）" if extreme
         else "【神火根基】已点燃，未达成顶级道种极境"), "",
        "使用 #查看神火 查看详情"]), events


# ---------------------------------------------------------------- 苦修 / 服丹

def _potential_pay(doc: Any, st: dict) -> str | None:
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < POTENTIAL_COST:
        return (f"【仙道潜力不足】点燃神火需消耗 {POTENTIAL_COST} 点仙道潜力"
                f"（当前：{pot} 点）。")
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["potential"] = pot - POTENTIAL_COST
    return None


def ignite_self(doc: Any, st: dict, rng: Callable[[], float],
                inv: Mapping[str, int] | None = None) -> tuple[str, dict]:
    """#点燃神火（苦修）：尊者境 + 潜力 10 + 修为血气各 5 万；60% 下品。"""
    events: dict[str, Any] = {}
    if not st.get("active"):
        return "【点燃神火·未入秘境】需先进入仙古秘境！", events
    if shenhuo_of(st).get("已点燃"):
        return "【点燃神火·已点燃】你体内神火早已燃起（#查看神火）。", events
    if xg_level_of(doc) < 7:
        return f"【点燃神火·境界不足】自身修炼点燃神火需在尊者境方可尝试（当前 {xg.realm_name(xg_level_of(doc))}）。", events
    poor = _potential_pay(doc, st)
    if poor:
        return poor, events
    from . import wallet
    # 原版：雄厚根基是「门槛」而非消耗；失败另扣 5% 修为
    if int(getattr(doc, "exp", 0) or 0) < IGNITE_ENERGY or wallet.xueqi(doc) < IGNITE_ENERGY:
        return (f"【点燃神火·根基未足】苦修点燃神火需雄厚根基，"
                f"修为/血气需各达 {IGNITE_ENERGY:,}。"), events
    if rng.random() > 0.6:
        loss = int(int(getattr(doc, "exp", 0) or 0) * 0.05)
        doc.exp = max(0, int(doc.exp) - loss)
        return "\n".join([
            "【点燃神火·苦修失败】",
            "苦修引动神火，却始终差一线契机...道果震颤，神火未能成型。", "",
            f"【损失】修为 -{loss:,}（道基受创）"]), events
    sh = ignite(doc, st, "苦修", "下品", root="苦修·凡火")
    events["ignited"] = True
    return "\n".join([
        "【神火点燃·成功（凡火）】", "",
        "自身修炼，终于引动神火！神火虽黯淡，却也是踏入神道领域的根基。", "",
        "【神火品质】下品（×0.3 倍率）",
        "【可逆追赶】日后以 #炼化道火精粹 逐步提纯至唯一真火！", "",
        "使用 #查看神火 查看详情"]), events


def ignite_medicine(doc: Any, st: dict, medicine: str, rng: Callable[[], float],
                    consume: Callable[[str, int], bool]) -> tuple[str, dict]:
    """#服用XXX点燃神火：神火丹 0.7 中品 / 九转神丹 0.85 上品。"""
    events: dict[str, Any] = {}
    med = str(medicine or "").strip()
    if not st.get("active"):
        return "【服用丹药·未入秘境】需先进入仙古秘境！", events
    if shenhuo_of(st).get("已点燃"):
        return "【服用丹药·已点燃】你体内神火早已燃起（#查看神火）。", events
    if xg_level_of(doc) < 7:
        return f"【服用丹药·境界不足】服丹点燃神火需尊者境（当前 {xg.realm_name(xg_level_of(doc))}）。", events
    poor = _potential_pay(doc, st)
    if poor:
        return poor, events
    cfg = MEDICINE_MAP.get(med)
    if cfg is None:
        return ("【服用丹药·无法炼化】目前支持：神火丹（中品·70%）、九转神丹（上品·85%）。"
                "\n用法：#服用神火丹点燃神火"), events
    if not consume(med, 1):
        return f"【服用丹药·丹药缺失】翻遍纳戒却找不到【{med}】！需先获得该丹药。", events
    quality, rate = cfg
    if rng.random() >= rate:
        return "\n".join([
            "【服用丹药·炼化失败】",
            f"体内丹力失控，神火未能成型...【{med}】已耗尽，道基受创。"]), events
    sh = ignite(doc, st, "天材地宝", quality, root=f"{med}·神火")
    events["ignited"] = True
    return "\n".join([
        f"【神火点燃·成功（{quality}）】", "",
        f"服下【{med}】，丹力化火，神火轰然燃起！", "",
        f"【神火品质】{quality}（×{sh['属性倍率']:.1f} 倍率）",
        "【可逆追赶】日后以 #炼化道火精粹 提纯至极品/唯一神火并补生第一道仙气！", "",
        "使用 #查看神火 查看详情"]), events


# ---------------------------------------------------------------- 祭炼真我（三千道火）

def jilian_gate(doc: Any, st: dict) -> str | None:
    """祭炼真我五重门：未入/已燃/境界/极境/场所/道韵/潜力/本源。"""
    if not st.get("active"):
        return "【祭炼真我·未入秘境】需先进入仙古秘境！"
    if shenhuo_of(st).get("已点燃"):
        return ("【祭炼真我·路线冲突】体内已有神火燃烧，祭炼真我的道路已经封闭！\n"
                "“神火已燃，道种已定，难再祭炼真我...”")
    lv = xg_level_of(doc)
    if lv < 7:
        return f"【祭炼真我·境界不足】需尊者境方可尝试（当前 {xg.realm_name(lv)}）。"
    ext_n = extremes_completed(doc)
    if ext_n < 6:
        return ("\n".join(["【祭炼真我·极境未满】",
                           "祭炼真我，需道基无暇，六大极境缺一不可！", "",
                           f"当前极境进度：{ext_n}/6"
                           "（神火境 8 = 主轨 24 起，每主轨境折算一重极境）"]))
    zone = xg.FRAGMENTS.get((st.get("map") or {}).get("fragment_id", ""), {}).get("zone")
    if zone != "火道禁区":
        return (f"【祭炼真我·场所不符】祭炼真我需在火道禁区·三千青石阶感悟大道，"
                f"当前：{st.get('location')}。")
    daoyun = int((st.get("gains") or {}).get("daoyun", 0) or 0)
    if daoyun < TRIB_DAOYUN:
        return (f"【祭炼真我·道韵不足】需 {TRIB_DAOYUN} 点道韵方可感悟祭炼真我大道，"
                f"当前：{daoyun} 点。")
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < POTENTIAL_COST:
        return (f"【仙道潜力不足】祭炼真我冲关需消耗 {POTENTIAL_COST} 点仙道潜力"
                f"（当前：{pot} 点）。")
    from . import wallet
    if int(getattr(doc, "exp", 0) or 0) < TRIB_ENERGY or wallet.xueqi(doc) < TRIB_ENERGY:
        return f"【祭炼真我·本源不足】需 {TRIB_ENERGY:,} 修为和血气。"
    return None


async def tribulation_run(doc: Any, st: dict, rng: Any,
                           now: float,
                           wave_runner: Callable[[Any, int, int, str, Any], Mapping | None] | None = None
                           ) -> tuple[str, dict]:
    """执行三千道火五重试炼，返回聚合文本及逐消息事件。

    固定原版 `xianguTribulation.js`：每道伤害按血量上限 × 原始比例 ×
    (1 + 3% × 道数) 计算；第 2 重三次各恢复上限的 11%；第 4 重假死后
    第五日恢复至 50%。`wave_runner` 接收原始伤害，可在入口层套用灵根、
    帝兵、已激活功法防御及致死复活，并返回 `hp/dead/damage/revival/messages`。
    `events["stream"]` 保留原版分段播报与等待时长，旧调用仍能读取单条聚合文本。
    """
    events: dict[str, Any] = {"waves": [], "stream": []}
    from . import wallet

    daoyun = int((st.get("gains") or {}).get("daoyun", 0) or 0)
    doc.exp = max(0, int(doc.exp) - TRIB_ENERGY)
    wallet.set_xueqi(doc, max(0, wallet.xueqi(doc) - TRIB_ENERGY))
    st["gains"]["daoyun"] = daoyun - TRIB_DAOYUN

    hp_max = max(1, int(float((getattr(doc, "ext", {}) or {}).get("hp_max", 0) or 0)) or xg._hp_of(doc))
    hp = hp_max
    xg._set_hp(doc, hp)

    def emit(text: str, delay_after: float = 0.0, **meta: Any) -> None:
        events["stream"].append({"text": text, "delay_after": float(delay_after), **meta})

    def bar(current: int) -> str:
        pct = max(0, min(100, int(current * 100 / hp_max)))
        return f"剩余血量：{current:,}/{hp_max:,}（肉身完整度 {pct}%）"

    emit("\n".join([
        "【祭炼真我·以天地为炉】", "",
        f"{getattr(doc, 'name', '') or '修士'}立于仙古花蕾之下，三千青石路无声。",
        "不借外物，以三千大道为火，祭炼肉身与元神！", "",
        "以天地为炉，以万道为火，焚肉身，烧元神，筑真我。",
        "这条路古来走者多形神俱灭。", "",
        "结算顺序：灵根减伤／本命帝兵护主／致死复活／复活后功法被动", "",
        bar(hp),
    ]), 1.6, kind="intro")

    name = getattr(doc, "name", "") or "修士"
    stages = (
        {
            "name": "第一重·引动道火·割肉裂魂",
            "intro": [
                f"【第一重·引动道火·割肉裂魂】\n\n{name}引动十几条青石路上的大道道则。",
                "道符缭绕肉身，炽盛火光烧出大窟窿，血肉模糊、露出白骨。",
                "道则烧其躯干、燃其精魂，如仙剑割肉裂魂。\n\n——道火劫报——",
            ],
            "waves": (("十几道道则如仙剑斩来，割肉裂魂", 0.10),
                      ("大道符号缭绕，烧出大窟窿", 0.12),
                      ("道火焚躯干、燃其精魂", 0.14),
                      ("伤势加重，几近断开", 0.16)),
            "summary": [
                f"{name}终于明白，为何古来走另类成神路者皆殒落。",
                "火道并非一味熬烧，必须转变思路，以天地为炉。",
                "【阶段渡过】第一重道火告一段落",
            ],
        },
        {
            "name": "第二重·乾坤为炉·虚空凝鼎",
            "intro": [
                "【第二重·乾坤为炉·虚空凝鼎】", "",
                f"{name}叱喝：乾坤为炉！虚空扭曲，体外凝出炉鼎，将自身收在其中。",
                "道火转而煅烧炉鼎，火威骤减，伤体渐愈、肌体生辉。\n\n——道火劫报（炉鼎护身，反受其淬）——",
            ],
            "heals": (("鼎壁隔绝道火，伤体渐愈·第一缕", 0.11),
                      ("鼎内温养，肌体生辉·第二缕", 0.11),
                      ("道火反哺，道基凝实·第三缕", 0.11)),
            "summary": [
                f"鼎内温养三道，{name}血肉重塑、道基初凝。",
                "【阶段渡过】炉火炼真我，第二重道火告一段落",
            ],
            "intro_delay": 2.0,
        },
        {
            "name": "第三重·再疑·以火锻己",
            "intro": [
                "【第三重·再疑·以火锻己】", "",
                f"{name}发现温和的炉火只护住自身，并非以万道为火锻造真我。",
                "鼎仍在，火势却更盛，几十种道火刺透躯体，伤势再起。\n\n——道火劫报——",
            ],
            "waves": (("盛烈刺透躯体，浑身喷火", 0.09),
                      ("几十种道火齐至，伤势复现", 0.11),
                      ("以火锻己，再踏死地", 0.13)),
            "summary": ["道火再次归于炉鼎，真我道基继续承压。",
                        "【阶段渡过】第三重道火告一段落"],
        },
        {
            "name": "第四重·炉火纯青·一百零八道",
            "intro": [
                "【第四重·炉火纯青·一百零八道】", "",
                f"一百零八道火焰齐聚，{name}只引小火慢慢适应。",
                "血肉焦黑、大小伤痕遍布，天地渐成熔炉。\n\n——道火劫报——",
            ],
            "waves": (("一百零八道火焰齐聚，血肉干枯", 0.12),
                      ("浑身焦黑如炭，窟窿上百处", 0.13),
                      ("天地为熔炉·肉身即熔炉，火光涌入", 0.15)),
            "summary": ["炉火暂歇，肉身与元神坠入寂灭边缘。",
                        "【阶段渡过】第四重道火告一段落"],
        },
        {
            "name": "第五重·三千道火齐现·上苍窥伺",
            "intro": [
                "【第五重·三千道火齐现·上苍窥伺】", "",
                "仙道花蕾三千花瓣对应三千青石路，大道火光次第亮起。",
                "上苍窥伺，万道齐焚，这是终极道火洗礼。\n\n——道火劫报——",
            ],
            "waves": (("三千大道火光齐现，上苍窥伺", 0.10),
                      ("万道齐焚·终极洗礼", 0.12),
                      ("道火灌顶，真我临界", 0.13)),
            "summary": ["三千大道火光归于一处，等待最终祭炼结果。",
                        "【阶段渡过】第五重道火告一段落"],
        },
    )

    wave_no = 0
    died_at = ""
    for stage_index, stage in enumerate(stages):
        emit("\n".join(stage["intro"]), float(stage.get("intro_delay", 1.5)),
             kind="stage_intro", stage=stage["name"])
        if "heals" in stage:
            heals = stage["heals"]
            for heal_index, (note, fraction) in enumerate(heals):
                recovered = int(hp_max * fraction)
                before = hp
                hp = min(hp_max, hp + recovered)
                xg._set_hp(doc, hp)
                actual = hp - before
                message = "\n".join([
                    f"【第二重·第{heal_index + 1}道淬炼】", "",
                    f"道火淬炼｜{note}｜恢复 {actual:,} 点血量", "", bar(hp),
                ])
                delay = 3.5 if heal_index < len(heals) - 1 else 0.0
                emit(message, delay, kind="heal", stage=stage["name"], hp=hp,
                     amount=actual, wave=heal_index + 1)
        else:
            for note, fraction in stage["waves"]:
                wave_no += 1
                raw_damage = max(1, int(hp_max * fraction * (1 + 0.03 * wave_no)))
                outcome: Mapping[str, Any] = {}
                if wave_runner is not None:
                    try:
                        raw = wave_runner(doc, raw_damage, wave_no, stage["name"], rng)
                        if inspect.isawaitable(raw):
                            raw = await raw
                        if isinstance(raw, Mapping):
                            outcome = raw
                    except Exception as exc:
                        # A callback failure must not silently award the route.
                        outcome = {"dead": True, "hp": 0,
                                   "messages": [f"防御/复活结算失败：{type(exc).__name__}"],
                                   "callback_error": True}
                else:
                    damage = max(1, raw_damage)
                    hp = max(0, hp - damage)
                    outcome = {"damage": damage, "hp": hp, "dead": hp <= 0,
                               "messages": [f"道火原始伤害 {damage:,}（防御/复活回调未接入）"]}
                if "hp" in outcome:
                    hp = max(0, min(hp_max, int(outcome.get("hp") or 0)))
                    xg._set_hp(doc, hp)
                else:
                    ext = getattr(doc, "ext", {}) or {}
                    hp = max(0, min(hp_max, int(ext.get("hp", hp) or 0)))
                dead = bool(outcome.get("dead", hp <= 0))
                lines = [f"第{wave_no}道劫｜{note}"]
                lines.extend(str(line) for line in outcome.get("messages", ()) or ())
                if outcome.get("revival"):
                    lines.append(f"道火致死时触发{outcome['revival']}，恢复至 {hp:,} 点并避过本道劫。")
                elif not outcome.get("avoided"):
                    lines.append(f"道火结算后实受 {int(outcome.get('damage', raw_damage) or 0):,} 点伤害。")
                lines.extend(["", bar(hp)])
                events["waves"].append({
                    "number": wave_no, "stage": stage["name"], "note": note,
                    "raw_damage": raw_damage, "damage": int(outcome.get("damage", raw_damage) or 0),
                    "hp": hp, "dead": dead, "revival": outcome.get("revival"),
                })
                emit("\n".join(lines), 3.0 if dead else 3.5,
                     kind="wave", stage=stage["name"], wave=wave_no,
                     hp=hp, dead=dead, raw_damage=raw_damage)
                if dead:
                    died_at = note
                    break
        if died_at:
            break
        emit("\n".join(stage["summary"]), 3.0,
             kind="stage_summary", stage=stage["name"])

        if stage_index == 3:
            hp = 1
            xg._set_hp(doc, hp)
            emit("\n".join([
                "【天地寂灭·如化石骸】", "",
                "乾坤炉鼎化去，一百零八道火消退。",
                f"{name}坠落青石阶，通体焦黑、皮包骨头，一动也不能动。",
                "外界哗然：妄自而为，烧废了！", "……（三日寂灭，生气渐消）", "",
                f"剩余血量：1/{hp_max:,}（肉身完整度 0%·假死）",
            ]), 3.2, kind="fake_death", hp=1)
            hp = max(1, int(hp_max * 0.50))
            xg._set_hp(doc, hp)
            emit("\n".join([
                "第五日。", f"{name}猛地睁眼，真我复苏！",
                "一百零八处伤痕内，有火光跳动，圣焰滋养全身。", "炉火纯青，这一步走到了头。", "",
                f"——道火劫报（真我复苏）——恢复 {max(0, hp - 1):,} 点血量", "", bar(hp),
            ]), 2.4, kind="revival", hp=hp)

    rate = 0.30 + extremes_completed(doc) * 0.10 + min(daoyun / 5000.0, 0.10)
    rate = min(1.0, rate)
    success_roll = None if died_at else float(rng.random())
    success = not died_at and success_roll <= rate
    events["success_rate"] = rate
    events["success_roll"] = success_roll
    events["dead_at"] = died_at or None
    events["success"] = success

    if not success:
        reason = f"（陨于「{died_at}」）" if died_at else ""
        final_text = "\n".join([
            "【祭炼真我·天地不容】", "",
            f"{name}未能令三千道火归一，真火在最后一刻溃散。{reason}",
            "道基崩裂，境界跌落；血气与当前气血恢复至上限。", "",
            f"（本次成功率 {rate * 100:.0f}%：30% 基础 +10%/极境 + 道韵加成）",
        ])
        emit(final_text, 0.0, kind="result", success=False)
        return "\n".join(row["text"] for row in events["stream"]), events
    sh = ignite(doc, st, "祭炼真我", "唯一", root="祭炼真我·唯一真火",
                skill="草字剑诀", extra="不受秘境境界压制·天地共鸣")
    grant_xianqi(doc, st, "祭炼真我·三千道火淬炼")
    st["daohuo_jingcui"] = int(st.get("daohuo_jingcui", 0) or 0) + 1
    st.setdefault("titles", [])
    if "祭炼真我" not in st["titles"]:
        st["titles"].append("祭炼真我")
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        potential = int(float(ext.get("potential", 0) or 0))
        ext["potential"] = max(0, potential - POTENTIAL_COST)
    events["ignited"] = True
    events["technique"] = "草字剑诀"
    final_text = "\n".join([
        "【祭炼真我·天地共鸣！！！】", "",
        "三千大道火光归一，肉身与元神熬炼无瑕！",
        "一道绝世剑意从体内冲出——获得草字剑诀。", "",
        "【神火点燃】不借外物，天地间唯一不灭的真火燃起！",
        f"神火品质：唯一 ×{sh['属性倍率']:.1f} 倍率",
        "【渡劫造化】道火精粹液 ×1｜道韵消耗 500",
        f"【仙道潜力】-{POTENTIAL_COST}", "【称号】祭炼真我",
        "【仙气极境】第一道仙气已成；#冲关极境 可依次挑战第二、第三道仙气。", "",
        f"（成功率 {rate * 100:.0f}%）",
    ])
    emit(final_text, 0.0, kind="result", success=True)
    return "\n".join(row["text"] for row in events["stream"]), events


def settle_tribulation_failure(doc: Any, st: dict | None = None, now: float | None = None,
                               *, hp_max: int | None = None,
                               xueqi_max: int | None = None) -> dict[str, int]:
    """Apply the pinned original's failed祭炼 aftermath."""
    from . import wallet

    ext = getattr(doc, "ext", {}) or {}
    hp_cap = max(1, int(hp_max or ext.get("hp_max", 0) or xg._hp_max_of(doc)))
    xueqi_cap = max(1, int(xueqi_max or ext.get("xueqi_max", 0) or hp_cap))
    doc.realm_index = max(0, int(getattr(doc, "realm_index", 0) or 0) - 1)
    xg._set_hp(doc, hp_cap)
    wallet.set_xueqi(doc, xueqi_cap)
    return {"realm_index": int(doc.realm_index), "hp": hp_cap, "xueqi": xueqi_cap}

def yishenweizhong_text(doc: Any) -> str:
    lv = xg_level_of(doc)
    if lv < 11:
        return ("\n".join(["【以身为种·境界不足】",
                           "以身为种是天神绝巅冲击虚道境的道路，并非尊者境点燃神火之法。",
                           f"当前仙古境界：{xg.realm_name(lv)}；需先达到天神境。"]))
    if lv > 11:
        return "【以身为种】你已越过虚道境，无需再次欺天种道。"
    return "\n".join([
        "【以身为种·道路已明】",
        "你已至天神绝巅，可舍弃外界道种，以人体为种开启体内众门。",
        "使用 #冲关，引动上苍天谴并冲击虚道境。"])


# ---------------------------------------------------------------- 道火精粹提纯 / 仙气试炼

def refine_shenhuo(doc: Any, st: dict) -> tuple[bool, str]:
    """#炼化道火精粹：品质升一档；极品/唯一补生第一道仙气。"""
    sh = shenhuo_of(st)
    if not sh.get("已点燃"):
        return False, "【炼化道火精粹·无火可炼】尚未点燃神火。"
    n = int(st.get("daohuo_jingcui", 0) or 0)
    if n < 1:
        return False, "【炼化道火精粹·精粹不足】需 1 份道火精粹液（三千道火试炼/祭炼产出）。"
    cur = str(sh.get("神火品质", "下品"))
    idx = FLAME_LADDER.index(cur) if cur in FLAME_LADDER else 0
    if idx >= len(FLAME_LADDER) - 1:
        return False, "【炼化道火精粹·已至极致】神火品质已是「唯一」，无可再提。"
    st["daohuo_jingcui"] = n - 1
    new_q = FLAME_LADDER[idx + 1]
    sh["神火品质"] = new_q
    sh["属性倍率"] = FLAME_RATE[new_q]
    note = ""
    if new_q in ("极品", "唯一") and xianqi_count(st) == 0:
        grant_xianqi(doc, st, f"道火精粹提纯·{new_q}")
        note = "\n✨ 神火达「" + new_q + "」，补生第一道仙气！"
    return True, (f"【炼化道火精粹·成功】\n神火品质：{cur} → {new_q}"
                  f"（×{FLAME_RATE[new_q]:.1f} 倍率）{note}")


XIANQI_TRIAL_WAVES: dict[int, tuple[tuple[str, float], ...]] = {
    2: (("万道规则入体，神火道果震荡", .07),
        ("古代强者烙印显化，同境围杀", .085),
        ("肉身与元神同时龟裂，仙气重组真我", .10),
        ("大道铡刀落下，斩去神火境旧极限", .13)),
    3: (("雷霆凶兽成群扑杀，双气护体", .075),
        ("大道古器横空，镇压肉身元神", .09),
        ("时间碎片割裂真我，神火近乎熄灭", .105),
        ("仙道劫光贯体，两道仙气反复崩散重聚", .12),
        ("大道铡刀终极斩落，第三道仙气破劫而生", .15)),
}


def xianqi_trial_waves(target_strand: int) -> tuple[tuple[str, float], ...]:
    """Return the fixed-source second/third strand wave schedule."""
    try:
        return XIANQI_TRIAL_WAVES.get(int(target_strand), ())
    except (TypeError, ValueError, OverflowError):
        return ()



def resolve_xianqi_trial_waves(doc: Any, target_strand: int, max_hp: int,
                               rng: Any,
                               wave_runner: Callable[[Any, int, int, str, int, Any], Mapping | None] | None = None
                               ) -> dict[str, Any]:
    """Resolve the pinned four/five wave trial after entry cost was paid.

    Raw wave damage follows `_dealWave`: HP maximum × configured fraction ×
    (1 + 3% per global wave). A custom runner may layer the port's common
    defense/revival callbacks while leaving wave data and ordering source-exact.
    """
    gate = xianqi_trial_gate(doc, getattr(doc, "ext", {}).get("xiangu", {}), target_strand)
    if not gate["allowed"]:
        return {"success": False, "dead": False, "target_strand": int(target_strand),
                "waves": [], "message": gate["message"]}
    try:
        hp_max = max(1, int(max_hp))
    except (TypeError, ValueError, OverflowError):
        return {"success": False, "dead": False, "target_strand": int(target_strand),
                "waves": [], "message": "仙气试炼生命上限无效。"}
    schedule = xianqi_trial_waves(target_strand)
    if not schedule:
        return {"success": False, "dead": False, "target_strand": int(target_strand),
                "waves": [], "message": "不存在对应的仙气极境试炼。"}
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return {"success": False, "dead": False, "target_strand": int(target_strand),
                "waves": [], "message": "玩家档案无效。"}
    ext["hp_max"], ext["hp"] = hp_max, hp_max
    rows: list[dict[str, Any]] = []
    current_hp = hp_max
    for index, (note, fraction) in enumerate(schedule, 1):
        raw_damage = max(0, int(hp_max * float(fraction) * (1 + 0.03 * index)))
        if wave_runner is None:
            damage = min(current_hp, raw_damage)
            current_hp = max(0, current_hp - damage)
            outcome: Mapping[str, Any] = {"damage": damage, "hp": current_hp,
                                          "dead": current_hp <= 0, "messages": ()}
        else:
            value = wave_runner(doc, int(target_strand), index, note, raw_damage, rng)
            outcome = value if isinstance(value, Mapping) else {}
            current_hp = max(0, int(outcome.get("hp", ext.get("hp", current_hp)) or 0))
            ext["hp"] = current_hp
        row = {"wave": index, "note": note, "fraction": fraction,
               "raw_damage": raw_damage,
               "damage": max(0, int(outcome.get("damage", raw_damage) or 0)),
               "hp": current_hp, "dead": bool(outcome.get("dead", current_hp <= 0)),
               "revival": outcome.get("revival"),
               "messages": list(outcome.get("messages") or ())}
        rows.append(row)
        if row["dead"]:
            ext["hp"] = max(1, int(hp_max * 0.10))
            return {"success": False, "dead": True,
                    "target_strand": int(target_strand), "waves": rows,
                    "hp": ext["hp"],
                    "message": f"仙气试炼陨于第 {index} 道劫，既有仙气保留，气血仅余一成。"}
    return {"success": True, "dead": False,
            "target_strand": int(target_strand), "waves": rows,
            "hp": current_hp, "message": "仙气试炼波次全部渡过。"}
