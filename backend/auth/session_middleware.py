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
    "/api/health",
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
        set_current_user(user_id)
        try:
            response = await call_next(request)
            return response
        finally:
            # Clean up context
            set_current_user(None)