"""Regression checks at public progression and mining functions; run with unittest."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import reinc_story as rs, occupation as oc
from core.player import PlayerDoc

class Fixed:
    def __init__(self, bucket=0): self.bucket = bucket
    def random(self): return .999999
    def randrange(self, start, stop):
        return min(self.bucket, stop - 1)

def player(state=None):
    return PlayerDoc(uid='progress-test', ext={'reinc_story': state or {}})

def complete(doc):
    assert rs.start(doc, '老兵')[0]
    for pick in (3, 3, 2, 3, 3):
        assert rs.choose(doc, pick, now=1800000000, rng=Fixed())[0]
    assert rs.settle(doc)[0]

class ProgressRegression(unittest.TestCase):
    def test_wallet_accumulates_without_changing_run_grade(self):
        d = player()
        complete(d)
        self.assertEqual(rs.state_of(d)['points'], 2150)
        complete(d)
        self.assertEqual(rs.state_of(d)['points'], 4300)
        self.assertEqual(rs.state_of(d)['run_points'], 2150)
        self.assertEqual(rs.state_of(d)['grade'], 'B·同行者')
        self.assertFalse(rs.settle(d)[0])
        self.assertEqual(rs.state_of(d)['points'], 4300)
        self.assertTrue(rs.exchange(d, '神经加速器·B')[0])
        self.assertEqual(rs.state_of(d)['points'], 1700)
        self.assertTrue(rs.enhance(d, '体术')[0])
        self.assertEqual(rs.state_of(d)['points'], 1100)
        self.assertEqual(rs.state_of(d)['run_points'], 2150)

    def test_fresh_player_can_reach_top_exchange_by_playing(self):
        d = player()
        for _ in range(15):
            complete(d)
        self.assertEqual(rs.state_of(d)['points'], 32250)
        self.assertTrue(rs.exchange(d, '轮回者权限·SSS')[0])
        self.assertEqual(rs.state_of(d)['points'], 2250)

    def test_malformed_optional_state_keeps_default_fallback(self):
        for raw in (123, True, 'run_points', []):
            with self.subTest(raw=raw):
                d = PlayerDoc(uid='malformed-test', ext={'reinc_story': raw})
                self.assertEqual(rs.state_of(d)['points'], 0)
                self.assertTrue(rs.start(d, '学生')[0])

    def test_old_active_migrates_once_and_old_settled_wallet_survives(self):
        active = player({'active': True, 'points': 2150, 'scene': 5})
        first = rs.state_of(active)
        self.assertEqual(first, rs.state_of(active))
        self.assertEqual(active.ext['reinc_story']['points'], 2150)
        rs.save(active, first)
        self.assertEqual(first, rs.state_of(active))
        self.assertTrue(rs.settle(active)[0])
        self.assertEqual(rs.state_of(active)['points'], 2150)
        self.assertFalse(rs.settle(active)[0])
        old = player({'active': False, 'points': 2600, 'best': 2150})
        self.assertTrue(rs.exchange(old, '神经加速器·B')[0])
        self.assertEqual(rs.state_of(old)['points'], 0)
        self.assertTrue(rs.start(old, '学生')[0])
        self.assertEqual(rs.state_of(old)['points'], 0)

    def test_spending_during_run_does_not_reduce_score_or_double_award(self):
        d = player({'active': False, 'points': 3000})
        self.assertTrue(rs.start(d, '学生')[0])
        self.assertEqual(rs.state_of(d)['points'], 3000)
        self.assertTrue(rs.choose(d, 3, now=0, rng=Fixed())[0])
        self.assertTrue(rs.enhance(d, '心智')[0])
        self.assertTrue(rs.settle(d)[0])
        self.assertEqual(rs.state_of(d)['points'], 2560)
        self.assertEqual(rs.state_of(d)['run_points'], 160)
        self.assertIn('本局', rs.panel(d))
        self.assertIn('可用', rs.panel(d))

    def test_keep_permission_carries_score_not_wallet_and_rank_up_is_not_currency(self):
        d = player({'points': 30000, 'active': False})
        self.assertTrue(rs.exchange(d, '轮回者权限·SSS')[0])
        complete(d)
        self.assertEqual(rs.state_of(d)['points'], 2150)
        self.assertTrue(rs.start(d, '医生')[0])
        self.assertEqual(rs.state_of(d)['points'], 2150)
        self.assertEqual(rs.state_of(d)['run_points'], 430)
        self.assertTrue(rs.settle(d)[0])
        self.assertEqual(rs.state_of(d)['points'], 2150)

    def test_legacy_kept_score_and_rank_upgrade_do_not_mint_currency(self):
        old = player({'active': False, 'points': 1200, 'keep_ratio': .2,
                      'history': [{'points': 2150}], 'grade': 'B·同行者'})
        self.assertTrue(rs.start(old, '学生')[0])
        self.assertEqual(rs.state_of(old)['run_points'], 430)
        self.assertTrue(rs.settle(old)[0])
        self.assertEqual(rs.state_of(old)['points'], 1200)
        ranked = player({'active': True, 'points': 100, 'run_points': 2150,
                         'run_start_points': 0, 'rank_up': True})
        self.assertTrue(rs.settle(ranked)[0])
        self.assertEqual(rs.state_of(ranked)['points'], 2250)
        self.assertEqual(rs.state_of(ranked)['grade'], 'A·幸存者')
        self.assertEqual(rs.state_of(ranked)['run_points'], 2150)

    def test_wallet_prices_and_caps(self):
        for name, cost, _ in rs.EXCHANGES:
            for amount in (cost-1, cost, cost+1):
                with self.subTest(name=name, amount=amount):
                    d = player({'points': amount})
                    self.assertEqual(rs.exchange(d, name)[0], amount >= cost)
                    self.assertEqual(rs.state_of(d)['points'], amount-cost if amount >= cost else amount)
        d = player({'points': 599})
        self.assertFalse(rs.enhance(d, '体术')[0])
        d = player({'points': 600, 'attrs': {'体术': 10}})
        self.assertFalse(rs.enhance(d, '体术')[0])
        self.assertEqual(rs.state_of(d)['points'], 600)

    def test_all_ten_mining_buckets_at_both_sides_of_old_level_gate(self):
        table = json.loads((ROOT/'data/occupation/experience.json').read_text(encoding='utf-8'))
        for level in (0, 23, 24, 37):
            for bucket in range(10):
                with self.subTest(level=level, bucket=bucket):
                    out, exp = oc.mine_yield_full(720, level, table, Fixed(bucket))
                    self.assertEqual(exp, 7200)
                    a = ('金色石胚','棕色石胚','绿色石胚','红色石胚','蓝色石胚','金色石料','棕色石料','绿色石料','红色石料','蓝色石料')[bucket]
                    b = ('金色妖石','棕色妖石','绿色妖石','红色妖石','蓝色妖石','金色妖丹','棕色妖丹','绿色妖丹','红色妖丹','蓝色妖丹')[bucket]
                    if level == 37:
                        self.assertEqual(out[b], 1)
                    self.assertIn(a, out)
        self.assertEqual(oc.mine_yield_full(0, 37, table, Fixed(9)), ({}, 0))

if __name__ == '__main__': unittest.main()
