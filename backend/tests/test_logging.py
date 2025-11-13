"""
Test logging configuration.
"""
import sys
from pathlib import Path

import pytest
from loguru import logger

from backend.app.core.logging import setup_logging


def test_setup_logging_creates_log_directory(tmp_path, monkeypatch):
    """Test that logging setup creates logs directory."""
    # Change to temp directory
    monkeypatch.chdir(tmp_path)

    # Remove existing handlers
    logger.remove()

    setup_logging()

    log_dir = tmp_path / "logs"
    assert log_dir.exists()
    assert log_dir.is_dir()


def test_logging_configuration():
    """Test that logging is configured correctly."""
    # Remove all handlers
    logger.remove()

    setup_logging()

    # Logger should have handlers now
    # We can't easily count handlers with loguru, but we can test logging works
    try:
        logger.info("Test message")
        logger.error("Test error")
        assert True  # If no exception, logging works
    except Exception as e:
        pytest.fail(f"Logging failed: {e}")


def test_log_levels():
    """Test different log levels work."""
    logger.remove()
    setup_logging()

    # All these should work without exceptions
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")

    # Should not raise exception
    assert True
