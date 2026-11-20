"""只读预检与事务性导入 Yunzai 原版玩家/纳戒存档。

原版存档是按 QQ 分文件的 JSON；移植版把玩家聚合写入 SQLite、背包写入
inventory。该模块只负责边界转换，不在读取时修改源文件，也不自动覆盖已有玩家。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


PLAYER_DIR_NAMES = ("xiuxian_player", "players")
NAJIE_DIR_NAMES = ("xiuxian_najie", "najie", "inventory")


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


def normalize_player(raw: Mapping[str, Any], uid_hint: str) -> tuple[dict[str, Any], list[str]]:
    """把原版常见中文字段转换为 PlayerDoc 可保存的字典。"""
    uid = _uid(raw, uid_hint)
    realm = raw.get("realm_index", raw.get("境界等级", raw.get("境界", 0)))
    physique = raw.get("physique_index", raw.get("炼体等级", raw.get("炼体境界", 0)))
    doc = {
        "uid": uid,
        "name": str(raw.get("name", raw.get("名号", raw.get("姓名", ""))) or ""),
        "realm_table": str(raw.get("realm_table", "Level/练气境界")),
        "realm_index": max(0, _number(realm)),
        "physique_index": max(0, _number(physique)),
        "exp": max(0, _number(raw.get("exp", raw.get("修为", 0)))),
        "stones": max(0, _number(raw.get("stones", raw.get("灵石", 0)))),
        "state": str(raw.get("state", raw.get("当前动作", raw.get("状态", "空闲"))) or "空闲"),
        "state_start": float(raw.get("state_start", raw.get("动作开始时间", 0)) or 0),
        "created_at": float(raw.get("created_at", raw.get("创建时间", 0)) or 0),
        # 原版没有一一对应的 ext 字段；完整源文档放入命名空间，避免静默丢失。
        "ext": {"legacy_source": dict(raw)},
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
    report: dict[str, Any] = {
        "source": str(base), "players": [], "errors": [], "warnings": [],
        "source_sha256": {}, "ready": False,
    }
    if not player_dir:
        report["errors"].append("找不到 xiuxian_player/players 目录")
        return report
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
        if najie_dir:
            path_n = najie_dir / f"{path.stem}.json"
            if path_n.exists():
                raw_n, error_n = _json(path_n)
                report["source_sha256"][str(path_n)] = hashlib.sha256(path_n.read_bytes()).hexdigest()
                if error_n or raw_n is None:
                    item["warnings"].append(error_n or f"{path_n}: 无法读取")
                else:
                    item["inventory"], inv_warnings = normalize_inventory(raw_n)
                    item["warnings"].extend(inv_warnings)
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
    async with db.transaction() as conn:
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
    return {"imported": imported, "skipped": skipped}
