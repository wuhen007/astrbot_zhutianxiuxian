import ast
import asyncio
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import calamity, reincarnation, xiangu, xiangu_baodi


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def load_advance_method():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.AsyncFunctionDef)
              and node.name == "_advance_unclaimed_relics")
    fn.decorator_list = []
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            node.level = 0
    module = ast.Module(body=[fn], type_ignores=[])
    namespace = {"calamity": calamity, "reincarnation_mod": reincarnation,
                 "xgm_mod": xiangu, "xbd_mod": xiangu_baodi}
    # The extracted method imports its module alias locally; remove that now-bound import.
    fn.body = [node for node in fn.body
               if not (isinstance(node, ast.ImportFrom)
                       and any(alias.name == "reincarnation" for alias in node.names))]
    exec(compile(ast.fix_missing_locations(module), str(MAIN_PATH), "exec"), namespace)
    return namespace["_advance_unclaimed_relics"]


class _DB:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.calamity_lock = asyncio.Lock()
        self.saves = 0

    async def get_calamity(self):
        return copy.deepcopy(self.state)

    async def save_calamity(self, value):
        self.state = copy.deepcopy(value)
        self.saves += 1


class UnclaimedRelicConversionTests(unittest.IsolatedAsyncioTestCase):
    async def test_converts_only_unclaimed_old_high_level_drops_once(self):
        now = 100_000.0
        old = now - xiangu_baodi.RELIC_UNCLAIMED_MS / 1000 - 1
        recent = now - xiangu_baodi.RELIC_UNCLAIMED_MS / 1000 + 1
        state = {
            "reincarnation": {"mode": "纳戒", "drops": [
                {"id": "eligible", "uid": "u1", "name": "高境修士", "owner_level": 42,
                 "plane": "凡间", "items": {"灵药": 3}, "stones": 9,
                 "source_stones": 2, "t": old, "exp": now + 100_000},
                {"id": "recent", "uid": "u2", "name": "近期修士", "owner_level": 80,
                 "plane": "仙界", "items": {"灵药": 1}, "stones": 0,
                 "source_stones": 0, "t": recent, "exp": now + 100_000},
                {"id": "low", "uid": "u3", "name": "低境修士", "owner_level": 41,
                 "plane": "凡间", "items": {"灵药": 1}, "stones": 0,
                 "source_stones": 0, "t": old, "exp": now + 100_000},
            ]},
            "xiangu": {},
        }
        host = SimpleNamespace(db=_DB(state))
        advance = load_advance_method()

        converted = await advance(host, now)

        self.assertEqual(converted, 1)
        self.assertEqual({row["id"] for row in host.db.state["reincarnation"]["drops"]},
                         {"recent", "low"})
        sites = host.db.state["xiangu"]["baodi"]
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["source_drop_id"], "eligible")
        self.assertEqual(sites[0]["loot"], {"灵药": 3})
        self.assertEqual(sites[0]["stones"], 9)
        self.assertEqual(await advance(host, now + 1), 0)
        self.assertEqual(len(host.db.state["xiangu"]["baodi"]), 1)
        self.assertEqual(host.db.saves, 1)


if __name__ == "__main__":
    unittest.main()
