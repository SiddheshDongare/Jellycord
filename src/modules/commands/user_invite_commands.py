"""Command handlers for paid invite related commands."""

import asyncio
import datetime
import logging
from typing import List, Optional

import discord
from discord import app_commands

from modules.commands.auth import is_in_support_and_authorized
from modules.config import get_config_value
from modules.models import AdminAction
from modules.messaging import get_message, create_embed

logger = logging.getLogger(__name__)


async def plan_type_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """Autocompletes plan types by fetching from JFA-GO."""
    ac_logger = logger.getChild("plan_type_autocomplete")
    ac_logger.debug(
        f"Autocomplete triggered by user {interaction.user} with current value: '{current}'"
    )

    # Get the bot instance
    bot = interaction.client

    profiles, error_msg = await asyncio.to_thread(bot.jfa_client.get_profiles)
    if profiles is None:
        ac_logger.error(f"Autocomplete failed to fetch profiles: {error_msg}")
        return []  # Return empty list on error

    ac_logger.debug(f"Fetched {len(profiles)} profiles. Filtering with '{current}'")

    choices = [
        app_commands.Choice(name=profile, value=profile)
        for profile in profiles
        if current.lower() in profile.lower()
    ]
    ac_logger.debug(f"Returning {len(choices)} choices for autocomplete.")
    return choices[:25]  # Discord limits choices to 25


async def create_user_invite_command(
    interaction: discord.Interaction,
    user: discord.Member,
    plan_type: str,
    months: Optional[int] = None,
    days: Optional[int] = None,
):
    """Create a user invite for a user with specified plan and duration."""
    cmd_logger = logger.getChild("create-user-invite")
    cmd_logger.info(
        f"Command initiated by {interaction.user} for target {user.display_name} (Plan: {plan_type}, Months: {months}, Days: {days})"
    )
    await interaction.response.defer(thinking=True)

    try:
        # Get the bot instance
        bot = interaction.client

        # --- Validation ---
        if months is None and days is None:
            cmd_logger.warning("Validation failed: Both months and days are None.")
            await interaction.followup.send(
                get_message("user_invite.validation_duration_missing"),
                ephemeral=True,
            )
            return

        if (months is not None and months < 0) or (days is not None and days < 0):
            cmd_logger.warning(
                f"Validation failed: Negative duration provided (Months: {months}, Days: {days})."
            )
            await interaction.followup.send(
                get_message("user_invite.validation_duration_negative"),
                ephemeral=True,
            )
            return

        # Validate plan_type against available profiles
        cmd_logger.debug(f"Validating selected plan type: {plan_type}")
        valid_profiles, fetch_msg = await asyncio.to_thread(bot.jfa_client.get_profiles)
        if valid_profiles is None:
            cmd_logger.error(
                f"Could not validate plan type because profile fetch failed: {fetch_msg}"
            )
            await interaction.followup.send(
                get_message(
                    "user_invite.validation_jfa_profiles_fetch_error",
                    error_message=fetch_msg,
                ),
                ephemeral=True,
            )
            return

        if plan_type not in valid_profiles:
            cmd_logger.warning(
                f"Validation failed: Invalid plan type '{plan_type}' selected. Available: {valid_profiles}"
            )
            profile_list_str = (
                ", ".join(valid_profiles)
                if valid_profiles
                else get_message(
                    "user_invite.validation_invalid_plan_type_no_profiles_fallback"
                )
            )
            await interaction.followup.send(
                get_message(
                    "user_invite.validation_invalid_plan_type",
                    plan_type=plan_type,
                    profile_list=profile_list_str,
                ),
                ephemeral=True,
            )
            return

        cmd_logger.debug(f"Plan type '{plan_type}' is valid.")

        # --- Calculate Duration ---
        total_user_days = 0
        duration_str_parts = []
        if months is not None and months > 0:
            # Assuming 30 days per month for calculation
            total_user_days += months * 30
            duration_str_parts.append(f"{months} month(s)")
        if days is not None and days > 0:
            total_user_days += days
            duration_str_parts.append(f"{days} day(s)")

        if total_user_days <= 0:
            # This case might happen if user enters 0 for both, handle defensively
            cmd_logger.warning(
                f"Validation failed: Calculated total duration is not positive ({total_user_days} days)."
            )
            await interaction.followup.send(
                get_message("user_invite.validation_duration_not_positive"),
                ephemeral=True,
            )
            return

        duration_str = " and ".join(duration_str_parts)
        invite_duration_days = get_config_value(
            "commands.create_user_invite.link_validity_days"
        )

        # --- Check Existing Invite ---
        existing_invite_info_key = None
        existing_invite_info_params = {}
        cmd_logger.debug(
            f"Checking database for existing invite for user {user.display_name} (ID: {user.id})"
        )
        existing_invite = bot.db.get_invite_info(str(user.id))
        if existing_invite:
            current_time = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            expiry_dt = datetime.datetime.fromtimestamp(
                existing_invite.expires_at, tz=datetime.timezone.utc
            )
            is_expired = current_time >= existing_invite.expires_at

            log_message = (
                f"User {user.display_name} (ID: {user.id}) already has an invite record: "
                f"Code={existing_invite.code}, Claimed={existing_invite.claimed}, "
                f"Expires={expiry_dt.strftime('%Y-%m-%d %H:%M')}. "
            )

            if existing_invite.claimed:
                log_message += "Invite was claimed. Creating new user invite."
            elif is_expired:
                log_message += "Invite is expired. Creating new user invite."
                existing_invite_info_key = (
                    "user_invite.confirm_channel_note_previous_expired"
                )
                existing_invite_info_params = {
                    "expiry_date": expiry_dt.strftime("%Y-%m-%d")
                }
            else:  # Active and unclaimed
                log_message += (
                    "Invite is active and unclaimed. Replacing with new user invite."
                )
                existing_invite_info_key = (
                    "user_invite.confirm_channel_note_previous_active_unclaimed"
                )
                existing_invite_info_params = {
                    "expiry_date_time": expiry_dt.strftime("%Y-%m-%d %H:%M %Z")
                }

            cmd_logger.info(log_message)  # Log the detailed check result
            # No need to explicitly block, record_invite will update the record.
        else:
            existing_invite_info_key = None
            existing_invite_info_params = {}

        # --- Create Invite ---
        label = f"{user.display_name} - {plan_type} - {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')}"
        cmd_logger.info(
            f"Attempting to create user invite via JFA-GO with label: {label}, plan: {plan_type}, user_days: {total_user_days}, invite_days: {invite_duration_days}"
        )

        success, message = await asyncio.to_thread(
            bot.jfa_client.create_invite,
            label=label,
            profile_name=plan_type,
            user_duration_days=total_user_days,
            invite_duration_days=invite_duration_days,
            remaining_uses=1,  # Paid invites are single use
        )

        if not success:
            cmd_logger.error(f"JFA-GO failed to create user invite: {message}")
            await interaction.followup.send(
                get_message(
                    "user_invite.error_jfa_create_failed", error_message=message
                ),
                ephemeral=True,
            )
            return

        # --- Get Invite Code ---
        invite_code, message = await asyncio.to_thread(
            bot.jfa_client.get_invite_code, label
        )
        if not invite_code:
            # Attempt to fetch again with slight delay in case of race condition
            cmd_logger.warning(
                f"Initial fetch failed for invite code '{label}', retrying after delay... Error: {message}"
            )
            await asyncio.sleep(1)
            invite_code, message = await asyncio.to_thread(
                bot.jfa_client.get_invite_code, label
            )

            if not invite_code:
                cmd_logger.error(
                    f"Failed to retrieve user invite code from JFA-GO after retry: {message}"
                )
                await interaction.followup.send(
                    get_message(
                        "user_invite.error_jfa_get_code_failed",
                        user_mention=user.mention,
                        error_message=message,
                    ),
                    ephemeral=True,
                )
                # Consider *not* recording in DB if code is missing? Or record with null code?
                # For now, we'll stop here.
                return

        # --- Record Invite & Admin Action ---
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_ts = int(now_utc.timestamp())
        paid_account_expiry_ts = now_ts + (total_user_days * 86400)

        # INVITE_BASE_URL will be fetched from config
        invite_base_url = get_config_value("invite_settings.invite_link_base_url")
        if not invite_base_url:
            # Fallback or error if not configured - for now, log and use a sensible default or raise error
            cmd_logger.error("invite_settings.invite_link_base_url is not configured!")
            # Depending on strictness, either use a placeholder, a default, or stop
            await interaction.followup.send(
                get_message("errors.config_missing_invite_base_url"), ephemeral=True
            )
            return

        bot.db.record_invite(
            user_id=str(user.id),
            username=user.display_name,
            invite_code=invite_code,
            plan_type=plan_type,
            account_expires_at=paid_account_expiry_ts,
        )
        invite_url = f"{invite_base_url}{invite_code}"

        cmd_logger.info(
            f"User invite recorded for {user.display_name}. Attempting to assign role for plan: {plan_type}."
        )

        # --- Log Admin Action ---
        # (Admin action logging remains largely the same, but details might be updated based on role changes)
        # Ensure log_admin_action can handle slightly longer details if role changes are included.

        action_details_parts = [
            f"Created user invite: {invite_code}",
            f"Plan: {plan_type}",
            f"User Account Valid for: {duration_str} ({total_user_days} days)",
            f"Invite Link Valid for: {invite_duration_days} day(s)",
        ]

        # --- Role Management ---
        assigned_roles_messages = []
        removed_roles_messages = []
        trial_role_assigned_during_paid_flow = False

        # Get configured trial role name
        trial_role_name_config = get_config_value("discord.trial_user_role_name")
        trial_role_obj = None
        if trial_role_name_config:
            trial_role_obj = discord.utils.get(
                interaction.guild.roles, name=trial_role_name_config
            )

        # Remove previous mapped roles and old trial role (if different from new trial role)
        roles_to_remove_from_user = []
        plan_role_map = get_config_value(
            "commands.create_user_invite.plan_to_role_map", {}
        )
        all_mapped_roles_names_or_ids = [
            str(r_name_or_id) for r_name_or_id in plan_role_map.values()
        ]

        # Add the configured trial role to the list of roles that could potentially be removed
        # if it's different from the current trial role being assigned or checked.
        # This handles cases where the trial role name might have changed in config.
        # For this flow, we primarily ensure the *current* configured trial role is present.
        # Old trial roles (if name changed) would be caught by the general mapped role removal.

        for role in user.roles:
            if (
                str(role.name) in all_mapped_roles_names_or_ids
                or str(role.id) in all_mapped_roles_names_or_ids
            ):
                if (
                    trial_role_obj and role.id == trial_role_obj.id
                ):  # Don't remove the trial role if it's one of the mapped ones AND it's THE trial role
                    continue
                roles_to_remove_from_user.append(role)
            elif (
                trial_role_name_config
                and role.name == trial_role_name_config
                and not (trial_role_obj and role.id == trial_role_obj.id)
            ):  # remove old trial role if name changed
                roles_to_remove_from_user.append(role)

        if roles_to_remove_from_user:
            removed_role_names = []
            for role_to_remove in roles_to_remove_from_user:
                try:
                    await user.remove_roles(
                        role_to_remove,
                        reason=f"User invite created by {interaction.user.display_name} - removing old plan role.",
                    )
                    removed_roles_messages.append(
                        get_message(
                            "user_invite.role_removed_log",
                            role_name=role_to_remove.name,
                        )
                    )
                    removed_role_names.append(role_to_remove.name)
                except discord.Forbidden:
                    removed_roles_messages.append(
                        get_message(
                            "user_invite.warning_old_role_remove_failed_permission",
                            role_name=role_to_remove.name,
                        )
                    )
                except discord.HTTPException:
                    removed_roles_messages.append(
                        get_message(
                            "user_invite.warning_old_role_remove_failed_api",
                            role_name=role_to_remove.name,
                        )
                    )
            if removed_role_names:
                action_details_parts.append(
                    f"Removed old roles: {', '.join(removed_role_names)}."
                )

        # Assign new role based on plan_to_role_map
        new_role_name_or_id = plan_role_map.get(plan_type)
        new_role_assigned = False
        if new_role_name_or_id:
            new_role = discord.utils.get(
                interaction.guild.roles, name=str(new_role_name_or_id)
            )
            if not new_role:  # Try by ID if name failed
                try:
                    new_role = interaction.guild.get_role(int(new_role_name_or_id))
                except ValueError:
                    pass  # new_role_name_or_id was not an int

            if new_role:
                if new_role not in user.roles:
                    try:
                        await user.add_roles(
                            new_role,
                            reason=f"User invite created by {interaction.user.display_name} - plan: {plan_type}",
                        )
                        assigned_roles_messages.append(
                            get_message(
                                "user_invite.role_assigned_log", role_name=new_role.name
                            )
                        )
                        action_details_parts.append(
                            f"Assigned plan role: {new_role.name}."
                        )
                        new_role_assigned = True
                    except discord.Forbidden:
                        assigned_roles_messages.append(
                            get_message(
                                "user_invite.warning_new_role_assign_failed_permission",
                                role_name=new_role.name,
                            )
                        )
                    except discord.HTTPException:
                        assigned_roles_messages.append(
                            get_message(
                                "user_invite.warning_new_role_assign_failed_api",
                                role_name=new_role.name,
                            )
                        )
                else:
                    assigned_roles_messages.append(
                        get_message(
                            "user_invite.role_already_had_log", role_name=new_role.name
                        )
                    )
                    action_details_parts.append(
                        f"User already had plan role: {new_role.name}."
                    )
                    new_role_assigned = True  # Considered assigned for logic purposes
            else:
                assigned_roles_messages.append(
                    get_message(
                        "user_invite.warning_new_role_not_found",
                        role_name=new_role_name_or_id,
                    )
                )
        else:
            assigned_roles_messages.append(
                get_message(
                    "user_invite.info_new_role_mapping_not_found", plan_type=plan_type
                )
            )

        # Assign Trial Role if not already present
        if trial_role_obj:
            if trial_role_obj not in user.roles:
                try:
                    await user.add_roles(
                        trial_role_obj,
                        reason=f"User invite (paid plan) created by {interaction.user.display_name} - ensuring trial role presence.",
                    )
                    assigned_roles_messages.append(
                        get_message(
                            "user_invite.trial_role_assigned_log",
                            role_name=trial_role_obj.name,
                        )
                    )
                    action_details_parts.append(
                        f"Assigned trial role: {trial_role_obj.name}."
                    )
                    trial_role_assigned_during_paid_flow = True
                except discord.Forbidden:
                    assigned_roles_messages.append(
                        get_message(
                            "user_invite.warning_trial_role_assign_failed_permission",
                            role_name=trial_role_obj.name,
                        )
                    )
                except discord.HTTPException:
                    assigned_roles_messages.append(
                        get_message(
                            "user_invite.warning_trial_role_assign_failed_api",
                            role_name=trial_role_obj.name,
                        )
                    )
            else:
                assigned_roles_messages.append(
                    get_message(
                        "user_invite.trial_role_already_had_log",
                        role_name=trial_role_obj.name,
                    )
                )
                action_details_parts.append(
                    f"User already had trial role: {trial_role_obj.name}."
                )
                trial_role_assigned_during_paid_flow = (
                    True  # User has it, counts as success for this check
                )
        elif trial_role_name_config:  # Configured but not found
            assigned_roles_messages.append(
                get_message(
                    "user_invite.warning_trial_role_not_found",
                    role_name=trial_role_name_config,
                )
            )

        action_details_full = "\n".join(action_details_parts)
        if len(action_details_full) > 1000:  # Discord embed field value limit
            action_details_full = action_details_full[:997] + "..."

        action = AdminAction(
            admin_id=str(interaction.user.id),
            admin_username=interaction.user.display_name,
            action_type="CREATE_USER_INVITE",
            target_user_id=str(user.id),
            target_username=user.display_name,
            details=action_details_full,
            performed_at=now_ts,
        )
        bot.db.record_admin_action(action)
        await bot.log_admin_action(action)

        # --- Send Confirmation (Channel) ---
        embed = create_embed(
            title_key="user_invite.confirm_channel_title",
            description_key="user_invite.confirm_channel_description",
            description_kwargs={"user_mention": user.mention},
            color_type="success",
            timestamp=now_utc,
        )
        embed.add_field(
            name=get_message("user_invite.confirm_channel_user_field_name"),
            value=get_message(
                "user_invite.confirm_channel_user_field_value",
                user_mention=user.mention,
            ),
            inline=True,
        )
        embed.add_field(
            name=get_message("user_invite.confirm_channel_plan_field_name"),
            value=get_message(
                "user_invite.confirm_channel_plan_field_value", plan_type=plan_type
            ),
            inline=True,
        )
        embed.add_field(
            name=get_message("user_invite.confirm_channel_duration_field_name"),
            value=get_message(
                "user_invite.confirm_channel_duration_field_value",
                duration_str=duration_str,
                total_user_days=total_user_days,
            ),
            inline=False,
        )
        embed.add_field(
            name=get_message("user_invite.confirm_channel_link_field_name"),
            value=get_message(
                "user_invite.confirm_channel_link_field_value", invite_url=invite_url
            ),
            inline=False,
        )
        embed.add_field(
            name=get_message("user_invite.confirm_channel_validity_field_name"),
            value=get_message(
                "user_invite.confirm_channel_validity_field_value",
                invite_duration_days=invite_duration_days,
            ),
            inline=False,
        )
        embed.set_footer(
            text=get_message(
                "user_invite.confirm_channel_footer",
                admin_user_name=interaction.user.display_name,
            )
        )

        # Add note about existing invite if relevant
        if existing_invite_info_key:
            cmd_logger.debug(
                f"Adding note to embed about existing invite: {existing_invite_info_key}"
            )
            embed.add_field(
                name=get_message("user_invite.confirm_channel_note_field_name"),
                value=get_message(
                    existing_invite_info_key, **existing_invite_info_params
                ),
                inline=False,
            )

        # Add role management messages to the channel confirmation embed
        if assigned_roles_messages or removed_roles_messages:
            role_management_summary_parts = []
            if removed_roles_messages:
                role_management_summary_parts.extend(removed_roles_messages)
            if assigned_roles_messages:
                role_management_summary_parts.extend(assigned_roles_messages)

            role_management_summary = "\n".join(
                role_management_summary_parts
            )  # Use \n for newlines in embed

            if role_management_summary.strip():  # Ensure not just empty strings
                embed.add_field(
                    name=get_message(
                        "user_invite.confirm_channel_role_management_name"
                    ),
                    value=role_management_summary.strip()[
                        :1024
                    ],  # Max field value length
                    inline=False,
                )

        await interaction.followup.send(embed=embed)

        cmd_logger.info(
            f"Confirmation sent. Attempting to send DM to user {user.display_name}."
        )

        # --- Send Confirmation (DM) ---
        try:
            dm_embed = create_embed(
                title_key="user_invite.confirm_dm_title",
                description_key="user_invite.confirm_dm_description",
                description_kwargs={
                    "user_name": user.display_name,
                    "guild_name": interaction.guild.name,
                },
                color_type="blue",
            )
            dm_embed.add_field(
                name=get_message("user_invite.confirm_channel_plan_field_name"),
                value=get_message(
                    "user_invite.confirm_channel_plan_field_value", plan_type=plan_type
                ),
                inline=True,
            )
            dm_embed.add_field(
                name=get_message("user_invite.confirm_channel_duration_field_name"),
                value=get_message(
                    "user_invite.confirm_channel_duration_field_value",
                    duration_str=duration_str,
                    total_user_days=total_user_days,
                ),
                inline=True,
            )
            dm_embed.add_field(
                name=get_message("user_invite.confirm_channel_link_field_name"),
                value=get_message(
                    "user_invite.confirm_channel_link_field_value",
                    invite_url=invite_url,
                ),
                inline=False,
            )
            dm_embed.add_field(
                name=get_message("user_invite.confirm_channel_validity_field_name"),
                value=get_message(
                    "user_invite.confirm_channel_validity_field_value",
                    invite_duration_days=invite_duration_days,
                ),
                inline=False,
            )
            dm_embed.set_footer(text=get_message("user_invite.confirm_dm_footer"))

            # Add role management messages to DM as well, if configured or desired
            # For now, keeping DM simpler, but this could be added.

            await user.send(embed=dm_embed)
            cmd_logger.info(f"Successfully sent user invite DM to {user.display_name}.")
            await interaction.followup.send(
                get_message("user_invite.ephemeral_dm_sent", user_mention=user.mention),
                ephemeral=True,
            )
        except discord.Forbidden:
            cmd_logger.warning(
                f"Could not send user invite DM to {user.display_name} (ID: {user.id}): DMs disabled or bot blocked."
            )
            await interaction.followup.send(
                get_message(
                    "user_invite.ephemeral_dm_failed_permission",
                    user_mention=user.mention,
                ),
                ephemeral=True,
            )
        except Exception as e:
            cmd_logger.error(
                f"Error sending user invite DM to user {user.display_name}: {str(e)}",
                exc_info=True,
            )
            await interaction.followup.send(
                get_message(
                    "user_invite.ephemeral_dm_failed_unexpected",
                    user_mention=user.mention,
                ),
                ephemeral=True,
            )

    except Exception as e:
        cmd_logger.error(
            f"Unhandled error in create_user_invite command: {str(e)}", exc_info=True
        )
        # Check if response already sent before sending error message
        if not interaction.response.is_done():
            await interaction.response.send_message(
                get_message("user_invite.error_generic_command_processing"),
                ephemeral=True,
            )
        else:
            # If initial response was sent, followup might be possible
            try:
                await interaction.followup.send(
                    get_message("user_invite.error_generic_command_processing"),
                    ephemeral=True,
                )
            except discord.HTTPException:
                cmd_logger.error("Failed to send error followup message.")


async def create_user_invite_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    """Error handler for the create_user_invite command."""
    err_logger = logger.getChild("create-user-invite.error")
    err_logger.debug(
        f"Error handler invoked for user {interaction.user} with error type {type(error)}"
    )
    try:
        if isinstance(error, app_commands.errors.CheckFailure):
            # The check failure message is handled by the decorator/check itself
            err_logger.warning(
                f"CheckFailure suppressed for user {interaction.user}: {error}"
            )
            pass
        elif isinstance(error, app_commands.errors.CommandInvokeError):
            # Errors inside the command function are already logged by the main try/except
            err_logger.error(
                f"CommandInvokeError caught (error logged previously): {error.original}"
            )
            # Send a generic message only if no response has been sent yet
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    get_message("user_invite.error_invoke_error_if_not_done"),
                    ephemeral=True,
                )
        else:
            # Log other unexpected AppCommandErrors
            err_logger.error(
                f"Unhandled AppCommandError in create_user_invite: {type(error).__name__} - {str(error)}",
                exc_info=True,
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    get_message("user_invite.error_app_command_error_if_not_done"),
                    ephemeral=True,
                )
    except Exception as e:
        # Catch errors within the error handler itself
        err_logger.critical(
            f"CRITICAL: Error within create_user_invite_error handler: {str(e)}",
            exc_info=True,
        )


def setup_commands(bot):
    """Register the commands with the bot."""

    @bot.tree.command(
        name="create-user-invite",
        description="Create a JFA-GO user invite for a user with specific plan and duration",
    )
    @app_commands.autocomplete(plan_type=plan_type_autocomplete)
    @app_commands.describe(
        user="The user to create the invite for",
        plan_type="The JFA-GO profile/plan to assign",
        months="Number of months the user account is valid (optional)",
        days="Number of days the user account is valid (optional)",
    )
    @is_in_support_and_authorized()
    async def create_user_invite(
        interaction: discord.Interaction,
        user: discord.Member,
        plan_type: str,
        months: Optional[int] = None,
        days: Optional[int] = None,
    ):
        await create_user_invite_command(interaction, user, plan_type, months, days)

    # Register error handler
    create_user_invite.error(create_user_invite_error)
