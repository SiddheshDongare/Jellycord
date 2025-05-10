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
LOG_FILE_NAME = get_config_value("bot_settings.log_file_name", "jfa_bot.log")

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
    log_level = LOG_LEVEL
    log_formatter = logging.Formatter(LOG_FORMAT)

    # Root logger setup
    root_logger = logging.getLogger()  # Get the root logger
    root_logger.setLevel(log_level)  # Set level on the root logger
    root_logger.handlers.clear()  # Clear any default or previously added handlers

    # Create a rotating file handler
    # Fallback to a default name if config isn't fully loaded or value is bad
    log_file = (
        LOG_FILE_NAME
        if isinstance(LOG_FILE_NAME, str) and LOG_FILE_NAME
        else "fallback_bot.log"
    )

    # Ensure the log directory exists if LOG_FILE_NAME includes a path
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            root_logger.info(f"Created log directory: {log_dir}")
        except OSError as e:
            root_logger.error(
                f"Could not create log directory {log_dir}: {e}. Using current directory for logs."
            )
            log_file = os.path.basename(log_file)  # Fallback to current dir

    # Rotating File Handler (for production)
    # Rotates log file when it reaches 5MB, keeps 5 backup files
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)
    except PermissionError:
        print(
            f"Error: Permission denied writing log file to {log_file}. Check permissions.",
            file=sys.stderr,
        )
        # Optionally fall back to only console logging or exit
    except Exception as e:
        print(f"Error setting up file logger: {e}", file=sys.stderr)

    # Stream Handler (for console output)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    root_logger.addHandler(stream_handler)

    # Use the root logger to signal completion
    logging.info(
        f"Logging setup complete. Level: {logging.getLevelName(log_level)}, File: {log_file}"
    )
