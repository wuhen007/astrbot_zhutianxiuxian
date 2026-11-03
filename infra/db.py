"""SQLite 存储层：WAL + 版本化迁移 + 玩家文档读写。"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

LATEST_DB_VERSION = 14


def _shanghai_date_key(ts: float) -> str:
    """上海时区日期键（YYYY-MM-DD），每日任务以它判定"今天"。"""
    return time.strftime("%Y-%m-%d", time.gmtime(ts + 8 * 3600))


class DataBase:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn: Optional[aiosqlite.Connection] = None

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

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """多语句事务；异常自动回滚。"""
        assert self.conn is not None
        await self.conn.execute("BEGIN")
        try:
            yield self.conn
        except Exception:
            await self.conn.rollback()
            raise
        else:
            await self.conn.commit()

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
                await _v11_calamity(self.conn)
                await _v12_lingjie(self.conn)
                await _v13_ancient(self.conn)
                await _v14_other_shore(self.conn)
                await self.conn.execute("INSERT INTO db_info (version) VALUES (?)", (LATEST_DB_VERSION,))
            return

        # 后续版本在此登记：MIGRATIONS[n] = upgrade_fn
        MIGRATIONS = {2: _v2_inventory, 3: _v3_world_boss, 4: _v4_sects, 5: _v5_auction, 6: _v6_sect_score, 7: _v7_daily_tasks, 8: _v8_dark_boss, 9: _v9_raid, 10: _v10_rift, 11: _v11_calamity, 12: _v12_lingjie, 13: _v13_ancient, 14: _v14_other_shore}
        for version in sorted(v for v in MIGRATIONS if v > current):
            async with self.transaction():
                await MIGRATIONS[version](self.conn)
                await self.conn.execute("UPDATE db_info SET version = ?", (version,))

    # ---- 纳戒（背包）：以物品名为键，全部游戏操作均按名字进行 ----

    async def get_inventory(self, uid: str) -> dict[str, int]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT item, qty FROM inventory WHERE uid = ? ORDER BY qty DESC", (uid,)
        ) as cur:
            return {row[0]: row[1] for row in await cur.fetchall()}

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

    # ---- 玩家文档 ----

    async def get_player(self, uid: str) -> Optional[dict[str, Any]]:
        assert self.conn is not None
        async with self.conn.execute("SELECT doc FROM players WHERE uid = ?", (uid,)) as cur:
            row = await cur.fetchone()
            return json.loads(row[0]) if row else None

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

    async def dark_ledger(self, round_no: int) -> dict[str, tuple[str, int]]:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT uid, name, damage FROM dark_ledger WHERE boss_round = ? ORDER BY damage DESC",
            (round_no,),
        ) as cur:
            return {row[0]: (row[1], row[2]) for row in await cur.fetchall()}

    # ---- 裂界副本：全服单例状态（当前裂界 + 锚定度 + 贡献） ----

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

    async def save_other_shore(self, doc: dict[str, Any]) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT OR REPLACE INTO other_shore_state (id, doc) VALUES (1, ?)",
            (json.dumps(doc, ensure_ascii=False),),
        )
        if owned:
            await self.conn.commit()

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

    async def get_raid(self, code: str) -> dict[str, Any] | None:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT code, boss, leader_uid, leader_name, hp, hp_max, atk, defense,"
            " reward, status, created_at, finished_at, settled, killer_uid FROM raid_team WHERE code = ?",
            (str(code),),
        ) as cur:
            return self._raid_row(await cur.fetchone())

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

    async def raid_member(self, code: str, uid: str) -> dict[str, Any] | None:
        for m in await self.raid_members(code):
            if m["uid"] == uid:
                return m
        return None

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

    async def mark_raid_settled(self, code: str) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "UPDATE raid_team SET settled = 1 WHERE code = ?", (str(code),)
        )
        if owned:
            await self.conn.commit()

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

    async def raid_member_count(self, code: str) -> int:
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT COUNT(*) FROM raid_member WHERE code = ?", (str(code),)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---- 世界 Boss ----


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

    async def boss_ledger(self, round_no: int) -> dict[str, tuple[str, int]]:
        """某轮贡献账本：uid → (名字, 累计伤害)，按伤害降序。"""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT uid, name, damage FROM boss_ledger WHERE boss_round = ? ORDER BY damage DESC",
            (round_no,),
        ) as cur:
            return {r[0]: (r[1], r[2]) for r in await cur.fetchall()}


    # ---- 宗门 ----

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

    async def create_sect(self, name: str, master_uid: str, now: float) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute(
            "INSERT INTO sects (name, master_uid, level, fund, created_at) VALUES (?, ?, 1, 0, ?)",
            (name, master_uid, now),
        )
        if owned:
            await self.conn.commit()

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

    async def delete_sect(self, name: str) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute("DELETE FROM sects WHERE name = ?", (name,))
        if owned:
            await self.conn.commit()

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

    async def add_sect_score(self, name: str, delta: int) -> None:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        await self.conn.execute("UPDATE sects SET score = score + ? WHERE name = ?", (delta, name))
        if owned:
            await self.conn.commit()

    async def all_players(self) -> list[dict[str, Any]]:
        """遍历玩家文档（排行用；群服规模下可接受全扫）。"""
        assert self.conn is not None
        async with self.conn.execute("SELECT uid, doc FROM players") as cur:
            return [{"uid": r[0], **json.loads(r[1])} for r in await cur.fetchall()]


    # ---- 拍卖行（寄售制，物品托管） ----

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

    async def delete_auction(self, lot_id: int) -> bool:
        assert self.conn is not None
        owned = not self.conn.in_transaction
        cur = await self.conn.execute("DELETE FROM auction WHERE id = ?", (lot_id,))
        if owned:
            await self.conn.commit()
        return cur.rowcount > 0

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


