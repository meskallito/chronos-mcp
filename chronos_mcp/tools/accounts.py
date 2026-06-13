"""
Account management tools for Chronos MCP
"""

from typing import Any, Dict, Optional

from pydantic import Field

from ..exceptions import AccountNotFoundError
from ..models import Account, AccountStatus
from ..validation import InputValidator
from .base import create_success_response, handle_tool_errors

# Module-level managers dictionary for dependency injection
_managers: Dict[str, Any] = {}


# Account tool functions - defined as standalone functions for importability
@handle_tool_errors
async def add_account(
    alias: str = Field(..., description="Unique alias for the account"),
    url: str = Field(..., description="CalDAV server URL"),
    username: str = Field(..., description="Username for authentication"),
    password: str = Field(..., description="Password for authentication"),
    display_name: Optional[str] = Field(None, description="Display name for the account"),
    allow_local: bool = Field(
        False,
        description="Allow localhost/private IPs (WARNING: only for development/testing)",
    ),
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Add a new CalDAV account to Chronos

    By default, this function blocks URLs pointing to localhost and private IP
    addresses for security (SSRF protection). For local development or testing,
    set allow_local=True to explicitly allow these addresses.
    """
    # Validate inputs before creating account
    # SSRF protection is enabled by default (allow_private_ips defaults to False)
    url = InputValidator.validate_url(url, allow_private_ips=allow_local, field_name="url")

    alias = InputValidator.validate_text_field(alias, "alias", required=True)
    username = InputValidator.validate_text_field(username, "username", required=True)
    password = InputValidator.validate_text_field(password, "password", required=True)
    display_name = InputValidator.validate_text_field(display_name or alias, "display_name")

    account = Account(
        alias=alias,
        url=url,  # type: ignore[arg-type]
        username=username,
        password=password,
        display_name=display_name or alias,
        status=AccountStatus.UNKNOWN,
        last_sync=None,
    )
    _managers["config_manager"].add_account(account)

    test_result = _managers["account_manager"].test_account(alias, request_id=request_id)

    return create_success_response(
        message=f"Account '{alias}' added successfully",
        request_id=request_id,
        alias=alias,
        connected=test_result["connected"],
        calendars=test_result["calendars"],
    )


async def list_accounts() -> Dict[str, Any]:
    """List all configured CalDAV accounts"""
    accounts = _managers["config_manager"].list_accounts()

    return {
        "accounts": [
            {
                "alias": alias,
                "url": str(acc.url),
                "display_name": acc.display_name,
                "status": acc.status,
                "is_default": alias == _managers["config_manager"].config.default_account,
            }
            for alias, acc in accounts.items()
        ],
        "total": len(accounts),
    }


@handle_tool_errors
async def remove_account(
    alias: str = Field(..., description="Account alias to remove"),
    request_id: str | None = None,
) -> Dict[str, Any]:
    """Remove a CalDAV account from Chronos"""
    if not _managers["config_manager"].get_account(alias):
        raise AccountNotFoundError(alias, request_id=request_id)

    # Use the lock-acquiring variant: disconnect_account is lock-free and must be
    # serialized w.r.t. request-thread reconnect / idle-heal paths.
    _managers["account_manager"].disconnect_account_locked(alias)
    _managers["config_manager"].remove_account(alias)

    return create_success_response(
        message=f"Account '{alias}' removed successfully",
        request_id=request_id,
    )


async def test_account(
    alias: str = Field(..., description="Account alias to test"),
) -> Dict[str, Any]:
    """Test connectivity to a CalDAV account"""
    return _managers["account_manager"].test_account(alias)


def register_account_tools(mcp, managers):
    """Register account management tools with the MCP server"""

    # Update module-level managers for dependency injection
    _managers.update(managers)

    # Register all account tools with the MCP server
    mcp.tool(add_account)
    mcp.tool(list_accounts)
    mcp.tool(remove_account)
    mcp.tool(test_account)


# Add .fn attribute to each function for backwards compatibility with tests
add_account.fn = add_account  # type: ignore[attr-defined]
list_accounts.fn = list_accounts  # type: ignore[attr-defined]
remove_account.fn = remove_account  # type: ignore[attr-defined]
test_account.fn = test_account  # type: ignore[attr-defined]


# Export all tools for backwards compatibility
__all__ = [
    "add_account",
    "list_accounts",
    "remove_account",
    "test_account",
    "register_account_tools",
]
