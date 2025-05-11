"""Command handlers for admin-related commands."""

import asyncio
import datetime
import logging
import sqlite3
from typing import Optional

import discord
from discord import app_commands

from modules.commands.auth import is_in_support_and_authorized
from modules.models import AdminAction, InviteInfo
from modules.messaging import get_message, create_embed

logger = logging.getLogger(__name__)

# Define managed paid role names (consistency with user_invite_commands.py)
# MANAGED_PAID_ROLE_NAMES = {"Ultimate", "Premium", "Standard", "Basic"} # To be replaced by config
# TRIAL_ROLE_NAME = "Trial" # To be replaced by config


async def _process_remove_invite(
    interaction: discord.Interaction, user_identifier: str
):
    """
    Processes the logic for removing an invite for a specified user.
    Attempts to delete the user from JFA-GO and their invite code from JFA-GO.
    Updates the user's status to 'disabled' in the local database.
    """
    await interaction.response.defer(ephemeral=True)
    bot_instance = interaction.client
    logger = bot_instance.logger
    db = bot_instance.db
    jfa_client = bot_instance.jfa_client  # Will be used in later steps

    target_discord_user: Optional[discord.User] = None
    jfa_user_cache_entry: Optional[sqlite3.Row] = None
    jellyfin_username_to_process: Optional[str] = None  # Renamed for clarity
    discord_user_id_for_db: Optional[str] = None

    identification_notes = []
    error_messages = []

    logger.info(f"[remove_invite] Initiated for identifier: {user_identifier}")

    # 1. User Identification Logic
    try:
        # Attempt to parse as Discord User ID
        if user_identifier.isdigit():
            try:
                user_id_int = int(user_identifier)
                target_discord_user = await bot_instance.fetch_user(user_id_int)
                discord_user_id_for_db = str(target_discord_user.id)
                identification_notes.append(
                    f"Identified as Discord User by ID: {target_discord_user.name} (`{target_discord_user.id}`)."
                )
                logger.info(
                    f"[remove_invite] Identified Discord User by ID: {target_discord_user.name} ({target_discord_user.id})."
                )
            except discord.NotFound:
                logger.warning(
                    f"[remove_invite] Discord User ID '{user_identifier}' not found."
                )
                error_messages.append(f"Discord User ID '{user_identifier}' not found.")
            except ValueError:
                # Should not happen if isdigit() is true, but as a fallback
                logger.warning(
                    f"[remove_invite] Invalid Discord User ID format: {user_identifier}"
                )
                error_messages.append(
                    f"Invalid Discord User ID format: '{user_identifier}'."
                )

        # Attempt to parse as Discord Mention (if not already identified by ID)
        elif user_identifier.startswith("<@") and user_identifier.endswith(">"):
            mention_id_str = user_identifier.strip(
                "<@!>"
            )  # Handles both <@id> and <@!id>
            if mention_id_str.isdigit():
                try:
                    target_discord_user = await bot_instance.fetch_user(
                        int(mention_id_str)
                    )
                    discord_user_id_for_db = str(target_discord_user.id)
                    identification_notes.append(
                        f"Identified as Discord User by mention: {target_discord_user.name} (`{target_discord_user.id}`)."
                    )
                    logger.info(
                        f"[remove_invite] Identified Discord User by mention: {target_discord_user.name} ({target_discord_user.id})."
                    )
                except discord.NotFound:
                    logger.warning(
                        f"[remove_invite] Discord User for mention '{user_identifier}' (ID: {mention_id_str}) not found."
                    )
                    error_messages.append(
                        f"Discord User for mention '{user_identifier}' not found."
                    )
            else:
                logger.warning(
                    f"[remove_invite] Invalid Discord mention format: {user_identifier}"
                )
                error_messages.append(
                    f"Invalid Discord mention format: '{user_identifier}'."
                )

        # If not identified as a Discord user directly, treat as Jellyfin username and check cache
        if (
            not target_discord_user and not error_messages
        ):  # Only proceed if no Discord user found yet and no fatal ID/mention parse error
            logger.info(
                f"[remove_invite] Identifier '{user_identifier}' not a direct Discord user. Checking JFA cache for Jellyfin username."
            )
            jfa_user_cache_entry = await asyncio.to_thread(
                db.get_jfa_user_from_cache_by_jellyfin_username, user_identifier
            )
            if jfa_user_cache_entry:
                jellyfin_username_to_process = jfa_user_cache_entry["jellyfin_username"]
                identification_notes.append(
                    f"Identifier '{user_identifier}' matches Jellyfin username '{jellyfin_username_to_process}' in JFA cache."
                )
                logger.info(
                    f"[remove_invite] Found Jellyfin username '{jellyfin_username_to_process}' in JFA cache."
                )
                if jfa_user_cache_entry["discord_id"]:
                    discord_user_id_for_db = jfa_user_cache_entry["discord_id"]
                    try:
                        # Attempt to fetch the Discord user object if we only had Jellyfin username initially
                        target_discord_user = await bot_instance.fetch_user(
                            int(discord_user_id_for_db)
                        )
                        identification_notes.append(
                            f"Associated Discord User from JFA cache: {target_discord_user.name} (`{discord_user_id_for_db}`)."
                        )
                        logger.info(
                            f"[remove_invite] Fetched associated Discord User {target_discord_user.name} from JFA cache (ID: {discord_user_id_for_db})."
                        )
                    except discord.NotFound:
                        logger.warning(
                            f"[remove_invite] Discord ID '{discord_user_id_for_db}' from JFA cache (for Jellyfin user '{jellyfin_username_to_process}') not found."
                        )
                        identification_notes.append(
                            f"Discord ID '{discord_user_id_for_db}' (from JFA cache) not found on Discord."
                        )
                    except ValueError:
                        logger.warning(
                            f"[remove_invite] Invalid Discord ID '{discord_user_id_for_db}' in JFA cache for '{jellyfin_username_to_process}'."
                        )
                        identification_notes.append(
                            f"Invalid Discord ID '{discord_user_id_for_db}' found in JFA cache."
                        )
            else:
                logger.info(
                    f"[remove_invite] Identifier '{user_identifier}' not found as Jellyfin username in JFA cache."
                )
                # No error_message append here, as it might be a Discord user not in cache but directly identifiable next

        # If we have a target_discord_user but no jellyfin_username_to_process yet, try to find it via their Discord ID in cache
        if target_discord_user and not jellyfin_username_to_process:
            logger.info(
                f"[remove_invite] Have Discord user {target_discord_user.name}, checking JFA cache for linked Jellyfin username."
            )
            cached_by_discord_id = await asyncio.to_thread(
                db.get_jfa_user_from_cache_by_discord_id, str(target_discord_user.id)
            )
            if cached_by_discord_id:
                jellyfin_username_to_process = cached_by_discord_id["jellyfin_username"]
                identification_notes.append(
                    f"Found linked Jellyfin username '{jellyfin_username_to_process}' in JFA cache for Discord user {target_discord_user.name}."
                )
                logger.info(
                    f"[remove_invite] Found Jellyfin username '{jellyfin_username_to_process}' for Discord user {target_discord_user.name} via JFA cache."
                )
            else:
                logger.info(
                    f"[remove_invite] No Jellyfin username linked in JFA cache for Discord user {target_discord_user.name}."
                )
                identification_notes.append(
                    f"No Jellyfin username found in JFA cache for Discord user {target_discord_user.name}."
                )

    except Exception as e:
        logger.error(
            f"[remove_invite] Unexpected error during user identification for '{user_identifier}': {e}",
            exc_info=True,
        )
        error_messages.append(
            f"An unexpected error occurred during user identification: {str(e)}"
        )

    # Final check and response based on identification outcome
    if not target_discord_user and not jellyfin_username_to_process:
        # If error_messages already contains something, it means parsing ID/mention failed.
        # Otherwise, it means the Jellyfin username lookup also failed.
        if not error_messages:
            error_messages.append(
                f"Could not identify user from identifier '{user_identifier}'. Not a recognized Discord user, and not found as a Jellyfin username in the JFA cache."
            )

        logger.warning(
            f"[remove_invite] Failed to identify user from '{user_identifier}'. Errors: {'; '.join(error_messages)}"
        )
        await interaction.edit_original_response(
            embed=create_embed(
                title_key="remove_invite.error_title",
                description_key="remove_invite.error_user_not_found_detailed",  # A new key might be better
                description_kwargs={
                    "user_identifier": user_identifier,
                    "error_details": "\\n- " + "\\n- ".join(error_messages)
                    if error_messages
                    else "No specific error details.",
                },
                color_type="error",
            )
        )
        return

    # At this point, we should have at least one of target_discord_user or jellyfin_username_to_process
    # Or discord_user_id_for_db if a Jellyfin user had a Discord ID in cache that wasn't fetchable but is still valid for DB ops.

    # --- Begin Step 2: JFA-GO User Deletion ---
    if jellyfin_username_to_process:
        logger.info(
            f"[remove_invite] Attempting to delete JFA-GO user: '{jellyfin_username_to_process}'."
        )
        try:
            success, message = await asyncio.to_thread(
                jfa_client.delete_jfa_user_by_username, jellyfin_username_to_process
            )
            if success:
                logger.info(
                    f"[remove_invite] Successfully deleted JFA-GO user: '{jellyfin_username_to_process}'."
                )
                identification_notes.append(
                    f"Successfully deleted Jellyfin user '{jellyfin_username_to_process}' from JFA-GO."
                )
            else:
                # Common case: User not found in JFA-GO. This is not a critical error for the command's continuation.
                logger.warning(
                    f"[remove_invite] Failed to delete JFA-GO user '{jellyfin_username_to_process}': {message}"
                )
                identification_notes.append(
                    f"Attempt to delete Jellyfin user '{jellyfin_username_to_process}' from JFA-GO: {message}."
                )
        except Exception as e:
            logger.error(
                f"[remove_invite] Error during JFA-GO user deletion for '{jellyfin_username_to_process}': {e}",
                exc_info=True,
            )
            error_messages.append(
                f"Error deleting Jellyfin user '{jellyfin_username_to_process}' from JFA-GO: {str(e)}."
            )
            identification_notes.append(
                f"An error occurred while trying to delete Jellyfin user '{jellyfin_username_to_process}' from JFA-GO."
            )
    else:
        logger.info(
            "[remove_invite] No Jellyfin username identified; skipping JFA-GO user deletion step."
        )
        identification_notes.append(
            "No specific Jellyfin username found to attempt JFA-GO user deletion."
        )
    # --- End Step 2 ---

    # --- Begin Step 3: Retrieve Local Invite & Attempt JFA-GO Invite Code Deletion ---
    original_invite_code: Optional[str] = None
    if discord_user_id_for_db:
        logger.info(
            f"[remove_invite] Attempting to retrieve local invite info for Discord ID: {discord_user_id_for_db}"
        )
        try:
            # We need the InviteInfo model here if it's not already imported
            # from modules.models import InviteInfo (ensure this import is at the top of the file)
            invite_info_record: Optional[InviteInfo] = await asyncio.to_thread(
                db.get_invite_info, discord_user_id_for_db
            )
            if invite_info_record:
                original_invite_code = invite_info_record.code
                logger.info(
                    f"[remove_invite] Found local invite code '{original_invite_code}' for Discord ID {discord_user_id_for_db}."
                )
                identification_notes.append(
                    f"Found JFA-GO invite code '{original_invite_code}' in local DB for the Discord user."
                )

                # Now attempt to delete this JFA-GO invite code
                logger.info(
                    f"[remove_invite] Attempting to delete JFA-GO invite code: '{original_invite_code}'."
                )
                success, message = await asyncio.to_thread(
                    jfa_client.delete_jfa_invite, original_invite_code
                )
                if success:
                    logger.info(
                        f"[remove_invite] Successfully deleted JFA-GO invite code: '{original_invite_code}'."
                    )
                    identification_notes.append(
                        f"Successfully deleted JFA-GO invite code '{original_invite_code}'."
                        )
                else:
                    logger.warning(
                        f"[remove_invite] Failed to delete JFA-GO invite code '{original_invite_code}': {message}"
                    )
                    identification_notes.append(
                        f"Attempt to delete JFA-GO invite code '{original_invite_code}': {message}."
                    )
            else:
                logger.info(
                    f"[remove_invite] No local invite record found for Discord ID {discord_user_id_for_db}."
                )
                identification_notes.append(
                    "No active JFA-GO invite code found in local DB for the Discord user (no record to delete from JFA-GO)."
                )
        except Exception as e:
            logger.error(
                f"[remove_invite] Error during local invite retrieval or JFA-GO invite code deletion for Discord ID {discord_user_id_for_db}: {e}",
                exc_info=True,
            )
            error_messages.append(
                f"Error processing local invite/JFA-GO invite code deletion: {str(e)}."
            )
            identification_notes.append(
                "An error occurred while retrieving local invite details or deleting the JFA-GO invite code."
            )
    else:
        logger.info(
            "[remove_invite] No Discord ID available for bot-managed JFA-GO invite code processing."
        )
        # Add to summary only if we didn't primarily act based on a Jellyfin username without a linked Discord user
        if not (jellyfin_username_to_process and not target_discord_user):
            identification_notes.append(
                "Bot-managed JFA-GO invite code actions skipped (no linked Discord User ID for this operation)."
            )
    # --- End Step 3 ---

    # --- Begin Step 4: Update Local DB Status, Log, and Confirm ---
    status_updated_in_db = False
    if discord_user_id_for_db:
        logger.info(
            f"[remove_invite] Attempting to update status to 'disabled' for Discord ID: {discord_user_id_for_db} in local DB."
        )
        try:
            status_updated_in_db = await asyncio.to_thread(
                db.update_user_invite_status, discord_user_id_for_db, "disabled"
            )
            if status_updated_in_db:
                logger.info(
                    f"[remove_invite] Successfully updated status to 'disabled' for Discord ID {discord_user_id_for_db}."
                )
                identification_notes.append(
                    "Successfully set user status to 'disabled' in the local database."
                )
            else:
                # This might happen if the user never had an invite record or another DB issue.
                logger.warning(
                    f"[remove_invite] Could not update status to 'disabled' for Discord ID {discord_user_id_for_db} (no record or DB error)."
                )
                identification_notes.append(
                    "Could not update user status to 'disabled' in local DB (no existing record or a database error occurred)."
                )
        except Exception as e:
            logger.error(
                f"[remove_invite] Error updating local DB status for Discord ID {discord_user_id_for_db}: {e}",
                exc_info=True,
            )
            error_messages.append(f"Error updating user status in local DB: {str(e)}.")
            identification_notes.append(
                "An error occurred while updating user status in the local database."
            )
    else:  # discord_user_id_for_db is None
        logger.info(
            "[remove_invite] No Discord ID available for local database status update."
        )
        # Add to summary only if we didn't primarily act based on a Jellyfin username without a linked Discord user
        if not (jellyfin_username_to_process and not target_discord_user):
            identification_notes.append(
                "Local database status update skipped (no linked Discord User ID for this operation)."
            )

    # Log Admin Action
    admin_user = interaction.user
    # Determine the most relevant username and ID for logging based on what was identified
    log_target_username_display = user_identifier  # Default to the input identifier
    if target_discord_user:
        log_target_username_display = target_discord_user.name
    elif (
        jellyfin_username_to_process
    ):  # If no discord user, use Jellyfin username if available
        log_target_username_display = jellyfin_username_to_process

    log_target_id_display = (
        discord_user_id_for_db
        if discord_user_id_for_db
        else (jellyfin_username_to_process or "N/A")
    )

    # Create a detailed summary for the log
    log_details_summary = "; ".join(identification_notes)
    if error_messages:
        log_details_summary += f". Issues: {'; '.join(error_messages)}"

    if (
        len(log_details_summary) > 1000
    ):  # Cap log details to avoid overly long DB entries
        log_details_summary = log_details_summary[:997] + "..."

    admin_action_log_entry = AdminAction(
        admin_id=str(admin_user.id),
        admin_username=admin_user.name,
        action_type="remove_invite_process",  # More descriptive action type
        target_user_id=log_target_id_display,
        target_username=log_target_username_display,
        details=f"Input: '{user_identifier}'. Actions: {log_details_summary}",
        performed_at=int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
    )
    try:
        await asyncio.to_thread(db.record_admin_action, admin_action_log_entry)
        await bot_instance.log_admin_action(
            admin_action_log_entry
        )  # Also send to Discord log channel
        logger.info(f"[remove_invite] Admin action logged for '{user_identifier}'.")
    except Exception as e:
        logger.error(
            f"[remove_invite] Failed to log admin action for '{user_identifier}': {e}",
            exc_info=True,
        )
        # Non-critical for the user-facing part of the command, but good to note.

    # Send Confirmation Embed
    final_summary_for_embed = "**Summary of Actions Taken:**\n" + "\n".join(
        [f"🔷 {note.strip()}" for note in identification_notes]
    )
    if error_messages:
        final_summary_for_embed += "\n\n**Issues Encountered:**\n" + "\n".join(
            [f"⚠️ {err.strip()}" for err in error_messages]
        )

    # Determine overall success for embed color - success if no errors, warning otherwise.
    # Could be more nuanced, e.g. if JFA-GO user deletion failed but local status update worked.
    embed_color_type = "success" if not error_messages else "warning"
    if (
        not status_updated_in_db and not error_messages and discord_user_id_for_db
    ):  # If main goal of status update failed without other errors
        embed_color_type = "warning"

    confirmation_embed = create_embed(
        title_key="remove_invite.confirmation_title",  # New message key
        description_key="remove_invite.confirmation_description",  # New message key, to be formatted
        color_type=embed_color_type,
        # description_kwargs will be set dynamically below
    )
    confirmation_embed.description = (
        get_message(
            "remove_invite.confirmation_description",
            target_display=log_target_username_display,  # Use the identified name for user-facing message
        )
        + f"\n\n{final_summary_for_embed}"
    )

    if (
        len(confirmation_embed.description) > 4000
    ):  # Discord embed description limit is 4096
        confirmation_embed.description = (
            confirmation_embed.description[:4000] + "... (details truncated)"
        )

    await interaction.edit_original_response(embed=confirmation_embed)
    # --- End Step 4 ---

    # Placeholder for next steps - for now, just report what was found.
    # summary_message = "**User Identification & JFA-GO Deletion Summary:**\\n" + "\\n".join([f"- {note}" for note in identification_notes])
    # if error_messages:
    #     summary_message += "\\n\\n**Issues during identification:**\\n" + "\\n".join([f"- {err}" for err in error_messages])

    # # Determine primary identified entity for messages
    # primary_entity_display = user_identifier
    # if target_discord_user:
    #     primary_entity_display = f"{target_discord_user.name} (`{target_discord_user.id}`)"
    # elif jellyfin_username_to_process:
    #     primary_entity_display = f"Jellyfin User '{jellyfin_username_to_process}'"

    # response_embed = create_embed(
    #     title_key="remove_invite.identification_title", # New message key
    #     description_key="remove_invite.identification_summary", # New message key
    #     description_kwargs={"user_identifier": primary_entity_display, "summary_details": summary_message},
    #     color_type="info"
    # )
    # if len(response_embed.description) > 4000:
    #     response_embed.description = response_embed.description[:4000] + "... (details truncated)"

    # await interaction.edit_reply(embed=response_embed)

    # TODO: Next steps:
    # 2. Attempt to delete user from JFA-GO (if jellyfin_username_to_process) -- DONE
    # 3. Retrieve invite code from bot's DB (if discord_user_id_for_db) -- DONE
    # 4. Attempt to delete JFA-GO invite code (if found) -- DONE (as part of step 3)
    # 5. Update user status in user_invites table to "disabled" (if discord_user_id_for_db) -- DONE
    # 6. Log Admin Action -- DONE
    # 7. Send Confirmation -- DONE


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
        description="Removes a user's invite and disables their record.",
    )
    @app_commands.describe(
        user_identifier="The Discord user (@mention or ID) or their Jellyfin username whose invite should be removed."
    )
    @is_in_support_and_authorized()
    async def remove_invite_tree_command(
        interaction: discord.Interaction, user_identifier: str
    ):
        await _process_remove_invite(interaction, user_identifier)

    # Register error handler
    remove_invite_tree_command.error(remove_invite_error)

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
