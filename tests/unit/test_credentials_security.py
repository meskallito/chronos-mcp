"""
Security-focused tests for credential management
"""

import logging
from unittest.mock import patch

from chronos_mcp.credentials import CredentialManager


class TestCredentialSecurity:
    """Test security aspects of credential management"""

    def test_no_password_info_in_debug_logs(self, caplog):
        """Test that password information is redacted in debug logs"""
        # Test with keyring available
        with patch("chronos_mcp.credentials.keyring") as mock_keyring:
            mock_keyring.get_password.return_value = "test_password"

            manager = CredentialManager()
            manager.keyring_available = True

            with caplog.at_level(logging.DEBUG):
                password = manager.get_password("test_alias")

            # Check that debug log doesn't contain actual alias
            debug_logs = [
                record.message for record in caplog.records if record.levelname == "DEBUG"
            ]
            assert any("[REDACTED]" in log for log in debug_logs)
            assert not any("test_alias" in log for log in debug_logs)
            assert password == "test_password"

    def test_no_password_info_in_fallback_logs(self, caplog):
        """Test that fallback password logs are redacted"""
        manager = CredentialManager()
        manager.keyring_available = False

        with caplog.at_level(logging.DEBUG):
            password = manager.get_password("test_alias", fallback_password="fallback_pass")

        # Check that debug log doesn't contain actual alias
        debug_logs = [record.message for record in caplog.records if record.levelname == "DEBUG"]
        assert any("[REDACTED]" in log for log in debug_logs)
        assert not any("test_alias" in log for log in debug_logs)
        assert password == "fallback_pass"

    def test_no_password_info_in_store_logs(self, caplog):
        """Test that password storage logs are redacted"""
        with patch("chronos_mcp.credentials.keyring") as mock_keyring:
            mock_keyring.set_password.return_value = None

            manager = CredentialManager()
            manager.keyring_available = True

            with caplog.at_level(logging.INFO):
                result = manager.set_password("test_alias", "secret_password")

            # Check that info log doesn't contain actual alias
            info_logs = [record.message for record in caplog.records if record.levelname == "INFO"]
            assert any("[REDACTED]" in log for log in info_logs)
            assert not any("test_alias" in log for log in info_logs)
            assert result is True

    def test_no_password_info_in_delete_logs(self, caplog):
        """Test that password deletion logs are redacted"""
        with patch("chronos_mcp.credentials.keyring") as mock_keyring:
            mock_keyring.delete_password.return_value = None

            manager = CredentialManager()
            manager.keyring_available = True

            with caplog.at_level(logging.INFO):
                result = manager.delete_password("test_alias")

            # Check logs don't contain actual alias
            info_logs = [record.message for record in caplog.records if record.levelname == "INFO"]
            assert any("[REDACTED]" in log for log in info_logs)
            assert not any("test_alias" in log for log in info_logs)
            assert result is True

    def test_no_password_info_in_debug_delete_logs(self, caplog):
        """Test that debug deletion logs are redacted"""
        with (
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
            patch("chronos_mcp.credentials.keyring.errors") as mock_errors,
        ):
            # Create a proper PasswordDeleteError exception
            class MockPasswordDeleteError(Exception):
                pass

            mock_errors.PasswordDeleteError = MockPasswordDeleteError

            # Make delete_password raise the exception
            mock_keyring.delete_password.side_effect = MockPasswordDeleteError()

            manager = CredentialManager()
            manager.keyring_available = True

            with caplog.at_level(logging.DEBUG):
                result = manager.delete_password("test_alias")

            # Check that debug log doesn't contain actual alias
            debug_logs = [
                record.message for record in caplog.records if record.levelname == "DEBUG"
            ]
            assert any("[REDACTED]" in log for log in debug_logs)
            assert not any("test_alias" in log for log in debug_logs)
            assert result is False

    def test_no_password_info_when_keyring_unavailable(self, caplog):
        """Test redacted logs when keyring is unavailable"""
        manager = CredentialManager()
        manager.keyring_available = False

        with caplog.at_level(logging.DEBUG):
            result = manager.set_password("test_alias", "secret_password")

        # Check that debug log doesn't contain actual alias
        debug_logs = [record.message for record in caplog.records if record.levelname == "DEBUG"]
        assert any("[REDACTED]" in log for log in debug_logs)
        assert not any("test_alias" in log for log in debug_logs)
        assert result is False

    def test_password_never_logged_directly(self, caplog):
        """Test that actual passwords are never logged anywhere"""
        with patch("chronos_mcp.credentials.keyring") as mock_keyring:
            mock_keyring.get_password.return_value = "supersecret123"
            mock_keyring.set_password.return_value = None
            mock_keyring.delete_password.return_value = None

            manager = CredentialManager()
            manager.keyring_available = True

            # Capture all log levels
            with caplog.at_level(logging.DEBUG):
                manager.get_password("test_alias")
                manager.set_password("test_alias", "supersecret123")
                manager.delete_password("test_alias")

            # Check that password never appears in any log
            all_logs = [record.message for record in caplog.records]
            assert not any("supersecret123" in log for log in all_logs)
            assert not any(
                "secret" in log.lower() for log in all_logs if "supersecret123" not in log
            )

    def test_alias_never_logged_in_password_context(self, caplog):
        """Test that aliases never appear in password-related logs"""
        sensitive_alias = "production_admin_account"

        with patch("chronos_mcp.credentials.keyring") as mock_keyring:
            mock_keyring.get_password.return_value = "password123"

            manager = CredentialManager()
            manager.keyring_available = True

            with caplog.at_level(logging.DEBUG):
                manager.get_password(sensitive_alias)

            # Check that sensitive alias never appears in logs
            all_logs = [record.message for record in caplog.records]
            assert not any(sensitive_alias in log for log in all_logs)
            assert any("[REDACTED]" in log for log in all_logs)
