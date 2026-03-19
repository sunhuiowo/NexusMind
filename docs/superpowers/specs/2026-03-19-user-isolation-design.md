# Multi-Tenant User Isolation Design

**Date**: 2026-03-19
**Status**: Approved for implementation

---

## 1. Overview

**Goal**: Complete data isolation between users, with a super admin that can manage users and impersonate them via audited tokens.

**Core principle**: `user_id` must be present in every data operation. No `user_id` = no operation = error.

**Architecture**: RBAC + Multi-Tenant Isolation + Impersonation (auditable)

---

## 2. Data Model Changes

### 2.1 Schema Changes (SQLite)

All tables **must** have `user_id TEXT NOT NULL`. Tables to modify:

| Table | Change |
|-------|--------|
| `memories` | Add `user_id TEXT NOT NULL` field |
| `oauth_tokens` | Add explicit `user_id` column (storage path already per-user) |
| `platform_accounts` | Add `user_id TEXT NOT NULL` |
| `tasks` | Add `user_id TEXT NOT NULL` |
| `logs` | Add `user_id TEXT NOT NULL` |

### 2.2 New Tables

```sql
-- Users: is_admin=True for super admin
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Sessions (existing)
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Impersonation tokens for admin delegation
CREATE TABLE impersonation_tokens (
    id TEXT PRIMARY KEY,
    admin_user_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    audit_log TEXT,
    FOREIGN KEY (admin_user_id) REFERENCES users(id),
    FOREIGN KEY (target_user_id) REFERENCES users(id)
);

-- Audit log for admin actions
CREATE TABLE admin_audit_logs (
    id TEXT PRIMARY KEY,
    admin_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_user_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);
```

### 2.3 Storage Path Changes

Current: Per-user storage at path level (`memories_{user_id}.db`, `vectors/{user_id}/`)
After: User data stays in per-user paths, but **all data records also carry `user_id`** for query-level enforcement.

### 2.4 Migration Strategy

- Existing per-user files already have path-level isolation
- Migration script walks existing files and backfills `user_id` column
- Old data migrates to the user who owns that storage path
- `user_id=NULL` is never allowed

---

## 3. Request Lifecycle

### 3.1 Session Middleware

```
Request (X-Session-Id header OR session cookie)
→ Decode session_id from sessions table
→ Lookup user_id
→ Check impersonation_tokens for active impersonation (X-Impersonation-Token header)
→ Set request.state.user_id
→ Set request.state.is_impersonating (bool)
→ Set request.state.admin_user_id (if impersonating)
→ Proceed
```

### 3.2 Impersonation Flow

1. Admin calls `POST /admin/impersonate/{target_user_id}`
2. System creates `impersonation_tokens` record with expiry
3. Returns impersonation token to admin
4. Admin sends subsequent requests with `X-Impersonation-Token: {token}` header
5. Middleware detects impersonation token → uses `target_user_id` as `request.state.user_id`
6. All operations tagged with `admin_user_id` in audit log
7. Admin calls `DELETE /admin/impersonate` or token expires → impersonation ends

### 3.3 Authorization Rules

| Role | Can Do |
|------|--------|
| Regular user | Own data only (user_id enforced) |
| Admin | Manage users, impersonate, view audit logs |
| Impersonating admin | Target user's data, all actions logged |

### 3.4 No Implicit Fallback

**Critical rule**: `request.state.user_id` **must** be set. If missing → 401 Unauthorized. No fallback to "default" or "anonymous".

---

## 4. Component Changes

### 4.1 OAuthHandler (`backend/auth/oauth_handler.py`)

**Current bug**: Global singleton, uses default TokenStore
**Fix**: Accept `user_id` explicitly on each method call

```python
# Before (broken)
oauth_handler = get_oauth_handler()
oauth_handler.start_flow(platform, redirect_uri)

# After (fixed)
oauth_handler = OAuthHandler()  # No global singleton
oauth_handler.start_flow(platform, user_id, redirect_uri)
```

### 4.2 CollectorAgent (`backend/agents/collector_agent.py`)

**Current bug**: `get_token_store()` called without `user_id` for Bilibili
**Fix**: All methods require `user_id` parameter, passed explicitly

```python
# Before (broken)
token_store = get_token_store()
token_data = token_store.load("bilibili")

# After (fixed)
token_store = get_token_store(user_id)
token_data = token_store.load("bilibili")
```

### 4.3 MemoryAgent (`backend/agents/memory_agent.py`)

**Current bug**: Uses `get_memory_store()` without user_id (defaults to `_default`)
**Fix**: Accept `user_id` in constructor or per-method. For background tasks, spawn per-user agents.

### 4.4 MCP Tools (`backend/tools/mcp_tools.py`)

**Current bug**: Relies on ContextVar which may not propagate in background tasks
**Fix**: All tool functions accept explicit `user_id` parameter

```python
# Before (broken)
def search_memory(query: str) -> QueryResult:
    store = get_memory_store()

# After (fixed)
def search_memory(query: str, user_id: str) -> QueryResult:
    store = get_memory_store(user_id)
```

### 4.5 KnowledgeAgent (`backend/agents/knowledge_agent.py`)

**Fix**: All methods receive `user_id` explicitly, no implicit context lookup.

### 4.6 All API Endpoints

Every endpoint that reads/writes data must use `request.state.user_id`. No exceptions.

---

## 5. Admin Features

### 5.1 User Management Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/users` | GET | List all users |
| `/admin/users` | POST | Create new user |
| `/admin/users/{user_id}` | DELETE | Delete user + all their data |
| `/admin/impersonate/{user_id}` | POST | Start impersonation, returns token |
| `/admin/impersonate` | DELETE | End impersonation |
| `/admin/audit-logs` | GET | View audit logs |

### 5.2 Delete User Cascade

When deleting a user:

1. Delete from `sessions` table
2. Delete from `impersonation_tokens` table (where admin or target)
3. Delete file: `backend/data/memories_{user_id}.db`
4. Delete directory: `backend/data/vectors/{user_id}/`
5. Delete directory: `backend/data/auth/{user_id}/`
6. Record deletion in `admin_audit_logs`

### 5.3 Audit Logging

Every admin action is logged:

```json
{
  "action": "impersonate_start",
  "admin_user_id": "admin_abc",
  "target_user_id": "user_xyz",
  "timestamp": "2026-03-19T10:00:00Z",
  "ip": "127.0.0.1"
}
```

Impersonation audit includes every action taken while impersonating.

---

## 6. File Structure Changes

```
backend/
├── auth/
│   ├── user_store.py          # Add: delete_user_cascade, admin audit
│   ├── session_middleware.py # Add: impersonation token handling
│   └── impersonation.py      # NEW: impersonation token management
├── memory/
│   ├── memory_store.py        # Enforce user_id on all operations
│   ├── memory_schema.py       # Add user_id to Memory dataclass
│   └── migrations/            # NEW: migration scripts
├── agents/
│   ├── collector_agent.py    # Fix: pass user_id everywhere
│   ├── knowledge_agent.py     # Fix: pass user_id everywhere
│   └── memory_agent.py        # Fix: per-user instances
├── tools/
│   └── mcp_tools.py           # Fix: explicit user_id parameter
├── platforms/                 # Review all for user_id consistency
├── routers/
│   ├── admin.py               # NEW: admin endpoints
│   └── ... (existing)
└── main.py                    # Wire admin router
```

---

## 7. Verification Checklist

Before claiming completion, verify:

- [ ] Every SQLite INSERT has `user_id`
- [ ] Every SQLite query filters by `user_id`
- [ ] `get_memory_store(user_id)` is called everywhere (no bare `get_memory_store()`)
- [ ] `get_token_store(user_id)` is called everywhere (no bare `get_token_store()`)
- [ ] OAuth callback stores tokens in correct user's store
- [ ] Impersonation creates audit log entry
- [ ] Delete user removes all storage files
- [ ] New users cannot see other users' data
- [ ] No `request.state.user_id` is `None` after middleware
- [ ] ContextVar is removed as fallback mechanism
