"""彼岸区域远征（原版 model/otherShoreExpedition.js 主链移植，每玩家会话制）。

原版要点：
- 三条战役链（前置串联）：玄阙神炉(1,-1) → 先秦归航(4,-4) → 母锚归一(0,-4)，
  每条 5 阶段（观测/清剿/修复/读取/镇压 boss），boss 独立血量；
  首通掉落钥匙物（纪元之力/先秦归航碑拓/裂界母锚坐标核）。
- 前线营地 L0-L3（建设 0/10/30/60，仓储 0/20/60/200，韧性 0/6/12/20）；
  行囊随身+营地封存两栏；强制撤离损失 30%；遗失行囊 30 分钟回收。
- 踏足大星后才能开始远征；前置战役个人首通解锁下一条。

移植口径（差异已标注）：
- 原版为全服共享战役（Redis 会话 + web 网关）；本移植每玩家会话（ext["tw_expedition"]）。
- 濒危/同星救援/遗失行囊回收为多人机制，本移植省略（战败按真世界口径气血降至 1，
  战役阶段失败可重试推进）。
- 阶段战斗走真实 run_1v1（handler 回调）；观测/读取/修复类阶段直接成功。
- 战果领取：材料入 other_shore_forge 材料袋，纪元之力解锁时走 fashan.add_era。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

EXT_KEY = "tw_expedition"
FORCED_LOSS_RATE = 0.30
CAMP_CONTRIBUTION_CAP = 10

CAMPAIGNS: tuple[dict[str, Any], ...] = (
    {"star": "1,-1", "id": "xuanque-divine-furnace", "name": "玄阙神炉", "order": 0,
     "prerequisite": None,
     "first_clear": {"id": "key:era-power", "name": "纪元之力", "era": 3},
     "boss": {"id": "xuanque-calamity-core", "name": "玄阙灾核", "hp": 600_000_000_000_000},
     "stages": (
         {"id": "observe-scar", "name": "观测灾痕", "kind": "explore"},
         {"id": "clear-variants", "name": "清剿同源变异体", "kind": "battle"},
         {"id": "repair-star-eye", "name": "修复古星阵眼", "kind": "operation"},
         {"id": "read-qin-inscription", "name": "读取先秦炉铭", "kind": "lore"},
         {"id": "suppress-calamity-core", "name": "镇压神炉灾核", "kind": "boss"},
     )},
    {"star": "4,-4", "id": "qin-homeward-voyage", "name": "先秦归航", "order": 1,
     "prerequisite": "1,-1",
     "first_clear": {"id": "key:qin-homeward-stele-rubbing", "name": "先秦归航碑拓", "era": 5},
     "boss": {"id": "rift-voyage-devourer", "name": "裂隙噬航者", "hp": 900_000_000_000_000},
     "stages": (
         {"id": "trace-qin-route", "name": "追溯先秦航痕", "kind": "lore"},
         {"id": "cross-spirit-rift", "name": "穿行灵界裂隙", "kind": "explore"},
         {"id": "restore-ferry-stele", "name": "复原彼岸渡碑", "kind": "operation"},
         {"id": "repel-rift-demons", "name": "击退裂隙邪魔", "kind": "battle"},
         {"id": "defeat-voyage-devourer", "name": "斩灭噬航者", "kind": "boss"},
     )},
    {"star": "0,-4", "id": "rift-mother-anchor-unification", "name": "母锚归一", "order": 2,
     "prerequisite": "4,-4",
     "first_clear": {"id": "key:rift-mother-anchor-core", "name": "裂界母锚坐标核", "era": 8},
     "boss": {"id": "world-devouring-anchor-emperor", "name": "噬界锚皇", "hp": 1_200_000_000_000_000},
     "stages": (
         {"id": "decode-rift-genealogy", "name": "解读裂隙源谱", "kind": "lore"},
         {"id": "stabilize-anchor-veins", "name": "校准母锚维脉", "kind": "operation"},
         {"id": "recover-qin-dojo", "name": "复原先秦道场坐标", "kind": "explore"},
         {"id": "clear-anchor-corruption", "name": "清剿母锚侵蚀体", "kind": "battle"},
         {"id": "suppress-anchor-emperor", "name": "镇压噬界锚皇", "kind": "boss"},
     )},
)
CAMPAIGN_BY_STAR = {c["star"]: c for c in CAMPAIGNS}

CAMP_LEVELS: tuple[dict[str, int], ...] = (
    {"level": 0, "build": 0, "storage": 0, "resilience": 0},
    {"level": 1, "build": 10, "storage": 20, "resilience": 6},
    {"level": 2, "build": 30, "storage": 60, "resilience": 12},
    {"level": 3, "build": 60, "storage": 200, "resilience": 20},
)


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = {
        "runs": {},          # star -> run（每星一次远征的进度档案）
        "camps": {},         # star -> {"build": n, "level": n}
        "first_clears": [],  # 已首通战役 star 列表
        "pending_rewards": [],
    }
    if isinstance(raw, Mapping):
        st.update({k: v for k, v in raw.items() if k in st})
        st.setdefault("runs", {})
        st.setdefault("camps", {})
        st.setdefault("first_clears", [])
        st.setdefault("pending_rewards", [])
    return st


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = {}
        doc.ext = ext
    ext[EXT_KEY] = dict(st)


def campaign_unlocked(st: Mapping, campaign: Mapping) -> tuple[bool, str]:
    if not campaign.get("prerequisite"):
        return True, ""
    if campaign["prerequisite"] in (st.get("first_clears") or []):
        return True, ""
    pre = CAMPAIGN_BY_STAR[campaign["prerequisite"]]
    return False, f"需先完成前置战役【{pre['name']}】个人首通"


def start_run(doc: Any, star: str) -> tuple[bool, str]:
    """#进入区域远征：需已观测/踏足该大星坐标 + 前置首通 + 无进行中远征。"""
    st = state_of(doc)
    campaign = CAMPAIGN_BY_STAR.get(str(star or "").strip())
    if not campaign:
        names = "、".join(f"{c['name']}({c['star']})" for c in CAMPAIGNS)
        return False, f"没有该大星的战役。可选：{names}"
    from . import other_shore_true_world as tw_mod
    tw_st = tw_mod.state_of(doc)
    if not tw_st.get("active"):
        return False, "先 #进入真世界，并观测/前往目标大星坐标。"
    if f"{campaign['star']}" not in (tw_st.get("sectors") or {}):
        return False, f"踏足该大星后才能开始远征（先 #观测真世界 {campaign['star']}）。"
    ok, why = campaign_unlocked(st, campaign)
    if not ok:
        return False, why
    run = st["runs"].get(campaign["star"])
    if isinstance(run, Mapping) and run.get("status") == "active":
        return False, "当前修士已有进行中的彼岸远征。"
    if campaign["star"] in (st.get("first_clears") or []):
        return False, f"当前修士已经完成{campaign['name']}首通。"
    st["runs"][campaign["star"]] = {
        "status": "active", "stage_index": 0,
        "carried": [], "stored": [],
        "camp_build": int((st["camps"].get(campaign["star"]) or {}).get("build", 0) or 0),
        "started_at": float(time.time()),
    }
    stage = campaign["stages"][0]
    save(doc, st)
    return True, (f"【彼岸区域战役·{campaign['name']}】远征开始（阶段 1/{len(campaign['stages'])}："
                  f"{stage['name']}）。#推进彼岸战役 执行当前阶段；#彼岸行囊 查看携带。")


def _run_of(st: dict) -> tuple[str, dict] | None:
    for star, run in (st.get("runs") or {}).items():
        if isinstance(run, Mapping) and run.get("status") in ("active", "waiting_boss"):
            return star, dict(run)
    return None


def camp_level_of(build: int) -> int:
    level = 0
    for row in CAMP_LEVELS:
        if build >= row["build"]:
            level = row["level"]
    return level


def camp_of(st: dict, star: str) -> dict[str, int]:
    camps = st.setdefault("camps", {})
    row = camps.setdefault(star, {"build": 0})
    return dict(row)


def build_camp(doc: Any, star: str | None) -> tuple[bool, str]:
    """#建设前线营地：每次投入 10 点建设（单人单次上限 10，原版贡献上限同）。"""
    st = state_of(doc)
    run = _run_of(st)
    star = str(star or "").strip() or (run[0] if run else "")
    campaign = CAMPAIGN_BY_STAR.get(star)
    if not campaign:
        return False, "没有进行中的远征（先 #进入区域远征）。"
    camp = camp_of(st, star)
    if camp.get("contributed_today"):
        return False, "本轮远征中你已为营地出力（上限 10 点）。"
    camp["build"] = int(camp.get("build", 0) or 0) + CAMP_CONTRIBUTION_CAP
    camp["contributed_today"] = True
    st["camps"][star] = camp
    run = st["runs"].get(star)
    if isinstance(run, Mapping) and run.get("status") in ("active", "waiting_boss"):
        run["camp_build"] = camp["build"]
    level = camp_level_of(camp["build"])
    save(doc, st)
    row = CAMP_LEVELS[level]
    return True, (f"【前线营地】建设 +{CAMP_CONTRIBUTION_CAP}（累计 {camp['build']}/60）"
                  f"｜营地 L{level}｜仓储容量 {row['storage']} 份｜韧性 {row['resilience']}。")


def bag_summary(run: Mapping) -> str:
    carried = run.get("carried") or []
    stored = run.get("stored") or []
    level = camp_level_of(int(run.get("camp_build", 0) or 0))
    cap = CAMP_LEVELS[level]["storage"]
    def _fmt(items):
        return "、".join(f"{i['name']}×{i['qty']}" for i in items) or "无"
    return (f"随身 {sum(i['qty'] for i in carried)} 份（{_fmt(carried)}）｜"
            f"营地封存 {sum(i['qty'] for i in stored)} 份/{cap}（{_fmt(stored)}）")


def advance(doc: Any, now: float, rng: Any, battle_cb: Any = None) -> tuple[bool, str]:
    """#推进彼岸战役：非战斗阶段直接成功；battle/boss 阶段回调真实战斗。"""
    st = state_of(doc)
    found = _run_of(st)
    if not found:
        return False, "没有进行中的彼岸远征（先 #进入区域远征）。"
    star, run = found
    campaign = CAMPAIGN_BY_STAR[star]
    idx = int(run.get("stage_index", 0) or 0)
    stages = campaign["stages"]
    if idx >= len(stages):
        return False, "本轮远征战役已经完成，#彼岸撤离 撤回。"
    stage = stages[idx]
    if stage["kind"] in ("battle", "boss"):
        if stage["kind"] == "boss":
            return False, (f"最终阶段需挑战区域首领【{campaign['boss']['name']}】："
                           f"#推进彼岸战役 将触发决战（请确保状态最佳）。")
        if battle_cb is None:
            return False, "战斗回调缺失。"
        tier_idx = min(3, campaign["order"] + 1)
        from . import other_shore_true_world as tw_mod
        tier = tw_mod.ENEMY_TIERS[tier_idx]
        won, hp_after = battle_cb(tier)
        if not won:
            return True, (f"【{stage['name']}】作战失利——阶段未推进，气血降至 1，可整备后再战。")
        run["hp_after"] = int(hp_after)
    loot = _stage_loot(campaign["order"], idx, rng)
    for item in loot:
        run.setdefault("carried", []).append(item)
    run["stage_index"] = idx + 1
    lines = [f"【{stage['name']}】完成（阶段 {idx + 1}/{len(stages)}）。"]
    if loot:
        lines.append("缴获：" + "、".join(f"{i['name']}×{i['qty']}" for i in loot))
    if run["stage_index"] == len(stages) - 1:
        run["status"] = "waiting_boss"
        lines.append(f"下一阶段为决战：#推进彼岸战役 挑战区域首领【{campaign['boss']['name']}】"
                     f"（血量 {campaign['boss']['hp']:,}）。")
    st["runs"][star] = run
    save(doc, st)
    return True, "\n".join(lines)


def _stage_loot(order: int, idx: int, rng: Any) -> list[dict[str, Any]]:
    """阶段战利：真界源晶为主，随战役进度微增（简化自原版 loot 注入）。"""
    base = 2 + order * 2 + idx // 2
    return [{"name": "真界源晶", "mid": "true-world-source-crystal", "qty": base}]


def boss_fight(doc: Any, now: float, battle_cb: Any) -> tuple[bool, str]:
    """最终阶段决战：胜 → 首通钥匙 + 材料包 + 纪元（first_clear.era）入 pending。"""
    st = state_of(doc)
    found = _run_of(st)
    if not found:
        return False, "没有进行中的彼岸远征。"
    star, run = found
    campaign = CAMPAIGN_BY_STAR[star]
    if run.get("status") != "waiting_boss":
        return False, "当前阶段不是区域首领决战（先 #推进彼岸战役 完成前序阶段）。"
    if battle_cb is None:
        return False, "战斗回调缺失。"
    boss = campaign["boss"]
    won, hp_after = battle_cb(boss)
    if not won:
        return True, (f"【{boss['name']}】决战失利——气血降至 1，整备后再战"
                      f"（首领血量独立记录，重试 #推进彼岸战役 即可再战）。")
    first = star not in (st.get("first_clears") or [])
    run["status"] = "evac_ready"
    run["cleared_at"] = float(now)
    st["runs"][star] = run
    pending = st.setdefault("pending_rewards", [])
    bundle = {"star": star, "campaign": campaign["name"],
              "materials": {"true-world-source-crystal": 12 + campaign["order"] * 6,
                            "dao-rule-origin": 6 + campaign["order"] * 3,
                            "dimension-anchor-crystal": 3 + campaign["order"]},
              "era": int(campaign["first_clear"]["era"]) if first else 0,
              "keys": [campaign["first_clear"]["name"]] if first else [],
              "at": float(now)}
    pending.append(bundle)
    if first:
        st.setdefault("first_clears", []).append(star)
    save(doc, st)
    lines = [f"【区域首领伏诛】{boss['name']}轰然崩解——{campaign['name']}战役完成！"]
    if first:
        lines.append(f"首通掉落钥匙物：【{campaign['first_clear']['name']}】"
                     + (f"（含纪元 +{campaign['first_clear']['era']}，领取时入账）"
                        if campaign["first_clear"].get("era") else ""))
    lines.append("#彼岸撤离 返航（或 #存放彼岸战利品 先行封存）。")
    return True, "\n".join(lines)


def boss_hp_of(st: Mapping, star: str) -> dict[str, Any] | None:
    """当前等待决战的区域首领（供 handler 构造 Fighter）。"""
    run = (st.get("runs") or {}).get(star)
    if not isinstance(run, Mapping) or run.get("status") != "waiting_boss":
        return None
    return CAMPAIGN_BY_STAR[star]["boss"]


def battle_tier_of(st: Mapping, star: str) -> dict[str, Any] | None:
    """当前 battle 阶段的敌群档（供 handler 构造 Fighter）。"""
    run = (st.get("runs") or {}).get(star)
    if not isinstance(run, Mapping) or run.get("status") != "active":
        return None
    campaign = CAMPAIGN_BY_STAR[star]
    idx = int(run.get("stage_index", 0) or 0)
    if idx >= len(campaign["stages"]) or campaign["stages"][idx]["kind"] != "battle":
        return None
    from . import other_shore_true_world as tw_mod
    return tw_mod.ENEMY_TIERS[min(3, campaign["order"] + 1)]


def deposit(doc: Any) -> tuple[bool, str]:
    """#存放彼岸战利品：随身物资 → 营地封存（需营地 L1+）。"""
    st = state_of(doc)
    found = _run_of(st)
    if not found:
        return False, "没有进行中的彼岸远征。"
    star, run = found
    level = camp_level_of(int(run.get("camp_build", 0) or 0))
    if level < 1:
        return False, "当前大星营地不可用（先 #建设前线营地 升至 L1）。"
    cap = CAMP_LEVELS[level]["storage"]
    stored = run.setdefault("stored", [])
    used = sum(i["qty"] for i in stored)
    moved, remain = [], []
    for item in run.get("carried") or []:
        space = max(0, cap - used)
        take = min(int(item["qty"]), space)
        if take > 0:
            stored.append({"name": item["name"], "mid": item.get("mid"), "qty": take})
            used += take
        if int(item["qty"]) - take > 0:
            remain.append(item)
    run["carried"] = remain
    run["stored"] = stored
    st["runs"][star] = run
    save(doc, st)
    return True, f"【营地封存】已存入 {len(stored)} 类物资（仓储 {used}/{cap}）。行囊：{bag_summary(run)}"


def evacuate(doc: Any, forced: bool = False) -> tuple[bool, str]:
    """#彼岸撤离（营地韧性保护）/ #彼岸强撤（损失 30%）。"""
    st = state_of(doc)
    found = _run_of(st) or next(((s, r) for s, r in (st.get("runs") or {}).items()
                                 if isinstance(r, Mapping) and r.get("status") == "evac_ready"), None)
    if not found:
        return False, "没有进行中的彼岸远征。"
    star, run = found
    campaign = CAMPAIGN_BY_STAR[star]
    level = camp_level_of(int(run.get("camp_build", 0) or 0))
    resilience = CAMP_LEVELS[level]["resilience"]
    loss = FORCED_LOSS_RATE if forced else 0.0
    if forced and resilience >= 12 and not forced:
        loss = 0.0
    pending = st.setdefault("pending_rewards", [])
    all_items = (run.get("carried") or []) + (run.get("stored") or [])
    if not all_items:
        return False, "行囊空空，无战果可撤离。"
    bundle = {"star": star, "campaign": campaign["name"], "materials": {}, "era": 0,
              "keys": [], "at": float(time.time())}
    for item in all_items:
        qty = int(item["qty"])
        if forced and loss:
            qty = max(1, int(qty * (1 - loss)))
        if item.get("mid"):
            bundle["materials"][item["mid"]] = bundle["materials"].get(item["mid"], 0) + qty
    if run.get("status") == "evac_ready":
        pass  # 决战奖励已在 boss_fight 入 pending
    pending.append(bundle)
    run["status"] = "evacuated"
    run["carried"], run["stored"] = [], []
    st["runs"][star] = run
    if forced:
        note = f"（强制撤离，物资损失 {int(loss * 100)}%）"
    else:
        note = f"（营地韧性 {resilience} 护航，物资无损）"
    save(doc, st)
    return True, (f"【{'彼岸强撤' if forced else '彼岸撤离'}】{campaign['name']}远征返航{note}。"
                  "#领取彼岸远征战果 结算入纳戒/材料袋。")


def claim(doc: Any) -> tuple[bool, str, dict[str, int], int, list[str]]:
    """#领取彼岸远征战果：材料入铸宝袋；纪元（首通钥匙附带）走 fashan.add_era。"""
    st = state_of(doc)
    pending = st.get("pending_rewards") or []
    if not pending:
        return False, "没有待领取的远征战果。", {}, 0, []
    from . import other_shore_forge as osf_mod, fashan as fashan_mod
    forge_st = osf_mod.ensure(doc)
    items: dict[str, int] = {}
    total_era = 0
    keys: list[str] = []
    lines = ["--- 彼岸远征战果领取 ---"]
    for b in pending:
        for mid, qty in (b.get("materials") or {}).items():
            items[mid] = items.get(mid, 0) + int(qty)
        total_era += int(b.get("era", 0) or 0)
        keys += list(b.get("keys") or [])
    osf_mod.add_materials(forge_st, items)
    era_gained = fashan_mod.add_era(doc, total_era) if total_era else 0
    st["pending_rewards"] = []
    save(doc, st)
    lines.append(f"结算 {len(pending)} 份战果：材料入铸宝材料袋。")
    lines.append("材料：" + "、".join(f"{osf_mod.MATERIAL_NAMES.get(k, k)}×{v}"
                                     for k, v in items.items()))
    if keys:
        lines.append("钥匙物：" + "、".join(keys))
    if total_era:
        lines.append(f"纪元积累 +{era_gained}（{fashan_mod.era_of(doc)}/{fashan_mod.ERA_CAP}）")
    return True, "\n".join(lines), items, era_gained, keys


def panel(doc: Any) -> str:
    st = state_of(doc)
    lines = ["--- 彼岸区域战役 ---"]
    found = _run_of(st)
    if not found:
        lines.append("当前没有进行中的个人远征。")
        cleared = st.get("first_clears") or []
        if cleared:
            lines.append("已首通：" + "、".join(CAMPAIGN_BY_STAR[s]["name"] for s in cleared))
        lines.append("在真世界踏足战役大星后 #进入区域远征 星坐标 开启。")
        return "\n".join(lines)
    star, run = found
    campaign = CAMPAIGN_BY_STAR[star]
    idx = int(run.get("stage_index", 0) or 0)
    stages = campaign["stages"]
    chain = " → ".join(
        f"{'已通' if c['star'] in (st.get('first_clears') or []) else '可战' if campaign_unlocked(st, c)[0] else '锁定'}·{c['name']}"
        for c in CAMPAIGNS)
    lines.append(f"【彼岸区域战役·{campaign['name']}】（{campaign['star']}）")
    if run.get("status") == "waiting_boss":
        boss = campaign["boss"]
        lines.append(f"阶段：决战待发——区域首领【{boss['name']}】（血量 {boss['hp']:,}）")
    else:
        lines.append(f"阶段：{idx + 1}/{len(stages)} {stages[idx]['name']}")
    level = camp_level_of(int(run.get("camp_build", 0) or 0))
    lines.append(f"前线营地：L{level}｜建设 {run.get('camp_build', 0)}/60")
    lines.append("行囊：" + bag_summary(run))
    lines.append(f"沧澜主线：{chain}")
    lines.append("动作：#推进彼岸战役｜#建设前线营地｜#存放彼岸战利品｜"
                 "#彼岸撤离｜#彼岸强撤｜#领取彼岸远征战果")
    return "\n".join(lines)
