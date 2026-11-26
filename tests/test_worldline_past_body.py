import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.player import PlayerDoc
from core import worldline


class RollSequence:
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class PastBodyWorldline(unittest.TestCase):
    def test_unlocked_equipped_treasure_can_be_destroyed_and_unbound(self):
        doc = PlayerDoc(uid='A', ext={
            'equipment': {'至宝': '先天宝物'},
            'xtzb': {'current': '先天宝物'},
        })
        result = worldline.collapse_past_artifacts(
            doc, RollSequence(0.1, 0.0), lambda name: {'name': name, 'class': '装备'})
        self.assertTrue(result['destroyed'])
        self.assertNotIn('至宝', doc.ext['equipment'])
        self.assertEqual(doc.ext['xtzb']['current'], '')

    def test_locked_or_body_treasures_are_never_selected(self):
        doc = PlayerDoc(uid='A', ext={
            'equipment': {'帝兵': '锁定帝兵', '至宝': '大道至宝'},
        })
        result = worldline.collapse_past_artifacts(
            doc, RollSequence(0.0), lambda name: {
                'name': name, 'class': '装备',
                '锁定': name == '锁定帝兵', '大道至宝本体': name == '大道至宝',
            })
        self.assertFalse(result['destroyed'])
        self.assertEqual(result['candidates'], 0)

    def test_past_line_destruction_records_the_present_wound(self):
        doc = PlayerDoc(uid='A')
        result = worldline.destroy_past(doc, '时间长河过去身', 1_800_000_000)
        self.assertFalse(result['protected'])
        self.assertEqual(doc.ext['ancient_wound'], 1)
        self.assertIn(result['line_id'], doc.ext['worldline']['destroyed_lines'])


if __name__ == '__main__':
    unittest.main()
