import random
import unittest

from core.endless import MAX_LAYERS, make_starmap


class EndlessProgressionTests(unittest.TestCase):
    def test_each_difficulty_tier_has_150_layers_and_boss_every_ten(self):
        self.assertEqual(MAX_LAYERS, 150)
        content = {"worlds": [{"id": "w", "boss": [{"name": "Boss"}], "normal": [], "elite": []}]}
        for current in (0, 8, 9, 10, 18, 19, 20, 148, 149):
            st = {"layer": current, "world": "w"}
            nodes = make_starmap(st, content, random.Random(0))
            next_layer = current + 1
            if next_layer % 10 == 0:
                self.assertEqual(["boss"], [node["type"] for node in nodes])
            elif next_layer < MAX_LAYERS:
                self.assertEqual(3, len(nodes))
                self.assertNotIn("boss", [node["type"] for node in nodes])
            else:
                self.assertEqual("boss", nodes[0]["type"])


if __name__ == "__main__":
    unittest.main()
