import random
import unittest

from core import stone_king


class StoneKingStateTests(unittest.TestCase):
    def test_week_rollover_prunes_inactive_group_states_once(self):
        now = 1_800_000_000.0
        current_week = int(stone_king.week_key(now))
        current_state = stone_king.create_state("active", now, random.Random(1))
        old_state = dict(current_state, week_key=str(current_week - 1))
        calamity = {
            "stone_king_cleanup_week": str(current_week - 1),
            "stone_king_groups": {"inactive": old_state, "active": current_state},
        }

        state, changed = stone_king.state_for(
            calamity, "active", now, random.Random(2))

        self.assertTrue(changed)
        self.assertIs(state, current_state)
        self.assertNotIn("inactive", calamity["stone_king_groups"])
        self.assertEqual(calamity["stone_king_cleanup_week"], str(current_week))

        _, changed_again = stone_king.state_for(
            calamity, "active", now, random.Random(3))
        self.assertFalse(changed_again)


if __name__ == "__main__":
    unittest.main()
