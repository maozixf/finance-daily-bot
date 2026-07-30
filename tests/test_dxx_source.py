import unittest
from datetime import date
from unittest.mock import patch

from finance_bot.dxx_source import DxxClient


class DxxSourceTests(unittest.TestCase):
    @patch("finance_bot.dxx_source.fetch_section")
    def test_today_hot_filters_exact_beijing_date(self, fetch_section):
        fetch_section.return_value = {
            "items": [
                *[
                    {"date": "2026-07-28", "title": f"A{index}"}
                    for index in range(12)
                ],
                {"date": "2026-07-27", "title": "B"},
            ]
        }
        items = DxxClient().today_hot(date(2026, 7, 28))
        self.assertEqual(len(items), 12)
        self.assertEqual(items[-1]["title"], "A11")

    @patch("finance_bot.dxx_source.fetch_section")
    def test_calendar_covers_current_and_next_week(self, fetch_section):
        fetch_section.return_value = {
            "items": [
                {"date": "2026-07-27", "event": "second alphabetically"},
                {"date": "2026-07-27", "event": "first alphabetically"},
                {"date": "2026-08-09", "event": "end"},
                {"date": "2026-08-10", "event": "outside"},
            ]
        }
        start, end, items = DxxClient().two_week_calendar(date(2026, 7, 30))
        self.assertEqual(start, date(2026, 7, 27))
        self.assertEqual(end, date(2026, 8, 9))
        self.assertEqual(
            [item["event"] for item in items],
            ["second alphabetically", "first alphabetically", "end"],
        )

    @patch("finance_bot.dxx_source.fetch_section")
    def test_calendar_covers_tomorrow_and_day_after(self, fetch_section):
        fetch_section.return_value = {
            "items": [
                {"date": "2026-07-30", "event": "outside"},
                {"date": "2026-07-31", "event": "明日第一项"},
                {"date": "2026-07-31", "event": "明日第二项"},
                {"date": "2026-08-01", "event": "后天第一项"},
                {"date": "2026-08-02", "event": "outside"},
            ]
        }
        start, end, items = DxxClient().tomorrow_day_after_calendar(
            date(2026, 7, 30)
        )
        self.assertEqual(start, date(2026, 7, 31))
        self.assertEqual(end, date(2026, 8, 1))
        self.assertEqual(
            [item["event"] for item in items],
            ["明日第一项", "明日第二项", "后天第一项"],
        )


if __name__ == "__main__":
    unittest.main()
