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
            - Now requires an explicit `user: discord.Member` parameter.
            - Checks for existing active invites for the user.
            - Uses configurable settings for JFA-GO profile (`jfa_go.default_trial_profile`), link validity (`invite_settings.link_validity_days`), account duration (`invite_settings.trial_account_duration_days`), and invite label format (`invite_settings.trial_invite_label_format`).
            - Creates a single-use invite via JFA-GO.
            - Records the invite in the local DB with plan type "Trial" and account expiry.
            - Assigns a configured Discord role (`discord.trial_user_role_name`).
            - Logs the action and sends a success message with the invite link.
        - **Paid/User Invites (`/create-user-invite` in `modules/commands/user_invite_commands.py`):**
            - Takes `user: discord.Member`, `plan_type: str` (with autocomplete fetching profiles from JFA-GO), `months: Optional[int]`, `days: Optional[int]` as input.
            - Validates duration and plan type.
            - Calculates total account duration.
            - Handles existing invites (replaces active unclaimed, allows new if claimed/expired).
            - Creates a single-use invite via JFA-GO.
            - Records invite in local DB with `plan_type` and `account_expires_at`.
            - **Role Management (Enhanced):**
                - Uses `commands.create_user_invite.plan_to_role_map` to find the Discord role for the JFA-GO `plan_type`.
                - Removes previously mapped plan roles from the user (excluding the configured trial role).
                - If a new plan role is mapped and found, it's assigned.
                - **Ensures the configured 'Trial' role (`discord.trial_user_role_name`) is assigned to the user if they don't already have it, regardless of the plan type being 'Trial' or paid.**
                - Logs all role changes.
                - Confirmation embed includes a summary of role management actions.
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
        - **User Removal (`/remove_invite` in `modules/commands/admin_commands.py`):**
            - Takes `user_identifier: str` (Discord ID, @mention, or Jellyfin username).
            - Enhanced user identification logic:
                - Direct Discord ID/mention resolution.
                - Jellyfin username lookup in local `jfa_user_cache` (linking to Discord ID if available).
                - Fallback to checking `user_invites` table by Discord username if direct identification or cache lookup fails.
                - Further fallbacks for mention-based removal by checking Discord username/display name against JFA cache if IDs aren't linked.
                - Force deletion attempts using display names or original identifier if other methods fail.
            - Deletes the user from JFA-GO (if Jellyfin username identified).
            - Deletes the JFA-GO invite code from JFA-GO (if a code was stored in the bot's DB for the user).
            - Updates the user's status to 'disabled' in the local `user_invites` table.
            - **Role Reversion:**
                - If a Discord user is identified as a guild member:
                    - Removes any Discord roles that are mapped as "paid plan roles" (via `commands.create_user_invite.plan_to_role_map`).
                    - **Preserves the configured "Trial" role (`discord.trial_user_role_name`) if the user has it.**
                - Logs role reversion actions and includes them in the confirmation summary.
            - Logs the comprehensive admin action (including all sub-steps and role changes).
            - Provides a detailed confirmation embed to the administrator summarizing all actions taken (JFA-GO user deletion, JFA-GO invite deletion, local DB update, role changes) and any errors.
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

### Invite Management and Administration

- **Trial System:**
  - Create configurable trial invites with `/create-trial-invite`
  - Trial accounts are automatically set to expire after a configurable period
  - Users are notified before expiry
  - Admins can extend plans with `/extend-plan`

- **Invite Removal & User Management:**
  - Remove invites and disable user accounts with `/remove_invite [user_identifier]`
  - Highly flexible user identification:
    - Discord mentions (@username)
    - Discord IDs
    - Discord usernames
    - Jellyfin usernames
  - Intelligent fallback system tries multiple identification methods
  - Clear visual summary of actions with success/failure indicators
  - Preserves historical records while ensuring new invites can be created
  - Attempts both JFA-GO user removal and local database updates

- **Invite Tracking:**
  - All invites are recorded in a local database
  - Bot tracks whether invites have been claimed
  - Invites can be set to expire after a configurable period
  - Status tracking: trial, paid, or disabled

### User Interface

- **Discord Integration:**
  - Slash commands for all functionality
  - Role-based and channel-based command authorization
  - Clear, structured response embeds with consistent formatting
  - Visual status indicators (✅/⚠️/❌) for command success/failure
  - In-depth logging of all admin actions
