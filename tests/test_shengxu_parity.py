import unittest
from types import SimpleNamespace

from core import shengxu


class FixedRandom:
    def __init__(self, values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class ShengxuParityTests(unittest.TestCase):
    def test_field_bonus_scales_only_flower_base_stats_and_caps_at_nine(self):
        realm = {"基础攻击": 1_000_000, "基础防御": 2_000_000, "基础血量": 3_000_000}
        self.assertEqual(
            shengxu.field_attribute_bonus(realm, 9, path_multiplier=1.2),
            {"atk": 324_000, "defense": 648_000, "hp": 972_000},
        )
        self.assertEqual(shengxu.field_attribute_bonus(realm, 99),
                         {"atk": 270_000, "defense": 540_000, "hp": 810_000})

    def test_skill_trigger_uses_original_order_and_one_proc_per_action(self):
        attacker = SimpleNamespace(
            name="楚风", atk=1_000, hp_max=5_000,
            tags={"shengxu_flower_skills": ("大力牛魔拳", "终极拳"), "shengxu_field_stage": 0},
        )
        defender = SimpleNamespace(name="异变生灵", atk=5_000, effects={})
        hp = [5_000, 10_000]
        log = []
        triggered = shengxu.trigger_flower_pollen_skill(
            attacker, defender, {"hp": hp, "side": 0, "rng": FixedRandom([0.5, 0.0]), "log": log},
        )
        self.assertTrue(triggered)
        self.assertEqual(hp, [5_000, 8_400])
        self.assertIn("终极拳", log[0])
        self.assertEqual(len(log), 1)

    def test_field_suppression_uses_original_four_percent_stage_growth(self):
        attacker = SimpleNamespace(
            name="楚风", atk=1_000, hp_max=5_000,
            tags={"shengxu_flower_skills": ("场域法·镇",), "shengxu_field_stage": 9},
        )
        defender = SimpleNamespace(name="阳间神祇", atk=10_000, effects={})
        shengxu.trigger_flower_pollen_skill(
            attacker, defender, {"hp": [5_000, 10_000], "side": 0,
                                 "rng": FixedRandom([0.0]), "log": []},
        )
        self.assertEqual(defender.atk, 8_369)  # JS Math.floor preserves the source float result

    def test_tier_rates_accept_original_mapping_and_era_tuple(self):
        dungeon = shengxu.dungeon_of("太行山")
        self.assertIsNone(shengxu.resolve_tier_reward(
            dungeon, FixedRandom([0.5]), {"one": 0.0, "two": 0.5, "three": 0.25},
        ))
        reward = shengxu.resolve_tier_reward(dungeon, FixedRandom([0.0, 0.5, 0.0]), (1.0, 0.0, 0.0))
        self.assertEqual(reward["tier"], "one")
        self.assertEqual(reward["name"], "普通进化花粉")

    def test_memory_guarantees_skip_awarded_and_permanently_unique_items(self):
        dungeon = shengxu.dungeon_of("阳间名山")
        already = {"神性进化花粉", "道引呼吸法"}
        drops = shengxu._guaranteed_recollection(
            dungeon, already, ("one", "two", "three"), "receipt-1",
            lambda name: {"name": name, "全服唯一": True} if name == "本源异果" else {"name": name},
            multiplier=3,
        )
        self.assertEqual(len(drops), 1)
        self.assertNotIn(drops[0][0], {"神性进化花粉", "道引呼吸法", "本源异果"})
        self.assertEqual(drops[0][1], 3)


if __name__ == "__main__":
    unittest.main()
