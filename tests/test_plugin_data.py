import tempfile
import unittest
from pathlib import Path

from infra.plugin_data import prepare_plugin_data_dir


class PluginDataDirectoryTests(unittest.TestCase):
    def test_copies_legacy_database_and_panels_without_removing_legacy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "zhutian"
            (legacy / "panels").mkdir(parents=True)
            (legacy / "zhutian.db").write_bytes(b"database")
            (legacy / "zhutian.db-wal").write_bytes(b"wal")
            (legacy / "panels" / "status.png").write_bytes(b"panel")

            target = prepare_plugin_data_dir(root / "astrbot_zhutianxiuxian", legacy)

            self.assertEqual((target / "zhutian.db").read_bytes(), b"database")
            self.assertEqual((target / "zhutian.db-wal").read_bytes(), b"wal")
            self.assertEqual((target / "panels" / "status.png").read_bytes(), b"panel")
            self.assertEqual((legacy / "zhutian.db").read_bytes(), b"database")

    def test_migrates_into_astrbot_precreated_empty_plugin_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "astrbot_zhutianxiuxian"
            target.mkdir()
            legacy = root / "zhutian"
            legacy.mkdir()
            (legacy / "zhutian.db").write_bytes(b"legacy")

            resolved = prepare_plugin_data_dir(target, legacy)

            self.assertEqual(resolved, target)
            self.assertEqual((target / "zhutian.db").read_bytes(), b"legacy")

    def test_existing_plugin_database_wins_and_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "astrbot_zhutianxiuxian"
            target.mkdir()
            (target / "zhutian.db").write_bytes(b"current")
            legacy = root / "zhutian"
            legacy.mkdir()
            (legacy / "zhutian.db").write_bytes(b"legacy")

            resolved = prepare_plugin_data_dir(target, legacy)

            self.assertEqual(resolved, target)
            self.assertEqual((target / "zhutian.db").read_bytes(), b"current")
            self.assertEqual((legacy / "zhutian.db").read_bytes(), b"legacy")

    def test_fills_missing_files_without_replacing_existing_plugin_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "astrbot_zhutianxiuxian"
            (target / "panels").mkdir(parents=True)
            (target / "panels" / "status.png").write_bytes(b"current-panel")
            legacy = root / "zhutian"
            (legacy / "panels").mkdir(parents=True)
            (legacy / "zhutian.db").write_bytes(b"legacy")
            (legacy / "panels" / "status.png").write_bytes(b"legacy-panel")
            (legacy / "panels" / "help.png").write_bytes(b"legacy-help")

            prepare_plugin_data_dir(target, legacy)

            self.assertEqual((target / "zhutian.db").read_bytes(), b"legacy")
            self.assertEqual((target / "panels" / "status.png").read_bytes(), b"current-panel")
            self.assertEqual((target / "panels" / "help.png").read_bytes(), b"legacy-help")


if __name__ == "__main__":
    unittest.main()
