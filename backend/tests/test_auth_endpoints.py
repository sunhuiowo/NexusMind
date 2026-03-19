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