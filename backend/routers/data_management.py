"""Data management router: export/import/cleanup/reset/clear memories."""
from fastapi import APIRouter, Request, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime, timedelta
import json
import uuid
import numpy as np

from memory.memory_store import get_memory_store, _get_db_conn
from memory.memory_schema import Memory
from tools.llm import get_embedder

DEFAULT_CLEANUP_DAYS = 180
MAX_IMPORT_ERRORS = 20

router = APIRouter(prefix="/memories", tags=["data_management"])
config_router = APIRouter(prefix="/config", tags=["config_management"])

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


# ── Export/Import ──────────────────────────────────────────────────────────────

@router.get("/export")
async def export_memories(request: Request):
    """
    Export all memories for the current user as a downloadable JSON file.
    Returns all memory fields including embeddings.
    """
    user_id = get_user_id(request)
    store = get_memory_store(user_id)
    conn = _get_db_conn(store._db_path)

    rows = conn.execute(
        "SELECT * FROM memories WHERE user_id=?", (user_id,)
    ).fetchall()

    memories = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["related_ids"] = json.loads(d.get("related_ids") or "[]")
        d.pop("embedding", None)  # Don't export raw embeddings
        memories.append(d)

    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "count": len(memories),
        "memories": memories,
    }

    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    filename = f"memories_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_memories(request: Request, file: UploadFile = File(...)):
    """
    Import memories from a JSON file.
    - For existing records (same platform+platform_id): FULL SQL UPDATE
    - For new records: batch insert via add_batch
    """
    user_id = get_user_id(request)

    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are supported")

    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    memories_data = data.get("memories", [])
    if not memories_data:
        raise HTTPException(status_code=400, detail="No memories found in the file")

    store = get_memory_store(user_id)
    conn = _get_db_conn(store._db_path)
    embedder = get_embedder()

    imported = 0
    updated = 0
    failed = 0
    errors = []
    new_memories = []
    now = datetime.utcnow().isoformat()

    for idx, mem_data in enumerate(memories_data):
        try:
            platform = mem_data.get("platform", "")
            platform_id = mem_data.get("platform_id", "")

            if not platform or not platform_id:
                errors.append({"index": idx, "error": "Missing platform or platform_id"})
                failed += 1
                continue

            # Check if record already exists
            existing = conn.execute(
                "SELECT id FROM memories WHERE platform=? AND platform_id=? AND user_id=?",
                (platform, platform_id, user_id),
            ).fetchone()

            if existing:
                # FULL SQL UPDATE for existing records
                memory_id = existing[0]
                conn.execute("""
                    UPDATE memories SET
                        title=?,
                        summary=?,
                        tags=?,
                        source_url=?,
                        bookmarked_at=?,
                        importance=?,
                        query_count=?,
                        media_type=?,
                        author=?,
                        thumbnail_url=?,
                        last_accessed_at=?,
                        related_ids=?,
                        platform_name=?
                    WHERE id=? AND user_id=?
                """, (
                    mem_data.get("title", ""),
                    mem_data.get("summary", ""),
                    json.dumps(mem_data.get("tags", []), ensure_ascii=False),
                    mem_data.get("source_url", ""),
                    mem_data.get("bookmarked_at", now),
                    mem_data.get("importance", 0.5),
                    mem_data.get("query_count", 0),
                    mem_data.get("media_type", "text"),
                    mem_data.get("author", ""),
                    mem_data.get("thumbnail_url", ""),
                    mem_data.get("last_accessed_at", ""),
                    json.dumps(mem_data.get("related_ids", []), ensure_ascii=False),
                    mem_data.get("platform_name", ""),
                    memory_id,
                    user_id,
                ))
                updated += 1
            else:
                # Create new Memory object for batch insert
                memory = Memory(
                    id=mem_data.get("id") or str(uuid.uuid4()),
                    created_at=mem_data.get("created_at") or now,
                    user_id=user_id,
                    platform=platform,
                    platform_name=mem_data.get("platform_name", ""),
                    platform_id=platform_id,
                    source_url=mem_data.get("source_url", ""),
                    author=mem_data.get("author", ""),
                    bookmarked_at=mem_data.get("bookmarked_at", now),
                    title=mem_data.get("title", ""),
                    summary=mem_data.get("summary", ""),
                    raw_content=mem_data.get("raw_content", ""),
                    tags=mem_data.get("tags", []),
                    media_type=mem_data.get("media_type", "text"),
                    thumbnail_url=mem_data.get("thumbnail_url", ""),
                    importance=mem_data.get("importance", 0.5),
                    query_count=mem_data.get("query_count", 0),
                    last_accessed_at=mem_data.get("last_accessed_at", ""),
                    related_ids=mem_data.get("related_ids", []),
                    parent_id=mem_data.get("parent_id"),
                )
                new_memories.append(memory)
                imported += 1

        except Exception as e:
            errors.append({"index": idx, "error": str(e)})
            failed += 1

    # Batch insert new memories
    if new_memories:
        # Generate embeddings for new memories
        for memory in new_memories:
            if memory.summary:
                try:
                    memory.embedding = embedder.embed(memory.summary)
                except Exception:
                    memory.embedding = []

        store.add_batch(new_memories)

    conn.commit()

    return ImportResult(
        success=True,
        imported=imported,
        updated=updated,
        failed=failed,
        errors=errors[:MAX_IMPORT_ERRORS],  # Limit errors to first MAX_IMPORT_ERRORS
    )


# ── Delete Old Memories ────────────────────────────────────────────────────────

@router.delete("/old")
async def delete_old_memories(
    request: Request,
    days: int = Query(default=DEFAULT_CLEANUP_DAYS, ge=1, description="Delete memories not accessed in last N days"),
):
    """
    Delete memories older than specified days OR with NULL/empty last_accessed_at.
    """

    user_id = get_user_id(request)
    store = get_memory_store(user_id)
    conn = _get_db_conn(store._db_path)

    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # Delete memories where last_accessed_at is NULL, empty, or older than cutoff
    result = conn.execute("""
        DELETE FROM memories
        WHERE user_id=?
        AND (
            last_accessed_at IS NULL
            OR last_accessed_at = ''
            OR last_accessed_at < ?
        )
    """, (user_id, cutoff))

    conn.commit()
    deleted_count = result.rowcount

    # Rebuild FAISS index to remove orphaned entries
    _rebuild_faiss_index(store, conn, user_id)

    return DeleteOldResult(success=True, deleted_count=deleted_count)


# ── Clear All Memories ────────────────────────────────────────────────────────

@router.delete("/all")
async def clear_all_memories(
    request: Request,
    confirm: bool = Query(description="Must be true to execute deletion"),
):
    """
    Delete ALL memories for the current user and reset FAISS index.
    Requires confirm=true to execute.
    """
    if not confirm:
        raise HTTPException(status_code=400, detail="Must set confirm=true to execute deletion")

    user_id = get_user_id(request)
    store = get_memory_store(user_id)
    conn = _get_db_conn(store._db_path)

    # Get count before deletion
    count_result = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE user_id=?", (user_id,)
    ).fetchone()
    deleted_count = count_result[0] if count_result else 0

    # Delete all memories for this user
    conn.execute("DELETE FROM memories WHERE user_id=?", (user_id,))
    conn.commit()

    # Reset FAISS index for this user
    store._index.reset()
    store._id_to_pos.clear()
    store._pos_to_id.clear()
    store._save_index()

    return ClearAllResult(success=True, deleted_count=deleted_count)


# ── Config Reset ───────────────────────────────────────────────────────────────

@config_router.post("/reset")
async def reset_config(request: Request):
    """
    Reset runtime configuration by clearing runtime_config.json and _runtime_overrides.
    This clears all runtime configuration changes made via POST /config.
    """
    get_user_id(request)  # Ensure user is authenticated

    import config as cfg_module

    # Clear runtime overrides in memory
    cfg_module._runtime_overrides = {}

    # Clear runtime_config.json file
    cfg_module.RUNTIME_CONFIG_PATH.write_text("{}")

    return ConfigResetResult(success=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _rebuild_faiss_index(store, conn, user_id: str):
    """
    Rebuild FAISS index by removing entries for deleted memories.
    This is called after bulk deletions to clean up orphaned FAISS entries.
    """
    try:
        import faiss

        # Get all remaining memory IDs from SQLite
        rows = conn.execute(
            "SELECT id FROM memories WHERE user_id=?", (user_id,)
        ).fetchall()
        remaining_ids = {row[0] for row in rows}

        # Remove orphaned entries from ID mappings
        orphaned_ids = set(store._id_to_pos.keys()) - remaining_ids
        for memory_id in orphaned_ids:
            if memory_id in store._id_to_pos:
                pos = store._id_to_pos.pop(memory_id)
                store._pos_to_id.pop(pos, None)

        # If too many orphaned entries, rebuild index entirely
        if remaining_ids and len(orphaned_ids) > len(remaining_ids) * 0.5:
            # Get all memories and rebuild embeddings
            embedder = get_embedder()
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND summary IS NOT NULL AND summary != ''",
                (user_id,)
            ).fetchall()

            # Reset index
            store._index.reset()
            store._id_to_pos.clear()
            store._pos_to_id.clear()

            # Re-add all memories
            for row in rows:
                memory = Memory.from_dict({
                    "id": row["id"],
                    "summary": row["summary"],
                    "platform": row["platform"],
                    "platform_id": row["platform_id"],
                })

                if memory.summary:
                    try:
                        memory.embedding = embedder.embed(memory.summary)
                        vec = np.array([memory.embedding], dtype=np.float32)
                        norm = np.linalg.norm(vec, axis=1, keepdims=True)
                        if norm[0][0] > 0:
                            vec = vec / norm
                        faiss_pos = store._index.ntotal
                        store._index.add(vec)
                        store._id_to_pos[memory.id] = faiss_pos
                        store._pos_to_id[faiss_pos] = memory.id
                    except Exception:
                        pass

        store._save_index()

    except ImportError:
        pass  # FAISS not available