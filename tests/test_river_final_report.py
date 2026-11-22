import unittest
from types import SimpleNamespace

from core import river


class FakeDoc:
    uid = "river-test"
    name = "道友"
    realm_index = 45
    physique_index = 0
    exp = 1000
    stones = 0

    def __init__(self):
        self.ext = {}


class FixedRng:
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

        def build(name, _mult):
            return SimpleNamespace(hp=100)

        def win(_me, _enemy, _rng):
            return SimpleNamespace(winner=0)

        text, gains = river.roam(doc, None, build, win, FixedRng(), now=1000)
        self.assertIn("时间长河·终局战报", text)
        self.assertIn("连战", text)
        self.assertIn("胜苍帝法身、胜鸿帝法身、胜羽帝法身", text)
        self.assertNotIn("第 1 战", text)
        self.assertEqual(gains["crystal"], river.CRYSTAL_TRIAD[0])


if __name__ == "__main__":
    unittest.main()
