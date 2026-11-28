import unittest

from core.player import PlayerDoc
from core.quest import grant_completion_potential


class DailyQuestParityTests(unittest.TestCase):
    def test_completion_potential_uses_mingge_rate_and_flat_bonus(self):
        doc = PlayerDoc(uid="legacy", ext={
            "potential": 10,
            "legacy_source": {"mijinglevel_id": 4, "xiangulevel_id": 7},
            "mingge": {"effects": {"仙道潜力收益": 0.2, "仙道潜力额外": 20}},
        })
        amount, granted = grant_completion_potential(doc, "2026-11-20")
        self.assertTrue(granted)
        self.assertEqual(amount, 104)
        self.assertEqual(doc.ext["potential"], 114)

    def test_completion_potential_is_idempotent_per_day(self):
        doc = PlayerDoc(uid="repeat", realm_index=8, ext={"potential": 3})
        first = grant_completion_potential(doc, "2026-11-20")
        after_first = doc.ext["potential"]
        second = grant_completion_potential(doc, "2026-11-20")
        self.assertEqual(first, (40, True))
        self.assertEqual(second, (40, False))
        self.assertEqual(doc.ext["potential"], after_first)

    def test_next_day_has_a_separate_claim_key(self):
        doc = PlayerDoc(uid="two-days", ext={"legacy_source": {"mijinglevel_id": 1}})
        self.assertEqual(grant_completion_potential(doc, "2026-11-20"), (20, True))
        self.assertEqual(grant_completion_potential(doc, "2026-11-21"), (20, True))
        self.assertEqual(doc.ext["potential"], 40)


if __name__ == "__main__":
    unittest.main()
