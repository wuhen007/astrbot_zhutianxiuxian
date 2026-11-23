import asyncio
import unittest

from infra.player_locks import PlayerLockPool


class PlayerLockPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_player_commands_serialize_and_idle_locks_are_removed(self):
        pool = PlayerLockPool()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()
        active = 0
        peak_active = 0

        async def first():
            nonlocal active, peak_active
            async with pool.hold("player"):
                active += 1
                peak_active = max(peak_active, active)
                first_entered.set()
                await release_first.wait()
                active -= 1

        async def second():
            nonlocal active, peak_active
            async with pool.hold("player"):
                active += 1
                peak_active = max(peak_active, active)
                second_entered.set()
                active -= 1

        first_task = asyncio.create_task(first())
        await first_entered.wait()
        second_task = asyncio.create_task(second())
        await asyncio.sleep(0)

        self.assertFalse(second_entered.is_set())
        release_first.set()
        await asyncio.gather(first_task, second_task)

        self.assertTrue(second_entered.is_set())
        self.assertEqual(peak_active, 1)
        self.assertEqual(pool._entries, {})

    async def test_different_players_can_run_concurrently(self):
        pool = PlayerLockPool()
        both_entered = asyncio.Event()
        release = asyncio.Event()
        entered_count = 0

        async def hold(uid):
            nonlocal entered_count
            async with pool.hold(uid):
                entered_count += 1
                if entered_count == 2:
                    both_entered.set()
                await release.wait()

        first = asyncio.create_task(hold("first"))
        second = asyncio.create_task(hold("second"))
        await both_entered.wait()
        self.assertEqual(len(pool._entries), 2)
        release.set()
        await asyncio.gather(first, second)

        self.assertEqual(pool._entries, {})


if __name__ == "__main__":
    unittest.main()
