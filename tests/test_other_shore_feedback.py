import unittest

from core import other_shore_world


class OtherShoreFeedbackTests(unittest.TestCase):
    def test_invalid_coordinate_returns_player_facing_error_instead_of_raising(self):
        world = other_shore_world.create_other_shore_world("web-invalid-coordinate")
        star, error = other_shore_world.find_star(world, {"q": 6, "r": 4})

        self.assertIsNone(star)
        self.assertIn("坐标不存在", error)
        self.assertIn("6,4", error)

    def test_valid_coordinate_returns_star_without_error(self):
        world = other_shore_world.create_other_shore_world("web-valid-coordinate")
        star, error = other_shore_world.find_star(world, {"q": 0, "r": 0})

        self.assertIsNotNone(star)
        self.assertEqual(star["id"], "0,0")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
