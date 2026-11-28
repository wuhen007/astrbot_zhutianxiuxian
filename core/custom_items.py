from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

REGISTRY_KEY = "custom_equipment"
MAX_NAME_LENGTH = 8
MAX_PERCENT_STAT = 499.0
EQUIPMENT_TYPES = frozenset({"武器", "护具", "法宝", "帝兵", "至宝"})
PRIVATE_MARKERS = frozenset(
    {"绑定者", "参悟仿制", "private_owner_uid", "owner_uid", "owner_id", "private_item"}
)


def is_private_item(item: Mapping[str, Any] | None) -> bool:
    """Bound or explicitly private equipment must stay owner-scoped."""
    if not isinstance(item, Mapping):
        return False
    return (any(key in item for key in PRIVATE_MARKERS)
            or str(item.get("品阶") or "") == "参悟仿制")


def normalize_registry(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate a legacy custom.json list while retaining full item stat snapshots."""
    if not isinstance(raw, list):
        return [], ["custom.json: 根值不是数组，未导入动态装备"]
    out: list[dict[str, Any]] = []
    names: set[str] = set()
    warnings: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            warnings.append(f"custom.json[{index}]: 忽略非对象条目")
            continue
        name = str(item.get("name") or "").strip()
        if not name or item.get("class") != "装备":
            warnings.append(f"custom.json[{index}]: 忽略无名称或非装备条目")
            continue
        if is_private_item(item):
            warnings.append(f"custom.json[{index}] {name}: 忽略绑定私有装备")
            continue
        if name in names:
            warnings.append(f"custom.json: 重名装备 {name}，保留首个定义")
            continue
        names.add(name)
        out.append(copy.deepcopy(dict(item)))
    return out, warnings


def merge_legacy_registry(world: dict[str, Any], imported: Any) -> int:
    """Merge imported public definitions by name; keep existing definitions on conflicts."""
    incoming, _warnings = normalize_registry(imported)
    rows = world.get(REGISTRY_KEY)
    if not isinstance(rows, list):
        rows = []
        world[REGISTRY_KEY] = rows
    existing = {str(row.get("name") or "") for row in rows if isinstance(row, Mapping)}
    added = 0
    for row in incoming:
        if row["name"] in existing:
            continue
        rows.append(row)
        existing.add(row["name"])
        added += 1
    return added


def custom_equipment(world: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the mutable public registry stored in calamity/world state."""
    rows = world.get(REGISTRY_KEY)
    if not isinstance(rows, list):
        rows = []
        world[REGISTRY_KEY] = rows
    return rows


def equipment_index(world: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Build the public dynamic name index, excluding private/bound cards."""
    rows = world.get(REGISTRY_KEY) if isinstance(world, Mapping) else None
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (not isinstance(row, Mapping) or is_private_item(row)
                or row.get("class") != "装备" or not row.get("name")):
            continue
        result.setdefault(str(row["name"]), dict(row))
    return result


def _legacy_instance(instances: Mapping[str, Any] | None, name: str,
                     predicate=None) -> Mapping | None:
    if not isinstance(instances, Mapping):
        return None
    value = instances.get(name)
    rows = [value] if isinstance(value, Mapping) else value if isinstance(value, list) else []
    rows = [item for item in rows if isinstance(item, Mapping)]
    if predicate is not None:
        return next((item for item in rows if predicate(item)), rows[0] if rows else None)
    return rows[0] if rows else None


def lookup_item(name: str, static_index: Mapping[str, Any], world: Mapping[str, Any] | None,
                *, private_items: Mapping[str, Any] | None = None,
                owner_uid: str = "",
                instance_items: Mapping[str, Any] | None = None,
                instance_predicate=None) -> Mapping[str, Any] | None:
    """Resolve owner-bound cards, imported instance snapshots, then public catalogs.

    Instance snapshots come from original per-item 纳戒 entries and retain upgraded
    stats that the port's name->quantity inventory cannot represent by itself.
    """
    key = str(name or "")
    private = private_items.get(key) if isinstance(private_items, Mapping) else None
    private_uid = (private.get("绑定者") or private.get("private_owner_uid")
                   or private.get("owner_uid") or private.get("owner_id") or "") \
        if isinstance(private, Mapping) else ""
    if (isinstance(private, Mapping) and is_private_item(private)
            and owner_uid and str(private_uid) == str(owner_uid)):
        return private

    instance = _legacy_instance(instance_items, key, instance_predicate)
    if isinstance(instance, Mapping):
        if is_private_item(instance):
            instance_uid = (instance.get("绑定者") or instance.get("private_owner_uid")
                            or instance.get("owner_uid") or instance.get("owner_id") or "")
            if not owner_uid or str(instance_uid) != str(owner_uid):
                instance = None
        if instance is not None:
            return instance

    static = static_index.get(key) if isinstance(static_index, Mapping) else None
    if isinstance(static, Mapping):
        return static
    return equipment_index(world).get(key)


def is_nameable_percentage_equipment(item: Mapping[str, Any] | None) -> bool:
    """Fixed-original equipment nameability rule from model/equipmentStats.js."""
    if not isinstance(item, Mapping):
        return False
    if item.get("class") != "装备" and item.get("type") not in EQUIPMENT_TYPES:
        return False
    try:
        atk = float(item.get("atk", 0) or 0)
        defense = float(item.get("def", 0) or 0)
        hp = float(item.get("HP", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    cap = 500.0 if item.get("天阙创世") is True else MAX_PERCENT_STAT
    if max(atk, defense, hp) > cap:
        return False
    return (atk >= 1.5 or defense >= 1.2
            or item.get("type") == "法宝" and (atk >= 1 or defense >= 1)
            or atk + defense > 1.95)


def _inventory_count(inventory: Mapping[str, Any], name: str) -> int:
    try:
        return max(0, int(inventory.get(name, 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _sync_worn_name(doc: Any, old: str, new: str) -> None:
    equipment = doc.ext.get("equipment")
    if isinstance(equipment, dict):
        for slot, equipped in list(equipment.items()):
            current = equipped.get("name") if isinstance(equipped, Mapping) else equipped
            if current == old:
                equipment[slot] = new


def _rename_instance_snapshot(doc: Any, old: str, new: str, source: Mapping[str, Any]) -> int:
    """Rename only the source stack selected by original getnewname(), preserving peers."""
    instances = doc.ext.get("legacy_equipment_instances")
    if not isinstance(instances, dict):
        return 0
    rows = instances.get(old)
    if isinstance(rows, Mapping):
        rows = [rows]
    if not isinstance(rows, list):
        return 0
    for index, card in enumerate(rows):
        if card is source:
            try:
                quantity = max(1, int(card.get("数量", card.get("num", 1)) or 1))
            except (TypeError, ValueError, OverflowError):
                quantity = 1
            card["name"] = new
            rows.pop(index)
            if not rows:
                instances.pop(old, None)
            renamed = instances.setdefault(new, [])
            if isinstance(renamed, list):
                renamed.append(card)
            elif isinstance(renamed, dict):
                instances[new] = [renamed, card]
            else:
                instances[new] = [card]
            return quantity
    return 0


def _rename_all_instance_snapshots(doc: Any, old: str, new: str) -> None:
    instances = doc.ext.get("legacy_equipment_instances")
    if not isinstance(instances, dict):
        return
    rows = instances.pop(old, None)
    if rows is None:
        return
    if isinstance(rows, Mapping):
        rows = [rows]
    if isinstance(rows, list):
        for card in rows:
            if isinstance(card, dict):
                card["name"] = new
        existing = instances.get(new)
        if isinstance(existing, list):
            existing.extend(rows)
        elif isinstance(existing, Mapping):
            instances[new] = [existing, *rows]
        else:
            instances[new] = rows


def register_named_equipment(doc: Any, inventory: Mapping[str, Any], source: Mapping[str, Any],
                             old_name: str, new_name: str, world: dict[str, Any], now: float,
                             name_exists) -> tuple[bool, str, dict[str, int]]:
    """Rename an eligible owned card and register its public definition.

    Returns an inventory delta for the caller to commit atomically with PlayerDoc
    and calamity_state, mirroring the original inventory/custom.json write pair.
    """
    old_name, new_name = str(old_name or "").strip(), str(new_name or "").strip()
    if not old_name or not new_name:
        return False, "格式：#赋名 原装备名*新名字", {}
    if len(new_name) > MAX_NAME_LENGTH:
        return False, f"字符超出最大限制（{MAX_NAME_LENGTH} 字），请重新赋名。", {}
    if _inventory_count(inventory, old_name) < 1:
        return False, f"你没有这件装备（{old_name}）。", {}
    if not isinstance(source, Mapping) or str(source.get("name") or old_name) != old_name:
        return False, "找不到原装备属性档案。", {}
    if is_private_item(source):
        return False, "绑定或私有装备不能登记为全服共享物品。", {}
    if not is_nameable_percentage_equipment(source):
        return False, "这件装备不符合赋名条件。", {}

    rows = custom_equipment(world)
    registered_names = {str(row.get("name") or "") for row in rows if isinstance(row, Mapping)}
    if old_name in registered_names:
        return False, "这件装备已完成赋名，请使用 #神兵重铸 改名。", {}
    if any(str(row.get("原名") or "") == old_name for row in rows if isinstance(row, Mapping)):
        return False, "一件装备只能赋名一次。", {}
    if new_name == old_name or new_name in registered_names or bool(name_exists(new_name)):
        return False, "这个世间已经拥有这个名字了。", {}

    card = copy.deepcopy(dict(source))
    card["name"] = new_name
    card["class"] = "装备"
    card["owner_name"] = str(doc.uid)
    try:
        rarity = float(card.get("稀有度", 2) or 2)
        card["稀有度"] = max(1, min(10, rarity))
    except (TypeError, ValueError, OverflowError):
        card["稀有度"] = 2
    for field in ("atk", "def", "HP"):
        try:
            card[field] = math.floor(float(card.get(field, 0) or 0) * 100 + 0.5) / 100
        except (TypeError, ValueError, OverflowError):
            card[field] = 0
    rows.append(card)
    _sync_worn_name(doc, old_name, new_name)
    transferred = _rename_instance_snapshot(doc, old_name, new_name, source)
    quantity = min(_inventory_count(inventory, old_name), transferred or 1)
    return True, f"赋名成功：「{old_name}」已更名为「{new_name}」。", {
        old_name: -quantity, new_name: quantity,
    }


def recast_named_equipment(doc: Any, inventory: Mapping[str, Any], old_name: str,
                           new_name: str, world: dict[str, Any], now: float,
                           name_exists) -> tuple[bool, str, dict[str, int]]:
    """Rename a public custom item, keeping its catalog and wear slots in sync."""
    old_name, new_name = str(old_name or "").strip(), str(new_name or "").strip()
    if not old_name or not new_name or len(new_name) > MAX_NAME_LENGTH:
        return False, f"新名字不能为空，且不能超过 {MAX_NAME_LENGTH} 字。", {}
    if _inventory_count(inventory, old_name) < 1:
        return False, f"你没有这件装备（{old_name}）。", {}
    rows = custom_equipment(world)
    entry = next((row for row in rows if isinstance(row, dict) and row.get("name") == old_name), None)
    if not entry or is_private_item(entry):
        return False, f"「{old_name}」不是可重铸的公开赋名装备。", {}
    if (new_name == old_name or any(
            isinstance(row, Mapping) and row.get("name") == new_name for row in rows
    ) or bool(name_exists(new_name))):
        return False, "这个世间已经拥有这个名字了。", {}
    entry["name"] = new_name
    _sync_worn_name(doc, old_name, new_name)
    _rename_all_instance_snapshots(doc, old_name, new_name)
    quantity = _inventory_count(inventory, old_name)
    _rename_all_instance_snapshots(doc, old_name, new_name)
    return True, f"神兵已重塑真名：「{old_name}」→「{new_name}」。", {
        old_name: -quantity, new_name: quantity,
    }


def remove_named_equipment(world: dict[str, Any], name: str) -> bool:
    """Explicit administrative/global-wipe deletion; ordinary selling keeps catalog history."""
    rows = custom_equipment(world)
    before = len(rows)
    rows[:] = [row for row in rows if not (isinstance(row, Mapping) and row.get("name") == name)]
    return len(rows) != before
