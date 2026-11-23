import ast
import unittest
from pathlib import Path

from core import secret


class SecretFeedbackTests(unittest.TestCase):
    def test_battle_name_prefers_daohao_then_nickname_and_never_uid(self):
        self.assertEqual(secret.combat_name("openid-123", "openid-123", "群昵称"), "群昵称")
        self.assertEqual(secret.combat_name("openid-123…", "openid-123456", "群昵称"), "群昵称")
        self.assertEqual(secret.combat_name("自定义道号", "openid-123", "群昵称"), "自定义道号")
        self.assertEqual(secret.combat_name("", "openid-123", "openid-123"), "道友")

    def test_defeat_notice_persists_until_cleared_for_a_new_exploration(self):
        ext = {}
        session = secret.Session(place="青冥山", floor=2)

        self.assertIsNone(secret.defeat_notice(ext))
        secret.remember_defeat(ext, session)
        notice = secret.defeat_notice(ext)

        self.assertIn("青冥山", notice)
        self.assertIn("第 2 层", notice)
        self.assertIn("战败", notice)
        secret.clear_defeat_notice(ext)
        self.assertIsNone(secret.defeat_notice(ext))

    def test_secret_search_command_is_registered_without_the_conflicting_name(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        source = main_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        constants = {
            target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        plugin = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "ZhutianPlugin")
        handler = next(node for node in plugin.body
                       if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_search")
        command = next(dec for dec in handler.decorator_list
                       if isinstance(dec, ast.Call)
                       and isinstance(dec.func, ast.Attribute)
                       and dec.func.attr == "command")

        self.assertEqual(constants["CMD_ENTER"], "#降临秘境")
        self.assertEqual(constants["CMD_SEARCH"], "#秘境寻宝")
        self.assertIsInstance(command.args[0], ast.Name)
        self.assertEqual(command.args[0].id, "CMD_SEARCH")
        self.assertEqual(command.args[1].value, "秘境寻宝")
        self.assertNotIn("#" + "寻宝", source)

    def test_state_mutating_single_player_handlers_use_the_player_lock(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        plugin = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "ZhutianPlugin")
        handlers = {node.name: node for node in plugin.body
                    if isinstance(node, ast.AsyncFunctionDef)}

        for name in ("handle_sign", "handle_buy", "handle_sell", "handle_use",
                     "handle_enter", "handle_search", "handle_flee"):
            with self.subTest(handler=name):
                self.assertIn(name, handlers)
                self.assertTrue(any(isinstance(dec, ast.Name)
                                    and dec.id == "_serialized_player_command"
                                    for dec in handlers[name].decorator_list))

    def test_trade_rejects_non_positive_quantity_instead_of_coercing_it(self):
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"))
        plugin = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "ZhutianPlugin")
        trade = next(node for node in plugin.body
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "_trade")
        rejects_non_positive = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "qty"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Lt)
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == 1
            for node in ast.walk(trade)
        )
        coerces_to_one = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "max"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 1
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "qty"
            for node in ast.walk(trade)
        )

        self.assertTrue(rejects_non_positive)
        self.assertFalse(coerces_to_one)


if __name__ == "__main__":
    unittest.main()
