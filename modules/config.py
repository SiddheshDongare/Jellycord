"""
Handles loading and validation of configuration settings.

This module is responsible for loading, merging, and validating configuration settings from:
1. The config.yaml file (primary configuration source)
2. Environment variables (for secrets and overrides)

It provides a unified configuration access mechanism through the get_config_value function,
ensures settings are validated against expected types and requirements, and makes the
configuration available throughout the application.

Key components:
- APP_CONFIG: The global configuration dictionary
- get_config_value: Function to retrieve values using dot notation
- validate_config: Validates configuration against expected structure and types
- load_app_config: Loads and merges configuration from all sources
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import yaml  # Added for YAML loading
from dotenv import load_dotenv

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Load environment variables from .env file first
# This allows environment variables to override .env file settings if both exist
load_dotenv()

# --- Global Configuration Dictionary ---
# This will hold the merged configuration from YAML and environment variables
APP_CONFIG: Dict[str, Any] = {}

# Define __all__ to control what 'from modules.config import *' imports
# Only core config accessors and the APP_CONFIG itself should be exported.
__all__ = [
    "APP_CONFIG",
    "load_app_config",
    "get_config_value",
    "validate_config",
]

# --- Default values for YAML structure (helps with validation and access) ---
DEFAULT_CONFIG_STRUCTURE = {
    "bot_settings": {
        "bot_name": "JFA-GO Invite Bot",
        "log_file_name": "jfa_bot.log",
        "db_file_name": "jfa_bot.db",
        "debug_mode": False,
        "log_level": "INFO",  # Added for completeness based on EXPECTED_CONFIG
    },
    "discord": {
        "token": None,  # Secret
        "guild_id": None,
        "admin_log_channel_id": None,
        "command_authorized_roles": [],
        "command_channel_ids": [],
        "trial_user_role_name": "Trial",
        "notification_channel_id": None,
        # "notification_days_before_expiry": [3, 1], # This is in notification_settings now
    },
    "jfa_go": {
        "base_url": None,
        "username": None,  # Secret
        "password": None,  # Secret
        "default_trial_profile": "Default Profile",
    },
    "invite_settings": {
        "invite_link_base_url": None,
        "link_validity_days": 1,
        "trial_account_duration_days": 3,
        "trial_invite_label_format": "{discord_username}-Trial-{date}",
        "user_invite_label_format": "{discord_username}-{plan_name}-{date}",
        "jfa_profile_to_discord_role_mapping": {},
    },
    "message_settings": {
        "templates_file": "message_templates.json",
        "embed_colors": {
            "success": "0x28a745",
            "error": "0xdc3545",
            "info": "0x17a2b8",
            "warning": "0xffc107",
            "blue": "0x007bff",  # Added blue as a default
        },
        "embed_footer_text": "Powered by {bot_name}",
        "bot_display_name_in_messages": "JFA-GO Bot",
    },
    "notification_settings": {
        "expiry_check_fetch_days": 4,
        "expiry_notification_interval_days": 2,
        "notification_days_before_expiry": [3, 0],
    },
    "sync_settings": {  # New section for sync task configurations
        "jfa_user_sync_interval_hours": 12,
    },
    "commands": {
        "create_trial_invite": {
            "jfa_user_expiry_days": 3,
            "jfa_invite_label_format": "Trial - {user_name} - {date}",
            "assign_role_name": "Trial",
        },
        "create_user_invite": {
            "link_validity_days": 7,
            "plan_to_role_map": {},
            "trial_role_name": "Trial",
        },
    },
}

# (type, is_required, default_value)
EXPECTED_CONFIG: Dict[str, Tuple[type, bool, Any]] = {
    "bot_settings.bot_name": (str, False, "JFA-GO Invite Bot"),
    "bot_settings.log_file_name": (str, False, "jfa_bot.log"),
    "bot_settings.db_file_name": (str, False, "jfa_bot.db"),
    "bot_settings.debug_mode": (bool, False, False),
    "bot_settings.log_level": (str, False, "INFO"),
    "discord.token": (str, True, None),
    "discord.guild_id": (str, True, None),
    "discord.admin_log_channel_id": (
        str,
        False,
        None,
    ),  # Not strictly required for bot to run, but for feature
    "discord.command_authorized_roles": (list, True, []),
    "discord.command_channel_ids": (list, True, []),
    "discord.trial_user_role_name": (
        str,
        False,
        "Trial",
    ),  # Can be empty string if no role
    "discord.notification_channel_id": (str, False, None),
    "jfa_go.base_url": (str, True, None),
    "jfa_go.username": (str, True, None),
    "jfa_go.password": (str, True, None),
    "jfa_go.default_trial_profile": (str, False, "Default Profile"),
    "invite_settings.invite_link_base_url": (
        str,
        False,
        None,
    ),  # Commands needing it will fail if not set
    "invite_settings.link_validity_days": (int, False, 1),
    "invite_settings.trial_account_duration_days": (int, False, 3),
    "invite_settings.trial_invite_label_format": (
        str,
        False,
        "{discord_username}-Trial-{date}",
    ),
    "invite_settings.user_invite_label_format": (
        str,
        False,
        "{discord_username}-{plan_name}-{date}",
    ),
    "invite_settings.jfa_profile_to_discord_role_mapping": (dict, False, {}),
    "message_settings.templates_file": (str, False, "message_templates.json"),
    "message_settings.embed_colors": (
        dict,
        False,
        {},
    ),  # Defaults are in DEFAULT_CONFIG_STRUCTURE
    "message_settings.embed_footer_text": (str, False, "Powered by {bot_name}"),
    "message_settings.bot_display_name_in_messages": (str, False, "JFA-GO Bot"),
    "notification_settings.expiry_check_fetch_days": (int, False, 4),
    "notification_settings.expiry_notification_interval_days": (int, False, 2),
    "notification_settings.notification_days_before_expiry": (list, False, [3, 0]),
    "sync_settings.jfa_user_sync_interval_hours": (
        int,
        False,
        12,
    ),  # New expected config
    "commands.create_trial_invite.jfa_user_expiry_days": (int, False, 3),
    "commands.create_trial_invite.jfa_invite_label_format": (
        str,
        False,
        "Trial - {user_name} - {date}",
    ),
    "commands.create_trial_invite.assign_role_name": (
        str,
        False,
        "Trial",
    ),  # Can be empty string
    "commands.create_user_invite.link_validity_days": (int, False, 7),
    "commands.create_user_invite.plan_to_role_map": (dict, False, {}),
    "commands.create_user_invite.trial_role_name": (
        str,
        False,
        "Trial",
    ),  # Can be empty string
}


def _load_yaml_config(path: str = "config.yaml") -> Dict[str, Any]:
    """Loads configuration from a YAML file."""
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                yaml_config = yaml.safe_load(f)
                logger.info(f"Successfully loaded configuration from {path}")
                return yaml_config or {}
        else:
            logger.warning(
                f"YAML configuration file not found at {path}. "
                "Ensure 'config.yaml' exists or all settings are provided via environment variables."
            )
            return {}
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration file {path}: {e}")
        sys.exit(f"Critical error: Could not parse {path}. Please check its syntax.")
    except Exception as e:
        logger.error(f"Unexpected error loading YAML configuration {path}: {e}")
        return {}  # Proceed with empty, rely on defaults/env vars for graceful partial failure


def _get_typed_env_var(key: str, default_value: Any, expected_type: type) -> Any:
    """Gets an environment variable and attempts to cast it to the expected type."""
    value = os.getenv(key)
    if value is None:
        return default_value

    try:
        if expected_type is bool:
            return value.lower() in ("true", "1", "t", "yes", "y")
        if expected_type is int:
            return int(value)
        if expected_type is list:  # Expect comma-separated string for lists from env
            return [item.strip() for item in value.split(",") if item.strip()]
        if (
            expected_type is dict
        ):  # Basic support for JSON string dicts from env, not heavily used.
            import json

            return json.loads(value)
        return expected_type(value)
    except ValueError:
        logger.warning(
            f"Could not cast environment variable {key}='{value}' to {expected_type}. Using default: {default_value}"
        )
        return default_value
    except Exception:
        logger.warning(
            f"Unexpected error casting env var {key}. Using default: {default_value}"
        )
        return default_value


def _merge_configs(
    yaml_config: Dict[str, Any], defaults: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Merges YAML config with defaults and environment variable overrides for specific keys.
    Secrets are preferentially taken from environment variables if set.
    """
    merged_config = {}

    for section, section_defaults in defaults.items():
        merged_config[section] = section_defaults.copy()
        yaml_section = yaml_config.get(section, {})

        if isinstance(yaml_section, dict) and isinstance(merged_config[section], dict):
            for key, default_val in section_defaults.items():
                merged_config[section][key] = yaml_section.get(key, default_val)
        elif yaml_section is not None:
            merged_config[section] = yaml_section

    return merged_config


def _apply_env_vars_to_merged_config(
    config_dict: Dict[str, Any], defaults: Dict[str, Any]
):
    """Applies environment variables to the config_dict based on default structure.
    Environment variables are expected to be in format SECTION_KEY=value (e.g., BOT_SETTINGS_DEBUG_MODE=true).
    This will override values previously set by YAML or defaults if the env var is present.
    """
    for section_name, section_defaults in defaults.items():
        if section_name not in config_dict:
            config_dict[section_name] = {}
        for key_name, default_value in section_defaults.items():
            env_var_key = f"{section_name.upper()}_{key_name.upper()}"
            expected_type = type(default_value) if default_value is not None else str

            if section_name == "discord" and key_name == "token":
                env_var_key = "DISCORD_TOKEN"
            elif section_name == "jfa_go" and key_name == "username":
                env_var_key = "JFA_GO_USERNAME"
            elif section_name == "jfa_go" and key_name == "password":
                env_var_key = "JFA_GO_PASSWORD"

            current_val_in_config = config_dict[section_name].get(
                key_name, default_value
            )
            env_val = _get_typed_env_var(
                env_var_key, current_val_in_config, expected_type
            )

            if os.getenv(env_var_key) is not None:
                config_dict[section_name][key_name] = env_val
                if env_val != current_val_in_config:
                    logger.debug(
                        f"Applied environment variable '{env_var_key}' to '{section_name}.{key_name}' (value: {env_val}) over '{current_val_in_config}'"
                    )
                else:
                    logger.debug(
                        f"Environment variable '{env_var_key}' set for '{section_name}.{key_name}' with value: {env_val}"
                    )


def load_app_config():
    """
    Load application configuration from YAML and environment variables.

    This function:
    1. Loads the base configuration from config.yaml
    2. Applies environment variable overrides using structured naming (e.g., DISCORD__TOKEN)
    3. Populates the global APP_CONFIG dictionary

    The configuration loading follows this priority order:
    - Base settings from config.yaml
    - Overrides from environment variables

    Returns:
        Dict[str, Any]: The loaded configuration dictionary
    """
    global APP_CONFIG

    # Load YAML config first
    yaml_config = _load_yaml_config()

    # Merge the YAML config with the default structure for consistent access
    merged_config = _merge_configs(yaml_config, DEFAULT_CONFIG_STRUCTURE)

    # Apply any environment variable overrides (with secret handling)
    _apply_env_vars_to_merged_config(merged_config, DEFAULT_CONFIG_STRUCTURE)

    # Set global APP_CONFIG
    APP_CONFIG = merged_config

    logger.debug(f"Configuration loaded with {len(APP_CONFIG)} top-level keys.")
    return APP_CONFIG


# Load configuration when this module is imported
load_app_config()

# --- Configuration Accessors ---
# These functions provide a clean way to access config values
# and can be expanded with more specific typing or error handling if needed.


def get_config_value(path: str, default: Any = None) -> Any:
    """
    Retrieves a configuration value using dot notation path.

    This function allows accessing nested configuration values using dot notation
    (e.g., 'discord.token') and provides a default value if the requested path
    doesn't exist in the configuration.

    Args:
        path: Dot-notation path to the configuration value (e.g., 'discord.token')
        default: Value to return if the path is not found

    Returns:
        The configuration value at the specified path, or the default if not found

    Examples:
        >>> get_config_value('bot_settings.bot_name', 'Default Bot Name')
        'JFA-GO Invite Bot'
        >>> get_config_value('nonexistent.path', 'fallback')
        'fallback'
    """
    # Import here to avoid circular imports when config.py is first loaded
    global APP_CONFIG

    if not APP_CONFIG:
        # If APP_CONFIG is empty, try to load it
        load_app_config()

    # Split the path into parts and navigate the config dict
    parts = path.split(".")
    current = APP_CONFIG
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def validate_config() -> None:
    """
    Validates the loaded configuration against expected types and requirements.

    This function checks that:
    - All required configuration values are present
    - Configuration values match their expected types
    - Basic validation rules are met

    If critical validation errors are found, this may cause the application to exit.
    Warnings for non-critical issues are logged but allow the application to continue.

    Raises:
        SystemExit: If a critical configuration error is found
    """
    global APP_CONFIG  # No, APP_CONFIG is already global. We use get_config_value.
    logger.info("Validating configuration...")
    valid = True
    # VALIDATED_CONFIG_KEYS = set() # Not strictly needed here anymore

    for key, (p_type, is_required, _default) in EXPECTED_CONFIG.items():
        val = get_config_value(key)
        # VALIDATED_CONFIG_KEYS.add(key) # Not strictly needed here anymore

        # 1. Check for presence if required
        if val is None:
            if is_required:
                logger.critical(
                    f"Config Error: Required key '{key}' is missing or not set."
                )
                valid = False
            continue  # Skip further checks for this key if it's None (and not required or error already logged)

        # 2. Basic Type Validation (already partially done, let's refine)
        type_valid = True
        if p_type == list and not isinstance(val, list):
            type_valid = False
        elif p_type == dict and not isinstance(val, dict):
            type_valid = False
        elif p_type == int and not isinstance(val, int):
            # Allow stringified integers from env vars if they are digits and not bools
            if isinstance(val, str) and val.isdigit():
                logger.info(
                    f"Config Note: Key '{key}' (value: '{val}') is a string but expected int. Will be used as int if possible by consuming code."
                )
                # Or convert and update APP_CONFIG here if auto-conversion during validation is desired
            elif not isinstance(val, bool):  # bool is subclass of int
                type_valid = False
        elif p_type == bool and not isinstance(val, bool):
            # Allow stringified booleans
            if isinstance(val, str) and val.lower() in [
                "true",
                "false",
                "1",
                "0",
                "yes",
                "no",
                "t",
                "f",
            ]:
                logger.info(
                    f"Config Note: Key '{key}' (value: '{val}') is a string but expected bool. Will be used as bool if possible."
                )
            else:
                type_valid = False
        elif p_type == str and not isinstance(val, str):
            type_valid = False

        if not type_valid:
            logger.critical(
                f"Config Error: Key '{key}' (value: '{val}', type: {type(val).__name__}) must be of type {p_type.__name__}."
            )
            valid = False
            continue  # Skip specific content checks if basic type is wrong

        # 3. Specific Content Validations
        if key == "bot_settings.log_level" and isinstance(val, str):
            if val.upper() not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                logger.critical(
                    f"Config Error: '{key}' (value: {val}) must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL."
                )
                valid = False

        elif key in [
            "discord.guild_id",
            "discord.admin_log_channel_id",
            "discord.notification_channel_id",
        ] and isinstance(val, str):
            if not val.isdigit():
                logger.critical(
                    f"Config Error: '{key}' (value: {val}) must be a valid Discord ID (string of digits). Recommended to keep as string in YAML."
                )
                valid = False

        elif key in [
            "discord.command_authorized_roles",
            "discord.command_channel_ids",
        ] and isinstance(val, list):
            if is_required and not val:
                logger.critical(
                    f"Config Error: Required key '{key}' cannot be an empty list."
                )
                valid = False
            elif not all(isinstance(item, str) for item in val):
                logger.critical(
                    f"Config Error: All items in '{key}' must be strings (names or IDs)."
                )
                valid = False

        elif (
            key == "notification_settings.notification_days_before_expiry"
            and isinstance(val, list)
        ):
            if not all(isinstance(item, int) and item >= 0 for item in val):
                logger.critical(
                    f"Config Error: All items in '{key}' must be non-negative integers."
                )
                valid = False

        elif key.endswith("days") and isinstance(val, int):
            # General check for day counts to be non-negative, specific positive checks elsewhere if needed
            if val < 0:
                logger.critical(
                    f"Config Error: Key '{key}' (value: {val}) must be a non-negative integer."
                )
                valid = False
            if (
                key
                in [
                    "invite_settings.link_validity_days",
                    "invite_settings.trial_account_duration_days",
                    "commands.create_trial_invite.jfa_user_expiry_days",
                    "commands.create_user_invite.link_validity_days",
                    "notification_settings.expiry_check_fetch_days",
                    "notification_settings.expiry_notification_interval_days",
                ]
                and val <= 0
            ):
                if not (
                    key == "notification_settings.notification_days_before_expiry"
                    and 0 in val
                ):  # 0 is allowed for day of expiry
                    logger.critical(
                        f"Config Error: Key '{key}' (value: {val}) must be a positive integer."
                    )
                    valid = False

        elif key.endswith("url") and isinstance(val, str) and val:
            if not (val.startswith("http://") or val.startswith("https://")):
                logger.warning(
                    f"Config Warning: Key '{key}' (value: {val}) does not appear to be a valid HTTP/HTTPS URL."
                )

        elif key == "message_settings.embed_colors" and isinstance(val, dict):
            for color_name, color_value in val.items():
                if not isinstance(color_name, str) or not isinstance(color_value, str):
                    logger.critical(
                        f"Config Error: In '{key}', both color name and value must be strings. Found: '{color_name}': '{color_value}'."
                    )
                    valid = False
                    break
                if not (
                    color_value.startswith("0x")
                    and len(color_value) == 8
                    and all(c in "0123456789abcdefABCDEF" for c in color_value[2:])
                ):
                    logger.critical(
                        f"Config Error: In '{key}', color value '{color_value}' for '{color_name}' is not a valid hex color string (e.g., '0xFF00FF')."
                    )
                    valid = False
                    break

        elif key.endswith("plan_to_role_map") and isinstance(val, dict):
            if not all(
                isinstance(k, str) and isinstance(v, str) for k, v in val.items()
            ):
                logger.critical(
                    f"Config Error: For '{key}', all keys (JFA Plan Names) and values (Discord Role Names/IDs) must be strings."
                )
                valid = False
        elif (
            key == "invite_settings.jfa_profile_to_discord_role_mapping"
            and isinstance(val, dict)
        ):
            if not all(
                isinstance(k, str) and isinstance(v, str) for k, v in val.items()
            ):
                logger.critical(
                    f"Config Error: For '{key}', all keys (JFA Profile Names) and values (Discord Role Names/IDs) must be strings."
                )
                valid = False

    if not valid:
        logger.critical(
            "Configuration validation failed. Please check your config.yaml and .env files, or bot logs for details."
        )
        sys.exit(1)
    logger.info("Configuration validated successfully.")


# Note: The old flat variables like TOKEN, JFA_USERNAME are kept for now to minimize
# immediate changes in other files. Other modules will still import them directly.
# Gradually, other modules should be updated to use get_config_value('path.to.setting')
# or specific accessor functions if complex logic/typing is needed for a value.
