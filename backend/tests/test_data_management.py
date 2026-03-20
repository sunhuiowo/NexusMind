"""Tests for data management API endpoints."""
import pytest
import json
from datetime import datetime

def test_export_memories_empty(client, auth_headers):
    """Export returns empty list when no memories."""
    response = client.get("/memories/export", headers=auth_headers)
    assert response.status_code == 200
    # Check it returns JSON
    data = response.json()
    assert "memories" in data
    assert data["version"] == "1.0"

def test_import_memories_success(client, auth_headers):
    """Import adds new memories."""
    export_data = {
        "version": "1.0",
        "memories": [
            {
                "platform": "youtube",
                "platform_name": "YouTube",
                "platform_id": f"test_yt_{datetime.utcnow().timestamp()}",
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

def test_import_empty_memories(client, auth_headers):
    """Import with empty memories array returns error."""
    export_data = {"version": "1.0", "memories": []}
    files = {"file": ("export.json", json.dumps(export_data), "application/json")}
    response = client.post("/memories/import", files=files, headers=auth_headers)
    assert response.status_code == 400

def test_cleanup_old_memories(client, auth_headers):
    """Cleanup removes old memories."""
    response = client.delete("/memories/old?days=1", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert "deleted_count" in result
    assert result["success"] == True

def test_cleanup_default_days(client, auth_headers):
    """Cleanup with default days parameter."""
    response = client.delete("/memories/old", headers=auth_headers)
    assert response.status_code == 200  # default is 180

def test_clear_all_requires_confirm(client, auth_headers):
    """Clear all fails without confirm=true."""
    response = client.delete("/memories/all", headers=auth_headers)
    assert response.status_code == 400

def test_clear_all_with_confirm(client, auth_headers):
    """Clear all deletes all user memories with confirm=true."""
    response = client.delete("/memories/all?confirm=true", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
    assert "deleted_count" in result

def test_config_reset(client, auth_headers):
    """Reset config clears runtime overrides."""
    response = client.post("/config/reset", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True

def test_unauthorized_without_auth(client):
    """All endpoints require authentication."""
    response = client.get("/memories/export")
    assert response.status_code == 401