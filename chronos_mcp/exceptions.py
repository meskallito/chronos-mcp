"""
Chronos MCP Exception Hierarchy

This module provides a comprehensive error handling framework for Chronos MCP,
with custom exceptions for different error scenarios and utilities for
consistent error handling across the application.
"""

import functools
import logging
import re
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, Union

T = TypeVar("T")


# Base Exception
class ChronosError(Exception):
    """
    Base exception for all Chronos errors.

    Provides structured error information including:
    - Unique request ID for tracing
    - Error code for categorization
    - Detailed context information
    - Timestamp for debugging
    - Full traceback capture
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.request_id = request_id or str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.traceback = traceback.format_exc()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/API responses"""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }

    def __str__(self):
        return f"{self.error_code}: {self.message} (request_id={self.request_id})"


# Configuration Errors
class ConfigurationError(ChronosError):
    """Raised when configuration is invalid or missing"""

    pass


class AccountNotFoundError(ConfigurationError):
    """Raised when an account is not found in configuration"""

    def __init__(self, alias: str, **kwargs):
        super().__init__(
            f"Account '{alias}' not found in configuration",
            details={"alias": alias},
            **kwargs,
        )


class InvalidConfigError(ConfigurationError):
    """Raised when configuration file is invalid"""

    def __init__(self, reason: str, config_path: Optional[str] = None, **kwargs):
        details = {"reason": reason}
        if config_path:
            details["config_path"] = config_path

        super().__init__(f"Invalid configuration: {reason}", details=details, **kwargs)


# Account Management Errors
class AccountError(ChronosError):
    """Base class for account-related errors"""

    pass


class AccountConnectionError(AccountError):
    """Raised when connection to CalDAV account fails"""

    def __init__(self, alias: str, original_error: Optional[Exception] = None, **kwargs):
        details = {"alias": alias}
        if original_error:
            details["original_error"] = str(original_error)
            details["original_type"] = type(original_error).__name__

        super().__init__(f"Failed to connect to account '{alias}'", details=details, **kwargs)


class AccountAuthenticationError(AccountError):
    """Raised when authentication fails"""

    def __init__(self, alias: str, **kwargs):
        super().__init__(
            f"Authentication failed for account '{alias}'",
            error_code="AUTH_FAILED",
            details={"alias": alias},
            **kwargs,
        )


class AccountAlreadyExistsError(AccountError):
    """Raised when trying to add an account that already exists"""

    def __init__(self, alias: str, **kwargs):
        super().__init__(
            f"Account '{alias}' already exists",
            error_code="ACCOUNT_EXISTS",
            details={"alias": alias},
            **kwargs,
        )


# CalDAV Operation Errors
class CalDAVError(ChronosError):
    """Base class for CalDAV operation errors"""

    pass


class CalendarNotFoundError(CalDAVError):
    """Raised when a calendar is not found"""

    def __init__(self, calendar_uid: str, account: Optional[str] = None, **kwargs):
        details = {"calendar_uid": calendar_uid}
        if account:
            details["account"] = account

        super().__init__(f"Calendar '{calendar_uid}' not found", details=details, **kwargs)


class CalendarCreationError(CalDAVError):
    """Raised when calendar creation fails"""

    def __init__(self, name: str, reason: Optional[str] = None, **kwargs):
        message = f"Failed to create calendar '{name}'"
        if reason:
            message += f": {reason}"

        super().__init__(message, details={"calendar_name": name, "reason": reason}, **kwargs)


class CalendarDeletionError(CalDAVError):
    """Raised when calendar deletion fails"""

    def __init__(self, calendar_uid: str, reason: Optional[str] = None, **kwargs):
        message = f"Failed to delete calendar '{calendar_uid}'"
        if reason:
            message += f": {reason}"

        super().__init__(
            message, details={"calendar_uid": calendar_uid, "reason": reason}, **kwargs
        )


class EventNotFoundError(CalDAVError):
    """Raised when an event is not found"""

    def __init__(self, event_uid: str, calendar_uid: str, **kwargs):
        super().__init__(
            f"Event '{event_uid}' not found in calendar '{calendar_uid}'",
            details={"event_uid": event_uid, "calendar_uid": calendar_uid},
            **kwargs,
        )


class TaskNotFoundError(CalDAVError):
    """Raised when a task is not found"""

    def __init__(self, task_uid: str, calendar_uid: str, **kwargs):
        super().__init__(
            f"Task '{task_uid}' not found in calendar '{calendar_uid}'",
            details={"task_uid": task_uid, "calendar_uid": calendar_uid},
            **kwargs,
        )


class JournalNotFoundError(CalDAVError):
    """Raised when a journal entry is not found"""

    def __init__(self, journal_uid: str, calendar_uid: str, **kwargs):
        super().__init__(
            f"Journal '{journal_uid}' not found in calendar '{calendar_uid}'",
            details={"journal_uid": journal_uid, "calendar_uid": calendar_uid},
            **kwargs,
        )


class EventCreationError(CalDAVError):
    """Raised when event creation fails"""

    def __init__(self, summary: str, reason: Optional[str] = None, **kwargs):
        message = f"Failed to create event '{summary}'"
        if reason:
            message += f": {reason}"

        super().__init__(message, details={"event_summary": summary, "reason": reason}, **kwargs)


class EventDeletionError(CalDAVError):
    """Raised when event deletion fails"""

    def __init__(self, event_uid: str, reason: Optional[str] = None, **kwargs):
        message = f"Failed to delete event '{event_uid}'"
        if reason:
            message += f": {reason}"

        super().__init__(message, details={"event_uid": event_uid, "reason": reason}, **kwargs)


# Validation Errors
class ValidationError(ChronosError):
    """Base class for validation errors"""

    pass


class DateTimeValidationError(ValidationError):
    """Raised when datetime parsing/validation fails"""

    def __init__(self, value: str, expected_format: Optional[str] = None, **kwargs):
        message = f"Invalid datetime format: '{value}'"
        if expected_format:
            message += f" (expected: {expected_format})"

        super().__init__(
            message,
            error_code="INVALID_DATETIME",
            details={"value": value, "expected_format": expected_format},
            **kwargs,
        )


class RecurrenceRuleValidationError(ValidationError):
    """Raised when RRULE validation fails"""

    def __init__(self, rrule: str, reason: str, **kwargs):
        super().__init__(
            f"Invalid recurrence rule: {reason}",
            error_code="INVALID_RRULE",
            details={"rrule": rrule, "reason": reason},
            **kwargs,
        )


class AttendeeValidationError(ValidationError):
    """Raised when attendee data validation fails"""

    def __init__(self, attendee_data: Any, reason: str, **kwargs):
        super().__init__(
            f"Invalid attendee data: {reason}",
            error_code="INVALID_ATTENDEE",
            details={"attendee_data": str(attendee_data), "reason": reason},
            **kwargs,
        )


# Error Handling Utilities
class ErrorHandler:
    """Utility class for consistent error handling"""

    @staticmethod
    def safe_operation(
        logger: logging.Logger,
        default_return: Any = None,
        error_message: Optional[str] = None,
        raise_on_error: bool = False,
    ):
        """
        Decorator for safe operations that follow the None/False pattern.

        This decorator catches exceptions and handles them according to
        the Chronos error handling strategy:
        - Log detailed error information
        - Return a default value (None/False)
        - Optionally re-raise for specific scenarios

        Args:
            logger: Logger instance for error logging
            default_return: Value to return on error (default: None)
            error_message: Custom error message format
            raise_on_error: Whether to re-raise exceptions

        Usage:
            @ErrorHandler.safe_operation(logger, default_return=False)
            def connect_account(self, alias: str) -> bool:
                # implementation that may raise exceptions
        """

        def decorator(func: Callable[..., T]) -> Callable[..., Union[T, Any]]:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                request_id = kwargs.get("request_id", str(uuid.uuid4()))

                try:
                    # Only add request_id if the function accepts it
                    import inspect

                    sig = inspect.signature(func)
                    if "request_id" in sig.parameters and "request_id" not in kwargs:
                        kwargs["request_id"] = request_id

                    return func(*args, **kwargs)

                except ChronosError as e:
                    # Already a Chronos error, just log and handle
                    e.request_id = request_id
                    logger.error(f"{e} | Details: {e.details}")

                    if raise_on_error:
                        raise
                    return default_return

                except Exception as e:
                    # Wrap in ChronosError
                    chronos_error = ChronosError(
                        message=error_message or f"Operation failed: {str(e)}",
                        details={
                            "function": func.__name__,
                            "original_error": str(e),
                            "original_type": type(e).__name__,
                        },
                        request_id=request_id,
                    )

                    logger.error(f"{chronos_error} | Stack: {chronos_error.traceback}")

                    if raise_on_error:
                        raise chronos_error
                    return default_return

            return wrapper

        return decorator

    @staticmethod
    @contextmanager
    def error_context(
        logger: logging.Logger,
        operation: str,
        request_id: Optional[str] = None,
        raise_on_error: bool = False,
    ):
        """
        Context manager for error handling.

        Provides consistent error handling and logging for code blocks.

        Args:
            logger: Logger instance
            operation: Description of the operation
            request_id: Optional request ID for tracing
            raise_on_error: Whether to re-raise exceptions

        Usage:
            with ErrorHandler.error_context(logger, "connect_account"):
                # operation code that may raise exceptions
        """
        request_id = request_id or str(uuid.uuid4())
        logger.debug(f"Starting {operation} (request_id={request_id})")

        try:
            yield request_id
            logger.debug(f"Completed {operation} (request_id={request_id})")

        except ChronosError as e:
            e.request_id = request_id
            logger.error(f"{operation} failed: {e}")
            if raise_on_error:
                raise

        except Exception as e:
            chronos_error = ChronosError(
                message=f"{operation} failed: {str(e)}",
                details={
                    "operation": operation,
                    "original_error": str(e),
                    "original_type": type(e).__name__,
                },
                request_id=request_id,
            )
            logger.error(f"{chronos_error}")
            if raise_on_error:
                raise chronos_error


class ErrorSanitizer:
    """Sanitize error messages for user consumption"""

    # Patterns to redact sensitive information
    SENSITIVE_PATTERNS = [
        (r'password\s*[=:]\s*["\']?[\w\-\.@#$%^&*!]+["\']?', "password=***"),
        (r'token\s*[=:]\s*["\']?[\w\-\.]+["\']?', "token=***"),
        (r"https?://[^:]+:[^@]+@", "https://***:***@"),
        (r"Authorization:\s*[\w]+\s+[\w\-\.=]+", "Authorization: ***"),
        (r"Bearer\s+[\w\-\.=]+", "Bearer ***"),
        (r'api[_-]?key\s*[=:]\s*["\']?[\w\-\.]+["\']?', "api_key=***"),
        (r'secret\s*[=:]\s*["\']?[\w\-\.]+["\']?', "secret=***"),
    ]

    @classmethod
    def sanitize_message(cls, message: str) -> str:
        """Remove sensitive information from error messages"""
        sanitized = message
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

        return sanitized

    @classmethod
    def sanitize_error(cls, error: ChronosError) -> Dict[str, Any]:
        """Create sanitized error dict for API responses"""
        return {
            "error": error.error_code,
            "message": cls.sanitize_message(error.message),
            "request_id": error.request_id,
            # Don't include details or traceback in user responses
        }

    @classmethod
    def get_user_friendly_message(cls, error: ChronosError) -> str:
        """Get user-friendly error message"""
        # Map error codes to friendly messages
        friendly_messages = {
            "AUTH_FAILED": "Authentication failed. Please check your credentials.",
            "INVALID_DATETIME": (
                "Invalid date/time format. Please use ISO format (YYYY-MM-DD HH:MM:SS)."
            ),
            "INVALID_RRULE": "Invalid recurrence rule format.",
            "INVALID_ATTENDEE": "Invalid attendee information provided.",
            "ACCOUNT_EXISTS": "An account with this name already exists.",
            "AccountNotFoundError": "The specified account was not found.",
            "CalendarNotFoundError": "The specified calendar was not found.",
            "EventNotFoundError": "The specified event was not found.",
            "TaskNotFoundError": "The specified task was not found.",
            "JournalNotFoundError": "The specified journal entry was not found.",
            "AccountConnectionError": (
                "Could not connect to the calendar server. Please check the server URL."
            ),
            "CalendarCreationError": "Could not create the calendar. It may already exist.",
            "EventCreationError": "Could not create the event. Please check all required fields.",
            "InvalidConfigError": "The configuration file is invalid or corrupted.",
        }

        return friendly_messages.get(
            error.error_code,
            f"An error occurred: {cls.sanitize_message(error.message)}",
        )
