import asyncio
from pathlib import Path
import tempfile
import unittest

from infra.db import DataBase


def player(uid, name):
    return {
        "uid": uid,
        "name": name,
        "realm_table": "练气境界",
        "realm_index": 0,
        "exp": 0,
        "stones": 0,
        "created_at": 0.0,
        "ext": {},
    }


class DatabaseTransactionIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DataBase(Path(self.temp_dir.name) / "test.sqlite")
        await self.db.connect()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_outside_write_survives_another_tasks_rollback(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def transaction_a():
            try:
                async with self.db.transaction():
                    await self.db.save_player(player("a", "transaction"))
                    entered.set()
                    await release.wait()
                    raise RuntimeError("rollback transaction A")
            except RuntimeError:
                pass

        async def write_b():
            await entered.wait()
            await self.db.save_player(player("b", "independent"))

        task_a = asyncio.create_task(transaction_a())
        task_b = asyncio.create_task(write_b())
        await entered.wait()
        await asyncio.sleep(0.01)
        self.assertFalse(task_b.done(), "independent write must wait for transaction A")
        release.set()
        await asyncio.gather(task_a, task_b)

        self.assertIsNone(await self.db.get_player("a"))
        self.assertEqual((await self.db.get_player("b"))["name"], "independent")

    async def test_other_task_cannot_read_uncommitted_player_data(self):
        await self.db.save_player(player("shared", "before"))
        entered = asyncio.Event()
        release = asyncio.Event()

        async def transaction_a():
            try:
                async with self.db.transaction():
                    await self.db.save_player(player("shared", "uncommitted"))
                    entered.set()
                    await release.wait()
                    raise RuntimeError("rollback transaction A")
            except RuntimeError:
                pass

        task_a = asyncio.create_task(transaction_a())
        await entered.wait()
        task_reader = asyncio.create_task(self.db.get_player("shared"))
        await asyncio.sleep(0.01)
        self.assertFalse(task_reader.done(), "read must wait for the active transaction")
        release.set()
        await task_a
        self.assertEqual((await task_reader)["name"], "before")


if __name__ == "__main__":
    unittest.main()
