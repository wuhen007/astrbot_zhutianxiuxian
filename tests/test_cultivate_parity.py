import random
import unittest

from core import cultivate
from core.player import PlayerDoc


class SequenceRandom(random.Random):
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class BreakthroughParityTests(unittest.TestCase):
    def setUp(self):
        self.levels = [
            {"level": "凡人", "exp": 100},
            {"level": "筑基", "exp": 200},
            {"level": "金丹", "exp": 300},
        ]

    def test_potential_cost_tiers_and_mingge_modifiers(self):
        self.assertEqual([cultivate.breakthrough_potential_cost(i) for i in (1, 26, 27, 41, 42)],
                         [2, 2, 4, 4, 8])
        doc = PlayerDoc(uid="mg", ext={"mingge": {"effects": {"仙道潜力消耗减少": 0.1}}})
        self.assertEqual(cultivate.player_breakthrough_potential_cost(doc, 1), 1)
        doc.ext["mingge"] = {"effects": {"仙道潜力消耗增加": 0.15}}
        self.assertEqual(cultivate.player_breakthrough_potential_cost(doc, 1), 3)

    def test_qi_success_spends_exp_and_potential(self):
        doc = PlayerDoc(uid="qi", exp=100, ext={"potential": 2})
        ok, message, result = cultivate.breakthrough(
            doc, self.levels, 1.0, 0.3, SequenceRandom(0.0))
        self.assertTrue(ok, message)
        self.assertEqual((result.realm_index, result.exp, result.ext["potential"]), (1, 0, 0))
        self.assertEqual((doc.realm_index, doc.exp, doc.ext["potential"]), (0, 100, 2))

    def test_potential_shortage_does_not_mutate_player(self):
        doc = PlayerDoc(uid="low", exp=1000, ext={"potential": 1})
        ok, message, result = cultivate.breakthrough(
            doc, self.levels, 1.0, 0.3, SequenceRandom())
        self.assertFalse(ok)
        self.assertIn("潜力不足", message)
        self.assertIs(result, doc)
        self.assertEqual((doc.realm_index, doc.exp, doc.ext["potential"]), (0, 1000, 1))

    def test_qi_failure_spends_base_and_extra_loss_but_not_potential(self):
        doc = PlayerDoc(uid="fail", exp=1000, ext={"potential": 2})
        ok, message, result = cultivate.breakthrough(
            doc, self.levels, 1.0, 0.3, SequenceRandom(0.999, 0.95))
        self.assertTrue(ok)
        self.assertIn("额外损失 40", message)
        self.assertEqual((result.realm_index, result.exp, result.ext["potential"]), (0, 860, 2))

    def test_body_uses_talent_and_spends_potential_on_success(self):
        table = [{"level": "莽夫", "exp": 1000}, {"level": "初境", "exp": 2000}]
        doc = PlayerDoc(uid="body", ext={"potential": 2,
            "linggen": {"name": "大成·荒古圣体"}})
        ok, message, cost = cultivate.body_breakthrough(
            doc, table, 1000, SequenceRandom(0.0), cost_scale=1.0)
        self.assertTrue(ok, message)
        self.assertEqual((doc.physique_index, doc.ext["potential"], cost), (1, 0, 750))

    def test_one_key_body_keeps_five_percent_loss_tier(self):
        table = [{"level": "莽夫", "exp": 100}, {"level": "初境", "exp": 200}]
        doc = PlayerDoc(uid="body-fail", ext={"potential": 2})
        ok, _message, loss = cultivate.body_breakthrough(
            doc, table, 100, SequenceRandom(0.999, 0.7), cost_scale=1.0, one_key=True)
        self.assertFalse(ok)
        self.assertEqual(loss, 5)


if __name__ == "__main__":
    unittest.main()
