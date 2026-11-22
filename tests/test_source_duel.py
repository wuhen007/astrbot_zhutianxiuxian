import unittest
from types import SimpleNamespace

from core import source_duel, yuanshi


class SourceDuelRulesTests(unittest.TestCase):
    def test_npc_risk_and_fee_progression_matches_original_catalog(self):
        self.assertEqual(
            [(npc["name"], npc["wager"], npc["stone_fee"], npc["skill"])
             for npc in source_duel.NPCS],
            [("吴子明", 200_000, 200_000, 0.12),
             ("拓跋昌", 1_000_000, 1_000_000, 0.58),
             ("南宫奇", 5_000_000, 5_000_000, 0.92)],
        )

    def test_session_generates_two_unique_five_stone_batches_and_job_insight(self):
        session = source_duel.create_session(
            1, {"occupation": "源天师", "occupation_level": 51}, now=100, seed="duel-test")

        self.assertEqual(session["expires_at"], 400)
        self.assertEqual(len(session["player_stones"]), 5)
        self.assertEqual(len(session["npc_stones"]), 5)
        self.assertEqual(len({stone["name"] for stone in session["player_stones"]}), 5)
        self.assertEqual(len({stone["name"] for stone in session["npc_stones"]}), 5)
        self.assertTrue(all(stone["insight"].startswith("源术判断：")
                            for stone in session["player_stones"]))
        self.assertTrue(all(not stone["insight"] for stone in
                            source_duel.create_session(1, {}, now=100, seed="ordinary")
                            ["player_stones"]))

    def test_outcome_threshold_boundary_advances_to_next_tier(self):
        class FixedRandom:
            def __init__(self, values):
                self.values = iter(values)

            def random(self):
                return next(self.values)

        form = {"name": "边界石", "bias": 0, "appearance": "边界", "weight": 1}
        below = source_duel._draw_outcome(form, 100, None, FixedRandom((0.599999, 0, 0)))
        at_boundary = source_duel._draw_outcome(form, 100, None, FixedRandom((0.6, 0, 0)))

        self.assertEqual(below["outcome_tier"], 1)
        self.assertEqual(at_boundary["outcome_tier"], 2)
        self.assertEqual((below["source_value"], at_boundary["source_value"]), (50, 100))

    def test_resonance_bonus_only_applies_to_a_complete_pair(self):
        stones = [
            {"id": 1, "name": "烈阳石", "source_value": 100_000},
            {"id": 2, "name": "月亮石", "source_value": 100_000},
            {"id": 3, "name": "青皮石", "source_value": 100_000},
        ]

        result = source_duel.evaluate_cut(stones)

        self.assertEqual(result["base_source"], 300_000)
        self.assertEqual(result["source"], 375_000)
        self.assertEqual(result["resonance"]["name"], "日月同辉")

    def test_win_loss_draw_and_stake_multiplier_settlement(self):
        npc = source_duel.NPCS[0]
        self.assertEqual(source_duel.calculate_settlement(npc, "win", 300_000, 200_000),
                         {"fee": 200_000, "wager": 200_000,
                          "credit": 900_000, "net": 500_000})
        self.assertEqual(source_duel.calculate_settlement(npc, "lose", 300_000, 200_000),
                         {"fee": 200_000, "wager": 200_000,
                          "credit": 0, "net": -400_000})
        self.assertEqual(source_duel.calculate_settlement(npc, "draw", 300_000, 300_000),
                         {"fee": 200_000, "wager": 200_000,
                          "credit": 500_000, "net": 100_000})
        self.assertEqual(source_duel.calculate_settlement(npc, "win", 300_000, 200_000, "豪赌"),
                         {"fee": 200_000, "wager": 600_000,
                          "credit": 1_700_000, "net": 900_000})

    def test_invalid_duplicate_or_expired_choices_are_rejected(self):
        session = source_duel.create_session(1, {}, now=100, seed="duel-test")

        with self.assertRaisesRegex(ValueError, "三块不同"):
            source_duel.resolve_session(session, [1, 1, 2], "平注")
        with self.assertRaisesRegex(ValueError, "时间已过"):
            source_duel.resolve_session(session, [1, 2, 3], "平注", now=401)
        with self.assertRaisesRegex(ValueError, "押注方式"):
            source_duel.calculate_settlement(source_duel.NPCS[0], "win", 1, 1, "all-in")

    def test_resolution_is_repeatable_for_a_persisted_session(self):
        session = source_duel.create_session(2, {}, now=100, seed="stable-seed")
        first = source_duel.resolve_session(session, [1, 3, 5], "加注", now=101)
        second = source_duel.resolve_session(session, [1, 3, 5], "加注", now=101)

        self.assertEqual(first, second)

    def test_duel_state_initializes_without_replacing_market_currency_or_ledger(self):
        y = {"amount": 900_000, "market": {"pending": {"stone": 1}},
             "ledger": [{"name": "existing"}]}

        duel = source_duel.duel_state(y)

        self.assertIs(y["market"]["pending"]["stone"], 1)
        self.assertEqual(y["amount"], 900_000)
        self.assertEqual(y["ledger"], [{"name": "existing"}])
        self.assertEqual((duel["wins"], duel["losses"], duel["draws"], duel["session"]),
                         (0, 0, 0, None))

    def test_duel_state_imports_original_cumulative_player_statistics(self):
        y = {"amount": 1}
        legacy = {"源石坊对决胜场": 4, "源石坊对决负场": 2, "源石坊对决平局": 3,
                  "源石坊对决净收益": -1200, "源石坊对决累计切源": 50_000,
                  "源石坊对决最高切源": 20_000}

        duel = source_duel.duel_state(y, legacy)

        self.assertEqual((duel["wins"], duel["losses"], duel["draws"]), (4, 2, 3))
        self.assertEqual(duel["net"], -1200)
        self.assertEqual((duel["total_cut_source"], duel["peak_cut_source"]),
                         (50_000, 20_000))

    def test_expired_session_is_cleared_without_refunding_source(self):
        y = {"amount": 500_000, "duel": {"session": {"expires_at": 300},
                                         "net": -200_000}}

        session, expired = source_duel.active_session(y, 301)

        self.assertIsNone(session)
        self.assertTrue(expired)
        self.assertIsNone(y["duel"]["session"])
        self.assertEqual(y["amount"], 500_000)
        self.assertEqual(yuanshi.system_of(SimpleNamespace(ext={"yuanshi": y}))["amount"],
                         500_000)

    def test_duel_ledger_rows_preserve_format_without_counting_as_stone_cuts(self):
        y = {"amount": 100, "ledger": [], "cuts": 4, "empty_streak": 2}

        yuanshi.record_duel_ledger(
            y, 123, price=200_000, source=450_000, name="吴子明·win",
            extra={"event": "duel_settlement"})

        self.assertEqual(y["ledger"], [{
            "t": 123.0, "garden": "源术对决", "price": 200_000, "cur": "源石",
            "source": 450_000, "item": "", "name": "吴子明·win", "empty": False,
            "cut": False, "extra": {"event": "duel_settlement"},
            "refund": 0, "refund_cur": "",
        }])
        self.assertEqual((y["cuts"], y["empty_streak"]), (4, 2))


if __name__ == "__main__":
    unittest.main()
