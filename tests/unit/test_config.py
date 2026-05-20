"""
Unit tests for configuration management
"""

import pytest

from chronos_mcp.config import ChronosConfig, ConfigManager
from chronos_mcp.models import Account


class TestConfigManager:
    def test_config_init(self, mock_config_manager):
        """Test ConfigManager initialization"""
        # The config_dir is set but not necessarily created until save
        assert mock_config_manager.config_dir.name == ".chronos"
        assert mock_config_manager.config_file.name == "accounts.json"
        assert isinstance(mock_config_manager.config, ChronosConfig)

    def test_add_account(self, mock_config_manager, sample_account):
        """Test adding an account"""
        mock_config_manager.add_account(sample_account)
        assert "test_account" in mock_config_manager.config.accounts
        assert mock_config_manager.config.accounts["test_account"].username == "testuser"
        # Should be set as default if it's the first account
        assert mock_config_manager.config.default_account == "test_account"

    def test_remove_account(self, mock_config_manager, sample_account):
        """Test removing an account"""
        mock_config_manager.add_account(sample_account)
        mock_config_manager.remove_account("test_account")
        assert "test_account" not in mock_config_manager.config.accounts
        assert mock_config_manager.config.default_account is None

    def test_get_account(self, mock_config_manager, sample_account):
        """Test getting an account"""
        mock_config_manager.add_account(sample_account)
        account = mock_config_manager.get_account("test_account")
        assert account.username == "testuser"

    def test_get_default_account(self, mock_config_manager, sample_account):
        """Test getting default account when no alias specified"""
        mock_config_manager.add_account(sample_account)
        account = mock_config_manager.get_account()  # No alias
        assert account.username == "testuser"

    def test_save_and_load_config(self, tmp_path, sample_account):
        """Test saving and loading configuration"""
        # Create a config manager with a real temp directory
        config_dir = tmp_path / ".chronos"
        config_dir.mkdir(exist_ok=True)

        # Override the config_dir for this test
        mgr = ConfigManager()
        mgr.config_dir = config_dir
        mgr.config_file = config_dir / "accounts.json"

        # Add account and save
        mgr.add_account(sample_account)
        mgr.save_config()  # Changed from _save_config to save_config

        # Verify file was created
        assert mgr.config_file.exists()

        # Create new manager instance to test loading
        new_mgr = ConfigManager()
        new_mgr.config_dir = config_dir
        new_mgr.config_file = config_dir / "accounts.json"
        new_mgr._load_config()

        assert "test_account" in new_mgr.config.accounts
        assert new_mgr.config.accounts["test_account"].username == "testuser"

    def test_list_accounts(self, mock_config_manager, sample_account):
        """Test listing all accounts"""
        mock_config_manager.add_account(sample_account)
        accounts = mock_config_manager.list_accounts()
        assert len(accounts) == 1
        assert "test_account" in accounts

    def test_add_duplicate_account_raises_error(self, mock_config_manager, sample_account):
        """Test that adding an account with duplicate alias raises AccountAlreadyExistsError"""
        from chronos_mcp.exceptions import AccountAlreadyExistsError

        # Add the first account
        mock_config_manager.add_account(sample_account)

        # Create a second account with the same alias but different URL
        duplicate_account = Account(
            alias="test_account",  # Same alias
            url="https://different.caldav.com",  # Different URL
            username="different_user",
            password="different_pass",
        )

        # Attempt to add duplicate should raise error
        with pytest.raises(AccountAlreadyExistsError) as exc_info:
            mock_config_manager.add_account(duplicate_account)

        # Verify error details
        assert "test_account" in str(exc_info.value)
        assert exc_info.value.error_code == "ACCOUNT_EXISTS"

        # Verify original account was not modified
        accounts = mock_config_manager.list_accounts()
        assert len(accounts) == 1
        assert str(accounts["test_account"].url) == "https://caldav.example.com/"
        assert accounts["test_account"].username == "testuser"
