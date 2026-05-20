"""
Shared CalDAV utility functions for calendar operations.

This module provides reusable patterns for working with CalDAV calendars,
eliminating code duplication across events, tasks, and journals managers.
"""

import logging
from typing import Any, Optional

from icalendar import Calendar as iCalendar  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def get_item_with_fallback(
    calendar,
    uid: str,
    item_type: str,
    request_id: Optional[str] = None,
) -> Any:
    """
    Get CalDAV item by UID with automatic fallback to full search.

    This function implements a two-method approach for finding CalDAV items:
    1. Method 1: Try the direct UID lookup method if available (fast)
    2. Method 2: Fallback to iterating all items and matching UID (slow but reliable)

    This pattern is necessary because not all CalDAV servers implement the
    direct UID lookup methods (event_by_uid, todo_by_uid, journal_by_uid).

    Args:
        calendar: CalDAV calendar object
        uid: Item UID to find
        item_type: Type of item - one of: "event", "task", "journal"
        request_id: Optional request ID for logging context

    Returns:
        CalDAV item object (Event, Todo, or Journal)

    Raises:
        ValueError: If item not found by either method
        Exception: Any exception from CalDAV operations

    Example:
        >>> calendar = account.calendar(calendar_uid)
        >>> event = get_item_with_fallback(calendar, "event-123", "event")
        >>> task = get_item_with_fallback(calendar, "task-456", "task")
    """
    # Map item types to their CalDAV methods and component names
    type_config = {
        "event": {
            "by_uid_method": "event_by_uid",
            "list_method": "events",
            "fallback_method": None,  # events don't have fallback
            "component_name": "VEVENT",
        },
        "task": {
            "by_uid_method": "event_by_uid",  # CalDAV uses event_by_uid for tasks
            "list_method": "todos",
            "fallback_method": "events",  # If todos() not available, use events()
            "component_name": "VTODO",
        },
        "journal": {
            "by_uid_method": "event_by_uid",  # CalDAV uses event_by_uid for journals
            "list_method": "journals",
            "fallback_method": "events",  # If journals() not available, use events()
            "component_name": "VJOURNAL",
        },
    }

    if item_type not in type_config:
        raise ValueError(f"Invalid item_type: {item_type}. Must be 'event', 'task', or 'journal'")

    config = type_config[item_type]
    by_uid_method = config["by_uid_method"]  # type: ignore[index]
    list_method = config["list_method"]  # type: ignore[index]
    fallback_method = config["fallback_method"]  # type: ignore[index]
    component_name = config["component_name"]  # type: ignore[index]

    # Method 1: Try direct UID lookup if available
    if hasattr(calendar, by_uid_method):
        try:
            item = getattr(calendar, by_uid_method)(uid)
            logger.debug(
                f"Found {item_type} '{uid}' using {by_uid_method}",
                extra={"request_id": request_id},
            )
            return item
        except Exception as e:
            logger.warning(
                f"{by_uid_method} failed for {item_type} '{uid}': {e}, trying fallback method",
                extra={"request_id": request_id},
            )

    # Method 2: Fallback - iterate all items and match UID
    try:
        # Get the list of items
        if hasattr(calendar, list_method):
            if list_method == "todos":
                items = getattr(calendar, list_method)(include_completed=True)
            else:
                items = getattr(calendar, list_method)()
        elif fallback_method and hasattr(calendar, fallback_method):
            # Use fallback method if primary not available (e.g., todos() not available)
            logger.debug(
                f"{list_method}() not available, using {fallback_method}() for {item_type}",
                extra={"request_id": request_id},
            )
            items = getattr(calendar, fallback_method)()
        else:
            raise ValueError(f"Calendar does not support {list_method}() or {fallback_method}()")

        # Search through items
        for item in items:
            # Check if UID matches in the raw data (fast check)
            # Handle both bytes (real CalDAV) and string (test mocks)
            if isinstance(item.data, bytes):
                uid_to_check: bytes | str = uid.encode("utf-8")
            else:
                uid_to_check = uid

            if uid_to_check in item.data:
                # Parse iCalendar to verify exact UID match
                try:
                    ical = iCalendar.from_ical(item.data)
                    for component in ical.walk():
                        if component.name == component_name:
                            item_uid = str(component.get("uid", ""))
                            if item_uid == uid:
                                logger.debug(
                                    f"Found {item_type} '{uid}' using fallback search",
                                    extra={"request_id": request_id},
                                )
                                return item
                except Exception as parse_error:
                    logger.warning(
                        f"Failed to parse {item_type} data: {parse_error}",
                        extra={"request_id": request_id},
                    )
                    continue

    except Exception as e:
        logger.warning(
            f"Fallback search failed for {item_type} '{uid}': {e}",
            extra={"request_id": request_id},
        )
        raise

    # Item not found by either method
    raise ValueError(f"{item_type.capitalize()} with UID '{uid}' not found")
