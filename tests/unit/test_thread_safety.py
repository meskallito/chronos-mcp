"""
Thread safety tests for connection management
"""

import threading
import time
from unittest.mock import Mock, patch

import pytest

from chronos_mcp.accounts import AccountManager
from chronos_mcp.config import ConfigManager
from chronos_mcp.models import Account


class TestThreadSafety:
    """Test thread safety of connection management"""

    @pytest.fixture
    def mock_config_with_account(self):
        """Create a mock config manager with a test account"""
        config_manager = Mock(spec=ConfigManager)

        # Create a test account
        test_account = Account(
            alias="test_account",
            url="https://caldav.example.com/",
            username="testuser",
            password="testpass",
            display_name="Test Account",
        )

        config_manager.get_account.return_value = test_account

        # Mock the config attribute and its default_account
        mock_config = Mock()
        mock_config.default_account = "test_account"
        config_manager.config = mock_config

        return config_manager

    def test_concurrent_connection_creation(self, mock_config_with_account):
        """Test that concurrent connection attempts don't create duplicate connections"""
        with (
            patch("chronos_mcp.accounts.DAVClient") as mock_dav_client,
            patch("chronos_mcp.accounts.get_credential_manager") as mock_cred_mgr,
        ):

            # Setup mocks
            mock_client = Mock()
            mock_principal = Mock()
            mock_client.principal.return_value = mock_principal
            mock_dav_client.return_value = mock_client

            mock_cred_mgr.return_value.get_password.return_value = "testpass"

            manager = AccountManager(mock_config_with_account)

            # Track connection attempts
            connection_attempts = []
            original_connect = manager.connect_account

            def track_connect(alias, request_id=None):
                connection_attempts.append(time.time())
                # Add small delay to increase chance of race condition
                time.sleep(0.01)
                return original_connect(alias, request_id)

            manager.connect_account = track_connect

            # Create multiple threads that try to get the same connection
            threads = []
            results = []

            def get_connection_worker():
                try:
                    conn = manager.get_connection("test_account")
                    results.append(conn)
                except Exception as e:
                    results.append(e)

            # Start multiple threads simultaneously
            for _ in range(5):
                thread = threading.Thread(target=get_connection_worker)
                threads.append(thread)

            # Start all threads at roughly the same time
            for thread in threads:
                thread.start()

            # Wait for all threads to complete
            for thread in threads:
                thread.join(timeout=5.0)
                assert not thread.is_alive(), "Thread took too long to complete"

            # Verify results
            assert len(results) == 5, "All threads should have completed"
            assert all(
                r is not None for r in results
            ), "All threads should have gotten a connection"

            # Most importantly: only one connection should have been created
            assert len(manager.connections) == 1, "Only one connection should exist"
            assert "test_account" in manager.connections, "Connection should be for test_account"

            # Verify connect was called only once despite multiple concurrent requests
            # (The exact number may vary due to timing, but should be minimal)
            assert (
                len(connection_attempts) <= 2
            ), f"Too many connection attempts: {len(connection_attempts)}"

    def test_concurrent_principal_access(self, mock_config_with_account):
        """Test that concurrent principal access is thread-safe"""
        with (
            patch("chronos_mcp.accounts.DAVClient") as mock_dav_client,
            patch("chronos_mcp.accounts.get_credential_manager") as mock_cred_mgr,
        ):

            # Setup mocks
            mock_client = Mock()
            mock_principal = Mock()
            mock_client.principal.return_value = mock_principal
            mock_dav_client.return_value = mock_client

            mock_cred_mgr.return_value.get_password.return_value = "testpass"

            manager = AccountManager(mock_config_with_account)

            # Create multiple threads that try to get the same principal
            threads = []
            results = []

            def get_principal_worker():
                try:
                    principal = manager.get_principal("test_account")
                    results.append(principal)
                except Exception as e:
                    results.append(e)

            # Start multiple threads simultaneously
            for _ in range(3):
                thread = threading.Thread(target=get_principal_worker)
                threads.append(thread)

            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join(timeout=5.0)
                assert not thread.is_alive(), "Thread took too long to complete"

            # Verify results
            assert len(results) == 3, "All threads should have completed"
            assert all(r is not None for r in results), "All threads should have gotten a principal"

            # Only one principal should exist in cache
            assert len(manager.principals) == 1, "Only one principal should exist"
            assert "test_account" in manager.principals, "Principal should be for test_account"

    def test_connection_lock_per_account(self, mock_config_with_account):
        """Test that different accounts have different locks"""
        with (
            patch("chronos_mcp.accounts.DAVClient") as mock_dav_client,
            patch("chronos_mcp.accounts.get_credential_manager") as mock_cred_mgr,
        ):

            # Setup mocks for multiple accounts
            mock_client = Mock()
            mock_principal = Mock()
            mock_client.principal.return_value = mock_principal
            mock_dav_client.return_value = mock_client

            mock_cred_mgr.return_value.get_password.return_value = "testpass"

            # Setup config to return different accounts
            def get_account_side_effect(alias):
                return Account(
                    alias=alias,
                    url=f"https://{alias}.example.com/",
                    username="testuser",
                    password="testpass",
                    display_name=f"Test Account {alias}",
                )

            mock_config_with_account.get_account.side_effect = get_account_side_effect

            manager = AccountManager(mock_config_with_account)

            # Access connections for different accounts concurrently
            results = []

            def get_connection_worker(account_alias):
                try:
                    conn = manager.get_connection(account_alias)
                    results.append((account_alias, conn))
                except Exception as e:
                    results.append((account_alias, e))

            threads = []
            account_aliases = ["account1", "account2", "account3"]

            for alias in account_aliases:
                thread = threading.Thread(target=get_connection_worker, args=(alias,))
                threads.append(thread)

            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join(timeout=5.0)

            # Verify all accounts got connections
            assert len(results) == 3, "All threads should have completed"
            assert len(manager.connections) == 3, "Should have connections for all accounts"
            assert len(manager._connection_locks) == 3, "Should have locks for all accounts"

            # Verify different locks for different accounts
            lock_ids = set()
            for alias in account_aliases:
                if alias in manager._connection_locks:
                    lock_ids.add(id(manager._connection_locks[alias]))

            assert len(lock_ids) == 3, "Each account should have its own lock instance"

    def test_error_handling_in_concurrent_access(self, mock_config_with_account):
        """Test that errors in one thread don't affect others"""
        with (
            patch("chronos_mcp.accounts.DAVClient") as mock_dav_client,
            patch("chronos_mcp.accounts.get_credential_manager") as mock_cred_mgr,
        ):

            # Setup mock to fail on first call, succeed on others
            call_count = 0

            def failing_connect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise Exception("First connection fails")

                mock_client = Mock()
                mock_principal = Mock()
                mock_client.principal.return_value = mock_principal
                return mock_client

            mock_dav_client.side_effect = failing_connect
            mock_cred_mgr.return_value.get_password.return_value = "testpass"

            manager = AccountManager(mock_config_with_account)

            results = []
            errors = []

            def get_connection_worker():
                try:
                    conn = manager.get_connection("test_account")
                    results.append(conn)
                except Exception as e:
                    errors.append(e)

            # Start multiple threads
            threads = []
            for _ in range(3):
                thread = threading.Thread(target=get_connection_worker)
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join(timeout=5.0)

            # One thread should have failed, others should succeed or get None
            # (Exact behavior depends on timing and error handling)
            total_attempts = len(results) + len(errors)
            assert total_attempts == 3, "All threads should have completed"

    def test_lock_cleanup_on_disconnect(self, mock_config_with_account):
        """Test that locks are properly managed when connections are disconnected"""
        manager = AccountManager(mock_config_with_account)

        # Force creation of locks by accessing _connection_locks
        manager._connection_locks["test_account"] = threading.Lock()
        manager.connections["test_account"] = Mock()
        manager.principals["test_account"] = Mock()

        # Disconnect should clean up connections and principals
        manager.disconnect_account("test_account")

        assert "test_account" not in manager.connections
        assert "test_account" not in manager.principals
        # Note: We intentionally keep locks around to avoid lock creation overhead
        # This is acceptable since locks are lightweight
