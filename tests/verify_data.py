"""Compare packaged JSON with the pinned original Git snapshot.

Usage: python tests/verify_data.py [original-repository]
The checker reads the pinned commit with ``git archive`` and applies only the
explicit migration allowlists below. It does not infer parity from row counts.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

PINNED_ORIGINAL_REVISION = "04af6a9a7ec11e700a0aedb85a5981e48826035c"
DEFAULT_ORIGINAL_REPO = Path(tempfile.gettempdir()) / "zhutian-original-parity-audit"
PLUGIN_DATA = Path(__file__).resolve().parent.parent / "data"
ORIGINAL_DATA_PREFIX = "resources/data/"

# Plugin-owned files added after the pinned source commit.
ALLOWED_ADDED_FILES = {
    "chengzhang/chengzhang.json", "cmd_config.json", "daofa_list.json",
    "dimension_guard_state.json", "fishing/immortal.json", "forbidden_event_state.json",
    "foreign_imperial_pass.json",
    "help/Association.json", "help/help.json", "help/help2.json", "help/helpcopy.json",
    "help/huodonghelp.json", "help/jichuhelp.json", "help/linggenhelp.json", "help/set.json",
    "help/shituhelp.json", "help/xiaoshijiehelp.json", "help/xinghai.json",
    "help/zhiyehelp.json", "help/zhounianqing.json", "help/zhutianhelp.json",
    "innate_treasure_state.json", "item/位面天骄.json", "item/兑换码.json",
    "item/小世界列表.json", "item/异果.json", "item/本命材料.json", "item/玩家自创帝经.json",
    "item/精神宇宙掉落.json", "item/至宝信物.json", "item/花粉.json",
    "jingshen/精神宇宙.json", "plane_rift_festival.json", "renwu/renwu.json",
    "strange_sacrifice_state.json", "weimian_events.json", "xianguSecretPlace.json", "位面.json",
}

# Local rows intentionally retained alongside the pinned original records.
ALLOWED_ADDED_ROWS = {
    "item/位面boss列表.json": {("名号", "猪咪岁岁")},
    "item/功法列表.json": {("name", "鹤鸣九霄")},
    "item/成就列表.json": {("name", "破网者")},
    # 折冠破妄：pin 快照 04af6a9 之后原版新增（GitHub V1.0 快照已含），0.1.7 按原版补齐。
    "item/命格词条.json": {("name", "折冠破妄")},
    "item/技能组/攻击技能.json": {("name", "鹤鸣九霄")},
    "item/每日抽奖列表.json": {("name", "奇怪的石头")},
    "item/装备列表.json": {
        ("name", "紫云剑"), ("name", "炼血竹枪"), ("name", "少阴玉剑"),
        ("name", "造化·三千世界"), ("name", "仙尊战袍·拓本"),
        ("name", "弑帝枪·拓本"), ("name", "万劫不侵钟·拓本"),
    },
    "item/道具列表.json": {
        ("name", "奇怪的石头"), ("name", "不朽之王传承"), ("name", "异域法则"),
    },
}

# (table, identity, field) -> (pinned source value, approved plugin value)
ALLOWED_UPDATED_FIELDS = {
    ("item/材料列表.json", ("name", "天外清风"), "desc"): (
        "可用 #消耗天外清风 获得一次清风引路，使下一次跨位面穿梭缩短5分钟，最低保留1分钟；亦可合成大位面传送阵",
        "使用 #使用 天外清风 [数量] 获得对应次数的清风引路；每次跨位面旅行缩短5分钟，至少保留1分钟；亦可合成大位面传送阵",
    ),
}

# Added help text on pinned rows; numerical and behavioral fields remain exact.
_FORGING_PILL_DESC = "提升锻炉容量，效果持续至下一次成功开炉并在出炉后消耗；需先完成炼器师能力评测，每次限用1颗。"
_SPIRIT_PILL_DESC = "服用后提升炼器师锻造天赋，最高200（超出上限部分不生效）；需先完成能力评测，每次限用1颗。"
ALLOWED_ADDED_FIELDS = {
    ("item/炼丹师丹药.json", ("name", "凡品器灵丹")): {"desc": _SPIRIT_PILL_DESC},
    ("item/炼丹师丹药.json", ("name", "极品器灵丹")): {"desc": _SPIRIT_PILL_DESC},
    ("item/炼丹师丹药.json", ("name", "仙品器灵丹")): {"desc": _SPIRIT_PILL_DESC},
    ("item/炼丹师丹药.json", ("name", "凡品真器丹")): {"desc": _FORGING_PILL_DESC},
    ("item/炼丹师丹药.json", ("name", "极品真器丹")): {"desc": _FORGING_PILL_DESC},
    ("item/炼丹师丹药.json", ("name", "仙品真器丹")): {"desc": _FORGING_PILL_DESC},
    ("item/道具列表.json", ("name", "帝品真器丹")): {
        "desc": "提升锻炉容量10件，效果持续至下一次成功开炉并在出炉后消耗；需先完成炼器师能力评测，每次限用1颗。",
    },
    ("item/道具列表.json", ("name", "圣品真器丹")): {
        "desc": "提升锻炉容量4件，效果持续至下一次成功开炉并在出炉后消耗；需先完成炼器师能力评测，每次限用1颗。",
    },
}

# Small source fingerprints detect an accidentally changed baseline revision.
SAMPLE_COUNTS = {
    "item/丹药列表.json": 221,
    "item/炼丹师丹药.json": 29,
    "occupation/炼丹配方.json": 21,
    "item/灵根列表.json": 139,
}


def load_json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8-sig"))


def load_pinned_original(repo: Path) -> dict[str, Any]:
    resolved = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{PINNED_ORIGINAL_REVISION}^{{commit}}"],
        stderr=subprocess.PIPE,
        text=True,
    ).strip()
    if resolved != PINNED_ORIGINAL_REVISION:
        raise ValueError(f"原版解析为 {resolved}，与锁定版本不一致")

    tar_bytes = subprocess.check_output(
        ["git", "-C", str(repo), "archive", "--format=tar", PINNED_ORIGINAL_REVISION, "resources/data"],
        stderr=subprocess.PIPE,
    )
    tables: dict[str, Any] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith(ORIGINAL_DATA_PREFIX):
                continue
            rel = member.name[len(ORIGINAL_DATA_PREFIX):]
            if not rel.endswith(".json"):
                continue
            stream = archive.extractfile(member)
            if stream is not None:
                tables[rel] = load_json(stream.read())
    return tables


def load_plugin_tables() -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for path in PLUGIN_DATA.rglob("*.json"):
        rel = path.relative_to(PLUGIN_DATA).as_posix()
        tables[rel] = load_json(path.read_bytes())
    return tables


def row_identity(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    for key in ("name", "名号", "名称", "名字", "物品名", "装备名", "技能名", "功法名", "id", "ID"):
        if key in value and isinstance(value[key], (str, int, float)):
            return key, str(value[key])
    return None


def strict_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def record_matches(path: str, original: Any, port: Any) -> bool:
    if not isinstance(original, dict) or not isinstance(port, dict):
        return strict_equal(original, port)

    identity = row_identity(original)
    allowed_added = ALLOWED_ADDED_FIELDS.get((path, identity), {})
    extra_fields = set(port) - set(original)
    if extra_fields != set(allowed_added):
        return False
    if any(port.get(field) != expected for field, expected in allowed_added.items()):
        return False

    for field, original_value in original.items():
        if field not in port:
            return False
        changed = ALLOWED_UPDATED_FIELDS.get((path, identity, field))
        if changed is None:
            if not strict_equal(original_value, port[field]):
                return False
        else:
            expected_original, expected_port = changed
            if original_value != expected_original or port[field] != expected_port:
                return False
    return True


def compare_table(path: str, original: Any, port: Any) -> tuple[list[str], int, int]:
    errors: list[str] = []
    verified = added = 0
    if isinstance(original, list) and isinstance(port, list):
        remaining = list(enumerate(port))
        for source_row in original:
            identity = row_identity(source_row)
            candidates = [
                pair for pair in remaining
                if (row_identity(pair[1]) == identity if identity is not None else pair[1] == source_row)
            ]
            match = next((pair for pair in candidates if record_matches(path, source_row, pair[1])), None)
            if match is None:
                errors.append(f"{path}: 原版记录缺失或被改动：{identity or source_row!r}")
                continue
            remaining.remove(match)
            verified += 1

        actual_added = [row_identity(row) for _, row in remaining]
        expected_added = ALLOWED_ADDED_ROWS.get(path, set())
        if set(actual_added) != expected_added or len(actual_added) != len(expected_added):
            errors.append(
                f"{path}: 新增记录不符；实际={sorted(actual_added, key=str)}，"
                f"期望={sorted(expected_added, key=str)}"
            )
        else:
            added = len(remaining)
    elif not strict_equal(original, port):
        errors.append(f"{path}: 非列表数据与原版不一致")
    else:
        verified = 1
    return errors, verified, added


def main() -> int:
    original_repo = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ORIGINAL_REPO
    if not original_repo.exists():
        print(f"固定原版仓库不存在: {original_repo}")
        print("用法：python tests/verify_data.py [原版仓库工作树路径]")
        return 2
    try:
        original = load_pinned_original(original_repo)
    except (OSError, subprocess.CalledProcessError, tarfile.TarError, ValueError) as exc:
        print(f"无法读取锁定原版 {PINNED_ORIGINAL_REVISION}: {exc}")
        return 2

    plugin = load_plugin_tables()
    missing = sorted(set(original) - set(plugin))
    added_files = sorted(set(plugin) - set(original))
    unexpected_added_files = sorted(set(added_files) - ALLOWED_ADDED_FILES)
    absent_added_files = sorted(ALLOWED_ADDED_FILES - set(added_files))
    print(f"原版 JSON 表: {len(original)} | 插件 JSON 表: {len(plugin)}")
    print(f"锁定原版提交: {PINNED_ORIGINAL_REVISION}")
    print(f"缺少原版表: {missing}")
    print(f"未登记插件新增表: {unexpected_added_files}")
    print(f"登记但不存在的插件新增表: {absent_added_files}")

    errors: list[str] = []
    verified = added = 0
    for path in sorted(set(original) & set(plugin)):
        table_errors, table_verified, table_added = compare_table(path, original[path], plugin[path])
        errors.extend(table_errors)
        verified += table_verified
        added += table_added

    for path, expected_count in SAMPLE_COUNTS.items():
        source = original.get(path)
        plugin_table = plugin.get(path)
        source_count = len(source) if isinstance(source, (list, dict)) else None
        plugin_count = len(plugin_table) if isinstance(plugin_table, (list, dict)) else None
        ok = source_count == expected_count and plugin_count == expected_count
        print(f"抽样 {path}: 原={source_count} 插件={plugin_count} 期望={expected_count} [{'OK' if ok else 'FAIL'}]")
        if not ok:
            errors.append(f"抽样表数量不符合锁定基线: {path}")

    errors.extend(f"缺少原版表: {path}" for path in missing)
    errors.extend(f"未登记插件新增表: {path}" for path in unexpected_added_files)
    errors.extend(f"登记但不存在的插件新增表: {path}" for path in absent_added_files)
    print(f"原版记录逐项核对: {verified} 条/表项 | 已登记新增记录: {added} 条")
    if errors:
        print(f"数据校验: FAIL（{len(errors)} 项）")
        for error in errors:
            print(f"- {error}")
        return 1
    print("数据校验: PASS（锁定原版数据保留，已登记插件扩展与文案差异均已核实）")
    return 0


if __name__ == "__main__":
    sys.exit(main())