"""
Tests for configuration validation
"""

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from chronos_mcp.config import ConfigManager


class TestConfigValidation:
    """Test configuration input validation"""

    @patch("chronos_mcp.config.get_credential_manager")
    @patch("os.getenv")
    def test_environment_password_validation(self, mock_getenv, mock_cred_manager):
        """Test that environment variable passwords are validated"""

        # Mock environment variables with control character in password
        def getenv_side_effect(key, default=None):
            env_vars = {
                "CALDAV_BASE_URL": "https://example.com",
                "CALDAV_USERNAME": "valid_user",
                "CALDAV_PASSWORD": "a" * 11000,  # Exceeds max length
            }
            return env_vars.get(key, default)

        mock_getenv.side_effect = getenv_side_effect
        mock_cred_manager.return_value.keyring_available = False

        with patch.object(Path, "exists", return_value=False):
            config_mgr = ConfigManager()

        # Default account should not be created due to validation failure
        assert "default" not in config_mgr.config.accounts

    @patch("chronos_mcp.config.get_credential_manager")
    @patch("os.getenv")
    def test_environment_username_validation(self, mock_getenv, mock_cred_manager):
        """Test that environment variable usernames are validated"""

        # Mock environment variables with XSS in username
        def getenv_side_effect(key, default=None):
            env_vars = {
                "CALDAV_BASE_URL": "https://example.com",
                "CALDAV_USERNAME": '<script>alert("xss")</script>',  # XSS
                "CALDAV_PASSWORD": "ValidPassword123",
            }
            return env_vars.get(key, default)

        mock_getenv.side_effect = getenv_side_effect
        mock_cred_manager.return_value.keyring_available = False

        with patch.object(Path, "exists", return_value=False):
            config_mgr = ConfigManager()

        # Default account should not be created
        assert "default" not in config_mgr.config.accounts

    @patch("chronos_mcp.config.get_credential_manager")
    @patch.dict(
        os.environ,
        {
            "CALDAV_BASE_URL": "https://example.com",
            "CALDAV_USERNAME": "valid_user",
            "CALDAV_PASSWORD": "ValidP@ssw0rd!",
        },
    )
    def test_environment_valid_credentials(self, mock_cred_manager):
        """Test that valid environment credentials are accepted"""
        mock_cred_mgr = Mock()
        mock_cred_mgr.keyring_available = False
        mock_cred_manager.return_value = mock_cred_mgr

        with patch.object(Path, "exists", return_value=False):
            config_mgr = ConfigManager()

        # Default account should be created with valid inputs
        assert "default" in config_mgr.config.accounts
        assert config_mgr.config.accounts["default"].username == "valid_user"
        assert config_mgr.config.accounts["default"].password == "ValidP@ssw0rd!"


class TestModelValidation:
    """Test Pydantic model-level validation (defense-in-depth)"""

    def test_account_model_password_validation(self):
        """Test that Account model validates password field"""
        from pydantic import ValidationError

        from chronos_mcp.models import Account

        # Test with oversized password - should be rejected by validator
        with pytest.raises(ValidationError) as exc_info:
            Account(
                alias="test",
                url="https://example.com",
                username="user",
                password="a" * 11000,  # Exceeds validation limit
                display_name="Test Account",
            )

        assert "CALDAV_PASSWORD" in str(exc_info.value) or "password" in str(exc_info.value).lower()

    def test_account_model_valid_password(self):
        """Test that Account model accepts valid passwords"""
        from chronos_mcp.models import Account

        # Valid password should pass
        account = Account(
            alias="test",
            url="https://example.com",
            username="user",
            password="ValidP@ssw0rd!123",
            display_name="Test Account",
        )

        assert account.password == "ValidP@ssw0rd!123"

    def test_account_model_none_password(self):
        """Test that Account model accepts None password (keyring scenario)"""
        from chronos_mcp.models import Account

        # None password should pass (for keyring usage)
        account = Account(
            alias="test",
            url="https://example.com",
            username="user",
            password=None,
            display_name="Test Account",
        )

        assert account.password is None
