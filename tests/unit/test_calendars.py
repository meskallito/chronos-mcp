"""
Unit tests for calendar management
"""

from unittest.mock import Mock

import pytest

from chronos_mcp.accounts import AccountManager
from chronos_mcp.calendars import CalendarManager


class TestCalendarManager:
    """Test calendar management functionality"""

    @pytest.fixture
    def mock_account_manager(self):
        """Mock AccountManager"""
        mock = Mock(spec=AccountManager)
        mock.config = Mock()
        mock.config.config = Mock()
        mock.config.config.default_account = "default"
        return mock

    @pytest.fixture
    def mock_principal(self):
        """Mock CalDAV principal"""
        principal = Mock()
        return principal

    @pytest.fixture
    def mock_calendar(self):
        """Mock CalDAV calendar"""
        cal = Mock()
        cal.url = "http://caldav.example.com/calendars/user/test-calendar/"
        cal.name = "Test Calendar"
        return cal

    def test_init(self, mock_account_manager):
        """Test CalendarManager initialization"""
        mgr = CalendarManager(mock_account_manager)
        assert mgr.accounts == mock_account_manager

    def test_list_calendars_no_principal(self, mock_account_manager):
        """Test listing calendars when no principal found"""
        mock_account_manager.get_principal.return_value = None

        mgr = CalendarManager(mock_account_manager)

        # Should raise AccountNotFoundError when no principal
        from chronos_mcp.exceptions import AccountNotFoundError

        with pytest.raises(AccountNotFoundError) as exc_info:
            mgr.list_calendars("test_account")

        assert "test_account" in str(exc_info.value)

    def test_list_calendars_success(self, mock_account_manager, mock_principal, mock_calendar):
        """Test successful calendar listing"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_calendar2 = Mock()
        mock_calendar2.url = "http://caldav.example.com/calendars/user/personal"
        mock_calendar2.name = "Personal"

        mock_principal.calendars.return_value = [mock_calendar, mock_calendar2]

        mgr = CalendarManager(mock_account_manager)
        result = mgr.list_calendars("test_account")

        assert len(result) == 2
        assert result[0].uid == "test-calendar"
        assert result[0].name == "Test Calendar"
        assert result[0].account_alias == "test_account"
        assert result[1].uid == "personal"
        assert result[1].name == "Personal"

    def test_list_calendars_with_default_account(
        self, mock_account_manager, mock_principal, mock_calendar
    ):
        """Test listing calendars with default account"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.calendars.return_value = [mock_calendar]

        mgr = CalendarManager(mock_account_manager)
        result = mgr.list_calendars()  # No account specified

        assert len(result) == 1
        assert result[0].account_alias == "default"

    def test_list_calendars_exception(self, mock_account_manager, mock_principal):
        """Test calendar listing with exception"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.calendars.side_effect = Exception("CalDAV error")

        mgr = CalendarManager(mock_account_manager)
        result = mgr.list_calendars("test_account")

        assert result == []

    def test_create_calendar_no_principal(self, mock_account_manager):
        """Test creating calendar when no principal found"""
        mock_account_manager.get_principal.return_value = None

        mgr = CalendarManager(mock_account_manager)

        # Should raise AccountNotFoundError
        from chronos_mcp.exceptions import AccountNotFoundError

        with pytest.raises(AccountNotFoundError) as exc_info:
            mgr.create_calendar("New Calendar", account_alias="test_account")

        assert "test_account" in str(exc_info.value)
        mock_account_manager.get_principal.assert_called_once_with("test_account")

    def test_create_calendar_success(self, mock_account_manager, mock_principal):
        """Test successful calendar creation"""
        mock_account_manager.get_principal.return_value = mock_principal

        # Mock the created calendar
        created_cal = Mock()
        created_cal.url = "http://caldav.example.com/calendars/user/new_calendar/"
        mock_principal.make_calendar.return_value = created_cal

        mgr = CalendarManager(mock_account_manager)
        result = mgr.create_calendar(
            name="New Calendar",
            description="Test Description",
            color="#FF0000",
            account_alias="test_account",
        )

        assert result is not None
        assert result.uid == "new_calendar"
        assert result.name == "New Calendar"
        assert result.description == "Test Description"
        assert result.color == "#FF0000"
        assert result.account_alias == "test_account"
        assert result.read_only is False

        mock_principal.make_calendar.assert_called_once_with(
            name="New Calendar", cal_id="new_calendar"
        )

    def test_create_calendar_with_default_account(self, mock_account_manager, mock_principal):
        """Test creating calendar with default account"""
        mock_account_manager.get_principal.return_value = mock_principal
        created_cal = Mock()
        created_cal.url = "http://caldav.example.com/calendars/user/test_cal/"
        mock_principal.make_calendar.return_value = created_cal

        mgr = CalendarManager(mock_account_manager)
        result = mgr.create_calendar("Test Cal")  # No account specified

        assert result is not None
        assert result.account_alias == "default"

    def test_create_calendar_exception(self, mock_account_manager, mock_principal):
        """Test calendar creation with exception"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.make_calendar.side_effect = Exception("CalDAV error")

        mgr = CalendarManager(mock_account_manager)

        # Should raise CalendarCreationError
        from chronos_mcp.exceptions import CalendarCreationError

        with pytest.raises(CalendarCreationError) as exc_info:
            mgr.create_calendar("New Calendar")

        assert "CalDAV error" in str(exc_info.value)

    def test_delete_calendar_no_principal(self, mock_account_manager):
        """Test deleting calendar when no principal found"""
        mock_account_manager.get_principal.return_value = None

        mgr = CalendarManager(mock_account_manager)

        # Should raise AccountNotFoundError
        from chronos_mcp.exceptions import AccountNotFoundError

        with pytest.raises(AccountNotFoundError) as exc_info:
            mgr.delete_calendar("cal-123", "test_account")

        assert "test_account" in str(exc_info.value)
        mock_account_manager.get_principal.assert_called_once_with("test_account")

    def test_delete_calendar_success(self, mock_account_manager, mock_principal, mock_calendar):
        """Test successful calendar deletion"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.calendars.return_value = [mock_calendar]

        mgr = CalendarManager(mock_account_manager)
        result = mgr.delete_calendar("test-calendar", "test_account")

        assert result is True
        mock_calendar.delete.assert_called_once()

    def test_delete_calendar_not_found(self, mock_account_manager, mock_principal):
        """Test deleting non-existent calendar"""
        mock_account_manager.get_principal.return_value = mock_principal

        # Mock calendar with different UID
        other_cal = Mock()
        other_cal.url = "http://caldav.example.com/calendars/user/other-cal/"
        mock_principal.calendars.return_value = [other_cal]

        mgr = CalendarManager(mock_account_manager)

        # Should raise CalendarNotFoundError
        from chronos_mcp.exceptions import CalendarNotFoundError

        with pytest.raises(CalendarNotFoundError) as exc_info:
            mgr.delete_calendar("test-calendar", "test_account")

        assert "test-calendar" in str(exc_info.value)
        other_cal.delete.assert_not_called()

    def test_delete_calendar_exception(self, mock_account_manager, mock_principal, mock_calendar):
        """Test calendar deletion with exception"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.calendars.return_value = [mock_calendar]
        mock_calendar.delete.side_effect = Exception("CalDAV error")

        mgr = CalendarManager(mock_account_manager)

        # Should raise CalendarDeletionError
        from chronos_mcp.exceptions import CalendarDeletionError

        with pytest.raises(CalendarDeletionError) as exc_info:
            mgr.delete_calendar("test-calendar", "test_account")

        assert "CalDAV error" in str(exc_info.value)

    def test_get_calendar_no_principal(self, mock_account_manager):
        """Test getting calendar when no principal found"""
        mock_account_manager.get_principal.return_value = None

        mgr = CalendarManager(mock_account_manager)
        result = mgr.get_calendar("cal-123", "test_account")

        assert result is None
        mock_account_manager.get_principal.assert_called_once_with("test_account")

    def test_get_calendar_success(self, mock_account_manager, mock_principal, mock_calendar):
        """Test successful calendar retrieval"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.calendars.return_value = [mock_calendar]

        mgr = CalendarManager(mock_account_manager)
        result = mgr.get_calendar("test-calendar", "test_account")

        assert result == mock_calendar

    def test_get_calendar_not_found(self, mock_account_manager, mock_principal):
        """Test getting non-existent calendar"""
        mock_account_manager.get_principal.return_value = mock_principal

        # Mock calendar with different UID
        other_cal = Mock()
        other_cal.url = "http://caldav.example.com/calendars/user/other-cal/"
        mock_principal.calendars.return_value = [other_cal]

        mgr = CalendarManager(mock_account_manager)
        result = mgr.get_calendar("test-calendar", "test_account")

        assert result is None

    def test_get_calendar_exception(self, mock_account_manager, mock_principal):
        """Test getting calendar with exception"""
        mock_account_manager.get_principal.return_value = mock_principal
        mock_principal.calendars.side_effect = Exception("CalDAV error")

        mgr = CalendarManager(mock_account_manager)
        result = mgr.get_calendar("test-calendar", "test_account")

        assert result is None
