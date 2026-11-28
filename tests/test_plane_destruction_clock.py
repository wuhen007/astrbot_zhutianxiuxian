import random
import unittest

from core import plane_destruction


class PlaneDestructionClockTests(unittest.TestCase):
    def test_first_round_waits_ten_seconds_and_destroys_at_most_two(self):
        state = {}
        clock = plane_destruction.sync(state, "big-1", 12_000, 100.0)
        destroyed = {}
        rng = random.Random(2)

        before = plane_destruction.tick(clock, 12_000, 109.9, destroyed, rng)
        first = plane_destruction.tick(clock, 12_000, 110.0, destroyed, rng)

        self.assertEqual(before, [])
        self.assertLessEqual(len(first), 2)
        self.assertTrue(set(first).issubset(plane_destruction.DESTRUCTION_PLANES))
        self.assertFalse(clock["first_round_pending"])
        self.assertEqual(clock["next_world_year"], 16_000)

    def test_cycle_waits_for_absolute_world_year_and_skips_destroyed_and_protected(self):
        clock = plane_destruction.sync({}, "big-1", 10_000, 100.0)
        plane_destruction.tick(clock, 10_000, 110.0, {}, random.Random(1))
        destroyed = {name: {"source": "prior"}
                     for name in plane_destruction.DESTRUCTION_PLANES[:4]}
        clock["protected_planes"] = {plane_destruction.DESTRUCTION_PLANES[4]: {"uid": "owner"}}

        early = plane_destruction.tick(clock, 13_999, 140.0, destroyed, random.Random(3))
        due = plane_destruction.tick(clock, 14_000, 170.0, destroyed, random.Random(3))

        self.assertEqual(early, [])
        self.assertTrue(due)
        self.assertTrue(set(due).isdisjoint(destroyed))
        self.assertNotIn(plane_destruction.DESTRUCTION_PLANES[4], due)
        self.assertEqual(clock["next_world_year"], 16_000)

    def test_long_year_jump_schedules_one_round_without_catchup_burst(self):
        clock = plane_destruction.sync({}, "big-1", 2_000, 100.0)
        plane_destruction.tick(clock, 2_000, 110.0, {}, random.Random(1))

        round1 = plane_destruction.tick(clock, 9_000, 140.0, {}, random.Random(2))
        round2_early = plane_destruction.tick(clock, 9_000, 170.0, {}, random.Random(3))
        round2_due = plane_destruction.tick(clock, 9_001, 200.0, {}, random.Random(4))

        self.assertTrue(round1)
        self.assertEqual(round2_early, [])
        self.assertTrue(round2_due)
        self.assertEqual(clock["next_world_year"], 11_001)

    def test_single_rescue_protects_only_eligible_unbroken_plane(self):
        clock = plane_destruction.sync({}, "big-1", 12_000, 100.0)
        destroyed = {plane_destruction.DESTRUCTION_PLANES[0]: {"source": "prior"}}
        target = plane_destruction.DESTRUCTION_PLANES[1]

        ok, _message = plane_destruction.protect(clock, target, "owner", "主宰", 12_000, 120.0,
                                                  destroyed)
        again, _message = plane_destruction.protect(clock, plane_destruction.DESTRUCTION_PLANES[2],
                                                     "other", "天尊", 12_000, 121.0, destroyed)
        invalid, _message = plane_destruction.protect(clock, plane_destruction.DESTRUCTION_PLANES[0],
                                                       "third", "圣人", 12_000, 122.0, destroyed)

        self.assertTrue(ok)
        self.assertFalse(again)
        self.assertFalse(invalid)
        self.assertTrue(clock["rescue_used"])
        self.assertIn(target, clock["protected_planes"])

    def test_syncing_another_activity_resets_round_and_rescue_state(self):
        state = {}
        first = plane_destruction.sync(state, "big-1", 4_000, 100.0)
        first["rescue_used"] = True
        first["rounds"] = 5
        second = plane_destruction.sync(state, "big-2", 4_000, 200.0)

        self.assertEqual(second["activity_id"], "big-2")
        self.assertFalse(second["rescue_used"])
        self.assertEqual(second["rounds"], 0)
        self.assertTrue(plane_destruction.sync(state, None, 4_000, 201.0)["stopped"])


if __name__ == "__main__":
    unittest.main()
