"""
Unit tests for base tool utilities
"""

import pytest

from chronos_mcp.exceptions import ChronosError
from chronos_mcp.tools.base import handle_tool_errors


class TestHandleToolErrors:
    """Test error handling decorator"""

    @pytest.mark.asyncio
    async def test_chronos_error_sanitization(self):
        """Test that ChronosError exceptions are properly sanitized"""

        @handle_tool_errors
        async def tool_with_chronos_error(**kwargs):
            raise ChronosError("Error with password=secret123 in message")

        result = await tool_with_chronos_error()

        assert result["success"] is False
        assert "password=secret123" not in result["error"]
        assert "password=***" in result["error"]
        assert result["error_code"] == "ChronosError"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_generic_exception_sanitization(self):
        """
        Test that generic exceptions are properly sanitized.

        SECURITY TEST: This test verifies that unexpected exceptions containing
        sensitive information (passwords, tokens, API keys) are sanitized before
        being returned to the client. This prevents information disclosure via
        error messages.

        BUG: Currently FAILING - generic exceptions bypass ErrorSanitizer
        Location: chronos_mcp/tools/base.py:42
        """

        @handle_tool_errors
        async def tool_with_generic_error(**kwargs):
            # Simulate an unexpected exception with sensitive data
            raise ValueError("Database connection failed: password=mysecret123 token=abc-xyz-789")

        result = await tool_with_generic_error()

        # Verify response structure
        assert result["success"] is False
        assert result["error_code"] == "ValueError"
        assert "request_id" in result

        # CRITICAL SECURITY CHECK: Sensitive data MUST be redacted
        error_message = result["error"]
        assert (
            "password=mysecret123" not in error_message
        ), "SECURITY FAILURE: Password leaked in generic exception"
        assert (
            "token=abc-xyz-789" not in error_message
        ), "SECURITY FAILURE: Token leaked in generic exception"

        # Should contain sanitized versions
        assert "password=***" in error_message or "password" not in error_message.lower()
        assert "token=***" in error_message or "token" not in error_message.lower()

    @pytest.mark.asyncio
    async def test_generic_exception_with_url_credentials(self):
        """Test that URLs with embedded credentials are sanitized in generic exceptions"""

        @handle_tool_errors
        async def tool_with_url_error(**kwargs):
            raise ConnectionError("Failed to connect to https://user:pass@example.com/api")

        result = await tool_with_url_error()

        assert result["success"] is False
        error_message = result["error"]

        # CRITICAL: URL credentials must be redacted
        assert (
            "user:pass" not in error_message
        ), "SECURITY FAILURE: URL credentials leaked in generic exception"
        assert "***:***@" in error_message or "user" not in error_message

    @pytest.mark.asyncio
    async def test_generic_exception_with_api_key(self):
        """Test that API keys are sanitized in generic exceptions"""

        @handle_tool_errors
        async def tool_with_api_key_error(**kwargs):
            raise RuntimeError("API request failed: api_key=sk_live_abc123xyz789")

        result = await tool_with_api_key_error()

        assert result["success"] is False
        error_message = result["error"]

        # CRITICAL: API key must be redacted
        assert (
            "sk_live_abc123xyz789" not in error_message
        ), "SECURITY FAILURE: API key leaked in generic exception"
        assert "api_key=***" in error_message or "api_key" not in error_message

    @pytest.mark.asyncio
    async def test_success_path_no_error(self):
        """Test that successful tool execution returns normally"""

        @handle_tool_errors
        async def successful_tool(**kwargs):
            return {"success": True, "data": "test"}

        result = await successful_tool()

        assert result["success"] is True
        assert result["data"] == "test"
        # Note: request_id is only added to error responses, not success responses

    @pytest.mark.asyncio
    async def test_request_id_propagation(self):
        """Test that request_id is properly injected as a kwarg to the tool function"""

        @handle_tool_errors
        async def tool_that_uses_request_id(request_id=None, **kwargs):
            # Tool should receive the injected request_id
            assert request_id is not None
            # Return it so we can verify it was passed
            return {"success": True, "received_id": request_id}

        result = await tool_that_uses_request_id()

        # Tool function received the request_id
        assert result["success"] is True
        assert "received_id" in result
        # Verify it's a valid UUID string
        import uuid

        uuid.UUID(result["received_id"])  # Will raise if invalid
