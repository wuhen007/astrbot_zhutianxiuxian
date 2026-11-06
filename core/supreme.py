"""至尊线（W8-B1b）：至尊骨 / 斩骨涅槃 / 舍骨入血 / 至尊试炼 / 仙骨 / 重瞳 / 瞳骨合一。

原版取证：`apps/User/linggenjuexing.js`（1251 行，8 条 reg / 10 个命令字面量）、
`model/supremePath.js`（183 行）、`test/supreme-path.test.js`、`config/help/linggenhelp.yaml:164-192`。
数据表本移植已 1:1 存在：`item/灵根列表.json`（三阶至尊体 + 重瞳者）、
`item/材料列表.json`（至尊骨 / 涅槃至尊骨 / 重瞳本源 / 仙王残魂）、
`item/功法列表.json`（四门前置 + 三至尊宝术）、`item/技能组/{攻击,防御}技能.json`。

原版语义（务必保持）：
- **阶段由灵根名反推**（`getSupremeStage`），不是独立字段；进阶是**整体替换 player.灵根**
  后由 `player_efficiency` 重算，本移植等价为 `linggen.snapshot()` 换 `ext["linggen"]`。
- 全部指令**无 CD、无成功率、无失败惩罚**；`#至尊试炼` 打一场，败了「道痕未损」，胜场累积。
- **不产生等效境界**，故不注册 B0 第三轨（原版 `realmAuthority.js` 只取三体系，grep 至尊 = 0）。

shortcut（本移植折算，写在模块头便于回溯）：
- 原版「极境含 2(搬血)/3(洞天)」本移植无极境数组 → 用 `realm_index ≥12 / physique_index ≥12` 代理。
- 原版「纪元积累 ≥100」→ 直接复用 `fashan.era_of(doc)`（上限 1000）。
- 原版「mijinglevel_id / xiangulevel_id ≥6」→ 用 `realm_index ≥5`（第 6 境）。
- 原版 `生命本源 = 100 + 灵根.生命本源` → 存 `ext["supreme"]["life"]`（原始点数，
  **不**乘 `linggen.ORIGIN_SCALE`；进战斗的扁平气血仍由灵根快照 origin 负责）。
- 原版至尊骨由搬血极境自动显化、材料靠大荒峡谷掉落；本移植补一条入口 `#至尊传承`
  （耗【至尊骨】换「天生至尊」灵根），并在秘境结算按 `explore_drop` 投放骨/瞳/魂材料。
- 试炼战斗：原版临时把玩家灵根改「凡血之躯」(法球 0.8)、敌方 = 玩家三维 × enemyScale；
  本移植 `battle.Unit` 无法球字段，故玩家侧三维保持满值、只由敌方 scale 承担难度
  （若把玩家也 ×0.8，ultimate 的 0.8 会变成完全对等、同随机序列下必败）。
- 原版渡劫 `BODY_EFFECTS` 减伤 0.25/0.40/0.65、重瞳者 0.50 → `trib_reduction()` 固定值，
  概率型 special（至尊初现 / 终极至尊 / 重瞳开天）未搬。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

STAGE_NAMES: tuple[str | None, ...] = (None, "天生至尊", "涅槃·至尊", "终极涅槃·至尊")
STAGE_LABEL = {1: "天生至尊", 2: "涅槃·至尊", 3: "终极涅槃·至尊"}
BONE_INIT = "初现"

# model/supremePath.js:111-119 + linggenjuexing.js:1037/1064
TRIALS: dict[str, dict[str, Any]] = {
    "nirvana": {"name": "失骨涅槃", "target": 9, "enemy": "夺骨者投影", "scale": 0.65,
                "next": "涅槃·至尊", "bone": "涅槃再生"},
    "ultimate": {"name": "血肉铭骨", "target": 4, "enemy": "至尊骨中的自己", "scale": 0.8,
                 "next": "终极涅槃·至尊", "bone": "血肉铭骨"},
}

# 参悟两骨 → 至尊宝术；两术齐时自动合成轮回天罚（supremePath.js:50-58）
ART_MAP = {"至尊骨": "上苍之手", "涅槃至尊骨": "轮回宝术"}
COMBINED_ART = "轮回天罚"

NIRVANA_GONGFA = "原始真解神引篇"
ULTIMATE_GONGFA = ("六道轮回天功", "原始真解终极篇")
IMMORTAL_GONGFA = "五行涅槃法"
ERA_GATE = 100                 # 原版 纪元积累 ≥100
NIRVANA_REALM = 12             # 代理「搬血极境」
NIRVANA_PHYSIQUE = 12          # 代理「洞天极境」
PUPIL_REALM = 5                # 原版 遮天/仙古第六境

IMMORTAL_COST = {"仙王残魂": 3, "世界石": 1}
PUPIL_COST = {"重瞳本源": 1}
INHERIT_COST = {"至尊骨": 1}

# 渡劫减伤：apps/SecretPlace/xianguTribulation.js:63-68 / zhetiandujie.js:5206-5227
TRIB_REDUCTION = {1: 0.25, 2: 0.40, 3: 0.65}
PUPIL_REDUCTION = 0.50


# ---------------------------------------------------------------- 状态

def stage_of(doc: Any) -> int:
    """从灵根快照名反推阶段（原版 getSupremeStage）；0 = 非至尊体。"""
    snap = getattr(doc, "ext", {}).get("linggen") if isinstance(getattr(doc, "ext", None), Mapping) else None
    name = str(snap.get("name") or "") if isinstance(snap, Mapping) else ""
    for i, n in enumerate(STAGE_NAMES):
        if i and n == name:
            return i
    return 0


def life_max(doc: Any) -> int:
    """100 + 灵根.生命本源（原版 xiuxian.js:14193-14204）。"""
    snap = getattr(doc, "ext", {}).get("linggen") if isinstance(getattr(doc, "ext", None), Mapping) else None
    if not isinstance(snap, Mapping):
        return 100
    try:
        return 100 + int(float(snap.get("origin", 0) or 0))
    except (TypeError, ValueError):
        return 100


def state_of(doc: Any) -> dict[str, Any]:
    """惰性创建 ext["supreme"]；按阶段清洗试炼进度（supremePath.js:33-48）。"""
    ext = getattr(doc, "ext", None)
    raw = ext.get("supreme") if isinstance(ext, Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("bone", "")
    st.setdefault("immortal", False)
    st.setdefault("pupil", False)
    st.setdefault("resonance", False)
    st.setdefault("arts", [])
    st.setdefault("life", 0)
    st.setdefault("title", "")
    if not isinstance(st["arts"], list):
        st["arts"] = list(st["arts"]) if isinstance(st["arts"], (tuple, set)) else []
    try:
        st["life"] = max(0, int(st["life"] or 0))
    except (TypeError, ValueError):
        st["life"] = 0
    if st["life"] <= 0 and stage_of(doc) > 0:
        st["life"] = life_max(doc)
    tr = st.get("trial")
    if isinstance(tr, Mapping):
        kind = str(tr.get("kind") or "")
        stage = stage_of(doc)
        keep = (kind == "nirvana" and stage == 1) or (kind == "ultimate" and stage == 2)
        st["trial"] = dict(tr) if keep else None
    else:
        st["trial"] = None
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["supreme"] = dict(st)


def title_of(doc: Any, st: Mapping[str, Any] | None = None) -> str:
    st = st or state_of(doc)
    if st.get("resonance"):
        return "至尊重瞳仙骨"
    if st.get("pupil") and st.get("immortal"):
        return "重瞳仙骨至尊"
    if st.get("pupil"):
        return "重瞳至尊"
    if st.get("immortal"):
        return "双骨至尊"
    return STAGE_LABEL.get(stage_of(doc), "凡血之躯")


def _gongfa(doc: Any) -> list[str]:
    g = getattr(doc, "ext", {}).get("gongfa") or []
    return [str(x) for x in g] if isinstance(g, (list, tuple, set)) else []


def _has(inv: Mapping[str, Any] | None, cost: Mapping[str, int]) -> bool:
    inv = inv if isinstance(inv, Mapping) else {}
    return all(int(inv.get(k, 0) or 0) >= v for k, v in cost.items())


def _delta_cost(cost: Mapping[str, int]) -> dict[str, int]:
    return {k: -int(v) for k, v in cost.items()}


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, delta or {}


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


# ---------------------------------------------------------------- 条件

def missing_of(doc: Any, kind: str) -> list[str]:
    """开试炼的前置缺口（supremePath.js:164-182 / linggenjuexing.js:1025/1053）。"""
    st = state_of(doc)
    stage = stage_of(doc)
    out: list[str] = []
    if st["trial"]:
        out.append(f"【{st['trial'].get('name')}】试炼进行中（{int(st['trial'].get('win', 0) or 0)}/{int(st['trial'].get('target', 0) or 0)} 胜）")
        return out
    if kind == "nirvana":
        if stage != 1:
            out.append("需灵根【天生至尊】（阶段 1）")
        if str(st["bone"]) != BONE_INIT:
            out.append(f"至尊骨需为「{BONE_INIT}」（先 #至尊传承 或待极境显化）")
        if int(getattr(doc, "realm_index", 0) or 0) < NIRVANA_REALM:
            out.append(f"需第 {NIRVANA_REALM + 1} 境以上（代理搬血极境）")
        if int(getattr(doc, "physique_index", 0) or 0) < NIRVANA_PHYSIQUE:
            out.append(f"需炼体第 {NIRVANA_PHYSIQUE + 1} 境以上（代理洞天极境）")
        gf = _gongfa(doc)
        if NIRVANA_GONGFA not in gf:
            out.append(f"需已参悟《{NIRVANA_GONGFA}》")
    else:
        if stage != 2:
            out.append("需灵根【涅槃·至尊】（阶段 2）")
        gf = _gongfa(doc)
        for g in ULTIMATE_GONGFA:
            if g not in gf:
                out.append(f"需已参悟《{g}》")
        try:
            from . import fashan
            era = fashan.era_of(doc)
        except Exception:
            era = 0
        if era < ERA_GATE:
            out.append(f"需纪元积累 {ERA_GATE}（现 {era}；#凝聚无上法身 / 镇守 / 时间长河产出）")
    return out


# ---------------------------------------------------------------- 指令逻辑

def inherit(doc: Any, inv: Mapping[str, Any] | None,
            table: Sequence[Mapping]) -> tuple[bool, str, dict[str, int]]:
    """本移植入口：耗【至尊骨】×1 把灵根换成「天生至尊」（原版由搬血极境自动显化）。"""
    if stage_of(doc) > 0:
        return _no(f"你已是【{STAGE_LABEL[stage_of(doc)]}】，无需再承至尊血脉。")
    if not _has(inv, INHERIT_COST):
        return _no("承接至尊血脉需【至尊骨】×1（秘境探索「大荒峡谷」一线可遇）。")
    row = next((r for r in table if isinstance(r, Mapping) and str(r.get("name")) == STAGE_NAMES[1]), None)
    if row is None:
        return _no("灵根表缺少【天生至尊】，请检查 data/item/灵根列表.json。")
    from . import linggen
    old = doc.ext.get("linggen") if isinstance(doc.ext.get("linggen"), Mapping) else {}
    snap = linggen.snapshot(row)
    snap["awaken"] = int(dict(old).get("awaken", 0) or 0)
    doc.ext["linggen"] = snap
    st = state_of(doc)
    st["bone"] = BONE_INIT
    st["life"] = life_max(doc)
    st["title"] = STAGE_LABEL[1]
    set_state(doc, st)
    atk, dfn, hp, origin = linggen.stats_of(snap)
    return _ok(
        "【至尊传承】陨落至尊的遗骨融入血肉，先天符文自骨髓里醒来——\n"
        f"灵根已换为【天生至尊】：修炼效率 ×{float(snap.get('eff', 1)):g}｜法球 {float(snap.get('orb', 0)):g}\n"
        f"四维：攻 +{atk:.0%}｜防 +{dfn:.0%}｜血 +{hp:.0%}｜生命本源 {st['life']}\n"
        f"至尊骨「{BONE_INIT}」｜下一步 #斩骨涅槃（先备《{NIRVANA_GONGFA}》与境界门槛）",
        _delta_cost(INHERIT_COST))


def start(doc: Any, kind: str, via_chop: bool = False) -> tuple[bool, str, dict[str, int]]:
    """#斩骨(涅槃) / #舍骨入血：开试炼并发出对应宝骨。`via_chop` = 阶段 2 时 #斩骨 复用。"""
    if kind not in TRIALS:
        return _no("试炼类型未知。")
    gaps = missing_of(doc, kind)
    if gaps:
        label = "斩骨涅槃" if kind == "nirvana" else "舍骨入血"
        return _no(f"【{label}·条件未足】\n" + "\n".join(f"　· {g}" for g in gaps))
    spec = TRIALS[kind]
    st = state_of(doc)
    bone_name = "至尊骨" if kind == "nirvana" else "涅槃至尊骨"
    st["bone"] = "已斩出" if kind == "nirvana" else "已舍入血肉"
    st["trial"] = {"kind": kind, "name": spec["name"], "win": 0, "target": spec["target"]}
    set_state(doc, st)
    head = "【斩骨涅槃】" if kind == "nirvana" else "【舍骨入血】"
    body = ("亲手挖出至尊骨，血肉在剧痛里重新铭刻符文——" if kind == "nirvana"
            else "截下核心宝骨舍入血肉，从此骨即是身、身即是骨——")
    tail = ("（阶段 2 的 #斩骨 已自动转为此令）" if via_chop else "")
    return _ok(
        f"{head}{body}{tail}\n"
        f"获得【{bone_name}】×1（可 #参悟{'涅槃' if kind == 'ultimate' else ''}至尊骨）\n"
        f"开启试炼【{spec['name']}】：需 {spec['target']} 胜，对手「{spec['enemy']}」\n"
        f"每次 #至尊试炼 打一场，败不损胜场、无惩罚。",
        {bone_name: 1})


def trial(doc: Any, stats: Any, table: Sequence[Mapping],
          rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """#至尊试炼：一场切磋；胜场达标则整体换灵根快照并进阶。"""
    st = state_of(doc)
    tr = st.get("trial")
    if not isinstance(tr, Mapping):
        return _no("当前没有进行中的至尊试炼（先 #斩骨涅槃 或 #舍骨入血）。")
    spec = TRIALS.get(str(tr.get("kind") or ""))
    if spec is None:
        st["trial"] = None
        set_state(doc, st)
        return _no("试炼记录已失效，进度已清空，请重新开启。")
    from . import battle
    name = str(getattr(doc, "name", "") or "道友")
    atk = max(1, int(getattr(stats, "atk", 0) or 0))
    defense = max(1, int(getattr(stats, "defense", 0) or 0))
    hp = max(1, int(getattr(stats, "hp", 0) or 0))
    bao = float(getattr(stats, "bao", 0) or 0)
    # 原版临时改「凡血之躯」只换法球/技能，**三维不打折**；难度由敌方 enemyScale 单独承担
    me = battle.Unit(name, atk, defense, hp, bao)
    foe = battle.Unit(str(spec["enemy"]), int(atk * float(spec["scale"])),
                      int(defense * float(spec["scale"])), int(hp * float(spec["scale"])), 0.05)
    won, log, hp_left, _ = battle.spar_full(me, foe, rng, max_rounds=20)
    brief = "｜".join(str(x) for x in (log or [])[-2:])[:160]
    if won != 0:
        set_state(doc, st)
        return _no(f"【{spec['name']}·失守】道痕未损，当前进度仍为 "
                   f"{int(tr.get('win', 0) or 0)}/{int(tr.get('target', 0) or 0)} 胜。\n"
                   f"战报：{brief or '势均力敌，暂且收兵'}")
    tr = dict(tr)
    tr["win"] = int(tr.get("win", 0) or 0) + 1
    st["trial"] = tr
    lines = [f"【{spec['name']}·胜】{brief or '一击破敌'}",
             f"进度 {tr['win']}/{int(tr.get('target', 0) or 0)} 胜"]
    if tr["win"] < int(tr.get("target", 0) or 0):
        set_state(doc, st)
        return _ok("\n".join(lines) + "｜继续 #至尊试炼。")
    # 达标：整体换灵根（原版 player.灵根 = {...nextTalent}）
    row = next((r for r in table if isinstance(r, Mapping) and str(r.get("name")) == spec["next"]), None)
    if row is None:
        set_state(doc, st)
        return _no(f"{lines[0]}，但灵根表缺少【{spec['next']}】，进阶暂缓（进度已保留）。")
    from . import linggen
    old = doc.ext.get("linggen") if isinstance(doc.ext.get("linggen"), Mapping) else {}
    snap = linggen.snapshot(row)
    snap["awaken"] = int(dict(old).get("awaken", 0) or 0)
    doc.ext["linggen"] = snap
    st["trial"] = None
    st["bone"] = str(spec["bone"])
    st["life"] = life_max(doc)
    st["title"] = title_of(doc, st)
    set_state(doc, st)
    atk2, dfn2, hp2, origin2 = linggen.stats_of(snap)
    lines += [f"≡≡≡ {spec['name']} 圆满 ≡≡≡",
              f"灵根晋为【{spec['next']}】：修炼效率 ×{float(snap.get('eff', 1)):g}｜法球 {float(snap.get('orb', 0)):g}",
              f"四维：攻 +{atk2:.0%}｜防 +{dfn2:.0%}｜血 +{hp2:.0%}｜生命本源 {st['life']}",
              f"至尊骨「{st['bone']}」｜称号【{st['title']}】"]
    if str(tr.get("kind")) == "nirvana":
        lines.append("下一步：参悟《六道轮回天功》《原始真解终极篇》、纪元积累 100 → #舍骨入血")
    else:
        lines.append("至尊线已至终极，可继续 #孕育仙骨 / #重瞳开天 / #瞳骨合一")
    return _ok("\n".join(lines))


def comprehend(doc: Any, inv: Mapping[str, Any] | None,
               kind: str) -> tuple[bool, str, dict[str, int]]:
    """#参悟至尊骨 / #参悟涅槃至尊骨：耗骨学宝术，两术齐自动合成轮回天罚。"""
    art = ART_MAP.get(kind)
    if not art:
        return _no("参悟目标未知。")
    stage = stage_of(doc)
    need_stage = 1 if kind == "至尊骨" else 2
    if stage < need_stage:
        return _no(f"参悟【{kind}】需灵根阶段 {need_stage} 以上（先完成对应试炼）。")
    st = state_of(doc)
    if art in st["arts"]:
        return _no(f"《{art}》已在参悟之中，无需重复领悟。")
    if not _has(inv, {kind: 1}):
        return _no(f"纳戒中没有【{kind}】×1（由 #{'斩骨涅槃' if need_stage == 1 else '舍骨入血'} 产出）。")
    st["arts"] = list(st["arts"]) + [art]
    gf = _gongfa(doc)
    gained = [art]
    if art not in gf:
        gf.append(art)
    if all(a in st["arts"] for a in ART_MAP.values()) and COMBINED_ART not in gf:
        gf.append(COMBINED_ART)
        gained.append(COMBINED_ART)
    doc.ext["gongfa"] = gf
    set_state(doc, st)
    combo = (f"\n【两术合一】上苍之手 × 轮回宝术 → 自动领悟《{COMBINED_ART}》！"
             if COMBINED_ART in gained else "")
    return _ok(f"【至尊骨参悟】符文自骨髓流入识海，领悟《{art}》！\n"
               f"已入功法栏（战斗技能池自动命中）｜至尊宝术 {len(st['arts'])}/{len(ART_MAP)}{combo}",
               {kind: -1})


def immortal_bone(doc: Any, inv: Mapping[str, Any] | None) -> tuple[bool, str, dict[str, int]]:
    """#孕育仙骨：五行涅槃法 + 生命本源满值 + 仙王残魂×3 + 世界石×1。"""
    st = state_of(doc)
    if st["immortal"]:
        return _no("仙骨已孕育，无需再铸。")
    if stage_of(doc) < 2:
        return _no("孕育仙骨需阶段 2（涅槃·至尊）以上。")
    if IMMORTAL_GONGFA not in _gongfa(doc):
        return _no(f"需先参悟《{IMMORTAL_GONGFA}》。")
    if st["life"] < life_max(doc):
        return _no(f"生命本源未满（{st['life']}/{life_max(doc)}），先将本源养回峰值。")
    if not _has(inv, IMMORTAL_COST):
        need = "、".join(f"【{k}】×{v}" for k, v in IMMORTAL_COST.items())
        return _no(f"孕育仙骨需 {need}（秘境奇遇 / 小世界 / 众生仙钓产出）。")
    st["immortal"] = True
    st["resonance"] = False
    st["title"] = title_of(doc, st)
    set_state(doc, st)
    return _ok(f"【仙骨孕育】仙王残魂凝为不朽骨，与至尊骨并生——\n"
               f"称号【{st['title']}】｜战斗附加「仙骨」防御（削伤 50%）\n"
               f"可与 #重瞳开天 并行，二者齐备后 #瞳骨合一。",
               _delta_cost(IMMORTAL_COST))


def double_pupil(doc: Any, inv: Mapping[str, Any] | None) -> tuple[bool, str, dict[str, int]]:
    """#重瞳开天：第 6 境 + 重瞳本源×1。"""
    st = state_of(doc)
    if st["pupil"]:
        return _no("重瞳已开，无需再启。")
    if int(getattr(doc, "realm_index", 0) or 0) < PUPIL_REALM:
        return _no(f"重瞳开天需第 {PUPIL_REALM + 1} 境以上（原版遮天/仙古第六境）。")
    if not _has(inv, PUPIL_COST):
        return _no("重瞳开天需【重瞳本源】×1（秘境「大荒重瞳者」遭遇产出）。")
    st["pupil"] = True
    st["resonance"] = False
    st["title"] = title_of(doc, st)
    set_state(doc, st)
    return _ok(f"【重瞳开天】眸中日月重开，看破万法本源——\n"
               f"称号【{st['title']}】｜战斗附加「重瞳 / 重瞳至尊」神通，渡劫减伤 ≥50%\n"
               f"可与 #孕育仙骨 并行，二者齐备后 #瞳骨合一。",
               _delta_cost(PUPIL_COST))


def merge(doc: Any) -> tuple[bool, str, dict[str, int]]:
    """#瞳骨合一：阶段≥2 + 重瞳 + 仙骨 → 终极共鸣。"""
    st = state_of(doc)
    if st["resonance"]:
        return _no("瞳骨已合一，共鸣长存。")
    if stage_of(doc) < 2:
        return _no("瞳骨合一需阶段 2（涅槃·至尊）以上。")
    gaps = []
    if not st["pupil"]:
        gaps.append("未开重瞳（#重瞳开天）")
    if not st["immortal"]:
        gaps.append("未孕仙骨（#孕育仙骨）")
    if gaps:
        return _no("【瞳骨合一·条件未足】\n" + "\n".join(f"　· {g}" for g in gaps))
    st["resonance"] = True
    st["title"] = title_of(doc, st)
    set_state(doc, st)
    return _ok(f"【瞳骨合一】重瞳映照上苍、至尊骨反演轮回、仙骨镇住不朽道躯——\n"
               f"终极共鸣「瞳照上苍·不朽轮回」｜称号【{st['title']}】\n"
               f"战斗附加「至尊重瞳仙骨」神通（零倍率防御 / 攻势 3.5 倍）。")


# ---------------------------------------------------------------- 面板 / 规则

def panel(doc: Any) -> str:
    st = state_of(doc)
    stage = stage_of(doc)
    lines = ["--- 至尊之路 ---",
             f"道友：{str(getattr(doc, 'name', '') or '')}｜称号【{title_of(doc, st)}】",
             f"本命阶段：{stage}/3　{STAGE_LABEL.get(stage, '凡血之躯（未承至尊血脉）')}",
             f"至尊骨：{st['bone'] or '未显化'}｜生命本源：{st['life']}/{life_max(doc)}",
             f"仙骨：{'已孕育' if st['immortal'] else '未孕育'}｜重瞳：{'已开' if st['pupil'] else '未开'}"
             f"｜瞳骨共鸣：{'已成' if st['resonance'] else '未成'}",
             f"至尊宝术：{'、'.join(st['arts']) if st['arts'] else '无'}（{len(st['arts'])}/{len(ART_MAP)}，两术齐自动得《{COMBINED_ART}》)" ]
    tr = st.get("trial")
    if isinstance(tr, Mapping):
        lines.append(f"试炼【{tr.get('name')}】：{int(tr.get('win', 0) or 0)}/{int(tr.get('target', 0) or 0)} 胜"
                     f"｜对手「{TRIALS[str(tr.get('kind'))]['enemy']}」｜#至尊试炼 打一场")
    else:
        lines.append("试炼：无进行中")
    if stage == 0:
        lines.append("下一阶段尚缺：【至尊骨】×1 → #至尊传承（秘境探索可遇）")
    elif stage == 1:
        gaps = missing_of(doc, "nirvana")
        lines.append("下一阶段尚缺：" + ("；".join(gaps) if gaps else "无（可 #斩骨涅槃）"))
    elif stage == 2:
        gaps = missing_of(doc, "ultimate")
        lines.append("下一阶段尚缺：" + ("；".join(gaps) if gaps else "无（可 #舍骨入血）"))
    else:
        lines.append("至尊线已至终极：可 #孕育仙骨 / #重瞳开天 / #瞳骨合一")
    lines += ["", "可用指令：#至尊传承 · #斩骨涅槃 · #舍骨入血 · #至尊试炼 · "
              "#参悟至尊骨 · #参悟涅槃至尊骨 · #孕育仙骨 · #重瞳开天 · #瞳骨合一 · #至尊规则"]
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join([
        "--- 至尊规则 ---",
        "1. 阶段由灵根决定：天生至尊(1) → 涅槃·至尊(2) → 终极涅槃·至尊(3)；"
        "进阶整体替换灵根（四维/效率/法球/生命本源全部重算）。",
        "2. 试炼：#斩骨涅槃 开「失骨涅槃」9 胜；#舍骨入血 开「血肉铭骨」4 胜。"
        "每次 #至尊试炼 打一场，败不损胜场、无 CD、无惩罚，进度永久保留。",
        "3. 阶段 2 时 #斩骨 自动转 #舍骨入血；#斩骨涅槃 恒走斩骨线（原版复用规则）。",
        "4. 宝术：#参悟至尊骨 →《上苍之手》；#参悟涅槃至尊骨 →《轮回宝术》；"
        "两术齐备自动合成《轮回天罚》，三者进功法栏并命中战斗技能池。",
        "5. 支线：#孕育仙骨（五行涅槃法 + 生命本源满 + 仙王残魂×3 + 世界石×1）、"
        "#重瞳开天（第 6 境 + 重瞳本源×1）、#瞳骨合一（阶段≥2 + 二者齐备）。",
        "6. 战斗：灵根同名技能 + 「重瞳 / 仙骨 / 重瞳至尊 / 至尊重瞳仙骨」按状态附加；"
        "渡劫减伤 25% / 40% / 65%，重瞳另保底 50%。",
        "7. 至尊线不产生等效境界，不进第三轨；材料在秘境结算按大荒峡谷口径投放。",
    ])


# ---------------------------------------------------------------- 消费点

def trib_reduction(doc: Any) -> float:
    """渡劫减伤：apps/SecretPlace/xianguTribulation.js:63-68。"""
    st = state_of(doc)
    red = float(TRIB_REDUCTION.get(stage_of(doc), 0.0))
    if st["pupil"]:
        red = max(red, PUPIL_REDUCTION)
    return red


def skill_names(doc: Any) -> list[str]:
    """额外挂进战斗技能池的灵根类技能名（原版 hasSupremeInnate 分支）。"""
    st = state_of(doc)
    names: list[str] = []
    if st["pupil"]:
        names += ["重瞳", "重瞳至尊"]
    if st["immortal"]:
        names.append("仙骨")
    if st["resonance"]:
        names.append("至尊重瞳仙骨")
    return names


def explore_drop(doc: Any, rng: random.Random) -> dict[str, int]:
    """秘境结算材料投放（原版大荒峡谷 four 掉落 + 10% 重瞳者遭遇 + 仙王残魂奇遇）。

    对非至尊体只投【至尊骨】（给入口），至尊体投支线材料；返回空 dict 时旧行为不变。
    """
    st = state_of(doc)
    out: dict[str, int] = {}
    if stage_of(doc) <= 0:
        if rng.random() < 0.02:
            out["至尊骨"] = 1
        return out
    if not st["pupil"] and rng.random() < 0.10:
        out["重瞳本源"] = 1
    if not st["immortal"]:
        if rng.random() < 0.15:
            out["仙王残魂"] = 1
        if rng.random() < 0.10:
            out["世界石"] = 1
    return out


def equivalent_level(doc: Any) -> int:
    """占位：至尊线**不**提供等效境界（原版 realmAuthority.js 三体系无至尊）。"""
    return 0
