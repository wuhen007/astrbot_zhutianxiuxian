"""装备系统：五槽位穿戴 + 属性聚合（纯函数，无 IO）。

规则对应原版数据的两种加成语义：
- 数值 ≤ 1：按比例加成（如 atk 0.92 = 基础攻击 +92%）
- 数值 > 1：固定值加成
- bao：暴击率加成（恒为小数，聚合后封顶 1.0）
- 全属性：同时作用于攻击/防御/血量，语义同上
槽位取自原版 normalizeEquipment：武器 / 护具 / 法宝 / 帝兵 / 至宝。
装备名存于玩家文档 ext["equipment"] = {槽位: 物品名}，属性按名称查物品索引现算。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .player import PlayerDoc, realm_entry

SLOTS = ("武器", "护具", "法宝", "帝兵", "至宝")


SET_BONUS = {2: 0.15, 3: 0.35}   # 同套装 2 件 +15%、3 件齐 +35%（三维）


@dataclass
class Stats:
    atk: int
    defense: int
    hp: int
    bao: float
    set_lines: tuple[str, ...] = ()


def _split(value: Any) -> tuple[float, float]:
    """数值加成 → (固定值, 比例)。≤0 视为无加成。"""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if v <= 0:
        return 0.0, 0.0
    return (v, 0.0) if v > 1 else (0.0, v)


def slot_of(item: Mapping[str, Any] | None) -> str | None:
    """装备所属槽位；非装备或部位未知返回 None。"""
    if not isinstance(item, Mapping) or item.get("class") != "装备":
        return None
    t = item.get("type")
    return t if t in SLOTS else None


def wear(doc: PlayerDoc, item: Mapping[str, Any]) -> tuple[bool, str, str | None]:
    """穿戴装备。返回 (ok, msg, 换下的旧物品名)。"""
    slot = slot_of(item)
    if not slot:
        return False, "该物品不是可穿戴的装备。", None
    name = str(item.get("name", ""))
    cur = doc.ext.setdefault("equipment", {})
    old = cur.get(slot)
    if old == name:
        return False, f"「{name}」已在{slot}位上。", None
    cur[slot] = name
    msg = f"已将「{name}」装上{slot}位。"
    if old:
        msg += f"（原{slot}「{old}」已回到纳戒）"
    return True, msg, old


def unequip(doc: PlayerDoc, slot: str) -> tuple[bool, str, str | None]:
    """卸下指定槽位。返回 (ok, msg, 卸下的物品名)。"""
    if slot not in SLOTS:
        return False, f"部位只能是：{' / '.join(SLOTS)}。", None
    cur = doc.ext.setdefault("equipment", {})
    old = cur.pop(slot, None)
    if not old:
        return False, f"{slot}位本来就没有装备。", None
    return True, f"已卸下{slot}位的「{old}」，回到纳戒。", old


ENHANCE_MAX = 10
ENHANCE_BONUS_PER_LEVEL = 0.10   # 每级强化：该件装备的加成 +10%
ENHANCE_COST_BASE = 2000         # 强化费用 = 基数 × (当前等级 + 1)


def enhance_cost(current: int) -> int:
    return ENHANCE_COST_BASE * (current + 1)


def enhance_rate(current: int) -> float:
    """成功率：每级递减 7%，下限 35%。"""
    return max(0.35, 1.0 - 0.07 * current)


def aggregate(
    doc: PlayerDoc,
    level_table: list[dict],
    item_lookup: Callable[[str], Mapping[str, Any] | None],
    enhance: Mapping[str, int] | None = None,
    imperial: set[str] | None = None,
    physique_table: list[dict] | None = None,
) -> Stats:
    """基础属性（练气 + 炼体双轨，对齐原版四体系求和；秘境/仙古/花粉未开为 0）
    + 已装备加成（× 强化乘数；认主帝兵再 ×2）→ 总属性。"""
    entry = realm_entry(doc, level_table)
    base_atk = float(entry.get("基础攻击", 0) or 0)
    base_def = float(entry.get("基础防御", 0) or 0)
    base_hp = float(entry.get("基础血量", 0) or 0)
    bao = float(entry.get("基础暴击", 0) or 0)   # 原版：暴击率 = 练气 + 炼体 + 命格
    if physique_table:
        # 原版：四体系基础 = 练气 + 炼体 + 秘境 + 仙古 + 花粉×倍率；本移植后三轨未开放
        prow = physique_table[max(0, min(int(getattr(doc, "physique_index", 0) or 0), len(physique_table) - 1))]
        base_atk += float(prow.get("基础攻击", 0) or 0)
        base_def += float(prow.get("基础防御", 0) or 0)
        base_hp += float(prow.get("基础血量", 0) or 0)
        bao += float(prow.get("基础暴击", 0) or 0)

    enhance = enhance or {}
    tainted_slots = set((doc.ext.get("tainted") or {}).keys()) if isinstance(doc.ext.get("tainted"), dict) else set()
    flat = {"atk": 0.0, "def": 0.0, "hp": 0.0}
    ratio = {"atk": 0.0, "def": 0.0, "hp": 0.0}
    for slot, name in (doc.ext.get("equipment") or {}).items():
        item = item_lookup(name)
        if not item:
            continue
        # 天骄污损（W7-3）：比例属性 -20%，击杀来源天骄或 #修复污损 复原
        taint_mult = 0.8 if str(slot) in tainted_slots else 1.0
        mult = 1.0 + ENHANCE_BONUS_PER_LEVEL * min(
            max(int(enhance.get(slot, 0) or 0), 0), ENHANCE_MAX
        )
        if item.get("type") == "帝兵" and imperial and name in imperial:
            mult *= 2.0  # 认主帝兵：属性加成翻倍
        for key, acc in (("atk", "atk"), ("def", "def"), ("HP", "hp")):
            f, r = _split(item.get(key))
            flat[acc] += f * mult
            ratio[acc] += r * mult * taint_mult
        f, r = _split(item.get("全属性"))
        for acc in flat:
            flat[acc] += f * mult
            ratio[acc] += r * mult * taint_mult
        try:
            bao += float(item.get("bao") or 0)
        except (TypeError, ValueError):
            pass
        # 宝石镶嵌：ext["gems"]={槽位:[宝石名]}，宝石四维加成直加
        for gem_name in ((doc.ext.get("gems") or {}).get(slot) or []):
            gem = item_lookup(gem_name)
            if not gem or gem.get("class") != "宝石":
                continue
            flat["atk"] += max(0, float(gem.get("攻击加成") or 0))
            flat["def"] += max(0, float(gem.get("防御加成") or 0))
            flat["hp"] += max(0, float(gem.get("生命加成") or 0))
            try:
                bao += max(0.0, float(gem.get("暴击加成") or 0))
            except (TypeError, ValueError):
                pass

    # 套装特效：统计已穿装备的套装名，2 件/3 件档位给三维乘区
    set_count: dict[str, int] = {}
    for name in (doc.ext.get("equipment") or {}).values():
        e = item_lookup(name)
        if e and e.get("class") == "装备" and e.get("套装"):
            set_count[str(e["套装"])] = set_count.get(str(e["套装"]), 0) + 1
    set_mult = 1.0
    set_lines = []
    for sname, cnt in set_count.items():
        bonus = SET_BONUS.get(min(cnt, max(SET_BONUS)))
        if bonus:
            set_mult += bonus
            set_lines.append(f"{sname}×{cnt}（+{bonus:.0%} 三维）")

    # 仙宠：ext["pet"]={name, level}，加成 = 初始加成 + 每级增加×(level-1)（三维）
    pet_mult = 1.0
    pet = doc.ext.get("pet")
    if pet and pet.get("name"):
        pinfo = item_lookup(str(pet["name"]))
        if pinfo and pinfo.get("class") == "仙宠":
            try:
                lv_cap = int(pinfo.get("等级上限", 100) or 100)
                lv = min(max(int(pet.get("level", 1) or 1), 1), lv_cap)
                base_b = float(pinfo.get("初始加成") or 0)
                per_lv = float(pinfo.get("每级增加") or 0)
                pet_mult += max(0.0, base_b + per_lv * (lv - 1))
            except (TypeError, ValueError):
                pass

    # 血气打熬：ext["xueqi"] 为丹药累计的永久血上限加成（吃套装/仙宠乘区之前直加）
    try:
        xueqi_flat = max(0.0, float(doc.ext.get("xueqi", 0) or 0))
    except (TypeError, ValueError):
        xueqi_flat = 0.0
    flat["hp"] += xueqi_flat

    # 灵根四维（W7-4 觉醒）：攻击/防御/生命按比例、生命本源折算扁平气血
    lg_atk = lg_def = lg_hp = lg_flat = 0.0
    try:
        from . import linggen as _lg
        lg_atk, lg_def, lg_hp, lg_flat = _lg.stats_of(doc.ext.get("linggen"))
    except Exception:
        pass

    # 大道至宝（W7-5a）：永久全属性/暴击加成
    dt_all, dt_bao = 0.0, 0.0
    try:
        from . import other_shore_forge as _osf
        dt_all, dt_bao = _osf.treasure_bonus(_osf.ensure(doc))
    except Exception:
        pass

    # 诸天化身：装载化身时的三维比例加成（ext["zhutian"]["current"] 对应化身的 root）
    av_atk = av_def = av_hp = 0.0
    zt = doc.ext.get("zhutian")
    if isinstance(zt, dict) and zt.get("current"):
        av = (zt.get("avatars") or {}).get(str(zt["current"])) or {}
        root = av.get("root") or {}
        try:
            av_atk = max(0.0, float(root.get("atk", 0) or 0))
            av_def = max(0.0, float(root.get("def", 0) or 0))
            av_hp = max(0.0, float(root.get("hp", 0) or 0))
        except (TypeError, ValueError):
            pass

    flat["hp"] += lg_flat

    return Stats(
        atk=int((base_atk * (1 + ratio["atk"] + av_atk + lg_atk + dt_all) + flat["atk"]) * set_mult * pet_mult),
        defense=int((base_def * (1 + ratio["def"] + av_def + lg_def + dt_all) + flat["def"]) * set_mult * pet_mult),
        hp=int((base_hp * (1 + ratio["hp"] + av_hp + lg_hp + dt_all) + flat["hp"]) * set_mult * pet_mult),
        bao=min(bao + dt_bao, 1.0),
        set_lines=tuple(set_lines),
    )
