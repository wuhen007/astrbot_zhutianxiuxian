"""Real harvest and pet settlement regressions; run directly with bundled Python."""
import copy
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import xiaoshijie as x

NOW = 1800000000


def world(count=1, level=1, debt=0, food=0):
    return dict(name='test', level=1, avatar=True,
                last_harvest=NOW - 24 * 3600 / x.WORLD_LEVELS[1]['ratio'],
                fields=[], env=[], temple={}, workshops={'矿脉': level},
                pets=[dict(name=f'pet{i}', type='战斗', quality='仙胎', traits=[],
                           energy=100, max_energy=100, workshop='矿脉', guard=False, cycle=0)
                      for i in range(count)],
                supplies={'欠餐': debt, '仙宠口粮': food})


class WorldEconomyRegression(unittest.TestCase):
    def test_current_harvest_consumed_before_old_inventory(self):
        w = world()
        inv = {'仙馐果': 4}
        original = copy.deepcopy(w)
        ok, _, nw, out, extras = x.harvest_full(w, NOW, inv, random.Random(0))
        self.assertTrue(ok)
        self.assertEqual(nw['supplies']['欠餐'], 0)
        self.assertEqual(out['仙馐果'], 1199)
        self.assertEqual(extras.get('meals_used', {}), {})
        self.assertEqual(inv, {'仙馐果': 4})
        self.assertEqual(w, original)

    def test_old_inventory_elixir_is_returned_as_debit(self):
        w, _, _, used = x.settle_pets(world(), 24, {'混沌元液': 1}, random.Random(0))
        self.assertEqual(w['supplies']['欠餐'], 0)
        self.assertEqual(used, {'混沌元液': 1})

    def test_multiple_pets_consume_only_available_old_food(self):
        w, _, _, used = x.settle_pets(world(count=2), 24, {'混沌元液': 1}, random.Random(0))
        self.assertEqual(used, {'混沌元液': 1})
        self.assertEqual(w['supplies']['欠餐'], 1)

    def test_multiple_pets_current_harvest_is_debited_once_each(self):
        ok, _, nw, out, extras = x.harvest_full(world(count=2), NOW, {}, random.Random(0))
        self.assertTrue(ok)
        self.assertEqual(nw['supplies']['欠餐'], 0)
        self.assertEqual(out['仙馐果'], 1198)
        self.assertEqual(extras.get('meals_used', {}), {})

    def test_debt_recovers_from_current_harvest_after_supplies(self):
        ok, _, nw, out, extras = x.harvest_full(world(debt=2, food=1), NOW, {}, random.Random(0))
        self.assertTrue(ok)
        self.assertEqual(nw['supplies']['欠餐'], 0)
        self.assertEqual(nw['supplies']['仙宠口粮'], 0)
        self.assertEqual(out['仙馐果'], 1198)
        self.assertGreater(out['__stones__'], 0)
        self.assertEqual(extras.get('meals_used', {}), {})

    def test_missing_food_and_old_inventory_debit_remain_consistent(self):
        w, extra, _, used = x.settle_pets(world(debt=2, food=1), 24, {'仙馐果': 1}, random.Random(0))
        self.assertEqual(w['supplies']['欠餐'], 1)
        self.assertEqual(used, {'仙馐果': 1})
        recovered, extra, _, used = x.settle_pets(world(debt=2, food=3), 24, {}, random.Random(0))
        self.assertEqual(recovered['supplies']['欠餐'], 0)
        self.assertEqual(extra['__stones__'], 700000)

    def test_shared_current_and_old_food_budget_never_duplicates(self):
        harvested = {'仙馐果': 1, '混沌元液': 1}
        old = {'仙馐果': 1}
        nw, _, logs, used = x.settle_pets(
            world(count=4), 24, old, random.Random(0), harvested=harvested)
        self.assertEqual(harvested, {'仙馐果': 0, '混沌元液': 0})
        self.assertEqual(used, {'仙馐果': 1})
        self.assertEqual(old, {'仙馐果': 1})
        self.assertEqual(nw['supplies']['欠餐'], 1)
        self.assertIn('仙馐果×2', logs[0])
        self.assertIn('混沌元液×1', logs[0])

    def test_reachable_workshop_level_pet_multipliers(self):
        yields = []
        for level in (1, 2, 3, 4, 5):
            _, extra, _, _ = x.settle_pets(world(level=level), 1, {}, random.Random(0))
            yields.append(extra['__stones__'])
        self.assertEqual(yields, [50000, 60000, 70000, 85000, 100000])

    def test_existing_upgrade_design_is_preserved(self):
        w = world()
        w['supplies'].update({'界源矿石': 72, '工坊构件': 72})
        ok, _, nw, cost = x.upgrade_workshop(w, '矿脉', 16000000, 2)
        self.assertTrue(ok)
        self.assertEqual(cost, 16000000)
        self.assertEqual(nw['supplies']['界源矿石'], 72)
        self.assertEqual(nw['supplies']['工坊构件'], 72)
        self.assertFalse(x.upgrade_workshop(world(level=5), '矿脉', 10**12, 100)[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
