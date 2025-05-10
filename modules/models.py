"""Data models for the application."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class InviteInfo:
    """Model for invite information."""

    code: str
    label: str
    created_at: int
    expires_at: int
    claimed: bool
    jfa_user_id: Optional[str] = None
    plan_type: Optional[str] = None
    account_expires_at: Optional[int] = None
    last_notified_at: Optional[int] = None


@dataclass
class AdminAction:
    """Model for admin actions."""

    admin_id: str
    admin_username: str
    action_type: str
    target_user_id: str
    target_username: str
    details: Optional[str]
    performed_at: int
