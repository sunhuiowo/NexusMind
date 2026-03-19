"""Impersonation token management for admin users"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth.user_store import get_user_store, _get_db_conn
import config

logger = logging.getLogger(__name__)

IMPERSONATION_EXPIRY_HOURS = 8  # Admin impersonation expires after 8 hours


def _get_conn():
    """Get database connection for impersonation tables (same DB as user_store)"""
    # Use same db path as user_store
    db_path = str(config.AUTH_DIR / "users.db")
    return _get_db_conn(db_path)


def create_impersonation_token(admin_user_id: str, target_user_id: str) -> Tuple[str, Optional[str]]:
    """
    Create an impersonation token for an admin to act as target_user.
    Returns: (token_id, error_or_none)
    """
    conn_userstore = _get_conn()

    # Verify admin is actually an admin
    admin = conn_userstore.execute("SELECT is_admin FROM users WHERE id = ?", (admin_user_id,)).fetchone()
    if not admin or not admin[0]:
        return "", "Not authorized to impersonate"

    # Verify target user exists and is NOT an admin
    target = conn_userstore.execute("SELECT id, is_admin FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        return "", "Target user not found"
    if target[1]:  # is_admin
        return "", "Cannot impersonate another admin"

    token_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=IMPERSONATION_EXPIRY_HOURS)).isoformat()

    conn_userstore.execute("""
        INSERT INTO impersonation_tokens (id, admin_user_id, target_user_id, created_at, expires_at, audit_log)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (token_id, admin_user_id, target_user_id, created_at, expires_at, json.dumps([])))

    # Log impersonation start
    conn_userstore.execute("""
        INSERT INTO admin_audit_logs (id, admin_user_id, action, target_user_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), admin_user_id, "impersonate_start", target_user_id,
          json.dumps({"token_id": token_id}), created_at))
    conn_userstore.commit()

    logger.info(f"[Impersonation] Admin {admin_user_id} started impersonating {target_user_id}")
    return token_id, None


def validate_impersonation_token(token_id: str) -> Optional[Dict[str, str]]:
    """
    Validate an impersonation token and return the mapping if valid.
    Returns: {admin_user_id, target_user_id} or None if invalid/expired
    """
    conn = _get_conn()

    row = conn.execute("""
        SELECT admin_user_id, target_user_id, expires_at
        FROM impersonation_tokens
        WHERE id = ?
    """, (token_id,)).fetchone()

    if not row:
        return None

    admin_user_id, target_user_id, expires_at = row

    # Check expiry
    try:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if datetime.now(timezone.utc) > expires_dt:
        return None

    return {"admin_user_id": admin_user_id, "target_user_id": target_user_id}


def revoke_impersonation_token(token_id: str, admin_user_id: str) -> Tuple[bool, Optional[str]]:
    """
    Revoke an impersonation token (admin ends their impersonation session).
    Returns: (success, error_or_none)
    """
    conn = _get_conn()

    token = conn.execute("""
        SELECT admin_user_id, target_user_id FROM impersonation_tokens WHERE id = ?
    """, (token_id,)).fetchone()

    if not token:
        return False, "Token not found"

    if token[0] != admin_user_id:
        return False, "Not authorized to revoke this token"

    conn.execute("DELETE FROM impersonation_tokens WHERE id = ?", (token_id,))

    # Log impersonation end
    conn.execute("""
        INSERT INTO admin_audit_logs (id, admin_user_id, action, target_user_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), admin_user_id, "impersonate_end", token[1],
          json.dumps({"token_id": token_id}), datetime.now(timezone.utc).isoformat()))
    conn.commit()

    logger.info(f"[Impersonation] Admin {admin_user_id} ended impersonation of {token[1]}")
    return True, None


def append_to_audit_log(token_id: str, action: Dict[str, Any]):
    """Append an action to the impersonation token's audit log."""
    conn = _get_conn()

    row = conn.execute("SELECT audit_log FROM impersonation_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        return

    audit_log = json.loads(row[0] or "[]")
    audit_log.append({**action, "timestamp": datetime.now(timezone.utc).isoformat()})

    conn.execute("UPDATE impersonation_tokens SET audit_log = ? WHERE id = ?",
                  (json.dumps(audit_log), token_id))
    conn.commit()