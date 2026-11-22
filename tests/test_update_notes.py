import unittest

from core.update_notes import format_updates


class UpdateNotesTests(unittest.TestCase):
    def test_groups_commits_by_date_and_limits_output(self):
        commits = [
            {"date": "2026-11-21", "subject": "docs: refresh help"},
            {"date": "2026-11-20", "subject": "fix: clamp occupation level"},
            {"date": "2026-11-20", "subject": "feat: add a player command"},
        ]

        text = format_updates(commits)

        self.assertIn("【修仙更新·最近 3 条】", text)
        self.assertEqual(text.count("2026-11-20"), 1)
        self.assertIn("· fix: clamp occupation level\n· feat: add a player command", text)

    def test_empty_or_invalid_entries_have_fallback(self):
        fallback = "暂时读不到更新记录"
        self.assertIn(fallback, format_updates([]))
        self.assertIn(fallback, format_updates([None, {"title": "missing subject"}]))


if __name__ == "__main__":
    unittest.main()
