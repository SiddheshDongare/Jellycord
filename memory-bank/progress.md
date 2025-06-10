# Progress

*This document tracks what's working, what's left to build, current status, known issues, and the evolution of project decisions.*

## Current Status: Phase 2 Complete

- **Phase 1 (JFA-GO User Sync & Local Storage):** Fully Complete.
    - JFA-GO users are periodically synced to a local `jfa_user_cache` table.
    - Bot can query this local cache for user identification.
- **Phase 2 (`/remove_invite` Command Refactor):** Fully Complete.
    - The `/remove_invite` command now has enhanced user identification (Discord ID, mention, Jellyfin username via cache).
    - It attempts to delete the user from JFA-GO.
    - It attempts to delete the JFA-GO invite code.
    - It updates the user's status to 'disabled' in the local `user_invites` table.
    - Provides detailed feedback to the admin.

## What Works

- **Core Bot Functionality:** Startup, logging, configuration loading (`config.yaml`, `.env`), basic event handling.
- **JFA-GO API Client (`jfa_client.py`):**
    - Authentication (token login, refresh).
    - Session management with retries.
    - Creating invites (`create_invite`).
    - Retrieving invite codes by label (`get_invite_code`).
    - Fetching JFA-GO profiles (`get_profiles`) with caching.
    - Extending user expiry (`extend_user_expiry`).
    - Deleting JFA-GO invite codes (`delete_jfa_invite`).
    - Fetching all JFA-GO users (`get_all_jfa_users`).
    - Deleting JFA-GO users by username (`delete_jfa_user_by_username`).
- **Database (`database.py`):
    - Initialization and schema creation (`user_invites`, `admin_actions`, `jfa_user_cache`).
    - Recording and retrieving invite information, including plan type, account expiry, and status.
    - Recording admin actions.
    - Upserting and querying the `jfa_user_cache`.
    - Updating user status (e.g., to 'disabled').
- **Slash Commands:**
    - **`/create-trial-invite`**: Creates trial invites, assigns trial roles, logs action.
    - **`/create-user-invite`**: Creates paid invites, assigns mapped roles, manages JFA-GO user expiry, logs action, DMs user.
    - **`/extend-plan`**: Extends JFA-GO user plans, updates local DB, logs action.
    - **`/remove_invite`**:
        - Identifies users by Discord ID, mention, or Jellyfin username (via local JFA cache).
        - Attempts to delete the identified user from JFA-GO directly.
        - Attempts to delete the associated JFA-GO invite code (if one was stored for the user).
        - Updates the user's status to 'disabled' in the bot's local `user_invites` database table.
        - Logs the multi-step action and provides detailed feedback to the administrator.
- **Background Tasks (`bot.py`):
    - User expiry notifications (DM to user, summary to admin channel).
    - JFA-GO user cache synchronization (`sync_jfa_users_cache_task`).
- **Authorization:** Role-based and channel-based command authorization decorator (`is_in_support_and_authorized`).
- **Messaging (`messaging.py`):** Configurable messages and embeds using `message_templates.json`.
- **Admin Logging:** Actions logged to database and a Discord channel.

## What's Left to Build / Future Enhancements

- **Role Reversion for `/remove_invite`:** [COMPLETED] Implemented logic to remove paid plan roles but keep the trial role. `/create-user-invite` also updated to ensure trial role is assigned with paid plans. `/remove_invite` now correctly handles role reversion based on these rules.
- **Comprehensive Testing:** Especially for the refactored `/remove_invite` with various edge cases and user states, and new role logic in `/create-user-invite` and `/remove_invite`.
- **Error Handling & Resilience:** Continue to improve error handling for API calls and bot operations.
- **Documentation:** Keep all memory bank files and `README.md` up-to-date with any further changes.

## Known Issues

- *(Review and update this section after testing the `/remove_invite` refactor)*
- Potential for slight discrepancies between JFA-GO state and bot's local invite DB state if API calls fail without proper rollback or reconciliation (though current commands attempt to update local state after JFA-GO actions).

## Evolution of Project Decisions

- **Decision (Previous):** `/remove_invite` only deleted the JFA-GO *invite code* and the local bot DB record. It did **not** delete the JFA-GO user account.
- **Decision (Current - Phase 2):** `/remove_invite` now actively attempts to delete the JFA-GO *user account* (by Jellyfin username) first, then the JFA-GO *invite code* (if known), and then updates the local bot DB record's `status` to 'disabled' instead of deleting the record. This provides a more comprehensive removal process.
- **Decision (Phase 1):** Implemented a local JFA user cache (`jfa_user_cache`) synchronized periodically from JFA-GO to improve user identification for commands and reduce direct API calls for lookups.
- **Decision:** Using `asyncio.to_thread` for JFA-GO client calls within async command handlers to prevent blocking the bot.

### Recent Changes

#### Invite Management Improvements
- Fixed issue where creating a new trial invite would fail if a user previously had an invite that was marked as disabled through `/remove_invite`.
- Improved the user lookup logic in `/remove_invite` to allow using Discord usernames directly from the `user_invites` table, making it easier to remove new invites that haven't been claimed yet.
- Enhanced the mention-based user removal in `/remove_invite` by adding fallback logic that tries to match Discord username/display name with Jellyfin username when Discord IDs aren't properly linked in JFA-GO.
- Added force deletion capability to the `/remove_invite` command that attempts to delete JFA-GO users using Discord display names directly, even when they're not found in the JFA cache. This helps with removing users who haven't claimed their invites yet.
- Made force deletion universal across all identifier types in `/remove_invite` (raw username strings, mentions, and IDs), ensuring consistent removal behavior regardless of how users are identified.
- Implemented bidirectional username lookup in `/remove_invite` to properly mark database records as disabled when removing users by their Jellyfin username, fixing an issue where creating new invites would fail after removal.
- Standardized the response format for the `/remove_invite` command with clear visual indicators of operation success/failure, making it easier to understand what actions were taken.
