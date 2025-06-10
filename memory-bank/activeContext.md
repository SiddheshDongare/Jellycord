# Active Context

*This document outlines the current work focus, recent changes, next steps, and active decisions.*

## Current Work Focus

- **Codebase Restructuring:** The user has requested a significant restructuring of the project's directory layout.
    - `main.py` and `modules/` to be moved into a new `src/` directory.
    - Log files (`*.log`) to be placed in a new `logs/` directory.
    - Configuration files (`config.yaml`, `message_templates.json`, and their `.example` counterparts) to be moved into a new `config/` directory.
    - The `images/` directory to be moved into a new `data/` directory.
    - The SQLite database (`jfa_bot.db`) to be placed in a new `data/db/` directory.
- **Refactoring for New Structure:** This involves updating code to correctly reference files in their new locations, particularly in `modules/config.py`, `modules/logging_setup.py`, `modules/database.py`, and `modules/messaging.py` to handle new default paths and ensure directory creation.
- **Import Paths:** Ensuring import statements work correctly after `main.py` and `modules/` are moved into `src/`. Current assessment is that direct imports in `main.py` (e.g., `from modules.bot import ...`) should continue to work if `main.py` is run from `src/` (e.g., `python src/main.py`) as `src/` will be in `sys.path`.
- **Phase 2 Completion:** Finalizing the refactor of the `/remove_invite` command.
- **Memory Bank Update:** Ensuring all relevant memory bank files accurately reflect the recent major changes to JFA-GO integration and command logic.

## Recent Changes & Key Decisions

- **`/remove_invite` Command Refactor (Completed):**
    - The `/remove_invite [user_identifier]` command in `modules/commands/admin_commands.py` has been significantly overhauled.
    - **User Identification:** It now attempts to identify the target user via multiple methods:
        1. Direct Discord User ID.
        2. Discord User Mention.
        3. Jellyfin Username (by querying the `jfa_user_cache` table in `database.py`).
        - If a Discord user is identified, it also attempts to find a linked Jellyfin username from the `jfa_user_cache`.
    - **Deletion Process:**
        1. **JFA-GO User Deletion:** If a Jellyfin username is identified, the command attempts to delete the user directly from JFA-GO using the new `jfa_client.delete_jfa_user_by_username()` method.
        2. **JFA-GO Invite Code Deletion:** If a Discord user ID is known and a corresponding invite record exists in the local `user_invites` table, the command attempts to delete the stored JFA-GO *invite code* from JFA-GO using `jfa_client.delete_jfa_invite()`.
        3. **Local Status Update:** If a Discord user ID is known, the command updates the user's record in the `user_invites` table by setting their `status` to 'disabled' using `db.update_user_invite_status()`. The record itself is *not* deleted from `user_invites`.
    - **Logging & Confirmation:** The command provides a detailed summary of all actions attempted and their outcomes to the administrator and logs this information.
- **JFA-GO Client (`jfa_client.py`):**
    - The `delete_jfa_user_by_username(jellyfin_username: str)` method was refactored. It now first calls `get_all_jfa_users()` to find the JFA-GO user's `id` by their `jellyfin_username` (matching the `name` field), and then sends a `DELETE /users` request to JFA-GO with a payload of `{"users": ["<user_id>"]}`.
- **Database (`database.py`):**
    - The `user_invites` table now includes a `status TEXT` column (e.g., 'trial', 'paid', 'disabled').
    - The `record_invite()` method now sets the initial `status` based on the plan type.
    - Added `update_user_invite_status(user_id: str, status: str)` method.
- **JFA-GO User Sync & Cache (Phase 1 - Completed):**
    - Implemented `jfa_client.get_all_jfa_users()`.
    - Added `jfa_user_cache` table to `database.py` with `upsert_jfa_users` and lookup methods.
    - Integrated `sync_jfa_users_cache_task` in `bot.py` to periodically refresh this cache.
    - This cache is now crucial for identifying users in commands like `/remove_invite`.
- Corrected newline character handling in `/create-user-invite` command confirmation embed.
- Synced `config.yaml.example` with `config.yaml` after correcting `plan_to_role_map` path.
- Removed an obsolete commented-out code block from `/remove_invite` command.
- Updated default file paths in `modules/config.py` (`DEFAULT_CONFIG_STRUCTURE`, `DEFAULT_CONFIG_FILE_PATH`, `DEFAULT_TEMPLATES_FILE_PATH`).
- Updated `modules/logging_setup.py` to create the `logs/` directory and use the new default log file path.
- Updated `modules/database.py` to create the `data/db/` directory and use the new default database file path.
- Updated `modules/messaging.py` to use the new default templates file path from `config/` and attempt to create the `config/` directory if needed for the default templates file.

## Next Steps

1. User to manually create the new directory structure (`src`, `config`, `data`, `data/db`, `data/images`, `logs`).
2. User to manually move the specified files and folders into their new locations.
3. User to add `__init__.py` to `src/` (recommended).
4. Test the bot thoroughly after restructuring to catch any path or import issues.
5. Update `README.md` to reflect the new directory structure and any changes to running the bot (e.g., `python src/main.py`).

## Active Decisions & Considerations

- The primary approach for code changes is to modify default path configurations and ensure necessary directories are created by the relevant modules (`config.py`, `logging_setup.py`, `database.py`, `messaging.py`).
- Import statements within `main.py` are assumed to work without direct modification due to Python's `sys.path` behavior when running a script from a subdirectory, but this needs testing by the user.
- Inter-module imports within the `modules` package should remain unaffected as their relative structure is preserved.
- **`/remove_invite` Database Record:** Decided to only update the `status` to 'disabled' in the `user_invites` table upon removal, rather than deleting the record. This preserves historical association.
- **Error Handling in `/remove_invite`:** The command now provides more detailed feedback on which steps succeeded or failed (e.g., JFA-GO user deletion vs. invite code deletion vs. local DB update).
- **Username Lookup in `/remove_invite`:** Improved user lookup to check the `username` field in the `user_invites` table, enabling removal of invites using Discord usernames even for newly created invites that haven't been claimed yet.
- **Fallback Username Matching in `/remove_invite`:** Added fallback logic that tries to match a Discord username/display name with a Jellyfin username when removing users via mention. This helps when Discord IDs aren't properly linked in JFA-GO but usernames match.
- **Force Deletion Attempt in `/remove_invite`:** Enhanced the command to attempt deleting a JFA-GO user using the Discord display name directly, even when the user isn't found in the JFA cache. This helps delete users who haven't claimed their invites yet.
- **Universal Force Deletion in `/remove_invite`:** Added force deletion logic for all user identifier types (direct username strings, mentions, and IDs), ensuring consistent behavior regardless of how users are identified.
- **Bidirectional Username Lookup in `/remove_invite`:** Added the ability to find Discord IDs from Jellyfin usernames in the local database when removing by direct username. This ensures the local database record is properly marked as disabled, allowing new invites to be created.
- **Standardized Response Format in `/remove_invite`:** Implemented a consistent, clear message format for the command's responses, with standardized sections showing action status (success/failure) and detailed information.
