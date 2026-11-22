"""内容数据表加载器：扫描 data/ 下全部 JSON，建索引，缺表优雅降级。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from astrbot.api import logger

NAME_KEYS = ("level", "level_name", "name")


class ContentStore:
    """表名 = 相对路径去扩展名，如 'Level/练气境界'。

    值为原始 JSON（dict 或 list）。对元素含名称键的 list 表，
    额外建 名称→条目 索引，供指令按名字查询。
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.tables: dict[str, Any] = {}
        self.name_index: dict[str, dict[str, dict]] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.data_dir.exists():
            logger.warning(f"[zhutian] 数据目录不存在：{self.data_dir}")
            return
        for path in sorted(self.data_dir.rglob("*.json")):
            rel = path.relative_to(self.data_dir).with_suffix("").as_posix()
            try:
                with path.open("r", encoding="utf-8") as f:
                    self.tables[rel] = json.load(f)
            except Exception as e:
                logger.error(f"[zhutian] 加载 {rel} 失败，已跳过：{e}")

        for rel, table in self.tables.items():
            if not isinstance(table, list):
                continue
            index: dict[str, dict] = {}
            for entry in table:
                if isinstance(entry, dict):
                    for key in NAME_KEYS:
                        if key in entry:
                            index[str(entry[key])] = entry
                            break
            if index:
                self.name_index[rel] = index
        logger.info(f"[zhutian] 内容表加载完成：{len(self.tables)} 张（{self.data_dir}）")

    def table(self, name: str, default: Any = None) -> Any:
        """按全名查表（如 'Level/练气境界'）；找不到时按文件名后缀兜底。"""
        if name in self.tables:
            return self.tables[name]
        for rel, table in self.tables.items():
            if rel.split("/")[-1] == name.split("/")[-1]:
                return table
        return default if default is not None else ([])

    def by_name(self, table: str, name: str) -> dict | None:
        return self.name_index.get(table, {}).get(name)
