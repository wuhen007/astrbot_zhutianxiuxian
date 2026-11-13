"""仙古秘境 道种融合·神火四路·祭炼真我（W27）——原版 `xianguPlace.js`
道种查看 L4553 / 融合确认 L4662 / 取消 L4693 / 借助道种点燃 L4701 /
神火查看 L5121 / 苦修点燃 L5226 / 服丹点燃 L5357 / 祭炼真我 L5514 /
以身为种 L5744 + `xianguTribulation.js` 三千道火五幕（成功率 L145：
30% + 10%×极境 + min(道韵/5000, 10%)）+ 仙气（xianguXianqi.js）。

shortcut：
- 神火点燃成功 → 仙古境界钉到神火境（xg_level_of 对已点燃者取 max(推导, 8)）；
  端口主轨不动，属性走 ext["shenhuo"] 战斗乘区（handler 战斗回调套用）。
- 三千道火五幕（逐波扣血+演出推播）同步化为一次性聚合结算：净伤害 ≈
  Σ波次占比（约 172% 上限）按当前血量折算，血量不足即道火反噬（败）。
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
    """覆盖 xg.xg_level_of：已点燃神火者仙古境界 ≥ 8（神火境）。"""
    base = xg.xg_level_of(doc)
    ext = getattr(doc, "ext", {}) or {}
    st = ext.get("xiangu") if isinstance(ext.get("xiangu"), dict) else {}
    sh = (st.get("shenhuo") or {}) if isinstance(st, dict) else {}
    if sh.get("已点燃"):
        return max(base, 8)
    return base


def extremes_completed(doc: Any) -> int:
    """六大极境换算（docstring shortcut）：clamp(realm_index - 24, 0, 6)。"""
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
    poor = _potential_pay(doc, st)
    if poor:
        return poor
    from . import wallet
    if int(getattr(doc, "exp", 0) or 0) < TRIB_ENERGY or wallet.xueqi(doc) < TRIB_ENERGY:
        return f"【祭炼真我·本源不足】需 {TRIB_ENERGY:,} 修为和血气。"
    return None


def tribulation_run(doc: Any, st: dict, rng: Callable[[], float],
                    now: float) -> tuple[str, dict]:
    """三千道火五幕（聚合演出）→ 成败判定 → 状态写入。返回 (text, events)。"""
    events: dict[str, Any] = {}
    from . import wallet
    daoyun = int((st.get("gains") or {}).get("daoyun", 0) or 0)
    doc.exp = max(0, int(doc.exp) - TRIB_ENERGY)
    wallet.set_xueqi(doc, max(0, wallet.xueqi(doc) - TRIB_ENERGY))
    st["gains"]["daoyun"] = daoyun - TRIB_DAOYUN

    # 聚合五幕：按当前血量逐波结算，血量触底即道火反噬
    hp_max = max(1, int(float((getattr(doc, "ext", {}) or {}).get("hp_max", 0) or 0)) or xg._hp_of(doc))
    hp = hp_max          # 满血入劫（原版一致）
    died_at = ""
    for note, frac in TRIB_WAVES:
        hp = min(hp_max, max(0, int(hp + hp_max * frac)))
        if hp <= 0 and frac < 0:
            died_at = note
            break
    rate = 0.30 + extremes_completed(doc) * 0.10 + min(daoyun / 5000.0, 0.10)
    rate = min(1.0, rate)
    if died_at or rng.random() > rate:
        # 道火反噬：道伤 +1（走 zhengdao 记账）、精粹 +1、血量 20%
        from . import zhengdao
        try:
            zhengdao.add_wounds(doc, 1.0, "祭炼真我·道火反噬", now)
        except Exception:
            pass
        st["daohuo_jingcui"] = int(st.get("daohuo_jingcui", 0) or 0) + 1
        xg._set_hp(doc, max(1, int(hp_max * 0.2)))
        reason = f"（陨于「{died_at}」）" if died_at else ""
        return "\n".join([
            "【祭炼真我·道火反噬！！！】", "",
            "三千道火未能归一，真我道基遭受反噬（道伤 +1，可用 #道基重塑 祛除）...",
            "万幸保住尊者境果位未曾跌落，并自余烬中凝出一滴【道火精粹液】（+1）！",
            reason,
            "", "“百折不挠，重铸根基再登青石路！”",
            f"（本次成功率 {rate * 100:.0f}%：30% 基础 +10%/极境 + 道韵加成）"]), events
    # 成功：唯一真火 + 草字剑诀 + 仙气 + 精粹
    sh = ignite(doc, st, "祭炼真我", "唯一", root="祭炼真我·唯一真火",
                skill="草字剑诀", extra="不受秘境境界压制·天地共鸣")
    grant_xianqi(doc, st, "祭炼真我·三千道火淬炼")
    st["daohuo_jingcui"] = int(st.get("daohuo_jingcui", 0) or 0) + 1
    st.setdefault("titles", [])
    if "祭炼真我" not in st["titles"]:
        st["titles"].append("祭炼真我")
    events["ignited"] = True
    events["technique"] = "草字剑诀"
    return "\n".join([
        "【祭炼真我·天地共鸣！！！】", "",
        "三千大道火光归一，肉身与元神熬炼无瑕！",
        "一道绝世剑意从体内冲出——草字剑诀！", "",
        "【神火点燃】不借外物，天地间唯一不灭的真火燃起！",
        f"神火品质：唯一 ×{sh['属性倍率']:.1f} 倍率",
        "【获得神通】草字剑诀·万古最强攻伐之术",
        "【渡劫造化】道火精粹液 ×1｜道韵消耗 500",
        "【称号】祭炼真我",
        "【仙气极境】第一道仙气已成；#冲关极境 可依次挑战第二、第三道仙气。", "",
        "“此道开创，万古未有！”",
        f"（成功率 {rate * 100:.0f}%）"]), events


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


def charge_extreme_xianqi(doc: Any, st: dict, rng: Callable[[], float]) -> tuple[bool, str]:
    """#冲关极境 分流：神火境且仙气 <3 → 仙气试炼（40% + 10%/道）。"""
    sh = shenhuo_of(st)
    if not sh.get("已点燃"):
        return False, ""
    n = xianqi_count(st)
    if n >= 3:
        return False, ""
    rate = min(0.9, 0.40 + 0.10 * n)
    if rng.random() < rate:
        grant_xianqi(doc, st, "神火境极境试炼")
        return True, ("\n".join([
            f"✅【仙气试炼·第{'一二三'[n]}道仙气已成！】", "",
            "神火焚烧道则，仙气自神火中凝出一缕，缠绕周身。", "",
            f"当前仙气：{n + 1}/3" +
            ("（神火境绝巅圆满）" if n + 1 >= 3 else "")]))
    return True, ("\n".join([
        "【仙气试炼·未成】", "",
        "神火震荡，仙气溃散回炉。道基无损，来日再战。",
        f"（成功率 {rate * 100:.0f}%）"]))
