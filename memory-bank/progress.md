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

- **Refine User Detection in `/create-trial-invite`:** Improve logic for selecting the target user if multiple non-staff users are in a thread/channel, or make it an explicit parameter.
- **Role Reversion for `/remove_invite`:** The previous `/remove_invite` logic included reverting Discord roles. Decide if this should be reintroduced and how it interacts with the new status system.
- **Message Template Review & Expansion:** Ensure all new/modified messages (especially for `/remove_invite`) are present in `message_templates.json` and are clear. Add more templates for flexibility if needed.
- **Comprehensive Testing:** Especially for the refactored `/remove_invite` with various edge cases and user states.
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
