import json
import tempfile
import unittest
from pathlib import Path

from core.legacy_import import normalize_equipment, normalize_inventory, normalize_player, preflight


class LegacyImportTests(unittest.TestCase):
    def test_player_and_inventory_normalize_without_loss(self):
        doc, warnings = normalize_player({"名号": "甲", "level_id": 3, "Physique_id": 2,
                                          "修为": "12", "灵石": 88, "源石": 9,
                                          "仙道潜力": 45, "寿元": 70,
                                          "灵根": {"name": "天灵根", "eff": 1.5},
                                          "学习的功法": ["功法甲"], "自定义": {"x": 1}}, "qg_7")
        self.assertEqual(doc["uid"], "7")
        self.assertEqual(doc["realm_index"], 2)
        self.assertEqual(doc["physique_index"], 1)
        self.assertEqual(doc["exp"], 12)
        self.assertEqual(doc["stones"], 88)
        self.assertEqual(doc["ext"]["yuanshi"], 9)
        self.assertEqual(doc["ext"]["potential"], 45)
        self.assertEqual(doc["ext"]["lifespan"], 70)
        self.assertEqual(doc["ext"]["linggen"]["name"], "天灵根")
        self.assertEqual(doc["ext"]["gongfa"], ["功法甲"])
        self.assertEqual(doc["ext"]["legacy_source"]["自定义"], {"x": 1})
        inv, inv_warnings = normalize_inventory({"丹药": [{"name": "筑基丹", "数量": 2}], "装备": [{"name": "剑"}]})
        self.assertEqual(inv, {"筑基丹": 2, "剑": 1})
        self.assertFalse(warnings)
        self.assertFalse(inv_warnings)

    def test_equipment_file_maps_to_python_slots(self):
        equipment, warnings = normalize_equipment({
            "武器": {"name": "烂铁匕首"}, "护具": {"name": "破铜护具"},
            "帝兵": {"name": "废铁"}, "饰品": {"name": "旧饰品"},
        })
        self.assertEqual(equipment, {"武器": "烂铁匕首", "护具": "破铜护具", "帝兵": "废铁", "至宝": "旧饰品"})
        self.assertFalse(warnings)

    def test_preflight_rejects_duplicate_uids_and_reports_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "xiuxian_player").mkdir()
            (root / "xiuxian_najie").mkdir()
            (root / "xiuxian_equipment").mkdir()
            for name in ("a", "b"):
                (root / "xiuxian_player" / f"{name}.json").write_text(json.dumps({"id": "same", "名号": name}), encoding="utf-8")
            report = preflight(root)
            self.assertFalse(report["ready"])
            self.assertTrue(any("重复 UID" in error for error in report["errors"]))
            self.assertEqual(len(report["source_sha256"]), 2)

    def test_preflight_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "xiuxian_player").mkdir()
            path = root / "xiuxian_player" / "1.json"
            path.write_text(json.dumps({"id": "1", "灵石": 3}), encoding="utf-8")
            before = path.read_bytes()
            preflight(root)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
