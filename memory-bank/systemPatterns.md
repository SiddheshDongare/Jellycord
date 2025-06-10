# System Patterns

*This document outlines the system's architecture, key technical decisions, design patterns, and component interactions.*

## System Architecture

- **Entry Point:** `main.py` initializes logging, configuration, the main bot instance (`JfaGoBot` from `modules/bot.py`), registers event and command handlers, and starts the bot.
- **Modularity:** The application is structured into modules (located in the `modules/` directory) for distinct functionalities:
    - `bot.py`: Core bot class, event handling, command tree, background tasks (e.g., expiry notifications).
    - `config.py`: Loads and validates configuration from `config.yaml` and environment variables.
    - `logging_setup.py`: Configures application-wide logging.
    - `messaging.py`: Manages user-facing messages from `message_templates.json`.
    - `models.py`: Defines data classes (e.g., `InviteInfo`, `AdminAction`).
    - `database.py`: Handles SQLite database interactions (storing invites, admin logs).
    - `jfa_client.py`: A dedicated client for all communication with the JFA-GO API.
    - `modules/commands/`: Sub-package for slash command definitions, further broken down by command type (admin, invite, user_invite) and includes an `auth.py` for command authorization.
- **Configuration-Driven:** Bot behavior, API endpoints, Discord server details, and messages are heavily reliant on `config.yaml` and `message_templates.json`.
- **Event-Driven:** As a Discord bot, its core operation is event-driven (reacting to messages, commands, scheduled tasks).

## Key Technical Decisions

- **Python with discord.py:** Leveraging a mature library for Discord API interaction.
- **Centralized Configuration:** Using YAML (`config.yaml`) for easy-to-read and comprehensive settings management, with `.env` for secrets.
- **SQLite Database:** Chosen for local data persistence (invites, logs) without requiring a separate database server.
- **Modular Design:** Separating concerns into different Python modules for maintainability and clarity (e.g., JFA-GO client, database logic, command handlers).
- **API Client for JFA-GO:** Encapsulating all JFA-GO interactions within `jfa_client.py` to decouple it from other bot logic.
- **Customizable Messaging:** Storing all user-facing strings in `message_templates.json` allows for easy modification and theming.
- **Docker Support:** Providing a `Dockerfile` and pre-built images facilitates deployment.

## Design Patterns in Use

- **Configuration Management (`modules/config.py`):**
    - A dedicated module handles loading, merging (YAML, .env, defaults), and validation of application configuration.
    - Provides a global accessor (`get_config_value`) for type-safe retrieval of settings.
    - Includes a schema-like definition (`EXPECTED_CONFIG`) for validation rules (type, required, default).
- **Template Method (Conceptual for Messaging - `modules/messaging.py`):**
    - `create_embed()` acts as a template for creating standardized embeds.
    - `get_message()` provides a consistent way to retrieve and format localized/configurable text strings from `message_templates.json`.
    - This promotes consistency in bot responses and allows easy modification of text and embed structure without code changes.
- **API Client (`jfa_client.py`):**
    - Encapsulates all JFA-GO API communication.
    - Manages authentication (token fetching and renewal) and session (with retries via `requests.adapters.HTTPAdapter`).
    - Provides specific methods for JFA-GO actions (e.g., `create_invite`, `get_profiles`, `extend_user_expiry`, `delete_jfa_invite`, `get_jfa_user_details_by_username`).
    - Implements response caching (`_invite_cache`, `_profile_cache`) with expiry to reduce API calls.
    - Includes detailed API call logging (`_log_api_call`) for debugging, redacting sensitive information.
    - Consistent error handling by returning tuples indicating success status and a message or data.
- **Event Handling:** Core to `discord.py` and how the bot responds to Discord events (e.g., messages, commands, bot ready). `JfaGoBot` class in `modules/bot.py` handles `on_ready` (via `register_event_handlers`) and `setup_hook` (for command syncing and starting tasks), and has a global `on_error` handler.
- **Command Pattern:** Slash commands in `modules/commands/` represent distinct actions, with specific handlers for each.
    - Each command module (e.g., `invite_commands.py`, `user_invite_commands.py`, `admin_commands.py`) typically has:
        - A `setup_commands(bot)` function that registers commands to the `bot.tree` using `@bot.tree.command(...)`.
        - Command handler functions (e.g., `create_trial_invite_command`) decorated with `@is_in_support_and_authorized()` and potentially a command-specific error handler using `@command_name.error`.
        - Command handlers interact with `interaction.client` (the `JfaGoBot` instance) to access `jfa_client`, `db`, `log_admin_action`, and configuration values.
        - Asynchronous operations (like JFA-GO calls) are often run in a separate thread using `asyncio.to_thread` to avoid blocking the bot.
        - User feedback is provided via initial ephemeral messages, then edited, or new messages/embeds using `modules/messaging.py` helpers.
        - **Role management within `/create-user-invite`**:
            - Removes existing mapped plan roles (except the trial role).
            - Assigns the new plan's mapped role.
            - Ensures the configured trial role is present on the user.
        - **Role management within `/remove_invite`**:
            - If a Discord member is identified:
                - Removes mapped paid plan roles.
                - Preserves the configured trial role.
            - Actions are logged and included in the admin confirmation.
- **Decorator Pattern:** Used for command authorization. The `is_in_support_and_authorized()` decorator in `modules/commands/auth.py` is an `app_commands.check` that wraps command handler predicate functions. It verifies:
    - If the command is used in a channel/category specified in `discord.command_channel_ids` (via `JfaGoBot.is_support_category`).
    - If the interacting user possesses at least one of the roles defined in `discord.command_authorized_roles` (checks by name or ID).
    - Sends ephemeral error messages on failure.
- **Singleton (Conceptual):** The `JfaGoBot` instance in `modules/bot.py` acts as a central orchestrator for bot operations, holding instances of `JfaGoClient`, `Database`, and the `app_commands.CommandTree`.
- **Repository/Data Access Object (Conceptual) (`database.py`):**
    - The `Database` class in `modules/database.py` encapsulates all SQLite interactions.
    - It defines the schema (`user_invites`, `admin_actions`, `jfa_user_cache` tables) and provides methods for CRUD operations and specific queries.
    - The `user_invites` table tracks Discord user ID, their JFA-GO invite code, creation/update timestamps, claimed status, JFA-GO user ID, plan type, account expiry, last notification time, and a `status` field (e.g., 'trial', 'paid', 'disabled').
    - The `jfa_user_cache` table stores a local copy of JFA-GO user data (from `GET /users`), periodically updated by a background task in `bot.py`, to facilitate quick lookups by Jellyfin username or Discord ID.
    - Uses a context manager (`_get_connection`) for safe database connection handling.
    - Employs `sqlite3.Row` for easier data access from query results.
    - Utilizes transactions (`with conn:`) for atomic write operations.
- **Database Operations (`database.py`):**
    - Schema creation and table structure for `user_invites` and `admin_actions`.
    - Reliable execution of SQL queries, particularly the upsert logic in `record_invite`.
    - Transaction management for data integrity.
    - Correct handling of timestamps for created_at, updated_at, account_expires_at, and last_notified_at fields.

## `/remove_invite` Command Flow (Admin Deletion Process)

- The `/remove_invite [user_identifier]` command implements a multi-step process for comprehensive user and invite removal:
    1.  **User Identification (`admin_commands.py`):**
        - The input `user_identifier` is parsed to find a user through multiple methods:
            - **Discord User ID**: Direct numeric ID identification
            - **Discord User Mention**: Parsing mention format like `<@123456789>`
            - **Jellyfin Username**: Looking up in the `jfa_user_cache` table
            - **Discord Username**: Looking up in the `user_invites` table
        - **Enhanced Fallback Logic**:
            - If a Discord user is found but no Jellyfin username exists in JFA cache:
                1. Try the Discord username as a potential Jellyfin username
                2. Try the Discord display name as a potential Jellyfin username
            - If a direct username is used but not found in JFA cache:
                - Force attempt deletion with the username directly
            - **Bidirectional Resolution**:
                - When only Jellyfin username is known, attempt to find Discord ID in local database through:
                    - Exact username matching in `user_invites` table
                    - Pattern matching with SQL LIKE wildcards
                - This ensures both the JFA-GO user deletion and local database status update succeed

    2.  **JFA-GO User Deletion:**
        - If a Jellyfin username is determined (either directly or through fallbacks), `jfa_client.delete_jfa_user_by_username()` is called
        - It first calls `jfa_client.get_all_jfa_users()` to fetch all users from JFA-GO
        - It iterates through the fetched users to find the one whose `name` matches the target Jellyfin username, to obtain their JFA-GO internal `id`
        - If the `id` is found, it sends a `DELETE` request to the JFA-GO `/users` endpoint with a JSON payload: `{"users": ["<user_id>"]}`
        - Force deletion attempts are made even when the user isn't found in the JFA cache

    3.  **JFA-GO Invite Code Deletion:**
        - If a Discord user ID was identified and a corresponding record exists in the local `user_invites` table (retrieved via `db.get_invite_info`), the associated JFA-GO `invite_code` is extracted
        - `jfa_client.delete_jfa_invite(original_invite_code)` is called to attempt deletion of this specific invite code from JFA-GO

    4.  **Local Database Status Update:**
        - If a Discord user ID was identified, `db.update_user_invite_status(discord_user_id, "disabled")` is called to mark the user's invite record as disabled in the local `user_invites` table
        - The record itself is *not* deleted from `user_invites`, preserving historical data
        - If only a Jellyfin username was identified (no Discord ID), the system attempts to find an associated Discord ID through:
            - Direct lookup in `user_invites` table using the Jellyfin username
            - Pattern matching to find similar usernames

    5.  **Standardized Response Format:**
        - A consistent, clearly structured embed is returned with:
            - A standardized title: "User Removal Summary"
            - Clear target user identification
            - Action status sections with visual indicators:
                - **JFA-GO User Removal:** ✅ Success / ⚠️ Attempted but failed / ❌ Not Attempted
                - **Local Database Update:** ✅ Success / ⚠️ Attempted but failed / ❌ Not Attempted
            - Detailed information about each step that was attempted
        - This provides both quick visual status and detailed logs in one consistent format

This comprehensive approach ensures that:
- Users can be removed using any identifier (Discord ID, mention, username, or Jellyfin username)
- Both JFA-GO and local database records are properly handled
- The system attempts to correlate and find users even when identifiers don't perfectly match
- After removal, new invites can be created for the same user

## Data Structures (`modules/models.py`)
    - The application uses dataclasses for structured data representation:
        - **`InviteInfo`**: Represents details of a user invite, including invite code, label, creation/expiry timestamps, claimed status, associated JFA-GO user ID, plan type, account expiry timestamp, and last notification timestamp. Used by `database.py` and command logic.
        - **`AdminAction`**: Captures information about an administrative action, including the performing admin (ID, username), the type of action, the target user (ID, username), optional details, and the timestamp of the action. Used by `bot.py` for logging and `database.py` for persistence.

## Component Relationships

- `main.py` initializes and runs `JfaGoBot` (from `bot.py`).
- `JfaGoBot` uses:
    - `jfa_client.py` to talk to JFA-GO.
    - `database.py` to store and retrieve data.
    - `config.py` (indirectly via `get_config_value`) for settings.
    - `messaging.py` for constructing responses.
    - Command modules from `modules/commands/` which are registered with it.
- Command modules use `auth.py` for authorization checks and interact with `JfaGoBot` methods or its attributes (like the JFA client or database).
- `logging_setup.py` is called early in `main.py` to set up logging for all modules.
- `models.py` provides data structures (dataclasses `InviteInfo`, `AdminAction`) used by various components like `database.py` (for storing/retrieving), `jfa_client.py` (potentially for return types, though not explicitly shown in outline), `bot.py` (for `AdminAction` logging), and command logic.

## Critical Implementation Paths

- **JFA-GO API Interaction (`jfa_client.py`):**
    - Authentication lifecycle (login, token storage with expiry, re-login).
    - Correct usage of `requests.Session` with headers, timeouts, and retry strategies.
    - Robust parsing of JFA-GO API responses and handling of potential errors (HTTP status codes, JSON parsing issues).
    - Cache logic for profiles and invites to optimize performance and reduce API load.
    - Specific endpoint interactions for all supported JFA-GO features.
- **User Expiry Notification Task (`bot.py`):**
    - The `check_expiry_notifications` background task (`discord.ext.tasks.loop`) logic, including fetching users from JFA-GO, checking against notification day rules, preventing re-notification spam via database checks, sending DMs, and reporting summaries.
- **JFA-GO User Cache Sync Task (`bot.py`):**
    - A new background task (`sync_jfa_users_cache_task` using `discord.ext.tasks.loop`) periodically calls `jfa_client.get_all_jfa_users()` and updates the local `jfa_user_cache` table in the database via `db.upsert_jfa_users()`. This ensures the bot has a relatively up-to-date list of JFA-GO users for lookups.
- **Command Handling and Authorization (`bot.py`, `modules/commands/`):
    - Ensuring commands are correctly parsed, authorized, and executed.
    - The `is_in_support_and_authorized` check in `modules/commands/auth.py` correctly validating channel and user roles against configuration before allowing command execution.
