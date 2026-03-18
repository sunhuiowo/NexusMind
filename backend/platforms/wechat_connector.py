"""
platforms/wechat_connector.py
微信收藏连接器 - API Key 模式（需企业微信权限）
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
from auth.token_store import get_token_store, TokenData

logger = logging.getLogger(__name__)

WECHAT_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WeChatConnector(BasePlatformConnector):

    def __init__(self):
        self._store = get_token_store()
        self._api_key: Optional[str] = None
        self._corp_access_token: Optional[str] = None

    def get_platform_id(self) -> str:
        return "wechat"

    def get_platform_name(self) -> str:
        return "微信收藏"

    def get_auth_mode(self) -> str:
        return "apikey"

    def get_media_type(self) -> str:
        return "text"

    def authenticate(self) -> bool:
        # 从环境变量或存储加载
        api_key = config.WECHAT_API_KEY
        if not api_key:
            token_data = self._store.load("wechat")
            if token_data:
                api_key = token_data.api_key

        if not api_key:
            logger.warning("[微信] 未配置 WECHAT_API_KEY，跳过")
            return False

        self._api_key = api_key

        # 保存到 store
        self._store.save(TokenData(
            platform="wechat",
            auth_mode="apikey",
            api_key=api_key,
            status="connected",
        ))
        return True

    def is_authenticated(self) -> bool:
        if self._api_key:
            return True
        return self.authenticate()

    def revoke(self) -> None:
        self._api_key = None
        self._store.delete("wechat")

    def fetch_bookmarks(
        self,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RawBookmark]:
        if not self.is_authenticated():
            raise AuthError("微信收藏 未配置 API Key（需企业微信权限）")

        # 企业微信收藏 API（需开放平台权限）
        try:
            resp = requests.post(
                f"{WECHAT_API_BASE}/message/get_fav_list",
                json={
                    "access_token": self._api_key,
                    "limit": min(limit, 50),
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[微信] fetch_bookmarks 失败: {e}")
            return []

        items = data.get("item_list", [])
        bookmarks = []

        for item in items:
            create_time = datetime.utcfromtimestamp(item.get("create_time", 0))
            if since and create_time < since:
                continue

            bm = RawBookmark(
                platform="wechat",
                platform_id=str(item.get("item_id", "")),
                url=item.get("url", ""),
                title=item.get("title", ""),
                bookmarked_at=create_time,
                raw_data=item,
            )
            bookmarks.append(bm)

        logger.info(f"[微信] 拉取到 {len(bookmarks)} 条收藏")
        return bookmarks

    def fetch_content(self, bookmark: RawBookmark) -> RawContent:
        item = bookmark.raw_data
        return RawContent(
            platform="wechat",
            platform_name="微信收藏",
            platform_id=bookmark.platform_id,
            url=bookmark.url,
            title=item.get("title", ""),
            body=item.get("content", "") or item.get("digest", ""),
            media_type="text",
            author=item.get("source_username", ""),
            thumbnail_url=item.get("cover", ""),
            bookmarked_at=bookmark.bookmarked_at,
            raw_metadata={
                "source_app_id": item.get("source_app_id", ""),
                "item_type": item.get("item_type", 0),
            },
        )
