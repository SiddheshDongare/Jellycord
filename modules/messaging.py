"""Handles loading and formatting of user-facing messages and embeds from templates."""

import json
import logging
import os
from typing import Any, Dict, Optional

import discord

# Assuming your config.py has a way to get the APP_CONFIG or specific values
from modules.config import get_config_value

logger = logging.getLogger(__name__)

MESSAGE_TEMPLATES: Dict[str, Any] = {}


def load_message_templates() -> None:
    """
    Loads message templates from the JSON file specified in the bot configuration.
    Should be called once at startup.
    """
    global MESSAGE_TEMPLATES
    templates_file_path = get_config_value(
        "message_settings.templates_file", "message_templates.json"
    )

    # Try to find the templates file relative to the project root or module location
    # This assumes the script is run from the project root or modules/ is in PYTHONPATH
    possible_paths = [
        templates_file_path,
        os.path.join(
            os.path.dirname(__file__), "..", templates_file_path
        ),  # Relative to modules/ directory
    ]

    loaded_path = None
    for path_option in possible_paths:
        abs_path = os.path.abspath(path_option)
        if os.path.exists(abs_path):
            templates_file_path = abs_path
            loaded_path = templates_file_path
            break

    if not loaded_path:
        logger.error(
            f"Message templates file could not be found at specified/default paths: {templates_file_path} (tried {possible_paths}). Messaging system will be impaired."
        )
        MESSAGE_TEMPLATES = {}
        return

    try:
        with open(templates_file_path, "r", encoding="utf-8") as f:
            MESSAGE_TEMPLATES = json.load(f)
        logger.info(
            f"Successfully loaded message templates from: {templates_file_path}"
        )
    except FileNotFoundError:
        logger.error(
            f"Message templates file not found: {templates_file_path}. Using empty templates."
        )
        MESSAGE_TEMPLATES = {}
    except json.JSONDecodeError as e:
        logger.error(
            f"Error decoding JSON from message templates file {templates_file_path}: {e}. Using empty templates."
        )
        MESSAGE_TEMPLATES = {}
    except Exception as e:
        logger.error(
            f"Unexpected error loading message templates from {templates_file_path}: {e}. Using empty templates.",
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
    title_key: Optional[str] = None,
    description_key: Optional[str] = None,
    color_type: str = "info",
    title_kwargs: Optional[Dict[str, Any]] = None,
    description_kwargs: Optional[Dict[str, Any]] = None,
    footer_key: Optional[str] = None,
    footer_kwargs: Optional[Dict[str, Any]] = None,
    fields: Optional[list] = None,
    **embed_constructor_kwargs: Any,
) -> discord.Embed:
    """
    Creates a discord.Embed object using message templates for title and description.

    Args:
        title_key: Dot-separated key for the embed title in message_templates.json.
        description_key: Dot-separated key for the embed description.
        color_type: Type of color (e.g., 'success', 'error', 'info', 'warning') to fetch from config.
        title_kwargs: Keyword arguments for formatting the title string.
        description_kwargs: Keyword arguments for formatting the description string.
        footer_key: Dot-separated key for the embed footer text. If provided, this takes precedence.
        footer_kwargs: Keyword arguments for formatting the footer string if footer_key is used.
        fields: A list of dictionaries, where each dict defines a field (name, value, inline). Example: [{'name_key': 'key', 'value_key': 'key', 'inline': False, 'name_kwargs': {}, 'value_kwargs': {}}]
        **embed_constructor_kwargs: Additional keyword arguments to pass directly to the discord.Embed constructor
                                (e.g., timestamp=datetime.datetime.now()). Note: 'footer' passed here will be overridden by footer_key or default footer logic.

    Returns:
        A discord.Embed object.
    """
    title = get_message(title_key, **(title_kwargs or {})) if title_key else None
    description = (
        get_message(description_key, **(description_kwargs or {}))
        if description_key
        else None
    )
    color = get_embed_color(color_type)

    # Prepare kwargs for Embed constructor, excluding 'footer' if present in direct kwargs, as we handle it separately
    # also exclude title and description as they are handled by keys
    valid_embed_kwargs = {
        k: v
        for k, v in embed_constructor_kwargs.items()
        if k not in ["footer", "title", "description"]
    }

    embed = discord.Embed(
        title=title, description=description, color=color, **valid_embed_kwargs
    )

    # Handle Footer
    footer_text_to_set = None
    bot_name = get_bot_display_name()  # Get bot name once for potential use

    if footer_key:
        # If a specific footer_key is provided, use it.
        # Pass bot_name to get_message in case the template uses {bot_name}
        footer_text_to_set = get_message(
            footer_key, **(footer_kwargs or {}), bot_name=bot_name
        )
    elif (
        "footer" in embed_constructor_kwargs
    ):  # Check if footer was passed in direct kwargs
        footer_info = embed_constructor_kwargs["footer"]
        if isinstance(footer_info, dict) and "text" in footer_info:
            raw_footer_text = footer_info["text"]
            # If direct footer text might contain {bot_name}, format it.
            try:
                footer_text_to_set = raw_footer_text.format(bot_name=bot_name)
            except KeyError:  # If {bot_name} is not a placeholder, use as is
                footer_text_to_set = raw_footer_text
        elif isinstance(footer_info, str):
            try:
                footer_text_to_set = footer_info.format(bot_name=bot_name)
            except KeyError:
                footer_text_to_set = footer_info
    else:
        # If no specific footer provided, use the default footer from config
        default_footer_text_format = get_config_value(
            "message_settings.embed_footer_text"
        )
        if default_footer_text_format:
            try:
                footer_text_to_set = default_footer_text_format.format(
                    bot_name=bot_name
                )
            except KeyError:  # Should not happen if template is correct
                footer_text_to_set = default_footer_text_format

    if footer_text_to_set:
        # icon_url can also be part of footer_info if it was a dict
        icon_url = None
        if "footer" in embed_constructor_kwargs and isinstance(
            embed_constructor_kwargs["footer"], dict
        ):
            icon_url = embed_constructor_kwargs["footer"].get("icon_url")
        embed.set_footer(text=footer_text_to_set, icon_url=icon_url)

    # Handle Fields if provided
    if fields:
        for field_data in fields:
            field_name = get_message(
                field_data["name_key"], **(field_data.get("name_kwargs") or {})
            )
            field_value = get_message(
                field_data["value_key"], **(field_data.get("value_kwargs") or {})
            )
            is_inline = field_data.get("inline", False)
            embed.add_field(name=field_name, value=field_value, inline=is_inline)

    return embed


# Load templates when this module is imported.
# This should happen after config.py has loaded APP_CONFIG.
# Ensure this module is imported after config.py in your main application flow.
if (
    __name__ != "__main__"
):  # Avoid loading if module is run directly for testing (though not typical for this kind of module)
    load_message_templates()
