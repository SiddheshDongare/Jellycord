# Project Brief

*This document is the foundation for the project. It defines the core requirements, goals, and overall scope.*

## Core Requirements

- Integrate with JFA-GO to manage user invites for a Jellyfin media server.
- Allow authorized Discord users to create trial and paid invite links.
- Allow authorized Discord users to manage existing invites (remove, extend plans).
- Provide user notifications for account expiry.
- Implement role-based access control for commands.
- Log administrative actions to a Discord channel and a local database.
- Offer high configurability for bot behavior, settings, messages, and embed appearances (via YAML and JSON).
- Support Docker for deployment.

## Goals

- To provide a seamless way for Discord community administrators to manage Jellyfin user access via JFA-GO.
- To automate invite creation and user lifecycle management (expiry notifications).
- To centralize JFA-GO user management tasks within Discord.
- To maintain a high degree of customizability to fit various server needs.

## Scope

- **In Scope:**
    - Creation of trial and paid invites linked to JFA-GO.
    - Removal of invite records from the bot's database and Discord roles.
    - Extension of JFA-GO user account expiry.
    - Automated DM notifications to users before account expiry.
    - Admin logging of bot actions.
    - Configuration of bot name, JFA-GO connection, Discord server specifics, command behaviors, message templates, embed appearances.
- **Out of Scope (Current Limitations as per README.md):**
    - Migration of existing users from JFA-GO database to the bot's database.
    - Direct removal of users from JFA-GO itself (the `/remove_invite` command only affects the bot's DB and Discord roles).
