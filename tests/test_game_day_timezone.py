from datetime import datetime, timedelta, timezone
import time
import unittest
from unittest.mock import patch

from core import academy, activity, auto_task, endless, fishing, flower, tianji, wudao


TZ_SHANGHAI = timezone(timedelta(hours=8))


class GameDayTimezoneTests(unittest.TestCase):
    def test_daily_keys_follow_shanghai_day_on_utc_hosts(self):
        before = datetime(2026, 1, 1, 23, 59, tzinfo=TZ_SHANGHAI).timestamp()
        after = datetime(2026, 1, 2, 0, 1, tzinfo=TZ_SHANGHAI).timestamp()
        keyed_functions = (
            (auto_task._day_key, ("20260101", "20260102")),
            (activity._day_key, ("20260101", "20260102")),
            (academy._day_key, ("20260101", "20260102")),
            (flower._date_key, ("2026-01-01", "2026-01-02")),
            (wudao._day_key, ("20260101", "20260102")),
        )
        for get_key, expected in keyed_functions:
            with self.subTest(function=get_key.__module__):
                with patch("time.localtime", time.gmtime):
                    self.assertEqual((get_key(before), get_key(after)), expected)

        with patch("time.localtime", time.gmtime):
            self.assertEqual((fishing._day_key(before), fishing._day_key(after)),
                             ("2026-01-01", "2026-01-02"))

    def test_daily_limits_do_not_reset_at_utc_midnight(self):
        before = datetime(2026, 1, 2, 7, 59, tzinfo=TZ_SHANGHAI).timestamp()
        after = datetime(2026, 1, 2, 8, 1, tzinfo=TZ_SHANGHAI).timestamp()
        keyed_functions = (
            auto_task._day_key,
            activity._day_key,
            academy._day_key,
            flower._date_key,
            wudao._day_key,
        )
        with patch("time.localtime", time.gmtime):
            for get_key in keyed_functions:
                with self.subTest(function=get_key.__module__):
                    self.assertEqual(get_key(before), get_key(after), get_key.__module__)
            world = {"tianji": {"day": "", "bought": {}}}
            tianji.daily_of(world, before)["item"] = 1
            self.assertEqual(tianji.daily_of(world, after), {"item": 1})

    def test_fishing_day_key_does_not_add_the_host_timezone_twice(self):
        before = datetime(2026, 1, 2, 15, 59, tzinfo=TZ_SHANGHAI).timestamp()
        after = datetime(2026, 1, 2, 16, 1, tzinfo=TZ_SHANGHAI).timestamp()
        with patch("time.localtime", lambda ts: time.gmtime(ts + 8 * 3600)):
            self.assertEqual(fishing._day_key(before), fishing._day_key(after))

    def test_weekly_free_key_uses_shanghai_calendar(self):
        now = datetime(2023, 1, 2, 0, 1, tzinfo=TZ_SHANGHAI).timestamp()
        import datetime as dt
        from types import SimpleNamespace

        class UtcDate(dt.date):
            @classmethod
            def fromtimestamp(cls, stamp):
                return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date()

        utc_host_datetime = SimpleNamespace(
            date=UtcDate, datetime=dt.datetime, timezone=dt.timezone, timedelta=dt.timedelta)
        with patch.object(endless, "datetime", utc_host_datetime):
            self.assertEqual(endless.week_key(now), "2023-W01")


if __name__ == "__main__":
    unittest.main()
