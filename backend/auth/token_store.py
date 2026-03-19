"""
auth/token_store.py
AES-256-GCM 加密凭证存储
密钥由用户主密码通过 PBKDF2 派生，所有凭证落盘前加密
"""

import os
import json
import base64
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


@dataclass
class TokenData:
    """平台凭证数据"""
    platform: str
    auth_mode: str              # oauth2 / apikey / cookie / pat
    access_token: str = ""
    refresh_token: str = ""
    api_key: str = ""
    cookie: str = ""
    # B站专用 Cookie 字段
    sessdata: str = ""          # B站 SESSDATA cookie
    bili_jct: str = ""          # B站 CSRF token
    dedeuserid: str = ""        # B站用户 ID
    token_type: str = "Bearer"
    scope: str = ""
    expires_at: str = ""        # ISO 8601
    last_refresh: str = ""      # ISO 8601
    status: str = "connected"   # connected / needs_reauth / error
    extra: Dict[str, Any] = None  # 平台特定额外字段

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}

    def is_expired(self) -> bool:
        """检查 access_token 是否已过期"""
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.utcnow() >= expires
        except ValueError:
            return False

    def is_expiring_soon(self, minutes: int = None) -> bool:
        """检查是否即将过期（默认提前 config 中配置的分钟数）"""
        if minutes is None:
            minutes = config.TOKEN_REFRESH_BEFORE_MINUTES
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.utcnow() >= expires - timedelta(minutes=minutes)
        except ValueError:
            return False

    def is_cookie_expiring_soon(self, days: int = None) -> bool:
        """检查 Cookie 是否即将过期（提前 N 天提醒）"""
        if days is None:
            days = config.COOKIE_EXPIRE_WARN_DAYS
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.utcnow() >= expires - timedelta(days=days)
        except ValueError:
            return False


class TokenStore:
    """
    AES-256-GCM 加密凭证存储
    存储目录：config.AUTH_DIR / {user_id} / {platform}_tokens.enc
    """

    def __init__(self, master_password: str = None, encrypt_key: bytes = None, user_id: str = None):
        """
        初始化存储，优先使用 encrypt_key，否则从 master_password 派生
        user_id 用于用户隔离的目录
        """
        if encrypt_key:
            assert len(encrypt_key) == 32, "加密密钥必须为 32 字节（AES-256）"
            self._key = encrypt_key
        elif master_password:
            self._key = self._derive_key(master_password)
        elif config.TOKEN_ENCRYPT_KEY:
            key_bytes = config.TOKEN_ENCRYPT_KEY.encode()
            self._key = hashlib.sha256(key_bytes).digest()
        elif config.TOKEN_MASTER_PASSWORD:
            self._key = self._derive_key(config.TOKEN_MASTER_PASSWORD)
        else:
            # 开发模式：使用固定密钥（生产环境必须设置主密码）
            import warnings
            warnings.warn("未设置加密密钥，使用默认开发密钥，生产环境请设置 TOKEN_MASTER_PASSWORD")
            self._key = self._derive_key("dev-default-password-please-change")

        # 用户隔离的目录
        if user_id and user_id != "_default":
            self._auth_dir = Path(config.AUTH_DIR) / user_id
        else:
            self._auth_dir = Path(config.AUTH_DIR)
        self._auth_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _derive_key(password: str, salt: bytes = None) -> bytes:
        """PBKDF2-HMAC-SHA256 从密码派生 256bit 密钥"""
        if salt is None:
            # 固定盐（简化版，生产环境应将盐与密文一起存储）
            salt = b"personal-ai-memory-salt-v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        return kdf.derive(password.encode())

    def _encrypt(self, data: dict) -> bytes:
        """AES-256-GCM 加密 JSON 数据"""
        plaintext = json.dumps(data, ensure_ascii=False).encode()
        nonce = os.urandom(12)  # GCM 标准 96-bit nonce
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        # 格式：nonce(12) + ciphertext
        return base64.b64encode(nonce + ciphertext)

    def _decrypt(self, data: bytes) -> dict:
        """AES-256-GCM 解密"""
        raw = base64.b64decode(data)
        nonce, ciphertext = raw[:12], raw[12:]
        aesgcm = AESGCM(self._key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode())

    def save(self, token_data: TokenData) -> None:
        """加密保存平台凭证"""
        data = {
            "platform": token_data.platform,
            "auth_mode": token_data.auth_mode,
            "access_token": token_data.access_token,
            "refresh_token": token_data.refresh_token,
            "api_key": token_data.api_key,
            "cookie": token_data.cookie,
            "sessdata": token_data.sessdata,
            "bili_jct": token_data.bili_jct,
            "dedeuserid": token_data.dedeuserid,
            "token_type": token_data.token_type,
            "scope": token_data.scope,
            "expires_at": token_data.expires_at,
            "last_refresh": token_data.last_refresh,
            "status": token_data.status,
            "extra": token_data.extra,
        }
        enc_path = self._auth_dir / f"{token_data.platform}_tokens.enc"
        enc_path.write_bytes(self._encrypt(data))

        # 保存明文状态文件（不含敏感数据）
        status_path = self._auth_dir / f"{token_data.platform}_status.json"
        status_path.write_text(json.dumps({
            "platform": token_data.platform,
            "auth_mode": token_data.auth_mode,
            "status": token_data.status,
            "expires_at": token_data.expires_at,
            "last_refresh": token_data.last_refresh,
            "scope": token_data.scope,
        }, ensure_ascii=False, indent=2))

    def load(self, platform: str) -> Optional[TokenData]:
        """加载并解密平台凭证"""
        enc_path = self._auth_dir / f"{platform}_tokens.enc"
        if not enc_path.exists():
            return None
        try:
            data = self._decrypt(enc_path.read_bytes())
            return TokenData(**data)
        except Exception as e:
            print(f"[TokenStore] 解密 {platform} 凭证失败: {e}")
            return None

    def delete(self, platform: str) -> None:
        """删除平台凭证（撤销授权）"""
        for suffix in ["_tokens.enc", "_status.json"]:
            path = self._auth_dir / f"{platform}{suffix}"
            if path.exists():
                path.unlink()

    def get_status(self, platform: str) -> Dict[str, str]:
        """读取平台连接状态（无需解密）"""
        status_path = self._auth_dir / f"{platform}_status.json"
        if not status_path.exists():
            return {"status": "disconnected"}
        return json.loads(status_path.read_text())

    def list_connected_platforms(self) -> list:
        """列出所有已连接平台"""
        result = []
        for f in self._auth_dir.glob("*_status.json"):
            try:
                status = json.loads(f.read_text())
                if status.get("status") == "connected":
                    result.append(status["platform"])
            except Exception:
                pass
        return result

    def mark_needs_reauth(self, platform: str, reason: str = "") -> None:
        """将平台标记为需要重新授权"""
        token = self.load(platform)
        if token:
            token.status = "needs_reauth"
            if reason:
                token.extra["reauth_reason"] = reason
            self.save(token)


# ── 用户隔离的 TokenStore ─────────────────────────────────────────────────────────


# 每个用户有独立的 TokenStore 实例
_token_stores: Dict[str, TokenStore] = {}


def get_token_store(user_id: str) -> TokenStore:
    """
    Get a TokenStore for the specified user.
    user_id is REQUIRED - no default, no ContextVar fallback.
    Raises ValueError if user_id is empty.
    """
    global _token_stores

    if not user_id:
        raise ValueError("get_token_store() requires explicit user_id")

    if user_id not in _token_stores:
        _token_stores[user_id] = TokenStore(user_id=user_id)
        logger.info(f"Created new TokenStore for user: {user_id}")

    return _token_stores[user_id]


def clear_user_token_store(user_id: str) -> None:
    """清除指定用户的 TokenStore 实例"""
    global _token_stores
    if user_id in _token_stores:
        del _token_stores[user_id]
        logger.info(f"Cleared TokenStore for user: {user_id}")
