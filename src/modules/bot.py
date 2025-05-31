"""
Discord bot for JFA-GO integration.

This module implements the core Discord bot functionality that integrates with JFA-GO.
It handles command registration, background tasks, event processing, and communication
with the JFA-GO API and database.

Key components:
- JfaGoBot class: Main bot implementation inheriting from discord.Client
- register_event_handlers: Sets up event listeners for the bot
- Background tasks: Periodic checks for expiring accounts and user notifications
"""

import asyncio
import datetime
import logging
from typing import List, Any

import discord
from discord import app_commands
from discord.ext import tasks

from modules.config import (
    get_config_value,
)
from modules.messaging import create_embed, get_message
from modules.database import Database
from modules.jfa_client import JfaGoClient
from modules.models import AdminAction


class JfaGoBot(discord.Client):
    """
    Discord bot for JFA-GO integration.

    This class handles:
    - Communication with JFA-GO API (account creation, invites, etc.)
    - Discord command registration and processing
    - Scheduled tasks (expiry notifications)
    - Event handling and logging
    - Database interactions for tracking invites and user data

    Attributes:
        jfa_client: JFA-GO API client instance
        db: Database connection for invite tracking
        tree: Command tree for registering slash commands
        admin_log_channel_id: Channel for administrative action logging
    """

    def __init__(self, jfa_username: str, jfa_password: str, jfa_base_url: str):
        self.logger = logging.getLogger(
            self.__class__.__name__
        )  # Logger for JfaGoBot class
        try:
            intents = discord.Intents.default()
            intents.members = True
            intents.message_content = True
            super().__init__(intents=intents)

            self.logger.info("Initializing JFA-GO Client...")
            self.jfa_client = JfaGoClient(jfa_base_url, jfa_username, jfa_password)
            self.logger.info("Initializing Database...")
            db_file_path = get_config_value("bot_settings.db_file_name", "jfa_bot.db")
            self.db = Database(db_file_path)
            self.logger.info("Initializing Command Tree...")
            self.tree = app_commands.CommandTree(self)

            config_admin_log_channel_id = get_config_value(
                "discord.admin_log_channel_id"
            )
            self.admin_log_channel_id = 0  # Default to 0 (disabled)
            if config_admin_log_channel_id:
                try:
                    self.admin_log_channel_id = int(config_admin_log_channel_id)
                except ValueError:
                    self.logger.warning(
                        f"Invalid format for discord.admin_log_channel_id: '{config_admin_log_channel_id}'. Admin logging to Discord channel disabled."
                    )

            if self.admin_log_channel_id == 0:
                self.logger.warning(
                    "ADMIN_LOG_CHANNEL_ID is not set or is 0. Admin actions will not be logged to Discord."
                )
            else:
                self.logger.info(
                    f"Admin log channel ID set to: {self.admin_log_channel_id}"
                )

            # Cache for support category ID - This is no longer used by the refactored is_support_category
            # self.support_category_id = None
            self.logger.info("JfaGoBot initialized successfully.")

        except Exception as e:
            # Use the class logger if available, otherwise fallback to root logger
            init_logger = getattr(self, "logger", logging.getLogger())
            init_logger.critical(
                f"Failed to initialize JfaGoBot: {str(e)}", exc_info=True
            )
            raise

    def is_support_category(self, channel: discord.abc.GuildChannel) -> bool:
        """
        Check if a channel is in the support category or is a configured command channel.

        This method determines if commands should be allowed in a given channel by checking
        against the configured command_channel_ids list. It handles various channel types
        including text channels, threads, and their parent categories.

        Args:
            channel: The Discord channel object to check

        Returns:
            bool: True if the channel is allowed for commands, False otherwise
        """
        try:
            if not channel or not hasattr(channel, "category") or not channel.category:
                self.logger.debug(
                    f"Channel {channel.name if channel else 'None'} is not in a category."
                )
                return False

            # Use COMMAND_CHANNEL_IDS from the new config
            # This replaces the old SUPPORT_CATEGORY_NAME logic
            configured_channel_ids = get_config_value("discord.command_channel_ids", [])

            if not configured_channel_ids:
                self.logger.warning(
                    "is_support_category: No command_channel_ids configured. All channels will be considered non-support."
                )
                return False

            # Check direct channel ID match
            if str(channel.id) in configured_channel_ids:
                self.logger.debug(
                    f"Channel {channel.name} ({channel.id}) is directly in configured command_channel_ids."
                )
                return True

            # Check parent category ID match
            if hasattr(channel, "category_id") and channel.category_id:
                if str(channel.category_id) in configured_channel_ids:
                    self.logger.debug(
                        f"Channel {channel.name} ({channel.id}) is in a configured support category ({channel.category_id})."
                    )
                    return True

            # Check if the channel is a thread and its parent is a support channel/category
            if isinstance(channel, discord.Thread):
                parent_channel_id = channel.parent_id
                if str(parent_channel_id) in configured_channel_ids:
                    self.logger.debug(
                        f"Thread {channel.name} ({channel.id}) has parent channel ({parent_channel_id}) in configured command_channel_ids."
                    )
                    return True
                # Check thread's parent channel's category
                parent_channel = self.get_channel(parent_channel_id)
                if (
                    parent_channel
                    and hasattr(parent_channel, "category_id")
                    and parent_channel.category_id
                ):
                    if str(parent_channel.category_id) in configured_channel_ids:
                        self.logger.debug(
                            f"Thread {channel.name} ({channel.id}) has parent channel in configured support category ({parent_channel.category_id})."
                        )
                        return True

            self.logger.debug(
                f"Channel {channel.name} ({channel.id}) with category ID {channel.category_id if hasattr(channel, 'category_id') else 'N/A'} is not a configured support channel/category."
            )
            return False
        except Exception as e:
            self.logger.error(
                f"Error checking support category for channel {channel.name if channel else 'None'}: {str(e)}",
                exc_info=True,
            )
            return False

    async def setup_hook(self):
        """
        Bot setup hook called when the bot connects to Discord.

        This method initializes and syncs slash commands with the Discord guild and
        starts the background tasks like expiry notifications. It handles:
        - Command registration for the configured guild
        - Starting scheduled tasks
        - Logging connection details

        This is called automatically by discord.py when the bot connects.
        """
        try:
            # Fetch GUILD_ID from config
            guild_id_str = get_config_value("discord.guild_id")
            if not guild_id_str:
                self.logger.error(
                    "discord.guild_id is not set in config. Command sync will be skipped."
                )
                # Start background tasks even if guild sync fails, as they might be independent
                self.check_expiry_notifications.start()
                self.sync_jfa_users_cache_task.start()
                return

            try:
                guild_id_int = int(guild_id_str)
            except ValueError:
                self.logger.error(
                    f"Invalid format for discord.guild_id: '{guild_id_str}'. Command sync will be skipped."
                )
                # Start background tasks even if guild sync fails
                self.check_expiry_notifications.start()
                self.sync_jfa_users_cache_task.start()
                return

            self.logger.info(
                f"Running setup_hook to sync commands for guild ID: {guild_id_int}"
            )
            guild = discord.Object(id=guild_id_int)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            self.logger.info(
                f"Successfully synced commands to guild ID: {guild_id_int}"
            )
            self.logger.info(f"Bot {self.user} is ready and online!")
            self.logger.info(f"Connected to {len(self.guilds)} guilds.")
            # Start background tasks here
            self.check_expiry_notifications.start()
            self.sync_jfa_users_cache_task.start()
            self.logger.info("All background tasks started.")
        except Exception as e:
            self.logger.error(
                f"Error during setup_hook command sync: {str(e)}", exc_info=True
            )
            raise

    async def get_thread_members(self, thread: discord.Thread) -> List[discord.Member]:
        """
        Get all members in a Discord thread with retry logic.

        This method attempts to fetch all members of a thread, with built-in retry logic
        to handle potential Discord API rate limits or temporary failures.

        Args:
            thread: The Discord thread object to fetch members from

        Returns:
            List[discord.Member]: A list of member objects in the thread

        Raises:
            discord.HTTPException: If fetching thread members fails after all retries
        """
        self.logger.debug(
            f"Attempting to fetch members for thread: {thread.name} (ID: {thread.id})"
        )
        max_retries = 3
        retry_delay = 1  # seconds

        for attempt in range(max_retries):
            try:
                members = []
                async for member in thread.fetch_members():
                    member_obj = thread.guild.get_member(member.id)
                    if member_obj:
                        self.logger.debug(
                            f"Fetched member {member_obj.display_name} (ID: {member_obj.id}) from thread {thread.name}"
                        )
                        members.append(member_obj)
                    else:
                        self.logger.warning(
                            f"Could not find guild member object for ThreadMember ID: {member.id} in thread {thread.name}"
                        )
                self.logger.info(
                    f"Successfully fetched {len(members)} members for thread: {thread.name}"
                )
                return members
            except discord.HTTPException as e:
                self.logger.warning(
                    f"discord.HTTPException while fetching thread members (attempt {attempt + 1}/{max_retries}) for thread {thread.name}: {str(e)}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    self.logger.error(
                        f"Failed to fetch thread members for thread {thread.name} after {max_retries} attempts: {str(e)}"
                    )
                    raise
            except Exception as e:
                self.logger.error(
                    f"Unexpected error fetching members for thread {thread.name} (attempt {attempt + 1}): {str(e)}",
                    exc_info=True,
                )
                if attempt >= max_retries - 1:
                    raise  # Rethrow after final attempt
                await asyncio.sleep(retry_delay)
                retry_delay *= 2

        # Should not be reachable if loop finishes, but added for safety
        self.logger.error(
            f"Exited get_thread_members loop unexpectedly for thread {thread.name}"
        )
        return []

    async def log_admin_action(self, action: AdminAction) -> None:
        """
        Log an administrative action to both the logger and the admin log channel.

        This method documents administrative actions like invite creation or removal
        by logging to both the application log and a designated Discord channel if configured.

        Args:
            action: AdminAction object containing details about the admin action
        """
        try:
            await (
                self.wait_until_ready()
            )  # Ensure the bot is fully connected and cache is populated

            if self.admin_log_channel_id == 0:
                self.logger.warning(
                    "Skipping Discord admin log: ADMIN_LOG_CHANNEL_ID is not configured."
                )
                return

            self.logger.info(
                f"Attempting to send admin action log ({action.action_type} by {action.admin_username}) to channel {self.admin_log_channel_id}"
            )

            guild_id_to_check_str = get_config_value("discord.guild_id")
            if not guild_id_to_check_str:
                self.logger.error(
                    "Cannot log admin action to Discord: GUILD_ID is not configured."
                )
                return
            try:
                guild_id_to_check = int(guild_id_to_check_str)
            except ValueError:
                self.logger.error(
                    f"Cannot log admin action to Discord: GUILD_ID '{guild_id_to_check_str}' is not a valid integer."
                )
                return

            guild = self.get_guild(guild_id_to_check)
            if not guild:
                self.logger.error(
                    f"Cannot log admin action to Discord: Guild {guild_id_to_check} not found in bot's cache. Ensure GUILD_ID in config.yaml is correct and the bot is in that guild."
                )
                return

            try:
                target_channel_id_int = int(self.admin_log_channel_id)
            except (
                ValueError
            ):  # Should have been caught in __init__, but defensive check
                self.logger.error(
                    f"Cannot log admin action: admin_log_channel_id '{self.admin_log_channel_id}' is not a valid integer."
                )
                return

            channel = guild.get_channel(target_channel_id_int)

            if not channel:
                self.logger.error(
                    f"Cannot log admin action to Discord: Channel {target_channel_id_int} not found in guild {guild.name}."
                )
                return

            # Refactored embed creation using messaging.py
            embed = create_embed(
                title_key="admin_log.embed_title",
                color_type="info",  # Or a dedicated color from message_templates for admin logs
                timestamp=datetime.datetime.fromtimestamp(
                    action.performed_at, tz=datetime.timezone.utc
                ),
                footer_key="admin_log.footer_text",  # Using specific footer from template
            )

            embed.add_field(
                name=get_message("admin_log.field_action_type_name"),
                value=get_message(
                    "admin_log.field_action_type_value", action_type=action.action_type
                ),
                inline=True,
            )
            embed.add_field(
                name=get_message("admin_log.field_performed_by_name"),
                value=get_message(
                    "admin_log.field_performed_by_value",
                    admin_username=action.admin_username,
                    admin_id=action.admin_id,
                ),
                inline=True,
            )
            embed.add_field(
                name=get_message("admin_log.field_target_user_name"),
                value=get_message(
                    "admin_log.field_target_user_value",
                    target_username=action.target_username,
                    target_user_id=action.target_user_id,
                ),
                inline=True,
            )
            embed.add_field(
                name=get_message("admin_log.field_details_name"),
                value=get_message(
                    "admin_log.field_details_value", details=(action.details or "N/A")
                ),
                inline=False,
            )

            await channel.send(embed=embed)
            self.logger.info(
                f"Successfully sent admin action log to channel #{channel.name} in guild {guild.name}."
            )

        except discord.errors.Forbidden:
            self.logger.error(
                f"Failed to send admin action log to channel {self.admin_log_channel_id}: Bot lacks necessary permissions (Forbidden)."
            )
        except discord.errors.HTTPException as e:
            self.logger.error(
                f"Failed to send admin action log to channel {self.admin_log_channel_id} due to an HTTP error: {str(e)}"
            )
        except Exception as e:
            self.logger.error(
                f"An unexpected error occurred while sending admin action log: {str(e)}",
                exc_info=True,
            )

    def _get_expiry_notification_data(self, expires_at_ts: int) -> dict:
        """
        Helper method to prepare formatted date strings for expiry notifications.

        Args:
            expires_at_ts: Timestamp of when the account expires

        Returns:
            dict: Mapping containing formatted date strings
        """
        expiry_datetime = datetime.datetime.fromtimestamp(
            expires_at_ts, tz=datetime.timezone.utc
        )
        return {
            "expiry_date_str": expiry_datetime.strftime("%Y-%m-%d %H:%M %Z"),
            "human_readable_expiry": discord.utils.format_dt(
                expiry_datetime, style="R"
            ),
            "expiry_datetime": expiry_datetime,
        }

    async def _send_expiry_dm(
        self,
        user_id_str: str,
        username: str,
        plan_type: str,
        expires_at_ts: int,
        days_remaining: int,
    ) -> tuple:
        """
        Helper method to send a DM to a user about their expiring account.

        Args:
            user_id_str: Discord user ID as string
            username: User's username
            plan_type: User's plan type in JFA-GO
            expires_at_ts: Timestamp when account expires
            days_remaining: Days remaining until expiry

        Returns:
            tuple: (success_status, status_key)
        """
        try:
            user_id_int = int(user_id_str)
            discord_user_obj = self.get_user(user_id_int) or await self.fetch_user(
                user_id_int
            )

            if not discord_user_obj:
                self.logger.warning(
                    f"Could not find Discord user with ID {user_id_int} for {username}. Skipping DM."
                )
                return False, "expiry_notification_summary.dm_status_failed"

            expiry_data = self._get_expiry_notification_data(expires_at_ts)
            expiry_date_str_formatted = expiry_data["expiry_date_str"]
            human_readable_expiry_formatted = expiry_data["human_readable_expiry"]
            expiry_datetime = expiry_data["expiry_datetime"]

            # Safely get guild name
            guild_name = get_config_value("bot_settings.bot_name", "Our Server")
            if hasattr(discord_user_obj, "guild") and discord_user_obj.guild:
                guild_name = discord_user_obj.guild.name

            dm_embed = create_embed(
                title_key="user_expiry_dm.embed_title",
                description_key="user_expiry_dm.embed_description",
                description_kwargs={
                    "user_mention": discord_user_obj.mention,
                    "guild_name": guild_name,
                    "plan_type_display": plan_type,
                    "expiry_date_str": expiry_date_str_formatted,
                    "human_readable_expiry": human_readable_expiry_formatted,
                },
                color_type="warning" if days_remaining > 0 else "error",
                footer_key="user_expiry_dm.footer_text",
                timestamp=expiry_datetime,
                fields=[
                    {
                        "name_key": "user_expiry_dm.field_plan_type_name",
                        "value_key": "user_expiry_dm.field_plan_type_value",
                        "value_kwargs": {"plan_type_display": plan_type},
                        "inline": True,
                    },
                    {
                        "name_key": "user_expiry_dm.field_expires_on_name",
                        "value_key": "user_expiry_dm.field_expires_on_value",
                        "value_kwargs": {"expiry_date_str": expiry_date_str_formatted},
                        "inline": True,
                    },
                    {
                        "name_key": "user_expiry_dm.field_time_remaining_name",
                        "value_key": "user_expiry_dm.field_time_remaining_value",
                        "value_kwargs": {
                            "human_readable_expiry": human_readable_expiry_formatted
                        },
                        "inline": True,
                    },
                ],
            )

            await discord_user_obj.send(embed=dm_embed)
            self.logger.info(
                f"Sent expiry notification DM to {username} ({user_id_str}). Days remaining: {days_remaining}"
            )

            # Update the notification timestamp in DB
            now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            self.db.update_last_notified(user_id_str, now_ts)

            return True, "expiry_notification_summary.dm_status_success"

        except discord.Forbidden:
            self.logger.warning(
                f"Could not send expiry DM to {username} ({user_id_str}): DMs disabled or bot blocked."
            )
            return False, "expiry_notification_summary.dm_status_failed"
        except discord.HTTPException as e:
            self.logger.error(
                f"Failed to send expiry DM to {username} ({user_id_str}) due to API error: {e}"
            )
            return False, "expiry_notification_summary.dm_status_failed"
        except Exception as e:
            self.logger.error(
                f"Unexpected error sending DM to {username} ({user_id_str}): {e}",
                exc_info=True,
            )
            return False, "expiry_notification_summary.dm_status_failed"

    @tasks.loop(hours=6)  # Check every 6 hours (adjust as needed)
    async def check_expiry_notifications(self):
        """
        Background task to check for expiring accounts and notify users.

        This method runs periodically to identify JFA-GO accounts that are nearing expiration
        and sends direct message notifications to the associated Discord users. It also sends
        a summary of notifications to a designated channel if configured.

        Configuration settings used:
        - notification_settings.expiry_check_fetch_days: How many days ahead to check
        - notification_settings.expiry_notification_interval_days: Minimum days between notifications
        - notification_settings.notification_days_before_expiry: Days before expiry to notify
        """
        await self.wait_until_ready()  # Wait until the bot is fully ready
        self.logger.info("Running check_expiry_notifications task...")

        # Get settings from config
        fetch_days = get_config_value(
            "notification_settings.expiry_check_fetch_days", 4
        )
        notification_interval_days = get_config_value(
            "notification_settings.expiry_notification_interval_days", 2
        )
        notification_days_list = get_config_value(
            "notification_settings.notification_days_before_expiry", [3, 0]
        )
        notification_interval_seconds = notification_interval_days * 86400
        notification_channel_id_str = get_config_value(
            "discord.notification_channel_id"
        )
        notification_channel = None

        if notification_channel_id_str:
            try:
                guild_id = int(get_config_value("discord.guild_id", 0))
                guild = self.get_guild(guild_id)
                if guild:
                    notification_channel = guild.get_channel(
                        int(notification_channel_id_str)
                    )
                if not notification_channel:
                    self.logger.warning(
                        f"Expiry notification channel ID {notification_channel_id_str} not found."
                    )
            except ValueError:
                self.logger.warning(
                    f"Invalid notification_channel_id: {notification_channel_id_str}"
                )
        else:
            self.logger.info(
                "No Discord notification channel configured for expiry summaries."
            )

        expiring_user_details_for_summary = []
        notified_count = 0
        failed_dm_count = 0

        try:
            potential_users_data = self.db.get_expiring_users(fetch_days)
            now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

            if not potential_users_data:
                self.logger.info(
                    "No users nearing expiry within the fetch window found."
                )
                if notification_channel:
                    no_users_embed = create_embed(
                        title_key="expiry_notification_summary.no_users_to_notify_title",
                        description_key="expiry_notification_summary.no_users_to_notify_description",
                        color_type="info",
                        footer_key="expiry_notification_summary.footer_text",
                    )
                    await notification_channel.send(embed=no_users_embed)
                return

            self.logger.info(
                f"Found {len(potential_users_data)} potential users nearing expiry. Processing notifications..."
            )

            for user_row in potential_users_data:
                user_id_str = user_row["user_id"]
                username = user_row["username"]
                expires_at_ts = user_row["account_expires_at"]
                plan_type = user_row["plan_type"] or "Unknown Plan"
                last_notified_at = user_row["last_notified_at"]
                dm_status_key = "expiry_notification_summary.dm_status_not_attempted"  # Default status

                try:
                    user_id_int = int(user_id_str)
                    discord_user_obj = self.get_user(
                        user_id_int
                    ) or await self.fetch_user(user_id_int)

                    if not discord_user_obj:
                        self.logger.warning(
                            f"Could not find Discord user with ID {user_id_int} for {username}. Skipping DM."
                        )
                        failed_dm_count += 1  # Count as failed if user object not found
                        dm_status_key = "expiry_notification_summary.dm_status_failed"
                        expiry_data = self._get_expiry_notification_data(expires_at_ts)
                        expiring_user_details_for_summary.append(
                            {
                                "username": username,
                                "user_id": user_id_str,
                                "plan_type_display": plan_type,
                                "expiry_date_str": expiry_data["expiry_date_str"],
                                "human_readable_expiry": expiry_data[
                                    "human_readable_expiry"
                                ],
                                "dm_status_key": dm_status_key,
                            }
                        )
                        continue

                    remaining_seconds = expires_at_ts - now_ts
                    days_remaining = remaining_seconds // 86400
                    should_notify_discord_user = False

                    if days_remaining in notification_days_list:
                        if (
                            last_notified_at is None
                            or (now_ts - last_notified_at)
                            > notification_interval_seconds
                        ):
                            should_notify_discord_user = True
                        else:
                            self.logger.debug(
                                f"User {username} ({user_id_str}) due for {days_remaining}-day notice, but notified recently. Skipping DM."
                            )
                            # dm_status_key remains "not_attempted"

                    if should_notify_discord_user:
                        success_status, dm_status_key = await self._send_expiry_dm(
                            user_id_str,
                            username,
                            plan_type,
                            expires_at_ts,
                            days_remaining,
                        )
                        if success_status:
                            notified_count += 1
                        else:
                            failed_dm_count += 1

                    # Add to summary list regardless of DM attempt, but with correct status
                    expiry_data = self._get_expiry_notification_data(expires_at_ts)
                    expiring_user_details_for_summary.append(
                        {
                            "username": username,
                            "user_id": user_id_str,
                            "plan_type_display": plan_type,
                            "expiry_date_str": expiry_data["expiry_date_str"],
                            "human_readable_expiry": expiry_data[
                                "human_readable_expiry"
                            ],
                            "dm_status_key": dm_status_key,
                        }
                    )

                except ValueError:
                    self.logger.error(
                        f"Invalid user_id format found in database: {user_id_str}"
                    )
                    # Don't add to summary if user_id is fundamentally broken
                except Exception as e:
                    self.logger.error(
                        f"Error processing expiry for user_id {user_id_str} ({username}): {e}",
                        exc_info=True,
                    )
                    # Add to summary with failed status if we got this far
                    expiry_data = self._get_expiry_notification_data(expires_at_ts)
                    expiring_user_details_for_summary.append(
                        {
                            "username": username,
                            "user_id": user_id_str,
                            "plan_type_display": plan_type,
                            "expiry_date_str": expiry_data["expiry_date_str"],
                            "human_readable_expiry": expiry_data[
                                "human_readable_expiry"
                            ],
                            "dm_status_key": "expiry_notification_summary.dm_status_failed",  # Mark as failed due to processing error
                        }
                    )
                    failed_dm_count += (
                        1  # Assume DM failed if user processing had an error
                    )

            # Send summary to notification channel if configured
            if notification_channel and expiring_user_details_for_summary:
                summary_desc_kwargs = {
                    "expiring_users_count": len(expiring_user_details_for_summary),
                    "notified_count": notified_count,
                    "failed_dm_count": failed_dm_count,
                }
                summary_embed = create_embed(
                    title_key="expiry_notification_summary.embed_title",
                    description_key="expiry_notification_summary.embed_description",
                    description_kwargs=summary_desc_kwargs,
                    color_type="info",
                    footer_key="expiry_notification_summary.footer_text",
                )

                field_texts = []
                for user_detail in expiring_user_details_for_summary:
                    field_text = get_message(
                        "expiry_notification_summary.field_expiring_user_entry",
                        username=user_detail["username"],
                        user_id=user_detail["user_id"],
                        plan_type_display=user_detail["plan_type_display"],
                        expiry_date_str=user_detail["expiry_date_str"],
                        human_readable_expiry=user_detail["human_readable_expiry"],
                        dm_status=get_message(
                            user_detail["dm_status_key"]
                        ),  # Get the translated status message
                    )
                    field_texts.append(field_text)

                # Discord embed field values have a limit of 1024 characters.
                # Descriptions have a limit of 4096. We'll add entries to description to avoid hitting field limits too fast.
                current_description = summary_embed.description + "\n\n**Details:**\n"
                if not field_texts:
                    current_description += "No specific user details to list for this summary (e.g. all users processed without DMs being attempted or failing)."

                for (
                    text_chunk
                ) in field_texts:  # Iterate and add to description, handling limits
                    if (
                        len(current_description) + len(text_chunk) + 2 > 4096
                    ):  # +2 for newline chars
                        summary_embed.description = current_description
                        await notification_channel.send(embed=summary_embed)
                        # Start a new embed for overflow
                        summary_embed = create_embed(
                            title_key="expiry_notification_summary.embed_title",
                            title_kwargs={"continued": True},
                            color_type="info",
                            footer_key="expiry_notification_summary.footer_text",
                        )
                        current_description = "**Details (continued):**\n"
                    current_description += text_chunk + "\n\n"

                summary_embed.description = current_description.strip()
                if summary_embed.description:  # Ensure there's something to send
                    await notification_channel.send(embed=summary_embed)

        except Exception as e:
            self.logger.error(
                f"Error in check_expiry_notifications task: {e}", exc_info=True
            )

    @check_expiry_notifications.before_loop
    async def before_check_expiry(self):
        """Wait until the bot is ready before starting the loop."""
        await self.wait_until_ready()
        self.logger.info("Expiry notification task loop is starting.")

    @tasks.loop(
        hours=get_config_value("sync_settings.jfa_user_sync_interval_hours", 12)
    )
    async def sync_jfa_users_cache_task(self):
        """Periodically fetches all users from JFA-GO and updates the local cache."""
        self.logger.info("Starting JFA-GO user cache sync task...")
        try:
            users_data, message = await asyncio.to_thread(
                self.jfa_client.get_all_jfa_users
            )
            if users_data is not None:
                self.logger.info(
                    f"Fetched {len(users_data)} users from JFA-GO. Updating local cache."
                )
                await asyncio.to_thread(self.db.upsert_jfa_users, users_data)
                self.logger.info("JFA-GO user cache sync task completed successfully.")
            else:
                self.logger.error(
                    f"Failed to fetch users from JFA-GO for cache sync: {message}"
                )
        except Exception as e:
            self.logger.error(
                f"Error during JFA-GO user cache sync task: {e}", exc_info=True
            )

    @sync_jfa_users_cache_task.before_loop
    async def before_sync_jfa_users_cache(self):
        await self.wait_until_ready()
        interval = get_config_value("sync_settings.jfa_user_sync_interval_hours", 12)
        self.logger.info(
            f"sync_jfa_users_cache_task is about to start. Interval: {interval} hours."
        )

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any) -> None:
        """Handle errors for the bot."""
        self.logger.exception(f"Unhandled error in {event_method}")


def register_event_handlers(bot: JfaGoBot):
    """
    Register event handlers for the bot instance.

    This function sets up the Discord event handlers like on_ready for the bot. It properly
    configures logging for each event and handles exceptions that might occur during event processing.

    Args:
        bot: The JfaGoBot instance to register handlers for
    """

    @bot.event
    async def on_ready():
        """
        Event handler for when the bot is ready and connected to Discord.

        Logs information about the bot's connection status including:
        - Bot username and ID
        - Number of connected guilds
        - Discord.py version
        """
        # Use the bot's logger instance
        bot_logger = (
            bot.logger
            if bot and hasattr(bot, "logger")
            else logging.getLogger("JfaGoBot")
        )
        try:
            bot_logger.info("------ BOT READY ------")
            bot_logger.info(f"Logged in as: {bot.user} (ID: {bot.user.id})")
            bot_logger.info(f"Connected to {len(bot.guilds)} guild(s).")
            bot_logger.info(f"Discord.py Version: {discord.__version__}")
            bot_logger.info("-----------------------")
        except Exception as e:
            bot_logger.error(f"Error in on_ready event: {str(e)}", exc_info=True)
