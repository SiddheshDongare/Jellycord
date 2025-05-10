"""Authorization check for commands."""

import logging

import discord
from discord import app_commands

from modules.config import get_config_value
from modules.messaging import get_message  # create_embed will be used later

logger = logging.getLogger(__name__)


def is_in_support_and_authorized():
    """Check if user is in support category and has a required role."""

    async def predicate(interaction: discord.Interaction) -> bool:
        # Use the bot's logger instance if possible, otherwise module logger
        check_logger = logger
        try:
            check_logger.debug(
                f"Running authorization check for command '{interaction.command.name if interaction.command else 'Unknown'}' by user {interaction.user} in channel {interaction.channel}"
            )
            # Ensure channel object exists before checking category
            if not interaction.channel:
                check_logger.warning(
                    "Authorization check failed: Interaction has no channel object."
                )
                await interaction.response.send_message(
                    get_message("errors.auth_no_channel"), ephemeral=True
                )
                return False

            # Get the bot instance from the client property
            bot = interaction.client

            # Call is_support_category method from the bot instance
            if not bot.is_support_category(interaction.channel):
                check_logger.warning(
                    f"Auth check failed for user {interaction.user}: Command used outside configured support channels/categories in channel #{interaction.channel.name}."
                )
                await interaction.response.send_message(
                    get_message("errors.not_in_support_channel"),  # Use new system
                    ephemeral=True,
                )
                return False

            # Ensure interaction.user is a Member object to check roles
            if not isinstance(interaction.user, discord.Member):
                check_logger.error(
                    f"Auth check failed: interaction.user is not a discord.Member object (Type: {type(interaction.user)}). Cannot check roles."
                )
                await interaction.response.send_message(
                    get_message("errors.auth_not_member"), ephemeral=True
                )
                return False

            # Role check
            # Get allowed roles from the new config structure
            allowed_role_names_or_ids = get_config_value(
                "discord.command_authorized_roles", []
            )
            if not allowed_role_names_or_ids:
                logger.warning(
                    "Authorization check: No 'command_authorized_roles' configured. Denying command access."
                )
                await interaction.response.send_message(
                    get_message("errors.auth_config_error"),
                    ephemeral=True,  # Use new system
                )
                return False

            user_roles = interaction.user.roles
            authorized = any(
                role.name in allowed_role_names_or_ids
                or str(role.id) in allowed_role_names_or_ids
                for role in user_roles
            )

            if not authorized:
                check_logger.warning(
                    f"Auth check failed for user {interaction.user}: User lacks required roles ({', '.join(allowed_role_names_or_ids)})"
                )
                await interaction.response.send_message(
                    get_message("errors.not_authorized_command"),  # Use new system
                    ephemeral=True,
                )
                return False

            check_logger.debug(
                f"Authorization check passed for user {interaction.user} for command '{interaction.command.name if interaction.command else 'Unknown'}'."
            )
            return True
        except Exception as e:
            check_logger.error(
                f"Error during command authorization check for user {interaction.user}: {str(e)}",
                exc_info=True,
            )
            # Avoid sending response if already sent
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    get_message("errors.permission_check_error"),  # Use new system
                    ephemeral=True,
                )
            return False

    return app_commands.check(predicate)
