import unittest

from core import plane, selfdao
from core.player import PlayerDoc


class PlaneDamageParityTests(unittest.TestCase):
    def test_selfdao_damage_updates_damage_without_destroying_planes(self):
        calamity = {
            "destroyed_planes": {"界海": {"source": "既有毁灭记录"}},
            "plane_world": {"level": 5, "bearing": 250_000,
                            "last_repair_world_year": 0},
        }

        result = plane.damage_planes(
            calamity, ["仙域", "仙域", "界海"],
            source="尸骸仙帝苏醒", actor="道友", now=123.0)

        self.assertEqual(result["planes"], ["仙域", "界海"])
        self.assertEqual(calamity["plane_damage"]["仙域"]["damage"], 10)
        self.assertEqual(calamity["plane_damage"]["仙域"]["count"], 1)
        self.assertEqual(calamity["plane_damage"]["界海"]["damage"], 10)
        self.assertEqual(calamity["destroyed_planes"], {"界海": {"source": "既有毁灭记录"}})
        self.assertEqual(result["bearing_loss"], 200_000)
        self.assertEqual(result["bearing_after"], 50_000)
        self.assertEqual(calamity["cosmic_essence_loss"], 200_000)

    def test_plane_damage_caps_at_one_hundred_and_bearing_at_zero(self):
        calamity = {
            "plane_world": {"level": 5, "bearing": 0,
                            "last_repair_world_year": 0},
            "plane_damage": {"仙域": {"damage": 95, "count": 4}},
        }

        result = plane.damage_planes(
            calamity, ["仙域"], source="尸骸仙帝苏醒", actor="道友", now=456.0)

        self.assertEqual(calamity["plane_damage"]["仙域"]["damage"], 100)
        self.assertEqual(calamity["plane_damage"]["仙域"]["count"], 5)
        self.assertEqual(result["bearing_loss"], 0)
        self.assertEqual(result["bearing_after"], 0)
        self.assertEqual(calamity["cosmic_essence_loss"], 0)

    def test_final_selfdao_terror_is_claimed_once(self):
        doc = PlayerDoc(uid="selfdao-final", ext={"selfdao": {"layers": 20}})

        self.assertTrue(selfdao.claim_final_terror(doc))
        self.assertFalse(selfdao.claim_final_terror(doc))
        self.assertTrue(doc.ext["selfdao"]["terror_triggered"])

    def test_final_selfdao_terror_requires_twentieth_layer(self):
        doc = PlayerDoc(uid="selfdao-not-final", ext={"selfdao": {"layers": 19}})

        self.assertFalse(selfdao.claim_final_terror(doc))
        self.assertFalse(doc.ext["selfdao"]["terror_triggered"])


class CausalPlaneImpactTests(unittest.TestCase):
    def test_personal_debt_uses_global_units_and_processes_at_most_three(self):
        calamity = {"plane_world": {"level": 5, "bearing": 1_000_000,
                                    "last_repair_world_year": 0},
                    "destroyed_planes": {}}
        debt_result = {"debt": 1_000, "tier": {"level": 3}}

        first = plane.apply_causal_plane_impact(
            calamity, debt_result, "道友甲", 100.0)
        second = plane.apply_causal_plane_impact(
            calamity, debt_result, "道友甲", 101.0)
        third = plane.apply_causal_plane_impact(
            calamity, {"debt": 600, "tier": {"level": 3}}, "道友乙", 102.0)

        self.assertEqual(len(first["planes"]), 3)
        self.assertEqual(first["pending_units"], 1)
        self.assertEqual(len(second["planes"]), 1)
        self.assertEqual(second["pending_units"], 0)
        self.assertIsNone(third)
        self.assertEqual(calamity["causal_plane_impact"]["processed_units"], 4)

    def test_causal_plane_pending_retries_after_no_candidates(self):
        calamity = {"plane_world": {"level": 5, "bearing": 500_000,
                                    "last_repair_world_year": 0},
                    "destroyed_planes": {
                        name: {"source": "test"}
                        for name in plane.CAUSAL_DAMAGE_PLANES
                    }}
        debt_result = {"debt": 600, "tier": {"level": 3}}

        pending = plane.apply_causal_plane_impact(
            calamity, debt_result, "道友", 200.0)
        calamity["destroyed_planes"].pop(plane.CAUSAL_DAMAGE_PLANES[0])
        retried = plane.apply_causal_plane_impact(
            calamity, debt_result, "道友", 201.0)

        self.assertEqual(pending["planes"], [])
        self.assertEqual(pending["pending_units"], 1)
        self.assertEqual(retried["planes"], [plane.CAUSAL_DAMAGE_PLANES[0]])
        self.assertEqual(retried["pending_units"], 0)

    def test_causal_damage_skips_destroyed_and_fully_damaged_planes(self):
        first, second, third = plane.CAUSAL_DAMAGE_PLANES[:3]
        calamity = {"plane_world": {"level": 5, "bearing": 500_000,
                                    "last_repair_world_year": 0},
                    "destroyed_planes": {first: {"source": "test"}},
                    "plane_damage": {second: {"damage": 100, "count": 10}}}

        impact = plane.apply_causal_plane_impact(
            calamity, {"debt": 600, "tier": {"level": 3}}, "道友", 300.0)

        self.assertEqual(impact["planes"], [third])
        self.assertEqual(calamity["plane_damage"][third]["damage"], 10)
        self.assertIn(first, calamity["destroyed_planes"])

if __name__ == "__main__":
    unittest.main()
