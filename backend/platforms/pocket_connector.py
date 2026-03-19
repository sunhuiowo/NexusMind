"""
platforms/pocket_connector.py
Pocket 平台连接器 - Phase 1 第一个接入平台（API 最规范、限制最少）
Pocket 使用自有 OAuth 流程（非标准 OAuth 2.0）
"""

import logging
import requests
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import RawBookmark, RawContent
from platforms.base_connector import BasePlatformConnector, AuthError, RateLimitError
from auth.token_store import get_token_store, TokenData

logger = logging.getLogger(__name__)

POCKET_API_BASE = "https://getpocket.com/v3"
POCKET_REQUEST_TOKEN_URL = f"{POCKET_API_BASE}/oauth/request"
POCKET_AUTH_URL = "https://getpocket.com/auth/authorize"
POCKET_ACCESS_TOKEN_URL = f"{POCKET_API_BASE}/oauth/authorize"


class PocketConnector(BasePlatformConnector):
    """
    Pocket 连接器
    认证模式：Pocket 自有 OAuth（request token -> 授权页 -> access token）
    """

    def __init__(self, user_id: str = ""):
        self._store = get_token_store(user_id)
        self._access_token: Optional[str] = None
        self._username: Optional[str] = None

    # ── 平台信息 ───────────────────────────────────────────────────────────────

    def get_platform_id(self) -> str:
        return "pocket"

    def get_platform_name(self) -> str:
        return "Pocket"

    def get_auth_mode(self) -> str:
        return "oauth2"

    def get_media_type(self) -> str:
        return "text"

    # ── 认证 ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """从本地存储加载 access_token"""
        token_data = self._store.load("pocket")
        if not token_data:
            return False
        if token_data.status == "needs_reauth":
            return False
        if not token_data.access_token:
            return False
        self._access_token = token_data.access_token
        self._username = token_data.extra.get("username", "")
        return True

    def is_authenticated(self) -> bool:
        if self._access_token:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._access_token = None
        self._username = None
        self._store.delete("pocket")

    def get_request_token(self, redirect_uri: str) -> Optional[str]:
        """
        Pocket OAuth Step 1: 获取 request token
        返回 request_token，供生成授权 URL 使用
        """
        if not config.POCKET_CONSUMER_KEY:
            raise AuthError("未配置 POCKET_CONSUMER_KEY")

        resp = requests.post(
            POCKET_REQUEST_TOKEN_URL,
            json={
                "consumer_key": config.POCKET_CONSUMER_KEY,
                "redirect_uri": redirect_uri,
            },
            headers={
                "Content-Type": "application/json",
                "X-Accept": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("code")

    def get_auth_url(self, request_token: str, redirect_uri: str) -> str:
        """生成 Pocket 授权页 URL"""
        from urllib.parse import urlencode
        params = urlencode({"request_token": request_token, "redirect_uri": redirect_uri})
        return f"{POCKET_AUTH_URL}?{params}"

    def complete_auth(self, request_token: str) -> bool:
        """
        Pocket OAuth Step 3: 用 request_token 换取 access_token
        用户在授权页完成授权后调用
        """
        if not config.POCKET_CONSUMER_KEY:
            raise AuthError("未配置 POCKET_CONSUMER_KEY")

        try:
            resp = requests.post(
                POCKET_ACCESS_TOKEN_URL,
                json={
                    "consumer_key": config.POCKET_CONSUMER_KEY,
                    "code": request_token,
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Accept": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"[Pocket] access_token 换取失败: {e}")
            return False

        access_token = data.get("access_token")
        username = data.get("username", "")

        if not access_token:
            return False

        token_data = TokenData(
            platform="pocket",
            auth_mode="oauth2",
            access_token=access_token,
            status="connected",
            extra={"username": username},
        )
        self._store.save(token_data)
        self._access_token = access_token
        self._username = username
        logger.info(f"[Pocket] 授权成功，用户: {username}")
        return True

    # ── 数据拉取 ───────────────────────────────────────────────────────────────

    def _api_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Accept": "application/json",
        }

    def _api_post(self, path: str, params: dict) -> dict:
        """统一 API 调用，含错误处理"""
        if not self.is_authenticated():
            raise AuthError("Pocket 未授权")

        payload = {
            **params,
            "consumer_key": config.POCKET_CONSUMER_KEY,
            "access_token": self._access_token,
        }

        resp = requests.post(
            f"{POCKET_API_BASE}{path}",
            json=payload,
            headers=self._api_headers(),
            timeout=30,
        )

        if resp.status_code == 401:
            self._store.mark_needs_reauth("pocket", "access_token 失效")
            raise AuthError("Pocket access_token 已失效，请重新授权")

        if resp.status_code == 429:
            raise RateLimitError("Pocket API 请求频率超限")

        resp.raise_for_status()
        return resp.json()

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        """
        拉取 Pocket 收藏列表
        since: 增量同步起点
        """
        params = {
            "state": "all",       # all / unread / archive
            "sort": "newest",
            "detailType": "complete",
            "count": min(limit, 30),  # Pocket 单次最多30条
        }

        if since:
            params["since"] = int(since.timestamp())

        try:
            data = self._api_post("/get", params)
        except AuthError:
            raise
        except Exception as e:
            logger.error(f"[Pocket] fetch_bookmarks 失败: {e}")
            return []

        items = data.get("list", {})
        bookmarks = []

        for item_id, item in items.items():
            # 过滤已删除
            if item.get("status") == "2":
                continue

            bookmarked_at = datetime.utcfromtimestamp(
                int(item.get("time_added", 0))
            )

            bm = RawBookmark(
                platform="pocket",
                platform_id=item_id,
                url=item.get("given_url") or item.get("resolved_url", ""),
                title=item.get("resolved_title") or item.get("given_title", ""),
                bookmarked_at=bookmarked_at,
                raw_data=item,
            )
            bookmarks.append(bm)

        logger.info(f"[Pocket] 拉取到 {len(bookmarks)} 条书签")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        """
        将 Pocket 书签 normalize 为 RawContent
        Pocket /get 已返回完整数据，无需再次请求
        """
        item = bookmark.raw_data

        # 提取正文摘要
        body = (
            item.get("excerpt", "") or
            item.get("resolved_title", "") or
            item.get("given_title", "")
        )

        # 提取标签
        tags_raw = item.get("tags", {})
        tags = list(tags_raw.keys()) if isinstance(tags_raw, dict) else []

        # 提取作者
        authors = item.get("authors", {})
        author = ""
        if isinstance(authors, dict) and authors:
            first_author = next(iter(authors.values()))
            author = first_author.get("name", "")

        # 封面图
        images = item.get("images", {})
        thumbnail_url = ""
        if isinstance(images, dict) and images:
            first_image = next(iter(images.values()))
            thumbnail_url = first_image.get("src", "")

        # 媒体类型：Pocket 主要是文章
        has_video = item.get("has_video") == "1"
        media_type = "video" if has_video else "text"

        return RawContent(
            platform="pocket",
            platform_name="Pocket",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=bookmark.title or item.get("resolved_title", ""),
            body=body,
            media_type=media_type,
            author=author,
            thumbnail_url=thumbnail_url,
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "word_count": item.get("word_count", 0),
                "time_to_read": item.get("time_to_read", 0),
                "status": item.get("status", "0"),
                "favorite": item.get("favorite", "0"),
                "tags": tags,
            },
        )
