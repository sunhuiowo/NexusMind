"""Session validation middleware for user authentication"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth.user_store import get_user_store, set_current_user

logger = logging.getLogger(__name__)

# Public paths that don't require authentication
PUBLIC_PATHS = {
    "/auth/register",   # Public - anyone can register
    "/auth/login",      # Public - anyone can login
    "/health",
    "/docs",
    "/openapi.json",
    "/api/health",
    # OAuth callbacks - MUST be public (external redirects from OAuth providers)
    "/auth/callback/youtube",
    "/auth/callback/twitter",
    "/auth/callback/pocket",
    "/auth/callback/github",
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
        if path in self.public_paths:
            response = await call_next(request)
            return response

        # Get session_id from header or cookie
        session_id = request.headers.get("x-session-id")
        if not session_id:
            session_id = request.cookies.get("session_id")

        if not session_id:
            return JSONResponse(status_code=401, content={"error": "请先登录"})

        # Validate session and get user data
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