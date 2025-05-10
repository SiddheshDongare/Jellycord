"""Command handlers for admin-related commands."""

import asyncio
import datetime
import logging
from typing import Optional

import discord
from discord import app_commands

from modules.commands.auth import is_in_support_and_authorized
from modules.models import AdminAction
from modules.config import get_config_value
from modules.messaging import get_message, create_embed

logger = logging.getLogger(__name__)

# Define managed paid role names (consistency with user_invite_commands.py)
# MANAGED_PAID_ROLE_NAMES = {"Ultimate", "Premium", "Standard", "Basic"} # To be replaced by config
# TRIAL_ROLE_NAME = "Trial" # To be replaced by config


async def remove_invite_command(interaction: discord.Interaction, user: discord.Member):
    """Remove a trial invite for a user."""
    cmd_logger = logger.getChild("remove_invite")
    cmd_logger.info(
        f"Command initiated by {interaction.user} (ID: {interaction.user.id}) for target user {user.display_name} (ID: {user.id})"
    )
    await interaction.response.defer(thinking=True)

    try:
        # Get the bot instance
        bot = interaction.client

        # Check if user exists in the database
        cmd_logger.debug(
            f"Checking database for invite record for user {user.display_name} (ID: {user.id})"
        )
        existing_invite = bot.db.get_invite_info(str(user.id))
        if not existing_invite:
            cmd_logger.warning(
                f"No trial invite found in DB for user {user.display_name}."
            )
            await interaction.followup.send(
                get_message(
                    "admin_remove_invite.error_no_db_record", user_mention=user.mention
                ),
                ephemeral=True,
            )
            return

        cmd_logger.info(
            f"Found invite record for user {user.display_name} (Code: {existing_invite.code}). Attempting deletion."
        )

        # Delete the invite from the local database
        db_deleted = bot.db.delete_invite(str(user.id))

        if db_deleted:
            cmd_logger.info(
                f"Successfully deleted invite record for user {user.display_name} from database."
            )

            # Attempt to delete from JFA-GO
            jfa_deleted = False
            jfa_message = (
                "JFA-GO invite deletion not attempted (DB deletion failed first)."
            )
            if existing_invite and existing_invite.code:
                cmd_logger.info(
                    f"Attempting to delete invite code {existing_invite.code} from JFA-GO."
                )
                jfa_deleted, jfa_message = bot.jfa_client.delete_jfa_invite(
                    existing_invite.code
                )
                if jfa_deleted:
                    cmd_logger.info(
                        f"Successfully deleted invite {existing_invite.code} from JFA-GO."
                    )
                else:
                    cmd_logger.warning(
                        f"Failed to delete invite {existing_invite.code} from JFA-GO: {jfa_message}"
                    )
            else:
                cmd_logger.warning(
                    "No invite code found in DB record, cannot delete from JFA-GO."
                )
                jfa_message = "No invite code in DB to attempt JFA-GO deletion."

            # Record admin action
            cmd_logger.debug("Recording REMOVE_INVITE admin action.")
            action = AdminAction(
                admin_id=str(interaction.user.id),
                admin_username=interaction.user.display_name,
                action_type="REMOVE_INVITE",
                target_user_id=str(user.id),
                target_username=user.display_name,
                details=f"Removed trial invite with code: {existing_invite.code}",
                performed_at=int(
                    datetime.datetime.now(datetime.timezone.utc).timestamp()
                ),
            )
            bot.db.record_admin_action(action)
            await bot.log_admin_action(action)

            cmd_logger.info("Admin action logged. Preparing confirmation embed.")

            # --- Role Reversion Logic ---
            guild = interaction.guild
            roles_to_remove = []
            role_removed_name = None

            # Get configured role names
            # For paid roles, we need to iterate through the map from config
            plan_to_role_map = get_config_value(
                "commands.create_user_invite.plan_to_role_map", {}
            )
            managed_paid_role_names_config = set(plan_to_role_map.values())

            trial_role_name_config = get_config_value(
                "commands.create_user_invite.trial_role_name", "Trial"
            )
            trial_role_to_add = discord.utils.get(
                guild.roles, name=trial_role_name_config
            )

            # Find current paid role to remove
            for role in user.roles:
                if role.name in managed_paid_role_names_config:
                    roles_to_remove.append(role)
                    role_removed_name = role.name
                    cmd_logger.info(
                        f"Identified paid role '{role.name}' to remove from {user.display_name}."
                    )
                    break

            role_change_success = True
            role_change_messages = []

            if roles_to_remove:
                try:
                    await user.remove_roles(
                        *roles_to_remove, reason="Invite removed by admin"
                    )
                    cmd_logger.info(
                        f"Successfully removed role(s) {[r.name for r in roles_to_remove]} from {user.display_name}."
                    )
                    role_change_messages.append(
                        get_message(
                            "admin_remove_invite.role_summary_removed",
                            role_name=role_removed_name,
                        )
                    )
                except discord.Forbidden:
                    role_change_success = False
                    cmd_logger.error(
                        f"Failed to remove paid role(s) from {user.display_name}: Missing Permissions."
                    )
                    role_change_messages.append(
                        get_message(
                            "admin_remove_invite.role_summary_remove_failed_permission",
                            role_name=role_removed_name,
                        )
                    )
                except discord.HTTPException as e:
                    role_change_success = False
                    cmd_logger.error(
                        f"Failed to remove paid role(s) from {user.display_name} due to API error: {e}"
                    )
                    role_change_messages.append(
                        get_message(
                            "admin_remove_invite.role_summary_remove_failed_api",
                            role_name=role_removed_name,
                        )
                    )
            else:
                cmd_logger.info(
                    f"User {user.display_name} did not have a managed paid role to remove."
                )

            if trial_role_to_add:
                if trial_role_to_add not in user.roles:
                    try:
                        await user.add_roles(
                            trial_role_to_add,
                            reason="Reverted to Trial by admin remove_invite",
                        )
                        cmd_logger.info(
                            f"Successfully assigned '{trial_role_name_config}' role to {user.display_name}."
                        )
                        role_change_messages.append(
                            get_message(
                                "admin_remove_invite.role_summary_assigned",
                                role_name=trial_role_name_config,
                            )
                        )
                    except discord.Forbidden:
                        role_change_success = (
                            False  # Keep overall success false if any part fails
                        )
                        cmd_logger.error(
                            f"Failed to assign '{trial_role_name_config}' role to {user.display_name}: Missing Permissions."
                        )
                        role_change_messages.append(
                            get_message(
                                "admin_remove_invite.role_summary_assign_failed_permission",
                                role_name=trial_role_name_config,
                            )
                        )
                    except discord.HTTPException as e:
                        role_change_success = False  # Keep overall success false
                        cmd_logger.error(
                            f"Failed to assign '{trial_role_name_config}' role to {user.display_name} due to API error: {e}"
                        )
                        role_change_messages.append(
                            get_message(
                                "admin_remove_invite.role_summary_assign_failed_api",
                                role_name=trial_role_name_config,
                            )
                        )
                else:
                    cmd_logger.info(
                        f"User {user.display_name} already has the '{trial_role_name_config}' role."
                    )
                    role_change_messages.append(
                        get_message(
                            "admin_remove_invite.role_summary_already_had_role",
                            role_name=trial_role_name_config,
                        )
                    )
            else:
                # If trial_role_name_config was set but role not found, it's a config issue on server side
                if (
                    trial_role_name_config
                ):  # Only a warning if it was configured but not found
                    role_change_success = False  # Potentially, or just a warning if this isn't critical for success
                    cmd_logger.warning(
                        f"Could not find the '{trial_role_name_config}' role in the server. Cannot assign."
                    )
                    role_change_messages.append(
                        get_message(
                            "admin_remove_invite.role_summary_role_not_found_to_assign",
                            role_name=trial_role_name_config,
                        )
                    )
                # If trial_role_name_config was empty/None from start, it's fine, no message needed here.

            cmd_logger.info("Role changes processed. Sending confirmation embed.")

            embed_color_type = (
                "warning" if not role_change_success else "success"
            )  # Use success if all good, warning otherwise
            # Original logic used red for success here, which is unusual. Changed to success (green). Error (red) might be too strong if only role failed but DB was ok.

            embed = create_embed(
                title_key="admin_remove_invite.embed_title",
                description_key="admin_remove_invite.embed_description",
                description_kwargs={"user_mention": user.mention},
                color_type=embed_color_type,
                timestamp=datetime.datetime.now(datetime.timezone.utc),  # UTC
            )
            embed.add_field(
                name=get_message("admin_remove_invite.field_db_details_name"),
                value=get_message(
                    "admin_remove_invite.field_db_details_value",
                    user_display_name=user.display_name,
                    invite_code=existing_invite.code,
                ),
                inline=False,
            )

            jfa_status_key = (
                "admin_remove_invite.field_jfa_status_success"
                if jfa_deleted
                else "admin_remove_invite.field_jfa_status_failed"
            )
            if (
                not existing_invite.code and not jfa_deleted
            ):  # If no code, and no deletion attempted/failed
                jfa_message = get_message(
                    "admin_remove_invite.field_jfa_status_no_code"
                )
                jfa_status_key = "admin_remove_invite.field_jfa_status_failed"  # Or a neutral status? For now, failed implies it wasn't a success.

            embed.add_field(
                name=get_message("admin_remove_invite.field_jfa_status_name"),
                value=get_message(
                    "admin_remove_invite.field_jfa_status_value",
                    status=get_message(jfa_status_key),
                    details=jfa_message,
                ),
                inline=False,
            )
            embed.add_field(
                name=get_message("admin_remove_invite.field_role_summary_name"),
                value="\n".join(role_change_messages)
                if role_change_messages
                else get_message("admin_remove_invite.role_summary_no_changes"),
                inline=False,
            )

            embed.set_footer(text=get_message("admin_remove_invite.embed_footer"))

            await interaction.followup.send(embed=embed)
        else:
            # This case means DB deletion failed
            cmd_logger.error(
                f"Failed to remove trial invite for {user.display_name}. delete_invite returned False unexpectedly."
            )
            await interaction.followup.send(
                get_message(
                    "admin_remove_invite.error_db_delete_failed",
                    user_mention=user.mention,
                ),
                ephemeral=True,
            )

    except Exception as e:
        cmd_logger.error(
            f"Unhandled error in remove_invite command: {str(e)}", exc_info=True
        )
        # Check if response already sent before sending error message
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "An unexpected error occurred processing the remove invite command.",
                ephemeral=True,
            )
        else:
            try:
                await interaction.followup.send(
                    "An unexpected error occurred processing the remove invite command.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                cmd_logger.error("Failed to send error followup message.")


async def remove_invite_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    """Error handler for the remove_invite command."""
    err_logger = logger.getChild("remove_invite.error")
    err_logger.debug(
        f"Error handler invoked for user {interaction.user} with error type {type(error)}"
    )
    try:
        if isinstance(error, app_commands.errors.CheckFailure):
            err_logger.warning(
                f"CheckFailure suppressed for user {interaction.user}: {error}"
            )
            pass  # Handled by check
        elif isinstance(error, app_commands.errors.CommandInvokeError):
            err_logger.error(
                f"CommandInvokeError caught (error logged previously): {error.original}"
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while executing the command.", ephemeral=True
                )
        else:
            err_logger.error(
                f"Unhandled AppCommandError in remove_invite: {type(error).__name__} - {str(error)}",
                exc_info=True,
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An unexpected application command error occurred.", ephemeral=True
                )
    except Exception as e:
        err_logger.critical(
            f"CRITICAL: Error within remove_invite_error handler: {str(e)}",
            exc_info=True,
        )


def setup_commands(bot):
    """Register the commands with the bot."""

    @bot.tree.command(
        name="remove_invite",
        description="Remove a trial invite for a user.",
    )
    @is_in_support_and_authorized()
    async def remove_invite(interaction: discord.Interaction, user: discord.Member):
        await remove_invite_command(interaction, user)

    # Register error handler
    remove_invite.error(remove_invite_error)

    # --- Extend Plan Command ---

    async def extend_plan_command(
        interaction: discord.Interaction,
        user: discord.Member,
        jfa_username: str,
        months: Optional[int] = 0,
        days: Optional[int] = 0,
        hours: Optional[int] = 0,
        minutes: Optional[int] = 0,
        reason: Optional[str] = None,
        notify: bool = True,
    ):
        cmd_logger = logger.getChild("extend_plan")
        cmd_logger.info(
            f"Command initiated by {interaction.user} for Discord user {user.display_name} (ID: {user.id}) / JFA user '{jfa_username}' "
            f"(M={months}, D={days}, h={hours}, m={minutes}, Reason='{reason}', Notify={notify})"
        )
        await interaction.response.defer(thinking=True)

        # Default None duration components to 0 for comparison and calculation
        months = months or 0
        days = days or 0
        hours = hours or 0
        minutes = minutes or 0

        try:
            bot = interaction.client

            # Validate that the user exists in JFA-GO
            jfa_user_details = await asyncio.to_thread(
                bot.jfa_client.get_jfa_user_details_by_username, jfa_username
            )
            if not jfa_user_details:
                cmd_logger.warning(f"JFA-GO user {jfa_username} not found.")
                await interaction.followup.send(
                    get_message(
                        "admin_extend_plan.error_user_not_found_jfa",
                        jfa_username=jfa_username,
                        user_mention=user.mention,
                    ),
                    ephemeral=True,
                )
                return

            current_expiry_ts = jfa_user_details.get("expires")  # Timestamp or None
            # Convert current_expiry_ts to datetime object if it exists, make it UTC aware
            current_expiry_dt = (
                datetime.datetime.fromtimestamp(
                    current_expiry_ts, datetime.timezone.utc
                )
                if current_expiry_ts
                else datetime.datetime.now(datetime.timezone.utc)
            )

            total_seconds_to_add = 0
            duration_parts = []

            if months and months > 0:
                total_seconds_to_add += months * 30 * 86400  # Approx month
                duration_parts.append(f"{months} month(s)")
            if days and days > 0:
                total_seconds_to_add += days * 86400
                duration_parts.append(f"{days} day(s)")
            if hours and hours > 0:
                total_seconds_to_add += hours * 3600
                duration_parts.append(f"{hours} hour(s)")
            if minutes and minutes > 0:
                total_seconds_to_add += minutes * 60
                duration_parts.append(f"{minutes} minute(s)")

            if total_seconds_to_add == 0:
                cmd_logger.warning("No duration specified for extension.")
                await interaction.followup.send(
                    get_message("admin_extend_plan.error_duration_not_specified"),
                    ephemeral=True,
                )
                return

            if (
                months < 0 or days < 0 or hours < 0 or minutes < 0
            ):  # Simpler check for any negative
                cmd_logger.warning("Negative duration specified for extension.")
                await interaction.followup.send(
                    get_message("admin_extend_plan.error_duration_negative"),
                    ephemeral=True,
                )
                return

            duration_str = ", ".join(duration_parts) if duration_parts else "None"

            # Calculate new expiry from current expiry or now if not set
            new_expiry_dt = current_expiry_dt + datetime.timedelta(
                seconds=total_seconds_to_add
            )
            new_expiry_ts = int(new_expiry_dt.timestamp())

            success, message = await asyncio.to_thread(
                bot.jfa_client.extend_user_expiry,
                jfa_username=jfa_username,
                exact_timestamp=new_expiry_ts,
                notify=notify,
            )
            jfa_notify_success = notify if success else False

            if not success:
                cmd_logger.error(
                    f"JFA-GO failed to extend plan for {jfa_username}: {message}"
                )
                await interaction.followup.send(
                    get_message(
                        "admin_extend_plan.error_jfa_extend_failed",
                        jfa_username=jfa_username,
                        user_mention=user.mention,
                        error_message=message,
                    ),
                    ephemeral=True,
                )
                return

            # Log admin action
            admin_action_details = (
                f"Extended plan for JFA-GO user: {jfa_username} (Discord: {user.display_name}). "
                f"Added: {duration_str}. New Expiry: {new_expiry_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}. "
                f"Reason: {reason if reason else 'N/A'}. JFA Notified: {jfa_notify_success}"
            )
            action = AdminAction(
                admin_id=str(interaction.user.id),
                admin_username=interaction.user.display_name,
                action_type="EXTEND_PLAN",
                target_user_id=str(user.id),  # Discord user ID
                target_username=jfa_username,  # JFA-GO username as primary target id for this action
                details=admin_action_details,
                performed_at=int(
                    datetime.datetime.now(datetime.timezone.utc).timestamp()
                ),  # UTC
            )
            bot.db.record_admin_action(action)
            await bot.log_admin_action(action)

            # Send confirmation
            # Human readable new expiry (e.g., "in 2 months and 3 days") - placeholder for now
            # For a more precise human-readable relative time, a library like `humanize` would be good, or a simpler custom formatter.
            # Simple version:
            time_diff = new_expiry_dt - datetime.datetime.now(datetime.timezone.utc)
            human_readable_new_expiry = (
                f"in approx. {time_diff.days} days"
                if time_diff.days > 0
                else "Expired or very soon"
            )
            if time_diff.days < 0:
                human_readable_new_expiry = "already passed"

            embed = create_embed(
                title_key="admin_extend_plan.embed_success_title",
                description_key="admin_extend_plan.embed_success_description",
                description_kwargs={
                    "jfa_username": jfa_username,
                    "user_mention": user.mention,
                },
                color_type="success",
                timestamp=datetime.datetime.now(datetime.timezone.utc),  # UTC
            )
            embed.add_field(
                name=get_message("admin_extend_plan.field_jfa_user_name"),
                value=get_message(
                    "admin_extend_plan.field_jfa_user_value", jfa_username=jfa_username
                ),
                inline=True,
            )
            embed.add_field(
                name=get_message("admin_extend_plan.field_discord_user_name"),
                value=get_message(
                    "admin_extend_plan.field_discord_user_value",
                    user_mention=user.mention,
                ),
                inline=True,
            )
            embed.add_field(
                name=get_message("admin_extend_plan.field_duration_added_name"),
                value=get_message(
                    "admin_extend_plan.field_duration_added_value",
                    duration_string=duration_str,
                ),
                inline=False,
            )
            embed.add_field(
                name=get_message("admin_extend_plan.field_new_expiry_name"),
                value=get_message(
                    "admin_extend_plan.field_new_expiry_value",
                    new_expiry_string=new_expiry_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    new_expiry_human=human_readable_new_expiry,
                ),
                inline=False,
            )
            if reason:
                embed.add_field(
                    name=get_message("admin_extend_plan.field_reason_name"),
                    value=get_message(
                        "admin_extend_plan.field_reason_value", reason=reason
                    ),
                    inline=False,
                )

            notified_value_key = (
                "admin_extend_plan.field_jfa_notified_yes"
                if jfa_notify_success
                else "admin_extend_plan.field_jfa_notified_no_unknown"
            )
            embed.add_field(
                name=get_message("admin_extend_plan.field_jfa_notified_name"),
                value=get_message(notified_value_key),
                inline=True,
            )

            embed.set_footer(
                text=get_message(
                    "admin_extend_plan.embed_footer",
                    admin_user_name=interaction.user.display_name,
                )
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            cmd_logger.error(
                f"Unhandled error in extend_plan_command: {str(e)}", exc_info=True
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    get_message("admin_extend_plan.generic_error_command_processing"),
                    ephemeral=True,
                )
            else:
                try:
                    await interaction.followup.send(
                        get_message(
                            "admin_extend_plan.generic_error_command_processing"
                        ),
                        ephemeral=True,
                    )
                except discord.HTTPException:
                    cmd_logger.error(
                        "Failed to send error followup for extend_plan_command."
                    )

    async def extend_plan_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """Error handler for the extend_plan command."""
        err_logger = logger.getChild(
            "extend-plan.error"
        )  # Consistent naming for child logger
        err_logger.debug(
            f"Error handler invoked for user {interaction.user} with error type {type(error)}"
        )
        try:
            if isinstance(error, app_commands.errors.CheckFailure):
                err_logger.warning(
                    f"CheckFailure suppressed for user {interaction.user}: {error}"
                )
                pass  # Auth check should handle its own response
            elif isinstance(error, app_commands.errors.CommandInvokeError):
                err_logger.error(
                    f"CommandInvokeError caught (error logged previously by command): {error.original}"
                )
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        get_message("admin_extend_plan.error_invoke_error_if_not_done"),
                        ephemeral=True,
                    )
            else:
                err_logger.error(
                    f"Unhandled AppCommandError in extend_plan: {type(error).__name__} - {str(error)}",
                    exc_info=True,
                )
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        get_message(
                            "admin_extend_plan.error_app_command_error_if_not_done"
                        ),
                        ephemeral=True,
                    )
        except Exception as e:
            err_logger.critical(
                f"CRITICAL: Error within extend_plan_error handler: {str(e)}",
                exc_info=True,
            )

    @bot.tree.command(
        name="extend-plan",
        description="Extend the account expiry duration for a JFA-GO user (Admin only)",
    )
    @app_commands.describe(
        user="The Discord user associated with the JFA-GO account",
        jfa_username="The exact username of the user in JFA-GO",
        months="Number of months to add (e.g., 3)",
        days="Number of days to add (e.g., 15)",
        hours="Number of hours to add",
        minutes="Number of minutes to add",
        reason="Optional reason for the extension (logged)",
        notify="Whether JFA-GO should notify the user (default: True)",
    )
    @is_in_support_and_authorized()
    async def extend_plan(
        interaction: discord.Interaction,
        user: discord.Member,
        jfa_username: str,
        months: Optional[int] = None,
        days: Optional[int] = None,
        hours: Optional[int] = None,
        minutes: Optional[int] = None,
        reason: Optional[str] = None,
        notify: Optional[bool] = True,
    ):
        # Handle potential None for boolean
        notify_bool = True if notify is None else notify
        await extend_plan_command(
            interaction,
            user,
            jfa_username,
            months,
            days,
            hours,
            minutes,
            reason,
            notify_bool,
        )

    extend_plan.error(extend_plan_error)
