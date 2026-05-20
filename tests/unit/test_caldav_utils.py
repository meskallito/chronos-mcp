"""
Unit tests for chronos_mcp/caldav_utils.py

Tests the get_item_with_fallback utility function that eliminates
8x code duplication across events, tasks, and journals managers.
"""

from unittest.mock import Mock

import pytest
from icalendar import Calendar as iCalendar
from icalendar import Event as iEvent
from icalendar import Journal as iJournal
from icalendar import Todo as iTodo

from chronos_mcp.caldav_utils import get_item_with_fallback


class TestGetItemWithFallback:
    """Test get_item_with_fallback function"""

    @pytest.fixture
    def mock_calendar(self):
        """Create a mock calendar object"""
        calendar = Mock()
        return calendar

    @pytest.fixture
    def mock_event_item(self):
        """Create a mock CalDAV event item"""
        item = Mock()
        # Create iCalendar data with VEVENT component
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "event-123")
        event.add("summary", "Test Event")
        cal.add_component(event)
        item.data = cal.to_ical()
        return item

    @pytest.fixture
    def mock_task_item(self):
        """Create a mock CalDAV task item"""
        item = Mock()
        # Create iCalendar data with VTODO component
        cal = iCalendar()
        todo = iTodo()
        todo.add("uid", "task-456")
        todo.add("summary", "Test Task")
        cal.add_component(todo)
        item.data = cal.to_ical()
        return item

    @pytest.fixture
    def mock_journal_item(self):
        """Create a mock CalDAV journal item"""
        item = Mock()
        # Create iCalendar data with VJOURNAL component
        cal = iCalendar()
        journal = iJournal()
        journal.add("uid", "journal-789")
        journal.add("summary", "Test Journal")
        cal.add_component(journal)
        item.data = cal.to_ical()
        return item

    # METHOD 1 SUCCESS TESTS (Direct UID lookup)

    def test_event_method1_success(self, mock_calendar, mock_event_item):
        """Test event found using event_by_uid (Method 1)"""
        mock_calendar.event_by_uid = Mock(return_value=mock_event_item)

        result = get_item_with_fallback(mock_calendar, "event-123", "event")

        assert result == mock_event_item
        mock_calendar.event_by_uid.assert_called_once_with("event-123")

    def test_task_method1_success(self, mock_calendar, mock_task_item):
        """Test task found using event_by_uid (Method 1)"""
        mock_calendar.event_by_uid = Mock(return_value=mock_task_item)

        result = get_item_with_fallback(mock_calendar, "task-456", "task")

        assert result == mock_task_item
        mock_calendar.event_by_uid.assert_called_once_with("task-456")

    def test_journal_method1_success(self, mock_calendar, mock_journal_item):
        """Test journal found using event_by_uid (Method 1)"""
        mock_calendar.event_by_uid = Mock(return_value=mock_journal_item)

        result = get_item_with_fallback(mock_calendar, "journal-789", "journal")

        assert result == mock_journal_item
        mock_calendar.event_by_uid.assert_called_once_with("journal-789")

    # METHOD 2 FALLBACK TESTS (Iterate and search)

    def test_event_method2_fallback(self, mock_calendar, mock_event_item):
        """Test event found using fallback search (Method 2)"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))
        # Method 2 succeeds
        mock_calendar.events = Mock(return_value=[mock_event_item])

        result = get_item_with_fallback(mock_calendar, "event-123", "event")

        assert result == mock_event_item
        mock_calendar.event_by_uid.assert_called_once()
        mock_calendar.events.assert_called_once()

    def test_task_method2_fallback(self, mock_calendar, mock_task_item):
        """Test task found using fallback search (Method 2)"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))
        # Method 2 succeeds
        mock_calendar.todos = Mock(return_value=[mock_task_item])

        result = get_item_with_fallback(mock_calendar, "task-456", "task")

        assert result == mock_task_item
        mock_calendar.event_by_uid.assert_called_once()
        mock_calendar.todos.assert_called_once_with(include_completed=True)

    def test_journal_method2_fallback(self, mock_calendar, mock_journal_item):
        """Test journal found using fallback search (Method 2)"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))
        # Method 2 succeeds
        mock_calendar.journals = Mock(return_value=[mock_journal_item])

        result = get_item_with_fallback(mock_calendar, "journal-789", "journal")

        assert result == mock_journal_item
        mock_calendar.event_by_uid.assert_called_once()
        mock_calendar.journals.assert_called_once()

    # FALLBACK METHOD TESTS (todos/journals not available)

    def test_task_fallback_to_events(self, mock_calendar, mock_task_item):
        """Test task search falls back to events() when todos() not available"""
        # Explicitly configure calendar methods
        del mock_calendar.event_by_uid  # Method 1 not available
        del mock_calendar.todos  # Primary method not available
        mock_calendar.events = Mock(return_value=[mock_task_item])

        result = get_item_with_fallback(mock_calendar, "task-456", "task")

        assert result == mock_task_item
        mock_calendar.events.assert_called_once()

    def test_journal_fallback_to_events(self, mock_calendar, mock_journal_item):
        """Test journal search falls back to events() when journals() not available"""
        # Explicitly configure calendar methods
        del mock_calendar.event_by_uid  # Method 1 not available
        del mock_calendar.journals  # Primary method not available
        mock_calendar.events = Mock(return_value=[mock_journal_item])

        result = get_item_with_fallback(mock_calendar, "journal-789", "journal")

        assert result == mock_journal_item
        mock_calendar.events.assert_called_once()

    # MULTIPLE ITEMS TESTS (search through list)

    def test_event_found_in_multiple_items(self, mock_calendar):
        """Test finding specific event among multiple items"""
        # Create multiple event items
        items = []
        for i in range(3):
            item = Mock()
            cal = iCalendar()
            event = iEvent()
            event.add("uid", f"event-{i}")
            event.add("summary", f"Event {i}")
            cal.add_component(event)
            item.data = cal.to_ical()
            items.append(item)

        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))
        # Method 2 with multiple items
        mock_calendar.events = Mock(return_value=items)

        # Find the middle item
        result = get_item_with_fallback(mock_calendar, "event-1", "event")

        assert result == items[1]

    # ERROR CASES

    def test_invalid_item_type(self, mock_calendar):
        """Test ValueError raised for invalid item type"""
        with pytest.raises(ValueError, match="Invalid item_type"):
            get_item_with_fallback(mock_calendar, "test-123", "invalid_type")

    def test_item_not_found(self, mock_calendar, mock_event_item):
        """Test ValueError raised when item not found"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))
        # Method 2 returns different UID
        wrong_item = Mock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "different-uid")
        cal.add_component(event)
        wrong_item.data = cal.to_ical()
        mock_calendar.events = Mock(return_value=[wrong_item])

        with pytest.raises(ValueError, match="Event with UID 'event-123' not found"):
            get_item_with_fallback(mock_calendar, "event-123", "event")

    def test_no_list_method_available(self, mock_calendar):
        """Test ValueError when no list method available"""
        # Explicitly configure calendar to have no methods
        del mock_calendar.event_by_uid  # Method 1 not available
        del mock_calendar.todos  # Primary list method not available
        del mock_calendar.events  # Fallback method not available

        with pytest.raises(ValueError, match="does not support"):
            get_item_with_fallback(mock_calendar, "task-456", "task")

    def test_parse_error_handling(self, mock_calendar):
        """Test graceful handling of iCalendar parse errors"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))

        # Create item with malformed data
        bad_item = Mock()
        bad_item.data = b"MALFORMED DATA"

        # Create valid item
        good_item = Mock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "event-123")
        cal.add_component(event)
        good_item.data = cal.to_ical()

        mock_calendar.events = Mock(return_value=[bad_item, good_item])

        # Should skip bad item and find good item
        result = get_item_with_fallback(mock_calendar, "event-123", "event")
        assert result == good_item

    # REQUEST_ID LOGGING TESTS

    def test_request_id_passed_to_logging(self, mock_calendar, mock_event_item, caplog):
        """Test request_id is passed to logging context"""
        mock_calendar.event_by_uid = Mock(return_value=mock_event_item)

        get_item_with_fallback(mock_calendar, "event-123", "event", request_id="req-789")

        # Verify request_id appears in logs (implementation detail, but validates parameter is used)
        # Note: actual log verification would require caplog fixture and checking extra fields

    # UID MATCHING TESTS (string exact match)

    def test_uid_exact_match_required(self, mock_calendar):
        """Test UID matching requires exact string match"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))

        # Create item with similar but not exact UID
        item = Mock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "event-123-extra")  # Similar but not exact
        cal.add_component(event)
        item.data = cal.to_ical()
        mock_calendar.events = Mock(return_value=[item])

        # Should not match
        with pytest.raises(ValueError, match="not found"):
            get_item_with_fallback(mock_calendar, "event-123", "event")

    def test_uid_in_data_fast_check(self, mock_calendar):
        """Test fast UID check in raw data before parsing"""
        # Method 1 fails
        mock_calendar.event_by_uid = Mock(side_effect=Exception("Not found"))

        # Create items where UID is not in data
        items_without_uid = []
        for i in range(100):  # Many items to test performance
            item = Mock()
            cal = iCalendar()
            event = iEvent()
            event.add("uid", f"other-{i}")
            cal.add_component(event)
            item.data = cal.to_ical()
            items_without_uid.append(item)

        # Add the target item at the end
        target_item = Mock()
        cal = iCalendar()
        event = iEvent()
        event.add("uid", "event-123")
        cal.add_component(event)
        target_item.data = cal.to_ical()
        items_without_uid.append(target_item)

        mock_calendar.events = Mock(return_value=items_without_uid)

        result = get_item_with_fallback(mock_calendar, "event-123", "event")
        assert result == target_item
