"""
Configure logging for the application.

This module sets up the application's logging infrastructure with both console and file output.
It configures:
- A rotating file handler to manage log files
- A console handler for immediate feedback
- Log level based on debug mode configuration
- Custom log format with timestamps and source information

The logging system is initialized early in the application startup to ensure all activities
are properly recorded.
"""

import logging
import logging.handlers
import os
import sys

from modules.config import get_config_value

# Determine log level from debug_mode config, with fallback
debug_mode = get_config_value("bot_settings.debug_mode", False)
LOG_LEVEL = logging.DEBUG if debug_mode else logging.INFO

# Get log file name from config, with a fallback for initial setup
log_file_name = get_config_value("bot_settings.log_file_name", "logs/jfa_bot.log")
log_level_str = get_config_value("bot_settings.log_level", "INFO").upper()

# Define log format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s"


def setup_logging():
    """
    Configure logging with rotating file and stream handlers.

    This function sets up the logging system with:
    - A root logger configured with the appropriate log level
    - A rotating file handler that limits log file size and keeps backups
    - A console output handler for immediate feedback
    - Proper error handling for file access issues

    Returns:
        None, but configures the global logging system
    """
    logger = logging.getLogger()  # Get the root logger
    logger.setLevel(LOG_LEVEL)  # Set level on the root logger
    logger.handlers.clear()  # Clear any default or previously added handlers

    # Ensure the log directory exists
    log_dir = os.path.dirname(log_file_name)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            logger.info(f"Created log directory: {log_dir}")
        except OSError as e:
            logger.error(f"Failed to create log directory {log_dir}: {e}")
            # Potentially fall back to current directory or handle error as appropriate
            # For now, we'll let it try to create the file handler which might fail visibly

    # Determine log level
    log_level = getattr(logging, log_level_str, logging.INFO)
    log_formatter = logging.Formatter(LOG_FORMAT)

    # Create a rotating file handler
    # Rotates log file when it reaches 5MB, keeps 5 backup files
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_name, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except PermissionError:
        print(
            f"Error: Permission denied writing log file to {log_file_name}. Check permissions.",
            file=sys.stderr,
        )
        # Optionally fall back to only console logging or exit
    except Exception as e:
        print(f"Error setting up file logger: {e}", file=sys.stderr)

    # Stream Handler (for console output)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)

    # Use the root logger to signal completion
    logging.info(
        f"Logging setup complete. Level: {logging.getLevelName(log_level)}, File: {log_file_name}"
    )
