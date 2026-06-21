"""
Task management tools for Chronos MCP
"""

import uuid
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from ..exceptions import (
    CalendarNotFoundError,
    ChronosError,
    ErrorSanitizer,
    EventCreationError,
    ValidationError,
)
from ..logging_config import setup_logging
from ..models import Task, TaskStatus
from ..utils import _is_date_only, parse_datetime
from ..validation import InputValidator
from .base import create_success_response, handle_tool_errors

logger = setup_logging()

# Module-level managers dictionary for dependency injection
_managers: Dict[str, Any] = {}


def _render_due(task: Task) -> Optional[str]:
    """Render a task's DUE for the tool response.

    A date-only (all-day) task renders as a plain ``YYYY-MM-DD`` so the agent
    doesn't see a phantom ``T00:00:00`` time; a timed task keeps its full
    datetime isoformat.
    """
    if task.due is None:
        return None
    if task.all_day:
        return task.due.date().isoformat()
    return task.due.isoformat()


# Task tool functions - defined as standalone functions for importability
async def create_task(
    calendar_uid: str = Field(..., description="Calendar UID"),
    summary: str = Field(..., description="Task title/summary"),
    description: Optional[str] = Field(None, description="Task description"),
    due: Optional[str] = Field(None, description="Task due date (ISO format)"),
    priority: Optional[Union[int, str]] = Field(
        None, description="Task priority (1-9, 1 is highest)"
    ),
    status: str = Field(
        "NEEDS-ACTION",
        description="Task status (NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED)",
    ),
    related_to: Optional[List[str]] = Field(None, description="List of related component UIDs"),
    all_day: bool = Field(
        False,
        description=(
            "Create a date-only (all-day) task: the due date is stored as "
            "DUE;VALUE=DATE (no time, no timezone shift). A bare YYYY-MM-DD due "
            "string is auto-detected as all-day."
        ),
    ),
    recurrence_rule: Optional[str] = Field(
        None,
        description=(
            "RFC 5545 RRULE for a recurring task (e.g. "
            "'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=20'). A COUNT or UNTIL "
            "terminator is REQUIRED (unbounded rules are rejected). When set, a "
            "DTSTART anchor is added (matching the due date/time, or today in "
            "the default zone)."
        ),
    ),
    account: Optional[str] = Field(None, description="Account alias"),
) -> Dict[str, Any]:
    """Create a new task"""
    request_id = str(uuid.uuid4())

    # Handle type conversion for parameters that might come as strings from MCP
    if priority is not None:
        try:
            priority = int(priority)
        except (ValueError, TypeError):
            return {
                "success": False,
                "error": f"Invalid priority value: {priority}. Must be an integer between 1 and 9",
                "error_code": "VALIDATION_ERROR",
                "request_id": request_id,
            }

    try:
        # Validate and sanitize text inputs
        try:
            summary = InputValidator.validate_text_field(summary, "summary", required=True)
            if description:
                description = InputValidator.validate_text_field(description, "description")
        except ValidationError as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": "VALIDATION_ERROR",
                "request_id": request_id,
            }

        # Parse due date if provided. Effective date-only = explicit all_day
        # flag OR a bare YYYY-MM-DD due string (auto-detect). parse_datetime
        # always returns a datetime, so the date-only decision is made here in
        # the tool layer and threaded to the manager as all_day.
        due_dt = None
        effective_all_day = all_day
        if due:
            if _is_date_only(due):
                effective_all_day = True
            due_dt = parse_datetime(due)

        # Validate priority
        if priority is not None and not (1 <= priority <= 9):
            return {
                "success": False,
                "error": "Priority must be between 1 and 9",
                "error_code": "VALIDATION_ERROR",
                "request_id": request_id,
            }

        # Parse status
        try:
            task_status = TaskStatus(status)
        except ValueError:
            return {
                "success": False,
                "error": (
                    f"Invalid status: {status}. "
                    "Must be one of: NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED"
                ),
                "error_code": "VALIDATION_ERROR",
                "request_id": request_id,
            }

        task = _managers["task_manager"].create_task(
            calendar_uid=calendar_uid,
            summary=summary,
            description=description,
            due=due_dt,
            priority=priority,
            status=task_status,
            related_to=related_to,
            all_day=effective_all_day,
            recurrence_rule=recurrence_rule,
            account_alias=account,
            request_id=request_id,
        )

        return {
            "success": True,
            "task": {
                "uid": task.uid,
                "summary": task.summary,
                "description": task.description,
                "due": _render_due(task),
                "all_day": task.all_day,
                "priority": task.priority,
                "status": task.status.value,
                "percent_complete": task.percent_complete,
                "related_to": task.related_to,
                "recurrence_rule": task.recurrence_rule,
            },
            "request_id": request_id,
        }

    except (CalendarNotFoundError, EventCreationError) as e:
        e.request_id = request_id
        logger.error(f"Task creation error: {e}")

        return {
            "success": False,
            "error": ErrorSanitizer.get_user_friendly_message(e),
            "error_code": e.error_code,
            "request_id": request_id,
        }

    except ChronosError as e:
        e.request_id = request_id
        logger.error(f"Create task failed: {e}")

        return {
            "success": False,
            "error": ErrorSanitizer.get_user_friendly_message(e),
            "error_code": e.error_code,
            "request_id": request_id,
        }

    except Exception as e:
        chronos_error = ChronosError(
            message=f"Failed to create task: {str(e)}",
            details={
                "tool": "create_task",
                "summary": summary,
                "calendar_uid": calendar_uid,
                "original_error": str(e),
                "original_type": type(e).__name__,
            },
            request_id=request_id,
        )
        logger.error(f"Unexpected error in create_task: {chronos_error}")

        return {
            "success": False,
            "error": ErrorSanitizer.get_user_friendly_message(chronos_error),
            "error_code": chronos_error.error_code,
            "request_id": request_id,
        }


async def list_tasks(
    calendar_uid: str = Field(..., description="Calendar UID"),
    status_filter: Optional[str] = Field(
        None,
        description="Filter by status (NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED)",
    ),
    account: Optional[str] = Field(None, description="Account alias"),
) -> Dict[str, Any]:
    """List tasks in a calendar"""
    request_id = str(uuid.uuid4())

    try:
        # Parse status filter if provided
        status_enum = None
        if status_filter:
            try:
                status_enum = TaskStatus(status_filter)
            except ValueError:
                return {
                    "success": False,
                    "error": (
                        f"Invalid status filter: {status_filter}. "
                        "Must be one of: NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED"
                    ),
                    "error_code": "VALIDATION_ERROR",
                    "request_id": request_id,
                }

        tasks = _managers["task_manager"].list_tasks(
            calendar_uid=calendar_uid,
            status_filter=status_enum,
            account_alias=account,
        )

        return {
            "tasks": [
                {
                    "uid": task.uid,
                    "summary": task.summary,
                    "description": task.description,
                    "due": _render_due(task),
                    "all_day": task.all_day,
                    "priority": task.priority,
                    "status": task.status.value,
                    "percent_complete": task.percent_complete,
                    "related_to": task.related_to,
                    "recurrence_rule": task.recurrence_rule,
                }
                for task in tasks
            ],
            "total": len(tasks),
            "calendar_uid": calendar_uid,
            "request_id": request_id,
        }

    except CalendarNotFoundError as e:
        e.request_id = request_id
        logger.error(f"Calendar not found for task listing: {e}")

        return {
            "tasks": [],
            "total": 0,
            "error": ErrorSanitizer.get_user_friendly_message(e),
            "error_code": e.error_code,
            "request_id": request_id,
        }

    except ChronosError as e:
        e.request_id = request_id
        logger.error(f"List tasks failed: {e}")

        return {
            "tasks": [],
            "total": 0,
            "error": ErrorSanitizer.get_user_friendly_message(e),
            "error_code": e.error_code,
            "request_id": request_id,
        }

    except Exception as e:
        chronos_error = ChronosError(
            message=f"Failed to list tasks: {str(e)}",
            details={
                "tool": "list_tasks",
                "calendar_uid": calendar_uid,
                "original_error": str(e),
                "original_type": type(e).__name__,
            },
            request_id=request_id,
        )
        logger.error(f"Unexpected error in list_tasks: {chronos_error}")

        return {
            "tasks": [],
            "total": 0,
            "error": ErrorSanitizer.get_user_friendly_message(chronos_error),
            "error_code": chronos_error.error_code,
            "request_id": request_id,
        }


@handle_tool_errors
async def update_task(
    calendar_uid: str = Field(..., description="Calendar UID"),
    task_uid: str = Field(..., description="Task UID to update"),
    summary: Optional[str] = Field(None, description="Task title/summary"),
    description: Optional[str] = Field(None, description="Task description"),
    due: Optional[str] = Field(None, description="Task due date (ISO format)"),
    priority: Optional[Union[int, str]] = Field(
        None, description="Task priority (1-9, 1 is highest)"
    ),
    status: Optional[str] = Field(None, description="Task status"),
    percent_complete: Optional[Union[int, str]] = Field(
        None, description="Completion percentage (0-100)"
    ),
    all_day: Optional[bool] = Field(
        None,
        description=(
            "Tri-state, only affects an updated due date. None (default) leaves "
            "the task's existing all-day-ness unchanged; True stores the new due "
            "as a date-only DUE;VALUE=DATE (no time, no timezone shift); False "
            "forces a timed DATE-TIME. A bare YYYY-MM-DD due string is "
            "auto-detected as all-day."
        ),
    ),
    recurrence_rule: Optional[str] = Field(
        None,
        description=(
            "RFC 5545 RRULE for a recurring task (e.g. "
            "'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=20'). A COUNT or UNTIL "
            "terminator is REQUIRED (unbounded rules are rejected). None leaves "
            "recurrence untouched; a non-empty rule sets/replaces RRULE (and a "
            "matching DTSTART anchor); an empty string ('') clears both."
        ),
    ),
    account: Optional[str] = Field(None, description="Account alias"),
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Update an existing task. Only provided fields will be updated."""
    # Handle type conversion for parameters that might come as strings from MCP
    if priority is not None:
        try:
            priority = int(priority)
        except (ValueError, TypeError):
            raise ValidationError(
                f"Invalid priority value: {priority}. Must be an integer between 1 and 9"
            )

    if percent_complete is not None:
        try:
            percent_complete = int(percent_complete)
        except (ValueError, TypeError):
            raise ValidationError(
                f"Invalid percent_complete value: {percent_complete}. "
                "Must be an integer between 0 and 100"
            )

    # Validate and parse inputs
    if summary is not None:
        summary = InputValidator.validate_text_field(summary, "summary", required=True)
    if description is not None:
        description = InputValidator.validate_text_field(description, "description")

    # Parse due date if provided. As on the create path, parse_datetime always
    # returns a datetime, so the date-only decision is made here in the tool
    # layer (explicit all_day OR a bare YYYY-MM-DD due) and threaded to the
    # manager as effective_all_day.
    due_dt = None
    # Tri-state: None means "leave all-day-ness unchanged" — pass it straight
    # through so the manager preserves the existing DUE value-type. A bare
    # YYYY-MM-DD due string still upgrades to all_day=True.
    effective_all_day = all_day
    if due is not None:
        if due:
            if _is_date_only(due):
                effective_all_day = True
            due_dt = parse_datetime(due)
        else:
            # Empty string ⇒ clear DUE. Pass a non-None falsy sentinel so the
            # manager's "due is not None" branch runs and deletes DUE.
            due_dt = ""

    # Validate priority
    if priority is not None and not (1 <= priority <= 9):
        raise ValidationError("Priority must be between 1 and 9")

    # Parse status
    status_enum = None
    if status is not None:
        try:
            status_enum = TaskStatus(status)
        except ValueError:
            raise ValidationError(
                f"Invalid status: {status}. "
                "Must be one of: NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED"
            )

    # Validate percent_complete
    if percent_complete is not None and not (0 <= percent_complete <= 100):
        raise ValidationError("Percent complete must be between 0 and 100")

    updated_task = _managers["task_manager"].update_task(
        calendar_uid=calendar_uid,
        task_uid=task_uid,
        summary=summary,
        description=description,
        due=due_dt,
        priority=priority,
        status=status_enum,
        percent_complete=percent_complete,
        all_day=effective_all_day,
        recurrence_rule=recurrence_rule,
        account_alias=account,
        request_id=request_id,
    )

    return create_success_response(
        message=f"Task '{task_uid}' updated successfully",
        request_id=request_id,
        task={
            "uid": updated_task.uid,
            "summary": updated_task.summary,
            "description": updated_task.description,
            "due": _render_due(updated_task),
            "all_day": updated_task.all_day,
            "priority": updated_task.priority,
            "status": updated_task.status.value,
            "percent_complete": updated_task.percent_complete,
            "related_to": updated_task.related_to,
            "recurrence_rule": updated_task.recurrence_rule,
        },
    )


@handle_tool_errors
async def delete_task(
    calendar_uid: str = Field(..., description="Calendar UID"),
    task_uid: str = Field(..., description="Task UID to delete"),
    account: Optional[str] = Field(None, description="Account alias"),
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Delete a task"""
    _managers["task_manager"].delete_task(
        calendar_uid=calendar_uid,
        task_uid=task_uid,
        account_alias=account,
        request_id=request_id,
    )

    return create_success_response(
        message=f"Task '{task_uid}' deleted successfully",
        request_id=request_id,
    )


def register_task_tools(mcp, managers):
    """Register task management tools with the MCP server"""

    # Update module-level managers for dependency injection
    _managers.update(managers)

    # Register all task tools with the MCP server
    mcp.tool(create_task)
    mcp.tool(list_tasks)
    mcp.tool(update_task)
    mcp.tool(delete_task)


# Add .fn attribute to each function for backwards compatibility with tests
create_task.fn = create_task  # type: ignore[attr-defined]
list_tasks.fn = list_tasks  # type: ignore[attr-defined]
update_task.fn = update_task  # type: ignore[attr-defined]
delete_task.fn = delete_task  # type: ignore[attr-defined]


# Export all tools for backwards compatibility
__all__ = [
    "create_task",
    "list_tasks",
    "update_task",
    "delete_task",
    "register_task_tools",
]
