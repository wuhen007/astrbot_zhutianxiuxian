import asyncio
import ast
import tempfile
import time
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace

from core import profile
from core.player import PlayerDoc
from infra.db import DataBase


class ProfileCommandTests(unittest.TestCase):
    def test_name_aliases_share_one_normalized_value(self):
        for prefix in ("#改名", "#更名", "#设置姓名", "#改道号"):
            with self.subTest(prefix=prefix):
                command = profile.parse_profile_command(f"{prefix} 星+辰")
                self.assertEqual(command, ("name", "星+辰"))
        self.assertEqual(profile.normalize_profile_text(" 星 + 辰 "), "星辰")

    def test_declaration_and_gender_routes_are_distinct(self):
        self.assertEqual(profile.parse_profile_command("#设置道宣 心向大道"), ("declaration", "心向大道"))
        self.assertEqual(profile.parse_profile_command("#更替性别 女修"), ("gender", "女修"))

    def test_name_and_declaration_use_upstream_length_limits(self):
        self.assertEqual(profile.validate_name("八字道号"), "八字道号")
        self.assertEqual(profile.validate_declaration("道" * 50), "道" * 50)
        with self.assertRaisesRegex(ValueError, "最多八字"):
            profile.validate_name("一二三四五六七八九")
        with self.assertRaisesRegex(ValueError, "最多 50"):
            profile.validate_declaration("道" * 51)

    def test_empty_profile_values_are_rejected(self):
        with self.assertRaises(ValueError):
            profile.validate_name(" +  ")
        with self.assertRaises(ValueError):
            profile.validate_declaration(" + ")

    def test_duplicate_names_are_rejected_but_current_name_is_allowed(self):
        self.assertEqual(profile.validate_unique_name("新道号", {"旧道号", "别的道友"}), "新道号")
        with self.assertRaises(ValueError):
            profile.validate_unique_name("重名", {"重名", "其他"})

    def test_gender_synonyms_match_upstream_and_ignore_unsupported_values(self):
        self.assertEqual(profile.parse_gender("男性修士"), 2)
        self.assertEqual(profile.parse_gender("姑娘"), 1)
        self.assertIsNone(profile.parse_gender("无所谓"))
        self.assertEqual(profile.gender_label(0), "未设置")
        self.assertEqual(profile.gender_label(1), "女")
        self.assertEqual(profile.gender_label(2), "男")
        self.assertTrue(profile.gender_is_set("3"))
        self.assertFalse(profile.gender_is_set("0"))

    def test_discard_defaults_to_one_and_parses_explicit_quantity(self):
        self.assertEqual(profile.parse_discard("#丢弃筑基丹"), ("筑基丹", 1))
        self.assertEqual(profile.parse_discard("丢弃 修为丹 * 12"), ("修为丹", 12))

    def test_discard_rejects_missing_name_bad_quantity_and_cancel(self):
        for raw in ("#丢弃", "#丢弃*2", "#丢弃筑基丹*0", "#丢弃筑基丹*-1", "#丢弃筑基丹*1*2"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                profile.parse_discard(raw)
        self.assertIsNone(profile.parse_discard("#取消丢弃"))


def command_handlers():
    plugin_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((plugin_root / "main.py").read_text(encoding="utf-8"))
    wanted = {"handle_profile_command", "handle_discard_item"}
    methods = [node for node in ast.walk(tree)
               if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted]
    for method in methods:
        method.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *methods,
    ], type_ignores=[])
    env = {"PlayerDoc": PlayerDoc, "profile_mod": profile,
           "time": time,
           "day_key": __import__("core.clock", fromlist=["day_key"]).day_key}
    exec(compile(ast.fix_missing_locations(module), "main.py:profile-handlers", "exec"), env)
    return {name: env[name] for name in wanted if name in env}


class ProfileCommandHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = DataBase(Path(self.temp.name) / "profile.sqlite")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.locks = {}
        self.host = SimpleNamespace(db=self.db, _allowed=lambda event: True)
        self.host._profile_name_lock = asyncio.Lock()

        def pl_lock(uid):
            return self.locks.setdefault(str(uid), asyncio.Lock())

        self.host._pl_lock = pl_lock

        async def require_player(event):
            raw = await self.db.get_player(event.get_sender_id())
            return (PlayerDoc(**raw), None) if raw else (None, "missing")

        self.host._require_player = require_player
        self.host._msg_of = lambda event: event.message_str
        for name, method in command_handlers().items():
            setattr(self.host, name, MethodType(method, self.host))
        self.assertTrue(hasattr(self.host, "handle_profile_command"))
        self.assertTrue(hasattr(self.host, "handle_discard_item"))

    async def add_player(self, uid, name, stones=3000, ext=None):
        doc = PlayerDoc(uid=uid, name=name, stones=stones, ext=ext or {})
        await self.db.save_player(doc.model_dump())

    @staticmethod
    def event(uid, message):
        return SimpleNamespace(uid=uid, message_str=message,
                               get_sender_id=lambda: uid,
                               plain_result=lambda text: text)

    async def invoke(self, handler_name, uid, message):
        handler = getattr(self.host, handler_name)
        return [value async for value in handler(self.event(uid, message))]

    async def test_concurrent_renames_cannot_claim_the_same_name(self):
        await self.add_player("A", "甲")
        await self.add_player("B", "乙")
        results = await asyncio.gather(
            self.invoke("handle_profile_command", "A", "#改道号 新名"),
            self.invoke("handle_profile_command", "B", "#更名 新名"),
        )
        names = [(await self.db.get_player(uid))["name"] for uid in ("A", "B")]
        docs = [await self.db.get_player(uid) for uid in ("A", "B")]
        self.assertEqual(names.count("新名"), 1)
        self.assertEqual(sum(doc["stones"] == 2000 for doc in docs), 1)
        self.assertEqual(sum(any("已存在" in str(result) for result in group) for group in results), 1)

    async def test_rename_costs_once_per_shanghai_day(self):
        await self.add_player("A", "甲")
        first = await self.invoke("handle_profile_command", "A", "#改名 新道号")
        second = await self.invoke("handle_profile_command", "A", "#改名 另一个")
        doc = await self.db.get_player("A")
        self.assertEqual(doc["name"], "新道号")
        self.assertEqual(doc["stones"], 2000)
        self.assertTrue(any("每日只能改名一次" in str(result) for result in second))
        self.assertTrue(any("新道号" in str(result) for result in first))

    async def test_rename_without_fee_does_not_change_name_or_daily_limit(self):
        await self.add_player("A", "甲", stones=999)
        result = await self.invoke("handle_profile_command", "A", "#改名 新道号")
        doc = await self.db.get_player("A")
        self.assertEqual(doc["name"], "甲")
        self.assertEqual(doc["stones"], 999)
        self.assertNotIn("name", doc["ext"].get("profile_daily", {}))
        self.assertTrue(any("1000 灵石" in str(message) for message in result))

    async def test_gender_can_only_be_set_once(self):
        await self.add_player("A", "甲")
        await self.invoke("handle_profile_command", "A", "#设置性别 男修")
        await self.invoke("handle_profile_command", "A", "#变更性别 女")
        doc = await self.db.get_player("A")
        self.assertEqual(doc["ext"]["sex"], 2)

    async def test_legacy_nonzero_gender_code_is_already_set(self):
        await self.add_player("A", "甲", ext={"legacy_source": {"sex": 3}})
        await self.invoke("handle_profile_command", "A", "#设置性别 女")
        doc = await self.db.get_player("A")
        self.assertNotIn("sex", doc["ext"])

    async def test_declaration_is_limited_and_cannot_change_twice_today(self):
        await self.add_player("A", "甲")
        await self.invoke("handle_profile_command", "A", "#设置道宣 心向大道")
        await self.invoke("handle_profile_command", "A", "#设置道宣 另立新誓")
        doc = await self.db.get_player("A")
        self.assertEqual(doc["ext"]["declaration"], "心向大道")
        self.assertTrue(any("每日仅可更改一次道宣" in str(result)
                            for result in await self.invoke("handle_profile_command", "A", "#设置道宣 另立新誓")))

    async def test_discard_decrements_exact_quantity_and_checks_stock(self):
        await self.add_player("A", "甲")
        await self.db.add_items("A", {"筑基丹": 3})
        await self.invoke("handle_discard_item", "A", "#丢弃筑基丹*2")
        self.assertEqual(await self.db.get_inventory("A"), {"筑基丹": 1})
        await self.invoke("handle_discard_item", "A", "#丢弃 筑基丹*2")
        self.assertEqual(await self.db.get_inventory("A"), {"筑基丹": 1})

    async def test_discard_cannot_remove_an_equipped_item(self):
        await self.add_player("A", "甲", ext={"equipment": {"武器": "长剑"}})
        await self.invoke("handle_discard_item", "A", "#丢弃长剑")
        self.assertEqual(await self.db.get_inventory("A"), {})

    async def test_cancel_discard_never_changes_inventory(self):
        await self.add_player("A", "甲")
        await self.db.add_items("A", {"筑基丹": 2})
        await self.invoke("handle_discard_item", "A", "#取消丢弃")
        self.assertEqual(await self.db.get_inventory("A"), {"筑基丹": 2})

    async def test_discard_shortage_does_not_partially_remove_items(self):
        await self.add_player("A", "甲")
        await self.db.add_items("A", {"筑基丹": 2})
        result = await self.invoke("handle_discard_item", "A", "#丢弃筑基丹*3")
        self.assertTrue(any("数量不足" in str(message) for message in result))
        self.assertEqual(await self.db.get_inventory("A"), {"筑基丹": 2})


if __name__ == "__main__":
    unittest.main()
