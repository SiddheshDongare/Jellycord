<p align="center">
  <img src="images/logo.jpg" alt="Jellycord Logo" width="200"/>
</p>

# Jellycord: A JFA-GO Companion Bot

[![Discord.py](https://img.shields.io/badge/discord.py-v2.3.2-blue.svg)](https://github.com/Rapptz/discord.py)
[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Docker Hub](https://img.shields.io/badge/docker-sidikulous%2Fjellycord-blue.svg?logo=docker)](https://hub.docker.com/r/sidikulous/jellycord)

## Description

Jellycord is a highly configurable Discord bot designed as a companion app to integrate with [JFA-GO](https://github.com/hrfee/jfa-go) for managing user invites to a Jellyfin media server. It empowers authorized Discord users to create trial and paid invite links, manage existing invites, and extend user plans directly within designated support channels or threads. All bot behaviors, settings, messages, and embed appearances are customizable through YAML and JSON configuration files.

**Important Note / Current Limitations:**
*   Jellycord currently does **not** support migrating existing users from your JFA-GO database to the bot's database.
*   The `/remove_invite` command **only** removes the invite record from Jellycord's database and Discord roles. It does **not** remove the user from JFA-GO itself. You will need to manually remove the user from JFA-GO.
*   These limitations are planned to be addressed in future releases.
*   Jellycord is best suited for new JFA-GO setups or if these limitations are not major hurdles for your existing workflow.

## Features

*   **Configurable Invite Types:**
    *   **Trial Invites:** Create temporary, single-use trial invites. Durations for the invite link and the resulting user account are configurable.
    *   **Paid Invites:** Generate invites linked to specific JFA-GO user profiles, with customizable account durations.
*   **Invite Management (See Limitations Above):**
    *   Remove existing invite records from the bot's database.
    *   Extend the expiry of existing JFA-GO user accounts.
*   **User Notifications:** Automatically notify users via DM before their JFA-GO account expires, with configurable notification timings.
*   **Role-Based Access Control:** Restrict command usage to users with specific Discord roles within designated support categories/channels.
*   **Comprehensive Admin Logging:** Logs administrative actions (invite creation/removal, plan extensions) to a specified Discord channel and the local database. All log messages are configurable.
*   **Deep JFA-GO Integration:** Communicates directly with the JFA-GO API for profile fetching, user lookup, invite creation/deletion, and plan extensions.
*   **Database Persistence:** Stores invite information and admin actions in an SQLite database (filename configurable).
*   **Fully Configurable Messaging:** All user-facing messages, embed titles, field names, colors, and footers are configurable via a `message_templates.json` file.
*   **Centralized YAML Configuration:** Primary bot settings (name, branding), JFA-GO connection details, Discord server specifics (IDs, roles, channels), command behaviors, and role mappings are managed through a central `config.yaml` file.
*   **Modular Design:** Code is structured into modules for better organization and maintainability.
*   **Docker Support:** Includes a Dockerfile for easy containerization and deployment.

## Tech Stack

*   **Language:** Python 3.12+
*   **Discord API Wrapper:** [discord.py](https://github.com/Rapptz/discord.py)
*   **HTTP Requests:** [requests](https://requests.readthedocs.io/en/latest/)
*   **Configuration:** [PyYAML](https://pyyaml.org/) for `config.yaml`, [python-dotenv](https://github.com/theskumar/python-dotenv) for `.env` (secrets/overrides).
*   **Database:** SQLite 3
*   **JFA-GO:** Interacts with a running JFA-GO instance API.

## Prerequisites

*   Python 3.12 or higher
*   `pip` (Python package installer)
*   A running instance of [JFA-GO](https://github.com/hrfee/jfa-go) accessible from where the bot runs.
*   A Discord Bot Token and Application.
*   [Docker](https://www.docker.com/) (Optional, for containerized deployment)

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url> # Replace with the actual URL
    cd Jellycord # Or your chosen directory name
    ```

2.  **Create a virtual environment (Recommended):**
    ```bash
    python -m venv venv
    # Activate the virtual environment
    # Windows (Command Prompt/PowerShell)
    venv\Scripts\activate
    # Linux/macOS
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure the Bot:**

    *   **Example Files:**
        Copy `config.yaml.example` to `config.yaml`.
        Copy `message_templates.json.example` to `message_templates.json` (if you plan to customize messages, otherwise the defaults embedded in the example are a good start).

    *   **Primary Configuration (`config.yaml`):**
        This file is the main hub for tailoring the bot. Edit `config.yaml` to set your JFA-GO connection details (excluding secrets), Discord server IDs, roles, channels, command parameters (like invite durations, label formats), notification settings, and paths to other configuration files. Detailed comments within `config.yaml.example` explain each option.

    *   **Secrets & Environment-Specific Overrides (`.env` file):**
        Create a `.env` file in the project root for secrets (e.g., Discord token, JFA-GO password) and environment-specific overrides.
        Environment variables take precedence over `config.yaml` values.
        The effective configuration is determined by loading `config.yaml` first, then applying any overriding environment variables.
        New-style environment variables match the YAML structure (e.g., `JFA_GO_USERNAME` for `jfa_go.username`, `BOT_SETTINGS_DEBUG_MODE` for `bot_settings.debug_mode`).

        Example `.env` file:
        ```dotenv
        # Discord Bot Token (Required - Secret)
        DISCORD_TOKEN="YOUR_DISCORD_BOT_TOKEN"

        # JFA-GO API Configuration (Secrets - Recommended here)
        JFA_GO_USERNAME="YOUR_JFA_GO_ADMIN_USERNAME"
        JFA_GO_PASSWORD="YOUR_JFA_GO_ADMIN_PASSWORD"

        # Optional: Override a setting from config.yaml using new style
        # BOT_SETTINGS_DEBUG_MODE="true"
        # (Corresponds to bot_settings.debug_mode in YAML)
        ```
        Place critical secrets like `DISCORD_TOKEN`, `JFA_GO_USERNAME`, and `JFA_GO_PASSWORD` in `.env`.

    *   **Message Customization (`message_templates.json`):**
        Edit `message_templates.json` to change any bot output: messages, embed titles, field names, colors, etc. The path is set in `config.yaml` (`message_settings.templates_file`).

## Running the Bot

### Directly with Python

Ensure your virtual environment is activated and `config.yaml` (and `.env`) are configured.
```bash
python main.py
```

### Using Docker

Deploying Jellycord with Docker is a convenient way to manage the application and its dependencies. You can use a pre-built image from Docker Hub or build the image locally.

**Recommended: Using the Pre-built Docker Image from Docker Hub**

A pre-built image is available on Docker Hub: [sidikulous/jellycord:latest](https://hub.docker.com/repository/docker/sidikulous/jellycord).

1.  **Prepare your host environment:**
    *   Create a dedicated directory for your Jellycord configuration and data. For example:
        ```bash
        mkdir ~/jellycord_bot_data
        cd ~/jellycord_bot_data
        ```
    *   Inside this directory, create subdirectories for the database and logs:
        ```bash
        mkdir bot_data_db
        mkdir bot_data_logs
        ```
        Ensure these directories have the correct permissions for the Docker user/group to write to them.
    *   Place your `config.yaml` and `.env` file (containing secrets like `DISCORD_TOKEN`, `JFA_GO_USERNAME`, `JFA_GO_PASSWORD`) in the `~/jellycord_bot_data` directory.
    *   If you are customizing messages, also place your `message_templates.json` in this directory.

2.  **Configure Paths in `config.yaml`:**
    Update your `config.yaml` to reflect the paths *inside the container* where the data and log directories will be mounted. The provided `docker run` command below mounts `bot_data_db` to `/app/data_db` and `bot_data_logs` to `/app/data_logs`.
    Therefore, your `config.yaml` should have entries like:
    ```yaml
    bot_settings:
      # ... other bot_settings ...
      db_file_name: "data_db/jellycord.db"  # Or your chosen db filename inside data_db
      log_file_name: "data_logs/jellycord.log" # Or your chosen log filename inside data_logs
      # ...
    ```

3.  **Run the Docker container:**
    From your dedicated directory (`~/jellycord_bot_data` in this example), run the following command:
    ```bash
    docker run -d \\
      --name jellycord \\
      --env-file .env \\
      -v "$(pwd)/config.yaml:/app/config.yaml:ro" \\
      -v "$(pwd)/message_templates.json:/app/message_templates.json:ro" \\
      -v "$(pwd)/bot_data_db:/app/data_db" \\
      -v "$(pwd)/bot_data_logs:/app/data_logs" \\
      sidikulous/jellycord:latest
    ```
    *   `--env-file .env`: Passes your secrets to the container.
    *   `-v "$(pwd)/config.yaml:/app/config.yaml:ro"`: Mounts your `config.yaml` as read-only.
    *   `-v "$(pwd)/message_templates.json:/app/message_templates.json:ro"`: Mounts your `message_templates.json` as read-only (optional, if used).
    *   `-v "$(pwd)/bot_data_db:/app/data_db"`: Mounts your local database directory to `/app/data_db` inside the container. The bot will write its database file here.
    *   `-v "$(pwd)/bot_data_logs:/app/data_logs"`: Mounts your local logs directory to `/app/data_logs` inside the container. The bot will write its log files here.
    *   `-d`: Runs the container in detached mode.
    *   `sidikulous/jellycord:latest`: Specifies the image to use.

**Alternative: Building the Docker image locally**

1.  **Build the Docker image:**
    From the root of the project directory (where the `Dockerfile` is located):
    ```bash
    docker build -t jellycord-bot .
    ```

2.  **Run the Docker container (using local build):**
    Follow the same steps 1 and 2 from the "Pre-built Image" section to prepare your host environment and configure `config.yaml`. Then, run the container using your locally built image name:
    ```bash
    # Ensure you are in your dedicated directory (e.g., ~/jellycord_bot_data)
    docker run -d \\
      --name jellycord \\
      --env-file .env \\
      -v "$(pwd)/config.yaml:/app/config.yaml:ro" \\
      -v "$(pwd)/message_templates.json:/app/message_templates.json:ro" \\
      -v "$(pwd)/bot_data_db:/app/data_db" \\
      -v "$(pwd)/bot_data_logs:/app/data_logs" \\
      jellycord-bot # Use your local image name
    ```

**Common Docker Operations:**

*   To view logs:
    ```bash
    docker logs jellycord -f
    ```
*   To stop the container:
    ```bash
    docker stop jellycord
    ```
*   To remove the container (after stopping):
    ```bash
    docker rm jellycord
    ```

**Updating the Bot (Docker):**

To update Jellycord to the latest version when using a pre-built Docker image:

1.  **Pull the latest image from Docker Hub:**
    ```bash
    docker pull sidikulous/jellycord:latest
    ```
2.  **Stop the currently running container:**
    ```bash
    docker stop jellycord
    ```
3.  **Remove the old container:**
    This does *not* delete your data volumes.
    ```bash
    docker rm jellycord
    ```
4.  **Run the new container using the same `docker run` command as before.** Ensure your volume mounts (`-v`) for `config.yaml`, `message_templates.json` (if used), `bot_data_db`, and `bot_data_logs` are identical to your initial setup. This will reconnect the new container to your existing data and configuration.

    Navigate to your dedicated bot directory (e.g., `~/jellycord_bot_data`) and execute:
    ```bash
    docker run -d \\
      --name jellycord \\
      --env-file .env \\
      -v "$(pwd)/config.yaml:/app/config.yaml:ro" \\
      -v "$(pwd)/message_templates.json:/app/message_templates.json:ro" \\
      -v "$(pwd)/bot_data_db:/app/data_db" \\
      -v "$(pwd)/bot_data_logs:/app/data_logs" \\
      sidikulous/jellycord:latest
    ```
    Your existing database and logs will be used by the updated bot.

    *   Ensure the `db_file_name` and `log_file_name` paths in `config.yaml` correctly point to locations within the mounted volumes (e.g., `data_db/your_database.db`, `data_logs/your_log.log`).

## Configuration Explained

Configuration is primarily managed via `config.yaml`. Environment variables can override these settings. Refer to `config.yaml.example` for a comprehensive list of options.

Key sections in `config.yaml`:

*   **`bot_settings`**: General bot settings (name, log file, database file, debug mode).
*   **`discord`**: Discord-specific settings (token, guild ID, admin log channel, authorized roles/channels for commands, role for trial users, notification channel and timings).
*   **`jfa_go`**: JFA-GO connection details (base URL, username, password - ideally set in `.env`, default trial profile).
*   **`invite_settings`**: Global settings for invite generation (base URL for invite links, default link validity, trial account duration, label formats for trial/paid invites, JFA-GO profile to Discord role mapping for paid invites).
*   **`message_settings`**: Path to `message_templates.json`, default embed colors, default embed footer text (can use `{bot_name}` placeholder), and the bot's display name used in messages.
*   **`notification_settings`**: Configuration for user expiry notifications (how far ahead to check for expiries, how often to send the same notification, and on which specific days before expiry to notify).
*   **`commands`**: Fine-grained settings for specific commands:
    *   `create_trial_invite`: Override JFA-GO user expiry, label format, and assigned Discord role for trial invites.
    *   `create_user_invite`: Override invite link validity, define the mapping from JFA-GO plans to Discord roles, and specify the trial role to remove when a user plan is given.
    *   `/remove_invite [user]`: Removes an invite record for a specified Discord user from Jellycord's database and attempts to revert their Discord roles. **Does not remove the user from JFA-GO.**
    *   `/extend-plan [user] [jfa_username] [months/days/hours/minutes (at least one required)] [reason (optional)] [notify (optional)]`: Extends a user's JFA-GO plan.

## Module Breakdown

*   **`main.py`**: Entry point; initializes logging, configuration, the bot instance, registers handlers, and runs the bot.
*   **`config.py`**: Loads and validates configuration from `config.yaml` and environment variables. Provides the `get_config_value()` helper. Does *not* export flat variables anymore.
*   **`logging_setup.py`**: Configures application-wide logging.
*   **`messaging.py`**: Loads `message_templates.json` and provides `get_message()`, `create_embed()`, and `get_bot_display_name()` helpers.
*   **`models.py`**: Defines data classes (e.g., `InviteInfo`, `AdminAction`).
*   **`database.py`**: Manages SQLite database interactions.
*   **`jfa_client.py`**: Handles all communication with the JFA-GO API.
*   **`bot.py`**: Defines the main `JfaGoBot` class, handles event processing, command tree setup, and core bot logic like admin logging and the expiry notification background task.
*   **`modules/commands/`**: Sub-package for command definitions:
    *   `auth.py`: Authorization decorator (`is_in_support_and_authorized()`).
    *   `invite_commands.py`: Logic for `/create-trial-invite`.
    *   `user_invite_commands.py`: Logic for `/create-user-invite`.
    *   `admin_commands.py`: Logic for `/remove_invite` and `/extend-plan`.

## Usage

Once the bot is running and configured:

1.  Invite the bot to your Discord server.
2.  Ensure commands are usable in channels/categories listed in `discord.command_channel_ids`.
3.  Ensure users who need to run commands have a role listed in `discord.command_authorized_roles`.
4.  Available slash commands (exact behavior and output are configurable):
    *   `/create-trial-invite`: Creates a trial invite for a user in the current channel/thread (user is auto-detected).
        <p align="center">
          <img src="images/create_trial_invite_command.png" alt="Create Trial Invite Command Screenshot" width="600"/>
        </p>
    *   `/create-user-invite [user] [plan_type] [months (optional)] [days (optional)]`: Creates a user invite for a specified Discord user, assigning them to a JFA-GO plan.
        <p align="center">
          <img src="images/create_user_invite_command.png" alt="Create User Invite Command Screenshot" width="600"/>
        </p>
    *   `/remove_invite [user]`: Removes an invite record for a specified Discord user from Jellycord's database and attempts to revert their Discord roles. **Does not remove the user from JFA-GO.**
        <p align="center">
          <img src="images/remove_invite_command.png" alt="Remove Invite Command Screenshot" width="600"/>
        </p>
    *   `/extend-plan [user] [jfa_username] [months/days/hours/minutes (at least one required)] [reason (optional)] [notify (optional)]`: Extends a user's JFA-GO plan.
        <p align="center">
          <img src="images/extend_plan_command.png" alt="Extend Plan Command Screenshot" width="600"/>
        </p>

## Contributing

Contributions, issues, and feature requests are welcome!

## License

This project is licensed under the GNU License. See the `LICENSE` file for details.
