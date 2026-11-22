import ast
import random
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from core import superdim
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

        class Host:
            def _allowed(self, event):
                return True

            async def _require_player(self, event):
                return doc, None

            async def _dl_finish(self, event, actual_doc, result, title):
                yield (actual_doc, result, title)

        Host.handle_sd_deduce = load_deduce_handler(SimpleNamespace(deduce=deduce))
        host = Host()
        result = [item async for item in host.handle_sd_deduce(object())]

        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], doc)
        self.assertEqual(result, [(doc, (True, "推演完成", {}), "推演己道")])


if __name__ == "__main__":
    unittest.main()
