"""仙王大宇宙（对齐原版 apps/Garden/GrandUniverse.js + model/grandUniverse.js）。

本轮范围：升格 / 面板 / 法则强化 / 灵韵炼化。
后续：自定义秘境（铸造/演绎/编辑/进入）、跨玩家访问（列表/开放/进入/离开）。

shortcut:
- 原版升格扣 10 点纪元积累，本移植无该资源，按 1000 万修为折算（与法身凝聚同口径）。
- 灵韵原本只能由 `#炼化宇宙灵韵` 从物品提纯，本模块按稀有度 1~6 → 5/10/20/40/80/160 折算。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MIN_AUTHORITY = 18          # 原版 GRAND_UNIVERSE_MIN_AUTHORITY
MAX_DUNGEONS = 12
ASCEND_EXP = 10_000_000
ERA_COST = 10     # 原版升格扣 10 点纪元积累（fashan.era_of/add_era 为唯一实现）
AURA_PER_RARITY = {1: 5, 2: 10, 3: 20, 4: 40, 5: 80, 6: 160, 7: 320, 8: 640}
AURA_DEFAULT = 5

# (阶, 名, 承载, 道则要求, 潜力, 修为, 灵韵)
LAW_STAGES: tuple[tuple[int, str, str, int, int, int, int], ...] = (
    (0, "宇宙初生", "真仙", 151, 0, 0, 0),
    (1, "红尘天则", "红尘仙", 160, 500, 5_000_000_000, 200),
    (2, "王境法域", "仙王", 175, 1_000, 10_000_000_000, 300),
    (3, "绝顶王域", "绝顶仙王", 190, 2_000, 20_000_000_000, 500),
    (4, "巨头天宇", "仙王巨头", 205, 4_000, 40_000_000_000, 800),
    (5, "帝光诸天", "帝光仙王", 220, 8_000, 80_000_000_000, 1_200),
)
LAW_MAX = LAW_STAGES[-1][0]
STAGE_BY_LEVEL = {row[0]: row for row in LAW_STAGES}
EXT_KEY = "grand_universe"


def _ext(doc: Any) -> dict | None:
    ext = getattr(doc, "ext", None)
    return ext if isinstance(ext, dict) else None


def _migrate_legacy_dict(old: Mapping[str, Any]) -> dict[str, Any]:
    """将旧版 ext['universe'] 结构无损迁移至 ext['grand_universe']。"""
    level = max(0, min(LAW_MAX, int(old.get("law", 0) or 0)))
    created_at = float(old.get("ascend_ts", 0) or 0)
    dungeons: list[dict[str, Any]] = []
    for i, d in enumerate(old.get("dungeons") or []):
        if not isinstance(d, Mapping):
            continue
        dungeons.append({
            "id": f"d{i + 1}",
            "name": str(d.get("name") or f"秘境{i + 1}"),
            "mode": "item",
            "category": "",
            "itemName": "",
            "description": str(d.get("intro") or ""),
            "enemyName": str(d.get("enemy") or ""),
            "rewardText": "",
            "lawLevel": level,
            "runs": int(d.get("cleared", 0) or 0),
            "lastRunAt": 0.0,
            "created_at": created_at,
        })
    return {
        "name": str(old.get("name") or "无名大宇宙"),
        "level": level,
        "aura": max(0, int(old.get("aura", 0) or 0)),
        "dungeons": dungeons,
        "dungeon_seq": len(dungeons),
        "open": bool(old.get("open", True)),
        "created_at": created_at,
    }


def migrate_legacy(doc: Any) -> dict[str, Any] | None:
    """若存在旧版 ext['universe'] 且尚未迁移，则就地转换为 ext['grand_universe']。"""
    ext = _ext(doc)
    if ext is None:
        return None
    st = ext.get(EXT_KEY)
    if isinstance(st, dict):
        return st
    old = ext.get("universe")
    if isinstance(old, Mapping) and old:
        migrated = _migrate_legacy_dict(old)
        ext[EXT_KEY] = migrated
        ext.pop("universe", None)
        return migrated
    return None


def state_of(doc: Any) -> dict[str, Any] | None:
    ext = _ext(doc)
    if ext is None:
        return None
    st = ext.get(EXT_KEY)
    if isinstance(st, dict):
        return st
    return migrate_legacy(doc)


def _new_state(name: str, now: float) -> dict[str, Any]:
    return {"name": name, "level": 0, "aura": 0, "dungeons": [],
            "open": True, "created_at": float(now)}


def law_stage(level: int) -> tuple:
    return STAGE_BY_LEVEL.get(max(0, min(LAW_MAX, int(level or 0))), LAW_STAGES[0])


def stage_name(level: int) -> str:
    return law_stage(level)[1]


def ascend(doc: Any, name: str, now: float) -> tuple[bool, str, dict[str, Any] | None]:
    """小世界 → 大宇宙。要求：有小世界、权柄 18+、已开自身之道、修为足够。"""
    ext = _ext(doc)
    if ext is None:
        return False, "档案异常。", None
    if state_of(doc):
        return False, "你的小世界早已升格为大宇宙（#我的大宇宙 查看）。", None
    world = ext.get("xiaoshijie")
    if not isinstance(world, Mapping):
        return False, "你尚未开辟小世界，何谈升格为宇宙。", None
    if int(getattr(doc, "realm_index", 0) or 0) < MIN_AUTHORITY:
        return False, f"需仙王权柄（境界 ≥{MIN_AUTHORITY}）才可开辟大宇宙。", None
    try:
        from . import ownway
        ow = ownway.state_of(doc)
        if int(ow.get("seg", 0) or 0) <= 0 and not ow.get("unique"):
            return False, "需先开创并命名自己的修炼体系（#开创自身之道），方能以自身之道升格宇宙。", None
    except Exception:
        pass
    # 原版扣 10 点纪元积累；不足时按法身同口径回退修为（fashan.create 已如此）
    from . import fashan
    era = fashan.era_of(doc)
    if era >= ERA_COST:
        doc.ext["era_points"] = era - ERA_COST
        cost_note = f"纪元积累 -{ERA_COST}"
    else:
        exp = int(getattr(doc, "exp", 0) or 0)
        if exp < ASCEND_EXP:
            return False, (f"升格需 {ERA_COST} 点纪元积累（当前 {era}），"
                           f"或 {ASCEND_EXP:,} 修为（当前 {exp:,}）。"), None
        doc.exp = exp - ASCEND_EXP
        cost_note = f"修为 -{ASCEND_EXP:,}（纪元积累不足 {ERA_COST}）"
    st = _new_state(name, now)
    ext[EXT_KEY] = st
    return True, (f"【界门洞开】「{name}」自小世界升格为大宇宙（{cost_note}）。\n"
                  f"法则：{stage_name(0)}（承载 {law_stage(0)[2]}）｜灵韵 0\n"
                  "发 #完善宇宙法则*1 提升法则，或 #炼化宇宙灵韵 分类*物品*数量 积攒灵韵。"), st


def aura_of_item(item: Mapping[str, Any] | None) -> int:
    try:
        rarity = int(float((item or {}).get("稀有度", 0) or 0))
    except (TypeError, ValueError):
        rarity = 0
    return AURA_PER_RARITY.get(rarity, AURA_DEFAULT)


def refine_aura(st: dict[str, Any], inv: Mapping[str, int], item_name: str,
                qty: int, item_index: Mapping[str, Any]) -> tuple[bool, str, dict[str, int], int]:
    """炼化物品 → 灵韵。返回 (ok, msg, 扣除物品, 获得灵韵)。"""
    name = str(item_name or "").strip()
    if not name:
        return False, "格式：#炼化宇宙灵韵 分类*物品名*数量", {}, 0
    have = int(inv.get(name, 0) or 0)
    qty = max(1, int(qty or 1))
    if have < qty:
        return False, f"纳戒中「{name}」只有 {have} 个。", {}, 0
    per = aura_of_item(item_index.get(name))
    gain = per * qty
    st["aura"] = int(st.get("aura", 0) or 0) + gain
    return True, (f"【万物归源】炼化 {name}×{qty}，得宇宙灵韵 {gain:,}"
                  f"（当前 {int(st['aura']):,}）。"), {name: qty}, gain


def improve_law(doc: Any, st: dict[str, Any], times: int) -> tuple[bool, str, dict[str, int]]:
    """连续升 N 阶，逐阶扣潜力/修为/灵韵。返回 (ok, msg, 消耗明细)。"""
    times = max(1, min(5, int(times or 1)))
    cur = int(st.get("level", 0) or 0)
    if cur >= LAW_MAX:
        return False, "法则已至「帝光诸天」，无可再升。", {}
    target = min(LAW_MAX, cur + times)
    ext = _ext(doc) or {}
    need_pot = sum(law_stage(lv)[4] for lv in range(cur + 1, target + 1))
    need_exp = sum(law_stage(lv)[5] for lv in range(cur + 1, target + 1))
    need_aura = sum(law_stage(lv)[6] for lv in range(cur + 1, target + 1))
    have_pot = int(float(ext.get("potential", 0) or 0))
    have_exp = int(getattr(doc, "exp", 0) or 0)
    have_aura = int(st.get("aura", 0) or 0)
    if have_pot < need_pot:
        return False, f"潜力不足：升 {cur}→{target} 需 {need_pot:,}，现有 {have_pot:,}。", {}
    if have_exp < need_exp:
        return False, f"修为不足：需 {need_exp:,}，现有 {have_exp:,}。", {}
    if have_aura < need_aura:
        return False, f"灵韵不足：需 {need_aura:,}，现有 {have_aura:,}（#炼化宇宙灵韵 提纯）。", {}
    ext["potential"] = have_pot - need_pot
    doc.exp = have_exp - need_exp
    st["aura"] = have_aura - need_aura
    st["level"] = target
    stage = law_stage(target)
    return True, (f"【大宇宙·法则升华】{stage_name(cur)} → {stage[1]}（承载 {stage[2]}）。\n"
                  f"耗潜力 {need_pot:,}、修为 {need_exp:,}、灵韵 {need_aura:,}"
                  f"（余灵韵 {int(st['aura']):,}）。"), {
        "potential": need_pot, "exp": need_exp, "aura": need_aura}


def registry_entry(st: Mapping[str, Any], doc: Any, now: float) -> dict[str, Any]:
    """写入全服注册表的元信息（不含玩家私有资源）。"""
    return {
        "uid": str(getattr(doc, "uid", "")),
        "owner": str(getattr(doc, "name", "") or ""),
        "name": str(st.get("name") or ""),
        "level": int(st.get("level", 0) or 0),
        "open": bool(st.get("open", True)),
        "dungeons": len(st.get("dungeons") or []),
        "updated_at": float(now),
    }


def panel(doc: Any, st: Mapping[str, Any], now: float) -> str:
    level = int(st.get("level", 0) or 0)
    stage = law_stage(level)
    nxt = law_stage(level + 1) if level < LAW_MAX else None
    lines = [f"【大宇宙·{st.get('name') or '无名'}】",
             f"法则：{stage[1]}（{level}/{LAW_MAX}）｜承载上限：{stage[2]}",
             f"灵韵：{int(st.get('aura', 0) or 0):,}｜秘境：{len(st.get('dungeons') or [])}/{MAX_DUNGEONS}",
             f"接引：{'对外开放' if st.get('open', True) else '封闭'}"]
    if nxt:
        lines.append(f"下一阶：{nxt[1]}（{nxt[2]}）需潜力 {nxt[4]:,}、修为 {nxt[5]:,}、灵韵 {nxt[6]:,}")
        lines.append("提升：#完善宇宙法则*1（可连升，最多 5 阶）")
    else:
        lines.append("法则已至帝光诸天，诸天之上再无可升。")
    lines.append("灵韵来源：#炼化宇宙灵韵 分类*物品名*数量")
    return "\n".join(lines)


# ---------------------------------------------------------------- 宇宙秘境

DUNGEON_AURA_COST = 100
DUNGEON_COOLDOWN = 8 * 3600
DUNGEON_CATEGORIES = ("装备", "丹药", "道具", "功法", "草药", "食材", "材料", "仙宠口粮", "盒子", "宝石")
DERIVE_COST = {"cultivation": 10_000_000_000_000, "blood": 10_000_000_000_000,
               "sourceStone": 100_000_000, "aura": 1_000}
DERIVE_DISCOUNT = 0.35
EDIT_FIELDS = {"简介": "description", "敌人": "enemyName", "奖励": "rewardText"}


def _dungeons(st: dict[str, Any]) -> list[dict[str, Any]]:
    rows = st.get("dungeons")
    if not isinstance(rows, list):
        rows = st["dungeons"] = []
    return rows


def _find(st: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((d for d in _dungeons(st) if str(d.get("name")) == str(name)), None)


def _check_name(name: str) -> str | None:
    text = str(name or "").strip()
    return text if 2 <= len(text) <= 10 else None


def forge_dungeon(st: dict[str, Any], inv: Mapping[str, int], name: str,
                  category: str, item_name: str) -> tuple[bool, str, dict[str, int]]:
    """`#铸造宇宙秘境 名字*分类*物品名`：耗 100 灵韵 + 1 个物品。"""
    title = _check_name(name)
    if not title:
        return False, "秘境名需 2~10 字。", {}
    rows = _dungeons(st)
    if any(str(d.get("name")) == title for d in rows):
        return False, f"大宇宙中已有同名秘境「{title}」。", {}
    if len(rows) >= MAX_DUNGEONS:
        return False, f"秘境数量已达 {MAX_DUNGEONS} 座上限。", {}
    if category not in DUNGEON_CATEGORIES:
        return False, f"分类需为：{'、'.join(DUNGEON_CATEGORIES)}。", {}
    if int(st.get("aura", 0) or 0) < DUNGEON_AURA_COST:
        return False, f"灵韵不足：开天需 {DUNGEON_AURA_COST}（现有 {int(st.get('aura', 0) or 0)}）。", {}
    item = str(item_name or "").strip()
    if int(inv.get(item, 0) or 0) < 1:
        return False, f"纳戒中没有「{item}」。", {}
    st["aura"] = int(st["aura"]) - DUNGEON_AURA_COST
    st["dungeon_seq"] = int(st.get("dungeon_seq", 0) or 0) + 1
    rows.append({
        "id": f"d{int(st.get('dungeon_seq', 0) or 0) + 1}",
        "name": title, "mode": "item", "category": category, "itemName": item,
        "description": "", "enemyName": "", "rewardText": "",
        "lawLevel": int(st.get("level", 0) or 0), "runs": 0, "lastRunAt": 0.0,
        "created_at": 0.0,
    })
    return True, (f"【造化秘境·以物开天】\n秘境：「{title}」\n核心：{category}·{item}\n"
                  f"法则承载：{law_stage(st.get('level', 0))[2]}｜消耗灵韵 {DUNGEON_AURA_COST}\n"
                  f"可发 #编辑宇宙秘境 {title}*简介*内容 自定义。"), {item: 1}


def derive_dungeon(doc: Any, st: dict[str, Any], name: str) -> tuple[bool, str, dict[str, int]]:
    """`#演绎宇宙秘境 名字`：权柄 20+，消耗修为/血气/源石/灵韵。"""
    title = _check_name(name)
    if not title:
        return False, "秘境名需 2~10 字。", {}
    authority = int(getattr(doc, "realm_index", 0) or 0)
    if authority < 20:
        return False, f"需准仙帝权柄（境界 ≥20）才能凭空演绎秘境（当前 {authority}）。", {}
    rows = _dungeons(st)
    if any(str(d.get("name")) == title for d in rows):
        return False, f"大宇宙中已有同名秘境「{title}」。", {}
    if len(rows) >= MAX_DUNGEONS:
        return False, f"秘境数量已达 {MAX_DUNGEONS} 座上限。", {}
    mult = DERIVE_DISCOUNT if authority >= 21 else 1.0
    cost = {k: int(v * mult) for k, v in DERIVE_COST.items()}
    ext = _ext(doc) or {}
    have = {"cultivation": int(getattr(doc, "exp", 0) or 0),
            "blood": int(ext.get("xueqi", 0) or 0),
            "sourceStone": int(ext.get("yuanshi", 0) or 0),
            "aura": int(st.get("aura", 0) or 0)}
    missing = [k for k in cost if have[k] < cost[k]]
    if missing:
        labels = {"cultivation": "修为", "blood": "血气", "sourceStone": "源石", "aura": "灵韵"}
        return False, "演绎代价不足：" + "、".join(
            f"{labels[k]}需 {cost[k]:,}（有 {have[k]:,}）" for k in missing), {}
    doc.exp = have["cultivation"] - cost["cultivation"]
    ext["xueqi"] = have["blood"] - cost["blood"]
    ext["yuanshi"] = have["sourceStone"] - cost["sourceStone"]
    st["aura"] = have["aura"] - cost["aura"]
    st["dungeon_seq"] = int(st.get("dungeon_seq", 0) or 0) + 1
    rows.append({
        "id": f"d{int(st.get('dungeon_seq', 0) or 0) + 1}",
        "name": title, "mode": "reincarnation", "category": "", "itemName": "",
        "description": "", "enemyName": "", "rewardText": "",
        "lawLevel": int(st.get("level", 0) or 0), "runs": 0, "lastRunAt": 0.0,
        "created_at": 0.0,
    })
    tail = "（路尽级权能减免至 35%）" if mult < 1 else "（准仙帝强行演绎，承受完整开天代价）"
    return True, (f"【演绎万物轮回】\n你截取一缕宇宙可能，将「{title}」由虚化实{tail}。\n"
                  f"耗修为 {cost['cultivation']:,}、血气 {cost['blood']:,}、"
                  f"源石 {cost['sourceStone']:,}、灵韵 {cost['aura']:,}。"), {}


def edit_dungeon(st: dict[str, Any], name: str, field: str, value: str) -> tuple[bool, str]:
    dg = _find(st, name)
    if not dg:
        return False, f"大宇宙中没有「{name}」这座秘境。"
    key = EDIT_FIELDS.get(str(field).strip())
    if not key:
        return False, "可编辑字段：简介 / 敌人 / 奖励。"
    text = str(value or "").strip()
    if not 2 <= len(text) <= 60:
        return False, "内容需 2~60 字。"
    dg[key] = text
    return True, f"【秘境法则已改】{dg.get('name')}的{field}已更新。"


def dungeon_panel(st: Mapping[str, Any]) -> str:
    rows = _dungeons(dict(st))
    lines = [f"【宇宙秘境】{len(rows)}/{MAX_DUNGEONS} 座｜灵韵 {int(st.get('aura', 0) or 0):,}"]
    if not rows:
        lines.append("尚未开辟秘境。")
    for i, dg in enumerate(rows, 1):
        tags = []
        if dg.get("description"):
            tags.append(str(dg["description"]))
        if dg.get("enemyName"):
            tags.append("敌：" + str(dg["enemyName"]))
        lines.append(f"{i}. {dg.get('name')}（承载 {law_stage(dg.get('lawLevel', 0))[2]}"
                     f"｜已探 {int(dg.get('runs', 0) or 0)} 次）"
                     + (f"｜{'｜'.join(tags)}" if tags else ""))
    lines.append(f"铸造：#铸造宇宙秘境 名*分类*物品（{DUNGEON_AURA_COST} 灵韵）")
    lines.append(f"演绎：#演绎宇宙秘境 名（权柄 20+）｜编辑：#编辑宇宙秘境 名*简介|敌人|奖励*内容")
    lines.append(f"进入：#进入宇宙秘境 名（{DUNGEON_COOLDOWN // 3600} 小时冷却）")
    return "\n".join(lines)


def enter_dungeon(doc: Any, st: dict[str, Any], name: str, now: float,
                  rng: Any) -> tuple[bool, str, dict[str, int]]:
    """进入秘境：按法则阶卡权柄，成功率 0.72+(权柄-门槛)*0.08，失败气血降到 10%。"""
    dg = _find(st, name)
    if not dg:
        return False, f"大宇宙中没有「{name}」这座秘境。", {}
    ext = _ext(doc) or {}
    cd = ext.setdefault("universe_dungeon_cd", {})
    if not isinstance(cd, dict):
        cd = ext["universe_dungeon_cd"] = {}
    key = f"{dg.get('id')}"
    last = float(cd.get(key, 0) or 0)
    left = last + DUNGEON_COOLDOWN - now
    if left > 0:
        return False, (f"「{name}」冷却中，约 {int(left // 3600)} 时 "
                       f"{int((left % 3600) // 60)} 分后可再入。"), {}
    law_level = int(dg.get("lawLevel", 0) or 0)
    need = 19 if law_level >= 4 else (18 if law_level >= 2 else 17)
    authority = int(getattr(doc, "realm_index", 0) or 0)
    if authority < need:
        return False, f"此秘境需境界 {need} 以上才能承载（当前 {authority}）。", {}
    chance = max(0.35, min(0.98, 0.72 + (authority - need) * 0.08))
    cd[key] = now
    dg["lastRunAt"] = now
    dg["runs"] = int(dg.get("runs", 0) or 0) + 1
    mult = law_level + 1
    if rng.random() >= chance:
        doc.ext["hp"] = max(1, int(float(doc.ext.get("hp", 0) or 0) * 0.1))
        return True, (f"【{name}】秘境法则崩摧，你被反噬震出——气血只剩一成"
                      f"（成功率 {chance:.0%}，{DUNGEON_COOLDOWN // 3600} 小时后可再入）。"), {}
    rewards = {"exp": 50_000_000 * mult, "xueqi": 50_000_000 * mult,
               "potential": 5 * mult, "aura": 20 * mult}
    doc.exp = int(getattr(doc, "exp", 0) or 0) + rewards["exp"]
    ext["xueqi"] = int(ext.get("xueqi", 0) or 0) + rewards["xueqi"]
    ext["potential"] = int(float(ext.get("potential", 0) or 0)) + rewards["potential"]
    st["aura"] = int(st.get("aura", 0) or 0) + rewards["aura"]
    return True, (f"【{name}】你踏破秘境法则（成功率 {chance:.0%}）：\n"
                  f"修为 +{rewards['exp']:,}，血气 +{rewards['xueqi']:,}，"
                  f"潜力 +{rewards['potential']}，灵韵 +{rewards['aura']}。"), rewards


def set_open(st: dict[str, Any], value: bool) -> tuple[bool, str]:
    """`#开放大宇宙` / `#关闭大宇宙`：接引开关（关闭后他人无法进入）。"""
    st["open"] = bool(value)
    if value:
        return True, (f"【界门洞开】「{st.get('name')}」已接入诸天位面，"
                      "其他修士现在可以进入。")
    return True, f"【界门封闭】「{st.get('name')}」已封闭，暂不接引外界生灵。"


# ---------------------------------------------------------------- 跨玩家访问

def list_open(reg: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(v) for v in (reg or {}).values()
            if isinstance(v, Mapping) and v.get("open", True) and v.get("name")]
    rows.sort(key=lambda r: (-int(r.get("level", 0) or 0), -float(r.get("updated_at", 0) or 0)))
    return rows


def enter(doc: Any, reg: Mapping[str, Any], target: str) -> tuple[bool, str, str]:
    """`#进入大宇宙 X`：X 可为 uid、宇宙名或 @界主。返回 (ok, msg, 界主uid)。"""
    key = str(target or "").strip()
    if not key:
        return False, "请指定目标：#进入大宇宙 QQ / 宇宙名 / @界主。", ""
    rows = [dict(v) for v in (reg or {}).values() if isinstance(v, Mapping)]
    hit = next((r for r in rows if key in (str(r.get("uid")), str(r.get("name")))), None)
    if hit is None:
        hit = next((r for r in rows if key and key in str(r.get("name"))), None)
    if hit is None:
        return False, f"没有找到「{key}」这座大宇宙。", ""
    owner = str(hit.get("uid") or "")
    if owner == str(getattr(doc, "uid", "")):
        return False, "你本就是这座大宇宙的界主。", owner
    if hit.get("open") is False:
        return False, f"「{hit.get('name')}」已封闭，暂不接引外界生灵。", owner
    ext = _ext(doc) or {}
    pos = ext.get("universe_pos")
    if isinstance(pos, Mapping) and pos.get("owner"):
        return False, f"你现处「{pos.get('name')}」，先 #离开大宇宙 再入他界。", owner
    ext["universe_pos"] = {"owner": owner, "name": str(hit.get("name")),
                           "level": int(hit.get("level", 0) or 0), "at": 0.0}
    return True, (f"【界门洞开】你踏入「{hit.get('name')}」（界主 {hit.get('owner') or owner}，"
                  f"法则 {stage_name(int(hit.get('level', 0) or 0))}）。\n"
                  "在此可观摩他人宇宙法则；发 #离开大宇宙 返回。"), owner


def leave(doc: Any) -> tuple[bool, str]:
    ext = _ext(doc) or {}
    pos = ext.get("universe_pos")
    if not isinstance(pos, Mapping) or not pos.get("owner"):
        return False, "你当前不在其他玩家的大宇宙中。"
    name = str(pos.get("name") or "")
    ext.pop("universe_pos", None)
    return True, f"【界门闭合】你自「{name}」退出，回到己身宇宙。"
