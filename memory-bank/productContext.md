# Product Context

*This document explains the "why" behind the project, the problems it solves, its intended functionality, and user experience goals.*

## Problem Statement

- Managing user access to a Jellyfin media server, especially in a community setting using Discord, can be manual and time-consuming.
- There's a need for a tool that integrates JFA-GO (a Jellyfin account manager) with Discord to simplify and automate invite generation, user lifecycle management, and administrative tasks.

## Intended Functionality

- The bot, Jellycord, acts as a companion to JFA-GO, allowing authorized Discord users to:
    - Execute slash commands within designated Discord channels/threads. Authorization is two-fold (handled by `modules/commands/auth.py`):
        1.  Channel Check: Command must be in a channel/category listed in `discord.command_channel_ids`.
        2.  Role Check: User must have one of the roles listed in `discord.command_authorized_roles`.
    - Create configurable trial and paid invite links for Jellyfin, managed through JFA-GO.
        - **Trial Invites (`/create-trial-invite` in `modules/commands/invite_commands.py`):**
            - Automatically detects a non-staff target user in the current channel/thread (logic for multiple users needs refinement).
            - Checks for existing active invites for the user.
            - Uses configurable settings for JFA-GO profile (`jfa_go.default_trial_profile`), link validity (`invite_settings.link_validity_days`), account duration (`invite_settings.trial_account_duration_days`), and invite label format (`invite_settings.trial_invite_label_format`).
            - Creates a single-use invite via JFA-GO.
            - Records the invite in the local DB with plan type "Trial" and account expiry.
            - Assigns a configured Discord role (`discord.trial_user_role_name`).
            - Logs the action and sends a success message with the invite link.
        - **Paid/User Invites (`/create-user-invite` in `modules/commands/user_invite_commands.py`):**
            - Takes `user: discord.Member`, `plan_type: str` (with autocomplete fetching profiles from JFA-GO), `months: Optional[int]`, `days: Optional[int]` as input.
            - Validates that duration (months or days) is provided, non-negative, and that the total user days are positive. `plan_type` is validated against JFA-GO profiles.
            - Calculates total account duration in days (months are converted as 30 days each).
            - Handles existing invites: proceeds if claimed or expired (noting this in confirmation), or if active & unclaimed (replacing it and noting).
            - Creates a single-use invite via JFA-GO using `plan_type` as the JFA-GO profile name, the calculated `total_user_days` for account validity, and a configured link validity duration (`commands.create_user_invite.link_validity_days`).
            - Records the invite in the local database with the given `plan_type` and calculated `account_expires_at` timestamp.
            - **Role Management:**
                - Uses `commands.create_user_invite.plan_to_role_map` to find the Discord role corresponding to the JFA-GO `plan_type`.
                - If a role is mapped, it's assigned to the user.
                - Attempts to remove any previously assigned roles by this bot that are part of the `plan_to_role_map` values or the configured `commands.create_user_invite.trial_role_name` to prevent role accumulation.
            - Logs the administrative action.
            - Sends a confirmation message to the channel and a direct message to the target user with invite details.
    - Manage aspects of user accounts such as extending plan durations. This involves JFA-GO API calls to modify user expiry dates.
        - **Extend Plan (`/extend-plan` in `modules/commands/admin_commands.py`):**
            - Takes Discord `user`, `jfa_username`, duration components (`months`, `days`, `hours`, `minutes`), optional `reason`, and `notify` flag (for JFA-GO notification).
            - At least one non-negative duration component is required.
            - Calls JFA-GO API to extend the specified user's account.
            - If successful, logs admin action, updates the local DB record for the Discord user (if JFA-GO username matches) with the new expiry and clears notification status, and sends a confirmation.
            - Handles JFA-GO errors (user not found, extension failed).
    - Remove existing invite records from the bot's database and attempt JFA-GO deletion.
        - **`/remove_invite <discord_user_or_id_or_jellyfin_username>`**: (Admin)
            - This command now performs a comprehensive removal process.
            - It identifies the user by Discord @mention, Discord User ID, or Jellyfin username.
            - If a Jellyfin username is determined (either directly provided or found via the bot's JFA-GO user cache from a Discord ID), the bot attempts to **delete the user directly from JFA-GO**.
            - If the user was associated with a specific invite code in the bot's local database, it attempts to **delete that JFA-GO invite code** as well.
            - The user's record in the bot's local `user_invites` table is updated by setting their `status` to 'disabled' (the record is not deleted, preserving history).
            - The command also attempts to revert any Discord roles that were assigned by the bot.
            - A detailed summary of actions taken (and any errors encountered during the process, such as JFA-GO API failures) is provided in the confirmation message and logged for administrators.
    - Retrieve JFA-GO profile names to present as options in commands.
    - Delete invites from JFA-GO (though this is currently limited in the `/remove_invite` command scope).
    - Look up JFA-GO user details.
    - Receive automated notifications (e.g., users get DMs before account expiry). This is handled by a background task checking JFA-GO user expiries and cross-referencing with a local database to avoid spamming, with summaries sent to an admin channel.
- The bot logs administrative actions (creations, deletions, extensions) to a local SQLite database and optionally to a specific Discord channel (`discord.admin_log_channel_id`) as formatted embeds for auditability.
- The bot's behavior, including messages and visual elements (embeds), is highly customizable through configuration files (`config.yaml`, `message_templates.json`).

## User Experience (UX) Goals

- **Efficiency:** Streamline the process of managing Jellyfin invites and user accounts directly from Discord.
- **Control:** Provide administrators with role-based access and clear logging of actions.
- **Customization:** Allow server owners to tailor the bot's messages, appearance, and behavior to match their community's branding and operational needs. This is heavily supported by `message_templates.json` and `modules/messaging.py`, allowing full control over text, embed titles, descriptions, fields, colors, and footers.
- **Clarity:** Offer clear feedback to users and administrators through configurable messages and embed notifications for actions performed, facilitated by the messaging module.
- **Automation:** Reduce manual intervention for tasks like expiry notifications.

### User Lifecycle & Data Management

- **Invite Generation & Tracking:** When an admin creates an invite (trial or user-specific), the bot:
    1. Calls JFA-GO to create the invite code and potentially the user account.
    2. Records the Discord User ID, generated JFA-GO invite code, creation time, plan type, and initial `status` ('trial' or 'paid') in its local `user_invites` database table.
- **Invite Claiming:** (Conceptual - current implementation might differ slightly in directness)
- **Account Expiry & Notifications:**
    - The bot periodically checks for users in its `user_invites` table whose `account_expires_at` timestamp is approaching.
    - It sends DMs to users based on configurable notification windows (e.g., 3 days before, on day of expiry).
    - It records `last_notified_at` to prevent spamming.
- **JFA-GO User Synchronization:**
    - A background task (`sync_jfa_users_cache_task`) runs periodically (e.g., every 12 hours).
    - It calls `jfa_client.get_all_jfa_users()` to get all user details from JFA-GO.
    - This data is then upserted into the local `jfa_user_cache` table in the bot's database. This cache is used for quick lookups by Discord ID or Jellyfin username, especially for commands like `/remove_invite` or `/extend_expiry`.
- **User Status:** The `user_invites` table in the bot's database maintains a `status` for each tracked user, which can be 'trial', 'paid', or 'disabled'. This status is updated when invites are created or users are removed.

### Error Handling and Logging
