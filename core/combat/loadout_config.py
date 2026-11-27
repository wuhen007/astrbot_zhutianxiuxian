"""战斗技能配置（对齐原版 model/combatSkillLoadout.js）。

玩家从已掌握技能里挑：攻击 ≤5、防御 ≤5、生机（恢复/回血/复活）1。
未配置时沿用全池自动装配（兼容旧档）；灵根自带技能始终自动生效，不占名额。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ATTACK_LIMIT = 5
DEFENSE_LIMIT = 5

TYPE_ALIASES = {
    "攻击": "攻击", "防御": "防御",
    "恢复": "生机", "回血": "生机", "复活": "生机", "生机": "生机",
}

POOL_OF = {"攻击": "atk", "防御": "def", "生机": "heal"}

EXT_KEY = "combat_skill_loadout"


def normalize_type(raw: str) -> str | None:
    return TYPE_ALIASES.get(str(raw or "").strip())


def state_of(doc: Any) -> dict[str, Any] | None:
    """返回配置；从未配置过返回 None（调用方据此判断走全池）。"""
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return None
    cfg = ext.get(EXT_KEY)
    if not isinstance(cfg, Mapping):
        return None
    return {
        "攻击": [str(x) for x in (cfg.get("攻击") or [])][:ATTACK_LIMIT],
        "防御": [str(x) for x in (cfg.get("防御") or [])][:DEFENSE_LIMIT],
        "生机": str(cfg.get("生机") or ""),
    }


def effective(doc: Any, pools: Mapping[str, Any], learned: set[str]) -> dict[str, Any]:
    """生效配置：未落档时按原版 ensureCombatSkillLoadout 自动填满（不写档，只读场景用）。"""
    cfg = state_of(doc)
    if cfg is not None:
        return cfg
    return {
        "攻击": options(doc, "攻击", pools, learned)[:ATTACK_LIMIT],
        "防御": options(doc, "防御", pools, learned)[:DEFENSE_LIMIT],
        "生机": (options(doc, "生机", pools, learned) or [""])[0],
    }


def ensure(doc: Any, pools: Mapping[str, Any], learned: set[str]) -> dict[str, Any]:
    cfg = state_of(doc)
    if cfg is None:
        cfg = effective(doc, pools, learned)
        doc.ext[EXT_KEY] = dict(cfg)
    return cfg


def options(doc: Any, type_: str, pools: Mapping[str, Any],
            learned: set[str] | None = None) -> list[str]:
    """可配置技能名：条目归属（熟练度归属/name）必须是已学功法。"""
    if learned is None:
        learned = set(getattr(doc, "ext", {}).get("gongfa") or [])
    pool = pools.get(POOL_OF.get(type_, "")) or []
    seen: list[str] = []
    for entry in pool:
        if not isinstance(entry, Mapping):
            continue
        owner = str(entry.get("熟练度归属") or entry.get("name") or "").strip()
        if owner and owner in learned and owner not in seen:
            seen.append(owner)
    return seen


def resolve(doc: Any, type_: str, selection: str, pools: Mapping[str, Any],
            learned: set[str]) -> tuple[bool, str, str]:
    """序号或名字 → 技能名。"""
    opts = options(doc, type_, pools, learned)
    if not opts:
        return False, f"你当前没有可配置的{type_}技能（需先学对应功法）。", ""
    raw = str(selection or "").strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if not 0 <= idx < len(opts):
            return False, f"{type_}技能序号无效，当前可选 1~{len(opts)}。", ""
        return True, "", opts[idx]
    if raw not in opts:
        return False, f"【{raw}】不是你已掌握的{type_}技能。", ""
    return True, "", raw


def equip(doc: Any, type_: str, name: str, pools: Mapping[str, Any],
          learned: set[str]) -> tuple[bool, str]:
    cfg = ensure(doc, pools, learned)
    if type_ == "生机":
        old = cfg["生机"]
        cfg["生机"] = name
        doc.ext[EXT_KEY] = dict(cfg)
        return True, f"生机技能已设为【{name}】" + (f"（替换【{old}】）" if old and old != name else "")
    slot, limit = ("攻击", ATTACK_LIMIT) if type_ == "攻击" else ("防御", DEFENSE_LIMIT)
    if name in cfg[slot]:
        return False, f"【{name}】已在{slot}技能栏。"
    if len(cfg[slot]) >= limit:
        return False, f"{slot}技能栏已满（{limit} 个），请先卸下一个。"
    cfg[slot].append(name)
    doc.ext[EXT_KEY] = dict(cfg)
    return True, f"已装备{slot}技能【{name}】（{len(cfg[slot])}/{limit}）"


def unequip(doc: Any, type_: str, name: str, pools: Mapping[str, Any],
            learned: set[str]) -> tuple[bool, str]:
    cfg = ensure(doc, pools, learned)
    if type_ == "生机":
        if cfg["生机"] != name:
            return False, f"【{name}】不在生机技能栏。"
        cfg["生机"] = ""
        doc.ext[EXT_KEY] = dict(cfg)
        return True, f"已卸下生机技能【{name}】"
    slot = "攻击" if type_ == "攻击" else "防御"
    if name not in cfg[slot]:
        return False, f"【{name}】不在{slot}技能栏。"
    cfg[slot].remove(name)
    doc.ext[EXT_KEY] = dict(cfg)
    return True, f"已卸下{slot}技能【{name}】（{len(cfg[slot])}/{ATTACK_LIMIT if slot == '攻击' else DEFENSE_LIMIT}）"


def panel_text(doc: Any, pools: Mapping[str, Any], learned: set[str]) -> str:
    cfg = effective(doc, pools, learned)
    lines = ["【战斗技能配置】"]
    for slot, limit in (("攻击", ATTACK_LIMIT), ("防御", DEFENSE_LIMIT)):
        lines.append(f"{slot}（{len(cfg[slot])}/{limit}）：" +
                     ("、".join(cfg[slot]) if cfg[slot] else "未装备"))
        avail = [n for n in options(doc, slot, pools, learned) if n not in cfg[slot]]
        if avail:
            lines.append("  可选：" + "、".join(avail[:12]) +
                         (f" 等 {len(avail)} 个" if len(avail) > 12 else ""))
    lines.append(f"生机（{'1' if cfg['生机'] else '0'}/1）：{cfg['生机'] or '未装备'}")
    lines.append("装备：#装备攻击技能 名称/序号｜#装备防御技能 …｜#装备生机技能 …")
    lines.append("卸下：#卸下攻击技能 名称｜#卸下防御技能 …｜#卸下生机技能 …")
    return "\n".join(lines)
