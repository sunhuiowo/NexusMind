"""
platforms/youtube_connector.py
YouTube 平台连接器 - OAuth 2.0
拉取：稍后观看列表、用户收藏播放列表
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
from auth.token_store import get_token_store
from auth.oauth_handler import get_oauth_handler

logger = logging.getLogger(__name__)

YT_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeConnector(BasePlatformConnector):
    """YouTube 连接器 - OAuth 2.0"""

    def __init__(self):
        self._store = get_token_store()
        self._oauth = get_oauth_handler()
        self._access_token: Optional[str] = None

    def get_platform_id(self) -> str:
        return "youtube"

    def get_platform_name(self) -> str:
        return "YouTube"

    def get_auth_mode(self) -> str:
        return "oauth2"

    def get_media_type(self) -> str:
        return "video"

    def authenticate(self) -> bool:
        token = self._oauth.ensure_valid_token("youtube")
        if token:
            self._access_token = token
            return True
        return False

    def is_authenticated(self) -> bool:
        if self._access_token:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._access_token = None
        self._oauth.revoke("youtube")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _get(self, path: str, params: dict = None) -> dict:
        if not self.is_authenticated():
            raise AuthError("YouTube 未授权")
        resp = requests.get(
            f"{YT_API_BASE}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        if resp.status_code == 401:
            self._store.mark_needs_reauth("youtube", "token 失效")
            raise AuthError("YouTube token 已失效")
        if resp.status_code == 403:
            raise RateLimitError("YouTube API quota 超限")
        resp.raise_for_status()
        return resp.json()

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[RawBookmark]:
        """拉取稍后观看播放列表"""
        bookmarks = []
        page_token = None
        fetched = 0
        max_per_page = min(limit, 50)

        # 获取稍后观看播放列表 ID（WL 是固定 ID）
        while fetched < limit:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": "WL",
                "maxResults": max_per_page,
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                data = self._get("/playlistItems", params)
            except Exception as e:
                logger.warning(f"[YouTube] fetch_bookmarks 失败: {e}")
                break

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                video_id = snippet.get("resourceId", {}).get("videoId", "")
                if not video_id:
                    continue

                added_at_str = snippet.get("publishedAt", "")
                try:
                    added_at = datetime.fromisoformat(added_at_str.replace("Z", "+00:00"))
                    added_at = added_at.replace(tzinfo=None)
                except Exception:
                    added_at = datetime.utcnow()

                if since and added_at < since:
                    continue

                bm = RawBookmark(
                    platform="youtube",
                    platform_id=video_id,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    title=snippet.get("title", ""),
                    bookmarked_at=added_at,
                    raw_data=item,
                )
                bookmarks.append(bm)
                fetched += 1

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"[YouTube] 拉取到 {len(bookmarks)} 条收藏")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        """拉取视频详情"""
        video_id = bookmark.platform_id
        try:
            data = self._get("/videos", {
                "part": "snippet,contentDetails,statistics",
                "id": video_id,
            })
        except Exception as e:
            logger.warning(f"[YouTube] 视频详情拉取失败 {video_id}: {e}")
            # 降级：用书签已有信息
            return self._from_bookmark(bookmark)

        items = data.get("items", [])
        if not items:
            return self._from_bookmark(bookmark)

        video = items[0]
        snippet = video.get("snippet", {})
        content_details = video.get("contentDetails", {})

        # 构建描述文本
        description = snippet.get("description", "")
        channel = snippet.get("channelTitle", "")

        # 封面图（取最高清）
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("maxres", {}).get("url") or
            thumbnails.get("high", {}).get("url") or
            thumbnails.get("medium", {}).get("url") or ""
        )

        return RawContent(
            platform="youtube",
            platform_name="YouTube",
            platform_id=video_id,
            url=bookmark.url,
            title=snippet.get("title", bookmark.title),
            body=description[:5000] if description else "",  # 限制长度
            media_type="video",
            author=channel,
            thumbnail_url=thumbnail_url,
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "duration": content_details.get("duration", ""),
                "view_count": video.get("statistics", {}).get("viewCount", 0),
                "like_count": video.get("statistics", {}).get("likeCount", 0),
                "channel_id": snippet.get("channelId", ""),
                "tags": snippet.get("tags", []),
                "published_at": snippet.get("publishedAt", ""),
            },
        )

    def _from_bookmark(self, bookmark: RawBookmark) -> RawContent:
        """从书签数据降级构建 RawContent"""
        snippet = bookmark.raw_data.get("snippet", {})
        return RawContent(
            platform="youtube",
            platform_name="YouTube",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=bookmark.title,
            body=snippet.get("description", ""),
            media_type="video",
            author=snippet.get("channelTitle", ""),
            thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata=bookmark.raw_data,
        )
