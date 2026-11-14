import unittest

from core import xiangu as xg
from core import xiangu_npc as npc


class XianguAutonomyTests(unittest.TestCase):
    def make_state(self, hostile=True):
        grid = [[xg.CELL_EMPTY for _ in range(5)] for _ in range(5)]
        grid[1][1] = xg.CELL_NPC
        grid[3][3] = xg.CELL_TREASURE
        return {"npc_relations": {}, "map": {
            "grid": grid, "revealed": [[False] * 5 for _ in range(5)],
            "pos": {"x": 3, "y": 1},
            "npc_locations": [{"x": 1, "y": 1, "under_cell": xg.CELL_EMPTY,
                               "npc": {"id": "hunter", "name": "追猎者",
                                       "hostile": hostile, "faction": "evil"}}],
        }}

    def test_initial_delay_then_hostile_npc_moves_one_bfs_step(self):
        st = self.make_state()
        self.assertEqual(npc.advance_autonomous(st, 1_000), {"initialized": True, "moved": False})
        ecology = st["map"]["npcEcology"]
        self.assertEqual(ecology["nextActionAt"], 16_000)
        self.assertIsNone(npc.advance_autonomous(st, 15_999))
        result = npc.advance_autonomous(st, 16_000)
        self.assertEqual(result["from"], (1, 1))
        self.assertEqual(result["to"], (2, 1))
        self.assertEqual(st["map"]["grid"][1][1], xg.CELL_EMPTY)
        self.assertEqual(st["map"]["grid"][1][2], xg.CELL_NPC)
        self.assertEqual(st["map"]["npcEcology"]["nextActionAt"], 46_000)
        self.assertIsNone(npc.advance_autonomous(st, 45_999))

    def test_neutral_npc_follows_nearest_treasure(self):
        st = self.make_state(hostile=False)
        npc.advance_autonomous(st, 1_000)
        moved = npc.advance_autonomous(st, 16_000)
        self.assertIsNotNone(moved)
        self.assertEqual(moved["to"], (2, 2))
        self.assertFalse(moved["hostile"])


if __name__ == "__main__":
    unittest.main()
