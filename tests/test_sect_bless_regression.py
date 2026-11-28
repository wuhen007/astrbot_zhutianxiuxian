import sys
from pathlib import Path
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.player import PlayerDoc
from core import sect_extra as se


class RollSequence:
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class BeastBlessRegression(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 23, 59, tzinfo=timezone(timedelta(hours=8))).timestamp()
        self.sect = {'beast': '青龙', 'build': 50, 'place': '昆仑山'}
        self.pools = {
            'gongfa': [{'name': '普通青龙功法', 'class': '功法', '稀有度': 3}],
            'qinglong': [{'name': '限定青龙功法', 'class': '功法', '稀有度': 4}],
        }

    def bless(self, doc, when=None, fund=0, rng=None):
        return se.beast_bless(
            doc, self.sect, fund, self.now if when is None else when,
            rng or RollSequence(0.1), self.pools)

    def test_summon_insufficient_fund_returns_full_result(self):
        doc = PlayerDoc(uid='A', name='宗主')
        ok, message, remaining = se.summon_beast(
            doc, {'build': 50, 'place': '昆仑山'}, se.BEAST_COST - 1,
            se.BEAST_LEVEL, self.now, RollSequence(0.5))
        self.assertFalse(ok)
        self.assertIn('基金', message)
        self.assertEqual(remaining, se.BEAST_COST - 1)

    def test_summon_requires_realm_build_place_and_fund(self):
        doc = PlayerDoc(uid='A', name='宗主')
        for state, fund, level, expected in (
            ({'build': 50, 'place': '昆仑山'}, se.BEAST_COST, se.BEAST_LEVEL - 1, '等级'),
            ({'build': 49, 'place': '昆仑山'}, se.BEAST_COST, se.BEAST_LEVEL, '建设'),
            ({'build': 50, 'place': ''}, se.BEAST_COST, se.BEAST_LEVEL, '驻地'),
            ({'build': 50, 'place': '昆仑山'}, se.BEAST_COST - 1, se.BEAST_LEVEL, '基金'),
        ):
            ok, message, remaining = se.summon_beast(
                doc, state, fund, level, self.now, RollSequence(0.5))
            self.assertFalse(ok)
            self.assertIn(expected, message)
            self.assertEqual(remaining, fund)

    def test_shared_original_timestamp_does_not_block_members(self):
        self.sect['beast_bless_ts'] = self.now
        self.assertTrue(self.bless(PlayerDoc(uid='A'))[0])

    def test_members_have_independent_daily_attempts(self):
        a, b = PlayerDoc(uid='A'), PlayerDoc(uid='B')
        self.assertTrue(self.bless(a)[0])
        self.assertTrue(self.bless(b)[0])
        saved = PlayerDoc(**a.model_dump())
        self.assertFalse(self.bless(saved)[0])

    def test_beijing_midnight_resets_instead_of_waiting_24_hours(self):
        doc = PlayerDoc(uid='A')
        self.assertTrue(self.bless(doc)[0])
        self.assertFalse(self.bless(doc, self.now + 59)[0])
        self.assertTrue(self.bless(doc, self.now + 60)[0])

    def test_no_drop_attempt_consumes_daily_use_and_one_favor_charge(self):
        doc = PlayerDoc(uid='A', ext={'buffs': {'shenci': {'times': 2, 'bonus': 0}}})
        self.assertTrue(self.bless(doc, rng=RollSequence(0.69))[0])
        self.assertEqual(doc.ext['buffs']['shenci']['times'], 1)
        self.assertFalse(self.bless(doc)[0])

    def test_favor_bonus_selects_preferred_pool_without_fund_cost(self):
        doc = PlayerDoc(uid='A', ext={'buffs': {'shenci': {'times': 2, 'bonus': 0.02}}})
        ok, _, reward, remaining = self.bless(
            doc, fund=0, rng=RollSequence(0.69, 0.95, 0.0))
        self.assertTrue(ok)
        self.assertEqual(reward, {'限定青龙功法': 1})
        self.assertEqual(remaining, 0)
        self.assertEqual(doc.ext['buffs']['shenci']['times'], 1)


if __name__ == '__main__':
    unittest.main()
