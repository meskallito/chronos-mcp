"""
Unit tests for credential management
"""

from unittest.mock import Mock, patch

from chronos_mcp.credentials import CredentialManager, get_credential_manager


class TestCredentialManager:
    """Test credential manager functionality"""

    def test_init_with_keyring_available(self):
        """Test initialization when keyring is available"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "KeychainBackend"
            mock_keyring.get_keyring.return_value = mock_backend

            mgr = CredentialManager()
            assert mgr.keyring_available is True

    def test_init_without_keyring(self):
        """Test initialization when keyring is not available"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            assert mgr.keyring_available is False

    def test_init_with_fail_backend(self):
        """Test initialization with non-functional keyring backend"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "failBackend"
            mock_keyring.get_keyring.return_value = mock_backend

            mgr = CredentialManager()
            assert mgr.keyring_available is False

    def test_get_password_from_keyring(self):
        """Test retrieving password from keyring"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "TestBackend"
            mock_keyring.get_keyring.return_value = mock_backend
            mock_keyring.get_password.return_value = "secret123"

            mgr = CredentialManager()
            result = mgr.get_password("test_alias")
            assert result == "secret123"

    def test_get_password_fallback(self):
        """Test password retrieval falls back to provided value"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "TestBackend"
            mock_keyring.get_keyring.return_value = mock_backend
            mock_keyring.get_password.return_value = None

            mgr = CredentialManager()
            result = mgr.get_password("test_alias", fallback_password="fallback_pw")
            assert result == "fallback_pw"

    def test_get_password_no_keyring_uses_fallback(self):
        """Test password retrieval uses fallback when keyring unavailable"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            result = mgr.get_password("test_alias", fallback_password="config_pw")
            assert result == "config_pw"

    def test_get_password_returns_none_when_nothing_available(self):
        """Test password retrieval returns None when nothing available"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            result = mgr.get_password("test_alias")
            assert result is None

    def test_set_password_success(self):
        """Test storing password in keyring"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "TestBackend"
            mock_keyring.get_keyring.return_value = mock_backend

            mgr = CredentialManager()
            result = mgr.set_password("test_alias", "new_secret")
            assert result is True
            mock_keyring.set_password.assert_called_once()

    def test_set_password_no_keyring(self):
        """Test storing password fails gracefully when keyring unavailable"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            result = mgr.set_password("test_alias", "new_secret")
            assert result is False

    def test_delete_password_success(self):
        """Test deleting password from keyring"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "TestBackend"
            mock_keyring.get_keyring.return_value = mock_backend

            mgr = CredentialManager()
            result = mgr.delete_password("test_alias")
            assert result is True

    def test_delete_password_no_keyring(self):
        """Test deleting password fails gracefully when keyring unavailable"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            result = mgr.delete_password("test_alias")
            assert result is False

    def test_get_status_with_keyring(self):
        """Test status returns keyring info"""
        with (
            patch("chronos_mcp.credentials.KEYRING_AVAILABLE", True),
            patch("chronos_mcp.credentials.keyring") as mock_keyring,
        ):
            mock_backend = Mock()
            type(mock_backend).__name__ = "Keychain"
            mock_keyring.get_keyring.return_value = mock_backend

            mgr = CredentialManager()
            status = mgr.get_status()
            assert status["keyring_available"] is True
            assert status["secure"] is True

    def test_get_status_without_keyring(self):
        """Test status reflects unavailable keyring"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            status = mgr.get_status()
            assert status["keyring_available"] is False
            assert status["secure"] is False

    def test_get_credential_manager_singleton(self):
        """Test singleton pattern"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr1 = get_credential_manager()
            mgr2 = get_credential_manager()
            assert mgr1 is mgr2

    def test_keyring_key_format(self):
        """Test keyring key generation"""
        with patch("chronos_mcp.credentials.KEYRING_AVAILABLE", False):
            mgr = CredentialManager()
            key = mgr._get_keyring_key("my_account")
            assert key == "caldav:my_account"
