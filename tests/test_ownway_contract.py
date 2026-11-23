import unittest

from core import ownway
from core.player import PlayerDoc


class OwnwayContractTests(unittest.TestCase):
    def test_emperor_sutra_gate_failure_keeps_three_value_contract(self):
        doc = PlayerDoc(uid="new-player")

        result = ownway.emperor_sutra(doc, "岁月剑经", now=1_800_000_000)

        self.assertEqual(len(result), 3)
        self.assertFalse(result[0])
        self.assertIn("权柄", result[1])
        self.assertEqual(result[2], {})


if __name__ == "__main__":
    unittest.main()
