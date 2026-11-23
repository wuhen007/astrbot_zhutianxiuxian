import unittest

from core import wudao
from core.player import PlayerDoc


class WudaoContractTests(unittest.TestCase):
    def test_insufficient_lifespan_keeps_three_value_result_contract(self):
        doc = PlayerDoc(uid="wudao-contract", realm_index=10, exp=10**9, stones=10**9,
                        ext={"xueqi": 10**9, "shouyuan": 1, "potential": 10**6})
        result = wudao.attempt(doc, {}, now=1_800_000_000)

        self.assertEqual(len(result), 3)
        self.assertFalse(result[0])
        self.assertIn("寿元", result[1])
        self.assertEqual(result[2], {})


if __name__ == "__main__":
    unittest.main()
