import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import extra_cultivation, lifespan, reincarnation
from core.player import PlayerDoc


class LifespanReincarnationTests(unittest.TestCase):
    def test_lifespan_depletion_is_reported_only_when_crossing_zero(self):
        doc = PlayerDoc(uid="target", ext={"shouyuan": 10})

        self.assertEqual(lifespan.daily_decay(doc, 86_400), (10, True))
        self.assertEqual(lifespan.daily_decay(doc, 172_800), (0, False))

    def test_rescue_closes_after_five_minutes_unless_held_for_decision(self):
        expired = PlayerDoc(uid="target", ext={
            "shouyuan": 0, "awaiting_rescue": True, "rescue_deadline": 300,
        })
        self.assertFalse(lifespan.rescue(expired, 300)[0])

        held = expired.model_copy(deep=True)
        held.ext["reincarnation_phase"] = "decision"
        self.assertTrue(lifespan.rescue(held, 301, controller_pending=True)[0])

    def test_travel_ambush_rebirth_uses_five_minute_rescue_without_changing_lifespan(self):
        fallen = PlayerDoc(uid="travel", name="旅者", ext={"shouyuan": 2400, "hp": 1})
        message = lifespan.mark_travel_ambush_death(fallen, 100.0)
        self.assertIn("5 分钟", message)
        self.assertTrue(lifespan.pending(fallen))
        self.assertEqual(lifespan.rescue_left(fallen, 100.0), 300)
        self.assertEqual(fallen.ext["shouyuan"], 2400)

        ok, _ = lifespan.rescue(fallen, 399.0)
        self.assertTrue(ok)
        self.assertFalse(lifespan.pending(fallen))
        self.assertEqual(fallen.ext["shouyuan"], 2400)
        self.assertFalse(fallen.ext.get("travel_ambush_rebirth"))

    def test_expired_travel_ambush_can_still_be_rescued_when_controller_holds_it(self):
        fallen = PlayerDoc(uid="travel-held", name="旅者", ext={
            "shouyuan": 2400, "hp": 1, "awaiting_rescue": True,
            "rescue_deadline": 300.0, "travel_ambush_rebirth": True,
            "reincarnation_phase": "decision",
        })
        ok, _ = lifespan.rescue(fallen, 301.0, controller_pending=True)
        self.assertTrue(ok)
        self.assertFalse(lifespan.pending(fallen))
        self.assertEqual(fallen.ext["shouyuan"], 2400)
        self.assertFalse(fallen.ext.get("travel_ambush_rebirth"))

    def test_denial_or_difficulty_restore_keeps_travel_ambush_lifespan(self):
        denied = PlayerDoc(uid="travel-denied", ext={
            "shouyuan": 2400, "hp": 0, "awaiting_rescue": True,
            "rescue_deadline": 300.0, "travel_ambush_rebirth": True,
        })
        self.assertTrue(lifespan.restore_expired_rescue(denied))
        self.assertEqual(denied.ext["shouyuan"], 2400)
        self.assertEqual(denied.ext["hp"], 1)
        self.assertFalse(lifespan.pending(denied))

    def test_travel_ambush_forces_rebirth_even_when_lifespan_difficulty_is_nonlethal(self):
        fallen = PlayerDoc(uid="travel-expired", realm_index=9, exp=50, stones=100,
                           ext={"shouyuan": 2400, "hp": 1, "awaiting_rescue": True,
                                "rescue_deadline": 300.0, "travel_ambush_rebirth": True})
        message = lifespan.resolve_if_due(fallen, 301.0, forced=False)
        self.assertIn("轮回往生", message)
        self.assertEqual(fallen.ext["rebirths"], 1)
        self.assertFalse(fallen.ext.get("travel_ambush_rebirth"))

    def test_only_current_controller_can_decide_a_pending_rebirth_once(self):
        controller = PlayerDoc(uid="controller")
        extra_cultivation.set_level(controller, "mijing", 16)
        outsider = PlayerDoc(uid="outsider")
        target = PlayerDoc(uid="target", name="待往生者", ext={
            "shouyuan": 0, "awaiting_rescue": True, "rescue_deadline": 300,
        })
        world = {"reincarnation": {
            "controller": {"uid": controller.uid, "name": "执掌者", "authority": 16},
            "pending": {},
        }}

        self.assertTrue(reincarnation.queue_decision(world, target, 301)[0])
        self.assertFalse(reincarnation.decide(world, target.uid, outsider, "allow", 302)[0])
        self.assertTrue(reincarnation.decide(world, target.uid, controller, "allow", 303)[0])
        self.assertFalse(reincarnation.decide(world, target.uid, controller, "allow", 304)[0])

    def test_drop_requires_memory_and_matching_location_then_cannot_be_claimed_twice(self):
        owner = PlayerDoc(uid="owner", name="遗物主人")
        world = {}
        row = reincarnation.make_drop(
            world, owner, "凡间", {"x": 12, "y": 34}, 20, {"灵药": 2}, 1_000.0,
        )
        self.assertIsNotNone(row)
        self.assertFalse(reincarnation.can_claim(row, "凡间", {"x": 12, "y": 34}, []))
        memories = owner.ext[reincarnation.DROP_MEMORY_KEY]
        self.assertFalse(reincarnation.can_claim(row, "凡间", {"x": 12, "y": 35}, memories))
        self.assertTrue(reincarnation.can_claim(row, "凡间", {"x": 12, "y": 34}, memories))

        self.assertTrue(reincarnation.claim(world, row, 1_001.0, owner.uid)[0])
        self.assertFalse(reincarnation.claim(world, row, 1_002.0, owner.uid)[0])


if __name__ == "__main__":
    unittest.main()
