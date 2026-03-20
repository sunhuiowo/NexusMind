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
    """Return headers with a valid session for testing."""
    # Mock auth - the SessionMiddleware sets user_id from session
    return {"X-Session-Id": "test_session_id"}