"""
Logging configuration using loguru.
"""

import sys
from pathlib import Path

from loguru import logger

from backend.app.core.settings import Settings, settings


def setup_logging(app_settings: Settings | None = None) -> None:
    """Configure application logging (from ``app_settings``, default: global settings)."""
    app_settings = app_settings or settings

    # Remove default handler
    logger.remove()

    # Set safe default for request_id extra field
    logger.configure(extra={"request_id": "-"})

    # Add console handler with formatting
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "rid={extra[request_id]} | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
        level=app_settings.log_level,
        colorize=True,
    )

    # Add file handler for errors
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "error.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "rid={extra[request_id]} | "
        "{name}:{function}:{line} - {message}",
        level="ERROR",
        rotation="10 MB",
        retention="1 week",
        compression="zip",
    )

    # Add file handler for all logs if debug mode
    if app_settings.debug:
        logger.add(
            log_dir / "debug.log",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "rid={extra[request_id]} | "
            "{name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation="50 MB",
            retention="3 days",
            compression="zip",
        )

    logger.info(f"Logging initialized at level {app_settings.log_level}")
