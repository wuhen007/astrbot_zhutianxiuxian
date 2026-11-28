import tempfile
import unittest
import time
from pathlib import Path

from infra.db import DataBase


class CombatSessionDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DataBase(Path(self.temp_dir.name) / "combat.sqlite")
        await self.db.connect()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    @staticmethod
    def session(session_id="spar-1", player_a="a", player_b="b", expiry=None):
        return {"session_id": session_id, "platform_id": "qq", "group_id": "group",
                "player_a": player_a, "player_b": player_b, "status": "active",
                "expires_at": time.time() + 200 if expiry is None else expiry,
                "phase": "select", "payload": {}}

    async def test_creation_atomically_reserves_both_players(self):
        created, busy = await self.db.create_combat_session(self.session())
        self.assertTrue(created)
        self.assertIsNone(busy)
        created, busy = await self.db.create_combat_session(
            self.session("spar-2", player_a="c", player_b="a"))
        self.assertFalse(created)
        self.assertEqual(busy, "a")
        self.assertEqual((await self.db.find_active_combat_session("b"))["session_id"], "spar-1")

    async def test_session_round_payload_survives_read_and_update(self):
        original = self.session()
        original["units"] = {"a": {"hp": 500}}
        await self.db.save_combat_session(original)
        saved = await self.db.get_combat_session("spar-1")
        self.assertEqual(saved["units"]["a"]["hp"], 500)
        saved["units"]["a"]["hp"] = 250
        await self.db.save_combat_session(saved)
        self.assertEqual((await self.db.get_combat_session("spar-1"))["units"]["a"]["hp"], 250)

    async def test_expired_sessions_can_be_reaped_and_deleted(self):
        await self.db.save_combat_session(self.session(expiry=90.0))
        self.assertEqual(await self.db.due_combat_sessions(now=100.0), [self.session(expiry=90.0)])
        expired = await self.db.expire_combat_sessions(now=100.0)
        self.assertEqual(len(expired), 1)
        self.assertIsNone(await self.db.find_active_combat_session("a", now=100.0))
        await self.db.delete_combat_session("spar-1")
        self.assertIsNone(await self.db.get_combat_session("spar-1"))


if __name__ == "__main__":
    unittest.main()
