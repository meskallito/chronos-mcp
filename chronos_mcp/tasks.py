"""
Task operations for Chronos MCP
"""

import uuid
from datetime import date, datetime, time, timezone
from typing import List, Optional, Union

import caldav  # type: ignore[import-untyped,import-not-found]
from caldav import Event as CalDAVEvent
from icalendar import Calendar as iCalendar  # type: ignore[import-untyped]
from icalendar import Todo as iTodo  # type: ignore[import-untyped]

from .caldav_utils import get_item_with_fallback
from .calendars import CalendarManager
from .exceptions import (
    CalendarNotFoundError,
    ChronosError,
    EventCreationError,
    EventDeletionError,
    TaskNotFoundError,
)
from .logging_config import setup_logging
from .models import Task, TaskStatus
from .utils import _default_tz, ical_to_datetime, validate_rrule

logger = setup_logging()


def _is_date_value(value: object) -> bool:
    """Return True when ``value`` represents a date-only (VALUE=DATE) value.

    Accepts either an icalendar property (with a ``.dt`` attribute) or a raw
    ``date``/``datetime``. A date-only value has no time component, i.e. its
    underlying object is a ``date`` that is not a ``datetime`` (equivalently,
    it has no ``hour`` attribute). Used by both the write and read paths to
    derive the DATE-vs-DATE-TIME value-type.
    """
    dt = getattr(value, "dt", value)
    return isinstance(dt, date) and not isinstance(dt, datetime)


def _anchor_for(
    due_value: Union[date, datetime, None],
    existing_due: Union[date, datetime, None],
    all_day: bool,
) -> Union[date, datetime]:
    """Select the DTSTART anchor for a recurring VTODO (RFC 5545).

    The RRULE of a VTODO anchors to DTSTART, which we keep at the same
    value-type as DUE. Preference ladder: the freshly-supplied ``due_value``,
    else the task's ``existing_due``, else today in the default zone (a bare
    ``date`` when ``all_day`` is truthy, otherwise a zoned ``datetime``).
    """
    if due_value is not None:
        return due_value
    if existing_due is not None:
        return existing_due
    if all_day:
        return datetime.now(_default_tz()).date()
    return datetime.now(_default_tz())


class TaskManager:
    """Manage calendar tasks (VTODO)"""

    def __init__(self, calendar_manager: CalendarManager):
        self.calendars = calendar_manager

    def _get_default_account(self) -> Optional[str]:
        try:
            return self.calendars.accounts.config.config.default_account
        except Exception:
            return None

    def create_task(
        self,
        calendar_uid: str,
        summary: str,
        description: Optional[str] = None,
        due: Optional[datetime] = None,
        priority: Optional[int] = None,
        status: TaskStatus = TaskStatus.NEEDS_ACTION,
        related_to: Optional[List[str]] = None,
        all_day: bool = False,
        recurrence_rule: Optional[str] = None,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Create a new task - raises exceptions on failure"""
        request_id = request_id or str(uuid.uuid4())

        calendar = self.calendars.get_calendar(calendar_uid, account_alias, request_id=request_id)
        if not calendar:
            raise CalendarNotFoundError(calendar_uid, account_alias, request_id=request_id)

        try:
            # Validate RRULE if provided (mirrors the event path)
            if recurrence_rule:
                is_valid, error_msg = validate_rrule(recurrence_rule)
                if not is_valid:
                    raise EventCreationError(
                        summary, f"Invalid RRULE: {error_msg}", request_id=request_id
                    )

            cal = iCalendar()
            task = iTodo()

            # Generate UID if not provided
            task_uid = str(uuid.uuid4())

            task.add("uid", task_uid)
            task.add("summary", summary)
            task.add("dtstamp", datetime.now(timezone.utc))

            if description:
                task.add("description", description)
            # Compute the DUE value (a date for all-day, else the datetime) so it
            # can also be reused as the RRULE DTSTART anchor with a matching value-type.
            # NOTE: unlike events.py, timed task DUE/DTSTART are emitted in their
            # supplied (default-zone) datetime rather than normalized to UTC. This
            # is deliberate — the date-grounding fix relies on preserving the zone.
            due_value = None
            if due:
                if all_day:
                    # Emit DUE;VALUE=DATE:YYYYMMDD (no time, no UTC day-shift)
                    due_value = due.date() if isinstance(due, datetime) else due
                else:
                    due_value = due
                task.add("due", due_value)
            if recurrence_rule:
                # RFC 5545: a VTODO RRULE anchors to DTSTART. Anchor to the DUE
                # value (same value-type as DUE so DTSTART == DUE), or to
                # today-in-default-tz when no due is provided. Never emit a
                # DURATION (a VTODO must not carry both DUE and DURATION).
                task.add("dtstart", _anchor_for(due_value, None, all_day))
                task.add("rrule", recurrence_rule)
            if priority is not None and 1 <= priority <= 9:
                task.add("priority", priority)
            task.add("status", status.value)
            task.add("percent-complete", 0)

            if related_to:
                for related_uid in related_to:
                    task.add("related-to", related_uid)

            cal.add_component(task)

            # Save to CalDAV server using component-specific method when available
            ical_data = cal.to_ical().decode("utf-8")

            if hasattr(calendar, "save_todo"):
                logger.debug(
                    "Using calendar.save_todo() for optimized task creation",
                    extra={"request_id": request_id},
                )
                try:
                    calendar.save_todo(ical_data)
                except Exception as e:
                    logger.warning(
                        f"calendar.save_todo() failed: {e}, falling back to save_event()",
                        extra={"request_id": request_id},
                    )
                    calendar.save_event(ical_data)
            else:
                logger.debug(
                    "Server doesn't support calendar.save_todo(), using calendar.save_event()",
                    extra={"request_id": request_id},
                )
                calendar.save_event(ical_data)

            task_model = Task(
                uid=task_uid,
                summary=summary,
                description=description,
                due=due,
                completed=None,
                priority=priority,
                status=status,
                percent_complete=0,
                related_to=related_to or [],
                calendar_uid=calendar_uid,
                account_alias=account_alias or self._get_default_account() or "default",
            )

            return task_model

        except caldav.lib.error.AuthorizationError as e:
            logger.error(
                f"Authorization error creating task '{summary}': {e}",
                extra={"request_id": request_id},
            )
            raise EventCreationError(summary, "Authorization failed", request_id=request_id)
        except Exception as e:
            logger.error(
                f"Error creating task '{summary}': {e}",
                extra={"request_id": request_id},
            )
            raise EventCreationError(summary, str(e), request_id=request_id)

    def get_task(
        self,
        task_uid: str,
        calendar_uid: str,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Get a specific task by UID"""
        request_id = request_id or str(uuid.uuid4())

        calendar = self.calendars.get_calendar(calendar_uid, account_alias, request_id=request_id)
        if not calendar:
            raise CalendarNotFoundError(calendar_uid, account_alias, request_id=request_id)

        try:
            # Use utility function to find task with automatic fallback
            caldav_task = get_item_with_fallback(calendar, task_uid, "task", request_id=request_id)
            return self._parse_caldav_task(caldav_task, calendar_uid, account_alias)
        except ValueError:
            # get_item_with_fallback raises ValueError when not found
            raise TaskNotFoundError(task_uid, calendar_uid, request_id=request_id)

        except TaskNotFoundError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting task '{task_uid}': {e}",
                extra={"request_id": request_id},
            )
            raise ChronosError(f"Failed to get task: {str(e)}", request_id=request_id)

    def list_tasks(
        self,
        calendar_uid: str,
        status_filter: Optional[TaskStatus] = None,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[Task]:
        """List all tasks in a calendar"""
        request_id = request_id or str(uuid.uuid4())

        calendar = self.calendars.get_calendar(calendar_uid, account_alias, request_id=request_id)
        if not calendar:
            raise CalendarNotFoundError(calendar_uid, account_alias, request_id=request_id)

        tasks = []
        try:
            # Try component-specific method first for better performance
            if hasattr(calendar, "todos"):
                try:
                    logger.debug(
                        "Using calendar.todos() for server-side filtering",
                        extra={"request_id": request_id},
                    )
                    todos = calendar.todos(include_completed=True)

                    for caldav_todo in todos:
                        task_data = self._parse_caldav_task(
                            caldav_todo, calendar_uid, account_alias
                        )
                        if task_data:
                            tasks.append(task_data)

                except Exception as e:
                    logger.warning(
                        f"calendar.todos() failed: {e}, falling back to calendar.events()",
                        extra={"request_id": request_id},
                    )
                    # Fall through to fallback method
                    raise
            else:
                # Fallback method for servers without todos() support
                logger.debug(
                    "Server doesn't support calendar.todos(),"
                    " using calendar.events() with client-side filtering",
                    extra={"request_id": request_id},
                )
                events = calendar.events()

                for caldav_event in events:
                    task_data = self._parse_caldav_task(caldav_event, calendar_uid, account_alias)
                    if task_data:
                        tasks.append(task_data)

        except Exception as e:
            # If todos() method failed, try the fallback approach
            if hasattr(calendar, "todos"):
                try:
                    logger.info(
                        "Retrying with calendar.events() fallback method",
                        extra={"request_id": request_id},
                    )
                    events = calendar.events()

                    for caldav_event in events:
                        task_data = self._parse_caldav_task(
                            caldav_event, calendar_uid, account_alias
                        )
                        if task_data:
                            tasks.append(task_data)
                except Exception as fallback_error:
                    logger.error(
                        f"Error listing tasks (both methods failed): {fallback_error}",
                        extra={"request_id": request_id},
                    )
            else:
                logger.error(f"Error listing tasks: {e}", extra={"request_id": request_id})

        # Filter by status if requested
        if status_filter:
            tasks = [task for task in tasks if task.status == status_filter]
            logger.debug(
                f"Filtered tasks by status {status_filter.value}: {len(tasks)} tasks",
                extra={"request_id": request_id},
            )

        return tasks

    def update_task(
        self,
        task_uid: str,
        calendar_uid: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        due: Optional[datetime] = None,
        priority: Optional[int] = None,
        status: Optional[TaskStatus] = None,
        percent_complete: Optional[int] = None,
        related_to: Optional[List[str]] = None,
        all_day: Optional[bool] = None,
        recurrence_rule: Optional[str] = None,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Update an existing task - raises exceptions on failure.

        Clear conventions (mirroring the existing description/due/related_to
        semantics where ``None`` means "not provided" and an empty value means
        "clear"):
        - ``due=None`` leaves DUE untouched; pass a datetime/date to set it.
        - ``recurrence_rule=None`` leaves RRULE/DTSTART untouched; a non-empty
          string sets/replaces them; an empty string ("") clears both.
        - ``all_day`` is tri-state and only affects the DUE re-emission when a
          new ``due`` is provided: ``None`` leaves the all-day-ness unchanged
          (preserving the existing DUE's DATE-vs-DATE-TIME value-type), ``True``
          forces a date-only DUE;VALUE=DATE, ``False`` forces a timed DATE-TIME.
        """
        request_id = request_id or str(uuid.uuid4())

        # Validate RRULE early if one is being set (mirrors the create path);
        # an empty string is the "clear" sentinel and skips validation.
        if recurrence_rule:
            is_valid, error_msg = validate_rrule(recurrence_rule)
            if not is_valid:
                raise EventCreationError(
                    f"Task {task_uid}", f"Invalid RRULE: {error_msg}", request_id=request_id
                )

        calendar = self.calendars.get_calendar(calendar_uid, account_alias, request_id=request_id)
        if not calendar:
            raise CalendarNotFoundError(calendar_uid, account_alias, request_id=request_id)

        try:
            # Use utility function to find task with automatic fallback
            try:
                caldav_task = get_item_with_fallback(
                    calendar, task_uid, "task", request_id=request_id
                )
            except ValueError:
                raise TaskNotFoundError(task_uid, calendar_uid, request_id=request_id)

            # Parse existing task data
            ical = iCalendar.from_ical(caldav_task.data)
            existing_task = None

            for component in ical.walk():
                if component.name == "VTODO":
                    existing_task = component
                    break

            if not existing_task:
                raise EventCreationError(
                    f"Task {task_uid}",
                    "Could not parse existing task data",
                    request_id=request_id,
                )

            # Update only provided fields
            if summary is not None:
                existing_task["SUMMARY"] = summary

            if description is not None:
                if description:
                    existing_task["DESCRIPTION"] = description
                elif "DESCRIPTION" in existing_task:
                    del existing_task["DESCRIPTION"]

            # Track the effective DUE value (date for all-day, else datetime)
            # so a concurrently-updated RRULE can re-anchor DTSTART to it.
            due_value = None
            due_updated = False
            if due is not None:
                due_updated = True
                # Detect the existing DUE's value-type BEFORE deleting it so a
                # tri-state ``all_day=None`` can preserve date-only-ness.
                existing_due_prop = existing_task.get("due")
                existing_due_is_date = existing_due_prop is not None and _is_date_value(
                    existing_due_prop
                )
                if "DUE" in existing_task:
                    del existing_task["DUE"]
                if due:
                    # Resolve the effective all-day-ness: ``None`` preserves the
                    # existing DUE value-type, otherwise honour the explicit flag.
                    effective_all_day = existing_due_is_date if all_day is None else all_day
                    # Re-emit as a date (VALUE=DATE) for all-day, or a
                    # (correctly-zoned) datetime otherwise. Supports switching a
                    # timed task -> date-only AND date-only -> timed.
                    if effective_all_day:
                        due_value = due.date() if isinstance(due, datetime) else due
                    else:
                        due_value = due
                    existing_task.add("DUE", due_value)

            if priority is not None:
                if priority and 1 <= priority <= 9:
                    existing_task["PRIORITY"] = priority
                elif "PRIORITY" in existing_task:
                    del existing_task["PRIORITY"]

            if status is not None:
                existing_task["STATUS"] = status.value

            if percent_complete is not None:
                if 0 <= percent_complete <= 100:
                    existing_task["PERCENT-COMPLETE"] = percent_complete

            # Handle RELATED-TO property updates
            if related_to is not None:
                # Remove all existing RELATED-TO properties
                if "RELATED-TO" in existing_task:
                    del existing_task["RELATED-TO"]

                # Add new RELATED-TO properties if provided
                if related_to:
                    for related_uid in related_to:
                        existing_task.add("RELATED-TO", related_uid)

            # Recurrence handling. ``None`` = untouched, "" (empty) = clear,
            # non-empty = set/replace. RFC 5545 anchors a VTODO's RRULE to
            # DTSTART, so we keep DTSTART == DUE (same value-type, no DURATION).
            if recurrence_rule is not None:
                # Always remove any existing RRULE/DTSTART first so set and
                # clear both start from a clean slate.
                if "RRULE" in existing_task:
                    del existing_task["RRULE"]
                if "DTSTART" in existing_task:
                    del existing_task["DTSTART"]
                if recurrence_rule:
                    # Anchor DTSTART to the DUE value: the freshly-updated due
                    # if provided, else the task's current DUE, else
                    # today-in-default-tz (matching its all_day-ness).
                    existing_due_prop = existing_task.get("due")
                    existing_due_dt = (
                        existing_due_prop.dt if existing_due_prop is not None else None
                    )
                    existing_task.add(
                        "DTSTART", _anchor_for(due_value, existing_due_dt, bool(all_day))
                    )
                    existing_task.add("RRULE", recurrence_rule)
            elif due_updated and "RRULE" in existing_task:
                # DUE changed on an already-recurring task and no new rule was
                # supplied: keep the DTSTART anchor in sync with the new DUE.
                # A recurring VTODO MUST retain a DTSTART anchor (RFC 5545), so
                # never strip it to nothing — if the DUE was *cleared*
                # (due_value is None), re-anchor to today-in-default-tz instead
                # of leaving a dangling RRULE.
                existing_dtstart_prop = existing_task.get("dtstart")
                existing_anchor_is_date = existing_dtstart_prop is not None and _is_date_value(
                    existing_dtstart_prop
                )
                if "DTSTART" in existing_task:
                    del existing_task["DTSTART"]
                # ``due_value`` (the freshly-set DUE) wins; when DUE was cleared
                # we re-anchor to today, matching the prior DTSTART's
                # date-vs-datetime value-type so an all-day recurrence stays
                # all-day. (A recurring VTODO MUST keep a DTSTART anchor.)
                existing_task.add("DTSTART", _anchor_for(due_value, None, existing_anchor_is_date))

            # Update last-modified timestamp
            if "LAST-MODIFIED" in existing_task:
                del existing_task["LAST-MODIFIED"]
            existing_task.add("LAST-MODIFIED", datetime.now(timezone.utc))

            # Save the updated task
            caldav_task.data = ical.to_ical().decode("utf-8")
            caldav_task.save()

            # Parse and return the updated task
            return self._parse_caldav_task(caldav_task, calendar_uid, account_alias)

        except TaskNotFoundError:
            raise
        except EventCreationError:
            raise
        except Exception as e:
            logger.error(
                f"Error updating task '{task_uid}': {e}",
                extra={"request_id": request_id},
            )
            raise EventCreationError(
                task_uid, f"Failed to update task: {str(e)}", request_id=request_id
            )

    def delete_task(
        self,
        calendar_uid: str,
        task_uid: str,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """Delete a task by UID - raises exceptions on failure"""
        request_id = request_id or str(uuid.uuid4())

        calendar = self.calendars.get_calendar(calendar_uid, account_alias, request_id=request_id)
        if not calendar:
            raise CalendarNotFoundError(calendar_uid, account_alias, request_id=request_id)

        try:
            # Use utility function to find task with automatic fallback
            task = get_item_with_fallback(calendar, task_uid, "task", request_id=request_id)
            task.delete()
            logger.info(
                f"Deleted task '{task_uid}'",
                extra={"request_id": request_id},
            )
            return True
        except ValueError:
            # get_item_with_fallback raises ValueError when not found
            raise TaskNotFoundError(task_uid, calendar_uid, request_id=request_id)

        except TaskNotFoundError:
            raise
        except caldav.lib.error.AuthorizationError as e:
            logger.error(
                f"Authorization error deleting task '{task_uid}': {e}",
                extra={"request_id": request_id},
            )
            raise EventDeletionError(task_uid, "Authorization failed", request_id=request_id)
        except Exception as e:
            logger.error(
                f"Error deleting task '{task_uid}': {e}",
                extra={"request_id": request_id},
            )
            raise EventDeletionError(task_uid, str(e), request_id=request_id)

    def _parse_caldav_task(
        self, caldav_event: CalDAVEvent, calendar_uid: str, account_alias: Optional[str]
    ) -> Optional[Task]:
        """Parse CalDAV VTODO to Task model"""
        try:
            # Parse iCalendar data
            ical = iCalendar.from_ical(caldav_event.data)

            for component in ical.walk():
                if component.name == "VTODO":
                    # Parse date/time values
                    due_dt = None
                    completed_dt = None
                    all_day = False

                    # Detect a date-only DUE on the RAW property (mirroring the
                    # event read path in events.py) BEFORE ical_to_datetime
                    # flattens a date to midnight-UTC — the read-side of the
                    # original day-shift bug.
                    due_prop = component.get("due")
                    if due_prop is not None:
                        # VALUE=DATE → ``.dt`` is a ``date`` that is not a ``datetime``.
                        is_date = hasattr(due_prop, "dt") and _is_date_value(due_prop)
                        if is_date:
                            all_day = True
                            # Midnight in the default zone, NOT UTC, so callers
                            # formatting ``due.date()`` get the correct day.
                            due_dt = datetime.combine(due_prop.dt, time.min, tzinfo=_default_tz())
                        else:
                            due_dt = ical_to_datetime(due_prop)
                    if component.get("completed"):
                        completed_dt = ical_to_datetime(component.get("completed"))

                    # Surface a recurrence rule as a clean RFC 5545 RRULE string
                    # (e.g. ``FREQ=WEEKLY;BYDAY=MO,TU;COUNT=10``) so it can be fed
                    # straight back into create/update. ``str()`` on the icalendar
                    # ``vRecur`` yields its Python repr, which is NOT round-trippable.
                    rrule_prop = component.get("rrule")
                    recurrence_rule = (
                        rrule_prop.to_ical().decode() if rrule_prop is not None else None
                    )

                    # Parse priority
                    priority = None
                    if component.get("priority"):
                        try:
                            priority = int(component.get("priority"))
                        except (ValueError, TypeError):
                            priority = None

                    # Parse percent complete
                    percent_complete = 0
                    if component.get("percent-complete"):
                        try:
                            percent_complete = int(component.get("percent-complete"))
                        except (ValueError, TypeError):
                            percent_complete = 0

                    # Parse status
                    status = TaskStatus.NEEDS_ACTION
                    if component.get("status"):
                        try:
                            status = TaskStatus(str(component.get("status")))
                        except ValueError:
                            status = TaskStatus.NEEDS_ACTION

                    # Parse RELATED-TO properties
                    related_to = []
                    if component.get("related-to"):
                        related_prop = component.get("related-to")
                        if isinstance(related_prop, list):
                            related_to = [str(r) for r in related_prop]
                        else:
                            related_to = [str(related_prop)]

                    # Parse basic task data
                    task = Task(
                        uid=str(component.get("uid", "")),
                        summary=str(component.get("summary", "No Title")),
                        description=(
                            str(component.get("description", ""))
                            if component.get("description")
                            else None
                        ),
                        due=due_dt,
                        all_day=all_day,
                        completed=completed_dt,
                        priority=priority,
                        status=status,
                        percent_complete=percent_complete,
                        related_to=related_to,
                        recurrence_rule=recurrence_rule,
                        calendar_uid=calendar_uid,
                        account_alias=account_alias or self._get_default_account() or "default",
                    )

                    return task

        except Exception as e:
            logger.error(f"Error parsing task: {e}")

        return None
