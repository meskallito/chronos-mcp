"""
Unit tests for Chronos MCP exception handling framework
"""

from chronos_mcp.exceptions import ChronosError


class TestChronosError:
    """Test base ChronosError class"""

    def test_chronos_error_creation(self):
        """Test creating a ChronosError with all fields"""
        error = ChronosError(
            message="Test error",
            error_code="TEST_ERROR",
            details={"key": "value"},
            request_id="test-123",
        )

        assert error.message == "Test error"
        assert error.error_code == "TEST_ERROR"
        assert error.details == {"key": "value"}
        assert error.request_id == "test-123"
        assert error.timestamp is not None
        assert error.traceback is not None

    def test_chronos_error_defaults(self):
        """Test ChronosError with default values"""
        error = ChronosError("Test error")

        assert error.message == "Test error"
        assert error.error_code == "ChronosError"
        assert error.details == {}
        assert error.request_id is not None  # Auto-generated UUID

    def test_to_dict(self):
        """Test converting error to dictionary"""
        error = ChronosError(
            message="Test error",
            error_code="TEST_ERROR",
            details={"key": "value"},
            request_id="test-123",
        )

        error_dict = error.to_dict()
        assert error_dict["error"] == "TEST_ERROR"
        assert error_dict["message"] == "Test error"
        assert error_dict["details"] == {"key": "value"}
        assert error_dict["request_id"] == "test-123"
        assert "timestamp" in error_dict

    def test_str_representation(self):
        """Test string representation of error"""
        error = ChronosError(message="Test error", error_code="TEST_ERROR", request_id="test-123")

        assert str(error) == "TEST_ERROR: Test error (request_id=test-123)"
