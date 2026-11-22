import ast
import asyncio
import random
import re
import secrets
import tempfile
import time
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from types import MethodType, SimpleNamespace

from core import source_duel, yuanshi
from core.player import PlayerDoc
from infra.db import DataBase


def duel_handlers():
    plugin_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((plugin_root / "main.py").read_text(encoding="utf-8"))
    wanted = {"handle_source_duel", "handle_source_duel_choice"}
    methods = [node for node in ast.walk(tree)
               if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted]
    for method in methods:
        method.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *methods,
    ], type_ignores=[])
    env = {
        "PlayerDoc": PlayerDoc,
        "source_duel_mod": source_duel,
        "yuanshi": yuanshi,
        "time": time,
        "random": random,
        "secrets": secrets,
        "re": re,
        "math": __import__("math"),
        "AsyncExitStack": AsyncExitStack,
    }
    exec(compile(ast.fix_missing_locations(module), "main.py:source-duel-handlers", "exec"), env)
    return {name: env[name] for name in wanted if name in env}


class SourceDuelHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = DataBase(Path(self.temp.name) / "source-duel.sqlite")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.locks = {}
        self.host = SimpleNamespace(db=self.db, _allowed=lambda event: True)

        def pl_lock(uid):
            return self.locks.setdefault(str(uid), asyncio.Lock())

        async def require_player(event):
            raw = await self.db.get_player(event.get_sender_id())
            return (PlayerDoc(**raw), None) if raw else (None, "missing")

        self.host._pl_lock = pl_lock
        self.host._require_player = require_player
        self.host._msg_of = lambda event: event.message_str
        for name, method in duel_handlers().items():
            setattr(self.host, name, MethodType(method, self.host))

    @staticmethod
    def event(uid, message):
        return SimpleNamespace(message_str=message, get_sender_id=lambda: uid,
                               plain_result=lambda text: text)

    async def invoke(self, uid, message, handler):
        async with self.host._pl_lock(uid):
            return [line async for line in getattr(self.host, handler)(self.event(uid, message))]

    async def save_player(self, uid, source, *, occupation="", level=1, duel=None):
        y = {"amount": source, "ledger": [], "cuts": 0, "empty_streak": 0}
        if duel is not None:
            y["duel"] = duel
        doc = PlayerDoc(uid=uid, name=uid, ext={"yuanshi": y,
                                               "occupation": occupation,
                                               "occupation_level": level})
        await self.db.save_player(doc.model_dump())

    async def test_start_charges_only_fee_and_persists_five_minute_session(self):
        await self.save_player("start", 400_000, occupation="源天师", level=10)

        lines = await self.invoke("start", "#源石坊对决1", "handle_source_duel")

        saved = await self.db.get_player("start")
        y = yuanshi.system_of(PlayerDoc(**saved))
        session = y["duel"]["session"]
        self.assertEqual(y["amount"], 200_000)
        self.assertEqual(y["duel"]["net"], -200_000)
        self.assertEqual(session["npc_id"], 1)
        self.assertEqual(session["expires_at"] - session["created_at"], 300)
        self.assertEqual(len(session["player_stones"]), 5)
        self.assertEqual(len(session["npc_stones"]), 5)
        self.assertIn("石料费已扣", "\n".join(str(line) for line in lines))

    async def test_start_requires_fee_plus_base_wager_without_mutating_player(self):
        await self.save_player("poor", 399_999)

        lines = await self.invoke("poor", "#源石坊对决1", "handle_source_duel")

        saved = await self.db.get_player("poor")
        y = yuanshi.system_of(PlayerDoc(**saved))
        self.assertEqual(y["amount"], 399_999)
        self.assertIsNone(y.get("duel", {}).get("session"))
        self.assertIn("验资", "\n".join(str(line) for line in lines))

    async def test_invalid_choice_keeps_session_and_does_not_charge_wager(self):
        session = source_duel.create_session(1, {}, now=time.time(), seed="invalid-choice")
        await self.save_player("invalid", 50_000, duel={"session": session, "net": -200_000})

        lines = await self.invoke("invalid", "#对决选石 1 1 2", "handle_source_duel_choice")

        y = yuanshi.system_of(PlayerDoc(**(await self.db.get_player("invalid"))))
        self.assertEqual(y["amount"], 50_000)
        self.assertIsNotNone(y["duel"]["session"])
        self.assertIn("不同的源石", "\n".join(str(line) for line in lines))

    async def test_insufficient_selected_wager_keeps_session_and_balance(self):
        session = source_duel.create_session(1, {}, now=time.time(), seed="short-wager")
        await self.save_player("short-wager", 100_000,
                               duel={"session": session, "net": -200_000})

        lines = await self.invoke("short-wager", "#对决选石 1 2 3 豪赌",
                                  "handle_source_duel_choice")

        y = yuanshi.system_of(PlayerDoc(**(await self.db.get_player("short-wager"))))
        self.assertEqual(y["amount"], 100_000)
        self.assertIsNotNone(y["duel"]["session"])
        self.assertEqual(y["duel"].get("wins", 0), 0)
        self.assertIn("仍可重新选择", "\n".join(str(line) for line in lines))

    async def test_expired_session_clears_lazily_without_refunding_fee(self):
        session = source_duel.create_session(1, {}, now=time.time() - 600, seed="expired")
        await self.save_player("expired", 25_000, duel={"session": session, "net": -200_000})

        lines = await self.invoke("expired", "#对决选石 1 2 3", "handle_source_duel_choice")

        y = yuanshi.system_of(PlayerDoc(**(await self.db.get_player("expired"))))
        self.assertEqual(y["amount"], 25_000)
        self.assertIsNone(y["duel"]["session"])
        self.assertEqual(y["duel"]["net"], -200_000)
        self.assertIn("石料费不退", "\n".join(str(line) for line in lines))

    async def test_win_settlement_records_cooldown_and_cannot_be_claimed_twice(self):
        now = time.time()
        session = source_duel.create_session(1, {}, now=now, seed="winning-session")
        for stone in session["player_stones"]:
            stone["source_value"] = 100_000
        for stone in session["npc_stones"]:
            stone["source_value"] = 0
        await self.save_player("winner", 250_000, duel={"session": session, "net": -200_000})

        lines = await self.invoke("winner", "#对决选石 1 2 3 平注", "handle_source_duel_choice")
        after_first = await self.db.get_player("winner")
        first_y = yuanshi.system_of(PlayerDoc(**after_first))
        second_lines = await self.invoke("winner", "#对决选石 1 2 3 平注",
                                        "handle_source_duel_choice")
        after_second = await self.db.get_player("winner")
        second_y = yuanshi.system_of(PlayerDoc(**after_second))

        self.assertEqual(first_y["amount"], 750_000)
        self.assertEqual(first_y["duel"]["wins"], 1)
        self.assertIsNone(first_y["duel"]["session"])
        self.assertGreater(first_y["duel"]["cooldown_until"], time.time())
        self.assertEqual(second_y["amount"], first_y["amount"])
        self.assertEqual(second_y["duel"]["wins"], 1)
        self.assertIn("赢下对决", "\n".join(str(line) for line in lines))
        self.assertIn("没有等待选石", "\n".join(str(line) for line in second_lines))

    async def test_start_database_failure_rolls_back_fee_and_session(self):
        await self.save_player("rollback-start", 500_000)
        original_save = self.db.save_player

        async def fail_save(doc):
            raise RuntimeError("duel save failed")

        self.db.save_player = fail_save
        with self.assertRaisesRegex(RuntimeError, "duel save failed"):
            await self.invoke("rollback-start", "#源石坊对决1", "handle_source_duel")
        self.db.save_player = original_save

        y = yuanshi.system_of(PlayerDoc(**(await self.db.get_player("rollback-start"))))
        self.assertEqual(y["amount"], 500_000)
        self.assertIsNone(y.get("duel", {}).get("session"))

    async def test_existing_cooldown_blocks_new_duel_without_charging_fee(self):
        await self.save_player("cooldown", 500_000,
                               duel={"session": None,
                                     "cooldown_until": time.time() + 600})

        lines = await self.invoke("cooldown", "#源石坊对决2", "handle_source_duel")

        y = yuanshi.system_of(PlayerDoc(**(await self.db.get_player("cooldown"))))
        self.assertEqual(y["amount"], 500_000)
        self.assertIsNone(y["duel"]["session"])
        self.assertIn("源术对决耗费心神", "\n".join(str(line) for line in lines))

    async def test_settlement_database_failure_preserves_session_and_source(self):
        session = source_duel.create_session(1, {}, now=time.time(), seed="rollback-settle")
        await self.save_player("rollback-settle", 500_000,
                               duel={"session": session, "net": -200_000})
        original_save = self.db.save_player

        async def fail_save(doc):
            raise RuntimeError("duel settlement failed")

        self.db.save_player = fail_save
        with self.assertRaisesRegex(RuntimeError, "duel settlement failed"):
            await self.invoke("rollback-settle", "#对决选石 1 2 3 平注",
                              "handle_source_duel_choice")
        self.db.save_player = original_save

        y = yuanshi.system_of(PlayerDoc(**(await self.db.get_player("rollback-settle"))))
        self.assertEqual(y["amount"], 500_000)
        self.assertIsNotNone(y["duel"]["session"])
        self.assertEqual(y["duel"]["net"], -200_000)


if __name__ == "__main__":
    unittest.main()
