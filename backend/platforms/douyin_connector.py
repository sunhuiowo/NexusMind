"""
platforms/douyin_connector.py
抖音平台连接器 - OAuth 2.0（开放平台审核模式）
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
from platforms.base_connector import BasePlatformConnector, AuthError
from auth.token_store import get_token_store
from auth.oauth_handler import get_oauth_handler

logger = logging.getLogger(__name__)

DOUYIN_API_BASE = "https://open.douyin.com"


class DouyinConnector(BasePlatformConnector):

    def __init__(self):
        self._store = get_token_store()
        self._oauth = get_oauth_handler()
        self._access_token: Optional[str] = None
        self._open_id: Optional[str] = None

    def get_platform_id(self) -> str:
        return "douyin"

    def get_platform_name(self) -> str:
        return "抖音"

    def get_auth_mode(self) -> str:
        return "oauth2"

    def get_media_type(self) -> str:
        return "video"

    def authenticate(self) -> bool:
        token_data = self._store.load("douyin")
        if not token_data or token_data.status != "connected":
            return False
        self._access_token = token_data.access_token
        self._open_id = token_data.extra.get("open_id", "")
        return bool(self._access_token)

    def is_authenticated(self) -> bool:
        if self._access_token:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._access_token = None
        self._open_id = None
        self._oauth.revoke("douyin")

    def _headers(self) -> dict:
        return {
            "access-token": self._access_token,
            "Content-Type": "application/json",
        }

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        if not self.is_authenticated():
            raise AuthError("抖音 未授权（需申请开放平台应用审核）")

        bookmarks = []
        cursor = 0
        count = min(20, limit)

        while len(bookmarks) < limit:
            try:
                resp = requests.post(
                    f"{DOUYIN_API_BASE}/video/list/",
                    headers=self._headers(),
                    json={
                        "open_id": self._open_id,
                        "cursor": cursor,
                        "count": count,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"[抖音] fetch_bookmarks 失败: {e}")
                break

            videos = data.get("data", {}).get("list", [])
            if not videos:
                break

            for video in videos:
                create_time = datetime.utcfromtimestamp(video.get("create_time", 0))
                if since and create_time < since:
                    return bookmarks

                video_id = video.get("item_id", "")
                bm = RawBookmark(
                    platform="douyin",
                    platform_id=video_id,
                    url=f"https://www.douyin.com/video/{video_id}",
                    title=video.get("title", ""),
                    bookmarked_at=create_time,
                    raw_data=video,
                )
                bookmarks.append(bm)

            has_more = data.get("data", {}).get("has_more", False)
            cursor = data.get("data", {}).get("cursor", 0)
            if not has_more:
                break

        logger.info(f"[抖音] 拉取到 {len(bookmarks)} 条收藏")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        video = bookmark.raw_data
        return RawContent(
            platform="douyin",
            platform_name="抖音",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=video.get("title", ""),
            body=video.get("title", ""),
            media_type="video",
            author=video.get("author", {}).get("nickname", ""),
            thumbnail_url=video.get("video", {}).get("cover", {}).get("url_list", [""])[0],
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "duration": video.get("duration", 0),
                "statistics": video.get("statistics", {}),
            },
        )
