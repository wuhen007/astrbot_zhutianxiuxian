"""沧澜界 · 彼岸世界/真世界：世界状态访问（SQLite 单例表）。

对应原版 ``model/otherShoreState.js`` 的 redis 锁 + 租约写文档流程。
插件无 redis / web session，改用 SQLite 单例表 ``other_shore_state``（单进程原子更新），
语义与 redis 租约一致：读写串行、写前整体读-改-写、写失败可整体重试。

惯例（与 infra/db.py 中 calamity/lingjie/ancient 单例一致）：
- 表 ``other_shore_state(id INTEGER PRIMARY KEY CHECK (id = 1), doc TEXT NOT NULL)``；
- 写入用 ``INSERT OR REPLACE``，commit 条件 ``owned = not self.conn.in_transaction``，
  否则踩 in_transaction 归属坑。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .other_shore_world import create_other_shore_world

OTHER_SHORE_STATE_TABLE = "other_shore_state"


async def read_other_shore_world(conn: Any) -> dict[str, Any] | None:
    assert conn is not None
    async with conn.execute(
        f"SELECT doc FROM {OTHER_SHORE_STATE_TABLE} WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    try:
        value = json.loads(row[0])
    except Exception:
        return None
    return value if isinstance(value, dict) else None


async def save_other_shore_world(conn: Any, doc: dict[str, Any]) -> None:
    assert conn is not None
    owned = not conn.in_transaction
    await conn.execute(
        f"INSERT OR REPLACE INTO {OTHER_SHORE_STATE_TABLE} (id, doc) VALUES (1, ?)",
        (json.dumps(doc, ensure_ascii=False),),
    )
    if owned:
        await conn.commit()


async def ensure_other_shore_world(conn: Any, seed: str = "canglan") -> dict[str, Any]:
    doc = await read_other_shore_world(conn)
    if doc:
        return doc
    created = create_other_shore_world(seed)
    await save_other_shore_world(conn, created)
    return created


async def update_other_shore_world(
    conn: Any,
    doc: dict[str, Any],
    updater: Callable[[dict[str, Any]], Any],
    *,
    attempts: int = 50,
    retry_delay: int = 10,
) -> tuple[dict[str, Any], Any]:
    """整体读-改-写，返回 (保存后的 doc, updater 的返回值)。

    单进程下以「读-改-写」保证一致性；失败可整体重试（对齐 redis 租约重试语义）。
    """
    for _ in range(max(1, int(attempts))):
        current = await read_other_shore_world(conn)
        if current is None:
            current = create_other_shore_world(str(doc.get("seed") or "canglan"))
        try:
            working = dict(current)
            value = updater(working)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"沧澜界状态更新失败：{exc}") from exc
        # updater 可就地修改 working，也可返回部分字段/新文档；dict 返回值合并进文档
        saved = {**working, **value} if isinstance(value, dict) else working
        await save_other_shore_world(conn, dict(saved))
        return dict(saved), value
    raise RuntimeError("沧澜界状态更新重试次数用尽")
