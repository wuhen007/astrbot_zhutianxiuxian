import ast
import random
import time
import unittest
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from core import superdim, calamity, plane
from core.player import PlayerDoc


def load_deduce_handler(selfdao_module):
    plugin_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((plugin_root / "main.py").read_text(encoding="utf-8"))
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_sd_deduce"
    )
    handler.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        handler,
    ], type_ignores=[])
    env = {
        "random": random,
        "PlayerDoc": PlayerDoc,
        "calamity": calamity,
        "plane": plane,
        "selfdao_mod": selfdao_module,
        "sd_mod": superdim,
        "time": time,
    }
    exec(compile(ast.fix_missing_locations(module), "main.py:selfdao-route", "exec"), env)
    return env["handle_sd_deduce"]


class SelfDaoCommandRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_deduce_handler_calls_selfdao_module(self):
        doc = PlayerDoc(uid="selfdao-route", name="帝路人")
        calls = []

        def deduce(actual_doc, now, rng):
            calls.append((actual_doc, now, rng))
            return True, "推演完成", {}

        class FakeDB:
            def __init__(self):
                self.calamity_lock = asyncio.Lock()
                self.player = doc.model_dump()
                self.calamity = {}

            @asynccontextmanager
            async def transaction(self):
                yield

            async def get_player(self, uid):
                return self.player

            async def save_player(self, player):
                self.player = player

            async def get_calamity(self):
                return self.calamity

            async def save_calamity(self, state):
                self.calamity = state

        class Host:
            def __init__(self):
                self.db = FakeDB()
                self.player_lock = asyncio.Lock()

            def _pl_lock(self, uid):
                return self.player_lock

            def _allowed(self, event):
                return True

            async def _require_player(self, event):
                return doc, None

            async def _dl_finish(self, event, actual_doc, result, title):
                ok, message, delta = result
                async with self.db.transaction():
                    await self.db.save_player(actual_doc.model_dump())
                    for name, qty in (delta or {}).items():
                        if qty > 0:
                            await self.db.add_items(actual_doc.uid, {name: qty})
                        elif qty < 0:
                            await self.db.remove_item(actual_doc.uid, name, -qty)
                if not ok:
                    yield event.plain_result(message)
                    return
                async for item in self._smart(event, message, title):
                    yield item

            async def _smart(self, event, message, title=""):
                yield (message, title)

        Host.handle_sd_deduce = load_deduce_handler(SimpleNamespace(
            deduce=deduce, claim_final_terror=lambda _doc: False))
        host = Host()
        result = [item async for item in host.handle_sd_deduce(object())]

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0].uid, doc.uid)
        self.assertEqual(result, [("推演完成", "推演己道")])


if __name__ == "__main__":
    unittest.main()
