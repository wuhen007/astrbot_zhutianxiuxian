import random
import unittest

from core import cultivate, plane
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

    def test_original_plane_level_growth_caps(self):
        self.assertEqual(plane.world_level_caps(5),
                         {"mijing": 16, "qi": 59, "body": 58, "xiangu": 14})
        self.assertEqual(plane.world_level_caps(10),
                         {"mijing": 21, "qi": 64, "body": 63, "xiangu": 19})
        self.assertEqual(plane.world_level_caps(0), plane.world_level_caps(10))

    def test_qi_breakthrough_obeys_world_level_cap_without_spending(self):
        table = [{"level": f"境界{i}", "level_id": i, "exp": 0} for i in range(1, 62)]
        doc = PlayerDoc(uid="qi-world-cap", realm_index=58, exp=10**9,
                        ext={"potential": 100})
        ok, message, result = cultivate.breakthrough(
            doc, table, 1.0, 0.3, SequenceRandom(), plane_level=5)
        self.assertFalse(ok)
        self.assertIn("当前位面等级 5", message)
        self.assertIs(result, doc)
        self.assertEqual((doc.realm_index, doc.exp), (58, 10**9))

    def test_body_one_key_stops_at_world_level_cap(self):
        table = [{"level": f"炼体{i}", "level_id": i, "exp": 0} for i in range(1, 65)]
        doc = PlayerDoc(uid="body-world-cap", physique_index=57,
                        ext={"xueqi": 10**9, "potential": 100})
        message, result, used = cultivate.one_key_body(
            doc, table, SequenceRandom(), plane_level=5)
        self.assertIn("当前位面等级 5", message)
        self.assertEqual(result.physique_index, 57)
        self.assertEqual(used, 0)

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

    def test_chaos_bell_shortens_planned_cultivation_without_double_multiplying_yield(self):
        doc = PlayerDoc(uid="clock-cultivate", ext={
            "xtzb": {"current": "混沌钟", "owned": ["混沌钟"]}})
        ok, message, started = cultivate.start_cultivate(doc, 30, 7200)
        self.assertTrue(ok)
        self.assertIn("预计实时时长 21 分钟", message)

        ok, _, settled = cultivate.end_cultivate(
            started, started.state_start + 21 * 60, 20, 7200)

        self.assertTrue(ok)
        self.assertEqual(settled.exp, 600)
        self.assertNotIn("cultivate_minutes", settled.ext)

    def test_east_emperor_bell_shortens_work_and_credits_elapsed_work_minutes(self):
        doc = PlayerDoc(uid="clock-work", ext={
            "xtzb": {"current": "东皇钟", "owned": ["东皇钟"]}})
        ok, message, started = cultivate.start_work(doc, 30)
        self.assertTrue(ok)
        self.assertIn("预计实时时长 24 分钟", message)

        ok, _, settled = cultivate.end_work(
            started, started.state_start + 24 * 60, 10)

        self.assertTrue(ok)
        self.assertEqual(settled.stones, 300)


if __name__ == "__main__":
    unittest.main()
