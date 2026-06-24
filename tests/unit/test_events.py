"""
Unit tests for event management
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest
import pytz
from icalendar import Calendar as iCalendar
from icalendar import Event as iEvent

from chronos_mcp.calendars import CalendarManager
from chronos_mcp.events import EventManager


class TestEventManager:
    """Test event management functionality"""

    @pytest.fixture
    def mock_calendar_manager(self):
        """Mock CalendarManager.

        ``get_events_range`` now resolves the calendar AND runs date_search inside
        one ``accounts.execute_with_reconnect`` closure (so a stale iCloud socket
        on EITHER step heals). We wire ``.accounts.execute_with_reconnect`` as a
        faithful passthrough that runs the operation against a mock principal, and
        the real ``CalendarManager.find_calendar_in_principal`` staticmethod
        resolves the calendar from that principal by url. Tests set
        ``mock_calendar_manager._test_principal`` to the principal to use.
        (Heal/reconnect behaviour itself is covered in test_reconnect_heal.py.)
        """
        mgr = Mock(spec=CalendarManager)
        # `accounts` is an instance attribute, not in the class spec — set it.
        # Give it a real default_account string so EventManager._get_default_account
        # (self.calendars.accounts.config.config.default_account) returns a str.
        mgr.accounts = Mock()
        mgr.accounts.config.config.default_account = "default"
        # find_calendar_in_principal is a staticmethod on the real class; expose it
        # so the production code's reference (CalendarManager.find_calendar_in_principal)
        # works, and the closure can call it.
        mgr.find_calendar_in_principal = CalendarManager.find_calendar_in_principal

        def _passthrough(operation, account_alias=None, request_id=None):
            principal = getattr(mgr, "_test_principal", None)
            return operation(principal)

        mgr.accounts.execute_with_reconnect.side_effect = _passthrough
        return mgr

    @staticmethod
    def _principal_with_calendar(calendar, uid):
        """Build a mock principal whose calendars() yields ``calendar`` at ``uid``."""
        calendar.url = f"https://caldav.example.com/calendars/user/{uid}/"
        principal = Mock()
        principal.calendars.return_value = [calendar]
        return principal

    @pytest.fixture
    def mock_calendar(self):
        """Mock calendar object"""
        calendar = Mock()
        calendar.save_event = Mock()
        calendar.events = Mock()
        return calendar

    @pytest.fixture
    def sample_event_data(self):
        """Sample event data for testing"""
        return {
            "calendar_uid": "cal-123",
            "summary": "Test Meeting",
            "start": datetime(2025, 7, 10, 14, 0, tzinfo=pytz.UTC),
            "end": datetime(2025, 7, 10, 15, 0, tzinfo=pytz.UTC),
            "description": "Test Description",
            "location": "Conference Room A",
            "account_alias": "test_account",
        }

    def test_init(self, mock_calendar_manager):
        """Test EventManager initialization"""
        mgr = EventManager(mock_calendar_manager)
        assert mgr.calendars == mock_calendar_manager

    def test_create_event_calendar_not_found(self, mock_calendar_manager, sample_event_data):
        """Test creating event when calendar not found"""
        mock_calendar_manager.get_calendar.return_value = None
        mgr = EventManager(mock_calendar_manager)

        # Should raise CalendarNotFoundError
        from chronos_mcp.exceptions import CalendarNotFoundError

        with pytest.raises(CalendarNotFoundError) as exc_info:
            mgr.create_event(**sample_event_data)

        assert "cal-123" in str(exc_info.value)
        mock_calendar_manager.get_calendar.assert_called_once()

    def test_create_event_connection_error_not_masked_as_not_found(
        self, mock_calendar_manager, sample_event_data
    ):
        """De-mask end-to-end: a cold-start connect timeout raised by get_calendar
        surfaces as AccountConnectionError, NOT a misleading CalendarNotFoundError."""
        from chronos_mcp.exceptions import (
            AccountConnectionError,
            CalendarNotFoundError,
        )

        mock_calendar_manager.get_calendar.side_effect = AccountConnectionError("icloud")
        mgr = EventManager(mock_calendar_manager)

        with pytest.raises(AccountConnectionError):
            mgr.create_event(**sample_event_data)

        # And explicitly: it is NOT a CalendarNotFoundError.
        mock_calendar_manager.get_calendar.side_effect = AccountConnectionError("icloud")
        try:
            mgr.create_event(**sample_event_data)
        except CalendarNotFoundError:  # pragma: no cover - must not happen
            pytest.fail("connection timeout was masked as CalendarNotFoundError")
        except AccountConnectionError:
            pass

    @patch("chronos_mcp.events.uuid.uuid4")
    def test_create_event_success(
        self, mock_uuid, mock_calendar_manager, mock_calendar, sample_event_data
    ):
        """Test successful event creation"""
        mock_uuid.return_value = "evt-test-123"
        mock_calendar_manager.get_calendar.return_value = mock_calendar
        mock_caldav_event = Mock()
        mock_calendar.save_event.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        result = mgr.create_event(**sample_event_data)

        assert result is not None
        assert result.uid == "evt-test-123"
        assert result.summary == "Test Meeting"
        assert result.description == "Test Description"
        assert result.location == "Conference Room A"
        assert result.calendar_uid == "cal-123"
        assert result.account_alias == "test_account"

        # Verify calendar.save_event was called with proper ical data
        mock_calendar.save_event.assert_called_once()
        ical_data = mock_calendar.save_event.call_args[0][0]
        assert "BEGIN:VCALENDAR" in ical_data

    @patch("chronos_mcp.events.uuid.uuid4")
    def test_create_event_preserves_timezone_as_utc(
        self, mock_uuid, mock_calendar_manager, mock_calendar
    ):
        """Test that non-UTC timezone is converted to UTC in iCal output (issue #17)"""
        mock_uuid.return_value = "evt-tz-test"
        mock_calendar_manager.get_calendar.return_value = mock_calendar
        mock_calendar.save_event.return_value = Mock()

        mgr = EventManager(mock_calendar_manager)

        eastern = pytz.timezone("US/Eastern")
        start_local = eastern.localize(datetime(2025, 7, 10, 14, 0))
        end_local = eastern.localize(datetime(2025, 7, 10, 15, 0))

        result = mgr.create_event(
            calendar_uid="cal-123",
            summary="Timezone Test",
            start=start_local,
            end=end_local,
        )

        assert result is not None
        ical_data = mock_calendar.save_event.call_args[0][0]
        assert "BEGIN:VCALENDAR" in ical_data
        assert "SUMMARY:Timezone Test" in ical_data
        # DTSTART and DTEND should be in UTC (14:00 EDT = 18:00 UTC)
        assert "DTSTART:20250710T180000Z" in ical_data
        assert "DTEND:20250710T190000Z" in ical_data

    def test_create_event_with_attendees(
        self, mock_calendar_manager, mock_calendar, sample_event_data
    ):
        """Test creating event with attendees"""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        attendees = [
            {
                "email": "user1@example.com",
                "name": "User One",
                "role": "REQ-PARTICIPANT",
            },
            {
                "email": "user2@example.com",
                "name": "User Two",
                "role": "OPT-PARTICIPANT",
                "rsvp": False,
            },
        ]
        sample_event_data["attendees"] = attendees

        mgr = EventManager(mock_calendar_manager)
        result = mgr.create_event(**sample_event_data)

        assert result is not None
        assert len(result.attendees) == 2
        assert result.attendees[0].email == "user1@example.com"
        assert result.attendees[1].role == "OPT-PARTICIPANT"

        # Check ical contains attendees
        ical_data = mock_calendar.save_event.call_args[0][0]
        assert "ATTENDEE" in ical_data
        assert "mailto:user1@example.com" in ical_data

    def test_create_event_with_alarm(self, mock_calendar_manager, mock_calendar, sample_event_data):
        """Test creating event with alarm"""
        mock_calendar_manager.get_calendar.return_value = mock_calendar
        sample_event_data["alarm_minutes"] = 15

        mgr = EventManager(mock_calendar_manager)
        result = mgr.create_event(**sample_event_data)

        assert result is not None
        assert result.alarms is not None
        assert len(result.alarms) == 1
        assert result.alarms[0].trigger == "-PT15M"
        assert result.alarms[0].action == "DISPLAY"

        # Check ical contains alarm
        ical_data = mock_calendar.save_event.call_args[0][0]
        assert "BEGIN:VALARM" in ical_data
        assert "TRIGGER:-PT15M" in ical_data

    def test_create_event_with_recurrence(
        self, mock_calendar_manager, mock_calendar, sample_event_data
    ):
        """Test creating recurring event"""
        mock_calendar_manager.get_calendar.return_value = mock_calendar
        sample_event_data["recurrence_rule"] = "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10"

        mgr = EventManager(mock_calendar_manager)
        result = mgr.create_event(**sample_event_data)

        assert result is not None
        assert result.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10"

        # Check ical contains rrule (iCalendar reorders: COUNT before BYDAY)
        ical_data = mock_calendar.save_event.call_args[0][0]
        assert "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=MO,WE,FR" in ical_data

    def test_create_event_all_day(self, mock_calendar_manager, mock_calendar):
        """Test creating all-day event"""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mgr = EventManager(mock_calendar_manager)
        result = mgr.create_event(
            calendar_uid="cal-123",
            summary="All Day Event",
            start=datetime(2025, 7, 10, 0, 0, tzinfo=pytz.UTC),
            end=datetime(2025, 7, 11, 0, 0, tzinfo=pytz.UTC),
            all_day=True,
        )

        assert result is not None
        assert result.all_day is True

    def test_create_event_exception(self, mock_calendar_manager, mock_calendar, sample_event_data):
        """Test event creation with exception"""
        mock_calendar_manager.get_calendar.return_value = mock_calendar
        mock_calendar.save_event.side_effect = Exception("CalDAV error")

        mgr = EventManager(mock_calendar_manager)

        # Should raise EventCreationError
        from chronos_mcp.exceptions import EventCreationError

        with pytest.raises(EventCreationError) as exc_info:
            mgr.create_event(**sample_event_data)

        assert "CalDAV error" in str(exc_info.value)

    def test_get_events_range_calendar_not_found(self, mock_calendar_manager):
        """Test getting events when calendar not found"""
        # Principal has no calendar matching the requested uid.
        empty_principal = Mock()
        empty_principal.calendars.return_value = []
        mock_calendar_manager._test_principal = empty_principal

        mgr = EventManager(mock_calendar_manager)

        # Should raise CalendarNotFoundError
        from chronos_mcp.exceptions import CalendarNotFoundError

        with pytest.raises(CalendarNotFoundError) as exc_info:
            mgr.get_events_range(
                calendar_uid="cal-123",
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(days=1),
            )

        assert "cal-123" in str(exc_info.value)

    def test_get_events_range_success(self, mock_calendar_manager, mock_calendar):
        """Test successful event range retrieval"""
        mock_calendar_manager._test_principal = self._principal_with_calendar(
            mock_calendar, "cal-123"
        )

        # Create mock CalDAV events
        mock_event1 = Mock()
        mock_event1.data = """BEGIN:VEVENT
UID:evt-1
SUMMARY:Event 1
DTSTART:20250710T140000Z
DTEND:20250710T150000Z
END:VEVENT"""

        mock_event2 = Mock()
        mock_event2.data = """BEGIN:VEVENT
UID:evt-2
SUMMARY:Event 2
DTSTART:20250710T160000Z
DTEND:20250710T170000Z
DESCRIPTION:Test description
LOCATION:Room B
END:VEVENT"""

        mock_calendar.date_search.return_value = [mock_event1, mock_event2]

        mgr = EventManager(mock_calendar_manager)
        result = mgr.get_events_range(
            calendar_uid="cal-123",
            start_date=datetime(2025, 7, 10, 0, 0, tzinfo=pytz.UTC),
            end_date=datetime(2025, 7, 11, 0, 0, tzinfo=pytz.UTC),
        )

        assert len(result) == 2
        assert result[0].uid == "evt-1"
        assert result[0].summary == "Event 1"
        assert result[1].uid == "evt-2"
        assert result[1].summary == "Event 2"
        assert result[1].description == "Test description"
        assert result[1].location == "Room B"

    def test_get_events_range_with_attendees(self, mock_calendar_manager, mock_calendar):
        """Test getting events with attendees"""
        mock_calendar_manager._test_principal = self._principal_with_calendar(
            mock_calendar, "cal-123"
        )

        mock_event = Mock()
        mock_event.data = """BEGIN:VEVENT
UID:evt-3
SUMMARY:Meeting
DTSTART:20250710T140000Z
DTEND:20250710T150000Z
ATTENDEE;CN=User One;ROLE=REQ-PARTICIPANT:mailto:user1@example.com
ATTENDEE;CN=User Two;ROLE=OPT-PARTICIPANT;RSVP=FALSE:mailto:user2@example.com
END:VEVENT"""

        mock_calendar.date_search.return_value = [mock_event]

        mgr = EventManager(mock_calendar_manager)
        result = mgr.get_events_range(
            calendar_uid="cal-123",
            start_date=datetime(2025, 7, 10, tzinfo=pytz.UTC),
            end_date=datetime(2025, 7, 11, tzinfo=pytz.UTC),
        )

        assert len(result) == 1
        assert len(result[0].attendees) == 2
        assert result[0].attendees[0].email == "user1@example.com"
        assert result[0].attendees[0].name == "User One"
        assert result[0].attendees[1].role == "OPT-PARTICIPANT"

    def test_get_events_range_exception_propagates(self, mock_calendar_manager, mock_calendar):
        """De-mask: a date_search failure must NOT be swallowed to [].

        The old code did `except Exception: return events` (empty), masking a
        stale-socket timeout as "0 events, no error". The heal path retries
        connection errors once; a genuine persistent error now surfaces honestly
        instead of pretending the range is empty.
        """
        mock_calendar.date_search.side_effect = Exception("CalDAV error")
        mock_calendar_manager._test_principal = self._principal_with_calendar(
            mock_calendar, "cal-123"
        )

        mgr = EventManager(mock_calendar_manager)
        with pytest.raises(Exception, match="CalDAV error"):
            mgr.get_events_range(
                calendar_uid="cal-123",
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(days=1),
            )

    def test_delete_event_calendar_not_found(self, mock_calendar_manager):
        """Test deleting event when calendar not found"""
        from unittest.mock import ANY

        from chronos_mcp.exceptions import CalendarNotFoundError

        mock_calendar_manager.get_calendar.return_value = None

        mgr = EventManager(mock_calendar_manager)

        # Should raise CalendarNotFoundError
        with pytest.raises(CalendarNotFoundError) as exc_info:
            mgr.delete_event("cal-123", "evt-123")

        assert "cal-123" in str(exc_info.value)
        mock_calendar_manager.get_calendar.assert_called_once_with("cal-123", None, request_id=ANY)

    def test_create_event_with_valid_rrule(self, mock_calendar_manager, mock_calendar):
        """Test creating event with valid RRULE"""
        mock_calendar_manager.get_calendar.return_value = mock_calendar
        mock_calendar.save_event.return_value = Mock()

        mgr = EventManager(mock_calendar_manager)

        # Test with daily recurrence
        event = mgr.create_event(
            calendar_uid="cal-123",
            summary="Daily Standup",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
            recurrence_rule="FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=20",
        )

        assert event is not None
        assert event.summary == "Daily Standup"
        assert event.recurrence_rule == "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=20"

        # Verify the iCalendar was created with RRULE (iCalendar reorders: COUNT before BYDAY)
        mock_calendar.save_event.assert_called_once()
        ical_data = mock_calendar.save_event.call_args[0][0]
        assert "RRULE:FREQ=DAILY;COUNT=20;BYDAY=MO,TU,WE,TH,FR" in ical_data

    def test_create_event_with_invalid_rrule(self, mock_calendar_manager, mock_calendar):
        """Test creating event with invalid RRULE raises error"""
        from chronos_mcp.exceptions import EventCreationError

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mgr = EventManager(mock_calendar_manager)

        # Test with invalid RRULE
        with pytest.raises(EventCreationError) as exc_info:
            mgr.create_event(
                calendar_uid="cal-123",
                summary="Bad Recurring Event",
                start=datetime.now(),
                end=datetime.now() + timedelta(hours=1),
                recurrence_rule="INVALID=RRULE",
            )

        assert "Invalid RRULE" in str(exc_info.value)
        # Should not have called save_event due to validation failure
        mock_calendar.save_event.assert_not_called()

    def test_update_event_success(self, mock_calendar_manager, mock_calendar):
        """Test successful event update"""

        # Setup
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        # Create mock CalDAV event
        mock_caldav_event = MagicMock()

        # Create test iCalendar data
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-123")
        event.add("summary", "Original Title")
        event.add("description", "Original Description")
        event.add("dtstart", datetime.now())
        event.add("dtend", datetime.now() + timedelta(hours=1))
        event.add("location", "Original Location")
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Update event
        updated_event = mgr.update_event(  # noqa: F841
            calendar_uid="cal-123",
            event_uid="evt-123",
            summary="Updated Title",
            description="Updated Description",
        )

        # Verify update was called
        mock_caldav_event.save.assert_called_once()

        # Verify the event data was updated
        saved_data = mock_caldav_event.data
        assert "Updated Title" in saved_data
        assert "Updated Description" in saved_data
        assert "Original Location" in saved_data  # Unchanged field

    def test_update_event_partial_update(self, mock_calendar_manager, mock_calendar):
        """Test updating only specific fields"""

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        # Create mock CalDAV event with full data
        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-123")
        event.add("summary", "Original Title")
        event.add("description", "Original Description")
        event.add("dtstart", datetime.now())
        event.add("dtend", datetime.now() + timedelta(hours=1))
        event.add("location", "Conference Room A")
        event.add("rrule", "FREQ=WEEKLY;BYDAY=MO")
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Update only location
        mgr.update_event(calendar_uid="cal-123", event_uid="evt-123", location="Conference Room B")

        # Verify save was called
        mock_caldav_event.save.assert_called_once()

        # Verify only location changed
        saved_data = mock_caldav_event.data
        assert "Original Title" in saved_data
        assert "Original Description" in saved_data
        assert "Conference Room B" in saved_data
        assert "FREQ=WEEKLY;BYDAY=MO" in saved_data

    def test_update_event_remove_optional_fields(self, mock_calendar_manager, mock_calendar):
        """Test removing optional fields by setting them to empty string"""

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        # Create event with optional fields
        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-123")
        event.add("summary", "Meeting")
        event.add("description", "Team sync")
        event.add("location", "Room 101")
        event.add("dtstart", datetime.now())
        event.add("dtend", datetime.now() + timedelta(hours=1))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Remove description and location
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-123",
            description="",  # Empty string removes field
            location="",  # Empty string removes field
        )

        saved_data = mock_caldav_event.data
        assert "Meeting" in saved_data  # Summary unchanged
        assert "Team sync" not in saved_data  # Description removed
        assert "Room 101" not in saved_data  # Location removed

    def test_update_event_not_found(self, mock_calendar_manager, mock_calendar):
        """Test updating non-existent event"""
        from chronos_mcp.exceptions import EventNotFoundError

        mock_calendar_manager.get_calendar.return_value = mock_calendar
        mock_calendar.event_by_uid.side_effect = Exception("Not found")
        mock_calendar.events.return_value = []  # No events

        mgr = EventManager(mock_calendar_manager)

        with pytest.raises(EventNotFoundError) as exc_info:
            mgr.update_event(calendar_uid="cal-123", event_uid="non-existent", summary="New Title")

        assert "non-existent" in str(exc_info.value)

    def test_update_event_invalid_rrule(self, mock_calendar_manager, mock_calendar):
        """Test updating event with invalid RRULE"""
        from chronos_mcp.exceptions import EventCreationError

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        # Create simple event
        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-123")
        event.add("summary", "Meeting")
        event.add("dtstart", datetime.now())
        event.add("dtend", datetime.now() + timedelta(hours=1))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Try to update with invalid RRULE
        with pytest.raises(EventCreationError) as exc_info:
            mgr.update_event(
                calendar_uid="cal-123",
                event_uid="evt-123",
                recurrence_rule="INVALID=RRULE",
            )

        assert "Invalid RRULE" in str(exc_info.value)
        # Verify save was NOT called due to validation failure
        mock_caldav_event.save.assert_not_called()

    def test_update_event_duration_only_no_dtend(self, mock_calendar_manager, mock_calendar):
        """Regression: updating start/end on an event that carries DURATION (no DTEND)
        must NOT raise KeyError; the resulting event must have a well-formed DTEND and
        the stale DURATION must be removed."""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-dur")
        event.add("summary", "Duration Event")
        event.add("dtstart", datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC))
        event.add("duration", timedelta(hours=1))  # DURATION instead of DTEND
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Edit the time window — supplies both start and end.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-dur",
            start=datetime(2026, 6, 23, 11, 0, tzinfo=pytz.UTC),
            end=datetime(2026, 6, 23, 12, 30, tzinfo=pytz.UTC),
        )

        # No KeyError raised, save() called.
        mock_caldav_event.save.assert_called_once()

        # Re-parse and assert a well-formed DTEND, DURATION removed.
        saved = iCalendar.from_ical(mock_caldav_event.data)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert "dtend" in vevent
        assert "duration" not in vevent
        assert vevent["dtend"].dt == datetime(2026, 6, 23, 12, 30, tzinfo=pytz.UTC)
        assert vevent["dtstart"].dt == datetime(2026, 6, 23, 11, 0, tzinfo=pytz.UTC)

    def test_update_event_allday_to_timed(self, mock_calendar_manager, mock_calendar):
        """Regression: updating an existing all-day event (DTSTART;VALUE=DATE) to a timed
        slot yields valid date-time DTSTART/DTEND with no stray VALUE=DATE param."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-allday")
        event.add("summary", "All Day")
        event.add("dtstart", date(2026, 6, 23))  # VALUE=DATE
        event.add("dtend", date(2026, 6, 24))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Caller supplies timed datetimes but omits all_day -> override to timed.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-allday",
            start=datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC),
            end=datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        # Raw ical must not carry VALUE=DATE on DTSTART/DTEND anymore.
        raw = mock_caldav_event.data
        assert "VALUE=DATE" not in raw

        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert isinstance(vevent["dtstart"].dt, datetime)
        assert isinstance(vevent["dtend"].dt, datetime)
        assert vevent["dtstart"].dt == datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC)
        assert vevent["dtend"].dt == datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC)

    def test_update_event_summary_only_preserves_duration(
        self, mock_calendar_manager, mock_calendar
    ):
        """Regression: a summary-only update on a DURATION-only event must leave DURATION
        intact and must NOT inject an accidental DTEND."""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-dur2")
        event.add("summary", "Original")
        event.add("dtstart", datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC))
        event.add("duration", timedelta(hours=2))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-dur2",
            summary="Renamed",
        )

        mock_caldav_event.save.assert_called_once()

        saved = iCalendar.from_ical(mock_caldav_event.data)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert str(vevent["summary"]) == "Renamed"
        assert "duration" in vevent  # DURATION preserved
        assert "dtend" not in vevent  # no accidental DTEND

    def test_update_event_end_only_on_timed_event(self, mock_calendar_manager, mock_calendar):
        """Regression (truth-table end-only): updating only `end` (no `start`, all_day
        omitted) on a timed event leaves DTSTART untouched and re-adds DTEND as a
        matching timed value."""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        original_start = datetime(2026, 6, 23, 14, 0, tzinfo=pytz.UTC)

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-timed")
        event.add("summary", "Timed")
        event.add("dtstart", original_start)
        event.add("dtend", datetime(2026, 6, 23, 15, 0, tzinfo=pytz.UTC))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-timed",
            end=datetime(2026, 6, 23, 16, 30, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        saved = iCalendar.from_ical(mock_caldav_event.data)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        # DTSTART untouched, still timed.
        assert isinstance(vevent["dtstart"].dt, datetime)
        assert vevent["dtstart"].dt == original_start
        # DTEND re-added as the new timed value.
        assert isinstance(vevent["dtend"].dt, datetime)
        assert vevent["dtend"].dt == datetime(2026, 6, 23, 16, 30, tzinfo=pytz.UTC)

    def test_update_event_last_modified_well_formed(self, mock_calendar_manager, mock_calendar):
        """Regression: the updated event's LAST-MODIFIED must be a valid iCal UTC date-time
        (e.g. 20260624T013517Z), NOT a bare Python datetime str ('2026-06-24 01:35:17+00:00').
        The latter is what a dict-set `event["last-modified"] = datetime(...)` produces, and
        strict CalDAV servers (Radicale, iCloud) reject it with 400 Bad Request on PUT."""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-lastmod")
        event.add("summary", "LastMod")
        event.add("dtstart", datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC))
        event.add("dtend", datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-lastmod",
            start=datetime(2026, 6, 23, 14, 30, tzinfo=pytz.UTC),
            end=datetime(2026, 6, 23, 15, 30, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        raw = mock_caldav_event.data
        # The malformed serialization carries a space + offset; the valid one is compact UTC.
        lastmod_lines = [ln for ln in raw.splitlines() if ln.startswith("LAST-MODIFIED")]
        assert lastmod_lines, "LAST-MODIFIED not present"
        for ln in lastmod_lines:
            assert " " not in ln, f"malformed LAST-MODIFIED (raw datetime str): {ln!r}"
            assert "+00:00" not in ln, f"malformed LAST-MODIFIED (offset, not Z): {ln!r}"
            assert ln.rstrip().endswith("Z"), f"LAST-MODIFIED not UTC Z-form: {ln!r}"
        # And it re-parses cleanly as a datetime.
        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert isinstance(vevent["last-modified"].dt, datetime)

    def test_update_event_end_only_timed_on_allday_event(
        self, mock_calendar_manager, mock_calendar
    ):
        """Regression (MAJOR): an end-only TIMED edit on an existing ALL-DAY event must
        coerce the UNTOUCHED DTSTART to timed as well, so the pair never mixes a
        VALUE=DATE DTSTART with a timed DTEND (the malformed shape strict CalDAV rejects)."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-allday-end")
        event.add("summary", "All Day")
        event.add("dtstart", date(2026, 6, 23))  # VALUE=DATE
        event.add("dtend", date(2026, 6, 24))  # VALUE=DATE
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Only `end` supplied, with a time component -> resolves to timed.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-allday-end",
            end=datetime(2026, 6, 23, 15, 30, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        raw = mock_caldav_event.data
        assert "VALUE=DATE" not in raw  # no stray VALUE=DATE on either endpoint

        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        # BOTH endpoints must be timed datetimes.
        assert isinstance(vevent["dtstart"].dt, datetime)
        assert isinstance(vevent["dtend"].dt, datetime)
        # DTSTART coerced from the original 2026-06-23 date to midnight UTC.
        assert vevent["dtstart"].dt == datetime(2026, 6, 23, 0, 0, tzinfo=pytz.UTC)
        assert vevent["dtend"].dt == datetime(2026, 6, 23, 15, 30, tzinfo=pytz.UTC)

    def test_update_event_start_only_timed_on_allday_event(
        self, mock_calendar_manager, mock_calendar
    ):
        """Regression (MAJOR): a start-only TIMED edit on an existing ALL-DAY event must
        coerce the UNTOUCHED DTEND to timed as well — no stray VALUE=DATE on DTEND."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-allday-start")
        event.add("summary", "All Day")
        event.add("dtstart", date(2026, 6, 23))  # VALUE=DATE
        event.add("dtend", date(2026, 6, 24))  # VALUE=DATE
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Only `start` supplied, with a time component -> resolves to timed.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-allday-start",
            start=datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        raw = mock_caldav_event.data
        assert "VALUE=DATE" not in raw  # no stray VALUE=DATE on either endpoint

        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        # BOTH endpoints must be timed datetimes.
        assert isinstance(vevent["dtstart"].dt, datetime)
        assert isinstance(vevent["dtend"].dt, datetime)
        assert vevent["dtstart"].dt == datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC)
        # DTEND coerced from the original 2026-06-24 date to midnight UTC.
        assert vevent["dtend"].dt == datetime(2026, 6, 24, 0, 0, tzinfo=pytz.UTC)

    def test_update_event_explicit_all_day_true_on_timed_event(
        self, mock_calendar_manager, mock_calendar
    ):
        """Caller-supplied all_day=True against a timed event makes BOTH DTSTART and
        DTEND become VALUE=DATE dates (the caller-value-verbatim truth-table branch)."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-timed-to-allday")
        event.add("summary", "Timed")
        event.add("dtstart", datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC))
        event.add("dtend", datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-timed-to-allday",
            start=datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC),
            end=datetime(2026, 6, 24, 10, 0, tzinfo=pytz.UTC),
            all_day=True,  # explicit -> verbatim, overrides the timed datetimes
        )

        mock_caldav_event.save.assert_called_once()

        saved = iCalendar.from_ical(mock_caldav_event.data)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        # Both must be plain dates (all-day), not datetimes.
        assert isinstance(vevent["dtstart"].dt, date)
        assert not isinstance(vevent["dtstart"].dt, datetime)
        assert isinstance(vevent["dtend"].dt, date)
        assert not isinstance(vevent["dtend"].dt, datetime)
        assert vevent["dtstart"].dt == date(2026, 6, 23)
        assert vevent["dtend"].dt == date(2026, 6, 24)

    def test_update_event_explicit_all_day_false_on_allday_event(
        self, mock_calendar_manager, mock_calendar
    ):
        """Caller-supplied all_day=False against an all-day event makes BOTH DTSTART and
        DTEND become timed datetimes."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-allday-to-timed")
        event.add("summary", "All Day")
        event.add("dtstart", date(2026, 6, 23))
        event.add("dtend", date(2026, 6, 24))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-allday-to-timed",
            start=datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC),
            end=datetime(2026, 6, 23, 10, 0, tzinfo=pytz.UTC),
            all_day=False,  # explicit timed
        )

        mock_caldav_event.save.assert_called_once()

        raw = mock_caldav_event.data
        assert "VALUE=DATE" not in raw

        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert isinstance(vevent["dtstart"].dt, datetime)
        assert isinstance(vevent["dtend"].dt, datetime)

    def test_update_event_midnight_utc_treated_as_allday(
        self, mock_calendar_manager, mock_calendar
    ):
        """Boundary: a caller datetime at exactly 00:00:00 UTC (no all_day given) on an
        all-day event is treated as all-day — the midnight override does NOT fire, so the
        time is dropped and the event stays VALUE=DATE. Locks the documented behavior."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-midnight")
        event.add("summary", "All Day")
        event.add("dtstart", date(2026, 6, 23))
        event.add("dtend", date(2026, 6, 24))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Midnight-UTC start, all_day omitted -> stays all-day (time dropped).
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-midnight",
            start=datetime(2026, 6, 25, 0, 0, 0, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        saved = iCalendar.from_ical(mock_caldav_event.data)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        # Both endpoints remain plain dates (all-day preserved).
        assert isinstance(vevent["dtstart"].dt, date)
        assert not isinstance(vevent["dtstart"].dt, datetime)
        assert vevent["dtstart"].dt == date(2026, 6, 25)
        assert isinstance(vevent["dtend"].dt, date)
        assert not isinstance(vevent["dtend"].dt, datetime)

    def test_update_event_duration_only_start_only_to_allday_drops_duration(
        self, mock_calendar_manager, mock_calendar
    ):
        """Regression (MAJOR edge): a DURATION-only event (DTSTART + time-based DURATION,
        NO DTEND) edited start-only and resolving to all-day must NOT leave a time-based
        DURATION paired with a VALUE=DATE DTSTART — that mixed shape is invalid per
        RFC 5545 and strict CalDAV (Radicale/iCloud) 400s it. The stale time-based
        DURATION must be dropped (an all-day VEVENT with just DTSTART;VALUE=DATE is
        valid and implies a one-day span)."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-dur-allday")
        event.add("summary", "Duration Only")
        event.add("dtstart", datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC))
        event.add("duration", timedelta(hours=1))  # time-based PT1H, no DTEND
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Start-only edit, end omitted, all_day forced True -> resolves to all-day.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-dur-allday",
            start=datetime(2026, 6, 25, 9, 0, tzinfo=pytz.UTC),
            all_day=True,
        )

        mock_caldav_event.save.assert_called_once()

        raw = mock_caldav_event.data
        # The saved iCal must re-parse cleanly and carry no malformed mix.
        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")

        # DTSTART is VALUE=DATE (a plain date, not a datetime).
        assert isinstance(vevent["dtstart"].dt, date)
        assert not isinstance(vevent["dtstart"].dt, datetime)
        assert vevent["dtstart"].dt == date(2026, 6, 25)

        # The time-based DURATION is gone — no VALUE=DATE/timed-DURATION mix remains.
        assert "duration" not in vevent
        # No DTEND was fabricated out of thin air.
        assert "dtend" not in vevent

    def test_update_event_duration_only_baredate_start_drops_duration(
        self, mock_calendar_manager, mock_calendar
    ):
        """Same MAJOR edge reached via inference: a DURATION-only event edited with a
        bare ``date`` start (all_day omitted) infers all-day and must drop the stale
        time-based DURATION."""
        from datetime import date

        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-dur-bare")
        event.add("summary", "Duration Only Bare")
        event.add("dtstart", date(2026, 6, 23))  # already all-day VALUE=DATE
        event.add("duration", timedelta(hours=3))  # but a stale time-based DURATION
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Bare-date start, all_day omitted -> inferred all-day from existing VALUE=DATE.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-dur-bare",
            start=date(2026, 6, 25),
        )

        mock_caldav_event.save.assert_called_once()

        saved = iCalendar.from_ical(mock_caldav_event.data)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert isinstance(vevent["dtstart"].dt, date)
        assert not isinstance(vevent["dtstart"].dt, datetime)
        assert "duration" not in vevent
        assert "dtend" not in vevent

    def test_update_event_duration_only_to_timed_stays_coherent(
        self, mock_calendar_manager, mock_calendar
    ):
        """A DURATION-only event edited to a timed start (resolves timed) must stay
        coherent: DTSTART becomes a timed datetime and the time-based DURATION is left
        intact (a timed DTSTART + time-based DURATION is a valid pairing)."""
        mock_calendar_manager.get_calendar.return_value = mock_calendar

        mock_caldav_event = MagicMock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "evt-dur-timed")
        event.add("summary", "Duration Only Timed")
        event.add("dtstart", datetime(2026, 6, 23, 9, 0, tzinfo=pytz.UTC))
        event.add("duration", timedelta(hours=1))
        cal.add_component(event)

        mock_caldav_event.data = cal.to_ical().decode("utf-8")
        mock_calendar.event_by_uid.return_value = mock_caldav_event

        mgr = EventManager(mock_calendar_manager)

        # Timed start (non-midnight) -> override keeps it timed.
        mgr.update_event(
            calendar_uid="cal-123",
            event_uid="evt-dur-timed",
            start=datetime(2026, 6, 25, 14, 30, tzinfo=pytz.UTC),
        )

        mock_caldav_event.save.assert_called_once()

        raw = mock_caldav_event.data
        assert "VALUE=DATE" not in raw  # DTSTART stayed timed
        saved = iCalendar.from_ical(raw)
        vevent = next(c for c in saved.walk() if c.name == "VEVENT")
        assert isinstance(vevent["dtstart"].dt, datetime)
        assert vevent["dtstart"].dt == datetime(2026, 6, 25, 14, 30, tzinfo=pytz.UTC)
        # Time-based DURATION is valid alongside a timed DTSTART -> preserved.
        assert "duration" in vevent
        assert "dtend" not in vevent
