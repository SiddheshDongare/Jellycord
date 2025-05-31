"""Command handlers for invite-related commands."""

import asyncio
import datetime
import logging

import discord
from discord import app_commands

from modules.commands.auth import is_in_support_and_authorized
from modules.config import get_config_value

# Import the new messaging functions
from modules.messaging import create_embed, get_message
from modules.models import AdminAction

logger = logging.getLogger(__name__)


async def create_trial_invite_command(
    interaction: discord.Interaction, user: discord.Member
):
    """Create a trial invite for a specified user."""
    cmd_logger = logger.getChild("create_trial_invite")
    cmd_logger.info(
        f"Command initiated by {interaction.user} (ID: {interaction.user.id}) for target user {user.display_name} (ID: {user.id}) in channel {interaction.channel.name} ({interaction.channel.id})"
    )

    # Use an initial ephemeral message
    initial_embed = create_embed(
        title_key="trial_invite.creating_title",
        description_key="trial_invite.creating_description_for_user",
        description_kwargs={"user_mention": user.mention},
        color_type="info",
    )
    await interaction.response.send_message(embed=initial_embed, ephemeral=True)

    bot = interaction.client
    target_user = user

    try:
        # --- Check Existing Invite ---
        cmd_logger.debug(
            f"Checking database for existing invite for user {target_user.id}"
        )
        existing_invite = bot.db.get_invite_info(str(target_user.id))
        if existing_invite and not existing_invite.claimed:
            # Check if the invite is disabled - if so, allow creating a new one
            if existing_invite.status != "disabled":
                cmd_logger.warning(
                    f"User {target_user.display_name} already has an active invite code: {existing_invite.code}"
                )
                error_embed = create_embed(
                    title_key="trial_invite.error_already_exists_title",
                    description_key="trial_invite.error_already_exists_desc",
                    description_kwargs={
                        "user_mention": target_user.mention,
                        "existing_code": existing_invite.code,
                    },
                    color_type="error",
                )
                await interaction.edit_original_response(embed=error_embed)
                return
            else:
                cmd_logger.info(
                    f"User {target_user.display_name} has a disabled invite. Creating a new one."
                )

        # --- Get Configuration ---
        cmd_logger.debug("Fetching invite configuration settings.")
        link_days = get_config_value("invite_settings.link_validity_days", 1)
        user_days = get_config_value("invite_settings.trial_account_duration_days", 3)
        jfa_profile = get_config_value(
            "jfa_go.default_trial_profile", "Default Profile"
        )
        trial_role_name = get_config_value("discord.trial_user_role_name", "Trial")
        base_url = get_config_value("jfa_go.base_url")
        invite_label_format = get_config_value(
            "invite_settings.trial_invite_label_format",
            "{discord_username}-Trial-{date}",
        )

        if not base_url:
            cmd_logger.error("JFA-GO base URL not configured.")
            error_embed = create_embed(
                title_key="trial_invite.error_config_missing_title",
                description_key="trial_invite.error_config_missing_desc_base_url",
                color_type="error",
            )
            await interaction.edit_original_response(embed=error_embed)
            return

        # --- Create Invite Label ---
        try:
            invite_label = invite_label_format.format(
                discord_username=target_user.display_name,
                date=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
            )
        except KeyError as e:
            cmd_logger.error(f"Invalid placeholder in invite_label_format: {e}")
            error_embed = create_embed(
                title_key="trial_invite.error_config_label_format_title",
                description_key="trial_invite.error_config_label_format_desc",
                description_kwargs={"error_details": str(e)},
                color_type="error",
            )
            await interaction.edit_original_response(embed=error_embed)
            return

        # --- Create JFA-GO Invite ---
        cmd_logger.debug("Attempting to create invite via JFA-GO client...")
        success, message = await asyncio.to_thread(
            bot.jfa_client.create_invite,
            label=invite_label,
            profile_name=jfa_profile,
            user_duration_days=user_days,
            invite_duration_days=link_days,
            multiple_uses=False,
            remaining_uses=1,
        )

        if not success:
            cmd_logger.error(f"Failed to create JFA-GO invite: {message}")
            error_embed = create_embed(
                title_key="trial_invite.error_jfa_create_failed_title",
                description_key="trial_invite.error_jfa_create_failed_desc",
                description_kwargs={"error_message": message},
                color_type="error",
            )
            await interaction.edit_original_response(embed=error_embed)
            return

        # --- Get Invite Code ---
        cmd_logger.debug("Attempting to retrieve invite code from JFA-GO...")
        invite_code, message = await asyncio.to_thread(
            bot.jfa_client.get_invite_code, invite_label
        )

        if not invite_code:
            cmd_logger.error(f"Failed to get invite code after creation: {message}")
            error_embed = create_embed(
                title_key="trial_invite.error_jfa_get_code_failed_title",
                description_key="trial_invite.error_jfa_get_code_failed_desc",
                description_kwargs={"error_message": message},
                color_type="error",
            )
            # Invite might exist in JFA-GO but bot failed to get code/record it
            await interaction.edit_original_response(embed=error_embed)
            return
        cmd_logger.info(f"Successfully retrieved invite code: {invite_code}")

        # --- Record Invite in DB ---
        cmd_logger.debug("Recording invite in local database...")
        try:
            bot.db.record_invite(
                user_id=str(target_user.id),
                username=target_user.display_name,
                invite_code=invite_code,
                plan_type="Trial",  # Indicate this is a trial invite
                account_expires_at=int(
                    (
                        datetime.datetime.now(datetime.timezone.utc)
                        + datetime.timedelta(days=user_days)
                    ).timestamp()
                ),
            )
        except Exception as e:
            cmd_logger.error(f"Failed to record invite in DB: {e}", exc_info=True)
            # Critical: Invite exists in JFA-GO but not in local DB
            error_embed = create_embed(
                title_key="trial_invite.error_db_record_failed_title",
                description_key="trial_invite.error_db_record_failed_desc",
                description_kwargs={"invite_code": invite_code},
                color_type="error",
            )
            await interaction.edit_original_response(embed=error_embed)
            # Consider attempting to delete the JFA-GO invite here if DB record fails?
            return
        cmd_logger.info("Successfully recorded invite in database.")

        # --- Log Admin Action ---
        cmd_logger.debug("Recording admin action...")
        action = AdminAction(
            admin_id=str(interaction.user.id),
            admin_username=interaction.user.display_name,
            action_type="CREATE_INVITE",
            target_user_id=str(target_user.id),
            target_username=target_user.display_name,
            details=f"Created trial invite. Code: {invite_code}, Profile: {jfa_profile}, Account Duration: {user_days} days, Link Duration: {link_days} days.",
            performed_at=int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        )
        bot.db.record_admin_action(action)
        await bot.log_admin_action(action)
        cmd_logger.info("Admin action recorded.")

        # --- Assign Trial Role (Optional) ---
        role_assign_message = None
        if trial_role_name:
            cmd_logger.info(
                f"Attempting to assign configured trial role: '{trial_role_name}'"
            )
            trial_role = discord.utils.get(
                interaction.guild.roles, name=trial_role_name
            )
            if trial_role:
                if trial_role not in target_user.roles:
                    try:
                        await target_user.add_roles(
                            trial_role,
                            reason=f"Trial Invite created by {interaction.user.display_name}",
                        )
                        cmd_logger.info(
                            f"Successfully assigned role '{trial_role_name}' to {target_user.display_name}"
                        )
                    except discord.Forbidden:
                        cmd_logger.error(
                            f"Failed to assign role '{trial_role_name}' to {target_user.display_name}: Bot lacks permissions."
                        )
                        role_assign_message = get_message(
                            "trial_invite.error_role_assign_failed_desc",
                            role_name=trial_role_name,
                            user_mention=target_user.mention,
                            invite_code=invite_code,
                        )
                    except discord.HTTPException as e:
                        cmd_logger.error(
                            f"Failed to assign role '{trial_role_name}' to {target_user.display_name} due to API error: {e}"
                        )
                        role_assign_message = get_message(
                            "trial_invite.error_role_assign_failed_desc",
                            role_name=trial_role_name,
                            user_mention=target_user.mention,
                            invite_code=invite_code,
                        )
                else:
                    cmd_logger.debug(
                        f"User {target_user.display_name} already has role '{trial_role_name}'."
                    )
            else:
                cmd_logger.warning(
                    f"Configured trial role '{trial_role_name}' not found in server."
                )
                role_assign_message = get_message(
                    "trial_invite.error_role_assign_failed_role_not_found_full",
                    role_name=trial_role_name,
                    user_mention=target_user.mention,
                    invite_code=invite_code,
                )
        else:
            cmd_logger.debug("No trial role configured to assign.")

        # --- Send Final Confirmation ---
        invite_url = f"{base_url.rstrip('/')}/{invite_code}"
        cmd_logger.info(f"Sending success confirmation for invite {invite_code}")

        success_embed = create_embed(
            title_key="trial_invite.success_title",
            description_key="trial_invite.success_description",
            description_kwargs={"user_mention": target_user.mention},
            color_type="success",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        success_embed.add_field(
            name=get_message("trial_invite.field_invite_link"),
            value=get_message("trial_invite.field_link_value", invite_url=invite_url),
            inline=False,
        )
        success_embed.add_field(
            name=get_message("trial_invite.field_account_duration"),
            value=get_message("trial_invite.field_duration_value", days=user_days),
            inline=True,
        )
        success_embed.add_field(
            name=get_message("trial_invite.field_notes"),
            value=get_message(
                "trial_invite.field_notes_value",
                link_days=link_days,
                account_days=user_days,
            ),
            inline=False,
        )

        # Optionally add role assignment status
        if role_assign_message:
            success_embed.add_field(
                name=get_message("trial_invite.error_role_assign_failed"),
                value=role_assign_message,
                inline=False,
            )

        # Send to channel (not ephemeral)
        await interaction.followup.send(embed=success_embed)

        # Delete the initial ephemeral message now that the followup is sent
        try:
            await interaction.delete_original_response()
        except discord.HTTPException as e:
            # Log if deletion fails, but don't halt the process
            cmd_logger.warning(f"Could not delete original ephemeral response: {e}")

        cmd_logger.info(
            f"Trial invite process completed successfully for {target_user.display_name}."
        )

    except Exception as e:
        cmd_logger.error(
            f"Unhandled error in create_trial_invite: {str(e)}", exc_info=True
        )
        # Send generic error message if possible
        if not interaction.response.is_done():
            # If the initial response wasn't even sent
            await interaction.response.send_message(
                get_message("errors.generic_command_error"), ephemeral=True
            )
        else:
            try:
                error_embed = create_embed(
                    title_key="errors.generic_command_error",
                    # No description key needed if title is sufficient
                    color_type="error",
                )
                await interaction.edit_original_response(
                    content=None, embed=error_embed
                )
            except discord.HTTPException:
                cmd_logger.error("Failed to send final error message update.")


async def create_trial_invite_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    """Generic error handler for the trial invite command."""
    err_logger = logger.getChild("create_trial_invite.error")
    err_logger.error(
        f"Error handled by create_trial_invite_error: {type(error).__name__} - {error}",
        exc_info=True,
    )

    # Use generic error message from template
    error_message = get_message("errors.generic_command_error")

    if isinstance(error, app_commands.errors.CheckFailure):
        err_logger.warning(
            f"CheckFailure suppressed for user {interaction.user}: {error}"
        )
        # Auth check should have already sent a specific message
        pass
    elif not interaction.response.is_done():
        await interaction.response.send_message(error_message, ephemeral=True)
    else:
        try:
            await interaction.followup.send(error_message, ephemeral=True)
        except discord.HTTPException:
            err_logger.error("Failed to send error followup message.")


def setup_commands(bot):
    """Register the commands with the bot."""
    command_name = get_config_value(
        "commands.create_trial_invite.name", "create-trial-invite"
    )
    command_description = get_config_value(
        "commands.create_trial_invite.description", "Creates a trial invite for a user."
    )

    @bot.tree.command(name=command_name, description=command_description)
    @app_commands.describe(user="The user to create a trial invite for.")
    @is_in_support_and_authorized()
    async def trial_invite_wrapper(
        interaction: discord.Interaction, user: discord.Member
    ):
        await create_trial_invite_command(interaction, user)

    @trial_invite_wrapper.error
    async def create_trial_invite_error_handler(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        await create_trial_invite_error(interaction, error)

    bot.logger.info(f"Command '{command_name}' (Trial Invite) setup.")
