"""只读预检与事务性导入 Yunzai 原版玩家/纳戒存档。

原版存档是按 QQ 分文件的 JSON；移植版把玩家聚合写入 SQLite、背包写入
inventory。该模块只负责边界转换，不在读取时修改源文件，也不自动覆盖已有玩家。
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Mapping

from . import custom_items
from .wenxian import EXP_PER_LEVEL, MAX_LEVEL


PLAYER_DIR_NAMES = ("xiuxian_player", "players")
NAJIE_DIR_NAMES = ("xiuxian_najie", "najie", "inventory")
EQUIPMENT_DIR_NAMES = ("xiuxian_equipment", "equipment")
CUSTOM_JSON_CANDIDATES = (
    "resources/data/custom/custom.json", "data/custom/custom.json",
    "custom/custom.json", "custom.json",
)


def _json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{path}: {exc}"
    if isinstance(value, dict):
        return value, None
    return None, f"{path}: 根值不是对象"


def _number(value: Any, default: int = 0) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return number


def _uid(raw: Mapping[str, Any], fallback: str) -> str:
    for key in ("uid", "id", "QQ", "qq", "user_id", "用户"):
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).replace("qg_", "").strip()
    return fallback.replace("qg_", "").strip()


def _normalize_wenxian(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None

    claimed = sorted({
        level for value in raw.get("claimed", []) if (level := _number(value, -1)) in range(1, MAX_LEVEL + 1)
    }) if isinstance(raw.get("claimed"), list) else []
    level = max(0, _number(raw.get("level", 0)), max(claimed, default=0))
    total_exp = max(0, _number(raw.get("exp", 0)), level * EXP_PER_LEVEL)
    total_exp = min(MAX_LEVEL * EXP_PER_LEVEL, total_exp)
    level = min(MAX_LEVEL, total_exp // EXP_PER_LEVEL)
    exp = min(EXP_PER_LEVEL - 1, total_exp - level * EXP_PER_LEVEL)
    unlocked = raw.get("unlocked")
    tasks = raw.get("tasks") if isinstance(raw.get("tasks"), Mapping) else {}
    source_weekly = tasks.get("weekly") if isinstance(tasks.get("weekly"), Mapping) else {}
    source_progress = source_weekly.get("progress") if isinstance(source_weekly.get("progress"), Mapping) else {}
    weekly_progress = {
        "daily_task": _number(source_progress.get("dailyTask", 0)),
        "tianjiao": _number(source_progress.get("tianjiao", 0)),
        "stone_market": _number(source_progress.get("stoneMarket", 0)),
        "spirit_heart": _number(source_progress.get("spiritHeart", 0)),
        "dungeon": _number(source_progress.get("dungeon", 0)),
    }
    trial = raw.get("trial") if isinstance(raw.get("trial"), Mapping) else {}
    clue = raw.get("clue") or False
    return {
        "active": bool(unlocked) if isinstance(unlocked, bool) else bool(total_exp or claimed),
        "clue": clue,
        "step": 3 if trial.get("clueExplored") else 0,
        "level": level,
        "exp": exp,
        "claimed": claimed,
        "daily": {},
        "weekly": {
            "week": str(source_weekly.get("weekKey") or ""),
            "prog": weekly_progress,
            "claimed": bool(source_weekly.get("claimed")),
        },
        "trial": {
            "dailyTasks": min(7, max(0, _number(trial.get("dailyTasks", 0)))),
            "lastDailyTaskDate": str(trial.get("lastDailyTaskDate") or ""),
            "innerWorldOpened": bool(trial.get("innerWorldOpened")),
            "tianjiaoDefeated": bool(trial.get("tianjiaoDefeated")),
            "clueExplored": bool(trial.get("clueExplored")),
        },
        "pendingExp": max(0, _number(raw.get("pendingExp", 0))),
        "dungeonClueAttempts": min(30, max(0, _number(raw.get("dungeonClueAttempts", 0)))),
        "lastDungeonClueDate": str(raw.get("lastDungeonClueDate") or ""),
        "legacyTasks": dict(tasks),
    }


def normalize_player(raw: Mapping[str, Any], uid_hint: str) -> tuple[dict[str, Any], list[str]]:
    """把原版常见中文字段转换为 PlayerDoc 可保存的字典。"""
    uid = _uid(raw, uid_hint)
    # 原版 level_id/Physique_id 从 1 开始；PlayerDoc 的 index 从 0 开始。
    realm = raw.get("realm_index", raw.get("level_id", raw.get("境界等级", raw.get("境界", 1))))
    physique = raw.get("physique_index", raw.get("Physique_id", raw.get("炼体等级", raw.get("炼体境界", 1))))
    realm_index = max(0, _number(realm) - (0 if "realm_index" in raw else 1))
    physique_index = max(0, _number(physique) - (0 if "physique_index" in raw else 1))
    preserved = dict(raw)
    # 这些是 Python 现有系统已经消费的领域状态；原文档仍完整保存在 legacy_source。
    state_map = {
        "yuanshi": _number(raw.get("源石", 0)),
        "hp_current": max(0, _number(raw.get("当前血量", 0))),
        "hp_max": max(0, _number(raw.get("血量上限", 0))),
        "xueqi": max(0, _number(raw.get("血气", 0))),
        "lifespan": max(0, _number(raw.get("寿元", 0))),
        "potential": max(0, _number(raw.get("仙道潜力", 0))),
        "daoxin": max(0, _number(raw.get("道心值", raw.get("道心", 0)))),
        "modao": max(0, _number(raw.get("魔道值", 0))),
        "power_place": raw.get("power_place", 0),
        "luck": _number(raw.get("幸运", 0)),
        "speed": _number(raw.get("速度", 100)),
        "occupation": raw.get("occupation", []),
        "occupation_level": max(0, _number(raw.get("occupation_level", 0))),
        "cultivation_efficiency": float(raw.get("修炼效率提升", 0) or 0),
    }
    wenxian_state = _normalize_wenxian(raw.get("问仙令"))
    if wenxian_state is not None:
        state_map["wenxian"] = wenxian_state
    if isinstance(raw.get("灵根"), Mapping):
        state_map["linggen"] = dict(raw["灵根"])
    elif isinstance(raw.get("linggen"), list) and raw["linggen"]:
        state_map["linggen_legacy"] = list(raw["linggen"])
    if isinstance(raw.get("学习的功法"), list):
        state_map["gongfa"] = list(raw["学习的功法"])
    preserved.pop("ext", None)
    doc = {
        "uid": uid,
        "name": str(raw.get("name", raw.get("名号", raw.get("姓名", ""))) or ""),
        "realm_table": str(raw.get("realm_table", "Level/练气境界")),
        "realm_index": realm_index,
        "physique_index": physique_index,
        "exp": max(0, _number(raw.get("exp", raw.get("修为", 0)))),
        "stones": max(0, _number(raw.get("stones", raw.get("灵石", 0)))),
        "state": str(raw.get("state", raw.get("当前动作", raw.get("状态", "空闲"))) or "空闲"),
        "state_start": float(raw.get("state_start", raw.get("动作开始时间", 0)) or 0),
        "created_at": float(raw.get("created_at", raw.get("创建时间", 0)) or 0),
        # 原版没有一一对应的 ext 字段；完整源文档放入命名空间，避免静默丢失。
        "ext": {"legacy_source": preserved, **state_map},
    }
    warnings: list[str] = []
    if not doc["uid"]:
        warnings.append("缺少玩家 UID")
    if not doc["name"]:
        warnings.append(f"{uid}: 缺少名号，使用空字符串")
    if _number(realm, -1) < 0:
        warnings.append(f"{uid}: 境界无法转换，回退为 0")
    return doc, warnings


def normalize_inventory(raw: Mapping[str, Any]) -> tuple[dict[str, int], list[str]]:
    """展开原版纳戒分类数组；装备按名称聚合，数量字段兼容 num/数量/amount。"""
    out: dict[str, int] = {}
    warnings: list[str] = []
    for category, entries in raw.items():
        if category in ("灵石", "源石") or not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, Mapping):
                warnings.append(f"{category}: 忽略非对象条目")
                continue
            name = str(item.get("name", item.get("名称", item.get("物品", ""))) or "").strip()
            qty = _number(item.get("num", item.get("数量", item.get("amount", 1))), 0)
            if not name:
                warnings.append(f"{category}: 忽略无名称条目")
            elif qty < 0:
                warnings.append(f"{name}: 数量为负，拒绝导入")
            elif qty:
                out[name] = out.get(name, 0) + qty
    return out, warnings


def normalize_equipment(raw: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    """把原版独立装备档转换为 Python `ext["equipment"]` 五槽位名称。"""
    slots = ("武器", "护具", "法宝", "帝兵", "至宝", "饰品", "帝具")
    out: dict[str, str] = {}
    warnings: list[str] = []
    for slot in slots:
        item = raw.get(slot)
        if item in (None, "", False):
            continue
        if isinstance(item, Mapping):
            name = str(item.get("先天至宝本体") or item.get("name", item.get("名称", "")) or "").strip()
        else:
            name = str(item).strip()
        if not name:
            warnings.append(f"{slot}: 装备条目没有名称")
            continue
        # Python 装备模块使用“至宝”槽；原版旧字段“饰品/帝具”保留在 legacy_source。
        target = "至宝" if slot in ("饰品", "帝具") else slot
        if target in out:
            warnings.append(f"{target}: 存在多个装备，保留 {out[target]}，忽略 {name}")
            continue
        out[target] = name
    return out, warnings


def normalize_equipment_instances(raw: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Preserve original per-item equipment snapshots before name/quantity aggregation."""
    out: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    entries = raw.get("装备")
    if not isinstance(entries, list):
        return out, warnings
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            warnings.append(f"装备[{index}]: 忽略非对象条目")
            continue
        name = str(item.get("name", item.get("名称", item.get("物品", ""))) or "").strip()
        qty = _number(item.get("num", item.get("数量", item.get("amount", 1))), 0)
        if not name or qty <= 0:
            continue
        card = dict(item)
        card["name"] = name
        card["class"] = "装备"
        card["数量"] = qty
        out.setdefault(name, []).append(card)
    return out, warnings


def _find_custom_json(root: Path) -> Path | None:
    for relative in CUSTOM_JSON_CANDIDATES:
        path = root / relative
        if path.is_file():
            return path
    return None

def _find_dir(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = root / name
        if path.is_dir():
            return path
    return None


def preflight(root: str | Path) -> dict[str, Any]:
    """扫描原版目录并返回可审阅报告；不会连接数据库或写文件。"""
    base = Path(root)
    player_dir = _find_dir(base, PLAYER_DIR_NAMES)
    najie_dir = _find_dir(base, NAJIE_DIR_NAMES)
    equipment_dir = _find_dir(base, EQUIPMENT_DIR_NAMES)
    report: dict[str, Any] = {
        "source": str(base), "players": [], "errors": [], "warnings": [],
        "source_sha256": {}, "custom_equipment": None, "ready": False,
    }
    if not player_dir:
        report["errors"].append("找不到 xiuxian_player/players 目录")
        return report
    custom_path = _find_custom_json(base)
    if custom_path is not None:
        try:
            custom_raw = json.loads(custom_path.read_text(encoding="utf-8"))
            custom_rows, custom_warnings = custom_items.normalize_registry(custom_raw)
            report["custom_equipment"] = custom_rows
            report["warnings"].extend(custom_warnings)
            report["source_sha256"][str(custom_path)] = hashlib.sha256(custom_path.read_bytes()).hexdigest()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            report["warnings"].append(f"{custom_path}: {exc}; 保留现有动态装备目录，未导入 custom.json")
    else:
        report["warnings"].append(
            "未找到原版 resources/data/custom/custom.json；玩家和纳戒仍可导入，"
            "但旧动态赋名装备不会迁入。")
    files = sorted(player_dir.glob("*.json"))
    for path in files:
        raw, error = _json(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        report["source_sha256"][str(path)] = digest
        if error or raw is None:
            report["errors"].append(error or f"{path}: 无法读取")
            continue
        doc, warnings = normalize_player(raw, path.stem)
        uid = doc["uid"]
        item = {"uid": uid, "player_file": str(path), "doc": doc, "inventory": {}, "warnings": warnings}
        if equipment_dir:
            path_e = equipment_dir / f"{path.stem}.json"
            if path_e.exists():
                raw_e, error_e = _json(path_e)
                report["source_sha256"][str(path_e)] = hashlib.sha256(path_e.read_bytes()).hexdigest()
                if error_e or raw_e is None:
                    item["warnings"].append(error_e or f"{path_e}: 无法读取")
                else:
                    equipment, eq_warnings = normalize_equipment(raw_e)
                    item["doc"]["ext"]["equipment"] = equipment
                    projection = {}
                    for slot in ("帝兵", "至宝", "饰品", "帝具"):
                        legacy_item = raw_e.get(slot)
                        if not isinstance(legacy_item, Mapping):
                            continue
                        treasure = str(legacy_item.get("先天至宝本体") or "").strip()
                        deadline = legacy_item.get("先天投影截止")
                        if treasure and deadline is not None:
                            deadline = float(deadline or 0)
                            projection[treasure] = deadline / 1000 if deadline > 100_000_000_000 else deadline
                    if projection:
                        item["doc"]["ext"]["xtzb"] = {"owned": list(projection), "projection": projection}
                    item["warnings"].extend(eq_warnings)
            else:
                item["warnings"].append(f"{uid}: 找不到对应装备文件")
        if najie_dir:
            path_n = najie_dir / f"{path.stem}.json"
            if path_n.exists():
                raw_n, error_n = _json(path_n)
                report["source_sha256"][str(path_n)] = hashlib.sha256(path_n.read_bytes()).hexdigest()
                if error_n or raw_n is None:
                    item["warnings"].append(error_n or f"{path_n}: 无法读取")
                else:
                    item["inventory"], inv_warnings = normalize_inventory(raw_n)
                    instances, instance_warnings = normalize_equipment_instances(raw_n)
                    if instances:
                        item["doc"]["ext"]["legacy_equipment_instances"] = instances
                    item["warnings"].extend(inv_warnings)
                    item["warnings"].extend(instance_warnings)
            else:
                item["warnings"].append(f"{uid}: 找不到对应纳戒文件")
        else:
            item["warnings"].append("找不到纳戒目录，背包将为空")
        report["players"].append(item)
        report["warnings"].extend(item["warnings"])
    uids = [item["uid"] for item in report["players"]]
    if len(uids) != len(set(uids)):
        report["errors"].append("存在重复 UID，拒绝导入")
    report["ready"] = bool(report["players"]) and not report["errors"]
    return report


async def import_report(db: Any, report: Mapping[str, Any], *, overwrite: bool = False) -> dict[str, int]:
    """把已预检报告导入 SQLite；默认不覆盖现有玩家，异常整体回滚。"""
    if not report.get("ready"):
        raise ValueError("预检未通过，不能导入")
    imported = skipped = 0
    async with AsyncExitStack() as stack:
        calamity_lock = getattr(db, "calamity_lock", None)
        if isinstance(report.get("custom_equipment"), list) and calamity_lock is not None:
            await stack.enter_async_context(calamity_lock)
        conn = await stack.enter_async_context(db.transaction())
        for entry in report["players"]:
            uid = str(entry["uid"])
            async with conn.execute("SELECT 1 FROM players WHERE uid = ?", (uid,)) as cur:
                exists = await cur.fetchone() is not None
            if exists and not overwrite:
                skipped += 1
                continue
            await conn.execute(
                "INSERT INTO players (uid, doc, updated_at) VALUES (?, ?, strftime('%s','now')) "
                "ON CONFLICT(uid) DO UPDATE SET doc=excluded.doc, updated_at=excluded.updated_at",
                (uid, json.dumps(entry["doc"], ensure_ascii=False)),
            )
            await conn.execute("DELETE FROM inventory WHERE uid = ?", (uid,))
            for name, qty in dict(entry.get("inventory") or {}).items():
                if int(qty) > 0:
                    await conn.execute("INSERT INTO inventory (uid, item, qty) VALUES (?, ?, ?)", (uid, name, int(qty)))
            imported += 1
        imported_custom = 0
        if isinstance(report.get("custom_equipment"), list):
            calamity = await db.get_calamity()
            forge = calamity.get("forge")
            if not isinstance(forge, dict):
                forge = {}
                calamity["forge"] = forge
            imported_custom = custom_items.merge_legacy_registry(forge, report["custom_equipment"])
            if imported_custom:
                await db.save_calamity(calamity)
    return {"imported": imported, "skipped": skipped, "custom_equipment": imported_custom}
