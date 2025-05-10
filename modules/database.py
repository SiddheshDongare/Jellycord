"""Database operations for the application."""

import datetime
import logging
import sqlite3
from contextlib import contextmanager
from typing import Generator, List, Optional

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
    last_notified_at INTEGER NULL   -- Added: Timestamp when expiry notification was last sent
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
        self.logger.debug(
            f"Recording invite for user {username} (ID: {user_id}), code: {invite_code}, plan: {plan_type}, expiry: {account_expires_at}"
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
                            plan_type, account_expires_at
                            -- jfa_user_id and last_notified_at are not set here
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            username = excluded.username,
                            invite_code = excluded.invite_code,
                            created_at = excluded.created_at, -- Reset created_at for expiry calculation
                            updated_at = excluded.updated_at,
                            claimed = FALSE, -- Reset claimed status on new invite
                            plan_type = excluded.plan_type,
                            account_expires_at = excluded.account_expires_at,
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
                        ),
                    )
                    self.logger.info(
                        f"Recorded/Updated invite for user {username} (ID: {user_id}) with code {invite_code}"
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
        """Get users whose accounts expire within the configured notice period."""
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
