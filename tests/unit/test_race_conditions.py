"""
Tests for concurrency and race conditions
"""

import threading
import time
from unittest.mock import Mock, patch

from chronos_mcp.accounts import AccountManager


class TestRaceConditions:
    """Test concurrent access patterns"""

    @patch("chronos_mcp.accounts.DAVClient")
    def test_concurrent_connection_requests_no_duplicate_disconnect(
        self, mock_dav_client, mock_config_manager, sample_account
    ):
        """Test that staleness check happens inside lock (TOCTOU prevention)

        Race condition scenario WITHOUT fix:
        1. Thread A checks _is_connection_stale (True) at line 320 OUTSIDE lock
        2. Thread B acquires lock at line 331, creates fresh connection
        3. Thread A acquires lock, checks stale at line 323 INSIDE lock (still True from step 1)
        4. Thread A disconnects fresh connection from step 2
        5. Thread A reconnects, but data race has occurred

        WITH fix: staleness check must happen INSIDE lock
        """
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)
        mgr._connection_ttl_minutes = 0.001  # Very short TTL

        # Mock connection
        call_count = [0]

        def create_mock_client(*args, **kwargs):
            call_count[0] += 1
            mock_client = Mock()
            mock_client.principal.return_value = Mock()
            # Add delay to increase race window
            time.sleep(0.01)
            return mock_client

        mock_dav_client.side_effect = create_mock_client

        # Create initial connection and make it stale
        mgr.connect_account("test_account")
        mgr._connection_timestamps["test_account"] = time.time() - 60

        # Track disconnect calls with timing
        disconnect_times = []
        connect_times = []
        original_disconnect = mgr.disconnect_account
        original_connect = mgr.connect_account

        def tracked_disconnect(alias):
            disconnect_times.append(time.time())
            return original_disconnect(alias)

        def tracked_connect(alias):
            connect_times.append(time.time())
            return original_connect(alias)

        mgr.disconnect_account = tracked_disconnect
        mgr.connect_account = tracked_connect

        # Force race: threads check stale outside lock
        barrier = threading.Barrier(3)  # Synchronize 3 threads

        def get_conn_with_timing():
            barrier.wait()  # All threads start simultaneously
            mgr.get_connection("test_account")

        threads = [threading.Thread(target=get_conn_with_timing) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # With race condition: multiple disconnects could happen
        # Proper fix: staleness check inside lock prevents this
        # This test documents the issue even if hard to trigger reliably
        assert (
            len(disconnect_times) <= 1
        ), f"Disconnect called {len(disconnect_times)} times - race detected"

    @patch("chronos_mcp.accounts.DAVClient")
    def test_connection_staleness_check_under_lock(
        self, mock_dav_client, mock_config_manager, sample_account
    ):
        """Test that staleness check happens inside lock to prevent TOCTOU"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        mock_client = Mock()
        mock_dav_client.return_value = mock_client
        mock_principal = Mock()
        mock_client.principal.return_value = mock_principal

        # Connect initially
        mgr.connect_account("test_account")

        # Make connection just barely not stale
        mgr._connection_timestamps["test_account"] = time.time() - (
            mgr._connection_ttl_minutes * 60 - 1
        )

        # Concurrent access shouldn't cause issues
        threads = [
            threading.Thread(target=lambda: mgr.get_connection("test_account")) for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should still have exactly one connection
        assert "test_account" in mgr.connections
        assert mgr.connections["test_account"] is not None

    @patch("chronos_mcp.accounts.DAVClient")
    def test_get_principal_concurrent_no_duplicate_disconnect(
        self, mock_dav_client, mock_config_manager, sample_account
    ):
        """Test that get_principal() prevents TOCTOU race same as get_connection()"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)
        mgr._connection_ttl_minutes = 0.001

        # Mock connection
        def create_mock_client(*args, **kwargs):
            mock_client = Mock()
            mock_client.principal.return_value = Mock()
            time.sleep(0.01)  # Increase race window
            return mock_client

        mock_dav_client.side_effect = create_mock_client

        # Create initial connection and make it stale
        mgr.connect_account("test_account")
        mgr._connection_timestamps["test_account"] = time.time() - 60

        # Track disconnect calls
        disconnect_times = []
        original_disconnect = mgr.disconnect_account

        def tracked_disconnect(alias):
            disconnect_times.append(time.time())
            return original_disconnect(alias)

        mgr.disconnect_account = tracked_disconnect

        # Force race with synchronized start
        barrier = threading.Barrier(3)

        def get_principal_with_timing():
            barrier.wait()  # All threads start simultaneously
            mgr.get_principal("test_account")

        threads = [threading.Thread(target=get_principal_with_timing) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should only disconnect once during reconnect
        assert (
            len(disconnect_times) <= 1
        ), f"Disconnect called {len(disconnect_times)} times - race detected"

    @patch("chronos_mcp.accounts.DAVClient")
    def test_mixed_connection_principal_access(
        self, mock_dav_client, mock_config_manager, sample_account
    ):
        """Test concurrent get_connection() and get_principal() don't interfere"""
        mock_config_manager.add_account(sample_account)
        mgr = AccountManager(mock_config_manager)

        mock_client = Mock()
        mock_dav_client.return_value = mock_client
        mock_principal = Mock()
        mock_client.principal.return_value = mock_principal

        results = {"connection": [], "principal": []}

        def get_conn():
            conn = mgr.get_connection("test_account")
            results["connection"].append(conn is not None)

        def get_princ():
            princ = mgr.get_principal("test_account")
            results["principal"].append(princ is not None)

        # Mix of connection and principal requests
        threads = []
        for i in range(10):
            if i % 2 == 0:
                threads.append(threading.Thread(target=get_conn))
            else:
                threads.append(threading.Thread(target=get_princ))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All requests should succeed
        assert all(results["connection"]), "Some connection requests failed"
        assert all(results["principal"]), "Some principal requests failed"
