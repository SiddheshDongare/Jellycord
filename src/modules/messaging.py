"""Handles loading and formatting of user-facing messages and embeds from templates."""

import json
import logging
import os
from typing import Any, Dict, Optional

import discord

# Assuming your config.py has a way to get the APP_CONFIG or specific values
from modules.config import get_config_value, DEFAULT_TEMPLATES_FILE_PATH

logger = logging.getLogger(__name__)

MESSAGE_TEMPLATES: Dict[str, Any] = {}


def load_message_templates() -> None:
    """
    Loads message templates from the JSON file specified in config.
    Should be called once at startup.
    """
    global MESSAGE_TEMPLATES
    # Use the constant defined in config.py for the default path
    templates_file = get_config_value(
        "message_settings.templates_file", DEFAULT_TEMPLATES_FILE_PATH
    )

    # Ensure the config directory exists if the path is nested and default
    # This is more for robustness during initial setup if config isn't run first
    # or if user directly calls this. In normal flow, config.py doesn't create this dir.
    if templates_file == DEFAULT_TEMPLATES_FILE_PATH:
        config_dir = os.path.dirname(DEFAULT_TEMPLATES_FILE_PATH)
        if config_dir and not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir)
                logger.info(f"Created directory for message templates: {config_dir}")
            except OSError as e:
                logger.error(
                    f"Could not create directory for message templates {config_dir}: {e}. Loading may fail."
                )

    try:
        with open(templates_file, "r", encoding="utf-8") as f:
            MESSAGE_TEMPLATES = json.load(f)
        logger.info(f"Successfully loaded message templates from: {templates_file}")
    except FileNotFoundError:
        logger.error(
            f"Message templates file not found: {templates_file}. Using empty templates."
        )
        MESSAGE_TEMPLATES = {}
    except json.JSONDecodeError as e:
        logger.error(
            f"Error decoding JSON from message templates file {templates_file}: {e}. Using empty templates."
        )
        MESSAGE_TEMPLATES = {}
    except Exception as e:
        logger.error(
            f"Unexpected error loading message templates from {templates_file}: {e}. Using empty templates.",
            exc_info=True,
        )
        MESSAGE_TEMPLATES = {}


def get_bot_display_name() -> str:
    """Retrieves the bot's display name from configuration."""
    return get_config_value(
        "message_settings.bot_display_name_in_messages",
        get_config_value(
            "bot_settings.bot_name", "Bot"
        ),  # Fallback to bot_name, then "Bot"
    )


def get_message(key: str, default: Optional[str] = None, **kwargs: Any) -> str:
    """
    Retrieves a message template by its dot-separated key, formats it with kwargs,
    and returns the formatted string.

    Example: get_message("errors.not_authorized_command")
             get_message("general.hello", user_name="Bob")
    """
    if not MESSAGE_TEMPLATES:
        logger.warning(
            f"Attempted to get message for key '{key}' but templates are not loaded."
        )
        return default if default is not None else f"<Missing Template: {key}>"

    keys = key.split(".")
    value = MESSAGE_TEMPLATES
    try:
        for k in keys:
            if isinstance(value, dict):
                value = value[k]
            else:
                raise KeyError(
                    f"Path '{k}' not found in sub-template during lookup of '{key}'."
                )

        if not isinstance(value, str):
            logger.warning(
                f"Template value for key '{key}' is not a string: {type(value)}. Returning as is or default."
            )
            return str(value) if default is None else default

        return value.format(**kwargs)
    except KeyError:
        logger.warning(
            f"Message template key '{key}' not found. Returning default or placeholder."
        )
        return default if default is not None else f"<Missing Template: {key}>"
    except Exception as e:
        logger.error(
            f"Error formatting message for key '{key}' with args {kwargs}: {e}",
            exc_info=True,
        )
        return default if default is not None else f"<Error Formatting Template: {key}>"


def get_embed_color(color_type: str) -> discord.Color:
    """
    Retrieves a hex color string from message_settings.embed_colors based on type (e.g., 'success', 'error'),
    and returns a discord.Color object.
    Falls back to discord.Color.default() if not found or invalid.
    """
    hex_color_str = get_config_value(f"message_settings.embed_colors.{color_type}")

    if isinstance(hex_color_str, str):
        try:
            return discord.Color(int(hex_color_str, 16))
        except ValueError:
            logger.warning(
                f"Invalid hex color format for '{color_type}': '{hex_color_str}'. Using default color."
            )
    else:
        logger.warning(
            f"Embed color type '{color_type}' not found or not a string in config. Using default color."
        )

    return discord.Color.default()


def create_embed(
    title_key=None,
    description_key=None,
    title=None,
    description=None,
    color_type="default",
    description_kwargs=None,
    timestamp=None,
    footer_key=None,
    fields=None,
):
    """Creates a Discord embed with standard formatting.

    Args:
        title_key (str, optional): The message key for the embed title.
        description_key (str, optional): The message key for the embed description.
        title (str, optional): Direct title text (bypasses message template lookup).
        description (str, optional): Direct description text (bypasses message template lookup).
        color_type (str, optional): The type of color to use (default, success, error, warning, info).
        description_kwargs (dict, optional): Keywords arguments to format into the description.
        timestamp (datetime, optional): Timestamp to add to the embed.
        footer_key (str, optional): The message key for the embed footer.
        fields (list, optional): List of field dictionaries to add to the embed.

    Returns:
        discord.Embed: A formatted embed.
    """
    # Set embed color based on type
    if color_type == "success":
        color = 0x57F287  # Green
    elif color_type == "error":
        color = 0xED4245  # Red
    elif color_type == "warning":
        color = 0xFEE75C  # Yellow
    elif color_type == "info":
        color = 0x5865F2  # Blue
    else:
        color = 0x2F3136  # Default Discord dark theme color

    # Create embed
    embed = discord.Embed(color=color)

    # Set title if provided via key
    if title_key:
        embed.title = get_message(title_key)
    # Set title directly if provided
    elif title:
        embed.title = title

    # Set description if provided via key
    if description_key:
        kwargs = description_kwargs or {}
        embed.description = get_message(description_key, **kwargs)
    # Set description directly if provided
    elif description:
        embed.description = description

    # Set timestamp if provided
    if timestamp:
        embed.timestamp = timestamp

    # Set footer if footer_key is provided
    if footer_key:
        embed.set_footer(text=get_message(footer_key))

    # Add fields if provided
    if fields:
        for field in fields:
            name = (
                get_message(field["name_key"])
                if "name_key" in field
                else field.get("name", "")
            )

            if "value_key" in field:
                value_kwargs = field.get("value_kwargs", {})
                value = get_message(field["value_key"], **value_kwargs)
            else:
                value = field.get("value", "")

            inline = field.get("inline", True)
            embed.add_field(name=name, value=value, inline=inline)

    return embed


def create_direct_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color_type: str = "info",
    timestamp: Optional[Any] = None,
) -> discord.Embed:
    """
    Creates a discord.Embed object with direct title and description values.

    Args:
        title: Direct text for the embed title.
        description: Direct text for the embed description.
        color_type: Type of color (e.g., 'success', 'error', 'info', 'warning').
        timestamp: Optional timestamp to set on the embed.

    Returns:
        A discord.Embed object.
    """
    color = get_embed_color(color_type)

    # Create embed with direct values
    embed = discord.Embed(title=title, description=description, color=color)

    # Set timestamp if provided
    if timestamp:
        embed.timestamp = timestamp

    return embed


# Load templates when this module is imported.
# This should happen after config.py has loaded APP_CONFIG.
# Ensure this module is imported after config.py in your main application flow.
if (
    __name__ != "__main__"
):  # Avoid loading if module is run directly for testing (though not typical for this kind of module)
    load_message_templates()
