"""RRULE validation and parsing for recurring events.

This module provides utilities for validating and working with
iCalendar RRULE (recurrence rule) strings used in recurring events.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY, rrulestr

logger = logging.getLogger(__name__)

# Maximum values for safety
MAX_COUNT = 365  # Maximum number of occurrences
MAX_YEARS_AHEAD = 2  # Maximum years into the future
MIN_INTERVAL_SECONDS = 3600  # Minimum 1 hour between occurrences
MAX_INSTANCES_TO_EXPAND = 1000  # Maximum instances to expand at once


class RRuleValidator:
    """Validate and parse RRULE strings for recurring events."""

    # Allowed frequencies (no SECONDLY or MINUTELY for performance)
    ALLOWED_FREQUENCIES = {
        "DAILY": DAILY,
        "WEEKLY": WEEKLY,
        "MONTHLY": MONTHLY,
        "YEARLY": YEARLY,
    }

    @classmethod
    def validate_rrule(cls, rrule_string: str) -> Tuple[bool, Optional[str]]:
        """
        Validate an RRULE string for safety and correctness.

        Args:
            rrule_string: The RRULE string to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not rrule_string:
            return False, "RRULE cannot be empty"

        try:
            # Basic format check
            if not rrule_string.startswith("FREQ="):
                return False, "RRULE must start with FREQ="

            # Parse the rule to check validity
            rrulestr(rrule_string)

            # Extract frequency
            freq_str = None
            for part in rrule_string.split(";"):
                if part.startswith("FREQ="):
                    freq_str = part.split("=")[1]
                    break

            if freq_str not in cls.ALLOWED_FREQUENCIES:
                return (
                    False,
                    f"Frequency {freq_str} not allowed. "
                    f"Use: {', '.join(cls.ALLOWED_FREQUENCIES.keys())}",
                )

            # Check for end condition (COUNT or UNTIL)
            has_count = "COUNT=" in rrule_string
            has_until = "UNTIL=" in rrule_string

            if not has_count and not has_until:
                return (
                    False,
                    "RRULE must have COUNT or UNTIL to prevent infinite recurrence",
                )

            # Validate COUNT if present
            if has_count:
                count_value = cls._extract_value(rrule_string, "COUNT")
                if count_value:
                    try:
                        count = int(count_value)
                        if count > MAX_COUNT:
                            return False, f"COUNT cannot exceed {MAX_COUNT}"
                        if count < 1:
                            return False, "COUNT must be at least 1"
                    except ValueError:
                        return False, "COUNT must be a valid integer"

            # Validate UNTIL if present
            if has_until:
                until_value = cls._extract_value(rrule_string, "UNTIL")
                if until_value:
                    try:
                        # Parse the until date
                        if "T" in until_value:
                            until_dt = datetime.strptime(until_value, "%Y%m%dT%H%M%SZ")
                        else:
                            until_dt = datetime.strptime(until_value, "%Y%m%d")

                        # Ensure it's timezone aware
                        if until_dt.tzinfo is None:
                            until_dt = until_dt.replace(tzinfo=timezone.utc)

                        # Check it's not too far in the future
                        now = datetime.now(timezone.utc)
                        max_future = now.replace(year=now.year + MAX_YEARS_AHEAD)

                        if until_dt > max_future:
                            return (
                                False,
                                f"UNTIL date cannot be more than "
                                f"{MAX_YEARS_AHEAD} years in the future",
                            )

                    except ValueError:
                        return (
                            False,
                            "UNTIL must be a valid date in YYYYMMDD or YYYYMMDDTHHMMSSZ format",
                        )

            # Validate INTERVAL if present
            if "INTERVAL=" in rrule_string:
                interval_value = cls._extract_value(rrule_string, "INTERVAL")
                if interval_value:
                    try:
                        interval = int(interval_value)
                        if interval < 1:
                            return False, "INTERVAL must be at least 1"
                        # Check minimum interval based on frequency
                        if freq_str == "DAILY" and interval > 365:
                            return False, "Daily INTERVAL cannot exceed 365"
                    except ValueError:
                        return False, "INTERVAL must be a valid integer"

            return True, None

        except Exception as e:
            logger.error(f"Error validating RRULE: {str(e)}")
            return False, f"Invalid RRULE format: {str(e)}"

    @staticmethod
    def _extract_value(rrule_string: str, param: str) -> Optional[str]:
        """Extract a parameter value from an RRULE string."""
        for part in rrule_string.split(";"):
            if part.startswith(f"{param}="):
                return part.split("=")[1]
        return None

    @classmethod
    def expand_occurrences(
        cls,
        rrule_string: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        limit: int = MAX_INSTANCES_TO_EXPAND,
    ) -> List[datetime]:
        """
        Expand recurring rule to individual occurrences.
        Args:
            rrule_string: The RRULE string
            start_date: Start date for the recurrence
            end_date: Optional end date to limit occurrences
            limit: Maximum number of occurrences to return

        Returns:
            List of datetime objects representing occurrences
        """
        try:
            # Ensure start_date has timezone
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)

            # Parse the rule
            rule = rrulestr(rrule_string, dtstart=start_date)

            # Generate occurrences
            occurrences = []
            for i, occurrence in enumerate(rule):
                if i >= limit:
                    break

                if end_date and occurrence > end_date:
                    break

                occurrences.append(occurrence)

            return occurrences

        except Exception as e:
            logger.error(f"Error expanding RRULE occurrences: {str(e)}")
            return []

    @classmethod
    def get_rrule_info(cls, rrule_string: str) -> Dict[str, Any]:
        """
        Extract information from an RRULE string.

        Args:
            rrule_string: The RRULE string to parse

        Returns:
            Dictionary with RRULE components
        """
        info = {
            "frequency": None,
            "interval": 1,
            "count": None,
            "until": None,
            "byday": None,
            "bymonthday": None,
            "bymonth": None,
        }

        for part in rrule_string.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)

                if key == "FREQ":
                    info["frequency"] = value
                elif key == "INTERVAL":
                    info["interval"] = int(value)
                elif key == "COUNT":
                    info["count"] = int(value)
                elif key == "UNTIL":
                    info["until"] = value
                elif key == "BYDAY":
                    info["byday"] = value.split(",")
                elif key == "BYMONTHDAY":
                    info["bymonthday"] = [int(d) for d in value.split(",")]
                elif key == "BYMONTH":
                    info["bymonth"] = [int(m) for m in value.split(",")]

        return info


# Common RRULE patterns for convenience
class RRuleTemplates:
    """Common RRULE templates for recurring events."""

    # Daily patterns
    DAILY_WEEKDAYS = "FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"
    DAILY_FOREVER = "FREQ=DAILY"  # Needs COUNT or UNTIL added

    # Weekly patterns
    WEEKLY_ON_DAY = "FREQ=WEEKLY;BYDAY={day}"  # Replace {day} with MO, TU, etc.
    WEEKLY_MULTIPLE_DAYS = "FREQ=WEEKLY;BYDAY={days}"  # Replace {days} with comma-separated

    # Monthly patterns
    MONTHLY_ON_DATE = "FREQ=MONTHLY;BYMONTHDAY={day}"  # Replace {day} with 1-31
    MONTHLY_LAST_DAY = "FREQ=MONTHLY;BYMONTHDAY=-1"
    MONTHLY_FIRST_WEEKDAY = "FREQ=MONTHLY;BYDAY=1{day}"  # e.g., 1MO for first Monday

    # Yearly patterns
    YEARLY_ON_DATE = "FREQ=YEARLY"
    YEARLY_ON_MONTH_DAY = "FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day}"
