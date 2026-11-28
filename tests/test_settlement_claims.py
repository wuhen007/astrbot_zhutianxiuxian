import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.player import PlayerDoc
from core import settlement, addict


class SettlementClaims(unittest.TestCase):
    def test_claim_is_idempotent_and_namespaced(self):
        doc = PlayerDoc(uid='A')
        self.assertTrue(settlement.claim(doc, 'secret', 'run-1', 10))
        self.assertFalse(settlement.claim(doc, 'secret', 'run-1', 11))
        self.assertTrue(settlement.claim(doc, 'addict', 'run-1', 12))

    def test_legacy_addiction_id_is_stable_across_claim_attempts(self):
        rec = {"start": 10, "end": 190, "place": "青冥山", "count": 1}
        self.assertEqual(addict.settlement_id("A", rec), addict.settlement_id("A", dict(rec)))
    def test_claim_history_is_bounded_without_dropping_latest_receipt(self):
        doc = PlayerDoc(uid='A')
        for index in range(settlement.MAX_RECEIPTS + 2):
            self.assertTrue(settlement.claim(doc, 'secret', str(index), index))
        self.assertTrue(settlement.claimed(doc, 'secret', str(settlement.MAX_RECEIPTS + 1)))


if __name__ == '__main__':
    unittest.main()
