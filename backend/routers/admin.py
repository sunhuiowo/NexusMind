"""Admin router for user management and impersonation"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uuid
import json

from auth.user_store import get_user_store
from auth.impersonation import (
    create_impersonation_token,
    validate_impersonation_token,
    revoke_impersonation_token,
)
from auth.user_store import _get_db_conn

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str
    password: str


# ── User Management ──────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(request: Request):
    """List all users (admin only)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    conn = _get_db_conn(get_user_store()._db_path)
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
    conn = _get_db_conn(user_store._db_path)
    conn.execute("""
        INSERT INTO admin_audit_logs (id, admin_user_id, action, target_user_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), request.state.user_id, "user_create", user_id,
          json.dumps({"username": req.username}), datetime.now().isoformat()))
    conn.commit()

    return {"success": True, "user_id": user_id, "username": req.username}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    """Delete a user and all their data (admin only, cannot delete other admins)"""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Cascade delete via user_store
    user_store = get_user_store()
    success, error = user_store.delete_user_cascade(user_id)

    if not success:
        raise HTTPException(status_code=400, detail=error)

    # Log deletion
    conn = _get_db_conn(user_store._db_path)
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

    conn = _get_db_conn(get_user_store()._db_path)
    logs = conn.execute("""
        SELECT id, admin_user_id, action, target_user_id, details, created_at
        FROM admin_audit_logs ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()

    return {"logs": [{"id": l[0], "admin_user_id": l[1], "action": l[2],
                      "target_user_id": l[3], "details": json.loads(l[4] or "{}"),
                      "created_at": l[5]} for l in logs]}
