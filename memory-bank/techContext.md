# Technical Context

*This document details the technologies, development environment, constraints, dependencies, and tools used in the project.*

## Technologies Used

- **Language:** Python 3.12+ (as specified in `README.md` and `Dockerfile`)
- **Discord API Wrapper:** discord.py v2.3.2 (from `README.md`)
- **HTTP Requests:** requests library (for JFA-GO API communication, from `README.md`)
- **Configuration:** PyYAML (for `config.yaml`), python-dotenv (for `.env` files) (from `README.md`)
- **Database:** SQLite 3 (for storing invite info and admin actions, from `README.md`)
    - **Module:** `modules/database.py` (Class `Database`)
    - **Connection:** Uses `sqlite3` standard library. Connection and cursor management handled via a context manager (`_get_connection`). `db_file_name` is configurable in `config.yaml`.
    - **Row Factory:** `sqlite3.Row` is used for dictionary-like access to columns.
    - **Initialization (`_init_db`)**: Creates tables based on `CREATE_TABLE_SQL` if they don't exist upon instantiation.
    - **Schema (`CREATE_TABLE_SQL`):
        - `user_invites`:
            - `user_id TEXT PRIMARY KEY`
            - `username TEXT NOT NULL`
            - `invite_code TEXT NOT NULL`
            - `created_at INTEGER NOT NULL` (Timestamp)
            - `updated_at INTEGER NOT NULL` (Timestamp)
            - `claimed BOOLEAN NOT NULL DEFAULT FALSE`
            - `jfa_user_id TEXT NULL` (Corresponding JFA-GO User ID)
            - `plan_type TEXT NULL` (e.g., 'Trial', 'Premium Profile')
            - `account_expires_at INTEGER NULL` (Timestamp when JFA-GO account expires)
            - `last_notified_at INTEGER NULL` (Timestamp when expiry notification was last sent)
            - `status TEXT NULL` (Current status of the user/invite)
        - `admin_actions`:
            - `id INTEGER PRIMARY KEY AUTOINCREMENT`
            - `admin_id TEXT NOT NULL`
            - `admin_username TEXT NOT NULL`
            - `action_type TEXT NOT NULL`
            - `target_user_id TEXT NOT NULL`
            - `target_username TEXT NOT NULL`
            - `details TEXT`
            - `performed_at INTEGER NOT NULL` (Timestamp)
        - `jfa_user_cache`:
            - `jfa_id TEXT PRIMARY KEY` (JFA-GO User ID)
            - `jellyfin_username TEXT NOT NULL UNIQUE` (JFA-GO `name`)
            - `discord_id TEXT UNIQUE` (JFA-GO `discord_id`, nullable)
            - `email TEXT` (nullable)
            - `expiry INTEGER` (Unix timestamp, nullable)
            - `disabled BOOLEAN`
            - `jfa_accounts_admin BOOLEAN` (JFA-GO specific admin role)
            - `jfa_admin BOOLEAN` (Jellyfin admin role)
            - `last_synced INTEGER NOT NULL` (Unix timestamp of last sync for this record)
    - **Key Methods:**
        - `get_invite_info(user_id)`: Returns `InviteInfo` object or `None`.
        - `record_invite(...)`: Inserts or updates (upserts) an invite. Resets `claimed` and `last_notified_at` on update/creation.
        - `mark_invite_claimed(user_id)`.
        - `delete_invite(user_id)`.
        - `record_admin_action(action: AdminAction)`.
        - `update_last_notified(user_id, timestamp)`: For expiry notification tracking.
        - `get_expiring_users(days_notice)`: Retrieves users due for expiry notification.
        - `clear_account_expiry(user_id)`: Resets expiry and notification timestamps for a user.
        - `upsert_jfa_users(users_data: list[dict])`: Bulk inserts/updates JFA-GO user data into `jfa_user_cache`.
        - `get_jfa_user_from_cache_by_discord_id(discord_id: str)`.
        - `get_jfa_user_from_cache_by_jellyfin_username(jellyfin_username: str)`.
        - `get_jfa_user_from_cache_by_jfa_id(jfa_id: str)`.
        - `update_user_invite_status(user_id: str, status: str)`: Updates the `status` field for a user in the `user_invites` table (e.g., to 'trial', 'paid', or 'disabled').
    - **Transactions:** Uses `with conn:` blocks for atomic operations.
- **JFA-GO:** Interacts with a running JFA-GO instance API (core dependency).

## Development Setup

- **Prerequisites:**
    - Python 3.12 or higher
    - `pip` (Python package installer)
    - A running instance of JFA-GO accessible by the bot.
    - A Discord Bot Token and Application.
- **Steps (as per `README.md`):
    1.  Clone the repository.
    2.  Create a Python virtual environment (e.g., `python -m venv venv`) and activate it.
    3.  Install dependencies: `pip install -r requirements.txt`.
    4.  Configure the bot:
        - Copy `config.yaml.example` to `config.yaml` and edit.
        - Copy `message_templates.json.example` to `message_templates.json` (optional, for message customization).
        - Create and populate `.env` for secrets (Discord token, JFA-GO credentials).
- **Running:** `python main.py`

## Technical Constraints

- Requires Python 3.12+.
- Depends on an external JFA-GO instance being operational and accessible.
- Current known limitations (see `projectbrief.md` - Scope and `progress.md` - Known Issues).

## Dependencies

- **Primary Python Libraries (from `README.md` Tech Stack and implied by `requirements.txt`):
    - `discord.py` (v2.3.2, including `discord.Client`, `app_commands.CommandTree`, `discord.ext.tasks` for background loops)
    - `requests` (heavily used in `modules/jfa_client.py` for API calls, configured with retries and timeouts)
    - `PyYAML` (used in `modules/config.py`)
    - `python-dotenv` (used in `modules/config.py`)
    - `APScheduler` (likely for background tasks like notifications in `modules/bot.py` - *verification from `bot.py` needed*)
- **External Services:**
    - JFA-GO API
    - Discord API
- Dependencies are managed via `requirements.txt`.

## Tool Usage Patterns

- **Version Control:** Git (implied by `git clone` in setup).
- **Package Management:** `pip` with `requirements.txt`.
- **Containerization:** Docker, with a provided `Dockerfile`. Pre-built images available on Docker Hub (`sidikulous/jellycord`).
- **Configuration Management:**
    - **Primary File:** `config.yaml`
    - **Secrets & Overrides:** `.env` file (loaded using `python-dotenv`). Environment variables take precedence.
    - **Loading Mechanism (`modules/config.py`):**
        - `load_app_config()`: Orchestrates loading.
        - `_load_yaml_config()`: Loads `config.yaml`.
        - `_get_typed_env_var()`: Retrieves and casts environment variables.
        - `_merge_configs()`: Merges YAML config with `DEFAULT_CONFIG_STRUCTURE`.
        - `_apply_env_vars_to_merged_config()`: Applies environment variable overrides, prioritizing them for secrets.
        - Stores the final configuration in a global `APP_CONFIG` dictionary.
    - **Access Mechanism:** `get_config_value(path: str, default: Any = None)` function allows accessing configuration values using dot notation (e.g., "discord.token").
    - **Validation:** `validate_config()` function checks the loaded configuration against an `EXPECTED_CONFIG` structure, which defines expected types, requirement status, and default values for each configuration key. It logs errors and can exit if critical configurations are missing or invalid.
    - **Defaults:** A `DEFAULT_CONFIG_STRUCTURE` dictionary in `modules/config.py` provides a base structure and default values. This structure includes keys like:
        - `discord.token` (str, True, None) - Bot token, critical.
        - `discord.guild_id` (int, True, None) - Primary server ID.
        - `discord.command_channel_ids` (list[int], False, []) - Channels where commands can be used.
        - `discord.admin_log_channel_id` (int, False, None) - Channel for admin action logs.
        - `discord.trial_user_role_name` (str, False, "Trial") - Name of the role for trial users. Used by `/create-trial-invite` for assignment, `/create-user-invite` to ensure its presence even with paid plans, and `/remove_invite` to preserve it during role cleanup.
        - `discord.notification_channel_id` (int, False, None) - Channel for expiry notifications summary.
        - `jfa_go.username`, `jfa_go.password`, `jfa_go.base_url` - Critical JFA-GO API credentials.
        - `bot_settings.debug_mode` (bool, False, False) - Enables debug logging.
        - `bot_settings.db_file_name` (str, False, "jellyfin_invites.db") - Database file name.
        - `bot_settings.log_file_name` (str, False, "jellyfin_invite_bot.log") - Log file name.
        - `commands.create_trial_invite.trial_duration_days` (int, False, 7) - Default trial duration.
        - `commands.create_trial_invite.trial_invite_label_format` (str, False, "Trial Invite - {user_name} ({user_id})") - Format for JFA-GO invite label.
        - `commands.create_user_invite.plan_to_role_map` (dict, False, {}) - Maps JFA-GO Profile Name to Discord Role Name/ID for paid plans.
        - `commands.create_user_invite.link_validity_days` (int, False, 7) - How long generated user invite links are valid.
        - `commands.create_user_invite.trial_role_name` (str, False, "Trial") - **DEPRECATED.** Use `discord.trial_user_role_name` instead. This key might be removed in future versions.
        - `notification_settings...` - Various settings for user expiry notifications.
        - `sync_settings...` - Settings for JFA-GO user cache synchronization.
    - **Environment Variable Casting:** Supports casting environment variables to `bool`, `int`, `list` (comma-separated), and basic `dict` (JSON string).
- **IDE/Editor:** Not specified, user's choice.
- **Shell:** Bash/PowerShell examples in `README.md` for setup and Docker commands.

## JFA-GO API Client (`modules/jfa_client.py`)
    - **Authentication:** Handles token-based authentication (`login()`, `ensure_auth()`). Obtains a token via `/token/login` endpoint using basic auth, stores it with an expiry time, and refreshes when necessary.
    - **Session Management:** Uses `requests.Session()` with a User-Agent, Accept header, and a retry strategy (3 retries, backoff factor 1, for status codes 429, 500, 502, 503, 504).
    - **API Call Logging:** `_log_api_call()` logs request and response details (method, URL, payload, status, headers, body) in debug mode, with password redaction for login calls.
    - **Caching:** Implements in-memory caching for `get_profiles()` and `get_invites()` results with a configurable duration (`_cache_duration_seconds`, default 5 minutes) to reduce API load.
    - **Core Methods:**
        - `get_profiles()`: Fetches available user profiles (e.g., for plan selection). Endpoint: `/profiles`.
        - `extend_user_expiry()`: Extends a user's account validity. Endpoint: `/users/{jfa_username}/extend`.
        - `create_invite()`: Creates a new invite link. Endpoint: `/invites` (POST).
        - `get_invite_code()`: Retrieves an invite code by its label (iterates through `/invites` GET).
        - `get_invites()`: Fetches all existing invites. Endpoint: `/invites` (GET).
        - `delete_jfa_invite()`: Deletes an invite from JFA-GO. Endpoint: `/invites/{invite_code}` (DELETE).
        - `get_jfa_user_details_by_username()`: Fetches details for a specific JFA-GO user. Endpoint: `/users/{username}`.
        - `get_all_jfa_users()`: Fetches all users from JFA-GO (`GET /users`). Returns a list of user objects and a status message.
        - `delete_jfa_user_by_username(jellyfin_username: str)`: Deletes a user from JFA-GO.
            - First calls `get_all_jfa_users()` to find the user's JFA-GO `id` by matching `jellyfin_username` against the `name` field in the user list.
            - Then sends a `DELETE` request to the `/users` endpoint with the payload `{"users": ["<user_id>"]}`.
            - Returns a success boolean and status message.
    - **Error Handling:** Methods typically return a `Tuple[bool, str]` or `Tuple[Optional[Any], str]` indicating success/failure and a message or data.

## Core Bot Logic (`modules/bot.py` - `JfaGoBot` class)
    - **Initialization:** Inherits `discord.Client`. Initializes `JfaGoClient`, `Database`, and `app_commands.CommandTree`. Sets up intents (members, message_content).
    - **Event Handling:**
        - `on_ready()`: Logs bot readiness.
        - `setup_hook()`: Syncs slash commands with the configured Discord guild. Starts background tasks.
        - `on_error()`: Generic error handler for bot events.
    - **Command Management:** Uses `app_commands.CommandTree` for slash command registration and synchronization.
    - **Admin Logging (`log_admin_action`)**: Logs `AdminAction` dataclass instances to the SQLite database and sends a formatted embed to the configured `discord.admin_log_channel_id`.
    - **Authorization (`is_support_category`)**: Determines if a command is used in an allowed channel or category based on `discord.command_channel_ids` from `config.yaml`. Handles text channels, threads, and parent categories.
    - **Background Tasks (`discord.ext.tasks`):
        - `check_expiry_notifications`: Runs periodically (e.g., every 6 hours).
            - Fetches JFA-GO users expiring within `notification_settings.expiry_check_fetch_days`.
            - Filters users based on `notification_settings.notification_days_before_expiry`.
            - Checks `database` to avoid re-notifying within `notification_settings.expiry_notification_interval_days`.
            - Sends DMs (`_send_expiry_dm`) to users.
            - Sends a summary report to `discord.notification_channel_id`.
        - `sync_jfa_users_cache_task`: Runs periodically (configured by `sync_settings.jfa_user_sync_interval_hours`, default 12 hours).
            - Calls `jfa_client.get_all_jfa_users()`.
            - Updates the local `jfa_user_cache` table in the database via `db.upsert_jfa_users()`.

## Logging (`modules/logging_setup.py`)
    - **Setup Function:** `setup_logging()` is called early (in `main.py`) to configure logging for the entire application.
    - **Log Level:** Determined by `bot_settings.debug_mode` from `config.yaml` (DEBUG if true, INFO if false). Configured via `LOG_LEVEL` global in the module.
    - **Log Format:** `%(asctime)s - %(name)s - %(levelname)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s`.
    - **Handlers:**
        - **Console:** `logging.StreamHandler` outputting to `sys.stdout`.
        - **File:** `logging.handlers.RotatingFileHandler`:
            - File path from `bot_settings.log_file_name` (config).
            - Rotates at 5MB, keeps 5 backup files.
            - Uses UTF-8 encoding.
            - Ensures log directory exists before creating the handler.
    - **Configuration:** The root logger is configured, and existing handlers are cleared before adding new ones.

## Messaging System (`modules/messaging.py`)

- **Message Templates:**
  - Loaded from `message_templates.json` for internationalization/customization
  - Accessed via dot-notation keys: `get_message("category.subcategory.key", **kwargs)`
  - Templates support formatting placeholders with variable substitution

- **Embed Creation:**
  - `create_embed()`: Creates Discord embeds using template keys for titles/descriptions.
    - Supports `title_key`, `description_key`, `title`, `description` (direct text).
    - Handles `color_type` ("success", "error", "warning", "info", "default").
    - Accepts `description_kwargs` for formatting.
    - Includes `timestamp` (datetime object).
    - Supports `footer_key` for templated footers.
    - Allows adding multiple `fields` via a list of dictionaries. Each dictionary can define `name_key` (or `name`), `value_key` (or `value`), `value_kwargs`, and `inline` status.
  - `create_direct_embed()`: Creates embeds with direct string values, bypassing templates.
  - Standard color types: "success" (green), "error" (red), "warning" (yellow), "info" (blue), "default" (Discord dark theme)
  - Support for timestamps, fields, and custom footers.

## Database Structure

- **SQLite Database:**
  - File location configured via `bot_settings.db_file_name`
  - Managed by the `Database` class in `modules/database.py`
    - Provides robust error handling and connection management
    - Methods for querying and updating invite information

- **Tables and Schema:**
    - **Schema (`CREATE_TABLE_SQL`):
        - `user_invites`:
            - `user_id TEXT PRIMARY KEY`
            - `username TEXT NOT NULL`
            - `invite_code TEXT NOT NULL`
            - `created_at INTEGER NOT NULL` (Timestamp)
            - `updated_at INTEGER NOT NULL` (Timestamp)
            - `claimed BOOLEAN NOT NULL DEFAULT FALSE`
            - `jfa_user_id TEXT NULL` (Corresponding JFA-GO User ID)
            - `plan_type TEXT NULL` (e.g., 'Trial', 'Premium Profile')
            - `account_expires_at INTEGER NULL` (Timestamp when JFA-GO account expires)
            - `last_notified_at INTEGER NULL` (Timestamp when expiry notification was last sent)
            - `status TEXT NULL` (Current status of the user/invite - 'trial', 'paid', 'disabled')
        - `admin_actions`:
            - `id INTEGER PRIMARY KEY AUTOINCREMENT`
            - `admin_id TEXT NOT NULL`
            - `admin_username TEXT NOT NULL`
            - `action_type TEXT NOT NULL`
            - `target_user_id TEXT NOT NULL`
            - `target_username TEXT NOT NULL`
            - `details TEXT`
            - `performed_at INTEGER NOT NULL` (Timestamp)
        - `jfa_user_cache`:
            - `jfa_id TEXT PRIMARY KEY` (JFA-GO User ID)
            - `jellyfin_username TEXT NOT NULL UNIQUE` (JFA-GO `name`)
            - `discord_id TEXT UNIQUE` (JFA-GO `discord_id`, nullable)
            - `email TEXT` (nullable)
            - `expiry INTEGER` (Unix timestamp, nullable)
            - `disabled BOOLEAN`
            - `jfa_accounts_admin BOOLEAN` (JFA-GO specific admin role)
            - `jfa_admin BOOLEAN` (Jellyfin admin role)
            - `last_synced INTEGER NOT NULL` (Unix timestamp of last sync for this record)
    - **Key Methods:**
        - `get_invite_info(user_id)`: Returns `InviteInfo` object or `None`.
        - `get_invite_by_username(username)`: Returns user invite record by Discord username or `None`.
        - `find_invites_by_username_pattern(pattern)`: Returns list of user invite records matching a pattern.
        - `record_invite(...)`: Inserts or updates (upserts) an invite. Resets `claimed` and `last_notified_at` on update/creation.
        - `mark_invite_claimed(user_id)`: Marks an invite as claimed.
        - `update_user_invite_status(user_id, status)`: Updates status to 'trial', 'paid', or 'disabled'.
        - `get_invite_status(user_id)`: Gets the current status of an invite.
        - `record_admin_action(action)`: Records an administrative action.
        - `get_jfa_user_from_cache_by_discord_id(discord_id)`: Gets JFA-GO user by Discord ID.
        - `get_jfa_user_from_cache_by_jellyfin_username(jellyfin_username)`: Gets JFA-GO user by Jellyfin username.
        - `upsert_jfa_users(users_data)`: Bulk updates the JFA user cache.

## User Identification Logic

- **Multi-method User Identification:**
  - **Direct Discord Identification:**
    - By ID: Pure numeric strings are treated as Discord IDs
    - By Mention: Strings like `<@123456789>` are parsed to extract Discord IDs
    - Lookups performed via Discord API with `bot.fetch_user()`

  - **Jellyfin Username Identification:**
    - Direct lookup in `jfa_user_cache` by `jellyfin_username`
    - If found, attempts to resolve associated `

## Configuration Structure

- **Config File (`config.yaml`):**
  - Contains various configuration options and settings.
  - **Example Structure:**
    - `discord.trial_user_role_name`: (str, False, "Trial")
    - `discord.notification_channel_id`: (str, False, None)
    - `commands.create_user_invite.plan_to_role_map`: (dict, False, {})
    - `commands.create_user_invite.trial_role_name`: (str, False, "Trial")
