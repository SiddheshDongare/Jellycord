"""Database operations for the application."""

import datetime
import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator, List, Optional, Dict, Any

from modules.config import get_config_value
from modules.models import AdminAction, InviteInfo

# Database schema
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_invites (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    invite_code TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    claimed BOOLEAN NOT NULL DEFAULT FALSE,
    jfa_user_id TEXT NULL,          -- Added: Corresponding JFA-GO User ID (once known)
    plan_type TEXT NULL,            -- Added: e.g., 'Trial', 'Premium Profile'
    account_expires_at INTEGER NULL,-- Added: Timestamp when the JFA-GO account expires
    last_notified_at INTEGER NULL,  -- Added: Timestamp when expiry notification was last sent
    status TEXT NULL                -- Added: 'trial', 'paid', 'disabled'
);

CREATE TABLE IF NOT EXISTS admin_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id TEXT NOT NULL,
    admin_username TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    target_username TEXT NOT NULL,
    details TEXT,
    performed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jfa_user_cache (
    jfa_id TEXT PRIMARY KEY,
    jellyfin_username TEXT NOT NULL UNIQUE,
    discord_id TEXT UNIQUE,
    email TEXT,
    expiry INTEGER,
    disabled BOOLEAN,
    jfa_accounts_admin BOOLEAN,
    jfa_admin BOOLEAN,
    last_synced INTEGER NOT NULL
);
"""


class Database:
    """Handles database operations with proper connection management and error handling"""

    def __init__(self, db_file_path: str):
        self.db_file = db_file_path
        self.logger = logging.getLogger(
            self.__class__.__name__
        )  # Logger for Database class
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database with required tables"""
        try:
            with self._get_connection() as conn:
                conn.executescript(CREATE_TABLE_SQL)
                conn.commit()
                self.logger.info(f"Database initialized successfully: {self.db_file}")
        except Exception as e:
            self.logger.critical(
                f"Failed to initialize database {self.db_file}: {str(e)}"
            )
            raise

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections with proper error handling"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            self.logger.debug(f"Database connection opened: {self.db_file}")
            yield conn
        except sqlite3.Error as e:
            self.logger.error(f"Database error ({self.db_file}): {str(e)}")
            raise
        finally:
            if conn:
                conn.close()
                self.logger.debug(f"Database connection closed: {self.db_file}")

    def get_invite_info(self, user_id: str) -> Optional[InviteInfo]:
        """Get invite information for a user"""
        self.logger.debug(f"Fetching invite info for user_id: {user_id}")
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM user_invites WHERE user_id = ?", (user_id,)
                )
                row = cursor.fetchone()
                if row:
                    self.logger.debug(f"Found invite record for user_id: {user_id}")
                    link_validity_days = get_config_value(
                        "invite_settings.link_validity_days", 1
                    )
                    return InviteInfo(
                        code=row["invite_code"],
                        label=f"{row['username']} - {datetime.datetime.fromtimestamp(row['created_at']).strftime('%Y-%m-%d')}",
                        created_at=row["created_at"],
                        expires_at=row["created_at"] + (link_validity_days * 86400),
                        claimed=bool(row["claimed"]),
                        jfa_user_id=row["jfa_user_id"],
                        plan_type=row["plan_type"],
                        account_expires_at=row["account_expires_at"],
                        last_notified_at=row["last_notified_at"],
                    )
                self.logger.debug(f"No invite record found for user_id: {user_id}")
                return None
        except Exception as e:
            self.logger.error(
                f"Error getting invite info for user_id {user_id}: {str(e)}"
            )
            return None

    def record_invite(
        self,
        user_id: str,
        username: str,
        invite_code: str,
        plan_type: Optional[str] = None,
        account_expires_at: Optional[int] = None,
    ) -> None:
        """Record or update a user's invite information."""
        # Determine status based on plan_type
        status = None
        if plan_type:
            if "trial" in plan_type.lower():
                status = "trial"
            else:
                status = "paid"  # Assume any non-trial plan is 'paid'

        self.logger.debug(
            f"Recording invite for user {username} (ID: {user_id}), code: {invite_code}, plan: {plan_type}, expiry: {account_expires_at}, status: {status}"
        )
        try:
            now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            with self._get_connection() as conn:
                with conn:  # Use transaction
                    # When updating, preserve existing jfa_user_id and last_notified_at unless explicitly changed elsewhere
                    conn.execute(
                        """
                        INSERT INTO user_invites (
                            user_id, username, invite_code, created_at, updated_at, claimed,
                            plan_type, account_expires_at, status
                            -- jfa_user_id and last_notified_at are not set here initially
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            username = excluded.username,
                            invite_code = excluded.invite_code,
                            created_at = excluded.created_at, -- Reset created_at for expiry calculation
                            updated_at = excluded.updated_at,
                            claimed = FALSE, -- Reset claimed status on new invite
                            plan_type = excluded.plan_type,
                            account_expires_at = excluded.account_expires_at,
                            status = excluded.status, -- Update status
                            last_notified_at = NULL -- Reset notification status on new invite
                        """,
                        (
                            user_id,
                            username,
                            invite_code,
                            now,  # created_at
                            now,  # updated_at
                            False,  # claimed
                            plan_type,
                            account_expires_at,
                            status,  # new status field
                        ),
                    )
                    self.logger.info(
                        f"Recorded/Updated invite for user {username} (ID: {user_id}) with code {invite_code}, status {status}"
                    )
        except Exception as e:
            self.logger.error(
                f"Error recording invite for user {username} (ID: {user_id}): {str(e)}"
            )
            raise

    def mark_invite_claimed(self, user_id: str) -> None:
        """Mark an invite as claimed"""
        self.logger.debug(f"Marking invite as claimed for user_id: {user_id}")
        try:
            with self._get_connection() as conn:
                with conn:  # Use transaction
                    conn.execute(
                        "UPDATE user_invites SET claimed = TRUE WHERE user_id = ?",
                        (user_id,),
                    )
                    self.logger.info(f"Marked invite as claimed for user {user_id}")
        except Exception as e:
            self.logger.error(
                f"Error marking invite as claimed for user {user_id}: {str(e)}"
            )
            raise

    def record_admin_action(self, action: AdminAction) -> None:
        """Record an admin action in the database"""
        self.logger.debug(
            f"Recording admin action: {action.action_type} by {action.admin_username} for {action.target_username}"
        )
        try:
            with self._get_connection() as conn:
                with conn:  # Use transaction
                    conn.execute(
                        """
                        INSERT INTO admin_actions (
                            admin_id, admin_username, action_type,
                            target_user_id, target_username, details, performed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            action.admin_id,
                            action.admin_username,
                            action.action_type,
                            action.target_user_id,
                            action.target_username,
                            action.details,
                            action.performed_at,
                        ),
                    )
                    self.logger.info(
                        f"Recorded admin action: {action.action_type} by {action.admin_username} for {action.target_username} ID {action.target_user_id}"
                    )
        except Exception as e:
            self.logger.error(
                f"Error recording admin action {action.action_type} by {action.admin_username}: {str(e)}"
            )
            raise

    def delete_invite(self, user_id: str) -> bool:
        """Delete an invite for a user"""
        self.logger.debug(f"Attempting to delete invite for user_id: {user_id}")
        try:
            with self._get_connection() as conn:
                with conn:  # Use transaction
                    cursor = conn.execute(
                        "DELETE FROM user_invites WHERE user_id = ?", (user_id,)
                    )
                    deleted = cursor.rowcount > 0
                    if deleted:
                        self.logger.info(
                            f"Deleted invite record for user_id: {user_id}"
                        )
                    else:
                        # This isn't necessarily a warning, could be normal operation
                        self.logger.info(
                            f"Attempted to delete invite for user_id {user_id}, but no record was found."
                        )
                    return deleted
        except Exception as e:
            self.logger.error(f"Error deleting invite for user {user_id}: {str(e)}")
            return False

    def clear_account_expiry(self, user_id: str) -> None:
        """Set account_expires_at and last_notified_at to NULL for a user."""
        self.logger.debug(
            f"Clearing account expiry and notification status for user_id: {user_id}"
        )
        try:
            with self._get_connection() as conn:
                with conn:  # Transaction
                    conn.execute(
                        "UPDATE user_invites SET account_expires_at = NULL, last_notified_at = NULL WHERE user_id = ?",
                        (user_id,),
                    )
                    self.logger.info(
                        f"Cleared account expiry/notification status for user_id {user_id}"
                    )
        except Exception as e:
            self.logger.error(
                f"Error clearing account expiry for user {user_id}: {str(e)}"
            )
            # Optionally raise e depending on desired error handling

    def update_last_notified(self, user_id: str, timestamp: int) -> None:
        """Update the last_notified_at timestamp for a user."""
        self.logger.debug(
            f"Updating last_notified_at for user_id: {user_id} to {timestamp}"
        )
        try:
            with self._get_connection() as conn:
                with conn:  # Transaction
                    conn.execute(
                        "UPDATE user_invites SET last_notified_at = ? WHERE user_id = ?",
                        (timestamp, user_id),
                    )
                    self.logger.info(f"Updated last_notified_at for user_id {user_id}")
        except Exception as e:
            self.logger.error(
                f"Error updating last_notified_at for user {user_id}: {str(e)}"
            )
            # Optionally raise e

    def get_expiring_users(self, days_notice: int) -> List[sqlite3.Row]:
        """Get users from user_invites table whose accounts are expiring soon and haven't been notified recently."""
        self.logger.debug(f"Fetching users expiring within {days_notice} days.")
        now = int(
            datetime.datetime.now(datetime.timezone.utc).timestamp()
        )  # Ensure UTC
        # Calculate the timestamp for X days from now
        notice_timestamp = now + (days_notice * 86400)
        # The check for "notified recently" is handled in bot.py using a configurable interval.
        # recent_notification_threshold = now - 604800 # Removed unused variable

        results = []
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT user_id, username, account_expires_at, plan_type, last_notified_at
                    FROM user_invites
                    WHERE account_expires_at IS NOT NULL
                    AND account_expires_at <= ? -- Expires within the notice period (or slightly beyond)
                    AND account_expires_at > ?  -- Has not already expired
                    """,
                    (notice_timestamp, now),
                )
                results = cursor.fetchall()
                self.logger.info(
                    f"Found {len(results)} users nearing account expiry for notification."
                )
        except Exception as e:
            self.logger.error(f"Error fetching expiring users: {str(e)}")
            # Return empty list on error

        return results

    def upsert_jfa_users(self, users_data: List[Dict[str, Any]]) -> None:
        """Bulk inserts or updates JFA-GO user data into the jfa_user_cache table."""
        if not users_data:
            self.logger.info("upsert_jfa_users: No user data provided to upsert.")
            return

        self.logger.info(f"Upserting {len(users_data)} users into jfa_user_cache.")
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

        records_to_upsert = []
        for user_info in users_data:
            if not user_info.get("id") or not user_info.get("name"):
                self.logger.warning(
                    f"Skipping user data due to missing id or name: {user_info}"
                )
                continue

            discord_id_val = user_info.get("discord_id")
            # Convert empty string discord_id to None to play well with UNIQUE constraint if multiple users have no Discord ID
            if discord_id_val == "":
                discord_id_val = None

            records_to_upsert.append(
                (
                    user_info.get("id"),
                    user_info.get("name"),
                    discord_id_val,  # Use the potentially modified value
                    user_info.get("email"),
                    user_info.get("expiry"),
                    user_info.get("disabled"),
                    user_info.get("accounts_admin"),  # from JFA-GO field name
                    user_info.get("admin"),  # from JFA-GO field name
                    now,
                )
            )

        if not records_to_upsert:
            self.logger.info(
                "upsert_jfa_users: No valid records to upsert after filtering."
            )
            return

        try:
            with self._get_connection() as conn:
                with conn:  # Transaction
                    conn.executemany(
                        """
                        INSERT INTO jfa_user_cache (
                            jfa_id, jellyfin_username, discord_id, email, expiry,
                            disabled, jfa_accounts_admin, jfa_admin, last_synced
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(jfa_id) DO UPDATE SET
                            jellyfin_username = excluded.jellyfin_username,
                            discord_id = excluded.discord_id,
                            email = excluded.email,
                            expiry = excluded.expiry,
                            disabled = excluded.disabled,
                            jfa_accounts_admin = excluded.jfa_accounts_admin,
                            jfa_admin = excluded.jfa_admin,
                            last_synced = excluded.last_synced;
                    """,
                        records_to_upsert,
                    )
                    self.logger.info(
                        f"Successfully upserted {len(records_to_upsert)} records into jfa_user_cache."
                    )
        except sqlite3.Error as e:
            self.logger.error(
                f"Database error during jfa_user_cache upsert: {e}", exc_info=True
            )
            # Depending on severity, you might want to raise this
        except Exception as e:
            self.logger.error(
                f"Unexpected error during jfa_user_cache upsert: {e}", exc_info=True
            )
            # Depending on severity, you might want to raise this

    def get_jfa_user_from_cache_by_discord_id(
        self, discord_id: str
    ) -> Optional[sqlite3.Row]:
        """Fetches a JFA-GO user from the cache by their Discord ID."""
        self.logger.debug(f"Fetching JFA user from cache by discord_id: {discord_id}")
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM jfa_user_cache WHERE discord_id = ?", (discord_id,)
                )
                row = cursor.fetchone()
                if row:
                    self.logger.debug(
                        f"Found JFA user in cache for discord_id: {discord_id}"
                    )
                    return row
                self.logger.debug(
                    f"No JFA user found in cache for discord_id: {discord_id}"
                )
                return None
        except Exception as e:
            self.logger.error(
                f"Error getting JFA user from cache by discord_id {discord_id}: {e}",
                exc_info=True,
            )
            return None

    def get_jfa_user_from_cache_by_jellyfin_username(
        self, jellyfin_username: str
    ) -> Optional[sqlite3.Row]:
        """Fetches a JFA-GO user from the cache by their Jellyfin username."""
        self.logger.debug(
            f"Fetching JFA user from cache by jellyfin_username: {jellyfin_username}"
        )
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM jfa_user_cache WHERE jellyfin_username = ?",
                    (jellyfin_username,),
                )
                row = cursor.fetchone()
                if row:
                    self.logger.debug(
                        f"Found JFA user in cache for jellyfin_username: {jellyfin_username}"
                    )
                    return row
                self.logger.debug(
                    f"No JFA user found in cache for jellyfin_username: {jellyfin_username}"
                )
                return None
        except Exception as e:
            self.logger.error(
                f"Error getting JFA user from cache by jellyfin_username {jellyfin_username}: {e}",
                exc_info=True,
            )
            return None

    def get_jfa_user_from_cache_by_jfa_id(self, jfa_id: str) -> Optional[sqlite3.Row]:
        """Fetches a JFA-GO user from the cache by their JFA ID."""
        self.logger.debug(f"Fetching JFA user from cache by jfa_id: {jfa_id}")
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM jfa_user_cache WHERE jfa_id = ?", (jfa_id,)
                )
                row = cursor.fetchone()
                if row:
                    self.logger.debug(f"Found JFA user in cache for jfa_id: {jfa_id}")
                    return row
                self.logger.debug(f"No JFA user found in cache for jfa_id: {jfa_id}")
                return None
        except Exception as e:
            self.logger.error(
                f"Error getting JFA user from cache by jfa_id {jfa_id}: {e}",
                exc_info=True,
            )
            return None

    def update_user_invite_status(self, user_id: str, status: str) -> bool:
        """Update the status of a user's invite record (e.g., 'trial', 'paid', 'disabled')."""
        allowed_statuses = [
            "trial",
            "paid",
            "disabled",
            None,
        ]  # None could be used to clear it, though 'disabled' is preferred for removal.
        if status not in allowed_statuses and status is not None:  # Allow explicit None
            self.logger.warning(
                f"Attempted to set invalid status '{status}' for user_id {user_id}. Allowed: {allowed_statuses}"
            )
            return False

        self.logger.debug(f"Updating status to '{status}' for user_id: {user_id}")
        try:
            with self._get_connection() as conn:
                with conn:  # Use transaction
                    cursor = conn.execute(
                        "UPDATE user_invites SET status = ?, updated_at = ? WHERE user_id = ?",
                        (
                            status,
                            int(
                                datetime.datetime.now(datetime.timezone.utc).timestamp()
                            ),
                            user_id,
                        ),
                    )
                    if cursor.rowcount > 0:
                        self.logger.info(
                            f"Successfully updated status to '{status}' for user_id {user_id}"
                        )
                        return True
                    else:
                        self.logger.warning(
                            f"No user_invite record found for user_id {user_id} to update status."
                        )
                        return False
        except Exception as e:
            self.logger.error(
                f"Error updating status for user {user_id} to '{status}': {str(e)}",
                exc_info=True,
            )
            return False
