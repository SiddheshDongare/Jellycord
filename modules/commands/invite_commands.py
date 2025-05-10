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


async def create_trial_invite_command(interaction: discord.Interaction):
    """Create a trial invite for a user in the current channel/thread."""
    cmd_logger = logger.getChild("create_trial_invite")
    cmd_logger.info(
        f"Command initiated by {interaction.user} (ID: {interaction.user.id}) in channel {interaction.channel.name} ({interaction.channel.id})"
    )

    # Use an initial ephemeral message
    initial_embed = create_embed(
        title_key="trial_invite.creating_title",
        description_key="trial_invite.creating_description",
        description_kwargs={"user_mention": "the user"},  # Placeholder
        color_type="info",
    )
    await interaction.response.send_message(embed=initial_embed, ephemeral=True)

    bot = interaction.client
    target_user = None

    try:
        # --- Find Target User ---
        cmd_logger.debug("Attempting to find target user...")
        if isinstance(interaction.channel, discord.Thread):
            cmd_logger.debug(
                f"Channel is thread '{interaction.channel.name}'. Fetching members."
            )
            try:
                members = await bot.get_thread_members(interaction.channel)
            except Exception as e:
                cmd_logger.error(f"Failed to get thread members: {e}")
                error_embed = create_embed(
                    title_key="trial_invite.error_fetch_thread_members_failed",
                    description_key="trial_invite.error_fetch_thread_members_failed_desc",
                    color_type="error",
                )
                await interaction.edit_original_response(embed=error_embed)
                return
        else:
            cmd_logger.debug(
                f"Channel is text channel '{interaction.channel.name}'. Using channel members."
            )
            members = interaction.channel.members

        # Temporary use of legacy ALLOWED_ROLES to filter staff
        # TODO: Refactor this to use configured roles properly if staff filtering is needed
        allowed_role_names_or_ids = get_config_value(
            "discord.command_authorized_roles", []
        )

        potential_users = []
        for member in members:
            if member.bot:  # Skip bots
                continue
            is_staff = any(
                role.name in allowed_role_names_or_ids
                or str(role.id) in allowed_role_names_or_ids
                for role in member.roles
            )
            if (
                not is_staff and member != interaction.user
            ):  # Skip staff and the command invoker
                potential_users.append(member)
                cmd_logger.debug(
                    f"Found potential non-staff user: {member.display_name} ({member.id})"
                )

        if len(potential_users) == 1:
            target_user = potential_users[0]
            cmd_logger.info(
                f"Found single target user: {target_user.display_name} ({target_user.id})"
            )
        elif len(potential_users) > 1:
            # TODO: Handle multiple potential users (e.g., ask admin to specify)
            cmd_logger.warning(
                f"Found multiple potential users: {[u.display_name for u in potential_users]}. Ambiguous target."
            )
            # For now, just take the first one found as a fallback - needs improvement
            target_user = potential_users[0]
            cmd_logger.info(
                f"Multiple users found, selecting first as target: {target_user.display_name} ({target_user.id})"
            )
        else:
            cmd_logger.warning(
                "No suitable non-staff user found in the channel/thread."
            )
            error_embed = create_embed(
                title_key="trial_invite.error_no_valid_user_found",
                description_key="trial_invite.error_no_valid_user_found_desc",
                color_type="error",
            )
            await interaction.edit_original_response(embed=error_embed)
            return

        # --- Update initial message with identified user ---
        initial_embed.description = get_message(
            "trial_invite.creating_description", user_mention=target_user.mention
        )
        await interaction.edit_original_response(embed=initial_embed)

        # --- Check Existing Invite ---
        cmd_logger.debug(
            f"Checking database for existing invite for user {target_user.id}"
        )
        existing_invite = bot.db.get_invite_info(str(target_user.id))
        if existing_invite and not existing_invite.claimed:
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

        # --- Get Configuration ---
        cmd_logger.debug("Fetching invite configuration settings.")
        link_days = get_config_value("invite_settings.link_validity_days", 1)
        user_days = get_config_value("invite_settings.trial_account_duration_days", 3)
        jfa_profile = get_config_value(
            "jfa_go.default_trial_profile", "Default Profile"
        )
        label_format = get_config_value(
            "invite_settings.trial_invite_label_format",
            "{discord_username}-Trial-{date}",
        )
        base_url = get_config_value("invite_settings.invite_link_base_url", "")
        trial_role_name = get_config_value("discord.trial_user_role_name")

        # --- Create Invite Label ---
        now = datetime.datetime.utcnow()
        label_context = {
            "discord_username": target_user.display_name,
            "discord_user_id": target_user.id,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "datetime": now.isoformat(),
        }
        try:
            invite_label = label_format.format(**label_context)
        except KeyError as e:
            cmd_logger.warning(
                f"Invalid placeholder '{e}' in trial_invite_label_format. Using default label."
            )
            invite_label = f"{target_user.display_name}-Trial-{now.strftime('%Y-%m-%d')}"  # Fallback
        cmd_logger.info(f"Generated invite label: '{invite_label}'")

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
                    (now + datetime.timedelta(days=user_days)).timestamp()
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
            performed_at=int(now.timestamp()),
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
                role_assign_message = (
                    get_message(
                        "trial_invite.error_role_assign_failed_desc",
                        role_name=trial_role_name,
                        user_mention=target_user.mention,
                        invite_code=invite_code,
                    )
                    + " (Role not found)"
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
            timestamp=now,
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
    """Register the invite command with the bot."""

    @bot.tree.command(
        name="create-trial-invite",
        description="Create a standard trial invite for a non-staff user in the channel.",
    )
    @is_in_support_and_authorized()
    async def create_trial_invite(interaction: discord.Interaction):
        await create_trial_invite_command(interaction)

    # Register error handler
    create_trial_invite.error(create_trial_invite_error)
