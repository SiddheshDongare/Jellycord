"""Main entry point for the application."""

import logging
import sys

from modules.bot import JfaGoBot, register_event_handlers
from modules.commands.admin_commands import setup_commands as setup_admin_commands
from modules.commands.invite_commands import setup_commands as setup_invite_commands
from modules.commands.user_invite_commands import setup_commands as setup_user_invite_commands

from modules.config import get_config_value, validate_config
from modules.logging_setup import setup_logging

# Setup logging first
setup_logging()

# Get the main logger
logger = logging.getLogger(__name__)

# Validate configuration
validate_config()

if __name__ == "__main__":
    try:
        logger.info("Starting JFA-GO Discord Bot")

        # Fetch required config values
        jfa_username = get_config_value("jfa_go.username")
        jfa_password = get_config_value("jfa_go.password")
        jfa_base_url = get_config_value("jfa_go.base_url")
        discord_token = get_config_value("discord.token")

        if not all([jfa_username, jfa_password, jfa_base_url, discord_token]):
            logger.critical(
                "Missing critical JFA-GO or Discord configuration. Please check your config.yaml and .env file."
            )
            sys.exit(1)

        # Initialize the bot
        bot = JfaGoBot(jfa_username, jfa_password, jfa_base_url)

        # Register event handlers
        register_event_handlers(bot)

        # Register command handlers
        setup_invite_commands(bot)
        logger.debug("Invite commands setup.")
        setup_user_invite_commands(bot)
        logger.debug("User invite commands setup.")
        setup_admin_commands(bot)
        logger.debug("Admin commands setup.")

        # Run the bot
        bot.run(discord_token)
    except Exception as e:
        logger.critical(f"Failed to start bot: {e}", exc_info=True)
        sys.exit(1)
