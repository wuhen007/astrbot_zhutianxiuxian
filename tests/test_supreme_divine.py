import unittest

from core import rift, xiangu, zhengdao


class FakeDoc:
    def __init__(self, wounds=2.0, flaws=1, failed_at=1000.0):
        self.uid = "test"
        self.realm_index = 20
        self.physique_index = 0
        self.exp = 100_000_000
        self.ext = {
            "xueqi": 100_000_000,
            "daoshang": {
                "wounds": wounds,
                "last_decay_at": 1000.0,
                "dao_flaws": flaws,
                "break_king_failed_at": failed_at,
                "last_prove_at": failed_at,
            }
        }


class AlwaysFailRng:
    def random(self):
        return 1.0


class SupremeDivineTests(unittest.TestCase):
    def test_item_is_available_from_both_original_sources(self):
        self.assertEqual(rift.EXCHANGES["无上神物"], {"cost": 80, "qty": 1})
        core_items = xiangu._LOCATION_ITEMS["核心区域"]
        self.assertTrue(any(row["name"] == "无上神物" for row in core_items))

    def test_failed_emperor_proof_creates_repairable_flaw_and_cooldown(self):
        doc = FakeDoc(wounds=0.0, flaws=0, failed_at=0.0)
        ok, text, _, _ = zhengdao.prove(doc, {}, now=1_000_000.0, rng=AlwaysFailRng())
        state = zhengdao.state_of(doc, now=1_000_000.0)
        self.assertTrue(ok)
        self.assertIn("道果瑕疵 +1", text)
        self.assertEqual(state["dao_flaws"], 1)
        self.assertEqual(state["break_king_failed_at"], 1_000_000.0)
        self.assertEqual(state["last_prove_at"], 1_000_000.0)
        self.assertFalse(zhengdao.prove(doc, {}, now=1_000_001.0)[0])

    def test_repairs_one_flaw_and_releases_retry_cooldown(self):
        doc = FakeDoc()
        ok, text = zhengdao.use_supreme_divine_item(doc, now=1100.0)
        state = zhengdao.state_of(doc, now=1100.0)
        self.assertTrue(ok)
        self.assertEqual(state["dao_flaws"], 0)
        self.assertEqual(state["wounds"], 1.0)
        self.assertEqual(state["break_king_failed_at"], 0.0)
        self.assertEqual(zhengdao.PROVE_CD - (1100.0 - state["last_prove_at"]), 0)
        self.assertIn("冷却已解除", text)

    def test_does_not_consume_when_there_is_nothing_to_repair(self):
        doc = FakeDoc(wounds=0.0, flaws=0, failed_at=0.0)
        ok, text = zhengdao.use_supreme_divine_item(doc, now=2000.0)
        self.assertFalse(ok)
        self.assertIn("无需使用", text)


if __name__ == "__main__":
    unittest.main()
