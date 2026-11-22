from types import SimpleNamespace
import unittest

from core.admin import grant_occupation_level
from core.occupation import MAX_OCC_LEVEL


class GrantOccupationLevelTests(unittest.TestCase):
    def test_grant_is_clamped_to_occupation_table(self):
        doc = SimpleNamespace(uid="player-1", name="测试玩家", ext={"occupation": "炼丹师", "occupation_level": MAX_OCC_LEVEL - 2})
        ok, message = grant_occupation_level(doc, 10)
        self.assertTrue(ok)
        self.assertEqual(doc.ext["occupation_level"], MAX_OCC_LEVEL)
        self.assertIn("+2", message)
        self.assertIn("夹紧", message)

    def test_capped_occupation_cannot_be_granted_again(self):
        doc = SimpleNamespace(uid="player-1", name="测试玩家", ext={"occupation": "炼丹师", "occupation_level": MAX_OCC_LEVEL})
        ok, message = grant_occupation_level(doc, 1)
        self.assertFalse(ok)
        self.assertEqual(doc.ext["occupation_level"], MAX_OCC_LEVEL)
        self.assertIn("上限", message)


if __name__ == "__main__":
    unittest.main()
