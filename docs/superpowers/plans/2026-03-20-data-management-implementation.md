# Data Management API Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 5 backend API endpoints for data management: export memories, import memories, cleanup old memories, reset config, and clear all memories.

**Architecture:** New FastAPI router at `backend/routers/data_management.py` with 5 endpoints. User isolation via `request.state.user_id`. Storage via existing `MemoryStore` with batch operations.

**Tech Stack:** FastAPI, Pydantic, SQLite, FAISS, Python 3.10+

---

## Chunk 1: Create Data Management Router

**Files:**
- Create: `backend/routers/data_management.py`
- Test: `backend/tests/test_data_management.py`

### Step 1: Write the data_management.py router

- [ ] **Step 1: Create router file with skeleton**

```python
"""Data management router: export/import/cleanup/reset/clear memories."""
from fastapi import APIRouter, Request, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime
import json

router = APIRouter(prefix="/memories", tags=["data_management"])

# ── Pydantic Models ────────────────────────────────────────────────────────────

class ImportMemory(BaseModel):
    platform: str
    platform_name: str
    platform_id: str
    title: str
    summary: str
    tags: List[str] = []
    source_url: str
    bookmarked_at: str
    importance: float = 0.5
    query_count: int = 0
    media_type: str = "text"
    author: str = ""
    thumbnail_url: str = ""

class ImportResult(BaseModel):
    success: bool
    imported: int = 0
    updated: int = 0
    failed: int = 0
    errors: List[dict] = []

class DeleteOldResult(BaseModel):
    success: bool
    deleted_count: int

class ClearAllResult(BaseModel):
    success: bool
    deleted_count: int

class ConfigResetResult(BaseModel):
    success: bool

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id

def parse_iso_datetime(s: str) -> datetime:
    """Parse ISO datetime string, return current time on failure."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.utcnow()
```

- [ ] **Step 2: Add GET /memories/export endpoint**

```python
from fastapi.responses import Response

@router.get("/export")
async def export_memories(request: Request):
    """Export all memories for the current user as JSON."""
    user_id = get_user_id(request)

    from memory.memory_store import get_memory_store
    store = get_memory_store(user_id)

    # Get all memories (batch query for large datasets)
    all_memories = []
    offset = 0
    BATCH = 1000
    while True:
        rows = store._conn.execute(
            "SELECT * FROM memories WHERE user_id = ? ORDER BY bookmarked_at DESC LIMIT ? OFFSET ?",
            (user_id, BATCH, offset)
        ).fetchall()
        if not rows:
            break
        cols = [c[0] for c in store._conn.execute("PRAGMA table_info(memories)").fetchall()]
        for row in rows:
            d = dict(zip(cols, row))
            all_memories.append({
                "platform": d.get("platform", ""),
                "platform_name": d.get("platform_name", ""),
                "platform_id": d.get("platform_id", ""),
                "title": d.get("title", ""),
                "summary": d.get("summary", ""),
                "tags": json.loads(d.get("tags", "[]")),
                "source_url": d.get("source_url", ""),
                "bookmarked_at": d.get("bookmarked_at", ""),
                "importance": d.get("importance", 0.5),
                "query_count": d.get("query_count", 0),
                "media_type": d.get("media_type", "text"),
                "author": d.get("author", ""),
                "thumbnail_url": d.get("thumbnail_url", ""),
            })
        offset += BATCH

    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "user_id": user_id,
        "memories": all_memories,
    }

    json_str = json.dumps(export_data, ensure_ascii=False)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="memories_export_{timestamp}.json"'}
    )
```

- [ ] **Step 3: Add POST /memories/import endpoint**

```python
@router.post("/import", response_model=ImportResult)
async def import_memories(request: Request, file: UploadFile = File(...)):
    """Import memories from JSON file. Overwrites duplicates by updating existing records."""
    user_id = get_user_id(request)

    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files supported")

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    version = data.get("version", "")
    # Accept "1.0" exactly, reject future versions
    if version != "1.0":
        raise HTTPException(status_code=400, detail="Unsupported export version")

    memories = data.get("memories", [])
    if not memories:
        return ImportResult(success=True, imported=0, updated=0, failed=0, errors=[])

    from memory.memory_store import get_memory_store
    from memory.memory_schema import Memory

    store = get_memory_store(user_id)
    imported = updated = failed = 0
    errors = []

    new_memories = []
    for i, m in enumerate(memories):
        try:
            platform = m.get("platform", "")
            platform_id_val = m.get("platform_id", "")

            # Check if exists
            existing = store._conn.execute(
                "SELECT id FROM memories WHERE user_id = ? AND platform = ? AND platform_id = ?",
                (user_id, platform, platform_id_val)
            ).fetchone()

            bookmarked_at = m.get("bookmarked_at", "")
            parsed_bookmarked = parse_iso_datetime(bookmarked_at)

            mem = Memory(
                user_id=user_id,
                platform=platform,
                platform_name=m.get("platform_name", ""),
                platform_id=platform_id_val,
                title=m.get("title", ""),
                summary=m.get("summary", ""),
                tags=m.get("tags", []),
                source_url=m.get("source_url", ""),
                bookmarked_at=parsed_bookmarked.isoformat(),
                importance=m.get("importance", 0.5),
                query_count=m.get("query_count", 0),
                media_type=m.get("media_type", "text"),
                author=m.get("author", ""),
                thumbnail_url=m.get("thumbnail_url", ""),
            )

            if existing:
                # Update existing - preserve id and last_accessed_at, update all other fields via SQL
                mem.id = existing[0]
                existing_row = store._conn.execute(
                    "SELECT last_accessed_at FROM memories WHERE id = ?", (existing[0],)
                ).fetchone()
                preserved_last_accessed = existing_row[0] if existing_row else ""
                try:
                    # Full UPDATE with all fields (store.update() only updates a subset)
                    store._conn.execute("""
                        UPDATE memories SET
                            platform=?, platform_name=?, platform_id=?, source_url=?,
                            author=?, bookmarked_at=?, title=?, summary=?,
                            raw_content=?, tags=?, media_type=?, thumbnail_url=?,
                            importance=?, query_count=?, last_accessed_at=?
                        WHERE id=? AND user_id=?
                    """, (
                        mem.platform, mem.platform_name, mem.platform_id, mem.source_url,
                        mem.author, mem.bookmarked_at, mem.title, mem.summary,
                        mem.raw_content[:10000] if mem.raw_content else "",
                        json.dumps(mem.tags, ensure_ascii=False),
                        mem.media_type, mem.thumbnail_url,
                        mem.importance, mem.query_count, preserved_last_accessed,
                        mem.id, user_id
                    ))
                    store._conn.commit()
                    updated += 1
                except Exception as e:
                    failed += 1
                    errors.append({"index": i, "platform_id": platform_id_val, "error": str(e)})
            else:
                mem.last_accessed_at = datetime.utcnow().isoformat()
                new_memories.append(mem)
                imported += 1

        except Exception as e:
            failed += 1
            errors.append({"index": i, "platform_id": m.get("platform_id", ""), "error": str(e)})

    # Batch add new memories (add_batch skips duplicates, does NOT update)
    if new_memories:
        try:
            store.add_batch(new_memories)
        except Exception as e:
            failed += len(new_memories)
            errors.append({"index": -1, "error": f"Batch insert failed: {str(e)}"})

    return ImportResult(success=True, imported=imported, updated=updated, failed=failed, errors=errors)
```

Note: `add_batch` only inserts - it skips records where `exists_by_platform_id` returns True. For existing records, a full SQL UPDATE covers all fields. For new records, `add_batch` is used for performance. FAISS vectors for updated records are NOT re-indexed (would require re-embedding).

- [ ] **Step 4: Add DELETE /memories/old endpoint**

```python
@router.delete("/old")
async def cleanup_old_memories(request: Request, days: int = Query(180, ge=1)):
    """Delete memories not accessed in the last N days."""
    user_id = get_user_id(request)

    from datetime import timedelta
    from memory.memory_store import get_memory_store

    store = get_memory_store(user_id)
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # Delete memories where last_accessed_at < cutoff OR last_accessed_at is NULL/empty
    cur = store._conn.execute(
        "SELECT COUNT(*) FROM memories WHERE user_id = ? AND (last_accessed_at < ? OR last_accessed_at IS NULL OR last_accessed_at = '')",
        (user_id, cutoff)
    )
    count = cur.fetchone()[0]

    store._conn.execute(
        "DELETE FROM memories WHERE user_id = ? AND (last_accessed_at < ? OR last_accessed_at IS NULL OR last_accessed_at = '')",
        (user_id, cutoff)
    )
    store._conn.commit()

    return DeleteOldResult(success=True, deleted_count=count)
```

- [ ] **Step 5: Add DELETE /memories/all endpoint**

```python
@router.delete("/all")
async def clear_all_memories(request: Request, confirm: str = Query(...)):
    """Delete ALL memories for the current user. Requires confirm=true."""
    if confirm.lower() != "true":
        raise HTTPException(status_code=400, detail="confirm must be 'true'")

    user_id = get_user_id(request)

    from memory.memory_store import get_memory_store
    import faiss
    import numpy as np

    store = get_memory_store(user_id)

    cur = store._conn.execute("SELECT COUNT(*) FROM memories WHERE user_id = ?", (user_id,))
    count = cur.fetchone()[0]

    # Delete only current user's memories (not all users!)
    store._conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
    store._conn.commit()

    # Rebuild empty FAISS index (inline from memory_store.delete_all)
    if store._index is not None:
        store._index.reset()
        store._id_to_pos.clear()
        store._pos_to_id.clear()
        store._save_index()

    return ClearAllResult(success=True, deleted_count=count)
```

- [ ] **Step 6: Add POST /config/reset endpoint (in same router or separate)**

Add to `backend/routers/data_management.py`:

```python
config_router = APIRouter(prefix="/config", tags=["config_management"])

@config_router.post("/reset", response_model=ConfigResetResult)
async def reset_config(request: Request):
    """Reset all runtime config to defaults (including API keys)."""
    user_id = get_user_id(request)

    import config as cfg_module

    # Clear runtime config file and in-memory state
    cfg_module.RUNTIME_CONFIG_PATH.write_text("{}")
    cfg_module._runtime_overrides = {}

    return ConfigResetResult(success=True)
```

- [ ] **Step 7: Commit chunk 1**

```bash
git add backend/routers/data_management.py
git commit -m "feat: add data management router with 5 endpoints"
```

---

## Chunk 2: Register Router in main.py

**Files:**
- Modify: `backend/main.py` (add include_router lines)

- [ ] **Step 1: Add router imports and registration**

Find the line `app.include_router(admin_router)` in `backend/main.py` (around line 53) and add after it:

```python
from routers.data_management import router as data_management_router, config_router as data_config_router

app.include_router(data_management_router)
app.include_router(data_config_router)
```

Also need to add `UploadFile` import if not already present.

- [ ] **Step 2: Verify the imports work**

Run: `cd backend && python -c "from routers.data_management import router; print('OK')"`

- [ ] **Step 3: Commit chunk 2**

```bash
git add backend/main.py
git commit -m "feat: register data management routes in main app"
```

---

## Chunk 3: Write Tests

**Files:**
- Create: `backend/tests/test_data_management.py`

- [ ] **Step 1: Write test file with fixtures**

```python
"""Tests for data management API endpoints."""
import pytest
import json
from datetime import datetime
from fastapi.testclient import TestClient

# Assumes app fixture is available via conftest.py

def test_export_memories_empty(client, auth_headers):
    """Export returns empty list when no memories."""
    response = client.get("/memories/export", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "1.0"
    assert data["memories"] == []

def test_export_memories_with_data(client, auth_headers, sample_memory):
    """Export returns all user memories."""
    response = client.get("/memories/export", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["memories"]) >= 1

def test_import_memories_success(client, auth_headers):
    """Import adds new memories."""
    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "user_id": "test_user",
        "memories": [
            {
                "platform": "youtube",
                "platform_name": "YouTube",
                "platform_id": "test_yt_001",
                "title": "Test Video",
                "summary": "Test summary",
                "tags": ["test"],
                "source_url": "https://youtube.com/watch?v=test",
                "bookmarked_at": "2026-01-01T00:00:00",
                "importance": 0.8,
                "query_count": 3,
                "media_type": "video",
                "author": "Test Author",
                "thumbnail_url": ""
            }
        ]
    }
    files = {"file": ("export.json", json.dumps(export_data), "application/json")}
    response = client.post("/memories/import", files=files, headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
    assert result["imported"] >= 1

def test_import_invalid_version(client, auth_headers):
    """Import rejects unsupported version."""
    export_data = {"version": "99.0", "memories": []}
    files = {"file": ("export.json", json.dumps(export_data), "application/json")}
    response = client.post("/memories/import", files=files, headers=auth_headers)
    assert response.status_code == 400

def test_cleanup_old_memories(client, auth_headers, sample_memory):
    """Cleanup removes old memories."""
    response = client.delete("/memories/old?days=1", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert "deleted_count" in result

def test_cleanup_requires_days_param(client, auth_headers):
    """Cleanup requires days parameter."""
    response = client.delete("/memories/old", headers=auth_headers)
    assert response.status_code == 422  # FastAPI validation error

def test_clear_all_requires_confirm(client, auth_headers):
    """Clear all fails without confirm=true."""
    response = client.delete("/memories/all", headers=auth_headers)
    assert response.status_code == 400

def test_clear_all_with_confirm(client, auth_headers, sample_memory):
    """Clear all deletes all user memories with confirm=true."""
    response = client.delete("/memories/all?confirm=true", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
    assert result["deleted_count"] >= 1

def test_config_reset(client, auth_headers):
    """Reset config clears runtime overrides."""
    response = client.post("/config/reset", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
```

- [ ] **Step 2: Verify tests compile**

First check if conftest.py fixtures exist:

Run: `ls backend/tests/conftest.py && head -30 backend/tests/conftest.py`

If conftest.py does not exist or lacks required fixtures, create it with:

```python
"""Test fixtures for backend tests."""
import pytest
import sys
from pathlib import Path

# Add backend root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture
def client():
    """Create a test client with app."""
    from main import create_app
    app = create_app()
    from fastapi.testclient import TestClient
    return TestClient(app)

@pytest.fixture
def auth_headers():
    """Return headers with a valid session cookie for testing."""
    # For unit tests, mock authentication via header
    return {"X-Session-Id": "test_session_id"}

@pytest.fixture
def sample_memory():
    """Create a sample memory in the test database."""
    # This fixture should be implemented to create a test memory
    # that can be cleaned up after the test
    pass
```

Then run: `cd backend && python -m pytest tests/test_data_management.py --collect-only`

- [ ] **Step 3: Commit chunk 3**

```bash
git add backend/tests/test_data_management.py
git commit -m "test: add data management API tests"
```

---

## Chunk 4: Frontend Integration

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/api/apiClient.ts`

- [ ] **Step 1: Add API client methods**

In `frontend/src/api/apiClient.ts`, add:

```typescript
export const exportMemories = async (): Promise<Blob> => {
  const response = await http.get('/memories/export', { responseType: 'blob' })
  return response.data
}

export const importMemories = async (file: File): Promise<{ success: boolean; imported: number; updated: number; failed: number }> => {
  const formData = new FormData()
  formData.append('file', file)
  const response = await http.post('/memories/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
  return response.data
}

export const cleanupOldMemories = async (days: number = 180): Promise<{ success: boolean; deleted_count: number }> =>
  (await http.delete('/memories/old', { params: { days } })).data

export const resetConfig = async (): Promise<{ success: boolean }> =>
  (await http.post('/config/reset')).data

export const clearAllMemories = async (confirm: boolean): Promise<{ success: boolean; deleted_count: number }> =>
  (await http.delete('/memories/all', { params: { confirm: confirm.toString() } })).data
```

- [ ] **Step 2: Wire up button handlers in Settings.tsx**

Replace the placeholder handlers:

```typescript
async function handleExportMemories() {
  try {
    const blob = await exportMemories()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `memories_export_${new Date().toISOString().slice(0,10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    push('导出成功', 'success')
  } catch {
    push('导出失败', 'error')
  }
}

async function handleImportMemories() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (e) => {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (!file) return
    try {
      const result = await importMemories(file)
      push(`导入完成：新增 ${result.imported}，更新 ${result.updated}，失败 ${result.failed}`, 'success')
    } catch {
      push('导入失败', 'error')
    }
  }
  input.click()
}

async function handleClearOldMemories() {
  if (confirming !== 'clearold') { setConfirming('clearold'); return }
  setConfirming(null)
  try {
    const result = await cleanupOldMemories(180)
    push(`已清理 ${result.deleted_count} 条旧记忆`, 'success')
  } catch {
    push('清理失败', 'error')
  }
}

async function handleResetConfig() {
  if (confirming !== 'reset') { setConfirming('reset'); return }
  setConfirming(null)
  try {
    await resetConfig()
    push('配置已重置，请刷新页面', 'success')
  } catch {
    push('重置失败', 'error')
  }
}

async function handleClearAllMemories() {
  if (confirming !== 'clear') { setConfirming('clear'); return }
  setConfirming(null)
  try {
    const result = await clearAllMemories(true)
    push(`已清空 ${result.deleted_count} 条记忆`, 'success')
  } catch {
    push('清空失败', 'error')
  }
}
```

Also update the confirming state types in the component to handle `'clearold'` in addition to `'reset'` and `'clear'`.

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 4: Commit chunk 4**

```bash
git add frontend/src/api/apiClient.ts frontend/src/pages/Settings.tsx
git commit -m "feat: wire up data management API to Settings UI"
```

---

## Verification Checklist

After all chunks:

- [ ] `cd backend && python -c "from routers.data_management import router, config_router; print('Router imports OK')"`
- [ ] `cd backend && python -m pytest tests/test_data_management.py -v`
- [ ] `cd frontend && npx tsc --noEmit 2>&1 | grep -v "Sync.tsx"` (Sync.tsx has pre-existing error)
- [ ] Manual test: export returns valid JSON, import works, cleanup deletes old, reset clears config, clear all empties user data
