import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.player import PlayerDoc
from core import extra_cultivation as extra


class ExtraCultivationState(unittest.TestCase):
    def test_imported_track_ids_are_preserved_independently(self):
        doc = PlayerDoc(uid='legacy', realm_index=40, physique_index=35, ext={
            'legacy_source': {
                'mijinglevel_id': 16,
                'xiangulevel_id': 15,
                'huafenlevel_id': 13,
            },
        })
        self.assertEqual(extra.levels_of(doc), {'mijing': 16, 'xiangu': 15, 'huafen': 13})

    def test_python_projection_advances_when_its_source_track_advances(self):
        doc = PlayerDoc(uid='native', realm_index=2)
        before = extra.level_of(doc, 'mijing')
        doc.realm_index += 2
        self.assertEqual(extra.level_of(doc, 'mijing'), before + 1)

    def test_reforge_reduces_only_extra_tracks_and_clears_route_extremes(self):
        doc = PlayerDoc(uid='legacy', realm_index=40, physique_index=35, ext={
            'legacy_source': {
                'mijinglevel_id': 16,
                'xiangulevel_id': 9,
                'huafenlevel_id': 13,
            },
            'flower': {'level': 13, 'extremes': ['本源觉醒'], 'accum': 100},
            'xiangu': {
                'shenhuo': {'已点燃': True, '极境达成': True, '极境名称': '神火极境'},
                'xianqi': 2,
                'xianqi_detail': ['第一道仙气'],
            },
        })
        result = extra.reforge(doc)
        self.assertEqual(result['next'], {'mijing': 15, 'xiangu': 8, 'huafen': 12})
        self.assertEqual(doc.realm_index, 40)
        self.assertEqual(doc.physique_index, 35)
        self.assertEqual(doc.ext['flower']['level'], 12)
        self.assertEqual(doc.ext['flower']['extremes'], [])
        self.assertEqual(doc.ext['xiangu']['xianqi'], 0)
        self.assertFalse(doc.ext['xiangu']['shenhuo']['极境达成'])

    def test_initial_tracks_cannot_be_reduced(self):
        doc = PlayerDoc(uid='new')
        self.assertFalse(extra.reforge(doc)['changed'])


if __name__ == '__main__':
    unittest.main()
