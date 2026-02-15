from __future__ import annotations

import unittest
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from zoneinfo import ZoneInfo

from misc.discord_timestamps import RecurringTimestampSpec
from misc.discord_timestamps import fixed_date_time_timestamp_tag
from misc.discord_timestamps import format_discord_timestamp
from misc.discord_timestamps import next_weekday_time
from misc.discord_timestamps import next_weekday_timestamp_tag
from misc.discord_timestamps import render_named_timestamp_placeholders


class DiscordTimestampHelperTests(unittest.TestCase):
    def test_next_weekday_time_same_day_future_returns_today(self):
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 2, 2, 12, 0, tzinfo=tz)  # Monday
        out = next_weekday_time(weekday=0, hour=13, minute=30, timezone_name="America/New_York", now=now)
        self.assertEqual(out.date(), now.date())
        self.assertEqual((out.hour, out.minute), (13, 30))

    def test_next_weekday_time_same_day_past_returns_next_week(self):
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 2, 2, 14, 0, tzinfo=tz)  # Monday
        out = next_weekday_time(weekday=0, hour=13, minute=30, timezone_name="America/New_York", now=now)
        self.assertEqual(out.date(), now.date() + timedelta(days=7))
        self.assertEqual((out.hour, out.minute), (13, 30))

    def test_format_discord_timestamp_aware_datetime(self):
        dt = datetime(2026, 2, 2, 13, 30, tzinfo=timezone.utc)
        self.assertEqual(format_discord_timestamp(dt, style="f"), f"<t:{int(dt.timestamp())}:f>")

    def test_next_weekday_time_dst_boundary_preserves_wall_clock_time(self):
        # DST starts Sunday, March 8, 2026 in America/New_York.
        tz = ZoneInfo("America/New_York")
        now = datetime(2026, 3, 7, 23, 0, tzinfo=tz)  # Saturday night before DST shift
        out = next_weekday_time(weekday=6, hour=13, minute=30, timezone_name="America/New_York", now=now)
        self.assertEqual(out.date().isoformat(), "2026-03-08")
        self.assertEqual((out.hour, out.minute), (13, 30))

    def test_fixed_date_time_timestamp_tag_known_reference(self):
        event_date = date(2026, 7, 4)
        expected_dt = datetime(2026, 7, 4, 9, 15, tzinfo=ZoneInfo("America/New_York"))
        expected = f"<t:{int(expected_dt.timestamp())}:F>"
        out = fixed_date_time_timestamp_tag(
            date=event_date,
            hour=9,
            minute=15,
            timezone_name="America/New_York",
            style="F",
        )
        self.assertEqual(out, expected)

    def test_format_discord_timestamp_rejects_naive_datetime(self):
        with self.assertRaises(ValueError):
            format_discord_timestamp(datetime(2026, 1, 1, 0, 0), style="f")

    def test_helpers_raise_for_invalid_style_and_timezone(self):
        with self.assertRaises(ValueError):
            next_weekday_timestamp_tag(
                weekday=0,
                hour=13,
                minute=30,
                timezone_name="America/New_York",
                style="bad",
                now=datetime(2026, 2, 2, 12, 0, tzinfo=timezone.utc),
            )
        with self.assertRaises(ValueError):
            fixed_date_time_timestamp_tag(
                date=date(2026, 1, 1),
                hour=13,
                minute=30,
                timezone_name="Mars/Olympus",
                style="f",
            )

    def test_placeholder_named_replacement(self):
        now = datetime(2026, 2, 2, 12, 0, tzinfo=timezone.utc)
        events = {
            "monday_workshop": RecurringTimestampSpec(
                weekday=0,
                hour=13,
                minute=30,
                timezone="America/New_York",
                style="f",
            )
        }
        expected_tag = next_weekday_timestamp_tag(
            weekday=0,
            hour=13,
            minute=30,
            timezone_name="America/New_York",
            style="f",
            now=now,
        )
        result = render_named_timestamp_placeholders(
            "Starts {{DISCORD_TS:monday_workshop}}",
            events=events,
            now=now,
        )
        self.assertEqual(result.text, f"Starts {expected_tag}")
        self.assertEqual(result.resolved_count, 1)
        self.assertEqual(result.unresolved_names, [])
        self.assertEqual(result.raw_tag_count, 1)
        self.assertFalse(result.blocked)

    def test_placeholder_unresolved_passthrough_vs_block(self):
        text = "Starts {{DISCORD_TS:unknown_event}}"
        result_passthrough = render_named_timestamp_placeholders(
            text,
            events={},
            unresolved_policy="passthrough",
        )
        self.assertEqual(result_passthrough.text, text)
        self.assertEqual(result_passthrough.unresolved_names, ["unknown_event"])
        self.assertFalse(result_passthrough.blocked)
        self.assertIsNone(result_passthrough.block_reason)

        result_block = render_named_timestamp_placeholders(
            text,
            events={},
            unresolved_policy="block",
        )
        self.assertTrue(result_block.blocked)
        self.assertEqual(result_block.block_reason, "unresolved_placeholders")
        self.assertEqual(result_block.unresolved_names, ["unknown_event"])

    def test_placeholder_raw_tag_allow_vs_block(self):
        text = "Starts <t:1770316200:f>"
        result_allow = render_named_timestamp_placeholders(
            text,
            events={},
            raw_tag_policy="allow",
        )
        self.assertFalse(result_allow.blocked)
        self.assertEqual(result_allow.raw_tag_count, 1)

        result_block = render_named_timestamp_placeholders(
            text,
            events={},
            raw_tag_policy="block",
        )
        self.assertTrue(result_block.blocked)
        self.assertEqual(result_block.block_reason, "raw_timestamp_tags")
        self.assertEqual(result_block.raw_tag_count, 1)


if __name__ == "__main__":
    unittest.main()
