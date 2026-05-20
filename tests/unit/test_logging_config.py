"""
Unit tests for logging configuration
"""

import logging

from chronos_mcp.logging_config import setup_logging


class TestLoggingConfig:
    """Test logging configuration"""

    def test_setup_logging_returns_logger(self):
        """Test setup_logging returns a logger instance"""
        logger = setup_logging()
        assert isinstance(logger, logging.Logger)

    def test_setup_logging_returns_named_logger(self):
        """Test setup_logging returns a logger with a name"""
        logger = setup_logging()
        assert logger.name is not None

    def test_setup_logging_idempotent(self):
        """Test calling setup_logging multiple times is safe"""
        logger1 = setup_logging()
        logger2 = setup_logging()
        assert isinstance(logger1, logging.Logger)
        assert isinstance(logger2, logging.Logger)
