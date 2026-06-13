"""
Account management for Chronos MCP
"""

import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import caldav  # type: ignore[import-untyped,import-not-found]
from caldav import DAVClient, Principal

from .config import ConfigManager
from .credentials import get_credential_manager
from .exceptions import (
    AccountAuthenticationError,
    AccountConnectionError,
    AccountNotFoundError,
    ChronosError,
    ErrorSanitizer,
)
from .logging_config import setup_logging
from .models import AccountStatus

logger = setup_logging()


class CircuitBreakerState(Enum):
    """Circuit breaker states"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Circuit breaker for connection failures"""

    failure_count: int = 0
    failure_threshold: int = 5
    recovery_timeout: int = 60  # seconds
    last_failure_time: float = 0
    state: CircuitBreakerState = CircuitBreakerState.CLOSED

    def should_allow_request(self) -> bool:
        """Check if request should be allowed through circuit breaker"""
        if self.state == CircuitBreakerState.CLOSED:
            return True
        elif self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                return True
            return False
        else:  # HALF_OPEN
            return True

    def record_success(self):
        """Record successful operation"""
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED

    def record_failure(self):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN


@dataclass
class ConnectionHealth:
    """Track connection health metrics"""

    total_attempts: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    last_success_time: float = 0
    last_failure_time: float = 0

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 1.0
        return self.successful_connections / self.total_attempts


class AccountManager:
    """Manage CalDAV account connections with lifecycle management"""

    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.connections: Dict[str, DAVClient] = {}
        self.principals: Dict[str, Principal] = {}
        self._connection_locks: Dict[str, threading.Lock] = {}
        self._connection_timestamps: Dict[str, float] = {}
        self._connection_ttl_minutes: int = 30  # Connection TTL in minutes

        # Connection pool limits and health tracking
        self._max_connections_per_account: int = 3
        self._connection_timeout: int = 30  # Connection timeout in seconds
        self._max_retries: int = 3
        self._base_retry_delay: float = 1.0  # Base delay for exponential backoff

        # Circuit breaker and health tracking
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._connection_health: Dict[str, ConnectionHealth] = {}

    def connect_account(self, alias: str, request_id: Optional[str] = None) -> bool:
        """Connect to a CalDAV account with circuit breaker and retry logic"""
        request_id = request_id or str(uuid.uuid4())

        account = self.config.get_account(alias)
        if not account:
            raise AccountNotFoundError(alias, request_id=request_id)

        # Check connection pool limits
        if (
            alias in self.connections
            and len([k for k in self.connections.keys() if k == alias])
            >= self._max_connections_per_account
        ):
            logger.warning(f"Connection pool limit reached for account '{alias}'")
            # Clean up stale connections first
            self._cleanup_stale_connection(alias)

        # Initialize circuit breaker and health tracking if needed
        if alias not in self._circuit_breakers:
            self._circuit_breakers[alias] = CircuitBreaker()
        if alias not in self._connection_health:
            self._connection_health[alias] = ConnectionHealth()

        circuit_breaker = self._circuit_breakers[alias]
        health = self._connection_health[alias]

        # Check circuit breaker
        if not circuit_breaker.should_allow_request():
            health.total_attempts += 1
            health.failed_connections += 1
            logger.error(
                f"Circuit breaker OPEN for account '{alias}' - rejecting connection attempt",
                extra={"request_id": request_id},
            )
            raise AccountConnectionError(
                alias,
                original_error=Exception("Circuit breaker is OPEN"),
                request_id=request_id,
            )

        # Get password from keyring or fallback to config
        credential_manager = get_credential_manager()
        password = credential_manager.get_password(alias, fallback_password=account.password)

        if not password:
            raise AccountAuthenticationError(alias, request_id=request_id)

        # Retry logic with exponential backoff
        last_exception = None
        for attempt in range(self._max_retries):
            health.total_attempts += 1

            try:
                client = DAVClient(
                    url=str(account.url),
                    username=account.username,
                    password=password,
                    timeout=self._connection_timeout,
                )

                # Test connection by getting principal with timeout
                principal = client.principal()

                # Store connection with timestamp
                self.connections[alias] = client
                self.principals[alias] = principal
                self._connection_timestamps[alias] = time.time()

                # Ensure lock exists for this connection
                if alias not in self._connection_locks:
                    self._connection_locks[alias] = threading.Lock()

                # Record success
                circuit_breaker.record_success()
                health.successful_connections += 1
                health.last_success_time = time.time()

                account.status = AccountStatus.CONNECTED
                logger.info(
                    f"Successfully connected to account '{alias}' on attempt {attempt + 1}",
                    extra={"request_id": request_id},
                )
                return True

            except caldav.lib.error.AuthorizationError as e:
                last_exception = e
                circuit_breaker.record_failure()
                health.failed_connections += 1
                health.last_failure_time = time.time()

                account.status = AccountStatus.ERROR
                logger.error(
                    f"Authentication failed for '{alias}' on attempt {attempt + 1}: {e}",
                    extra={"request_id": request_id},
                )
                # Don't retry auth errors
                raise AccountAuthenticationError(alias, request_id=request_id)

            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Connection attempt {attempt + 1} failed for '{alias}': {e}",
                    extra={"request_id": request_id},
                )

                if attempt < self._max_retries - 1:
                    delay = self._base_retry_delay * (2**attempt)
                    logger.debug(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    # All retries exhausted
                    circuit_breaker.record_failure()
                    health.failed_connections += 1
                    health.last_failure_time = time.time()

                    account.status = AccountStatus.ERROR
                    logger.error(
                        f"All {self._max_retries} connection attempts failed for '{alias}'",
                        extra={"request_id": request_id},
                    )
                    raise AccountConnectionError(
                        alias, original_error=last_exception, request_id=request_id
                    )

        # Should never reach here, but just in case
        raise AccountConnectionError(alias, original_error=last_exception, request_id=request_id)

    def disconnect_account(self, alias: str):
        """Disconnect from an account and clean up resources

        Thread-safety: This method MUST be called while holding self._connection_locks[alias].
        All callers (get_connection, get_principal) acquire lock before calling this method.
        """
        if alias in self.connections:
            del self.connections[alias]
        if alias in self.principals:
            del self.principals[alias]
        if alias in self._connection_timestamps:
            del self._connection_timestamps[alias]
        # Keep lock for reuse - don't delete self._connection_locks[alias]
        # Reusing locks avoids race where Thread A deletes lock while Thread B tries to acquire it
        # Note: Keep circuit breaker and health data for future connections

        account = self.config.get_account(alias)
        if account:
            account.status = AccountStatus.DISCONNECTED

        logger.debug(f"Disconnected and cleaned up resources for account '{alias}'")

    def _cleanup_stale_connection(self, alias: str):
        """Clean up a specific stale connection"""
        if alias in self._connection_timestamps:
            age_minutes = (time.time() - self._connection_timestamps[alias]) / 60
            if age_minutes > self._connection_ttl_minutes:
                logger.debug(
                    f"Cleaning up stale connection for '{alias}' (age: {age_minutes:.1f} min)"
                )
                self.disconnect_account(alias)
                return True
        return False

    def get_connection_health(self, alias: str) -> Optional[ConnectionHealth]:
        """Get connection health metrics for an account"""
        return self._connection_health.get(alias)

    def get_circuit_breaker_status(self, alias: str) -> Optional[CircuitBreakerState]:
        """Get circuit breaker status for an account"""
        breaker = self._circuit_breakers.get(alias)
        return breaker.state if breaker else None

    def cleanup_stale_connections(self, max_age_minutes: Optional[int] = None):
        """Remove connections older than max_age_minutes"""
        max_age = max_age_minutes or self._connection_ttl_minutes
        current_time = time.time()
        stale_aliases = []

        for alias, timestamp in self._connection_timestamps.items():
            age_minutes = (current_time - timestamp) / 60
            if age_minutes > max_age:
                stale_aliases.append(alias)

        for alias in stale_aliases:
            age_minutes = (current_time - self._connection_timestamps[alias]) / 60
            logger.debug(
                f"Cleaning up stale connection for account '{alias}' "
                f"(age: {age_minutes:.1f} minutes)"
            )
            self.disconnect_account(alias)

        if stale_aliases:
            logger.info(f"Cleaned up {len(stale_aliases)} stale connections")

    def _is_connection_stale(self, alias: str) -> bool:
        """Check if a connection is stale"""
        if alias not in self._connection_timestamps:
            return True

        age_minutes = (time.time() - self._connection_timestamps[alias]) / 60
        return age_minutes > self._connection_ttl_minutes

    def get_connection(self, alias: Optional[str] = None) -> Optional[DAVClient]:
        """Get connection for an account - internal utility method

        Thread-safe connection management with proper TOCTOU prevention.
        Staleness check MUST happen inside lock to prevent race conditions.

        De-masking note: this method is intentionally NOT wrapped in
        ``ErrorHandler.safe_operation(default_return=None)``. A slow iCloud
        cold-start connect raises inside ``connect_account`` (timeout / transient
        network error -> ``AccountConnectionError``); swallowing it to ``None``
        here surfaced one layer up as a misleading ``CalendarNotFoundError``.
        We now let ``connect_account``'s honest ``ChronosError`` (most often
        ``AccountConnectionError``, also ``AccountNotFoundError`` /
        ``AccountAuthenticationError``) propagate so the tool layer can return a
        retryable error instead of pretending the calendar is missing. ``None`` is
        returned ONLY for the genuine "no alias and no default account" case.
        """
        if not alias:
            alias = self.config.config.default_account

        if not alias:
            return None

        # Ensure lock exists before checking staleness
        if alias not in self._connection_locks:
            self._connection_locks[alias] = threading.Lock()

        with self._connection_locks[alias]:
            # Check staleness INSIDE lock to prevent TOCTOU race
            # Race scenario without this: Thread A checks stale=True outside lock,
            # Thread B connects, Thread A disconnects fresh connection
            if alias not in self.connections or self._is_connection_stale(alias):
                # Clean up stale connection if it exists
                if alias in self.connections:
                    logger.debug(f"Connection for '{alias}' is stale, reconnecting")
                    self.disconnect_account(alias)

                # Create new connection
                self.connect_account(alias)

        return self.connections.get(alias)

    def get_principal(self, alias: Optional[str] = None) -> Optional[Principal]:
        """Get principal for an account - internal utility method

        Thread-safe principal access with proper TOCTOU prevention.
        Staleness check MUST happen inside lock to prevent race conditions.

        De-masking note: like ``get_connection``, this method is intentionally
        NOT wrapped in ``ErrorHandler.safe_operation(default_return=None)``. The
        cold-start iCloud timeout is lost HERE (one layer below ``get_calendar``)
        when ``connect_account``'s ``AccountConnectionError`` is collapsed to
        ``None``. We let that honest error propagate; ``None`` is returned ONLY for
        the genuine "no alias and no default account" case.
        """
        if not alias:
            alias = self.config.config.default_account

        if not alias:
            return None

        # Ensure lock exists before checking staleness
        if alias not in self._connection_locks:
            self._connection_locks[alias] = threading.Lock()

        with self._connection_locks[alias]:
            # Check staleness INSIDE lock to prevent TOCTOU race
            # Same pattern as get_connection() for consistency
            if alias not in self.principals or self._is_connection_stale(alias):
                # Clean up stale connection if it exists
                if alias in self.principals:
                    logger.debug(f"Principal for '{alias}' is stale, reconnecting")
                    self.disconnect_account(alias)

                # Create new connection (also updates principals)
                self.connect_account(alias)

        return self.principals.get(alias)

    def test_account(self, alias: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        """Test account connectivity and return structured result"""
        result = {"alias": alias, "connected": False, "calendars": 0, "error": None}

        request_id = request_id or str(uuid.uuid4())

        try:
            if self.connect_account(alias, request_id=request_id):
                principal = self.principals.get(alias)
                if principal:
                    calendars = principal.calendars()
                    result["connected"] = True
                    result["calendars"] = len(calendars)
        except ChronosError as e:
            # Use sanitized error message for user response
            result["error"] = ErrorSanitizer.get_user_friendly_message(e)
            logger.error(f"Test account failed: {e}", extra={"request_id": request_id})
        except Exception as e:
            # Unexpected error - wrap and sanitize
            wrapped_error = AccountConnectionError(alias, original_error=e, request_id=request_id)
            result["error"] = ErrorSanitizer.get_user_friendly_message(wrapped_error)
            logger.error(
                f"Test account failed with unexpected error: {wrapped_error}",
                extra={"request_id": request_id},
            )

        return result
