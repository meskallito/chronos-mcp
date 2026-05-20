"""
Comprehensive unit tests for chronos_mcp/tools/journals.py module
Tests all MCP journal tool functions for 100% coverage with defensive programming patterns
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from chronos_mcp.exceptions import CalendarNotFoundError, ChronosError, ValidationError
from chronos_mcp.tools.journals import (
    _managers,
    create_journal,
    delete_journal,
    list_journals,
    register_journal_tools,
    update_journal,
)


class TestJournalTools:
    """Test MCP journal tool functions with comprehensive coverage"""

    @pytest.fixture
    def mock_managers(self):
        """Mock managers for dependency injection"""
        journal_manager = Mock()
        return {"journal_manager": journal_manager}

    @pytest.fixture
    def sample_journal(self):
        """Sample journal object for testing"""
        journal = Mock()
        journal.uid = "journal-123"
        journal.summary = "Test Journal"
        journal.description = "Test journal content"
        journal.dtstart = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
        journal.related_to = ["related-1", "related-2"]
        return journal

    @pytest.fixture
    def setup_managers(self, mock_managers):
        """Setup _managers module variable"""
        original = _managers.copy()
        _managers.clear()
        _managers.update(mock_managers)
        yield
        _managers.clear()
        _managers.update(original)

    # CREATE_JOURNAL TOOL TESTS

    @pytest.mark.asyncio
    async def test_create_journal_minimal_success(self, setup_managers, sample_journal):
        """Test create_journal with minimal required parameters"""
        _managers["journal_manager"].create_journal.return_value = sample_journal

        result = await create_journal.fn(
            calendar_uid="cal-123",
            summary="Test Journal",
            description=None,
            entry_date=None,
            related_to=None,
            account=None,
        )

        assert result["success"] is True
        assert result["journal"]["uid"] == "journal-123"
        assert result["journal"]["summary"] == "Test Journal"
        assert "request_id" in result
        _managers["journal_manager"].create_journal.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_journal_full_parameters(self, setup_managers, sample_journal):
        """Test create_journal with all parameters provided"""
        _managers["journal_manager"].create_journal.return_value = sample_journal

        result = await create_journal.fn(
            calendar_uid="cal-123",
            summary="Full Test Journal",
            description="Full journal content",
            entry_date="2025-12-31T23:59:00Z",
            related_to=["related-1", "related-2"],
            account="test_account",
        )

        assert result["success"] is True
        assert result["journal"]["summary"] == "Test Journal"  # from sample_journal
        _managers["journal_manager"].create_journal.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_journal_summary_validation_error(self, setup_managers):
        """Test create_journal validation error for summary"""
        with patch(
            "chronos_mcp.tools.journals.InputValidator.validate_text_field"
        ) as mock_validate:
            mock_validate.side_effect = ValidationError("Summary too long")

            result = await create_journal.fn(
                calendar_uid="cal-123",
                summary="x" * 1000,  # Very long summary
                description=None,
                entry_date=None,
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Summary too long" in result["error"]
            assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_create_journal_description_validation_error(self, setup_managers):
        """Test create_journal validation error for description"""
        with patch(
            "chronos_mcp.tools.journals.InputValidator.validate_text_field"
        ) as mock_validate:
            # Summary passes, description fails
            mock_validate.side_effect = [
                "Valid Summary",  # First call for summary
                ValidationError("Description invalid"),  # Second call for description
            ]

            result = await create_journal.fn(
                calendar_uid="cal-123",
                summary="Valid Summary",
                description="Invalid description",
                entry_date=None,
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Description invalid" in result["error"]
            assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_create_journal_entry_date_none(self, setup_managers, sample_journal):
        """Test create_journal with entry date as None in response"""
        sample_journal.dtstart = None
        _managers["journal_manager"].create_journal.return_value = sample_journal

        result = await create_journal.fn(
            calendar_uid="cal-123",
            summary="Test Journal",
            description=None,
            entry_date=None,
            related_to=None,
            account=None,
        )

        assert result["success"] is True
        assert result["journal"]["entry_date"] is None

    @pytest.mark.asyncio
    async def test_create_journal_chronos_error(self, setup_managers):
        """Test create_journal handles ChronosError"""
        error = ChronosError("General error")
        _managers["journal_manager"].create_journal.side_effect = error

        result = await create_journal.fn(
            calendar_uid="cal-123",
            summary="Test Journal",
            description=None,
            entry_date=None,
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert result["error_code"] == "ChronosError"

    @pytest.mark.asyncio
    async def test_create_journal_unexpected_exception(self, setup_managers):
        """Test create_journal handles unexpected exceptions"""
        _managers["journal_manager"].create_journal.side_effect = RuntimeError("Unexpected error")

        result = await create_journal.fn(
            calendar_uid="cal-123",
            summary="Test Journal",
            description=None,
            entry_date=None,
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Failed to create journal" in result["error"]
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_create_journal_malformed_entry_date(self, setup_managers):
        """Test create_journal with malformed entry date triggering parse_datetime error"""
        with patch("chronos_mcp.tools.journals.parse_datetime") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid date format")

            result = await create_journal.fn(
                calendar_uid="cal-123",
                summary="Test Journal",
                description=None,
                entry_date="invalid-date",
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Failed to create journal" in result["error"]

    # LIST_JOURNALS TOOL TESTS

    @pytest.mark.asyncio
    async def test_list_journals_success(self, setup_managers, sample_journal):
        """Test list_journals successful execution"""
        _managers["journal_manager"].list_journals.return_value = [sample_journal]

        result = await list_journals.fn(calendar_uid="cal-123", account=None, limit=50)

        assert len(result["journals"]) == 1
        assert result["total"] == 1
        assert result["calendar_uid"] == "cal-123"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_list_journals_with_account_and_limit(self, setup_managers, sample_journal):
        """Test list_journals with account and limit parameters"""
        _managers["journal_manager"].list_journals.return_value = [sample_journal]

        result = await list_journals.fn(calendar_uid="cal-123", account="test_account", limit=10)

        assert len(result["journals"]) == 1
        _managers["journal_manager"].list_journals.assert_called_once_with(
            calendar_uid="cal-123", limit=10, account_alias="test_account"
        )

    @pytest.mark.asyncio
    async def test_list_journals_limit_string_conversion(self, setup_managers, sample_journal):
        """Test list_journals converts string limit to int"""
        _managers["journal_manager"].list_journals.return_value = [sample_journal]

        result = await list_journals.fn(
            calendar_uid="cal-123",
            account=None,
            limit="25",  # String that should convert to int
        )

        assert len(result["journals"]) == 1
        _managers["journal_manager"].list_journals.assert_called_once_with(
            calendar_uid="cal-123", limit=25, account_alias=None
        )

    @pytest.mark.asyncio
    async def test_list_journals_invalid_limit_string(self, setup_managers):
        """Test list_journals handles invalid limit string"""
        result = await list_journals.fn(
            calendar_uid="cal-123",
            account=None,
            limit="invalid",  # Cannot convert to int
        )

        assert result["journals"] == []
        assert result["total"] == 0
        assert "Invalid limit value" in result["error"]
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_list_journals_limit_type_error(self, setup_managers):
        """Test list_journals handles TypeError in limit conversion"""
        result = await list_journals.fn(
            calendar_uid="cal-123", account=None, limit={}  # TypeError when int({})
        )

        assert result["journals"] == []
        assert result["total"] == 0
        assert "Invalid limit value" in result["error"]

    @pytest.mark.asyncio
    async def test_list_journals_entry_date_none(self, setup_managers):
        """Test list_journals with journal having None entry date"""
        journal = Mock()
        journal.uid = "journal-123"
        journal.summary = "Test Journal"
        journal.description = "Test content"
        journal.dtstart = None  # No entry date
        journal.related_to = []

        _managers["journal_manager"].list_journals.return_value = [journal]

        result = await list_journals.fn(calendar_uid="cal-123", account=None, limit=50)

        assert result["journals"][0]["entry_date"] is None

    @pytest.mark.asyncio
    async def test_list_journals_calendar_not_found_error(self, setup_managers):
        """Test list_journals handles CalendarNotFoundError"""
        error = CalendarNotFoundError("Calendar not found")
        _managers["journal_manager"].list_journals.side_effect = error

        result = await list_journals.fn(calendar_uid="cal-123", account=None, limit=50)

        assert result["journals"] == []
        assert result["total"] == 0
        assert "error" in result
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_list_journals_chronos_error(self, setup_managers):
        """Test list_journals handles ChronosError"""
        error = ChronosError("General error")
        _managers["journal_manager"].list_journals.side_effect = error

        result = await list_journals.fn(calendar_uid="cal-123", account=None, limit=50)

        assert result["journals"] == []
        assert result["total"] == 0
        assert result["error_code"] == "ChronosError"

    @pytest.mark.asyncio
    async def test_list_journals_unexpected_exception(self, setup_managers):
        """Test list_journals handles unexpected exceptions"""
        _managers["journal_manager"].list_journals.side_effect = RuntimeError("Unexpected error")

        result = await list_journals.fn(calendar_uid="cal-123", account=None, limit=50)

        assert result["journals"] == []
        assert result["total"] == 0
        assert "Failed to list journals" in result["error"]

    # UPDATE_JOURNAL TOOL TESTS (uses @handle_tool_errors decorator)

    @pytest.mark.asyncio
    async def test_update_journal_success(self, setup_managers, sample_journal):
        """Test update_journal successful execution"""
        _managers["journal_manager"].update_journal.return_value = sample_journal

        result = await update_journal.fn(
            calendar_uid="cal-123",
            journal_uid="journal-123",
            summary="Updated Summary",
            description=None,
            entry_date=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is True
        assert result["journal"]["uid"] == "journal-123"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_update_journal_all_parameters(self, setup_managers, sample_journal):
        """Test update_journal with all parameters"""
        _managers["journal_manager"].update_journal.return_value = sample_journal

        result = await update_journal.fn(
            calendar_uid="cal-123",
            journal_uid="journal-123",
            summary="Updated Summary",
            description="Updated content",
            entry_date="2025-12-31T23:59:00Z",
            account="test_account",
            request_id=None,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_journal_summary_validation_error(self, setup_managers):
        """Test update_journal validation error for summary"""
        with patch(
            "chronos_mcp.tools.journals.InputValidator.validate_text_field"
        ) as mock_validate:
            mock_validate.side_effect = ValidationError("Summary invalid")

            result = await update_journal.fn(
                calendar_uid="cal-123",
                journal_uid="journal-123",
                summary="Invalid summary",
                description=None,
                entry_date=None,
                account=None,
                request_id=None,
            )

            assert result["success"] is False
            assert "Summary invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_update_journal_description_validation_error(self, setup_managers):
        """Test update_journal validation error for description"""
        with patch(
            "chronos_mcp.tools.journals.InputValidator.validate_text_field"
        ) as mock_validate:
            mock_validate.side_effect = ValidationError("Description invalid")

            result = await update_journal.fn(
                calendar_uid="cal-123",
                journal_uid="journal-123",
                summary=None,
                description="Invalid description",
                entry_date=None,
                account=None,
                request_id=None,
            )

            assert result["success"] is False
            assert "Description invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_update_journal_entry_date_none_in_response(self, setup_managers):
        """Test update_journal with None entry date in response"""
        sample_journal = Mock()
        sample_journal.uid = "journal-123"
        sample_journal.summary = "Test Journal"
        sample_journal.description = "Test content"
        sample_journal.dtstart = None  # No entry date
        sample_journal.related_to = []

        _managers["journal_manager"].update_journal.return_value = sample_journal

        result = await update_journal.fn(
            calendar_uid="cal-123",
            journal_uid="journal-123",
            summary="Updated",
            description=None,
            entry_date=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is True
        assert result["journal"]["entry_date"] is None

    @pytest.mark.asyncio
    async def test_update_journal_malformed_entry_date(self, setup_managers):
        """Test update_journal with malformed entry date triggering parse_datetime error"""
        with patch("chronos_mcp.tools.journals.parse_datetime") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid date format")

            result = await update_journal.fn(
                calendar_uid="cal-123",
                journal_uid="journal-123",
                summary=None,
                description=None,
                entry_date="invalid-date",
                account=None,
                request_id=None,
            )

            assert result["success"] is False

    # DELETE_JOURNAL TOOL TESTS (uses @handle_tool_errors decorator)

    @pytest.mark.asyncio
    async def test_delete_journal_success(self, setup_managers):
        """Test delete_journal successful execution"""
        _managers["journal_manager"].delete_journal.return_value = True

        result = await delete_journal.fn(
            calendar_uid="cal-123",
            journal_uid="journal-123",
            account=None,
            request_id=None,
        )

        assert result["success"] is True
        assert "deleted successfully" in result["message"]
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_delete_journal_with_account(self, setup_managers):
        """Test delete_journal with account parameter"""
        _managers["journal_manager"].delete_journal.return_value = True

        result = await delete_journal.fn(
            calendar_uid="cal-123",
            journal_uid="journal-123",
            account="test_account",
            request_id=None,
        )

        _managers["journal_manager"].delete_journal.assert_called_once_with(
            calendar_uid="cal-123",
            journal_uid="journal-123",
            account_alias="test_account",
            request_id=result["request_id"],
        )

    # REGISTER_JOURNAL_TOOLS TESTS

    def test_register_journal_tools(self, mock_managers, setup_managers):
        """Test register_journal_tools function"""
        mock_mcp = Mock()

        register_journal_tools(mock_mcp, mock_managers)

        # Verify managers were updated - strict equality now works with clean state from fixture
        assert _managers == mock_managers

        # Verify all tools were registered
        assert mock_mcp.tool.call_count == 4

        # Verify specific tools were registered
        calls = [call[0][0] for call in mock_mcp.tool.call_args_list]
        assert create_journal in calls
        assert list_journals in calls
        assert update_journal in calls
        assert delete_journal in calls

    # FUNCTION ATTRIBUTE TESTS

    def test_function_attributes_exist(self):
        """Test that .fn attributes exist for backwards compatibility"""
        assert hasattr(create_journal, "fn")
        assert hasattr(list_journals, "fn")
        assert hasattr(update_journal, "fn")
        assert hasattr(delete_journal, "fn")

        assert create_journal.fn == create_journal
        assert list_journals.fn == list_journals
        assert update_journal.fn == update_journal
        assert delete_journal.fn == delete_journal

    # EDGE CASES AND DEFENSIVE PROGRAMMING

    @pytest.mark.asyncio
    async def test_create_journal_empty_summary(self, setup_managers):
        """Test create_journal with empty summary"""
        with patch(
            "chronos_mcp.tools.journals.InputValidator.validate_text_field"
        ) as mock_validate:
            mock_validate.side_effect = ValidationError("Summary is required")

            result = await create_journal.fn(
                calendar_uid="cal-123",
                summary="",
                description=None,
                entry_date=None,
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Summary is required" in result["error"]

    @pytest.mark.asyncio
    async def test_list_journals_limit_none(self, setup_managers, sample_journal):
        """Test list_journals with limit as None"""
        _managers["journal_manager"].list_journals.return_value = [sample_journal]

        result = await list_journals.fn(calendar_uid="cal-123", account=None, limit=None)

        assert len(result["journals"]) == 1
        _managers["journal_manager"].list_journals.assert_called_once_with(
            calendar_uid="cal-123", limit=None, account_alias=None
        )

    @pytest.mark.asyncio
    async def test_managers_not_initialized(self):
        """Test behavior when _managers is not properly initialized"""
        # Clear managers to simulate uninitialized state
        original = _managers.copy()
        _managers.clear()

        try:
            result = await create_journal.fn(
                calendar_uid="cal-123",
                summary="Test Journal",
                description=None,
                entry_date=None,
                related_to=None,
                account=None,
            )
            # Should get an error response, not an exception
            assert result["success"] is False
            assert "Failed to create journal" in result["error"]
        finally:
            _managers.update(original)

    @pytest.mark.asyncio
    async def test_create_journal_empty_description_not_validated(
        self, setup_managers, sample_journal
    ):
        """Test create_journal with empty description (should not be validated)"""
        _managers["journal_manager"].create_journal.return_value = sample_journal

        result = await create_journal.fn(
            calendar_uid="cal-123",
            summary="Test Journal",
            description="",  # Empty description should be ignored
            entry_date=None,
            related_to=None,
            account=None,
        )

        # Empty description should not trigger validation
        assert result["success"] is True
