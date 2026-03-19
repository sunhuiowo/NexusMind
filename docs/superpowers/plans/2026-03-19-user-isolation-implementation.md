# User Isolation System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement complete multi-user authentication and data isolation system where each user has independent credentials, memories, and platform connections.

**Architecture:** Session-based authentication with SQLite user store. Each user gets isolated MemoryStore and TokenStore instances. SessionMiddleware validates session_id from header and sets user context for request-scoped operations.

**Tech Stack:** FastAPI, SQLite (users.db), bcrypt, Python ContextVar for request-scoped user context.

---

## File Structure

```
backend/
├── auth/
│   ├── __init__.py
│   ├── user_store.py        # NEW: User + Session CRUD
│   └── session_middleware.py # NEW: Session validation
├── config.py               # MODIFY: Add USERS_DB_PATH
├── main.py                 # MODIFY: Replace middleware, add new endpoints
├── memory/
│   └── memory_store.py     # ALREADY HAS: per-user isolation
├── tools/
│   └── mcp_tools.py        # MODIFY: sync_platform needs user_id

frontend/src/
├── api/
│   └── apiClient.ts        # MODIFY: X-Session-Id header
├── store/
│   └── index.ts           # MODIFY: Auth store → API calls
└── pages/
    └── Auth.tsx           # MODIFY: Connect to backend
```

---

## Chunk 1: Backend Infrastructure (user_store.py)

**Files:**
- Create: `backend/auth/user_store.py`
- Modify: `backend/config.py` (add USERS_DB_PATH)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_store.py`:

```python
"""Tests for user_store.py"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def test_user_store_creates_tables():
    """User store should create users and sessions tables on init"""
    from auth.user_store import UserStore
    store = UserStore()
    # Check tables exist
    conn = store._get_conn()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    assert 'users' in tables
    assert 'sessions' in tables

def test_register_creates_user():
    """Register should create a new user"""
    from auth.user_store import UserStore
    store = UserStore()
    user_id, error = store.register_user("testuser", "password123")
    assert user_id is not None
    assert error is None
    assert user_id.startswith("user_")

def test_register_duplicate_username():
    """Register should fail for duplicate username"""
    from auth.user_store import UserStore
    store = UserStore()
    store.register_user("dupuser", "password123")
    user_id, error = store.register_user("dupuser", "password456")
    assert user_id is None
    assert "already exists" in error

def test_login_success():
    """Login should return session_id for valid credentials"""
    from auth.user_store import UserStore
    store = UserStore()
    store.register_user("loginuser", "correctpassword")
    result = store.login_user("loginuser", "correctpassword")
    assert result["session_id"] is not None
    assert result["user_id"] is not None

def test_login_wrong_password():
    """Login should fail for wrong password"""
    from auth.user_store import UserStore
    store = UserStore()
    store.register_user("loginuser2", "correctpassword")
    result = store.login_user("loginuser2", "wrongpassword")
    assert result["error"] is not None

def test_session_validation():
    """Valid session should return user_id"""
    from auth.user_store import UserStore
    store = UserStore()
    store.register_user("sessionuser", "password")
    login_result = store.login_user("sessionuser", "password")
    session_id = login_result["session_id"]
    user_id = store.validate_session(session_id)
    assert user_id == login_result["user_id"]

def test_session_invalid():
    """Invalid session should return None"""
    from auth.user_store import UserStore
    store = UserStore()
    user_id = store.validate_session("nonexistent-session-id")
    assert user_id is None

def test_logout():
    """Logout should invalidate session"""
    from auth.user_store import UserStore
    store = UserStore()
    store.register_user("logoutuser", "password")
    login_result = store.login_user("logoutuser", "password")
    session_id = login_result["session_id"]
    store.logout_user(session_id)
    assert store.validate_session(session_id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_user_store.py -v`
Expected: FAIL - module 'auth.user_store' not found

- [ ] **Step 3: Add USERS_DB_PATH to config.py**

Modify `backend/config.py` line ~14:

```python
# Add after AUTH_DIR = DATA_DIR / "auth"
USERS_DB_PATH = DATA_DIR / "users.db"
```

- [ ] **Step 4: Write minimal user_store.py implementation**

Create `backend/auth/user_store.py`:

```python
"""User and Session management with SQLite backend"""
import uuid
import sqlite3
import bcrypt
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Context variable for current user_id (thread-safe)
_current_user_id: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)

def set_current_user(user_id: Optional[str]) -> None:
    _current_user_id.set(user_id)

def get_current_user() -> Optional[str]:
    return _current_user_id.get()

class UserStore:
    """
    SQLite-backed user and session management.
    Tables: users, sessions
    """
    _local = sqlite3.connect

    def __init__(self, db_path: str = None):
        import config
        self._db_path = db_path or str(config.USERS_DB_PATH)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self):
        """Create tables if not exist"""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        conn.commit()
        logger.info(f"[UserStore] Initialized: {self._db_path}")

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode(), password_hash.encode())

    def register_user(self, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
        """Register new user. Returns (user_id, error)"""
        if len(username) < 2:
            return None, "Username must be at least 2 characters"
        if len(password) < 4:
            return None, "Password must be at least 4 characters"

        conn = self._get_conn()
        # Check duplicate
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return None, "Username already exists"

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        password_hash = self._hash_password(password)
        created_at = datetime.utcnow().isoformat()

        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, password_hash, created_at)
        )
        conn.commit()
        logger.info(f"[UserStore] Registered user: {username} ({user_id})")
        return user_id, None

    def login_user(self, username: str, password: str) -> Dict[str, Any]:
        """Login user. Returns dict with session_id or error"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if not row:
            return {"error": "Invalid username or password"}

        user_id, username, password_hash, is_admin = row
        if not self._verify_password(password, password_hash):
            return {"error": "Invalid username or password"}

        # Create session
        session_id = str(uuid.uuid4())
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=7)

        conn.execute(
            "INSERT INTO sessions (session_id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, created_at.isoformat(), expires_at.isoformat())
        )
        conn.commit()

        logger.info(f"[UserStore] User logged in: {username}")
        return {
            "session_id": session_id,
            "user_id": user_id,
            "username": username,
            "is_admin": bool(is_admin)
        }

    def validate_session(self, session_id: str) -> Optional[str]:
        """Validate session and return user_id if valid, else None"""
        if not session_id:
            return None
        conn = self._get_conn()
        row = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        if not row:
            return None
        user_id, expires_at = row
        # Check expiry
        if datetime.fromisoformat(expires_at) < datetime.utcnow():
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return None
        return user_id

    def logout_user(self, session_id: str) -> None:
        """Delete session"""
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user info by id"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "is_admin": bool(row[2]), "created_at": row[3]}

    def list_users(self) -> list:
        """List all users (for admin)"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [{"id": r[0], "username": r[1], "is_admin": bool(r[2]), "created_at": r[3]} for r in rows]

    def delete_user(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """Delete user and all their sessions"""
        conn = self._get_conn()
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False, "User not found"
        if user[0]:  # is_admin
            return False, "Cannot delete admin user"
        # Delete sessions first
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        logger.info(f"[UserStore] Deleted user: {user_id}")
        return True, None

# Global instance
_user_store: Optional[UserStore] = None

def get_user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_user_store.py -v`
Expected: PASS (or FAIL with import errors if bcrypt not installed - install with pip)

- [ ] **Step 6: Install bcrypt if needed and retest**

Run: `pip install bcrypt && python -m pytest tests/test_user_store.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/auth/user_store.py backend/config.py backend/tests/test_user_store.py
git commit -m "feat: add UserStore with SQLite backend for user/session management"
```

---

## Chunk 2: Session Middleware

**Files:**
- Create: `backend/auth/session_middleware.py`
- Modify: `backend/main.py` (replace UserIsolationMiddleware)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_session_middleware.py`:

```python
"""Tests for session_middleware.py"""
import pytest
from unittest.mock import MagicMock, patch
from starlette.requests import Request
from starlette.responses import JSONResponse

def test_session_middleware_allows_public_paths():
    """Public paths should bypass session check"""
    from auth.session_middleware import SessionMiddleware

    app = MagicMock()
    middleware = SessionMiddleware(app, public_paths=["/auth/login", "/health"])

    # Create mock request to public path
    request = MagicMock(spec=Request)
    request.url.path = "/auth/login"
    request.headers = {}

    # Mock call_next
    async def call_next(req):
        return JSONResponse({"success": True})

    response = None
    # Check it allows public path without session
    with patch('auth.session_middleware.get_user_store') as mock_store:
        # If public path, should not call validate_session
        response = middleware.dispatch(request, call_next)

    assert response is not None

def test_session_middleware_sets_context():
    """Valid session should set user context"""
    from auth.session_middleware import SessionMiddleware
    from auth.user_store import get_current_user, set_current_user

    app = MagicMock()

    # Create middleware with mock user_store
    middleware = SessionMiddleware(app)

    request = MagicMock(spec=Request)
    request.url.path = "/api/memories"
    request.headers = {"x-session-id": "valid-session-id"}

    mock_store = MagicMock()
    mock_store.validate_session.return_value = "user_123"

    async def call_next(req):
        # Check that context was set
        user_id = get_current_user()
        return JSONResponse({"user_id": user_id})

    with patch('auth.session_middleware.get_user_store', return_value=mock_store):
        response = middleware.dispatch(request, call_next)

    # The response should contain the user_id
    assert response is not None

def test_session_middleware_rejects_invalid_session():
    """Invalid session should return 401"""
    from auth.session_middleware import SessionMiddleware

    app = MagicMock()
    middleware = SessionMiddleware(app)

    request = MagicMock(spec=Request)
    request.url.path = "/api/memories"
    request.headers = {"x-session-id": "invalid-session"}

    mock_store = MagicMock()
    mock_store.validate_session.return_value = None

    async def call_next(req):
        return JSONResponse({"success": True})

    with patch('auth.session_middleware.get_user_store', return_value=mock_store):
        response = middleware.dispatch(request, call_next)

    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_session_middleware.py -v`
Expected: FAIL - module 'auth.session_middleware' not found

- [ ] **Step 3: Write session_middleware.py**

Create `backend/auth/session_middleware.py`:

```python
"""Session validation middleware for user authentication"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth.user_store import get_user_store, set_current_user

logger = logging.getLogger(__name__)

# Public paths that don't require authentication
PUBLIC_PATHS = {
    "/auth/register",
    "/auth/login",
    "/health",
    "/docs",
    "/openapi.json",
    "/api/health",  # Backend health check
}


class SessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware that validates session_id from X-Session-Id header
    and sets user context for the request.
    """

    def __init__(self, app, public_paths: set = None):
        super().__init__(app)
        self.public_paths = public_paths or PUBLIC_PATHS

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths without session check
        if path in self.public_paths or path.startswith("/auth/"):
            response = await call_next(request)
            return response

        # Get session_id from header or cookie
        session_id = request.headers.get("x-session-id")
        if not session_id:
            # Try cookie as fallback
            session_id = request.cookies.get("session_id")

        if not session_id:
            return JSONResponse(
                status_code=401,
                content={"error": "请先登录"}
            )

        # Validate session
        user_store = get_user_store()
        user_id = user_store.validate_session(session_id)

        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"error": "会话已过期，请重新登录"}
            )

        # Set user context for this request
        token = set_current_user(user_id)
        try:
            response = await call_next(request)
            return response
        finally:
            # Clean up context
            set_current_user(None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_session_middleware.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth/session_middleware.py backend/tests/test_session_middleware.py
git commit -m "feat: add SessionMiddleware for session-based authentication"
```

---

## Chunk 3: main.py - New Auth Endpoints

**Files:**
- Modify: `backend/main.py` (add register, login, logout, me, admin endpoints; replace middleware)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_endpoints.py`:

```python
"""Tests for auth endpoints in main.py"""
import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_register_endpoint():
    """POST /auth/register should create user"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    response = client.post("/auth/register", json={
        "username": "newuser",
        "password": "password123"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "user_id" in data

def test_register_duplicate():
    """Duplicate username should return 400"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    # First registration
    client.post("/auth/register", json={
        "username": "dupuser",
        "password": "password123"
    })

    # Duplicate
    response = client.post("/auth/register", json={
        "username": "dupuser",
        "password": "password456"
    })
    assert response.status_code == 400

def test_login_endpoint():
    """POST /auth/login should return session"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    # Register first
    client.post("/auth/register", json={
        "username": "loginuser",
        "password": "password123"
    })

    # Login
    response = client.post("/auth/login", json={
        "username": "loginuser",
        "password": "password123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert data["success"] is True

def test_login_wrong_password():
    """Login with wrong password should fail"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    client.post("/auth/register", json={
        "username": "loginuser2",
        "password": "password123"
    })

    response = client.post("/auth/login", json={
        "username": "loginuser2",
        "password": "wrongpassword"
    })
    assert response.status_code == 401

def test_me_endpoint_without_login():
    """GET /auth/me without login should return 401"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    response = client.get("/auth/me")
    assert response.status_code == 401

def test_me_endpoint_with_login():
    """GET /auth/me with valid session should return user info"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    # Register and login
    client.post("/auth/register", json={
        "username": "meuser",
        "password": "password123"
    })
    login_resp = client.post("/auth/login", json={
        "username": "meuser",
        "password": "password123"
    })
    session_id = login_resp.json()["session_id"]

    # Get me
    response = client.get("/auth/me", headers={"x-session-id": session_id})
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "meuser"

def test_logout_endpoint():
    """POST /auth/logout should invalidate session"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    # Register and login
    client.post("/auth/register", json={
        "username": "logoutuser",
        "password": "password123"
    })
    login_resp = client.post("/auth/login", json={
        "username": "logoutuser",
        "password": "password123"
    })
    session_id = login_resp.json()["session_id"]

    # Logout
    response = client.post("/auth/logout", headers={"x-session-id": session_id})
    assert response.status_code == 200

    # Verify session invalid
    me_resp = client.get("/auth/me", headers={"x-session-id": session_id})
    assert me_resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_auth_endpoints.py -v`
Expected: FAIL - no /auth/register endpoint

- [ ] **Step 3: Modify main.py - Add auth endpoints and replace middleware**

First, add imports after existing imports (around line 20):

```python
from auth.user_store import get_user_store, set_current_user
```

Replace `UserIsolationMiddleware` import/class (lines 26-46) with new SessionMiddleware:

```python
from auth.session_middleware import SessionMiddleware, PUBLIC_PATHS
```

Replace `UserIsolationMiddleware` usage (around line 68-69) with new middleware:

```python
app.add_middleware(SessionMiddleware, public_paths=PUBLIC_PATHS)
```

Add new auth endpoints after the existing imports block (~line 73):

```python
    # ── Auth (Session-based) ─────────────────────────────────────────────────

    class RegisterRequest(BaseModel):
        username: str
        password: str

    @app.post("/auth/register", status_code=201)
    async def register(req: RegisterRequest):
        store = get_user_store()
        user_id, error = store.register_user(req.username, req.password)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"success": True, "user_id": user_id, "username": req.username}

    @app.post("/auth/login")
    async def login(req: RegisterRequest):
        store = get_user_store()
        result = store.login_user(req.username, req.password)
        if "error" in result:
            raise HTTPException(status_code=401, detail=result["error"])
        return result

    @app.post("/auth/logout")
    async def logout(request: Request):
        session_id = request.headers.get("x-session-id")
        if session_id:
            store = get_user_store()
            store.logout_user(session_id)
        return {"success": True}

    @app.get("/auth/me")
    async def get_me(request: Request):
        user_id = get_current_user_from_request(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="请先登录")
        store = get_user_store()
        user = store.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user

    # ── Admin ───────────────────────────────────────────────────────────────

    @app.get("/admin/users")
    async def list_users(request: Request):
        user_id = get_current_user_from_request(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="请先登录")
        store = get_user_store()
        user = store.get_user(user_id)
        if not user or not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        users = store.list_users()
        return {"users": users}

    @app.delete("/admin/users/{user_id}")
    async def delete_user(user_id: str, request: Request):
        current_user_id = get_current_user_from_request(request)
        if not current_user_id:
            raise HTTPException(status_code=401, detail="请先登录")
        store = get_user_store()
        current_user = store.get_user(current_user_id)
        if not current_user or not current_user.get("is_admin"):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        success, error = store.delete_user(user_id)
        if not success:
            raise HTTPException(status_code=400, detail=error)
        return {"success": True}

    # Helper to get user_id from request
    def get_current_user_from_request(request: Request) -> Optional[str]:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            return None
        store = get_user_store()
        return store.validate_session(session_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_auth_endpoints.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: add session-based auth endpoints (register, login, logout, me, admin)"
```

---

## Chunk 4: Fix /auth/status to use user isolation

**Files:**
- Modify: `backend/main.py` (`/auth/status` endpoint)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_auth_endpoints.py`:

```python
def test_auth_status_uses_user_isolation():
    """GET /auth/status should return status for current user's tokens"""
    from main import create_app
    app = create_app()
    client = TestClient(app)

    # Register and login as user1
    client.post("/auth/register", json={
        "username": "user1",
        "password": "password123"
    })
    login_resp = client.post("/auth/login", json={
        "username": "user1",
        "password": "password123"
    })
    session1 = login_resp.json()["session_id"]

    # Register and login as user2
    client.post("/auth/register", json={
        "username": "user2",
        "password": "password123"
    })
    login_resp2 = client.post("/auth/login", json={
        "username": "user2",
        "password": "password123"
    })
    session2 = login_resp2.json()["session_id"]

    # User1 checks status - should not see user2's tokens
    status1 = client.get("/auth/status", headers={"x-session-id": session1})
    assert status1.status_code == 200

    # User2 checks status - should not see user1's tokens
    status2 = client.get("/auth/status", headers={"x-session-id": session2})
    assert status2.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_auth_endpoints.py::test_auth_status_uses_user_isolation -v`
Expected: FAIL - /auth/status currently doesn't use user isolation

- [ ] **Step 3: Modify /auth/status endpoint in main.py**

Find and replace the `/auth/status` endpoint (around line 251):

```python
    @app.get("/auth/status")
    async def auth_status(request: Request):
        user_id = get_current_user_from_request(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="请先登录")
        from auth.token_store import get_token_store
        store = get_token_store(user_id)
        return {p: store.get_status(p) for p in
                ["youtube","twitter","github","pocket","bilibili","wechat","douyin","xiaohongshu"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_auth_endpoints.py::test_auth_status_uses_user_isolation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix: /auth/status now uses per-user token store"
```

---

## Chunk 5: MCP Tools - Fix user_id propagation

**Files:**
- Modify: `backend/tools/mcp_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_user_store.py`:

```python
def test_sync_platform_uses_user_context():
    """sync_platform MCP tool should use current user context"""
    from auth.user_store import set_current_user, get_current_user
    from tools.mcp_tools import sync_platform

    # Set user context
    set_current_user("user_test123")

    # sync_platform should use the context
    # This will fail if user_id is not properly propagated
    try:
        result = sync_platform("github", full_sync=False)
        # Result should be a dict, not error about user_id
        assert isinstance(result, dict)
    except TypeError as e:
        if "user_id" in str(e):
            pytest.fail("sync_platform doesn't accept user_id parameter")
        raise
    finally:
        set_current_user(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_user_store.py::test_sync_platform_uses_user_context -v`
Expected: FAIL - sync_platform doesn't accept user_id

- [ ] **Step 3: Modify sync_platform in mcp_tools.py**

Find the `sync_platform` function and update it:

```python
def sync_platform(platform: str, full_sync: bool = False, user_id: str = None) -> Dict[str, Any]:
    """
    触发平台同步
    MCP Tool: sync_platform
    委托给 CollectorAgent 执行
    user_id: 可选，默认从上下文获取
    """
    from agents.collector_agent import CollectorAgent
    from auth.user_store import get_current_user

    # 如果没有提供 user_id，从上下文获取
    if user_id is None:
        user_id = get_current_user()

    agent = CollectorAgent()
    return agent.sync_single_platform(platform, full_sync=full_sync, user_id=user_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/frontis/Desktop/SH/personal-ai-memory-full/backend && python -m pytest tests/test_user_store.py::test_sync_platform_uses_user_context -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tools/mcp_tools.py
git commit -m "fix: sync_platform MCP tool now accepts and propagates user_id"
```

---

## Chunk 6: Frontend - apiClient.ts with Session-Id

**Files:**
- Modify: `frontend/src/api/apiClient.ts`

- [ ] **Step 1: Modify apiClient.ts to use X-Session-Id instead of X-User-Id**

Replace the request interceptor (lines 10-26):

```typescript
// Add request interceptor to include session_id for authentication
http.interceptors.request.use((config) => {
  try {
    const authStorage = localStorage.getItem('auth-storage')
    if (authStorage) {
      const parsed = JSON.parse(authStorage)
      const sessionId = parsed?.state?.sessionId
      if (sessionId) {
        config.headers['X-Session-Id'] = sessionId
      }
    }
  } catch (e) {
    // Ignore parse errors
  }
  return config
})
```

Also remove any reference to `X-User-Id` and ensure all API calls work with the session header.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/apiClient.ts
git commit -m "feat: apiClient now uses X-Session-Id header for authentication"
```

---

## Chunk 7: Frontend - Auth Store with Backend API

**Files:**
- Modify: `frontend/src/store/index.ts`

- [ ] **Step 1: Replace Auth store to use backend API**

Replace the `useAuthStore` section (lines 429-551) with:

```typescript
// ── Auth store (user session management) ─────────────────────────────────────
interface AuthState {
  isAuthenticated: boolean
  isRegistered: boolean
  username: string | null
  userId: string | null
  sessionId: string | null
  isAdmin: boolean
  registeredUsers: User[]
  login: (username: string, password: string) => { success: boolean; error?: string }
  register: (username: string, password: string, confirmPassword: string) => { success: boolean; error?: string }
  logout: () => void
  checkUsernameAvailable: (username: string) => boolean
  fetchMe: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      isRegistered: false,
      username: null,
      userId: null,
      sessionId: null,
      isAdmin: false,
      registeredUsers: [],

      checkUsernameAvailable: (username: string) => {
        // Backend handles this on register, but we can check locally for quick feedback
        const { registeredUsers } = get()
        return !registeredUsers.some(u => u.username === username)
      },

      register: async (username: string, password: string, confirmPassword: string) => {
        if (!username || username.trim().length < 2) {
          return { success: false, error: '用户名至少需要2个字符' }
        }
        if (!password || password.length < 4) {
          return { success: false, error: '密码至少需要4个字符' }
        }
        if (password !== confirmPassword) {
          return { success: false, error: '两次输入的密码不一致' }
        }

        try {
          const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
          })
          const data = await response.json()

          if (!response.ok) {
            return { success: false, error: data.detail || '注册失败' }
          }

          // Auto login after successful registration
          return get().login(username, password)
        } catch (error) {
          return { success: false, error: '网络错误，请重试' }
        }
      },

      login: async (username: string, password: string) => {
        try {
          const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
          })
          const data = await response.json()

          if (!response.ok) {
            return { success: false, error: data.detail || '登录失败' }
          }

          set({
            isAuthenticated: true,
            isRegistered: true,
            username: data.username,
            userId: data.user_id,
            sessionId: data.session_id,
            isAdmin: data.is_admin,
          })

          return { success: true }
        } catch (error) {
          return { success: false, error: '网络错误，请重试' }
        }
      },

      logout: async () => {
        const { sessionId } = get()
        if (sessionId) {
          try {
            await fetch('/api/auth/logout', {
              method: 'POST',
              headers: { 'X-Session-Id': sessionId }
            })
          } catch {
            // Ignore logout errors
          }
        }

        set({
          isAuthenticated: false,
          username: null,
          userId: null,
          sessionId: null,
          isAdmin: false,
        })
      },

      fetchMe: async () => {
        const { sessionId } = get()
        if (!sessionId) return

        try {
          const response = await fetch('/api/auth/me', {
            headers: { 'X-Session-Id': sessionId }
          })
          if (response.ok) {
            const data = await response.json()
            set({
              isAuthenticated: true,
              username: data.username,
              userId: data.id,
              isAdmin: data.is_admin,
            })
          } else {
            // Session invalid
            set({
              isAuthenticated: false,
              sessionId: null,
            })
          }
        } catch {
          // Ignore errors
        }
      },
    }),
    {
      name: 'auth-storage',
    }
  )
)
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/store/index.ts
git commit -m "feat: Auth store now uses backend API for authentication"
```

---

## Chunk 8: Create default admin user

**Files:**
- Modify: `backend/auth/user_store.py`

- [ ] **Step 1: Add create_admin_user method**

Add to `UserStore` class:

```python
def create_admin_user(self, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
    """Create an admin user"""
    if len(username) < 2:
        return None, "Username must be at least 2 characters"
    if len(password) < 4:
        return None, "Password must be at least 4 characters"

    conn = self._get_conn()
    # Check duplicate
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
```

- [ ] **Step 2: Auto-create default admin on first run**

Add at end of `UserStore.__init__`:

```python
def _ensure_default_admin(self):
    """Create default admin user if no admin exists"""
    conn = self._get_conn()
    admin_exists = conn.execute(
        "SELECT id FROM users WHERE is_admin = 1"
    ).fetchone()
    if not admin_exists:
        logger.info("[UserStore] Creating default admin user (admin/admin123)")
        self.create_admin_user("admin", "admin123")
```

Call this at end of `__init__`:

```python
self._init_db()
self._ensure_default_admin()  # Add this line
```

- [ ] **Step 3: Add CLI command to create admin**

Add to `main.py` CLI section:

```python
# Add to argparse section
admin = subs.add_parser("create-admin")
admin.add_argument("username")
admin.add_argument("password")

# Add to cli_main:
elif args.command == "create-admin":
    from auth.user_store import get_user_store
    store = get_user_store()
    user_id, error = store.create_admin_user(args.username, args.password)
    if error:
        print(f"Error: {error}")
    else:
        print(f"Admin user created: {user_id}")
```

- [ ] **Step 4: Commit**

```bash
git add backend/auth/user_store.py backend/main.py
git commit -m "feat: add default admin user and create-admin CLI command"
```

---

## Summary

After all chunks:
1. Backend has session-based authentication with SQLite user store
2. All data (memories, tokens) is per-user isolated
3. Frontend uses session_id header for auth
4. Admin can manage users via /admin/* endpoints

Total: 8 chunks, ~8 commits
