"""
Unit tests for account management
"""

import time
from unittest.mock import Mock, patch

import pytest
from caldav.lib.error import AuthorizationError

from chronos_mcp.accounts import AccountManager, CircuitBreaker, CircuitBreakerState
from chronos_mcp.exceptions import (
    AccountAuthenticationError,
    AccountConnectionError,
    AccountNotFoundError,
)
from chronos_mcp.models import AccountStatus


class TestAccountManager:
    def test_init(self, mock_config_manager):
        """Test AccountManager initialization"""
        mgr = AccountManager(mock_config_manager)
        assert mgr.config == mock_config_manager
        assert mgr.connections == {}
        assert mgr.principals == {}

    def test_connect_account_not_found(self, mock_config_manager):
        """Test connecting to non-existent account"""
        # Use real config manager - account doesn't exist
        mgr = AccountManager(mock_config_manager)

        # Should raise AccountNotFoundError
        with pytest.raises(AccountNotFoundError) as exc_info:
            mgr.connect_account("nonexistent")

        assert "nonexistent" in str(exc_info.value)
        assert exc_info.value.details["alias"] == "nonexistent"

    @patch("chronos_mcp.accounts.DAVClient")
    def test_connect_account_success(self, mock_dav_client, mock_config_manager, sample_account):
        """Test successful connection to an account"""
        # Add account to config manager first
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Mock successful connection
        mock_client = Mock()
        mock_dav_client.return_value = mock_client
        mock_principal = Mock()
        mock_client.principal.return_value = mock_principal

        result = mgr.connect_account("test_account")
        assert result is True
        assert "test_account" in mgr.connections
        assert "test_account" in mgr.principals
        assert sample_account.status == AccountStatus.CONNECTED

    @patch("chronos_mcp.accounts.DAVClient")
    def test_connect_account_failure(self, mock_dav_client, mock_config_manager, sample_account):
        """Test connection failure"""
        # Add account to config manager first
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Mock connection failure
        mock_dav_client.side_effect = AuthorizationError("Invalid credentials")

        # Should raise AccountAuthenticationError
        with pytest.raises(AccountAuthenticationError) as exc_info:
            mgr.connect_account("test_account")

        assert exc_info.value.details["alias"] == "test_account"
        assert sample_account.status == AccountStatus.ERROR

    def test_disconnect_account(self, mock_config_manager, sample_account):
        """Test disconnecting an account"""
        # Add account to config manager first
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Simulate connected account
        mgr.connections["test_account"] = Mock()
        mgr.principals["test_account"] = Mock()

        mgr.disconnect_account("test_account")
        assert "test_account" not in mgr.connections
        assert "test_account" not in mgr.principals
        assert sample_account.status == AccountStatus.DISCONNECTED

    def test_get_connection_not_connected(self, mock_config_manager, sample_account):
        """Test getting connection when not connected - should auto-connect"""
        mock_config_manager.config.default_account = None
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Mock connect_account to fail
        with patch.object(mgr, "connect_account", return_value=False):
            connection = mgr.get_connection("test_account")
            assert connection is None

    @patch("chronos_mcp.accounts.DAVClient")
    def test_test_account(self, mock_dav_client, mock_config_manager, sample_account):
        """Test testing account connectivity"""
        # Add account to config manager first
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Mock successful connection
        mock_client = Mock()
        mock_dav_client.return_value = mock_client
        mock_principal = Mock()
        mock_client.principal.return_value = mock_principal
        mock_calendars = [Mock(), Mock()]
        mock_principal.calendars.return_value = mock_calendars

        result = mgr.test_account("test_account")
        assert result["alias"] == "test_account"
        assert result["connected"] is True
        assert result["calendars"] == 2
        assert result["error"] is None

    def test_get_principal(self, mock_config_manager):
        """Test getting principal for an account"""
        mgr = AccountManager(mock_config_manager)

        # De-mask: a request for an account that isn't configured propagates an
        # honest AccountNotFoundError from connect_account (it is NOT swallowed to
        # None by safe_operation anymore).
        with pytest.raises(AccountNotFoundError):
            mgr.get_principal("nonexistent")

        # Should return principal when already connected (cached)
        mock_principal = Mock()
        mgr.principals["test_account"] = mock_principal
        # Add timestamp to prevent stale connection check
        mgr._connection_timestamps["test_account"] = time.time()

        principal = mgr.get_principal("test_account")
        assert principal == mock_principal

    def test_get_principal_no_alias_no_default_returns_none(self, mock_config_manager):
        """get_principal returns None ONLY for the genuine no-alias/no-default case."""
        mock_config_manager.config.default_account = None
        mgr = AccountManager(mock_config_manager)

        # No alias passed and no default account configured -> honest None.
        assert mgr.get_principal() is None

    def test_get_principal_connection_failure_propagates(
        self, mock_config_manager, sample_account
    ):
        """De-mask PRIMARY fix: a connect timeout surfaces as AccountConnectionError.

        Previously the @safe_operation(default_return=None) decorator swallowed the
        timeout to None one layer below get_calendar, which then looked like a
        CalendarNotFoundError. It must now propagate.
        """
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Simulate a cold-start connect timeout: DAVClient construction raises a
        # transient (non-auth) error on every retry.
        with patch("chronos_mcp.accounts.DAVClient") as mock_dav_client:
            with patch("time.sleep"):  # don't actually back off
                mock_dav_client.side_effect = TimeoutError("connection timed out")

                with pytest.raises(AccountConnectionError) as exc_info:
                    mgr.get_principal("test_account")

        assert exc_info.value.details["alias"] == "test_account"
        # The principal was NOT silently cached/None'd.
        assert "test_account" not in mgr.principals

    def test_get_connection_connection_failure_propagates(
        self, mock_config_manager, sample_account
    ):
        """De-mask: get_connection also propagates the honest AccountConnectionError."""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        with patch("chronos_mcp.accounts.DAVClient") as mock_dav_client:
            with patch("time.sleep"):
                mock_dav_client.side_effect = TimeoutError("connection timed out")

                with pytest.raises(AccountConnectionError):
                    mgr.get_connection("test_account")

    def test_get_connection_no_alias_no_default_returns_none(self, mock_config_manager):
        """get_connection returns None ONLY for the genuine no-alias/no-default case."""
        mock_config_manager.config.default_account = None
        mgr = AccountManager(mock_config_manager)

        assert mgr.get_connection() is None

    @patch("chronos_mcp.accounts.DAVClient")
    def test_get_connection_with_default(
        self, mock_dav_client, mock_config_manager, sample_account
    ):
        """Test getting connection uses default account when no alias provided"""
        # Set up default account
        mock_config_manager.add_account(sample_account)
        mock_config_manager.config.default_account = "test_account"

        mgr = AccountManager(mock_config_manager)

        # Mock successful connection
        mock_client = Mock()
        mock_dav_client.return_value = mock_client
        mock_principal = Mock()
        mock_client.principal.return_value = mock_principal

        # Get connection without specifying alias
        mgr.get_connection()

        # Should have connected to default account
        assert "test_account" in mgr.connections

    def test_circuit_breaker_functionality(self, mock_config_manager, sample_account):
        """Test circuit breaker opens after repeated failures"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Trigger multiple failures to open circuit breaker
        with patch("chronos_mcp.accounts.DAVClient") as mock_dav_client:
            mock_dav_client.side_effect = Exception("Connection failed")

            # Try to connect multiple times to trigger circuit breaker
            for _ in range(6):  # Exceeds failure threshold of 5
                try:
                    mgr.connect_account("test_account")
                except AccountConnectionError:
                    pass

            # Circuit breaker should be OPEN
            breaker_state = mgr.get_circuit_breaker_status("test_account")
            assert breaker_state == CircuitBreakerState.OPEN

            # Next connection attempt should be rejected immediately
            with pytest.raises(AccountConnectionError) as exc_info:
                mgr.connect_account("test_account")
            # Check that the error details contain the circuit breaker message
            assert "Circuit breaker is OPEN" in exc_info.value.details.get("original_error", "")

    def test_connection_health_tracking(self, mock_config_manager, sample_account):
        """Test connection health metrics are tracked"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Test successful connection updates health
        with patch("chronos_mcp.accounts.DAVClient") as mock_dav_client:
            mock_client = Mock()
            mock_dav_client.return_value = mock_client
            mock_principal = Mock()
            mock_client.principal.return_value = mock_principal

            mgr.connect_account("test_account")

            health = mgr.get_connection_health("test_account")
            assert health is not None
            assert health.total_attempts == 1
            assert health.successful_connections == 1
            assert health.failed_connections == 0
            assert health.success_rate == 1.0

    def test_connection_retry_logic(self, mock_config_manager, sample_account):
        """Test connection retry with exponential backoff"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)
        mgr._max_retries = 3

        call_count = 0

        def mock_dav_client_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:  # Fail first 2 attempts
                raise Exception("Temporary failure")
            # Succeed on 3rd attempt
            mock_client = Mock()
            mock_client.principal.return_value = Mock()
            return mock_client

        with patch("chronos_mcp.accounts.DAVClient", side_effect=mock_dav_client_side_effect):
            with patch("time.sleep") as mock_sleep:  # Mock sleep for testing
                result = mgr.connect_account("test_account")

                assert result is True
                assert call_count == 3  # Should have retried
                assert mock_sleep.call_count == 2  # 2 sleeps before success

    def test_connection_timeout_configuration(self, mock_config_manager, sample_account):
        """Test connection timeout is properly configured"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        with patch("chronos_mcp.accounts.DAVClient") as mock_dav_client:
            mock_client = Mock()
            mock_dav_client.return_value = mock_client
            mock_principal = Mock()
            mock_client.principal.return_value = mock_principal

            mgr.connect_account("test_account")

            # Verify DAVClient was called with timeout
            mock_dav_client.assert_called_with(
                url=str(sample_account.url),
                username=sample_account.username,
                password=sample_account.password,
                timeout=30,  # Default timeout
            )

    def test_password_validation_in_add_account(self):
        """Test that password is validated when adding an account"""
        from chronos_mcp.exceptions import ValidationError
        from chronos_mcp.validation import InputValidator

        # Test with control characters in password - should be rejected
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_text_field("pass\x00word", "password", required=True)
        assert "potentially dangerous content" in str(exc_info.value).lower()

        # Test with excessively long password - should be rejected
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_text_field("a" * 11000, "password", required=True)
        assert "maximum" in str(exc_info.value).lower()

        # Test with valid password - should pass
        result = InputValidator.validate_text_field("ValidP@ssw0rd!", "password", required=True)
        assert result == "ValidP@ssw0rd!"

    @patch("chronos_mcp.tools.accounts._managers")
    def test_add_account_validates_password(self, mock_managers_dict, mock_config_manager):
        """Test that add_account tool validates password input"""
        import asyncio

        from chronos_mcp.tools.accounts import add_account

        # Setup managers
        mock_managers_dict.__getitem__.return_value = mock_config_manager
        mock_account_manager = Mock()
        mock_account_manager.test_account.return_value = {
            "alias": "test",
            "connected": True,
            "calendars": 2,
            "error": None,
        }

        def manager_getter(key):
            if key == "config_manager":
                return mock_config_manager
            elif key == "account_manager":
                return mock_account_manager
            raise KeyError(key)

        mock_managers_dict.__getitem__.side_effect = manager_getter

        # Test with invalid password (control character)
        # The decorator catches exceptions and returns error dict
        result = asyncio.run(
            add_account(
                alias="test",
                url="https://example.com",
                username="user",
                password="pass\x00word",  # Null byte
                allow_local=True,
            )
        )

        # Should return error response
        assert result["success"] is False
        assert "error_code" in result
        assert result["error_code"] == "ValidationError"
        assert "dangerous content" in result["error"].lower()

    def test_circuit_breaker_recovery(self, mock_config_manager, sample_account):
        """Test circuit breaker transitions to HALF_OPEN after recovery timeout"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        # Manually create and configure circuit breaker for testing
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        mgr._circuit_breakers["test_account"] = breaker

        # Trigger failures to open circuit breaker
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

        # Initially should not allow requests
        assert not breaker.should_allow_request()

        # Fast-forward time past recovery timeout
        breaker.last_failure_time = time.time() - 2  # 2 seconds ago

        # Should now allow request (HALF_OPEN)
        assert breaker.should_allow_request()
        assert breaker.state == CircuitBreakerState.HALF_OPEN

        # Successful operation should close circuit
        breaker.record_success()
        assert breaker.state == CircuitBreakerState.CLOSED

    @patch("chronos_mcp.accounts.DAVClient")
    def test_cleanup_stale_connection(self, mock_dav_client, mock_config_manager, sample_account):
        """Test cleanup of stale connections"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)
        mgr._connection_ttl_minutes = 0.01  # Very short TTL for testing

        # Mock successful connection
        mock_client = Mock()
        mock_dav_client.return_value = mock_client
        mock_principal = Mock()
        mock_client.principal.return_value = mock_principal

        # Connect and then wait for it to become stale
        mgr.connect_account("test_account")
        assert "test_account" in mgr.connections

        # Make connection timestamp old
        mgr._connection_timestamps["test_account"] = time.time() - 60  # 1 minute ago

        # Cleanup should remove stale connection
        result = mgr._cleanup_stale_connection("test_account")
        assert result is True
        assert "test_account" not in mgr.connections
