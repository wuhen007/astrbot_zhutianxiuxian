import asyncio
import tempfile
import unittest
from pathlib import Path

from infra.db import DataBase


class QQOperationsDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DataBase(Path(self.temp_dir.name) / "operations.sqlite")
        await self.db.connect()
        await self.db.save_player({"uid": "member-openid", "name": "道友", "stones": 10, "ext": {}})

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_group_subscription_is_scoped_by_platform_and_accepts_openids(self):
        await self.db.register_qq_group("qq-official-instance", "group_openid:abc")
        await self.db.set_qq_group("qq-official-instance", "group_openid:abc", ["daily", "era"])
        await self.db.set_qq_group("other-instance", "group_openid:abc", ["auction"])

        self.assertEqual(await self.db.qq_group_categories("qq-official-instance", "group_openid:abc"), ["daily", "era"])
        self.assertEqual(await self.db.qq_subscribers("daily"), [("qq-official-instance", "group_openid:abc")])

    async def test_claim_is_targeted_and_only_credits_once_under_concurrency(self):
        await self.db.create_item_grant("0123456789abcdef", "member-openid", "超越宝盒", 2, "admin", "qq", "group")
        wrong = await self.db.claim_item_grant("0123456789", "different-openid")
        self.assertFalse(wrong[0])
        self.assertEqual(await self.db.get_inventory("member-openid"), {})

        results = await asyncio.gather(*(
            self.db.claim_item_grant("0123456789abcdef", "member-openid") for _ in range(2)
        ))
        self.assertEqual(sum(ok for ok, _ in results), 1)
        self.assertEqual(await self.db.get_inventory("member-openid"), {"超越宝盒": 2})

    async def test_stone_grant_updates_player_inside_claim_transaction(self):
        await self.db.create_item_grant("abcdef1234567890", "member-openid", "灵石", 25, "admin", "qq", "group")
        self.assertEqual(await self.db.claim_item_grant("abcdef1234567890", "member-openid"), (True, "灵石"))
        self.assertEqual((await self.db.get_player("member-openid"))["stones"], 35)

    async def test_private_openid_claim_requires_group_account_confirmation(self):
        await self.db.save_player({"uid": "group-member-openid", "name": "群内角色", "stones": 0, "ext": {}})
        await self.db.create_item_grant("0123456789abcdef", "group-member-openid", "神源石", 3, "admin", "qq", "group-openid")

        requested = await self.db.claim_item_grant("0123456789abcdef", "private-user-openid")
        self.assertFalse(requested[0])
        self.assertIn("#确认发放", requested[1])
        self.assertEqual(await self.db.get_inventory("group-member-openid"), {})

        wrong_group = await self.db.confirm_item_grant(
            "0123456789abcdef", "group-member-openid", "qq", "another-group"
        )
        self.assertFalse(wrong_group[0])
        confirmed = await self.db.confirm_item_grant(
            "0123456789abcdef", "group-member-openid", "qq", "group-openid"
        )
        self.assertTrue(confirmed[0])
        claimed = await self.db.claim_item_grant("0123456789abcdef", "private-user-openid")
        self.assertEqual(claimed, (True, "神源石"))
        self.assertEqual(await self.db.get_inventory("group-member-openid"), {"神源石": 3})

    async def test_v17_database_migrates_qq_operations_tables(self):
        path = self.db.db_path
        async with self.db.transaction() as conn:
            await conn.execute("DROP TABLE qq_groups")
            await conn.execute("DROP TABLE item_grants")
            await conn.execute("UPDATE db_info SET version = 17")
        await self.db.close()

        self.db = DataBase(path)
        await self.db.connect()
        async with self.db.conn.execute("SELECT version FROM db_info") as cur:
            self.assertEqual((await cur.fetchone())[0], 18)
        await self.db.register_qq_group("qq", "group_openid")
        self.assertEqual(await self.db.qq_group_categories("qq", "group_openid"), [])


if __name__ == "__main__":
    unittest.main()
