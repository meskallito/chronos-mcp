"""
Secure credential management for Chronos MCP using system keyring.

This module provides secure storage for CalDAV passwords using the system keyring
when available, with fallback to configuration file (with warnings).
"""

from typing import Any, Dict, Optional

# Try to import keyring, but handle its absence gracefully
try:
    import keyring  # type: ignore[import-untyped]

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    keyring = None  # type: ignore[assignment]

from .logging_config import setup_logging

logger = setup_logging()


class CredentialManager:
    """
    Manages secure credential storage using system keyring with fallback.

    Keyring service name follows the pattern: chronos-mcp
    Keyring keys follow the pattern: caldav:{alias}
    """

    SERVICE_NAME = "chronos-mcp"
    KEY_PREFIX = "caldav:"

    def __init__(self):
        """Initialize the credential manager."""
        self.keyring_available = KEYRING_AVAILABLE
        self._keyring_backend = None

        if self.keyring_available:
            try:
                # Test keyring availability by getting the backend
                self._keyring_backend = keyring.get_keyring()
                backend_name = type(self._keyring_backend).__name__

                # Check if we have a null/fail backend
                if "fail" in backend_name.lower() or "null" in backend_name.lower():
                    self.keyring_available = False
                    logger.warning(f"Keyring backend is non-functional: {backend_name}")
                else:
                    logger.info(f"Using keyring backend: {backend_name}")
            except Exception as e:
                self.keyring_available = False
                logger.warning(f"Keyring initialization failed: {e}")
        else:
            logger.warning("Keyring module not available - passwords will be stored in config file")

    def _get_keyring_key(self, alias: str) -> str:
        """Generate the keyring key for an account alias."""
        return f"{self.KEY_PREFIX}{alias}"

    def get_password(self, alias: str, fallback_password: Optional[str] = None) -> Optional[str]:
        """
        Retrieve password from keyring, with fallback to provided value.

        Args:
            alias: Account alias
            fallback_password: Password from config file (used if keyring fails)

        Returns:
            Password string or None if not found
        """
        if self.keyring_available:
            try:
                key = self._get_keyring_key(alias)
                password = keyring.get_password(self.SERVICE_NAME, key)

                if password:
                    logger.debug("Retrieved password from keyring for account: [REDACTED]")
                    return password
                elif fallback_password:
                    logger.warning(
                        f"Password for '{alias}' found in config file but not in keyring. "
                        "Consider running the migration script to securely store "
                        "passwords in keyring: python -m chronos_mcp.scripts.migrate_to_keyring"
                    )

            except Exception as e:
                logger.error(f"Failed to retrieve password from keyring: {e}")

        if fallback_password:
            if not self.keyring_available:
                logger.debug("Using password from config file for account: [REDACTED]")
            return fallback_password

        return None

    def set_password(self, alias: str, password: str) -> bool:
        """
        Store password in keyring.

        Args:
            alias: Account alias
            password: Password to store

        Returns:
            True if successfully stored, False otherwise
        """
        if not self.keyring_available:
            logger.debug("Keyring not available, cannot store password for account: [REDACTED]")
            return False

        try:
            key = self._get_keyring_key(alias)
            keyring.set_password(self.SERVICE_NAME, key, password)
            logger.info("Password stored in keyring for account: [REDACTED]")
            return True
        except Exception as e:
            logger.error(f"Failed to store password in keyring: {e}")
            return False

    def delete_password(self, alias: str) -> bool:
        """
        Remove password from keyring.

        Args:
            alias: Account alias

        Returns:
            True if successfully deleted, False otherwise
        """
        if not self.keyring_available:
            return False

        try:
            key = self._get_keyring_key(alias)
            keyring.delete_password(self.SERVICE_NAME, key)
            logger.info("Password removed from keyring for account: [REDACTED]")
            return True
        except keyring.errors.PasswordDeleteError:
            logger.debug("No password in keyring for account: [REDACTED]")
            return False
        except Exception as e:
            logger.error(f"Failed to delete password from keyring: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """
        Get credential manager status information.

        Returns:
            Dictionary with status information
        """
        status = {
            "keyring_available": self.keyring_available,
            "backend": None,
            "backend_type": None,
            "secure": False,
        }

        if self.keyring_available and self._keyring_backend:
            backend_name = type(self._keyring_backend).__name__
            status["backend"] = str(self._keyring_backend)
            status["backend_type"] = backend_name

            # Determine if backend is secure
            secure_backends = ["Keychain", "SecretService", "KWallet", "Windows"]
            status["secure"] = any(sb in backend_name for sb in secure_backends)

        return status


# Singleton instance
_credential_manager = None


def get_credential_manager() -> CredentialManager:
    """Get the singleton credential manager instance."""
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager()
    return _credential_manager
