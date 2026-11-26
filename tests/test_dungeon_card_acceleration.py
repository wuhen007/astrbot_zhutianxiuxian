import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import dungeon, addict


class DungeonCardAcceleration(unittest.TestCase):
    def test_bulk_card_allocation_uses_lowest_tiers_without_over_accelerating(self):
        cards, reduction = dungeon.allocate_settlement_cards({
            "凡品秘境结算卡": 3,
            "仙品秘境结算卡": 2,
            "帝品秘境结算卡": 1,
        }, 1900)
        self.assertEqual(cards, {"凡品秘境结算卡": 3, "仙品秘境结算卡": 2})
        self.assertEqual(reduction, 690)
    def test_addiction_acceleration_requeues_the_next_due_time(self):
        run = addict.make("青冥山", 3, now=1000)
        run["settled_count"] = 1
        updated, reduced = addict.accelerate(run, 60, now=1100)
        self.assertEqual(reduced, 60)
        self.assertEqual(updated["end"], run["end"] - 60)
        self.assertGreaterEqual(updated["next_settle_time"], 1100)
        self.assertEqual(updated["settlement_id"], run["settlement_id"])
    def test_acceleration_updates_deadline_without_changing_identity(self):
        action = {'seed': 'stable', 'starts_at': 1000, 'ends_at': 2000}
        updated, reduced = dungeon.accelerate_original_expedition(action, 300, now=1200)
        self.assertEqual(reduced, 300)
        self.assertEqual(updated['ends_at'], 1700)
        self.assertEqual(updated['seed'], 'stable')
        self.assertEqual(action['ends_at'], 2000)

    def test_acceleration_never_moves_deadline_before_now(self):
        action = {'seed': 'stable', 'starts_at': 1000, 'ends_at': 1250}
        updated, reduced = dungeon.accelerate_original_expedition(action, 600, now=1200)
        self.assertEqual(reduced, 50)
        self.assertEqual(updated['ends_at'], 1200)

    def test_expired_action_cannot_consume_acceleration(self):
        action = {'seed': 'stable', 'starts_at': 1000, 'ends_at': 1100}
        updated, reduced = dungeon.accelerate_original_expedition(action, 30, now=1200)
        self.assertEqual(reduced, 0)
        self.assertEqual(updated['ends_at'], 1100)


if __name__ == '__main__':
    unittest.main()
