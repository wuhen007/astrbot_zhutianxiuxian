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

import copy
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
    {"id": "shop_inflation", "name": "天市炽盛", "tone": "danger",
     "desc": "无尽商店价格上涨 25%（商店 B8-2 开放后生效）。"},
    {"id": "shop_discount", "name": "万宝潮生", "tone": "gold",
     "desc": "无尽商店价格降低 20%（商店 B8-2 开放后生效）。"},
    {"id": "shop_expansion", "name": "商路拓界", "tone": "jade",
     "desc": "限购商品额度 +20%（商店 B8-2 开放后生效）。"},
]

NODE_LABEL = {
    "battle": "遭遇战", "elite": "精英", "boss": "界主",
    "boon": "诸天遗珍", "rest": "涅槃温泉", "treasure": "道痕矿脉",
}

NODE_REWARD = {"battle": 40, "elite": 90, "boss": 260, "boon": 30, "rest": 20, "treasure": 80}

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


def tier_of(tier: int) -> dict:
    return TIERS[max(0, min(len(TIERS) - 1, int(tier or 1) - 1))]


def celestial_of(now: float) -> dict:
    day = int(time.strftime("%Y%m%d", time.localtime(now)))
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
    base = NODE_REWARD.get(str(node.get("type")), 40) + layer * 8
    return max(1, int(base * tier["reward"] * float(celestial.get("token", 1) or 1)))


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
    pool = []
    for a in idx["abilities"].values():
        if a.get("bossOnly") or a.get("requiredMetaNode"):
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
                f"劫境道痕：{int(st.get('marks_total', 0)):,}\n"
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
        f"道痕：{int(st.get('marks', 0)):,}（未带出）｜累计 {int(st.get('marks_total', 0)):,}",
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
             f"回血 {stats['regen']:.1%}/层｜涅槃 {revive_txt}"]
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
    return "\n".join(lines)


def rank_rows(players: Sequence[Mapping], limit: int = 10) -> list[dict]:
    rows = []
    for p in players:
        ext = p.get("ext") or {}
        st = ext.get("endless") or {}
        if not isinstance(st, Mapping):
            continue
        tier = int(st.get("best_tier", 1) or 1)
        layer = int(st.get("best_layer", 0) or 0)
        marks = int(st.get("marks_total", 0) or 0)
        if layer <= 0 and marks <= 0:
            continue
        rows.append({"name": p.get("name") or str(p.get("uid", ""))[:8],
                     "tier": tier, "layer": layer, "marks": marks})
    rows.sort(key=lambda r: (-r["tier"], -r["layer"], -r["marks"]))
    return rows[:limit]
