"""
Unit tests for utility functions
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
import pytz

from chronos_mcp.utils import (
    _default_tz,
    _is_date_only,
    _resolve_default_tz,
    create_ical_event,
    datetime_to_ical,
    ical_to_datetime,
    parse_datetime,
)


@pytest.fixture(autouse=True)
def _clear_default_tz_cache():
    """Reset the cached default-timezone resolver so env changes take effect."""
    _resolve_default_tz.cache_clear()
    yield
    _resolve_default_tz.cache_clear()


class TestDefaultTimezone:
    """Test the CHRONOS_DEFAULT_TIMEZONE-driven default timezone source"""

    def test_default_tz_unset_is_utc(self, monkeypatch):
        """Unset env defaults to UTC (back-compat)"""
        monkeypatch.delenv("CHRONOS_DEFAULT_TIMEZONE", raising=False)
        assert _default_tz() == timezone.utc

    def test_default_tz_named_zone(self, monkeypatch):
        """A valid IANA name resolves to that zone"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "America/New_York")
        assert _default_tz() == ZoneInfo("America/New_York")

    def test_default_tz_invalid_falls_back_and_warns(self, monkeypatch, caplog):
        """An invalid name falls back to UTC and logs a warning"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "Not/AZone")
        with caplog.at_level("WARNING"):
            result = _default_tz()
        assert result == timezone.utc
        assert any(
            "CHRONOS_DEFAULT_TIMEZONE" in rec.message and "Not/AZone" in rec.message
            for rec in caplog.records
        )


class TestIsDateOnly:
    """Test the bare-YYYY-MM-DD all-day auto-detection heuristic."""

    @pytest.mark.parametrize(
        "value",
        ["2026-06-21", " 2026-06-21 ", "2026-12-01"],
    )
    def test_bare_date_is_date_only(self, value):
        assert _is_date_only(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "2026-06-21T00:00:00",  # midnight datetime: explicit all_day, not heuristic
            "2026-06-21T09:30:00",
            "2026-06-21 09:30",
            "09:30",
            "not-a-date",
            "20260621",  # no dashes ⇒ not matched by %Y-%m-%d
            "",
        ],
    )
    def test_non_bare_date_is_not_date_only(self, value):
        assert _is_date_only(value) is False

    def test_non_string_is_not_date_only(self):
        assert _is_date_only(None) is False  # type: ignore[arg-type]
        assert _is_date_only(datetime(2026, 6, 21)) is False  # type: ignore[arg-type]


class TestParseDatetime:
    """Test parse_datetime function"""

    def test_parse_datetime_object(self):
        """Test parsing when input is already a datetime"""
        dt = datetime(2025, 7, 10, 14, 0, tzinfo=timezone.utc)
        result = parse_datetime(dt)
        assert result == dt

    def test_parse_iso_string(self):
        """Test parsing ISO format string"""
        result = parse_datetime("2025-07-10T14:00:00Z")
        expected = datetime(2025, 7, 10, 14, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_parse_naive_datetime(self):
        """Test parsing datetime without timezone"""
        result = parse_datetime("2025-07-10 14:00:00")
        assert result.tzinfo == timezone.utc
        assert result.year == 2025
        assert result.month == 7
        assert result.day == 10
        assert result.hour == 14

    def test_parse_various_formats(self):
        """Test parsing various datetime formats"""
        formats = [
            "2025-07-10",
            "07/10/2025",
            "July 10, 2025",
            "2025-07-10T14:00:00+00:00",
            "2025-07-10T14:00:00-05:00",
        ]

        for fmt in formats:
            result = parse_datetime(fmt)
            assert isinstance(result, datetime)
            assert result.tzinfo is not None

    def test_parse_invalid_format(self):
        """Test parsing invalid datetime format"""
        with pytest.raises(ValueError, match="Invalid datetime format"):
            parse_datetime("not a date")

    def test_parse_naive_uses_default_zone(self, monkeypatch):
        """Naive input is stamped with CHRONOS_DEFAULT_TIMEZONE, not UTC"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "America/New_York")
        result = parse_datetime("2026-06-21 14:00:00")
        assert result.tzinfo == ZoneInfo("America/New_York")
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 21
        assert result.hour == 14

    def test_parse_aware_input_preserved(self, monkeypatch):
        """An aware input string keeps its own offset regardless of default zone"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "America/New_York")
        result = parse_datetime("2026-06-21T14:00:00+00:00")
        assert result == datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc)

    def test_parse_naive_unset_env_is_utc(self, monkeypatch):
        """Unset env keeps the historical UTC default (back-compat)"""
        monkeypatch.delenv("CHRONOS_DEFAULT_TIMEZONE", raising=False)
        result = parse_datetime("2026-06-21 14:00:00")
        assert result.tzinfo == timezone.utc
        assert result.hour == 14

    def test_parse_naive_invalid_env_is_utc(self, monkeypatch):
        """Invalid env name falls back to UTC for naive input"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "Bogus/Zone")
        result = parse_datetime("2026-06-21 14:00:00")
        assert result.tzinfo == timezone.utc
        assert result.hour == 14

    def test_naive_timed_string_serializes_to_correct_instant(self, monkeypatch):
        """A naive Eastern timed string serializes to the right UTC instant (no day shift)"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "America/New_York")
        # Midnight June 21 Eastern is the instant 04:00Z on June 21 (EDT, UTC-4) --
        # the old UTC-stamping bug rendered this as 00:00Z June 21, which a
        # New_York client shows as 20:00 June 20 (the wrong day).
        dt = parse_datetime("2026-06-21T00:00:00")
        # Assert on the represented instant, not the literal offset/Z spelling.
        assert dt.astimezone(timezone.utc) == datetime(2026, 6, 21, 4, 0, tzinfo=timezone.utc)
        # And the serialized iCal (UTC) reflects that same instant on the right day.
        assert datetime_to_ical(dt) == "20260621T040000Z"

    def test_dst_spring_forward_instant(self, monkeypatch):
        """DST boundary: a naive timed string on spring-forward day resolves correctly"""
        monkeypatch.setenv("CHRONOS_DEFAULT_TIMEZONE", "America/New_York")
        # 2026-03-08 is spring-forward in the US; 10:00 local is after the
        # 02:00->03:00 jump, so the zone is EDT (UTC-4) => 14:00Z.
        dt = parse_datetime("2026-03-08T10:00:00")
        assert dt.astimezone(timezone.utc) == datetime(2026, 3, 8, 14, 0, tzinfo=timezone.utc)


class TestDatetimeToIcal:
    """Test datetime_to_ical function"""

    def test_datetime_to_ical_regular(self):
        """Test converting regular datetime to iCal format"""
        dt = datetime(2025, 7, 10, 14, 30, 45, tzinfo=timezone.utc)
        result = datetime_to_ical(dt)
        assert result == "20250710T143045Z"

    def test_datetime_to_ical_all_day(self):
        """Test converting all-day event to iCal format"""
        dt = datetime(2025, 7, 10, 0, 0, 0, tzinfo=timezone.utc)
        result = datetime_to_ical(dt, all_day=True)
        assert result == "20250710"

    def test_datetime_to_ical_naive(self):
        """Test converting naive datetime (assumes UTC)"""
        dt = datetime(2025, 7, 10, 14, 30, 45)
        result = datetime_to_ical(dt)
        assert result == "20250710T143045Z"

    def test_datetime_to_ical_other_timezone(self):
        """Test converting datetime in non-UTC timezone"""
        eastern = pytz.timezone("US/Eastern")
        dt = eastern.localize(datetime(2025, 7, 10, 14, 30, 45))
        result = datetime_to_ical(dt)
        # Should be converted to UTC
        assert result.endswith("Z")
        assert "1830" in result or "1930" in result  # Accounts for DST


class TestIcalToDatetime:
    """Test ical_to_datetime function"""

    def test_ical_to_datetime_with_dt_attribute(self):
        """Test converting iCal object with dt attribute"""
        from icalendar import vDatetime

        ical_dt = vDatetime.from_ical("20250710T143045Z")
        result = ical_to_datetime(ical_dt)
        expected = datetime(2025, 7, 10, 14, 30, 45, tzinfo=timezone.utc)
        assert result == expected

    def test_ical_to_datetime_direct_datetime(self):
        """Test converting direct datetime object"""
        dt = datetime(2025, 7, 10, 14, 30, 45, tzinfo=timezone.utc)
        result = ical_to_datetime(dt)
        assert result == dt

    def test_ical_to_datetime_date_only(self):
        """Test converting date-only (all-day event)"""
        dt = date(2025, 7, 10)
        result = ical_to_datetime(dt)
        expected = datetime(2025, 7, 10, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_ical_to_datetime_naive(self):
        """Test converting naive datetime"""
        dt = datetime(2025, 7, 10, 14, 30, 45)
        result = ical_to_datetime(dt)
        assert result.tzinfo == timezone.utc
        assert result.replace(tzinfo=None) == dt


class TestCreateIcalEvent:
    """Test create_ical_event function"""

    def test_create_ical_event_minimal(self):
        """Test creating event with minimal data"""
        event_data = {
            "uid": "test-123",
            "summary": "Test Event",
            "start": datetime(2025, 7, 10, 14, 0, tzinfo=timezone.utc),
            "end": datetime(2025, 7, 10, 15, 0, tzinfo=timezone.utc),
        }

        event = create_ical_event(event_data)

        assert event["uid"] == "test-123"
        assert event["summary"] == "Test Event"
        assert event["dtstart"].dt == event_data["start"]
        assert event["dtend"].dt == event_data["end"]

    def test_create_ical_event_full(self):
        """Test creating event with all optional fields"""
        event_data = {
            "uid": "test-456",
            "summary": "Full Event",
            "start": datetime(2025, 7, 10, 14, 0, tzinfo=timezone.utc),
            "end": datetime(2025, 7, 10, 15, 0, tzinfo=timezone.utc),
            "description": "This is a test event",
            "location": "Conference Room A",
            "status": "CONFIRMED",
        }

        event = create_ical_event(event_data)

        assert event["uid"] == "test-456"
        assert event["summary"] == "Full Event"
        assert event["description"] == "This is a test event"
        assert event["location"] == "Conference Room A"
        assert event["status"] == "CONFIRMED"

    def test_create_ical_event_missing_optional(self):
        """Test creating event without optional fields"""
        event_data = {
            "uid": "test-789",
            "summary": "Basic Event",
            "start": datetime(2025, 7, 10, 14, 0, tzinfo=timezone.utc),
            "end": datetime(2025, 7, 10, 15, 0, tzinfo=timezone.utc),
        }

        event = create_ical_event(event_data)

        # Optional fields should not be present
        assert "description" not in event
        assert "location" not in event
        assert "status" not in event
