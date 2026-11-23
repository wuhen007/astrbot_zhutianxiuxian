import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from core import plane_events
from core.player import PlayerDoc


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def plugin_tree():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    plugin = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == "ZhutianPlugin")
    return tree, plugin


def bare_handler(name):
    _, plugin = plugin_tree()
    handler = next(node for node in plugin.body
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    handler.decorator_list = []
    namespace = {"AstrMessageEvent": object}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(MAIN_PATH), "exec"), namespace)
    return namespace[name]


class LiveReportRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_marry_yes_without_pending_proposal_replies_without_loading_player(self):
        async def require_player(_event):
            raise AssertionError("no pending proposal should be handled before player lookup")

        host = SimpleNamespace(_allowed=lambda _event: True,
                               _pending_marriage=None,
                               _require_player=require_player)
        event = SimpleNamespace(get_sender_id=lambda: "recipient",
                                plain_result=lambda text: text)

        result = [line async for line in bare_handler("handle_marry_yes")(host, event)]

        self.assertEqual(len(result), 1)
        self.assertIn("没有待处理的求婚", result[0])

    async def test_marry_no_without_pending_proposal_replies(self):
        host = SimpleNamespace(_allowed=lambda _event: True, _pending_marriage=None)
        event = SimpleNamespace(get_sender_id=lambda: "recipient",
                                plain_result=lambda text: text)

        result = [line async for line in bare_handler("handle_marry_no")(host, event)]

        self.assertEqual(len(result), 1)
        self.assertIn("没有待处理的求婚", result[0])

    def test_fish_sign_passes_button_rows_as_separate_action_rows(self):
        _, plugin = plugin_tree()
        handler = next(node for node in plugin.body
                       if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == "handle_fish_sign")
        combined_rows = [node for node in ast.walk(handler)
                         if isinstance(node, ast.BinOp)
                         and isinstance(node.op, ast.Add)
                         and any(isinstance(child, ast.Call)
                                 and isinstance(child.func, ast.Attribute)
                                 and child.func.attr == "_daily_sign_rows"
                                 for child in ast.walk(node))]

        self.assertEqual(combined_rows, [])

    def test_pvp_handlers_resolve_health_before_running_gates(self):
        _, plugin = plugin_tree()
        handlers = {node.name: node for node in plugin.body
                    if isinstance(node, ast.AsyncFunctionDef)}

        for name in ("handle_rob", "handle_biwu"):
            with self.subTest(handler=name):
                sync_calls = [node for node in ast.walk(handlers[name])
                              if isinstance(node, ast.Call)
                              and isinstance(node.func, ast.Attribute)
                              and node.func.attr == "_sync_pvp_health"]
                self.assertEqual(len(sync_calls), 1)

    def test_sign_usage_text_contains_the_required_command_argument_separator(self):
        ok, message = plane_events.ask_sign(PlayerDoc(uid="player"), "unknown", now=1)

        self.assertFalse(ok)
        self.assertIn("#求取 问道签", message)
        self.assertIn("#求取 历练签", message)
        self.assertIn("#求取 寻缘签", message)

    def test_flower_and_item_gifts_have_distinct_registered_handlers(self):
        tree, plugin = plugin_tree()
        cmd_assignments = [target.id for node in tree.body
                           if isinstance(node, ast.Assign)
                           and isinstance(node.value, ast.Constant)
                           for target in node.targets
                           if isinstance(target, ast.Name) and target.id.startswith("CMD_")]
        constants = {
            target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets if isinstance(target, ast.Name)
        }
        handlers = {node.name: node for node in plugin.body
                    if isinstance(node, ast.AsyncFunctionDef)}

        self.assertEqual(constants["CMD_GIFT_FLOWER"], "#赠予花篮")
        self.assertEqual(constants["CMD_GIFT"], "#赠送")
        self.assertEqual(constants["CMD_REDEEM_MIRACLE"], "#救赎")
        self.assertEqual(len(cmd_assignments), len(set(cmd_assignments)))
        self.assertIn("handle_gift_flower", handlers)
        self.assertIn("handle_gift", handlers)
        self.assertIn("handle_sakura_redeem", handlers)

        def command_constant(handler_name):
            command = next(dec for dec in handlers[handler_name].decorator_list
                           if isinstance(dec, ast.Call)
                           and isinstance(dec.func, ast.Attribute)
                           and dec.func.attr == "command")
            return command.args[0].id

        self.assertEqual(command_constant("handle_gift_flower"), "CMD_GIFT_FLOWER")
        self.assertEqual(command_constant("handle_gift"), "CMD_GIFT")
        self.assertEqual(command_constant("handle_sakura_redeem"), "CMD_REDEEM_MIRACLE")
        self.assertEqual(command_constant("handle_redeem"), "CMD_REDEEM")


if __name__ == "__main__":
    unittest.main()
