import ast
import asyncio
import copy
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import battle, lifespan, plane, plane_encounters, tianjiao
from core.player import PlayerDoc


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def load_plane_handlers():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    wanted = {"_plane_sync", "_plane_travel_ambush"}
    nodes = [node for node in ast.walk(tree)
             if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted]
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *nodes,
    ], type_ignores=[])
    namespace = {
        "PlayerDoc": PlayerDoc,
        "battle": battle,
        "lifespan": lifespan,
        "plane": plane,
        "plane_enc_mod": plane_encounters,
        "random": random,
        "time": SimpleNamespace(time=lambda: 100.0),
        "tj_mod": tianjiao,
    }
    exec(compile(ast.fix_missing_locations(module), str(MAIN_PATH), "exec"), namespace)
    return namespace


class _DB:
    def __init__(self):
        self.saved = []
        self.players = {}

    async def get_player(self, uid):
        raw = self.players.get(uid)
        return copy.deepcopy(raw) if raw else None

    async def save_player(self, player):
        saved = copy.deepcopy(player)
        self.saved.append(saved)
        self.players[str(saved["uid"])] = saved

    async def get_tianjiao(self):
        return {}


class PlaneTravelAmbushHandlerTests(unittest.IsolatedAsyncioTestCase):
    def make_host_and_doc(self):
        namespace = load_plane_handlers()

        class Host:
            def __init__(self):
                self.db = _DB()
                self.item_index = {}
                self.player_lock = asyncio.Lock()

            def _pl_lock(self, _uid):
                return self.player_lock

            def _plane_data(self):
                return {}

            def _tianjiao_rows(self):
                return [{"name": "天骄甲", "atk": 100, "defense": 80,
                         "hp": 90, "暴击率": 0.05}]

            def _stats(self, _doc):
                return SimpleNamespace(atk=100, defense=80, hp=100, bao=0.05)

            def _hp_pair(self, _doc):
                return 80, 100

        for name in ("_plane_sync", "_plane_travel_ambush"):
            setattr(Host, name, namespace[name])
        host = Host()
        doc = PlayerDoc(uid="traveler", name="旅人")
        st = plane.state_of(doc)
        st["current"] = "遮天位面"
        st["travel"] = {
            "from": "遮天位面", "to": "仙域", "depart": 1.0, "arrive": 50.0,
            "minutes": 1, "travel_protected": False,
        }
        doc.state = "穿梭中"
        doc.state_start = 1.0
        host.db.players[doc.uid] = copy.deepcopy(doc.model_dump())
        return host, doc

    async def test_protected_travel_skips_tianjiao_battle_and_arrives(self):
        host, doc = self.make_host_and_doc()
        plane.state_of(doc)["travel"]["travel_protected"] = True
        doc.ext["tianjiao_hatred"] = {"天骄甲": 30}
        host.db.players[doc.uid] = copy.deepcopy(doc.model_dump())

        with patch.object(battle, "spar_full", side_effect=AssertionError("protected trip fought")):
            settled, message = await host._plane_sync(doc)

        self.assertIn("抵达", message)
        self.assertEqual(plane.current(plane.state_of(settled)), "仙域")
        self.assertIsNone(plane.state_of(settled)["travel"])
        self.assertEqual(len(host.db.saved), 1)

    async def test_ambush_defeat_enters_rescue_and_does_not_settle_twice(self):
        host, doc = self.make_host_and_doc()
        plan = {"name": "天骄甲", "row": {"name": "天骄甲", "暴击率": 0.05},
                "ambush_type": "单人偷袭", "multiplier": 0.8}
        with patch.object(plane_encounters, "select_tianjiao_ambush", return_value=plan) as select, \
                patch.object(battle, "spar_full", return_value=(1, ["伏击战报"], 0, 80)):
            fallen, message = await host._plane_sync(doc)
            again, second_message = await host._plane_sync(fallen)

        self.assertIn("伏杀败北", message)
        self.assertIn("伏击战报", message)
        self.assertEqual(fallen.state, "空闲")
        self.assertEqual(plane.current(plane.state_of(fallen)), "遮天位面")
        self.assertIsNone(plane.state_of(fallen)["travel"])
        self.assertTrue(lifespan.pending(fallen))
        self.assertIsNone(second_message)
        self.assertEqual(select.call_count, 1)
        self.assertEqual(len(host.db.saved), 1)
        self.assertEqual(again.uid, fallen.uid)

    async def test_two_stale_arrival_requests_resolve_one_ambush(self):
        host, doc = self.make_host_and_doc()
        first = doc.model_copy(deep=True)
        second = doc.model_copy(deep=True)
        plan = {"name": "天骄甲", "row": {"name": "天骄甲", "暴击率": 0.05},
                "ambush_type": "单人偷袭", "multiplier": 0.8}
        with patch.object(plane_encounters, "select_tianjiao_ambush", return_value=plan) as select, \
                patch.object(battle, "spar_full", return_value=(1, ["伏击战报"], 0, 80)) as fight:
            results = await asyncio.gather(host._plane_sync(first), host._plane_sync(second))

        self.assertEqual(select.call_count, 1)
        self.assertEqual(fight.call_count, 1)
        self.assertEqual(len(host.db.saved), 1)
        self.assertEqual(sum(1 for _doc, message in results if message), 1)


class PlaneEncounterImportTests(unittest.TestCase):
    def test_plane_encounter_import_does_not_shadow_plane_events(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
        aliases = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "core":
                for item in node.names:
                    if item.name in {"plane_events", "plane_encounters"}:
                        aliases[item.name] = item.asname or item.name
        self.assertNotEqual(aliases.get("plane_events"), aliases.get("plane_encounters"))


if __name__ == "__main__":
    unittest.main()
