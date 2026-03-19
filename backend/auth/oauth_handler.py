"""
auth/oauth_handler.py
OAuth 2.0 统一流程处理
支持 Authorization Code Flow + PKCE
"""

import secrets
import hashlib
import base64
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode, urljoin
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from auth.token_store import TokenStore, TokenData, get_token_store


# ── 各平台 OAuth 配置 ─────────────────────────────────────────────────────────

PLATFORM_OAUTH_CONFIGS = {
    "youtube": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/youtube.readonly",
        "client_id": config.YOUTUBE_CLIENT_ID,
        "client_secret": config.YOUTUBE_CLIENT_SECRET,
    },
    "twitter": {
        "auth_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scope": "tweet.read users.read bookmark.read offline.access",
        "client_id": config.TWITTER_CLIENT_ID,
        "client_secret": config.TWITTER_CLIENT_SECRET,
        "use_pkce": True,
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "read:user",
        "client_id": config.GITHUB_CLIENT_ID,
        "client_secret": config.GITHUB_CLIENT_SECRET,
    },
    "bilibili": {
        "auth_url": "https://passport.bilibili.com/oauth2/authorize",
        "token_url": "https://passport.bilibili.com/oauth2/token",
        "scope": "read",
        "client_id": config.BILIBILI_CLIENT_ID,
        "client_secret": config.BILIBILI_CLIENT_SECRET,
    },
    "douyin": {
        "auth_url": "https://open.douyin.com/platform/oauth/connect",
        "token_url": "https://open.douyin.com/oauth/access_token",
        "scope": "user.info.basic,video.list,item.comment",
        "client_id": config.DOUYIN_CLIENT_ID,
        "client_secret": config.DOUYIN_CLIENT_SECRET,
    },
}


def _generate_pkce() -> Tuple[str, str]:
    """生成 PKCE code_verifier 和 code_challenge（S256）"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


class OAuthHandler:
    """OAuth 2.0 统一流程处理器"""

    def __init__(self, token_store: TokenStore = None):
        self._store = token_store  # Don't call get_token_store() here
        self._pending_states: Dict[str, Dict] = {}  # state -> {platform, user_id, code_verifier}

    def get_auth_url(self, platform: str, user_id: str) -> Tuple[str, str]:
        """
        生成平台授权 URL
        返回 (auth_url, state)
        """
        cfg = PLATFORM_OAUTH_CONFIGS.get(platform)
        if not cfg:
            raise ValueError(f"不支持的平台: {platform}")

        state = secrets.token_urlsafe(16)
        callback_url = urljoin(
            config.OAUTH_CALLBACK_BASE,
            f"{config.OAUTH_CALLBACK_PATH}/{platform}"
        )

        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": callback_url,
            "scope": cfg["scope"],
            "response_type": "code",
            "state": state,
            "access_type": "offline",  # 请求 refresh_token（Google）
        }

        pending = {"platform": platform, "user_id": user_id}

        # PKCE 支持（Twitter 等）
        if cfg.get("use_pkce"):
            code_verifier, code_challenge = _generate_pkce()
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
            pending["code_verifier"] = code_verifier

        self._pending_states[state] = pending
        auth_url = cfg["auth_url"] + "?" + urlencode(params)
        return auth_url, state

    def handle_callback(self, platform: str, code: str, state: str) -> bool:
        """
        处理 OAuth 回调，用 code 换取 tokens
        返回是否成功
        """
        pending = self._pending_states.pop(state, None)
        if not pending or pending["platform"] != platform:
            print(f"[OAuth] state 无效或已过期: {state}")
            return False

        user_id = pending.get("user_id", "_default")  # Extract user_id

        cfg = PLATFORM_OAUTH_CONFIGS.get(platform)
        if not cfg:
            return False

        callback_url = urljoin(
            config.OAUTH_CALLBACK_BASE,
            f"{config.OAUTH_CALLBACK_PATH}/{platform}"
        )

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }

        if "code_verifier" in pending:
            data["code_verifier"] = pending["code_verifier"]

        try:
            headers = {"Accept": "application/json"}
            resp = requests.post(cfg["token_url"], data=data, headers=headers, timeout=30)
            resp.raise_for_status()
            token_json = resp.json()
        except Exception as e:
            print(f"[OAuth] {platform} token 换取失败: {e}")
            return False

        return self._save_token_response(platform, token_json, cfg, user_id)

    def refresh_token(self, platform: str, user_id: str) -> bool:
        """
        静默刷新 access_token
        过期前 TOKEN_REFRESH_BEFORE_MINUTES 分钟自动调用
        """
        token_store = get_token_store(user_id)
        token_data = token_store.load(platform)
        if not token_data or not token_data.refresh_token:
            return False

        cfg = PLATFORM_OAUTH_CONFIGS.get(platform)
        if not cfg:
            return False

        data = {
            "grant_type": "refresh_token",
            "refresh_token": token_data.refresh_token,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }

        try:
            resp = requests.post(cfg["token_url"], data=data, timeout=30)
            resp.raise_for_status()
            token_json = resp.json()
        except Exception as e:
            print(f"[OAuth] {platform} token 刷新失败: {e}")
            token_store.mark_needs_reauth(platform, str(e))
            return False

        # 某些平台不返回新 refresh_token，保留旧的
        if "refresh_token" not in token_json:
            token_json["refresh_token"] = token_data.refresh_token

        return self._save_token_response(platform, token_json, cfg, user_id)

    def ensure_valid_token(self, platform: str, user_id: str) -> Optional[str]:
        """
        确保 access_token 有效，必要时自动刷新
        返回有效的 access_token 或 None
        """
        token_store = get_token_store(user_id)
        token_data = token_store.load(platform)
        if not token_data:
            return None

        if token_data.status == "needs_reauth":
            print(f"[OAuth] {platform} 需要重新授权")
            return None

        if token_data.is_expiring_soon():
            print(f"[OAuth] {platform} token 即将过期，静默刷新中...")
            if not self.refresh_token(platform, user_id):
                return None
            token_data = token_store.load(platform)

        return token_data.access_token if token_data else None

    def _save_token_response(self, platform: str, token_json: dict, cfg: dict, user_id: str) -> bool:
        """解析 token 响应并保存"""
        expires_in = token_json.get("expires_in", 3600)
        expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

        token_data = TokenData(
            platform=platform,
            auth_mode="oauth2",
            access_token=token_json.get("access_token", ""),
            refresh_token=token_json.get("refresh_token", ""),
            token_type=token_json.get("token_type", "Bearer"),
            scope=token_json.get("scope", cfg.get("scope", "")),
            expires_at=expires_at,
            last_refresh=datetime.utcnow().isoformat(),
            status="connected",
        )

        if not token_data.access_token:
            print(f"[OAuth] {platform} 未收到 access_token")
            return False

        token_store = get_token_store(user_id)
        token_store.save(token_data)
        print(f"[OAuth] {platform} 授权成功，token 已加密存储")
        return True

    def revoke(self, platform: str, user_id: str) -> None:
        """撤销平台授权"""
        token_store = get_token_store(user_id)
        token_store.delete(platform)
        print(f"[OAuth] {platform} 授权已撤销")


