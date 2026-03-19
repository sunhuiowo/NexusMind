# User Isolation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement complete multi-tenant user isolation where `user_id` is mandatory on every data operation, with super admin impersonation via audited tokens.

**Architecture:** Data-layer first approach — schema changes, then auth/impersonation, then fix all components to pass `user_id` explicitly, finally admin API.

**Tech Stack:** FastAPI, SQLite, FAISS, Python threading

---

## Architecture Summary

```
HTTP Request
  → X-Session-Id header
  → SessionMiddleware validates, sets request.state.user_id
  → If X-Impersonation-Token present → resolve to target_user_id
  → All layers receive explicit user_id (NOT ContextVar)
  → MemoryStore / TokenStore / Agents all require user_id
```

**Key principle**: No ContextVar fallback. `user_id=None` → error, not default.

---

## File Overview

| File | Role |
|------|------|
| `backend/memory/memory_schema.py` | Add `user_id` field to `Memory` dataclass |
| `backend/memory/memory_store.py` | Add `user_id` column to SQLite, remove ContextVar fallback |
| `backend/auth/token_store.py` | Remove ContextVar fallback from `get_token_store` |
| `backend/auth/user_store.py` | Add cascade delete, impersonation tables |
| `backend/auth/session_middleware.py` | Add impersonation token handling |
| `backend/auth/impersonation.py` | NEW: impersonation token CRUD |
| `backend/auth/oauth_handler.py` | Fix: encode user_id in state, remove global singleton |
| `backend/agents/collector_agent.py` | Fix: pass user_id to get_token_store |
| `backend/agents/memory_agent.py` | Fix: require user_id in constructor |
| `backend/agents/knowledge_agent.py` | Fix: require user_id in all methods |
| `backend/tools/mcp_tools.py` | Fix: add user_id param to all functions |
| `backend/main.py` | Add admin endpoints, wire impersonation |
| `backend/routers/admin.py` | NEW: admin user management endpoints |
| `backend/db/migrations/` | NEW: migration scripts for schema changes |

---

## Chunk 1: Data Layer — Schema & Migrations

### Task 1: Add `user_id` to Memory dataclass

**Files:**
- Modify: `backend/memory/memory_schema.py:49-108`

- [ ] **Step 1: Read current Memory dataclass**

Run: `cat backend/memory/memory_schema.py | head -120`
Confirm: dataclass starts at line 49 with `class Memory:`

- [ ] **Step 2: Add `user_id` field to Memory dataclass**

Add after line 50 (`created_at` field):
```python
    # ── 所有者 ────────────────────────────────────────────────────────────────
    user_id: str = ""           # 所属用户 ID，强制字段
```

- [ ] **Step 3: Commit**

```bash
git add backend/memory/memory_schema.py
git commit -m "feat(schema): add user_id field to Memory dataclass"
```

---

### Task 2: Update _memory_to_params to include user_id

**Files:**
- Modify: `backend/memory/memory_store.py:131-153`

- [ ] **Step 1: Read _memory_to_params method**

Run: `sed -n '131,153p' backend/memory/memory_store.py`

- [ ] **Step 2: Update _memory_to_params to add user_id as first param**

Change the tuple to include `memory.user_id` as the first value:

```python
    def _memory_to_params(self, memory: Memory, faiss_pos: int = -1) -> tuple:
        return (
            memory.user_id,  # NEW: first position
            memory.id,
            memory.created_at,
            # ... rest unchanged
        )
```

- [ ] **Step 3: Update INSERT statement to include user_id**

Run: `sed -n '239,245p' backend/memory/memory_store.py`
Update INSERT to include `user_id` column:

```python
            conn.execute("""
                INSERT INTO memories (user_id, id, created_at, platform, platform_name,
                    platform_id, source_url, author, bookmarked_at, title, summary,
                    raw_content, tags, media_type, thumbnail_url, importance,
                    query_count, last_accessed_at, related_ids, parent_id, faiss_pos)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, self._memory_to_params(memory, faiss_pos))
```

- [ ] **Step 4: Update CREATE TABLE statement**

Find the CREATE TABLE in `memory_store.py` and add `user_id TEXT NOT NULL` as first column.

- [ ] **Step 5: Update all SELECT queries to filter by user_id**

Search for all `SELECT` statements and ensure they have `WHERE user_id = ?` with the user_id parameter bound.

- [ ] **Step 6: Commit**

```bash
git add backend/memory/memory_store.py
git commit -m "feat(schema): add user_id to memories table and all queries"
```

---

### Task 3: Create migration script for existing data

**Files:**
- Create: `backend/db/migrations/001_add_user_id.py`

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""
Migration 001: Add user_id to memories table
Backfills existing memories with the owner user_id based on storage path.
"""
import sys
import re
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from memory.memory_store import get_memory_store, _get_db_conn
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_memories_table(user_id: str = None):
    """
    Add user_id column to memories table if it doesn't exist.
    For existing data, we need to know which user owns each memory.
    Since old data used _default, we migrate it to the first registered user
    or a specified user_id.
    """
    db_path = str(Path(__file__).parent.parent.parent / "data" / "memories.db")

    # Check if column already exists
    conn = _get_db_conn(db_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
    logger.info(f"Current columns: {columns}")

    if "user_id" in columns:
        logger.info("user_id column already exists, skipping")
        return

    # Add the column
    conn.execute("ALTER TABLE memories ADD COLUMN user_id TEXT NOT NULL DEFAULT '_default'")
    conn.commit()
    logger.info("Added user_id column to memories table")

    # Update all NULL/empty user_id to _default for safety
    conn.execute("UPDATE memories SET user_id = '_default' WHERE user_id IS NULL OR user_id = ''")
    conn.commit()
    logger.info("Backfilled user_id values")

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else "_default"
    migrate_memories_table(user_id)
    print(f"Migration complete. Existing memories assigned to user: {user_id}")
```

- [ ] **Step 2: Create db/migrations directory and __init__.py**

```bash
mkdir -p backend/db/migrations
touch backend/db/migrations/__init__.py
```

- [ ] **Step 3: Run migration**

Run: `cd backend && python db/migrations/001_add_user_id.py _default`
Expected: "Migration complete. Existing memories assigned to user: _default"

- [ ] **Step 4: Commit**

```bash
git add backend/db/migrations/
git commit -m "feat(migration): add user_id column migration script"
```

---

## Chunk 2: Auth Layer — Impersonation & Session Middleware

### Task 4: Create impersonation.py

**Files:**
- Create: `backend/auth/impersonation.py`

- [ ] **Step 1: Write impersonation.py**

```python
"""Impersonation token management for admin users"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
import logging

from auth.user_store import get_user_store
from db.db_utils import _get_db_conn

logger = logging.getLogger(__name__)

IMPERSONATION_EXPIRY_HOURS = 8  # Admin impersonation expires after 8 hours


def create_impersonation_token(admin_user_id: str, target_user_id: str) -> Tuple[str, str]:
    """
    Create an impersonation token for an admin to act as target_user.

    Returns: (token_id, error_or_none)
    """
    conn = _get_db_conn()

    # Verify admin is actually an admin
    user_store = get_user_store()
    admin = conn.execute("SELECT is_admin FROM users WHERE id = ?", (admin_user_id,)).fetchone()
    if not admin or not admin[0]:
        return "", "Not authorized to impersonate"

    # Verify target user exists
    target = conn.execute("SELECT id FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        return "", "Target user not found"

    # Cannot impersonate another admin
    if target[0] if len(target) > 0 else False:
        return "", "Cannot impersonate another admin"

    token_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=IMPERSONATION_EXPIRY_HOURS)).isoformat()

    conn.execute("""
        INSERT INTO impersonation_tokens (id, admin_user_id, target_user_id, created_at, expires_at, audit_log)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (token_id, admin_user_id, target_user_id, created_at, expires_at, json.dumps([])))

    # Log the impersonation start
    conn.execute("""
        INSERT INTO admin_audit_logs (id, admin_user_id, action, target_user_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), admin_user_id, "impersonate_start", target_user_id,
          json.dumps({"token_id": token_id}), created_at))
    conn.commit()

    logger.info(f"[Impersonation] Admin {admin_user_id} started impersonating {target_user_id}")
    return token_id, None


def validate_impersonation_token(token_id: str) -> Optional[Dict[str, str]]:
    """
    Validate an impersonation token and return the mapping if valid.

    Returns: {admin_user_id, target_user_id} or None if invalid/expired
    """
    conn = _get_db_conn()

    row = conn.execute("""
        SELECT admin_user_id, target_user_id, expires_at
        FROM impersonation_tokens
        WHERE id = ?
    """, (token_id,)).fetchone()

    if not row:
        return None

    admin_user_id, target_user_id, expires_at = row

    # Check expiry
    expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_dt:
        return None

    return {"admin_user_id": admin_user_id, "target_user_id": target_user_id}


def revoke_impersonation_token(token_id: str, admin_user_id: str) -> Tuple[bool, str]:
    """
    Revoke an impersonation token (admin ends their impersonation session).
    """
    conn = _get_db_conn()

    token = conn.execute("""
        SELECT admin_user_id, target_user_id FROM impersonation_tokens WHERE id = ?
    """, (token_id,)).fetchone()

    if not token:
        return False, "Token not found"

    if token[0] != admin_user_id:
        return False, "Not authorized to revoke this token"

    conn.execute("DELETE FROM impersonation_tokens WHERE id = ?", (token_id,))

    # Log the impersonation end
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
    conn = _get_db_conn()

    row = conn.execute("SELECT audit_log FROM impersonation_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        return

    audit_log = json.loads(row[0] or "[]")
    audit_log.append({**action, "timestamp": datetime.now(timezone.utc).isoformat()})

    conn.execute("UPDATE impersonation_tokens SET audit_log = ? WHERE id = ?",
                  (json.dumps(audit_log), token_id))
    conn.commit()
```

- [ ] **Step 2: Add impersonation_tables to db setup**

In `backend/db/db_utils.py` (or wherever the users.db schema is initialized), add the new tables:

```python
# In the init function that creates users.db
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
```

- [ ] **Step 3: Commit**

```bash
git add backend/auth/impersonation.py
# Also commit the db_utils changes
git add backend/db/
git commit -m "feat(auth): add impersonation token management"
```

---

### Task 5: Update session_middleware to handle impersonation

**Files:**
- Modify: `backend/auth/session_middleware.py`

- [ ] **Step 1: Read current middleware**

Run: `cat backend/auth/session_middleware.py`

- [ ] **Step 2: Update dispatch method to handle impersonation**

The key changes:
1. Check for `X-Impersonation-Token` header after validating session
2. If present, validate token and set `request.state.target_user_id` as the effective user_id
3. Set `request.state.is_impersonating = True`
4. Add `X-Impersonation-Token` to public paths (for admin endpoints that need it)

```python
async def dispatch(self, request: Request, call_next):
    path = request.url.path

    # Allow public paths without session check
    if path in self.public_paths:
        response = await call_next(request)
        return response

    # Get session_id from header or cookie
    session_id = request.headers.get("x-session-id")
    if not session_id:
        session_id = request.cookies.get("session_id")

    if not session_id:
        return JSONResponse(status_code=401, content={"error": "请先登录"})

    # Validate session
    user_store = get_user_store()
    session_data = user_store.validate_session_with_data(session_id)

    if not session_data:
        return JSONResponse(status_code=401, content={"error": "会话已过期，请重新登录"})

    user_id = session_data["user_id"]
    is_admin = session_data.get("is_admin", False)

    # Set base user context
    set_current_user(user_id)
    request.state.user_id = user_id
    request.state.is_admin = is_admin
    request.state.is_impersonating = False
    request.state.admin_user_id = None

    # Check for impersonation token (admins only)
    impersonation_token = request.headers.get("x-impersonation-token")
    if impersonation_token and is_admin:
        from auth.impersonation import validate_impersonation_token
        token_data = validate_impersonation_token(impersonation_token)
        if token_data and token_data["admin_user_id"] == user_id:
            # Impersonation is valid - use target user as effective user_id
            request.state.user_id = token_data["target_user_id"]
            request.state.is_impersonating = True
            request.state.admin_user_id = user_id
            logger.info(f"[Middleware] Admin {user_id} impersonating {token_data['target_user_id']}")
        else:
            return JSONResponse(status_code=403, content={"error": "Invalid or expired impersonation token"})

    try:
        response = await call_next(request)
        return response
    finally:
        set_current_user(None)
```

- [ ] **Step 3: Update user_store.validate_session to return is_admin**

Add a `validate_session_with_data` method or modify `validate_session` to return full session data.

- [ ] **Step 4: Commit**

```bash
git add backend/auth/session_middleware.py backend/auth/user_store.py
git commit -m "feat(auth): add impersonation token handling to session middleware"
```

---

### Task 6: Fix OAuthHandler — encode user_id in state, remove global singleton

**Files:**
- Modify: `backend/auth/oauth_handler.py`

- [ ] **Step 1: Read get_auth_url and handle_callback**

Run: `sed -n '80,160p' backend/auth/oauth_handler.py`

- [ ] **Step 2: Update get_auth_url to accept and encode user_id**

```python
    def get_auth_url(self, platform: str, user_id: str) -> Tuple[str, str]:
        """
        生成平台授权 URL
        返回 (auth_url, state)

        state 包含 platform, code_verifier, user_id
        """
        cfg = PLATFORM_OAUTH_CONFIGS.get(platform)
        if not cfg:
            return "", ""

        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)

        # Encode user_id in state so callback can route tokens correctly
        state = json.dumps({
            "platform": platform,
            "code_verifier": code_verifier,
            "user_id": user_id  # NEW
        })

        callback_url = urljoin(
            config.OAUTH_CALLBACK_BASE,
            f"{config.OAUTH_CALLBACK_PATH}/{platform}"
        )

        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": cfg.get("scope", ""),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }

        auth_url = f"{cfg['auth_url']}?{urlencode(params)}"
        return auth_url, state
```

- [ ] **Step 3: Update handle_callback to decode user_id from state**

```python
    def handle_callback(self, platform: str, code: str, state: str) -> bool:
        """
        处理 OAuth 回调，用 code 换取 tokens
        返回是否成功
        """
        try:
            state_data = json.loads(state)
        except json.JSONDecodeError:
            print(f"[OAuth] state 解析失败: {state}")
            return False

        pending = self._pending_states.pop(state_data.get("code_verifier", ""), None)
        if not pending or pending["platform"] != platform:
            print(f"[OAuth] state 无效或已过期")
            return False

        # Extract user_id from state
        user_id = state_data.get("user_id", "_default")

        cfg = PLATFORM_OAUTH_CONFIGS.get(platform)
        if not cfg:
            return False

        callback_url = urljoin(
            config.OAUTH_CALLBACK_BASE,
            f"{config.OAUTH_CALLBACK_PATH}/{platform}"
        )

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }

        if "code_verifier" in state_data:
            data["code_verifier"] = state_data["code_verifier"]

        try:
            headers = {"Accept": "application/json"}
            resp = requests.post(cfg["token_url"], data=data, headers=headers, timeout=30)
            resp.raise_for_status()
            token_json = resp.json()
        except Exception as e:
            print(f"[OAuth] {platform} token 换取失败: {e}")
            return False

        # Save to the correct user's token store
        return self._save_token_response(platform, token_json, cfg, user_id)

    def _save_token_response(self, platform: str, token_json: dict, cfg: dict, user_id: str) -> bool:
        """Save token response to the correct user's token store."""
        from auth.token_store import get_token_store

        token_store = get_token_store(user_id)  # Always pass user_id

        # ... rest of the existing token saving logic
```

- [ ] **Step 4: Remove global singleton**

Delete lines 246-253 (the `get_oauth_handler()` function and `_oauth_handler` global).

- [ ] **Step 5: Update all callers of get_oauth_handler() / get_auth_url()**

Search for all callers:
```bash
grep -rn "get_oauth_handler\|get_auth_url\|handle_callback" backend/ --include="*.py"
```

Update each to instantiate OAuthHandler directly with user_id.

- [ ] **Step 6: Commit**

```bash
git add backend/auth/oauth_handler.py
git commit -m "fix(oauth): encode user_id in state, remove global singleton"
```

---

## Chunk 3: Store Functions — Remove ContextVar Fallback

### Task 7: Fix get_memory_store — require explicit user_id

**Files:**
- Modify: `backend/memory/memory_store.py:627-663`

- [ ] **Step 1: Read current get_memory_store**

Run: `sed -n '627,663p' backend/memory/memory_store.py`

- [ ] **Step 2: Remove ContextVar fallback, require explicit user_id**

Change `user_id: str = None` to `user_id: str` (no default). If called without user_id, it should raise an error:

```python
def get_memory_store(user_id: str) -> MemoryStore:
    """
    获取指定用户的 MemoryStore 实例
    user_id is REQUIRED - no default, no ContextVar fallback.
    If user_id is missing, raise ValueError.
    """
    global _stores

    if not user_id:
        raise ValueError("get_memory_store() requires explicit user_id. "
                        "Use request.state.user_id from SessionMiddleware.")

    # If the user's MemoryStore instance doesn't exist, create it
    if user_id not in _stores:
        user_db_path = str(config.DATA_DIR / f"memories_{user_id}.db")
        user_faiss_path = str(config.VECTOR_DIR / user_id / "index.faiss")

        Path(user_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(user_faiss_path).parent.mkdir(parents=True, exist_ok=True)

        _stores[user_id] = MemoryStore(
            faiss_path=user_faiss_path,
            db_path=user_db_path,
        )
        logger.info(f"Created new MemoryStore for user: {user_id}, db_path: {user_db_path}")

    return _stores[user_id]
```

- [ ] **Step 3: Also update _get_db_conn to track connection per db_path**

The existing thread-local connection tracking at lines 14-27 should be verified to work correctly. Read it.

- [ ] **Step 4: Commit**

```bash
git add backend/memory/memory_store.py
git commit -m "fix(store): require explicit user_id in get_memory_store, remove ContextVar fallback"
```

---

### Task 8: Fix get_token_store — require explicit user_id

**Files:**
- Modify: `backend/auth/token_store.py:245-265`

- [ ] **Step 1: Read get_token_store**

Run: `sed -n '245,265p' backend/auth/token_store.py`

- [ ] **Step 2: Remove ContextVar fallback, require explicit user_id**

```python
def get_token_store(user_id: str) -> TokenStore:
    """
    获取指定用户的 TokenStore 实例
    user_id is REQUIRED - no default, no ContextVar fallback.
    """
    global _token_stores

    if not user_id:
        raise ValueError("get_token_store() requires explicit user_id")

    if user_id not in _token_stores:
        _token_stores[user_id] = TokenStore(user_id=user_id)
        logger.info(f"Created new TokenStore for user: {user_id}")

    return _token_stores[user_id]
```

- [ ] **Step 3: Commit**

```bash
git add backend/auth/token_store.py
git commit -m "fix(store): require explicit user_id in get_token_store, remove ContextVar fallback"
```

---

## Chunk 4: Agents & MCP Tools — Pass user_id Everywhere

### Task 9: Fix CollectorAgent — pass user_id to get_token_store

**Files:**
- Modify: `backend/agents/collector_agent.py:78-93`

- [ ] **Step 1: Read the bilibili token loading section**

Run: `sed -n '76,99p' backend/agents/collector_agent.py`

- [ ] **Step 2: The sync_platform method must receive user_id**

Check the method signature of `sync_platform`. It should already have `user_id` parameter from the design doc. Verify:
```bash
grep -n "def sync_platform" backend/agents/collector_agent.py
```

- [ ] **Step 3: Fix token_store call to pass user_id**

Change:
```python
token_store = get_token_store()  # NO user_id - WRONG
```
To:
```python
token_store = get_token_store(user_id)  # Always pass user_id
```

- [ ] **Step 4: Verify all other get_token_store calls in collector_agent**

Search for all `get_token_store()` calls:
```bash
grep -n "get_token_store" backend/agents/collector_agent.py
```

Fix any that don't pass `user_id`.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/collector_agent.py
git commit -m "fix(collector): pass user_id to get_token_store"
```

---

### Task 10: Fix MemoryAgent — accept user_id, fix background tasks

**Files:**
- Modify: `backend/agents/memory_agent.py`

- [ ] **Step 1: Read __init__ and start_background**

Run: `sed -n '35,45p' backend/agents/memory_agent.py`
Run: `sed -n '176,195p' backend/agents/memory_agent.py`

- [ ] **Step 2: Update __init__ to require user_id**

```python
    def __init__(self, user_id: str):
        if not user_id:
            raise ValueError("MemoryAgent requires user_id")
        self._user_id = user_id
        self._store = get_memory_store(user_id)  # Pass user_id
        self._llm = get_llm_client()
        self._embedder = get_embedder()
        self._updater = ImportanceUpdater(self._store, llm_func=self._llm)
        self._running = False
        self._thread: Optional[threading.Thread] = None
```

- [ ] **Step 3: Background tasks**

For background tasks, we need per-user agent instances. The approach:
- Don't start global background tasks in MemoryAgent
- Instead, the SessionMiddleware or a login handler starts per-user background agents
- Store agents in a dict: `_user_agents[user_id] = MemoryAgent(user_id)`

Update `start_background` to be per-user, and add a class-level registry:

```python
# At module level
_user_agents: Dict[str, MemoryAgent] = {}

def get_memory_agent(user_id: str) -> MemoryAgent:
    """Get or create a MemoryAgent for the specified user."""
    if user_id not in _user_agents:
        _user_agents[user_id] = MemoryAgent(user_id)
    return _user_agents[user_id]
```

- [ ] **Step 3: Commit**

```bash
git add backend/agents/memory_agent.py
git commit -m "fix(memory_agent): require user_id in constructor, add per-user agent registry"
```

---

### Task 11: Fix KnowledgeAgent — require user_id

**Files:**
- Modify: `backend/agents/knowledge_agent.py`

- [ ] **Step 1: Check KnowledgeAgent init and methods**

Run: `grep -n "def __init__\|def query\|def answer" backend/agents/knowledge_agent.py | head -20`

- [ ] **Step 2: Update all methods to accept and pass user_id**

Every public method should accept `user_id: str` parameter and pass it to `get_memory_store(user_id)` and `get_token_store(user_id)`.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/knowledge_agent.py
git commit -m "fix(knowledge_agent): require user_id in all methods"
```

---

### Task 12: Fix all MCP tools — add user_id parameter

**Files:**
- Modify: `backend/tools/mcp_tools.py` (10+ locations)

- [ ] **Step 1: List all functions that call get_memory_store()**

From the exploration: lines 45, 95, 126, 167, 234, 253, 289, 322, 352, 364

- [ ] **Step 2: Add user_id parameter to each function**

Each function signature changes from:
```python
def search_memory(query: str, platform_filter: str = None) -> QueryResult:
```

To:
```python
def search_memory(query: str, user_id: str, platform_filter: str = None) -> QueryResult:
```

And the call changes from:
```python
store = get_memory_store()
```

To:
```python
store = get_memory_store(user_id)
```

Apply this to ALL 10 functions. The `user_id` parameter should be required (no default).

- [ ] **Step 3: Verify the @tool decorator can handle the new signature**

Check if the MCP framework (likely FastMCP or similar) handles `user_id` as a special parameter that gets injected from request context. If so, the tool functions need to accept `user_id` as an injected parameter.

- [ ] **Step 4: Commit**

```bash
git add backend/tools/mcp_tools.py
git commit -m "fix(mcp): add required user_id parameter to all tool functions"
```

---

## Chunk 5: API Endpoints — Admin Router

### Task 13: Create admin router

**Files:**
- Create: `backend/routers/admin.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create admin.py with all admin endpoints**

```python
"""Admin router for user management and impersonation"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid

from auth.user_store import get_user_store
from auth.impersonation import (
    create_impersonation_token,
    validate_impersonation_token,
    revoke_impersonation_token,
)
from db.db_utils import _get_db_conn
import json

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str
    password: str


class ImpersonateRequest(BaseModel):
    target_user_id: str


# ── User Management ──────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(request: Request):
    """List all users (admin only)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    conn = _get_db_conn()
    users = conn.execute("""
        SELECT id, username, is_admin, created_at FROM users ORDER BY created_at
    """).fetchall()

    return {"users": [{"id": u[0], "username": u[1], "is_admin": bool(u[2]), "created_at": u[3]} for u in users]}


@router.post("/users")
async def create_user(req: CreateUserRequest, request: Request):
    """Create a new user (admin only)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    user_store = get_user_store()
    user_id, error = user_store.register_user(req.username, req.password)

    if error:
        raise HTTPException(status_code=400, detail=error)

    # Log creation
    conn = _get_db_conn()
    conn.execute("""
        INSERT INTO admin_audit_logs (id, admin_user_id, action, target_user_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), request.state.user_id, "user_create", user_id,
          json.dumps({"username": req.username}), datetime.now().isoformat()))
    conn.commit()

    return {"success": True, "user_id": user_id, "username": req.username}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    """Delete a user and all their data (admin only, cannot delete self or other admins)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Check target is not an admin
    conn = _get_db_conn()
    target = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target[0]:
        raise HTTPException(status_code=400, detail="Cannot delete admin user")

    # Cascade delete via user_store (updated in Task 14)
    user_store = get_user_store()
    success, error = user_store.delete_user_cascade(user_id)

    if not success:
        raise HTTPException(status_code=400, detail=error)

    # Log deletion
    conn.execute("""
        INSERT INTO admin_audit_logs (id, admin_user_id, action, target_user_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), request.state.user_id, "user_delete", user_id,
          json.dumps({}), datetime.now().isoformat()))
    conn.commit()

    return {"success": True}


# ── Impersonation ───────────────────────────────────────────────────────────

@router.post("/impersonate/{target_user_id}")
async def impersonate_user(target_user_id: str, request: Request):
    """Start impersonating a user (admin only)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    token_id, error = create_impersonation_token(request.state.user_id, target_user_id)

    if error:
        raise HTTPException(status_code=400, detail=error)

    return {"success": True, "impersonation_token": token_id}


@router.delete("/impersonate")
async def end_impersonation(request: Request):
    """End current impersonation session"""
    token = request.headers.get("x-impersonation-token")
    if not token:
        raise HTTPException(status_code=400, detail="No impersonation token provided")

    success, error = revoke_impersonation_token(token, request.state.user_id)
    if not success:
        raise HTTPException(status_code=400, detail=error)

    return {"success": True}


# ── Audit Logs ───────────────────────────────────────────────────────────────

@router.get("/audit-logs")
async def get_audit_logs(request: Request, limit: int = 100):
    """Get admin audit logs (admin only)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    conn = _get_db_conn()
    logs = conn.execute("""
        SELECT id, admin_user_id, action, target_user_id, details, created_at
        FROM admin_audit_logs ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()

    return {"logs": [{"id": l[0], "admin_user_id": l[1], "action": l[2],
                      "target_user_id": l[3], "details": json.loads(l[4] or "{}"),
                      "created_at": l[5]} for l in logs]}
```

- [ ] **Step 2: Wire admin router into main.py**

In `backend/main.py`, add:
```python
from routers.admin import router as admin_router

app.include_router(admin_router)
```

Add after the auth endpoints section.

- [ ] **Step 3: Commit**

```bash
git add backend/routers/admin.py backend/main.py
git commit -m "feat(admin): add admin router with user management and impersonation"
```

---

### Task 14: Implement cascade delete in user_store

**Files:**
- Modify: `backend/auth/user_store.py`

- [ ] **Step 1: Read delete_user method**

Run: `sed -n '340,369p' backend/auth/user_store.py`

- [ ] **Step 2: Add delete_user_cascade method**

```python
    def delete_user_cascade(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """
        Delete user and ALL their data (cascade delete).
        Returns (success, error_message).
        """
        import shutil
        from pathlib import Path
        import config as cfg

        conn = _get_db_conn(self._db_path)

        # Check user exists and is not admin
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False, "User not found"
        if user[0]:
            return False, "Cannot delete admin user"

        # Delete sessions
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

        # Delete impersonation tokens (where admin or target)
        conn.execute("DELETE FROM impersonation_tokens WHERE admin_user_id = ? OR target_user_id = ?",
                     (user_id, user_id))

        # Delete user
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

        # Delete storage files
        data_dir = Path(cfg.DATA_DIR)

        # Delete memories DB
        mem_db = data_dir / f"memories_{user_id}.db"
        if mem_db.exists():
            mem_db.unlink()

        # Delete FAISS index directory
        faiss_dir = data_dir / "vectors" / user_id
        if faiss_dir.exists():
            shutil.rmtree(faiss_dir)

        # Delete auth tokens directory
        auth_dir = data_dir / "auth" / user_id
        if auth_dir.exists():
            shutil.rmtree(auth_dir)

        logger.info(f"[UserStore] Cascade deleted user: {user_id}")
        return True, None
```

- [ ] **Step 3: Also add update to delete_user to prevent self-delete of admin**

Update existing `delete_user` to also prevent deleting self:
```python
if user[0]:  # is_admin
    return False, "Cannot delete admin user"
```

- [ ] **Step 4: Commit**

```bash
git add backend/auth/user_store.py
git commit -m "feat(auth): add cascade delete for user data cleanup"
```

---

## Chunk 6: Verification & Integration

### Task 15: Update existing API endpoints to pass user_id

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Audit all route handlers in main.py**

Run: `grep -n "get_memory_store()\|get_token_store()" backend/main.py`

- [ ] **Step 2: Update each call to pass request.state.user_id**

Every `get_memory_store()` → `get_memory_store(request.state.user_id)`
Every `get_token_store()` → `get_token_store(request.state.user_id)`

- [ ] **Step 3: Also update CollectorAgent.sync_single_platform calls**

Verify that sync endpoints pass user_id correctly:
```bash
grep -n "sync_single_platform\|sync_platform\|CollectorAgent" backend/main.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "fix(api): pass user_id to all store and agent calls"
```

---

### Task 16: Final verification checklist

- [ ] Run: `grep -rn "get_memory_store()" backend/ --include="*.py" | grep -v user_id`
  - Should return ZERO results

- [ ] Run: `grep -rn "get_token_store()" backend/ --include="*.py" | grep -v "user_id"`
  - Should return ZERO results

- [ ] Run: `grep -rn "get_current_user()" backend/ --include="*.py"`
  - Should return ZERO results (ContextVar removed as fallback)

- [ ] Run: `grep -rn "_default" backend/ --include="*.py" | grep -v test`
  - Verify only in migration/initialization code

- [ ] Run backend tests:
  ```bash
  cd backend && pytest tests/ -v
  ```

- [ ] Start services and test:
  ```bash
  ./start.sh
  # Register two users
  # Login as user A, save a memory
  # Login as user B, verify cannot see user A's memory
  # Login as admin, impersonate user A
  # Verify admin can see user A's data
  # Delete user B, verify all storage cleaned up
  ```

---

## Dependencies Between Tasks

```
Chunk 1 (Data)          → must happen first
Chunk 2 (Auth/Impersonation) → depends on Chunk 1 tables
Chunk 3 (Store fixes)   → depends on Chunk 2 middleware
Chunk 4 (Agents/MCP)    → depends on Chunk 3
Chunk 5 (Admin API)     → depends on Chunk 2
Chunk 6 (Integration)  → depends on all previous
```

**Execute in order: Chunk 1 → 2 → 3 → 4 → 5 → 6**
