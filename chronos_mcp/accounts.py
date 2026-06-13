"""
Account management for Chronos MCP
"""

import socket
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, Type, TypeVar

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

T = TypeVar("T")


def _http_backend_stale_types() -> Tuple[Type[BaseException], ...]:
    """Collect the HTTP backend's ConnectionError/Timeout exception classes.

    caldav's HTTP backend differs by version: caldav>=3 uses ``niquests`` (a
    requests-compatible fork), older caldav uses ``requests``. The slim
    production image ships ONLY the backend caldav actually depends on, so we
    must NOT hard-import either — we import whichever is present (best-effort)
    and fall back to a class-name heuristic for any we miss. (A hard
    ``import requests`` here previously crashed the caldav>=3 production image,
    which has niquests but not requests.)
    """
    types: list = []
    for mod_name in ("niquests", "requests"):
        try:
            exc_mod = __import__(f"{mod_name}.exceptions", fromlist=["exceptions"])
        except Exception:  # noqa: BLE001 - backend simply not installed
            continue
        for attr in ("ConnectionError", "Timeout", "ChunkedEncodingError"):
            cls = getattr(exc_mod, attr, None)
            if isinstance(cls, type):
                types.append(cls)
    return tuple(types)


# Resolved once at import. Note: do NOT add bare socket.error / OSError —
# OSError subclasses like PermissionError(403)/FileNotFoundError are NOT socket
# rot and must not trigger a reconnect+retry. The builtin ConnectionError covers
# the real dead-socket cases (BrokenPipeError/ConnectionResetError/
# ConnectionAbortedError); socket.timeout covers raw socket read timeouts.
_STALE_TYPES: Tuple[Type[BaseException], ...] = _http_backend_stale_types() + (
    ConnectionError,  # builtin
    socket.timeout,
)


def _is_stale_connection_error(exc: BaseException) -> bool:
    """Heuristic: does this exception look like a dead/stale TCP socket?

    iCloud (caldav.icloud.com) silently drops idle keep-alive connections after
    ~15-20 s. The python caldav/niquests/urllib3 stack does NOT detect the dead
    socket: the next CalDAV op hangs for the full read timeout and then surfaces
    as a backend ``Timeout`` / ``ConnectionError`` (or a raw socket error). We
    treat those as healable: evict the cached client + reconnect (a fresh
    DAVClient reads iCloud in ~0.4 s) and retry once. We deliberately do NOT
    treat auth/HTTP-status errors as stale (those are real, not socket rot).

    Matches both by class (``_STALE_TYPES``) and, as a backend-agnostic safety
    net, by module+name heuristic (``<backend>.exceptions`` + the name mentions
    Timeout/ConnectionError) — so a backend we couldn't import still heals.
    Walks the ``__cause__``/``__context__`` chain because caldav often wraps the
    underlying transport error inside its own DAVError.
    """
    seen = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, _STALE_TYPES):
            return True
        mod = type(cur).__module__ or ""
        name = type(cur).__name__
        if mod.endswith("exceptions") and (
            "ConnectionError" in name or "Timeout" in name or "ChunkedEncoding" in name
        ):
            return True
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return False


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

        # Idle-staleness guard (the iCloud idle-drop fix). iCloud silently drops
        # idle keep-alive sockets after ~15-20 s; the python stack does NOT detect
        # the dead socket and the next op hangs for the FULL read timeout before
        # the reactive heal can even fire (measured: a ~30 s hang then recover).
        # So we PROACTIVELY reconnect (cheap: ~0.4 s for a fresh DAVClient, ~ms for
        # local Radicale) when the cached connection has been idle longer than this
        # threshold — preempting the dead-socket hang entirely. Reactive heal stays
        # as the safety net for an unexpected drop INSIDE the threshold. Tracked by
        # last *activity* (not connect) time so an actively-used connection is never
        # needlessly recycled. 0 disables the proactive guard.
        self._idle_reconnect_seconds: float = 10.0
        self._last_activity: Dict[str, float] = {}

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
                # Seed last-activity so a freshly-connected-but-then-idle socket is
                # still caught by the proactive idle-staleness reconnect.
                self._last_activity[alias] = time.time()

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
        if alias in self._last_activity:
            del self._last_activity[alias]
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

    def _force_reconnect(self, alias: str, request_id: Optional[str] = None) -> Principal:
        """Evict the cached (stale) connection for ``alias`` and reconnect.

        Used by the reactive-heal path. Acquires the per-alias lock so an evict +
        reconnect is atomic w.r.t. ``get_connection``/``get_principal``. Returns
        the freshly-connected principal.
        """
        if alias not in self._connection_locks:
            self._connection_locks[alias] = threading.Lock()
        with self._connection_locks[alias]:
            if alias in self.connections or alias in self.principals:
                logger.info(
                    f"Evicting stale cached connection for '{alias}' and reconnecting",
                    extra={"request_id": request_id},
                )
                self.disconnect_account(alias)
            self.connect_account(alias, request_id=request_id)
        principal = self.principals.get(alias)
        if principal is None:  # pragma: no cover - connect_account raises on failure
            raise AccountConnectionError(alias, request_id=request_id)
        return principal

    def _is_connection_idle_stale(self, alias: str) -> bool:
        """Has the cached connection been idle longer than the idle threshold?

        Targets the iCloud idle-drop: a connection unused for more than
        ``_idle_reconnect_seconds`` is assumed to have a dead socket and should be
        proactively recycled (cheap) rather than hung on (the full read timeout).
        Returns False when the guard is disabled (threshold <= 0) or the
        connection was used recently.
        """
        if self._idle_reconnect_seconds <= 0:
            return False
        last = self._last_activity.get(alias)
        if last is None:
            return False
        return (time.time() - last) > self._idle_reconnect_seconds

    def execute_with_reconnect(
        self,
        operation: Callable[[Principal], T],
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> T:
        """Run a CalDAV ``operation`` against the account's principal, healing a
        stale cached connection ONCE.

        ``operation`` receives the (cached, warm) ``Principal`` and performs the
        actual CalDAV round-trip(s) — e.g. ``principal.calendars()`` then
        ``calendar.date_search(...)``. On the warm path this is a single call and
        does NOT reconnect (no perf regression). If the operation raises an error
        that looks like a dead/stale socket (see ``_is_stale_connection_error`` —
        the iCloud idle-drop failure mode), we evict the cached client, reconnect
        (~0.4 s for a fresh DAVClient), re-run ``operation`` with the FRESH
        principal exactly once, and return its result.

        Combined strategy (approach A reactive-heal + approach c idle-TTL):
          - PROACTIVE: if the cached connection has been idle past
            ``_idle_reconnect_seconds`` we reconnect BEFORE running the op. This is
            the primary iCloud fix — a dead idle socket otherwise hangs for the
            full read timeout (~30 s) BEFORE the reactive heal can fire; preempting
            it costs only ~0.4 s (a fresh DAVClient). For local Radicale the
            reconnect is ~ms, so this does not meaningfully regress it.
          - REACTIVE: if the op still raises a dead-socket error (an unexpected
            drop INSIDE the idle window), we evict + reconnect + retry ONCE.
          - WARM: a recently-used connection runs the op directly with no
            reconnect (no perf regression).

        Why not disable keep-alive entirely: that would add ~0.4 s to EVERY call
        including Radicale's fast local reads. The idle-TTL keeps the warm-path
        cache fast and pays the reconnect only after an actual idle gap.

        Bounded to a single reactive retry: a persistent failure re-raises honestly
        (an ``AccountConnectionError`` from ``connect_account`` if the reconnect
        itself fails, else the operation's own error) — never an infinite loop,
        never a masked ``None``/empty result (preserves the de-mask invariant).
        """
        request_id = request_id or str(uuid.uuid4())
        alias = account_alias or self.config.config.default_account

        # PROACTIVE idle-staleness reconnect (the iCloud idle-drop preempt).
        if alias and alias in self.connections and self._is_connection_idle_stale(alias):
            idle = time.time() - self._last_activity.get(alias, 0)
            logger.info(
                f"Connection for '{alias}' idle {idle:.0f}s (> "
                f"{self._idle_reconnect_seconds:.0f}s) — proactively reconnecting "
                f"to avoid a stale-socket hang",
                extra={"request_id": request_id},
            )
            self._force_reconnect(alias, request_id=request_id)

        principal = self.get_principal(account_alias)
        if principal is None:
            # No alias and no default account — honest, non-retryable.
            raise AccountNotFoundError(alias or "default", request_id=request_id)

        try:
            result = operation(principal)
            if alias:
                self._last_activity[alias] = time.time()
            return result
        except Exception as exc:  # noqa: BLE001 - re-raised below if not healable
            if not (alias and _is_stale_connection_error(exc)):
                raise
            logger.warning(
                f"CalDAV operation on '{alias}' failed with a stale-connection error "
                f"({type(exc).__name__}); evicting + reconnecting and retrying once",
                extra={"request_id": request_id},
            )
            # _force_reconnect raises AccountConnectionError if the reconnect fails;
            # that honest error propagates (we do NOT mask it).
            fresh_principal = self._force_reconnect(alias, request_id=request_id)
            result = operation(fresh_principal)
            self._last_activity[alias] = time.time()
            return result

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
