"""
auth/user_store.py
SQLite-backed user and session management
"""

import uuid
import sqlite3
import threading
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import bcrypt

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# Context variable to store current user_id for request-scoped storage
_current_user_id: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)


def set_current_user(user_id: Optional[str]) -> None:
    """Set current request's user ID"""
    _current_user_id.set(user_id)


def get_current_user() -> Optional[str]:
    """Get current request's user ID"""
    return _current_user_id.get()


# Thread-local SQLite connection
_local = threading.local()


def _get_db_conn(db_path: str) -> sqlite3.Connection:
    """Get thread-local SQLite connection"""
    if not hasattr(_local, "conn") or _local.conn is None or getattr(_local, "_db_path", None) != db_path:
        _local.conn = sqlite3.connect(db_path, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local._db_path = db_path
    return _local.conn


class UserStore:
    """
    SQLite-backed user and session management
    Tables: users, sessions
    """

    def __init__(self, db_path: str = None):
        self._db_path = db_path or str(config.USERS_DB_PATH)
        # Ensure directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ensure_default_admin()

    def _ensure_default_admin(self):
        """Create default admin user if no admin exists"""
        conn = _get_db_conn(self._db_path)
        admin_exists = conn.execute(
            "SELECT id FROM users WHERE is_admin = 1"
        ).fetchone()
        if not admin_exists:
            logger.info("[UserStore] Creating default admin user (admin/admin123)")
            self.create_admin_user("admin", "admin123")

    def create_admin_user(self, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
        """Create an admin user"""
        if len(username) < 2:
            return None, "Username must be at least 2 characters"
        if len(password) < 4:
            return None, "Password must be at least 4 characters"

        conn = _get_db_conn(self._db_path)
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return None, "Username already exists"

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        password_hash = self._hash_password(password)
        created_at = datetime.utcnow().isoformat()

        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, password_hash, 1, created_at)
        )
        conn.commit()
        logger.info(f"[UserStore] Created admin user: {username} ({user_id})")
        return user_id, None

    def _init_db(self):
        """Initialize database tables"""
        conn = _get_db_conn(self._db_path)

        # Create users table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # Create sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Create index on sessions for faster lookups
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)
        """)

        # Impersonation tokens for admin delegation
        conn.execute("""
            CREATE TABLE IF NOT EXISTS impersonation_tokens (
                id TEXT PRIMARY KEY,
                admin_user_id TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                audit_log TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id TEXT PRIMARY KEY,
                admin_user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_user_id TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()
        logger.info(f"[UserStore] Database initialized: {self._db_path}")

    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against bcrypt hash"""
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

    def _generate_user_id(self) -> str:
        """Generate user ID in format: user_{uuid_hex[:12]}"""
        return f"user_{uuid.uuid4().hex[:12]}"

    def _generate_session_id(self) -> str:
        """Generate session ID"""
        return str(uuid.uuid4())

    def register_user(self, username: str, password: str) -> tuple:
        """
        Register a new user

        Returns:
            (user_id, error) - user_id on success, error message on failure
        """
        if not username or not password:
            return None, "Username and password are required"

        if len(password) < 6:
            return None, "Password must be at least 6 characters"

        # Check if username already exists
        conn = _get_db_conn(self._db_path)
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if existing:
            return None, "Username already exists"

        # Create user
        user_id = self._generate_user_id()
        password_hash = self._hash_password(password)
        created_at = datetime.now(timezone.utc).isoformat()

        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, password_hash, 0, created_at)
            )
            conn.commit()
            logger.info(f"[UserStore] User registered: {username} ({user_id})")
            return user_id, None
        except Exception as e:
            logger.error(f"[UserStore] Failed to register user: {e}")
            return None, str(e)

    def login_user(self, username: str, password: str) -> Dict[str, Any]:
        """
        Login user with username and password

        Returns:
            Dict with session_id, user_id, username, is_admin on success
            Dict with "error" key on failure
        """
        conn = _get_db_conn(self._db_path)

        # Find user
        row = conn.execute(
            "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if not row:
            logger.warning(f"[UserStore] Login failed - user not found: {username}")
            return {"error": "Invalid username or password"}

        # Verify password
        if not self._verify_password(password, row["password_hash"]):
            logger.warning(f"[UserStore] Login failed - wrong password: {username}")
            return {"error": "Invalid username or password"}

        # Create session
        session_id = self._generate_session_id()
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(days=7)  # 7 days expiry

        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, row["id"], created_at.isoformat(), expires_at.isoformat())
        )
        conn.commit()

        logger.info(f"[UserStore] User logged in: {username}")

        return {
            "session_id": session_id,
            "user_id": row["id"],
            "username": row["username"],
            "is_admin": bool(row["is_admin"])
        }

    def validate_session(self, session_id: str) -> Optional[str]:
        """
        Validate session and return user_id if valid

        Returns:
            user_id if session is valid and not expired
            None otherwise
        """
        if not session_id:
            return None

        conn = _get_db_conn(self._db_path)

        row = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()

        if not row:
            return None

        # Check if session expired
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                # Delete expired session
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                conn.commit()
                return None
        except ValueError:
            return None

        return row["user_id"]

    def validate_session_with_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Validate session and return full session data including is_admin flag.
        Returns: {user_id, is_admin} or None if invalid/expired
        """
        if not session_id:
            return None

        conn = _get_db_conn(self._db_path)
        row = conn.execute("""
            SELECT s.user_id, u.is_admin
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = ? AND s.expires_at > ?
        """, (session_id, datetime.now(timezone.utc).isoformat())).fetchone()

        if not row:
            return None

        return {"user_id": row[0], "is_admin": bool(row[1])}

    def logout_user(self, session_id: str) -> bool:
        """
        Logout user by deleting session

        Returns:
            True if session was deleted
            False if session not found
        """
        conn = _get_db_conn(self._db_path)

        result = conn.execute(
            "DELETE FROM sessions WHERE id = ?",
            (session_id,)
        )
        conn.commit()

        if result.rowcount > 0:
            logger.info(f"[UserStore] Session logged out: {session_id}")
            return True
        return False

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user info by user_id

        Returns:
            Dict with id, username, is_admin, created_at
            None if user not found
        """
        conn = _get_db_conn(self._db_path)

        row = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        if not row:
            return None

        return {
            "id": row["id"],
            "username": row["username"],
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"]
        }

    def list_users(self) -> List[Dict[str, Any]]:
        """
        List all users (for admin)

        Returns:
            List of dicts with id, username, is_admin, created_at
        """
        conn = _get_db_conn(self._db_path)

        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()

        return [
            {
                "id": row["id"],
                "username": row["username"],
                "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"]
            }
            for row in rows
        ]

    def delete_user(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Delete user and all their sessions

        Returns:
            Tuple of (success, error_message)
            (True, None) if user was deleted
            (False, "User not found") if user not found
            (False, "Cannot delete admin user") if attempting to delete admin
        """
        conn = _get_db_conn(self._db_path)

        # Check if user exists and get is_admin flag
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False, "User not found"

        # Check if user is admin
        if user[0]:  # is_admin
            return False, "Cannot delete admin user"

        # Delete sessions first (foreign key constraint)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

        # Delete user
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

        logger.info(f"[UserStore] User deleted: {user_id}")
        return True, None

    def delete_user_cascade(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Delete user and ALL their data (cascade delete).
        Returns (success, error_message).
        """
        import shutil
        from pathlib import Path

        conn = _get_db_conn(self._db_path)

        # Check user exists and is not admin
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False, "User not found"
        if user[0]:
            return False, "Cannot delete admin user"

        # Clear in-memory stores (important!)
        from memory.memory_store import _stores as memory_stores
        from auth.token_store import _token_stores as token_stores
        memory_stores.pop(user_id, None)
        token_stores.pop(user_id, None)

        # Delete sessions
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

        # Delete impersonation tokens (where admin or target)
        conn.execute("DELETE FROM impersonation_tokens WHERE admin_user_id = ? OR target_user_id = ?",
                     (user_id, user_id))

        # Delete user
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

        # Delete storage files
        from config import DATA_DIR

        # Delete memories DB
        mem_db = DATA_DIR / f"memories_{user_id}.db"
        if mem_db.exists():
            mem_db.unlink()

        # Delete FAISS index directory
        faiss_dir = DATA_DIR / "vectors" / user_id
        if faiss_dir.exists():
            shutil.rmtree(faiss_dir)

        # Delete auth tokens directory
        auth_dir = DATA_DIR / "auth" / user_id
        if auth_dir.exists():
            shutil.rmtree(auth_dir)

        logger.info(f"[UserStore] Cascade deleted user: {user_id}")
        return True, None


# ── Global singleton ─────────────────────────────────────────────────────────
_user_store: Optional[UserStore] = None


def get_user_store() -> UserStore:
    """Get the global UserStore singleton instance"""
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store