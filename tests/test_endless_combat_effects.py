import random
import unittest

from core.battle import Unit
from core.combat import Fighter, run_1v1
from core.endless import _fold_effect, run_stats


class EndlessCombatEffectTests(unittest.TestCase):
    def test_proc_effects_remain_independent_from_static_stats(self):
        effect = _fold_effect({
            "dodgeChance": 0.2,
            "damageReduction": 0.3,
            "reflectChance": 0.4,
            "reflectPct": 0.5,
            "extraActionChance": 0.25,
            "executePct": 0.6,
            "summonPct": 0.7,
        })
        self.assertEqual(0, effect["def"])
        self.assertEqual(0, effect["atk"])
        self.assertEqual(0.2, effect["dodgeChance"])
        self.assertEqual(0.3, effect["damageReduction"])
        self.assertEqual(0.4, effect["reflectChance"])
        self.assertEqual(0.5, effect["reflectPct"])
        self.assertEqual(0.25, effect["extraActionChance"])
        self.assertEqual(0.6, effect["executePct"])
        self.assertEqual(0.7, effect["summonPct"])

    def test_run_stats_exposes_all_dynamic_proc_fields_and_tag_bonuses(self):
        content = {
            "abilities": [{
                "id": "fire",
                "tags": ["火焰"],
                "effect": {
                    "comboAttackPct": 0.1,
                    "takeDamageAttackPct": 0.05,
                    "onWinAttackPct": 0.02,
                    "victoryHealPct": 0.03,
                    "fireScalingPct": 0.01,
                    "teamShieldPct": 0.04,
                },
            }],
            "checkpointBoons": [],
            "worlds": [],
        }
        stats = run_stats({"abilities": {"fire": 3}, "boons": []},
                          {"atk": 100, "def": 10, "hp": 100, "bao": 0.05}, content)
        self.assertAlmostEqual(0.3, stats["comboAttackPct"])
        self.assertAlmostEqual(0.15, stats["takeDamageAttackPct"])
        self.assertAlmostEqual(0.06, stats["onWinAttackPct"])
        self.assertAlmostEqual(0.09, stats["victoryHealPct"])
        self.assertAlmostEqual(0.03, stats["fireScalingPct"])
        self.assertAlmostEqual(0.12, stats["teamShieldPct"])
        self.assertEqual(1.17, stats["atk_mult"])

    def test_guaranteed_dodge_prevents_damage(self):
        a = Fighter("attacker", 100, 0, 100, 100)
        b = Fighter("dodger", 1, 0, 100, 100, effects={"dodge_chance": 1.0})
        result = run_1v1(a, b, random.Random(1), max_rounds=1)
        self.assertEqual(100, result.b_hp)
        self.assertEqual(100, result.a_hp)
        self.assertIn("避开", "".join(result.log))


if __name__ == "__main__":
    unittest.main()
