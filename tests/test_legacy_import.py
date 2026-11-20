import json
import tempfile
import unittest
from pathlib import Path

from core.legacy_import import normalize_inventory, normalize_player, preflight


class LegacyImportTests(unittest.TestCase):
    def test_player_and_inventory_normalize_without_loss(self):
        doc, warnings = normalize_player({"名号": "甲", "修为": "12", "灵石": 88, "自定义": {"x": 1}}, "qg_7")
        self.assertEqual(doc["uid"], "7")
        self.assertEqual(doc["exp"], 12)
        self.assertEqual(doc["stones"], 88)
        self.assertEqual(doc["ext"]["legacy_source"]["自定义"], {"x": 1})
        inv, inv_warnings = normalize_inventory({"丹药": [{"name": "筑基丹", "数量": 2}], "装备": [{"name": "剑"}]})
        self.assertEqual(inv, {"筑基丹": 2, "剑": 1})
        self.assertFalse(warnings)
        self.assertFalse(inv_warnings)

    def test_preflight_rejects_duplicate_uids_and_reports_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "xiuxian_player").mkdir()
            (root / "xiuxian_najie").mkdir()
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
