import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import faction
from core.player import PlayerDoc


class JianyunhaiVisitTests(unittest.TestCase):
    def test_repeating_pending_visit_reopens_choice_without_spending_token(self):
        doc = PlayerDoc(uid="jyh-pending", realm_index=45,
                        ext={"jyh_choice_pending": True})

        ok, message, cost = faction.jyh_visit(doc, {faction.JYH_ITEM: 1}, 45, 0)

        self.assertTrue(ok)
        self.assertEqual(cost, 0)
        self.assertIn("剑云海机缘", message)
        self.assertTrue(faction.jyh_choice_pending(doc))


if __name__ == "__main__":
    unittest.main()
