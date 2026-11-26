"""仙宠对战：宠物独立三维战斗（纯函数，无 IO）。

原版 Pokemon 模块只有"出战切换"（宠物按类型给主人加成），无宠物 PVP——本模块为自创玩法：
- 宠物战斗三维 = 图鉴 atk/def/HP × (1 + (等级-1)×0.1)，品级差保留（仙灵碾压仙胎）
- 对战为友情赛（无战损）；胜 +3 成长、平 +1、负 +0；每 9 点成长自动 +1 级（上限图鉴）
"""

from __future__ import annotations

import random
import math
import time
from copy import deepcopy
from datetime import datetime
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .battle import spar, Unit

LEVEL_SCALE = 0.10      # 每级战斗三维 +10%
EXP_PER_LEVEL = 9       # 每级所需成长值
GAIN_WIN, GAIN_DRAW = 3, 1

# 品级链（对齐原版）：等级上限 / 进阶所需口粮 / 品级觉醒暴击（自创技能体系）
GRADE_CHAIN = ("仙胎", "仙仔", "仙兽", "仙道", "仙灵")
GRADE_CAPS = {"仙胎": 20, "仙仔": 40, "仙兽": 60, "仙道": 80, "仙灵": 100}
GRADE_CRIT = {"仙胎": 0.0, "仙仔": 0.05, "仙兽": 0.10, "仙道": 0.20, "仙灵": 0.30}
ADVANCE_FOOD = {"仙胎": ("五果", 3), "仙仔": ("六斋", 3), "仙兽": ("七荤", 3), "仙道": ("八素", 3)}
ADVANCE_STONE = 100_000  # 进阶契约灵石（品级递增见 advance_cost）

# 随机天赋（进阶时觉醒）：效果作用在属性层，不改战斗引擎
# rarity: 普通(60%) / 稀有(30%) / 史诗(10%)；mult 三维乘区、bao 加值、exp_mult 成长速度
TALENTS = (
    {"id": "balanced", "name": "均衡成长", "rarity": "普通", "mult": 1.08, "bao": 0.0, "exp_mult": 1.0},
    {"id": "savage", "name": "蛮荒之力", "rarity": "稀有", "mult": 0.0, "atk": 1.20, "bao": 0.0, "exp_mult": 1.0},
    {"id": "rock", "name": "磐石之躯", "rarity": "稀有", "mult": 0.0, "defense": 1.25, "hp": 1.25, "bao": 0.0, "exp_mult": 1.0},
    {"id": "vital", "name": "不灭血脉", "rarity": "稀有", "mult": 0.0, "hp": 1.40, "bao": 0.0, "exp_mult": 1.0},
    {"id": "claw", "name": "天生锐爪", "rarity": "史诗", "mult": 0.0, "bao": 0.12, "exp_mult": 1.0},
    {"id": "koi", "name": "锦鲤附体", "rarity": "史诗", "mult": 1.0, "bao": 0.0, "exp_mult": 1.5},
)
TALENT_BY_NAME = {t["name"]: t for t in TALENTS}


def roll_talent(rng: random.Random) -> dict:
    """加权随机：普通 60 / 稀有 30 / 史诗 10。"""
    x = rng.random() * 100
    rarity = "普通" if x < 60 else "稀有" if x < 90 else "史诗"
    pool = [t for t in TALENTS if t["rarity"] == rarity]
    return rng.choice(pool)


def talent_of(pet: Mapping) -> dict | None:
    return TALENT_BY_NAME.get(str((pet or {}).get("talent") or ""))


@dataclass
class PetBattle:
    unit: Unit
    level: int
    cap: int
    exp: int


def build(
    pet: Mapping, item_lookup: Callable[[str], Mapping | None]
) -> PetBattle | None:
    """从宠物会话 {name, level, exp} 构建战斗单位（含品级觉醒暴击）。"""
    info = item_lookup(str(pet.get("name", "")))
    if not info and isinstance(pet.get("instance_data"), Mapping):
        info = pet["instance_data"]
    if not info or info.get("class") != "仙宠":
        return None
    try:
        grade = str(info.get("品级", "仙胎"))
        cap = GRADE_CAPS.get(grade, int(info.get("等级上限", 100) or 100))
        level = min(max(int(pet.get("level", 1) or 1), 1), cap)
        scale = 1.0 + LEVEL_SCALE * (level - 1)
        atk = float(info.get("atk") or 1) * scale
        defense = float(info.get("def") or 1) * scale
        hp = float(info.get("HP") or 1) * scale
        bao = GRADE_CRIT.get(grade, 0.0)
        talent = talent_of(pet)
        if talent:
            m = talent.get("mult") or 1.0
            atk *= m * float(talent.get("atk") or 1.0)
            defense *= m * float(talent.get("defense") or 1.0)
            hp *= m * float(talent.get("hp") or 1.0)
            bao += float(talent.get("bao") or 0.0)
        unit = Unit(
            str(info.get("name", "?")),
            max(1, int(atk)), max(1, int(defense)), max(1, int(hp)), bao,
        )
        return PetBattle(unit=unit, level=level, cap=cap, exp=int(pet.get("exp", 0) or 0))
    except (TypeError, ValueError):
        return None


def ability_bonus(pet: Mapping | None, kind: str) -> float:
    """原版 getPetAbilityBonus：本体能力、炼妖继承、独立附加能力相加。"""
    if not isinstance(pet, Mapping):
        return 0.0
    def value(raw: Any) -> float:
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    total = value(pet.get("加成")) if pet.get("type") == kind else 0.0
    inherited = pet.get("炼妖继承能力")
    if isinstance(inherited, Mapping) and inherited.get("type") == kind:
        total += value(inherited.get("加成"))
    extras = pet.get("附加能力")
    if isinstance(extras, list):
        for entry in extras:
            if isinstance(entry, Mapping) and entry.get("type") == kind:
                total += value(entry.get("成长值", entry.get("加成", 0)))
    return total


def advance_cost(current_grade: str) -> int:
    """进阶契约灵石：品级序号 × 10 万。"""
    try:
        idx = GRADE_CHAIN.index(current_grade)
    except ValueError:
        return 0
    return ADVANCE_STONE * (idx + 1)


def next_form(
    info: Mapping, pet_by_id: Mapping[int, Mapping]
) -> Mapping | None:
    """进阶形态：图鉴 id+1 且品级为下一档（对齐原版同系升级形态）。"""
    try:
        pid = int(info.get("id") or 0)
    except (TypeError, ValueError):
        return None
    nxt = pet_by_id.get(pid + 1)
    if not nxt or nxt.get("name") == info.get("name"):
        return None
    if nxt.get("品级") not in GRADE_CHAIN:
        return None
    cur_idx = GRADE_CHAIN.index(str(info.get("品级", "仙胎")))
    if GRADE_CHAIN.index(str(nxt.get("品级"))) != cur_idx + 1:
        return None
    return nxt


def gain_exp(pet: Mapping, amount: int, item_lookup: Callable[[str], Mapping | None]) -> tuple[dict, int]:
    """累计成长并自动升级（锦鲤附体：成长 +50%）。返回 (新宠物会话, 升级数)。"""
    info = item_lookup(str(pet.get("name", "")))
    try:
        cap = int((info or {}).get("等级上限", 100) or 100)
    except (TypeError, ValueError):
        cap = 100
    talent = talent_of(pet)
    if talent and talent.get("exp_mult"):
        amount = int(amount * float(talent["exp_mult"]))
    exp = int(pet.get("exp", 0) or 0) + max(0, amount)
    level = min(max(int(pet.get("level", 1) or 1), 1), cap)
    up = 0
    while exp >= EXP_PER_LEVEL and level < cap:
        exp -= EXP_PER_LEVEL
        level += 1
        up += 1
    if level >= cap:
        exp = 0
    out = dict(pet)
    out["exp"] = exp
    out["level"] = level
    return out, up


def duel(
    a: PetBattle, b: PetBattle, rng: random.Random
) -> tuple[int | None, list[str]]:
    """宠物对战：复用切磋引擎（无战损）。返回 (胜者索引/None, 战报)。"""
    return spar(a.unit, b.unit, rng)


# ---- 上游仙宠玩法：栖息地、工坊作息、守卫、偷菜与野外驯服 ----
# 这些规则与上面的自创宠物对战分开。它们接收/返回数据，不读写数据库。

HABITAT_QUALITY_CAPS = {"仙胎": 20, "仙仔": 40, "仙兽": 60, "仙道": 80, "仙灵": 100}
HABITAT_ENERGY = 100
PET_CARE_CYCLE = {"work": 14.0, "rest": 7.0, "play": 3.0}
PET_WORKSHOP_TYPES = {
    "灵田": ("修炼", "幸运"), "丹房": ("炼丹",), "器阁": ("炼器",),
    "符台": ("制符",), "矿脉": ("战斗",),
}
PET_WILD_NAMES = (
    "赤瞳灵狐", "青鳞幼蛟", "金翅大鹏雏", "九尾仙猫", "玄甲龙龟",
    "紫电雷貂", "冰晶雪猿", "噬金仙蚁", "幻影灵蝶", "三足金乌雏",
    "碧水麒麟崽", "幽冥玄虎", "天音仙鹤", "噬灵古藤", "炎阳火凤雏",
)
PET_WILD_TYPES = ("战斗", "修炼", "炼丹", "炼器", "幸运", "制符")
PET_WILD_QUALITIES = ("仙胎", "仙仔", "仙兽", "仙道", "仙灵")
PET_WILD_QUALITY_WEIGHTS = (35, 30, 20, 10, 5)
PET_WILD_TRAITS = (
    "勤勉", "懒惰", "强韧", "贪吃", "聪慧", "神速", "灵秀", "火灵",
    "金刚", "符心", "匠魂", "暴食",
)
PET_CAPTURE_TALISMANS = (("极品封灵符", 0.90), ("上品封灵符", 0.70), ("普通封灵符", 0.50))
PET_WILD_ENCOUNTER_CHANCE = 0.08
PET_WILD_ENCOUNTER_PERIOD_HOURS = 24.0
PET_WILD_ENCOUNTER_VALID_SECONDS = 30 * 60
SMALL_WORLD_STEAL_COOLDOWN_MS = 12 * 60 * 60 * 1000
SMALL_WORLD_STEAL_PROTECTION_MS = 6 * 60 * 60 * 1000
SMALL_WORLD_GUARD_ENERGY_COST = 10
_PET_GRADE_SCORE = {"仙胎": 1, "仙仔": 2, "仙兽": 3, "仙道": 4, "仙灵": 5}
_PET_TRAIT_WORK = {"勤勉": 1.3, "懒惰": 0.8, "神速": 1.25}
_PET_TRAIT_COST = {"强韧": 0.5, "暴食": 1.3}
_PET_TRAIT_WORKSHOP = {
    "灵秀": {"灵田": 1.4}, "火灵": {"丹房": 1.4}, "金刚": {"矿脉": 1.4},
    "符心": {"符台": 1.4}, "匠魂": {"器阁": 1.4},
}


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _pet_value(pet: Mapping, english: str, legacy: str, default=None):
    if legacy in pet:
        return pet[legacy]
    return pet.get(english, default)


def _legacy_pet_schema(pet: Mapping) -> bool:
    return any(key in pet for key in ("品级", "等级", "特性", "纳戒数据", "小世界状态"))


def _epoch_seconds(value: object) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if value is None or value == "":
        return None
    try:
        number = float(value)
        if math.isfinite(number):
            return number / 1000 if number > 100_000_000_000 else number
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(text, pattern).timestamp()
            except ValueError:
                continue
    return None


def normalize_habitat_pet(pet: Mapping) -> dict:
    """归一旧/新栖息地宠物存档，保留未知字段供旧档和扩展字段往返。"""
    out = deepcopy(dict(pet))
    legacy = _legacy_pet_schema(out)
    energy_key, max_key = ("精力", "最大精力") if legacy else ("energy", "max_energy")
    workshop_key = "工坊" if legacy else "workshop"
    traits_key = "特性" if legacy else "traits"
    exhausted_key = "累倒" if legacy else "exhausted"
    counter_key = "累倒_counter" if legacy else "exhausted_counter"
    guard_key = "守卫" if legacy else "guard"
    cycle_key = "作息进度" if legacy else "cycle"
    max_energy = max(1.0, _number(out.get(max_key), HABITAT_ENERGY) or HABITAT_ENERGY)
    energy = max(0.0, min(max_energy, _number(out.get(energy_key), max_energy)))
    workshop = out.get(workshop_key)
    out[energy_key] = energy
    out[max_key] = max_energy
    out[workshop_key] = None if workshop == "兽栏" else workshop
    out[traits_key] = list(out.get(traits_key) or []) if isinstance(out.get(traits_key), (list, tuple)) else []
    out[exhausted_key] = out.get(exhausted_key) is True
    out[counter_key] = max(0, int(_number(out.get(counter_key), 0)))
    out[guard_key] = out.get(guard_key) is True
    out[cycle_key] = _number(out.get(cycle_key), 0.0)
    return out


def create_habitat_pet_data(inventory_pet: Mapping, settled_at=None) -> dict:
    """把纳戒宠物做成栖息地实例，并保留完整快照供召回还原。"""
    legacy = _legacy_pet_schema(inventory_pet)
    snapshot = deepcopy(dict(inventory_pet))
    quantity_key = "数量" if legacy else "quantity"
    lock_key = "islockd" if legacy else "locked"
    snapshot[quantity_key] = 1
    snapshot[lock_key] = int(_number(snapshot.get(lock_key), 0))
    state_key = "小世界状态" if legacy else "small_world_state"
    small_state = snapshot.pop(state_key, {})
    if not isinstance(small_state, Mapping):
        small_state = {}
    energy_key, max_key = ("精力", "最大精力") if legacy else ("energy", "max_energy")
    max_energy = max(1.0, _number(small_state.get(max_key), HABITAT_ENERGY) or HABITAT_ENERGY)
    energy = max(0.0, min(max_energy, _number(small_state.get(energy_key), max_energy)))
    if legacy:
        return {
            "name": inventory_pet.get("name"), "type": inventory_pet.get("type"),
            "品级": inventory_pet.get("品级", "仙胎"),
            "等级": inventory_pet.get("等级", 1), "等级上限": inventory_pet.get("等级上限"),
            "精力": energy, "最大精力": max_energy, "工坊": None,
            "特性": list(inventory_pet.get("特性") or []),
            "累倒": small_state.get("累倒") is True,
            "累倒_counter": max(0, int(_number(small_state.get("累倒_counter"), 0))),
            "守卫": False, "安置时间": settled_at, "产出累积": {}, "纳戒数据": snapshot,
        }
    return {
        "name": inventory_pet.get("name"), "type": inventory_pet.get("type"),
        "quality": inventory_pet.get("quality", "仙胎"),
        "level": inventory_pet.get("level", 1), "max_level": inventory_pet.get("max_level"),
        "energy": energy, "max_energy": max_energy, "workshop": None,
        "traits": list(inventory_pet.get("traits") or []),
        "exhausted": small_state.get("exhausted") is True,
        "exhausted_counter": max(0, int(_number(small_state.get("exhausted_counter"), 0))),
        "guard": False, "settled_at": settled_at, "output_accumulated": {},
        "inventory_snapshot": snapshot,
    }


def restore_habitat_pet_data(habitat_pet: Mapping, base_pets=()) -> dict | None:
    """从栖息地实例恢复完整纳戒宠物；旧档无快照时回退到基础图鉴。"""
    legacy = _legacy_pet_schema(habitat_pet)
    snapshot_key = "纳戒数据" if "纳戒数据" in habitat_pet else "inventory_snapshot"
    snapshot = habitat_pet.get(snapshot_key)
    base = next((item for item in (base_pets or ())
                 if isinstance(item, Mapping) and item.get("name") == habitat_pet.get("name")), None)
    template = deepcopy(dict(snapshot if isinstance(snapshot, Mapping) else base or {}))
    if not template:
        return None
    legacy = legacy or _legacy_pet_schema(template)
    grade = _pet_value(habitat_pet, "quality", "品级", _pet_value(template, "quality", "品级", "仙胎"))
    level = max(1, int(_number(_pet_value(habitat_pet, "level", "等级", _pet_value(template, "level", "等级", 1)), 1)))
    traits = _pet_value(habitat_pet, "traits", "特性", _pet_value(template, "traits", "特性", []))
    traits = list(traits) if isinstance(traits, (list, tuple)) else []
    max_energy = max(1.0, _number(_pet_value(habitat_pet, "max_energy", "最大精力", HABITAT_ENERGY), HABITAT_ENERGY))
    energy = max(0.0, min(max_energy, _number(_pet_value(habitat_pet, "energy", "精力", max_energy), max_energy)))
    cap_key = "等级上限" if legacy else "max_level"
    cap = max(int(_number(template.get(cap_key), 0)), HABITAT_QUALITY_CAPS.get(str(grade), 20))
    if legacy:
        template.update({
            "name": habitat_pet.get("name"), "class": "仙宠",
            "type": _pet_value(habitat_pet, "type", "类型", template.get("type")),
            "品级": grade, "等级": level, "等级上限": cap, "特性": traits,
            "数量": 1, "islockd": int(_number(template.get("islockd"), 0)),
            "小世界状态": {
                "精力": energy, "最大精力": max_energy,
                "累倒": _pet_value(habitat_pet, "exhausted", "累倒", False) is True,
                "累倒_counter": max(0, int(_number(_pet_value(habitat_pet, "exhausted_counter", "累倒_counter", 0), 0))),
            },
        })
        if not isinstance(snapshot, Mapping):
            template["加成"] = level * _number(template.get("每级增加"), 0.001)
    else:
        template.update({
            "name": habitat_pet.get("name"), "class": "仙宠",
            "type": habitat_pet.get("type", template.get("type")),
            "quality": grade, "level": level, "max_level": cap, "traits": traits,
            "quantity": 1, "locked": int(_number(template.get("locked"), 0)),
            "small_world_state": {
                "energy": energy, "max_energy": max_energy,
                "exhausted": habitat_pet.get("exhausted") is True,
                "exhausted_counter": max(0, int(_number(habitat_pet.get("exhausted_counter"), 0))),
            },
        })
        if not isinstance(snapshot, Mapping):
            template["bonus"] = level * _number(template.get("per_level"), 0.001)
    return template


def same_pet_variant(left: Mapping, right: Mapping) -> bool:
    """完整仙宠实例比较，数量不参与比较，特性/绑定等差异保留。"""
    a, b = deepcopy(dict(left)), deepcopy(dict(right))
    for key in ("数量", "quantity"):
        a.pop(key, None)
        b.pop(key, None)
    return a == b


def add_inventory_pet_variant(inventory_pets, pet: Mapping) -> tuple[list[dict], bool]:
    """加回/奖励一只完整宠物；仅完全相同的实例合并数量。"""
    items = deepcopy(list(inventory_pets or []))
    if not pet or not pet.get("name"):
        return items, False
    legacy = _legacy_pet_schema(pet)
    quantity_key = "数量" if legacy else "quantity"
    lock_key = "islockd" if legacy else "locked"
    incoming = deepcopy(dict(pet))
    incoming[quantity_key] = 1
    incoming[lock_key] = int(_number(incoming.get(lock_key), 0))
    for existing in items:
        if isinstance(existing, dict) and same_pet_variant(existing, incoming):
            existing[quantity_key] = max(0, int(_number(existing.get(quantity_key), 0))) + 1
            return items, True
    items.append(incoming)
    return items, False


def remove_inventory_pet_at(inventory_pets, pet_index: int) -> tuple[list, dict | None]:
    """从仙宠列表取出一只，数量大于一时只扣一只。"""
    items = deepcopy(list(inventory_pets or []))
    if not isinstance(pet_index, int) or pet_index < 0 or pet_index >= len(items):
        return items, None
    pet = items[pet_index]
    if not isinstance(pet, Mapping):
        return items, None
    removed = deepcopy(dict(pet))
    legacy = _legacy_pet_schema(removed)
    quantity_key = "数量" if legacy else "quantity"
    quantity = max(1, int(_number(removed.get(quantity_key), 1)))
    removed[quantity_key] = 1
    if quantity > 1:
        items[pet_index][quantity_key] = quantity - 1
    else:
        items.pop(pet_index)
    return items, removed


def _find_inventory_pet_index(inventory_pets, selector, code_offset: int = 1001) -> int:
    query = str(selector or "").strip()
    if query.isdigit() and int(query) >= code_offset:
        index = int(query) - code_offset
        return index if 0 <= index < len(inventory_pets) else -1
    return next((i for i, pet in enumerate(inventory_pets)
                 if isinstance(pet, Mapping) and pet.get("name") == query), -1)


def find_habitat_pet_index(habitat, selector, code_offset: int = 1001) -> int:
    pets = list(habitat or [])
    return _find_inventory_pet_index(pets, selector, code_offset)


def transfer_inventory_pet_to_habitat(
    inventory_pets, habitat, selector, settled_at=None, max_slots: int | None = None
) -> tuple[bool, str, list, list]:
    """纯逻辑安置：同一只只在纳戒或栖息地出现一次，调用方负责原子落盘。"""
    items, residents = deepcopy(list(inventory_pets or [])), deepcopy(list(habitat or []))
    if max_slots is not None and len(residents) >= max(0, int(max_slots)):
        return False, "栖息地已满。", items, residents
    index = _find_inventory_pet_index(items, selector)
    if index < 0:
        return False, f"纳戒中找不到仙宠【{str(selector or '').strip()}】。", items, residents
    source = items[index]
    pet_data = create_habitat_pet_data(source, settled_at)
    items, removed = remove_inventory_pet_at(items, index)
    if removed is None:
        return False, "仙宠数据不完整。", deepcopy(list(inventory_pets or [])), deepcopy(list(habitat or []))
    residents.append(pet_data)
    return True, f"{pet_data.get('name')}已安置。", items, residents


def restore_habitat_pet_to_inventory(
    inventory_pets, habitat, selector, base_pets=()
) -> tuple[bool, str, list, list]:
    """纯逻辑召回：恢复快照后移出栖息地，失败时两边原样返回。"""
    items, residents = deepcopy(list(inventory_pets or [])), deepcopy(list(habitat or []))
    index = find_habitat_pet_index(residents, selector)
    if index < 0:
        return False, f"栖息地中找不到仙宠【{str(selector or '').strip()}】。", items, residents
    restored = restore_habitat_pet_data(residents[index], base_pets)
    if restored is None:
        return False, f"基础仙宠表中找不到【{residents[index].get('name')}】。", items, residents
    items, _ = add_inventory_pet_variant(items, restored)
    residents.pop(index)
    return True, f"{restored.get('name')}已从栖息地召回。", items, residents


def pet_energy_period(energy, max_energy, hours, hourly_cost) -> dict[str, float | bool]:
    """工作扣精力/栖息地恢复精力，含高低精力对工作效率的分段折减。"""
    maximum = max(1.0, _number(max_energy, HABITAT_ENERGY) or HABITAT_ENERGY)
    start = max(0.0, min(maximum, _number(energy, maximum)))
    elapsed, cost = max(0.0, _number(hours)), _number(hourly_cost)
    if cost < 0:
        return {"start": start, "end": min(maximum, start - cost * elapsed), "active": 0.0, "weighted": 0.0, "exhausted": False}
    if cost == 0:
        efficiency = 1.0 if start >= 30 else 0.6 if start >= 10 else 0.2 if start > 0 else 0.0
        return {"start": start, "end": start, "active": elapsed if start > 0 else 0.0,
                "weighted": elapsed * efficiency, "exhausted": False}
    active = min(elapsed, start / cost)
    end = max(0.0, start - cost * active)
    above = lambda threshold: max(0.0, min(active, (start - threshold) / cost))
    high = above(30)
    medium = max(0.0, above(10) - high)
    low = max(0.0, active - high - medium)
    return {"start": start, "end": end, "active": active,
            "weighted": high + medium * 0.6 + low * 0.2, "exhausted": end <= 0}


def pet_care_period(energy, max_energy, hours, hourly_cost, cycle_progress=0) -> dict[str, float | int]:
    """按 14 小时工作、7 小时休息、3 小时玩耍推进宠物作息周期。"""
    work, rest, play = PET_CARE_CYCLE["work"], PET_CARE_CYCLE["rest"], PET_CARE_CYCLE["play"]
    cycle_hours = work + rest + play
    remaining = max(0.0, _number(hours))
    maximum = max(1.0, _number(max_energy, HABITAT_ENERGY) or HABITAT_ENERGY)
    start = max(0.0, min(maximum, _number(energy, maximum)))
    progress = _number(cycle_progress) % cycle_hours
    current, active, weighted, rest_hours, play_hours, meals = start, 0.0, 0.0, 0.0, 0.0, 0
    while remaining > 1e-9:
        if progress < work:
            phase, phase_end = "work", work
        elif progress < work + rest:
            phase, phase_end = "rest", work + rest
        else:
            phase, phase_end = "play", cycle_hours
        phase_hours = min(remaining, phase_end - progress)
        if phase == "work":
            state = pet_energy_period(current, maximum, phase_hours, hourly_cost)
            current = state["end"]
            active += state["active"]
            weighted += state["weighted"]
        elif phase == "rest":
            current = pet_energy_period(current, maximum, phase_hours, -8)["end"]
            rest_hours += phase_hours
        else:
            play_hours += phase_hours
        remaining -= phase_hours
        progress += phase_hours
        if progress >= cycle_hours - 1e-9:
            progress = 0.0
            meals += 1
    return {"start": start, "end": current, "active": active, "weighted": weighted,
            "rest": rest_hours, "play": play_hours, "meals": meals, "cycle": progress}


def pet_work_efficiency(pet: Mapping, workshop: str) -> float:
    """按类型适配与特性计算工坊效率；不适配工坊按原版减半。"""
    pet_type = _pet_value(pet, "type", "type", "")
    traits = _pet_value(pet, "traits", "特性", [])
    efficiency = 1.0 if pet_type in PET_WORKSHOP_TYPES.get(workshop, ()) else 0.5
    for trait in traits if isinstance(traits, (list, tuple)) else ():
        efficiency *= _PET_TRAIT_WORK.get(trait, 1.0)
        efficiency *= _PET_TRAIT_WORKSHOP.get(trait, {}).get(workshop, 1.0)
    return efficiency


def pet_work_energy_cost(pet: Mapping) -> float:
    """工坊基础每小时耗 4 点精力，再乘强韧/暴食特性。"""
    traits = _pet_value(pet, "traits", "特性", [])
    cost = 4.0
    for trait in traits if isinstance(traits, (list, tuple)) else ():
        cost *= _PET_TRAIT_COST.get(trait, 1.0)
    return cost


def normalize_epoch_milliseconds(value) -> float:
    timestamp = _epoch_seconds(value)
    if timestamp is None:
        return 0.0
    return timestamp * 1000


def get_steal_cooldown_remaining(last_steal_time, now=None) -> float:
    now_ms = normalize_epoch_milliseconds(now) if now is not None else time.time() * 1000
    last_ms = normalize_epoch_milliseconds(last_steal_time)
    return max(0.0, last_ms + SMALL_WORLD_STEAL_COOLDOWN_MS - now_ms)


def is_world_steal_protected(last_stolen_time, now=None) -> bool:
    now_ms = normalize_epoch_milliseconds(now) if now is not None else time.time() * 1000
    last_ms = normalize_epoch_milliseconds(last_stolen_time)
    return last_ms > 0 and last_ms + SMALL_WORLD_STEAL_PROTECTION_MS > now_ms


def calculate_crop_growth_state(crop: Mapping, seed_config: Mapping, world: Mapping, now=None) -> dict:
    """原版小世界作物成熟计算，支持旧中文字段及当前英文世界档。"""
    requirements = seed_config.get("requirements") or {}
    attributes = world.get("attributes") or world.get("attrs") or {}
    required_aura = _number(requirements.get("灵气浓度", requirements.get("aura", 1000)), 1000) or 1000
    world_aura = _number(attributes.get("灵气浓度", attributes.get("aura", 0)))
    required_seconds = required_aura / 1000 * 4 * 60 * 60
    time_flow = str(attributes.get("时间流速", attributes.get("time_flow", "1:1")))
    try:
        source, target = (float(part) for part in time_flow.split(":", 1))
        ratio = target / source if source > 0 and target > 0 else 1.0
    except (TypeError, ValueError):
        ratio = 1.0
    multiplier = _number(crop.get("记忆生长倍率", crop.get("memory_growth_multiplier", 1)), 1)
    if multiplier not in (1.5, 2.0, 3.0):
        multiplier = 1.0
    start_value = crop.get("种植时间", crop.get("阶段开始时间", crop.get("planted_at")))
    start_ms = normalize_epoch_milliseconds(start_value) if start_value is not None else 0.0
    now_ms = normalize_epoch_milliseconds(now) if now is not None else time.time() * 1000
    elapsed_ms = now_ms - start_ms
    growth_rate = world_aura / required_aura * multiplier if required_aura > 0 else 0.0
    valid = start_value is not None and elapsed_ms >= 0 and growth_rate > 0
    elapsed_seconds = elapsed_ms / 1000 if valid else 0.0
    total_growth = elapsed_seconds * ratio * growth_rate + _number(crop.get("时间加成", crop.get("time_bonus", 0))) if valid else 0.0
    remaining = max(0.0, required_seconds - total_growth)
    return {"valid": valid, "elapsed_seconds": elapsed_seconds, "time_ratio": ratio,
            "growth_rate": growth_rate, "required_seconds": required_seconds,
            "total_growth_seconds": total_growth, "remaining_seconds": remaining,
            "is_mature": valid and total_growth >= required_seconds}


def is_crop_stealable(crop: Mapping, seed_config: Mapping, world: Mapping, now=None) -> bool:
    state = calculate_crop_growth_state(crop, seed_config, world, now)
    records = crop.get("偷菜记录", crop.get("steal_records", []))
    return state["is_mature"] and not (isinstance(records, list) and records)


def record_crop_steal(crop: Mapping, thief_id, now=None) -> dict:
    out = deepcopy(dict(crop))
    legacy = "偷菜记录" in out or "种植时间" in out
    key = "偷菜记录" if legacy else "steal_records"
    records = out.get(key)
    if not isinstance(records, list):
        records = []
    else:
        records = deepcopy(records)
    timestamp = now if now is not None else time.time() * 1000
    records.append({"偷取者": str(thief_id), "时间": timestamp} if legacy
                   else {"thief": str(thief_id), "time": timestamp})
    out[key] = records
    return out


def calculate_guard_intercept_chance(pet: Mapping) -> float:
    """原版守卫宠拦截率，受品级、等级、类型、特性、当前精力影响。"""
    if not pet or _pet_value(pet, "exhausted", "累倒", False) is True:
        return 0.0
    max_energy = max(1.0, _number(_pet_value(pet, "max_energy", "最大精力", HABITAT_ENERGY), HABITAT_ENERGY) or HABITAT_ENERGY)
    energy = max(0.0, min(max_energy, _number(_pet_value(pet, "energy", "精力", max_energy), max_energy)))
    if energy <= 0:
        return 0.0
    quality = str(_pet_value(pet, "quality", "品级", "仙胎"))
    level = max(1, min(100, int(_number(_pet_value(pet, "level", "等级", 1), 1))))
    chance = 0.15 + _PET_GRADE_SCORE.get(quality, 1) * 0.06 + level * 0.002
    if pet.get("type") == "战斗":
        chance += 0.12
    traits = _pet_value(pet, "traits", "特性", [])
    traits = set(traits) if isinstance(traits, (list, tuple)) else set()
    chance += 0.05 if "强韧" in traits else 0.0
    chance += 0.04 if "聪慧" in traits else 0.0
    chance += 0.04 if "神速" in traits else 0.0
    chance += 0.03 if "勤勉" in traits else 0.0
    chance -= 0.08 if "懒惰" in traits else 0.0
    return max(0.05, min(0.8, chance * (0.4 + 0.6 * energy / max_energy)))


def consume_guard_energy(pet: Mapping, cost: float = SMALL_WORLD_GUARD_ENERGY_COST) -> dict:
    out = deepcopy(dict(pet))
    legacy = _legacy_pet_schema(out)
    energy_key, max_key, guard_key = (("精力", "最大精力", "守卫") if legacy
                                     else ("energy", "max_energy", "guard"))
    maximum = max(1.0, _number(out.get(max_key), HABITAT_ENERGY) or HABITAT_ENERGY)
    energy = max(0.0, min(maximum, _number(out.get(energy_key), maximum)))
    out[energy_key] = max(0.0, energy - max(0.0, _number(cost)))
    if out[energy_key] <= 0:
        out[guard_key] = False
    return out


def wild_encounter_chance(elapsed_hours, period_chance=PET_WILD_ENCOUNTER_CHANCE,
                          period_hours=PET_WILD_ENCOUNTER_PERIOD_HOURS) -> float:
    hours = max(0.0, _number(elapsed_hours))
    chance = max(0.0, min(1.0, _number(period_chance)))
    period = max(1e-12, _number(period_hours, PET_WILD_ENCOUNTER_PERIOD_HOURS))
    return 1.0 - (1.0 - chance) ** (hours / period)


def generate_wild_pet(rng: random.Random) -> dict:
    roll = rng.random() * sum(PET_WILD_QUALITY_WEIGHTS)
    quality_index = 0
    for index, weight in enumerate(PET_WILD_QUALITY_WEIGHTS):
        roll -= weight
        if roll <= 0:
            quality_index = index
            break
    traits = list(rng.sample(PET_WILD_TRAITS, 2 if rng.random() < 0.3 else 1))
    return {"name": rng.choice(PET_WILD_NAMES), "type": rng.choice(PET_WILD_TYPES),
            "quality": PET_WILD_QUALITIES[quality_index], "traits": traits, "hp": 100}


def maybe_wild_encounter(world: Mapping, elapsed_hours, rng: random.Random, now=None) -> tuple[dict, dict | None]:
    """收获结算时创建限时遭遇；兼容旧 `驯服状态` 与 ext 小世界 `tame`。"""
    out = deepcopy(dict(world))
    current_time = _epoch_seconds(now) if now is not None else time.time()
    current_time = current_time or 0.0
    current = out.get("tame") if "tame" in out else out.get("驯服状态")
    if isinstance(current, Mapping):
        expires = _epoch_seconds(current.get("expires"))
        active = current.get("active", True)
        if active and expires is not None and expires > current_time:
            return out, None
    if rng.random() >= wild_encounter_chance(elapsed_hours):
        return out, None
    beast = generate_wild_pet(rng)
    if "tame" in out or "pets" in out:
        encounter = {"beast": beast, "expires": current_time + PET_WILD_ENCOUNTER_VALID_SECONDS}
        out["tame"] = encounter
    else:
        encounter = {
            "active": True, "beast_name": beast["name"], "beast_type": beast["type"],
            "beast_quality": beast["quality"], "beast_hp": beast["hp"],
            "beast_traits": list(beast["traits"]),
            "expires": current_time + PET_WILD_ENCOUNTER_VALID_SECONDS,
        }
        out["驯服状态"] = encounter
    return out, deepcopy(beast)


def pick_capture_talisman(inventory: Mapping[str, int]) -> tuple[str, float] | None:
    for name, rate in PET_CAPTURE_TALISMANS:
        if int(_number(inventory.get(name), 0)) > 0:
            return name, rate
    return None


def create_wild_pet_reward(beast: Mapping, item_lookup=None, now_ms: int = 0) -> dict:
    """构造原版驯服奖励仙宠实例；调用方将其加入纳戒并提交同一事务。"""
    name = str(beast.get("name", beast.get("beast_name", "野生仙兽")))
    base = item_lookup(name) if callable(item_lookup) else (item_lookup or {}).get(name)
    quality = str(beast.get("quality", beast.get("beast_quality", "仙胎")))
    traits = beast.get("traits", beast.get("beast_traits", []))
    traits = list(traits) if isinstance(traits, (list, tuple)) else []
    return {
        "id": (base or {}).get("id") or (2900 + int(now_ms) % 100000),
        "name": name, "class": "仙宠", "type": beast.get("type", beast.get("beast_type", "战斗")),
        "atk": 1, "def": 1, "HP": 1, "初始加成": 0.005, "每级增加": 0.001,
        "加成": 0.005, "灵魂绑定": 0, "品级": quality, "等级": 1,
        "等级上限": HABITAT_QUALITY_CAPS.get(quality, 20), "获取难度": 10,
        "出售价": 100000, "特性": traits, "数量": 1, "islockd": 0,
    }


def capture_wild_pet(encounter: Mapping | None, talisman: str, rng: random.Random,
                     now=None, item_lookup=None, now_ms: int = 0) -> dict:
    """尝试驯服遭遇；返回消费状态、成功率与完整奖励，不修改存档/背包。"""
    current_time = _epoch_seconds(now) if now is not None else time.time()
    current_time = current_time or 0.0
    if not isinstance(encounter, Mapping):
        return {"attempted": False, "consumed": False, "clear_encounter": False,
                "success": False, "success_rate": 0.0, "reward": None, "message": "当前没有可驯服的野生仙兽。"}
    beast = encounter.get("beast") if isinstance(encounter.get("beast"), Mapping) else encounter
    expires = _epoch_seconds(encounter.get("expires"))
    if encounter.get("active") is False or (expires is not None and expires <= current_time):
        return {"attempted": False, "consumed": False, "clear_encounter": True,
                "success": False, "success_rate": 0.0, "reward": None, "message": "野生仙兽已经离开。"}
    base_rate = dict(PET_CAPTURE_TALISMANS).get(talisman)
    if base_rate is None:
        return {"attempted": False, "consumed": False, "clear_encounter": False,
                "success": False, "success_rate": 0.0, "reward": None,
                "message": "需要封灵符：普通(50%)/上品(70%)/极品(90%)。"}
    hp = _number(beast.get("hp", encounter.get("beast_hp", 100)), 100)
    success_rate = base_rate + (1.0 - hp / 100.0) / 2.0
    name = beast.get("name", encounter.get("beast_name", "野生仙兽"))
    success = rng.random() < success_rate
    reward = create_wild_pet_reward(beast if "name" in beast else encounter,
                                    item_lookup, now_ms) if success else None
    message = (f"驯服成功：{name}已收入纳戒。" if success
               else f"{name}挣脱封灵符，逃入山林深处；{talisman}已被消耗。")
    return {"attempted": True, "consumed": True, "clear_encounter": True,
            "success": success, "success_rate": success_rate, "reward": reward, "message": message}


def wild_reward_session(reward: Mapping) -> dict:
    """Map a captured inventory-style pet to the existing single-pet ext session."""
    instance = deepcopy(dict(reward))
    return {
        "name": instance.get("name"), "level": max(1, int(_number(instance.get("等级"), 1))),
        "exp": 0, "quality": instance.get("品级", "仙胎"),
        "type": instance.get("type", "战斗"), "traits": list(instance.get("特性") or []),
        "instance_data": instance,
    }


def habitat_pet_session(habitat_pet: Mapping, base_pets=()) -> dict:
    """Move a habitat resident into the contract session without losing its snapshot."""
    instance = restore_habitat_pet_data(habitat_pet, base_pets)
    legacy = _legacy_pet_schema(instance or {})
    level = _number(_pet_value(habitat_pet, "level", "等级", 1), 1)
    if instance is None:
        instance = {"name": habitat_pet.get("name"), "type": habitat_pet.get("type"),
                    "品级": habitat_pet.get("quality", "仙胎"), "等级": max(1, int(level)),
                    "特性": list(habitat_pet.get("traits") or [])}
        legacy = True
    name = habitat_pet.get("name")
    quality = _pet_value(habitat_pet, "quality", "品级", instance.get("品级", instance.get("quality", "仙胎")))
    pet_type = habitat_pet.get("type", instance.get("type", "战斗"))
    traits = _pet_value(habitat_pet, "traits", "特性", instance.get("特性", instance.get("traits", [])))
    energy = _number(_pet_value(habitat_pet, "energy", "精力", HABITAT_ENERGY), HABITAT_ENERGY)
    max_energy = max(1.0, _number(_pet_value(habitat_pet, "max_energy", "最大精力", HABITAT_ENERGY), HABITAT_ENERGY))
    exhausted = _pet_value(habitat_pet, "exhausted", "累倒", False) is True
    counter = max(0, int(_number(_pet_value(habitat_pet, "exhausted_counter", "累倒_counter", 0))))
    if legacy:
        instance["小世界状态"] = {"精力": energy, "最大精力": max_energy,
                                  "累倒": exhausted, "累倒_counter": counter}
    else:
        instance["small_world_state"] = {"energy": energy, "max_energy": max_energy,
                                          "exhausted": exhausted, "exhausted_counter": counter}
    return {"name": name, "level": max(1, int(level)), "exp": int(_number(instance.get("exp"), 0)),
            "quality": quality, "type": pet_type, "traits": list(traits or []),
            "instance_data": instance}

def capture_wild_encounter(world: Mapping, talisman: str, rng: random.Random,
                           now=None, item_lookup=None, now_ms: int = 0) -> tuple[dict, dict]:
    """结算遭遇并清除成功/失败/过期状态；奖励仍由调用方原子写入背包。"""
    out = deepcopy(dict(world))
    encounter = out.get("tame") if "tame" in out else out.get("驯服状态")
    if isinstance(encounter, Mapping) and "beast" not in encounter and encounter.get("active"):
        encounter = {
            "active": True,
            "beast": {"name": encounter.get("beast_name"), "type": encounter.get("beast_type"),
                      "quality": encounter.get("beast_quality"), "hp": encounter.get("beast_hp", 100),
                      "traits": encounter.get("beast_traits", [])},
            "expires": encounter.get("expires"),
        }
    result = capture_wild_pet(encounter, talisman, rng, now, item_lookup, now_ms)
    if result["clear_encounter"]:
        if "tame" in out or "pets" in out:
            out["tame"] = None
        elif isinstance(out.get("驯服状态"), Mapping):
            out["驯服状态"] = {**out["驯服状态"], "active": False}
    return out, result
