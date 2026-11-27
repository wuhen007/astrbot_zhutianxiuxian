"""SQLite 存储层：WAL + 版本化迁移 + 玩家文档读写。"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

LATEST_DB_VERSION = 20


def _shanghai_date_key(ts: float) -> str:
    """每日任务日期键：北京时间（UTC+8），与 core/clock.day_key 同一口径。

    不直接导入 core.clock：本模块会被 AstrBot 以包子模块、被 selfcheck 以
    顶层模块两种方式加载，跨包导入在后者会炸。
    """
    return time.strftime("%Y-%m-%d", time.gmtime(ts + 8 * 3600))


def _serialized(write_fn):
    """连接访问串行化；仅持锁协程可在事务内重入。

    aiosqlite 连接的事务状态属于整个连接，不能用 in_transaction 判断调用方
    是否处于该事务，否则其他协程会读到未提交数据或把写入并入该事务。
    """
    @functools.wraps(write_fn)
    async def wrapper(self, *args, **kwargs):
        assert self.conn is not None
        task = asyncio.current_task()
        if self._db_owner is task:
            return await write_fn(self, *args, **kwargs)
        async with self.wlock:
            if self.conn.in_transaction:   # 上次异常遗留的孤儿事务，清掉再写
                await self.conn.rollback()
            self._db_owner = task
            try:
                return await write_fn(self, *args, **kwargs)
            finally:
                self._db_owner = None
    return wrapper


class DataBase:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn: Optional[aiosqlite.Connection] = None
        self.wlock = asyncio.Lock()   # 全部写路径共用一把锁：命令并发时串行落库
        self._db_owner: asyncio.Task | None = None
        # 审计修复3：calamity_state 是全服单例整档覆盖，"读档→改→save_calamity"
        # 跨度必须持本锁，否则并发写入者互相回滚字段（护法/帝关/天地榜/战功）。
        self.calamity_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self._migrate()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    @_serialized
    async def get_combat_session(self, session_id: str) -> dict[str, Any] | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT payload FROM combat_sessions WHERE session_id = ?", (str(session_id),)
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    @_serialized
    async def find_active_combat_session(self, uid: str, now: float | None = None) -> dict[str, Any] | None:
        assert self.conn is not None
        now = time.time() if now is None else float(now)
        async with self.conn.execute(
            "SELECT payload FROM combat_sessions WHERE status = 'active' AND expires_at > ? "
            "AND (player_a = ? OR player_b = ?) ORDER BY updated_at DESC LIMIT 1",
            (now, str(uid), str(uid)),
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    @_serialized
    async def create_combat_session(self, doc: dict[str, Any]) -> tuple[bool, str | None]:
        """原子创建玩家切磋会话；任一参战者已有未过期会话时拒绝。"""
        assert self.conn is not None
        now = time.time()
        try:
            await self.conn.execute("BEGIN IMMEDIATE")
            async with self.conn.execute(
                "SELECT player_a, player_b FROM combat_sessions "
                "WHERE status='active' AND expires_at > ? AND "
                "(player_a IN (?, ?) OR player_b IN (?, ?)) LIMIT 1",
                (now, str(doc["player_a"]), str(doc["player_b"]),
                 str(doc["player_a"]), str(doc["player_b"]))
            ) as cur:
                active = await cur.fetchone()
            if active:
                await self.conn.rollback()
                occupied = next((uid for uid in (str(doc["player_a"]), str(doc["player_b"]))
                                 if uid in (str(active[0]), str(active[1]))), str(active[0]))
                return False, occupied
            await self.conn.execute(
                "INSERT INTO combat_sessions(session_id, platform_id, group_id, player_a, player_b, "
                "status, expires_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (str(doc["session_id"]), str(doc["platform_id"]), str(doc["group_id"]),
                 str(doc["player_a"]), str(doc["player_b"]), float(doc["expires_at"]), now,
                 json.dumps(doc, ensure_ascii=False)),
            )
            await self.conn.commit()
            return True, None
        except Exception:
            await self.conn.rollback()
            raise

    @_serialized
    async def save_combat_session(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        now = time.time()
        await self.conn.execute(
            "INSERT INTO combat_sessions(session_id, platform_id, group_id, player_a, player_b, "
            "status, expires_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET platform_id=excluded.platform_id, "
            "group_id=excluded.group_id, player_a=excluded.player_a, player_b=excluded.player_b, "
            "status=excluded.status, expires_at=excluded.expires_at, updated_at=excluded.updated_at, "
            "payload=excluded.payload",
            (str(doc["session_id"]), str(doc["platform_id"]), str(doc["group_id"]),
             str(doc["player_a"]), str(doc["player_b"]), str(doc.get("status", "active")),
             float(doc["expires_at"]), now, json.dumps(doc, ensure_ascii=False)),
        )
        await self.conn.commit()

    @_serialized
    async def due_combat_sessions(self, now: float | None = None) -> list[dict[str, Any]]:
        assert self.conn is not None
        now = time.time() if now is None else float(now)
        async with self.conn.execute(
            "SELECT payload FROM combat_sessions WHERE status='active' AND expires_at <= ?",
            (now,),
        ) as cur:
            return [json.loads(row[0]) for row in await cur.fetchall()]

    @_serialized
    async def expire_combat_sessions(self, now: float | None = None) -> list[dict[str, Any]]:
        assert self.conn is not None
        now = time.time() if now is None else float(now)
        async with self.conn.execute(
            "SELECT session_id, payload FROM combat_sessions WHERE status='active' AND expires_at <= ?",
            (now,),
        ) as cur:
            rows = await cur.fetchall()
        sessions = [json.loads(row[1]) for row in rows]
        if rows:
            await self.conn.executemany(
                "UPDATE combat_sessions SET status='expired', updated_at=? WHERE session_id=?",
                [(now, str(row[0])) for row in rows],
            )
            await self.conn.commit()
        return sessions

    @_serialized
    async def delete_combat_session(self, session_id: str) -> None:
        assert self.conn is not None
        await self.conn.execute("DELETE FROM combat_sessions WHERE session_id=?", (str(session_id),))
        await self.conn.commit()

    @staticmethod
    def _spar_session_record(duel: dict[str, Any], platform_id: str | None = None,
                             group_id: str | None = None) -> dict[str, Any]:
        record = dict(duel)
        record.update({
            "session_id": f"spar:{duel['id']}",
            "platform_id": str(platform_id if platform_id is not None else duel.get("platform_id", "unknown")),
            "group_id": str(group_id if group_id is not None else duel.get("group_id", "")),
            "player_a": str(duel["a"]["uid"]),
            "player_b": str(duel["b"]["uid"]),
            "status": "done" if duel.get("phase") == "done" else "active",
            "expires_at": float(duel.get("deadline", time.time())),
        })
        return record

    @_serialized
    async def get_spar(self, duel_id: str) -> dict[str, Any] | None:
        """Read a persisted duel, falling back to the pre-v20 table."""
        session = await self.get_combat_session(f"spar:{duel_id}")
        if session is not None:
            return session
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT doc FROM spar_duel WHERE id = ?", (str(duel_id),)
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def create_spar(self, duel: dict[str, Any], platform_id: str,
                          group_id: str = "") -> tuple[bool, str | None]:
        """Atomically create a multi-round duel, rejecting busy players."""
        return await self.create_combat_session(
            self._spar_session_record(duel, platform_id, group_id),
        )

    async def save_spar(self, duel: dict[str, Any]) -> None:
        """Persist an existing multi-round duel state and its current deadline."""
        await self.save_combat_session(self._spar_session_record(duel))

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """多语句事务；异常自动回滚。持写锁执行，期间其它写命令排队。"""
        assert self.conn is not None
        async with self.wlock:
            if self.conn.in_transaction:   # 上次异常遗留的孤儿事务，清掉再开
                await self.conn.rollback()
            await self.conn.execute("BEGIN")
            self._db_owner = asyncio.current_task()
            try:
                yield self.conn
            except Exception:
                await self.conn.rollback()
                raise
            else:
                await self.conn.commit()
            finally:
                self._db_owner = None

    async def _migrate(self) -> None:
        assert self.conn is not None
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS db_info (version INTEGER NOT NULL)"
        )
        async with self.conn.execute("SELECT version FROM db_info") as cur:
            row = await cur.fetchone()
        current = row[0] if row else None

        if current is None:
            async with self.transaction():
                await _v1_create(self.conn)
                await _v2_inventory(self.conn)  # 全新安装直接建到最新结构
                await _v3_world_boss(self.conn)
                await _v4_sects(self.conn)
                await _v5_auction(self.conn)
                await _v6_sect_score(self.conn)
                await _v7_daily_tasks(self.conn)
                await _v8_dark_boss(self.conn)
                await _v9_raid(self.conn)
                await _v10_rift(self.conn)
                await _v15_market(self.conn)
                await _v11_calamity(self.conn)
                await _v12_lingjie(self.conn)
                await _v13_ancient(self.conn)
                await _v14_other_shore(self.conn)
                await _v16_era(self.conn)
                await _v17_tianjiao_faction(self.conn)
                await _v18_qq_operations(self.conn)
                await _v19_spar_duel(self.conn)
                await _v20_combat_sessions(self.conn)
                await self.conn.execute("INSERT INTO db_info (version) VALUES (?)", (LATEST_DB_VERSION,))
            return

        # 后续版本在此登记：MIGRATIONS[n] = upgrade_fn
        MIGRATIONS = {2: _v2_inventory, 3: _v3_world_boss, 4: _v4_sects, 5: _v5_auction, 6: _v6_sect_score, 7: _v7_daily_tasks, 8: _v8_dark_boss, 9: _v9_raid, 10: _v10_rift, 11: _v11_calamity, 12: _v12_lingjie, 13: _v13_ancient, 14: _v14_other_shore, 15: _v15_market, 16: _v16_era, 17: _v17_tianjiao_faction, 18: _v18_qq_operations, 19: _v19_spar_duel, 20: _v20_combat_sessions}
        for version in sorted(v for v in MIGRATIONS if v > current):
            async with self.transaction():
                await MIGRATIONS[version](self.conn)
                await self.conn.execute("UPDATE db_info SET version = ?", (version,))

    # ---- 纳戒（背包）：以物品名为键，全部游戏操作均按名字进行 ----

    @_serialized
    async def register_qq_group(self, platform_id: str, group_id: str) -> None:
        assert self.conn is not None
        now = time.time()
        await self.conn.execute(
            "INSERT INTO qq_groups(platform_id, group_id, categories, registered_at, last_seen) "
            "VALUES (?, ?, '[]', ?, ?) ON CONFLICT(platform_id, group_id) "
            "DO UPDATE SET last_seen = excluded.last_seen",
            (str(platform_id), str(group_id), now, now),
        )
        await self.conn.commit()

    @_serialized
    async def set_qq_group(self, platform_id: str, group_id: str, categories: list[str]) -> None:
        assert self.conn is not None
        now = time.time()
        await self.conn.execute(
            "INSERT INTO qq_groups(platform_id, group_id, categories, registered_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(platform_id, group_id) DO UPDATE SET "
            "categories = excluded.categories, last_seen = excluded.last_seen",
            (str(platform_id), str(group_id), json.dumps(sorted(set(categories))), now, now),
        )
        await self.conn.commit()

    @_serialized
    async def qq_group_categories(self, platform_id: str, group_id: str) -> list[str] | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT categories FROM qq_groups WHERE platform_id = ? AND group_id = ?",
            (str(platform_id), str(group_id)),
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    @_serialized
    async def qq_subscribers(self, category: str) -> list[tuple[str, str]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT platform_id, group_id FROM qq_groups WHERE categories LIKE ?",
            (f'%"{category}"%',),
        ) as cur:
            return [(str(row[0]), str(row[1])) for row in await cur.fetchall()]

    @_serialized
    async def create_item_grant(self, grant_id: str, target_uid: str, item: str, qty: int,
                                issuer_uid: str, platform_id: str, group_id: str) -> None:
        assert self.conn is not None
        await self.conn.execute(
            "INSERT INTO item_grants(id, target_uid, item, qty, issuer_uid, platform_id, group_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (grant_id, str(target_uid), item, int(qty), str(issuer_uid), str(platform_id), str(group_id), time.time()),
        )
        await self.conn.commit()

    async def confirm_item_grant(self, grant_id: str, target_uid: str,
                                 platform_id: str, group_id: str) -> tuple[bool, str]:
        assert self.conn is not None
        async with self.transaction():
            async with self.conn.execute(
                "SELECT target_uid, platform_id, group_id, claim_uid, claimed_at FROM item_grants WHERE id = ?",
                (grant_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return False, "发放单不存在。"
            if str(row[0]) != str(target_uid) or str(row[1]) != str(platform_id) or str(row[2]) != str(group_id):
                return False, "只能由创建发放单所在群的目标玩家本人确认。"
            if row[4] is not None:
                return False, "此发放单已经领取。"
            if not row[3]:
                return False, "还没有待确认的私聊领取申请。"
            await self.conn.execute(
                "UPDATE item_grants SET confirmed_at = ? WHERE id = ? AND claimed_at IS NULL",
                (time.time(), grant_id),
            )
            return True, "已确认私聊领取申请，请申请人返回私聊发送「#领取发放 单号」完成领取。"

    async def claim_item_grant(self, grant_id: str, target_uid: str) -> tuple[bool, str]:
        assert self.conn is not None
        async with self.transaction():
            async with self.conn.execute(
                "SELECT target_uid, item, qty, claimed_at, claim_uid, confirmed_at "
                "FROM item_grants WHERE id = ?", (grant_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return False, "发放单不存在。"
            if row[3] is not None:
                return False, "此发放单已经领取。"
            if str(row[0]) != str(target_uid):
                if str(row[4] or "") != str(target_uid) or row[5] is None:
                    await self.conn.execute(
                        "UPDATE item_grants SET claim_uid = ?, confirmed_at = NULL WHERE id = ?",
                        (str(target_uid), grant_id),
                    )
                    return False, "已登记私聊领取申请。请只在本人刚刚发起申请时回到发放单所在群，由被 @ 的账号发送「#确认发放 单号」；确认后再私聊领取。"
            reward_uid = str(row[0])
            raw = await self.get_player(reward_uid)
            if not raw:
                return False, "请先私聊机器人踏入仙途，再领取发放。"
            if row[1] == "灵石":
                raw["stones"] = int(raw.get("stones", 0) or 0) + int(row[2])
                await self.save_player(raw)
            else:
                await self.add_items(reward_uid, {str(row[1]): int(row[2])})
            await self.conn.execute(
                "UPDATE item_grants SET claimed_at = ? WHERE id = ? AND claimed_at IS NULL",
                (time.time(), grant_id),
            )
            return True, str(row[1])

    @_serialized
    async def get_inventory(self, uid: str) -> dict[str, int]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT item, qty FROM inventory WHERE uid = ? ORDER BY qty DESC", (uid,)
        ) as cur:
            return {row[0]: row[1] for row in await cur.fetchall()}

    @_serialized
    async def add_items(self, uid: str, items: dict[str, int]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        for name, qty in items.items():
            if qty <= 0:
                continue
            await self.conn.execute(
                "INSERT INTO inventory (uid, item, qty) VALUES (?, ?, ?) "
                "ON CONFLICT(uid, item) DO UPDATE SET qty = qty + excluded.qty",
                (uid, name, qty),
            )
        if owned:
            await self.conn.commit()

    @_serialized
    async def remove_item(self, uid: str, item: str, qty: int) -> bool:
        """数量不足返回 False（调用方负责回滚或提示）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "UPDATE inventory SET qty = qty - ? WHERE uid = ? AND item = ? AND qty >= ?",
            (qty, uid, item, qty),
        )
        if cur.rowcount == 0:
            if owned:
                await self.conn.rollback()
            return False
        await self.conn.execute(
            "DELETE FROM inventory WHERE uid = ? AND item = ? AND qty <= 0", (uid, item)
        )
        if owned:
            await self.conn.commit()
        return True

    @_serialized
    async def purge_inventory_row(self, uid: str, item: str) -> bool:
        """整行删除（用于清理数量非法/为负的脏条目，remove_item 会因 qty 校验拒绝）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "DELETE FROM inventory WHERE uid = ? AND item = ?", (uid, item))
        if owned:
            await self.conn.commit()
        return cur.rowcount > 0

    # ---- 玩家文档 ----

    async def delete_player_bundle(self, uid: str) -> None:
        """W33c：再入仙途——删除玩家全部档案行（players/inventory/daily_tasks/
        boss_ledger/dark_ledger/raid_member）。全局单例与队伍表不动。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        for table in ("players", "inventory", "daily_tasks", "boss_ledger",
                      "dark_ledger", "raid_member"):
            await self.conn.execute(f"DELETE FROM {table} WHERE uid = ?", (uid,))
        if owned:
            await self.conn.commit()

    @_serialized
    async def get_player(self, uid: str) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM players WHERE uid = ?", (uid,)) as cur:
            row = await cur.fetchone()
            return json.loads(row[0]) if row else None

    @_serialized
    async def save_player(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        # sqlite3 会在 DML 时隐式开启事务：execute 前无事务 = 本方法拥有它，负责提交；
        # 已处于外层 transaction() 中则只写不提交，由外层统一提交/回滚。
        owned = not self.conn.in_transaction
        async with self.conn.execute(
            "SELECT doc FROM players WHERE uid = ?", (doc["uid"],)
        ) as cur:
            old_row = await cur.fetchone()
        await self.conn.execute(
            "INSERT INTO players (uid, doc, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(uid) DO UPDATE SET doc = excluded.doc, updated_at = excluded.updated_at",
            (doc["uid"], json.dumps(doc, ensure_ascii=False), time.time()),
        )
        # 每日任务灵石追踪：新旧灵石差值自动入账（原版 Add_灵石 trackDailyTask 方案的落库点等价实现）
        if old_row:
            try:
                old_stones = int(json.loads(old_row[0]).get("stones", 0) or 0)
            except (ValueError, TypeError):
                old_stones = 0
            delta = int(doc.get("stones", 0) or 0) - old_stones
            if delta:
                await self.track_task_stones(doc["uid"], delta)
        if owned:
            await self.conn.commit()

    # ---- 每日任务 ----

    @_serialized
    async def get_daily_task(self, uid: str) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT uid, level, exp, w1, w2, w3, j1, j2, j3, renwu, date, gained, spent"
            " FROM daily_tasks WHERE uid = ?", (uid,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            keys = ("uid", "level", "exp", "w1", "w2", "w3", "j1", "j2", "j3",
                    "renwu", "date", "gained", "spent")
            return dict(zip(keys, row))

    @_serialized
    async def upsert_daily_task(self, rec: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT INTO daily_tasks (uid, level, exp, w1, w2, w3, j1, j2, j3,"
            " renwu, date, gained, spent)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(uid) DO UPDATE SET level = excluded.level, exp = excluded.exp,"
            " w1 = excluded.w1, w2 = excluded.w2, w3 = excluded.w3,"
            " j1 = excluded.j1, j2 = excluded.j2, j3 = excluded.j3,"
            " renwu = excluded.renwu, date = excluded.date,"
            " gained = excluded.gained, spent = excluded.spent",
            (rec["uid"], rec.get("level", 1), rec.get("exp", 0),
             rec.get("w1", 0), rec.get("w2", 0), rec.get("w3", 0),
             rec.get("j1", 0), rec.get("j2", 0), rec.get("j3", 0),
             rec.get("renwu", 0), rec.get("date", ""),
             rec.get("gained", 0), rec.get("spent", 0)),
        )
        if owned:
            await self.conn.commit()

    async def track_task_stones(self, uid: str, delta: int) -> None:
        """灵石差值入任务进度：仅当日已接取且对应任务进行中时累计。"""
        assert self.conn is not None
        gained = delta if delta > 0 else 0
        spent = -delta if delta < 0 else 0
        await self.conn.execute(
            "UPDATE daily_tasks SET gained = gained + ?, spent = spent + ?"
            " WHERE uid = ? AND date = ? AND (w1 = 1 OR w2 = 1)",
            (gained, spent, uid, _shanghai_date_key(time.time())),
        )

    @_serialized
    async def add_daily_secret(self, uid: str) -> bool:
        """秘境探索次数 +1（任务 3 进行中才计数）。返回是否计入。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "UPDATE daily_tasks SET j3 = j3 + 1"
            " WHERE uid = ? AND date = ? AND w3 = 1",
            (uid, _shanghai_date_key(time.time())),
        )
        if owned:
            await self.conn.commit()
        return cur.rowcount > 0


    # ---- 黑暗动乱帝战 ----

    @_serialized
    async def get_dark_boss(self) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT round, health, health_max, reward, atk, defense, alive, killed_at"
            " FROM dark_boss WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "round": row[0], "health": row[1], "health_max": row[2],
                "reward": row[3], "atk": row[4], "defense": row[5],
                "alive": bool(row[6]), "killed_at": row[7],
            }

    @_serialized
    async def init_dark_boss(self, round_no: int, health: int, reward: int,
                             atk: int, defense: int) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT INTO dark_boss (id, round, health, health_max, reward, atk, defense, alive, killed_at)"
            " VALUES (1, ?, ?, ?, ?, ?, ?, 1, -1)"
            " ON CONFLICT(id) DO UPDATE SET round = excluded.round, health = excluded.health,"
            " health_max = excluded.health_max, reward = excluded.reward, atk = excluded.atk,"
            " defense = excluded.defense, alive = 1, killed_at = -1",
            (round_no, health, health, reward, atk, defense),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def damage_dark_boss(self, round_no: int, uid: str, name: str, dmg: int) -> int:
        """对黑暗 Boss 扣血并记账。返回剩余血量（≤0 = 已被击杀）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "UPDATE dark_boss SET health = health - ? WHERE id = 1 AND alive = 1", (dmg,)
        )
        await self.conn.execute(
            "INSERT INTO dark_ledger (boss_round, uid, name, damage) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(boss_round, uid) DO UPDATE SET"
            " damage = damage + excluded.damage, name = excluded.name",
            (round_no, uid, name, dmg),
        )
        async with self.conn.execute("SELECT health FROM dark_boss WHERE id = 1") as cur:
            left = (await cur.fetchone())[0]
        if left <= 0:
            await self.conn.execute(
                "UPDATE dark_boss SET health = 0, alive = 0, killed_at = ? WHERE id = 1",
                (time.time(),),
            )
        if owned:
            await self.conn.commit()
        return left

    @_serialized
    async def dark_ledger(self, round_no: int) -> dict[str, tuple[str, int]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT uid, name, damage FROM dark_ledger WHERE boss_round = ? ORDER BY damage DESC",
            (round_no,),
        ) as cur:
            return {row[0]: (row[1], row[2]) for row in await cur.fetchall()}

    # ---- 裂界副本：全服单例状态（当前裂界 + 锚定度 + 贡献） ----

    @_serialized
    async def get_market(self) -> dict[str, Any]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM market_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_market(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO market_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def get_era(self) -> dict[str, Any]:
        """世界时代单例（五时代轮转 / 历法 / 出金率）。缺表或空档返回 {}。"""
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM era_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_era(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO era_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def get_tianjiao(self) -> dict[str, Any]:
        """位面天骄共享状态（血条 / 轮回 / 贡献榜）。"""
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM tianjiao_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_tianjiao(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO tianjiao_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def get_faction(self) -> dict[str, Any]:
        """势力全服状态（等级 / 成员 / 贡献）。"""
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM faction_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_faction(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO faction_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def get_rift(self) -> dict[str, Any]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM rift_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_rift(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO rift_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    # ---- 千年灾劫：全服单例状态（灾厄列表 + 魔主 + 纪元） ----

    @_serialized
    async def get_calamity(self) -> dict[str, Any]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM calamity_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_calamity(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO calamity_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    # ---- 灵界裂缝：全服单例状态（现世裂缝 + 探索任务 + 界印记录） ----

    @_serialized
    async def get_lingjie(self) -> dict[str, Any]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM lingjie_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_lingjie(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO lingjie_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    # ---- 彼岸古文明：全服单例状态（四章贡献链） ----

    @_serialized
    async def get_ancient(self) -> dict[str, Any]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM ancient_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_ancient(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO ancient_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    # ---- 彼岸世界/真世界：全服单例状态（世界 + 星辰 + 路径） ----

    @_serialized
    async def get_other_shore(self) -> dict[str, Any]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM other_shore_state WHERE id = 1") as cur:
            row = await cur.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0]) or {}
        except Exception:
            return {}

    @_serialized
    async def save_other_shore(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO other_shore_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def all_player_uids(self) -> list[str]:
        assert self.conn is not None
        async with self.conn.execute("SELECT uid FROM players") as cur:
            return [row[0] for row in await cur.fetchall()]

    # ---- 团本讨伐 ----

    @staticmethod
    def _raid_row(row: Any) -> dict[str, Any] | None:
        if not row:
            return None
        keys = ("code", "boss", "leader_uid", "leader_name", "hp", "hp_max", "atk",
                "defense", "reward", "status", "created_at", "finished_at", "settled", "killer_uid")
        d = dict(zip(keys, row))
        d["settled"] = bool(d["settled"])
        return d

    @_serialized
    async def create_raid(self, code: str, boss: str, leader_uid: str,
                          leader_name: str, now: float) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT INTO raid_team (code, boss, leader_uid, leader_name, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (code, boss, leader_uid, leader_name, now),
        )
        await self.conn.execute(
            "INSERT OR IGNORE INTO raid_member (code, uid, name, joined_at) VALUES (?, ?, ?, ?)",
            (code, leader_uid, leader_name, now),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def get_raid(self, code: str) -> dict[str, Any] | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT code, boss, leader_uid, leader_name, hp, hp_max, atk, defense,"
            " reward, status, created_at, finished_at, settled, killer_uid FROM raid_team WHERE code = ?",
            (str(code),),
        ) as cur:
            return self._raid_row(await cur.fetchone())

    @_serialized
    async def active_raid_of(self, uid: str) -> dict[str, Any] | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT t.code, t.boss, t.leader_uid, t.leader_name, t.hp, t.hp_max, t.atk,"
            " t.defense, t.reward, t.status, t.created_at, t.finished_at, t.settled, t.killer_uid"
            " FROM raid_team t JOIN raid_member m ON m.code = t.code"
            " WHERE m.uid = ? AND t.status IN ('recruiting', 'fighting')"
            " ORDER BY t.created_at DESC LIMIT 1",
            (uid,),
        ) as cur:
            return self._raid_row(await cur.fetchone())

    @_serialized
    async def last_raid_of(self, uid: str) -> dict[str, Any] | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT t.code, t.boss, t.leader_uid, t.leader_name, t.hp, t.hp_max, t.atk,"
            " t.defense, t.reward, t.status, t.created_at, t.finished_at, t.settled, t.killer_uid"
            " FROM raid_team t JOIN raid_member m ON m.code = t.code"
            " WHERE m.uid = ? ORDER BY t.created_at DESC LIMIT 1",
            (uid,),
        ) as cur:
            return self._raid_row(await cur.fetchone())

    @_serialized
    async def raid_members(self, code: str) -> list[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT uid, name, dmg, hits_today, hits_day, last_ts, joined_at"
            " FROM raid_member WHERE code = ? ORDER BY dmg DESC, joined_at ASC",
            (str(code),),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {"uid": r[0], "name": r[1], "dmg": r[2], "hits_today": r[3],
             "hits_day": r[4], "last_ts": r[5], "joined_at": r[6]}
            for r in rows
        ]

    @_serialized
    async def raid_member(self, code: str, uid: str) -> dict[str, Any] | None:
        for m in await self.raid_members(code):
            if m["uid"] == uid:
                return m
        return None

    @_serialized
    async def join_raid(self, code: str, uid: str, name: str, now: float) -> bool:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO raid_member (code, uid, name, joined_at) VALUES (?, ?, ?, ?)",
            (str(code), uid, name, now),
        )
        ok = cur.rowcount > 0
        if owned:
            await self.conn.commit()
        return ok

    @_serialized
    async def start_raid(self, code: str, stats: dict[str, int]) -> bool:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "UPDATE raid_team SET status = 'fighting', hp = ?, hp_max = ?, atk = ?,"
            " defense = ?, reward = ? WHERE code = ? AND status = 'recruiting'",
            (stats["hp"], stats["hp_max"], stats["atk"], stats["defense"],
             stats["reward"], str(code)),
        )
        ok = cur.rowcount > 0
        if owned:
            await self.conn.commit()
        return ok

    @_serialized
    async def damage_raid(self, code: str, uid: str, dmg: int, day: str, now: float) -> int:
        """扣 Boss 血 + 记成员伤害/次数，原子完成。返回剩余血量（≤0 = 击杀）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "UPDATE raid_member SET dmg = dmg + ?,"
            " hits_today = CASE WHEN hits_day = ? THEN hits_today + 1 ELSE 1 END,"
            " hits_day = ?, last_ts = ? WHERE code = ? AND uid = ?",
            (int(dmg), day, day, float(now), str(code), uid),
        )
        await self.conn.execute(
            "UPDATE raid_team SET hp = MAX(0, hp - ?) WHERE code = ? AND status = 'fighting'",
            (int(dmg), str(code)),
        )
        async with self.conn.execute(
            "SELECT hp FROM raid_team WHERE code = ?", (str(code),)
        ) as cur:
            row = await cur.fetchone()
        left = int(row[0]) if row else 0
        if left <= 0:
            await self.conn.execute(
                "UPDATE raid_team SET hp = 0, status = 'victory', finished_at = ?, killer_uid = ?"
                " WHERE code = ? AND status = 'fighting'",
                (float(now), uid, str(code)),
            )
        if owned:
            await self.conn.commit()
        return left

    @_serialized
    async def close_raid(self, code: str, status: str, now: float) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "UPDATE raid_team SET status = ?, finished_at = ?"
            " WHERE code = ? AND status IN ('recruiting', 'fighting')",
            (status, float(now), str(code)),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def mark_raid_settled(self, code: str) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "UPDATE raid_team SET settled = 1 WHERE code = ?", (str(code),)
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def leave_raid(self, code: str, uid: str) -> bool:
        """W8-D4 #离开队伍：退队不删队伍（队长须先 #解散队伍，接线层判断）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "DELETE FROM raid_member WHERE code = ? AND uid = ?",
            (str(code), str(uid)),
        )
        ok = cur.rowcount > 0
        if owned:
            await self.conn.commit()
        return ok

    @_serialized
    async def settle_raid_battle(self, code: str, damage: dict[str, int],
                                 hp: int, status: str, now: float) -> None:
        """W8-D4 帝尊战一次性落库：成员伤害账本 + 队伍血条/终局态。

        不用 damage_raid：后者会在 hp<=0 时立刻置 victory，而帝尊有
        者字秘·极尽二阶段（中途血空要复活），必须等 run_raid 结算完再落。
        """
        assert self.conn is not None
        owned = not self.conn.in_transaction
        for uid, dmg in damage.items():
            await self.conn.execute(
                "UPDATE raid_member SET dmg = dmg + ? WHERE code = ? AND uid = ?",
                (int(dmg), str(code), str(uid)),
            )
        await self.conn.execute(
            "UPDATE raid_team SET hp = ?, status = ?, finished_at = ?, settled = ?"
            " WHERE code = ? AND status = 'fighting'",
            (max(0, int(hp)), str(status), float(now), 1 if status == "victory" else 0,
             str(code)),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def close_all_raids(self, now: float, status: str = "closed") -> int:
        """W8-D4 #关闭所有讨伐：收掉所有招募中 / 讨伐中的队伍。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "UPDATE raid_team SET status = ?, finished_at = ?"
            " WHERE status IN ('recruiting', 'fighting')",
            (str(status), float(now)),
        )
        n = int(cur.rowcount or 0)
        if owned:
            await self.conn.commit()
        return n

    @_serialized
    async def list_raids(self, status: str = "recruiting", limit: int = 10) -> list[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT code, boss, leader_uid, leader_name, hp, hp_max, atk, defense,"
            " reward, status, created_at, finished_at, settled, killer_uid FROM raid_team"
            " WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, int(limit)),
        ) as cur:
            rows = await cur.fetchall()
        return [d for d in (self._raid_row(r) for r in rows) if d]

    @_serialized
    async def raid_member_count(self, code: str) -> int:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT COUNT(*) FROM raid_member WHERE code = ?", (str(code),)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---- 世界 Boss ----


    @_serialized
    async def get_boss(self) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT round, health, health_max, reward, alive, killed_at FROM world_boss WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "round": row[0], "health": row[1], "health_max": row[2],
                "reward": row[3], "alive": bool(row[4]), "killed_at": row[5],
            }

    @_serialized
    async def init_boss(self, round_no: int, health: int, reward: int) -> None:
        """创建/重置第 round_no 轮 Boss（单行 UPSERT）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT INTO world_boss (id, round, health, health_max, reward, alive, killed_at)"
            " VALUES (1, ?, ?, ?, ?, 1, -1)"
            " ON CONFLICT(id) DO UPDATE SET round = excluded.round, health = excluded.health,"
            " health_max = excluded.health_max, reward = excluded.reward, alive = 1, killed_at = -1",
            (round_no, health, health, reward),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def damage_boss(self, round_no: int, uid: str, name: str, dmg: int) -> int:
        """对 Boss 扣血并记账。返回 Boss 剩余血量（≤0 = 已被击杀）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "UPDATE world_boss SET health = health - ? WHERE id = 1 AND alive = 1", (dmg,)
        )
        await self.conn.execute(
            "INSERT INTO boss_ledger (boss_round, uid, name, damage) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(boss_round, uid) DO UPDATE SET"
            " damage = damage + excluded.damage, name = excluded.name",
            (round_no, uid, name, dmg),
        )
        async with self.conn.execute("SELECT health FROM world_boss WHERE id = 1") as cur:
            left = (await cur.fetchone())[0]
        if left <= 0:
            await self.conn.execute(
                "UPDATE world_boss SET health = 0, alive = 0, killed_at = ? WHERE id = 1",
                (time.time(),),
            )
        if owned:
            await self.conn.commit()
        return left

    @_serialized
    async def boss_ledger(self, round_no: int) -> dict[str, tuple[str, int]]:
        """某轮贡献账本：uid → (名字, 累计伤害)，按伤害降序。"""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT uid, name, damage FROM boss_ledger WHERE boss_round = ? ORDER BY damage DESC",
            (round_no,),
        ) as cur:
            return {r[0]: (r[1], r[2]) for r in await cur.fetchall()}


    # ---- 宗门 ----

    @_serialized
    async def get_sect(self, name: str) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT name, master_uid, level, fund, created_at, score FROM sects WHERE name = ?", (name,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "name": row[0], "master_uid": row[1], "level": row[2],
                "fund": row[3], "created_at": row[4], "score": row[5],
            }

    @_serialized
    async def create_sect(self, name: str, master_uid: str, now: float) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT INTO sects (name, master_uid, level, fund, created_at) VALUES (?, ?, 1, 0, ?)",
            (name, master_uid, now),
        )
        if owned:
            await self.conn.commit()

    @_serialized
    async def update_sect(self, name: str, level: int, fund: int, master_uid: str | None = None) -> None:
        """宗门更新；master_uid 传 None 表示不变。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        if master_uid is None:
            await self.conn.execute(
                "UPDATE sects SET level = ?, fund = ? WHERE name = ?", (level, fund, name)
            )
        else:
            await self.conn.execute(
                "UPDATE sects SET level = ?, fund = ?, master_uid = ? WHERE name = ?",
                (level, fund, master_uid, name),
            )
        if owned:
            await self.conn.commit()

    @_serialized
    async def delete_sect(self, name: str) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute("DELETE FROM sects WHERE name = ?", (name,))
        if owned:
            await self.conn.commit()

    @_serialized
    async def all_sects(self) -> list[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT name, master_uid, level, fund, created_at, score FROM sects"
            " ORDER BY score DESC, level DESC, fund DESC"
        ) as cur:
            return [
                {"name": r[0], "master_uid": r[1], "level": r[2], "fund": r[3],
                 "created_at": r[4], "score": r[5]}
                for r in await cur.fetchall()
            ]

    @_serialized
    async def add_sect_score(self, name: str, delta: int) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute("UPDATE sects SET score = score + ? WHERE name = ?", (delta, name))
        if owned:
            await self.conn.commit()

    @_serialized
    async def all_players(self) -> list[dict[str, Any]]:
        """遍历玩家文档（排行用；群服规模下可接受全扫）。"""
        assert self.conn is not None
        async with self.conn.execute("SELECT uid, doc FROM players") as cur:
            return [{"uid": r[0], **json.loads(r[1])} for r in await cur.fetchall()]

    # ---- W8-F1 超管：删档 / 备份 / 诸天初始化 ----

    @_serialized
    async def delete_player(self, uid: str) -> bool:
        """彻底删档：玩家文档 + 纳戒。返回是否真的删到了东西。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute("DELETE FROM players WHERE uid = ?", (str(uid),))
        await self.conn.execute("DELETE FROM inventory WHERE uid = ?", (str(uid),))
        await self.conn.execute("DELETE FROM daily_tasks WHERE uid = ?", (str(uid),))
        if owned:
            await self.conn.commit()
        return cur.rowcount > 0

    @_serialized
    async def all_auctions(self) -> list[dict[str, Any]]:
        """全量拍卖挂单（超管清场用）。"""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT id, seller_uid, seller_name, item, qty, price, listed_at"
            " FROM auction ORDER BY id"
        ) as cur:
            return [{"id": r[0], "seller_uid": r[1], "seller_name": r[2],
                     "item": r[3], "qty": r[4], "price": r[5], "listed_at": r[6]}
                    for r in await cur.fetchall()]

    @_serialized
    async def wipe_all(self, tables: tuple[str, ...]) -> dict[str, int]:
        """诸天初始化：清空给定表的全部行（db_info 不传即不动版本号）。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        counts: dict[str, int] = {}
        for table in tables:
            async with self.conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                counts[table] = int((await cur.fetchone())[0])
            await self.conn.execute(f"DELETE FROM {table}")
        if owned:
            await self.conn.commit()
        return counts

    async def backup_to(self, path: Path) -> Path:
        """一致性快照（VACUUM INTO）；同名文件已存在时自动加序号，不覆盖旧备份。

        返回实际落盘路径（可能带 -1/-2 后缀），调用方据此回报文件名。
        """
        assert self.conn is not None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stem, suffix = path.stem, path.suffix
            for i in range(1, 100):
                cand = path.with_name(f"{stem}-{i}{suffix}")
                if not cand.exists():
                    path = cand
                    break
        async with self.wlock:
            if self.conn.in_transaction:
                await self.conn.rollback()
            await self.conn.execute("VACUUM INTO ?", (str(path),))
        return path


    # ---- 拍卖行（寄售制，物品托管） ----

    @_serialized
    async def list_auction(
        self, seller_uid: str, seller_name: str, item: str, qty: int, price: int
    ) -> int:
        """挂单。返回单号。"""
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute(
            "INSERT INTO auction (seller_uid, seller_name, item, qty, price, listed_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (seller_uid, seller_name, item, qty, price, time.time()),
        )
        if owned:
            await self.conn.commit()
        return cur.lastrowid

    @_serialized
    async def get_auction(self, lot_id: int) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT id, seller_uid, seller_name, item, qty, price, listed_at"
            " FROM auction WHERE id = ?", (lot_id,)
        ) as cur:
            r = await cur.fetchone()
            if not r:
                return None
            return {"id": r[0], "seller_uid": r[1], "seller_name": r[2],
                    "item": r[3], "qty": r[4], "price": r[5], "listed_at": r[6]}

    @_serialized
    async def auction_page(self, page: int, per: int = 8) -> tuple[list[dict], int]:
        assert self.conn is not None
        async with self.conn.execute("SELECT COUNT(*) FROM auction") as cur:
            total = (await cur.fetchone())[0]
        pages = max(1, -(-total // per))
        page = min(max(1, page), pages)
        async with self.conn.execute(
            "SELECT id, seller_name, item, qty, price FROM auction"
            " ORDER BY id LIMIT ? OFFSET ?", (per, (page - 1) * per),
        ) as cur:
            rows = [
                {"id": r[0], "seller_name": r[1], "item": r[2], "qty": r[3], "price": r[4]}
                for r in await cur.fetchall()
            ]
        return rows, pages

    @_serialized
    async def delete_auction(self, lot_id: int) -> bool:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute("DELETE FROM auction WHERE id = ?", (lot_id,))
        if owned:
            await self.conn.commit()
        return cur.rowcount > 0

    @_serialized
    async def my_auctions(self, uid: str) -> list[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT id, item, qty, price FROM auction WHERE seller_uid = ? ORDER BY id", (uid,)
        ) as cur:
            return [{"id": r[0], "item": r[1], "qty": r[2], "price": r[3]} for r in await cur.fetchall()]


async def _v1_create(conn: aiosqlite.Connection) -> None:
    """玩家以 JSON 文档主存；结构性查询需求（背包/账本）在后续版本加关系表。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS players ("
        " uid TEXT PRIMARY KEY, doc TEXT NOT NULL, updated_at REAL NOT NULL)"
    )


async def _v2_inventory(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS inventory ("
        " uid TEXT NOT NULL, item TEXT NOT NULL, qty INTEGER NOT NULL,"
        " PRIMARY KEY (uid, item))"
    )


async def _v3_world_boss(conn: aiosqlite.Connection) -> None:
    """世界 Boss：单行共享实体 + 伤害贡献账本（击杀后按贡献分奖池）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS world_boss ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " round INTEGER NOT NULL, health INTEGER NOT NULL, health_max INTEGER NOT NULL,"
        " reward INTEGER NOT NULL, alive INTEGER NOT NULL, killed_at REAL NOT NULL)"
    )
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS boss_ledger ("
        " boss_round INTEGER NOT NULL, uid TEXT NOT NULL, name TEXT NOT NULL,"
        " damage INTEGER NOT NULL, PRIMARY KEY (boss_round, uid))"
    )


async def _v4_sects(conn: aiosqlite.Connection) -> None:
    """宗门：名称主键共享实体；成员关系存玩家文档 ext["sect"]。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS sects ("
        " name TEXT PRIMARY KEY, master_uid TEXT NOT NULL, level INTEGER NOT NULL,"
        " fund INTEGER NOT NULL, created_at REAL NOT NULL)"
    )


async def _v5_auction(conn: aiosqlite.Connection) -> None:
    """拍卖行：寄售挂单，物品上架即托管。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS auction ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " seller_uid TEXT NOT NULL, seller_name TEXT NOT NULL,"
        " item TEXT NOT NULL, qty INTEGER NOT NULL, price INTEGER NOT NULL,"
        " listed_at REAL NOT NULL)"
    )


async def _v6_sect_score(conn: aiosqlite.Connection) -> None:
    """宗门挑战积分。"""
    await conn.execute("ALTER TABLE sects ADD COLUMN score INTEGER NOT NULL DEFAULT 0")


async def _v7_daily_tasks(conn: aiosqlite.Connection) -> None:
    """每日任务（对齐原版 meirrenwu：三任务 + 任务等级/经验 + 领奖状态）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_tasks ("
        " uid TEXT PRIMARY KEY,"
        " level INTEGER NOT NULL DEFAULT 1,"    # 任务等级
        " exp INTEGER NOT NULL DEFAULT 0,"       # 任务经验（升级用）
        " w1 INTEGER NOT NULL DEFAULT 0,"        # 任务1 消耗灵石：0未接 1进行中 2完成
        " w2 INTEGER NOT NULL DEFAULT 0,"        # 任务2 获取灵石
        " w3 INTEGER NOT NULL DEFAULT 0,"        # 任务3 秘境次数
        " j1 INTEGER NOT NULL DEFAULT 0,"        # 进度：今日累计消耗灵石
        " j2 INTEGER NOT NULL DEFAULT 0,"        # 进度：今日累计获取灵石
        " j3 INTEGER NOT NULL DEFAULT 0,"        # 进度：秘境次数
        " renwu INTEGER NOT NULL DEFAULT 0,"     # 0未提交 1全部完成待领奖 2已领奖
        " date TEXT NOT NULL DEFAULT '',"        # 接取日期键（上海时区）
        " gained INTEGER NOT NULL DEFAULT 0,"    # 今日灵石获取滚动累计（提交时并入 j2）
        " spent INTEGER NOT NULL DEFAULT 0)"     # 今日灵石消耗滚动累计（提交时并入 j1）
    )


async def _v8_dark_boss(conn: aiosqlite.Connection) -> None:
    """黑暗动乱帝战（对齐原版 BOSS2：单行状态 + 贡献账本，结构同 world_boss）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS dark_boss ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " round INTEGER NOT NULL,"
        " health INTEGER NOT NULL,"
        " health_max INTEGER NOT NULL,"
        " reward INTEGER NOT NULL,"
        " atk INTEGER NOT NULL DEFAULT 0,"
        " defense INTEGER NOT NULL DEFAULT 0,"
        " alive INTEGER NOT NULL DEFAULT 1,"
        " killed_at REAL NOT NULL DEFAULT -1)"
    )
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS dark_ledger ("
        " boss_round INTEGER NOT NULL,"
        " uid TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " damage INTEGER NOT NULL,"
        " PRIMARY KEY (boss_round, uid))"
    )


async def _v9_raid(conn: aiosqlite.Connection) -> None:
    """团本讨伐：队伍 + 成员伤害账本（对齐原版 tuanben/TeamBoss 的 5 人共享血条）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS raid_team ("
        " code TEXT PRIMARY KEY,"
        " boss TEXT NOT NULL,"
        " leader_uid TEXT NOT NULL,"
        " leader_name TEXT NOT NULL DEFAULT '',"
        " hp INTEGER NOT NULL DEFAULT 0,"
        " hp_max INTEGER NOT NULL DEFAULT 0,"
        " atk INTEGER NOT NULL DEFAULT 0,"
        " defense INTEGER NOT NULL DEFAULT 0,"
        " reward INTEGER NOT NULL DEFAULT 0,"
        " status TEXT NOT NULL DEFAULT 'recruiting',"
        " created_at REAL NOT NULL,"
        " finished_at REAL NOT NULL DEFAULT 0,"
        " settled INTEGER NOT NULL DEFAULT 0,"
        " killer_uid TEXT NOT NULL DEFAULT '')"
    )
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS raid_member ("
        " code TEXT NOT NULL,"
        " uid TEXT NOT NULL,"
        " name TEXT NOT NULL DEFAULT '',"
        " dmg INTEGER NOT NULL DEFAULT 0,"
        " hits_today INTEGER NOT NULL DEFAULT 0,"
        " hits_day TEXT NOT NULL DEFAULT '',"
        " last_ts REAL NOT NULL DEFAULT 0,"
        " joined_at REAL NOT NULL,"
        " PRIMARY KEY (code, uid))"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_raid_member_uid ON raid_member(uid)"
    )


async def _v10_rift(conn: aiosqlite.Connection) -> None:
    """裂界副本：全服共享裂界状态（单例 JSON，窗口轮换 + 锚定度 + 贡献账本）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS rift_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v13_ancient(conn: aiosqlite.Connection) -> None:
    """彼岸古文明：全服单例状态（四章贡献链 + 领取记录）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS ancient_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v11_calamity(conn: aiosqlite.Connection) -> None:
    """千年灾劫·域外来敌：全服单例状态（灾厄列表 + 魔主 + 纪元）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS calamity_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v12_lingjie(conn: aiosqlite.Connection) -> None:
    """凡间限时副本·灵界裂缝：全服单例状态（现世裂缝 + 探索任务）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS lingjie_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v14_other_shore(conn: aiosqlite.Connection) -> None:
    """彼岸世界/真世界：全服单例状态（世界 + 星辰 + 探索）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS other_shore_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )




async def _v15_market(conn: aiosqlite.Connection) -> None:
    """万界灵市：全服共享市场状态（单例 JSON，确定性 PRNG 行情）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS market_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v16_era(conn: aiosqlite.Connection) -> None:
    """时代系统：全服唯一的世界历法（五时代轮转 + 秘境出金率）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS era_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v17_tianjiao_faction(conn: aiosqlite.Connection) -> None:
    """位面天骄共享状态 + 势力状态（两张单例）。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS tianjiao_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS faction_state ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " doc TEXT NOT NULL)"
    )


async def _v18_qq_operations(conn: aiosqlite.Connection) -> None:
    """群推送订阅及需要玩家私聊领取的发放单。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS qq_groups ("
        " platform_id TEXT NOT NULL, group_id TEXT NOT NULL, categories TEXT NOT NULL,"
        " registered_at REAL NOT NULL, last_seen REAL NOT NULL,"
        " PRIMARY KEY(platform_id, group_id))"
    )
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS item_grants ("
        " id TEXT PRIMARY KEY, target_uid TEXT NOT NULL, item TEXT NOT NULL, qty INTEGER NOT NULL,"
        " issuer_uid TEXT NOT NULL, platform_id TEXT NOT NULL, group_id TEXT NOT NULL,"
        " claim_uid TEXT, confirmed_at REAL, created_at REAL NOT NULL, claimed_at REAL)"
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_item_grants_target ON item_grants(target_uid, claimed_at)")


async def _v19_spar_duel(conn: aiosqlite.Connection) -> None:
    """Legacy persisted multi-round duel state retained for existing databases."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS spar_duel ("
        " id TEXT PRIMARY KEY, doc TEXT NOT NULL)"
    )


async def _v20_combat_sessions(conn: aiosqlite.Connection) -> None:
    """持久化玩家交互切磋的选技与逐回合状态，支持重载恢复。"""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS combat_sessions ("
        " session_id TEXT PRIMARY KEY, platform_id TEXT NOT NULL, group_id TEXT NOT NULL,"
        " player_a TEXT NOT NULL, player_b TEXT NOT NULL, status TEXT NOT NULL,"
        " expires_at REAL NOT NULL, updated_at REAL NOT NULL, payload TEXT NOT NULL)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_combat_sessions_active_player "
        "ON combat_sessions(status, player_a, player_b, expires_at)"
    )
