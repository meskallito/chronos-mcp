"""
Comprehensive unit tests for chronos_mcp/tools/tasks.py module
Tests all MCP tool functions for 100% coverage with defensive programming patterns
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from chronos_mcp.exceptions import (
    CalendarNotFoundError,
    ChronosError,
    EventCreationError,
    ValidationError,
)
from chronos_mcp.models import TaskStatus
from chronos_mcp.tools.tasks import (
    _managers,
    create_task,
    delete_task,
    list_tasks,
    register_task_tools,
    update_task,
)


class TestTaskToolsComprehensive:
    """Test MCP task tool functions with comprehensive coverage"""

    @pytest.fixture
    def mock_managers(self):
        """Mock managers for dependency injection"""
        task_manager = Mock()
        return {"task_manager": task_manager}

    @pytest.fixture
    def sample_task(self):
        """Sample task object for testing"""
        task = Mock()
        task.uid = "task-123"
        task.summary = "Test Task"
        task.description = "Test description"
        task.due = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
        task.priority = 5
        task.status = TaskStatus.NEEDS_ACTION
        task.percent_complete = 0
        task.related_to = ["related-1", "related-2"]
        return task

    @pytest.fixture
    def setup_managers(self, mock_managers):
        """Setup _managers module variable"""
        original = _managers.copy()
        _managers.clear()
        _managers.update(mock_managers)
        yield
        _managers.clear()
        _managers.update(original)

    # CREATE_TASK TOOL TESTS

    @pytest.mark.asyncio
    async def test_create_task_minimal_success(self, setup_managers, sample_task):
        """Test create_task with minimal required parameters"""
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is True
        assert result["task"]["uid"] == "task-123"
        assert result["task"]["summary"] == "Test Task"
        assert "request_id" in result
        _managers["task_manager"].create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_full_parameters(self, setup_managers, sample_task):
        """Test create_task with all parameters provided"""
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Full Test Task",
            description="Full description",
            due="2025-12-31T23:59:00Z",
            priority=3,
            status="IN-PROCESS",
            related_to=["related-1", "related-2"],
            account="test_account",
        )

        assert result["success"] is True
        assert result["task"]["status"] == "NEEDS-ACTION"  # from sample_task
        _managers["task_manager"].create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_bare_date_autodetects_all_day(self, setup_managers, sample_task):
        """A bare YYYY-MM-DD due string auto-detects all_day=True for the manager."""
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Date-only Task",
            description=None,
            due="2026-06-21",
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            all_day=False,
            account=None,
        )

        assert result["success"] is True
        _, kwargs = _managers["task_manager"].create_task.call_args
        assert kwargs["all_day"] is True
        # Still threaded as a datetime on the same calendar day
        assert kwargs["due"].date() == datetime(2026, 6, 21).date()

    @pytest.mark.asyncio
    async def test_create_task_explicit_all_day_with_datetime(self, setup_managers, sample_task):
        """Explicit all_day=True with a datetime input threads all_day=True."""
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Date-only Task",
            description=None,
            due="2026-06-21T15:00:00",
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            all_day=True,
            account=None,
        )

        assert result["success"] is True
        _, kwargs = _managers["task_manager"].create_task.call_args
        assert kwargs["all_day"] is True

    @pytest.mark.asyncio
    async def test_create_task_midnight_datetime_stays_timed(self, setup_managers, sample_task):
        """A ...T00:00:00 input WITHOUT all_day stays a timed task (heuristic boundary)."""
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Midnight Task",
            description=None,
            due="2026-06-21T00:00:00",
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            all_day=False,
            account=None,
        )

        assert result["success"] is True
        _, kwargs = _managers["task_manager"].create_task.call_args
        assert kwargs["all_day"] is False

    @pytest.mark.asyncio
    async def test_create_task_priority_string_conversion(self, setup_managers, sample_task):
        """Test create_task converts string priority to int"""
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority="5",  # String that should convert to int
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is True
        _managers["task_manager"].create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_invalid_priority_string(self, setup_managers):
        """Test create_task handles invalid priority string"""
        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority="invalid",  # Cannot convert to int
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Invalid priority value" in result["error"]
        assert result["error_code"] == "VALIDATION_ERROR"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_create_task_priority_type_error(self, setup_managers):
        """Test create_task handles TypeError in priority conversion"""
        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority={},  # TypeError when int({})
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Invalid priority value" in result["error"]

    @pytest.mark.asyncio
    async def test_create_task_summary_validation_error(self, setup_managers):
        """Test create_task validation error for summary"""
        with patch("chronos_mcp.tools.tasks.InputValidator.validate_text_field") as mock_validate:
            mock_validate.side_effect = ValidationError("Summary too long")

            result = await create_task.fn(
                calendar_uid="cal-123",
                summary="x" * 1000,  # Very long summary
                description=None,
                due=None,
                priority=None,
                status="NEEDS-ACTION",
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Summary too long" in result["error"]
            assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_create_task_description_validation_error(self, setup_managers):
        """Test create_task validation error for description"""
        with patch("chronos_mcp.tools.tasks.InputValidator.validate_text_field") as mock_validate:
            # Summary passes, description fails
            mock_validate.side_effect = [
                "Valid Summary",  # First call for summary
                ValidationError("Description invalid"),  # Second call for description
            ]

            result = await create_task.fn(
                calendar_uid="cal-123",
                summary="Valid Summary",
                description="Invalid description",
                due=None,
                priority=None,
                status="NEEDS-ACTION",
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Description invalid" in result["error"]
            assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_create_task_invalid_priority_range(self, setup_managers):
        """Test create_task validates priority range"""
        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=10,  # Outside 1-9 range
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Priority must be between 1 and 9" in result["error"]
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_create_task_invalid_status(self, setup_managers):
        """Test create_task validates status enum"""
        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="INVALID-STATUS",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Invalid status" in result["error"]
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_create_task_due_date_none(self, setup_managers, sample_task):
        """Test create_task with due date as None in response"""
        sample_task.due = None
        _managers["task_manager"].create_task.return_value = sample_task

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is True
        assert result["task"]["due"] is None

    @pytest.mark.asyncio
    async def test_create_task_calendar_not_found_error(self, setup_managers):
        """Test create_task handles CalendarNotFoundError"""
        error = CalendarNotFoundError("Calendar not found")
        _managers["task_manager"].create_task.side_effect = error

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_create_task_event_creation_error(self, setup_managers):
        """Test create_task handles EventCreationError"""
        error = EventCreationError("Creation failed")
        _managers["task_manager"].create_task.side_effect = error

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert result["error_code"] == "EventCreationError"

    @pytest.mark.asyncio
    async def test_create_task_chronos_error(self, setup_managers):
        """Test create_task handles general ChronosError"""
        error = ChronosError("General error")
        _managers["task_manager"].create_task.side_effect = error

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert result["error_code"] == "ChronosError"

    @pytest.mark.asyncio
    async def test_create_task_unexpected_exception(self, setup_managers):
        """Test create_task handles unexpected exceptions"""
        _managers["task_manager"].create_task.side_effect = RuntimeError("Unexpected error")

        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=None,
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Failed to create task" in result["error"]
        assert "request_id" in result

    # LIST_TASKS TOOL TESTS

    @pytest.mark.asyncio
    async def test_list_tasks_success(self, setup_managers, sample_task):
        """Test list_tasks successful execution"""
        _managers["task_manager"].list_tasks.return_value = [sample_task]

        result = await list_tasks.fn(calendar_uid="cal-123", status_filter=None, account=None)

        assert len(result["tasks"]) == 1
        assert result["total"] == 1
        assert result["calendar_uid"] == "cal-123"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_list_tasks_with_status_filter(self, setup_managers, sample_task):
        """Test list_tasks with status filter"""
        _managers["task_manager"].list_tasks.return_value = [sample_task]

        result = await list_tasks.fn(
            calendar_uid="cal-123", status_filter="NEEDS-ACTION", account=None
        )

        assert len(result["tasks"]) == 1
        _managers["task_manager"].list_tasks.assert_called_once_with(
            calendar_uid="cal-123",
            status_filter=TaskStatus.NEEDS_ACTION,
            account_alias=None,
        )

    @pytest.mark.asyncio
    async def test_list_tasks_invalid_status_filter(self, setup_managers):
        """Test list_tasks with invalid status filter"""
        result = await list_tasks.fn(
            calendar_uid="cal-123", status_filter="INVALID-STATUS", account=None
        )

        assert result["success"] is False
        assert "Invalid status filter" in result["error"]
        assert result["error_code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_list_tasks_task_due_none(self, setup_managers):
        """Test list_tasks with task having None due date"""
        task = Mock()
        task.uid = "task-123"
        task.summary = "Test Task"
        task.description = "Test description"
        task.due = None  # No due date
        task.priority = 5
        task.status = TaskStatus.NEEDS_ACTION
        task.percent_complete = 0
        task.related_to = []

        _managers["task_manager"].list_tasks.return_value = [task]

        result = await list_tasks.fn(calendar_uid="cal-123", status_filter=None, account=None)

        assert result["tasks"][0]["due"] is None

    @pytest.mark.asyncio
    async def test_list_tasks_calendar_not_found_error(self, setup_managers):
        """Test list_tasks handles CalendarNotFoundError"""
        error = CalendarNotFoundError("Calendar not found")
        _managers["task_manager"].list_tasks.side_effect = error

        result = await list_tasks.fn(calendar_uid="cal-123", status_filter=None, account=None)

        assert result["tasks"] == []
        assert result["total"] == 0
        assert "error" in result
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_list_tasks_chronos_error(self, setup_managers):
        """Test list_tasks handles ChronosError"""
        error = ChronosError("General error")
        _managers["task_manager"].list_tasks.side_effect = error

        result = await list_tasks.fn(calendar_uid="cal-123", status_filter=None, account=None)

        assert result["tasks"] == []
        assert result["total"] == 0
        assert result["error_code"] == "ChronosError"

    @pytest.mark.asyncio
    async def test_list_tasks_unexpected_exception(self, setup_managers):
        """Test list_tasks handles unexpected exceptions"""
        _managers["task_manager"].list_tasks.side_effect = RuntimeError("Unexpected error")

        result = await list_tasks.fn(calendar_uid="cal-123", status_filter=None, account=None)

        assert result["tasks"] == []
        assert result["total"] == 0
        assert "Failed to list tasks" in result["error"]

    # UPDATE_TASK TOOL TESTS (uses @handle_tool_errors decorator)

    @pytest.mark.asyncio
    async def test_update_task_success(self, setup_managers, sample_task):
        """Test update_task successful execution"""
        _managers["task_manager"].update_task.return_value = sample_task

        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary="Updated Summary",
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is True
        assert result["task"]["uid"] == "task-123"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_update_task_priority_string_conversion(self, setup_managers, sample_task):
        """Test update_task converts string priority to int"""
        _managers["task_manager"].update_task.return_value = sample_task

        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority="7",
            status=None,
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_task_invalid_priority_string(self, setup_managers):
        """Test update_task handles invalid priority string"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority="invalid",
            status=None,
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Invalid priority value" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_percent_complete_string_conversion(
        self, setup_managers, sample_task
    ):
        """Test update_task converts string percent_complete to int"""
        _managers["task_manager"].update_task.return_value = sample_task

        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete="50",
            account=None,
            request_id=None,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_task_invalid_percent_complete_string(self, setup_managers):
        """Test update_task handles invalid percent_complete string"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete="invalid",
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Invalid percent_complete value" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_priority_range_validation(self, setup_managers):
        """Test update_task validates priority range"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=15,  # Outside 1-9 range
            status=None,
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Priority must be between 1 and 9" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_invalid_status(self, setup_managers):
        """Test update_task validates status enum"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=None,
            status="INVALID-STATUS",
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Invalid status" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_percent_complete_range_validation(self, setup_managers):
        """Test update_task validates percent_complete range"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete=150,  # Outside 0-100 range
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Percent complete must be between 0 and 100" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_due_none_in_response(self, setup_managers):
        """Test update_task with None due date in response"""
        sample_task = Mock()
        sample_task.uid = "task-123"
        sample_task.summary = "Test Task"
        sample_task.description = "Test description"
        sample_task.due = None  # No due date
        sample_task.priority = 5
        sample_task.status = TaskStatus.NEEDS_ACTION
        sample_task.percent_complete = 0
        sample_task.related_to = []

        _managers["task_manager"].update_task.return_value = sample_task

        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary="Updated",
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is True
        assert result["task"]["due"] is None

    # DELETE_TASK TOOL TESTS (uses @handle_tool_errors decorator)

    @pytest.mark.asyncio
    async def test_delete_task_success(self, setup_managers):
        """Test delete_task successful execution"""
        _managers["task_manager"].delete_task.return_value = True

        result = await delete_task.fn(
            calendar_uid="cal-123", task_uid="task-123", account=None, request_id=None
        )

        assert result["success"] is True
        assert "deleted successfully" in result["message"]
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_delete_task_with_account(self, setup_managers):
        """Test delete_task with account parameter"""
        _managers["task_manager"].delete_task.return_value = True

        result = await delete_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            account="test_account",
            request_id=None,
        )

        _managers["task_manager"].delete_task.assert_called_once_with(
            calendar_uid="cal-123",
            task_uid="task-123",
            account_alias="test_account",
            request_id=result["request_id"],
        )

    # REGISTER_TASK_TOOLS TESTS

    def test_register_task_tools(self, mock_managers, setup_managers):
        """Test register_task_tools function"""
        mock_mcp = Mock()

        register_task_tools(mock_mcp, mock_managers)

        # Verify managers were updated - strict equality now works with clean state from fixture
        assert _managers == mock_managers

        # Verify all tools were registered
        assert mock_mcp.tool.call_count == 4

        # Verify specific tools were registered
        calls = [call[0][0] for call in mock_mcp.tool.call_args_list]
        assert create_task in calls
        assert list_tasks in calls
        assert update_task in calls
        assert delete_task in calls

    # FUNCTION ATTRIBUTE TESTS

    def test_function_attributes_exist(self):
        """Test that .fn attributes exist for backwards compatibility"""
        assert hasattr(create_task, "fn")
        assert hasattr(list_tasks, "fn")
        assert hasattr(update_task, "fn")
        assert hasattr(delete_task, "fn")

        assert create_task.fn == create_task
        assert list_tasks.fn == list_tasks
        assert update_task.fn == update_task
        assert delete_task.fn == delete_task

    # EDGE CASES AND DEFENSIVE PROGRAMMING

    @pytest.mark.asyncio
    async def test_create_task_zero_priority(self, setup_managers):
        """Test create_task with priority 0 (invalid)"""
        result = await create_task.fn(
            calendar_uid="cal-123",
            summary="Test Task",
            description=None,
            due=None,
            priority=0,  # Below valid range
            status="NEEDS-ACTION",
            related_to=None,
            account=None,
        )

        assert result["success"] is False
        assert "Priority must be between 1 and 9" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_negative_percent_complete(self, setup_managers):
        """Test update_task with negative percent_complete"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete=-10,  # Below valid range
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Percent complete must be between 0 and 100" in result["error"]

    @pytest.mark.asyncio
    async def test_create_task_malformed_due_date(self, setup_managers):
        """Test create_task with malformed due date triggering parse_datetime error"""
        with patch("chronos_mcp.tools.tasks.parse_datetime") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid date format")

            result = await create_task.fn(
                calendar_uid="cal-123",
                summary="Test Task",
                description=None,
                due="invalid-date",
                priority=None,
                status="NEEDS-ACTION",
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Failed to create task" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_malformed_due_date(self, setup_managers):
        """Test update_task with malformed due date triggering parse_datetime error"""
        with patch("chronos_mcp.tools.tasks.parse_datetime") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid date format")

            result = await update_task.fn(
                calendar_uid="cal-123",
                task_uid="task-123",
                summary=None,
                description=None,
                due="invalid-date",
                priority=None,
                status=None,
                percent_complete=None,
                account=None,
                request_id=None,
            )

            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_task_empty_summary(self, setup_managers):
        """Test create_task with empty summary"""
        with patch("chronos_mcp.tools.tasks.InputValidator.validate_text_field") as mock_validate:
            mock_validate.side_effect = ValidationError("Summary is required")

            result = await create_task.fn(
                calendar_uid="cal-123",
                summary="",
                description=None,
                due=None,
                priority=None,
                status="NEEDS-ACTION",
                related_to=None,
                account=None,
            )

            assert result["success"] is False
            assert "Summary is required" in result["error"]

    @pytest.mark.asyncio
    async def test_list_tasks_with_account(self, setup_managers, sample_task):
        """Test list_tasks with account parameter"""
        _managers["task_manager"].list_tasks.return_value = [sample_task]

        result = await list_tasks.fn(
            calendar_uid="cal-123", status_filter=None, account="test_account"
        )

        _managers["task_manager"].list_tasks.assert_called_once_with(
            calendar_uid="cal-123", status_filter=None, account_alias="test_account"
        )
        assert result["total"] == 1
        assert len(result["tasks"]) == 1

    @pytest.mark.asyncio
    async def test_update_task_all_parameters(self, setup_managers, sample_task):
        """Test update_task with all parameters"""
        _managers["task_manager"].update_task.return_value = sample_task

        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary="Updated Summary",
            description="Updated description",
            due="2025-12-31T23:59:00Z",
            priority=3,
            status="IN-PROCESS",
            percent_complete=75,
            account="test_account",
            request_id=None,
        )

        assert result["success"] is True
        assert result["task"]["uid"] == "task-123"

    @pytest.mark.asyncio
    async def test_update_task_summary_validation_error(self, setup_managers):
        """Test update_task validation error for summary"""
        with patch("chronos_mcp.tools.tasks.InputValidator.validate_text_field") as mock_validate:
            mock_validate.side_effect = ValidationError("Summary invalid")

            result = await update_task.fn(
                calendar_uid="cal-123",
                task_uid="task-123",
                summary="Invalid summary",
                description=None,
                due=None,
                priority=None,
                status=None,
                percent_complete=None,
                account=None,
                request_id=None,
            )

            assert result["success"] is False
            assert "Summary invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_description_validation_error(self, setup_managers):
        """Test update_task validation error for description"""
        with patch("chronos_mcp.tools.tasks.InputValidator.validate_text_field") as mock_validate:
            mock_validate.side_effect = ValidationError("Description invalid")

            result = await update_task.fn(
                calendar_uid="cal-123",
                task_uid="task-123",
                summary=None,
                description="Invalid description",
                due=None,
                priority=None,
                status=None,
                percent_complete=None,
                account=None,
                request_id=None,
            )

            assert result["success"] is False
            assert "Description invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_priority_type_error(self, setup_managers):
        """Test update_task handles TypeError in priority conversion"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority={},  # TypeError when int({})
            status=None,
            percent_complete=None,
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Invalid priority value" in result["error"]

    @pytest.mark.asyncio
    async def test_update_task_percent_complete_type_error(self, setup_managers):
        """Test update_task handles TypeError in percent_complete conversion"""
        result = await update_task.fn(
            calendar_uid="cal-123",
            task_uid="task-123",
            summary=None,
            description=None,
            due=None,
            priority=None,
            status=None,
            percent_complete=[],  # TypeError when int([])
            account=None,
            request_id=None,
        )

        assert result["success"] is False
        assert "Invalid percent_complete value" in result["error"]

    @pytest.mark.asyncio
    async def test_managers_not_initialized(self):
        """Test behavior when _managers is not properly initialized"""
        # Clear managers to simulate uninitialized state
        original = _managers.copy()
        _managers.clear()

        try:
            result = await create_task.fn(
                calendar_uid="cal-123",
                summary="Test Task",
                description=None,
                due=None,
                priority=None,
                status="NEEDS-ACTION",
                related_to=None,
                account=None,
            )
            # Should get an error response, not an exception
            assert result["success"] is False
            assert "Failed to create task" in result["error"]
        finally:
            _managers.update(original)
