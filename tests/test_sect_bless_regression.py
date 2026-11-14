import sys
from pathlib import Path
import random
import unittest
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.player import PlayerDoc
from core import sect_extra as se

class BeastBlessRegression(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 23, 59, tzinfo=timezone(timedelta(hours=8))).timestamp()
        self.sect = {'beast': '青龙'}
    def test_legacy_shared_timestamp_does_not_block_members(self):
        self.sect['beast_bless_ts'] = self.now
        self.assertTrue(self.bless(PlayerDoc(uid='A'))[0])
    def bless(self, doc, when=None, fund=100000):
        return se.beast_bless(doc, self.sect, fund, self.now if when is None else when, random.Random(1))
    def test_members_have_independent_daily_attempts(self):
        a, b = PlayerDoc(uid='A'), PlayerDoc(uid='B')
        self.assertTrue(self.bless(a)[0], 'legacy shared timestamp must not block every member')
        self.assertTrue(self.bless(b)[0], 'member B must not inherit member A cooldown')
        saved = PlayerDoc(**a.model_dump())
        self.assertFalse(self.bless(saved)[0], 'personal daily mark must survive persistence')
    def test_beijing_midnight_resets_instead_of_24_hours(self):
        a = PlayerDoc(uid='A')
        self.assertTrue(self.bless(a)[0])
        self.assertFalse(self.bless(a, self.now + 59)[0])
        self.assertTrue(self.bless(a, self.now + 60)[0], 'next Beijing date must reset after one minute')
    def test_failed_attempt_does_not_consume_daily_eligibility(self):
        a = PlayerDoc(uid='A')
        self.assertFalse(self.bless(a, fund=0)[0])
        self.assertTrue(self.bless(a)[0])

if __name__ == '__main__':
    unittest.main()
