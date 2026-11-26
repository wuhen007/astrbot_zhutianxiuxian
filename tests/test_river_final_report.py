import unittest
from types import SimpleNamespace

from core import river
from core.combat.engine import Fighter


class FakeDoc:
    uid = "river-test"
    name = "道友"
    realm_index = 45
    physique_index = 0
    exp = 1000
    stones = 0

    def __init__(self):
        self.ext = {}


class FixedRng(__import__("random").Random):
    def random(self):
        return 0.1

    def uniform(self, low, high):
        return low

    def choice(self, values):
        return values[0]

    def randint(self, low, high):
        return low


class RiverFinalReportTests(unittest.TestCase):
    def test連战只返回终局汇总(self):
        doc = FakeDoc()

        def build(name, mult):
            if name == "__me__":
                return Fighter(name="道友", atk=100_000, defense=1_000,
                               hp=10_000, hp_max=10_000, bao=0.0)
            return Fighter(name=name, atk=1, defense=1,
                           hp=max(1, int(100 * mult)), hp_max=max(1, int(100 * mult)), bao=0.0)

        text, gains = river.roam(doc, None, build, FixedRng(), now=1000)
        self.assertIn("时间长河·终局战报", text)
        self.assertIn("同时交战", text)
        self.assertIn("未能击败苍、鸿、羽三帝", text)
        self.assertNotIn("第 1 战", text)
        self.assertEqual(gains["crystal"], river.CRYSTAL_LOSE)


if __name__ == "__main__":
    unittest.main()
