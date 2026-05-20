"""
Configuration management for Chronos MCP
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, HttpUrl

from .credentials import get_credential_manager
from .logging_config import setup_logging
from .models import Account, AccountStatus

logger = setup_logging()


class ChronosConfig(BaseModel):
    """Main configuration"""

    accounts: Dict[str, Account] = Field(default_factory=dict, description="Configured accounts")
    default_account: Optional[str] = Field(None, description="Default account alias")


class ConfigManager:
    """Manage Chronos configuration"""

    def __init__(self):
        self.config_dir = Path.home() / ".chronos"
        self.config_file = self.config_dir / "accounts.json"
        self.config: ChronosConfig = ChronosConfig(default_account=None)
        self._load_config()

    def _load_config(self):
        """Load configuration from file and environment"""
        # First, try to load from config file
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    # Convert account dicts to Account objects
                    accounts = {}
                    for alias, acc_data in data.get("accounts", {}).items():
                        acc_data["alias"] = alias
                        if "url" in acc_data and isinstance(acc_data["url"], str):
                            accounts[alias] = Account(**acc_data)

                    self.config = ChronosConfig(
                        accounts=accounts, default_account=data.get("default_account")
                    )
                    logger.info(f"Loaded {len(accounts)} accounts from config file")
            except Exception as e:
                logger.error(f"Error loading config file: {e}")

        env_url = os.getenv("CALDAV_BASE_URL")
        env_username = os.getenv("CALDAV_USERNAME")
        env_password = os.getenv("CALDAV_PASSWORD")

        # Validate environment variables before use (defense-in-depth)
        if env_url and env_username:
            from .validation import InputValidator

            try:
                # Allow local URLs for development environments
                env_url = InputValidator.validate_url(
                    env_url, allow_private_ips=True, field_name="CALDAV_BASE_URL"
                )
                env_username = InputValidator.validate_text_field(
                    env_username, "CALDAV_USERNAME", required=True
                )
                if env_password:
                    env_password = InputValidator.validate_text_field(
                        env_password, "CALDAV_PASSWORD", required=True
                    )
            except Exception as e:
                logger.error(f"Invalid environment variable values: {e}")
                return  # Skip environment account creation if validation fails

        if env_url and env_username:
            env_account = Account(
                alias="default",
                url=HttpUrl(env_url),
                username=env_username,
                password=env_password,
                display_name="Default Account (from environment)",
                status=AccountStatus.UNKNOWN,
                last_sync=None,
            )

            if "default" not in self.config.accounts:
                # Store password in keyring if available
                if env_password:
                    credential_manager = get_credential_manager()
                    if credential_manager.keyring_available:
                        if credential_manager.set_password("default", env_password):
                            logger.info("Environment password stored in keyring")
                            # Don't include password in account object if stored in keyring
                            env_account.password = None

                self.config.accounts["default"] = env_account
                if not self.config.default_account:
                    self.config.default_account = "default"
                logger.info("Added default account from environment variables")

    def save_config(self):
        """Save configuration to file"""
        self.config_dir.mkdir(exist_ok=True)

        credential_manager = get_credential_manager()

        data: Dict[str, Any] = {
            "accounts": {},
            "default_account": self.config.default_account,
        }

        for alias, acc in self.config.accounts.items():
            account_data = {
                "url": str(acc.url),
                "username": acc.username,
                "display_name": acc.display_name,
            }

            # Only save password to config if keyring is not available
            if not credential_manager.keyring_available and acc.password:
                account_data["password"] = acc.password
                logger.warning(
                    f"Saving password for '{alias}' to config file (keyring not available)"
                )

            data["accounts"][alias] = account_data

        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Configuration saved")

    def add_account(self, account: Account):
        """Add a new account

        Args:
            account: The Account object to add

        Raises:
            AccountAlreadyExistsError: If an account with the same alias already exists
        """
        if account.alias in self.config.accounts:
            from .exceptions import AccountAlreadyExistsError

            raise AccountAlreadyExistsError(account.alias)

        # Store password in keyring if available
        if account.password:
            credential_manager = get_credential_manager()
            if credential_manager.keyring_available:
                if credential_manager.set_password(account.alias, account.password):
                    logger.info(f"Password for '{account.alias}' stored in keyring")
                else:
                    logger.warning(f"Failed to store password in keyring for '{account.alias}'")

        self.config.accounts[account.alias] = account
        if not self.config.default_account:
            self.config.default_account = account.alias
        self.save_config()

    def remove_account(self, alias: str):
        """Remove an account"""
        if alias in self.config.accounts:
            # Remove password from keyring if stored there
            credential_manager = get_credential_manager()
            if credential_manager.delete_password(alias):
                logger.info(f"Password removed from keyring for account: {alias}")

            del self.config.accounts[alias]
            if self.config.default_account == alias:
                self.config.default_account = next(iter(self.config.accounts), None)
            self.save_config()

    def get_account(self, alias: Optional[str] = None) -> Optional[Account]:
        """Get an account by alias or return default"""
        if alias:
            return self.config.accounts.get(alias)
        elif self.config.default_account:
            return self.config.accounts.get(self.config.default_account)
        return None

    def list_accounts(self) -> Dict[str, Account]:
        """List all configured accounts"""
        return self.config.accounts
