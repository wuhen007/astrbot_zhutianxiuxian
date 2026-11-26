import ast
import asyncio
import random
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from core import battle, lifespan, plane, plane_encounters, tianjiao
from core.player import PlayerDoc


PLUGIN = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0


def load_plane_sync():
    source = (PLUGIN / "main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    methods = [node for node in ast.walk(tree)
               if isinstance(node, ast.AsyncFunctionDef)
               and node.name in {"_plane_sync", "_plane_travel_ambush"}]
    for method in methods:
        method.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *methods,
    ], type_ignores=[])
    env = {
        "plane": plane,
        "pe_mod": plane_encounters,
        "plane_enc_mod": plane_encounters,
        "tj_mod": tianjiao,
        "lifespan": lifespan,
        "battle": battle,
        "time": SimpleNamespace(time=lambda: NOW),
        "random": random,
    }
    exec(compile(ast.fix_missing_locations(module), "main.py:plane-sync", "exec"), env)
    return env


class FakeDatabase:
    def __init__(self):
        self.world = {"bosses": {}}
        self.saved_players = []

    async def get_tianjiao(self):
        return self.world

    async def get_player(self, _uid):
        return None

    async def save_player(self, player):
        self.saved_players.append(player)


class PlaneTravelAmbushHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDatabase()
        self.host = SimpleNamespace(db=self.db, item_index={})
        self.host._player_lock = asyncio.Lock()
        self.host._pl_lock = lambda _uid: self.host._player_lock
        self.host._plane_data = lambda: {}
        self.host._tianjiao_rows = lambda: [self.row]
        self.host._stats = lambda _doc: SimpleNamespace(atk=100, defense=100, hp=1000, bao=0.0)
        self.host._hp_pair = lambda doc: (int(doc.ext.get("hp", 1000)), 1000)
        methods = load_plane_sync()
        self.host._plane_sync = MethodType(methods["_plane_sync"], self.host)
        self.host._plane_travel_ambush = MethodType(methods["_plane_travel_ambush"], self.host)
        self.row = {"name": "天骄甲", "掉落物": []}

    def traveler(self, *, protected=False, hatred=0):
        doc = PlayerDoc(uid="traveler", name="星路行者", ext={"hp": 1000})
        state = plane.state_of(doc)
        state["current"] = "凡间"
        state["travel"] = {
            "from": "凡间", "to": "仙界", "arrive": NOW - 1,
            "minutes": 30, "travel_protected": protected,
        }
        doc.state = "穿梭中"
        doc.ext["tianjiao_hatred"] = {"天骄甲": hatred} if hatred else {}
        return doc

    async def test_travel_protected_arrives_without_fighting(self):
        doc = self.traveler(protected=True, hatred=200)
        with patch.object(plane_encounters, "select_tianjiao_ambush",
                          wraps=plane_encounters.select_tianjiao_ambush) as select, \
             patch.object(battle, "spar_full") as spar:
            arrived, message = await self.host._plane_sync(doc)

        select.assert_called_once()
        spar.assert_not_called()
        self.assertEqual(plane.current(plane.state_of(arrived)), "仙界")
        self.assertIsNone(plane.travel_state(plane.state_of(arrived), NOW))
        self.assertIn("抵达·仙界", message)
        self.assertNotIn("tianjiao_offer", arrived.ext)

    async def test_no_selected_ambush_completes_normal_arrival(self):
        doc = self.traveler(hatred=0)
        with patch.object(plane_encounters, "select_tianjiao_ambush",
                          wraps=plane_encounters.select_tianjiao_ambush) as select, \
             patch.object(battle, "spar_full") as spar:
            arrived, message = await self.host._plane_sync(doc)

        select.assert_called_once()
        spar.assert_not_called()
        self.assertEqual(plane.current(plane.state_of(arrived)), "仙界")
        self.assertIn("抵达·仙界", message)
        self.assertFalse(lifespan.pending(arrived))

    async def test_winning_ambush_creates_offer_and_continues_to_destination(self):
        doc = self.traveler(hatred=200)
        plan = {"name": "天骄甲", "row": self.row, "ambush_type": "单人偷袭",
                "multiplier": 0.8}
        with patch.object(plane_encounters, "select_tianjiao_ambush", return_value=plan), \
             patch.object(battle, "spar_full", return_value=(0, ["胜利战报"], 800, 0)) as spar:
            arrived, message = await self.host._plane_sync(doc)

        spar.assert_called_once()
        self.assertEqual(plane.current(plane.state_of(arrived)), "仙界")
        self.assertEqual(arrived.ext["hp"], 800)
        self.assertEqual(arrived.ext["tianjiao_offer"]["source"], "travel_ambush")
        self.assertGreater(arrived.ext["tianjiao_fear"]["天骄甲"], NOW)
        self.assertFalse(lifespan.pending(arrived))
        self.assertIn("抵达·仙界", message)

    async def test_losing_ambush_marks_travel_rebirth_and_repeat_sync_cannot_replay(self):
        doc = self.traveler(hatred=200)
        plan = {"name": "天骄甲", "row": self.row, "ambush_type": "单人偷袭",
                "multiplier": 0.8}
        with patch.object(plane_encounters, "select_tianjiao_ambush", return_value=plan) as select, \
             patch.object(battle, "spar_full", return_value=(1, ["战败战报"], 0, 80)) as spar:
            fallen, message = await self.host._plane_sync(doc)
            again, second_message = await self.host._plane_sync(fallen)

        select.assert_called_once()
        spar.assert_called_once()
        self.assertTrue(fallen.ext.get(lifespan.TRAVEL_AMBUSH_REBIRTH))
        self.assertTrue(lifespan.pending(fallen))
        self.assertEqual(plane.current(plane.state_of(fallen)), "凡间")
        self.assertIsNone(plane.travel_state(plane.state_of(fallen), NOW))
        self.assertIn("伏杀陨落", message)
        self.assertIsNone(second_message)
        self.assertTrue(again.ext.get(lifespan.TRAVEL_AMBUSH_REBIRTH))
        self.assertEqual(len(self.db.saved_players), 1)


if __name__ == "__main__":
    unittest.main()
