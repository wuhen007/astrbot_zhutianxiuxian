import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import addict, secret
from core.battle import Unit


class AddictionRoundQueue(unittest.TestCase):
    def test_new_run_uses_individual_rounds_across_the_same_total_duration(self):
        run = addict.make("青冥山", 2, now=1_000)
        self.assertEqual(run["rounds"], 20)
        self.assertEqual(run["total_count"], 20)
        self.assertEqual(run["total_time"], 140)
        self.assertEqual(run["interval"], 420)
        self.assertEqual(addict.rounds_due(run, 1_359), 0)
        self.assertEqual(addict.rounds_due(run, 1_361), 1)
        self.assertEqual(addict.rounds_due(run, 2_621), 4)

    def test_each_round_receipt_advances_one_tick_and_keeps_reward_session_delta_local(self):
        run = addict.make("青冥山", 1, now=1_000)

        def explore(session, base, me, item_pool, rng):
            session.floor += 1
            session.stones += 30
            session.items["灵草"] = session.items.get("灵草", 0) + 1
            me.hp -= 10
            return session, me, f"第{session.floor}层", False

        with patch.object(secret, "explore", side_effect=explore):
            one, hp, delta = addict.simulate_round(
                run, (100, 100, 100), 100, 0, [], random.Random(1), 1_001,
                realm_id=1, physique_id=1)
            expected = secret.original_win_rewards(1, 1, random.Random(1))
            self.assertEqual(delta, {"stones": 30, "exp": expected["exp"],
                                     "xueqi": expected["xueqi"],
                                     "items": {"灵草": 1}, "fled": False,
                                     "log": "第1层"})
            self.assertEqual(one["settled_count"], 1)
            self.assertEqual(one["session"]["floor"], 1)
            self.assertEqual(one["session"]["stones"], 0)
            self.assertEqual(one["session"]["items"], {})
            two, hp, delta_two = addict.simulate_round(
                one, (100, 100, 100), hp, 0, [], random.Random(2), 1_721)
        self.assertEqual(two["settled_count"], 2)
        self.assertEqual(two["items_gained"], {"灵草": 2})
        self.assertEqual(delta_two["items"], {"灵草": 1})

    def test_failure_stops_queue_but_preserves_earlier_rounds(self):
        run = addict.make("青冥山", 1, now=1_000)
        run["settled_count"] = 2
        run["done"] = 2
        run["next_settle_time"] = run["start"] + 3 * run["interval"]
        run["stones"] = 50
        run["items_gained"] = {"灵草": 2}
        run["items"] = {"灵草": 2}

        def lose(session, base, me, item_pool, rng):
            session.floor += 1
            me.hp = 0
            return session, me, "战败", True

        with patch.object(secret, "explore", side_effect=lose):
            result, _hp, delta = addict.simulate_round(
                run, (100, 100, 100), 100, 0, [], random.Random(1), 2_301)
        self.assertEqual(result["status"], "died")
        self.assertEqual(result["settled_count"], 3)
        self.assertEqual(result["stones"], 50)
        self.assertEqual(result["items_gained"], {"灵草": 2})
        self.assertTrue(delta["fled"])
        self.assertEqual(delta["exp"], 800)
        self.assertEqual(delta["xueqi"], 0)
        self.assertEqual(addict.rounds_due(result, 1_500), 0)


if __name__ == "__main__":
    unittest.main()
