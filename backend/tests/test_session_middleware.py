"""Tests for session_middleware.py"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from starlette.requests import Request
from starlette.responses import JSONResponse


@pytest.mark.asyncio
async def test_session_middleware_allows_public_paths():
    """Public paths should bypass session check"""
    from auth.session_middleware import SessionMiddleware

    app = MagicMock()
    middleware = SessionMiddleware(app, public_paths={"/auth/login", "/health"})

    request = MagicMock(spec=Request)
    request.url.path = "/auth/login"
    request.headers = {}

    async def call_next(req):
        return JSONResponse({"success": True})

    with patch('auth.session_middleware.get_user_store') as mock_store:
        response = await middleware.dispatch(request, call_next)

    assert response is not None
    # Should not have called validate_session for public path
    mock_store.validate_session.assert_not_called()


@pytest.mark.asyncio
async def test_session_middleware_rejects_missing_session():
    """Missing session on protected path should return 401"""
    from auth.session_middleware import SessionMiddleware

    app = MagicMock()
    middleware = SessionMiddleware(app)

    request = MagicMock(spec=Request)
    request.url.path = "/api/memories"
    request.headers = {}
    request.cookies = {}

    async def call_next(req):
        return JSONResponse({"success": True})

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_session_middleware_rejects_invalid_session():
    """Invalid session should return 401"""
    from auth.session_middleware import SessionMiddleware

    app = MagicMock()
    middleware = SessionMiddleware(app)

    request = MagicMock(spec=Request)
    request.url.path = "/api/memories"
    request.headers = {"x-session-id": "invalid-session"}
    request.cookies = {}

    mock_store = MagicMock()
    mock_store.validate_session.return_value = None

    async def call_next(req):
        return JSONResponse({"success": True})

    with patch('auth.session_middleware.get_user_store', return_value=mock_store):
        response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_session_middleware_sets_context_on_valid_session():
    """Valid session should set user context and call next"""
    from auth.session_middleware import SessionMiddleware
    from auth.user_store import set_current_user, get_current_user

    app = MagicMock()
    middleware = SessionMiddleware(app)

    request = MagicMock(spec=Request)
    request.url.path = "/api/memories"
    request.headers = {"x-session-id": "valid-session-id"}
    request.cookies = {}

    mock_store = MagicMock()
    mock_store.validate_session.return_value = "user_123"

    context_set = []
    def mock_set_current_user(uid):
        context_set.append(uid)

    async def call_next(req):
        # Verify context was set
        context_set.append(get_current_user())
        return JSONResponse({"success": True})

    with patch('auth.session_middleware.get_user_store', return_value=mock_store):
        with patch('auth.user_store.set_current_user', side_effect=mock_set_current_user):
            response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    assert "user_123" in context_set


@pytest.mark.asyncio
async def test_session_middleware_cleans_up_context():
    """Context should be cleaned up after request"""
    from auth.session_middleware import SessionMiddleware
    from auth.user_store import set_current_user, get_current_user

    app = MagicMock()
    middleware = SessionMiddleware(app)

    request = MagicMock(spec=Request)
    request.url.path = "/api/memories"
    request.headers = {"x-session-id": "valid-session"}
    request.cookies = {}

    mock_store = MagicMock()
    mock_store.validate_session.return_value = "user_456"

    async def call_next(req):
        return JSONResponse({"success": True})

    with patch('auth.session_middleware.get_user_store', return_value=mock_store):
        with patch('auth.user_store.set_current_user') as mock_set:
            mock_set.side_effect = lambda x: set_current_user(x) if x else set_current_user(None)
            response = await middleware.dispatch(request, call_next)

    # After request, context should be None
    assert get_current_user() is None