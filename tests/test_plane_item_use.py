import ast
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import items, plane, plane_relay
from core.player import PlayerDoc


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def load_trade():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.AsyncFunctionDef) and node.name == "_trade")
    fn.decorator_list = []
    module = ast.Module(body=[fn], type_ignores=[])
    namespace = {
        "AstrMessageEvent": object,
        "items": items,
        "plane": plane,
        "plane_relay": plane_relay,
        "pr_mod": plane_relay,
        "random": __import__("random"),
        "time": SimpleNamespace(time=lambda: 100.0),
    }
    exec(compile(ast.fix_missing_locations(module), str(MAIN_PATH), "exec"), namespace)
    return namespace["_trade"]


class PlaneItemUseTests(unittest.IsolatedAsyncioTestCase):
    async def test_using_travel_items_activates_portal_and_wind_receipts(self):
        plugin = SimpleNamespace()
        doc = PlayerDoc(uid="travel-items", exp=1000, ext={"xueqi": 1000})
        save_player = AsyncMock()
        add_items = AsyncMock()
        remove_item = AsyncMock(return_value=True)
        db = SimpleNamespace(
            get_player=AsyncMock(return_value=doc.model_dump()),
            get_inventory=AsyncMock(return_value={"位面传送阵": 2, "\u5929\u5916\u6e05\u98ce": 3}),
            save_player=save_player,
            add_items=add_items,
            remove_item=remove_item,
            transaction=lambda: _transaction(),
        )
        plugin.db = db
        plugin._require_player = AsyncMock(return_value=(doc, None))
        plugin.item_index = {
            "位面传送阵": {"name": "位面传送阵", "class": "材料"},
            "\u5929\u5916\u6e05\u98ce": {"name": "\u5929\u5916\u6e05\u98ce", "class": "材料"},
        }
        plugin.shop_item_index = {}
        plugin.sell_item_index = {}
        plugin._val = lambda _key, default=None: default
        plugin._stats = lambda _doc: SimpleNamespace(hp=100)
        plugin.linggen_table = []

        event = SimpleNamespace(uid=doc.uid, plain_result=lambda msg: msg)

        with patch.object(items, "use_item", side_effect=AssertionError("generic use path")):
            messages = [message async for message in load_trade()(plugin, event, "位面传送阵", 2, "use")]
            messages += [message async for message in load_trade()(plugin, event, "\u5929\u5916\u6e05\u98ce", 3, "use")]

        self.assertTrue(any("传送" in msg for msg in messages))
        self.assertTrue(any("清风" in msg for msg in messages))
        self.assertTrue(any(call.args[1] == "位面传送阵" and call.args[2] == 2
                            for call in remove_item.await_args_list))
        self.assertTrue(any(call.args[1] == "\u5929\u5916\u6e05\u98ce" and call.args[2] == 3
                            for call in remove_item.await_args_list))
        self.assertEqual(plane.state_of(doc)["portal_uses"]["low"], 2)
        self.assertEqual(plane.state_of(doc)["wind_uses"], 3)


from contextlib import asynccontextmanager


@asynccontextmanager
async def _transaction():
    yield


if __name__ == "__main__":
    unittest.main()
