import ast
import re
import sys
import unittest
from copy import deepcopy
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from core import xiangu
from core.player import PlayerDoc


class XianguExploreCommandContractTests(unittest.TestCase):
    def test_explore_reveals_map_without_rolling_loot_or_waiting_for_numbers(self):
        doc = PlayerDoc(
            uid="explore-contract",
            name="探索测试",
            realm_index=16,
            ext={"hp": 2_000_000, "xueqi": 0, "potential": 0},
        )
        st = xiangu.state_of(doc)
        st["active"] = True
        map_st = st["map"] = xiangu.new_run_map("explore-contract-seed")
        bag = deepcopy(st["bag"])
        pos = map_st["pos"].copy()

        text, events = xiangu.explore_turn(
            doc, st, xiangu.seeded_rng("explore-contract-turn"), 1_000_000, {}
        )
        self.assertTrue(events["explored"])
        self.assertTrue(map_st["revealed"][pos["y"]][pos["x"]])
        self.assertGreater(sum(sum(row) for row in map_st["revealed"]), 1)
        self.assertEqual(map_st["pos"], pos)
        self.assertEqual(st["bag"], bag)
        self.assertNotIn("即时结算", text)
        self.assertNotIn("1/2/3", text)

        st["evac"] = {"mode": "emergency"}
        before = deepcopy(st)
        text, events = xiangu.explore_turn(
            doc, st, xiangu.seeded_rng("explore-contract-blocked"), 1_001_000, {}
        )
        self.assertFalse(events["explored"])
        self.assertIn("探索冷却中", text)
        self.assertEqual(st, before)

        text, events = xiangu.explore_turn(
            doc, st, xiangu.seeded_rng("explore-contract-ready"), 1_025_000, {}
        )
        self.assertTrue(events["explored"])
        self.assertIn("撤离中断", text)
        self.assertNotIn("evac", st)

    def test_area_travel_uses_any_revealed_exit_without_standing_on_it(self):
        doc = PlayerDoc(
            uid="zone-travel-contract",
            name="跨区测试",
            realm_index=20,
            ext={"hp": 10_000, "xueqi": 0, "potential": 0},
        )
        st = xiangu.state_of(doc)
        st["active"] = True
        st["world_seed"] = "zone-travel-contract"
        map_st = st["map"] = xiangu.create_fragment_state(
            st["world_seed"], "edge_camp", {"right": "ancient_ruins"}
        )
        st["location"] = "边缘区域"
        exit_pos = map_st["exit_positions"][0]
        map_st["revealed"][exit_pos["y"]][exit_pos["x"]] = True
        self.assertNotEqual(map_st["pos"], {"x": exit_pos["x"], "y": exit_pos["y"]})

        class SafeTravelRng:
            def random(self):
                return 0.99

        text, events = xiangu.move_to_zone(
            doc, st, "中层区域", xiangu.load_config(), SafeTravelRng(), 1_000.0
        )
        self.assertEqual(events["transition"], "ancient_ruins")
        self.assertEqual(st["location"], "中层区域")
        self.assertIn("edge_camp", st["history"])
        self.assertIn("移动时间", text)
        self.assertEqual(doc.ext["hp"], 10_000)

    def test_area_travel_applies_original_ambush_damage(self):
        doc = PlayerDoc(
            uid="zone-travel-ambush",
            name="跨区遭遇测试",
            realm_index=20,
            ext={"hp": 10_000, "xueqi": 0, "potential": 0},
        )
        st = xiangu.state_of(doc)
        st["active"] = True
        st["world_seed"] = "zone-travel-ambush"
        st["map"] = xiangu.create_fragment_state(
            st["world_seed"], "edge_camp", {"right": "ancient_ruins"}
        )
        st["location"] = "边缘区域"
        exit_pos = st["map"]["exit_positions"][0]
        st["map"]["revealed"][exit_pos["y"]][exit_pos["x"]] = True

        class AmbushTravelRng:
            values = iter((0.0, 0.0, 0.3))

            def random(self):
                return next(self.values)

        text, events = xiangu.move_to_zone(
            doc, st, "中层区域", xiangu.load_config(), AmbushTravelRng(), 1_000.0
        )
        self.assertEqual(events["encounter"], "伏击")
        self.assertEqual(events["hp_loss"], 1_000)
        self.assertEqual(doc.ext["hp"], 9_000)
        self.assertIn("移动意外·伏击", text)

    def test_area_travel_keeps_original_realm_gate(self):
        doc = PlayerDoc(
            uid="zone-travel-gate",
            name="低境界测试",
            realm_index=12,
            ext={"hp": 10_000, "xueqi": 0, "potential": 0},
        )
        st = xiangu.state_of(doc)
        st["active"] = True
        st["map"] = xiangu.create_fragment_state(
            "zone-travel-gate", "edge_camp", {"right": "dark_prison"}
        )
        st["location"] = "边缘区域"
        exit_pos = st["map"]["exit_positions"][0]
        st["map"]["revealed"][exit_pos["y"]][exit_pos["x"]] = True
        before = st["map"]["pos"].copy()

        text, events = xiangu.move_to_zone(
            doc, st, "深层区域", xiangu.load_config(), xiangu.seeded_rng("zone-gate"), 1_000.0
        )
        self.assertIn("境界不足", text)
        self.assertIsNone(events["transition"])
        self.assertEqual(st["map"]["pos"], before)

    def test_numeric_reward_flow_is_removed_from_the_active_port(self):
        source = (PLUGIN / "core" / "xiangu.py").read_text(encoding="utf-8")
        self.assertFalse(hasattr(xiangu, "perform_explore"))
        self.assertNotIn("generate_explore_options", source)
        self.assertNotIn("choose_explore", source)
        self.assertNotIn("_explore_boss", source)
        self.assertNotIn("XianguExploreChoice", (PLUGIN / "main.py").read_text(encoding="utf-8"))

    def test_original_named_areas_normalize_for_fragment_exit_travel(self):
        self.assertEqual(xiangu.normalize_zone_name("仙古花蕾·核心"), "核心区域")
        self.assertEqual(xiangu.normalize_zone_name("仙古擂台"), "擂台区域")
        self.assertEqual(xiangu.normalize_zone_name("万火深渊"), "火道禁区")

    def test_map_actions_are_registered_without_bare_numeric_choices(self):
        source = (PLUGIN / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "ZhutianPlugin")
        methods = {node.name: node for node in plugin.body if isinstance(node, ast.AsyncFunctionDef)}

        for handler, command in (("handle_xgm_explore", "CMD_XGM_EXPLORE"),
                                 ("handle_xgm_move_area", "CMD_XGM_MOVE")):
            decorators = methods[handler].decorator_list
            self.assertTrue(any(isinstance(d, ast.Call) and ast.unparse(d.func) == "filter.command"
                                and d.args and isinstance(d.args[0], ast.Name) and d.args[0].id == command
                                for d in decorators), handler)
        directions = next(d.args[0].value for d in methods["handle_xgm_move"].decorator_list
                          if isinstance(d, ast.Call) and ast.unparse(d.func) == "filter.regex")
        for direction in ("#上", "#下", "#左", "#右", "#左上5", "#右下"):
            self.assertIsNotNone(re.fullmatch(directions, direction))
        for name, handler in methods.items():
            if name.startswith("handle_xgm_"):
                for d in handler.decorator_list:
                    if isinstance(d, ast.Call) and ast.unparse(d.func) == "filter.regex":
                        for number in "123":
                            self.assertIsNone(re.match(d.args[0].value, number), name)
        self.assertNotIn("handle_xgm_choice", methods)
        self.assertNotIn('"xg.choice":', source)


if __name__ == "__main__":
    unittest.main()
