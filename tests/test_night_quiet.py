import unittest
from datetime import datetime, timezone

from core.night_quiet import is_quiet, window_start


def ts(hour: int, day: int = 21) -> float:
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc).timestamp()


class NightQuietTests(unittest.TestCase):
    def test_regular_window_uses_configured_offset(self):
        self.assertTrue(is_quiet(ts(16), True, 0, 8, 8))
        self.assertFalse(is_quiet(ts(8), True, 0, 8, 8))

    def test_overnight_window_and_start(self):
        now = ts(22)
        self.assertTrue(is_quiet(now, True, 22, 6, 0))
        self.assertEqual(window_start(now, 22, 6, 0), now)
        self.assertTrue(is_quiet(ts(4), True, 22, 6, 0))
        self.assertFalse(is_quiet(ts(12), True, 22, 6, 0))

    def test_disabled_invalid_and_equal_hours(self):
        self.assertFalse(is_quiet(ts(2), False, 0, 8))
        self.assertFalse(is_quiet(ts(2), True, 0, 0))
        self.assertFalse(is_quiet(ts(2), True, 30, 8))


if __name__ == "__main__":
    unittest.main()
