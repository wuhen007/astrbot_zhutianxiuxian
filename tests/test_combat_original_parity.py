from __future__ import annotations

import random
import unittest

from core import battle, boss
from core.player import PlayerDoc
from core.combat.engine import Fighter, run_1v1
from core.combat.loadout import build_fighter


class SequenceRng:
    """Deterministic stand-in for Math.random()/random.Random.random()."""

    def __init__(self, *values: float):
        self.values = iter(values)
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return next(self.values)


class OriginalDamageParityTests(unittest.TestCase):
    # Golden semantics are from model/xiuxian.js at original HEAD
    # 04af6a9a7ec11e700a0aedb85a5981e48826035c (2026-11-22).
    def test_harm_uses_fixed_multiplier_and_one_random_roll(self):
        rng = SequenceRng(0.4)

        damage, crit = battle.harm(100, 100, rng, 1.5)

        self.assertEqual((damage, crit), (14, True))
        self.assertEqual(rng.calls, 1)

    def test_harm_clamps_attack_defense_ratio_boundaries_as_original(self):
        cases = (
            (99, 100, 1.0, 0.0, 9),
            (100, 100, 1.0, 0.0, 9),
            (250, 100, 1.0, 0.0, 237),
            (251, 100, 1.0, 0.0, 238),
        )
        for atk, defense, multiplier, roll, expected in cases:
            with self.subTest(atk=atk, defense=defense):
                damage, _ = battle.harm(atk, defense, SequenceRng(roll), multiplier)
                self.assertEqual(damage, expected)

    def test_crit_chance_and_multiplier_are_separate_like_original(self):
        crit_rng = SequenceRng(0.39)
        plain_rng = SequenceRng(0.40)

        self.assertEqual(battle.baojishanghai(0.4, crit_rng, 2.2), 2.2)
        self.assertEqual(battle.baojishanghai(0.4, plain_rng, 2.2), 1.0)
        self.assertEqual((crit_rng.calls, plain_rng.calls), (1, 1))

    def test_attack_rolls_crit_before_harm_randomness_like_original_call_order(self):
        rng = SequenceRng(0.39, 0.5)

        damage, crit = battle.attack_harm(100, 100, rng, 0.4, 2.2)

        self.assertEqual((damage, crit), (19, True))
        self.assertEqual(rng.calls, 2)

    def test_shenpo_zero_segment_matches_original_zero_health_boss(self):
        self.assertEqual(boss.shenpo_specs(0), (0, 0, 0, 0))

    def test_calculate_harm_uses_original_big_integer_branch(self):
        atk = 9_007_199_254_740_992
        defense = 100

        damage = battle.calculate_harm(atk, defense, SequenceRng(0.99))

        self.assertEqual(damage, atk * 850 // 1000 - defense)


class OriginalActionBarParityTests(unittest.TestCase):
    def test_faster_side_can_take_repeated_actions_before_slower_side_is_ready(self):
        fast = Fighter("快者", 1000, 1_000_000, 100_000, 100_000, speed=5000)
        slow = Fighter("慢者", 1000, 1_000_000, 100_000, 100_000, speed=100)

        result = run_1v1(fast, slow, random.Random(4), max_rounds=3)

        attackers = [line for line in result.log if "出手" in line]
        self.assertEqual(["快者" in line for line in attackers], [True, True, True])

    def test_equal_ready_speed_tie_uses_original_a_side_priority(self):
        a = Fighter("甲", 1000, 1_000_000, 100_000, 100_000, speed=5000)
        b = Fighter("乙", 1000, 1_000_000, 100_000, 100_000, speed=5000)

        result = run_1v1(a, b, random.Random(5), max_rounds=2)

        attackers = [line for line in result.log if "出手" in line]
        self.assertEqual(["甲" in line for line in attackers], [True, True])

    def test_general_duel_uses_85_percent_attack_before_original_harm(self):
        a = Fighter("甲", 1000, 100, 100_000, 100_000, speed=5000)
        b = Fighter("乙", 1, 10_000, 100_000, 100_000, speed=100)

        result = run_1v1(a, b, SequenceRng(0.99, 0.5), max_rounds=1)

        self.assertEqual(result.b_hp, 99_915)

    def test_speed_includes_legacy_dimensions_evergreen_and_innate_treasure(self):
        doc = PlayerDoc(uid="speed-parity", ext={
            "speed": 200,
            "legacy_source": {
                "mijinglevel_id": 2,
                "xiangulevel_id": 3,
                "huafenlevel_id": 4,
            },
            "suiyun": {"awake": True, "stage": 3},
            "xtzb": {"current": "逐日仙辇"},
        })

        self.assertEqual(battle.speed_of(doc), 880)

    def test_player_loadout_passes_original_speed_into_action_bar_engine(self):
        doc = PlayerDoc(uid="fighter-speed", ext={
            "speed": 200,
            "legacy_source": {
                "mijinglevel_id": 2,
                "xiangulevel_id": 3,
                "huafenlevel_id": 4,
            },
        })

        fighter = build_fighter(doc, "道友", 1000, 500, 10_000, 0.2, lambda _name: None)

        self.assertEqual(fighter.speed, 600)
        self.assertEqual(fighter.crit_damage, 1.7)

    def test_initial_ready_bar_acts_before_normal_speed_accumulation(self):
        a = Fighter("甲", 1000, 10_000, 100_000, 100_000, speed=1, action_bar=5000)
        b = Fighter("乙", 1000, 10_000, 100_000, 100_000, speed=100)

        result = run_1v1(a, b, random.Random(7), max_rounds=1)

        self.assertTrue("甲" in next(line for line in result.log if "出手" in line))

    def test_original_inner_action_bar_advance_guard_stops_very_slow_units(self):
        a = Fighter("甲", 1000, 10_000, 100_000, 100_000, speed=1)
        b = Fighter("乙", 1000, 10_000, 100_000, 100_000, speed=1)

        result = run_1v1(a, b, random.Random(8))

        self.assertEqual((result.winner, result.a_hp, result.b_hp), (None, 100_000, 100_000))
        self.assertTrue(any("强制结束" in line for line in result.log))

    def test_100_action_timeout_awards_higher_absolute_hp_and_zeros_loser(self):
        a = Fighter("甲", 1, 1_000_000, 100, 100, speed=5000)
        b = Fighter("乙", 1, 1_000_000, 200, 200, speed=5000)

        result = run_1v1(a, b, random.Random(6), max_rounds=100)

        self.assertEqual((result.winner, result.a_hp, result.b_hp), (1, 0, 200))
        self.assertTrue(any("回合上限" in line for line in result.log))


if __name__ == "__main__":
    unittest.main()
