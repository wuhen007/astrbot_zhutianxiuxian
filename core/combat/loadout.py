"""功法战斗装填（W1-2）：把玩家已学功法接到战斗引擎上。

原版语义（model/xiuxian.js 复活技能分支 + zd_battle 开场乘区）：
- 已学功法（ext["gongfa"]）在 item_index 中命中 `复活技能 == 1` 的条目 → 死亡时掷 pr
  （默认 1=必发）复活为 血量上限 × 恢复比例，每场一次，战报输出 msg2
- 条目上的 攻击加成/防御加成/生命加成 → 战斗开场三维乘区（1 + 加成）
- 其余功法仍是修炼效率类，不进战斗

数据源：data/item/技能组/复活技能.json（17 条，经 item_index 按名命中）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .engine import Fighter


def learned_battle_skills(doc: Any, item_lookup: Any) -> list[dict]:
    """已学功法中的战斗条目（复活技能 == 1）。item_lookup 兼容 dict 与 callable。"""
    get = item_lookup.get if hasattr(item_lookup, "get") else item_lookup
    out = []
    for name in (getattr(doc, "ext", {}).get("gongfa") or []):
        item = get(name)
        if item and int(item.get("复活技能", 0) or 0) == 1:
            out.append(dict(item))
    return out


def apply_start_bonuses(f: Fighter, battle_skills: list[dict]) -> Fighter:
    """开场三维乘区：攻/防/血 ×（1 + 对应加成之和）。"""
    atk_b = sum(float(s.get("攻击加成", 0) or 0) for s in battle_skills)
    def_b = sum(float(s.get("防御加成", 0) or 0) for s in battle_skills)
    hp_b = sum(float(s.get("生命加成", 0) or 0) for s in battle_skills)
    f.atk = max(1, int(f.atk * (1 + atk_b)))
    f.defense = max(1, int(f.defense * (1 + def_b)))
    f.hp_max = max(1, int(f.hp_max * (1 + hp_b)))
    f.hp = f.hp_max
    return f


def build_fighter(
    doc: Any, name: str, atk: int, defense: int, hp: int, bao: float,
    item_lookup: Mapping[str, Any],
) -> Fighter:
    """从玩家文档构建带功法的战斗单位。"""
    f = Fighter(name=name, atk=int(atk), defense=int(defense), hp=int(hp),
                hp_max=int(hp), bao=float(bao or 0.0))
    battle_skills = learned_battle_skills(doc, item_lookup)
    if battle_skills:
        f = apply_start_bonuses(f, battle_skills)
        revive = battle_skills[0]      # 一场一次；多本取第一本（原版同为单次复活）
        f.effects["revive"] = {
            "name": str(revive.get("name") or "复活技"),
            "ratio": min(1.0, max(0.05, float(revive.get("恢复比例", 0.7) or 0.7))),
            "pr": min(1.0, max(0.0, float(revive.get("pr", 1) or 1))),
            "msg": str(revive.get("msg2") or ""),
            "used": False,
        }
        f.tags["battle_skills"] = [str(s.get("name")) for s in battle_skills]
    return f
