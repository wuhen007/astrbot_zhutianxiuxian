"""无尽劫境 · 劫环核心（单人 Roguelike，纯函数 + 局部战斗）。

对齐原版：
- data/无尽劫境.json：6 大世界 / 57 项能力 / 20 件诸天神器 / 10 档难度（A1-A10）
- apps/EndlessRealm.js：`#开启无尽劫境` → 星图定途 → 逐层推进 → 劫后抉择（每 3 层）
  → 能力三选一 → `#无尽撤离` 结算「劫境道痕」；每 10 层 Boss，通关解锁下一档
- model/endlessDifficulty.js：敌方三维 = 1 + (tier-1) × (0.35 / 0.22 / 0.15)
- model/endlessCelestial.js：每日天象（能力强度 / 道痕收益 / 商店价格）

本移植（B8-1，单人劫环）：
- 一局 10 层；第 5 层精英、第 10 层 Boss；第 3/6/9 层后「劫后问道」三选一
- 每层先看星图三途（战斗 / 精英 / 机缘 / 休整 / 道痕矿脉），选定后 `#无尽下一关`
- 能力只取数值型效果；闪避/减伤/斩杀等按系数折算为攻防血（见 `_fold_effect`），
  召唤/连击/周期天罚等 proc 在 B8-1 不单独结算（文档标注）
- 命火 / 心神 / 无尽秘钥 / 组队 / 跨服 / 商店 / 道碑 / 至宝 → B8-2/B8-3
"""

from __future__ import annotations
from .clock import day_key

import copy
import datetime
import random
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .battle import Unit, spar_full

MAX_LAYERS = 10
ENTRY_COST = 200_000
ENTRY_REALM = 15
BANK_ON_DEFEAT = 0.5
CLEAR_BONUS = 300

TIER_NAMES = [
    "本初劫境", "梦魇劫境", "天灾劫境", "灭世劫境", "纪元劫境",
    "轮回劫境", "祭道劫境", "超脱劫境", "彼岸劫境", "无量劫境",
]

TIERS = [
    {
        "tier": i + 1, "code": f"A{i + 1}", "name": name,
        "hp": 1 + i * 0.35, "atk": 1 + i * 0.22, "def": 1 + i * 0.15,
        "reward": 1 + i * 0.15,
    }
    for i, name in enumerate(TIER_NAMES)
]

PHENOMENA = [
    {"id": "sealed_treasures", "name": "黯星封宝", "tone": "danger",
     "desc": "两件无尽至宝被黯星遮蔽（至宝系统 B8-2 开放后生效）。"},
    {"id": "ability_ebb", "name": "万法低潮", "tone": "danger", "ability": 0.75,
     "desc": "本日能力加成降低 25%。"},
    {"id": "ability_surge", "name": "诸天共鸣", "tone": "gold", "ability": 1.25,
     "desc": "本日能力加成提高 25%。"},
    {"id": "trace_drought", "name": "道痕枯潮", "tone": "danger", "token": 0.7,
     "desc": "劫境道痕收益降低 30%。"},
    {"id": "shop_inflation", "name": "天市炽盛", "tone": "danger", "shop": 1.25,
     "desc": "无尽商店价格上涨 25%。"},
    {"id": "shop_discount", "name": "万宝潮生", "tone": "gold", "shop": 0.8,
     "desc": "无尽商店价格降低 20%。"},
    {"id": "shop_expansion", "name": "商路拓界", "tone": "jade", "shop_limit": 1.2,
     "desc": "限购商品额度 +20%（最低 +1 件）。"},
]

NODE_LABEL = {
    "battle": "遭遇战", "elite": "精英", "boss": "界主",
    "boon": "诸天遗珍", "rest": "涅槃温泉", "treasure": "道痕矿脉",
}

NODE_REWARD = {"battle": 400, "elite": 900, "boss": 2600, "boon": 300, "rest": 200, "treasure": 800}

CHECKPOINT_CHOICES = [
    {"id": "rest", "name": "涅槃归息", "sub": "收拢残魂，重燃命火",
     "desc": "气血恢复至满。"},
    {"id": "fortune", "name": "诸天垂青", "sub": "以伤躯叩问未知机缘",
     "desc": "随机获得一件诸天神器。"},
    {"id": "ascend", "name": "道果升华", "sub": "熔炼此战，推高已有构筑",
     "desc": "随机一项已有能力 +1 级。"},
]


# ---------------------------------------------------------------- 内容索引


def index(content: Mapping) -> dict:
    abilities = {a["id"]: a for a in content.get("abilities", []) if a.get("id")}
    boons = {b["id"]: b for b in content.get("checkpointBoons", []) if b.get("id")}
    worlds = {w["id"]: w for w in content.get("worlds", []) if w.get("id")}
    return {"abilities": abilities, "boons": boons, "worlds": worlds}


def world_of(content: Mapping, world_id: str) -> dict:
    worlds = content.get("worlds") or []
    for w in worlds:
        if w.get("id") == world_id:
            return w
    return worlds[0] if worlds else {"id": "perfect", "name": "乱古界海", "rule": "",
                                     "normal": [], "elite": [], "boss": []}


def time_key(ts: float) -> str:
    return day_key(ts)


def tier_of(tier: int) -> dict:
    return TIERS[max(0, min(len(TIERS) - 1, int(tier or 1) - 1))]


def celestial_of(now: float) -> dict:
    day = int(day_key(now).replace("-", ""))
    return PHENOMENA[day % len(PHENOMENA)]


# ---------------------------------------------------------------- 状态


def state_of(doc: Any) -> dict:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = doc if isinstance(doc, dict) else {}
    raw = ext.get("endless") if isinstance(ext.get("endless"), Mapping) else {}
    st = copy.deepcopy(dict(raw))
    st.setdefault("active", False)
    st.setdefault("tier", 1)
    st.setdefault("layer", 0)
    st.setdefault("world", "perfect")
    st.setdefault("phase", "idle")     # idle / ready / choice / checkpoint
    st.setdefault("hp", 0)
    st.setdefault("hp_max", 0)
    st.setdefault("abilities", {})
    st.setdefault("boons", [])
    st.setdefault("choices", [])
    st.setdefault("checkpoint", [])
    st.setdefault("starmap", [])
    st.setdefault("pending_node", 0)
    st.setdefault("marks", 0)
    st.setdefault("marks_total", 0)
    st.setdefault("marks_earned", 0)
    if not st["marks_earned"] and int(st.get("marks_total", 0) or 0) > 0:
        # 兼容 B8-1 老数据：历史道痕从钱包回填
        st["marks_earned"] = int(st.get("marks_total", 0) or 0)
    st.setdefault("title", "")
    st.setdefault("shop_day", "")
    st.setdefault("shop_counts", {})
    st.setdefault("merchant", [])
    st.setdefault("merchant_layer", 0)
    st.setdefault("weekend_week", "")
    st.setdefault("sweep_day", "")
    st.setdefault("rerolls", 0)
    st.setdefault("meta", {})
    st.setdefault("treasures", [])
    st.setdefault("best_tier", 1)
    st.setdefault("best_layer", 0)
    st.setdefault("clears", [])
    st.setdefault("revived", False)
    st.setdefault("kills", 0)
    st.setdefault("started_at", 0.0)
    st.setdefault("celestial", "")
    st.setdefault("log", [])
    return st


def save(doc: Any, st: dict) -> Any:
    d = doc.model_copy(deep=True) if hasattr(doc, "model_copy") else copy.deepcopy(doc)
    d.ext["endless"] = st
    return d


def unlocked_tier(st: Mapping) -> int:
    return max(1, min(len(TIERS), 1 + len(st.get("clears") or [])))


def set_tier(st: Mapping, tier: int) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    if st2.get("active"):
        return False, "劫境之中无法调整难度，先「#无尽撤离」。", st2
    t = max(1, min(len(TIERS), int(tier or 1)))
    if t > unlocked_tier(st2):
        return False, (f"尚未解锁 {TIERS[t - 1]['code']}·{TIERS[t - 1]['name']}；"
                       f"通关上一档（第 {MAX_LAYERS} 层）后解锁。"), st2
    st2["tier"] = t
    return True, (f"难度已定为 {TIERS[t - 1]['code']}·{TIERS[t - 1]['name']}"
                  f"（敌方气血 ×{TIERS[t - 1]['hp']:.2f}、攻击 ×{TIERS[t - 1]['atk']:.2f}）"), st2


# ---------------------------------------------------------------- 属性与能力


def _fold_effect(eff: Mapping) -> dict:
    """把原版各类效果折算为攻/防/血/暴击/回血/复活。"""
    out = {"atk": 0.0, "def": 0.0, "hp": 0.0, "crit": 0.0, "regen": 0.0, "revive": 0.0}
    out["atk"] += float(eff.get("attackPct", 0) or 0)
    out["def"] += float(eff.get("defensePct", 0) or 0)
    out["hp"] += float(eff.get("hpPct", 0) or 0)
    out["crit"] += float(eff.get("critChance", 0) or 0)
    out["regen"] += float(eff.get("regenPct", 0) or 0)
    out["revive"] = max(out["revive"], float(eff.get("revivePct", 0) or 0))
    # 以下为近似折算（原版为 proc/闪避/减伤等独立机制，B8-1 不单独结算）
    out["def"] += float(eff.get("dodgeChance", 0) or 0) * 2.5
    out["def"] += float(eff.get("damageReduction", 0) or 0) * 1.5
    out["def"] += float(eff.get("reflectChance", 0) or 0) * float(eff.get("reflectPct", 0) or 0) * 0.5
    out["atk"] += float(eff.get("executePct", 0) or 0) * 0.4
    out["atk"] += float(eff.get("extraActionChance", 0) or 0) * 0.8
    out["atk"] += float(eff.get("comboAttackPct", 0) or 0) * 2.0
    out["atk"] += float(eff.get("summonPct", 0) or 0) * 0.25
    out["atk"] += float(eff.get("takeDamageAttackPct", 0) or 0)
    out["atk"] += float(eff.get("onWinAttackPct", 0) or 0)
    out["atk"] += float(eff.get("fireScalingPct", 0) or 0) * 0.5
    out["hp"] += float(eff.get("teamShieldPct", 0) or 0) * 0.4
    return out


def run_stats(st: Mapping, base: Mapping, content: Mapping, celestial: Mapping | None = None) -> dict:
    """能力与神器加成后的本局三维。"""
    ab_idx = index(content)["abilities"]
    boon_idx = index(content)["boons"]
    mul = float((celestial or {}).get("ability", 1) or 1)
    atk = 1.0
    df = 1.0
    hp = 1.0
    crit = float(base.get("bao", 0) or 0)
    regen = 0.0
    revive = 0.0
    for aid, lv in (st.get("abilities") or {}).items():
        ab = ab_idx.get(aid)
        if not ab:
            continue
        fold = _fold_effect(ab.get("effect") or {})
        lv = max(1, int(lv or 1))
        atk += fold["atk"] * lv * mul
        df += fold["def"] * lv * mul
        hp += fold["hp"] * lv * mul
        crit += fold["crit"] * lv * mul
        regen += fold["regen"] * lv * mul
        revive = max(revive, fold["revive"])
    for bid in st.get("boons") or []:
        boon = boon_idx.get(bid)
        if not boon:
            continue
        fold = _fold_effect(boon.get("effect") or {})
        atk += fold["atk"]
        df += fold["def"]
        hp += fold["hp"]
        crit += fold["crit"]
        regen += fold["regen"]
        revive = max(revive, fold["revive"])
    title = title_of(st)
    if title:
        atk += float(title.get("atk", 0) or 0)
        df += float(title.get("def", 0) or 0)
        hp += float(title.get("hp", 0) or 0)
    meta = st.get("meta") or {}
    if meta:
        atk += float(meta.get("atk", 1) or 1) - 1
        df += float(meta.get("def", 1) or 1) - 1
        hp += float(meta.get("hp", 1) or 1) - 1
        crit += float(meta.get("crit", 0) or 0)
        regen += float(meta.get("regen", 0) or 0)
    tr = treasure_effects(st)
    atk += tr["atk"]
    df += tr["def"]
    hp += tr["hp"]
    crit += tr["crit"]
    regen += tr["regen"]
    revive = max(revive, tr["revive"])
    return {
        "atk": max(1, int(float(base.get("atk", 1) or 1) * atk)),
        "def": max(0, int(float(base.get("def", 0) or 0) * df)),
        "hp": max(1, int(float(base.get("hp", 1) or 1) * hp)),
        "bao": min(1.0, round(crit, 4)),
        "regen": round(regen, 4),
        "revive": round(revive, 4),
        "atk_mult": round(atk, 3), "def_mult": round(df, 3), "hp_mult": round(hp, 3),
    }


def sync_hp(st: dict, stats: Mapping) -> dict:
    """能力提升血量上限时，补足新增部分。"""
    new_max = int(stats.get("hp", 1) or 1)
    old_max = int(st.get("hp_max", 0) or 0)
    if new_max > old_max:
        st["hp"] = int(st.get("hp", 0) or 0) + (new_max - old_max)
    st["hp_max"] = new_max
    st["hp"] = max(0, min(int(st.get("hp", 0) or 0), new_max))
    return st


# ---------------------------------------------------------------- 开局


def check_entry(doc: Any) -> tuple[bool, str]:
    if int(getattr(doc, "realm_index", 0) or 0) + 1 < ENTRY_REALM:
        return False, f"无尽劫境需第 {ENTRY_REALM} 境方可入内。"
    return True, ""


def start_run(st: Mapping, doc: Any, base: Mapping, content: Mapping,
              world_id: str = "", now: float = 0.0) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    if st2.get("active"):
        return False, "你已在一场劫境之中（#无尽构筑 / #无尽撤离）。", st2
    ok, msg = check_entry(doc)
    if not ok:
        return False, msg, st2
    worlds = content.get("worlds") or []
    if not worlds:
        return False, "劫境世界数据缺失。", st2
    pick = None
    if world_id:
        for w in worlds:
            if w.get("name") == world_id or w.get("id") == world_id:
                pick = w
                break
        if not pick:
            return False, f"没有「{world_id}」这个劫境世界。", st2
    else:
        pick = worlds[0]
    tier = min(unlocked_tier(st2), max(1, int(st2.get("tier", 1) or 1)))
    stats = run_stats(st2, base, content, celestial_of(now))
    st2.update({
        "active": True, "layer": 0, "world": pick["id"], "phase": "ready",
        "hp": int(base.get("hp", 1) or 1), "hp_max": int(base.get("hp", 1) or 1),
        "abilities": {}, "boons": [], "choices": [], "checkpoint": [],
        "marks": 0, "revived": False, "kills": 0, "started_at": float(now),
        "celestial": celestial_of(now)["id"], "pending_node": 0, "log": [],
        "tier": tier,
    })
    meta_eff = meta_effects(meta_state_of(doc))
    st2["meta"] = meta_eff
    st2["rerolls"] = int(meta_eff.get("reroll", 0) or 0)
    st2["treasures"] = equipped_treasures(treasury_of(doc))
    st2["starmap"] = make_starmap(st2, content, random.Random(f"{pick['id']}:{now}"))
    return True, (
        f"【无尽劫境·{pick['name']}】{pick.get('rule', '')}\n"
        f"难度 {TIERS[tier - 1]['code']}·{TIERS[tier - 1]['name']}｜共 {MAX_LAYERS} 层\n"
        f"本局气血 {st2['hp_max']:,}（独立投影之身，不影响本尊气血）\n"
        f"先看「#劫途星图」定途，再「#无尽下一关」。"
    ), st2


# ---------------------------------------------------------------- 星图


def _enemy_pool(world: Mapping, kind: str) -> list[dict]:
    key = {"battle": "normal", "elite": "elite", "boss": "boss"}.get(kind, "normal")
    return list(world.get(key) or []) or [{"name": "劫境游魂", "trait": ""}]


def make_starmap(st: Mapping, content: Mapping, rng: random.Random) -> list[dict]:
    layer = int(st.get("layer", 0) or 0) + 1
    world = world_of(content, str(st.get("world") or ""))
    if layer >= MAX_LAYERS:
        e = rng.choice(_enemy_pool(world, "boss"))
        return [{
            "type": "boss", "name": e.get("name") or "界主",
            "trait": e.get("trait") or "", "desc": "此界之主。击败即可通关本档。",
        }]
    kinds = ["battle", "boon", "rest", "treasure"]
    if layer >= 3:
        kinds.append("elite")
    picked: list[str] = []
    while len(picked) < 3:
        k = rng.choice(kinds)
        if k not in picked:
            picked.append(k)
    if "battle" not in picked and "elite" not in picked:
        picked[0] = "battle"
    nodes = []
    for k in picked:
        if k in ("battle", "elite"):
            e = rng.choice(_enemy_pool(world, k))
            nodes.append({"type": k, "name": e.get("name") or "劫境生灵",
                          "trait": e.get("trait") or "",
                          "desc": f"第 {layer} 层遭遇，胜则前行。"})
        elif k == "boon":
            nodes.append({"type": k, "name": "诸天遗珍",
                          "desc": "直接获得一项能力，无需战斗。"})
        elif k == "rest":
            nodes.append({"type": k, "name": "涅槃温泉",
                          "desc": "回复 40% 气血，稳妥前行。"})
        else:
            nodes.append({"type": k, "name": "道痕矿脉",
                          "desc": "大量劫境道痕，但无战斗收获。"})
    return nodes


def map_text(st: Mapping) -> str:
    nodes = st.get("starmap") or []
    layer = int(st.get("layer", 0) or 0) + 1
    lines = [f"--- 劫途星图 · 第 {layer}/{MAX_LAYERS} 层 ---"]
    for i, n in enumerate(nodes, 1):
        trait = f"（{n['trait']}）" if n.get("trait") else ""
        lines.append(f"{i}. 【{NODE_LABEL.get(n['type'], n['type'])}】{n['name']}{trait}")
        lines.append(f"   {n.get('desc')}")
    sel = int(st.get("pending_node", 0) or 0)
    if sel:
        lines.append(f"已选：{sel}. {nodes[sel - 1]['name']}" if sel <= len(nodes) else "")
    lines.append(f"定途：#星图定途 1-{len(nodes)}｜前进：#无尽下一关")
    return "\n".join(lines)


def select_node(st: Mapping, idx: int) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    nodes = st2.get("starmap") or []
    if st2.get("phase") != "ready":
        return False, "现在不是定途的时候。", st2
    i = int(idx or 0)
    if i < 1 or i > len(nodes):
        return False, f"星图只有 1-{len(nodes)} 条路。", st2
    st2["pending_node"] = i
    return True, f"已定途：{nodes[i - 1]['name']}（{NODE_LABEL.get(nodes[i - 1]['type'])}）", st2


# ---------------------------------------------------------------- 战斗与推进


def enemy_unit(st: Mapping, node: Mapping, stats: Mapping, content: Mapping,
               rng: random.Random) -> Unit:
    layer = int(st.get("layer", 0) or 0) + 1
    tier = tier_of(int(st.get("tier", 1) or 1))
    kind = str(node.get("type") or "battle")
    coef = {"battle": (2.0, 0.95, 0.38), "elite": (2.6, 1.00, 0.40),
            "boss": (3.6, 1.05, 0.55)}.get(kind, (2.0, 0.95, 0.38))
    grow = 1 + 0.06 * max(0, layer - 1)
    hp = int(float(stats["atk"]) * coef[0] * grow * tier["hp"])
    atk = int(float(stats["atk"]) * coef[1] * grow * tier["atk"])
    df = int(float(stats["def"]) * coef[2] * grow * tier["def"])
    trait = str(node.get("trait") or "")
    if trait == "狂暴":
        atk = int(atk * 1.08)
    elif trait == "再生":
        hp = int(hp * 1.12)
    elif trait == "破甲":
        df = int(df * 0.85)
    elif trait == "迅捷":
        atk = int(atk * 1.05)
    elif trait in ("禁疗", "封法"):
        hp = int(hp * 1.05)
    return Unit(str(node.get("name") or "劫境生灵"), max(1, atk), max(0, df), max(1, hp), 0.05)


def reward_of(st: Mapping, node: Mapping, celestial: Mapping) -> int:
    layer = int(st.get("layer", 0) or 0) + 1
    tier = tier_of(int(st.get("tier", 1) or 1))
    base = NODE_REWARD.get(str(node.get("type")), 400) + layer * 80
    title = title_of(st)
    return max(1, int(base * tier["reward"] * float(celestial.get("token", 1) or 1)
                      * (1 + float(title.get("marks", 0) or 0))))


def resolve_node(st: Mapping, base: Mapping, content: Mapping, now: float,
                 rng: random.Random) -> tuple[dict, dict]:
    """执行当前层。返回 (新状态, 结果 dict)。"""
    st2 = copy.deepcopy(dict(st))
    if st2.get("phase") != "ready":
        return st2, {"ok": False, "msg": "现在不能前进（先处理能力/劫后抉择）。"}
    nodes = st2.get("starmap") or []
    if not nodes:
        nodes = make_starmap(st2, content, rng)
        st2["starmap"] = nodes
    idx = int(st2.get("pending_node", 0) or 0)
    if idx < 1 or idx > len(nodes):
        idx = 1
    node = nodes[idx - 1]
    kind = str(node.get("type"))
    celestial = celestial_of(now)
    stats = run_stats(st2, base, content, celestial)
    sync_hp(st2, stats)
    layer = int(st2.get("layer", 0) or 0) + 1
    result: dict[str, Any] = {"ok": True, "node": node, "layer": layer, "win": True,
                              "battle": False, "marks": 0, "msg": ""}

    if kind in ("battle", "elite", "boss"):
        me = Unit("道友·劫境投影", stats["atk"], stats["def"], max(1, int(st2["hp"])), stats["bao"])
        foe = enemy_unit(st2, node, stats, content, rng)
        won, log, hp_left, _ = spar_full(me, foe, rng, max_rounds=30)
        st2["hp"] = max(0, int(hp_left))
        result["battle"] = True
        result["log"] = log
        result["enemy"] = foe.name
        if won != 0:
            if stats["revive"] > 0 and not st2.get("revived"):
                st2["revived"] = True
                st2["hp"] = max(1, int(stats["hp"] * float(stats["revive"])))
                result["msg"] = (f"你不敌{foe.name}，气血溃散——\n"
                                 f"✦ 能力「涅槃」发动，你在劫火中重塑残躯（{st2['hp']:,} 气血）。\n"
                                 f"本层未过，可重新定途再战。")
                st2["starmap"] = make_starmap(st2, content, rng)
                st2["pending_node"] = 0
                return st2, result
            # 真败：结算一半道痕，结束本局
            banked = int(st2.get("marks", 0) * BANK_ON_DEFEAT)
            st2["marks_total"] = int(st2.get("marks_total", 0)) + banked
            st2["marks_earned"] = int(st2.get("marks_earned", 0)) + banked
            st2 = _end_run(st2, victory=False)
            result["win"] = False
            result["msg"] = (f"你被{foe.name}击溃，劫境投影消散。\n"
                             f"带出劫境道痕 {banked:,}（战败仅保留一半）。")
            result["banked"] = banked
            return st2, result
        st2["kills"] = int(st2.get("kills", 0)) + 1

    marks = reward_of(st2, node, celestial)
    st2["marks"] = int(st2.get("marks", 0)) + marks
    result["marks"] = marks
    if kind == "rest":
        heal = int(stats["hp"] * 0.4)
        before = int(st2["hp"])
        st2["hp"] = min(int(stats["hp"]), before + heal)
        result["msg"] = f"你在涅槃温泉中调息，气血 {before:,} → {st2['hp']:,}。"
    elif kind == "boon":
        pool = [b for b in (content.get("checkpointBoons") or []) if b.get("id") not in (st2.get("boons") or [])]
        if pool:
            boon = rng.choice(pool)
            st2["boons"] = list(st2.get("boons") or []) + [boon["id"]]
            result["boon"] = boon.get("name")
            result["msg"] = f"诸天遗珍现世——你获得【{boon.get('name')}】！"
        else:
            result["msg"] = "遗珍已被你搜刮一空，只余道痕。"
    elif kind == "treasure":
        extra = int(marks * 1.5)
        st2["marks"] = int(st2["marks"]) + extra
        result["marks"] = marks + extra
        result["msg"] = f"道痕矿脉喷涌，额外采得 {extra:,} 道痕。"
    else:
        result["msg"] = f"你击败{result.get('enemy') or node.get('name')}，继续深入。"

    # 能力回复（每层结算）
    if stats["regen"] > 0:
        heal = int(stats["hp"] * float(stats["regen"]))
        st2["hp"] = min(int(stats["hp"]), int(st2["hp"]) + heal)

    st2["layer"] = layer
    st2["pending_node"] = 0

    if layer >= MAX_LAYERS:
        banked = int(st2.get("marks", 0)) + CLEAR_BONUS
        st2["marks_total"] = int(st2.get("marks_total", 0)) + banked
        st2["marks_earned"] = int(st2.get("marks_earned", 0)) + banked
        if int(st2.get("tier", 1)) not in (st2.get("clears") or []):
            st2["clears"] = list(st2.get("clears") or []) + [int(st2["tier"])]
        st2["best_tier"] = max(int(st2.get("best_tier", 1)), int(st2.get("tier", 1)))
        st2["best_layer"] = MAX_LAYERS
        st2 = _end_run(st2, victory=True)
        result["win"] = True
        result["clear"] = True
        result["banked"] = banked
        result["msg"] = (f"第 {MAX_LAYERS} 层界主伏诛，本档劫境通关！\n"
                         f"带出劫境道痕 {banked:,}（含通关奖励 {CLEAR_BONUS}）。\n"
                         f"已解锁 {TIERS[min(len(TIERS) - 1, int(st2.get('tier', 1)))]['code']} 难度。")
        return st2, result

    if layer in (3, 6, 9):
        st2["phase"] = "checkpoint"
        st2["checkpoint"] = copy.deepcopy(CHECKPOINT_CHOICES)
        result["checkpoint"] = True
    else:
        st2["choices"] = ability_choices(st2, content, rng)
        st2["phase"] = "choice" if st2["choices"] else "ready"
        if st2["choices"]:
            result["choices"] = st2["choices"]
        else:
            st2["starmap"] = make_starmap(st2, content, rng)
    st2["best_layer"] = max(int(st2.get("best_layer", 0)), layer)
    return st2, result


def _end_run(st: dict, victory: bool) -> dict:
    st["active"] = False
    st["phase"] = "idle"
    st["starmap"] = []
    st["choices"] = []
    st["checkpoint"] = []
    st["pending_node"] = 0
    st["hp"] = 0
    st["marks"] = 0
    st["log"] = list(st.get("log") or [])[-8:]
    return st


# ---------------------------------------------------------------- 能力三选一


def _rarity_weight(rarity: str) -> float:
    return {"普通": 6.0, "稀有": 4.0, "核心": 2.5, "禁忌": 1.0}.get(rarity, 2.0)


def ability_choices(st: Mapping, content: Mapping, rng: random.Random,
                    count: int = 3) -> list[str]:
    idx = index(content)
    world = str(st.get("world") or "")
    owned = st.get("abilities") or {}
    tier = int(st.get("tier", 1) or 1)
    meta = st.get("meta") or {}
    count = max(3, int(meta.get("choice", count) or count))
    unlocks = set(meta.get("unlocks") or [])
    pool = []
    for a in idx["abilities"].values():
        if a.get("bossOnly"):
            continue
        req = a.get("requiredMetaNode")
        if req and req not in unlocks:
            continue
        if int(a.get("minDifficultyTier", 1) or 1) > tier:
            continue
        max_lv = max(1, int(a.get("maxLevel", 3) or 3))
        if int(owned.get(a["id"], 0) or 0) >= max_lv:
            continue
        pool.append(a)
    related = [a for a in pool if a.get("world") == world]
    neutral = [a for a in pool if a.get("world") == "neutral"]
    picks: list[str] = []

    def pick_from(cands: list[dict]) -> bool:
        cands = [a for a in cands if a["id"] not in picks]
        if not cands:
            return False
        weights = [_rarity_weight(str(a.get("rarity") or "")) for a in cands]
        aid = rng.choices(cands, weights=weights, k=1)[0]["id"]
        picks.append(aid)
        return True

    pick_from(related)
    pick_from(neutral)
    while len(picks) < count:
        if not pick_from(pool):
            break
    return picks[:count]


def pick_ability(st: Mapping, idx: int, content: Mapping) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    if st2.get("phase") != "choice":
        return False, "现在没有待选的道法。", st2
    choices = st2.get("choices") or []
    i = int(idx or 0)
    if i < 1 or i > len(choices):
        return False, f"只有 1-{len(choices)} 可选。", st2
    ab_idx = index(content)["abilities"]
    aid = choices[i - 1]
    ab = ab_idx.get(aid) or {}
    cur = int((st2.get("abilities") or {}).get(aid, 0) or 0)
    max_lv = max(1, int(ab.get("maxLevel", 3) or 3))
    if cur >= max_lv:
        return False, f"【{ab.get('name')}】已至满级。", st2
    st2.setdefault("abilities", {})[aid] = cur + 1
    st2["choices"] = []
    st2["phase"] = "ready"
    st2["starmap"] = make_starmap(st2, content, random.Random(f"{aid}:{st2['layer']}"))
    st2["pending_node"] = 0
    lv_txt = f"Lv.{cur + 1}" if cur else "Lv.1"
    return True, (f"你参悟【{ab.get('name')}】{lv_txt}——{ab.get('description', '')}"), st2


def reroll_choices(st: Mapping, content: Mapping, rng: random.Random) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    if st2.get("phase") != "choice":
        return False, "现在没有待选的道法。", st2
    if int(st2.get("rerolls", 0) or 0) <= 0:
        return False, "本次劫境没有剩余的重演次数（需在万劫道碑参悟「劫机重演」）。", st2
    st2["rerolls"] = int(st2["rerolls"]) - 1
    st2["choices"] = ability_choices(st2, content, rng)
    return True, f"劫机重演！剩余重演次数 {st2['rerolls']}。", st2


# ---------------------------------------------------------------- 劫后抉择


def apply_checkpoint(st: Mapping, idx: int, content: Mapping, base: Mapping,
                     rng: random.Random, now: float) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    if st2.get("phase") != "checkpoint":
        return False, "现在不是劫后抉择的时候。", st2
    i = int(idx or 0)
    opts = st2.get("checkpoint") or CHECKPOINT_CHOICES
    if i < 1 or i > len(opts):
        return False, f"只有 1-{len(opts)} 可选。", st2
    choice = opts[i - 1]
    cid = choice.get("id")
    celestial = celestial_of(now)
    if cid == "rest":
        stats = run_stats(st2, base, content, celestial)
        sync_hp(st2, stats)
        st2["hp"] = int(stats["hp"])
        msg = "【涅槃归息】劫火褪去，你的投影恢复至满血。"
    elif cid == "fortune":
        pool = [b for b in (content.get("checkpointBoons") or [])
                if b.get("id") not in (st2.get("boons") or [])]
        if pool:
            boon = rng.choice(pool)
            st2["boons"] = list(st2.get("boons") or []) + [boon["id"]]
            msg = f"【诸天垂青】一件诸天神器自虚空落下——【{boon.get('name')}】！"
        else:
            msg = "【诸天垂青】遗珍已尽，只得一缕道韵（道痕 +80）。"
            st2["marks"] = int(st2.get("marks", 0)) + 80
    else:
        owned = st2.get("abilities") or {}
        if owned:
            aid = rng.choice(list(owned.keys()))
            ab_idx = index(content)["abilities"]
            max_lv = max(1, int((ab_idx.get(aid) or {}).get("maxLevel", 3) or 3))
            if int(owned[aid]) < max_lv:
                owned[aid] = int(owned[aid]) + 1
                msg = f"【道果升华】【{(ab_idx.get(aid) or {}).get('name', aid)}】提升至 Lv.{owned[aid]}。"
            else:
                msg = "【道果升华】诸法皆满，道果化作道痕（+80）。"
                st2["marks"] = int(st2.get("marks", 0)) + 80
            st2["abilities"] = owned
        else:
            st2["choices"] = ability_choices(st2, content, rng)
            st2["phase"] = "choice"
            st2["checkpoint"] = []
            return True, "【道果升华】你尚未有道法可升，先选一门（#无尽选择 1-3）。", st2
    st2["phase"] = "ready"
    st2["checkpoint"] = []
    st2["starmap"] = make_starmap(st2, content, random.Random(f"cp:{st2['layer']}"))
    st2["pending_node"] = 0
    return True, msg, st2


# ---------------------------------------------------------------- 撤离 / 文本


def withdraw(st: Mapping, now: float) -> tuple[str, dict]:
    st2 = copy.deepcopy(dict(st))
    if not st2.get("active"):
        return "", st2
    banked = int(st2.get("marks", 0) or 0)
    st2["marks_total"] = int(st2.get("marks_total", 0)) + banked
    st2["marks_earned"] = int(st2.get("marks_earned", 0)) + banked
    st2["best_layer"] = max(int(st2.get("best_layer", 0)), int(st2.get("layer", 0)))
    st2["best_tier"] = max(int(st2.get("best_tier", 1)), int(st2.get("tier", 1)))
    layer = int(st2.get("layer", 0) or 0)
    st2 = _end_run(st2, victory=False)
    return (f"你自劫境中抽身而退（第 {layer} 层）。\n"
            f"带出劫境道痕 {banked:,}，累计 {st2['marks_total']:,}。"), st2


def status_text(st: Mapping, base: Mapping, content: Mapping, now: float) -> str:
    if not st.get("active"):
        tier = tier_of(int(st.get("tier", 1) or 1))
        return (f"--- 无尽劫境 ---\n"
                f"当前难度：{tier['code']}·{tier['name']}｜最高：A{st.get('best_tier', 1)} 第 {st.get('best_layer', 0)} 层\n"
                f"劫境道痕：{int(st.get('marks_total', 0)):,}｜称号：{title_of(st).get('name') or '无'}\n"
                f"未开启：#开启无尽劫境 [世界名]｜难度：#无尽难度 A2｜天象：#今日天象")
    stats = run_stats(st, base, content, celestial_of(now))
    sync_hp(st, stats)
    world = world_of(content, str(st.get("world") or ""))
    tier = tier_of(int(st.get("tier", 1) or 1))
    layer = int(st.get("layer", 0) or 0)
    phase = {"ready": "星图待定", "choice": "道法三选一", "checkpoint": "劫后问道"}.get(
        str(st.get("phase")), str(st.get("phase")))
    lines = [
        f"--- 无尽劫境 · {world.get('name')} ---",
        f"难度：{tier['code']}·{tier['name']}｜已过 {layer}/{MAX_LAYERS} 层｜{phase}",
        f"气血：{int(st.get('hp', 0)):,} / {int(stats['hp']):,}",
        f"攻 {stats['atk']:,}｜防 {stats['def']:,}｜暴击 {stats['bao']:.0%}",
        f"道痕：{int(st.get('marks', 0)):,}（未带出）｜钱包 {int(st.get('marks_total', 0)):,}"
        f"｜称号：{title_of(st).get('name') or '无'}",
        f"道法：{len(st.get('abilities') or {})} 门｜神器：{len(st.get('boons') or [])} 件",
    ]
    if st.get("phase") == "ready":
        lines.append(f"下一步：#劫途星图 → #星图定途 N → #无尽下一关")
    elif st.get("phase") == "choice":
        lines.append("待选道法：#无尽选择 1-3")
    elif st.get("phase") == "checkpoint":
        lines.append("劫后问道：#劫后抉择 1-3")
    return "\n".join(lines)


def build_text(st: Mapping, base: Mapping, content: Mapping, now: float) -> str:
    idx = index(content)
    stats = run_stats(st, base, content, celestial_of(now))
    revive_txt = f"{stats['revive']:.0%}" if stats["revive"] else "无"
    lines = ["--- 无尽构筑 ---",
             f"攻 {stats['atk']:,}（×{stats['atk_mult']}）｜防 {stats['def']:,}（×{stats['def_mult']}）"
             f"｜血 {stats['hp']:,}（×{stats['hp_mult']}）｜暴击 {stats['bao']:.0%}",
             f"回血 {stats['regen']:.1%}/层｜涅槃 {revive_txt}"
             f"｜称号：{title_of(st).get('name') or '无'}"]
    abs_ = st.get("abilities") or {}
    if abs_:
        lines.append("【道法】")
        for aid, lv in sorted(abs_.items(), key=lambda kv: -int(kv[1])):
            ab = idx["abilities"].get(aid) or {}
            lines.append(f"· {ab.get('name', aid)} Lv.{lv}/{ab.get('maxLevel', 3)}"
                         f"｜{ab.get('rarity', '')}｜{ab.get('description', '')}")
    else:
        lines.append("【道法】尚无")
    boons = st.get("boons") or []
    lines.append("【诸天神器】" + ("、".join(
        (idx["boons"].get(b) or {}).get("name", b) for b in boons) if boons else "无"))
    trs = st.get("treasures") or []
    if trs:
        parts = []
        for entry in trs:
            data = TREASURE_MAP.get(str(entry.get("id")))
            if not data:
                continue
            lv = int(entry.get("lv", 1) or 1)
            parts.append(f"{data['name']} Lv.{lv}"
                         + ("（已觉醒）" if _treasure_awakened(data, st) else ""))
        lines.append("【无尽至宝】" + ("、".join(parts) if parts else "无"))
    if int(st.get("rerolls", 0) or 0) > 0:
        lines.append(f"【劫机重演】剩余 {int(st['rerolls'])} 次")
    return "\n".join(lines)


# ---------------------------------------------------------------- 万劫道碑

BASE_COSTS = [50, 100, 180, 300, 450, 650, 900, 1200, 1550, 1950]
BRANCH_COSTS = [400, 800, 1400, 2200, 3200]

META_NODES = [
    {"id": "attack", "name": "征伐道痕", "alias": ["攻击", "征伐"], "max": 10,
     "costs": BASE_COSTS, "gate": 0, "atk": 0.05,
     "desc": "每级永久提高 5% 攻击。"},
    {"id": "hp", "name": "劫体道痕", "alias": ["生命", "劫体"], "max": 10,
     "costs": BASE_COSTS, "gate": 0, "hp": 0.06,
     "desc": "每级永久提高 6% 生命。"},
    {"id": "defense", "name": "守御道痕", "alias": ["防御", "守御"], "max": 10,
     "costs": BASE_COSTS, "gate": 0, "def": 0.06,
     "desc": "每级永久提高 6% 防御。"},
    {"id": "choice", "name": "衍算天机", "alias": ["四选一", "选项"], "max": 1,
     "costs": [800], "gate": 1,
     "desc": "能力三选一变为四选一。"},
    {"id": "reroll", "name": "劫机重演", "alias": ["刷新", "重置能力"], "max": 1,
     "costs": [1000], "gate": 1,
     "desc": "每次劫境可刷新一次能力三选一。"},
    {"id": "three_pointed_blade", "name": "三尖两刃刀", "alias": ["显圣神兵", "三尖刀"],
     "max": 1, "costs": [5000], "gate": 4,
     "desc": "A4 及以上劫境，三尖两刃刀进入能力池。"},
    {"id": "branch_healer", "name": "治疗师", "alias": ["治疗", "医者"], "branch": "healer",
     "max": 5, "costs": BRANCH_COSTS, "gate": 1, "regen": 0.05,
     "desc": "每级每层恢复 5% 气血。首次参悟后锁定流派。"},
    {"id": "branch_vanguard", "name": "破阵师", "alias": ["输出", "攻伐"], "branch": "vanguard",
     "max": 5, "costs": BRANCH_COSTS, "gate": 1, "atk": 0.10, "crit": 0.04,
     "desc": "每级攻击 +10%、暴击 +4%。首次参悟后锁定流派。"},
    {"id": "branch_guardian", "name": "守护者", "alias": ["坦克", "守护"], "branch": "guardian",
     "max": 5, "costs": BRANCH_COSTS, "gate": 1, "hp": 0.08, "def": 0.10,
     "desc": "每级生命 +8%、防御 +10%。首次参悟后锁定流派。"},
]
META_MAP = {n["id"]: n for n in META_NODES}


def _meta_node(query: str) -> dict | None:
    q = str(query or "").strip()
    for n in META_NODES:
        if q in (n["id"], n["name"]) or q in (n.get("alias") or []):
            return n
    return None


def meta_state_of(doc: Any) -> dict:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = doc if isinstance(doc, dict) else {}
    raw = ext.get("endless_meta") if isinstance(ext.get("endless_meta"), Mapping) else {}
    nodes = {}
    for n in META_NODES:
        nodes[n["id"]] = max(0, min(int(n["max"]), int((raw.get("nodes") or {}).get(n["id"], 0) or 0)))
    branch = str(raw.get("branch") or "")
    if branch not in ("healer", "vanguard", "guardian"):
        branch = ""
    return {"nodes": nodes, "branch": branch,
            "spent": max(0, int(raw.get("spent", 0) or 0))}


def save_meta(doc: Any, meta: dict) -> Any:
    d = doc.model_copy(deep=True) if hasattr(doc, "model_copy") else copy.deepcopy(doc)
    d.ext["endless_meta"] = meta
    return d


def meta_effects(meta: Mapping) -> dict:
    n = (meta or {}).get("nodes") or {}

    def r(k: str) -> int:
        return int(n.get(k, 0) or 0)

    return {
        "atk": 1 + 0.05 * r("attack") + 0.10 * r("branch_vanguard"),
        "hp": 1 + 0.06 * r("hp") + 0.08 * r("branch_guardian"),
        "def": 1 + 0.06 * r("defense") + 0.10 * r("branch_guardian"),
        "crit": 0.04 * r("branch_vanguard"),
        "regen": 0.05 * r("branch_healer"),
        "choice": 4 if r("choice") else 3,
        "reroll": 1 if r("reroll") else 0,
        "unlocks": (["three_pointed_blade"] if r("three_pointed_blade") else []),
    }


def meta_text(meta: Mapping, st: Mapping) -> str:
    n = (meta or {}).get("nodes") or {}
    clears = _clears_count(st)
    lines = ["--- 万劫道碑 ---",
             f"道痕钱包：{int(st.get('marks_total', 0) or 0):,}｜通关档数：{clears}",
             f"流派：{meta.get('branch') or '未定（首次参悟分支后锁定）'}"]
    for node in META_NODES:
        rank = int(n.get(node["id"], 0) or 0)
        gate = int(node.get("gate", 0) or 0)
        lock = "" if clears >= gate else f"🔒需通关 {gate} 档"
        cost = "" if rank >= int(node["max"]) else f"{node['costs'][rank]:,} 道痕"
        lines.append(f"· {node['name']} Lv.{rank}/{node['max']} {lock}"
                     + (f"｜下一级 {cost}" if cost else "｜已满"))
        lines.append(f"    {node['desc']}")
    eff = meta_effects(meta)
    lines.append(f"当前道碑加成：攻 ×{eff['atk']:.2f}｜防 ×{eff['def']:.2f}｜血 ×{eff['hp']:.2f}"
                 f"｜暴击 +{eff['crit']:.0%}｜每层回血 {eff['regen']:.0%}")
    lines.append("参悟：#参悟道碑 节点名｜重置：#重置万劫道碑")
    return "\n".join(lines)


def upgrade_meta(meta: Mapping, st: Mapping, query: str) -> tuple[bool, str, dict, dict]:
    meta2 = copy.deepcopy(dict(meta))
    st2 = copy.deepcopy(dict(st))
    node = _meta_node(query)
    if not node:
        return False, f"道碑上没有「{query}」。可发「#万劫道碑」查看。", meta2, st2
    nid = node["id"]
    rank = int(meta2["nodes"].get(nid, 0) or 0)
    if rank >= int(node["max"]):
        return False, f"【{node['name']}】已至满级。", meta2, st2
    if _clears_count(st2) < int(node.get("gate", 0) or 0):
        return False, f"【{node['name']}】需通关 {node['gate']} 档劫境。", meta2, st2
    branch = node.get("branch")
    if branch:
        if meta2.get("branch") and meta2["branch"] != branch:
            return False, f"已锁定「{meta2['branch']}」流派，不可改投。", meta2, st2
    cost = int(node["costs"][rank])
    if int(st2.get("marks_total", 0) or 0) < cost:
        return False, (f"道痕不足：【{node['name']}】下一级需 {cost:,}"
                       f"（持有 {int(st2.get('marks_total', 0) or 0):,}）。"), meta2, st2
    st2["marks_total"] = int(st2.get("marks_total", 0) or 0) - cost
    meta2["nodes"][nid] = rank + 1
    meta2["spent"] = int(meta2.get("spent", 0) or 0) + cost
    if branch:
        meta2["branch"] = branch
    return True, (f"参悟【{node['name']}】Lv.{rank + 1}，耗道痕 {cost:,}。\n{node['desc']}"
                  if node.get("desc") else f"参悟【{node['name']}】Lv.{rank + 1}。"), meta2, st2


def reset_meta(meta: Mapping, st: Mapping) -> tuple[bool, str, dict, dict]:
    """重置道碑：返还 80% 已投入道痕，清空节点与流派。"""
    refund = int(int((meta or {}).get("spent", 0) or 0) * 0.8)
    st2 = copy.deepcopy(dict(st))
    st2["marks_total"] = int(st2.get("marks_total", 0) or 0) + refund
    meta2 = {"nodes": {n["id"]: 0 for n in META_NODES}, "branch": "", "spent": 0}
    return True, f"万劫道碑已重置，返还道痕 {refund:,}（80%）。", meta2, st2


# ---------------------------------------------------------------- 无尽至宝

TREASURES = [
    {
        "id": "yoriichi", "name": "缘一的斩鬼之刀", "icon": "🗡️", "rarity": "神话",
        "base": {"atk": 0.06, "hp": 0.025, "crit": 0.03},
        "awaken": {"name": "日呼传人", "req": {"anime_sun_breath": 1, "anime_transparent_world": 1},
                   "effect": {"atk": 0.18, "hp": 0.10, "def": 0.05}},
        "desc": "继国缘一遗落的日轮刀。集齐日之呼吸与通透世界后觉醒。",
    },
    {
        "id": "ninetails", "name": "九尾人柱力", "icon": "🦊", "rarity": "神话",
        "base": {"atk": 0.04, "hp": 0.06, "regen": 0.005},
        "awaken": {"name": "仙狐模式", "req": {"anime_rasengan": 1, "anime_shadow_clone": 1},
                   "effect": {"atk": 0.15, "hp": 0.15, "def": 0.05}},
        "desc": "身负九尾查克拉的封印容器。集齐螺旋丸与影分身后觉醒。",
    },
    {
        "id": "domain", "name": "领域展开·无量空处", "icon": "🌀", "rarity": "神话",
        "base": {"atk": 0.04, "def": 0.045},
        "awaken": {"name": "无量空处", "min_abilities": 3,
                   "effect": {"atk": 0.15, "hp": 0.10, "def": 0.05}},
        "desc": "以咒力构筑生得领域。拥有 3 项能力后展开。",
    },
    {
        "id": "magical_girl", "name": "魔法少女·星光契约", "icon": "✨", "rarity": "史诗",
        "base": {"atk": 0.04, "hp": 0.04, "def": 0.015},
        "awaken": {"name": "星光魔法·完全变身", "world_count": ("anime", 2),
                   "effect": {"atk": 0.12, "hp": 0.08, "def": 0.08}},
        "desc": "与星光缔结的变身契约。掌握 2 项万象番界能力后完全变身。",
    },
    {
        "id": "wushi_clock", "name": "无始钟·镇压诸天", "icon": "🔔", "rarity": "神话",
        "base": {"atk": 0.04, "hp": 0.04, "def": 0.03},
        "awaken": {"name": "无始钟鸣", "min_abilities": 3,
                   "effect": {"atk": 0.18, "def": 0.09, "rewind": 0.10}},
        "desc": "无始大帝伴生古钟。拥有 3 项能力后钟鸣镇世。",
    },
    {
        "id": "hogyoku", "name": "崩玉·无限进化", "icon": "💎", "rarity": "禁忌",
        "base": {"atk": 0.06, "hp": 0.06, "def": 0.06},
        "awaken": {"name": "崩玉融合·无限进化", "req": {"anime_hogyoku": 3},
                   "effect": {"atk": 0.22, "hp": 0.20, "def": 0.18, "revive": 0.25}},
        "desc": "读取灵魂愿望并突破界限的核心。崩玉能力 3 级后融合进化。",
    },
]
TREASURE_MAP = {t["id"]: t for t in TREASURES}
TREASURE_LEVEL_CAP = 10
TREASURE_SLOT_COST = 8000
TREASURE_SLOT_MAX = 3


def treasury_of(doc: Any) -> dict:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = doc if isinstance(doc, dict) else {}
    raw = ext.get("endless_treasure") if isinstance(ext.get("endless_treasure"), Mapping) else {}
    owned = {}
    for tid, lv in (raw.get("owned") or {}).items():
        if tid in TREASURE_MAP:
            owned[tid] = max(1, min(TREASURE_LEVEL_CAP, int(lv or 1)))
    equipped = [tid for tid in (raw.get("equipped") or []) if tid in owned]
    slots = max(1, min(TREASURE_SLOT_MAX, int(raw.get("slots", 1) or 1)))
    return {"owned": owned, "equipped": equipped[:slots], "slots": slots}


def save_treasury(doc: Any, treasury: dict) -> Any:
    d = doc.model_copy(deep=True) if hasattr(doc, "model_copy") else copy.deepcopy(doc)
    d.ext["endless_treasure"] = treasury
    return d


def _treasure_awakened(data: Mapping, st: Mapping) -> bool:
    aw = data.get("awaken") or {}
    abilities = st.get("abilities") or {}
    if aw.get("req"):
        for aid, lv in (aw["req"] or {}).items():
            if int(abilities.get(aid, 0) or 0) < int(lv):
                return False
    if aw.get("min_abilities"):
        if len(abilities) < int(aw["min_abilities"]):
            return False
    if aw.get("world_count"):
        world, count = aw["world_count"]
        if sum(1 for aid in abilities if aid.startswith(str(world))) < int(count):
            return False
    return True


def treasure_effects(st: Mapping, content: Mapping | None = None) -> dict:
    out = {"atk": 0.0, "def": 0.0, "hp": 0.0, "crit": 0.0, "regen": 0.0, "revive": 0.0}
    for entry in st.get("treasures") or []:
        data = TREASURE_MAP.get(str(entry.get("id")))
        if not data:
            continue
        lv = max(1, int(entry.get("lv", 1) or 1))
        scale = 0.5 + 0.15 * lv
        for key in ("atk", "def", "hp", "crit", "regen"):
            out[key] += float((data.get("base") or {}).get(key, 0) or 0) * scale
        if _treasure_awakened(data, st):
            eff = (data.get("awaken") or {}).get("effect") or {}
            out["atk"] += float(eff.get("atk", 0) or 0)
            out["def"] += float(eff.get("def", 0) or 0)
            out["hp"] += float(eff.get("hp", 0) or 0)
            out["crit"] += float(eff.get("crit", 0) or 0)
            out["regen"] += float(eff.get("regen", 0) or 0)
            out["revive"] = max(out["revive"], float(eff.get("revive", 0) or 0))
    return out


def equipped_treasures(treasury: Mapping) -> list[dict]:
    owned = treasury.get("owned") or {}
    return [{"id": tid, "lv": int(owned.get(tid, 1))} for tid in (treasury.get("equipped") or [])]


def grant_treasure(treasury: Mapping, st: Mapping) -> tuple[dict, str | None]:
    t2 = copy.deepcopy(dict(treasury))
    cleared = _clears_count(st)
    if cleared <= 0:
        return t2, None
    owned = t2.setdefault("owned", {})
    for i in range(min(cleared, len(TREASURES))):
        data = TREASURES[i]
        if data["id"] not in owned:
            owned[data["id"]] = 1
            return t2, data["name"]
    return t2, None


def treasury_text(treasury: Mapping, st: Mapping) -> str:
    owned = treasury.get("owned") or {}
    equipped = treasury.get("equipped") or []
    lines = ["--- 无尽至宝 ---",
             f"槽位：{len(equipped)}/{treasury.get('slots', 1)}｜通关档数：{_clears_count(st)}",
             f"劫境道痕：{int(st.get('marks_total', 0) or 0):,}"]
    if not owned:
        lines.append("尚无至宝。每通关一档劫境，解锁一件至宝（A1 起）。")
    for data in TREASURES:
        tid = data["id"]
        lv = int(owned.get(tid, 0) or 0)
        if not lv:
            need = TREASURES.index(data) + 1
            lines.append(f"🔒 {data['name']}｜需通关 {need} 档")
            continue
        mark = "✅" if tid in equipped else "·"
        cost = 1000 + 750 * (lv - 1)
        lines.append(f"{mark} {data['icon']} {data['name']} Lv.{lv}/{TREASURE_LEVEL_CAP}"
                     f"｜升级 {cost:,} 道痕")
        lines.append(f"    基础：{_effect_txt(data.get('base'))}"
                     f"｜觉醒【{data['awaken']['name']}】：{_effect_txt(data['awaken'].get('effect'))}")
    lines.append("指令：#升级无尽至宝 名｜#装备无尽至宝 名｜#卸下无尽至宝 名｜#拓展无尽至宝槽")
    return "\n".join(lines)


def _effect_txt(eff: Mapping | None) -> str:
    if not eff:
        return "无"
    names = {"atk": "攻", "def": "防", "hp": "血", "crit": "暴击",
             "regen": "回血", "revive": "涅槃", "rewind": "回溯"}
    parts = []
    for k, v in eff.items():
        if not v:
            continue
        parts.append(f"{names.get(k, k)}+{float(v):.0%}")
    return "、".join(parts) or "无"


def upgrade_treasure(treasury: Mapping, st: Mapping, name: str) -> tuple[bool, str, dict, dict]:
    t2 = copy.deepcopy(dict(treasury))
    st2 = copy.deepcopy(dict(st))
    data = next((t for t in TREASURES if t["name"] == name), None)
    if not data:
        return False, f"没有「{name}」这件至宝。", t2, st2
    lv = int((t2.get("owned") or {}).get(data["id"], 0) or 0)
    if not lv:
        return False, f"尚未拥有【{data['name']}】。", t2, st2
    if lv >= TREASURE_LEVEL_CAP:
        return False, f"【{data['name']}】已满级。", t2, st2
    cost = 1000 + 750 * (lv - 1)
    if int(st2.get("marks_total", 0) or 0) < cost:
        return False, f"道痕不足：升级需 {cost:,}（持有 {int(st2.get('marks_total', 0) or 0):,}）。", t2, st2
    st2["marks_total"] = int(st2.get("marks_total", 0) or 0) - cost
    t2["owned"][data["id"]] = lv + 1
    return True, f"【{data['name']}】升至 Lv.{lv + 1}，耗道痕 {cost:,}。", t2, st2


def equip_treasure(treasury: Mapping, name: str) -> tuple[bool, str, dict]:
    t2 = copy.deepcopy(dict(treasury))
    data = next((t for t in TREASURES if t["name"] == name), None)
    if not data:
        return False, f"没有「{name}」这件至宝。", t2
    if data["id"] not in (t2.get("owned") or {}):
        return False, f"尚未拥有【{data['name']}】。", t2
    if data["id"] in (t2.get("equipped") or []):
        return False, f"【{data['name']}】已在槽位中。", t2
    if len(t2.get("equipped") or []) >= int(t2.get("slots", 1) or 1):
        return False, f"至宝槽已满（{t2['slots']}/{t2['slots']}），先卸下或拓展槽位。", t2
    t2["equipped"] = list(t2.get("equipped") or []) + [data["id"]]
    return True, f"已装备【{data['name']}】（下次入境生效）。", t2


def unequip_treasure(treasury: Mapping, name: str) -> tuple[bool, str, dict]:
    t2 = copy.deepcopy(dict(treasury))
    data = next((t for t in TREASURES if t["name"] == name), None)
    if not data:
        return False, f"没有「{name}」这件至宝。", t2
    if data["id"] not in (t2.get("equipped") or []):
        return False, f"【{data['name']}】未装备。", t2
    t2["equipped"] = [x for x in t2["equipped"] if x != data["id"]]
    return True, f"已卸下【{data['name']}】。", t2


def expand_slots(treasury: Mapping, st: Mapping) -> tuple[bool, str, dict, dict]:
    t2 = copy.deepcopy(dict(treasury))
    st2 = copy.deepcopy(dict(st))
    slots = int(t2.get("slots", 1) or 1)
    if slots >= TREASURE_SLOT_MAX:
        return False, "至宝槽已至上限（3 个）。", t2, st2
    if int(st2.get("marks_total", 0) or 0) < TREASURE_SLOT_COST:
        return False, f"拓展槽位需 {TREASURE_SLOT_COST:,} 道痕（持有 {int(st2.get('marks_total', 0) or 0):,}）。", t2, st2
    st2["marks_total"] = int(st2.get("marks_total", 0) or 0) - TREASURE_SLOT_COST
    t2["slots"] = slots + 1
    return True, f"至宝槽拓展至 {slots + 1} 个，耗道痕 {TREASURE_SLOT_COST:,}。", t2, st2


# ---------------------------------------------------------------- 扫荡


def sweep(st: Mapping, now: float, celestial: Mapping) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    if st2.get("active"):
        return False, "劫境进行中，无法扫荡（先撤离）。", st2
    best = int(st2.get("best_layer", 0) or 0)
    if best < 3:
        return False, "最高层数不足 3 层，无法扫荡。", st2
    today = time_key(now)
    if str(st2.get("sweep_day") or "") == today:
        return False, "今日已扫荡过，明日再来。", st2
    tier = tier_of(int(st2.get("tier", 1) or 1))
    gain = max(1, int(120 * best * float(tier["reward"])
                      * float(celestial.get("token", 1) or 1)))
    st2["sweep_day"] = today
    st2["marks_total"] = int(st2.get("marks_total", 0) or 0) + gain
    st2["marks_earned"] = int(st2.get("marks_earned", 0) or 0) + gain
    return True, (f"扫荡完成：按最高 {best} 层结算，获得劫境道痕 {gain:,}"
                  f"（每日一次）。"), st2


# ---------------------------------------------------------------- 称号

TITLES = [
    {"id": "ruins", "name": "初入劫境", "need_layer": 1, "need_clears": 0,
     "atk": 0.03, "hp": 0.03, "def": 0.03, "marks": 0.0,
     "desc": "第一次自劫境中生还。"},
    {"id": "walker", "name": "劫境行者", "need_layer": 5, "need_clears": 0,
     "atk": 0.06, "hp": 0.06, "def": 0.06, "marks": 0.05,
     "desc": "在劫境中走过五层。"},
    {"id": "breaker", "name": "破界者", "need_layer": 10, "need_clears": 1,
     "atk": 0.10, "hp": 0.10, "def": 0.10, "marks": 0.10,
     "desc": "首次打穿一档劫境。"},
    {"id": "unmoved", "name": "万劫不磨", "need_layer": 10, "need_clears": 3,
     "atk": 0.15, "hp": 0.15, "def": 0.15, "marks": 0.15,
     "desc": "打穿三档劫境，道心不磨。"},
    {"id": "master", "name": "无量劫主", "need_layer": 10, "need_clears": 6,
     "atk": 0.20, "hp": 0.20, "def": 0.20, "marks": 0.20,
     "desc": "六档劫境尽数踏平。"},
    {"id": "heaven", "name": "无尽劫境天尊", "need_layer": 10, "need_clears": 10,
     "atk": 0.25, "hp": 0.25, "def": 0.25, "marks": 0.25,
     "desc": "十档皆破，劫境称尊（原版全服第一专属，本插件改为通关 A10 授予）。"},
]
TITLE_MAP = {t["name"]: t for t in TITLES}


def _clears_count(st: Mapping) -> int:
    return len([c for c in (st.get("clears") or []) if int(c or 0) > 0])


def title_owned(st: Mapping, title: Mapping) -> bool:
    return (int(st.get("best_layer", 0) or 0) >= int(title.get("need_layer", 0))
            and _clears_count(st) >= int(title.get("need_clears", 0)))


def title_of(st: Mapping) -> dict:
    name = str(st.get("title") or "")
    t = TITLE_MAP.get(name)
    return t if t and title_owned(st, t) else {}


def owned_titles(st: Mapping) -> list[dict]:
    return [t for t in TITLES if title_owned(st, t)]


def equip_title(st: Mapping, name: str) -> tuple[bool, str, dict]:
    st2 = copy.deepcopy(dict(st))
    title = TITLE_MAP.get(str(name or "").strip())
    if not title:
        return False, f"没有「{name}」这个称号。可发「#称号」查看。", st2
    if not title_owned(st2, title):
        return False, f"尚未获得称号【{title['name']}】。", st2
    st2["title"] = title["name"]
    return True, (f"已佩戴称号【{title['name']}】：{title['desc']}\n"
                  f"加成：攻/防/血 +{title['atk']:.0%}，道痕 +{title['marks']:.0%}"), st2


def titles_text(st: Mapping) -> str:
    lines = ["--- 称号 ---"]
    cur = title_of(st)
    lines.append(f"当前佩戴：{cur.get('name') or '无'}")
    owned = {t["id"] for t in owned_titles(st)}
    for t in TITLES:
        mark = "✅" if t["id"] in owned else "🔒"
        wear = "（佩戴中）" if cur.get("id") == t["id"] else ""
        need = []
        if t.get("need_layer"):
            need.append(f"最高 {t['need_layer']} 层")
        if t.get("need_clears"):
            need.append(f"通关 {t['need_clears']} 档")
        lines.append(f"{mark} {t['name']}{wear}｜{'、'.join(need)}")
        lines.append(f"    {t['desc']}（攻防血 +{t['atk']:.0%}｜道痕 +{t['marks']:.0%}）")
    lines.append("佩戴：#佩戴称号 名称")
    return "\n".join(lines)


# ---------------------------------------------------------------- 周末免费


def is_weekend(now: float) -> bool:
    return time.gmtime(now + 8 * 3600).tm_wday >= 5


def week_key(now: float) -> str:
    y, w, _ = datetime.date.fromtimestamp(now).isocalendar()
    return f"{y}-W{w:02d}"


def weekend_available(st: Mapping, now: float) -> bool:
    return is_weekend(now) and str(st.get("weekend_week") or "") != week_key(now)


def weekend_text(st: Mapping, now: float) -> str:
    key = week_key(now)
    weekend = is_weekend(now)
    used = str(st.get("weekend_week") or "") == key
    lines = ["--- 周末免费 ---", f"今日：{'周末' if weekend else '工作日'}｜本周：{key}"]
    if not weekend:
        lines.append("周末（周六/周日）首次开启劫境免入场灵石。")
    elif used:
        lines.append("本周免费额度已用，下次周末再来。")
    else:
        lines.append("本周免费额度可用：开启劫境时自动免入场灵石。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 无尽商店


def shop_products(shop_content: Mapping) -> list[dict]:
    return list(shop_content.get("products") or [])


def shop_today(st: Mapping, now: float) -> dict:
    today = time_key(now)
    counts = st.get("shop_counts") if isinstance(st.get("shop_counts"), dict) else {}
    if str(st.get("shop_day") or "") != today:
        counts = {}
    return counts


def shop_limit(product: Mapping, celestial: Mapping) -> int:
    base = int(product.get("dailyLimit", 0) or 0)
    if base <= 0:
        return 0
    rate = float(celestial.get("shop_limit", 1) or 1)
    return max(1, int(-(-base * rate // 1)))


def shop_price(product: Mapping, celestial: Mapping) -> int:
    return max(1, int(float(product.get("price", 0) or 0) * float(celestial.get("shop", 1) or 1)))


def shop_text(st: Mapping, shop_content: Mapping, celestial: Mapping, now: float) -> str:
    counts = shop_today(st, now)
    lines = ["--- 无尽商店 ---",
             f"劫境道痕：{int(st.get('marks_total', 0) or 0):,}｜今日：{time_key(now)}",
             f"天象：{celestial.get('name')}（价格 ×{float(celestial.get('shop', 1) or 1):.2f}）"]
    for p in shop_products(shop_content):
        pid = str(p.get("id"))
        action = str(p.get("action") or "item")
        price = shop_price(p, celestial)
        limit = shop_limit(p, celestial)
        used = int(counts.get(pid, 0) or 0)
        limit_txt = "不限购" if limit <= 0 else f"今日 {used}/{limit}"
        lock = "" if action == "item" else "（暂未开放）"
        qty = int(p.get("quantity", 1) or 1)
        qty_txt = f"×{qty}" if qty > 1 else ""
        lines.append(f"· [{p.get('id')}] {p.get('name')}{qty_txt}｜{price:,} 道痕｜{limit_txt}{lock}")
        lines.append(f"    {p.get('description', '')}")
    lines.append("购买：#无尽购买 编号或名称[*数量]")
    return "\n".join(lines)


def buy_shop(st: Mapping, product_id: str, qty: int, now: float,
             shop_content: Mapping, celestial: Mapping) -> tuple[bool, str, dict, dict]:
    st2 = copy.deepcopy(dict(st))
    qty = max(1, int(qty or 1))
    key = str(product_id or "").strip()
    product = None
    for p in shop_products(shop_content):
        if str(p.get("id")) == key or str(p.get("name")) == key:
            product = p
            break
    if not product:
        return False, f"商店里没有「{product_id}」。", st2, {}
    if str(product.get("action") or "item") != "item":
        return False, f"【{product['name']}】对应系统尚未开放，暂不可购买。", st2, {}
    today = time_key(now)
    counts = shop_today(st2, now)
    st2["shop_day"] = today
    pid = str(product.get("id"))
    limit = shop_limit(product, celestial)
    used = int(counts.get(pid, 0) or 0)
    if limit > 0 and used + qty > limit:
        return False, f"【{product['name']}】今日限购 {limit} 件（已购 {used}）。", st2, {}
    price = shop_price(product, celestial) * qty
    if int(st2.get("marks_total", 0) or 0) < price:
        return False, (f"道痕不足：【{product['name']}】需 {price:,}"
                       f"（持有 {int(st2.get('marks_total', 0) or 0):,}）。"), st2, {}
    st2["marks_total"] = int(st2.get("marks_total", 0) or 0) - price
    counts[pid] = used + qty
    st2["shop_counts"] = counts
    grant = int(product.get("quantity", 1) or 1) * qty
    return True, (f"购入【{product['name']}】×{grant}，耗道痕 {price:,}"
                  f"（余 {st2['marks_total']:,}）。"), st2, {str(product["name"]): grant}


# ---------------------------------------------------------------- 劫境商人


def refresh_merchant(st: Mapping, shop_content: Mapping, celestial: Mapping,
                     rng: random.Random) -> dict:
    """每层可遇一次行商：4 件随机商品，价格 6-9 折，用未带出的道痕支付。"""
    st2 = copy.deepcopy(dict(st))
    layer = int(st2.get("layer", 0) or 0)
    if st2.get("merchant") and int(st2.get("merchant_layer", 0) or 0) == layer:
        return st2
    pool = [p for p in shop_products(shop_content) if str(p.get("action") or "item") == "item"]
    if not pool:
        return st2
    picks = rng.sample(pool, min(4, len(pool)))
    offers = []
    for p in picks:
        disc = round(rng.uniform(0.6, 0.9), 2)
        price = max(20, int(float(p.get("price", 0) or 0) * disc
                           * float(celestial.get("shop", 1) or 1) * 0.35))
        offers.append({
            "id": p.get("id"), "name": p.get("name"), "price": price,
            "discount": disc, "qty": int(p.get("quantity", 1) or 1),
            "desc": p.get("description", ""),
        })
    st2["merchant"] = offers
    st2["merchant_layer"] = layer
    return st2


def merchant_text(st: Mapping) -> str:
    offers = st.get("merchant") or []
    if not offers:
        return "劫境行商尚未现身（先「#无尽下一关」推进一层）。"
    lines = ["--- 劫境商人 ---",
             f"可用道痕：{int(st.get('marks', 0) or 0):,}（未带出）"]
    for i, o in enumerate(offers, 1):
        lines.append(f"{i}. {o['name']}×{o.get('qty', 1)}｜{o['price']:,} 道痕"
                     f"（{o['discount'] * 10:.1f} 折）")
        lines.append(f"    {o.get('desc', '')}")
    lines.append("购买：#劫境购买 1-4（本层有效）")
    return "\n".join(lines)


def buy_merchant(st: Mapping, idx: int, celestial: Mapping) -> tuple[bool, str, dict, dict]:
    st2 = copy.deepcopy(dict(st))
    offers = list(st2.get("merchant") or [])
    i = int(idx or 0)
    if i < 1 or i > len(offers):
        return False, f"商人只有 1-{len(offers)} 件货。", st2, {}
    offer = offers[i - 1]
    price = int(offer.get("price", 0) or 0)
    if int(st2.get("marks", 0) or 0) < price:
        return False, (f"未带出的道痕不足（{int(st2.get('marks', 0) or 0):,}/{price:,}）。\n"
                       f"提示：道痕需在劫境内使用，撤离后才能进商店。"), st2, {}
    st2["marks"] = int(st2.get("marks", 0) or 0) - price
    offers.pop(i - 1)
    st2["merchant"] = offers
    grant = int(offer.get("qty", 1) or 1)
    return True, (f"购入【{offer['name']}】×{grant}，耗道痕 {price:,}"
                  f"（余 {st2['marks']:,}）。"), st2, {str(offer["name"]): grant}


# ---------------------------------------------------------------- 等级 / 排名


def rank_rows(players: Sequence[Mapping], limit: int = 10) -> list[dict]:
    rows = []
    for p in players:
        ext = p.get("ext") or {}
        st = ext.get("endless") or {}
        if not isinstance(st, Mapping):
            continue
        tier = int(st.get("best_tier", 1) or 1)
        layer = int(st.get("best_layer", 0) or 0)
        marks = int(st.get("marks_earned", st.get("marks_total", 0)) or 0)
        if layer <= 0 and marks <= 0:
            continue
        rows.append({"name": p.get("name") or str(p.get("uid", ""))[:8],
                     "tier": tier, "layer": layer, "marks": marks})
    rows.sort(key=lambda r: (-r["tier"], -r["layer"], -r["marks"]))
    return rows[:limit]
