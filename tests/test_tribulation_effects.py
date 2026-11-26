import unittest
from types import SimpleNamespace

from core import daolu, memory, story_npc
from core.player import PlayerDoc


class _SequenceRng:
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class TribulationEffectsTests(unittest.TestCase):
    def test_memory_time_revival_uses_original_tier_cost_once_per_attempt(self):
        doc = SimpleNamespace(ext={
            "linggen": {"name": memory.STAGES[1]["name"]},
            "memory": {"factors": {"时间": 2}},
            "life_source": 400,
            "hp": 1,
            "hp_max": 900,
        })
        state = memory.create_tribulation_state()
        memory.tick_tribulation_round(state)
        result = memory.try_time_tribulation_revival(doc, state, lethal=True)

        self.assertTrue(result["revived"])
        self.assertEqual(result["cost"], 400)
        self.assertEqual(doc.ext["life_source"], 0)
        self.assertEqual(doc.ext["hp"], 900)
        self.assertFalse(memory.try_time_tribulation_revival(doc, state, lethal=True)["revived"])

    def test_memory_time_revival_does_not_spend_origin_without_lethal_damage(self):
        doc = SimpleNamespace(ext={
            "linggen": {"name": memory.STAGES[0]["name"]},
            "memory": {"factors": {"时间": 1}},
            "life_source": 500,
            "hp": 400,
            "hp_max": 900,
        })
        result = memory.try_time_tribulation_revival(
            doc, memory.create_tribulation_state(), lethal=False)

        self.assertFalse(result["revived"])
        self.assertEqual(doc.ext["life_source"], 500)

    def test_帝路自动复活_applies_the_selected_skill_and_refunds_failure_loss(self):
        doc = PlayerDoc(uid="daolu-revive", realm_index=15, physique_index=0,
                        exp=2_000_000, ext={"xueqi": 2_000_000, "potential": 5,
                                           "hp": 900_000, "hp_max": 1_000_000,
                                           "life_source": 100, "gongfa": ["柳神法"]})
        ok, message, _ = daolu.run(doc, "斩道", {"qi_cost": 1.0}, now=1_800_000_000,
                                   rng=_SequenceRng(.99))
        self.assertFalse(ok)
        self.assertIn("复活功法", message)
        self.assertIn("柳神法", message)
        self.assertEqual(doc.exp, 2_000_000 - daolu.BASE_COST)
        self.assertEqual(doc.ext["xueqi"], int((2_000_000 - daolu.BASE_COST) * .75))
        self.assertEqual(doc.ext["life_source"], 50)
        self.assertGreater(doc.ext["hp"], 0)

    def test_black_emperor_formation_consumes_pending_and_applies_original_multiplier(self):
        state = {"trib_pending": True, "chars": {"黑皇": {"events": []}}}
        result = story_npc.resolve_tribulation_formation(state, _SequenceRng(0.1, 0.5))

        self.assertTrue(result["consumed"])
        self.assertTrue(result["success"])
        self.assertEqual(result["damage_multiplier"], 0.75)
        self.assertEqual(result["range_shift"], 0)
        self.assertFalse(state["trib_pending"])

    def test_black_emperor_formation_failure_still_consumes_the_attempt(self):
        state = {"trib_pending": True}
        result = story_npc.resolve_tribulation_formation(state, _SequenceRng(0.9))

        self.assertTrue(result["consumed"])
        self.assertFalse(result["success"])
        self.assertEqual(result["damage_multiplier"], 1.0)
        self.assertFalse(state["trib_pending"])


if __name__ == "__main__":
    unittest.main()
