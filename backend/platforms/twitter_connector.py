"""
platforms/twitter_connector.py
Twitter / X 平台连接器 - OAuth 2.0 with PKCE
拉取：书签（Bookmarks）
"""

import logging
import requests
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory.memory_schema import RawBookmark, RawContent
from platforms.base_connector import BasePlatformConnector, AuthError, RateLimitError
from auth.token_store import get_token_store
from auth.oauth_handler import get_oauth_handler

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"


class TwitterConnector(BasePlatformConnector):

    def __init__(self, user_id: str = ""):
        self._store = get_token_store(user_id)
        self._oauth = get_oauth_handler()
        self._access_token: Optional[str] = None
        self._user_id: Optional[str] = None

    def get_platform_id(self) -> str:
        return "twitter"

    def get_platform_name(self) -> str:
        return "Twitter / X"

    def get_auth_mode(self) -> str:
        return "oauth2"

    def get_media_type(self) -> str:
        return "text"

    def authenticate(self) -> bool:
        token = self._oauth.ensure_valid_token("twitter")
        if token:
            self._access_token = token
            self._user_id = self._fetch_user_id()
            return True
        return False

    def is_authenticated(self) -> bool:
        if self._access_token:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._access_token = None
        self._user_id = None
        self._oauth.revoke("twitter")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _get(self, path: str, params: dict = None) -> dict:
        if not self.is_authenticated():
            raise AuthError("Twitter 未授权")
        resp = requests.get(
            f"{TWITTER_API_BASE}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        if resp.status_code == 401:
            self._store.mark_needs_reauth("twitter", "token 失效")
            raise AuthError("Twitter token 已失效")
        if resp.status_code == 429:
            raise RateLimitError("Twitter API 限速")
        resp.raise_for_status()
        return resp.json()

    def _fetch_user_id(self) -> Optional[str]:
        try:
            data = self._get("/users/me", {"user.fields": "id,username"})
            return data.get("data", {}).get("id")
        except Exception:
            return None

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        if not self._user_id:
            self._user_id = self._fetch_user_id()
        if not self._user_id:
            logger.error("[Twitter] 无法获取用户 ID")
            return []

        bookmarks = []
        pagination_token = None
        fetched = 0

        while fetched < limit:
            params = {
                "max_results": min(100, limit - fetched),
                "tweet.fields": "created_at,author_id,text,entities,attachments",
                "expansions": "attachments.media_keys,author_id",
                "media.fields": "type,url,preview_image_url",
                "user.fields": "name,username",
            }
            if pagination_token:
                params["pagination_token"] = pagination_token

            try:
                data = self._get(f"/users/{self._user_id}/bookmarks", params)
            except Exception as e:
                logger.warning(f"[Twitter] fetch_bookmarks 失败: {e}")
                break

            tweets = data.get("data", [])
            if not tweets:
                break

            includes = data.get("includes", {})
            users_map = {u["id"]: u for u in includes.get("users", [])}

            for tweet in tweets:
                tweet_id = tweet["id"]
                created_at_str = tweet.get("created_at", "")
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    created_at = created_at.replace(tzinfo=None)
                except Exception:
                    created_at = datetime.utcnow()

                if since and created_at < since:
                    continue

                author = users_map.get(tweet.get("author_id", ""), {})
                author_name = author.get("name", "")

                bm = RawBookmark(
                    platform="twitter",
                    platform_id=tweet_id,
                    url=f"https://twitter.com/i/web/status/{tweet_id}",
                    title=tweet.get("text", "")[:100],
                    bookmarked_at=created_at,
                    raw_data={**tweet, "_author": author},
                )
                bookmarks.append(bm)
                fetched += 1

            pagination_token = data.get("meta", {}).get("next_token")
            if not pagination_token:
                break

        logger.info(f"[Twitter] 拉取到 {len(bookmarks)} 条书签")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        tweet = bookmark.raw_data
        author = tweet.get("_author", {})
        text = tweet.get("text", "")

        # 检测媒体类型
        has_media = bool(tweet.get("attachments", {}).get("media_keys"))
        media_type = "image" if has_media else "text"

        return RawContent(
            platform="twitter",
            platform_name="Twitter / X",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=text[:100] if text else bookmark.title,
            body=text,
            media_type=media_type,
            author=author.get("name", ""),
            thumbnail_url="",
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "author_username": author.get("username", ""),
                "author_id": tweet.get("author_id", ""),
                "entities": tweet.get("entities", {}),
            },
        )
